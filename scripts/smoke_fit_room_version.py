"""Smoke: A174 changed the room allowance without a fit-version step — A198 bumps clothing to 19 and keeps every
room-free fit current (``garment_fit.room_may_change``).

Usage:
    ./.venv/bin/python scripts/smoke_fit_room_version.py

No server, no world DB. Pure record checks, every expectation derived by hand from the rule:

  A174 (2c9d19f6c) moves a FIXED width allowance (``allowance`` not "auto") and a DEPTH allowance (``depth`` not 0)
  to ``room_offset`` after the clearance pass. Auto width with depth 0 passes ``room=None`` -> X unchanged, and the
  old code passed ``ease_z=None`` / ``allowance="auto"`` -> the same: such a fit is unchanged bit for bit. A shell
  takes no settings. So:
    [1] version 18, allowance 10            -> due: expected 19
    [2] version 18, allowance auto, depth 3 -> due: 19
    [3] version 18, allowance auto, depth 0 -> current: 18
    [4] version 18, no fit_settings         -> defaults (auto, 0) -> current: 18
    [5] version 18, shell with allowance 10 -> shell ignores it -> current: 18
    [6] version 17, unseeded opening, allowance 6 -> the chain would keep 17, but room changes -> 19
    [7] version 17, unseeded opening, defaults -> chain keeps 17
    [8] version 19 anything                 -> 19

Pre-fix proof: at e846d7d02 FIT_VERSION["clothing"] == 18 and [1]/[2]/[6] read current (18 / 18 / 17).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import garment_fit as gf  # noqa: E402

FAILED = []


def check(label, ok, detail=""):
    print(("OK   " if ok else "FAIL ") + label + ("" if ok else f"  -> {detail}"))
    if not ok:
        FAILED.append(label)


unseeded = {"components": [{"by": "recess", "dropped": True, "seeds": 0}], "faces": 0}


def rec(v, settings=None, shell=False, opening=None):
    inputs = {}
    if settings is not None:
        inputs["fit_settings"] = settings
    if shell:
        inputs["mesh_shape"] = "shell"
    r = {"kind": "clothing", "fit_version": v, "inputs": inputs, "report": {"transfer": {"sleeve_share": 0.3}}}
    if opening is not None:
        r["report"]["opening"] = opening
    return r


check("FIT_VERSION clothing 19", gf.FIT_VERSION["clothing"] == 19, gf.FIT_VERSION)
cases = [
    ("[1] fixed width", rec(18, {"allowance": 10, "depth": 0}), 19),
    ("[2] depth", rec(18, {"allowance": "auto", "depth": 3}), 19),
    ("[3] room-free", rec(18, {"allowance": "auto", "depth": 0}), 18),
    ("[4] no settings", rec(18), 18),
    ("[5] shell", rec(18, {"allowance": 10, "depth": 0}, shell=True), 18),
    ("[6] 17 with room", rec(17, {"allowance": 6, "depth": 0}, opening=unseeded), 19),
    ("[7] 17 room-free", rec(17, {"allowance": "auto", "depth": 0}, opening=unseeded), 17),
    ("[8] 19", rec(19, {"allowance": 10, "depth": 3}), 19),
]
for label, r, want in cases:
    got = gf.expected_fit_version(r)
    check(f"{label}: expected {want}", got == want, got)

print()
print("FAILED: %d — %s" % (len(FAILED), "; ".join(FAILED)) if FAILED else "all OK")
sys.exit(1 if FAILED else 0)
