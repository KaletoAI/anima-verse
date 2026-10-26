"""Write the animal fixtures of `--check animals` (fixtures/README.md "Animals world"): a tiny box quadruped with a
generic skeleton, exported to FBX with the SAME exporter settings as the server's quadruped rig
(app/blender/scripts/quadruped_rig.py: NLA strips as takes, no leaf bones, -Z forward, Y up, texture path stripped),
plus its separate base-colour texture.

  native/fixtures/animals/animal_takes.fbx   three takes: idle, walk, sit (model.clips of the fixtures flags walk
                                             true and sit false; idle carries no flag -> loops)
  native/fixtures/animals/animal_static.fbx  the same rig and mesh without any take (a clip-less rig: procedural gait)
  native/fixtures/animals/animal_basecolor.png  4 x 8 px, texel (column c, row r counted from the TOP) =
                                             RGB(32 + 64 c, 16 + 32 r, 200)

Blender coordinates (metres, Z up, the animal faces -Y):
  body box  x [-0.15, 0.15], y [-0.3, 0.3], z [0.3, 0.5]   UV of every corner (0.375, 0.1875)
  4 legs    x lx +- 0.04, y ly +- 0.04, z rings 0 / 0.05 / 0.15 / 0.3 at (lx, ly) = (+-0.1, +-0.2)
                                                           UV (0.875, 0.4375)
  tail box  x [-0.02, 0.02], y [0.3, 0.4], z [0.43, 0.47]  UV (0.125, 0.8125)
Bones (head -> tail): Body (0, 0.25, 0.4) -> (0, -0.25, 0.4), roll 90 deg; per leg Hip (lx, ly, 0.3) -> (.., 0.05), Paw -> (.., 0)
(connected); Tail (0, 0.3, 0.45) -> (0, 0.4, 0.45). Every vertex weighs 1 on one bone: the body on Body, the tail on
Tail, a leg ring at z > 0.05 on its Hip, the bottom ring on its Paw. Legs: FL (-0.1, -0.2), FR (0.1, -0.2),
BL (-0.1, 0.2), BR (0.1, 0.2). Length 0.7 m is under 1.5 x the height 0.5 m: the clients' Z-up rule
(`s.z > s.y * 1.5`, figures.ts buildModel) leaves it standing (README "Animals world").
Takes (24 fps, frame 1 = 0 s, LINEAR keys, 13 frames = 0.5 s each), rotation about the bone's local axis:
  idle: Tail about Z 0 / 30 deg (frame 7) / 0;  walk: Hip_FL and Hip_BR about X 0 / +20 (4) / 0 (7) / -20 (10) / 0 (13),
  Hip_FR and Hip_BL negated;  sit: Hip_BL and Hip_BR about X 0 -> 60 deg (frame 13).
The exporter bakes every frame of every bone (FBX: about 80 KB per take); three's FBXLoader keeps those 24 fps keys,
Godot's import drops the constant curves and adds samples on its 30 fps grid (fixtures/README.md "Animals world").

Usage (Blender 5.2, the server's version):
  blender --background --factory-startup --python native/tools/animal_fbx.py -- native/fixtures/animals
"""
import math
import os
import sys

import bpy
from bpy_extras import anim_utils

out = sys.argv[sys.argv.index('--') + 1]
os.makedirs(out, exist_ok=True)

LEGS = {'FL': (-0.1, -0.2), 'FR': (0.1, -0.2), 'BL': (-0.1, 0.2), 'BR': (0.1, 0.2)}
W, H = 4, 8


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.context.scene.render.fps = 24
    bpy.context.scene.unit_settings.system = 'METRIC'
    bpy.context.scene.unit_settings.scale_length = 1.0


def texture():
    img = bpy.data.images.new('animal_basecolor', W, H, alpha=False)
    px = []
    for row_from_bottom in range(H):
        r = H - 1 - row_from_bottom          # Blender stores the bottom row first
        for c in range(W):
            px += [(32 + 64 * c) / 255, (16 + 32 * r) / 255, 200 / 255, 1.0]
    img.pixels = px
    img.filepath_raw = os.path.join(out, 'animal_basecolor.png')
    img.file_format = 'PNG'
    img.save()
    return img


def box(verts, faces, x0, x1, y0, y1, zs):
    """A box with horizontal rings at every z of `zs` (bottom to top); returns the new vertex indices."""
    base = len(verts)
    for z in zs:
        verts += [(x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z)]
    n = len(zs)
    faces.append((base + 3, base + 2, base + 1, base + 0))
    for k in range(n - 1):
        a, b = base + 4 * k, base + 4 * (k + 1)
        for i in range(4):
            j = (i + 1) % 4
            faces.append((a + i, a + j, b + j, b + i))
    top = base + 4 * (n - 1)
    faces.append((top + 0, top + 1, top + 2, top + 3))
    return list(range(base, base + 4 * n))


