#!/usr/bin/env python3
"""
Shared SVG card rendering primitives for GitHub-README-embedded graphics.

GitHub's markdown sanitizer strips <style> blocks and style=/class= attributes
from raw HTML, so real CSS styling (gradients, custom colors, fonts) can only
reach a README through an <img> pointing at a generated image. These helpers
build hand-rolled SVG documents (no headless browser, no external deps) that
get committed to the `profile-cards` branch and referenced from README.md.

Text width is estimated (proportional-font heuristic), not measured, since
there's no font-metrics engine available at generation time. Wrapping widths
are kept conservative to avoid overflow.
"""

import os
import re
from typing import List, Optional, Tuple

FONT_FAMILY = "-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif"

BG = "#0d1117"
BORDER = "#30363d"
TEXT = "#c9d1d9"
MUTED = "#8b949e"
TITLE_COLOR = "#e6edf3"

CARD_WIDTH = 900
PAD_X = 24

ACCENT_BLUE = "#58a6ff"
ACCENT_GREEN = "#3fb950"
ACCENT_PURPLE = "#a371f7"
ACCENT_ORANGE = "#f78166"
ACCENT_AMBER = "#e3b341"

# Text on bright fills (pills, badges). Visually identical to the dark card
# background, but a DISTINCT token: the light-theme recolor maps card
# backgrounds to white and must never touch this value.
ON_ACCENT = "#0c0e13"


def plain_text(s: str) -> str:
    """Strips markdown link/emphasis syntax that would otherwise render as
    literal characters in an SVG <text> node (no markdown renderer there)."""
    s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)  # [label](url) -> label
    s = re.sub(r"[*_`]", "", s)
    return s


def esc(s: str) -> str:
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def text_width(s: str, font_size: float, bold: bool = False) -> float:
    """Rough proportional-font width estimate; errs wide on purpose."""
    factor = 0.62 if bold else 0.54
    return len(s) * font_size * factor


def truncate(s: str, font_size: float, max_width: float, bold: bool = False) -> str:
    if text_width(s, font_size, bold) <= max_width:
        return s
    while s and text_width(s + "...", font_size, bold) > max_width:
        s = s[:-1]
    return s.rstrip() + "..."


def wrap_by_width(s: str, font_size: float, max_width: float, bold: bool = False, max_lines: Optional[int] = None) -> List[str]:
    words = re.sub(r"\s+", " ", s.strip()).split(" ")
    lines: List[str] = []
    cur = ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if not cur or text_width(trial, font_size, bold) <= max_width:
            cur = trial
        else:
            lines.append(cur)
            cur = w
        if max_lines and len(lines) == max_lines:
            break
    if cur and (not max_lines or len(lines) < max_lines):
        lines.append(cur)
    if max_lines and len(lines) > max_lines:
        lines = lines[:max_lines]
    if max_lines and len(lines) == max_lines:
        remaining_words = words[sum(len(l.split(" ")) for l in lines):]
        if remaining_words:
            lines[-1] = truncate(lines[-1] + " " + " ".join(remaining_words), font_size, max_width, bold)
    return lines


def _is_near_black(hex_color: str) -> bool:
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return False
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return (r + g + b) / 3 < 30


def pill(x: float, y: float, label: str, fill: str, text_color: str = ON_ACCENT, font_size: float = 11.5) -> Tuple[str, float]:
    """Returns (svg_fragment, width) for a rounded badge pill at (x, y) top-left."""
    height = 20
    pad_x = 9
    w = text_width(label, font_size, bold=True) + pad_x * 2
    # Very dark fills (e.g. brand-black badges) blend into the card's own dark
    # background, so give them a hairline border to stay legible.
    stroke = f' stroke="{BORDER}" stroke-width="1"' if _is_near_black(fill) else ""
    svg = (
        f'<g transform="translate({x:.1f},{y:.1f})">'
        f'<rect width="{w:.1f}" height="{height}" rx="{height / 2:.1f}" fill="{fill}"{stroke}/>'
        f'<text x="{w / 2:.1f}" y="{height / 2 + font_size * 0.36:.1f}" '
        f'font-size="{font_size}" font-weight="700" fill="{text_color}" '
        f'text-anchor="middle" font-family="{FONT_FAMILY}">{esc(label)}</text>'
        f"</g>"
    )
    return svg, w


def flow_pills(x: float, y: float, labels: List[Tuple[str, str, str]], max_x: float, gap: float = 8, row_height: float = 28) -> Tuple[str, float]:
    """Lays out (label, fill, text_color) pills left-to-right, wrapping rows.
    Returns (svg_fragment, total_height_consumed)."""
    frags = []
    cx, cy = x, y
    for label, fill, text_color in labels:
        w = text_width(label, 11.5, bold=True) + 18
        if cx + w > max_x and cx > x:
            cx = x
            cy += row_height
        frag, actual_w = pill(cx, cy, label, fill, text_color)
        frags.append(frag)
        cx += actual_w + gap
    total_height = (cy - y) + row_height
    return "\n".join(frags), total_height


