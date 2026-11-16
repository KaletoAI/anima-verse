"""Drape one garment template onto a plain rigged body (P1, Ruling A138).

Runner contract (``app/blender/runner.py``): ``inputs`` {body: the plain rigged
base GLB, front / back: the piece's views (cut-outs or the item picture)},
``params`` from ``app.core.garment_template.build_args``:

* ``spec``    the sampled pygarment panels (``panel_spec``): rows x cols grids per
              panel (front, back; each half the circumference), ``row_y`` = the
              world height of every row (Blender Z = glTF Y), row 0 = the pinned top;
* ``fabric``  bending / mass / quality / shrink of the cloth run;
* ``slit``    {side: none|left|right|front|back, depth_m}: vertical edges at that
              angle are split from the hem up;
* ``node``    the name of the exported garment node (``garment_…``);
* ``poses``   the poses measured after the drape (spike evaluator), ``render``.

Steps: wrap the panel rows round the body axis (radius = the pattern's own, never
closer than 2 cm outside the body; the pinned top row FOLLOWS the body at 6 mm —
the spike's open point), merge the side seams, split the slit, pin the top row,
cloth-drape on the voxel-remeshed posed body (spike ``drape``), measure stretch,
Solidify 1.5 mm, project the views onto the panel UVs, skin by Data Transfer,
measure the poses, export armature + garment. Wall and CPU seconds are reported
for the drape and the whole script.
"""
import math
import sys
import time
from pathlib import Path

import bmesh
import bpy
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from _common import main  # noqa: E402
import garment_template_drape as gd  # noqa: E402
sys.path.pop(0)

#: Angle of each slit side (0 = +X = the character's left, front = -Y).
SLIT_ANGLE = {"left": 0.0, "back": math.pi / 2, "right": math.pi, "front": 3 * math.pi / 2}
TOP_CLEAR_M = 0.006
ROW_CLEAR_M = 0.02


def wrap(spec, btree, centre):
    """Vertices / quads / UVs of the panels wrapped round the body axis."""
    rows, cols = spec["rows"], spec["cols"]
    row_y = spec["row_y"]
    spans = {"front": (math.pi, 2 * math.pi), "back": (0.0, math.pi)}
    verts, faces, uvs, angles = [], [], [], []
    allg = np.array([p["grid_m"] for p in spec["panels"]])
    xmin, xmax = allg[..., 0].min(), allg[..., 0].max()
    ymax = allg[..., 1].max()
    for pi_, p in enumerate(spec["panels"]):
        g = np.array(p["grid_m"])
        a0, a1 = spans[p["name"]]
        for r in range(rows):
            row = g[r]
            circ = 2 * float(np.sum(np.linalg.norm(np.diff(row, axis=0), axis=1)))
            z = row_y[r]
            for c in range(cols):
                ang = a0 + (a1 - a0) * c / (cols - 1)
                body_r = gd.body_radius(btree, centre, ang, z)
                if r == 0:
                    rad = body_r + TOP_CLEAR_M if body_r > 0 else circ / (2 * math.pi)
                else:
                    rad = max(circ / (2 * math.pi), body_r + ROW_CLEAR_M)
                verts.append((centre[0] + rad * math.cos(ang), centre[1] + rad * math.sin(ang), z))
                uvs.append((0.02 + 0.47 * (row[c, 0] - xmin) / max(1e-6, xmax - xmin) + 0.5 * pi_,
                            0.02 + 0.96 * row[c, 1] / max(1e-6, ymax)))
                angles.append(ang)
        base = pi_ * rows * cols
        for r in range(rows - 1):
            for c in range(cols - 1):
                i = base + r * cols + c
                faces.append((i, i + 1, i + cols + 1, i + cols))
    return verts, faces, uvs, angles


def split_slit(obj, angles, slit, hem_z, centre):
    """Split the vertical edges at the slit's angle from the hem up to ``depth_m``."""
    side, depth = slit.get("side"), float(slit.get("depth_m") or 0)
    if side not in SLIT_ANGLE or depth <= 0:
        return 0
    target = SLIT_ANGLE[side]
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bm.verts.ensure_lookup_table()

    def ang_of(v):
        a = math.atan2(v.co.y - centre[1], v.co.x - centre[0]) % (2 * math.pi)
        d = abs(a - target)
        return min(d, 2 * math.pi - d)
    step = 2 * math.pi / 80
    cut = [e for e in bm.edges
           if all(ang_of(v) < step * 0.5 for v in e.verts)
           and max(v.co.z for v in e.verts) <= hem_z + depth + 1e-4
           and abs(e.verts[0].co.z - e.verts[1].co.z) > 1e-4]
    if cut:
        bmesh.ops.split_edges(bm, edges=cut)
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()
    return len(cut)


