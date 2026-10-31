#!/usr/bin/env bash
# All tests, in Docker (nothing to install on the PC):
#   scripts/test.sh          api (lint, types, pytest against a real PostgreSQL) + web (type-check, build)
#   scripts/test.sh api      only the api suite;  scripts/test.sh web   only the web build
#   scripts/test.sh api -k settings   extra args go to pytest
# The api stack runs as compose project garten-planer-test and is always removed.
set -euo pipefail
cd "$(dirname "$0")/.."
export MSYS_NO_PATHCONV=1
what=${1:-all}; shift || true
rc=0

if [[ $what == all || $what == api ]]; then
  echo "==> api"
  compose=(docker compose -p garten-planer-test -f api/compose.test.yml)
  trap '"${compose[@]}" down -v --remove-orphans >/dev/null 2>&1 || true' EXIT
  "${compose[@]}" build -q tests
  if [[ $# -gt 0 ]]; then
    "${compose[@]}" run --rm tests uv run --frozen --no-sync pytest "$@" || rc=1
  else
    "${compose[@]}" run --rm tests || rc=1
  fi
fi

if [[ $what == all || $what == web ]]; then
  echo "==> web"
  docker run --rm -v "$PWD/web:/src" -v /src/node_modules -w /src node:24.21.0-slim \
    sh -c "npm ci --no-audit --no-fund --loglevel=error && npm run build >/dev/null && echo 'web build ok'" || rc=1
fi
exit $rc
