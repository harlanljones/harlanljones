import datetime as dt
import io
import json
from pathlib import Path

from scripts import collect_mirrors
from scripts import weekly_summary


def test_weekly_diff_store_uses_code_changes_and_excludes_private_repos(monkeypatch, tmp_path):
    start = dt.datetime(2026, 10, 2, 17, 0, tzinfo=dt.timezone(dt.timedelta(hours=-7)))
    end = start + dt.timedelta(hours=12)
    commits = {
        "public-project": [
            ("new", start + dt.timedelta(hours=1), "Harlan", "chore: update feature", [
                {
                    "filename": "src/alerts.py",
                    "additions": 2,
                    "deletions": 0,
                    "patch": "@@ -0,0 +1,2 @@\n+def build_alert(payload):\n+    return Alert(payload)",
                }
            ]),
            ("old", start - dt.timedelta(minutes=1), "Harlan", "feat: stale change", [
                {
                    "filename": "src/old.py",
                    "additions": 1,
                    "deletions": 0,
                    "patch": "@@ -0,0 +1 @@\n+stale_code()",
                }
            ]),
        ],
        "private-project": [
            ("private", start + dt.timedelta(hours=2), "Harlan", "feat: private work", [
                {
                    "filename": "src/private.py",
                    "additions": 1,
                    "deletions": 0,
                    "patch": "@@ -0,0 +1 @@\n+confidential_change()",
                }
            ]),
        ],
    }

    def fake_iter_commits(git_dir, since, author_pattern, env):
        return iter(commits[Path(git_dir).name.removesuffix(".git")])

    monkeypatch.setattr(collect_mirrors, "iter_commits", fake_iter_commits)
    store = collect_mirrors.weekly_diff_store(
        [str(tmp_path / "public-project.git"), str(tmp_path / "private-project.git")],
        {"public-project"},
        start,
        end,
        "author",
        {},
    )

    assert [project["name"] for project in store["projects"]] == ["public-project"]
    assert "build_alert" in str(store["projects"][0]["commits"])
    assert "stale_code" not in str(store)
    assert "confidential_change" not in str(store)


def test_gemini_prompt_contains_diff_evidence_not_just_commit_subjects(monkeypatch):
    prompt_text = []

    def fake_urlopen(request, timeout):
        payload = json.loads(request.data.decode("utf-8"))
        prompt_text.append(payload["contents"][0]["parts"][0]["text"])
        result = {
            "candidates": [{
                "content": {"parts": [{"text": "* **[public-project](https://github.com/harlanljones/public-project):** Added the new alert builder."}]}
            }]
        }
        return io.BytesIO(json.dumps(result).encode("utf-8"))

    monkeypatch.setattr(weekly_summary.urllib.request, "urlopen", fake_urlopen)
    projects = [{
        "name": "public-project",
        "changed_lines": 2,
        "commits": [{
            "subject": "chore: vague title",
            "files": [{"path": "src/alerts.py", "added": ["def build_alert():"], "removed": []}],
        }],
    }]

    bullets = weekly_summary.synthesize_with_gemini(projects, "test-key", "Oct 02, 2026")

    assert bullets and "public-project" in bullets[0]
    assert "def build_alert()" in prompt_text[0]
    assert "do not merely paraphrase" in prompt_text[0]


def test_week_in_review_readme_alt_text(tmp_path):
    readme = tmp_path / "README.md"
    url = "https://example.test/week.svg"
    readme.write_text(
        f'<!-- WEEKLY_HIGHLIGHTS_START --><picture><source srcset="{url}" />'
        f'<img src="https://example.test/week-light.svg" alt="What I Did This Week" /></picture>'
        "<!-- WEEKLY_HIGHLIGHTS_END -->",
        encoding="utf-8",
    )

    assert weekly_summary.ensure_readme_image(str(readme), url)
    content = readme.read_text(encoding="utf-8")
    assert 'alt="Week in Review"' in content
    assert "<picture><source" in content
    assert not weekly_summary.ensure_readme_image(str(readme), url)
    assert "No qualifying public code changes" in weekly_summary.render_weekly_svg([], "Oct 02, 2026")
