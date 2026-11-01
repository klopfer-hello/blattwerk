"""Plan and name quality check against the real Claude (/plan-eval, #005).

Runs a fixed set of plants and typed names through the same prompt, CLI call and
validation as the worker, writes nothing, and checks the answers with simple,
deterministic rules (strong cuts only in the § 39 window, harvest in the Sorte's
season, product hints, name resolution of the F-PL-1 test cases).
Run in the worker container: python -m blattwerk.plan_eval [--plans|--names]
Exit code 1 when a check fails; costs about USD 0.5 per full run."""

import asyncio
import re
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from blattwerk import names, plan
from blattwerk.claude_cli import config_from_env, run_json
from blattwerk.config import Config
from blattwerk.resolver import fold

WINTER = {10, 11, 12, 1, 2}  # § 39 BNatSchG: strong cuts on woody plants


def months(a: int | None, b: int | None) -> set[int]:
    if a is None or b is None:
        return set(range(1, 13))
    return set(range(a, b + 1)) if a <= b else set(range(a, 13)) | set(range(1, b + 1))


Check = Callable[[plan.Plan], str | None]  # None = ok, else what is wrong


def strong_cuts_in_winter(p: plan.Plan) -> str | None:
    bad = [t.title for t in p.tasks if t.cut_type == "stark" and not months(t.month_from, t.month_to) <= WINTER]
    return f"starker Schnitt außerhalb Okt-Feb: {bad}" if bad else None


def harvest_within(allowed: set[int]) -> Check:
    def check(p: plan.Plan) -> str | None:
        got = [months(t.month_from, t.month_to) for t in p.tasks if t.category == "ernte"]
        if not got:
            return "keine Ernte-Aufgabe"
        if all(m <= allowed for m in got):
            return None
        return f"Ernte {sorted(set().union(*got))} statt in {sorted(allowed)}"

    return check


def cut_in(allowed: set[int], kind: str = "pflege") -> Check:
    def check(p: plan.Plan) -> str | None:
        got = [months(t.month_from, t.month_to) for t in p.tasks if t.category == "schnitt" and t.cut_type == kind]
        return None if any(m & allowed for m in got) else f"kein {kind}-Schnitt in {sorted(allowed)}"

    return check


def no_cut_in(banned: set[int]) -> Check:
    def check(p: plan.Plan) -> str | None:
        bad = [t.title for t in p.tasks if t.category == "schnitt" and months(t.month_from, t.month_to) & banned]
        return f"Schnitt in {sorted(banned)}: {bad}" if bad else None

    return check


def product(pattern: str) -> Check:
    def check(p: plan.Plan) -> str | None:
        text = " ".join(f"{pr['name']} {' '.join(pr['brands'])}" for t in p.tasks for pr in t.products)
        return None if re.search(pattern, text, re.IGNORECASE) else f"kein Produkt passend zu /{pattern}/"

    return check


def basics(p: plan.Plan) -> str | None:
    problems = []
    if p.dropped:
        problems.append(f"{p.dropped} Aufgabe(n) verworfen")
    if len(p.tasks) < 3:
        problems.append("weniger als 3 Aufgaben")
    for t in p.tasks:
        if t.category == "duengen" and not any(len(pr["brands"]) >= 2 for pr in t.products):
            problems.append(f"Düngen ohne 2 Marken: {t.title}")
    return "; ".join(problems) or None


def F(latin: str, german: str, cultivar: str | None, form: str | None, *, rootstock: str | None = None,
      container: bool = False, light: str = "sonnig", standort: str = "beet") -> plan.PlanFacts:  # fmt: skip
    return plan.PlanFacts(latin=latin, german=german, cultivar=cultivar, form=form, rootstock=rootstock,
                          planted_year=2021, in_container=container, light=light, standort_type=standort,
                          bundesland="Sachsen", fertiliser="gemischt", eco_defaults=True)  # fmt: skip


@dataclass
class PlantCase:
    key: str
    facts: plan.PlanFacts
    checks: list[Check] = field(default_factory=list)


