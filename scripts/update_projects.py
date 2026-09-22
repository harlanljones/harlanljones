#!/usr/bin/env python3
"""
Featured Projects Sync Automation.

Checks the user's public GitHub repositories and appends any repository not
already tracked in the JSON store (scripts/data/featured_projects.json).
Existing entries are never reordered, rewritten, or re-synthesized; new
entries are appended to the store, then the whole Featured Projects section
is re-rendered as a single SVG card (GitHub's README sanitizer strips
<style>/style=/class=, so real styling only survives inside a generated
image). The SVG is written to --svg-out for a workflow to commit to the
`profile-cards` branch; README.md itself only needs one <img> tag pointing
at that asset, inserted once above the <!-- PROJECTS_END --> anchor.

Each generated entry carries a brief summary synthesized from recent
project-level commit activity plus detected technologies (languages + topics).
"""

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, List, Optional, Set, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from render_project_index import update_readme_featured_repos  # noqa: E402
from svg_cards import ACCENT_ORANGE, CARD_WIDTH, FONT_FAMILY, MUTED, ON_ACCENT, PAD_X, TEXT, card_shell, esc, flow_pills, plain_text, truncate, wrap_by_width, write_theme_pair  # noqa: E402

PROJECTS_ANCHOR = "<!-- PROJECTS_END -->"
DEFAULT_STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "featured_projects.json")

FALLBACK_PALETTE = ["#6e40c9", "#bf3989", "#0969da", "#1a7f37", "#9a6700", "#cf222e"]


def _stable_color_index(label: str, n: int) -> int:
    return int(hashlib.md5(label.encode("utf-8")).hexdigest(), 16) % n

LANG_BADGES = {
    "python": ("Python", "3776AB", "python", "white"),
    "typescript": ("TypeScript", "3178C6", "typescript", "white"),
    "javascript": ("JavaScript", "F7DF1E", "javascript", "black"),
    "rust": ("Rust", "000000", "rust", "white"),
    "go": ("Go", "00ADD8", "go", "white"),
    "c++": ("C++", "00599C", "cplusplus", "white"),
    "c": ("C", "A8B9CC", "c", "black"),
    "c#": ("C#", "239120", "csharp", "white"),
    "java": ("Java", "ED8B00", "openjdk", "white"),
    "kotlin": ("Kotlin", "7F52FF", "kotlin", "white"),
    "swift": ("Swift", "F05138", "swift", "white"),
    "ruby": ("Ruby", "CC342D", "ruby", "white"),
    "php": ("PHP", "777BB4", "php", "white"),
    "shell": ("Shell", "89E051", "gnubash", "black"),
    "powershell": ("PowerShell", "5391FE", "powershell", "white"),
    "lua": ("Lua", "000080", "lua", "white"),
    "html": ("HTML5", "E34F26", "html5", "white"),
    "css": ("CSS3", "1572B6", "css3", "white"),
    "scss": ("Sass", "CC6699", "sass", "white"),
    "vue": ("Vue", "4FC08D", "vuedotjs", "white"),
    "dart": ("Dart", "0175C2", "dart", "white"),
    "jupyter notebook": ("Jupyter", "DA5B0B", "jupyter", "white"),
    "haskell": ("Haskell", "5D4F85", "haskell", "white"),
    "zig": ("Zig", "F7A41D", "zig", "black"),
    "r": ("R", "276DC3", "r", "white"),
    "nix": ("Nix", "7EBAE7", "nixos", "white"),
    "go template": ("Go Templates", "00ADD8", "go", "white"),
    "vim script": ("Vim Script", "199F4B", "vim", "white"),
    "vimscript": ("Vim Script", "199F4B", "vim", "white"),
}

