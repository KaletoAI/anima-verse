# Shared animation clips

Skeletal animation clips for the 3D character models, shared across ALL worlds
(they belong to the rig, not to a character or a world). Served read-only by
`GET /assets/animation-clips`; the files themselves at
`GET /assets/animation-clips/{filename}`.

Drop the `.fbx` files straight into this folder — no registration, no config.

## Naming → `kind` + `set`

    <kind>[_<set>][_<number>].fbx

| file | kind | set |
|------|------|-----|
| `walk.fbx` | `walk` | — (default figure) |
| `walk_lady.fbx` | `walk` | `lady` |
| `Sit_Lady_02.fbx` | `sit` | `lady` |
| `walk_02.fbx` | `walk` | — |

**`kind`** is the category an activity maps onto (`idle`, `walk`, `run`, `sit`,
`lie`, `dance`, `wave`, …). It comes from what the character is *doing*: the
pose presets carry an `animation` field (Game-Admin → Poses).

**`set`** is the figure the clip was authored for (`lady`, `man`, `dog`, …). It
comes from *who* the character is: every character has an optional
`animation_set` attribute. Setting it once to `lady` gives that character
`walk_lady`, `sit_lady`, `sleep_lady` … automatically — no per-character clip
assignment anywhere. A character without a set (or without a matching clip)
falls back to the plain `<kind>.fbx`.

Both vocabularies are OPEN — **no list exists in the code**; a new kind or set
is just a new file name. Trailing numbers only distinguish several clips of the
same kind+set.

## Hard requirements for the files

Violating these does not fail loudly — it produces characters that walk on their
belly. Take them seriously:

1. **Mixamo FBX, exported "Without Skin"** — keyframes only, no mesh, no texture.
2. **All clips from the SAME source.** Mixed skeleton conventions tip the
   figures over. Download fresh from mixamo.com — do NOT take FBX files from
   model repos, and never one labelled "UE4 Skeleton".
3. **Must match the Mixamo 52-bone rig** that the character models already use
   (the same basis as the character GLBs and the generated meshes).

## Why here and not under `characters/`

A clip is not character data: the same `walk.fbx` drives every figure that
carries the Mixamo rig. Keeping it world-independent means one upload, every
world, every client.
