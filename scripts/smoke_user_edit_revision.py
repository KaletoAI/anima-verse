#!/usr/bin/env python3
"""Smoke: the admin user edit (PATCH /auth/users/{id}) checks the revision it
was based on, and the /admin/users page sends only what changed.

Usage:  ./.venv/bin/python scripts/smoke_user_edit_revision.py

Needs no running server and no real world: `paths.init` points at a throwaway
directory BEFORE any world-DB module is imported, `db.init_schema()` builds an
empty world.db there, and the auth router is mounted on a throwaway FastAPI app
behind the real `auth_gate_middleware` (the order of `app/server.py`).
Section J runs `static/admin/users.js` under `node` with stubbed DOM/fetch and
is skipped (said so) when `node` is not on PATH.

WHAT IS CHECKED, and where every expected value comes from
-----------------------------------------------------------

The contract (app/core/users.py, app/routes/auth.py): `GET /auth/users` lists
every user with a `revision` — a hash of the fields `update_user` writes
(username, role, allowed_characters, theme, settings). A PATCH carries
`base_revision`; under `keyed_lock("user_settings", <id>)` (the lock of every
other users-row writer) the user is re-read and compared. Different -> 409
`{"code": "stale"}` and NOTHING is written. Before this fix the PATCH wrote
whatever it was given, so the second of two edits silently replaced the
first one's character list.

Seed: player "demo" (role user, allowed ["Alpha"]) and admin "demo_admin".

A) THE LIST CARRIES THE REVISION: the listed revision of demo equals
   `users.user_revision(get_user_by_id(demo))` (R0).

B) EDIT 1 based on R0: allowed -> ["Alpha", "Beta"]  => 200; the answer's
   revision R1 != R0 (the list changed) and equals the listed one.

C) EDIT 2, ALSO based on R0: role "admin", allowed ["Alpha"]  => 409 code
   "stale"; afterwards allowed == ["Alpha", "Beta"] and role == "user"
   (nothing of edit 1 lost, nothing of edit 2 written); revision still R1.

D) A PLAYER-SIDE CHANGE in between: `character_ops._grant_to_creator` adds
   "Gamma" (what creating a character does). A PATCH based on R1 that sets
   allowed ["Alpha"]  => 409; allowed stays ["Alpha", "Beta", "Gamma"].

E) A SETTINGS WRITE in between (what the avatar switch / login restore do:
   `update_user(settings=...)`) also changes the revision => a PATCH on the
   older revision is 409.

F) ONLY THE SENT FIELDS: role "admin" on the current revision => 200; the
   allowed list ["Alpha", "Beta", "Gamma"] and the settings stay as they are.

G) REFUSALS that write nothing:
     no base_revision                  -> 428, detail.code "revision_required"
     base_revision 5 (not a string)    -> 400
     unknown user id                   -> 404
     role "boss" + a valid password    -> 400; role and password unchanged
     a stale revision + only a password -> 409; the old password still works

H) TWO EDITS AT ONCE on the same revision (two threads straight into
   `users.update_user_checked`): exactly one returns a revision and exactly
   one raises `UserStale` — the lock makes check+write one step.

J) THE PAGE (`editBody` in static/admin/users.js). Loaded state:
   allowed ["Hidden", "Alpha", "Beta"], CHARS (the checkbox list) =
   ["Alpha", "Beta", "Gamma"] — "Hidden" is not offered by the dialog.
     nothing changed          -> {base_revision}
     only the role changed    -> {base_revision, role}   (no list sent)
     uncheck Beta, check Gamma -> allowed_characters ["Hidden", "Alpha", "Gamma"]
                                 (the loaded order, the new one appended,
                                  the unoffered "Hidden" kept)
     only the username changed -> {base_revision, username}

Sample user names are `demo…` only — no real account names in code.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

STORAGE = Path(tempfile.mkdtemp(prefix="user-edit-rev-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="user-edit-rev-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
paths.init_instance(STORAGE / "instance")
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


db.init_schema()
PLAYER_PW = "player-pass-1"
PLAYER_ID = users.create_user("demo", PLAYER_PW, role=users.ROLE_USER,
                              allowed_characters=["Alpha"])
ADMIN_ID = users.create_user("demo_admin", "admin-pass-1", role=users.ROLE_ADMIN)

app = FastAPI()
app.middleware("http")(auth_dependency.auth_gate_middleware)
app.middleware("http")(auth_dependency.user_context_middleware)
app.include_router(auth_route.router)
client = TestClient(app, follow_redirects=False)
admin_token = sessions.create_session(ADMIN_ID)


def patch(body, user_id=PLAYER_ID):
    client.cookies.clear()
    client.cookies.set(sessions.SESSION_COOKIE_NAME, admin_token)
    return client.request("PATCH", f"/auth/users/{user_id}", json=body,
                          headers={"accept": "application/json"})


def listed():
    client.cookies.clear()
    client.cookies.set(sessions.SESSION_COOKIE_NAME, admin_token)
    rows = client.get("/auth/users", headers={"accept": "application/json"}).json()["users"]
    return next(u for u in rows if u["id"] == PLAYER_ID)


def player():
    return users.get_user_by_id(PLAYER_ID)


def code(r):
    detail = r.json().get("detail")
    return detail.get("code") if isinstance(detail, dict) else None


print("A) the list carries the revision")
R0 = listed()["revision"]
check("listed revision == user_revision(row)", R0, users.user_revision(player()))

print("B) edit 1 on R0")
r = patch({"allowed_characters": ["Alpha", "Beta"], "base_revision": R0})
check("status", r.status_code, 200)
R1 = r.json().get("revision")
check("R1 != R0", R1 != R0, True)
check("R1 == listed", R1, listed()["revision"])

print("C) edit 2, also on R0")
r = patch({"role": "admin", "allowed_characters": ["Alpha"], "base_revision": R0})
check("status", r.status_code, 409)
check("detail.code", code(r), "stale")
check("allowed (edit 1 kept)", player()["allowed_characters"], ["Alpha", "Beta"])
check("role (edit 2 not written)", player()["role"], "user")
check("revision unchanged", listed()["revision"], R1)

print("D) a player-side grant in between")
from app.core.character_ops import _grant_to_creator  # noqa: E402
_grant_to_creator({"id": PLAYER_ID, "username": "demo"}, "Gamma")
check("grant landed", player()["allowed_characters"], ["Alpha", "Beta", "Gamma"])
r = patch({"allowed_characters": ["Alpha"], "base_revision": R1})
check("status", r.status_code, 409)
check("allowed (grant kept)", player()["allowed_characters"], ["Alpha", "Beta", "Gamma"])

print("E) a settings write in between")
R2 = listed()["revision"]
users.update_user(PLAYER_ID, settings={"active_character": "Alpha"})
check("revision moved", listed()["revision"] != R2, True)
r = patch({"role": "admin", "base_revision": R2})
check("status", r.status_code, 409)

print("F) only the sent fields")
r = patch({"role": "admin", "base_revision": listed()["revision"]})
check("status", r.status_code, 200)
check("role", player()["role"], "admin")
check("allowed untouched", player()["allowed_characters"], ["Alpha", "Beta", "Gamma"])
check("settings untouched", player()["settings"], {"active_character": "Alpha"})

print("G) refusals")
r = patch({"role": "user"})
check("no base_revision -> status", r.status_code, 428)
check("no base_revision -> code", code(r), "revision_required")
check("non-string base_revision -> status",
      patch({"role": "user", "base_revision": 5}).status_code, 400)
check("unknown user -> status",
      patch({"role": "user", "base_revision": "x"}, user_id="u_absent").status_code, 404)
r = patch({"role": "boss", "password": "player-pass-2", "base_revision": listed()["revision"]})
check("invalid role -> status", r.status_code, 400)
check("role unchanged", player()["role"], "admin")
check("password unchanged",
      users.check_user_password("demo", PLAYER_PW) is not None, True)
r = patch({"password": "player-pass-3", "base_revision": R0})
check("stale password reset -> status", r.status_code, 409)
check("old password still works",
      users.check_user_password("demo", PLAYER_PW) is not None, True)

print("H) two edits at once on the same revision")
base = listed()["revision"]
outcomes = []
gate = threading.Barrier(2)


def edit(chars):
    gate.wait()
    try:
        users.update_user_checked(PLAYER_ID, base, {"allowed_characters": chars})
        outcomes.append("ok")
    except users.UserStale:
        outcomes.append("stale")


threads = [threading.Thread(target=edit, args=(c,)) for c in (["Alpha"], ["Beta"])]
for t in threads:
    t.start()
for t in threads:
    t.join(10)
check("one wins, one is stale", sorted(outcomes), ["ok", "stale"])

print("J) the page sends only what changed")
node = shutil.which("node")
if not node:
    print("  [skip] node not on PATH — static/admin/users.js not exercised")
else:
    js = r"""
