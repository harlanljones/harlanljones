#!/usr/bin/env python3
"""
Renders the "Skills in Practice" card: 3 categories x top 5 skills, each
drawn as a Baseball Savant percentile bubble for its wRP (weighted Reps
Practiced).

The weekly store (scripts/data/skill_weeks.json) is produced by the nightly
GCP collector (collect_mirrors.py), which reads full diffs from local
mirrors of every repo I own. This module owns the store shape, the stat
derivation, and the card; `main` re-renders from the store for local tweaks.

Display wRP is recency-weighted over the last 4 weeks (1, .6, .36, .22); the
bubble is its percentile among every skill's 4-week wRP over the last 26
weeks — a league made of my own skill-weeks.
"""

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta
from typing import Dict, List, Tuple
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sabermetrics import percentile, savant_color, weighted_recent  # noqa: E402
from skill_signals import CATEGORIES, SKILL_CATEGORY  # noqa: E402
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
    truncate,
    write_theme_pair,
)

PACIFIC = ZoneInfo("America/Los_Angeles")
DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "skill_weeks.json")
RECENT_WEEKS = 4
LEAGUE_WEEKS = 26
KEEP_WEEKS = 52
CATEGORY_ACCENTS = {CATEGORIES[0]: ACCENT_BLUE, CATEGORIES[1]: ACCENT_GREEN, CATEGORIES[2]: ACCENT_ORANGE}


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def week_record(commits: List[Tuple[str, Dict[str, float], int]]) -> Dict:
    """One week's store entry from (repo, {skill: reps}, file_count) per
    commit. Repo names are only counted, never stored: the store is public."""
    skills: Dict[str, float] = {}
    for _, reps, _ in commits:
        for name, value in reps.items():
            skills[name] = skills.get(name, 0.0) + value
    return {
        "skills": {k: round(v, 2) for k, v in sorted(skills.items(), key=lambda kv: -kv[1])},
        "commits": len(commits),
        "diffs": sum(n for _, _, n in commits),
        "repos": len({repo for repo, _, _ in commits}),
    }


def load_store(path: str) -> Dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"weeks": {}}


# ---------------------------------------------------------------------------
# Stat derivation
# ---------------------------------------------------------------------------

def rolling_wrp(weeks: Dict[str, Dict], end: date) -> Dict[str, float]:
    """Skill -> recency-weighted wRP over the RECENT_WEEKS weeks ending at `end`."""
    series: Dict[str, List[float]] = {}
    for back in range(RECENT_WEEKS):
        wk = (end - timedelta(weeks=back)).isoformat()
        for name, reps in ((weeks.get(wk) or {}).get("skills") or {}).items():
            series.setdefault(name, [0.0] * RECENT_WEEKS)[back] = reps
    return {name: weighted_recent(vals) for name, vals in series.items()}


def skill_board(store: Dict, current: date) -> Tuple[Dict[str, List[Tuple[str, float, int]]], Dict]:
    """Category -> top 5 (skill, wRP, percentile), plus summary counts."""
    weeks = store.get("weeks") or {}
    now_wrp = rolling_wrp(weeks, current)
    league: List[float] = []
    for back in range(LEAGUE_WEEKS):
        league.extend(v for v in rolling_wrp(weeks, current - timedelta(weeks=back)).values() if v > 0)

    board: Dict[str, List[Tuple[str, float, int]]] = {c: [] for c in CATEGORIES}
    for name, value in sorted(now_wrp.items(), key=lambda kv: -kv[1]):
        cat = SKILL_CATEGORY.get(name)
        if cat and value > 0 and len(board[cat]) < 5:
            board[cat].append((name, value, percentile(value, league)))

    recent = [weeks.get((current - timedelta(weeks=b)).isoformat()) or {} for b in range(RECENT_WEEKS)]
    summary = {
        "commits": sum(int(w.get("commits") or 0) for w in recent),
        "diffs": sum(int(w.get("diffs") or 0) for w in recent),
        "league": len(league),
    }
    return board, summary


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _bubble_row(x: float, y: float, width: float, name: str, value: float, pct: int) -> str:
    """Savant percentile row: name, track, filled segment to the bubble."""
    name_w = 122
    value_w = 30
    track_x = x + name_w
    track_w = width - name_w - value_w - 12
    r = 10.5
    cy = y + 12
    bx = track_x + r + (track_w - 2 * r) * pct / 100
    color = savant_color(pct)
    mid = track_x + track_w / 2
    return (
        f'<g><title>{esc(name)}: {value:.1f} wRP ({pct}th percentile)</title>'
        f'<text x="{x:.1f}" y="{cy + 4:.1f}" font-size="11.5" fill="{TEXT}" '
        f'font-family="{FONT_FAMILY}">{esc(truncate(name, 11.5, name_w - 8))}</text>'
        f'<line x1="{track_x:.1f}" y1="{cy:.1f}" x2="{track_x + track_w:.1f}" y2="{cy:.1f}" '
        f'stroke="{BORDER}" stroke-width="4" stroke-linecap="round"/>'
        f'<line x1="{mid:.1f}" y1="{cy - 6:.1f}" x2="{mid:.1f}" y2="{cy + 6:.1f}" stroke="{BORDER}" stroke-width="1"/>'
        f'<line x1="{track_x:.1f}" y1="{cy:.1f}" x2="{bx:.1f}" y2="{cy:.1f}" '
        f'stroke="{color}" stroke-opacity="0.55" stroke-width="4" stroke-linecap="round"/>'
        f'<circle cx="{bx:.1f}" cy="{cy:.1f}" r="{r}" fill="{color}"/>'
        f'<text x="{bx:.1f}" y="{cy + 3.8:.1f}" font-size="10.5" font-weight="800" fill="#ffffff" '
        f'text-anchor="middle" font-family="{FONT_FAMILY}">{pct}</text>'
        f'<text x="{x + width:.1f}" y="{cy + 4:.1f}" font-size="10" fill="{MUTED}" '
        f'text-anchor="end" font-family="{FONT_FAMILY}">{value:.1f}</text>'
        f'</g>'
    )


