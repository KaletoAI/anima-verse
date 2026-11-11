"""Layered fits — own-mesh pieces worn over each other (plan
``docs/superpowers/plans/2026-11-10-texture-body-reuse-and-layering.md``, Task 2).

Every own-mesh piece is fitted against the BODY alone by its garment chain (``garments._fit``: the fit
``garments/{item}_{fsig}.glb``, accepted on one base model). Worn over other own-mesh pieces it is served LAYERED:

- **Order** — ``garment_set.layer_order`` over the pieces of the outfit (its intended own-mesh pieces): a piece
  whose slots / covers / partially_covers include a slot another worn piece is worn on is OUTER; cycles go by slot
  rank and are reported (``garment_set.mesh_overlaps``, the Wardrobe warning; a log line on every build).
- **Fit** — an outer piece over inner pieces = its body fit pushed over the inner pieces' SERVED meshes (their own
  layered fit when they lie over something too) by ``garment_fit_layers.layer_over`` in the rigged bind space —
  CPU only: no image, no mesh generator, no hub job; the outer piece's images, mesh and body fit stay. Built
  inner → outer, so a piece is never layered over a stale inner one.
- **Key** — ``lsig`` = md5[:12] over ``{version, inner: {item: sha256 of the inner piece's served full-tier
  GLB}}``; the file is ``garments/layers/{item}_{fsig}_{lsig}.glb`` (+ ``.json``, + ``layers/low/…`` from the
  body fit's distance tier). Any change of an inner fit (a refit on a new base model, a new mesh, an inner piece
  that now lies over something itself) gives another ``lsig`` — the outer piece is refitted (layered again, no
  hub job) instead of being served over the old inner one. The record names the inner fits
  (``inner: {item: {fsig, sha256}}``), the body fit it was made from (``base_fit_sha256``) and the base model
  (``base_model_sha256``); a layered fit is valid only while all three are current.
- **Without** — an inner piece without an accepted fit is painted onto the body (the outfit build), so the outer
  piece is fitted against the body there: it is served with its body fit and listed ``without`` that piece
  (the Wardrobe chip). When the inner piece's fit lands the outfit model is rebuilt with it as a mesh
  (``base_body.after_mesh_item_ready``) and the outer piece gets its layered fit then.
- **Cache** — the fits are kept per inner set: an outer piece worn WITHOUT the inner piece is served its body
  fit (no layer), and worn with it again its stored layered fit — toggling never refits twice. Per
  ``(item, fsig)`` the newest ``LAYER_KEEP`` layered fits made from the CURRENT body fit stay; the rest go on
  every write. The cache GC treats them as part of the ``(item, fsig)`` group (``garment_store.parse_name``).

Per body (plan ``2026-11-10-outfit-body-mesh-mode.md``, Task 2): on an OUTFIT BODY (mesh mode) the pieces' fits
are the fits on that body (``garments.body_fit``), the layered fits live in that body's folder
(``garments/bodies/<body id>/layers/``, ``garment_store.body_root``), ``base_sha`` is the body's sha256 and the
rigged body is ``model3d/<body id>.glb``; the record names ``body_id`` + ``body_sha256``. A layered fit of one body
is never valid on another (its record's body sha differs).

Who builds: the garment assembly (``garment_assembly.assemble`` → ``_wanted(build_layers=True)``) before it
grafts — serving (``served``) only reads (``plan``): a missing layered fit serves the body fit, marks the
assembly ``pending`` and asks for a build.

**Trousers over a boot — the hem** (boots spec ``docs/superpowers/specs/2026-11-11-footwear-boots-mens-design.md``
§ 8, plan Task 10; ``app.core.outfit_options``). When the outfit wears a split boot and own-mesh trousers (no
skirt), the assembly hands ``plan`` / ``ensure`` a ``hem`` = ``{boot, fit, trousers, mode}``: the boot's two SHAFT
nodes of its fit GLB (``garment_footwear.node_name(item, side, "shaft")`` — never the foot part, whose bind
geometry is rotated back by the extension) become an inner piece of the trousers, keyed ``inner[boot]`` = the
sha256 of the shaft nodes' arrays (``shaft_sha``), so a refit of the boot invalidates the file; ``mode`` goes into
the ``lsig`` (``layer_sig(inner, mode=…, plane_m=…)``) — a toggle is another file, flipping back serves the cached
one. ``over`` (the default): the trousers are ``layer_over``-ed with the shafts among the inners. ``tucked``: the
trousers (layered over their inner clothing first) are cut by ``footwear_cut.plane_cut`` at ``plane_m`` = the
shaft nodes' top (bind space) − ``TUCK_RESERVE_M`` (0.03: the hem ends inside the collar and never shows when the
knee bends); gate ``tucked_poke`` = of the remaining trouser vertices between the plane and the shaft top, the
share outside the shaft's cross-section at the plane (``footwear_insole.opening_polygon`` of either shaft) —
above ``TUCKED_POKE_MAX`` (1 %) the pair cannot be tucked (nor in reality: there is no inward layering), the
``over`` geometry is built under the tucked ``lsig`` instead and the record says ``hem.fallback = "too_wide"``
(the Wardrobe warning ``outfit_options.TOO_WIDE_WARNING``). The record's ``hem`` = ``{mode, built, plane_m,
tucked_poke, fallback, boot, shaft_sha}``; ``plan`` returns it per entry (``hem``) and the assembly's ``_state``
carries ``{mode, lsig, fallback}``, so a toggle rebuilds the served model.
"""
import hashlib
import json
import threading
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

