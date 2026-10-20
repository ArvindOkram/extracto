from pathlib import Path

import pytest

from extracto.settings import Settings, normalize_database_url


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "postgres://u:p@ep-x.neon.tech/db?sslmode=require",
            "postgresql+psycopg://u:p@ep-x.neon.tech/db?sslmode=require",
        ),
        ("postgresql://u:p@h:5432/db", "postgresql+psycopg://u:p@h:5432/db"),
        ("postgresql+psycopg://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
        ("sqlite:///data/monitor.db", "sqlite:///data/monitor.db"),
        ("  postgres://u:p@h/db  ", "postgresql+psycopg://u:p@h/db"),
    ],
)
def test_normalize_database_url(raw: str, expected: str) -> None:
    assert normalize_database_url(raw) == expected


def test_default_is_sqlite_in_data_dir(tmp_path: Path) -> None:
    s = Settings(_env_file=None, data_dir=tmp_path)
    assert s.resolved_database_url == f"sqlite:///{(tmp_path / 'monitor.db').as_posix()}"
    assert s.is_sqlite


def test_postgres_url_resolved() -> None:
    s = Settings(_env_file=None, database_url="postgres://u:p@h/db")
    assert s.resolved_database_url == "postgresql+psycopg://u:p@h/db"
    assert not s.is_sqlite


def test_raw_html_defaults_follow_database() -> None:
    assert Settings(_env_file=None).raw_html_enabled is True
    assert Settings(_env_file=None, database_url="postgres://u:p@h/db").raw_html_enabled is False


def test_raw_html_explicit_override() -> None:
    s = Settings(_env_file=None, database_url="postgres://u:p@h/db", keep_raw_html=True)
    assert s.raw_html_enabled is True
    assert Settings(_env_file=None, keep_raw_html=False).raw_html_enabled is False


def test_generic_api_key_env_var_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("API_KEY", "from-some-other-tool")
    monkeypatch.delenv("EXTRACTO_API_KEY", raising=False)
    assert Settings(_env_file=None).api_key is None
    monkeypatch.setenv("EXTRACTO_API_KEY", "ours")
    key = Settings(_env_file=None).api_key
    assert key is not None and key.get_secret_value() == "ours"
