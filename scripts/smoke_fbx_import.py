#!/usr/bin/env python3
"""Smoke run for the foreign-FBX import inbox (plan-clip-import.md steps 1+3).

Builds a throwaway inbox and two throwaway clip libraries and points
ANIMATION_CLIPS_INBOX_DIR / ANIMATION_CLIPS_DIR / ANIMATION_CLIPS_LICENSED_DIR
at them — the real shared/models/clips*, which hold user-provided binaries
that exist nowhere else, are never touched. Covers app/core/fbx_import.py plus
the four inbox routes in app/routes/assets.py.

The expectations are derived by hand from the four rules the feature rests on:

RULE 1 — "the probe reads NODE NAMES out of the bytes, no Blender". An FBX
keeps its node names as printable ASCII, so a file that contains the four
signature names of a family IS that family:

    contains Hips + Left_UpperLeg + Left_UpperArm + Chest -> unity-humanoid
    contains Hips + LeftUpLeg + LeftForeArm + Spine2      -> mixamo-noprefix
    contains Hips + LeftUpLeg + LeftForeArm + Spine02     -> meshy-biped
    contains only Hips/Bone_01/…                          -> "" (unknown rig)
    + Left_IndexProximal                                  -> has_fingers True
    file name contains tpose/t-pose/rest/bind             -> reference pose

  bone_count counts the family's OWN names found: the synthetic file below
  carries 6 of them (Hips, Chest, Left_UpperLeg, Left_UpperArm, Left_Hand,
  Left_IndexProximal), so bone_count == 6 exactly.

  RULE 1b — the unprefixed Mixamo names are a SUBSTRING of the prefixed ones,
  so "mixamo-noprefix" carries an exclusion: a file whose tokens contain
  "mixamorig:" is never that family, even when the bare signature names are
  in the byte stream too. And what the map does not know is simply not
  counted — MotusMan's Root, hand_*_wep sockets and Leaf*Roll1 twist helpers
  are discarded, not an obstacle to recognition.

  RULE 1c — the SPINE tells the two Mixamo-shaped families apart. Meshy AI
  numbers its spine downwards from the chest (``Spine02`` is the child of the
  hips, ``Spine`` the topmost segment), Mixamo upwards. One token — Spine2 vs
  Spine02 — decides, and neither spelling appears in the other rig, so the
  order the signatures are tried in cannot matter.

  RULE 1d — the probe's byte cap is a shortcut, not a verdict. An ANIMATION
  export writes its skeleton first, so the cap classifies it for the price of
  one chunk; a SKINNED character export writes its mesh first and its
  armature last. A file the capped scan cannot place is therefore read to the
  end instead of being called unknown — and that matters beyond tidiness,
  because that file is exactly the one an admin reaches for as a reference
  pose, and a reference pose whose family is unknown is REFUSED (RULE 6).

  RULE 1e — and it is read in CHUNKS, because an inbox file has no size cap.
  ``MAX_PROBE_BYTES`` is the size of one chunk, not a window followed by a
  single read of the remainder: the scan keeps only the node names some table
  actually asks about, carries a 256-byte overlap into the next chunk, and
  stops at the chunk that identifies the family. Its peak is therefore a
  function of the CHUNK, not of the file. Counting every chunk-sized buffer
  that can be alive at once — the chunk just read, the buffer it was read
  through, the previous chunk (still referenced until that read returns) and
  the copy that prepends the overlap:

      peak <= 4 x MAX_PROBE_BYTES + the known-name set (~130 short strings)

  With the 64 KiB window this check installs, that is at most 4 x 65,536 plus
  a few KB of names — a quarter of a megabyte, whatever the file weighs. The
  fixture below is a 2 MiB file (32 chunks) whose padding is one DISTINCT
  printable token per 16 bytes, so 131,072 of them: reading the remainder in
  one piece would cost 2 x ~2 MiB for the bytes alone, and remembering every
  printable run of the file another ~11 MB for the set. The bound asserted is
  512 KiB — a quarter of the file, twice the derived need, and an order of
  magnitude below either of those. It is a bound on the chunk: it must not
  move when the file grows.

RULE 2 — "a pair is two files whose NAMES say so". Female_/Male_, _A/_B,
__a/__b, _L/_R — and only when the partner really lies in the inbox:

    Female_Dance.fbx  + Male_Dance.fbx      -> partner suggested
    take_A.fbx        + take_B.fbx          -> partner suggested
    Female_Solo.fbx   (no Male_Solo.fbx)    -> "" (no suggestion)

RULE 3 — "a kind is a file stem, and one kind exists once per library and
set". So the import refuses ``__``, path separators and an empty kind (422),
and a kind the target library already has (409) unless overwrite is set.

RULE 4 — "a foreign file is licensed until its owner says otherwise". The
default target is the LICENSED library; the free (tracked, redistributable)
one needs redistributable=True — 400 without it.

RULE 6 — "a reference pose belongs to the rig it is read on". The rest file
is measured on the SOURCE skeleton, so a file from another family puts a
constant offset into every frame that nothing downstream can notice — measured
up to -174 deg on the forearm when the picker offered the Unity `Tpose.fbx`
for the Mixamo-named MOB1 packs. Same for the two halves of a pair. The probe
already knows both families, so both are refused with 422, and the Poses tab
only offers files of the picked file's own family.

  The guard fails CLOSED: a rest file whose family the probe cannot name is
  refused too, exactly like an unclassifiable CLIP file, and BEFORE Blender is
  started. Letting it through would leave the family to ``bone_map: "auto"``
  inside Blender — a late error at best, and at worst a silent retarget
  against the wrong family where the byte probe and Blender disagree.

RULE 5 — "a converted clip is CONTINUOUS". The positional retargeter rebuilds
a bone's roll from an anatomical secondary axis, and the limbs have TWO
candidates: the bend normal (thigh × shin) once the joint is bent far enough to
define it, the pelvis/palm axis while it is straight. Those two axes are
17–40 deg apart on a real skeleton, so any HARD switch between them makes the
roll jump by that much from one frame to the next while the pose itself moved
by less than a degree. The check is therefore a per-frame quaternion step on the
four leg bones of the EXPORTED file (``clip_continuity`` below), with a
two-part, motion-relative verdict:

    a jump = a step above 3 deg/frame that is also more than 4x the clip's own
             90th-percentile step of the same bone

3 deg/frame at 30 fps is 90 deg/s — no relaxed idle moves a thigh that fast —
and the 4x factor is what keeps a genuinely fast clip from tripping the rule:
in a jog the thighs step ~9 deg per frame EVERY frame, so max/p90 stays near 1.
Measured on this very pipeline (Blender 4.2.5, reference.fbx), max leg step and
max/p90 per clip, before and after the roll blend of ``fbx_clip._secondary``:

    MOB1_Stand_Relaxed_Idle_v2   34.75 deg / 163.1   ->   0.91 deg /  3.19
    MOB1_Walk_F_Loop             41.33 deg /   5.89  ->  14.89 deg /  1.60
    MOB1_Jog_F_Loop              29.24 deg /   1.61  ->  29.38 deg /  1.21
    Female_Standing_Lotus_Loop0   6.61 deg /   1.99  ->   6.61 deg /  1.99

The threshold sits in the gap between the two columns: everything healthy stays
below 2.0 (the idle's 3.19 never reaches the 3 deg floor), everything broken is
at 5.89 or above.

The Blender run itself is monkeypatched here: this smoke checks the ROUTE and
core contract (probe, suggestions, validation, target rule, what reaches the
converter), not the retargeter. With ``--real`` it additionally runs one TRUE
pair conversion, if the real inbox holds two Female_/Male_ files plus a
reference pose and Blender is installed.

Usage:
    ./.venv/bin/python scripts/smoke_fbx_import.py [--real]
"""
import argparse
import asyncio
import gc
import json
import os
import shutil
import subprocess
import struct
import sys
import tempfile
import tracemalloc
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

