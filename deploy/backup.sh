#!/usr/bin/env bash
# Manual backup / restore of the blattwerk database. Runs ON the Docker host
# in the stack directory (the PC calls it through scripts/backup.sh). Archives
# stay on the host in ./backups (personal data: never copied to the PC or git).
#   ./backup.sh create [label]        pg_dump -Fc → backups/blattwerk-<time>[-label].dump
#   ./backup.sh list
#   ./backup.sh restore <file> --yes  safety backup first, api stopped while restoring
#   ./backup.sh restore-weather <file> --yes   InfluxDB data (weather history) from a create run
# pg_dump/pg_restore run inside the db container over its local socket: no
# password on any command line, no extra tools container.
set -euo pipefail
cd "$(dirname "$0")"
DB=blattwerk
USER=blattwerk
KEEP=20

docker inspect -f '{{.State.Running}}' blattwerk-db 2>/dev/null | grep -q true \
  || { echo "blattwerk-db is not running" >&2; exit 1; }
mkdir -p backups && chmod 700 backups

create() {
  local name file
  [[ ${1:-} =~ ^[a-z0-9-]*$ ]] || { echo "label: only a-z, 0-9 and -" >&2; exit 2; }
  name="$(date +%Y%m%d-%H%M%S)${1:+-$1}"
  file="backups/blattwerk-$name.dump"
  (umask 077; docker exec blattwerk-db pg_dump -U "$USER" -d "$DB" -Fc > "$file.tmp")
  [[ -s $file.tmp ]] || { rm -f "$file.tmp"; echo "backup is empty: aborted" >&2; exit 1; }
  mv "$file.tmp" "$file"
  weather "$name" || true
  ls -1t backups/blattwerk-*.dump | grep -vxF "${PROTECT:-}" | tail -n +$((KEEP + 1)) | xargs -r rm -f
  echo "created $file ($(du -h "$file" | cut -f1))"
}

influx_volume() {   # the volume compose actually created (its name follows the stack directory)
  docker inspect -f '{{range .Mounts}}{{if eq .Destination "/var/lib/influxdb3"}}{{.Name}}{{end}}{{end}}' \
    blattwerk-influxdb 2>/dev/null
}
weather() {   # InfluxDB data as tar.gz; best effort: never fails the database backup
  local vol img out="backups/weather-$1.tar.gz"
  vol=$(influx_volume) && [[ -n $vol ]] || return 0   # no weather stack: nothing to do
  img=$(docker inspect -f '{{.Config.Image}}' blattwerk-influxdb)
  docker stop blattwerk-influxdb >/dev/null   # a consistent copy (a few seconds; Telegraf buffers)
  if (umask 077; docker run --rm --network none -v "$vol:/data:ro" --entrypoint tar "$img" czf - -C /data . > "$out.tmp"); then
    mv "$out.tmp" "$out"
    echo "created $out ($(du -h "$out" | cut -f1))"
  else
    rm -f "$out.tmp"
    echo "weather backup failed (database backup is fine)" >&2
  fi
  docker start blattwerk-influxdb >/dev/null
  ls -1t backups/weather-*.tar.gz 2>/dev/null | grep -vxF "${PROTECT:-}" | tail -n +$((KEEP + 1)) | xargs -r rm -f
}
restore_weather() {
  local file=${1:-} vol img
  [[ -f $file && $file == *.tar.gz ]] || { echo "usage: $0 restore-weather backups/weather-<time>.tar.gz --yes" >&2; exit 2; }
  [[ ${2:-} == --yes ]] || { echo "replaces the weather history with $file: add --yes" >&2; exit 2; }
  tar tzf "$file" >/dev/null || { echo "$file is not a readable archive: nothing changed" >&2; exit 1; }
  vol=$(influx_volume) && [[ -n $vol ]] || { echo "no InfluxDB container/volume found: nothing changed" >&2; exit 1; }
  img=$(docker inspect -f '{{.Config.Image}}' blattwerk-influxdb)
  PROTECT=$file weather pre-restore   # safety copy first
  docker stop blattwerk-influxdb >/dev/null
  docker run --rm -i --network none --user 0 -v "$vol:/data" --entrypoint sh "$img" -c \
    'find /data -mindepth 1 -delete && tar xzf - -C /data && chown -R 1500:1500 /data' < "$file"
  docker start blattwerk-influxdb >/dev/null || { echo "influxdb did not start" >&2; exit 1; }
  echo "restored $file"
}
restore() {
  local file=${1:-}
  [[ -f $file && $file == *.dump ]] || { echo "usage: $0 restore backups/<file>.dump --yes" >&2; exit 2; }
  [[ ${2:-} == --yes ]] || { echo "restore replaces ALL current data with $file: add --yes" >&2; exit 2; }
  exec 3<"$file"           # opened before the safety backup ...
  PROTECT=$file create pre-restore   # ... and kept out of its rotation
  docker stop blattwerk-api >/dev/null
  if docker exec -i blattwerk-db pg_restore -U "$USER" -d "$DB" --clean --if-exists --single-transaction --no-owner <&3; then
    echo "restored $file"
  else
    echo "restore FAILED, nothing changed (single transaction); the pre-restore backup is above" >&2
    docker compose up -d >/dev/null 2>&1
    exit 1
  fi
  # compose, not "docker start": an older dump may need the migrations applied again (migrate → api)
  docker compose up -d >/dev/null 2>&1
  for _ in $(seq 1 30); do
    [[ $(docker inspect -f '{{.State.Health.Status}}' blattwerk-api) == healthy ]] && { echo "api healthy"; return; }
    sleep 2
  done
  echo "api did not become healthy" >&2
  exit 1
}

case ${1:-} in
  create) create "${2:-}" ;;
  list) ls -lh backups/ | tail -n +2 ;;
  restore) restore "${2:-}" "${3:-}" ;;
  restore-weather) restore_weather "${2:-}" "${3:-}" ;;
  *) echo "usage: $0 create [label] | list | restore <file> --yes | restore-weather <file> --yes" >&2; exit 2 ;;
esac
