"""UI smoke test (/ui-smoke, ticket 004): an invented demo garden through the API, then every
screen at phone and desktop sizes. Fails on console errors, page errors, failed API calls
and horizontal scrolling; reports touch targets under 44 px. Screenshots go to ./out
(gitignored). All data here is made up: no real garden, place or person."""

import json
import os
import struct
import sys
import time
import urllib.request
import zlib
from datetime import date
from pathlib import Path

from playwright.sync_api import ConsoleMessage, Page, Response, sync_playwright

BASE = os.environ.get("BASE", "http://localhost:8080")
OUT = Path(__file__).parent / "out"
SIZES = {"iphone": (390, 844), "android": (412, 915), "desktop": (1280, 900)}
MIN_TARGET = 44


def api(method: str, path: str, body: object | None = None) -> object:
    req = urllib.request.Request(
        f"{BASE}/api{path}", method=method, data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json", "Origin": BASE},
    )  # fmt: skip
    with urllib.request.urlopen(req, timeout=20) as r:  # noqa: S310 - the local smoke stack
        raw = r.read()
    return json.loads(raw) if raw else None


def wait_for_api() -> None:
    for _ in range(60):
        try:
            api("GET", "/healthz")
            return
        except Exception:
            time.sleep(1)
    sys.exit("api did not come up")


def seed() -> dict[str, str]:
    """An invented garden: four Standorte, four plants, a few tasks (one due, one urgent)."""
    s = api("GET", "/settings")
    assert isinstance(s, dict)
    s["location"] = {"ort": None, "plz": None, "bundesland": "Bayern"}
    api("PUT", "/settings", s)
    sites = {}
    for name, light, typ in (("Beet am Zaun", "sonnig", "beet"), ("Hecke Nord", "halbschattig", "hecke"),
                             ("Terrasse", "sonnig", "kuebelplatz"), ("Gewächshaus", "sonnig", "gewaechshaus"),
                             ("Wohnzimmer", "halbschattig", "zimmer")):  # fmt: skip
        windows = ["O"] if typ == "zimmer" else []
        sites[typ] = api("POST", "/standorte", {"name": name, "light": light, "type": typ, "windows": windows,
                                                "notes": ""})["id"]  # type: ignore[index]
    plants = {}
    for key, body in {
        "apfel": {"species_id": "malus-domestica", "standort_id": sites["beet"], "form": "Spindel", "planted_year": 2020},
        "hecke": {"species_id": "carpinus-betulus", "standort_id": sites["hecke"], "form": "Hecke"},
        "kuebel": {"species_id": "malus-domestica", "standort_id": sites["kuebelplatz"], "in_container": True,
                   "nickname": "Säulenapfel Terrasse"},
        "zimmer": {"species_id": "monstera-deliciosa", "standort_id": sites["zimmer"],
                   "window_distance": "bis_1m", "pot_cm": 24, "pot_material": "kunststoff", "height_cm": 60},
    }.items():  # fmt: skip
        plants[key] = api("POST", "/plants", body)["id"]  # type: ignore[index]
    m = date.today().month
    tasks = [
        {"title": "Leimringe prüfen", "category": "pflanzenschutz", "recurrence": "yearly", "month_from": m, "month_to": m,
         "plant_id": plants["apfel"], "instructions": "1. Ring abtasten.\n2. Bei Bedarf erneuern."},
        {"title": "Kübel mit Vlies umwickeln", "category": "winterschutz", "recurrence": "once",
         "due_date": date.today().isoformat(), "urgent": True, "plant_id": plants["kuebel"]},
        {"title": "Hecke in Form schneiden", "category": "schnitt", "cut_type": "pflege", "recurrence": "yearly",
         "month_from": 6, "month_to": 6, "plant_id": plants["hecke"]},
        {"title": "Rosen schneiden", "category": "schnitt", "cut_type": "pflege", "recurrence": "yearly",
         "month_from": 3, "month_to": 4, "pheno_phase": "erstfruehling"},
        {"title": "Gießen", "category": "giessen", "recurrence": "interval", "interval_days": 7,
         "winter_interval_days": 10, "amount_ml": 300, "plant_id": plants["zimmer"], "instructions": "Obere 2 cm trocken? Dann gießen."},
        {"title": "Blätter abstauben", "category": "entstauben", "recurrence": "interval", "interval_days": 45,
         "plant_id": plants["zimmer"]},
    ]  # fmt: skip
    for t in tasks:
        api("POST", "/tasks", t)
    req = urllib.request.Request(f"{BASE}/api/photos", method="POST", data=noise_png(400, 300),
                                 headers={"Content-Type": "image/png", "Origin": BASE})  # fmt: skip
    with urllib.request.urlopen(req, timeout=20) as r:  # noqa: S310 - the local smoke stack
        pid = json.loads(r.read())["id"]
    chat = api("POST", "/chats", {"text": "Flecken auf dem Blatt?", "photo_ids": [pid], "plant_id": plants["apfel"]})
    return {"plant": plants["apfel"], "chat": chat["chat_id"], "zimmer": plants["zimmer"]}  # type: ignore[index]


