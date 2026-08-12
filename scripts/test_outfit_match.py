#!/usr/bin/env python3
"""Standalone checks for the nearest-outfit matching (app/core/outfit_match.py
+ the serving fallbacks built on it).

The serving problem: 3D mesh and expression variants are cached per EXACT
outfit signature — a character in a never-rendered combination served no model
at all (3D client fell back to a pool placeholder). The nearest-outfit
fallback serves the stored entry whose recorded piece combination is closest
to the worn one instead.

Scoring rule (slot-aware, hand-derived expectations below):
  per slot in the union: 1.0 same item, 0.5 both occupied by different items,
  0.0 only one side occupied; non-piece items match by id (1.0/0.0).
  score = sum / (|slot union| + |item union|); two empty outfits score 1.0.
  Rationale for the 0.5: same COVERAGE with a different garment beats a
  missing garment — {shirt, skirt} must not beat {other shirt, skirt} for a
  character wearing {shirt', skirt} (a topless model would win on plain
  Jaccard: 2/3 > 2/4).

Runs against a THROWAWAY storage dir with fake model/variant files — no
server, no GPU, no world DB rows.

Usage:  ./.venv/bin/python scripts/test_outfit_match.py
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("ANIMATION_CLIPS_DIR", tempfile.mkdtemp(prefix="clips-"))

STORAGE = Path(tempfile.mkdtemp(prefix="outfit-match-"))

from app.core import paths  # noqa: E402

paths.init(STORAGE)

from app.core import db  # noqa: E402

db.init_schema()

from app.core.outfit_match import outfit_similarity  # noqa: E402

FAILURES = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


def close(a: float, b: float) -> bool:
    return abs(a - b) < 1e-9


# ---------------------------------------------------------------- similarity
print("outfit_similarity:")
U = {"underwear_bottom": "u1"}
check("identical -> 1.0",
      close(outfit_similarity({"top": "a", **U}, ["i1"], {"top": "a", **U}, ["i1"]), 1.0))
check("both empty -> 1.0", close(outfit_similarity({}, [], {}, []), 1.0))
check("disjoint slots -> 0.0",
      close(outfit_similarity({"top": "a"}, [], {"bottom": "b"}, []), 0.0))
check("same slot, different item -> 0.5",
      close(outfit_similarity({"top": "a"}, [], {"top": "b"}, []), 0.5))
# The Vallerie case: worn = underwear+skirt+NEW top. A stored topless
# underwear+skirt model (2/3) must LOSE against underwear+skirt+other-top
# (2.5/3) — same coverage with a different garment is the nearer outfit.
worn = {"underwear_bottom": "u1", "bottom": "b1", "top": "t_new"}
topless = outfit_similarity(worn, [], {"underwear_bottom": "u1", "bottom": "b1"}, [])
other_top = outfit_similarity(worn, [],
                              {"underwear_bottom": "u1", "bottom": "b1", "top": "t_old"}, [])
check("topless scores 2/3", close(topless, 2.0 / 3.0), f"{topless}")
check("other top scores 2.5/3", close(other_top, 2.5 / 3.0), f"{other_top}")
check("other top beats topless", other_top > topless)
check("extra item halves", close(outfit_similarity({"top": "a"}, ["i1"], {"top": "a"}, []), 0.5))
check("one-sided vs empty -> 0.0", close(outfit_similarity({"top": "a"}, [], {}, []), 0.0))

# ------------------------------------------------------- find_model3d_serving
print("find_model3d_serving:")
import app.core.model3d as model3d  # noqa: E402
import app.models.character as character_mod  # noqa: E402

CHAR = "demo"
char_dir = STORAGE / "characters" / CHAR
mesh_dir = char_dir / "model3d"
refs_dir = char_dir / "model_refs"
mesh_dir.mkdir(parents=True)
refs_dir.mkdir(parents=True)

character_mod.get_character_dir = lambda name, create=False: STORAGE / "characters" / name

_STATE = {"pieces": {}, "items": [], "sig": ""}
model3d.current_outfit_state = lambda name: (_STATE["pieces"], _STATE["items"], _STATE["sig"])


def set_worn(pieces, items, sig):
    _STATE.update({"pieces": pieces, "items": items, "sig": sig})


def add_mesh(sig, pieces=None, items=None, mtime=None):
    (mesh_dir / f"{sig}.glb").write_bytes(b"glb")
    meta = {"signature": sig}
    if pieces is not None:
        meta.update({"pieces": pieces, "items": items or []})
    (mesh_dir / f"{sig}.json").write_text(json.dumps(meta), encoding="utf-8")
    if mtime is not None:
        os.utime(mesh_dir / f"{sig}.glb", (mtime, mtime))


# No models at all -> nothing to serve.
set_worn({"top": "t_new"}, [], "aaaaaaaaaaaa")
path, match = model3d.find_model3d_serving(CHAR)
check("no models -> (None, '')", path is None and match == "")

# Exact hit wins over everything.
add_mesh("aaaaaaaaaaaa", {"top": "t_new"})
add_mesh("bbbbbbbbbbbb", {"top": "t_new", "bottom": "b1"})
path, match = model3d.find_model3d_serving(CHAR)
check("exact hit", path is not None and path.stem == "aaaaaaaaaaaa" and match == "exact")

# State-suffixed signature falls back to the neutral entry of the outfit.
set_worn({"top": "t_new"}, [], "aaaaaaaaaaaa-sdeadbeef")
path, match = model3d.find_model3d_serving(CHAR)
check("neutral fallback", path is not None and path.stem == "aaaaaaaaaaaa" and match == "neutral")

# Unknown combination -> nearest by manifest (slot-aware score).
set_worn({"top": "t_other", "bottom": "b1"}, [], "cccccccccccc")
path, match = model3d.find_model3d_serving(CHAR)
check("nearest via mesh manifest",
      path is not None and path.stem == "bbbbbbbbbbbb" and match == "nearest",
      f"got {path and path.stem} / {match}")

# Manifest fallback: mesh sidecar without pieces -> tpose sidecar of same sig.
add_mesh("dddddddddddd")  # sidecar records no pieces
(refs_dir / "tpose_dddddddddddd.json").write_text(json.dumps({
    "equipped_pieces": {"top": "t_other", "bottom": "b1"}, "equipped_items": []}),
    encoding="utf-8")
path, match = model3d.find_model3d_serving(CHAR)
check("nearest via tpose manifest",
      path is not None and path.stem == "dddddddddddd" and match == "nearest",
      f"got {path and path.stem} / {match}")

# Ties resolve to the newest file.
now = time.time()
add_mesh("eeeeeeeeeeee", {"top": "t_other", "bottom": "b1"}, mtime=now + 100)
os.utime(mesh_dir / "dddddddddddd.glb", (now - 100, now - 100))
path, match = model3d.find_model3d_serving(CHAR)
check("tie -> newest", path is not None and path.stem == "eeeeeeeeeeee",
      f"got {path and path.stem}")

# find_model3d (management semantics) must NOT nearest-match: an unknown
# combination has no model to delete/rename.
check("find_model3d stays exact", model3d.find_model3d(CHAR) is None)

# --------------------------------------------------- find_nearest_expression
print("find_nearest_expression:")
import app.core.expression_regen as expr  # noqa: E402

outfits_dir = char_dir / "outfits"
outfits_dir.mkdir(parents=True)
character_mod.get_character_outfits_dir = lambda name: STORAGE / "characters" / name / "outfits"


def add_variant(key, pieces, mood, mtime_off=0.0):
    """A variant sidecar as generate_expression_image writes it: the free-text
    mood for display, the EXPRESSION CATALOG KEY for machine comparison
    ("happy" -> `positive`, "sad" -> `sad`; both are listed synonyms, so no
    embedding is involved)."""
    from app.core.expression_pose_maps import resolve_expression_key
    img = outfits_dir / f"{CHAR}_{key}.png"
    img.write_bytes(b"png")
    (outfits_dir / f"{CHAR}_{key}.json").write_text(json.dumps({
        "mood": mood, "expression_key": resolve_expression_key(mood),
        "activity": "", "pose_key": "", "equipped_pieces": pieces,
        "equipped_items": []}), encoding="utf-8")
    t = time.time() + mtime_off
    os.utime(img, (t, t))


worn_p = {"top": "t_new", "bottom": "b1"}
check("empty cache -> None",
      expr.find_nearest_expression(CHAR, "happy", worn_p, []) is None)

add_variant("far", {"underwear_bottom": "u9"}, "happy")
add_variant("near_sad", {"top": "t_old", "bottom": "b1"}, "sad")
p = expr.find_nearest_expression(CHAR, "happy", worn_p, [])
check("outfit similarity dominates mood",
      p is not None and p.stem == f"{CHAR}_near_sad", f"got {p and p.stem}")

add_variant("near_happy", {"top": "t_old", "bottom": "b1"}, "happy", mtime_off=-500)
p = expr.find_nearest_expression(CHAR, "happy", worn_p, [])
check("expression key breaks outfit tie",
      p is not None and p.stem == f"{CHAR}_near_happy", f"got {p and p.stem}")

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILED: {FAILURES}")
    sys.exit(1)
print("all checks passed")