from app.core.log import get_logger

logger = get_logger("garment_layers")

#: Bumped when a layered fit's meaning changes (part of ``lsig``).
LAYER_VERSION = 1
#: Layered fits kept per (item, fsig) — inner sets an outfit switches between.
LAYER_KEEP = 4
#: A tucked trouser leg is cut this far under the boot shaft's top (metres; spec § 8.1).
TUCK_RESERVE_M = 0.03
#: Tucked: the largest share of the remaining trouser vertices under the shaft top that may stand outside the
#: shaft — above it the pair falls back to ``over`` (``HEM_FALLBACK_TOO_WIDE``).
TUCKED_POKE_MAX = 0.01
HEM_FALLBACK_TOO_WIDE = "too_wide"
#: ``tucked_poke`` reads the trouser vertices between the plane and the shaft top with this tolerance (metres).
HEM_BAND_EPS_M = 1e-9

_lock = threading.Lock()
# (character, item, fsig, lsig, body fit sha256, base model sha256) -> the error of a build that failed: not
# retried with the same inputs in this process (a new inner fit, body fit or base model is a new key).
_failed: Dict[Tuple[str, str, str, str, str, str], str] = {}


def _failure_key(character_name: str, item_id: str, entry: Dict[str, Any],
                 base_sha: str) -> Tuple[str, str, str, str, str, str]:
    # ``base_sha`` is the body's sha on an outfit body: the key differs per body.
    return character_name, item_id, entry["fsig"], entry["lsig"], _sha(entry["fit"]), base_sha


def layer_sig(inner: Dict[str, str], *, mode: str = "", plane_m: Optional[float] = None) -> str:
    """``lsig`` of a layered fit over ``inner`` (item -> sha256 of its served full-tier GLB; a boot: its shaft
    nodes' ``shaft_sha``). ``mode`` (the hem, ``over`` / ``tucked``) and ``plane_m`` (the tucked cut's height,
    6 decimals) enter the payload only when given, so a plain layer's lsig is unchanged."""
    payload: Dict[str, Any] = {"version": LAYER_VERSION, "inner": dict(sorted(inner.items()))}
    if mode:
        payload["mode"] = str(mode)
    if plane_m is not None:
        payload["plane_m"] = round(float(plane_m), 6)
    return hashlib.md5(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:12]


def shaft_meshes(fit_bytes: bytes, boot_item: str) -> List[Any]:
    """The boot's shaft nodes (both sides, ``garment_footwear.node_name(…, "shaft")``) of a footwear fit GLB as
    ``GarmentMesh`` objects, in side order; [] when the fit has no shaft node (a shoe)."""
    from app.core import glb_mesh
    from app.core.footwear_fit import SIDES
    from app.core.garment_footwear import node_name
    out = []
    for side in SIDES:
        try:
            out.append(glb_mesh.garment_arrays(fit_bytes, node_prefix=node_name(boot_item, side, "shaft"), exact=True))
        except ValueError:
            continue
    return out


def shaft_sha(meshes: Sequence[Any]) -> str:
    """sha256 over the shaft nodes' arrays (positions, indices, joints, weights, in side order) — what a refit of
    the boot changes; "" without a shaft."""
    if not meshes:
        return ""
    h = hashlib.sha256()
    for g in meshes:
        for arr in (g.positions, g.indices, g.joints, g.weights):
            a = np.ascontiguousarray(np.asarray(arr))
            h.update(str(a.dtype).encode()); h.update(str(a.shape).encode()); h.update(a.tobytes())
    return h.hexdigest()


