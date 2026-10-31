#!/usr/bin/env bash
# UI smoke test (/ui-smoke): builds the api and web images from the working tree, runs them
# with an invented demo garden (offline: no Claude, no weather) and drives every screen with
# Playwright at iPhone, Android and desktop sizes. Screenshots: scripts/smoke/out/ (gitignored).
set -euo pipefail
cd "$(dirname "$0")/.."
export MSYS_NO_PATHCONV=1
export SMOKE_API_IMAGE=garten-planer-api:smoke SMOKE_WEB_IMAGE=garten-planer-web:smoke
SMOKE_UID=$(id -u); SMOKE_GID=$(id -g); export SMOKE_UID SMOKE_GID
echo "==> building"
docker build -q -t "$SMOKE_API_IMAGE" --target runtime api >/dev/null
docker build -q -t "$SMOKE_WEB_IMAGE" web >/dev/null
compose=(docker compose -p garten-planer-smoke -f scripts/smoke/compose.yml)
trap '"${compose[@]}" down -v --remove-orphans >/dev/null 2>&1 || true' EXIT
rm -rf scripts/smoke/out
echo "==> smoke"
"${compose[@]}" up -d --quiet-pull db migrate api web >/dev/null 2>&1
"${compose[@]}" run --rm smoke
