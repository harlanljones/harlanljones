#!/usr/bin/env python3
"""
Profile collector: keeps bare mirrors of every repository I own (public and
private) and computes weekly skill reps from full local diffs — no search API,
no per-commit REST calls, all branches, full history.

Runs as a nightly GCP Cloud Run Job (collector/setup.sh):

  1. Restore mirrors from the state volume (a tarball on a Cloud Storage mount).
  2. List owned repos via REST, `git clone --mirror` new ones, `git fetch
     --prune` the rest, drop mirrors of repos that are gone.
  3. `git log --all -p` over the last KEEP_WEEKS weeks of my commits; each
     commit's files feed skill_signals, reps aggregate per Pacific week. The
     whole window is recomputed every run, so detector changes apply
     retroactively and there is no incremental state to drift.
  4. Render skills.svg, pipeline.svg + glossary.svg, push the store to main and the SVGs to
     profile-cards.

Privacy: private repos contribute to aggregate counts only. The published
store carries skill names and counts, never repository names.

Environment:
  GH_READ_TOKEN    fine-grained PAT, all my repos, Contents + Metadata read
  GH_WRITE_TOKEN   fine-grained PAT, harlanljones repo only, Contents write
  STATE_DIR        mounted state volume (default /mnt/state)
  AUTHOR_PATTERN   git --author regex (default: my identities + every agent/bot identity)
  DRY_RUN=1        compute + render into WORK_DIR/out, skip pushes
"""

import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterator, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import render_glossary_svg  # noqa: E402
import render_pipeline_svg  # noqa: E402
from render_skills_svg import KEEP_WEEKS, PACIFIC, render, skill_board, week_record, week_start  # noqa: E402
from sabermetrics import wrp_reps  # noqa: E402
from skill_signals import commit_skill_lines, is_noise_commit  # noqa: E402
from svg_cards import write_theme_pair  # noqa: E402

PROFILE_REPO = "harlanljones/harlanljones"
STORE_PATH = "scripts/data/skill_weeks.json"
MAX_REPO_MB = 1500
# Changed lines examined per file; credit is capped far below this anyway.
MAX_PATCH_LINES = 4000
NUMSTAT = re.compile(r"^(\d+|-)\t(\d+|-)\t(.+)$")
RECORD_SEP, FIELD_SEP = "\x1e", "\x1f"


def log(msg: str) -> None:
    print(msg, flush=True)


# ---------------------------------------------------------------------------
# GitHub + git plumbing
# ---------------------------------------------------------------------------

def gh_get(path: str, token: str) -> Optional[object]:
    req = urllib.request.Request(
        f"https://api.github.com{path}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "ProfileCollector/1.0",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:  # noqa: BLE001 - a listing hiccup must not sink the run
        log(f"[WARN] GET {path}: {e}")
        return None


def git_env(token: str) -> Dict[str, str]:
    """Auth via GIT_CONFIG_* env vars: the token never lands in a remote URL,
    a config file, or the process list."""
    basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    env = dict(os.environ)
    env.update({
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
        "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {basic}",
    })
    return env


def git(args: List[str], env: Dict[str, str], cwd: Optional[str] = None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], env=env, cwd=cwd, capture_output=True, text=True)


def owned_repos(token: str) -> List[dict]:
    repos: List[dict] = []
    for page in range(1, 6):
        batch = gh_get(f"/user/repos?affiliation=owner&per_page=100&page={page}", token)
        if not isinstance(batch, list):
            break
        repos.extend(batch)
        if len(batch) < 100:
            break
    return [r for r in repos if not r.get("fork") and (r.get("size") or 0) / 1024 <= MAX_REPO_MB]


def sync_mirrors(mirror_dir: str, repos: List[dict], env: Dict[str, str]) -> List[str]:
    """Clone/fetch every repo into mirror_dir/<name>.git. Returns synced dirs."""
    os.makedirs(mirror_dir, exist_ok=True)
    wanted = {f"{r['name']}.git": r for r in repos}
    for stale in set(os.listdir(mirror_dir)) - set(wanted):
        shutil.rmtree(os.path.join(mirror_dir, stale), ignore_errors=True)
    synced = []
    for dirname, repo in sorted(wanted.items()):
        path = os.path.join(mirror_dir, dirname)
        url = f"https://github.com/{repo['full_name']}.git"
        if os.path.isdir(path):
            res = git(["--git-dir", path, "fetch", "--prune", "--quiet", "origin"], env)
        else:
            res = git(["clone", "--mirror", "--quiet", url, path], env)
        if res.returncode == 0:
            synced.append(path)
        else:
            log(f"[WARN] sync {repo['full_name']}: {res.stderr.strip()[:200]}")
    return synced


