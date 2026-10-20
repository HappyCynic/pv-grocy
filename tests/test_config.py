# SPDX-FileCopyrightText: 2026 Happy Cynic Software LLC
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from pv_grocy.config import Access, ConfigError, load_config, parse_config

SHA = "a" * 64
ENV = {"PV_GROCY_API_KEY": "k"}


def raw(**token: Any) -> dict[str, Any]:
    return {
        "grocy": {"url": "http://grocy:80/"},
        "tokens": [{"label": "t", "sha256": SHA, **token}],
    }


def test_minimal_config_is_read_only() -> None:
    cfg = parse_config(raw(), ENV)
    assert cfg.grocy_url == "http://grocy:80"
    assert cfg.write is False
    assert cfg.tokens[0].access == Access.READ
    assert cfg.tokens[0].max_writes_per_hour == 60


def test_write_access_needs_the_switch() -> None:
    with pytest.raises(ConfigError, match="writes are off"):
        parse_config(raw(access="write"), ENV)
    cfg = parse_config(raw(access="full"), {**ENV, "PV_GROCY_WRITE": "enabled"})
    assert cfg.write and cfg.tokens[0].access == Access.FULL


@pytest.mark.parametrize("value", ["yes", "true", "Enabled", "1"])
def test_switch_takes_only_enabled_or_disabled(value: str) -> None:
    with pytest.raises(ConfigError, match="PV_GROCY_WRITE"):
        parse_config(raw(), {**ENV, "PV_GROCY_WRITE": value})


@pytest.mark.parametrize(
    ("config", "env", "message"),
    [
        (raw(), {}, "PV_GROCY_API_KEY"),
        ({"tokens": raw()["tokens"]}, ENV, "grocy.url"),
        ({**raw(), "grocy": {"url": "ftp://grocy"}}, ENV, "http"),
        ({**raw(), "grocy": {"url": "http://u:p@grocy"}}, ENV, "credentials"),
        ({**raw(), "grocy": {"url": "http://grocy", "timeout_seconds": 0}}, ENV, "timeout"),
        ({**raw(), "extra": 1}, ENV, "unknown key"),
        ({"grocy": {"url": "http://g"}, "tokens": []}, ENV, "at least one token"),
        (raw(sha256="xyz"), ENV, "sha256"),
        (raw(label="Bad Label"), ENV, "label"),
        (raw(access="admin"), ENV, "read, write or full"),
        (raw(max_writes_per_hour=0), ENV, "positive"),
        (raw(scopes=["x"]), ENV, "unknown key"),
        (
            {
                "grocy": {"url": "http://g"},
                "tokens": [{"label": "a", "sha256": SHA}, {"label": "b", "sha256": SHA}],
            },
            ENV,
            "unique",
        ),
    ],
)
def test_invalid_config(config: Any, env: dict[str, str], message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        parse_config(config, env)


def test_load_config_from_file(tmp_path: Path) -> None:
    path = tmp_path / "c.yaml"
    path.write_text(f"grocy:\n  url: http://grocy\ntokens:\n  - label: t\n    sha256: {SHA}\n")
    cfg = load_config({**ENV, "PV_GROCY_CONFIG": str(path)})
    assert cfg.tokens[0].label == "t"
    with pytest.raises(ConfigError, match="cannot read"):
        load_config({**ENV, "PV_GROCY_CONFIG": str(tmp_path / "missing.yaml")})
    path.write_text("grocy: [")
    with pytest.raises(ConfigError, match="not valid YAML"):
        load_config({**ENV, "PV_GROCY_CONFIG": str(path)})


def test_example_config_is_valid() -> None:
    example = Path(__file__).resolve().parent.parent / "config" / "pv-grocy.example.yaml"
    cfg = load_config({**ENV, "PV_GROCY_CONFIG": str(example)})
    assert all(t.access == Access.READ for t in cfg.tokens)
