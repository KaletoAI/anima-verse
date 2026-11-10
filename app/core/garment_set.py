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
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

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


def piece_status(info: Dict[str, Any], *, worn: bool, base_model_ready: bool,
                 layers: Optional[Dict[str, List[str]]] = None, mesh_mode: bool = False) -> Dict[str, Any]:
    """The Wardrobe row chip of an own-mesh piece from its
    ``garments.garment_info``: ``{state, step, painted, reason, over,
    without}`` (+ ``missing`` in mesh mode).

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
    ``base_body.NO_MESH_FIT``; None when neither painted nor missing.
    ``missing`` — outfit body mode mesh (``mesh_mode``, ruling 2026-11-10):
    the same worn piece without an accepted fit is NOT painted (never meshed
    into the outfit body) — it is missing from the outfit model until its
    mesh is accepted (``base_body.MESH_ITEM_NOT_READY``); ``painted`` is then
    False and ``reason`` says why it is not ready.
    ``body`` — mesh mode only: ``{body_id, status, error}`` of the piece's
    fit on the outfit body worn now (``garment_info["body"]``).
    ``queue_position`` — the 1-based place of the piece's next waiting run
    in the character's garment queue, None when none waits
    (``garments.queue_state``).
    ``over`` / ``without`` — the names of the worn pieces under this one with
    and without a fit (``worn_layers``' entry of the piece, ``layers``): the
    chip says "fitted over <inner>" / "without <inner>". Both keys are left
    out when nothing is worn under it."""
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
    absent = bool(worn and not fitted)
    painted = absent and not mesh_mode
    reason = None
    if absent:
        failed = info.get("failed") if isinstance(info.get("failed"), dict) else None
        if failed and failed.get("step") and failed.get("error"):
            reason = f"{failed['step']} — {failed['error']}"
        else:
            reason = base_body.NO_MESH_FIT if base_model_ready else base_body.BASE_MODEL_MISSING
    out = {"state": state, "step": running, "painted": painted, "reason": reason,
           "queue_position": info.get("queue_position")}
    if mesh_mode:
        out["missing"] = absent
    if isinstance(info.get("body"), dict):
        # Mesh mode: the piece's fit on the outfit body worn now (garments.body_fit_info).
        out["body"] = {k: info["body"].get(k) for k in ("body_id", "status", "error")}
    if layers and (layers.get("over") or layers.get("without")):
        out.update(over=list(layers.get("over") or []), without=list(layers.get("without") or []))
    return out


def _cover_slots(item: Dict[str, Any]) -> set:
    piece = item.get("outfit_piece") if isinstance(item.get("outfit_piece"), dict) else {}
    return {str(s) for key in ("slots", "covers", "partially_covers") for s in piece.get(key) or []}


def _worn_slots(item: Dict[str, Any]) -> set:
    piece = item.get("outfit_piece") if isinstance(item.get("outfit_piece"), dict) else {}
    return {str(s) for s in piece.get("slots") or []}


def _slot_order(slot_order: Optional[Sequence[str]]) -> List[str]:
    if slot_order:
        return [str(s) for s in slot_order]
    from app.models.inventory import VALID_PIECE_SLOTS
    return list(VALID_PIECE_SLOTS)


