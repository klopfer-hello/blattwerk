# Development

Everything runs in Docker; nothing besides Docker, git and bash is needed on the PC.

```sh
bash scripts/setup-dev.sh        # once: git hooks (privacy scan + gitleaks on commit and push)
bash scripts/test.sh             # api: ruff, ruff format, mypy strict, pytest (real PostgreSQL); web: tsc + build
bash scripts/test.sh api -k soil # only pytest, filtered
bash scripts/ui-smoke.sh         # Playwright: every screen at phone and desktop sizes, invented demo garden
bash scripts/plan-eval.sh        # care-plan and name quality against the real Claude (costs a few cents)
```

## Repository layout

| Path | |
|---|---|
| `api/src/blattwerk/` | FastAPI app (`routes/`), worker, alerts (`wetterwacht`), AI (`plan.py`, `names.py`, `chat.py`, `claude_cli.py`), MCP server, legal rules, schedule, schema |
| `api/src/blattwerk/migrations/` | Alembic migrations |
| `api/tests/` | pytest suite against a real PostgreSQL |
| `web/src/` | React app (`screens/`, `components/`), service worker in `web/public/` |
| `deploy/` | Compose file, Telegraf config, `switch.sh`, backups, `.env.example` |
| `scripts/` | tests, smoke, deploy, scans, hooks |
| `docs/` | this site (MkDocs Material), ADRs |

## Working rules

- **Tests first** for new behaviour; every review finding that was a real bug becomes a test.
- **Migrations** for every schema change; the database enforces the important rules.
- **No personal data in git** – real places, hosts, names and tokens live only in the host's `.env`. Fixtures and
  screenshots use invented data. The hooks block commits that look private.
- **Prompts** have a version; a prompt change runs `/plan-eval` before release.
- **Commits** follow conventional commits (`feat:`, `fix:`, `docs:` …); the release notes are built from them.

## CI and releases

- **CI** on every push and pull request: tests, dependency audit (`pip-audit`, `npm audit`), images built and
  scanned with Trivy (HIGH/CRITICAL with a fix fail the build), no Claude CLI in the images, gitleaks and the
  privacy scan over the whole history, CodeQL for Python and TypeScript, and this site built with `--strict`.
- **Release**: a tag `vX.Y.Z` (matching `VERSION`) runs the same gates and pushes exactly the tested images to
  `ghcr.io/klopfer-hello/blattwerk-api` and `-web`, then creates the GitHub release with notes from the commits.
- Third-party actions are pinned to commit SHAs; Dependabot proposes updates with a 14-day cooldown.
