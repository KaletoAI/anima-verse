#!/usr/bin/env python3
"""Smoke: World Dev free mode — the server's hairstyle as the journal op
``remove_hairstyle`` (plan docs/superpowers/plans/2026-11-25-world-dev-free-media.md,
Task 6).

A temp world and instance (paths.init BEFORE any world-DB import), an EMPTY
ANIMATION_CLIPS_DIR; no server, no LLM, no render: ``get_image_service`` raises,
``garment_assembly.schedule`` and ``figure_build.request`` are no-ops (their calls are
counted), so nothing CPU- or GPU-heavy starts. Characters are made by the real
``create_character`` tool (``world_dev_tools.run_tool``).

Usage:
    ./.venv/bin/python scripts/smoke_world_dev_media_hairstyle.py

WHAT IS CHECKED, and where every expected value comes from
----------------------------------------------------------

The species fixture of smoke_world_dev_media_plan.py: one body slot "hair"
with ``mesh_item: hair`` and the fragment "{length} {color} hair", so a
character with body_slots.hair {red, long} has the appearance hair text
"long red hair", owns no hairstyle and is a humanoid of human-roleplay —
``garment_hair.ensure_hairstyle`` mints its first hairstyle and ``_claim_first``
makes it worn (equipped_mesh_pieces["hair"]) and the plain body's
(base_hairstyle). The created character profile carries neither key before
(create_character writes no hairstyle), so ``before`` is ABSENT for both.

  (a) created character "Demo Hair" (run R1): make_hairstyle -> ("done", "");
      the item exists, equipped_mesh_pieces["hair"] == its id; the newest
      journal row has tool "media:hairstyle", kind "write", inverse op
      "remove_hairstyle" with that item id and before = ABSENT for both keys.
      The run's ``steps`` (the model's tool-call counter, plan 2026-11-25
      complete-characters-budget B1) is the same before and after: the
      media lane's journal row is no model call.
  (b) discard_preview(R1) has the 'character "Demo Hair"' line and NO line
      starting with "hairstyle" (the character goes; the handler deletes its
      unchanged item first — the newer row is undone first); undo(R1) is
      complete, the item and the character are gone.
  (c) pre-existing "Demo A" (created by an earlier, accepted run R0, no
      hairstyle) in run R2: preview line 'hairstyle <id> of "Demo A"'; undo ->
      complete, item gone, both keys absent again (they were absent before).
  (d) pre-existing "Demo B" (R0) in run R3, then equipped_mesh_pieces set by
      hand to {} -> preview has a "was changed since" line naming
      equipped_mesh_pieces; undo skips ``changed since`` keys
      ["equipped_mesh_pieces"] (one skip), base_hairstyle is absent again,
      the item is gone (no key left unrestored references it), the hand-set {}
      stays.
  (e) set_media_state(R4, "closed") -> make_hairstyle == ("cancelled",
      "run closed"), no journal row, no item.
  (f) set_media_state(R5, "accepted") -> make_hairstyle == ("done", ""), the
      item exists and is worn, the journal row count is unchanged.
  (g) pre-existing "Demo C" (R0) in run R6, then equipped_mesh_pieces set by
      hand to {"hair": <id>, "top": "item_x"} -> undo skips the key AND the
      item (two ``changed since`` records, keys ["equipped_mesh_pieces"] each);
      the item still exists, the profile value is untouched; base_hairstyle
      (unchanged since) is absent again. The preview says "was changed since"
      for both and has no going hairstyle line.
  (h) pre-existing "Demo A" (both keys ABSENT after (c)) in run R7,
      _claim_first patched to write and then raise: make_hairstyle raises,
      the row stays pending (written None) with the item id attached; the
      keys hold what _claim_first writes (base = id, worn = {"hair": id}), so
      the preview names the going hairstyle and undo is complete: item gone,
      both keys absent again.
  (i) the same in run R8, then equipped_mesh_pieces set by hand to {} — that
      is neither before (ABSENT) nor what the step writes ({"hair": id}), so
      the pending row does NOT restore it blindly: one skip changed since
      ["equipped_mesh_pieces"], the {} stays, base_hairstyle absent again,
      the item gone (no unrestored key names it).
  (j) _claim_first patched to raise BEFORE writing (run R9): keys still equal
      before (base ABSENT, worn {} from (i)); undo complete, item gone, keys
      unchanged.
  (k) media state "accepted" (run R10) with ensure_hairstyle raising
      ValueError("smoke: no hair slot") -> ("skipped", "smoke: no hair slot"),
      the same skip contract as "open"; no journal row.
"""
from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

