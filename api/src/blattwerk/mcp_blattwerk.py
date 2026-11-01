"""MCP server `garten` (M8, F-AI-4): the garden chat's only tools, over stdio. The
Claude CLI in the worker starts it for one answer (--mcp-config, --strict-mcp-config,
--allowedTools mcp__blattwerk__*); BW_CHAT_MESSAGE_ID ties proposals to that answer.

Read tools and two "vorschlagen" tools; nothing here writes the garden, deletes or
reaches the network except Postgres and InfluxDB. The logic lives in blattwerk_tools.py."""

import os
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from blattwerk import blattwerk_tools as gt
from blattwerk.config import Config
from blattwerk.influx import from_config
from blattwerk.routes.todos import TZ
from blattwerk.weather import FETCHED_SQL, HA_SQL, fc_sql, summarise
from blattwerk.wetterwacht import active_alerts

INSTRUCTIONS = (
    "Werkzeuge für den Garten des Nutzers. Erst ueberblick aufrufen, um Pflanzen-IDs zu kennen. "
    "Aufgaben oder Notizen nie behaupten anzulegen: nur vorschlagen; der Nutzer bestätigt in der App."
)

_engine: AsyncEngine | None = None


def _db() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_async_engine(Config().database_url.get_secret_value())
    return _engine


def _today() -> Any:
    return datetime.now(TZ).date()


async def _read(fn: Any, *args: Any) -> dict[str, Any]:
    async with _db().connect() as c:
        result: dict[str, Any] = await fn(c, *args)
        return result


async def _write(fn: Any, *args: Any) -> dict[str, Any]:
    async with _db().begin() as c:
        result: dict[str, Any] = await fn(c, *args)
        return result


def build() -> Any:
    from mcp.server.mcpserver import MCPServer

    server = MCPServer(name="blattwerk", instructions=INSTRUCTIONS)
    message_id = os.environ.get("BW_CHAT_MESSAGE_ID", "")

    @server.tool(description="Überblick: Datum, Bundesland, Jahreszeit, Standorte mit ihren Pflanzen (IDs).")
    async def ueberblick() -> dict[str, Any]:
        return await _read(gt.ueberblick, _today())

    @server.tool(description="Eine Pflanze: Art, Sorte, Form, Alter, Pflegeplan, Schädlinge und Aufgaben.")
    async def pflanze(pflanze_id: str) -> dict[str, Any]:
        return await _read(gt.pflanze, pflanze_id, _today())

    @server.tool(description="Aufgaben dieses Monats: offen (fällig, dringend, überfällig) und erledigt.")
    async def aufgaben() -> dict[str, Any]:
        return await _read(gt.aufgaben, _today())

    @server.tool(description="Phänologische Jahreszeit: aktuelle Phase, Verspätung gegen das Mittel, nächste Phasen.")
    async def jahreszeit() -> dict[str, Any]:
        return await _read(gt.jahreszeit, _today())

    @server.tool(description="Erledigte Aufgaben und gespeicherte Diagnosen einer Pflanze (neueste zuerst).")
    async def verlauf(pflanze_id: str) -> dict[str, Any]:
        return await _read(gt.verlauf, pflanze_id)

    @server.tool(description="Wetter: Messwerte im Garten, Vorhersage der nächsten Tage, aktive Wetterwarnungen.")
    async def wetter() -> dict[str, Any]:
        now = datetime.now(TZ)
        async with _db().connect() as c:
            warnings = await active_alerts(c, now.date())
        db = from_config(Config())
        if db is None:
            return {"verfuegbar": False, "warnungen": warnings}
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        try:
            s = summarise(await db.query(HA_SQL), await db.query(fc_sql(midnight)), now, await db.query(FETCHED_SQL))
        except Exception:  # weather is optional for an answer
            return {"verfuegbar": False, "warnungen": warnings}
        return {"verfuegbar": True, "jetzt": s["current"], "tage": s["days"], "veraltet": s["stale"],
                "warnungen": warnings}  # fmt: skip

    @server.tool(description=(
        "Eine einmalige Aufgabe VORSCHLAGEN (der Nutzer bestätigt in der App). datum: JJJJ-MM-TT; "
        "kategorie: schnitt, duengen, ernte, pflanzenschutz, winterschutz, aussaat oder sonstiges; bei schnitt "
        "schnitt_art: pflege (Form-/Erhaltungsschnitt) oder stark (Verjüngung, auf den Stock, Roden). "
        "Keine Gießaufgaben."
    ))  # fmt: skip
    async def aufgabe_vorschlagen(
        titel: str, datum: str, anleitung: str = "", pflanze_id: str | None = None, kategorie: str = "sonstiges",
        schnitt_art: str = "stark",
    ) -> dict[str, Any]:  # fmt: skip
        return await _write(gt.aufgabe_vorschlagen, message_id, titel, datum, pflanze_id, anleitung, kategorie,
                            schnitt_art)  # fmt: skip

    @server.tool(description="Eine Notiz zu einer Pflanze VORSCHLAGEN (der Nutzer bestätigt in der App).")
    async def notiz_vorschlagen(pflanze_id: str, text: str) -> dict[str, Any]:
        return await _write(gt.notiz_vorschlagen, message_id, pflanze_id, text)

    @server.tool(description=(
        "Eine Diagnose nach Fotos VORSCHLAGEN (der Nutzer speichert sie in der App im Verlauf der Pflanze). "
        "befund: kurz, z. B. 'Echter Mehltau'; sicherheit: 'ziemlich sicher' oder 'sicher'; ursache: kurz. "
        "Nur wenn du dir wirklich ziemlich sicher bist, sonst nachfragen (anderes Foto, Blattunterseite)."
    ))  # fmt: skip
    async def diagnose_vorschlagen(pflanze_id: str, befund: str, sicherheit: str, ursache: str = "") -> dict[str, Any]:
        return await _write(gt.diagnose_vorschlagen, message_id, pflanze_id, befund, sicherheit, ursache)

    return server


if __name__ == "__main__":
    build().run("stdio")
