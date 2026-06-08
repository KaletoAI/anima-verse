"""Central UTC time helpers.

Server stores/sends timezone-aware UTC ISO strings (``…+00:00``); the frontend
converts to local time. Works regardless of the server's timezone.
"""

from datetime import datetime, timezone


def utc_now() -> datetime:
    """Current time as a timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


def utc_now_iso(timespec: str = "seconds") -> str:
    """Current UTC time as an ISO string with a +00:00 offset."""
    return datetime.now(timezone.utc).isoformat(timespec=timespec)


def _world_tz():
    """Konfigurierte Welt-Zeitzone (``server.timezone``, IANA-Name). Steuert die
    *Anzeige*-/Welt-Uhr + Tagesgrenzen — NICHT die Speicherung (die bleibt UTC).
    Fallback UTC, wenn nicht gesetzt / ungültig."""
    try:
        from app.core import config
        name = (config.get("server.timezone") or "").strip()
        if name:
            from zoneinfo import ZoneInfo
            return ZoneInfo(name)
    except Exception:
        pass
    return timezone.utc


def local_now() -> datetime:
    """Aktuelle Zeit in der konfigurierten Welt-Zeitzone (aware). Für die Welt-Uhr
    im Prompt + Tagesgrenzen. Speicherung nutzt weiterhin ``utc_now()``."""
    return datetime.now(timezone.utc).astimezone(_world_tz())


def to_local(dt: datetime) -> datetime:
    """UTC-(oder beliebig-aware-)Stempel → konfigurierte Welt-Zeitzone."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_world_tz())


def parse_iso(s: str) -> datetime:
    """ISO string -> timezone-aware datetime.

    Naive legacy data is interpreted as UTC (migration path: old timestamps were
    effectively UTC because the server ran on UTC). This is the key guard against
    "can't compare offset-naive and offset-aware" TypeErrors: every parsed stamp
    becomes aware before it is compared.
    """
    dt = datetime.fromisoformat(s)
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
