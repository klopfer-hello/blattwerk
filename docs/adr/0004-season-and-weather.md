# 0004 The real season: DWD phenology, MOSMIX and InfluxDB
- Status: accepted
- Date: 2026-10-31

## Context
Garden work depends on the season as it is, not on the calendar: roses are pruned when the forsythia blooms, frost
in May hurts blossom, tubs need protection before the first frost. The household has its own weather sensors in
Home Assistant.

## Decision
- Season: DWD phenology reports of the region (Bundesland) and the user's own observations decide the current
  phase; tasks can be tied to a phase with an offset, the month window stays as fallback.
- Forecast: DWD MOSMIX for the nearest station (rounded position), Open-Meteo as backup.
- Measurements: Telegraf polls Home Assistant and Open-Meteo into InfluxDB 3 Core (the classic telemetry agent
  pattern); the `wetterwacht` service evaluates frost, late frost, heat and storm with per-plant hardiness and sends
  push alerts with concrete actions.

## Alternatives
- Only a month window per task: wrong by weeks in early or late years.
- Reading Home Assistant directly from the app: couples the app to HA and gives no history.

## Consequences
- Weather is optional: without position or sensors the app runs with month windows.
- InfluxDB Core refuses wide scans; queries stay narrow in time.
