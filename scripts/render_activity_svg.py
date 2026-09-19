#!/usr/bin/env python3
"""
GitHub Activity card generator (replaces the third-party streak-stats and
profile-summary-card graphics with cards rendered in the same house style as
skills/projects/weekly-highlights).

Fetches the last 12 months of public contribution data from the GitHub API:

  GraphQL contributionsCollection
    - totals (commits, PRs, issues, repos contributed to)
    - contributionCalendar -> stat-tile streaks + 52-week heatmap
    - commitContributionsByRepository -> language commit share
  REST search/commits
    - commit authored hours -> "commits by hour" histogram (Pacific local time)

Renders two SVGs using the shared svg_cards primitives:

  activity.svg      stat tiles + contribution heatmap
  commit-rhythm.svg language bars + commit-hours histogram

The daily `activity-cards.yml` workflow runs this and commits the output to
the `profile-cards` branch.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from svg_cards import (  # noqa: E402
    BORDER,
    CARD_WIDTH,
    FONT_FAMILY,
    MUTED,
    PAD_X,
    TEXT,
    TITLE_COLOR,
    card_shell,
    esc,
    truncate,
)

PACIFIC = ZoneInfo("America/Los_Angeles")

TILE_FILL = "#161b22"
ACCENTS = ["#58a6ff", "#a371f7", "#f78166", "#3fb950", "#e3b341", "#f778ba"]

HEATMAP_SCALE = ["#161b22", "#0e4429", "#006d32", "#26a641", "#39d353"]

# Official github-linguist language colors; unknown languages fall back to a
# stable rotation of GitHub-graph palette colors.
LANGUAGE_COLORS = {
    "Python": "#3572A5",
    "TypeScript": "#3178C6",
    "JavaScript": "#f1e05a",
    "Rust": "#dea584",
    "Go": "#00ADD8",
    "C++": "#f34b7d",
    "C": "#555555",
    "C#": "#178600",
    "Java": "#b07219",
    "Kotlin": "#A97BFF",
    "Swift": "#F05138",
    "Ruby": "#701516",
    "PHP": "#4F5D95",
    "Shell": "#89e051",
    "PowerShell": "#012456",
    "Lua": "#000080",
    "HTML": "#e34c26",
    "CSS": "#563d7c",
    "SCSS": "#c6538c",
    "Vue": "#41b883",
    "Svelte": "#ff3e00",
    "Astro": "#ff5a03",
    "Jupyter Notebook": "#DA5B0B",
    "MDX": "#fcb32c",
    "Markdown": "#083fa1",
    "Dockerfile": "#384d54",
    "HCL": "#844FBA",
    "Nix": "#7e7eff",
    "Vim Script": "#199f4b",
    "Makefile": "#427819",
    "R": "#198CE7",
    "Dart": "#00B4AB",
    "Elixir": "#6e4a7e",
    "Haskell": "#5e5086",
    "Zig": "#ec915c",
    "Perl": "#0298c3",
}
FALLBACK_PALETTE = ["#6e40c9", "#bf3989", "#0969da", "#1a7f37", "#9a6700", "#cf222e"]


def lang_color(name: str) -> str:
    if name in LANGUAGE_COLORS:
        return LANGUAGE_COLORS[name]
    idx = sum(ord(c) for c in name) % len(FALLBACK_PALETTE)
    return FALLBACK_PALETTE[idx]


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------

def gh_rest(path: str, token: str) -> Optional[object]:
    url = f"https://api.github.com{path}"
    req = urllib.request.Request(url, headers={
        "User-Agent": "ActivityCardRenderer/1.0",
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"[WARN] REST request failed for {url}: {e}", file=sys.stderr)
        return None


def gh_graphql(query: str, variables: Dict, token: str) -> Optional[Dict]:
    body = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=body,
        headers={
            "User-Agent": "ActivityCardRenderer/1.0",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"[ERROR] GraphQL request failed: {e}", file=sys.stderr)
        return None
    if payload.get("errors"):
        print(f"[ERROR] GraphQL errors: {json.dumps(payload['errors'])[:500]}", file=sys.stderr)
        return None
    return payload.get("data")


CONTRIBUTIONS_QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      totalCommitContributions
      totalPullRequestContributions
      totalIssueContributions
      totalRepositoriesWithContributedCommits
      contributionCalendar {
        weeks {
          contributionDays {
            date
            contributionCount
          }
        }
      }
      commitContributionsByRepository(maxRepositories: 100) {
        contributions(first: 1) {
          totalCount
        }
        repository {
          primaryLanguage {
            name
          }
        }
      }
    }
  }
}
"""


