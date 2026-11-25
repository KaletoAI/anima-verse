"""One-time boot migration (plan-anhaenger Task 5, ruling D1 "migrate"): the item-image parts of a necklace and a belt
become part items.

Before design G a necklace's pendant and a belt's buckle were meshed from the HOST's item image
(``pendant: {from_image, size_mm}``, ``buckle: {from_image, size_mm}``). Part items replace both
(``accessory_parts``):

- a necklace with a stored ``pendant`` without a linked ``item`` gets a part item ``<host>_pendant`` (name
  "<host name> — pendant", empty text, ``jewellery: {kind: charm, charm: {size_mm: <old size>, mount: hang}}``, no slot);
  the host's image is copied BYTE-EQUAL to the part (so its ``accessory_pendant.current_psig`` is the same), and an
  accepted pendant mesh under ``jewellery/<host>/<psig>`` is moved to ``jewellery/<part>/<psig>`` — 0 hub jobs, the
  pendant stays. The host then links it: ``pendant: {item: <part>, size_mm: <old size>}`` (+ ``gem_color``).
- a belt's ``buckle`` without a linked ``item`` becomes ``None``: the old default put EVERY belt on ``from_image``, and
  a part made from a whole-belt image would mesh the whole belt again (finding G). The Wardrobe offers "Make buckle
  item" instead.

A part is never put in an inventory or a room (``accessory_parts``): whoever owned the host owns only the host.
It runs before anything normalizes the stored items again, so it reads the RAW ``outfit_piece.jewellery`` itself. A
host that already links an item is left alone (idempotent).

Two scopes, two markers (like ``painted_mode_migration``): the world's items once per world (world_kv ``FLAG``), the
shared library once per installation (top-level key ``SHARED_KEY`` of the shared items file). A part made for a shared
host is moved to the shared library with it (never a shared host with a world-only link).
"""
import os
import shutil
from typing import Any, Dict, List, Optional

from app.core.log import get_logger

logger = get_logger("accessory_parts_migration")

FLAG = "accessory_parts_v1"
SHARED_KEY = "accessory_parts_v1"


