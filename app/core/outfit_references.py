"""Outfit reference images — the dressed front of an outfit made FROM A PICTURE
(Ruling A74b; the base front's counterpart is ``base_body.front_reference``).

The user, 2026-11-14: the A-pose made from text gives every character nearly the
same build, so the A-pose is made from a reference image — the plain body's
front from the profile image, and an outfit's dressed front from a picture of
the character WEARING that outfit, when one is set. Unset, the dressed views
stay what they were (an edit of the body's front, or a copy of the body shape's
view — ``base_body.dressed_view_source``, Ruling A70).

WHAT AN OUTFIT IS here: the PAINTED SET of the worn combination (Ruling A115,
spec 2026-11-12-unified-worn-pieces "Reuse, not rebuild": a texture is cached by
the set of painted pieces on its shape) — the worn pieces the figure paints,
with those of them worn open (``reference_key`` = ``outfit_key`` of
``painted_pieces``). An own-mesh piece (or a HairDeck/HAAR hairstyle) and an
in-body piece are no part of it: the picture shows the body wearing ONLY the
painted pieces, so adding, removing or swapping an own-mesh piece keeps the
reference, the texture key and its stored views — no image job. Held items
are not part of it (a picture of the outfit does not change with what is held),
nor the own-mesh token or the base variant (technical keys that move when a
piece's mesh lands — a reference must not vanish with them). Two saved outfits
with the same pieces are one outfit here, as the Figure tab names them
(``figure_build._outfit_name``).

STORAGE: the character profile in world.db, key ``outfit_references`` —
``{outfit key: {image, sha256, label, set_at}}``: ``image`` a file of the
character's gallery (``images/``), ``sha256`` its content when it was picked,
``label`` what the outfit was called then (the saved outfit's name, else the
piece names), ``set_at`` a SYSTEM stamp. DB-only: no JSON file, no copy of the
picture. A picture deleted from the gallery leaves the record standing — the
render then refuses with ``REFERENCE_GONE`` (never a silent fallback).

WHAT IT CHANGES (``applied``): only an outfit whose dressed front is an EDIT —
something is painted on the figure (``base_body._paints``). Then the
picture's content is part of the figure's texture key
(``figure.texture_key`` → ``texture_part``), so the outfit gets its own
painted texture, its own texture store and its own model, and its dressed front
is an edit of the picture (``base_body._render_views``); every dressed view
records ``outfit_reference_sha256`` and one made for another picture is not
current (``base_body.dressed_image``). An outfit with nothing painted (its
pieces are in the body shape or are their own meshes) keeps its copies — the
reference is stored but not used, and the Figure tab says so.

NOTHING RUNS: picking, uploading or clearing only saves (and drops the memoised
figure). The dressed front then shows as due with its cost; the Build you start
renders it — or the automatic Build on a LATER trigger, when "Build
automatically" is on. The ``outfit_rebuild`` improvement never rebuilds an
outfit whose only change is its reference (``reference_only_change``).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from app.core.log import get_logger

logger = get_logger("outfit_references")

#: The profile key of the records.
PROFILE_KEY = "outfit_references"
#: The render's refusal when the picked picture is gone from the gallery.
REFERENCE_GONE = "The outfit's full-body reference is gone from the gallery — pick another one or clear it"
#: Why a set reference is not used now (the Figure tab's line).
NOT_PAINTED_NOTE = ("Not used now: nothing is painted on this figure — its pieces are in the body shape or have "
                    "their own mesh, so the dressed views are copies")


def outfit_key(pieces: Optional[Dict[str, str]], open_ids: Iterable[str] = ()) -> str:
    """``"or"`` + 10 hex over the sorted worn item ids and the sorted ids worn
    open — the key of an outfit (module docstring). ``"or"`` + the hash of
    nothing worn for an empty combination."""
    ids = sorted({str(v).strip() for v in (pieces or {}).values() if v and str(v).strip()})
    worn = set(ids)
    opened = sorted({str(i) for i in open_ids or () if str(i) in worn})
    raw = json.dumps({"pieces": ids, "open": opened}, sort_keys=True, separators=(",", ":"))
    return "or" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:10]


def _valid(record: Any) -> bool:
    return (isinstance(record, dict) and isinstance(record.get("image"), str) and bool(record["image"])
            and Path(record["image"]).name == record["image"] and isinstance(record.get("sha256"), str)
            and bool(record["sha256"]))


def _records_of(profile: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    raw = (profile or {}).get(PROFILE_KEY)
    if not isinstance(raw, dict):
        return {}
    return {str(k): dict(v) for k, v in raw.items() if _valid(v)}


def _read_records(character_name: str) -> Dict[str, Dict[str, Any]]:
    """The records straight from the profile row — one cheap read for the
    hot paths that hold no profile (``base_body.dressed_image``)."""
    try:
        from app.core.db import get_connection
        row = get_connection().execute(
            "SELECT json_extract(profile_json, '$.outfit_references') FROM characters WHERE name=?",
            (character_name,)).fetchone()
    except Exception:  # noqa: BLE001 — unreadable = none; the profile read elsewhere reports it
        logger.debug("Outfit references of %s unreadable", character_name, exc_info=True)
        return {}
    if not row or not row[0]:
        return {}
    try:
        return _records_of({PROFILE_KEY: json.loads(row[0])})
    except ValueError:
        return {}


def references_of(character_name: str, *, profile: Optional[Dict[str, Any]] = None) -> Dict[str, Dict[str, Any]]:
    """Every outfit's record ``{key: {image, sha256, label, set_at}}``."""
    return _records_of(profile) if profile is not None else _read_records(character_name)