def _hem_inputs(hem: Dict[str, Any]) -> Dict[str, Any]:
    """The shaft meshes of a ``hem`` (``{boot, fit, trousers, mode}``), their sha and the tucked plane height:
    ``{meshes, sha, top_m, plane_m}``; ``meshes`` [] when the boot fit carries no shaft node."""
    meshes = shaft_meshes(Path(hem["fit"]).read_bytes(), str(hem["boot"]))
    top = max((float(np.asarray(g.positions, np.float64)[:, 1].max()) for g in meshes if len(g.positions)),
              default=None)
    return {"meshes": meshes, "sha": shaft_sha(meshes), "top_m": top,
            "plane_m": None if top is None else top - TUCK_RESERVE_M}


def _sha(path: Optional[Path]) -> str:
    from app.core.base_body import file_sha256
    return file_sha256(path)


def _target_sha(record: Dict[str, Any], body: str) -> str:
    """The sha of the rigged body a layered fit was made on: ``body_sha256``
    on an outfit body (``body``), ``base_model_sha256`` on the base."""
    return str(record.get("body_sha256" if body else "base_model_sha256") or "")


def _valid(record: Dict[str, Any], *, lsig: str, base_sha: str, base_fit_sha: str,
           inner: Dict[str, str], body: str = "") -> bool:
    if body and record.get("body_id") != body:
        return False
    return (record.get("accepted") is True and record.get("lsig") == lsig
            and _target_sha(record, body) == base_sha and record.get("base_fit_sha256") == base_fit_sha
            and {k: (v or {}).get("sha256") for k, v in (record.get("inner") or {}).items()} == inner)