def fetch_contribution_stats(login: str, token: str) -> Optional[Dict]:
    today = datetime.now(timezone.utc).date()
    frm = f"{today - timedelta(days=364)}T00:00:00Z"
    to = f"{today + timedelta(days=1)}T00:00:00Z"
    data = gh_graphql(
        CONTRIBUTIONS_QUERY,
        {"login": login, "from": frm, "to": to},
        token,
    )
    if not data or not data.get("user"):
        return None
    return data["user"]["contributionsCollection"]


def fetch_commit_hours(login: str, token: str, start_date: str) -> Dict[int, int]:
    """Commit counts by Pacific-local authored hour over the past year.

    Uses the commit search API (default branches of public repos), matching
    the scope the old profile-summary card used."""
    hours: Dict[int, int] = {h: 0 for h in range(24)}
    query = urllib.parse.quote(f"author:{login} author-date:>{start_date}")
    for page in range(1, 11):
        data = gh_rest(
            f"/search/commits?q={query}&sort=committer-date&order=desc&per_page=100&page={page}",
            token,
        )
        if not isinstance(data, dict):
            break
        items = data.get("items") or []
        for item in items:
            raw = (((item.get("commit") or {}).get("author")) or {}).get("date") or ""
            if not raw:
                continue
            try:
                authored = datetime.fromisoformat(raw.replace("Z", "+00:00"))
                hours[authored.astimezone(PACIFIC).hour] += 1
            except ValueError:
                continue
        if len(items) < 100:
            break
    return hours


# ---------------------------------------------------------------------------
# Derived stats
# ---------------------------------------------------------------------------

def flatten_calendar(collection: Dict) -> Dict[date, int]:
    days: Dict[date, int] = {}
    for week in (collection.get("contributionCalendar") or {}).get("weeks") or []:
        for day in week.get("contributionDays") or []:
            try:
                d = date.fromisoformat(day["date"][:10])
            except (KeyError, ValueError):
                continue
            days[d] = int(day.get("contributionCount") or 0)
    return days


def compute_streaks(days: Dict[date, int]) -> Tuple[int, int]:
    """(current, longest) streaks in days. Mirrors GitHub's convention that a
    streak alive through yesterday is still current even if today is empty."""
    today = datetime.now(PACIFIC).date()
    current = 0
    cursor = today if days.get(today, 0) > 0 else today - timedelta(days=1)
    while days.get(cursor, 0) > 0:
        current += 1
        cursor -= timedelta(days=1)

    longest = 0
    run = 0
    for d in sorted(days):
        if days[d] > 0:
            run += 1
            longest = max(longest, run)
        else:
            run = 0
    return current, longest


