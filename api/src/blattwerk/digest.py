"""When the push digest is due and what it says (pure). Settings: daily or
weekly (weekday 0 = Monday) at HH:MM garden-local time, or off; at most once a
day. The text lists up to three titles."""

from datetime import date, datetime


def digest_due(at: datetime, mode: str, hhmm: str, weekday: int, last_sent: date | None) -> bool:
    if mode == "off" or last_sent == at.date():
        return False
    if mode == "weekly" and at.weekday() != weekday:
        return False
    hour, minute = (int(x) for x in hhmm.split(":"))
    return (at.hour, at.minute) >= (hour, minute)


def digest_text(titles: list[str]) -> tuple[str, str]:
    n = len(titles)
    if n == 1:
        return "Neue Aufgabe im Garten", titles[0]
    if n <= 3:
        return f"{n} neue Aufgaben im Garten", ", ".join(titles[:-1]) + " und " + titles[-1]
    return f"{n} neue Aufgaben im Garten", ", ".join(titles[:3]) + f" und {n - 3} weitere"
