"""Character-domain operations behind app/routes/characters.py.

Logic moved 1:1 out of the route handlers (code-review section 5a); the
routes remain thin HTTP adapters (auth, request parsing, response types).
HTTPExceptions that were embedded mid-logic moved along unchanged.
"""
from fastapi import HTTPException
from typing import Any, Dict, List, Optional
from app.core.log import get_logger

logger = get_logger("characters")

from app.core.timeutils import utc_now

# File-default whitelist (single source of truth for the soul editor UI)
from app.core.soul_sections import (
    EDITABLE_SECTIONS as _SOUL_EDITABLE,
    LOCKED_SECTIONS as _SOUL_LOCKED,
    SECTION_FILE_MAP as _SOUL_FILE_MAP,
    EDITABLE_MARKER as _SOUL_EDITABLE_MARKER)

DEFAULT_NEW_CHARACTER_SKILLS = (
    # Skill IDs from app/skills/skill_manager.py:SKILL_REGISTRY.
    # Defaults for newly created characters -- the list matches the ticks in
    # the Skills tab for a "freshly born" character (everything essential on,
    # special/niche skills like OutfitCreation, VideoGenerator, Retrospect,
    # MarkdownWriter, KnowledgeExtract stay off because they cost tokens/setup
    # and not every NPC needs them).
    "imagegen", "setlocation", "talk_to", "send_message", "notify_user",
    "instagram_comment", "instagram_reply",
    "consume_item", "outfit_change", "setactivity",
    "invite_to_party", "join_party", "leave_party",
)


# === Pure helpers ===

def _resolve_face_prompt(profile: dict, character_name: str, tmpl) -> str:
    """Profile-image prompt = face prompt (face_appearance), tokens resolved
    (target_key 'character_appearance' — this resolves both appearance fields).
    Falls back to the body appearance when face_appearance is empty."""
    from app.models.character import get_character_appearance
    from app.models.character_template import resolve_profile_tokens
    face = ((profile or {}).get("face_appearance") or "").strip()
    if face:
        if "{" in face:
            face = resolve_profile_tokens(face, profile, template=tmpl, target_key="character_appearance")
        return face.strip()
    return (get_character_appearance(character_name) or "").strip()


def _build_outfit_image_prompt(character_name: str, outfit_description: str) -> str:
    """Builds the prompt for an outfit image (separated: character + outfit + pose + expression)."""
    import os
    from app.core.prompt_builder import PromptBuilder
    from app.core.expression_pose_maps import DEFAULT_EXPRESSION, DEFAULT_POSE

    _builder = PromptBuilder(character_name)
    _persons = _builder.detect_persons("", character_names=[character_name])
    _actor = _persons[0].actor_label if _persons else character_name
    _appearance = _persons[0].appearance if _persons else ""

    # Style/framing come from the "outfit" use case — only the content here.
    character_prompt = f"{_actor}, {_appearance}"
    outfit_prompt = f"{_actor} is wearing {outfit_description}"
    return ", ".join(p for p in [
        character_prompt, outfit_prompt, DEFAULT_POSE, DEFAULT_EXPRESSION,
    ] if p)


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
    """
    from datetime import datetime as _dt
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
        ts = _dt.fromisoformat(entry.get("timestamp", ""))
        age_days = max(0, (_dt.now() - ts).total_seconds() / 86400)
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

    current_activity = profile.get("pose_intent") or ""
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
        thoughts_recent = [
            {"ts": r.get("ts", ""), "action": r.get("action", "")}
            for r in recent if r.get("name") == character_name
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
        from app.models.rules import load_rules, check_force_rules
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
                "action": r.get("action", ""), "target": target,
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
            "grid_x": loc.get("grid_x"),
            "grid_y": loc.get("grid_y"),
            "map_rotation_2d": loc.get("map_rotation_2d", 0),
            "passable": bool(loc.get("passable")),
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
                               history_limit: int = 10) -> Dict[str, Any]:
    """Tab "Relationships": sentiment, strength, tension + last N events.

    `memories_count` = how many memories have this partner set as
    related_character — a click in the frontend filters tab 2.
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

    items = []
    for r in rels:
        # Partner = the other side. _row_to_rel fills character_a/b with
        # from_char/to_char (DB order); we want the non-self name.
        a = r.get("character_a") or ""
        b = r.get("character_b") or ""
        partner = b if a == character_name else a
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
            "last_interaction": r.get("last_interaction", ""),
            "memories_count": rel_count_by_partner.get(partner, 0),
            "history_recent": recent,
        })
    # Sort: most interactions first
    items.sort(key=lambda x: x["interaction_count"], reverse=True)
    return {"character": character_name, "items": items}


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


