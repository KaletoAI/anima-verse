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

Collection files at the top level:

* `_catalog.json` — the browsing catalog: EVERY take of the database, measured,
  tagged and grouped. This is the file a catalog browser loads (~2–4 MB).
* `_index.json` — one record per converted clip: id, category path, clip path,
  duration, frame count, pair flag, description. The conversion's own ledger;
  `_catalog.json` takes the clip path from it.
* `_errors.json` — takes whose conversion failed, with the reason
  (`_catalog_errors.json` for takes the measurement could not read).
* `_status.json` — the REVIEW state, written by the admin UI (see below).

## Browsing and importing (Game-Admin → Poses → CMU clip catalog)

`app/core/clip_catalog.py` + three admin-only routes in `app/routes/assets.py`:

    GET  /assets/clip-catalog                  catalog + review state, merged
    PUT  /assets/clip-catalog/{take}/status    {favorite?, rejected?}
    POST /assets/clip-catalog/{take}/import    {kind, set, start_s, end_s,
                                                loop_s, in_place, overwrite}
    GET  /assets/animation-clips/trial/{rel}   one trial clip, for the preview

`_status.json` is this UI's own file — `{"takes": {"<id>": {"favorite",
"rejected", "imported": [{kind, set, source, at}]}}}`. `favorite` and
`rejected` are independent booleans, not one tri-state; `imported` is the trace
of what was already lifted out of that take (one entry per kind+set).

An import runs `app/core/cmu_import.py` synchronously — the same functions the
`scripts/clip_import_cmu.py` CLI uses — on the ORIGINAL ASF/AMC under
`shared/models/mocap-src`, not on the trial FBX: the clip is re-cut and
retargeted from scratch, so window/loop/in-place are real conversion
parameters. A pair take always imports BOTH halves as one kind. The target is
always the FREE library (`shared/models/clips`); CMU data is redistributable,
which is the whole reason it may live there.

PARTIAL STATE IS NORMAL. Measuring and converting run in the background, so a
take may have no clip yet (the browser shows "not converted yet" instead of a
preview — importing still works, it goes to the original) and takes may be
missing from the catalog entirely.

Trial clips are in NO library: `animation_clips` never scans this directory,
they never appear in `/assets/animation-clips`, and no character can play one.

Checked by `scripts/smoke_clip_catalog.py` (`--real <take>` adds one true
Blender conversion when Blender and the originals are present).

`speed_factor` in an index record is always `1.0` today: the converter hands
the capture rate to Blender, so the takes recorded at 60 Hz keep their real
timing. The field only tells clips converted before that fix (2026-08-21)
apart — those play at double speed and have to be stretched.

## `_catalog.json`

Written by `scripts/cmu_enrich_index.py` from the ORIGINAL ASF/AMC files, not
from the FBX: it needs no Blender and runs before or during the conversion.
Per take it holds the CMU facts (description, categories, subject/trial,
framerate, confirmed pair role and partner), the derived `tags` and duplicate
`group`, the clip path once the converter has one, a 40-point hip-height
`sparkline`, and `metrics`:

    posture   standing | sitting | kneeling | lying | mixed
    energy    static | calm | moderate | fast     (hands/feet/head, m/s)
    travel    in-place | walks | travels         (root, start→end + path)
    duration_class  short | medium | long
    loop_seam / loopable   how well the take closes into a cycle

Every length is measured against the ACTOR's own leg length, so subjects of
different height compare. The rules and their thresholds are documented in the
script's module docstring — read it there, it is the single source.

The run is incremental: a take keeps its measurements until its AMC changes,
everything catalog-derived is rebuilt each time. Takes whose originals are not
downloaded yet are skipped and picked up by the next run.

Rebuild with `scripts/cmu_fetch_all.py`, then `scripts/cmu_convert_all.py`
(clips, resumable — delete a clip to have it redone) and
`scripts/cmu_enrich_index.py --jobs 4` (the catalog). Checked by
`scripts/smoke_cmu_enrich.py`.

The data used in this project was obtained from mocap.cs.cmu.edu. The database
was created with funding from NSF EIA-0196217.
