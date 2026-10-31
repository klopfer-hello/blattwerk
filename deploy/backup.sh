#!/usr/bin/env bash
# Manual backup / restore of the garten-planer database. Runs ON the Docker host
# in the stack directory (the PC calls it through scripts/backup.sh). Archives
# stay on the host in ./backups (personal data: never copied to the PC or git).
#   ./backup.sh create [label]        pg_dump -Fc → backups/garten-planer-<time>[-label].dump
#   ./backup.sh list
#   ./backup.sh restore <file> --yes  safety backup first, api stopped while restoring
# pg_dump/pg_restore run inside the db container over its local socket: no
# password on any command line, no extra tools container.
set -euo pipefail
cd "$(dirname "$0")"
DB=garten_planer
USER=gartenplaner
KEEP=20

docker inspect -f '{{.State.Running}}' garten-planer-db 2>/dev/null | grep -q true \
  || { echo "garten-planer-db is not running" >&2; exit 1; }
mkdir -p backups && chmod 700 backups

create() {
  local name file
  [[ ${1:-} =~ ^[a-z0-9-]*$ ]] || { echo "label: only a-z, 0-9 and -" >&2; exit 2; }
  name="$(date +%Y%m%d-%H%M%S)${1:+-$1}"
  file="backups/garten-planer-$name.dump"
  (umask 077; docker exec garten-planer-db pg_dump -U "$USER" -d "$DB" -Fc > "$file.tmp")
  [[ -s $file.tmp ]] || { rm -f "$file.tmp"; echo "backup is empty: aborted" >&2; exit 1; }
  mv "$file.tmp" "$file"
  ls -1t backups/garten-planer-*.dump | grep -vxF "${PROTECT:-}" | tail -n +$((KEEP + 1)) | xargs -r rm -f
  echo "created $file ($(du -h "$file" | cut -f1))"
}

restore() {
  local file=${1:-}
  [[ -f $file && $file == *.dump ]] || { echo "usage: $0 restore backups/<file>.dump --yes" >&2; exit 2; }
  [[ ${2:-} == --yes ]] || { echo "restore replaces ALL current data with $file: add --yes" >&2; exit 2; }
  exec 3<"$file"           # opened before the safety backup ...
  PROTECT=$file create pre-restore   # ... and kept out of its rotation
  docker stop garten-planer-api >/dev/null
  if docker exec -i garten-planer-db pg_restore -U "$USER" -d "$DB" --clean --if-exists --single-transaction --no-owner <&3; then
    echo "restored $file"
  else
    echo "restore FAILED, nothing changed (single transaction); the pre-restore backup is above" >&2
    docker compose up -d >/dev/null 2>&1
    exit 1
  fi
  # compose, not "docker start": an older dump may need the migrations applied again (migrate → api)
  docker compose up -d >/dev/null 2>&1
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
