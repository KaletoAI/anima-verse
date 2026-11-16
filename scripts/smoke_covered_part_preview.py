#!/usr/bin/env python3
"""Smoke (Ruling A75): a preview never shows an attached part under a piece that covers its slot, and the Figure
tab's viewer says when the figure it shows is not the whole outfit worn now.

Usage:  ./.venv/bin/python scripts/smoke_covered_part_preview.py

No server, no world, no outbound request: a temp STORAGE_DIR / INSTANCE_DIR, stub packages, stub items and stub
model / assembly readers.

WHY
---
A fit on the PLAIN body is stored with the plain body as it is — the rigged base, which carries the attached part
of an exposed slot (a node with ``extras.attached_part = <group id>``). The Details previews served that GLB as
stored, so jeans worn over a covered slot showed the part straight through them (Kai, 2026-11-14: 7187 of the
part's 14543 vertices, 49.4 %, outside the jeans surface, up to 10.7 cm). And when a piece's fit was refused, the
serving path re-assembled the stored outfit model without it while the piece's row said "The figure built before
stays shown" — the figure lacked the jeans and nothing said so.

EXPECTED VALUES, DERIVED BY HAND
--------------------------------
Stub package: one body slot ``groin`` with a separate mesh part, ``covered_by: [bottom, underwear_bottom]``, rigs
``g_chain`` and ``g_bone``; a second slot ``chest`` with a mesh part, ``covered_by: [top]``, rig ``g_tip``; a third
slot ``feet_detail`` WITHOUT a mesh part, ``covered_by: [bottom]``, rig ``g_motion`` (never a part, never hidden).
Items: ``jeans`` (slots [bottom]), ``jacket`` (slots [outer], closable, ``covers: [top]``), ``boxers``
(slots [underwear_bottom]), ``shirt`` (slots [top]).

[1] covered_part_groups(character, item, profile):
    a. nothing worn, preview of ``jeans`` → jeans counts in its own slot bottom → groin covered → [g_bone, g_chain]
       (sorted); chest not covered (no top) → g_tip absent; feet_detail has no mesh part → g_motion absent.
    b. nothing worn, preview of ``jacket`` (closed by default) → its slot outer and its covers [top] → chest covered
       → [g_tip]; groin exposed.
    c. ``boxers`` worn, preview of ``jacket`` → the worn outfit counts → groin covered by boxers, chest by the closed
       jacket → [g_bone, g_chain, g_tip].
    d. ``boxers`` worn, ``jacket`` worn OPEN (``equipped_options.piece_state`` open), preview of ``jacket`` → an open piece covers nothing
       → [g_bone, g_chain] only.
    e. ``jeans`` worn in bottom, preview of ``jeans`` → [g_bone, g_chain] (the worn slot, not added twice).
[2] covered_parts_token: [] → "" ; [g_bone, g_chain] → "-h" + sha1("g_bone,g_chain")[:8], order-independent.
[3] without_covered_parts on a synthetic GLB with nodes body (mesh 0), Part (mesh 1, skin 0, extras
    attached_part g_chain), garment (mesh 2) and a bone node:
    - groups [] or [g_tip] → the SAME bytes object back;
    - groups [g_chain] → node Part has neither ``mesh`` nor ``skin``; body keeps mesh 0, garment mesh 2; still 4
      nodes, 3 meshes, BIN chunk byte-identical.
[4] figure_build._served_state with stub readers (``garment_assembly.bare_meta_of`` → ``mesh_items.effective =
    [jeans, shoes]``):
    a. match "base" (Ruling A119: the plain body served; the delivered figure paints "blouse"), garments {shoes}
       carried → yellow SERVED_PLAIN, missing [blouse PIECE_NO_TEXTURE, jeans PIECE_NO_FIT] (painted first),
       pieces "blouse, Jeans" (no item row for the blouse: its id is its name).
    b. exact, assembled sidecar garments {jeans, shoes} → green SERVED_COMPLETE.
    c. exact, assembled garments {shoes}; _wanted's left_off {jeans: "deep_push_share 0.225 > 0.12"} → red
       SERVED_WITHOUT, pieces "Jeans", missing [{jeans, PIECE_REFUSED, detail "deep_push_share 0.225 > 0.12",
       pending False}].
    d. exact, garments {shoes}; jeans neither wanted nor left off; its plain fit refused ("deep_push_share 0.1512 >
       0.12") → red, missing reason PIECE_REFUSED_PLAIN with that detail.
    e. exact, bare file served (assembly not current), _wanted lists both → blue SERVED_ASSEMBLING, pieces
       "Jeans, Shoes" (both pending).
    f. (removed with Ruling A119: the pipeline serves no "stale" / "nearest" model any more.)
    g. hair in ``equipped_mesh_pieces`` is never counted as a missing outfit piece: effective [jeans, hairX],
       hairX worn as hair, garments {jeans} → green.
    And _not_on_figure gives the jeans rows without a note NOT_ON_FIGURE for case c, not for case e.
[5] Fails on the old code: at commit d1ca152281426caee1e5fa1397cf6ee1e89d0a6f the fit-model route served the stored
    GLB untouched (no ``covered_part_groups`` in app/routes/characters.py) and the Figure payload had no
    ``served_state`` (app/core/figure_build.py) — read with ``git show``; skipped when git is unavailable.
"""
import hashlib
import json
import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
TMP = tempfile.mkdtemp(prefix="smoke_a75_")
os.environ["STORAGE_DIR"] = str(Path(TMP) / "world")
os.environ["INSTANCE_DIR"] = str(Path(TMP) / "instance")
Path(os.environ["STORAGE_DIR"]).mkdir()
Path(os.environ["INSTANCE_DIR"]).mkdir()

