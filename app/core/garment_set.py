"""Which items a character wears or holds as their own garment mesh
(plan ``docs/superpowers/plans/2026-11-09-base-body-phase5-mesh-items.md``),
and the mode of every worn outfit piece (plan
``docs/superpowers/plans/2026-11-12-unified-worn-pieces.md`` Task 2).

The mode is a property of the ITEM — ``outfit_piece.mesh_mode`` (``mesh_mode_of``),
the same for every wearer: ``own_mesh`` (a finished mesh fitted on top),
``painted`` (on the body's texture) or ``in_body`` (meshed as part of the
body). A mode is stored only when someone picks it (the Wardrobe's mode
select, a route that names it); an item without a valid stored mode is in
the body (``default_mesh_mode``, Ruling A10 — for every slot set, footwear
included: own mesh and painted must be chosen).

Two kinds of item become a fitted garment mesh on a base-body character:

- ``hair`` — the hair garment (category ``garment``, ``garment.kind ==
  "hair"``), worn through the profile state key ``equipped_mesh_pieces`` and
  owned through ``item.owner`` (``garment_hair``);
- ``clothing`` — an ordinary ``outfit_piece`` whose mode is ``own_mesh``.
  It stays an outfit piece worn through ``equipped_pieces`` (2D renders, the
  outfit signature and the chat prompts never see the mode); the mode lives
  on the ITEM, so it applies to every wearer, and a wearer is whoever holds
  it (inventory) or wears it. Its fits are per wearer, under
  ``characters/<n>/garments/`` like the hair fits;
- ``footwear`` — an own-mesh outfit piece worn in slot ``feet`` ONLY (plan
  ``docs/superpowers/plans/2026-11-10-footwear-rigid-shoes.md``): a rigid
  shoe meshed once per item from its item image (``footwear_source``) and
  fitted per wearer × body on the CPU (method ``shoe``,
  ``garment_footwear``). It takes no part in layering. A multi-slot piece
  that also covers ``feet`` (own-mesh tights ``[legs, feet]``) stays
  clothing (controller ruling 2026-11-10). It is NEVER painted onto the
  body, in either outfit body mode (spec § 9.1): without an accepted fit on
  the current body it is missing (bare feet) until the fit is accepted.

``OWN_MESH_PIECE_KINDS`` answers "is this an own-mesh outfit piece" (the
mode, the worn set, the mesh-items token); ``GRAFTED_PIECE_KINDS`` the kinds
whose accepted fit is grafted into the served model (clothing and, since
Task 16 of the footwear plan, footwear).

Only characters on the base-body pipeline (``base_body.is_base_pipeline``)
wear garments; everyone else ignores the mode (``worn_garments`` is empty).
"""
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

HAIR = "hair"
CLOTHING = "clothing"
FOOTWEAR = "footwear"
#: The kinds of an outfit piece in mode ``own_mesh``.
OWN_MESH_PIECE_KINDS: Tuple[str, ...] = (CLOTHING, FOOTWEAR)
#: The own-mesh piece kinds whose accepted fit is grafted into the served model.
GRAFTED_PIECE_KINDS: Tuple[str, ...] = (CLOTHING, FOOTWEAR)
#: The slot an own-mesh piece is worn in ALONE to be footwear.
FOOTWEAR_SLOT = "feet"

#: The modes of an outfit piece (``outfit_piece.mesh_mode``, module docstring).
OWN_MESH, PAINTED, IN_BODY = "own_mesh", "painted", "in_body"
#: A sewing-pattern template draped onto the plain body on the CPU (``garment_template``, Ruling A138).
TEMPLATE = "template"
#: A mesh of its own made from the plain body's surface over the region the piece covers (``garment_shell``,
#: Ruling A48d; its own mode since A168): the own-mesh chain without the cut-outs and the hub mesh job.
SHELL = "shell"
MESH_MODES: Tuple[str, ...] = (OWN_MESH, SHELL, PAINTED, IN_BODY, TEMPLATE)
#: The modes whose piece is a fitted mesh of its own (the own-mesh chain, ``garment_kind_of``).
OWN_MESH_MODES: Tuple[str, ...] = (OWN_MESH, SHELL)


def default_mesh_mode(slots: Iterable[str]) -> str:
    """The default mode of an outfit piece worn on ``slots`` — the mode of
    every piece without a stored one: ``in_body`` for every slot set,
    footwear included (Ruling A10: "in the body" is the default, own mesh
    and painted must be chosen). ``slots`` stays a parameter so a later
    per-slot rule needs no new call sites."""
    return IN_BODY


def _piece_of(item: Dict[str, Any]) -> Dict[str, Any]:
    return item.get("outfit_piece") if isinstance(item.get("outfit_piece"), dict) else {}


