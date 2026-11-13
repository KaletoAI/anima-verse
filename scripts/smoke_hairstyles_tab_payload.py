#!/usr/bin/env python3
"""Smoke: the read-only data the rebuilt Hairstyles tab reads (Task UI4 of
docs/superpowers/plans/2026-11-12-unified-worn-pieces.md).

Usage:  ./.venv/bin/python scripts/smoke_hairstyles_tab_payload.py

No server, no world: storage is a temp dir (``paths.init`` before any world-DB import); the Build planner is
replaced by stubs where a case needs it.

THE CASES, DERIVED BY HAND
--------------------------
[1] ``hair_motion.preview_payload`` — the live Stiffness preview of the previewed fit. A record whose
    ``report.chains`` has two chains:
      chain 0: stiffness 0.40, weighted HairGen_c00_00, HairGen_c00_01 (the ``_end`` leaf never swings)
      chain 3: stiffness 0.75, weighted HairGen_c03_00
    and ``inputs.swing`` True. With Swing on and Stiffness 1 each group's frequency is
    ``HAIR_FREQ_PER_STIFFNESS`` (3.7 Hz per unit) × its chain stiffness, inside 0.8..6.0 Hz:
      hair_c00: 3.7 × 0.40 = 1.48 Hz  · bones [HairGen_c00_00, HairGen_c00_01]
      hair_c03: 3.7 × 0.75 = 2.775 Hz · bones [HairGen_c03_00]
    ``chain_stiffness`` = {hair_c00: 0.4, hair_c03: 0.75}; ``freq`` = {per_stiffness 3.7, min_hz 0.8,
    max_hz 6.0} (the client recomputes a dragged factor f as clamp(3.7 × s × f)); ``fit_swing`` True.
    The same record with ``inputs.swing`` False → ``fit_swing`` False (groups still listed: the client says
    the fit has no swinging cards). A record without ``report.chains`` (a fit from before the spring chains)
    → None; no record → None.
[2] ``garment_hair.wear_estimate`` — what the Wear button spends. The profile wears hairstyle ``hs_a``;
    estimating ``hs_b``:
      - the plan is made for a COPY of the profile with ``equipped_mesh_pieces.hair`` = ``hs_b`` (every other
        worn mesh piece kept: ``feet`` stays ``boot_1``), the stored profile unchanged;
      - "Build automatically" on → an automatic plan (``explicit`` False) and ``automatic`` True; off → the
        manual plan (``explicit`` True), ``automatic`` False;
      - ``hub_jobs`` / ``note`` are the planner's cost of that plan (stub: 9 → 9, None → None);
      - the worn hairstyle ``hs_a`` → None; off the pipeline → None; a planner that raises → None.
[3] The hair GET names each step's hub jobs from ``garments.HUB_JOBS`` (the buttons' "1 hub job" / "no hub
    job"): HUB_JOBS["hair:hairdeck"] = {hairdeck: 1, fit: 0} and HUB_JOBS["hair:body"] = {}; the route
    sends ``step_jobs`` from that table and ``preview_motion`` from ``hair_motion.preview_payload``; the
    hairstyles GET sends ``wear`` per hairstyle (``wear_estimate``), ``due`` (the steps of
    ``garments.run_estimate``) plus ``pipeline`` and ``auto_build``;
    ``garments.hairdeck_panel``'s placement carries ``pivot`` from the newest fit's ``report.placement``.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP = tempfile.mkdtemp(prefix="smoke_hairstyles_")
from app.core import paths  # noqa: E402

paths.init(TMP)

failures = []


def check(label, got, want):
    if got != want:
        failures.append(f"{label}: got {got!r}, want {want!r}")


# [1] the live Stiffness preview ------------------------------------------------------------------------------
from app.core import hair_motion  # noqa: E402

record = {"inputs": {"swing": True}, "report": {"chains": {"count": 2, "chains": [
    {"index": 0, "stiffness": 0.4, "bones": ["HairGen_c00_00", "HairGen_c00_01", "HairGen_c00_end"],
     "weighted": ["HairGen_c00_00", "HairGen_c00_01"], "rigid": []},
    {"index": 3, "stiffness": 0.75, "bones": ["HairGen_c03_00", "HairGen_c03_end"],
     "weighted": ["HairGen_c03_00"], "rigid": []},
]}}}
got = hair_motion.preview_payload("Demo", None, record, profile={})
check("[1] groups", sorted((got or {}).get("groups", {})), ["hair_c00", "hair_c03"])
groups = (got or {}).get("groups", {})
check("[1] hair_c00 freq", groups.get("hair_c00", {}).get("freq_hz"), 1.48)
check("[1] hair_c03 freq", groups.get("hair_c03", {}).get("freq_hz"), 2.775)
check("[1] hair_c00 bones", groups.get("hair_c00", {}).get("bones"), ["HairGen_c00_00", "HairGen_c00_01"])
check("[1] hair_c03 bones", groups.get("hair_c03", {}).get("bones"), ["HairGen_c03_00"])
check("[1] chain stiffness", (got or {}).get("chain_stiffness"), {"hair_c00": 0.4, "hair_c03": 0.75})
check("[1] freq mapping", (got or {}).get("freq"), {"per_stiffness": 3.7, "min_hz": 0.8, "max_hz": 6.0})
check("[1] fit swing on", (got or {}).get("fit_swing"), True)
off = hair_motion.preview_payload("Demo", None, {**record, "inputs": {"swing": False}}, profile={})
check("[1] fit swing off", (off or {}).get("fit_swing"), False)
check("[1] before the spring chains", hair_motion.preview_payload("Demo", None, {"report": {}}, profile={}), None)
check("[1] no record", hair_motion.preview_payload("Demo", None, None, profile={}), None)

# [2] the Wear estimate ----------------------------------------------------------------------------------------
from app.core import figure_build, garment_hair  # noqa: E402

stored = {"equipped_mesh_pieces": {"hair": "hs_a", "feet": "boot_1"}}
calls = []
state = {"pipeline": True, "auto": True, "jobs": 9, "raise": False}


def fake_plan(name, *, profile=None, explicit=True, resolved=None):
    if state["raise"]:
        raise RuntimeError("planner down")
    calls.append((name, profile, explicit))
    return ["step"]


def fake_cost(name, steps=None):
    return {"hub_jobs": state["jobs"], "steps": [], "note": f"cost {state['jobs']}"}


figure_build.on_pipeline = lambda name, profile=None: state["pipeline"]
figure_build.auto_build_on = lambda name, profile=None: state["auto"]
figure_build.plan = fake_plan
figure_build.cost = fake_cost

got = garment_hair.wear_estimate("Demo", "hs_b", profile=stored)
check("[2] automatic", got, {"hub_jobs": 9, "automatic": True, "note": "cost 9"})
check("[2] plan of the trial profile", calls[-1][1].get("equipped_mesh_pieces"), {"hair": "hs_b", "feet": "boot_1"})
check("[2] automatic plan", calls[-1][2], False)
check("[2] stored profile unchanged", stored, {"equipped_mesh_pieces": {"hair": "hs_a", "feet": "boot_1"}})
state.update(auto=False, jobs=None)
got = garment_hair.wear_estimate("Demo", "hs_b", profile=stored)
check("[2] manual", got, {"hub_jobs": None, "automatic": False, "note": "cost None"})
check("[2] manual plan", calls[-1][2], True)
check("[2] worn one", garment_hair.wear_estimate("Demo", "hs_a", profile=stored), None)
state.update(pipeline=False)
check("[2] off the pipeline", garment_hair.wear_estimate("Demo", "hs_b", profile=stored), None)
state.update(pipeline=True, **{"raise": True})
check("[2] planner raises", garment_hair.wear_estimate("Demo", "hs_b", profile=stored), None)

# [3] the routes' keys -----------------------------------------------------------------------------------------
from app.core import garments  # noqa: E402

check("[3] HairDeck step jobs", garments.HUB_JOBS.get("hair:hairdeck"), {"hairdeck": 1, "fit": 0})
check("[3] body step jobs", garments.HUB_JOBS.get("hair:body"), {})
route = (ROOT / "app/routes/characters.py").read_text(encoding="utf-8")
check("[3] step_jobs from HUB_JOBS",
      '"step_jobs": dict(garments.HUB_JOBS.get(f"hair:{method}") or {}),' in route, True)
check("[3] preview_motion", '"preview_motion": preview_motion,' in route
      and "hair_motion.preview_payload(" in route, True)
check("[3] wear per hairstyle", 'row["wear"] = (garment_hair.wear_estimate(character_name, row["id"], profile=profile)'
      in route, True)
check("[3] due steps per HairDeck hairstyle", 'due = list(garments.run_estimate(character_name, row["id"], profile=profile)'
      in route and 'row["due"] = due' in route, True)
check("[3] pipeline + auto_build", '"pipeline": bool(pipeline),' in route and '"auto_build": bool(pipeline and' in route,
      True)
panel = (ROOT / "app/core/garments.py").read_text(encoding="utf-8")
check("[3] pivot", '"pivot": ((newest[1].get("report") or {}).get("placement") or {}).get("pivot")' in panel, True)

if failures:
    print("FAIL")
    for f in failures:
        print("  " + f)
    sys.exit(1)
print("OK — hairstyles tab payload: preview motion, wear estimate, step jobs, pivot")
