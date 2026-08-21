# Clip import inbox (per installation, not in git)

Drop animation files here — or upload them in the Game-Admin under
**Poses → Import files** — and they show up as "to be imported". Nothing in
this folder is game content: no character plays a file from here, the clip
listing (`GET /assets/animation-clips`) never mentions it, and a file becomes
a real clip only by being IMPORTED: retargeted onto the library rig, cut to a
window, optionally looped, and written into one of the two clip libraries
next door.

**Licensed files never enter git.** Everything under this directory is
ignored except this README — the same rule as `../clips-licensed`. That is
also the default import target: a foreign file goes into the LICENSED library
unless you explicitly mark it as redistributable.

## What can lie here

* `*.fbx` — a foreign rig's animation, flat in this directory (no
  subdirectories are scanned). The server probes the file for its skeleton
  family without Blender, by reading the node names out of the bytes:
  * `unity-humanoid` (Unity Humanoid / UMotion exports: `Hips`,
    `Left_UpperLeg`, `Left_UpperArm`, `Chest`) — importable.
  * anything else is reported as "unknown rig" and refused: the retargeter
    (`app/blender/scripts/fbx_clip.py`) has no bone map for it.

## Pairs

Two files recorded together become ONE clip kind with two halves
(`<kind>__a.fbx` / `<kind>__b.fbx`). The importer suggests the partner from
the file names — `Female_`/`Male_`, `_A`/`_B`, `__a`/`__b`, `_L`/`_R` — and
the A file is the one selected first.

## Reference pose (optional but worth it)

An FBX of the SAME rig in a well-defined reference pose (a T- or A-pose
export, e.g. `Tpose.fbx`) makes the import read every bone's own node
rotation relative to that pose — twist included — instead of rebuilding the
orientation from joint positions. Without it a thigh's roll follows the
pelvis and a forearm's the hand, which is approximate. A file whose name
contains `tpose`, `t-pose`, `rest` or `bind` is offered as the reference pose
automatically.