def _raw_jewellery(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    piece = item.get("outfit_piece") if isinstance(item.get("outfit_piece"), dict) else {}
    raw = piece.get("jewellery")
    return raw if isinstance(raw, dict) else None


def wants(item: Dict[str, Any]) -> Optional[str]:
    """``"necklace"`` / ``"belt"`` when ``item``'s stored jewellery still carries an image part without a link, else
    None."""
    if item.get("category") != "outfit_piece":
        return None
    raw = _raw_jewellery(item)
    if not raw:
        return None
    kind = raw.get("kind")
    key = "pendant" if kind == "necklace" else "buckle" if kind == "belt" else ""
    block = raw.get(key) if key else None
    if isinstance(block, dict) and not block.get("item"):
        return str(kind)
    return None


def _size(block: Dict[str, Any], default: float) -> float:
    try:
        return float(block.get("size_mm", default))
    except (TypeError, ValueError):
        return default


def _make_part(host: Dict[str, Any], size_mm: float) -> Dict[str, Any]:
    """The part item of a necklace's pendant (world item; image copied byte-equal, mesh moved). ``{part, moved}``."""
    from app.core import accessory_pendant
    from app.models import inventory
    host_id = str(host["id"])
    part_id = f"{host_id}_pendant"
    if inventory.get_item(part_id) is None:
        inventory.add_item(name=f"{host.get('name') or host_id} — pendant", item_id=part_id, category="outfit_piece",
                           prompt_fragment="",
                           outfit_piece={"slots": [], "jewellery": {"kind": "charm",
                                                                    "charm": {"size_mm": size_mm, "mount": "hang"}}})
    src = inventory.get_item_image_path(host_id)
    if src and not inventory.get_item_image_path(part_id):
        name = os.path.basename(src)
        dst = inventory._get_item_dir(part_id, create=True) / name
        shutil.copyfile(src, dst)
        inventory.set_item_image(part_id, name)
    moved = 0
    psig = accessory_pendant.current_psig(part_id)
    if psig:
        try:
            old = accessory_pendant.pendant_dir(host_id, psig)
            new = accessory_pendant.pendant_dir(part_id, psig)
        except ValueError:
            old = new = None
        if old is not None and (old / "raw.glb").is_file() and not new.exists():
            new.parent.mkdir(parents=True, exist_ok=True)
            os.replace(old, new)
            moved = 1
    return {"part": part_id, "moved": moved}


def _relink(item: Dict[str, Any], kind: str, part_id: str = "", size_mm: float = 0.0) -> None:
    raw = dict(_raw_jewellery(item) or {})
    if kind == "necklace":
        old = raw.get("pendant") if isinstance(raw.get("pendant"), dict) else {}
        link: Dict[str, Any] = {"item": part_id, "size_mm": size_mm}
        if old.get("gem_color"):
            link["gem_color"] = old["gem_color"]
        raw["pendant"] = link
    else:
        raw["buckle"] = None
    item["outfit_piece"]["jewellery"] = raw


def _migrate_world() -> Dict[str, Any]:
    from app.models import inventory
    out = {"necklaces": 0, "belts": 0, "meshes_moved": 0, "saved_all": True}
    ids = [str(i.get("id") or "") for i in inventory._load_items(strict=True) if wants(i)]
    for host_id in ids:
        with inventory._item_locks(host_id):
            fresh = next((i for i in inventory._load_items(strict=True) if str(i.get("id") or "") == host_id), None)
            kind = wants(fresh) if fresh else None
            if not kind:
                continue
            if kind == "necklace":
                size = _size(fresh["outfit_piece"]["jewellery"]["pendant"], 18.0)
                made = _make_part(fresh, size)
                _relink(fresh, kind, made["part"], size)
                out["meshes_moved"] += made["moved"]
            else:
                _relink(fresh, kind)
            if inventory._save_items([fresh]):
                out["necklaces" if kind == "necklace" else "belts"] += 1
                logger.info("Part migration (world): %s %s", kind, host_id)
            else:
                out["saved_all"] = False
                logger.warning("Part migration: world item %s not saved", host_id)
    return out


def _migrate_shared() -> Dict[str, Any]:
    """The shared library: a necklace's part is made in the world, moved to the library (its image with it), then the
    hosts and the marker are written in ONE write."""
    from app.core.timeutils import utc_now_iso
    from app.models import inventory
    out = {"necklaces": 0, "belts": 0, "meshes_moved": 0}
    pending = [i for i in inventory._load_shared_items(strict=True) if wants(i) == "necklace"]
    made: Dict[str, Dict[str, Any]] = {}
    for host in pending:
        size = _size(host["outfit_piece"]["jewellery"]["pendant"], 18.0)
        # the host's image lives in the library: the part is made beside it there
        m = _make_part({**host, "_shared": True}, size)
        if not inventory.is_shared_item(m["part"]):
            inventory.move_item_to_shared(m["part"])
        made[str(host["id"])] = {**m, "size": size}
    with inventory.item_write_lock():
        items = inventory._load_shared_items(strict=True)
        for item in items:
            kind = wants(item)
            if kind == "necklace" and str(item.get("id")) in made:
                m = made[str(item["id"])]
                _relink(item, kind, m["part"], m["size"])
                out["necklaces"] += 1
                out["meshes_moved"] += m["moved"]
            elif kind == "belt":
                _relink(item, kind)
                out["belts"] += 1
        inventory._save_shared_items(items, meta={SHARED_KEY: utc_now_iso()})
    return out


def migrate_parts_once() -> Dict[str, int]:
    """The migration (module docstring): ``{necklaces, belts, meshes_moved}`` of this run (all 0 when both halves ran
    already)."""
    from app.models import inventory
    from app.models.world import get_world_setting, set_world_setting
    total = {"necklaces": 0, "belts": 0, "meshes_moved": 0}
    world_done = bool(get_world_setting(FLAG, strict=True))
    shared_done = bool(inventory.get_shared_items_meta(strict=True).get(SHARED_KEY))
    if world_done and shared_done:
        return total
    if not world_done:
        w = _migrate_world()
        for k in total:
            total[k] += w[k]
        if w["saved_all"]:
            set_world_setting(FLAG, "1")
    if not shared_done:
        try:
            sh = _migrate_shared()
            for k in total:
                total[k] += sh[k]
        except Exception as e:  # noqa: BLE001 — the marker stays unset: the next boot retries
            logger.warning("Part migration: shared items not saved: %s", e)
    logger.info("accessory_parts migration done: %s", total)
    return total
