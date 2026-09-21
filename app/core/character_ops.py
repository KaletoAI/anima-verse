"""Character-domain operations behind app/routes/characters.py.

Logic moved 1:1 out of the route handlers (code-review section 5a); the
routes remain thin HTTP adapters (auth, request parsing, response types).
HTTPExceptions that were embedded mid-logic moved along unchanged.
"""
from fastapi import HTTPException
from typing import Any, Dict, List, Optional
from app.core.log import get_logger

logger = get_logger("characters")

from app.core.timeutils import parse_iso, utc_now

# File-default whitelist (single source of truth for the soul editor UI)
from app.core.soul_sections import (
    EDITABLE_SECTIONS as _SOUL_EDITABLE,
    LOCKED_SECTIONS as _SOUL_LOCKED,
    SECTION_FILE_MAP as _SOUL_FILE_MAP,
    EDITABLE_MARKER as _SOUL_EDITABLE_MARKER)

DEFAULT_NEW_CHARACTER_SKILLS = (
    # Skill IDs from app/skills/skill_manager.py:SKILL_REGISTRY — the
    # UNMIGRATED built-ins only. Migrated skill packages declare
    # `default_enabled: true` in their plugin.yaml instead; the combined
    # list comes from default_new_character_skills().
    # Defaults for newly created characters -- the list matches the ticks in
    # the Skills tab for a "freshly born" character (everything essential on,
    # special/niche skills like OutfitCreation, VideoGenerator, Retrospect,
    # MarkdownWriter, KnowledgeExtract stay off because they cost tokens/setup
    # and not every NPC needs them).
    "outfit_change",
)


def default_new_character_skills() -> tuple:
    """Skill IDs enabled by default for newly created characters:
    the built-in list plus package-declared defaults (default_enabled)."""
    try:
        from app.plugins.registry import default_enabled_skill_ids
        extra = tuple(sid for sid in default_enabled_skill_ids()
                      if sid not in DEFAULT_NEW_CHARACTER_SKILLS)
    except Exception:
        extra = ()
    return DEFAULT_NEW_CHARACTER_SKILLS + extra


# === Pure helpers ===

def _resolve_face_prompt(profile: dict, character_name: str, tmpl) -> str:
    """Profile-image prompt = face prompt (face_appearance), tokens resolved
    (target_key 'character_appearance' — this resolves both appearance fields).
    Falls back to the body appearance when face_appearance is empty.

    Face-relevant body-slot fragments (``face: true`` in the species
    manifest — hair/eyes/skin) are appended: after the body-slot migration
    those attributes live in slots, not in the text anymore."""
    from app.models.character import get_character_appearance
    from app.models.character_template import resolve_profile_tokens
    face = ((profile or {}).get("face_appearance") or "").strip()
    if face and "{" in face:
        face = resolve_profile_tokens(face, profile, template=tmpl,
                                      target_key="character_appearance")
    if not face:
        face = (get_character_appearance(character_name) or "").strip()
    try:
        from app.core.body_slots import appearance_suffix
        suffix = appearance_suffix(character_name, face_only=True,
                                   profile=profile)
    except Exception:
        suffix = ""
    if suffix:
        face = f"{face}, {suffix}" if face else suffix
    try:
        from app.core.prompt_filters import apply_image_modifiers
        face = apply_image_modifiers(character_name, face)
    except Exception:
        pass
    return face.strip()


def _soul_field_keys(template_id: str) -> set:
    """Set of profile keys whose content comes from an MD file (source_file)."""
    if not template_id:
        return set()
    try:
        from app.models.character_template import get_template
        tmpl = get_template(template_id)
    except Exception:
        return set()
    if not tmpl:
        return set()
    keys = set()
    for section in tmpl.get("sections", []):
        for field in section.get("fields", []):
            if field.get("source_file") and field.get("key"):
                keys.add(field["key"])
    return keys


# ---------------------------------------------------------------------------
# Memory modal v2 — tab-specific logic cores
# Plan: development_instructions/plan-memory-window-redesign.md
# ---------------------------------------------------------------------------

def _score_memory_no_mutate(entry: Dict[str, Any], current_message: str = "") -> float:
    """retrieve_relevant_memories without side effects (no access_count bump).

    Mirrors the score formula from app/models/memory.py:retrieve_relevant_memories
    for the read-only display in the "Today" tab.

    Stamps are SYSTEM time and aware (``utc_now_iso()``); they must be read with
    ``parse_iso`` and compared against ``utc_now()``. A naive comparison raised a
    TypeError inside the try below, so ``age_days`` silently fell back to 30.0
    and the recency boost was permanently off.
    """
    from app.models.memory import _compute_decay, _keyword_overlap, _recency_boost

    decay = _compute_decay(entry)
    importance = entry.get("importance", 3)
    search_text = entry.get("content", "") + " " + " ".join(entry.get("tags", []))
    relevance = _keyword_overlap(search_text, current_message) if current_message else 0.0
    type_bonus = 0.0
    mtype = entry.get("memory_type")
    if mtype == "commitment":
        if "completed" not in entry.get("tags", []):
            type_bonus = 0.3
    elif mtype == "episodic":
        type_bonus = 0.1
    try:
        ts = parse_iso(entry.get("timestamp", ""))
        age_days = max(0, (utc_now() - ts).total_seconds() / 86400)
    except (ValueError, TypeError):
        age_days = 30.0
    recency = _recency_boost(age_days)
    return importance * decay * recency * (1.0 + relevance * 2.0 + type_bonus)


def _bucket_state_lane(events: List[Dict[str, Any]],
                       max_unbucketed: int = 50) -> Dict[str, Any]:
    """Hybrid compaction: above `max_unbucketed` events, group per hour.

    Expects events sorted (oldest first). Returns
    {bucketed: bool, points: [{ts, value, count?}], buckets?: [{hour, dominant, items}]}.
    """
    if len(events) <= max_unbucketed:
        return {"bucketed": False, "points": events}
    # Hour bucketing: per hour slot the dominant value (most frequent)
    buckets: Dict[str, List[Dict[str, Any]]] = {}
    for ev in events:
        ts = ev.get("ts") or ev.get("timestamp") or ""
        hour = ts[:13]  # 'YYYY-MM-DDTHH'
        buckets.setdefault(hour, []).append(ev)
    out_points = []
    out_buckets = []
    for hour in sorted(buckets.keys()):
        items = buckets[hour]
        # dominant = most frequent value
        from collections import Counter
        cnt = Counter(it.get("value", "") for it in items)
        dominant, _ = cnt.most_common(1)[0]
        # Representative ts = last event in this hour
        out_points.append({
            "ts": items[-1].get("ts") or items[-1].get("timestamp"),
            "value": dominant,
            "count": len(items),
        })
        out_buckets.append({
            "hour": hour,
            "dominant": dominant,
            "items": items,
        })
    return {"bucketed": True, "points": out_points, "buckets": out_buckets}


def build_memory_today(character_name: str) -> Dict[str, Any]:
    """Tab "Today": status, 24h lanes, top-K currently relevant memories.

    Read-only — no access_count bump on display.
    """
    from datetime import datetime, timedelta
    from app.core.db import get_connection
    from app.models.memory import load_memories, load_mood_history
    from app.models.character import get_character_profile, get_known_locations
    from app.models.world import (get_location_name, resolve_location,
                                   get_room_by_id, _load_world_data)

    profile = get_character_profile(character_name)
    now = utc_now()
    cutoff = (now - timedelta(hours=24)).isoformat()

    conn = get_connection()
    import json as _json

    # Activity durations (lane band caps) no longer exist — the activity
    # library was removed, poses have no fixed duration.
    activity_durations: Dict[str, Optional[int]] = {}

    # --- 24h state history (all types) — for the lanes ---
    rows = conn.execute(
        "SELECT ts, state_json FROM state_history "
        "WHERE character_name=? AND ts>=? ORDER BY ts ASC",
        (character_name, cutoff),
    ).fetchall()
    activity_lane: List[Dict[str, Any]] = []
    location_lane: List[Dict[str, Any]] = []
    effects_lane: List[Dict[str, Any]] = []
    last_warning: Optional[Dict[str, Any]] = None
    for ts, state_json in rows:
        try:
            s = _json.loads(state_json or "{}")
        except Exception:
            continue
        t = s.get("type", "")
        v = s.get("value", "")
        ev = {"ts": s.get("timestamp", ts), "value": v}
        if t == "activity":
            ev["duration_min"] = activity_durations.get(v)
            activity_lane.append(ev)
        elif t == "location":
            # Resolve location ids into readable names — for the UI display.
            ev["value"] = get_location_name(v) or v
            location_lane.append(ev)
        elif t == "effects":
            effects_lane.append(ev)
        elif t in ("access_denied", "forced_action"):
            last_warning = {"type": t, "value": v, "ts": ev["ts"]}

    # --- 24h mood history ---
    full_mood = load_mood_history(character_name)
    mood_lane = [m for m in full_mood if m.get("timestamp", "") >= cutoff]

    # --- "Since" timestamps of the current state ---
    def _last_change_ts(lane: List[Dict[str, Any]], current: str) -> Optional[str]:
        # Last change TO the current value (scan from oldest to newest).
        last_ts = None
        prev = None
        for ev in lane:
            if ev.get("value") != prev and ev.get("value") == current:
                last_ts = ev.get("ts")
            prev = ev.get("value")
        return last_ts

    current_activity = profile.get("pose_flavor") or profile.get("pose_key") or ""
    current_location_id = profile.get("current_location") or ""
    current_room_id = profile.get("current_room") or ""
    current_mood = profile.get("current_feeling") or profile.get("current_mood") or ""

    # Resolve names (location/room are often UUIDs in the DB)
    location_name = get_location_name(current_location_id) if current_location_id else ""
    room_name = ""
    if current_location_id and current_room_id:
        loc = resolve_location(current_location_id)
        if loc:
            room = get_room_by_id(loc, current_room_id)
            if room:
                room_name = room.get("name", "")

    # "Since" fallback: when the 24h lane is empty, oldest matching state_history entry
    def _since_fallback(state_type: str, current_value: str) -> Optional[str]:
        if not current_value:
            return None
        row = conn.execute(
            "SELECT ts FROM state_history WHERE character_name=? "
            "AND json_extract(state_json,'$.type')=? "
            "AND json_extract(state_json,'$.value')=? "
            "ORDER BY ts DESC LIMIT 1",
            (character_name, state_type, current_value),
        ).fetchone()
        return row[0] if row else None

    # --- Top-K active memories (score-based, without mutation) ---
    all_mem = load_memories(character_name)
    # completed commitments excluded by default
    visible = [m for m in all_mem if "completed" not in (m.get("tags") or [])]
    scored = [(_score_memory_no_mutate(m), m) for m in visible]
    scored.sort(key=lambda x: x[0], reverse=True)
    top = []
    for score, m in scored[:12]:
        top.append({
            "id": m.get("id"),
            "memory_type": m.get("memory_type", "semantic"),
            "ts": m.get("timestamp", ""),
            "content": m.get("content", ""),
            "importance": m.get("importance", 3),
            "decay_factor": round(m.get("decay_factor", 1.0), 3),
            "related_character": m.get("related_character", ""),
            "score": round(score, 3),
            "tags": m.get("tags", []),
        })

    # known_locations now live in their own tab via /memory/locations.

    since_activity = (_last_change_ts(activity_lane, current_activity)
                      or _since_fallback("activity", current_activity))
    # The location lane is post name resolution — compare directly against
    # the raw DB instead of against the resolved lane.
    since_location = _since_fallback("location", current_location_id)
    since_mood = (mood_lane[-1].get("timestamp") if mood_lane
                  else (full_mood[-1].get("timestamp") if full_mood else None))

    # --- Stats (status_effects) — generic from the template, hardcode nothing.
    # Order + labels from the template fields with store=status_effects;
    # additional keys not defined in the template are appended at the end.
    stat_items: List[Dict[str, Any]] = []
    try:
        from app.models.character_template import is_feature_enabled, get_template
        if is_feature_enabled(character_name, "status_effects_enabled"):
            cur_stats = profile.get("status_effects", {}) or {}
            tmpl = get_template(profile.get("template", "")) if profile.get("template") else None
            seen: set = set()
            if tmpl:
                for section in tmpl.get("sections", []):
                    for fld in section.get("fields", []):
                        if fld.get("store") != "status_effects":
                            continue
                        k = fld.get("key")
                        if not k or k not in cur_stats:
                            continue
                        stat_items.append({"key": k, "label": fld.get("label") or k,
                                           "value": cur_stats.get(k)})
                        seen.add(k)
            for k, v in cur_stats.items():
                if k not in seen:
                    stat_items.append({"key": k, "label": k, "value": v})
    except Exception:
        pass

    return {
        "character": character_name,
        "now": now.isoformat(),
        "stats": stat_items,
        "status": {
            "location": location_name or current_location_id,
            "location_id": current_location_id,
            "room": room_name,
            "room_id": current_room_id,
            "activity": current_activity,
            "mood": current_mood,
            "since": {
                "activity": since_activity,
                "location": since_location,
                "mood": since_mood,
            },
            "last_warning": last_warning,
        },
        "lanes_24h": {
            "activity": _bucket_state_lane(activity_lane),
            "location": _bucket_state_lane(location_lane),
            "mood": _bucket_state_lane(
                [{"ts": m.get("timestamp"), "value": m.get("mood")} for m in mood_lane]
            ),
            "effects": _bucket_state_lane(effects_lane),
        },
        "active_memories": top,
    }


def game_label(game_ts: Any, lang: str = "en") -> str:
    """Ready-made world-calendar label for a persisted GAME stamp.

    ``""`` for an empty stamp (rows written before the column existed) and
    for anything that is not a canonical ``Y0002-D109T14:00:00`` string. The
    SERVER renders the label — clients never parse a game stamp themselves,
    and the clock part already carries the configured display format.
    """
    from app.core.game_time import GameTime
    try:
        return GameTime.parse(game_ts).display_label(lang)
    except (ValueError, TypeError):
        return ""


