"""Smoke: a character WITHOUT a character_state row is a valid character —
also for the strict readers the influence rules use.

Usage:
    ./.venv/bin/python scripts/smoke_state_row_missing.py

Runs against a temp world (no server, no real world DB).

Derivation: ``character_reset._reset_mechanical_state`` DELETES the
character_state row on purpose — "the profile's own values take over on the
next read". A missing row is therefore legitimate absence (default state, no
metre point), never a read error; strict mode only exists to tell a reader
FAILURE apart from a false/absent value.

Fixture: demo-a and demo-b (template human-roleplay), demo-b's
character_state row deleted.

[A] get_character_profile(demo-b, strict=True) returns the profile:
    character_name "demo-b", current_location "", current_room "".
[B] get_character_pos(demo-b, strict=True) is None (no point).
[C] stat_influence.influence_options() answers (a "stats" list, no raise).
[D] influence_rule_status of a wildcard rule (actor "", recipient "",
    stat "stamina") carries no "read_error" reason.
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(tempfile.mkdtemp(prefix="state-row-missing-smoke-"))
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

from app.models import character as ch  # noqa: E402

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


for _name in ("demo-a", "demo-b"):
    assert ch.save_character_profile(_name, {"character_name": _name,
                                             "template": "human-roleplay"},
                                     create_new=True), _name
with db.transaction() as conn:
    conn.execute("DELETE FROM character_state WHERE character_name=?", ("demo-b",))

print("[A] strict profile")
try:
    _p = ch.get_character_profile("demo-b", strict=True) or {}
    check("profile name", _p.get("character_name"), "demo-b")
    check("profile location", _p.get("current_location"), "")
    check("profile room", _p.get("current_room"), "")
except Exception as e:  # noqa: BLE001
    check("strict profile read", repr(e), "no error")

print("[B] strict position")
try:
    check("pos", ch.get_character_pos("demo-b", strict=True), None)
except Exception as e:  # noqa: BLE001
    check("strict pos read", repr(e), "no error")

print("[C] influence options")
from app.core import stat_influence  # noqa: E402
try:
    _o = stat_influence.influence_options()
    check("options have stats", isinstance(_o.get("stats"), list), True)
except Exception as e:  # noqa: BLE001
    check("influence_options", repr(e), "no error")

print("[D] influence rule status")
_rule = {"id": "demo-influence", "name": "Synthetic influence", "type": "influence",
         "condition": "", "actor_condition": "", "pair_conditions": [],
         "influence": {"actor": "", "recipient": "", "stat": "stamina",
                       "direction": "increase", "factor": 2}}
_st = stat_influence.influence_rule_status(_rule)
check("no read_error", [r for r in _st.get("reasons", []) if "read_error" in str(r)], [])

print(f"\n{CHECKED - len(FAILURES)}/{CHECKED} checks passed")
if FAILURES:
    print("FAILED:", ", ".join(FAILURES))
    sys.exit(1)
