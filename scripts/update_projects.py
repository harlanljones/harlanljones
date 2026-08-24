#!/usr/bin/env python3
"""
Featured Projects Sync Automation.

Checks the user's public GitHub repositories and appends any repository not
already listed in the README "Featured Projects" section. Existing entries are
never reordered or rewritten; new entries are appended at the bottom of the
list, above the <!-- PROJECTS_END --> anchor.

Each generated entry carries a brief summary synthesized from recent
project-level commit activity plus detected technologies (languages + topics),
rendered with shields.io badges in the existing README style.
"""

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, List, Optional, Set, Tuple

PROJECTS_ANCHOR = "<!-- PROJECTS_END -->"
SECTION_HEADING = "### Featured Projects"

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


def extract_existing_names(content: str) -> Set[str]:
    """Collect repo names already linked inside the Featured Projects section only."""
    m = re.search(rf"{re.escape(SECTION_HEADING)}(.*?)(?=\n---\n)", content, re.DOTALL)
    if not m:
        print(f"[ERROR] Could not locate '{SECTION_HEADING}' section in README.", file=sys.stderr)
        sys.exit(1)

    section = m.group(1)
    names = set(n.lower() for n in re.findall(r"github\.com/[A-Za-z0-9-]+/([A-Za-z0-9_.\-]+)", section))
    return names


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


def select_new_repos(repos: List[Dict], username: str, existing: Set[str], max_new: int) -> List[Dict]:
    new_repos = []
    for r in repos:
        name = r.get("name") or ""
        if not name or name.lower() == username.lower():
            continue
        if r.get("fork") or r.get("archived") or r.get("disabled"):
            continue
        if (r.get("size") or 0) == 0:
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


def _shields_text(s: str) -> str:
    return s.replace("-", "--").replace("_", "__").replace(" ", "_")


def render_badge(label: str) -> str:
    spec = LABEL_TO_BADGE.get(label)
    if not spec:
        return ""
    _, color, logo, logo_color = spec
    text = _shields_text(label)
    url = f"https://img.shields.io/badge/{text}-{color}?style=flat-square"
    if logo:
        url += f"&logo={logo}&logoColor={logo_color}"
    return f"![{label}]({url})"


def render_live_demo_badge(homepage: str) -> str:
    host = urllib.parse.urlparse(homepage).netloc if "://" in homepage else homepage
    host = host.rstrip("/")
    text = f"Live_Demo-{_shields_text(host)}"
    url = f"https://img.shields.io/badge/{text}-F38020?style=flat-square&logo=cloudflare&logoColor=white"
    link = homepage if "://" in homepage else f"https://{homepage}"
    return f"[![Live Demo]({url})]({link})"


def build_entry(name: str, summary: str, badges: List[str], homepage: str) -> str:
    name = name.strip()
    if not summary.endswith("."):
        summary += "."
    lines = [f"* **[{name}](https://github.com/harlanljones/{name})** — {summary}"]

    rendered = []
    if homepage:
        rendered.append(render_live_demo_badge(homepage))
    for label in badges[:4]:
        b = render_badge(label)
        if b:
            rendered.append(b)

    for b in rendered:
        lines.append(f"  {b}")

    return "\n".join(lines)


def append_entries(readme_path: str, entry_blocks: List[str]) -> bool:
    """Append-only insert above the PROJECTS_END anchor; never touches existing content."""
    if not os.path.exists(readme_path):
        print(f"[ERROR] README not found at {readme_path}", file=sys.stderr)
        return False

    with open(readme_path, "r", encoding="utf-8") as f:
        content = f.read()

    block = "\n\n".join(entry_blocks)

    if PROJECTS_ANCHOR in content:
        updated = content.replace(PROJECTS_ANCHOR, f"{block}\n{PROJECTS_ANCHOR}", 1)
    else:
        m = re.search(rf"{re.escape(SECTION_HEADING)}", content)
        if not m:
            print("[ERROR] Featured Projects heading and anchor both missing; aborting.", file=sys.stderr)
            return False
        insert_at = content.find("\n---\n", m.start())
        if insert_at == -1:
            print("[ERROR] Could not find end of Featured Projects section; aborting.", file=sys.stderr)
            return False
        updated = content[:insert_at] + f"\n{block}\n" + content[insert_at:]

    if updated != content:
        with open(readme_path, "w", encoding="utf-8") as f:
            f.write(updated)
        print(f"[OK] Appended {len(entry_blocks)} new project entr{'y' if len(entry_blocks) == 1 else 'ies'} to {readme_path}")
        return True

    print("[INFO] No changes needed in README.md")
    return False


def main():
    parser = argparse.ArgumentParser(description="Sync newly published public repos into the Featured Projects README section.")
    parser.add_argument("--username", default="harlanljones", help="GitHub username")
    parser.add_argument("--readme", default="README.md", help="Path to README.md")
    parser.add_argument("--token", default=os.getenv("GITHUB_TOKEN"), help="GitHub API Token")
    parser.add_argument("--gemini-api-key", default=os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"), help="Gemini API Key")
    parser.add_argument("--max-new", type=int, default=5, help="Maximum new entries per run")
    parser.add_argument("--dry-run", action="store_true", help="Print output without writing to README.md")

    args = parser.parse_args()

    if not os.path.exists(args.readme):
        print(f"[ERROR] README not found at {args.readme}", file=sys.stderr)
        sys.exit(1)

    with open(args.readme, "r", encoding="utf-8") as f:
        content = f.read()

    existing = extract_existing_names(content)
    print(f"[INFO] Found {len(existing)} repositories already listed under '{SECTION_HEADING}'.")

    print(f"[INFO] Fetching public repositories for {args.username}...")
    repos = fetch_public_repos(args.username, args.token)
    if not repos:
        print("[ERROR] Could not fetch public repositories; aborting.", file=sys.stderr)
        sys.exit(1)
    print(f"[INFO] Discovered {len(repos)} public repositories.")

    new_repos = select_new_repos(repos, args.username, existing, args.max_new)
    if not new_repos:
        print("[INFO] No new public repositories to add.")
        sys.exit(0)
    print(f"[INFO] {len(new_repos)} new repositories to append:")
    for r in new_repos:
        print(f"   + {r.get('name')}")

    entry_blocks: List[str] = []
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

        entry_blocks.append(build_entry(detail["name"], summary, badges, detail["homepage"]))

    markdown_block = "\n\n".join(entry_blocks)

    if args.dry_run:
        print("\n--- DRY RUN OUTPUT ---")
        print(markdown_block)
        print("----------------------\n")
        sys.exit(0)

    append_entries(args.readme, entry_blocks)


if __name__ == "__main__":
    main()
