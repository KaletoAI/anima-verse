"""Eases the tail of a finished LOOP clip into its head — the repair of loop
clips whose source is gone (Kimodo/Meshy imports), so they cannot be cut
again with the converter's loop search. The same blend the converter bakes
(``cmu_clip._bake`` with ``loop``): the last ``blend_frames`` keys move
toward key 0 with weights 1/(K+1) … K/(K+1) — quaternions slerped per bone,
the hips location lerped — so frame n-1 → frame 0 is continuous when the
clip repeats.

Invoked through ``app.blender.runner.run("clip_loop_blend", inputs=…,
params=…, out_dir=…)``:

    inputs   src            the clip — or ``src_0`` … ``src_n``
    params   blend_frames   K (default ``cmu_clip.LOOP_BLEND_FRAMES``, 8)
             dry_run        measure and report only (default False)
             fps            the library's frame rate (default 30)

Per clip ``data["clips"][slot]`` carries ``seam_before_cm`` / ``seam_after_cm``
(the largest joint distance, hips-relative, between the last and the first
frame) and ``untouched_max_deg`` (frames before the blend window, re-evaluated
against the import — must stay 0). A clip whose untouched frames moved fails
the run; no file is declared then.
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


def _seam_cm(arm, sample, frames) -> float:
    hips = next(b.name for b in arm.data.bones if b.parent is None)
    a, b = sample[frames[0]], sample[frames[-1]]
    ha, hb = a[hips].translation, b[hips].translation
    return max(((a[n].translation - ha) - (b[n].translation - hb)).length for n in a)


def _process(slot: str, src: str, args: dict):
    p = args.get("params") or {}
    fps = int(p.get("fps", 30) or 30)
    k_blend = int(p.get("blend_frames", cmu_clip.LOOP_BLEND_FRAMES) or cmu_clip.LOOP_BLEND_FRAMES)
    dry = bool(p.get("dry_run", False))
    arm = clip_roll._import_armature(src, fps)
    _action, frames = clip_roll._frames_of(arm)
    n = len(frames)
    if n <= 2 * k_blend:
        clip_roll._remove(arm)
        return {"frames": n, "skipped": f"too short for a {k_blend}-frame blend"}, None
    before = clip_roll._sample(arm, frames)
    data = {"frames": n, "blend_frames": k_blend, "dry_run": dry,
            "seam_before_cm": round(_seam_cm(arm, before, frames), 2)}
    fcs = curves(arm)
    if not dry:
        for fc_group in {fc.data_path for fc in fcs}:
            tracks = sorted((fc for fc in fcs if fc.data_path == fc_group),
                            key=lambda fc: fc.array_index)
            vals = [[t.evaluate(f) for t in tracks] for f in frames]
            if fc_group.endswith("rotation_quaternion") and len(tracks) == 4:
                for k in range(k_blend):
                    fi = n - k_blend + k
                    vals[fi] = _cmu._q_blend(vals[fi], vals[0], (k + 1) / (k_blend + 1))
            elif fc_group.endswith("location"):
                for k in range(k_blend):
                    fi = n - k_blend + k
                    w = (k + 1) / (k_blend + 1)
                    vals[fi] = [v * (1 - w) + v0 * w for v, v0 in zip(vals[fi], vals[0])]
            else:
                continue
            for k in range(k_blend):
                fi = n - k_blend + k
                f = frames[fi]
                for i, t in enumerate(tracks):
                    kp = next((x for x in t.keyframe_points if abs(x.co[0] - f) < 1e-6), None)
                    if kp is None:
                        kp = t.keyframe_points.insert(float(f), vals[fi][i], options={"FAST"})
                    kp.co[1] = vals[fi][i]
                    kp.handle_left[1] = kp.handle_right[1] = vals[fi][i]
            for t in tracks:
                t.update()
        after = clip_roll._sample(arm, frames)
        data["seam_after_cm"] = round(_seam_cm(arm, after, frames), 2)
        quiet = frames[:n - k_blend]
        data["untouched_max_deg"] = clip_roll._deviation(before, after, quiet)["max_other_rot_deg"]
    reasons = []
    if not dry and data["untouched_max_deg"] > 0.05:
        reasons.append(f"frames before the blend window moved {data['untouched_max_deg']} deg")
    data["limits_ok"] = not reasons
    data["reasons"] = reasons
    out_path = None
    if not dry and not reasons:
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
        if not data.get("limits_ok", True):
            failed.append(f"{slot}: " + "; ".join(data["reasons"]))
    if failed:
        raise ValueError("loop blend verification failed — " + " | ".join(failed))
    return {"clips": clips}, outputs


if __name__ == "__main__":
    _common.main(run)
