"""State filters drop thought-context blocks and add prompt/image/motion modifiers.

Replaces the old ``danger_system.build_status_prompt_section`` rule path.
Each filter has:
    condition       — generic expression evaluated against character state
    drop_blocks     — list of *_block keys to clear from the prompt
    prompt_modifier — text rendered in the effects section so the LLM
                      sees what state is active

Storage:
    shared/prompt_filters/filters.json — versioned baseline
    world.db.prompt_filters             — per-world overlay (replaces by id)

Public API:
    apply_filters(character_name, ctx) -> dict
        mutates ctx in place: drops listed blocks, sets effects_block
        from accumulated modifier text. Returns the same ctx for chaining.
"""
import json
from contextlib import contextmanager
from contextvars import ContextVar
from threading import RLock
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from app.core.log import get_logger

logger = get_logger("prompt_filters")


_SHARED_FILE = Path(__file__).resolve().parent.parent.parent / "shared" / "prompt_filters" / "filters.json"


def _load_shared() -> List[Dict[str, Any]]:
    """Read baseline filters from the shared JSON file. Empty on miss/parse-fail."""
    try:
        if not _SHARED_FILE.exists():
            return []
        data = json.loads(_SHARED_FILE.read_text(encoding="utf-8"))
        return list(data.get("filters") or [])
    except Exception as e:
        logger.warning("shared prompt_filters load failed: %s", e)
        return []


def _load_world() -> List[Dict[str, Any]]:
    """Read per-world filters from the prompt_filters table."""
    try:
        from app.core.db import get_connection
        conn = get_connection()
        rows = conn.execute(
            "SELECT id, condition, label, drop_blocks, prompt_modifier, "
            "enabled, meta, icon, image_modifier, bone_pose "
            "FROM prompt_filters"
        ).fetchall()
        out: List[Dict[str, Any]] = []
        for r in rows:
            try:
                drops = json.loads(r[3] or "[]")
            except Exception:
                drops = []
            try:
                meta = json.loads(r[6] or "{}")
            except Exception:
                meta = {}
            try:
                bone_pose = json.loads(r[9] or "{}")
            except (TypeError, ValueError):
                bone_pose = {}
            out.append({
                "id": r[0] or "",
                "condition": r[1] or "",
                "label": r[2] or "",
                "drop_blocks": drops if isinstance(drops, list) else [],
                "prompt_modifier": r[4] or "",
                "enabled": bool(r[5]),
                "meta": meta,
                "icon": r[7] or "",
                "image_modifier": r[8] or "",
                "bone_pose": bone_pose if isinstance(bone_pose, dict) else {},
            })
        return out
    except Exception as e:
        logger.debug("world prompt_filters load failed: %s", e)
        return []


_snapshot_lock = RLock()
_snapshot_key = None
_snapshot = None
_render_modifiers = ContextVar("render_modifiers", default=None)


def invalidate_filter_snapshot():
    """Invalidate definitions after a successful store mutation."""
    global _snapshot_key
    with _snapshot_lock:
        _snapshot_key = None


@contextmanager
def image_modifier_snapshot(character_name):
    """Pin one render's directives for its key and every prompt consumer."""
    directives = collect_image_modifiers(character_name)
    token = _render_modifiers.set((character_name, directives))
    try:
        yield directives
    finally:
        _render_modifiers.reset(token)


def load_filters() -> List[Dict[str, Any]]:
    """Merge shared + world filters. World entries override shared by id."""
    global _snapshot_key, _snapshot
    from app.core import paths
    from copy import deepcopy
    with _snapshot_lock:
        stat = _SHARED_FILE.stat() if _SHARED_FILE.exists() else None
        key = (str(paths.get_storage_dir()), str(_SHARED_FILE),
               (stat.st_mtime_ns, stat.st_size) if stat else None)
        if key != _snapshot_key:
            by_id = {}
            for entry in (*_load_shared(), *_load_world()):
                fid = (entry.get("id") or "").strip()
                if fid:
                    by_id[fid] = entry
            _snapshot = list(by_id.values())
            _snapshot_key = key
        return deepcopy(_snapshot)


