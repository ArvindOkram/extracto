"""Load and validate `sites.yaml`. Defaults merge into each site; errors are human-readable."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


class ConfigError(Exception):
    pass


def _check_http_url(value: str) -> str:
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError(f"must be an http(s) URL, got {value!r}")
    return value


def _check_patterns(patterns: list[str]) -> list[str]:
    for pattern in patterns:
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"invalid regex {pattern!r}: {exc}") from None
    return patterns


class FieldRule(BaseModel):
    """A structured field to track (e.g. a price), by CSS selector or regex."""

    model_config = ConfigDict(extra="forbid")

    selector: str | None = None
    regex: str | None = None
    type: Literal["text", "number"] = "text"

    @model_validator(mode="after")
    def _one_source(self) -> FieldRule:
        if (self.selector is None) == (self.regex is None):
            raise ValueError("set exactly one of selector or regex")
        return self


class _Limits(BaseModel):
    model_config = ConfigDict(extra="forbid")

    delay_seconds: float = Field(2.5, gt=0)
    max_pages: int = Field(500, gt=0)
    max_depth: int = Field(3, ge=0)
    timeout_seconds: float = Field(20, gt=0)
    max_bytes: int = Field(2_097_152, gt=0)
    render_js: bool = False
    exclude_patterns: list[str] = []
    noise_selectors: list[str] = []

    @field_validator("exclude_patterns")
    @classmethod
    def _exclude(cls, value: list[str]) -> list[str]:
        return _check_patterns(value)


class Defaults(_Limits):
    user_agent: str = Field(min_length=1)


class SiteConfig(_Limits):
    name: str = Field(min_length=1)
    start_url: str
    sitemap_url: str | None = None
    allow_patterns: list[str] = []
    extra_domains: list[str] = []
    extractors: dict[str, FieldRule] = {}
    user_agent: str = Field(min_length=1)

    @field_validator("start_url")
    @classmethod
    def _start(cls, value: str) -> str:
        return _check_http_url(value)

    @field_validator("allow_patterns")
    @classmethod
    def _allow(cls, value: list[str]) -> list[str]:
        return _check_patterns(value)

    @field_validator("sitemap_url")
    @classmethod
    def _sitemap(cls, value: str | None) -> str | None:
        return None if value is None else _check_http_url(value)

    @property
    def domain(self) -> str:
        host = urlsplit(self.start_url).hostname or ""
        return host.removeprefix("www.")


class AppConfig(BaseModel):
    defaults: Defaults
    sites: list[SiteConfig]

    @model_validator(mode="after")
    def _unique_names(self) -> AppConfig:
        seen: set[str] = set()
        for site in self.sites:
            if site.name in seen:
                raise ValueError(f"duplicate site name {site.name!r}")
            seen.add(site.name)
        return self

    def site(self, name: str) -> SiteConfig:
        for site in self.sites:
            if site.name == name:
                return site
        raise ConfigError(f"unknown site {name!r}")

    def build_site(self, values: dict[str, Any]) -> SiteConfig:
        """A site not in the file (e.g. from an API request), with defaults applied.

        Raises pydantic's ValidationError on invalid values.
        """
        return SiteConfig.model_validate(_merge(self.defaults.model_dump(), values))


def _merge(defaults: dict[str, Any], site: dict[str, Any]) -> dict[str, Any]:
    merged = {**defaults, **site}
    # Exclusions accumulate so a site can't accidentally drop the global junk filters.
    merged["exclude_patterns"] = [
        *defaults.get("exclude_patterns", []),
        *site.get("exclude_patterns", []),
    ]
    return merged


def _format(exc: ValidationError, prefix: str = "") -> str:
    lines = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in (prefix, *err["loc"]) if p != "")
        lines.append(f"  {loc}: {err['msg']}")
    return "invalid config:\n" + "\n".join(lines)


def load_config(path: Path) -> AppConfig:
    if not path.exists():
        raise ConfigError(f"config file not found: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {path}: {exc}") from None
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: top level must be a mapping with 'defaults' and 'sites'")

    try:
        defaults = Defaults.model_validate(raw.get("defaults") or {})
    except ValidationError as exc:
        raise ConfigError(_format(exc, "defaults")) from None

    sites = raw.get("sites") or []
    if not isinstance(sites, list) or not all(isinstance(s, dict) for s in sites):
        raise ConfigError(f"{path}: 'sites' must be a list of mappings")

    defaults_dict = defaults.model_dump(exclude_unset=False)
    try:
        return AppConfig.model_validate(
            {"defaults": defaults, "sites": [_merge(defaults_dict, s) for s in sites]}
        )
    except ValidationError as exc:
        raise ConfigError(_format(exc)) from None
