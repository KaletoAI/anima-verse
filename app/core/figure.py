"""One figure, one mode per worn piece — the pure resolver (plan
``docs/superpowers/plans/2026-11-12-unified-worn-pieces.md`` Task 4; spec
``docs/superpowers/specs/2026-11-12-unified-worn-pieces-design.md``,
builder-check ruling 1).

Every worn outfit piece has the item mode ``garment_set.mesh_mode_of``:
``in_body`` (meshed as part of the body), ``painted`` (on the body's
texture) or ``own_mesh`` (its own garment mesh, fitted on top). A figure is
built from two keys:

- the SHAPE key (``shape_key``): the body mesh, keyed by the in-body set —
  and by the worn hairstyle when the plain body does not carry it
  (``garment_hair.shape_hair``, plan Task 13 / D4: another ``body``
  hairstyle puts its text into the shape, a HairDeck one on a haired plain
  body needs a bald shape). With nothing in the body and the plain body's
  own hair the shape IS the base (``bsig``): today's base, haired iff its
  hairstyle is in the body, so no base is rebuilt. Otherwise ``"ob"`` + 8
  hex over ``shape_inputs`` (the prefix and regex of
  ``base_body.OUTFIT_BODY_RE``, so the outfit body folders, collision and
  ``model3d`` keep working). Painted and own-mesh pieces never enter it.
- the TEXTURE key (``texture_key``): the painted set on that shape. On the
  plain body it is today's tsig (``base_body.texture_signature`` of
  ``texture_inputs`` with every own-mesh piece left out), so stored painted
  bodies keep their keys; on a meshed shape ``"tex"`` + 12 hex over the
  shape and the dress text without own-mesh and in-body pieces, ``""`` when
  nothing is painted there.

Pure and read-only: no locks, no writes, no hub. Off the base-body pipeline
every worn piece counts as painted (``garment_set.worn_garments`` ignores the
modes there), so the shape is the plain one.

Stored shapes (Task 5): a meshed shape is stored as an outfit body under its
shape key (``base_body.outfit_body_path``); its sidecars carry the parent
record ``outfit_body`` = ``{body_id, shape_key (== body_id), version
(SHAPE_VERSION), shape_inputs, base_signature, base_variant, built_for, views,
used_views, view_guard, view_warnings}``. ``stored_shape`` judges one;
``predicted_keys`` is what the artefact GC asks per live outfit. Bodies stored
under the old texture-keyed ids are re-keyed once at boot
(``figure_migration.rekey_bodies_once``) or left stale.

What is stored (Task 10, Ruling 5a): ``stored`` lists every stored shape and
painted body with the artefact graph's verdict; ``delete_stored`` is the
Figure tab's explicit Delete of one of them (never one an outfit would be
built on now). ``stored_unneeded`` is the subset an automatic collect keeps
although nothing predicts it.
"""
import hashlib
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

#: Bumped when a shape is meshed differently for the same inputs.
SHAPE_VERSION = 2
#: Bumped when a painted texture on a meshed shape is made differently.
SHAPE_TEXTURE_VERSION = 1


@dataclass(frozen=True)
class WornSets:
    """The worn pieces of a character split by mode (``worn_sets``)."""
    in_body: Tuple[str, ...]      # sorted item ids, mode in_body
    painted: Tuple[str, ...]      # sorted, mode painted (+ every non-garment worn piece)
    own: Dict[str, str]           # item id -> "clothing" | "footwear" (mode own_mesh)
    hair_in_body: bool            # garment_hair.hair_in_body: the worn hairstyle's mode is ``body``
    hair_item: str                # worn HairDeck or HAAR hairstyle id (a grafted hair mesh), "" otherwise
    #: The worn ``{slot: item id}`` the sets were resolved from — the dress
    #: texts of ``shape_inputs`` / ``texture_key`` are composed from it.
    pieces: Dict[str, str] = field(default_factory=dict)
    #: Sorted worn closable item ids worn OPEN, any mode (plan Task 11a,
    #: ``outfit_options.piece_states``) — "worn open" in their dress text, so
    #: an open in-body / painted piece has its own shape / texture key; all
    #: closed keys every text as before (D-A1).
    open: Tuple[str, ...] = ()
    #: What the worn hairstyle adds to the body shape (``garment_hair.shape_hair``, D4): "" (the plain body
    #: carries it), its text (another ``body`` hairstyle) or ``garment_hair.BALD``; "" off the pipeline.
    hair_shape: str = ""
    #: The worn hairstyle's id when it is not the plain body's (``garment_hair.hair_style_id``), else "".
    hair_style: str = ""


def _open_map(open_ids) -> Dict[str, str]:
    """``{item_id: "open"}`` of a set of open ids (the shape ``outfit_options`` stores)."""
    from app.core.outfit_options import OPEN
    return {str(i): OPEN for i in open_ids or ()}


