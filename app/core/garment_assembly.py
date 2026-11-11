"""Garment assembly — the served 3D model = bare outfit model + grafted
garment meshes (plan 2026-11-09-base-body-phase4-hair R11, R12).

The stored ``model3d/<sig>.glb`` stays BARE: every management path
(``find_model3d``, ``find_model3d_serving``, Blender steps, base-colour and
face checks, extension-rig rebuilds, LOD, weight repair) keeps seeing the file
without hair. The delivery is a derived file next to it::

    model3d/assembled/<sig>.glb      + .json   full tier
    model3d/assembled/low/<sig>.glb  + .json   distance tier

built by numpy (``glb_mesh.graft``) from the bare file of that tier plus the
garment node of every wanted fit. Its sidecar is the bare sidecar plus
``garments: {item_id: {kind, fsig, sha256}}`` (``sha256`` = the garment
source used for THAT tier) and ``bare_revision`` (stat records of the bare
file and its sidecar when the build captured them).

Only the byte/URL paths substitute the assembly (``served``), and only when
it is current: same ``bare_revision`` as the bare file on disk now, same
garments as wanted now. Anything else serves the bare file and asks for a
background build (``schedule``) — serving never waits. A build publishes
under ``model3d_publication`` only if the bare file is still the one it read
(generation-key rule), so a republished bare file can never be covered by an
assembly of its predecessor.

Which garment: the hair of the profile's ``equipped_mesh_pieces`` (outfit
independent) plus the own-mesh outfit pieces of THE SIGNATURE — the
pieces its bare sidecar recorded as left out of the texture
(``effective_mesh_items``: ``mesh_items.effective``, in outfit body mode mesh
``mesh_items.unpainted``; plan 2026-11-09-base-body-phase5-mesh-items, Task
4), never the current profile's pieces, so a stand-in or a
model of another outfit carries exactly the garments its texture lacks.
Per garment the fit ``garment_store.accepted_fit`` names on the CURRENT base
model (current fsig, else the newest accepted fit) — and only when the bare
model of the signature was built on that same base model
(``built_on_fit_base``: the bare full sidecar's ``base_model_sha256``, else
its ``base_signature``, equals the fit record's). An outfit model from an
older base (served as stale until rebuilt) has another body under the
garments: it is served bare, and no assembly is built for it. Off the
base-body pipeline, or with nothing wanted, the bare file is served
unchanged.

An outfit model on an OUTFIT BODY (mesh mode, plan
2026-11-10-outfit-body-mesh-mode, Task 2; bare sidecar ``body_id`` +
``body_sha256``) carries per garment its fit ON THAT BODY
(``garments.body_fit``: derived from the fit served on the base model, same
fsig, keyed ``(item, fsig, body id)``) — never a fit of the base model or of
another body (``built_on_fit_base``). ``served`` only reads: a body fit still
to be made is listed ``pending`` (the assembly is not current, a build is
asked for); the build (``assemble``) fits it first — CPU, no hub job. A fit
refused on the body is recorded there and the garment left off (the outfit
model's ``garment_warnings`` say so, ``body_fit_warning``).

Own-mesh pieces of the signature worn over each other (plan
2026-11-10-texture-body-reuse-and-layering, Task 2): an outer piece is
grafted from its LAYERED fit over the inner pieces of the set
(``garment_layers``; its sidecar entry adds ``over: <lsig>``). ``served``
only reads: a layered fit not built yet serves the body fit, the entry says
``pending`` and the build (``assemble``) makes the layered fit first — CPU
work, no hub job. A changed inner fit changes the ``lsig``, so the assembly
is no longer current and the outer piece is layered again.

A FOOTWEAR piece (spec 2026-11-10-footwear-rigid-shoes § 6.1, § 7.1, § 11)
is grafted as its shoe nodes ``garment_footwear_<item>_<side>`` — and a
boot's ``…_<side>_shaft`` nodes (fit version 6), the material as the fit GLB
carries it — read from its fit GLB (``garment_footwear.node_name``), and the bare body of that tier
gets the fit record's ``cut`` applied first (``footwear_cut.apply_cut`` per
body primitive, written back by ``glb_mesh.rewrite_body_primitives``) — the
foot inside the shoe is removed from the served file itself, the bare file
stays whole. On an outfit body the shoe is fitted on that body directly
(``garment_footwear.body_fit``: from the item's source, never from a base
fit). At most ONE footwear piece per outfit (slot ``feet`` is single
occupancy): the piece worn in the feet slot per the bare sidecar's
``pieces``, else the first by item id, is grafted; another is left off with
``FOOTWEAR_SECOND`` in the assembly sidecar's ``garment_warnings`` (the bare
sidecar's warnings first). The assembled sidecar then carries ``foot_pose``:
the record's payload with ``source {item_id, fsig, glb_sha256}`` of THAT
tier's assembled bytes (``served_foot_pose`` reads it for the routes; None
whenever the bare file is served — never a pose without its shoe).
"""
import json
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.core.log import get_logger