from app.core import paths  # noqa: E402

paths.init(os.environ["STORAGE_DIR"])
paths.init_instance(os.environ["INSTANCE_DIR"])

from app.core import fit_attempts, figure_build  # noqa: E402
import app.plugins.registry as registry  # noqa: E402
import app.models.inventory as inventory  # noqa: E402
import app.core.outfit_renderer as outfit_renderer  # noqa: E402

FAILS = []


def check(name, got, want):
    if got != want:
        FAILS.append(f"{name}: got {got!r}, want {want!r}")
    else:
        print(f"ok  {name}")


# --- Stubs -----------------------------------------------------------------------------------------------------
def rig(gid):
    return SimpleNamespace(id=gid)


SLOTS = [
    SimpleNamespace(id="groin", mesh_part=SimpleNamespace(switch="blender_part"),
                    covered_by=["bottom", "underwear_bottom"], rigs=[rig("g_chain"), rig("g_bone")]),
    SimpleNamespace(id="chest", mesh_part=SimpleNamespace(switch="blender_part"), covered_by=["top"],
                    rigs=[rig("g_tip")]),
    SimpleNamespace(id="feet_detail", mesh_part=None, covered_by=["bottom"], rigs=[rig("g_motion")]),
]
registry.packages = lambda: [SimpleNamespace(body_slots=SLOTS)]
ITEMS = {
    "jeans": {"name": "Jeans", "category": "outfit_piece", "outfit_piece": {"slots": ["bottom"]}},
    "jacket": {"name": "Jacket", "category": "outfit_piece",
               "outfit_piece": {"slots": ["outer"], "covers": ["top"], "closable": True}},
    "boxers": {"name": "Boxers", "category": "outfit_piece", "outfit_piece": {"slots": ["underwear_bottom"]}},
    "shirt": {"name": "Shirt", "category": "outfit_piece", "outfit_piece": {"slots": ["top"]}},
    "shoes": {"name": "Shoes", "category": "outfit_piece", "outfit_piece": {"slots": ["feet"]}},
    "hairX": {"name": "Hair X", "category": "garment"},
}
inventory.get_item = lambda item_id: ITEMS.get(item_id)
outfit_renderer._get_item = lambda item_id: ITEMS.get(item_id)
outfit_renderer.is_free_text_wardrobe = lambda profile: False

