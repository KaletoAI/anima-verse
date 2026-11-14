#!/usr/bin/env python3
"""A tip part that is off leaves a neutral surface — the mesh levelled, the texture untouched (Rulings A44, A53).

A ``pair_tip`` group whose declaration says ``when_off: neutralise`` and which a base model has switched off is
passed to the extension script as ``neutralise``: the skin where the source group located the part is levelled onto
the surface around it (``extension_bones.neutralise_mesh`` / ``level_surface``). Since Ruling A53 nothing is painted:
``extension_tip.paint_disc_masks`` leaves the texture alone. The base body tab's "Tip smoothing (local)" row records
it (``mode: "neutralised"``); switching the part on or off makes the row due.

Usage:
    ./.venv/bin/python scripts/smoke_tip_neutralise.py            # both parts
    ./.venv/bin/python scripts/smoke_tip_neutralise.py --no-blender

Part A runs against a THROWAWAY storage directory (``paths.init(<tmp>)`` before any world module is imported) — no
world, no server; Blender (``refine.apply_script``) is a recorder. Same harness as ``smoke_tip_smoothing_step.py``:
character "demo", stored base ``base1.glb``, declarations P (``pair_protrusion``) and T (``pair_tip``, depends on P,
``when_off: neutralise``). The base colour reader and writer are recorders too: nothing may be written.

[1] T off, ``when_off: neutralise`` → the row shows T in mode "neutralised", due (no record), Run all kind
    "tip_smoothing". ``_extension_rig_once`` hands T to Blender as ``neutralise`` (not as a group); the record of T is
    {mode neutralised, applied True, reason "Smoothed — part is off", height_mm [[3.982, .05] x2], bump_mm
    [[4.0, 0.0] x2], max_shift_mm 4.1, moved 900, radius_mm 12.0} — no colour fields; the base colour is never
    written; the light is "ok" with that reason; not due; a second build is a no-op.
[2] T switched on again → due (its entry is "neutralised", it now wants "smoothed"); the build hands Blender no
    ``neutralise`` group and T as a group.
[3] ``when_off: nothing`` (the default) and T off → no row (as before A44); the build hands Blender no ``neutralise``.
[4] Nothing located (the script answers T ``not_found`` with its reason) → applied False, that reason, light "off".
[5] Manifest: ``when_off`` defaults to "nothing", accepts "neutralise" on ``pair_tip``, refuses it on another op and
    refuses an unknown value.

Part B (Blender) uses the pair-tip smoke's fixture: two spherical caps of radius .106 (centre y = -.044) over the
plane y = -.1, colour markers of radius 9 mm at (+-.15, 1.41) on skin (.72, .52, .40). A cosine bump of 4 mm height
and 6 mm radius is pushed out at each placed tip (``smoke_extension_rig_pair_tip`` derives its height along the cap
normal: .004 * cos(asin(.01 / .106)) = 3.982 mm ± .05). The marker's equal-area radius R ≈ 9 mm → the full region is
max(1.2 R, 12 mm, stub .0045 + wall .0015 + margin .003 = 9 mm) = 12 mm, the blend 0.8 x 12 = 9.6 mm, so nothing
beyond 21.6 mm moves; the levelled surface is a
quadratic fitted on the cap at 21.6-30 mm, whose error against the sphere inside is the r^4 term
(.0216^2 * .03^2) / (8 * .106^3) = .044 mm plus the tilt — the pair-tip smoke's .3 mm fit budget covers it.
[6] Part off + neutralise → status "neutralised"; height before 3.982 ± .05 mm, after < .3 mm; every vertex within
    12 mm (in x, z) of a tip lies within .3 mm of the sphere; every original grid vertex further than 21.7 mm from
    both tips is where the fixture put it (1e-6); the tip lies within 1.35 mm of the marker centre; the metrics
    carry no paint mask. With an offset of 20 mm up and 20 mm out (Ruling A53: an offset moves only a part that is
    on) the very same vertices move to the very same places (1e-9).
[7] Part on (no ``neutralise`` group) → no vertex moves, no T metrics.
[8] No footprint (T depends on a group that is not there) → T "not_found" with "Nothing located where the part would
    sit — nothing changed", no vertex moves.

No expected value is recorded from a run. Fails on f466b5bf: ImportError — ``extension_tip`` has no
``smoothing_ids``; the A53 rule (no paint, levelled at the source whatever the offset) fails on
33d69c57569c82987d949bc3abc46bf039830f67: [1] reason / painted, [6] offset (scripts/smoke_tip_off_mesh_only.py).
"""
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_tmp = Path(tempfile.mkdtemp(prefix="smoke_tip_neutralise_"))
from app.core import paths  # noqa: E402
paths.init(str(_tmp))
from app.core import db  # noqa: E402
db.init_schema()


