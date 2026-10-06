import base64
import os
import re
from pathlib import Path

import pytest

from scripts import collect_mirrors
from scripts.collector_config import (
    CollectorSettings,
    ConfigError,
    Secret,
    load_cloudflare_creds,
)

REQUIRED = {"GH_READ_TOKEN": "read-token", "GH_WRITE_TOKEN": "write-token"}


def write_env_file(tmp_path, text):
    path = tmp_path / "cloudflare.env"
    path.write_text(text, encoding="utf-8")
    return path


def test_from_environ_parses_defaults(tmp_path):
    settings = CollectorSettings.from_environ(REQUIRED, cf_env_file=tmp_path / "missing.env")

    assert settings.gh_read_token.reveal() == "read-token"
    assert settings.require_write_token().reveal() == "write-token"
    assert settings.dry_run is False
    assert settings.state_dir == Path("/mnt/state")
    assert settings.work_dir.is_dir()
    assert settings.cloudflare is None
    assert re.search("agent", settings.author_pattern)


def test_secret_never_reveals_in_repr():
    secret = Secret("super-secret")

    assert "super-secret" not in repr(secret)
    assert "super-secret" not in str(secret)
    assert secret.reveal() == "super-secret"
    assert not Secret("")
    assert Secret("x")


@pytest.mark.parametrize("raw", ["1", "true", "TRUE", "yes", "on"])
def test_dry_run_accepts_truthy_values(raw, tmp_path):
    settings = CollectorSettings.from_environ(
        {"GH_READ_TOKEN": "r", "DRY_RUN": raw}, cf_env_file=tmp_path / "none"
    )

    assert settings.dry_run is True
    assert settings.gh_write_token is None


@pytest.mark.parametrize("raw", ["0", "false", "no", "off"])
def test_dry_run_accepts_falsy_values(raw, tmp_path):
    settings = CollectorSettings.from_environ(
        {"GH_READ_TOKEN": "r", "GH_WRITE_TOKEN": "w", "DRY_RUN": raw}, cf_env_file=tmp_path / "none"
    )

    assert settings.dry_run is False


def test_dry_run_rejects_garbage(tmp_path):
    with pytest.raises(ConfigError, match="DRY_RUN"):
        CollectorSettings.from_environ(
            {"GH_READ_TOKEN": "r", "DRY_RUN": "maybe"}, cf_env_file=tmp_path / "none"
        )


def test_write_token_required_unless_dry_run(tmp_path):
    with pytest.raises(ConfigError, match="GH_WRITE_TOKEN"):
        CollectorSettings.from_environ({"GH_READ_TOKEN": "r"}, cf_env_file=tmp_path / "none")


def test_all_errors_reported_at_once(tmp_path):
    with pytest.raises(ConfigError) as excinfo:
        CollectorSettings.from_environ(
            {"DRY_RUN": "maybe", "AUTHOR_PATTERN": "("}, cf_env_file=tmp_path / "none"
        )

    message = str(excinfo.value)
    for expected in ("GH_READ_TOKEN", "GH_WRITE_TOKEN", "DRY_RUN", "AUTHOR_PATTERN"):
        assert expected in message


def test_direct_construction_enforces_invariants(tmp_path):
    def build(**overrides):
        fields = dict(
            gh_read_token=Secret("r"),
            dry_run=False,
            state_dir=tmp_path,
            work_dir=tmp_path,
            author_pattern="agent",
        )
        fields.update(overrides)
        return CollectorSettings(**fields)

    with pytest.raises(ConfigError, match="GH_READ_TOKEN"):
        build(gh_read_token=Secret(""))
    with pytest.raises(ConfigError, match="GH_WRITE_TOKEN"):
        build()
    assert build(dry_run=True).gh_write_token is None


def test_cloudflare_pair_from_env(tmp_path):
    settings = CollectorSettings.from_environ(
        dict(REQUIRED, CLOUDFLARE_API_TOKEN="t", CLOUDFLARE_ACCOUNT_ID="a"),
        cf_env_file=tmp_path / "none",
    )

    assert settings.cloudflare is not None
    assert settings.cloudflare.token.reveal() == "t"
    assert settings.cloudflare.account_id == "a"


def test_cloudflare_half_pair_is_an_error(tmp_path):
    with pytest.raises(ConfigError, match="CLOUDFLARE_ACCOUNT_ID"):
        CollectorSettings.from_environ(
            dict(REQUIRED, CLOUDFLARE_API_TOKEN="t"), cf_env_file=tmp_path / "none"
        )


def test_cloudflare_file_fallback_and_parsing(tmp_path):
    env_file = write_env_file(
        tmp_path,
        'export CLOUDFLARE_API_TOKEN="file-token"\n\n# comment\nCLOUDFLARE_ACCOUNT_ID=file-account\n',
    )

    settings = CollectorSettings.from_environ(REQUIRED, cf_env_file=env_file)

    assert settings.cloudflare.token.reveal() == "file-token"
    assert settings.cloudflare.account_id == "file-account"


def test_environment_wins_over_file_per_key(tmp_path):
    env_file = write_env_file(tmp_path, "CLOUDFLARE_API_TOKEN=file\nCLOUDFLARE_ACCOUNT_ID=file\n")

    creds = load_cloudflare_creds({"CLOUDFLARE_API_TOKEN": "env"}, env_file)

    assert creds.token.reveal() == "env"
    assert creds.account_id == "file"


def test_load_cloudflare_creds_returns_none_when_absent(tmp_path):
    assert load_cloudflare_creds({}, tmp_path / "none") is None


def test_typesafe_api_key_is_optional_and_trimmed(tmp_path):
    without = CollectorSettings.from_environ(REQUIRED, cf_env_file=tmp_path / "none")
    with_key = CollectorSettings.from_environ(
        dict(REQUIRED, TYPESAFE_API_KEY="  ts-key  "), cf_env_file=tmp_path / "none"
    )

    assert without.typesafe_api_key is None
    assert with_key.typesafe_api_key.reveal() == "ts-key"
    assert "ts-key" not in repr(with_key.typesafe_api_key)


def test_load_cloudflare_creds_does_not_mutate_process_env(tmp_path, monkeypatch):
    monkeypatch.delenv("CLOUDFLARE_API_TOKEN", raising=False)
    monkeypatch.delenv("CLOUDFLARE_ACCOUNT_ID", raising=False)
    env_file = write_env_file(tmp_path, "CLOUDFLARE_API_TOKEN=t\nCLOUDFLARE_ACCOUNT_ID=a\n")

    load_cloudflare_creds({}, env_file)

    assert "CLOUDFLARE_API_TOKEN" not in os.environ
    assert "CLOUDFLARE_ACCOUNT_ID" not in os.environ


def test_git_env_reveals_token_only_into_git_config():
    env = collect_mirrors.git_env(Secret("tok"))

    encoded = env["GIT_CONFIG_VALUE_0"].split()[-1]
    assert base64.b64decode(encoded).decode() == "x-access-token:tok"
