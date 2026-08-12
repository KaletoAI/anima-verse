#!/usr/bin/env python3
"""Seed `image_prompt_map_2d` (the flat 2D map-icon prompt) for every location.

For each base location (clones inherit from their template) the 2D prompt is
seeded from the location description → name. The existing iso map prompt is
deliberately NOT used as a base because it is phrased "isometric 3d map view…",
which conflicts with a flat 2D icon. The generation pipeline wraps this base
with the flat-2D style suffix at render time, so we store only the descriptive
base. Idempotent (skips already-set unless --force).

Usage:
  python3 scripts/seed_map2d_prompts.py --world <world>
  python3 scripts/seed_map2d_prompts.py --world <world> --force --dry-run
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
    ap.add_argument("--force", action="store_true", help="Overwrite existing 2D prompts")
    ap.add_argument("--dry-run", action="store_true", help="Print changes only")
    args = ap.parse_args()

    world_dir = Path("worlds") / args.world
    from app.core import paths as paths_mod
    paths_mod.init(world_dir)
    from app.core.config import load as load_config
    load_config(paths_mod.get_config_path())
    os.environ["STORAGE_DIR"] = str((_project_root / world_dir).resolve())
    paths_mod.init(world_dir)

    from app.models.world import _load_world_data, _save_world_data

    data = _load_world_data()
    locations = data.get("locations", [])
    changed = 0
    skipped_clone = 0
    for loc in locations:
        if (loc.get("template_location_id") or "").strip():
            skipped_clone += 1  # clone inherits image_prompt_map_2d from template
            continue
        existing = (loc.get("image_prompt_map_2d") or "").strip()
        if existing and not args.force:
            print(f"  = {loc.get('name')}: already set")
            continue
        base = (loc.get("description") or loc.get("name") or "").strip()
        if not base:
            print(f"  ! {loc.get('name')}: no base text, skipped")
            continue
        if args.dry_run:
            print(f"  ~ {loc.get('name')}: would set -> {base[:70]!r}")
        else:
            loc["image_prompt_map_2d"] = base
            print(f"  + {loc.get('name')}: set -> {base[:70]!r}")
        changed += 1

    if changed and not args.dry_run:
        _save_world_data(data)

    verb = "would change" if args.dry_run else "updated"
    print(f"Done: {changed} base locations {verb}, {skipped_clone} clones inherit "
          f"(world={args.world}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
