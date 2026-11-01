# Architecture

Blattwerk is one Docker Compose stack on one host in the home network. The phones talk to exactly one container;
everything else is internal.

## System context

```mermaid
flowchart LR
  phone["Phones (PWA)"] -- HTTPS --> bw["Blattwerk stack"]
  bw -- "care plans, names, chat, photos" --> claude["Claude (Anthropic)"]
  bw -- "forecast, phenology" --> dwd["DWD open data"]
  bw -- "rounded position: backup forecast, degree days" --> om["Open-Meteo"]
  bw -- "encrypted push" --> push["Push services (Google, Apple, Mozilla)"]
  ha["Home Assistant (optional)"] -- sensors --> bw
```

## Containers and networks

```mermaid
flowchart TB
  subgraph routing["routing network (Traefik)"]
    traefik["Traefik (TLS)"]
    web["web: nginx<br/>static app + /api proxy<br/>(also on backend)"]
  end
  subgraph backend["backend network (internal, no route out)"]
    api["api: FastAPI"]
    db[("db: PostgreSQL 17")]
    migrate["migrate: Alembic (one-shot)"]
    influx[("influxdb: InfluxDB 3 Core")]
    ww["wetterwacht: alerts"]
  end
  subgraph egress["egress network (internet) – also on backend"]
    worker["worker: jobs, Claude CLI, MCP"]
    telegraf["telegraf: sensors (only with Home Assistant)"]
  end
  traefik --> web --> api --> db
  migrate --> db
  worker --> db
  worker --> influx
  ww --> influx
  ww --> db
  telegraf --> influx
```

- **Only `web` is reachable** (through Traefik). It serves the built React app and proxies `/api` to the API by
  container name, so nginx starts even while the API restarts.
- **`backend` is an internal network**: PostgreSQL, InfluxDB, the API and the migration job have no route to the
  internet and no published ports.
- **`worker` and `telegraf`** sit on `backend` and also join `egress`: the worker talks to Claude, DWD, Open-Meteo
  (growing degree days) and the push services; Telegraf to Home Assistant and Open-Meteo. `web` joins `backend` to
  reach the API. The API itself cannot reach the internet at all.
- **`migrate`** runs Alembic once before the API starts; the API only starts after it succeeded.
- All containers drop all capabilities (`cap_drop: [ALL]`) and run with `no-new-privileges`, read-only root
  filesystems where possible, and healthchecks. The app containers run as non-root users; the database gets back
  the five capabilities its entrypoint needs and then runs as the `postgres` user.

## Request flow: from tap to database

```mermaid
sequenceDiagram
  participant P as Phone
  participant W as web (nginx)
  participant A as api (FastAPI)
  participant D as PostgreSQL
  P->>W: POST /api/todos/{id}/done (JSON, same origin)
  W->>A: proxy (Host kept)
  A->>A: WriteGuard: JSON only, ≤ 64 KB, same origin
  A->>D: one transaction: close the to-do, plan the next one
  D-->>A: ok
  A-->>P: the updated to-do
```

## Background work: the worker

The API never waits for the AI. It stores a **job** (care plan, name lookup, chat answer) and returns; the worker
claims jobs with `SELECT … FOR UPDATE SKIP LOCKED`, runs the Claude CLI, and writes the result in one transaction.
The phone polls (plans) or streams server-sent events (chat).

```mermaid
sequenceDiagram
  participant P as Phone
  participant A as api
  participant D as PostgreSQL
  participant K as worker
  participant C as Claude CLI
  P->>A: add a plant
  A->>D: insert plant + queue plan job
  A-->>P: 201 (plan "in progress")
  K->>D: claim job (SKIP LOCKED)
  K->>C: prompt + JSON schema (no tools, budget, timeout)
  C-->>K: structured plan
  K->>K: validate, sanitise, legal rules
  K->>D: plan + tasks + first to-dos (one transaction)
  P->>A: poll plan state
  A-->>P: done
```

## Data model (core)

```mermaid
erDiagram
  STANDORTE ||--o{ PLANTS : "has"
  SPECIES ||--o{ CULTIVARS : "has"
  SPECIES ||--o{ PLANTS : "is"
  CULTIVARS |o--o{ PLANTS : "is"
  PLANTS ||--o{ CARE_PLANS : "gets"
  PLANTS |o--o{ TASKS : "for"
  CARE_PLANS |o--o{ TASKS : "made"
  TASKS ||--o{ TODOS : "occurs as"
  PLANTS ||--o{ DIAGNOSES : "has"
  CHATS ||--o{ CHAT_MESSAGES : "has"
  CHAT_MESSAGES ||--o{ CHAT_ACTIONS : "proposes"
  CHAT_MESSAGES |o--o{ PHOTOS : "shows"
```

- **tasks** describe *what and when* (once, yearly month window, interval, optional season trigger);
  **todos** are the concrete occurrences on the checklist. See [the to-do engine](how-it-works/todo-engine.md).
- Care plans keep their history: a new plan *retires* the old tasks; done to-dos stay.
- Integrity lives in the database: foreign keys, CHECK constraints (e.g. `cut_type` only for pruning, an amount
  only for watering), unique keys that make job and to-do creation idempotent. Rules that depend on other rows
  (watering only for indoor plants) are enforced in the API where tasks and to-dos are made.

## Deployment

```mermaid
flowchart LR
  dev["Developer PC<br/>tests, build"] -- "docker save | ssh docker load" --> host["Docker host"]
  ci["GitHub Actions<br/>tests, Trivy, release"] -- "push images" --> ghcr["GHCR"]
  ghcr -- "pull (self-hosters)" --> host
  host -- "switch.sh: secrets, compose up, health, rollback" --> stack["Blattwerk stack"]
```

`deploy/switch.sh` does the same on every host: generate secrets that never leave it, start the stack, wait for
health, roll back to the previous images on failure. See [self-hosting](self-hosting.md).
