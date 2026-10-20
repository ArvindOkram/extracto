"""Text cleanup and content hashing. Pure functions, no I/O."""

from __future__ import annotations

import hashlib
import re
import unicodedata

SHORT_TEXT_CHARS = 200

_COOKIE_LINE = re.compile(
    r"\b(we use cookies|this (web)?site uses cookies|accept (all )?cookies|cookie (policy|settings|"
    r"preferences|consent)|manage cookies)\b",
    re.IGNORECASE,
)
_COOKIE_LINE_MAX_CHARS = 300

_MONTHS = (
    r"(jan(uary)?|feb(ruary)?|mar(ch)?|apr(il)?|may|jun(e)?|jul(y)?|aug(ust)?|"
    r"sep(t(ember)?)?|oct(ober)?|nov(ember)?|dec(ember)?)"
)
# Dynamic fragments that change between fetches without the content really changing.
_NOISE = [
    re.compile(r"\blast (updated|modified)\b[:\s]*[^\n.]*", re.IGNORECASE),
    re.compile(rf"\b{_MONTHS}\.? \d{{1,2}}(st|nd|rd|th)?,? \d{{4}}\b", re.IGNORECASE),
    re.compile(rf"\b\d{{1,2}}(st|nd|rd|th)? {_MONTHS}\.?,? \d{{4}}\b", re.IGNORECASE),
    re.compile(r"\b\d{4}-\d{2}-\d{2}(t[\d:.]+z?)?\b", re.IGNORECASE),
    re.compile(r"\b\d{1,2}[/.]\d{1,2}[/.]\d{2,4}\b"),
    re.compile(r"\b\d{1,2}:\d{2}(:\d{2})?\s*([ap]\.?m\.?)?", re.IGNORECASE),
    re.compile(r"\b[\d,.]+\s*[km]?\s+(views?|reads?|shares?|likes?)\b", re.IGNORECASE),
    re.compile(r"\b\d+\s+(seconds?|minutes?|mins?|hours?|days?|weeks?)\s+ago\b", re.IGNORECASE),
]


def normalize_text(text: str) -> str:
    """NFKC-normalize, collapse whitespace within lines, and drop blank lines."""
    text = unicodedata.normalize("NFKC", text)
    lines = (" ".join(line.split()) for line in text.splitlines())
    return "\n".join(line for line in lines if line)


def strip_cookie_lines(text: str) -> str:
    """Remove short cookie-consent lines that slipped past extraction."""
    return "\n".join(
        line
        for line in text.splitlines()
        if not (len(line) <= _COOKIE_LINE_MAX_CHARS and _COOKIE_LINE.search(line))
    )


def content_hash(text: str) -> str:
    """SHA-256 of the text with dynamic noise (dates, times, counters) removed."""
    cleaned = normalize_text(text)
    for pattern in _NOISE:
        cleaned = pattern.sub(" ", cleaned)
    return hashlib.sha256(normalize_text(cleaned).encode("utf-8")).hexdigest()


def is_short_text(text: str, threshold: int = SHORT_TEXT_CHARS) -> bool:
    return len(text) < threshold
