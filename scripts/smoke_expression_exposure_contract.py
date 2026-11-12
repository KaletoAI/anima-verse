#!/usr/bin/env python3
"""Smoke: the expression render contract carries the EXPOSURE of the framed body slots, not their declaration.

Usage:
    ./.venv/bin/python scripts/smoke_expression_exposure_contract.py

Runs on a throwaway storage + instance (``paths.init`` before any world-DB import); no server, no world, no
GPU. Stubs: ``app.models.inventory.get_item`` -> the fixture items, ``body_slots.slots_for_character`` -> the
fixture body slot (declaration swapped per case), ``body_slots.portrait_piece_slots`` -> ("top", "outer").

Why: ``expression_regen._framing_basis`` put each framed slot's ``covered_by`` list into the contract, so a
package widening a declaration made EVERY waist-up expression image stale, also where the widening changes
nothing in the picture. The contract now holds which framed slots are exposed under the rendered outfit and its
open / closed pieces (``body_slots.is_slot_exposed``).

Fixture: body slot "upper" (portrait, texts "covered upper body text" / "uncovered upper body text"); items
jacket {slots [outer], covers [underwear_top]} and coat {slots [outer], no covers}; shirt {slots [top]}.
Declarations: D1 = [top, underwear_top]; D2 = [top, underwear_top, outer]; D3 = D2 + [neck].

Expected, by hand:
 [1] shirt worn: D1 -> D2 -> D3 change nothing in its exposure (covered by the shirt) -> the three contracts are
     byte-identical.
 [2] jacket closed: covered under D1 already (its covers [underwear_top]) and under D2 -> identical.
 [3] coat closed: exposed under D1, covered under D2 -> the contracts differ.
 [4] coat open (piece_state open): exposed under D1 and D2 -> identical; and != the closed coat under D2.
 [5] render_profile_of: a sidecar {equipped_pieces {outer: coat}, outfit_raw "outer=coat|open:coat"} over a
     profile wearing the shirt -> pieces {outer: coat}, piece_state {coat: open}; its contract equals the contract
     of the profile that rendered it (the coat open), not the one of the current outfit.
 [6] Fails on the old code: ``_framing_basis`` from ``git show 5e908226:app/core/expression_regen.py`` gives
     different contracts for case [1] (D1 vs D2) — the declaration list was in the contract.
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
TMP = Path(tempfile.mkdtemp(prefix="expo-contract-"))
os.environ["STORAGE_DIR"] = str(TMP / "world")
os.environ["INSTANCE_DIR"] = str(TMP / "instance")
os.environ["ANIMATION_CLIPS_DIR"] = str(TMP / "clips")
os.environ["ANIMATION_RIG_FILE"] = str(TMP / "rig.fbx")

from app.core import paths  # noqa: E402
paths.init(TMP / "world")
paths.init_instance(TMP / "instance")
from app.core import config  # noqa: E402
(TMP / "world" / "config.json").write_text("{}")
config.load(TMP / "world" / "config.json")

from app.core import body_slots as bs  # noqa: E402
from app.core import expression_regen as er  # noqa: E402
from app.plugins.registry import BodySlotSpec  # noqa: E402

FAILURES = []
CHECKS = 0


def check(name, condition, detail=""):
    global CHECKS
    CHECKS += 1
    print(f"  {'ok  ' if condition else 'FAIL'} {name}" + ("" if condition else f": {detail}"))
    if not condition:
        FAILURES.append(name)


def _item(iid, slots, covers=()):
    return {"id": iid, "name": iid, "category": "outfit_piece", "prompt_fragment": f"{iid} fragment",
            "outfit_piece": {"slots": list(slots), "covers": list(covers), "partially_covers": []}}


ITEMS = {i["id"]: i for i in (_item("jacket", ["outer"], ["underwear_top"]), _item("coat", ["outer"]),
                               _item("shirt", ["top"]))}
D1 = ["top", "underwear_top"]
D2 = ["top", "underwear_top", "outer"]
D3 = ["top", "underwear_top", "outer", "neck"]


def spec(covered_by):
    return BodySlotSpec(id="upper", package_id="fixture", covered_by=list(covered_by), portrait=True,
                        prompt={"covered": "covered upper body text", "exposed": "uncovered upper body text"})


def profile(pieces, open_ids=()):
    return {"name": "Demo", "equipped_pieces": dict(pieces),
            "equipped_options": {"piece_state": {iid: "open" for iid in open_ids}}}


def contract(prof, covered_by, basis=None):
    with patch.object(bs, "slots_for_character", return_value=[spec(covered_by)]), \
            patch.object(er, "_framing_basis", basis or er._framing_basis):
        return er.render_contract([], "make the person neutral", "upper_body", prof)


def main() -> int:
    with patch("app.models.inventory.get_item", side_effect=lambda iid: ITEMS.get(iid)), \
            patch.object(bs, "portrait_piece_slots", return_value=("top", "outer")):
        print("[1] a declaration change that leaves the exposure alone")
        shirt = profile({"top": "shirt"})
        c1, c2, c3 = (contract(shirt, d) for d in (D1, D2, D3))
        check("D1 == D2 == D3 byte-identical", c1 == c2 == c3, (c1, c2, c3))

        print("[2] closed piece covering through covers")
        jacket = profile({"outer": "jacket"})
        check("D1 == D2", contract(jacket, D1) == contract(jacket, D2))

        print("[3] a declaration change that changes the exposure")
        coat = profile({"outer": "coat"})
        check("D1 != D2", contract(coat, D1) != contract(coat, D2))

        print("[4] the same piece worn open")
        coat_open = profile({"outer": "coat"}, ["coat"])
        check("open: D1 == D2", contract(coat_open, D1) == contract(coat_open, D2))
        check("open != closed under D2", contract(coat_open, D2) != contract(coat, D2))

        print("[5] the contract of a stored image is computed under its rendered outfit")
        meta = {"equipped_pieces": {"outer": "coat"}, "equipped_items": [], "outfit_raw": "outer=coat|open:coat"}
        rendered = er.render_profile_of(shirt, meta)
        check("pieces from the sidecar", rendered["equipped_pieces"] == {"outer": "coat"}, rendered)
        check("open pieces from outfit_raw",
              rendered["equipped_options"]["piece_state"] == {"coat": "open"}, rendered)
        check("contract == the rendering profile's", contract(rendered, D2) == contract(coat_open, D2))
        check("contract != the current outfit's", contract(rendered, D2) != contract(shirt, D2))

        print("[6] fails on the old code (5e908226)")
        src = subprocess.run(["git", "-C", str(ROOT), "show", "5e908226:app/core/expression_regen.py"],
                             capture_output=True, text=True).stdout
        fn = next((n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == "_framing_basis"),
                  None) if src else None
        if fn is None:
            check("old source available", False, "git show 5e908226 failed")
        else:
            ns = {}
            exec(compile(ast.Module(body=[fn], type_ignores=[]), "old_expression_regen", "exec"), ns)
            old = ns["_framing_basis"]
            check("old code: D1 != D2 for an unchanged exposure",
                  contract(shirt, D1, old) != contract(shirt, D2, old))

    print(f"\n{CHECKS - len(FAILURES)}/{CHECKS} checks passed")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
