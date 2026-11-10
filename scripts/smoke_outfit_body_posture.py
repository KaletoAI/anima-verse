#!/usr/bin/env python3
"""Numeric check of the outfit body's POSTURE MATCH to its base body —
``app/core/outfit_body_posture.py``, ``app/blender/scripts/posture_match.py``,
``refine.posture_match`` / ``posture_match_allowance``,
``model3d._auto_posture_match`` / ``match_outfit_body_posture`` and the
step line of ``model_overview.outfit_body_steps``.

Usage:
    ./.venv/bin/python scripts/smoke_outfit_body_posture.py

Needs Blender (auto-discovered, or image_generation.blender_executable), no
server, no world DB, no hub. Works in a temp directory only (``paths.init``
on it before any world module is imported). Results are verified by
RE-READING the produced GLBs (node tree and vertices), not by trusting the
script's report.

THE FIXTURE, AND THE EXPECTATIONS DERIVED BY HAND
=================================================
A vertical column (radius 0.08 m, z 0..1.70, a ring every 2 cm; Blender
world, Z up, the figure faces -Y) skinned rigidly to a Mixamo chain Hips
0.95, Spine 1.05, Spine1 1.15, Spine2 1.27, Neck 1.43, Head 1.52..1.70. Its
rest hips->head line is d = (0, 0, 0.57): lean 0 forward, 0 sideways.

"The rigger's attitude" is a RIGID turn of armature and skin together about
the origin, applied as rest (``transform_apply``): Rx(θ) about +X maps +Z to
(0, -sin θ, cos θ), and forward is -Y, so forward = atan2(sin θ, cos θ) = θ
exactly. Ry(φ) after Rx(θ) maps +Z to (cos θ sin φ, -sin θ, cos θ cos φ):
sideways = atan2(cos θ sin φ, cos θ cos φ) = φ exactly, forward =
atan(tan θ / cos φ).

    base.glb   Rx(5°)            -> forward 5.0000, sideways 0
    body.glb   Rx(14°)           -> forward 14.0000, sideways 0
    side.glb   Ry(3°)·Rx(5°)     -> forward atan(tan5°/cos3°) = 5.0068, sideways 3.0000

[1] THE MEASURE. ``rest_lean`` (glTF node tree, +Y up, forward +Z) reads
    those three to ±0.01°; ``lean_delta(body, base)`` = 9.0 ± 0.01.
[2] THE TURN. ``refine.posture_match(body, 5, 0)``: the output's lean is
    5.0 ± 0.5 forward and 0 ± 0.5 sideways (a rigid turn is exact: checked
    ±0.01); ``applied_deg`` = 9.0 ± 0.05 (the angle between the two lines);
    lowest vertex z = 0 ± 1e-4 and the box centred in x and in the forward
    axis ± 1e-4 (re-grounded as normalize leaves a model); every joint's
    LOCAL rotation is unchanged (< 0.01°) except the root bone Hips, turned
    by 9.0 ± 0.05.
[3] THE FRAME GATE. That output turned Hips by 9° > the 5° tolerance:
    ``rig_frames_preserved`` REJECTS it without an allowance and ACCEPTS it
    with ``posture_match_allowance(data)`` = {hips: 9.0} — the gate inside
    ``apply_script`` therefore let it through ([2] applied).
[4] NOTHING TWICE (the "manual tilt" question). The target is the BASE's
    own lean, never base + body: the matched output run again against the
    same target turns < 0.05° and writes nothing ("nothing to do"); the base
    itself matched against its own lean stays at 5.0 (not 10.0). The viewer
    Tilt sliders are a preview rotation only (never stored), so no stored
    tilt can enter the target. The side fixture matched to (5, 0) ends at
    forward 5.0 ± 0.5, sideways 0 ± 0.5 (both components in one turn).
[5] ``model3d._auto_posture_match`` on a body sidecar whose parent record
    names base signature B (model3d/<B>.glb = base.glb) in a temp world:
    record version 1, status "applied", base_signature B, base_sha256 =
    sha256(base.glb), target 5.0, before 14.0, after 5.0 ± 0.5, applied 9.0;
    ``stale_reason`` "" then; "version" with version 0; "failed" with an
    error; "base" once model3d/<B>.glb holds other bytes; "missing" without a
    record; "" for a sidecar that is no outfit body. Without the base model
    file: status "failed", error names the base, the body bytes unchanged.
    The validator is stubbed to "parses as GLB" (the fixture has 6 joints,
    not the 52 of a delivery); the frame gate stays real.
[6] ``match_outfit_body_posture`` on a STORED body (signature ob…):
    a) no prerig: matched in place — the published body's lean 5.0 ± 0.5,
       its sha changed, the sidecar record status "applied", collision
       refresh called once; a second call is a no-op (``noop`` True, sha
       unchanged).
    b) prerig + applied extension bones: the prerig source is matched (lean
       5.0 ± 0.5) and the body is REBUILT from it (``rebuild_extension_rig``
       force=True, stubbed as the real publish does: prerig bytes + prerig
       ``blender`` block onto the body) — the body's lean 5.0 ± 0.5 and its
       record names the base sha; the in-place path is not taken.
[7] THE STEP LINE. ``outfit_body_steps`` of [6a]'s sidecar holds the row
    ``posture_match`` "Posture matched to base", status done, detail
    "forward +14.0° → +5.0° (base +5.0°) · sideways +0.0° → +0.0° (base
    +0.0°) · turned 9.0°" (a sideways -0.0° read as +0.0°), numbers forward_before_deg 14.0 /
    forward_after_deg 5.0 / turned_deg 9.0; no record -> status "missing";
    an error -> "failed"; within tolerance -> "skipped".
"""
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TMP = Path(tempfile.mkdtemp(prefix="smoke-obody-posture-"))
os.environ["ANIMATION_CLIPS_DIR"] = str(TMP / "clips")
from app.core import paths  # noqa: E402

