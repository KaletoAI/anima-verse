#!/usr/bin/env python3
"""Smoke: a heeled shoe's foot pose reaches every viewer of the served figure and survives every clip (Ruling A52).

Usage:  ./.venv/bin/python scripts/smoke_heel_pose.py

No world, no server, no hub: a throwaway storage dir (``paths.init``), the synthetic foot and shoes of
``scripts/_footwear_fixtures.py``, a text scan of the viewer call sites, and one esbuild bundle of
``packages/scene-render/src/footPose.ts`` run in node (section [5]; a missing esbuild or node fails the smoke).

THE DEFECT (Ruling A52, measured on read-only copies of Kira's served outfit model d5320a5297d2 with the Black
Stilettos, fit e4bd2f4eb796: Foot +26.2 / +26.1 deg, ToeBase -26.6 / -26.8 deg, root lift 49.9 mm). A fitted shoe is
bound with its foot turned BACK by the fit's extension (``footwear_fit`` step 7), so only a viewer that applies the
served ``foot_pose`` shows it right. The 3D client did (idle: Foot pitch 25.7 deg, heel tip -0.5 mm, ball -2.5 mm);
the Game-Admin viewers of the SERVED figure — Figure tab, Pose tab, 3D model tab — were never handed the record and
showed the bind pose (heel tip -13 mm, ball -35 mm, i.e. through the floor) or played clips with a bare foot (idle:
Foot -20.5 deg, the shoe's toe 82 mm up, its forepart 28 deg up): "bent upward at the front, the heel ignored".

Expected, by hand:
[1] THE HEEL POSE OF A HEELED SHOE (``footwear_fit.fit_pair`` on the wedge pump and the flat box foot of
    ``smoke_footwear_fit.py``, whose docstring derives the fixed point in full). The foot: heel contact 0.04 behind
    and 0.08 below the ankle (0, 0.08), ball contact at x 0.13 on the floor, heel -> ball d = 0.17, rest pitch 0.
    The shoe: scale k = 0.255 / 0.288062 = 0.88522 (+-2e-4); the heel seat stands 0.09 k = 0.07967 over the ground,
    the forepart 0.01 k = 0.00885, so the heel stands h = 0.08 k = 0.07082 over the ball.
    - pitch: the rigid chord asin(h / d) = asin(0.07082 / 0.17) = 24.62 deg; the fit's fixed point on the SKINNED
      ball shortens it to 24.29 deg (+-0.05) — within 0.4 deg of asin(h / d). ToeBase turns back by the same
      (forepart flat): -24.29. The record's ``foot_pose`` carries both per side.
    - hips: the heel contact sits on the heel seat, so the root goes up by the seat's height less how far the turn
      lifts the heel contact about the ankle: the contact, 0.04 behind and 0.08 below the ankle, turned toe-down by
      24.29 deg sits 0.08 cos - 0.04 sin = 0.07292 - 0.01646 = 0.05646 below it, i.e. 0.08 - 0.05646 = 0.02354 higher
      than at rest -> lift = 0.07967 - 0.02354 = 0.05613 (+-5e-4; k read off the sampled insole, 0.885337, gives
      0.05614); ``foot_pose.root_lift_m`` the same. With the ankle straight over the heel contact the rise would be 0
      and the hips would go up by the full seat height.
[2] A FLAT SHOE gives zero pitch: the closed clog (insole flat at 0.01 raw, k = 1.023599) on the same foot -> chord 0,
    rest 0 -> Foot and ToeBase 0 deg (+-1e-6); the root lift is the sole alone, 0.01 k = 0.010236 (+-1e-5).
[3] THE FIGURE TAB GETS THE SERVED POSE: ``figure_build._served_foot_pose`` returns
    ``garment_assembly.served_foot_pose(name, full, "full")`` of the serving tier's full file (stubs: the file
    ``/x/abc.glb``, the pose {"version": 1, …}) -> that record, with the path and tier passed through; no served
    file -> None; a raising lookup -> None. ``figure_build._figure_info`` (off the pipeline, every other input
    stubbed) carries ``served_foot_pose`` = that record beside ``served_url``.
[4] EVERY VIEWER OF THE SERVED FIGURE PASSES IT (text scan of ``frontend/src``): each ``<Model3DViewer`` whose URL is
    the served figure — ``data.served_url`` (FieldFigure.tsx), ``/model3d/file`` (FieldPose.tsx; FieldModel3D.tsx
    through ``viewerUrl``), all under ``frontend/src/tabs/characters`` — passes ``footPose=`` from the served record (``served_foot_pose`` / ``foot_pose``);
    FieldFigure and FieldPose, which show the still figure, also pass ``clipGroup`` 'ground' when the record is there
    (the floor grid at the bare soles and the root lifted by ``footPoseLiftM``). The Wardrobe's shoe preview keeps its
    ``footPose``. A served-figure viewer found anywhere else without ``footPose`` fails.
[5] A CLIP FRAME KEEPS THE OFFSET (``applyFootPose`` in node; the bone chain of ``smoke_foot_pose.mjs``: Foot at
    (0, 0.08, 0), ToeBase at local (0, -0.06, 0.13), bind identity; a turn by t about +x takes the ToeBase's offset
    (y, z) = (-0.06, 0.13) to (-0.06 cos t - 0.13 sin t, -0.06 sin t + 0.13 cos t)). A one-key clip whose Foot key
    is R(+x, -20 deg) — the idle clip's own dorsiflexion of Kira's foot, -20.5 deg — played:
      record Foot +26 deg -> the net turn -20 + 26 = +6 deg: ToeBase (0, 0.006740, 0.123016)
        (cos 6 = 0.9945219, sin 6 = 0.1045285: y = 0.08 - 0.0596713 - 0.0135887, z = -0.0062717 + 0.1292878);
      no record (the admin viewers before) -> -20 deg: ToeBase (0, 0.068081, 0.142681)
        (cos 20 = 0.9396926, sin 20 = 0.3420201: y = 0.08 - 0.0563816 + 0.0444626, z = 0.0205212 + 0.1221600);
      a flat record (Foot 0 deg) -> the clip's own -20 deg, the same point.
    The still pose (``applyFootPoseToPose``, record +26 deg): ToeBase (0, -0.030916, 0.090541)
      (cos 26 = 0.8987940, sin 26 = 0.4383711); ``footPoseLiftM`` 'ground' = the record's lift, 'seat' = 0.
    All +-1e-6.

FAILS BEFORE / PASSES AFTER — against main before the fix (33d69c57569c82987d949bc3abc46bf039830f67):

    d=$(mktemp -d); git archive 33d69c57569c82987d949bc3abc46bf039830f67 app frontend/src \
        shared/models/rig/joints.json | tar -x -C "$d"
    SMOKE_REPO="$d" ./.venv/bin/python scripts/smoke_heel_pose.py

``SMOKE_REPO`` points [3] (``app`` is imported from there) and [4] (the scan) at that tree; [1], [2] and [5] run the
same code there and pass. It reports 8 failures: [3] ``_served_foot_pose`` missing and the payload without
``served_foot_pose`` (two); [4] the three served-figure viewers without ``footPose`` (three), FieldFigure / FieldPose
without ``clipGroup`` (two) and the stray scan naming those three files (one).
"""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
#: ``SMOKE_REPO``: another checkout whose ``app`` and ``frontend/src`` are checked (the "fails before" proof).
REPO = Path(os.environ.get("SMOKE_REPO") or ROOT)
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(REPO))

