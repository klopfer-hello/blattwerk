# 0003 The AI only proposes; rules live in code
- Status: accepted
- Date: 2026-10-31

## Context
AI answers vary and can be wrong: a strong cut in May breaks § 39 BNatSchG (bird protection), a watering task in
the garden was explicitly not wanted, a chat answer could claim it changed data. Text from the user (plant names,
questions, photos) reaches the model and could try to steer it.

## Decision
AI output is data, never instructions or code. Care plans are validated against a schema and sanitised (unknown
fields dropped, numbers clamped, watering removed for garden plants, cuts recognised by their wording). The legal
rules (§ 39 window per Bundesland, tree protection, fruit-tree exemption) are code in `legal.py` and move or block
to-dos whatever the plan said. The chat can only read through its tools and create *proposals*; a task, note or
diagnosis becomes real only with the user's "Ja", and is checked again then.

## Alternatives
- Rules in the prompt only: the model does not reliably follow them.
- Letting the chat write directly: one wrong or manipulated answer would change the garden.

## Consequences
- /plan-eval checks plan quality against fixed cases; the code still guards what the eval cannot.
- Some good suggestions are dropped (e.g. a cut task in the wrong category); the user can add them by hand.
