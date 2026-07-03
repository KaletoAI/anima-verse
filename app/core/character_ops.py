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
