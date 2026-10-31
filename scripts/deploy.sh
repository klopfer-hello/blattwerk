#!/usr/bin/env bash
# Build the garten-planer image on this PC, ship it to the Docker host over
# SSH and switch the container there. A failed switch (compose error, container
# not healthy, wrong version answering) rolls back to the previous image.
# Host facts come only from the gitignored scripts/deploy.local.env.
#   scripts/deploy.sh                  build HEAD + ship + switch
#   scripts/deploy.sh --allow-dirty    deploy uncommitted changes (version +sha.dirty)
#   scripts/deploy.sh --image <tag>    switch back to an image already on the host
set -euo pipefail
cd "$(dirname "$0")/.."
export MSYS_NO_PATHCONV=1

[[ -f scripts/deploy.local.env ]] || { echo "missing scripts/deploy.local.env" >&2; exit 1; }
# shellcheck disable=SC1091
source scripts/deploy.local.env
: "${DEPLOY_HOST:?}" "${DEPLOY_DIR:?}" "${GP_HOST:?}" "${TRAEFIK_NETWORK:?}"

image='' dirty=false
while [[ $# -gt 0 ]]; do
  case $1 in
    --image) image=$2; shift 2 ;;
    --allow-dirty) dirty=true; shift ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
ssh_() { ssh -o BatchMode=yes "$DEPLOY_HOST" "$@"; }

if [[ -z $image ]]; then
  sha=$(git rev-parse --short=12 HEAD)
  if [[ -n "$(git status --porcelain)" ]]; then
    $dirty || { echo "working tree is dirty: commit first or pass --allow-dirty" >&2; exit 1; }
    sha="${sha}.dirty.$(date +%H%M%S)"
  fi
  version="$(sed -n 's/.*"version": *"\([^"]*\)".*/\1/p' web/package.json)+${sha}"
  image="garten-planer-web:${version//+/-}"
  echo "==> building ${image}"
  docker build -q -t "$image" --build-arg VERSION="$version" web >/dev/null
  if ssh_ docker image inspect "$image" >/dev/null 2>&1; then
    echo "==> image already on the host"
  else
    echo "==> shipping"
    docker save "$image" | ssh_ docker load >/dev/null
  fi
else
  version=$(ssh_ docker run --rm --entrypoint cat "$image" /usr/share/nginx/html/version.txt)
fi

echo "==> switching to ${image}"
ssh_ "mkdir -p '$DEPLOY_DIR'"
scp -q deploy/docker-compose.yml "$DEPLOY_HOST:$DEPLOY_DIR/docker-compose.yml"
ssh_ bash -s -- "$DEPLOY_DIR" "$image" "$GP_HOST" "$TRAEFIK_NETWORK" <<'REMOTE'
set -euo pipefail
cd "$1"; image=$2
touch .env && chmod 600 .env
prev=$(sed -n 's/^GARTEN_PLANER_IMAGE=//p' .env)
setenv() { { grep -v "^$1=" .env || true; echo "$1=$2"; } > .env.new && chmod 600 .env.new && mv .env.new .env; }
setenv GP_HOST "$3"; setenv TRAEFIK_NETWORK "$4"; setenv GARTEN_PLANER_IMAGE "$image"
healthy() {
  for _ in $(seq 1 30); do                      # up to 60 s
    case $(docker inspect -f '{{.State.Health.Status}}' garten-planer-web 2>/dev/null || echo missing) in
      healthy) return 0 ;;
      unhealthy) return 1 ;;
    esac
    sleep 2
  done
  return 1
}
if docker compose up -d --remove-orphans >/dev/null 2>&1 && healthy && \
   [[ $(docker inspect -f '{{.Config.Image}}' garten-planer-web) == "$image" ]]; then
  echo "current: $image (previous: ${prev:-none})"
  exit 0
fi
echo "switch FAILED" >&2
docker logs --tail 20 garten-planer-web >&2 || true
if [[ -n $prev && $prev != "$image" ]]; then
  setenv GARTEN_PLANER_IMAGE "$prev"; docker compose up -d >/dev/null 2>&1 || true
  echo "ROLLED BACK to $prev" >&2
fi
exit 1
REMOTE

echo "==> checking https://${GP_HOST}/healthz"
got=$(curl -sk --max-time 10 "https://${GP_HOST}/healthz" || true)
if [[ $got != "$version" ]]; then
  echo "healthz answers '${got}', expected '${version}'" >&2
  exit 1
fi
echo "healthz: ${got}"
# Keep the 3 newest local images.
docker image ls garten-planer-web --format '{{.Tag}}' | grep -v '^test$' | tail -n +4 | xargs -r -I{} docker image rm -f "garten-planer-web:{}" >/dev/null
echo "rollback: scripts/deploy.sh --image <previous tag>"
