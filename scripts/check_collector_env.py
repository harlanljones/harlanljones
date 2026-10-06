#!/usr/bin/env python3
"""Read-only drift check for the collector's environment contract.

Compares three sources:

  1. collector_config's schema (required/optional secret-backed env vars);
  2. the deployed Cloud Run Job's env list (secrets + plain values);
  3. image-level defaults baked into collector/Dockerfile.

The only gcloud call is `gcloud run jobs describe` — this script never writes
to GCP. It refuses to run against the agent's work identity, and always passes
the personal account/project explicitly rather than trusting the active config.

Usage:
  python3 scripts/check_collector_env.py
  python3 scripts/check_collector_env.py --account a@b --project p --region r --job j

Exit codes: 0 clean (warnings allowed), 1 drift found, 2 could not check.
"""

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from collector_config import (  # noqa: E402
    FORBIDDEN_ACCOUNT_SUFFIXES,
    GCP_ACCOUNT,
    GCP_JOB,
    GCP_PROJECT,
    GCP_REGION,
    IMAGE_ENV_DEFAULTS,
    JOB_SECRET_ENV,
    OPTIONAL_SECRET_GROUPS,
)


class CheckError(RuntimeError):
    """The environment could not be checked (as opposed to drift found)."""


@dataclass(frozen=True)
class Finding:
    level: str  # "error" (drift) or "warn" (suspicious but not fatal)
    message: str


def secret_ref(entry: dict) -> Optional[str]:
    """Secret name backing an env entry, supporting both the gcloud CLI shape
    (valueFrom.secretKeyRef.name) and the Cloud Run v2 API shape
    (valueSource.secretKeyRef.secret). None means a plain value."""
    ref = (entry.get("valueFrom") or {}).get("secretKeyRef") or {}
    if ref.get("name"):
        return ref["name"]
    ref = (entry.get("valueSource") or {}).get("secretKeyRef") or {}
    return ref.get("secret") or None


def check_job_env(entries: List[dict]) -> List[Finding]:
    findings: List[Finding] = []
    deployed: Dict[str, Optional[str]] = {}
    for entry in entries:
        name = entry.get("name")
        if name:
            deployed[name] = secret_ref(entry)

    for name, secret in JOB_SECRET_ENV.items():
        if name not in deployed:
            findings.append(Finding("error", f"job is missing required env var {name} (secret {secret})"))
        elif deployed[name] is None:
            findings.append(Finding("error", f"job sets {name} as a plain value; it must come from secret {secret}"))
        elif deployed[name] != secret:
            findings.append(Finding("error", f"job maps {name} to secret {deployed[name]}; schema says {secret}"))

    known = set(JOB_SECRET_ENV)
    for group in OPTIONAL_SECRET_GROUPS:
        known |= set(group)
        present = {name: deployed[name] for name in group if name in deployed}
        if present and len(present) != len(group):
            missing = sorted(set(group) - set(present))
            findings.append(Finding("warn", f"optional secrets are half-deployed; missing {', '.join(missing)} (expect all or none)"))
        for name, secret in present.items():
            if secret is None:
                findings.append(Finding("error", f"job sets {name} as a plain value; it must come from secret {group[name]}"))
            elif secret != group[name]:
                findings.append(Finding("error", f"job maps {name} to secret {secret}; schema says {group[name]}"))
    for name in sorted(set(deployed) - known):
        secret = deployed[name]
        if secret:
            findings.append(Finding("warn", f"undeclared secret-backed env var {name} (secret {secret})"))
        else:
            findings.append(Finding("warn", f"undeclared plain env var {name} on the job"))
    return findings