def build(with_takes):
    reset()
    img = texture()
    verts, faces = [], []
    parts = {'Body': box(verts, faces, -0.15, 0.15, -0.3, 0.3, [0.3, 0.5])}
    nbody = len(faces)
    for key, (lx, ly) in LEGS.items():
        parts['Leg_' + key] = box(verts, faces, lx - 0.04, lx + 0.04, ly - 0.04, ly + 0.04, [0, 0.05, 0.15, 0.3])
    nlegs = len(faces)
    parts['Tail'] = box(verts, faces, -0.02, 0.02, 0.3, 0.4, [0.43, 0.47])
    mesh = bpy.data.meshes.new('Animal')
    mesh.from_pydata(verts, [], faces)
    uv = mesh.uv_layers.new(name='UVMap')
    for poly in mesh.polygons:
        at = (0.375, 0.1875) if poly.index < nbody else (0.875, 0.4375) if poly.index < nlegs else (0.125, 0.8125)
        for li in poly.loop_indices:
            uv.data[li].uv = at
    mat = bpy.data.materials.new('Animal basecolor')
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get('Principled BSDF')
    tex = mat.node_tree.nodes.new('ShaderNodeTexImage')
    tex.image = img
    mat.node_tree.links.new(tex.outputs['Color'], bsdf.inputs['Base Color'])
    mesh.materials.append(mat)
    body = bpy.data.objects.new('Animal', mesh)
    bpy.context.collection.objects.link(body)

    arm_data = bpy.data.armatures.new('Rig')
    arm = bpy.data.objects.new('Rig', arm_data)
    bpy.context.collection.objects.link(arm)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode='EDIT')
    eb = arm_data.edit_bones
    # The spine lies along the body with a 90 deg roll, so the hips' parent frame is NOT the world's: the swing axis
    # must really be turned into it (findLegChains' axis.applyQuaternion(parentWorld.invert())).
    b = eb.new('Body'); b.head, b.tail = (0, 0.25, 0.4), (0, -0.25, 0.4); b.roll = math.pi / 2
    for key, (lx, ly) in LEGS.items():
        hip = eb.new('Hip_' + key); hip.head, hip.tail = (lx, ly, 0.3), (lx, ly, 0.05); hip.parent = b
        paw = eb.new('Paw_' + key); paw.head, paw.tail = (lx, ly, 0.05), (lx, ly, 0.0)
        paw.parent = hip; paw.use_connect = True
    t = eb.new('Tail'); t.head, t.tail = (0, 0.3, 0.45), (0, 0.4, 0.45); t.parent = b
    bpy.ops.object.mode_set(mode='OBJECT')

    groups = {name: body.vertex_groups.new(name=name) for name in [bone.name for bone in arm_data.bones]}
    groups['Body'].add(parts['Body'], 1.0, 'REPLACE')
    groups['Tail'].add(parts['Tail'], 1.0, 'REPLACE')
    for key in LEGS:
        for i in parts['Leg_' + key]:
            z = verts[i][2]
            name = ('Hip_' if z > 0.05 else 'Paw_') + key
            groups[name].add([i], 1.0, 'REPLACE')
    body.parent = arm
    mod = body.modifiers.new('Armature', 'ARMATURE')
    mod.object = arm

    takes = []
    if with_takes:
        arm.animation_data_create()

        def take(name, frames, keys):
            """keys: {bone: [(frame, degrees, axis)]}"""
            action = bpy.data.actions.new(name)
            arm.animation_data.action = action
            for pb in arm.pose.bones:
                pb.rotation_mode = 'XYZ'
                pb.rotation_euler = (0, 0, 0)
            for bone, ks in keys.items():
                pb = arm.pose.bones[bone]
                for frame, deg, axis in ks:
                    e = [0.0, 0.0, 0.0]
                    e['XYZ'.index(axis)] = math.radians(deg)
                    pb.rotation_euler = e
                    pb.keyframe_insert('rotation_euler', frame=frame)
            bag = anim_utils.action_get_channelbag_for_slot(action, action.slots[0])
            for fc in bag.fcurves:
                for kp in fc.keyframe_points:
                    kp.interpolation = 'LINEAR'
            # Linear keys: every baked frame lies on the straight segments, so a value between two baked frames whose
            # neighbours are collinear is the plain linear one (hand-derivable) in three's mixer and Godot's import.
            takes.append((name, action, frames))

        swing = lambda s, a: [(1, 0, 'X'), (1 + s, a, 'X'), (1 + 2 * s, 0, 'X'), (1 + 3 * s, -a, 'X'), (1 + 4 * s, 0, 'X')]
        take('idle', 13, {'Tail': [(1, 0, 'Z'), (7, 30, 'Z'), (13, 0, 'Z')]})
        take('walk', 13, {'Hip_FL': swing(3, 20), 'Hip_BR': swing(3, 20), 'Hip_FR': swing(3, -20), 'Hip_BL': swing(3, -20)})
        take('sit', 13, {'Hip_BL': [(1, 0, 'X'), (13, 60, 'X')], 'Hip_BR': [(1, 0, 'X'), (13, 60, 'X')]})
        arm.animation_data.action = None
        for name, action, frames in takes:
            track = arm.animation_data.nla_tracks.new()
            track.name = name
            strip = track.strips.new(name, 1, action)
            strip.name = name
            strip.action_frame_start, strip.action_frame_end = 1, frames
            strip.blend_type = 'REPLACE'
            strip.extrapolation = 'NOTHING'
        for pb in arm.pose.bones:
            pb.rotation_euler = (0, 0, 0)
    bpy.context.scene.frame_start = 1
    bpy.context.scene.frame_end = max((f for _, _, f in takes), default=1)

    bpy.ops.object.select_all(action='DESELECT')
    body.select_set(True)
    arm.select_set(True)
    bpy.context.view_layer.objects.active = arm
    fbx = os.path.join(out, 'animal_takes.fbx' if with_takes else 'animal_static.fbx')
    bpy.ops.export_scene.fbx(filepath=fbx, use_selection=True,
        object_types={'ARMATURE', 'MESH'}, add_leaf_bones=False, bake_anim=bool(takes),
        bake_anim_use_nla_strips=True, bake_anim_use_all_actions=False,
        bake_anim_force_startend_keying=True, bake_anim_step=1.0,
        bake_anim_simplify_factor=0.0, axis_forward='-Z', axis_up='Y',
        path_mode='STRIP', embed_textures=False)
    print('wrote', fbx, os.path.getsize(fbx), 'bytes')


build(True)
build(False)
