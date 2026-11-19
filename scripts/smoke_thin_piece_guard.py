"""Smoke: Ruling A118 J6 / A216 — an own-mesh piece too thin for its chain is refused before the ghost step
(``garment_gates.thin_piece``, ``garments._thin_piece_check``).

Usage: ./.venv/bin/python scripts/smoke_thin_piece_guard.py   (no server; temp storage, monkeypatched images)

Expected values, derived by hand (THIN_PIECE_MAX = 0.03, exclusive):

[1] ``thin_piece``: Lirien's necklace {front 0.0086, back 0.0089} → True; {front 0.0086, back 0.03} → False (0.03 is
    not < 0.03); {front 0.0299} → True; {} → False; {front None} → False (a view without an accepted gate never
    counts as thin).
[2] ``_thin_piece_check`` with the worn gates {front 0.0086, back 0.0089}: a clothing piece in own_mesh → raises
    ``_Refused`` at step "ghost", error "Too thin for its own mesh — use Painted or Accessory", gates code
    "THIN_PIECE" with both shares and limit 0.03; the same piece in shell → no refusal; kind footwear → no refusal;
    a clothing piece with {front 0.2, back 0.18} (a shirt) → no refusal. A216 review M3: the same thin shares on a
    piece worn on slot ``wrist`` (not ``neck``) → no refusal; on ``neck`` with a fit already (``_fit_state``
    ``accepted`` or ``stale``) → no refusal; ``missing`` → refused.
[3] The check sits before the ghost step in both run paths of ``garments._run_locked`` (source scan: two calls
    of ``_thin_piece_check`` guarded by ``step == "ghost"``), so no ghost job is ever submitted for such a piece.
"""
import os
import re
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
TMP = tempfile.mkdtemp(prefix="smoke_thin_piece_")
os.environ["STORAGE_DIR"] = TMP
from app.core import paths  # noqa: E402

paths.init(TMP)
from app.core import garment_gates, garments  # noqa: E402

FAIL = []


def check(name, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{name}: {got!r}" + ("" if ok else f" (expected {want!r})"))
    if not ok:
        FAIL.append(name)


check("[1] necklace", garment_gates.thin_piece({"front": 0.0086, "back": 0.0089}), True)
check("[1] one view at the limit", garment_gates.thin_piece({"front": 0.0086, "back": 0.03}), False)
check("[1] 0.0299", garment_gates.thin_piece({"front": 0.0299}), True)
check("[1] empty", garment_gates.thin_piece({}), False)
check("[1] no gate", garment_gates.thin_piece({"front": None}), False)

SHARES = {}
garments._step_views = lambda c, i, s, p: list(SHARES)
garments._image = lambda c, i, f, s, v, attempt=0: v
garments._accepted = lambda path: SHARES.get(path) is not None
garments._accepted_gate = lambda path: {"garment_share": SHARES[path]}
from app.core import base_body  # noqa: E402
base_body.current_base = lambda c, profile=None: ("base1", "B1")
FIT = {"state": "missing"}
garments._fit_state = lambda c, i, f, sha, method="edit_chain", profile=None: FIT["state"]


def run(mode, kind="clothing", shares=None, slots=("neck",)):
    SHARES.clear()
    SHARES.update(shares or {"front": 0.0086, "back": 0.0089})
    it = {"id": "item_n", "category": "outfit_piece", "outfit_piece": {"slots": list(slots), "mesh_mode": mode}}
    try:
        garments._thin_piece_check("C", it, kind, "f", {})
        return None
    except garments._Refused as e:
        return e


e = run("own_mesh")
check("[2] own_mesh refused", e is not None, True)
if e is not None:
    check("[2] step", e.step, "ghost")
    check("[2] text", e.error, "Too thin for its own mesh — use Painted or Accessory")
    check("[2] gates", e.gates, {"code": "THIN_PIECE", "garment_share": {"front": 0.0086, "back": 0.0089},
                                 "limit": 0.03})
check("[2] shell exempt", run("shell"), None)
check("[2] footwear exempt", run("own_mesh", kind="footwear"), None)
check("[2] shirt passes", run("own_mesh", shares={"front": 0.2, "back": 0.18}), None)
check("[2] wrist piece exempt (M3)", run("own_mesh", slots=("wrist",)), None)
for state, refused in (("accepted", False), ("stale", False), ("missing", True)):
    FIT["state"] = state
    check(f"[2] fit {state}", run("own_mesh") is not None, refused)
FIT["state"] = "missing"

src = open(os.path.join(ROOT, "app/core/garments.py"), encoding="utf-8").read()
calls = re.findall(r'if step == "ghost":\s*\n\s*(?:#[^\n]*\n\s*)?_thin_piece_check\(', src)
check("[3] guarded calls before the ghost step", len(calls), 2)

if FAIL:
    print(f"\n{len(FAIL)} check(s) failed: {FAIL}")
    sys.exit(1)
print("\nall checks passed")
