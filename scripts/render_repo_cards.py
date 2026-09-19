#!/usr/bin/env python3
"""
Renders the repository cards: Repo Leaderboard, Repo Spotlight, and the
Dev Immaculate Grid — one data pass against the GitHub REST API, six SVGs
(dark + light for each card).

- Repo Leaderboard: top repositories ranked by a bWAR-style composite
  (commits/10 + stars + forks + freshness), drawn as a horizontal bar chart.
- Repo Spotlight: the leaderboard's #1 repo for this cycle — description plus
  a 30-day commit area chart and latest release pill.
- Dev Immaculate Grid: a 3x3 languages x stack grid where every filled cell
  is a real repository from the public index.

Weekly cadence via .github/workflows/repo-cards.yml; static/one-off runs are
just `python3 scripts/render_repo_cards.py --out-dir <dir>` with a token.
"""

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.request
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from svg_cards import (  # noqa: E402
    ACCENT_AMBER,
    ACCENT_BLUE,
    ACCENT_PURPLE,
    BORDER,
    CARD_WIDTH,
    FONT_FAMILY,
    MUTED,
    ON_ACCENT,
    PAD_X,
    TEXT,
    TITLE_COLOR,
    card_shell,
    esc,
    text_width,
    truncate,
    wrap_by_width,
    write_theme_pair,
)

API = "https://api.github.com"
LANG_COLORS = {
    "Python": "#3572A5", "Rust": "#dea584", "TypeScript": "#3178c6", "JavaScript": "#f1e05a",
    "Go": "#00ADD8", "Shell": "#89e051", "C++": "#f34b7d", "C": "#555555", "C#": "#178600",
    "HTML": "#e34c26", "CSS": "#563d7c", "Jupyter Notebook": "#DA5B0B", "Dockerfile": "#384d54",
    "Nix": "#7e7eff", "Vue": "#41b883", "Java": "#b07219", "Kotlin": "#A97BFF", "Ruby": "#701516",
}
DEFAULT_LANG_COLOR = "#8b949e"

DOMAINS: List[Tuple[str, set]] = [
    ("AI / ML", {
        "llm", "llms", "ml", "machine-learning", "deep-learning", "pytorch", "pytorch-geometric",
        "tensorflow", "keras", "agents", "agent", "ai-agents", "ai-agent", "agent-analytics",
        "agent-orchestration", "coding-agents", "ai", "openai", "rag", "inference", "genai", "nlp",
        "transformers", "diffusion", "gan", "graph-neural-networks", "gnn", "lightgbm",
        "bayesian-inference", "empirical-bayes", "onnx-runtime", "earthquake-forecasting",
        "seismology", "forecasting",
    }),
    ("Cloud / Infra", {
        "kubernetes", "k8s", "docker", "terraform", "aws", "gcp", "cloudflare", "workers",
        "cloudflare-workers", "cloudflare-tunnel", "devops", "ci-cd", "nix", "systemd", "homelab",
        "self-hosted", "infrastructure", "iac", "telemetry", "daemon", "remote-access", "ipc",
    }),
    ("Data", {
        "postgres", "postgresql", "duckdb", "kafka", "apache-kafka", "elasticsearch",
        "clickhouse", "sqlite", "database", "embedded-database", "analytics", "timeseries",
        "time-series", "backtesting", "data-engineering", "data-pipeline", "data-science", "etl",
        "visualization", "lakehouse", "vector-search", "embeddings", "ann",
        "approximate-nearest-neighbor-search", "hnsw", "ivf-pq", "lsm-tree",
        "log-structured-merge-tree", "storage-engine", "key-value-store", "persistent-storage",
        "low-latency", "spatio-temporal", "spatio-temporal-data", "geospatial",
    }),
    ("Baseball", {
        "baseball", "baseball-analytics", "baseball-data", "baseball-projections", "mlb",
        "mlb-draft", "sabermetrics", "sports", "sports-analytics", "sports-api", "sports-data",
        "sports-betting", "fantasy", "fantasy-baseball", "pitching", "immaculate-grid",
        "amateur-baseball", "college-baseball", "player-projections", "prospect-analysis",
        "nfl", "nfl-analytics",
    }),
    ("Web / API", {
        "react", "reactjs", "nextjs", "next-js", "astro", "fastapi", "flask", "hono",
        "websocket", "websockets", "grpc", "api", "tailwindcss", "rest", "graphql",
        "fullstack", "streamlit", "dashboard", "local-first", "backend", "backends",
        "configuration-explorer",
    }),
    ("Tools / CLI", {
        "cli", "tdd", "vim", "dotfiles", "shell", "developer-tools", "testing", "linting",
        "workflow", "automation", "productivity", "chezmoi", "archlinux-dotfiles",
        "neovim-dotfiles", "hyprland-dotfiles", "omarchy", "ansi", "pty", "npm",
        "interactive-terminal", "issue-tracking", "linear", "scheduler", "sync", "webhook",
        "integrations", "animated-svg",
    }),
]


