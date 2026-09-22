#!/usr/bin/env python3
"""
The merged Projects card: replaces the old "Featured Projects" pill wall with
sections drawn from the live repo index. Every repository appears in at most
one section — first category that claims it wins.

  Top 5 · by gWAR     the leaderboard's best, with the Featured summary text
  September call-ups  newest repos (rookies), not already shown
  Live in production  repos with a homepage URL
  Hitting streak      hottest repos by Pace+ (30-day vs 90-day commit rate)
  Hidden gems         positive-gWAR repos with the fewest stars

Layout: Top 5 hero full-width on top, the other four categories in a 2x2
grid below; repos stack in a single column inside each category block.

Rendered by the weekly repo-cards workflow, which owns the repo metadata
(gWAR, Pace+, commit counts). Summaries/badges come from the
Featured Projects store (scripts/data/featured_projects.json).
"""

import os
import re
import sys
import datetime as dt
from typing import Dict, List, Optional, Tuple

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
    TITLE_COLOR,
    card_shell,
    esc,
    truncate,
    wrap_by_width,
    write_theme_pair,
)


def parse_iso(ts: str) -> dt.datetime:
    return dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))


def get_section_accent(name: str) -> str:
    n = name.lower()
    if "top 5" in n or "starting" in n:
        return ACCENT_AMBER
    if "call-up" in n or "rookie" in n or "debut" in n:
        return ACCENT_GREEN
    if "live" in n or "production" in n:
        return ACCENT_BLUE
    if "streak" in n or "hitting" in n:
        return ACCENT_ORANGE
    if "gem" in n or "hidden" in n:
        return ACCENT_PURPLE
    return ACCENT_BLUE


def format_section_stat(r: dict, section_name: str, now: Optional[dt.datetime] = None) -> str:
    now = now or dt.datetime.now(dt.timezone.utc)
    commits_90 = r.get("commits_90", 0)
    commit_days = r.get("commit_days", [])
    active_days = len(set(d[:10] for d in commit_days))
    gwar = r.get("gwar", 0.0)
    pace = r.get("pace_plus", 100)
    stars = r.get("stargazers_count", 0)

    if section_name.startswith("Top 5") or "starting" in section_name.lower():
        parts = [f"gWAR {gwar:.1f}", f"{commits_90} commits"]
        if active_days > 0:
            parts.append(f"{active_days}d active")
        elif stars > 0:
            parts.append(f"★ {stars}")
        return " · ".join(parts)

    if "call-up" in section_name.lower() or "rookie" in section_name.lower() or "debut" in section_name.lower():
        created = r.get("created_at")
        if created:
            c_date = parse_iso(created)
            days_ago = max(0, (now - c_date).days)
            return f"debut {c_date.strftime('%b %-d')} ({days_ago}d ago) · {commits_90} commits"
        return f"{commits_90} commits · gWAR {gwar:.1f}"

    if section_name.startswith("Live in production"):
        hp = r.get("homepage") or ""
        domain = re.sub(r"^https?://(www\.)?", "", hp).rstrip("/")
        domain = domain.split("/")[0] if domain else ""
        parts = []
        if domain:
            parts.append(domain)
        pushed = r.get("pushed_at")
        if pushed:
            p_days = max(0, (now - parse_iso(pushed)).days)
            push_str = "today" if p_days == 0 else (f"{p_days}d ago" if p_days < 30 else f"{p_days // 7}w ago")
            parts.append(f"pushed {push_str}")
        if not parts:
            parts = [f"{commits_90} commits", f"gWAR {gwar:.1f}"]
        return " · ".join(parts)

    if section_name.startswith("Hitting streak"):
        recent_30 = sum(1 for d in commit_days if parse_iso(d) >= now - dt.timedelta(days=30))
        parts = [f"Pace+ {pace}"]
        if recent_30 > 0:
            parts.append(f"{recent_30} in 30d")
        elif commits_90 > 0:
            parts.append(f"{commits_90} in 90d")
        return " · ".join(parts)

    if section_name.startswith("Hidden gems"):
        size_kb = r.get("size", 0)
        parts = [f"gWAR {gwar:.1f}"]
        if size_kb > 0:
            parts.append(f"{size_kb:,} KB")
        parts.append(f"{commits_90} commits")
        return " · ".join(parts)

    return f"gWAR {gwar:.1f} · {commits_90} commits"


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
    if now.month == 9:
        callups_label = "September call-ups"
    elif now.month in (3, 4):
        callups_label = "Opening Day call-ups"
    elif now.month in (5, 6, 7, 8):
        callups_label = f"{now.strftime('%B')} call-ups"
    else:
        callups_label = "Rookie call-ups & debuts"
    sections.append((callups_label, take(fresh, 3)))
    live = sorted((r for r in ranked if r.get("homepage")), key=lambda r: -r["gwar"])
    sections.append(("Live in production", take(live, 3)))
    streak = sorted((r for r in ranked if r.get("commits_90", 0) > 0),
                    key=lambda r: (-r.get("pace_plus", 100), -r.get("commits_90", 0)))
    sections.append(("Hitting streak", take(streak, 3)))
    gems = sorted((r for r in ranked if r["gwar"] > 0), key=lambda r: (r.get("stargazers_count", 0), -r["gwar"]))
    sections.append(("Hidden gems", take(gems, 3)))
    return [(name, rows) for name, rows in sections if rows]


