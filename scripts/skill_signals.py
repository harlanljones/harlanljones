#!/usr/bin/env python3
"""
Skill detection from commit diffs (not commit messages).

Each skill is identified from the patch itself in one of two ways:

- path rules: the file *is* the skill (a Dockerfile, a workflow YAML, a test
  file). The skill is credited with every changed line in that file.
- line rules: a changed (+/-) line *uses* the skill (`import torch`,
  `async def`, `CREATE TABLE`). The skill is credited with CONTEXT_LINES per
  matching line, capped at the file's changed lines, so one stray `await` in
  a 300-line change doesn't claim all 300.

Languages are deliberately absent: they already get their own stat (Lang+)
on the Languages & Commit Rhythm card.
"""

import re
from typing import Dict, List, Optional, Pattern, Tuple

LIBS = "Frameworks & Libraries"
INFRA = "Infra & Tooling"
CRAFT = "Craft & Practices"
CATEGORIES = [LIBS, INFRA, CRAFT]

CONTEXT_LINES = 4.0
DELETION_WEIGHT = 0.5

# (skill, category, path regex or None, line regex or None)
_RAW_SKILLS: List[Tuple[str, str, Optional[str], Optional[str]]] = [
    # ---- Frameworks & Libraries
    ("PyTorch", LIBS, None, r"\b(import torch|from torch\b|torch\.\w+|nn\.Module)"),
    ("NumPy", LIBS, None, r"\b(import numpy|np\.\w+\()"),
    ("pandas", LIBS, None, r"\b(import pandas|pd\.(DataFrame|read_\w+|concat|merge|Series)\b)"),
    ("Polars", LIBS, None, r"\b(import polars|pl\.(DataFrame|col|scan_\w+|read_\w+|lit)\b)"),
    ("scikit-learn", LIBS, None, r"\b(from sklearn|import sklearn)"),
    ("Gradient Boosting", LIBS, None, r"\b(import (lightgbm|xgboost|catboost)|lgb\.\w+\(|xgb\.\w+\()"),
    ("FastAPI", LIBS, None, r"\b(from fastapi|FastAPI\(|APIRouter\()"),
    ("Flask", LIBS, None, r"\b(from flask|Flask\(__name__)"),
    ("Pydantic", LIBS, None, r"\b(from pydantic|\(BaseModel\))"),
    ("React", LIBS, r"\.(jsx|tsx)$", r"(from ['\"]react['\"]|\buse(State|Effect|Memo|Callback|Ref|Reducer)\()"),
    ("Next.js", LIBS, r"(^|/)next\.config\.\w+$", r"(from ['\"]next/|['\"]use (client|server)['\"])"),
    ("Astro", LIBS, r"(\.astro$|(^|/)astro\.config\.\w+$)", None),
    ("Tailwind CSS", LIBS, r"(^|/)tailwind\.config\.\w+$",
     r"class(Name)?=[\"'][^\"']*\b(flex|grid|p[xy]?-\d|m[xy]?-\d|gap-\d|text-(xs|sm|base|lg|xl)|bg-\w+-\d{2,3})\b"),
    ("Hono", LIBS, None, r"(from ['\"]hono|new Hono\()"),
    ("Zod", LIBS, None, r"(from ['\"]zod['\"]|\bz\.(object|string|number|array|enum)\()"),
    ("Tokio", LIBS, None, r"(\btokio::|#\[tokio::main\])"),
    ("Serde", LIBS, None, r"(use serde|#\[derive\([^)]*\b(Serialize|Deserialize)\b)"),
    ("Axum", LIBS, None, r"\b(use axum|axum::)"),
    ("Clap", LIBS, None, r"(use clap|#\[derive\([^)]*\bParser\b|#\[(arg|command)\()"),
    ("LLM APIs", LIBS, None,
     r"(\bimport anthropic|from anthropic|@anthropic-ai/|\bopenai\b|generativelanguage\.googleapis|"
     r"messages\.create\(|chat\.completions|claude-(opus|sonnet|haiku|fable))"),
    ("DuckDB", LIBS, None, r"\b(import duckdb|duckdb\.\w+)"),
    ("SQLAlchemy", LIBS, None, r"\bsqlalchemy\b"),
    ("Streamlit", LIBS, None, r"\b(import streamlit|st\.(write|sidebar|columns|dataframe|metric)\()"),
    ("Remotion", LIBS, None, r"(from ['\"]remotion['\"]|@remotion/)"),
    ("Supabase", LIBS, r"(^|/)supabase/", r"(@supabase/|from supabase\b|supabase\.(from|auth|storage)\b)"),

    # ---- Infra & Tooling
    ("Docker", INFRA, r"((^|/)(Dockerfile|docker-compose\.ya?ml|compose\.ya?ml)$|\.dockerfile$)", None),
    ("GitHub Actions", INFRA, r"^\.github/(workflows|actions)/.*\.ya?ml$", None),
    ("Cloudflare Workers", INFRA, r"(^|/)wrangler\.(toml|jsonc?)$",
     r"(export default \{\s*async fetch|\bDurableObject\b|env\.\w+\.(get|put|prepare)\(|@cloudflare/)"),
    ("Kubernetes", INFRA, r"(^|/)(k8s|kubernetes|helm|charts)/",
     r"^\s*kind:\s*(Deployment|Service|Pod|Ingress|StatefulSet|ConfigMap)\b"),
    ("Terraform", INFRA, r"\.tf$", None),
    ("Nix", INFRA, r"(\.nix$|(^|/)flake\.lock$)", None),
    ("systemd", INFRA, r"\.(service|timer|socket)$", None),
    ("Make & Just", INFRA, r"(^|/)(Makefile|justfile|Justfile)$", None),
    ("Build Config", INFRA,
     r"(^|/)(pyproject\.toml|Cargo\.toml|package\.json|tsconfig(\.\w+)?\.json|vite\.config\.\w+|setup\.cfg)$", None),
    ("Lint & Format", INFRA,
     r"(^|/)(\.eslintrc[\w.]*|eslint\.config\.\w+|\.prettierrc[\w.]*|ruff\.toml|biome\.jsonc?|"
     r"rustfmt\.toml|clippy\.toml|\.editorconfig)$", r"^\s*\[tool\.(ruff|black|mypy|pyright)\]"),
    ("Git Hooks", INFRA, r"(\.pre-commit-config\.ya?ml$|(^|/)\.husky/|lefthook\.ya?ml$)", None),
    ("Vercel", INFRA, r"(^|/)vercel\.json$", None),
    ("Agent Tooling", INFRA, r"((^|/)(CLAUDE|AGENTS|GEMINI)\.md$|(^|/)\.claude/|(^|/)SKILL\.md$|\.mcp\.json$)", None),
    ("Dotfiles", INFRA, r"((^|/)dot_\w+|(^|/)\.config/|(^|/)(\.zshrc|\.bashrc|\.tmux\.conf|init\.lua)$)", None),

    # ---- Craft & Practices
    ("Testing", CRAFT,
     r"((^|/)(tests?|__tests__|spec)/|(^|/)test_[^/]+\.py$|_test\.(py|go|rs)$|\.(test|spec)\.[jt]sx?$)",
     r"^\s*(def test_\w+|#\[test\]|#\[cfg\(test\)\]|(it|test|describe)\(['\"`]|assert\b|expect\()"),
    ("Type Design", CRAFT, None,
     r"^\s*(export )?(interface \w+|type \w+(<[^>]*>)? = |@dataclass|class \w+\([^)]*(TypedDict|Protocol|NamedTuple|Enum)\)|"
     r"(pub )?(struct|enum|trait) \w+)"),
    ("Concurrency", CRAFT, None,
     r"(\basync (def|fn|function)\b|\bawait\b|\basyncio\.|tokio::spawn|Promise\.(all|race|allSettled)|"
     r"\bthreading\.|ThreadPoolExecutor|\bgo func\b|\bMutex\b|\bArc<)"),
    ("SQL & Data Modeling", CRAFT, r"(\.sql$|(^|/)migrations?/)",
     r"\b(SELECT .+ FROM|INSERT INTO|CREATE (TABLE|INDEX|VIEW)|ALTER TABLE|LEFT JOIN|GROUP BY)\b"),
    ("Error Handling", CRAFT, None,
     r"(^\s*(try:|try \{|except\b|raise \w+|throw new )|catch\s*\(|\bResult<|\.map_err\(|\banyhow::|\?;\s*$)"),
    ("CLI Design", CRAFT, None,
     r"(\bargparse\b|ArgumentParser\(|add_argument\(|\bclap::|from ['\"]commander['\"]|\byargs\b|\btyper\b|"
     r"click\.(command|option|argument)\b)"),
    ("Regex & Parsing", CRAFT, None,
     r"(\bre\.(compile|sub|match|search|findall|finditer|split)\(|new RegExp\(|Regex::new\(|\.matchAll\()"),
    ("Data Viz", CRAFT, None,
     r"(<(svg|polyline|linearGradient|rect|circle)\b|\bmatplotlib\b|\bplt\.\w+\(|\bd3\.\w+|\bRecharts?\b|"
     r"\bplotly\b|\bchart\.js\b)"),
    ("API Integration", CRAFT, None,
     r"(\bfetch\(|requests\.(get|post|put|delete)\(|urllib\.request|\baxios\b|\bhttpx\.|\breqwest::|"
     r"api\.github\.com|graphql)"),
    ("Performance", CRAFT, None,
     r"(\blru_cache\b|@functools\.cache|\bmemoi[sz]e|\bbenchmark|\bcriterion::|perf_counter|\btimeit\b|"
     r"\bprofil(e|er|ing)\b)"),
    ("Docs & Writing", CRAFT, r"\.(md|mdx|rst)$", r'^\s*(""".{8,}|/\*\*|///\s*\w)'),
]

