"""Smoke: the login avatar restore, the orphaned-avatar reaper and the
creator grant write the users table under the per-user ``user_settings``
lock, from a fresh read, changing only their own keys.

Usage:
    ./.venv/bin/python scripts/smoke_user_settings_writers_lock.py

Runs against a temp world (no server, no real world DB). Sibling of
scripts/smoke_linked_avatar_settings_lock.py (review 10#1 follow-up).

Derivation (account._update_current_user_settings: every user-settings
read-modify-write takes ``keyed_lock("user_settings", <user id>)`` and re-reads
the user INSIDE the lock). The lock-wait checks use events, not sleeps: the
holder waits for a "go" the main thread sends only after it has looked at the
waiter; the waiter gets a generous 2 s to finish if it does NOT wait (the old
code finishes in milliseconds), and the new code waits however loaded the
machine is, so the window cannot produce a false failure.

Fixture: users (role user) "demo" (allowed [Tilda]), "demo2" (allowed [Kira]),
"demo3" (allowed [Mo]), "demo4" (allowed [Ann]); no sessions at first.

[A] Login restore merges into a FRESH read. ``snap`` = demo as the password
    check returned it, settings {active_character: Tilda}. Then a layout save
    stores ``layout`` = {"w": 1}. restore_avatar_on_login(snap): settings
    avatar_released False, active_character Tilda, current_character Tilda,
    layout {"w": 1} kept. (Old: merged into snap -> layout None.)
[B] Login restore waits for the lock. demo settings {active_character:
    Tilda, avatar_released: True}. T holds the lock, reads, waits for go;
    restore runs in S from the same stale snapshot. 2 s later S is still
    alive -> True. go: T writes its read settings + named "n1". S then
    re-reads: avatar_released False, named "n1". (Old: S wrote first, then
    T's write put avatar_released True back -> True.)
[C] Reaper keeps a login that happened after its session scan. demo2
    settings {active_character: Kira}, no session. ``list_users`` is wrapped:
    after the reaper's snapshot, demo2 logs in (create_session, then
    restore_avatar_on_login of the fresh user). Reaper -> demo2
    active_character still Kira. (Old: its session scan predates the login,
    so it cleared it -> "".)
[D] Reaper keeps a layout key saved after its snapshot. demo3 settings
    {active_character: Mo}, no session; after the snapshot ``layout`` =
    {"h": 2} is stored for demo3. Reaper -> active_character "",
    current_character "", layout {"h": 2} kept. (Old: layout None.)
[E] Creator grant re-reads. ``creator`` = demo4 as authenticated, allowed
    [Ann]; then allowed becomes [Ann, Obs] (a grant elsewhere).
    character_ops._grant_to_creator(creator, "New") -> [Ann, Obs, New].
    (Old inline body appended to creator's copy: [Ann, New].)
[F] Creator grant waits for the lock: demo4 allowed reset to [Ann]; T holds
    the lock, waits for go; the grant in S is alive after 2 s -> True; go: T
    appends Obs to what it reads (inside the lock); final [Ann, Obs, New].
"""
import os
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(tempfile.mkdtemp(prefix="user-settings-writers-smoke-"))
STORAGE = ROOT / "world"
STORAGE.mkdir()
os.environ["STORAGE_DIR"] = str(STORAGE)
os.environ["INSTANCE_DIR"] = str(ROOT / "instance")
os.environ["ANIMATION_CLIPS_DIR"] = str(ROOT / "clips")
os.environ["ANIMATION_RIG_FILE"] = str(ROOT / "rig.fbx")
(STORAGE / "config.json").write_text("{}", encoding="utf-8")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
paths.init_instance(ROOT / "instance")
from app.core import config, db  # noqa: E402
config.load(STORAGE / "config.json")
db.init_schema()

from app.core import sessions, users  # noqa: E402
from app.core import character_ops  # noqa: E402
from app.core.keyed_lock import keyed_lock  # noqa: E402
from app.models import account  # noqa: E402

FAILURES = []
CHECKED = 0
WAIT = 2.0


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'OK ' if ok else 'FAIL'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


U1 = users.create_user("demo", "password-123", allowed_characters=["Tilda"])
U2 = users.create_user("demo2", "password-123", allowed_characters=["Kira"])
U3 = users.create_user("demo3", "password-123", allowed_characters=["Mo"])
U4 = users.create_user("demo4", "password-123", allowed_characters=["Ann"])


