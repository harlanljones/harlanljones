import datetime as dt
import pytest
from scripts.weekly_summary import (
    filter_weekly_projects,
    generate_diff_heuristics,
    get_weekly_dates,
    generate_markdown,
    render_weekly_svg,
)
from scripts.render_project_index import get_section_accent, format_section_stat, build_sections
from scripts.render_header_svg import render as render_header, CHIPS


def test_weekly_summary_fallback_uses_diff_evidence():
    """Summaries use changed lines from the three projects, not their titles."""
    projects = [
        {"name": "repo-alpha", "changed_lines": 4, "commits": [{"subject": "title alpha", "changed_lines": 4, "files": [{"path": "src/alpha.py", "additions": 3, "deletions": 1, "added": ["def build_alpha():"], "removed": []}]}]},
        {"name": "repo-beta", "changed_lines": 3, "commits": [{"subject": "title beta", "changed_lines": 3, "files": [{"path": "src/beta.ts", "additions": 3, "deletions": 0, "added": ["export function buildBeta() {}"], "removed": []}]}]},
        {"name": "repo-gamma", "changed_lines": 2, "commits": [{"subject": "title gamma", "changed_lines": 2, "files": [{"path": "src/gamma.rs", "additions": 2, "deletions": 0, "added": ["pub fn build_gamma() {}"], "removed": []}]}]},
    ]
    bullets = generate_diff_heuristics(projects, "testuser")
    assert len(bullets) == 3
    assert "build_alpha" in bullets[0] and "title alpha" not in bullets[0]
    assert "buildBeta" in bullets[1] and "title beta" not in bullets[1]
    assert "build_gamma" in bullets[2] and "title gamma" not in bullets[2]
    assert "build_alpha" in render_weekly_svg(bullets, "Oct 02, 2026")


def test_weekly_fallback_phrases_docstrings_and_skips_machine_data():
    """Docstring evidence becomes a sentence; JSON fragments never leak."""
    projects = [{
        "name": "signal",
        "changed_lines": 30,
        "commits": [{
            "subject": "data: refresh snapshot",
            "changed_lines": 30,
            "files": [
                {"path": "data/snapshot.json", "additions": 20, "deletions": 10,
                 "added": ["{", '"asOf": "2026-10-05",'], "removed": []},
                {"path": "src/runner.py", "additions": 5, "deletions": 0,
                 "added": ['"""Crash-safe commit, replay, normalization and permit-only feature aggregation."""'],
                 "removed": []},
            ],
        }],
    }]
    bullets = generate_diff_heuristics(projects, "testuser")
    assert len(bullets) == 1
    assert "crash-safe commit, replay, normalization and permit-only feature aggregation" in bullets[0]
    assert "src/runner.py" in bullets[0]
    assert '"asOf"' not in bullets[0]
    assert "Added {" not in bullets[0]


def test_weekly_fallback_phrases_verb_docstrings_as_tooling_sentences():
    """Third-person docstrings compose as 'Updated `file` to ...'."""
    projects = [{
        "name": "collector",
        "changed_lines": 10,
        "commits": [{
            "subject": "chore: rework summary script",
            "changed_lines": 10,
            "files": [{
                "path": "scripts/weekly_summary.py",
                "additions": 8,
                "deletions": 0,
                "added": [
                    '"""Weekly Project Summary Automation.',
                    "Summarizes actual public-repository code diffs mined by the nightly collector,",
                ],
                "removed": [],
            }],
        }],
    }]
    bullets = generate_diff_heuristics(projects, "testuser")
    assert bullets == [
        "* **[collector](https://github.com/testuser/collector):** "
        "Added `scripts/weekly_summary.py` to summarize actual public-repository code diffs "
        "mined by the nightly collector."
    ]


def test_weekly_fallback_uses_subject_when_diff_is_data_only():
    """Data-only evidence (JSON keys, hashes) falls back to the commit subject."""
    projects = [{
        "name": "roster",
        "changed_lines": 500,
        "commits": [{
            "subject": "data: refresh public roster snapshot",
            "changed_lines": 500,
            "files": [{
                "path": "spikes/mlb-2026/timeline-snapshot.json",
                "additions": 490,
                "deletions": 10,
                "added": ['"asOf": "2026-10-05",', '"fetchedAt": "2026-10-05T16:08:14Z",'],
                "removed": [],
            }],
        }],
    }]
    bullets = generate_diff_heuristics(projects, "testuser")
    assert bullets == [
        "* **[roster](https://github.com/testuser/roster):** "
        "Refreshed public roster snapshot in `spikes/mlb-2026/timeline-snapshot.json`."
    ]