FAILS: list[str] = []


def check(ok: bool, label: str) -> None:
    print(("ok   " if ok else "FAIL ") + label)
    if not ok:
        FAILS.append(label)


def near(a, b, tol) -> bool:
    return a is not None and abs(a - b) <= tol


def part_fit() -> None:
    import _footwear_fixtures as fx
    from app.core import footwear_fit as ff
    from app.core import footwear_insole, glb_mesh
    glb = fx.foot_body_glb()
    body, joints = glb_mesh.body_arrays(glb), glb_mesh.joint_bind_matrices(glb)

    print("[1] a heeled shoe")
    P, F = fx.wedge()
    fit = ff.fit_pair(footwear_insole.analyse_arrays(P, F), fx.shoe_garment(P, F), body, joints, width_cap=1.10)
    rec, fp = fit.record, fit.foot_pose
    k = rec["scale"]["k_m_per_unit"]
    h, d = 0.08 * k, 0.17
    rigid = math.degrees(math.asin(h / d))
    check(near(k, 0.88522, 2e-4), f"[1] k {k:.6f} = 0.88522")
    check(near(rigid, 24.62, 0.01), f"[1] asin(h/d) = asin({h:.5f} / 0.17) = {rigid:.3f} deg = 24.62")
    for side in ("left", "right"):
        cap = side.capitalize()
        foot, toe = fp["bones"][f"{cap}Foot"]["deg"], fp["bones"][f"{cap}ToeBase"]["deg"]
        check(near(foot, 24.29, 0.05) and 0 < rigid - foot < 0.4 and near(toe, -foot, 1e-6),
              f"[1] {side}: Foot {foot:.3f} deg (asin(h/d) {rigid:.3f} less the skinned-ball 0.33), ToeBase {toe:.3f}")
    t = math.radians(fp["bones"]["LeftFoot"]["deg"])
    lift = 0.09 * k - (0.04 * math.sin(t) - 0.08 * math.cos(t)) - 0.08
    check(near(lift, 0.05614, 5e-4) and near(fp["root_lift_m"], lift, 5e-4) and near(rec["root_lift_m"], fp["root_lift_m"], 1e-9),
          f"[1] hips raised {fp['root_lift_m']:.5f} m = heel seat {0.09 * k:.5f} - heel rise about the ankle "
          f"{0.09 * k - lift:.5f} = {lift:.5f}")

    print("[2] a flat shoe")
    P, F = fx.clog()
    flat = ff.fit_pair(footwear_insole.analyse_arrays(P, F), fx.shoe_garment(P, F), body, joints, width_cap=1.10)
    bones = flat.foot_pose["bones"]
    check(all(near(bones[f"{c}{b}"]["deg"], 0.0, 1e-6) for c in ("Left", "Right") for b in ("Foot", "ToeBase")),
          f"[2] flat clog: every foot turn 0 ({sorted((n, v['deg']) for n, v in bones.items())})")
    check(near(flat.foot_pose["root_lift_m"], 0.010236, 1e-5),
          f"[2] flat clog: the hips go up by the sole only, {flat.foot_pose['root_lift_m']:.6f} = 0.010236")