def gh_get(path: str, token: str) -> Optional[dict]:
    req = urllib.request.Request(
        f"{API}{path}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "profile-cards-renderer",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - a card must render despite one bad call
        print(f"[WARN] GET {path}: {exc}")
        return None


def parse_iso(ts: str) -> dt.datetime:
    return dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))


def fetch_repos(username: str, token: str) -> List[dict]:
    repos: List[dict] = []
    for page in (1, 2):
        batch = gh_get(f"/users/{username}/repos?per_page=100&sort=pushed&page={page}", token) or []
        repos.extend(batch)
        if len(batch) < 100:
            break
    return [
        r for r in repos
        if not r.get("fork") and not r.get("archived") and not r.get("disabled")
    ]


def enrich_with_commits(repos: List[dict], token: str) -> None:
    """Adds commits_90 (count, capped at 100) and commit_days (last-90d dates)
    to each repo dict from a single commits call per repo."""
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%SZ")
    for repo in repos:
        data = gh_get(
            f"/repos/{repo['full_name']}/commits?since={since}&per_page=100", token
        )
        if isinstance(data, list):
            repo["commits_90"] = len(data)
            repo["commit_days"] = [
                d for d in (
                    (c.get("commit") or {}).get("committer", {}).get("date", "")
                    for c in data
                ) if d
            ]
        else:
            repo["commits_90"] = 0
            repo["commit_days"] = []
        time.sleep(0.05)


def score_repo(repo: dict, now: dt.datetime) -> float:
    days_pushed = max(0.0, (now - parse_iso(repo["pushed_at"])).total_seconds() / 86400)
    freshness = 3.0 * max(0.0, 1.0 - days_pushed / 90)
    return round(repo["commits_90"] / 10.0 + repo["stargazers_count"] + repo["forks_count"] + freshness, 1)


def lang_color(lang: Optional[str]) -> str:
    return LANG_COLORS.get(lang or "", DEFAULT_LANG_COLOR)


# ---------------------------------------------------------------- leaderboard

