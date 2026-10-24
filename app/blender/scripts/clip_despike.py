"""Clears one- and two-frame GLITCHES out of finished library clips — the
repair of clips converted before ``cmu_clip._bake`` ran ``_cmu.despike``
itself (2026-10-24), without converting them again (their window, loop cut
and roll repair stay exactly as they are).

Invoked through ``app.blender.runner.run("clip_despike", inputs=…, params=…,
out_dir=…)``:

    inputs   src            the clip to repair — or ``src_0`` … ``src_n`` for
                            several in one Blender start (a library dry run)
    params   max_deg        the spike threshold (default ``_cmu.SPIKE_DEG``)
             dry_run        measure and report only, write nothing (default
                            False)
             fps            the library's frame rate (default 30)
             max_other_dev_deg  how far a bone may move on a frame NOT
                            repaired, or a bone that was not repaired (and
                            hangs on no repaired bone), between the import
                            and the re-evaluated result (default 0.05)

Per clip ``data["clips"][slot]`` carries ``repaired`` = short bone name ->
repaired frame indices (0-based, as ``_bake`` counts) and ``verify``; a
verification limit that breaks fails the run and declares no file.

What is repaired: every bone's PARENT-relative rotation keys
(``rotation_quaternion``), one series per bone, through the same
``_cmu.despike`` the converter uses — a joint that turns more than the
threshold into a frame and back out of it, landing where it started. Only
that bone's key at that frame changes; what hangs on it follows, nothing
else moves. Track shape and axes are ``cmu_clip``'s (``_export``), so the
file goes back into the library as it came out (``clip_roll`` does the same).
"""
import sys
from pathlib import Path

_SCRIPTS_DIR = str(Path(__file__).parent)
sys.path.insert(0, _SCRIPTS_DIR)
import _cmu                                                   # noqa: E402
import _common                                                # noqa: E402
from _action import curves                                    # noqa: E402
import clip_roll                                              # noqa: E402
import cmu_clip                                               # noqa: E402
sys.path.remove(_SCRIPTS_DIR)

import bpy                                                    # noqa: E402

PREFIX = cmu_clip.PREFIX


def _descendants(arm, names):
    """``names`` plus every bone below one of them."""
    out = set(names)
    for b in arm.data.bones:
        p = b.parent
        while p is not None:
            if p.name in names:
                out.add(b.name)
                break
            p = p.parent
    return out


def _process(slot: str, src: str, args: dict):
    p = args.get("params") or {}
    fps = int(p.get("fps", 30) or 30)
    max_deg = float(p.get("max_deg", _cmu.SPIKE_DEG) or _cmu.SPIKE_DEG)
    dry = bool(p.get("dry_run", False))
    max_other = float(p.get("max_other_dev_deg", 0.05) or 0.05)

    arm = clip_roll._import_armature(src, fps)
    _action, frames = clip_roll._frames_of(arm)
    before = clip_roll._sample(arm, frames)
    fcs = curves(arm)
    repaired = {}
    for pb in arm.pose.bones:
        path = f'pose.bones["{pb.name}"].rotation_quaternion'
        tracks = [fcs.find(path, index=i) for i in range(4)]
        if any(t is None for t in tracks):
            continue
        qs = [[t.evaluate(f) for t in tracks] for f in frames]
        fixed = _cmu.despike(qs, max_deg)
        if not fixed:
            continue
        repaired[pb.name] = fixed
        if dry:
            continue
        for k in fixed:
            f = frames[k]
            for i, t in enumerate(tracks):
                kp = next((x for x in t.keyframe_points if abs(x.co[0] - f) < 1e-6), None)
                if kp is None:
                    kp = t.keyframe_points.insert(float(f), qs[k][i], options={"FAST"})
                kp.co[1] = qs[k][i]
                kp.handle_left[1] = kp.handle_right[1] = qs[k][i]
        for t in tracks:
            t.update()

    data = {"frames": len(frames), "fps": fps, "max_deg": max_deg, "dry_run": dry,
            "repaired": {n[len(PREFIX):] if n.startswith(PREFIX) else n: v
                         for n, v in repaired.items()}}
    reasons = []
    if repaired and not dry:
        # Untouched = every frame that no bone repaired, and on the repaired
        # frames every bone that neither was repaired nor hangs on one.
        got = clip_roll._sample(arm, frames)
        hit = {frames[k] for v in repaired.values() for k in v}
        moved = _descendants(arm, set(repaired))
        quiet = [f for f in frames if f not in hit]
        v = clip_roll._deviation(before, got, quiet) if quiet else {"max_other_rot_deg": 0.0}
        w = clip_roll._deviation(before, got, sorted(hit), skip=moved)
        data["verify"] = {"untouched_frames_max_deg": v["max_other_rot_deg"],
                          "untouched_bones_max_deg": w["max_other_rot_deg"]}
        if v["max_other_rot_deg"] > max_other:
            reasons.append(f"a frame without repair moved {v['max_other_rot_deg']} deg (limit {max_other})")
        if w["max_other_rot_deg"] > max_other:
            reasons.append(f"{w['worst_other_bone']} moved {w['max_other_rot_deg']} deg "
                           f"on a repaired frame without being repaired (limit {max_other})")
    data["limits_ok"] = not reasons
    data["reasons"] = reasons

    out_path = None
    if repaired and not dry and not reasons:
        driven = sorted({fc.data_path.split('"')[1][len(PREFIX):]
                         for fc in curves(arm)
                         if fc.data_path.endswith("rotation_quaternion")
                         and fc.data_path.split('"')[1].startswith(PREFIX)})
        cmu_clip.DRIVEN.clear()
        cmu_clip.DRIVEN.update(driven)
        scene = bpy.context.scene
        scene.render.fps = fps
        scene.frame_start, scene.frame_end = frames[0], frames[-1]
        out_path = Path(args["out_dir"]) / f"{slot}.fbx"
        cmu_clip._export(arm, out_path)
    clip_roll._remove(arm)
    return data, out_path


def run(job):
    args = dict(job)
    inputs = args.get("inputs") or {}
    _common.reset_scene()
    slots = sorted(k for k in inputs if k == "src" or k.startswith("src_"))
    if not slots:
        raise ValueError("no 'src' input")
    clips, outputs, failed = {}, {}, []
    for slot in slots:
        data, out_path = _process(slot, inputs[slot], args)
        clips[slot] = data
        if out_path is not None:
            outputs[slot] = str(out_path)
        if not data["limits_ok"]:
            failed.append(f"{slot}: " + "; ".join(data["reasons"]))
    if failed:
        raise ValueError("despike verification failed — " + " | ".join(failed))
    return {"clips": clips}, outputs


if __name__ == "__main__":
    _common.main(run)
