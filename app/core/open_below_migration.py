"""One-time boot prefill of ``outfit_piece.open_below`` (contact clips and clothes, owner decisions 2026-11-25).

A piece declared open below (a skirt, a dress, a kilt) never blocks a contact clip (``contact_clothing``); every
other piece on a clothing slot a part or a channel needs free does. The flag is new, so the pieces already in the
data get it once from their words: an outfit piece that sits on (``slots``) or ``covers`` a slot some loaded package
declares under ``contact_free`` (``contact_clothing.declared_slots``) is JUDGED; only a piece worn on the ``bottom`` clothing
slot can be open below — any other (an outer piece, an underwear piece) is skipped whatever its words say. A judged
piece on ``bottom`` is set open below when its NAME (any language variant) names a skirt, a dress, a kilt, a gown, a
robe or a sarong (``_OPEN``, English or German), or when it spans ``top`` and ``bottom`` as a one-piece dress — and
nothing closed is named anywhere in its words (``_CLOSED``: trousers, shorts, leggings, a bodysuit, underwear words,
…; name, description, prompt fragment). A description word alone never opens a piece.
Conservative on purpose: a piece that is left closed blocks until it is taken off, and the item editor's "Open
below" switch corrects it; a piece wrongly opened would let a clip through. A piece that already carries the flag
(true) is untouched; nothing is ever set to false here.

Two scopes, two markers (as ``figure_migration``): the world's items once per world (world_kv ``FLAG``), the shared
library (``shared/items/items.json``) once per installation (its own marker ``SHARED_KEY``, a top-level key written in
the same write as the flagged items). Without any declared slot (no anatomy package loaded) nothing runs and no
marker is set: the first boot with such a package does it. One INFO line per flagged item, one summary line; a
failed world write is a WARNING and leaves the flag unset (the next start retries).
"""
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from app.core.log import get_logger

logger = get_logger("open_below_migration")

#: world_kv marker of the world's half.
FLAG = "prefilled_open_below"
#: Marker of the shared library's half (top-level key of the shared items file).
SHARED_KEY = "prefilled_open_below"

# Whole words, or the END of a compound ("Sommerkleid", "Minirock", "sundress", "miniskirt").
_OPEN = re.compile(r"(?:\w*(?:skirt|skirts|dress|dresses|kleid|kleider|rock|röcke|roecke)|kilt|kilts|gown|gowns|"
                   r"robe|robes|bathrobe|bademantel|sarong|sarongs|dirndl|tutu)\b", re.IGNORECASE)
# Anywhere in a word: a closed bottom or an underwear piece keeps the piece closed.
_CLOSED = re.compile(r"trouser|pants|shorts|jeans|legging|tights|hose|panty|panties|brief|boxer|thong|underwear|"
                     r"unterwäsche|unterwaesche|höschen|hoeschen|skort|jumpsuit|overall|bodysuit|onesie|"
                     r"chaps|culotte|bloomer", re.IGNORECASE)


#: The one clothing slot an open-below piece is worn on (core outfit vocabulary, ``inventory.VALID_PIECE_SLOTS``).
_BOTTOM = "bottom"
_TOP = "top"


def _texts(item: Dict[str, Any], keys: Sequence[str] = ("name", "description", "prompt_fragment")) -> List[str]:
    """The words of an item under ``keys``, with every language variant (``name_de``, …)."""
    out = []
    for key, value in item.items():
        if not isinstance(value, str):
            continue
        base = re.sub(r"_[a-z]{2}$", "", key)
        if key in keys or base in keys and base in ("name", "description"):
            out.append(value)
    return out


