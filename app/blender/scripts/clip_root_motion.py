"""Applies a ROOT-MOTION mode to a baked library clip — the importer's last
pass before export (``cmu_clip.run_takes``) and a measuring job of its own.

    strip      the hips stay at the origin (Mixamo "In Place"); the pass only
               measures how far the planted feet slide (``max_drift_cm``)
    keep       the recorded travel stays (scaled by the leg ratio in _bake);
               the pass measures it
    foot_lock  the take arrives STRIPPED; the pass rebuilds the hips' XZ from
               the foot contacts (``_root_motion.foot_lock_path``), writes it
               into the root track and verifies that no planted point moves
               more than MAX_LOCK_DRIFT_CM

Invoked as a runner job (``measure_only``) on a finished FBX:
    inputs   rig, src     params  fps, measure_only=True
Returns the measurement of the file as it is (see ``run``) and writes nothing.

The contact heights come from the REST POSE OF THE REFERENCE RIG, in the pass
and in the measuring job alike. A clip FBX carries no bind pose (``cmu_clip.
_export``), so the rest Blender builds when it imports one is not the rig's —
its RightFoot came back at 10.79 cm instead of 7.32 — and a measurement taken
from it clamps the grounds differently, weights other frames as planted and
reports another number for the very same keys (111_11 from 1.533 s: 0.97 cm in
the pass, 2.83 cm "in the file", with the joint tracks equal within 0.001 cm).
"""
import sys
from pathlib import Path

_SCRIPTS_DIR = str(Path(__file__).parent)
sys.path.insert(0, _SCRIPTS_DIR)
import _common                                                # noqa: E402
import _root_motion as rm                                     # noqa: E402
from _clip_scene import sample, write_root                    # noqa: E402
sys.path.remove(_SCRIPTS_DIR)

from mathutils import Matrix, Vector                          # noqa: E402

# cmu_clip.PREFIX — not imported from there: cmu_clip imports this module.
PREFIX = "mixamorig:"
MAX_LOCK_DRIFT_CM = 1.5


def _frames(arm):
    act = arm.animation_data.action
    f0, f1 = act.frame_range
    return act, list(range(int(round(f0)), int(round(f1)) + 1))


def _tracks(arm, joints, frames):
    out = {}
    for p in rm.CONTACT_POINTS:
        bone = PREFIX + p
        if bone in arm.pose.bones:
            out[p] = [tuple(joints[f][bone][0]) for f in frames]
    return out


def _rest_heights(arm):
    """Per contact point its head height in the REST pose over the rest's
    lowest foot point, cm — and the rig's standing height, m."""
    heads = {b.name: b.head_local for b in arm.data.bones}
    feet = [heads[PREFIX + n].y for n in rm.CONTACT_POINTS + ("LeftToe_End", "RightToe_End")
            if PREFIX + n in heads]
    floor = min(feet) if feet else 0.0
    rest = {p: heads[PREFIX + p].y - floor for p in rm.CONTACT_POINTS if PREFIX + p in heads}
    top = max(h.y for h in heads.values()) if heads else floor
    return rest, (top - floor) / 100.0


def _contacts(arm, joints, frames, fps, rest=None):
    """Contact tracks and weights of the CURRENT action, plus the rig's
    standing height (m). ``rest`` = ``_rest_heights`` of the reference rig;
    omitted, ``arm``'s own rest is used (the pass: ``arm`` IS the rig)."""
    tracks = _tracks(arm, joints, frames)
    rest_h, ref_height_m = rest or _rest_heights(arm)
    weights = rm.contact_weights(tracks, rm.ground_heights(tracks, rest_h), fps)
    return tracks, weights, ref_height_m


def apply(arm, mode: str, fps: int) -> dict:
    """Runs ``mode`` on the armature's action in place and returns the sidecar
    block ``{mode, travel_m, ref_height_m, contact_s, max_drift_cm}``.
    Raises ValueError when foot_lock cannot hold the feet."""
    if mode not in rm.MODES:
        raise ValueError(f"root_motion must be one of {rm.MODES}, not {mode!r}")
    action, frames = _frames(arm)
    hips = PREFIX + "Hips"
    mats, joints = sample(arm, frames)
    tracks, weights, ref_height_m = _contacts(arm, joints, frames, fps)
    zero = [(0.0, 0.0)] * len(frames)
    if mode == "foot_lock":
        path = rm.foot_lock_path(tracks, weights)
        rest = arm.data.bones[hips].matrix_local.copy()
        moved = {f: Matrix.Translation(Vector((path[i][0], 0.0, path[i][1]))) @ mats[f][hips]
                 for i, f in enumerate(frames)}
        write_root(arm, action, hips, moved, rest)
        mats, joints = sample(arm, frames)
        # Same weights as the path was built from: the pass moved the root in
        # XZ only, so the heights (and with them the contacts) are unchanged.
        drift = rm.max_planted_drift(_tracks(arm, joints, frames), weights, zero)
        if drift > MAX_LOCK_DRIFT_CM:
            raise ValueError(f"foot_lock left a planted foot moving {drift:.2f} cm "
                             f"(limit {MAX_LOCK_DRIFT_CM})")
    else:
        drift = rm.max_planted_drift(tracks, weights, zero)
    t0, t1 = mats[frames[0]][hips].translation, mats[frames[-1]][hips].translation
    return {"mode": mode,
            "travel_m": [round((t1.x - t0.x) / 100, 3), round((t1.z - t0.z) / 100, 3)],
            "ref_height_m": round(ref_height_m, 3),
            "contact_s": rm.contact_spans(weights, fps),
            "max_drift_cm": round(drift, 2)}


def run(job):
    """Measuring job: import ``src``, report the block of its CURRENT state,
    write nothing. Returns ``(data, outputs)`` like every runner script."""
    sys.path.insert(0, _SCRIPTS_DIR)
    try:
        import clip_orient                                    # scene import helpers
    finally:
        sys.path.remove(_SCRIPTS_DIR)
    p = job.get("params") or {}
    inputs = job.get("inputs") or {}
    if "rig" not in inputs:
        raise ValueError("input 'rig' (the reference skeleton) is required: "
                         "a clip file carries no rest pose of its own")
    fps = int(p.get("fps", 30) or 30)
    _common.reset_scene()
    rig = clip_orient._import_armature(inputs["rig"], fps, anim=False)
    rest = _rest_heights(rig)
    clip_orient._remove(rig)
    arm = clip_orient._import_armature(inputs["src"], fps)
    _action, frames = _frames(arm)
    mats, joints = sample(arm, frames)
    tracks, weights, ref_height_m = _contacts(arm, joints, frames, fps, rest)
    hips = PREFIX + "Hips"
    zero = [(0.0, 0.0)] * len(frames)
    return {"frames": len(frames),
            "max_drift_cm": round(rm.max_planted_drift(tracks, weights, zero), 2),
            "hips_y": [round(mats[f][hips].translation.y, 3) for f in frames],
            "hips_xz": [[round(mats[f][hips].translation.x, 3),
                         round(mats[f][hips].translation.z, 3)] for f in frames],
            "contact_s": rm.contact_spans(weights, fps),
            "ref_height_m": round(ref_height_m, 3)}, {}


if __name__ == "__main__":
    _common.main(run)