from app.blender import refine  # noqa: E402
from app.core import base_body, extension_rig, extension_tip, figure_build, model3d  # noqa: E402
from app.core.extension_tip import (NEUTRALISED_REASON, smoothing_ids, tip_smoothing_due,  # noqa: E402
                                    tip_smoothing_state, tip_smoothing_summary)
from app.core.keyed_lock import keyed_lock  # noqa: E402
from app.models.character import get_character_dir, save_character_profile  # noqa: E402
from app.plugins.registry import RigSpec  # noqa: E402

FAILS = []


def check(label, got, want=True):
    ok = got == want
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + ("" if ok else f"  — got {got!r}, want {want!r}"))
    if not ok:
        FAILS.append(label)


# --- Part A ------------------------------------------------------------------------------------------------------

C, BSIG = "demo", "base1"
P = {"id": "P", "op": "pair_protrusion", "depends_on": None, "chains": [], "params": {}, "label": "Source"}
T = {"id": "T", "op": "pair_tip", "depends_on": "P", "chains": [], "params": {}, "label": "Tips",
     "when_off": "neutralise"}
DECLARED = {"groups": [P, T]}

NEUTRAL_METRICS = {"status": "neutralised", "mode": "neutralised", "reason": "",
                   "placement": [{"tip": [0.05, -0.1, 1.3], "height_before_mm": 3.982, "height_after_mm": 0.05,
                                  "bump_mm": [4.0, 0.0]},
                                 {"tip": [-0.05, -0.1, 1.3], "height_before_mm": 3.982, "height_after_mm": 0.05,
                                  "bump_mm": [4.0, 0.0]}],
                   "source_smooth": {"radius_m": 0.012, "blend_m": 0.0096, "iterations": None, "moved": 900,
                                     "max_shift_mm": 4.1},
                   "tip_normals": {"region_mm": 40.0, "vertices": [100, 900], "inverted": [2, 0], "off_60": [5, 0]}}
SMOOTH = {"radius_m": 0.0187333, "blend_m": 0.0026762, "iterations": 292, "moved": 2522, "max_shift_mm": 4.546}
TIP_METRICS = {"placement": [{"tip_source": "stub", "source_smooth": SMOOTH}],
               "tip_normals": {"region_mm": 40.0, "vertices": [524, 13297], "inverted": [3, 0], "off_60": [7, 0]}}
BLENDER = {"metrics": {"P": {"placement": []}, "T": NEUTRAL_METRICS}, "calls": [], "painted": [], "read": 0}


def fake_apply_script(path, script, args, **_kw):
    BLENDER["calls"].append(json.loads(json.dumps(args)))
    return {"applied": True, "data": {"status": "applied", "metrics": json.loads(json.dumps(BLENDER["metrics"]))}}


def fake_replace(glb, image, mime):
    BLENDER["painted"].append(image)
    return glb


def fake_read(glb):
    BLENDER["read"] += 1
    return b"png", "image/png"


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


def write_sidecar(**extra):
    from app.models.character import get_character_profile
    profile = get_character_profile(C) or {}
    declarations = extension_rig.rig_groups_for(C, profile=profile)
    meta = {"base": True, "rig": "mixamo", "blender": {"steps": ["limb_weights"]}}
    fingerprint = extension_rig.extension_rig_fingerprint(
        declarations, extension_rig.effective_extension_overrides(profile, BSIG, meta, declarations))
    meta.update({"extension_rig": {"attempted": True, "status": "applied", "fingerprint": fingerprint,
                                   "groups": [g["id"] for g in declarations],
                                   "group_ops": {g["id"]: g["op"] for g in declarations}}}, **extra)
    model.with_suffix(".json").write_text(json.dumps(meta))
    return meta


def switch_t(enabled):
    model3d.set_model3d_options(C, {"signature": BSIG, "extension_rig": {} if enabled else {"T": {"enabled": False}}})