def run(a):
    t_all, c_all = time.time(), time.process_time()
    inp, prm = a["inputs"], a["params"]
    out = Path(a["out_dir"])
    arm, body, _g = gd.load_fit(inp["body"])
    spec = prm["spec"]
    bco, _bn, btri = gd.world_coords(body)
    # the radius tree is the torso + legs only: a T-posed arm beside the chest band would
    # otherwise be the "body" a ray from outside meets first (the band then spans the arms)
    half = float(prm.get("torso_half_m") or 0.24)
    tri = np.asarray(btri)
    keep = np.all(np.abs(bco[tri][..., 0]) < half, axis=1)
    btree = gd.bvh_of(bco, [tuple(t) for t in tri[keep]])
    top_z = spec["row_y"][0]
    sl = bco[np.abs(bco[:, 2] - top_z) < 0.01]
    centre = sl[:, :2].mean(0) if len(sl) else bco[:, :2].mean(0)
    verts, faces, uvs, angles = wrap(spec, btree, centre)
    me = bpy.data.meshes.new("template")
    me.from_pydata(verts, [], faces)
    uvl = me.uv_layers.new(name="UVMap")
    for lp in me.loops:
        uvl.data[lp.index].uv = uvs[lp.vertex_index]
    obj = bpy.data.objects.new(prm["node"], me)
    bpy.context.scene.collection.objects.link(obj)
    bm = bmesh.new()
    bm.from_mesh(me)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.004)   # the two side seams
    bm.to_mesh(me)
    bm.free()
    hem_z = spec["row_y"][-1]
    slit_edges = split_slit(obj, angles, prm.get("slit") or {}, hem_z, centre)
    me = obj.data
    co0 = np.array([v.co for v in me.vertices])
    edges = gd.edges_of(obj)
    rest_len = np.linalg.norm(co0[edges[:, 0]] - co0[edges[:, 1]], axis=1)
    pin = np.where(co0[:, 2] > top_z - 0.004)[0]
    fab = prm["fabric"]
    cpu, wall, drift = gd.drape(obj, body, pin, int(prm.get("frames", 50)), quality=int(fab["quality"]),
                                bending=float(fab["bending"]), shrink=float(fab.get("shrink", 0.0)),
                                self_collision=False, thickness=float(prm.get("thickness", 0.004)))
    me = obj.data
    co1 = np.array([v.co for v in me.vertices])
    st = np.linalg.norm(co1[edges[:, 0]] - co1[edges[:, 1]], axis=1) / np.maximum(rest_len, 1e-6)
    worst = co0[edges[int(st.argmax())]].mean(0)
    worst_at = {"z": round(float(worst[2]), 3),
                "deg": round(math.degrees(math.atan2(worst[1] - centre[1], worst[0] - centre[0])) % 360, 1),
                "over_1_3": int((st > 1.3).sum())}
    sol = obj.modifiers.new("sol", "SOLIDIFY")
    sol.thickness = 0.0015
    sol.offset = 1
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.modifier_apply(modifier=sol.name)
    t_bake = time.time()
    tex = gd.project_bake(obj, {"view_front": inp["front"], "view_back": inp["back"]},
                          out / "template_atlas.png", size=1024)
    tex["wall_s"] = round(time.time() - t_bake, 2)
    edges2 = gd.edges_of(obj)
    co2 = np.array([v.co for v in obj.data.vertices])
    rest2 = np.linalg.norm(co2[edges2[:, 0]] - co2[edges2[:, 1]], axis=1)
    rim = gd.boundary_verts(obj)
    gd.bind_to_armature(obj, body, arm)
    view = gd.frame_of(co2)
    t_meas = time.time()
    measured = {}
    for pose in prm.get("poses") or ["rest"]:
        measured[pose] = gd.measure_pose(arm, body, obj, pose, rest2, edges2, rim)
        if prm.get("render"):
            gd.render(out / f"template_{pose}.png", view)
    gd.set_pose(arm, "rest")
    meas_s = round(time.time() - t_meas, 2)
    glb = out / "template.glb"
    gd.export(glb, [arm, obj])
    outputs = {"glb": str(glb), "atlas": str(out / "template_atlas.png")}
    for pose in measured:
        p = out / f"template_{pose}.png"
        if p.is_file():
            outputs[f"render_{pose}"] = str(p)
    data = {"verts": len(obj.data.vertices), "pins": int(len(pin)), "slit_edges": int(slit_edges),
            "drape": {"cpu_s": cpu, "wall_s": wall, "pin_drift_mm": drift,
                      "stretch_max": round(float(st.max()), 3), "stretch_at": worst_at, "stretch_p99": round(float(np.percentile(st, 99)), 3),
                      "quality": int(fab["quality"])},
            "bake": tex, "draped": measured, "measure_wall_s": meas_s,
            "script_wall_s": round(time.time() - t_all, 2), "script_cpu_s": round(time.process_time() - c_all, 2)}
    return gd._plain(data), outputs


if __name__ == "__main__":
    main(run)
