# Shared animation clips

Skeletal animation clips for the 3D character models, shared across ALL worlds
(they belong to the rig, not to a character or a world). Served read-only by
`GET /assets/animation-clips`; the files themselves at
`GET /assets/animation-clips/[{set}/]{filename}`.

Drop the `.fbx` files straight in — no registration, no config.

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

## Hard requirements for the files

Violating these does not fail loudly — it produces characters that walk on their
belly. Take them seriously:

1. **Mixamo FBX, exported "Without Skin"** — keyframes only, no mesh, no texture.
2. **All clips from the SAME source.** Mixed skeleton conventions tip the
   figures over. Download fresh from mixamo.com — do NOT take FBX files from
   model repos, and never one labelled "UE4 Skeleton".
3. **Must match the Mixamo 52-bone rig** that the character models already use
   (the same basis as the character GLBs and the generated meshes).
4. **Movement clips must be exported "In Place".** The client moves the figure
   itself (the walk, the journey, the click route); a clip that also carries
   root motion drives the body away from the position the game holds it at.
   Mixamo has the checkbox — `swim.fbx` was downloaded without it and travels
   2.36 m forward per cycle (0.52 m/s), the only clip in the library that does.
5. **Author them on the FLOOR.** A movement clip is played against a figure
   whose soles stand on the ground, so a clip animated on a line of its own —
   `swim.fbx` is authored on a water line — holds the body over that ground.
   The client measures the offset and drops the figure onto the ground while it
   moves (`client3d/src/scene/clipGround.ts`), which rescues the picture but not
   the intent: the swimmer then wades at the height the clip was authored at.
   Standing clips are exempt on purpose — `sleep.fbx` is animated on a bed and
   is meant to be.

## Why here and not under `characters/`

A clip is not character data: the same `walk.fbx` drives every figure that
carries the Mixamo rig. Keeping it world-independent means one upload, every
world, every client.