def part_a():
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
        patch.object(base_body, "base_color_image", fake_read),
        patch.object(base_body, "replace_base_color", fake_replace),
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
        # [1] T off, when_off neutralise
        switch_t(False)
        write_sidecar()
        state = tip_smoothing_state(C, BSIG)
        check("[1] row: T neutralised", (state or {}).get("groups"), [{"id": "T", "label": "Tips", "mode": "neutralised"}])
        check("[1] due without a record", (state or {}).get("due"), True)
        check("[1] Run all kind", figure_build.base_run_all(C)["kind"], "tip_smoothing")
        meta = model3d._read_sidecar(model)
        model3d._extension_rig_once(C, model, meta, force=False)
        call = BLENDER["calls"][-1]
        check("[1] Blender: T as neutralise, not as a group",
              ([g["id"] for g in call["groups"]], [g["id"] for g in call.get("neutralise") or []]), (["P"], ["T"]))
        entry = (meta.get("tip_smoothing") or {}).get("groups", {}).get("T") or {}
        check("[1] record mode / applied / reason", (entry.get("mode"), entry.get("applied"), entry.get("reason")),
              ("neutralised", True, NEUTRALISED_REASON))
        check("[1] record numbers", (entry.get("height_mm"), entry.get("bump_mm"),
                                     entry.get("max_shift_mm"), entry.get("moved"), entry.get("radius_mm")),
              ([[3.982, 0.05], [3.982, 0.05]], [[4.0, 0.0], [4.0, 0.0]], 4.1, 900, 12.0))
        check("[1] no colour fields", [k for k in ("delta_e", "colours", "painted") if k in entry], [])
        check("[1] the texture is neither read nor written", (BLENDER["read"], BLENDER["painted"]), (0, []))
        check("[1] no paint summary in the metrics", "neutral" in meta["extension_rig"]["metrics"]["T"], False)
        model3d._publish_sidecar(model, meta)
        state = tip_smoothing_state(C, BSIG)
        check("[1] light and line", (state["due"], state["light"], state["summary"]), (False, "ok", NEUTRALISED_REASON))
        calls = len(BLENDER["calls"])
        again = model3d._extension_rig_once(C, model, model3d._read_sidecar(model), force=False)
        check("[1] second build is a no-op", (bool(again.get("noop")), len(BLENDER["calls"])), (True, calls))

        # [2] switched on again → due, built as a part
        switch_t(True)
        record = model3d._read_sidecar(model).get("tip_smoothing")
        check("[2] on again: due", tip_smoothing_due(record, ["T"], []), True)
        check("[2] on again: Run all kind", figure_build.base_run_all(C)["kind"], "tip_smoothing")
        BLENDER["metrics"] = {"P": {"placement": []}, "T": TIP_METRICS}
        meta = model3d._read_sidecar(model)
        model3d._extension_rig_once(C, model, meta, force=False)
        call = BLENDER["calls"][-1]
        check("[2] Blender: T as a group, nothing neutralised",
              ([g["id"] for g in call["groups"]], call.get("neutralise")), (["P", "T"], []))
        check("[2] record mode smoothed", (meta["tip_smoothing"]["groups"]["T"].get("mode"),
                                           tip_smoothing_due(meta["tip_smoothing"], ["T"], [])), (None, False))

        # [3] when_off nothing → no row
        DECLARED["groups"] = [P, {**T, "when_off": "nothing"}]
        switch_t(False)
        write_sidecar()
        check("[3] when_off nothing, off: no row", tip_smoothing_state(C, BSIG), None)
        meta = model3d._read_sidecar(model)
        meta["extension_rig"]["fingerprint"] = "older"
        model3d._extension_rig_once(C, model, meta, force=False)
        check("[3] Blender: nothing neutralised", BLENDER["calls"][-1].get("neutralise"), [])
        DECLARED["groups"] = [P, T]

        # [4] nothing located
        located = extension_tip.tip_neutral_group(
            {"status": "not_found", "mode": "neutralised",
             "reason": "Nothing located where the part would sit — nothing changed"})
        check("[4] nothing located", (located["applied"], located["reason"]),
              (False, "Nothing located where the part would sit — nothing changed"))
        check("[4] light off", tip_smoothing_summary({"version": 1, "status": "built", "groups": {"T": located}},
                                                     False)[0], "off")
        check("[4] smoothing_ids", smoothing_ids([{**T, "enabled": False}, {**T, "id": "U", "enabled": True},
                                                  {**T, "id": "V", "enabled": False, "when_off": "nothing"}]),
              (["U"], ["T"]))
    finally:
        for p in patches:
            p.stop()

    # [5] manifest
    raw = {"id": "T", "op": "pair_tip", "chains": [[{"bone": "a:TipLeft", "parent": "a:Left"}],
                                                   [{"bone": "a:TipRight", "parent": "a:Right"}]]}
    check("[5] default nothing", RigSpec.parse(dict(raw)).when_off, "nothing")
    check("[5] neutralise on pair_tip", RigSpec.parse(dict(raw, when_off="neutralise")).when_off, "neutralise")
    for label, bad in (("other op", dict(raw, op="pair_protrusion", when_off="neutralise")),
                       ("unknown value", dict(raw, when_off="flatten"))):
        try:
            RigSpec.parse(bad)
            check(f"[5] refuses {label}", False)
        except ValueError:
            check(f"[5] refuses {label}", True)


