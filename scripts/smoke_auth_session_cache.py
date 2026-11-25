#!/usr/bin/env python3
"""Auth session cache: a hit never touches the DB, every writer ends a cached session at once.

Usage: ./.venv/bin/python scripts/smoke_auth_session_cache.py
Storage is a temp dir, initialised before any world-DB module is imported. No server, no HTTP.

DB access is counted by wrapping ``get_connection`` in db, sessions and users (the two
modules import the name directly). Constants: LOOKUP_CACHE_TTL_SECONDS = 5,
SLIDE_THROTTLE_SECONDS = 60, SESSION_TTL_HOURS = 24. Both clocks of the cache
(sessions._now = UTC wall clock, sessions._monotonic = entry age) are replaced by a fake
clock T (seconds) where a check needs time to pass.

Expected, derived by hand:
  [1] two lookups of one token at the same T: the first is a miss (DB > 0), the second
      a hit: 0 DB calls, same user id.
  [2] delete_session(A) (logout), then lookup A within the TTL -> user None; the cache
      entry is gone (cached_session_user(A) is MISS, not a hit).
  [3] tokens B and C of one user, both warm; delete_other_sessions(uid, keep=B)
      -> lookup C None immediately, lookup B returns the user.
  [4] warm entry with role "admin" / allowed ["Ann"]; update_user(role="user") ->
      next lookup role "user" (and it went to the DB: > 0 calls);
      update_user(allowed_characters=["Ann","Bo"]) -> next lookup ["Ann","Bo"];
      update_user(settings={"active_character":"Bo"}) -> next lookup sees it;
      set_user_password / touch_last_login drop the entry too (cached_session_user = MISS);
      delete_user -> next lookup user None.
  [5] session D created at T=0 expires at T0+24h. Warm at T=0, then the wall clock
      jumps to T0+24h+1s while the monotonic clock stays (entry still younger than 5 s):
      lookup -> (None, None) with 0 DB calls.
  [6] loop_guard strict, loop registered inside the coroutine: the middleware with a
      cold cache (miss -> thread) and then warm (hit) leaves violations == []; inside
      call_next current_user_ctx is the user both times; the warm call does 0 DB calls;
      the auth_gate-style dependency get_current_user_optional(request) called ON the loop
      inside call_next returns the middleware's user with 0 DB calls.
  [7] one session E used every second from T=0 to T=130 (131 lookups). Entries live 5 s,
      so the DB is read at T = 0,5,...,130 -> 27 misses, 104 hits. The row slides when a
      refill sees last_activity >= 60 s old: T=60 (since 0) and T=120 (since 60) ->
      exactly 2 refreshes, at T=60 and T=120; afterwards expires_at = T0+120s+24h.
      Then the middleware at T=185 (entry from T=130 is stale, last slide 65 s ago)
      slides again -> response carries Set-Cookie av_session=E.
  [8] a fill racing a logout: during the miss, after the session row is read, the user
      read is intercepted and delete_session(F) runs (commit + invalidate). The racing
      lookup still returns what it read, but must NOT store it -> the next lookup of F
      is None.
  [9] bound: with LOOKUP_CACHE_MAX_ENTRIES patched to 3, filling 4 tokens G1..G4 in
      order leaves 3 entries, G1 (oldest) gone.
  [10] copies: mutating the returned user's allowed_characters / settings does not change
       what the next hit returns.
  [11] a slide that cannot get the write lock (another connection holds BEGIN IMMEDIATE,
       as a prop-action claim did for a minute): session X created at T=0, lookup at T=70
       (last slide 70 s ago > 60 s, so the miss tries to slide). The slide waits at most
       SLIDE_BUSY_TIMEOUT_MS = 200 ms instead of busy_timeout 5000 ms, so the lookup
       returns the user in < 1 s (200 ms wait + a few ms of reads), raises nothing and
       reports refreshed False; the entry is cached, so a second lookup at T=70 is a hit
       with 0 DB calls. At T=76 the entry is 6 s old (> 5 s TTL) -> miss, the slide fails
       again: still the user, and still exactly ONE warning (throttle 60 s on the
       monotonic clock: 70 -> 76 is 6 s). The thread's connection is back to
       busy_timeout 5000 after each failed slide. Lock released, T=82: miss (entry from
       T=76 is 6 s old) and the slide succeeds -> refreshed True, expires_at =
       T0+82s+24h.
"""
import asyncio
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths  # noqa: E402