logger = get_logger("garment_assembly")

FULL = "full"
LOW = "low"
TIERS = (FULL, LOW)

_lock = threading.Lock()
# One build per (character, signature) at a time; a request while one runs
# makes it run once more afterwards (the wanted state may have moved on).
_building: set = set()
_again: set = set()
# (character, signature) -> the input key of a build that failed: the same
# inputs are not retried on every request (a new bare file, fit or equip is).
_failed: Dict[Tuple[str, str], str] = {}

#: The ``garment_warnings`` entry of a second footwear piece in one outfit (spec § 11: a data error, left off).
FOOTWEAR_SECOND = "{item}: a second shoe piece in one outfit — left off"


# --- Paths and revisions ------------------------------------------------------

def _model3d():
    from app.core import model3d
    return model3d


def bare_path(directory: Path, signature: str, tier: str) -> Path:
    """The bare GLB of ``signature`` at ``tier`` in a model directory."""
    return directory / f"{signature}.glb" if tier == FULL else directory / tier / f"{signature}.glb"


def assembled_path(directory: Path, signature: str, tier: str) -> Path:
    """The assembled GLB of ``signature`` at ``tier`` in a model directory."""
    root = directory / _model3d().ASSEMBLED_DIR
    return root / f"{signature}.glb" if tier == FULL else root / tier / f"{signature}.glb"


def _stat_record(path: Path) -> Optional[List[int]]:
    try:
        st = path.stat()
    except OSError:
        return None
    return [st.st_size, st.st_mtime_ns, st.st_ino]


def bare_revision(path: Path) -> List[Optional[List[int]]]:
    """Stat records (size, mtime_ns, inode) of a bare model file and its
    sidecar — what an assembly was built from. No content is read."""
    path = Path(path)
    return [_stat_record(path), _stat_record(path.with_suffix(".json"))]


def carry_sidecar_key(bare: Path, before: List[Optional[List[int]]], key: str, value: Any) -> bool:
    """A bare sidecar write that is no assembly input — ONE key the caller
    just published into it (``collision``: the capsule set, measured on the
    bare body) — carried into the assembly of that tier: an assembly that was
    current against ``before`` (``bare_revision`` captured right before the
    write) gets the key and the new revision, so it stays served instead of
    being rebuilt for a key it merely copies. The caller holds
    ``model3d_publication`` of the model directory. True when re-stamped."""
    bare = Path(bare)
    if bare.parent.name == LOW:
        directory, tier = bare.parent.parent, LOW
    else:
        directory, tier = bare.parent, FULL
    assembled = assembled_path(directory, bare.stem, tier)
    if not assembled.is_file():
        return False
    meta = _read_json(assembled.with_suffix(".json"))
    if not meta or meta.get("bare_revision") != before:
        return False
    meta[key] = value
    meta["bare_revision"] = bare_revision(bare)
    _model3d()._publish_sidecar(assembled, meta)
    return True


def read_sidecar(path: Path) -> Dict[str, Any]:
    """The sidecar of an assembled (or bare) model file, {} when unreadable."""
    return _read_json(Path(path).with_suffix(".json"))


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _file_sha256(path: Optional[Path]) -> str:
    from app.core.base_body import file_sha256
    return file_sha256(path)


# --- What is wanted -----------------------------------------------------------

def built_on_fit_base(bare_meta: Dict[str, Any], record: Dict[str, Any]) -> bool:
    """Whether a bare outfit model (its sidecar ``bare_meta``) was built on
    the base model a fit (its ``record``) was fitted to: the sidecar's
    ``base_model_sha256`` equals the record's, or — a sidecar without the
    sha — its ``base_signature`` does. A sidecar with neither (a model from
    before the pipeline) matches nothing. A bare model on an OUTFIT BODY
    (sidecar ``body_id``, mesh mode) matches only a fit made on that body
    (record ``body_id``) on the same body bytes (``body_sha256``; plan
    2026-11-10-outfit-body-mesh-mode Task 2) — a fit of the base model or of
    another body is never grafted onto it, and a fit on an outfit body never
    onto a model of the base."""
    body = str(bare_meta.get("body_id") or "")
    if body:
        return (body == str(record.get("body_id") or "")
                and bool(bare_meta.get("body_sha256"))
                and str(bare_meta.get("body_sha256")) == str(record.get("body_sha256") or ""))
    if record.get("base_fit_sha256") and not record.get("base_model_sha256"):
        return False  # a fit on an outfit body
    sha = str(bare_meta.get("base_model_sha256") or "")
    if sha:
        return sha == str(record.get("base_model_sha256") or "")
    bsig = str(bare_meta.get("base_signature") or "")
    return bool(bsig) and bsig == str(record.get("base_signature") or "")


