"""Care plans (M5): what goes to Claude (privacy), what comes back (validation and
the code-side safety filters), and the job flow with a fake Claude."""

import asyncio
from datetime import date, datetime, time
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.ext.asyncio import create_async_engine

from blattwerk import worker
from blattwerk.claude_cli import ClaudeError
from blattwerk.plan import PlanFacts, build_prompt, sanitize
from blattwerk.routes.todos import TZ, now
from blattwerk.worker import run_plan_jobs
from tests.conftest import BASE, DATABASE_URL

H = {"Origin": BASE}

FACTS = PlanFacts(latin="Carpinus betulus", german="Hainbuche", cultivar=None, form="Hecke", rootstock=None,
                  planted_year=2020, in_container=False, light="halbschattig", standort_type="hecke",
                  bundesland="Sachsen", fertiliser="gemischt", eco_defaults=True)  # fmt: skip


def answer(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "summary": "Hainbuchenhecke: zweimal im Jahr schneiden.",
        "confidence": "high",
        "caveats": "",
        "tasks": [
            {"title": "Hecke in Form schneiden", "category": "schnitt", "cut_type": "pflege", "recurrence": "yearly",
             "month_from": 6, "month_to": 6, "instructions": "1. Seiten schräg schneiden.", "why": "Dichter Wuchs.",
             "products": []},
            {"title": "Hecke stark verjüngen", "category": "schnitt", "cut_type": "stark", "recurrence": "yearly",
             "month_from": 6, "month_to": 6, "instructions": "Alte Triebe entfernen.", "why": "Verkahlung.",
             "products": []},
            {"title": "Organisch düngen", "category": "duengen", "cut_type": None, "recurrence": "yearly",
             "month_from": 3, "month_to": 4, "instructions": "80 g/m².", "why": "Austrieb.",
             "products": [{"name": "Hornspäne", "kind": "organisch", "npk": "14-0-0", "dose": "80 g/m²",
                           "brands": ["Oscorna", "Neudorff", "Compo"]}]},
        ],
        "pests": [{"name": "Mehltau", "time": "Jun-Aug", "prevent": "Luftig schneiden.",
                   "treat": "Befallene Triebe entfernen."}],
    }  # fmt: skip
    return base | kw


# ----- prompt -----------------------------------------------------------------


def test_prompt_contains_what_matters_and_nothing_personal() -> None:
    prompt = build_prompt(FACTS)
    for needed in ("Carpinus betulus", "Hainbuche", "Hecke", "halbschattig", "Sachsen", "2020"):
        assert needed in prompt
    system_and_prompt = prompt.lower()
    for private in ("ort", "plz", "nickname", "spitzname", "notiz"):
        assert f'"{private}"' not in system_and_prompt


# ----- sanitize (code-side checks, not prompt) ---------------------------------


def test_sanitize_keeps_valid_tasks() -> None:
    plan = sanitize(answer())
    assert [t.title for t in plan.tasks] == ["Hecke in Form schneiden", "Hecke stark verjüngen", "Organisch düngen"]
    assert plan.tasks[2].products[0]["brands"] == ["Oscorna", "Neudorff", "Compo"]


@pytest.mark.parametrize("title", ["Regelmäßig gießen", "Bei Trockenheit wässern", "Bewässerung prüfen"])
def test_watering_is_dropped_whatever_the_category(title: str) -> None:
    t = {"title": title, "category": "sonstiges", "cut_type": None, "recurrence": "interval", "interval_days": 3,
         "instructions": "", "why": "", "products": []}  # fmt: skip
    assert [x.title for x in sanitize(answer(tasks=[*answer()["tasks"], t])).tasks] == [
        "Hecke in Form schneiden", "Hecke stark verjüngen", "Organisch düngen"]  # fmt: skip
    assert sanitize(answer(tasks=[*answer()["tasks"], t])).dropped == 1


def test_cut_without_type_is_treated_as_strong_and_type_elsewhere_removed() -> None:
    tasks = answer()["tasks"]
    tasks[0] = tasks[0] | {"cut_type": None}
    tasks[2] = tasks[2] | {"cut_type": "stark"}
    plan = sanitize(answer(tasks=tasks))
    assert plan.tasks[0].cut_type == "stark" and plan.tasks[2].cut_type is None


@pytest.mark.parametrize(
    "bad",
    [
        {"tasks": "keine"},
        {"confidence": "sehr hoch"},
        {"tasks": [{"title": "", "category": "schnitt"}]},
        {"summary": "x" * 2000},
    ],
)
def test_invalid_answers_are_rejected(bad: dict[str, Any]) -> None:
    with pytest.raises(ClaudeError, match="unvollständig"):
        sanitize(answer(**bad))


