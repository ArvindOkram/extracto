from pathlib import Path

import pytest

from extracto.config import ConfigError, load_config

VALID = """
defaults:
  user_agent: "Extracto/0.1 (contact: me@x.test)"
  delay_seconds: 2.5
  exclude_patterns: ["/login"]
sites:
  - name: A
    start_url: https://www.a.test/
    sitemap_url: https://www.a.test/sitemap.xml
    allow_patterns: ["^/(pricing|blog)"]
    exclude_patterns: ["/tag/"]
  - name: B
    start_url: https://b.test/
    max_pages: 50
    render_js: true
"""


def write(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "sites.yaml"
    path.write_text(content, encoding="utf-8")
    return path


def test_defaults_merge_into_each_site(tmp_path: Path) -> None:
    cfg = load_config(write(tmp_path, VALID))
    a, b = cfg.sites

    assert a.delay_seconds == b.delay_seconds == 2.5
    assert a.max_pages == 500 and b.max_pages == 50
    assert b.render_js is True and a.render_js is False
    assert a.user_agent == "Extracto/0.1 (contact: me@x.test)"
    assert a.timeout_seconds == 20 and a.max_bytes == 2_097_152 and a.max_depth == 3


def test_exclude_patterns_extend_defaults(tmp_path: Path) -> None:
    a, b = load_config(write(tmp_path, VALID)).sites
    assert a.exclude_patterns == ["/login", "/tag/"]
    assert b.exclude_patterns == ["/login"]


def test_site_domain_strips_www(tmp_path: Path) -> None:
    a, b = load_config(write(tmp_path, VALID)).sites
    assert a.domain == "a.test"
    assert b.domain == "b.test"


def test_lookup_site_by_name(tmp_path: Path) -> None:
    cfg = load_config(write(tmp_path, VALID))
    assert cfg.site("B").start_url == "https://b.test/"
    with pytest.raises(ConfigError, match="unknown site 'C'"):
        cfg.site("C")


def test_user_agent_required(tmp_path: Path) -> None:
    content = VALID.replace('  user_agent: "Extracto/0.1 (contact: me@x.test)"\n', "")
    with pytest.raises(ConfigError, match="user_agent"):
        load_config(write(tmp_path, content))


def test_bad_url_gives_readable_error(tmp_path: Path) -> None:
    content = VALID.replace("https://b.test/", "ftp://b.test/")
    with pytest.raises(ConfigError, match=r"sites\.1\.start_url"):
        load_config(write(tmp_path, content))


def test_invalid_regex_rejected(tmp_path: Path) -> None:
    content = VALID.replace('["/tag/"]', '["(unclosed"]')
    with pytest.raises(ConfigError, match="invalid regex"):
        load_config(write(tmp_path, content))


def test_duplicate_site_names_rejected(tmp_path: Path) -> None:
    content = VALID.replace("name: B", "name: A")
    with pytest.raises(ConfigError, match="duplicate site name"):
        load_config(write(tmp_path, content))


def test_unknown_field_rejected(tmp_path: Path) -> None:
    content = VALID.replace("max_pages: 50", "max_pagez: 50")
    with pytest.raises(ConfigError, match="max_pagez"):
        load_config(write(tmp_path, content))


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nope.yaml")


def test_example_config_is_valid() -> None:
    cfg = load_config(Path(__file__).parents[2] / "config" / "sites.example.yaml")
    assert len(cfg.sites) >= 2