def build_debug_activity(character_name: str) -> Dict[str, Any]:
    """Game-Admin debug: why is a (non-avatar) character behaving this way?

    Aggregates read-only: current feeling + source, most recent mood/state/
    thought activity and active block/force rules into a "why" reasoning. No
    avatar binding — the name comes from the path.
    """
    from app.core.db import get_connection
    from app.models.memory import load_mood_history
    from app.models.character import (get_character_profile,
                                      get_character_current_feeling, get_state_flags)
    import json as _json

    profile = get_character_profile(character_name) or {}
    feeling = (get_character_current_feeling(character_name) or "").strip()
    status_effects = profile.get("status_effects", {}) or {}
    try:
        flags = get_state_flags(character_name)
    except Exception:
        flags = {}

    # Last thought time + this character's most recent (global) thought turns.
    last_thought_at = ""
    try:
        from app.core.agent_inbox import get_last_thought_at
        last_thought_at = get_last_thought_at(character_name) or ""
    except Exception:
        pass
    thoughts_recent: List[Dict[str, Any]] = []
    try:
        from app.core.agent_loop import get_agent_loop
        recent = (get_agent_loop().status() or {}).get("recent", []) or []
        # The ring-buffer entries are keyed agent/started_at/outcome
        # (agent_loop._record_turn) — not name/ts/action.
        thoughts_recent = [
            {"ts": r.get("started_at", ""),
             # Both clocks side by side: `ts` is SYSTEM time, `game_ts` the
             # canonical world stamp, `game_label` its rendered form.
             "game_ts": r.get("game_ts", ""),
             "game_label": game_label(r.get("game_ts", "")),
             "action": (r.get("outcome", "")
                        + (f" — {r['preview']}" if r.get("preview") else ""))}
            for r in recent if r.get("agent") == character_name
        ][-12:]
    except Exception:
        pass

    # Mood history (most recent first).
    mood_all = load_mood_history(character_name) or []
    mood_recent = list(reversed(mood_all))[:8]
    latest_mood = mood_recent[0] if mood_recent else None

    # Read the state history directly (no public reader) — most recent first.
    state_recent: List[Dict[str, Any]] = []
    last_warning: Optional[Dict[str, Any]] = None

    # id→name for location/room entries (otherwise the UI shows raw hex ids).
    def _resolve_state_value(stype: str, value: str) -> str:
        if not value:
            return value
        try:
            from app.models.world import get_location_name, list_locations, get_location_rooms
            if stype == "location":
                return get_location_name(value) or value
            if stype == "room":
                for _loc in list_locations():
                    for _rm in get_location_rooms(_loc):
                        if _rm.get("id") == value:
                            return _rm.get("name") or value
        except Exception:
            pass
        return value

    try:
        conn = get_connection()
        rows = conn.execute(
            "SELECT ts, state_json FROM state_history WHERE character_name=? "
            "ORDER BY ts DESC LIMIT 25", (character_name,),
        ).fetchall()
        for ts, state_json in rows:
            try:
                s = _json.loads(state_json or "{}")
            except Exception:
                continue
            _stype = s.get("type", "")
            ev = {"ts": s.get("timestamp", ts), "type": _stype,
                  "value": _resolve_state_value(_stype, s.get("value", "")),
                  "metadata": s.get("metadata", {})}
            state_recent.append(ev)
            if last_warning is None and ev["type"] in ("access_denied", "forced_action"):
                last_warning = ev
    except Exception:
        pass

    # Active block rules for this character (character empty/"all" = applies
    # to everyone) + the active force rule.
    block_rules: List[Dict[str, Any]] = []
    force_rule: Optional[Dict[str, Any]] = None
    try:
        from app.models.rules import load_rules, check_force_rules, rule_action
        from app.core.activity_engine import evaluate_condition
        for r in (load_rules() or []):
            if (r.get("type") or "") != "block":
                continue
            who = (r.get("character") or "").strip().lower()
            if who and who not in ("all", "*", "any", character_name.lower()):
                continue
            target = r.get("target", {}) or {}
            cond = (r.get("condition") or "").strip()
            # Evaluate the condition against the character + the TARGET of the
            # rule so the Mind panel shows whether the rule applies NOW. Block
            # semantics (see rules.check_access): condition true → blocked; a
            # rule WITHOUT a condition does not block in the location/room scope.
            t_loc, t_room = "", ""
            if isinstance(target, dict):
                t_loc = (target.get("location_id") or target.get("location") or "").strip()
                _rooms = target.get("room_ids") or target.get("rooms") or []
                if isinstance(_rooms, list) and _rooms:
                    t_room = _rooms[0]
            cond_met = False
            if cond:
                try:
                    cond_met, _ = evaluate_condition(cond, character_name, t_loc, t_room)
                except Exception:
                    cond_met = False
            block_rules.append({
                "id": r.get("id", ""), "name": r.get("name", ""),
                "action": rule_action(r), "target": target,
                "message": r.get("message", ""), "event_id": r.get("event_id", ""),
                "condition": cond,
                "condition_met": bool(cond_met),
                "blocking": bool(cond and cond_met),
            })
        force_rule = check_force_rules(character_name)
    except Exception:
        pass

    # "Why" — human-readable reasoning building blocks, most important first.
    reasons: List[str] = []
    if feeling:
        if latest_mood and (latest_mood.get("source") or "").strip():
            reasons.append(f"Feeling “{feeling}” (last set via {latest_mood['source']})")
        else:
            reasons.append(f"Feeling “{feeling}”")
    if force_rule:
        reasons.append(
            f"Forced by rule “{force_rule.get('rule_name', force_rule.get('rule_id',''))}”"
            + (f" → {force_rule.get('go_to')}" if force_rule.get("go_to") else ""))
    for br in block_rules:
        if (br.get("action") or "") == "leave":
            reasons.append(f"Must leave (rule “{br.get('name') or br.get('id')}”)"
                           + (f": {br['message']}" if br.get("message") else ""))
    if last_warning:
        kind = "Blocked" if last_warning["type"] == "access_denied" else "Forced action"
        reasons.append(f"{kind}: {last_warning.get('value','')}".strip())
    # Report conspicuous stat extremes generically (no hardcoded stat names).
    for k, v in status_effects.items():
        try:
            iv = int(v)
        except (TypeError, ValueError):
            continue
        if iv <= 20:
            reasons.append(f"Low {k}: {iv}")
        elif iv >= 80:
            reasons.append(f"High {k}: {iv}")

    # Active prompt_filter effects (exactly the effects_block modifiers that go
    # into the system prompt) + the raw active_conditions (with cooldown), so
    # Mind stays consistent with the prompt.
    active_effects: List[str] = []
    try:
        from app.core.prompt_filters import active_modifiers
        active_effects = active_modifiers(character_name, profile.get("current_location") or "")
    except Exception as _ae:
        logger.debug("active_modifiers fuer %s fehlgeschlagen: %s", character_name, _ae)
    active_conditions = profile.get("active_conditions", []) or []

    return {
        "character": character_name,
        "current_feeling": feeling,
        "state_flags": flags,
        "status_effects": status_effects,
        "active_effects": active_effects,
        "active_conditions": active_conditions,
        "last_thought_at": last_thought_at,
        "last_warning": last_warning,
        "reasons": reasons,
        "mood_recent": mood_recent,
        "state_recent": state_recent[:20],
        "thoughts_recent": list(reversed(thoughts_recent)),
        "block_rules": block_rules,
        "force_rule": force_rule,
    }


def build_memory_locations(character_name: str) -> Dict[str, Any]:
    """Tab "Known places": map with all world locations + known/current/visit counts.

    Delivers both all world locations (for layout context) and the subset
    the character knows according to `known_locations`. The frontend decides
    whether it shows only the known ones or everything.
    """
    from app.models.character import get_character_profile, get_known_locations
    from app.models.world import list_locations
    from app.core.db import get_connection

    profile = get_character_profile(character_name)
    current_id = profile.get("current_location") or ""
    known_ids = get_known_locations(character_name)
    known_set = set(known_ids)

    # Visit counts from state_history (ring buffer ~200 entries)
    conn = get_connection()
    visits: Dict[str, Dict[str, Any]] = {}
    for loc_id, n, last_ts in conn.execute(
        "SELECT json_extract(state_json,'$.value') AS loc_id, COUNT(*) AS n, "
        "MAX(ts) AS last_ts FROM state_history WHERE character_name=? "
        "AND json_extract(state_json,'$.type')='location' GROUP BY loc_id",
        (character_name,),
    ).fetchall():
        if loc_id:
            visits[loc_id] = {"count": n, "last": last_ts}

    items: List[Dict[str, Any]] = []
    for loc in list_locations() or []:
        lid = loc.get("id", "")
        if not lid:
            continue
        is_known = lid in known_set
        v = visits.get(lid, {})
        items.append({
            "id": lid,
            "name": loc.get("name", ""),
            "pos_x": loc.get("pos_x"),
            "pos_z": loc.get("pos_z"),
            "danger_level": loc.get("danger_level"),
            "is_known": is_known,
            "is_current": (lid == current_id),
            "visit_count": v.get("count", 0),
            "last_visit": v.get("last"),
        })
    return {
        "character": character_name,
        "current_location_id": current_id,
        "items": items,
    }


def build_memory_list(character_name: str,
                      limit: int = 50,
                      offset: int = 0,
                      tier: str = "",
                      min_importance: int = 0,
                      q: str = "",
                      related: str = "",
                      source: str = "",
                      sort: str = "recent",
                      include_completed: bool = False) -> Dict[str, Any]:
    """Tab "Memories": filtered, paginated memory list + facets.

    Sort: 'recent' (default) | 'importance' | 'access' | 'score'
    """
    from app.models.memory import load_memories
    from collections import Counter

    all_mem = load_memories(character_name)
    total_unfiltered = len(all_mem)

    # --- Facets from the unfiltered stock (for toolbar counts) ---
    tier_counts = Counter(m.get("memory_type", "semantic") for m in all_mem)
    src_counts: Counter = Counter()
    rel_counts: Counter = Counter()
    for m in all_mem:
        # Source: derived from meta — the agent loop writes 'thought'/'intent',
        # the extraction path leaves it empty.
        src = "thought" if "thought" in (m.get("tags") or []) else (
            "intent" if "intent" in (m.get("tags") or []) else "extraction"
        )
        # If stored explicitly (newer code): use meta.source
        # via load_memories it sits flat in the entry dict
        if m.get("source"):
            src = m["source"]
        src_counts[src] += 1
        rc = (m.get("related_character") or "").strip()
        if rc:
            rel_counts[rc] += 1

    # --- Filter ---
    items = all_mem
    if not include_completed:
        items = [m for m in items if "completed" not in (m.get("tags") or [])]
    if tier:
        items = [m for m in items if m.get("memory_type") == tier]
    if min_importance > 0:
        items = [m for m in items if m.get("importance", 3) >= min_importance]
    if related:
        items = [m for m in items if (m.get("related_character") or "") == related]
    if source:
        def _src(m):
            if m.get("source"): return m["source"]
            tags = m.get("tags") or []
            if "thought" in tags: return "thought"
            if "intent" in tags: return "intent"
            return "extraction"
        items = [m for m in items if _src(m) == source]
    if q:
        ql = q.lower()
        items = [m for m in items
                 if ql in (m.get("content") or "").lower()
                 or any(ql in (t or "").lower() for t in (m.get("tags") or []))]

    total = len(items)

    # --- Sort ---
    if sort == "importance":
        items.sort(key=lambda m: (m.get("importance", 3), m.get("timestamp", "")), reverse=True)
    elif sort == "access":
        items.sort(key=lambda m: (m.get("access_count", 0), m.get("timestamp", "")), reverse=True)
    elif sort == "score":
        scored = [(_score_memory_no_mutate(m), m) for m in items]
        scored.sort(key=lambda x: x[0], reverse=True)
        items = [m for _, m in scored]
    else:  # recent
        items.sort(key=lambda m: m.get("timestamp", ""), reverse=True)

    # --- Paginate ---
    page = items[offset:offset + max(1, min(200, limit))]

    return {
        "character": character_name,
        "total": total,
        "total_unfiltered": total_unfiltered,
        "limit": limit,
        "offset": offset,
        "items": page,
        "facets": {
            "tiers": dict(tier_counts),
            "sources": dict(src_counts),
            "related_characters": [
                {"name": n, "count": c}
                for n, c in rel_counts.most_common()
            ],
        },
    }


def build_memory_relationships(character_name: str,
                               history_limit: int = 10,
                               lang: str = "en") -> Dict[str, Any]:
    """Tab "Relationships": sentiment, strength, tension + last N events.

    `memories_count` = how many memories have this partner set as
    related_character — a click in the frontend filters tab 2.

    "Last met" is WORLD time: `last_interaction_game` is the canonical game
    stamp and `last_interaction_label` the label the server renders for it —
    the client never formats a game stamp itself. The system stamp is not in
    the payload; nothing here sorts or filters by it.
    """
    from app.models.relationship import get_character_relationships
    from app.models.memory import load_memories
    from collections import Counter

    rels = get_character_relationships(character_name)
    mem = load_memories(character_name)
    rel_count_by_partner: Counter = Counter(
        (m.get("related_character") or "").strip()
        for m in mem if (m.get("related_character") or "").strip()
    )

    # Ghost filter: relationships whose partner no longer exists in the
    # world (character deleted) stay in the DB but must not show in the
    # Mind panel.
    try:
        from app.models.character import list_available_characters
        existing = set(list_available_characters())
    except Exception:
        existing = set()

    items = []
    for r in rels:
        # Partner = the other side. _row_to_rel fills character_a/b with
        # from_char/to_char (DB order); we want the non-self name.
        a = r.get("character_a") or ""
        b = r.get("character_b") or ""
        partner = b if a == character_name else a
        if existing and partner not in existing:
            continue
        # Flip the sentiment to the calling character's point of view if
        # needed: a_to_b is the sentiment from a towards b.
        if a == character_name:
            self_sent = r.get("sentiment_a_to_b", 0.0)
            other_sent = r.get("sentiment_b_to_a", 0.0)
        else:
            self_sent = r.get("sentiment_b_to_a", 0.0)
            other_sent = r.get("sentiment_a_to_b", 0.0)
        history = r.get("history") or []
        # Most recent N events
        recent = history[-history_limit:][::-1] if history else []
        items.append({
            "partner": partner,
            "type": r.get("type", "neutral"),
            "strength": r.get("strength", 10),
            "sentiment_self_to_other": round(self_sent, 3),
            "sentiment_other_to_self": round(other_sent, 3),
            "romantic_tension": round(r.get("romantic_tension", 0.0), 3),
            "interaction_count": r.get("interaction_count", 0),
            "last_interaction_game": r.get("last_interaction_game", ""),
            "last_interaction_label": game_label(
                r.get("last_interaction_game", ""), lang),
            "memories_count": rel_count_by_partner.get(partner, 0),
            "history_recent": recent,
        })
    # Sort: most interactions first
    items.sort(key=lambda x: x["interaction_count"], reverse=True)
    return {"character": character_name, "items": items}


