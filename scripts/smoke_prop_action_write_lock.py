#!/usr/bin/env python3
"""Prop-action admission: a short write lock, a state read that does not wait,
one actor request at a time, and cheaper offers.

Usage: ./.venv/bin/python scripts/smoke_prop_action_write_lock.py

Runs on the private temp world of ``smoke_prop_action_paths`` (imported via
``smoke_prop_action_runs``, which calls ``paths.init(<tmp>)`` before any world-DB
module). No LLM, image or Blender work (the fixture's tripwire is checked).

Expected values, derived by hand
---------------------------------------------------------------------------
[1] Write lock. The claim re-checks what the plan rested on (validate, planning
    state, slot occupancy) under the place lock but BEFORE ``BEGIN IMMEDIATE``;
    only the claim SQL runs in the write transaction. The second
    ``_planning_state`` call of one admission is that re-check; it is slowed by
    2.0 s. A second thread that writes through ``db.transaction()`` 0.2 s into
    that pause must get no "database is locked" and wait <= 0.5 s (the old code
    held BEGIN IMMEDIATE across the re-check: it waited the remaining ~1.8 s).
    Every ``store.transaction()`` span of the admission lasts < 0.5 s (only a
    few SELECT/INSERT statements). The admission still succeeds: "approaching".
[2] Two actors in the room admit the same solo action on the one-slot seat at
    once; both finish planning (barrier after ``_plan``) before either claims.
    The place lock serialises the claims: exactly one "approaching", the other
    refused "no_free_slot" (the winner's committed slot claim shows up in the
    loser's occupancy re-check) — no IntegrityError, no "participant_claimed".
[3] ``state_for`` while another thread holds the run lock for 3 s: it returns
    within 1 s (lock wait 0.25 s + reads) and still lists the run with its last
    committed status (old code: blocked ~3 s).
[4] Narration and the claim re-check reuse the admission's geometry: an
    invitation (pair, "ask") composes the room (``places._compose``) exactly
    twice — the definition preflight of ``request_with_creation`` (its own
    query, untouched here) and the admission's query; the old code composed it
    four times (+ claim re-check, + narration). The room line reads
    "<inviter> suggests <pose label> to <invitee>.". A direct ``_narrate`` with
    the "{actor} uses {prop}." form gives the same text with and without a
    passed query, and composes nothing when one is passed.
[5] One request per actor at a time (``request_guard``): while thread A is
    inside the guard with nonce n1, the same actor with nonce n2 is refused at
    once (< 0.2 s) with ``RequestInProgress``; the HTTP adapter answers 409
    {"status": "refused", "reason": "request_in_progress"} and the NPC adapter
    ``prop_actions.execute`` returns that refusal as a dict. The same nonce n1
    from another thread WAITS (serialised replay): it enters only after A left
    (>= the 0.5 s A holds it). The same thread may nest the guard.
[6] Clip library fingerprint: memoised per library root for
    _FINGERPRINT_TTL_S = 5 s (monotonic). After a fill, 3 more
    ``clip_entries()`` calls scandir nothing (old: one scandir per existing root
    and call; the fixture's licensed root does not exist -> 1 x 3 = 3). A clip file
    added (dir mtime dated back, i.e. settled) is not seen within the TTL,
    ``reload_clip_caches()`` (what every library writer calls) makes it visible
    at once; another addition is seen once the monotonic clock passes the TTL.
[7] ``places.inside`` per approach plan reuses the query's location list: a
    seat with capacity 3 gives 3 solo allocations -> 3 plans -> 3 ``inside``
    calls; ``list_locations`` is read once per query (old: 3 times). The check
    stays enabled.
[8] ``prompt_block`` (cache contract of the chat prompt): the text built with
    the memoised fingerprint and the shared location list is byte-identical to
    the one built with TTL 0 and a fresh ``list_locations`` per ``inside``.
[9] ``llm_stats.record_call`` while another connection holds BEGIN IMMEDIATE:
    it waits at most _STATS_BUSY_TIMEOUT_MS = 250 ms (old: busy_timeout 5000 ms),
    so it returns in < 1 s without raising; the row is dropped; the thread's
    connection is back to busy_timeout 5000. Lock released: the next call writes
    its row (count 0 -> 1).
"""
import os
import sqlite3
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import smoke_prop_action_runs as RUNS  # noqa: E402  (paths.init on a temp world)

F, A, R = RUNS.F, RUNS.A, RUNS.R
from app.core import paths  # noqa: E402
paths.init(F.ROOT / "world")  # the fixture's private world (already set by the import)
from app.core import db, places, prop_actions  # noqa: E402
from app.core import animation_clips as clips  # noqa: E402
from app.models import world as world_model  # noqa: E402

failed = 0