def render_leaderboard(rows: List[dict], date_str: str) -> str:
    max_x = CARD_WIDTH - PAD_X
    bar_x, bar_w = 340.0, 300.0
    top = max(r["bwar"] for r in rows) or 1.0
    frags = [
        f'<text x="{PAD_X}" y="{14}" font-size="9" font-weight="700" letter-spacing="1.5" '
        f'fill="{MUTED}" font-family="{FONT_FAMILY}">LANGUAGE</text>',
        f'<text x="150" y="{14}" font-size="9" font-weight="700" letter-spacing="1.5" '
        f'fill="{MUTED}" font-family="{FONT_FAMILY}">REPOSITORY</text>',
        f'<text x="{bar_x + bar_w + 12}" y="{14}" font-size="9" font-weight="700" letter-spacing="1.5" '
        f'fill="{MUTED}" font-family="{FONT_FAMILY}">STARS</text>',
        f'<text x="{bar_x + bar_w + 64}" y="{14}" font-size="9" font-weight="700" letter-spacing="1.5" '
        f'fill="{MUTED}" font-family="{FONT_FAMILY}">COMMITS 90D</text>',
        f'<text x="{max_x}" y="{14}" font-size="9" font-weight="700" letter-spacing="1.5" text-anchor="end" '
        f'fill="{ACCENT_AMBER}" font-family="{FONT_FAMILY}">BWAR</text>',
    ]
    cy = 24.0
    for i, r in enumerate(rows):
        opacity = 0.95 - i * 0.07
        frags.append(f'<text x="38" y="{cy + 12:.1f}" font-size="12" font-weight="700" text-anchor="end" '
                     f'fill="{MUTED}" font-family="{FONT_FAMILY}">{i + 1}</text>')
        frags.append(f'<circle cx="52" cy="{cy + 8:.1f}" r="4" fill="{lang_color(r["language"])}"/>')
        frags.append(f'<text x="62" y="{cy + 12:.1f}" font-size="11" fill="{MUTED}" '
                     f'font-family="{FONT_FAMILY}">{esc(truncate(r["language"] or "—", 11, 80))}</text>')
        frags.append(f'<text x="150" y="{cy + 12:.1f}" font-size="13" font-weight="700" fill="{TEXT}" '
                     f'font-family="{FONT_FAMILY}">{esc(truncate(r["name"], 20, 175, bold=True))}</text>')
        w = max(6.0, bar_w * (r["bwar"] / top))
        frags.append(f'<rect x="{bar_x}" y="{cy + 3:.1f}" width="{w:.1f}" height="10" rx="5" '
                     f'fill="{ACCENT_BLUE}" fill-opacity="{opacity:.2f}"/>')
        frags.append(f'<text x="{bar_x + bar_w + 12}" y="{cy + 12:.1f}" font-size="11.5" fill="{TEXT}" '
                     f'font-family="{FONT_FAMILY}">{r["stargazers_count"]:,}</text>')
        frags.append(f'<text x="{bar_x + bar_w + 64}" y="{cy + 12:.1f}" font-size="11.5" fill="{TEXT}" '
                     f'font-family="{FONT_FAMILY}">{r["commits_90"]}</text>')
        frags.append(f'<text x="{max_x}" y="{cy + 12:.1f}" font-size="13" font-weight="800" text-anchor="end" '
                     f'fill="{ACCENT_AMBER}" font-family="{FONT_FAMILY}">{r["bwar"]:.1f}</text>')
        cy += 28
    cy += 6
    frags.append(f'<text x="{PAD_X}" y="{cy + 8:.1f}" font-size="9.5" fill="{MUTED}" '
                 f'font-family="{FONT_FAMILY}">bWAR = commits(90d)/10 + stars + forks + freshness · '
                 f'commits capped at 100/repo · {esc(date_str)} · GitHub Actions</text>')
    return card_shell("Repo Leaderboard", "top repositories ranked by bWAR — win above replacement, sort of",
                      "\n".join(frags), cy + 16, accent=ACCENT_AMBER)


# ------------------------------------------------------------------ spotlight