def test_invalid_single_tasks_are_dropped_not_the_plan() -> None:
    broken = {"title": "Ohne Zeitraum", "category": "duengen", "recurrence": "yearly"}
    plan = sanitize(answer(tasks=[*answer()["tasks"], broken]))
    assert len(plan.tasks) == 3 and plan.dropped == 1


# ----- jobs (fake Claude) ---------------------------------------------------------


def hedge(client: TestClient, **kw: Any) -> str:
    st = client.post(
        "/api/standorte", json={"name": "Nord", "light": "halbschattig", "type": "hecke"}, headers=H
    ).json()
    body = {"species_id": "carpinus-betulus", "standort_id": st["id"], "form": "Hecke", "nickname": "Geheime Hecke",
            "notes": "Privates", **kw}  # fmt: skip
    return str(client.post("/api/plants", json=body, headers=H).json()["id"])


def work(runner: Any) -> int:
    async def go() -> int:
        engine = create_async_engine(DATABASE_URL)
        try:
            return await run_plan_jobs(engine, runner, daily_limit=60)
        finally:
            await engine.dispose()

    return asyncio.run(go())


def fake(result: dict[str, Any] | Exception, seen: list[str] | None = None) -> Any:
    async def run(prompt: str, system: str, schema: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        if seen is not None:
            seen.append(prompt)
        if isinstance(result, Exception):
            raise result
        return result, {"model": "claude-sonnet-test", "cost_usd": 0.1, "duration_ms": 1}

    return run


def test_plan_job_creates_tasks_through_the_legal_rules(client: TestClient) -> None:
    client.app.dependency_overrides[now] = lambda: datetime.combine(date(2026, 6, 10), time(10), TZ)  # type: ignore[attr-defined]
    pid = hedge(client)  # the plan is queued with the plant
    assert client.post(f"/api/plants/{pid}/plan", headers=H).status_code == 409  # one at a time
    seen: list[str] = []
    assert work(fake(answer(), seen)) == 1
    assert "Geheime Hecke" not in seen[0] and "Privates" not in seen[0]
    p = client.get(f"/api/plants/{pid}/plan").json()
    assert p["job"]["status"] == "done" and p["plan"]["summary"].startswith("Hainbuchenhecke")
    assert p["plan"]["model"] == "claude-sonnet-test" and p["plan"]["pests"][0]["name"] == "Mehltau"
    tasks = client.get("/api/tasks", params={"plant_id": pid}).json()
    assert {t["source"] for t in tasks} == {"plan"} and len(tasks) == 3
    titles = [x["task"]["title"] for x in client.get("/api/todos/heute").json()["open"]]
    assert "Hecke in Form schneiden" in titles and "Hecke stark verjüngen" not in titles  # moved to October


def test_failed_job_keeps_the_old_plan_and_says_why(client: TestClient) -> None:
    pid = hedge(client)
    client.post(f"/api/plants/{pid}/plan", headers=H)
    work(fake(ClaudeError("Die KI hat nach 300 s nicht geantwortet.")))
    p = client.get(f"/api/plants/{pid}/plan").json()
    assert p["job"]["status"] == "failed" and "300 s" in p["job"]["error"] and p["plan"] is None


def test_regenerating_disables_old_plan_tasks_and_keeps_manual_ones(client: TestClient) -> None:
    pid = hedge(client)
    manual = {"title": "Eigene Aufgabe", "category": "sonstiges", "recurrence": "yearly", "month_from": 5,
              "month_to": 5, "plant_id": pid}  # fmt: skip
    client.post("/api/tasks", json=manual, headers=H)
    for _ in range(2):
        client.post(f"/api/plants/{pid}/plan", headers=H)
        work(fake(answer()))
    tasks = client.get("/api/tasks", params={"plant_id": pid, "retired": True}).json()
    enabled = sorted(t["title"] for t in tasks if t["enabled"])
    assert enabled == ["Eigene Aufgabe", "Hecke in Form schneiden", "Hecke stark verjüngen", "Organisch düngen"]
    assert len([t for t in tasks if not t["enabled"]]) == 3  # the first plan's tasks stay as history


def test_daily_limit(client: TestClient, db: Engine) -> None:
    pid = hedge(client)
    client.post(f"/api/plants/{pid}/plan", headers=H)

    async def go() -> int:
        engine = create_async_engine(DATABASE_URL)
        try:
            return await run_plan_jobs(engine, fake(answer()), daily_limit=0)
        finally:
            await engine.dispose()

    assert asyncio.run(go()) == 0
    with db.connect() as c:
        assert c.execute(text("SELECT status FROM plan_jobs")).scalar() == "queued"  # waits for tomorrow


def test_unknown_plant_is_404(client: TestClient) -> None:
    assert client.post("/api/plants/nope/plan", headers=H).status_code == 404


# ----- review findings ---------------------------------------------------------------


def test_cut_hidden_in_another_category_still_goes_through_the_legal_rules() -> None:
    sneaky = {"title": "Hecke radikal zurückschneiden", "category": "sonstiges", "cut_type": None,
              "recurrence": "yearly", "month_from": 6, "month_to": 6, "instructions": "", "why": "",
              "products": []}  # fmt: skip
    t = sanitize(answer(tasks=[sneaky])).tasks[0]
    assert (t.category, t.cut_type) == ("schnitt", "stark")


def test_brands_must_be_a_list() -> None:
    tasks = answer()["tasks"]
    tasks[2]["products"][0]["brands"] = "Oscorna"
    assert sanitize(answer(tasks=tasks)).tasks[2].products[0]["brands"] == []


def test_stale_running_job_is_failed_and_the_plant_unlocked(client: TestClient, db: Engine) -> None:
    pid = hedge(client)
    client.post(f"/api/plants/{pid}/plan", headers=H)
    with db.begin() as c:  # a worker died mid-run an hour ago
        c.execute(text("UPDATE plan_jobs SET status = 'running', started_at = now() - interval '1 hour'"))
    assert client.post(f"/api/plants/{pid}/plan", headers=H).status_code == 202
    p = client.get(f"/api/plants/{pid}/plan").json()
    assert p["job"]["status"] == "queued"
    with db.connect() as c:
        assert c.execute(text("SELECT count(*) FROM plan_jobs WHERE status = 'failed'")).scalar() == 1


def test_job_whose_facts_fail_ends_failed_and_does_not_block_the_queue(
    client: TestClient, db: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    pid = hedge(client)
    client.post(f"/api/plants/{pid}/plan", headers=H)

    async def broken(*_: Any) -> None:
        raise RuntimeError("broken row")

    monkeypatch.setattr(worker, "_plan_facts", broken)
    assert work(fake(answer())) == 1
    with db.connect() as c:
        assert c.execute(text("SELECT status FROM plan_jobs")).scalar() == "failed"


def test_archived_plant_gets_no_plan(client: TestClient) -> None:
    pid = hedge(client)
    client.post(f"/api/plants/{pid}/archive", headers=H)
    assert client.post(f"/api/plants/{pid}/plan", headers=H).status_code == 409


def test_daily_limit_is_told_when_asking(client: TestClient, db: Engine) -> None:
    pid = hedge(client)
    with db.begin() as c:
        for i in range(60):
            c.execute(text("INSERT INTO plan_jobs (id, plant_id, status, created_at, started_at) "
                           "VALUES (:i, :p, 'failed', now(), now())"), {"i": f"j{i}", "p": pid})  # fmt: skip
    assert client.post(f"/api/plants/{pid}/plan", headers=H).status_code == 429


def test_retired_plan_tasks_are_hidden_and_cannot_be_enabled(client: TestClient) -> None:
    pid = hedge(client)
    for _ in range(2):
        client.post(f"/api/plants/{pid}/plan", headers=H)
        work(fake(answer()))
    visible = client.get("/api/tasks", params={"plant_id": pid}).json()
    assert len(visible) == 3 and all(t["enabled"] for t in visible)
    with_retired = client.get("/api/tasks", params={"plant_id": pid, "retired": True}).json()
    old = next(t for t in with_retired if not t["enabled"])
    assert client.post(f"/api/tasks/{old['id']}/enable", headers=H).status_code == 409


# ----- ticket 027 ------------------------------------------------------------------------------------


def test_watering_sentences_are_taken_out_of_the_instructions() -> None:
    tasks = answer()["tasks"]
    tasks[2] |= {
        "instructions": "Hornspäne einarbeiten. Danach gut angießen. Mulchen.",
        "why": "Austrieb. Gießen hilft.",
    }
    t = sanitize(answer(tasks=tasks)).tasks[2]
    assert t.instructions == "Hornspäne einarbeiten. Mulchen." and t.why == "Austrieb."


def test_a_paused_plan_task_stays_paused_in_the_next_plan(client: TestClient) -> None:
    pid = hedge(client)
    client.post(f"/api/plants/{pid}/plan", headers=H)
    work(fake(answer()))
    tasks = client.get("/api/tasks", params={"plant_id": pid}).json()
    paused = next(t for t in tasks if t["title"] == "Organisch düngen")
    client.post(f"/api/tasks/{paused['id']}/disable", headers=H)
    client.post(f"/api/plants/{pid}/plan", headers=H)
    work(fake(answer()))
    now_ = {t["title"]: t["enabled"] for t in client.get("/api/tasks", params={"plant_id": pid}).json()}
    assert now_ == {"Hecke in Form schneiden": True, "Hecke stark verjüngen": True, "Organisch düngen": False}


def test_a_job_that_never_reached_claude_does_not_count(client: TestClient, db: Engine) -> None:
    from blattwerk.claude_cli import NotReady

    pid = hedge(client)
    client.post(f"/api/plants/{pid}/plan", headers=H)
    work(fake(NotReady("Die KI ist noch nicht eingerichtet (CLAUDE_CODE_OAUTH_TOKEN fehlt auf dem Server).")))
    with db.connect() as c:
        row = c.execute(text("SELECT status, started_at FROM plan_jobs")).one()
    assert row.status == "failed" and row.started_at is None


@pytest.mark.parametrize(
    ("text", "dried"),
    [
        ("Gut wässern, z. B. morgens. Dann mulchen.", "Dann mulchen."),
        ("Ca. 3 kg Kompost geben. Danach angießen.", "Ca. 3 kg Kompost geben."),
        ("1. Boden lockern. 2. Gut angießen. 3. Mulchen.", "1. Boden lockern. 3. Mulchen."),
        ("1. Boden lockern.\n2. Gut angießen.\n3. Mulchen.", "1. Boden lockern.\n3. Mulchen."),
        ("Schnitt bzw. Rückschnitt im März.\nNicht gießen.", "Schnitt bzw. Rückschnitt im März."),
        ("Erste Zeile.\n\nZweiter Absatz bleibt.", "Erste Zeile.\n\nZweiter Absatz bleibt."),
    ],
)
def test_dry_keeps_german_text_whole(text: str, dried: str) -> None:
    from blattwerk.plan import dry

    assert dry(text) == dried


# ----- automatic plan (user request 2026-11-01) ---------------------------------------------------


def plan_jobs_count(db: Engine) -> int:
    with db.connect() as c:
        return int(c.execute(text("SELECT count(*) FROM plan_jobs")).scalar() or 0)


def test_a_new_plant_gets_its_plan_queued(client: TestClient, db: Engine) -> None:
    pid = hedge(client)
    assert plan_jobs_count(db) == 1
    assert client.get(f"/api/plants/{pid}/plan").json()["job"]["status"] == "queued"


def test_changing_species_or_sorte_queues_a_new_plan_other_edits_do_not(client: TestClient, db: Engine) -> None:
    pid = hedge(client)
    work(fake(answer()))
    p = client.get(f"/api/plants/{pid}").json()
    body = {"species_id": p["species"]["id"], "cultivar_id": None, "standort_id": p["standort"]["id"],
            "nickname": None, "form": "Strauch", "rootstock": None, "planted_year": 2021, "girth_cm": None,
            "in_container": False, "notes": ""}  # fmt: skip
    client.put(f"/api/plants/{pid}", json=body, headers=H)
    assert plan_jobs_count(db) == 1  # form changed: no new plan by itself
    client.put(f"/api/plants/{pid}", json=body | {"species_id": "fagus-sylvatica"}, headers=H)
    assert plan_jobs_count(db) == 2


def test_no_automatic_plan_over_the_daily_limit(client: TestClient, db: Engine) -> None:
    st = client.post("/api/standorte", json={"name": "N", "light": "sonnig", "type": "beet"}, headers=H).json()
    first = client.post("/api/plants", json={"species_id": "malus-domestica", "standort_id": st["id"]}, headers=H)
    with db.begin() as c:
        c.execute(text("UPDATE plan_jobs SET status = 'done', started_at = now()"))
        sql = (
            "INSERT INTO plan_jobs (id, plant_id, status, created_at, started_at) VALUES (:i, :p, 'done', now(), now())"
        )
        for i in range(60):
            c.execute(text(sql), {"i": f"x{i}", "p": first.json()["id"]})
    r = client.post("/api/plants", json={"species_id": "pyrus-communis", "standort_id": st["id"]}, headers=H)
    assert r.status_code == 201 and plan_jobs_count(db) == 61
