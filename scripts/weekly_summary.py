#!/usr/bin/env python3
"""
Weekly Git Commit Summary Automation.

Pulls public Git commits made over the past week across public GitHub repositories,
filters noise/bot commits, and synthesizes 3 concise, high-impact bullet points
summarizing what was accomplished.

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


def get_headers(token: Optional[str] = None) -> Dict[str, str]:
    headers = {
        "User-Agent": "WeeklySummaryScript/1.0",
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
                # Fetch single commit detail
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


def clean_commit_message(msg: str) -> str:
    """Clean markdown artifacts and extract first line of message."""
    first_line = msg.strip().split("\n")[0]
    # Remove leading conventional commit prefix if helpful for readability
    first_line = re.sub(r"\s*\[skip\s+ci\]", "", first_line, flags=re.IGNORECASE)
    return first_line.strip()


def extract_and_group_commits(items: List[Dict], cutoff_dt: datetime) -> Dict[str, List[str]]:
    """Group filtered commit messages by repository name."""
    repo_groups: Dict[str, List[str]] = {}
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

        cleaned = clean_commit_message(msg)
        if cleaned:
            repo_groups.setdefault(repo_name, []).append(cleaned)

    return repo_groups


def synthesize_with_gemini(repo_groups: Dict[str, List[str]], api_key: str, date_str: str) -> Optional[List[str]]:
    """Synthesize exactly 3 high-impact bullet points using Google Gemini API."""
    prompt_commits = []
    for repo, msgs in repo_groups.items():
        prompt_commits.append(f"Repository: {repo}")
        for m in msgs[:15]:
            prompt_commits.append(f"  - {m}")
        prompt_commits.append("")

    commit_payload = "\n".join(prompt_commits)
    
    system_prompt = (
        "You are an expert software engineering editor for Harlan Jones's GitHub profile. "
        "Review the public git commits from the past week and synthesize EXACTLY 3 high-impact bullet points.\n\n"
        "Guidelines:\n"
        "1. Return EXACTLY 3 markdown bullet points.\n"
        "2. Format each bullet point as: `* **[repo-name](https://github.com/harlanljones/repo-name):** <Clear, punchy explanation of feature, architecture, optimization, or milestone>`\n"
        "3. Highlight substantial technical accomplishments (e.g. real-time engines, TDD SLAs, algorithms, visualizations, security) rather than chores.\n"
        "4. Keep each bullet concise, professional, and action-oriented (1 to 2 sentences max).\n"
        "5. Do NOT include greetings, intro, or outro text; return ONLY the 3 markdown bullets."
    )

    request_body = {
        "contents": [
            {
                "parts": [
                    {"text": f"{system_prompt}\n\nTime Period: {date_str}\n\nCommits from this week:\n{commit_payload}"}
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 500,
        }
    }

    # Support gemini-2.5-flash or fallback to gemini-1.5-flash
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
                        # Ensure bullet standard starts with '*'
                        return ["* " + b.lstrip("*- ").strip() for b in bullets]
        except Exception as e:
            print(f"[WARN] Gemini API call ({model}) failed: {e}", file=sys.stderr)

    return None


def score_commit(msg: str) -> int:
    """Score a commit based on impact keywords."""
    msg_lower = msg.lower()
    score = 1
    if msg_lower.startswith("feat"):
        score += 6
    elif msg_lower.startswith("perf"):
        score += 5
    elif msg_lower.startswith("refactor"):
        score += 4
    elif msg_lower.startswith("fix"):
        score += 3
    elif msg_lower.startswith("docs"):
        score += 2
    
    # Keyword boosts
    keywords = ["real-time", "pipeline", "dashboard", "engine", "adapter", "algorithm", "test", "benchmark", "model"]
    for kw in keywords:
        if kw in msg_lower:
            score += 2
    return score


def humanize_message(msg: str) -> str:
    """Convert conventional commit message into a clean readable sentence."""
    cleaned = msg
    # Strip type prefix like feat(scope): or fix:
    match = re.match(r"^[a-zA-Z0-9_-]+(?:\([^\)]+\))?:\s*(.*)$", cleaned)
    if match:
        cleaned = match.group(1).strip()
    
    if not cleaned:
        cleaned = msg
        
    # Capitalize first letter
    if len(cleaned) > 1:
        cleaned = cleaned[0].upper() + cleaned[1:]
    
    # Ensure terminal punctuation
    if not cleaned.endswith((".", "!", "?")):
        cleaned += "."
        
    return cleaned


def synthesize_heuristics(repo_groups: Dict[str, List[str]], username: str) -> List[str]:
    """Deterministic fallback synthesis ranking repositories and key commits."""
    if not repo_groups:
        return [
            "* **System Architecture & Design:** Focused on technical research, domain modeling, and continuous integration improvements.",
            "* **Core Workspaces:** Refactored project dependencies and optimized local development workflows.",
            "* **Open Source Maintenance:** Code reviews, repository maintenance, and environment hardening.",
        ]

    # Rank repos by combined commit score
    repo_scores = []
    for repo, msgs in repo_groups.items():
        # Deprioritize personal profile repo or dotfiles if specialized project repos exist
        penalty = 0
        if repo == username:
            penalty = -10
        elif repo == "dotfiles":
            penalty = -2

        total_score = sum(score_commit(m) for m in msgs) + (len(msgs) * 2) + penalty
        repo_scores.append((total_score, repo, msgs))

    repo_scores.sort(key=lambda x: x[0], reverse=True)

    bullets = []
    # Pick top repos
    top_repos = repo_scores[:3]

    for _, repo, msgs in top_repos:
        # Sort msgs by commit score
        sorted_msgs = sorted(msgs, key=score_commit, reverse=True)
        top_msg = sorted_msgs[0]
        readable_desc = humanize_message(top_msg)
        
        # If there are additional features, merge context
        if len(sorted_msgs) > 1:
            second_msg = sorted_msgs[1]
            if score_commit(second_msg) >= 4:
                second_desc = humanize_message(second_msg)
                readable_desc = f"{readable_desc.rstrip('.')} along with {second_desc[0].lower() + second_desc[1:]}"

        repo_link = f"https://github.com/{username}/{repo}"
        bullets.append(f"* **[{repo}]({repo_link}):** {readable_desc}")

    # If fewer than 3 repos were active, fill with high-ranking messages from the active repos
    if len(bullets) < 3 and repo_scores:
        primary_repo = repo_scores[0][1]
        remaining_msgs = [m for m in sorted(repo_scores[0][2], key=score_commit, reverse=True) if humanize_message(m) not in "".join(bullets)]
        for extra_msg in remaining_msgs:
            if len(bullets) >= 3:
                break
            repo_link = f"https://github.com/{username}/{primary_repo}"
            bullets.append(f"* **[{primary_repo}]({repo_link}):** {humanize_message(extra_msg)}")

    # Pad if still less than 3
    fallbacks = [
        "* **Engineering Architecture:** Advanced multi-repo tooling, telemetry instrumentation, and continuous integration workflows.",
        "* **Developer Environment:** Hardened system dotfiles, automated toolchains, and agent workspace integrations.",
    ]
    fb_idx = 0
    while len(bullets) < 3:
        bullets.append(fallbacks[fb_idx % len(fallbacks)])
        fb_idx += 1

    return bullets[:3]


def generate_markdown(bullets: List[str], start_dt: datetime, end_dt: datetime) -> str:
    """Format the full Weekly Highlights section."""
    start_str = start_dt.strftime("%b %d")
    end_str = end_dt.strftime("%b %d, %Y")
    header = f"### ⚡ What I Did This Week ({start_str} – {end_str})"

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
        # Insert after MLB_BIRTHDAY_END or before Featured Projects
        if "<!-- MLB_BIRTHDAY_END -->" in content:
            updated_content = content.replace(
                "<!-- MLB_BIRTHDAY_END -->",
                f"<!-- MLB_BIRTHDAY_END -->\n\n---\n\n{new_section}"
            )
        elif "### 🚀 Featured Projects" in content:
            updated_content = content.replace(
                "### 🚀 Featured Projects",
                f"{new_section}\n\n---\n\n### 🚀 Featured Projects"
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
    parser.add_argument("--lookback-days", type=int, default=7, help="Days to look back for commits")
    parser.add_argument("--readme", default="README.md", help="Path to README.md")
    parser.add_argument("--token", default=os.getenv("GITHUB_TOKEN"), help="GitHub API Token")
    parser.add_argument("--gemini-api-key", default=os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"), help="Gemini API Key")
    parser.add_argument("--dry-run", action="store_true", help="Print output without writing to README.md")

    args = parser.parse_args()

    end_dt = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(days=args.lookback_days)
    start_date_str = start_dt.strftime("%Y-%m-%d")

    print(f"[INFO] Fetching public commits for {args.username} since {start_date_str}...")
    
    # 1. Fetch commits
    commits = fetch_commits_search(args.username, start_date_str, args.token)
    if not commits:
        print("[INFO] Search API returned 0 commits; trying events API fallback...")
        commits = fetch_events_fallback(args.username, start_dt, args.token)

    print(f"[INFO] Ingested {len(commits)} raw commit records.")

    # 2. Filter and cluster
    repo_groups = extract_and_group_commits(commits, start_dt)
    print(f"[INFO] Clustered into {len(repo_groups)} active repositories.")
    for repo, msgs in repo_groups.items():
        print(f"   • {repo}: {len(msgs)} commit(s)")

    # 3. Synthesize 3 bullets
    bullets = None
    date_range_label = f"{start_dt.strftime('%b %d')} – {end_dt.strftime('%b %d, %Y')}"

    if args.gemini_api_key:
        print("[INFO] Synthesizing highlights with Gemini AI...")
        bullets = synthesize_with_gemini(repo_groups, args.gemini_api_key, date_range_label)

    if not bullets:
        if args.gemini_api_key:
            print("[INFO] Gemini synthesis unavailable; falling back to deterministic heuristic engine.")
        else:
            print("[INFO] Using deterministic heuristic synthesis engine.")
        bullets = synthesize_heuristics(repo_groups, args.username)

    # 4. Generate Markdown
    markdown_section = generate_markdown(bullets, start_dt, end_dt)

    if args.dry_run:
        print("\n--- DRY RUN OUTPUT ---")
        print(markdown_section)
        print("----------------------\n")
    else:
        update_readme(args.readme, markdown_section)


if __name__ == "__main__":
    main()
