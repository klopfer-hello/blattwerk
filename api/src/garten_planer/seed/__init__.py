"""Curated species/cultivar master data shipped with the app (species.json).
Validated strictly on load, so a typo in the file fails the tests, not the
household's phone."""

import json
from importlib import resources
from typing import Literal

from pydantic import BaseModel, ConfigDict

Growth = Literal[
    "baum", "strauch", "hecke", "kletterpflanze", "kuebel", "staude", "gras", "knolle", "gemuese", "kraut", "einjaehrig"
]
Feeder = Literal["stark", "mittel", "schwach"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SeedCultivar(_Strict):
    name: str
    synonyms: list[str] = []


class SeedSpecies(_Strict):
    id: str
    latin: str
    family: str
    german: list[str]
    synonyms: list[str] = []
    growth: Growth
    woody: bool
    hardiness_c: int | None = None  # °C, planted out (F-WX-5)
    feeder: Feeder | None = None
    cultivars: list[SeedCultivar]


class Seed(_Strict):
    version: int
    note: str
    species: list[SeedSpecies]


def load_seed() -> Seed:
    text = resources.files(__package__).joinpath("species.json").read_text(encoding="utf-8")
    return Seed.model_validate(json.loads(text))