def part_payload() -> None:
    print("[3] the Figure tab's payload")
    from app.core import figure_build, garment_assembly, model3d
    if not hasattr(figure_build, "_served_foot_pose"):
        check(False, "[3] figure_build._served_foot_pose exists")
        check(False, "[3] the figure payload carries served_foot_pose")
        return
    pose = {"version": 1, "source": {"item_id": "i", "fsig": "f", "glb_sha256": "x"}, "bones": {}, "root_lift_m": 0.05}
    seen: list = []
    saved = (model3d.find_model3d_serving_tier, garment_assembly.served_foot_pose)
    try:
        model3d.find_model3d_serving_tier = lambda name, sig: (Path("/x/abc.glb"), None, None)
        garment_assembly.served_foot_pose = lambda name, path, tier="full": (seen.append((name, path, tier)) or pose)
        got = figure_build._served_foot_pose("demo")
        check(got is pose and seen == [("demo", Path("/x/abc.glb"), "full")],
              f"[3] the served full file's record, path and tier passed through ({seen})")
        model3d.find_model3d_serving_tier = lambda name, sig: (None, None, None)
        check(figure_build._served_foot_pose("demo") is None, "[3] no served file -> None")

        def boom(name, sig):
            raise OSError("unreadable")
        model3d.find_model3d_serving_tier = boom
        check(figure_build._served_foot_pose("demo") is None, "[3] a raising lookup -> None")
        model3d.find_model3d_serving_tier = lambda name, sig: (Path("/x/abc.glb"), None, None)
        stubs = {"on_pipeline": lambda name, profile=None: False, "auto_build_on": lambda name, profile=None: False,
                 "_served_url": lambda name: "/u", "_served_built_at": lambda name: None,
                 "cost": lambda name, steps=None: {}}
        from app.core import model_refs
        old = {key: getattr(figure_build, key) for key in stubs}
        old_h = model_refs.is_humanoid
        try:
            for key, fn in stubs.items():
                setattr(figure_build, key, fn)
            model_refs.is_humanoid = lambda name, profile=None: True
            info = figure_build._figure_info("demo", profile={}, build={})
        finally:
            for key, fn in old.items():
                setattr(figure_build, key, fn)
            model_refs.is_humanoid = old_h
        check(info.get("served_foot_pose") is pose and info.get("served_url") == "/u",
              "[3] the figure payload carries served_foot_pose beside served_url")
    finally:
        model3d.find_model3d_serving_tier, garment_assembly.served_foot_pose = saved