TMP = Path(tempfile.mkdtemp(prefix="smoke_wd_media_hair_"))
atexit.register(shutil.rmtree, TMP, ignore_errors=True)
os.environ["ANIMATION_CLIPS_DIR"] = str(TMP / "clips")
os.environ["STORAGE_DIR"] = str(TMP / "world")
os.environ["INSTANCE_DIR"] = str(TMP / "instance")

from app.core import paths  # noqa: E402

paths.init(TMP / "world")

from app.core import db  # noqa: E402

db.init_schema()

import app.imagegen.service as image_service  # noqa: E402


def _no_render(*_a, **_k):
    raise AssertionError("render reached")


image_service.get_image_service = _no_render

from app.core import figure_build, garment_assembly, garment_hair  # noqa: E402
from app.core import world_dev_media as wdm  # noqa: E402
from app.core import world_dev_runs as wr  # noqa: E402
from app.core import world_dev_tools as wt  # noqa: E402
from app.core import world_dev_undo as wu  # noqa: E402
from app.core.keyed_lock import keyed_lock  # noqa: E402
from app.models.character import (character_row_exists, get_character_profile,  # noqa: E402
                                  save_character_profile)
from app.models.character_template import clear_template_cache  # noqa: E402
from app.models.inventory import get_item  # noqa: E402
from app.plugins import registry  # noqa: E402
from app.plugins.registry import BodySlotSpec, Package  # noqa: E402

CALLS = []
garment_assembly.schedule = lambda name, *a, **k: CALLS.append(("assembly", name))
figure_build.request = lambda name, *a, **k: CALLS.append(("build", name)) or False

failures = []


def check(label, cond, detail=None):
    print(("  ok   " if cond else "  FAIL ") + label
          + ("" if cond or detail is None else f"   -> {detail!r}"))
    if not cond:
        failures.append(label)


# The skill manager loads (and re-registers) the packages on its first use;
# the completeness line of a character write asks it for the skill groups
# (plan 2026-11-25-world-dev-free-complete-characters-budget, Task 5), so it
# is loaded before the fake package is registered.
from app.core.dependencies import get_skill_manager  # noqa: E402

get_skill_manager()
registry.clear_registry()
registry.register_package(Package(
    id="smoke_species", dir=TMP, manifest={}, apply_to=["human-roleplay"],
    piece_slots=["top"],
    body_slots=[BodySlotSpec(
        id="hair", package_id="smoke_species", face=True, mesh_item="hair",
        attributes={"color": {"type": "select", "options": ["red", "black"]},
                    "length": {"type": "select", "options": ["short", "long"]}},
        prompt={"always": "{length} {color} hair"})]))
clear_template_cache()

KEY = garment_hair.BASE_HAIRSTYLE_KEY
HAIR = {"hair": {"color": "red", "length": "long"}}


def create(ctx, name):
    res = wt.run_tool(ctx, "create_character", {"data": {
        "name": name, "gender": "female", "body_slots": HAIR}})
    check(f"create {name} ok", res.ok and res.wrote, res)


def new_run():
    run = wr.create_run("build", "m", "p", "u", 80, 300000)
    wr.next_turn(run)
    return run, wt.ToolCtx(run_id=run, turn=1)


def review(run):
    wr.set_status(run, "awaiting_review")


def profile(name):
    return get_character_profile(name) or {}


def hand_set(name, key, value):
    with keyed_lock("character_profile", name):
        prof = profile(name)
        prof[key] = value
        check(f"hand-set {name}.{key}", save_character_profile(name, prof))