def _evaluate(condition: str, character_name: str, location_id: str = "") -> bool:
    """Reuse the existing condition evaluator (stamina<10, has_condition:X, …)."""
    if not condition:
        return False
    try:
        from app.core.activity_engine import evaluate_condition
        passed, _ = evaluate_condition(condition, character_name, location_id)
        return bool(passed)
    except Exception as e:
        logger.debug("evaluate_condition('%s') failed for %s: %s",
                     condition, character_name, e)
        return False


def _has_tag_condition(character_name: str, tag: str, profile=None) -> bool:
    """True if ``tag`` is in the character's profile.active_conditions list.

    Filter-id triggers implicitly when the same name is set as a tag
    (e.g. via apply_condition). So a filter ``id=drunk`` doesn't need
    ``condition: condition:drunk`` anymore — the id makes the tag entry
    point automatic.
    """
    if not tag or not character_name:
        return False
    try:
        from app.models.character import get_character_profile
        if profile is None:
            profile = get_character_profile(character_name) or {}
        active = profile.get("active_conditions", []) or []
        tag_l = tag.strip().lower()
        return any((c.get("name") or "").strip().lower() == tag_l for c in active)
    except Exception:
        return False


def _resolve_avatar_name() -> str:
    """Substitute the request avatar, otherwise the unique world avatar.

    Background calls with zero or multiple avatars use "the avatar".
    """
    try:
        from app.models.account import get_active_character
        ac = (get_active_character() or "").strip()
        if ac:
            return ac
    except Exception:
        pass
    try:
        from app.models.account import get_all_avatars
        avs = sorted(a for a in (get_all_avatars() or set()) if a)
        if len(avs) == 1:
            return avs[0]
    except Exception:
        pass
    return "the avatar"


def _condition_source(character_name: str, cond_name: str) -> str:
    """The active condition's giver, recorded by apply_item_effects on consumption."""
    if not cond_name:
        return ""
    try:
        from app.models.character import get_character_profile
        for c in (get_character_profile(character_name) or {}).get("active_conditions", []) or []:
            if isinstance(c, dict) and (c.get("name") or "").lower() == cond_name.lower():
                return (c.get("source_character") or "").strip()
    except Exception:
        pass
    return ""


def _substitute(modifier: str, character_name: str, fid: str, avatar_subst: str) -> str:
    """Substitute avatar and condition giver; a missing giver falls back to avatar."""
    out = modifier.replace("{avatar}", avatar_subst)
    if "{giver}" in out:
        out = out.replace("{giver}", _condition_source(character_name, fid) or avatar_subst)
    return out


def active_modifiers(character_name: str, location_id: str = "") -> List[str]:
    """Triggered prompt modifiers for paths without a thought context.

    Chat replies see the same state effects; block drops stay thought-specific.
    """
    out: List[str] = []
    try:
        filters = load_filters()
        avatar_subst = _resolve_avatar_name()
        for f in filters:
            if not f.get("enabled", True):
                continue
            fid = (f.get("id") or "").strip()
            condition = (f.get("condition") or "").strip()
            triggered = (fid and _has_tag_condition(character_name, fid)) \
                or (bool(condition) and _evaluate(condition, character_name, location_id))
            if not triggered:
                continue
            modifier = (f.get("prompt_modifier") or "").strip()
            if modifier:
                out.append(_substitute(modifier, character_name, fid, avatar_subst))
    except Exception as e:
        logger.debug("active_modifiers(%s) failed: %s", character_name, e)
    return out


def triggered_state_labels(character_name: str,
                           location_id: str = "") -> List[str]:
    """Labels of the character's currently TRIGGERED states (tag OR
    condition) — used to show visible states of OTHER present characters
    in thought prompts ('aroused', 'drunk', ...)."""
    out: List[str] = []
    try:
        for f in load_filters():
            if not f.get("enabled", True):
                continue
            fid = (f.get("id") or "").strip()
            condition = (f.get("condition") or "").strip()
            triggered = (fid and _has_tag_condition(character_name, fid)) \
                or (bool(condition) and _evaluate(condition, character_name, location_id))
            if triggered:
                out.append((f.get("label") or fid or "").strip())
    except Exception as e:
        logger.debug("triggered_state_labels(%s) failed: %s", character_name, e)
    return [l for l in out if l]


