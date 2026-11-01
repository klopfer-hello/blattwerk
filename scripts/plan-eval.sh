#!/usr/bin/env bash
# /plan-eval: run the fixed plant + name set through the real Claude CLI inside the
# deployed worker (no DB writes). Arguments: --plans | --names (default: both).
# Costs about USD 0.5 per full run on the account behind CLAUDE_CODE_OAUTH_TOKEN.
set -euo pipefail
cd "$(dirname "$0")/.."
[[ -f scripts/deploy.local.env ]] || { echo "missing scripts/deploy.local.env" >&2; exit 1; }
source scripts/deploy.local.env
arg=${1:-all}
case $arg in all|--plans|--names) ;; *) echo "usage: $0 [--plans|--names]" >&2; exit 2 ;; esac
exec ssh -o BatchMode=yes "$DEPLOY_HOST" docker exec blattwerk-worker python -m blattwerk.plan_eval "$arg"
