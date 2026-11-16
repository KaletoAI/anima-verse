"""Garment templates (spike S0, Ruling A135): drape a worn piece onto a base body.

Not wired into the Build or the UI yet. This module only builds the job arguments
for ``app/blender/scripts/garment_template_drape.py`` and judges its result against
the spike thresholds of ``docs/superpowers/specs/2026-11-16-garment-templates-design.md``
section 8. The numbers are derived in ``scripts/smoke_garment_template_spike.py``.
"""
from pathlib import Path
from typing import Any, Dict, List

SCRIPT = "garment_template_drape.py"

# Spec section 8 pass marks (hand-derived in the smoke docstring).
THRESHOLDS = {
    "drape_cpu_s": 60.0,          # CPU seconds of the cloth run (all threads summed)
    "poke_share": 0.005,          # body vertices poking through, per pose
    "pin_drift_mm": 5.0,          # largest displacement of a pinned vertex
    "stretch_max": 1.3,           # longest edge / its pre-drape length, after the drape
    "bake_coverage": 0.85,        # template texels that received a view colour
}

# Pin rings by piece kind (where the cloth hangs from).
PIN_BY_KIND = {"skirt": "waist", "trousers": "waist", "top": "shoulders", "jacket": "shoulders",
               "dress": "shoulders"}


def mesh_args(fit_glb: Path, plain_body: Path, kind: str, tag: str, **over: Any) -> Dict[str, Any]:
    """Job args for draping an EXISTING generated piece (mode ``mesh``)."""
    args = {"mode": "mesh", "tag": tag, "fit_glb": str(fit_glb), "plain_body": str(plain_body),
            "pin": PIN_BY_KIND.get(kind, "shoulders"), "voxel_m": 0.006, "target_faces": 12000,
            "frames": 40, "quality": 6}
    args.update(over)
    return args


def judge(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Pass/fail rows for one drape result (``data`` of the script result)."""
    rows: List[Dict[str, Any]] = []
    drape = result.get("drape") or {}

    def row(name, value, limit, ok):
        rows.append({"check": name, "value": value, "limit": limit, "ok": bool(ok)})

    if "cpu_s" in drape:
        row("drape_cpu_s", drape["cpu_s"], THRESHOLDS["drape_cpu_s"], drape["cpu_s"] < THRESHOLDS["drape_cpu_s"])
    if "pin_drift_mm" in drape:
        row("pin_drift_mm", drape["pin_drift_mm"], THRESHOLDS["pin_drift_mm"],
            drape["pin_drift_mm"] < THRESHOLDS["pin_drift_mm"])
    if "stretch_max" in drape:
        row("stretch_max", drape["stretch_max"], THRESHOLDS["stretch_max"],
            drape["stretch_max"] < THRESHOLDS["stretch_max"])
    for pose, m in (result.get("draped") or {}).items():
        row(f"poke_share[{pose}]", m["poke_share"], THRESHOLDS["poke_share"],
            m["poke_share"] < THRESHOLDS["poke_share"])
    bake = result.get("bake") or {}
    if "coverage" in bake:
        row("bake_coverage", bake["coverage"], THRESHOLDS["bake_coverage"],
            bake["coverage"] > THRESHOLDS["bake_coverage"])
    return rows
