# Season and weather

## The phenological season

Gardeners have always timed work by nature: "cut the roses when the forsythia blooms". The German weather service
(DWD) publishes when indicator plants reach their phases, reported by volunteers across the country. Blattwerk
uses ten phases:

| Season | Indicator |
|---|---|
| Vorfrühling | hazel blossom |
| Erstfrühling | forsythia blossom |
| Vollfrühling | apple blossom |
| Frühsommer | elder blossom |
| Hochsommer | lime blossom |
| Spätsommer | early apple ripening |
| Frühherbst | elderberries ripe |
| Vollherbst | acorns ripe |
| Spätherbst | leaf colouring |
| Winter | leaf fall |

- The **current season** comes from the reports of the household's region (enough reports to count), or the
  user's own observation, which always wins.
- **Long-term normals** say how early or late this year is ("10 Tage früher als im Mittel").
- A task can be tied to a phase with an offset and a window ("erstfruehling, +0 days, 14 days"); its month window
  stays as the fallback until the phase is reported. When the phase arrives later, open to-dos follow it.

## Forecast and measurements

- **DWD MOSMIX**: hourly station forecast for the nearest station to the garden's rounded position.
- **Open-Meteo** as a second source.
- **Home Assistant** (optional): Telegraf polls the household's own sensors (air, ground, rain, wind, soil
  moisture, greenhouse) into InfluxDB.

## Alert rules

`wetterwacht` evaluates the next 48 hours, at most one event per kind and day:

| Event | Rule |
|---|---|
| Strenger Frost | air ≤ −10 °C, any time |
| Frost | air ≤ −2 °C (and the season's first frost from November) |
| Spätfrost | from apple blossom in the region (15 April without data) to end of May: air ≤ 0 °C or ground ≤ −1 °C |
| Hitze | air ≥ 32 °C |
| Sturm | gusts ≥ 75 km/h |

- **Hysteresis**: an alert ends only when the forecast is clearly better (e.g. heat below 30 °C, storm below
  65 km/h), so values near a threshold do not flap.
- **Per plant**: each plant's hardiness (from the catalogue or the care plan) decides who is at risk; plants in
  pots freeze about 10 °C earlier than in the ground; unknown hardiness counts as at risk. Blossom and young shoots
  are at risk in late frost whatever their winter hardiness.
- **Actions, not just warnings**: the alert creates urgent to-dos ("Kübel mit Vlies umwickeln", "Knollen
  ausgraben") and sends a push immediately. Never watering in the garden; never anything for indoor plants.

## Why like this

Fixed calendar dates are wrong by weeks in early or late years and between regions. Phenology is how gardeners
already think; the DWD makes it measurable. Separating the measurement agent (Telegraf), the store (InfluxDB) and
the rules (pure functions in `alerts.py`) keeps each part simple and testable – alert rules are tested with
synthetic forecasts, not live weather.
