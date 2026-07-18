# Shared test figure

The neutral example figure the admin previews use (floor-plan marker
figures, the scale-comparison figure next to the metre ruler). Served by
`GET /play/test-figure/model` (+ `/meta` naming the format).

Drop **one Mixamo STANDARD character** here — e.g. **X Bot** or **Y Bot**
from mixamo.com, downloaded as *T-Pose*, format *FBX Binary* (or converted
to `.glb`). No registration, no config; the first `.glb`/`.gltf`/`.fbx`
file (alphabetically) wins.

Hard requirements (same as the animation clips):
- **Mixamo rig** (`mixamorig:` joints) — the shared clips in
  `../clips/` must be applicable, mixed rig sources tip the figures over.
- WITH skin/mesh (unlike the clips, which are "Without Skin").

Rendering note: the previews replace all materials with a flat clay-gray
one anyway — textures in the file are ignored, so the plain X Bot is
ideal.

Without a file here, the previews fall back to the first humanoid
CHARACTER model on the server (in clay gray), and without that to a
simple built-in mannequin.

Like the clips, the binaries are user-provided per installation and
gitignored — only this README is tracked.
