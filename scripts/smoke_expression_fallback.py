#!/usr/bin/env python3
"""Checks the serving fallback of GET /characters/{name}/outfit-expression.

Usage:
    ./.venv/bin/python scripts/smoke_expression_fallback.py

Throwaway storage, throwaway world DB — no server, no real world is touched,
nothing is generated. The route function is called DIRECTLY (it is a plain
`def`, FastAPI only wires it up), so what is measured is the response the
client would get: a FileResponse with its `X-Variant-Status` header, or the
HTTPException the router turns into a 404.

WHY these expectations (derived by hand from the route + the cache-key rule,
not recorded from current output):

  THE CASE. A temporary NPC has `expression_variants_enabled: false`
  (`shared/templates/character/npc-temporary.json`), so
  `trigger_expression_generation` returns False before it does anything
  (`app/core/expression_regen.py`, feature gate) — `ignore_feature_gate` is
  only set for an explicit `trigger=1`. Such a character therefore never has
  a generation running and never starts one: `started` is False,
  `is_generating` is False, and the route falls through to its closing 404.
  Its ONE image is the default variant the finish-gate pipeline renders
  (mood "" + pose ""); every request for any other pose misses the cache. The
  player UI asks with the character's effective pose key and
  `fallback=default`, gets the 404, and `EnvironmentPanel`'s `onError` hides
  the figure — the NPC is invisible although its picture is on disk. The
  fallback ladder exists for exactly this and was unreachable, because it was
  only consulted in the 202 branches.

  THE FILE NAMES, by hand. `_cache_key` hashes
  `f"{expression_key}:{pose}:{eq}"` and takes 12 hex, prefixed with the safe
  character name:
    * `expression_key = resolve_expression_key("")` → "neutral" (catalog
      default for empty text; the NPC's current feeling is "", so the route
      resolves the same thing);
    * `pose = _canonical_pose_key(...)` → "standing" for "" (catalog
      default), "kneeling" for "kneeling" (an exact catalog key, so it does
      NOT collapse onto the default — that is what makes the request miss);
    * `eq = outfit_signature_raw({}, [], name)`, and a piece-less temporary
      NPC folds in its free outfit text → "wearing: a grey linen apron";
    * `state_fp` is "" — no image_modifier state is active.
  So:
    md5("neutral:standing:wearing: a grey linen apron")
      = a8021c6b637b06982bcc4483fb5cabe7  → Torvin_a8021c6b637b.png
    md5("neutral:kneeling:wearing: a grey linen apron")
      = a3506035ea0598364c2c45dc36c1df0a  → Torvin_a3506035ea05(.png)
  The second file is never written here; that request is the miss.

  [1] THE PRECONDITION. The gate really is off for this character
      (`is_feature_enabled(name, "expression_variants_enabled")` is False) and
      `trigger_expression_generation(...)` therefore answers False without
      starting anything (`is_generating` stays False). Without this the run
      would prove nothing — the ladder would be reached through a 202 branch
      instead of the closing one.

  [2] A NAKED REQUEST STILL 404s. `fallback` empty = "give me exactly this
      variant": missing stays 404. The fix must not turn every cache miss
      into some other picture.

  [3] `fallback=default` SERVES THE DEFAULT VARIANT. The image on disk is the
      default one, the request asks for "kneeling" → rung 1 of the ladder
      (`find_nearest_expression`) finds nothing, because that rung compares
      the outfit RECORDED IN A SIDECAR and this variant has none; rung 2
      (`get_cached_expression(name, "", "", <same equipped state>)`) hits.
      Expected: 200 with exactly `Torvin_a8021c6b637b.png` and
      `X-Variant-Status: fallback-default`.

  [4] WITH A SIDECAR IT IS RUNG 1. The finish-gate pipeline writes a sidecar
      next to the variant, so the realistic case answers one rung earlier:
      the same file, `X-Variant-Status: fallback-nearest`. Both rungs are
      asserted because rung 1 shadows rung 2 as soon as any sidecar records
      an outfit.

  [5] NO IMAGE AT ALL STAYS 404. The ladder has nothing to serve (no
      variant, no sidecar, an empty outfits directory), so the route must
      still answer 404 — "no picture on disk" is a real failure and the
      profile image is deliberately NOT a fallback.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="exprfallback-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="exprfallback-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import config, db  # noqa: E402
config.load(STORAGE / "config.json")
db.init_schema()

from fastapi import HTTPException  # noqa: E402

from app.core import expression_regen  # noqa: E402
from app.models.character import (get_character_current_feeling,  # noqa: E402
                                  get_character_outfits_dir,
                                  save_character_profile)
from app.models.character_template import is_feature_enabled  # noqa: E402
from app.models.inventory import get_equipped_items, get_equipped_pieces  # noqa: E402
from app.routes.characters import get_outfit_expression  # noqa: E402

FAILURES = []
CHECKED = 0


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"{'OK  ' if ok else 'FAIL'}  {label}: {actual!r}"
          + ("" if ok else f"  (expected {expected!r})"))
    if not ok:
        FAILURES.append(label)


def call(name, **kw):
    """Calls the route and normalises the answer to (status, file, variant)."""
    try:
        resp = get_outfit_expression(name, **kw)
    except HTTPException as e:
        return (e.status_code, None, None)
    path = getattr(resp, "path", None)
    return (resp.status_code,
            Path(path).name if path else None,
            resp.headers.get("x-variant-status"))


NAME = "Torvin"
DEFAULT_FILE = "Torvin_a8021c6b637b.png"

save_character_profile(NAME, {
    "name": NAME,
    "template": "npc-temporary",
    "outfit_description": "a grey linen apron",
}, create_new=True)

# --- [1] the precondition: no gate, hence no generation, hence the 404 branch
check("current feeling is empty (so mood resolves to the catalog default)",
      get_character_current_feeling(NAME), "")
check("nothing is worn (so the outfit axis is the free text)",
      (get_equipped_pieces(NAME), get_equipped_items(NAME)), ({}, []))
check("expression_variants_enabled is off for a temporary NPC",
      is_feature_enabled(NAME, "expression_variants_enabled"), False)
check("trigger_expression_generation refuses (feature gate)",
      expression_regen.trigger_expression_generation(
          NAME, "", "kneeling", equipped_pieces={}, equipped_items=[],
          ignore_cooldown=True, coalesce=False), False)
check("…and nothing is generating",
      expression_regen.is_generating(NAME, "", "kneeling",
                                     equipped_pieces={}, equipped_items=[]),
      False)
check("the default variant's file name is the hand-derived one",
      expression_regen._cache_key("", "", NAME, {}, []) + ".png",
      DEFAULT_FILE)

# --- the one image such an NPC gets: the default variant, mood "" + pose ""
outfits = get_character_outfits_dir(NAME)
default_img = outfits / DEFAULT_FILE
default_img.write_bytes(b"\x89PNG\r\n\x1a\n default variant")

# --- [2] a naked request for a variant that is not there stays a 404
check("no fallback asked for → 404",
      call(NAME, mood="", pose_key="kneeling"), (404, None, None))

# --- [3] fallback=default serves the default variant (rung 2)
check("fallback=default serves the default variant",
      call(NAME, mood="", pose_key="kneeling", fallback="default"),
      (200, DEFAULT_FILE, "fallback-default"))

# --- [4] with a sidecar the nearest-outfit rung answers first
(outfits / DEFAULT_FILE).with_suffix(".json").write_text(json.dumps({
    "equipped_pieces": {},
    "equipped_items": [],
    "expression_key": "neutral",
}), encoding="utf-8")
check("with a sidecar the nearest-outfit rung serves the same file",
      call(NAME, mood="", pose_key="kneeling", fallback="default"),
      (200, DEFAULT_FILE, "fallback-nearest"))

# --- [5] nothing on disk → the 404 remains
for leftover in outfits.iterdir():
    leftover.unlink()
check("no image on disk at all → 404 even with fallback=default",
      call(NAME, mood="", pose_key="kneeling", fallback="default"),
      (404, None, None))

print(f"\n{CHECKED} checks, {len(FAILURES)} failed")
if FAILURES:
    print("FAILED: " + ", ".join(FAILURES))
    sys.exit(1)
print("all green")
