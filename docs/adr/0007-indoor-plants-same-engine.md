# 0007 Indoor plants on the same engine
- Status: accepted
- Date: 2026-11-01

## Context
The household wanted its indoor plants in the same app: watering reminders (the garden is deliberately never
watered through the app), misting, dusting, rooms and windows instead of beds and sun.

## Decision
A Standort is either outside or a room (`zimmer`). Rooms have the directions of their windows instead of a light
level; plants inside have the distance to the window, pot and height. Watering, misting and dusting are task
categories allowed only for indoor plants, enforced where tasks are created, enabled, planned and turned into
to-dos. Intervals gain a winter rhythm and active months; "how was the soil?" adjusts the watering interval.
Indoor plants get their own care-plan prompt and are exempt from weather alerts, § 39 and the garden calendar.

## Alternatives
- A separate indoor module with its own to-dos: a second engine, checklist and push digest.
- Allowing watering everywhere: against the explicit wish for the garden.

## Consequences
- One to-do list for the household, with the Standort shown next to the plant.
- Rules that differ inside and outside need a check at every place a task can appear; tests cover each path.
