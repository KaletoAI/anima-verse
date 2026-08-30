# The reference figure

`default.fbx` (or `default.glb`) is THE figure of this project: the size
reference and the marker figure wherever a body has to stand in for a body —
the floor-plan preview's marker figures, the scale figure next to the metre
ruler, the prop viewer's seat and lying markers, and the measurement smokes
(`scripts/smoke_prop_marker_place.mjs`). Served by
`GET /play/test-figure/model` (+ `/meta` naming the format).

Drop your figure in under that name; no registration, no config.

Requirements:
- **Rigged on the project's skeleton** (`mixamorig:` joints, `../rig/README.md`)
  — the shared clips in `../clips/` must be applicable, a foreign rig tips the
  figure over.
- **WITH skin/mesh**, unlike the clips ("Without Skin"): this figure is what
  gets drawn.
- Any height — every preview normalises it to the contract's 1.70 m
  (`packages/scene-render` `FIGURE_HEIGHT_M`), so the model's own scale does
  not matter. It is measured, not trusted.

Rendering note: the previews replace all materials with a flat clay-gray one
anyway — textures in the file are ignored.

Fallback chain (unchanged): `default.*` first, then any other
`.glb`/`.gltf`/`.fbx` lying here (alphabetically), then the first humanoid
CHARACTER model on the server (in clay gray), and without that a simple
built-in mannequin.

Like the clips, the binaries are user-provided per installation and
gitignored — only this README is tracked.
