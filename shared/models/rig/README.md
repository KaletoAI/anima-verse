# The reference skeleton

`reference.fbx` is the ONE rig every animation clip of this project is
retargeted onto — an FBX carrying the `mixamorig:` armature and nothing else:
no mesh, no texture, no animation. 69 bones, hips at 111.03 cm, the armature
object in the Mixamo convention (0.01 scale, +90° X, centimetres in armature
space).

Everything that turns motion into a clip drives it onto this file:

* `scripts/clip_import_cmu.py` and the Poses tab's CMU catalog browser
  (`app/core/cmu_import.py` → `default_rig()`),
* the inbox import of foreign FBX animations (`app/core/fbx_import.py`),
* the bulk conversion `scripts/cmu_convert_all.py`.

`app/core/paths.py:get_rig_file()` resolves it; `ANIMATION_RIG_FILE` overrides
the location (tests must set it, same rule as `ANIMATION_CLIPS_DIR`). There is
NO fallback: without this file an import fails with a named error instead of
retargeting onto some other skeleton.

## Why it is not a clip

Because all clips must share ONE skeleton. The 3D client normalises every clip
against the library's standing hip height (`figures.ts adaptExternalClips`), so
a clip driven onto a shorter or taller rig reads as "crouching" or "stilted"
and sinks into the ground. The reference used to be the library's own
`idle.fbx`, which tied the pipeline to a piece of CONTENT: emptying, replacing
or deleting the clip library took the importer's reference with it. It is
pipeline, so it lives here.

## Licence

Derived from `shared/models/clips/idle.fbx`, a CMU Graphics Lab mocap
conversion — free to copy, modify and redistribute, hence tracked in git. A
bare skeleton carries no motion of its own anyway.

> The data used in this project was obtained from mocap.cs.cmu.edu. The
> database was created with funding from NSF EIA-0196217.

## Rebuilding it

    ./.venv/bin/python scripts/make_reference_rig.py [<source.fbx>]

Any FBX with the project's `mixamorig:` armature works as the source (a library
clip, a rigged character export); without an argument the library's `idle.fbx`
is taken. The script runs Blender headlessly
(`app/blender/scripts/rig_export.py`): it keeps the armature, deletes every
other object and every action, and re-exports with the same axis settings the
clip exporter uses, so the bones come back bit for bit.

REBUILDING IS A DECISION, not maintenance. Every existing clip sits on the
skeleton this file holds today; a reference with different bone rest positions
or a different height would put NEW clips on a different footing than the old
ones. Replace it only to change the rig on purpose — and then reconvert the
library with it.
