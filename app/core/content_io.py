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
import re
import shutil
import zipfile
import zlib
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

def _referenced_prop_ids(loc: Dict[str, Any]) -> List[str]:
    """Every prop id the location NAMES, sorted.

    Three places store one: a furnishing placement (``layout.props[].prop_id``),
    the optional frame/leaf prop of a wall opening
    (``layout.openings[].prop_id``, world_ops._sanitize_opening) and the
    location's own ``default_door_prop_id``, which fills every door that names
    none (2026-08-27). All three are stored references, so all three are a
    DEPENDENCY of the pack — a prop that does not travel renders as "missing"
    forever on the far side.

    The GROUND room is an ordinary member of ``rooms`` and its reduced layout
    (§ A13a) carries ``props`` like any other, so it is covered by walking the
    room list; there is no second place to look.
    """
    out: Set[str] = set()
    default_door = str(loc.get("default_door_prop_id") or "").strip()
    if default_door:
        out.add(default_door)
    for room in (loc.get("rooms") or []):
        if not isinstance(room, dict):
            continue
        layout = room.get("layout")
        if not isinstance(layout, dict):
            continue
        for key in ("props", "openings"):
            for entry in (layout.get(key) or []):
                if not isinstance(entry, dict):
                    continue
                pid = (entry.get("prop_id") or "").strip()
                if pid:
                    out.add(pid)
    return sorted(out)


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
        prop_ids = _referenced_prop_ids(loc)
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


def _remap_room_refs(loc: Dict[str, Any], room_id_map: Dict[str, str]) -> None:
    """Point every stored ROOM REFERENCE at the freshly minted id.

    The import mints a new id for every room but the reserved ground, so a
    reference that still names the SOURCE world's id is a dangling one — the
    same class of bug the ``gallery_meta`` remap fixes for images. Three
    fields carry a room id; ``entry_room`` is remapped by the caller, the two
    here sit inside the geometry:

    * ``map3d.boundary_openings[].room`` — which room a pass-through at the
      LOCATION edge leads into (§ A13a),
    * ``rooms[].layout.openings[].to`` — a wall opening's connectivity target.
      The literal ``outside`` is not a room and is left alone; so is any other
      id the map does not know, which then simply stays dangling instead of
      being pointed at an unrelated room.
    """
    if not room_id_map:
        return
    map3d = loc.get("map3d")
    if isinstance(map3d, dict):
        for op in (map3d.get("boundary_openings") or []):
            if isinstance(op, dict) and op.get("room") in room_id_map:
                op["room"] = room_id_map[op["room"]]
    for room in (loc.get("rooms") or []):
        if not isinstance(room, dict):
            continue
        layout = room.get("layout")
        if not isinstance(layout, dict):
            continue
        for op in (layout.get("openings") or []):
            if isinstance(op, dict) and op.get("to") in room_id_map:
                op["to"] = room_id_map[op["to"]]