def language_share(collection: Dict) -> List[Tuple[str, int]]:
    """Aggregated commit counts by repository primary language, descending."""
    totals: Dict[str, int] = {}
    for entry in collection.get("commitContributionsByRepository") or []:
        repo = entry.get("repository") or {}
        lang = ((repo.get("primaryLanguage") or {}).get("name")) or ""
        if not lang:
            continue
        count = (((entry.get("contributions") or {}).get("totalCount")) or 0)
        totals[lang] = totals.get(lang, 0) + int(count)
    return sorted(totals.items(), key=lambda kv: kv[1], reverse=True)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _stat_tiles(x: float, y: float, tiles: List[Tuple[str, str, str]], total_w: float) -> str:
    """One row of stat tiles: (value, label, accent)."""
    gap = 10
    n = len(tiles)
    w = (total_w - gap * (n - 1)) / n
    height = 62
    frags = []
    for i, (value, label, accent) in enumerate(tiles):
        tx = x + i * (w + gap)
        frags.append(
            f'<g transform="translate({tx:.1f},{y:.1f})">'
            f'<rect width="{w:.1f}" height="{height}" rx="8" fill="{TILE_FILL}" stroke="{BORDER}"/>'
            f'<text x="{w / 2:.1f}" y="30" font-size="20" font-weight="700" fill="{accent}" '
            f'text-anchor="middle" font-family="{FONT_FAMILY}">{esc(value)}</text>'
            f'<text x="{w / 2:.1f}" y="48" font-size="10.5" fill="{MUTED}" '
            f'text-anchor="middle" font-family="{FONT_FAMILY}">{esc(label)}</text>'
            f"</g>"
        )
    return "\n".join(frags)


def _heatmap_level(count: int) -> int:
    if count <= 0:
        return 0
    if count <= 3:
        return 1
    if count <= 7:
        return 2
    if count <= 12:
        return 3
    return 4


def render_heatmap(days: Dict[date, int], x: float, y: float, max_width: float) -> Tuple[str, float]:
    """52-week contribution heatmap with month labels and a legend.
    Returns (svg_fragment, height)."""
    cell, gap = 13, 3
    pitch = cell + gap
    weeks: List[List[Tuple[date, int]]] = [[] for _ in range(60)]
    for d in sorted(days):
        col = (d.weekday() + 1) % 7  # Sunday-aligned columns, GitHub-style
        wk = ((d - timedelta(days=col)) - (min(days) - timedelta(days=(min(days).weekday() + 1) % 7))).days // 7
        weeks[wk].append((d, days[d]))
    # Trim leading empty columns
    first_nonempty = next((i for i, w in enumerate(weeks) if w), 0)
    weeks = [w for w in weeks[first_nonempty:] if w]

    frags = []
    month_labels: List[Tuple[float, str]] = []
    seen_months = set()
    for ci, week in enumerate(weeks):
        cx = x + ci * pitch
        for d, count in week:
            cy = y + ((d.weekday() + 1) % 7) * pitch
            fill = HEATMAP_SCALE[_heatmap_level(count)]
            frags.append(
                f'<rect x="{cx:.1f}" y="{cy:.1f}" width="{cell}" height="{cell}" rx="2.5" fill="{fill}"'
                + (' stroke="#30363d" stroke-width="0.5"' if count == 0 else "")
                + "/>"
            )
            if d.day == 1 and d.month not in seen_months:
                seen_months.add(d.month)
                month_labels.append((cx, d.strftime("%b")))

    for lx, label in month_labels:
        frags.append(
            f'<text x="{lx:.1f}" y="{y - 7:.1f}" font-size="10" fill="{MUTED}" '
            f'font-family="{FONT_FAMILY}">{esc(label)}</text>'
        )

    # Legend, right-aligned on the month-label row
    grid_w = (len(weeks) - 1) * pitch + cell
    legend_right = min(x + max_width, x + grid_w)
    more_w = len("More") * 9 * 0.54
    lx = legend_right - more_w
    frags.append(
        f'<text x="{lx:.1f}" y="{y - 7:.1f}" font-size="9" fill="{MUTED}" '
        f'font-family="{FONT_FAMILY}">More</text>'
    )
    for level in range(4, -1, -1):
        lx -= pitch
        frags.append(
            f'<rect x="{lx:.1f}" y="{y - 15:.1f}" width="{cell}" height="{cell}" rx="2.5" '
            f'fill="{HEATMAP_SCALE[level]}"'
            + (' stroke="#30363d" stroke-width="0.5"' if level == 0 else "")
            + "/>"
        )
    lx -= 4 + len("Less") * 9 * 0.54
    frags.append(
        f'<text x="{lx:.1f}" y="{y - 7:.1f}" font-size="9" fill="{MUTED}" '
        f'font-family="{FONT_FAMILY}">Less</text>'
    )

    height = 7 * pitch + 22  # grid + month-label row
    return "\n".join(frags), height


