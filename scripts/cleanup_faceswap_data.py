#!/usr/bin/env python3
"""Remove leftover FaceSwap DATA from worlds (config.json, world.db, skill
configs, image sidecars) after the FaceSwap CODE was removed.

Dry-run by default — prints what it WOULD change. Pass --apply to write.
Before changing a file/db it is copied (preserving relative path) into
migration_backup/faceswap_cleanup/ so the whole backup can be deleted later in
one go.

Usage:
    python scripts/cleanup_faceswap_data.py                 # dry-run, all worlds
    python scripts/cleanup_faceswap_data.py --apply         # write changes (+ backups)
    python scripts/cleanup_faceswap_data.py --world demo    # restrict to one world
    python scripts/cleanup_faceswap_data.py --apply --no-backup   # skip backups (NOT recommended)

What it removes:
  config.json   : top-level "faceswap" + "face_enhance" sections,
                  story_engine.beat_faceswap, image_generation backends[].faceswap_needed
                  and comfyui_workflows[].faceswap_needed
  world.db      : faceswap_enabled / swap_mode / multiswap_mode keys inside the
                  characters table profile_json + config_json blobs
  skill config  : worlds/*/characters/*/skills/image_generation.json -> swap_mode,
                  faceswap_enabled, multiswap_mode
  image sidecars: worlds/*/{characters/*/images,instagram,characters/*/outfits}/*.json
                  -> faceswap, faceswap_method, faceswap_fallback, face_enhance
"""
import argparse
import json
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORLDS = ROOT / "worlds"
BACKUP_ROOT = ROOT / "migration_backup" / "faceswap_cleanup"

# keys to strip
SIDECAR_KEYS = ("faceswap", "faceswap_method", "faceswap_fallback", "face_enhance")
CHAR_BLOB_KEYS = ("faceswap_enabled", "swap_mode", "multiswap_mode")
SKILL_KEYS = ("swap_mode", "faceswap_enabled", "multiswap_mode")
CONFIG_SECTIONS = ("faceswap", "face_enhance")

stats = {"config": 0, "db_chars": 0, "skill": 0, "sidecar": 0}


def _backup(path: Path, apply: bool, do_backup: bool):
    """Mirror path under migration_backup/faceswap_cleanup/<relative path>.

    Each file is backed up only once (skips if a backup already exists), so
    re-running --apply does not overwrite the original-state backup.
    """
    if not (apply and do_backup):
        return
    try:
        rel = path.relative_to(ROOT)
    except ValueError:
        rel = Path(path.name)
    dest = BACKUP_ROOT / rel
    if dest.exists():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, dest)


def _load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"  ! skip (unreadable): {path} ({e})")
        return None


def _save_json(path: Path, data, apply: bool, do_backup: bool):
    if not apply:
        return
    _backup(path, apply, do_backup)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def clean_config_json(path: Path, apply: bool, do_backup: bool):
    d = _load_json(path)
    if d is None:
        return
    changed = []
    for sec in CONFIG_SECTIONS:
        if sec in d:
            del d[sec]
            changed.append(sec)
    se = d.get("story_engine")
    if isinstance(se, dict) and "beat_faceswap" in se:
        del se["beat_faceswap"]
        changed.append("story_engine.beat_faceswap")
    ig = d.get("image_generation")
    if isinstance(ig, dict):
        for grp in ("backends", "comfyui_workflows"):
            coll = ig.get(grp)
            items = coll.values() if isinstance(coll, dict) else (coll or [])
            for it in items:
                if isinstance(it, dict) and "faceswap_needed" in it:
                    del it["faceswap_needed"]
                    changed.append(f"image_generation.{grp}[].faceswap_needed")
    if changed:
        # de-dup the [] entries for printing
        uniq = sorted(set(changed))
        print(f"  config.json: remove {uniq}")
        _save_json(path, d, apply, do_backup)
        stats["config"] += 1


