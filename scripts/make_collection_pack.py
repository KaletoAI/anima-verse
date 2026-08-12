#!/usr/bin/env python3
"""Bundle per-location export ZIPs into ONE marketplace "collection" pack.

Moving a world today means exporting N locations and importing N ZIPs by hand.
This packs them into a single collection ZIP that the marketplace installer
unpacks and installs one by one.

Usage:
    ./.venv/bin/python scripts/make_collection_pack.py <dir-with-location-zips> <out.zip> [--name "My locations"]

    # typical round trip
    ./.venv/bin/python scripts/export_world_content.py worlds/demo exports/demo
    ./.venv/bin/python scripts/make_collection_pack.py exports/demo/locations exports/demo-locations.zip \
        --name "Demo locations"

Every `*.zip` directly inside the input dir is taken. `map_layout.zip` is
skipped explicitly (with a warning): it carries grid coordinates of the SOURCE
world and would drag a legacy grid into a metre world. ZIPs without
`db/location.json` are warned about and skipped as well.

Output layout (exactly what `_install_collection` expects, see below):

    manifest.json      {"version": 1, "type": "collection", "name": ...,
                        "contents": [{"type": "location", "name": ..., "file": "packs/<x>.zip"}, ...]}
    packs/<x>.zip      the untouched per-location export ZIPs

Import (fuer den User)
----------------------
Der Server muss laufen, und der Import braucht Admin-Rechte (alle
`/api/content/*`-Routen haengen an `require_admin`).

  1. Im Browser als Admin in der Ziel-Welt anmelden (z.B. http://localhost:8000/play).
  2. Collection hochladen — der EINZIGE Pfad, der `collection` versteht:

         POST /api/content/install_upload?pack_type=collection
         curl -b cookies.txt -F "file=@exports/demo-locations.zip" \
              "http://localhost:8000/api/content/install_upload?pack_type=collection"

     (`cookies.txt` = Session-Cookie des Admin-Logins, z.B. per
      `curl -c cookies.txt -X POST http://localhost:8000/auth/login ...`.)
  3. Antwort pruefen: `result.installed` / `result.failed` und die Liste
     `result.results[]` nennt pro Location success / exists / failed.

WICHTIG: Der generische Upload-Dialog der UI (Import-Button →
`/api/content/preview` + `/api/content/import`) funktioniert fuer Collections
NICHT — `preview_import_zip` kennt den Typ `collection` nicht und antwortet mit
"unsupported export type: 'collection'". Die einzelnen Location-ZIPs aus
`packs/` lassen sich dort weiterhin einzeln importieren.

Jede Location wird beim Import als NEUE Location mit frischer UUID angelegt
(`import_location_from_zip`) — es wird nie etwas ueberschrieben.

Layout evidence (verified 2026-08-09):
    app/routes/content_packs.py:441-506  `_install_collection` — reads
        `manifest.json`, requires `type == "collection"` and a non-empty
        `contents` list; per entry uses `type` (must be in SUPPORTED_TYPES and
        not "collection") and `file` (a path inside the ZIP, by convention
        `packs/<name>.zip`), then dispatches to the normal importer.
    app/routes/content_packs.py:607-624  `/install_upload` — `pack_type` must
        be in SUPPORTED_TYPES (which includes "collection", line 38).
    app/core/content_io.py:431-475  `export_location_to_zip` — the inner packs:
        `manifest.json` (type "location") + `db/location.json` + `files/gallery/*`.

Read-only w.r.t. the input dir; writes only <out.zip>.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Mirror of app/routes/content_packs.py:38 — imported so the check can never
# drift from the installer.
try:
    from app.routes.content_packs import SUPPORTED_TYPES
except Exception:  # running outside the repo venv
    SUPPORTED_TYPES = {"character", "item", "item_bundle", "rule", "states",
                       "location", "collection", "skill_package"}

MANIFEST_VERSION = 1
SKIP_FILES = {"map_layout.zip"}


def _inspect_location_zip(path: Path) -> Tuple[bool, str, str]:
    """(ok, location_name, reason). Minimal validation: a location pack must
    carry db/location.json plus a manifest of type "location"."""
    try:
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
            if "db/location.json" not in names:
                return False, "", "no db/location.json"
            if "manifest.json" not in names:
                return False, "", "no manifest.json"
            manifest = json.loads(zf.read("manifest.json"))
            mtype = manifest.get("type")
            if mtype != "location":
                return False, "", f"manifest type is {mtype!r}, expected 'location'"
            name = (manifest.get("location_name") or "").strip()
            if not name:
                loc = json.loads(zf.read("db/location.json"))
                name = (loc.get("name") or "").strip()
            return True, name or path.stem, ""
    except zipfile.BadZipFile as e:
        return False, "", f"not a ZIP ({e})"
    except (json.JSONDecodeError, KeyError, UnicodeDecodeError) as e:
        return False, "", f"unreadable pack ({e})"


def build(in_dir: Path, out_path: Path, coll_name: str) -> int:
    """Write the collection pack. Returns the number of bundled locations."""
    zips = sorted(p for p in in_dir.glob("*.zip") if p.is_file())
    if not zips:
        print(f"[error] no *.zip files in {in_dir}")
        return 0

    contents: List[Dict[str, Any]] = []
    payload: List[Tuple[str, bytes]] = []
    used: set[str] = set()

    for zp in zips:
        if zp.name in SKIP_FILES:
            print(f"[warn] skipping {zp.name} — grid coordinates of the source "
                  f"world, must never enter a metre world")
            continue
        ok, loc_name, reason = _inspect_location_zip(zp)
        if not ok:
            print(f"[warn] skipping {zp.name} — {reason}")
            continue
        arcname = f"packs/{zp.name}"
        if arcname in used:
            print(f"[warn] skipping {zp.name} — duplicate file name")
            continue
        used.add(arcname)
        contents.append({"type": "location", "name": loc_name, "file": arcname})
        payload.append((arcname, zp.read_bytes()))
        print(f"[ok]   {loc_name}  ({zp.name})")

    if not contents:
        print("[error] nothing to bundle")
        return 0

    manifest = {
        "version": MANIFEST_VERSION,
        "type": "collection",
        "name": coll_name,
        "contents": contents,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        for arcname, data in payload:
            # Inner packs are already compressed — store them as-is.
            zf.writestr(arcname, data, compress_type=zipfile.ZIP_STORED)
    return len(contents)


def verify(out_path: Path) -> bool:
    """Re-open the written pack and apply the SAME expectations the installer
    has (`_install_collection`), then — if the app is importable — run a real
    `preview_import_zip` on every inner pack in a throwaway storage dir."""
    print("\n-- self-check --")
    try:
        zf = zipfile.ZipFile(out_path)
    except zipfile.BadZipFile as e:
        print(f"[FAIL] not a ZIP: {e}")
        return False
    ok = True
    with zf:
        names = set(zf.namelist())
        if "manifest.json" not in names:
            print("[FAIL] manifest.json missing")
            return False
        try:
            manifest = json.loads(zf.read("manifest.json"))
        except json.JSONDecodeError as e:
            print(f"[FAIL] manifest invalid JSON: {e}")
            return False
        if manifest.get("type") != "collection":
            print(f"[FAIL] manifest type {manifest.get('type')!r} != 'collection'")
            ok = False
        entries = manifest.get("contents")
        if not isinstance(entries, list) or not entries:
            print("[FAIL] contents empty or not a list")
            return False

        preview = None
        tmp_storage = None
        try:
            import app.core.paths as paths
            tmp_storage = tempfile.mkdtemp(prefix="collcheck_")
            paths.init(tmp_storage)
            from app.core.content_io import preview_import_zip as preview
        except Exception as e:
            print(f"[warn] preview unavailable ({e}) — structural check only")

        for entry in entries:
            sub_type = (entry.get("type") or "").strip()
            sub_file = (entry.get("file") or "").strip()
            label = entry.get("name") or sub_file
            if sub_type not in SUPPORTED_TYPES or sub_type == "collection":
                print(f"[FAIL] {label}: type {sub_type!r} would be skipped by the installer")
                ok = False
                continue
            if sub_file not in names:
                print(f"[FAIL] {label}: {sub_file!r} not in the ZIP")
                ok = False
                continue
            data = zf.read(sub_file)
            if preview is None:
                print(f"[ok]   {label}: {sub_file} present ({len(data)} bytes)")
                continue
            try:
                res = preview(data)
            except Exception as e:
                print(f"[FAIL] {label}: preview_import_zip rejected the pack: {e}")
                ok = False
                continue
            els = ", ".join(el.get("name") or el.get("id") or "?"
                            for el in res.get("elements") or [])
            print(f"[ok]   {label}: preview type={res.get('type')} -> {els}")
        if tmp_storage:
            import shutil
            shutil.rmtree(tmp_storage, ignore_errors=True)
    print("[OK] pack matches the installer's expectations" if ok
          else "[FAIL] pack would not install cleanly")
    return ok


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Bundle per-location export ZIPs into one collection pack.",
        epilog="See the module docstring for the import steps.")
    ap.add_argument("in_dir", help="directory containing the per-location *.zip exports")
    ap.add_argument("out_zip", help="path of the collection ZIP to write")
    ap.add_argument("--name", default="", help='collection name (default: "<dir> locations")')
    args = ap.parse_args()

    in_dir = Path(args.in_dir)
    out_path = Path(args.out_zip)
    if not in_dir.is_dir():
        print(f"[error] not a directory: {in_dir}")
        sys.exit(2)
    coll_name = args.name.strip() or f"{in_dir.resolve().parent.name} locations"

    count = build(in_dir, out_path, coll_name)
    if not count:
        sys.exit(1)
    if not verify(out_path):
        sys.exit(1)

    size_kb = out_path.stat().st_size / 1024
    print(f"\n{count} location(s) -> {out_path}  ({size_kb:.0f} KiB, name: {coll_name!r})")
    print("Import (server running, admin session in cookies.txt):")
    print(f'  curl -b cookies.txt -F "file=@{out_path}" \\\n'
          f'       "http://localhost:8000/api/content/install_upload?pack_type=collection"')


if __name__ == "__main__":
    main()