TOPIC_BADGES = {
    "react": ("React", "61DAFB", "react", "black"),
    "nextjs": ("Next.js", "000000", "nextdotjs", "white"),
    "next-js": ("Next.js", "000000", "nextdotjs", "white"),
    "astro": ("Astro", "BC52EE", "astro", "white"),
    "vite": ("Vite", "646CFF", "vite", "white"),
    "svelte": ("Svelte", "FF3E00", "svelte", "white"),
    "tailwindcss": ("Tailwind CSS", "06B6D4", "tailwindcss", "white"),
    "tailwind-css": ("Tailwind CSS", "06B6D4", "tailwindcss", "white"),
    "fastapi": ("FastAPI", "009688", "fastapi", "white"),
    "flask": ("Flask", "000000", "flask", "white"),
    "django": ("Django", "092E20", "django", "white"),
    "hono": ("Hono", "E36002", "hono", "white"),
    "bun": ("Bun", "000000", "bun", "white"),
    "nodejs": ("Node.js", "5FA04E", "nodedotjs", "white"),
    "node-js": ("Node.js", "5FA04E", "nodedotjs", "white"),
    "deno": ("Deno", "000000", "deno", "white"),
    "express": ("Express.js", "000000", "express", "black"),
    "postgresql": ("PostgreSQL", "4169E1", "postgresql", "white"),
    "postgres": ("PostgreSQL", "4169E1", "postgresql", "white"),
    "sqlite": ("SQLite", "003B57", "sqlite", "white"),
    "mysql": ("MySQL", "4479A1", "mysql", "white"),
    "redis": ("Redis", "DC382D", "redis", "white"),
    "mongodb": ("MongoDB", "47A248", "mongodb", "white"),
    "duckdb": ("DuckDB", "FFF100", "duckdb", "black"),
    "kafka": ("Apache Kafka", "231F20", "apachekafka", "white"),
    "apache-kafka": ("Apache Kafka", "231F20", "apachekafka", "white"),
    "elasticsearch": ("Elasticsearch", "005571", "elasticsearch", "white"),
    "clickhouse": ("ClickHouse", "FFCC01", "clickhouse", "black"),
    "docker": ("Docker", "2496ED", "docker", "white"),
    "kubernetes": ("Kubernetes", "326CE5", "kubernetes", "white"),
    "k8s": ("Kubernetes", "326CE5", "kubernetes", "white"),
    "terraform": ("Terraform", "7B42BC", "terraform", "white"),
    "cloudflare-workers": ("Cloudflare Workers", "F38020", "cloudflare", "white"),
    "cloudflare": ("Cloudflare Workers", "F38020", "cloudflare", "white"),
    "cf-workers": ("Cloudflare Workers", "F38020", "cloudflare", "white"),
    "aws": ("AWS", "232F3E", "amazonwebservices", "white"),
    "amazon-web-services": ("AWS", "232F3E", "amazonwebservices", "white"),
    "gcp": ("GCP", "4289C7", "googlecloud", "white"),
    "google-cloud": ("GCP", "4289C7", "googlecloud", "white"),
    "pytorch": ("PyTorch", "EE4C2C", "pytorch", "white"),
    "tensorflow": ("TensorFlow/Keras", "FF6F00", "tensorflow", "white"),
    "keras": ("Keras", "D00000", "keras", "white"),
    "scikit-learn": ("Scikit-Learn", "F7931E", "scikitlearn", "black"),
    "sklearn": ("Scikit-Learn", "F7931E", "scikitlearn", "black"),
    "pandas": ("Pandas", "150458", "pandas", "white"),
    "numpy": ("NumPy", "013243", "numpy", "white"),
    "pymc": ("PyMC Bayesian Inference", "FF6F00", None, None),
    "llm": ("LLMs Deep Learning", "555555", None, None),
    "llms": ("LLMs Deep Learning", "555555", None, None),
    "machine-learning": ("Machine Learning", "blueviolet", None, None),
    "ml": ("Machine Learning", "blueviolet", None, None),
    "websocket": ("WebSocket", "010101", None, None),
    "websockets": ("WebSocket", "010101", None, None),
    "grpc": ("gRPC", "244C5C", "grpc", "white"),
    "real-time": ("Real-Time", "009688", None, None),
    "realtime": ("Real-Time", "009688", None, None),
    "streaming": ("Streaming Pipelines", "009688", None, None),
    "turborepo": ("Turborepo Monorepo", "000000", None, None),
    "monorepo": ("Turborepo Monorepo", "000000", None, None),
    "tdd": ("TDD Test-Driven Development", "blueviolet", None, None),
}

