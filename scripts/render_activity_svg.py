#!/usr/bin/env python3
"""
GitHub Activity card generator (replaces the third-party streak-stats and
profile-summary-card graphics with cards rendered in the same house style as
skills/projects/weekly-highlights).

  activity.svg       stat tiles (incl. Pace+) + trailing-30-day bars + 7-day
                     average, from the GraphQL contributionsCollection calendar.
                     Rendered by the daily `activity-cards.yml` workflow.
  commit-rhythm.svg  language share with Lang+, commits by hour, language lanes.
                     Rendered by the nightly GCP collector (collect_mirrors.py)
                     from full local diffs of every repo; this module only owns
                     the drawing (render_rhythm_card) and lang_plus.
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
from sabermetrics import plus_stat, rate_plus  # noqa: E402
from svg_cards import (  # noqa: E402
    ACCENT_AMBER,
    BORDER,
    CARD_WIDTH,
    FONT_FAMILY,
    MUTED,
    PAD_X,
    TEXT,
    TITLE_COLOR,
    card_shell,
    esc,
    legible_lang_color,
    truncate,
    write_theme_pair,
)

PACIFIC = ZoneInfo("America/Los_Angeles")

TILE_FILL = "#161b22"
ACCENTS = ["#58a6ff", "#a371f7", "#f78166", "#3fb950", "#e3b341", "#f778ba"]

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
FALLBACK_PALETTE = ["#8250df", "#bf3989", "#0969da", "#1a7f37", "#9a6700", "#cf222e"]


def lang_color(name: str) -> str:
    if name in LANGUAGE_COLORS:
        return legible_lang_color(LANGUAGE_COLORS[name])
    idx = sum(ord(c) for c in name) % len(FALLBACK_PALETTE)
    return FALLBACK_PALETTE[idx]


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------

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


def lang_plus(season: List[Tuple[str, int]], recent: Dict[str, int]) -> Dict[str, int]:
    """Lang+: a language's 30-day share of commits vs its 12-month share, 100 =
    normal usage. Split shares regress toward the season share (sabermetrics.PLUS_PRIOR)."""
    season_total = sum(c for _, c in season)
    recent_total = sum(recent.values())
    return {
        name: plus_stat(recent.get(name, 0), recent_total, count, season_total)
        for name, count in season
    }


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


def render_last30_days(days: Dict[date, int], x: float, y: float, max_width: float) -> Tuple[str, float]:
    """Last-30-days contribution chart: rounded vertical bars plus a 7-day
    moving-average trend line. Deliberately unlike GitHub's default
    contribution grid. Returns (svg_fragment, height)."""
    today = datetime.now(PACIFIC).date()
    dates = [today - timedelta(days=29 - i) for i in range(30)]
    values = [int(days.get(d, 0) or 0) for d in dates]
    total = sum(values)
    avg = total / 30 if values else 0.0

    title_y = y + 12
    frags = [
        f'<text x="{x:.1f}" y="{title_y:.1f}" font-size="13" font-weight="700" '
        f'fill="{TITLE_COLOR}" font-family="{FONT_FAMILY}">Last 30 days</text>',
        f'<text x="{x + max_width:.1f}" y="{title_y:.1f}" font-size="11" fill="{MUTED}" '
        f'text-anchor="end" font-family="{FONT_FAMILY}">{total:,} contributions · {avg:.1f}/day</text>',
    ]

    top = y + 26
    chart_h = 96
    baseline = top + chart_h
    axis_w = 30
    plot_x = x + axis_w
    plot_w = max_width - axis_w
    pitch = plot_w / 30
    bar_w = max(4.0, pitch - 5)
    peak = max(values) or 1

    # Horizontal gridlines at 0 / 50% / 100% of peak.
    for frac, label in ((1.0, str(peak)), (0.5, str(peak // 2 if peak > 1 else peak)), (0.0, "0")):
        gy = baseline - chart_h * frac
        frags.append(
            f'<line x1="{plot_x:.1f}" y1="{gy:.1f}" x2="{plot_x + plot_w:.1f}" y2="{gy:.1f}" '
            f'stroke="{BORDER}" stroke-width="1" stroke-dasharray="3 4" opacity="0.8"/>'
            f'<text x="{plot_x - 6:.1f}" y="{gy + 3.5:.1f}" font-size="9" fill="{MUTED}" '
            f'text-anchor="end" font-family="{FONT_FAMILY}">{esc(label)}</text>'
        )

    # Bars, intensity-scaled blue.
    for i, v in enumerate(values):
        bar_h = max(2.0 if v > 0 else 1.0, chart_h * v / peak)
        bx = plot_x + i * pitch + (pitch - bar_w) / 2
        opacity = 0.35 + 0.65 * (v / peak) if v > 0 else 0.25
        fill = ACCENTS[0] if v > 0 else "#21262d"
        frags.append(
            f'<rect x="{bx:.1f}" y="{baseline - bar_h:.1f}" width="{bar_w:.1f}" height="{bar_h:.1f}" '
            f'rx="3" fill="{fill}" opacity="{opacity:.2f}"/>'
        )

    # 7-day moving-average trend line in contrasting amber.
    pts = []
    for i in range(30):
        window_vals = values[max(0, i - 6): i + 1]
        m = sum(window_vals) / len(window_vals)
        px = plot_x + i * pitch + pitch / 2
        py = baseline - chart_h * m / peak
        pts.append(f"{px:.1f},{py:.1f}")
    frags.append(
        f'<polyline points="{" ".join(pts)}" fill="none" stroke="{ACCENTS[4]}" '
        f'stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>'
    )

    # X-axis: first day, mid-point, today.
    frags.append(
        f'<line x1="{plot_x:.1f}" y1="{baseline:.1f}" x2="{plot_x + plot_w:.1f}" y2="{baseline:.1f}" '
        f'stroke="{BORDER}" stroke-width="1"/>'
    )
    for i in (0, 14, 29):
        tx = plot_x + i * pitch + pitch / 2
        frags.append(
            f'<text x="{tx:.1f}" y="{baseline + 14:.1f}" font-size="9" fill="{MUTED}" '
            f'text-anchor="middle" font-family="{FONT_FAMILY}">{dates[i].strftime("%b %-d")}</text>'
        )
    frags.append(
        f'<text x="{plot_x + plot_w:.1f}" y="{baseline + 26:.1f}" font-size="9" fill="{MUTED}" '
        f'text-anchor="end" font-family="{FONT_FAMILY}">— 7-day avg</text>'
    )

    height = 26 + chart_h + 30
    return "\n".join(frags), height


def render_activity_card(stats: Dict, updated: datetime) -> str:
    days = flatten_calendar(stats)
    current_streak, longest_streak = compute_streaks(days)
    commits = int(stats.get("totalCommitContributions") or 0)
    prs = int(stats.get("totalPullRequestContributions") or 0)
    repos = int(stats.get("totalRepositoriesWithContributedCommits") or 0)
    today = datetime.now(PACIFIC).date()
    last30 = sum(v for d, v in days.items() if d > today - timedelta(days=30))
    pace = rate_plus(last30, 30, sum(days.values()), max(1, len(days)))

    tiles = [
        (f"{commits:,}", "Commits", ACCENTS[0]),
        (f"{prs:,}", "Pull Requests", ACCENTS[1]),
        (f"{repos:,}", "Repos Contributed", ACCENTS[3]),
        (str(pace), "Pace+ (30d vs year)", ACCENTS[2]),
        (str(current_streak), "Hitting Streak (days)", ACCENTS[4]),
        (str(longest_streak), "Career Best (days)", ACCENTS[5]),
    ]

    frags = [_stat_tiles(PAD_X, 10.0, tiles, CARD_WIDTH - PAD_X * 2)]
    chart, chart_h = render_last30_days(days, PAD_X, 110.0, CARD_WIDTH - PAD_X * 2)
    frags.append(chart)
    body_height = 110.0 + chart_h - 22

    subtitle = f"Public contributions · trailing 30 days · updated {updated.strftime('%b %-d, %Y')}"
    return card_shell("GitHub Activity", subtitle, "\n".join(frags), body_height)


def _language_rows(
    x: float, y: float, width: float, langs: List[Tuple[str, int]], plus: Optional[Dict[str, int]] = None
) -> Tuple[str, float]:
    """Horizontal language share bars with a Lang+ column. Returns (svg_fragment, height used)."""
    plus = plus or {}
    frags = [
        f'<text x="{x:.1f}" y="{y + 12:.1f}" font-size="13" font-weight="700" '
        f'fill="{TITLE_COLOR}" font-family="{FONT_FAMILY}">Top Languages</text>',
        f'<text x="{x + width - 50:.1f}" y="{y + 12:.1f}" font-size="9" font-weight="700" letter-spacing="1.2" '
        f'text-anchor="end" fill="{MUTED}" font-family="{FONT_FAMILY}">SHARE</text>',
        f'<text x="{x + width:.1f}" y="{y + 12:.1f}" font-size="9" font-weight="700" letter-spacing="1.2" '
        f'text-anchor="end" fill="{MUTED}" font-family="{FONT_FAMILY}">LANG+</text>',
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
    pct_w = 92
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
            f'<text x="{x + width - 50:.1f}" y="{cy + 9:.1f}" font-size="11" fill="{MUTED}" '
            f'text-anchor="end" font-family="{FONT_FAMILY}">{pct}%</text>'
            f'<text x="{x + width:.1f}" y="{cy + 9:.1f}" font-size="11.5" font-weight="700" fill="{TEXT}" '
            f'text-anchor="end" font-family="{FONT_FAMILY}">{plus.get(name, 100)}</text>'
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


def _language_timeseries_chart(
    x: float, y: float, width: float, dates: List[date], series: Dict[str, List[int]],
    plus: Optional[Dict[str, int]] = None,
) -> Tuple[str, float]:
    """Language activity as small multiples: one lane per language, daily
    commit bars on a shared y-scale so lanes compare honestly. Overlaid lines
    were unreadable with spiky daily counts and near-identical linguist blues
    (Python vs TypeScript); lanes carry identity by name, not color alone.
    Returns (svg_fragment, height)."""
    frags = [
        f'<text x="{x:.1f}" y="{y + 12:.1f}" font-size="13" font-weight="700" '
        f'fill="{TITLE_COLOR}" font-family="{FONT_FAMILY}">Language activity · commits per day · last 30 days</text>'
    ]
    if not dates or not series:
        frags.append(
            f'<text x="{x:.1f}" y="{y + 32:.1f}" font-size="12" fill="{MUTED}" '
            f'font-family="{FONT_FAMILY}">No dated commit data for the last 30 days.</text>'
        )
        return "\n".join(frags), 48

    n = len(dates)
    names = list(series.keys())
    peak = max(max((v for vals in series.values() for v in vals), default=0), 1)
    frags.append(
        f'<text x="{x + width:.1f}" y="{y + 12:.1f}" font-size="11" fill="{MUTED}" '
        f'text-anchor="end" font-family="{FONT_FAMILY}">shared scale · tallest bar = {peak}/day</text>'
    )

    plus = plus or {}
    label_w = 104
    total_w = 140
    plot_x = x + label_w
    plot_w = width - label_w - total_w
    pitch = plot_w / n
    bar_w = max(3.0, pitch - 4)
    lane_h = 26
    lane_gap = 8
    top = y + 26

    for row, name in enumerate(names):
        vals = series[name]
        color = lang_color(name)
        lane_top = top + row * (lane_h + lane_gap)
        baseline = lane_top + lane_h
        mid_y = lane_top + lane_h / 2 + 4
        frags.append(
            f'<circle cx="{x + 4:.1f}" cy="{mid_y - 4:.1f}" r="4" fill="{color}"/>'
            f'<text x="{x + 13:.1f}" y="{mid_y:.1f}" font-size="11.5" fill="{TEXT}" '
            f'font-family="{FONT_FAMILY}">{esc(truncate(name, 11.5, label_w - 18))}</text>'
            f'<line x1="{plot_x:.1f}" y1="{baseline:.1f}" x2="{plot_x + plot_w:.1f}" y2="{baseline:.1f}" '
            f'stroke="{BORDER}" stroke-width="1"/>'
        )
        for i, v in enumerate(vals):
            if v <= 0:
                continue
            bar_h = max(2.0, lane_h * v / peak)
            bx = plot_x + i * pitch + (pitch - bar_w) / 2
            frags.append(
                f'<rect x="{bx:.1f}" y="{baseline - bar_h:.1f}" width="{bar_w:.1f}" height="{bar_h:.1f}" '
                f'rx="2" fill="{color}"/>'
            )
        frags.append(
            f'<text x="{x + width - 74:.1f}" y="{mid_y:.1f}" font-size="11" fill="{MUTED}" '
            f'text-anchor="end" font-family="{FONT_FAMILY}">{sum(vals):,} total</text>'
            f'<text x="{x + width:.1f}" y="{mid_y:.1f}" font-size="11" font-weight="700" fill="{TEXT}" '
            f'text-anchor="end" font-family="{FONT_FAMILY}">Lang+ {plus.get(name, 100)}</text>'
        )

    axis_y = top + len(names) * (lane_h + lane_gap) - lane_gap
    for i in (0, n // 2, n - 1):
        tx = plot_x + (i + 0.5) * pitch
        anchor = "middle"
        if i == 0:
            anchor, tx = "start", plot_x
        elif i == n - 1:
            anchor, tx = "end", plot_x + plot_w
        frags.append(
            f'<text x="{tx:.1f}" y="{axis_y + 14:.1f}" font-size="9" fill="{MUTED}" '
            f'text-anchor="{anchor}" font-family="{FONT_FAMILY}">{dates[i].strftime("%b %-d")}</text>'
        )
    height = axis_y + 18 - y
    return "\n".join(frags), height


def render_rhythm_card(
    langs: List[Tuple[str, int]],
    hours: Dict[int, int],
    total_commits: int,
    trend_dates: Optional[List[date]] = None,
    trend_series: Optional[Dict[str, List[int]]] = None,
    plus: Optional[Dict[str, int]] = None,
) -> str:
    col_w = (CARD_WIDTH - PAD_X * 2 - 28) / 2
    left_svg, left_h = _language_rows(PAD_X, 10.0, col_w, langs[:7], plus)
    right_x = PAD_X + col_w + 28
    right_svg, right_h = _hour_histogram(right_x, 10.0, col_w, hours)
    top_h = max(left_h, right_h)

    # Language Activity lanes: top 5 by Lang+, sorted Lang+ desc (not commit share).
    series = trend_series or {}
    plus_map = plus or {}
    top_series = dict(
        sorted(series.items(), key=lambda kv: -plus_map.get(kv[0], 100))[:5]
    )
    trend_svg, trend_h = _language_timeseries_chart(
        PAD_X, 10.0 + top_h + 18, CARD_WIDTH - PAD_X * 2, trend_dates or [], top_series, plus
    )
    body_height = top_h + 18 + trend_h

    subtitle = (f"Every repo I own, all branches · {total_commits:,} commits in the last 12 months"
                " · Lang+ in Glossary")
    return card_shell(
        "Languages & Commit Rhythm", subtitle, left_svg + "\n" + right_svg + "\n" + trend_svg, body_height,
        accent=ACCENT_AMBER,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Render the GitHub Activity SVG card.")
    parser.add_argument("--username", default="harlanljones")
    parser.add_argument("--out-dir", default=".", help="Directory for activity.svg")
    parser.add_argument("--token", default=os.getenv("GITHUB_TOKEN"))
    args = parser.parse_args()

    if not args.token:
        print("[ERROR] No GitHub token supplied (set GITHUB_TOKEN or pass --token).", file=sys.stderr)
        sys.exit(1)

    stats = fetch_contribution_stats(args.username, args.token)
    if not stats:
        print("[ERROR] Could not fetch contribution stats; aborting.", file=sys.stderr)
        sys.exit(1)

    os.makedirs(args.out_dir, exist_ok=True)
    for path in write_theme_pair(os.path.join(args.out_dir, "activity.svg"), render_activity_card(stats, datetime.now(PACIFIC))):
        print(f"[OK] Wrote {path}")


if __name__ == "__main__":
    main()
