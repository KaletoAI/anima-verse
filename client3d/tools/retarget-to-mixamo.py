"""
Retargeting beliebiger Mocap-Animationen (BVH/FBX) auf das Mixamo-52-Bone-
Skelett — macht Public-Domain-Quellen (z.B. CMU) für unsere Figuren nutzbar.

Aufruf (headless):
  blender --background --python tools/retarget-to-mixamo.py -- \
      --ref  public/models/Idle.fbx \
      --in   <datei.bvh|.fbx|verzeichnis> \
      --out  <ausgabeverzeichnis> \
      [--kind walk]        # Dateiname der Ausgabe: <kind>.fbx statt Quellname

Verfahren: Quell-Skelett laden, Knochen per Namens-Heuristik dem Mixamo-
Skelett zuordnen, Rotationen über Welt-Raum übertragen (kompensiert
abweichende Ruhe-Orientierungen), Hüft-Position auf die Zielgröße skalieren,
Ergebnis als FBX ohne Mesh exportieren — Format-gleich zu Mixamo-Downloads.
"""
import bpy
import sys
import os
import math
from pathlib import Path
from mathutils import Vector, Quaternion

# --- Argumente hinter "--" ---------------------------------------------------
argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
def arg(name, default=None):
    return argv[argv.index(name) + 1] if name in argv else default

REF   = arg('--ref')
INP   = arg('--in')
OUT   = arg('--out', 'out')
KIND  = arg('--kind')
if not REF or not INP:
    raise SystemExit('--ref und --in sind Pflicht')

# Mixamo-Knochen -> Kandidaten-Namen in Mocap-Skeletten (klein geschrieben)
MAP = {
    'Hips':          ['hips', 'pelvis', 'root', 'hip'],
    'Spine':         ['spine', 'lowerback', 'spine1', 'abdomen'],
    'Spine1':        ['spine1', 'spine2', 'upperback', 'chest'],
    'Spine2':        ['spine2', 'spine3', 'thorax', 'chest2'],
    'Neck':          ['neck', 'neck1'],
    'Head':          ['head'],
    'LeftShoulder':  ['leftshoulder', 'lclavicle', 'l_collar', 'lcollar'],
    'LeftArm':       ['leftarm', 'lhumerus', 'l_upperarm', 'lshldr', 'leftupperarm'],
    'LeftForeArm':   ['leftforearm', 'lradius', 'l_forearm', 'lforearm'],
    'LeftHand':      ['lefthand', 'lwrist', 'l_hand', 'lhand'],
    'RightShoulder': ['rightshoulder', 'rclavicle', 'r_collar', 'rcollar'],
    'RightArm':      ['rightarm', 'rhumerus', 'r_upperarm', 'rshldr', 'rightupperarm'],
    'RightForeArm':  ['rightforearm', 'rradius', 'r_forearm', 'rforearm'],
    'RightHand':     ['righthand', 'rwrist', 'r_hand', 'rhand'],
    'LeftUpLeg':     ['leftupleg', 'lfemur', 'l_thigh', 'lhipjoint', 'leftthigh'],
    'LeftLeg':       ['leftleg', 'ltibia', 'l_shin', 'leftshin', 'leftcalf'],
    'LeftFoot':      ['leftfoot', 'lfoot', 'l_foot'],
    'LeftToeBase':   ['lefttoebase', 'ltoes', 'l_toe', 'lefttoe'],
    'RightUpLeg':    ['rightupleg', 'rfemur', 'r_thigh', 'rhipjoint', 'rightthigh'],
    'RightLeg':      ['rightleg', 'rtibia', 'r_shin', 'rightshin', 'rightcalf'],
    'RightFoot':     ['rightfoot', 'rfoot', 'r_foot'],
    'RightToeBase':  ['righttoebase', 'rtoes', 'r_toe', 'righttoe'],
}

def clean(name):
    n = name.lower()
    for p in ('mixamorig:', 'mixamorig', 'bip01_', 'bip_', 'bip01 '):
        n = n.replace(p, '')
    return n.replace('_', '').replace(' ', '').replace(':', '').replace('.', '')

def load(path):
    """Datei laden; gibt das NEU hinzugekommene Armature zurück."""
    before = set(bpy.context.scene.objects)
    ext = Path(path).suffix.lower()
    if ext == '.bvh':
        bpy.ops.import_anim.bvh(filepath=path, rotate_mode='NATIVE',
                                axis_forward='-Z', axis_up='Y',
                                update_scene_fps=False, update_scene_duration=True)
    elif ext == '.fbx':
        bpy.ops.import_scene.fbx(filepath=path, automatic_bone_orientation=False,
                                 ignore_leaf_bones=True)
    else:
        raise SystemExit(f'Format nicht unterstützt: {ext}')
    new_objs = set(bpy.context.scene.objects) - before
    arms = [o for o in new_objs if o.type == 'ARMATURE']
    return arms[0] if arms else None

