#!/usr/bin/env python3
"""
Smarter repository multi-language mapping and stack classification.

Captures multi-language, full-stack, and hybrid systems architecture
(e.g., Python backend + TypeScript/React frontend, Rust engine + TS dashboard,
TypeScript + QML desktop widgets, Elixir + Python data pipelines).

Elevates real programming languages over raw markup (HTML/CSS) to prevent
misclassifications (e.g. bayes-horizon showing HTML instead of Python),
detects frontend vs backend stacks, powers multi-dot / dual-badge card
rendering, and expands Dev Immaculate Grid cell eligibility.
"""

import json
import os
import re
import sys
import urllib.request
from typing import Dict, List, Optional, Set, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

STORE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "repo_languages.json")

LANG_COLORS: Dict[str, str] = {
    "Python": "#3572A5",
    "Rust": "#dea584",
    "TypeScript": "#3178c6",
    "JavaScript": "#f1e05a",
    "Go": "#00ADD8",
    "Shell": "#89e051",
    "C++": "#f34b7d",
    "C": "#555555",
    "C#": "#178600",
    "HTML": "#e34c26",
    "CSS": "#563d7c",
    "SCSS": "#c6538c",
    "Jupyter Notebook": "#DA5B0B",
    "Dockerfile": "#384d54",
    "Nix": "#7e7eff",
    "Vue": "#41b883",
    "Java": "#b07219",
    "Kotlin": "#A97BFF",
    "Ruby": "#701516",
    "Elixir": "#6e4a7e",
    "QML": "#44a51c",
    "Svelte": "#ff3e00",
    "Assembly": "#6E4C13",
    "Lua": "#000080",
    "HCL": "#844FBA",
    "PHP": "#777bb4",
    "Dart": "#00B4AB",
    "Zig": "#ec915c",
    "Julia": "#a270ba",
    "Haskell": "#5e5086",
}
DEFAULT_LANG_COLOR = "#8b949e"

FRONTEND_CODE: Set[str] = {
    "TypeScript", "JavaScript", "Svelte", "Vue", "Astro", "QML",
}
MARKUP: Set[str] = {
    "HTML", "CSS", "SCSS", "Go Template", "Dockerfile", "Makefile",
}
BACKEND: Set[str] = {
    "Python", "Rust", "Go", "C++", "C", "C#", "Java", "Kotlin",
    "Ruby", "PHP", "Elixir", "Zig", "Haskell", "Julia", "SQL",
}
SYSTEMS: Set[str] = {
    "Rust", "C++", "C", "Assembly", "Zig", "Go",
}
INFRA_CODE: Set[str] = {
    "Shell", "Nix", "Lua", "HCL",
}
CODE_LANGS: Set[str] = BACKEND | FRONTEND_CODE | SYSTEMS | INFRA_CODE

LANG_ABBR: Dict[str, str] = {
    "TypeScript": "TS",
    "JavaScript": "JS",
    "Python": "Py",
    "Svelte": "Svelte",
    "QML": "QML",
    "Rust": "Rust",
    "Go": "Go",
    "Shell": "Shell",
    "Elixir": "Ex",
    "Assembly": "Asm",
    "C++": "C++",
    "HTML": "HTML",
    "CSS": "CSS",
    "Dockerfile": "Docker",
}


def lang_color(lang: Optional[str]) -> str:
    """Returns accessible hex color for a programming language."""
    from svg_cards import legible_lang_color
    return legible_lang_color(LANG_COLORS.get(lang or "", DEFAULT_LANG_COLOR))