# Neutral-token map for generating light-theme variants of the dark cards.
# Only semantic neutrals are remapped; brand/functional accents stay the same
# so team colors, language dots, and pills render identically in both themes.
_LIGHT_NEUTRALS = [
    ("#0b0f16", "#f6f8fa"),                                # hero base
    ("#0d1117", "#ffffff"),                                # card background
    ("#161b22", "#f6f8fa"),                                # activity tiles
    ("#21262d", "#eaeef2"),                                # activity empty bars
    ("#30363d", "#d0d7de"),                                # borders
    ("#c9d1d9", "#1f2328"),                                # body text
    ("#8b949e", "#59636e"),                                # muted text
    ("#e3b341", "#9a6700"),                                # amber accent: text/bars unreadable on white
    ("#e6edf3", "#1f2328"),                                # titles
    ("#f0f6fc", "#24292f"),                                # hero name
    ('fill="#ffffff" fill-opacity="0.04"', 'fill="#1f2328" fill-opacity="0.06"'),  # hero chips
    ('values="0 0 0 0 1  0 0 0 0 1  0 0 0 0 1  0 0 0 0.12 0"',
     'values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  0 0 0 0.08 0"'),  # grain: white -> dark speckle
]


# github-linguist colors are brand colors, but some vanish on one theme. Each
# fix steps HLS lightness (same hue) until the mark reaches 3:1 against that
# theme's card background — the WCAG minimum for graphical objects.
# Too dark on the dark card (#0d1117): lighter step, used in both themes (all
# of these still clear 6:1 on white).
_LANG_DARK_LEGIBLE = {
    "#555555": "#606060",  # C
    "#563d7c": "#704fa2",  # CSS
    "#384d54": "#49656e",  # Dockerfile
    "#701516": "#bb2325",  # Ruby
    "#012456": "#0259d4",  # PowerShell
    "#000080": "#3e3eff",  # Lua
    "#083fa1": "#0b56db",  # Markdown
    "#6e4a7e": "#79528b",  # Elixir
    "#5e5086": "#675893",  # Haskell
}
# Too light on white: darker step, light variant only.
_LIGHT_LANG = [
    ("#f1e05a", "#a6950e"),  # JavaScript
    ("#89e051", "#54a81e"),  # Shell
    ("#fcb32c", "#cc8503"),  # MDX
    ("#dea584", "#d18052"),  # Rust
]


def legible_lang_color(hex_color: str) -> str:
    """A language color that stays visible on the dark card background."""
    return _LANG_DARK_LEGIBLE.get(hex_color.lower(), hex_color)


def recolor_light(svg: str) -> str:
    """Remaps the dark-theme neutral palette to GitHub-light equivalents and
    darkens language colors that would wash out on white."""
    for dark, light in _LIGHT_NEUTRALS:
        svg = svg.replace(dark, light)
    for dark, light in _LIGHT_LANG:
        svg = re.sub(re.escape(dark), light, svg, flags=re.I)
    return svg


def write_theme_pair(out_path: str, svg: str) -> List[str]:
    """Writes the dark SVG to out_path and its light-theme recolor as
    <stem>-light.svg next to it. Returns the written paths."""
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(svg)
    stem, ext = os.path.splitext(out_path)
    light_path = f"{stem}-light{ext}"
    with open(light_path, "w", encoding="utf-8") as f:
        f.write(recolor_light(svg))
    return [out_path, light_path]


def card_shell(title: str, subtitle: Optional[str], body_svg: str, body_height: float, width: int = CARD_WIDTH, accent: str = ACCENT_BLUE) -> str:
    header_height = 56 if subtitle else 44
    height = header_height + body_height + 20
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height:.0f}" viewBox="0 0 {width} {height:.0f}">',
        "<defs>",
        # Signature edge: the border picks up the card's accent along the top
        # and melts back to the house border color — one gradient, no extra
        # hairline geometry to fight the rounded corners.
        '<linearGradient id="shellEdge" x1="0" y1="0" x2="1" y2="0.9">',
        f'<stop offset="0" stop-color="{accent}" stop-opacity="0.85"/>',
        f'<stop offset="0.3" stop-color="{accent}" stop-opacity="0.12"/>',
        f'<stop offset="0.65" stop-color="{BORDER}" stop-opacity="1"/>',
        "</linearGradient>",
        "</defs>",
        f'<rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1:.0f}" rx="12" fill="{BG}" stroke="url(#shellEdge)"/>',
        f'<text x="{PAD_X}" y="30" font-size="18" font-weight="700" fill="{TITLE_COLOR}" '
        f'font-family="{FONT_FAMILY}">{esc(title)}</text>',
    ]
    if subtitle:
        parts.append(
            f'<text x="{PAD_X}" y="48" font-size="12.5" fill="{MUTED}" '
            f'font-family="{FONT_FAMILY}">{esc(subtitle)}</text>'
        )
    parts.append(f'<g transform="translate(0,{header_height})">{body_svg}</g>')
    parts.append("</svg>")
    return "\n".join(parts)