def _sanitize_imported_location(loc: Dict[str, Any]) -> List[str]:
    """Run the location's geometry through the WORLD'S OWN sanitizers, in
    place, and report in plain words what did not survive.

    THE IMPORTER NEVER WRITES RAW JSON INTO THE WORLD. ``_save_world_data``
    stores a location dict verbatim in the ``meta`` blob, so a ZIP is a direct
    write path into the world — without this step an archive could put a shape
    into the DB that no editor, no API call and no map-layout apply could ever
    produce. These are the exact same functions the ordinary save path uses
    (``world_ops.create_location_with_extras`` /
    ``update_location_with_extras`` / ``layout_apply``), so a pack cannot
    store what the admin UI could not.

    NO MIGRATION, BY DOCTRINE. A pre-v6 archive is not translated: what the
    sanitizer refuses is DROPPED, and every drop is named in the returned
    warnings so the user sees what fell away instead of finding a silently
    emptied room later. The two that bite hardest:

    * ``map3d.plan_width_m`` is not an input at all any more — it is DERIVED
      from the drawn boundary (v6 Nr. 2). A submitted value is ignored and the
      width recomputed here, so an archive can never smuggle a width that
      contradicts its own outline.
    * a boundary opening's ``edge`` is a 0-based INDEX into that boundary
      (v6 Nr. 5). The letters N/S/E/W have no reader left, so such an entry is
      dropped, and so is an index the outline does not have.
    """
    from app.core.world_ops import (_GROUND_FORBIDDEN, _sanitize_map3d,
                                    _sanitize_room_layout,
                                    sanitize_ground_layout)
    from app.models.world import GROUND_ROOM_ID

    warnings: List[str] = []

    if "map3d" in loc:
        raw = loc.get("map3d")
        if not isinstance(raw, dict):
            loc.pop("map3d", None)
            warnings.append("map3d dropped — it is not an object")
        elif raw:
            clean = _sanitize_map3d(raw)
            raw_bo = raw.get("boundary_openings")
            n_raw = len(raw_bo) if isinstance(raw_bo, list) else 0
            n_clean = len(clean.get("boundary_openings") or [])
            if n_clean < n_raw:
                warnings.append(
                    f"map3d: {n_raw - n_clean} of {n_raw} boundary opening(s) "
                    "dropped — since contract v6 an edge is a 0-based INDEX "
                    "into the drawn boundary; letter edges (N/S/E/W) and "
                    "indices the boundary does not have have no reader left")
            if raw.get("boundary") and not clean.get("boundary"):
                warnings.append(
                    "map3d: the boundary was dropped — fewer than 3 distinct "
                    "points, or a shape with no extent, encloses no area")
            raw_width = raw.get("plan_width_m")
            new_width = clean.get("plan_width_m")
            if raw_width is not None and new_width != raw_width:
                warnings.append(
                    f"map3d: the stored plan_width_m ({raw_width!r}) was "
                    "ignored — it is DERIVED from the drawn boundary, never "
                    f"imported (now: {new_width!r})")
            gone = sorted(set(raw) - set(clean)
                          - {"boundary", "boundary_openings", "plan_width_m"})
            if gone:
                warnings.append(
                    "map3d: field(s) the v6 contract no longer knows were "
                    "dropped: " + ", ".join(gone))
            if clean:
                loc["map3d"] = clean
            else:
                loc.pop("map3d", None)
                warnings.append(
                    "map3d: nothing survived — the location has no area and "
                    "lands on the map as a bare pin")

    for room in (loc.get("rooms") or []):
        if not isinstance(room, dict) or "layout" not in room:
            continue
        raw = room.get("layout")
        label = str(room.get("name") or room.get("id") or "?")
        is_ground = room.get("id") == GROUND_ROOM_ID
        if is_ground:
            clean = sanitize_ground_layout(raw)
            stripped = ([k for k in _GROUND_FORBIDDEN if k in raw]
                        if isinstance(raw, dict) else [])
            if stripped:
                warnings.append(
                    "ground layout: room-geometry field(s) dropped ("
                    + ", ".join(stripped)
                    + ") — the ground has no rect, its frame IS the location "
                      "(§ A13a)")
        else:
            clean = _sanitize_room_layout(raw)
            if raw and not clean:
                warnings.append(
                    f"room '{label}': the whole layout was dropped — x/y/w/d "
                    "in METRES are what makes a layout (contract v6 Nr. 2)")
        if clean and isinstance(raw, dict):
            for key, what in (("props", "prop placement"),
                              ("markers", "marker"),
                              ("openings", "opening")):
                n_raw = len(raw.get(key) or [])
                n_clean = len(clean.get(key) or [])
                if n_clean < n_raw:
                    warnings.append(
                        f"room '{label}': {n_raw - n_clean} of {n_raw} "
                        f"{what}(s) dropped by the sanitizer")
        if clean:
            room["layout"] = clean
        else:
            room.pop("layout", None)

    return warnings


