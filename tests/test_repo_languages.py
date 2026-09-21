import pytest
from scripts.repo_languages import analyze_repo_languages, lang_color, enrich_repo_languages


def test_primary_markup_elevation():
    """bayes-horizon has huge HTML but is really a Python ML project."""
    raw_bytes = {
        "HTML": 473057,
        "Python": 179121,
        "CSS": 53670,
        "JavaScript": 4932,
    }
    info = analyze_repo_languages(
        name="bayes-horizon",
        raw_bytes=raw_bytes,
        gh_primary="HTML",
        topics=["ml", "bayesian-inference"],
    )
    assert info["primary"] == "Python"
    assert info["secondary"] is None
    assert info["display"] == "Python"
    assert "Python" in info["eligible"]


def test_fullstack_repo_detection():
    """urban-signal has Python backend and TypeScript / Web frontend."""
    raw_bytes = {
        "Python": 6677585,
        "HTML": 252373,
        "TypeScript": 150419,
        "JavaScript": 126071,
        "CSS": 38108,
    }
    info = analyze_repo_languages(
        name="urban-signal",
        raw_bytes=raw_bytes,
        gh_primary="Python",
        topics=["kafka", "react", "fastapi"],
    )
    assert info["primary"] == "Python"
    assert info["secondary"] == "TypeScript"
    assert info["is_fullstack"] is True
    assert info["display"] == "Python · TS"
    assert "Python" in info["eligible"]
    assert "TypeScript" in info["eligible"]


def test_rust_and_typescript_repo():
    """arbkit is Rust engine + TypeScript frontend."""
    raw_bytes = {
        "Rust": 1018076,
        "TypeScript": 301757,
        "CSS": 33402,
        "JavaScript": 14380,
    }
    info = analyze_repo_languages(
        name="arbkit",
        raw_bytes=raw_bytes,
        gh_primary="Rust",
    )
    assert info["primary"] == "Rust"
    assert info["secondary"] == "TypeScript"
    assert info["is_fullstack"] is True
    assert info["display"] == "Rust · TS"
    assert "Rust" in info["eligible"]
    assert "TypeScript" in info["eligible"]


def test_long_primary_abbreviation():
    """statcast-lakehouse is TypeScript primary + Python secondary -> TS · Py."""
    raw_bytes = {
        "TypeScript": 256014,
        "Python": 202439,
    }
    info = analyze_repo_languages(
        name="statcast-lakehouse",
        raw_bytes=raw_bytes,
        gh_primary="TypeScript",
    )
    assert info["primary"] == "TypeScript"
    assert info["secondary"] == "Python"
    assert info["display"] == "TS · Py"


def test_lang_color_legibility():
    assert lang_color("Python").startswith("#")
    assert lang_color("Rust").startswith("#")
    assert lang_color("TypeScript").startswith("#")
    assert lang_color("UnknownLang").startswith("#")