# ---------------------------------------------------------------------------
# Form of address per pair (world authoring — admin only)
# ---------------------------------------------------------------------------

def _known_character_or_404(name: str) -> str:
    """Return *name* if it is an existing character, else raise 404."""
    from app.models.character import list_available_characters
    if name not in list_available_characters():
        raise HTTPException(status_code=404,
                            detail=f"Character '{name}' not found")
    return name


def build_relationship_addresses(character_name: str) -> Dict[str, Any]:
    """Every known pair of *character_name* with both address directions.

    ``outgoing`` = how *character_name* addresses the other one, ``incoming``
    = how the other one addresses *character_name*. Pairs whose other side no
    longer exists in the world are skipped (the rows stay in the DB and come
    back with a re-import, exactly like the Mind panel does it).
    """
    from app.models.character import list_available_characters
    from app.models.relationship import get_address, get_character_relationships

    _known_character_or_404(character_name)
    existing = set(list_available_characters())
    items: List[Dict[str, Any]] = []
    for r in get_character_relationships(character_name):
        a = r.get("character_a") or ""
        b = r.get("character_b") or ""
        other = b if a.lower() == character_name.lower() else a
        if not other or other == character_name or other not in existing:
            continue
        items.append({
            "other": other,
            "outgoing": get_address(character_name, other),
            "incoming": get_address(other, character_name),
            "type": r.get("type", "neutral"),
            "strength": r.get("strength", 10),
        })
    items.sort(key=lambda x: x["other"].lower())
    return {"character": character_name, "items": items}


def set_relationship_address(character_name: str, other: str, *,
                             outgoing: Optional[str] = None,
                             incoming: Optional[str] = None) -> Dict[str, Any]:
    """Write one or both address directions of the pair (character, other).

    Creates the pair when it does not exist yet — that is how the admin panel
    adds a new one. ``None`` leaves a direction untouched, an empty string
    clears it.
    """
    from app.models.relationship import (AddressTextError, get_address,
                                         set_address)

    _known_character_or_404(character_name)
    _known_character_or_404(other)
    if other == character_name:
        raise HTTPException(status_code=400,
                            detail="a character has no form of address for itself")
    if outgoing is None and incoming is None:
        raise HTTPException(status_code=400,
                            detail="outgoing or incoming is required")
    try:
        if outgoing is not None:
            set_address(character_name, other, outgoing)
        if incoming is not None:
            set_address(other, character_name, incoming)
    except AddressTextError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {
        "success": True,
        "character": character_name,
        "other": other,
        "outgoing": get_address(character_name, other),
        "incoming": get_address(other, character_name),
    }


def _evolution_diff(prev: Dict[str, Any], curr: Dict[str, Any]) -> Dict[str, Any]:
    """Line-based diff (sentence-granular) over beliefs/lessons/goals.

    Splits each field at sentence boundaries (`. `, `! `, `? `) and returns
    per field {removed: [str,...], added: [str,...]}.
    """
    import re as _re

    def _split(text: str) -> List[str]:
        if not text: return []
        # Split at sentence boundaries, but keep non-empty pieces.
        parts = _re.split(r"(?<=[\.!?])\s+", text.strip())
        return [p.strip() for p in parts if p.strip()]

    out = {}
    for field in ("beliefs", "lessons", "goals"):
        a = set(_split(prev.get(field, "")))
        b = set(_split(curr.get(field, "")))
        out[field] = {
            "removed": sorted(list(a - b)),
            "added": sorted(list(b - a)),
        }
    return out


def _day_key_label(day_key: str, lang: str = "en") -> str:
    """Readable world date of a game day key ("" when it is not one)."""
    from app.core.game_time import GameTime
    try:
        return GameTime.parse(f"{day_key}T00:00:00").date_label(lang)
    except (ValueError, TypeError):
        return ""


def _week_key_label(week_key: str, lang: str = "en") -> str:
    """Readable label of a game week key ("" when it is not one)."""
    from app.core.memory_service import _week_start
    start = _week_start(week_key)
    return start.date_label(lang) if start is not None else ""


def build_memory_history(character_name: str,
                         kind: str = "daily",
                         limit: int = 60,
                         offset: int = 0,
                         lang: str = "en") -> Dict[str, Any]:
    """Tab "History": daily | weekly | monthly | history | diary | evolution.

    Default: `daily` (last 60 entries across all partners).

    Every date key here is a GAME calendar key (``Y0002-D109`` /
    ``Y0002-W016`` / ``Y0002-S01``); the server ships the readable ``label``
    alongside it so the client never has to know the world calendar.
    """
    from app.core.db import get_connection
    import json as _json

    conn = get_connection()

    if kind == "daily":
        rows = conn.execute("""
            SELECT date_key, partner, content
            FROM summaries
            WHERE character_name=? AND kind='daily'
            ORDER BY date_key DESC, partner ASC
            LIMIT ? OFFSET ?
        """, (character_name, limit, offset)).fetchall()
        items = [{"date": r[0], "label": _day_key_label(r[0], lang),
                  "partner": r[1] or "", "content": r[2]} for r in rows]
        total = conn.execute(
            "SELECT COUNT(*) FROM summaries WHERE character_name=? AND kind='daily'",
            (character_name,),
        ).fetchone()[0]
        return {"character": character_name, "kind": kind,
                "total": total, "limit": limit, "offset": offset, "items": items}

    if kind == "weekly":
        from app.core.memory_service import load_weekly_summaries
        weekly = load_weekly_summaries(character_name)
        items = [{"week": k, "label": _week_key_label(k, lang), "content": v}
                 for k, v in sorted(weekly.items(), reverse=True)]
        return {"character": character_name, "kind": kind, "items": items}

    if kind == "monthly":
        from app.core.memory_service import load_monthly_summaries
        monthly = load_monthly_summaries(character_name)
        from app.core.memory_service import season_label
        items = [{"month": k, "label": season_label(k, lang), "content": v}
                 for k, v in sorted(monthly.items(), reverse=True)]
        return {"character": character_name, "kind": kind, "items": items}

    if kind == "history":
        from app.utils.history_manager import get_cached_summary
        return {"character": character_name, "kind": kind,
                "content": get_cached_summary(character_name) or ""}

    if kind == "diary":
        rows = conn.execute("""
            SELECT id, ts, game_ts, content, tags
            FROM diary_entries
            WHERE character_name=?
            ORDER BY game_ts DESC, ts DESC
            LIMIT ? OFFSET ?
        """, (character_name, limit, offset)).fetchall()
        items = []
        for r in rows:
            try: tags = _json.loads(r[4] or "[]")
            except Exception: tags = []
            day_key = (r[2] or "")[:10]
            items.append({"id": r[0], "ts": r[1], "game_ts": r[2] or "",
                          "date": day_key,
                          "label": _day_key_label(day_key, lang),
                          "content": r[3], "tags": tags})
        total = conn.execute(
            "SELECT COUNT(*) FROM diary_entries WHERE character_name=?",
            (character_name,),
        ).fetchone()[0]
        return {"character": character_name, "kind": kind,
                "total": total, "limit": limit, "offset": offset, "items": items}

    if kind == "evolution":
        rows = conn.execute("""
            SELECT ts, new_value, reason
            FROM evolution_history
            WHERE character_name=? AND field='snapshot'
            ORDER BY ts ASC
        """, (character_name,)).fetchall()
        snaps = []
        for ts, new_value, reason in rows:
            try: payload = _json.loads(new_value or "{}")
            except Exception: payload = {}
            snaps.append({
                "ts": ts,
                "trigger": payload.get("trigger") or reason or "",
                "beliefs": payload.get("beliefs", ""),
                "lessons": payload.get("lessons", ""),
                "goals": payload.get("goals", ""),
            })
        # Diff each against the previous snapshot
        items = []
        prev = None
        for s in snaps:
            diff = _evolution_diff(prev, s) if prev else None
            items.append({**s, "diff": diff})
            prev = s
        # Most recent on top
        items.reverse()
        return {"character": character_name, "kind": kind, "items": items}

    raise HTTPException(status_code=400, detail=f"unknown kind: {kind}")


# ===========================================================================
# 5a Runde B — simple-domain + soul/status/template/create logic cores
# Moved 1:1 out of app/routes/characters.py; routes remain thin adapters.
# ===========================================================================

def build_available_models() -> Dict[str, Any]:
    """List available models from all configured providers.

    Returns model lists grouped by provider, plus current task defaults.
    Used by the frontend for per-character model selection dropdowns.
    """
    from app.core.provider_manager import get_provider_manager
    from app.core.model_capabilities import (get_model_capabilities,
                                             get_all_suitability)

    pm = get_provider_manager()
    providers = pm.list_all_models()
    suit_all = get_all_suitability()  # Key: "provider::model" (lowercased)

    # Attach capabilities to each model. Pre-fill the vision column: if nothing
    # is stored (None) and the name identifies a vision model, pre-fill with
    # True. (The name heuristic can only confirm vision, not rule it out
    # -> for non-vision names it stays unknown.) COPY the caps, otherwise the
    # cached _default/substring entry would be mutated.
    # The suitability test (HW-dependent) is merged EXACTLY per full
    # provider::model -> the same model on different hardware gets its own values.
    for provider_name, provider_data in providers.items():
        for model in provider_data.get("models", []):
            caps = dict(get_model_capabilities(model.get("name", "")))
            if caps.get("vision") is None and model.get("vision"):
                caps["vision"] = True
            sd = suit_all.get(f"{provider_name}::{model.get('name', '')}".lower())
            if sd:
                caps.update(sd)
            model["capabilities"] = caps

    return {
        "providers": providers,
        "task_defaults": {},
    }


def build_characters_at_location(location: str, room: str = "") -> Dict[str, Any]:
    """Returns all characters located at the given place.

    - `location`: ID or name of the location.
    - `room` (optional): when set, characters get a `same_room` flag (true
      when they are in exactly this room). No filtering happens -- the
      frontend can grey out who is in a different room of the same location.

    The roster is ``perception.addressable_at_location``, THE addressability
    rule -- everybody inside the location plus whoever stands within earshot
    of its map anchor out in the open. Somebody waiting in front of the gate
    belongs on the list of people one can speak to here; they carry
    ``same_room`` False and an empty ``room``, because they are in none.
    """
    from app.core.perception import addressable_at_location
    from app.models.world import resolve_location, get_room_by_id
    from app.models.character import get_character_current_room
    from app.models.character import (get_character_current_location,
                                      get_character_profile_image)
    loc = resolve_location(location)
    loc_id = loc.get("id", "") if loc else ""
    loc_name = loc.get("name", location) if loc else location

    # Resolve the avatar room to {id, name} -- char_room can historically be
    # either an ID or a name, so we match against both.
    room_norm = (room or "").strip()
    avatar_room_id = ""
    avatar_room_name = ""
    if room_norm and loc:
        _r = get_room_by_id(loc, room_norm)
        if _r:
            avatar_room_id = _r.get("id", "") or room_norm
            avatar_room_name = _r.get("name", "")
        else:
            for _r in (loc.get("rooms") or []):
                if _r.get("name") == room_norm:
                    avatar_room_id = _r.get("id", "")
                    avatar_room_name = room_norm
                    break
            else:
                avatar_room_name = room_norm
                avatar_room_id = room_norm

    result = []
    for name in addressable_at_location(loc_id or location):
        char_loc = get_character_current_location(name) or ""
        char_room = (get_character_current_room(name) or "").strip()
        if not char_loc:
            # Within earshot but inside no wall of this location: never in
            # "the" room, and its stored room (if any) belongs elsewhere.
            same_room = False
            char_room = ""
        elif room_norm and char_room:
            # Default same_room=True; only when the avatar is in a room AND
            # the character is explicitly in ANOTHER room does it count as
            # "elsewhere". A character without a room is present everywhere
            # in the location.
            same_room = char_room in (avatar_room_id, avatar_room_name)
        else:
            same_room = True
        profile_img = get_character_profile_image(name)
        result.append({
            "name": name,
            "profile_image": profile_img or "",
            "avatar_url": f"/characters/{name}/images/{profile_img}" if profile_img else "",
            "same_room": same_room,
            "room": char_room,
        })
    return {"characters": result, "location": loc_name, "location_id": loc_id, "room": room_norm}


def build_chatbots_list() -> Dict[str, Any]:
    """Lists all chatbots (characters without a location system).

    A chatbot is a character whose template has `locations_enabled: false` --
    it has no world position and is always addressable.
    """
    from app.models.character_template import is_feature_enabled
    from app.models.character import (list_available_characters,
                                      get_character_profile_image)
    all_chars = list_available_characters()
    result = []
    for name in all_chars:
        # No location system = chatbot
        if is_feature_enabled(name, "locations_enabled"):
            continue
        profile_img = get_character_profile_image(name)
        result.append({
            "name": name,
            "profile_image": profile_img or "",
            "avatar_url": f"/characters/{name}/images/{profile_img}" if profile_img else "",
        })
    return {"characters": result}


def build_character_notice(character_name: str) -> Dict[str, Any]:
    """Returns the persistent notices for the avatar header banner.

    - ``force_warning``: active force rule (rule_name + message + go_to +
      set_activity) OR ``None``. For the avatar the rule is NOT executed
      automatically.
    - ``critical_events``: unresolved events of the ``disruption``/``danger``
      categories at the current avatar location, newest first.
    """
    out: Dict[str, Any] = {"force_warning": None, "critical_events": []}
    try:
        from app.models.rules import check_force_rules, resolve_force_destination
        force = check_force_rules(character_name)
        if force:
            go_loc, go_room = resolve_force_destination(character_name,
                                                        force.get("go_to", "stay"))
            out["force_warning"] = {
                "rule_id": force.get("rule_id", ""),
                "rule_name": force.get("rule_name", ""),
                "message": force.get("message", ""),
                "go_to": force.get("go_to", "stay"),
                "go_to_location_id": go_loc,
                "go_to_room_id": go_room,
                "set_activity": force.get("set_activity", ""),
            }
    except Exception as e:
        logger.debug("notice: force_rules failed for %s: %s", character_name, e)

    try:
        from app.models.character import get_character_current_location
        from app.models.events import list_events
        loc_id = (get_character_current_location(character_name) or "").strip()
        if loc_id:
            for ev in list_events(location_id=loc_id) or []:
                cat = (ev.get("category") or "").lower()
                if cat not in ("disruption", "danger"):
                    continue
                if ev.get("resolved"):
                    continue
                out["critical_events"].append({
                    "id": ev.get("id", ""),
                    "category": cat,
                    "text": ev.get("text", ""),
                    "created_at": ev.get("created_at", ""),
                })
            out["critical_events"].sort(key=lambda e: e.get("created_at", ""), reverse=True)
    except Exception as e:
        logger.debug("notice: critical_events failed for %s: %s", character_name, e)

    return out


