"""Season-driven tasks (M7b, F-WX-3): a yearly task can follow an indicator phase
("Rosenschnitt zur Forsythienblüte"); the month window stays the fallback, the legal
rules still apply, and an open to-do moves when the phase is reported later."""

from datetime import date, datetime, time, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from garten_planer.routes.todos import TZ, now
from garten_planer.schedule import TaskTiming, occurrences
from tests.conftest import BASE

H = {"Origin": BASE}


def timing(**kw: object) -> TaskTiming:
    base = {"recurrence": "yearly", "month_from": 3, "month_to": 4, "pheno_phase": "erstfruehling",
            "pheno_offset": 7, "pheno_window": 14}  # fmt: skip
    return TaskTiming(**(base | kw))  # type: ignore[arg-type]


def test_window_follows_the_phase() -> None:
    starts = {2026: date(2026, 3, 20)}
    [o] = occurrences(timing(), date(2026, 3, 1), phase_start=starts.get)
    assert (o.period, o.due_from, o.due_to) == ("2026", date(2026, 3, 27), date(2026, 4, 10))


def test_without_a_phase_date_the_month_window_is_used() -> None:
    [o] = occurrences(timing(), date(2026, 3, 1), phase_start=lambda _y: None)
    assert (o.due_from, o.due_to) == (date(2026, 3, 1), date(2026, 4, 30))


def test_negative_offset_means_before_the_phase() -> None:
    [o] = occurrences(
        timing(pheno_offset=-10, pheno_window=7), date(2026, 3, 1), phase_start={2026: date(2026, 3, 20)}.get
    )
    assert (o.due_from, o.due_to) == (date(2026, 3, 10), date(2026, 3, 17))


# ----- API ----------------------------------------------------------------------------------------


def on(client: TestClient, day: date) -> None:
    client.app.dependency_overrides[now] = lambda: datetime.combine(day, time(10), TZ)  # type: ignore[attr-defined]


def phase(db: Engine, key: str, day: date, source: str = "dwd") -> None:
    with db.begin() as c:
        c.execute(text("INSERT INTO pheno_events (year, phase, source, day, reports, updated_at) "
                       "VALUES (:y, :p, :s, :d, 3, now()) ON CONFLICT (year, phase, source) DO UPDATE SET day = :d"),
                  {"y": day.year, "p": key, "s": source, "d": day})  # fmt: skip


def rose_task(client: TestClient) -> dict[str, object]:
    body = {"title": "Rosen schneiden", "category": "schnitt", "cut_type": "pflege", "recurrence": "yearly",
            "month_from": 3, "month_to": 4, "pheno_phase": "erstfruehling", "pheno_offset": 0,
            "pheno_window": 14}  # fmt: skip
    r = client.post("/api/tasks", json=body, headers=H)
    assert r.status_code == 201, r.text
    return dict(r.json())


def test_task_api_keeps_the_trigger_and_heute_follows_the_phase(client: TestClient, db: Engine) -> None:
    on(client, date(2026, 3, 18))
    phase(db, "erstfruehling", date(2026, 3, 16))
    t = rose_task(client)
    assert t["pheno_phase"] == "erstfruehling" and t["pheno_window"] == 14
    open_ = client.get("/api/todos/heute").json()["open"]
    assert [(x["due_from"], x["due_to"]) for x in open_] == [("2026-03-16", "2026-03-30")]


def test_open_todo_moves_when_the_phase_is_reported_later(client: TestClient, db: Engine) -> None:
    on(client, date(2026, 3, 2))
    rose_task(client)  # no phase yet: month window
    assert client.get("/api/todos/heute").json()["open"][0]["due_from"] == "2026-03-01"
    phase(db, "erstfruehling", date(2026, 3, 25))
    on(client, date(2026, 3, 26))
    got = client.get("/api/todos/heute").json()["open"]
    assert [(x["due_from"], x["due_to"]) for x in got] == [("2026-03-25", "2026-04-08")]


def test_own_observation_counts_for_the_tasks(client: TestClient, db: Engine) -> None:
    on(client, date(2026, 3, 18))
    phase(db, "erstfruehling", date(2026, 3, 20))
    phase(db, "erstfruehling", date(2026, 3, 12), source="garten")
    rose_task(client)
    assert client.get("/api/todos/heute").json()["open"][0]["due_from"] == "2026-03-12"


def test_trigger_needs_a_yearly_task(client: TestClient) -> None:
    body = {"title": "x", "category": "sonstiges", "recurrence": "once", "due_date": "2026-05-01",
            "pheno_phase": "erstfruehling"}  # fmt: skip
    assert client.post("/api/tasks", json=body, headers=H).status_code == 422


