# Shared animation clips — the FREE library

Skeletal animation clips for the 3D character models, shared across ALL worlds
(they belong to the rig, not to a character or a world).

    GET    /assets/animation-clips                          the listing (public)
    GET    /assets/animation-clips/[licensed/][<set>/]<file> one clip (public)
    GET    /assets/animation-rig                            ../rig/reference.fbx
    PATCH  /assets/animation-clips/<library>/<rel>          rename/move/loop/roles
    POST   /assets/animation-clips/<library>/<rel>/orient   turn + lift the FILE
    DELETE /assets/animation-clips/<library>/<rel>          both halves of a pair

Reading is public, editing is admin-only, and `<library>` is `free` (this
directory) or `licensed`. The edit routes are what the Game-Admin's **Poses**
tab drives; they rewrite the files in place, which is why clips are served
with an ETag and `no-cache` rather than a long `max-age`.

Two libraries, one layout:

* **this one** — clips that may be REDISTRIBUTED with the repository (tracked
  in git). It carries the BASE SET everything else falls back to (`idle`,
  `walk`, `run`, `sit`, `laying`, …), each with a `<kind>.json` sidecar. Two
  sources feed it: CMU Graphics Lab mocap converted by
  `scripts/clip_import_cmu.py` (the sidecar then names the take and carries
  the CMU credit) and foreign FBX animations imported through the inbox
  (`../clips-inbox/`), whose sidecar names the file, the take and the bone map
  it was read with. Whatever the source, the result sits on the one reference
  rig — put a file here only if its licence allows redistribution.
* **`../clips-licensed/`** — bought packs: usable in the game, not
  redistributable, gitignored, per installation. The same `[<set>/]<file>` in
  both libraries resolves to the licensed one, so a pack overrides the base set
  clip by clip.

**The retarget reference is NOT in this library.** Every import
(`clip_import_cmu.py`, the Poses tab, the inbox) drives its take onto
`../rig/reference.fbx` (`cmu_import.default_rig()`, see the README there), so
all clips share one rig and one standing hip height — the height the client
normalises against. `idle.fbx` here is an ordinary clip like every other one;
this library may be emptied or deleted without touching the pipeline.

Drop the `.fbx` files straight in — no registration, no config.

## The sidecar `<kind>.json`

Written by the importer, edited by the Poses tab. What a renderer reads:

| Field | Meaning |
|---|---|
| `kind`, `pair`, `roles` | the kind, whether it is a pair and which role letters exist |
| `fps`, `source_fps`, `frames`, `duration_s` | timing; `speed` is `1.0` for everything converted since the capture rate reached Blender |
| `loop` | `true` = repeat, `false` = hold the last frame (Three.js `LoopOnce` + `clampWhenFinished`). Measured on import, overridden by the admin's switch in the Poses tab; it holds for both halves of a pair and for every numbered take of that kind in that set. A kind with NO listing entry counts as looping — locomotion must never stand still |
| `geometry` | what the conversion measured: `floor_shift_cm`, the `root_motion` block of a solo clip (`mode` strip/keep/foot_lock, `travel_m` = `[x, z]` where the clip ends up in the clip frame — +Z forward, +X the figure's left, metres of the reference rig —, `ref_height_m` = the reference rig's standing height, `contact_s` = the full-contact spans `[[start, end], …]` in seconds, `max_drift_cm` = the worst planted-foot slide foot_lock left), the pair anchor (`anchor_frame`, `anchor_s`, `root_distance_m`, per-role `start_xz_m`/`anchor_xz_m`), the hip scale and, after a `…/orient` run, the accumulated angles |
| `source` | where it came from: the CMU take plus its credit, or the file, take and `bone_map` of an inbox import |

The sidecar of `<stem>.fbx` is `<stem>.json` when that file exists (so
`idle_02.fbx` may carry its own duration in `idle_02.json`), otherwise the
shared `<kind>.json` of its kind.

## Layout → `kind` + `set`

    [<set>/]<kind>[_<number>].fbx

| file | kind | set |
|------|------|-----|
| `walk.fbx` | `walk` | — (neutral figure) |
| `lady/walk.fbx` | `walk` | `lady` |
| `lady/sit_02.fbx` | `sit` | `lady` |
| `walk_02.fbx` | `walk` | — |
| `swim-idle.fbx` | `swim-idle` | — |
| `treading-water.fbx` | `treading-water` | — |
| `spell_casting.fbx` | `spell_casting` | — |

**`kind`** is the category an activity maps onto (`idle`, `walk`, `run`, `sit`,
`lie`, `dance`, `wave`, …) and is the FILE NAME without its extension —
**hyphens and underscores are part of it**. The ONLY thing cut off is a
trailing `_<number>`, the numbering of several clips of one kind. So
`swim-idle.fbx` is the kind `swim-idle`, not a second `swim`. It is what the
character is *doing*: the pose presets carry an `animation` field (Game-Admin →
Poses), and a terrain type names one in `move_anim`/`idle_anim` — both must
spell the kind exactly as the file does.

