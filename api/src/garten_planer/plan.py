"""Care plans by Claude (M5): what we send, what we accept, how it is stored.

- build_prompt: only what the plan needs (species, Sorte, form, age, container,
  Standort light/type, Bundesland, preferences). Never Ort, PLZ, nicknames,
  notes or anything else personal (security rules; requirements PLAN-M5).
- SCHEMA: the answer structure the CLI enforces (--json-schema).
- sanitize: our own checks after the AI, not prompt-only: watering is dropped
  whatever the category (F-CP-6), a cut without type counts as strong
  (conservative for §39), every task must pass TaskIn, products are bounded.
- apply_plan: stores the plan, retires the previous plan's tasks (history
  stays; manual tasks are untouched, F-CP-7) and inserts the new ones, which
  then run through the legal rules like any task."""

import json
import re
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, ValidationError
from sqlalchemy import delete, insert, select, update
from sqlalchemy.ext.asyncio import AsyncConnection

from garten_planer.claude_cli import ClaudeError
from garten_planer.models import TaskIn
from garten_planer.names import clamp_hardiness
from garten_planer.schema import INDOOR, INDOOR_CATEGORIES, care_plans, plants, species, standorte, tasks, todos

PROMPT_VERSION = "plan-4"  # plan-2: phenological triggers (M7); plan-4: indoor plants (M11)
WATERING = re.compile(r"gie(ß|ss)|w(ä|ae)ssern|bew(ä|ae)sser|wassergabe|tr(ä|ae)nken|einschl(ä|ae)mmen", re.IGNORECASE)
# A cut the AI filed under another category must still meet § 39 (legal rules are code, not prompt).
CUTTING = re.compile(
    r"schneid|schnitt|r(ü|ue)ckschn|stutz|auslicht|verj(ü|ue)ng|roden|rodung|f(ä|ae)ll|auf den stock", re.IGNORECASE
)
CATEGORIES = [
    "schnitt",
    "duengen",
    "ernte",
    "pflanzenschutz",
    "winterschutz",
    "aussaat",
    "sonstiges",
    *INDOOR_CATEGORIES,
]

SYSTEM = """Du bist erfahrene Gärtnerin/Gärtnermeister für Hausgärten in Deutschland und erstellst einen Pflegeplan
für genau eine Pflanze. Antworte ausschließlich im vorgegebenen JSON-Format, alle Texte auf Deutsch, kurz und
handlungsorientiert.

Regeln:
- KEINE Gieß- oder Bewässerungsaufgaben (der Garten wird nicht über die App gegossen).
- Termine passend zur Sorte (nicht nur zur Art): z. B. Erntezeit, Schnittzeit, Blütezeit der genannten Sorte. Ist die
  Sorte unbekannt oder dir unsicher, sag das in "caveats" und setze "confidence" entsprechend.
- Zeitraum als Monatsfenster (recurrence "yearly", month_from/month_to 1-12) oder als Intervall in Tagen
  (recurrence "interval", z. B. Kontrollen). Klima des Bundeslands berücksichtigen.
- Wo die Natur den Zeitpunkt besser angibt als der Kalender, zusätzlich "pheno_phase" (Zeigerpflanze des
  phänologischen Kalenders) und "pheno_offset" (Tage danach, negativ = davor) angeben, z. B. Rosenschnitt zur
  Forsythienblüte = "erstfruehling", 0; Rasen-/Gehölzdüngung zum Austrieb = "erstfruehling"; nach der Blüte der
  Sorte = passende Phase mit Versatz. Phasen: vorfruehling (Haselblüte), erstfruehling (Forsythienblüte),
  vollfruehling (Apfelblüte), fruehsommer (Holunderblüte), hochsommer (Lindenblüte), spaetsommer (Frühapfel-Reife),
  fruehherbst (Holunderbeeren), vollherbst (Eicheln), spaetherbst (Laubfärbung), winter (Laubfall).
  "pheno_window" = wie viele Tage ab dann (1-60, sonst 14). Das Monatsfenster bleibt als Rückfallebene trotzdem
  Pflicht. Nur bei recurrence "yearly".
- Schnitt: immer "cut_type": "pflege" (schonender Form-/Pflegeschnitt, Zuwachs entfernen) oder "stark" (starker
  Rückschnitt, auf den Stock setzen, Verjüngung, Roden). Starke Schnitte an Hecken, Sträuchern und Gehölzen nur
  1. Oktober bis Ende Februar planen (§ 39 BNatSchG). Andere Kategorien: "cut_type": null.
- Düngen: Produktart, NPK, Menge und 2-3 Markenbeispiele aus deutschen Bau- und Gartenmärkten (z. B. OBI,
  Hornbach, Dehner, Raiffeisen); die Dünger-Vorliebe beachten.
- Pflanzenschutz: typische Schädlinge/Krankheiten der Sorte mit Vorbeugung (z. B. Leimringe, Gelbtafeln für
  Kirschfruchtfliege, Weißtafeln für Apfelsägewespe), Kontrollen und Behandlung: zuerst mechanisch/biologisch,
  Mittel nur mit Zulassung für Haus- und Kleingarten.
- Ökologische Empfehlungen beachten, wenn eingeschaltet (Samenstände/Halme über den Winter stehen lassen).
- "winterhaerte_c": tiefste Temperatur in °C, die diese Pflanze ausgepflanzt übersteht (für Frostwarnungen);
  null, wenn unklar.
- Anleitungen als kurze Schritte; "why" in einem Satz. Höchstens 12 Aufgaben, nur das Wichtige."""