def _slots_of(piece: Dict[str, Any]) -> List[str]:
    slots = piece.get("slots")
    return [str(s) for s in slots] if isinstance(slots, (list, tuple)) else []


def mesh_mode_of(item: Optional[Dict[str, Any]]) -> Optional[str]:
    """The mode of an outfit piece: its stored ``outfit_piece.mesh_mode``,
    or the default (``default_mesh_mode``: in the body) when that is missing
    or not one of ``MESH_MODES``. None for anything that is not an
    ``outfit_piece``. Read-only: never store its answer back on the item —
    a stored mode is a choice (module docstring)."""
    if not isinstance(item, dict) or item.get("category") != "outfit_piece":
        return None
    piece = _piece_of(item)
    mode = piece.get("mesh_mode")
    return mode if mode in MESH_MODES else default_mesh_mode(_slots_of(piece))


#: The slot that makes a piece closable (worn open / closed) by default (``default_closable``).
_CLOSABLE_SLOT = "outer"


def default_closable(slots: Iterable[str]) -> bool:
    """The kind default of the open / closed option (plan Addendum A): ``outer`` among the slots → True;
    footwear (slots exactly ``feet``) is never closable — its chain reads the item image, not the text, so open
    and closed would be one mesh (D-A3)."""
    worn = {str(s) for s in (slots or ()) if s}
    if worn == {FOOTWEAR_SLOT}:
        return False
    return _CLOSABLE_SLOT in worn


def closable_of(item: Optional[Dict[str, Any]]) -> bool:
    """Whether an outfit piece can be worn open: its stored ``outfit_piece.closable`` (bool), else the kind
    default of its slots (``default_closable`` — an item without the key needs no migration). False for anything
    that is not an ``outfit_piece`` and for footwear (slots exactly ``feet``) whatever is stored."""
    if not isinstance(item, dict) or item.get("category") != "outfit_piece":
        return False
    piece = _piece_of(item)
    slots = _slots_of(piece)
    if set(slots) == {FOOTWEAR_SLOT}:
        return False
    stored = piece.get("closable")
    return stored if isinstance(stored, bool) else default_closable(slots)


def garment_kind_of(item: Optional[Dict[str, Any]]) -> Optional[str]:
    """``"hair"`` for a hair garment; for an outfit piece in mode
    ``own_mesh`` ``"footwear"`` when its slots are ``feet`` alone (a
    multi-slot piece with ``feet`` stays clothing), else ``"clothing"``;
    None for anything else."""
    if not isinstance(item, dict):
        return None
    category = item.get("category")
    if category == "garment":
        kind = str((item.get("garment") or {}).get("kind") or "")
        return HAIR if kind == HAIR else None
    mode = mesh_mode_of(item)
    if mode == SHELL:
        return CLOTHING  # a shell is made from the body's skin: never a shoe
    if mode == OWN_MESH:
        return FOOTWEAR if set(_slots_of(_piece_of(item))) == {FOOTWEAR_SLOT} else CLOTHING
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
    return sorted({iid for iid in item_ids if garment_kind_of(get_item(iid)) in OWN_MESH_PIECE_KINDS})


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


