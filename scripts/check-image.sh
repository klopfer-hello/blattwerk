#!/usr/bin/env bash
# Image gate (CI and release): the Claude Code CLI is Anthropic's proprietary software and must never be part of
# an image (ADR 0002); the worker installs the pinned version into the /claude volume at runtime.
#   scripts/check-image.sh <image> [<image> ...]
set -euo pipefail
rc=0
for img in "$@"; do
  found=$(docker run --rm --network none --entrypoint sh "$img" -c \
    'command -v claude 2>/dev/null
     find / -xdev \( -type f -name claude -o -type d -name @anthropic-ai \) 2>/dev/null | head -5
     [ -d /claude ] && find /claude -mindepth 1 2>/dev/null | head -5   # the mount point of the volume: empty' \
    || true)
  if [[ -n $found ]]; then
    echo "FAIL $img contains the Claude Code CLI:" >&2
    sed 's/^/  /' <<<"$found" >&2
    rc=1
  else
    echo "ok   $img: no Claude Code CLI"
  fi
done
exit $rc