SYSTEM_INDOOR = """Du bist erfahrene Zimmerpflanzen-Gärtnerin und erstellst einen Pflegeplan für genau eine
Zimmerpflanze in einer Wohnung in Deutschland. Antworte ausschließlich im vorgegebenen JSON-Format, alle Texte auf
Deutsch, kurz und handlungsorientiert.

Regeln:
- Gießen als eigene Aufgabe: category "giessen", recurrence "interval", "interval_days" (Frühling bis Herbst) und
  "winter_interval_days" (November bis Februar, meist länger). Richte die Tage nach Art, Licht (Fensterrichtung,
  Abstand zum Fenster), Topfgröße und Topfmaterial (Ton trocknet schneller als Kunststoff) und Heizungsluft im
  Winter. Sukkulenten und Kakteen deutlich seltener, Farne und Calathea öfter. In "instructions" wie viel und woran
  man erkennt, dass es Zeit ist (Fingerprobe, Topfgewicht), und Staunässe vermeiden.
- Besprühen (category "bespruehen", Intervall in Tagen): für Pflanzen, die hohe Luftfeuchte mögen (Farne,
  Calathea, Orchideen-Luftwurzeln, Tillandsien, viele Tropenpflanzen), im Winter bei Heizungsluft öfter
  ("winter_interval_days" kürzer). NICHT bei Sukkulenten, Kakteen und behaarten oder samtigen Blättern (Usambara-
  veilchen): dann keine Besprüh-Aufgabe. Anleitung: kalkarmes, zimmerwarmes Wasser, morgens, nicht in die Sonne.
- Entstauben (category "entstauben", Intervall in Tagen, meist 30-60): für Pflanzen mit glatten Blättern (Monstera,
  Ficus, Gummibaum, Zamioculcas, Palmen); Anleitung: feuchtes Tuch oder lauwarm abduschen, Blattunterseiten auf
  Schädlinge prüfen; bei behaarten Blättern nur mit weichem Pinsel.
- Wiederkehrende Pflege als Intervall in Tagen: Düngen nur in der Wachstumszeit (month_from 3 oder 4 bis month_to 8
  oder 9 setzen), Topf drehen, Umtopfen alle n Jahre (z. B. 730 oder 1095 Tage). Einmal im Jahr zu einem festen
  Zeitpunkt: recurrence "yearly" mit Monatsfenster.
- Düngen: flüssiger Grün- oder Kakteendünger, Menge und 2-3 Markenbeispiele (z. B. Compo, Substral, Seramis).
- Schädlinge: typische für Zimmerpflanzen (Spinnmilben, Trauermücken, Woll- und Schmierläuse, Thripse) mit
  Vorbeugung, Kontrolle und Behandlung, zuerst mechanisch/biologisch.
- Keine Frost-, Garten- oder Schnittaufgaben nach Gartenkalender, keine "pheno_phase". "cut_type" nur bei
  category "schnitt" ("pflege"), sonst null. "winterhaerte_c": null.
- Anleitungen als kurze Schritte; "why" in einem Satz. Höchstens 8 Aufgaben, nur das Wichtige."""


S20 = Annotated[str, Field(max_length=20)]
S40 = Annotated[str, Field(max_length=40)]
S80 = Annotated[str, Field(max_length=80)]
S120 = Annotated[str, Field(max_length=120)]
S300 = Annotated[str, Field(max_length=300)]
S400 = Annotated[str, Field(max_length=400)]
S600 = Annotated[str, Field(max_length=600)]
S2000 = Annotated[str, Field(max_length=2000)]


