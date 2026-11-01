#!/usr/bin/env bash
# Switch a Blattwerk host to a version: runs ON the Docker host, in the stack directory.
# Used by scripts/deploy.sh (over SSH, images built on the PC) and by self-hosters with the
# images from GHCR (docs/self-hosting.md):
#   bash switch.sh <dir> <tag> <host name> <traefik network> [<former host name>]
#   IMAGE_PREFIX=ghcr.io/klopfer-hello/blattwerk bash switch.sh . 0.16.0 plants.example.org proxy
# Secrets (DB passwords, VAPID keys, the InfluxDB token) are generated here into .env (mode 600) and never
# leave the host. A failed switch rolls back to the previous images and compose file.
set -euo pipefail
prefix=${IMAGE_PREFIX:-blattwerk}   # images: <prefix>-web:<tag>, <prefix>-api:<tag>
cd "$1"; tag=$2
touch .env && chmod 600 .env
get() { sed -n "s/^$1=//p" .env; }
setenv() {   # set KEY=value, or remove KEY when value is empty
  { grep -v "^$1=" .env || true; if [[ -n $2 ]]; then echo "$1=$2"; fi; } > .env.new
  chmod 600 .env.new && mv .env.new .env
}
# InfluxDB admin token, before anything is switched (a failure here leaves the running version alone).
# Created offline into its own volume (uid 1500, mode 400), copied into .env; never leaves the host.
[[ -f docker-compose.yml.new ]] || cp docker-compose.yml docker-compose.yml.new
[[ -f telegraf.conf.new ]] || cp telegraf.conf telegraf.conf.new
influx_img=$(tr -d '\r' < docker-compose.yml.new | sed -n 's/^ *image: *\(influxdb:[^ #]*\).*$/\1/p' | head -1)
vol=blattwerk-influx-secret   # same name as in docker-compose.yml
docker volume create "$vol" >/dev/null   # idempotent: also brings back a pruned volume
docker run --rm --network none --user 0 --entrypoint sh -v "$vol:/secret" "$influx_img" -c \
  'test -s /secret/admin.json || influxdb3 create token --admin --offline --output-file /secret/admin.json >/dev/null; chown 1500:1500 /secret/admin.json && chmod 400 /secret/admin.json'
token=$(docker run --rm --network none --user 0 --entrypoint cat -v "$vol:/secret:ro" "$influx_img" /secret/admin.json \
  | sed -n 's/.*"token" *: *"\([^"]*\)".*/\1/p')
[[ -n $token ]] || { echo "could not read the InfluxDB token" >&2; exit 1; }
[[ $(get BW_INFLUX_TOKEN) == "$token" ]] || setenv BW_INFLUX_TOKEN "$token"   # file and .env always agree
unset token

prev_web=$(get BLATTWERK_WEB_IMAGE); prev_api=$(get BLATTWERK_API_IMAGE)
# Keep the files that belong to the previous images: a rollback needs them.
if [[ -f docker-compose.yml ]]; then cp docker-compose.yml docker-compose.yml.prev; fi
mv docker-compose.yml.new docker-compose.yml
conf_changed=false
if ! cmp -s telegraf.conf.new telegraf.conf 2>/dev/null; then
  [[ -f telegraf.conf ]] && cp telegraf.conf telegraf.conf.prev
  conf_changed=true
fi
mv telegraf.conf.new telegraf.conf
[[ -z $prev_web ]] && prev_web=$(get BLATTWERK_IMAGE)       # 0.1.x used one image variable
setenv BLATTWERK_IMAGE ''
[[ -n $(get BW_DB_PASSWORD) ]] || setenv BW_DB_PASSWORD "$(head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n')"
[[ -n $(get BW_MCP_DB_PASSWORD) ]] || setenv BW_MCP_DB_PASSWORD "$(head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n')"
if [[ -z $(get BW_VAPID_PRIVATE) ]]; then   # web push keys: generated here, never leave the host
  keys=$(docker run --rm --network none --entrypoint python "$prefix-api:$tag" -m blattwerk.push keygen)
  setenv BW_VAPID_PUBLIC "$(sed -n 's/^BW_VAPID_PUBLIC=//p' <<<"$keys")"
  setenv BW_VAPID_PRIVATE "$(sed -n 's/^BW_VAPID_PRIVATE=//p' <<<"$keys")"
