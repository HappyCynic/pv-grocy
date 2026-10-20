# SPDX-FileCopyrightText: 2026 Happy Cynic Software LLC
# SPDX-License-Identifier: Apache-2.0

# Production image for pv-grocy. Non-root, runs with a read-only root FS and keeps no state.
# Build: docker build -t ghcr.io/happycynic/pv-grocy:dev .
# Base images are pinned by digest (tag kept for readability); Dependabot bumps them.

FROM python:3.14-slim-trixie@sha256:a2b82f3c48559aa0a8446d9af49826b6e2b2016f4cd2afabfe6013ec53729170 AS build
COPY --from=ghcr.io/astral-sh/uv:0.12@sha256:3af4716e991d6956a41e573eab705d0ee08500cd829ed30293eb8472f372c65a /uv /usr/local/bin/
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /src
# Dependencies first so source edits don't invalidate the layer.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY README.md LICENSE ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.14-slim-trixie@sha256:a2b82f3c48559aa0a8446d9af49826b6e2b2016f4cd2afabfe6013ec53729170
# Fixed uid:gid 10001:10001. pip is not needed at runtime and vendors its own (often
# outdated) copies of urllib3 and others, so it goes.
RUN groupadd --system --gid 10001 pv \
    && useradd --system --uid 10001 --gid 10001 --home-dir /nonexistent --shell /usr/sbin/nologin pv \
    && python -m pip uninstall --yes --quiet pip
COPY --from=build /app/.venv /app/.venv
COPY LICENSE NOTICE /usr/share/doc/pv-grocy/
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PV_GROCY_CONFIG=/config/pv-grocy.yaml \
    PV_GROCY_HOST=0.0.0.0 \
    PV_GROCY_PORT=8772
USER pv
EXPOSE 8772
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --start-interval=2s \
    CMD ["python", "-c", "import os,urllib.request as u; u.urlopen(f'http://127.0.0.1:{os.environ[\"PV_GROCY_PORT\"]}/healthz', timeout=4)"]
ENTRYPOINT ["pv-grocy"]
