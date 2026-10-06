#!/usr/bin/env python3
"""Typed environment configuration for the profile collector.

Single source of truth for the collector's environment contract:

  * what each variable means, its default, and its invariants (this module);
  * the Cloud Run Job secret/env mapping and image-level defaults, consumed by
    scripts/check_collector_env.py to detect deployment drift.

Configuration is parsed and validated once, up front: malformed environments
fail the run with every problem listed at once instead of a silent default.

Environment:
  GH_READ_TOKEN    fine-grained PAT, all my repos, Contents + Metadata read
  GH_WRITE_TOKEN   fine-grained PAT, harlanljones repo only, Contents write
                   (required unless DRY_RUN=1)
  DRY_RUN          1/true/yes/on (or 0/false/no/off) — render without pushing
  STATE_DIR        mounted state volume (default /mnt/state)
  WORK_DIR         scratch directory (default: a fresh temp dir)
  AUTHOR_PATTERN   git --author regex (default: my identities + agent bots)
  CLOUDFLARE_API_TOKEN / CLOUDFLARE_ACCOUNT_ID
                   optional pair; falls back to ~/.config/dots/cloudflare.env
  TYPESAFE_API_KEY optional TypeSafe key; enables typed Jev project judgments

Runtime dependencies: Python standard library only.
"""

from dataclasses import dataclass
import os
import re
import tempfile
from pathlib import Path
from typing import Dict, List, Mapping, Optional

# --- Deployment contract -----------------------------------------------------

GCP_PROJECT = "harlanljones-profile"
GCP_ACCOUNT = "harlanljones@gmail.com"
GCP_REGION = "us-central1"
GCP_JOB = "profile-collector"
# The agent's work identity must never be used against personal resources.
FORBIDDEN_ACCOUNT_SUFFIXES = ("@primeiq.ai",)

# Env var -> Secret Manager secret name, for Cloud Run --set-secrets.
JOB_SECRET_ENV: Dict[str, str] = {
    "GH_READ_TOKEN": "gh-read-token",
    "GH_WRITE_TOKEN": "gh-write-token",
}
# Optional groups: a group is all-or-nothing. Cloudflare creds degrade
# gracefully without the pair; TYPESAFE_API_KEY enables Jev judgments.
OPTIONAL_SECRET_GROUPS: List[Dict[str, str]] = [
    {
        "CLOUDFLARE_API_TOKEN": "cloudflare-token",
        "CLOUDFLARE_ACCOUNT_ID": "cloudflare-account",
    },
    {
        "TYPESAFE_API_KEY": "typesafe-api-key",
    },
]
# Image-level defaults baked into collector/Dockerfile.
IMAGE_ENV_DEFAULTS: Dict[str, str] = {
    "STATE_DIR": "/mnt/state",
    "WORK_DIR": "/tmp/collector",
}

DEFAULT_AUTHOR_PATTERN = (
    r"harlanljones|Harlan Jones|harlan@jolai\.com|harlan@local|agent|claude|copilot|cursor"
)
CF_ENV_FILE = Path("~/.config/dots/cloudflare.env").expanduser()

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


class ConfigError(ValueError):
    """Raised when the environment is missing or malformed."""


class Secret:
    """A credential whose repr/str never reveal the value.

    Pass `.reveal()` only at the point of use (an HTTP header, git config).
    """

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def reveal(self) -> str:
        return self._value

    def __bool__(self) -> bool:
        return bool(self._value)

    def __repr__(self) -> str:
        return "Secret('***')"

    __str__ = __repr__


@dataclass(frozen=True)
class CloudflareCreds:
    """Both halves of the Cloudflare API credentials, or nothing at all."""

    token: Secret
    account_id: str

    def __post_init__(self) -> None:
        if not self.token or not self.account_id:
            raise ConfigError("Cloudflare credentials need both a token and an account id")