def test_section_accent_and_dynamic_callups():
    """Verify dynamic call-up detection and accent assignment."""
    assert get_section_accent("September call-ups") == "#3fb950"
    assert get_section_accent("October call-ups") == "#3fb950"
    assert get_section_accent("Rookie call-ups & debuts") == "#3fb950"
    assert get_section_accent("Live in production") == "#58a6ff"
    assert get_section_accent("Top 5 · by gWAR") == "#e3b341"

    now_sep = dt.datetime(2026, 9, 22, tzinfo=dt.timezone.utc)
    stat = format_section_stat(
        {"created_at": "2026-09-20T00:00:00Z", "commits_90": 25, "gwar": 1.5},
        "September call-ups",
        now=now_sep,
    )
    assert "debut Sep 20" in stat

    now_oct = dt.datetime(2026, 10, 15, tzinfo=dt.timezone.utc)
    repos = [
        {"full_name": f"u/p{i}", "name": f"p{i}", "gwar": 5.0 - i * 0.5, "created_at": "2026-01-01T00:00:00Z"}
        for i in range(5)
    ]
    repos.append({"full_name": "u/rookie", "name": "rookie", "gwar": 2.0, "created_at": "2026-10-01T00:00:00Z"})
    sections = build_sections(repos, now_oct, {})
    section_names = [s[0] for s in sections]
    assert any("Rookie" in name or "call-up" in name.lower() for name in section_names)


def test_render_header_contains_identity_chips():
    """Verify header SVG renders all identity chips and correct dimensions."""
    svg = render_header()
    assert 'width="900"' in svg
    assert 'height="300"' in svg
    from scripts.svg_cards import esc
    for label, _ in CHIPS:
        assert esc(label) in svg


def test_generate_featured_repos_table_collapsed_by_default():
    """Verify markdown directory is collapsed by default and contains live links."""
    from scripts.render_project_index import generate_featured_repos_table

    entries = [
        {
            "name": "urban-signal",
            "priority": 1,
            "featured": True,
            "focus": "Real-time spatio-temporal property forecasting & telemetry",
            "badges": ["Python", "Apache Kafka", "FastAPI"],
            "homepage": "https://urban-signal.harlanljones.com",
        },
        {
            "name": "statcast-lakehouse",
            "priority": 2,
            "featured": True,
            "focus": "Statcast pitch telemetry ingestion",
            "badges": ["Python", "TypeScript"],
            "homepage": "",
        },
    ]

    table_md = generate_featured_repos_table(entries, username="testuser")

    # Collapsed by default check
    assert "<details>" in table_md
    assert "<details open>" not in table_md
    assert "</details>" in table_md
    assert "<summary><b>🚀 Featured Repositories & Live Demos</b></summary>" in table_md

    # Header check
    assert "| Project | Focus | Tech Stack | Live Deployment |" in table_md
    assert "| :--- | :--- | :--- | :--- |" in table_md

    # Row content checks
    assert "[**urban-signal**](https://github.com/testuser/urban-signal)" in table_md
    assert "Real-time spatio-temporal property forecasting & telemetry" in table_md
    assert "`Python` `Kafka` `FastAPI`" in table_md
    assert "[urban-signal.harlanljones.com ↗](https://urban-signal.harlanljones.com)" in table_md

    assert "[**statcast-lakehouse**](https://github.com/testuser/statcast-lakehouse)" in table_md
    assert "[GitHub Repository ↗](https://github.com/testuser/statcast-lakehouse)" in table_md


def test_update_readme_featured_repos_idempotent(tmp_path):
    """Verify update_readme_featured_repos inserts and updates cleanly without duplication."""
    from scripts.render_project_index import update_readme_featured_repos, FEATURED_REPOS_START, FEATURED_REPOS_END

    test_readme = tmp_path / "README.md"
    initial_content = (
        "# Profile\n\n"
        "<!-- PROJECTS_END -->\n\n"
        "<picture>\n<img src=\"skills.svg\" />\n</picture>\n"
    )
    test_readme.write_text(initial_content, encoding="utf-8")

    entries = [
        {
            "name": "urban-signal",
            "priority": 1,
            "featured": True,
            "focus": "Real-time forecasting",
            "badges": ["Python"],
            "homepage": "https://urban-signal.harlanljones.com",
        }
    ]

    # First run should insert section
    assert update_readme_featured_repos(str(test_readme), entries, "testuser") is True

    content_after = test_readme.read_text(encoding="utf-8")
    assert FEATURED_REPOS_START in content_after
    assert FEATURED_REPOS_END in content_after
    assert "<details>" in content_after
    assert "[**urban-signal**]" in content_after

    # Second run with same entries should be idempotent (return False)
    assert update_readme_featured_repos(str(test_readme), entries, "testuser") is False

    # Run with updated focus should update in-place
    entries[0]["focus"] = "Next-gen forecasting"
    assert update_readme_featured_repos(str(test_readme), entries, "testuser") is True
    updated_content = test_readme.read_text(encoding="utf-8")
    assert "Next-gen forecasting" in updated_content
    assert content_after.count(FEATURED_REPOS_START) == 1
    assert updated_content.count(FEATURED_REPOS_START) == 1


