"""Smoke: A172 — template parameters survive a save, the dialog's starting kind, the live drape progress.

Usage:
    ./.venv/bin/python scripts/smoke_garment_template_a172.py

No server, no Blender, no LLM: a throwaway world (``paths.init`` into a temp dir BEFORE any world import), a world
outfit piece made with ``inventory.add_item``, the live progress driven by hand.

Expected, derived by hand from ``app/models/inventory.py`` and ``app/core/garment_template.py``:

[1] ``set_params`` on a world T-shirt (slots ["top"]) with {kind top, length 0.6, sleeves short} stores
    ``outfit_piece.template`` and ``get_item`` reads it back: params_of → kind "top", length_m 0.6, sleeves "short",
    shoulders "covered" (a top is always covered). Before A172 ``update_item._apply_updates`` rebuilt
    ``outfit_piece`` from its whitelist without "template", so this read gave None while set_params returned the
    record (the user's Save of Kai's T-shirt "worked" and was gone).
[2] A later edit that does not name the template keeps it: ``update_item(id, {"name": ...})`` and an
    ``outfit_piece`` update without "template" (the Items tab saving slots) both leave params_of "top" / 0.6.
    An ``outfit_piece`` update with "template": None clears it (params_of None).
[3] default_kind: slots ["top"] + "T-Shirt" → top; ["outer"] → jacket; ["top"] + "Denim jacket" → jacket;
    ["bottom"] + "Blue jeans" → trousers; ["bottom"] + "Pleated skirt" → skirt; ["top", "bottom"] → dress;
    ["top"] + "Summer dress" → dress; [] → skirt (PARAM_SPEC's default).
[4] kind_defaults("top") = PARAM_SPEC defaults + KIND_DEFAULTS["top"]: length 0.6, sleeves "short", fit 0.4,
    shoulders "covered", flare 0.3 (reset: not a top field), slit "none"; kind_defaults("skirt"): length 0.5, sleeves
    "none", shoulders "strapless".
[5] live_progress: none registered → None. After ``_live_stage(key, "measure_body")`` → stage "measure_body", label
    "Measuring the body", frame None, attempt 1. After ``_live_stage(key, "blender", file=f, attempt=2)`` with f
    holding {stage "shapes", pose "sit", index 2, count 4, frame 8, frames 16} → stage "shapes", label "Draping the
    pose shapes", index 2 / count 4, pose "sit", frame 8 / frames 16, attempt 2; an unreadable file → stage "setup"
    ("Cutting the panels in Blender"). elapsed_s ≥ 0. ``_live_end`` → None again.
[6] the Blender scripts write the side channel: garment_template_drape.progress merges fields and replaces the
    file (checked by importing the function's source without bpy — the module needs Blender, so the function is
    exec'd alone).
"""
import ast
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_SCRATCH = Path(tempfile.mkdtemp(prefix="smoke-a172-"))
from app.core import paths  # noqa: E402
paths.init(_SCRATCH / "world")
paths.init_instance(_SCRATCH / "instance")

