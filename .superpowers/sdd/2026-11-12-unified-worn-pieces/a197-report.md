# A197 — mesh purge script (prepared, NOT run on the live world)

Script: `scripts/purge_meshes_a197.py`; smoke: `scripts/smoke_purge_meshes_a197.py` (OK, hand-derived totals 766 B / 11 files).

## Scope decisions
- Keep list default `Spoty,Gelina` — the world's character is spelled **Spoty**, not "Spotty". Unknown `--keep` names
  are refused (so a typo can never purge a kept character).
- Temporary NPCs = template feature `temporary_npc` (template `npc-temporary`), read from `shared/templates/character/`.
- Per purged character: whole `model3d/` (base body, outfit bodies, combination models, texture models, assembled,
  rollback, geometry npz, facefix texture) + legacy `model/`; all of `garments/` except `garments/images/`
  (fits+records, low, raw incl. HairDeck/HAAR hair job folders, prepared, layers, bodies, attempts, shell, templates,
  failed, limbs, `.geometry_judged` marker). Hair pieces count as outfit meshes.
- Shared `footwear/<item>/<ssig>/` raw.glb/prepared.glb/insole.json of items held by NO kept character / temp NPC;
  steps `mesh`/`insole` dropped from that `record.json` (original backed up). Images stay.
- DB: profiles hold no mesh state (nothing changed there); `hub_ops` rows `model3d:<name>:…` / `garment_haar:<name>:…`
  are exported + deleted (live copy: none).
- Everything moved to `<world>/.purge-backup-a197-<stamp>/` (same layout) + `manifest.json` + `db_rows.json`;
  `--restore` moves back, re-inserts rows, restores records.
- Refuses when `.pids/main.pid` is alive or a `uvicorn app.server:app` process exists.

## Dry run on a copy of Anima Divide (copy deleted) — ~/claude-out/a197/dry_run.txt
13 characters purged, 2148 files, 8.6 GB, 0 DB rows; 15 temp NPCs + Spoty + Gelina skipped; 10 footwear sources.
