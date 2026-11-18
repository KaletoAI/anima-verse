#!/usr/bin/env python3
"""Smoke: ``garment_fit_settings.changed`` counts only settings that can shape the piece (review 06#10).

Usage:  ./.venv/bin/python scripts/smoke_fit_settings_applicable.py

No storage, no world DB: ``app.models.inventory.get_item`` is replaced by a dict lookup.

Pieces: ``shirt`` (slots torso, mode own_mesh), ``shellshirt`` (torso, mode shell), ``boot`` (feet + legs,
own_mesh). Every record is made with the defaults (``inputs.fit_settings`` = ``defaults()``, ``mesh_shape`` as the
mode makes it). Expected, from the rules in ``changed``'s docstring:
[1] shirt, sleeves_left "fitted"            -> True  (applies to a generated mesh)
[2] shellshirt, sleeves_left "fitted"       -> False (a shell is only grafted; fails on 69aeeba75: True)
[3] shellshirt, allowance 10 / depth 6 / trunk "fitted" -> False each (same)
[4] shirt, shaft "cut"                      -> False (not feet + legs; fails on 69aeeba75: True)
[5] boot, shaft "cut"                       -> True
[6] boot, shaft "cut" in record AND profile, shaft_overlap 20 in profile -> False (overlap shapes split only)
[7] boot, shaft "split", shaft_overlap 20   -> True
[8] shellshirt, shell_offset changed        -> True; shirt, shell_offset changed -> False (A166, unchanged)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.models import inventory  # noqa: E402
from app.core import garment_fit_settings as fs, garment_shell  # noqa: E402

ITEMS = {
    "shirt": {"category": "outfit_piece", "outfit_piece": {"slots": ["torso"], "mesh_mode": "own_mesh"}},
    "shellshirt": {"category": "outfit_piece", "outfit_piece": {"slots": ["torso"], "mesh_mode": "shell"}},
    "boot": {"category": "outfit_piece", "outfit_piece": {"slots": ["feet", "legs"], "mesh_mode": "own_mesh"}},
}
inventory.get_item = lambda item_id, *a, **k: ITEMS.get(item_id)


def rec(item_id, **made):
    shape = garment_shell.shape_of(ITEMS[item_id])
    return {"inputs": {"fit_settings": dict(fs.defaults(), **made), "mesh_shape": shape}}


def prof(item_id, **now):
    return {fs.SETTINGS_KEY: {item_id: now}}


fails = []


def check(label, got, want):
    print(("ok  " if got == want else "FAIL"), label, got)
    if got != want:
        fails.append(label)


check("[1]", fs.changed(rec("shirt"), prof("shirt", sleeves_left="fitted"), "shirt"), True)
check("[2]", fs.changed(rec("shellshirt"), prof("shellshirt", sleeves_left="fitted"), "shellshirt"), False)
for k, v in (("allowance", 10), ("depth", 6), ("trunk", "fitted")):
    check(f"[3] {k}", fs.changed(rec("shellshirt"), prof("shellshirt", **{k: v}), "shellshirt"), False)
check("[4]", fs.changed(rec("shirt"), prof("shirt", shaft="cut"), "shirt"), False)
check("[5]", fs.changed(rec("boot"), prof("boot", shaft="cut"), "boot"), True)
check("[6]", fs.changed(rec("boot", shaft="cut"), prof("boot", shaft="cut", shaft_overlap=20), "boot"), False)
check("[7]", fs.changed(rec("boot"), prof("boot", shaft_overlap=20), "boot"), True)
off = [c for c in garment_shell.SHELL_OFFSET_CHOICES if c != garment_shell.SHELL_OFFSET_DEFAULT][0]
check("[8] shell", fs.changed(rec("shellshirt"), prof("shellshirt", shell_offset=off), "shellshirt"), True)
check("[8] shirt", fs.changed(rec("shirt"), prof("shirt", shell_offset=off), "shirt"), False)
print("FAILED:" if fails else "all passed", fails or "")
sys.exit(1 if fails else 0)
