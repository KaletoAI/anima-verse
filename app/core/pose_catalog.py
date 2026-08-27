"""Pose/expression catalog - the finite render-key axes (plan-pose-katalog.md).

The catalog entry key is the ONLY key under which 2D image variants are
cached and 3D animation clips are resolved. Free text never reaches a
render path; it survives only as sanitized "flavor" prompt text.
"""
import json
import re
import threading
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from app.core.log import get_logger

logger = get_logger("pose_catalog")

AXES = ("pose", "expression")
_FILES = {
    "pose": ("pose", "pose_catalog.json"),
    "expression": ("expression", "expression_catalog.json"),
}
_FALLBACK_DEFAULT = {"pose": "standing", "expression": "neutral"}

_lock = threading.Lock()
_cache: Dict[str, Dict[str, dict]] = {}
_groups_cache: Dict[str, dict] = {}


def catalog_path(axis: str) -> Path:
    """File the catalog of this axis lives in — the ONE place the admin
    editor writes to as well. Raises KeyError on an unknown axis."""
    from app.core.paths import get_shared_dir
    sub, name = _FILES[axis]
    return get_shared_dir() / "templates" / sub / name


def _load(axis: str) -> Dict[str, dict]:
    try:
        data = json.loads(catalog_path(axis).read_text(encoding="utf-8"))
        entries = data.get("entries") or {}
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.warning("catalog %s unreadable: %s", axis, e)
        entries = {}
    out: Dict[str, dict] = {}
    for key, entry in entries.items():
        solo = bool(entry.get("solo", True))
        norm = {
            "prompt": str(entry.get("prompt") or ""),
            "synonyms": [str(s).strip().lower() for s in (entry.get("synonyms") or []) if str(s).strip()],
            "animation": str(entry.get("animation") or ""),
            "solo": solo,
            "_default": bool(entry.get("_default", False)),
        }
        if axis == "pose":
            # Place types are POSE vocabulary — an expression has no place.
            # plan-posen-plaetze.md § 3.2: the PLACE TYPE the pose needs.
            norm["group"] = str(entry.get("group") or "").strip().lower()
            # pair poses only: slots of the anchor marker the pair consumes,
            # and how the clip frame (+X = A->B) turns against the marker
            # facing. A solo pose occupies exactly one place and never turns.
            norm["places"] = (1 if solo
                              else max(1, min(2, int(entry.get("places") or 2))))
            norm["yaw_offset"] = (0.0 if solo
                                  else float(entry.get("yaw_offset") or 0.0))
            norm["_stray_pair_fields"] = solo and ("places" in entry
                                                   or "yaw_offset" in entry)
        out[str(key).strip().lower()] = norm
    return out


def _load_groups() -> Dict[str, dict]:
    """Place types of the pose axis (plan-posen-plaetze.md § 3.1): the finite
    vocabulary a MARKER speaks. ``root_drop`` x figure height is how far a
    figure's root sinks below the marked surface; ``default`` the pose a
    "sit here" click sets."""
    try:
        data = json.loads(catalog_path("pose").read_text(encoding="utf-8"))
        raw = data.get("groups") or {}
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.warning("pose groups unreadable: %s", e)
        raw = {}
    out: Dict[str, dict] = {}
    for key, spec in raw.items():
        k = str(key).strip().lower()
        if not k or not isinstance(spec, dict):
            continue
        try:
            drop = float(spec.get("root_drop") or 0.0)
        except (TypeError, ValueError):
            drop = 0.0
        out[k] = {"label": str(spec.get("label") or k),
                  "root_drop": round(max(0.0, min(1.0, drop)), 3),
                  "default": str(spec.get("default") or "").strip().lower()}
    return out


def get_groups() -> Dict[str, dict]:
    """All place types, keyed by group id."""
    with _lock:
        if not _groups_cache:
            _groups_cache.update(_load_groups())
        return dict(_groups_cache)


def get_catalog(axis: str) -> Dict[str, dict]:
    with _lock:
        if axis not in _cache:
            _cache[axis] = _load(axis)
        return _cache[axis]


def reload_catalogs() -> None:
    with _lock:
        _cache.clear()
        _groups_cache.clear()
        _embed_cache.clear()


def get_default_key(axis: str) -> str:
    for key, entry in get_catalog(axis).items():
        if entry["_default"]:
            return key
    return _FALLBACK_DEFAULT[axis]


def group_of(pose_key: str) -> str:
    """Place type a pose needs ("" = unknown key or ungrouped entry)."""
    entry = get_catalog("pose").get((pose_key or "").strip().lower())
    return (entry or {}).get("group", "")


def poses_in_group(group: str) -> List[str]:
    """Keys of the group, the group's default first, the rest alphabetical."""
    g = (group or "").strip().lower()
    default = (get_groups().get(g) or {}).get("default", "")
    keys = sorted(k for k, e in get_catalog("pose").items() if e.get("group") == g)
    if default in keys:
        keys.remove(default)
        keys.insert(0, default)
    return keys


