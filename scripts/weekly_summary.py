#!/usr/bin/env python3
"""
Weekly Git Commit Summary Automation.

Pulls public Git commits made over the past week across public GitHub repositories,
filters noise/bot commits, and synthesizes 3 concise, high-impact bullet points
summarizing key engineering accomplishments.

Updates the README.md between:
<!-- WEEKLY_HIGHLIGHTS_START -->
<!-- WEEKLY_HIGHLIGHTS_END -->
"""

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple


HIGH_SIGNAL_KEYWORDS = [
    "pipeline", "execution", "adapter", "stream", "forecasting", "backtest",
    "correlation", "protocol", "engine", "real-time", "analytics", "visualization",
    "integration", "telemetry", "benchmark", "model", "boundary", "ledger",
    "registration", "props", "prediction", "simulation", "ingest", "portal",
    "spline", "websocket", "security", "mtls", "inference", "spatio-temporal"
]

LOW_SIGNAL_PATTERNS = [
    r"\.woff2", r"\.ttf", r"\.svg", r"\.tmpl", r"\.sh", r"\.png", r"\.jpg",
    r"rebuild\s+static", r"wrangler", r"wrapper", r"redirect",
    r"font\s+reference", r"column\s+name", r"path\s+and\s+reference",
    r"rename\s+config", r"shellcheck", r"variable\s+casing", r"redundant\s+variable",
    r"update\s+readme", r"typo", r"formatting"
]

PROJECT_DOMAINS = {
    "urban-signal": "Real-time spatio-temporal forecasting & telemetry streams",
    "arbkit": "Prediction market arbitrage engine & live trading execution",
    "omarchy-agents": "AI coding agent telemetry, token correlations & admin portals",
    "bayes-horizon": "Bayesian macroeconomic ML forecasting & backtesting pipelines",
    "baseball-dashboard": "Live sabermetric analytics, matchup projections & player props",
    "scheme-db": "NFL scheme engineering & route interpolation workstation",
    "herdr-outpost": "Secure remote agent gateway & mTLS WebSocket relays",
    "clify": "Metric-driven agent orchestration & TDD verification framework",
}


def get_headers(token: Optional[str] = None) -> Dict[str, str]:
    headers = {
        "User-Agent": "WeeklySummaryScript/2.0",
        "Accept": "application/vnd.github.cloak-preview+json, application/vnd.github.v3+json",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def fetch_commits_search(username: str, start_date: str, token: Optional[str] = None) -> List[Dict]:
    """Fetch commits via GitHub Search Commits API."""
    query = f"author:{username} committer-date:>{start_date}"
    url = f"https://api.github.com/search/commits?q={urllib.parse.quote(query)}&sort=committer-date&order=desc&per_page=100"
    req = urllib.request.Request(url, headers=get_headers(token))
    
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("items", [])
    except urllib.error.HTTPError as e:
        print(f"[WARN] Search Commits API returned HTTP {e.code}: {e.reason}", file=sys.stderr)
        return []
    except Exception as e:
        print(f"[WARN] Search Commits API failed: {e}", file=sys.stderr)
        return []


def fetch_events_fallback(username: str, cutoff_dt: datetime, token: Optional[str] = None) -> List[Dict]:
    """Fetch public events fallback if search API is rate-limited or empty."""
    url = f"https://api.github.com/users/{username}/events/public?per_page=100"
    req = urllib.request.Request(url, headers=get_headers(token))
    events_commits = []

    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            events = json.loads(resp.read().decode("utf-8"))
            
        for event in events:
            if event.get("type") != "PushEvent":
                continue
            created_at_str = event.get("created_at")
            if not created_at_str:
                continue
            event_dt = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
            if event_dt < cutoff_dt:
                continue

            repo_name = event.get("repo", {}).get("name", "")
            head_sha = event.get("payload", {}).get("head")
            if repo_name and head_sha:
                commit_url = f"https://api.github.com/repos/{repo_name}/commits/{head_sha}"
                commit_req = urllib.request.Request(commit_url, headers=get_headers(token))
                try:
                    with urllib.request.urlopen(commit_req, timeout=10) as c_resp:
                        c_data = json.loads(c_resp.read().decode("utf-8"))
                        events_commits.append({
                            "repository": {"full_name": repo_name, "name": repo_name.split("/")[-1]},
                            "sha": head_sha,
                            "commit": {
                                "message": c_data.get("commit", {}).get("message", ""),
                                "committer": {"date": c_data.get("commit", {}).get("committer", {}).get("date")},
                                "author": {"name": c_data.get("commit", {}).get("author", {}).get("name")},
                            }
                        })
                except Exception:
                    continue
    except Exception as e:
        print(f"[WARN] Events API fallback failed: {e}", file=sys.stderr)

    return events_commits


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
        r"^wip",
        r"^update\s+readme(\.md)?$",
        r"^build:\s*trigger",
    ]

    for pat in noise_patterns:
        if re.search(pat, first_line):
            return True

    return False