def _triggered_filters(character_name: str, location_id: str = "", profile=None):
    """Share profile fields and expression results across all state definitions."""
    if profile is None:
        from app.models.character import get_character_profile
        profile = get_character_profile(character_name) or {}
    atoms = {}
    from app.plugins.registry import flag_specs
    flags = {"is_sleeping", *(spec.flag for spec in flag_specs())}

    def atom(text):
        text = text.strip().lower()
        if text not in atoms:
            negated = text.startswith("not ")
            raw = text[4:].strip() if negated else text
            match = re.fullmatch(r"([a-z_]+)([><=])(\d+)", raw)
            if raw.startswith("condition:"):
                result = _has_tag_condition(character_name, raw.split(":", 1)[1], profile)
            elif match and match[1] not in {"mood", "relationship", "romantic"}:
                value = (profile.get("status_effects") or {}).get(match[1], 100)
                threshold = int(match[3])
                result = {">": value > threshold, "<": value < threshold, "=": int(value) == threshold}[match[2]]
            elif raw in flags:
                result = bool(profile.get(raw))
            elif raw.startswith("mood:"):
                current = (profile.get("current_feeling") or "").lower()
                target = raw.split(":", 1)[1].strip()
                result = target in current or current in target
            elif raw.startswith("current_activity:"):
                from app.models.character import get_effective_activity
                current = get_effective_activity(character_name, profile=profile).lower()
                target = raw.split(":", 1)[1].strip()
                result = bool(current) and (target in current or current in target)
            else:
                result = _evaluate(raw, character_name, location_id)
            atoms[text] = not result if negated else result
        return atoms[text]

    for state in load_filters():
        if not state.get("enabled", True):
            continue
        fid = (state.get("id") or "").strip()
        condition = (state.get("condition") or "").strip()
        if ((fid and _has_tag_condition(character_name, fid, profile))
                or (condition and any(all(atom(part) for part in re.split(r"\s+AND\s+", group, flags=re.I))
                                      for group in re.split(r"\s+OR\s+", condition, flags=re.I)))):
            yield state


def collect_image_modifiers(character_name: str,
                            location_id: str = "") -> "Tuple[List[Tuple[str, str]], List[str]]":
    """image_modifier of every TRIGGERED state (profile tag OR condition
    expression — same trigger logic as the prompt filters; the old
    collector only saw tags).

    Each non-empty line is a directive:
        "A -> B" (or "A → B")  — replacement applied to the person
                                  description ("neat hair -> messy
                                  tousled hair")
        anything else           — additive fragment, appended
    Returns (replacements, additive).
    """
    pinned = _render_modifiers.get()
    if pinned is not None and pinned[0] == character_name:
        return pinned[1]
    replacements: List[Tuple[str, str]] = []
    additive: List[str] = []
    try:
        for f in _triggered_filters(character_name, location_id):
            for line in (f.get("image_modifier") or "").splitlines():
                line = line.strip()
                if not line:
                    continue
                parts = re.split(r"\s*(?:->|→)\s*", line, maxsplit=1)
                if len(parts) == 2 and parts[0].strip():
                    replacements.append((parts[0].strip(), parts[1].strip()))
                else:
                    additive.append(line)
    except Exception as e:
        logger.debug("collect_image_modifiers(%s) failed: %s", character_name, e)
    return replacements, additive


def apply_image_modifiers(character_name: str, text: str,
                          location_id: str = "") -> str:
    """Apply the triggered states' image directives to a person
    description: replacements rewrite (case-insensitive), additive
    fragments append. Never raises — on any error the text passes
    through unchanged."""
    try:
        replacements, additive = collect_image_modifiers(character_name, location_id)
        out = text or ""
        for find, repl in replacements:
            out = re.sub(re.escape(find), repl, out, flags=re.IGNORECASE)
        if additive:
            extra = ", ".join(additive)
            out = f"{out}, {extra}" if out.strip() else extra
        return out
    except Exception:
        return text