def import_location_from_zip(content: bytes) -> Dict[str, Any]:
    """Import a location ZIP. Always creates a new location (new UUID).

    Everything the rooms reference travels with it: gallery files land in a
    fresh `world_gallery/<new-id>/` directory, the 3D models in
    `locations/<new-id>/model3d/` (renamed to the new room ids), bundled props
    are installed unless the world already has them, and embedded room items
    are created unless they already exist. A placement whose prop is neither
    bundled nor present is reported in `props_missing` — never swallowed.

    THE GEOMETRY GOES THROUGH THE WORLD'S OWN SANITIZERS
    (:func:`_sanitize_imported_location`) before the first byte reaches the DB,
    and what they refuse is reported in `warnings` rather than translated —
    see that function for the no-migration doctrine this rests on.

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
    # The remaining room references sit inside the geometry, and the geometry
    # itself only reaches the DB through the world's own sanitizers — see
    # _sanitize_imported_location for why a ZIP is a write path that must not
    # bypass them.
    _remap_room_refs(loc, room_id_map)
    sanitize_warnings = _sanitize_imported_location(loc)

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
    from app.core.prop_field_migration import normalize_prop_sidecar
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
        # A pack authored before 2026-08-25 carries the size, subject, ground
        # offset and markers on the PROP record, which nothing reads any more.
        # The boot migration ran long before this import, so the sidecar is
        # brought into the current shape here — the same one-way transform,
        # applied where the file lands.
        normalize_prop_sidecar(pid)
        props_imported.append(pid)

    # Read from the SANITIZED location: a placement the sanitizer already threw
    # away (a prop id the store would refuse) is no longer a dependency, and
    # reporting it as "missing" would send the user hunting for a prop that
    # nothing references any more. That drop is reported on its own, in
    # `warnings`.
    referenced = set(_referenced_prop_ids(loc))
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
    for line in sanitize_warnings:
        logger.warning("Location import %s: %s", new_loc_id, line)
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
        # What the sanitizers refused, in plain words. Empty for a pack from a
        # current world; non-empty is the no-migration doctrine made visible —
        # the UI shows these lines instead of letting the user find an emptied
        # room weeks later.
        "warnings": sanitize_warnings,
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

    Every failure mode is a ``ValueError`` and every one of them happens
    BEFORE the first byte on disk changes — a broken ZIP never costs the
    prop that is already there.
    """
    from app.core.prop_field_migration import normalize_prop_sidecar
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
        # The whole payload is decoded BEFORE anything on disk is touched: an
        # overwrite deletes the existing prop, and a ZIP that only fails
        # halfway through reading (CRC error, truncated member) would leave a
        # partial directory — possibly without the sidecar, i.e. a prop that
        # is no longer a prop. Nothing here is streamed, the archive already
        # sits in memory anyway.
        payload: Dict[str, bytes] = {}
        try:
            for member in zf.namelist():
                if not member.startswith("files/"):
                    continue
                safe = _safe_relpath(member[len("files/"):])
                if not safe:
                    continue                      # Zip-Slip / directory entry
                payload[safe] = zf.read(member)
        except (zipfile.BadZipFile, zlib.error, EOFError,
                OSError, RuntimeError) as e:
            # The exports are ZIP_DEFLATED, so a corrupt member usually fails
            # inside zlib (zlib.error) or runs out of stream (EOFError) —
            # neither is an OSError. RuntimeError = encrypted member. All of
            # them mean the same thing: the ZIP cannot be trusted. ValueError
            # keeps the routes' 400 mapping intact (BadZipFile & Co. would be
            # a 500).
            raise ValueError(f"unreadable ZIP member: {e}")
        # The master record is what MAKES a prop.
        if "sidecar.json" not in payload:
            raise ValueError("files/sidecar.json missing — not a prop export")

        dst = _prop_dir(pid)
        if dst is not None and dst.is_dir():
            if not overwrite:
                return {"status": "exists", "prop_id": pid}
            shutil.rmtree(dst, ignore_errors=True)

        dst = _prop_dir(pid, create=True)
        for rel, blob in payload.items():
            target = dst / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(blob)
        count = len(payload)
    finally:
        zf.close()

    # A ZIP authored before 2026-08-25 puts size, subject, ground offset and
    # markers on the master record, which nothing reads any more — the same
    # one-way transform the boot migration runs, applied where the file lands.
    normalize_prop_sidecar(pid)
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
# Map layout (metre snapshot)
# ---------------------------------------------------------------------------

