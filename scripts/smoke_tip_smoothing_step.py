#!/usr/bin/env python3
"""Tip smoothing is its own visible step with a record, due on base models built before it (Ruling A43).

Before a ``pair_tip`` group builds its stub, ``extension_bones.tip_mesh`` levels the source bump onto the surface
around it (Ruling A53, the levelling of A44) and refreshes the normals (Ruling A34). It runs inside the extension rebuild; A43 records it on the base
model (``meta["tip_smoothing"]``, ``extension_tip.TIP_SMOOTHING_VERSION``), makes a base without that record due
(Run all kind ``tip_smoothing``, Build step ``tip_smoothing``) and shows it as its own row (``tip_smoothing_state``,
the model step ``tip_smoothing`` between ``mesh_repair`` and ``extension_rig``).

Usage:
    ./.venv/bin/python scripts/smoke_tip_smoothing_step.py

Runs against a THROWAWAY storage directory (``paths.init(<tmp>)`` before any world module is imported) — no world,
no Blender, no server. One character "demo" with a stored base model ``base1.glb`` (+ ``prerig/base1.glb``); its
extension groups are two declarations — the source ``P`` (``pair_protrusion``) and the tip ``T`` (``pair_tip``,
depends on P). Blender (``refine.apply_script``) is a recorder that answers with the metrics below; normalisation,
validation and the mesh repair are stubbed as current.

The script's metrics of T (the numbers measured on the Kira copy, see a43-report.md): both placement rows carry
``source_smooth = {radius_m 0.0187333, iterations 292, moved 2522, max_shift_mm 4.546}``, ``tip_source "stub"``;
``tip_normals = {region_mm 40, inverted [3, 0], off_60 [7, 0]}``; per side ``source_level`` (Ruling A53: the source
bump above the fitted surface before → after and the placed tip's distance from the source apex — the A53 Kira copy):
``{bump_mm [1.81, 0.0], tip_from_source_mm 0.0}`` and ``{bump_mm [3.431, 0.0], tip_from_source_mm 0.0}``. ``V`` below
is ``TIP_SMOOTHING_VERSION`` (2 since Ruling A53).

[1] Marker missing → due. The sidecar's extension state is current (same fingerprint, applied, source current) and
    has NO ``tip_smoothing``: ``tip_smoothing_due(None, ["T"])`` True; ``model_tip_smoothing_due`` True;
    ``tip_smoothing_state`` → light "warn", summary "Not applied to this model yet — rebuilds the extension bones
    (local, no hub job)", groups [T]; ``figure_build._tip_smoothing_due`` True; ``base_run_all`` (plain body, face
    and repair current) → kind "tip_smoothing", steps [tip_smoothing 0, extension 0], hub_jobs 0; the model step
    row ``tip_smoothing`` sits right after ``mesh_repair`` and right before ``extension_rig``, status "missing"
    (nothing recorded). ``STEP_ORDER`` has ``tip_smoothing`` right after ``base_repair``; it holds the slot, is
    unpinned, and depends on ``plain_body``.
[2] After the extension rebuild → applied, with the numbers. ``_extension_rig_once(force=False)`` is NOT a no-op
    (Blender called once) although the extension fingerprint is current; the record is
    ``{version V, status built, groups: {T: {applied True, max_shift_mm 4.546, moved 2522, radius_mm 18.73
    (0.0187333 m x 1000, 2 decimals), passes 292, inverted [3, 0], off_60 [7, 0], region_mm 40, bump_mm [[1.81, 0.0],
    [3.431, 0.0]], tip_from_source_mm [0.0, 0.0]}}}``; due False;
    summary "Applied — max shift 4.5 mm, inverted normals 3 → 0", light "ok"; the model step is "done" with
    numbers {max_shift_mm 4.546, inverted_before 3, inverted_after 0, version V}; ``base_run_all`` → kind "" (current).
    A second ``_extension_rig_once(force=False)`` is a no-op (Blender not called again).
    A failed rebuild of a due model (a record of version 0; Blender answers not applied) keeps the groups and records
    status "failed" with the current version → not due, light "error" (no retry loop in automatic Builds).
    Rows without a levelling (no ``source_smooth``) → applied False, reason "Not smoothed", light "off" (a kept own
    tip no longer exists, Ruling A53); a levelling that could not reach a side (``source_smooth.error``) → reason
    "Source bump not levelled: <error>".
[3] No tip groups → no row: with the declarations [P] only, ``tip_smoothing_state`` is None, the model steps carry
    no ``tip_smoothing`` row, ``model_tip_smoothing_due`` False, and ``base_run_all`` stays "" (current).
    The same with T switched off for the model (``extension_rig_models[base1][T].enabled`` False).
[4] The version bump makes it due: with ``TIP_SMOOTHING_VERSION`` V + 1 the record of [2] (version V) → due True, light
    "warn", the "Not applied to this model yet" summary, Run all kind "tip_smoothing" again.

Fails on c5dccfb4: ImportError — ``extension_tip`` has no ``tip_smoothing_due``.
"""
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_tmp = Path(tempfile.mkdtemp(prefix="smoke_tip_smoothing_"))
from app.core import paths  # noqa: E402
paths.init(str(_tmp))
from app.core import db  # noqa: E402
db.init_schema()

