#!/usr/bin/env python3
"""Position-origin and session-order smoke, contract A15.

Usage: ./.venv/bin/python scripts/smoke_pos_origin.py

Hand derivation: (1,2) stamped A/7 keeps precisely that origin; an ordinary
write and pool reset clear it. A/500 -> B/1 retires A, so A/501 writes nothing.
B/2 moves 1 m in (340-5)/1000 = .335 s, below the 5 m floor.
After 60 s, A/3 is still older than A/5; A/6 may move 3 m (<5 m).
An unstamped write clears origin/time basis, not A's highest accepted number 7.
A new B/1 resets that order. SQL lint at 15924012 finds three bare statements
(character UPDATE and INSERT, pool UPDATE); adjacent literals are one statement.
All storage is temporary; expected numbers are independent of implementation.
Validation: a trailing newline is outside the session alphabet, so returns 400.
Facing (yaw, radians): a report with yaw 1.5 stores 1.5 and the avatar's map
row says 1.5, an NPC row null; a report WITHOUT yaw keeps 1.5; yaw 7.0 is
stored as remainder(7, 2*pi) = 7 - 6.283185 = 0.716815 -> 0.7168 (4 places);
yaw -3.5 -> -3.5 + 6.283185 = 2.783185 -> 2.7832; true / "x" / NaN return
400 and leave 2.7832. Every server writer clears it: set_character_pos
without yaw, the owned-runtime commit (write_effect_profile) with pos_x, the
pool unplace. The SQL lint additionally demands pos_yaw in every pos_x write
(fails on ad79c128: 4 statements — the character UPDATE and INSERT, the
travel tick UPDATE, the pool UPDATE; the sleep/stand UPDATE is built from
fragments the lint cannot join and clears pos_yaw by hand).
10**400 exceeds the finite float range for x/z/t_ms and the seq maximum;
each field must return 400 rather than raising an overflow error.
"""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_tmp = tempfile.TemporaryDirectory(prefix="pos-origin-")
os.environ["STORAGE_DIR"] = _tmp.name
os.environ["INSTANCE_DIR"] = str(Path(_tmp.name) / "instance")
os.environ["ANIMATION_CLIPS_DIR"] = str(Path(_tmp.name) / "clips")
from app.core import paths
paths.init(_tmp.name)
paths.init_instance(Path(_tmp.name) / "instance")
from app.core import db
db.init_schema()
from app.models.character import (set_character_pos, get_avatar_sync_snapshot,
    save_character_profile)
from app.core.keyed_lock import keyed_lock
from app.core.db import transaction
from app.core.timeutils import motion_time
from app.core.world_ops import build_worldmap_payload
from app.routes import play
from fastapi import HTTPException

failures = []
def check(label, got, want):
    print(f"{'PASS' if got == want else 'FAIL'} {label}: {got!r}")
    if got != want:
        failures.append((label, got, want))

save_character_profile("demo", {}, create_new=True)
save_character_profile("npc_other", {}, create_new=True)

def _store(profile_journey, profile_target, meta_target):
    with keyed_lock("character_profile", "demo"), transaction() as conn:
        conn.execute("UPDATE characters SET profile_json = json_set(profile_json, "
                     "'$.journey', json(?), '$.movement_target', ?) WHERE name='demo'",
                     (json.dumps(profile_journey), profile_target))
        if meta_target is None:
            conn.execute("UPDATE character_state SET meta = json_remove(COALESCE(meta,'{}'), "
                         "'$.movement_target') WHERE character_name='demo'")
        else:
            conn.execute("UPDATE character_state SET meta = json_set(COALESCE(meta,'{}'), "
                         "'$.movement_target', ?) WHERE character_name='demo'", (meta_target,))

# origin_write: a report write stamps its origin
set_character_pos("demo", 1.0, 2.0, origin=("sessAAAA01", 7))
snap = get_avatar_sync_snapshot("demo")
check("origin_write", snap["origin"], {"session": "sessAAAA01", "seq": 7})
check("origin_write pos", snap["pos"], {"x": 1.0, "z": 2.0})
# foreign_write: any other writer clears it
set_character_pos("demo", 3.0, 2.0)
check("foreign_write", get_avatar_sync_snapshot("demo")["origin"], None)
# pool_reset: the npc_pool unplace clears pos AND origin
set_character_pos("demo", 1.0, 2.0, origin=("sessAAAA01", 8))
from app.core.npc_pool import _unplace   # npc_pool.py:82 — the pool's raw unplace
_unplace("demo")
s = get_avatar_sync_snapshot("demo")
check("pool_reset", (s["pos"], s["origin"]), (None, None))
# snapshot_journey: journey + movement_target come from the same SELECT and are validated.
# Write the profile under the profile lock like start_journey does (travel_engine.py:714-721):
J = {"target": "loc_a", "waypoints": [[0, 0, 0], [10, 0, 10]],
     "started_at_s": motion_time(), "speed_m_s": 1.0, "journey_id": "a" * 32}