def render_activity_card(stats: Dict, updated: datetime) -> str:
    days = flatten_calendar(stats)
    current_streak, longest_streak = compute_streaks(days)
    commits = int(stats.get("totalCommitContributions") or 0)
    prs = int(stats.get("totalPullRequestContributions") or 0)
    issues = int(stats.get("totalIssueContributions") or 0)
    repos = int(stats.get("totalRepositoriesWithContributedCommits") or 0)

    tiles = [
        (f"{commits:,}", "Commits", ACCENTS[0]),
        (f"{prs:,}", "Pull Requests", ACCENTS[1]),
        (f"{issues:,}", "Issues", ACCENTS[2]),
        (f"{repos:,}", "Repos Contributed", ACCENTS[3]),
        (str(current_streak), "Current Streak (days)", ACCENTS[4]),
        (str(longest_streak), "Longest Streak (days)", ACCENTS[5]),
    ]

    frags = [_stat_tiles(PAD_X, 10.0, tiles, CARD_WIDTH - PAD_X * 2)]
    heatmap, heat_h = render_heatmap(days, PAD_X, 110.0, CARD_WIDTH - PAD_X * 2)
    frags.append(heatmap)
    body_height = 110.0 + heat_h - 22

    subtitle = f"Public contributions · last 12 months · updated {updated.strftime('%b %-d, %Y')}"
    return card_shell("GitHub Activity", subtitle, "\n".join(frags), body_height)


def _language_rows(x: float, y: float, width: float, langs: List[Tuple[str, int]]) -> Tuple[str, float]:
    """Horizontal language share bars. Returns (svg_fragment, height used)."""
    frags = [
        f'<text x="{x:.1f}" y="{y + 12:.1f}" font-size="13" font-weight="700" '
        f'fill="{TITLE_COLOR}" font-family="{FONT_FAMILY}">Top Languages</text>'
    ]
    cy = y + 24
    if not langs:
        frags.append(
            f'<text x="{x:.1f}" y="{cy + 12:.1f}" font-size="12" fill="{MUTED}" '
            f'font-family="{FONT_FAMILY}">No public commit activity in the last year.</text>'
        )
        return "\n".join(frags), cy + 24 - y
    max_count = max(c for _, c in langs) or 1
    total = sum(c for _, c in langs)
    name_w = 105
    pct_w = 42
    bar_max = width - name_w - pct_w - 14
    for name, count in langs:
        pct = round(100 * count / total)
        bar_w = max(3.0, bar_max * count / max_count)
        cy += 6
        frags.append(
            f'<text x="{x:.1f}" y="{cy + 9:.1f}" font-size="12" fill="{TEXT}" '
            f'font-family="{FONT_FAMILY}">{esc(truncate(name, 12, name_w))}</text>'
            f'<rect x="{x + name_w:.1f}" y="{cy:.1f}" width="{bar_w:.1f}" height="9" rx="3" '
            f'fill="{lang_color(name)}"/>'
            f'<text x="{x + width:.1f}" y="{cy + 9:.1f}" font-size="11" fill="{MUTED}" '
            f'text-anchor="end" font-family="{FONT_FAMILY}">{pct}%</text>'
        )
        cy += 20
    return "\n".join(frags), cy - y