from app.blender import refine  # noqa: E402
from app.core import base_body, extension_rig, extension_tip, figure_build, model3d, model_overview  # noqa: E402
from app.core.extension_tip import (model_tip_smoothing_due, tip_smoothing_due, tip_smoothing_record,  # noqa: E402
                                    tip_smoothing_state)
from app.core.keyed_lock import keyed_lock  # noqa: E402
from app.models.character import get_character_dir, get_character_profile, save_character_profile  # noqa: E402

FAILS = []
V = extension_tip.TIP_SMOOTHING_VERSION


def check(label, got, want=True):
    ok = got == want
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + ("" if ok else f"  — got {got!r}, want {want!r}"))
    if not ok:
        FAILS.append(label)


C, BSIG = "demo", "base1"
P = {"id": "P", "op": "pair_protrusion", "depends_on": None, "chains": [], "params": {}, "label": "Source"}
T = {"id": "T", "op": "pair_tip", "depends_on": "P", "chains": [], "params": {}, "label": "Tips"}
DECLARED = {"groups": [P, T]}

SMOOTH = {"radius_m": 0.0187333, "blend_m": 0.0026762, "iterations": 292, "moved": 2522, "max_shift_mm": 4.546,
          "edge_mm": 1.097, "folds_released": 15}
TIP_METRICS = {"placement": [{"tip": [0.05, -0.1, 1.3], "tip_source": "stub", "source_smooth": SMOOTH,
                              "source_level": {"bump_mm": [1.81, 0.0], "tip_from_source_mm": 0.0}},
                             {"tip": [-0.05, -0.1, 1.3], "tip_source": "stub", "source_smooth": SMOOTH,
                              "source_level": {"bump_mm": [3.431, 0.0], "tip_from_source_mm": 0.0}}],
               "tip_normals": {"region_mm": 40.0, "vertices": [524, 13297], "inverted": [3, 0], "off_60": [7, 0]},
               "normals_refreshed": 13198}
BLENDER = {"answer": {"applied": True, "data": {"status": "applied", "metrics": {"P": {"placement": []},
                                                                               "T": TIP_METRICS}}},
           "calls": 0}


def fake_apply_script(path, script, args, **_kw):
    BLENDER["calls"] += 1
    return json.loads(json.dumps(BLENDER["answer"]))


get_character_dir(C).mkdir(parents=True, exist_ok=True)
with keyed_lock("character_profile", C):
    assert save_character_profile(C, {"name": C})
directory = model3d.get_model3d_dir(C)
(directory / "prerig").mkdir(parents=True, exist_ok=True)
model = directory / f"{BSIG}.glb"
model.write_bytes(b"model")
(directory / "prerig" / f"{BSIG}.glb").write_bytes(b"source")
(directory / "prerig" / f"{BSIG}.json").write_text(json.dumps({"blender": {"steps": ["limb_weights"]},
                                                              "rig": "mixamo"}))


def fingerprint():
    profile = get_character_profile(C) or {}
    declarations = extension_rig.rig_groups_for(C, profile=profile)
    meta = model3d._read_sidecar(model)
    return extension_rig.extension_rig_fingerprint(
        declarations, extension_rig.effective_extension_overrides(profile, BSIG, meta, declarations))


def write_sidecar(**extra):
    meta = {"base": True, "rig": "mixamo", "blender": {"steps": ["limb_weights"]},
            "extension_rig": {"attempted": True, "status": "applied", "fingerprint": fingerprint(),
                              "groups": [g["id"] for g in DECLARED["groups"]],
                              "group_ops": {g["id"]: g["op"] for g in DECLARED["groups"]}},
            **extra}
    model.with_suffix(".json").write_text(json.dumps(meta))
    return meta