def apply_filters(character_name: str,
                  ctx: Dict[str, Any],
                  location_id: str = "") -> Dict[str, Any]:
    """Apply state-driven filters to a thought context dict.

    Drops blocks listed in triggered filters' ``drop_blocks`` (sets them to
    "" so the {% if %} gate skips them). Collects ``prompt_modifier`` text
    of all triggered filters into ``effects_block``.

    Mutates and returns the same ctx for caller convenience.
    """
    filters = load_filters()
    if not filters:
        return ctx

    triggered_modifiers: List[str] = []
    dropped: set = set()

    # Resolve the request avatar or unique world avatar for background thoughts.
    avatar_subst = _resolve_avatar_name()

    for f in filters:
        if not f.get("enabled", True):
            continue
        fid = (f.get("id") or "").strip()
        condition = (f.get("condition") or "").strip()
        # The id tag or an evaluated expression can trigger the state.
        # Without either trigger it remains inactive.
        triggered = (fid and _has_tag_condition(character_name, fid)) \
            or (bool(condition) and _evaluate(condition, character_name, location_id))
        if not triggered:
            continue
        for blk in (f.get("drop_blocks") or []):
            if isinstance(blk, str) and blk:
                dropped.add(blk)
        modifier = (f.get("prompt_modifier") or "").strip()
        if modifier:
            modifier = _substitute(modifier, character_name, fid, avatar_subst)
            triggered_modifiers.append(modifier)
        logger.debug("prompt_filter triggered: %s for %s", fid, character_name)

    # Fine-grained skill-block drops: an entry "skill:<package_id>" drops only
    # that package's thought_context_block, not the whole skill_context_blocks.
    skill_drops = {b.split(":", 1)[1].strip() for b in dropped
                   if isinstance(b, str) and b.startswith("skill:") and ":" in b}

    for blk in dropped:
        if isinstance(blk, str) and blk.startswith("skill:"):
            continue  # handled below (not a plain ctx block key)
        if blk in ctx:
            ctx[blk] = ""

    # Remove the addressed packages' parts and re-join skill_context_blocks. The
    # coarse "skill_context_blocks" drop (all packages) still works via the loop
    # above. _skill_block_parts comes from thought_context._build_skill_context_blocks.
    if skill_drops and isinstance(ctx.get("_skill_block_parts"), list):
        kept = [(pid, txt) for (pid, txt) in ctx["_skill_block_parts"]
                if pid not in skill_drops]
        ctx["_skill_block_parts"] = kept
        ctx["skill_context_blocks"] = "\n\n".join(txt for _, txt in kept)

    # effects_block = aggregated modifiers. Overrides whatever build_thought_context
    # populated for this key (typically empty now since rules are deactivated).
    effects = "\n".join(f"- {m}" for m in triggered_modifiers)
    if effects:
        ctx["effects_block"] = effects

    return ctx


BONE_POSE_FIELDS = ("rest_deg", "gravity", "freq", "zeta", "gain", "flatten", "spill", "length", "girth")


def valid_bone_pose_number(number, *, signed=False):
    """Finite JSON number, optionally signed, excluding booleans and overflowing integers."""
    import math
    if isinstance(number, bool) or not isinstance(number, (int, float)) or (not signed and number < 0):
        return False
    try:
        return math.isfinite(number)
    except OverflowError:
        return False


def validate_bone_pose(value):
    """Validate sparse state angles and multipliers; preserve unloaded groups for packs."""
    if not isinstance(value, dict):
        raise ValueError("bone_pose must be an object")
    from app.core.extension_rig import control_allowed, declared_motion_groups
    groups = {group["id"]: group for group in declared_motion_groups()}
    for gid, fields in value.items():
        if not isinstance(gid, str) or not gid.strip() or not isinstance(fields, dict):
            raise ValueError("bone_pose groups must be objects with non-empty ids")
        if set(fields) - set(BONE_POSE_FIELDS):
            raise ValueError("unknown bone_pose field")
        for key, number in fields.items():
            if not control_allowed(groups.get(gid, {}), key):
                raise ValueError(f"bone_pose.{gid}.{key} is not allowed")
            if not valid_bone_pose_number(number, signed=key == "rest_deg"):
                raise ValueError(f"bone_pose.{gid}.{key} must be finite" if key == "rest_deg" else f"bone_pose.{gid}.{key} must be finite and non-negative")
            if key in ("length", "girth") and not .5 <= number <= 2:
                raise ValueError(f"bone_pose.{gid}.{key} must be within [0.5, 2.0]")
            if key == "rest_deg" and abs(number) > 180:
                raise ValueError(f"bone_pose.{gid}.rest_deg must be within [-180, 180]")
    return value


def collect_bone_poses(character_name, location_id="", profile=None):
    """Active ids and sparse pose values for revision hashing, including explicit zero."""
    out = [{"id": state["id"], "bone_pose": state.get("bone_pose") or {}}
           for state in _triggered_filters(character_name, location_id, profile)]
    return sorted(out, key=lambda state: state["id"])