def load_languages_store() -> Dict[str, dict]:
    """Loads cached repository language breakdown from JSON store."""
    if os.path.exists(STORE_PATH):
        try:
            with open(STORE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            pass
    return {}


def save_languages_store(data: Dict[str, dict]) -> None:
    """Saves repository language breakdown to JSON store."""
    os.makedirs(os.path.dirname(STORE_PATH), exist_ok=True)
    with open(STORE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)


def fetch_gh_languages(full_name: str, token: str) -> Dict[str, int]:
    """Fetches language byte counts from GitHub REST API."""
    req = urllib.request.Request(
        f"https://api.github.com/repos/{full_name}/languages",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "profile-language-mapper",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if isinstance(data, dict):
                return {k: int(v) for k, v in data.items()}
    except Exception as exc:
        print(f"[WARN] Failed fetching languages for {full_name}: {exc}")
    return {}


def analyze_repo_languages(
    name: str,
    raw_bytes: Dict[str, int],
    gh_primary: Optional[str] = None,
    topics: Optional[List[str]] = None,
    badges: Optional[List[str]] = None,
) -> dict:
    """Analyzes a repository's language breakdown and classifies stack roles."""
    topics = [t.lower() for t in (topics or [])]
    badges = [b.lower() for b in (badges or [])]

    prog_bytes = {k: v for k, v in raw_bytes.items() if k in CODE_LANGS}
    total_prog = sum(prog_bytes.values())
    total_raw = sum(raw_bytes.values())

    # 1. Primary language determination:
    # Deprioritize raw markup (HTML/CSS) if substantial real code exists.
    if gh_primary in MARKUP and prog_bytes:
        primary = max(prog_bytes.items(), key=lambda kv: kv[1])[0]
    elif gh_primary and gh_primary in CODE_LANGS:
        primary = gh_primary
    elif prog_bytes:
        primary = max(prog_bytes.items(), key=lambda kv: kv[1])[0]
    elif gh_primary:
        primary = gh_primary
    elif raw_bytes:
        primary = max(raw_bytes.items(), key=lambda kv: kv[1])[0]
    else:
        primary = None

    # 2. Significant programming languages
    sig_prog: List[str] = []
    if primary and primary in CODE_LANGS:
        sig_prog.append(primary)

    for lang, b in sorted(prog_bytes.items(), key=lambda kv: -kv[1]):
        if lang == primary:
            continue
        # Significant if >= 10% of code or >= 25,000 bytes
        if (total_prog > 0 and b / total_prog >= 0.10) or b >= 25000:
            sig_prog.append(lang)

    # 3. Secondary language: prefer real code over markup
    secondary = sig_prog[1] if len(sig_prog) > 1 else None

    # 4. Stack classification
    has_backend = any(l in BACKEND for l in sig_prog)
    has_frontend = any(l in FRONTEND_CODE for l in sig_prog)
    has_systems = any(l in SYSTEMS for l in sig_prog)
    has_infra = any(l in INFRA_CODE for l in sig_prog)

    if has_backend and has_frontend:
        stack_type = "fullstack"
    elif has_systems:
        stack_type = "systems"
    elif has_backend:
        stack_type = "backend"
    elif has_frontend:
        stack_type = "frontend"
    elif has_infra:
        stack_type = "infra"
    else:
        stack_type = "general"

    # 5. Display label (e.g. "Python · TS", "Rust · TS", "TS · QML")
    display = primary or "—"
    if secondary:
        p_abbr = LANG_ABBR.get(primary, primary) if len(primary or "") > 8 else primary
        s_abbr = LANG_ABBR.get(secondary, secondary)
        display = f"{p_abbr} · {s_abbr}"

    # 6. Eligible languages for Dev Immaculate Grid matching
    eligible: Set[str] = set(sig_prog)
    if primary:
        eligible.add(primary)
    if gh_primary:
        eligible.add(gh_primary)

    for lang, b in raw_bytes.items():
        if b >= 25000 or (total_prog > 0 and b / total_prog >= 0.10):
            eligible.add(lang)

    # Explicit badges or topics can also establish language eligibility
    for badge in badges:
        for known_lang in LANG_COLORS:
            if badge == known_lang.lower():
                eligible.add(known_lang)

    # Percentage breakdown of top languages for tooltips
    pct_parts = []
    denom = total_prog if total_prog > 0 else total_raw
    if denom > 0:
        for lang in (sig_prog[:3] or ([primary] if primary else [])):
            if lang in raw_bytes:
                pct = round(100.0 * raw_bytes[lang] / denom)
                if pct > 0:
                    pct_parts.append(f"{lang} {pct}%")

    pct_str = " · ".join(pct_parts) if pct_parts else (primary or "—")

    return {
        "primary": primary,
        "secondary": secondary,
        "sig_prog": sig_prog,
        "eligible": sorted(eligible),
        "stack_type": stack_type,
        "is_fullstack": stack_type == "fullstack",
        "display": display,
        "pct_summary": pct_str,
        "bytes": raw_bytes,
    }


def enrich_repo_languages(repos: List[dict], token: Optional[str] = None) -> None:
    """Enriches repo dicts in place with smart multi-language metadata."""
    store = load_languages_store()
    dirty = False

    for r in repos:
        name = r.get("name") or ""
        full_name = r.get("full_name") or f"harlanljones/{name}"
        cached = store.get(name)

        raw_bytes: Dict[str, int] = {}
        if cached and "bytes" in cached:
            raw_bytes = cached["bytes"]
        elif token:
            raw_bytes = fetch_gh_languages(full_name, token)
            dirty = True

        info = analyze_repo_languages(
            name=name,
            raw_bytes=raw_bytes,
            gh_primary=r.get("language"),
            topics=r.get("topics"),
        )

        store[name] = info

        # Populate repo fields
        r["primary_language"] = info["primary"]
        r["secondary_language"] = info["secondary"]
        r["language"] = info["primary"]  # Override gh markup primary (e.g. bayes-horizon HTML -> Python)
        r["lang_display"] = info["display"]
        r["eligible_languages"] = info["eligible"]
        r["stack_type"] = info["stack_type"]
        r["languages_pct"] = info["pct_summary"]
        r["lang_bytes"] = info["bytes"]

    if dirty:
        save_languages_store(store)
