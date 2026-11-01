# 0005 The garden chat reads through an MCP server with its own database role
- Status: accepted
- Date: 2026-11-01

## Context
The chat ("Fragen") should answer about *this* household's plants, to-dos, weather and season, and propose tasks,
notes and diagnoses. Giving the model the whole database in the prompt is costly and leaks more than needed.

## Decision
The worker starts the CLI with exactly one MCP server (`blattwerk`, stdio) and no other tools. Its tools read an
overview, one plant, the month's to-dos, weather, season and a plant's history, and can create proposals. The MCP
process connects as a PostgreSQL role `blattwerk_mcp` with SELECT on the tables it needs and INSERT only on
`chat_actions`; its password is generated on the host. Answers stream to the phone through server-sent events.

## Alternatives
- Prompt stuffing: tokens for every question, and every detail in every prompt.
- Tools with the app's own database user: one bug or injection away from writing anything.

## Consequences
- The database enforces what the chat can do, independent of the prompt.
- New tools need a grant in a migration and a test that lists the tool set.
