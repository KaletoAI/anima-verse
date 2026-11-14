#!/usr/bin/env python3
"""A tip part off only levels the mesh; on, the source bump is levelled under it; one box per tip group (Ruling A53).

Usage:
    ./.venv/bin/python scripts/smoke_tip_off_mesh_only.py              # parts A and B (B needs Blender, ~4 min)
    ./.venv/bin/python scripts/smoke_tip_off_mesh_only.py --no-blender # part A only

Runs against a THROWAWAY storage directory (``paths.init(<tmp>)`` before any world module is imported) — no world, no
server, no hub.

Part A — the UI payload (no Blender).
[1] ``extension_tip.group_tip_settings(panels, extension)`` puts everything of a tip group in its tip panel: with the
    panels [T] and the extension state {groups [P (controls None), T (controls [length, girth])], lights {P: LP,
    T: LT}, result {status applied, attempted_at "2026-11-14T18:49:00+00:00"}}, panel T carries ``light`` LT,
    ``controls`` [length, girth] and ``built_at`` "2026-11-14T18:49:00+00:00" beside its own enabled / override /
    limits; ``box_groups`` is [P] (the box lists no tip group); ``groups`` and ``lights`` stay whole (the viewer's
    motion preview reads every group). A failed result → ``built_at`` None; no extension state → light None,
    controls [], no ``box_groups``.
[2] The route wires it: ``figure._plain_body_extras`` (its model readers stubbed) answers ``extension_tips`` [T with
    light LT and controls [length, girth]] and ``extension.box_groups`` [P].
    Fails on 33d69c57569c82987d949bc3abc46bf039830f67: ``extension_tip`` there has no ``group_tip_settings`` and its
    figure route hands the panels no light (checked below against ``git show <hash>:…``).

Part B — the mesh (Blender), on the pair-tip smoke's fixture: two spherical caps of radius .106 (centre y = -.044)
over the plane y = -.1, colour markers of radius 9 mm at (+-.15, 1.41), skin (.72, .52, .40), marker (.62, .28, .30)
in a 1024 x 1024 base colour. A cosine bump of 4 mm height and 6 mm radius (4 mm x (1 + cos(pi r / 6 mm)) / 2,
along -Y) is pushed out at each SOURCE apex (where the source group located the part — the marker centre). The
levelling (``extension_bones.level_sides``, Ruling A44's fitted surface): full out to max(1.2 R, 12 mm, stub radius
4.5 + wall 1.5 + margin 3 = 9 mm) = 12 mm with R ≈ 9 mm, fading over 9.6 mm; the quadratic is fitted on the cap at
21.6-30 mm and misses the sphere inside 12 mm by the r^4 term (.0216^2 x .03^2) / (8 x .106^3) = .044 mm — inside the
.3 mm budget the pair-tip smoke uses. "Bump" below = the largest height above the sphere (sphere y minus vertex y) of
an original grid vertex within 6 mm (in x, z) of a source apex: 4.0 mm before.
[3] Off (``when_off: neutralise``): the bump after < .3 mm on both sides, the record's height before 3.982 ± .05 mm
    (the pair-tip smoke's derivation) and after < .3 mm — and the texture is BYTE-IDENTICAL: a GLB holding the
    fixture's base colour as PNG goes through ``paint_disc_masks`` with the metrics the script returned and comes out
    with the very same bytes; the metrics carry no paint mask.
    On 33d69c57…: the script returns a ``neutral_mask`` and the old ``paint_disc_masks`` paints the marker over with
    the ring colour → the bytes differ.
[4] On, offset 20 mm up and 20 mm out (mirror): the source bump is levelled although the tip moved away — bump after
    < .3 mm, the record's ``source_level.bump_mm`` [>= 3.9 (3.982 less the fit's .044 mm), < .3]; the stub is built
    (``tip_source`` "stub", length 5 mm) where the walk put it: the walk is hypot(20, 20) = 28.28 mm long over the
    mesh BEFORE the levelling, starting on the bump's top, so it loses at most the bump slope's extra length (the
    arc of the 4 mm / 6 mm cosine flank is <= 7.3 mm for 6 mm across → <= 1.3 mm) and gains at most the 4 mm drop:
    ``tip_from_source_mm`` in [28.28 - 1.3 - .5 (the chord of a 28 mm arc on R = 106 mm loses .08) = 26.4,
    hypot(28.28, 4) = 28.57]; normals within 40 mm of the tips after: 0 inverted, 0 off by more than 60°.
    On 33d69c57…: the smoothing was centred on the placed tip 26+ mm away → the source bump stays > 2 mm.
[5] On, no offset: the mesher's own 4 mm tip is REPLACED (no more "kept") — ``tip_source`` "stub", ``source_level``
    bump [>= 3.9, < .3], ``tip_from_source_mm`` 0. On 33d69c57… it was kept (``tip_source`` "mesh", no stub).

No expected value is recorded from a run.
"""
import hashlib
import io
import json
import struct
import subprocess
import sys
import tempfile
import types
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OLD = "33d69c57569c82987d949bc3abc46bf039830f67"

