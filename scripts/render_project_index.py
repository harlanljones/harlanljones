#!/usr/bin/env python3
"""
The merged Projects card: replaces the old "Featured Projects" pill wall with
sections drawn from the live repo index. Every repository appears in at most
one section — first category that claims it wins.

  Top 5 · by gWAR     the leaderboard's best, with the Featured summary text
  Fresh off the bench newest repos, not already shown
  Live in production  repos with a homepage URL
  The long haul       oldest repos still pushed within 90 days

Rendered by the weekly repo-cards workflow, which owns the repo metadata
(gWAR, Pace+, commit counts). Summaries/badges come from the
Featured Projects store (scripts/data/featured_projects.json).
"""

import os
import sys
import datetime as dt
from typing import Dict, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from svg_cards import (  # noqa: E402
    ACCENT_AMBER,
    ACCENT_BLUE,
    ACCENT_GREEN,
    ACCENT_ORANGE,
    BORDER,
    CARD_WIDTH,
    FONT_FAMILY,
    MUTED,
    PAD_X,
    TEXT,
    TITLE_COLOR,
    card_shell,
    esc,
    truncate,
    wrap_by_width,
    write_theme_pair,
)

SECTION_ACCENTS = {"Top 5 · by gWAR": ACCENT_AMBER, "Fresh off the bench": ACCENT_GREEN,
                   "Live in production": ACCENT_ORANGE, "The long haul": ACCENT_BLUE}


