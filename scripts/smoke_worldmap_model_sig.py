#!/usr/bin/env python3
"""Smoke run for UI-3: the worldmap payload carries each character's MESH
signature, so the 3D client stops polling the model route per character.

``client3d`` ran a 20-second timer that asked ``GET /characters/<n>/model3d``
for EVERY character of the worldmap, sequentially, only to compare one string:
``model.signature``. The worldmap poll (every 3 s) already carries exactly that
pattern for the world — ``terrain_sig`` / ``height_sig`` — so the signature
belongs in the character row (§ A11a).

The server side is ``world_ops._model_signature``:

  * the ANSWER is the model route's own: ``model3d.find_model3d_serving``
    decides which file is served, and its stem is what ``get_model3d_info``
    reports as ``model.signature``.
  * that derivation costs two profile loads, a directory walk and a stored
    manifest per candidate — far too much per character per 3-second poll, and
    it would break the one-profile-per-character bound of
    ``scripts/smoke_worldmap_profile_loads.py``. So it runs only when a cheap
    CHANGE TOKEN moved: the outfit fields of the profile the loop has already
    loaded, plus ONE ``stat`` of ``<character>/model3d``.

Runs against a THROWAWAY storage directory and a throwaway animation-clip
directory — it never touches a real world, never starts a server and makes no
LLM/image call.

The seed (hand-built, so every expectation below is derived from it):

    location "Depot" at (0, 0), a drawn 10 m square, room "hall"

    npc_meshed   equips one outfit piece; its ``model3d/`` holds the file
                 ``<outfit signature>.glb`` — the EXACT match of the serving
                 chain
    npc_empty    has a ``model3d/`` directory, but no mesh in it
    npc_bare     has no ``model3d/`` directory at all

Hand-derived expectations
-------------------------

[1] the field. ``model_sig`` is present exactly where a mesh is served:

      npc_meshed -> the stem of its own file, i.e. its outfit signature, and
                    byte for byte what ``model3d.get_model3d_info`` reports as
                    ``model.signature`` — the two are asked independently here
      npc_empty  -> absent (a directory without a mesh serves nothing, so the
                    row has nothing to say)
      npc_bare   -> absent (no mesh store at all)

    An absent field is the contract's "nothing to poll", not "unknown".

[2] the cost. ``model3d.find_model3d_serving`` is counted:

      build 1 -> 2 calls (npc_meshed and npc_empty have a ``model3d/``
                 directory; npc_bare is skipped by the ``stat`` alone)
      build 2 -> 0 calls (nothing moved, so every token still matches)

    Before the fix the count would be 0 here and 3×N over the client's own
    poll instead — this check pins that the server pays the derivation once
    per real change and not once per poll.

[3] the profile-load budget. ``get_character_profile`` is counted per build.
    Build 2 must cost no more than a build of the same payload with the
    signature derivation switched off entirely: the cached path reads the
    profile it was handed and nothing else.

[4] invalidation, one change at a time, each followed by a build:

      a) the OUTFIT changes (a second piece is equipped) -> the outfit
         signature changes, so the EXACT match is gone. The nearest-neighbour
         branch judges candidates by their stored MANIFEST, and this fixture's
         mesh is a bare file without one, so nothing matches: ``model_sig``
         disappears from the row. What matters here is that the derivation RAN
         again (1 call) — that is what the change token is for; the serving
         chain's own verdict is ``model3d``'s business, not this payload's.
      b) a MESH for the new outfit lands in the directory -> the exact match
         is back and ``model_sig`` becomes the new stem.
      c) nothing changes -> 0 calls again.

Usage:  ./.venv/bin/python scripts/smoke_worldmap_model_sig.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

STORAGE = Path(tempfile.mkdtemp(prefix="worldmap-model-sig-"))
CLIPS = Path(tempfile.mkdtemp(prefix="worldmap-model-sig-clips-"))
os.environ["ANIMATION_CLIPS_DIR"] = str(CLIPS)

from app.core import paths  # noqa: E402

paths.init(STORAGE)

from app.core import db  # noqa: E402

db.init_schema()

from app.core import model3d, model_refs, world_ops  # noqa: E402
from app.models import character as character_mod  # noqa: E402
from app.models.character import (  # noqa: E402
    get_character_dir, get_character_profile, save_character_current_location,
    save_character_current_room, save_character_profile, set_character_pos,
    set_known_locations)
from app.models.world import (  # noqa: E402
    _load_world_data, _save_world_data, add_location,
    update_location_position)

FAILURES = []
CHECKED = 0


def check(label: str, actual, expected) -> None:
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'OK ' if ok else 'FAIL'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


def check_bound(label: str, actual: int, bound: int) -> None:
    global CHECKED
    CHECKED += 1
    ok = actual <= bound
    print(f"  {'OK ' if ok else 'FAIL'} {label}: {actual}"
          + ("" if ok else f" — expected <= {bound}"))
    if not ok:
        FAILURES.append(label)


# ── the world ───────────────────────────────────────────────────────────
DEPOT = add_location(name="Depot", description="model signature smoke",
                     rooms=[{"id": "hall", "name": "Hall"}])["id"]
update_location_position(DEPOT, 0.0, 0.0)
_data = _load_world_data()
for _loc in _data["locations"]:
    if _loc["id"] == DEPOT:
        _loc["map3d"] = {"plan_width_m": 10.0,
                         "boundary": [[-5.0, -5.0], [5.0, -5.0],
                                      [5.0, 5.0], [-5.0, 5.0]]}
_save_world_data(_data)

NAMES = ["npc_meshed", "npc_empty", "npc_bare"]


def person(name: str, pieces=None) -> None:
    save_character_profile(name, {"current_location": "", "language": "en",
                                  "equipped_pieces": dict(pieces or {})},
                           create_new=True)
    save_character_current_location(name, DEPOT)
    set_character_pos(name, -1.0, -1.0)
    save_character_current_room(name, "hall")
    set_known_locations(name, [DEPOT])


person("npc_meshed", {"top": "coat"})
person("npc_empty")
person("npc_bare")


def model_dir(name: str) -> Path:
    return get_character_dir(name) / "model3d"


def outfit_sig(name: str) -> str:
    """The signature the serving chain looks for — asked through the very
    function the mesh store keys on."""
    return model_refs.current_outfit_state(name)[2]


# npc_meshed: one mesh, named after the outfit it was made for (an EXACT hit).
model_dir("npc_meshed").mkdir(parents=True, exist_ok=True)
FIRST_SIG = outfit_sig("npc_meshed")
(model_dir("npc_meshed") / f"{FIRST_SIG}.glb").write_bytes(b"glTF-stub")
# npc_empty: the directory exists, but nothing is in it.
model_dir("npc_empty").mkdir(parents=True, exist_ok=True)
# npc_bare: no directory — nothing is created for it, deliberately.


# ── the counters ────────────────────────────────────────────────────────
_real_serving = model3d.find_model3d_serving
_real_gcp = character_mod.get_character_profile
_counts = {"serving": 0, "profile": 0}


def _counting_serving(name):
    _counts["serving"] += 1
    return _real_serving(name)


def _counting_gcp(character_name):
    _counts["profile"] += 1
    return _real_gcp(character_name)


def build(show_all: bool = True):
    """One worldmap build with both counters running."""
    model3d.find_model3d_serving = _counting_serving
    character_mod.get_character_profile = _counting_gcp
    _counts["serving"] = _counts["profile"] = 0
    try:
        payload = world_ops.build_worldmap_payload(None, show_all)
    finally:
        model3d.find_model3d_serving = _real_serving
        character_mod.get_character_profile = _real_gcp
    return payload, dict(_counts)


def row(payload, name: str) -> dict:
    for c in payload["characters"]:
        if c["name"] == name:
            return c
    return {}


def main() -> int:
    print("[1] the field is there exactly where a mesh is served")
    first, c1 = build()
    check("three characters on the map",
          sorted(c["name"] for c in first["characters"]), sorted(NAMES))
    check("npc_meshed reports its file's stem",
          row(first, "npc_meshed").get("model_sig"), FIRST_SIG)
    # …and the model ROUTE, asked independently, says the same thing.
    info = model3d.get_model3d_info("npc_meshed")
    check("…which is what /model3d reports as model.signature",
          (info.get("model") or {}).get("signature"), FIRST_SIG)
    check("npc_empty has no mesh, so no field",
          "model_sig" in row(first, "npc_empty"), False)
    check("npc_bare has no mesh store, so no field",
          "model_sig" in row(first, "npc_bare"), False)

    print("\n[2] the derivation runs on a change, not on a poll")
    check("build 1 derives for the two with a model3d directory",
          c1["serving"], 2)
    second, c2 = build()
    check("build 2 derives nothing", c2["serving"], 0)
    check("…and reports the same signature",
          row(second, "npc_meshed").get("model_sig"), FIRST_SIG)

    print("\n[3] the profile budget of the cached path")
    # The reference: the same build with the derivation switched off, i.e.
    # what the loop costs WITHOUT this feature at all.
    world_ops._MODEL_SIG_CACHE.clear()
    _plain = world_ops._model_signature
    world_ops._model_signature = lambda name, profile: ""
    try:
        _, c_off = build()
    finally:
        world_ops._model_signature = _plain
    _, c_warm = build()   # cache is cold again -> derives once per directory
    _, c_hot = build()
    print(f"  --  without the field: {c_off['profile']} profile loads; "
          f"cold: {c_warm['profile']}; warm: {c_hot['profile']}")
    check_bound("the warm build loads no more profiles than the bare one",
                c_hot["profile"], c_off["profile"])
    check("…and derives nothing", c_hot["serving"], 0)

    print("\n[4] a change re-derives")
    prof = get_character_profile("npc_meshed")
    prof["equipped_pieces"] = {"top": "coat", "legs": "trousers"}
    save_character_profile("npc_meshed", prof)
    SECOND_SIG = outfit_sig("npc_meshed")
    check("the outfit signature really moved", SECOND_SIG != FIRST_SIG, True)
    changed, c3 = build()
    check("an outfit change re-derives", c3["serving"], 1)
    check("…and with no mesh and no manifest to fall back on, the field goes",
          "model_sig" in row(changed, "npc_meshed"), False)

    (model_dir("npc_meshed") / f"{SECOND_SIG}.glb").write_bytes(b"glTF-stub")
    grown, c4 = build()
    check("a new mesh file re-derives", c4["serving"], 1)
    check("…and is served from then on",
          row(grown, "npc_meshed").get("model_sig"), SECOND_SIG)
    check("…which /model3d confirms",
          (model3d.get_model3d_info("npc_meshed").get("model")
           or {}).get("signature"), SECOND_SIG)
    _, c5 = build()
    check("and a quiet poll derives nothing again", c5["serving"], 0)

    print("\n[5] the payload is JSON, field for field")
    check("the row survives a round trip",
          json.loads(json.dumps(row(grown, "npc_meshed")))["model_sig"],
          SECOND_SIG)

    print(f"\n{CHECKED} checks, {len(FAILURES)} failed")
    for f in FAILURES:
        print(f"  FAILED: {f}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