_tmp = Path(tempfile.mkdtemp(prefix="smoke_tip_off_mesh_only_"))
from app.core import paths  # noqa: E402
paths.init(str(_tmp))

from app.core import extension_tip  # noqa: E402

FAILS = []


def check(label, got, want=True):
    ok = got == want
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + ("" if ok else f"  — got {got!r}, want {want!r}"))
    if not ok:
        FAILS.append(label)


def old_source(path):
    return subprocess.run(["git", "-C", str(ROOT), "show", f"{OLD}:{path}"], check=True, capture_output=True,
                          text=True).stdout


# --- Part A -------------------------------------------------------------------------------------------------------

LP = {"light": "green", "state": "Built", "reason": "", "detail": ""}
LT = {"light": "yellow", "state": "Not built", "reason": "Rebuild", "detail": ""}
AT = "2026-11-14T18:49:00+00:00"


def panel():
    return {"id": "T", "label": "Tips", "enabled": True, "active": True, "status": "applied", "reason": "",
            "override": {"offsets": [{"up": 1, "out": 2}, {"up": 1, "out": 2}], "mirror": True}, "limits": {}}


def extension(status="applied"):
    return {"groups": [{"id": "P", "controls": None}, {"id": "T", "controls": ["length", "girth"]}],
            "lights": {"P": dict(LP), "T": dict(LT)}, "result": {"status": status, "attempted_at": AT}}


def part_a():
    panels, ext = [panel()], extension()
    extension_tip.group_tip_settings(panels, ext)
    p = panels[0]
    check("[1] the tip panel carries light, controls, built time and its own settings",
          (p["light"], p["controls"], p["built_at"], p["enabled"], p["override"]["mirror"]),
          (LT, ["length", "girth"], AT, True, True))
    check("[1] the box lists no tip group", ext["box_groups"], ["P"])
    check("[1] groups and lights stay whole", ([g["id"] for g in ext["groups"]], sorted(ext["lights"])),
          (["P", "T"], ["P", "T"]))
    panels, ext = [panel()], extension("failed")
    extension_tip.group_tip_settings(panels, ext)
    check("[1] a failed build: no built time", panels[0]["built_at"], None)
    panels = [panel()]
    extension_tip.group_tip_settings(panels, None)
    check("[1] no extension state", (panels[0]["light"], panels[0]["controls"], panels[0]["built_at"]),
          (None, [], None))

    from app.routes import figure
    from app.core import collision, figure_build, model3d
    info = {"signature": "base1", "humanoid": True, "model": {"status": "ready"}}
    stubs = [patch.object(model3d, "find_model3d", lambda c, s: _tmp / "base1.glb"),
             patch.object(model3d, "get_model3d_options", lambda c: {}),
             patch.object(model3d, "face_cleanup_state", lambda c, s: None),
             patch.object(model3d, "mesh_repair_state", lambda c, s: None),
             patch.object(model3d, "face_info", lambda c, p: {}),
             patch.object(model3d, "model_extension_state", lambda c, s: extension()),
             patch.object(collision, "ensure", lambda c, s: None),
             patch.object(extension_tip, "tip_smoothing_state", lambda c, s: None),
             patch.object(extension_tip, "tip_panels", lambda c, s: [panel()]),
             patch.object(figure_build, "base_run_all", lambda c: {"kind": ""})]
    for stub in stubs:
        stub.start()
    try:
        out = figure._plain_body_extras("demo", info)
    finally:
        for stub in stubs:
            stub.stop()
    tips = out.get("extension_tips") or [{}]
    check("[2] the route groups it", (tips[0].get("light"), tips[0].get("controls"),
                                      (out.get("extension") or {}).get("box_groups")),
          (LT, ["length", "girth"], ["P"]))
    check(f"[2] fails on {OLD[:8]}: no group_tip_settings, no light in the route",
          ("def group_tip_settings" in old_source("app/core/extension_tip.py"),
           "group_tip_settings" in old_source("app/routes/figure.py")), (False, False))


