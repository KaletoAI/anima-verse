"""Expression Regeneration — generates outfit images with expression/pose variants.

Lazy on-demand: the frontend requests an expression image via the endpoint,
and this module generates it if not cached. Results live in the character's
outfits/ directory, keyed by CATALOG KEYS: the cache-key space is
|pose catalog| x |expression catalog| x outfit x state fingerprint — finite
and lazily filled. Free text never reaches this module: callers pass the pose
catalog key (``get_effective_pose_key``), the mood is mapped onto its
expression key here (``resolve_expression_key``).
"""

import hashlib
import json
import os
import re
import shutil
import threading
from pathlib import Path
from typing import Any, Dict, Optional, Set

from app.core.log import get_logger
from app.core.expression_pose_maps import (
    get_expression_prompt,
    get_pose_prompt,
    is_partner_activity,
    resolve_expression_key)

logger = get_logger(__name__)

# The use cases of the reference renders that feed the image->3D chain: front
# T-pose (humanoid / animal) plus the extra back and profile views. They are
# the ones a per-character T-pose backend match applies to; every other use
# case keeps the normal render match. Set in ``app/core/model_refs.py``.
TPOSE_USE_CASES = ("tpose", "tpose_animal", "tpose_back", "tpose_side")

# In-flight generation tracking (character:cache_key)
_generating: Set[str] = set()
_failed: Set[str] = set()  # tracks recently failed generations to avoid retry loops
_generating_lock = threading.Lock()
# Per-character mutex. The same character is serialized (file collision in
# the sidecar write and ref-image sharing); different characters run in
# parallel so multiple backends can generate at the same time. Backend
# selection round-robins over equal-cost backends to spread the load.
_char_generation_mutexes: Dict[str, threading.Lock] = {}
_char_mutexes_create_lock = threading.Lock()


def _get_char_mutex(character_name: str) -> threading.Lock:
    with _char_mutexes_create_lock:
        mx = _char_generation_mutexes.get(character_name)
        if mx is None:
            mx = threading.Lock()
            _char_generation_mutexes[character_name] = mx
        return mx

# Env config — render-target spec format: "backend:<glob>"


def _cleanup_stale_temps(expr_dir: Path) -> None:
    """Removes leftover .tmp_ / _temp_ files from the expressions directory."""
    count = 0
    for f in expr_dir.iterdir():
        if not f.is_file():
            continue
        if f.name.startswith(".tmp_") or f.name.startswith("_temp_"):
            try:
                f.unlink()
                count += 1
            except OSError:
                pass
    if count:
        logger.info("Cleanup: %d stale temp files removed", count)


def _get_expressions_dir(character_name: str) -> Path:
    """Returns the expressions cache directory for a character.

    The variant images live directly in the outfits/ folder (there are no
    outfit images any more); variants partition themselves via the cache key
    of character + equipped + pose key + expression key + state.
    """
    from app.models.character import get_character_outfits_dir
    expr_dir = get_character_outfits_dir(character_name)
    expr_dir.mkdir(parents=True, exist_ok=True)
    return expr_dir


def _safe_name(name: str) -> str:
    """Replace spaces with underscores for safe filenames."""
    return name.replace(" ", "_")


def _equipped_signature(equipped_pieces: Optional[Dict[str, str]] = None,
                        equipped_items: Optional[list] = None,
                        equipped_pieces_meta: Optional[Dict[str, Dict[str, Any]]] = None) -> str:
    """Stable signature of the worn items (pieces + other equipment).

    Slot order is sorted so the same equip set always produces the same hash;
    items alphabetically.

    The equipped_pieces_meta parameter stays in the signature for existing
    callers but is ignored — colour overrides were dropped in step 3
    (May 2026, plan §5).
    """
    parts = []
    if equipped_pieces:
        # Normalise to the VISIBLE subset (user finding 2026-07-27): a slot
        # fully hidden via `covers` does not change the image, so covered
        # variants collapse onto one signature — one render, one cache entry,
        # for the batch and the live outfit-change trigger alike. Sets
        # without covered pieces hash exactly as before, existing cache
        # entries stay valid.
        try:
            from app.core.outfit_renderer import visible_equipped_pieces
            equipped_pieces = visible_equipped_pieces(equipped_pieces)
        except Exception:
            pass  # unreadable items must not break signing — hash raw then
        for slot in sorted(equipped_pieces.keys()):
            iid = (equipped_pieces[slot] or "").strip()
            if iid:
                parts.append(f"{slot}={iid}")
    if equipped_items:
        cleaned = sorted({(i or "").strip() for i in equipped_items if i})
        if cleaned:
            parts.append("items:" + ",".join(cleaned))
    return "|".join(parts)


def _canonical_pose_key(pose_key: str) -> str:
    """The pose axis of the cache key: an EXACT catalog key.

    Unknown or empty input collapses onto the catalog's default key — the
    same entry ``get_pose_prompt`` renders for it, so key and image agree.
    """
    from app.core.pose_catalog import get_catalog, get_default_key
    key = (pose_key or "").strip().lower()
    if key and key in get_catalog("pose"):
        return key
    if key:
        logger.debug("cache key: pose '%s' is not a catalog key → default", key)
    return get_default_key("pose")


def _cache_key(mood: str, pose_key: str,
               character_name: str = "",
               equipped_pieces: Optional[Dict[str, str]] = None,
               equipped_items: Optional[list] = None,
               equipped_pieces_meta: Optional[Dict[str, Dict[str, Any]]] = None,
               state_fp: Optional[str] = None) -> str:
    """Build a deterministic cache key.

    Two catalog axes and nothing else: ``resolve_expression_key(mood)`` and
    the exact pose catalog key the caller passed
    (``character.get_effective_pose_key``). Together with the outfit
    signature and the state fingerprint that makes the key space finite —
    |pose catalog| x |expression catalog| x outfit x state — instead of
    growing with every phrasing an LLM invents.

    The outfit axis is ``model_refs.outfit_signature_raw`` — the SAME rule
    the per-outfit render caches use, and the raw string rather than its
    hash, because this key hashes it together with the two catalog axes (ONE
    signature rule, never a second hash). For a character with a structured
    outfit that string IS ``_equipped_signature(...)``, so no existing
    variant moves; for one whose template has no outfit system (a temporary
    NPC) it is the free-text ``outfit_description`` the image is actually
    rendered from. Without it every such character in the world shared one
    key and editing the outfit text invalidated nothing.
    ``equipped_pieces_meta`` is still accepted for existing callers and still
    ignored (colour overrides were dropped in step 3, May 2026).

    ``state_fp``: fingerprint of the triggered image-modifier state
    (model_refs.state_fingerprint). ``None`` = look it up live for
    ``character_name`` — every caller passes the character's CURRENT
    mood/outfit anyway, the state belongs to that same snapshot. Pass ""
    explicitly for a deliberately neutral render.
    """
    from app.core.model_refs import outfit_signature_raw
    expression_key = resolve_expression_key(mood)
    pose = _canonical_pose_key(pose_key)
    eq = outfit_signature_raw(equipped_pieces, equipped_items, character_name)
    if state_fp is None and character_name:
        from app.core.model_refs import state_fingerprint
        state_fp = state_fingerprint(character_name)
    raw = f"{expression_key}:{pose}:{eq}"
    if state_fp:
        raw += f":state={state_fp}"
    h = hashlib.md5(raw.encode()).hexdigest()[:12]
    if character_name:
        return f"{_safe_name(character_name)}_{h}"
    return h