PLANTS = [
    PlantCase("hainbuche", F("Carpinus betulus", "Hainbuche", None, "Hecke", light="halbschattig", standort="hecke"),
              [strong_cuts_in_winter, cut_in({6, 7, 8})]),
    PlantCase("kirsche", F("Prunus avium", "Süßkirsche", "Celeste", "Säule", rootstock="GiSelA 5"),
              [strong_cuts_in_winter, harvest_within({6, 7})]),
    PlantCase("apfel", F("Malus domestica", "Apfel", "Rhapsodie", "Säule", rootstock="M9"),
              [strong_cuts_in_winter, harvest_within({8, 9, 10})]),
    PlantCase("rambler", F("Rosa", "Ramblerrose", "Ghislaine de Féligonde", "Kletterer"),
              [strong_cuts_in_winter, cut_in({7, 8, 9})]),
    PlantCase("chinaschilf", F("Miscanthus sinensis", "Chinaschilf", None, "Horst"),
              [no_cut_in({9, 10, 11, 12}), cut_in({2, 3, 4}, kind="stark")]),
    PlantCase("heidelbeere", F("Vaccinium corymbosum", "Kulturheidelbeere", "Bluecrop", "Kübel", container=True,
                               standort="kuebelplatz"),
              [strong_cuts_in_winter, harvest_within({6, 7, 8, 9}),
               product(r"rhodo|moorbeet|heidelbeer|azalee|sauer")]),
    PlantCase("felsenbirne", F("Amelanchier alnifolia", "Erlenblättrige Felsenbirne", "Obelisk", "Strauch"),
              [strong_cuts_in_winter]),
]  # fmt: skip

# the F-PL-1 cases: (typed, Latin starts with, Sorte contains, form)
NAMES = [
    ("Prunus AV. Celeste Säule", "Prunus avium", "celeste", "Säule"),
    ("Malus Rapsodi R Säule", "Malus", "rhapsodi", "Säule"),  # offline resolver: seed "Rhapsodie"
    ("Säulenapfel Sonate", "Malus", "sonate", "Säule"),
    ("Felsenbrine Obelisk", "Amelanchier", "obelisk", None),
    ("Rambler Rose Ghislaine DE Feligonde", "Rosa", "ghislaine de feligonde", None),
    ("Maibeere", "Lonicera", None, None),
]


async def eval_plant(case: PlantCase, sem: asyncio.Semaphore) -> tuple[bool, str]:
    async with sem:
        t0 = time.monotonic()
        try:
            cfg = Config()
            raw, info = await run_json(config_from_env(), plan.build_prompt(case.facts), plan.SYSTEM, plan.SCHEMA,
                                       model=cfg.plan_model, budget_usd=cfg.plan_budget_usd)  # fmt: skip
            p = plan.sanitize(raw)
            problems = [msg for check in [basics, *case.checks] if (msg := check(p))]
        except Exception as e:  # one broken case must not hide the others
            return False, f"FAIL {case.key}: {type(e).__name__}: {e}"
        head = (f"{'ok  ' if not problems else 'FAIL'} {case.key}: {len(p.tasks)} Aufgaben, {p.confidence}, "
                f"{time.monotonic() - t0:.0f}s, ${info.get('cost_usd') or 0:.3f}")  # fmt: skip
        return not problems, "\n".join([head, *(f"     - {x}" for x in problems)])


async def eval_name(
    typed: str, latin: str, sorte: str | None, form: str | None, sem: asyncio.Semaphore
) -> tuple[bool, str]:
    async with sem:
        try:
            cfg = Config()
            raw, _ = await run_json(config_from_env(), names.build_prompt(typed), names.SYSTEM, names.SCHEMA,
                                    model=cfg.plan_model, budget_usd=cfg.name_budget_usd)  # fmt: skip
            found = names.sanitize(raw)
        except Exception as e:
            return False, f"FAIL {typed!r}: {type(e).__name__}: {e}"
        if not found:
            return False, f"FAIL {typed!r}: keine Kandidaten"
        top = found[0]
        problems = []
        if not top.latin.startswith(latin):
            problems.append(f"Art {top.latin!r} statt {latin}")
        if sorte and fold(sorte) not in fold(top.cultivar or ""):
            problems.append(f"Sorte {top.cultivar!r} statt {sorte}")
        if form and top.form_hint != form:
            problems.append(f"Form {top.form_hint!r} statt {form}")
        label = f"{top.latin} '{top.cultivar}'" if top.cultivar else top.latin
        status = "ok  " if not problems else "FAIL"
        return not problems, f"{status} {typed!r} -> {label} ({'; '.join(problems) or top.german[0]})"


async def main(which: str) -> int:
    if which not in ("all", "--plans", "--names"):
        print("usage: python -m blattwerk.plan_eval [--plans|--names]")
        return 2
    sem = asyncio.Semaphore(3)
    jobs = []
    if which in ("all", "--plans"):
        jobs += [eval_plant(c, sem) for c in PLANTS]
    if which in ("all", "--names"):
        jobs += [eval_name(*n, sem) for n in NAMES]
    results = await asyncio.gather(*jobs)
    for _, line in results:
        print(line)
    passed = sum(ok for ok, _ in results)
    print(f"\n{passed}/{len(results)} ok (prompts {plan.PROMPT_VERSION}, {names.PROMPT_VERSION})")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "all")))
