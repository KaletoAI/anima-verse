#!/usr/bin/env python3
"""Check for the sliding-session contract in ``app/core/sessions.py``.

Runs against a THROWAWAY storage directory — it never touches a real world.

Hand-derived expectations (SESSION_TTL_HOURS = 24, SLIDE_THROTTLE_SECONDS = 60):

1. create + immediate get
   ``create_session`` writes ``last_activity = T0`` and ``expires_at = T0+24h``.
   A ``get_session`` at T0+epsilon sees an age of ~0 s < 60 s, so it must NOT
   write: ``refreshed`` is False and ``last_activity``/``expires_at`` are
   byte-identical to what create wrote. (Without the throttle every 3-second
   poll of the play UI would UPDATE world.db.)

2. backdate ``last_activity`` by 120 s, then get
   Age 120 s > 60 s, so the row must slide: ``refreshed`` is True,
   ``last_activity`` is now ~T1 (age < 5 s) and ``expires_at`` is ~T1+24h.
   Expected bump: the stored ``expires_at`` must be strictly LATER than the
   value create wrote (T0+24h) — the whole point of the fix, since the browser
   cookie is re-issued exactly on this flag.

3. backdate ``expires_at`` into the past (T-1 s), then get
   The expiry check runs BEFORE the throttle: the call returns ``None`` and the
   row is gone from ``user_sessions`` (SELECT COUNT = 0).

5. the OTHER half of the slide: the cookie re-issue must stand down when the
   route already wrote that cookie (``auth_dependency._sets_session_cookie``).
   Derived from the header text the two writers produce, cookie name
   ``av_session``:
     - a bare response has no ``set-cookie`` header at all           -> False
     - ``clear_session_cookie`` (logout) writes ``av_session="";
       ... Max-Age=0; Path=/``, i.e. a Set-Cookie STARTING with the name
       plus "="                                                     -> True
       (without this the middleware appends a second Set-Cookie for the same
       name, the later one wins in the browser, and the client keeps a token
       whose DB row logout just deleted -> guaranteed 401)
     - ``set_session_cookie`` (login/rotation) likewise              -> True
     - a different cookie (``av_session_hint``, ``lang``) must NOT count:
       the name is compared with its "=", not as a substring         -> False

Usage:  ./.venv/bin/python scripts/test_session_sliding.py
"""
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="session-sliding-test-"))

from app.core import paths  # noqa: E402

paths.init(STORAGE)

from app.core import db  # noqa: E402

db.init_schema()

from app.core import sessions, users  # noqa: E402
from app.core.timeutils import parse_iso, utc_now  # noqa: E402

USER_ID = users.create_user("demo", "demo-password")

FAILURES = []
CHECKED = 0


def check(label: str, actual, expected) -> None:
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'OK ' if ok else 'FAIL'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


def row(token: str):
    conn = db.get_connection()
    return conn.execute(
        "SELECT token, user_id, created_at, expires_at, last_activity "
        "FROM user_sessions WHERE token=?", (token,)).fetchone()


def backdate(token: str, *, last_activity=None, expires_at=None) -> None:
    """Direct UPDATE — simulates a session that has been idle / has expired."""
    with db.transaction() as conn:
        if last_activity is not None:
            conn.execute("UPDATE user_sessions SET last_activity=? WHERE token=?",
                         (last_activity.isoformat(), token))
        if expires_at is not None:
            conn.execute("UPDATE user_sessions SET expires_at=? WHERE token=?",
                         (expires_at.isoformat(), token))


print("\n[1] create + immediate get -> throttled, no write")
token = sessions.create_session(USER_ID)
created = row(token)
sess, refreshed = sessions.get_session(token)
after = row(token)
check("session returned", bool(sess), True)
check("user_id", sess["user_id"] if sess else None, USER_ID)
check("refreshed", refreshed, False)
check("last_activity untouched", after["last_activity"], created["last_activity"])
check("expires_at untouched", after["expires_at"], created["expires_at"])

print("\n[2] last_activity 120 s old -> slides")
backdate(token, last_activity=utc_now() - timedelta(seconds=120))
sess, refreshed = sessions.get_session(token)
after = row(token)
check("session returned", bool(sess), True)
check("refreshed", refreshed, True)
age = (utc_now() - parse_iso(after["last_activity"])).total_seconds()
check("last_activity is fresh (< 5 s)", age < 5, True)
check("expires_at bumped past the create value",
      parse_iso(after["expires_at"]) > parse_iso(created["expires_at"]), True)
ttl = (parse_iso(after["expires_at"]) - utc_now()).total_seconds()
check("new TTL ~24 h", abs(ttl - sessions.SESSION_TTL_HOURS * 3600) < 5, True)

print("\n[3] expires_at in the past -> None + row deleted")
backdate(token, expires_at=utc_now() - timedelta(seconds=1))
sess, refreshed = sessions.get_session(token)
check("session is None", sess, None)
check("refreshed", refreshed, False)
check("row deleted", row(token), None)

print("\n[4] unknown token -> None, no crash")
sess, refreshed = sessions.get_session("does-not-exist")
check("session is None", sess, None)
check("refreshed", refreshed, False)
sess, refreshed = sessions.get_session("")
check("empty token is None", sess, None)

print("\n[5] cookie re-issue stands down when the route wrote the cookie")
from starlette.responses import Response  # noqa: E402
from app.core.auth_dependency import _sets_session_cookie  # noqa: E402

bare = Response()
check("bare response", _sets_session_cookie(bare), False)

logout = Response()
sessions.clear_session_cookie(logout)
check("after clear_session_cookie (logout)", _sets_session_cookie(logout), True)

login = Response()
sessions.set_session_cookie(login, "some-token")
check("after set_session_cookie", _sets_session_cookie(login), True)

other = Response()
other.set_cookie(key="lang", value="de", path="/")
other.set_cookie(key=sessions.SESSION_COOKIE_NAME + "_hint", value="x", path="/")
check("only foreign cookies", _sets_session_cookie(other), False)

print(f"\n{CHECKED - len(FAILURES)}/{CHECKED} checks passed")
if FAILURES:
    print("FAILED: " + ", ".join(FAILURES))
    sys.exit(1)
print("all good")