def render_spotlight(repo: dict, date_str: str) -> str:
    max_x = CARD_WIDTH - PAD_X
    cy = 14.0
    frags = [
        f'<circle cx="{PAD_X + 5}" cy="{cy + 2}" r="5" fill="{lang_color(repo["language"])}"/>',
        f'<text x="{PAD_X + 16}" y="{cy + 6:.1f}" font-size="19" font-weight="800" fill="{TITLE_COLOR}" '
        f'font-family="{FONT_FAMILY}">{esc(repo["name"])}</text>',
        f'<text x="{max_x}" y="{cy + 6:.1f}" font-size="11.5" fill="{MUTED}" text-anchor="end" '
        f'font-family="{FONT_FAMILY}">★ {repo["stargazers_count"]:,} · forks {repo["forks_count"]:,} · '
        f'bWAR {repo["bwar"]:.1f}</text>',
    ]
    cy += 24
    desc = repo.get("description") or " · ".join((repo.get("topics") or [])[:5]) or "No description yet."
    for line in wrap_by_width(desc, 12.5, max_x - PAD_X, max_lines=2):
        frags.append(f'<text x="{PAD_X}" y="{cy + 12:.1f}" font-size="12.5" fill="{TEXT}" '
                     f'font-family="{FONT_FAMILY}">{esc(line)}</text>')
        cy += 18
    cy += 10

    # 30-day commit area chart
    counts = repo["daily_30"]
    chart_x, chart_w, chart_h = float(PAD_X), max_x - PAD_X, 70.0
    baseline = cy + chart_h
    peak = max(counts) or 1
    n = len(counts)
    step = chart_w / max(1, n - 1)

    def pt(i: int) -> Tuple[float, float]:
        x = chart_x + i * step
        y = baseline - (counts[i] / peak) * (chart_h - 6) if counts[i] else baseline
        return x, y

    pts = [pt(i) for i in range(n)]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    area = f"M {chart_x},{baseline:.1f} L " + " L ".join(f"{x:.1f},{y:.1f}" for x, y in pts) + f" L {chart_x + chart_w:.1f},{baseline:.1f} Z"
    frags += [
        f'<defs><linearGradient id="spotArea" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="{ACCENT_BLUE}" stop-opacity="0.35"/>'
        f'<stop offset="1" stop-color="{ACCENT_BLUE}" stop-opacity="0"/></linearGradient></defs>',
        f'<path d="{area}" fill="url(#spotArea)"/>',
        f'<polyline points="{line}" fill="none" stroke="{ACCENT_BLUE}" stroke-width="1.5"/>',
        f'<circle cx="{pts[-1][0]:.1f}" cy="{pts[-1][1]:.1f}" r="3" fill="{ACCENT_BLUE}"/>',
        f'<text x="{PAD_X}" y="{cy - 4:.1f}" font-size="9.5" fill="{MUTED}" font-family="{FONT_FAMILY}">'
        f'{esc((dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=29)).strftime("%b %d"))}</text>',
        f'<text x="{max_x}" y="{cy - 4:.1f}" font-size="9.5" fill="{MUTED}" text-anchor="end" '
        f'font-family="{FONT_FAMILY}">{esc(date_str)}</text>',
        f'<text x="{chart_x + chart_w / 2:.1f}" y="{cy - 4:.1f}" font-size="10" font-weight="700" '
        f'text-anchor="middle" fill="{TEXT}" font-family="{FONT_FAMILY}">'
        f'{sum(counts)} commits · last 30 days</text>',
    ]
    cy += chart_h + 18

    release = repo.get("latest_release")
    if release:
        tag, published = release.get("tag_name", ""), (release.get("published_at") or "")[:10]
        label = f"↳ latest release {tag} · {published}"
        frags.append(f'<text x="{PAD_X}" y="{cy:.1f}" font-size="11" fill="{MUTED}" '
                     f'font-family="{FONT_FAMILY}">{esc(label)}</text>')
        cy += 16

    return card_shell("Repo Spotlight", f"top of this week's leaderboard · {esc(date_str)}",
                      "\n".join(frags), cy, accent=ACCENT_BLUE)


# ----------------------------------------------------------------------- grid