def screens(ids: dict[str, str]) -> dict[str, tuple[str, str]]:
    """name -> (hash, a text the screen must show)"""
    return {
        "heute": ("#/heute", "ToDos im"), "kalender": ("#/kalender", "Kalender"),
        "pflanzen": ("#/pflanzen", "Pflanzen"), "pflanze": (f"#/pflanze/{ids['plant']}", "Apfel"),
        "neu": ("#/neu", "Pflanze hinzufügen"), "aufgabe-neu": ("#/aufgabe-neu", "Neue Aufgabe"),
        "fragen": ("#/fragen", "Fragen"), "mehr": ("#/mehr", "Mehr"), "wetter": ("#/wetter", "Wetter"),
        "einstellungen": ("#/einstellungen", "Einstellungen"), "standorte": ("#/standorte", "Standorte"),
        "warnung": ("#/warnung", "Wetterwarnungen"),
        "pflanze-krank": (f"#/fragen-pflanze/{ids['plant']}", "Pflanze krank?"),
        "chat-foto": (f"#/fragen/{ids['chat']}", "Flecken auf dem Blatt?"),
        "zimmerpflanze": (f"#/pflanze/{ids['zimmer']}", "Fenster"),
        "zimmerpflanze-bearbeiten": (f"#/pflanze/{ids['zimmer']}/bearbeiten", "Abstand zum Fenster"),
    }  # fmt: skip


def check(page: Page, name: str, size: str, must: str, problems: list[str], notes: list[str]) -> None:
    page.wait_for_load_state("networkidle")
    try:  # data arrives after the first paint
        page.wait_for_function("t => document.querySelector('main').innerText.includes(t)", arg=must, timeout=8000)
    except Exception:
        problems.append(f"{size}/{name}: text '{must}' missing")
    over = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
    if over > 1:
        problems.append(f"{size}/{name}: scrolls sideways by {over}px")
    if size != "desktop":
        small = page.evaluate(f"""[...document.querySelectorAll('button, a, input, select, [role=switch]')]
            .filter(e => e.offsetParent !== null).map(e => [e, e.getBoundingClientRect()])
            .filter(([e, r]) => r.height > 0 && r.height < {MIN_TARGET} && !e.closest('nav'))
            .map(([e, r]) => (e.innerText || e.getAttribute('aria-label') || e.tagName).trim().slice(0, 30) + ' ' + Math.round(r.height) + 'px')""")
        notes += [f"{size}/{name}: small target {t}" for t in small]
    page.screenshot(path=str(OUT / f"{size}-{name}.png"), full_page=True)


def noise_png(w: int = 1200, h: int = 900) -> bytes:
    """Random pixels: the shrunk JPEG stays large (hundreds of KB), like a detailed leaf photo."""
    raw = b"".join(b"\x00" + os.urandom(w * 3) for _ in range(h))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    head = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", head) + chunk(b"IDAT", zlib.compress(raw, 1)) + chunk(b"IEND", b"")


def photo(page: Page, size: str, problems: list[str]) -> None:
    """The camera button's file input: shrink in the browser, upload through nginx, thumbnail shown."""
    page.set_input_files("input[type=file]", files=[{"name": "blatt.png", "mimeType": "image/png", "buffer": noise_png()}])
    try:
        page.wait_for_selector("img[alt='Foto 1']", timeout=15000)
    except Exception:
        problems.append(f"{size}/pflanze-krank: photo upload shows no thumbnail")
    page.screenshot(path=str(OUT / f"{size}-pflanze-krank-foto.png"), full_page=True)


