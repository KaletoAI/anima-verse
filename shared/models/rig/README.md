# The reference skeleton

`reference.fbx` is the ONE rig every animation clip of this project is
retargeted onto — an FBX carrying the `mixamorig:` armature and nothing else:
no mesh, no texture, no animation. 69 bones, hips at 113.03 cm, arms out along
±X in a T-POSE, the armature object in the Mixamo convention (0.01 scale,
+90° X, centimetres in armature space).

Everything that turns motion into a clip drives it onto this file:

* `scripts/clip_import_cmu.py` and the Poses tab's CMU catalog browser
  (`app/core/cmu_import.py` → `default_rig()`),
* the inbox import of foreign FBX animations (`app/core/fbx_import.py`),
* the bulk conversion `scripts/cmu_convert_all.py`.

`app/core/paths.py:get_rig_file()` resolves it; `ANIMATION_RIG_FILE` overrides
the location (tests must set it, same rule as `ANIMATION_CLIPS_DIR`). There is
NO fallback: without this file an import fails with a named error instead of
retargeting onto some other skeleton.

## The rest pose has to be a symmetric T-pose

The retarget composes `R_cmu(t) · A · R_rest` (`app/blender/scripts/cmu_clip.py`)
and reads the actor's motion as the rotation away from CMU's T-pose, so this
file's REST POSE is the neutral the motion is added to. A rest that is really a
posed frame tilts every clip driven onto it: the shoulder on the low side
droops and its palm rolls out, and the whole stance leans.

That is not theoretical — it happened. The reference of 2026-08-30 carried the
idle clip's FIRST FRAME as its rest (hips 20° off vertical, arms 88° off ±X,
80° of left/right mirror error), and every clip imported after it inherited a
hanging right shoulder. Two things went wrong at once:

* a CLIP FBX carries no bind pose (`cmu_clip._export` writes the armature
  alone), so Blender's importer rebuilds the rest from the animated node
  transforms and hands back frame 1 as the rest pose — a clip of this pipeline
  can never be the source;
* `rig_export.py` cleared the animation DATA but not the POSE, and the FBX
  exporter writes bones from the pose — so any source with an action was
  written out at its first frame.

Both are guarded now: the export resets the pose, refuses a source whose rest
is not a symmetric T-pose, and reads the written file back to confirm it
returns the source skeleton bone for bone.

## Why it is not a clip

Because all clips must share ONE skeleton. The 3D client normalises every clip
against the library's standing hip height (`figures.ts adaptExternalClips`), so
a clip driven onto a shorter or taller rig reads as "crouching" or "stilted"
and sinks into the ground. The reference used to be the library's own
`idle.fbx`, which tied the pipeline to a piece of CONTENT: emptying, replacing
or deleting the clip library took the importer's reference with it. It is
pipeline, so it lives here.

## Where the skeleton comes from

It is the skeleton the whole clip library already sits on — a retarget keeps the
TARGET rig's bones, so every clip in `shared/models/clips` carries these 69
bones and these bone lengths. The T-pose rest was recovered from the library's
former `idle.fbx` (tracked in this repository until commit `e93e1052`), which
is the file the existing clips were driven onto; nothing but the rest pose
changed with it.

The file holds a bare armature: no mesh, no texture, no motion of its own.

> The data used in this project was obtained from mocap.cs.cmu.edu. The
> database was created with funding from NSF EIA-0196217.

## Rebuilding it

    ./.venv/bin/python scripts/make_reference_rig.py <source.fbx>

The source must carry the project's `mixamorig:` armature IN ITS BIND POSE — a
rigged character export, not a clip of this pipeline (see above). The script
runs Blender headlessly (`app/blender/scripts/rig_export.py`): it keeps the
armature, deletes every other object and every action, resets the pose,
re-exports with the same axis settings the clip exporter uses, and verifies the
written file against the source. A source that fails the T-pose, symmetry or
read-back check produces an error instead of a file.

REBUILDING IS A DECISION, not maintenance. Every existing clip sits on the
skeleton this file holds today; a reference with different bone rest positions
or a different height would put NEW clips on a different footing than the old
ones. Replace it only to change the rig on purpose — and then reconvert the
library with it.
