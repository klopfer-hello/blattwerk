# Tech stack

Every part, what it does in Blattwerk, and why it was chosen. The bigger decisions have an
[ADR](adr/index.md).

## Backend

| Part | Role | Why |
|---|---|---|
| **Python 3.13** | API, worker, alerts, MCP server | One language for everything server-side; great libraries for data, HTTP and scheduling ([ADR 0001](adr/0001-python-fastapi-postgresql.md)). |
| **FastAPI** + Pydantic v2 | REST API, validation | Every input is a strict model with size limits; OpenAPI for free; async without ceremony. |
| **SQLAlchemy 2 Core** (async) + **psycopg 3** | SQL | Explicit SQL for the parts where locking matters (`FOR UPDATE`, `SKIP LOCKED`); no hidden ORM queries. |
| **Alembic** | Migrations | Every schema change is a reviewed, numbered migration; the `migrate` job runs them before the API starts. |
| **PostgreSQL 17** | The data | Constraints guard the rules (cut types, amounts, idempotent to-dos); JSONB for documents like care plans and settings; roles for least privilege (the chat's own role: reading plus proposals). |
| **uv** | Dependencies | Locked, hashed, fast; `exclude-newer` keeps dependencies at least two weeks old (supply-chain hygiene), with documented exceptions for urgent security fixes. |
| **Pillow** | Photos | Verifies uploads, refuses decompression bombs, re-encodes without metadata. |
| **mcp** (Python SDK) | Chat tools | A small stdio MCP server gives Claude exactly the tools it may use ([ADR 0005](adr/0005-chat-through-mcp.md)). |

## AI

| Part | Role | Why |
|---|---|---|
| **Claude Code CLI** (pinned, checksum-verified, installed at runtime) | Care plans, name lookups, photo ID, chat | Uses the household's Claude subscription; `--json-schema` for structured output; no built-in tools; budgets and timeouts per call ([ADR 0002](adr/0002-claude-code-cli-at-runtime.md)). |
| Schema + sanitising + legal rules | Guardrails | The model proposes, the code decides ([ADR 0003](adr/0003-ai-proposes-rules-in-code.md)). |
| `/plan-eval` | Quality checks | Fixed garden and indoor cases with deterministic checks against the real model. |

## Weather and season

| Part | Role | Why |
|---|---|---|
| **DWD MOSMIX** | Forecast | The German weather service's station forecasts: free, local, hourly; the station is chosen on the host. |
| **DWD phenology** | The season | Reports of indicator plants (hazel, forsythia, apple, elder …) per region decide the current season ([ADR 0004](adr/0004-season-and-weather.md)). |
| **Telegraf** | Sensor agent | The classic telemetry agent pattern: polls Home Assistant and Open-Meteo, writes line protocol (runs when Home Assistant is set up). |
| **InfluxDB 3 Core** | Measurements | A time-series store for history and charts, separate from the app's data. |
| **wetterwacht** | Alerts | Its own process: rules are pure functions (forecast in, events and actions out), IO around them. |

## Frontend

| Part | Role | Why |
|---|---|---|
| **React + TypeScript + Vite** | The app | Typed client for the API, fast builds, small bundle. |
| **PWA** (manifest, service worker) | Install, push | Home-screen app and web push on Android and iPhone without an app store. |
| **Web Push (VAPID)** | Notifications | Keys generated on the host; the push services only see encrypted payloads. |
| **nginx-unprivileged** | Serving | Static files, `/api` proxy, strict CSP and security headers, non-root. |

## Operations and quality

| Part | Role | Why |
|---|---|---|
| **Docker Compose** | Runtime | One file describes networks, limits, health and secrets; easy to self-host. |
| **Traefik** | TLS and routing | Fits an existing home-lab reverse proxy; an override runs without it. |
| **pytest** against real PostgreSQL | Tests | Constraints and locking are tested where they live, not mocked. |
| **ruff, mypy strict, tsc** | Static checks | Catch mistakes before tests run. |
| **Playwright** UI smoke | Every screen | Phone and desktop sizes, tap-target sizes, console errors, an invented demo garden. |
| **GitHub Actions** | CI/CD | Tests, `pip-audit`, `npm audit`, Trivy, gitleaks, privacy scan, CodeQL; releases push exactly the gated images. |
| **git hooks** | Before anything leaves the PC | Personal data and secrets are blocked at commit and push. |