def plan(character_name: str, item_ids: Iterable[str], *, base_sha: str,
         profile: Optional[Dict[str, Any]] = None, intended: Iterable[str] = (),
         fits: Optional[Dict[str, Tuple[Path, Dict[str, Any]]]] = None,
         body: str = "", hem: Optional[Dict[str, Any]] = None) -> Dict[str, Dict[str, Any]]:
    """What to serve per own-mesh piece of an outfit — read only, never builds.

    ``item_ids``: the pieces worn as meshes (with an accepted body fit on ``base_sha``; ``fits`` may hand those
    ``(fit GLB, record)`` in, else ``garment_store.accepted_fit``); ``intended``: every own-mesh piece the outfit
    wears (a piece without a fit there is painted on). Per piece with a body fit, in layer order:
    ``{fsig, fit, record, source, low, lsig, inner, pending, without}`` — ``source`` / ``low`` the full / distance
    tier GLB to take the garment from (the layered fit when it is stored and valid, else the body fit and its
    ``low/`` tier, ``low`` None without one), ``lsig`` "" for a piece over nothing, ``inner`` item -> sha256 of the
    inner pieces' served full tier, ``pending`` True when the layered fit is missing, ``without`` the intended
    pieces under it without a fit. ``body``: an outfit body id — ``base_sha`` is then that body's sha256 and
    ``fits`` MUST be its body fits (``garments.body_fit``; never looked up here), the layered fits are that body's.

    ``hem`` (module docstring): ``{boot, fit, trousers, mode}`` — the boot's shaft nodes become an inner piece of
    ``trousers`` (``inner[boot]`` = ``shaft_sha``), ``mode`` and the tucked plane enter its ``lsig``, and the entry
    carries ``hem`` = ``{boot, mode, plane_m, top_m, fit, fallback}`` (``fallback`` from the stored record, None
    while pending). A boot fit without a shaft node is ignored."""
    from app.core import body_slots, garment_set, garment_store
    pieces = sorted({str(i) for i in item_ids if i})
    if not pieces or not base_sha:
        return {}
    hem_in: Optional[Dict[str, Any]] = None
    if hem and str(hem.get("trousers") or "") in pieces and hem.get("fit") and hem.get("boot"):
        inputs = _hem_inputs(hem)
        if inputs["meshes"]:
            hem_in = {**hem, **inputs}
    if fits is None:
        if body:
            raise ValueError("the fits on an outfit body are handed in (garments.body_fit)")
        fits = {}
        for item_id in pieces:
            fit = garment_store.accepted_fit(character_name, item_id, base_model_sha=base_sha, profile=profile)
            if fit is not None:
                fits[item_id] = fit
    layers = garment_set.layer_order(set(pieces) | {str(i) for i in intended or () if i},
                                     slot_order=body_slots.piece_slots_for_character(character_name))
    out: Dict[str, Dict[str, Any]] = {}
    for item_id in layers["order"] + [p for p in pieces if p not in layers["order"]]:
        if item_id not in pieces or item_id not in fits:
            continue
        fit, record = fits[item_id]
        parsed = garment_store.parse_name(fit)
        if not parsed:
            continue
        fsig = parsed[1]
        body_low = garment_store.garment_path(character_name, item_id, fsig, "low", body=body)
        entry: Dict[str, Any] = {
            "fsig": fsig, "fit": fit, "record": record, "source": fit,
            "low": body_low if body_low.is_file() else None, "lsig": "", "inner": {}, "pending": False,
            "without": [u for u in layers["under"].get(item_id, []) if u not in fits]}
        below = [u for u in layers["under"].get(item_id, []) if u in out]
        inner = {u: _sha(out[u]["source"]) for u in below}
        mode, plane_m = "", None
        if hem_in is not None and item_id == str(hem_in["trousers"]):
            inner[str(hem_in["boot"])] = hem_in["sha"]
            mode = str(hem_in["mode"])
            plane_m = hem_in["plane_m"] if mode == "tucked" else None
            entry["hem"] = {"boot": str(hem_in["boot"]), "mode": mode, "plane_m": plane_m, "top_m": hem_in["top_m"],
                            "fit": Path(hem_in["fit"]), "fallback": None}
        if inner:
            lsig = layer_sig(inner, mode=mode, plane_m=plane_m)
            path = garment_store.garment_path(character_name, item_id, fsig, "layer", lsig=lsig, body=body)
            low = garment_store.garment_path(character_name, item_id, fsig, "layer_low", lsig=lsig, body=body)
            entry.update(lsig=lsig, inner=inner)
            record = garment_store.read_record(path.with_suffix(".json")) if path.is_file() else {}
            if path.is_file() and _valid(record, lsig=lsig, base_sha=base_sha, base_fit_sha=_sha(fit), inner=inner,
                                         body=body):
                entry.update(source=path, low=low if low.is_file() else None)
                if "hem" in entry:
                    entry["hem"]["fallback"] = (record.get("hem") or {}).get("fallback")
            else:
                entry["pending"] = True
        out[item_id] = entry
    return out


def ensure(character_name: str, item_ids: Iterable[str], *, base_sha: str,
           profile: Optional[Dict[str, Any]] = None, intended: Iterable[str] = (),
           fits: Optional[Dict[str, Tuple[Path, Dict[str, Any]]]] = None,
           body: str = "", hem: Optional[Dict[str, Any]] = None) -> Dict[str, Dict[str, Any]]:
    """``plan`` after building every missing layered fit, inner → outer (each build changes the inner sha its
    outer pieces are keyed by, so the plan is taken again after it). A build that fails is logged, remembered
    for its inputs and left ``pending`` (the piece keeps its body fit). Serialised per character. ``body`` and
    ``hem`` as in ``plan``."""
    from app.core.keyed_lock import keyed_lock
    pieces = sorted({str(i) for i in item_ids if i})
    intended = sorted({str(i) for i in intended or () if i})
    with keyed_lock("garment_layers", character_name):
        tried: set = set()
        current = plan(character_name, pieces, base_sha=base_sha, profile=profile, intended=intended, fits=fits,
                       body=body, hem=hem)
        _log_cycles(character_name, pieces, intended)
        for _ in range(len(current) + 1):
            todo = next((i for i, e in current.items() if e["pending"] and i not in tried
                         and _failure_key(character_name, i, e, base_sha) not in _failed), None)
            if todo is None:
                break
            tried.add(todo)
            entry = current[todo]
            try:
                _build(character_name, todo, entry, {u: current[u] for u in entry["inner"] if u in current},
                       base_sha, body=body)
            except Exception as e:  # noqa: BLE001 — the piece keeps its body fit, the assembly goes on
                logger.warning("Layered fit %s/%s over %s failed: %s", character_name, todo,
                               sorted(entry["inner"]), e)
                with _lock:
                    _failed[_failure_key(character_name, todo, entry, base_sha)] = str(e) or type(e).__name__
            current = plan(character_name, pieces, base_sha=base_sha, profile=profile, intended=intended,
                           fits=fits, body=body, hem=hem)
        return current


