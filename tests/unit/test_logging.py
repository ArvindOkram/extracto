import json
import logging

import pytest

from extracto.logging import configure_logging


@pytest.fixture(autouse=True)
def _restore_root_logger():
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)


def test_json_format_includes_extra_fields(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO", "json")
    log = logging.getLogger("extracto.test")
    log.info("fetched", extra={"url": "https://a.test/", "status": 200})

    record = json.loads(capsys.readouterr().err.strip())
    assert record["msg"] == "fetched"
    assert record["level"] == "info"
    assert record["url"] == "https://a.test/"
    assert record["status"] == 200


def test_kv_format(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO", "kv")
    logging.getLogger("extracto.test").info("fetched", extra={"status": 200})

    line = capsys.readouterr().err.strip()
    assert 'msg="fetched"' in line
    assert "status=200" in line


def test_level_filters(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("WARNING", "kv")
    logging.getLogger("extracto.test").info("hidden")
    assert capsys.readouterr().err == ""


def test_httpx_request_urls_not_logged(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("DEBUG", "kv")
    logging.getLogger("httpx").info("HTTP Request: POST https://discord.com/api/webhooks/1/secret")
    assert "secret" not in capsys.readouterr().err