LABEL_TO_BADGE = {spec[0]: spec for spec in list(LANG_BADGES.values()) + list(TOPIC_BADGES.values())}
BADGE_VOCAB = sorted(LABEL_TO_BADGE.keys())

HIGH_SIGNAL_KEYWORDS = [
    "pipeline", "execution", "adapter", "stream", "forecasting", "backtest",
    "correlation", "protocol", "engine", "real-time", "analytics", "visualization",
    "integration", "telemetry", "benchmark", "model", "boundary", "ledger",
    "registration", "props", "prediction", "simulation", "ingest", "portal",
    "spline", "websocket", "security", "mtls", "inference", "spatio-temporal",
]


def get_headers(token: Optional[str] = None) -> Dict[str, str]:
    headers = {
        "User-Agent": "ProjectsSyncScript/1.0",
        "Accept": "application/vnd.github+json",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def gh_get(url: str, token: Optional[str] = None) -> Optional[object]:
    req = urllib.request.Request(url, headers=get_headers(token))
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"[WARN] GitHub API returned HTTP {e.code} for {url}: {e.reason}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"[WARN] GitHub API request failed for {url}: {e}", file=sys.stderr)
        return None


def is_noise_commit(message: str) -> bool:
    """Filter out automated bot messages, churn, and merge commits."""
    msg = message.strip()
    first_line = msg.split("\n")[0].lower()

    noise_patterns = [
        r"^merge\s+(branch|pull\s+request)",
        r"^chore\(almanac\):",
        r"^chore\(deps\):",
        r"^chore\(deps-dev\):",
        r"^bump\s+.*from\s+.*to\s+",
        r"\[skip\s+ci\]",
        r"^wip$",
        r"^update\s+readme(\.md)?$",
        r"^initial\s+commit$",
        r"^build:\s*trigger",
    ]

    for pat in noise_patterns:
        if re.search(pat, first_line):
            return True

    return False


def score_and_distill_commit(msg: str) -> Tuple[int, str]:
    """Score commit significance and distill into a clean technical concept."""
    first = msg.split("\n")[0].strip()
    first = re.sub(r"\[skip\s+ci\]", "", first, flags=re.I).strip()

    clean = re.sub(r"^[a-zA-Z0-9_-]+(?:\([^\)]+\))?:\s*", "", first).strip()
    clean = re.sub(r"\s*\(#[0-9]+\)", "", clean).strip()

    score = 0
    first_lower = first.lower()

    if first_lower.startswith("feat"):
        score += 10
    elif first_lower.startswith("perf"):
        score += 8
    elif first_lower.startswith("refactor"):
        score += 5
    elif first_lower.startswith("fix"):
        score += 4
    elif first_lower.startswith("docs"):
        score += 2

    for kw in HIGH_SIGNAL_KEYWORDS:
        if kw in first_lower:
            score += 6

    distilled = re.sub(
        r"^(?:add|added|implement|implemented|update|updated|build|built|introduce|introduced|create|created|support|supporting|ensure|ensured)\s+",
        "",
        clean,
        flags=re.I
    ).strip()

    if len(distilled) > 1:
        distilled = distilled[0].lower() + distilled[1:]

    return score, distilled


def load_store(store_path: str) -> List[Dict]:
    if not os.path.exists(store_path):
        return []
    with open(store_path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_store(store_path: str, entries: List[Dict]) -> None:
    os.makedirs(os.path.dirname(store_path), exist_ok=True)
    with open(store_path, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2)
        f.write("\n")


def existing_names(entries: List[Dict]) -> Set[str]:
    return {e["name"].lower() for e in entries}


def fetch_public_repos(username: str, token: Optional[str]) -> List[Dict]:
    repos: List[Dict] = []
    page = 1
    while True:
        url = f"https://api.github.com/users/{username}/repos?type=owner&sort=pushed&direction=desc&per_page=100&page={page}"
        batch = gh_get(url, token)
        if not isinstance(batch, list) or not batch:
            break
        repos.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return repos


def repo_has_commits(full_name: str, token: Optional[str]) -> bool:
    """GitHub's cached `size` field can briefly read 0 right after a repo's
    first push, so a size==0 repo is only truly empty if it also has no commits."""
    commits = gh_get(f"https://api.github.com/repos/{full_name}/commits?per_page=1", token)
    return isinstance(commits, list) and len(commits) > 0


def select_new_repos(repos: List[Dict], username: str, existing: Set[str], max_new: int, token: Optional[str] = None) -> List[Dict]:
    new_repos = []
    for r in repos:
        name = r.get("name") or ""
        if not name or name.lower() == username.lower():
            continue
        if r.get("fork") or r.get("archived") or r.get("disabled"):
            continue
        if (r.get("size") or 0) == 0:
            full_name = r.get("full_name") or f"{username}/{name}"
            if not repo_has_commits(full_name, token):
                continue
        if name.lower() in existing:
            continue
        new_repos.append(r)

    new_repos.sort(key=lambda r: r.get("pushed_at") or "", reverse=True)
    return new_repos[:max_new]


def gather_repo_detail(repo: Dict, username: str, token: Optional[str]) -> Dict:
    full_name = repo.get("full_name") or f"{username}/{repo.get('name')}"

    languages = gh_get(f"https://api.github.com/repos/{full_name}/languages", token)
    lang_bytes: Dict[str, int] = {str(k).lower(): v for k, v in languages.items()} if isinstance(languages, dict) else {}
    langs_sorted = sorted(lang_bytes.keys(), key=lambda l: lang_bytes.get(l, 0), reverse=True)

    subjects: List[str] = []
    commits = gh_get(f"https://api.github.com/repos/{full_name}/commits?per_page=15", token)
    if isinstance(commits, list):
        for c in commits:
            author_login = ((c.get("author") or {}) or {}).get("login")
            if author_login and author_login.lower() != username.lower():
                continue
            msg = (((c.get("commit") or {}) or {}).get("message")) or ""
            if not msg or is_noise_commit(msg):
                continue
            subjects.append(msg.splitlines()[0].strip())
            if len(subjects) >= 12:
                break

    topics = repo.get("topics") or []

    return {
        "name": repo.get("name"),
        "description": (repo.get("description") or "").strip(),
        "homepage": (repo.get("homepage") or "").strip(),
        "topics": [str(t).lower() for t in topics],
        "langs_sorted": langs_sorted,
        "subjects": subjects,
    }


def synthesize_with_gemini(detail: Dict, api_key: str) -> Optional[Tuple[str, List[str]]]:
    """Synthesize one project summary + badge labels with Google Gemini."""
    langs = ", ".join(detail["langs_sorted"][:6]) or "unknown"
    topics = ", ".join(detail["topics"][:10]) or "none"
    desc = detail["description"] or "none"
    commit_lines = "\n".join(f"  - {s}" for s in detail["subjects"][:12]) or "  - (no recent commit activity)"
    vocab = ", ".join(BADGE_VOCAB)

    system_prompt = (
        "You are a Staff Technical Writer writing a 'Featured Projects' entry for Harlan Jones's GitHub profile README.\n"
        "Given a repository's description, detected technologies, and recent commit subjects, produce ONE featured-project entry.\n\n"
        "Output STRICTLY in this exact format (two lines, nothing else):\n"
        "SUMMARY: <one or two sentences describing what the project does and its most notable engineering, grounded in the recent activity; never start with the repo name; end with a period>\n"
        "BADGES: <comma-separated technology labels, up to 4, chosen ONLY from this vocabulary, most-defining first>\n"
        f"Vocabulary: {vocab}\n\n"
        "Rules:\n"
        "1. The summary must reflect both what the project is and what was recently built.\n"
        "2. No markdown, quotes, backticks, or extra lines.\n"
        "3. If BADGES vocabulary lacks an exact match for a technology, omit it rather than inventing a label."
    )

    request_body = {
        "contents": [
            {
                "parts": [
                    {"text": (
                        f"{system_prompt}\n\n"
                        f"Repository: {detail['name']}\n"
                        f"Description: {desc}\n"
                        f"Languages (by usage): {langs}\n"
                        f"Topics: {topics}\n\n"
                        f"Recent commit subjects:\n{commit_lines}"
                    )}
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 350,
        },
    }

    models = ["gemini-2.5-flash", "gemini-1.5-flash"]
    for model in models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        req = urllib.request.Request(
            url,
            data=json.dumps(request_body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=25) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                candidates = result.get("candidates", [])
                if not candidates:
                    continue
                text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")

            summary_m = re.search(r"SUMMARY:\s*(.+)", text)
            badges_m = re.search(r"BADGES:\s*(.+)", text)
            if not summary_m:
                continue

            summary = re.sub(r"\s+", " ", summary_m.group(1)).strip().strip('"').strip("`")
            if not summary:
                continue

            badges: List[str] = []
            if badges_m:
                for raw in badges_m.group(1).split(","):
                    label = raw.strip()
                    if label in LABEL_TO_BADGE and label not in badges:
                        badges.append(label)

            return summary, badges[:4]
        except Exception as e:
            print(f"[WARN] Gemini API call ({model}) failed: {e}", file=sys.stderr)

    return None


def _clean_concept(concept: str) -> str:
    concept = concept.split(". ")[0].strip().rstrip(".,;:").strip()
    if len(concept) > 140:
        cut = concept[:137].rsplit(" ", 1)[0].rstrip(",;:")
        concept = f"{cut}..."
    return concept


def synthesize_heuristics(detail: Dict) -> Tuple[str, List[str]]:
    """Template-based summary fallback: description + distilled concepts + top languages."""
    concepts: List[str] = []
    seen: Set[str] = set()
    scored: List[Tuple[int, str]] = []

    for subject in detail["subjects"]:
        score, concept = score_and_distill_commit(subject)
        if score > 0 and concept and concept.lower() not in seen:
            seen.add(concept.lower())
            scored.append((score, concept))

    scored.sort(key=lambda x: x[0], reverse=True)
    candidates = [c for c in (_clean_concept(c) for _, c in scored[:5]) if c]
    concise = [c for c in candidates if len(c) <= 110]
    concepts = (concise or candidates)[:2]

    desc = re.sub(r"\s+", " ", detail["description"]).strip()
    if len(desc) > 220:
        desc = desc[:217].rstrip() + "..."
    if desc and not desc.endswith((".", "!", "?")):
        desc += "."

    lang_labels = [LANG_BADGES[l][0] for l in detail["langs_sorted"][:2] if l in LANG_BADGES]
    tech = " and ".join(lang_labels) if lang_labels else "a polyglot stack"

    if desc and concepts:
        summary = f"{desc} Recent work includes {concepts[0]}"
        if len(concepts) > 1:
            summary += f" and {concepts[1]}"
        summary += f", built with {tech}."
    elif desc:
        summary = f"{desc} Built with {tech}."
    elif concepts:
        joined = f"{concepts[0]} and {concepts[1]}" if len(concepts) > 1 else concepts[0]
        summary = f"Active development focused on {joined}, built with {tech}."
    else:
        summary = f"Recently published {tech} project."

    badges: List[str] = []
    for l in detail["langs_sorted"][:2]:
        if l in LANG_BADGES:
            badges.append(LANG_BADGES[l][0])
    for t in detail["topics"]:
        spec = TOPIC_BADGES.get(t)
        if spec and spec[0] not in badges:
            badges.append(spec[0])
        if len(badges) >= 4:
            break

    return summary, badges[:4]


def build_entry(name: str, summary: str, badges: List[str], homepage: str) -> Dict:
    name = name.strip()
    if not summary.endswith("."):
        summary += "."
    return {"name": name, "summary": summary, "badges": badges[:4], "homepage": homepage}


def _badge_fill(label: str) -> Tuple[str, str]:
    spec = LABEL_TO_BADGE.get(label)
    if spec:
        _, color, _, logo_color = spec
        # Most entries store a bare hex code (for shields.io URLs); a few use
        # a CSS color name (e.g. "blueviolet") directly.
        is_hex = len(color) == 6 and all(c in "0123456789abcdefABCDEF" for c in color)
        fill = f"#{color}" if is_hex else color
        text_color = "#ffffff" if logo_color == "white" else ON_ACCENT
    else:
        # One-off labels (e.g. "PostGIS", "Performance") have no curated color;
        # derive a stable one so they still render instead of vanishing.
        fill = FALLBACK_PALETTE[_stable_color_index(label, len(FALLBACK_PALETTE))]
        text_color = "#ffffff"
    return fill, text_color


def _render_entry_block(x: float, y: float, entry: Dict, col_width: float) -> Tuple[str, float]:
    """Renders one project's name/summary/badges inside a column starting at
    (x, y). Returns (svg_fragment, height_used)."""
    name = entry["name"]
    summary = entry["summary"]
    badges = entry.get("badges") or []
    homepage = entry.get("homepage") or ""
    frags = []
    cy = y

    if homepage:
        live_w = len("LIVE") * 11 * 0.62 + 18
        name_max_w = col_width - live_w - 10
    else:
        live_w = 0.0
        name_max_w = col_width
    name_display = truncate(name, 15, name_max_w, bold=True)
    frags.append(
        f'<text x="{x:.1f}" y="{cy + 15:.1f}" font-size="15" font-weight="700" '
        f'fill="#58a6ff" font-family="{FONT_FAMILY}">{esc(name_display)}</text>'
    )
    if homepage:
        live_x = x + col_width - live_w
        frags.append(
            f'<g transform="translate({live_x:.1f},{cy - 1:.1f})">'
            f'<rect width="{live_w:.1f}" height="18" rx="9" fill="#238636"/>'
            f'<text x="{live_w / 2:.1f}" y="13" font-size="10.5" font-weight="700" fill="#ffffff" '
            f'text-anchor="middle" font-family="{FONT_FAMILY}">LIVE</text>'
            f"</g>"
        )
    cy += 24

    for line in wrap_by_width(plain_text(summary), 12.5, col_width, max_lines=3):
        frags.append(
            f'<text x="{x:.1f}" y="{cy + 12:.1f}" font-size="12.5" fill="{TEXT}" '
            f'font-family="{FONT_FAMILY}">{esc(line)}</text>'
        )
        cy += 18

    cy += 6
    pill_labels = [( label, *_badge_fill(label)) for label in badges]
    if pill_labels:
        pills_svg, pills_h = flow_pills(x, cy, pill_labels, x + col_width, row_height=25)
        frags.append(pills_svg)
        cy += pills_h
    else:
        cy += 4

    return "\n".join(frags), cy - y


def render_projects_svg(entries: List[Dict], columns: int = 2) -> str:
    gap = 28
    col_width = (CARD_WIDTH - PAD_X * 2 - gap * (columns - 1)) / columns
    frags = []
    cy = 10.0
    row_gap = 22

    for row_start in range(0, len(entries), columns):
        row = entries[row_start:row_start + columns]
        col_heights = []
        for col_i, entry in enumerate(row):
            x = PAD_X + col_i * (col_width + gap)
            svg, h = _render_entry_block(x, cy, entry, col_width)
            frags.append(svg)
            col_heights.append(h)
        row_h = max(col_heights)
        cy += row_h + row_gap
        if row_start + columns < len(entries):
            frags.append(f'<line x1="{PAD_X}" y1="{cy - row_gap / 2:.1f}" x2="{CARD_WIDTH - PAD_X}" y2="{cy - row_gap / 2:.1f}" stroke="{MUTED}" stroke-opacity="0.25"/>')

    body_height = cy
    subtitle = f"{len(entries)} public repositories"
    return card_shell("Featured Projects", subtitle, "\n".join(frags), body_height, accent=ACCENT_ORANGE)


def ensure_readme_image(readme_path: str, svg_url: str) -> bool:
    """Inserts a single <img> tag above PROJECTS_END once; leaves it alone on later runs."""
    if not os.path.exists(readme_path):
        print(f"[ERROR] README not found at {readme_path}", file=sys.stderr)
        return False

    with open(readme_path, "r", encoding="utf-8") as f:
        content = f.read()

    img_tag = f'<img src="{svg_url}" alt="Featured Projects" width="100%" />'
    if svg_url in content:
        print("[INFO] README.md already embeds the Featured Projects image.")
        return False

    if PROJECTS_ANCHOR in content:
        updated = content.replace(PROJECTS_ANCHOR, f"{img_tag}\n{PROJECTS_ANCHOR}", 1)
    else:
        print("[ERROR] Projects anchor missing; aborting.", file=sys.stderr)
        return False

    with open(readme_path, "w", encoding="utf-8") as f:
        f.write(updated)
    print(f"[OK] Inserted Featured Projects image tag into {readme_path}")
    return True


def main():
    parser = argparse.ArgumentParser(description="Sync newly published public repos into the Featured Projects card.")
    parser.add_argument("--username", default="harlanljones", help="GitHub username")
    parser.add_argument("--readme", default="README.md", help="Path to README.md")
    parser.add_argument("--store", default=DEFAULT_STORE, help="Path to the JSON entry store")
    parser.add_argument("--svg-out", default="projects.svg", help="Path to write the rendered SVG card")
    parser.add_argument("--svg-url", default="https://raw.githubusercontent.com/harlanljones/harlanljones/profile-cards/projects.svg",
                         help="URL the README <img> tag should point at")
    parser.add_argument("--token", default=os.getenv("GITHUB_TOKEN"), help="GitHub API Token")
    parser.add_argument("--gemini-api-key", default=os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"), help="Gemini API Key")
    parser.add_argument("--max-new", type=int, default=5, help="Maximum new entries per run")
    parser.add_argument("--dry-run", action="store_true", help="Print output without writing any files")

    args = parser.parse_args()

    entries = load_store(args.store)
    existing = existing_names(entries)
    print(f"[INFO] Found {len(existing)} repositories already tracked in {args.store}.")

    print(f"[INFO] Fetching public repositories for {args.username}...")
    repos = fetch_public_repos(args.username, args.token)
    if not repos:
        print("[ERROR] Could not fetch public repositories; aborting.", file=sys.stderr)
        sys.exit(1)
    print(f"[INFO] Discovered {len(repos)} public repositories.")

    new_repos = select_new_repos(repos, args.username, existing, args.max_new, args.token)
    if new_repos:
        print(f"[INFO] {len(new_repos)} new repositories to add:")
        for r in new_repos:
            print(f"   + {r.get('name')}")

        for repo in new_repos:
            detail = gather_repo_detail(repo, args.username, args.token)
            print(f"[INFO] Synthesizing entry for {detail['name']} ({len(detail['subjects'])} signal commits)...")

            synthesized = None
            if args.gemini_api_key:
                synthesized = synthesize_with_gemini(detail, args.gemini_api_key)
                if not synthesized:
                    print(f"[INFO] Gemini synthesis unavailable for {detail['name']}; using heuristic engine.")

            if synthesized:
                summary, badges = synthesized
            else:
                summary, badges = synthesize_heuristics(detail)

            entries.append(build_entry(detail["name"], summary, badges, detail["homepage"]))
    else:
        print("[INFO] No new public repositories to add.")

    svg = render_projects_svg(entries)

    if args.dry_run:
        print("\n--- DRY RUN OUTPUT (SVG omitted, entries below) ---")
        print(json.dumps(entries, indent=2))
        print("----------------------\n")
        sys.exit(0)

    if new_repos:
        save_store(args.store, entries)
        print(f"[OK] Saved {len(entries)} total entries to {args.store}")

    with open(args.svg_out, "w", encoding="utf-8") as f:
        f.write(svg)
    for path in write_theme_pair(args.svg_out, svg):
        print(f"[OK] Wrote {path}")
    print(f"[OK] Wrote {args.svg_out}")

    ensure_readme_image(args.readme, args.svg_url)
    update_readme_featured_repos(args.readme, entries, args.username)


if __name__ == "__main__":
    main()