def hair_rows(run):
    return [e for e in wr.entries(run, writes_only=False, include_undone=True)
            if e.get("tool") == "media:hairstyle"]


# ── R0: the pre-existing characters ──────────────────────────────────────
r0, ctx0 = new_run()
for n in ("Demo A", "Demo B", "Demo C"):
    create(ctx0, n)
wr.set_status(r0, "accepted")
check("pre-existing characters own no hairstyle",
      all(not garment_hair.hairstyles(n) for n in ("Demo A", "Demo B", "Demo C")))

# (a)
print("(a) created character")
r1, ctx1 = new_run()
create(ctx1, "Demo Hair")
check("(a) before: no hairstyle keys",
      KEY not in profile("Demo Hair") and "equipped_mesh_pieces" not in profile("Demo Hair"),
      {k: profile("Demo Hair").get(k) for k in (KEY, "equipped_mesh_pieces")})
review(r1)
steps_before = wr.get_run(r1)["steps"]
out = wdm.make_hairstyle(r1, "Demo Hair")
check("(a) the media row is no tool call: run.steps unchanged",
      wr.get_run(r1)["steps"] == steps_before, (steps_before, wr.get_run(r1)["steps"]))
check("(a) done", out == ("done", ""), out)
worn = (profile("Demo Hair").get("equipped_mesh_pieces") or {}).get("hair")
check("(a) the item exists and is worn", bool(worn) and get_item(worn) is not None, worn)
newest = wr.entries(r1)[0]
inv = newest.get("inverse") or {}
check("(a) journal row", (newest.get("tool"), newest.get("kind"), inv.get("op"), inv.get("item_id"))
      == ("media:hairstyle", "write", "remove_hairstyle", worn), (newest.get("tool"), newest.get("kind"), inv))
check("(a) before = ABSENT for both keys",
      inv.get("before") == {KEY: wu.ABSENT, "equipped_mesh_pieces": wu.ABSENT}, inv.get("before"))
check("(a) written keys re-read",
      (newest.get("written") or {}).get("keys") == {KEY: worn, "equipped_mesh_pieces": {"hair": worn}},
      newest.get("written"))

# (b)
print("(b) discard of the created character")
lines = wu.discard_preview(r1)
check("(b) character line", any(l.startswith('character "Demo Hair"') for l in lines), lines)
check("(b) no hairstyle line", not any(l.startswith("hairstyle") for l in lines), lines)
rep = wu.undo(r1)
check("(b) complete", rep["complete"], rep)
check("(b) item gone", get_item(worn) is None)
check("(b) character gone", not character_row_exists("Demo Hair"))
wr.set_status(r1, "rolled_back")

# (c)
print("(c) pre-existing character")
r2, _ = new_run()
review(r2)
check("(c) done", wdm.make_hairstyle(r2, "Demo A") == ("done", ""))
a_item = (profile("Demo A").get("equipped_mesh_pieces") or {}).get("hair")
check("(c) worn", bool(a_item) and profile("Demo A").get(KEY) == a_item, profile("Demo A"))
lines = wu.discard_preview(r2)
check("(c) preview line", f'hairstyle {a_item} of "Demo A"' in lines, lines)
CALLS.clear()
rep = wu.undo(r2)
check("(c) complete", rep["complete"] and not rep["skipped"], rep)
check("(c) item gone", get_item(a_item) is None)
check("(c) both keys absent again",
      KEY not in profile("Demo A") and "equipped_mesh_pieces" not in profile("Demo A"),
      {k: profile("Demo A").get(k) for k in (KEY, "equipped_mesh_pieces")})
check("(c) the worn hair's Build is requested (the ordinary path)", ("build", "Demo A") in CALLS, CALLS)
wr.set_status(r2, "rolled_back")

