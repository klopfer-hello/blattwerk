#!/usr/bin/env bash
# One-time setup of a fresh clone: activate the repo's git hooks and the
# public commit identity, and create the local deny list if missing.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
git config core.hooksPath scripts/hooks
git config user.name "Klopfer Hello"
git config user.email "forkent@icloud.com"
mkdir -p .claude
[[ -f .claude/private-terms.txt ]] || printf '%s\n' \
  '# One extended regex per line, case-insensitive. Never commit this file.' \
  '# Add: real name, private e-mail, Windows user name, town/PLZ, street, host names, HA host.' >.claude/private-terms.txt
echo "hooks: $(git config core.hooksPath), identity: $(git config user.name) <$(git config user.email)>"
