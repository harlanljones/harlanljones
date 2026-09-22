import datetime as dt
import pytest
from scripts.weekly_summary import synthesize_smart_heuristics
from scripts.render_project_index import get_section_accent, format_section_stat, build_sections
from scripts.render_header_svg import render as render_header, CHIPS


def test_synthesize_smart_heuristics_verb_rotation():
    """Verify that fallback bullets do not repeat identical verb pairs."""
    repos = {
        "repo-alpha": ["add data pipeline ingestion", "implement kafka streaming consumer"],
        "repo-beta": ["optimize query planner", "add unit tests and fixtures"],
        "repo-gamma": ["refactor database connection pool", "implement health check endpoints"],
    }
    bullets = synthesize_smart_heuristics(repos, "testuser")
    assert len(bullets) == 3

    # Ensure each bullet starts with distinct verbs
    verbs = []
    for b in bullets:
        # Extract text after '* **[repo](url):** '
        text = b.split(":** ")[1]
        first_word = text.split(" ")[0]
        verbs.append(first_word)

    assert len(set(verbs)) == 3, f"Expected 3 distinct verbs, got: {verbs}"


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
    assert "<summary><h3>🚀 Featured Repositories & Live Demos</h3></summary>" in table_md

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