INBOX = Path(tempfile.mkdtemp(prefix="fbx-import-inbox-"))
FIXT = Path(tempfile.mkdtemp(prefix="fbx-import-fixtures-"))
FREE = Path(tempfile.mkdtemp(prefix="fbx-import-free-"))
LICENSED = Path(tempfile.mkdtemp(prefix="fbx-import-licensed-"))
WORLD = Path(tempfile.mkdtemp(prefix="fbx-import-world-"))
# MUST be set before paths is imported — otherwise the smoke would write into
# the repo's real (gitignored, user-provided) libraries.
os.environ["ANIMATION_CLIPS_INBOX_DIR"] = str(INBOX)
os.environ["ANIMATION_CLIPS_DIR"] = str(FREE)
os.environ["ANIMATION_CLIPS_LICENSED_DIR"] = str(LICENSED)

from app.core import paths  # noqa: E402

paths.init(WORLD)

from fastapi import HTTPException  # noqa: E402

from app.blender import runner  # noqa: E402
from app.core import fbx_import  # noqa: E402
from app.routes import assets  # noqa: E402

FAILURES = []

#: The four names a unity-humanoid file must carry, plus two more so the bone
#: count and the finger flag have something to find.
UNITY_NAMES = ("Hips", "Chest", "Left_UpperLeg", "Left_UpperArm",
               "Left_Hand", "Left_IndexProximal")

#: A MocapOnline/MotusMan skeleton: the Mixamo names WITHOUT the prefix. 14
#: core bones + 2 finger roots are in the map (bone_count 16); the four names
#: after them are the rig's extras, which the map discards.
MOB_NAMES = ("Hips", "Spine", "Spine1", "Spine2", "Neck", "Head",
             "LeftShoulder", "LeftArm", "LeftForeArm", "LeftHand",
             "LeftUpLeg", "LeftLeg", "LeftFoot", "LeftToeBase",
             "LeftHandIndex1", "RightHandIndex1",
             "Root", "hand_l_wep", "hand_r_wep", "LeafLeftForeArmRoll1")
MOB_MAPPED = 16

#: A Meshy AI biped: Mixamo's names except for the spine, which Meshy numbers
#: DOWNWARDS from the chest, and a lowercase ``neck``. 12 of these are in the
#: map (bone_count 12); ``head_end`` and ``headfront`` are the rig's extras,
#: which the map discards exactly like MotusMan's sockets. No finger joints
#: exist on this rig at all.
MESHY_NAMES = ("Hips", "Spine", "Spine01", "Spine02", "neck", "Head",
               "LeftShoulder", "LeftArm", "LeftForeArm", "LeftHand",
               "LeftUpLeg", "LeftLeg",
               "head_end", "headfront")
MESHY_MAPPED = 12


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


#: RULE 5 — a step below this many degrees per frame is never a jump, however
#: quiet the rest of the clip is.
JUMP_FLOOR_DEG = 3.0
#: …and above the floor it still needs to stick out this far above the bone's
#: own 90th-percentile step to count as one.
JUMP_OVER_P90 = 4.0

_CONTINUITY_SRC = '''
import json, math, sys
import bpy
from mathutils import Quaternion

path = sys.argv[sys.argv.index("--") + 1:][0]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=path, global_scale=1.0)
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
scene = bpy.context.scene
f0, f1 = int(scene.frame_start), int(scene.frame_end)
for o in bpy.data.objects:
    if o.animation_data and o.animation_data.action:
        r = o.animation_data.action.frame_range
        f0, f1 = int(r[0]), int(r[1])
        break
names = [n for n in ("mixamorig:LeftUpLeg", "mixamorig:LeftLeg",
                     "mixamorig:RightUpLeg", "mixamorig:RightLeg")
         if n in arm.pose.bones]
series = {n: [] for n in names}
for fr in range(f0, f1 + 1):
    scene.frame_set(fr)
    bpy.context.view_layer.update()
    for n in names:
        series[n].append(arm.pose.bones[n].matrix_basis.to_quaternion().normalized())
out = {"frames": f1 - f0 + 1, "bones": {}}
for n, q in series.items():
    steps = []
    for i in range(1, len(q)):
        a, b = q[i - 1], q[i]
        if a.dot(b) < 0:
            b = Quaternion((-b.w, -b.x, -b.y, -b.z))
        d = a.inverted() @ b
        steps.append(math.degrees(2.0 * math.acos(max(-1.0, min(1.0, abs(d.w))))))
    if not steps:
        continue
    st = sorted(steps)
    out["bones"][n] = {"max": max(steps),
                       "p90": st[min(len(st) - 1, int(0.90 * len(st)))],
                       "at_frame": f0 + 1 + steps.index(max(steps))}
print("CONTINUITY_JSON " + json.dumps(out))
'''


def clip_continuity(fbx_path: Path) -> dict:
    """Per-frame quaternion step of the four leg bones of an exported clip.

    Returns ``{"max": deg, "over_p90": ratio, "bone": name, "at_frame": n}``
    for the WORST bone, or ``{}`` when Blender or the file is missing. The
    verdict itself is RULE 5 in the module docstring.
    """
    exe = runner.find_executable()
    if not exe or not Path(fbx_path).is_file():
        return {}
    script = FIXT / "_continuity.py"
    script.write_text(_CONTINUITY_SRC)
    proc = subprocess.run([exe, "-b", "--factory-startup", "-P", str(script),
                           "--", str(fbx_path)],
                          capture_output=True, text=True, timeout=600)
    line = next((ln for ln in proc.stdout.splitlines()
                 if ln.startswith("CONTINUITY_JSON ")), "")
    if not line:
        return {}
    data = json.loads(line.split(" ", 1)[1])
    worst = {}
    for name, b in (data.get("bones") or {}).items():
        ratio = b["max"] / b["p90"] if b["p90"] > 1e-6 else float("inf")
        # the worst bone is the one that comes CLOSEST to the verdict
        score = (b["max"] > JUMP_FLOOR_DEG, ratio)
        if not worst or score > (worst["max"] > JUMP_FLOOR_DEG, worst["over_p90"]):
            worst = {"max": b["max"], "over_p90": ratio, "bone": name,
                     "at_frame": b["at_frame"]}
    return worst


def check_continuity(label: str, fbx_path: Path) -> None:
    """RULE 5 on one exported clip — skipped, not failed, without Blender."""
    w = clip_continuity(fbx_path)
    if not w:
        print(f"  – {label}: continuity not measured (no Blender / no file)")
        return
    detail = (f"max {w['max']:.2f}°/frame on {w['bone'].split(':')[-1]} "
              f"at frame {w['at_frame']}, {w['over_p90']:.2f}× its own p90")
    check(f"{label}: the legs run continuously (RULE 5)",
          not (w["max"] > JUMP_FLOOR_DEG and w["over_p90"] > JUMP_OVER_P90),
          detail)