_store(profile_journey=J, profile_target="", meta_target="loc_a")   # target in character_state.meta
check("snapshot meta target", get_avatar_sync_snapshot("demo")["journey"]["journey_id"], "a" * 32)
_store(profile_journey=J, profile_target="loc_a", meta_target=None)  # target ONLY in profile_json
check("snapshot profile-only target", get_avatar_sync_snapshot("demo")["journey"]["journey_id"], "a" * 32)
_store(profile_journey=J, profile_target="", meta_target="")         # mismatch -> no journey
check("snapshot mismatch", get_avatar_sync_snapshot("demo")["journey"], None)

A, B = "sessAAAA01", "sessBBBB02"
def report(body):
    if "demo" in play._pos_report_at:
        import time
        play._pos_report_at["demo"] = min(play._pos_report_at["demo"], time.monotonic() - 1.0)
    with play._pos_lock("demo"):
        try:
            return play._play_pos_report("demo", body)
        except HTTPException as exc:
            return exc.status_code

def stamped(session, seq, t_ms, x=0, z=0):
    return report(dict(x=x, z=z, session=session, seq=seq, t_ms=t_ms))

for label, fields in [
    ("session_trailing_newline", dict(session="sessAAAA01\n")),
    ("x_overflow", dict(x=10**400)), ("z_overflow", dict(z=10**400)),
    ("seq_overflow", dict(seq=10**400)), ("t_overflow", dict(t_ms=10**400)),
    ("bad_session", dict(session="x")), ("seq_zero", dict(seq=0)),
    ("seq_big", dict(seq=2**31)), ("seq_frac", dict(seq=1.5)),
    ("seq_float", dict(seq=1.0)), ("seq_bool", dict(seq=True)),
    ("t_nan", dict(t_ms=float("nan"))), ("t_negative", dict(t_ms=-1)),
    ("t_bool", dict(t_ms=True)), ("explicit_null", dict(seq=None,t_ms=None,session=None)),
]:
    body = dict(x=1,z=1,seq=1,t_ms=0,session=A)
    body.update(fields)
    check(label, report(body), 400)
check("partial", report(dict(x=1,z=1,seq=1,t_ms=0)), 400)
check("one_null", report(dict(x=1,z=1,seq=None)), 400)
check("unstamped", report(dict(x=1,z=1)).get("ok"), True)
check("unstamped origin", get_avatar_sync_snapshot("demo")["origin"], None)
check("takeover A", stamped(A,500,1000).get("ok"), True)
check("takeover B", stamped(B,1,5,1).get("ok"), True)
check("retired_late", stamped(A,501,1330,2), {"ok":False,"stale":True})
check("retired origin", get_avatar_sync_snapshot("demo")["origin"], {"session":B,"seq":1})
check("retired pos", get_avatar_sync_snapshot("demo")["pos"], {"x":1.,"z":0.})
check("B step", stamped(B,2,340,2).get("ok"), True)
# Independent accepted-order scenario, with a fresh process-local session inventory.
for state in (play._pos_session_current, play._pos_session_retired,
              play._pos_session_seq, play._pos_client_at):
    state.pop("demo", None)
check("same_session baseline", stamped(A,5,1000).get("ok"), True)
import time
later = time.monotonic() + 60
with patch("time.monotonic", return_value=later):
    check("same_session_late", stamped(A,3,500), {"ok":False,"stale":True})
    check("long_pause", stamped(A,6,61000,3).get("ok"), True)
check("mixed baseline", stamped(A,7,62000,3).get("ok"), True)
check("mixed unstamped", report(dict(x=3,z=0)).get("ok"), True)
check("mixed_unstamped", stamped(A,4,600,3), {"ok":False,"stale":True})
check("takeover_resets_order", stamped(B,1,5,3).get("ok"), True)
set_character_pos("demo",1,2,origin=(A,9))
set_character_pos("npc_other",3,2)
rows = {c["name"]:c for c in build_worldmap_payload("demo", show_all=True)["characters"]}
check("map avatar origin", rows["demo"]["pos_origin"], {"session":A,"seq":9})
check("map foreign origin", rows["npc_other"]["pos_origin"], None)

# Facing: stored with the accepted report, kept by a report without one,
# cleared by every server writer.
def facing():
    return get_avatar_sync_snapshot("demo")["yaw"]
for state in (play._pos_session_current, play._pos_session_retired,
              play._pos_session_seq, play._pos_client_at):
    state.pop("demo", None)
set_character_pos("demo", 1, 2)
check("yaw report", report(dict(x=1, z=2, yaw=1.5)).get("ok"), True)
check("yaw stored", facing(), 1.5)
rows = {c["name"]: c for c in build_worldmap_payload("demo", show_all=True)["characters"]}
check("map avatar yaw", rows["demo"]["yaw"], 1.5)
check("map npc yaw", rows["npc_other"]["yaw"], None)
check("yaw absent keeps", (report(dict(x=1.5, z=2)).get("ok"), facing()), (True, 1.5))
check("yaw null keeps", (report(dict(x=1.5, z=2, yaw=None)).get("ok"), facing()), (True, 1.5))
check("yaw wraps", (report(dict(x=1.5, z=2, yaw=7.0)).get("ok"), facing()), (True, 0.7168))
check("yaw wraps negative", (report(dict(x=1.5, z=2, yaw=-3.5)).get("ok"), facing()), (True, 2.7832))
for label, bad_yaw in (("yaw bool", True), ("yaw text", "x"), ("yaw nan", float("nan"))):
    check(label, (report(dict(x=1.5, z=2, yaw=bad_yaw)), facing()), (400, 2.7832))
