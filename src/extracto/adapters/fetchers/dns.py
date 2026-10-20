"""Hostname resolution, used to refuse crawling private or internal addresses."""

from __future__ import annotations

import socket


def resolve_host(host: str) -> list[str]:
    """All IP addresses for a hostname. Raises OSError if it can't be resolved."""
    infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    return sorted({str(info[4][0]) for info in infos})
