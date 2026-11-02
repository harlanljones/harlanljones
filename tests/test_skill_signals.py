import pytest

from scripts.skill_signals import file_skill_lines


@pytest.mark.parametrize(
    ("statement", "skill"),
    [
        ("from numpy import array", "NumPy"),
        ("from pandas import DataFrame", "pandas"),
        ("from polars import col", "Polars"),
        ("import fastapi", "FastAPI"),
        ("import flask", "Flask"),
        ("import pydantic", "Pydantic"),
    ],
)
def test_library_imports_are_counted(statement, skill):
    assert file_skill_lines("app.py", f"+{statement}", 1, 0)[skill] == 1