fi
round2() {   # about 1 km; a malformed value (comma, text) stops the deploy instead of becoming 0.00
  [[ -z $1 ]] && return 0
  [[ $1 =~ ^-?[0-9]+(\.[0-9]+)?$ ]] || { echo "BW_LAT/BW_LON in .env must look like 51.05 (got '$1')" >&2; return 1; }
  LC_ALL=C printf '%.2f' "$1"
}
lat_km=$(round2 "$(get BW_LAT)") && lon_km=$(round2 "$(get BW_LON)") || exit 1
setenv BW_LAT_KM "$lat_km"; setenv BW_LON_KM "$lon_km"
# Telegraf (Home Assistant + Open-Meteo) only when Home Assistant is configured: weather is optional.
if [[ -n $(get BW_HA_URL) && -n $(get BW_HA_TOKEN) ]]; then setenv COMPOSE_PROFILES weather; else setenv COMPOSE_PROFILES ''; fi
setenv BW_HOST "$3"; setenv TRAEFIK_NETWORK "$4"; setenv BW_OLD_HOST "${5:-}"
for img in "$prefix-web:$tag" "$prefix-api:$tag"; do   # GHCR images: pulled once
  docker image inspect "$img" >/dev/null 2>&1 || docker pull -q "$img" >/dev/null
done
setenv BLATTWERK_WEB_IMAGE "$prefix-web:$tag"; setenv BLATTWERK_API_IMAGE "$prefix-api:$tag"

healthy() {   # the garden app's containers healthy, within 90 s (weather problems never roll back the app)
  for _ in $(seq 1 45); do
    ok=true
    for c in blattwerk-db blattwerk-api blattwerk-worker blattwerk-web; do
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
weather_check() {   # report only
  for c in blattwerk-influxdb blattwerk-telegraf blattwerk-wetterwacht; do
    [[ $c == blattwerk-telegraf && -z $(get COMPOSE_PROFILES) ]] && { echo "weather: telegraf off (no BW_HA_URL/BW_HA_TOKEN)"; continue; }
    for _ in $(seq 1 30); do
      s=$(docker inspect -f '{{.State.Health.Status}}' "$c" 2>/dev/null || echo missing)
      [[ $s == healthy || $s == unhealthy ]] && break
      sleep 2
    done
    echo "weather: $c $s"
  done
}

if out=$(docker compose up -d --remove-orphans 2>&1) && healthy \
   && running blattwerk-web "$prefix-web:$tag" && running blattwerk-api "$prefix-api:$tag"; then
  if $conf_changed && [[ -n $(get COMPOSE_PROFILES) ]]; then   # bind-mounted config: compose does not notice changes
    docker compose restart telegraf >/dev/null 2>&1 || echo "weather: telegraf restart failed" >&2
  fi
  weather_check
  echo "current: $tag (previous web: ${prev_web:-none}, api: ${prev_api:-none})"
  exit 0
fi
echo "switch FAILED" >&2
grep -v -i -E 'token|password|secret' <<<"${out:-}" | tail -5 | sed 's/^/[compose] /' >&2 || true
for c in blattwerk-migrate blattwerk-influx-init blattwerk-api blattwerk-worker blattwerk-web; do docker logs --tail 15 "$c" 2>&1 | sed "s/^/[$c] /" >&2 || true; done
if [[ -n $prev_web && -n $prev_api ]]; then
  [[ -f docker-compose.yml.prev ]] && cp docker-compose.yml.prev docker-compose.yml
  $conf_changed && [[ -f telegraf.conf.prev ]] && cp telegraf.conf.prev telegraf.conf
  setenv BLATTWERK_WEB_IMAGE "$prev_web"; setenv BLATTWERK_API_IMAGE "$prev_api"
  docker compose up -d --remove-orphans >/dev/null 2>&1 || true
  echo "ROLLED BACK to $prev_web / $prev_api (with the previous compose file)" >&2
  echo "If the failed version had already migrated the DB: restore the backup taken before the deploy." >&2
elif [[ -n $prev_web ]]; then   # first deploy with a backend: back to the web-only prototype
  docker compose stop api worker db >/dev/null 2>&1 || true
  [[ -f docker-compose.yml.prev ]] && cp docker-compose.yml.prev docker-compose.yml
  setenv BLATTWERK_WEB_IMAGE "$prev_web"
  docker compose up -d --no-deps web >/dev/null 2>&1 || true
  echo "ROLLED BACK to $prev_web (backend stopped)" >&2
fi
exit 1
