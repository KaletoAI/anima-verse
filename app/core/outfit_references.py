"""Outfit reference images — the dressed front of an outfit made FROM A PICTURE
(Ruling A74b; the base front's counterpart is ``base_body.front_reference``).

The user, 2026-11-14: the A-pose made from text gives every character nearly the
same build, so the A-pose is made from a reference image — the plain body's
front from the profile image, and an outfit's dressed front from a picture of
the character WEARING that outfit, when one is set. Unset, the dressed views
stay what they were (an edit of the body's front, or a copy of the body shape's
view — ``base_body.dressed_view_source``, Ruling A70).

WHAT AN OUTFIT IS here: what the Figure tab's "Dressed views" and "Outfit model"
show — the WORN COMBINATION of clothing pieces, with the pieces worn open
(``outfit_key``: the sorted worn item ids and the sorted open ids). Held items
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


def record_for(character_name: str, pieces: Optional[Dict[str, str]], open_ids: Iterable[str] = (), *,
               profile: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """The record of the outfit ``pieces`` (+ open ids), None without one."""
    record = references_of(character_name, profile=profile).get(outfit_key(pieces, open_ids))
    return dict(record) if record else None


def wanted_sha(character_name: str, pieces: Optional[Dict[str, str]], open_ids: Iterable[str] = (), *,
               profile: Optional[Dict[str, Any]] = None) -> str:
    """The picture content the outfit's dressed views are made for: the
    record's ``sha256``, "" without a reference."""
    record = record_for(character_name, pieces, open_ids, profile=profile)
    return str(record["sha256"]) if record else ""


def texture_part(character_name: str, pieces: Optional[Dict[str, str]], open_ids: Iterable[str] = (), *,
                 profile: Optional[Dict[str, Any]] = None) -> str:
    """What the reference adds to a PAINTED figure's texture key: its
    ``sha256`` ("" without one — the key then stays byte-identical to the one
    before references existed)."""
    return wanted_sha(character_name, pieces, open_ids, profile=profile)


def image_path(character_name: str, record: Optional[Dict[str, Any]]) -> Optional[Path]:
    """The gallery file of ``record``, None when it is gone or outside the
    character's gallery."""
    if not record or not _valid(record):
        return None
    from app.models.character import get_character_images_dir
    try:
        root = get_character_images_dir(character_name).resolve()
        path = (root / record["image"]).resolve()
        return path if path.is_relative_to(root) and path.is_file() else None
    except (OSError, RuntimeError, ValueError):
        return None


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
    """``(pieces, open ids)`` worn now."""
    from app.core.model_refs import live_piece_state
    pieces = dict(profile.get("equipped_pieces") or {})
    open_ids = sorted(live_piece_state(character_name, pieces, profile))
    return pieces, open_ids


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
        pieces, open_ids = _worn(character_name, profile)
        key = outfit_key(pieces, open_ids)
        record = {"image": name, "sha256": hashlib.sha256(data).hexdigest(),
                  "label": _label(character_name, pieces), "set_at": utc_now_iso()}
        records = _records_of(profile)
        records[key] = record
        profile[PROFILE_KEY] = records
        if not save_character_profile(character_name, profile):
            raise RuntimeError("The reference was not saved")
    _invalidate()
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


def store_upload(character_name: str, data: bytes, filename: str) -> str:
    """An uploaded picture (already capped and checked by the route:
    ``read_upload_capped`` / ``ensure_image``) into the character's gallery,
    as the gallery upload stores one. Returns its file name."""
    import time
    from app.models.character import add_character_image, get_character_images_dir
    suffix = Path(filename or "").suffix.lower()
    if suffix not in (".png", ".jpg", ".jpeg", ".webp"):
        raise ValueError("Format not supported — PNG, JPEG or WebP")
    images = get_character_images_dir(character_name)
    stem = f"{character_name}_{int(time.time())}_outfitref"
    target = images / f"{stem}{suffix}"
    n = 1
    while target.exists():
        n += 1
        target = images / f"{stem}{n}{suffix}"
    target.write_bytes(data)
    add_character_image(character_name, target.name)
    return target.name


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
    from urllib.parse import quote
    from app.core import base_body
    from app.models.character import get_character_profile
    profile = get_character_profile(character_name) or {}
    pieces, open_ids = _worn(character_name, profile)
    key = outfit_key(pieces, open_ids)
    records = _records_of(profile)
    enc = quote(character_name, safe="")

    def url_of(record: Dict[str, Any]) -> str:
        path = image_path(character_name, record)
        if path is None:
            return ""
        try:
            stamp = path.stat().st_mtime_ns
        except OSError:
            return ""
        return f"/characters/{enc}/images/{quote(path.name, safe='')}?v={stamp}"

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
    return {"key": key, "label": _label(character_name, pieces), "record": record,
            "url": url_of(record) if record else "", "gone": bool(record) and image_path(character_name, record) is None,
            "applies": applies, "note": "" if applies or not record else NOT_PAINTED_NOTE,
            "source": source.get("source") or "", "jobs": jobs, "others": others}