set_character_pos("demo", 4, 2)
check("yaw server move clears", facing(), None)
report(dict(x=4, z=2, yaw=1.0))
from app.models.character import write_effect_profile, get_character_profile
with transaction() as conn:
    write_effect_profile(conn, "demo", get_character_profile("demo"),
                         runtime=dict(pos_x=5.0, pos_z=2.0, pos_session=None, pos_seq=None))
check("yaw runtime commit clears", (get_avatar_sync_snapshot("demo")["pos"], facing()),
      ({"x": 5.0, "z": 2.0}, None))
report(dict(x=5, z=2, yaw=1.0))
_unplace("demo")
check("yaw pool clears", facing(), None)

import ast, pathlib, re
_WRITE = re.compile(r"\b(UPDATE|INSERT\s+INTO)\s+character_state\b", re.I)

def unstamped_pos_writes(source: str, filename: str = "<src>") -> list:
    """Every SQL string constant that WRITES character_state.pos_x without also
    naming pos_session, pos_seq AND pos_yaw — one finding per statement (line number)."""
    out = []
    for node in ast.walk(ast.parse(source, filename)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            sql = node.value
            if _WRITE.search(sql) and re.search(r"\bpos_x\b", sql):
                if not all(re.search(rf"\b{column}\b", sql) for column in ("pos_session", "pos_seq", "pos_yaw")):
                    out.append(f"{filename}:{node.lineno}")
    return out

# negative fixtures — the checker itself must catch each statement on its own
FIX = ('cur.execute("UPDATE character_state SET pos_x=?, pos_z=?, pos_session=?, pos_seq=?, pos_yaw=? "\n'
       '            "WHERE character_name=?")\n'
       'cur.execute("INSERT INTO character_state (character_name, pos_x, pos_z) "\n'
       '            "VALUES (?, ?, ?)")\n')
check("lint catches the bare INSERT", unstamped_pos_writes(FIX), ["<src>:3"])
check("lint passes a stamped UPDATE", unstamped_pos_writes(
    'x("UPDATE character_state SET pos_x=NULL, pos_session=NULL, pos_seq=NULL, pos_yaw=NULL")'), [])
check("lint catches a write without pos_yaw", unstamped_pos_writes(
    'x("UPDATE character_state SET pos_x=NULL, pos_session=NULL, pos_seq=NULL")'), ["<src>:1"])
check("lint ignores SELECT", unstamped_pos_writes('x("SELECT pos_x FROM character_state")'), [])
bad = []
for p in sorted(list(pathlib.Path("app").rglob("*.py")) + list(pathlib.Path("plugins").rglob("*.py"))):
    bad += unstamped_pos_writes(p.read_text(encoding="utf-8"), str(p))
check("lint pos origin columns", bad, [])
# A furniture run APPROACHING owns the avatar (A15 row 1a, 2026-11-03: an
# NPC's consent started the run between two state polls, the client's next
# report cancelled it with "position"). A run row holding demo's person claim
# with status approaching, avatar at (40, 40), report (40.5, 40) -> 200
# {ok: false, server_owned: true}, the stored point stays (40, 40); the run
# gone -> the same report is written.
from app.core import prop_action_store as runs
set_character_pos("demo", 40.0, 40.0)
before = get_avatar_sync_snapshot("demo")["pos"]
with transaction() as conn:
    conn.execute(
        "INSERT INTO prop_action_runs (execution_id, actor, partner, request_fingerprint, action_id, "
        "definition_revision, status, target, definition, data, created_at, updated_at) "
        "VALUES ('run1', 'demo', 'npc_other', 'f', 'a', 'r', 'approaching', '{}', '{}', '{}', 't', 't')")
    conn.execute("INSERT INTO prop_action_claims VALUES (?, 'run1', 'person', ?)",
                 (runs.person_key("demo"), json.dumps({"name": "demo"})))
moved = dict(x=before["x"] + 0.5, z=before["z"])
check("approach owns the avatar", report(dict(moved)), {"ok": False, "server_owned": True})
check("approach point unchanged", get_avatar_sync_snapshot("demo")["pos"], before)
with transaction() as conn:
    conn.execute("DELETE FROM prop_action_runs WHERE execution_id='run1'")  # claims cascade
check("without the run the report lands", report(dict(moved)).get("ok"), True)
check("landed point", get_avatar_sync_snapshot("demo")["pos"], moved)

print(f"Position origin: {len(failures)} failures")
_tmp.cleanup()
raise SystemExit(bool(failures))
