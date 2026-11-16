"""Ruling A134 smoke: a piece whose kept mesh needs only a CPU fit on the delivered body is never "not ready", and
"Regenerate" is an optional offer with its hub jobs.

Usage: ./.venv/bin/python scripts/smoke_garment_refit_offer.py

Hand-derived expectations (no world, ``run_estimate`` stubbed with the numbers the spec gives):
  1. plain run = {steps: ["fit"], hub_jobs: 0}            -> cpu_refit_suffices True   (only a CPU fit is due)
  2. plain run = {steps: ["mesh", "fit"], hub_jobs: 1}    -> False                     (a hub job is due)
  3. plain run = {steps: [], hub_jobs: 0}                 -> False                     (nothing is due at all)
  4. plain run = {hub_jobs: None} (unknown)               -> False
  5. _refit_offer, fit not accepted, case 1, stale ["base_model_changed"], forced chain from "worn" = 3+2+2+1 = 8
     (stub) -> {cpu_refit: True, regenerate: {step: "worn", hub_jobs: 8}}
  6. _refit_offer, fit accepted, no stale -> {cpu_refit: False, regenerate: None}
  7. piece_status worn, no fit, cpu_refit True, base ready -> reason figure.LEFT_OFF_REFIT (same text the figure
     gives, figure._not_fitted_reason); cpu_refit False -> base_body.NO_MESH_FIT (unchanged).
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="a134_")
os.environ["STORAGE_DIR"] = TMP
from app.core import paths  # noqa: E402
paths.init(TMP)

from app.core import base_body, figure, garment_set, garments  # noqa: E402
from app.core import garment_store as gs  # noqa: E402

FAIL = []


def check(name, got, want):
    ok = got == want
    print(("OK  " if ok else "FAIL"), name, "->", got, "" if ok else f"(want {want})")
    if not ok:
        FAIL.append(name)


ESTIMATES = {}


def fake_estimate(character_name, item_id, *, profile=None, state=None, from_step=""):
    return ESTIMATES[from_step]


garments.run_estimate = fake_estimate
for n, (est, want) in enumerate([({"steps": ["fit"], "hub_jobs": 0}, True),
                                 ({"steps": ["mesh", "fit"], "hub_jobs": 1}, False),
                                 ({"steps": [], "hub_jobs": 0}, False),
                                 ({"steps": ["fit"], "hub_jobs": None}, False)], 1):
    ESTIMATES[""] = est
    check(f"{n}. cpu_refit_suffices {est}", garments.cpu_refit_suffices("demo", "item_x", profile={}), want)

gs.steps_for = lambda kind, method: ("worn", "ghost", "cutout", "mesh", "fit")
ESTIMATES[""] = {"steps": ["fit"], "hub_jobs": 0}
ESTIMATES["worn"] = {"steps": ["worn", "ghost", "cutout", "mesh", "fit"], "hub_jobs": 8}
check("5. refit offer (stale, CPU fit due)",
      garments._refit_offer("demo", "item_x", "clothing", "edit_chain", "abc", {"fit": {"status": "missing"}},
                            ["base_model_changed"], {}),
      {"cpu_refit": True, "regenerate": {"step": "worn", "hub_jobs": 8}})
check("6. refit offer (fitted)",
      garments._refit_offer("demo", "item_x", "clothing", "edit_chain", "abc", {"fit": {"status": "accepted"}},
                            [], {}),
      {"cpu_refit": False, "regenerate": None})

info = {"fsig": "abc", "kind": "clothing", "steps": {"fit": {"status": "missing"}, "mesh": {"status": "accepted"}},
        "cpu_refit": True}
check("7a. piece_status reason (CPU fit)",
      garment_set.piece_status(info, worn=True, base_model_ready=True, left_out=True)["reason"], figure.LEFT_OFF_REFIT)
info["cpu_refit"] = False
check("7b. piece_status reason (no CPU fit)",
      garment_set.piece_status(info, worn=True, base_model_ready=True, left_out=True)["reason"], base_body.NO_MESH_FIT)

print("ALL OK" if not FAIL else f"{len(FAIL)} FAILED: {FAIL}")
sys.exit(1 if FAIL else 0)
