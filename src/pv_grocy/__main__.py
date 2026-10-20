# SPDX-FileCopyrightText: 2026 Happy Cynic Software LLC
# SPDX-License-Identifier: Apache-2.0

"""Entry point: `pv-grocy` (serve) or `pv-grocy hash-token` (new bearer token + hash)."""

from __future__ import annotations

import hashlib
import ipaddress
import logging
import os
import secrets
import sys

from .config import ConfigError, load_config

log = logging.getLogger("pv_grocy")


def bind_host() -> str:
    """PV_GROCY_HOST, default loopback; warns when plain HTTP is reachable from elsewhere."""
    host = os.environ.get("PV_GROCY_HOST", "127.0.0.1")
    try:
        loopback = host == "localhost" or ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = False
    if not loopback:
        log.warning(
            "listening on %s over plain HTTP (no TLS): reach it only through a private network "
            "or a TLS reverse proxy or tunnel, never directly from the internet. "
            "See the README's Security model.",
            host,
        )
    return host


def forwarded_allow_ips() -> str | None:
    """Proxies whose X-Forwarded-* headers are trusted (for client addresses in logs);
    never `*`."""
    value = os.environ.get("PV_GROCY_FORWARDED_ALLOW_IPS", "").strip()
    if "*" in value:
        sys.exit("pv-grocy: config error: PV_GROCY_FORWARDED_ALLOW_IPS must not contain '*'")
    return value or None


def main() -> None:
    if sys.argv[1:2] == ["hash-token"]:
        token = secrets.token_urlsafe(32)
        print(f"token:  {token}\nsha256: {hashlib.sha256(token.encode()).hexdigest()}")
        return

    import uvicorn

    from .server import Runtime, configure_logging, create_app

    configure_logging(os.environ.get("PV_GROCY_LOG_LEVEL", "INFO"))
    try:
        config = load_config()
    except ConfigError as exc:
        sys.exit(f"pv-grocy: config error: {exc}")
    log.info(
        "writes %s; tokens: %s",
        "enabled" if config.write else "off",
        ", ".join(f"{t.label} ({t.access.label})" for t in config.tokens),
    )
    proxies = forwarded_allow_ips()
    uvicorn.run(
        create_app(Runtime(config)),
        host=bind_host(),
        port=int(os.environ.get("PV_GROCY_PORT", "8772")),
        log_level="warning",
        server_header=False,
        proxy_headers=proxies is not None,
        forwarded_allow_ips=proxies,
    )


if __name__ == "__main__":
    main()