def large_view(page: Page, size: str, problems: list[str]) -> None:
    """A sent photo opens large inside the app and closes again (no new window: no way back in the PWA)."""
    page.get_by_role("button", name="Foto 1 groß ansehen").click()
    try:
        page.wait_for_selector("[role=dialog] img", timeout=5000)
        page.screenshot(path=str(OUT / f"{size}-chat-foto-gross.png"))
        page.get_by_role("button", name="Schließen").click()
        page.wait_for_selector("[role=dialog]", state="detached", timeout=5000)
    except Exception:
        problems.append(f"{size}/chat-foto: large view does not open or close")


def done_now(page: Page, problems: list[str]) -> None:
    """Plant page: "Heute gemacht" on a task closes its next to-do and restarts the rhythm."""
    try:
        page.get_by_role("button", name="Heute gemacht").first.click()
        page.wait_for_function("() => document.querySelector('main').innerText.includes('heute erledigt')", timeout=8000)
        page.screenshot(path=str(OUT / "iphone-zimmerpflanze-heute.png"), full_page=True)
    except Exception:
        problems.append("iphone/zimmerpflanze: 'Heute gemacht' does not work")


def edit_room(page: Page, problems: list[str]) -> None:
    """Standorte: "Bearbeiten" on the last card opens its form right there (not off-screen at the top)."""
    try:
        page.get_by_role("button", name="Bearbeiten").last.click()
        name = page.locator("#sn")  # the form's first field
        name.wait_for(timeout=5000)
        page.wait_for_timeout(600)  # smooth scroll
        top = page.evaluate("e => e.getBoundingClientRect().top", name.element_handle())
        if not 0 <= top < page.viewport_size["height"]:
            problems.append(f"iphone/standorte: the edit form opens outside the screen (top {top:.0f}px)")
        page.screenshot(path=str(OUT / "iphone-standorte-bearbeiten.png"))
        page.get_by_role("button", name="Abbrechen").click()
    except Exception:
        problems.append("iphone/standorte: 'Bearbeiten' does not open a form")


def soil(page: Page, problems: list[str]) -> None:
    """Indoor watering: tick it off, answer how the soil was (the rhythm adapts)."""
    try:
        page.get_by_role("checkbox", name="Gießen: erledigt").click()
        page.get_by_role("button", name="passt").click()
        page.wait_for_function("() => document.querySelector('main').innerText.includes('Erde vorher: passt')", timeout=8000)
        page.screenshot(path=str(OUT / "iphone-heute-giessen.png"), full_page=True)
    except Exception:
        problems.append("iphone/heute: watering with soil feedback does not work")


def main() -> None:
    OUT.mkdir(exist_ok=True)
    wait_for_api()
    ids = seed()
    problems: list[str] = []
    notes: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for size, (w, h) in SIZES.items():
            ctx = browser.new_context(viewport={"width": w, "height": h}, is_mobile=size != "desktop",
                                      has_touch=size != "desktop", locale="de-DE", timezone_id="Europe/Berlin")  # fmt: skip
            ctx.add_init_script("try { localStorage.setItem('blattwerk-welcomed-v2', '1') } catch (e) {}")
            page = ctx.new_page()
            current = {"name": ""}

            def on_console(m: ConsoleMessage, current: dict[str, str] = current, size: str = size) -> None:
                if m.type == "error":
                    problems.append(f"{size}/{current['name']}: console error: {m.text[:160]}")

            def on_response(r: Response, current: dict[str, str] = current, size: str = size) -> None:
                if "/api/" in r.url and r.status >= 400:
                    problems.append(f"{size}/{current['name']}: {r.status} {r.url.split('/api', 1)[1][:60]}")

            page.on("console", on_console)
            page.on("pageerror", lambda e, size=size, current=current: problems.append(f"{size}/{current['name']}: {e}"))
            page.on("response", on_response)
            for name, (path, must) in screens(ids).items():
                current["name"] = name
                page.goto(f"{BASE}/{path}")
                check(page, name, size, must, problems, notes)
                if name == "pflanze-krank":
                    photo(page, size, problems)
                if name == "chat-foto":
                    large_view(page, size, problems)
                if name == "standorte" and size == "iphone":
                    edit_room(page, problems)
                if name == "heute" and size == "iphone":
                    soil(page, problems)
                if name == "zimmerpflanze" and size == "iphone":
                    done_now(page, problems)
            ctx.close()
        browser.close()
    for n in sorted(set(notes)):
        print("note:", n)
    for pr in problems:
        print("FAIL:", pr)
    print(f"\n{len(SIZES) * len(screens(ids))} screens, {len(problems)} problems, {len(set(notes))} notes; screenshots in scripts/smoke/out/")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