def get_cached_expression(character_name: str,
                          mood: str, pose_key: str,
                          equipped_pieces: Optional[Dict[str, str]] = None,
                          equipped_items: Optional[list] = None,
                          equipped_pieces_meta: Optional[Dict[str, Dict[str, Any]]] = None) -> Optional[Path]:
    """Check if a cached expression image exists. Returns path or None.

    On a hit, updates the sidecar JSON with ``last_used_at`` (unix ts) and
    increments ``use_count``. The LRU-Pruner uses these to decide which
    variants to evict when a character exceeds its cap.
    """
    expr_dir = _get_expressions_dir(character_name)
    key = _cache_key(mood, pose_key, character_name, equipped_pieces, equipped_items, equipped_pieces_meta)
    for ext in (".png", ".jpg", ".webp"):
        path = expr_dir / f"{key}{ext}"
        if path.exists():
            _touch_sidecar(path.with_suffix(".json"))
            return path
    return None


def peek_cached_expression(character_name: str, mood: str, pose_key: str,
                           equipped_pieces: Optional[Dict[str, str]] = None,
                           equipped_items: Optional[list] = None,
                           equipped_pieces_meta: Optional[Dict[str, Dict[str, Any]]] = None) -> Optional[Path]:
    """Like get_cached_expression but WITHOUT the side effect (no sidecar
    touch) — for version/existence checks on every poll, so use_count/LRU
    stay honest."""
    expr_dir = _get_expressions_dir(character_name)
    key = _cache_key(mood, pose_key, character_name, equipped_pieces,
                     equipped_items, equipped_pieces_meta)
    for ext in (".png", ".jpg", ".webp"):
        path = expr_dir / f"{key}{ext}"
        if path.exists():
            return path
    return None


def find_nearest_expression(character_name: str, mood: str,
                            equipped_pieces: Optional[Dict[str, str]] = None,
                            equipped_items: Optional[list] = None) -> Optional[Path]:
    """Serving fallback: the cached variant whose recorded outfit is CLOSEST
    to the given equipped state (app/core/outfit_match.py), so a character in
    a never-rendered combination shows a near-matching image instead of an
    arbitrary one. Outfit similarity dominates; an EQUAL expression key breaks
    ties, then recency. Read-only — no sidecar touch, no generation trigger.
    None when no variant records an outfit (sidecars without the fields)."""
    from app.core.outfit_match import outfit_similarity
    expr_dir = _get_expressions_dir(character_name)
    if not expr_dir.is_dir():
        return None
    want_key = resolve_expression_key(mood)
    best = None
    for sidecar in expr_dir.glob(f"{_safe_name(character_name)}_*.json"):
        img = next((sidecar.with_suffix(ext)
                    for ext in (".png", ".jpg", ".webp")
                    if sidecar.with_suffix(ext).exists()), None)
        if img is None:
            continue
        try:
            meta = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(meta.get("equipped_pieces"), dict):
            continue  # legacy sidecar — outfit unknown, not comparable
        score = outfit_similarity(equipped_pieces, equipped_items,
                                  meta.get("equipped_pieces"),
                                  meta.get("equipped_items") or [])
        # Exact key equality — the sidecar records the key the image was
        # rendered under, so no free text is re-resolved while serving.
        expression_hit = str(meta.get("expression_key") or "") == want_key
        key = (score, expression_hit, img.stat().st_mtime)
        if best is None or key > best[0]:
            best = (key, img)
    return best[1] if best is not None else None