def test_get_weekly_dates_friday_rollover_to_present():
    """Verify weekly date window rolls over on Friday at 5pm PT and covers rollover-present."""
    from zoneinfo import ZoneInfo
    pac_tz = ZoneInfo("America/Los_Angeles")

    # Tuesday Sep 29, 2026: should be Sep 25 – Sep 29, 2026
    tue = dt.datetime(2026, 9, 29, 13, 30, tzinfo=pac_tz)
    s, e, q, label = get_weekly_dates(tue)
    assert label == "Sep 25 – Sep 29, 2026"
    assert q == "2026-09-25"
    assert s == dt.datetime(2026, 9, 25, 17, 0, tzinfo=pac_tz)
    assert e == tue

    # Saturday Sep 26, 2026: should be Sep 25 – Sep 26, 2026
    sat = dt.datetime(2026, 9, 26, 10, 0, tzinfo=pac_tz)
    s, e, q, label = get_weekly_dates(sat)
    assert label == "Sep 25 – Sep 26, 2026"

    # Sunday Sep 27, 2026: should be Sep 25 – Sep 27, 2026
    sun = dt.datetime(2026, 9, 27, 12, 0, tzinfo=pac_tz)
    s, e, q, label = get_weekly_dates(sun)
    assert label == "Sep 25 – Sep 27, 2026"

    # Friday Oct 2, 2026 at 16:30 PT (before 17:00 rollover): conclude the week.
    fri_before = dt.datetime(2026, 10, 2, 16, 30, tzinfo=pac_tz)
    s, e, q, label = get_weekly_dates(fri_before)
    assert label == "Sep 25 – Oct 02, 2026"

    # The rollover is inclusive at exactly 17:00, not 18:00.
    fri_at_rollover = dt.datetime(2026, 10, 2, 17, 0, tzinfo=pac_tz)
    s, e, q, label = get_weekly_dates(fri_at_rollover)
    assert label == "Oct 02, 2026"
    assert s == dt.datetime(2026, 10, 2, 17, 0, tzinfo=pac_tz)

    fri_after = dt.datetime(2026, 10, 2, 17, 1, tzinfo=pac_tz)
    s, e, q, label = get_weekly_dates(fri_after)
    assert label == "Oct 02, 2026"

    # The same local rollover holds during standard time (UTC-8).
    winter_rollover = dt.datetime(2026, 12, 4, 17, 0, tzinfo=pac_tz)
    s, e, q, label = get_weekly_dates(winter_rollover)
    assert s == winter_rollover
    assert s.utcoffset() == dt.timedelta(hours=-8)
    assert label == "Dec 04, 2026"

    # Explicit lookback override
    s, e, q, label = get_weekly_dates(tue, explicit_lookback=3)
    assert label == "Sep 26 – Sep 29, 2026"


def test_weekly_summary_uses_deliverables_from_active_projects_only():
    store = {
        "projects": [{
            "name": "baseball-dashboard",
            "changed_lines": 2,
            "commits": [{
                "authored_at": "2026-10-03T00:00:00+00:00",
                "changed_lines": 2,
                "subject": "title without evidence",
                "files": [{"path": "src/alerts.py", "additions": 2, "deletions": 0,
                           "added": ["def build_player_injury_alert():"], "removed": []}],
            }],
        }],
    }
    start = dt.datetime(2026, 10, 2, 17, 0, tzinfo=dt.timezone(dt.timedelta(hours=-7)))
    end = dt.datetime(2026, 10, 3, 0, 0, tzinfo=dt.timezone(dt.timedelta(hours=-7)))
    projects = filter_weekly_projects(store, start, end)
    bullets = generate_diff_heuristics(projects, "testuser")

    assert len(bullets) == 1
    assert "build_player_injury_alert" in bullets[0]
    assert "title without evidence" not in bullets[0]
    markdown = generate_markdown(bullets, "Oct 02, 2026")
    assert markdown.count("* **[") == 1
    assert "Week in Review" in markdown
    assert "Week in Review" in render_weekly_svg(bullets, "Oct 02, 2026")


def test_filter_weekly_projects_keeps_only_commits_in_window():
    store = {"projects": [{"name": "alpha", "commits": [
        {"authored_at": "2026-10-02T23:59:00+00:00", "changed_lines": 2, "files": [{"path": "a.py"}]},
        {"authored_at": "2026-10-03T00:00:00+00:00", "changed_lines": 3, "files": [{"path": "b.py"}]},
        {"authored_at": "2026-10-03T08:00:00+00:00", "changed_lines": 4, "files": [{"path": "c.py"}]},
    ]}]}
    start = dt.datetime(2026, 10, 2, 17, 0, tzinfo=dt.timezone(dt.timedelta(hours=-7)))
    end = dt.datetime(2026, 10, 3, 0, 30, tzinfo=dt.timezone(dt.timedelta(hours=-7)))

    projects = filter_weekly_projects(store, start, end)

    assert len(projects) == 1
    assert [commit["changed_lines"] for commit in projects[0]["commits"]] == [3]