**`set`** is the figure the clip was authored for and comes from the
DIRECTORY — one subdirectory per set, exactly one level deep. Clips in this
root folder are the neutral ones. The set is about *who* the character is;
nobody assigns clips per character:

* Every character DERIVES a set from what it already is: a non-humanoid one
  gets `animal`, a humanoid one its gender — `female` or `male`. So
  `female/walk.fbx`, `animal/sit.fbx` … are picked up automatically.
* A character may OVERRIDE that with any set (`animation_set`, e.g. `lady`).

### Fallback chain (per kind)

    <explicit set>/<kind>   →   <derived set>/<kind>   →   <kind>

An override does **not** have to be complete: a character on `lady` that has no
`lady/sit.fbx` sits like the figure it derives from (`female/sit.fbx`), and only
if that is missing too does the plain `sit.fbx` apply. So you can add a handful
of special clips without authoring a whole set.

Both vocabularies are OPEN — **no list exists in the code** (only `female`,
`male`, `animal` are always offered, because they follow from data every
character already carries). A new kind is just a new file, a new set just a new
directory.

## Pair clips — `<kind>__a.fbx` + `<kind>__b.fbx`

Two files recorded TOGETHER, one per partner, are a pair clip of one kind:
`handshake__a.fbx` and `handshake__b.fbx`. The double underscore is the ROLE
separator and nothing else (a single `_` stays part of the kind; a trailing
`_<n>` numbering is cut first, so `hug__a_02.fbx` is a second take of A's
half). A pair kind has no solo file — it is played by two figures at one
anchor, in lockstep (`docs/schnittstellen-3d.md` § A8a). Both halves share
one frame of reference: origin at the XZ midpoint of the two roots at the
anchor moment, +X from A to B, floor at y = 0, full root motion kept. A
sidecar `<kind>.json` next to them carries duration, fps and that geometry.

The converter `scripts/clip_import_cmu.py` writes such pairs (and solo clips)
from the CMU Graphics Lab mocap database — whose data, unlike a licensed pack's,
may be redistributed with the repository:

    ./.venv/bin/python scripts/clip_import_cmu.py handshake 18_01 19_01
    ./.venv/bin/python scripts/clip_import_cmu.py dance 55_02 --root-motion strip

It retargets onto the reference skeleton `../rig/reference.fbx`, so the result
keeps the same skeleton — and the same standing hip height — as every other
clip.

## Hard requirements for the files

These hold for EVERY clip, whatever its source — a CMU conversion, a bought
pack, a hand-authored take. Violating them does not fail loudly; it produces
characters that walk on their belly:

1. **FBX with keyframes only** — no mesh, no texture ("Without Skin").
2. **The project's rig** — the 69 `mixamorig:` bones of
   `../rig/reference.fbx`, the same basis the character GLBs and the generated
   meshes carry. A foreign convention (e.g. "UE4 Skeleton") tips the figures
   over; the importers retarget onto that file precisely so every clip ends up
   on that one skeleton.
3. **Movement clips must be IN PLACE.** The client moves the figure itself (the
   walk, the journey, the click route); a clip that also carries root motion
   drives the body away from the position the game holds it at.
   `clip_import_cmu.py --root-motion strip` (the default) strips it. The
   exception are bridge clips imported with `foot_lock`/`keep` (standing up
   out of a chair or a bed), which carry their travel on purpose: the client
   moves the figure along it and the server puts the stand point where the
   clip ends (`docs/schnittstellen-3d.md` § A8). A loop never does — the
   import refuses a loop cut together with `keep`/`foot_lock`.
4. **Author them on the FLOOR.** A movement clip is played against a figure
   whose soles stand on the ground, so a clip animated on a line of its own —
   a swimmer on a water line — holds the body over that ground. The client
   measures the offset and drops the figure onto the ground while it moves
   (`client3d/src/scene/clipGround.ts`), which rescues the picture but not the
   intent: the swimmer then wades at the height the clip was authored at.
   Clips that are MEANT to sit above the floor (a sleeper on a bed) are the
   deliberate exception.

## Tests must not touch this directory

`paths.get_animation_clips_dir()` resolves the library and honours the
override **`ANIMATION_CLIPS_DIR`**; the licensed library follows as
`<that>-licensed`, and `ANIMATION_RIG_FILE` does the same for
`../rig/reference.fbx`. A check that imports anything from `app` has to set
them BEFORE that first import — otherwise it reads (and a write path would
edit) the real user files. Every smoke under `scripts/` does it in its first
lines; copy the pattern from `scripts/smoke_scene_recipe.py`.

## Why here and not under `characters/`

A clip is not character data: the same `walk.fbx` drives every figure that
carries the project's rig. Keeping it world-independent means one upload, every
world, every client.