def _profile_of(character_name: str, profile: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if profile is not None:
        return profile
    from app.models.character import get_character_profile
    return get_character_profile(character_name) or {}


def _canonical(data: Dict[str, Any]) -> bytes:
    return json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def worn_sets(character_name: str, *, pieces: Optional[Dict[str, str]] = None,
              profile: Optional[Dict[str, Any]] = None,
              piece_state: Optional[Dict[str, str]] = None) -> WornSets:
    """The worn pieces of ``pieces`` (``{slot: item id}``, default: the
    profile's ``equipped_pieces``) by mode. A multi-slot piece counts once.
    Own-mesh pieces are the worn garments (``garment_set.worn_garments``,
    empty off the pipeline) among ``pieces``; in-body pieces need the
    pipeline as well; everything else — mode painted, or no outfit piece at
    all — is painted. ``hair_item``: the worn hairstyle when it is HairDeck
    or HAAR hair (a grafted hair mesh), else ``""``. ``open``: the worn closable pieces worn open —
    ``piece_state`` (``{item_id: "open"}``), None → the profile's
    (``outfit_options.piece_states``). ``hair_shape`` / ``hair_style``: the
    worn hairstyle against the plain body's (``garment_hair.shape_hair`` /
    ``hair_style_id``), on the pipeline only."""
    from app.core import base_body, garment_hair, garment_set
    from app.core.outfit_options import OPEN, piece_states
    from app.models.inventory import get_item
    profile = _profile_of(character_name, profile)
    if pieces is None:
        pieces = profile.get("equipped_pieces") or {}
    worn = {str(slot): str(iid).strip() for slot, iid in (pieces or {}).items() if iid and str(iid).strip()}
    ids = set(worn.values())
    own: Dict[str, str] = {}
    for item_id in garment_set.worn_garments(character_name, profile=profile, pieces=worn):
        kind = garment_set.garment_kind_of(get_item(item_id))
        if item_id in ids and kind in garment_set.OWN_MESH_PIECE_KINDS:
            own[item_id] = kind
    pipeline = bool(own) or base_body.is_base_pipeline(character_name, profile=profile)
    in_body = sorted(i for i in ids - set(own)
                     if pipeline and garment_set.mesh_mode_of(get_item(i)) == garment_set.IN_BODY)
    painted = sorted(ids - set(own) - set(in_body))
    mode = garment_hair.hair_mode(character_name, profile=profile)
    state = piece_states(profile, worn) if piece_state is None else (piece_state or {})
    opened = sorted(i for i in ids if state.get(i) == OPEN and garment_set.closable_of(get_item(i)))
    hair_pipeline = pipeline
    return WornSets(in_body=tuple(in_body), painted=tuple(painted), own=dict(sorted(own.items())),
                    hair_in_body=mode == garment_hair.BODY_MODE,
                    hair_item=(garment_hair.worn_hair_id(character_name, profile)
                               if mode in (garment_hair.HAIRDECK_MODE, garment_hair.HAAR_MODE) else ""),
                    pieces=dict(worn), open=tuple(opened),
                    hair_shape=garment_hair.shape_hair(character_name, profile) if hair_pipeline else "",
                    hair_style=garment_hair.hair_style_id(character_name, profile) if hair_pipeline else "")


def _dress_texts(character_name: str, sets: WornSets, *, left_out, items: Optional[list],
                 profile: Dict[str, Any]) -> Dict[str, str]:
    """``{view: dress text}`` of every dressed view with ``left_out`` left
    out of the pieces (``base_body.dress_text(mesh_items=…)``)."""
    from app.core import base_body
    meshed = sorted({str(i) for i in left_out})
    return {view: base_body.dress_text(character_name, view, pieces=dict(sets.pieces), items=list(items or []),
                                       profile=profile, mesh_items=meshed)
            for view in base_body.dressed_views()}


def _dressed_profile(profile: Dict[str, Any], sets: WornSets, items: Optional[list]) -> Dict[str, Any]:
    """The profile wearing ``sets.pieces`` / ``items`` (as
    ``base_body._worn_profile``) with ``sets.open`` as its open pieces — the
    dress texts say "worn open" for exactly those (``outfit_renderer``)."""
    from app.core.outfit_options import with_piece_state
    dressed = with_piece_state(profile, _open_map(sets.open))
    dressed["equipped_pieces"] = dict(sets.pieces)
    dressed["equipped_items"] = list(items or [])
    return dressed


def shape_inputs(character_name: str, sets: WornSets, *, bsig: str, variant: str,
                 profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """What a meshed shape is made of: the base signature and variant, the
    hair-in-body switch, the side-view switch and the dress text of every
    dressed view with the painted and own-mesh pieces left out (the in-body
    pieces only; held items never enter the body) — and ``hair`` (D4) only
    when the worn hairstyle is not the plain body's own hair
    (``WornSets.hair_shape``: another hairstyle's text, or ``"bald"``), so
    every shape stored before hairstyles keeps its key byte for byte."""
    from app.core import base_body
    profile = _dressed_profile(_profile_of(character_name, profile), sets, [])
    inputs = {"version": SHAPE_VERSION,
              "base_signature": bsig,
              "base_variant": variant,
              "hair_in_body": sets.hair_in_body,
              "side_views": base_body.side_views_dressed(),
              "dress_text": _dress_texts(character_name, sets, left_out=(*sets.painted, *sets.own), items=[],
                                         profile=profile)}
    if sets.hair_shape:
        inputs["hair"] = sets.hair_shape
    return inputs


def shape_key_of(inputs: Dict[str, Any]) -> str:
    """``"ob"`` + the first 8 hex of sha256 over the canonical JSON of the
    shape inputs ``inputs``."""
    return "ob" + hashlib.sha256(_canonical(inputs)).hexdigest()[:8]


def shape_key(character_name: str, sets: WornSets, *, bsig: str, variant: str,
              profile: Optional[Dict[str, Any]] = None) -> str:
    """``bsig`` for the plain body (nothing in the body, the plain body's own
    hair), else ``"ob"`` + the first 8 hex of sha256 over the canonical JSON
    of ``shape_inputs``."""
    if not sets.in_body and not sets.hair_shape:
        return bsig
    return shape_key_of(shape_inputs(character_name, sets, bsig=bsig, variant=variant, profile=profile))


def is_plain(shape: str) -> bool:
    """Whether ``shape`` is the plain body — a base signature."""
    from app.core import base_body
    return base_body.is_base_signature(shape)


def texture_key(character_name: str, sets: WornSets, *, shape: str, bsig: str, variant: str,
                items: Optional[list] = None, profile: Optional[Dict[str, Any]] = None) -> str:
    """The painted texture on ``shape``. Plain body: today's tsig —
    ``base_body.texture_signature(texture_inputs(mesh_effective=<own-mesh
    pieces>))`` — byte-identical for the same pieces. Meshed shape: ``"tex"``
    + the first 12 hex of sha256 over ``{"version", "shape", "base_variant",
    "dress_text"}`` with the own-mesh AND in-body pieces left out; ``""``
    when nothing is painted there (every dress text empty).

    An outfit with a reference image (Ruling A74b, ``outfit_references``)
    whose figure paints something adds the picture's content
    (``outfit_reference``) to either key: its dressed front is an edit of
    that picture, so its texture is its own. Without a reference — or with
    nothing painted — the key is byte-identical to the one before.

    Both keys carry the painted pieces' ``paint_region`` (Ruling A127): a
    texture is painted only inside the body regions of their slots."""
    from app.core import base_body, outfit_references, paint_region
    original = _profile_of(character_name, profile)
    reference = outfit_references.texture_part(character_name, sets.pieces, sets.open, painted=sets.painted,
                                               profile=original)
    profile = _dressed_profile(original, sets, items)
    if is_plain(shape):
        plain = base_body.texture_inputs(
            character_name, pieces=dict(sets.pieces), items=list(items or []), variant=variant,
            mesh_effective=sorted(sets.own), bsig=bsig, profile=profile)
        if reference and any(plain["dress_text"].values()):
            plain["outfit_reference"] = reference
        return base_body.texture_signature(plain)
    texts = _dress_texts(character_name, sets, left_out=(*sets.own, *sets.in_body), items=items, profile=profile)
    if not any(texts.values()):
        return ""
    inputs = {"version": SHAPE_TEXTURE_VERSION, "shape": shape, "base_variant": variant, "dress_text": texts}
    region = paint_region.paint_region(sets.pieces, sets.painted)
    if region:
        inputs["paint_region"] = region
    if reference:
        inputs["outfit_reference"] = reference
    return "tex" + hashlib.sha256(_canonical(inputs)).hexdigest()[:12]


def predicted_variant(character_name: str, sets: WornSets, items: Optional[list], *,
                      profile: Optional[Dict[str, Any]] = None) -> str:
    """The base variant a figure of ``sets`` is built from — the build's
    rule (``base_body.texture_variant``): the outfit variant for a dressed
    combination (dress text with the own-mesh pieces left out) or one with
    own-mesh pieces, else ``"rigged"``. Read-only."""
    from app.core import base_body
    profile = _profile_of(character_name, profile)
    dressed = bool(base_body.dress_text(character_name, "front", pieces=dict(sets.pieces), items=list(items or []),
                                        profile=_dressed_profile(profile, sets, items),
                                        mesh_items=sorted(sets.own)))
    return base_body.texture_variant(character_name, dict(sets.pieces), dressed=dressed,
                                     mesh={"intended": sorted(sets.own)}, profile=profile)


def _state_in(sets: WornSets, item_id: str) -> str:
    """``"open"`` / ``"closed"``: the state ``sets`` wear a piece in (``WornSets.open``)."""
    from app.core.outfit_options import CLOSED, OPEN
    return OPEN if item_id in sets.open else CLOSED


def predicted_keys(character_name: str, pieces: Optional[Dict[str, str]], items: Optional[list], *,
                   bsig: str, profile: Optional[Dict[str, Any]] = None,
                   piece_state: Optional[Dict[str, str]] = None) -> Tuple[str, str]:
    """``(shape key, texture key)`` a figure of the outfit ``pieces`` /
    ``items`` stands on NOW — ``worn_sets`` under the items' modes, the
    variant of ``predicted_variant``, ``shape_key`` and ``texture_key``,
    — the keys a Build makes (Ruling A119: no interim shape exists any
    more). Read-only (no garment chain, no
    image): the artefact GC asks it for every live outfit. The texture key
    is ``""`` on a meshed shape with nothing painted. ``piece_state``: the
    outfit's open pieces (a saved set's), None → the profile's."""
    profile = _profile_of(character_name, profile)
    sets, _notes = _refused_sets(worn_sets(character_name, pieces=dict(pieces or {}), profile=profile,
                                           piece_state=piece_state))
    variant = predicted_variant(character_name, sets, items, profile=profile)
    shape = shape_key(character_name, sets, bsig=bsig, variant=variant, profile=profile)
    return shape, texture_key(character_name, sets, shape=shape, bsig=bsig, variant=variant, items=items,
                              profile=profile)


def stored_shape(character_name: str, key: str, *, view_shas: Dict[str, str]) -> Optional[Dict[str, Any]]:
    """The sidecar of the stored shape ``key`` (an outfit body,
    ``model3d/<key>.glb``) when it is current: a rigged humanoid GLB without
    ``rig_error`` whose parent record ``outfit_body`` names ``key`` as
    ``body_id`` and ``shape_key``, ``version == SHAPE_VERSION`` and exactly
    the dressed view contents ``view_shas`` it was meshed from
    (``base_body.texture_view_shas``); else None. Read-only."""
    from app.core import base_body
    if not base_body.is_outfit_body_signature(key):
        return None
    path = base_body.outfit_body_path(character_name, key)
    meta = base_body._ref_sidecar(path)
    record = base_body._dict_of(meta.get("outfit_body"))
    if not path.is_file() or meta.get("rig") != "mixamo" or meta.get("rig_error"):
        return None
    if (record.get("body_id") != key or record.get("shape_key") != key
            or record.get("version") != SHAPE_VERSION or record.get("views") != view_shas):
        return None
    return meta


# --- The wanted and the delivered figure (Task 6, rulings 2 and 7) -------------
#
# The WANTED figure is what the worn pieces call for under their item modes:
# the in-body set meshed into ``shape``, the painted set on ``texture``, every
# own-mesh piece fitted on top, the hair as its method says. The DELIVERED
# figure is what is shown NOW — in the Figure tab's 3D view and in the game
# alike (Ruling A119, replacing the interim rule of ruling 2 / A11): it is
# always assembled on the NEWEST current body, and of the worn pieces only the
# ones whose own result is ready for that body are worn; every other piece is
# simply LEFT OFF (``left_out``, item -> reason) — never painted meanwhile,
# never put into an interim body shape, never taken from an older model.
# Judged at the call:
#
# 1. Body: the wanted shape when it is stored and current (``stored_shape``
#    of its current views, ``base_body.shape_view_shas``), else the plain
#    body — then every wanted in-body piece is left off (``LEFT_OFF_SHAPE``).
# 2. Own-mesh pieces: worn when the accepted fit exists — on the plain body
#    ``garment_store.accepted_fit`` on the base model in the worn state; on a
#    meshed shape that base fit and no fit refused on the shape
#    (``garments.body_fit``: an accepted or still-to-be-made CPU fit counts).
#    Else left off with the reason (the chain's failure, no fit yet, or
#    ``FIT_REFUSED``). A clothing piece worn OPEN whose open mesh is missing
#    is grafted with its CLOSED mesh (ruling F13 b, ``shown_closed``). A left
#    off piece stays in the outfit model's unpainted set, so the garment
#    assembly grafts it on the CPU as soon as its fit is accepted
#    (``garment_assembly.effective_mesh_items``) — no hub job, no rebuild.
# 3. Hair (the worn hairstyle, plan Task 13): HairDeck hair on the plain body
#    when that body is haired (``base_body.stored_base_haired``) is shown as
#    the plain body has it, ``"body"`` — its bald shape (D4) is not built yet;
#    HairDeck without a fit on the delivered shape is ``"bald"``. Another
#    ``body`` hairstyle lives in its body shape; on the plain body meanwhile
#    the plain body's hair shows (``hair_style`` ""). Hair wanted IN the
#    body on a plain body rendered bald keeps the worn HairDeck hair
#    meanwhile (ruling F13 a, ``interim_hair_fit``).
# 4. Refusal branch (``PAINT_ON_SHAPE`` False, ruling 7): nothing is painted
#    on a meshed shape; the wanted figure meshes the painted pieces worn with
#    in-body pieces into the shape (``notes`` = ``PAINT_NEEDS_PLAIN``).
# 5. Texture: ``texture_key`` of exactly the painted set on the delivered
#    body, every grafted and every left-off piece out of its dress text. No
#    other texture stands in: until the outfit model of this exact figure is
#    built, the plain body itself is served (``model3d.find_model3d_serving``
#    match ``"base"``) with the ready own-mesh pieces put on by the garment
#    assembly (``garment_assembly.bare_meta_of``) — the painted pieces left
#    off meanwhile; never an older model of another outfit, body or figure.

#: Ruling 1b (Task 1's spike): painting onto a meshed shape works. False
#: switches to the refusal branch of ruling 7 (rule 4 above).
PAINT_ON_SHAPE = True
#: ``Figure.notes`` of a painted piece meshed into the shape (refusal branch).
PAINT_NEEDS_PLAIN = "In the body here: painting needs the plain body"
#: ``Figure.left_out`` of an in-body piece while its body shape is not built (Ruling A119).
LEFT_OFF_SHAPE = "Body shape not built"
#: ``Figure.notes`` of a piece worn open shown with its closed mesh until its open mesh is built (ruling F13 b).
SHOWN_CLOSED = "Shown closed until its open mesh is built"
#: The note of a worn-open piece's ONE pending change while its open mesh is missing (ruling F13 b).
OPEN_MESH_MISSING = "worn open — open mesh missing"
#: The note of the hair's pending change when the hair is wanted in the body but the plain body is bald (F13 a).
HAIR_REBUILD = "in the body → plain body rebuild"
#: ``Figure.hair``. ``HAIR_HAIRDECK`` names a GRAFTED hair mesh — HairDeck or HAAR (the value predates HAAR
#: and is part of stored figures, so it is kept).
HAIR_BODY, HAIR_HAIRDECK, HAIR_BALD = "body", "hairdeck", "bald"
#: ``pending_changes`` keys of the body and the hair.
BODY_KEY, HAIR_KEY = "body", "hair"
#: The plain body's pending change (plan 2026-11-12-unified-worn-pieces ruling 8a): only a manual Build
#: (or the base_refresh improvement) spends its hub jobs — the ``note`` of the ``body`` change and
#: ``figure_build.Step.manual``.
BASE_OUTDATED = "Base body outdated — Build to refresh"
BASE_MISSING = "No base body yet — Build to create"
#: The wanted / delivered words of a piece in ``pending_changes``.
LEFT_OUT = "left_out"
#: Why a wanted own-mesh piece is not on the figure delivered (Ruling A23 c, T15-F1): its fit on the wanted body
#: shape was refused — a cached failure keyed by the fit's inputs and the shape (``garment_store.body_failure``).
FIT_REFUSED = "Fit refused — {reason}"


def _strip_refused(reason: str) -> str:
    """``reason`` without the fit paths' own "fit refused — " prefix (never "Fit refused — fit refused — …")."""
    from app.core.fit_attempts import strip_prefix
    return strip_prefix(reason)


@dataclass(frozen=True)
class Figure:
    """A figure of a character (block above)."""
    signature: str                  # mesh-input signature of the worn outfit
    bsig: str                       # the plain body
    shape: str                      # bsig (plain body) or "ob…"
    texture: str                    # "tex…" or "" (nothing painted on a meshed shape)
    in_body: Tuple[str, ...]        # meshed into ``shape``
    painted: Tuple[str, ...]        # painted on ``texture``
    own: Tuple[str, ...]            # own-mesh pieces grafted (fit on ``shape`` exists)
    left_out: Dict[str, str] = field(default_factory=dict)   # item -> reason (Ruling A119: not ready, not worn)
    notes: Dict[str, str] = field(default_factory=dict)      # item -> PAINT_NEEDS_PLAIN
    hair: str = HAIR_BODY           # "body" | "hairdeck" | "bald"
    #: The worn ``{slot: item id}`` the figure was resolved from (the dress
    #: texts of its shape and texture are composed from it).
    pieces: Dict[str, str] = field(default_factory=dict)
    #: The worn closable pieces worn open (``WornSets.open``), sorted.
    open: Tuple[str, ...] = ()
    #: Pieces worn open grafted with their CLOSED mesh until the open one is
    #: built (ruling F13 b), sorted — a subset of ``open`` and ``own``.
    shown_closed: Tuple[str, ...] = ()
    #: The hairstyle shown when it is not the plain body's (``WornSets.hair_style``; "" while the plain body's
    #: hair or no hair is shown) — two figures that differ only in the worn HairDeck hairstyle differ here.
    hair_style: str = ""
    #: Ruling A23 (T15-F1), never recorded (``as_dict``) nor compared: the wanted own-mesh pieces whose fit on the
    #: delivered body shape is refused (item -> reason) — left off (Ruling A119), the Figure tab offers the refit.
    fit_refused: Dict[str, str] = field(default_factory=dict, compare=False)
    #: The body shape those fits were refused on (Ruling A31: the Figure tab names it) — "" without a refusal.
    fit_refused_on: str = field(default="", compare=False)

    def as_dict(self) -> Dict[str, Any]:
        """The JSON form an outfit model sidecar records as ``figure`` —
        ``open`` only when a piece is open (an all-closed figure records
        what it recorded before the open / closed option, D-A1),
        ``shown_closed`` only when a piece stands in closed, ``hair_style`` only
        when another hairstyle than the plain body's is shown (a figure of
        the plain body's hairstyle records what it recorded before
        hairstyles)."""
        out = {"signature": self.signature, "bsig": self.bsig, "shape": self.shape, "texture": self.texture,
               "in_body": list(self.in_body), "painted": list(self.painted), "own": list(self.own),
               "left_out": dict(self.left_out), "notes": dict(self.notes),
               "hair": self.hair, "pieces": dict(self.pieces)}
        if self.open:
            out["open"] = list(self.open)
        if self.shown_closed:
            out["shown_closed"] = list(self.shown_closed)
        if self.hair_style:
            out["hair_style"] = self.hair_style
        return out

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Figure":
        def ids(key: str) -> Tuple[str, ...]:
            return tuple(sorted(str(i) for i in data.get(key) or [] if isinstance(i, str) and i))

        def texts(key: str) -> Dict[str, str]:
            value = data.get(key)
            return {str(k): str(v) for k, v in value.items()} if isinstance(value, dict) else {}

        return cls(signature=str(data.get("signature") or ""), bsig=str(data.get("bsig") or ""),
                   shape=str(data.get("shape") or ""), texture=str(data.get("texture") or ""),
                   in_body=ids("in_body"), painted=ids("painted"), own=ids("own"), left_out=texts("left_out"),
                   notes=texts("notes"), hair=str(data.get("hair") or HAIR_BODY),
                   pieces=texts("pieces"), open=ids("open"), shown_closed=ids("shown_closed"),
                   hair_style=str(data.get("hair_style") or ""))

    def state_of(self, item_id: str) -> str:
        """Where a worn piece is in this figure: ``in_body`` / ``painted`` /
        ``own_mesh`` / ``left_out`` (``""`` when not worn)."""
        from app.core import garment_set
        if item_id in self.in_body:
            return garment_set.IN_BODY
        if item_id in self.own:
            return garment_set.OWN_MESH
        if item_id in self.painted:
            return garment_set.PAINTED
        return LEFT_OUT if item_id in self.left_out else ""


def shape_plan(character_name: str, fig: "Figure", items: Optional[list], *,
               profile: Optional[Dict[str, Any]] = None) -> Tuple[WornSets, str, Optional[Dict[str, Any]]]:
    """``(worn sets, variant, shape inputs)`` the meshed shape of ``fig`` is
    made of — the WANTED figure (``_wanted``'s rule for its pieces and held
    ``items``; Ruling A119: the delivered shape is always a wanted one); the inputs are None when no piece is in the body. The caller compares
    ``shape_key_of(inputs)`` with ``fig.shape`` (the worn modes may have
    changed since ``fig`` was resolved)."""
    profile = _profile_of(character_name, profile)
    sets = worn_sets(character_name, pieces=dict(fig.pieces), profile=profile, piece_state=_open_map(fig.open))
    sets, _notes = _refused_sets(sets)
    variant = predicted_variant(character_name, sets, _items_of(profile, items), profile=profile)
    if not sets.in_body and not sets.hair_shape:
        return sets, variant, None
    return sets, variant, shape_inputs(character_name, sets, bsig=fig.bsig, variant=variant, profile=profile)


def built_figure(meta: Dict[str, Any]) -> Optional[Figure]:
    """The figure an outfit model was built as (its sidecar key ``figure``),
    None when it records none (built before Task 6)."""
    data = meta.get("figure") if isinstance(meta, dict) else None
    return Figure.from_dict(data) if isinstance(data, dict) else None


def _items_of(profile: Dict[str, Any], items: Optional[list]) -> list:
    if items is not None:
        return list(items)
    worn = profile.get("equipped_items")
    return list(worn) if isinstance(worn, list) else []


def _signature(character_name: str, pieces: Dict[str, str], items: list, profile: Dict[str, Any],
               open_ids=()) -> str:
    """The mesh-input signature of ``pieces`` / ``items`` with the open pieces ``open_ids``
    (``model_refs.current_outfit_state``'s rule)."""
    from app.core import model_refs
    return model_refs.mesh_signature(dict(pieces), list(items), character_name,
                                     model_refs.mesh_variant(character_name, dict(pieces), profile),
                                     model_refs.mesh_items_token(character_name, dict(pieces), profile),
                                     piece_state=_open_map(open_ids) or None)


def _refused_sets(sets: WornSets) -> Tuple[WornSets, Dict[str, str]]:
    """The refusal branch (``PAINT_ON_SHAPE`` False): the painted pieces worn
    with in-body pieces are meshed into the shape — ``(sets, notes)``."""
    from dataclasses import replace
    if PAINT_ON_SHAPE or not sets.in_body or not sets.painted:
        return sets, {}
    notes = {item_id: PAINT_NEEDS_PLAIN for item_id in sets.painted}
    return replace(sets, in_body=tuple(sorted({*sets.in_body, *sets.painted})), painted=()), notes


def _wanted(character_name: str, *, profile: Dict[str, Any], pieces: Optional[Dict[str, str]],
            items: Optional[list], piece_state: Optional[Dict[str, str]] = None) -> Tuple[Figure, WornSets, str]:
    """``(wanted figure, its worn sets, variant)``; ``piece_state`` None → the profile's open pieces."""
    from app.core import base_body
    if pieces is None:
        pieces = profile.get("equipped_pieces") or {}
    items = _items_of(profile, items)
    sets, notes = _refused_sets(worn_sets(character_name, pieces=dict(pieces), profile=profile,
                                          piece_state=piece_state))
    bsig = base_body.base_signature(character_name, profile=profile)
    variant = predicted_variant(character_name, sets, items, profile=profile)
    shape = shape_key(character_name, sets, bsig=bsig, variant=variant, profile=profile)
    texture = ("" if notes and not is_plain(shape)
               else texture_key(character_name, sets, shape=shape, bsig=bsig, variant=variant, items=items,
                                profile=profile))
    figure = Figure(signature=_signature(character_name, sets.pieces, items, profile, sets.open), bsig=bsig,
                    shape=shape, texture=texture, in_body=sets.in_body, painted=sets.painted,
                    own=tuple(sorted(sets.own)), notes=notes if not is_plain(shape) else {},
                    hair=HAIR_BODY if sets.hair_in_body else HAIR_HAIRDECK if sets.hair_item else HAIR_BALD,
                    pieces=dict(sets.pieces), open=sets.open, hair_style=sets.hair_style)
    return figure, sets, variant


def wanted_figure(character_name: str, *, profile: Optional[Dict[str, Any]] = None,
                  pieces: Optional[Dict[str, str]] = None, items: Optional[list] = None,
                  piece_state: Optional[Dict[str, str]] = None) -> Figure:
    """The figure the worn pieces (``pieces`` / ``items``, default the
    profile's ``equipped_pieces`` / ``equipped_items``) call for under their
    item modes and open pieces (``piece_state``, None → the profile's) —
    nothing judged as built or not. Read-only."""
    return _wanted(character_name, profile=_profile_of(character_name, profile), pieces=pieces, items=items,
                   piece_state=piece_state)[0]


def _shape_stored(character_name: str, shape: str, bsig: str) -> bool:
    """Whether the meshed shape ``shape`` is stored and current
    (``stored_shape`` against its views made from the current plain body)."""
    from app.core import base_body
    return stored_shape(character_name, shape, view_shas=base_body.shape_view_shas(character_name, shape, bsig)) \
        is not None


def _not_fitted_reason(character_name: str, item_id: str, *, base_sha: str, profile: Dict[str, Any],
                       state: Optional[str] = None) -> str:
    """Why an own-mesh piece has no fit (in ``state``, None: the worn one): its chain's persisted failure
    (``base_body.MESH_ITEM_CHAIN_FAILED``), else ``NO_MESH_FIT`` /
    ``BASE_MODEL_MISSING``."""
    from app.core import base_body, garments
    try:
        failure = garments.cached_failure(character_name, item_id, profile=profile, state=state)
    except Exception:  # noqa: BLE001 — a reason, never a failure of the resolver
        failure = None
    if failure and failure.get("step") and failure.get("error"):
        return base_body.MESH_ITEM_CHAIN_FAILED.format(step=failure["step"], error=failure["error"])
    return base_body.NO_MESH_FIT if base_sha else base_body.BASE_MODEL_MISSING


def _fit_on(character_name: str, item_id: str, *, shape: str, base_sha: str,
            profile: Dict[str, Any], state: Optional[str] = None) -> Tuple[bool, str]:
    """``(fitted, reason)`` of a garment (own-mesh piece or HairDeck hair) on
    the delivered ``shape`` (rule 2 of the block above) — for a clothing
    piece in ``state`` (the figure's open set; None: the profile's): a piece
    worn open needs its OPEN fit (plan Task 11b)."""
    from app.core import garment_store, garments
    if not item_id:
        return False, ""
    base_fit = (garment_store.accepted_fit(character_name, item_id, base_model_sha=base_sha, profile=profile,
                                           state=state)
                if base_sha else None)
    if base_fit is None:
        return False, _not_fitted_reason(character_name, item_id, base_sha=base_sha, profile=profile,
                                         state=state)
    if is_plain(shape):
        return True, ""
    on_shape = garments.body_fit(character_name, item_id, body_id=shape,
                                 body_sha=garments.body_sha256(character_name, shape), base_fit=base_fit,
                                 profile=profile, build=False)
    if on_shape.get("fit") is not None or on_shape.get("pending"):
        return True, ""
    return False, str(on_shape.get("error") or "") or "not fitted on this body"


def interim_hair_fit(character_name: str, *, bsig: str, base_sha: str,
                     profile: Optional[Dict[str, Any]] = None) -> Optional[Tuple[Any, Dict[str, Any]]]:
    """The HairDeck / HAAR fit served while the hair is wanted IN the body but the
    plain body ``bsig`` was rendered bald (``base_body.stored_base_haired``
    False — the hair mode was switched, only a rebuild puts the hair in;
    ruling F13 a): ``(fit GLB, record)`` of the newest accepted HairDeck or
    HAAR fit of the worn own hair item (``garment_hair.worn_hair_id``) on the base
    model ``base_sha``, None otherwise (hair not in the body, a haired or
    unknown plain body, no worn hair item, no such fit). Read-only — the
    delivered figure's rule 3 and the garment assembly ask it."""
    from app.core import base_body, garment_hair, garment_store
    profile = _profile_of(character_name, profile)
    if not base_sha or not garment_hair.hair_in_body(character_name, profile):
        return None
    if base_body.stored_base_haired(character_name, bsig) is not False:
        return None
    item_id = garment_hair.worn_hair_id(character_name, profile)
    if not item_id:
        return None
    # The hairstyle is in the body NOW, so its method names neither graft: the newer of its HairDeck and HAAR
    # fits (strand-hair Task 13; the GLB mtime decides like ``newest_accepted_fits``, HairDeck on a tie).
    fits = garment_store.newest_accepted_fits(character_name, item_id, base_model_sha=base_sha)
    found = [fits[m] for m in (garment_store.HAIRDECK, garment_store.HAAR) if fits.get(m)]

    def mtime(hit: Tuple[Any, Dict[str, Any]]) -> int:
        try:
            return hit[0].stat().st_mtime_ns
        except OSError:
            return 0
    return max(found, key=mtime) if found else None


def _interim_hair_on(character_name: str, *, shape: str, bsig: str, base_sha: str,
                     profile: Dict[str, Any]) -> bool:
    """Whether ``interim_hair_fit`` has a fit that the delivered ``shape`` carries (rule 2's test of a
    garment on a meshed shape: an accepted or still-to-be-made CPU body fit counts)."""
    fit = interim_hair_fit(character_name, bsig=bsig, base_sha=base_sha, profile=profile)
    if fit is None:
        return False
    if is_plain(shape):
        return True
    from app.core import garments, garment_hair
    on_shape = garments.body_fit(character_name, garment_hair.worn_hair_id(character_name, profile), body_id=shape,
                                 body_sha=garments.body_sha256(character_name, shape), base_fit=fit,
                                 profile=profile, build=False)
    return on_shape.get("fit") is not None or bool(on_shape.get("pending"))


def _mesh_delivered(character_name: str, item_id: str, kind: str, *, open_: bool, base_sha: str,
                    profile: Optional[Dict[str, Any]] = None) -> Tuple[bool, bool]:
    """``(delivered, closed_stand_in)`` of an own-mesh piece's mesh on the base
    model ``base_sha`` (Ruling A119: not delivered → left off): an accepted fit in the
    worn state; a clothing piece worn OPEN without its open fit counts with
    its CLOSED fit, ``closed_stand_in`` True (ruling F13 b). Read-only."""
    from app.core import garment_set, garment_store
    from app.core.outfit_options import CLOSED, OPEN
    if not base_sha:
        return False, False

    def fitted(state: str) -> bool:
        return garment_store.accepted_fit(character_name, item_id, base_model_sha=base_sha, profile=profile,
                                          state=state) is not None

    if fitted(OPEN if open_ else CLOSED):
        return True, False
    if open_ and kind != garment_set.FOOTWEAR and fitted(CLOSED):
        return True, True
    return False, False


def figure_served(character_name: str, signature: str = "") -> bool:
    """Whether the character has a figure to show (Ruling A15 b): an outfit model is served for the worn
    outfit (``model3d.find_model3d_serving``: the current model of exactly this figure, Ruling A119).
    ``signature`` (``base_body.prepare_outfit_figure``, an outfit rebuild or batch): a stored model of THAT
    outfit counts (stale ones too); another outfit than the worn one has nothing else to show."""
    from app.core import model3d
    try:
        if signature:
            if model3d.find_model3d(character_name, signature, include_stale=True) is not None:
                return True
            from app.core.model_refs import current_outfit_state
            if signature != current_outfit_state(character_name)[2]:
                return False
        return model3d.find_model3d_serving(character_name)[0] is not None
    except Exception:  # noqa: BLE001 — nothing to show, never a failure of the plan
        logger.debug("Served model of %s unreadable", character_name, exc_info=True)
        return False


def _delivered(character_name: str, *, profile: Dict[str, Any], pieces: Optional[Dict[str, str]] = None,
               items: Optional[list] = None,
               piece_state: Optional[Dict[str, str]] = None) -> Tuple[Figure, Figure]:
    """``(wanted, delivered)`` (block above, Ruling A119). The open pieces are
    a text input, so the delivered figure has the wanted ``open``."""
    from dataclasses import replace
    from app.core import base_body
    from app.core.outfit_options import CLOSED
    items = _items_of(profile, items)
    wanted, sets, variant = _wanted(character_name, profile=profile, pieces=pieces, items=items,
                                    piece_state=piece_state)
    bsig = wanted.bsig
    base_sha = base_body.base_model_sha256(character_name, bsig)
    left_out: Dict[str, str] = {}
    # 1. The body: the wanted shape when it is built, else the plain body — its in-body pieces are left off.
    if is_plain(wanted.shape) or _shape_stored(character_name, wanted.shape, bsig):
        shape, in_body, shape_variant = wanted.shape, tuple(wanted.in_body), variant
        notes = dict(wanted.notes) if not is_plain(wanted.shape) else {}
        refusal = bool(notes)
    else:
        shape, in_body, notes, refusal = bsig, (), {}, False
        shape_variant = predicted_variant(character_name, replace(sets, in_body=()), items, profile=profile)
        left_out.update({item_id: LEFT_OFF_SHAPE for item_id in wanted.in_body})
    meshed = not is_plain(shape)
    # 2. Own-mesh pieces: worn when their fit on that body exists (a clothing piece worn open whose open mesh is
    # missing stands in closed, F13 b), else left off with the reason.
    fit_refused: Dict[str, str] = {}
    own: List[str] = []
    closed: set = set()
    for item_id, kind in sorted(sets.own.items()):
        has, stand_in = _mesh_delivered(character_name, item_id, kind, open_=item_id in sets.open,
                                        base_sha=base_sha, profile=profile)
        if not has:
            left_out[item_id] = _not_fitted_reason(character_name, item_id, base_sha=base_sha, profile=profile,
                                                   state=_state_in(sets, item_id))
            continue
        if meshed:
            state = CLOSED if stand_in else _state_in(sets, item_id)
            fitted, reason = _fit_on(character_name, item_id, shape=shape, base_sha=base_sha, profile=profile,
                                     state=state)
            if not fitted:
                fit_refused[item_id] = reason
                left_out[item_id] = FIT_REFUSED.format(reason=_strip_refused(reason))
                continue
        own.append(item_id)
        if stand_in:
            closed.add(item_id)
    shown_closed = tuple(sorted(closed))
    notes.update({item_id: SHOWN_CLOSED for item_id in shown_closed})
    # 3. Hair.
    hair = wanted.hair
    hair_style = wanted.hair_style
    plain_haired = not meshed and bool(base_body.stored_base_haired(character_name, bsig))
    if hair == HAIR_HAIRDECK and plain_haired:
        # D4: HairDeck hair is never put on a haired plain body — its bald shape is not built yet, so the
        # plain body is shown with its own hair meanwhile.
        hair, hair_style = HAIR_BODY, ""
    elif hair == HAIR_HAIRDECK and not _fit_on(character_name, sets.hair_item, shape=shape, base_sha=base_sha,
                                               profile=profile)[0]:
        hair, hair_style = HAIR_BALD, ""
    elif hair == HAIR_BODY and base_body.stored_base_haired(character_name, bsig) is False:
        # Ruling F13 a: the worn HairDeck hair stays until the plain body is rebuilt with the hair.
        hair = HAIR_HAIRDECK if _interim_hair_on(character_name, shape=shape, bsig=bsig, base_sha=base_sha,
                                                 profile=profile) else HAIR_BALD
    elif hair == HAIR_BODY and sets.hair_shape and not meshed:
        # D4: another body hairstyle lives in its body shape; until that is built the plain body's hair shows.
        hair_style = ""
    # 4. The texture of the painted pieces on that body — its exact painted set; every piece not worn (left off)
    # and every grafted one stays out of its dress text.
    if meshed and refusal:
        texture = ""
    else:
        unpainted = set(own) | set(left_out)
        texture_sets = replace(sets, in_body=in_body, painted=tuple(wanted.painted),
                               own={item_id: sets.own.get(item_id, "") for item_id in unpainted})
        texture = texture_key(character_name, texture_sets, shape=shape, bsig=bsig, variant=shape_variant,
                              items=items, profile=profile)
    delivered = Figure(signature=wanted.signature, bsig=bsig, shape=shape, texture=texture,
                       in_body=tuple(sorted(in_body)), painted=tuple(sorted(wanted.painted)), own=tuple(own),
                       left_out=left_out, notes=notes, hair=hair, pieces=dict(sets.pieces), open=sets.open,
                       shown_closed=shown_closed, hair_style=hair_style, fit_refused=fit_refused,
                       fit_refused_on=shape if fit_refused else "")
    return wanted, delivered


def delivered_figure(character_name: str, *, profile: Optional[Dict[str, Any]] = None,
                     pieces: Optional[Dict[str, str]] = None, items: Optional[list] = None,
                     piece_state: Optional[Dict[str, str]] = None) -> Figure:
    """The figure that would be delivered NOW for the worn pieces (default:
    the profile's; ``pieces`` / ``items`` / ``piece_state`` judge another
    outfit, e.g. a stored model's manifest) — Ruling A119 applied (block
    above: the newest body, only ready pieces worn). Read-only: no chain, no fit, no image runs here."""
    return _delivered(character_name, profile=_profile_of(character_name, profile), pieces=pieces, items=items,
                      piece_state=piece_state)[1]


# --- Memo for serving paths (Ruling 6b) ------------------------------------------
#
# ``delivered_figure`` reads fits, stored shapes and their views; the serving
# paths (stale checks, model info, the Wardrobe, tile freshness) ask it per
# request. ``delivered_figure_cached`` memoises it per (character, profile
# content — the base signature, the worn pieces and the hair method follow
# from it —, the judged pieces and items, the content of the worn items —
# their modes and texts —, the disk generation). The disk generation
# (``invalidate``) moves with every write that can change a figure: a garment
# record (``garment_store.write_record``: fits, refusals), a model or
# sidecar publication (``model3d._publish_model_bytes``: shapes, the base),
# a base-body ref write and a render pass (``base_body._atomic_write`` /
# ``_render_views``). Deletions are not counted: an entry lives at most
# ``MEMO_TTL_S``. Producers (builds, triggers, the GC) call
# ``delivered_figure`` itself, never the memo.

#: The longest a memoised figure is served.
MEMO_TTL_S = 30.0
_MEMO_MAX = 512
_memo: Dict[Tuple[Any, ...], Tuple[float, "Figure"]] = {}
_memo_lock = threading.Lock()
_generation = [0]


def invalidate() -> None:
    """A write that can change a delivered figure happened (block above)."""
    with _memo_lock:
        _generation[0] += 1
        _memo.clear()


def delivered_figure_cached(character_name: str, *, profile: Optional[Dict[str, Any]] = None,
                            pieces: Optional[Dict[str, str]] = None, items: Optional[list] = None,
                            piece_state: Optional[Dict[str, str]] = None) -> "Figure":
    """``delivered_figure`` memoised for serving paths (block above)."""
    from app.models.inventory import get_item
    profile = _profile_of(character_name, profile)
    worn = pieces if pieces is not None else (profile.get("equipped_pieces") or {})
    ids = sorted({str(v) for v in (worn or {}).values() if v})
    # The hairstyles' modes and texts decide the hair and the shape (plan Task 13).
    from app.core.garment_hair import BASE_HAIRSTYLE_KEY
    mesh = profile.get("equipped_mesh_pieces")
    ids = sorted({*ids, *(str(v) for v in (mesh.values() if isinstance(mesh, dict) else ()) if v),
                  *([str(profile[BASE_HAIRSTYLE_KEY])] if profile.get(BASE_HAIRSTYLE_KEY) else [])})
    key = (character_name, _generation[0], hashlib.sha1(_canonical(profile)).hexdigest(),
           _canonical({"pieces": pieces, "items": items, "piece_state": piece_state}),
           hashlib.sha1(_canonical({i: get_item(i) for i in ids})).hexdigest())
    now = time.monotonic()
    with _memo_lock:
        hit = _memo.get(key)
        if hit is not None and now - hit[0] < MEMO_TTL_S:
            return hit[1]
    fig = delivered_figure(character_name, profile=profile, pieces=pieces, items=items, piece_state=piece_state)
    with _memo_lock:
        if key[1] == _generation[0]:
            if len(_memo) >= _MEMO_MAX:
                _memo.clear()
            _memo[key] = (now, fig)
    return fig


def pending_changes(character_name: str, *, profile: Optional[Dict[str, Any]] = None) -> List[Dict[str, str]]:
    """The "N changes" of the Figure tab's header, derived (never stored):
    ``[{key, name, wanted, delivered}]`` — one per worn piece whose delivered
    state differs from what its mode calls for (a piece left off until it is
    ready, Ruling A119, with ``note`` = its ``left_out`` reason; a piece
    meshed in by the refusal branch is delivered as wanted), then ``body`` when the plain body is missing or was
    rendered with older prompts (``base_body.OLDER_PROMPTS``) or its front
    from another reference (``base_body.front_reference_state``, Ruling A74b;
    its ``note`` = ``BASE_MISSING`` / ``BASE_OUTDATED``, ruling 8a; the front's entry also carries ``front``, the
    method the front is made from now — ``reference`` / ``text``, Ruling A86), then ``hair`` (named
    after the worn hairstyle) when the hair is not delivered as its mode says
    or another hairstyle than the worn one is shown. Read-only.

    Open / closed (plan Task 11a): ``{key: "<item_id>:state", name, wanted,
    delivered}`` (``"open"`` / ``"closed"``) for a worn closable piece whose
    state differs between the wanted figure and the figure the served model
    was built as (``served_figure``; a piece it shows closed for open,
    ``shown_closed``, counts as closed) — after the piece-list changes. A
    piece worn open whose open mesh is missing has ONE change (ruling F13 b):
    this state entry with ``note`` ``OPEN_MESH_MISSING`` — its piece entry
    (in the body meanwhile) is folded into it.

    The hair wanted in the body on a plain body rendered bald (ruling F13 a):
    ONE change, ``{key: "hair", …, note: HAIR_REBUILD}`` — it replaces the
    plain body's "older prompts" entry, whose rebuild it is (the hair mode
    changed the base prompt)."""
    profile = _profile_of(character_name, profile)
    wanted, delivered = _delivered(character_name, profile=profile)
    return _pending(character_name, wanted, delivered, profile)


def _open_mesh_missing(wanted: "Figure", delivered: "Figure") -> Dict[str, str]:
    """``{item: "closed" | "left_out"}`` of the worn-open own-mesh pieces whose open mesh is missing: shown
    closed meanwhile (``shown_closed``), or left off (no mesh of either state, Ruling A119)."""
    from app.core.outfit_options import CLOSED
    out: Dict[str, str] = {}
    for item_id in wanted.open:
        if item_id in wanted.own and item_id in delivered.shown_closed:
            out[item_id] = CLOSED
        elif item_id in wanted.own and item_id in delivered.left_out:
            out[item_id] = LEFT_OUT
    return out


def hair_needs_rebuild(character_name: str, wanted: "Figure", *, profile: Optional[Dict[str, Any]] = None) -> bool:
    """Whether the plain body's own hairstyle (``wanted.hair_style`` "") is wanted in the body while the
    stored plain body was rendered bald and its prompts are no longer current (the hair text is in them now)
    — the plain body's rebuild is what the hair change costs (ruling F13 a). A character without hair text
    keeps its bald plain body: no rebuild. Another body hairstyle is made as a body shape instead (D4)."""
    from app.core import base_body
    return (wanted.hair == HAIR_BODY and not wanted.hair_style
            and base_body.stored_base_haired(character_name, wanted.bsig) is False
            and not base_body.prompts_current(character_name, wanted.bsig,
                                              profile=_profile_of(character_name, profile)))


def _pending(character_name: str, wanted: "Figure", delivered: "Figure",
             profile: Dict[str, Any]) -> List[Dict[str, str]]:
    """``pending_changes`` of an already resolved ``(wanted, delivered)``."""
    from app.core import base_body
    from app.models.inventory import get_item
    out: List[Dict[str, str]] = []
    open_missing = _open_mesh_missing(wanted, delivered)
    for item_id in sorted({*wanted.in_body, *wanted.painted, *wanted.own}):
        if item_id in open_missing:
            continue  # its one change is the state entry below
        want, have = wanted.state_of(item_id), delivered.state_of(item_id)
        if want != have:
            change = {"key": item_id, "name": str((get_item(item_id) or {}).get("name") or item_id),
                      "wanted": want, "delivered": have}
            if item_id in delivered.left_out:   # Ruling A119: why the piece is left off
                change["note"] = delivered.left_out[item_id]
            out.append(change)
    out.extend(_state_changes(character_name, wanted, open_missing))
    from app.core.model_refs import find_ref_image
    hair_rebuild = hair_needs_rebuild(character_name, wanted, profile=profile)
    if (find_ref_image(character_name, "tpose", wanted.bsig) is None
            or not base_body.base_model_sha256(character_name, wanted.bsig)):
        out.append({"key": BODY_KEY, "name": "Plain body", "wanted": "built", "delivered": "missing",
                    "note": BASE_MISSING})
    elif not hair_rebuild and not base_body.prompts_current(character_name, wanted.bsig, profile=profile):
        out.append({"key": BODY_KEY, "name": "Plain body", "wanted": "built",
                    "delivered": base_body.OLDER_PROMPTS, "note": BASE_OUTDATED})
    elif not hair_rebuild and not (front_ref := base_body.front_reference_state(
            character_name, wanted.bsig, profile=profile))["current"]:
        # Ruling A74b: the front was made from another reference — only a Build you start refreshes it (8a).
        # Ruling A86: ``front`` = what the front is made from now — the Figure tab offers the front's Regenerate
        # ("reference" the profile image, "full_body" the full-body reference — Ruling A87 —, "text").
        out.append({"key": BODY_KEY, "name": "Plain body", "wanted": "built",
                    "delivered": front_ref["reason"], "note": BASE_OUTDATED,
                    "front": (base_body.SOURCE_FULL_BODY
                              if front_ref["wanted"].get("source") == base_body.SOURCE_FULL_BODY
                              else front_ref["wanted"]["method"])})
    from app.core.garment_hair import worn_hairstyle
    hairstyle = worn_hairstyle(character_name, profile)
    hair_name = str((hairstyle or {}).get("name") or "Hair")
    if hair_rebuild:
        out.append({"key": HAIR_KEY, "name": hair_name, "wanted": wanted.hair, "delivered": delivered.hair,
                    "note": HAIR_REBUILD})
    elif wanted.hair != delivered.hair or wanted.hair_style != delivered.hair_style:
        out.append({"key": HAIR_KEY, "name": hair_name, "wanted": wanted.hair, "delivered": delivered.hair})
    return out


#: The suffix of a piece's open / closed entry in ``pending_changes``.
STATE_KEY_SUFFIX = ":state"


def served_figure(character_name: str) -> Optional[Figure]:
    """The figure the model served for the worn outfit was built as
    (``model3d.find_model3d_serving`` — the current model or the plain body, Ruling A119 — and
    its sidecar ``figure``); None without a model or a record."""
    from app.core import model3d
    try:
        path, _match = model3d.find_model3d_serving(character_name)
    except Exception:  # noqa: BLE001 — a pending change, never a failure
        return None
    return built_figure(model3d._read_sidecar(path)) if path is not None else None


def _state_changes(character_name: str, wanted: Figure,
                   open_missing: Optional[Dict[str, str]] = None) -> List[Dict[str, str]]:
    """The open / closed entries of ``pending_changes``: worn closable pieces
    of ``wanted`` whose state the served model's figure does not show (a
    piece that model does not wear is not a state change; one it shows
    closed for open, ``shown_closed``, is closed there). ``open_missing``
    (``_open_mesh_missing``): pieces worn open whose open mesh is missing —
    always an entry, ``delivered`` how it is shown meanwhile ("closed" /
    "in_body"), with ``note`` ``OPEN_MESH_MISSING`` (ruling F13 b)."""
    from app.core import garment_set
    from app.core.outfit_options import CLOSED, OPEN
    from app.models.inventory import get_item
    closable = sorted(i for i in {str(v) for v in wanted.pieces.values() if v}
                      if garment_set.closable_of(get_item(i)))
    if not closable:
        return []
    open_missing = open_missing or {}
    built = served_figure(character_name) if any(i not in open_missing for i in closable) else None
    worn_there = {str(v) for v in built.pieces.values() if v} if built is not None else set()
    out: List[Dict[str, str]] = []
    for item_id in closable:
        name = str((get_item(item_id) or {}).get("name") or item_id)
        if item_id in open_missing:
            out.append({"key": item_id + STATE_KEY_SUFFIX, "name": name, "wanted": OPEN,
                        "delivered": open_missing[item_id], "note": OPEN_MESH_MISSING})
            continue
        if built is None:
            continue
        want = OPEN if item_id in wanted.open else CLOSED
        have = OPEN if item_id in built.open and item_id not in built.shown_closed else CLOSED
        if item_id in worn_there and want != have:
            out.append({"key": item_id + STATE_KEY_SUFFIX, "name": name, "wanted": want, "delivered": have})
    return out


def stored_unneeded(character_name: str) -> List[Dict[str, Any]]:
    """What is stored but not needed now (Ruling 5a; the Figure tab lists
    it, only an explicit Delete removes it): every outfit body the artefact
    GC calls ``STORED_NOT_NEEDED`` (of the current base, built for a live
    outfit, no live outfit predicts or names it — old-id bodies the boot
    re-key left stale included) and every painted body it calls
    ``OUTDATED_TEXTURE``. Per entry ``{key, kind ("shape" | "texture"),
    bytes (with the fits on a body), built_for, outfits, last_used}``:
    ``built_for`` = the record's outfit (a texture: the first live outfit
    built on it), ``last_used`` = the record's ``last_used`` if recorded,
    else the newest file mtime (UTC ISO). Read-only, newest first."""
    from datetime import datetime, timezone
    from app.core import artefact_graph
    analysis = artefact_graph.analyse(character_name, explicit=True, automatic=True)
    groups: Dict[Tuple[str, str], List[Any]] = {}   # (kind, key) -> the nodes freed with it
    for node in analysis.nodes:
        if node.kind == "body" and node.reason == artefact_graph.STORED_NOT_NEEDED:
            groups.setdefault(("shape", node.key), []).insert(0, node)
        elif node.kind == "texture" and node.reason == artefact_graph.OUTDATED_TEXTURE:
            groups.setdefault(("texture", str(node.parents.get("texture_signature") or node.key)), []).append(node)
        elif node.kind == "body_fit" and node.protected == artefact_graph.STORED:
            groups.setdefault(("shape", str(node.parents.get("body_id") or "")), []).append(node)
    root = artefact_graph._char_dir(character_name)
    out: List[Dict[str, Any]] = []
    for (kind, key), group in groups.items():
        head = group[0]
        if kind == "shape" and head.kind != "body":
            continue  # fits of a body that is not listed
        if kind == "shape":
            record = artefact_graph._body_record(root, key)
            outfits = [str(head.parents.get("built_for") or "")]
        else:
            record, outfits = {}, list(head.parents.get("built_on") or [])
        mtime = max(n.newest_mtime() for n in group)
        last = record.get("last_used") if isinstance(record.get("last_used"), str) else ""
        out.append({"key": key, "kind": kind, "bytes": sum(n.size() for n in group),
                    "built_for": outfits[0] if outfits else "", "outfits": outfits,
                    "last_used": last or datetime.fromtimestamp(mtime, timezone.utc).isoformat(timespec="seconds"),
                    "_mtime": mtime})
    out.sort(key=lambda e: e["_mtime"], reverse=True)
    return [{k: v for k, v in e.items() if k != "_mtime"} for e in out]


#: ``delete_stored`` (409): the body is the shape a live outfit would be built on now.
SHAPE_NEEDED = "Not deleted: an outfit would be built on this body now — see why it is kept."
#: ``delete_stored`` (409): a run works on it.
STORED_RUNNING = "Not deleted: a run works on it now — delete it after the run."
#: ``delete_stored`` (409): a Build of the character runs (it holds ``figure_build.build_lock``).
BUILD_RUNNING = "Not deleted: a Build runs now — delete it after the Build."
#: ``delete_stored`` (409): the worn figure stands on this body shape now (Ruling A64).
SHAPE_CURRENT = "Not deleted: the figure stands on this body shape now — it is deleted only once nothing is worn on it."
#: ``stored`` reasons that mean "stored, not needed now" (Ruling 5a: only an explicit Delete removes them).
_UNNEEDED_REASONS = ("stored, not needed now", "outdated: a live outfit was built on it, none would paint it now")
#: The artefact graph's body verdicts that mean an outfit would be built on the shape NOW (or that cannot be
#: told): such a shape is never deleted. Any other verdict of a shape that is neither worn nor in a run — "named by a
#: live outfit model" included, a shape kept only because an outfit MODEL was once built on it (its history) — is
#: deletable (Ruling A64); its outfit models go with it and are built anew when that outfit is worn again.
_SHAPE_NEEDED_REASONS = ("shape of a live outfit", "shape of its outfit not computable", "base unknown")


def stored(character_name: str) -> List[Dict[str, Any]]:
    """Every stored body shape (``ob…``) and painted body (texture key) of
    the character — the Figure tab's "Stored bodies and textures" (plan
    2026-11-12-unified-worn-pieces Task 10). Per entry ``{key, kind ("shape"
    | "texture"), bytes (a body: with its fits), built_for (an outfit
    signature, "" when none), built_for_name, outfits, last_used, reason
    (the artefact graph's verdict), unneeded (Ruling 5a: stored, not needed
    now), deletable (``delete_stored`` would remove it), refusal (why not:
    "running" a run works on it · "current" the worn figure stands on it ·
    "needed" an outfit would be built on it now · "" deletable), history (a
    shape kept only because an outfit model was built on it — deletable,
    Ruling A64), running (a run works on it), current (the worn figure's
    shape or texture, wanted or delivered)}``. A shape is deletable unless
    it runs, is current or its verdict is one of ``_SHAPE_NEEDED_REASONS``;
    when the worn figure cannot be resolved, only an unreachable shape is. A
    painted body is deletable when no root reaches it and no run works on
    it. The current ones first, then newest first. Read-only; the plain body
    (a base) is not listed."""
    from datetime import datetime, timezone
    from app.core import artefact_graph, outfit_bodies
    analysis = artefact_graph.analyse(character_name, explicit=True, automatic=True)
    heads: Dict[Tuple[str, str], Any] = {}
    groups: Dict[Tuple[str, str], List[Any]] = {}
    for node in analysis.nodes:
        if node.kind == "body":
            heads.setdefault(("shape", node.key), node)
            groups.setdefault(("shape", node.key), []).append(node)
        elif node.kind == "texture":
            key = ("texture", str(node.parents.get("texture_signature") or node.key))
            heads.setdefault(key, node)
            groups.setdefault(key, []).append(node)
    for node in analysis.nodes:
        if node.kind == "body_fit" and ("shape", str(node.parents.get("body_id") or "")) in groups:
            groups[("shape", str(node.parents["body_id"]))].append(node)
    current: set = set()
    current_known = False
    try:
        wanted, delivered = _delivered(character_name, profile=_profile_of(character_name, None))
        current = {k for k in (wanted.shape, wanted.texture, delivered.shape, delivered.texture) if k}
        current_known = True
    except Exception:  # noqa: BLE001 — a marker, never a failure (then only the graph's verdict decides)
        pass
    root = artefact_graph._char_dir(character_name)
    saved = outfit_bodies._saved_outfits(character_name)
    out: List[Dict[str, Any]] = []
    for (kind, key), head in heads.items():
        group = groups[(kind, key)]
        if kind == "shape":
            record = artefact_graph._body_record(root, key)
            outfits = [str(head.parents.get("built_for") or "")] if head.parents.get("built_for") else []
        else:
            record = {}
            outfits = list(head.parents.get("outfits") or head.parents.get("built_on") or [])
        mtime = max(n.newest_mtime() for n in group)
        last = record.get("last_used") if isinstance(record.get("last_used"), str) else ""
        reachable = any(n.reachable for n in group if n.kind == head.kind)
        running = any(n.protected == "running" for n in group)
        is_current = key in current
        history = (kind == "shape" and reachable and current_known and not is_current
                   and head.reason not in _SHAPE_NEEDED_REASONS)
        if running:
            refusal = "running"
        elif is_current:
            refusal = "current"
        elif reachable and not history:
            refusal = "needed"
        else:
            refusal = ""
        built_for = outfits[0] if outfits else ""
        out.append({"key": key, "kind": kind, "bytes": sum(n.size() for n in group),
                    "built_for": built_for,
                    "built_for_name": outfit_bodies.outfit_label(character_name, built_for, saved=saved)
                    if built_for else "",
                    "outfits": outfits,
                    "last_used": last or (datetime.fromtimestamp(mtime, timezone.utc).isoformat(timespec="seconds")
                                          if mtime else ""),
                    "reason": head.reason, "unneeded": head.reason in _UNNEEDED_REASONS,
                    "deletable": not refusal, "refusal": refusal, "history": history,
                    "running": running, "current": is_current,
                    "_mtime": mtime})
    out.sort(key=lambda e: e["_mtime"], reverse=True)
    out.sort(key=lambda e: not e["current"])
    return [{k: v for k, v in e.items() if k != "_mtime"} for e in out]


def delete_stored(character_name: str, key: str) -> Dict[str, Any]:
    """The Figure tab's Delete of ONE stored body shape or painted body — an
    explicit collect (Ruling 5a). A texture key: ``outfit_bodies.delete_texture``
    (``LookupError`` ``PAINTED_NEEDED`` while a live outfit would be built on it,
    ``UnknownBody`` when nothing of it is stored). A shape (``ob…``): only while
    ``stored`` calls it deletable — ``LookupError`` ``SHAPE_NEEDED`` while an
    outfit would be built on it, ``SHAPE_CURRENT`` while the worn figure
    stands on it, ``STORED_RUNNING`` while a run works on it; a shape kept
    only by an outfit model built on it (``history``) goes, that model with it;
    then ``outfit_bodies.delete`` (the body and its fits, ``artefact_graph.delete_body``).
    Both are judged and deleted under the character's Build lock
    (``figure_build.build_lock``, Ruling 10a), taken without waiting:
    ``LookupError`` ``BUILD_RUNNING`` while a Build holds it — so no Build
    plans on the body between the check and the delete.
    ``ValueError`` for a key of neither shape. Returns the delete report."""
    from app.core import base_body, figure_build, outfit_bodies
    texture = base_body.is_texture_signature(key)
    if not texture and not base_body.is_outfit_body_signature(key):
        raise ValueError(f"not a stored body or texture key: {str(key)[:40]!r}")
    lock = figure_build.build_lock(character_name)
    if not lock.acquire(blocking=False):
        raise LookupError(BUILD_RUNNING)
    try:
        if texture:
            report = outfit_bodies.delete_texture(character_name, key)
        else:
            entry = next((e for e in stored(character_name) if e["kind"] == "shape" and e["key"] == key), None)
            if entry is None:
                raise outfit_bodies.UnknownBody(f"No stored body {key}")
            if not entry["deletable"]:
                raise LookupError({"running": STORED_RUNNING, "current": SHAPE_CURRENT}.get(entry["refusal"],
                                                                                          SHAPE_NEEDED))
            report = outfit_bodies.delete(character_name, key)
    finally:
        lock.release()
    invalidate()
    return report


def delete_preview(character_name: str, key: str) -> Dict[str, Any]:
    """What the Delete of ONE stored body shape or painted body would do — the in-app confirmation's content
    (Ruling A64), read-only: ``{key, kind, built_for_name, deletable, refusal, reason, history, files (paths
    relative to the character folder, every one inside it), bytes, outfit_models (names of the outfit models
    deleted with a shape), running (keys a run protects — skipped)}``. Nothing becomes due by the delete itself:
    a deletable entry is one no outfit would be built on now; an outfit that needs it later meshes or paints it
    anew. ``UnknownBody`` when nothing of it is stored, ``ValueError`` for a key of neither shape (a path, ``..``)."""
    from app.core import artefact_graph, base_body, outfit_bodies
    texture = base_body.is_texture_signature(key)
    if not texture and not base_body.is_outfit_body_signature(key):
        raise ValueError(f"not a stored body or texture key: {str(key)[:40]!r}")
    kind = "texture" if texture else "shape"
    entry = next((e for e in stored(character_name) if e["kind"] == kind and e["key"] == key), None)
    if entry is None:
        raise outfit_bodies.UnknownBody(f"No stored body {key}")
    files = (artefact_graph.texture_files(character_name, key) if texture
             else artefact_graph.delete_body_preview(character_name, key))
    saved = outfit_bodies._saved_outfits(character_name)
    names = [outfit_bodies.outfit_label(character_name, sig, saved=saved) or sig for sig in files["outfit_models"]]
    return {"key": key, "kind": kind, "built_for_name": entry["built_for_name"], "deletable": entry["deletable"],
            "refusal": entry["refusal"], "reason": entry["reason"], "history": entry["history"],
            "files": files["files"], "bytes": files["bytes"], "outfit_models": names, "running": files["running"]}
