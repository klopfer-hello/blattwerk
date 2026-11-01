"""What the garden chat can see and propose (M8, F-AI-4). Plain async functions on a DB
connection, so they are tested directly; mcp_blattwerk.py exposes them as MCP tools.

Read: the garden (Standorte, plants with Sorte/form/age/container), one plant with its
care plan and tasks, this month's to-dos, the weather, the season, a plant's history.
Never: Ort, PLZ, coordinates, notes on plants, Standorte or to-dos (security rules).
Names the user typed (Standort names, plant nicknames) do go to the model.
Write: none. "Vorschlagen" stores a proposal; only the user's "Ja" in the app carries
it out (routes/chat.py). Answers are German keys and short values: they go into the
model's context."""

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncConnection

from blattwerk.models import GardenSettings, TaskIn, known_fields
from blattwerk.plan import CUTTING, WATERING, dry
from blattwerk.routes.todos import TZ
from blattwerk.schema import (
    INDOOR,
    INDOOR_CATEGORIES,
    care_plans,
    chat_actions,
    cultivars,
    diagnoses,
    plants,
    settings,
    species,
    standorte,
    tasks,
    todos,
)
from blattwerk.season_dates import season_core

MAX_NOTE = 500
MAX_FINDING = 120
CONFIDENCE = ("ziemlich sicher", "sicher")  # "unsicher" is no diagnosis: ask for another photo
MAX_PROPOSALS = 5  # per answer: a confused or manipulated answer cannot flood the screen


def _plant_name(r: Any) -> str:
    base = r.german[0] if r.german else r.latin
    return r.nickname or (f"{base} '{r.cultivar}'" if r.cultivar else base)


_plant_query = (
    select(
        plants.c.id, plants.c.nickname, plants.c.form, plants.c.planted_year, plants.c.in_container,
        plants.c.rootstock, plants.c.standort_id, species.c.german, species.c.latin, species.c.growth,
        cultivars.c.name.label("cultivar"),
    )
    .join(species, species.c.id == plants.c.species_id)
    .outerjoin(cultivars, cultivars.c.id == plants.c.cultivar_id)
    .where(plants.c.archived_at.is_(None))
)  # fmt: skip


def _plant(r: Any) -> dict[str, Any]:
    return {
        "id": r.id, "name": _plant_name(r), "art": r.german[0] if r.german else r.latin, "latein": r.latin,
        "sorte": r.cultivar, "wuchsform": r.form, "pflanzjahr": r.planted_year, "im_kuebel": r.in_container,
    }  # fmt: skip


async def _season(c: AsyncConnection, today: date) -> dict[str, Any] | None:
    cur = (await season_core(c, today))["current"]
    return None if cur is None else {"name": cur["name"], "seit": cur["since"], "tage_gegen_mittel": cur["delay_days"]}


async def ueberblick(c: AsyncConnection, today: date) -> dict[str, Any]:
    data = (await c.execute(select(settings.c.data).where(settings.c.id == 1))).scalar()
    g = GardenSettings.model_validate(known_fields(GardenSettings, data or {}))
    rows = (await c.execute(_plant_query.order_by(species.c.german))).all()
    sites = (await c.execute(select(standorte.c.id, standorte.c.name, standorte.c.light, standorte.c.type)
                             .order_by(standorte.c.name))).all()  # fmt: skip
    return {
        "heute": today.isoformat(),
        "bundesland": g.location.bundesland,
        "jahreszeit": await _season(c, today),
        "standorte": [
            {"name": s.name, "licht": s.light, "typ": s.type, "drinnen": s.type == INDOOR,
             "pflanzen": [_plant(r) for r in rows if r.standort_id == s.id]}
            for s in sites
        ],
    }  # fmt: skip


