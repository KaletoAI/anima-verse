#!/usr/bin/env python3
"""Smoke: a body slot's uncovered text appears only while no CLOSED worn piece covers it.

Usage:
    ./.venv/bin/python scripts/smoke_slot_cover_exposed.py

Runs without a server, without a world DB and without network (``paths.init`` on a temp dir before any
world-DB import). Exit 0 = all green, exit 1 = at least one check failed. Stubs:
``app.models.inventory.get_item`` -> the fixture items below, ``body_slots.slots_for_character`` -> the fixture
body slots below.

Bug (2026-11-12, a full-body pose render): a character wearing a CLOSED blazer and no top got the upper body's
uncovered text in the prompt. ``body_slots.is_slot_exposed`` only asked whether a covering piece SITS on a
clothing slot of the body slot's ``covered_by``; it ignored the piece's ``covers`` declaration, and the upper
body's declaration did not name ``outer``.

The rule (user, 2026-11-12): the uncovered text of a body slot appears only when no worn piece covers it, or
when every covering piece is worn OPEN (ruling A8: an open piece covers nothing in front). A piece covers a body
slot when it sits on, or ``covers``, a clothing slot of the body slot's ``covered_by``. ``partially_covers``
does NOT cover: what lies under a partial cover stays visible (``outfit_renderer.visible_equipped_pieces`` keeps
those targets, ``_resolve_partial_covers`` names them "underneath"), and so does the body under it.

Fixture body slots (texts invented):
  upper  covered_by [top, underwear_top, outer]   covered "covered upper body text"
                                                   exposed "uncovered upper body text"
  lower  covered_by [bottom, underwear_bottom]    covered "covered lower body text"
                                                   exposed "uncovered lower body text"
  narrow covered_by [top, underwear_top]          exposed "uncovered narrow text"  (a declaration without outer)

Fixture items (outfit_piece; closable = kind default unless named: outer -> closable, everything else not):
  jacket     slots [outer]          covers [underwear_top]   partially_covers [top]   (the reported blazer's shape)
  coat       slots [outer]          covers []                partially_covers [top]
  undershirt slots [underwear_top]
  skirt      slots [bottom]         covers [underwear_bottom]
  wrap       slots [outer]          covers [underwear_bottom]
  longshirt  slots [top]                                      partially_covers [bottom]
  dress      slots [top, bottom]

Expected, by hand from the rule:
 [1] {outer: jacket} closed     -> upper: no uncovered text, covered text in general
 [2] {outer: jacket} open       -> upper uncovered text present (A8)
 [3] {} nothing worn            -> upper AND lower uncovered texts present
 [4] {underwear_top: undershirt}-> upper absent, lower present
 [5] {bottom: skirt} closed     -> lower absent, upper present
 [6] {top: longshirt}           -> upper absent (sits on top); lower PRESENT (partially_covers [bottom] hides nothing)
 [7] {outer: coat} closed       -> upper absent (outer in covered_by); open -> present
 [8] narrow (covered_by without outer): jacket closed -> absent (its covers [underwear_top] count);
     jacket open -> present; coat closed -> PRESENT (no covers, outer not declared: the declaration decides)
 [9] {outer: wrap} closed       -> lower absent (covers [underwear_bottom]), upper absent (outer); open -> both present
[10] {top: dress, bottom: dress}-> both absent
[11] the same decision reaches appearance_suffix (2D scene / pose prompt text) and exposed_slot_loras
[12] Fails on the old code: ``is_slot_exposed`` from ``git show 0e5a7adf:app/core/body_slots.py`` reads the
     narrow slot with the jacket closed as EXPOSED (it ignored ``covers``).
[13] Every package body slot (manifest parse of plugins/*, incl. the symlinked packs) that ``top`` covers is also covered by ``outer`` (skipped without packages).
"""
import ast
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="cover-clips-")

from app.core import paths  # noqa: E402
paths.init(tempfile.mkdtemp(prefix="cover-storage-"))

from app.core import body_slots as bs  # noqa: E402
from app.plugins.registry import BodySlotSpec  # noqa: E402

FAILURES = []
CHECKS = 0

UP_X, UP_C = "uncovered upper body text", "covered upper body text"
LO_X, LO_C = "uncovered lower body text", "covered lower body text"
NA_X = "uncovered narrow text"


def check(name, condition, detail=""):
    global CHECKS
    CHECKS += 1
    print(f"  {'ok  ' if condition else 'FAIL'} {name}" + ("" if condition else f": {detail}"))
    if not condition:
        FAILURES.append(name)


def _item(iid, slots, covers=(), partial=()):
    return {"id": iid, "name": iid, "category": "outfit_piece", "prompt_fragment": f"{iid} fragment",
            "outfit_piece": {"slots": list(slots), "covers": list(covers), "partially_covers": list(partial)}}


ITEMS = {i["id"]: i for i in (
    _item("jacket", ["outer"], ["underwear_top"], ["top"]),
    _item("coat", ["outer"], [], ["top"]),
    _item("undershirt", ["underwear_top"]),
    _item("skirt", ["bottom"], ["underwear_bottom"]),
    _item("wrap", ["outer"], ["underwear_bottom"]),
    _item("longshirt", ["top"], [], ["bottom"]),
    _item("dress", ["top", "bottom"]),
)}

UPPER = BodySlotSpec(id="upper", package_id="fixture", covered_by=["top", "underwear_top", "outer"],
                     prompt={"covered": UP_C, "exposed": UP_X}, back=True,
                     attributes={"lora": {"type": "lora_select"}})
LOWER = BodySlotSpec(id="lower", package_id="fixture", covered_by=["bottom", "underwear_bottom"],
                     prompt={"covered": LO_C, "exposed": LO_X})