def status_of(call) -> int:
    """HTTP status a route call ends with (200 when it returns normally)."""
    try:
        call()
        return 200
    except HTTPException as e:
        return e.status_code


def fake_fbx(names, extra: bytes = b"") -> bytes:
    """A byte blob shaped like a binary FBX for the probe: the node names
    separated by the NUL bytes a binary FBX puts between them."""
    body = b"Kaydara FBX Binary  \x00\x1a\x00"
    for name in names:
        body += name.encode() + b"\x00\x01Model\x00"
    return body + extra


#: An Auto-Rig-Pro skeleton: ``.x``/``.l``/``.r`` side suffixes and
#: ``*_stretch`` limb names. 12 of these are in the map (bone_count 12); the
#: four after them are the rig's face controls and its null above the hips,
#: which the map discards exactly like MotusMan's weapon sockets.
ARP_NAMES = ("root.x", "spine_01.x", "spine_02.x", "spine_03.x", "neck.x",
             "head.x", "shoulder.l", "arm_stretch.l", "forearm_stretch.l",
             "hand.l", "thigh_stretch.l", "c_index1.l",
             "Root", "Jaw_ref.x", "eyes_ref.x", "eye_ref.L")
ARP_MAPPED = 12

#: FBX ticks per second — the constant ``fbx_import`` derives a duration with.
FBX_TICKS = 46186158000

