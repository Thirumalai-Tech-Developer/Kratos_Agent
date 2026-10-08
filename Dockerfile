# syntax=docker/dockerfile:1
FROM node:24-bookworm-slim AS node
FROM ghcr.io/astral-sh/uv:0.12.23 AS uv
FROM python:3.12-slim-bookworm

# Keep the two runtimes together: Studio supervises both over loopback.
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
COPY --from=node /usr/local/include/node /usr/local/include/node
COPY --from=uv /uv /uvx /usr/local/bin/
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
       build-essential pkg-config ca-certificates curl git openssh-client \
       portaudio19-dev libportaudio2 libgl1 libglib2.0-0 libsecret-1-0 \
       xvfb xauth scrot xclip wmctrl ffmpeg \
    && rm -rf /var/lib/apt/lists/*

ENV UV_PYTHON_DOWNLOADS=never \
    UV_HTTP_TIMEOUT=300 \
    UV_HTTP_RETRIES=4 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    NEXT_TELEMETRY_DISABLED=1 \
    HUSKY=0 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/kratos-browsers \
    PATH="/app/.venv/bin:/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin"

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project --python /usr/local/bin/python3.12
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --python /usr/local/bin/python3.12

ARG KRATOS_PORT=21128
ARG OMNIROUTE_BUILD_WORKERS=1
RUN --mount=type=cache,target=/root/.npm \
    --mount=type=cache,target=/app/services/omniroute/.build/next/cache \
    NEXT_PUBLIC_BASE_URL="http://127.0.0.1:${KRATOS_PORT}" \
    BASE_URL="http://127.0.0.1:${KRATOS_PORT}" \
    OMNIROUTE_USE_TURBOPACK=0 CIRCLE_NODE_TOTAL="${OMNIROUTE_BUILD_WORKERS}" \
    NODE_OPTIONS=--max-old-space-size=6144 \
    npm_config_fetch_retries=4 npm_config_fetch_timeout=300000 \
    kratos-studio setup --workspace /tmp/kratos-build

# Python and OmniRoute pin different Playwright versions; install both browsers.
RUN python -m playwright install --with-deps chromium \
    && node services/omniroute/node_modules/playwright/cli.js install chromium \
    && rm -rf /var/lib/apt/lists/*
RUN groupadd --gid 10001 kratos \
    && useradd --uid 10001 --gid 10001 --create-home --shell /bin/bash kratos \
    && install -d -o kratos -g kratos /workspace \
    && chown -R kratos:kratos /app /opt/kratos-browsers

ENV NODE_ENV=production \
    NODE_OPTIONS=--max-old-space-size=2048 \
    KRATOS_PORT=21128 \
    KRATOS_AGENT_PORT=7860 \
    KRATOS_COMPUTER_USE_MCP=false \
    KRATOS_OPENPETS_MCP=false \
    KRATOS_LIVE_ENABLED=false \
    KRATOS_BROWSER_SESSION_SYNC=false \
    KRATOS_CONTEXT7_MCP=false \
    KRATOS_GITNEXUS_MCP=false \
    REQUIRE_API_KEY=true \
    HOME=/home/kratos
USER kratos:kratos
WORKDIR /workspace
HEALTHCHECK --interval=30s --timeout=10s --start-period=300s --retries=3 \
    CMD ["python", "/app/deploy/docker/healthcheck.py"]
ENTRYPOINT ["/bin/sh", "/app/deploy/docker/entrypoint.sh"]