# (d)
print("(d) a key changed since")
r3, _ = new_run()
review(r3)
check("(d) done", wdm.make_hairstyle(r3, "Demo B") == ("done", ""))
b_item = (profile("Demo B").get("equipped_mesh_pieces") or {}).get("hair")
hand_set("Demo B", "equipped_mesh_pieces", {})
lines = wu.discard_preview(r3)
check("(d) preview: was changed since (equipped_mesh_pieces)",
      any(l.startswith(f"hairstyle {b_item}") and "equipped_mesh_pieces" in l
          and "was changed since" in l for l in lines), lines)
rep = wu.undo(r3)
sk = rep["skipped"]
check("(d) one skip: changed since [equipped_mesh_pieces]",
      len(sk) == 1 and sk[0]["reason"] == wu.REASON_CHANGED
      and sk[0].get("keys") == ["equipped_mesh_pieces"], sk)
check("(d) base_hairstyle absent again", KEY not in profile("Demo B"), profile("Demo B").get(KEY))
check("(d) hand-set value stays", profile("Demo B").get("equipped_mesh_pieces") == {},
      profile("Demo B").get("equipped_mesh_pieces"))
check("(d) item gone", get_item(b_item) is None)
wr.set_status(r3, "rollback_incomplete")

# (e)
print("(e) closed run")
r4, _ = new_run()
review(r4)
wdm.set_media_state(r4, "closed")
n_before = len(wr.entries(r4, writes_only=False, include_undone=True))
check("(e) cancelled", wdm.make_hairstyle(r4, "Demo B") == ("cancelled", "run closed"))
check("(e) no journal row", len(wr.entries(r4, writes_only=False, include_undone=True)) == n_before)
check("(e) no hairstyle", not garment_hair.hairstyles("Demo B"), garment_hair.hairstyles("Demo B"))
wr.set_status(r4, "rolled_back")

# (f)
print("(f) accepted run")
r5, _ = new_run()
review(r5)
wdm.set_media_state(r5, "accepted")
n_before = len(wr.entries(r5, writes_only=False, include_undone=True))
check("(f) done", wdm.make_hairstyle(r5, "Demo B") == ("done", ""))
f_item = (profile("Demo B").get("equipped_mesh_pieces") or {}).get("hair")
check("(f) item exists and is worn", bool(f_item) and get_item(f_item) is not None, profile("Demo B"))
check("(f) no journal row", len(wr.entries(r5, writes_only=False, include_undone=True)) == n_before)
wr.set_status(r5, "accepted")

# (g)
print("(g) a key still referencing the item")
r6, _ = new_run()
review(r6)
check("(g) done", wdm.make_hairstyle(r6, "Demo C") == ("done", ""))
c_item = (profile("Demo C").get("equipped_mesh_pieces") or {}).get("hair")
hand = {"hair": c_item, "top": "item_x"}
hand_set("Demo C", "equipped_mesh_pieces", hand)
lines = wu.discard_preview(r6)
check("(g) preview: changed since, no going line",
      any("was changed since" in l and l.startswith(f"hairstyle {c_item}") for l in lines)
      and f'hairstyle {c_item} of "Demo C"' not in lines, lines)
rep = wu.undo(r6)
sk = rep["skipped"]
check("(g) key AND item skipped, changed since [equipped_mesh_pieces]",
      len(sk) == 2 and all(s["reason"] == wu.REASON_CHANGED and s.get("keys") == ["equipped_mesh_pieces"]
                           for s in sk), sk)
check("(g) item still exists", get_item(c_item) is not None)
check("(g) profile value untouched", profile("Demo C").get("equipped_mesh_pieces") == hand,
      profile("Demo C").get("equipped_mesh_pieces"))
check("(g) base_hairstyle absent again", KEY not in profile("Demo C"), profile("Demo C").get(KEY))
wr.set_status(r6, "rollback_incomplete")

# (h)-(j): pending rows (ensure_hairstyle minted, then raised)
_orig_claim = garment_hair._claim_first


def _claim_then_fail(name, item_id):
    _orig_claim(name, item_id)
    raise RuntimeError("smoke: failure after the claim")


def _fail_before_claim(name, item_id):
    raise RuntimeError("smoke: failure before the claim")


