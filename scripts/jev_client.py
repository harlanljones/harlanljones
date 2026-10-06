#!/usr/bin/env python3
"""Typed judgments for public project diffs via the TypeSafe Jev API.

Jev is TypeSafe's System One model: POST /v1/systemone with a JSON `state` and
typed questions (`noul` = yes/no probability, `choice` = one option, `score` =
point on an ordered scale). This client asks five fixed questions about each
week's project diff (change kind, notability, magnitude, regression risk,
regression severity) and folds the answers into the public weekly diff store.

Privacy: the weekly diff store is built from public repositories only (see
`weekly_diff_store` filtering on `public_repo_names`), so only public evidence
is ever sent. Private repositories never reach this module.

Runtime dependencies: Python standard library only.
"""

import json
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, List, Optional, Tuple

from collector_config import Secret

API_URL = "https://api.typesafe.ai/v1/systemone"
DEFAULT_MODEL = "jev-latest"
DEFAULT_TIMEOUT = 30

CHANGE_KINDS = ("feature", "fix", "refactor", "docs", "tooling", "test", "other")
MAGNITUDE_LEVELS = ("small", "moderate", "large")
SEVERITY_LEVELS = ("minor", "moderate", "severe")
REGRESSION_WARN_THRESHOLD = 0.7

WEEKLY_QUESTIONS: Dict[str, Dict[str, Any]] = {
    "change_kind": {
        "type": "choice",
        "criteria": {
            "feature": "New capability or behavior",
            "fix": "Corrects a defect or regression",
            "refactor": "Restructures code without changing behavior",
            "docs": "Documentation or comments",
            "tooling": "Build, CI, dependencies, or developer tooling",
            "test": "Tests or test infrastructure",
            "other": "None of the above",
        },
        "instructions": "Classify the dominant kind of change in this diff.",
    },
    "notable": {
        "type": "noul",
        "criteria": {
            "true": "A user-visible or externally interesting change",
            "false": "Internal or routine change",
        },
        "instructions": "Does this diff contain a user-visible or externally interesting change?",
    },
    "magnitude": {
        "type": "score",
        "criteria": ["small", "moderate", "large"],
        "instructions": "How substantial is this change relative to a typical commit?",
    },
    "regression_risk": {
        "type": "noul",
        "criteria": {
            "true": "Plausibly introduces a regression or breaks existing behavior",
            "false": "Unlikely to change existing behavior for the worse",
        },
        "instructions": "Could this diff plausibly regress existing behavior?",
    },
    "severity": {
        "type": "score",
        "criteria": ["minor", "moderate", "severe"],
        "instructions": "If a regression shipped from this diff, how severe would its impact be?",
    },
}


class JevError(RuntimeError):
    """The Jev request or response could not be used."""


