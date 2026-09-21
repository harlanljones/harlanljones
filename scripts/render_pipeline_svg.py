#!/usr/bin/env python3
"""
Renders the "How This Page Is Built" card: every job that produces a card on
the profile, when it runs, where it runs, what it reads, and what it draws.

Static text like the Glossary; the nightly GCP collector re-renders it next
to glossary.svg. Keep JOBS in sync with .github/workflows/ and collector/.
"""

import argparse
import os
import sys
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from svg_cards import (  # noqa: E402
    ACCENT_BLUE,
    ACCENT_GREEN,
    ACCENT_ORANGE,
    BORDER,
    CARD_WIDTH,
    FONT_FAMILY,
    MUTED,
    ON_ACCENT,
    PAD_X,
    TEXT,
    card_shell,
    esc,
    wrap_by_width,
    write_theme_pair,
)
from sabermetrics import era, era_color  # noqa: E402

GCP = "GCP Cloud Run Job"
ACTIONS = "GitHub Actions"
LOCAL = "run by hand"
RUNTIME_ACCENT = {GCP: ACCENT_GREEN, ACTIONS: ACCENT_BLUE, LOCAL: MUTED}

# (cadence, job, runtime, sources, cards)
JOBS: List[Tuple[str, str, str, str, str]] = [
    ("nightly 3:15a PT", "profile-collector", GCP,
     "bare mirrors of every repo I own, full diffs on all branches",
     "Skills in Practice · Languages & Commit Rhythm · this card · Glossary"),
    ("daily", "activity-cards", ACTIONS,
     "GitHub GraphQL contribution calendar",
     "GitHub Activity · footer stamp"),
    ("daily", "mlb-birthdays", ACTIONS,
     "MLB Stats API, Baseball-Reference birthdays, Wikipedia",
     "Daily Dugout Dispatch"),
    ("weekly · Fri", "weekly-highlights", ACTIONS,
     "commit search, filtered and summarized by Gemini",
     "What I Did This Week"),
    ("weekly · Sat", "projects-sync", ACTIONS,
     "public repo index + README, summarized by Gemini",
     "Featured Projects store (summaries for the Projects card)"),
    ("weekly · Sun", "repo-cards", ACTIONS,
     "repo metadata, stars, forks, 90-day commits, featured store",
     "Projects · Repo Leaderboard · Repo Spotlight · Dev Immaculate Grid"),
    ("when edited", "header / overview", LOCAL,
     "hand-written constants in the generator scripts",
     "Header · Professional Overview"),
]



def _stat_tile(x: float, y: float, w: float, label: str, value: str, sub: str, color: str) -> str:
    return (
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="58" rx="8" fill="{BORDER}" fill-opacity="0.45"/>'
        f'<rect x="{x:.1f}" y="{y:.1f}" width="3" height="58" rx="1.5" fill="{color}"/>'
        f'<text x="{x + 14:.1f}" y="{y + 17:.1f}" font-size="9" font-weight="700" letter-spacing="1.5" '
        f'fill="{MUTED}" font-family="{FONT_FAMILY}">{esc(label)}</text>'
        f'<text x="{x + 14:.1f}" y="{y + 39:.1f}" font-size="21" font-weight="800" fill="{color}" '
        f'font-family="{FONT_FAMILY}">{esc(value)}</text>'
        f'<text x="{x + 14:.1f}" y="{y + 52:.1f}" font-size="9.5" fill="{MUTED}" '
        f'font-family="{FONT_FAMILY}">{esc(sub)}</text>'
    )


def _stats_strip(frags: List[str], stats: Dict) -> float:
    """Two Savant-style tiles under the jobs table: wDC and Actions ERA.
    Returns the extra height consumed."""
    max_x = CARD_WIDTH - PAD_X
    gap, tile_w = 14.0, (max_x - PAD_X - 14.0) / 2
    y = 6.0
    if "wdc" in stats:
        frags.append(_stat_tile(PAD_X, y, tile_w, "wDC · SEASON", f"{stats['wdc']:.0f}",
                                stats["wdc_sub"], ACCENT_ORANGE))
    if "era" in stats:
        frags.append(_stat_tile(PAD_X + tile_w + gap, y, tile_w, "ACTIONS ERA", f"{stats['era']:.2f}",
                                stats["era_sub"], era_color(stats["era"])))
    return y + 58 + 14 if stats else 0.0

