#!/usr/bin/env python3
"""
Renders the static profile header as an animated SVG hero banner.

The banner is the page's "above the fold": a shader-style night-stadium
background (turbulence-displaced aurora blobs, drifting via SMIL + film
grain + a faint infield-diamond motif) under a strict left-axis type
ramp — eyebrow, name, tagline, capability chips. Identity details change
rarely, so this is a manual/one-off generator; edit the constants below,
re-run, and commit the result to the `profile-cards` branch.

Motion lives only in the background layers (SMIL <animate>/<animateTransform>
runs inside GitHub's camo-proxied <img>); every text node is static for
readability, and every filter is decorative — if a renderer drops filters
the gradient field and type still render.
"""

import argparse
import os
import sys
from typing import Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from svg_cards import (  # noqa: E402
    BORDER,
    FONT_FAMILY,
    MUTED,
    PAD_X,
    TEXT,
    esc,
    text_width,
)

NAME = "Harlan Jones"
TAGLINE = "Building PrimeIQ.ai • Baseball Enthusiast • Software Developer"
BYLINE = "San Francisco Bay Area · Boston University"
CHIPS = [
    ("Software Development", "#58a6ff"),
    ("Baseball & Sports Analytics", "#e3b341"),
    ("ML & Data Engineering", "#a371f7"),
]

W, H = 900, 320


def _chip(x: float, y: float, label: str, accent: str) -> Tuple[float, str]:
    """Outlined chip with a colored dot. Returns (next_x, svg_fragment)."""
    h = 26
    dot_pad, text_pad = 11, 21
    w = text_pad + text_width(label, 11.5, bold=True) + 14
    svg = (
        f'<g transform="translate({x:.1f},{y:.1f})">'
        f'<rect width="{w:.1f}" height="{h}" rx="{h / 2:.1f}" fill="#ffffff" fill-opacity="0.04" '
        f'stroke="{BORDER}" stroke-width="1"/>'
        f'<circle cx="{dot_pad}" cy="{h / 2:.1f}" r="3" fill="{accent}"/>'
        f'<text x="{text_pad}" y="{h / 2 + 4:.1f}" font-size="11.5" font-weight="600" '
        f'fill="{TEXT}" font-family="{FONT_FAMILY}">{esc(label)}</text>'
        f"</g>"
    )
    return x + w + 10, svg


def render() -> str:
    chips_x, chip_y = float(PAD_X), 208.0
    chip_frags = []
    for label, accent in CHIPS:
        chips_x, frag = _chip(chips_x, chip_y, label, accent)
        chip_frags.append(frag)

    edge = (
        '<linearGradient id="hbEdge" x1="0" y1="0" x2="1" y2="0.55">'
        '<stop offset="0" stop-color="#3fb950" stop-opacity="0.9"/>'
        '<stop offset="0.45" stop-color="#58a6ff" stop-opacity="0.55"/>'
        f'<stop offset="0.8" stop-color="{BORDER}" stop-opacity="1"/>'
        "</linearGradient>"
    )
    blob_grads = "".join(
        f'<radialGradient id="hb{key}">'
        f'<stop offset="0" stop-color="{color}" stop-opacity="{peak}"/>'
        f'<stop offset="1" stop-color="{color}" stop-opacity="0"/>'
        "</radialGradient>"
        for key, color, peak in (
            ("Emerald", "#2ea043", 0.55),
            ("Blue", "#1f6feb", 0.45),
            ("Clay", "#f78166", 0.34),
            ("Amber", "#e3b341", 0.26),
        )
    )

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">
<defs>
{edge}
{blob_grads}
<linearGradient id="hbFade" x1="0" y1="0" x2="0" y2="1">
<stop offset="0" stop-color="#0d1117" stop-opacity="0"/>
<stop offset="1" stop-color="#0d1117" stop-opacity="0.9"/>
</linearGradient>
<filter id="hbWobble" x="-25%" y="-25%" width="150%" height="150%">
<feTurbulence type="fractalNoise" baseFrequency="0.011 0.019" numOctaves="2" seed="8" result="noise">
<animate attributeName="baseFrequency" dur="24s" values="0.011 0.019;0.015 0.026;0.011 0.019" repeatCount="indefinite"/>
</feTurbulence>
<feDisplacementMap in="SourceGraphic" in2="noise" scale="52" xChannelSelector="R" yChannelSelector="G"/>
<feGaussianBlur stdDeviation="11"/>
</filter>
<filter id="hbGrain" x="0" y="0" width="100%" height="100%">
<feTurbulence type="fractalNoise" baseFrequency="0.8" numOctaves="2" seed="3"/>
<feColorMatrix type="matrix" values="0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  0 0 0 0.12 0"/>
</filter>
<clipPath id="hbClip"><rect x="0.5" y="0.5" width="{W - 1}" height="{H - 1}" rx="12"/></clipPath>
</defs>
<g clip-path="url(#hbClip)">
<rect width="{W}" height="{H}" fill="#0b0f16"/>
<g filter="url(#hbWobble)">
<ellipse cx="215" cy="115" rx="265" ry="150" fill="url(#hbEmerald)" opacity="0.6">
<animateTransform attributeName="transform" type="translate" values="0 0; 42 16; 0 0" dur="36s" repeatCount="indefinite"/>
</ellipse>
<ellipse cx="645" cy="70" rx="285" ry="140" fill="url(#hbBlue)" opacity="0.5">
<animateTransform attributeName="transform" type="translate" values="0 0; -52 14; 0 0" dur="44s" repeatCount="indefinite"/>
</ellipse>
<ellipse cx="540" cy="265" rx="300" ry="130" fill="url(#hbClay)" opacity="0.4">
<animateTransform attributeName="transform" type="translate" values="0 0; 30 -12; 0 0" dur="52s" repeatCount="indefinite"/>
</ellipse>
<ellipse cx="115" cy="285" rx="225" ry="110" fill="url(#hbAmber)" opacity="0.28">
<animateTransform attributeName="transform" type="translate" values="0 0; -26 -10; 0 0" dur="40s" repeatCount="indefinite"/>
</ellipse>
</g>
<g stroke="#e6edf3" fill="none" stroke-width="1.5" opacity="0.09">
<path d="M 758 78 L 856 168 L 758 258 L 660 168 Z"/>
<path d="M 758 118 L 818 168 L 758 218 L 698 168 Z" opacity="0.6"/>
</g>
<circle cx="758" cy="168" r="4" fill="#e6edf3" opacity="0.14"/>
<line x1="0" y1="292" x2="{W}" y2="252" stroke="#e6edf3" stroke-width="1" opacity="0.05"/>
<rect x="0" y="150" width="{W}" height="{H - 150}" fill="url(#hbFade)"/>
<rect width="{W}" height="{H}" filter="url(#hbGrain)" opacity="0.5"/>
</g>
<text x="{PAD_X}" y="102" font-size="10.5" font-weight="600" letter-spacing="3" fill="{MUTED}" font-family="{FONT_FAMILY}">{esc(BYLINE.upper())}</text>
<text x="{PAD_X}" y="152" font-size="44" font-weight="800" letter-spacing="0.3" fill="#f0f6fc" font-family="{FONT_FAMILY}">{esc(NAME)}</text>
<text x="{PAD_X}" y="184" font-size="15" fill="{TEXT}" font-family="{FONT_FAMILY}">{esc(TAGLINE)}</text>
{chr(10).join(chip_frags)}
<rect x="0.5" y="0.5" width="{W - 1}" height="{H - 1}" rx="12" fill="none" stroke="url(#hbEdge)" stroke-width="1"/>
</svg>
'''


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
