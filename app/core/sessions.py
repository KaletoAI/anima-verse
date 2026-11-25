"""Session management (multiuser phase 1).

Server-side sessions with opaque tokens. The tokens live in the DB, the browser
only ever gets the token as an HttpOnly cookie.

TTL: sliding expiration — activity extends the session by its stored TTL:
SESSION_TTL_HOURS by default, REMEMBER_TTL_DAYS when remembered at login.
Both halves have to slide: the DB row (``get_session``) AND the browser cookie,
which is re-issued by the caller whenever ``get_session`` reports a refresh —
otherwise the browser drops the credential exactly one session TTL after
login, mid-session. The DB write is throttled to SLIDE_THROTTLE_SECONDS so
short-interval polling does not hammer world.db on every request.

Lookup cache (``resolve_session_user`` / ``cached_session_user``): every
HTTP request resolves its cookie, and the auth middleware runs on the event
loop, so the session + user lookup sits in front of a small in-process cache
(token -> session row, user dict; LOOKUP_CACHE_TTL_SECONDS). Rules:
- A hit does no DB access. It re-checks the cached ``expires_at`` against the
  clock, so an expired session is never served from the cache.
- Every writer of ``user_sessions`` and of ``users`` invalidates AFTER its
  commit (``invalidate_token`` / ``invalidate_user``); logout and "end the
  other sessions" therefore take effect on the very next lookup, not after the
  TTL. A fill that read the DB before such an invalidation is not stored
  (generation check), so a lookup racing a logout cannot re-insert the dead
  session.
- Sliding is unchanged: it happens in ``get_session``, i.e. on every refill
  from the DB. A continuously used session refills at least every
  LOOKUP_CACHE_TTL_SECONDS (5 s), far below SLIDE_THROTTLE_SECONDS (60 s), so
  it still slides about once a minute (at most 60 + 5 s after the last slide).
- A process that writes world.db from OUTSIDE (another process, a hand edit)
  is seen after at most LOOKUP_CACHE_TTL_SECONDS.
"""
import copy
import secrets
import threading
import time
from collections import OrderedDict
from datetime import datetime, timedelta

from app.core.timeutils import parse_iso, utc_now
from typing import Optional, Dict, Any, Tuple

from app.core.db import get_connection, transaction
from app.core.log import get_logger

logger = get_logger("sessions")


SESSION_COOKIE_NAME = "av_session"
SESSION_TTL_HOURS = 24
REMEMBER_TTL_DAYS = 30
# Only slide the DB row (and re-issue the cookie) once per minute — the play UI
# polls every few seconds, and every slide is a write to world.db.
SLIDE_THROTTLE_SECONDS = 60
#: How long a resolved (session, user) pair is served from memory. Must stay
#: far below SLIDE_THROTTLE_SECONDS so an active session keeps sliding.
LOOKUP_CACHE_TTL_SECONDS = 5.0
#: Bound of the lookup cache; the oldest entry goes first.
LOOKUP_CACHE_MAX_ENTRIES = 1024


def _now() -> datetime:
    return utc_now()


def _monotonic() -> float:
    return time.monotonic()


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def is_secure_request(scheme: str, forwarded_proto: str = "") -> bool:
    """Is this request served over HTTPS?

    ``X-Forwarded-Proto`` wins when present: behind a reverse proxy that
    terminates TLS, the request reaching uvicorn is plain http even though the
    browser spoke https, and only the header knows. A proxy may append its own
    value to an existing list, so the FIRST entry (the client-facing hop) is
    the one that counts.
    """
    first = (forwarded_proto or "").split(",")[0].strip().lower()
    if first:
        return first == "https"
    return (scheme or "").lower() == "https"


def request_is_secure(request) -> bool:
    """``is_secure_request`` for a Starlette request."""
    return is_secure_request(request.url.scheme,
                            request.headers.get("x-forwarded-proto", ""))