# --- Part B (Blender) --------------------------------------------------------------------------------------------

NEUTRAL_PROBE = r'''
import numpy as _np
tp={}
tp_extra=dict(subdivide_radii=[2.4,1.8,1.],normal_radius=2.,fill_radius=1.7,fill_ring=.7,fill_blend=.3,
 fill_depth=.03,fill_tolerance=.012,fill_rms_max=.0015,tip_diameter=.009,tip_length=.005,tip_round=.6,
 tip_wall=.0015,tip_band=.009,tip_subdivide=.009,weight_depth=.015)
case=job['params']['case']
fixture('B')
obj=bpy.data.objects['Surface']; arm=bpy.data.objects['Rig']
obj.vertex_groups['Child'].remove(list(range(len(obj.data.vertices))))
bpy.context.view_layer.objects.active=arm
bpy.ops.object.mode_set(mode='EDIT')
for name,head in [('Positive',(.3,0,1)),('Negative',(-.3,0,1)),('Front',(0,-.1,1))]:
 bone=arm.data.edit_bones.new(name); bone.head=head; bone.tail=Vector(head)+Vector((0,0,.05))
bpy.ops.object.mode_set(mode='OBJECT')
validated.update(lateral_positive_bone='Positive',lateral_negative_bone='Negative',front_to_bone='Front')
group.update(id='Pair',op='pair_protrusion',params=validated)
tp={k:validated[k] for k in scope['PARAMETERS']['pair_tip'] if k in validated}
tp.update(tp_extra)
tip=dict(id='Tip',op='pair_tip',depends_on='Pair',params=tp,enabled=False,when_off='neutralise',
 chains=[[dict(bone='TipLeft',parent='ExampleLeft')],[dict(bone='TipRight',parent='ExampleRight')]])
scope['parameters'](tip)
bones={scope['bone_key'](b.name):b for b in arm.data.bones}
co,edges,owners,normals,faces=scope['mesh_arrays']([obj])
placement=scope['pair_plan'](group,validated,co,bones,scope['pair_surface']([obj]),owners)[2]['placement']
tips=[Vector(row['tip']) for row in placement]
for vertex in obj.data.vertices:
 for t in tips:
  r=math.hypot(vertex.co.x-t.x,vertex.co.z-t.z)
  if r<.006:
   vertex.co.y-=.004*(1+math.cos(math.pi*r/.006))/2
obj.data.update()
scope['_common'].reset_scene=lambda:None
scope['_common'].import_model=lambda path:None
grid=241*241
before=[v.co.copy() for v in obj.data.vertices]
shifted=dict(tip,tip_override={'offsets':[{'up':20,'out':20},{'up':20,'out':20}],'mirror':True})
neutral={'neutral':[tip],'offset':[shifted],'on':[],'missing':[dict(tip,depends_on='Missing')]}[case]
result,outputs=scope['extension_bones']({'params':{'groups':[group],'neutralise':neutral},'inputs':{'model':'fixture'},
                                        'out_dir':str(Path(job['result']).parent)})
assert result['status']=='applied',result
metrics=result['metrics']
sphere=lambda x,z,sign:-.044-math.sqrt(.106**2-(x-sign*.15)**2-(z-1.4)**2)
out={}
if case in ('neutral','offset'):
 m=metrics['Tip']
 assert m['status']=='neutralised',m
 out['heights']=[(row['height_before_mm'],row['height_after_mm']) for row in m['placement']]
 worst,far=0.,0.
 for v in obj.data.vertices:
  for sign,t in zip((1,-1),tips):
   if math.hypot(v.co.x-t.x,v.co.z-t.z)<=.012:
    worst=max(worst,abs(v.co.y-sphere(v.co.x,v.co.z,sign)))
  if v.index<grid and all(math.hypot(v.co.x-t.x,v.co.z-t.z)>.0217 for t in tips):
   far=max(far,(v.co-before[v.index]).length)
 out['worst_mm']=worst*1000; out['far_m']=far
 out['offsets_mm']=[math.hypot(t.x-sign*.15,t.z-1.41)*1000 for sign,t in zip((1,-1),tips)]
 out['mask']='neutral_mask' in m
 out['positions']=[list(v.co) for v in obj.data.vertices]
else:
 out['moved']=max((v.co-b).length for v,b in zip(obj.data.vertices,before)) if len(before)==len(obj.data.vertices) else 'count changed'
 out['tip']=metrics.get('Tip')
Path(job['result']).write_text(json.dumps({'ok':True,'data':out,'outputs':{}}))
'''


