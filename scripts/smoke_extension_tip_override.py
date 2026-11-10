"""Tip suggestion, tip override and colour disc of pair_tip groups.

Usage: .venv/bin/python scripts/smoke_extension_tip_override.py [--python-only]

Python part (no Blender, no world):
[1] validate_tip_override clamps every offset to +-30 mm: up 45 -> 30,
    out -31.5 -> -30, -12/3 stay; mirror copies side 1 onto side 2; the disc
    diameter 5 -> 10 and 70 -> 50, the soft edge -1 -> 0 and 12 -> 10, the
    colour is lower-cased; all defaults (no offset, no mirror, disc off with
    the default look) are None; a bool, a NaN, an unknown key or "#12345"
    raise ValueError.
[2] extension_rig_fingerprint changes with the tip override (and with a 1 mm
    offset change), not for an equal one; pair_tip carries a build number, so
    bumping it changes the fingerprint too.
[3] effective_extension_overrides: an outfit model on the base body
    (base_signature set, no base flag) inherits the base model's tip; its own
    tip wins; a base model and a model without base_signature keep their own.
[4] paint_texels on a 4x4 PNG of (200,100,50): texel (1,2) alpha 128 with
    #ff0000 gives (200*127/255+255*128/255, 100*127/255, 50*127/255) =
    (227.6, 49.8, 24.9) -> (228, 50, 25); every other texel is unchanged.
    No texel -> the input bytes unchanged. A JPEG keeps its quantisation.
[5] Disc off restores the pristine texture: a GLB painted once, then a
    rebuild from the pristine source with the disc off (no mask) leaves the
    base colour byte-equal to the pristine one.

Blender part (headless, the pair wall fixture of smoke_extension_rig_pair_wall
with the spherical caps of smoke_extension_rig_pair_tip: sphere radius
rho=.106, centres (+-.15,-.044,1.4), cap edge radius .09, kind C = both colour
markers rejected -> geometry):
[6] surface_walk on the flat plane y=-.1 (x=.01, z=1.2 lies off both caps):
    up .01, out .005 on side +1 lands on (.015,-.1,1.21), on side -1 on
    (.005,-.1,1.21), exactly (the projected directions are Z and +-X).
[7] Offsets [{up 8}, {out 6}]: side +1 moves 8 mm up, side -1 6 mm away from
    the midline (x decreases). Both placed points lie on the sphere (|p-c|=rho
    within .0002; facet sagitta .0025**2/(8*.106)=7e-6) and their geodesic
    distance rho*angle from the suggestion is 8 / 6 mm within .2 mm; the up
    walk keeps x within .5 mm, the out walk z within .5 mm. The tip bone
    heads sit on the built tips; offset_mm is recorded.
[8] Disc 28 mm, no soft edge, no offset: the texture is 1024 px over .6 m
    (texel .6/1024 = .5859 mm), UV = the planar x/z map, the axis is -Y within
    asin(.0025/.106)=1.35 deg (cos >.9997). Per side the disc covers
    pi*(14/.5859)**2 = 1793.7 texels (+-1.5 % lattice/tilt budget) and its
    centroid (x=(i+.5)/1024*.6-.3, z=1.1+.6*(1-(j+.5)/1024)) is the tip within
    one texel. Soft edge 4 mm: alpha = 255*smooth((14+2-r)/4) for r the x/z
    distance to the tip (within 8/255), 0 beyond 16 mm.
[9] The per-model switch (Python): set_tip_override(enabled=False) stores
    {"enabled": False} next to the kept tip in extension_rig_models[sig]
    [group] — the 3D tab's dict; enabled=True removes the key again, so the
    stored dict, and with it the fingerprint, is the one of before (off
    differs). resolved_extension_groups (declarations Pair -> Tip) drops Tip
    from the enabled list when off, and only then. A non-bool is refused.
    Blender: the fixture built from the enabled list. Off -> no TipLeft /
    TipRight bone and no Tip metrics; on again -> the same tip rows and bone
    heads as the first build, and the same output GLB bytes.
[10] Outfit models on that base (meta base_signature "sig", no base flag):
    with the base on, the outfit's build list is [Pair, Tip] and its stored
    state (fingerprint taken then) is current. Base off -> the outfit's
    effective overrides carry Tip enabled False (reason "Switched off on the
    base body"), an outfit built now gets [Pair] (= [9]'s Blender off build:
    no tip bones), the existing outfit's state is no longer current (stale,
    rebuilt through the usual path), and its own enabled True does not turn
    Tip back on. Base on again -> the overrides, the list and the state are
    the ones of before. Only pair_tip switches are inherited ([3]: Other).
"""
import argparse
import io
import json
import math
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