def layer_order(item_ids: Iterable[str], *, slot_order: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    """The layer order of worn own-mesh pieces (plan
    ``docs/superpowers/plans/2026-11-10-texture-body-reuse-and-layering.md``,
    Task 2) — which piece is fitted over which.

    A piece is OVER another when the slots it is worn on or covers (``slots``
    ∪ ``covers`` ∪ ``partially_covers``) include a slot the other is worn on:
    a coat that covers ``top`` is over a dress worn on ``top``. Pieces that
    are over each other (a top that partially covers ``bottom`` and a
    high-waisted skirt that covers ``top``; any longer cycle too) have no
    order of their own: they are put in SLOT RANK order — the rank of a piece
    is its first worn slot in ``slot_order`` (default
    ``inventory.VALID_PIECE_SLOTS``, which runs from the underwear out;
    unknown slots after every known one), ties by item id — the lower rank
    inner, and the cycle is reported. Only own-mesh clothing
    (``garment_kind_of`` == ``clothing``) takes part; unknown ids are
    skipped.

    Returns ``{order, under, cycles}``: ``order`` inner → outer (a piece
    after every piece it is over; independent pieces by slot rank, item id),
    ``under`` item -> the pieces it is fitted over, sorted — every piece
    below it through the kept relations (the relation of a cycle that runs
    against the rank order is dropped), so a coat over a dress over a slip
    lies over both — and ``cycles``: ``[{items: [inner → outer], slots}]`` per
    cycle (``slots``: the slots its pieces share). Deterministic: the same set
    gives the same answer in any input order."""
    from app.models.inventory import get_item
    order_of = {slot: i for i, slot in enumerate(_slot_order(slot_order))}
    items: Dict[str, Dict[str, Any]] = {}
    for item_id in sorted({str(i) for i in item_ids if i}):
        item = get_item(item_id)
        if garment_kind_of(item) == CLOTHING:
            items[item_id] = item
    ids = sorted(items)
    worn = {i: _worn_slots(items[i]) for i in ids}
    cover = {i: _cover_slots(items[i]) for i in ids}

    def rank(item_id: str) -> Tuple[int, str]:
        return min((order_of.get(slot, len(order_of)) for slot in worn[item_id]), default=len(order_of)), item_id

    # over[a] = the pieces a is over (direct relation)
    over = {a: {b for b in ids if b != a and cover[a] & worn[b]} for a in ids}

    def reach(a: str) -> set:
        seen, todo = set(), [a]
        while todo:
            for b in over[todo.pop()]:
                if b not in seen:
                    seen.add(b)
                    todo.append(b)
        return seen
    below = {a: reach(a) for a in ids}
    # strongly connected components: pieces that are over each other
    component = {a: frozenset({a} | {b for b in below[a] if a in below[b]}) for a in ids}
    comps = sorted(set(component.values()), key=lambda c: min(rank(i) for i in c))
    placed: List[str] = []
    done: set = set()
    pending = list(comps)
    while pending:
        # the first component (by rank) whose pieces are over nothing outside it that is still unplaced
        ready = next(c for c in pending
                     if all(b in done or b in c for a in c for b in over[a]))
        pending.remove(ready)
        for item_id in sorted(ready, key=rank):
            placed.append(item_id)
            done.add(item_id)
    position = {item_id: i for i, item_id in enumerate(placed)}
    kept = {a: {b for b in over[a] if position[b] < position[a]} for a in ids}
    under: Dict[str, List[str]] = {}
    for a in ids:
        seen, todo = set(), [a]
        while todo:
            for b in kept[todo.pop()]:
                if b not in seen:
                    seen.add(b)
                    todo.append(b)
        under[a] = sorted(seen)
    cycles = []
    for comp in comps:
        if len(comp) < 2:
            continue
        members = sorted(comp, key=lambda i: position[i])
        shared = set()
        for a in members:
            for b in members:
                if a != b:
                    shared |= cover[a] & worn[b]
        cycles.append({"items": members, "slots": sorted(shared, key=lambda s: (order_of.get(s, len(order_of)), s))})
    return {"order": placed, "under": under, "cycles": cycles}


def mesh_overlaps(pieces: Optional[Dict[str, str]], *,
                  slot_order: Optional[Sequence[str]] = None) -> List[Dict[str, Any]]:
    """The worn own-mesh pieces whose layer order is a GUESS — pieces that
    are over each other (a cycle of ``layer_order``), put in slot rank order.
    Every other pair that shares a place on the body is layered: the outer
    piece is fitted over the inner one (``garment_layers``), no warning.
    ``pieces`` = ``{slot: item_id}``. ``[{items: [inner, …, outer], slots}]``."""
    return layer_order(_ids(pieces), slot_order=slot_order)["cycles"]


def worn_layers(character_name: str, *, profile: Optional[Dict[str, Any]] = None,
                base_model_sha: str = "") -> Dict[str, Dict[str, List[str]]]:
    """Per worn own-mesh piece with pieces under it (``layer_order`` of the
    worn ones, the character's slot order): ``{over: [names], without:
    [names]}`` — ``over`` the inner pieces with an accepted fit on
    ``base_model_sha`` (the outer piece is fitted over their meshes),
    ``without`` those still painted on (no fit yet: the outer piece is fitted
    against the body there and refitted over them once their fit lands).
    {} off the pipeline / without a base model."""
    from app.core import base_body, body_slots, garment_store
    from app.models.inventory import get_item
    profile = _profile_of(character_name, profile)
    if not base_model_sha or not base_body.is_base_pipeline(character_name, profile=profile):
        return {}
    pieces = profile.get("equipped_pieces") if isinstance(profile.get("equipped_pieces"), dict) else {}
    layers = layer_order(_ids(pieces), slot_order=body_slots.piece_slots_for_character(character_name))
    out: Dict[str, Dict[str, List[str]]] = {}
    fitted: Dict[str, bool] = {}
    for item_id, inner in layers["under"].items():
        if not inner:
            continue
        entry: Dict[str, List[str]] = {"over": [], "without": []}
        for other in inner:
            if other not in fitted:
                fitted[other] = garment_store.accepted_fit(character_name, other, base_model_sha=base_model_sha,
                                                           profile=profile) is not None
            name = str((get_item(other) or {}).get("name") or other)
            entry["over" if fitted[other] else "without"].append(name)
        out[item_id] = entry
    return out


def wardrobe(character_name: str, *, profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The Wardrobe's own-mesh overview of a character: ``{pipeline,
    items: {item_id: piece_status}, overlaps}`` — ``items`` covers every
    own-mesh piece the character holds or wears (``held_clothing``; a worn
    piece over others names them, ``worn_layers``), ``overlaps`` the worn
    ones whose layer order is a guess (``mesh_overlaps``: a cycle, put in
    slot rank order; [] off the pipeline, where the flag is ignored),
    ``queue_running`` / ``queue`` the character's garment queue
    (``garments.queue_state``: the item id in flight, the waiting ones)."""
    from app.core import base_body, body_slots, garments
    profile = _profile_of(character_name, profile)
    pipeline = base_body.is_base_pipeline(character_name, profile=profile)
    base = base_body.current_base(character_name, profile=profile) if pipeline else None
    mesh_mode = pipeline and base_body.outfit_body_mode(character_name, profile=profile) == base_body.MESH_MODE
    pieces = profile.get("equipped_pieces") if isinstance(profile.get("equipped_pieces"), dict) else {}
    worn = set(_ids(pieces))
    layers = worn_layers(character_name, profile=profile, base_model_sha=base[1] if base else "")
    items: Dict[str, Any] = {}
    for item_id in held_clothing(character_name, profile=profile):
        try:
            info = garments.garment_info(character_name, item_id)
        except ValueError:
            continue
        items[item_id] = piece_status(info, worn=pipeline and item_id in worn,
                                      base_model_ready=bool(base and base[1]), layers=layers.get(item_id),
                                      mesh_mode=mesh_mode)
    overlaps = (mesh_overlaps(pieces, slot_order=body_slots.piece_slots_for_character(character_name))
                if pipeline else [])
    queue = garments.queue_state(character_name)
    return {"pipeline": pipeline, "items": items, "overlaps": overlaps,
            "queue_running": queue["queue_running"], "queue": queue["queue"]}
