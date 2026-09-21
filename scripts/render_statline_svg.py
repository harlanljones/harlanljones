#!/usr/bin/env python3
"""
Season Stat Line card: the six season numbers, all defined in the Glossary.

- FIX− is mined by the nightly collector from full local diffs and published
  in the skills store (scripts/data/skill_weeks.json); this module only reads
  the published value.
- wDC and aERA are computed by the collector (Cloudflare Pages/Workers and
  GitHub Actions) and published under the store's "season" key.
- SHIP+, dOUT−, wMRG+ are computed here from the REST API over the public
  repo index (the same index the leaderboard uses).

Rendered by the weekly repo-cards workflow. Notation in the Glossary card.
"""

import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.request
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sabermetrics import aera_color, weighted_recent  # noqa: E402
from svg_cards import (  # noqa: E402
    ACCENT_BLUE,
    ACCENT_GREEN,
    ACCENT_ORANGE,
    ACCENT_PURPLE,
    BORDER,
    CARD_WIDTH,
    FONT_FAMILY,
    MUTED,
    PAD_X,
    TEXT,
    card_shell,
    esc,
    wrap_by_width,
    write_theme_pair,
)
from render_activity_svg import _stat_tiles  # noqa: E402

API = "https://api.github.com"
WEEK_WEIGHTS = (1.0, 0.6, 0.36, 0.22)
SHIP_DAYS = 90
PR_PAGES = 3


