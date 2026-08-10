"""Content Export / Import — ZIP bundles for items, locations, rules, etc.

Mirrors the pattern from `character_io.py` (manifest + db/ + files/), but
covers content types that are not character-owned:

    Item / item bundle  — DB row(s) + image file(s)
    Location            — DB row + rooms + gallery (TBD, phase 5)
    Map layout          — grid snapshot (TBD, phase 6)
    Rule                — DB row (TBD, phase 3)
    State block         — prompt-filters block (TBD, phase 4)

Each export carries a `manifest.json` at the root. The `type` field switches
the importer; the `version` field is the only forward-compat anchor.
"""
from __future__ import annotations

import io
import json
import shutil
import zipfile
from datetime import datetime

from app.core.timeutils import utc_now_iso
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from app.core.log import get_logger

logger = get_logger("content_io")

MANIFEST_VERSION = 1


def _safe_relpath(rel: str) -> Optional[str]:
    """Reject absolute / traversal paths; return normalized POSIX rel or None."""
    if not rel or rel.endswith("/"):
        return None
    if rel.startswith("/") or rel.startswith("\\"):
        return None
    if ".." in Path(rel).parts:
        return None
    return rel


def _read_manifest(zf: zipfile.ZipFile, expected_type: str) -> Dict[str, Any]:
    if "manifest.json" not in zf.namelist():
        raise ValueError("manifest.json missing — not a content pack")
    manifest = json.loads(zf.read("manifest.json"))
    if manifest.get("version") != MANIFEST_VERSION:
        raise ValueError(
            f"unsupported manifest version: {manifest.get('version')!r} "
            f"(expected {MANIFEST_VERSION})"
        )
    mtype = manifest.get("type", "")
    if mtype != expected_type:
        raise ValueError(
            f"manifest type mismatch: got {mtype!r}, expected {expected_type!r}"
        )
    return manifest


# ---------------------------------------------------------------------------
# Items
# ---------------------------------------------------------------------------

def _strip_runtime_keys(item: Dict[str, Any]) -> Dict[str, Any]:
    """Remove keys that are runtime-only or derived (not persisted)."""
    cleaned = dict(item)
    cleaned.pop("_shared", None)
    return cleaned


def _item_dir_for(item_id: str, *, shared: bool) -> Path:
    from app.models.inventory import _get_item_dir, _get_shared_item_dir
    return _get_shared_item_dir(item_id) if shared else _get_item_dir(item_id)


def _write_item_files(
    zf: zipfile.ZipFile, item: Dict[str, Any]
) -> List[str]:
    """Write the item's image (and any sibling files) into files/<item_id>/.

    Returns the relative file list for the manifest.
    """
    item_id = item["id"]
    is_shared = bool(item.get("_shared"))
    src_dir = _item_dir_for(item_id, shared=is_shared)
    written: List[str] = []
    if not src_dir.exists():
        return written
    for fp in sorted(src_dir.rglob("*")):
        if not fp.is_file():
            continue
        rel = fp.relative_to(src_dir).as_posix()
        arcname = f"files/{item_id}/{rel}"
        zf.write(fp, arcname)
        written.append(f"{item_id}/{rel}")
    return written


def embed_world_items(
    zf: zipfile.ZipFile, item_ids: Iterable[str]
) -> List[str]:
    """Write db/items.json + item_files/<id>/ for the given world items.

    Shared-library items are skipped (they ship with every world). Returns
    the embedded ids. Inverse: restore_embedded_items().
    """
    from app.models.inventory import get_item

    wanted = sorted({(iid or "").strip() for iid in item_ids} - {""})
    item_rows: List[Dict[str, Any]] = []
    for iid in wanted:
        it = get_item(iid)
        if not it or it.get("_shared"):
            continue  # shared-library items ship with every world
        item_rows.append(_strip_runtime_keys(it))
        src = _item_dir_for(iid, shared=False)
        if src.exists():
            for fp in sorted(src.rglob("*")):
                if fp.is_file():
                    zf.write(fp, f"item_files/{iid}/{fp.relative_to(src).as_posix()}")
    if item_rows:
        zf.writestr(
            "db/items.json",
            json.dumps(item_rows, ensure_ascii=False, indent=2),
        )
    return [it["id"] for it in item_rows]


def restore_embedded_items(zf: zipfile.ZipFile) -> List[str]:
    """Create every item from db/items.json that is missing in this world
    (existing items are never overwritten — references stay valid) and
    extract its item_files/. Returns the newly created ids.
    """
    from app.models.inventory import _save_items

    if "db/items.json" not in zf.namelist():
        return []
    try:
        item_rows = json.loads(zf.read("db/items.json"))
    except Exception as e:
        logger.warning("import: items.json invalid JSON: %s", e)
        return []
    if not isinstance(item_rows, list) or not item_rows:
        return []

    existing = _existing_item_ids()
    # items.json holds the flattened get_item() shape (meta spread to top
    # level, pieces -> outfit_piece, no updated_at). _save_items is the
    # inverse writer that rebuilds the meta/pieces/slots columns and stamps
    # created_at/updated_at — the generic _restore_table would drop those
    # columns and fail the updated_at NOT NULL constraint.
    # Keep original ids so outfit/inventory/room references stay valid.
    new_items = [
        it for it in item_rows
        if (it.get("id") or "").strip()
        and (it.get("id") or "").strip() not in existing
    ]
    if not new_items:
        return []
    _save_items(new_items)

    new_ids: List[str] = [(it.get("id") or "").strip() for it in new_items]
    for iid in new_ids:
        dest = _item_dir_for(iid, shared=False)
        prefix = f"item_files/{iid}/"
        for member in zf.namelist():
            if not member.startswith(prefix):
                continue
            safe = _safe_relpath(member[len(prefix):])
            if not safe:
                continue
            fp = dest / safe
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_bytes(zf.read(member))
    return new_ids


