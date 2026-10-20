"""robots.txt rules. Parsing only; fetching happens in the crawl service."""

from __future__ import annotations

from urllib.robotparser import RobotFileParser

from extracto.domain.urls import normalize_url


class RobotsRules:
    def __init__(
        self,
        parser: RobotFileParser | None = None,
        *,
        allow_all: bool = False,
        disallow_all: bool = False,
        only_url: str | None = None,
    ) -> None:
        self._parser = parser
        self._allow_all = allow_all
        self._disallow_all = disallow_all
        self._only_url = normalize_url(only_url) if only_url else None

    @classmethod
    def from_response(cls, status: int | None, text: str, start_url: str) -> RobotsRules:
        """Rules from a robots.txt fetch. `status` is None if the request failed."""
        if status is not None and 200 <= status < 300:
            parser = RobotFileParser()
            parser.parse(text.splitlines())
            return cls(parser)
        if status in (401, 403):
            return cls(disallow_all=True)
        if status is not None and 400 <= status < 500:
            return cls(allow_all=True)  # no robots.txt: everything allowed
        # Unreachable (network error or 5xx): be safe and fetch only the start URL.
        return cls(only_url=start_url)

    def can_fetch(self, url: str, user_agent: str) -> bool:
        if self._allow_all:
            return True
        if self._disallow_all:
            return False
        if self._only_url is not None:
            return normalize_url(url) == self._only_url
        assert self._parser is not None
        return self._parser.can_fetch(user_agent, url)

    def crawl_delay(self, user_agent: str) -> float | None:
        if self._parser is None:
            return None
        delay = self._parser.crawl_delay(user_agent)
        return float(delay) if delay is not None else None

    @property
    def sitemaps(self) -> list[str]:
        if self._parser is None:
            return []
        return list(self._parser.site_maps() or [])