const vm = require('vm');
const fs = require('fs');
const el = () => ({ style: {}, classList: { add() {}, remove() {}, toggle() {} },
                    textContent: '', value: '', innerHTML: '' });
const ctx = { document: { getElementById: el, querySelectorAll: () => [] },
              fetch: () => new Promise(() => {}), window: { location: {} },
              setTimeout: () => 0, console };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), ctx);
const out = vm.runInContext(`
  CHARS = ['Alpha', 'Beta', 'Gamma'];
  const u = { username: 'demo', role: 'user',
              allowed_characters: ['Hidden', 'Alpha', 'Beta'], revision: 'r0' };
  ({
    unchanged: editBody(u, 'demo', 'user', ['Alpha', 'Beta']),
    role: editBody(u, 'demo', 'admin', ['Alpha', 'Beta']),
    list: editBody(u, 'demo', 'user', ['Alpha', 'Gamma']),
    name: editBody(u, 'demo2', 'user', ['Alpha', 'Beta']),
  })`, ctx);
process.stdout.write(JSON.stringify(out));
"""
    res = subprocess.run([node, "-e", js, str(ROOT / "static/admin/users.js")],
                         capture_output=True, text=True, timeout=60)
    if res.returncode != 0:
        FAILS.append(f"node run failed: {res.stderr.strip()[:400]}")
        print("  [FAIL] node run:", res.stderr.strip()[:400])
    else:
        got = json.loads(res.stdout)
        check("nothing changed", got["unchanged"], {"base_revision": "r0"})
        check("only the role", got["role"], {"base_revision": "r0", "role": "admin"})
        check("list edit", got["list"],
              {"base_revision": "r0", "allowed_characters": ["Hidden", "Alpha", "Gamma"]})
        check("only the username", got["name"], {"base_revision": "r0", "username": "demo2"})

print()
for connection in db._connections.values():
    connection.close()
shutil.rmtree(STORAGE, ignore_errors=True)
if FAILS:
    print(f"FAILED ({len(FAILS)}):")
    for f in FAILS:
        print("  -", f)
    sys.exit(1)
print("all checks passed")
