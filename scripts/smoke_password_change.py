#!/usr/bin/env python3
"""Smoke: changing one's own password (POST /auth/password) and the session
consequences of an admin reset (PATCH /auth/users/{id}).

Usage:  ./.venv/bin/python scripts/smoke_password_change.py

Needs no running server and no real world: `paths.init` points at a throwaway
directory BEFORE any world-DB module is imported, `db.init_schema()` builds an
empty world.db there, and the auth router is mounted on a throwaway FastAPI app
behind the real `auth_gate_middleware` — exactly the order `app/server.py`
mounts it in. `app.server` itself is never imported.

WHAT IS CHECKED, and where every expected value comes from
-----------------------------------------------------------

A) REACHABILITY, read off `app/core/auth_dependency.py` by hand.
   `_PUBLIC_EXACT` lists `/auth/login`, `/auth/logout` and `/auth/status` —
   three exact paths, NOT an `/auth` prefix. So:

     is_public_path('/auth/password')            -> False
       (the gate refuses an anonymous caller; the route's
        Depends(get_current_user) is the second layer)
     is_admin_only_path('/auth/password','POST') -> False
       (`/auth` is in no admin prefix and in no admin-write prefix, so a
        logged-in NON-admin may call it — a player changes their own password)

   End to end through the mounted gate:
     anonymous POST /auth/password  -> 401
     player    POST /auth/password  -> reaches the route (never 403)

B) THE WRONG CURRENT PASSWORD IS A THROTTLED ATTEMPT. The route shares the
   login's counter — `_failure_key(username, client_ip)` into
   `auth._login_failures` — because an endpoint that verifies a password
   without a lock on it IS a login form.

     wrong current password            -> 403, and the failure list for that
                                          (username, ip) key grows by exactly 1
     LOGIN_FAIL_LIMIT wrong attempts,
       then one more call              -> 429 + Retry-After
       (N is read from auth.LOGIN_FAIL_LIMIT, never typed in here: the
        (N+1)-th attempt inside the window is the first one refused, which is
        precisely where `login_retry_after` starts returning > 0. The header
        value is at most LOGIN_FAIL_WINDOW_SECONDS + 1 — the value
        `login_retry_after` returns for a failure at age 0.)
     a correct current password        -> clears the counter (like a login)

C) THE NEW PASSWORD.  `users.MIN_PASSWORD_LENGTH` is 8 and
   `users.set_user_password` raises ValueError below it; the route maps that
   to 400. Equal-to-current is rejected by the route itself.

     new password of MIN_PASSWORD_LENGTH - 1 characters -> 400
     new password == current password                   -> 400
     missing field                                      -> 400

D) SUCCESS ENDS THE OTHER SESSIONS, NOT THIS ONE. The session token is stored
   VERBATIM in `user_sessions.token` (see `sessions.create_session`), so
   `delete_other_sessions(user_id, keep_token)` keeps the row by equality on
   the token the cookie carries.

     one extra session of the same user exists -> sessions_ended == 1
     the calling session                       -> still resolves (GET /auth/status)
     the extra session                         -> gone
     another user's session                    -> untouched
     the OLD password at POST /auth/login      -> 401
     the NEW password at POST /auth/login      -> 200

E) AN ADMIN RESET (PATCH /auth/users/{id} with `password`).

     reset of ANOTHER user, who has 2 sessions -> sessions_ended == 2, both
                                                  tokens gone, the admin's own
                                                  session still resolves
     reset of the admin's OWN password         -> the calling session survives,
                                                  sessions_ended counts only
                                                  the other ones (1 here)
     a PATCH without a password                -> sessions_ended == 0

Sample user names are `demo…` only — no real account names in code.
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="pwchange-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="pwchange-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import config  # noqa: E402
config.load(STORAGE / "config.json")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core import auth_dependency, db, sessions, users  # noqa: E402
from app.routes import auth as auth_route  # noqa: E402

FAILS = []


def check(label, got, expected):
    ok = got == expected
    if not ok:
        FAILS.append(f"{label}: got {got!r}, expected {expected!r}")
    print(f"  [{'ok' if ok else 'FAIL'}] {label}: {got!r}")


# ── The throwaway world + app ────────────────────────────────────────
db.init_schema()

PLAYER_PW = "player-pass-1"
OTHER_PW = "other-pass-1"
ADMIN_PW = "admin-pass-1"
PLAYER_ID = users.create_user("demo", PLAYER_PW, role=users.ROLE_USER)
OTHER_ID = users.create_user("demo_other", OTHER_PW, role=users.ROLE_USER)
ADMIN_ID = users.create_user("demo_admin", ADMIN_PW, role=users.ROLE_ADMIN)

app = FastAPI()
# SAME ORDER as app/server.py: the gate added first (=> innermost), then the
# user context (=> outermost). add_middleware/middleware() prepend.
app.middleware("http")(auth_dependency.auth_gate_middleware)
app.middleware("http")(auth_dependency.user_context_middleware)
app.include_router(auth_route.router)

client = TestClient(app, follow_redirects=False)


def call(method, path, body=None, token=""):
    """One request under exactly one session (or none)."""
    client.cookies.clear()
    if token:
        client.cookies.set(sessions.SESSION_COOKIE_NAME, token)
    return client.request(method, path, json=body,
                          headers={"accept": "application/json"})


def failure_count(username):
    key = auth_route._failure_key(username, "testclient")
    return len(auth_route._login_failures.get(key, []))


def clear_failures(username):
    auth_route._clear_failures(auth_route._failure_key(username, "testclient"))


def session_alive(token):
    return sessions.get_session(token)[0] is not None


print("A) reachability")
check("is_public_path /auth/password",
      auth_dependency.is_public_path("/auth/password"), False)
check("is_admin_only_path POST /auth/password",
      auth_dependency.is_admin_only_path("/auth/password", "POST"), False)
check("is_public_path /auth/login (reference)",
      auth_dependency.is_public_path("/auth/login"), True)
check("anon POST /auth/password",
      call("POST", "/auth/password",
           {"current_password": PLAYER_PW, "new_password": "whatever-1"}).status_code,
      401)

player_token = sessions.create_session(PLAYER_ID)
check("player session resolves", session_alive(player_token), True)

print()
print("B) the current password runs through the login throttle")
clear_failures("demo")
r = call("POST", "/auth/password",
         {"current_password": "definitely-wrong", "new_password": "brand-new-1"},
         player_token)
check("wrong current password -> status", r.status_code, 403)
check("wrong current password -> detail", r.json().get("detail"),
      "Current password is wrong")
check("failure counter after 1 wrong attempt", failure_count("demo"), 1)

# Fill the window up to the limit, then the next call is the first refused.
N = auth_route.LOGIN_FAIL_LIMIT
for _ in range(N - 1):
    call("POST", "/auth/password",
         {"current_password": "definitely-wrong", "new_password": "brand-new-1"},
         player_token)
check(f"failure counter at the limit (N={N})", failure_count("demo"), N)
r = call("POST", "/auth/password",
         {"current_password": PLAYER_PW, "new_password": "brand-new-1"},
         player_token)
check("attempt N+1 -> status", r.status_code, 429)
check("attempt N+1 -> Retry-After present",
      r.headers.get("retry-after", "").isdigit(), True)
check("attempt N+1 -> Retry-After <= window + 1",
      int(r.headers.get("retry-after", "0")) <= auth_route.LOGIN_FAIL_WINDOW_SECONDS + 1,
      True)
check("throttled attempt is not counted", failure_count("demo"), N)
# A throttled call must not have changed anything.
check("password unchanged while throttled",
      users.check_user_password("demo", PLAYER_PW) is not None, True)

clear_failures("demo")

print()
print("C) the new password")
short = "x" * (users.MIN_PASSWORD_LENGTH - 1)
r = call("POST", "/auth/password",
         {"current_password": PLAYER_PW, "new_password": short}, player_token)
check("too short -> status", r.status_code, 400)
check("too short -> detail mentions the minimum",
      str(users.MIN_PASSWORD_LENGTH) in str(r.json().get("detail")), True)
r = call("POST", "/auth/password",
         {"current_password": PLAYER_PW, "new_password": PLAYER_PW}, player_token)
check("new == current -> status", r.status_code, 400)
r = call("POST", "/auth/password", {"current_password": PLAYER_PW}, player_token)
check("missing new password -> status", r.status_code, 400)
check("a correct current password clears the counter", failure_count("demo"), 0)
check("password still the old one",
      users.check_user_password("demo", PLAYER_PW) is not None, True)

print()
print("D) success ends every OTHER session")
second_token = sessions.create_session(PLAYER_ID)      # the same user elsewhere
other_token = sessions.create_session(OTHER_ID)        # a different user
NEW_PW = "player-pass-2"
r = call("POST", "/auth/password",
         {"current_password": PLAYER_PW, "new_password": NEW_PW}, player_token)
check("success -> status", r.status_code, 200)
check("success -> body", r.json(), {"status": "success", "sessions_ended": 1})
check("calling session still resolves", session_alive(player_token), True)
check("calling session still answers /auth/status",
      call("GET", "/auth/status", token=player_token).json().get("authenticated"),
      True)
check("the other session of the same user is gone",
      session_alive(second_token), False)
check("the other USER's session is untouched", session_alive(other_token), True)

clear_failures("demo")
check("old password no longer logs in",
      call("POST", "/auth/login",
           {"username": "demo", "password": PLAYER_PW}).status_code, 401)
clear_failures("demo")
login = call("POST", "/auth/login", {"username": "demo", "password": NEW_PW})
check("new password logs in", login.status_code, 200)
fresh_token = login.cookies.get(sessions.SESSION_COOKIE_NAME) or ""
check("login handed out a session", bool(fresh_token), True)

print()
print("E) an admin reset")
admin_token = sessions.create_session(ADMIN_ID)
other_a = sessions.create_session(OTHER_ID)
other_b = sessions.create_session(OTHER_ID)
check("the other user has 3 sessions now",
      [session_alive(t) for t in (other_token, other_a, other_b)],
      [True, True, True])
r = call("PATCH", f"/auth/users/{OTHER_ID}", {"password": "other-pass-2"},
         admin_token)
check("admin reset -> status", r.status_code, 200)
check("admin reset -> sessions_ended", r.json().get("sessions_ended"), 3)
check("every session of the target is gone",
      [session_alive(t) for t in (other_token, other_a, other_b)],
      [False, False, False])
check("the admin's own session survives", session_alive(admin_token), True)
check("the target's new password works",
      users.check_user_password("demo_other", "other-pass-2") is not None, True)

# A PATCH that carries no password touches no session at all.
r = call("PATCH", f"/auth/users/{OTHER_ID}", {"role": "user"}, admin_token)
check("PATCH without a password -> sessions_ended",
      r.json().get("sessions_ended"), 0)

# The admin resets their OWN password: this session must survive.
admin_second = sessions.create_session(ADMIN_ID)
r = call("PATCH", f"/auth/users/{ADMIN_ID}", {"password": "admin-pass-2"},
         admin_token)
check("admin resets own password -> status", r.status_code, 200)
check("admin resets own password -> sessions_ended",
      r.json().get("sessions_ended"), 1)
check("the admin's calling session survives", session_alive(admin_token), True)
check("the admin's other session is gone", session_alive(admin_second), False)
check("the admin can still call an admin route",
      call("GET", "/auth/users", token=admin_token).status_code, 200)

# A player may not reset anybody through the admin route.
check("player PATCH /auth/users -> 403",
      call("PATCH", f"/auth/users/{OTHER_ID}", {"password": "nope-12345"},
           fresh_token).status_code, 403)

print()
if FAILS:
    print(f"FAILED ({len(FAILS)}):")
    for f in FAILS:
        print("  -", f)
    sys.exit(1)
print("all checks passed")
