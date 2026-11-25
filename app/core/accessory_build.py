"""Per character × body builds of thin accessories (Ruling A118; spec
``docs/superpowers/specs/2026-11-16-accessories-design.md`` § 4–§ 7, plan Task 6).

An outfit piece in mode ``accessory`` (``garment_set.ACCESSORY``) with a ``jewellery`` description
(``accessory_spec``) is built on the CPU from the character's plain rigged body — 0 hub jobs. Phase P1 builds the
necklace: ``accessory_curve.neck_curve`` (on the skin, ``GAP_M`` + the tube radius off it) swept into a tube
(``accessory_mesh.tube``) skinned with the nearest body vertices' weights.

Store (per character)::

    <character>/jewellery/<item>_<asig>.npz   positions, faces, normals, joints, weights
    <character>/jewellery/<item>_<asig>.json  the record: asig, spec, base_model_sha256 (+ base_geometry_id),
                                              joint_names, metrics, landmarks, built_at

``asig`` = md5[:12] over the GEOMETRY inputs only (``geometry_inputs``: kind, chain, version) — the metal is a
material and re-assembles on the CPU without a rebuild. A record holds for the body it was built on
(``model_geometry.record_matches``: the same base file or the same geometry). ``accessory_state`` judges:

- ``current`` — a record of the current asig on the current body;
- ``due`` — with the reason in words: "body changed" (a record of this asig on another body), "chain settings
  changed" (a record of another asig), "not built yet";
- ``blocked`` — no kind chosen, a kind not built yet (a later phase), no plain body;
- ``failed`` — the last build of this asig on this body raised (``<item>_<asig>.failed.json``).

A ``due`` or ``failed`` state also names ``previous``: the newest stored build of another asig that holds for the
current body (``previous_record``) — the mesh delivered before the change. The figure keeps showing it with the note
``REASON_OUTDATED`` until the Build makes the current one (A224, ruling 4: a previously delivered piece mesh stays,
never a stand-in of another kind). The garment assembly grafts a current build — or that previous one — as the node
``accessory_mesh.node_name`` (``garment_assembly``).
"""
import functools
import hashlib
import json
import re
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

#: Bumped when an accessory is built differently for the same inputs. 3: the test poses judge a side by the body's
#: outer wall only (``outer_wall_faces``) — a belt over a bent hip no longer fails on the inner wall, a piece pushed
#: through the skin is caught at its true depth. 4: linked part items (plan-anhaenger, design G) — a part is placed by
#: its link with its thinnest side as the depth. 5: a part's depth is the axis whose two others match its image's
#: outline (``accessory_pendant.orient``), its size the longer front side, and a flat part is cut to
#: ``FLAT_DEPTH_SHARE`` of its size behind its front (a mesher's invented loop or prong no longer stands off the band).
ACCESSORY_VERSION = 5
#: A234: the build version of the kinds around the body / on a bone (``make_around``, ``make_earrings``). 2: a choker
#: sits on a garment only where it hugs the neck (``accessory_band.UNDER_MAX_BY_KEY``).
AROUND_VERSION = 2
#: The air between the skin and the chain's surface. The plan's 1.5 mm left one ring of Lirien's chain at 0.94 mm
#: in the sit clip (A216 acceptance: rest 1.50–2.57 mm, sit min 0.94 mm); 1.7 mm keeps every ring inside the
#: 1–3 mm band in rest, walk and sit (the skinning moves a ring by at most ~0.6 mm there).
GAP_M = 0.0017
#: The folder of the builds in a character's directory.
DIR_NAME = "jewellery"

#: ``accessory_state`` reasons (English words, shown in the Wardrobe and the Figure tab).
REASON_NOT_BUILT = "Not built yet — Build makes it on the CPU (0 hub jobs)"
REASON_BODY = "Body changed — Build makes it again on the CPU (0 hub jobs)"
REASON_SETTINGS = "Chain settings changed — Build makes it again on the CPU (0 hub jobs)"
REASON_SETTINGS_PIECE = "Settings changed — Build makes it again on the CPU (0 hub jobs)"
#: A234: the layer under a band changed (another garment worn, refitted, or the chest shaping changed).
REASON_UNDER = "The clothing under it changed — Build fits it again on the CPU (0 hub jobs)"
REASON_NO_KIND = "Choose the accessory kind in the Wardrobe"
REASON_KIND_LATER = "{kind}: not built yet in this version — shown on the figure once its phase lands"
REASON_NO_BODY = "No plain body yet"
REASON_FAILED = "Build failed — {error}"
REASON_PENDANT_LEFT_OFF = "Drop left off — {error}"
REASON_PENDANT = "Drop ready — Build puts it on on the CPU (0 hub jobs)"
#: Design G: a linked part's mesh became ready since the host was built.
REASON_PART = "A linked part was built since — rebuild (CPU)"
REASON_PART_LEFT_OFF = "{role} left off — {error}"
#: A224: the figure's note of an accessory shown with its previously delivered build (``previous_record``).
REASON_OUTDATED = "Outdated — Build makes it again (0 hub jobs)"