def effective_mesh_items(bare_meta: Optional[Dict[str, Any]]) -> List[str]:
    """The own-mesh outfit pieces a bare outfit model was built WITHOUT in its
    texture (``base_body.mesh_items_unpainted``: sidecar
    ``mesh_items.effective``; in outfit body mode mesh ``unpainted``, every
    flagged piece — one without an accepted fit yet is simply not grafted
    until it has one, ruling 2026-11-10), sorted; [] when it records none."""
    from app.core.base_body import mesh_items_unpainted
    return mesh_items_unpainted(bare_meta)


def _piece_kind(item: Dict[str, Any]) -> str:
    """The garment kind of an own-mesh outfit piece the bare model left out
    of its texture: ``garment_set.garment_kind_of`` — and for a piece whose
    flag was switched off since (the kind rule then answers None) the same
    slot rule: ``feet`` alone is footwear, anything else clothing."""
    from app.core.garment_set import CLOTHING, FOOTWEAR, FOOTWEAR_SLOT, garment_kind_of
    kind = garment_kind_of(item)
    if kind is not None:
        return kind
    piece = item.get("outfit_piece") if isinstance(item.get("outfit_piece"), dict) else {}
    slots = piece.get("slots") if isinstance(piece.get("slots"), (list, tuple)) else []
    return FOOTWEAR if {str(s) for s in slots} == {FOOTWEAR_SLOT} else CLOTHING


