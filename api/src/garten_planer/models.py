"""API models. Unknown fields are refused everywhere (extra="forbid") so a typo
never silently disappears."""

from collections.abc import Mapping
from datetime import date
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field

from garten_planer.resolver import fold
from garten_planer.seed import Growth

Bundesland = Literal[
    "Baden-Württemberg", "Bayern", "Berlin", "Brandenburg", "Bremen", "Hamburg", "Hessen",
    "Mecklenburg-Vorpommern", "Niedersachsen", "Nordrhein-Westfalen", "Rheinland-Pfalz", "Saarland",
    "Sachsen", "Sachsen-Anhalt", "Schleswig-Holstein", "Thüringen",
]  # fmt: skip


def _blank_to_none(v: object) -> object:
    if isinstance(v, str):
        v = v.strip()
        return v or None
    return v


# Constraints sit on the str part, so a blank value can become None first.
Text80 = Annotated[Annotated[str, Field(max_length=80)] | None, BeforeValidator(_blank_to_none)]
Plz = Annotated[Annotated[str, Field(pattern=r"^\d{5}$")] | None, BeforeValidator(_blank_to_none)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def known_fields(model: type[BaseModel], data: Mapping[str, object]) -> dict[str, object]:
    """Keep only the keys `model` knows, recursively. Requests stay strict, but a
    stored document written by a newer version must still read after a rollback."""
    out: dict[str, object] = {}
    for name, field in model.model_fields.items():
        if name not in data:
            continue
        value, ann = data[name], field.annotation
        if isinstance(ann, type) and issubclass(ann, BaseModel) and isinstance(value, Mapping):
            value = known_fields(ann, value)
        out[name] = value
    return out


class Location(Strict):
    ort: Text80 = None
    plz: Plz = None
    bundesland: Bundesland | None = None


class Preferences(Strict):
    fertiliser: Literal["gemischt", "organisch", "mineralisch"] = "gemischt"
    eco_defaults: bool = True


class Legal(Strict):
    baumschutz_girth_cm: Annotated[int | None, Field(ge=10, le=500)] = None
    fruit_trees_exempt: bool = True


class Notifications(Strict):
    weather_push: bool = True


def _strip(v: object) -> object:
    return v.strip() if isinstance(v, str) else v


def _not_future(year: int | None) -> int | None:
    if year is not None and year > date.today().year:
        raise ValueError("year is in the future")
    return year


def _has_letters(v: str) -> str:
    if not fold(v):
        raise ValueError("needs letters or digits")
    return v


Name60 = Annotated[str, BeforeValidator(_strip), Field(min_length=1, max_length=60), AfterValidator(_has_letters)]
Text60 = Annotated[Annotated[str, Field(max_length=60)] | None, BeforeValidator(_blank_to_none)]
Text40 = Annotated[Annotated[str, Field(max_length=40)] | None, BeforeValidator(_blank_to_none)]
Ref = Annotated[str, Field(min_length=1, max_length=120)]
Light = Literal["sonnig", "halbschattig", "schattig"]
StandortType = Literal["beet", "gemuesebeet", "rasen", "hecke", "kuebelplatz", "gewaechshaus", "sonstiges"]
Form = Literal[
    "Säule", "Halbstamm", "Hochstamm", "Busch", "Spindel", "Spalier", "Strauch", "Hecke", "Solitär", "Kübel",
    "Kletterer", "Horst", "Knolle",
]  # fmt: skip


class StandortIn(Strict):
    """F-ST-2. A place in the garden; plants refer to it."""

    name: Name60
    light: Light
    type: StandortType
    notes: Annotated[str, Field(max_length=500)] = ""


class Standort(StandortIn):
    id: str
    plant_count: int


class PlantIn(Strict):
    """F-PL-3. One concrete specimen. References are checked by the route."""

    species_id: Ref
    cultivar_id: Ref | None = None
    standort_id: Ref
    nickname: Text60 = None
    form: Form | None = None
    rootstock: Text40 = None
    planted_year: Annotated[int | None, Field(ge=1900), AfterValidator(_not_future)] = None
    girth_cm: Annotated[int | None, Field(ge=1, le=1000)] = None
    in_container: bool = False
    notes: Annotated[str, Field(max_length=1000)] = ""


class SpeciesRef(BaseModel):
    id: str
    latin: str
    german: str
    growth: str
    woody: bool


class CultivarRef(BaseModel):
    id: str
    name: str


class StandortRef(BaseModel):
    id: str
    name: str
    light: Light | None  # None: the Standort was deleted meanwhile (see plants._expand)


class Plant(BaseModel):
    id: str
    species: SpeciesRef
    cultivar: CultivarRef | None
    standort: StandortRef
    nickname: str | None
    form: Form | None
    rootstock: str | None
    planted_year: int | None
    girth_cm: int | None
    in_container: bool
    notes: str
    archived: bool


class SpeciesIn(Strict):
    """A species the seed does not have (source "user"); Claude enriches it later (M5)."""

    latin: Annotated[
        str,
        BeforeValidator(_strip),
        Field(min_length=3, max_length=80, pattern="^[A-Za-z \u00d7.\\-]+$"),
        AfterValidator(_has_letters),
    ]
    german: Annotated[list[Name60], Field(min_length=1, max_length=5)]
    growth: Growth
    woody: bool


class CultivarIn(Strict):
    name: Name60


class GardenSettings(Strict):
    """F-ST-1/3. Personal data (location): stored in the data volume only."""

    location: Location = Location()
    preferences: Preferences = Preferences()
    legal: Legal = Legal()
    notifications: Notifications = Notifications()