# --- Part B (Blender) -----------------------------------------------------------------------------------------------

PROBE = r'''
import hashlib
case=job['params']['case']
if job['params'].get('old_repair'):
 import importlib.util
 scope['_common'].app_root_on_path()
 import app.core as _core
 spec=importlib.util.spec_from_file_location('app.core.base_mesh_repair',job['params']['old_repair'])
 module=importlib.util.module_from_spec(spec); sys.modules['app.core.base_mesh_repair']=module
 spec.loader.exec_module(module); _core.base_mesh_repair=module
tp_extra=dict(subdivide_radii=[2.4,1.8,1.],normal_radius=2.,fill_radius=1.7,fill_ring=.7,fill_blend=.3,
 fill_depth=.03,fill_tolerance=.012,fill_rms_max=.0015,tip_diameter=.009,tip_length=.005,tip_round=.6,
 tip_wall=.0015,tip_band=.009,tip_subdivide=.009,weight_depth=.015)
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
tip=dict(id='Tip',op='pair_tip',depends_on='Pair',params=tp,
 chains=[[dict(bone='TipLeft',parent='ExampleLeft')],[dict(bone='TipRight',parent='ExampleRight')]])
scope['parameters'](tip)
bones={scope['bone_key'](b.name):b for b in arm.data.bones}
co,edges,owners,normals,faces=scope['mesh_arrays']([obj])
placement=scope['pair_plan'](group,validated,co,bones,scope['pair_surface']([obj]),owners)[2]['placement']
sources=[Vector(row['tip']) for row in placement]
for vertex in obj.data.vertices:
 for t in sources:
  r=math.hypot(vertex.co.x-t.x,vertex.co.z-t.z)
  if r<.006:
   vertex.co.y-=.004*(1+math.cos(math.pi*r/.006))/2
obj.data.update()
scope['_common'].reset_scene=lambda:None
scope['_common'].import_model=lambda path:None
grid=241*241
sphere=lambda x,z,sign:-.044-math.sqrt(.106**2-(x-sign*.15)**2-(z-1.4)**2)
def bump():
 out=[]
 for sign,t in zip((1,-1),sources):
  out.append(max(sphere(v.co.x,v.co.z,sign)-v.co.y for v in obj.data.vertices
                 if v.index<grid and math.hypot(v.co.x-t.x,v.co.z-t.z)<.006)*1000)
 return out
image=bpy.data.images['Marker']
pixels=lambda:hashlib.sha256(bytes(memoryview(_np_px()))).hexdigest()
import numpy as _np
def _np_px():
 a=_np.empty(len(image.pixels),_np.float32); image.pixels.foreach_get(a); return a
texture_before=pixels()
before=bump()
if case=='off':
 run={'groups':[group],'neutralise':[dict(tip,enabled=False,when_off='neutralise')]}
elif case=='on_offset':
 run={'groups':[group,dict(tip,tip_override={'offsets':[{'up':20,'out':20},{'up':20,'out':20}],'mirror':True})]}
else:
 run={'groups':[group,tip]}
result,outputs=scope['extension_bones']({'params':run,'inputs':{'model':'fixture'},
                                        'out_dir':str(Path(job['result']).parent)})
assert result['status']=='applied',result
m=result['metrics']['Tip']
out={'before':before,'after':bump(),'texture_same':pixels()==texture_before,'status':m.get('status'),
     'metrics':result['metrics'],'mask':'neutral_mask' in m}
if case!='off':
 rows=m.get('placement') or []
 out['rows']=[{k:row.get(k) for k in ('tip_source','tip_length_m','source_level','tip')} for row in rows]
 out['normals']=m.get('tip_normals')
 out['heads']=[list(arm.data.bones[n].head_local) for n in ('TipLeft','TipRight') if n in arm.data.bones]
 out['sources']=[list(t) for t in sources]
Path(job['result']).write_text(json.dumps({'ok':True,'data':out,'outputs':{}}))
'''


