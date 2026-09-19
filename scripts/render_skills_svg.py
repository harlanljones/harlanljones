#!/usr/bin/env python3
"""
Renders the static Technical Skills card as SVG.

Skills change rarely and aren't derived from live GitHub data, so this is a
manual/one-off generator rather than something a cron workflow re-runs. Edit
CATEGORIES below and re-run to regenerate `skills.svg`.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from svg_cards import ACCENT_PURPLE, CARD_WIDTH, PAD_X, card_shell, esc, flow_pills  # noqa: E402

CATEGORIES = [
    ("Languages", "#58a6ff", "#0d1117", [
        "Rust", "Python", "TypeScript", "JavaScript", "C++", "Java", "SQL", "HTML5", "CSS3",
    ]),
    ("Machine Learning & AI", "#f78166", "#0d1117", [
        "PyTorch", "TensorFlow", "Scikit-Learn", "Pandas", "NumPy", "LLMs / Deep Learning",
    ]),
    ("Data Engineering & Cloud", "#3fb950", "#0d1117", [
        "Apache Kafka", "Elasticsearch", "Databricks", "BigQuery", "PostgreSQL", "AWS", "GCP", "Cloudflare Workers",
    ]),
    ("Frameworks & Frontend", "#a371f7", "#f6f8fa", [
        "FastAPI", "Flask", "Express.js", "React", "Next.js", "Tailwind CSS", "Astro", "Vite",
    ]),
    ("DevOps & Developer Tools", "#e3b341", "#0d1117", [
        "Docker", "Kubernetes", "CI/CD", "Linux", "Git", "Vim", "Linear",
    ]),
]


def render() -> str:
    row_gap = 14
    label_h = 24
    max_x = CARD_WIDTH - PAD_X
    body_frags = []
    cy = 6.0

    for name, accent, text_color, skills in CATEGORIES:
        body_frags.append(
            f'<text x="{PAD_X}" y="{cy + 14:.1f}" font-size="13" font-weight="700" '
            f'fill="#e6edf3" font-family="-apple-system,BlinkMacSystemFont,\'Segoe UI\',Helvetica,Arial,sans-serif">{esc(name)}</text>'
        )
        cy += label_h
        pills_svg, pills_h = flow_pills(
            PAD_X, cy, [(s, accent, text_color) for s in skills], max_x
        )
        body_frags.append(pills_svg)
        cy += pills_h + row_gap

    body_height = cy
    return card_shell("Technical Skills", None, "\n".join(body_frags), body_height, accent=ACCENT_PURPLE)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="skills.svg")
    args = parser.parse_args()
    svg = render()
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(svg)
    print(f"[OK] Wrote {args.out}")


if __name__ == "__main__":
    main()