def run_all():
    return figure_build.base_run_all(C)


def steps_of(meta):
    return model_overview.base_model_steps(meta, front_meta=None, tip_smoothing=tip_smoothing_state(C, BSIG))


patches = [
    patch.object(extension_rig, "rig_groups_for", lambda *a, **k: [dict(g) for g in DECLARED["groups"]]),
    patch.object(model3d, "_on_older_base", lambda *a, **k: False),
    patch.object(model3d, "required_rig", lambda *a, **k: "mixamo"),
    patch.object(model3d, "_auto_normalize", lambda *a, **k: None),
    patch.object(model3d, "_validator_for", lambda *a, **k: (lambda data: {"ok": True})),
    patch.object(model3d, "_mesh_repair_due", lambda *a, **k: False),
    patch.object(model3d, "_repaired_base", lambda c, data, meta: data),
    patch("app.core.model_validate.validate_glb", lambda data: {"ok": True}),
    patch.object(refine, "apply_script", fake_apply_script),
    # Run all: the plain body, the face cleanup, the face retexture and the mesh repair are current.
    patch.object(figure_build, "on_pipeline", lambda *a, **k: True),
    patch.object(base_body, "base_refresh_plan", lambda *a, **k: {"signature": BSIG, "views": [], "model": False}),
    patch.object(model3d, "face_cleanup_state", lambda *a, **k: {}),
    patch.object(figure_build, "_face_retexture_pending", lambda *a, **k: ""),
    patch.object(figure_build, "_mesh_repair_due", lambda *a, **k: False),
    patch.object(base_body, "base_signature", lambda *a, **k: BSIG),
]
for p in patches:
    p.start()

