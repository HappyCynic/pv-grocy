# SPDX-FileCopyrightText: 2026 Happy Cynic Software LLC
# SPDX-License-Identifier: Apache-2.0

"""Load config/pv-grocy.yaml plus the Grocy API key from the environment.

The file is per deployment and gitignored; config/pv-grocy.example.yaml is the template.
It holds no secrets: bearer tokens are SHA-256 hashes, and the Grocy API key comes from
PV_GROCY_API_KEY.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
LABEL_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

CONFIG_ENV = "PV_GROCY_CONFIG"
API_KEY_ENV = "PV_GROCY_API_KEY"
# Writes (docs/adr/0002-opt-in-writes.md): off unless this variable is `enabled`.
WRITE_ENV = "PV_GROCY_WRITE"
MAX_WRITES_PER_HOUR = 60
DEFAULT_TIMEOUT_SECONDS = 30.0


class ConfigError(Exception):
    pass


class Access(IntEnum):
    """What a token may do. Each level includes the ones below it (ADR-0002)."""

    READ = 0  # every read tool
    WRITE = 1  # everyday household changes, each reversible or easily redone
    FULL = 2  # also deletes, bulk clears, raw entity access, files, the iCal sharing link

    @property
    def label(self) -> str:
        return self.name.lower()


@dataclass(frozen=True)
class TokenConfig:
    label: str
    sha256: str
    access: Access = Access.READ
    max_writes_per_hour: int = MAX_WRITES_PER_HOUR


@dataclass(frozen=True)
class Config:
    grocy_url: str
    api_key: str
    tokens: tuple[TokenConfig, ...]
    write: bool = False
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS

    @property
    def max_access(self) -> Access:
        return Access.FULL if self.write else Access.READ


def _known_keys(where: str, raw: Mapping[str, Any], known: tuple[str, ...]) -> None:
    unknown = set(raw) - set(known)
    if unknown:
        raise ConfigError(f"{where}: unknown key(s) {', '.join(sorted(unknown))}")


def _mapping(where: str, value: Any) -> Mapping[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ConfigError(f"{where} must be a mapping")
    return value


def _positive_int(where: str, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ConfigError(f"{where} must be a positive integer")
    return value


def _grocy_url(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError("grocy.url is required, e.g. http://grocy:80")
    parts = urlsplit(value.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ConfigError("grocy.url must be an http(s) URL, e.g. http://grocy:80")
    if parts.query or parts.fragment or parts.username or parts.password:
        raise ConfigError("grocy.url must not contain credentials, a query or a fragment")
    return value.strip().rstrip("/")


def _write_switch(env: Mapping[str, str]) -> bool:
    value = env.get(WRITE_ENV, "").strip()
    if value not in ("", "enabled", "disabled"):
        raise ConfigError(f"{WRITE_ENV} must be `enabled`, `disabled` or unset")
    return value == "enabled"


def _token(where: str, raw: Any, write: bool) -> TokenConfig:
    raw = _mapping(where, raw)
    _known_keys(where, raw, ("label", "sha256", "access", "max_writes_per_hour"))
    label = raw.get("label")
    if not isinstance(label, str) or not LABEL_RE.match(label):
        raise ConfigError(f"{where}.label must be lowercase letters, digits, - or _")
    sha = raw.get("sha256")
    if not isinstance(sha, str) or not SHA256_RE.match(sha):
        raise ConfigError(f"{where}.sha256 must be 64 lowercase hex characters")
    level = raw.get("access", "read")
    try:
        access = Access[str(level).upper()]
    except KeyError:
        raise ConfigError(f"{where}.access must be read, write or full") from None
    if access > Access.READ and not write:
        raise ConfigError(
            f"{where}.access is {access.label}, but writes are off; set {WRITE_ENV}=enabled "
            "or give the token access: read"
        )
    limit = _positive_int(
        f"{where}.max_writes_per_hour", raw.get("max_writes_per_hour", MAX_WRITES_PER_HOUR)
    )
    return TokenConfig(label, sha, access, limit)


def parse_config(raw: Any, env: Mapping[str, str]) -> Config:
    raw = _mapping("config", raw)
    _known_keys("config", raw, ("grocy", "tokens"))
    grocy = _mapping("grocy", raw.get("grocy"))
    _known_keys("grocy", grocy, ("url", "timeout_seconds"))
    url = _grocy_url(grocy.get("url"))
    timeout = grocy.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
    if isinstance(timeout, bool) or not isinstance(timeout, int | float) or not 1 <= timeout <= 300:
        raise ConfigError("grocy.timeout_seconds must be a number from 1 to 300")
    api_key = env.get(API_KEY_ENV, "").strip()
    if not api_key:
        raise ConfigError(f"{API_KEY_ENV} is not set (Grocy: Manage API keys)")

    write = _write_switch(env)
    raw_tokens = raw.get("tokens")
    if not isinstance(raw_tokens, list) or not raw_tokens:
        raise ConfigError("tokens must list at least one token (pv-grocy hash-token)")
    tokens = tuple(_token(f"tokens[{i}]", t, write) for i, t in enumerate(raw_tokens))
    for field in ("label", "sha256"):
        values = [getattr(t, field) for t in tokens]
        if len(values) != len(set(values)):
            raise ConfigError(f"tokens: each {field} must be unique")
    return Config(url, api_key, tokens, write, float(timeout))


def load_config(env: Mapping[str, str] | None = None) -> Config:
    env = os.environ if env is None else env
    path = Path(env.get(CONFIG_ENV, "config/pv-grocy.yaml"))
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"cannot read {path}: {exc.strerror}") from None
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path} is not valid YAML: {exc}") from None
    return parse_config(raw, env)
