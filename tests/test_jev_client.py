import io
import json
import urllib.error

import pytest

from scripts import jev_client
from scripts.collector_config import Secret

ANSWERS = {
    "change_kind": {
        "type": "choice",
        "choice": "feature",
        "confidence": 0.9,
        "probabilities": {"feature": 0.9, "fix": 0.1},
    },
    "notable": {"type": "noul", "noul": 0.8},
    "magnitude": {
        "type": "score",
        "score": 1.4,
        "confidence": 0.7,
        "probabilities": {"0": 0.1, "1": 0.4, "2": 0.5},
        "legend": ["small", "moderate", "large"],
    },
    "regression_risk": {"type": "noul", "noul": 0.3},
    "severity": {
        "type": "score",
        "score": 1.0,
        "confidence": 0.6,
        "probabilities": {"0": 0.2, "1": 0.6, "2": 0.2},
        "legend": ["minor", "moderate", "severe"],
    },
}


def fake_urlopen(payload, captured=None):
    def opener(request, timeout=None):
        if captured is not None:
            captured.append({"request": request, "timeout": timeout})
        return io.BytesIO(json.dumps(payload).encode("utf-8"))

    return opener


def test_evaluate_posts_bearer_request_and_returns_answers(monkeypatch):
    captured = []
    monkeypatch.setattr(
        jev_client.urllib.request, "urlopen",
        fake_urlopen({"model": "jev-latest", "answers": ANSWERS}, captured),
    )

    answers = jev_client.evaluate(
        Secret("secret-key"), {"project": "x"}, {"magnitude": {"type": "noul"}}
    )

    assert answers == ANSWERS
    request = captured[0]["request"]
    assert request.full_url == "https://api.typesafe.ai/v1/systemone"
    assert request.method == "POST"
    assert request.get_header("Authorization") == "Bearer secret-key"
    body = json.loads(request.data.decode("utf-8"))
    assert body == {
        "model": "jev-latest",
        "state": {"project": "x"},
        "questions": {"magnitude": {"type": "noul"}},
    }


def test_evaluate_raises_jev_error_on_http_error(monkeypatch):
    def opener(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {}, io.BytesIO(b"bad key"))

    monkeypatch.setattr(jev_client.urllib.request, "urlopen", opener)

    with pytest.raises(jev_client.JevError, match="401"):
        jev_client.evaluate(Secret("k"), {}, {})


def test_evaluate_raises_jev_error_on_invalid_json(monkeypatch):
    monkeypatch.setattr(
        jev_client.urllib.request, "urlopen",
        lambda request, timeout=None: io.BytesIO(b"not json"),
    )

    with pytest.raises(jev_client.JevError, match="invalid JSON"):
        jev_client.evaluate(Secret("k"), {}, {})


def test_evaluate_raises_jev_error_when_answers_missing(monkeypatch):
    monkeypatch.setattr(
        jev_client.urllib.request, "urlopen", fake_urlopen({"model": "jev-latest"})
    )

    with pytest.raises(jev_client.JevError, match="answers"):
        jev_client.evaluate(Secret("k"), {}, {})


def test_judge_project_normalizes_answers(monkeypatch):
    monkeypatch.setattr(jev_client.urllib.request, "urlopen", fake_urlopen({"answers": ANSWERS}))

    judgment = jev_client.judge_project(
        Secret("k"), {"name": "demo", "changed_lines": 10, "commits": []}
    )

    assert judgment == {
        "model": "jev-latest",
        "change_kind": {"choice": "feature", "confidence": 0.9},
        "notable": {"noul": 0.8},
        "magnitude": {"score": 1.4, "level": 2, "label": "large", "confidence": 0.7},
        "regression_risk": {"noul": 0.3},
        "severity": {"score": 1.0, "level": 1, "label": "moderate", "confidence": 0.6},
    }


def test_judge_project_rejects_unknown_choice(monkeypatch):
    answers = dict(
        ANSWERS,
        change_kind={"type": "choice", "choice": "hacking", "confidence": 1.0, "probabilities": {}},
    )
    monkeypatch.setattr(jev_client.urllib.request, "urlopen", fake_urlopen({"answers": answers}))

    with pytest.raises(jev_client.JevError, match="change_kind"):
        jev_client.judge_project(Secret("k"), {"name": "demo"})


def test_annotate_diff_store_judges_every_project(monkeypatch):
    monkeypatch.setattr(jev_client.urllib.request, "urlopen", fake_urlopen({"answers": ANSWERS}))
    store = {"projects": [{"name": "a"}, {"name": "b"}]}

    assert jev_client.annotate_diff_store(store, Secret("k"), log=lambda message: None) == 2
    assert all("judgments" in project for project in store["projects"])


def test_annotate_diff_store_fails_open(monkeypatch):
    calls = {"n": 0}

    def opener(request, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise urllib.error.URLError("boom")
        return io.BytesIO(json.dumps({"answers": ANSWERS}).encode("utf-8"))

    monkeypatch.setattr(jev_client.urllib.request, "urlopen", opener)
    logs = []
    store = {"projects": [{"name": "a"}, {"name": "b"}]}

    judged = jev_client.annotate_diff_store(store, Secret("k"), log=logs.append)

    assert judged == 1
    assert "judgments" not in store["projects"][0]
    assert "judgments" in store["projects"][1]
    assert any("[WARN]" in message and "a" in message for message in logs)


def test_regression_warnings_flag_high_risk_projects():
    store = {"projects": [
        {"name": "risky", "judgments": {
            "regression_risk": {"noul": 0.82}, "severity": {"label": "severe"}}},
        {"name": "calm", "judgments": {
            "regression_risk": {"noul": 0.2}, "severity": {"label": "minor"}}},
        {"name": "unjudged"},
    ]}

    assert jev_client.regression_warnings(store) == [("risky", 0.82, "severe")]


def test_regression_risk_tolerates_older_judgments():
    assert jev_client.regression_risk({"judgments": {"model": "jev-latest"}}) is None


def test_annotate_diff_store_sends_only_bounded_public_evidence(monkeypatch):
    captured = []
    monkeypatch.setattr(
        jev_client.urllib.request, "urlopen", fake_urlopen({"answers": ANSWERS}, captured)
    )
    project = {
        "name": "demo",
        "changed_lines": 3,
        "commits": [{
            "subject": "feat: x",
            "changed_lines": 3,
            "files": [{
                "path": "a.py", "additions": 1, "deletions": 0,
                "added": ["x = 1"], "removed": [],
            }],
        }],
    }

    jev_client.annotate_diff_store({"projects": [project]}, Secret("k"), log=lambda message: None)

    body = json.loads(captured[0]["request"].data.decode("utf-8"))
    assert set(body["state"]) == {"project", "changed_lines", "commits"}
    assert body["questions"] == jev_client.WEEKLY_QUESTIONS
