# Features

Blattwerk is a mobile-first web app (installable as a PWA). The screens are German; the names in brackets are
what you see in the app.

## Plants and places (Pflanzen, Standorte)

- **Standorte** are either outside (Beet, Gemüsebeet, Rasen, Hecke, Kübelplatz, Gewächshaus) with a light level,
  or a room inside (Zimmer) with the directions its windows face (Nord/Ost/Süd/West, several allowed).
- **Plants** are added by name: German or Latin, with cultivar and form ("Säulenapfel Sonate", "Prunus AV.
  Celeste Säule"). An offline resolver with a curated catalogue of common garden and indoor plants answers
  instantly; unknown names go to the AI, which returns candidates to pick from.
- **Per Foto bestimmen**: identify a plant from a photo.
- Indoor plants also store the distance to the window, pot size and material, and the plant's height.

## Care plans (Pflegeplan)

Created automatically when a plant is added (and again when its species, Sorte, room, window, pot or height
change). A plan holds:

- tasks with timing: pruning (gentle or strong), fertilising with product type, NPK, dose and brand examples,
  harvest windows for the cultivar, winter protection, monitoring;
- typical pests and diseases with prevention and treatment (mechanical/biological first, then only products
  approved for home gardens);
- indoors: a watering rhythm for summer and for winter, the amount per watering, misting, dusting, repotting.

Every task can be edited, switched off for this plant (it stays off in future plans), or done today.

## To-dos (Heute, Kalender)

- **Heute** – this month's checklist for the household: overdue, urgent, then by category, each with plant and
  Standort. Tick off, skip, postpone, add a note; undo.
- **Kalender** – the garden year at a glance, including the bird-protection period.
- **Heute gemacht** on a plant – done now, whenever it was due; an interval starts again from today.
- **After watering**: "Wie war die Erde?" (still moist / just right / bone dry) lengthens or shortens the rhythm;
  **"Erde noch zu feucht – später"** skips it and checks again in a few days.
- **Push digest** at a time you choose, plus immediate push for urgent weather.

## Season and weather (Wetter, Jahreszeit)

- The current phenological season of your region (e.g. *Erstfrühling – forsythia blossom*), how early or late
  it is against the long-term mean, your own observations.
- Forecast and own sensors (via Home Assistant): air, ground, rain, wind, soil moisture, greenhouse.
- **Alerts** for frost, strong frost, late frost on blossom and young shoots, heat and storm, each with concrete
  to-dos for the plants at risk (e.g. "Kübel mit Vlies umwickeln", "Knollen ausgraben").

## Ask (Fragen) and the plant doctor

- A chat that looks things up in *your* garden: plants, plans, to-dos, weather, season, history.
- Up to three photos per question. Claude describes what it sees, asks back when unsure, and proposes a diagnosis
  with follow-up to-dos; saved diagnoses appear in the plant's history with their photos.
- Everything the chat proposes is a card with **Ja / Nein**.

## History (Verlauf)

Per plant: done and skipped to-dos with notes, diagnoses with photos – also the context the AI sees when you ask
about that plant later.