# --- [1] covered_part_groups -----------------------------------------------------------------------------------
cpg = fit_attempts.covered_part_groups
check("1a jeans alone", cpg("C", "jeans", profile={"equipped_pieces": {}}), ["g_bone", "g_chain"])
check("1b jacket alone", cpg("C", "jacket", profile={"equipped_pieces": {}}), ["g_tip"])
check("1c boxers worn + jacket", cpg("C", "jacket", profile={"equipped_pieces": {"underwear_bottom": "boxers"}}),
      ["g_bone", "g_chain", "g_tip"])
check("1d jacket worn open", cpg("C", "jacket", profile={
    "equipped_pieces": {"underwear_bottom": "boxers", "outer": "jacket"},
    "equipped_options": {"piece_state": {"jacket": "open"}}}),
      ["g_bone", "g_chain"])
check("1e jeans worn", cpg("C", "jeans", profile={"equipped_pieces": {"bottom": "jeans"}}), ["g_bone", "g_chain"])

# --- [2] covered_parts_token -----------------------------------------------------------------------------------
check("2 empty token", fit_attempts.covered_parts_token([]), "")
want = "-h" + hashlib.sha1(b"g_bone,g_chain").hexdigest()[:8]
check("2 token", fit_attempts.covered_parts_token(["g_chain", "g_bone"]), want)

# --- [3] without_covered_parts ---------------------------------------------------------------------------------
from app.core.glb_mesh import pack_glb  # noqa: E402
from app.core.model_validate import parse_glb  # noqa: E402

BIN = bytes(range(48))
GLTF = {"asset": {"version": "2.0"}, "buffers": [{"byteLength": len(BIN)}],
        "nodes": [{"name": "body", "mesh": 0}, {"name": "Part", "mesh": 1, "skin": 0,
                                                 "extras": {"attached_part": "g_chain"}},
                  {"name": "garment_clothing_jeans", "mesh": 2}, {"name": "Hips"}],
        "meshes": [{"primitives": []}, {"primitives": []}, {"primitives": []}],
        "skins": [{"joints": [3]}]}
GLB = pack_glb(json.loads(json.dumps(GLTF)), BIN)
check("3 no groups → same bytes", fit_attempts.without_covered_parts(GLB, []) is GLB, True)
check("3 other group → same bytes", fit_attempts.without_covered_parts(GLB, ["g_tip"]) is GLB, True)
out = parse_glb(fit_attempts.without_covered_parts(GLB, ["g_chain"]))
nodes = out["gltf"]["nodes"]
check("3 part node drawn", ("mesh" in nodes[1], "skin" in nodes[1]), (False, False))
check("3 body + garment keep meshes", (nodes[0].get("mesh"), nodes[2].get("mesh")), (0, 2))
check("3 counts", (len(nodes), len(out["gltf"]["meshes"])), (4, 3))
check("3 BIN unchanged", bytes(out["bin"][:len(BIN)]), BIN)

# --- [4] _served_state -----------------------------------------------------------------------------------------
from app.core import garment_assembly, model3d  # noqa: E402

BARE = Path(TMP) / "sig.glb"
ASM = Path(TMP) / "assembled" / "sig.glb"
STATE = {}


def setup(match, effective, garments, *, served_bare=False, left_off=None, wanted=(), plain_error=""):
    STATE.update(match=match, effective=effective, garments=garments, served_bare=served_bare,
                 left_off=left_off or {}, wanted=list(wanted), plain_error=plain_error)


model3d.find_model3d_serving = lambda c: (BARE, STATE["match"])
garment_assembly.bare_meta_of = lambda c, d, sig: {"mesh_items": {"effective": STATE["effective"]}}
from app.core import figure  # noqa: E402
from app.core.figure import Figure  # noqa: E402
figure.delivered_figure_cached = lambda c, profile=None, **_: Figure(
    signature="sig", bsig="base", shape="base", texture="", in_body=(), painted=("blouse",), own=("shoes",))
garment_assembly.effective_mesh_items = lambda meta: list(meta["mesh_items"]["effective"])
garment_assembly.served = lambda c, p, tier: BARE if STATE["served_bare"] else ASM
garment_assembly.read_sidecar = lambda p: {"garments": {g: {} for g in STATE["garments"]}}


