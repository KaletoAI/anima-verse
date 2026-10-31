#!/usr/bin/env python3
"""Rename item definitions of a world by id.

Usage:
    ./.venv/bin/python scripts/rename_items.py --world NAME --rename "ITEM_ID=New name" [--rename ...]
        [--worlds-dir DIR]   (default: <repo>/worlds)
        [--apply]

Only the ``name`` changes (``inventory.update_item``): ids, prompt fragments,
images and meshes stay as they are — a name reaches no render, so no cached
image or model is invalidated. Every owner of the item sees the new name.
The LLMs match items by name, so a name that does not say what the piece is
("Red Mieder" for an off-the-shoulder top), or one in another language than
the rest of the wardrobe, makes them guess.

Dry run by default: prints old -> new. ``--apply`` writes, and only with the
server STOPPED (it refuses while ``.pids/main.pid`` names a live process);
the old names are saved first to
``<repo>/migration_backup/rename-items-<stamp>.json`` — renaming back is the
same command with the old names.
"""
import argparse
import json
import os
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


def _server_running() -> bool:
    pid_file = REPO / ".pids" / "main.pid"
    try:
        os.kill(int(pid_file.read_text().strip()), 0)
    except (OSError, ValueError):
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--world", required=True)
    parser.add_argument("--rename", action="append", required=True, metavar="ITEM_ID=NAME")
    parser.add_argument("--worlds-dir", type=Path, default=REPO / "worlds")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    renames = {}
    for spec in args.rename:
        item_id, sep, name = spec.partition("=")
        if not sep or not item_id.strip() or not name.strip():
            print(f"--rename wants ITEM_ID=NAME, got {spec!r}", file=sys.stderr)
            return 2
        renames[item_id.strip()] = name.strip()
    world = (args.worlds_dir / args.world).resolve()
    if not (world / "world.db").is_file():
        print(f"no world.db in {world}", file=sys.stderr)
        return 2
    if args.apply and _server_running():
        print("the server is running — stop it before --apply", file=sys.stderr)
        return 2

    from app.core import paths
    paths.init(str(world))
    from app.models.inventory import get_item, update_item
    from app.core.timeutils import utc_now

    old = {}
    for item_id, name in renames.items():
        item = get_item(item_id)
        if not item:
            print(f"no item {item_id}", file=sys.stderr)
            return 2
        old[item_id] = item.get("name", "")
        print(f"{item_id}: {old[item_id]!r} -> {name!r}")
    if not args.apply:
        print("dry run, nothing written (add --apply)")
        return 0
    backup = REPO / "migration_backup" / f"rename-items-{utc_now().strftime('%Y%m%dT%H%M%S')}.json"
    backup.parent.mkdir(parents=True, exist_ok=True)
    backup.write_text(json.dumps({"world": args.world, "names": old}, ensure_ascii=False, indent=2))
    for item_id, name in renames.items():
        if not update_item(item_id, {"name": name}):
            print(f"{item_id}: not written", file=sys.stderr)
            return 1
    print(f"renamed {len(renames)} item(s); old names in {backup}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