paths.init(str(TMP / "world"))
from app.core import db  # noqa: E402

db.init_schema()  # an empty world: profile reads answer "no character" instead of a missing table

from app.blender import refine, runner  # noqa: E402

FIXTURE = r'''
import bpy, math, sys
from mathutils import Matrix
out = sys.argv[sys.argv.index("--") + 1]
SEGMENTS = [("mixamorig:Hips", 0.95, 1.05), ("mixamorig:Spine", 1.05, 1.15),
            ("mixamorig:Spine1", 1.15, 1.27), ("mixamorig:Spine2", 1.27, 1.43),
            ("mixamorig:Neck", 1.43, 1.52), ("mixamorig:Head", 1.52, 1.70)]

def figure(turn):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    verts, faces = [], []
    for r in range(86):
        for k in range(16):
            a = 2 * math.pi * k / 16
            verts.append((0.08 * math.cos(a), 0.08 * math.sin(a), 0.02 * r))
    for r in range(85):
        for k in range(16):
            a, b = r * 16 + k, r * 16 + (k + 1) % 16
            faces.append((a, b, b + 16, a + 16))
    me = bpy.data.meshes.new("column"); me.from_pydata(verts, [], faces)
    obj = bpy.data.objects.new("column", me); bpy.context.scene.collection.objects.link(obj)
    arm = bpy.data.armatures.new("rig"); armo = bpy.data.objects.new("Armature", arm)
    bpy.context.scene.collection.objects.link(armo)
    bpy.context.view_layer.objects.active = armo
    bpy.ops.object.mode_set(mode="EDIT")
    parent = None
    for name, z0, z1 in SEGMENTS:
        b = arm.edit_bones.new(name); b.head = (0, 0, z0); b.tail = (0, 0, z1)
        if parent is not None:
            b.parent = parent
        parent = b
    bpy.ops.object.mode_set(mode="OBJECT")
    for name, z0, z1 in SEGMENTS:
        vg = obj.vertex_groups.new(name=name)
        vg.add([v.index for v in obj.data.vertices if (z0 <= v.co.z < z1)
                or (name.endswith("Hips") and v.co.z < z0) or (name.endswith("Head") and v.co.z >= z1)], 1.0, "REPLACE")
    obj.modifiers.new("Armature", "ARMATURE").object = armo
    obj.parent = armo
    armo.matrix_world = turn @ armo.matrix_world
    bpy.context.view_layer.update()
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

def export(path):
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.export_scene.gltf(filepath=path, export_format="GLB")

rx = lambda d: Matrix.Rotation(math.radians(d), 4, "X")
ry = lambda d: Matrix.Rotation(math.radians(d), 4, "Y")
figure(rx(5)); export(out + "/base.glb")
figure(rx(14)); export(out + "/body.glb")
figure(ry(3) @ rx(5)); export(out + "/side.glb")
print("FIXTURES_OK")
'''