def held_outfit_pieces(character_name: str, *,
                       profile: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    """``{item_id: mode}`` of EVERY outfit piece the character holds
    (inventory) or wears (``equipped_pieces``), whatever its mode
    (``mesh_mode_of``) — the Wardrobe's mode select per row. Not gated on
    the pipeline (the select is disabled off it, the mode still shows)."""
    from app.models.inventory import _load_inventory, get_item
    entries = _load_inventory(character_name).get("inventory") or []
    ids = {str(e.get("item_id") or "").strip() for e in entries}
    ids.update(_ids(_profile_of(character_name, profile).get("equipped_pieces")))
    ids.discard("")
    out: Dict[str, str] = {}
    for item_id in sorted(ids):
        mode = mesh_mode_of(get_item(item_id))
        if mode is not None:
            out[item_id] = mode
    return out


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


def piece_live(character_name: str, item_id: str) -> Optional[Dict[str, Any]]:
    """A194: the live CPU line of a piece in flight (``cpu_progress.snapshot``) — its own garment run / drape, else
    the character's Build while its step in flight is this piece's; None when nothing of it runs. Never raises."""
    from app.core import cpu_progress
    snap = cpu_progress.snapshot(f"piece:{character_name}:{item_id}")
    if snap:
        return snap
    try:
        from app.core import figure_build
        step = figure_build.state(character_name).get("step") or {}
        if step.get("item_id") == item_id:
            return step.get("live")
    except Exception:  # noqa: BLE001
        pass
    return None


def piece_status(info: Dict[str, Any], *, worn: bool, base_model_ready: bool,
                 layers: Optional[Dict[str, List[str]]] = None, left_out: bool = False) -> Dict[str, Any]:
    """The Wardrobe row chip of an own-mesh piece from its
    ``garments.garment_info``: ``{state, step, painted, reason, over,
    without}`` (+ ``missing`` when it is left out).

    ``state`` — ``running`` (``step`` = the step in flight), else how far the
    chain of the CURRENT fingerprint got: ``fitted`` (accepted fit on the
    current base model), ``mesh`` (accepted mesh), ``images`` (at least one
    accepted image), ``missing``.
    ``painted`` — the piece is worn (``worn``: on the
    pipeline and in ``equipped_pieces``) without an accepted fit and neither
    left out (kept for a caller without the figure).
    ``reason`` says why, in the outfit
    warning's words: the persisted chain failure ``"<step> — <error>"``,
    else ``base_body.BASE_MODEL_MISSING`` without a base model, else
    ``base_body.NO_MESH_FIT``; None when neither painted nor missing.
    ``missing`` — the delivered figure LEAVES the piece out (``left_out``:
    in ``figure.Figure.left_out`` — Ruling A119: not ready, not worn): the worn piece without an accepted fit is NOT painted — it is
    missing from the outfit model until its mesh is accepted
    (``base_body.MESH_ITEM_NOT_READY``); ``painted`` is then False and
    ``reason`` says why it is not ready. A FOOTWEAR piece (``info["kind"]``)
    is never painted (spec § 9.1): worn without a fit it is ``missing``.
    ``body`` — on a meshed shape only: ``{body_id, status, error}`` of the
    piece's fit on the outfit body worn now (``garment_info["body"]``).
    ``queue_position`` — the 1-based place of the piece's next waiting run
    in the character's garment queue, None when none waits
    (``garments.queue_state``).
    ``over`` / ``without`` — the names of the worn pieces under this one with
    and without a fit (``worn_layers``' entry of the piece, ``layers``): the
    chip says "fitted over <inner>" / "without <inner>". Both keys are left
    out when nothing is worn under it. ``accepted_by_user`` (``fitted`` only,
    Ruling A69) — ``_user_accepted``: what of it the user accepted against its
    checks; left out when nothing."""
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
    footwear = str(info.get("kind") or "") == FOOTWEAR
    painted = absent and not left_out and not footwear
    reason = None
    if absent:
        failed = info.get("failed") if isinstance(info.get("failed"), dict) else None
        if failed and failed.get("step") and failed.get("error"):
            reason = f"{failed['step']} — {failed['error']}"
        else:
            from app.core.figure import LEFT_OFF_REFIT
            # Ruling A134: the figure's rule (``figure._not_fitted_reason``) — a CPU fit alone is no "not ready".
            reason = (LEFT_OFF_REFIT if base_model_ready and info.get("cpu_refit")
                      else base_body.NO_MESH_FIT if base_model_ready else base_body.BASE_MODEL_MISSING)
    out = {"state": state, "step": running, "painted": painted, "reason": reason,
           "queue_position": info.get("queue_position")}
    if left_out or footwear:
        out["missing"] = absent
    if isinstance(info.get("body"), dict):
        # A meshed shape: the piece's fit on the outfit body worn now (garments.body_fit_info).
        out["body"] = {k: info["body"].get(k) for k in ("body_id", "status", "error")}
    if layers and (layers.get("over") or layers.get("without")):
        out.update(over=list(layers.get("over") or []), without=list(layers.get("without") or []))
    taken = _user_accepted(steps, fit) if state == STATE_FITTED else None
    if taken:
        out["accepted_by_user"] = taken
    return out


def _user_accepted(steps: Dict[str, Any], fit: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Ruling A69: the Wardrobe chip's "Accepted by you" — ``{step, view, reason}`` of what the fitted piece uses
    that its checks refused and the user accepted: the fit (``fit.user_accepted``), else the mesh
    (``mesh.user_accepted``), else an image still holding its acceptance (the latest step first); None."""
    block = fit.get("user_accepted") if isinstance(fit.get("user_accepted"), dict) else None
    if block:
        return {"step": "fit", "view": "", "reason": str(block.get("reason") or "")}
    mesh = steps.get("mesh") if isinstance(steps.get("mesh"), dict) else {}
    if mesh.get("user_accepted"):
        return {"step": "mesh", "view": "", "reason": ""}
    for step in reversed([k for k in steps if k not in ("mesh", "fit")]):
        views = steps.get(step)
        for view, tile in (views.items() if isinstance(views, dict) else ()):
            taken = tile.get("user_accepted") if isinstance(tile, dict) else None
            if isinstance(taken, dict) and taken.get("holds"):
                return {"step": step, "view": str(view), "reason": "; ".join(str(r) for r in taken.get("reasons") or [])}
    return None


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
    items: {item_id: piece_status}, modes: {item_id: mode}, overlaps}`` —
    ``items`` covers every own-mesh piece the character holds or wears
    (``held_clothing``; a worn piece over others names them,
    ``worn_layers``), ``modes`` the mode of EVERY outfit piece it holds or
    wears (``held_outfit_pieces``, the row's mode select), ``overlaps`` the worn
    ones whose layer order is a guess (``mesh_overlaps``: a cycle, put in
    slot rank order; [] off the pipeline, where the mode is ignored),
    ``queue_running`` / ``queue`` the character's garment queue
    (``garments.queue_state``: the item id in flight, the waiting ones).
    Open / closed (plan 2026-11-12-unified-worn-pieces Task 11b): ``closable``
    ``{item_id: bool}`` for every held outfit piece (``closable_of``, the
    row's "Can be worn open" checkbox), ``piece_state`` ``{item_id: "open"}``
    of the worn pieces worn open (``outfit_options.piece_states``; absent =
    closed), ``names_state`` ``{item_id: True}`` for a closable piece whose
    prompt fragment already names a state (ruling A6, the row's hint) and
    ``auto_build`` (``figure_build.auto_build_on``: a toggle then starts the
    Build). ``materials`` ``{item_id: {choice, guess}}`` for every held outfit
    piece (``piece_material.describe``, Ruling A36: the row's material select)."""
    from app.core import base_body, body_slots, garments
    profile = _profile_of(character_name, profile)
    pipeline = base_body.is_base_pipeline(character_name, profile=profile)
    base = base_body.current_base(character_name, profile=profile) if pipeline else None
    left_out: Dict[str, str] = {}
    if pipeline:
        from app.core import figure
        left_out = dict(figure.delivered_figure_cached(character_name, profile=profile).left_out)
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
                                      left_out=item_id in left_out)
        items[item_id]["live"] = piece_live(character_name, item_id)  # A194
    overlaps = (mesh_overlaps(pieces, slot_order=body_slots.piece_slots_for_character(character_name))
                if pipeline else [])
    queue = garments.queue_state(character_name)
    modes = held_outfit_pieces(character_name, profile=profile)
    from app.core import figure_build, outfit_options
    from app.models.inventory import get_item
    closable = {item_id: closable_of(get_item(item_id)) for item_id in modes}
    names_state = {item_id: True for item_id, on in closable.items()
                   if on and outfit_options.fragment_names_state((get_item(item_id) or {}).get("prompt_fragment"))}
    from app.core import piece_material
    materials = {item_id: piece_material.describe(get_item(item_id)) for item_id in modes}
    return {"pipeline": pipeline, "items": items,
            "modes": modes, "overlaps": overlaps,
            "queue_running": queue["queue_running"], "queue": queue["queue"],
            "hem": _wardrobe_hem(character_name, profile, pipeline),
            "closable": closable, "piece_state": outfit_options.piece_states(profile), "names_state": names_state,
            "materials": materials,
            "auto_build": figure_build.auto_build_on(character_name, profile=profile)}


def _wardrobe_hem(character_name: str, profile: Dict[str, Any], pipeline: bool) -> Dict[str, Any]:
    """The Wardrobe's boot hem control (boots spec § 8.3): ``outfit_options.hem_applicable`` — ``{applicable,
    boot_item, trousers_item, reason, mode}`` — plus ``fallback`` (``too_wide`` / ``shaft_too_low`` when the tucked
    pair is worn over the boot: the assembly's layered fit, ``garment_assembly.hem_state``; None otherwise or while it is
    built). Off the pipeline nothing applies."""
    from app.core import outfit_options
    if not pipeline:
        return {"applicable": False, "boot_item": None, "trousers_item": None, "reason": "off the base body pipeline",
                "mode": outfit_options.boot_hem(profile), "fallback": None}
    try:
        hem = outfit_options.hem_applicable(character_name, profile=profile)
    except Exception:  # noqa: BLE001 — the control is left out, the Wardrobe still loads
        from app.core.log import get_logger
        get_logger("garment_set").exception("Wardrobe %s: boot hem unreadable", character_name)
        return {"applicable": False, "boot_item": None, "trousers_item": None, "reason": "unreadable",
                "mode": outfit_options.boot_hem(profile), "fallback": None}
    hem["fallback"] = None
    if hem["applicable"]:
        from app.core import garment_assembly
        state = garment_assembly.hem_state(character_name)
        if state and state["trousers"] == hem["trousers_item"] and state["mode"] == hem["mode"]:
            hem["fallback"] = state["fallback"]
    return hem