def _wanted(character_name: str, profile: Optional[Dict[str, Any]] = None, *,
            bare_meta: Optional[Dict[str, Any]] = None, build_layers: bool = False,
            left_off: Optional[Dict[str, str]] = None,
            warnings: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """The garments to graft, sorted by item id: ``{item_id, kind, fsig, fit,
    low, record}`` per garment with an accepted fit on the current base
    model — the hair of the profile's ``equipped_mesh_pieces``, and with
    ``bare_meta`` (the bare model's sidecar) the signature's effective mesh
    set (``effective_mesh_items``), restricted to fits on the base model that
    bare model was built on (``built_on_fit_base``). [] off the pipeline or
    with nothing wanted.

    Own-mesh pieces worn over each other (plan 2026-11-10 Task 2,
    ``garment_layers``): an outer piece's ``fit`` / ``low`` are its layered
    fit over the inner pieces of the set, and it carries ``over: {lsig,
    items, pending, without}``; a layered fit not built yet serves the body
    fit with ``pending`` True. ``build_layers`` (the assembly build, never
    serving) builds the missing ones first.

    A bare model on an outfit body (``body_id``): per garment its fit on that
    body (``garments.body_fit``) instead of the base fit; one still to be made
    is listed with ``fit`` None and ``pending`` True (serving), made first
    with ``build_layers``. ``left_off`` (a dict) collects item -> reason of the
    garments with a base fit that this body does not carry.

    Footwear (module docstring): its kind by ``_piece_kind``; at most one
    piece — the one worn in the feet slot per ``bare_meta['pieces']``, else
    the first by item id — any other is left off and named in ``warnings``
    (a list, ``FOOTWEAR_SECOND``). On an outfit body a footwear piece is
    fitted there from its source (``garment_footwear.body_fit``); no base
    fit is read for it."""
    if profile is None:
        from app.models.character import get_character_profile
        profile = get_character_profile(character_name) or {}
    worn = profile.get("equipped_mesh_pieces")
    hair = {str(v) for v in worn.values() if v} if isinstance(worn, dict) else set()
    clothing = set(effective_mesh_items(bare_meta)) - hair
    if not hair and not clothing:
        return []
    from app.core import base_body, garment_store
    from app.core.garment_set import CLOTHING, FOOTWEAR, FOOTWEAR_SLOT
    from app.models.inventory import get_item
    base = base_body.current_base(character_name, profile=profile)
    if not base or not base[1]:
        return []
    body_id = str((bare_meta or {}).get("body_id") or "")
    on_body = bare_meta is not None and garment_store.is_body_id(body_id)
    items = {item_id: get_item(item_id) or {} for item_id in hair | clothing}
    # The bare model was built without these in the texture: graft them even
    # when the flag was switched off since (that state has a signature of its
    # own; this model needs its garment).
    kinds = {item_id: _piece_kind(items[item_id]) for item_id in clothing
             if items[item_id].get("category") == "outfit_piece"}
    feet = sorted(item_id for item_id, kind in kinds.items() if kind == FOOTWEAR)
    worn_feet = str(((bare_meta or {}).get("pieces") or {}).get(FOOTWEAR_SLOT) or "")
    chosen_feet = worn_feet if worn_feet in feet else (feet[0] if feet else "")
    out: List[Dict[str, Any]] = []
    for item_id in sorted(hair | clothing):
        item = items[item_id]
        if item_id in clothing:
            kind = kinds.get(item_id)
            if kind is None:
                continue
            if kind == FOOTWEAR and item_id != chosen_feet:
                if warnings is not None:
                    warnings.append(FOOTWEAR_SECOND.format(item=str(item.get("name") or item_id)))
                continue
        else:
            kind = str((item.get("garment") or {}).get("kind") or "")
            if item.get("category") != "garment" or kind not in garment_store.GARMENT_VERSION:
                continue
        if on_body and kind == FOOTWEAR:
            # Fitted on the outfit body from the shoe source (spec § 5.8):
            # there is no base fit to derive it from, so none is required.
            from app.core import garment_footwear
            entry = garment_footwear.body_fit(character_name, item_id, body_id=body_id,
                                              body_sha=str(bare_meta.get("body_sha256") or ""),
                                              profile=profile, build=build_layers)
            fit = None
        else:
            # The fit of the CURRENT method (garment_store.accepted_fit): a switched
            # hair method serves that method's fit, or no hair before it has one.
            fit = garment_store.accepted_fit(character_name, item_id, base_model_sha=base[1], profile=profile)
            parsed = garment_store.parse_name(fit[0]) if fit else None
            if not parsed:
                continue
            entry = None
        if on_body:
            if entry is None:
                from app.core import garments
                entry = garments.body_fit(character_name, item_id, body_id=body_id,
                                          body_sha=str(bare_meta.get("body_sha256") or ""), base_fit=fit,
                                          profile=profile, build=build_layers)
            if entry["pending"]:
                out.append({"item_id": item_id, "kind": kind, "fsig": entry["fsig"], "fit": None, "low": None,
                            "record": {}, "pending": True})
                continue
            if entry["fit"] is None or not built_on_fit_base(bare_meta, entry["record"]):
                if left_off is not None:
                    left_off[item_id] = entry["error"] or "not fitted on this outfit body"
                continue
            out.append({"item_id": item_id, "kind": kind, "fsig": entry["fsig"], "fit": entry["fit"],
                        "low": entry["low"], "record": entry["record"]})
            continue
        if bare_meta is not None and not built_on_fit_base(bare_meta, fit[1]):
            continue
        fsig = parsed[1]
        low = garment_store.garment_path(character_name, item_id, fsig, "low")
        out.append({"item_id": item_id, "kind": kind, "fsig": fsig, "fit": fit[0],
                    "low": low if low.is_file() else None, "record": fit[1]})
    layered = [g for g in out if g["kind"] == CLOTHING and g["fit"] is not None]
    if bare_meta is not None and len(layered) > 1:
        from app.core import garment_layers
        from app.core.base_body import mesh_items_intended
        args = dict(base_sha=str(bare_meta.get("body_sha256") or "") if on_body else base[1], profile=profile,
                    intended=mesh_items_intended(bare_meta),
                    fits={g["item_id"]: (g["fit"], g["record"]) for g in layered},
                    **({"body": body_id} if on_body else {}))
        items = [g["item_id"] for g in layered]
        layers = (garment_layers.ensure if build_layers else garment_layers.plan)(character_name, items, **args)
        for g in layered:
            entry = layers.get(g["item_id"])
            if entry and entry["lsig"]:
                g.update(fit=entry["source"], low=entry["low"],
                         over={"lsig": entry["lsig"], "items": sorted(entry["inner"]),
                               "pending": entry["pending"], "without": entry["without"]})
    return out


def _wanted_for(character_name: str, directory: Path, signature: str, *,
                build_layers: bool = False) -> List[Dict[str, Any]]:
    """``_wanted`` for the bare model of ``signature`` in ``directory``: its
    FULL sidecar names the base it was built on (the low tier is derived
    from the full file)."""
    return _wanted(character_name, bare_meta=_read_json(bare_path(directory, signature, FULL).with_suffix(".json")),
                   build_layers=build_layers)


def body_fit_warning(character_name: str, bare_meta: Dict[str, Any], *,
                     profile: Optional[Dict[str, Any]] = None) -> str:
    """The outfit model build on an outfit body (``bare_meta``: its sidecar,
    ``body_id`` + ``body_sha256``, not published yet): fit every garment it
    carries onto the body now (``_wanted`` with ``build_layers`` — CPU, no
    hub job; the eager assembly then finds them) and return
    ``base_body.NOT_FITTED_ON_BODY`` naming the garments left off with the
    reason (a refused fit on that body), "" when none is. "" for a model on
    the base body."""
    from app.core import garment_store
    from app.core.base_body import NOT_FITTED_ON_BODY
    from app.models.inventory import get_item
    if not garment_store.is_body_id(str(bare_meta.get("body_id") or "")):
        return ""
    left_off: Dict[str, str] = {}
    _wanted(character_name, profile, bare_meta=bare_meta, build_layers=True, left_off=left_off)
    if not left_off:
        return ""
    names = [f"{(get_item(i) or {}).get('name') or i} ({reason})" for i, reason in sorted(left_off.items())]
    return NOT_FITTED_ON_BODY.format(items=", ".join(names))


def wanted_garments(character_name: str, *,
                    profile: Optional[Dict[str, Any]] = None) -> Dict[str, Tuple[Path, Optional[Path], dict]]:
    """item_id -> (fit GLB, low GLB or None, fit record) of every garment the
    served model should carry (R11); {} off the pipeline / with no equipped
    mesh piece / without an accepted fit on the current base model."""
    return {g["item_id"]: (g["fit"], g["low"], g["record"]) for g in _wanted(character_name, profile)}


def _source(garment: Dict[str, Any], tier: str) -> Path:
    """The GLB a tier takes the garment node from: the low tier's own garment
    when it was built, else the full fit (never a bald distance figure)."""
    return garment["low"] if tier == LOW and garment["low"] is not None else garment["fit"]


def _state(wanted: List[Dict[str, Any]], tier: str) -> Dict[str, Dict[str, Any]]:
    """The sidecar ``garments`` map an assembly of ``tier`` must carry — a
    layered piece adds ``over`` (its ``lsig``) and, while its layered fit is
    missing, ``pending`` (so the assembly is rebuilt once it exists)."""
    out: Dict[str, Dict[str, Any]] = {}
    for g in wanted:
        if g["fit"] is None:
            # A fit on an outfit body still to be made (``garments.body_fit``).
            out[g["item_id"]] = {"kind": g["kind"], "fsig": g["fsig"], "sha256": "", "pending": True}
            continue
        entry: Dict[str, Any] = {"kind": g["kind"], "fsig": g["fsig"], "sha256": _file_sha256(_source(g, tier))}
        over = g.get("over")
        if over:
            entry["over"] = over["lsig"]
            if over["pending"]:
                entry["pending"] = True
        out[g["item_id"]] = entry
    return out


def _current(assembled: Path, bare: Path, state: Dict[str, Any]) -> bool:
    if not assembled.is_file():
        return False
    meta = _read_json(assembled.with_suffix(".json"))
    return meta.get("bare_revision") == bare_revision(bare) and meta.get("garments") == state


# --- Serving ------------------------------------------------------------------

def served(character_name: str, path: Optional[Path], tier: str) -> Optional[Path]:
    """The file to deliver for the bare model ``path`` at ``tier``: its
    assembly when that is current (``bare_revision`` and ``garments`` equal
    the wanted state), else ``path`` itself — then a background build is
    asked for. ``path`` unchanged when nothing is wanted. Never raises."""
    if path is None:
        return path
    try:
        path = Path(path)
        tier = tier or FULL
        if path.suffix.lower() != ".glb" or tier not in TIERS:
            return path
        if tier == FULL:
            directory = path.parent
        elif path.parent.name == tier:
            directory = path.parent.parent
        else:
            return path
        signature = path.stem
        from app.core.base_body import is_base_signature
        if is_base_signature(signature):
            return path  # the base body itself is never dressed
        assembled = assembled_path(directory, signature, tier)
        wanted = _wanted_for(character_name, directory, signature)
        if not wanted:
            if assembled.exists():
                schedule(character_name, signature)  # takes the leftover away
            return path
        if _current(assembled, path, _state(wanted, tier)):
            return assembled
        schedule(character_name, signature)
        return path
    except Exception:  # noqa: BLE001 — serving falls back to the bare file
        logger.exception("Garment assembly %s: serving check failed", character_name)
        return path


def served_foot_pose(character_name: str, path: Optional[Path], tier: str = FULL) -> Optional[Dict[str, Any]]:
    """The ``foot_pose`` of the file ``served`` for the bare model ``path``
    at ``tier`` (spec § 6.1): the assembly sidecar's record when the
    assembly is served, else None — the bare file (an assembly still
    building, or none wanted) carries no pose, and an assembly without a
    footwear piece none either. Read under the publication lock, so the
    sidecar belongs to the file that is served. Never raises."""
    if path is None:
        return None
    try:
        from app.core.keyed_lock import keyed_lock
        path = Path(path)
        with keyed_lock("model3d_publication", str(path.parent.parent if path.parent.name == LOW else path.parent)):
            file = served(character_name, path, tier)
            if file is None or Path(file) == path:
                return None
            pose = read_sidecar(file).get("foot_pose")
        return pose if isinstance(pose, dict) else None
    except Exception:  # noqa: BLE001 — a missing pose never breaks the info
        logger.exception("Garment assembly %s: foot pose unreadable", character_name)
        return None


# --- Building -----------------------------------------------------------------

def _remove(directory: Path, signature: str, tier: str) -> bool:
    """Unlink one tier's assembly under the publication lock; True if any."""
    from app.core.keyed_lock import keyed_lock
    target = assembled_path(directory, signature, tier)
    removed = False
    with keyed_lock("model3d_publication", str(directory)):
        for p in (target, target.with_suffix(".json")):
            if p.exists():
                p.unlink(missing_ok=True)
                removed = True
    return removed


def _cut_body(blob: bytes, garment: Dict[str, Any], tier: str) -> bytes:
    """``blob`` (a bare tier) with the footwear fit record's ``cut`` applied
    to every body primitive (spec § 7.1: the foot inside the shoe goes from
    the served file; ``footwear_cut.apply_cut`` per primitive — a
    multi-primitive body is slimmed per primitive, as the fit does —
    written back by ``glb_mesh.rewrite_body_primitives``). ValueError for a
    record without a cut (a fit of another version is never grafted)."""
    from app.core import footwear_cut, glb_mesh
    record = garment.get("record") or {}
    cut = record.get("cut")
    if not isinstance(cut, dict) or not cut.get("sides"):
        raise ValueError(f"footwear fit {garment['item_id']} {garment['fsig']} carries no cut")
    joints = glb_mesh.joint_bind_matrices(blob)
    replaced: Dict[int, glb_mesh.Prim] = {}
    totals = {"removed_faces": 0, "bisected_faces": 0, "new_vertices": 0}
    for i, prim in enumerate(glb_mesh.body_primitive_arrays(blob)):
        replaced[i], stats = footwear_cut.apply_cut(prim, cut, joints)
        for key in totals:
            totals[key] += int(stats[key])
    logger.info("Garment assembly: %s (%s) cut the %s body — %d faces removed / %d bisected / %d new vertices",
                garment["item_id"], garment["fsig"], tier, totals["removed_faces"], totals["bisected_faces"],
                totals["new_vertices"])
    return glb_mesh.rewrite_body_primitives(blob, replaced)


def _tint_scalp(blob: bytes, mesh, garment: Dict[str, Any], tier: str, tints: Dict[str, Any]) -> bytes:
    """``blob`` with the scalp under the hair ``mesh`` tinted in the body texture (``hair_scalp_tint``; the bare
    and base files stay untouched — this is the assembly's copy). A failure keeps the untinted body: the tint is a
    finish, never a reason to withhold the assembly."""
    from app.core.hair_scalp_tint import tint_scalp
    try:
        tinted, report = tint_scalp(blob, mesh)
    except Exception as e:  # noqa: BLE001 — a finishing step; the assembly goes on without it
        logger.warning("Garment assembly: scalp tint under %s (%s, %s) failed: %s", garment["item_id"],
                       garment["fsig"], tier, e)
        tints[garment["item_id"]] = {"error": str(e)}
        return blob
    tints[garment["item_id"]] = {k: report[k] for k in ("skipped", "covered_cells", "images", "colour_srgb")
                                 if k in report}
    return tinted


def _build(character_name: str, directory: Path, bare: Path,
           wanted: List[Dict[str, Any]], tier: str,
           warnings: Optional[List[str]] = None) -> Tuple[bytes, Dict[str, Any], list]:
    """Read the bare file + its sidecar under the publication lock (so bytes
    and revision belong together), cut the body for a footwear piece, graft
    every garment (a footwear piece as its shoe nodes — the two foot nodes,
    and a boot's two shaft nodes, each read by its exact name), validate.
    ``warnings``: the assembly's own ``garment_warnings`` (``_wanted``),
    appended to the bare sidecar's in the assembled sidecar. Returns (bytes,
    sidecar, captured revision)."""
    import hashlib
    from app.core import glb_mesh
    from app.core.garment_set import FOOTWEAR, HAIR
    from app.core.keyed_lock import keyed_lock
    from app.core.model_validate import rig_frames_preserved
    from app.core.timeutils import utc_now_iso
    model3d = _model3d()
    with keyed_lock("model3d_publication", str(directory)):
        revision = bare_revision(bare)
        data = bare.read_bytes()
        meta = _read_json(bare.with_suffix(".json"))
    if meta.get("base") or meta.get("rig") != "mixamo":
        raise ValueError(f"bare model {bare.name} is no rigged outfit model (rig {meta.get('rig')!r})")
    blob = data
    grafted = [g for g in wanted if g["fit"] is not None]  # never a pending one (``_wanted`` with build_layers fits first)
    foot_pose: Optional[Dict[str, Any]] = None
    for garment in grafted:
        if garment["kind"] != FOOTWEAR:
            continue
        pose = (garment.get("record") or {}).get("foot_pose")
        if not isinstance(pose, dict):
            raise ValueError(f"footwear fit {garment['item_id']} {garment['fsig']} carries no foot_pose")
        blob = _cut_body(blob, garment, tier)
        # The BARE body's rest measurements ride with the record (``footwear_rest``, Task 20b): the served
        # body is cut under the shoe, so the renderers' bind-pose anchor and rest soles must not read it.
        # Measured on ``data`` — the very bare file this assembly is built from — and overriding what the fit
        # measured on its own (the same) body.
        from app.core.footwear_rest import rest_measurement
        foot_pose = {**pose, "rest": rest_measurement(data),
                     "source": {"item_id": garment["item_id"], "fsig": garment["fsig"], "glb_sha256": ""}}
    scalp_tints: Dict[str, Any] = {}
    for garment in grafted:
        source = _source(garment, tier).read_bytes()
        extras = {"kind": garment["kind"], "item_id": garment["item_id"], "fsig": garment["fsig"]}
        if garment["kind"] == FOOTWEAR:
            from app.core.footwear_fit import SIDES
            from app.core.garment_footwear import PARTS, node_name
            for side_name in SIDES:
                for part in PARTS:
                    name = node_name(garment["item_id"], side_name, part)
                    try:
                        # exact: the foot node's name is a prefix of the shaft node's
                        mesh = glb_mesh.garment_arrays(source, node_prefix=name, exact=True)
                    except ValueError:
                        if part == "foot":
                            raise
                        continue              # a shoe has no shaft node
                    blob = glb_mesh.graft(blob, mesh, name=name, extras={**extras, "side": side_name, "part": part})
            continue
        mesh = glb_mesh.garment_arrays(source)
        if garment["kind"] == HAIR:
            blob = _tint_scalp(blob, mesh, garment, tier, scalp_tints)
        if garment.get("over") and not garment["over"]["pending"]:
            extras["over"] = garment["over"]["items"]
        blob = glb_mesh.graft(blob, mesh, name=f"garment_{garment['kind']}_{garment['item_id']}", extras=extras)
    verdict = model3d._validator_for("mixamo", character_name)(blob)
    if not verdict.get("ok"):
        raise ValueError("assembled model failed validation: " + "; ".join(verdict.get("errors") or []))
    frames = rig_frames_preserved(data, blob)
    if not frames.get("ok"):
        raise ValueError("assembled model rewrote the rig frames: " + "; ".join(frames.get("errors") or []))
    side = {**meta, "garments": _state(wanted, tier), "bare_revision": revision,
            "assembled_at": utc_now_iso()}
    if scalp_tints:
        side["scalp_tint"] = scalp_tints
    if foot_pose is not None:
        foot_pose["source"]["glb_sha256"] = hashlib.sha256(blob).hexdigest()
        side["foot_pose"] = foot_pose
    if warnings:
        side["garment_warnings"] = [*(meta.get("garment_warnings") or []), *warnings]
    return blob, side, revision


def assemble(character_name: str, signature: str, *,
             tiers: Tuple[str, ...] = (FULL, LOW)) -> Dict[str, Any]:
    """Build (or remove) the assembled delivery files of ``signature``.

    Per tier: the bare revision and the wanted garments are captured FIRST;
    the result is published under ``model3d_publication`` only while the
    bare file is still the captured one. Nothing wanted (or no bare file of
    that tier) removes an existing assembly. An assembly that is already
    current is left alone. Works inside a staged model operation too (the
    model directory is then the stage; its publication carries the result).

    Returns ``{ok, tiers: {tier: status}, error?}`` with status
    ``assembled`` / ``current`` / ``removed`` / ``none`` / ``stale`` /
    ``failed``."""
    from app.core import sync_topics
    from app.core.keyed_lock import keyed_lock
    model3d = _model3d()
    if not isinstance(signature, str) or not signature or any(c in signature for c in ("/", "\\", "\0")) \
            or signature in (".", ".."):
        raise ValueError("Invalid model signature")
    directory = model3d.get_model3d_dir(character_name)
    # The layered fits of pieces worn over each other are built here (CPU, no hub job), never while serving.
    warnings: List[str] = []
    wanted = _wanted(character_name, bare_meta=_read_json(bare_path(directory, signature, FULL).with_suffix(".json")),
                     build_layers=True, warnings=warnings)
    statuses: Dict[str, str] = {}
    errors: List[str] = []
    changed = False
    for tier in tiers:
        if tier not in TIERS:
            raise ValueError(f"unknown model tier {tier!r}")
        bare = bare_path(directory, signature, tier)
        target = assembled_path(directory, signature, tier)
        if not wanted or not bare.is_file():
            removed = _remove(directory, signature, tier) if target.exists() or target.with_suffix(".json").exists() \
                else False
            changed |= removed
            statuses[tier] = "removed" if removed else "none"
            continue
        if _current(target, bare, _state(wanted, tier)):
            statuses[tier] = "current"
            continue
        try:
            blob, side, revision = _build(character_name, directory, bare, wanted, tier, warnings)
        except Exception as e:  # noqa: BLE001 — one tier's failure is reported, the bare file keeps serving
            logger.warning("Garment assembly %s/%s (%s) failed: %s", character_name, signature, tier, e)
            statuses[tier] = "failed"
            errors.append(f"{tier}: {e}")
            continue
        with keyed_lock("model3d_publication", str(directory)):
            if bare_revision(bare) != revision:
                statuses[tier] = "stale"  # the bare file moved on meanwhile
                continue
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                model3d._publish_model_bytes(target, blob)
                model3d._publish_sidecar(target, side)
            except FileNotFoundError:
                statuses[tier] = "none"  # model directory deleted meanwhile
                continue
        changed = True
        statuses[tier] = "assembled"
        logger.info("Garment assembly %s: %s (%s, %d garment(s), %d bytes)", character_name,
                    target.name, tier, len(wanted), len(blob))
    if changed and character_name not in getattr(model3d._staging, "directories", {}):
        sync_topics.changed_at(character_name)
    out: Dict[str, Any] = {"ok": not errors, "tiers": statuses}
    if errors:
        out["error"] = "; ".join(errors)
    return out


def _input_key(character_name: str, signature: str) -> str:
    """What a build of ``signature`` would read now (both tiers' bare
    revisions + wanted garments) — the failure memo's key."""
    directory = _model3d().get_model3d_dir(character_name)
    wanted = _wanted_for(character_name, directory, signature)
    return json.dumps([[bare_revision(bare_path(directory, signature, t)), _state(wanted, t)] for t in TIERS],
                      sort_keys=True)


def schedule(character_name: str, signature: Optional[str] = None) -> bool:
    """Ask for a background (re)build of the assembled model of ``signature``
    (None = the model the current outfit serves, else the current outfit
    signature). One build per (character, signature) at a time — a request
    while one runs makes it run once more. Inside a staged model operation
    the request waits for that operation's publication. A build that failed
    is not retried with unchanged inputs. True if started (or deferred)."""
    try:
        model3d = _model3d()
        if signature is None:
            path = model3d.find_model3d_serving(character_name)[0]
            if path is None:
                from app.core.model_refs import current_outfit_state
                signature = current_outfit_state(character_name)[2]
            else:
                signature = path.stem
        if not isinstance(signature, str) or not signature or any(c in signature for c in ("/", "\\", "\0")) \
                or signature in (".", ".."):
            return False
        if character_name in getattr(model3d._staging, "directories", {}):
            requests = getattr(model3d._staging, "assembly_requests", {}).get(character_name)
            if requests is None:
                return False
            requests.add(signature)
            return True
        key = (character_name, signature)
        directory = model3d.get_model3d_dir(character_name)
        if not _wanted_for(character_name, directory, signature) and not any(
                p.exists() for t in TIERS
                for p in (assembled_path(directory, signature, t),
                          assembled_path(directory, signature, t).with_suffix(".json"))):
            return False  # nothing to build and nothing to take away: no thread
        if key in _failed and _failed.get(key) == _input_key(character_name, signature):
            return False
        with _lock:
            if key in _building:
                _again.add(key)
                return False
            _building.add(key)
        threading.Thread(target=_run, args=(key,), daemon=True,
                         name=f"garment-assembly-{character_name}").start()
        return True
    except Exception:  # noqa: BLE001 — a schedule request never breaks its caller
        logger.exception("Garment assembly %s: schedule failed", character_name)
        return False


def _run(key: Tuple[str, str]) -> None:
    character_name, signature = key
    try:
        while True:
            with _lock:
                _again.discard(key)
            try:
                inputs = _input_key(character_name, signature)
                result = assemble(character_name, signature)
            except Exception as e:  # noqa: BLE001
                logger.warning("Garment assembly %s/%s failed: %s", character_name, signature, e)
                result, inputs = {"ok": False, "error": str(e)}, ""
            if result.get("ok"):
                _failed.pop(key, None)
            elif inputs:
                _failed[key] = inputs
            with _lock:
                # Leave the in-flight set in the same critical section that
                # saw no new request, so no request falls between the two.
                if key not in _again:
                    _building.discard(key)
                    return
    except BaseException:
        with _lock:
            _building.discard(key)
            _again.discard(key)
        raise


def wait_idle(timeout: float = 30.0) -> bool:
    """Block until no background build runs (smokes, shutdown). True when idle."""
    import time
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with _lock:
            if not _building:
                return True
        time.sleep(0.02)
    return False
