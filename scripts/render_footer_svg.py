#!/usr/bin/env python3
"""
Renders the profile page footer card as SVG.

Closes the page: a slim, quiet strip carrying the wordmark on the left and
the "how this page works" note on the right, so the card stack ends with a
deliberate baseline instead of trailing off. Static/one-off like the header
and overview generators; re-run and commit the result to the `profile-cards`
branch.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from svg_cards import (  # noqa: E402
    ACCENT_GREEN,
    BORDER,
    CARD_WIDTH,
    FONT_FAMILY,
    MUTED,
    esc,
    write_theme_pair,
)

W, H = CARD_WIDTH, 46
LEFT = "HARLAN JONES · SAN FRANCISCO BAY AREA"
RIGHT = "cards regenerate daily · GitHub Actions"


def render(right_text: str = RIGHT) -> str:
    edge = (
        '<linearGradient id="footEdge" x1="0" y1="0" x2="1" y2="0.9">'
        '<stop offset="0" stop-color="#58a6ff" stop-opacity="0.5"/>'
        '<stop offset="0.35" stop-color="#3fb950" stop-opacity="0.25"/>'
        f'<stop offset="0.7" stop-color="{BORDER}" stop-opacity="1"/>'
        "</linearGradient>"
    )
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">
<defs>{edge}</defs>
<rect x="0.5" y="0.5" width="{W - 1}" height="{H - 1}" rx="12" fill="#0d1117" stroke="url(#footEdge)"/>
<circle cx="24" cy="{H / 2:.0f}" r="3.5" fill="{ACCENT_GREEN}"/>
<text x="34" y="{H / 2 + 3.5:.0f}" font-size="9.5" font-weight="600" letter-spacing="2.5" fill="{MUTED}" font-family="{FONT_FAMILY}">{esc(LEFT)}</text>
<text x="{W - 24}" y="{H / 2 + 3.5:.0f}" font-size="10" fill="{MUTED}" text-anchor="end" font-family="{FONT_FAMILY}">{esc(right_text)}</text>
</svg>
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="footer.svg")
    parser.add_argument(
        "--stamp",
        default=None,
        help="Date string shown as 'last rendered <stamp> · GitHub Actions' (set by the daily workflow).",
    )
    args = parser.parse_args()
    right = f"last rendered {args.stamp} · GitHub Actions" if args.stamp else RIGHT
    svg = render(right)
    for path in write_theme_pair(args.out, svg):
        print(f"[OK] Wrote {path}")


if __name__ == "__main__":
    main()
