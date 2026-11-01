#!/usr/bin/env python3
"""Synthetic SOMA BVH conversion smoke, without a server or world database.

Usage: ALSOFT_DRIVERS=null ./.venv/bin/python scripts/smoke_bvh_soma_import.py

Hand-derived expectations: 31 samples at 30 fps span 1 second (the sidecar
may count all samples, within 1/30 s). Reading scene end 250 would be wrong.
The T-pose faces +Z, left +X: hips 92 cm, thigh/shin each 42 cm, ankle
8 cm above the floor and toe 14 cm forward. Absolute local positional
channels repeat those offsets; they must not be added a second time.
Hips move 0 to -30 cm in Z, so keep-mode travel has |x| <= .01 m and
z <= -.25 m. Retargeting straight legs puts hips at the reference rig's
standing height (113.03 cm, allowed 105..120 for floor adjustment), with
height variation <= .5 cm. clip_measure returns metres, so hips are explicitly
converted to centimetres for those bounds. The travel scales with the leg
ratio the importer applies (sidecar hips_scale, measured 1.164), so it must be
-0.30 * hips_scale within 1 cm (measured -0.349). Toe base and toe end sit on
the floor (ankle 8 cm up, toe base 8 cm down), so the lowest foot point is 0;
measured -2.46 cm: the existing despike pass dips the toe on this perfectly
straight synthetic pose (a diagnostic copy without despike gives ~0). The bound
is therefore min_foot_y >= -3 cm — a BVH read with the wrong axes or units
lands decimetres off, far outside it.
All joints and motions below are synthetic; no sample motion is used.
"""
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def write_fixture(path):
    """Write SOMA's hierarchy with six absolute local channels per joint."""
    joints = {}

    def joint(name, parent, offset):
        joints[name] = (parent, offset)

    joint("Root", None, (0, 0, 0))
    joint("Hips", "Root", (0, 92, 0))
    parent = "Hips"
    for name, height in (("Spine1", 12), ("Spine2", 12), ("Chest", 12),
                         ("Neck1", 10), ("Neck2", 4), ("Head", 8), ("HeadEnd", 15)):
        joint(name, parent, (0, height, 0))
        parent = name
    for name, offset in (("Jaw", (0, 0, 4)), ("LeftEye", (3, 5, 5)),
                         ("RightEye", (-3, 5, 5))):
        joint(name, "Head", offset)
    for side, sign in (("Left", 1), ("Right", -1)):
        parent = "Hips"
        for part, offset in (("Leg", (sign * 10, 0, 0)), ("Shin", (0, -42, 0)),
                             ("Foot", (0, -42, 0)), ("ToeBase", (0, -8, 14)),
                             ("ToeEnd", (0, 0, 5))):
            joint(side + part, parent, offset)
            parent = side + part
        parent = "Chest"
        for part, offset in (("Shoulder", (sign * 8, 6, 0)),
                             ("Arm", (sign * 10, 0, 0)),
                             ("ForeArm", (sign * 28, 0, 0)), ("Hand", (sign * 25, 0, 0))):
            joint(side + part, parent, offset)
            parent = side + part
        for finger, forward in (("Thumb", 5), ("Index", 3), ("Middle", 0),
                                ("Ring", -2), ("Pinky", -4)):
            parent = side + "Hand"
            parts = ("1", "2", "3", "End") if finger == "Thumb" else ("1", "2", "3", "4", "End")
            for index, part in enumerate(parts):
                name = side + "Hand" + finger + part
                offset = (sign * (3.2 if index == 0 else 6.3 if index == 1 else 2),
                          0, forward if index == 0 else 0)
                joint(name, parent, offset)
                parent = name
    lines, order = ["HIERARCHY"], []

    def emit(name, depth):
        parent, offset = joints[name]
        indent = "  " * depth
        lines.extend([f"{indent}{'ROOT' if parent is None else 'JOINT'} {name}",
                      indent + "{", indent + "  OFFSET " + " ".join(map(str, offset)),
                      indent + "  CHANNELS 6 Xposition Yposition Zposition Zrotation Xrotation Yrotation"])
        order.append(name)
        for child, (owner, _) in joints.items():
            if owner == name:
                emit(child, depth + 1)
        lines.append(indent + "}")

    emit("Root", 0)
    lines.extend(["MOTION", "Frames: 31", "Frame Time: 0.0333333333333333"])
    for frame in range(31):
        values = []
        for name in order:
            x, y, z = joints[name][1]
            values.extend((x, y, z - frame if name == "Hips" else z, 0, 0, 0))
        lines.append(" ".join(map(str, values)))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    with tempfile.TemporaryDirectory(prefix="smoke-bvh-soma-") as temporary:
        root = Path(temporary)
        for variable, directory in (("ANIMATION_CLIPS_INBOX_DIR", "inbox"),
                                    ("ANIMATION_CLIPS_DIR", "free"),
                                    ("ANIMATION_CLIPS_LICENSED_DIR", "licensed")):
            folder = root / directory
            folder.mkdir()
            os.environ[variable] = str(folder)
        from app.core.fbx_import import import_fbx
        from app.blender import runner

        write_fixture(root / "inbox/soma.bvh")
        result = import_fbx("smoke-soma", [{"name": "soma.bvh"}], root_motion="keep")
        side = result["sidecar"]
        measured = runner.run("clip_measure", inputs={"clip": root / "licensed/smoke-soma.fbx"},
                              timeout_s=900)
        assert measured["ok"], measured
        data = measured["data"]
        hips = [height * 100 for height in data["hips_y"]]
        travel = side["geometry"]["root_motion"]["travel_m"]
        print(f"Measured: travel={travel}, hips_y_cm=[{min(hips)}, {max(hips)}], "
              f"min_foot_y={data['min_foot_y']}, hips_scale={side['geometry']['hips_scale']}", flush=True)
        checks = [
            ("31 frames", side["frames"] == 31),
            ("30 fps (source and output)", side["fps"] == 30 and side["source_fps"] == 30),
            ("one second", abs(side["duration_s"] - 1) <= 1 / 30 + 1e-6),
            ("backward travel", abs(travel[0]) <= .01 and travel[1] <= -.25),
            ("travel = -0.30 m * hips_scale",
             abs(travel[1] + .30 * side["geometry"]["hips_scale"][0]) <= .01),
            ("constant hips", max(hips) - min(hips) <= .5),
            ("standing hips", 105 <= hips[0] <= 120),
            ("foot minimum >= -3 cm", data["min_foot_y"] >= -.03),
        ]
        for label, passed in checks:
            print(f"{'PASS' if passed else 'FAIL'} {label}")
        assert all(passed for _, passed in checks), "SOMA conversion expectations failed"
        print(f"OK smoke_bvh_soma_import: {len(checks)}/{len(checks)} passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