def _entry(x: float, y: float, w: float, r: dict, featured: Dict[str, dict], first: bool, section_name: str = "") -> Tuple[str, float]:
    """One repo row: name, right-side stat, two-line summary."""
    from repo_languages import lang_color
    frags = []
    cy = y
    stat = format_section_stat(r, section_name)
    live_w = (len("LIVE") * 11 * 0.62 + 18) if r.get("homepage") else 0.0
    name_max = w - live_w - 10

    prim_l = r.get("primary_language") or r.get("language")
    sec_l = r.get("secondary_language")
    disp_l = r.get("lang_display") or prim_l or "—"

    if sec_l:
        frags.append(
            f'<circle cx="{x + 4}" cy="{cy + 11:.1f}" r="3.5" fill="{lang_color(prim_l)}"/>'
            f'<circle cx="{x + 12}" cy="{cy + 11:.1f}" r="3.5" fill="{lang_color(sec_l)}"/>'
        )
        tx = x + 20
        pad_offset = 84
    else:
        frags.append(
            f'<circle cx="{x + 4}" cy="{cy + 11:.1f}" r="4" fill="{lang_color(prim_l)}"/>'
        )
        tx = x + 14
        pad_offset = 78

    title_tooltip = f'{r.get("full_name", r["name"])} · {r.get("languages_pct", disp_l)} · {stat}'
    frags.append(
        f'<text x="{tx:.1f}" y="{cy + 15:.1f}" font-size="14.5" font-weight="700" fill="{ACCENT_BLUE}" '
        f'font-family="{FONT_FAMILY}"><title>{esc(title_tooltip)}</title>{esc(truncate(r["name"], 24, name_max - pad_offset, bold=True))}</text>'
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
    # Strip markdown link markup [text](url) -> text
    summary = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", summary)
    for i, line in enumerate(wrap_by_width(summary, 11.5, w, max_lines=2)):
        frags.append(f'<text x="{x + 14:.1f}" y="{cy + 11 + i * 16:.1f}" font-size="11.5" fill="{MUTED}" '
                     f'font-family="{FONT_FAMILY}">{esc(line)}</text>')
    used_h = 16 * max(1, len(wrap_by_width(summary, 11.5, w, max_lines=2))) if summary else 10
    cy += used_h
    return "\n".join(frags), cy - y


def _section_block(name: str, rows: List[dict], width: float) -> Tuple[str, float]:
    """One category block in local coords (origin = block top-left): accent
    header plus single-column repo entries. The caller places the block with
    <g transform="translate(x,y)">. Returns (svg_fragment, height)."""
    frags = [
        f'<text x="0" y="12" font-size="13" font-weight="800" '
        f'fill="{get_section_accent(name)}" font-family="{FONT_FAMILY}">{esc(name)}</text>'
    ]
    cy = 24.0
    for r in rows:
        svg, h = _entry(0.0, cy, width, r, FEATURED_REF[0], False, name)
        frags.append(svg)
        cy += h + 8
    return "\n".join(frags), cy - 8


def render(sections: List[Tuple[str, List[dict]]], date_str: str, total_repos: int) -> str:
    max_x = CARD_WIDTH - PAD_X
    full_w = max_x - PAD_X
    col_gap = 30.0
    row_gap = 20.0
    cell_w = (full_w - col_gap) / 2
    frags = []
    cy = 10.0

    by_name = dict(sections)
    # Hero: Top 5 spans the full width, single column.
    hero = by_name.get("Top 5 · by gWAR", [])
    if hero:
        svg, h = _section_block("Top 5 · by gWAR", hero, full_w)
        frags.append(f'<g transform="translate({PAD_X:.1f},{cy:.1f})">{svg}</g>')
        cy += h

    # The remaining categories pair into a 2x2 grid; cells in a row share the
    # taller cell's height so the next row starts clean.
    grid = [(n, rows) for n, rows in sections if n != "Top 5 · by gWAR"]
    for i in range(0, len(grid), 2):
        cy += 10
        frags.append(f'<line x1="{PAD_X}" y1="{cy:.1f}" x2="{max_x}" y2="{cy:.1f}" '
                     f'stroke="{BORDER}" stroke-width="1"/>')
        cy += 16
        rendered = [_section_block(n, rows, cell_w) for n, rows in grid[i:i + 2]]
        row_h = max(h for _, h in rendered)
        for j, (svg, _) in enumerate(rendered):
            x = PAD_X + j * (cell_w + col_gap)
            frags.append(f'<g transform="translate({x:.1f},{cy:.1f})">{svg}</g>')
        cy += row_h + row_gap
    cy += 4
    frags.append(f'<text x="{max_x}" y="{cy + 8:.1f}" font-size="9.5" fill="{MUTED}" text-anchor="end" '
                 f'font-family="{FONT_FAMILY}">{total_repos} public repos · one entry per repo, best section wins · '
                 f'gWAR and Pace+ in Glossary · {esc(date_str)} · GitHub Actions</text>')
    return card_shell("Projects", "what I ship — ranked, rookies, live, hot, and hidden",
                      "\n".join(frags), cy + 16, accent=ACCENT_ORANGE)


# Cheap way to hand the featured store to _entry without threading it through
# every call: a one-element list the caller populates before render().
FEATURED_REF: List[Dict[str, dict]] = [{}]

FEATURED_REPOS_START = "<!-- FEATURED_REPOS_START -->"
FEATURED_REPOS_END = "<!-- FEATURED_REPOS_END -->"

SHORT_BADGES: Dict[str, str] = {
    "Apache Kafka": "Kafka",
    "Tailwind CSS": "Tailwind",
    "Cloudflare Workers": "Cloudflare",
    "Cloudflare Tunnel": "Cloudflare Tunnel",
    "PyMC Bayesian Inference": "PyMC",
    "TDD Test-Driven Development": "TDD",
    "LLMs Deep Learning": "LLMs",
    "Turborepo Monorepo": "Turborepo",
    "Streaming Pipelines": "Streaming",
}


def distill_focus(summary: str, max_len: int = 85) -> str:
    """Extract a concise single-line focus phrase from a longer summary."""
    clean = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", summary).strip()
    first_sent = clean.split(". ")[0].rstrip(".")
    if len(first_sent) <= max_len:
        return first_sent
    cut = first_sent[: max_len - 3].rsplit(" ", 1)[0]
    return f"{cut}..."


def format_tech_stack(badges: List[str]) -> str:
    """Format tech stack badges into backticked markdown chips."""
    chips = []
    for b in badges[:4]:
        name = SHORT_BADGES.get(b, b)
        chips.append(f"`{name}`")
    return " ".join(chips)


def format_live_deployment(name: str, homepage: str, username: str = "harlanljones") -> str:
    """Format live deployment URL or fallback to GitHub repository link."""
    if homepage:
        domain = re.sub(r"^https?://(www\.)?", "", homepage).rstrip("/")
        domain = domain.split("/")[0] if domain else homepage
        return f"[{domain} ↗]({homepage})"
    return f"[GitHub Repository ↗](https://github.com/{username}/{name})"


def generate_featured_repos_table(
    entries: List[Dict],
    username: str = "harlanljones",
) -> str:
    """
    Build the markdown table for Featured Repositories & Live Demos,
    wrapped in a collapsed <details> / <summary> block.
    """
    included = []
    for e in entries:
        is_live = bool(e.get("homepage"))
        is_featured = e.get("featured", is_live)
        if is_live or is_featured:
            included.append(e)

    # Sort: priority first, then live demos, then alphabetical by name
    included.sort(key=lambda x: (x.get("priority", 99), not bool(x.get("homepage")), x.get("name", "").lower()))

    rows = []
    for e in included:
        name = e["name"]
        repo_link = f"[**{name}**](https://github.com/{username}/{name})"
        focus = e.get("focus") or distill_focus(e.get("summary", ""))
        tech_stack = format_tech_stack(e.get("badges", []))
        deployment = format_live_deployment(name, e.get("homepage", ""), username)
        rows.append(f"| {repo_link} | {focus} | {tech_stack} | {deployment} |")

    table_lines = [
        "<details>",
        "  <summary><h3>🚀 Featured Repositories & Live Demos</h3></summary>",
        "",
        "| Project | Focus | Tech Stack | Live Deployment |",
        "| :--- | :--- | :--- | :--- |",
    ] + rows + [
        "",
        "</details>",
    ]
    return "\n".join(table_lines)


def update_readme_featured_repos(
    readme_path: str,
    entries: List[Dict],
    username: str = "harlanljones",
) -> bool:
    """Update or insert the collapsed Featured Repositories table in README.md."""
    if not os.path.exists(readme_path):
        return False

    with open(readme_path, "r", encoding="utf-8") as f:
        content = f.read()

    table_md = generate_featured_repos_table(entries, username)
    section = f"{FEATURED_REPOS_START}\n{table_md}\n{FEATURED_REPOS_END}"

    pattern = re.escape(FEATURED_REPOS_START) + r".*?" + re.escape(FEATURED_REPOS_END)
    if re.search(pattern, content, flags=re.DOTALL):
        updated = re.sub(pattern, section, content, flags=re.DOTALL)
    elif "<!-- PROJECTS_END -->" in content:
        # Check if an unanchored old table exists right after PROJECTS_END
        old_table_pattern = r"(<!-- PROJECTS_END -->\s*\n\s*)(?:### 🚀 Featured Repositories & Live Demos[\s\S]*?(?=\n<picture|\Z))"
        if re.search(old_table_pattern, content):
            updated = re.sub(old_table_pattern, rf"\1{section}\n\n", content)
        else:
            updated = content.replace("<!-- PROJECTS_END -->", f"<!-- PROJECTS_END -->\n\n{section}\n")
    else:
        updated = content + f"\n\n{section}\n"

    if updated != content:
        with open(readme_path, "w", encoding="utf-8") as f:
            f.write(updated)
        print(f"[OK] Updated Featured Repositories table in {readme_path}")
        return True
    print(f"[INFO] Featured Repositories table already up to date in {readme_path}")
    return False


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
    parser.add_argument("--readme", default=None, help="Optional path to README.md to update featured repos table")
    args = parser.parse_args()
    if not args.token:
        parser.error("a GitHub token is required (--token or GITHUB_TOKEN)")

    now = dt.datetime.now(dt.timezone.utc)
    repos = fetch_repos(args.username, args.token)
    repos.sort(key=lambda r: r.get("pushed_at", ""), reverse=True)
    from repo_languages import enrich_repo_languages
    enrich_repo_languages(repos, args.token)
    enrich_with_commits(repos[: args.max_repos], args.token)
    replacement = replacement_level([repo_runs(r, now) for r in repos])
    for r in repos:
        r["gwar"] = score_repo(r, now, replacement)
        r["pace_plus"] = pace_plus(r, now)
    ranked = sorted(repos, key=lambda r: (-r["gwar"], -r.get("commits_90", 0), -r["stargazers_count"]))

    try:
        with open(args.store, encoding="utf-8") as f:
            raw_entries = json.load(f)
            featured = {e["name"]: e for e in raw_entries}
    except (OSError, ValueError):
        raw_entries = []
        featured = {}
    FEATURED_REF[0] = featured

    sections = build_sections(ranked, now, featured)
    for path in write_theme_pair(args.out, render(sections, now.strftime("%b %d, %Y"), len(repos))):
        print(f"[OK] Wrote {path}")

    if args.readme:
        update_readme_featured_repos(args.readme, raw_entries, args.username)


if __name__ == "__main__":
    main()