FAILS = []


def check(label, ok, detail=""):
    print(("  OK   " if ok else "  FAIL ") + label + ("" if ok else f" — {detail}"))
    if not ok:
        FAILS.append(label)


def raises(function, *args):
    try:
        function(*args)
    except ValueError:
        return True
    return False


def png(pixels, size):
    from PIL import Image
    image = Image.new("RGB", size)
    image.putdata(pixels)
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def glb_with(image: bytes, mime: str) -> bytes:
    import struct
    doc = {"asset": {"version": "2.0"}, "meshes": [{"primitives": [{"material": 0}]}],
           "buffers": [{"byteLength": len(image)}], "bufferViews": [{"byteOffset": 0, "byteLength": len(image)}],
           "images": [{"bufferView": 0, "mimeType": mime}], "textures": [{"source": 0}],
           "materials": [{"pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}}]}
    raw = json.dumps(doc).encode()
    raw += b" " * (-len(raw) % 4)
    image += b"\0" * (-len(image) % 4)
    body = struct.pack("<II", len(raw), 0x4e4f534a) + raw + struct.pack("<II", len(image), 0x004e4942) + image
    return b"glTF" + struct.pack("<II", 2, len(body) + 12) + body


SWITCH_IDS = {}


def switch_part():
    """[9] Python half; leaves the enabled lists for the Blender half."""
    from app.core import paths
    paths.init(Path(tempfile.mkdtemp(prefix="tip-switch-")))   # never a real world (profile reads are patched)
    from app.core import extension_rig as er
    from app.core import extension_tip
    import app.models.character as character
    tip = {"offsets": [{"up": 4.0, "out": 0.0}], "mirror": True,
           "disc": {"enabled": True, "color": "#aa5544", "diameter_mm": 20.0, "soft_mm": 2.0}}
    store = {"model3d_opts": {"extension_rig_models": {"sig": {"Tip": {"tip": tip}, "Pair": {"flip": True}}}}}
    before = json.loads(json.dumps(store))
    declared = [{"id": "Pair", "op": "pair_protrusion", "depends_on": None, "chains": [], "params": {}},
                {"id": "Tip", "op": "pair_tip", "depends_on": "Pair", "chains": [], "params": {}}]

    def save(name, profile, **_):
        store.clear()
        store.update(json.loads(json.dumps(profile)))
        return True

    def enabled_ids():
        with patch.object(er, "rig_groups_for", lambda *a, **k: [dict(g) for g in declared]):
            groups = er.resolved_extension_groups("X", profile=store, signature="sig")
        return [g["id"] for g in groups if g["enabled"]]

    def fingerprint():
        return er.extension_rig_fingerprint(declared, er.model_extension_overrides(store, "sig"))

    with patch.object(extension_tip, "_tip_groups", lambda *a, **k: [{"id": "Tip"}]), \
            patch.object(character, "get_character_profile", lambda name: json.loads(json.dumps(store))), \
            patch.object(character, "save_character_profile", save):
        first = fingerprint()
        SWITCH_IDS["on"] = enabled_ids()
        returned = extension_tip.set_tip_override("X", "sig", "Tip", enabled=False)
        model = store["model3d_opts"]["extension_rig_models"]["sig"]
        check("[9] off stored beside the kept tip", model["Tip"] == {"tip": tip, "enabled": False}
              and model["Pair"] == {"flip": True} and returned == tip, model)
        check("[9] off changes the fingerprint", fingerprint() != first)
        SWITCH_IDS["off"] = enabled_ids()
        check("[9] off drops Tip from the build", SWITCH_IDS == {"on": ["Pair", "Tip"], "off": ["Pair"]}, SWITCH_IDS)
        extension_tip.set_tip_override("X", "sig", "Tip", enabled=True)
        check("[9] on again: the stored dict of before", store == before, store)
        check("[9] on again: the fingerprint of before", fingerprint() == first)
        check("[9] a non-bool switch is refused", raises(lambda: extension_tip.set_tip_override(
            "X", "sig", "Tip", enabled="no")))
        outfit_part(er, extension_tip, store, declared)


def outfit_part(er, extension_tip, store, declared):
    """[10] Outfit models on the base "sig" (Python; the Blender build of the
    resulting enabled list is [9]'s)."""
    from app.core import model3d
    outfit_meta = {"source": "base_body", "base_signature": "sig"}
    path = Path("/nonexistent/osig.glb")

    def effective():
        return er.effective_extension_overrides(store, "osig", outfit_meta, declared)

    def enabled_ids():
        with patch.object(er, "rig_groups_for", lambda *a, **k: [dict(g) for g in declared]):
            groups = er.resolved_extension_groups("X", profile=store, signature="osig", overrides=effective())
        return [g["id"] for g in groups if g["enabled"]]

    def current(meta):
        with patch.object(er, "rig_groups_for", lambda *a, **k: [dict(g) for g in declared]):
            return model3d._extension_state_current("X", path, meta)

    built_on = {**outfit_meta, "extension_rig": {"attempted": True, "status": "applied",
                                                 "fingerprint": er.extension_rig_fingerprint(declared, effective())}}
    before = effective()
    check("[10] base on: the outfit builds Tip, its state is current",
          enabled_ids() == ["Pair", "Tip"] and current(built_on))
    extension_tip.set_tip_override("X", "sig", "Tip", enabled=False)
    check("[10] base off: the outfit inherits the switch",
          effective()["Tip"].get("enabled") is False and er.inherited_extension_switches(
              store, "osig", outfit_meta, declared) == {"Tip": {"enabled": False, "reason": er.BASE_OFF_REASON}})
    check("[10] base off: an outfit built now leaves Tip out", enabled_ids() == ["Pair"], enabled_ids())
    check("[10] base off: the existing outfit is stale", not current(built_on))
    models = store["model3d_opts"]["extension_rig_models"]
    models["osig"] = {"Tip": {"enabled": True}}
    check("[10] the outfit's own switch cannot turn it back on", enabled_ids() == ["Pair"], enabled_ids())
    del models["osig"]
    check("[10] a base's own switch is never inherited onto itself",
          er.inherited_extension_switches(store, "sig", {"base": True, "base_signature": "sig"}, declared) == {})
    extension_tip.set_tip_override("X", "sig", "Tip", enabled=True)
    check("[10] base on again: overrides, build list and state as before",
          effective() == before and enabled_ids() == ["Pair", "Tip"] and current(built_on))


def python_part():
    from app.core import extension_rig as er
    from app.core.extension_tip import paint_disc_masks, paint_texels
    from app.core.base_body import base_color_image
    # [1]
    cleaned = er.validate_tip_override({"offsets": [{"up": 45, "out": -31.5}, {"up": -12, "out": 3}],
                                        "disc": {"diameter_mm": 5, "soft_mm": -1, "color": "#ABCDEF"}})
    check("[1] offsets clamped to +-30", cleaned["offsets"] == [{"up": 30.0, "out": -30.0}, {"up": -12.0, "out": 3.0}],
          cleaned)
    check("[1] diameter/soft clamped low, colour lower-cased",
          cleaned["disc"] == {"enabled": False, "color": "#abcdef", "diameter_mm": 10.0, "soft_mm": 0.0}, cleaned)
    high = er.validate_tip_override({"disc": {"enabled": True, "diameter_mm": 70, "soft_mm": 12}})
    check("[1] diameter/soft clamped high", (high["disc"]["diameter_mm"], high["disc"]["soft_mm"]) == (50.0, 10.0), high)
    mirrored = er.validate_tip_override({"offsets": [{"up": 4, "out": -2}, {"up": 9, "out": 9}], "mirror": True})
    check("[1] mirror copies side 1", mirrored["offsets"] == [{"up": 4.0, "out": -2.0}] * 2, mirrored)
    check("[1] defaults are None", er.validate_tip_override(
        {"offsets": [{"up": 0, "out": 0}], "mirror": False, "disc": dict(er.DISC_DEFAULTS)}) is None)
    for bad in ({"offsets": [{"up": True}]}, {"offsets": [{"up": float("nan")}]}, {"tilt": 1},
                {"disc": {"color": "#12345"}}, {"mirror": 1}, {"offsets": [{}, {}, {}]}):
        check(f"[1] rejects {bad}", raises(er.validate_tip_override, bad))
    # [2]
    groups = [{"id": "Tip", "op": "pair_tip", "chains": [], "params": {}}]
    base = er.extension_rig_fingerprint(groups, {})
    tip = er.extension_rig_fingerprint(groups, {"Tip": {"tip": cleaned}})
    moved = json.loads(json.dumps(cleaned))
    moved["offsets"][0]["up"] = 29.0
    check("[2] tip override changes the fingerprint", tip != base)
    check("[2] equal override, equal fingerprint", tip == er.extension_rig_fingerprint(
        groups, {"Tip": {"tip": json.loads(json.dumps(cleaned))}}))
    check("[2] a 1 mm offset change changes it", er.extension_rig_fingerprint(groups, {"Tip": {"tip": moved}}) != tip)
    with patch.dict(er.OP_BUILDS, pair_tip=er.OP_BUILDS["pair_tip"] + 1):
        check("[2] pair_tip build number is part of it", er.extension_rig_fingerprint(groups, {}) != base)
    # [3]
    profile = {"model3d_opts": {"extension_rig_models": {
        "basesig": {"Tip": {"tip": cleaned}, "Other": {"enabled": False}},
        "own": {"Tip": {"tip": mirrored, "enabled": False}}}}}
    decl = [{"id": "Tip", "op": "pair_tip"}, {"id": "Other", "op": "pair_protrusion"}]
    check("[3] outfit inherits the base tip (not Other's switch)", er.effective_extension_overrides(
        profile, "outfit", {"base_signature": "basesig"}, decl) == {"Tip": {"tip": cleaned}})
    check("[3] own tip wins", er.effective_extension_overrides(
        profile, "own", {"base_signature": "basesig"}, decl) == {"Tip": {"tip": mirrored, "enabled": False}})
    check("[3] a base keeps its own", er.effective_extension_overrides(
        profile, "outfit", {"base_signature": "basesig", "base": True}, decl) == {})
    check("[3] no base_signature, own only", er.effective_extension_overrides(profile, "outfit", {}, decl) == {})
    # [4]
    pristine = png([(200, 100, 50)] * 16, (4, 4))
    painted, count = paint_texels(pristine, "image/png", [{"size": [4, 4], "texels": [1, 2, 128], "color": "#ff0000"}])
    from PIL import Image
    with Image.open(io.BytesIO(painted)) as image:
        pixels = [image.convert("RGB").getpixel((x, y)) for y in range(4) for x in range(4)]
    check("[4] blended texel", pixels[2 * 4 + 1] == (228, 50, 25) and count == 1, pixels[2 * 4 + 1])
    check("[4] others unchanged", all(p == (200, 100, 50) for i, p in enumerate(pixels) if i != 9))
    check("[4] no texel -> same bytes", paint_texels(pristine, "image/png", [{"size": [4, 4], "texels": [],
                                                                           "color": "#ff0000"}]) == (pristine, 0))
    jpeg = io.BytesIO()
    Image.new("RGB", (32, 32), (180, 140, 120)).save(jpeg, format="JPEG", quality=70)
    jpeg_painted, _ = paint_texels(jpeg.getvalue(), "image/jpeg", [{"size": [32, 32], "texels": [3, 3, 255],
                                                                    "color": "#000000"}])
    with Image.open(io.BytesIO(jpeg.getvalue())) as a, Image.open(io.BytesIO(jpeg_painted)) as b:
        check("[4] JPEG keeps its quantisation tables", a.quantization == b.quantization)
    switch_part()
    # [5]
    with tempfile.TemporaryDirectory(prefix="tip-disc-") as tmp:
        path = Path(tmp) / "model.glb"
        source = glb_with(pristine, "image/png")
        path.write_bytes(source)
        on = [{"id": "Tip", "op": "pair_tip", "tip_override": {"disc": {"enabled": True, "color": "#ff0000"}}}]
        metrics = paint_disc_masks(path, on, {"Tip": {"placement": [], "disc_mask": {
            "size": [4, 4], "texels": [0, 0, 255, 3, 3, 255], "pixels": 2}}})
        check("[5] mask replaced by a summary", "disc_mask" not in metrics["Tip"]
              and metrics["Tip"]["disc"]["status"] == "applied" and metrics["Tip"]["disc"]["texture_pixels"] == 2,
              metrics)
        check("[5] disc painted", base_color_image(path.read_bytes())[0] != pristine)
        path.write_bytes(source)   # the rebuild starts from the clean source
        off = [{"id": "Tip", "op": "pair_tip", "tip_override": {"disc": {"enabled": False}}}]
        metrics = paint_disc_masks(path, off, {"Tip": {"placement": []}})
        check("[5] disc off -> base colour byte-equal to pristine",
              base_color_image(path.read_bytes())[0] == pristine and "disc" not in metrics["Tip"])


PROBE = r'''
import hashlib
fixture('C')
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
tp.update(subdivide_radii=[2.4,1.8,1.],normal_radius=2.,fill_radius=1.7,fill_ring=.7,fill_blend=.3,
 fill_depth=.03,fill_tolerance=.012,fill_rms_max=.0015,tip_diameter=.009,tip_length=.005,tip_round=.6,
 tip_wall=.0015,tip_band=.009,tip_subdivide=.009,weight_depth=.015,test_scale=[1.4,1.6,1.4])
tip_group=dict(id='Tip',op='pair_tip',depends_on='Pair',params=tp,tip_override=job['params'].get('override'),
 chains=[[dict(bone='TipLeft',parent='ExampleLeft')],[dict(bone='TipRight',parent='ExampleRight')]])
case=job['params']['case']; out={}
if case=='walk':
 nearest=scope['surface_nearest']([obj])
 out['plane']=[list(scope['surface_walk'](nearest,Vector((.01,-.1,1.2)),side,.01,.005)[0]) for side in (1,-1)]
scope['_common'].reset_scene=lambda:None
scope['_common'].import_model=lambda path:None
ids=job['params'].get('enabled_ids')
groups=[g for g in (tip_group,group) if ids is None or g['id'] in ids]
result,outputs=scope['extension_bones']({'params':{'groups':groups},'inputs':{'model':'fixture'},'out_dir':str(Path(job['result']).parent)})
assert result['status']=='applied',result
out['bones']=sorted(b.name for b in arm.data.bones)
model=(outputs or {}).get('model')
out['model_sha']=hashlib.sha256(Path(model).read_bytes()).hexdigest() if model and Path(model).exists() else None
out['has_tip_metrics']='Tip' in result['metrics']
if out['has_tip_metrics']:
 metrics=result['metrics']['Tip']
 out['tip_source']=metrics['tip_source']
 out['rows']=[{k:row[k] for k in ('suggested','placed','tip','axis','offset_mm')} for row in metrics['placement']]
 out['heads']=[list(arm.data.bones[name].head_local) for name in ('TipLeft','TipRight')]
 out['disc']=metrics.get('disc_mask')
Path(job['result']).write_text(json.dumps({'ok':True,'data':out,'outputs':{}}))
'''


def blender_part():
    from app.blender import runner
    from smoke_extension_rig_pair_wall import PROBE as WALL_PROBE
    if not runner.status()['executable']:
        check("Blender executable available", False, "no Blender: the Blender checks did not run")
        return
    prefix = WALL_PROBE[:WALL_PROBE.index("for kind in ('A','B','C','D','E'):")]
    prefix = prefix.replace("r2=(dx/.06)**2+(dz/.09)**2\n    y=-.1-.05*max(0.,1-r2)**.5",
                            "q=.106**2-dx*dx-dz*dz\n    y=min(-.1,-.044-math.sqrt(q)) if q>=0 else -.1")
    prefix = prefix.replace("assert abs(s['reach'][0]-s['reach'][2])>.01, s", "assert s['marker_area']>0, s")
    rho = .106

    def run(root, label, params):
        source = runner.SCRIPTS_DIR / 'extension_bones.py'
        with patch.object(runner, 'SCRIPTS_DIR', root):
            result = runner.run('probe', params={'source': str(source), **params}, out_dir=root / label, timeout_s=300)
        assert result['ok'], (label, result)
        return result['data']

    with tempfile.TemporaryDirectory(prefix='tip-override-') as tmp:
        root = Path(tmp)
        (root / 'probe.py').write_text(prefix + PROBE)
        # [6] + [7]
        data = run(root, 'walk', {'case': 'walk', 'override': {'offsets': [{'up': 8, 'out': 0}, {'up': 0, 'out': 6}]}})
        for got, want in zip(data['plane'], ([.015, -.1, 1.21], [.005, -.1, 1.21])):
            check(f"[6] plane walk -> {want}", max(abs(a - b) for a, b in zip(got, want)) < 1e-6, got)
        check("[7] tip_source geometry", data['tip_source'] == 'geometry', data['tip_source'])
        for index, (sign, distance, row, head) in enumerate(zip((1, -1), (.008, .006), data['rows'], data['heads'])):
            centre = [sign * .15, -.044, 1.4]
            s, p = row['suggested'], row['placed']
            radial = math.dist(p, centre)
            a = [v - c for v, c in zip(s, centre)]
            b = [v - c for v, c in zip(p, centre)]
            cosine = sum(x * y for x, y in zip(a, b)) / (math.hypot(*a) * math.hypot(*b))
            geodesic = rho * math.acos(max(-1., min(1., cosine)))
            check(f"[7] side {sign}: placed on the sphere", abs(radial - rho) < .0002, radial)
            check(f"[7] side {sign}: geodesic {distance * 1000:.0f} mm", abs(geodesic - distance) < .0002, geodesic)
            if sign == 1:
                check("[7] up walk: z up, x kept", p[2] - s[2] > .007 and abs(p[0] - s[0]) < .0005, (s, p))
            else:
                check("[7] out walk: x away from the midline, z kept", s[0] - p[0] > .005 and abs(p[2] - s[2]) < .0005,
                      (s, p))
            check(f"[7] side {sign}: offset recorded", row['offset_mm'] == ([8., 0.] if sign == 1 else [0., 6.]),
                  row['offset_mm'])
            check(f"[7] side {sign}: bone head on the built tip", math.dist(head, row['tip']) < 1e-4)
            check(f"[7] side {sign}: built tip near the placed point", math.dist(row['tip'], p) < .001)
        # [8]
        texel = .6 / 1024
        for soft in (0, 4):
            data = run(root, f'disc{soft}', {'case': 'disc', 'override': {
                'disc': {'enabled': True, 'color': '#ff0000', 'diameter_mm': 28, 'soft_mm': soft}}})
            disc = data['disc']
            check(f"[8] soft {soft}: mask size", disc['size'] == [1024, 1024], disc['size'])
            texels = [disc['texels'][i:i + 3] for i in range(0, len(disc['texels']), 3)]
            for sign, row in zip((1, -1), data['rows']):
                tip = row['tip']
                mine = [(x, y, a) for x, y, a in texels if (x + .5) / 1024 * .6 - .3 > 0] if sign == 1 else \
                    [(x, y, a) for x, y, a in texels if (x + .5) / 1024 * .6 - .3 < 0]
                pos = [((x + .5) / 1024 * .6 - .3, 1.1 + .6 * (1 - (y + .5) / 1024), a) for x, y, a in mine]
                if soft == 0:
                    expected = math.pi * (.014 / texel) ** 2
                    check(f"[8] side {sign}: {len(mine)} texels ~ {expected:.1f}",
                          abs(len(mine) - expected) < .015 * expected, len(mine))
                    cx = sum(p[0] for p in pos) / len(pos)
                    cz = sum(p[1] for p in pos) / len(pos)
                    check(f"[8] side {sign}: centroid on the tip", math.hypot(cx - tip[0], cz - tip[2]) < texel,
                          (cx, cz, tip))
                else:
                    worst = 0
                    for x, z, a in pos:
                        r = math.hypot(x - tip[0], z - tip[2])
                        t = max(0., min(1., (.016 - r) / .004))
                        worst = max(worst, abs(a - 255 * t * t * (3 - 2 * t)))
                    beyond = [p for p in pos if math.hypot(p[0] - tip[0], p[1] - tip[2]) > .016 + texel]
                    check(f"[8] side {sign}: soft edge alpha within 8/255", worst <= 8, worst)
                    check(f"[8] side {sign}: nothing beyond 16 mm", not beyond, len(beyond))
        # [9]
        override = {'offsets': [{'up': 4, 'out': 0}], 'mirror': True,
                    'disc': {'enabled': True, 'color': '#aa5544', 'diameter_mm': 20, 'soft_mm': 2}}
        builds = {label: run(root, f'switch-{label}', {'case': 'switch', 'override': override,
                                                       'enabled_ids': SWITCH_IDS[key]})
                  for label, key in (('on', 'on'), ('off', 'off'), ('again', 'on'))}
        off = builds['off']
        check("[9] off: no tip bones", not {'TipLeft', 'TipRight'} & set(off['bones']), off['bones'])
        check("[9] off: no tip metrics", not off['has_tip_metrics'])
        check("[9] on: tip bones", {'TipLeft', 'TipRight'} <= set(builds['on']['bones']))
        same = {key: builds['on'].get(key) == builds['again'].get(key) for key in ('rows', 'heads', 'disc', 'bones')}
        check("[9] on again: rows, heads, disc and bones as before", all(same.values()), same)
        if builds['on']['model_sha']:
            check("[9] on again: the same GLB bytes", builds['on']['model_sha'] == builds['again']['model_sha'],
                  (builds['on']['model_sha'], builds['again']['model_sha']))
        else:
            check("[9] the build wrote a GLB", False, "no model output")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--python-only', action='store_true')
    args = parser.parse_args()
    python_part()
    if not args.python_only:
        blender_part()
    print("FAIL" if FAILS else "PASS", f"({len(FAILS)} failed)" if FAILS else "")
    return 1 if FAILS else 0


if __name__ == '__main__':
    sys.exit(main())