def set_session_cookie(response, token: str, secure: bool, ttl_hours: int) -> None:
    """Writes the session cookie onto a response (login AND every slide).

    Lives here, not in the auth route, because the middleware re-issues the
    cookie on sliding refresh and core must not import routes.

    ``secure`` comes from the request scheme: on https the cookie must never
    travel over a plain-http connection, on http it MUST NOT carry the flag or
    the browser would drop it and no local setup could log in at all.
    """
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=ttl_hours * 3600,
        httponly=True,
        samesite="lax",
        secure=secure,
        path="/",
    )


def clear_session_cookie(response) -> None:
    """Removes the session cookie (logout)."""
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")


def create_session(user_id: str, remember: bool = False) -> str:
    """Creates a new session and returns its token."""
    token = secrets.token_urlsafe(32)
    now = _now()
    ttl_hours = REMEMBER_TTL_DAYS * 24 if remember is True else SESSION_TTL_HOURS
    expires = now + timedelta(hours=ttl_hours)
    with transaction() as conn:
        conn.execute(
            "INSERT INTO user_sessions (token, user_id, created_at, expires_at, "
            "last_activity, ttl_hours) VALUES (?, ?, ?, ?, ?, ?)",
            (token, user_id, _iso(now), _iso(expires), _iso(now), ttl_hours),
        )
    return token


def peek_session(token: str) -> Optional[Dict[str, Any]]:
    """The session row if the token is valid NOW — without sliding it.

    A long-lived stream re-checks its session every minute; sliding there would
    keep a session alive for as long as a tab stays open, without any user
    activity. Expired rows are left for get_session's cleanup."""
    if not token:
        return None
    row = get_connection().execute(
        "SELECT token, user_id, created_at, expires_at, last_activity, ttl_hours "
        "FROM user_sessions WHERE token=?", (token,)).fetchone()
    if not row:
        return None
    try:
        if _now() >= parse_iso(row["expires_at"]):
            return None
    except (TypeError, ValueError):
        return None
    session = dict(row)
    if session["ttl_hours"] is None:
        session["ttl_hours"] = SESSION_TTL_HOURS
    return session


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
        "SELECT token, user_id, created_at, expires_at, last_activity, ttl_hours "
        "FROM user_sessions WHERE token=?",
        (token,),
    ).fetchone()
    if not row:
        return None, False

    session = dict(row)
    if session["ttl_hours"] is None:
        session["ttl_hours"] = SESSION_TTL_HOURS
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
        return session, False

    new_expires = now + timedelta(hours=session["ttl_hours"])
    with transaction() as conn:
        conn.execute(
            "UPDATE user_sessions SET last_activity=?, expires_at=? WHERE token=?",
            (_iso(now), _iso(new_expires), token),
        )
    # The returned row is the row as it is NOW — the lookup cache checks expiry
    # against this expires_at, and the pre-slide value would end a cached
    # session early.
    session["last_activity"] = _iso(now)
    session["expires_at"] = _iso(new_expires)
    return session, True


def delete_session(token: str) -> None:
    try:
        with transaction() as conn:
            conn.execute("DELETE FROM user_sessions WHERE token=?", (token,))
    finally:
        invalidate_token(token)


def delete_sessions_for_user(user_id: str) -> int:
    """Kicks every session of a user (e.g. after an admin password reset).

    Returns how many sessions were ended.
    """
    try:
        with transaction() as conn:
            cur = conn.execute("DELETE FROM user_sessions WHERE user_id=?", (user_id,))
            return cur.rowcount
    finally:
        invalidate_user(user_id)


def delete_other_sessions(user_id: str, keep_token: str) -> int:
    """Kicks every session of a user EXCEPT the one holding ``keep_token``.

    A password change must invalidate the credential everywhere it is still
    lying around, but not log out the browser that is doing the change. The
    ``token`` column stores the opaque token verbatim (``create_session``
    inserts exactly what the cookie carries), so the row to keep is addressed
    by equality on that value — no hashing in between.

    Returns how many sessions were ended.
    """
    try:
        with transaction() as conn:
            cur = conn.execute(
                "DELETE FROM user_sessions WHERE user_id=? AND token<>?",
                (user_id, keep_token or ""),
            )
            return cur.rowcount
    finally:
        # All of the user's entries, the kept one included: it simply refills.
        invalidate_user(user_id)


