#!/usr/bin/env bash
# gitleaks (pinned image) on the staged changes or on a commit range.
#   scripts/gitleaks.sh staged
#   scripts/gitleaks.sh commits "<git log range args>"
# Exit 3 = Docker not available (callers decide whether that blocks).
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
export MSYS_NO_PATHCONV=1
IMAGE=ghcr.io/gitleaks/gitleaks:v8.21.2
docker info >/dev/null 2>&1 || exit 3
run() { docker run --rm -v "$PWD:/repo" -w /repo "$IMAGE" "$@" --no-banner --redact -v; }
case ${1:-} in
  staged) run protect --staged ;;
  commits) run detect --source . --log-opts="$2" ;;
  *) echo "usage: $0 staged | commits <range>" >&2; exit 2 ;;
esac