def build_grid(repos: List[dict], now: dt.datetime) -> Tuple[List[str], List[str], Dict[Tuple[str, str], Optional[dict]]]:
    """Chooses 3 languages x 3 domains maximizing filled, high-scoring cells."""
    lang_counts: Dict[str, int] = {}
    for r in repos:
        if r.get("language"):
            lang_counts[r["language"]] = lang_counts.get(r["language"], 0) + 1
    lang_candidates = [l for l, _ in sorted(lang_counts.items(), key=lambda kv: -kv[1])[:4]]

    def domain_of(r: dict) -> List[str]:
        topics = {t.lower() for t in (r.get("topics") or [])}
        # Fall back to name/description tokens so repos without topics still land.
        text = f"{r.get('name', '')} {r.get('description') or ''}".lower()
        words = set(re.findall(r"[a-z][a-z0-9-]+", text))
        return [name for name, keys in DOMAINS if topics & keys or words & keys]

    candidates: Dict[Tuple[str, str], List[dict]] = {}
    for r in repos:
        for d in domain_of(r):
            for l in lang_candidates:
                if r.get("language") == l:
                    candidates.setdefault((l, d), []).append(r)
    for cell in candidates:
        candidates[cell].sort(key=lambda r: -r["bwar"])

    domain_counts = {d: sum(1 for (l, dd) in candidates if dd == d) for d, _ in DOMAINS}
    domain_candidates = [d for d, _ in sorted(DOMAINS, key=lambda kv: -domain_counts.get(kv[0], 0))[:4]]
    domain_names = domain_candidates

    from itertools import combinations
    # Degrade gracefully when the index has fewer than 3 languages/domains.
    k_lang = min(3, len(lang_candidates))
    k_dom = min(3, len(domain_names))
    best = (0, 0.0, [], [])
    if k_lang and k_dom:
        for langs in combinations(lang_candidates, k_lang):
            for doms in combinations(domain_names, k_dom):
                filled, total = 0, 0.0
                for l in langs:
                    for d in doms:
                        c = candidates.get((l, d))
                        if c:
                            filled += 1
                            total += c[0]["bwar"]
                if (filled, total) > (best[0], best[1]):
                    best = (filled, total, list(langs), list(doms))

    langs, doms = best[2], best[3]
    assigned: Dict[Tuple[str, str], Optional[dict]] = {}
    used = set()
    cells = [(l, d) for l in langs for d in doms if candidates.get((l, d))]
    cells.sort(key=lambda c: -candidates[c][0]["bwar"])
    for cell in cells:
        pick = next((r for r in candidates[cell] if r["full_name"] not in used), None)
        assigned[cell] = pick
        if pick:
            used.add(pick["full_name"])
    for l in langs:
        for d in doms:
            assigned.setdefault((l, d), None)
    return langs, doms, assigned


def render_grid(langs: List[str], doms: List[str], assigned: Dict[Tuple[str, str], Optional[dict]], date_str: str) -> str:
    label_w, gap = 100.0, 8.0
    cell_w = (CARD_WIDTH - PAD_X * 2 - label_w - gap * 3) / 3
    cell_h = 56.0
    cy = 8.0
    frags = []
    for j, d in enumerate(doms):
        x = PAD_X + label_w + gap + j * (cell_w + gap)
        frags.append(f'<text x="{x + cell_w / 2:.1f}" y="{cy + 12:.1f}" font-size="11" font-weight="700" '
                     f'text-anchor="middle" fill="{ACCENT_PURPLE}" font-family="{FONT_FAMILY}">{esc(d)}</text>')
    cy += 18
    filled = 0
    for l in langs:
        frags.append(f'<circle cx="{PAD_X + 5}" cy="{cy + cell_h / 2:.1f}" r="4" fill="{lang_color(l)}"/>')
        frags.append(f'<text x="{PAD_X + 14}" y="{cy + cell_h / 2 + 4:.1f}" font-size="11.5" font-weight="700" '
                     f'fill="{TEXT}" font-family="{FONT_FAMILY}">{esc(truncate(l, 12, label_w - 18, bold=True))}</text>')
        for j, d in enumerate(doms):
            x = PAD_X + label_w + gap + j * (cell_w + gap)
            repo = assigned.get((l, d))
            if repo:
                filled += 1
                frags.append(
                    f'<rect x="{x:.1f}" y="{cy:.1f}" width="{cell_w:.1f}" height="{cell_h:.0f}" rx="8" '
                    f'fill="#161b22" stroke="{BORDER}"/>'
                    f'<text x="{x + 10:.1f}" y="{cy + 22:.1f}" font-size="12" font-weight="700" fill="{TEXT}" '
                    f'font-family="{FONT_FAMILY}">{esc(truncate(repo["name"], 18, cell_w - 20, bold=True))}</text>'
                    f'<text x="{x + cell_w - 10:.1f}" y="{cy + cell_h - 10:.1f}" font-size="9.5" text-anchor="end" '
                    f'fill="{MUTED}" font-family="{FONT_FAMILY}">★ {repo["stargazers_count"]:,} · bWAR {repo["bwar"]:.1f}</text>'
                )
            else:
                frags.append(
                    f'<rect x="{x + 0.5:.1f}" y="{cy + 0.5:.1f}" width="{cell_w - 1:.1f}" height="{cell_h - 1:.0f}" '
                    f'rx="8" fill="none" stroke="{BORDER}" stroke-dasharray="3 3"/>'
                    f'<text x="{x + cell_w / 2:.1f}" y="{cy + cell_h / 2 + 4:.1f}" font-size="13" text-anchor="middle" '
                    f'fill="{MUTED}" font-family="{FONT_FAMILY}">—</text>'
                )
        cy += cell_h + gap
    cy += 2
    frags.append(f'<text x="{PAD_X}" y="{cy + 8:.1f}" font-size="9.5" fill="{MUTED}" font-family="{FONT_FAMILY}">'
                 f'{filled}/9 filled · every cell is a real repo from the public index · {esc(date_str)} · GitHub Actions</text>')
    return card_shell("Dev Immaculate Grid", "languages x stack — the daily lineup, gamified",
                      "\n".join(frags), cy + 16, accent=ACCENT_PURPLE)


