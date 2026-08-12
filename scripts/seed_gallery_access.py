#!/usr/bin/env python3
"""Seed a viewer name into every character's gallery access list.

Adds the given viewer to ``gallery_allowed_viewers`` on each character's config
so that viewer may browse the character's gallery in the player UI. Idempotent —
re-running with the same viewer changes nothing.

Usage:
  python3 scripts/seed_gallery_access.py --world <world> --viewer "<Name>"
  python3 scripts/seed_gallery_access.py --world <world> --viewer "<Name>" --dry-run
"""
import argparse
import os
import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_project_root))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--world", required=True, help="World name under worlds/")
    ap.add_argument("--viewer", required=True, help="Viewer name to grant access")
    ap.add_argument("--dry-run", action="store_true", help="Print changes only")
    args = ap.parse_args()

    world_dir = Path("worlds") / args.world

    # Bootstrap the world: init storage, load config, then re-assert STORAGE_DIR
    # (config.load can reset it back to ./storage).
    from app.core import paths as paths_mod
    paths_mod.init(world_dir)
    from app.core.config import load as load_config
    load_config(paths_mod.get_config_path())
    os.environ["STORAGE_DIR"] = str((_project_root / world_dir).resolve())
    paths_mod.init(world_dir)

    from app.models.character import (
        list_available_characters,
        get_character_config,
        save_character_config,
    )

    viewer = args.viewer.strip()
    if not viewer:
        print("--viewer must not be empty", file=sys.stderr)
        return 2

    names = list_available_characters()
    changed = 0
    for name in names:
        cfg = get_character_config(name) or {}
        cur = cfg.get("gallery_allowed_viewers")
        lst = [str(v) for v in cur if v] if isinstance(cur, list) else []
        if viewer in lst:
            print(f"  = {name}: already allowed")
            continue
        lst.append(viewer)
        if args.dry_run:
            print(f"  ~ {name}: would add -> {lst}")
        else:
            cfg["gallery_allowed_viewers"] = lst
            save_character_config(name, cfg)
            print(f"  + {name}: added -> {lst}")
        changed += 1

    verb = "would change" if args.dry_run else "updated"
    print(f"Done: {changed}/{len(names)} characters {verb} "
          f"(world={args.world}, viewer={viewer!r}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