def pending_step(run, name, patch):
    garment_hair._claim_first = patch
    try:
        wdm.make_hairstyle(run, name)
        check("pending step raised", False)
    except RuntimeError:
        pass
    finally:
        garment_hair._claim_first = _orig_claim
    rows = hair_rows(run)
    inv = (rows[0].get("inverse") or {}) if rows else {}
    check("pending row with the item attached",
          len(rows) == 1 and rows[0].get("written") is None and bool(inv.get("item_id")), rows)
    return str(inv.get("item_id") or "")


print("(h) pending row, keys written, unchanged since")
r7, _ = new_run()
review(r7)
h_item = pending_step(r7, "Demo A", _claim_then_fail)
check("(h) keys were written", profile("Demo A").get(KEY) == h_item
      and profile("Demo A").get("equipped_mesh_pieces") == {"hair": h_item}, profile("Demo A"))
check("(h) preview line", f'hairstyle {h_item} of "Demo A"' in wu.discard_preview(r7),
      wu.discard_preview(r7))
rep = wu.undo(r7)
check("(h) complete", rep["complete"] and not rep["skipped"], rep)
check("(h) item gone", get_item(h_item) is None)
check("(h) both keys absent again",
      KEY not in profile("Demo A") and "equipped_mesh_pieces" not in profile("Demo A"), profile("Demo A"))
wr.set_status(r7, "rolled_back")

print("(i) pending row, a key edited by hand since")
r8, _ = new_run()
review(r8)
i_item = pending_step(r8, "Demo A", _claim_then_fail)
hand_set("Demo A", "equipped_mesh_pieces", {})
lines = wu.discard_preview(r8)
check("(i) preview: was changed since (equipped_mesh_pieces)",
      any(l.startswith(f"hairstyle {i_item}") and "equipped_mesh_pieces" in l
          and "was changed since" in l for l in lines), lines)
rep = wu.undo(r8)
sk = rep["skipped"]
check("(i) one skip: changed since [equipped_mesh_pieces]",
      len(sk) == 1 and sk[0]["reason"] == wu.REASON_CHANGED
      and sk[0].get("keys") == ["equipped_mesh_pieces"], sk)
check("(i) the hand edit stays (no blind restore)",
      profile("Demo A").get("equipped_mesh_pieces") == {}, profile("Demo A").get("equipped_mesh_pieces"))
check("(i) base_hairstyle absent again", KEY not in profile("Demo A"), profile("Demo A").get(KEY))
check("(i) item gone (no unrestored key names it)", get_item(i_item) is None)
wr.set_status(r8, "rollback_incomplete")

print("(j) pending row, failure before the profile write")
r9, _ = new_run()
review(r9)
j_item = pending_step(r9, "Demo A", _fail_before_claim)
check("(j) keys untouched", KEY not in profile("Demo A")
      and profile("Demo A").get("equipped_mesh_pieces") == {}, profile("Demo A"))
rep = wu.undo(r9)
check("(j) complete", rep["complete"] and not rep["skipped"], rep)
check("(j) item gone", get_item(j_item) is None)
check("(j) keys still as before", KEY not in profile("Demo A")
      and profile("Demo A").get("equipped_mesh_pieces") == {}, profile("Demo A"))
wr.set_status(r9, "rolled_back")

print("(k) accepted run, ValueError -> skipped")
r10, _ = new_run()
review(r10)
wdm.set_media_state(r10, "accepted")
_orig_ensure = garment_hair.ensure_hairstyle


def _refuse(name):
    raise ValueError("smoke: no hair slot")


garment_hair.ensure_hairstyle = _refuse
try:
    out = wdm.make_hairstyle(r10, "Demo A")
finally:
    garment_hair.ensure_hairstyle = _orig_ensure
check("(k) skipped with the reason", out == ("skipped", "smoke: no hair slot"), out)
check("(k) no journal row", not hair_rows(r10))
wr.set_status(r10, "accepted")

print()
if failures:
    print(f"FAILED: {len(failures)}")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("all ok")