def _log_cycles(character_name: str, pieces: List[str], intended: List[str]) -> None:
    from app.core import body_slots, garment_set
    cycles = garment_set.layer_order(set(pieces) | set(intended),
                                     slot_order=body_slots.piece_slots_for_character(character_name))["cycles"]
    for cycle in cycles:
        logger.warning("Own-mesh pieces of %s are over each other (%s on %s): layered in slot order, %s innermost",
                       character_name, ", ".join(cycle["items"]), ", ".join(cycle["slots"]), cycle["items"][0])


def _rigged_base(character_name: str, record: Dict[str, Any], base_sha: str, body: str = "") -> bytes:
    """The rigged base model the body fit was made on (its record's ``base_signature``; on an outfit body
    ``body`` that body's ``model3d/<body id>.glb``), read under the publication lock and checked against
    ``base_sha``. ValueError when it is gone or another one."""
    from app.core.keyed_lock import keyed_lock
    from app.models.character import get_character_dir
    bsig = body or str(record.get("base_signature") or "")
    if not bsig or any(c in bsig for c in "/\\\0") or bsig in (".", ".."):
        raise ValueError("the body fit names no base signature")
    directory = get_character_dir(character_name) / "model3d"
    with keyed_lock("model3d_publication", str(directory)):
        try:
            data = (directory / f"{bsig}.glb").read_bytes()
        except OSError as e:
            raise ValueError(f"the base model is gone: {e}") from e
    if hashlib.sha256(data).hexdigest() != base_sha:
        raise ValueError("the base model changed — the body fits are refitted first")
    return data


def _mesh_prim(g: Any):
    """A ``GarmentMesh`` as a ``footwear_cut.Prim`` (NORMAL / TEXCOORD_0 / COLOR_0 as attributes) and back."""
    from app.core.glb_mesh import Prim
    attributes: Dict[str, np.ndarray] = {"TEXCOORD_0": np.asarray(g.uvs, np.float64)}
    if g.normals is not None:
        attributes["NORMAL"] = np.asarray(g.normals, np.float64)
    if g.colors is not None:
        attributes["COLOR_0"] = np.asarray(g.colors, np.float64)
    return Prim(positions=np.asarray(g.positions, np.float64), faces=np.asarray(g.indices, np.int64).reshape(-1, 3),
                attributes=attributes, joints=np.asarray(g.joints, np.int64), weights=np.asarray(g.weights, np.float64),
                targets=[], joint_names=list(g.joint_names))


def _prim_mesh(prim: Any, like: Any):
    from dataclasses import replace
    return replace(like, positions=prim.positions, indices=prim.faces, uvs=prim.attributes["TEXCOORD_0"],
                   normals=prim.attributes.get("NORMAL"), colors=prim.attributes.get("COLOR_0"),
                   joints=prim.joints, weights=prim.weights)


def tucked_poke(mesh: Any, shafts: Sequence[Any], plane_m: float, top_m: float) -> Dict[str, Any]:
    """The tucked gate (module docstring): of the trouser vertices with bind height in [``plane_m``, ``top_m``],
    the share outside every shaft's cross-section at ``plane_m`` (``footwear_insole.opening_polygon``) —
    ``{"tucked_poke", "n", "outside"}``; 0 with no vertex in the band (nothing reaches into the shaft)."""
    from app.core.footwear_insole import inside_polygon, opening_polygon
    P = np.asarray(mesh.positions, np.float64)
    band = (P[:, 1] >= plane_m - HEM_BAND_EPS_M) & (P[:, 1] <= top_m + HEM_BAND_EPS_M)
    n = int(band.sum())
    if not n:
        return {"tucked_poke": 0.0, "n": 0, "outside": 0}
    inside = np.zeros(n, bool)
    for shaft in shafts:
        poly = opening_polygon(shaft.positions, shaft.indices, plane_m)
        inside |= inside_polygon(P[band][:, [0, 2]], poly)
    outside = int((~inside).sum())
    return {"tucked_poke": outside / n, "n": n, "outside": outside}