def fixture_png():
    """The fixture's base colour as PNG, rows top-down (v = 1 at the top): skin with the two markers."""
    import numpy as np
    from PIL import Image
    size = 1024
    ys, xs = np.mgrid[:size, :size]
    u = (xs + .5) / size * .6 - .3
    z = 1.1 + (1 - (ys + .5) / size) * .6
    mask = ((u - .15) ** 2 + (z - 1.41) ** 2 < .009 ** 2) | ((u + .15) ** 2 + (z - 1.41) ** 2 < .009 ** 2)
    rgb = np.empty((size, size, 3), np.float32)
    rgb[:] = (.72, .52, .40)
    rgb[mask] = (.62, .28, .30)
    # Blender stores the floats linear and reads them back as sRGB bytes; the byte check below only needs the same
    # picture both times, so the plain 8-bit quantisation is enough.
    out = io.BytesIO()
    Image.fromarray((rgb * 255 + .5).astype(np.uint8)).save(out, format="PNG")
    return out.getvalue()


def textured_glb(image):
    binary = image + b"\0" * (-len(image) % 4)
    doc = {"asset": {"version": "2.0"}, "buffers": [{"byteLength": len(binary)}],
           "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": len(image)}],
           "images": [{"bufferView": 0, "mimeType": "image/png"}], "textures": [{"source": 0}],
           "materials": [{"pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}}],
           "meshes": [{"primitives": [{"material": 0}]}], "nodes": [{"mesh": 0}]}
    raw = json.dumps(doc).encode()
    raw += b" " * (-len(raw) % 4)
    body = struct.pack("<II", len(raw), 0x4E4F534A) + raw + struct.pack("<II", len(binary), 0x004E4942) + binary
    return b"glTF" + struct.pack("<II", 2, 12 + len(body)) + body


def old_tip_module():
    module = types.ModuleType("old_extension_tip")
    module.__file__ = str(ROOT / "app/core/extension_tip.py")
    exec(compile(old_source("app/core/extension_tip.py"), module.__file__, "exec"), module.__dict__)
    return module


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
    # The old script imports ``_common`` from its own folder: let it find the current one.
    prefix = prefix.replace("source=Path(job['params']['source']);",
                            "sys.path.append(job['params']['scripts']); source=Path(job['params']['source']);")
    scripts = str(runner.SCRIPTS_DIR)
    results = {}
    with tempfile.TemporaryDirectory(prefix="tip-off-mesh-only-") as tmp:
        root = Path(tmp)
        (root / "probe.py").write_text(prefix + PROBE)
        old = root / "old"
        old.mkdir()
        (old / "extension_bones.py").write_text(old_source("app/blender/scripts/extension_bones.py"))
        (old / "base_mesh_repair.py").write_text(old_source("app/core/base_mesh_repair.py"))
        runs = [("off", "new", {}), ("on_offset", "new", {}), ("on_zero", "new", {}),
                ("off", "old", {"old_repair": str(old / "base_mesh_repair.py")}),
                ("on_offset", "old", {"old_repair": str(old / "base_mesh_repair.py")}),
                ("on_zero", "old", {"old_repair": str(old / "base_mesh_repair.py")})]
        with patch.object(runner, "SCRIPTS_DIR", root):
            for case, code, extra in runs:
                source = str(Path(scripts) / "extension_bones.py") if code == "new" else str(old / "extension_bones.py")
                result = runner.run("probe", params={"source": source, "scripts": scripts, "case": case, **extra},
                                    out_dir=root / f"{code}-{case}", timeout_s=300)
                if not result.get("ok"):
                    check(f"[B] {code} {case} ran", result.get("error"), None)
                    return
                results[(code, case)] = result["data"]

    png = fixture_png()

    def painted(module, metrics):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "staged.glb"
            glb = textured_glb(png)
            path.write_bytes(glb)
            module.paint_disc_masks(path, [{"id": "Tip", "tip_override": None}, {"id": "Pair"}], metrics)
            return hashlib.sha256(glb).hexdigest() == hashlib.sha256(path.read_bytes()).hexdigest()

    off = results[("new", "off")]
    print("      off: bump (mm)", [round(v, 3) for v in off["before"]], "→", [round(v, 3) for v in off["after"]])
    check("[3] off: the source bump is 4 mm before", all(abs(v - 4.0) < .05 for v in off["before"]), True)
    check("[3] off: levelled (< .3 mm)", all(v < .3 for v in off["after"]), True)
    rows = off["metrics"]["Tip"]["placement"]
    check("[3] off: record height 3.982 ± .05 → < .3 mm",
          all(abs(r["height_before_mm"] - 3.982) < .05 and r["height_after_mm"] < .3 for r in rows), True)
    check("[3] off: no paint mask, the script's texture untouched", (off["mask"], off["texture_same"]), (False, True))
    check("[3] off: the base colour stays byte-identical", painted(extension_tip, off["metrics"]), True)
    old_off = results[("old", "off")]
    check(f"[3] fails on {OLD[:8]}: a paint mask, the old paint changes the bytes",
          (old_off["mask"], painted(old_tip_module(), old_off["metrics"])), (True, False))

    on = results[("new", "on_offset")]
    print("      on, offset 20/20: bump (mm)", [round(v, 3) for v in on["before"]], "→",
          [round(v, 3) for v in on["after"]], "record", [r["source_level"] for r in on["rows"]],
          "normals", on["normals"])
    check("[4] on, offset: the source bump is levelled (< .3 mm)", all(v < .3 for v in on["after"]), True)
    levels = [r.get("source_level") or {} for r in on["rows"]]
    check("[4] on, offset: record bump [>= 3.9, < .3]", len(levels) == 2 and all(
        (lv.get("bump_mm") or [0, 9])[0] >= 3.9 and (lv.get("bump_mm") or [0, 9])[1] < .3 for lv in levels), True)
    check("[4] on, offset: a stub of 5 mm", [(r["tip_source"], round(r["tip_length_m"] or 0, 6)) for r in on["rows"]],
          [("stub", .005), ("stub", .005)])
    distances = [lv.get("tip_from_source_mm") for lv in levels]
    check("[4] on, offset: tip 26.4-28.57 mm from the source",
          all(isinstance(d, (int, float)) and 26.4 <= d <= 28.57 for d in distances), True)
    normals = on["normals"] or {}
    check("[4] on, offset: normals after — 0 inverted, 0 off by more than 60°",
          ((normals.get("inverted") or [None, None])[1], (normals.get("off_60") or [None, None])[1]), (0, 0))
    old_on = results[("old", "on_offset")]
    print("      old on, offset: bump (mm)", [round(v, 3) for v in old_on["before"]], "→",
          [round(v, 3) for v in old_on["after"]])
    check(f"[4] fails on {OLD[:8]}: the source bump stays > 2 mm", all(v > 2 for v in old_on["after"]), True)

    zero = results[("new", "on_zero")]
    levels = [r.get("source_level") or {} for r in zero["rows"]]
    check("[5] on, no offset: a stub, the own tip replaced", [r["tip_source"] for r in zero["rows"]], ["stub", "stub"])
    check("[5] on, no offset: record bump [>= 3.9, < .3], 0 mm from the source", len(levels) == 2 and all(
        (lv.get("bump_mm") or [0, 9])[0] >= 3.9 and (lv.get("bump_mm") or [0, 9])[1] < .3
        and lv.get("tip_from_source_mm") == 0 for lv in levels), True)
    check(f"[5] fails on {OLD[:8]}: the own tip was kept",
          [r["tip_source"] for r in results[("old", "on_zero")]["rows"]], ["mesh", "mesh"])


part_a()
if "--no-blender" not in sys.argv:
    part_b()
print()
print("ALL OK" if not FAILS else f"{len(FAILS)} FAILED: " + ", ".join(FAILS))
sys.exit(1 if FAILS else 0)
