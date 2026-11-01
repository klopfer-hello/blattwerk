# Indoor plants

Indoor plants use the same engine as the garden ([ADR 0007](../adr/0007-indoor-plants-same-engine.md)) with a few
different rules.

## Rooms, windows, distance

- A Standort is **outside** (with a light level) or a **room** (with the directions its windows face – several for
  a corner room; no light level, because inside the window and the distance to it decide).
- A plant in a room stores the **distance to the window** (window sill, up to 1 m, 1–2 m, middle of the room),
  which window is nearest when there are several, the **pot** (diameter, material) and its **height**.
- Changing any of these makes a new care plan: they decide how often and how much to water.

## Watering only inside

Watering, misting and dusting are task categories that exist **only for indoor plants**. This is checked wherever a
task can appear: creating and editing a task, switching it back on, applying an AI plan (also one that finished
after the plant was moved), the chat's proposals – and centrally where to-dos are made and listed. Moving a plant
outside pauses these tasks.

## The indoor care plan

The indoor prompt asks for:

- **Watering**: interval for spring to autumn and for winter (usually longer), and the amount per watering from pot
  size and plant height; how to tell it is time (finger test, pot weight), no waterlogging.
- **Misting** where the plant likes humidity (ferns, calathea, tropical plants; more often with heating air) –
  never for succulents, cacti or hairy leaves.
- **Dusting** for smooth leaves; checking the undersides for pests.
- **Fertilising** only in the growing season (active months), turning the pot, repotting every few years.
- Typical indoor pests (spider mites, fungus gnats, mealybugs, thrips).

Garden rules do not apply inside: no weather alerts, no § 39, no phenology, not in the garden calendar.

## Learning the rhythm

The plan's interval is a starting point. The [soil feedback](todo-engine.md#the-soil-feedback-loop) after each
watering – and "still moist, later" – moves it towards what this plant, in this room, actually needs. No humidity
sensor needed: a plant that needs more water simply shows it.