def build_memory_history(character_name: str,
                         kind: str = "daily",
                         limit: int = 60,
                         offset: int = 0) -> Dict[str, Any]:
    """Tab "History": daily | weekly | monthly | history | diary | evolution.

    Default: `daily` (last 60 entries across all partners).
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
        items = [{"date": r[0], "partner": r[1] or "", "content": r[2]} for r in rows]
        total = conn.execute(
            "SELECT COUNT(*) FROM summaries WHERE character_name=? AND kind='daily'",
            (character_name,),
        ).fetchone()[0]
        return {"character": character_name, "kind": kind,
                "total": total, "limit": limit, "offset": offset, "items": items}

    if kind == "weekly":
        from app.core.memory_service import load_weekly_summaries
        weekly = load_weekly_summaries(character_name)
        items = [{"week": k, "content": v} for k, v in sorted(weekly.items(), reverse=True)]
        return {"character": character_name, "kind": kind, "items": items}

    if kind == "monthly":
        from app.core.memory_service import load_monthly_summaries
        monthly = load_monthly_summaries(character_name)
        items = [{"month": k, "content": v} for k, v in sorted(monthly.items(), reverse=True)]
        return {"character": character_name, "kind": kind, "items": items}

    if kind == "history":
        from app.utils.history_manager import get_cached_summary
        return {"character": character_name, "kind": kind,
                "content": get_cached_summary(character_name) or ""}

    if kind == "diary":
        rows = conn.execute("""
            SELECT id, ts, content, tags
            FROM diary_entries
            WHERE character_name=?
            ORDER BY ts DESC
            LIMIT ? OFFSET ?
        """, (character_name, limit, offset)).fetchall()
        items = []
        for r in rows:
            try: tags = _json.loads(r[3] or "[]")
            except Exception: tags = []
            items.append({"id": r[0], "ts": r[1], "content": r[2], "tags": tags})
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
    """
    from app.models.world import resolve_location, get_room_by_id
    from app.models.character import get_character_current_room
    from app.models.character import (list_available_characters,
                                      get_character_current_location,
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

    all_chars = list_available_characters()
    result = []
    for name in all_chars:
        char_loc = get_character_current_location(name)
        if not (char_loc and (char_loc == loc_id or char_loc == location)):
            continue
        char_room = (get_character_current_room(name) or "").strip()
        # Default same_room=True; only when the avatar is in a room AND the
        # character is explicitly in ANOTHER room does it count as "elsewhere".
        # A character without a room is present everywhere in the location.
        if room_norm and char_room:
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


def apply_profile_update(character_name: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Updates character profile fields (bulk update)."""
    from app.models.character import get_character_profile, save_character_profile
    user_id = data.get("user_id", "")
    fields = data.get("fields", {})
    if not fields:
        raise HTTPException(status_code=400, detail="fields fehlt")

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

    profile.update(fields)
    save_character_profile(character_name, profile)
    return {"status": "success", "character": character_name,
            "updated_fields": list(fields.keys())}


def build_active_conditions(character_name: str) -> Dict[str, Any]:
    """Returns active conditions with icon/label/remaining duration.

    Expired conditions are filtered out. Icons/labels come from the prompt
    filters (Game Admin -> Conditions).
    """
    from datetime import datetime as _dt
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

    now = _dt.now()
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
                started = _dt.fromisoformat(cond["started_at"])
                elapsed_s = (now - started).total_seconds()
                total_s = duration_h * 3600
                if elapsed_s > total_s:
                    continue
                remaining_h = round((total_s - elapsed_s) / 3600, 1)
            except (ValueError, KeyError):
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


def build_available_skills(character_name: str) -> Dict[str, Any]:
    """Returns all globally loaded skills with per-character enabled state and config fields."""
    from app.core.dependencies import get_skill_manager
    from app.models.character import get_character_skill_config
    skill_manager = get_skill_manager()
    skills = []
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

        skills.append({
            "skill_id": skill_id,
            "name": skill.name,
            "description": skill.description,
            "enabled": enabled,
            "config_fields": config_fields if config_fields else None,
        })

    # Location list for skill config fields of type "locations"
    from app.models.world import list_locations
    all_locations = [{"id": loc.get("id", ""), "name": loc.get("name", "")}
                     for loc in list_locations() if loc.get("id")]

    return {"skills": skills, "locations": all_locations}


def apply_outfit_imagegen(character_name: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """Saves workflow/model/LoRA override for the outfit image service.
    All fields empty deletes the override completely."""
    from app.models.character import get_character_profile, save_character_profile
    workflow = (body.get("workflow") or "").strip()
    model = (body.get("model") or "").strip()
    loras = body.get("loras") or []
    if not isinstance(loras, list):
        loras = []
    clean_loras = []
    for l in loras:
        if not isinstance(l, dict):
            continue
        nm = (l.get("name") or "").strip()
        if not nm or nm == "None":
            continue
        try:
            st = float(l.get("strength", 1.0))
        except Exception:
            st = 1.0
        clean_loras.append({"name": nm, "strength": st})
    prof = get_character_profile(character_name) or {}
    # Always write (even empty) -- otherwise a clear does not persist:
    # outfit_imagegen lives in config_json and is only transferred on save when
    # the key is PRESENT in the profile. A del leaves the old config value in
    # place. Empty workflow + no LoRAs = override deleted. ``model`` is dropped
    # (it comes from the workflow).
    if workflow or clean_loras:
        prof["outfit_imagegen"] = {"workflow": workflow, "loras": clean_loras}
    else:
        prof["outfit_imagegen"] = {}
    save_character_profile(character_name, prof)
    return {"status": "ok", "workflow": workflow, "loras": clean_loras}


def build_slot_overrides(character_name: str) -> Dict[str, Any]:
    """Returns per-slot prompt+LoRA overrides (9 slots).

    Structure: {slot: {prompt: str, lora: {name, strength}}}.
    They only take effect when the slot is empty and not covered.
    """
    from app.models.character import get_character_profile
    from app.models.inventory import VALID_PIECE_SLOTS
    prof = get_character_profile(character_name) or {}
    raw = prof.get("slot_overrides") or {}
    if not isinstance(raw, dict):
        raw = {}
    out: Dict[str, Any] = {}
    for slot in VALID_PIECE_SLOTS:
        entry = raw.get(slot) or {}
        if not isinstance(entry, dict):
            entry = {}
        lora = entry.get("lora") or {}
        if not isinstance(lora, dict):
            lora = {}
        out[slot] = {
            "prompt": (entry.get("prompt") or "").strip(),
            "lora": {
                "name": (lora.get("name") or "").strip(),
                "strength": float(lora.get("strength", 1.0) or 1.0),
            },
        }
    return {"slots": out, "order": list(VALID_PIECE_SLOTS)}


def apply_slot_overrides(character_name: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """Saves per-slot prompt+LoRA overrides.

    Body: {slots: {slot: {prompt: str, lora: {name, strength}}}}.
    Empty entries (no prompt + no LoRA) are removed.
    """
    from app.models.character import get_character_profile, save_character_profile
    from app.models.inventory import VALID_PIECE_SLOTS
    slots_in = body.get("slots") or {}
    if not isinstance(slots_in, dict):
        slots_in = {}
    cleaned: Dict[str, Any] = {}
    for slot in VALID_PIECE_SLOTS:
        entry = slots_in.get(slot) or {}
        if not isinstance(entry, dict):
            continue
        prompt = (entry.get("prompt") or "").strip()
        lora_raw = entry.get("lora") or {}
        lora_name = ""
        lora_strength = 1.0
        if isinstance(lora_raw, dict):
            lora_name = (lora_raw.get("name") or "").strip()
            if lora_name.lower() == "none":
                lora_name = ""
            try:
                lora_strength = float(lora_raw.get("strength", 1.0))
            except Exception:
                lora_strength = 1.0
        if not prompt and not lora_name:
            continue
        out: Dict[str, Any] = {}
        if prompt:
            out["prompt"] = prompt
        if lora_name:
            out["lora"] = {"name": lora_name, "strength": lora_strength}
        cleaned[slot] = out
    prof = get_character_profile(character_name) or {}
    if cleaned:
        prof["slot_overrides"] = cleaned
    elif "slot_overrides" in prof:
        del prof["slot_overrides"]
    save_character_profile(character_name, prof)
    return {"status": "ok", "slots": cleaned}


def apply_videogen_config(character_name: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Saves the VideoGen config (ImageGen + animation settings)."""
    from app.models.character import get_character_skill_config, save_character_skill_config
    user_id = data.get("user_id", "").strip()

    config = get_character_skill_config(character_name, "video_generation") or {}

    # ImageGen fields
    for key in ("imagegen_backend", "imagegen_workflow", "imagegen_model", "animate_service"):
        if key in data:
            config[key] = str(data[key]).strip()

    # Normalize LoRA lists
    def _normalize_loras(loras):
        if not loras:
            return []
        out = []
        for l in loras:
            name = (l.get("name") or "").strip() or "None"
            try:
                strength = float(l.get("strength", 1.0))
            except (TypeError, ValueError):
                strength = 1.0
            out.append({"name": name, "strength": strength})
        return out

    for key in ("imagegen_loras",):
        if key in data:
            config[key] = _normalize_loras(data[key])

    save_character_skill_config(character_name, "video_generation", config)
    return {"status": "success"}


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

    # mode == "apply": run the migration

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
    from app.models.account import set_current_character
    from app.models.character import (list_available_characters,
                                      save_character_profile, get_character_config,
                                      save_character_config, save_character_skill_config)
    data = await request.json()
    character_name = data.get("character_name", "").strip()
    template_name = data.get("template", "human-default")
    if not character_name:
        raise HTTPException(status_code=400, detail="character_name fehlt")
    # Catch reserved / problematic names -- e.g. "undefined" or "null" appear
    # when some JS code fails to initialize a value and then string-converts
    # it. That must not create a character folder.
    if character_name.lower() in ("undefined", "null", "none", "nan"):
        raise HTTPException(status_code=400,
            detail=f"'{character_name}' ist als Character-Name nicht erlaubt")

    # Check if character already exists
    existing = list_available_characters()
    if character_name in existing:
        raise HTTPException(status_code=409, detail=f"Character '{character_name}' existiert bereits")

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
        logger.warning("create_character: known_locations init fehlgeschlagen: %s", _e)

    # Write skill defaults -- without these files the ALWAYS_LOAD filter logic
    # (skill_manager._get_agent_skills) kicks in and turns all skills off by
    # default. With the default list the fresh char has the usual repertoire
    # right away (chat, set_location, consume magic, outfit change, ...).
    for _sid in DEFAULT_NEW_CHARACTER_SKILLS:
        try:
            save_character_skill_config(character_name, _sid, {"enabled": True})
        except Exception as _e:
            logger.warning("create_character: skill-default '%s' nicht gesetzt: %s",
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
                    "create_character: konnte allowed_characters fuer "
                    "user=%s nicht aktualisieren: %s",
                    creator.get("username"), e,
                )

    # Set as current character
    set_current_character(character_name)

    return {
        "status": "success",
        "character": character_name,
        "template": template_name,
        "message": f"Character '{character_name}' erstellt"
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