# ----------------------------------------------------------------------- main

def main() -> None:
    parser = argparse.ArgumentParser(description="Render leaderboard, spotlight, and grid cards.")
    parser.add_argument("--username", default="harlanljones")
    parser.add_argument("--out-dir", default=".")
    parser.add_argument("--max-repos", type=int, default=40)
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN", ""))
    args = parser.parse_args()

    if not args.token:
        parser.error("a GitHub token is required (--token or GITHUB_TOKEN)")

    now = dt.datetime.now(dt.timezone.utc)
    date_str = now.strftime("%b %d, %Y")

    repos = fetch_repos(args.username, args.token)
    print(f"[INFO] {len(repos)} public (non-fork, non-archived) repositories")
    repos.sort(key=lambda r: r.get("pushed_at", ""), reverse=True)
    enrich_with_commits(repos[: args.max_repos], args.token)

    for r in repos:
        r["bwar"] = score_repo(r, now)
    ranked = sorted(repos, key=lambda r: (-r["bwar"], -r["commits_90"], -r["stargazers_count"]))
    top = [r for r in ranked if r["commits_90"] > 0][:8] or ranked[:8]

    hero = dict(top[0])
    cutoff = (now - dt.timedelta(days=29)).date()
    daily: Dict[dt.date, int] = {}
    for raw in hero.get("commit_days", []):
        day = parse_iso(raw).date()
        if day >= cutoff:
            daily[day] = daily.get(day, 0) + 1
    hero["daily_30"] = [daily.get(cutoff + dt.timedelta(days=i), 0) for i in range(30)]
    release = gh_get(f"/repos/{hero['full_name']}/releases/latest", args.token)
    hero["latest_release"] = release if isinstance(release, dict) else None

    os.makedirs(args.out_dir, exist_ok=True)
    cards = {
        "repo-leaderboard.svg": render_leaderboard(top, date_str),
        "repo-spotlight.svg": render_spotlight(hero, date_str),
        "dev-grid.svg": None,
    }
    langs, doms, assigned = build_grid(ranked, now)
    cards["dev-grid.svg"] = render_grid(langs, doms, assigned, date_str)

    for name, svg in cards.items():
        for path in write_theme_pair(os.path.join(args.out_dir, name), svg):
            print(f"[OK] Wrote {path}")


if __name__ == "__main__":
    main()