#: file -> (what marks its viewer as the served figure, the foot pose expression it must pass, clipGroup expected)
SITES = {
    "FieldFigure.tsx": ("data.served_url", "data.served_foot_pose", True),
    "FieldPose.tsx": ("/model3d/file", "model.foot_pose", True),
    "FieldModel3D.tsx": ("viewerUrl", "model.foot_pose", False),
}


def viewer_blocks(text: str):
    """Every ``<Model3DViewer …/>`` element's source (to its first ``/>``)."""
    for m in re.finditer(r"<Model3DViewer\b", text):
        end = text.find("/>", m.start())
        yield text[m.start():end + 2]


def part_sites() -> None:
    print("[4] the viewers of the served figure")
    base = REPO / "frontend/src/tabs/characters"
    for name, (marker, expr, group) in SITES.items():
        text = (base / name).read_text(encoding="utf-8")
        blocks = [b for b in viewer_blocks(text) if marker in b]
        check(len(blocks) == 1, f"[4] {name}: one served-figure viewer ({len(blocks)})")
        block = blocks[0] if blocks else ""
        check(re.search(r"footPose=\{\s*" + re.escape(expr), block) is not None, f"[4] {name}: footPose={{{expr} …}}")
        if group:
            check(re.search(re.escape(expr) + r"\s*\?\s*'ground'", block.split("clipGroup=", 1)[-1]) is not None
                  and "clipGroup=" in block, f"[4] {name}: clipGroup 'ground' when the record is there")
    ward = (base / "WardrobeGarment.tsx").read_text(encoding="utf-8")
    check(any("footPose=" in b for b in viewer_blocks(ward)), "[4] WardrobeGarment.tsx: the shoe preview keeps footPose")
    stray = []
    for path in sorted(base.rglob("*.tsx")):   # a character's served model: only the Characters tab shows one
        for block in viewer_blocks(path.read_text(encoding="utf-8")):
            if ("served_url" in block or "/model3d/file" in block or "viewerUrl" in block) and "footPose=" not in block:
                stray.append(path.name)
    check(not stray, f"[4] no served-figure viewer without footPose ({stray})")


