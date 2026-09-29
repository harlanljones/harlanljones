import datetime as dt
import pytest
from scripts.mlb_birthdays import (
    render_birthday_index_svg,
    build_daily_ledger,
    ensure_birthday_index_image,
    BIRTHDAY_INDEX_SVG_URL,
)
from scripts.render_pipeline_svg import JOBS, render as render_pipeline
from scripts.render_glossary_svg import ENTRIES, render as render_glossary


def test_render_birthday_index_svg_title_and_subtitle():
    """Verify SVG card renders 'MLB Birthday Index' and clear calendar birth subtitle."""
    dummy_model = {
        "date_str": "September 29",
        "total": 64,
        "empty": False,
        "featured": [
            {
                "category": "WARrior",
                "name": "Ed Morris",
                "span": "1884–1890",
                "franchises": "CBK, PBB, PIT",
                "metrics": "38.4 bWAR • .401 OPS",
                "img": "",
                "initials": "EM",
            }
        ],
        "mlb": [],
        "minors": [],
    }
    svg = render_birthday_index_svg(dummy_model)
    assert "MLB Birthday Index" in svg
    assert "Daily Dugout Dispatch" not in svg
    # Ensure subtitle identifies calendar birth records and does not collide with Savant's in-game birthday_index
    assert "historical birth index &amp; active roster tracker" in svg or "historical birth index & active roster tracker" in svg


def test_build_daily_ledger_title():
    """Verify markdown ledger uses MLB Birthday Index heading."""
    ledger = build_daily_ledger([], 9, 29, 2026)
    assert "### MLB Birthday Index: September 29" in ledger
    assert "Daily Dugout Dispatch" not in ledger


def test_pipeline_and_glossary_use_mlb_birthday_index():
    """Verify pipeline and glossary reflect the renamed MLB Birthday Index."""
    pipeline_svg = render_pipeline()
    assert "MLB Birthday Index" in pipeline_svg
    assert "Daily Dugout Dispatch" not in pipeline_svg

    glossary_svg = render_glossary()
    assert any("MLB Birthday Index" in e[3] for e in ENTRIES)
    assert "Birthday Index" in glossary_svg
    assert "Dugout Dispatch" not in glossary_svg


def test_ensure_birthday_index_image(tmp_path):
    """Verify ensure_birthday_index_image injects picture tag properly."""
    test_readme = tmp_path / "README.md"
    test_readme.write_text(
        "<!-- MLB_BIRTHDAY_START -->\n<!-- MLB_BIRTHDAY_END -->\n",
        encoding="utf-8",
    )
    res = ensure_birthday_index_image(str(test_readme))
    assert res is True
    content = test_readme.read_text(encoding="utf-8")
    assert "MLB Birthday Index" in content
    assert "mlb-birthday-index.svg" in content
    assert "mlb-birthday-index-light.svg" in content
