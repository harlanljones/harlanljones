from pathlib import Path

import pytest

from scripts import check_collector_env
from scripts.collector_config import JOB_SECRET_ENV, OPTIONAL_SECRET_GROUPS


def entry(name, secret=None):
    if secret:
        return {"name": name, "valueFrom": {"secretKeyRef": {"key": "latest", "name": secret}}}
    return {"name": name, "value": "plain"}


def schema_pairs():
    pairs = dict(JOB_SECRET_ENV)
    for group in OPTIONAL_SECRET_GROUPS:
        pairs.update(group)
    return pairs


def clean_entries():
    return [entry(name, secret) for name, secret in schema_pairs().items()]


def test_clean_job_env_has_no_findings():
    assert check_collector_env.check_job_env(clean_entries()) == []


def test_missing_required_secret_is_an_error():
    entries = [e for e in clean_entries() if e["name"] != "GH_WRITE_TOKEN"]

    findings = check_collector_env.check_job_env(entries)

    assert any(f.level == "error" and "GH_WRITE_TOKEN" in f.message for f in findings)


def test_wrong_secret_mapping_is_an_error():
    entries = clean_entries()
    entries[0] = entry("GH_READ_TOKEN", "some-other-secret")

    findings = check_collector_env.check_job_env(entries)

    assert any(f.level == "error" and "some-other-secret" in f.message for f in findings)


def test_plain_value_for_secret_is_an_error():
    entries = clean_entries()
    entries[0] = entry("GH_READ_TOKEN")

    findings = check_collector_env.check_job_env(entries)

    assert any(f.level == "error" and "plain" in f.message for f in findings)


def test_half_deployed_cloudflare_is_a_warning():
    entries = [e for e in clean_entries() if e["name"] != "CLOUDFLARE_ACCOUNT_ID"]

    findings = check_collector_env.check_job_env(entries)

    assert any(f.level == "warn" and "half-deployed" in f.message for f in findings)


def test_optional_group_may_be_entirely_absent():
    entries = [e for e in clean_entries() if e["name"] != "TYPESAFE_API_KEY"]

    assert check_collector_env.check_job_env(entries) == []


def test_wrong_typesafe_secret_mapping_is_an_error():
    entries = clean_entries()
    entries = [
        entry("TYPESAFE_API_KEY", "wrong-secret") if e["name"] == "TYPESAFE_API_KEY" else e
        for e in entries
    ]

    findings = check_collector_env.check_job_env(entries)

    assert any(f.level == "error" and "wrong-secret" in f.message for f in findings)


def test_undeclared_secret_env_is_a_warning():
    entries = clean_entries() + [entry("EXTRA_TOKEN", "extra-secret")]

    findings = check_collector_env.check_job_env(entries)

    assert any(f.level == "warn" and "EXTRA_TOKEN" in f.message for f in findings)


def test_secret_ref_supports_v2_shape():
    v2 = {"name": "X", "valueSource": {"secretKeyRef": {"secret": "s", "version": "latest"}}}

    assert check_collector_env.secret_ref(v2) == "s"


def test_dockerfile_env_parser_and_check():
    text = "FROM x\nENV A=1 \\\n    STATE_DIR=/wrong \\\n    WORK_DIR=/tmp/collector\n"

    values = check_collector_env.parse_dockerfile_env(text)
    findings = check_collector_env.check_image_env(values)

    assert values["STATE_DIR"] == "/wrong"
    assert any(f.level == "error" and "STATE_DIR" in f.message for f in findings)


def test_repo_dockerfile_matches_schema():
    dockerfile = Path(__file__).resolve().parent.parent / "collector" / "Dockerfile"

    values = check_collector_env.parse_dockerfile_env(dockerfile.read_text(encoding="utf-8"))

    assert check_collector_env.check_image_env(values) == []


def test_extract_container_env_reads_the_cli_shape():
    env = [entry("GH_READ_TOKEN", "gh-read-token")]
    job = {"spec": {"template": {"spec": {"template": {"spec": {"containers": [{"env": env}]}}}}}}

    assert check_collector_env.extract_container_env(job) == env


def test_run_describe_refuses_work_account():
    with pytest.raises(check_collector_env.CheckError, match="refusing"):
        check_collector_env.run_describe("harlan@primeiq.ai", "p", "r", "j")