def test_strong_cut_at_a_summer_phase_is_still_moved_by_the_law(client: TestClient, db: Engine) -> None:
    on(client, date(2026, 6, 1))
    phase(db, "fruehsommer", date(2026, 6, 1))
    st = client.post("/api/standorte", json={"name": "Nord", "light": "sonnig", "type": "hecke"}, headers=H).json()
    pid = client.post(
        "/api/plants", json={"species_id": "carpinus-betulus", "standort_id": st["id"]}, headers=H
    ).json()["id"]
    body = {"title": "Hecke verjüngen", "category": "schnitt", "cut_type": "stark", "recurrence": "yearly",
            "month_from": 6, "month_to": 6, "pheno_phase": "fruehsommer", "plant_id": pid}  # fmt: skip
    assert client.post("/api/tasks", json=body, headers=H).status_code == 201
    assert client.get("/api/todos/heute").json()["open"] == []  # § 39: not in June


# ----- plans and alerts ------------------------------------------------------------------------------


def test_plan_task_keeps_its_trigger_and_bad_triggers_are_ignored() -> None:
    from garten_planer.plan import sanitize
    from tests.test_plan import answer

    tasks = answer()["tasks"]
    tasks[0] |= {"pheno_phase": "erstfruehling", "pheno_offset": 3}
    tasks[2] |= {"pheno_phase": "erstfruehling", "pheno_offset": None, "recurrence": "interval", "interval_days": 30}
    plan = sanitize(answer(tasks=tasks))
    assert (plan.tasks[0].pheno_phase, plan.tasks[0].pheno_offset) == ("erstfruehling", 3)
    assert plan.tasks[2].pheno_phase is None


def test_late_frost_starts_with_the_apple_blossom() -> None:
    from garten_planer.alerts import Hour, detect

    now = datetime(2026, 4, 8, 12, tzinfo=TZ)
    hours = [Hour(now + timedelta(hours=i), 1.0 if i != 14 else -0.5, 1.0, 10.0) for i in range(40)]
    assert detect(hours, now) == []  # before 15 April, -0.5 °C is no alert
    assert [e.kind for e in detect(hours, now, late_from=date(2026, 4, 5))] == ["late_frost"]  # blossom came early


# ----- re-review ----------------------------------------------------------------------------------------


def test_postponed_todo_stays_where_the_user_put_it(client: TestClient, db: Engine) -> None:
    on(client, date(2026, 3, 18))
    phase(db, "erstfruehling", date(2026, 3, 16))
    rose_task(client)
    tid = client.get("/api/todos/heute").json()["open"][0]["id"]
    assert client.post(f"/api/todos/{tid}/postpone", json={"to": "2026-03-25"}, headers=H).status_code == 200
    phase(db, "erstfruehling", date(2026, 3, 17))  # the region date moves a little
    got = client.get("/api/todos/heute").json()["open"][0]
    assert (got["due_from"], got["due_to"]) == ("2026-03-25", "2026-03-25")


def test_late_frost_date_of_this_year_does_not_reach_into_january() -> None:
    from garten_planer.alerts import Hour, detect

    now = datetime(2026, 12, 31, 12, tzinfo=TZ)
    hours = [Hour(now + timedelta(hours=i), 1.0 if i != 16 else -0.5, 1.0, 10.0) for i in range(40)]
    assert detect(hours, now, late_from=date(2026, 4, 20)) == []  # 1 January: no "Spätfrost"


def test_one_report_alone_does_not_move_the_tasks(client: TestClient, db: Engine) -> None:
    on(client, date(2026, 3, 2))
    with db.begin() as c:
        c.execute(text("INSERT INTO pheno_events (year, phase, source, day, reports, updated_at) "
                       "VALUES (2026, 'erstfruehling', 'dwd', '2026-02-10', 1, now())"))  # fmt: skip
    rose_task(client)
    assert client.get("/api/todos/heute").json()["open"][0]["due_from"] == "2026-03-01"  # month window


def test_bad_plan_trigger_drops_only_the_trigger() -> None:
    from garten_planer.plan import sanitize
    from tests.test_plan import answer

    tasks = answer()["tasks"]
    tasks[0] |= {"pheno_phase": "sommer", "pheno_offset": 3}
    tasks[1] |= {"pheno_phase": "winter", "pheno_offset": 500, "pheno_window": 0}
    plan = sanitize(answer(tasks=tasks))
    assert len(plan.tasks) == 3 and plan.tasks[0].pheno_phase is None
    assert (plan.tasks[1].pheno_offset, plan.tasks[1].pheno_window) == (120, 1)
