"""robots.txt rules per RFC 9309. Parsing only; fetching happens in the crawl service.

Stdlib `urllib.robotparser` is not used: it ignores `*`/`$` wildcards and applies the first
matching rule instead of the longest one, so it can allow paths a site disallows.
"""

from __future__ import annotations

import contextlib
import re
from dataclasses import dataclass, field
from functools import lru_cache
from urllib.parse import urlsplit

from extracto.domain.urls import normalize_url


@dataclass
class _Group:
    agents: list[str] = field(default_factory=list)
    rules: list[tuple[bool, str]] = field(default_factory=list)  # (allow, pattern)
    crawl_delay: float | None = None


@lru_cache(maxsize=1024)
def _pattern(path: str) -> re.Pattern[str]:
    anchored = path.endswith("$")
    body = ".*".join(re.escape(part) for part in path.removesuffix("$").split("*"))
    return re.compile(body + ("$" if anchored else ""))


def _parse(text: str) -> tuple[list[_Group], list[str]]:
    groups: list[_Group] = []
    sitemaps: list[str] = []
    current: _Group | None = None
    in_agents = False  # consecutive user-agent lines share one group
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        key, sep, value = line.partition(":")
        if not sep:
            continue
        key, value = key.strip().lower(), value.strip()
        if key == "sitemap":
            if value:
                sitemaps.append(value)
        elif key == "user-agent":
            if current is None or not in_agents:
                current = _Group()
                groups.append(current)
            current.agents.append(value.lower())
            in_agents = True
        elif current is not None:
            in_agents = False
            if key in ("allow", "disallow") and value:
                current.rules.append((key == "allow", value))
            elif key == "crawl-delay":
                with contextlib.suppress(ValueError):
                    current.crawl_delay = float(value)
    return groups, sitemaps


class RobotsRules:
    def __init__(
        self,
        text: str | None = None,
        *,
        allow_all: bool = False,
        disallow_all: bool = False,
        only_url: str | None = None,
    ) -> None:
        self._groups, self._sitemaps = _parse(text) if text is not None else ([], [])
        self._allow_all = allow_all
        self._disallow_all = disallow_all
        self._only_url = normalize_url(only_url) if only_url else None

    @classmethod
    def from_response(cls, status: int | None, text: str, start_url: str) -> RobotsRules:
        """Rules from a robots.txt fetch. `status` is None if the request failed."""
        if status is not None and 200 <= status < 300:
            return cls(text)
        if status in (401, 403):
            return cls(disallow_all=True)
        if status is not None and 400 <= status < 500:
            return cls(allow_all=True)  # no robots.txt: everything allowed
        # Unreachable (network error or 5xx): be safe and fetch only the start URL.
        return cls(only_url=start_url)

    def _matching(self, user_agent: str) -> list[_Group]:
        token = user_agent.split("/", 1)[0].strip().lower()
        named = [g for g in self._groups if token in g.agents]
        return named or [g for g in self._groups if "*" in g.agents]

    def can_fetch(self, url: str, user_agent: str) -> bool:
        if self._allow_all:
            return True
        if self._disallow_all:
            return False
        if self._only_url is not None:
            return normalize_url(url) == self._only_url
        parts = urlsplit(url)
        target = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        if target == "/robots.txt":
            return True
        # Longest matching pattern wins; on a tie, allow wins (RFC 9309 section 2.2.2).
        best: tuple[int, bool] | None = None
        for group in self._matching(user_agent):
            for allow, pattern in group.rules:
                if _pattern(pattern).match(target):
                    candidate = (len(pattern), allow)
                    if best is None or candidate > best:
                        best = candidate
        return best is None or best[1]

    def crawl_delay(self, user_agent: str) -> float | None:
        delays = [g.crawl_delay for g in self._matching(user_agent) if g.crawl_delay is not None]
        return max(delays) if delays else None

    @property
    def sitemaps(self) -> list[str]:
        return list(self._sitemaps)
