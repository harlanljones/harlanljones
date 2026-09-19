#!/usr/bin/env python3
"""
Renders the static Professional Overview card as SVG.

Overview details change rarely and aren't derived from live data, so this is
a manual/one-off generator (like render_skills_svg.py) rather than something
a cron workflow re-runs. Edit ROWS below, re-run, and commit the result to
the `profile-cards` branch.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from svg_cards import CARD_WIDTH, FONT_FAMILY, MUTED, PAD_X, TEXT, card_shell, esc, wrap_by_width  # noqa: E402

ACCENT = "#58a6ff"
LABEL_W = 118

ROWS = [
    ("Currently", "Working with PrimeIQ.ai"),
    ("Interests", "Baseball & sports analytics"),
    ("Education", "B.S. Computer Engineering, Boston University"),
    ("Location", "San Francisco Bay Area"),
    ("Connect", "linkedin.com/in/harlanljones"),
]


def render() -> str:
    max_x = CARD_WIDTH - PAD_X
    value_x = PAD_X + LABEL_W
    value_w = max_x - value_x
    frags = []
    cy = 10.0

    for label, value in ROWS:
        frags.append(
            f'<text x="{PAD_X}" y="{cy + 13:.1f}" font-size="13" font-weight="700" '
            f'fill="{ACCENT}" font-family="{FONT_FAMILY}">{esc(label)}</text>'
        )
        lines = wrap_by_width(value, 13.5, value_w)
        for line in lines:
            frags.append(
                f'<text x="{value_x}" y="{cy + 13:.1f}" font-size="13.5" fill="{TEXT}" '
                f'font-family="{FONT_FAMILY}">{esc(line)}</text>'
            )
            cy += 19
        cy += 9

    body_height = cy
    return card_shell("Professional Overview", None, "\n".join(frags), body_height)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="overview.svg")
    args = parser.parse_args()
    svg = render()
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(svg)
    print(f"[OK] Wrote {args.out}")


if __name__ == "__main__":
    main()