def clean_world_db(path: Path, apply: bool, do_backup: bool):
    con = sqlite3.connect(str(path))
    try:
        rows = con.execute(
            "SELECT rowid, name, profile_json, config_json FROM characters "
            "WHERE profile_json LIKE '%faceswap%' OR profile_json LIKE '%swap_mode%' "
            "OR config_json LIKE '%faceswap%' OR config_json LIKE '%swap_mode%'"
        ).fetchall()
    except sqlite3.OperationalError as e:
        print(f"  ! db query failed: {e}")
        con.close()
        return
    if not rows:
        con.close()
        return
    backed = False
    for rowid, name, pj, cj in rows:
        new_pj, removed_p = _strip_blob_keys(pj)
        new_cj, removed_c = _strip_blob_keys(cj)
        if removed_p or removed_c:
            print(f"  world.db [{name}]: remove {sorted(set(removed_p + removed_c))}")
            if apply:
                if not backed:
                    _backup(path, apply, do_backup)
                    backed = True
                con.execute(
                    "UPDATE characters SET profile_json=?, config_json=? WHERE rowid=?",
                    (new_pj, new_cj, rowid))
            stats["db_chars"] += 1
    if apply:
        con.commit()
    con.close()


def _strip_blob_keys(blob: str):
    if not blob:
        return blob, []
    try:
        d = json.loads(blob)
    except Exception:
        return blob, []
    removed = [k for k in CHAR_BLOB_KEYS if k in d]
    for k in removed:
        del d[k]
    if removed:
        return json.dumps(d, ensure_ascii=False), removed
    return blob, []


def clean_skill_config(path: Path, apply: bool, do_backup: bool):
    d = _load_json(path)
    if not isinstance(d, dict):
        return
    removed = [k for k in SKILL_KEYS if k in d]
    for k in removed:
        del d[k]
    if removed:
        print(f"  skill {path.relative_to(WORLDS)}: remove {removed}")
        _save_json(path, d, apply, do_backup)
        stats["skill"] += 1


def clean_sidecar(path: Path, apply: bool, do_backup: bool):
    d = _load_json(path)
    if not isinstance(d, dict):
        return
    removed = [k for k in SIDECAR_KEYS if k in d]
    for k in removed:
        del d[k]
    if removed:
        _save_json(path, d, apply, do_backup)
        stats["sidecar"] += 1


def process_world(world_dir: Path, apply: bool, do_backup: bool):
    print(f"\n=== {world_dir.name} ===")
    cfg = world_dir / "config.json"
    if cfg.is_file():
        clean_config_json(cfg, apply, do_backup)
    db = world_dir / "world.db"
    if db.is_file():
        clean_world_db(db, apply, do_backup)
    for skill in world_dir.glob("characters/*/skills/image_generation.json"):
        clean_skill_config(skill, apply, do_backup)
    side_globs = [
        "characters/*/images/*.json",
        "instagram/*.json",
        "characters/*/outfits/*.json",
    ]
    for g in side_globs:
        for s in world_dir.glob(g):
            clean_sidecar(s, apply, do_backup)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    ap.add_argument("--world", default="", help="restrict to one world (dir name)")
    ap.add_argument("--no-backup", action="store_true", help="do not create .fsbak backups")
    args = ap.parse_args()

    if not WORLDS.is_dir():
        print(f"no worlds dir at {WORLDS}")
        return 1

    worlds = [WORLDS / args.world] if args.world else sorted(p for p in WORLDS.iterdir() if p.is_dir())
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"FaceSwap data cleanup — {mode}{'' if args.apply else ' (no files changed)'}")
    for w in worlds:
        if not w.is_dir():
            print(f"  ! world not found: {w}")
            continue
        process_world(w, args.apply, not args.no_backup)

    print("\n--- summary ---")
    print(f"  config.json files cleaned : {stats['config']}")
    print(f"  world.db characters cleaned: {stats['db_chars']}")
    print(f"  skill configs cleaned      : {stats['skill']}")
    print(f"  image sidecars cleaned     : {stats['sidecar']}")
    if not args.apply:
        print("\n(dry-run — rerun with --apply to write; backups go to <file>.fsbak)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