SKILLS: List[Tuple[str, str, Optional[Pattern], Optional[Pattern]]] = [
    (name, cat, re.compile(p) if p else None, re.compile(l, re.M) if l else None)
    for name, cat, p, l in _RAW_SKILLS
]
SKILL_CATEGORY: Dict[str, str] = {name: cat for name, cat, _, _ in SKILLS}

# Files whose diffs are generated, vendored, or binary-ish: they say nothing
# about practice and would swamp the counts.
NOISE_PATH = re.compile(
    r"((^|/)(node_modules|vendor|dist|build|target|\.next|__pycache__|site-packages)/|"
    r"(^|/)(package-lock\.json|pnpm-lock\.yaml|yarn\.lock|bun\.lockb?|Cargo\.lock|poetry\.lock|uv\.lock|"
    r"Pipfile\.lock|go\.sum)$|"
    r"\.(min\.(js|css)|map|svg|png|jpe?g|gif|webp|ico|pdf|woff2?|ttf|otf|mp4|mp3|wav|zip|gz|parquet|"
    r"csv|tsv|ipynb|pb\.go|snap)$)"
)
DOC_PATH = re.compile(r"\.(md|mdx|rst|txt)$")

# Agent and bot commits count as practice (they're work I directed), so the
# only message-level noise is reverts: the reverted diff already counted once.
NOISE_MESSAGE = re.compile(r"^revert \"", re.I)