async def pflanze(c: AsyncConnection, pflanze_id: str, today: date) -> dict[str, Any]:
    r = (await c.execute(_plant_query.where(plants.c.id == pflanze_id))).first()
    if r is None:
        return {"fehler": "Pflanze nicht gefunden"}
    plan = (
        await c.execute(
            select(care_plans).where(care_plans.c.plant_id == pflanze_id).order_by(care_plans.c.created_at.desc())
        )
    ).first()
    task_rows = await c.execute(
        select(tasks.c.title, tasks.c.category, tasks.c.recurrence, tasks.c.month_from, tasks.c.month_to,
               tasks.c.pheno_phase, tasks.c.enabled)
        .where(tasks.c.plant_id == pflanze_id, ~tasks.c.retired)
        .order_by(tasks.c.title)
    )  # fmt: skip
    return {
        **_plant(r),
        "unterlage": r.rootstock,
        "pflegeplan": None if plan is None else {
            "zusammenfassung": plan.summary, "sicherheit": plan.confidence, "hinweise": plan.caveats,
            "schaedlinge": plan.pests,
        },
        "aufgaben": [
            {"titel": t.title, "kategorie": t.category, "wiederholung": t.recurrence,
             "monate": [t.month_from, t.month_to] if t.month_from else None, "zur_phase": t.pheno_phase,
             "aktiv": t.enabled}
            for t in task_rows
        ],
    }  # fmt: skip


async def aufgaben(c: AsyncConnection, today: date) -> dict[str, Any]:
    from blattwerk.routes.todos import month_list  # the same list as Heute, read only

    h = await month_list(c, today)  # the app creates due occurrences itself

    def short(t: dict[str, Any]) -> dict[str, Any]:
        return {"titel": t["task"]["title"], "pflanze": (t.get("plant") or {}).get("title"),
                "von": str(t["due_from"]), "bis": str(t["due_to"]), "dringend": t["task"]["urgent"],
                "ueberfaellig": t.get("overdue", False), "status": t["status"]}  # fmt: skip

    return {"monat": f"{today.year}-{today.month:02d}", "offen": [short(t) for t in h["open"]],
            "erledigt": [short(t) for t in h["done"]]}  # fmt: skip


async def jahreszeit(c: AsyncConnection, today: date) -> dict[str, Any]:
    s = await season_core(c, today)
    return {
        "aktuell": await _season(c, today),
        "phasen": [{"name": p["name"], "zeiger": p["indicator"], "datum": p["date"], "erwartet": p["expected"],
                    "mittel": p["normal"]} for p in s["phases"]],
    }  # fmt: skip


async def verlauf(c: AsyncConnection, pflanze_id: str) -> dict[str, Any]:
    rows = await c.execute(
        select(tasks.c.title, todos.c.status, todos.c.done_at)
        .join(tasks, tasks.c.id == todos.c.task_id)
        .where(tasks.c.plant_id == pflanze_id, todos.c.status != "open")
        .order_by(todos.c.done_at.desc())
        .limit(30)
    )
    found = await c.execute(
        select(diagnoses).where(diagnoses.c.plant_id == pflanze_id).order_by(diagnoses.c.created_at.desc()).limit(10)
    )
    return {
        "eintraege": [
            {"titel": r.title, "status": r.status, "am": r.done_at.date().isoformat() if r.done_at else None,
             }
            for r in rows
        ],
        "diagnosen": [
            {"befund": d.title, "sicherheit": d.confidence, "ursache": d.cause, "am": d.created_at.date().isoformat()}
            for d in found
        ],
    }  # fmt: skip