# ---------------------------------------------------------------------------
# Diff mining
# ---------------------------------------------------------------------------

def _diff_path(header: str) -> str:
    # "diff --git a/<path> b/<path>" — take the b/ side (paths with " b/" are rare).
    idx = header.rfind(" b/")
    return header[idx + 3:] if idx != -1 else header


def iter_commits(git_dir: str, since: datetime, author_pattern: str, env: Dict[str, str]
                 ) -> Iterator[Tuple[str, datetime, str, List[dict]]]:
    """(sha, author_date, subject, files[]) for my non-merge commits on any
    branch. files[] entries match the REST shape skill_signals expects."""
    cmd = [
        "git", "--git-dir", git_dir, "log", "--all", "--no-merges", "--no-renames",
        "--extended-regexp", "--regexp-ignore-case", f"--author={author_pattern}",
        f"--since={since.isoformat()}", f"--format={RECORD_SEP}%H{FIELD_SEP}%aI{FIELD_SEP}%s",
        "--numstat", "-p", "-U0", "--no-color", "--no-ext-diff",
    ]
    proc = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            text=True, errors="replace")
    assert proc.stdout is not None

    header: Optional[Tuple[str, datetime, str]] = None
    stats: Dict[str, Tuple[int, int]] = {}
    patches: Dict[str, List[str]] = {}
    current: Optional[str] = None

    def flush():
        files = [
            {"filename": name, "additions": a, "deletions": d, "patch": "\n".join(patches.get(name, []))}
            for name, (a, d) in stats.items()
        ]
        return (header[0], header[1], header[2], files)

    for raw in proc.stdout:
        line = raw.rstrip("\n")
        if line.startswith(RECORD_SEP):
            if header:
                yield flush()
            sha, date_s, subject = (line[1:].split(FIELD_SEP) + ["", ""])[:3]
            header = (sha, datetime.fromisoformat(date_s), subject)
            stats, patches, current = {}, {}, None
            continue
        if header is None:
            continue
        if line.startswith("diff --git "):
            current = _diff_path(line)
            patches[current] = []
            continue
        if current is None:
            m = NUMSTAT.match(line)
            if m:
                a, d, name = m.groups()
                stats[name] = (0 if a == "-" else int(a), 0 if d == "-" else int(d))
            continue
        body = patches[current]
        if len(body) < MAX_PATCH_LINES and (line.startswith("+") or line.startswith("-")):
            body.append(line)
    if header:
        yield flush()
    proc.wait()


def compute_weeks(mirrors: List[str], author_pattern: str, env: Dict[str, str]) -> Dict[str, Dict]:
    current = week_start(datetime.now(PACIFIC).date())
    first = current - timedelta(weeks=KEEP_WEEKS - 1)
    since = datetime(first.year, first.month, first.day, tzinfo=PACIFIC)
    buckets: Dict[str, List[Tuple[str, Dict[str, float], int]]] = {}
    seen = set()
    for git_dir in mirrors:
        for sha, authored, subject, files in iter_commits(git_dir, since, author_pattern, env):
            if sha in seen or is_noise_commit(subject):
                continue
            seen.add(sha)
            wk = week_start(authored.astimezone(PACIFIC).date()).isoformat()
            reps = {name: wrp_reps(lines) for name, lines in commit_skill_lines(files).items()}
            buckets.setdefault(wk, []).append((os.path.basename(git_dir), reps, len(files)))
    weeks = {}
    for back in range(KEEP_WEEKS):
        wk = (current - timedelta(weeks=back)).isoformat()
        weeks[wk] = week_record(buckets.get(wk, []))
    log(f"[INFO] {len(seen)} commits across {len(mirrors)} mirrors, {KEEP_WEEKS} weeks")
    return weeks


# ---------------------------------------------------------------------------
# State + publishing
# ---------------------------------------------------------------------------

def restore_state(state_dir: str, mirror_dir: str) -> None:
    tar_path = os.path.join(state_dir, "mirrors.tar")
    if not os.path.exists(tar_path):
        log("[INFO] no saved mirrors; cold start")
        return
    with tarfile.open(tar_path) as tar:
        tar.extractall(mirror_dir, filter="tar")
    log(f"[INFO] restored {len(os.listdir(mirror_dir))} mirrors")


