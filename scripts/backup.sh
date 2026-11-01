#!/usr/bin/env bash
# Backup / restore of the blattwerk database ON the Docker host (archives
# never leave the host). Copies the current deploy/backup.sh there and runs it.
#   scripts/backup.sh create [label]    e.g. before a deploy with a schema change
#   scripts/backup.sh list
#   scripts/backup.sh restore backups/<file> --yes
set -euo pipefail
cd "$(dirname "$0")/.."
export MSYS_NO_PATHCONV=1
# shellcheck disable=SC1091
source scripts/deploy.local.env
: "${DEPLOY_HOST:?}" "${DEPLOY_DIR:?}"
scp -q deploy/backup.sh "$DEPLOY_HOST:$DEPLOY_DIR/backup.sh"
ssh -o BatchMode=yes "$DEPLOY_HOST" "chmod 700 '$DEPLOY_DIR/backup.sh' && '$DEPLOY_DIR/backup.sh' $(printf '%q ' "$@")"
