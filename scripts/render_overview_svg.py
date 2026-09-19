#!/usr/bin/env python3
"""
Renders the static Professional Overview card as SVG.

Layout: a two-column info grid — accent dot + letter-spaced uppercase label
on top, value beneath, hairline separators between rows. Chunked, aligned,
and scannable rather than a flat label:value list. Details change rarely
and aren't derived from live data, so this is a manual/one-off generator;
edit GRID below, re-run, and commit the result to the `profile-cards`
branch.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from svg_cards import (  # noqa: E402
    ACCENT_AMBER,
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

# (label, value) cells laid out two per row; the final row may hold one cell.
GRID = [
    ("Currently", "Working with PrimeIQ.ai"),
    ("Website", "harlanljones.com"),
    ("Interests", "Baseball & sports analytics"),
    ("Education", "B.S. Computer Engineering, Boston University"),
    ("Location", "San Francisco Bay Area"),
    ("Connect", "linkedin.com/in/harlanljones"),
]

DOTS = [ACCENT_BLUE, "#f778ba", ACCENT_AMBER, ACCENT_GREEN, ACCENT_PURPLE, ACCENT_ORANGE]
GAP = 32
ROW_PITCH = 60


def render() -> str:
    max_x = CARD_WIDTH - PAD_X
    col_w = (max_x - PAD_X - GAP) / 2
    frags = []
    cy = 6.0
    dot_i = 0
    row_count = (len(GRID) + 1) // 2

    for row in range(row_count):
        cells = GRID[row * 2:row * 2 + 2]
        for col_i, (label, value) in enumerate(cells):
            x = PAD_X + col_i * (col_w + GAP)
            label_y = cy + 10
            frags.append(
                f'<circle cx="{x:.1f}" cy="{cy + 6.5:.1f}" r="3" fill="{DOTS[dot_i % len(DOTS)]}"/>'
                f'<text x="{x + 11:.1f}" y="{label_y:.1f}" font-size="10.5" font-weight="600" '
                f'letter-spacing="2" fill="{MUTED}" font-family="{FONT_FAMILY}">{esc(label.upper())}</text>'
            )
            for line in wrap_by_width(value, 14, col_w - 11, max_lines=2):
                frags.append(
                    f'<text x="{x + 11:.1f}" y="{cy + 33:.1f}" font-size="14" fill="{TEXT}" '
                    f'font-family="{FONT_FAMILY}">{esc(line)}</text>'
                )
            dot_i += 1
        if row < row_count - 1:
            frags.append(
                f'<line x1="{PAD_X}" y1="{cy + 45:.1f}" x2="{max_x}" y2="{cy + 45:.1f}" '
                f'stroke="{BORDER}" stroke-opacity="0.55" stroke-width="1"/>'
            )
        cy += ROW_PITCH

    body_height = cy - ROW_PITCH + 48
    return card_shell("Professional Overview", "The short version", "\n".join(frags), body_height, accent=ACCENT_BLUE)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="overview.svg")
    args = parser.parse_args()
    svg = render()
    for path in write_theme_pair(args.out, svg):
        print(f"[OK] Wrote {path}")


if __name__ == "__main__":
    main()