def build_sections(ranked: List[dict], now, featured: Dict[str, dict]) -> List[Tuple[str, List[dict]]]:
    """Section name -> repos, honoring the no-duplicates rule."""
    used = set()

    def take(pool: List[dict], n: int) -> List[dict]:
        out = []
        for r in pool:
            if r["full_name"] not in used:
                out.append(r)
                used.add(r["full_name"])
                if len(out) >= n:
                    break
        return out

    sections = [("Top 5 · by gWAR", take(ranked, 5))]
    fresh = sorted((r for r in ranked if r["gwar"] > 0),
                   key=lambda r: r.get("created_at") or "", reverse=True)
    sections.append(("Fresh off the bench", take(fresh, 5)))
    live = sorted((r for r in ranked if r.get("homepage")), key=lambda r: -r["gwar"])
    sections.append(("Live in production", take(live, 4)))
    cutoff = (now - dt.timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%SZ")
    long_haul = sorted((r for r in ranked if (r.get("pushed_at") or "") >= cutoff),
                       key=lambda r: r.get("created_at") or "")
    sections.append(("The long haul", take(long_haul, 3)))
    return [(name, rows) for name, rows in sections if rows]


def _entry(x: float, y: float, w: float, r: dict, featured: Dict[str, dict], first: bool) -> Tuple[str, float]:
    """One repo row: name, right-side stat, two-line summary."""
    # Lazy import: render_repo_cards imports this module, so a top-level
    # import of lang_color would be circular when run standalone.
    from render_repo_cards import lang_color
    frags = []
    cy = y
    stat = f"gWAR {r['gwar']:.1f} · ★ {r['stargazers_count']:,} · Pace+ {r['pace_plus']}"
    live_w = (len("LIVE") * 11 * 0.62 + 18) if r.get("homepage") else 0.0
    name_max = w - live_w - 10
    frags.append(
        f'<circle cx="{x + 4}" cy="{cy + 11:.1f}" r="4" fill="{lang_color(r.get("language"))}"/>'
        f'<text x="{x + 14:.1f}" y="{cy + 15:.1f}" font-size="14.5" font-weight="700" fill="{ACCENT_BLUE}" '
        f'font-family="{FONT_FAMILY}">{esc(truncate(r["name"], 24, name_max - 78, bold=True))}</text>'
    )
    if r.get("homepage"):
        frags.append(
            f'<g transform="translate({x + w - live_w:.1f},{cy - 1:.1f})">'
            f'<rect width="{live_w:.1f}" height="18" rx="9" fill="#238636"/>'
            f'<text x="{live_w / 2:.1f}" y="13" font-size="10.5" font-weight="700" fill="#ffffff" '
            f'text-anchor="middle" font-family="{FONT_FAMILY}">LIVE</text></g>'
        )
    stat_x = x + w - live_w - 10 if live_w else x + w
    frags.append(
        f'<text x="{stat_x:.1f}" y="{cy + 15:.1f}" font-size="10.5" fill="{MUTED}" text-anchor="end" '
        f'font-family="{FONT_FAMILY}">{esc(stat)}</text>'
    )
    cy += 22
    summary = (featured.get(r["name"]) or {}).get("summary") or r.get("description") or ""
    if not summary:
        summary = " · ".join((r.get("topics") or [])[:6])
    for i, line in enumerate(wrap_by_width(summary, 11.5, w, max_lines=2)):
        frags.append(f'<text x="{x + 14:.1f}" y="{cy + 11 + i * 16:.1f}" font-size="11.5" fill="{MUTED}" '
                     f'font-family="{FONT_FAMILY}">{esc(line)}</text>')
    used_h = 16 * max(1, len(wrap_by_width(summary, 11.5, w, max_lines=2))) if summary else 10
    cy += used_h
    return "\n".join(frags), cy - y


def render(sections: List[Tuple[str, List[dict]]], date_str: str, total_repos: int) -> str:
    max_x = CARD_WIDTH - PAD_X
    col_gap = 30.0
    col_w = (max_x - PAD_X - col_gap) / 2
    frags = []
    cy = 10.0
    first_section = True
    for name, rows in sections:
        if not first_section:
            cy += 10
            frags.append(f'<line x1="{PAD_X}" y1="{cy:.1f}" x2="{max_x}" y2="{cy:.1f}" '
                         f'stroke="{BORDER}" stroke-width="1"/>')
            cy += 16
        first_section = False
        frags.append(f'<text x="{PAD_X}" y="{cy + 12:.1f}" font-size="13" font-weight="800" '
                     f'fill="{SECTION_ACCENTS.get(name, ACCENT_BLUE)}" font-family="{FONT_FAMILY}">{esc(name)}</text>')
        cy += 22
        if name == "Top 5 · by gWAR":
            # Two columns of detailed entries; the top repo spans full width.
            x0, y0 = PAD_X, cy
            svg, h = _entry(x0, y0, max_x - PAD_X, rows[0], FEATURED_REF[0], True)
            frags.append(svg)
            cy = y0 + h + 12
            for i in range(1, len(rows), 2):
                pair = rows[i:i + 2]
                if len(pair) == 1:
                    svg, h = _entry(PAD_X, cy, max_x - PAD_X, pair[0], FEATURED_REF[0], False)
                    frags.append(svg)
                    cy += h + 8
                    continue
                col_h = 0.0
                for j, r in enumerate(pair):
                    x = PAD_X + j * (col_w + col_gap)
                    svg, h = _entry(x, cy, col_w, r, FEATURED_REF[0], False)
                    frags.append(svg)
                    col_h = max(col_h, h)
                cy += col_h + 8
        else:
            for i in range(0, len(rows), 2):
                pair = rows[i:i + 2]
                if len(pair) == 1:
                    svg, h = _entry(PAD_X, cy, max_x - PAD_X, pair[0], FEATURED_REF[0], False)
                    frags.append(svg)
                    cy += h + 8
                    continue
                col_h = 0.0
                for j, r in enumerate(pair):
                    x = PAD_X + j * (col_w + col_gap)
                    svg, h = _entry(x, cy, col_w, r, FEATURED_REF[0], False)
                    frags.append(svg)
                    col_h = max(col_h, h)
                cy += col_h + 8
        cy += 2
    cy += 4
    frags.append(f'<text x="{max_x}" y="{cy + 8:.1f}" font-size="9.5" fill="{MUTED}" text-anchor="end" '
                 f'font-family="{FONT_FAMILY}">{total_repos} public repos · one entry per repo, best section wins · '
                 f'gWAR and Pace+ in Glossary · {esc(date_str)} · GitHub Actions</text>')
    return card_shell("Projects", "what I ship — ranked, fresh, live, and enduring",
                      "\n".join(frags), cy + 16, accent=ACCENT_ORANGE)


# Cheap way to hand the featured store to _entry without threading it through
# every call: a one-element list the caller populates before render().
FEATURED_REF: List[Dict[str, dict]] = [{}]


def main() -> None:
    import argparse
    import datetime as dt
    import json

    from render_repo_cards import fetch_repos, replacement_level, repo_runs, score_repo, pace_plus, enrich_with_commits

    parser = argparse.ArgumentParser(description="Render the merged Projects card.")
    parser.add_argument("--username", default="harlanljones")
    parser.add_argument("--store", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "featured_projects.json"))
    parser.add_argument("--out", default="projects.svg")
    parser.add_argument("--max-repos", type=int, default=40)
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN", ""))
    args = parser.parse_args()
    if not args.token:
        parser.error("a GitHub token is required (--token or GITHUB_TOKEN)")

    now = dt.datetime.now(dt.timezone.utc)
    repos = fetch_repos(args.username, args.token)
    repos.sort(key=lambda r: r.get("pushed_at", ""), reverse=True)
    enrich_with_commits(repos[: args.max_repos], args.token)
    replacement = replacement_level([repo_runs(r, now) for r in repos])
    for r in repos:
        r["gwar"] = score_repo(r, now, replacement)
        r["pace_plus"] = pace_plus(r, now)
    ranked = sorted(repos, key=lambda r: (-r["gwar"], -r.get("commits_90", 0), -r["stargazers_count"]))

    try:
        with open(args.store, encoding="utf-8") as f:
            featured = {e["name"]: e for e in json.load(f)}
    except (OSError, ValueError):
        featured = {}
    FEATURED_REF[0] = featured

    sections = build_sections(ranked, now, featured)
    for path in write_theme_pair(args.out, render(sections, now.strftime("%b %d, %Y"), len(repos))):
        print(f"[OK] Wrote {path}")


if __name__ == "__main__":
    main()