try:
    # [1] marker missing → due
    meta = write_sidecar()
    check("[1] tip_smoothing_due(None, [T])", tip_smoothing_due(None, ["T"]), True)
    check("[1] tip_smoothing_due without tip groups", tip_smoothing_due(None, []), False)
    check("[1] model_tip_smoothing_due", model_tip_smoothing_due(C, model, model3d._read_sidecar(model)), True)
    state = tip_smoothing_state(C, BSIG)
    check("[1] state light", (state or {}).get("light"), "warn")
    check("[1] state summary", (state or {}).get("summary"),
          "Not applied to this model yet — rebuilds the extension bones (local, no hub job)")
    check("[1] state groups", (state or {}).get("groups"), [{"id": "T", "label": "Tips", "mode": "smoothed"}])
    check("[1] Build: tip smoothing due", figure_build._tip_smoothing_due(C, BSIG), True)
    plan_now = run_all()
    check("[1] Run all kind", plan_now["kind"], "tip_smoothing")
    check("[1] Run all steps", plan_now["steps"], [{"name": "tip_smoothing", "jobs": 0}, {"name": "extension", "jobs": 0}])
    check("[1] Run all hub jobs", plan_now["hub_jobs"], 0)
    ids = [row["id"] for row in steps_of(meta)]
    check("[1] step row order mesh_repair → tip_smoothing → extension_rig",
          ids[ids.index("mesh_repair"):ids.index("mesh_repair") + 3], ["mesh_repair", "tip_smoothing", "extension_rig"])
    row = next(r for r in steps_of(meta) if r["id"] == "tip_smoothing")
    check("[1] step row status", row["status"], "missing")
    order = figure_build.STEP_ORDER
    check("[1] STEP_ORDER: tip_smoothing right after base_repair", order[order.index("base_repair") + 1], "tip_smoothing")
    check("[1] tip_smoothing: slot, unpinned, depends on plain_body",
          ("tip_smoothing" in figure_build.SLOT_STEPS, "tip_smoothing" in figure_build.UNPINNED_STEPS,
           figure_build.DEPENDS.get("tip_smoothing"), "tip_smoothing" in figure_build._RUNNERS),
          (True, True, {"plain_body"}, True))

    # [2] after the extension rebuild → applied, with the numbers
    meta = model3d._read_sidecar(model)
    result = model3d._extension_rig_once(C, model, meta, force=False)
    check("[2] not a no-op", (bool(result.get("noop")), BLENDER["calls"]), (False, 1))
    record = meta.get("tip_smoothing") or {}
    check("[2] record head", (record.get("version"), record.get("status")), (V, "built"))
    check("[2] record of T", record.get("groups", {}).get("T"),
          {"applied": True, "reason": "", "max_shift_mm": 4.546, "moved": 2522, "radius_mm": 18.73, "passes": 292,
           "inverted": [3, 0], "off_60": [7, 0], "region_mm": 40.0, "bump_mm": [[1.81, 0.0], [3.431, 0.0]],
           "tip_from_source_mm": [0.0, 0.0]})
    model3d._publish_sidecar(model, meta)
    state = tip_smoothing_state(C, BSIG)
    check("[2] due after the rebuild", state["due"], False)
    check("[2] summary", (state["light"], state["summary"]), ("ok", "Applied — max shift 4.5 mm, inverted normals 3 → 0"))
    row = next(r for r in steps_of(meta) if r["id"] == "tip_smoothing")
    check("[2] step row", (row["status"], row["numbers"]),
          ("done", {"max_shift_mm": 4.546, "inverted_before": 3, "inverted_after": 0, "version": V}))
    check("[2] Run all current", run_all()["kind"], "")
    again = model3d._extension_rig_once(C, model, model3d._read_sidecar(model), force=False)
    check("[2] second build is a no-op", (bool(again.get("noop")), BLENDER["calls"]), (True, 1))

    BLENDER["answer"] = {"applied": False, "error": "boom", "data": {"status": "failed", "reason": "boom"}}
    failed_meta = model3d._read_sidecar(model)
    failed_meta["tip_smoothing"]["version"] = 0   # an older record: due, so the build runs (and fails)
    model3d._extension_rig_once(C, model, failed_meta, force=False)
    failed = failed_meta.get("tip_smoothing") or {}
    check("[2] failed rebuild keeps the groups", (failed.get("status"), sorted(failed.get("groups") or {})),
          ("failed", ["T"]))
    check("[2] failed record not due", tip_smoothing_due(failed, ["T"]), False)
    check("[2] failed light", extension_tip.tip_smoothing_summary(failed, False)[0], "error")
    bare = extension_tip.tip_smoothing_group({"placement": [{"tip_source": "stub"}, {"tip_source": "stub"}]})
    check("[2] rows without a levelling", (bare["applied"], bare["reason"]), (False, "Not smoothed"))
    check("[2] rows without a levelling: light", extension_tip.tip_smoothing_summary(
        tip_smoothing_record({"T": {"placement": [{"tip_source": "stub"}]}}, ["T"], "x"), False)[0], "off")
    unlevelled = extension_tip.tip_smoothing_group({"placement": [{"tip_source": "stub", "source_smooth": {
        **SMOOTH, "error": "no surface around the part to level"}}]})
    check("[2] a side the levelling could not reach says so", unlevelled["reason"],
          "Source bump not levelled: no surface around the part to level")
    BLENDER["answer"] = {"applied": True, "data": {"status": "applied", "metrics": {"P": {}, "T": TIP_METRICS}}}

    # [3] no tip groups → no row
    DECLARED["groups"] = [P]
    meta = write_sidecar()
    check("[3] no tip group: state None", tip_smoothing_state(C, BSIG), None)
    check("[3] no tip group: no step row", "tip_smoothing" in [r["id"] for r in steps_of(meta)], False)
    check("[3] no tip group: not due", model_tip_smoothing_due(C, model, model3d._read_sidecar(model)), False)
    check("[3] no tip group: Run all current", run_all()["kind"], "")
    DECLARED["groups"] = [P, T]
    model3d.set_model3d_options(C, {"signature": BSIG, "extension_rig": {"T": {"enabled": False}}})
    meta = write_sidecar()
    check("[3] tip switched off: state None", tip_smoothing_state(C, BSIG), None)
    check("[3] tip switched off: Run all current", run_all()["kind"], "")
    model3d.set_model3d_options(C, {"signature": BSIG, "extension_rig": {}})

    # [4] the version bump makes it due
    write_sidecar(tip_smoothing=tip_smoothing_record({"T": TIP_METRICS}, ["T"], "2026-11-14T00:12:00+00:00"))
    check("[4] current version: current", tip_smoothing_state(C, BSIG)["due"], False)
    with patch.object(extension_tip, "TIP_SMOOTHING_VERSION", V + 1):
        state = tip_smoothing_state(C, BSIG)
        check("[4] next version: due", (state["due"], state["light"], state["summary"]),
              (True, "warn", "Not applied to this model yet — rebuilds the extension bones (local, no hub job)"))
        check("[4] next version: Run all", run_all()["kind"], "tip_smoothing")
finally:
    for p in patches:
        p.stop()

print()
print("ALL OK" if not FAILS else f"{len(FAILS)} FAILED: " + ", ".join(FAILS))
sys.exit(1 if FAILS else 0)
