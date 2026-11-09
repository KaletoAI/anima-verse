"""Which items a character wears or holds as their own garment mesh
(plan ``docs/superpowers/plans/2026-11-09-base-body-phase5-mesh-items.md``).

Two kinds of item become a fitted garment mesh on a base-body character:

- ``hair`` — the hair garment (category ``garment``, ``garment.kind ==
  "hair"``), worn through the profile state key ``equipped_mesh_pieces`` and
  owned through ``item.owner`` (``garment_hair``);
- ``clothing`` — an ordinary ``outfit_piece`` whose ``outfit_piece.own_mesh``
  flag is set. It stays an outfit piece worn through ``equipped_pieces`` (2D
  renders, the outfit signature and the chat prompts never see the flag);
  the flag lives on the ITEM, so it applies to every wearer, and a wearer is
  whoever holds it (inventory) or wears it. Its fits are per wearer, under
  ``characters/<n>/garments/`` like the hair fits.

Only characters on the base-body pipeline (``base_body.is_base_pipeline``)
wear garments; everyone else ignores the flag (``worn_garments`` is empty).
"""
from typing import Any, Dict, Iterable, List, Optional

HAIR = "hair"
CLOTHING = "clothing"


def garment_kind_of(item: Optional[Dict[str, Any]]) -> Optional[str]:
    """``"hair"`` for a hair garment, ``"clothing"`` for an outfit piece with
    the own-mesh flag, else None."""
    if not isinstance(item, dict):
        return None
    category = item.get("category")
    if category == "garment":
        kind = str((item.get("garment") or {}).get("kind") or "")
        return HAIR if kind == HAIR else None
    if category == "outfit_piece" and (item.get("outfit_piece") or {}).get("own_mesh") is True:
        return CLOTHING
    return None


