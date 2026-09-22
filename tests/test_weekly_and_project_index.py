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
