#!/usr/bin/env python3
"""
Renders the static profile header card as SVG.

Identity details change rarely, so this is a manual/one-off generator
(like render_overview_svg.py). Edit below, re-run, and commit the result
to the `profile-cards` branch.

The shields badge links stay in README.md as HTML: SVGs served through
<img> cannot navigate, so interactive badges live outside the card.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from svg_cards import FONT_FAMILY, MUTED, PAD_X, card_shell, esc  # noqa: E402

NAME = "Harlan Jones"
TAGLINE = "Building PrimeIQ.ai • Baseball Enthusiast • Software Developer"
BYLINE = "San Francisco Bay Area · Boston University"


def render() -> str:
    body = (
        f'<text x="{PAD_X}" y="20" font-size="13" fill="{MUTED}" '
        f'font-family="{FONT_FAMILY}">{esc(BYLINE)}</text>'
    )
    return card_shell(NAME, TAGLINE, body, 30)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="header.svg")
    args = parser.parse_args()
    svg = render()
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(svg)
    print(f"[OK] Wrote {args.out}")


if __name__ == "__main__":
    main()