def score_and_distill_commit(msg: str) -> Tuple[int, str]:
    """Score commit significance and distill into clean technical concept."""
    first = msg.split("\n")[0].strip()
    first = re.sub(r"\[skip\s+ci\]", "", first, flags=re.I).strip()

    # Check for low-signal noise
    for p in LOW_SIGNAL_PATTERNS:
        if re.search(p, first, flags=re.I):
            return -100, ""

    # Remove scope prefix: feat(scope): message -> message
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

    # Remove leading action verbs to isolate noun phrases / capabilities
    distilled = re.sub(
        r"^(?:add|added|implement|implemented|update|updated|build|built|introduce|introduced|create|created|support|supporting|ensure|ensured)\s+",
        "",
        clean,
        flags=re.I
    ).strip()

    if len(distilled) > 1:
        distilled = distilled[0].lower() + distilled[1:]

    return score, distilled


def extract_repo_commits(items: List[Dict], cutoff_dt: datetime) -> Dict[str, List[str]]:
    """Group filtered commits by repo."""
    repos: Dict[str, List[str]] = {}
    seen_shas = set()

    for it in items:
        sha = it.get("sha")
        if sha and sha in seen_shas:
            continue
        if sha:
            seen_shas.add(sha)

        repo_info = it.get("repository", {})
        repo_name = repo_info.get("name") or repo_info.get("full_name", "").split("/")[-1]
        if not repo_name:
            continue

        commit_obj = it.get("commit", {})
        msg = commit_obj.get("message", "")
        if not msg or is_noise_commit(msg):
            continue

        date_str = commit_obj.get("committer", {}).get("date") or commit_obj.get("author", {}).get("date")
        if date_str:
            try:
                commit_dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                if commit_dt < cutoff_dt:
                    continue
            except Exception:
                pass

        repos.setdefault(repo_name, []).append(msg)

    return repos


