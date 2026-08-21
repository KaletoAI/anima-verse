# Mocap source archive (untracked)

Untouched motion-capture originals, kept exactly as the source server delivers
them. Nothing here is generated or edited; the converters read from here and
write elsewhere, so this directory can always be deleted and re-fetched.

## `cmu/`

The complete CMU Graphics Lab Motion Capture Database: one directory per
subject (the server's own zero-padded name, e.g. `01/`, `18/`), each holding
the subject's skeleton `<s>.asf` and one `<s>_<trial>.amc` per take.

Fetched by `scripts/cmu_fetch_all.py` from the take list in
`shared/models/cmu_catalog.json` (built by `scripts/cmu_catalog.py`); converted
into `shared/models/clips-trial/` by `scripts/cmu_convert_all.py`.

The data used in this project was obtained from mocap.cs.cmu.edu. The database
was created with funding from NSF EIA-0196217.