def export_map_layout_to_zip() -> bytes:
    """Snapshot where every location stands, in world METRES.

    The locations themselves are NOT included — a row is only
    ``{id, name, pos_x, pos_z, yaw_deg}``. An unplaced location is a row with
    null coordinates, not a missing row: the layout describes the whole world,
    and "this one stands nowhere" is part of that.
    """
    from app.models.world import list_locations
    rows: List[Dict[str, Any]] = []
    for loc in list_locations():
        rows.append({
            "id": loc.get("id"),
            "name": loc.get("name"),
            "pos_x": loc.get("pos_x"),
            "pos_z": loc.get("pos_z"),
            "yaw_deg": loc.get("yaw_deg"),
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


def _layout_row_coords(entry: Dict[str, Any], index: int):
    """The validated ``(pos_x, pos_z, yaw_deg)`` of ONE layout row.

    Uses the writer's own guard (``world._finite_number``) so there is exactly
    ONE rule for what a coordinate is — a row this accepts is a row
    ``update_location_position`` will accept. Raises ``ValueError`` naming the
    row, so the caller can refuse the whole file instead of stopping halfway.

    Either coordinate being null means "unplaced" (what the exporter writes for
    a location that stands nowhere); the rotation is dropped with it, exactly
    as unplacing does.
    """
    from app.models.world import _finite_number

    def _where() -> str:
        ident = (entry.get("id") or "?")
        name = (entry.get("name") or "").strip()
        return f"row {index} ({ident}" + (f', "{name}"' if name else "") + ")"

    pos_x, pos_z = entry.get("pos_x"), entry.get("pos_z")
    if pos_x is None or pos_z is None:
        return None, None, None
    try:
        x = _finite_number(pos_x, "pos_x")
        z = _finite_number(pos_z, "pos_z")
        yaw = (None if entry.get("yaw_deg") is None
               else _finite_number(entry.get("yaw_deg"), "yaw_deg"))
    except ValueError as e:
        raise ValueError(f"{_where()}: {e}")
    return x, z, yaw


def import_map_layout_from_zip(content: bytes) -> Dict[str, Any]:
    """Apply a saved metre layout to the current world.

    Matching is by ID ONLY. A layout is a statement about THIS world's
    locations; matching by name would hand a position to whatever happens to
    carry the same label, and the caller cannot tell afterwards. Unknown ids
    are reported as ``skipped_unknown`` and nothing is created; rows that are
    not objects at all are reported as ``skipped_invalid`` rather than
    silently vanishing.

    Positions go through ``update_location_position`` — never straight into
    the row. That is the path that takes the OCCUPANTS along: a character
    standing in a location keeps its place in the location's local frame, so
    re-placing (and re-turning) a location moves the people in it with it.
    A row with null coordinates unplaces its location, which is what the
    exporter wrote for an unplaced one.

    ALL OR NOTHING. Every row is read and validated before the FIRST write —
    the grid-era shape and every coordinate — because each
    ``update_location_position`` persists on its own: a bad row discovered
    halfway would leave the world with half a layout and the caller with a
    400 instead of a report. Two refusals, both before anything moves:

    * grid-era ZIPs (rows of ``grid_x``/``grid_y``): their cell numbers mean
      nothing on a metre map. The test is the MISSING ``pos_x`` key — a
      present-but-null one is the legitimate "unplaced" row.
    * a coordinate that is not a finite number (``"abc"``, ``NaN``, ``1e999``):
      the error names the offending row.
    """
    from app.models.world import list_locations, update_location_position

    try:
        zf = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as e:
        raise ValueError(f"invalid ZIP: {e}")

    _read_manifest(zf, "map_layout")
    rows = json.loads(zf.read("db/map_layout.json"))
    if not isinstance(rows, list):
        raise ValueError("db/map_layout.json must be a list")
    zf.close()

    entries: List[Dict[str, Any]] = []
    skipped_invalid: List[Dict[str, Any]] = []
    for i, row in enumerate(rows):
        if isinstance(row, dict):
            entries.append(row)
        else:
            skipped_invalid.append({"index": i, "type": type(row).__name__})

    if any("pos_x" not in r for r in entries):
        raise ValueError(
            "grid-era layout (grid_x/grid_y) — no longer importable; "
            "the world map is measured in metres. Export the layout again "
            "from a current world.")

    # Validation pass over EVERY row before the first write (see the docstring).
    plan = [(entry, _layout_row_coords(entry, i)) for i, entry in enumerate(entries)]

    known_ids = {l.get("id") for l in list_locations() if l.get("id")}

    applied: List[str] = []
    skipped_unknown: List[Dict[str, Any]] = []

    for entry, (pos_x, pos_z, yaw_deg) in plan:
        ent_id = entry.get("id") or ""
        ent_name = (entry.get("name") or "").strip()
        if ent_id not in known_ids:
            skipped_unknown.append({"id": ent_id, "name": ent_name})
            continue
        loc = update_location_position(ent_id, pos_x, pos_z, yaw_deg)
        applied.append((loc or {}).get("name") or ent_name or ent_id)

    logger.info("Map import: %d applied, %d unknown, %d invalid",
                len(applied), len(skipped_unknown), len(skipped_invalid))
    return {
        "status": "success",
        "applied": applied,
        "skipped_unknown": skipped_unknown,
        "skipped_invalid": skipped_invalid,
        "applied_count": len(applied),
        "skipped_unknown_count": len(skipped_unknown),
        "skipped_invalid_count": len(skipped_invalid),
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
# Collections (ONE ZIP holding N ordinary packs)
# ---------------------------------------------------------------------------

def export_zip_for(pack_type: str, entity_id: str) -> bytes:
    """The ONE export dispatcher: pack type + entity id -> pack ZIP bytes.

    Everything that turns an entity of the active world into a distributable
    pack goes through here — the marketplace publish route, the collection
    builder below. ``states`` ignores ``entity_id``: there is exactly one
    world-level block.
    """
    if pack_type == "character":
        # Local import: character_io reaches back into this module, so a
        # top-level import would close the cycle.
        from app.core.character_io import export_character_to_zip
        return export_character_to_zip(entity_id)
    if pack_type == "item":
        return export_item_to_zip(entity_id)
    if pack_type == "rule":
        return export_rule_to_zip(entity_id)
    if pack_type == "location":
        return export_location_to_zip(entity_id)
    if pack_type == "prop":
        return export_prop_to_zip(entity_id)
    if pack_type == "states":
        return export_states_to_zip()
    raise ValueError(f"publish not supported for pack type {pack_type!r}")


def _pack_slug(text: str) -> str:
    """Filename-safe lowercase slug; empty input yields ``"pack"``."""
    base = re.sub(r"[^a-zA-Z0-9._-]+", "-", (text or "").strip()).strip("-_.").lower()
    return base or "pack"


def _pack_display_name(manifest: Dict[str, Any], pack_type: str, entity_id: str) -> str:
    """Human-readable name of a sub-pack, taken from its OWN manifest.

    The name in the collection index is what the marketplace and the import
    dialog show, so it must be the pack's real name — not whatever id the
    caller happened to pass in.
    """
    for key in ("character_name", "location_name", "prop_name", "name"):
        value = (manifest.get(key) or "").strip()
        if value:
            return value
    return entity_id.strip() or pack_type


def export_collection_to_zip(name: str, entries: List[Dict[str, str]]) -> bytes:
    """Bundle N entities into ONE collection pack.

    ``entries`` is ``[{"type": ..., "id": ...}]``. Each entry is exported
    through :func:`export_zip_for` and stored as ``packs/<slug>.zip``; the
    slug is ``<type>-<name>`` and a repeated slug is numbered (``-2``, ``-3``)
    instead of overwriting its predecessor.

    The manifest is the format the installer already consumes
    (``content_packs._install_collection``, ``scripts/make_collection_pack.py``)::

        {"version": 1, "type": "collection", "name": ...,
         "contents": [{"type", "name", "file"}, ...]}

    A failing sub-export aborts the whole thing: a collection that silently
    misses what the user picked is worse than no download at all.
    """
    if not entries:
        raise ValueError("collection needs at least one entry")

    contents: List[Dict[str, str]] = []
    payload: List[Tuple[str, bytes]] = []
    used: Set[str] = set()

    for entry in entries:
        pack_type = (entry.get("type") or "").strip()
        entity_id = (entry.get("id") or "").strip()
        if pack_type == "collection":
            raise ValueError("a collection cannot contain another collection")
        blob = export_zip_for(pack_type, entity_id)
        try:
            with zipfile.ZipFile(io.BytesIO(blob)) as sub:
                sub_manifest = json.loads(sub.read("manifest.json"))
        except (zipfile.BadZipFile, KeyError, json.JSONDecodeError) as e:
            raise ValueError(f"{pack_type} {entity_id!r} produced an unreadable pack: {e}")
        label = _pack_display_name(sub_manifest, pack_type, entity_id)

        slug = f"{_pack_slug(pack_type)}-{_pack_slug(label)}"
        candidate, n = slug, 1
        while f"packs/{candidate}.zip" in used:
            n += 1
            candidate = f"{slug}-{n}"
        arcname = f"packs/{candidate}.zip"
        used.add(arcname)

        contents.append({"type": pack_type, "name": label, "file": arcname})
        payload.append((arcname, blob))

    manifest = {
        "version": MANIFEST_VERSION,
        "type": "collection",
        "name": (name or "").strip() or "Collection",
        "contents": contents,
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        for arcname, blob in payload:
            # The inner packs are already deflated — storing them again only
            # costs CPU.
            zf.writestr(arcname, blob, compress_type=zipfile.ZIP_STORED)
    logger.info("Collection export: %s (%d packs)", manifest["name"], len(contents))
    return buf.getvalue()


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
        elif mtype == "collection":
            # A collection lists its SUB-PACKS. The element id is the
            # ZIP-internal file path — that is what the install dispatch
            # filters the selection on. `exists` stays False: what a sub-pack
            # will do is the sub-importer's business, and a collection must
            # not claim to know it up front.
            for entry in (manifest.get("contents") or []):
                if isinstance(entry, dict):
                    elements.append({"kind": entry.get("type") or "?",
                                     "id": entry.get("file") or "",
                                     "name": entry.get("name") or entry.get("file") or "?",
                                     "exists": False})
        elif mtype == "map_layout":
            elements.append({"kind": "map_layout", "id": "map_layout",
                             "name": f"Map layout ({manifest.get('count', '?')} positions)",
                             "exists": False})
        else:
            raise ValueError(f"unsupported export type: {mtype!r}")

        return {"type": mtype, "multi": len(elements) > 1, "elements": elements}
    finally:
        zf.close()
