#!/usr/bin/env bash
# Build the blattwerk images (web + api) on this PC, ship them to the Docker
# host over SSH and switch the stack there. A failed switch (compose error, a
# container not healthy, wrong image running) rolls back to the previous images.
# Host facts come only from the gitignored scripts/deploy.local.env. The DB
# password is generated ON the host into its .env and never leaves it.
#   scripts/deploy.sh                    test, build HEAD, ship, switch
#   scripts/deploy.sh --allow-dirty      deploy uncommitted changes (+sha.dirty.<time>)
#   scripts/deploy.sh --version <tag>    switch back to images already on the host (e.g. 0.2.0-beta.1-<sha>)
#   A rollback restores the previous compose file too; past a DB migration it also needs
#   the backup taken before the deploy (scripts/backup.sh restore …).
# Before a deploy with a DB schema change: make a backup first (ticket 011).
set -euo pipefail
cd "$(dirname "$0")/.."
export MSYS_NO_PATHCONV=1

[[ -f scripts/deploy.local.env ]] || { echo "missing scripts/deploy.local.env" >&2; exit 1; }
# shellcheck disable=SC1091
source scripts/deploy.local.env
: "${DEPLOY_HOST:?}" "${DEPLOY_DIR:?}" "${BW_HOST:?}" "${TRAEFIK_NETWORK:?}"

tag='' dirty=false
while [[ $# -gt 0 ]]; do
  case $1 in
    --version) tag=$2; shift 2 ;;
    --allow-dirty) dirty=true; shift ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
ssh_() { ssh -o BatchMode=yes "$DEPLOY_HOST" "$@"; }

if [[ -z $tag ]]; then
  sha=$(git rev-parse --short=12 HEAD)
  if [[ -n "$(git status --porcelain)" ]]; then
    $dirty || { echo "working tree is dirty: commit first or pass --allow-dirty" >&2; exit 1; }
    sha="${sha}.dirty.$(date +%H%M%S)"
  fi
  version="$(tr -d '[:space:]' < VERSION)+${sha}"
  tag=${version//+/-}
  echo "==> tests"
  bash scripts/test.sh >/dev/null 2>&1 || { echo "tests failed: run scripts/test.sh" >&2; exit 1; }
  echo "==> building ${tag}"
  docker build -q -t "blattwerk-web:$tag" --build-arg VERSION="$version" web >/dev/null
  docker build -q -t "blattwerk-api:$tag" --target runtime --build-arg VERSION="$version" api >/dev/null
  for img in "blattwerk-web:$tag" "blattwerk-api:$tag"; do
    if ssh_ docker image inspect "$img" >/dev/null 2>&1; then
      echo "    $img already on the host"
    else
      echo "==> shipping $img"
      docker save "$img" | ssh_ docker load >/dev/null
    fi
  done
else
  version=$(ssh_ docker run --rm --entrypoint cat "blattwerk-web:$tag" /usr/share/nginx/html/version.txt)
fi

echo "==> switching to ${tag}"
ssh_ "mkdir -p '$DEPLOY_DIR'"
scp -q deploy/docker-compose.yml "$DEPLOY_HOST:$DEPLOY_DIR/docker-compose.yml.new"
scp -q deploy/telegraf.conf "$DEPLOY_HOST:$DEPLOY_DIR/telegraf.conf.new"
scp -q deploy/backup.sh "$DEPLOY_HOST:$DEPLOY_DIR/"
scp -q deploy/switch.sh "$DEPLOY_HOST:$DEPLOY_DIR/switch.sh"
ssh_ bash "$DEPLOY_DIR/switch.sh" "$DEPLOY_DIR" "$tag" "$BW_HOST" "$TRAEFIK_NETWORK" "${BW_OLD_HOST:-}"

echo "==> checking https://${BW_HOST}"
web=$(curl -sk --max-time 10 "https://${BW_HOST}/healthz" || true)
apih=$(curl -sk --max-time 10 "https://${BW_HOST}/api/healthz" || true)
if [[ $web != "$version" || $apih != *"\"version\":\"$version\""* || $apih != *'"db":"ok"'* ]]; then
  echo "unexpected answers: web '${web}', api '${apih}'" >&2
  exit 1
fi
echo "web:  ${web}"
echo "api:  ${apih}"
for repo in blattwerk-web blattwerk-api; do   # keep the 3 newest local images
  docker image ls "$repo" --format '{{.Tag}}' | grep -v '^test$' | tail -n +4 | xargs -r -I{} docker image rm -f "$repo:{}" >/dev/null
done
echo "rollback: scripts/deploy.sh --version <previous tag>"