def save_state(state_dir: str, mirror_dir: str) -> None:
    tmp = os.path.join(state_dir, "mirrors.tar.tmp")
    with tarfile.open(tmp, "w") as tar:
        for name in sorted(os.listdir(mirror_dir)):
            tar.add(os.path.join(mirror_dir, name), arcname=name)
    os.replace(tmp, os.path.join(state_dir, "mirrors.tar"))


def publish(files: Dict[str, str], branch: str, message: str, env: Dict[str, str], work: str) -> None:
    """Commit `files` ({repo path: local source}) onto `branch` and push,
    re-cloning and retrying on a non-fast-forward."""
    for attempt in range(1, 4):
        checkout = tempfile.mkdtemp(dir=work, prefix=f"{branch}-")
        res = git(["clone", "--depth", "1", "--branch", branch, "--quiet",
                   f"https://github.com/{PROFILE_REPO}.git", checkout], env)
        if res.returncode != 0:
            raise RuntimeError(f"clone {branch}: {res.stderr.strip()}")
        for dest, src in files.items():
            os.makedirs(os.path.dirname(os.path.join(checkout, dest)) or checkout, exist_ok=True)
            shutil.copyfile(src, os.path.join(checkout, dest))
        git(["add", *files], env, checkout)
        if git(["diff", "--cached", "--quiet"], env, checkout).returncode == 0:
            log(f"[INFO] {branch}: no changes")
            return
        git(["-c", "user.name=profile-collector", "-c", "user.email=collector@profile.invalid",
             "commit", "--quiet", "-m", message], env, checkout)
        if git(["push", "--quiet", "origin", f"HEAD:{branch}"], env, checkout).returncode == 0:
            log(f"[OK] pushed {branch}")
            return
        log(f"[WARN] push {branch} attempt {attempt} rejected; retrying")
        time.sleep(attempt * 2)
    raise RuntimeError(f"push {branch} failed after retries")


def main() -> None:
    read_token = os.environ.get("GH_READ_TOKEN", "")
    write_token = os.environ.get("GH_WRITE_TOKEN", "")
    dry_run = os.environ.get("DRY_RUN") == "1"
    if not read_token or (not write_token and not dry_run):
        sys.exit("[ERROR] GH_READ_TOKEN and GH_WRITE_TOKEN are required (or DRY_RUN=1)")
    state_dir = os.environ.get("STATE_DIR", "/mnt/state")
    author_pattern = os.environ.get("AUTHOR_PATTERN", r"harlanljones|Harlan Jones|harlan@jolai\.com|harlan@local|\[bot\]|bot@|agent|claude|copilot|cursor")
    work = os.environ.get("WORK_DIR") or tempfile.mkdtemp(prefix="collector-")
    mirror_dir = os.path.join(work, "mirrors")
    out = os.path.join(work, "out")
    os.makedirs(mirror_dir, exist_ok=True)
    os.makedirs(out, exist_ok=True)

    read_env = git_env(read_token)
    if os.path.isdir(state_dir):
        restore_state(state_dir, mirror_dir)
    repos = owned_repos(read_token)
    log(f"[INFO] {len(repos)} owned repositories")
    mirrors = sync_mirrors(mirror_dir, repos, read_env)
    if os.path.isdir(state_dir):
        save_state(state_dir, mirror_dir)

    store = {
        "weeks": compute_weeks(mirrors, author_pattern, read_env),
        "source": "mirrors",
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    store_file = os.path.join(out, "skill_weeks.json")
    with open(store_file, "w", encoding="utf-8") as f:
        json.dump(store, f, indent=2, sort_keys=True)
        f.write("\n")

    current = week_start(datetime.now(PACIFIC).date())
    board, summary = skill_board(store, current)
    write_theme_pair(os.path.join(out, "skills.svg"), render(board, summary, current))
    write_theme_pair(os.path.join(out, "glossary.svg"), render_glossary_svg.render())
    write_theme_pair(os.path.join(out, "pipeline.svg"), render_pipeline_svg.render())
    log(f"[OK] rendered into {out}")
    if dry_run:
        return

    write_env = git_env(write_token)
    publish({STORE_PATH: store_file}, "main", "chore(skills): nightly skill reps snapshot [skip ci]", write_env, work)
    publish({name: os.path.join(out, name) for name in
             ("skills.svg", "skills-light.svg", "glossary.svg", "glossary-light.svg",
              "pipeline.svg", "pipeline-light.svg")},
            "profile-cards", "chore(skills): update Skills in Practice, pipeline, and Glossary cards", write_env, work)


if __name__ == "__main__":
    main()