def judge(item: Dict[str, Any], declared: Iterable[str]) -> Tuple[str, str]:
    """``(verdict, why)`` for one item: ``open`` (the prefill sets ``open_below``), ``closed``, ``skip`` (it touches a
    declared slot but is not worn on ``bottom``), or ``""`` (not an outfit piece on a declared slot — not judged).
    ``why`` names the word or the shape that decided."""
    piece = item.get("outfit_piece")
    if item.get("category") != "outfit_piece" or not isinstance(piece, dict):
        return "", ""
    wanted = {str(s).strip().lower() for s in declared}
    slots = {str(s).strip().lower() for s in piece.get("slots") or []}
    touched = slots | {str(s).strip().lower() for s in piece.get("covers") or []}
    if not touched & wanted:
        return "", ""
    if _BOTTOM not in slots:
        return "skip", "not worn on bottom"
    closed = _CLOSED.search(" ".join(_texts(item)))
    if closed:
        return "closed", f"closed word '{closed.group(0)}'"
    hit = _OPEN.search(" ".join(_texts(item, ("name",))))
    if hit:
        return "open", f"name '{hit.group(0)}'"
    if _TOP in slots:
        return "open", "one piece over top and bottom"
    return "closed", "no open-below word in the name"


def prefill(items: Sequence[Dict[str, Any]], declared: Iterable[str], where: str
            ) -> Tuple[List[Dict[str, Any]], List[Tuple[Dict[str, Any], str]]]:
    """Flag the open-below pieces of ``items`` in place: ``(changed items, [(item left closed, why)])`` — the
    second list holds every judged piece that stays closed (the dry run's report)."""
    declared = list(declared)
    changed: List[Dict[str, Any]] = []
    closed: List[Tuple[Dict[str, Any], str]] = []
    for item in items:
        verdict, why = judge(item, declared)
        if verdict not in ("open", "closed"):
            continue
        piece = item["outfit_piece"]
        if piece.get("open_below") is True:
            continue
        if verdict == "closed":
            closed.append((item, why))
            continue
        piece["open_below"] = True
        changed.append(item)
        logger.info("Open-below prefill: item %s (%s, %s) open below — %s",
                    item.get("id"), item.get("name") or "-", where, why)
    return changed, closed


def prefill_once() -> Optional[Dict[str, List[str]]]:
    """The migration (module docstring). None when both halves already ran or no package declares a slot,
    else ``{world: [ids], shared: [ids]}`` of the items flagged this time."""
    from app.core.contact_clothing import declared_slots
    from app.models import inventory
    from app.models.world import get_world_setting, set_world_setting
    world_done = bool(get_world_setting(FLAG, strict=True))
    shared_done = bool(inventory.get_shared_items_meta(strict=True).get(SHARED_KEY))
    if world_done and shared_done:
        return None
    declared = declared_slots()
    if not declared:
        logger.info("Open-below prefill waits: no package declares contact_free slots")
        return None
    result: Dict[str, List[str]] = {"world": [], "shared": []}
    if not world_done:
        changed, _ = prefill(inventory._load_items(strict=True), declared, "world")
        failed = [str(i.get("id")) for i in changed if not inventory._save_items([i])]
        result["world"] = [str(i.get("id")) for i in changed if str(i.get("id")) not in failed]
        if failed:
            logger.warning("Open-below prefill: world items not saved (%s) — retried at the next start",
                           ", ".join(failed))
        else:
            set_world_setting(FLAG, "1")
    if not shared_done:
        from app.core.timeutils import utc_now_iso
        shared = inventory._load_shared_items(strict=True)
        changed, _ = prefill(shared, declared, "shared")
        try:
            # The marker travels in the same write as the flagged items: no half state.
            inventory._save_shared_items(shared, meta={SHARED_KEY: utc_now_iso()})
            result["shared"] = [str(i.get("id")) for i in changed]
        except Exception as e:  # noqa: BLE001 — the marker stays unset: the next boot retries
            logger.warning("Open-below prefill: shared items not saved: %s", e)
    logger.info("Open-below prefill done: %d world item(s), %d shared item(s) open below",
                len(result["world"]), len(result["shared"]))
    return result
