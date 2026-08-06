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


def _catalog_path(axis: str) -> Path:
    from app.core.paths import get_shared_dir
    sub, name = _FILES[axis]
    return get_shared_dir() / "templates" / sub / name


def _load(axis: str) -> Dict[str, dict]:
    try:
        data = json.loads(_catalog_path(axis).read_text(encoding="utf-8"))
        entries = data.get("entries") or {}
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.warning("catalog %s unreadable: %s", axis, e)
        entries = {}
    out: Dict[str, dict] = {}
    for key, entry in entries.items():
        out[str(key).strip().lower()] = {
            "prompt": str(entry.get("prompt") or ""),
            "synonyms": [str(s).strip().lower() for s in (entry.get("synonyms") or []) if str(s).strip()],
            "animation": str(entry.get("animation") or ""),
            "solo": bool(entry.get("solo", True)),
            "_default": bool(entry.get("_default", False)),
        }
    return out


def get_catalog(axis: str) -> Dict[str, dict]:
    with _lock:
        if axis not in _cache:
            _cache[axis] = _load(axis)
        return _cache[axis]


def reload_catalogs() -> None:
    with _lock:
        _cache.clear()
        _embed_cache.clear()


def get_default_key(axis: str) -> str:
    for key, entry in get_catalog(axis).items():
        if entry["_default"]:
            return key
    return _FALLBACK_DEFAULT[axis]


def validate_catalog(axis: str) -> List[str]:
    """Returns human-readable problems; empty list = catalog is sound."""
    problems: List[str] = []
    catalog = get_catalog(axis)
    if not catalog:
        problems.append(f"{axis}: catalog is empty or unreadable")
        return problems
    seen: Dict[str, str] = {}
    defaults = 0
    for key, entry in catalog.items():
        if not entry["prompt"]:
            problems.append(f"{axis}/{key}: empty prompt")
        if axis == "pose" and not entry["animation"]:
            problems.append(f"{axis}/{key}: missing animation kind")
        if entry["_default"]:
            defaults += 1
        for alias in [key] + entry["synonyms"]:
            if alias in seen and seen[alias] != key:
                problems.append(f"{axis}: alias '{alias}' claimed by both '{seen[alias]}' and '{key}'")
            seen[alias] = key
    if defaults != 1:
        problems.append(f"{axis}: expected exactly 1 _default entry, found {defaults}")
    return problems


# ── Resolution: free text → catalog key ──────────────────────────────────
# Matching threshold: cosine similarity below which a free text is treated as
# "not in the catalog" and logged as a candidate. World-overridable like
# pose.variant_match_threshold. 0.60 (not 0.75 as the variant matcher used):
# catalog entries are short verb phrases, cross-phrasing similarity is lower
# than same-pose-different-words similarity.
DEFAULT_CATALOG_THRESHOLD = 0.60


def get_catalog_threshold() -> float:
    from app.models.world import get_world_setting
    try:
        raw = get_world_setting("pose.catalog_match_threshold", "")
        if raw:
            return max(0.0, min(1.0, float(raw)))
    except Exception:
        pass
    return DEFAULT_CATALOG_THRESHOLD


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
        if axis not in _embed_cache:
            vecs = {}
            for alias in aliases:
                v = embed_fn(alias)
                if v:
                    vecs[alias] = v
            _embed_cache[axis] = vecs
        return _embed_cache[axis]


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
        from app.core.pose_variants import cosine_similarity
        best_alias, best_score = "", 0.0
        for alias, vec in _alias_embeddings(axis, _embed).items():
            score = cosine_similarity(query, vec)
            if score > best_score:
                best_alias, best_score = alias, score
        if best_alias and best_score >= get_catalog_threshold():
            return index[best_alias], "embedding"
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
    raw = re.sub(r'["“„][^"“”„]*["”]', "", raw)
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
