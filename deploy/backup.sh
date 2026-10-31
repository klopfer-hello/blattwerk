#!/usr/bin/env bash
# Manual backup / restore of the garten-planer database. Runs ON the Docker host
# in the stack directory (the PC calls it through scripts/backup.sh). Archives
# stay on the host in ./backups (personal data: never copied to the PC or git).
#   ./backup.sh create [label]       mongodump through FerretDB → backups/<time>[-label].archive.gz
#   ./backup.sh list
#   ./backup.sh restore <file> --yes safety backup first, api stopped while restoring
# The DB password comes from ./.env and reaches the tools container only as an
# environment variable (never on a command line).
set -euo pipefail
cd "$(dirname "$0")"
TOOLS=mongo:8.0.32
DB=garten_planer
KEEP=20
URI="mongodb://gartenplaner@garten-planer-ferretdb:27017/"

PW=$(sed -n 's/^GP_DB_PASSWORD=//p' .env)
[[ -n $PW ]] || { echo "no GP_DB_PASSWORD in .env" >&2; exit 1; }
export PW
net=$(docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{$k}}{{"\n"}}{{end}}' garten-planer-ferretdb | grep '_backend$' || true)
[[ -n $net ]] || { echo "garten-planer-ferretdb is not running" >&2; exit 1; }
mkdir -p backups && chmod 700 backups
docker image inspect "$TOOLS" >/dev/null 2>&1 || docker pull -q "$TOOLS" >/dev/null

tools() {   # run a MongoDB tool with the password in a config file inside the container
  docker run --rm -i --network "$net" -e PW --user 999 --entrypoint sh "$TOOLS" \
    -c 'umask 077; printf "password: %s\n" "$PW" > /tmp/c.yml; exec "$@"' sh "$@"
}

create() {
  local name file
  [[ ${1:-} =~ ^[a-z0-9-]*$ ]] || { echo "label: only a-z, 0-9 and -" >&2; exit 2; }
  name="$(date +%Y%m%d-%H%M%S)${1:+-$1}"
  file="backups/garten-planer-$name.archive.gz"
  tools mongodump --config /tmp/c.yml --uri "$URI" --db "$DB" --archive --gzip --quiet > "$file.tmp"
  [[ -s $file.tmp ]] || { rm -f "$file.tmp"; echo "backup is empty: aborted" >&2; exit 1; }
  chmod 600 "$file.tmp" && mv "$file.tmp" "$file"
  ls -1t backups/garten-planer-*.archive.gz | tail -n +$((KEEP + 1)) | xargs -r rm -f
  echo "created $file ($(du -h "$file" | cut -f1))"
}

restore() {
  local file=${1:-}
  [[ -f $file ]] || { echo "usage: $0 restore backups/<file> --yes" >&2; exit 2; }
  [[ ${2:-} == --yes ]] || { echo "restore replaces ALL current data with $file: add --yes" >&2; exit 2; }
  create pre-restore
  docker stop garten-planer-api >/dev/null
  if tools mongorestore --config /tmp/c.yml --uri "$URI" --drop --archive --gzip --quiet --nsInclude "$DB.*" < "$file"; then
    echo "restored $file"
  else
    echo "restore FAILED (the pre-restore backup above holds the previous state)" >&2
    docker start garten-planer-api >/dev/null
    exit 1
  fi
  docker start garten-planer-api >/dev/null
  for _ in $(seq 1 30); do
    [[ $(docker inspect -f '{{.State.Health.Status}}' garten-planer-api) == healthy ]] && { echo "api healthy"; return; }
    sleep 2
  done
  echo "api did not become healthy" >&2
  exit 1
}

case ${1:-} in
  create) create "${2:-}" ;;
  list) ls -lh backups/ | tail -n +2 ;;
  restore) restore "${2:-}" "${3:-}" ;;
  *) echo "usage: $0 create [label] | list | restore <file> --yes" >&2; exit 2 ;;
esac
