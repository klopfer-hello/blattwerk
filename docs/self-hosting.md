# Self-hosting Blattwerk

Blattwerk runs as a small Docker Compose stack on one host in your home network. Phones use it as an installed
web app, which needs **HTTPS** (service worker, web push, camera).

## What you need

- A Linux host (amd64) with Docker Engine and the Compose plugin, about 1 GB RAM free.
- HTTPS for a host name, e.g. `blattwerk.example.lan`:
  - **Traefik** already running (the default): an external Docker network, entrypoints `web` and `websecure`,
    a TLS certificate for the name, and a middleware `redirect-to-https@file`; or
  - **any other reverse proxy**: Blattwerk then listens on `127.0.0.1:8080` (see "Without Traefik").
- For the AI features: a **Claude Code OAuth token** (`claude setup-token` on a machine with Claude Code). Each care
  plan, name lookup, photo diagnosis or chat answer uses that account (budgets per call and per day are built in).
- Optional: the garden's position for weather (DWD forecast, frost alerts) and Home Assistant for own sensors.

## Install

```sh
mkdir blattwerk && cd blattwerk
base=https://raw.githubusercontent.com/klopfer-hello/blattwerk/main/deploy
for f in docker-compose.yml telegraf.conf switch.sh backup.sh standalone.override.yml .env.example; do
  curl -fsSLO "$base/$f"
done
cp .env.example .env && chmod 600 .env
$EDITOR .env          # at least CLAUDE_CODE_OAUTH_TOKEN; BW_LAT/BW_LON for weather
IMAGE_PREFIX=ghcr.io/klopfer-hello/blattwerk bash switch.sh . <version> blattwerk.example.lan traefik
```

`<version>` is a release number without the "v" (see the releases page). `switch.sh <dir> <version> <host name>
<Traefik network> [<former host name>]`:

1. generates what has to be secret and stays on the host: database passwords, the web push keys and the InfluxDB
   admin token (in `.env`, mode 600, and a Docker volume);
2. pulls the images of that version from GHCR;
3. starts the stack (the `migrate` job sets up the database first) and waits until it is healthy;
4. rolls back to the previous images if anything fails.

Then open `https://blattwerk.example.lan` on the phone, "Zum Startbildschirm hinzufügen", and set the
Bundesland and push under Mehr → Einstellungen.

## Without Traefik

```sh
docker network create blattwerk-proxy
echo 'COMPOSE_FILE=docker-compose.yml:standalone.override.yml' >> .env
IMAGE_PREFIX=ghcr.io/klopfer-hello/blattwerk bash switch.sh . <version> blattwerk.example.lan blattwerk-proxy
```

The web container then answers on `127.0.0.1:8080`; point your proxy (Caddy, nginx, …) with TLS at it and keep
the `Host` header.

## Configuration (`.env`)

| Variable | |
|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` | AI features; without it the app works and says the AI is not set up |
| `BW_LAT`, `BW_LON` | the garden in decimal degrees; only rounded to about 1 km for the forecast |
| `BW_HA_URL`, `BW_HA_TOKEN`, `BW_HA_*` | Home Assistant (non-admin user) and the sensor entity ids |
| `BW_PLAN_DAILY_LIMIT` | care plans per day (default 60) |
| written by `switch.sh` | `BW_DB_PASSWORD`, `BW_MCP_DB_PASSWORD`, `BW_VAPID_*`, `BW_INFLUX_TOKEN`, image names, `BW_HOST`, `TRAEFIK_NETWORK`, `BW_OLD_HOST`, `BW_LAT_KM`/`BW_LON_KM`, `COMPOSE_PROFILES` (weather sensors on when Home Assistant is set) |

## Updates and backups

- Update: `IMAGE_PREFIX=ghcr.io/klopfer-hello/blattwerk bash switch.sh . <new version> <host> <network>` (download
  the new `docker-compose.yml`/`telegraf.conf` first if the release notes say so). Migrations run by themselves.
- Backup: `bash backup.sh create`, `bash backup.sh list`, `bash backup.sh restore <file> --yes`. Archives stay in
  `./backups` on the host; they contain your garden, photos and chats.

## What leaves the host

- To Anthropic (Claude), for the job it is used for: plant species, Sorten and nicknames, Standort names, the
  Bundesland and season, and for the chat what its tools look up (care plans, to-dos, weather, alerts, history,
  diagnoses, earlier messages of that chat) plus the question and its photos (re-encoded, no EXIF/GPS). Never
  your notes, place, postcode or coordinates.
- To Open-Meteo (only with Home Assistant set up, for the backup forecast and growing degree days): the position
  rounded to about 1 km. DWD only serves files; the nearest station is chosen on the host.
- To the push service of each phone (Google, Apple, Mozilla): the encrypted notification.
- Nothing else: no telemetry, no tracking, no external fonts or scripts.
