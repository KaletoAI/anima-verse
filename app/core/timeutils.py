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


def parse_iso(s: str) -> datetime:
    """ISO string -> timezone-aware datetime.

    Naive legacy data is interpreted as UTC (migration path: old timestamps were
    effectively UTC because the server ran on UTC). This is the key guard against
    "can't compare offset-naive and offset-aware" TypeErrors: every parsed stamp
    becomes aware before it is compared.
    """
    dt = datetime.fromisoformat(s)
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
