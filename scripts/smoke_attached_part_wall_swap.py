#!/usr/bin/env python3
"""Skin and inner wall are told apart before the window is flattened, so a wall the skin passed is never skin for the field (Ruling A98).

Usage: ./.venv/bin/python scripts/smoke_attached_part_wall_swap.py
Runs Blender 5.2 on the CPU against a synthetic double-walled body; no world,
no server, no network. Takes a few seconds.

The defect (measured on a stored UniForge body, size 1.45): the flatten moved
the skin under the root by 12.6 mm; 13 skin faces there passed the inner wall
and the outer-skin test, run AFTER the flatten, took them for an inner wall,
while 144 inner-wall faces it had moved along now read as skin. One of them,
facing the hollow (upward) under the body, was the nearest "skin" of every
point of the sweep from 30 % to 90 % of its length: (p - q).n < 0 there, the
skin field took the sweep's middle for the inside of the body, and the union
cut a gash up to 12.3 mm deep across it (the part looked broken in the middle).

Fixture (metres): the outer skin is a closed box x, y in [-.1, .1], z in
[0, .2], every side an 8 x 8 grid (25 mm quads), normals out. The inner wall is
a plate x, y in [-.096, .096] (8 x 8 quads of 24 mm, centres +-.012, +-.036,
+-.06, +-.084), normal +z (facing the hollow), at z .004 as delivered. The
"flatten" then moves the plate to z -.008, through the skin's bottom.

Hand-derived expectations (`_common.enclosed`: the normal ray and the 45 and
70 degree rays to +-u, +-w must all hit the mesh again):
- As delivered: every plate ray goes up into the closed box: all 64 plate
  faces are inner wall, no skin face is (each skin normal ray leaves the box).
  The classification taken then and kept by `refit` holds 64 inner-wall faces.
- After the move, classified again (the old order): a plate face's 70 degree
  ray (.940, 0, .342) climbs the 8 mm to z 0 over .008 / .342 x .940 = 22 mm;
  from a centre at |c| .084 it reaches |x| .106 beyond the box's bottom and
  side, which end at z 0: it leaves. The outer ring, 28 faces, reads as skin.
  A skin face of the bottom sends its rays down onto the plate; the 70 degree
  ray hits it while |c| + .022 <= .096, so the 36 faces with |c| <= .0625 read
  as inner wall: the skin passed by the wall is lost.
- The probe P = (0, 0, -.05), 50 mm under the body, is outside. Old order:
  the nearest skin left is a plate ring face, its point (.072, 0, -.008) at
  sqrt(.072^2 + .042^2) = 83.4 mm, nearer than the skin ring's (.075, 0, 0) at
  90.1 mm; its normal is +z, so (P - q).n = -.042: inside. Kept
  classification: the nearest skin is the bottom's centre, (P - q).n = +.050:
  outside, 50 mm.
- `build_part` builds its OuterSkin before the flatten and refits it after
  (source order), as the fix requires.

Old-code proof: the builder at commit 986a3498b377f8f9689d69f7c6da065d13a5ebc1
builds the OuterSkin after the flatten (source order check fails), which is
the old order measured above (inside, the sign the field cut with).
"""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
BLENDER = Path.home() / 'tools/blender-5.2.2-linux-x64/blender'
OLD_COMMIT = '986a3498b377f8f9689d69f7c6da065d13a5ebc1'


def grid(corner, du, dv, n=8):
    """Vertices and quads of an n x n grid from ``corner`` along du, dv (whole side)."""
    verts = [tuple(corner[k] + du[k] * i / n + dv[k] * j / n for k in range(3)) for i in range(n + 1) for j in range(n + 1)]
    quads = [(i * (n + 1) + j, (i + 1) * (n + 1) + j, (i + 1) * (n + 1) + j + 1, i * (n + 1) + j + 1)
             for i in range(n) for j in range(n)]
    return verts, quads


