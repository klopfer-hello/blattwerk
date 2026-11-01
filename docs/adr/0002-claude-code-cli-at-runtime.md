# 0002 Claude Code CLI, installed at runtime
- Status: accepted
- Date: 2026-10-31

## Context
Care plans, name lookups, the plant doctor and the chat need a capable model. The household already has a Claude
subscription; per-token API billing was not wanted. The Claude Code CLI is proprietary and may not be redistributed.

## Decision
The worker runs `claude -p` (pinned version) with a Claude Code OAuth token from the host's `.env`. The CLI is
never part of an image: the worker downloads the pinned version into its `/claude` volume at start and verifies the
SHA-256 against a checksum pinned in the compose file. Every call runs without built-in tools, without session
files, with a budget and a timeout; structured answers use `--json-schema` and are validated again in Python.

## Alternatives
- The Anthropic API with an API key: separate billing per token.
- Bundling the CLI in the image: not allowed by its licence; also hides version changes.

## Consequences
- Without the token the app works and says the AI is not set up.
- A CLI update is a one-line change (version + checksum) and is tested with /plan-eval.
- Costs show up on the subscription; daily limits per feature keep them bounded.
