# Shared animation clips

Skeletal animation clips for the 3D character models, shared across ALL worlds
(they belong to the rig, not to a character or a world). Served read-only by
`GET /assets/animation-clips`; the files themselves at
`GET /assets/animation-clips/{filename}`.

Drop the `.fbx` files straight into this folder — no registration, no config.

## Naming → `kind`

The **kind** is derived from the file name: everything up to the first `_`, `-`,
space or digit, lowercased.

| file | kind |
|------|------|
| `walk.fbx` | `walk` |
| `Walk_02.fbx` | `walk` |
| `idle-breathing.fbx` | `idle` |
| `sit.fbx` | `sit` |

`kind` is the category a client maps activities onto (`idle`, `walk`, `run`,
`sit`, `dance`, `wave`, …). It is an open vocabulary — **no fixed list exists in
the code**; a new kind is just a new file name. Several clips may share a kind
(the client picks/varies).

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