TS = r"""
import * as THREE from %(three)s
import { applyFootPose, applyFootPoseToPose, footPoseLiftM } from %(footpose)s
const chain = () => {
  const root = new THREE.Group()
  const foot = new THREE.Bone(); foot.name = 'mixamorigLeftFoot'; foot.position.set(0, 0.08, 0)
  const toe = new THREE.Bone(); toe.name = 'mixamorigLeftToeBase'; toe.position.set(0, -0.06, 0.13)
  foot.add(toe); root.add(foot); root.updateMatrixWorld(true)
  return { root, toe }
}
const record = (deg) => ({ version: 1, source: { item_id: 'i', fsig: 'f', glb_sha256: 'x' },
  bones: { 'mixamorig:LeftFoot': { axis: [1, 0, 0], deg } }, root_lift_m: 0.056139, contacts: { left: [], right: [] } })
const q = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), -20 * Math.PI / 180)
const clip = new THREE.AnimationClip('idle', 1, [new THREE.QuaternionKeyframeTrack('mixamorigLeftFoot.quaternion', [0],
  [q.x, q.y, q.z, q.w])])
const play = (fp) => {
  const { root, toe } = chain()
  const mixer = new THREE.AnimationMixer(root)
  mixer.clipAction(fp === undefined ? clip : applyFootPose(THREE, clip, fp)).play()
  mixer.setTime(0); root.updateMatrixWorld(true)
  return toe.getWorldPosition(new THREE.Vector3()).toArray()
}
const still = () => {
  const { root, toe } = chain()
  applyFootPoseToPose(THREE, root, record(26)); root.updateMatrixWorld(true)
  return toe.getWorldPosition(new THREE.Vector3()).toArray()
}
console.log(JSON.stringify({ heeled: play(record(26)), bare: play(undefined), none: play(null), flat: play(record(0)),
  still: still(), liftGround: footPoseLiftM(record(26), 'ground'), liftSeat: footPoseLiftM(record(26), 'seat') }))
"""


def part_clip() -> None:
    print("[5] a clip frame keeps the offset")
    esbuild = next((ROOT / p for p in ("node_modules/.bin/esbuild", "client3d/node_modules/.bin/esbuild",
                                       "frontend/node_modules/.bin/esbuild") if (ROOT / p).exists()), None)
    if esbuild is None or shutil.which("node") is None:
        check(False, "[5] esbuild and node available")
        return
    with tempfile.TemporaryDirectory() as tmp:
        entry, bundle = Path(tmp) / "heel.mjs", Path(tmp) / "heel.bundle.mjs"
        entry.write_text(TS % {"three": json.dumps(str(ROOT / "node_modules/three/build/three.module.js")),
                               "footpose": json.dumps(str(ROOT / "packages/scene-render/src/footPose.ts"))})
        built = subprocess.run([str(esbuild), str(entry), "--bundle", "--platform=node", "--format=esm",
                                "--log-level=error", f"--outfile={bundle}"], cwd=ROOT, capture_output=True, text=True)
        if built.returncode != 0:
            print(built.stderr)
            check(False, "[5] bundle")
            return
        run = subprocess.run(["node", str(bundle)], cwd=ROOT, capture_output=True, text=True)
    try:
        got = json.loads((run.stdout.strip().splitlines() or [""])[-1])
    except ValueError:
        print(run.stdout, run.stderr)
        check(False, "[5] run")
        return

    def at(p, want):
        return all(abs(a - b) <= 1e-6 for a, b in zip(p, want))
    check(at(got["heeled"], (0, 0.006740, 0.123016)), f"[5] clip -20 + record 26 = +6 deg: ToeBase {got['heeled']}")
    check(at(got["bare"], (0, 0.068081, 0.142681)) and at(got["none"], got["bare"]),
          f"[5] no record: the clip's -20 deg, ToeBase {got['none']}")
    check(at(got["flat"], got["bare"]), f"[5] flat record (0 deg): the clip unchanged, ToeBase {got['flat']}")
    check(at(got["still"], (0, -0.030916, 0.090541)), f"[5] still pose +26 deg: ToeBase {got['still']}")
    check(near(got["liftGround"], 0.056139, 1e-9) and got["liftSeat"] == 0,
          f"[5] lift ground {got['liftGround']}, seat {got['liftSeat']}")


def main() -> int:
    tmp = tempfile.mkdtemp(prefix="smoke_heel_pose_")
    try:
        from app.core import paths
        paths.init(tmp)
        part_fit()
        part_payload()
        part_sites()
        part_clip()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{'OK' if not FAILS else f'{len(FAILS)} FAILED'}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
