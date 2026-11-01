# 0001 Python backend with FastAPI and PostgreSQL
- Status: accepted
- Date: 2026-10-31

## Context
A household app with a REST API, background jobs (AI runs, weather, push) and documents (care plans, settings)
next to relational data (plant → Sorte → species, tasks → to-dos). One maintainer, a small LAN host.

## Decision
All backend code in Python 3.13: FastAPI for the API, one worker process for jobs, SQLAlchemy 2 Core (async,
psycopg 3) with Alembic migrations, PostgreSQL 17 with JSONB for the document-shaped parts. Integrity lives in the
database: foreign keys, CHECK constraints, unique keys, transactions. ruff and mypy strict; pytest against a real
PostgreSQL.

## Alternatives
- FerretDB/MongoDB-style documents: tried first; integrity checks had to be written by hand.
- Rust for the backend or one service: two languages double tooling and CI for little gain at this size.
- An ORM with models: Core keeps the SQL visible, which matters for the to-do engine's locking.

## Consequences
- One language, one test setup; constraints catch bugs the code misses.
- Schema changes always need a migration (CI and the deploy run them).
