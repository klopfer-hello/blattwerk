#!/usr/bin/env bash
# Build the garten-planer images (web + api) on this PC, ship them to the Docker
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
: "${DEPLOY_HOST:?}" "${DEPLOY_DIR:?}" "${GP_HOST:?}" "${TRAEFIK_NETWORK:?}"

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
  docker build -q -t "garten-planer-web:$tag" --build-arg VERSION="$version" web >/dev/null
  docker build -q -t "garten-planer-api:$tag" --target runtime --build-arg VERSION="$version" api >/dev/null
  for img in "garten-planer-web:$tag" "garten-planer-api:$tag"; do
    if ssh_ docker image inspect "$img" >/dev/null 2>&1; then
      echo "    $img already on the host"
    else
      echo "==> shipping $img"
      docker save "$img" | ssh_ docker load >/dev/null
    fi
  done
else
  version=$(ssh_ docker run --rm --entrypoint cat "garten-planer-web:$tag" /usr/share/nginx/html/version.txt)
fi

echo "==> switching to ${tag}"
ssh_ "mkdir -p '$DEPLOY_DIR'"
scp -q deploy/docker-compose.yml "$DEPLOY_HOST:$DEPLOY_DIR/docker-compose.yml.new"
scp -q deploy/backup.sh "$DEPLOY_HOST:$DEPLOY_DIR/"
ssh_ bash -s -- "$DEPLOY_DIR" "$tag" "$GP_HOST" "$TRAEFIK_NETWORK" <<'REMOTE'
set -euo pipefail
cd "$1"; tag=$2
touch .env && chmod 600 .env
get() { sed -n "s/^$1=//p" .env; }
setenv() {   # set KEY=value, or remove KEY when value is empty
  { grep -v "^$1=" .env || true; if [[ -n $2 ]]; then echo "$1=$2"; fi; } > .env.new
  chmod 600 .env.new && mv .env.new .env
}
prev_web=$(get GARTEN_PLANER_WEB_IMAGE); prev_api=$(get GARTEN_PLANER_API_IMAGE)
# Keep the compose file that belongs to the previous images: a rollback needs both.
if [[ -f docker-compose.yml ]]; then cp docker-compose.yml docker-compose.yml.prev; fi
mv docker-compose.yml.new docker-compose.yml
[[ -z $prev_web ]] && prev_web=$(get GARTEN_PLANER_IMAGE)       # 0.1.x used one image variable
setenv GARTEN_PLANER_IMAGE ''
[[ -n $(get GP_DB_PASSWORD) ]] || setenv GP_DB_PASSWORD "$(head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n')"
if [[ -z $(get GP_VAPID_PRIVATE) ]]; then   # web push keys: generated here, never leave the host
  keys=$(docker run --rm --network none --entrypoint python "garten-planer-api:$tag" -m garten_planer.push keygen)
  setenv GP_VAPID_PUBLIC "$(sed -n 's/^GP_VAPID_PUBLIC=//p' <<<"$keys")"
  setenv GP_VAPID_PRIVATE "$(sed -n 's/^GP_VAPID_PRIVATE=//p' <<<"$keys")"
fi
setenv GP_HOST "$3"; setenv TRAEFIK_NETWORK "$4"
setenv GARTEN_PLANER_WEB_IMAGE "garten-planer-web:$tag"; setenv GARTEN_PLANER_API_IMAGE "garten-planer-api:$tag"

healthy() {   # every container with a healthcheck healthy, within 90 s
  for _ in $(seq 1 45); do
    ok=true
    for c in garten-planer-db garten-planer-api garten-planer-worker garten-planer-web; do
      case $(docker inspect -f '{{.State.Health.Status}}' "$c" 2>/dev/null || echo missing) in
        healthy) ;;
        unhealthy) return 1 ;;
        *) ok=false ;;
      esac
    done
    $ok && return 0
    sleep 2
  done
  return 1
}
running() { [[ $(docker inspect -f '{{.Config.Image}}' "$1" 2>/dev/null) == "$2" ]]; }

if docker compose up -d --remove-orphans >/dev/null 2>&1 && healthy \
   && running garten-planer-web "garten-planer-web:$tag" && running garten-planer-api "garten-planer-api:$tag"; then
  echo "current: $tag (previous web: ${prev_web:-none}, api: ${prev_api:-none})"
  exit 0
fi
echo "switch FAILED" >&2
for c in garten-planer-migrate garten-planer-api garten-planer-worker garten-planer-web; do docker logs --tail 15 "$c" 2>&1 | sed "s/^/[$c] /" >&2 || true; done
if [[ -n $prev_web && -n $prev_api ]]; then
  [[ -f docker-compose.yml.prev ]] && cp docker-compose.yml.prev docker-compose.yml
  setenv GARTEN_PLANER_WEB_IMAGE "$prev_web"; setenv GARTEN_PLANER_API_IMAGE "$prev_api"
  docker compose up -d --remove-orphans >/dev/null 2>&1 || true
  echo "ROLLED BACK to $prev_web / $prev_api (with the previous compose file)" >&2
  echo "If the failed version had already migrated the DB: restore the backup taken before the deploy." >&2
elif [[ -n $prev_web ]]; then   # first deploy with a backend: back to the web-only prototype
  docker compose stop api worker db >/dev/null 2>&1 || true
  [[ -f docker-compose.yml.prev ]] && cp docker-compose.yml.prev docker-compose.yml
  setenv GARTEN_PLANER_WEB_IMAGE "$prev_web"
  docker compose up -d --no-deps web >/dev/null 2>&1 || true
  echo "ROLLED BACK to $prev_web (backend stopped)" >&2
fi
exit 1
REMOTE

echo "==> checking https://${GP_HOST}"
web=$(curl -sk --max-time 10 "https://${GP_HOST}/healthz" || true)
apih=$(curl -sk --max-time 10 "https://${GP_HOST}/api/healthz" || true)
if [[ $web != "$version" || $apih != *"\"version\":\"$version\""* || $apih != *'"db":"ok"'* ]]; then
  echo "unexpected answers: web '${web}', api '${apih}'" >&2
  exit 1
fi
echo "web:  ${web}"
echo "api:  ${apih}"
for repo in garten-planer-web garten-planer-api; do   # keep the 3 newest local images
  docker image ls "$repo" --format '{{.Tag}}' | grep -v '^test$' | tail -n +4 | xargs -r -I{} docker image rm -f "$repo:{}" >/dev/null
done
echo "rollback: scripts/deploy.sh --version <previous tag>"
