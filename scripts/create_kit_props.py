#!/usr/bin/env python3
"""Create furniture-kit prop records; generate their images and meshes in Props.

Usage: .venv/bin/python scripts/create_kit_props.py --world demo [--kit rustic] [--dry-run]
"""
import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def create_kit_props(kits, *, dry_run=False):
    """Seed selected kits after the caller has initialized world storage."""
    from app.core import paths, props

    # list_props builds render records and may backfill sizes or queue LODs.
    # Identity needs only sidecars, keeping dry runs strictly read-only.
    library = [
        props.read_sidecar(sidecar.parent.name)
        for sidecar in sorted((paths.get_storage_dir() / "props").glob(
            f"*/{props.SIDECAR_NAME}"))
        if props.safe_prop_id(sidecar.parent.name)
    ]
    for kit_id, kit in kits.items():
        created = []
        existing = 0
        for seed in kit["props"]:
            tags = [f"kit:{kit_id}", f"role:{seed['role']}", "furniture-kit"]
            required = set(tags[:2])
            if any(
                prop.get("name") == seed["name"]
                and required.issubset({tag.lower() for tag in prop.get("tags", [])})
                for prop in library
            ):
                existing += 1
                continue
            if dry_run:
                created.append((None, seed["name"]))
                continue
            dims = {key: seed[key] for key in ("width_m", "depth_m", "height_m")}
            prop = props.create_prop(
                name=seed["name"], category=seed["category"], **dims,
                mount=seed["mount"], tags=tags, description=seed["prompt"],
            )
            if not props.set_variant_dims(prop["id"], 0, dims):
                raise RuntimeError(f"Could not pin dimensions for {prop['id']}")
            library.append(prop)
            created.append((prop["id"], seed["name"]))
        action = "would create" if dry_run else "created"
        print(f"{kit_id}: {len(created)} {action}, {existing} existing")
        for prop_id, name in created:
            print(f"  + {prop_id or '[dry-run]'}  {name}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--world", required=True, help="Existing world name under worlds/")
    with (REPO_ROOT / "shared/furniture/kits.json").open(encoding="utf-8") as handle:
        kits = json.load(handle)["kits"]
    parser.add_argument("--kit", choices=list(kits), help="Create only this kit")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args(argv)
    worlds_dir = (REPO_ROOT / "worlds").resolve()
    world_dir = (worlds_dir / args.world).resolve()
    if (Path(args.world).name != args.world or world_dir.parent != worlds_dir
            or not world_dir.is_dir()):
        parser.error("--world must name an existing directory directly under worlds/")

    from app.core import paths

    paths.init(world_dir)
    create_kit_props({args.kit: kits[args.kit]} if args.kit else kits,
                     dry_run=args.dry_run)


if __name__ == "__main__":
    main()
