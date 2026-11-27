"""Removing hairstyles nobody needs, with their files.

A hairstyle is an item (``garment_hair``: category ``garment``, ``garment.kind`` ``hair``, ``owner`` = the
character). A character owns several and wears one, so an owned hairstyle that is not worn is normally a choice the
user may switch to and stays. This module finds the ones that are NOT, and removes them:

A hairstyle is **unneeded** when ALL of these hold:

1. **Nothing references it** (``references``): no character profile names it (its JSON, read as a whole, does not
   contain the id as a quoted token — covers ``equipped_mesh_pieces`` and ``garment_hair.BASE_HAIRSTYLE_KEY`` of
   every character, its owner included), no saved outfit set names it (same token test), no row of
   ``inventory_items`` / ``equipped_items`` / ``equipped_pieces`` names it and no room lists it. A read that fails
   counts as a reference (nothing is removed on a guess).
2. It is **not a shared library item** and is older than ``GRACE_DAYS`` SYSTEM days (``created_at``) — a hairstyle
   the user has just made and not worn or run yet is never swept.
3. It is **an orphan or a duplicate**:
   - *orphan*: its ``owner`` is empty or no stored character (dormant and pooled ones count as stored);
   - *duplicate*: another hairstyle of the same owner is an exact copy of it and is kept — the same text
     (``garment_hair.hairstyle_key``), the same mode (``garment_hair.hairstyle_mode``) and the same settings
     (``garment_hair.hairstyle_settings``). Whether a hairstyle has generated files is never part of it: a
     hairstyle in another mode or with other settings is an alternative the user made on purpose
     (``create_hairstyle`` allows the same text in another mode) and stays, run or not.
     Within one copy group the hairstyles are kept in this order: referenced ones, then ones with generated files
     (``hairstyle_delete.item_paths``), then the oldest, then by id; the first stays, the others are duplicates.

So every hairstyle with a text, a mode or settings of its own stays.

Removal goes through ``hairstyle_delete.delete_hairstyle`` for a stored owner (the item, its references, its files
under ``garments/`` — only names of THIS item, every path checked to resolve inside ``garments/``, never a symlink;
the assembled models and the body shapes only it stands on). An orphan has no hairstyle tab: it goes through
``hairstyle_delete.delete_orphan`` (its ``garments/`` files the same contained way when its owner's folder still
exists, then its row, inventory rows and media folder). A hairstyle that is busy (a run, a Build) is skipped and
found again by the next sweep. Deleting a character deletes its hairstyles itself
(``hairstyle_delete.delete_owned_items``), so an orphan is what an older deletion, a failed item delete or a
hand-made item left.

``unneeded`` is read-only (the Hairstyles tab's "Clean up" lists it); ``sweep`` removes. Nothing runs it on its
own: the Hairstyles tab runs it for one character (``POST /characters/{c}/hairstyles/cleanup``), the Characters
list for the whole world (``POST /characters/hairstyle-cleanup``), each after a confirmation that names the
hairstyles.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Set

from app.core.log import get_logger

logger = get_logger("hairstyle_sweep")

#: A hairstyle younger than this many SYSTEM days is never swept (``created_at``).
GRACE_DAYS = 7
ORPHAN = "orphan"
DUPLICATE = "duplicate"


def _hair_items() -> List[Dict[str, Any]]:
    """Every hair item of the world store (owned or not), by id. Raises when the store cannot be read."""
    from app.core import garment_hair
    from app.models import inventory
    return sorted((i for i in inventory._load_items(strict=True) if garment_hair.is_hair_item(i)),
                  key=lambda i: str(i.get("id") or ""))


def _characters() -> Set[str]:
    from app.models.character import list_available_characters
    return set(list_available_characters(include_pooled=True, include_dormant=True, strict=True))


class _References:
    """The ids named anywhere ``references`` looks (module docstring, rule 1), read once per sweep."""

    def __init__(self, names: Set[str]):
        from app.core.db import get_connection
        from app.models.character import get_character_outfits, get_character_profile
        from app.models.world import list_locations
        self.texts: List[str] = []
        for name in sorted(names):
            self.texts.append(json.dumps(get_character_profile(name) or {}, default=str))
            self.texts.append(json.dumps(get_character_outfits(name) or [], default=str))
        self.rows: Set[str] = set()
        conn = get_connection()
        for table in ("inventory_items", "equipped_items", "equipped_pieces"):
            self.rows.update(str(r[0]) for r in conn.execute(f"SELECT item_id FROM {table}").fetchall())
        for loc in list_locations() or []:
            for room in loc.get("rooms", []) or []:
                for entry in room.get("items", []) or []:
                    self.rows.add(str((entry or {}).get("item_id") or ""))

    def of(self, item_id: str) -> bool:
        token = json.dumps(item_id)
        return item_id in self.rows or any(token in text for text in self.texts)


def _old_enough(item: Dict[str, Any], now) -> bool:
    from app.core.timeutils import parse_iso
    stamp = str(item.get("created_at") or "")
    if not stamp:
        return True
    try:
        return (now - parse_iso(stamp)).total_seconds() >= GRACE_DAYS * 86400
    except Exception:  # noqa: BLE001 — an unreadable stamp is no reason to keep it forever, nor to sweep it now
        return False


def _has_files(owner: str, item_id: str) -> bool:
    from app.core import hairstyle_delete
    return bool(hairstyle_delete.item_paths(owner, item_id))


def unneeded(character_name: Optional[str] = None) -> List[Dict[str, Any]]:
    """The unneeded hairstyles (module docstring) — the duplicates of one character, or of the whole world when
    ``None`` (every character's duplicates plus the orphans). ``[{item_id, owner, name, mode, reason, kept,
    kept_name}]``: ``reason`` ``ORPHAN`` / ``DUPLICATE``, ``kept`` / ``kept_name`` the id and name of the hairstyle
    a duplicate is a copy of ("" for an orphan). Read-only; raises when a store cannot be read."""
    from app.core import garment_hair
    from app.core.timeutils import utc_now
    from app.models import inventory
    items = _hair_items()
    names = _characters()
    refs = _References(names)
    now = utc_now()
    out: List[Dict[str, Any]] = []

    def candidate(item: Dict[str, Any]) -> bool:
        iid = str(item.get("id") or "")
        return bool(iid) and not inventory.is_shared_item(iid) and not refs.of(iid) and _old_enough(item, now)

    def entry(item: Dict[str, Any], reason: str, kept: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        return {"item_id": str(item["id"]), "owner": str(item.get("owner") or "").strip(),
                "name": str(item.get("name") or item["id"]), "mode": garment_hair.hairstyle_mode(item),
                "reason": reason, "kept": str(kept["id"]) if kept else "",
                "kept_name": str(kept.get("name") or kept["id"]) if kept else ""}

    groups: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    for item in items:
        owner = str(item.get("owner") or "").strip()
        if character_name is not None and owner != character_name:
            continue
        if not owner or owner not in names:
            if character_name is None and candidate(item):
                out.append(entry(item, ORPHAN, None))
            continue
        key = garment_hair.hairstyle_key(item)
        if key:
            copy = json.dumps([key, garment_hair.hairstyle_mode(item), garment_hair.hairstyle_settings(item)],
                              sort_keys=True, default=str)
            groups.setdefault(owner, {}).setdefault(copy, []).append(item)

    for owner, by_text in sorted(groups.items()):
        for _key, members in sorted(by_text.items()):
            if len(members) < 2:
                continue
            files = {str(m["id"]): _has_files(owner, str(m["id"])) for m in members}
            ordered = sorted(members, key=lambda m: (not refs.of(str(m["id"])), not files[str(m["id"])],
                                                     str(m.get("created_at") or ""), str(m["id"])))
            for item in ordered[1:]:
                if candidate(item):
                    out.append(entry(item, DUPLICATE, ordered[0]))
    return out


def sweep(character_name: Optional[str] = None) -> Dict[str, Any]:
    """Remove the unneeded hairstyles (``unneeded``) — of one character, or of the whole world when ``None``.
    ``{removed: [{item_id, owner, name, reason, kept, deleted_files}], skipped: [{item_id, why}]}``. A busy
    hairstyle (a run or a Build works) and one that changed in between are skipped; the next sweep finds them again.
    One log line when something went."""
    from app.core import hairstyle_delete
    found = unneeded(character_name)
    removed: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []
    for entry in found:
        try:
            # Re-judged right before the delete: a Wear / an outfit set since the list was read keeps it.
            again = {e["item_id"]: e for e in unneeded(entry["owner"] if entry["reason"] == DUPLICATE else None)}
            if entry["item_id"] not in again:
                skipped.append({"item_id": entry["item_id"], "why": "changed since it was listed"})
                continue
            if entry["reason"] == ORPHAN:
                report = hairstyle_delete.delete_orphan(entry["owner"], entry["item_id"])
            else:
                report = hairstyle_delete.delete_hairstyle(entry["owner"], entry["item_id"])
        except hairstyle_delete.HairstyleBusy as e:
            skipped.append({"item_id": entry["item_id"], "why": str(e)})
            continue
        except Exception as e:  # noqa: BLE001 — the next one still goes
            logger.warning("Hairstyle sweep: %s not removed: %s", entry["item_id"], e)
            skipped.append({"item_id": entry["item_id"], "why": str(e)})
            continue
        removed.append({**entry, "deleted_files": int(report.get("deleted_files") or 0)})
    if removed or skipped:
        logger.info("Hairstyle sweep%s: %d removed (%s)%s", f" {character_name}" if character_name else "",
                    len(removed), ", ".join(f"{r['item_id']} [{r['reason']}]" for r in removed) or "-",
                    f", {len(skipped)} skipped: " + "; ".join(f"{s['item_id']} ({s['why']})" for s in skipped)
                    if skipped else "")
    return {"removed": removed, "skipped": skipped}
