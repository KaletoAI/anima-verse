"""One figure, one mode per worn piece — the pure resolver (plan
``docs/superpowers/plans/2026-11-12-unified-worn-pieces.md`` Task 4; spec
``docs/superpowers/specs/2026-11-12-unified-worn-pieces-design.md``,
builder-check ruling 1).

Every worn outfit piece has the item mode ``garment_set.mesh_mode_of``:
``in_body`` (meshed as part of the body), ``painted`` (on the body's
texture) or ``own_mesh`` (its own garment mesh, fitted on top). A figure is
built from two keys:

- the SHAPE key (``shape_key``): the body mesh, keyed by the in-body set —
  and in-body hair is part of that set (hair method ``body``). With nothing
  in the body the shape IS the base (``bsig``): today's base, haired iff
  the hair is in the body, so no base is rebuilt. Otherwise ``"ob"`` + 8
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
"""
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

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
    hair_in_body: bool            # garment_hair.hair_in_body
    hair_item: str                # worn HairDeck item id, "" otherwise
    #: The worn ``{slot: item id}`` the sets were resolved from — the dress
    #: texts of ``shape_inputs`` / ``texture_key`` are composed from it.
    pieces: Dict[str, str] = field(default_factory=dict)


def _profile_of(character_name: str, profile: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if profile is not None:
        return profile
    from app.models.character import get_character_profile
    return get_character_profile(character_name) or {}


def _canonical(data: Dict[str, Any]) -> bytes:
    return json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def worn_sets(character_name: str, *, pieces: Optional[Dict[str, str]] = None,
              profile: Optional[Dict[str, Any]] = None) -> WornSets:
    """The worn pieces of ``pieces`` (``{slot: item id}``, default: the
    profile's ``equipped_pieces``) by mode. A multi-slot piece counts once.
    Own-mesh pieces are the worn garments (``garment_set.worn_garments``,
    empty off the pipeline) among ``pieces``; in-body pieces need the
    pipeline as well; everything else — mode painted, or no outfit piece at
    all — is painted. ``hair_item``: the worn own hair item when the hair is
    NOT in the body (a leftover hair item is never served with in-body
    hair), else ``""``."""
    from app.core import base_body, garment_hair, garment_set
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
    hair_in = garment_hair.hair_in_body(character_name, profile)
    return WornSets(in_body=tuple(in_body), painted=tuple(painted), own=dict(sorted(own.items())),
                    hair_in_body=hair_in,
                    hair_item="" if hair_in else garment_hair.worn_hair_id(character_name, profile),
                    pieces=dict(worn))


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
    ``base_body._outfit_texture`` builds its ``mesh_profile``)."""
    dressed = dict(profile)
    dressed["equipped_pieces"] = dict(sets.pieces)
    dressed["equipped_items"] = list(items or [])
    return dressed


def shape_inputs(character_name: str, sets: WornSets, *, bsig: str, variant: str,
                 profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """What a meshed shape is made of: the base signature and variant, the
    hair-in-body switch, the side-view switch and the dress text of every
    dressed view with the painted and own-mesh pieces left out (the in-body
    pieces only; held items never enter the body)."""
    from app.core import base_body
    profile = _dressed_profile(_profile_of(character_name, profile), sets, [])
    return {"version": SHAPE_VERSION,
            "base_signature": bsig,
            "base_variant": variant,
            "hair_in_body": sets.hair_in_body,
            "side_views": base_body.side_views_dressed(),
            "dress_text": _dress_texts(character_name, sets, left_out=(*sets.painted, *sets.own), items=[],
                                       profile=profile)}


def shape_key_of(inputs: Dict[str, Any]) -> str:
    """``"ob"`` + the first 8 hex of sha256 over the canonical JSON of the
    shape inputs ``inputs``."""
    return "ob" + hashlib.sha256(_canonical(inputs)).hexdigest()[:8]


def shape_key(character_name: str, sets: WornSets, *, bsig: str, variant: str,
              profile: Optional[Dict[str, Any]] = None) -> str:
    """``bsig`` for the plain body (nothing in the body), else ``"ob"`` + the
    first 8 hex of sha256 over the canonical JSON of ``shape_inputs``."""
    if not sets.in_body:
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
    when nothing is painted there (every dress text empty)."""
    from app.core import base_body
    profile = _dressed_profile(_profile_of(character_name, profile), sets, items)
    if is_plain(shape):
        return base_body.texture_signature(base_body.texture_inputs(
            character_name, pieces=dict(sets.pieces), items=list(items or []), variant=variant,
            mesh_effective=sorted(sets.own), bsig=bsig, profile=profile))
    texts = _dress_texts(character_name, sets, left_out=(*sets.own, *sets.in_body), items=items, profile=profile)
    if not any(texts.values()):
        return ""
    inputs = {"version": SHAPE_TEXTURE_VERSION, "shape": shape, "base_variant": variant, "dress_text": texts}
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


def _painted_now(character_name: str, sets: WornSets, *, bsig: str) -> WornSets:
    """``sets`` as a build paints them NOW (ruling 2, the interim rule): an
    own-mesh CLOTHING piece without an accepted fit on the base model of
    ``bsig`` is painted meanwhile; footwear is never painted (left out until
    its fit exists). Read-only — the same rule as today's build
    (``base_body.resolve_mesh_items``: left out = the fitted pieces plus all
    footwear)."""
    from dataclasses import replace
    from app.core import base_body, garment_set, garment_store
    if not sets.own:
        return sets
    base_sha = base_body.base_model_sha256(character_name, bsig)
    own = {item_id: kind for item_id, kind in sets.own.items()
           if kind == garment_set.FOOTWEAR or (base_sha and garment_store.accepted_fit(
               character_name, item_id, base_model_sha=base_sha) is not None)}
    if own == sets.own:
        return sets
    return replace(sets, own=own, painted=tuple(sorted({*sets.painted, *(set(sets.own) - set(own))})))


def predicted_keys(character_name: str, pieces: Optional[Dict[str, str]], items: Optional[list], *,
                   bsig: str, profile: Optional[Dict[str, Any]] = None) -> Tuple[str, str]:
    """``(shape key, texture key)`` a figure of the outfit ``pieces`` /
    ``items`` stands on NOW — ``worn_sets`` under the items' modes, the
    variant of ``predicted_variant``, ``shape_key``, and ``texture_key`` of
    the pieces as painted now (``_painted_now``: an own-mesh clothing piece
    without its fit is painted meanwhile, so on the plain body this is the
    tsig today's build paints). Read-only (no garment chain, no image): the
    artefact GC asks it for every live outfit. The texture key is ``""`` on
    a meshed shape with nothing painted."""
    profile = _profile_of(character_name, profile)
    sets = worn_sets(character_name, pieces=dict(pieces or {}), profile=profile)
    variant = predicted_variant(character_name, sets, items, profile=profile)
    shape = shape_key(character_name, sets, bsig=bsig, variant=variant, profile=profile)
    return shape, texture_key(character_name, _painted_now(character_name, sets, bsig=bsig), shape=shape,
                              bsig=bsig, variant=variant, items=items, profile=profile)


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