from app.core import garment_template as gt  # noqa: E402
from app.models import inventory  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    print(("ok   " if cond else "FAIL ") + name + (f"   [{detail}]" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


# [1] + [2]
try:
    from app.core import db
    db.init_schema()
except Exception as e:  # noqa: BLE001
    print("schema:", e)
shirt = inventory.add_item("T-Shirt", category="outfit_piece", prompt_fragment="blue t-shirt",
                           outfit_piece={"slots": ["top"], "covers": [], "mesh_mode": "template"})
iid = shirt["id"]
record = gt.set_params(iid, {"kind": "top", "length_m": 0.6, "sleeves": "short"}, source="llm")
p = gt.params_of(inventory.get_item(iid))
check("[1] stored template reads back", p is not None and p["kind"] == "top" and p["length_m"] == 0.6
      and p["sleeves"] == "short" and p["shoulders"] == "covered", str(p))
check("[1] source kept", gt.template_of(inventory.get_item(iid)).get("source") == "llm")
inventory.update_item(iid, {"name": "Blue T-Shirt"})
p = gt.params_of(inventory.get_item(iid))
check("[2] a name edit keeps it", p is not None and p["kind"] == "top" and p["length_m"] == 0.6, str(p))
inventory.update_item(iid, {"outfit_piece": {"slots": ["top"], "covers": ["underwear_top"]}})
p = gt.params_of(inventory.get_item(iid))
check("[2] a slot edit keeps it", p is not None and p["kind"] == "top", str(p))
check("[2] mode kept too", (inventory.get_item(iid).get("outfit_piece") or {}).get("mesh_mode") == "template")
inventory.update_item(iid, {"outfit_piece": {"slots": ["top"], "template": None}})
check("[2] template None clears it", gt.params_of(inventory.get_item(iid)) is None)

# [3]
def it(slots, name=""):
    return {"name": name, "outfit_piece": {"slots": slots}}


for slots, name, want in ((["top"], "T-Shirt", "top"), (["outer"], "Coat", "jacket"),
                          (["top"], "Denim jacket", "jacket"), (["bottom"], "Blue jeans", "trousers"),
                          (["bottom"], "Pleated skirt", "skirt"), (["top", "bottom"], "Overall", "dress"),
                          (["top"], "Summer dress", "dress"), ([], "", "skirt")):
    got = gt.default_kind(it(slots, name))
    check(f"[3] default_kind {slots} {name!r} -> {want}", got == want, got)

# [4]
top = gt.kind_defaults("top")
check("[4] top defaults", (top["kind"], top["length_m"], top["sleeves"], top["fit"], top["shoulders"], top["flare"],
                           top["slit"]) == ("top", 0.6, "short", 0.4, "covered", 0.3, "none"), str(top))
sk = gt.kind_defaults("skirt")
check("[4] skirt defaults", (sk["length_m"], sk["sleeves"], sk["shoulders"]) == (0.5, "none", "strapless"), str(sk))

# [5]
key = ("Kai", "item_x")
check("[5] none registered", gt.live_progress(*key) is None)
gt._live_stage(key, "measure_body")
lv = gt.live_progress(*key)
check("[5] server stage", lv and lv["stage"] == "measure_body" and lv["label"] == "Measuring the body"
      and lv["frame"] is None and lv["attempt"] == 1 and lv["elapsed_s"] >= 0, str(lv))
f = _SCRATCH / "progress.json"
f.write_text(json.dumps({"stage": "shapes", "pose": "sit", "index": 2, "count": 4, "frame": 8, "frames": 16}))
gt._live_stage(key, "blender", file=str(f), attempt=2)
lv = gt.live_progress(*key)
check("[5] blender record", lv and (lv["stage"], lv["label"], lv["index"], lv["count"], lv["pose"], lv["frame"],
                                     lv["frames"], lv["attempt"])
      == ("shapes", "Draping the pose shapes", 2, 4, "sit", 8, 16, 2), str(lv))
f.write_text("{broken")
lv = gt.live_progress(*key)
check("[5] unreadable file -> setup", lv and lv["stage"] == "setup" and lv["label"] == "Cutting the panels in Blender",
      str(lv))
gt._live_end(key)
check("[5] ended", gt.live_progress(*key) is None)

# [6]
src = (ROOT / "app/blender/scripts/garment_template_drape.py").read_text()
tree = ast.parse(src)
fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "progress")
ns = {"Path": Path, "PROGRESS": {"file": str(_SCRATCH / "bl.json"), "state": {}}}
exec(compile(ast.Module(body=[fn], type_ignores=[]), "progress", "exec"), ns)
ns["progress"](stage="drape", frame=1, frames=30)
ns["progress"](frame=7)
got = json.loads((_SCRATCH / "bl.json").read_text())
check("[6] side channel merges", got == {"stage": "drape", "frame": 7, "frames": 30}, str(got))

print("\nFAILED: " + ", ".join(FAILS) if FAILS else "\nall ok")
sys.exit(1 if FAILS else 0)