def render(board: Dict[str, List[Tuple[str, float, int]]], summary: Dict, current: date) -> str:
    gap = 28
    col_w = (CARD_WIDTH - PAD_X * 2 - gap * 2) / 3
    row_h = 30
    frags = []
    top = 8.0
    for c, cat in enumerate(CATEGORIES):
        x = PAD_X + c * (col_w + gap)
        frags.append(
            f'<text x="{x:.1f}" y="{top + 12:.1f}" font-size="13" font-weight="700" '
            f'fill="{CATEGORY_ACCENTS[cat]}" font-family="{FONT_FAMILY}">{esc(cat)}</text>'
            f'<text x="{x + col_w:.1f}" y="{top + 12:.1f}" font-size="9" font-weight="700" letter-spacing="1.2" '
            f'text-anchor="end" fill="{MUTED}" font-family="{FONT_FAMILY}">wRP</text>'
        )
        rows = board.get(cat) or []
        if not rows:
            frags.append(
                f'<text x="{x:.1f}" y="{top + 40:.1f}" font-size="11.5" fill="{MUTED}" '
                f'font-family="{FONT_FAMILY}">No reps detected in the last {RECENT_WEEKS} weeks.</text>'
            )
        for i, (name, value, pct) in enumerate(rows):
            frags.append(_bubble_row(x, top + 22 + i * row_h, col_w, name, value, pct))
    body_bottom = top + 22 + 5 * row_h + 8

    # Scale key: cold -> avg -> hot, the Savant reading guide.
    key_y = body_bottom + 6
    key = [(1, "cold"), (50, "avg"), (99, "hot")]
    kx = PAD_X
    for pct, label in key:
        frags.append(
            f'<circle cx="{kx + 6:.1f}" cy="{key_y:.1f}" r="6" fill="{savant_color(pct)}"/>'
            f'<text x="{kx + 16:.1f}" y="{key_y + 3.5:.1f}" font-size="9.5" fill="{MUTED}" '
            f'font-family="{FONT_FAMILY}">{pct} {label}</text>'
        )
        kx += 70
    frags.append(
        f'<text x="{CARD_WIDTH - PAD_X:.1f}" y="{key_y + 3.5:.1f}" font-size="9.5" fill="{MUTED}" text-anchor="end" '
        f'font-family="{FONT_FAMILY}">bubble = wRP percentile vs {summary["league"]:,} of my own skill-weeks '
        f'(26w) · wRP defined in Glossary</text>'
    )
    subtitle = (
        f"wRP percentile · last {RECENT_WEEKS} weeks, recency-weighted · "
        f"{summary['commits']:,} commits, {summary['diffs']:,} file diffs read · week of {current.strftime('%b %-d')}"
    )
    return card_shell("Skills in Practice", subtitle, "\n".join(frags), key_y + 8, accent=ACCENT_PURPLE)


def main() -> None:
    parser = argparse.ArgumentParser(description="Render skills.svg from the weekly skill store.")
    parser.add_argument("--store", default=DEFAULT_STORE)
    parser.add_argument("--out", default="skills.svg")
    args = parser.parse_args()

    current = week_start(datetime.now(PACIFIC).date())
    board, summary = skill_board(load_store(args.store), current)
    for path in write_theme_pair(args.out, render(board, summary, current)):
        print(f"[OK] Wrote {path}")


if __name__ == "__main__":
    main()
