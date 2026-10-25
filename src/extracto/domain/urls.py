"""URL normalization and filtering. Pure functions, no I/O."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, quote, urlencode, urljoin, urlsplit, urlunsplit

TRACKING_PARAMS = frozenset({"gclid", "fbclid", "ref", "msclkid", "mc_cid", "mc_eid", "_ga"})
DEFAULT_PORTS = {"http": 80, "https": 443}
JUNK_EXTENSIONS = frozenset(
    [
        "pdf",
        "zip",
        "gz",
        "tar",
        "rar",
        "7z",
        "exe",
        "dmg",
        "msi",
        "mp3",
        "mp4",
        "mov",
        "avi",
        "webm",
        "wav",
        "png",
        "jpg",
        "jpeg",
        "gif",
        "svg",
        "webp",
        "ico",
        "bmp",
        "tiff",
        "css",
        "js",
        "json",
        "xml",
        "rss",
        "woff",
        "woff2",
        "ttf",
        "eot",
        "doc",
        "docx",
        "xls",
        "xlsx",
        "ppt",
        "pptx",
        "csv",
    ]
)


def _is_tracking(key: str) -> bool:
    return key.lower().startswith("utm_") or key.lower() in TRACKING_PARAMS


def normalize_url(url: str, base: str | None = None) -> str | None:
    """Canonical form of an http(s) URL, or None if it isn't one."""
    url = url.strip()
    if not url:
        return None
    if base is not None:
        url = urljoin(base, url)
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return None
    scheme = parts.scheme.lower()
    if scheme not in DEFAULT_PORTS or not parts.hostname:
        return None

    host = parts.hostname.lower()
    netloc = host if port in (None, DEFAULT_PORTS[scheme]) else f"{host}:{port}"
    # The trailing slash is kept: sites that use one redirect the slash-less form, so
    # stripping it would cost an extra request (and crawl delay) for every page.
    path = quote(parts.path, safe="/%:@!$&'()*+,;=-._~") or "/"
    query = urlencode(
        sorted(
            (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not _is_tracking(k)
        )
    )
    return urlunsplit((scheme, netloc, path, query, ""))


@dataclass(frozen=True)
class UrlFilter:
    domains: tuple[str, ...]
    allow: tuple[re.Pattern[str], ...] = ()
    exclude: tuple[re.Pattern[str], ...] = ()
    max_length: int = 300
    max_query_params: int = 3
    max_path_depth: int = 10
    junk_extensions: frozenset[str] = field(default=JUNK_EXTENSIONS)

    @classmethod
    def build(
        cls,
        *,
        domain: str,
        extra_domains: list[str] | None = None,
        allow_patterns: list[str] | None = None,
        exclude_patterns: list[str] | None = None,
    ) -> UrlFilter:
        return cls(
            domains=(domain.lower(), *(d.lower() for d in extra_domains or [])),
            allow=tuple(re.compile(p) for p in allow_patterns or []),
            exclude=tuple(re.compile(p) for p in exclude_patterns or []),
        )

    def on_domain(self, host: str) -> bool:
        return any(host == d or host.endswith("." + d) for d in self.domains)

    def reject_reason(self, url: str, *, check_allow: bool = True) -> str | None:
        """Why a normalized URL should be skipped, or None if it may be crawled."""
        parts = urlsplit(url)
        if not self.on_domain(parts.hostname or ""):
            return "offsite"
        target = parts.path + (f"?{parts.query}" if parts.query else "")
        if any(p.search(target) for p in self.exclude):
            return "excluded"
        last = parts.path.rsplit("/", 1)[-1]
        if "." in last and last.rsplit(".", 1)[-1].lower() in self.junk_extensions:
            return "junk_extension"
        if len(url) > self.max_length:
            return "too_long"
        if len(parse_qsl(parts.query, keep_blank_values=True)) > self.max_query_params:
            return "too_many_params"
        if len([s for s in parts.path.split("/") if s]) > self.max_path_depth:
            return "too_deep"
        if check_allow and self.allow and not any(p.search(target) for p in self.allow):
            return "not_allowed"
        return None