def painted_pieces(pieces: Optional[Dict[str, str]], painted: Iterable[str]) -> Dict[str, str]:
    """``{slot: item id}`` of ``pieces`` whose item is in ``painted`` (a figure's / worn set's painted ids)."""
    keep = {str(i) for i in painted or ()}
    return {str(slot): str(iid) for slot, iid in (pieces or {}).items() if iid and str(iid).strip() in keep}


def reference_key(pieces: Optional[Dict[str, str]], open_ids: Iterable[str], painted: Iterable[str]) -> str:
    """The key of an outfit's reference (Ruling A115): ``outfit_key`` of its PAINTED pieces only."""
    return outfit_key(painted_pieces(pieces, painted), open_ids)


def record_for(character_name: str, pieces: Optional[Dict[str, str]], open_ids: Iterable[str] = (), *,
               painted: Iterable[str], profile: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """The record of the painted set ``painted`` of the outfit ``pieces`` (+ open ids), None without one."""
    record = references_of(character_name, profile=profile).get(reference_key(pieces, open_ids, painted))
    return dict(record) if record else None


def wanted_sha(character_name: str, pieces: Optional[Dict[str, str]], open_ids: Iterable[str] = (), *,
               painted: Iterable[str], profile: Optional[Dict[str, Any]] = None) -> str:
    """The picture content the outfit's dressed views are made for: the
    record's ``sha256``, "" without a reference."""
    record = record_for(character_name, pieces, open_ids, painted=painted, profile=profile)
    return str(record["sha256"]) if record else ""


def texture_part(character_name: str, pieces: Optional[Dict[str, str]], open_ids: Iterable[str] = (), *,
                 painted: Iterable[str], profile: Optional[Dict[str, Any]] = None) -> str:
    """What the reference adds to a PAINTED figure's texture key: its
    ``sha256`` ("" without one — the key then stays byte-identical to the one
    before references existed)."""
    return wanted_sha(character_name, pieces, open_ids, painted=painted, profile=profile)


#: The sub-folder of ``model_refs`` that holds the reference pictures made FOR a figure — generated (plain body,
#: outfits) or uploaded as a reference: never the gallery (user rule 2026-11-16, with Ruling A125). A folder,
#: so no file name in it is read as a signature of ``model_refs``. A picture PICKED from the gallery (origin
#: "gallery", or an older record without an origin) stays in the gallery.
REFERENCES_DIR = "references"
#: Record origins whose file lives in ``REFERENCES_DIR``.
STORED_ORIGINS = ("generated", "upload")


def references_dir(character_name: str) -> Path:
    """``model_refs/references`` of the character (not created)."""
    from app.core.model_refs import get_model_refs_dir
    return get_model_refs_dir(character_name) / REFERENCES_DIR


def _folder(character_name: str, record: Dict[str, Any]) -> Path:
    from app.models.character import get_character_images_dir
    return (references_dir(character_name) if record.get("origin") in STORED_ORIGINS
            else get_character_images_dir(character_name))


def image_path(character_name: str, record: Optional[Dict[str, Any]]) -> Optional[Path]:
    """The file of ``record``: in ``references_dir`` for a generated or uploaded reference
    (``STORED_ORIGINS``), else in the gallery (a pick); None when it is gone or the name points outside."""
    if not record or not _valid(record):
        return None
    try:
        root = _folder(character_name, record).resolve()
        path = (root / record["image"]).resolve()
        return path if path.is_relative_to(root) and path.is_file() else None
    except (OSError, RuntimeError, ValueError):
        return None


def reference_url(character_name: str, path: Optional[Path]) -> str:
    """The URL of a reference file (``image_path``): one in ``references_dir`` through the figure route
    ``/characters/<c>/figure/reference-image/<name>``, a gallery one through ``/characters/<c>/images/<name>``;
    ``?v=`` its mtime. "" for None or a file gone."""
    from urllib.parse import quote
    if path is None:
        return ""
    try:
        stamp = path.stat().st_mtime_ns
        stored = path.parent.resolve() == references_dir(character_name).resolve()
    except OSError:
        return ""
    where = "figure/reference-image" if stored else "images"
    return f"/characters/{quote(character_name, safe='')}/{where}/{quote(path.name, safe='')}?v={stamp}"


def store_reference(character_name: str, data: bytes, suffix: str, tag: str) -> str:
    """Bytes (a generated picture, or an upload already capped and checked by its route) into
    ``references_dir`` as ``<name>_<stamp>_<tag><suffix>`` — never the gallery. Returns the file name."""
    import time
    suffix = (suffix or ".png").lower()
    if suffix not in (".png", ".jpg", ".jpeg", ".webp"):
        raise ValueError("Format not supported — PNG, JPEG or WebP")
    folder = references_dir(character_name)
    folder.mkdir(parents=True, exist_ok=True)
    stem = f"{character_name}_{int(time.time())}_{tag}"
    target = folder / f"{stem}{suffix}"
    n = 1
    while target.exists():
        n += 1
        target = folder / f"{stem}{n}{suffix}"
    target.write_bytes(data)
    return target.name


def move_gallery_references(character_name: str) -> List[str]:
    """One-time move (user rule 2026-11-16, idempotent): every picture a record of the character still uses
    from the GALLERY although its origin stores it in ``references_dir`` (``STORED_ORIGINS`` — generated or
    uploaded before the rule) is moved there with its ``.json`` sidecar (``os.replace``, one log line each).
    The records keep the file NAME, which now resolves in ``references_dir`` (``image_path``), and the dressed
    views' sidecars name the picture by file name and content sha — so no pointer changes. The profile image is
    never moved; unreferenced pictures stay in the gallery. Returns the moved names."""
    import os
    from app.core.keyed_lock import keyed_lock
    from app.core import full_body_reference
    from app.models.character import get_character_images_dir, get_character_profile
    moved: List[str] = []
    with keyed_lock("character_profile", character_name):
        profile = get_character_profile(character_name) or {}
        records = [profile.get(full_body_reference.PROFILE_KEY), *(profile.get(PROFILE_KEY) or {}).values()]
        gallery = get_character_images_dir(character_name)
        target_dir = references_dir(character_name)
        for record in records:
            if not isinstance(record, dict) or record.get("origin") not in STORED_ORIGINS:
                continue
            name = str(record.get("image") or "")
            if not name or Path(name).name != name or name == profile.get("profile_image"):
                continue
            source = gallery / name
            if not source.is_file() or (target_dir / name).exists():
                continue
            target_dir.mkdir(parents=True, exist_ok=True)
            os.replace(source, target_dir / name)
            sidecar = source.with_suffix(".json")
            if sidecar.is_file():
                os.replace(sidecar, (target_dir / name).with_suffix(".json"))
            logger.info("Reference picture of %s moved out of the gallery: %s", character_name, name)
            moved.append(name)
    if moved:
        from app.core import figure
        figure.invalidate()
    return moved


def move_all_gallery_references() -> int:
    """``move_gallery_references`` for every character (boot); a failing character is logged and skipped."""
    from app.models.character import list_available_characters
    total = 0
    for name in list_available_characters():
        try:
            total += len(move_gallery_references(name))
        except Exception as e:  # noqa: BLE001 — one character never stops the boot
            logger.warning("Reference pictures of %s not moved: %s", name, e)
    return total


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _label(character_name: str, pieces: Dict[str, str]) -> str:
    """The saved outfit's name when one has exactly these pieces, else the
    worn pieces' names joined."""
    from app.core.figure_build import _outfit_name
    name = _outfit_name(character_name, pieces)
    if name:
        return name
    from app.models.inventory import get_item
    names = [str((get_item(i) or {}).get("name") or i) for i in sorted({str(v) for v in pieces.values() if v})]
    return ", ".join(names) or "Nothing worn"


def _worn(character_name: str, profile: Dict[str, Any]):
    """``(pieces, open ids, painted ids)`` worn now — the painted ids of ``figure.worn_sets``."""
    from app.core import figure
    from app.core.model_refs import live_piece_state
    pieces = dict(profile.get("equipped_pieces") or {})
    open_ids = sorted(live_piece_state(character_name, pieces, profile))
    painted = figure.worn_sets(character_name, pieces=pieces, profile=profile).painted
    return pieces, open_ids, painted


def set_reference(character_name: str, image: str) -> Dict[str, Any]:
    """Pick the gallery picture ``image`` as the reference of the outfit worn
    NOW. Saves only (module docstring "NOTHING RUNS"). ValueError for a file
    that is not in the gallery or not an image; RuntimeError when the profile
    was not saved. Returns ``{key, record}``."""
    from app.core.keyed_lock import keyed_lock
    from app.core.timeutils import utc_now_iso
    from app.core.upload_limits import ensure_image
    from app.models.character import get_character_profile, save_character_profile
    name = str(image or "").strip()
    if not name or Path(name).name != name:
        raise ValueError("Pick a picture of the character's gallery")
    path = image_path(character_name, {"image": name, "sha256": "-"})
    if path is None:
        raise ValueError(f"Not in the gallery: {name}")
    data = path.read_bytes()
    try:
        ensure_image(data, filename=name, what="Reference image")
    except Exception as e:  # HTTPException of the upload helpers
        raise ValueError(f"Not an image: {name}") from e
    with keyed_lock("character_profile", character_name):
        profile = get_character_profile(character_name) or {}
        pieces, open_ids, painted = _worn(character_name, profile)
        key = reference_key(pieces, open_ids, painted)
        record = {"image": name, "sha256": hashlib.sha256(data).hexdigest(),
                  "label": _label(character_name, painted_pieces(pieces, painted)), "set_at": utc_now_iso()}
        records = _records_of(profile)
        records[key] = record
        profile[PROFILE_KEY] = records
        if not save_character_profile(character_name, profile):
            raise RuntimeError("The reference was not saved")
    _invalidate()
    from app.core import full_body_reference
    full_body_reference.clear_auto_failure(character_name, key)   # Ruling A104: a picked picture allows a retry
    logger.info("Outfit reference of %s (%s, %s): %s", character_name, key, record["label"], name)
    return {"key": key, "record": record}


def clear_reference(character_name: str, key: str) -> bool:
    """Drop the reference of the outfit ``key``. Saves only. False when there
    was none; RuntimeError when the profile was not saved."""
    from app.core.keyed_lock import keyed_lock
    from app.models.character import get_character_profile, save_character_profile
    with keyed_lock("character_profile", character_name):
        profile = get_character_profile(character_name) or {}
        records = _records_of(profile)
        if key not in records:
            return False
        del records[key]
        if records:
            profile[PROFILE_KEY] = records
        else:
            profile.pop(PROFILE_KEY, None)
        if not save_character_profile(character_name, profile):
            raise RuntimeError("The reference was not cleared")
    _invalidate()
    logger.info("Outfit reference of %s (%s) cleared", character_name, key)
    return True


def _invalidate() -> None:
    """A reference changes the figure's texture key: drop the memoised figures."""
    from app.core import figure
    figure.invalidate()


def reference_only_change(character_name: str, meta: Dict[str, Any], *,
                          profile: Optional[Dict[str, Any]] = None) -> bool:
    """Whether the stored outfit model ``meta`` is stale ONLY because its
    outfit's reference was set, changed or cleared since it was built: the
    figure delivered now with every reference left out has the model's shape
    and texture. The ``outfit_rebuild`` improvement passes such a model over —
    a person starts that render (module docstring "NOTHING RUNS")."""
    from app.core import figure
    built = figure.built_figure(meta)
    if built is None:
        return False
    from app.models.character import get_character_profile
    profile = dict(profile if profile is not None else (get_character_profile(character_name) or {}))
    pieces = dict(meta.get("pieces") or {})
    open_state = {i: "open" for i in built.open}
    now = figure.delivered_figure_cached(character_name, profile=profile, pieces=pieces,
                                         items=list(meta.get("items") or []), piece_state=open_state)
    if (built.shape, built.texture) == (now.shape, now.texture):
        return False
    bare = {k: v for k, v in profile.items() if k != PROFILE_KEY}
    without = figure.delivered_figure_cached(character_name, profile=bare, pieces=pieces,
                                             items=list(meta.get("items") or []), piece_state=open_state)
    return (built.shape, built.texture) == (without.shape, without.texture)


def info(character_name: str) -> Dict[str, Any]:
    """The Figure tab's "Reference image" row (``GET …/figure/outfit-reference``):
    ``{key, label, record, url, applies, note, source, jobs, others}`` —
    the outfit worn now (``record`` None without a reference; ``url`` its
    gallery URL, "" when gone; ``applies``: the dressed front is an edit, so
    the picture is used; ``note``: why it is not; ``jobs``: the image jobs of
    the dressed views due now — what the next Build renders for the outfit's
    views), and ``others``: the other outfits with a reference
    ``[{key, label, image, url, set_at}]``."""
    from app.core import base_body
    from app.models.character import get_character_profile
    profile = get_character_profile(character_name) or {}
    pieces, open_ids, painted = _worn(character_name, profile)
    key = reference_key(pieces, open_ids, painted)
    records = _records_of(profile)

    def url_of(record: Dict[str, Any]) -> str:
        return reference_url(character_name, image_path(character_name, record))

    record = records.get(key)
    source: Dict[str, Any] = {}
    try:
        source = base_body.dressed_view_source(character_name, profile=profile) or {}
    except Exception:  # noqa: BLE001 — the row never breaks the poll
        logger.debug("Dressed view source of %s unreadable", character_name, exc_info=True)
    applies = source.get("source") == base_body.VIEW_SOURCE_PAINTED
    jobs: Optional[int] = None
    try:
        from app.core import figure
        from app.core.model_refs import current_outfit_state
        _p, _items, signature = current_outfit_state(character_name)
        fig = figure.delivered_figure_cached(character_name, profile=profile)
        jobs = base_body.dressed_view_estimate(character_name, fig, signature, profile=profile)
    except Exception:  # noqa: BLE001 — unknown, never a silent 0
        logger.debug("Dressed view estimate of %s unreadable", character_name, exc_info=True)
    others: List[Dict[str, Any]] = [
        {"key": k, "label": str(r.get("label") or ""), "image": r["image"], "url": url_of(r),
         "set_at": str(r.get("set_at") or "")}
        for k, r in sorted(records.items(), key=lambda kv: str(kv[1].get("set_at") or ""), reverse=True)
        if k != key]
    return {"key": key, "label": _label(character_name, painted_pieces(pieces, painted)), "record": record,
            "url": url_of(record) if record else "", "gone": bool(record) and image_path(character_name, record) is None,
            "applies": applies, "note": "" if applies or not record else NOT_PAINTED_NOTE,
            "source": source.get("source") or "", "jobs": jobs, "others": others}