def ok(label, cond, detail=""):
    global failed
    print(("  OK  " if cond else "  FAIL ") + label + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        failed += 1


def cleanup():
    F.W.set_world_frozen(False)
    for run in R.live_runs():
        A.cancel(run["actor"], run["execution_id"])


def same_profile(name, like):
    """``name`` gets the measured-entry profile ``setup_run`` gave ``like``."""
    source = F.C.get_character_profile(like)
    profile = F.C.get_character_profile(name)
    profile.update(height=source.get("height"), template=source.get("template"),
                   status_effects=dict(source.get("status_effects") or {}))
    F.C.save_character_profile(name, profile)


db.get_connection().execute("CREATE TABLE IF NOT EXISTS smoke_write_probe (x INTEGER)")
db.get_connection().commit()

# [1] -----------------------------------------------------------------------
print("[1] the claim re-check runs outside the write transaction")
name, target, pid = RUNS.setup_run()
calls = {"n": 0}
in_recheck = threading.Event()
real_planning_state = A._planning_state


def slow_planning_state(run, query):
    calls["n"] += 1
    if calls["n"] == 2:
        in_recheck.set()
        time.sleep(2.0)
    return real_planning_state(run, query)


spans = []
real_transaction = R.transaction


def timed_transaction():
    from contextlib import contextmanager

    @contextmanager
    def span():
        started = time.perf_counter()
        try:
            with real_transaction() as conn:
                yield conn
        finally:
            spans.append(time.perf_counter() - started)
    return span()


writer = {}


def write_during_recheck():
    if not in_recheck.wait(10):
        writer["error"] = "the re-check never ran"
        return
    time.sleep(0.2)
    started = time.perf_counter()
    try:
        with db.transaction() as conn:
            conn.execute("INSERT INTO smoke_write_probe VALUES (1)")
    except sqlite3.OperationalError as exc:
        writer["error"] = repr(exc)
    writer["wait"] = time.perf_counter() - started


thread = threading.Thread(target=write_during_recheck)
thread.start()
with patch.object(A, "_planning_state", slow_planning_state), patch.object(R, "transaction", timed_transaction):
    result = RUNS.request(name, target)
thread.join(15)
ok("[1] admission succeeds", result["status"] == "approaching", str(result))
ok("[1] the re-check ran (2nd planning-state read)", calls["n"] >= 2, str(calls["n"]))
ok("[1] the concurrent writer got no 'database is locked'", "error" not in writer, writer.get("error", ""))
ok("[1] the concurrent writer waited <= 0.5 s", writer.get("wait", 99) <= 0.5, f"{writer.get('wait', 99):.2f} s")
ok("[1] every write-transaction span < 0.5 s", spans and max(spans) < 0.5,
   ", ".join(f"{s:.2f}" for s in spans))
execution_id = result["execution_id"]

# [3] (on the run of [1]) ---------------------------------------------------
print("[3] state_for does not wait for a held run lock")
held = threading.Event()
release = threading.Event()


def hold_run_lock():
    with A._lock(execution_id):
        held.set()
        release.wait(5)


holder = threading.Thread(target=hold_run_lock)
holder.start()
held.wait(5)
started = time.perf_counter()
state = A.state_for(name)
elapsed = time.perf_counter() - started
release.set()
holder.join(5)
row = next((r for r in state["current"] + state["outgoing"] if r["execution_id"] == execution_id), None)
ok("[3] state_for returns within 1 s", elapsed < 1.0, f"{elapsed:.2f} s")
ok("[3] the row is the committed one", row is not None and row["status"] == "approaching", str(row))
cleanup()

# [2] -----------------------------------------------------------------------
print("[2] two admissions on one slot: exactly one wins")
first, target, pid = RUNS.setup_run()
second = F.actor(target["location_id"], at=(2, 5))
same_profile(second, first)
barrier = threading.Barrier(2)
real_plan = A._plan


def plan_then_wait(*args, **kwargs):
    out = real_plan(*args, **kwargs)
    try:
        barrier.wait(10)
    except threading.BrokenBarrierError:
        pass
    return out


answers = {}


def admit(who):
    try:
        answers[who] = RUNS.request(who, target)
    except Exception as exc:  # an IntegrityError would land here
        answers[who] = {"status": "error", "reason": repr(exc)}


with patch.object(A, "_plan", plan_then_wait):
    threads = [threading.Thread(target=admit, args=(who,)) for who in (first, second)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
statuses = sorted((a["status"], a["reason"]) for a in answers.values())
ok("[2] one approaching, one refused no_free_slot",
   statuses == [("approaching", ""), ("refused", "no_free_slot")], str(statuses))
cleanup()

# [4] -----------------------------------------------------------------------
print("[4] narration reuses the admission's geometry")
inviter, partner, target, pid = RUNS.authored_pair()
built = {"n": 0}
real_compose = places._compose


def counting_compose(*args, **kwargs):
    built["n"] += 1
    return real_compose(*args, **kwargs)


lines = []
import app.core.perception as perception  # noqa: E402
with patch.object(places, "_compose", counting_compose), \
        patch.object(perception, "record_utterance", side_effect=lambda **kw: lines.append(kw["content"])):
    invited = RUNS.request(inviter, target, members=[partner])
ok("[4] the invitation waits for consent", invited["status"] == "awaiting_consent", str(invited))
ok("[4] the room is composed twice (preflight + admission)", built["n"] == 2, str(built["n"]))
from app.core.pose_catalog import pose_label  # noqa: E402
expected = f"{inviter} suggests {pose_label('run-pair', 'en')} to {partner}."
ok("[4] the room line", lines == [expected], f"{lines} != {[expected]}")
run = R.get(invited["execution_id"])
from app.core.keyed_lock import keyed_lock  # noqa: E402
fresh, passed = [], []
with patch.object(perception, "record_utterance", side_effect=lambda **kw: fresh.append(kw["content"])):
    with keyed_lock("smoke", "narrate"):
        A._narrate(run, "{actor} uses {prop}.")
query = places._GeometryQuery()
query.room_places(run["target"]["location_id"], run["target"]["room_id"])
built["n"] = 0
with patch.object(places, "_compose", counting_compose), \
        patch.object(perception, "record_utterance", side_effect=lambda **kw: passed.append(kw["content"])):
    with keyed_lock("smoke", "narrate"):
        A._narrate(run, "{actor} uses {prop}.", _query=query)
ok("[4] same text with a passed query", fresh == passed and len(fresh) == 1, f"{fresh} / {passed}")
ok("[4] a passed query composes nothing", built["n"] == 0, str(built["n"]))
cleanup()

# [5] -----------------------------------------------------------------------
print("[5] one request per actor at a time")
actor_name = "guard_actor"
inside = threading.Event()
leave = threading.Event()


def hold_guard():
    with A.request_guard(actor_name, "n1"):
        inside.set()
        leave.wait(5)


holder = threading.Thread(target=hold_guard)
holder.start()
inside.wait(5)
started = time.perf_counter()
try:
    with A.request_guard(actor_name, "n2"):
        refused = False
except A.RequestInProgress:
    refused = True
elapsed = time.perf_counter() - started
ok("[5] another nonce of the same actor is refused at once", refused and elapsed < 0.2,
   f"{refused} {elapsed:.2f} s")

from fastapi import HTTPException  # noqa: E402
import app.routes.prop_actions as route  # noqa: E402
body = route.ActionRequest(target=dict(location_id="l", room_id="r", placement_id="p", variant_uid="v"),
                           action_id="a", revision="x", request_id="n3")
with patch.object(route, "_avatar", return_value=actor_name):
    try:
        route._request_route(body, {"id": "u"})
        http = None
    except HTTPException as exc:
        http = exc
ok("[5] HTTP adapter: 409 request_in_progress",
   http is not None and http.status_code == 409 and http.detail.get("reason") == "request_in_progress",
   str(getattr(http, "detail", http)))
npc = prop_actions.execute(actor_name, dict(operation="request", action_id="a", revision="x",
                                            target=dict(location_id="l", room_id="r", placement_id="p",
                                                        variant_uid="v"), request_id="n4"))
ok("[5] NPC adapter: refused request_in_progress",
   npc.get("status") == "refused" and npc.get("reason") == "request_in_progress", str(npc))

replay = {}


def replay_n1():
    started = time.perf_counter()
    with A.request_guard(actor_name, "n1"):
        replay["entered_after"] = time.perf_counter() - started


replayer = threading.Thread(target=replay_n1)
replayer.start()
time.sleep(0.5)
leave.set()
holder.join(5)
replayer.join(5)
ok("[5] the same nonce waits for the first (serialised replay)",
   replay.get("entered_after", 0) >= 0.5, str(replay))
with A.request_guard(actor_name, "n5"):
    try:
        with A.request_guard(actor_name, "n6"):
            nested = True
    except A.RequestInProgress:
        nested = False
ok("[5] the same thread may nest the guard", nested)
with A.request_guard(actor_name, "n7"):
    pass
ok("[5] the actor is free again afterwards", True)

# [6] -----------------------------------------------------------------------
print("[6] clip library fingerprint memo")
clips.reload_clip_caches()
clips.clip_entries()
scans = {"n": 0}
real_scandir = os.scandir


def counting_scandir(*args, **kwargs):
    scans["n"] += 1
    return real_scandir(*args, **kwargs)


def backdate(path, seconds):
    stamp = time.time() - seconds
    os.utime(path, (stamp, stamp))


clip_dir = F.ROOT / "clips"
backdate(clip_dir, 10)
clips.reload_clip_caches()
clips.clip_entries()
with patch.object(clips.os, "scandir", counting_scandir):
    for _ in range(3):
        clips.clip_entries()
ok("[6] no scandir within the TTL", scans["n"] == 0, str(scans["n"]))
(clip_dir / "memo-probe.fbx").write_bytes(b"probe")
backdate(clip_dir, 8)
kinds = {e["kind"] for e in clips.clip_entries()}
ok("[6] within the TTL the new file is not seen yet", "memo-probe" not in kinds)
clips.reload_clip_caches()
kinds = {e["kind"] for e in clips.clip_entries()}
ok("[6] reload_clip_caches makes it visible at once", "memo-probe" in kinds)
(clip_dir / "memo-later.fbx").write_bytes(b"probe")
backdate(clip_dir, 7)
now = time.monotonic()
with patch.object(clips, "_monotonic", lambda: now + clips._FINGERPRINT_TTL_S + 1):
    kinds = {e["kind"] for e in clips.clip_entries()}
ok("[6] after the TTL a change is seen without a reload", "memo-later" in kinds)
(clip_dir / "memo-probe.fbx").unlink()
(clip_dir / "memo-later.fbx").unlink()
clips.reload_clip_caches()

# [7] -----------------------------------------------------------------------
print("[7] one location list per query")
name, target, pid = RUNS.setup_run()
doc = F.props.read_sidecar(pid)
doc["model_variants"][0]["markers"][0].update(capacity=3, spacing_m=.6)
F.props._write_sidecar(pid, doc)
target["definition_revision"] = F.props.get_prop(pid)["revision"]
places.invalidate()
reads = {"n": 0}
real_list = world_model.list_locations


def counting_list(*args, **kwargs):
    reads["n"] += 1
    return real_list(*args, **kwargs)


inside_calls = {"n": 0}
real_inside = places.inside


def counting_inside(*args, **kwargs):
    inside_calls["n"] += 1
    return real_inside(*args, **kwargs)


exact = {k: target[k] for k in ("location_id", "room_id", "placement_id", "variant_uid")}
with patch.object(world_model, "list_locations", counting_list), patch.object(places, "inside", counting_inside):
    checked = A.check(name, exact, target["action_id"], target["definition_revision"])
ok("[7] the check is enabled", checked["enabled"], str(checked))
ok("[7] three plans asked inside", inside_calls["n"] == 3, str(inside_calls["n"]))
ok("[7] list_locations read once", reads["n"] == 1, str(reads["n"]))

# [8] -----------------------------------------------------------------------
print("[8] prompt_block is byte-identical with the memo and the shared list")
prop_actions.invalidate_offers_cache()
block = prop_actions.prompt_block(name)
prop_actions.invalidate_offers_cache()
with patch.object(clips, "_FINGERPRINT_TTL_S", 0.0), \
        patch.object(places._GeometryQuery, "locations", lambda self: real_list()):
    clips.reload_clip_caches()
    reference = prop_actions.prompt_block(name)
ok("[8] identical text", block == reference, f"{block!r} != {reference!r}")
ok("[8] the block names the rest action", "Rest" in block, block)
cleanup()

# [9] -----------------------------------------------------------------------
print("[9] a stats row does not wait 5 s for the write lock")
from app.utils import llm_stats  # noqa: E402
holder = sqlite3.connect(str(db.get_db_path()), timeout=10)
try:
    holder.execute("BEGIN IMMEDIATE")
    started = time.perf_counter()
    try:
        llm_stats.record_call("smoke-model", "smoke-task", "smoke", 10, 5, 1.0)
        error = None
    except Exception as exc:
        error = exc
    elapsed = time.perf_counter() - started
finally:
    holder.rollback()
    holder.close()
ok("[9] record_call under a held lock: no error, < 1 s", error is None and elapsed < 1.0,
   f"{error!r} {elapsed:.2f} s")
ok("[9] busy_timeout back to 5000", db.get_connection().execute("PRAGMA busy_timeout").fetchone()[0] == 5000)
count = lambda: db.get_connection().execute(  # noqa: E731
    "SELECT COUNT(*) FROM llm_call_stats WHERE model='smoke-model'").fetchone()[0]
ok("[9] the locked row was dropped", count() == 0, str(count()))
llm_stats.record_call("smoke-model", "smoke-task", "smoke", 10, 5, 1.0)
ok("[9] lock released: the next row is written", count() == 1, str(count()))
F.assert_no_external_work()

print("FAILED" if failed else "Prop-action write-lock checks passed")
sys.exit(1 if failed else 0)