class _SchemaProduct(BaseModel):
    name: S80
    kind: Literal["organisch", "mineralisch", "organisch-mineralisch", "sonstiges"]
    npk: S20 | None
    dose: S80
    brands: list[S40]


class _SchemaTask(BaseModel):
    title: S120
    category: Literal[
        "schnitt", "duengen", "ernte", "pflanzenschutz", "winterschutz", "aussaat", "sonstiges", "giessen",
        "bespruehen", "entstauben",
    ]  # fmt: skip
    cut_type: Literal["pflege", "stark"] | None
    recurrence: Literal["yearly", "interval"]
    month_from: int | None
    month_to: int | None
    interval_days: int | None
    winter_interval_days: int | None
    pheno_phase: (
        Literal[
            "vorfruehling",
            "erstfruehling",
            "vollfruehling",
            "fruehsommer",
            "hochsommer",
            "spaetsommer",
            "fruehherbst",
            "vollherbst",
            "spaetherbst",
            "winter",
        ]
        | None
    )
    pheno_offset: int | None
    pheno_window: int | None
    instructions: S2000
    why: S300
    products: list[_SchemaProduct]


class _SchemaPest(BaseModel):
    name: S80
    time: S40
    prevent: S400
    treat: S400


class _SchemaPlan(BaseModel):
    winterhaerte_c: int | None
    summary: S600
    confidence: Literal["low", "medium", "high"]
    caveats: S400
    tasks: list[_SchemaTask]
    pests: list[_SchemaPest]


SCHEMA: dict[str, Any] = _SchemaPlan.model_json_schema()