def retarget(src_path, out_path):
    bpy.ops.wm.read_factory_settings(use_empty=True)

    # 1) Ziel: Mixamo-Skelett (aus Referenz-FBX), vorhandene Animation entfernen
    tgt = load(REF)
    if not tgt:
        raise SystemExit('Kein Armature in der Referenzdatei')
    tgt.name = 'MIXAMO_TARGET'
    tgt.animation_data_clear()
    for o in list(bpy.context.scene.objects):   # Meshes der Referenz weg
        if o.type == 'MESH':
            bpy.data.objects.remove(o, do_unlink=True)

    # 2) Quelle danebenladen
    src = load(src_path)
    if not src or src is tgt:
        raise SystemExit(f'Kein Armature in der Quelle: {src_path}')
    src.name = 'SOURCE'

    scene = bpy.context.scene
    f_start, f_end = int(src.animation_data.action.frame_range[0]), int(src.animation_data.action.frame_range[1])
    scene.frame_start, scene.frame_end = f_start, f_end

    # 3) Knochen-Zuordnung (Ziel-Mixamo-Name -> Quell-Knochen)
    src_by_key = {clean(b.name): b.name for b in src.pose.bones}
    pairs = {}
    for mixamo, candidates in MAP.items():
        for cand in candidates:
            if cand in src_by_key:
                pairs[mixamo] = src_by_key[cand]
                break
    hits = len(pairs)
    print(f'[retarget] {Path(src_path).name}: {hits}/{len(MAP)} Knochen zugeordnet')
    if hits < 12:
        raise SystemExit('Zu wenige Knochen zugeordnet — Namens-Heuristik erweitern (MAP)')

    # 4) Größenverhältnis über die Hüfthöhe in Rest-Pose
    def rest_height(arm, bone_name):
        # Blender ist Z-up; importierte Y-up-Skelette koennen anders liegen —
        # groesste Achse der Welt-Position als "Hoehe" nehmen
        p = arm.matrix_world @ arm.data.bones[bone_name].head_local
        return max(abs(p.x), abs(p.y), abs(p.z))
    tgt_hips_name = next(b.name for b in tgt.pose.bones if clean(b.name) == 'hips')
    src_hips_name = pairs['Hips']
    h_t = rest_height(tgt, tgt_hips_name)
    h_s = rest_height(src, src_hips_name)
    scale = (h_t / h_s) if h_s > 1e-6 else 1.0
    print(f'[retarget]   Hüfthöhe Ziel={h_t:.3f} Quelle={h_s:.3f} -> Skalierung {scale:.4f}')

    # 5) Rest-Welt-Rotationen beider Skelette (Basis für die Umrechnung)
    def rest_world_quat(arm, bone_name):
        return (arm.matrix_world @ arm.data.bones[bone_name].matrix_local).to_quaternion()
    rest_t = {m: rest_world_quat(tgt, next(b.name for b in tgt.pose.bones if clean(b.name) == clean(m)))
              for m in pairs}
    rest_s = {m: rest_world_quat(src, pairs[m]) for m in pairs}
    tgt_name = {m: next(b.name for b in tgt.pose.bones if clean(b.name) == clean(m)) for m in pairs}

    for pb in tgt.pose.bones:
        pb.rotation_mode = 'QUATERNION'

    hips_rest_head = tgt.data.bones[tgt_hips_name].head_local.copy()
    src_hips_rest = src.matrix_world @ src.data.bones[src_hips_name].head_local

    # 6) Frame für Frame: Welt-Rotation der Quelle -> Lokal-Rotation des Ziels
    for f in range(f_start, f_end + 1):
        scene.frame_set(f)
        for mixamo, src_bone in pairs.items():
            sp = src.pose.bones[src_bone]
            src_world = (src.matrix_world @ sp.matrix).to_quaternion()
            delta = src_world @ rest_s[mixamo].inverted()      # Welt-Delta der Quelle
            desired = delta @ rest_t[mixamo]                   # gewünschte Ziel-Welt-Rotation

            tb = tgt.pose.bones[tgt_name[mixamo]]
            parent_world = ((tgt.matrix_world @ tb.parent.matrix).to_quaternion()
                            if tb.parent else tgt.matrix_world.to_quaternion())
            tb.rotation_quaternion = parent_world.inverted() @ desired
            tb.keyframe_insert('rotation_quaternion', frame=f)

        # Hüft-Position: Bewegung relativ zur Rest-Pose, auf Zielgröße skaliert
        sh = (src.matrix_world @ src.pose.bones[src_hips_name].matrix).to_translation()
        offset = (sh - src_hips_rest) * scale
        hb = tgt.pose.bones[tgt_hips_name]
        target_head = hips_rest_head + offset
        hb.location = tgt.data.bones[tgt_hips_name].matrix_local.inverted() @ target_head
        hb.keyframe_insert('location', frame=f)

    # 7) Nur das Ziel-Skelett exportieren (kein Mesh) — Mixamo-kompatible FBX
    bpy.ops.object.select_all(action='DESELECT')
    tgt.select_set(True)
    bpy.context.view_layer.objects.active = tgt
    os.makedirs(Path(out_path).parent, exist_ok=True)
    bpy.ops.export_scene.fbx(
        filepath=str(out_path), use_selection=True, object_types={'ARMATURE'},
        add_leaf_bones=False, bake_anim=True, bake_anim_use_all_bones=True,
        bake_anim_use_nla_strips=False, bake_anim_use_all_actions=False,
        bake_anim_simplify_factor=0.0, armature_nodetype='NULL',
        axis_forward='-Z', axis_up='Y', global_scale=1.0,
    )
    print(f'[retarget] geschrieben: {out_path} ({f_end - f_start + 1} Frames)')

# --- Lauf --------------------------------------------------------------------
inputs = []
p = Path(INP)
if p.is_dir():
    inputs = sorted([f for f in p.iterdir() if f.suffix.lower() in ('.bvh', '.fbx')])
else:
    inputs = [p]

for i, src_file in enumerate(inputs):
    name = (KIND if KIND and len(inputs) == 1 else src_file.stem) + '.fbx'
    retarget(str(src_file), str(Path(OUT) / name))
print(f'[retarget] fertig: {len(inputs)} Datei(en)')