def render(stats: Optional[Dict] = None) -> str:
    stats = stats or {}
    max_x = CARD_WIDTH - PAD_X
    col_job = PAD_X + 118
    col_src = col_job + 180
    col_cards = col_src + 262
    src_w = col_cards - col_src - 34
    # Text widths are estimated, not measured; keep slack on the right edge.
    cards_w = max_x - col_cards - 24
    header = [("CADENCE", PAD_X), ("JOB", col_job), ("READS", col_src), ("DRAWS", col_cards)]
    frags = [
        f'<text x="{x}" y="14" font-size="9" font-weight="700" letter-spacing="1.5" fill="{MUTED}" '
        f'font-family="{FONT_FAMILY}">{label}</text>'
        for label, x in header
    ]
    cy = 26.0
    for cadence, job, runtime, sources, cards in JOBS:
        src_lines = wrap_by_width(sources, 11, src_w)
        card_lines = wrap_by_width(cards, 11.5, cards_w)
        row_h = max(34.0, 16.0 * max(len(src_lines), len(card_lines)) + 8)
        frags.append(
            f'<line x1="{PAD_X}" y1="{cy - 6:.1f}" x2="{max_x}" y2="{cy - 6:.1f}" stroke="{BORDER}" stroke-width="1"/>'
            f'<text x="{PAD_X}" y="{cy + 11:.1f}" font-size="11" font-weight="700" fill="{TEXT}" '
            f'font-family="{FONT_FAMILY}">{esc(cadence)}</text>'
            f'<text x="{col_job}" y="{cy + 11:.1f}" font-size="12" font-weight="700" fill="{TEXT}" '
            f'font-family="{FONT_FAMILY}">{esc(job)}</text>'
            f'<circle cx="{col_job + 4}" cy="{cy + 22:.1f}" r="3.5" fill="{RUNTIME_ACCENT[runtime]}"/>'
            f'<text x="{col_job + 12}" y="{cy + 25.5:.1f}" font-size="10" fill="{MUTED}" '
            f'font-family="{FONT_FAMILY}">{esc(runtime)}</text>'
        )
        for i, line in enumerate(src_lines):
            frags.append(f'<text x="{col_src}" y="{cy + 11 + i * 16:.1f}" font-size="11" fill="{MUTED}" '
                         f'font-family="{FONT_FAMILY}">{esc(line)}</text>')
        for i, line in enumerate(card_lines):
            frags.append(f'<text x="{col_cards}" y="{cy + 11 + i * 16:.1f}" font-size="11.5" fill="{TEXT}" '
                         f'font-family="{FONT_FAMILY}">{esc(line)}</text>')
        cy += row_h + 8
    cy += _stats_strip(frags, stats) + 2
    note = ("Every card is a hand-rolled SVG (no headless browser): jobs commit dark and light variants to the "
            "profile-cards branch, and the README embeds each pair with <picture> so it follows your theme. "
            "Private repos feed aggregate stats only; their names never leave the collector.")
    for line in wrap_by_width(note, 11, max_x - PAD_X):
        frags.append(f'<text x="{PAD_X}" y="{cy + 8:.1f}" font-size="11" fill="{MUTED}" '
                     f'font-family="{FONT_FAMILY}">{esc(line)}</text>')
        cy += 15
    return card_shell("How This Page Is Built", "the jobs behind every card, when they run, and what they read",
                      "\n".join(frags), cy, accent=ACCENT_GREEN)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="pipeline.svg")
    args = parser.parse_args()
    for path in write_theme_pair(args.out, render()):
        print(f"[OK] Wrote {path}")


if __name__ == "__main__":
    main()