def build_profile_payload(character_name: str) -> Dict[str, Any]:
    """Returns the complete character profile."""
    from app.models.character import get_character_profile
    profile = get_character_profile(character_name)

    # Attach token-resolved variants of the appearance fields so the frontend
    # (e.g. profile-image generation) gets the finished text without parsing
    # tokens itself.
    try:
        from app.models.character_template import (
            get_template, resolve_profile_tokens)
        _tmpl_id = profile.get("template", "") or ""
        _tmpl = get_template(_tmpl_id) if _tmpl_id else None
        for _key in ("character_appearance", "face_appearance"):
            _raw = (profile.get(_key) or "").strip()
            if not _raw or "{" not in _raw:
                continue
            _resolved = resolve_profile_tokens(
                _raw, profile, template=_tmpl, target_key="character_appearance")
            if _resolved and _resolved != _raw:
                if not isinstance(profile, dict):
                    profile = dict(profile)
                profile[f"{_key}_resolved"] = _resolved
    except Exception:
        pass

    # Resolve the location name so the editor shows the name instead of the ID
    loc_id = profile.get("current_location", "")
    if loc_id:
        try:
            from app.models.world import get_location_name as _get_loc_name
            resolved = _get_loc_name(loc_id)
            if resolved:
                profile = dict(profile)
                profile["current_location"] = resolved
        except Exception:
            pass
    # Resolve the room name (room ID -> name)
    room_id = profile.get("current_room", "")
    if room_id and loc_id:
        try:
            from app.models.world import get_location, get_room_by_id
            loc_data = get_location(loc_id)
            if loc_data:
                room = get_room_by_id(loc_data, room_id)
                if room and room.get("name"):
                    if not isinstance(profile, dict):
                        profile = dict(profile)
                    profile["current_room"] = room["name"]
        except Exception:
            pass
    return {"character": character_name, "profile": profile}


def _lifetime_fields(profile: Dict[str, Any],
                     fields: Dict[str, Any]) -> Dict[str, Any]:
    """The profile keys a temporary NPC's lifetime edit really writes.

    Three modes, one stamp (plan-npc-leben-bugs § Lifetime):

    * ``permanent`` — no stamp at all (``""`` is what ``sweep_expired_npcs``
      reads as "never") plus ``npc_permanent``, the flag DERIVED from the mode
      that survives pooling and stops ``npc_pool.revive_from_pool`` from
      handing the NPC a new TTL. The mode is the decision, the flag follows
      it — readers ask ``npc_ops.is_permanent_npc``, which accepts either, so
      a sheet written before the flag existed is permanent all the same;
    * ``custom`` — ``lifetime_hours`` GAME hours from now;
    * ``default`` — the world's own TTL for this kind of NPC: the wanderer TTL
      for a wanderer, the slot TTL for everyone else.

    Only the mode is read from ``fields`` first and from the stored profile
    second, so a save that carries the HOURS alone still restamps a custom
    lifetime.

    THE MODE OUTLIVES A MISSING NUMBER. The config form saves ONE field per
    request, so picking "custom" always arrives without any hours — the mode is
    stored as picked and only the STAMP falls back to the default TTL until the
    hours arrive in the next save. Writing ``default`` back here instead would
    snap the dropdown shut, hide the hours field before it could be typed into,
    and make the hours-only save that follows read the wrong stored mode.
    """
    from app.core.npc_ops import expiry_stamp
    from app.core.npc_spawn import slot_ttl_hours, wanderer_ttl_hours

    mode = str(fields.get("lifetime", profile.get("lifetime"))
               or "default").strip().lower()
    if mode == "permanent":
        return {"lifetime": "permanent", "expires_at": "",
                "npc_permanent": True}
    if mode == "custom":
        try:
            hours = float(fields.get("lifetime_hours",
                                     profile.get("lifetime_hours")))
        except (TypeError, ValueError):
            hours = 0.0
        if hours > 0:
            return {"lifetime": "custom", "lifetime_hours": hours,
                    "expires_at": expiry_stamp(hours), "npc_permanent": False}
    ttl = (wanderer_ttl_hours() if profile.get("npc_wanderer")
           else slot_ttl_hours())
    return {"lifetime": "custom" if mode == "custom" else "default",
            "expires_at": expiry_stamp(ttl), "npc_permanent": False}


def build_active_conditions(character_name: str) -> Dict[str, Any]:
    """Returns active conditions with icon/label/remaining duration.

    Expired conditions are filtered out. Icons/labels come from the prompt
    filters (Game Admin -> Conditions).

    A condition's lifetime is a WORLD duration ("drunk for 3 hours" means three
    in-world hours), so ``started_at`` is a canonical GameTime and the
    remaining time is counted on the game clock.
    """
    from app.core.game_time import GameDuration, GameTime
    from app.core.timeutils import game_time
    from app.core.prompt_filters import load_filters
    from app.models.character import get_character_profile

    profile = get_character_profile(character_name)
    active = profile.get("active_conditions", []) or []

    # Index: condition_name (lowercased) -> {icon, label, image_modifier}.
    # The filter `id` is the canonical condition name (new model): when the
    # tag shows up in active_conditions, the filter triggers implicitly. We
    # build the lookup primarily via id; legacy filters with a
    # `condition:<name>` expression are additionally indexed as an alias so
    # old data still gets an icon.
    meta_by_name: Dict[str, Dict[str, str]] = {}
    for f in load_filters():
        meta = {
            "icon": f.get("icon", "") or "",
            "label": f.get("label", "") or "",
            "image_modifier": f.get("image_modifier", "") or "",
        }
        fid = (f.get("id") or "").strip().lower()
        if fid:
            meta_by_name.setdefault(fid, dict(meta, label=meta["label"] or fid))
        cond_str = (f.get("condition") or "").strip()
        if cond_str.lower().startswith("condition:"):
            name = cond_str[10:].strip().lower()
            if name:
                meta_by_name.setdefault(name, dict(meta, label=meta["label"] or name))

    now_game = game_time()
    result = []
    for cond in active:
        name = (cond.get("name") or "").strip()
        if not name:
            continue
        # Expired?
        duration_h = cond.get("duration_hours", 0) or 0
        remaining_h = None
        if duration_h:
            try:
                started = GameTime.parse(cond["started_at"])
                elapsed = now_game - started
                total = GameDuration.of(hours=duration_h)
                if elapsed > total:
                    continue
                remaining_h = round((total - elapsed).hours, 1)
            except (ValueError, KeyError, TypeError):
                pass
        meta = meta_by_name.get(name.lower(), {})
        result.append({
            "name": name,
            "label": meta.get("label") or name,
            "icon": meta.get("icon", ""),
            "remaining_hours": remaining_h,
            "source": cond.get("source", ""),
        })
    return {"character": character_name, "conditions": result}