def _tuck(outer: Any, shafts: Sequence[Any], plane_m: float, top_m: float) -> Tuple[Any, Dict[str, Any]]:
    """The trousers cut at ``plane_m`` (``footwear_cut.plane_cut``) with the ``tucked_poke`` gate's numbers."""
    from app.core.footwear_cut import plane_cut
    prim, stats = plane_cut(_mesh_prim(outer), y_m=plane_m)
    cut = _prim_mesh(prim, outer)
    return cut, {**tucked_poke(cut, shafts, plane_m, top_m), "cut": stats}


def _build(character_name: str, item_id: str, entry: Dict[str, Any], inner: Dict[str, Dict[str, Any]],
           base_sha: str, *, body: str = "") -> Path:
    """Push the body fit of ``item_id`` over the served meshes of ``inner`` (both tiers), graft it onto the
    rigged base and store it under its ``lsig`` with its record; prune the item's older layered fits. With a
    ``hem`` entry (module docstring) the boot's shaft nodes join the inners (``over``) or the trousers are cut
    at the plane (``tucked``; the ``over`` geometry with ``fallback`` when the leg does not fit)."""
    from app.core import garment_fit_layers as gfl
    from app.core import garment_store, glb_mesh
    from app.core.garments import _write_atomic
    from app.core.garment_set import CLOTHING
    from app.core.timeutils import utc_now_iso
    fsig, lsig = entry["fsig"], entry["lsig"]
    fit_bytes = Path(entry["fit"]).read_bytes()
    base_fit_sha = hashlib.sha256(fit_bytes).hexdigest()
    rigged = _rigged_base(character_name, entry["record"], base_sha, body)
    body_mesh = glb_mesh.body_arrays(rigged)
    outer_full = glb_mesh.garment_arrays(fit_bytes)
    outer_low = glb_mesh.garment_arrays(Path(entry["low"]).read_bytes()) if entry.get("low") else None
    inner_full = []
    for u in sorted(inner):
        data = Path(inner[u]["source"]).read_bytes()
        # The key names the inner fit the plan saw: one replaced meanwhile is layered over on the next build.
        if hashlib.sha256(data).hexdigest() != entry["inner"][u]:
            raise ValueError(f"the fit of {u} changed during the build")
        inner_full.append(glb_mesh.garment_arrays(data))
    inner_low = [glb_mesh.garment_arrays(Path(inner[u]["low"]).read_bytes()) if inner[u].get("low") else g
                 for u, g in zip(sorted(inner), inner_full)]
    hem = entry.get("hem")
    shafts: List[Any] = []
    hem_record: Optional[Dict[str, Any]] = None
    if hem:
        shafts = shaft_meshes(Path(hem["fit"]).read_bytes(), str(hem["boot"]))
        if shaft_sha(shafts) != entry["inner"].get(str(hem["boot"])):
            raise ValueError(f"the fit of {hem['boot']} changed during the build")
        hem_record = {"mode": hem["mode"], "built": "over", "plane_m": hem.get("plane_m"), "top_m": hem.get("top_m"),
                      "tucked_poke": None, "fallback": None, "boot": str(hem["boot"]),
                      "shaft_sha": entry["inner"].get(str(hem["boot"]))}
    # One body field for both tiers.
    sdf = gfl.layer_sdf(body_mesh, [outer_full, *inner_full, *shafts, *([outer_low] if outer_low else []), *inner_low])
    tucked = bool(hem_record and hem["mode"] == "tucked" and hem.get("plane_m") is not None)
    full, report = gfl.layer_over(outer_full, body_mesh, inner_full if tucked else [*inner_full, *shafts], sdf=sdf)
    low = low_report = None
    if outer_low is not None:
        low, low_report = gfl.layer_over(outer_low, body_mesh, inner_low if tucked else [*inner_low, *shafts], sdf=sdf)
    if tucked:
        cut_full, poke = _tuck(full, shafts, float(hem["plane_m"]), float(hem["top_m"]))
        hem_record.update(tucked_poke=poke["tucked_poke"], tucked_n=poke["n"], tucked_outside=poke["outside"],
                          cut=poke["cut"])
        if poke["tucked_poke"] > TUCKED_POKE_MAX:
            # too wide to tuck: the over geometry under the tucked lsig, the record says so (the Wardrobe warning)
            hem_record["fallback"] = HEM_FALLBACK_TOO_WIDE
            full, report = gfl.layer_over(outer_full, body_mesh, [*inner_full, *shafts], sdf=sdf)
            if outer_low is not None:
                low, low_report = gfl.layer_over(outer_low, body_mesh, [*inner_low, *shafts], sdf=sdf)
        else:
            hem_record["built"] = "tucked"
            full = cut_full
            if low is not None:
                low, _low_poke = _tuck(low, shafts, float(hem["plane_m"]), float(hem["top_m"]))
    name = f"garment_{CLOTHING}_{item_id}"
    extras = {"kind": CLOTHING, "item_id": item_id, "fsig": fsig, "over": sorted(entry["inner"])}
    if hem_record:
        extras["hem"] = hem_record["built"]
    path = garment_store.garment_path(character_name, item_id, fsig, "layer", lsig=lsig, body=body)
    low_path = garment_store.garment_path(character_name, item_id, fsig, "layer_low", lsig=lsig, body=body)
    low_blob = glb_mesh.graft(rigged, low, name=name, extras=extras) if low is not None else None
    blob = glb_mesh.graft(rigged, full, name=name, extras=extras)
    record = {
        "accepted": True, "kind": CLOTHING, "item_id": item_id, "fsig": fsig, "lsig": lsig,
        "layer_version": LAYER_VERSION,
        "base_signature": entry["record"].get("base_signature"),
        **({"body_id": body, "body_sha256": base_sha} if body
           else {"base_model_sha256": base_sha, "body_id": entry["record"].get("base_signature"),
                 "body_sha256": base_sha}),
        "base_fit_sha256": base_fit_sha,
        "inner": {**{u: {"fsig": inner[u]["fsig"], "sha256": entry["inner"][u], "lsig": inner[u]["lsig"] or None}
                     for u in sorted(inner)},
                  **({str(hem["boot"]): {"fsig": None, "sha256": entry["inner"][str(hem["boot"])], "lsig": None,
                                         "shaft": True}} if hem_record else {})},
        **({"hem": hem_record} if hem_record else {}),
        "report": {"full": report, "low": low_report}, "low": low_blob is not None,
        "created_at": utc_now_iso()}
    # The low tier first: a reader that sees the record also finds its tier (or none, then the full one).
    if low_blob is not None:
        _write_atomic(low_path, low_blob)
    else:
        low_path.unlink(missing_ok=True)
    _write_atomic(path, blob)
    garment_store.write_record(path.with_suffix(".json"), record)
    logger.info("Layered fit %s/%s over %s (%s): moved %s vertices, max %.1f mm, gap p1 %s", character_name,
                item_id, sorted(inner), lsig, report.get("moved"), 1000 * float(report.get("max_m") or 0.0),
                report.get("gap_p1_m"))
    _prune(character_name, item_id, fsig, base_fit_sha, keep=lsig, body=body)
    return path