def gh_get(path: str, token: str) -> Optional[object]:
    req = urllib.request.Request(
        f"{API}{path}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "profile-cards-statline",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - one bad call must not sink the card
        print(f"[WARN] GET {path}: {exc}")
        return None


def parse_iso(ts: str) -> dt.datetime:
    return dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _polar(value: float, lo: float, hi: float, lower_good: bool) -> str:
    """Traffic-light accent: green at the good pole, red at the bad pole."""
    good = value <= lo if lower_good else value >= hi
    bad = value >= hi if lower_good else value <= lo
    if good:
        return ACCENT_GREEN
    if bad:
        return "#cf222e"
    return "#e3b341"


def closed_prs(full_name: str, token: str, cutoff: dt.datetime) -> List[dict]:
    """Closed PRs (newest first) newer than `cutoff`. Paginates until the
    window is covered or PR_PAGES is hit."""
    out = []
    for page in range(1, PR_PAGES + 1):
        batch = gh_get(f"/repos/{full_name}/pulls?state=closed&per_page=100&page={page}", token)
        if not isinstance(batch, list) or not batch:
            break
        for pr in batch:
            closed = (pr.get("closed_at") or "")[:10]
            if not closed:
                continue
            if parse_iso(pr["closed_at"]) < cutoff:
                return out
            out.append(pr)
        if len(batch) < 100:
            break
        time.sleep(0.05)
    return out


def latest_release_at(full_name: str, token: str) -> Optional[dt.datetime]:
    batch = gh_get(f"/repos/{full_name}/releases?per_page=1", token)
    if isinstance(batch, list) and batch and batch[0].get("published_at"):
        return parse_iso(batch[0]["published_at"])
    return None


def default_check(full_name: str, branch: str, token: str) -> Optional[str]:
    body = gh_get(f"/repos/{full_name}/actions/runs?branch={branch}&per_page=1", token)
    if isinstance(body, dict) and body.get("workflow_runs"):
        return body["workflow_runs"][0].get("conclusion")
    return None


def build(token: str, ranked: List[dict], now: dt.datetime, store_path: str) -> Dict:
    """Computes the four tiles. `ranked` is the public index with gWAR,
    pace_plus, and commits_90 (top repos enriched)."""
    cutoff_90 = now - dt.timedelta(days=SHIP_DAYS)

    shipped = active = 0
    sidelined: List[str] = []
    merged_w = [0.0] * 4
    decided_w = [0.0] * 4
    merged_n = decided_n = 0
    for r in ranked:
        full = r["full_name"]
        if r.get("commits_90", 0) > 0:
            active += 1
            rel = latest_release_at(full, token)
            if rel and rel >= cutoff_90:
                shipped += 1
        check = default_check(full, r.get("default_branch") or "main", token)
        if check == "failure":
            sidelined.append(r["name"])
        for pr in closed_prs(full, token, cutoff_90):
            back = min(3, (now - parse_iso(pr["closed_at"])).days // 7)
            decided_w[back] += 1
            decided_n += 1
            if pr.get("merged_at"):
                merged_w[back] += 1
                merged_n += 1
        time.sleep(0.05)

    ship = round(100 * shipped / active) if active else None
    wdecided = weighted_recent(decided_w, WEEK_WEIGHTS)
    merge = round(100 * weighted_recent(merged_w, WEEK_WEIGHTS) / wdecided) if wdecided > 0 else None

    try:
        with open(store_path, encoding="utf-8") as f:
            store = json.load(f)
        fix_store = store.get("fix_minus") or {}
        season = store.get("season") or {}
    except (OSError, ValueError):
        fix_store, season = {}, {}
    fix = fix_store.get("value")
    wdc, aera = season.get("wdc"), season.get("aera")

    tiles = [
        (f"{wdc:.0f}" if wdc is not None else "—", "wDC (deployments, weighted)",
         ACCENT_ORANGE if wdc is not None else MUTED),
        (f"{aera:.2f}" if aera is not None else "—", "aERA (fails per 9)",
         aera_color(aera) if aera is not None else MUTED),
        (str(fix) if fix is not None else "—", "FIX− (28d vs year)",
         _polar(fix, 90, 130, True) if fix is not None else MUTED),
        (str(ship) + "%" if ship is not None else "—", "SHIP+ (% active w/ release)",
         _polar(ship, 40, 70, False) if ship is not None else MUTED),
        (str(len(sidelined)), "dOUT− (red default checks)",
         _polar(len(sidelined), 0, 3, True)),
        (str(merge) + "%" if merge is not None else "—", "wMRG+ (merge rate 90d)",
         _polar(merge, 70, 90, False) if merge is not None else MUTED),
    ]
    note = (f"{fix_store.get('fix_28', '?')} fixes in {fix_store.get('commits_28', '?')} commits · "
            f"{shipped} of {active} active repos shipped a release · "
            f"{len(sidelined)} sidelined{': ' + ', '.join(sorted(sidelined)[:4]) if sidelined else ''} · "
            f"{merged_n} of {decided_n} PRs merged · {season.get('wdc_sub', '28-day windows')}")
    return {"tiles": tiles, "note": note}


def render(stat: Dict, date_str: str) -> str:
    max_x = CARD_WIDTH - PAD_X
    tiles = stat["tiles"]
    row_w = CARD_WIDTH - PAD_X * 2
    third = (row_w - 20) / 3
    frags = [_stat_tiles(PAD_X, 10.0, tiles[:3], row_w)]
    cy = 10.0 + 62 + 10
    # Row 2 mirrors row 1's tile geometry (3-up grid, no leaning on one row).
    frags.append(_stat_tiles(PAD_X, cy, tiles[3:], row_w))
    cy += 62 + 12
    for line in wrap_by_width(stat["note"] + f" · {date_str} · GitHub Actions", 11, max_x - PAD_X):
        frags.append(f'<text x="{PAD_X}" y="{cy + 8:.1f}" font-size="11" fill="{MUTED}" '
                      f'font-family="{FONT_FAMILY}">{esc(line)}</text>')
        cy += 15
    return card_shell("Season Stat Line", "the season on six numbers — see Glossary",
                      "\n".join(frags), cy + 8, accent=ACCENT_PURPLE)


def main() -> None:
    parser = argparse.ArgumentParser(description="Render the Season Stat Line card.")
    parser.add_argument("--username", default="harlanljones")
    parser.add_argument("--out", default="statline.svg")
    parser.add_argument("--store",
                        default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                             "data", "skill_weeks.json"))
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN", ""))
    args = parser.parse_args()
    if not args.token:
        parser.error("a GitHub token is required (--token or GITHUB_TOKEN)")

    from render_repo_cards import (  # noqa: E402 - local import avoids a cycle
        enrich_with_commits, fetch_repos, pace_plus, replacement_level, repo_runs, score_repo,
    )
    now = dt.datetime.now(dt.timezone.utc)
    repos = fetch_repos(args.username, args.token)
    repos.sort(key=lambda r: r.get("pushed_at", ""), reverse=True)
    enrich_with_commits(repos[:40], args.token)
    replacement = replacement_level([repo_runs(r, now) for r in repos])
    for r in repos:
        r["gwar"] = score_repo(r, now, replacement)
        r["pace_plus"] = pace_plus(r, now)
    ranked = sorted((r for r in repos if r["full_name"] != "harlanljones/harlanljones"),
                    key=lambda r: (-r["gwar"], -r.get("commits_90", 0), -r["stargazers_count"]))
    for path in write_theme_pair(args.out, render(build(args.token, ranked, now, args.store),
                                                  now.strftime("%b %d, %Y"))):
        print(f"[OK] Wrote {path}")


if __name__ == "__main__":
    main()