# ── Lookup cache ──────────────────────────────────────────────────────
#
# token -> (session dict, user dict, expires_at datetime, fetched_at monotonic).
# The lock guards the dict and the generation only; it is never held during DB
# access. Values are deep-copied in and out: callers mutate the user dict they
# get (account._update_current_user_settings writes user["settings"] back into
# the request's context object), and that must never reach the shared entry.
_cache: "OrderedDict[str, Tuple[Dict[str, Any], Dict[str, Any], datetime, float]]" = OrderedDict()
_cache_lock = threading.Lock()
#: Bumped by every invalidation. A fill stores its result only when the
#: generation is still the one it saw BEFORE reading the DB — otherwise a write
#: (a logout, a role change) committed while it was reading, and what it read
#: may be exactly what that write ended.
_cache_generation = 0

#: Returned by ``cached_session_user`` when only the DB can answer.
MISS = object()


def invalidate_token(token: str) -> None:
    """Drop one token's entry. Call AFTER the write that changed it committed."""
    global _cache_generation
    with _cache_lock:
        _cache_generation += 1
        _cache.pop(token, None)


def invalidate_user(user_id: str) -> None:
    """Drop every entry of a user (session delete, any change to the users row).
    Call AFTER the write committed."""
    global _cache_generation
    with _cache_lock:
        _cache_generation += 1
        for token in [t for t, entry in _cache.items()
                      if entry[0].get("user_id") == user_id]:
            del _cache[token]


def clear_lookup_cache() -> None:
    """Drop everything (tests; a world switch)."""
    global _cache_generation
    with _cache_lock:
        _cache_generation += 1
        _cache.clear()


def cached_session_user(token: str):
    """The cached ``(session, user, refreshed=False)`` for ``token`` — no DB
    access, safe on the event loop. ``(None, None, False)`` when the cached
    session has expired since it was read (refused without asking the DB; the
    next DB lookup deletes the row). ``MISS`` when only the DB can answer."""
    if not token:
        return None, None, False
    with _cache_lock:
        entry = _cache.get(token)
        if entry is None:
            return MISS
        session, user, expires, fetched = entry
        if _monotonic() - fetched >= LOOKUP_CACHE_TTL_SECONDS:
            del _cache[token]
            return MISS
        if _now() >= expires:
            del _cache[token]
            return None, None, False
    # Copied outside the lock: a stored entry is never changed afterwards, and
    # this runs on the event loop for every request.
    return copy.deepcopy(session), copy.deepcopy(user), False


def resolve_session_user(token: str):
    """``(session, user, refreshed)`` for a session cookie — from the cache when
    possible, otherwise from the DB (sliding the row like ``get_session``).

    Touches the DB on a miss: never call it on the event loop (the auth
    middleware tries ``cached_session_user`` there and sends a miss to a
    thread). ``session`` may be set while ``user`` is None (a session whose
    user is gone); such a pair is not cached.
    """
    hit = cached_session_user(token)
    if hit is not MISS:
        return hit
    from app.core import users
    with _cache_lock:
        generation = _cache_generation
    session, refreshed = get_session(token)
    if not session:
        return None, None, refreshed
    user = users.get_user_by_id(session["user_id"])
    if not user:
        return session, None, refreshed
    try:
        expires = parse_iso(session["expires_at"])
    except (TypeError, ValueError):
        return session, user, refreshed
    with _cache_lock:
        if generation == _cache_generation:
            _cache[token] = (copy.deepcopy(session), copy.deepcopy(user),
                             expires, _monotonic())
            _cache.move_to_end(token)
            while len(_cache) > LOOKUP_CACHE_MAX_ENTRIES:
                _cache.popitem(last=False)
    return session, user, refreshed