def part_b():
    from app.blender import runner
    if not runner.status()["executable"]:
        print("SKIP  part B — no Blender executable")
        return
    sys.path.insert(0, str(ROOT / "scripts"))
    from smoke_extension_rig_pair_wall import PROBE as WALL_PROBE
    prefix = WALL_PROBE[:WALL_PROBE.index("for kind in ('A','B','C','D','E'):")]
    prefix = prefix.replace("r2=(dx/.06)**2+(dz/.09)**2\n    y=-.1-.05*max(0.,1-r2)**.5",
                            "q=.106**2-dx*dx-dz*dz\n    y=min(-.1,-.044-math.sqrt(q)) if q>=0 else -.1")
    prefix = prefix.replace("assert abs(s['reach'][0]-s['reach'][2])>.01, s", "assert s['marker_area']>0, s")
    with tempfile.TemporaryDirectory(prefix="tip-neutralise-") as tmp:
        root = Path(tmp)
        (root / "probe.py").write_text(prefix + NEUTRAL_PROBE)
        source = runner.SCRIPTS_DIR / "extension_bones.py"
        results = {}
        with patch.object(runner, "SCRIPTS_DIR", root):
            for case in ("neutral", "offset", "on", "missing"):
                result = runner.run("probe", params={"source": str(source), "case": case}, out_dir=root / case,
                                    timeout_s=300)
                if not result.get("ok"):
                    check(f"[B] {case} ran", result.get("error"), None)
                    return
                results[case] = result["data"]
    data = results["neutral"]
    print("      heights (mm)", data["heights"], "worst", round(data["worst_mm"], 3), "mm, tip offsets (mm)",
          [round(v, 2) for v in data["offsets_mm"]])
    check("[6] height before 3.982 ± .05 mm", all(abs(b - 3.982) < .05 for b, _ in data["heights"]), True)
    check("[6] height after < .3 mm", all(a < .3 for _, a in data["heights"]), True)
    check("[6] within 12 mm on the sphere (.3 mm)", data["worst_mm"] < .3, True)
    check("[6] beyond 21.7 mm untouched", data["far_m"] < 1e-6, True)
    check("[6] tip within 1.35 mm of the marker centre", all(v <= 1.35 for v in data["offsets_mm"]), True)
    check("[6] no paint mask", data["mask"], False)
    shifted = results["offset"]["positions"]
    check("[6] an offset changes nothing for a part that is off",
          len(shifted) == len(data["positions"]) and max(abs(a - b) for p, q in zip(shifted, data["positions"])
                                                         for a, b in zip(p, q)) < 1e-9, True)
    check("[7] part on: nothing moves, no tip metrics", (results["on"]["moved"] == 0.0, results["on"]["tip"]),
          (True, None))
    missing = results["missing"]["tip"] or {}
    check("[8] no footprint: not found, reason, nothing moves",
          (missing.get("status"), missing.get("reason"), results["missing"]["moved"] == 0.0),
          ("not_found", "Nothing located where the part would sit — nothing changed", True))


part_a()
if "--no-blender" not in sys.argv:
    part_b()
print()
print("ALL OK" if not FAILS else f"{len(FAILS)} FAILED: " + ", ".join(FAILS))
sys.exit(1 if FAILS else 0)
