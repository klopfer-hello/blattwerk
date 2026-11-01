# Architecture decisions

Short records of the decisions that shaped Blattwerk: the context, the decision, the alternatives that were
considered, and the consequences. A decision that changes gets a new record; old ones are never rewritten.

| ADR | Decision |
|---|---|
| [0001](0001-python-fastapi-postgresql.md) | Python backend with FastAPI and PostgreSQL |
| [0002](0002-claude-code-cli-at-runtime.md) | Claude Code CLI, installed at runtime |
| [0003](0003-ai-proposes-rules-in-code.md) | The AI only proposes; rules live in code |
| [0004](0004-season-and-weather.md) | The real season: DWD phenology, MOSMIX and InfluxDB |
| [0005](0005-chat-through-mcp.md) | The garden chat reads through an MCP server with its own database role |
| [0006](0006-photos-without-metadata.md) | Photos are re-encoded without metadata and stay on the host |
| [0007](0007-indoor-plants-same-engine.md) | Indoor plants on the same engine |
