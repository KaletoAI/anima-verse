#!/usr/bin/env python3
"""Publish a ready-made pack ZIP to a marketplace catalog — for packs that are
not built from a world, i.e. the ``skill_package`` ZIPs of the private packs
repository (``anima-verse-packs/build_catalog.py`` writes ``dist/<pkg>.zip``).

Same storage as the Publish button (``app/core/marketplace_store.py``): the ZIP
becomes a release asset of the catalog repository and a line in that type's
index. The catalog (URL + token) is read from a world's config, exactly as the
server would read it; nothing in that world is written.

Usage:
    ./.venv/bin/python scripts/marketplace_publish.py \\
        --world "worlds/<world>" --catalog "<catalog name>" \\
        --type skill_package --zip ../anima-verse-packs/dist/<pkg>.zip \\
        --name "<display name>" [--slug <slug>] [--description "..."] [--tags a,b]

``--slug`` defaults to the ZIP's file name without ``.zip``; the pack id is
``<type>-<slug>``. Publishing the same content and text again is a no-op.
"""
import argparse
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--world", required=True, help="world directory whose config names the catalog")
    ap.add_argument("--catalog", required=True, help="catalog display name (content_marketplace.catalogs[].name)")
    ap.add_argument("--type", required=True, dest="pack_type", help="pack type, e.g. skill_package")
    ap.add_argument("--zip", required=True, type=Path)
    ap.add_argument("--name", required=True)
    ap.add_argument("--slug", default="")
    ap.add_argument("--description", default="")
    ap.add_argument("--tags", default="")
    args = ap.parse_args()

    from app.core import paths
    paths.init(args.world)
    from app.core import config
    config.load(paths.get_config_path())
    from app.core.content_io import _pack_slug
    from app.core.marketplace_store import (CatalogRepo, PackUpload, content_hash,
                                            publish)

    catalogs = (config.get("content_marketplace", {}) or {}).get("catalogs") or []
    catalog = next((c for c in catalogs if isinstance(c, dict)
                    and (c.get("name") or "").strip() == args.catalog), None)
    if not catalog:
        print(f"no catalog named {args.catalog!r} in {args.world}")
        return 2
    if not (catalog.get("auth_token") or "").strip():
        print("the catalog has no auth token — publishing needs write access to releases")
        return 2
    data = args.zip.read_bytes()
    slug = _pack_slug(args.slug or args.zip.stem)
    entry = {"id": f"{args.pack_type}-{slug}", "type": args.pack_type, "slug": slug,
             "name": args.name, "description": args.description,
             "tags": [t.strip() for t in args.tags.split(",") if t.strip()],
             "content_sha256": content_hash(data), "facts": {}}
    repo = CatalogRepo.from_url(catalog["url"], catalog["auth_token"])
    if len(data) > repo.host_limit:
        print(f"{args.zip.name} is over the host's per-file limit")
        return 1
    result = publish(repo, args.pack_type, [PackUpload(
        entry=entry, zip_bytes=data, checksum_sha256=hashlib.sha256(data).hexdigest())])[0]
    print(f"{result['pack_id']}: {result['status']}"
          + (f" — {result.get('error')}" if result["status"] == "error" else "")
          + (f" — {result.get('download_url')}" if result.get("download_url") else ""))
    for w in result.get("warnings") or []:
        print(f"warning: {w}")
    return 0 if result["status"] != "error" else 1


if __name__ == "__main__":
    sys.exit(main())