def apply_profile_update(character_name: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Updates character profile fields (bulk update)."""
    from app.models.character import get_character_profile, save_character_profile
    user_id = data.get("user_id", "")
    fields = data.get("fields", {})
    if not fields:
        raise HTTPException(status_code=400, detail="fields fehlt")

    # Read AND write under the per-character profile lock (DATA-3): the bulk
    # update writes the whole profile_json blob back, so a stale read drops
    # every field a concurrent writer stored. Everything inside the span is a
    # cached world/template read — no LLM, no image, no HTTP.
    from app.core.keyed_lock import keyed_lock
    with keyed_lock("character_profile", character_name):
        profile = get_character_profile(character_name)

        # current_location: resolve the name back to an ID so the world map keeps
        # finding the character (GET returns the resolved name, POST gets it back).
        if "current_location" in fields:
            loc_val = fields["current_location"]
            if loc_val:
                from app.models.world import resolve_location, get_location_id
                loc_id = get_location_id(loc_val)
                if loc_id:
                    fields["current_location"] = loc_id
                else:
                    loc_obj = resolve_location(loc_val)
                    if loc_obj and loc_obj.get("id"):
                        fields["current_location"] = loc_obj["id"]

        # Filter out __custom__ sentinel values (UI placeholder for custom input)
        for k, v in list(fields.items()):
            if v == "__custom__":
                fields[k] = ""

        # Fields with source_file belong in MD files, NOT in the JSON profile.
        # If someone sends them here, ignore them -- the soul editor is
        # responsible (see /characters/{char}/soul/*).
        _sf_keys = _soul_field_keys(profile.get("template", ""))
        for k in list(fields.keys()):
            if k in _sf_keys:
                fields.pop(k, None)

        # LIFETIME is derived, never typed. `expires_at` is a canonical GAME stamp
        # and only the server owns that clock, so the temp-NPC form offers the
        # DECISION (`lifetime` + `lifetime_hours`) and the stamp is recomputed
        # here. Every other save leaves `expires_at` exactly as it was — otherwise
        # editing a briefing would quietly hand the NPC a fresh day.
        from app.models.character import is_temporary_npc
        if ("lifetime" in fields or "lifetime_hours" in fields) \
                and is_temporary_npc(character_name):
            fields.update(_lifetime_fields(profile, fields))

        profile.update(fields)
        stored = save_character_profile(character_name, profile)
    if not stored:
        # The admin form must not answer "saved" for a value that is gone
        # after the next reload.
        raise HTTPException(status_code=500, detail="profile not stored")
    return {"status": "success", "character": character_name,
            "updated_fields": list(fields.keys())}


def apply_config_update(character_name: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Updates character config fields (bulk update)."""
    from app.models.character import get_character_config, save_character_config
    user_id = data.get("user_id", "")
    fields = data.get("fields", {})
    if not fields:
        raise HTTPException(status_code=400, detail="fields fehlt")

    config = get_character_config(character_name)
    config.update(fields)
    save_character_config(character_name, config)

    # Immediate effect of the avatar_only_presence flag: on + uncontrolled ->
    # disappear; off -> reappear (idempotent).
    if "avatar_only_presence" in fields:
        try:
            from app.models.account import is_player_controlled
            from app.models.character import enter_offmap_sleep, appear_in_world
            on = str(fields.get("avatar_only_presence")).strip().lower() == "true"
            if on:
                if not is_player_controlled(character_name):
                    enter_offmap_sleep(character_name)
            else:
                appear_in_world(character_name)
        except Exception:
            pass

    return {"status": "success", "character": character_name, "updated_fields": list(fields.keys())}


def build_prompt_preview(character_name: str) -> Dict[str, str]:
    """Effective prompt preview for the admin (Appearance/Wardrobe UI):
    how the person description, face prompt and outfit line actually
    render right now — including body-slot fragments and how the worn
    outfit (coverage) suppresses or exposes them."""
    from app.models.character import get_character_profile, get_character_appearance
    from app.models.character_template import get_template
    from app.core.body_slots import appearance_suffix
    from app.core.outfit_renderer import render_outfit
    profile = get_character_profile(character_name) or {}
    tmpl = get_template(profile.get("template", "")) if profile.get("template") else None
    # SAME production functions as the renderers — no re-implementation
    # (preview principle): the scene line IS scene_render's text-person
    # description; face IS the profile-image prompt resolver.
    from app.core.scene_render import _appearance_text
    return {
        "scene": _appearance_text(character_name),
        "face": _resolve_face_prompt(profile, character_name, tmpl),
        "outfit": (render_outfit(character_name=character_name).get("full", "") or ""),
    }


def build_body_slots(character_name: str) -> Dict[str, Any]:
    """Body-slot editor payload (species packages, plan-body-slots.md):
    applicable slots with attribute declarations + current values, plus the
    silhouette declaration. Generic — everything comes from the packages."""
    from app.core.body_slots import (silhouette_for_character,
                                     slot_values, slots_for_character)
    from app.models.character import get_character_profile
    profile = get_character_profile(character_name) or {}
    values = slot_values(character_name)
    equipped = dict(profile.get("equipped_pieces") or {})
    slots = []
    for spec in slots_for_character(character_name):
        exposed = (not spec.covered_by
                   or not any(equipped.get(s) for s in spec.covered_by))
        attrs = []
        for key, decl in spec.attributes.items():
            attr = {
                "key": key,
                "type": decl.get("type", "select"),
                "options": list(decl.get("options") or []),
                "allow_custom": bool(decl.get("allow_custom")),
                "label": decl.get("label", key.replace("_", " ").title()),
                "value": (values.get(spec.id) or {}).get(key, ""),
            }
            if attr["type"] == "lora_select":
                try:
                    attr["strength"] = float(
                        (values.get(spec.id) or {}).get(f"{key}_strength") or 1.0)
                except (TypeError, ValueError):
                    attr["strength"] = 1.0
            attrs.append(attr)
        entry = {
            "id": spec.id,
            "package_id": spec.package_id,
            "covered_by": list(spec.covered_by),
            "exposed": exposed,
            "attributes": attrs,
        }
        exposed_tpl = spec.prompt.get("exposed", "")
        if exposed_tpl:
            from app.core.body_slots import _format_if_complete
            vals_map = {k: str((values.get(spec.id) or {}).get(k, "") or "")
                        for k in spec.attributes}
            entry["exposed_prompt"] = str(
                (values.get(spec.id) or {}).get("exposed_prompt", "") or "")
            entry["exposed_always"] = bool(
                (values.get(spec.id) or {}).get("exposed_always"))
            # Grey placeholder: the resolved manifest default (raw template
            # when values are still missing) — never materialized as value.
            entry["exposed_default"] = (_format_if_complete(exposed_tpl, vals_map)
                                        or exposed_tpl)
        slots.append(entry)
    sil = silhouette_for_character(character_name)
    # Clothing topology of the species — consumers like the image
    # slot-overrides editor render per-slot UI from this instead of a
    # hardcoded human list.
    from app.core.body_slots import declared_piece_slots
    _declared = declared_piece_slots(character_name)
    if _declared:
        piece_ids, piece_labels = _declared
    else:
        from app.models.inventory import VALID_PIECE_SLOTS
        piece_ids, piece_labels = tuple(VALID_PIECE_SLOTS), {}
    return {
        "slots": slots,
        "piece_slots": [{"id": pid, "label": piece_labels.get(pid, pid.replace("_", " ").title())}
                        for pid in piece_ids],
        "silhouette_url": f"/characters/{character_name}/silhouette" if sil else "",
    }


def apply_body_slot_values(character_name: str,
                           slot_id: str, values: Dict[str, Any]) -> Dict[str, Any]:
    """Editor setter: store attribute values for one declared slot.
    Unknown slots/attributes are rejected (declarations are the schema)."""
    from app.core.body_slots import set_slot_value, slots_for_character
    spec = next((s for s in slots_for_character(character_name)
                 if s.id == slot_id), None)
    if spec is None:
        raise HTTPException(status_code=404,
                            detail=f"Unknown body slot '{slot_id}'")
    # lora_select attributes implicitly carry a companion '<key>_strength'
    # value (generic rule bound to the type — no manifest boilerplate).
    allowed = set(spec.attributes)
    for k, decl in spec.attributes.items():
        if str(decl.get("type", "")) == "lora_select":
            allowed.add(f"{k}_strength")
    if spec.prompt.get("exposed"):
        # Reserved: per-character override of the exposed prompt fragment +
        # the 'emit even without attribute values' flag.
        allowed.add("exposed_prompt")
        allowed.add("exposed_always")
    unknown = [k for k in values if k not in allowed]
    if unknown:
        raise HTTPException(status_code=400,
                            detail=f"Unknown attribute(s): {', '.join(unknown)}")
    for key, value in values.items():
        if key == "exposed_always":
            # Boolean flag from the editor arrives as "true"/"false" —
            # a stored "false" STRING would stay truthy. Store True or
            # remove the key entirely (empty value deletes).
            value = True if str(value).strip().lower() in ("true", "1") else ""
        set_slot_value(character_name, slot_id, key, value)
    return {"status": "success", "slot": slot_id}


def _package_active_for(character_name: str, pkg) -> bool:
    """Whether a package counts as ACTIVE on a character (F9 dependencies).

    Verb packages: any of their skills is enabled for the character
    (mirrors skill_manager._get_agent_skills semantics — missing per-char
    config counts as enabled unless the skill is ALWAYS_LOAD).
    Content-only packages: one of their template fragments applies to the
    character's template.
    """
    from app.models.character import (get_character_profile,
                                      get_character_skill_config)
    if pkg.skills:
        for s in pkg.skills:
            cfg = get_character_skill_config(character_name, s.skill_id) or {}
            if "enabled" in cfg:
                if bool(cfg["enabled"]):
                    return True
            elif not s.always_load:
                return True
        return False
    profile = get_character_profile(character_name) or {}
    tmpl_name = (profile.get("template") or "").strip()
    if not tmpl_name:
        return False
    from app.models.character_template import fragment_applies, get_template
    tmpl = get_template(tmpl_name) or {}
    return any(fragment_applies(f, tmpl_name, tmpl)
               for f in pkg.character_fragments)


def skill_dependency_block(character_name: str, skill_id: str) -> str:
    """Why this skill cannot be enabled for the character (empty = allowed).

    Evaluates the providing package's requires/conflicts declarations (F9)
    against the character's active packages — including reverse conflicts
    (an active package declaring a conflict with this one). Built-in skills
    (no package) are never blocked.
    """
    try:
        from app.plugins import registry as _reg
        pkg = _reg.package_of_skill(skill_id)
        if pkg is None:
            return ""
        reasons = []
        for req in pkg.requires:
            rp = _reg.get_package(req)
            if rp is None or not _package_active_for(character_name, rp):
                reasons.append(f"requires package '{req}'")
        for con in pkg.conflicts:
            cp = _reg.get_package(con)
            if cp is not None and _package_active_for(character_name, cp):
                reasons.append(f"conflicts with active package '{con}'")
        for other in _reg.packages():
            if (other.id != pkg.id and pkg.id in other.conflicts
                    and _package_active_for(character_name, other)):
                reasons.append(f"active package '{other.id}' conflicts with it")
        return "; ".join(reasons)
    except Exception as e:
        logger.debug("dependency check failed for %s/%s: %s",
                     character_name, skill_id, e)
        return ""


def _media_backend_options(media: str) -> List[Dict[str, str]]:
    """Enabled AND currently available backends of one media kind as
    ``{value, label}``, cheapest first.

    Reads the in-memory pool only — no ``check_availability()`` re-probe: this
    runs on every load of the Skills tab, and probing a dead endpoint there
    would stall the page for its timeout.
    """
    try:
        from app.imagegen.service import get_image_service
        svc = get_image_service()
    except Exception as e:
        logger.debug("backend options (%s): %s", media, e)
        return []
    if not getattr(svc, "enabled", False):
        return []
    picked = [b for b in svc.backends
              if getattr(b, "MEDIA_TYPE", "image") == media
              and getattr(b, "instance_enabled", False) and b.available]
    picked.sort(key=lambda b: (b.cost if b.cost is not None else 999999, b.name))
    return [{"value": b.name, "label": b.name} for b in picked]


def skill_option_source(source: str) -> List[Dict[str, str]]:
    """Options for a skill config field of type ``choice``.

    A field declares ``"options_source": "<name>"``; this is the ONE place
    that maps such a name to its option list, so no skill id is named in the
    UI or the route. Every source reads in-memory state only.

    Known sources:
      ``image_backends`` — backends with ``MEDIA_TYPE == "image"``
      ``video_backends`` — backends with ``MEDIA_TYPE == "video"``

    An unknown name yields an empty list: the field then still renders (empty
    entry = world default, plus a stored value marked unavailable).
    """
    if source == "image_backends":
        return _media_backend_options("image")
    if source == "video_backends":
        return _media_backend_options("video")
    logger.warning("Unknown skill config option source '%s'", source)
    return []


def build_available_skills(character_name: str) -> Dict[str, Any]:
    """Returns all globally loaded skills with per-character enabled state and config fields."""
    from app.core.dependencies import get_skill_manager
    from app.models.character import get_character_skill_config
    skill_manager = get_skill_manager()
    try:
        from app.plugins.registry import package_of_skill
    except Exception:
        package_of_skill = None
    skills = []
    # Option lists for "choice" fields, keyed by their options_source name.
    # Filled lazily: a source is computed at most ONCE per request, and only
    # when a loaded skill actually declares it.
    option_sources: Dict[str, List[Dict[str, str]]] = {}
    for skill in skill_manager.skills:
        skill_id = skill.SKILL_ID
        if not skill_id:
            continue
        config = get_character_skill_config(character_name, skill_id)
        # Default: ALWAYS_LOAD skills start disabled, others enabled
        default_enabled = not getattr(skill, 'ALWAYS_LOAD', False)
        enabled = default_enabled
        if config and "enabled" in config:
            enabled = bool(config["enabled"])

        # Config fields with defaults, types, and current values
        config_fields = skill.get_config_fields()
        if config_fields:
            for field_name, field_info in config_fields.items():
                if config and field_name in config:
                    field_info["value"] = config[field_name]
                else:
                    field_info["value"] = field_info["default"]
                # "choice" field: resolve its option list and flag a stored
                # value the source does not offer any more (a backend that was
                # removed or is offline). It stays selectable and marked —
                # same spirit as the LoRA library's "(missing)" entries.
                src = field_info.get("options_source")
                if src:
                    if src not in option_sources:
                        option_sources[src] = skill_option_source(src)
                    val = str(field_info.get("value") or "").strip()
                    field_info["value_unavailable"] = bool(val) and val not in {
                        o["value"] for o in option_sources[src]}

        _cap_pkg = None
        if package_of_skill is not None:
            try:
                _p = package_of_skill(skill_id)
                if _p is not None and _p.capability_label:
                    _cap_pkg = _p
            except Exception:
                pass
        skills.append({
            "skill_id": skill_id,
            "name": skill.name,
            "description": skill.description,
            "enabled": enabled,
            # Capability group (plugin.yaml capability_label): the UI
            # renders ONE toggle for all verbs of the package — e.g.
            # 'Party' for invite/join/leave.
            "capability_id": _cap_pkg.id if _cap_pkg else "",
            "capability_label": _cap_pkg.capability_label if _cap_pkg else "",
            # Human-facing group text — the per-verb descriptions are
            # LLM tool prose ("call FollowDressCode") and stay LLM-only.
            "capability_description": _cap_pkg.capability_description if _cap_pkg else "",
            # F9 dependencies: non-empty = enabling is blocked (UI disables
            # the toggle and shows why); the PUT route enforces it too.
            "blocked_reason": skill_dependency_block(character_name, skill_id),
            "config_fields": config_fields if config_fields else None,
        })

    # Location list for skill config fields of type "locations"
    from app.models.world import list_locations
    all_locations = [{"id": loc.get("id", ""), "name": loc.get("name", "")}
                     for loc in list_locations() if loc.get("id")]

    return {"skills": skills, "locations": all_locations,
            # {source_name: [{value, label}, ...]} for the "choice" fields
            # above — one list per source, not per field.
            "option_sources": option_sources}


def _clean_lora_list(raw: Any) -> List[Dict[str, Any]]:
    """Normalizes a submitted LoRA list to [{name, strength}] entries.
    Drops non-dicts, empty names and the 'None' placeholder; a non-numeric
    strength falls back to 1.0."""
    if not isinstance(raw, list):
        return []
    clean: List[Dict[str, Any]] = []
    for l in raw:
        if not isinstance(l, dict):
            continue
        nm = (l.get("name") or "").strip()
        if not nm or nm == "None":
            continue
        try:
            st = float(l.get("strength", 1.0))
        except Exception:
            st = 1.0
        clean.append({"name": nm, "strength": st})
    return clean


def apply_outfit_imagegen(character_name: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """Saves workflow/model/LoRA override for the outfit image service.
    All fields empty deletes the override completely."""
    from app.models.character import get_character_profile, save_character_profile
    workflow = (body.get("workflow") or "").strip()
    # Separate backend glob for the T-pose reference renders (the image->3D
    # input), e.g. a pose-controlled alias. Empty = the normal match above.
    tpose_workflow = (body.get("tpose_workflow") or "").strip()
    model = (body.get("model") or "").strip()
    clean_loras = _clean_lora_list(body.get("loras"))
    # Own LoRA list for the T-pose reference renders: it REPLACES the list
    # above for those renders (different backend, different LoRA ecosystem —
    # no merge). Empty = the normal LoRAs apply.
    clean_tpose_loras = _clean_lora_list(body.get("tpose_loras"))
    # Read AND write under the per-character profile lock (DATA-3): the save
    # rewrites the whole profile_json blob. No image is generated here — this
    # only stores the workflow/model/LoRA override the service reads later —
    # so the span is a leaf and holds no lock across a backend call.
    from app.core.keyed_lock import keyed_lock
    with keyed_lock("character_profile", character_name):
        prof = get_character_profile(character_name) or {}
        # Always write (even empty) -- otherwise a clear does not persist:
        # outfit_imagegen lives in config_json and is only transferred on save when
        # the key is PRESENT in the profile. A del leaves the old config value in
        # place. Empty workflow + no LoRAs = override deleted. ``model`` is dropped
        # (it comes from the workflow).
        if workflow or tpose_workflow or clean_loras or clean_tpose_loras:
            prof["outfit_imagegen"] = {"workflow": workflow,
                                       "tpose_workflow": tpose_workflow,
                                       "loras": clean_loras,
                                       "tpose_loras": clean_tpose_loras}
        else:
            prof["outfit_imagegen"] = {}
        save_character_profile(character_name, prof)
    return {"status": "ok", "workflow": workflow,
            "tpose_workflow": tpose_workflow, "loras": clean_loras,
            "tpose_loras": clean_tpose_loras}


def build_status_effects(character_name: str) -> Dict[str, Any]:
    """Returns the current status values of a character.

    On the first call: initializes status_effects from trait defaults and
    persists them in the profile. Afterwards the stored values are always
    returned.
    """
    from app.models.character_template import is_feature_enabled
    if not is_feature_enabled(character_name, "status_effects_enabled"):
        return {"status_effects": {}, "traits": {}, "bar_meta": {}}
    from app.models.character import get_character_profile, get_character_config, save_character_profile
    profile = get_character_profile(character_name)
    config = get_character_config(character_name)
    status = profile.get("status_effects", {})

    # Load the template -- source for stat defaults and bar metadata
    bar_meta = {}
    stat_defaults = {}  # stat_key -> default_value from the template
    stat_order: List[str] = []  # template order of the stats
    try:
        from app.models.character_template import get_template
        template_name = profile.get("template", "human-default")
        template = get_template(template_name)
        if template:
            for section in template.get("sections", []):
                for field in section.get("fields", []):
                    if field.get("store") != "status_effects":
                        continue
                    stat_key = field.get("key", "")
                    if not stat_key:
                        continue
                    if stat_key not in stat_order:
                        stat_order.append(stat_key)
                    # Default from the template
                    if field.get("default") is not None:
                        try:
                            stat_defaults[stat_key] = int(field["default"])
                        except (ValueError, TypeError):
                            pass
                    # Bar metadata
                    meta = {}
                    if field.get("bar_color"):
                        meta["color"] = field["bar_color"]
                    if field.get("bar_label"):
                        meta["label"] = field["bar_label"]
                    if field.get("label"):
                        meta["name"] = field["label"]
                    if field.get("label_de"):
                        meta["name_de"] = field["label_de"]
                    if meta:
                        bar_meta[stat_key] = meta
    except Exception:
        pass

    # Initialize and persist missing status_effects from template defaults
    status_changed = False
    for stat_key, stat_default in stat_defaults.items():
        if stat_key not in status:
            status[stat_key] = stat_default
            status_changed = True

    if status_changed:
        # Read AGAIN under the per-character profile lock and re-apply only
        # OUR keys (DATA-3, the pattern ``places.assign`` uses): the copy read
        # at the top of this function was read for the template walk above,
        # and writing it back would drop everything a concurrent writer stored
        # since. Only the missing defaults are filled in, never overwritten —
        # a value another thread just wrote wins.
        from app.core.keyed_lock import keyed_lock
        with keyed_lock("character_profile", character_name):
            profile = get_character_profile(character_name) or {}
            status = dict(profile.get("status_effects") or {})
            for stat_key, stat_default in stat_defaults.items():
                status.setdefault(stat_key, stat_default)
            profile["status_effects"] = status
            save_character_profile(character_name, profile)

    # Return in template order -- otherwise Self/Others panels show the same
    # stats in different (stored) orders.
    ordered_status = {k: status[k] for k in stat_order if k in status}
    for k, v in status.items():  # append keys not defined in the template
        if k not in ordered_status:
            ordered_status[k] = v

    return {"status_effects": ordered_status, "bar_meta": bar_meta}


def apply_template_switch(character_name: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Template switch with diff: shows new/dropped fields and runs migration.

    mode="diff": returns only the diff (no change)
    mode="apply": performs the switch (set new defaults, delete old fields)
    """
    user_id = data.get("user_id", "").strip()
    new_template_name = data.get("new_template", "").strip()
    mode = data.get("mode", "diff")

    if not new_template_name:
        raise HTTPException(status_code=400, detail="user_id und new_template erforderlich")

    from app.models.character import get_character_profile, get_character_config, save_character_profile, save_character_config
    from app.models.character_template import get_template

    profile = get_character_profile(character_name)
    config = get_character_config(character_name)
    old_template_name = profile.get("template", "")
    old_template = get_template(old_template_name) if old_template_name else None
    new_template = get_template(new_template_name)

    # A temporary NPC stays a temporary NPC: converting it to a full template
    # would grant wardrobe/memory/… the throwaway design excludes (and the UI
    # hides the selector for it — this is the API-side backstop).
    if old_template and (old_template.get("features") or {}).get("temporary_npc"):
        raise HTTPException(status_code=409, detail=(
            f"'{character_name}' is a temporary NPC — template switching is "
            "not supported for temporary NPCs"))

    if not new_template:
        raise HTTPException(status_code=404, detail=f"Template '{new_template_name}' nicht gefunden")

    # Collect ALL fields from old and new template (not just traits)
    def _collect_all_fields(tmpl):
        fields = {}
        if not tmpl:
            return fields
        for section in tmpl.get("sections", []):
            for field in section.get("fields", []):
                fkey = field.get("key", "")
                if fkey:
                    fields[fkey] = field
        return fields

    old_fields = _collect_all_fields(old_template)
    new_fields = _collect_all_fields(new_template)

    # Compute the diff
    added = []
    for key, field in new_fields.items():
        if key not in old_fields:
            added.append({
                "key": key,
                "label": field.get("label", key),
                "label_de": field.get("label_de", ""),
                "default": field.get("default"),
                "store": field.get("store", ""),
                "is_stat": field.get("store") == "status_effects",
            })

    removed = []
    for key, field in old_fields.items():
        if key not in new_fields:
            store = field.get("store", "")
            # Read the current value from the correct store
            if store == "status_effects":
                current_val = profile.get("status_effects", {}).get(key, "")
            elif store == "config":
                current_val = config.get(key, "")
            else:
                current_val = profile.get(key, "")
            removed.append({
                "key": key,
                "label": field.get("label", key),
                "label_de": field.get("label_de", ""),
                "current_value": current_val,
                "store": store,
                "is_stat": store == "status_effects",
            })

    if mode == "diff":
        return {
            "old_template": old_template_name,
            "new_template": new_template_name,
            "added": added,
            "removed": removed,
        }

    # mode == "apply": run the migration.
    # Read AGAIN under the per-character profile lock and apply the migration
    # to THAT copy (DATA-3): the read at the top of this function fed the diff
    # above, which may have been computed a while ago, and the save below
    # rewrites the whole profile_json blob. The template lookups all happened
    # outside the lock; nothing inside it takes another lock.
    from app.core.keyed_lock import keyed_lock
    with keyed_lock("character_profile", character_name):
        profile = get_character_profile(character_name)

        # 1. Fill new fields with defaults
        status = profile.get("status_effects", {})
        for item in added:
            default_val = item.get("default")
            key = item["key"]
            store = item.get("store", "")
            if store == "status_effects":
                if default_val is not None and key not in status:
                    status[key] = default_val
            elif store == "config":
                config[key] = default_val if default_val is not None else ""
            else:
                profile[key] = default_val if default_val is not None else ""

        # 2. Remove old fields
        for item in removed:
            key = item["key"]
            store = item.get("store", "")
            if store == "status_effects":
                status.pop(key, None)
                config.pop(key + "_hourly", None)
            elif store == "config":
                config.pop(key, None)
            else:
                profile.pop(key, None)

        profile["status_effects"] = status

        # 4. Set the template in the profile
        profile["template"] = new_template_name

        # 5. Save
        save_character_profile(character_name, profile)
    save_character_config(character_name, config)

    return {
        "ok": True,
        "old_template": old_template_name,
        "new_template": new_template_name,
        "added": added,
        "removed": removed,
    }


async def create_character_core(request) -> Dict[str, Any]:
    """Creates a new character with an empty profile and an assigned template."""
    from app.models.account import get_language_settings, set_current_character
    from app.models.character import (list_available_characters,
                                      save_character_profile, get_character_config,
                                      save_character_config, save_character_skill_config)
    from app.core.character_name import (CharacterNameError, localized_message,
                                         validate_character_name)
    from app.core.i18n import t
    data = await request.json()
    template_name = data.get("template", "human-default")
    lang = get_language_settings().get("system_language") or "en"
    # THE name rule (app/core/character_name.py) — one rule for every creator.
    # It also catches the JS nulls ("undefined", "null") that appear when some
    # frontend path string-converts an uninitialized value; those must never
    # create a character folder.
    try:
        character_name = validate_character_name(data.get("character_name", ""))
    except CharacterNameError as err:
        raise HTTPException(status_code=400,
                            detail=localized_message(err, lang))

    # Check if character already exists
    existing = list_available_characters()
    if character_name in existing:
        raise HTTPException(status_code=409, detail=t(
            "A character named \"{name}\" already exists.", lang
        ).format(name=character_name))

    # Create character with initial profile + template reference
    initial_profile = {
        "character_name": character_name,
        "template": template_name,
    }
    # Explicit creation -- save_character_profile otherwise blocks unknown
    # names (protection against ghost characters from LLM output).
    save_character_profile(character_name, initial_profile, create_new=True)

    # Initialize known_locations explicitly as an empty list. Without this
    # field the legacy bypass in the SetLocation skill kicks in and the char
    # may teleport to arbitrary places (path validation is skipped). Fresh
    # chars should not be able to go anywhere until they are actively placed
    # or led -- auto-discovery in save_character_current_location fills the
    # list afterwards automatically.
    try:
        cfg = get_character_config(character_name) or {}
        if "known_locations" not in cfg:
            cfg["known_locations"] = []
            save_character_config(character_name, cfg)
    except Exception as _e:
        logger.warning("create_character: known_locations init failed: %s", _e)

    # Write skill defaults -- without these files the ALWAYS_LOAD filter logic
    # (skill_manager._get_agent_skills) kicks in and turns all skills off by
    # default. With the default list the fresh char has the usual repertoire
    # right away (chat, set_location, consume magic, outfit change, ...).
    for _sid in default_new_character_skills():
        try:
            save_character_skill_config(character_name, _sid, {"enabled": True})
        except Exception as _e:
            logger.warning("create_character: skill default '%s' not set: %s",
                           _sid, _e)

    # Auto-assign the new character to the creator's allowed_characters list
    # so they can immediately see and use it without a separate admin step.
    from app.core.auth_dependency import get_current_user_optional
    from app.core.users import update_user
    creator = get_current_user_optional(request)
    if creator and creator.get("id"):
        allowed = list(creator.get("allowed_characters") or [])
        if character_name not in allowed:
            allowed.append(character_name)
            try:
                update_user(creator["id"], allowed_characters=allowed)
            except Exception as e:
                logger.warning(
                    "create_character: could not update allowed_characters "
                    "for user=%s: %s",
                    creator.get("username"), e,
                )

    # Set as current character
    set_current_character(character_name)

    return {
        "status": "success",
        "character": character_name,
        "template": template_name,
        "message": t("Character \"{name}\" created.", lang).format(
            name=character_name),
    }


# ---------------------------------------------------------------------------
# Soul Editor -- MD files under characters/{Char}/soul/
# ---------------------------------------------------------------------------

def _parse_soul_sections(text: str) -> List[Dict[str, Any]]:
    """Splits MD text into {heading, body, has_editable_marker} sections.

    A top-level `# Heading` is marked as a 'top' section. Body is raw content
    WITHOUT the EDITABLE marker (the UI renders the status indicator separately).
    """
    sections = []
    cur_h = None
    cur_lvl = 0
    cur_body: List[str] = []

    def _flush():
        if cur_h is None and not cur_body:
            return
        body_lines = list(cur_body)
        # Detect the EDITABLE marker + remove it from the body
        has_marker = any(_SOUL_EDITABLE_MARKER in ln for ln in body_lines)
        clean_body = [ln for ln in body_lines if _SOUL_EDITABLE_MARKER not in ln]
        body_text = "\n".join(clean_body).strip()
        sections.append({
            "level": cur_lvl,
            "heading": cur_h or "",
            "body": body_text,
            "editable_marker": has_marker,
        })

    for line in text.splitlines():
        if line.startswith("# ") and not line.startswith("## "):
            _flush()
            cur_h = line[2:].strip()
            cur_lvl = 1
            cur_body = []
        elif line.startswith("## "):
            _flush()
            cur_h = line[3:].strip()
            cur_lvl = 2
            cur_body = []
        else:
            cur_body.append(line)
    _flush()
    return sections


def _soul_file_meta(section_id: str) -> Dict[str, Any]:
    """Returns meta for a soul file: file-default lock status + path."""
    if section_id in _SOUL_EDITABLE:
        default = "editable"
    elif section_id in _SOUL_LOCKED:
        default = "locked"
    else:
        default = "unknown"
    return {
        "section": section_id,
        "file_default": default,
        "path": _SOUL_FILE_MAP.get(section_id, ""),
    }


def _is_soul_section_enabled(character_name: str, section_id: str) -> bool:
    """Checks whether the soul section is enabled via a template feature.

    'personality' / 'tasks' / 'presence' are ungated -> always on. Others via
    a template feature. beliefs/lessons/goals are additionally coupled to the
    Retrospect master switch -- when the char has disabled Retrospect via the
    UI, those three sections drop out of the soul tab regardless of what the
    template says for beliefs/lessons/goals.
    """
    if section_id in ("personality", "tasks", "presence"):
        return True
    feature_map = {
        "roleplay_rules": "roleplay_rules_enabled",
        "beliefs":        "beliefs_enabled",
        "lessons":        "lessons_enabled",
        "goals":          "goals_enabled",
        "soul":           "soul_enabled",
    }
    feature = feature_map.get(section_id)
    if not feature:
        return False
    try:
        from app.models.character_template import is_feature_enabled
        # Retrospect master switch: disables the three output sections
        # together.
        if section_id in ("beliefs", "lessons", "goals"):
            if not is_feature_enabled(character_name, "retrospect_enabled"):
                return False
        return is_feature_enabled(character_name, feature)
    except Exception:
        return True


def build_soul_files(character_name: str) -> Dict[str, Any]:
    """Lists the soul MD files available for this character.

    Honors template feature gates. Returns per file: section id, file-default
    lock status, and whether the file exists.
    """
    from app.models.character import get_character_dir, get_character_profile
    char_dir = get_character_dir(character_name)

    # Friendly labels from the template: source_file basename (= section id) ->
    # field label/label_de. So the soul tab shows "Roleplay Rules" instead of
    # "Roleplay_rules".
    import os as _os
    label_map: Dict[str, Dict[str, str]] = {}
    try:
        from app.models.character_template import get_template
        _prof = get_character_profile(character_name) or {}
        _tmpl = get_template(_prof.get("template", "")) if _prof.get("template") else None
        for _sec in (_tmpl or {}).get("sections", []):
            for _f in _sec.get("fields", []):
                _sf = _f.get("source_file") or ""
                if not _sf:
                    continue
                _sid = _os.path.basename(_sf)
                if _sid.endswith(".md"):
                    _sid = _sid[:-3]
                label_map[_sid] = {
                    "label": _f.get("label") or "",
                    "label_de": _f.get("label_de") or "",
                }
    except Exception:
        pass

    files = []
    for section_id in ("personality", "tasks", "presence", "roleplay_rules",
                        "beliefs", "lessons", "goals", "soul"):
        if not _is_soul_section_enabled(character_name, section_id):
            continue
        meta = _soul_file_meta(section_id)
        meta["exists"] = (char_dir / meta["path"]).exists()
        _lbl = label_map.get(section_id, {})
        meta["label"] = _lbl.get("label", "")
        meta["label_de"] = _lbl.get("label_de", "")
        files.append(meta)
    return {"character": character_name, "files": files}


def read_soul_file(character_name: str, section_id: str) -> Dict[str, Any]:
    """Returns content + parsed sections of a soul MD file."""
    if section_id not in _SOUL_FILE_MAP:
        raise HTTPException(status_code=404, detail=f"Unknown section: {section_id}")
    if not _is_soul_section_enabled(character_name, section_id):
        raise HTTPException(status_code=403, detail=f"Section '{section_id}' nicht im Template aktiv")

    from app.models.character import get_character_dir
    char_dir = get_character_dir(character_name)
    md_path = char_dir / _SOUL_FILE_MAP[section_id]

    raw = md_path.read_text(encoding="utf-8") if md_path.exists() else ""
    sections = _parse_soul_sections(raw)
    meta = _soul_file_meta(section_id)
    return {
        "character": character_name,
        "section": section_id,
        "path": meta["path"],
        "file_default": meta["file_default"],
        "raw": raw,
        "sections": sections,
        "editable_marker_token": _SOUL_EDITABLE_MARKER,
    }


async def write_soul_file(character_name: str, section_id: str, request) -> Dict[str, Any]:
    """Writes a complete soul MD file.

    Body: {"user_id": "...", "content": "...full MD text..."}
    """
    if section_id not in _SOUL_FILE_MAP:
        raise HTTPException(status_code=404, detail=f"Unknown section: {section_id}")
    data = await request.json()
    user_id = data.get("user_id", "")
    content = data.get("content", "")
    if not _is_soul_section_enabled(character_name, section_id):
        raise HTTPException(status_code=403, detail=f"Section '{section_id}' nicht im Template aktiv")

    from app.models.character import get_character_dir
    char_dir = get_character_dir(character_name)
    md_path = char_dir / _SOUL_FILE_MAP[section_id]
    md_path.parent.mkdir(parents=True, exist_ok=True)
    # Guarantee a trailing newline without collecting superfluous ones
    md_path.write_text(content.rstrip() + "\n", encoding="utf-8")
    return {"status": "success", "section": section_id, "size": len(content)}


# === Round C: movement + imagegen AI-ops (moved 1:1 from routes) ===


def build_current_location_payload(character_name: str) -> Dict[str, Any]:
    """Gibt den aktuellen virtuellen Aufenthaltsort zurueck"""
    from app.models.character import get_character_current_location
    from app.models.world import get_location_name as _get_loc_name, get_room_by_id, _load_world_data
    from app.models.character_template import is_feature_enabled
    locations_on = is_feature_enabled(character_name, "locations_enabled")
    activities_on = is_feature_enabled(character_name, "activities_enabled")
    location_id = get_character_current_location(character_name) if locations_on else ""
    location_name = _get_loc_name(location_id) if location_id else ""
    from app.models.character import get_effective_activity
    activity = get_effective_activity(character_name) if activities_on else ""
    from app.models.character import get_character_current_room
    current_room = get_character_current_room(character_name) if locations_on else ""
    # Resolve room: could be an ID or a name — normalize to ID + name
    current_room_id = ""
    current_room_name = ""
    if current_room and location_id:
        world_data = _load_world_data()
        for loc in world_data.get("locations", []):
            if loc.get("id") == location_id:
                # Try by ID first
                room = get_room_by_id(loc, current_room)
                if room:
                    current_room_id = room.get("id", current_room)
                    current_room_name = room.get("name", "")
                else:
                    # Fallback: match by name
                    for r in loc.get("rooms", []):
                        if r.get("name", "").lower() == current_room.lower():
                            current_room_id = r.get("id", "")
                            current_room_name = r.get("name", "")
                            break
                break
    # Detail-Beschreibung der Aktivitaet
    from app.models.character import get_character_profile, get_movement_target
    profile = get_character_profile(character_name)
    activity_detail = ""  # current_activity_detail entfernt (Pose-Modell)
    movement_target_id = get_movement_target(character_name) if locations_on else ""
    movement_target_name = _get_loc_name(movement_target_id) if movement_target_id else ""
    return {
        "character": character_name,
        "current_location": location_name or location_id or "",
        "current_location_id": location_id or "",
        "current_activity": activity or "",
        "current_activity_detail": activity_detail,
        "current_room": current_room_id or current_room or "",
        "current_room_name": current_room_name or current_room or "",
        "movement_target_id": movement_target_id,
        "movement_target_name": movement_target_name,
    }


def _wake_avatar_on_manual_move(character_name: str, moved: bool) -> None:
    """Player/admin-driven movement is a wake signal: without this a sleeping
    avatar keeps its Sleeping state (flag + sleep expression) after being
    moved to another location/room. Deliberately avatar-only — NPC sleep is
    managed by the agent loop/rules (sleep-walk moves sleeping characters on
    purpose). Counterpart of the same wake in /play/enter-room."""
    if not moved:
        return
    from app.models.character import is_character_sleeping, set_is_sleeping
    if is_character_sleeping(character_name):
        set_is_sleeping(character_name, False)
        logger.info("manual move: %s woke up (location/room change)", character_name)


async def apply_current_location(character_name: str, request) -> Dict[str, Any]:
    """Aktualisiert den aktuellen virtuellen Aufenthaltsort"""
    from app.models.character import save_character_current_location
    data = await request.json()
    user_id = data.get("user_id", "")
    location = data.get("current_location", "")
    room = data.get("current_room", "")

    # Name → ID aufloesen falls noetig
    from app.models.world import resolve_location as _resolve_loc, get_arrival_room_id
    from app.models.character import get_character_current_location, get_character_current_room, save_character_current_room, clear_pose_intent
    loc_obj = _resolve_loc(location)
    location_to_save = loc_obj["id"] if loc_obj and loc_obj.get("id") else location
    location_name_resp = loc_obj.get("name", location) if loc_obj else location
    old_loc = get_character_current_location(character_name)
    old_room = get_character_current_room(character_name) or ""
    # Default room for a cross-location move: where one arrives at the target
    # — its entry room, or the ground when none is declared.
    if not room and loc_obj and location_to_save != old_loc:
        room = get_arrival_room_id(loc_obj)
    # Avatar: Outfit NICHT automatisch umstellen (manuelle User-Wahl bleibt).
    from app.models.account import get_active_character
    _is_avatar = (get_active_character() == character_name)

    # Block-Regeln: Avatar darf nicht in geblockte Locations/Raeume.
    # Gleiche Gates wie der SetLocation-Skill der NPCs durchlaeuft.
    if _is_avatar and (location_to_save != old_loc or (room and room != old_room)):
        from app.models.rules import check_leave, check_access
        if old_loc and location_to_save != old_loc:
            ok_leave, leave_msg = check_leave(character_name)
            if not ok_leave:
                raise HTTPException(status_code=403,
                    detail={"reason": "block_leave", "message": leave_msg})
        ok_enter, enter_msg = check_access(character_name, location_to_save,
                                           room_id=room or "")
        if not ok_enter:
            raise HTTPException(status_code=403,
                detail={"reason": "block_enter", "message": enter_msg})
    save_character_current_location(character_name, location_to_save,
        _skip_compliance=_is_avatar)
    # Raum und Aktivitaet: bei Ortswechsel loeschen, es sei denn Raum wurde mitgegeben
    if location_to_save != old_loc:
        save_character_current_room(character_name, room or '')
        if not room:
            clear_pose_intent(character_name)
    elif room:
        save_character_current_room(character_name, room)
    if _is_avatar:
        _wake_avatar_on_manual_move(
            character_name,
            location_to_save != old_loc or bool(room and room != old_room))

    # Avatar-Eintritts-Hook: andere Characters im neuen Raum bemerken den
    # Eintritt und reagieren ggf. (forced_thought + TalkTo). Nur wenn:
    # - es der Avatar ist (sonst ist's der Auto-Move eines NPCs)
    # - tatsaechlich Raum oder Location gewechselt hat (nicht nur Re-Save)
    new_room = room or ''
    room_changed = (location_to_save != old_loc) or (new_room and new_room != old_room)
    from app.core.log import get_logger as _gl_route
    _gl_route("characters_route").info(
        "current-location POST: char=%s is_avatar=%s old_loc=%s -> new_loc=%s old_room=%s -> new_room=%s room_changed=%s",
        character_name, _is_avatar, old_loc, location_to_save, old_room, new_room, room_changed)
    room_entry_result = {"reactor": "", "silent_noticers": []}
    # Roll-on-Entry: bei echtem Cross-Location-Move sofort wuerfeln, ob ein
    # Event fuer den Avatar entsteht. Nur fuer Avatar (nicht fuer NPC-Moves).
    if _is_avatar and location_to_save != old_loc and loc_obj:
        try:
            from app.core.random_events import try_roll_on_entry
            try_roll_on_entry(character_name, location_to_save, loc_obj)
        except Exception as _re:
            logger.debug("try_roll_on_entry fehlgeschlagen: %s", _re)
    if _is_avatar and room_changed:
        try:
            from app.core.room_entry import on_avatar_room_entry
            # Room-Label aufloesen
            _room_label = ""
            if new_room and loc_obj:
                from app.models.world import get_room_by_id
                _r = get_room_by_id(loc_obj, new_room)
                if _r and _r.get("name"):
                    _room_label = _r["name"]
            import asyncio as _asyncio
            room_entry_result = await _asyncio.to_thread(
                on_avatar_room_entry,
                avatar_name=character_name,
                location_id=location_to_save,
                room_id=new_room,
                location_label=location_name_resp,
                room_label=_room_label,
            ) or room_entry_result
        except Exception as _re:
            from app.core.log import get_logger as _gl
            _gl("characters_route").debug("avatar_room_entry hook failed: %s", _re)

    return {
        "status": "success",
        "character": character_name,
        "current_location": location_name_resp,
        "reactor": room_entry_result.get("reactor", ""),
        "silent_noticers": room_entry_result.get("silent_noticers", []),
    }


async def apply_place_on_map(character_name: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """ADMIN placement: put a character at a location + room by hand.

    This is a TELEPORT, not a move the character decided on. Everything an
    arrival entails therefore happens through the PUBLIC setters the engines
    use, never by writing the profile here:

    * ``travel_engine.cancel_journey`` first — a running journey would keep
      walking the figure away from where it was just put, and the journey is
      only dropped by ``save_character_current_location`` when the location
      really changes (placing inside the location one is currently nearest to
      would leave it running),
    * ``save_character_current_location`` does the rest of the arrival: it
      ends a pair interaction, clears the pose (= the activity, see
      ``get_effective_activity``), drags the metre position to the target,
      discovers the place (``known_locations`` + sight), runs the outfit
      compliance and PULLS THE PARTY along when this character leads one,
    * ``save_character_current_room`` releases the held place, sets the room
      and puts the figure on a free standing point (``room_stand.stand_up``).

    Body: ``{"location_id": ..., "current_room": ... (optional, default the
    target's entry room), "leave_party": true (optional, see below)}``.

    Gates:

    * unknown location or unknown room -> 400. A raw id written through would
      leave the character standing nowhere,
    * a party FOLLOWER owns no movement of its own (only the leader moves,
      followers are pulled) -> 409 ``party_follower``. Placing one alone is a
      state the party engine never produces; the admin either places the
      LEADER (which pulls everyone) or says so explicitly with
      ``leave_party: true``, which leaves the party first — leaving is always
      allowed,
    * a SLEEPING character is placed and stays asleep — no wake-up here: an
      admin moving a figure on the map is not the character's own manual move,
    * the ACTIVE AVATAR is allowed. Its client keeps reporting positions
      (``POST /play/pos``), but a report that is suddenly far away from the
      stored point is refused with the server's point in the body, which the
      client snaps onto — the same correction path a party pull uses.

    The avatar's block rules are checked as on every avatar move.
    """
    from app.models.character import (get_character_current_location,
                                      save_character_current_location)
    location = (data.get("location_id") or data.get("current_location") or "").strip()
    room = (data.get("current_room") or "").strip()
    if not location:
        raise HTTPException(status_code=400, detail="location_id is required")

    from app.models.world import (get_arrival_room_id, get_room_by_id,
                                  resolve_location as _resolve_loc)
    from app.models.character import (
        add_known_location, get_character_current_room,
        save_character_current_room, clear_pose_intent)

    loc_obj = _resolve_loc(location)
    if not loc_obj or not loc_obj.get("id"):
        raise HTTPException(status_code=400,
                            detail=f"Unknown location '{location}'")
    location_to_save = loc_obj["id"]
    location_name_resp = loc_obj.get("name", location_to_save)

    # A named room has to BE a room of that place — the id goes straight into
    # the profile and a typo would leave the character in a room nobody can
    # render. No room handed in -> the target's arrival room (entry room, or
    # the ground when none is declared).
    if room:
        if not get_room_by_id(loc_obj, room):
            raise HTTPException(
                status_code=400,
                detail=f"Unknown room '{room}' in '{location_name_resp}'")
    else:
        room = get_arrival_room_id(loc_obj)

    # A follower is carried by its leader; it has no move of its own.
    from app.core.party_engine import get_party_of, is_party_follower, leave_party
    if is_party_follower(character_name):
        if not data.get("leave_party"):
            from app.core.i18n import t as _t
            from app.models.character import get_character_language
            _party = get_party_of(character_name) or {}
            _lang = get_character_language(character_name) or "de"
            raise HTTPException(status_code=409, detail={
                "reason": "party_follower",
                "leader": _party.get("leader", ""),
                "message": _t(
                    "{name} travels with {leader} and is taken along by them. "
                    "Place {leader} instead, or let {name} leave the party "
                    "first.", _lang).format(
                        name=character_name,
                        leader=_party.get("leader", "") or "the leader")})
        leave_party(character_name)

    old_loc = get_character_current_location(character_name)
    old_room = get_character_current_room(character_name) or ""
    from app.models.account import get_active_character
    _is_avatar = (get_active_character() == character_name)

    # Block rules: the avatar may not be put into a blocked location/room —
    # the same gates its own move walks through.
    if _is_avatar and (location_to_save != old_loc or (room and room != old_room)):
        from app.models.rules import check_leave, check_access
        if old_loc and location_to_save != old_loc:
            ok_leave, leave_msg = check_leave(character_name)
            if not ok_leave:
                raise HTTPException(status_code=403,
                    detail={"reason": "block_leave", "message": leave_msg})
        ok_enter, enter_msg = check_access(character_name, location_to_save,
                                           room_id=room or "")
        if not ok_enter:
            raise HTTPException(status_code=403,
                detail={"reason": "block_enter", "message": enter_msg})

    # The trip is over before the teleport, not because of it.
    from app.core.travel_engine import cancel_journey
    cancel_journey(character_name)

    add_known_location(character_name, location_to_save)
    save_character_current_location(character_name, location_to_save,
        _skip_compliance=_is_avatar)
    if location_to_save != old_loc:
        save_character_current_room(character_name, room or '')
        if not room:
            clear_pose_intent(character_name)
    elif room:
        save_character_current_room(character_name, room)

    new_room = room or ''
    room_changed = (location_to_save != old_loc) or (new_room and new_room != old_room)
    room_entry_result = {"reactor": "", "silent_noticers": []}
    # Roll-on-entry: a cross-location placement of the avatar rolls at once.
    if _is_avatar and location_to_save != old_loc:
        try:
            from app.core.random_events import try_roll_on_entry
            try_roll_on_entry(character_name, location_to_save, loc_obj)
        except Exception as _re:
            logger.debug("try_roll_on_entry failed: %s", _re)
    if _is_avatar and room_changed:
        try:
            from app.core.room_entry import on_avatar_room_entry
            _room_label = ""
            if new_room:
                _r = get_room_by_id(loc_obj, new_room)
                if _r and _r.get("name"):
                    _room_label = _r["name"]
            import asyncio as _asyncio
            room_entry_result = await _asyncio.to_thread(
                on_avatar_room_entry,
                avatar_name=character_name,
                location_id=location_to_save,
                room_id=new_room,
                location_label=location_name_resp,
                room_label=_room_label,
            ) or room_entry_result
        except Exception as _re:
            logger.debug("avatar_room_entry hook failed: %s", _re)

    return {
        "status": "success",
        "character": character_name,
        "current_location": location_name_resp,
        "current_location_id": location_to_save,
        "current_room": new_room,
        "reactor": room_entry_result.get("reactor", ""),
        "silent_noticers": room_entry_result.get("silent_noticers", []),
    }


async def detect_characters_core(character_name: str, image_name: str, request) -> Dict[str, Any]:
    """Erkennt im Bild verwendete Characters aus reference_images Metadaten."""
    from app.models.character import (list_available_characters, get_character_images_dir,
        get_character_outfits_dir, get_character_image_prompts, get_character_current_location)
    from app.models.account import get_user_profile, get_active_character
    from app.models.character import get_single_image_meta

    body = await request.json()
    user_id = body.get("user_id", "")

    all_chars = list_available_characters()
    user_profile = get_user_profile()
    # user_name = Login-Name (z.B. "admin") — ist KEINE Person die in einem
    # Bild auftauchen kann. Avatar ist der vom User gespielte Character.
    avatar_name = (get_active_character() or "").strip()
    user_name = avatar_name  # Fuer Detection (Filename-Match etc.) den Avatar nutzen

    # 1. Primaer: explizit gespeicherte character_names aus vorheriger Auswahl
    meta = get_single_image_meta(character_name, image_name)
    saved_names = (meta or {}).get("character_names")
    detected_names = []
    if saved_names and isinstance(saved_names, list):
        detected_names = saved_names
    else:
        # 2. Fallback: canonical.persons aus dem Generate-Zeitpunkt — das ist
        #    die zuverlaessigste Quelle, weil sie genau die Personen enthaelt
        #    die der Prompt-Builder ins Bild gepackt hat. Nur Nicht-Agent
        #    persons (= im Bild sichtbar, nicht der Photographer-Avatar).
        canonical = (meta or {}).get("canonical") or {}
        canon_persons = canonical.get("persons") or []
        if isinstance(canon_persons, list):
            for p in canon_persons:
                if not isinstance(p, dict):
                    continue
                _n = (p.get("name") or "").strip()
                if _n and _n not in detected_names:
                    detected_names.append(_n)

        # 3. Fallback: aus reference_images ableiten — aber NUR Person-Slots,
        #    keine Background-/Location-Refs (sonst wird der Avatar faelschlich
        #    detected weil das BG-Bild zufaellig im User-Image-Dir liegt).
        if not detected_names:
            ref_images = meta.get("reference_images", {}) if meta else {}
            _BG_SLOT_HINTS = ("background", "location", "scene", "_4", "room")
            for _slot, ref_filename in ref_images.items():
                _slot_lower = (_slot or "").lower()
                if any(h in _slot_lower for h in _BG_SLOT_HINTS):
                    continue  # Background/Location-Slot, keine Person
                matched = False
                # a) Dateiname beginnt mit Character-Name
                for c in all_chars:
                    if ref_filename.startswith(c + "_"):
                        if c not in detected_names:
                            detected_names.append(c)
                        matched = True
                        break
                if matched:
                    continue
                # b) Datei in Character-Verzeichnissen suchen (Images, Outfits, Variants)
                for c in all_chars:
                    _imgs_dir = get_character_images_dir(c)
                    _outfits_dir = get_character_outfits_dir(c)
                    _variants_dir = _outfits_dir / "variants"
                    if ((_imgs_dir / ref_filename).exists()
                            or (_outfits_dir / ref_filename).exists()
                            or (_variants_dir / ref_filename).exists()):
                        if c not in detected_names:
                            detected_names.append(c)
                        matched = True
                        break
                # c) User-Profilbild — nur wenn Slotname NICHT als BG identifiziert wurde
                #    (oben schon abgefangen)
                if not matched and user_name and user_name not in detected_names:
                    from app.models.account import get_user_images_dir
                    _user_imgs = get_user_images_dir()
                    if (_user_imgs / ref_filename).exists():
                        detected_names.append(user_name)

        # 4. Letzter Fallback: Prompt-basierte Erkennung
        if not detected_names:
            prompts = get_character_image_prompts(character_name)
            prompt = prompts.get(image_name, "")
            if prompt:
                from app.core.prompt_builder import PromptBuilder
                _pb = PromptBuilder(character_name)
                _persons = _pb.detect_persons(prompt)
                appearances = [{"name": p.name, "appearance": p.appearance} for p in _persons]
                detected_names = [p["name"] for p in appearances]

    # Underscore-Prefix-Filter (Sicherheitsnetz fuer System-Characters wie
    # _messaging_frame, falls list_available_characters cached o.ae.)
    all_chars = [c for c in all_chars if not c.startswith("_")]

    # "Agent" = der Charakter der das Bild ERSTELLT hat. Bei Bildern die ein
    # NPC dem Avatar geschickt hat (gallery_character != ersteller), steht
    # der Ersteller in meta.from_character. Sonst ist es der gallery_owner.
    agent_name = (meta or {}).get("from_character") or character_name
    available = []
    if agent_name and agent_name in all_chars:
        available.append({"name": agent_name, "type": "agent"})
    if user_name and user_name != agent_name:
        available.append({"name": user_name, "type": "user"})
    for c in all_chars:
        if c != agent_name and c != user_name:
            available.append({"name": c, "type": "character"})

    # Rooms der aktuellen Location (fuer Room-Auswahl im Dialog)
    rooms = []
    current_room_id = ""
    location_id = (meta or {}).get("location", "")
    if not location_id:
        location_id = get_character_current_location(character_name) or ""
    if location_id:
        from app.models.world import get_location
        loc_data = get_location(location_id)
        if loc_data:
            for room in loc_data.get("rooms", []):
                rooms.append({"id": room.get("id", ""), "name": room.get("name", "")})
        current_room_id = (meta or {}).get("room_id", "")
        # Room aus Slot-4 Hintergrundbild ableiten wenn nicht explizit gespeichert
        if not current_room_id:
            ref_images = meta.get("reference_images", {}) if meta else {}
            slot4_filename = ref_images.get("input_reference_image_4", "")
            if slot4_filename and loc_data:
                from app.models.world import get_gallery_image_rooms
                _img_rooms = get_gallery_image_rooms(location_id)
                _matched_room = _img_rooms.get(slot4_filename, "")
                if _matched_room:
                    current_room_id = _matched_room
        # Kein Fallback auf aktuellen Raum — wenn nicht bekannt, leer lassen

    return {
        "detected": detected_names,
        "available": available,
        "rooms": rooms,
        "current_room_id": current_room_id,
        "location_id": location_id,
    }


# === Image-generation endpoint cores + thread workers (5a-7) ===
# Routes keep auth/parsing/HTTP-mapping + the thread-spawn scaffold; the
# logic cores and worker bodies moved here 1:1.

def resolve_profile_imagegen(profile: Optional[Dict[str, Any]],
                             request_workflow: str = "",
                             request_backend: str = "") -> Dict[str, str]:
    """Resolves the render target of a PROFILE-IMAGE render.

    ONE chain for every caller — the character editor's route
    (`generate_profile_image_core`), the temporary-NPC asset job
    (`npc_assets._render_profile_image`) and any headless portrait render.
    Same order the T-pose/expression render uses (`expression_regen`):

        explicit request pick
        -> per-character override (`profile.outfit_imagegen.workflow`)
        -> `PROFILE_IMAGEGEN_DEFAULT` (config
           `image_generation.profile_imagegen_default`)
        -> empty, i.e. the service picks the cheapest available backend — the
           behaviour before this field existed.

    Which FIELD carries the spec matters: `service.generate_from_input` reads
    `workflow` as a SOFT backend glob (match by name, fall back to the ordinary
    selection when nothing matches) and `backend` as a HARD pick that fails the
    render when it does not resolve. A configured default must never fail a
    render, so the chain writes globs into `workflow`; only an explicit request
    pick reaches `backend`.

    Returns the two payload fields ready to merge into the generate request.
    """
    import os
    wf = (request_workflow or "").strip()
    be = (request_backend or "").strip()
    if wf or be:
        return {"workflow": wf, "backend": be}

    spec = ""
    char_override = (profile or {}).get("outfit_imagegen") or {}
    if isinstance(char_override, dict):
        # Legacy field name "workflow" — a backend glob since ComfyUI was removed.
        spec = (char_override.get("workflow") or "").strip()
    if not spec:
        spec = os.environ.get("PROFILE_IMAGEGEN_DEFAULT", "").strip()
    return {"workflow": spec, "backend": ""}


async def generate_profile_image_core(character_name: str, request) -> Dict[str, Any]:
    """Generates a new profile image via the core image service."""
    from app.core.dependencies import get_skill_manager
    import os
    import json as _json
    data = await request.json()
    user_id = data.get("user_id", "")

    # Character-Profil laden. Profilbild-Prompt = FACE PROMPT (face_appearance),
    # NICHT die Body-Appearance. Fallback auf Body-Appearance, falls leer.
    from app.models.character import get_character_profile, get_character_appearance, set_character_profile_image
    from app.models.character_template import resolve_profile_tokens, get_template
    profile = get_character_profile(character_name)
    tmpl = get_template(profile.get("template", "")) if profile.get("template") else None
    appearance = _resolve_face_prompt(profile, character_name, tmpl)

    # Prompt aus Dialog oder Face Prompt (Style kommt aus dem "profile"-Use-Case).
    prompt_text = data.get("prompt", "").strip() or (appearance or "").strip()

    # Image service (core engine — wave-6 split)
    from app.imagegen.service import get_image_service
    from app.core.lora_library import LoraNotAllowedError
    image_skill = get_image_service()
    if not image_skill.enabled:
        raise HTTPException(status_code=500, detail="Image service not available")

    # Render target: request pick -> character override -> config default.
    target = resolve_profile_imagegen(profile, data.get("workflow", ""),
                                      data.get("backend", ""))
    loras_override = data.get("loras")
    model_override = data.get("model_override", "").strip()

    payload = {
        "prompt": prompt_text,
        "agent_name": character_name,
        "user_id": "",
        "auto_enhance": False,
        "set_profile": True,
        "image_use_case": "profile",
        "workflow": target["workflow"],
        "backend": target["backend"],
    }
    if loras_override is not None:
        payload["loras"] = loras_override
        # Picked in THIS request (the profile-image dialog), so the gate
        # rejects an unassociated LoRA with a 400 instead of quietly
        # dropping it the way a stored one is dropped.
        payload["loras_explicit"] = True
    if model_override:
        payload["model_override"] = model_override
    input_data = _json.dumps(payload)

    try:
        import asyncio
        result = await asyncio.to_thread(image_skill.generate_from_input, input_data)
    except LoraNotAllowedError as e:
        # A LoRA the library does not associate with the resolved backend is a
        # bad request, not a failed render — the dialog offers exactly the
        # allowed ones, so only a direct API call gets here.
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Bildgenerierung fehlgeschlagen: {str(e)}")

    # Dateiname aus dem Ergebnis extrahieren
    import re
    image_match = re.search(r'/characters/[^/]+/images/([^?)\n]+)', result)
    if not image_match:
        raise HTTPException(status_code=500, detail=f"Kein Bild im Ergebnis: {result[:200]}")

    image_filename = image_match.group(1)

    # Als Profilbild setzen
    set_character_profile_image(character_name, image_filename)

    image_url = f"/characters/{character_name}/images/{image_filename}"
    return {"status": "success", "image": image_filename, "image_url": image_url}


def regenerate_image_worker(character_name, image_path, prompt, improvement_request, workflow_name, backend_name, agent_config, loras, model_override, character_names, room_id, original_location_id, negative_prompt_override, _track_id, create_new, use_room, use_source_as_reference, _tq):
    from app.skills.image_regenerate import regenerate_image
    from app.models.character import add_character_image_prompt
    from pathlib import Path
    try:
        _success, final_prompt, actual_path = regenerate_image(character_name, str(image_path),
            prompt, improvement_request, workflow_name, backend_name, agent_config,
            loras=loras,
            model_override=model_override,
            character_names=character_names,
            room_id=room_id,
            location_id=original_location_id,
            negative_prompt_override=negative_prompt_override,
            track_id=_track_id,
            create_new=bool(create_new),
            use_room=bool(use_room),
            use_source_as_reference=use_source_as_reference,
            source_image_path=str(image_path))
        _actual_filename = Path(actual_path).name
        if final_prompt != prompt:
            add_character_image_prompt(character_name, _actual_filename, final_prompt)
        _tq.track_finish(_track_id)
    except Exception as e:
        logger.error("Bild-Regenerierung fehlgeschlagen: %s", e)
        _tq.track_finish(_track_id, error=str(e))


# ═══════════════════════════════════════════════════════════════════════════
# Memory wipe — admin test tool (plan-memory-consolidation-npc-specific.md)
# ═══════════════════════════════════════════════════════════════════════════

def wipe_character_memory(character_name: str) -> Dict[str, Any]:
    """Wipes ALL derived memory artifacts of one character — the admin test
    tool for the consolidation pipeline (watch it rebuild from a clean slate).

    Thin adapter: the wipe itself is ``character_reset.reset_character`` at
    scope ``memory``, the SAME implementation the import's re-init uses at
    scope ``reinit``. There is exactly one store list (``character_reset.STORES``);
    a new per-character table is added there, not in two divergent wipes.

    Scope ``memory`` covers the whole day timeline the character page shows —
    memories, summaries (dailies + weekly/season rollups), diary entries,
    thoughts, mood/state/evolution history, the storyteller action log — plus
    the day-consolidation cursor + sleep flags. Correspondence
    (``chat_messages``) and the shared room record (``utterances``/``scenes``)
    stay; see ``character_reset.KEPT``.
    """
    # Existence check via the character LIST — get_character_profile returns
    # a default profile for unknown names (ghost-character pitfall).
    from app.models.character import list_available_characters
    if character_name not in list_available_characters():
        raise HTTPException(status_code=404,
                            detail=f"Character '{character_name}' not found")

    from app.core.character_reset import SCOPE_MEMORY, reset_character
    return reset_character(character_name, scope=SCOPE_MEMORY)