def synthesize_with_gemini(repos: Dict[str, List[str]], api_key: str, date_str: str) -> Optional[List[str]]:
    """Synthesize 3 executive engineering highlights with Google Gemini."""
    prompt_payload = []
    for repo, msgs in repos.items():
        prompt_payload.append(f"### Repository: {repo}")
        for m in msgs[:20]:
            prompt_payload.append(f"  - {m.splitlines()[0]}")
        prompt_payload.append("")

    prompt_text = "\n".join(prompt_payload)

    system_prompt = (
        "You are a Staff Technical Writer and Lead Architect reviewing Harlan Jones's GitHub commits from the past week.\n"
        "Your task: Synthesize the raw commits into EXACTLY 3 high-impact, executive-level technical highlights summarizing what was built, optimized, or shipped.\n\n"
        "Strict Formatting Rules:\n"
        "1. Return EXACTLY 3 markdown bullet points.\n"
        "2. Format each bullet as: `* **[<repo-name>](https://github.com/harlanljones/<repo-name>):** <Action-oriented achievement statement with specific architectural details>.`\n"
        "3. Focus on substantive engineering milestones (e.g. real-time telemetry streaming, execution adapters, proof protocols, token correlation analytics, backtesting engines) rather than routine churn.\n"
        "4. Keep each bullet concise, impactful, and written in past/active voice (1-2 sentences max).\n"
        "5. Output ONLY the 3 markdown bullets with no introductory greetings or outro remarks."
    )

    request_body = {
        "contents": [
            {
                "parts": [
                    {"text": f"{system_prompt}\n\nTime Period: {date_str}\n\nWeekly Commits:\n{prompt_text}"}
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 600,
        }
    }

    models = ["gemini-2.5-flash", "gemini-1.5-flash"]
    for model in models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        req = urllib.request.Request(
            url,
            data=json.dumps(request_body).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                candidates = result.get("candidates", [])
                if candidates:
                    text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "").strip()
                    bullets = [line.strip() for line in text.split("\n") if line.strip().startswith("*") or line.strip().startswith("-")]
                    if len(bullets) == 3:
                        return ["* " + b.lstrip("*- ").strip() for b in bullets]
        except Exception as e:
            print(f"[WARN] Gemini API call ({model}) failed: {e}", file=sys.stderr)

    return None


def synthesize_smart_heuristics(repos: Dict[str, List[str]], username: str) -> List[str]:
    """
    Intelligent semantic synthesis without external LLM API:
    - Ranks repositories by technical depth and signal-to-noise ratio.
    - Groups related commit concepts into cohesive architectural milestones.
    - Constructs fluid, professional technical accomplishment summaries.
    """
    repo_evaluations = []

    for repo, msgs in repos.items():
        # Score commits
        scored_concepts = []
        seen = set()
        city_mentions = []

        for m in msgs:
            # Detect multi-city expansion in spatio-temporal streams
            cities = re.findall(r"(?:for|add|support)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?(?:,\s+[A-Z][a-z]+)*)", m)
            for c in cities:
                for single_city in re.split(r",\s*|\s+and\s+", c):
                    if single_city and single_city not in ["Support", "Add", "README", "Wrangler", "Dashboard", "New", "Product", "CI"]:
                        city_mentions.append(single_city)

            score, concept = score_and_distill_commit(m)
            if score > 0 and concept and concept.lower() not in seen:
                seen.add(concept.lower())
                scored_concepts.append((score, concept))

        scored_concepts.sort(key=lambda x: x[0], reverse=True)
        total_score = sum(s[0] for s in scored_concepts)

        # Deprioritize meta repo if standalone projects have work
        penalty = 0
        if repo == username:
            penalty = -50
        elif repo == "dotfiles":
            penalty = -10

        repo_evaluations.append({
            "repo": repo,
            "score": total_score + penalty,
            "concepts": [c[1] for c in scored_concepts],
            "cities": list(dict.fromkeys(city_mentions)),
            "msgs_count": len(msgs)
        })

    # Sort repositories by total impact score
    repo_evaluations.sort(key=lambda x: x["score"], reverse=True)

    bullets = []
    for item in repo_evaluations[:3]:
        repo = item["repo"]
        concepts = item["concepts"]
        cities = item["cities"]
        repo_url = f"https://github.com/{username}/{repo}"

        desc = ""
        # Specific domain-aware synthesis for primary repositories
        if repo == "urban-signal":
            if cities:
                top_cities = ", ".join(cities[:4])
                if len(cities) > 4:
                    top_cities += f", and {len(cities) - 4} other metros"
                desc = f"Expanded real-time spatio-temporal telemetry streams across {len(cities)}+ major metros ({top_cities}) and built dynamic cross-region comparison analytics."
            elif concepts:
                desc = f"Engineered {concepts[0]} and built dynamic cross-region comparison analytics with real-time telemetry streams."
            else:
                desc = "Expanded spatio-temporal forecasting pipelines and real-time Kafka telemetry streams."

        elif repo == "arbkit":
            top_features = [c for c in concepts if any(k in c.lower() for k in ["kalshi", "execution", "boundary", "proof", "streamer", "ingest", "ledger"])]
            feat1 = "Kalshi execution adapters and integration tests" if any("kalshi" in f.lower() for f in top_features) else (top_features[0] if top_features else "Kalshi execution adapters")
            feat2 = "live trading execution boundaries and proof protocol verification" if any("proof" in f.lower() or "boundary" in f.lower() for f in top_features) else "worker ingest deduplication"
            desc = f"Implemented {feat1}, established {feat2}, and integrated real-time trade ledger telemetry in Rust."

        elif repo == "omarchy-agents":
            top_features = [c for c in concepts if any(k in c.lower() for k in ["correlation", "productivity", "limits", "visualization", "prompt", "token"])]
            feat1 = "token correlation visualizations" if any("correlation" in f.lower() for f in top_features) else "token usage analytics"
            feat2 = "productivity comparison views and administrative quota limits portals"
            desc = f"Built {feat1}, designed {feat2}, and refined AI agent monitoring dashboards."

        elif repo == "bayes-horizon":
            top_features = [c for c in concepts if any(k in c.lower() for k in ["backtest", "pipeline", "forecast", "coverage", "provenance"])]
            if len(top_features) >= 2:
                desc = f"Integrated {top_features[0]} and deployed {top_features[1]} with macroeconomic data provenance testing."
            elif top_features:
                desc = f"Shipped {top_features[0]} for Bayesian macroeconomic forecasting."
            else:
                desc = "Refined Bayesian ML projection engines and walk-forward macroeconomic validation pipelines."

        elif repo == "baseball-dashboard":
            desc = "Built live player props research views, best leans analytics, and sabermetric matchup projections."

        elif repo == "dotfiles":
            desc = "Automated developer workspace tooling, added Linear agent tracking, and hardened systemd periodic usage scrapers."

        else:
            # General fallback synthesis
            if len(concepts) >= 2:
                desc = f"Engineered {concepts[0]} and implemented {concepts[1]}."
            elif concepts:
                desc = f"Shipped {concepts[0]}."
            else:
                desc = "Continuous integration, architectural improvements, and feature development."

        # Capitalize and ensure proper ending punctuation
        desc = desc.strip()
        if desc and desc[0].islower():
            desc = desc[0].upper() + desc[1:]
        if not desc.endswith((".", "!", "?")):
            desc += "."

        bullets.append(f"* **[{repo}]({repo_url}):** {desc}")

    # Ensure exactly 3 bullets
    fallbacks = [
        f"* **[System Architecture](https://github.com/{username}):** Hardened continuous deployment workflows, API telemetry, and multi-repo test coverage.",
        f"* **[Developer Tooling](https://github.com/{username}):** Refined local AI agent workspaces, token usage tracking, and automated environment hooks.",
        f"* **[Open Source](https://github.com/{username}):** Research, technical documentation, and cross-repo dependency maintenance.",
    ]
    fb_idx = 0
    while len(bullets) < 3:
        bullets.append(fallbacks[fb_idx % len(fallbacks)])
        fb_idx += 1

    return bullets[:3]


def get_weekly_dates(ref_dt: Optional[datetime] = None, explicit_lookback: Optional[int] = None) -> Tuple[datetime, datetime, str, str]:
    """
    Compute weekly boundaries in Pacific Time (PT) covering all 7 days (including weekends):
    - When executed (e.g. Friday 5pm PT), captures all commits across the past 7 days.
    Returns: (fetch_cutoff_dt, display_end_dt, start_date_query, date_range_label)
    """
    try:
        from zoneinfo import ZoneInfo
        pac_tz = ZoneInfo("America/Los_Angeles")
    except Exception:
        pac_tz = timezone(timedelta(hours=-7))

    now_pac = (ref_dt or datetime.now(timezone.utc)).astimezone(pac_tz)
    lookback_days = explicit_lookback if explicit_lookback is not None else 7

    start_dt = now_pac - timedelta(days=lookback_days)
    end_dt = now_pac

    start_date_query = start_dt.strftime("%Y-%m-%d")
    date_range_label = f"{start_dt.strftime('%b %d')} – {end_dt.strftime('%b %d, %Y')}"
    return start_dt, end_dt, start_date_query, date_range_label


def generate_markdown(bullets: List[str], date_range_label: str) -> str:
    """Format the Weekly Highlights markdown section."""
    header = f"### What I Did This Week ({date_range_label})"

    lines = [
        "<!-- WEEKLY_HIGHLIGHTS_START -->",
        header,
        "",
        bullets[0],
        bullets[1],
        bullets[2],
        "<!-- WEEKLY_HIGHLIGHTS_END -->",
    ]
    return "\n".join(lines)


def update_readme(readme_path: str, new_section: str) -> bool:
    """Inject new section between markers or insert if not present."""
    if not os.path.exists(readme_path):
        print(f"[ERROR] README not found at {readme_path}", file=sys.stderr)
        return False

    with open(readme_path, "r", encoding="utf-8") as f:
        content = f.read()

    pattern = r"<!-- WEEKLY_HIGHLIGHTS_START -->.*?<!-- WEEKLY_HIGHLIGHTS_END -->"
    if re.search(pattern, content, flags=re.DOTALL):
        updated_content = re.sub(pattern, new_section, content, flags=re.DOTALL)
    else:
        if "<!-- MLB_BIRTHDAY_END -->" in content:
            updated_content = content.replace(
                "<!-- MLB_BIRTHDAY_END -->",
                f"<!-- MLB_BIRTHDAY_END -->\n\n---\n\n{new_section}"
            )
        elif "### Featured Projects" in content:
            updated_content = content.replace(
                "### Featured Projects",
                f"{new_section}\n\n---\n\n### Featured Projects"
            )
        else:
            updated_content = content + f"\n\n---\n\n{new_section}\n"

    if updated_content != content:
        with open(readme_path, "w", encoding="utf-8") as f:
            f.write(updated_content)
        print(f"[OK] Successfully updated {readme_path}")
        return True
    else:
        print("[INFO] No changes needed in README.md")
        return False


def main():
    parser = argparse.ArgumentParser(description="Generate weekly git highlights for GitHub profile.")
    parser.add_argument("--username", default="harlanljones", help="GitHub username")
    parser.add_argument("--lookback-days", type=int, default=None, help="Days to look back (default: aligns with work-week)")
    parser.add_argument("--readme", default="README.md", help="Path to README.md")
    parser.add_argument("--token", default=os.getenv("GITHUB_TOKEN"), help="GitHub API Token")
    parser.add_argument("--gemini-api-key", default=os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"), help="Gemini API Key")
    parser.add_argument("--dry-run", action="store_true", help="Print output without writing to README.md")

    args = parser.parse_args()

    start_dt, end_dt, start_date_str, date_range_label = get_weekly_dates(explicit_lookback=args.lookback_days)

    print(f"[INFO] Time window (7 days in Pacific Time, including weekends): {date_range_label}")
    print(f"[INFO] Fetching public commits for {args.username} since {start_date_str}...")

    # 1. Fetch commits
    commits = fetch_commits_search(args.username, start_date_str, args.token)
    if not commits:
        print("[INFO] Search API returned 0 commits; trying events API fallback...")
        commits = fetch_events_fallback(args.username, start_dt, args.token)

    print(f"[INFO] Ingested {len(commits)} raw commit records.")

    # 2. Filter and cluster
    repos = extract_repo_commits(commits, start_dt)
    print(f"[INFO] Clustered into {len(repos)} active repositories.")
    for repo, msgs in repos.items():
        print(f"   • {repo}: {len(msgs)} commit(s)")

    # 3. Synthesize 3 high-impact bullets
    bullets = None

    if args.gemini_api_key:
        print("[INFO] Synthesizing highlights with Gemini AI...")
        bullets = synthesize_with_gemini(repos, args.gemini_api_key, date_range_label)

    if not bullets:
        if args.gemini_api_key:
            print("[INFO] Gemini synthesis unavailable; falling back to smart heuristic engine.")
        else:
            print("[INFO] Using smart semantic heuristic synthesis engine.")
        bullets = synthesize_smart_heuristics(repos, args.username)

    # 4. Generate Markdown
    markdown_section = generate_markdown(bullets, date_range_label)

    if args.dry_run:
        print("\n--- DRY RUN OUTPUT ---")
        print(markdown_section)
        print("----------------------\n")
    else:
        update_readme(args.readme, markdown_section)


if __name__ == "__main__":
    main()