class _Loose(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Pest(_Loose):
    name: Annotated[str, Field(min_length=1, max_length=80)]
    time: Annotated[str, Field(max_length=40)] = ""
    prevent: Annotated[str, Field(max_length=400)] = ""
    treat: Annotated[str, Field(max_length=400)] = ""


class _Answer(_Loose):
    winterhaerte_c: Annotated[int | None, BeforeValidator(clamp_hardiness)] = None
    summary: Annotated[str, Field(min_length=1, max_length=600)]
    confidence: Literal["low", "medium", "high"]
    caveats: Annotated[str, Field(max_length=400)] = ""
    tasks: Annotated[list[dict[str, Any]], Field(min_length=1, max_length=25)]
    pests: Annotated[list[Pest], Field(max_length=10)] = []


class Product(_Loose):
    name: Annotated[str, Field(min_length=1, max_length=80)]
    kind: Annotated[str, Field(max_length=30)] = "sonstiges"
    npk: Annotated[str | None, Field(max_length=20)] = None
    dose: Annotated[str, Field(max_length=80)] = ""
    brands: list[Annotated[str, Field(max_length=40)]] = []


class PlanTask(TaskIn):
    products: list[dict[str, Any]] = Field(default_factory=list)
    why: Annotated[str, Field(max_length=300)] = ""


@dataclass(frozen=True)
class Plan:
    summary: str
    confidence: str
    caveats: str
    pests: list[dict[str, str]]
    tasks: list[PlanTask]
    dropped: int
    hardiness_c: int | None = None  # the AI's value for the species, kept when the species has none


@dataclass(frozen=True)
class PlanFacts:
    latin: str
    german: str
    cultivar: str | None
    form: str | None
    rootstock: str | None
    planted_year: int | None
    in_container: bool
    light: str
    standort_type: str
    bundesland: str | None
    fertiliser: str
    eco_defaults: bool
    window: str | None = None  # indoor plants (M11)
    window_distance: str | None = None
    pot_cm: int | None = None
    pot_material: str | None = None

    @property
    def indoor(self) -> bool:
        return self.standort_type == INDOOR


def system_for(f: PlanFacts) -> str:
    return SYSTEM_INDOOR if f.indoor else SYSTEM


def build_prompt(f: PlanFacts) -> str:
    if f.indoor:
        room = {
            "art_latein": f.latin,
            "art_deutsch": f.german,
            "sorte": f.cultivar or "unbekannt",
            "licht_im_raum": f.light,
            "fenster": f.window or "unbekannt",
            "abstand_zum_fenster": f.window_distance or "unbekannt",
            "topf_cm": f.pot_cm,
            "topf_material": f.pot_material or "unbekannt",
            "duenger_vorliebe": f.fertiliser,
        }
        return "Erstelle den Pflegeplan für diese Zimmerpflanze:\n" + json.dumps(room, ensure_ascii=False, indent=2)
    facts = {
        "art_latein": f.latin,
        "art_deutsch": f.german,
        "sorte": f.cultivar or "unbekannt",
        "wuchsform": f.form or "unbekannt",
        "unterlage": f.rootstock or "unbekannt",
        "pflanzjahr": f.planted_year,
        "im_kuebel": f.in_container,
        "licht_am_standort": f.light,
        "standort_typ": f.standort_type,
        "bundesland": f.bundesland or "unbekannt (Deutschland)",
        "duenger_vorliebe": f.fertiliser,
        "oekologische_empfehlungen": f.eco_defaults,
    }
    return "Erstelle den Pflegeplan für diese Pflanze:\n" + json.dumps(facts, ensure_ascii=False, indent=2)


# A sentence ends at . ! ? before a capital letter or a step number ("2. "), not after an
# abbreviation ("z. B.", "ca.") or a step number itself ("1. ").
_END = re.compile(r"[.!?](\s+)(?=[A-ZÄÖÜ]|\d+[.)]\s)")
_ABBR = {"z", "b", "ca", "bzw", "ggf", "u", "a", "nr", "evtl", "inkl", "max", "min", "mind", "usw", "vgl", "d", "h",
         "bspw", "etc", "o", "s", "zb", "ff"}  # fmt: skip
_STEP_ONLY = re.compile(r"\s*\d+[.)]\s*")


def _sentences(line: str) -> list[str]:
    out, start = [], 0
    for m in _END.finditer(line):
        word = re.search(r"(\w+)$", line[start : m.start()])
        token = word.group(1).lower() if word else ""
        if token in _ABBR or token.isdigit():
            continue
        out.append(line[start : m.end()])
        start = m.end()
    out.append(line[start:])
    return out


def dry(text: str) -> str:
    """Without the sentences that tell to water (F-CP-6: the app never asks for watering).
    Line by line, so steps and paragraphs keep their shape; a line left with only its step
    number goes too."""
    lines = []
    for line in text.strip().split("\n"):
        kept = "".join(s for s in _sentences(line) if not WATERING.search(s)).rstrip()
        if line.strip() and (not kept.strip() or _STEP_ONLY.fullmatch(kept)):
            continue  # the whole line was about watering
        lines.append(kept)
    return "\n".join(lines).strip()


def _products(raw: Any) -> list[dict[str, Any]]:
    out = []
    for p in raw if isinstance(raw, list) else []:
        try:
            brands = p.get("brands")
            prod = Product.model_validate({**p, "brands": brands[:3] if isinstance(brands, list) else []})
        except (ValidationError, TypeError, AttributeError):
            continue
        out.append(prod.model_dump())
    return out[:3]


PHASE_KEYS = {"vorfruehling", "erstfruehling", "vollfruehling", "fruehsommer", "hochsommer", "spaetsommer",
              "fruehherbst", "vollherbst", "spaetherbst", "winter"}  # fmt: skip


def _int(v: Any, low: int, high: int, default: int) -> int:
    return min(high, max(low, v)) if isinstance(v, int) and not isinstance(v, bool) else default


def _winter(t: dict[str, Any]) -> dict[str, Any]:
    """Indoor watering: the winter interval, clamped like the summer one; only for interval tasks."""
    if t.get("recurrence") != "interval" or not isinstance(t.get("winter_interval_days"), int):
        return {}
    return {"winter_interval_days": _int(t["winter_interval_days"], 1, 3650, 1)}


def _trigger(t: dict[str, Any]) -> dict[str, Any]:
    """The phenological trigger, checked on its own: a bad one is dropped, not the task (the
    month window stays); offset and window are clamped to what TaskIn allows."""
    if t.get("recurrence") != "yearly" or t.get("pheno_phase") not in PHASE_KEYS:
        return {}
    return {"pheno_phase": t["pheno_phase"], "pheno_offset": _int(t.get("pheno_offset"), -60, 120, 0),
            "pheno_window": _int(t.get("pheno_window"), 1, 60, 14)}  # fmt: skip


def sanitize(raw: dict[str, Any], indoor: bool = False) -> Plan:
    """Indoor (M11): watering stays (as "giessen"), no phenological triggers; the garden never
    gets watering (F-CP-6)."""
    try:
        a = _Answer.model_validate(raw)
    except ValidationError:
        raise ClaudeError("Die KI-Antwort war unvollständig. Bitte nochmal versuchen.") from None
    kept: list[PlanTask] = []
    dropped = 0
    for t in a.tasks:
        if not isinstance(t, dict):
            dropped += 1
            continue
        waters = bool(WATERING.search(f"{t.get('title', '')} {t.get('category', '')}"))
        if waters and not indoor:
            dropped += 1  # never watering in the garden (F-CP-6), whatever the category
            continue
        fields = {k: t.get(k) for k in ("title", "category", "recurrence", "month_from", "month_to", "interval_days")}
        if indoor:
            fields |= _winter(t)
            if waters and fields["category"] in (None, "sonstiges") and WATERING.search(str(fields["title"] or "")):
                fields["category"] = "giessen"
        else:
            fields |= _trigger(t)
            if fields["category"] in INDOOR_CATEGORIES:
                dropped += 1
                continue
        if fields["category"] not in ("schnitt", "ernte") and CUTTING.search(str(fields["title"] or "")):
            fields["category"] = "schnitt"
        cut = t.get("cut_type")
        cut = (cut if cut in ("pflege", "stark") else "stark") if fields["category"] == "schnitt" else None
        try:
            kept.append(
                PlanTask.model_validate(
                    {
                        **fields,
                        "cut_type": cut,
                        "instructions": dry(str(t.get("instructions") or ""))[:4000],
                        "why": dry(str(t.get("why") or ""))[:300],
                        "products": _products(t.get("products")),
                    }
                )
            )
        except ValidationError:
            dropped += 1
    if not kept:
        raise ClaudeError("Die KI-Antwort war unvollständig (keine brauchbaren Aufgaben). Bitte nochmal versuchen.")
    return Plan(a.summary, a.confidence, a.caveats, [p.model_dump() for p in a.pests], kept, dropped, a.winterhaerte_c)


async def apply_plan(c: AsyncConnection, plant_id: str, plan: Plan, info: dict[str, Any]) -> tuple[str, list[str]]:
    """Store the plan and its tasks; returns (plan id, new task ids). The caller materializes.
    The plant may have moved in or out during the AI run: indoor-only tasks are kept only indoors."""
    stamp = datetime.now(UTC)
    where = (
        await c.execute(select(standorte.c.type).select_from(plants.join(standorte)).where(plants.c.id == plant_id))
    ).scalar()
    if where != INDOOR:
        plan = replace(plan, tasks=[t for t in plan.tasks if t.category not in INDOOR_CATEGORIES])
    plan_id = uuid.uuid4().hex
    await c.execute(
        insert(care_plans).values(
            id=plan_id,
            plant_id=plant_id,
            created_at=stamp,
            model=str(info.get("model") or "unbekannt"),
            prompt_version=PROMPT_VERSION,
            cost_usd=info.get("cost_usd"),
            summary=plan.summary,
            confidence=plan.confidence,
            caveats=plan.caveats,
            pests=plan.pests,
            dropped=plan.dropped,
        )
    )
    previous = (
        await c.execute(
            select(tasks.c.id, tasks.c.title, tasks.c.enabled).where(
                tasks.c.plant_id == plant_id, tasks.c.source == "plan", ~tasks.c.retired
            )
        )
    ).all()
    old = [r.id for r in previous]
    if plan.hardiness_c is not None:  # only fills a gap of a species the app added; seed values stay
        sid = select(plants.c.species_id).where(plants.c.id == plant_id).scalar_subquery()
        await c.execute(
            update(species)
            .where(species.c.id == sid, species.c.source == "user", species.c.hardiness_c.is_(None))
            .values(hardiness_c=plan.hardiness_c)
        )
    paused = {r.title.casefold() for r in previous if not r.enabled}  # the user's pause carries over by title
    if old:  # retire the previous plan: open occurrences go, done ones stay as history
        await c.execute(update(tasks).where(tasks.c.id.in_(old)).values(enabled=False, retired=True, updated_at=stamp))
        await c.execute(delete(todos).where(todos.c.task_id.in_(old), todos.c.status == "open"))
    ids = []
    for t in plan.tasks:
        tid = uuid.uuid4().hex
        ids.append(tid)
        values = t.model_dump(exclude={"products", "why"}) | {"plant_id": plant_id}
        await c.execute(
            insert(tasks).values(
                **values,
                id=tid,
                source="plan",
                plan_id=plan_id,
                products=t.products,
                why=t.why,
                enabled=t.title.casefold() not in paused,
                generation=1,
                created_at=stamp,
                updated_at=stamp,
            )
        )
    return plan_id, ids