def is_noise_commit(message: str) -> bool:
    return bool(NOISE_MESSAGE.search(message.strip().split("\n")[0]))


def _changed_lines(patch: str) -> Tuple[List[str], List[str]]:
    added, removed = [], []
    for line in patch.split("\n"):
        if line.startswith("+") and not line.startswith("+++"):
            added.append(line[1:])
        elif line.startswith("-") and not line.startswith("---"):
            removed.append(line[1:])
    return added, removed


def file_skill_lines(filename: str, patch: str, additions: int, deletions: int) -> Dict[str, float]:
    """Skill -> credited changed lines for one file in one commit."""
    if NOISE_PATH.search(filename):
        return {}
    file_lines = additions + DELETION_WEIGHT * deletions
    if file_lines <= 0:
        return {}
    added, removed = _changed_lines(patch or "")
    is_doc = bool(DOC_PATH.search(filename))
    credit: Dict[str, float] = {}
    for name, _, path_re, line_re in SKILLS:
        if path_re is not None and path_re.search(filename):
            credit[name] = file_lines
            continue
        # Code blocks in prose don't count as practicing the library.
        if line_re is None or is_doc:
            continue
        hits = sum(1 for l in added if line_re.search(l)) + DELETION_WEIGHT * sum(
            1 for l in removed if line_re.search(l)
        )
        if hits:
            credit[name] = min(file_lines, CONTEXT_LINES * hits)
    return credit


def commit_skill_lines(files: List[dict]) -> Dict[str, float]:
    """Skill -> credited lines summed over a commit's files (GitHub REST
    `files[]` entries: filename, patch, additions, deletions)."""
    totals: Dict[str, float] = {}
    for f in files:
        for name, lines in file_skill_lines(
            f.get("filename", ""), f.get("patch") or "", int(f.get("additions") or 0), int(f.get("deletions") or 0)
        ).items():
            totals[name] = totals.get(name, 0.0) + lines
    return totals