def _profile_of(character_name: str, profile: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if profile is not None:
        return profile
    from app.models.character import get_character_profile
    return get_character_profile(character_name) or {}


def _ids(mapping: Any) -> List[str]:
    if not isinstance(mapping, dict):
        return []
    return [str(v).strip() for v in mapping.values() if v and str(v).strip()]


def _flagged(item_ids: Iterable[str]) -> List[str]:
    from app.models.inventory import get_item
    return sorted({iid for iid in item_ids if garment_kind_of(get_item(iid)) == CLOTHING})


def holds(character_name: str, item_id: str, *,
          profile: Optional[Dict[str, Any]] = None) -> bool:
    """The character has the item in the inventory or wears it (as an outfit
    piece or a mesh piece)."""
    if not isinstance(item_id, str) or not item_id:
        return False
    from app.models.inventory import has_item
    if has_item(character_name, item_id):
        return True
    profile = _profile_of(character_name, profile)
    return item_id in _ids(profile.get("equipped_pieces")) or item_id in _ids(
        profile.get("equipped_mesh_pieces"))


def worn_garments(character_name: str, *, profile: Optional[Dict[str, Any]] = None,
                  pieces: Optional[Dict[str, str]] = None) -> List[str]:
    """Item ids of the garments the character wears, sorted and deduped: the
    mesh pieces of ``equipped_mesh_pieces`` (hair) plus the own-mesh outfit
    pieces of ``pieces`` (default: the profile's ``equipped_pieces``; a
    multi-slot piece once). Empty off the base-body pipeline."""
    from app.core import base_body
    profile = _profile_of(character_name, profile)
    if not base_body.is_base_pipeline(character_name, profile=profile):
        return []
    worn = set(_ids(profile.get("equipped_mesh_pieces")))
    worn.update(_flagged(_ids(profile.get("equipped_pieces") if pieces is None else pieces)))
    return sorted(worn)


def held_clothing(character_name: str, *,
                  profile: Optional[Dict[str, Any]] = None) -> List[str]:
    """Own-mesh outfit pieces the character holds or wears, sorted — the
    keep set of the garment cache GC (a dress in the wardrobe keeps its fit).
    Not gated on the pipeline: switching it off and on again must not cost
    the fits."""
    from app.models.inventory import _load_inventory
    entries = _load_inventory(character_name).get("inventory") or []
    ids = {str(e.get("item_id") or "").strip() for e in entries}
    ids.update(_ids(_profile_of(character_name, profile).get("equipped_pieces")))
    ids.discard("")
    return _flagged(ids)


# --- The Wardrobe (plan Task 5): row status and overlap warning ---------------------

#: Progress states of an own-mesh piece (``piece_status``), in chain order.
STATE_MISSING = "missing"
STATE_IMAGES = "images"
STATE_MESH = "mesh"
STATE_FITTED = "fitted"
STATE_RUNNING = "running"


def _accepted_images(steps: Dict[str, Any]) -> bool:
    for views in steps.values():
        if isinstance(views, dict) and any(isinstance(tile, dict) and tile.get("accepted") and "attempts" in tile
                                           for tile in views.values()):
            return True
    return False


def piece_status(info: Dict[str, Any], *, worn: bool, base_model_ready: bool) -> Dict[str, Any]:
    """The Wardrobe row chip of an own-mesh piece from its
    ``garments.garment_info``: ``{state, step, painted, reason}``.

    ``state`` — ``running`` (``step`` = the step in flight), else how far the
    chain of the CURRENT fingerprint got: ``fitted`` (accepted fit on the
    current base model), ``mesh`` (accepted mesh), ``images`` (at least one
    accepted image), ``missing``.
    ``painted`` — the piece is worn (``worn``: on the pipeline and in
    ``equipped_pieces``) without an accepted fit, so the outfit build paints
    it onto the body (``base_body.resolve_mesh_items``: effective = accepted
    fit on the current base model). ``reason`` says why, in the outfit
    warning's words: the persisted chain failure ``"<step> — <error>"``,
    else ``base_body.BASE_MODEL_MISSING`` without a base model, else
    ``base_body.NO_MESH_FIT``; None when not painted."""
    from app.core import base_body
    steps = info.get("steps") if isinstance(info.get("steps"), dict) else {}
    fit = steps.get("fit") if isinstance(steps.get("fit"), dict) else {}
    mesh = steps.get("mesh") if isinstance(steps.get("mesh"), dict) else {}
    running = info.get("running_step") or None
    if running:
        state = STATE_RUNNING
    elif info.get("fsig") and fit.get("status") == "accepted":
        state = STATE_FITTED
    elif mesh.get("status") == "accepted":
        state = STATE_MESH
    elif _accepted_images(steps):
        state = STATE_IMAGES
    else:
        state = STATE_MISSING
    fitted = bool(info.get("fsig") and fit.get("status") == "accepted")
    painted = bool(worn and not fitted)
    reason = None
    if painted:
        failed = info.get("failed") if isinstance(info.get("failed"), dict) else None
        if failed and failed.get("step") and failed.get("error"):
            reason = f"{failed['step']} — {failed['error']}"
        else:
            reason = base_body.NO_MESH_FIT if base_model_ready else base_body.BASE_MODEL_MISSING
    return {"state": state, "step": running, "painted": painted, "reason": reason}


def _cover_slots(item: Dict[str, Any]) -> set:
    piece = item.get("outfit_piece") if isinstance(item.get("outfit_piece"), dict) else {}
    return {str(s) for key in ("slots", "covers", "partially_covers") for s in piece.get(key) or []}


def mesh_overlaps(pieces: Optional[Dict[str, str]]) -> List[Dict[str, Any]]:
    """Pairs of worn own-mesh pieces whose meshes take the same place on the
    body — no collision between garments yet (the next strand), so such
    meshes may intersect. Equipping displaces whatever sat in a piece's own
    slots, so two worn pieces never hold the same slot; they overlap when
    the slots one piece is worn on or covers (``slots`` ∪ ``covers`` ∪
    ``partially_covers``) include a slot the other is worn on (a coat that
    covers ``top`` over a dress worn on ``top``). ``pieces`` = ``{slot:
    item_id}``. Sorted ``[{items: [a, b], slots: [...]}]``."""
    from app.models.inventory import get_item
    flagged = []
    for item_id in sorted(set(_ids(pieces))):
        item = get_item(item_id)
        if garment_kind_of(item) == CLOTHING:
            piece = item.get("outfit_piece") or {}
            flagged.append((item_id, {str(s) for s in piece.get("slots") or []}, _cover_slots(item)))
    out = []
    for i, (a, a_slots, a_cover) in enumerate(flagged):
        for b, b_slots, b_cover in flagged[i + 1:]:
            shared = (a_cover & b_slots) | (b_cover & a_slots)
            if shared:
                out.append({"items": [a, b], "slots": sorted(shared)})
    return out


def wardrobe(character_name: str, *, profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The Wardrobe's own-mesh overview of a character: ``{pipeline,
    items: {item_id: piece_status}, overlaps}`` — ``items`` covers every
    own-mesh piece the character holds or wears (``held_clothing``),
    ``overlaps`` the worn ones that share a body slot (``mesh_overlaps``,
    [] off the pipeline, where the flag is ignored)."""
    from app.core import base_body, garments
    profile = _profile_of(character_name, profile)
    pipeline = base_body.is_base_pipeline(character_name, profile=profile)
    base = base_body.current_base(character_name, profile=profile) if pipeline else None
    pieces = profile.get("equipped_pieces") if isinstance(profile.get("equipped_pieces"), dict) else {}
    worn = set(_ids(pieces))
    items: Dict[str, Any] = {}
    for item_id in held_clothing(character_name, profile=profile):
        try:
            info = garments.garment_info(character_name, item_id)
        except ValueError:
            continue
        items[item_id] = piece_status(info, worn=pipeline and item_id in worn,
                                      base_model_ready=bool(base and base[1]))
    return {"pipeline": pipeline, "items": items, "overlaps": mesh_overlaps(pieces) if pipeline else []}