def fresh(uid):
    return users.get_user_by_id(uid)


def put_key(uid, key, value):
    s = dict(fresh(uid)["settings"])
    s[key] = value
    users.update_user(uid, settings=s)


_REAL_LIST = users.list_users


def list_then(write):
    def _wrapped():
        snapshot = _REAL_LIST()
        write()
        return snapshot
    return _wrapped


def run_against_holder(target, args, holder_write):
    """T holds the user_settings lock of the uid ``holder_write`` names, S runs
    ``target(*args)``. Returns whether S was still waiting after WAIT s."""
    uid, write = holder_write
    held, go = threading.Event(), threading.Event()

    def holder():
        with keyed_lock("user_settings", uid):
            snapshot = fresh(uid)
            held.set()
            go.wait(30)
            write(snapshot)

    t = threading.Thread(target=holder)
    t.start()
    held.wait(30)
    s = threading.Thread(target=target, args=args)
    s.start()
    s.join(WAIT)
    waited = s.is_alive()
    go.set()
    t.join(30)
    s.join(30)
    return waited


# ── [A] ─────────────────────────────────────────────────────────────────────
print("[A] login restore: fresh read")
users.update_user(U1, settings={"active_character": "Tilda"})
snap = fresh(U1)
put_key(U1, "layout", {"w": 1})
account.restore_avatar_on_login(snap)
s = fresh(U1)["settings"]
check("avatar_released", s.get("avatar_released"), False)
check("active/current", (s.get("active_character"), s.get("current_character")), ("Tilda", "Tilda"))
check("layout kept", s.get("layout"), {"w": 1})

# ── [B] ─────────────────────────────────────────────────────────────────────
print("[B] login restore: waits for the lock")
users.update_user(U1, settings={"active_character": "Tilda", "avatar_released": True})
snap = fresh(U1)


def _save_named(read_user):
    st = dict(read_user["settings"])
    st["named"] = "n1"
    users.update_user(U1, settings=st)


waited = run_against_holder(account.restore_avatar_on_login, (snap,), (U1, _save_named))
s = fresh(U1)["settings"]
check("restore waited for the lock", waited, True)
check("avatar_released", s.get("avatar_released"), False)
check("named kept", s.get("named"), "n1")

# ── [C] ─────────────────────────────────────────────────────────────────────
print("[C] reaper: a login after its session scan")
users.update_user(U2, settings={"active_character": "Kira"})


def _login_demo2():
    sessions.create_session(U2)
    account.restore_avatar_on_login(fresh(U2))


users.list_users = list_then(_login_demo2)
try:
    account.reap_orphaned_avatars()
finally:
    users.list_users = _REAL_LIST
check("demo2 keeps Kira", fresh(U2)["settings"].get("active_character"), "Kira")

# ── [D] ─────────────────────────────────────────────────────────────────────
print("[D] reaper: a layout save after its snapshot")
users.update_user(U3, settings={"active_character": "Mo"})
users.list_users = list_then(lambda: put_key(U3, "layout", {"h": 2}))
try:
    account.reap_orphaned_avatars()
finally:
    users.list_users = _REAL_LIST
s = fresh(U3)["settings"]
check("demo3 released", (s.get("active_character"), s.get("current_character")), ("", ""))
check("layout kept", s.get("layout"), {"h": 2})

# ── [E] ─────────────────────────────────────────────────────────────────────
print("[E] creator grant: fresh read")
creator = fresh(U4)
users.update_user(U4, allowed_characters=["Ann", "Obs"])
character_ops._grant_to_creator(creator, "New")
check("allowed", fresh(U4)["allowed_characters"], ["Ann", "Obs", "New"])

# ── [F] ─────────────────────────────────────────────────────────────────────
print("[F] creator grant: waits for the lock")
users.update_user(U4, allowed_characters=["Ann"])
creator = fresh(U4)
waited = run_against_holder(
    character_ops._grant_to_creator, (creator, "New"),
    (U4, lambda read_user: users.update_user(
        U4, allowed_characters=list(read_user["allowed_characters"]) + ["Obs"])))
check("grant waited for the lock", waited, True)
check("allowed", fresh(U4)["allowed_characters"], ["Ann", "Obs", "New"])

print(f"\n{CHECKED - len(FAILURES)}/{CHECKED} checks passed")
if FAILURES:
    print("FAILED:", ", ".join(FAILURES))
    sys.exit(1)