@dataclass(frozen=True)
class CollectorSettings:
    """Validated collector configuration; construct directly in tests."""

    gh_read_token: Secret
    dry_run: bool
    state_dir: Path
    work_dir: Path
    author_pattern: str
    gh_write_token: Optional[Secret] = None
    cloudflare: Optional[CloudflareCreds] = None
    typesafe_api_key: Optional[Secret] = None

    def __post_init__(self) -> None:
        if not self.gh_read_token:
            raise ConfigError("GH_READ_TOKEN is required")
        if not self.dry_run and not self.gh_write_token:
            raise ConfigError("GH_WRITE_TOKEN is required unless DRY_RUN=1")

    def require_write_token(self) -> Secret:
        if self.gh_write_token is None:  # pragma: no cover - guarded above
            raise ConfigError("GH_WRITE_TOKEN is required unless DRY_RUN=1")
        return self.gh_write_token

    @classmethod
    def from_environ(
        cls,
        env: Optional[Mapping[str, str]] = None,
        cf_env_file: Optional[Path] = None,
    ) -> "CollectorSettings":
        env = os.environ if env is None else env
        errors: List[str] = []

        read_token = (env.get("GH_READ_TOKEN") or "").strip()
        if not read_token:
            errors.append("GH_READ_TOKEN is required")

        write_token = (env.get("GH_WRITE_TOKEN") or "").strip()

        dry_run = False
        raw_dry_run = env.get("DRY_RUN")
        if raw_dry_run is not None and raw_dry_run.strip():
            parsed = _parse_bool(raw_dry_run)
            if parsed is None:
                errors.append(
                    f"DRY_RUN must be a boolean (got {raw_dry_run!r}); "
                    "use 1/true/yes/on or 0/false/no/off"
                )
            else:
                dry_run = parsed
        if not write_token and not dry_run:
            errors.append("GH_WRITE_TOKEN is required unless DRY_RUN=1")

        author_pattern = env.get("AUTHOR_PATTERN") or DEFAULT_AUTHOR_PATTERN
        try:
            re.compile(author_pattern)
        except re.error as exc:
            errors.append(f"AUTHOR_PATTERN is not a valid regex: {exc}")

        cloudflare = None
        try:
            cloudflare = load_cloudflare_creds(env, cf_env_file)
        except ConfigError as exc:
            errors.append(str(exc))

        if errors:
            raise ConfigError("invalid collector environment:\n  - " + "\n  - ".join(errors))

        typesafe_key = (env.get("TYPESAFE_API_KEY") or "").strip()
        work_raw = env.get("WORK_DIR")
        return cls(
            gh_read_token=Secret(read_token),
            dry_run=dry_run,
            state_dir=Path(env.get("STATE_DIR") or IMAGE_ENV_DEFAULTS["STATE_DIR"]),
            work_dir=Path(work_raw) if work_raw else Path(tempfile.mkdtemp(prefix="collector-")),
            author_pattern=author_pattern,
            gh_write_token=Secret(write_token) if write_token else None,
            cloudflare=cloudflare,
            typesafe_api_key=Secret(typesafe_key) if typesafe_key else None,
        )


def _parse_bool(raw: str) -> Optional[bool]:
    value = raw.strip().lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    return None


def parse_env_file(path: Path) -> Dict[str, str]:
    """Parse a simple KEY=VALUE dotenv file; unreadable files yield {}."""
    values: Dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return values
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        if key:
            values[key] = value.strip().strip('"').strip("'")
    return values


def load_cloudflare_creds(
    env: Optional[Mapping[str, str]] = None,
    env_file: Optional[Path] = None,
) -> Optional[CloudflareCreds]:
    """Cloudflare creds from the environment, falling back per-key to the dots
    env file. Returns None when neither key is present; raises when only one is
    set (a half-configured pair would silently disable the deployment stats)."""
    env = os.environ if env is None else env
    values = parse_env_file(CF_ENV_FILE if env_file is None else env_file)
    token = (env.get("CLOUDFLARE_API_TOKEN") or values.get("CLOUDFLARE_API_TOKEN") or "").strip()
    account = (env.get("CLOUDFLARE_ACCOUNT_ID") or values.get("CLOUDFLARE_ACCOUNT_ID") or "").strip()
    if not token and not account:
        return None
    if not token or not account:
        missing = "CLOUDFLARE_API_TOKEN" if not token else "CLOUDFLARE_ACCOUNT_ID"
        raise ConfigError(f"Cloudflare credentials are incomplete: {missing} is not set")
    return CloudflareCreds(Secret(token), account)
