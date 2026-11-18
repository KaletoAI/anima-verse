#!/usr/bin/env python3
"""Real Blender regression: distance meshes must not remove protected glazing, nor a humanoid's fingers.

Usage: .venv/bin/python scripts/smoke_blender_lod.py [--blender /path/to/blender]

No server, world, providers or stored settings are changed.

[G] Glazing: four separate 2m panes in one marked mesh must retain their full
    coverage after reduction, while ordinary masonry simplifies. The output GLB
    is re-imported and raycast.

[H] Hands (``protect_hands``, hand analysis 2026-11-18 § 1.3). ONE skinned mesh
    holds a body — a UV sphere r 0.3 m, 64 segments x 32 rings = 3968 triangles
    (2 x 64 pole fans + 64 x 30 x 2 quads), every edge curved so every collapse
    costs something — and a left hand: a palm box (12) and five fingers along
    +X, each an octagonal prism r 7.5 mm (a vertex pointing +-Y), 80 mm long in
    16 rings of segments: 8 x 16 x 2 = 256 side + 2 x 6 cap = 268 triangles,
    1340 for five. Finger axes 19 mm apart in Y, so the gap between neighbours
    is 19 - 2 x 7.5 = 4.0 mm. The inner rings of a straight prism are coplanar
    with their neighbours: collapsing them costs NOTHING, so a plain Decimate
    takes them first (that is the paddle). Each third of a finger is skinned
    to ``mixamorig:LeftHand<Finger>1..3``, the palm to ``LeftHand``, the body
    to ``Hips``. Total 3968 + 12 + 1340 = 5320; ratio 0.5 -> 2660.
    [H1] with ``protect_hands``: every finger triangle of the input (all three
         corners skinned >= 0.01 to a finger bone, counted after the glTF round
         trip) is still there — 1340 — and every finger vertex position is
         found in the output within 1 micrometre;
    [H2] the gap: the smallest distance between neighbouring fingers is still
         4.0 mm (+-0.05);
    [H3] the tier meets its target: the stage reports 2660 +- 1 % and
         ``hand_guard_tris`` >= 1340 (the guarded set also holds the caps);
    [H4] counter-probe = the code before the guard: the same job without
         ``protect_hands`` keeps fewer than 1340 finger triangles;
    [H5] a mesh without finger bones (the same fixture, finger groups named
         ``LeftPaw<Finger><k>`` — an animal's) gives a BYTE-IDENTICAL file with
         and without ``protect_hands``, and ``hand_guard_tris`` 0.
"""
import argparse
import json
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def smoke_in_blender():
    import bpy
    from mathutils import Vector
    import math

    with tempfile.TemporaryDirectory(prefix="smoke-glazing-lod-") as temporary:
        directory = Path(temporary)
        bpy.ops.wm.read_factory_settings(use_empty=True)
        centres = (-6, -3, 0, 3)
        panes = []
        for x in centres:
            bpy.ops.mesh.primitive_plane_add(
                size=2, location=(x, 0, 1), rotation=(math.pi / 2, 0, 0))
            panes.append(bpy.context.object)
        bpy.ops.object.select_all(action="DESELECT")
        for pane in panes:
            pane.select_set(True)
        bpy.context.view_layer.objects.active = panes[0]
        bpy.ops.object.join()
        window = bpy.context.object
        window.name = "protected-windows"
        window["lod_preserve"] = True
        glass = bpy.data.materials.new("window glass")
        glass.use_nodes = True
        glass.node_tree.nodes["Principled BSDF"].inputs["Alpha"].default_value = .25
        glass.surface_render_method = "BLENDED"
        window.data.materials.append(glass)
        bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=3, radius=1, location=(8, 0, 1))
        masonry = bpy.context.object
        masonry.name = "masonry"
        before = len(masonry.data.polygons)
        source = directory / "input.glb"
        bpy.ops.export_scene.gltf(filepath=str(source), export_format="GLB", export_extras=True)

        output = directory / "out"
        output.mkdir()
        result = directory / "result.json"
        packet = directory / "job.json"
        packet.write_text(json.dumps({"inputs": {"model": str(source)},
                                     "params": {"ratios": [.5]}, "out_dir": str(output),
                                     "result": str(result)}), encoding="utf-8")
        previous_argv = sys.argv
        try:
            sys.argv = ["lod.py", "--", str(packet)]
            runpy.run_path(str(ROOT / "app/blender/scripts/lod.py"), run_name="__main__")
        finally:
            sys.argv = previous_argv
        response = json.loads(result.read_text(encoding="utf-8"))
        assert response["ok"], response["error"]
        produced = next(iter(response["outputs"].values()))
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.gltf(filepath=produced)
        graph = bpy.context.evaluated_depsgraph_get()
        quadrants = []
        for centre in centres:
            for x in (centre - .5, centre + .5):
                for z in (.5, 1.5):
                    hit, _, _, _, obj, _ = bpy.context.scene.ray_cast(
                        graph, Vector((x, -1, z)), Vector((0, 1, 0)), distance=2)
                    quadrants.append(bool(hit and obj.name.startswith("protected-windows")))
        print("Window quadrant coverage:", quadrants)
        assert all(quadrants), "LOD removed part of a protected window pane"
        reduced = sum(len(obj.data.polygons) for obj in bpy.context.scene.objects
                      if obj.type == "MESH" and obj.name.startswith("masonry"))
        print("Ordinary masonry triangles:", before, "->", reduced)
        assert 0 < reduced < before * .75, "Protection accidentally disabled masonry reduction"
        print("Protected glazing survives; ordinary geometry still reduces.")
    smoke_hands()