def _touch_sidecar(sidecar_path: Path) -> None:
    """Best-effort update of last_used_at/use_count in a variant sidecar JSON.

    Failures are logged at debug level only — a missing sidecar or a write
    error must not break image-serving.
    """
    if not sidecar_path.exists():
        return
    import time as _time
    try:
        data = json.loads(sidecar_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return
        data["last_used_at"] = _time.time()
        data["use_count"] = int(data.get("use_count", 0)) + 1
        sidecar_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        logger.debug("touch sidecar %s failed: %s", sidecar_path.name, e)


_VARIANTS_MAX_PER_CHAR_DEFAULT = 30


def _get_variants_cap() -> int:
    """Read the per-character variants cap from config, with a sensible default."""
    try:
        from app.core import config as _cfg
        val = int(_cfg.get("server.variants_max_per_character")
                  or _VARIANTS_MAX_PER_CHAR_DEFAULT)
        return max(5, min(500, val))
    except Exception:
        return _VARIANTS_MAX_PER_CHAR_DEFAULT


def prune_variants(character_name: str, max_per_char: Optional[int] = None) -> int:
    """LRU-Eviction: keep only the N most-recently-used variants for a character.

    Sort order: variants with ``last_used_at`` win over variants without
    (legacy entries get their file mtime as a tiebreaker). Among those with
    the field, newest wins. Excess sidecars and their PNGs are deleted in
    pairs. Returns the number of variant pairs removed.
    """
    cap = max_per_char if max_per_char is not None else _get_variants_cap()
    expr_dir = _get_expressions_dir(character_name)
    if not expr_dir.exists():
        return 0
    entries = []  # (sort_key, sidecar_path, image_path or None)
    for sidecar in expr_dir.glob("*.json"):
        last_used = 0.0
        try:
            meta = json.loads(sidecar.read_text(encoding="utf-8"))
            if isinstance(meta, dict):
                last_used = float(meta.get("last_used_at") or 0.0)
        except Exception:
            pass
        if last_used <= 0:
            try:
                last_used = sidecar.stat().st_mtime
            except OSError:
                last_used = 0.0
        img = None
        for ext in (".png", ".jpg", ".webp"):
            cand = sidecar.with_suffix(ext)
            if cand.exists():
                img = cand
                break
        entries.append((last_used, sidecar, img))
    if len(entries) <= cap:
        return 0
    entries.sort(key=lambda e: e[0], reverse=True)  # newest first
    removed = 0
    for _ts, sidecar, img in entries[cap:]:
        try:
            if img and img.exists():
                img.unlink()
            sidecar.unlink()
            removed += 1
        except OSError as e:
            logger.debug("prune %s failed: %s", sidecar.name, e)
    if removed:
        logger.info("Variant pruning %s: %d pairs removed (cap=%d)",
                     character_name, removed, cap)
    return removed


def prune_variants_all(max_per_char: Optional[int] = None) -> int:
    """Run prune_variants for every character. Returns total pairs removed."""
    try:
        from app.models.character import list_available_characters
    except Exception:
        return 0
    total = 0
    for char_name in list_available_characters():
        try:
            total += prune_variants(char_name, max_per_char=max_per_char)
        except Exception as e:
            logger.debug("prune_variants_all %s: %s", char_name, e)
    return total


def is_generating(character_name: str, mood: str, pose_key: str,
                  equipped_pieces: Optional[Dict[str, str]] = None,
                  equipped_items: Optional[list] = None,
                  equipped_pieces_meta: Optional[Dict[str, Dict[str, Any]]] = None) -> bool:
    """True while a generation runs OR waits inside the coalesce window.

    A pending coalesce counts as generating so the frontend polling does not
    fire a new trigger per poll (which would reset the debounce timer) and
    gets a 202 until the image is actually there.
    """
    key = f"{character_name}:{_cache_key(mood, pose_key, character_name, equipped_pieces, equipped_items, equipped_pieces_meta)}"
    with _generating_lock:
        if key in _generating:
            return True
        pending = _pending_triggers.get(character_name)
        if pending:
            pending_key = f"{character_name}:{_cache_key(pending.get('mood', ''), pending.get('pose_key', ''), character_name, pending.get('equipped_pieces'), pending.get('equipped_items'), pending.get('equipped_pieces_meta'))}"
            if pending_key == key:
                return True
    return False


def has_failed(character_name: str, mood: str, pose_key: str,
               equipped_pieces: Optional[Dict[str, str]] = None,
               equipped_items: Optional[list] = None,
               equipped_pieces_meta: Optional[Dict[str, Dict[str, Any]]] = None) -> bool:
    """Check if generation recently failed for this combo (avoids retry loops)."""
    key = f"{character_name}:{_cache_key(mood, pose_key, character_name, equipped_pieces, equipped_items, equipped_pieces_meta)}"
    with _generating_lock:
        return key in _failed


def invalidate_variants_for_item(item_id: str) -> int:
    """Deletes exactly those variant files whose equipped_pieces/items
    contained the changed item — read from the .json sidecar next to the PNG.

    Variants without a sidecar are skipped, not deleted wholesale.
    """
    if not item_id:
        return 0
    try:
        from app.models.character import list_available_characters
    except Exception:
        return 0
    total = 0
    for char_name in list_available_characters():
        try:
            expr_dir = _get_expressions_dir(char_name)
            if not expr_dir.exists():
                continue
            for sidecar in expr_dir.glob("*.json"):
                try:
                    meta = json.loads(sidecar.read_text(encoding="utf-8"))
                except Exception:
                    continue
                eq_pieces = meta.get("equipped_pieces") or {}
                eq_items = meta.get("equipped_items") or []
                in_pieces = item_id in (eq_pieces.values() if isinstance(eq_pieces, dict) else [])
                in_items = item_id in eq_items
                if not (in_pieces or in_items):
                    continue
                # Delete the image and its sidecar together
                for ext in (".png", ".jpg", ".webp"):
                    img = sidecar.with_suffix(ext)
                    if img.exists():
                        try:
                            img.unlink()
                            total += 1
                        except OSError:
                            pass
                try:
                    sidecar.unlink()
                except OSError:
                    pass
        except Exception as e:
            logger.debug("invalidate_variants_for_item %s/%s: %s", char_name, e)
    if total:
        logger.info("Variant invalidation for item %s: %d files deleted", item_id, total)
    return total


def clear_failed_marker(character_name: str, mood: str, pose_key: str,
                         equipped_pieces: Optional[Dict[str, str]] = None,
                         equipped_items: Optional[list] = None,
                         equipped_pieces_meta: Optional[Dict[str, Dict[str, Any]]] = None) -> None:
    """Removes the failed marker for one combination so the generation can be
    attempted again."""
    key = f"{character_name}:{_cache_key(mood, pose_key, character_name, equipped_pieces, equipped_items, equipped_pieces_meta)}"
    with _generating_lock:
        _failed.discard(key)


def clear_expression_cache(character_name: str) -> int:
    """Clear all cached expression images for a character."""
    expr_dir = _get_expressions_dir(character_name)
    count = 0
    for f in expr_dir.iterdir():
        if not f.is_file():
            continue
        f.unlink()
        count += 1
    # Also clear failed-generation markers so variants are retried
    with _generating_lock:
        prefix = f"{character_name}:"
        stale = {k for k in _failed if k.startswith(prefix)}
        _failed.difference_update(stale)
    if count or stale:
        logger.info("Expression cache cleared: %d files, %d failed markers (%s)",
                     count, len(stale), character_name)
    return count


# Image extensions a variant image can carry next to its .json sidecar.
_VARIANT_IMG_EXTS = (".png", ".jpg", ".jpeg", ".webp")


def list_expressions(character_name: str) -> list:
    """Lists all cached expression variants of a character with their
    parameters (from the .json sidecar). Newest first.

    Each entry: ``{file, mood, activity, equipped_pieces, equipped_items,
    model, seed, provider, service, workflow, prompt, created_at, use_count,
    last_used_at}`` — ``activity`` carries the pose catalog key. Images
    without a sidecar (or sidecars without an image) are skipped; only
    complete pairs are displayable.
    """
    expr_dir = _get_expressions_dir(character_name)
    if not expr_dir.exists():
        return []
    # Resolve item ids to readable names (the sidecar only stores ids like
    # "item_936518eb"). Cached per call so not every image pulls the same id
    # from the DB again. Unknown ids fall back to the id.
    from app.models.inventory import get_item
    _name_cache: Dict[str, str] = {}

    def _item_name(item_id: str) -> str:
        iid = (item_id or "").strip()
        if not iid:
            return ""
        if iid not in _name_cache:
            try:
                it = get_item(iid)
            except Exception:
                it = None
            _name_cache[iid] = (it or {}).get("name", "") or iid
        return _name_cache[iid]

    out = []
    for sidecar in expr_dir.glob("*.json"):
        img = next((sidecar.with_suffix(ext) for ext in _VARIANT_IMG_EXTS
                    if sidecar.with_suffix(ext).exists()), None)
        if not img:
            continue
        try:
            meta = json.loads(sidecar.read_text(encoding="utf-8"))
            if not isinstance(meta, dict):
                meta = {}
        except Exception:
            meta = {}
        try:
            mtime = sidecar.stat().st_mtime
        except OSError:
            mtime = 0.0
        _pieces = meta.get("equipped_pieces", {}) or {}
        _items = meta.get("equipped_items", []) or []
        out.append({
            "file": img.name,
            "mood": meta.get("mood", "") or "",
            "activity": meta.get("activity", "") or "",
            # slot -> item NAME (instead of the raw id); list of item names.
            "equipped_pieces": {slot: _item_name(iid)
                                for slot, iid in _pieces.items()} if isinstance(_pieces, dict) else {},
            "equipped_items": [_item_name(i) for i in _items] if isinstance(_items, list) else [],
            "model": meta.get("model", "") or "",
            "seed": meta.get("seed"),
            "provider": meta.get("provider", "") or "",
            "service": meta.get("service", "") or "",
            "workflow": meta.get("workflow", "") or "",
            "prompt": meta.get("prompt", "") or "",
            "created_at": meta.get("created_at", "") or "",
            "use_count": meta.get("use_count", 0) or 0,
            "last_used_at": meta.get("last_used_at") or 0.0,
            "_sort": meta.get("created_at", "") or mtime,
        })
    # Newest first: created_at (an ISO string sorts lexicographically) with
    # mtime as the fallback. Mixed types -> normalize to string.
    out.sort(key=lambda e: str(e.pop("_sort")), reverse=True)
    return out


def delete_expression(character_name: str, filename: str) -> bool:
    """Deletes a single variant image + its .json sidecar.

    Path-traversal safe: ``filename`` must be a plain file name inside the
    expressions directory. Returns True if at least one file was removed.
    """
    expr_dir = _get_expressions_dir(character_name)
    # Only the base name is allowed — no path components.
    if not filename or filename != Path(filename).name:
        return False
    img = expr_dir / filename
    try:
        # The resolved path MUST stay inside the expressions dir (symlink/.. guard).
        if img.resolve().parent != expr_dir.resolve():
            return False
    except OSError:
        return False
    removed = False
    for p in (img, img.with_suffix(".json")):
        try:
            if p.exists():
                p.unlink()
                removed = True
        except OSError as e:
            logger.debug("delete_expression %s failed: %s", p.name, e)
    if removed:
        logger.info("Expression deleted: %s (%s)", filename, character_name)
    return removed


_EXPRESSION_COOLDOWN = 300  # seconds between expression generations per character
_last_expression_time: Dict[str, float] = {}  # character_name -> timestamp

# Coalesce window: triggers arriving for the same character inside it are
# bundled (latest state wins). Keeps a single chat turn from producing several
# variants (mood change → outfit unequip → pose extraction).
#
# Size: the extraction LLM (2 hops, intent + extraction) needs 6-12s in
# practice to deliver the pose. With a window < 12s the mood-triggered variant
# still fires with the old/unclassified pose before the extraction trigger can
# take over. It is the compromise between "chat end until variant visible" and
# "all triggers bundled".
_COALESCE_WINDOW = 10.0
_pending_triggers: Dict[str, Dict[str, Any]] = {}   # character → request dict
_pending_timers: Dict[str, threading.Timer] = {}    # character → scheduled Timer


def trigger_expression_generation(character_name: str,
                                  mood: str, pose_key: str,
                                  equipped_pieces: Optional[Dict[str, str]] = None,
                                  equipped_items: Optional[list] = None,
                                  equipped_pieces_meta: Optional[Dict[str, Dict[str, Any]]] = None,
                                  ignore_cooldown: bool = False,
                                  ignore_feature_gate: bool = False,
                                  prompt_prefix: Optional[str] = None,
                                  coalesce: bool = True) -> bool:
    """Queue or start an expression generation.

    ``pose_key`` is a pose CATALOG key (``character.get_effective_pose_key``),
    never free text — the garbage/mood-leakage filter this function used to
    run is obsolete: text that means nothing never becomes a key here, it is
    absorbed by the catalog resolution at the write path.

    By default triggers are bundled inside a short window
    (_COALESCE_WINDOW): a chat turn typically fires three triggers in a row
    (mood, outfit unequip, pose extraction), of which only the last carries
    the final state. Instead of generating three images the trigger waits for
    the end of the burst and then fires once with the newest state.

    coalesce=False bypasses the debounce — for callers that want exactly one
    immediate image (test helpers). Production paths (auto regen, chat
    extraction, wardrobe preview, skills) leave coalesce at True.

    Returns True if a trigger (or a pending trigger) was registered.
    """
    # Style/framing come from the "expression" use case (no env prefix).
    if prompt_prefix is None:
        prompt_prefix = ""

    if not ignore_feature_gate:
        try:
            from app.models.character_template import is_feature_enabled
            if not is_feature_enabled(character_name, "expression_variants_enabled"):
                return False
        except Exception:
            pass

    # Partner poses (kissing, embracing, ...) are skipped entirely. The
    # pipeline injects only ONE character, so the image model duplicates the
    # subject to satisfy the "two people" implication of the pose prompt.
    # Instead of generating a broken variant the avatar keeps its last good
    # frame. Tagged via ``"solo": false`` in the pose catalog — no heuristic.
    if is_partner_activity(pose_key):
        logger.info(
            "Expression trigger [%s]: pose '%s' is a partner pose (solo:false) → skip",
            character_name, pose_key)
        return False

    if not coalesce:
        return _do_trigger_expression_generation(
            character_name, mood, pose_key,
            equipped_pieces=equipped_pieces,
            equipped_items=equipped_items,
            equipped_pieces_meta=equipped_pieces_meta,
            ignore_cooldown=ignore_cooldown,
            prompt_prefix=prompt_prefix)

    new_key = _cache_key(mood, pose_key, character_name,
                         equipped_pieces, equipped_items, equipped_pieces_meta)
    request = {
        "mood": mood,
        "pose_key": pose_key,
        "equipped_pieces": equipped_pieces,
        "equipped_items": equipped_items,
        "equipped_pieces_meta": equipped_pieces_meta,
        "ignore_cooldown": ignore_cooldown,
        "prompt_prefix": prompt_prefix,
    }

    with _generating_lock:
        existing = _pending_triggers.get(character_name)
        if existing:
            existing_key = _cache_key(existing.get("mood", ""),
                                       existing.get("pose_key", ""),
                                       character_name,
                                       existing.get("equipped_pieces"),
                                       existing.get("equipped_items"),
                                       existing.get("equipped_pieces_meta"))
            if existing_key == new_key:
                # Identical request — do NOT reset the timer (frontend-polling
                # protection), but raise ignore_cooldown if the new caller set it
                if ignore_cooldown and not existing.get("ignore_cooldown"):
                    existing["ignore_cooldown"] = True
                return True
            # State changed → cancel the old timer, set a new one
            old_timer = _pending_timers.pop(character_name, None)
            if old_timer:
                try:
                    old_timer.cancel()
                except Exception:
                    pass

        _pending_triggers[character_name] = request
        timer = threading.Timer(_COALESCE_WINDOW,
                                _fire_coalesced_trigger,
                                args=[character_name])
        timer.daemon = True
        _pending_timers[character_name] = timer
        timer.start()
    return True


def _fire_coalesced_trigger(character_name: str) -> None:
    """Fires the pending trigger of a character at the end of the coalesce window."""
    with _generating_lock:
        request = _pending_triggers.pop(character_name, None)
        _pending_timers.pop(character_name, None)
    if not request:
        return
    try:
        _do_trigger_expression_generation(character_name, **request)
    except Exception as e:
        logger.error("Coalesced expression trigger for %s failed: %s",
                      character_name, e)


def _do_trigger_expression_generation(character_name: str,
                                       mood: str, pose_key: str,
                                       equipped_pieces: Optional[Dict[str, str]] = None,
                                       equipped_items: Optional[list] = None,
                                       equipped_pieces_meta: Optional[Dict[str, Dict[str, Any]]] = None,
                                       ignore_cooldown: bool = False,
                                       prompt_prefix: str = "") -> bool:
    """The actual trigger logic: cooldown check, dedup, thread spawn.

    Called either directly (coalesce=False) or by the timer at the end of the
    coalesce window. The feature gate was already checked in the wrapper.
    """
    import time as _time

    if not ignore_cooldown:
        now = _time.monotonic()
        last = _last_expression_time.get(character_name, 0)
        if now - last < _EXPRESSION_COOLDOWN:
            logger.debug("Expression cooldown active for %s (%ds left)",
                         character_name, int(_EXPRESSION_COOLDOWN - (now - last)))
            return False
    else:
        now = _time.monotonic()
    _last_expression_time[character_name] = now

    key = f"{character_name}:{_cache_key(mood, pose_key, character_name, equipped_pieces, equipped_items, equipped_pieces_meta)}"
    with _generating_lock:
        if key in _generating:
            return False
        _generating.add(key)

    def _run():
        # Pending entry in the panel while waiting for the mutex, so stacked
        # expression triggers are visible.
        _pending_track_id = None
        try:
            from app.core.task_queue import get_task_queue
            _pending_track_id = get_task_queue().track_start(
                "expression_regen",
                f"Variant: {character_name} ({pose_key or 'idle'})",
                agent_name=character_name,
                start_running=False)
        except Exception:
            _pending_track_id = None
        try:
            # Per-character mutex: the same character serially, different
            # characters in parallel (they can go to different backends/GPUs).
            with _get_char_mutex(character_name):
                if _pending_track_id:
                    # Discard the placeholder instead of cancelling it —
                    # otherwise every expression trigger shows up as
                    # "cancelled manually" in Recently.
                    try:
                        get_task_queue().track_discard(_pending_track_id)
                    except Exception:
                        pass
                    _pending_track_id = None
                result = generate_expression_image(character_name, mood, pose_key,
                                                    equipped_pieces, equipped_items,
                                                    prompt_prefix=prompt_prefix)
            if result is None:
                with _generating_lock:
                    _failed.add(key)
        finally:
            if _pending_track_id:
                try:
                    get_task_queue().track_discard(_pending_track_id)
                except Exception:
                    pass
            with _generating_lock:
                _generating.discard(key)

    t = threading.Thread(target=_run, daemon=True,
                         name=f"expr-regen-{character_name}")
    t.start()
    return True


def generate_expression_image(character_name: str,
                              mood: str, pose_key: str,
                              equipped_pieces: Optional[Dict[str, str]] = None,
                              equipped_items: Optional[list] = None,
                              prompt_prefix: str = "",
                              pose_prompt_override: Optional[str] = None,
                              expression_prompt_override: Optional[str] = None,
                              image_use_case: str = "expression",
                              output_stem: Optional[Path] = None,
                              override_width: Optional[int] = None,
                              override_height: Optional[int] = None,
                              apply_state_modifiers: bool = True,
                              include_exposed: bool = True) -> Optional[Path]:
    """Generate an expression/pose variant.

    Character + equipped items + pose + expression -> text-prompt-based
    image generation. No outfit reference image needed. ``mood`` is free text
    (resolved to its expression catalog key), ``pose_key`` is a pose CATALOG
    key — both prompt and cache key come from the same two keys.

    Prompt layering: the use-case style (camera/framing/lighting/background)
    is prepended by the image service; THIS function composes the content
    layers actor+appearance -> outfit -> pose -> expression. Overrides feed
    a single layer verbatim and must not carry style fragments.

    Reference-render extras (model_refs, AV3D):
    - ``pose_prompt_override`` uses the given pose text verbatim (bypasses
      the catalog lookup and the default pose).
    - ``expression_prompt_override`` uses the given expression text verbatim
      (``""`` omits the expression layer entirely).
    - ``image_use_case`` picks the style use case (default "expression").
    - ``output_stem`` (path without extension) stores the result there
      instead of the expression-image cache — no cache bookkeeping.
    - ``override_width`` / ``override_height`` win over the outfit image
      format (a T-pose needs a wider frame than a portrait).
    - ``apply_state_modifiers=False`` renders the NEUTRAL appearance (no
      triggered image_modifier rewrites) — for cache entries whose key
      deliberately carries no state (outfit-batch pre-warm).
    - ``include_exposed=False`` drops the exposed body-slot fragments AND
      the LoRAs bound to those slots — for a view that cannot show
      uncovered anatomy anyway (the T-pose back view), where the words and
      the LoRA only drag the figure back toward the camera.

    Returns the path to the generated image, or None on failure.
    """
    from app.core.dependencies import get_skill_manager
    from app.models.character import (
        get_character_appearance,
        get_character_images_dir,
        postprocess_outfit_image)
    from app.core.outfit_renderer import render_outfit

    # Load the equipped state if it was not handed in
    if equipped_pieces is None or equipped_items is None:
        try:
            from app.models.inventory import get_equipped_pieces, get_equipped_items
            if equipped_pieces is None:
                equipped_pieces = get_equipped_pieces(character_name)
            if equipped_items is None:
                equipped_items = get_equipped_items(character_name)
        except Exception:
            equipped_pieces = equipped_pieces or {}
            equipped_items = equipped_items or []

    # Outfit text via the central renderer (plan §4). equipped_pieces/items
    # are passed in so set previews work (override against the profile state).
    from app.models.character import get_character_profile as _gcp_render
    _render_profile = _gcp_render(character_name) or {}
    _rendered = render_outfit(
        profile=_render_profile,
        equipped_pieces=equipped_pieces,
        equipped_items=equipped_items,
    )
    outfit_desc = _rendered.get("pieces", "")
    items_desc = _rendered.get("items", "")
    _fallback_text = _rendered.get("fallback", "")
    # Free-text wardrobe: a template without an outfit system (a temporary
    # NPC) is dressed by the profile's `outfit_description` alone, and
    # render_outfit puts that text into `full` ONLY — the three keys above
    # are empty. Without this the T-pose reference render, and therefore the
    # 3D mesh built from it, would show an undressed figure. Taken only when
    # nothing is equipped, so a real wardrobe can never be overridden; the
    # `wearing: ` prefix is stripped because the outfit layer below supplies
    # its own "is wearing".
    if not outfit_desc and not items_desc and not (equipped_pieces or equipped_items):
        _free_text = _rendered.get("full", "") or ""
        if _free_text.startswith("wearing: "):
            outfit_desc = _free_text[len("wearing: "):].strip()

    # One state snapshot for key AND sidecar — the render below uses the
    # same trigger state, so key, image and manifest describe one moment.
    if apply_state_modifiers:
        from app.core.model_refs import state_fingerprint
        _state_fp = state_fingerprint(character_name)
    else:
        _state_fp = ""
    # The two catalog axes — the same values go into the key, the prompt and
    # the sidecar, so an image can never disagree with the key it hangs under.
    _pose_key = (pose_key or "").strip().lower()
    _expression_key = resolve_expression_key(mood)
    cache_key = _cache_key(mood, _pose_key, character_name,
                            equipped_pieces, equipped_items,
                            state_fp=_state_fp)

    logger.info("Expression generation: %s expression='%s' pose='%s' equipped=%d/%d",
                character_name, _expression_key, _pose_key or "-",
                len(equipped_pieces or {}), len(equipped_items or []))

    # Resolve prompts via PromptBuilder — separated for correct ordering
    from app.core.prompt_builder import PromptBuilder
    if expression_prompt_override is not None:
        expression_prompt = expression_prompt_override.strip()
    else:
        expression_prompt = get_expression_prompt(_expression_key)
    # Catalog pose prompts ("The person is seated…") are human-centric. Apply
    # them only for humanoid characters; animals get the bare key as their
    # pose text ("sleeping", "lying") — the image model maps that onto their
    # anatomy without a human pose template.
    _humanoid = True
    try:
        from app.models.character_template import is_feature_enabled as _ife
        _humanoid = _ife(character_name, "humanoid")
    except Exception:
        pass
    if pose_prompt_override is not None:
        pose_prompt = pose_prompt_override.strip()
    elif _humanoid:
        # Empty/unknown key → the default pose prompt (admin override wins).
        pose_prompt = get_pose_prompt(_pose_key)
    else:
        pose_prompt = _pose_key

    # Active states (drunk, aroused, ...) flow into the appearance via
    # prompt_filters.apply_image_modifiers (PromptBuilder person path) —
    # additive fragments AND "A -> B" replacements, tag- or
    # condition-triggered alike.

    _expr_builder = PromptBuilder(character_name,
                                  apply_state_modifiers=apply_state_modifiers,
                                  include_exposed=include_exposed)
    persons = _expr_builder.detect_persons("", character_names=[character_name])
    appearance = persons[0].appearance if persons else get_character_appearance(character_name)
    actor_label = persons[0].actor_label if persons else character_name

    # Prompt prefix: only passed for an explicit preview (wardrobe); it stays
    # empty for automatic expression regens.
    _prompt_prefix = (prompt_prefix or "").strip()

    # Separate prompts: prefix, character (appearance), outfit, pose, expression
    character_prompt = f"{actor_label}, {appearance}"
    # outfit_desc / items_desc / _fallback_text come from render_outfit()
    # above — single source in app.core.outfit_renderer (plan §4).

    # "is wearing" only when at least one piece slot is filled.
    if outfit_desc:
        if _fallback_text:
            outfit_prompt = f"{_fallback_text}, {actor_label} is wearing {outfit_desc}"
        else:
            outfit_prompt = f"{actor_label} is wearing {outfit_desc}"
    else:
        outfit_prompt = _fallback_text

    # Equipped non-piece items (spells, tools, ...) get their own phrase, so
    # prompt_fragment="holding a glowing recall stone" reads as
    # "{actor} holding a glowing recall stone", not as "is wearing".
    if items_desc:
        if outfit_prompt:
            outfit_prompt = f"{outfit_prompt}. {actor_label} {items_desc}"
        else:
            outfit_prompt = f"{actor_label} {items_desc}"

    # Core image service (wave-6 split)
    from app.imagegen.service import get_image_service, render_has_reference_image
    image_skill = get_image_service()
    if not image_skill.enabled:
        logger.warning("image service not available")
        return None
    # A variant render pins the character's profile image as identity reference,
    # so it prefers img2img — the SAME preference get_outfit_lora_options uses, so
    # the LoRA list and this render resolve to the same backend.
    _has_ref = render_has_reference_image(character_name)

    # Read the per-character override early — allows render/model/LoRA
    # overrides per character (configurable in the character editor).
    model_override = ""
    loras_override = None
    char_render_override = ""
    try:
        from app.models.character import get_character_profile as _gcp
        _prof = _gcp(character_name) or {}
        _char_override = _prof.get("outfit_imagegen") or {}
        if isinstance(_char_override, dict):
            # Legacy field name "workflow" — now a backend glob.
            char_render_override = (_char_override.get("workflow") or "").strip()
            # why: the T-pose reference renders feed the image->3D chain, so a
            # character may route them to a pose-controlled alias of its own
            # while every other render stays on the normal match. Empty = the
            # normal render match.
            _tpose_override = (_char_override.get("tpose_workflow") or "").strip()
            if _tpose_override and image_use_case in TPOSE_USE_CASES:
                char_render_override = _tpose_override
            m = (_char_override.get("model") or "").strip()
            l = _char_override.get("loras")
            if m:
                model_override = m
            if isinstance(l, list):
                loras_override = l
            # why: the T-pose match may route to a different backend with its
            # own LoRA ecosystem (e.g. a pose/turnaround LoRA), so this list
            # REPLACES the normal per-character one for those renders instead
            # of merging. Empty = the normal LoRAs apply.
            _tpose_loras = _char_override.get("tpose_loras")
            if (isinstance(_tpose_loras, list) and _tpose_loras
                    and image_use_case in TPOSE_USE_CASES):
                loras_override = _tpose_loras
    except Exception as _err:
        logger.debug("Outfit-ImageGen-Override lesen fehlgeschlagen: %s", _err)

    # Backend selection (backend-only; ComfyUI workflows removed):
    # char override (backend glob) -> env default spec -> agent default.
    backend = None
    if char_render_override:
        backend = image_skill.match_backend(char_render_override,
                                            has_input_image=_has_ref)
        if not backend:
            logger.warning(
                "Character render override '%s' matches no available backend",
                char_render_override)
    if not backend:
        _expr_default = os.environ.get("EXPRESSION_IMAGEGEN_DEFAULT", "").strip()
        if not _expr_default:
            _expr_default = os.environ.get("OUTFIT_IMAGEGEN_DEFAULT", "").strip()
        if _expr_default:
            backend = image_skill.resolve_imagegen_target(_expr_default)
    if not backend:
        backend = image_skill._wait_for_backend(character_name,
                                                has_input_image=_has_ref)
    if not backend:
        logger.warning("No backend available for the expression regen")
        return None
    backend_name = backend.name
    logger.info("Expression regen: backend=%s (char override=%s)",
                backend_name, "yes" if char_render_override else "no")

    # Resolution from admin config (image_generation.outfit_image_width/height)
    # — expression variants use the same resolution as wardrobe outfit images.
    # An explicit override wins (the T-pose needs a wider frame than the
    # portrait format). When unset, generation falls back to the backend default.
    outfit_w = override_width or int(os.environ.get("OUTFIT_IMAGE_WIDTH", 0) or 0) or None
    outfit_h = override_height or int(os.environ.get("OUTFIT_IMAGE_HEIGHT", 0) or 0) or None

    # Single prompt: prefix + character + outfit + pose + expression in one string
    parts = [_prompt_prefix, character_prompt]
    if outfit_prompt:
        parts.append(outfit_prompt)
    parts.append(pose_prompt)
    parts.append(expression_prompt)
    full_prompt = ", ".join(p for p in parts if p)
    payload = {
        "prompt": full_prompt,
        "input": full_prompt,
        "agent_name": character_name,
        "user_id": "",
        "set_profile": False,
        "skip_gallery": True,
        "auto_enhance": False,
        "backend": backend_name,
        "equipped_pieces_override": equipped_pieces or {},
        # Profile image as input_reference_image_1 (identity consistency).
        # profile_only prevents the self-reference loop via an already
        # existing variant. Backends without ref slots ignore it.
        "profile_only": True,
        "appearances": [{"name": character_name, "appearance": appearance or ""}],
    }

    if outfit_w:
        payload["override_width"] = outfit_w
    if outfit_h:
        payload["override_height"] = outfit_h

    if model_override:
        payload["model_override"] = model_override
    # LoRAs: character override + slot-override LoRAs of ACTIVE (empty,
    # uncovered) slots from render_outfit — e.g. an anatomy LoRA bound to
    # the unequipped underwear slot. Character override first, dedup by name.
    _merged_loras = list(loras_override or [])
    _have = {str(l.get("name")) for l in _merged_loras if isinstance(l, dict)}
    # Without the exposed fragments their LoRAs go too: an anatomy LoRA
    # renders what the prompt no longer asks for.
    for _sl in ((_rendered.get("loras") or []) if include_exposed else []):
        if str(_sl.get("name")) not in _have:
            _merged_loras.append(_sl)
            _have.add(str(_sl.get("name")))
    if _merged_loras:
        payload["loras"] = _merged_loras
    payload["image_use_case"] = image_use_case

    try:
        img_result = image_skill.generate_from_input(json.dumps(payload))

        # Backend fallback on timeout: when the pinned backend is not
        # available, drop the backend binding and re-run execute() with
        # auto selection — the match/availability logic IS the fallback.
        # model_override + loras are reset because a local model name /
        # LoRAs are not valid on another backend.
        if isinstance(img_result, str) and "Timeout" in img_result and "verfuegbar" in img_result:
            payload_fb = dict(payload)
            payload_fb.pop("backend", None)
            payload_fb.pop("model_override", None)
            payload_fb.pop("loras", None)
            logger.warning(
                "Expression regen: backend '%s' offline — using auto backend",
                backend_name)
            img_result = image_skill.generate_from_input(json.dumps(payload_fb))

        # Extract filename from result
        match = re.search(r'/images/([^?)\n]+)', img_result)
        if not match:
            logger.warning("Could not extract the file name: %s", img_result[:200])
            return None

        image_filename = match.group(1)
        images_dir = get_character_images_dir(character_name)
        src_path = images_dir / image_filename

        if not src_path.exists():
            logger.warning("Generated image not found: %s", src_path)
            return None

        # Post-process (rembg + crop) in a temporary path, then move into
        # place — prevents the frontend from picking up the unprocessed
        # image via polling. With output_stem the target is the model_refs
        # location instead of the expression-variant cache.
        if output_stem is not None:
            out_dir = output_stem.parent
            out_dir.mkdir(parents=True, exist_ok=True)
            out_stem_name = output_stem.name
        else:
            out_dir = _get_expressions_dir(character_name)
            out_stem_name = cache_key
        tmp_path = out_dir / f".tmp_{out_stem_name}{src_path.suffix}"
        shutil.move(str(src_path), str(tmp_path))

        try:
            final_tmp = postprocess_outfit_image(tmp_path)
        except Exception as pp_err:
            logger.warning("Post-processing failed, using the original: %s", pp_err)
            final_tmp = tmp_path

        # Rename atomically into the target path
        final_path = out_dir / f"{out_stem_name}{final_tmp.suffix}"
        if output_stem is not None:
            # Fixed stem: drop a stale ref with a different extension
            # (e.g. old tpose.jpg being replaced by tpose.png).
            for _old in out_dir.glob(f"{out_stem_name}.*"):
                if _old.suffix.lower() != ".json" and _old != final_path:
                    _old.unlink()
        final_tmp.rename(final_path)
        # Clean up the temp file if the suffix changed (e.g. .jpg -> .png)
        if tmp_path != final_tmp and tmp_path.exists():
            tmp_path.unlink()

        # Cleanup: remove any leftover temp files
        _cleanup_stale_temps(out_dir)

        # Metadata JSON next to the image. equipped_pieces/items are recorded
        # so invalidate_variants_for_item can delete exactly the variants that
        # actually contained the changed item. The generation meta is read
        # thread-locally — prevents collisions when expression regens for
        # different characters run in parallel.
        _tls = getattr(image_skill, '_meta_tls', None)
        _gen_meta = getattr(_tls, 'last_image_meta', None) if _tls is not None else None
        if _gen_meta is None:
            _gen_meta = getattr(image_skill, 'last_image_meta', {}) or {}
        _expr_meta = {
            "provider": _gen_meta.get("backend_type", ""),
            "service": _gen_meta.get("backend", ""),
            "model": _gen_meta.get("model", ""),
            "loras": _gen_meta.get("loras", []),
            "prompt": full_prompt,
            "negative_prompt": _gen_meta.get("negative_prompt", ""),
            "characters": [character_name],
            "reference_images": _gen_meta.get("reference_images", {}),
            "seed": _gen_meta.get("seed", 0),
            "created_at": _gen_meta.get("created_at", ""),
            "duration_s": _gen_meta.get("duration_s", 0),
            "workflow": _gen_meta.get("workflow", ""),
            # Free-text mood for the admin listing, the KEYS for every
            # machine-side comparison (find_nearest_expression).
            "mood": mood,
            "expression_key": _expression_key,
            # The variant list in the admin UI shows this as "activity".
            "activity": _pose_key,
            "pose_key": _pose_key,
            "equipped_pieces": equipped_pieces or {},
            "equipped_items": equipped_items or [],
            "state_fingerprint": _state_fp,
        }
        try:
            _meta_path = final_path.with_suffix(".json")
            _meta_path.write_text(json.dumps(_expr_meta, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as _me:
            logger.warning("Writing the expression meta failed: %s", _me)

        logger.info("Expression image generated: %s", final_path.name)

        # (The visual-analysis trigger that used to sit here fed the pose
        # variant cache — removed with it, Aug 2026. Its example_image guard
        # only ever deduplicated that analysis job; nothing is enqueued any
        # more, so there is nothing left to deduplicate. The image cache
        # itself is keyed by pose_key/expression_key and stays as it was.)

        return final_path

    except Exception as e:
        logger.error("Expression generation failed: %s", e)
        return None


def _update_refs_in_json(json_file: Path, rename_map: Dict[str, str],
                         oid_to_safe: Optional[Dict[str, str]] = None) -> None:
    """Update reference_images entries in a JSON file using the rename map.

    Also uses oid_to_safe to fix references to deleted variants not in rename_map.
    """
    # Pattern: {8-hex-outfit-id}_{12-hex-hash}.ext  (old format without char name)
    _old_variant_re = re.compile(r'^([0-9a-f]{8})_[0-9a-f]{12}\.\w+$')
    try:
        data = json.loads(json_file.read_text(encoding="utf-8"))
        refs = data.get("reference_images", {})
        changed = False
        for slot, ref_filename in refs.items():
            if ref_filename in rename_map:
                refs[slot] = rename_map[ref_filename]
                changed = True
            elif oid_to_safe:
                m = _old_variant_re.match(ref_filename)
                if m:
                    oid = m.group(1)
                    safe = oid_to_safe.get(oid)
                    if safe:
                        refs[slot] = f"{safe}_{ref_filename}"
                        changed = True
        if changed:
            json_file.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8")
    except Exception:
        pass


def migrate_variant_filenames() -> int:
    """Rename old-format variant files ({oid}_{hash}) to new format ({CharName}_{oid}_{hash}).

    Also updates reference_images entries in image JSON metadata.
    Returns number of files renamed.
    """
    from app.models.character import (
        get_character_outfits_dir, get_character_images_dir)
    from app.core.paths import get_storage_dir

    renamed = 0
    sd = get_storage_dir()
    chars_dir = sd / "characters"
    if not chars_dir.exists():
        return 0

    # Phase 1: Rename variant files and build global rename map
    global_rename_map: Dict[str, str] = {}  # old_name -> new_name
    _oid_to_safe: Dict[str, str] = {}  # outfit_id -> safe character name
    for char_dir in chars_dir.iterdir():
        if not char_dir.is_dir():
            continue
        character_name = char_dir.name
        safe = _safe_name(character_name)
        variants_dir = char_dir / "outfits" / "variants"
        if not variants_dir.exists():
            continue

        for f in variants_dir.iterdir():
            if not f.is_file() or f.name.startswith("."):
                continue
            if f.stem.startswith(f"{safe}_"):
                # Already migrated — record old->new mapping for JSON updates
                old_name = f.name[len(safe) + 1:]  # strip "{safe}_" prefix
                global_rename_map[old_name] = f.name
                continue
            new_name = f"{safe}_{f.name}"
            old_path = variants_dir / f.name
            new_path = variants_dir / new_name
            if not new_path.exists():
                old_path.rename(new_path)
                renamed += 1
            global_rename_map[f.name] = new_name

    # Also build outfit_id -> safe_name map from outfit configs
    # so we can fix references to deleted variant files too
    for char_dir in chars_dir.iterdir():
        if not char_dir.is_dir():
            continue
        safe = _safe_name(char_dir.name)
        # Outfits are stored in character_profile.json under "outfits"
        profile_json = char_dir / "character_profile.json"
        if profile_json.exists():
            try:
                profile_data = json.loads(profile_json.read_text(encoding="utf-8"))
                for o in profile_data.get("outfits", []):
                    oid = o.get("id", "")
                    if oid:
                        _oid_to_safe[oid] = safe
            except Exception:
                pass
        # Also derive from existing variant filenames (covers deleted outfits)
        variants_dir = char_dir / "outfits" / "variants"
        if variants_dir.exists():
            for f in variants_dir.iterdir():
                if f.is_file() and f.stem.startswith(f"{safe}_"):
                    # e.g. Zula_18d0d47a_hash -> oid=18d0d47a
                    parts = f.stem[len(safe) + 1:].split("_", 1)
                    if parts:
                        _oid_to_safe[parts[0]] = safe

    if global_rename_map or _oid_to_safe:
        # Phase 2: Update reference_images in ALL characters' image JSONs
        for char_dir in chars_dir.iterdir():
            if not char_dir.is_dir():
                continue
            images_dir = char_dir / "images"
            if not images_dir.exists():
                continue
            for json_file in images_dir.glob("*.json"):
                _update_refs_in_json(json_file, global_rename_map, _oid_to_safe)

        # Phase 3: Update reference_images in Instagram JSONs
        instagram_dir = sd / "instagram"
        if instagram_dir.exists():
            for json_file in instagram_dir.glob("*.json"):
                _update_refs_in_json(json_file, global_rename_map, _oid_to_safe)
            # Auch metadata/ Unterverzeichnis
            meta_dir = instagram_dir / "metadata"
            if meta_dir.exists():
                for json_file in meta_dir.glob("*.json"):
                    _update_refs_in_json(json_file, global_rename_map, _oid_to_safe)

    if renamed:
        logger.info("Variant migration: %d files renamed (character-name prefix)", renamed)
    return renamed