failed = 0


def ok(label, cond, detail=""):
    global failed
    print(("  OK  " if cond else "  FAIL ") + label + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        failed += 1


with tempfile.TemporaryDirectory() as tmp:
    paths.init(Path(tmp))
    from app.core import db  # noqa: E402
    db.init_schema()
    from app.core import auth_dependency, loop_guard, sessions, users  # noqa: E402
    from app.core.timeutils import utc_now  # noqa: E402

    calls = {"n": 0}
    _real_conn = db.get_connection

    def counting_conn():
        calls["n"] += 1
        return _real_conn()

    db.get_connection = counting_conn
    sessions.get_connection = counting_conn
    users.get_connection = counting_conn

    def counted(fn, *a):
        before = calls["n"]
        out = fn(*a)
        return out, calls["n"] - before

    # A fake clock for both cache clocks; None = real time.
    clock = {"t": None}
    T0 = utc_now()
    real_now, real_mono = sessions._now, sessions._monotonic

    def fake_now():
        return real_now() if clock["t"] is None else T0 + timedelta(seconds=clock["t"])

    def fake_mono():
        return real_mono() if clock["t"] is None else 1_000_000.0 + clock["t"]

    sessions._now = fake_now
    sessions._monotonic = fake_mono

    uid = users.create_user("demo", "demo-password-1", role="admin", allowed_characters=["Ann"])
    lookup = sessions.resolve_session_user

    # [1]
    A = sessions.create_session(uid)
    (s1, u1, _), n1 = counted(lookup, A)
    (s2, u2, _), n2 = counted(lookup, A)
    ok("[1] first lookup is a DB miss", n1 > 0 and u1 and u1["id"] == uid, f"n={n1}")
    ok("[1] second lookup: 0 DB calls, same user", n2 == 0 and u2 and u2["id"] == uid, f"n={n2}")

    # [2]
    sessions.delete_session(A)
    ok("[2] cache entry dropped on logout", sessions.cached_session_user(A) is sessions.MISS)
    ok("[2] logout: next lookup None", lookup(A)[1] is None)

    # [3]
    B = sessions.create_session(uid)
    C = sessions.create_session(uid)
    lookup(B), lookup(C)
    ok("[3] both warm", sessions.cached_session_user(B) is not sessions.MISS
       and sessions.cached_session_user(C) is not sessions.MISS)
    sessions.delete_other_sessions(uid, B)
    ok("[3] other session refused immediately", lookup(C)[1] is None)
    ok("[3] kept session still works", (lookup(B)[1] or {}).get("id") == uid)

    # [4]
    lookup(B)
    users.update_user(uid, role="user")
    (_, u, _), n = counted(lookup, B)
    ok("[4] role change visible on next lookup", u and u["role"] == "user" and n > 0, f"{u and u['role']} n={n}")
    users.update_user(uid, allowed_characters=["Ann", "Bo"])
    ok("[4] allowed_characters change visible", lookup(B)[1]["allowed_characters"] == ["Ann", "Bo"])
    users.update_user(uid, settings={"active_character": "Bo"})
    ok("[4] active character change visible", lookup(B)[1]["settings"].get("active_character") == "Bo")
    users.set_user_password(uid, "demo-password-2")
    ok("[4] password change drops the entry", sessions.cached_session_user(B) is sessions.MISS)
    lookup(B)
    users.touch_last_login(uid)
    ok("[4] touch_last_login drops the entry", sessions.cached_session_user(B) is sessions.MISS)
    lookup(B)
    users.update_user_checked(uid, users.user_revision(users.get_user_by_id(uid)), {"role": "admin"})
    ok("[4] update_user_checked visible", lookup(B)[1]["role"] == "admin")
    uid2 = users.create_user("demo2", "demo-password-1")
    X = sessions.create_session(uid2)
    lookup(X)
    users.delete_user(uid2)
    ok("[4] deleted user: next lookup has no user", lookup(X)[1] is None)

    # [5]
    clock["t"] = 0
    D = sessions.create_session(uid)
    lookup(D)
    clock["t"] = 24 * 3600 + 1      # wall clock past expiry ...
    sessions._monotonic = lambda: 1_000_000.0   # ... entry age stays 0
    (sd, ud, rd), n = counted(lookup, D)
    sessions._monotonic = fake_mono
    ok("[5] expired session refused from cache without DB", sd is None and ud is None and n == 0, f"n={n}")
    clock["t"] = None

    # [6]
    from starlette.requests import Request
    from starlette.responses import Response

    def fake_request(token, path="/play/state"):
        return Request({"type": "http", "method": "GET", "path": path, "raw_path": path.encode(),
                        "query_string": b"", "scheme": "http", "server": ("test", 80),
                        "headers": [(b"cookie", f"av_session={token}".encode())]})

    E6 = sessions.create_session(uid)

    async def strict_scenario():
        loop_guard.register_server_loop()
        loop_guard.strict(True)
        loop_guard.clear_violations()
        seen = []

        async def call_next(request):
            seen.append(auth_dependency.current_user_ctx.get())
            before = calls["n"]
            dep = auth_dependency.get_current_user_optional(request)
            seen.append(("dep", dep, calls["n"] - before))
            return Response("ok")

        sessions.clear_lookup_cache()
        await auth_dependency.user_context_middleware(fake_request(E6), call_next)
        before = calls["n"]
        await auth_dependency.user_context_middleware(fake_request(E6), call_next)
        warm_calls = calls["n"] - before
        violations = list(loop_guard.violations)
        loop_guard.strict(False)
        loop_guard.unregister()
        return seen, warm_calls, violations

    seen, warm_calls, violations = asyncio.run(strict_scenario())
    ok("[6] strict mode: no loop violations (cold + warm)", violations == [], str(violations))
    ok("[6] contextvar set in the request task (cold)", (seen[0] or {}).get("id") == uid)
    ok("[6] contextvar set in the request task (warm)", (seen[2] or {}).get("id") == uid)
    ok("[6] warm middleware path: 0 DB calls", warm_calls == 0, f"n={warm_calls}")
    ok("[6] dependency on the loop reuses the middleware user, 0 DB calls",
       seen[1][1] is seen[0] and seen[1][2] == 0 and seen[3][2] == 0, str(seen[1][2]))

    # [7]
    sessions.clear_lookup_cache()
    clock["t"] = 0
    E = sessions.create_session(uid)
    misses = hits = 0
    refreshed_at = []
    for t in range(0, 131):
        clock["t"] = t
        hit = sessions.cached_session_user(E) is not sessions.MISS
        _, u, refreshed = lookup(E)
        misses += 0 if hit else 1
        hits += 1 if hit else 0
        if refreshed:
            refreshed_at.append(t)
    ok("[7] 27 misses / 104 hits", (misses, hits) == (27, 104), f"{misses}/{hits}")
    ok("[7] slides at T=60 and T=120", refreshed_at == [60, 120], str(refreshed_at))
    row = _real_conn().execute("SELECT expires_at FROM user_sessions WHERE token=?", (E,)).fetchone()
    ok("[7] expires_at = T0+120s+24h",
       row["expires_at"] == sessions._iso(T0 + timedelta(seconds=120, hours=24)), row["expires_at"])
    clock["t"] = 185

    async def slide_through_middleware():
        async def call_next(request):
            return Response("ok")
        return await auth_dependency.user_context_middleware(fake_request(E), call_next)

    resp = asyncio.run(slide_through_middleware())
    cookies = resp.headers.getlist("set-cookie")
    ok("[7] refresh reaches the response cookie", any(c.startswith(f"av_session={E}") for c in cookies), str(cookies))
    clock["t"] = None

    # [8]
    F = sessions.create_session(uid)
    real_get_user = users.get_user_by_id

    def racing_get_user(user_id):
        sessions.delete_session(F)          # a logout commits mid-fill
        return real_get_user(user_id)

    users.get_user_by_id = racing_get_user
    sessions.clear_lookup_cache()
    lookup(F)
    users.get_user_by_id = real_get_user
    ok("[8] racing fill not stored", sessions.cached_session_user(F) is sessions.MISS)
    ok("[8] next lookup after the racing logout: None", lookup(F)[1] is None)

    # [9]
    sessions.clear_lookup_cache()
    old_max = sessions.LOOKUP_CACHE_MAX_ENTRIES
    sessions.LOOKUP_CACHE_MAX_ENTRIES = 3
    G = [sessions.create_session(uid) for _ in range(4)]
    for g in G:
        lookup(g)
    ok("[9] bounded to 3 entries", len(sessions._cache) == 3, str(len(sessions._cache)))
    ok("[9] oldest dropped", G[0] not in sessions._cache and all(g in sessions._cache for g in G[1:]))
    sessions.LOOKUP_CACHE_MAX_ENTRIES = old_max

    # [10]
    H = sessions.create_session(uid)
    _, u, _ = lookup(H)
    u["allowed_characters"].append("Evil")
    u["settings"]["active_character"] = "Evil"
    u["role"] = "admin-evil"
    _, u2, _ = lookup(H)
    _, u3, _ = sessions.cached_session_user(H)
    ok("[10] the cached user cannot be poisoned",
       "Evil" not in u3["allowed_characters"] and u3["settings"].get("active_character") != "Evil"
       and u3["role"] == "admin", str(u3))

    # [11]
    import sqlite3
    import time
    sessions.clear_lookup_cache()
    clock["t"] = 0
    X = sessions.create_session(uid)
    clock["t"] = 70
    warnings = []
    real_warning = sessions.logger.warning
    sessions.logger.warning = lambda *a, **k: warnings.append(a)
    holder = sqlite3.connect(str(db.get_db_path()), timeout=10)
    try:
        holder.execute("BEGIN IMMEDIATE")
        started = time.perf_counter()
        try:
            got = lookup(X)
            error = None
        except Exception as exc:  # the old slide raised "database is locked" after 5 s
            got, error = (None, None, False), exc
        elapsed = time.perf_counter() - started
        ok("[11] locked slide: lookup raises nothing", error is None, repr(error))
        ok("[11] locked slide: the user, in < 1 s", (got[1] or {}).get("id") == uid and elapsed < 1.0,
           f"{elapsed:.2f} s")
        ok("[11] locked slide: refreshed False", got[2] is False, str(got[2]))
        ok("[11] busy_timeout back to 5000",
           _real_conn().execute("PRAGMA busy_timeout").fetchone()[0] == 5000)
        (_, u_hit, _), n_hit = counted(lookup, X)
        ok("[11] follow-up lookup is a cache hit (0 DB calls)",
           n_hit == 0 and (u_hit or {}).get("id") == uid, f"n={n_hit}")
        clock["t"] = 76
        try:
            again = lookup(X)
        except Exception as exc:
            again = (None, None, False)
            ok("[11] second locked slide raises nothing", False, repr(exc))
        ok("[11] second locked slide: still the user", (again[1] or {}).get("id") == uid)
        ok("[11] one warning per minute", len(warnings) == 1, str(len(warnings)))
    finally:
        holder.rollback()
        holder.close()
        sessions.logger.warning = real_warning
    clock["t"] = 82
    _, u_after, refreshed_after = lookup(X)
    row = _real_conn().execute("SELECT expires_at FROM user_sessions WHERE token=?", (X,)).fetchone()
    ok("[11] lock released: the slide succeeds",
       refreshed_after is True and (u_after or {}).get("id") == uid
       and row["expires_at"] == sessions._iso(T0 + timedelta(seconds=82, hours=24)),
       f"{refreshed_after} {row['expires_at']}")
    clock["t"] = None

print("FAILED" if failed else "Auth session cache checks passed")
sys.exit(1 if failed else 0)