def _hour_histogram(x: float, y: float, width: float, hours: Dict[int, int]) -> Tuple[str, float]:
    """24-bar commit-hours histogram (Pacific local time). Returns (svg_fragment, height used)."""
    frags = [
        f'<text x="{x:.1f}" y="{y + 12:.1f}" font-size="13" font-weight="700" '
        f'fill="{TITLE_COLOR}" font-family="{FONT_FAMILY}">Commits by Hour (Pacific)</text>'
    ]
    top = y + 26
    chart_h = 78
    baseline = top + chart_h
    pitch = width / 24
    bar_w = pitch - 5
    max_count = max(hours.values()) or 1
    hour_labels = {0: "12a", 4: "4a", 8: "8a", 12: "12p", 16: "4p", 20: "8p"}
    for h in range(24):
        bar_h = max(2.0, chart_h * hours.get(h, 0) / max_count)
        bx = x + h * pitch + (pitch - bar_w) / 2
        frags.append(
            f'<rect x="{bx:.1f}" y="{baseline - bar_h:.1f}" width="{bar_w:.1f}" height="{bar_h:.1f}" '
            f'rx="2" fill="{ACCENTS[0]}"/>'
        )
        if h in hour_labels:
            frags.append(
                f'<text x="{x + h * pitch + pitch / 2:.1f}" y="{baseline + 14:.1f}" font-size="9" '
                f'fill="{MUTED}" text-anchor="middle" font-family="{FONT_FAMILY}">{hour_labels[h]}</text>'
            )
    frags.append(
        f'<line x1="{x:.1f}" y1="{baseline:.1f}" x2="{x + width:.1f}" y2="{baseline:.1f}" '
        f'stroke="{BORDER}" stroke-width="1"/>'
    )
    return "\n".join(frags), chart_h + 26 + 20


def render_rhythm_card(langs: List[Tuple[str, int]], hours: Dict[int, int], total_commits: int) -> str:
    col_w = (CARD_WIDTH - PAD_X * 2 - 28) / 2
    left_svg, left_h = _language_rows(PAD_X, 10.0, col_w, langs[:7])
    right_x = PAD_X + col_w + 28
    right_svg, right_h = _hour_histogram(right_x, 10.0, col_w, hours)
    body_height = max(left_h, right_h)

    subtitle = f"Commit share by language and local commit time · {total_commits:,} commits in the last 12 months"
    return card_shell("Languages & Commit Rhythm", subtitle, left_svg + "\n" + right_svg, body_height)


def main() -> None:
    parser = argparse.ArgumentParser(description="Render GitHub activity SVG cards.")
    parser.add_argument("--username", default="harlanljones")
    parser.add_argument("--out-dir", default=".", help="Directory for activity.svg / commit-rhythm.svg")
    parser.add_argument("--token", default=os.getenv("GITHUB_TOKEN"))
    args = parser.parse_args()

    if not args.token:
        print("[ERROR] No GitHub token supplied (set GITHUB_TOKEN or pass --token).", file=sys.stderr)
        sys.exit(1)

    stats = fetch_contribution_stats(args.username, args.token)
    if not stats:
        print("[ERROR] Could not fetch contribution stats; aborting.", file=sys.stderr)
        sys.exit(1)

    start = (datetime.now(timezone.utc).date() - timedelta(days=364)).isoformat()
    hours = fetch_commit_hours(args.username, args.token, start)
    langs = language_share(stats)
    updated = datetime.now(PACIFIC)

    os.makedirs(args.out_dir, exist_ok=True)
    activity = render_activity_card(stats, updated)
    rhythm = render_rhythm_card(langs, hours, int(stats.get("totalCommitContributions") or 0))

    for name, svg in (("activity.svg", activity), ("commit-rhythm.svg", rhythm)):
        path = os.path.join(args.out_dir, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(svg)
        print(f"[OK] Wrote {path}")


if __name__ == "__main__":
    main()