failures = []


def check(label, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'} {label}{(' — ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


def near(a, b, tol):
    return a is not None and b is not None and abs(float(a) - float(b)) <= tol


def node_rotations(path):
    from app.core.model_validate import parse_glb
    nodes = parse_glb(Path(path).read_bytes())["gltf"]["nodes"]
    return {n.get("name"): n.get("rotation") or [0, 0, 0, 1] for n in nodes if "mixamorig" in str(n.get("name"))}


def quat_angle(a, b):
    dot = abs(sum(x * y for x, y in zip(a, b)))
    return math.degrees(2 * math.acos(min(1.0, dot)))


def bounds(path):
    """(min, max) of all POSITION accessors' declared bounds in world (the fixture has no node transforms on
    the mesh after transform_apply, so accessor min/max are world)."""
    from app.core.model_validate import glb_bounds
    return glb_bounds(Path(path).read_bytes())


def main():
    st = runner.status()
    if not st.get("executable"):
        print("SKIP — no Blender:", st.get("error"))
        return 0
    work = TMP / "fixtures"
    work.mkdir()
    script = TMP / "fixture.py"
    script.write_text(FIXTURE, encoding="utf-8")
    proc = subprocess.run([st["executable"], "-b", "--factory-startup", "--python-exit-code", "1",
                           "--python", str(script), "--", str(work)], capture_output=True, text=True, timeout=300)
    if "FIXTURES_OK" not in proc.stdout:
        print(proc.stdout[-2000:], proc.stderr[-2000:])
        print("FAIL — fixtures not built")
        return 1

    from app.core import outfit_body_posture as posture
    from app.core.model_validate import rig_frames_preserved

    print("[1] the measure")
    base = posture.rest_lean((work / "base.glb").read_bytes())
    body = posture.rest_lean((work / "body.glb").read_bytes())
    side = posture.rest_lean((work / "side.glb").read_bytes())
    check("base forward 5.0", near(base["forward_deg"], 5.0, 0.01), str(base))
    check("base sideways 0", near(base["side_deg"], 0.0, 0.01), str(base))
    check("body forward 14.0", near(body["forward_deg"], 14.0, 0.01), str(body))
    expected_side_forward = math.degrees(math.atan(math.tan(math.radians(5)) / math.cos(math.radians(3))))
    check("side forward atan(tan5/cos3) = 5.0068", near(side["forward_deg"], expected_side_forward, 0.01)
          and near(expected_side_forward, 5.0068, 0.0001), str(side))
    check("side sideways 3.0", near(side["side_deg"], 3.0, 0.01), str(side))
    check("lean_delta(body, base) = 9.0", near(posture.lean_delta(body, base), 9.0, 0.01))

    print("[2] the turn")
    matched = TMP / "matched.glb"
    shutil.copy2(work / "body.glb", matched)
    res = refine.posture_match(matched, 5.0, 0.0)
    data = res.get("data") or {}
    check("applied", bool(res.get("applied")), res.get("error", ""))
    after = posture.rest_lean(matched.read_bytes())
    check("after forward 5.0 ±0.5 (exact ±0.01)", near(after["forward_deg"], 5.0, 0.01), str(after))
    check("after sideways 0 ±0.5 (exact ±0.01)", near(after["side_deg"], 0.0, 0.01), str(after))
    check("applied_deg 9.0", near(data.get("applied_deg"), 9.0, 0.05), str(data.get("applied_deg")))
    lo, hi = bounds(matched)
    check("lowest point z(up) = 0", near(lo[1], 0.0, 1e-4), str(lo))
    check("box centred in x and forward", near((lo[0] + hi[0]) / 2, 0.0, 1e-4) and near((lo[2] + hi[2]) / 2, 0.0, 1e-4),
          f"{lo} {hi}")
    rb, ra = node_rotations(work / "body.glb"), node_rotations(matched)
    others = {n: quat_angle(rb[n], ra[n]) for n in rb if not n.endswith("Hips")}
    check("every joint but Hips keeps its local frame (<0.01°)", max(others.values()) < 0.01, str(others))
    check("Hips frame turned 9.0", near(quat_angle(rb["mixamorig:Hips"], ra["mixamorig:Hips"]), 9.0, 0.05))

    print("[3] the frame gate")
    before_bytes, after_bytes = (work / "body.glb").read_bytes(), matched.read_bytes()
    check("rejected without allowance", not rig_frames_preserved(before_bytes, after_bytes)["ok"])
    allowance = refine.posture_match_allowance(data)
    check("allowance = {hips: 9.0}", list(allowance) == ["hips"] and near(allowance["hips"], 9.0, 0.05), str(allowance))
    check("accepted with allowance", rig_frames_preserved(before_bytes, after_bytes, allowed_deg=allowance)["ok"])
    check("no allowance for a missing angle", refine.posture_match_allowance({"root": "mixamorig:Hips"}) == {})

    print("[4] nothing twice")
    again_sha = hashlib.sha256(matched.read_bytes()).hexdigest()
    res2 = refine.posture_match(matched, 5.0, 0.0)
    check("matched body again: nothing to do", not res2.get("applied") and res2.get("error") == "nothing to do",
          res2.get("error", ""))
    check("... turn < 0.05°", float((res2.get("data") or {}).get("applied_deg", 1)) < 0.05)
    check("... bytes unchanged", hashlib.sha256(matched.read_bytes()).hexdigest() == again_sha)
    base_copy = TMP / "base_copy.glb"
    shutil.copy2(work / "base.glb", base_copy)
    res3 = refine.posture_match(base_copy, base["forward_deg"], base["side_deg"])
    check("base against its own lean: not applied", not res3.get("applied"))
    check("... stays 5.0 (not 10.0)", near(posture.rest_lean(base_copy.read_bytes())["forward_deg"], 5.0, 0.01))
    side_copy = TMP / "side_copy.glb"
    shutil.copy2(work / "side.glb", side_copy)
    refine.posture_match(side_copy, 5.0, 0.0)
    side_after = posture.rest_lean(side_copy.read_bytes())
    check("side fixture -> forward 5.0, sideways 0", near(side_after["forward_deg"], 5.0, 0.5)
          and near(side_after["side_deg"], 0.0, 0.5), str(side_after))

    print("[5] _auto_posture_match + stale_reason")
    from app.core import model3d
    from app.models.character import get_character_dir
    model3d._validator_for = lambda rig, name: (lambda blob: {"ok": blob[:4] == b"glTF", "errors": []})
    bsig, bid = "base1234abcd", "ob12345678"
    char = "Demo"
    mdir = get_character_dir(char, create=True) / "model3d"
    mdir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(work / "base.glb", mdir / f"{bsig}.glb")
    base_sha = hashlib.sha256((mdir / f"{bsig}.glb").read_bytes()).hexdigest()
    parent = {"body_id": bid, "mode": "mesh", "version": 1, "base_signature": bsig}
    loose = TMP / "loose.glb"
    shutil.copy2(work / "body.glb", loose)
    meta = {"rig": "mixamo", "outfit_body": parent}
    record = model3d._auto_posture_match(char, loose, meta)
    check("record status applied", record.get("status") == "applied", str(record)[:300])
    check("record version 1, base", record.get("version") == 1 and record.get("base_signature") == bsig
          and record.get("base_sha256") == base_sha)
    check("record target 5.0 / before 14.0 / after 5.0 / applied 9.0",
          near(record["target"]["forward_deg"], 5.0, 0.01) and near(record["before"]["forward_deg"], 14.0, 0.01)
          and near(record["after"]["forward_deg"], 5.0, 0.5) and near(record["applied_deg"], 9.0, 0.05))
    check("record lands in meta.blender.posture_match", meta["blender"]["posture_match"] is record)
    check("stale_reason current -> ''", posture.stale_reason(char, meta) == "")
    check("stale_reason version 0 -> version",
          posture.stale_reason(char, {**meta, "blender": {"posture_match": {**record, "version": 0}}}) == "version")
    check("stale_reason error -> failed",
          posture.stale_reason(char, {**meta, "blender": {"posture_match": {**record, "error": "x"}}}) == "failed")
    check("stale_reason no record -> missing", posture.stale_reason(char, {**meta, "blender": {}}) == "missing")
    check("stale_reason not an outfit body -> ''", posture.stale_reason(char, {"rig": "mixamo"}) == "")
    shutil.copy2(work / "side.glb", mdir / f"{bsig}.glb")
    check("stale_reason other base bytes -> base", posture.stale_reason(char, meta) == "base")
    shutil.copy2(work / "base.glb", mdir / f"{bsig}.glb")
    orphan = TMP / "orphan.glb"
    shutil.copy2(work / "body.glb", orphan)
    orphan_sha = hashlib.sha256(orphan.read_bytes()).hexdigest()
    bad = model3d._auto_posture_match(char, orphan, {"rig": "mixamo",
                                                     "outfit_body": {**parent, "base_signature": "base00000000"}})
    check("no base model: failed, names the base", bad.get("status") == "failed" and "base00000000" in bad.get("error", ""),
          str(bad.get("error")))
    check("... body bytes unchanged", hashlib.sha256(orphan.read_bytes()).hexdigest() == orphan_sha)

    print("[6] match_outfit_body_posture on a stored body")
    from app.core import collision
    calls = []
    collision.refresh = lambda name, path, meta: calls.append(Path(path).name) or True
    model3d._attach_measurement = lambda meta, path: None
    body_path = mdir / f"{bid}.glb"
    shutil.copy2(work / "body.glb", body_path)
    model3d._publish_sidecar(body_path, {"rig": "mixamo", "outfit_body": parent, "signature": bid,
                                         "extension_rig": {"status": "none_applicable"},
                                         "blender": {"steps": ["normalize"]}})
    sha0 = hashlib.sha256(body_path.read_bytes()).hexdigest()
    check("stored body stale (missing)", posture.is_stale(char, bid))
    out = model3d.match_outfit_body_posture(char, bid)
    check("a) ok", out.get("ok") and not out.get("noop"), str(out)[:300])
    sha1 = hashlib.sha256(body_path.read_bytes()).hexdigest()
    check("a) body sha changed", sha1 != sha0)
    check("a) published lean 5.0", near(posture.rest_lean(body_path.read_bytes())["forward_deg"], 5.0, 0.5))
    stored = model3d._read_sidecar(body_path)
    check("a) sidecar record applied", posture.record_of(stored).get("status") == "applied")
    check("a) collision refreshed once", calls == [f"{bid}.glb"], str(calls))
    check("a) not stale any more", not posture.is_stale(char, bid))
    again = model3d.match_outfit_body_posture(char, bid)
    check("a) second call no-op", again.get("ok") and again.get("noop")
          and hashlib.sha256(body_path.read_bytes()).hexdigest() == sha1)

    bid2 = "ob87654321"
    body2 = mdir / f"{bid2}.glb"
    prerig = mdir / "prerig" / f"{bid2}.glb"
    prerig.parent.mkdir(exist_ok=True)
    shutil.copy2(work / "body.glb", body2)
    shutil.copy2(work / "body.glb", prerig)
    parent2 = {**parent, "body_id": bid2}
    model3d._publish_sidecar(body2, {"rig": "mixamo", "outfit_body": parent2, "signature": bid2,
                                     "extension_rig": {"status": "applied", "has_applied": True},
                                     "blender": {"steps": ["normalize"]}})
    model3d._publish_sidecar(prerig, {"rig": "mixamo", "blender": {"steps": ["normalize"]}})
    rebuilt = []

    def fake_rebuild(name, signature=None, *, tier="full", force=False):
        # As _extension_rig_once publishes: the prerig bytes (+ bones) and the prerig's blender block.
        directory = model3d.get_model3d_dir(name)
        source = directory / "prerig" / f"{signature}.glb"
        target = directory / f"{signature}.glb"
        rebuilt.append((signature, force))
        model3d._publish_model_bytes(target, source.read_bytes())
        meta_t = model3d._read_sidecar(target)
        meta_t["blender"] = model3d._read_sidecar(source).get("blender") or {}
        model3d._publish_sidecar(target, meta_t)
        return {"ok": True, "applied": True}
    model3d.rebuild_extension_rig = fake_rebuild
    in_place = []
    real_auto = model3d._auto_posture_match

    def spy(name, path, meta, **kw):
        in_place.append(Path(path).parent.name)
        return real_auto(name, path, meta, **kw)
    model3d._auto_posture_match = spy
    out2 = model3d.match_outfit_body_posture(char, bid2)
    check("b) ok", out2.get("ok"), str(out2)[:300])
    check("b) prerig matched to 5.0", near(posture.rest_lean(prerig.read_bytes())["forward_deg"], 5.0, 0.5))
    check("b) rebuilt from the prerig with force", rebuilt == [(bid2, True)], str(rebuilt))
    check("b) body lean 5.0", near(posture.rest_lean(body2.read_bytes())["forward_deg"], 5.0, 0.5))
    check("b) body record names the base sha",
          posture.record_of(model3d._read_sidecar(body2)).get("base_sha256") == base_sha)
    check("b) only the prerig was matched (no in-place pass)", in_place == ["prerig"], str(in_place))
    model3d._auto_posture_match = real_auto

    print("[7] the step line")
    from app.core.model_overview import outfit_body_steps
    rows = {r["id"]: r for r in outfit_body_steps(stored)}
    row = rows.get("posture_match") or {}
    check("row label", row.get("label") == "Posture matched to base")
    check("row done", row.get("status") == "done", str(row.get("status")))
    # "-0.0": the turn leaves the sideways lean at -1e-5°, printed with its sign.
    check("row detail", str(row.get("detail")).replace("-0.0°", "+0.0°") == "forward +14.0° → +5.0° (base +5.0°) · "
          "sideways +0.0° → +0.0° (base +0.0°) · turned 9.0°", repr(row.get("detail")))
    nums = row.get("numbers") or {}
    check("row numbers", near(nums.get("forward_before_deg"), 14.0, 0.01) and near(nums.get("forward_after_deg"), 5.0, 0.01)
          and near(nums.get("turned_deg"), 9.0, 0.05), str(nums))
    none = {r["id"]: r for r in outfit_body_steps({"rig": "mixamo", "blender": {}})}
    check("no record -> missing", none["posture_match"]["status"] == "missing")
    err = {r["id"]: r for r in outfit_body_steps({"blender": {"posture_match": {**record, "error": "boom"}}})}
    check("error -> failed", err["posture_match"]["status"] == "failed")
    tol = {r["id"]: r for r in outfit_body_steps({"blender": {"posture_match": {**record, "status": "within_tolerance"}}})}
    check("within tolerance -> skipped", tol["posture_match"]["status"] == "skipped")

    print()
    if failures:
        print(f"FAILED: {len(failures)} — " + "; ".join(failures))
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    try:
        code = main()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(code)
