#!/usr/bin/env python3
"""Export a world's importable content as per-entity ZIPs.

Uses the project's OWN export functions, so every ZIP is in exactly the
format the in-app Import accepts:

    Characters  -> characters/<name>.zip   (POST /characters/import)
    States      -> states.zip              (POST /admin/prompt-filters/import)
    Rules       -> rules/<id>.zip          (POST /rules/import)         [world scope only]
    Locations   -> locations/<name>_<id>.zip (POST /world/locations/import)
    Map layout  -> map_layout.zip          (POST /world/map/import)     [bonus: positions in metres]

Usage:
    python scripts/export_world_content.py <world_storage_dir> <output_dir>
    python scripts/export_world_content.py worlds/demo exports/demo

Read-only: never writes to the world's world.db / world.json.
"""
import re
import sys
from pathlib import Path


def _safe(name: str) -> str:
    return re.sub(r"[^\w.-]+", "_", name or "").strip("_") or "unnamed"


def main() -> None:
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    world_dir, out_dir = sys.argv[1], sys.argv[2]

    import app.core.paths as paths
    paths.init(world_dir)
    try:
        from app.core import config
        config.load()
    except Exception as e:  # config is not needed for reading world content
        print(f"[warn] config.load failed (continuing): {e}")

    from app.core.character_io import export_character_to_zip
    from app.core.content_io import (
        export_states_to_zip, export_rule_to_zip,
        export_location_to_zip, export_map_layout_to_zip,
        export_items_to_bundle_zip)
    from app.models.character import list_available_characters
    from app.models.world import list_locations
    from app.models.rules import load_rules
    from app.models.inventory import list_items

    out = Path(out_dir)
    for sub in ("characters", "locations", "rules"):
        (out / sub).mkdir(parents=True, exist_ok=True)

    summary: dict = {}

    chars = list_available_characters() or []
    n = 0
    for name in chars:
        try:
            data = export_character_to_zip(name, include_chats=True, include_stories=True)
            (out / "characters" / f"{_safe(name)}.zip").write_bytes(data)
            n += 1
        except Exception as e:
            print(f"[err] character {name!r}: {e}")
    summary["characters"] = f"{n}/{len(chars)}"

    locs = list_locations() or []
    n = 0
    for loc in locs:
        lid = loc.get("id")
        if not lid:
            continue
        try:
            data = export_location_to_zip(lid)
            (out / "locations" / f"{_safe(loc.get('name') or lid)}_{str(lid)[:8]}.zip").write_bytes(data)
            n += 1
        except Exception as e:
            print(f"[err] location {lid!r}: {e}")
    summary["locations"] = f"{n}/{len(locs)}"

    rules = load_rules() or []
    world_rules = [r for r in rules if r.get("_origin") in ("world", "world override")]
    n = 0
    for r in world_rules:
        rid = (r.get("id") or "").strip()
        if not rid:
            continue
        try:
            (out / "rules" / f"{_safe(rid)}.zip").write_bytes(export_rule_to_zip(rid))
            n += 1
        except Exception as e:
            print(f"[err] rule {rid!r}: {e}")
    summary["rules"] = f"{n}/{len(world_rules)} (world-scope; {len(rules) - len(world_rules)} shared skipped)"

    # Items (world-scope only; shared library items ship with the repo). Bonus —
    # characters reference item_ids, so the item library must exist before a
    # character re-import or inventories break.
    item_ids = [it.get("id") for it in (list_items() or [])
                if it.get("id") and not it.get("_shared")]
    if item_ids:
        try:
            (out / "items_bundle.zip").write_bytes(export_items_to_bundle_zip(item_ids))
            summary["items"] = f"items_bundle.zip ({len(item_ids)})"
        except Exception as e:
            print(f"[err] items: {e}")
            summary["items"] = f"FAILED: {e}"
    else:
        summary["items"] = "none (world-scope)"

    try:
        (out / "states.zip").write_bytes(export_states_to_zip())
        summary["states"] = "states.zip"
    except Exception as e:
        print(f"[err] states: {e}")
        summary["states"] = f"FAILED: {e}"

    try:
        (out / "map_layout.zip").write_bytes(export_map_layout_to_zip())
        summary["map_layout"] = "map_layout.zip"
    except Exception as e:
        print(f"[err] map_layout: {e}")
        summary["map_layout"] = f"FAILED: {e}"

    print(f"\nEXPORT {world_dir} -> {out_dir}")
    for k, v in summary.items():
        print(f"  {k:12} {v}")


if __name__ == "__main__":
    main()