def _prune(character_name: str, item_id: str, fsig: str, base_fit_sha: str, *, keep: str,
           body: str = "") -> List[str]:
    """Drop the layered fits of ``(item_id, fsig)`` on ``body`` (its folder only) made from another body fit,
    and beyond the newest ``LAYER_KEEP`` (``keep`` always stays). Returns the dropped lsigs."""
    from app.core import garment_store
    folder = garment_store.body_root(character_name, body) / garment_store.PART_DIRS["layer"]
    if not folder.is_dir():
        return []
    entries = []
    prefix = f"{item_id}_{fsig}_"
    for path in folder.glob(f"{prefix}*.glb"):
        if garment_store.parse_name(path) != (item_id, fsig):
            continue
        lsig = path.stem[len(prefix):]
        record = garment_store.read_record(path.with_suffix(".json"))
        try:
            mtime = path.stat().st_mtime_ns
        except OSError:
            continue
        entries.append((lsig != keep, record.get("base_fit_sha256") != base_fit_sha, -mtime, lsig))
    entries.sort()
    dropped = []
    for i, (not_kept, foreign, _mtime, lsig) in enumerate(entries):
        if not_kept and (foreign or i >= LAYER_KEEP):
            for part in ("layer", "layer_low"):
                p = garment_store.garment_path(character_name, item_id, fsig, part, lsig=lsig, body=body)
                p.unlink(missing_ok=True)
                p.with_suffix(".json").unlink(missing_ok=True)
            dropped.append(lsig)
    return dropped


def forget_failures(character_name: Optional[str] = None) -> None:
    """Drop the in-process memo of failed layer builds (smokes; a character's own)."""
    with _lock:
        for key in [k for k in _failed if character_name is None or k[0] == character_name]:
            _failed.pop(key, None)