def blender_side(out_path):
    import bpy
    from mathutils import Vector
    sys.path.insert(0, str(ROOT / 'app/blender/scripts'))
    import _common
    import attached_part
    _common.reset_scene()
    verts, faces = [], []

    def add(corner, du, dv):
        v, q = grid(corner, du, dv)
        base = len(verts)
        verts.extend(v)
        faces.extend(tuple(base + i for i in quad) for quad in q)
    # Box sides; each (du x dv) points out of the box.
    add((-.1, -.1, 0), (0, .2, 0), (.2, 0, 0))      # bottom, -z
    add((-.1, -.1, .2), (.2, 0, 0), (0, .2, 0))     # top, +z
    add((-.1, -.1, 0), (.2, 0, 0), (0, 0, .2))      # front, -y
    add((-.1, .1, 0), (0, 0, .2), (.2, 0, 0))       # back, +y
    add((-.1, -.1, 0), (0, 0, .2), (0, .2, 0))      # left, -x
    add((.1, -.1, 0), (0, .2, 0), (0, 0, .2))       # right, +x
    skin_faces = len(faces)
    skin_verts = len(verts)
    add((-.096, -.096, .004), (.192, 0, 0), (0, .192, 0))   # inner wall, +z
    mesh = bpy.data.meshes.new('body')
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    body = bpy.data.objects.new('body', mesh)
    bpy.context.scene.collection.objects.link(body)
    import bmesh
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.verts.ensure_lookup_table()
    bmesh.ops.remove_doubles(bm, verts=bm.verts[:skin_verts], dist=1e-7)
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    plate = [p.index for p in mesh.polygons if abs(p.center.z - .004) < 1e-6 and abs(p.center.x) < .0961]
    skin_bottom = [p.index for p in mesh.polygons if abs(p.center.z) < 1e-9]
    centre, probe = Vector((0, 0, .1)), Vector((0, 0, -.05))
    kept = attached_part.OuterSkin(body, centre, .25)
    delivered_inner = len(mesh.polygons) - len(kept.index)
    plate_inner = sum(i not in kept.index for i in plate)
    plate_verts = {v for i in plate for v in mesh.polygons[i].vertices}
    for v in plate_verts:
        mesh.vertices[v].co.z = -.008
    mesh.update()
    kept.refit()

    def sign(skin):
        location, normal, index, distance = skin.find_nearest(probe)
        return (probe - location).dot(normal), distance, index
    kept_sign, kept_distance, kept_face = sign(kept)
    again = attached_part.OuterSkin(body, centre, .25)
    again_sign, again_distance, again_face = sign(again)
    Path(out_path).write_text(json.dumps({
        'skin_faces': skin_faces, 'plate_faces': len(plate), 'skin_bottom': len(skin_bottom),
        'delivered_inner': delivered_inner, 'plate_inner_delivered': plate_inner,
        'kept_inner_after': len(mesh.polygons) - len(kept.index),
        'again_plate_skin': sum(i in again.index for i in plate),
        'again_bottom_lost': sum(i not in again.index for i in skin_bottom),
        'kept': [kept_sign, kept_distance, kept_face in plate],
        'again': [again_sign, again_distance, again_face in plate]}))


def source_order(text):
    """Whether build_part builds its OuterSkin before the flatten and refits it after."""
    build = text[text.index('def build_part'):]
    made = build.find('= OuterSkin(')
    flatten = build.find('Flatten the front window')
    written = build.find('bmb.to_mesh(body.data)')
    refit = build.find('bvh.refit()')
    return 0 <= made < flatten < written < refit


def main():
    if '--blender' in sys.argv:
        blender_side(sys.argv[sys.argv.index('--blender') + 1])
        return
    with tempfile.TemporaryDirectory(prefix='attached-part-wall-swap-') as directory:
        out = Path(directory) / 'result.json'
        log = Path(directory) / 'blender.log'
        with log.open('w') as stream:
            result = subprocess.run(['nice', '-n', '15', 'timeout', '300', str(BLENDER), '-b', '-noaudio', '--factory-startup',
                                     '--python-exit-code', '1', '--python', str(Path(__file__).resolve()), '--',
                                     '--blender', str(out)], stdout=stream, stderr=subprocess.STDOUT,
                                    env={**os.environ, 'PYTHONUNBUFFERED': '1'})
        if result.returncode:
            print(log.read_text()[-4000:])
            raise SystemExit(result.returncode)
        data = json.loads(out.read_text())
    problems = []
    if (data['skin_faces'], data['plate_faces'], data['skin_bottom']) != (384, 64, 64):
        problems.append(f'fixture: {data}')
    if data['delivered_inner'] != 64 or data['plate_inner_delivered'] != 64:
        problems.append(f'as delivered {data["delivered_inner"]} inner-wall faces, {data["plate_inner_delivered"]} of them the plate, expected 64 / 64')
    if data['kept_inner_after'] != 64:
        problems.append(f'refit changed the classification: {data["kept_inner_after"]} inner-wall faces')
    kept_sign, kept_distance, kept_on_plate = data['kept']
    if kept_on_plate or abs(kept_sign - .05) > 1e-4 or abs(kept_distance - .05) > 1e-4:
        problems.append(f'kept classification: probe at {kept_sign * 1000:.1f} mm (plate {kept_on_plate}), expected +50.0 mm on the skin')
    again_sign, again_distance, again_on_plate = data['again']
    old_order = (data['again_plate_skin'], data['again_bottom_lost'], again_on_plate, round(again_sign, 4), round(again_distance, 4))
    if old_order != (28, 36, True, -.042, round((.072 ** 2 + .042 ** 2) ** .5, 4)):
        problems.append(f'the old order did not reproduce the defect as derived: {old_order}')
    text = (ROOT / 'app/blender/scripts/attached_part.py').read_text()
    if not source_order(text):
        problems.append('build_part does not build its OuterSkin before the flatten and refit it after')
    assert not problems, problems
    old = subprocess.run(['git', '-C', str(ROOT), 'show', f'{OLD_COMMIT}:app/blender/scripts/attached_part.py'],
                         capture_output=True, text=True, check=True).stdout
    assert not source_order(old), 'the old builder already kept the classification'
    assert not re.search(r'def refit', old)
    print(f'kept classification: probe {kept_sign * 1000:+.1f} mm from the skin; classified again after the move: '
          f'{data["again_plate_skin"]} wall faces read as skin, {data["again_bottom_lost"]} skin faces lost, '
          f'probe {again_sign * 1000:+.1f} mm (inside) at {again_distance * 1000:.1f} mm; old builder {OLD_COMMIT[:9]} '
          'classifies after the flatten')
    print('PASS attached_part wall swap: the skin field keeps the delivered skin and inner wall apart')


if __name__ == '__main__':
    main()