def parse_dockerfile_env(text: str) -> Dict[str, str]:
    """KEY=VALUE pairs from ENV instructions, including backslash continuations."""
    values: Dict[str, str] = {}
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if line.startswith("ENV "):
            chunk = line[len("ENV "):]
            while chunk.endswith("\\") and index + 1 < len(lines):
                index += 1
                chunk = chunk[:-1] + " " + lines[index].strip()
            for token in chunk.split():
                key, sep, value = token.partition("=")
                if sep:
                    values[key] = value.strip('"').strip("'")
        index += 1
    return values


def check_image_env(dockerfile_values: Dict[str, str]) -> List[Finding]:
    findings: List[Finding] = []
    for name, expected in IMAGE_ENV_DEFAULTS.items():
        actual = dockerfile_values.get(name)
        if actual is None:
            findings.append(Finding("error", f"collector/Dockerfile does not set {name} (schema default {expected})"))
        elif actual != expected:
            findings.append(Finding("error", f"collector/Dockerfile {name}={actual} does not match schema default {expected}"))
    return findings


def extract_container_env(job_json: dict) -> List[dict]:
    node = job_json
    for key in ("spec", "template", "spec", "template", "spec", "containers"):
        if not isinstance(node, dict) or key not in node:
            raise CheckError("unexpected `gcloud run jobs describe` shape; expected spec.template.spec.template.spec.containers")
        node = node[key]
    if not isinstance(node, list) or not node:
        raise CheckError("job has no container spec")
    env = node[0].get("env") or []
    if not isinstance(env, list):
        raise CheckError("container env is not a list")
    return env


def gcloud_command() -> List[str]:
    exe = shutil.which("gcloud")
    if exe:
        return [exe]
    if shutil.which("mise"):
        return ["mise", "exec", "gcloud@585.0.0", "--", "gcloud"]
    raise CheckError("gcloud not found (install the SDK or mise)")


def run_describe(account: str, project: str, region: str, job: str) -> dict:
    """The one and only GCP call: a read-only job description."""
    lowered = account.lower()
    if any(lowered.endswith(suffix) for suffix in FORBIDDEN_ACCOUNT_SUFFIXES):
        raise CheckError(f"refusing to probe personal resources with work account {account}")
    cmd = [
        *gcloud_command(), "run", "jobs", "describe", job,
        f"--region={region}", f"--project={project}", f"--account={account}", "--format=json",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True)
    except OSError as exc:
        raise CheckError(f"could not run gcloud: {exc}") from exc
    if proc.returncode != 0:
        raise CheckError(f"gcloud run jobs describe failed: {proc.stderr.strip()[:300]}")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise CheckError(f"could not parse gcloud output: {exc}") from exc


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--account", default=GCP_ACCOUNT, help="personal account, never the work identity")
    parser.add_argument("--project", default=GCP_PROJECT)
    parser.add_argument("--region", default=GCP_REGION)
    parser.add_argument("--job", default=GCP_JOB)
    parser.add_argument("--dockerfile", type=Path,
                        default=Path(__file__).resolve().parent.parent / "collector" / "Dockerfile")
    args = parser.parse_args(argv)

    print(f"Read-only drift check: {args.job} ({args.project}/{args.region}) as {args.account}")
    findings: List[Finding] = []
    try:
        job_json = run_describe(args.account, args.project, args.region, args.job)
        entries = extract_container_env(job_json)
    except CheckError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2
    findings += check_job_env(entries)
    print(f"Checked {len(entries)} deployed env var(s); no writes performed")

    try:
        dockerfile = args.dockerfile.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"[ERROR] cannot read {args.dockerfile}: {exc}", file=sys.stderr)
        return 2
    findings += check_image_env(parse_dockerfile_env(dockerfile))

    for finding in findings:
        stream = sys.stderr if finding.level == "error" else sys.stdout
        print(f"[{finding.level.upper()}] {finding.message}", file=stream)
    errors = sum(1 for f in findings if f.level == "error")
    warnings = len(findings) - errors
    if errors:
        print(f"DRIFT: {errors} error(s), {warnings} warning(s)")
        return 1
    print(f"OK: no drift ({warnings} warning(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