async def _propose(c: AsyncConnection, message_id: str, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    query = select(chat_actions.c.payload).where(chat_actions.c.message_id == message_id)
    earlier = list((await c.execute(query)).scalars())
    if payload in earlier:
        return {"vorgeschlagen": True, "hinweis": "Diesen Vorschlag gibt es schon."}
    if len(earlier) >= MAX_PROPOSALS:
        return {"fehler": f"Höchstens {MAX_PROPOSALS} Vorschläge pro Antwort."}
    aid = uuid.uuid4().hex
    await c.execute(chat_actions.insert().values(id=aid, message_id=message_id, kind=kind, payload=payload,
                                                 status="proposed", created_at=datetime.now(UTC)))  # fmt: skip
    return {"vorgeschlagen": True, "hinweis": "Der Nutzer bestätigt oder verwirft den Vorschlag in der App."}


def check_task(payload: dict[str, Any], today: date, indoor: bool = False) -> TaskIn | str:
    """The rules for a chat task, used when proposing and again when confirming: watering only
    for an indoor plant (M11),
    a date from today to 13 months ahead, a cut always goes through § 39 (strong unless the
    proposal says gentle), and whatever TaskIn requires."""
    title = str(payload.get("title", ""))
    if WATERING.search(title) or payload.get("category") == "giessen":
        if not indoor:
            return "Gießaufgaben gibt es nur für Zimmerpflanzen; der Garten wird nicht über die App gegossen."
        if payload.get("category") in (None, "sonstiges"):
            payload = payload | {"category": "giessen"}
    if payload.get("category") in INDOOR_CATEGORIES and not indoor:
        return "Besprühen und Entstauben gibt es nur für Zimmerpflanzen."
    payload = payload | {"instructions": dry(str(payload.get("instructions", "")))}
    if payload.get("category") != "ernte" and CUTTING.search(title):
        payload = payload | {"category": "schnitt"}
    if payload.get("category") == "schnitt":
        payload = payload | {"cut_type": "pflege" if payload.get("cut_type") == "pflege" else "stark"}
    else:
        payload = payload | {"cut_type": None}
    try:
        task = TaskIn.model_validate(payload | {"recurrence": "once"})
    except ValidationError:
        return "Ungültig: Titel (1-120 Zeichen), Datum JJJJ-MM-TT, bekannte Kategorie."
    if task.due_date is None or not (today <= task.due_date <= today + timedelta(days=400)):
        return "Datum muss heute oder in den nächsten 13 Monaten liegen."
    return task


async def indoor_plant(c: AsyncConnection, plant_id: str | None) -> bool:
    if not plant_id:
        return False
    found = await c.execute(select(standorte.c.type).select_from(plants.join(standorte)).where(plants.c.id == plant_id))
    return found.scalar() == INDOOR


async def active_plant(c: AsyncConnection, plant_id: str) -> bool:
    found = await c.execute(select(plants.c.id).where(plants.c.id == plant_id, plants.c.archived_at.is_(None)))
    return found.first() is not None


async def aufgabe_vorschlagen(
    c: AsyncConnection, message_id: str, titel: str, datum: str, pflanze_id: str | None, anleitung: str,
    kategorie: str = "sonstiges", schnitt_art: str = "stark", today: date | None = None,
) -> dict[str, Any]:  # fmt: skip
    today = today or datetime.now(TZ).date()
    try:
        day = date.fromisoformat(datum)
    except ValueError:
        return {"fehler": "Datum als JJJJ-MM-TT."}
    payload = {"title": titel, "category": kategorie, "due_date": day, "instructions": anleitung[:4000],
               "plant_id": pflanze_id or None, "cut_type": schnitt_art}  # fmt: skip
    task = check_task(payload, today, await indoor_plant(c, pflanze_id or None))
    if isinstance(task, str):
        return {"fehler": task}
    if task.plant_id and not await active_plant(c, task.plant_id):
        return {"fehler": "Pflanze nicht gefunden"}
    return await _propose(c, message_id, "aufgabe", task.model_dump(mode="json"))


async def notiz_vorschlagen(c: AsyncConnection, message_id: str, pflanze_id: str, text: str) -> dict[str, Any]:
    text = text.strip()
    if not text or len(text) > MAX_NOTE:
        return {"fehler": f"Notiz mit 1-{MAX_NOTE} Zeichen."}
    if not await active_plant(c, pflanze_id):
        return {"fehler": "Pflanze nicht gefunden"}
    return await _propose(c, message_id, "notiz", {"plant_id": pflanze_id, "text": text})


async def diagnose_vorschlagen(
    c: AsyncConnection, message_id: str, pflanze_id: str, befund: str, sicherheit: str, ursache: str
) -> dict[str, Any]:
    """A diagnosis to save in the plant's history; the photos of the question are attached on "Ja"."""
    befund, ursache = befund.strip(), ursache.strip()
    if not befund or len(befund) > MAX_FINDING or len(ursache) > MAX_NOTE:
        return {"fehler": f"Befund mit 1-{MAX_FINDING} Zeichen, Ursache höchstens {MAX_NOTE}."}
    if sicherheit not in CONFIDENCE:
        return {"fehler": "sicherheit: 'ziemlich sicher' oder 'sicher'. Bei Unsicherheit keine Diagnose, nachfragen."}
    if not await active_plant(c, pflanze_id):
        return {"fehler": "Pflanze nicht gefunden"}
    payload = {"plant_id": pflanze_id, "title": befund, "confidence": sicherheit, "cause": ursache}
    return await _propose(c, message_id, "diagnose", payload)
