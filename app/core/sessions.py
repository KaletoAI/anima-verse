"""Session management (multiuser phase 1).

Server-side sessions with opaque tokens. The tokens live in the DB, the browser
only ever gets the token as an HttpOnly cookie.

TTL: sliding expiration — activity extends the session by SESSION_TTL_HOURS.
Both halves have to slide: the DB row (``get_session``) AND the browser cookie,
which is re-issued by the caller whenever ``get_session`` reports a refresh —
otherwise the browser drops the credential exactly SESSION_TTL_HOURS after
login, mid-session. The DB write is throttled to SLIDE_THROTTLE_SECONDS so
short-interval polling does not hammer world.db on every request.
"""
import secrets
from datetime import datetime, timedelta

from app.core.timeutils import parse_iso, utc_now
from typing import Optional, Dict, Any, Tuple

from app.core.db import get_connection, transaction
from app.core.log import get_logger

logger = get_logger("sessions")


SESSION_COOKIE_NAME = "av_session"
SESSION_TTL_HOURS = 24
# Only slide the DB row (and re-issue the cookie) once per minute — the play UI
# polls every few seconds, and every slide is a write to world.db.
SLIDE_THROTTLE_SECONDS = 60


def _now() -> datetime:
    return utc_now()


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def set_session_cookie(response, token: str) -> None:
    """Writes the session cookie onto a response (login AND every slide).

    Lives here, not in the auth route, because the middleware re-issues the
    cookie on sliding refresh and core must not import routes.
    """
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=SESSION_TTL_HOURS * 3600,
        httponly=True,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response) -> None:
    """Removes the session cookie (logout)."""
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")


def create_session(user_id: str) -> str:
    """Creates a new session and returns its token."""
    token = secrets.token_urlsafe(32)
    now = _now()
    expires = now + timedelta(hours=SESSION_TTL_HOURS)
    with transaction() as conn:
        conn.execute(
            "INSERT INTO user_sessions (token, user_id, created_at, expires_at, "
            "last_activity) VALUES (?, ?, ?, ?, ?)",
            (token, user_id, _iso(now), _iso(expires), _iso(now)),
        )
    return token


def get_session(token: str) -> Tuple[Optional[Dict[str, Any]], bool]:
    """Loads the session if the token is valid, sliding the TTL.

    Returns ``(session, refreshed)``. ``refreshed`` is True when this call
    actually slid the row — the caller then has to re-issue the browser cookie
    so client and server expiry stay in sync.
    """
    if not token:
        return None, False
    conn = get_connection()
    row = conn.execute(
        "SELECT token, user_id, created_at, expires_at, last_activity "
        "FROM user_sessions WHERE token=?",
        (token,),
    ).fetchone()
    if not row:
        return None, False

    now = _now()
    expires = parse_iso(row["expires_at"])
    if now >= expires:
        # Expired — clean up.
        delete_session(token)
        return None, False

    # Sliding, throttled: only extend once the last slide is old enough.
    try:
        age = (now - parse_iso(row["last_activity"])).total_seconds()
    except (TypeError, ValueError):
        age = SLIDE_THROTTLE_SECONDS + 1  # unreadable stamp -> refresh it
    if age < SLIDE_THROTTLE_SECONDS:
        return dict(row), False

    new_expires = now + timedelta(hours=SESSION_TTL_HOURS)
    with transaction() as conn:
        conn.execute(
            "UPDATE user_sessions SET last_activity=?, expires_at=? WHERE token=?",
            (_iso(now), _iso(new_expires), token),
        )
    return dict(row), True


def delete_session(token: str) -> None:
    with transaction() as conn:
        conn.execute("DELETE FROM user_sessions WHERE token=?", (token,))


def delete_sessions_for_user(user_id: str) -> None:
    """Kicks every session of a user (e.g. after a password change)."""
    with transaction() as conn:
        conn.execute("DELETE FROM user_sessions WHERE user_id=?", (user_id,))


