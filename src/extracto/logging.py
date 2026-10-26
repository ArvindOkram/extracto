"""Structured logging setup (JSON lines or key=value)."""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

# Attributes every LogRecord has; anything else was passed via `extra=` and is logged as a field.
_STANDARD_ATTRS = frozenset(vars(logging.makeLogRecord({}))) | {"message", "asctime"}


def _fields(record: logging.LogRecord) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(timespec="milliseconds"),
        "level": record.levelname.lower(),
        "logger": record.name,
        "msg": record.getMessage(),
    }
    fields.update({k: v for k, v in vars(record).items() if k not in _STANDARD_ATTRS})
    if record.exc_info:
        fields["exc"] = logging.Formatter().formatException(record.exc_info)
    return fields


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(_fields(record), default=str)


class KeyValueFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return " ".join(f"{k}={json.dumps(v, default=str)}" for k, v in _fields(record).items())


def configure_logging(level: str = "INFO", fmt: str = "kv") -> None:
    """Configure the root logger. `fmt` is "json" or "kv"."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter() if fmt == "json" else KeyValueFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    # httpx logs every request URL at INFO, which would leak the Discord webhook token.
    # Our own fetch logs already record crawled URLs.
    logging.getLogger("httpx").setLevel(logging.WARNING)