FINGERS = ("Thumb", "Index", "Middle", "Ring", "Pinky")
FINGER_R, FINGER_LEN, FINGER_RINGS, FINGER_PITCH = 0.0075, 0.08, 16, 0.019


def _hand_fixture(path, finger_group):
    """The [H] fixture as one skinned mesh, exported to ``path``; ``finger_group(finger, k)`` names the
    finger vertex groups (and bones)."""
    import bpy
    import math
    bpy.ops.wm.read_factory_settings(use_empty=True)
    verts, faces, owner = [], [], []

    def add(vs, fs, group):
        base = len(verts)
        verts.extend(vs)
        owner.extend(group(i) for i in range(len(vs)))
        faces.extend(tuple(base + i for i in f) for f in fs)

    # body: UV sphere at (0, 0, 1)
    seg, rings = 64, 32
    vs = [(0, 0, 1.3)]
    for r in range(1, rings):
        th = math.pi * r / rings
        vs += [(0.3 * math.sin(th) * math.cos(2 * math.pi * s / seg), 0.3 * math.sin(th) * math.sin(2 * math.pi * s / seg),
                1 + 0.3 * math.cos(th)) for s in range(seg)]
    vs.append((0, 0, 0.7))
    fs = [(0, 1 + s, 1 + (s + 1) % seg) for s in range(seg)]
    for r in range(rings - 2):
        for s in range(seg):
            a, b = 1 + r * seg + s, 1 + r * seg + (s + 1) % seg
            fs.append((a, b, b + seg, a + seg))
    last = len(vs) - 1
    fs += [(last, 1 + (rings - 2) * seg + (s + 1) % seg, 1 + (rings - 2) * seg + s) for s in range(seg)]
    add(vs, fs, lambda i: "mixamorig:Hips")
    # palm: a box behind the finger roots
    x0, y0, z0 = 0.6, -0.045, 1.0
    box = [(x0 + dx, y0 + dy, z0 + dz) for dx in (-0.09, 0) for dy in (-0.01, 0.09) for dz in (-0.01, 0.01)]
    add(box, [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)],
        lambda i: "mixamorig:LeftHand")
    # fingers: octagonal prisms along +X, a vertex pointing +-Y
    for n, finger in enumerate(FINGERS):
        cy = (n - 2) * FINGER_PITCH
        vs = [(x0 + FINGER_LEN * r / FINGER_RINGS, cy + FINGER_R * math.cos(math.pi * k / 4),
               z0 + FINGER_R * math.sin(math.pi * k / 4)) for r in range(FINGER_RINGS + 1) for k in range(8)]
        fs = [(r * 8 + k, r * 8 + (k + 1) % 8, (r + 1) * 8 + (k + 1) % 8, (r + 1) * 8 + k)
              for r in range(FINGER_RINGS) for k in range(8)]
        fs += [tuple(range(7, -1, -1)), tuple(FINGER_RINGS * 8 + k for k in range(8))]
        add(vs, fs, lambda i, f=finger: finger_group(f, min(3, 1 + 3 * (i // 8) // (FINGER_RINGS + 1))))
    me = bpy.data.meshes.new("body")
    me.from_pydata(verts, [], faces)
    obj = bpy.data.objects.new("body", me)
    bpy.context.scene.collection.objects.link(obj)
    arm = bpy.data.armatures.new("rig")
    armo = bpy.data.objects.new("Armature", arm)
    bpy.context.scene.collection.objects.link(armo)
    bpy.context.view_layer.objects.active = armo
    bpy.ops.object.mode_set(mode="EDIT")
    hips = arm.edit_bones.new("mixamorig:Hips")
    hips.head, hips.tail = (0, 0, 0.9), (0, 0, 1.1)
    hand = arm.edit_bones.new("mixamorig:LeftHand")
    hand.head, hand.tail, hand.parent = (x0 - 0.09, 0, z0), (x0, 0, z0), hips
    for n, finger in enumerate(FINGERS):
        parent, cy = hand, (n - 2) * FINGER_PITCH
        for k in (1, 2, 3):
            b = arm.edit_bones.new(finger_group(finger, k))
            b.head = (x0 + FINGER_LEN * (k - 1) / 3, cy, z0)
            b.tail = (x0 + FINGER_LEN * k / 3, cy, z0)
            b.parent = parent
            parent = b
    bpy.ops.object.mode_set(mode="OBJECT")
    groups = {}
    for i, name in enumerate(owner):
        groups.setdefault(name, []).append(i)
    for name, rows in groups.items():
        obj.vertex_groups.new(name=name).add(rows, 1.0, "REPLACE")
    obj.modifiers.new("Armature", "ARMATURE").object = armo
    obj.parent = armo
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.export_scene.gltf(filepath=str(path), export_format="GLB")


def _run_lod(source, out_dir, params):
    out_dir.mkdir()
    result = out_dir / "result.json"
    packet = out_dir / "job.json"
    packet.write_text(json.dumps({"inputs": {"model": str(source)}, "params": params,
                                  "out_dir": str(out_dir), "result": str(result)}), encoding="utf-8")
    previous_argv = sys.argv
    try:
        sys.argv = ["lod.py", "--", str(packet)]
        runpy.run_path(str(ROOT / "app/blender/scripts/lod.py"), run_name="__main__")
    finally:
        sys.argv = previous_argv
    response = json.loads(result.read_text(encoding="utf-8"))
    assert response["ok"], response["error"]
    return Path(next(iter(response["outputs"].values()))), response["data"]["stages"][0]


def _finger_geometry(path):
    """(finger triangle count, finger vertex positions, positions per finger) of a GLB after import."""
    import bpy
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(path))
    obj = next(o for o in bpy.context.scene.objects if o.type == "MESH")
    names = {g.index: g.name for g in obj.vertex_groups}
    me = obj.data
    finger_of = {}
    for v in me.vertices:
        w = {}
        for g in v.groups:
            name = names[g.group]
            for f in FINGERS:
                if f in name and name[-1] in "123":
                    w[f] = w.get(f, 0.0) + g.weight
        if sum(w.values()) >= 0.01:
            finger_of[v.index] = max(w, key=w.get)
    me.calc_loop_triangles()
    tris = sum(1 for t in me.loop_triangles if all(i in finger_of for i in t.vertices))
    mw = obj.matrix_world
    points = {i: tuple(mw @ me.vertices[i].co) for i in finger_of}
    per = {f: [points[i] for i, g in finger_of.items() if g == f] for f in FINGERS}
    return tris, list(points.values()), per


def smoke_hands():
    import math
    with tempfile.TemporaryDirectory(prefix="smoke-hand-lod-") as temporary:
        directory = Path(temporary)
        source = directory / "hand.glb"
        _hand_fixture(source, lambda f, k: f"mixamorig:LeftHand{f}{k}")
        tris_in, points_in, _ = _finger_geometry(source)
        print("[H] input finger triangles:", tris_in)
        assert tris_in == 1340, f"fixture: expected 1340 finger triangles, got {tris_in}"

        guarded, stage = _run_lod(source, directory / "guarded", {"ratios": [0.5], "protect_hands": True})
        tris_out, points_out, per = _finger_geometry(guarded)
        print("[H1] finger triangles kept:", tris_out, "stage:", stage)
        assert tris_out == 1340, f"[H1] the guarded tier lost finger triangles: {tris_out}"
        out_keys = {tuple(round(c * 1e6) for c in p) for p in points_out}
        lost = [p for p in points_in if tuple(round(c * 1e6) for c in p) not in out_keys]
        assert not lost, f"[H1] {len(lost)} finger vertices moved or vanished, e.g. {lost[:2]}"
        gaps = [min(math.dist(a, b) for a in per[f] for b in per[g]) for f, g in zip(FINGERS, FINGERS[1:])]
        print("[H2] neighbour gaps (mm):", [round(g * 1000, 3) for g in gaps])
        assert all(abs(g - 0.004) <= 0.00005 for g in gaps), f"[H2] gaps changed: {gaps}"
        assert stage["tris_before"] == 5320, f"[H3] fixture: {stage['tris_before']} triangles, expected 5320"
        assert abs(stage["tris"] - 2660) <= 27, f"[H3] the tier missed its target: {stage['tris']} vs 2660"
        assert stage["hand_guard_tris"] >= 1340, f"[H3] guarded triangles {stage['hand_guard_tris']}"

        plain, stage_plain = _run_lod(source, directory / "plain", {"ratios": [0.5]})
        tris_plain, _, _ = _finger_geometry(plain)
        print("[H4] without the guard:", tris_plain, "finger triangles, stage:", stage_plain)
        assert tris_plain < 1340, "[H4] counter-probe: the plain decimation kept every finger triangle"

        paw = directory / "paw.glb"
        _hand_fixture(paw, lambda f, k: f"mixamorig:LeftPaw{f}{k}")
        on, stage_on = _run_lod(paw, directory / "paw_on", {"ratios": [0.5], "protect_hands": True})
        off, _ = _run_lod(paw, directory / "paw_off", {"ratios": [0.5]})
        same = on.read_bytes() == off.read_bytes()
        print("[H5] no finger bones: identical =", same, "guarded:", stage_on.get("hand_guard_tris"))
        assert same, "[H5] protect_hands changed a mesh without finger bones"
        assert stage_on.get("hand_guard_tris") == 0, f"[H5] guarded triangles {stage_on.get('hand_guard_tris')}"
        print("Fingers survive the distance tier; the rest pays; no finger bones = no change.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blender", default="", help="Override executable for this smoke only")
    args = parser.parse_args()
    executable = args.blender
    if not executable:
        sys.path.insert(0, str(ROOT))
        from app.blender import runner
        executable = runner.status()["executable"]
    if not executable:
        print("FAIL: Blender is required for the real geometry regression")
        return 1
    return subprocess.run(
        [executable, "--background", "--factory-startup", "--python-exit-code", "1",
         "--python", str(Path(__file__).resolve()), "--", "--in-blender"],
        check=False, timeout=180).returncode


if __name__ == "__main__":
    if "--in-blender" in sys.argv:
        smoke_in_blender()
    else:
        raise SystemExit(main())