def fake_wanted(c, profile, *, bare_meta=None, left_off=None, **_):
    if left_off is not None:
        left_off.update(STATE["left_off"])
    return [{"item_id": i, "pending": True} for i in STATE["wanted"]]


garment_assembly._wanted = fake_wanted
fit_attempts.fit_status = lambda c, i, body, profile=None: (
    {"failure": {"error": STATE["plain_error"]}} if STATE["plain_error"] and i == "jeans" else {"failure": None})
fb = figure_build
served = fb._served_state

setup("base", ["jeans", "shoes"], ["shoes"])
s = served("C", profile={})
check("4a plain body served", (s["light"], s["state"], s["pieces"], [(m["item_id"], m["reason"]) for m in s["missing"]]),
      ("yellow", fb.SERVED_PLAIN, "blouse, Jeans",
       [("blouse", fb.PIECE_NO_TEXTURE), ("jeans", fb.PIECE_NO_FIT)]))
setup("exact", ["jeans", "shoes"], ["jeans", "shoes"])
s = served("C", profile={})
check("4b complete", (s["light"], s["state"]), ("green", fb.SERVED_COMPLETE))
setup("exact", ["jeans", "shoes"], ["shoes"], left_off={"jeans": "deep_push_share 0.225 > 0.12"})
s = served("C", profile={})
check("4c refused on body", (s["light"], s["state"], s["pieces"], s["missing"]),
      ("red", fb.SERVED_WITHOUT, "Jeans", [{"item_id": "jeans", "name": "Jeans", "reason": fb.PIECE_REFUSED,
                                            "detail": "deep_push_share 0.225 > 0.12", "pending": False}]))
state_c = s
setup("exact", ["jeans", "shoes"], ["shoes"], plain_error="deep_push_share 0.1512 > 0.12")
s = served("C", profile={})
check("4d refused on plain body", (s["light"], s["missing"][0]["reason"], s["missing"][0]["detail"]),
      ("red", fb.PIECE_REFUSED_PLAIN, "deep_push_share 0.1512 > 0.12"))
setup("exact", ["jeans", "shoes"], [], served_bare=True, wanted=["jeans", "shoes"])
s = served("C", profile={})
check("4e assembling", (s["light"], s["state"], s["pieces"]), ("blue", fb.SERVED_ASSEMBLING, "Jeans, Shoes"))
state_e = s
setup("exact", ["jeans", "hairX"], ["jeans"])
s = served("C", profile={"equipped_mesh_pieces": {"hair": "hairX"}})
check("4g hair not counted", s["light"], "green")

rows = [{"item_id": "jeans", "note": ""}]
changes = [{"key": "jeans", "note": ""}]
fb._not_on_figure(state_e, changes, rows)
check("4 pending: no note added", (rows[0]["note"], changes[0]["note"]), ("", ""))
fb._not_on_figure(state_c, changes, rows)
check("4 refused → not on figure", (rows[0]["note"], changes[0]["note"]), (fb.NOT_ON_FIGURE, fb.NOT_ON_FIGURE))

# --- [5] fails on the old code ---------------------------------------------------------------------------------
OLD = "d1ca152281426caee1e5fa1397cf6ee1e89d0a6f"
try:
    route = subprocess.run(["git", "-C", str(REPO), "show", f"{OLD}:app/routes/characters.py"],
                           capture_output=True, text=True, check=True).stdout
    build = subprocess.run(["git", "-C", str(REPO), "show", f"{OLD}:app/core/figure_build.py"],
                           capture_output=True, text=True, check=True).stdout
    check("5 old route served the stored part", "covered_part_groups" in route, False)
    check("5 old payload had no served_state", "served_state" in build, False)
except (OSError, subprocess.CalledProcessError) as e:
    print(f"skip [5]: git unavailable ({e})")

if FAILS:
    print("\nFAILED:\n  " + "\n  ".join(FAILS))
    sys.exit(1)
print("\nALL OK")