#: The take fixture, derived BY HAND from the format: a binary FBX whose
#: ``Objects`` block holds two ``AnimationStack`` nodes. The first runs a full
#: second, the second half of one, so the expected answer is
#: ``[(0, "alpha", 1.0), (1, "beta", 0.5)]`` by construction — 2 takes,
#: because two were written, and those durations because
#: ``(stop - start) / FBX_TICKS`` is what the format says a KTime means.
TAKE_FIXTURE = (("alpha", 0, FBX_TICKS), ("beta", 0, FBX_TICKS // 2))
TAKE_EXPECT = [(0, "alpha", 1.0), (1, "beta", 0.5)]


def _fbx_prop_str(text: str) -> bytes:
    raw = text.encode("utf-8")
    return b"S" + struct.pack("<I", len(raw)) + raw


def _fbx_prop_long(value: int) -> bytes:
    return b"L" + struct.pack("<q", value)


def _fbx_node(name: bytes, props: bytes, nprops: int, kids, start: int) -> bytes:
    """One binary-FBX node at absolute offset ``start``.

    ``kids`` is a list of builders that each take their own start offset — the
    end offset in the header is absolute, so a node can only be written once
    its children's lengths are known.
    """
    body = start + 25 + len(name)
    blob = b""
    pos = body + len(props)
    for build in kids:
        chunk = build(pos)
        blob += chunk
        pos += len(chunk)
    if kids:
        blob += b"\x00" * 25   # the null record that closes a nested list
        pos += 25
    return (struct.pack("<QQQ", pos, nprops, len(props))
            + bytes([len(name)]) + name + props + blob)


def fake_take_fbx(takes, names=()) -> bytes:
    """A binary FBX (version 7500) carrying nothing but ``Objects`` and one
    ``AnimationStack`` per entry of ``takes`` — enough for the take walker,
    and nothing it does not read.

    ``names`` appends rig node names AFTER the structure, where the probe's
    byte scan finds them and the take walker never looks: it stops at
    ``Objects``, the only block that can carry a stack. That is what lets one
    fixture answer both questions — which rig, and how many animations.
    """
    def stack(name: str, start_t: int, stop_t: int):
        def build(off: int) -> bytes:
            def p70(off2: int) -> bytes:
                def one(key: str, value: int):
                    def build_p(off3: int) -> bytes:
                        props = (_fbx_prop_str(key) + _fbx_prop_str("KTime")
                                 + _fbx_prop_str("") + _fbx_prop_str("")
                                 + _fbx_prop_long(value))
                        return _fbx_node(b"P", props, 5, [], off3)
                    return build_p
                return _fbx_node(b"Properties70", b"", 0,
                                 [one("LocalStart", start_t),
                                  one("LocalStop", stop_t)], off2)
            props = (_fbx_prop_long(1234)
                     + _fbx_prop_str(f"{name}\x00\x01AnimStack")
                     + _fbx_prop_str(""))
            return _fbx_node(b"AnimationStack", props, 3, [p70], off)
        return build

    head = b"Kaydara FBX Binary  \x00\x1a\x00" + struct.pack("<I", 7500)
    objects = _fbx_node(b"Objects", b"", 0,
                        [stack(n, a, b) for n, a, b in takes], len(head))
    tail = b"".join(n.encode() + b"\x00\x01Model\x00" for n in names)
    return head + objects + b"\x00" * 25 + tail


#: RULE 1e — the chunked-scan fixture. The probe window is shrunk to
#: ``BIG_CHUNK`` for the check, so a file of ``BIG_SIZE`` is 32 windows wide;
#: the rig signature sits in the MIDDLE of it, on the boundary of chunk
#: ``BIG_BOUNDARY``, with one signature name cut in half by it.
BIG_CHUNK = 64 * 1024
BIG_SIZE = 2 * 1024 * 1024
BIG_BOUNDARY = 16
#: The memory bound derived in RULE 1e: at most four chunk-sized buffers plus
#: the known-name set, so 4 x 64 KiB and a little — twice that is a quarter of
#: the file, and far below the ~4 MiB of bytes (plus ~11 MB of token set) that
#: reading the remainder in one piece would take.
BIG_PEAK_LIMIT = BIG_SIZE // 4


def _pad(n: int, seed: int) -> bytes:
    """Exactly ``n`` bytes of padding, one DISTINCT printable token per 16
    bytes: a scan that remembered every printable run of a file instead of the
    node names it knows would be caught doing it here."""
    buf = bytearray()
    i = seed
    while len(buf) < n:
        buf += b"N%014d\x00" % i
        i += 1
    del buf[n:]
    if buf:
        buf[-1] = 0            # the padding never merges into what follows
    return bytes(buf)


def write_big_fixture(path: Path) -> tuple:
    """Writes the RULE 1e fixture and reports ``(boundary, 7 bytes around
    it)`` so the check can see that the signature name really is cut."""
    body = fake_fbx(MESHY_NAMES)
    cut = body.index(b"Spine02") + 3          # 3 bytes of the name, then the cut
    boundary = BIG_BOUNDARY * BIG_CHUNK
    head = _pad(boundary - cut, 0)
    tail = _pad(BIG_SIZE - len(head) - len(body), 10 ** 6)
    path.write_bytes(head + body + tail)
    with path.open("rb") as fh:
        fh.seek(boundary - 3)
        straddle = fh.read(7)
    return boundary, straddle


def build_inbox() -> None:
    """Six Unity files: a pair (Female_/Male_), an _A/_B pair, a lone Female_
    file, an unknown rig and a reference pose — plus two files of the OTHER
    family, which RULE 6 needs to have something to refuse."""
    for name in ("Female_Dance.fbx", "Male_Dance.fbx", "take_A.fbx",
                 "take_B.fbx", "Female_Solo.fbx"):
        (INBOX / name).write_bytes(fake_fbx(UNITY_NAMES))
    (INBOX / "Tpose.fbx").write_bytes(fake_fbx(UNITY_NAMES))
    for name in ("MOB1_Walk.fbx", "MOB1_Jog.fbx"):
        (INBOX / name).write_bytes(fake_fbx(MOB_NAMES))
    (INBOX / "strange.fbx").write_bytes(fake_fbx(("Bone_01", "Bone_02", "Root")))
    (INBOX / "notes.txt").write_text("not a clip", encoding="utf-8")
    # a library the import can collide with
    (LICENSED / "idle.fbx").write_bytes(b"library-idle")


#: One entry per stand-in Blender run — the kind it was given. A refusal that
#: is supposed to happen BEFORE the converter starts is checked against this.
RUNS: list = []


def fake_run(script, *, inputs=None, params=None, out_dir=None, timeout_s=0):
    """Stands in for the Blender retargeter: writes the files the real script
    writes (``<kind>.fbx`` or the two halves, plus ``<kind>.json``) and reports
    the same result shape. The sidecar echoes what it was handed, so the
    checks can see WHAT reached the converter."""
    kind = (params or {}).get("kind", "x")
    RUNS.append(kind)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    pair = "src_b" in (inputs or {})
    stems = [f"{kind}__a", f"{kind}__b"] if pair else [kind]
    outputs = {}
    for stem in stems:
        p = out / f"{stem}.fbx"
        p.write_bytes(b"fake-" + stem.encode())
        outputs[stem] = str(p)
    side = {"kind": kind, "pair": pair, "script": script,
            "slots": sorted(inputs or {}),
            "rest_name": Path((inputs or {}).get("rest", "")).name,
            "params": dict(params or {})}
    sc = out / f"{kind}.json"
    sc.write_text(json.dumps(side), encoding="utf-8")
    outputs["sidecar"] = str(sc)
    return {"ok": True, "error": "", "data": side, "outputs": outputs,
            "seconds": 0.01}


def imp(body):
    class Req:
        async def json(self):
            return body
    return asyncio.run(assets.post_clips_inbox_import(Req(), None))


def test_probe() -> None:
    print("\n[1] probe — skeleton family out of the bytes (RULE 1)")
    p = fbx_import.probe_fbx(INBOX / "Female_Dance.fbx")
    check("a unity-humanoid file is recognised",
          p["skeleton_family"] == "unity-humanoid", str(p))
    check("bone_count counts the family's own names (6 planted)",
          p["bone_count"] == 6, str(p["bone_count"]))
    check("fingers are seen", p["has_fingers"] is True, str(p))
    check("and it is no reference pose", p["is_rest_candidate"] is False)
    q = fbx_import.probe_fbx(INBOX / "strange.fbx")
    check("an unknown rig stays unknown", q["skeleton_family"] == "", str(q))
    check("with no bones and no fingers",
          q["bone_count"] == 0 and q["has_fingers"] is False, str(q))
    r = fbx_import.probe_fbx(INBOX / "Tpose.fbx")
    check("Tpose.fbx is a reference-pose candidate", r["is_rest_candidate"] is True)
    for name in ("hero_t-pose.fbx", "REST.fbx", "bindpose.fbx", "A-Pose.fbx"):
        check(f"…so is {name}", fbx_import.is_rest_name(name) is True)
    for name in ("walk.fbx", "Female_Dance.fbx"):
        check(f"…and {name} is not", fbx_import.is_rest_name(name) is False)
    missing = fbx_import.probe_fbx(INBOX / "gone.fbx")
    check("a missing file probes to an error, not an exception",
          "error" in missing and missing["skeleton_family"] == "", str(missing))

    print("\n[2] listing")
    entries = fbx_import.inbox_entries()
    names = [e["name"] for e in entries]
    check("only the FBX files are listed, sorted",
          names == ["Female_Dance.fbx", "Female_Solo.fbx", "Male_Dance.fbx",
                    "MOB1_Jog.fbx", "MOB1_Walk.fbx", "strange.fbx",
                    "take_A.fbx", "take_B.fbx", "Tpose.fbx"],
          str(names))
    check("each entry carries size, mtime and the probe",
          all({"name", "size", "mtime", "probe"} <= set(e) for e in entries))
    route = assets.get_clips_inbox(None)
    check("the route adds the pair suggestion per entry",
          all("pair" in e for e in route["entries"]))
    check("and names the reference pose",
          route["rest_suggestion"] == "Tpose.fbx", str(route["rest_suggestion"]))
    check("the inbox directory is the throwaway one",
          route["dir"] == str(INBOX), route["dir"])


def test_families() -> None:
    """Family recognition on throwaway fixtures OUTSIDE the inbox — the probe
    reads a path, so nothing here disturbs the listing above."""
    print("\n[2b] skeleton families (RULE 1 + RULE 1b)")

    def probe(stem, names):
        p = FIXT / f"{stem}.fbx"
        p.write_bytes(fake_fbx(names))
        return fbx_import.probe_fbx(p)

    p = probe("mob1_idle", MOB_NAMES)
    check("the unprefixed Mixamo names are recognised",
          p["skeleton_family"] == "mixamo-noprefix", str(p))
    check(f"bone_count counts only the mapped names ({MOB_MAPPED} planted)",
          p["bone_count"] == MOB_MAPPED, str(p["bone_count"]))
    check("Root / hand_*_wep / Leaf*Roll1 are neither counted nor an obstacle",
          p["bone_count"] == MOB_MAPPED and p["skeleton_family"] == "mixamo-noprefix")
    check("its fingers are seen", p["has_fingers"] is True, str(p))

    q = probe("mixamo_prefixed", tuple("mixamorig:" + n for n in MOB_NAMES))
    check("a PREFIXED Mixamo file is not the unprefixed family",
          q["skeleton_family"] != "mixamo-noprefix", str(q))
    check("…and matches nothing else either", q["skeleton_family"] == "", str(q))

    r = probe("mixed", MOB_NAMES + ("mixamorig:Hips",))
    check("one 'mixamorig:' token disqualifies the family even with the bare "
          "signature present", r["skeleton_family"] == "", str(r))

    u = probe("unity_still_wins", UNITY_NAMES)
    check("the unity-humanoid family is untouched by the new one",
          u["skeleton_family"] == "unity-humanoid" and u["bone_count"] == 6, str(u))

    # RULE 1c — one token separates the two Mixamo-shaped families.
    m = probe("meshy_adventurer", MESHY_NAMES)
    check("a Meshy biped is recognised",
          m["skeleton_family"] == "meshy-biped", str(m))
    check(f"bone_count counts only the mapped names ({MESHY_MAPPED} planted)",
          m["bone_count"] == MESHY_MAPPED, str(m["bone_count"]))
    check("head_end / headfront are neither counted nor an obstacle",
          m["bone_count"] == MESHY_MAPPED and m["skeleton_family"] == "meshy-biped")
    check("a rig without finger joints reports none",
          m["has_fingers"] is False, str(m))
    check("a Meshy file is NOT read as unprefixed Mixamo (Spine02 vs Spine2)",
          m["skeleton_family"] != "mixamo-noprefix", str(m))
    check("…and a MotusMan file is not read as Meshy either",
          probe("mob1_again", MOB_NAMES)["skeleton_family"] == "mixamo-noprefix")

    # RULE 1d — the byte cap is a shortcut, not a verdict. Rather than write a
    # 33 MB fixture, the cap is moved to a handful of bytes: what is tested is
    # the MECHANISM (read on past the cap, and re-scan across the boundary),
    # and that is the same mechanism at 32 MB. A signature name is planted so
    # that it STRADDLES the cap — the case a naive second read would swallow.
    pad_stem = FIXT / "big_character.fbx"
    body = fake_fbx(MESHY_NAMES)
    cut = body.index(b"Spine02") + 3          # the cap falls INSIDE the token
    real_cap = fbx_import.MAX_PROBE_BYTES
    try:
        pad_stem.write_bytes(body)
        fbx_import.MAX_PROBE_BYTES = cut
        # The cached probe would answer from the earlier full-file read.
        fbx_import._probe_cache.pop(str(pad_stem), None)
        big = fbx_import.probe_fbx(pad_stem)
        check("a rig beyond the byte cap is still recognised, not called "
              "unknown", big["skeleton_family"] == "meshy-biped", str(big))
        check("…including a name cut in half by the cap",
              big["bone_count"] == MESHY_MAPPED, str(big["bone_count"]))
        fbx_import.MAX_PROBE_BYTES = len(body) + 1000
        fbx_import._probe_cache.pop(str(pad_stem), None)
        whole = fbx_import.probe_fbx(pad_stem)
        check("…and the answer is the same one the uncapped scan gives",
              whole == big, f"{whole} vs {big}")
    finally:
        fbx_import.MAX_PROBE_BYTES = real_cap
        fbx_import._probe_cache.pop(str(pad_stem), None)

    # RULE 1e — the same mechanism on a file that is REALLY bigger than the
    # window (32 of them), with the signature in the middle and one of its
    # names cut by a chunk boundary. What is measured besides the answer is
    # the memory: the scan must not grow with the file.
    big_file = FIXT / "big_unknown_head.fbx"
    boundary, straddle = write_big_fixture(big_file)
    check("the fixture is bigger than the probe window it is scanned with",
          big_file.stat().st_size == BIG_SIZE and BIG_SIZE > BIG_CHUNK,
          f"{big_file.stat().st_size} bytes / {BIG_CHUNK} per chunk")
    check("…and a signature name really lies across a chunk boundary",
          straddle == b"Spine02" and boundary % BIG_CHUNK == 0,
          f"{straddle!r} at {boundary}")
    tracemalloc.start()
    try:
        fbx_import.MAX_PROBE_BYTES = BIG_CHUNK
        fbx_import._probe_cache.pop(str(big_file), None)
        gc.collect()
        tracemalloc.reset_peak()
        base, _ = tracemalloc.get_traced_memory()
        big2 = fbx_import.probe_fbx(big_file)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
        fbx_import.MAX_PROBE_BYTES = real_cap
        fbx_import._probe_cache.pop(str(big_file), None)
    used = peak - base
    check("a rig 16 chunks into a file is found, not called unknown",
          big2["skeleton_family"] == "meshy-biped", str(big2))
    check("…including the name the boundary cuts in half",
          big2["bone_count"] == MESHY_MAPPED, str(big2["bone_count"]))
    check(f"…and the scan peaks under {BIG_PEAK_LIMIT // 1024} KiB on a "
          f"{BIG_SIZE // 1024} KiB file (RULE 1e)", used < BIG_PEAK_LIMIT,
          f"peak {used / 1024:.1f} KiB")

    # RULE 1f — the Auto-Rig-Pro family. Its node names share no token with
    # any Mixamo-shaped rig, so it can neither absorb nor be absorbed by one.
    a = probe("arp_rig", ARP_NAMES)
    check("an Auto-Rig-Pro skeleton is recognised",
          a["skeleton_family"] == "autorig-pro", str(a))
    check(f"bone_count counts only the mapped names ({ARP_MAPPED} planted)",
          a["bone_count"] == ARP_MAPPED, str(a["bone_count"]))
    check("Root / Jaw_ref.x / eyes_ref.x / eye_ref.L are neither counted nor "
          "an obstacle",
          a["bone_count"] == ARP_MAPPED and a["skeleton_family"] == "autorig-pro")
    check("its three-joint fingers are seen", a["has_fingers"] is True, str(a))
    check("an Auto-Rig-Pro file is read as no Mixamo-shaped family",
          a["skeleton_family"] not in ("mixamo-noprefix", "meshy-biped"), str(a))
    check("…and the other families are untouched by it",
          probe("unity_after_arp", UNITY_NAMES)["skeleton_family"] == "unity-humanoid"
          and probe("mob_after_arp", MOB_NAMES)["skeleton_family"] == "mixamo-noprefix")

    # RULE 1g — the take walker, against a file whose takes were WRITTEN here,
    # so the expectation comes from the construction and not from the output.
    take_file = FIXT / "two_takes.fbx"
    take_file.write_bytes(fake_take_fbx(TAKE_FIXTURE))
    got = fbx_import.fbx_takes(take_file)
    check("both takes are listed, in file order",
          [(g["index"], g["name"], g["duration_s"]) for g in got] == TAKE_EXPECT,
          str(got))
    single = FIXT / "one_take.fbx"
    single.write_bytes(fake_take_fbx(TAKE_FIXTURE[:1]))
    check("a single-take file answers with exactly one entry",
          [(g["index"], g["name"]) for g in fbx_import.fbx_takes(single)]
          == [(0, "alpha")], str(fbx_import.fbx_takes(single)))

    check("the probe reports how many animations a file holds",
          fbx_import.probe_fbx(take_file)["take_count"] == 2
          and fbx_import.probe_fbx(single)["take_count"] == 1)

    not_fbx = FIXT / "plain.fbx"
    not_fbx.write_bytes(b"this is not an FBX at all")
    raised = False
    try:
        fbx_import.fbx_takes(not_fbx)
    except fbx_import.FbxReadError:
        raised = True
    check("a file that is no binary FBX is refused, not guessed at", raised)
    check("…and the probe survives it with take_count 0",
          fbx_import.probe_fbx(not_fbx)["take_count"] == 0)

    # RULE 1h — a multi-take file is REFUSED. Blender assigns only the first
    # stack's action, so importing one without naming a take would silently
    # convert the wrong animation under the name the user asked for.
    (INBOX / "many.fbx").write_bytes(fake_take_fbx(TAKE_FIXTURE, ARP_NAMES))
    fbx_import._probe_cache.pop(str(INBOX / "many.fbx"), None)
    fbx_import._takes_cache.pop(str(INBOX / "many.fbx"), None)
    check("the same file answers both questions — rig and take count",
          fbx_import.probe_fbx(INBOX / "many.fbx")["skeleton_family"] == "autorig-pro"
          and fbx_import.probe_fbx(INBOX / "many.fbx")["take_count"] == 2,
          str(fbx_import.probe_fbx(INBOX / "many.fbx")))
    refused = ""
    try:
        fbx_import.import_fbx("many", ["many.fbx"])
    except Exception as e:      # ClipImportError, by its message
        refused = str(e)
    check("a file with several animations is refused by the importer",
          "2 animations" in refused, refused or "no refusal")

    # The two tables MUST agree — `fbx_clip` imports bpy and cannot be
    # imported here, so its families are read out of the source. A family
    # added there and forgotten here probes as "unknown"; one added here and
    # forgotten there fails inside Blender, halfway through an import.
    import ast
    clip_src = (Path(__file__).resolve().parents[1] / "app" / "blender"
                / "scripts" / "fbx_clip.py").read_text(encoding="utf-8")
    tree = ast.parse(clip_src)
    tables = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name) and tgt.id in ("BONE_MAPS", "SIGNATURES"):
                    tables[tgt.id] = [k.value for k in node.value.keys
                                      if isinstance(k, ast.Constant)]
    check("fbx_clip.BONE_MAPS and fbx_import.SIGNATURES name the same families",
          sorted(tables.get("BONE_MAPS", [])) == sorted(fbx_import.SIGNATURES),
          f"{sorted(tables.get('BONE_MAPS', []))} vs {sorted(fbx_import.SIGNATURES)}")
    check("…and so do the two SIGNATURES tables",
          sorted(tables.get("SIGNATURES", [])) == sorted(fbx_import.SIGNATURES),
          f"{sorted(tables.get('SIGNATURES', []))} vs {sorted(fbx_import.SIGNATURES)}")
    check("every family with a signature has a bone-name mirror",
          all(f in fbx_import.BONE_NAMES for f in fbx_import.SIGNATURES),
          str(sorted(set(fbx_import.SIGNATURES) - set(fbx_import.BONE_NAMES))))

    live = paths.get_shared_dir() / "models" / "clips-inbox" / "MOB1_Stand_Relaxed_Idle_v2.fbx"
    if live.is_file():
        real = fbx_import.probe_fbx(live)
        check("the real MOB1 file probes as mixamo-noprefix with fingers",
              real["skeleton_family"] == "mixamo-noprefix"
              and real["has_fingers"] is True, str(real))
    else:
        print("  – the real MOB1 file is not in the live inbox, skipped")


def test_pairs() -> None:
    print("\n[3] pair suggestion (RULE 2)")
    cases = [
        ("Female_Dance.fbx", "Male_Dance.fbx"),
        ("Male_Dance.fbx", "Female_Dance.fbx"),
        ("take_A.fbx", "take_B.fbx"),
        ("take_B.fbx", "take_A.fbx"),
        ("Female_Solo.fbx", ""),          # no Male_Solo.fbx in the inbox
        ("Tpose.fbx", ""),                # no pattern at all
        ("strange.fbx", ""),
    ]
    for name, want in cases:
        got = fbx_import.pair_suggestion(name)
        check(f"{name} -> {want or '(none)'}", got == want, got or "(none)")
    check("__a/__b is a pattern too (candidate names, no file needed)",
          "hug__b.fbx" in fbx_import.partner_names("hug__a.fbx"),
          str(fbx_import.partner_names("hug__a.fbx")))
    check("…and _L/_R", "cam_r.fbx" in fbx_import.partner_names("cam_L.fbx"),
          str(fbx_import.partner_names("cam_L.fbx")))
    check("the longer suffix wins: __a does not also propose _a -> _b",
          fbx_import.partner_names("hug__a.fbx") == ["hug__b.fbx"],
          str(fbx_import.partner_names("hug__a.fbx")))


def test_path_limits() -> None:
    print("\n[4] path limits — the inbox talks in relative POSIX paths")
    for bad, why in [
        ("../secrets.json", "parent traversal"),
        ("sub/../../x.fbx", "traversal hidden mid-path"),
        ("/etc/walk.fbx", "an absolute path"),
        ("sub\\walk.fbx", "a backslash"),
        ("", "empty"),
        (".hidden.fbx", "a dotfile"),
        (".preview/walk.fbx", "the probe scratch directory"),
        ("sub/.hid/walk.fbx", "a dot segment further in"),
        ("notes.txt", "not a clip extension"),
        ("..", "the parent itself"),
    ]:
        try:
            fbx_import.safe_inbox_name(bad)
            check(f"rejected: {why}", False, repr(bad))
        except fbx_import.ClipImportError:
            check(f"rejected: {why}", True, repr(bad))
    check("a plain name passes",
          fbx_import.safe_inbox_name("Female_Dance.fbx") == "Female_Dance.fbx")
    check("a subdirectory passes",
          fbx_import.safe_inbox_name("pack/female/walk.fbx")
          == "pack/female/walk.fbx")
    check("an empty segment collapses",
          fbx_import.safe_inbox_name("pack//female/walk.fbx")
          == "pack/female/walk.fbx")
    check("the DELETE route answers 400 on a path, not a traversal",
          status_of(lambda: assets.delete_clips_inbox("../x.fbx", None)) == 400)

    print("\n[5] an inbox file is in NO library")
    listing = assets.list_animation_clips()
    names = {c["filename"] for c in listing["clips"]}
    check("the clip listing holds only the library clip",
          names == {"idle.fbx"}, str(sorted(names)))
    check("and the clip route does not reach into the inbox",
          assets.resolve_clip_path("Female_Dance.fbx") is None
          or not assets.resolve_clip_path("Female_Dance.fbx").is_file())


def test_import() -> None:
    print("\n[6] import validation (RULE 3 + RULE 4)")
    real_run = runner.run
    fbx_import.runner.run = fake_run
    try:
        for kind, why in [("dance__a", "the pair role separator"),
                          ("a/b", "a path separator"),
                          ("", "empty"),
                          ("dance.fbx", "an extension")]:
            code = status_of(lambda: imp({"kind": kind, "files": ["Female_Dance.fbx"]}))
            check(f"422 for kind {kind!r} — {why}", code == 422, str(code))
        check("422 for an unknown rig",
              status_of(lambda: imp({"kind": "odd", "files": ["strange.fbx"]})) == 422)
        check("422 for a file that is not in the inbox",
              status_of(lambda: imp({"kind": "x", "files": ["gone.fbx"]})) == 422)
        check("422 for three files",
              status_of(lambda: imp({"kind": "x", "files": ["a.fbx", "b.fbx", "c.fbx"]})) == 422)
        check("400 when files is not a list",
              status_of(lambda: imp({"kind": "x", "files": "Female_Dance.fbx"})) == 400)
        check("400 for the free library without 'redistributable' (RULE 4)",
              status_of(lambda: imp({"kind": "dance", "files": ["Female_Dance.fbx"],
                                     "target": "free"})) == 400)
        check("422 for an unknown target",
              status_of(lambda: imp({"kind": "dance", "files": ["Female_Dance.fbx"],
                                     "target": "public"})) == 422)
        check("409 for a kind the licensed library already has",
              status_of(lambda: imp({"kind": "idle", "files": ["Female_Dance.fbx"]})) == 409)

        print("\n[7] a solo import — licensed by default")
        res = imp({"kind": "resting", "files": ["Female_Dance.fbx"],
                   "start_s": 0.5, "end_s": 3.0, "loop_s": 1.5, "in_place": True})
        check("the clip landed in the LICENSED library",
              (LICENSED / "resting.fbx").is_file() and (LICENSED / "resting.json").is_file())
        check("and NOT in the free one", not (FREE / "resting.fbx").exists())
        check("the answer names the target", res["target"] == "licensed", str(res["target"]))
        check("its url carries the licensed/ prefix",
              res["clip"]["url"] == "/assets/animation-clips/licensed/resting.fbx",
              str(res["clip"]))
        params = res["sidecar"]["params"]
        check("the window, the loop and in_place reached the converter",
              params["start_s"] == 0.5 and params["end_s"] == 3.0
              and params["loop_s"] == 1.5 and params["in_place"] is True, str(params))
        check("the family is detected by the converter itself (bone_map auto)",
              params["bone_map"] == "auto", str(params["bone_map"]))
        check("30 fps out", params["fps"] == 30, str(params["fps"]))
        check("the source file name travels into the sidecar",
              params["source_name"] == ["Female_Dance.fbx"], str(params["source_name"]))
        check("no rest file was passed",
              res["sidecar"]["slots"] == ["rig", "src"], str(res["sidecar"]["slots"]))
        check("and the library now offers the kind",
              "resting" in assets.list_animation_clips()["kinds"])

        print("\n[8] the reference pose reaches inputs['rest']")
        res = imp({"kind": "resting2", "files": ["Female_Dance.fbx"],
                   "rest_file": "Tpose.fbx"})
        check("the rest slot is filled",
              res["sidecar"]["slots"] == ["rest", "rig", "src"],
              str(res["sidecar"]["slots"]))
        check("with the file that was named",
              res["sidecar"]["rest_name"] == "Tpose.fbx",
              res["sidecar"]["rest_name"])
        check("and the answer reports it", res["rest_file"] == "Tpose.fbx",
              str(res["rest_file"]))
        check("422 for a reference pose that is not in the inbox",
              status_of(lambda: imp({"kind": "resting3", "files": ["Female_Dance.fbx"],
                                     "rest_file": "nope.fbx"})) == 422)

        print("\n[8b] a reference pose has to be the SAME RIG (RULE 6)")
        check("422 for a Unity reference pose under a Mixamo clip",
              status_of(lambda: imp({"kind": "mob-rest", "files": ["MOB1_Walk.fbx"],
                                     "rest_file": "Tpose.fbx"})) == 422)
        check("422 for two pair halves of different rigs",
              status_of(lambda: imp({"kind": "mob-pair",
                                     "files": ["MOB1_Walk.fbx",
                                               "Female_Dance.fbx"]})) == 422)
        before = len(RUNS)
        code = status_of(lambda: imp({"kind": "rest-unknown",
                                      "files": ["Female_Dance.fbx"],
                                      "rest_file": "strange.fbx"}))
        check("422 for a reference pose whose rig cannot be named at all "
              "— the guard fails CLOSED", code == 422, str(code))
        check("…and Blender was never started for it",
              len(RUNS) == before, f"{len(RUNS) - before} run(s)")
        res = imp({"kind": "mob-ok", "files": ["MOB1_Walk.fbx"],
                   "rest_file": "MOB1_Jog.fbx"})
        check("but the same family goes through",
              res["sidecar"]["rest_name"] == "MOB1_Jog.fbx",
              res["sidecar"]["rest_name"])

        print("\n[9] a pair import — both halves, one kind")
        res = imp({"kind": "resting-pair", "files": ["Female_Dance.fbx", "Male_Dance.fbx"],
                   "rest_file": "Tpose.fbx", "in_place": True, "loop_s": 2.0})
        check("both halves were written",
              (LICENSED / "resting-pair__a.fbx").is_file()
              and (LICENSED / "resting-pair__b.fbx").is_file())
        check("the answer flags it as a pair", res["pair"] is True)
        check("the A file first, the partner second",
              res["sidecar"]["params"]["source_name"]
              == ["Female_Dance.fbx", "Male_Dance.fbx"],
              str(res["sidecar"]["params"]["source_name"]))
        check("in_place is ignored for a pair (the roots carry the contact)",
              res["sidecar"]["params"]["in_place"] is False)
        check("so is the loop cut",
              res["sidecar"]["params"]["loop_s"] is None,
              str(res["sidecar"]["params"]["loop_s"]))
        check("the two source slots are src_a/src_b",
              res["sidecar"]["slots"] == ["rest", "rig", "src_a", "src_b"],
              str(res["sidecar"]["slots"]))
        check("the library sees ONE pair kind",
              assets.list_animation_clips()["pair_kinds"] == ["resting-pair"],
              str(assets.list_animation_clips()["pair_kinds"]))
        check("422 for a pair of the same file twice",
              status_of(lambda: imp({"kind": "twin",
                                     "files": ["Female_Dance.fbx", "Female_Dance.fbx"]})) == 422)

        print("\n[10] overwrite, set and the free library")
        check("409 without the flag",
              status_of(lambda: imp({"kind": "resting", "files": ["Female_Dance.fbx"]})) == 409)
        again = imp({"kind": "resting", "files": ["Female_Dance.fbx"], "overwrite": True})
        check("200 with it", again["kind"] == "resting")
        res = imp({"kind": "resting", "files": ["Female_Dance.fbx"], "set": "female"})
        check("the same kind is free again in another set",
              (LICENSED / "female" / "resting.fbx").is_file())
        check("its url carries the set segment",
              res["clip"]["url"] == "/assets/animation-clips/licensed/female/resting.fbx",
              str(res["clip"]["url"]))
        res = imp({"kind": "free-take", "files": ["take_A.fbx"],
                   "target": "free", "redistributable": True})
        check("with redistributable the clip goes into the FREE library",
              (FREE / "free-take.fbx").is_file() and res["target"] == "free")
        check("and its url has no licensed/ prefix",
              res["clip"]["url"] == "/assets/animation-clips/free-take.fbx",
              str(res["clip"]["url"]))
    finally:
        fbx_import.runner.run = real_run


def test_delete() -> None:
    print("\n[11] delete")
    (INBOX / "throwaway.fbx").write_bytes(fake_fbx(UNITY_NAMES))
    check("it is listed", "throwaway.fbx" in [e["name"] for e in fbx_import.inbox_entries()])
    r = assets.delete_clips_inbox("throwaway.fbx", None)
    check("the route removes it", r["removed"] is True and not (INBOX / "throwaway.fbx").exists())
    r = assets.delete_clips_inbox("throwaway.fbx", None)
    check("deleting it again is no error, just removed=False", r["removed"] is False)


def test_real() -> None:
    """One TRUE pair conversion out of the REAL inbox — only when Blender and
    the files are there. Expectations from the measurement of 2026-08-21 with
    the local pair (two FBX with a Female_/Male_ prefix) plus the reference
    pose that lies beside them."""
    print("\n[12] real pair conversion out of the live inbox")
    st = runner.status()
    live = paths.get_shared_dir() / "models" / "clips-inbox"
    files = sorted(p.name for p in live.glob("*.fbx")) if live.is_dir() else []
    female = [n for n in files if n.lower().startswith("female_")]
    male = [n for n in files if n.lower().startswith("male_")]
    rest = [n for n in files if fbx_import.is_rest_name(n)]
    rig = paths.get_rig_file()
    if not (st["executable"] and female and male and rest and rig.is_file()):
        print(f"  – skipped (blender={bool(st['executable'])}, pair={bool(female and male)}, "
              f"reference pose={bool(rest)}, rig={rig.is_file()})")
        return
    # The live inbox, but a THROWAWAY target: nothing is written into a library.
    os.environ["ANIMATION_CLIPS_INBOX_DIR"] = str(live)
    fbx_import._probe_cache.clear()
    try:
        # The project's reference skeleton — the same file an import in
        # production picks (``cmu_import.default_rig()``); it lives outside
        # the libraries, so the throwaway target does not hide it.
        res = fbx_import.import_fbx("smoketest-pair", [female[0], male[0]],
                                    rest_file=rest[0], target="licensed",
                                    out_dir=LICENSED / "real", rig=rig,
                                    overwrite=True)
    finally:
        os.environ["ANIMATION_CLIPS_INBOX_DIR"] = str(INBOX)
        fbx_import._probe_cache.clear()
    side = res["sidecar"]
    check("both halves were written",
          (LICENSED / "real" / "smoketest-pair__a.fbx").is_file()
          and (LICENSED / "real" / "smoketest-pair__b.fbx").is_file())
    check("the sidecar says pair", side.get("pair") is True, str(side.get("pair")))
    src = side.get("source") or {}
    check("the bone map was detected", src.get("bone_map") == "unity-humanoid",
          str(src.get("bone_map")))
    check("fingers came along", src.get("fingers") is True, str(src.get("fingers")))
    check("the reference pose put it in rest-delta mode",
          src.get("rotation_mode") == "rest-delta", str(src.get("rotation_mode")))
    geo = side.get("geometry") or {}
    dist = geo.get("root_distance_m")
    check("the two roots stand 0.15–0.30 m apart (measured 0.22)",
          isinstance(dist, (int, float)) and 0.15 <= dist <= 0.30, str(dist))
    floor = geo.get("rig_floor_min_cm")
    check("no figure sinks through the floor (rig_floor_min_cm > -1)",
          isinstance(floor, (int, float)) and floor > -1.0, str(floor))
    for role in ("a", "b"):
        check_continuity(f"half {role}", LICENSED / "real" / f"smoketest-pair__{role}.fbx")
    print(f"  · {res['seconds']:.1f} s, files {res['outputs']}")


def test_real_mob1() -> None:
    """One TRUE solo conversion of the MocapOnline idle out of the REAL inbox.
    Expectations from the measurement of 2026-08-31 (Blender 4.2.5 LTS,
    reference.fbx): bone_map ``mixamo-noprefix``, fingers, 185 frames /
    6.167 s at 30 fps, ``hips_scale`` 1.1905 (the source rig is shorter than
    the reference: 113.03 cm hip height in the bind pose, 112.2 cm standing
    after the retarget), ``rig_floor_shift_cm`` 0.23, ``rig_floor_min_cm``
    -0.02 — the feet stand ON the floor, nothing is crouching or sunken.

    If the pack's rig/T-pose file (``MotusMan_v55.fbx``) lies beside it, the
    same conversion is run again WITH it as the reference pose, which must put
    the converter into rest-delta mode without changing the geometry numbers:
    positions come from the animation either way, only the roll changes —
    measured 0.23–0.26 cm at the hands, 0.00 cm at head and feet.
    """
    print("\n[13] real solo conversion — MocapOnline / MotusMan")
    st = runner.status()
    live = paths.get_shared_dir() / "models" / "clips-inbox"
    src = "MOB1_Stand_Relaxed_Idle_v2.fbx"
    rig = paths.get_rig_file()
    if not (st["executable"] and (live / src).is_file() and rig.is_file()):
        print(f"  – skipped (blender={bool(st['executable'])}, "
              f"file={(live / src).is_file()}, rig={rig.is_file()})")
        return
    rest = "MotusMan_v55.fbx" if (live / "MotusMan_v55.fbx").is_file() else None
    os.environ["ANIMATION_CLIPS_INBOX_DIR"] = str(live)
    fbx_import._probe_cache.clear()
    try:
        res = fbx_import.import_fbx("smoketest-mob1", [src], target="licensed",
                                    out_dir=LICENSED / "mob1", rig=rig,
                                    overwrite=True)
        res_rest = (fbx_import.import_fbx("smoketest-mob1-rest", [src],
                                          rest_file=rest, target="licensed",
                                          out_dir=LICENSED / "mob1", rig=rig,
                                          overwrite=True) if rest else None)
    finally:
        os.environ["ANIMATION_CLIPS_INBOX_DIR"] = str(INBOX)
        fbx_import._probe_cache.clear()
    side = res["sidecar"]
    source, geo = side.get("source") or {}, side.get("geometry") or {}
    check("the clip was written",
          (LICENSED / "mob1" / "smoketest-mob1.fbx").is_file())
    check("the new bone map was detected",
          source.get("bone_map") == "mixamo-noprefix", str(source.get("bone_map")))
    check("fingers came along", source.get("fingers") is True, str(source.get("fingers")))
    dur = side.get("duration_s")
    check("the idle is 5–8 s long (measured 6.167)",
          isinstance(dur, (int, float)) and 5.0 <= dur <= 8.0, str(dur))
    scale = (geo.get("hips_scale") or [None])[0]
    check("the hips are scaled 1.0–1.3 (measured 1.1905) — no belly-walking",
          isinstance(scale, (int, float)) and 1.0 <= scale <= 1.3, str(scale))
    floor = geo.get("rig_floor_min_cm")
    check("the feet stand on the floor (|rig_floor_min_cm| < 3)",
          isinstance(floor, (int, float)) and abs(floor) < 3.0, str(floor))
    check("in_place stayed off", geo.get("in_place") is False, str(geo.get("in_place")))
    check_continuity("the relaxed idle", LICENSED / "mob1" / "smoketest-mob1.fbx")
    print(f"  · {res['seconds']:.1f} s, hips_scale {scale}, "
          f"rig_floor_shift_cm {geo.get('rig_floor_shift_cm')}, "
          f"rig_floor_min_cm {floor}, duration {dur} s")
    if res_rest is None:
        print("  – no MotusMan_v55.fbx beside it, reference-pose lane skipped")
        return
    rsrc = (res_rest["sidecar"].get("source") or {})
    rgeo = (res_rest["sidecar"].get("geometry") or {})
    check("with the pack's rig file as reference pose it runs in rest-delta mode",
          rsrc.get("rotation_mode") == "rest-delta", str(rsrc.get("rotation_mode")))
    check("…on the same family", rsrc.get("bone_map") == "mixamo-noprefix",
          str(rsrc.get("bone_map")))
    check("…and the figure still stands on the floor",
          isinstance(rgeo.get("rig_floor_min_cm"), (int, float))
          and abs(rgeo["rig_floor_min_cm"]) < 3.0, str(rgeo.get("rig_floor_min_cm")))
    check_continuity("the rest-delta idle",
                     LICENSED / "mob1" / "smoketest-mob1-rest.fbx")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--real", action="store_true",
                    help="also run one true Blender conversion of the live inbox")
    a = ap.parse_args()
    build_inbox()
    check("ANIMATION_CLIPS_INBOX_DIR is honoured",
          paths.get_clips_inbox_dir() == INBOX, str(paths.get_clips_inbox_dir()))
    check("…and both libraries point at the throwaway dirs",
          paths.get_animation_clips_dir() == FREE
          and paths.get_licensed_clips_dir() == LICENSED)
    test_probe()
    test_families()
    test_pairs()
    test_path_limits()
    test_import()
    test_delete()
    if a.real:
        test_real()
        test_real_mob1()
    print(f"\n{'FAILED: ' + ', '.join(FAILURES) if FAILURES else 'all checks passed'}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        shutil.rmtree(INBOX, ignore_errors=True)
        shutil.rmtree(FIXT, ignore_errors=True)
        shutil.rmtree(FREE, ignore_errors=True)
        shutil.rmtree(LICENSED, ignore_errors=True)
        shutil.rmtree(WORLD, ignore_errors=True)