def _profile_of(character_name: str, profile: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if profile is not None:
        return profile
    from app.models.character import get_character_profile
    return get_character_profile(character_name) or {}


def store_dir(character_name: str) -> Path:
    from app.models.character import get_character_dir
    return get_character_dir(character_name) / DIR_NAME


def shape_inputs(spec: Dict[str, Any]) -> Dict[str, Any]:
    """A234: the shape fields of a kind other than the necklace (the metal / band colour is a material, not here)."""
    kind = spec["kind"]
    band = spec["band"]
    if kind in ("belt", "choker", "strap"):
        out: Dict[str, Any] = {"height_cm": band["height_cm"], "width_cm": band["width_cm"], "layer": band["layer"],
                               "material": band["material"]}
        if kind == "strap":
            out["at"] = band["at"]
            if band["at"] != "chest":
                out["side"] = spec["side"]
        return out
    if kind in ("anklet", "bracelet"):
        return {"height_cm": band["height_cm"], "thickness_mm": spec["chain"]["thickness_mm"], "side": spec["side"],
                "layer": band["layer"]}
    if kind == "ring":
        # A238: sized from the skeleton — no layer under it, no height (``ring.along`` places it)
        return {"finger": spec["finger"], "side": spec["side"], "along": spec["ring"]["along"],
                "width_cm": band["width_cm"], "thickness_mm": spec["chain"]["thickness_mm"]}
    if kind == "earrings":
        return {"earring": dict(spec["earring"]), "thickness_mm": spec["chain"]["thickness_mm"], "side": spec["side"]}
    if kind == "glasses":
        # the lenses' tint, opacity and mirror are a material (``material_key``), not the geometry
        g = spec["glasses"]
        return {k: g[k] for k in ("shape", "size", "rim_mm", "frame", "temple")}
    return {}


def geometry_inputs(spec: Dict[str, Any], parts_ready: Optional[List[list]] = None,
                    context: Optional[Dict[str, Any]] = None, drop_psig: str = "") -> Dict[str, Any]:
    """What an accessory's GEOMETRY is made of (the metal is not). Design G: the READY linked parts
    (``parts_ready`` = ``accessory_parts.ready_inputs``: ``[role, index, item, psig, size_mm, at_deg, mount, drop_cm,
    flip]``) — a part not built yet is not (the host alone is built and shown). A234: the other kinds' shape fields
    (``shape_inputs``), the earrings' READY own drop (``drop_psig``) and its size, and the worn context
    (``worn_context``): the garments under a band (``[item, fsig]``) and the chest shaping."""
    from app.core.accessory_spec import image_part_mm
    inputs: Dict[str, Any] = {"version": ACCESSORY_VERSION, "kind": spec["kind"]}
    if spec["kind"] == "necklace":
        inputs["chain"] = dict(spec["chain"])
    else:
        inputs["around"] = AROUND_VERSION
        inputs["shape"] = shape_inputs(spec)
    if drop_psig and image_part_mm(spec) is not None:
        inputs["pendant"] = {"psig": drop_psig, "size_mm": float(image_part_mm(spec))}
    if parts_ready:
        inputs["parts"] = [list(p) for p in parts_ready]
    context = context or {}
    if context.get("under"):
        inputs["under"] = [[str(u["item_id"]), str(u["fsig"])] for u in context["under"]]
    if context.get("shaping"):
        inputs["shaping"] = shaping_key(context["shaping"])
    return inputs


def shaping_key(rec: Dict[str, Any]) -> str:
    """md5[:12] of a chest shaping record (``bust_shaping.record``)."""
    return hashlib.md5(json.dumps(rec, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:12]


def asig(spec: Dict[str, Any], parts_ready: Optional[List[list]] = None, context: Optional[Dict[str, Any]] = None,
         drop_psig: str = "") -> str:
    """md5[:12] of ``geometry_inputs`` (canonical JSON)."""
    raw = json.dumps(geometry_inputs(spec, parts_ready, context, drop_psig), sort_keys=True,
                     separators=(",", ":")).encode("utf-8")
    return hashlib.md5(raw).hexdigest()[:12]


#: A234: the kinds the chest shaping (A228, ``bust_shaping``) moves the skin under — they are fitted on the shaped
#: body and keyed by the shaping (A228 L7).
SHAPED_KINDS = ("necklace",)


def _keyed_by_shaping(spec: Dict[str, Any]) -> bool:
    return spec["kind"] in SHAPED_KINDS or (spec["kind"] == "strap" and spec["band"]["at"] == "chest")


def _wants_under(spec: Dict[str, Any]) -> bool:
    return spec["kind"] not in ("necklace", "earrings", "ring", "glasses") and spec["band"]["layer"] == "auto"


def worn_context(character_name: str, profile: Dict[str, Any], base_sha: str,
                 spec: Dict[str, Any]) -> Dict[str, Any]:
    """A234: what a piece is fitted over in the worn set of ``profile`` (``equipped_pieces``) on the plain body
    ``base_sha``: ``under`` — per worn own-mesh / template piece on one of the region's slots
    (``accessory_band.UNDER_SLOTS``) with a fit / drape on this body, ``{item_id, fsig, path, slots, footwear}`` (sorted
    by item id; only for ``band.layer: auto``); ``shaping`` — the chest shaping of the worn template drapes
    (``bust_shaping.worn_record``) for the kinds near the chest. Read-only; a piece whose fit cannot be read is
    skipped (never a failure)."""
    out: Dict[str, Any] = {"under": [], "shaping": None}
    want_under, want_shaping = _wants_under(spec), _keyed_by_shaping(spec)
    if not (want_under or want_shaping) or not base_sha:
        return out
    from app.core import accessory_band, garment_set, garment_store, garment_template
    from app.models.inventory import get_item
    pieces = profile.get("equipped_pieces") or {}
    ids = sorted({str(i).strip() for i in pieces.values() if i and str(i).strip()})
    items = {i: (get_item(i) or {}) for i in ids}
    mesh_ids = [i for i in ids if garment_set.mesh_mode_of(items[i]) in (*garment_set.OWN_MESH_MODES,
                                                                         garment_set.TEMPLATE)]
    # owner ruling 2: a bra hidden under a top with cups is in neither figure — nothing is fitted over it
    hidden = garment_template.hidden_by_cups([i for i in mesh_ids
                                              if garment_set.mesh_mode_of(items[i]) == garment_set.TEMPLATE])
    mesh_ids = [i for i in mesh_ids if i not in hidden]
    region = set(accessory_band.UNDER_SLOTS.get(accessory_band.region_key(spec), ()))
    drapes = []
    for item_id in mesh_ids:
        item = items[item_id]
        slots = [str(x) for x in ((item.get("outfit_piece") or {}).get("slots") or [])]
        try:
            if garment_set.mesh_mode_of(item) == garment_set.TEMPLATE:
                drape = garment_template.drape_state(character_name, item_id, base_sha=base_sha,
                                                     lower=garment_template.lower_layers(mesh_ids, item_id), item=item)
                if drape.get("state") != "ready":
                    continue
                drapes.append({"template": True, "record": drape.get("record") or {}})
                path, fsig = drape["path"], str(drape["tsig"])
            else:
                fit = garment_store.accepted_fit(character_name, item_id, base_model_sha=base_sha, profile=profile)
                parsed = garment_store.parse_name(fit[0]) if fit else None
                if not parsed:
                    continue
                path, fsig = fit[0], parsed[1]
        except Exception:  # noqa: BLE001 — a piece not judged is not under the band
            logger.debug("Accessory context: %s of %s unreadable", item_id, character_name, exc_info=True)
            continue
        if want_under and region & set(slots):
            out["under"].append({"item_id": item_id, "fsig": fsig, "path": str(path), "slots": slots,
                                 "footwear": garment_set.garment_kind_of(item) == garment_set.FOOTWEAR})
    if want_shaping:
        from app.core import bust_shaping
        out["shaping"] = bust_shaping.worn_record(drapes)
    return out


def pendant_info(item_id: str, spec: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """``accessory_pendant.pendant_state`` of the item's OWN drop (the earrings' ``drop`` style — the only item-image
    part left since part items, D1), else None."""
    from app.core import accessory_pendant, accessory_spec
    if not accessory_spec.pendant_on(spec):
        return None
    try:
        return accessory_pendant.pendant_state(item_id)
    except ValueError:
        return None


def pendant_row(state: Dict[str, Any], spec: Optional[Dict[str, Any]], record: Optional[Dict[str, Any]]
                ) -> Optional[Dict[str, Any]]:
    """The earrings' own drop line of a Wardrobe / Figure row — ``{state, reason, size_mm, on_figure, metrics, cost}``,
    None without a drop. ``state`` is the mesh's (``accessory_pendant.pendant_state``); ``on_figure`` whether the
    CURRENT build carries it; ``reason`` says why the earrings are shown without it."""
    pendant = state.get("pendant")
    if not pendant or not spec:
        return None
    record = record or {}
    on = isinstance(record.get("pendant"), dict) and state.get("state") == "current"
    reason = pendant["reason"]
    if pendant["state"] == "ready" and not on:
        reason = record.get("pendant_error") or (REASON_PENDANT if state.get("state") != "current" else "")
    return {"state": pendant["state"], "reason": reason, "size_mm": float(accessory_spec_size(spec)),
            "on_figure": on, "metrics": (record.get("pendant") or {}).get("metrics") if on else None,
            "cost": {"hub_jobs": 0 if pendant["state"] == "ready" else 1}}


def part_rows(state: Dict[str, Any], spec: Optional[Dict[str, Any]], record: Optional[Dict[str, Any]]
              ) -> List[Dict[str, Any]]:
    """Design G: one line per part link of a Wardrobe / Figure / Items row — ``{role, index, item, part_name, state,
    reason, size_mm, mount, at_deg, drop_cm, flip, on_figure, metrics, cost, image_url}``. ``state`` is the part
    mesh's (or ``gone``); ``on_figure`` whether the CURRENT build carries it; ``reason`` why it is not shown."""
    from app.core import accessory_spec
    record = record or {}
    current = state.get("state") == "current"
    built = {(p.get("role"), int(p.get("index", 0)), p.get("item")): p for p in record.get("parts") or []}
    errors = record.get("part_errors") or {}
    rows = []
    for ps in state.get("parts") or []:
        key = (ps["role"], int(ps["index"]), ps["item"])
        on = current and key in built and built[key].get("psig") == ps["psig"]
        reason = ps["reason"]
        if ps["state"] == "ready" and not on:
            err = errors.get(f"{ps['role']}:{ps['index']}")
            reason = (REASON_PART_LEFT_OFF.format(role=accessory_spec.ROLE_NAMES.get(ps["role"], "Part"), error=err)
                      if err and current else ("" if current else REASON_PART))
        rows.append({"role": ps["role"], "index": int(ps["index"]), "item": ps["item"], "part_name": ps["part_name"],
                     "state": ps["state"], "reason": reason, "size_mm": ps.get("size_mm"), "mount": ps.get("mount"),
                     "at_deg": ps.get("at_deg"), "drop_cm": ps.get("drop_cm"), "flip": bool(ps.get("flip")),
                     "on_figure": bool(on), "metrics": (built[key].get("metrics") if on else None),
                     "cost": {"hub_jobs": 0 if ps["state"] in ("ready", "gone", "no_image") else 1},
                     "image_url": (f"/inventory/items/{ps['item']}/image" if ps["state"] not in ("gone", "no_image")
                                   else "")})
    return rows


def accessory_spec_size(spec: Dict[str, Any]) -> float:
    from app.core.accessory_spec import image_part_mm
    return float(image_part_mm(spec) or 0.0)


def _ready_psig(pendant: Optional[Dict[str, Any]]) -> str:
    return str(pendant["psig"]) if pendant and pendant.get("state") == "ready" else ""


def record_path(character_name: str, item_id: str, sig: str, suffix: str = ".json") -> Path:
    return store_dir(character_name) / f"{item_id}_{sig}{suffix}"


def _read(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _records(character_name: str, item_id: str) -> Dict[str, Dict[str, Any]]:
    """asig -> record of every stored build of ``item_id`` (failure records excluded)."""
    folder = store_dir(character_name)
    out: Dict[str, Dict[str, Any]] = {}
    if not folder.is_dir():
        return out
    prefix = f"{item_id}_"
    for path in folder.glob(f"{item_id}_*.json"):
        name = path.name[len(prefix):-len(".json")]
        if "." in name or len(name) != 12:
            continue
        rec = _read(path)
        if rec and path.with_suffix(".npz").is_file():
            out[name] = rec
    return out


def material_key(item: Optional[Dict[str, Any]]) -> str:
    """The material identity of an accessory (``metal`` + colour + roughness): a change re-assembles, never rebuilds."""
    from app.core import accessory_spec
    spec = accessory_spec.of_item(item)
    if spec is None:
        return ""
    color, rough, metal = piece_material(spec, str((item or {}).get("id") or ""))
    band = f"{spec['band']['material']}:" if spec["kind"] in BAND_KINDS else ""
    if spec["kind"] == "glasses":
        # the frame's material and the lenses' (tint, opacity, mirror) re-assemble, never rebuild
        lens = accessory_spec.lens_material(spec)
        band = (f"{spec['glasses']['frame']}:lens={lens['color']}/{lens['opacity']}/"
                f"{int(lens['mirror'])}:")
    return f"accessory:{spec['metal']}:{band}{color}:{rough}:{metal}"


#: A234: the kinds whose material is the band's (``band.material``), not the chain's metal.
BAND_KINDS = ("belt", "choker", "strap")
#: The band colour ``from_image`` takes when the item has no usable image.
BAND_FALLBACK = "leather"


def piece_material(spec: Dict[str, Any], item_id: str = "") -> tuple:
    """``(colour hex, roughness, metalness)`` of a built piece: the chain's metal (``accessory_spec.metal_material``),
    the glasses' frame (``accessory_spec.frame_material``), or for a band (A234) its ``band.material`` — leather / fabric presets, ``metal`` the chosen metal,
    ``from_image`` the item image's median colour with the leather finish (``image_colour``)."""
    from app.core import accessory_spec
    if spec.get("kind") == "glasses":
        return accessory_spec.frame_material(spec)
    if spec.get("kind") not in BAND_KINDS:
        return accessory_spec.metal_material(spec)
    material = spec["band"]["material"]
    if material == "metal":
        return accessory_spec.metal_material(spec)
    if material == "from_image":
        _c, rough, metal = accessory_spec.METAL_PRESETS[BAND_FALLBACK]
        colour = image_colour(item_id) if item_id else ""
        return (colour or _c), rough, metal
    return accessory_spec.METAL_PRESETS[material]


def image_colour(item_id: str) -> str:
    """The median colour (sRGB hex) of the item image's subject — the pixels neither transparent nor near-white /
    near-black background — '' without an image or a subject."""
    from app.core.accessory_pendant import _item_image
    path = _item_image(item_id)
    if path is None:
        return ""
    try:
        st = path.stat()
        return _image_colour_cached(str(path), st.st_mtime_ns, st.st_size)
    except OSError:
        return ""


@functools.lru_cache(maxsize=64)
def _image_colour_cached(path: str, _mtime: int, _size: int) -> str:
    from PIL import Image
    with Image.open(path) as im:
        im = im.convert("RGBA")
        im.thumbnail((128, 128))
        px = np.asarray(im, np.float64).reshape(-1, 4)
    rgb = px[:, :3]
    keep = (px[:, 3] > 128) & (rgb.max(1) < 235) & (rgb.max(1) > 20)
    if keep.sum() < 20:
        return ""
    m = np.median(rgb[keep], axis=0)
    return "#" + "".join(f"{int(round(c)):02x}" for c in m)


def _current_base(character_name: str, profile: Dict[str, Any]):
    from app.core import base_body
    base = base_body.current_base(character_name, profile=profile)
    if not base or not base[1]:
        return None
    return base


def base_sha(character_name: str, profile: Optional[Dict[str, Any]] = None) -> str:
    """The content sha of the current plain body ('' without one) — the preview's cache key (A216 review L2)."""
    base = _current_base(character_name, _profile_of(character_name, profile))
    return str(base[1]) if base else ""


def accessory_state(character_name: str, item_id: str, *, profile: Optional[Dict[str, Any]] = None,
                    item: Optional[Dict[str, Any]] = None,
                    context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """``{state, reason, asig, record, pendant, parts, context}`` of a worn accessory (module docstring; ``pendant`` =
    ``pendant_info`` — the earrings' own drop; ``parts`` = ``accessory_parts.part_states`` — the linked parts;
    ``context`` = ``worn_context``, read from the profile when not given). Read-only."""
    from app.core import accessory_parts, accessory_spec, model_geometry
    profile = _profile_of(character_name, profile)
    if item is None:
        from app.models.inventory import get_item
        item = get_item(item_id) or {}
    spec = accessory_spec.of_item(item)
    if spec is None:
        return {"state": "blocked", "reason": REASON_NO_KIND, "asig": "", "record": None}
    if spec["kind"] not in accessory_spec.BUILT_KINDS:
        return {"state": "blocked", "reason": REASON_KIND_LATER.format(kind=spec["kind"].capitalize()),
                "asig": "", "record": None}
    base = _current_base(character_name, profile)
    parts = accessory_parts.part_states(spec)
    if base is None:   # the links are listed without a body too (they are picked before anything is built)
        return {"state": "blocked", "reason": REASON_NO_BODY, "asig": "", "record": None, "parts": parts}
    pendant = pendant_info(item_id, spec)
    ready = accessory_parts.ready_inputs(parts)
    if context is None:
        context = worn_context(character_name, profile, str(base[1]), spec)
    sig = asig(spec, ready, context, _ready_psig(pendant))
    records = _records(character_name, item_id)
    rec = records.get(sig)
    out = {"asig": sig, "pendant": pendant, "parts": parts, "context": context}
    if rec is not None and model_geometry.record_matches(rec, base[1]):
        return {"state": "current", "reason": "", "record": rec, **out}
    failed = _read(record_path(character_name, item_id, sig, ".failed.json"))
    if failed and failed.get("base_model_sha256") == base[1]:
        return {"state": "failed", "reason": REASON_FAILED.format(error=failed.get("error") or "unknown"),
                "record": None, "previous": previous_record(character_name, item_id, base_sha=base[1], skip=sig),
                **out}
    out["previous"] = previous_record(character_name, item_id, base_sha=base[1], skip=sig)
    if rec is not None:
        return {"state": "due", "reason": REASON_BODY, "record": None, **out}
    if records:
        want = geometry_inputs(spec, ready, context, _ready_psig(pendant))
        shape_keys = ("version", "kind", "chain", "around", "shape")
        same_shape = [r for r in records.values()
                      if all((r.get("inputs") or {}).get(k) == want.get(k) for k in shape_keys)]
        lost = [p for p in parts if p["state"] != "ready"
                and any([p["role"], p["index"], p["item"]] == q[:3]
                        for r in same_shape for q in (r.get("inputs") or {}).get("parts") or [])]
        if _ready_psig(pendant) and any("pendant" not in (r.get("inputs") or {}) for r in same_shape):
            reason = REASON_PENDANT
        elif lost:
            # a part the last build carried is no longer ready (a new image, deleted): its own words
            reason = lost[0]["reason"]
        elif ready and any((r.get("inputs") or {}).get("parts") != want.get("parts") for r in same_shape):
            reason = REASON_PART
        elif same_shape:
            reason = REASON_UNDER
        else:
            reason = REASON_SETTINGS if spec["kind"] == "necklace" else REASON_SETTINGS_PIECE
        return {"state": "due", "reason": reason, "record": None, **out}
    return {"state": "due", "reason": REASON_NOT_BUILT, "record": None, **out}


def previous_record(character_name: str, item_id: str, *, base_sha: str, skip: str = "") -> Optional[Dict[str, Any]]:
    """The newest stored build of ``item_id`` (other than the asig ``skip``) that holds for the body of content
    ``base_sha`` (``model_geometry.record_matches``): the mesh delivered before its settings changed. None without
    one. Read-only."""
    from app.core import model_geometry
    best: Optional[Dict[str, Any]] = None
    best_mtime = -1
    for sig, rec in _records(character_name, item_id).items():
        if sig == skip or not model_geometry.record_matches(rec, base_sha):
            continue
        try:
            mtime = record_path(character_name, item_id, sig, ".npz").stat().st_mtime_ns
        except OSError:
            continue
        if mtime > best_mtime:
            best, best_mtime = rec, mtime
    return best


def _write_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def make_necklace(rigged: bytes, spec: Dict[str, Any], parts: Optional[List[Any]] = None) -> Dict[str, Any]:
    """The necklace geometry on the rigged plain body ``rigged`` (GLB bytes): ``{V, F, N, J, W, joint_names, curve,
    landmarks, metrics, parts, part_errors}``. ``parts``: ``[(link, mesh)]`` — the linked pendant (``link`` with its
    effective ``size_mm`` / ``flip``; ``mesh`` = ``accessory_pendant.load_mesh``), hung at the chain's lowest point
    (``attach_pendant``); ``out["parts"]`` = ``[hung | None]``, ``out["part_errors"]`` = ``{index: reason}``. Pure CPU,
    no I/O beyond the bytes given."""
    from app.core import accessory_curve, accessory_mesh, glb_mesh
    from app.core.garment_fit import dense_weights
    started = time.monotonic()
    body = glb_mesh.body_arrays(rigged)
    radius = float(spec["chain"]["thickness_mm"]) / 2000.0
    detail = accessory_curve.neck_curve_detail(body.positions, body.faces, body.joint_positions,
                                               drop_m=float(spec["chain"]["drop_cm"]) / 100.0,
                                               offset_m=GAP_M + radius)
    curve = np.asarray(detail["curve"])
    surface = np.asarray(detail["surface"])
    V, F, N = accessory_mesh.tube(curve, radius, outward=curve - surface)
    J, W = accessory_mesh.skin_weights(V, np.asarray(body.positions, np.float64), dense_weights(body))
    J, W = accessory_mesh.fold_to_base(J, W, list(body.joint_names), glb_mesh.skin_joint_parents(rigged))
    Pw, skin = detail["welded"]
    metrics = gap_metrics(V, len(curve), Pw, skin, outward=np.asarray(detail["outward"]))
    seg = np.linalg.norm(np.diff(np.vstack([curve, curve[:1]]), axis=0), axis=1)
    metrics.update({"triangles": int(len(F)), "vertices": int(len(V)),
                    "length_m": round(float(seg.sum()), 4),
                    "max_segment_ratio": round(float(seg.max() / max(float(np.median(seg)), 1e-9)), 2),
                    "neck_ellipse_m": detail["landmarks"]["neck_ellipse_m"],
                    "joints": {str(body.joint_names[j]): round(float(W[J == j].max()), 3)
                               for j in np.unique(J[W > PLAUSIBLE_WEIGHT])},
                    "cpu_s": round(time.monotonic() - started, 2)})
    plausible(metrics, float(spec["chain"]["drop_cm"]) / 100.0)
    out = {"V": V, "F": F, "N": N, "J": J, "W": W, "joint_names": list(body.joint_names), "curve": curve,
           "landmarks": detail["landmarks"], "metrics": metrics}
    out["parts"], out["part_errors"] = [], {}
    for i, (link, mesh) in enumerate(parts or []):
        try:
            out["parts"].append(attach_pendant(body, rigged, curve, np.asarray(detail["outward"]), J, W, radius,
                                               mesh, float(link.get("size_mm") or 18.0), bool(link.get("flip"))))
        except ValueError as e:
            # The chain stays; the pendant is left off with its reason (A225).
            out["parts"].append(None)
            out["part_errors"][i] = str(e)
    return out


#: A225 — the pendant's gates on the body: its longer front side within ``SIZE_TOLERANCE`` of ``size_mm``, at most
#: ``PENDANT_MAX_PUSH_MM`` off its cord and nothing inside the body in any ``accessory_pendant.TEST_POSES`` pose.
SIZE_TOLERANCE = 0.05
#: How far the pendant may be pushed off its cord to clear the body (a pendant too long for the drop meets the
#: throat or the chest and would float in the air).
PENDANT_MAX_PUSH_MM = 6.0
PENDANT_OFF_CORD = ("it would stand {mm:.0f} mm off its cord to clear the body — a longer drop or a smaller size "
                    "lets it hang")
PENDANT_INSIDE = "it would sink into the body in the {poses} pose"


def anchor_index(curve: np.ndarray) -> int:
    """The chain's lowest point (where the pendant hangs): the curve point with the smallest y."""
    return int(np.argmin(np.asarray(curve)[:, 1]))


def attach_pendant(body, rigged: bytes, curve: np.ndarray, outward: np.ndarray, J: np.ndarray, W: np.ndarray,
                   radius: float, pendant: Dict[str, Any], size_mm: float, flip: bool = False) -> Dict[str, Any]:
    """The pendant hung at the chain's lowest point (``accessory_pendant.place``), rigid with the chain's skin there
    (the first tube vertex of that ring — the tube's weights are already folded onto the base skeleton), checked
    through the test poses against the body's outer wall (``outer_wall_faces``). ``{V, F, N, UV, J, W, image, mime, material, metrics}``; ``ValueError`` naming why it is
    left off."""
    from app.core import accessory_curve, accessory_pendant, glb_mesh
    from app.core.garment_fit import dense_weights
    from app.core.garment_shell import top4_weights
    from app.core.rig_contract import norm_bone_name
    a = anchor_index(curve)
    outline = accessory_pendant.front_reason(pendant["V"], pendant.get("front_ratio"))
    if outline:
        raise ValueError(outline)
    Vn = accessory_pendant.normalise(pendant["V"], size_mm, flip, pendant.get("front_ratio"))
    Pw, Fw = accessory_curve.weld(np.asarray(body.positions, np.float64), np.asarray(body.faces, np.int64))
    # The pendant hangs in FRONT of the cord (its bail around it): its back starts one cord radius out.
    n = np.asarray(outward[a], np.float64)
    hang = curve[a] + radius * n / max(float(np.linalg.norm(n)), 1e-12)
    V, how = accessory_pendant.place(Vn, hang, outward[a], Pw, Fw)
    R = how.pop("rotation")
    if how["push_mm"] > PENDANT_MAX_PUSH_MM:
        raise ValueError(PENDANT_OFF_CORD.format(mm=how["push_mm"]))
    sides = len(J) // len(curve)
    Jp = np.repeat(J[a * sides][None], len(V), 0)
    Wp = np.repeat(W[a * sides][None], len(V), 0)
    # The longer front side in the pendant's own frame (its box turned back): the size the user set.
    local = (V - hang) @ R
    measured = float((local.max(0) - local.min(0))[:2].max()) * 1000.0
    if abs(measured - size_mm) > SIZE_TOLERANCE * size_mm:
        raise ValueError(f"its size came out {measured:.1f} mm instead of {size_mm:.0f} mm")
    # The body posed with its own skin: dense weights reduced to four per vertex.
    Jb, Wb, used = top4_weights(dense_weights(body))
    Jb = used[Jb]
    parents = glb_mesh.skin_joint_parents(rigged)
    heads = {norm_bone_name(k): v for k, v in body.joint_positions.items()}
    # The welded body and the skin of each welded vertex (``weld`` keeps the first vertex of each position).
    from scipy.spatial import cKDTree
    _, first = cKDTree(np.asarray(body.positions, np.float64)).query(Pw)
    Fo = Fw[outer_wall_faces(Pw, Fw, body.joint_positions, parents)]
    poses = accessory_pendant.pose_check(Pw, Fo, Jb[first], Wb[first], V, Jp, Wp, list(body.joint_names), parents,
                                         heads)
    inside = [name for name, m in poses.items() if m["inside_share"] > 0.0]
    if inside:
        raise ValueError(PENDANT_INSIDE.format(poses=", ".join(inside)))
    F = np.asarray(pendant["F"], np.int64)
    N = accessory_curve.vertex_normals(V, F)
    weights = {str(body.joint_names[j]): round(float(Wp[0][k]), 3) for k, j in enumerate(Jp[0]) if Wp[0][k] > 0}
    metrics = {"size_mm": round(measured, 2), "anchor": [round(float(x), 5) for x in hang], **how,
               "triangles": int(len(F)), "joints": weights, "poses": poses}
    return {"V": V, "F": F, "N": N, "UV": np.asarray(pendant["UV"], np.float64), "J": Jp, "W": Wp,
            "image": pendant.get("image") or b"", "mime": pendant.get("mime") or "",
            "material": pendant.get("material") or {}, "metrics": metrics}


#: The plausibility gate (A216 review H2) — a chain that misses one of these fails its build instead of being shown:
#: length at most ``LENGTH_PER_NECK`` × the neck ellipse (side points + notch + back, ``neck_ellipse_m``) +
#: ``LENGTH_PER_DROP`` × the drop (a U hanging the drop below the notch adds about twice the drop) and at least the
#: ellipse × ``LENGTH_MIN_PER_NECK``;
#: no segment longer than ``MAX_SEGMENT_RATIO`` × the median (a jump to hair or a shoulder); weight above
#: ``PLAUSIBLE_WEIGHT`` only on the neck, the spine and the shoulders (the head / jaw up to ``HEAD_WEIGHT_MAX``,
#: never an arm); nothing inside. ``metrics["joints"]``: joint -> its largest weight on the chain.
LENGTH_PER_NECK = 1.35
LENGTH_PER_DROP = 2.6
LENGTH_MIN_PER_NECK = 0.9
MAX_SEGMENT_RATIO = 3.0
PLAUSIBLE_WEIGHT = 0.2
PLAUSIBLE_JOINTS = frozenset({"neck", "spine", "spine1", "spine2", "leftshoulder", "rightshoulder"})
#: The head and the jaw may move a stretch of the chain by at most this weight: the skin just under the chin follows
#: the head a little (moving that weight to the neck pressed Lirien's chain to 0.85 mm in the sit clip), a chain
#: riding ON the jaw is wrong.
HEAD_WEIGHT_MAX = 0.5
HEAD_JOINTS = frozenset({"head", "jaw"})
IMPLAUSIBLE = "The chain does not fit this body ({why})"


def plausible(metrics: Dict[str, Any], drop_m: float) -> None:
    """Raise ``ValueError`` (``IMPLAUSIBLE``) when ``metrics`` of a built necklace break the gate above."""
    from app.core.rig_contract import norm_bone_name
    why = []
    neck = float(metrics["neck_ellipse_m"])
    length = float(metrics["length_m"])
    if length > LENGTH_PER_NECK * neck + LENGTH_PER_DROP * drop_m:
        why.append(f"{length:.2f} m long for a {neck:.2f} m neck")
    if length < LENGTH_MIN_PER_NECK * neck:
        why.append(f"{length:.2f} m is shorter than the {neck:.2f} m neck")
    if float(metrics["max_segment_ratio"]) > MAX_SEGMENT_RATIO:
        why.append("it jumps between two points")
    others = [j for j, w in metrics["joints"].items() if norm_bone_name(j) not in PLAUSIBLE_JOINTS
              and not (norm_bone_name(j) in HEAD_JOINTS and w <= HEAD_WEIGHT_MAX)]
    if others:
        why.append("it would move with " + ", ".join(norm_bone_name(j) for j in others))
    if float(metrics["inside_share"]) > 0.0:
        why.append("part of it lies inside the body")
    if why:
        raise ValueError(IMPLAUSIBLE.format(why="; ".join(why)))


def gap_metrics(V: np.ndarray, rings: int, P: np.ndarray, F: np.ndarray,
                outward: Optional[np.ndarray] = None) -> Dict[str, Any]:
    """The tube's air to the skin: per ring (``rings`` rings of ``len(V) / rings`` vertices) the smallest signed
    distance of its vertices to the body ``(P, F)`` — p05 / p50 / p95 / min in mm — and the share of tube vertices
    more than 0.5 mm inside the skin (``inside_share``). ``outward`` (per ring, the skin's normal under it): ``F`` is
    the skin patch under the chain and the sign comes from that normal; else ``F`` is the whole closed body
    (``garment_shell.signed_distance``)."""
    if outward is None:
        from app.core.accessory_curve import weld
        from app.core.garment_shell import signed_distance
        Pw, Fw = weld(np.asarray(P, np.float64), np.asarray(F, np.int64))
        sd = signed_distance(np.asarray(V, np.float64), Pw, Fw)
    else:
        # The skin patch has no inside of its own: per ring its CENTRE's distance to the skin, signed by the ring's
        # outward normal, minus the tube radius (exact for a flat skin; a vertex's own closest point can sit on an
        # edge of a crease beside the chain, where a face's plane gives the wrong side).
        from scipy.spatial import cKDTree
        from app.core.accessory_curve import _closest
        Pf = np.asarray(P, np.float64)
        Fs = np.asarray(F, np.int64)
        X = np.asarray(V, np.float64).reshape(rings, -1, 3)
        centre = X.mean(1)
        radius = np.linalg.norm(X - centre[:, None], axis=2).mean(1)
        cp = _closest(centre, Pf, Fs, cKDTree(Pf[Fs].mean(1)))
        side = np.einsum("ij,ij->i", centre - cp, np.asarray(outward))
        sd = (np.linalg.norm(centre - cp, axis=1) * np.where(side < 0, -1.0, 1.0) - radius)[:, None]
    sd = sd.reshape(rings, -1)
    gap = sd.min(1) * 1000.0
    return {"gap_mm": {"p05": round(float(np.percentile(gap, 5)), 2), "p50": round(float(np.median(gap)), 2),
                       "p95": round(float(np.percentile(gap, 95)), 2), "min": round(float(gap.min()), 2)},
            "inside_share": round(float((sd < -0.0005).mean()), 4)}


def drop_other_builds(folder: Path, item_id: str, sig: str) -> List[str]:
    r"""Delete the files of ``item_id``'s builds other than ``sig`` in ``folder`` — names matching exactly
    ``^<item_id>_<12 hex>\.`` (A216 review L1: never another item whose id starts with this one); the deleted
    names."""
    own = re.compile(rf"^{re.escape(item_id)}_([0-9a-f]{{12}})\.")
    gone = []
    for other in sorted(folder.iterdir()):
        m = own.match(other.name)
        if m and m.group(1) != sig:
            other.unlink(missing_ok=True)
            gone.append(other.name)
    return gone


def failure_text(e: BaseException) -> str:
    """The words a failed build shows (A216 review L3): a missing bone named, a ``ValueError`` as it is, anything
    else with its type."""
    if isinstance(e, KeyError):
        return f"The plain body has no {str(e.args[0] if e.args else '').strip(chr(39))} bone"
    if isinstance(e, ValueError):
        return str(e)
    return f"{type(e).__name__}: {e}"


def build(character_name: str, item_id: str, *, profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Build the accessory ``item_id`` of ``character_name`` on its current plain body (CPU, 0 hub jobs) and store
    it; returns ``accessory_state`` afterwards (+ ``metrics``). A blocked accessory is returned unbuilt; a build
    that raises writes the failure record and returns state ``failed``."""
    from app.core import figure, model_geometry
    from app.core.keyed_lock import keyed_lock
    from app.core.timeutils import utc_now_iso
    from app.models.inventory import get_item
    profile = _profile_of(character_name, profile)
    item = get_item(item_id) or {}
    state = accessory_state(character_name, item_id, profile=profile, item=item)
    if state["state"] == "blocked":
        return state
    from app.core import accessory_parts, accessory_pendant, accessory_spec
    spec = accessory_spec.of_item(item)
    bsig, sha = _current_base(character_name, profile)
    psig = _ready_psig(state.get("pendant"))
    context = state.get("context") or {}
    ready_states = [p for p in state.get("parts") or [] if p["state"] == "ready"]
    ready = accessory_parts.ready_inputs(ready_states)
    sig = asig(spec, ready, context, psig)
    folder = store_dir(character_name)
    with keyed_lock("accessory_build", f"{character_name}/{item_id}"):
        folder.mkdir(parents=True, exist_ok=True)
        failed_path = record_path(character_name, item_id, sig, ".failed.json")
        try:
            from app.models.character import get_character_dir
            blob = (get_character_dir(character_name) / "model3d" / f"{bsig}.glb").read_bytes()
            mesh = accessory_pendant.load_mesh(item_id, psig) if psig else None
            parts = [({k: p[k] for k in ("role", "index", "item", "size_mm", "at_deg", "mount", "drop_cm", "flip")},
                      accessory_pendant.load_mesh(p["item"], p["psig"])) for p in ready_states]
            made = make_any(blob, spec, mesh, context, parts)
        except Exception as e:  # noqa: BLE001 — recorded as the step's failure, the figure leaves it off
            logger.exception("Accessory %s of %s failed", item_id, character_name)
            _write_atomic(failed_path, json.dumps({"error": failure_text(e)[:300], "base_model_sha256": sha,
                                                   "asig": sig, "at": utc_now_iso()}).encode("utf-8"))
            figure.invalidate()
            return accessory_state(character_name, item_id, profile=profile, item=item)
        import io
        buf = io.BytesIO()
        arrays = {"V": made["V"].astype(np.float32), "F": made["F"].astype(np.int32),
                  "N": made["N"].astype(np.float32), "J": made["J"].astype(np.int32),
                  "W": made["W"].astype(np.float32), "curve": made["curve"].astype(np.float32)}
        hung = made.get("pendant")
        if hung is not None:
            arrays.update({"PV": hung["V"].astype(np.float32), "PF": hung["F"].astype(np.int32),
                           "PN": hung["N"].astype(np.float32), "PUV": hung["UV"].astype(np.float32),
                           "PJ": hung["J"].astype(np.int32), "PW": hung["W"].astype(np.float32),
                           "Pimage": np.frombuffer(hung["image"], np.uint8)})
        placed = [(i, ps, h) for i, (ps, h) in enumerate(zip(ready_states, made.get("parts") or [])) if h is not None]
        for slot, (_i, _ps, h) in enumerate(placed):
            arrays.update({f"P{slot}V": h["V"].astype(np.float32), f"P{slot}F": h["F"].astype(np.int32),
                           f"P{slot}N": h["N"].astype(np.float32), f"P{slot}UV": h["UV"].astype(np.float32),
                           f"P{slot}J": h["J"].astype(np.int32), f"P{slot}W": h["W"].astype(np.float32),
                           f"P{slot}image": np.frombuffer(h["image"] or b"", np.uint8)})
        lens = made.get("lens")
        if lens is not None:
            # the glasses: the lenses (their own node) and which frame faces are the temples (the distance tier)
            arrays.update({"LV": lens["V"].astype(np.float32), "LF": lens["F"].astype(np.int32),
                           "LN": lens["N"].astype(np.float32), "LJ": lens["J"].astype(np.int32),
                           "LW": lens["W"].astype(np.float32), "FT": made["temple_faces"].astype(np.uint8)})
        np.savez_compressed(buf, **arrays)
        _write_atomic(record_path(character_name, item_id, sig, ".npz"), buf.getvalue())
        record = {"version": ACCESSORY_VERSION, "item_id": item_id, "asig": sig, "kind": spec["kind"],
                  "inputs": geometry_inputs(spec, ready, context, psig), "bsig": bsig, "base_model_sha256": sha,
                  **model_geometry.stamp_on(character_name, bsig, sha),
                  "joint_names": made["joint_names"], "landmarks": made["landmarks"], "metrics": made["metrics"],
                  "hub_jobs": 0, "built_at": utc_now_iso()}
        if hung is not None:
            pend_rec = accessory_pendant.pendant_state(item_id).get("record") or {}
            record["pendant"] = {"psig": psig, "size_mm": accessory_spec_size(spec), "mime": hung["mime"],
                                 "material": hung["material"], "metrics": hung["metrics"],
                                 # route_meta of the job that made the mesh (the sidecar of this build)
                                 "backend": pend_rec.get("backend", ""), "routing": pend_rec.get("routing") or {},
                                 **({"fallback_from": pend_rec["fallback_from"]}
                                    if pend_rec.get("fallback_from") else {})}
        elif made.get("pendant_error"):
            record["pendant_error"] = REASON_PENDANT_LEFT_OFF.format(error=made["pendant_error"])
        if ready_states:
            record["parts"] = []
            for slot, (_i, ps, h) in enumerate(placed):
                prec = accessory_pendant.pendant_state(ps["item"]).get("record") or {}
                record["parts"].append({
                    "slot": slot, "role": ps["role"], "index": int(ps["index"]), "item": ps["item"],
                    "psig": ps["psig"], "size_mm": float(ps["size_mm"]), "mime": h["mime"], "material": h["material"],
                    "metrics": h["metrics"], "backend": prec.get("backend", ""), "routing": prec.get("routing") or {},
                    **({"fallback_from": prec["fallback_from"]} if prec.get("fallback_from") else {})})
            errors = made.get("part_errors") or {}
            record["part_errors"] = {f"{ready_states[i]['role']}:{ready_states[i]['index']}": str(e)
                                     for i, e in errors.items()}
        _write_atomic(record_path(character_name, item_id, sig), json.dumps(record, indent=1).encode("utf-8"))
        failed_path.unlink(missing_ok=True)
        # One build per item is kept: the other settings' builds go (a switch back rebuilds on the CPU).
        drop_other_builds(folder, item_id, sig)
    figure.invalidate()
    out = accessory_state(character_name, item_id, profile=profile, item=item)
    out["metrics"] = made["metrics"]
    return out


def garment_mesh(character_name: str, item_id: str, record: Dict[str, Any],
                 item: Optional[Dict[str, Any]] = None, without_temples: bool = False):
    """The stored build of ``record`` as a ``glb_mesh.GarmentMesh`` with the item's CURRENT metal (glasses: the frame;
    ``without_temples`` leaves the temples off — the distance tier)."""
    from app.core import accessory_mesh, accessory_spec
    if item is None:
        from app.models.inventory import get_item
        item = get_item(item_id) or {}
    spec = accessory_spec.of_item(item) or accessory_spec.normalize({"kind": record.get("kind") or "necklace"})
    color, rough, metal = piece_material(spec, item_id)
    with np.load(record_path(character_name, item_id, str(record["asig"]), ".npz")) as z:
        V, F, N, J, W = z["V"], z["F"], z["N"], z["J"], z["W"]
        if without_temples and "FT" in z.files:
            V, F, N, J, W = _faces_subset(V, F[z["FT"] == 0], N, J, W)
        return accessory_mesh.garment_mesh(V, F, N, J, W, list(record["joint_names"]),
                                           color=color, roughness=rough, metalness=metal)


def _faces_subset(V, F, N, J, W):
    """Only the vertices the faces ``F`` use, the faces renumbered."""
    used = np.unique(np.asarray(F).reshape(-1))
    remap = np.full(len(V), -1, np.int64)
    remap[used] = np.arange(len(used))
    return V[used], remap[np.asarray(F)], N[used], J[used], W[used]


def lens_mesh(character_name: str, item_id: str, record: Dict[str, Any], item: Optional[Dict[str, Any]] = None):
    """Glasses: the stored lenses of ``record`` as a ``glb_mesh.GarmentMesh`` and their ``glb_mesh.graft`` material
    overrides (the sheer path of A204: alphaMode BLEND, both sides, base-colour alpha = the opacity,
    ``extras.anima_sheer``); None when the build carries none."""
    from app.core import accessory_mesh, accessory_spec
    if item is None:
        from app.models.inventory import get_item
        item = get_item(item_id) or {}
    spec = accessory_spec.of_item(item) or accessory_spec.normalize({"kind": "glasses"})
    lens = accessory_spec.lens_material(spec)
    with np.load(record_path(character_name, item_id, str(record["asig"]), ".npz")) as z:
        if "LV" not in z.files:
            return None
        mesh = accessory_mesh.garment_mesh(z["LV"], z["LF"], z["LN"], z["LJ"], z["LW"], list(record["joint_names"]),
                                           color=lens["color"], roughness=lens["roughness"],
                                           metalness=lens["metalness"])
    opacity = float(lens["opacity"])
    overrides = {"alphaMode": "BLEND", "doubleSided": True,
                 "pbrMetallicRoughness": {"baseColorFactor": [*accessory_spec.srgb_to_linear(lens["color"]), opacity]},
                 "extras": {"anima_sheer": True, "opacity": opacity}}
    return mesh, overrides


def pendant_mesh(character_name: str, item_id: str, record: Dict[str, Any]):
    """A225: the stored pendant of ``record`` as a ``glb_mesh.GarmentMesh`` (its own texture and material from the
    mesher), None when the build carries none."""
    if not isinstance(record.get("pendant"), dict):
        return None
    from app.core.glb_mesh import GarmentMesh
    meta = record["pendant"]
    with np.load(record_path(character_name, item_id, str(record["asig"]), ".npz")) as z:
        if "PV" not in z.files:
            return None
        image = z["Pimage"].tobytes()
        material = dict(meta.get("material") or {})
        material.setdefault("name", "pendant")
        if not image:
            material.setdefault("pbrMetallicRoughness", {"baseColorFactor": [0.8, 0.78, 0.7, 1.0],
                                                         "metallicFactor": 0.0, "roughnessFactor": 0.6})
        return GarmentMesh(positions=z["PV"].astype(np.float64), normals=z["PN"].astype(np.float64),
                           uvs=z["PUV"].astype(np.float64), indices=z["PF"].astype(np.int64),
                           joints=z["PJ"].astype(np.int64), weights=z["PW"].astype(np.float64),
                           joint_names=list(record["joint_names"]), image=image,
                           mime=str(meta.get("mime") or ("image/png" if image else "")), material=material)


def part_meshes(character_name: str, item_id: str, record: Dict[str, Any]) -> List[Any]:
    """Design G: the stored linked parts of ``record`` as ``[(meta, glb_mesh.GarmentMesh)]`` (each with its own
    texture and material from the mesher), in slot order; [] when the build carries none."""
    metas = [m for m in record.get("parts") or [] if isinstance(m, dict)]
    if not metas:
        return []
    from app.core.glb_mesh import GarmentMesh
    out = []
    with np.load(record_path(character_name, item_id, str(record["asig"]), ".npz")) as z:
        for meta in metas:
            k = f"P{int(meta.get('slot', 0))}"
            if f"{k}V" not in z.files:
                continue
            image = z[f"{k}image"].tobytes()
            material = dict(meta.get("material") or {})
            material.setdefault("name", str(meta.get("role") or "part"))
            if not image:
                material.setdefault("pbrMetallicRoughness", {"baseColorFactor": [0.8, 0.78, 0.7, 1.0],
                                                             "metallicFactor": 0.0, "roughnessFactor": 0.6})
            out.append((meta, GarmentMesh(
                positions=z[f"{k}V"].astype(np.float64), normals=z[f"{k}N"].astype(np.float64),
                uvs=z[f"{k}UV"].astype(np.float64), indices=z[f"{k}F"].astype(np.int64),
                joints=z[f"{k}J"].astype(np.int64), weights=z[f"{k}W"].astype(np.float64),
                joint_names=list(record["joint_names"]), image=image,
                mime=str(meta.get("mime") or ("image/png" if image else "")), material=material)))
    return out


#: A225 LOD: the distance tier carries the pendant only up to this many triangles (a 2 cm pendant is a few pixels
#: there; a heavier delivery is left off at distance, never decimated through Blender for it).
PENDANT_LOW_MAX_TRIS = 3000


def graft_accessory(blob: bytes, character_name: str, item_id: str, record: Dict[str, Any], fsig: str,
                    item: Optional[Dict[str, Any]] = None, kind: str = "accessory", low: bool = False) -> bytes:
    """``blob`` + the accessory's chain node and, when the build carries one, its pendant node (A225; on the distance
    tier ``low`` only up to ``PENDANT_LOW_MAX_TRIS``). Glasses: the frame node and the lens node (``lens_mesh``); the
    distance tier leaves off the temples and a clear pair of lenses (``accessory_spec.lens_seen_far``)."""
    from app.core import accessory_mesh, accessory_spec, glb_mesh
    if low and record.get("kind") in LOW_TIER_DROPPED:
        return blob      # A234 / J4: a ring is shown in close-up and admin views only
    extras = {"kind": kind, "item_id": item_id, "fsig": fsig}
    glasses = record.get("kind") == "glasses"
    blob = glb_mesh.graft(blob, garment_mesh(character_name, item_id, record, item, without_temples=low and glasses),
                          name=accessory_mesh.node_name(item_id), extras=extras)
    if glasses:
        # the lenses: their own node with the sheer material; on the distance tier only a tinted or mirrored pair
        if item is None:
            from app.models.inventory import get_item
            item = get_item(item_id) or {}
        lens = lens_mesh(character_name, item_id, record, item)
        spec = accessory_spec.of_item(item)
        if lens is not None and not (low and not accessory_spec.lens_seen_far(spec or {})):
            blob = glb_mesh.graft(blob, lens[0], name=accessory_mesh.node_name(item_id, "g"),
                                  extras={**extras, "part": "lenses"}, material_overrides=lens[1])
    pend = pendant_mesh(character_name, item_id, record)
    if pend is not None and low and len(pend.indices) > PENDANT_LOW_MAX_TRIS:
        pend = None
    if pend is not None:
        blob = glb_mesh.graft(blob, pend, name=accessory_mesh.node_name(item_id, "p"),
                              extras={**extras, "part": "pendant"})
    # design G: one node per linked part (on the distance tier each only up to ``PENDANT_LOW_MAX_TRIS``)
    for meta, mesh in part_meshes(character_name, item_id, record):
        if low and len(mesh.indices) > PENDANT_LOW_MAX_TRIS:
            continue
        blob = glb_mesh.graft(blob, mesh, name=accessory_mesh.node_name(item_id, f"p{int(meta.get('slot', 0))}"),
                              extras={**extras, "part": str(meta.get("role") or "part"),
                                      "part_item": str(meta.get("item") or "")})
    return blob


def npz_path(character_name: str, item_id: str, record: Dict[str, Any]) -> Path:
    return record_path(character_name, item_id, str(record["asig"]), ".npz")


def preview_glb(character_name: str, item_id: str, *, profile: Optional[Dict[str, Any]] = None) -> Optional[bytes]:
    """The plain rigged body with the current build grafted (the Wardrobe's 3D view); the plain body alone while the
    piece is not built (the live curve is drawn over it); None without a plain body."""
    from app.models.character import get_character_dir
    profile = _profile_of(character_name, profile)
    base = _current_base(character_name, profile)
    if base is None:
        return None
    blob = (get_character_dir(character_name) / "model3d" / f"{base[0]}.glb").read_bytes()
    state = accessory_state(character_name, item_id, profile=profile)
    if state["state"] != "current":
        return blob
    return graft_accessory(blob, character_name, item_id, state["record"], state["asig"])


def preview_curve(character_name: str, item_id: str, *, drop_cm: float, thickness_mm: float,
                  profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The chain's centre line for other settings, without storing anything (the Wardrobe's live slider preview):
    ``{points: [[x, y, z]…], landmarks}`` on the current plain body. CPU only."""
    from app.core import accessory_curve, glb_mesh
    from app.models.character import get_character_dir
    profile = _profile_of(character_name, profile)
    base = _current_base(character_name, profile)
    if base is None:
        raise ValueError(REASON_NO_BODY)
    body = glb_mesh.body_arrays((get_character_dir(character_name) / "model3d" / f"{base[0]}.glb").read_bytes())
    radius = max(float(thickness_mm), 0.5) / 2000.0
    detail = accessory_curve.neck_curve_detail(body.positions, body.faces, body.joint_positions,
                                               drop_m=float(drop_cm) / 100.0, offset_m=GAP_M + radius,
                                               n=48, settle=False)
    curve = np.asarray(detail["curve"])
    a = anchor_index(curve)
    return {"points": np.round(curve, 5).tolist(), "landmarks": detail["landmarks"], "radius_m": radius,
            # A225: where a pendant hangs, and the skin's outward normal there (the dialog's placeholder box)
            "anchor": np.round(curve[a], 5).tolist(),
            "anchor_outward": np.round(np.asarray(detail["outward"])[a], 4).tolist()}


# --- A234: the kinds around the body and on a bone -------------------------------------------------------------------

def make_any(rigged: bytes, spec: Dict[str, Any], part: Optional[Dict[str, Any]] = None,
             context: Optional[Dict[str, Any]] = None, parts: Optional[List[Any]] = None) -> Dict[str, Any]:
    """The geometry of any kind on the rigged plain body ``rigged``: the necklace (``make_necklace``), the earrings
    (``make_earrings``), the ring (``make_ring``), the glasses (``make_glasses``) or a piece around a body part (``make_around``). A chest shaping in ``context`` (A228 L7)
    shapes the body first, so a piece near the chest sits on the shaped skin the figure shows. ``part``: the earrings'
    own drop mesh; ``parts``: the linked parts ``[(link, mesh)]`` of a necklace or a belt."""
    context = context or {}
    if context.get("shaping") and _keyed_by_shaping(spec):
        from app.core import bust_shaping
        rigged = bust_shaping.shape_glb(rigged, context["shaping"])
    if spec["kind"] == "necklace":
        return make_necklace(rigged, spec, parts)
    if spec["kind"] == "earrings":
        return make_earrings(rigged, spec, part)
    if spec["kind"] == "ring":
        return make_ring(rigged, spec)
    if spec["kind"] == "glasses":
        return make_glasses(rigged, spec)
    return make_around(rigged, spec, parts, load_under(context.get("under") or []))


def load_under(under: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The worn garments of ``worn_context`` as ``{item_id, P, F, J (n, 4), W, joint_names, slots, footwear}`` — every
    garment node of the fit / drape GLB (a shoe has four), positions in the plain body's bind space."""
    from app.core import glb_mesh
    out = []
    for u in under:
        try:
            blob = Path(u["path"]).read_bytes()
            parsed = glb_mesh._parse(blob, "Garment")
            names = [str(n.get("name") or "") for n in parsed["gltf"].get("nodes") or []
                     if "mesh" in n and glb_mesh._is_garment_node(n)]
            for name in names:
                g = glb_mesh.garment_arrays(blob, node_prefix=name, exact=True)
                out.append({"item_id": u["item_id"], "P": np.asarray(g.positions, np.float64),
                            "F": np.asarray(g.indices, np.int64).reshape(-1, 3),
                            "J": np.asarray(g.joints), "W": np.asarray(g.weights),
                            "joint_names": list(g.joint_names), "slots": list(u.get("slots") or []),
                            "footwear": bool(u.get("footwear"))})
        except Exception:  # noqa: BLE001 — an unreadable garment is not under the band
            logger.warning("Accessory: garment %s under the band unreadable", u.get("item_id"), exc_info=True)
    return out


def _garment_dominant(g: Dict[str, Any], allowed) -> np.ndarray:
    """The faces of a worn garment whose vertices' strongest joint is one of ``allowed`` (``dominant_faces``)."""
    from app.core.rig_contract import norm_bone_name
    names = np.array([norm_bone_name(str(n)) for n in g["joint_names"]] or [""])
    J, W = g["J"], g["W"]
    if not len(J) or not len(g["joint_names"]):
        return g["F"][:0]
    top = names[np.clip(J[np.arange(len(J)), W.argmax(1)], 0, len(names) - 1)]
    ok = np.isin(top, list(allowed))
    return g["F"][ok[g["F"]].sum(1) >= 2]


#: A234 plausibility per section (``around_plausible``): the length of the piece's centre line (metres) and the joints
#: that may move it (normalised; weight above ``PLAUSIBLE_WEIGHT``).
AROUND_LENGTH_M: Dict[str, tuple] = {
    "belt": (0.5, 1.7), "choker": (0.22, 0.6), "strap:thigh": (0.28, 1.0), "strap:upper_arm": (0.14, 0.55),
    "strap:chest": (0.55, 1.5), "anklet": (0.13, 0.45), "bracelet": (0.10, 0.35),
}
AROUND_JOINTS: Dict[str, frozenset] = {
    "belt": frozenset({"hips", "spine", "spine1", "leftupleg", "rightupleg"}),
    "choker": frozenset({"neck", "spine2", "head"}),
    "strap:thigh": frozenset({"hips", "leftupleg", "rightupleg"}),
    "strap:upper_arm": frozenset({"leftshoulder", "rightshoulder", "leftarm", "rightarm", "leftforearm",
                                  "rightforearm", "spine2"}),
    "strap:chest": frozenset({"spine", "spine1", "spine2", "leftshoulder", "rightshoulder"}),
    "anklet": frozenset({"leftleg", "rightleg", "leftfoot", "rightfoot"}),
    "bracelet": frozenset({"leftforearm", "rightforearm", "lefthand", "righthand"}),
    "glasses": frozenset({"head"}),
}
AROUND_IMPLAUSIBLE = "The {what} does not fit this body ({why})"
#: What a section is called in the words of a failure.
AROUND_WHAT = {"belt": "belt", "choker": "choker", "strap:thigh": "thigh strap", "strap:upper_arm": "arm strap",
               "strap:chest": "chest strap", "anklet": "anklet", "bracelet": "bracelet",
               "earrings": "earring", "glasses": "glasses"}


def around_plausible(key: str, metrics: Dict[str, Any]) -> None:
    """``ValueError`` (``AROUND_IMPLAUSIBLE``) when a built piece misses its gate: centre-line length per side in
    ``AROUND_LENGTH_M``, weight only on ``AROUND_JOINTS``, nothing inside
    in any test pose, a segment at most ``MAX_SEGMENT_RATIO`` × the median."""
    from app.core.rig_contract import norm_bone_name
    why = []
    lo, hi = AROUND_LENGTH_M[key]
    for side, length in (metrics.get("length_m") or {}).items():
        if not lo <= float(length) <= hi:
            why.append(f"{float(length) * 100:.0f} cm round{' (' + side + ')' if side else ''}, expected "
                       f"{lo * 100:.0f}–{hi * 100:.0f} cm")
    if float(metrics.get("max_segment_ratio") or 0) > MAX_SEGMENT_RATIO:
        why.append("it jumps between two points")
    others = [j for j in metrics["joints"] if norm_bone_name(j) not in AROUND_JOINTS[key]]
    if others:
        why.append("it would move with " + ", ".join(norm_bone_name(j) for j in others))
    inside = [name for name, m in (metrics.get("poses") or {}).items() if m["inside_share"] > 0.0]
    if float(metrics.get("inside_share") or 0) > 0.0:
        inside.insert(0, "rest (on the layer under it)")
    if inside:
        why.append("part of it lies inside in the " + ", ".join(inside) + " pose")
    if why:
        raise ValueError(AROUND_IMPLAUSIBLE.format(what=AROUND_WHAT[key], why="; ".join(why)))


def _body_context(rigged: bytes):
    """``(body, dense, Pw, Fw, first, Fo)``: the body, its dense weights, the welded body, the source vertex of each
    welded one and the faces the test poses judge a side by (``outer_wall_faces``)."""
    from scipy.spatial import cKDTree
    from app.core import accessory_curve, glb_mesh
    from app.core.garment_fit import dense_weights
    body = glb_mesh.body_arrays(rigged)
    dense = dense_weights(body)
    Pw, Fw = accessory_curve.weld(np.asarray(body.positions, np.float64), np.asarray(body.faces, np.int64))
    _, first = cKDTree(np.asarray(body.positions, np.float64)).query(Pw)
    Fo = Fw[outer_wall_faces(Pw, Fw, body.joint_positions, glb_mesh.skin_joint_parents(rigged))]
    return body, dense, Pw, Fw, first, Fo


#: Faces smaller than this (m²) never decide a point's side in the test poses: three micro-triangles with opposite
#: normals at the front of Lirien's belly (0.07 mm² each) gave "inside" by the order they were met.
SIGN_MIN_AREA_M2 = 0.5e-6
#: How many of the nearest bone segments vote on a face's side (``outer_wall_faces``). Measured against faces a ray
#: can leave the body from (Blender BVH, 25 rays per face, 10 bodies): the nearest segment alone dropped 0.2–4.2 % of
#: that skin by area, four dropped 0.0–3.8 % and kept less inner wall on every body.
OUTER_SEGMENTS = 4


def outer_wall_faces(P: np.ndarray, F: np.ndarray, heads: Dict[str, Any], parents: Dict[str, str]) -> np.ndarray:
    """The mask of the faces of the body's OUTER wall in the bind pose. Every generated base body is double-walled
    (a second, inward-facing wall 5–19 mm under the skin), and ``garment_shell.signed_distance`` takes its sign from
    the nearest face: where a bent hip brings the inner wall nearest, a piece outside the skin counts as inside, and
    the cavity behind the inner wall counts as outside. A face is outer when its winding normal (signed by the
    mesh's volume) points away from the bone segments of the base skeleton nearest to it (a base joint's head to its
    base parent's head): the cosines to the ``OUTER_SEGMENTS`` nearest segments, weighted by 1 / distance², sum
    above 0. One nearest segment alone took the skin under a bulge for inner wall where a segment ends at a joint
    (the flank above the hip read against the hip bone: a belt there measured −8 mm); faces under
    ``SIGN_MIN_AREA_M2`` are left out."""
    from app.core.rig_contract import BASE_JOINT_KEYS, norm_bone_name
    P = np.asarray(P, np.float64)
    F = np.asarray(F, np.int64).reshape(-1, 3)
    by_key = {norm_bone_name(str(k)): np.asarray(v, np.float64) for k, v in heads.items()}
    a, b = [], []
    for name, parent in parents.items():
        key, pkey = norm_bone_name(str(name)), norm_bone_name(str(parent or ""))
        if key in BASE_JOINT_KEYS and pkey in BASE_JOINT_KEYS and key in by_key and pkey in by_key:
            a.append(by_key[pkey])
            b.append(by_key[key])
    if not a:
        return np.ones(len(F), bool)
    A, D = np.asarray(a), np.asarray(b) - np.asarray(a)
    dd = np.maximum(np.einsum("ij,ij->i", D, D), 1e-12)
    N = np.cross(P[F[:, 1]] - P[F[:, 0]], P[F[:, 2]] - P[F[:, 0]])
    vol = np.einsum("ij,ij->i", P[F[:, 0]], np.cross(P[F[:, 1]], P[F[:, 2]])).sum()
    N = N * (1.0 if vol >= 0 else -1.0)
    C = P[F].mean(1)
    m = min(OUTER_SEGMENTS, len(A))
    away = np.zeros(len(F), bool)
    for s in range(0, len(F), 20000):
        c, n = C[s:s + 20000], N[s:s + 20000]
        t = np.clip(np.einsum("cij,ij->ci", c[:, None] - A[None], D) / dd[None], 0.0, 1.0)
        X = c[:, None] - (A[None] + t[..., None] * D[None])
        d2 = np.maximum(np.einsum("cij,cij->ci", X, X), 1e-18)
        cos = np.einsum("cij,cj->ci", X, n) / np.sqrt(d2)
        near = np.argsort(d2, axis=1)[:, :m]
        away[s:s + 20000] = (np.take_along_axis(cos, near, 1) / np.take_along_axis(d2, near, 1)).sum(1) > 0
    return away & (np.linalg.norm(N, axis=1) / 2 >= SIGN_MIN_AREA_M2)


def _poses(rigged: bytes, body, dense, Pw, Fo, first, V, J, W) -> Dict[str, Dict[str, float]]:
    """``accessory_pendant.pose_check`` of the piece ``V`` (skin ``J/W``) against the body's outer wall ``Fo``
    (``_body_context``) in the CPU test poses."""
    from app.core import accessory_pendant, glb_mesh
    from app.core.garment_shell import top4_weights
    from app.core.rig_contract import norm_bone_name
    Jb, Wb, used = top4_weights(dense)
    Jb = used[Jb]
    heads = {norm_bone_name(k): v for k, v in body.joint_positions.items()}
    return accessory_pendant.pose_check(Pw, Fo, Jb[first], Wb[first], V, J, W, list(body.joint_names),
                                        glb_mesh.skin_joint_parents(rigged), heads, kq=POSE_KQ)


#: A234: candidate faces per point in the test-pose check (12 picked a far face over Henrik's ankle: −6 mm "inside"
#: where 48 and 200 both give the true +2.4 mm).
POSE_KQ = 48


def _joint_maxima(joint_names, J: np.ndarray, W: np.ndarray) -> Dict[str, float]:
    return {str(joint_names[j]): round(float(W[J == j].max()), 3) for j in np.unique(J[W > PLAUSIBLE_WEIGHT])}


#: A234: the air of a piece that needs more than ``accessory_band.GAP_M``: under the bust the breast's skin swings
#: onto a band skinned to the spine when the trunk bends (Vallerie, sit: −1 mm at 2 mm).
AROUND_GAP_M = {"strap:chest": 0.0035}


def make_around(rigged: bytes, spec: Dict[str, Any], parts: Optional[List[Any]] = None,
                under: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """A belt / choker / strap (a flat band) or an anklet / bracelet (a round tube) around its body part
    (``accessory_band``), on the outermost layer under it (``under``: ``load_under``; the body alone for
    ``band.layer: body``), skinned with the nearest body vertices' weights folded onto the base skeleton, gated by
    ``around_plausible``. A belt's linked parts (``parts``: ``[(link, mesh)]`` — the buckle and the side charms) are
    placed by their links (``attach_parts``; one that does not fit is left off with its reason). ``{V, F, N, J, W,
    joint_names, curve, landmarks, metrics, parts, part_errors}``. Pure CPU."""
    from app.core import accessory_band as ab, accessory_mesh, glb_mesh
    from app.core.accessory_spec import BAND_KINDS
    started = time.monotonic()
    body, dense, Pw, Fw, first, Fo = _body_context(rigged)
    key = ab.region_key(spec)
    what = AROUND_WHAT[key]
    band = spec["kind"] in BAND_KINDS
    reach = ab.REACH_M[spec["kind"]]
    radius = float(spec["chain"]["thickness_mm"]) / 2000.0
    thickness = ab.BAND_THICKNESS_M[spec["band"]["material"]]
    width = float(spec["band"]["width_cm"]) / 100.0
    under = under or []
    gap_m = AROUND_GAP_M.get(key, ab.GAP_M)
    Vs, Fs, curves, lengths, ratios, landmarks = [], [], [], {}, [], {}
    gaps, under_share, skins = [], [], []
    for side in ab.sides_of(spec):
        allowed = ab.joints_for(spec, side)
        Fb = ab.dominant_faces(Fw, dense[first], body.joint_names, allowed)
        layers = [(g["P"], _garment_dominant(g, allowed)) for g in under
                  if spec["kind"] == "anklet" or not g["footwear"]]
        layers = [(P, F) for P, F in layers if len(F)]
        top = belt_top(under, body.joint_positions) if spec["kind"] == "belt" else None
        fr = ab.frame(spec, body.joint_positions, side, belt_top_y=top)
        offsets = ab.band_rows(fr, width) if band else np.array([0.0])
        surf = ab.surface_radius(Pw, Fb, layers, fr, offsets, reach=reach, what=what)
        t = ab.smooth_up(surf["t"])
        dirs = surf["dirs"]
        # The air is held to the whole skin near the piece (a bump of the back above a belt belongs to Spine2), along
        # the skin's normal. Over a garment the radius already lies on its outermost surface (the rays): a garment's
        # thin walls and rims are no surface to push along.
        skin_only = [(Pw, Fw)]
        if band:
            inner = (fr["centre"][None, None] + offsets[:, None, None] * fr["axis"][None, None]
                     + (t + gap_m)[:, :, None] * dirs[None])
            flat = ab.push_out(inner.reshape(-1, 3), np.tile(dirs, (len(offsets), 1)), skin_only, gap_m)
            inner = flat.reshape(inner.shape)
            radial = np.einsum("rnk,nk->rn", inner - fr["centre"][None, None], dirs)
            V, F, N = ab.band_mesh(fr, offsets, radial, dirs, thickness)
            # the outer wall and the edges clear the skin too (a chin over a choker, a hip over a belt's edge)
            V = ab.push_out(V, np.repeat(dirs, 2 * len(offsets), 0), skin_only, gap_m)
            curve = inner[len(offsets) // 2] + dirs * thickness / 2
            X = inner.reshape(-1, 3)
            over = surf["on_garment"].reshape(-1)
            rad_gap = (radial - surf["t"]).reshape(-1)
        else:
            curve = ab.ring_curve(fr, t[0] + gap_m + radius, dirs)
            curve = ab.push_out(curve, dirs, skin_only, gap_m + radius)
            V, F, N = accessory_mesh.tube(curve, radius, outward=dirs)
            X = curve - dirs * radius
            over = surf["on_garment"][0]
            rad_gap = np.einsum("nk,nk->n", X - fr["centre"][None], dirs) - surf["t"][0]
        # the air under it: to the skin along its normal; over a garment, along the ray to the garment's surface
        gap_skin = ab.surface_gap(X, np.tile(dirs, (len(X) // len(dirs), 1)), skin_only)
        gaps.append(np.where(over, np.minimum(gap_skin, rad_gap), gap_skin))
        seg = np.linalg.norm(np.diff(np.vstack([curve, curve[:1]]), axis=0), axis=1)
        lengths[side] = round(float(seg.sum()), 4)
        ratios.append(float(seg.max() / max(float(np.median(seg)), 1e-9)))
        under_share.append(surf["under_share"])
        # A piece on one limb takes its weights from that limb's skin only: thighs touching in the bind pose
        # would otherwise hand the inner side half to the other leg, which leaves through it when the legs move.
        src = np.unique(first[np.unique(Fb)]) if side else np.arange(len(body.positions))
        Jv, Wv = accessory_mesh.skin_weights(V, np.asarray(body.positions, np.float64)[src], dense[src])
        skins.append((Jv, Wv))
        Fs.append(F + sum(len(v) for v in Vs))
        Vs.append(V)
        curves.append(curve)
        landmarks[side or "centre"] = {"centre": np.round(fr["centre"], 5).tolist(),
                                       "axis": np.round(fr["axis"], 4).tolist(),
                                       **({"belt_top_y": round(float(top), 4)} if top is not None else {})}
    V, F = np.vstack(Vs), np.vstack(Fs)
    from app.core.accessory_curve import vertex_normals
    N = vertex_normals(V, F)
    J, W = np.vstack([j for j, _ in skins]), np.vstack([w for _, w in skins])
    J, W = accessory_mesh.fold_to_base(J, W, list(body.joint_names), glb_mesh.skin_joint_parents(rigged))
    gap = np.concatenate(gaps) * 1000.0
    poses = _poses(rigged, body, dense, Pw, Fo, first, V, J, W)
    metrics = {"gap_mm": {"p05": round(float(np.percentile(gap, 5)), 2), "p50": round(float(np.median(gap)), 2),
                          "p95": round(float(np.percentile(gap, 95)), 2), "min": round(float(gap.min()), 2)},
               "inside_share": round(float((gap < -0.5).mean()), 4),
               "on_clothing_share": round(float(np.mean(under_share)), 3),
               "triangles": int(len(F)), "vertices": int(len(V)), "length_m": lengths,
               "max_segment_ratio": round(max(ratios), 2), "joints": _joint_maxima(body.joint_names, J, W),
               "poses": poses, "cpu_s": 0.0}
    around_plausible(key, metrics)
    out = {"V": V, "F": F, "N": N, "J": J, "W": W, "joint_names": list(body.joint_names),
           "curve": np.vstack(curves), "landmarks": landmarks, "metrics": metrics}
    out["parts"], out["part_errors"] = [], {}
    if parts and spec["kind"] == "belt":
        out["parts"], out["part_errors"] = attach_parts(rigged, body, dense, Pw, Fw, Fo, first, curves[0], V, J, W,
                                                        parts, thickness)
    metrics["cpu_s"] = round(time.monotonic() - started, 2)
    return out


def belt_top(under: List[Dict[str, Any]], bones: Dict[str, Any]) -> Optional[float]:
    """The top edge of a worn bottom (a garment on ``bottom`` / ``legs`` / ``underwear_bottom``) at the front middle:
    the highest garment vertex within 4 cm of the Hips bone head's x, in front of it; None without one."""
    from app.core.accessory_band import _bone
    hips = _bone(bones, "hips")
    tops = []
    for g in under:
        if g["footwear"] or not set(g["slots"]) & {"bottom", "legs", "underwear_bottom"}:
            continue
        P = g["P"]
        front = (np.abs(P[:, 0] - hips[0]) < 0.04) & (P[:, 2] > hips[2])
        if front.any():
            tops.append(float(P[front, 1].max()))
    return max(tops) if tops else None


def _rigid_part(Vn: np.ndarray, part: Dict[str, Any], J_at: np.ndarray, W_at: np.ndarray, rigged: bytes, body,
                dense, Pw, Fo, first, size_mm: Optional[float], what: str) -> Dict[str, Any]:
    """An item-image part already in place (``Vn``), rigid with the skin ``J_at / W_at``: the size and the test-pose
    gates of the pendant (``SIZE_TOLERANCE`` unless ``size_mm`` is None — a pair of drops measures across both;
    nothing inside in any pose). ``ValueError`` naming why it is left
    off."""
    from app.core import accessory_curve
    lo, hi = Vn.min(0), Vn.max(0)
    measured = float((hi - lo).max()) * 1000.0
    if size_mm is not None and abs(measured - size_mm) > SIZE_TOLERANCE * size_mm:
        raise ValueError(f"its size came out {measured:.1f} mm instead of {size_mm:.0f} mm")
    Jp = np.repeat(np.asarray(J_at)[None], len(Vn), 0)
    Wp = np.repeat(np.asarray(W_at)[None], len(Vn), 0)
    poses = _poses(rigged, body, dense, Pw, Fo, first, Vn, Jp, Wp)
    inside = [name for name, m in poses.items() if m["inside_share"] > 0.0]
    if inside:
        raise ValueError(f"the {what} would sink into the body in the {', '.join(inside)} pose")
    F = np.asarray(part["F"], np.int64)
    weights = {str(body.joint_names[j]): round(float(Wp[0][k]), 3) for k, j in enumerate(Jp[0]) if Wp[0][k] > 0}
    return {"V": Vn, "F": F, "N": accessory_curve.vertex_normals(Vn, F), "UV": np.asarray(part["UV"], np.float64),
            "J": Jp, "W": Wp, "image": part.get("image") or b"", "mime": part.get("mime") or "",
            "material": part.get("material") or {},
            "metrics": {"size_mm": round(measured, 2), "triangles": int(len(F)), "joints": weights, "poses": poses}}


def curve_point_at(curve: np.ndarray, deg: float) -> int:
    """The index of the point of ``curve`` whose azimuth about the curve's mean, ``atan2(x − cx, z − cz)`` (0 = the
    front, +90 = the body's left), is nearest ``deg``."""
    C = np.asarray(curve, np.float64)
    c = C.mean(0)
    az = np.degrees(np.arctan2(C[:, 0] - c[0], C[:, 2] - c[2]))
    diff = np.abs(((az - float(deg)) + 180.0) % 360.0 - 180.0)
    return int(np.argmin(diff))


#: ``attach_part``: the AABB overlap (m, on every axis) at which two parts count as one on top of the other.
PART_OVERLAP_M = 0.001
#: ``attach_part``: a FLAT part keeps at most this share of its size as depth behind its front — it lies on the band
#: like a buckle frame; what a mesher invented behind it (the strap loop, the prong, a bail) is pressed into that
#: depth (50 mm buckle → 10 mm). A hanging part keeps its depth (it hangs free, ``place`` clears the body).
FLAT_DEPTH_SHARE = 0.20
#: How a part's role reads in its overlap reason.
PART_WORDS = {"buckle": "buckle", "pendant": "pendant", "charm": "charm"}


def attach_part(rigged: bytes, body, dense, Pw, Fw, Fo, first, curve: np.ndarray, V: np.ndarray, J: np.ndarray,
                W: np.ndarray, link: Dict[str, Any], mesh: Dict[str, Any], size_mm: float, flip: bool,
                thickness: float, placed: List[Any]) -> Dict[str, Any]:
    """A linked part (plan-anhaenger, design G) placed by its link on the band whose centre line is ``curve``: at the
    curve point ``curve_point_at(link.at_deg)``, turned to face the horizontal outward direction there.

    ``flat``: centred on that point, its back ``thickness / 2 + 0.5 mm`` out (on the band), no push; deeper than
    ``FLAT_DEPTH_SHARE`` of its size, what lies further behind its front is pressed onto that depth. ``hang``: its top
    centre at the same distance out and ``drop_cm`` lower, hung through ``accessory_pendant.place`` against ``Fw`` (the
    whole welded body — the rest pose, as the necklace's pendant), at most ``PENDANT_MAX_PUSH_MM`` off its point.
    Rigid with the band's skin at the nearest band vertex; the test poses judge it against the outer wall ``Fo``
    (``_rigid_part``). ``placed``: ``(lo, hi, role)`` boxes of the parts already on the band — an overlap of
    ``PART_OVERLAP_M`` or more on every axis leaves this one off ("it overlaps the …"). ``ValueError`` naming why it
    is left off; else ``_rigid_part``'s dict (+ ``metrics.anchor / mount / at_deg``)."""
    from app.core import accessory_pendant
    C = np.asarray(curve, np.float64)
    k = curve_point_at(C, float(link.get("at_deg") or 0.0))
    at = C[k]
    c = C.mean(0)
    h = np.array([at[0] - c[0], 0.0, at[2] - c[2]])
    h = h / np.linalg.norm(h) if np.linalg.norm(h) > 1e-9 else np.array([0.0, 0.0, 1.0])
    outline = accessory_pendant.front_reason(mesh["V"], mesh.get("front_ratio"))
    if outline:
        raise ValueError(outline)
    Vn = accessory_pendant.normalise(mesh["V"], size_mm, flip, mesh.get("front_ratio"))
    off = float(thickness) / 2 + 0.0005
    mount = link.get("mount") or "flat"
    how: Dict[str, Any] = {}
    raw_depth = float(Vn[:, 2].max())         # back at z 0 after ``normalise``, front at the top
    if mount != "hang":
        cap = FLAT_DEPTH_SHARE * float(size_mm) / 1000.0
        if raw_depth > cap:
            Vn[:, 2] = np.maximum(Vn[:, 2], raw_depth - cap) - (raw_depth - cap)
            how["depth_cut_from_mm"] = round(raw_depth * 1000.0, 2)
    local = Vn.copy()
    if mount == "hang":
        anchor = at + h * off - np.array([0.0, float(link.get("drop_cm") or 0.0) / 100.0, 0.0])
        Vp, how = accessory_pendant.place(Vn, anchor, h, Pw, Fw)
        how.pop("rotation", None)
        if how["push_mm"] > PENDANT_MAX_PUSH_MM:
            raise ValueError(PENDANT_OFF_CORD.format(mm=how["push_mm"]))
    else:
        Vn = Vn - np.array([0.0, (Vn[:, 1].min() + Vn[:, 1].max()) / 2, 0.0])     # centred in height too
        R = accessory_pendant._rot_y(float(np.arctan2(h[0], h[2])))
        anchor = at + h * off
        Vp = Vn @ R.T + anchor
    lo, hi = Vp.min(0), Vp.max(0)
    for plo, phi, other in placed:
        overlap = np.minimum(hi, phi) - np.maximum(lo, plo)
        if bool((overlap >= PART_OVERLAP_M).all()):
            raise ValueError(f"it overlaps the {PART_WORDS.get(other, other)}")
    kv = int(np.argmin(np.linalg.norm(np.asarray(V, np.float64) - anchor, axis=1)))
    hung = _rigid_part(Vp, mesh, J[kv], W[kv], rigged, body, dense, Pw, Fo, first, None,
                       PART_WORDS.get(link.get("role"), "part"))
    measured = float((local.max(0) - local.min(0))[:2].max()) * 1000.0
    if abs(measured - size_mm) > SIZE_TOLERANCE * size_mm:
        raise ValueError(f"its size came out {measured:.1f} mm instead of {size_mm:.0f} mm")
    hung["metrics"].update({"size_mm": round(measured, 2), "anchor": [round(float(x), 5) for x in anchor],
                            "mount": mount, "at_deg": float(link.get("at_deg") or 0.0),
                            "depth_mm": round(float((local.max(0) - local.min(0))[2]) * 1000.0, 2), **how})
    return hung


def attach_parts(rigged: bytes, body, dense, Pw, Fw, Fo, first, curve: np.ndarray, V: np.ndarray, J: np.ndarray,
                 W: np.ndarray, parts: List[Any], thickness: float):
    """Every linked part of a band (``parts``: ``[(link, mesh)]``, link with the effective ``size_mm`` / ``mount`` /
    ``flip``) through ``attach_part`` in order: ``([hung | None], {index: reason})`` — a part that does not fit is left
    off with its reason, the band and the other parts stay."""
    hung: List[Optional[Dict[str, Any]]] = []
    errors: Dict[int, str] = {}
    placed: List[Any] = []
    for i, (link, mesh) in enumerate(parts):
        try:
            got = attach_part(rigged, body, dense, Pw, Fw, Fo, first, curve, V, J, W, link, mesh,
                              float(link.get("size_mm") or 30.0), bool(link.get("flip")), thickness, placed)
        except ValueError as e:
            hung.append(None)
            errors[i] = str(e)
            continue
        hung.append(got)
        placed.append((got["V"].min(0), got["V"].max(0), link.get("role") or "part"))
    return hung, errors


def make_earrings(rigged: bytes, spec: Dict[str, Any], part: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Earrings on the ear lobes (``accessory_band.ear_anchor``), rigid on the Head (spec § 4): ``stud`` a ball of
    ``earring.size_mm``, ``hoop`` a torus of that diameter hanging beside the lobe (wire = ``chain.thickness_mm``),
    ``drop`` the item-image mesh (``part``) hung under the lobe — without a ready mesh a stud stands in. Gated: nothing
    inside the body in the test poses, at most ``EARRING_MAX_GAP_MM`` from the lobe."""
    from app.core import accessory_band as ab, accessory_pendant
    from app.core.accessory_curve import vertex_normals
    from app.core.rig_contract import norm_bone_name
    started = time.monotonic()
    body, dense, Pw, Fw, first, Fo = _body_context(rigged)
    head = [i for i, n in enumerate(body.joint_names) if norm_bone_name(str(n)) == "head"]
    if not head:
        raise KeyError("head")
    style = spec["earring"]["style"]
    size = float(spec["earring"]["size_mm"]) / 1000.0
    wire = float(spec["chain"]["thickness_mm"]) / 2000.0
    Vs, Fs, anchors, part_V, part_F = [], [], {}, [], []
    for side in ab.sides_of(spec):
        anc = ab.ear_anchor(Pw, dense[first], body.joint_names, body.joint_positions, side)
        p, n = anc["point"], anc["outward"]
        sx = float(n[0])
        if style == "hoop":
            major = size / 2 - wire
            # beside the skin it hangs past (the jaw under the lobe stands out farther than the lobe)
            x = ab.clear_lateral(Pw, p, side, size, major + wire) * sx + sx * (wire + ab.GAP_M)
            # tilted out at the bottom (``HOOP_TILT_DEG``): the top stays at the lobe, the lowest point swings away
            # from the jaw and neck below it
            th = np.radians(HOOP_TILT_DEG)
            axis = np.array([np.cos(th) * sx, np.sin(th), 0.0])
            up = np.array([-np.sin(th) * sx, np.cos(th), 0.0])
            top = np.array([x, p[1] + wire, p[2]])
            V, F, _N = ab.torus(top - up * major, axis, major, wire)
        elif style == "drop" and part is not None:
            from app.core.accessory_spec import image_part_mm
            Vn = accessory_pendant.normalise(part["V"], float(image_part_mm(spec) or 18.0),
                                             front_ratio=part.get("front_ratio"))
            # front (+Z) turned to face out to the side; top centre just under the lobe
            R = accessory_pendant._rot_y(np.pi / 2 if side == "left" else -np.pi / 2)
            # its back (z 0 after ``normalise``) turned to face the head, beside the skin it hangs past
            reach = ab.clear_lateral(Pw, p, side, float(np.ptp(Vn[:, 1])) + 0.002, float(np.ptp(Vn[:, 0])) / 2)
            V = Vn @ R.T + np.array([sx * (reach + ab.GAP_M), p[1] - 0.002, p[2]])
            F = np.asarray(part["F"], np.int64)
            part_V.append(V)
            part_F.append(F + sum(len(v) for v in part_V[:-1]))
            V, F = ab.icosphere(max(wire * 1.5, 0.0012))
            V = V + p + n * (ab.GAP_M + max(wire * 1.5, 0.0012))
        else:
            r = size / 2
            V, F = ab.icosphere(r)
            V = V + p + n * (r + ab.GAP_M)
        V = _clear_of_head(V, n, Pw, Fw, passes=12)
        if part_V and len(part_V) == len(anchors) + 1:
            part_V[-1] = _clear_of_head(part_V[-1], n, Pw, Fw)
        Fs.append(F + sum(len(v) for v in Vs))
        Vs.append(V)
        anchors[side] = {"lobe": np.round(p, 5).tolist(), "lobe_y": anc["lobe_y"]}
    V, F = np.vstack(Vs), np.vstack(Fs)
    J = np.zeros((len(V), 4), np.int64)
    J[:, 0] = head[0]
    W = np.zeros((len(V), 4))
    W[:, 0] = 1.0
    from app.core.garment_shell import signed_distance
    sd = signed_distance(V, Pw, Fw) * 1000.0
    poses = _poses(rigged, body, dense, Pw, Fo, first, V, J, W)
    metrics = {"gap_mm": {"min": round(float(sd.min()), 2), "p50": round(float(np.median(sd)), 2)},
               "inside_share": round(float((sd < -0.5).mean()), 4), "style": style,
               "triangles": int(len(F)), "vertices": int(len(V)), "joints": {str(body.joint_names[head[0]]): 1.0},
               "poses": poses, "cpu_s": 0.0}
    why = [name for name, m in poses.items() if m["inside_share"] > 0.0]
    if why or metrics["inside_share"] > 0:
        raise ValueError(AROUND_IMPLAUSIBLE.format(what="earring", why="part of it lies inside the head in the "
                                                   + ", ".join(why or ["rest"]) + " pose"))
    if float(sd.min()) < EARRING_MIN_GAP_MM:
        raise ValueError(AROUND_IMPLAUSIBLE.format(what="earring", why=f"it comes within {max(sd.min(), 0):.1f} mm "
                                                   "of the jaw or neck (a smaller hoop or a stud fits)"))
    if float(sd.min()) > EARRING_MAX_GAP_MM:
        raise ValueError(AROUND_IMPLAUSIBLE.format(what="earring", why=f"it stands {sd.min():.0f} mm off the ear"))
    out = {"V": V, "F": F, "N": vertex_normals(V, F), "J": J, "W": W, "joint_names": list(body.joint_names),
           "curve": np.vstack([np.asarray(a["lobe"])[None] for a in anchors.values()]), "landmarks": anchors,
           "metrics": metrics}
    if part_V:
        Vp = np.vstack(part_V)
        Fp = np.vstack(part_F)
        try:
            both = {"V": Vp, "F": Fp, "UV": np.vstack([np.asarray(part["UV"], np.float64)] * len(part_V)),
                    "image": part.get("image"), "mime": part.get("mime"), "material": part.get("material")}
            out["pendant"] = _rigid_part(Vp, both, J[0], W[0], rigged, body, dense, Pw, Fo, first, None, "drop")
            # one drop's longest side (the pair measured together spans the head)
            out["pendant"]["metrics"]["size_mm"] = round(float(np.ptp(part_V[0], 0).max()) * 1000.0, 2)
        except ValueError as e:
            out["pendant_error"] = str(e)
    metrics["cpu_s"] = round(time.monotonic() - started, 2)
    return out


def make_ring(rigged: bytes, spec: Dict[str, Any]) -> Dict[str, Any]:
    """A238: the ring (``accessory_ring``) on ``spec['finger']`` of the ``spec['side']`` hand: a band of
    ``band.width_cm`` × ``chain.thickness_mm`` whose inner radius is computed from the skeleton (hand width, proximal
    bone length) and the body height (the mesh's vertical extent, which scales the clamp range) — never the finger's skin, which the webbing fuses with its neighbours), centred on the
    proximal bone at ``ring.along``, rigid on that bone (weight 1.0). Gated only by ``accessory_ring.check`` (centre
    in the hand's skin box, radius in range). ``{V, F, N, J, W, joint_names, curve, landmarks, metrics}``. Pure
    CPU."""
    from app.core import accessory_ring as ar, glb_mesh
    from app.core.garment_fit import joint_index
    from app.core.rig_contract import norm_bone_name
    started = time.monotonic()
    body = glb_mesh.body_arrays(rigged)
    P = np.asarray(body.positions, np.float64)
    side, finger = spec["side"], spec["finger"]
    height = float(P[:, 1].max() - P[:, 1].min())
    sized = ar.size(body.joint_positions, finger, side, height)
    fr = ar.frame(body.joint_positions, finger, side, spec["ring"]["along"])
    radius = float(sized["radius_m"])
    width = float(spec["band"]["width_cm"]) / 100.0
    thickness = float(spec["chain"]["thickness_mm"]) / 1000.0
    names = np.array([norm_bone_name(str(n)) for n in body.joint_names] or [""])
    top = names[np.clip(body.joints[np.arange(len(P)), body.weights.argmax(1)], 0, len(names) - 1)]
    hand = np.char.startswith(top.astype(str), f"{side}hand")
    ar.check(fr["centre"], P[hand], sized)
    V, F, N = ar.band(fr, radius, width, thickness)
    bone = joint_index(body, fr["bone"])
    J = np.zeros((len(V), 4), np.int64)
    J[:, 0] = bone
    W = np.zeros((len(V), 4))
    W[:, 0] = 1.0
    curve = ar.centre_line(fr, radius, thickness)
    metrics = {"inner_radius_mm": round(radius * 1000.0, 2), "estimate_mm": sized["estimate_mm"],
               "range_mm": [round(x, 3) for x in sized["range_mm"]], "clamped": sized["clamped"],
               "hand_width_mm": sized["hand_width_mm"], "bone_length_mm": sized["bone_length_mm"],
               "height_m": round(height, 3), "length_m": {side: round(2 * np.pi * radius, 4)},
               "triangles": int(len(F)), "vertices": int(len(V)),
               "joints": {str(body.joint_names[bone]): 1.0}, "cpu_s": round(time.monotonic() - started, 2)}
    landmarks = {side: {"centre": np.round(fr["centre"], 5).tolist(), "axis": np.round(fr["axis"], 4).tolist(),
                        "bone": str(body.joint_names[bone])}}
    return {"V": V, "F": F, "N": N, "J": J, "W": W, "joint_names": list(body.joint_names), "curve": curve,
            "landmarks": landmarks, "metrics": metrics}


def make_glasses(rigged: bytes, spec: Dict[str, Any]) -> Dict[str, Any]:
    """Glasses (``accessory_glasses``): the frame (rims, bridge, nose pads, temples) and the lenses, sized and placed
    from the face, gated against the body, every vertex rigid on the Head (weight 1.0). ``{V, F, N, J, W,
    joint_names, curve, landmarks, metrics, lens: {V, F, N, J, W}, temple_faces}``. Pure CPU."""
    from app.core import accessory_glasses as ag
    from app.core.rig_contract import norm_bone_name
    started = time.monotonic()
    body, dense, Pw, Fw, first, _Fo = _body_context(rigged)
    head = [i for i, n in enumerate(body.joint_names) if norm_bone_name(str(n)) == "head"]
    if not head:
        raise KeyError("head")
    made = ag.build(body, dense, Pw, Fw, first, spec)

    def rigid(n: int):
        J = np.zeros((n, 4), np.int64)
        J[:, 0] = head[0]
        W = np.zeros((n, 4))
        W[:, 0] = 1.0
        return J, W
    J, W = rigid(len(made["V"]))
    lens = dict(made["lens"])
    lens["J"], lens["W"] = rigid(len(lens["V"]))
    metrics = {**made["metrics"], "joints": {str(body.joint_names[head[0]]): 1.0},
               "cpu_s": round(time.monotonic() - started, 2)}
    return {"V": made["V"], "F": made["F"], "N": made["N"], "J": J, "W": W, "joint_names": list(body.joint_names),
            "curve": made["curve"], "landmarks": made["landmarks"], "metrics": metrics, "lens": lens,
            "temple_faces": made["temple_faces"]}


#: A234: a hoop hangs tilted this far out at the bottom (its plane turned about the front-back axis).
HOOP_TILT_DEG = 15.0
#: The least air an earring may keep to the head (the target is ``accessory_band.GAP_M``; a hoop that cannot get
#: this clear of the jaw is refused).
EARRING_MIN_GAP_MM = 1.9


def _clear_of_head(V: np.ndarray, n: np.ndarray, Pw: np.ndarray, Fw: np.ndarray, passes: int = 6) -> np.ndarray:
    """``V`` moved along ``n`` (the lobe's outward side) until it is at least ``accessory_band.GAP_M`` off the body
    (the ear is a thin, slanted flap — a ball placed on its rim point can still touch it)."""
    from app.core.accessory_band import GAP_M
    from app.core.garment_shell import signed_distance
    V = np.asarray(V, np.float64)
    for _ in range(passes):
        d = float(signed_distance(V, Pw, Fw, kq=POSE_KQ).min())
        if d >= GAP_M - 1e-5:
            break
        V = V + n * (GAP_M - d + 1e-4)
    return V


#: A234: an earring stands at most this far off the lobe it hangs on (mm).
EARRING_MAX_GAP_MM = 8.0
#: A234 LOD (decision J4): the kinds the distance tier leaves off (a ring is ~1 px there).
LOW_TIER_DROPPED = ("ring",)


def preview_rings(character_name: str, spec: Dict[str, Any], *,
                  profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """A234: the centre lines of a band / tube kind for unsaved settings ``spec`` (normalized) on the current plain
    body — the Wardrobe's live preview while a slider moves: ``{rings: [[[x, y, z]…]…], landmarks, radius_m}``; the
    body's surface only (the clothing under it is taken by the Build). Earrings: the lobe points. A238: the ring's
    middle circle at the size the Build gives it (the skeleton only, ``accessory_ring``). Glasses: the lens outlines,
    bridge and temples (``accessory_glasses.layout``) and their sizes. CPU only; nothing stored."""
    from app.core import accessory_band as ab
    from app.core.accessory_spec import BAND_KINDS as SPEC_BAND_KINDS
    from app.models.character import get_character_dir
    profile = _profile_of(character_name, profile)
    base = _current_base(character_name, profile)
    if base is None:
        raise ValueError(REASON_NO_BODY)
    rigged = (get_character_dir(character_name) / "model3d" / f"{base[0]}.glb").read_bytes()
    if spec["kind"] == "ring":
        from app.core import accessory_ring as ar, glb_mesh
        body = glb_mesh.body_arrays(rigged)
        P = np.asarray(body.positions, np.float64)
        sized = ar.size(body.joint_positions, spec["finger"], spec["side"], float(np.ptp(P[:, 1])))
        fr = ar.frame(body.joint_positions, spec["finger"], spec["side"], spec["ring"]["along"])
        thickness = float(spec["chain"]["thickness_mm"]) / 1000.0
        return {"rings": [np.round(ar.centre_line(fr, sized["radius_m"], thickness), 5).tolist()],
                "landmarks": {spec["side"]: {"centre": np.round(fr["centre"], 5).tolist()}},
                "radius_m": thickness / 2, "inner_radius_mm": round(float(sized["radius_m"]) * 1000.0, 2)}
    body, dense, Pw, Fw, first, _Fo = _body_context(rigged)
    rings, marks = [], {}
    if spec["kind"] == "glasses":
        # the lens outlines, the bridge and the temples where the Build lays them (before its gate's pushes)
        from app.core import accessory_glasses as ag
        P, F = np.asarray(body.positions, np.float64), np.asarray(body.faces, np.int64)
        lm = ag.face_landmarks(P, F, body.joint_positions)
        ears = {side: ag.ear_info(Pw, dense[first], body.joint_names, body.joint_positions, side, lm["eye_y"])
                for side in ("left", "right")}
        lay = ag.layout(lm, ag.head_samples(P, F, ag._bone(body.joint_positions, "head")), spec["glasses"], ears,
                        float(np.ptp(P[:, 1])))
        lines = [*lay["lenses"].values(), *lay["bridges"], *lay["temples"].values()]
        return {"rings": [np.round(x, 5).tolist() for x in lines],
                "landmarks": {"nose_tip": np.round(lm["nose_tip"], 5).tolist()},
                "radius_m": ag.frame_section(spec["glasses"])[0],
                "glasses": {"frame_mm": round(lay["W"] * 2000.0, 1),
                            "lens_mm": [round(lay["w"] * 1000.0, 1), round(lay["h"] * 1000.0, 1)],
                            "bridge_mm": round(lay["b"] * 2000.0, 1),
                            "ear_used": {s: bool(e["used"]) for s, e in ears.items()}}}
    if spec["kind"] == "earrings":
        for side in ab.sides_of(spec):
            p = ab.ear_anchor(Pw, dense[first], body.joint_names, body.joint_positions, side)["point"]
            rings.append([np.round(p, 5).tolist()])
        return {"rings": rings, "landmarks": marks, "radius_m": float(spec["earring"]["size_mm"]) / 2000.0}
    for side in ab.sides_of(spec):
        fr = ab.frame(spec, body.joint_positions, side)
        Fb = ab.dominant_faces(Fw, dense[first], body.joint_names, ab.joints_for(spec, side))
        surf = ab.surface_radius(Pw, Fb, [], fr, [0.0], reach=ab.REACH_M[spec["kind"]], what=AROUND_WHAT[fr["key"]])
        t = ab.smooth_up(surf["t"])[0] + ab.GAP_M
        rings.append(np.round(ab.ring_curve(fr, t, surf["dirs"]), 5).tolist())
        marks[side or "centre"] = {"centre": np.round(fr["centre"], 5).tolist()}
    radius = (float(spec["band"]["width_cm"]) / 200.0 if spec["kind"] in SPEC_BAND_KINDS
              else float(spec["chain"]["thickness_mm"]) / 2000.0)
    out = {"rings": rings, "landmarks": marks, "radius_m": radius}
    if spec["kind"] == "belt" and rings:
        out["anchors"] = link_anchors(np.asarray(rings[0], np.float64), spec)
    return out


def link_anchors(curve: np.ndarray, spec: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Design G: where each part link of a belt sits on its centre line ``curve`` — the Wardrobe's blue placeholder
    box: ``[{index, role, at: [x, y, z], out: [x, y, z]}]`` in link order (``accessory_spec.links``), ``at`` the curve
    point at the link's angle (``curve_point_at``) moved down by a hanging charm's drop, ``out`` the horizontal outward
    direction there. A preview only: the Build places the part against the band and the body (``attach_part``)."""
    from app.core import accessory_spec
    C = np.asarray(curve, np.float64)
    if len(C) == 0:
        return []
    c = C.mean(0)
    out = []
    for i, link in enumerate(accessory_spec.links(spec)):
        k = curve_point_at(C, link["at_deg"])
        p = C[k].copy()
        h = p - c
        h[1] = 0.0
        n = float(np.linalg.norm(h))
        h = h / n if n > 1e-9 else np.array([0.0, 0.0, 1.0])
        if link.get("mount") == "hang":
            p[1] -= float(link.get("drop_cm") or 0.0) / 100.0
        out.append({"index": i, "role": link["role"], "at": np.round(p, 5).tolist(), "out": np.round(h, 5).tolist()})
    return out