def export_item_to_zip(item_id: str) -> bytes:
    """Export a single item from the active world as a ZIP.

    Shared-library items (`shared/items/`) ship with the game repo and are
    not exportable — they're already part of any checkout, distributing
    them again would just cause merge collisions.
    """
    from app.models.inventory import get_item

    item = get_item(item_id)
    if not item:
        raise ValueError(f"item not found: {item_id!r}")
    if item.get("_shared"):
        raise ValueError(
            f"item {item_id!r} is in the shared library — shared items "
            "are distributed with the game, not via export/marketplace"
        )

    item_clean = _strip_runtime_keys(item)
    scope = "world"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        files = _write_item_files(zf, item)
        zf.writestr(
            "db/items.json",
            json.dumps([item_clean], ensure_ascii=False, indent=2),
        )
        manifest = {
            "version": MANIFEST_VERSION,
            "type": "item",
            "item_id": item_id,
            "exported_at": utc_now_iso(),
            "scope": scope,
            "files": sorted(files),
        }
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    return buf.getvalue()


def export_items_to_bundle_zip(item_ids: List[str]) -> bytes:
    """Export multiple items as a single bundle ZIP.

    Shared-library items are rejected — they ship with the game repo.
    """
    from app.models.inventory import get_item

    if not item_ids:
        raise ValueError("no item ids given")

    items: List[Dict[str, Any]] = []
    scopes: Dict[str, str] = {}
    for iid in item_ids:
        it = get_item(iid)
        if not it:
            raise ValueError(f"item not found: {iid!r}")
        if it.get("_shared"):
            raise ValueError(
                f"item {iid!r} is in the shared library — drop it from the bundle"
            )
        items.append(it)
        scopes[iid] = "world"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        all_files: List[str] = []
        for it in items:
            all_files.extend(_write_item_files(zf, it))
        cleaned = [_strip_runtime_keys(it) for it in items]
        zf.writestr(
            "db/items.json",
            json.dumps(cleaned, ensure_ascii=False, indent=2),
        )
        manifest = {
            "version": MANIFEST_VERSION,
            "type": "item_bundle",
            "items": [it["id"] for it in items],
            "scopes": scopes,
            "exported_at": utc_now_iso(),
            "files": sorted(all_files),
        }
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    return buf.getvalue()


def _next_free_item_id(base: str, taken: set) -> str:
    """Append a numeric suffix until the id is free."""
    if base not in taken:
        return base
    suffix = 2
    while f"{base}_{suffix}" in taken:
        suffix += 1
    return f"{base}_{suffix}"


def _existing_item_ids() -> set:
    from app.models.inventory import list_items, list_shared_items
    ids = {it.get("id") for it in list_items() if it.get("id")}
    ids.update(it.get("id") for it in list_shared_items() if it.get("id"))
    return ids


def _persist_imported_item(
    item: Dict[str, Any],
    *,
    target: str,
    overwrite: bool,
) -> Tuple[str, bool]:
    """Insert/replace an item row. Returns (final_id, renamed).

    `target` is 'world' or 'shared'. On overwrite=True an existing id is kept
    and its data replaced; on overwrite=False a new id with suffix is used.
    """
    from app.models.inventory import (
        _save_items,
        _load_shared_items,
        _save_shared_items,
        delete_item,
    )

    item = _strip_runtime_keys(item)
    original_id = item.get("id") or ""
    if not original_id:
        raise ValueError("item has no id")

    taken = _existing_item_ids()
    renamed = False
    final_id = original_id
    if original_id in taken:
        if overwrite:
            delete_item(original_id)
        else:
            final_id = _next_free_item_id(original_id, taken)
            renamed = final_id != original_id

    item["id"] = final_id
    item.setdefault("created_at", utc_now_iso())

    if target == "shared":
        shared = _load_shared_items()
        shared.append(item)
        _save_shared_items(shared)
    else:
        # Single-item UPSERT — _save_items iterates rows and upserts each.
        _save_items([item])
    return final_id, renamed


def _restore_item_files(
    zf: zipfile.ZipFile, original_id: str, final_id: str, *, shared: bool
) -> int:
    """Copy ZIP files for one item into its (possibly renamed) target dir."""
    dst_dir = _item_dir_for(final_id, shared=shared)
    if dst_dir.exists():
        shutil.rmtree(dst_dir)
    dst_dir.mkdir(parents=True, exist_ok=True)
    prefix = f"files/{original_id}/"
    count = 0
    for member in zf.namelist():
        if not member.startswith(prefix):
            continue
        rel = member[len(prefix):]
        safe = _safe_relpath(rel)
        if not safe:
            continue
        target = dst_dir / safe
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(zf.read(member))
        count += 1
    return count


