import datetime as dt
import io
import json
import sys
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


def _judged_project(name, changed_lines, magnitude_level, notable_value):
    return {
        "name": name,
        "changed_lines": changed_lines,
        "judgments": {
            "model": "jev-latest",
            "change_kind": {"choice": "feature", "confidence": 0.9},
            "notable": {"noul": notable_value},
            "magnitude": {
                "score": float(magnitude_level), "level": magnitude_level,
                "label": "large", "confidence": 0.9,
            },
            "regression_risk": {"noul": 0.1},
            "severity": {"score": 0.0, "level": 0, "label": "minor", "confidence": 0.5},
        },
        "commits": [{
            "subject": "feat: x",
            "changed_lines": changed_lines,
            "files": [{
                "path": "src/core.py", "additions": 2, "deletions": 0,
                "added": ["def build_alert(payload):"], "removed": [],
            }],
        }],
    }


def test_jev_judgments_rank_and_phrase_bullets_deterministically():
    projects = [
        _judged_project("small-internal", 500, 0, 0.1),
        _judged_project("big-feature", 10, 2, 0.9),
    ]

    bullets = weekly_summary.synthesize_with_jev(projects, "harlanljones")

    assert len(bullets) == 2
    assert bullets[0].startswith("* **[big-feature](https://github.com/harlanljones/big-feature):**")
    assert "build_alert" in bullets[0]


def test_jev_synthesis_returns_none_without_judgments():
    assert weekly_summary.synthesize_with_jev([{"name": "x", "commits": []}], "u") is None


def test_jev_synthesis_badges_risky_projects():
    risky = _judged_project("risky", 10, 2, 0.9)
    risky["judgments"]["regression_risk"] = {"noul": 0.85}
    risky["judgments"]["severity"] = {
        "score": 2.0, "level": 2, "label": "severe", "confidence": 0.9,
    }

    bullets = weekly_summary.synthesize_with_jev([risky], "harlanljones")

    assert bullets[0].endswith("[risk: severe]")
    svg = weekly_summary.render_weekly_svg(bullets, "Oct 02, 2026")
    assert "risk: severe" in svg
    assert "#f85149" in svg
    assert "[risk: severe]" not in svg
    assert "[risk: severe]" in weekly_summary.generate_markdown(bullets, "Oct 02, 2026")


def test_main_prefers_jev_judgments_over_gemini(monkeypatch, tmp_path, capsys):
    now = dt.datetime.now(dt.timezone.utc)
    store = {
        "window_end": now.isoformat(),
        "projects": [{
            **_judged_project("big-feature", 2, 2, 0.9),
            "commits": [{
                "sha": "abc123",
                "authored_at": now.isoformat(),
                "subject": "feat: alert",
                "changed_lines": 2,
                "files": [{
                    "path": "src/core.py", "additions": 2, "deletions": 0,
                    "added": ["def build_alert(payload):"], "removed": [],
                }],
            }],
        }],
    }
    store_path = tmp_path / "store.json"
    store_path.write_text(json.dumps(store), encoding="utf-8")
    gemini_calls = []
    monkeypatch.setattr(weekly_summary, "synthesize_with_gemini",
                        lambda *args, **kwargs: gemini_calls.append("gemini"))
    monkeypatch.setattr(sys, "argv", [
        "weekly_summary.py", "--diff-store", str(store_path),
        "--dry-run", "--gemini-api-key", "test-key",
    ])

    weekly_summary.main()

    out = capsys.readouterr().out
    assert "typed Jev judgments" in out
    assert gemini_calls == []


def test_main_accepts_injected_settings_and_skips_environ(monkeypatch, tmp_path):
    from scripts.collector_config import CollectorSettings, Secret

    settings = CollectorSettings(
        gh_read_token=Secret("read-token"),
        dry_run=True,
        state_dir=tmp_path / "state",
        work_dir=tmp_path / "work",
        author_pattern="Harlan",
    )

    def fail_from_environ(cls, *args, **kwargs):
        raise AssertionError("main() must not read the process environment when settings are injected")

    monkeypatch.setattr(collect_mirrors.CollectorSettings, "from_environ", classmethod(fail_from_environ))
    monkeypatch.setattr(collect_mirrors, "owned_repos", lambda token: [])
    monkeypatch.setattr(collect_mirrors, "sync_mirrors", lambda *args, **kwargs: [])
    monkeypatch.setattr(collect_mirrors, "mine", lambda *args, **kwargs: (
        {},
        {"season": [], "lanes": {}, "lane_dates": [], "hours": {}, "weekdays": {}, "commits": 0},
        {},
    ))
    monkeypatch.setattr(collect_mirrors, "weekly_diff_store", lambda *args, **kwargs: {})
    monkeypatch.setattr(collect_mirrors, "deployment_stats", lambda *args, **kwargs: {
        "wdc": 0.0, "aera": 0.0, "wdc_sub": "", "aera_sub": "",
    })
    monkeypatch.setattr(collect_mirrors, "skill_board", lambda *args, **kwargs: ({}, ""))
    monkeypatch.setattr(collect_mirrors, "render", lambda *args, **kwargs: "<svg/>")
    monkeypatch.setattr(collect_mirrors, "render_rhythm", lambda *args, **kwargs: "<svg/>")
    monkeypatch.setattr(collect_mirrors.render_glossary_svg, "render", lambda: "<svg/>")
    monkeypatch.setattr(collect_mirrors.render_pipeline_svg, "render", lambda: "<svg/>")
    written = []
    monkeypatch.setattr(collect_mirrors, "write_theme_pair",
                        lambda path, svg: written.append(path) or [path])

    collect_mirrors.main(settings)

    out = tmp_path / "work" / "out"
    assert (out / "skill_weeks.json").exists()
    assert (out / "weekly_diff_store.json").exists()
    assert {Path(p).name for p in written} == {
        "skills.svg", "commit-rhythm.svg", "glossary.svg", "pipeline.svg",
    }


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