NARROW = BodySlotSpec(id="narrow", package_id="fixture", covered_by=["top", "underwear_top"],
                      prompt={"exposed": NA_X})
SPECS = [UPPER, LOWER, NARROW]


def profile(pieces, open_ids=()):
    return {"name": "Demo", "equipped_pieces": dict(pieces),
            "equipped_options": {"piece_state": {iid: "open" for iid in open_ids}},
            "body_slots": {"upper": {"lora": "fixture_upper_lora"}}}


def frags(pieces, open_ids=()):
    return bs.prompt_fragments("Demo", profile=profile(pieces, open_ids))


def main() -> int:
    with patch("app.models.inventory.get_item", side_effect=lambda iid: ITEMS.get(iid)), \
            patch.object(bs, "slots_for_character", return_value=SPECS):
        f = frags({"outer": "jacket"})
        print("[1] closed outer piece, no top")
        check("upper uncovered text absent", UP_X not in f["exposed"], f)
        check("upper covered text in general", UP_C in f["general"], f)

        print("[2] the same piece open")
        f = frags({"outer": "jacket"}, open_ids=["jacket"])
        check("upper uncovered text present", UP_X in f["exposed"], f)
        check("upper covered text gone", UP_C not in f["general"], f)

        print("[3] nothing worn")
        f = frags({})
        check("upper present", UP_X in f["exposed"], f)
        check("lower present", LO_X in f["exposed"], f)

        print("[4] upper underwear only")
        f = frags({"underwear_top": "undershirt"})
        check("upper absent", UP_X not in f["exposed"], f)
        check("lower present", LO_X in f["exposed"], f)

        print("[5] skirt closed")
        f = frags({"bottom": "skirt"})
        check("lower absent", LO_X not in f["exposed"], f)
        check("lower covered text in general", LO_C in f["general"], f)
        check("upper present", UP_X in f["exposed"], f)

        print("[6] partially_covers")
        f = frags({"top": "longshirt"})
        check("upper absent (piece sits on top)", UP_X not in f["exposed"], f)
        check("lower present (a partial cover hides nothing)", LO_X in f["exposed"], f)

        print("[7] outer piece without covers")
        check("closed -> upper absent", UP_X not in frags({"outer": "coat"})["exposed"])
        check("open -> upper present", UP_X in frags({"outer": "coat"}, open_ids=["coat"])["exposed"])

        print("[8] narrow declaration (no outer): covers decide")
        check("jacket closed -> absent", NA_X not in frags({"outer": "jacket"})["exposed"])
        check("jacket open -> present", NA_X in frags({"outer": "jacket"}, open_ids=["jacket"])["exposed"])
        check("coat closed -> present", NA_X in frags({"outer": "coat"})["exposed"])

        print("[9] outer piece covering the lower body")
        f = frags({"outer": "wrap"})
        check("closed -> lower absent", LO_X not in f["exposed"], f)
        check("closed -> upper absent", UP_X not in f["exposed"], f)
        f = frags({"outer": "wrap"}, open_ids=["wrap"])
        check("open -> lower present", LO_X in f["exposed"], f)
        check("open -> upper present", UP_X in f["exposed"], f)

        print("[10] dress on top and bottom")
        f = frags({"top": "dress", "bottom": "dress"})
        check("both absent", UP_X not in f["exposed"] and LO_X not in f["exposed"], f)

        print("[11] the same test behind the scene text and the LoRAs")
        closed, opened = profile({"outer": "jacket"}), profile({"outer": "jacket"}, ["jacket"])
        check("appearance_suffix closed has no upper text", UP_X not in bs.appearance_suffix("Demo", profile=closed))
        check("appearance_suffix open has it", UP_X in bs.appearance_suffix("Demo", profile=opened))
        check("appearance_suffix back view closed has none",
              UP_X not in bs.appearance_suffix("Demo", profile=closed, back_view=True))

        def lora_names(p):
            return [entry.get("name") for entry in bs.exposed_slot_loras("Demo", profile=p)]
        closed_loras, open_loras = lora_names(closed), lora_names(opened)
        check("exposed_slot_loras closed has no slot LoRA", "fixture_upper_lora" not in closed_loras, closed_loras)
        check("exposed_slot_loras open has it", "fixture_upper_lora" in open_loras, open_loras)

        print("[12] fails on the old code (0e5a7adf)")
        src = subprocess.run(["git", "-C", str(ROOT), "show", "0e5a7adf:app/core/body_slots.py"],
                             capture_output=True, text=True).stdout
        fn = next((n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == "is_slot_exposed"),
                  None) if src else None
        if fn is None:
            check("old source available", False, "git show 0e5a7adf failed")
        else:
            ns = {"Dict": dict, "Any": object}
            exec(compile(ast.Module(body=[fn], type_ignores=[]), "old_body_slots", "exec"), ns)
            check("old code read the narrow slot as exposed under a closed jacket",
                  ns["is_slot_exposed"](NARROW, profile({"outer": "jacket"})) is True)
            check("new code reads it covered", bs.is_slot_exposed(NARROW, profile({"outer": "jacket"})) is False)

    print("[13] packages: whatever top covers, outer covers too")
    from app.plugins.loader import PLUGIN_DIR, _collect_packages  # manifest-only parse, no on_load, no registry
    declared = [(p.id, s.id, s.covered_by) for p in _collect_packages(PLUGIN_DIR, warn=False)
                for s in p.body_slots if "top" in s.covered_by]
    if not declared:
        print("  skip no package declares a slot covered by top")
    for pid, sid, cov in declared:
        check(f"{pid}/{sid} covered_by names outer", "outer" in cov, cov)

    print(f"\n{CHECKS - len(FAILURES)}/{CHECKS} checks passed")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
