"""One-time boot migration (bug round 2026-11-20): template trousers stored before A233 get the trouser fields.

Before A233 the template kind ``trousers`` existed but was not built; its fields were the skirt's ``length_m`` (from
the waist down) and ``waist_height``. A233 replaced them with ``trouser_length`` / ``rise`` / ``leg_shape`` (and
more), so a piece saved before it kept ``length_m`` / ``waist_height`` — which no trouser reads — and silently drape
on the defaults (full / mid / straight): a piece the user had saved as low-waisted came out mid-rise.

Every outfit piece whose stored ``outfit_piece.template.params`` is a trouser without ``leg_shape`` (the mark of a
pre-A233 save) is rewritten ONCE by an explicit mapping, never at read time:

- ``waist_height`` -> ``rise``: ``WAIST_TO_RISE`` (high -> high, natural -> mid, low -> low);
- ``length_m`` -> ``trouser_length``: the first of ``LENGTH_BANDS`` whose bound the length stays under (a length
  from the waist down on a person of about 1.70 m: the knee lies about 0.55 m, the ankle about 0.90 m below the
  waist), else ``full``;
- a missing ``leg_shape`` -> ``straight``;
- ``length_m`` and ``waist_height`` leave the stored parameters.

Nothing is built: the next Build re-drapes the piece (its key changes). Two scopes, two markers (like
``painted_mode_migration``): the world's items once per world (world_kv ``FLAG``), the shared library once per
installation (top-level key ``SHARED_KEY`` of the shared items file, written in the same write). A world item that
was not saved leaves the world flag unset, so the next start retries.
"""
from typing import Any, Dict, List, Optional, Tuple

from app.core.log import get_logger

logger = get_logger("trouser_params_migration")

#: world_kv key of the world's done flag.
FLAG = "migrated_trouser_params"
#: Top-level key of the shared items file: the shared library was migrated (once per installation).
SHARED_KEY = "migrated_trouser_params"
#: The old waistband height -> the trouser rise.
WAIST_TO_RISE = {"high": "high", "natural": "mid", "low": "low"}
#: The old length from the waist down (metres) -> the trouser length: the first band whose bound it stays under.
LENGTH_BANDS: Tuple[Tuple[float, str], ...] = ((0.40, "shorts"), (0.62, "knee"), (0.75, "capri"), (0.85, "ankle"))
#: The leg shape a pre-A233 piece gets.
LEG_SHAPE = "straight"


def trouser_length(length_m: Any) -> str:
    """``LENGTH_BANDS`` of an old ``length_m``; ``full`` when it is longer or not a number."""
    try:
        value = float(length_m)
    except (TypeError, ValueError):
        return "full"
    for bound, name in LENGTH_BANDS:
        if value < bound:
            return name
    return "full"


def due(item: Dict[str, Any]) -> bool:
    """Whether ``item`` is an outfit piece with stored pre-A233 trouser parameters (no ``leg_shape``)."""
    if not isinstance(item, dict) or item.get("category") != "outfit_piece":
        return False
    piece = item.get("outfit_piece")
    record = piece.get("template") if isinstance(piece, dict) else None
    params = record.get("params") if isinstance(record, dict) else None
    return isinstance(params, dict) and params.get("kind") == "trousers" and params.get("leg_shape") in (None, "")


def apply(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Rewrite ``item``'s stored parameters in place (module docstring); ``{item, rise, trouser_length,
    leg_shape}`` of the change, None when untouched."""
    if not due(item):
        return None
    params = item["outfit_piece"]["template"]["params"]
    waist = str(params.pop("waist_height", "") or "").strip().lower()
    length = params.pop("length_m", None)
    params["rise"] = WAIST_TO_RISE.get(waist, params.get("rise") or "mid")
    params["trouser_length"] = trouser_length(length) if length is not None else (params.get("trouser_length")
                                                                                  or "full")
    params["leg_shape"] = LEG_SHAPE
    return {"item": str(item.get("id") or ""), "rise": params["rise"], "trouser_length": params["trouser_length"],
            "leg_shape": LEG_SHAPE, "from": {"waist_height": waist, "length_m": length}}


def _migrate_world() -> Tuple[List[Dict[str, Any]], bool]:
    """The world's items: ``(changes, every change saved)``, each under its piece lock, re-read fresh there."""
    from app.models import inventory
    changes: List[Dict[str, Any]] = []
    saved_all = True
    ids = [str(i.get("id") or "") for i in inventory._load_items(strict=True) if due(i)]
    for item_id in ids:
        with inventory._item_locks(item_id):
            fresh = next((i for i in inventory._load_items(strict=True) if str(i.get("id") or "") == item_id), None)
            change = apply(fresh) if fresh is not None else None
            if change is None:
                continue
            if inventory._save_items([fresh]):
                changes.append(change)
                logger.info("Trouser params migration (world): %s", change)
            else:
                saved_all = False
                logger.warning("Trouser params migration: world item %s not saved", item_id)
    return changes, saved_all


def _migrate_shared() -> List[Dict[str, Any]]:
    """The shared library, in ONE write together with its marker (``SHARED_KEY``)."""
    from app.core.timeutils import utc_now_iso
    from app.models import inventory
    changes: List[Dict[str, Any]] = []
    with inventory.item_write_lock():
        items = inventory._load_shared_items(strict=True)
        for item in items:
            change = apply(item)
            if change is not None:
                changes.append(change)
        inventory._save_shared_items(items, meta={SHARED_KEY: utc_now_iso()})
    for change in changes:
        logger.info("Trouser params migration (shared): %s", change)
    return changes


def migrate_trouser_params_once() -> Optional[Dict[str, Any]]:
    """The migration (module docstring). None when both halves already ran, else ``{items: [changes]}``."""
    from app.models import inventory
    from app.models.world import get_world_setting, set_world_setting
    world_done = bool(get_world_setting(FLAG, strict=True))
    shared_done = bool(inventory.get_shared_items_meta(strict=True).get(SHARED_KEY))
    if world_done and shared_done:
        return None
    changes: List[Dict[str, Any]] = []
    saved_all = True
    if not world_done:
        changes, saved_all = _migrate_world()
    if not shared_done:
        try:
            changes.extend(_migrate_shared())
        except Exception as e:  # noqa: BLE001 — the marker stays unset: the next boot retries
            logger.warning("Trouser params migration: shared items not saved: %s", e)
    if not world_done and saved_all:
        set_world_setting(FLAG, "1")
    logger.info("Trouser params migration done: %d piece(s) given trouser fields", len(changes))
    return {"items": changes}
