"""Smoke: the avatar switch and the access grant of linked characters write
user settings under the per-user ``user_settings`` lock, from a fresh read.

Usage:
    ./.venv/bin/python scripts/smoke_linked_avatar_settings_lock.py

Runs against a temp world (no server, no real world DB).

Derivation (account._update_current_user_settings: every user-settings
read-modify-write takes ``keyed_lock("user_settings", <user id>)`` and re-reads
the user INSIDE the lock; linked_characters._switch_avatars /
_grant_like_leader must do the same — review 10#1):

Fixture: user "demo" (role user), settings {active_character: Tilda,
current_character: Tilda}, allowed_characters [Tilda].

[A] Snapshot race (a layout save lands after the users were listed, before
    the switch writes). ``list_users`` is wrapped so that right after it
    returns its snapshot, settings key ``layout`` = {"w": 1} is written for
    demo (as the autosave would). Then _switch_avatars(Tilda, Glut):
    returns [demo id]; settings active_character Glut, current_character
    Glut, layout {"w": 1} still there; allowed [Tilda, Glut].
    (The old body merged into the snapshot: layout gone.)
[B] Lock race (a settings save read BEFORE the switch, writes AFTER it).
    demo reset to active Tilda, allowed [Tilda]. Thread T takes
    keyed_lock("user_settings", demo id), reads demo, then waits for a go
    signal; meanwhile the switch runs in thread S. After 0.3 s S must still
    be running (blocked on T's lock) -> True. Go: T writes its read settings
    plus ``named`` = "n1" and releases; S then re-reads. Final: active
    Glut, named "n1" kept, allowed [Tilda, Glut].
    (The old body did not wait: S finished first, then T's write put
    active_character back to Tilda.)
[C] Grant snapshot race. demo allowed reset to [Tilda]. ``list_users`` is
    wrapped so that after the snapshot demo's allowed becomes [Tilda, Obs].
    _grant_like_leader(Glut, Tilda) -> allowed [Tilda, Obs, Glut].
    (The old body appended to the snapshot list: [Tilda, Glut], Obs lost.)
[D] Grant waits for the lock: allowed reset to [Tilda]; T holds the lock
    for 0.6 s, then appends Obs (read inside the lock) and releases; the
    grant in thread S, started once T holds the lock, is still running at
    0.3 s -> True; final allowed [Tilda, Obs, Glut].
    (The old body did not wait: it was done before 0.3 s -> False, and its
    write landed first, so T's append gave [Tilda, Glut, Obs].)
"""
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(tempfile.mkdtemp(prefix="linked-avatar-lock-smoke-"))
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

from app.core import users  # noqa: E402
from app.core import linked_characters as lc  # noqa: E402
from app.core.keyed_lock import keyed_lock  # noqa: E402

FAILURES = []
CHECKED = 0


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'OK ' if ok else 'FAIL'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


UID = users.create_user("demo", "password-123", role=users.ROLE_USER,
                        allowed_characters=["Tilda"])


def reset(allowed=("Tilda",)):
    users.update_user(UID, settings={"active_character": "Tilda",
                                     "current_character": "Tilda"},
                      allowed_characters=list(allowed))


def fresh():
    return users.get_user_by_id(UID)


_REAL_LIST = users.list_users


def list_then(write):
    """A ``list_users`` whose snapshot is taken BEFORE ``write`` runs."""
    def _wrapped():
        snapshot = _REAL_LIST()
        write()
        return snapshot
    return _wrapped


def add_settings_key(key, value):
    u = fresh()
    s = dict(u["settings"])
    s[key] = value
    users.update_user(UID, settings=s)


# ── [A] ─────────────────────────────────────────────────────────────────────
print("[A] switch: snapshot race")
reset()
users.list_users = list_then(lambda: add_settings_key("layout", {"w": 1}))
try:
    switched = lc._switch_avatars("Tilda", "Glut")
finally:
    users.list_users = _REAL_LIST
u = fresh()
check("switched ids", switched, [UID])
check("active_character", u["settings"].get("active_character"), "Glut")
check("current_character", u["settings"].get("current_character"), "Glut")
check("layout kept", u["settings"].get("layout"), {"w": 1})
check("allowed", u["allowed_characters"], ["Tilda", "Glut"])

# ── [B] ─────────────────────────────────────────────────────────────────────
print("[B] switch: waits for the user_settings lock")
reset()
held = threading.Event()
go = threading.Event()


def settings_save():
    with keyed_lock("user_settings", UID):
        settings = dict(fresh()["settings"])
        held.set()
        go.wait(5)
        settings["named"] = "n1"
        users.update_user(UID, settings=settings)


t = threading.Thread(target=settings_save)
t.start()
held.wait(5)
s = threading.Thread(target=lc._switch_avatars, args=("Tilda", "Glut"))
s.start()
time.sleep(0.3)
check("switch blocked while the save holds the lock", s.is_alive(), True)
go.set()
t.join(5)
s.join(5)
u = fresh()
check("active_character", u["settings"].get("active_character"), "Glut")
check("named kept", u["settings"].get("named"), "n1")
check("allowed", u["allowed_characters"], ["Tilda", "Glut"])

# ── [C] ─────────────────────────────────────────────────────────────────────
print("[C] grant: snapshot race")
reset()
users.list_users = list_then(
    lambda: users.update_user(UID, allowed_characters=["Tilda", "Obs"]))
try:
    lc._grant_like_leader("Glut", "Tilda")
finally:
    users.list_users = _REAL_LIST
check("allowed", fresh()["allowed_characters"], ["Tilda", "Obs", "Glut"])

# ── [D] ─────────────────────────────────────────────────────────────────────
print("[D] grant: waits for the user_settings lock")
reset()
held.clear()


def other_grant():
    with keyed_lock("user_settings", UID):
        held.set()
        time.sleep(0.6)
        allowed = list(fresh()["allowed_characters"])
        users.update_user(UID, allowed_characters=allowed + ["Obs"])


t = threading.Thread(target=other_grant)
t.start()
held.wait(5)
s = threading.Thread(target=lc._grant_like_leader, args=("Glut", "Tilda"))
s.start()
time.sleep(0.3)
check("grant blocked while the lock is held", s.is_alive(), True)
t.join(5)
s.join(5)
check("allowed", fresh()["allowed_characters"], ["Tilda", "Obs", "Glut"])

print(f"\n{CHECKED - len(FAILURES)}/{CHECKED} checks passed")
if FAILURES:
    print("FAILED:", ", ".join(FAILURES))
    sys.exit(1)