def pose_places(pose_key: str) -> int:
    """Marker slots the pose consumes: 1 for a solo pose, else its ``places``."""
    entry = get_catalog("pose").get((pose_key or "").strip().lower()) or {}
    return 1 if entry.get("solo", True) else int(entry.get("places") or 2)


def pose_yaw_offset(pose_key: str) -> float:
    """Degrees the pair clip's frame turns against the marker facing (0 solo)."""
    entry = get_catalog("pose").get((pose_key or "").strip().lower()) or {}
    return 0.0 if entry.get("solo", True) else float(entry.get("yaw_offset") or 0.0)


def validate_catalog(axis: str) -> List[str]:
    """Returns human-readable problems; empty list = catalog is sound."""
    problems: List[str] = []
    catalog = get_catalog(axis)
    if not catalog:
        problems.append(f"{axis}: catalog is empty or unreadable")
        return problems
    seen: Dict[str, str] = {}
    defaults = 0
    pairs: set = set()
    if axis == "pose":
        try:
            from app.core.animation_clips import pair_kinds
            pairs = set(pair_kinds())
        except Exception:
            pairs = set()
    for key, entry in catalog.items():
        if not entry["prompt"]:
            problems.append(f"{axis}/{key}: empty prompt")
        if axis == "pose" and not entry["animation"]:
            problems.append(f"{axis}/{key}: missing animation kind")
        if axis == "pose" and entry["animation"] in pairs and entry["solo"]:
            # A pair clip has no solo half — the pose needs a partner.
            problems.append(f"{axis}/{key}: '{entry['animation']}' is a pair "
                            f"animation, the pose must not be solo")
        if entry["_default"]:
            defaults += 1
        for alias in [key] + entry["synonyms"]:
            if alias in seen and seen[alias] != key:
                problems.append(f"{axis}: alias '{alias}' claimed by both '{seen[alias]}' and '{key}'")
            seen[alias] = key
    if defaults != 1:
        problems.append(f"{axis}: expected exactly 1 _default entry, found {defaults}")
    if axis == "pose":
        groups = get_groups()
        for g, spec in groups.items():
            d = spec["default"]
            # A place type only just added has no poses yet — and a pose can
            # only name a type that already EXISTS, so the empty default of a
            # poseless group is legal; without that the block could never grow.
            # A default is demanded as soon as the group has its first pose.
            if not d and not any(e.get("group") == g for e in catalog.values()):
                continue
            if d not in catalog or catalog[d].get("group") != g:
                problems.append(f"pose group '{g}': default '{d}' is not a pose of this group")
        for key, entry in catalog.items():
            if entry.get("group", "") not in groups:
                problems.append(f"{axis}/{key}: unknown place type '{entry.get('group', '')}'")
            if entry.get("_stray_pair_fields"):
                problems.append(f"{axis}/{key}: places/yaw_offset only make sense on a pair pose")
    return problems


# ── Resolution: free text → catalog key ──────────────────────────────────
# Matching threshold: cosine similarity below which a free text is treated as
# "not in the catalog" and logged as a candidate. 0.60, because catalog entries
# are short verb phrases: cross-phrasing similarity is lower than
# same-pose-different-words similarity.
# Constant, not a world setting: the world knob pose.catalog_match_threshold
# never had a UI (rule "feature = backend + UI"), so it froze at this default
# anyway — removed with the pose-variant teardown (Aug 2026).
CATALOG_THRESHOLD = 0.60


# Cosine similarity lives with the vectors it compares (app/core/embedding.py)
# — the situational memory block is a second consumer since Aug 2026.
from app.core.embedding import cosine_similarity  # noqa: E402


def _alias_index(axis: str) -> Dict[str, str]:
    """alias (key or synonym, lowercased) -> entry key."""
    index: Dict[str, str] = {}
    for key, entry in get_catalog(axis).items():
        for alias in [key] + entry["synonyms"]:
            index.setdefault(alias, key)
    return index


_embed_cache: Dict[str, Dict[str, list]] = {}   # axis -> {alias: vector}


def _alias_embeddings(axis: str, embed_fn) -> Dict[str, list]:
    # Resolve the aliases BEFORE taking _lock: _alias_index() -> get_catalog()
    # takes the same (non-reentrant) lock and would deadlock on itself.
    aliases = _alias_index(axis)
    with _lock:
        cached = _embed_cache.get(axis)
    if cached is not None:
        return cached
    # The warm-up runs OUTSIDE the lock: with an external embedding backend it
    # is one HTTP call per alias, and _lock is the same lock every catalog
    # reader takes. Two threads racing here just embed twice — harmless.
    vecs = {}
    for alias in aliases:
        v = embed_fn(alias)
        if v:
            vecs[alias] = v
    with _lock:
        return _embed_cache.setdefault(axis, vecs)


