#!/usr/bin/env python3
"""Real Blender regression: distance meshes must not remove protected glazing.

Usage: .venv/bin/python scripts/smoke_blender_lod.py [--blender /path/to/blender]

No server, world, providers or stored settings are changed. Four separate 2m
panes in one marked mesh must retain their full coverage after reduction,
while ordinary masonry simplifies. The output GLB is re-imported and raycast.
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
