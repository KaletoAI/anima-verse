#!/usr/bin/env python3
"""User ruling 2026-11-23 — a male character never gets the chest shaping (``app/core/bust_shaping.py``); a small chest
of any other wearer keeps it.

Usage: ./.venv/bin/python scripts/smoke_chest_shaping_male.py

THE RULE (``bust_shaping.character_shaped`` -> ``set_lift``, the one place the wearer decides)

``character_shaped(name, profile)`` is False exactly when ``base_skin.is_male(profile)`` — the profile's ``gender``,
stripped and lower-cased, is one of "male" / "man" / "m". Every other value ("female", "nonbinary", "", absent) keeps
the shaping. ``set_lift`` returns 0.0 for such a wearer whatever the pieces say — an explicit ``outfit_piece.lift``
too; ``key_tokens`` and ``prepare`` read the lift from ``set_lift``, so a male wearer's drape and cut keys carry no
``shape:`` token and his drape runs on the plain body file itself (``prepare`` returns it untouched, without reading
it).

HAND-DERIVED NUMBERS

The slot defaults are pinned here: ``{"underwear_top": 0.25, "top": 0.0}`` (the A228 smoke's table).

* ``tee``  — template top, slots ``["top"]``, covers ``["underwear_top"]``, no own lift: ``piece_lift`` hits
  ``underwear_top`` (full cover) -> 0.25. ``shapes_chest``: kind top, 0.25 > 0 -> yes.
* ``top1`` — template top, slots ``["top"]``, own lift 1.0 -> 1.0.
* ``dress5`` — template dress, slots ``["top"]``, own lift 0.5 -> 0.5.
* ``skirt`` — template skirt (not a shaping kind) -> never shapes.

Female / unset / non-binary wearer (unchanged from 32056ce9d): ``set_lift(["tee"])`` = 0.25,
``set_lift(["top1", "dress5", "skirt"])`` = max(1.0, 0.5) = 1.0, the tee's token = "shape:" + md5 of
``{"lift": 0.25, "v": VERSION}`` (sort_keys JSON) [:8].
Male wearer ("male", "Male", " M ", "man"): every one of those is 0.0, every token list [] — the explicit 1.0 of
``top1`` included.

OLD-CODE PROOF (pinned 32056ce9d): the module of that commit has no wearer at all — its ``set_lift(["tee"])`` is 0.25
and its ``key_tokens`` of the tee a ``shape:`` token, for anyone (Kai's T-shirt was shaped +5 mm).
"""
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.core import paths  # noqa: E402

paths.init(tempfile.mkdtemp(prefix="smoke-chest-male-"))

from app.core import bust_shaping as bs  # noqa: E402
from app.core import extension_rig  # noqa: E402
import app.models.character as character  # noqa: E402
import app.models.inventory as inventory  # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        FAILS.append(name)


DEF = {"underwear_top": 0.25, "top": 0.0}
extension_rig.clothing_lift_slots = lambda: dict(DEF)


def tpl(kind, lift=None, slots=("top",), covers=()):
    op = {"mesh_mode": "template", "slots": list(slots), "covers": list(covers), "partially_covers": [],
          "template": {"params": {"kind": kind}}}
    if lift is not None:
        op["lift"] = lift
    return {"outfit_piece": op}


ITEMS = {"tee": tpl("top", covers=("underwear_top",)), "top1": tpl("top", 1.0), "dress5": tpl("dress", 0.5),
         "skirt": tpl("skirt", None, ("legs",))}
inventory.get_item = lambda iid: ITEMS.get(iid)
PROFILES = {"F": {"gender": "female"}, "U": {}, "E": {"gender": ""}, "N": {"gender": "nonbinary"},
            "M": {"gender": "male"}, "M2": {"gender": "Male"}, "M3": {"gender": " M "}, "M4": {"gender": "man"}}
READS = []


def fake_profile(name, *a, **k):
    READS.append(name)
    return PROFILES.get(name)


character.get_character_profile = fake_profile
TEE_TOKEN = "shape:" + hashlib.md5(json.dumps({"v": bs.VERSION, "lift": 0.25}, sort_keys=True)
                                   .encode("utf-8")).hexdigest()[:8]

# --- the gate itself
for name in ("F", "U", "E", "N"):
    check(f"character_shaped: {PROFILES[name]} keeps the shaping", bs.character_shaped(name) is True)
for name in ("M", "M2", "M3", "M4"):
    check(f"character_shaped: {PROFILES[name]} never", bs.character_shaped(name) is False)
check("character_shaped: a passed profile is used, nothing read",
      (READS.clear() or True) and bs.character_shaped("nobody", {"gender": "male"}) is False and READS == [])
check("character_shaped: an unknown character (no profile) keeps the shaping", bs.character_shaped("nobody") is True)

# --- not male: unchanged
for name in ("F", "U", "E", "N"):
    check(f"{name}: set_lift(tee) = 0.25 (slot default)", bs.set_lift(["tee"], character_name=name) == 0.25)
    check(f"{name}: set_lift(top1, dress5, skirt) = 1.0",
          bs.set_lift(["top1", "dress5", "skirt"], character_name=name) == 1.0)
    check(f"{name}: tee token", bs.key_tokens("tee", ITEMS["tee"], [], character_name=name) == [TEE_TOKEN])

# --- male: 0 for every piece, an explicit lift included
for name in ("M", "M2", "M3", "M4"):
    for ids in (["tee"], ["top1"], ["dress5"], ["top1", "dress5", "skirt"]):
        check(f"{name}: set_lift({ids}) = 0", bs.set_lift(ids, character_name=name) == 0.0)
    for iid in ("tee", "top1", "dress5"):
        check(f"{name}: no token for {iid}", bs.key_tokens(iid, ITEMS[iid], ["skirt"], character_name=name) == [])
    missing = Path(tempfile.gettempdir()) / "smoke-chest-male-no-such-body.glb"
    body, rec, note = bs.prepare(missing, "top1", ITEMS["top1"], [], Path(tempfile.mkdtemp()), character_name=name)
    check(f"{name}: prepare drapes on the plain body file, unread", body == missing and rec is None and note == "")
check("a non-shaping set reads no profile", (READS.clear() or True)
      and bs.set_lift(["skirt"], character_name="M") == 0.0 and READS == [])

# --- old code (32056ce9d): no wearer, the tee shaped for anyone
try:
    old_src = subprocess.run(["git", "show", "32056ce9d:app/core/bust_shaping.py"], cwd=ROOT, capture_output=True,
                             text=True, check=True).stdout
    spec = importlib.util.spec_from_loader("bust_shaping_32056ce9d", loader=None)
    old = importlib.util.module_from_spec(spec)
    exec(compile(old_src, "bust_shaping_32056ce9d", "exec"), old.__dict__)
    check("old code (32056ce9d): set_lift(tee) = 0.25 with no wearer at all", old.set_lift(["tee"]) == 0.25)
    check("old code (32056ce9d): the tee carries a shape token for anyone",
          old.key_tokens("tee", ITEMS["tee"], []) == [TEE_TOKEN])
except subprocess.CalledProcessError:
    print("skip old-code proof: commit 32056ce9d not in this clone")

print("\n" + ("all passed" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}"))
sys.exit(1 if FAILS else 0)
