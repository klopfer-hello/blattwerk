"""AI name suggestions (M5, F-AI-3): only the typed name goes to Claude, the answer is
validated like user input, and picking a suggestion creates the species/Sorte once."""

import asyncio
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.ext.asyncio import create_async_engine

from blattwerk.claude_cli import ClaudeError
from blattwerk.names import build_prompt, sanitize
from blattwerk.worker import run_name_jobs
from tests.conftest import BASE, DATABASE_URL

H = {"Origin": BASE}

KIRSCHE = {"latin": "Prunus avium", "german": ["Süßkirsche", "Vogelkirsche"], "family": "Rosaceae", "growth": "baum",
           "woody": True, "cultivar": "Celeste", "form_hint": "Säule", "note": "Säulenkirsche"}  # fmt: skip
NEU = {"latin": "Lonicera kamtschatica", "german": ["Maibeere"], "family": "Caprifoliaceae", "growth": "strauch",
       "woody": True, "cultivar": "Duet", "form_hint": None, "note": ""}  # fmt: skip


def fake(result: dict[str, Any] | Exception, seen: list[str] | None = None) -> Any:
    async def run(prompt: str, system: str, schema: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        if seen is not None:
            seen.append(prompt)
        if isinstance(result, Exception):
            raise result
        return result, {"model": "claude-test", "cost_usd": 0.01, "duration_ms": 1}

    return run


def work(runner: Any, limit: int = 100) -> int:
    async def go() -> int:
        engine = create_async_engine(DATABASE_URL)
        try:
            return await run_name_jobs(engine, runner, daily_limit=limit)
        finally:
            await engine.dispose()

    return asyncio.run(go())


def ask(client: TestClient, q: str, answer: dict[str, Any] | Exception) -> dict[str, Any]:
    r = client.post("/api/species/ai", json={"q": q}, headers=H)
    assert r.status_code == 202, r.text
    work(fake(answer))
    return dict(client.get(f"/api/species/ai/{r.json()['job_id']}").json())


# ----- prompt and validation ----------------------------------------------------------


def test_prompt_is_only_the_typed_name() -> None:
    p = build_prompt("Maibeere Duet")
    assert "Maibeere Duet" in p and len(p) < 400


def test_sanitize_drops_invalid_candidates_and_bounds_the_list() -> None:
    bad = KIRSCHE | {"latin": "<script>"}
    weird = KIRSCHE | {"growth": "riesig"}
    found = sanitize({"candidates": [KIRSCHE, bad, weird, *[NEU] * 8]})
    assert [c.latin for c in found] == ["Prunus avium", *["Lonicera kamtschatica"] * 4]


def test_sanitize_needs_the_list() -> None:
    with pytest.raises(ClaudeError, match="unvollständig"):
        sanitize({"kandidaten": []})


def test_unknown_form_hint_is_dropped_not_the_candidate() -> None:
    assert sanitize({"candidates": [KIRSCHE | {"form_hint": "Riesenbaum"}]})[0].form_hint is None


# ----- flow -------------------------------------------------------------------------------


def test_known_species_is_marked_and_picking_creates_only_the_sorte(client: TestClient) -> None:
    res = ask(client, "Prunus AV. Celeste Säule", {"candidates": [KIRSCHE]})
    assert res["status"] == "done" and res["query"] == "Prunus AV. Celeste Säule"
    c = res["candidates"][0]
    assert c["known_species_id"] == "prunus-avium"
    r = client.post(f"/api/species/ai/{res['id']}/pick", json={"index": 0}, headers=H)
    assert r.status_code == 200, r.text
    picked = r.json()
    assert picked["species_id"] == "prunus-avium" and picked["cultivar_id"] and picked["form_hint"] == "Säule"
    cults = client.get("/api/species/prunus-avium").json()["cultivars"]
    assert "Celeste" in [x["name"] for x in cults]


def test_new_species_is_created_once_and_found_offline_afterwards(client: TestClient) -> None:
    res = ask(client, "Maibeere Duet", {"candidates": [NEU]})
    assert res["candidates"][0]["known_species_id"] is None
    for _ in range(2):  # picking twice is harmless
        r = client.post(f"/api/species/ai/{res['id']}/pick", json={"index": 0}, headers=H)
        assert r.status_code == 200 and r.json()["species_id"] == "lonicera-kamtschatica"
    sp = client.get("/api/species/lonicera-kamtschatica").json()
    assert sp["source"] == "user" and sp["family"] == "Caprifoliaceae" and sp["woody"] is True
    offline = client.get("/api/species/resolve", params={"q": "Maibeere"}).json()["candidates"]
    assert offline and offline[0]["species_id"] == "lonicera-kamtschatica"


def test_failed_job_says_why(client: TestClient) -> None:
    res = ask(client, "irgendwas", ClaudeError("Die KI hat nach 300 s nicht geantwortet."))
    assert res["status"] == "failed" and "300 s" in res["error"] and res["candidates"] == []


def test_pick_needs_a_done_job_and_a_valid_index(client: TestClient) -> None:
    res = ask(client, "Prunus AV. Celeste Säule", {"candidates": [KIRSCHE]})
    assert client.post(f"/api/species/ai/{res['id']}/pick", json={"index": 3}, headers=H).status_code == 404
    assert client.post("/api/species/ai/nope/pick", json={"index": 0}, headers=H).status_code == 404


@pytest.mark.parametrize("q", ["", "x", "a" * 201])
def test_query_is_bounded(client: TestClient, q: str) -> None:
    assert client.post("/api/species/ai", json={"q": q}, headers=H).status_code == 422


def test_daily_limit_is_told_when_asking(client: TestClient, db: Engine) -> None:
    with db.begin() as c:
        for i in range(100):
            c.execute(text("INSERT INTO name_jobs (id, query, status, candidates, created_at, started_at) "
                           "VALUES (:i, 'x', 'done', '[]', now(), now())"), {"i": f"n{i}"})  # fmt: skip
    assert client.post("/api/species/ai", json={"q": "Apfel"}, headers=H).status_code == 429


# ----- review findings ---------------------------------------------------------------


@pytest.mark.parametrize(
    "latin", ["Malus domestica Rhapsodie", "Prunus avium L.", "PRUNUS", "prunus avium", "Rosa Ghislaine de Feligonde"]
)
def test_only_real_botanical_names_pass(latin: str) -> None:
    assert sanitize({"candidates": [KIRSCHE | {"latin": latin}]}) == []


@pytest.mark.parametrize("latin", ["Rosa", "Prunus avium", "Prunus \u00d7 cistena", "Allium ampeloprasum var. porrum"])
def test_botanical_shapes_that_are_fine(latin: str) -> None:
    assert sanitize({"candidates": [KIRSCHE | {"latin": latin}]})[0].latin == latin


def test_woody_comes_from_the_known_genus_not_from_the_ai(client: TestClient) -> None:
    hedge_says_not_woody = NEU | {"latin": "Prunus laurocerasus", "german": ["Kirschlorbeer"], "woody": False,
                                  "growth": "baum", "cultivar": None}  # fmt: skip
    res = ask(client, "Kirschlorbeer", {"candidates": [hedge_says_not_woody]})
    sid = client.post(f"/api/species/ai/{res['id']}/pick", json={"index": 0}, headers=H).json()["species_id"]
    assert client.get(f"/api/species/{sid}").json()["woody"] is True  # Prunus is woody in the seed


def test_existing_species_found_by_id_reports_its_own_names(client: TestClient) -> None:
    porree = NEU | {
        "latin": "Allium porrum",
        "german": ["Porree"],
        "cultivar": None,
    }  # seed: A. ampeloprasum var. porrum
    res = ask(client, "Porree", {"candidates": [porree]})
    assert res["candidates"][0]["known_species_id"] == "allium-porrum"
    r = client.post(f"/api/species/ai/{res['id']}/pick", json={"index": 0}, headers=H).json()
    assert r["species_id"] == "allium-porrum" and r["latin"] == "Allium ampeloprasum var. porrum"


def test_queue_is_capped_and_same_query_reuses_the_open_job(client: TestClient) -> None:
    first = client.post("/api/species/ai", json={"q": "Apfel"}, headers=H).json()["job_id"]
    assert client.post("/api/species/ai", json={"q": "Apfel"}, headers=H).json()["job_id"] == first
    for i in range(4):
        assert client.post("/api/species/ai", json={"q": f"Birne {i}"}, headers=H).status_code == 202
    assert client.post("/api/species/ai", json={"q": "Kirsche"}, headers=H).status_code == 429


def test_old_queued_lookup_expires(client: TestClient, db: Engine) -> None:
    jid = client.post("/api/species/ai", json={"q": "Apfel"}, headers=H).json()["job_id"]
    with db.begin() as c:
        c.execute(text("UPDATE name_jobs SET created_at = now() - interval '1 hour'"))
    work(fake({"candidates": [KIRSCHE]}))
    assert client.get(f"/api/species/ai/{jid}").json()["status"] == "failed"


def test_jobs_wait_until_the_cli_is_installed() -> None:
    from blattwerk.worker import wait_ready

    ready = asyncio.Event()

    async def go() -> bool:
        task = asyncio.create_task(wait_ready(ready))
        await asyncio.sleep(0.05)
        waiting = not task.done()
        ready.set()
        await task
        return waiting

    assert asyncio.run(go())


def test_user_species_can_be_corrected_seed_species_not(client: TestClient) -> None:
    res = ask(client, "Maibeere Duet", {"candidates": [NEU]})
    sid = client.post(f"/api/species/ai/{res['id']}/pick", json={"index": 0}, headers=H).json()["species_id"]
    body = {"german": ["Maibeere", "Haskap"], "growth": "strauch", "woody": True}
    r = client.put(f"/api/species/{sid}", json=body, headers=H)
    assert r.status_code == 200 and r.json()["german"] == ["Maibeere", "Haskap"]
    assert client.put("/api/species/malus-domestica", json=body, headers=H).status_code == 409


def test_attempts_that_never_reached_claude_do_not_use_up_the_day(client: TestClient, db: Engine) -> None:
    with db.begin() as c:
        for i in range(100):
            c.execute(text("INSERT INTO name_jobs (id, query, status, candidates, created_at) "
                           "VALUES (:i, 'x', 'failed', '[]', now())"), {"i": f"f{i}"})  # fmt: skip
    assert client.post("/api/species/ai", json={"q": "Apfel"}, headers=H).status_code == 202


def test_hardiness_from_the_ai_is_kept_and_can_be_corrected(client: TestClient) -> None:
    res = ask(client, "Maibeere", {"candidates": [NEU | {"winterhaerte_c": -40}]})
    sid = client.post(f"/api/species/ai/{res['id']}/pick", json={"index": 0}, headers=H).json()["species_id"]
    assert client.get(f"/api/species/{sid}").json()["hardiness_c"] == -40
    body = {"german": ["Maibeere"], "growth": "strauch", "woody": True, "hardiness_c": -35}
    assert client.put(f"/api/species/{sid}", json=body, headers=H).json()["hardiness_c"] == -35
    assert client.get("/api/species/nerium-oleander").json()["hardiness_c"] == -5  # the seed has one


def test_odd_hardiness_from_the_ai_is_clamped_not_fatal() -> None:
    assert sanitize({"candidates": [KIRSCHE | {"winterhaerte_c": -50}]})[0].winterhaerte_c == -45
    assert sanitize({"candidates": [KIRSCHE | {"winterhaerte_c": "kalt"}]})[0].winterhaerte_c is None
