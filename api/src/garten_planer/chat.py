"""Garden chat (M8, F-AI-4): the system prompt, the prompt with the conversation so far,
and the CLI's stream-json events. Our own history in Postgres is the conversation
memory (no CLI sessions), so every answer sees at most HISTORY earlier messages."""

from typing import Any

HISTORY = 12
MAX_QUESTION = 2000
SYSTEM = """Du bist der Gartenplaner der Familie: ein erfahrener Gärtner für einen Hausgarten in Deutschland.
Antworte auf Deutsch, kurz und für das Handy (wenige Sätze oder eine kurze Liste), konkret für DIESEN Garten.

- Nutze die Werkzeuge des Servers "garten": erst garten_ueberblick, dann je nach Frage pflanze, aufgaben, wetter,
  jahreszeit oder verlauf. Erfinde keine Pflanzen, Termine oder Messwerte; wenn Daten fehlen, sag es.
- Termine an Jahreszeit, Wetter und Recht ausrichten: starke Schnitte an Gehölzen nur 1.10.-28.2. (§ 39 BNatSchG),
  Brutvögel schonen. Keine Gießaufgaben vorschlagen (der Garten wird nicht über die App gegossen).
- Wenn eine Aufgabe oder Notiz hilft, schlage sie mit aufgabe_vorschlagen / notiz_vorschlagen vor und sag dem
  Nutzer, dass er sie unten bestätigen kann. Behaupte nie, etwas angelegt oder gelöscht zu haben.
- Pflanzenschutz: zuerst mechanisch/biologisch, Mittel nur mit Zulassung für Haus- und Kleingarten.
- Keine Fragen nach Wohnort oder persönlichen Daten."""


def build_prompt(history: list[tuple[str, str]], question: str) -> str:
    """`history`: earlier (role, text) pairs, oldest first."""
    lines = []
    for role, text in history[-HISTORY:]:
        lines.append(f"{'Nutzer' if role == 'user' else 'Gartenplaner'}: {text}")
    prior = "Bisheriges Gespräch:\n" + "\n\n".join(lines) + "\n\n" if lines else ""
    return f"{prior}Neue Frage des Nutzers:\n{question}"


NARRATION = 120  # a turn this short before a tool call is "Ich schaue nach …", not part of the answer


def final_answer(text: str, mark: str) -> str:
    """The stored answer: every turn with substance plus the last one; short narration before
    a tool call is left out (the answer often comes first, then a proposal, then "steht bereit")."""
    turns = [t.strip() for t in text.split(mark)]
    keep = [t for i, t in enumerate(turns) if t and (i == len(turns) - 1 or len(t) >= NARRATION)]
    return "\n\n".join(keep).strip()


def parse_event(e: dict[str, Any]) -> tuple[str, Any] | None:
    """One line of `claude -p --output-format stream-json --include-partial-messages`:
    ("text", delta), ("turn", "") when a new assistant message starts (after a tool call),
    ("result", event) at the end; None for everything else (init, tool use, ...)."""
    kind = e.get("type")
    if kind == "result":
        return "result", e
    if kind != "stream_event":
        return None
    ev = e.get("event") or {}
    if ev.get("type") == "message_start":
        return "turn", ""
    delta = ev.get("delta") or {}
    if ev.get("type") == "content_block_delta" and delta.get("type") == "text_delta":
        return "text", str(delta.get("text", ""))
    return None