def import_item_from_zip(
    content: bytes,
    *,
    target: str = "auto",
    overwrite: bool = False,
) -> Dict[str, Any]:
    """Import a single-item ZIP. `target` ∈ {'auto', 'world', 'shared'}."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as e:
        raise ValueError(f"invalid ZIP: {e}")

    manifest = _read_manifest(zf, "item")
    rows = json.loads(zf.read("db/items.json"))
    if not isinstance(rows, list) or len(rows) != 1:
        raise ValueError("db/items.json must contain exactly one item")
    item = rows[0]
    original_id = item.get("id") or manifest.get("item_id") or ""
    if not original_id:
        raise ValueError("item id missing")

    if overwrite is False and original_id in _existing_item_ids():
        raise FileExistsError(
            f"Item '{original_id}' already exists. "
            f"Re-import with overwrite=true to replace, "
            f"or it will be imported under a suffixed id."
        )

    effective_target = target
    if effective_target == "auto":
        effective_target = manifest.get("scope") or "world"
    if effective_target not in ("world", "shared"):
        effective_target = "world"

    final_id, renamed = _persist_imported_item(
        item, target=effective_target, overwrite=overwrite,
    )
    file_count = _restore_item_files(
        zf, original_id, final_id, shared=(effective_target == "shared"),
    )
    zf.close()
    logger.info(
        "Item import: %s → %s (%s, files=%d, renamed=%s)",
        original_id, final_id, effective_target, file_count, renamed,
    )
    return {
        "status": "success",
        "item_id": final_id,
        "original_id": original_id,
        "scope": effective_target,
        "renamed": renamed,
        "files_imported": file_count,
    }


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------

def export_rule_to_zip(rule_id: str) -> bytes:
    """Export a single rule as a ZIP. Rules carry no files — manifest only.

    Shared baseline rules (origin=shared, lives in shared/rules/rules.json)
    ship with the repo and cannot be exported.
    """
    from app.models.rules import get_rule
    rule = get_rule(rule_id)
    if not rule:
        raise ValueError(f"rule not found: {rule_id!r}")
    if rule.get("_origin") == "shared":
        raise ValueError(
            f"rule {rule_id!r} is part of the shared baseline — shared rules "
            "are distributed with the game, not via export/marketplace"
        )
    rule_clean = {k: v for k, v in rule.items() if not k.startswith("_")}
    scope = "world"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "db/rules.json",
            json.dumps([rule_clean], ensure_ascii=False, indent=2),
        )
        manifest = {
            "version": MANIFEST_VERSION,
            "type": "rule",
            "rule_id": rule_id,
            "scope": scope,
            "exported_at": utc_now_iso(),
        }
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    return buf.getvalue()


def _existing_rule_ids() -> set:
    from app.models.rules import load_rules
    return {r.get("id") for r in load_rules() if r.get("id")}


def import_rule_from_zip(
    content: bytes,
    *,
    target: str = "auto",
    overwrite: bool = False,
) -> Dict[str, Any]:
    """Import a single rule. `target` ∈ {'auto', 'world', 'shared'}."""
    from app.models.rules import add_rule, delete_rule

    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as e:
        raise ValueError(f"invalid ZIP: {e}")

    manifest = _read_manifest(zf, "rule")
    rows = json.loads(zf.read("db/rules.json"))
    if not isinstance(rows, list) or len(rows) != 1:
        raise ValueError("db/rules.json must contain exactly one rule")
    rule = rows[0]
    original_id = rule.get("id") or manifest.get("rule_id") or ""
    if not original_id:
        raise ValueError("rule id missing")

    rule.pop("_origin", None)
    rule.pop("_storage", None)

    effective_target = target
    if effective_target == "auto":
        effective_target = manifest.get("scope") or "world"
    if effective_target not in ("world", "shared"):
        effective_target = "world"

    if original_id in _existing_rule_ids():
        if not overwrite:
            raise FileExistsError(
                f"Rule '{original_id}' already exists. "
                f"Re-import with overwrite=true to replace."
            )
        # add_rule does upsert-by-id within the same scope; for cross-scope
        # overwrite we delete the existing entry first.
        delete_rule(original_id, target_dir="")
    zf.close()
    created = add_rule(rule, target_dir=effective_target)
    logger.info(
        "Rule import: %s (%s, overwrite=%s)",
        original_id, effective_target, overwrite,
    )
    return {
        "status": "success",
        "rule_id": created.get("id"),
        "scope": effective_target,
        "overwritten": overwrite,
    }


# ---------------------------------------------------------------------------
# Locations
# ---------------------------------------------------------------------------

def export_location_to_zip(location_id: str) -> bytes:
    """Export a location as a ZIP: DB row + rooms + gallery, plus everything
    the rooms reference — 3D models, placed props and room items."""
    from app.models.world import (
        get_location_by_id, resolve_location, get_gallery_dir,
    )
    loc = get_location_by_id(location_id) or resolve_location(location_id)
    if not loc:
        raise ValueError(f"location not found: {location_id!r}")
    canonical_id = loc.get("id") or location_id

    gallery_dir = get_gallery_dir(canonical_id)
    file_entries: List[str] = []

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        if gallery_dir.exists():
            for fp in sorted(gallery_dir.rglob("*")):
                if not fp.is_file():
                    continue
                rel = fp.relative_to(gallery_dir).as_posix()
                arcname = f"files/gallery/{rel}"
                zf.write(fp, arcname)
                file_entries.append(f"gallery/{rel}")

        # 3D models (building + per-room GLBs, sidecars, selection.json). Clones
        # redirect to their template's store, same as the gallery does.
        from app.core.location_model3d import _model_dir, _owner_id
        model_dir = _model_dir(_owner_id(canonical_id))
        model3d_count = 0
        if model_dir.exists():
            for fp in sorted(model_dir.rglob("*")):
                if fp.is_file():
                    zf.write(fp, f"files/model3d/{fp.relative_to(model_dir).as_posix()}")
                    model3d_count += 1

        # Referenced props travel as a dependency — a placement without its prop
        # renders as "missing" forever (room_recipe.py:395).
        from app.core.props import _prop_dir
        prop_ids = sorted({
            (p.get("prop_id") or "").strip()
            for room in (loc.get("rooms") or [])
            for p in ((room.get("layout") or {}).get("props") or [])
            if isinstance(p, dict) and (p.get("prop_id") or "").strip()
        })
        bundled_props: List[str] = []
        for pid in prop_ids:
            d = _prop_dir(pid)
            if not d or not d.is_dir():
                continue
            for fp in sorted(d.rglob("*")):
                if fp.is_file():
                    zf.write(fp, f"props/{pid}/{fp.relative_to(d).as_posix()}")
            bundled_props.append(pid)

        # Room items (rooms[].items[].item_id) — same embed shape as character ZIPs.
        item_ids = sorted({
            (it.get("item_id") or "").strip()
            for room in (loc.get("rooms") or [])
            for it in (room.get("items") or [])
            if isinstance(it, dict) and (it.get("item_id") or "").strip()
        })
        embedded_items = embed_world_items(zf, item_ids)

        zf.writestr(
            "db/location.json",
            json.dumps(loc, ensure_ascii=False, indent=2),
        )
        manifest = {
            "version": MANIFEST_VERSION,
            "type": "location",
            "location_id": canonical_id,
            "location_name": loc.get("name", ""),
            "room_count": len(loc.get("rooms") or []),
            "image_count": sum(
                1 for f in file_entries
                if f.startswith("gallery/") and any(
                    f.lower().endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".webp")
                )
            ),
            "model3d_file_count": model3d_count,
            "prop_ids": bundled_props,
            "embedded_items": embedded_items,
            "exported_at": utc_now_iso(),
            "files": sorted(file_entries),
        }
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    return buf.getvalue()


def _free_location_name(name: str) -> str:
    """If `name` is taken, append `(2)`, `(3)`, …"""
    from app.models.world import list_locations
    taken = {(l.get("name") or "").strip() for l in list_locations()}
    if name not in taken:
        return name
    suffix = 2
    while f"{name} ({suffix})" in taken:
        suffix += 1
    return f"{name} ({suffix})"


def _remap_model3d_basename(name: str, room_id_map: Dict[str, str]) -> str:
    """``room_<old>…`` -> ``room_<new>…`` (filename OR bare stem).

    The model store names its files after the SUBJECT: ``building[_<ts>]`` for
    the location shell, ``room_<room_id>[_<ts>]`` for a room — plus a ``.json``
    sidecar per file and the ``selection.json`` keys, which are bare stems.
    Import mints new room ids, so every one of those names has to follow;
    ``building*`` and anything else is left alone.
    """
    if not name.startswith("room_"):
        return name
    rest = name[len("room_"):]
    for old, new in room_id_map.items():
        if old and (rest == old or rest.startswith(old + "_") or rest.startswith(old + ".")):
            return "room_" + new + rest[len(old):]
    return name


def import_location_from_zip(content: bytes) -> Dict[str, Any]:
    """Import a location ZIP. Always creates a new location (new UUID).

    Everything the rooms reference travels with it: gallery files land in a
    fresh `world_gallery/<new-id>/` directory, the 3D models in
    `locations/<new-id>/model3d/` (renamed to the new room ids), bundled props
    are installed unless the world already has them, and embedded room items
    are created unless they already exist. A placement whose prop is neither
    bundled nor present is reported in `props_missing` — never swallowed.

    The location itself lands UNPLACED; the user positions it in the map
    editor. The known_locations status is NOT auto-granted to existing
    characters — discovery happens organically on entry (memory:
    project_known_locations_strict).
    """
    import uuid
    from app.models.world import (
        GROUND_ROOM_ID, _load_world_data, _save_world_data, get_gallery_dir,
    )

    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as e:
        raise ValueError(f"invalid ZIP: {e}")

    _read_manifest(zf, "location")
    loc = json.loads(zf.read("db/location.json"))
    if not isinstance(loc, dict):
        raise ValueError("db/location.json must be an object")

    # Fresh ids — clones are flattened: the imported location becomes a
    # STANDALONE copy. `template_location_id` is the clone marker
    # (app/models/world.py), and an export carries it verbatim; leaving it in
    # would bind the copy to a template id from the SOURCE world, and then
    # _gallery_owner_id would serve gallery/models from that id (never from
    # the files written here), _resolve_clones would merge a foreign template
    # over the fresh rooms, and cleanup_orphan_clones would delete the record
    # outright — an unplaced clone counts as off-map.
    new_loc_id = uuid.uuid4().hex[:8]
    loc["id"] = new_loc_id
    loc.pop("template_location_id", None)

    rooms = loc.get("rooms") or []
    room_id_map: Dict[str, str] = {}
    for room in rooms:
        old_id = room.get("id") or ""
        # The ground room's id is RESERVED, not authored — every location has
        # exactly this one and the code addresses it by the constant. Renaming
        # it would leave the import with a nameless ordinary room and NO
        # ground. It maps to itself, which makes the model3d remap a no-op for
        # its files as well.
        new_id = old_id if old_id == GROUND_ROOM_ID else uuid.uuid4().hex[:8]
        room_id_map[old_id] = new_id
        room["id"] = new_id
        # Rooms can carry prompt_changed flag; re-trigger generation on import.
        if room.get("image_prompt_day") or room.get("image_prompt_night"):
            room["prompt_changed"] = True
    if loc.get("entry_room") and loc["entry_room"] in room_id_map:
        loc["entry_room"] = room_id_map[loc["entry_room"]]

    loc["name"] = _free_location_name((loc.get("name") or "Imported location").strip())
    if loc.get("image_prompt_day") or loc.get("image_prompt_night"):
        loc["prompt_changed"] = True
    # Placement is reset — the import lands unplaced (pos_x IS NULL); the user
    # places it in the map editor. Without this the copy sits exactly ON the
    # original. grid_* still appears in pre-E1 ZIPs.
    for key in ("grid_x", "grid_y", "pos_x", "pos_z", "yaw_deg"):
        loc.pop(key, None)

    data = _load_world_data()
    locations = data.get("locations", [])
    locations.append(loc)
    data["locations"] = locations
    _save_world_data(data)

    # Move gallery files
    gallery_dir = get_gallery_dir(new_loc_id)
    if gallery_dir.exists():
        shutil.rmtree(gallery_dir)
    gallery_dir.mkdir(parents=True, exist_ok=True)
    file_count = 0
    prefix = "files/gallery/"
    for member in zf.namelist():
        if not member.startswith(prefix):
            continue
        rel = member[len(prefix):]
        safe = _safe_relpath(rel)
        if not safe:
            continue
        target = gallery_dir / safe
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(zf.read(member))
        file_count += 1

    # Remap the image→room mapping in gallery_meta.json to the new room ids.
    # The file is copied verbatim and still references the OLD room ids; without
    # this the imported room images stay orphaned (each room falls back to the
    # location default), which reads as "room images were not imported".
    meta_path = gallery_dir / "gallery_meta.json"
    if meta_path.exists() and room_id_map:
        try:
            gmeta = json.loads(meta_path.read_text(encoding="utf-8"))
            rooms_map = gmeta.get("rooms")
            if isinstance(rooms_map, dict) and rooms_map:
                gmeta["rooms"] = {
                    img: room_id_map.get(rid, rid) for img, rid in rooms_map.items()
                }
                meta_path.write_text(
                    json.dumps(gmeta, ensure_ascii=False, indent=2), encoding="utf-8"
                )
        except Exception as e:
            logger.warning("Location import: remap gallery_meta rooms failed: %s", e)

    # 3D models. The import is always a standalone copy, so the model store's
    # owner is the new location id itself. The files are named after the OLD
    # room ids — every basename goes through the remap; a tier file may sit in
    # a subdirectory, so only the basename is touched, never the path.
    from app.core.location_model3d import _model_dir
    model_prefix = "files/model3d/"
    model_dir: Optional[Path] = None
    model3d_files = 0
    for member in zf.namelist():
        if not member.startswith(model_prefix):
            continue
        safe = _safe_relpath(member[len(model_prefix):])
        if not safe:
            continue
        if model_dir is None:
            model_dir = _model_dir(new_loc_id, create=True)
        head, _sep, base = safe.rpartition("/")
        new_base = _remap_model3d_basename(base, room_id_map)
        target = model_dir / (f"{head}/{new_base}" if head else new_base)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(zf.read(member))
        model3d_files += 1

    # selection.json names the ACTIVE file per stem ({stem: {tier: filename}}) —
    # both sides carry old room ids and have to follow the rename, or the
    # imported rooms serve nothing.
    if model_dir is not None and room_id_map:
        sel_path = model_dir / "selection.json"
        if sel_path.exists():
            try:
                sel = json.loads(sel_path.read_text(encoding="utf-8"))
                if isinstance(sel, dict):
                    sel = {
                        _remap_model3d_basename(stem, room_id_map): (
                            {tier: _remap_model3d_basename(str(fn), room_id_map)
                             for tier, fn in tiers.items()}
                            if isinstance(tiers, dict) else tiers
                        )
                        for stem, tiers in sel.items()
                    }
                    sel_path.write_text(
                        json.dumps(sel, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception as e:
                logger.warning("Location import: remap model3d selection failed: %s", e)

    # Bundled props are a DEPENDENCY, not content of their own: an existing
    # prop is never overwritten (other locations place the same id), a missing
    # one is installed, and a placement whose prop is neither is reported.
    from app.core.props import _prop_dir, safe_prop_id
    # An id the prop store would refuse is NOT a dependency this ZIP satisfies:
    # it is filtered out BEFORE the props_missing subtraction below, so a
    # bundled-but-invalid id is reported as missing instead of counting as
    # delivered.
    bundled = sorted({m.split("/", 2)[1] for m in zf.namelist()
                      if m.startswith("props/") and m.count("/") >= 2
                      and safe_prop_id(m.split("/", 2)[1])})
    props_imported: List[str] = []
    props_existing: List[str] = []
    for pid in bundled:
        dest = _prop_dir(pid)
        if dest is not None and dest.is_dir():
            props_existing.append(pid)          # never overwrite an existing prop
            continue
        dest = _prop_dir(pid, create=True)
        prefix = f"props/{pid}/"
        for member in zf.namelist():
            if not member.startswith(prefix):
                continue
            safe = _safe_relpath(member[len(prefix):])
            if not safe:
                continue
            target = dest / safe
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zf.read(member))
        props_imported.append(pid)

    referenced = {
        (p.get("prop_id") or "").strip()
        for room in (loc.get("rooms") or [])
        for p in ((room.get("layout") or {}).get("props") or [])
        if isinstance(p, dict) and (p.get("prop_id") or "").strip()
    }
    props_missing = sorted(
        pid for pid in referenced - set(bundled)
        if not (_prop_dir(pid) and _prop_dir(pid).is_dir()))
    if props_missing:
        logger.warning(
            "Location import: %s (id=%s) places props that are neither bundled "
            "nor known here — they will render as missing: %s",
            loc["name"], new_loc_id, ", ".join(props_missing),
        )

    # Room items — created only when this world does not have the id yet.
    items_imported = restore_embedded_items(zf)
    zf.close()

    logger.info(
        "Location import: %s (id=%s, %d gallery files, %d model files, "
        "%d props installed, %d items restored)",
        loc["name"], new_loc_id, file_count, model3d_files,
        len(props_imported), len(items_imported),
    )
    return {
        "status": "success",
        "location_id": new_loc_id,
        "location_name": loc["name"],
        "files_imported": file_count,
        "room_count": len(rooms),
        "model3d_files": model3d_files,
        "props_imported": props_imported,
        "props_existing": props_existing,
        "props_missing": props_missing,
        "items_imported": items_imported,
    }


# ---------------------------------------------------------------------------
# Props
# ---------------------------------------------------------------------------

def export_prop_to_zip(prop_id: str) -> bytes:
    """Export ONE prop of the active world as a ZIP.

    A prop is a pure file entity (``props/<prop_id>/``, no DB row), so the
    export is the whole directory under ``files/`` plus the manifest: the
    master ``sidecar.json``, every mesh with its own sidecar, the selection
    and the source render.
    """
    from app.core.props import _prop_dir, get_prop, safe_prop_id

    pid = safe_prop_id(prop_id)
    if not pid:
        raise ValueError(f"invalid prop id: {prop_id!r}")
    prop = get_prop(pid)
    if not prop:
        raise ValueError(f"prop not found: {prop_id!r}")
    src = _prop_dir(pid)
    if src is None or not src.is_dir():
        raise ValueError(f"prop directory missing: {pid!r}")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        files: List[str] = []
        for fp in sorted(src.rglob("*")):
            if not fp.is_file():
                continue
            rel = fp.relative_to(src).as_posix()
            zf.write(fp, f"files/{rel}")
            files.append(rel)
        manifest = {
            "version": MANIFEST_VERSION,
            "type": "prop",
            "prop_id": pid,
            "prop_name": prop.get("name") or pid,
            "exported_at": utc_now_iso(),
            "files": sorted(files),
        }
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    return buf.getvalue()


def import_prop_from_zip(
    content: bytes,
    *,
    overwrite: bool = False,
) -> Dict[str, Any]:
    """Import a single-prop ZIP into the active world.

    The prop id is KEPT — room placements reference it by id, so a renamed
    prop would arrive orphaned. An id that already exists is therefore never
    silently duplicated: without ``overwrite`` the import reports
    ``{"status": "exists"}`` and changes nothing, with it the directory is
    replaced wholesale (stale meshes of the old prop must not survive).
    """
    from app.core.props import _prop_dir, read_sidecar, safe_prop_id

    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as e:
        raise ValueError(f"invalid ZIP: {e}")
    try:
        manifest = _read_manifest(zf, "prop")
        raw_id = (manifest.get("prop_id") or "").strip()
        pid = safe_prop_id(raw_id)
        if not pid:
            raise ValueError(f"invalid prop id in manifest: {raw_id!r}")
        # The master record is what MAKES a prop — checked BEFORE anything is
        # deleted, so a truncated ZIP can never wipe an existing prop and
        # leave a record-less ghost directory behind.
        if "files/sidecar.json" not in zf.namelist():
            raise ValueError("files/sidecar.json missing — not a prop export")

        dst = _prop_dir(pid)
        if dst is not None and dst.is_dir():
            if not overwrite:
                return {"status": "exists", "prop_id": pid}
            shutil.rmtree(dst, ignore_errors=True)

        dst = _prop_dir(pid, create=True)
        count = 0
        for member in zf.namelist():
            if not member.startswith("files/"):
                continue
            safe = _safe_relpath(member[len("files/"):])
            if not safe:
                continue
            target = dst / safe
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zf.read(member))
            count += 1
    finally:
        zf.close()

    name = read_sidecar(pid).get("name") or manifest.get("prop_name") or pid
    logger.info("Prop import: %s (%s, files=%d)", pid, name, count)
    return {
        "status": "success",
        "prop_id": pid,
        "prop_name": name,
        "files_imported": count,
    }


# ---------------------------------------------------------------------------
# States (prompt-filters block)
# ---------------------------------------------------------------------------

def export_states_to_zip() -> bytes:
    """Export the whole world-level prompt-filters block as a single ZIP."""
    from app.core.prompt_filters import _load_world
    rows = _load_world()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "db/prompt_filters.json",
            json.dumps(rows, ensure_ascii=False, indent=2),
        )
        manifest = {
            "version": MANIFEST_VERSION,
            "type": "states",
            "count": len(rows),
            "exported_at": utc_now_iso(),
        }
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    return buf.getvalue()


def _upsert_prompt_filter(conn, entry: Dict[str, Any]) -> None:
    """Insert/update a single prompt_filters row. Mirrors prompt_filters_save."""
    drops = entry.get("drop_blocks") or []
    if not isinstance(drops, list):
        drops = []
    meta = entry.get("meta") or {}
    conn.execute(
        """
        INSERT INTO prompt_filters (id, condition, label, drop_blocks,
                                    prompt_modifier, enabled, meta,
                                    icon, image_modifier)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            condition=excluded.condition,
            label=excluded.label,
            drop_blocks=excluded.drop_blocks,
            prompt_modifier=excluded.prompt_modifier,
            enabled=excluded.enabled,
            meta=excluded.meta,
            icon=excluded.icon,
            image_modifier=excluded.image_modifier
        """,
        (
            (entry.get("id") or "").strip(),
            (entry.get("condition") or "").strip(),
            (entry.get("label") or "").strip(),
            json.dumps(drops, ensure_ascii=False),
            (entry.get("prompt_modifier") or "").strip(),
            1 if entry.get("enabled", True) else 0,
            json.dumps(meta, ensure_ascii=False),
            (entry.get("icon") or "").strip(),
            (entry.get("image_modifier") or "").strip(),
        ),
    )


def import_states_from_zip(
    content: bytes,
    *,
    replace_all: bool = False,
    selected_ids: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    """Import a states pack.

    `replace_all=False` (default): upsert each filter (merge with existing).
    `replace_all=True`: wipe the world-level prompt_filters table first.
    `selected_ids`: if given, only import filters whose id is in the set.
    """
    from app.core.db import transaction

    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as e:
        raise ValueError(f"invalid ZIP: {e}")

    _read_manifest(zf, "states")
    rows = json.loads(zf.read("db/prompt_filters.json"))
    if not isinstance(rows, list):
        raise ValueError("db/prompt_filters.json must be a list")
    zf.close()

    count = 0
    with transaction() as conn:
        if replace_all:
            conn.execute("DELETE FROM prompt_filters")
        for entry in rows:
            if not isinstance(entry, dict) or not (entry.get("id") or "").strip():
                continue
            if selected_ids is not None and entry["id"] not in selected_ids:
                continue
            _upsert_prompt_filter(conn, entry)
            count += 1
    logger.info("States import: %d filter(s) (replace_all=%s)", count, replace_all)
    return {
        "status": "success",
        "filters_imported": count,
        "replaced_all": replace_all,
    }


# ---------------------------------------------------------------------------
# Map layout (grid snapshot)
# ---------------------------------------------------------------------------

def export_map_layout_to_zip() -> bytes:
    """Snapshot every location's grid position. Locations themselves are NOT
    included — only id/name/grid_x/grid_y."""
    from app.models.world import list_locations
    rows: List[Dict[str, Any]] = []
    for loc in list_locations():
        rows.append({
            "id": loc.get("id"),
            "name": loc.get("name"),
            "grid_x": loc.get("grid_x"),
            "grid_y": loc.get("grid_y"),
        })
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "db/map_layout.json",
            json.dumps(rows, ensure_ascii=False, indent=2),
        )
        manifest = {
            "version": MANIFEST_VERSION,
            "type": "map_layout",
            "count": len(rows),
            "exported_at": utc_now_iso(),
        }
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    return buf.getvalue()


def import_map_layout_from_zip(
    content: bytes,
    *,
    match_by: str = "auto",
) -> Dict[str, Any]:
    """Apply a saved map layout to the current world.

    `match_by` ∈ {'auto', 'id', 'name'}:
      'auto' tries id first, falls back to name.

    Locations that don't exist locally are skipped and reported.
    """
    from app.models.world import (
        _load_world_data, _save_world_data, list_locations,
    )

    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as e:
        raise ValueError(f"invalid ZIP: {e}")

    _read_manifest(zf, "map_layout")
    rows = json.loads(zf.read("db/map_layout.json"))
    if not isinstance(rows, list):
        raise ValueError("db/map_layout.json must be a list")
    zf.close()

    by_id = {l.get("id"): l for l in list_locations() if l.get("id")}
    by_name = {(l.get("name") or "").strip(): l for l in list_locations() if l.get("name")}

    applied: List[str] = []
    skipped: List[Dict[str, Any]] = []

    data = _load_world_data()
    locations = data.get("locations", [])
    live_by_id = {l.get("id"): l for l in locations if l.get("id")}

    for entry in rows:
        if not isinstance(entry, dict):
            continue
        ent_id = entry.get("id") or ""
        ent_name = (entry.get("name") or "").strip()
        target: Optional[Dict[str, Any]] = None
        if match_by in ("auto", "id") and ent_id in by_id:
            target = live_by_id.get(ent_id)
        if target is None and match_by in ("auto", "name") and ent_name in by_name:
            target = live_by_id.get(by_name[ent_name].get("id"))
        if target is None:
            skipped.append({"id": ent_id, "name": ent_name, "reason": "not found"})
            continue

        if entry.get("grid_x") is not None:
            target["grid_x"] = int(entry["grid_x"])
        if entry.get("grid_y") is not None:
            target["grid_y"] = int(entry["grid_y"])
        applied.append(target.get("name") or target.get("id") or "?")

    _save_world_data(data)
    logger.info("Map import: %d applied, %d skipped", len(applied), len(skipped))
    return {
        "status": "success",
        "applied": applied,
        "skipped": skipped,
        "applied_count": len(applied),
        "skipped_count": len(skipped),
    }


def import_bundle_from_zip(
    content: bytes,
    *,
    target: str = "auto",
    overwrite: bool = False,
    selected_ids: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    """Import an item bundle ZIP (multiple items).

    `selected_ids`: if given, only items whose id is in the set are imported
    (the rest are skipped); selecting an existing item implies overwrite.
    """
    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as e:
        raise ValueError(f"invalid ZIP: {e}")

    manifest = _read_manifest(zf, "item_bundle")
    rows = json.loads(zf.read("db/items.json"))
    if not isinstance(rows, list) or not rows:
        raise ValueError("db/items.json must be a non-empty list")

    if selected_ids is not None:
        rows = [r for r in rows if r.get("id") in selected_ids]
        overwrite = True  # explicit per-element selection = overwrite the chosen

    if overwrite is False:
        existing = _existing_item_ids()
        clash = [r.get("id") for r in rows if r.get("id") in existing]
        if clash:
            raise FileExistsError(
                f"{len(clash)} item(s) already exist: {', '.join(clash[:5])}"
                + ("…" if len(clash) > 5 else "")
                + " — re-import with overwrite=true to replace."
            )

    scopes = manifest.get("scopes") or {}
    results: List[Dict[str, Any]] = []
    for item in rows:
        original_id = item.get("id") or ""
        if not original_id:
            continue
        effective_target = target
        if effective_target == "auto":
            effective_target = scopes.get(original_id) or "world"
        if effective_target not in ("world", "shared"):
            effective_target = "world"
        final_id, renamed = _persist_imported_item(
            item, target=effective_target, overwrite=overwrite,
        )
        files = _restore_item_files(
            zf, original_id, final_id, shared=(effective_target == "shared"),
        )
        results.append({
            "item_id": final_id,
            "original_id": original_id,
            "scope": effective_target,
            "renamed": renamed,
            "files_imported": files,
        })
    zf.close()
    logger.info("Bundle import: %d item(s)", len(results))
    return {
        "status": "success",
        "imported": results,
        "count": len(results),
    }


# ---------------------------------------------------------------------------
# Generic import preview (cross-type element listing + clash flags)
# ---------------------------------------------------------------------------

def _character_exists(name: str) -> bool:
    from app.core.db import get_connection
    try:
        conn = get_connection()
        return bool(conn.execute("SELECT 1 FROM characters WHERE name=?", (name,)).fetchone())
    except Exception:
        return False


def _existing_prompt_filter_ids() -> set:
    from app.core.db import get_connection
    try:
        conn = get_connection()
        return {r[0] for r in conn.execute("SELECT id FROM prompt_filters").fetchall()}
    except Exception:
        return set()


def preview_import_zip(content: bytes) -> Dict[str, Any]:
    """Inspect ANY project export ZIP and list its importable elements without
    importing anything. Generic across all export types.

    Returns ``{type, multi, elements: [{kind, id, name, exists}]}`` where
    ``exists`` flags an element that would overwrite an existing one.
    """
    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as e:
        raise ValueError(f"invalid ZIP: {e}")
    try:
        if "manifest.json" not in zf.namelist():
            raise ValueError("manifest.json missing — not a project export")
        manifest = json.loads(zf.read("manifest.json"))
        mtype = manifest.get("type") or ("character" if manifest.get("character_name") else "")
        elements: List[Dict[str, Any]] = []

        def _rows(path: str) -> List[Dict[str, Any]]:
            if path not in zf.namelist():
                return []
            data = json.loads(zf.read(path))
            return data if isinstance(data, list) else []

        if mtype == "character" or manifest.get("character_name"):
            mtype = "character"
            name = (manifest.get("character_name") or "").strip()
            elements.append({"kind": "character", "id": name, "name": name,
                             "exists": _character_exists(name)})
        elif mtype in ("item", "item_bundle"):
            existing = _existing_item_ids()
            for r in _rows("db/items.json"):
                iid = (r.get("id") or "").strip()
                if iid:
                    elements.append({"kind": "item", "id": iid, "name": r.get("name") or iid,
                                     "exists": iid in existing})
        elif mtype == "rule":
            existing = _existing_rule_ids()
            for r in _rows("db/rules.json"):
                rid = (r.get("id") or "").strip()
                if rid:
                    elements.append({"kind": "rule", "id": rid,
                                     "name": r.get("label") or r.get("name") or rid,
                                     "exists": rid in existing})
        elif mtype == "states":
            existing = _existing_prompt_filter_ids()
            for r in _rows("db/prompt_filters.json"):
                fid = (r.get("id") or "").strip()
                if fid:
                    elements.append({"kind": "state", "id": fid, "name": r.get("label") or fid,
                                     "exists": fid in existing})
        elif mtype == "location":
            # Location import always creates a NEW location (new UUID) — never
            # overwrites, so it stays ONE element. What travels with it is
            # spelled out in the name; old ZIPs simply report zeros.
            loc_name = manifest.get("location_name") or "Location"
            elements.append({
                "kind": "location",
                "id": manifest.get("location_id") or "location",
                "name": (
                    f"{loc_name} ({manifest.get('room_count', 0)} rooms, "
                    f"{manifest.get('model3d_file_count', 0)} model files, "
                    f"{len(manifest.get('prop_ids') or [])} props)"
                ),
                "exists": False,
            })
        elif mtype == "prop":
            pid = (manifest.get("prop_id") or "").strip()
            from app.core.props import _prop_dir
            d = _prop_dir(pid)
            elements.append({"kind": "prop", "id": pid,
                             "name": manifest.get("prop_name") or pid,
                             "exists": bool(d is not None and d.is_dir())})
        elif mtype == "map_layout":
            elements.append({"kind": "map_layout", "id": "map_layout",
                             "name": f"Map layout ({manifest.get('count', '?')} positions)",
                             "exists": False})
        else:
            raise ValueError(f"unsupported export type: {mtype!r}")

        return {"type": mtype, "multi": len(elements) > 1, "elements": elements}
    finally:
        zf.close()
