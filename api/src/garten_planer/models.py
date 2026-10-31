"""API models. Unknown fields are refused everywhere (extra="forbid") so a typo
never silently disappears."""

from collections.abc import Mapping
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

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


class GardenSettings(Strict):
    """F-ST-1/3. Personal data (location): stored in the data volume only."""

    location: Location = Location()
    preferences: Preferences = Preferences()
    legal: Legal = Legal()
    notifications: Notifications = Notifications()
