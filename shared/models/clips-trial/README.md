# Trial clip archive (untracked)

The whole CMU database converted to Mixamo-rig FBX clips — a browsing pool to
pick from, NOT the animation library the game plays from. That library is
`shared/models/clips/`; a clip only moves there once it has been reviewed
(and usually re-cut: trimmed, looped, given a real name).

Layout mirrors the CMU motion categories:

    <main-category>/<sub-category>/<take-id>.fbx      solo, converted in place
                                  /<take-id>.json     the converter's sidecar
                                  /<take-id>__a.fbx   pair, subject A
                                  /<take-id>__b.fbx   pair, subject B

Takes that no category lists sit under `uncategorized/`.

Two collection files at the top level:

* `_index.json` — one record per converted clip: id, category path, clip path,
  duration, frame count, pair flag, description. This is what a catalog
  browser reads.
* `_errors.json` — takes whose conversion failed, with the reason.

`speed_factor` in an index record is the one caveat: the Blender converter
reads every AMC as the database's usual 120 Hz, so the takes captured at 60 Hz
come out running twice as fast. Their poses are correct, their timing is not —
stretch by `speed_factor` when cutting such a clip for the real library.

Rebuild with `scripts/cmu_fetch_all.py` followed by
`scripts/cmu_convert_all.py` (both resumable; delete a clip to have it redone).

The data used in this project was obtained from mocap.cs.cmu.edu. The database
was created with funding from NSF EIA-0196217.