def resolve_to_catalog(text: str, axis: str, _embed=None) -> Tuple[str, str]:
    """Maps free text onto a catalog key. Never raises, never returns an
    unknown key. `_embed` overrides the embedding function (tests)."""
    cleaned = (text or "").strip().lower()
    if not cleaned:
        return get_default_key(axis), "empty"
    index = _alias_index(axis)
    if cleaned in index:
        return index[cleaned], "exact"
    if _embed is None:
        from app.core.embedding import embed as _embed
    query = _embed(cleaned)
    if query:
        best_alias, best_score = "", 0.0
        for alias, vec in _alias_embeddings(axis, _embed).items():
            score = cosine_similarity(query, vec)
            if score > best_score:
                best_alias, best_score = alias, score
        if best_alias and best_score >= CATALOG_THRESHOLD:
            # A catalog edit racing the embedding warm-up can leave the alias
            # embeddings holding aliases this fresh index no longer knows —
            # fall through to the fallback rather than break "never raises".
            hit = index.get(best_alias)
            if hit:
                return hit, "embedding"
        record_candidate(axis, cleaned, index.get(best_alias, ""), 1.0 - best_score)
        return get_default_key(axis), "fallback"
    # no embedding available at all: fall back, still record the miss
    record_candidate(axis, cleaned, "", None)
    return get_default_key(axis), "fallback"


# ── Candidates: free text the catalog could not absorb ───────────────────
def record_candidate(axis: str, raw_text: str, nearest_key: str,
                     distance: Optional[float]) -> None:
    from app.core.db import transaction
    from app.core.timeutils import utc_now_iso
    now = utc_now_iso()
    try:
        with transaction() as conn:
            conn.execute(
                "INSERT INTO pose_candidates (axis, raw_text, nearest_key, distance, "
                " count, status, first_seen, last_seen) "
                "VALUES (?, ?, ?, ?, 1, 'open', ?, ?) "
                "ON CONFLICT(axis, raw_text) DO UPDATE SET "
                " count = count + 1, last_seen = excluded.last_seen",
                (axis, raw_text[:200], nearest_key or "", distance, now, now),
            )
    except Exception as e:
        logger.debug("record_candidate failed: %s", e)


def list_candidates(axis: str, status: str = "open") -> List[dict]:
    from app.core.db import get_connection
    try:
        rows = get_connection().execute(
            "SELECT raw_text, nearest_key, distance, count, first_seen, last_seen "
            "FROM pose_candidates WHERE axis=? AND status=? "
            "ORDER BY count DESC, last_seen DESC", (axis, status)).fetchall()
        return [{"raw_text": r[0], "nearest_key": r[1], "distance": r[2],
                 "count": r[3], "first_seen": r[4], "last_seen": r[5]} for r in rows]
    except Exception as e:
        logger.debug("list_candidates failed: %s", e)
        return []


def delete_candidate(axis: str, raw_text: str) -> bool:
    """Removes a candidate row for good.

    Used when a candidate was APPROVED into the catalog: the text now resolves
    exactly, so it will not come back — and if the approval was imperfect (a
    synonym that still misses), the miss has to surface as a fresh candidate
    instead of hiding behind a terminal status.
    """
    from app.core.db import transaction
    try:
        with transaction() as conn:
            cur = conn.execute(
                "DELETE FROM pose_candidates WHERE axis=? AND raw_text=?",
                (axis, raw_text))
            return cur.rowcount > 0
    except Exception as e:
        logger.warning("delete_candidate failed: %s", e)
        return False


def set_candidate_status(axis: str, raw_text: str, status: str) -> bool:
    from app.core.db import transaction
    try:
        with transaction() as conn:
            cur = conn.execute(
                "UPDATE pose_candidates SET status=? WHERE axis=? AND raw_text=?",
                (status, axis, raw_text))
            return cur.rowcount > 0
    except Exception as e:
        logger.warning("set_candidate_status failed: %s", e)
        return False


# ── Flavor: what survives of the free text next to the catalog key ───────
_FLAVOR_MAX_CHARS = 120


def sanitize_flavor(text: str) -> str:
    """Sanitized 'flavor' prompt text: quoted speech removed, character names
    removed (exact stored names only - NO first/last-name resolution, standing
    directive), first sentence, hard cap 120 chars."""
    raw = (text or "").strip()
    if not raw:
        return ""
    # German pairs are „…“ — the closing class must contain “ as well.
    raw = re.sub(r'["“„][^"“”„]*["”“]', "", raw)
    try:
        from app.models.character import list_available_characters
        names = list_available_characters()
    except Exception:
        names = []
    for name in sorted(names, key=len, reverse=True):
        if name:
            raw = re.sub(rf"\b{re.escape(name)}\b", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s{2,}", " ", raw).strip(" ,;:-")
    first = re.split(r"(?<=[.!?])\s", raw, maxsplit=1)[0].strip()
    return first[:_FLAVOR_MAX_CHARS].strip()