def evaluate(
    api_key: Secret,
    state: Any,
    questions: Dict[str, Dict[str, Any]],
    *,
    model: str = DEFAULT_MODEL,
    timeout: int = DEFAULT_TIMEOUT,
) -> Dict[str, Dict[str, Any]]:
    """POST one typed question set; returns the raw `answers` object."""
    body = {"model": model, "state": state, "questions": questions}
    request = urllib.request.Request(
        API_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key.reveal()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "ProfileCollector/1.0",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:200]
        raise JevError(f"Jev request failed with HTTP {exc.code}: {detail}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise JevError(f"Jev request failed: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise JevError(f"Jev returned invalid JSON: {exc}") from exc

    answers = payload.get("answers") if isinstance(payload, dict) else None
    if not isinstance(answers, dict):
        raise JevError("Jev response is missing an answers object")
    return answers


def project_state(project: Dict) -> Dict:
    """The bounded public evidence sent as `state` for one project."""
    return {
        "project": project.get("name", ""),
        "changed_lines": project.get("changed_lines", 0),
        "commits": [
            {
                "subject": commit.get("subject", ""),
                "changed_lines": commit.get("changed_lines", 0),
                "files": [
                    {
                        "path": f.get("path", ""),
                        "additions": f.get("additions", 0),
                        "deletions": f.get("deletions", 0),
                        "added": f.get("added", []),
                        "removed": f.get("removed", []),
                    }
                    for f in commit.get("files", [])
                ],
            }
            for commit in project.get("commits", [])
        ],
    }


def judge_project(
    api_key: Secret,
    project: Dict,
    *,
    model: str = DEFAULT_MODEL,
    timeout: int = DEFAULT_TIMEOUT,
) -> Dict:
    """One Jev call for one project; returns normalized judgments."""
    answers = evaluate(api_key, project_state(project), WEEKLY_QUESTIONS, model=model, timeout=timeout)
    return {
        "model": model,
        "change_kind": _choice(answers, "change_kind", CHANGE_KINDS),
        "notable": _noul(answers, "notable"),
        "magnitude": _score(answers, "magnitude", MAGNITUDE_LEVELS),
        "regression_risk": _noul(answers, "regression_risk"),
        "severity": _score(answers, "severity", SEVERITY_LEVELS),
    }


def regression_risk(project: Dict) -> Optional[Tuple[float, str]]:
    """(probability, severity label) from a project's judgments, if present.

    Tolerates stores annotated before the regression questions existed.
    """
    judgments = project.get("judgments") or {}
    risk = (judgments.get("regression_risk") or {}).get("noul")
    if not isinstance(risk, (int, float)):
        return None
    severity = (judgments.get("severity") or {}).get("label", "unknown")
    return float(risk), str(severity)


def regression_warnings(
    store: Dict,
    threshold: float = REGRESSION_WARN_THRESHOLD,
) -> List[Tuple[str, float, str]]:
    """(name, probability, severity) for projects at or above the threshold."""
    warnings = []
    for project in store.get("projects", []):
        risk = regression_risk(project)
        if risk and risk[0] >= threshold:
            warnings.append((project.get("name", "?"), risk[0], risk[1]))
    return warnings


def annotate_diff_store(
    store: Dict,
    api_key: Secret,
    *,
    model: str = DEFAULT_MODEL,
    timeout: int = DEFAULT_TIMEOUT,
    log: Callable[[str], None] = print,
) -> int:
    """Adds a `judgments` key to every project in the public diff store.

    Fail-open: a failed call logs a warning and leaves that project unjudged,
    so the nightly collector always publishes a store. Returns projects judged.
    """
    judged = 0
    for project in store.get("projects", []):
        try:
            project["judgments"] = judge_project(api_key, project, model=model, timeout=timeout)
            judged += 1
        except JevError as exc:
            log(f"[WARN] Jev judgment for {project.get('name', '?')}: {exc}")
    return judged


def _choice(answers: Dict, question_id: str, allowed: tuple) -> Dict:
    answer = answers.get(question_id) or {}
    choice = answer.get("choice")
    if answer.get("type") != "choice" or choice not in allowed:
        raise JevError(f"Jev answer {question_id!r} is not one of {', '.join(allowed)}")
    return {"choice": choice, "confidence": answer.get("confidence")}


def _noul(answers: Dict, question_id: str) -> Dict:
    answer = answers.get(question_id) or {}
    value = answer.get("noul")
    if answer.get("type") != "noul" or not isinstance(value, (int, float)):
        raise JevError(f"Jev answer {question_id!r} is not a probability")
    return {"noul": value}


def _score(answers: Dict, question_id: str, levels: tuple) -> Dict:
    answer = answers.get(question_id) or {}
    score = answer.get("score")
    if answer.get("type") != "score" or not isinstance(score, (int, float)):
        raise JevError(f"Jev answer {question_id!r} is not a score")
    # `score` is the probability-weighted average of level indices; the label a
    # caller branches on is the modal level, not round(score).
    probabilities = answer.get("probabilities") or {}
    if probabilities:
        index = max(range(len(levels)), key=lambda i: probabilities.get(str(i), 0))
    else:
        index = min(max(round(score), 0), len(levels) - 1)
    return {"score": score, "level": index, "label": levels[index], "confidence": answer.get("confidence")}
