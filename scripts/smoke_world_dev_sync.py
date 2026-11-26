#!/usr/bin/env python3
"""Smoke: World Dev free mode — update_character pushes profile changes.

Plan docs/superpowers/plans/2026-11-25-world-dev-free-remove-schema-modes.md,
Task 1 (decision D12). The removed /apply-profile-patch route sent
sync_topics.profile_patched after its write; update_character (and the undo
of its profile step) must do the same, INSIDE the profile lock right after
the journaled write / the undo's profile save, so a later group's refusal or
a later skip cannot drop it. A temp world (paths.init BEFORE any world-DB
import); no server, no LLM; every tool call goes through
world_dev_tools.run_tool. Usage:

    ./.venv/bin/python scripts/smoke_world_dev_sync.py

The pushes are recorded by replacing the module attributes
sync_topics.changed_at, sync_topics.avatars and sync_topics.moved
(profile_patched looks them up as module globals). Entries:
("changed_at", name, topics), ("avatars", [names], topics),
("moved", name, from, to).

Expected values, derived by hand from sync_topics.profile_patched: a changed
"current_location" -> moved; else a changed key in PUBLIC_PROFILE_KEYS ->
changed_at(name, topics=("presence", "self")); else avatars([name], "self").
PUBLIC_PROFILE_KEYS holds "gender" but not "dialogue_style". In
human-default.json both are profile fields (no store key); "importance" is
store "config" (base-character.json) — config changes push nothing (D9).

Fixture (run 1, turn 1): create_location "Demo Square" placed at (0, 0) with
a 10 m square boundary; create_character{data: {name: "Demo Npc", template:
"human-default", gender: "female"}, home: "Demo Square"}. Recorder cleared.

  (a) update_character{"Demo Npc", {dialogue_style: "calm"}} -> recorder ==
      [("avatars", ["Demo Npc"], "self")].
  (b) {gender: "male"} -> [("changed_at", "Demo Npc", ("presence", "self"))].
  (c) {dialogue_style: "calm"} again (stored value unchanged) -> [].
  (d) {importance: 3} (config only, D9) -> [].
  (e) Discard run 1 (world_dev_undo.undo, then status rolled_back). The
      recorder records only while world_dev_undo._undo_restore_character runs
      (the run's create_character / create_location inverses delete the
      character and the place and may push on their own — not this check's
      subject). Newest first: (d) restores only config -> nothing; (c) has an
      empty profile inverse -> nothing; (b) restores gender male -> female
      -> changed_at; (a) restores dialogue_style -> avatars. Recorded ==
      [("changed_at", "Demo Npc", ("presence", "self")),
       ("avatars", ["Demo Npc"], "self")].
  (f) Run 2, turn 1: fixture create_location "Demo Square" again (run 1's
      discard removed the first one) and create_character "Demo Npc Two"
      (same data, home "Demo Square"), recorder cleared. update_character{"Demo Npc Two",
      {gender: "male", dialogue_style: "calm", schedule: [{hour: 8, location:
      "Demo Square"}]}} with world_dev_apply._apply_home_and_schedule replaced
      by a function that raises ToolRefusal — the home group runs AFTER the
      profile step completed. (The plan named a stat group via
      _write_char_fields; human-default has no status field, so the home
      group is the later group used here.) Expected: the call is not ok
      (an "error: ..." line), and the recorder holds
      [("changed_at", "Demo Npc Two", ("presence", "self"))] (changed =
      {gender, dialogue_style}; gender is public -> one changed_at, no
      avatars). The writer is restored afterwards.
  (g) dialogue_style of "Demo Npc Two" is then set to "loud" directly
      (keyed_lock + save_character_profile — "someone else"). Recorder
      cleared, recording only inside _undo_restore_character. Discard run 2:
      the restore_character entry restores gender ("male" -> "female") and
      skips dialogue_style (changed since) -> recorded ==
      [("changed_at", "Demo Npc Two", ("presence", "self"))], and the undo
      report's skipped records name "profile.dialogue_style".

  (h) Run 3, turn 1: fixture create_location "Demo Square" again and
      create_character "Demo Npc Three" (same data), recorder cleared.
      app.models.character.save_character_config replaced by a function that
      returns False (update_character imports it at call time).
      update_character{"Demo Npc Three", {gender: "male", importance: 3}}:
      the profile save succeeds, the config save fails inside the same
      step. Expected: not ok (an "error: ..." line), gender stored "male",
      recorder == [("changed_at", "Demo Npc Three", ("presence", "self"))]
      (the profile half is stored and journaled by the reconcile, so it
      pushes; importance is config -> nothing). Writer restored; discard
      run 3 (recording only inside _undo_restore_character, as in (e)) ->
      complete, and the reconcile-journaled restore_character entry restores
      gender "male" -> "female" -> recorded ==
      [("changed_at", "Demo Npc Three", ("presence", "self"))]. (The
      character itself is then deleted by its create_character inverse, so
      the stored value cannot be read back afterwards.)

(a), (b), (e), (f), (g), (h) fail on commit a90d96e7e, the baseline before this
change (no push for profile fields); (c) and (d) pass on both.
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="smoke_wd_sync_clips_")
os.environ["STORAGE_DIR"] = tempfile.mkdtemp(prefix="smoke_wd_sync_")
os.environ["INSTANCE_DIR"] = tempfile.mkdtemp(prefix="smoke_wd_sync_inst_")

from app.core import paths  # noqa: E402

paths.init(Path(os.environ["STORAGE_DIR"]))

from app.core import db  # noqa: E402

db.init_schema()

from app.core import sync_topics  # noqa: E402
from app.core import world_dev_apply  # noqa: E402
from app.core import world_dev_runs as wr  # noqa: E402
from app.core import world_dev_tools as wt  # noqa: E402
from app.core import world_dev_undo as wu  # noqa: E402
from app.core.keyed_lock import keyed_lock  # noqa: E402
from app.models.character import (get_character_profile,  # noqa: E402
                                  save_character_profile)

failures = []


def check(label, cond, detail=None):
    print(("  ok   " if cond else "  FAIL ") + label
          + ("" if cond or detail is None else f"   -> {detail!r}"))
    if not cond:
        failures.append(label)


calls = []
gate = {"only_restore": False, "inside": False}


def _on():
    return not gate["only_restore"] or gate["inside"]


def rec_changed_at(character, loc_id=None, topics=None, **_kw):
    if _on():
        calls.append(("changed_at", character, tuple(topics or ())))


def rec_avatars(names, topics):
    if _on():
        calls.append(("avatars", list(names), topics))


def rec_moved(character, from_id, to_id):
    if _on():
        calls.append(("moved", character, from_id, to_id))


sync_topics.changed_at = rec_changed_at
sync_topics.avatars = rec_avatars
sync_topics.moved = rec_moved

_orig_restore = wu._undo_restore_character


def wrapped_restore(entry, inv):
    gate["inside"] = True
    try:
        return _orig_restore(entry, inv)
    finally:
        gate["inside"] = False


wu._undo_restore_character = wrapped_restore
# The undo dispatches through the op table built at import time: rebind its
# entry by name, so a moved dispatch fails here instead of recording nothing.
if wu._HANDLERS.get("restore_character") is not _orig_restore:
    print("FAIL: world_dev_undo._HANDLERS['restore_character'] is not "
          "_undo_restore_character; the recorder gate cannot be installed")
    sys.exit(1)
wu._HANDLERS["restore_character"] = wrapped_restore

SQUARE = [[-5, -5], [5, -5], [5, 5], [-5, 5]]
PUB = ("presence", "self")


def upd(ctx, name, patch):
    calls.clear()
    return wt.run_tool(ctx, "update_character", {"name": name, "patch": patch})


# ── Run 1 ────────────────────────────────────────────────────────────────
print("run 1")
run1 = wr.create_run("sync", "m", "p", "u", 40, 300000)
ctx1 = wt.ToolCtx(run_id=run1, turn=1)
res = wt.run_tool(ctx1, "create_location",
                  {"data": {"name": "Demo Square"}, "x": 0, "z": 0, "boundary": SQUARE})
check("fixture: Demo Square created", res.ok, res)
res = wt.run_tool(ctx1, "create_character",
                  {"data": {"name": "Demo Npc", "template": "human-default",
                            "gender": "female"}, "home": "Demo Square"})
check("fixture: Demo Npc created", res.ok, res)

res = upd(ctx1, "Demo Npc", {"dialogue_style": "calm"})
check("(a) ok", res.ok, res)
check("(a) private field -> avatars", calls == [("avatars", ["Demo Npc"], "self")], calls)

res = upd(ctx1, "Demo Npc", {"gender": "male"})
check("(b) ok", res.ok, res)
check("(b) public field -> changed_at", calls == [("changed_at", "Demo Npc", PUB)], calls)

res = upd(ctx1, "Demo Npc", {"dialogue_style": "calm"})
check("(c) ok", res.ok, res)
check("(c) unchanged -> no push", calls == [], calls)

res = upd(ctx1, "Demo Npc", {"importance": 3})
check("(d) ok", res.ok, res)
check("(d) config only -> no push", calls == [], calls)

calls.clear()
gate["only_restore"] = True
rep1 = wu.undo(run1)
gate["only_restore"] = False
wr.set_status(run1, "rolled_back")
check("(e) discard complete", rep1.get("complete"), rep1)
check("(e) undo pushes newest first",
      calls == [("changed_at", "Demo Npc", PUB), ("avatars", ["Demo Npc"], "self")], calls)

# ── Run 2 ────────────────────────────────────────────────────────────────
print("run 2")
run2 = wr.create_run("sync", "m", "p", "u", 40, 300000)
ctx2 = wt.ToolCtx(run_id=run2, turn=1)
res = wt.run_tool(ctx2, "create_location",
                  {"data": {"name": "Demo Square"}, "x": 0, "z": 0, "boundary": SQUARE})
check("fixture: Demo Square created again", res.ok, res)
res = wt.run_tool(ctx2, "create_character",
                  {"data": {"name": "Demo Npc Two", "template": "human-default",
                            "gender": "female"}, "home": "Demo Square"})
check("fixture: Demo Npc Two created", res.ok, res)

_orig_home = world_dev_apply._apply_home_and_schedule


def refusing_home(*_a, **_kw):
    raise wt.ToolRefusal("simulated home refusal")


world_dev_apply._apply_home_and_schedule = refusing_home
try:
    res = upd(ctx2, "Demo Npc Two", {"gender": "male", "dialogue_style": "calm",
                                     "schedule": [{"hour": 8, "location": "Demo Square"}]})
finally:
    world_dev_apply._apply_home_and_schedule = _orig_home
check("(f) later group refused -> not ok", not res.ok and res.line.startswith("error"), res)
prof2 = get_character_profile("Demo Npc Two") or {}
check("(f) profile step written",
      (prof2.get("gender"), prof2.get("dialogue_style")) == ("male", "calm"), prof2)
check("(f) push still sent", calls == [("changed_at", "Demo Npc Two", PUB)], calls)

with keyed_lock("character_profile", "Demo Npc Two"):
    p = dict(get_character_profile("Demo Npc Two") or {})
    p["dialogue_style"] = "loud"
    check("(g) foreign write stored", save_character_profile("Demo Npc Two", p))

calls.clear()
gate["only_restore"] = True
rep2 = wu.undo(run2)
gate["only_restore"] = False
wr.set_status(run2, "rollback_incomplete")
check("(g) partial undo pushes for the restored key",
      calls == [("changed_at", "Demo Npc Two", PUB)], calls)
named = [k for s in rep2.get("skipped") or [] for k in (s.get("keys") or [])]
check("(g) dialogue_style reported as changed since",
      "profile.dialogue_style" in named, rep2.get("skipped"))

# ── Run 3 ────────────────────────────────────────────────────────────────
print("run 3")
import app.models.character as mchar  # noqa: E402

run3 = wr.create_run("sync", "m", "p", "u", 40, 300000)
ctx3 = wt.ToolCtx(run_id=run3, turn=1)
res = wt.run_tool(ctx3, "create_location",
                  {"data": {"name": "Demo Square"}, "x": 0, "z": 0, "boundary": SQUARE})
check("fixture: Demo Square created a third time", res.ok, res)
res = wt.run_tool(ctx3, "create_character",
                  {"data": {"name": "Demo Npc Three", "template": "human-default",
                            "gender": "female"}, "home": "Demo Square"})
check("fixture: Demo Npc Three created", res.ok, res)

_orig_save_cfg = mchar.save_character_config
mchar.save_character_config = lambda *_a, **_kw: False
try:
    res = upd(ctx3, "Demo Npc Three", {"gender": "male", "importance": 3})
finally:
    mchar.save_character_config = _orig_save_cfg
check("(h) config save failed -> not ok", not res.ok and res.line.startswith("error"), res)
check("(h) profile half stored",
      (get_character_profile("Demo Npc Three") or {}).get("gender") == "male")
check("(h) push still sent", calls == [("changed_at", "Demo Npc Three", PUB)], calls)
calls.clear()
gate["only_restore"] = True
rep3 = wu.undo(run3)
gate["only_restore"] = False
wr.set_status(run3, "rolled_back")
check("(h) discard complete", rep3.get("complete"), rep3)
check("(h) the journaled profile half is undone (its restore pushes)",
      calls == [("changed_at", "Demo Npc Three", PUB)], calls)

print()
if failures:
    print(f"FAILED: {len(failures)} check(s)")
    sys.exit(1)
print("all checks passed")
