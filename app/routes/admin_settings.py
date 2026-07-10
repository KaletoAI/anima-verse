"""Admin Settings Routes — JSON-based configuration management."""
import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Query
from fastapi.responses import HTMLResponse
from typing import Any, Dict, List
import httpx

from app.core.log import get_logger
from app.core import config
from app.core.config_schema import get_schema
from app.core.auth_dependency import require_admin

from app.core.timeutils import parse_iso, utc_now, utc_now_iso

logger = get_logger("admin_settings")

router = APIRouter(prefix="/admin", tags=["admin-settings"],
                   dependencies=[Depends(require_admin)])


# ── API Endpoints ──

@router.get("/settings", response_class=HTMLResponse)
async def settings_page():
    """Serve the admin settings HTML page."""
    return HTMLResponse(
        content=_build_settings_html(),
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"})


@router.get("/world-name")
async def world_name(user=Depends(require_admin)):
    """Return the active world name (= storage dir basename) so the admin
    UI can display which world it's actually configuring. Prevents the
    "I just saved Hotopia data into anima-dome" footgun where a stale
    browser tab carries form state across world boundaries.
    """
    from app.core.paths import get_storage_dir
    return {"world": get_storage_dir().name}


@router.get("/users", response_class=HTMLResponse)
async def users_page():
    """Serve the user-management HTML page."""
    return HTMLResponse(
        content=_build_users_html(),
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@router.get("/llm-stats", response_class=HTMLResponse)
async def llm_stats_page():
    """Serve the LLM-Stats admin HTML page (read-only Auswertung)."""
    return HTMLResponse(
        content=_build_llm_stats_html(),
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@router.get("/llm-stats/data")
async def llm_stats_data(
    request: Request,
    user=Depends(require_admin)):
    """Aggregierte LLM-Call-Statistik fuer den Admin-Stats-Tab.

    Query-Parameter:
        from, to     : ISO-Timestamps (inklusiv). Default: letzte 24h.
        agents       : komma-separierte Liste von agent_name. Default: alle.
        group_by_agent : "1" = pro (task, model, provider, agent),
                         sonst (default) = pro (task, model, provider).
        task         : optionaler Task-Filter (Substring-Match).

    Response:
        {
            "from": iso, "to": iso,
            "agents": [alle distinct agent_names im Zeitraum],
            "rows": [{
                task, model, provider, agent_name,
                calls, avg_duration, min_duration, max_duration, p90_duration,
                avg_in_tokens, avg_out_tokens, avg_total_tokens,
                max_in_tokens, max_total_tokens, avg_max_tokens
            }, ...]
        }
    """
    from datetime import datetime, timedelta
    from app.core.db import get_connection

    qp = request.query_params
    to_str = qp.get("to") or ""
    from_str = qp.get("from") or ""
    if not to_str:
        to_str = utc_now_iso()
    if not from_str:
        # Default-Fenster: letzte 24h
        try:
            to_dt = parse_iso(to_str)
        except Exception:
            to_dt = utc_now()
        from_str = (to_dt - timedelta(hours=24)).isoformat(timespec="seconds")

    agents_raw = (qp.get("agents") or "").strip()
    selected_agents = [a.strip() for a in agents_raw.split(",") if a.strip()] if agents_raw else []
    group_by_agent = qp.get("group_by_agent") in ("1", "true", "yes", "on")
    task_filter = (qp.get("task") or "").strip().lower()

    conn = get_connection()

    where = ["ts >= ?", "ts <= ?"]
    params: list = [from_str, to_str]
    if selected_agents:
        placeholders = ",".join(["?"] * len(selected_agents))
        where.append(f"agent_name IN ({placeholders})")
        params.extend(selected_agents)

    sql = (
        "SELECT task, model, provider, agent_name, "
        "       in_tokens, out_tokens, max_tokens, duration_s "
        "FROM llm_call_stats "
        f"WHERE {' AND '.join(where)} "
        "ORDER BY ts DESC "
        "LIMIT 100000"
    )
    cur = conn.execute(sql, params)
    raw_rows = cur.fetchall()

    # Distinct agents im Zeitraum (fuer Filter-Dropdown). Wir lesen das
    # immer ungefiltert, damit der User auch nach Filter-Wechsel die
    # vollstaendige Liste sieht.
    agents_sql = (
        "SELECT DISTINCT agent_name FROM llm_call_stats "
        "WHERE ts >= ? AND ts <= ? AND agent_name != '' "
        "ORDER BY agent_name COLLATE NOCASE"
    )
    agents_cur = conn.execute(agents_sql, [from_str, to_str])
    agents_list = [r[0] for r in agents_cur.fetchall()]

    # Aggregation in Python — flexibel + p90 ohne Window-Functions.
    buckets: Dict[tuple, Dict[str, list]] = {}
    for r in raw_rows:
        task, model, provider, agent, in_tok, out_tok, max_tok, dur = r
        if task_filter and task_filter not in (task or "").lower():
            continue
        if group_by_agent:
            key = (task, model, provider or "", agent or "")
        else:
            key = (task, model, provider or "", "")
        b = buckets.setdefault(key, {
            "durations": [], "in_tokens": [], "out_tokens": [],
            "max_tokens": [],
        })
        b["durations"].append(float(dur))
        b["in_tokens"].append(int(in_tok))
        b["out_tokens"].append(int(out_tok))
        if max_tok:
            b["max_tokens"].append(int(max_tok))

    def _p90(vals: list) -> float:
        if not vals:
            return 0.0
        s = sorted(vals)
        idx = max(0, int(len(s) * 0.9) - 1)
        return s[min(idx, len(s) - 1)]

    rows_out = []
    for (task, model, provider, agent), b in buckets.items():
        durs = b["durations"]
        ins = b["in_tokens"]
        outs = b["out_tokens"]
        mxs = b["max_tokens"]
        n = len(durs)
        totals = [a + bb for a, bb in zip(ins, outs)]
        rows_out.append({
            "task": task,
            "model": model,
            "provider": provider,
            "agent_name": agent,
            "calls": n,
            "avg_duration": round(sum(durs) / n, 2) if n else 0.0,
            "min_duration": round(min(durs), 2) if n else 0.0,
            "max_duration": round(max(durs), 2) if n else 0.0,
            "p90_duration": round(_p90(durs), 2),
            "avg_in_tokens": int(sum(ins) / n) if n else 0,
            "avg_out_tokens": int(sum(outs) / n) if n else 0,
            "avg_total_tokens": int(sum(totals) / n) if n else 0,
            "max_in_tokens": max(ins) if ins else 0,
            "max_total_tokens": max(totals) if totals else 0,
            "avg_max_tokens": int(sum(mxs) / len(mxs)) if mxs else 0,
        })

    rows_out.sort(key=lambda x: (-x["calls"], x["task"], x["model"]))

    return {
        "from": from_str,
        "to": to_str,
        "agents": agents_list,
        "group_by_agent": group_by_agent,
        "rows": rows_out,
    }


# Prompt-Block-Keys, die ein Filter gezielt unterdruecken kann — entspricht den
# *_block ctx-Keys in app/core/thought_context.py.
_PROMPT_FILTER_BLOCK_KEYS = [
    "inbox_block", "events_block", "assignments_block", "general_task",
    "commitments_block", "outfit_decision_block", "arc_block",
    "retrospective_block", "skill_context_blocks", "effects_block",
    "recent_chat_block", "outfit_self_block", "outfit_avatar_block",
    "room_items_block", "inventory_block", "present_people_block",
    "activity_hint_block", "daily_schedule_block",
]


def _skill_block_package_ids() -> List[str]:
    """Package ids of loaded skills that contribute a ``thought_context_block``
    — the targets for fine-grained ``skill:<pkg>`` drop-block addressing."""
    try:
        from app.core.dependencies import get_skill_manager
        from app.skills.base import BaseSkill
        from app.plugins.registry import package_of_skill
    except Exception:
        return []
    ids: List[str] = []
    seen: set = set()
    for skill in getattr(get_skill_manager(), "skills", []):
        try:
            if type(skill).thought_context_block is BaseSkill.thought_context_block:
                continue  # not overridden → no contribution
            sid = getattr(skill, "SKILL_ID", "") or ""
            pkg = package_of_skill(sid)
            pid = pkg.id if pkg else sid
            if pid and pid not in seen:
                seen.add(pid)
                ids.append(pid)
        except Exception:
            continue
    return ids


def _prompt_filter_block_keys() -> List[str]:
    """Static block keys + dynamic ``skill:<pkg>`` entries (one per loaded
    package that contributes a thought_context_block)."""
    return _PROMPT_FILTER_BLOCK_KEYS + [f"skill:{pid}"
                                        for pid in _skill_block_package_ids()]


@router.get("/prompt-filters/data")
async def prompt_filters_data(user=Depends(require_admin)):
    """Liste der gemergten Prompt-Filter (shared baseline + world overlay).

    Jeder Eintrag bekommt ein ``source``-Feld: "shared" / "world".
    Wenn dieselbe id in beiden vorkommt, gewinnt world (overlay) und
    source="world override".
    """
    from app.core.prompt_filters import _load_shared, _load_world

    shared = {(e.get("id") or "").strip(): e
              for e in _load_shared() if e.get("id")}
    world = {(e.get("id") or "").strip(): e
             for e in _load_world() if e.get("id")}

    # Condition-Referenzen mit DENSELBEN Resolvern wie die Live-Evaluierung pruefen.
    from app.core.activity_engine import validate_condition_references

    out = []
    seen_ids = set()

    def _finish(entry: Dict[str, Any]) -> Dict[str, Any]:
        entry["warnings"] = validate_condition_references(entry.get("condition") or "")
        return entry

    for fid, e in shared.items():
        if fid in world:
            entry = dict(world[fid])
            entry["source"] = "world override"
        else:
            entry = dict(e)
            entry["source"] = "shared"
        seen_ids.add(fid)
        out.append(_finish(entry))
    for fid, e in world.items():
        if fid in seen_ids:
            continue
        entry = dict(e)
        entry["source"] = "world"
        out.append(_finish(entry))

    return {
        "filters": out,
        "block_keys": _prompt_filter_block_keys(),
        "condition_hint": (
            "Filter id ALWAYS triggers when present as a tag in the profile (apply_condition). "
            "condition:<this-id> is therefore redundant here. This expression triggers ADDITIONALLY:\n"
            "Status: stamina>N, courage<N, stress>N, lust>N\n"
            "Time: alone, night, day\n"
            "Presence: present:Name (same room as Name)\n"
            "Relationship: relationship:Name>N, romantic:Name>N (Name or 'any')\n"
            "Mood: mood:happy\n"
            "Other condition: condition:<tag>\n"
            "Current activity: current_activity:cooking\n"
            "Daily schedule: schedule:sleeping, schedule:awake, schedule:<activity>\n"
            "Item: has_item:<item-id> (real id, not the example)\n"
            "Combination: AND / OR / NOT"
        ),
    }


@router.get("/prompt-filters/validate")
async def prompt_filters_validate(condition: str = "", user=Depends(require_admin)):
    """Live-Validierung einer Condition fuer den Editor — nutzt EXAKT dieselbe
    Funktion wie die Laufzeit-Pruefung (keine Frontend-Regex-Duplikate)."""
    from app.core.activity_engine import validate_condition_references
    return {"warnings": validate_condition_references(condition or "")}


# Kontextsensitive Editor-Hilfe (eine Quelle fuer das ausklappbare Help-Panel im
# Game-Admin). Pro Feld/Kontext ein Topic-Key; der Editor setzt ihn beim Fokus.
_HELP_TOPICS: Dict[str, Dict[str, Any]] = {
    "condition": {
        "title": "Condition syntax",
        "intro": "Filter id triggers via the profile tag (condition:<this-id> is redundant). This expression triggers ADDITIONALLY:",
        "items": [
            # __STATS__ / Stat-Werte werden im Endpoint dynamisch aus den
            # Character-Templates befuellt (Stats sind NICHT hartkodiert).
            {"code": "__STATS__", "text": "Status values (from the character template, e.g. stat>N / <N / =N)"},
            {"code": "__FLAGS__", "text": "State flags (declared by skill packages; true while set)"},
            {"code": "gender=male, template!=human-roleplay", "text": "Profile field equals / differs (string compare, any top-level profile field)"},
            {"code": "is_male, is_female", "text": "Shorthand for gender=male / gender=female"},
            {"code": "alone, night, day", "text": "Time / presence (day/night accept +/-minutes)"},
            {"code": "present:Name", "text": "Name is in the same room"},
            {"code": "npc_present", "text": "Any non-avatar character is here"},
            {"code": "relationship:Name>N, romantic:Name>N", "text": "Name or 'any'"},
            {"code": "mood:happy", "text": "Current mood"},
            {"code": "condition:<tag>", "text": "Another active condition tag"},
            {"code": "current_activity:cooking", "text": "Current activity"},
            {"code": "schedule:sleeping / awake / <activity>", "text": "Daily schedule"},
            {"code": "has_item:<item-id>", "text": "Character owns the item (real id)"},
            {"code": "room_has_item:<item-id>", "text": "The current room contains the item"},
            {"code": "has_secret", "text": "Character has an unrevealed secret"},
            {"code": "AND / OR / NOT", "text": "Combine expressions"},
        ],
    },
    "image_modifier": {
        "title": "Image modifier",
        "intro": "One directive per line — applied to the person description in EVERY image type (scene, character, profile/expression) while the state is active:",
        "items": [
            {"code": "flushed cheeks, glassy eyes", "text": "Plain text: appended to the description"},
            {"code": "neat hair -> messy tousled hair", "text": "Replacement: rewrites a matching fragment of the description (case-insensitive; '→' works too). Works on body-slot fragments as well"},
        ],
    },
    "romantic_interests": {
        "title": "Romantic interests",
        "intro": "Free text. When the attraction package is installed it is matched against OTHER characters' appearance to gate romantic potential. Understood cues:",
        "items": [
            # Filled dynamically from the attraction package's provider; this
            # fallback shows when no attraction package is installed.
            {"text": "Any free text works. Install the attraction package to enable preference matching against appearance/anatomy."},
        ],
    },
    "prompt_modifier": {
        "title": "Prompt modifier placeholders",
        "intro": "Text added to the character's prompt when the filter triggers. Placeholders:",
        "items": [
            {"code": "{avatar}", "text": "The world avatar (player-controlled character)."},
            {"code": "{giver}", "text": "Who handed over the item that applied this condition (source_character); falls back to the avatar."},
        ],
    },
    "imagegen_target": {
        "title": "Render target (match)",
        "intro": "A match glob resolving to an image backend (by availability + cost):",
        "items": [
            {"code": "LocalAI-Flux", "text": "A specific image backend (exact name or glob)"},
            {"code": "*", "text": "Any available backend"},
        ],
    },
    "image_prompt": {
        "title": "Image prompt",
        "intro": "Describes the scene to render. HOW you phrase it depends on the use-case's image family (not copied — these are styles, not tokens):",
        "items": [
            {"code": "natural", "copy": False, "text": "Flowing prose / full sentences — for Flux / Qwen."},
            {"code": "keywords", "copy": False, "text": "Comma-separated tags — for Z-Image / SD."},
            {"text": "Style and negative prompts come from the use-case, not from this field."},
        ],
    },
    "effects_syntax": {
        "title": "Effects",
        "intro": "One effect per line. Applied when the item is consumed:",
        "items": [
            {"code": "__STAT_CHANGES__", "text": "Change a template stat by +/- value"},
            {"code": "mood_influence: happy", "text": "Nudge the mood"},
            {"code": "apply_condition: charmed", "text": "Set a condition tag (filter id)"},
            {"code": "condition_duration_hours: 2", "text": "How long that condition lasts before it expires"},
        ],
    },
    "schedule_detail": {
        "title": "Trigger detail",
        "intro": "Meaning depends on the chosen trigger:",
        "items": [
            {"code": "30", "text": "Interval / delay in minutes"},
            {"code": "03:00", "text": "Daily time (HH:MM)"},
        ],
    },
    "llm_task": {
        "title": "LLM task",
        "intro": "Routing key — maps to a provider+model under LLM Routing.",
        "items": [
            {"code": "chat, tools, summarize, vision", "text": "Common task keys"},
        ],
    },
}


@router.get("/help-topics")
async def help_topics(user=Depends(require_admin)):
    """Hilfe-Themen fuers kontextsensitive Help-Panel (eine Quelle, kein Frontend-Duplikat).

    Der ``__STATS__``-Platzhalter im condition-Topic wird mit den echten Stat-Keys
    aus den Character-Templates der Welt befuellt — die Stats sind nicht hartkodiert
    und koennen pro Welt/Template variieren.
    """
    import copy as _copy
    topics = _copy.deepcopy(_HELP_TOPICS)
    try:
        from app.core.stat_hints import get_all_stat_keys
        keys = get_all_stat_keys()
        stat_code = ", ".join(f"{k}>N" for k in keys[:6]) if keys else "stat>N (e.g. stamina>50)"
        change_code = ", ".join(f"{k}_change: +N" for k in keys[:4]) if keys else "stat_change: +/-N"
        repl = {"__STATS__": stat_code, "__STAT_CHANGES__": change_code}
        try:
            from app.plugins.registry import flag_specs
            _flags = sorted({s.flag for s in flag_specs()} | {"is_sleeping"})
            repl["__FLAGS__"] = ", ".join(_flags[:8]) if _flags else "is_sleeping"
        except Exception:
            repl["__FLAGS__"] = "is_sleeping"
        for topic in topics.values():
            for it in topic.get("items", []):
                if it.get("code") in repl:
                    it["code"] = repl[it["code"]]
    except Exception as _se:
        logger.debug("Dynamische Stat-Keys fuer Help-Topics fehlgeschlagen: %s", _se)
    # Romantic-interests help: filled by the attraction package's provider
    # (package-aware — anatomy phrases only when those packages are loaded).
    try:
        from app.core.hooks import get_provider
        fn = get_provider("romantic_interests_help")
        if fn is not None and "romantic_interests" in topics:
            items = fn()
            if items:
                topics["romantic_interests"]["items"] = items
    except Exception as _re:
        logger.debug("romantic_interests help provider failed: %s", _re)
    return {"topics": topics}


@router.post("/prompt-filters/save")
async def prompt_filters_save(request: Request, user=Depends(require_admin)):
    """Upsert eines Filters in die per-world prompt_filters-Tabelle.

    Body: {id, condition, label, drop_blocks: [...], prompt_modifier,
           icon, image_modifier, enabled}.
    Wenn die id auch in shared/prompt_filters/filters.json existiert, ist das
    ein Override. Sonst wird ein neuer world-only Filter angelegt.
    """
    import json as _json
    from app.core.db import transaction

    body = await request.json()
    fid = (body.get("id") or "").strip()
    condition = (body.get("condition") or "").strip()
    label = (body.get("label") or "").strip()
    drop_blocks = body.get("drop_blocks") or []
    prompt_modifier = (body.get("prompt_modifier") or "").strip()
    icon = (body.get("icon") or "").strip()
    image_modifier = (body.get("image_modifier") or "").strip()
    enabled = bool(body.get("enabled", True))

    if not fid:
        raise HTTPException(status_code=400, detail="id required")
    # condition ist im neuen Modell optional — Filter-id triggert
    # implizit ueber den Profil-Tag, condition ist nur ein zusaetzlicher
    # Stat-/Composite-Trigger.
    if not isinstance(drop_blocks, list):
        raise HTTPException(status_code=400,
                             detail="drop_blocks must be a list")
    valid = set(_prompt_filter_block_keys())
    drop_blocks = [b for b in drop_blocks if b in valid]

    with transaction() as conn:
        conn.execute("""
            INSERT INTO prompt_filters (id, condition, label, drop_blocks,
                                        prompt_modifier, enabled, meta,
                                        icon, image_modifier)
            VALUES (?, ?, ?, ?, ?, ?, '{}', ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                condition=excluded.condition,
                label=excluded.label,
                drop_blocks=excluded.drop_blocks,
                prompt_modifier=excluded.prompt_modifier,
                enabled=excluded.enabled,
                icon=excluded.icon,
                image_modifier=excluded.image_modifier
        """, (fid, condition, label,
              _json.dumps(drop_blocks, ensure_ascii=False),
              prompt_modifier, 1 if enabled else 0,
              icon, image_modifier))
    return {"status": "ok", "id": fid}


@router.delete("/prompt-filters/{filter_id}")
async def prompt_filters_delete(filter_id: str, user=Depends(require_admin)):
    """Entfernt den world-overlay-Eintrag fuer diese id.

    Wenn dieselbe id auch im shared baseline existiert, wird damit der
    Override aufgehoben — der baseline-Filter greift wieder. Wenn die id
    nur in world existierte, ist der Filter danach komplett weg.
    """
    from app.core.db import transaction

    with transaction() as conn:
        conn.execute("DELETE FROM prompt_filters WHERE id=?", (filter_id,))
    return {"status": "ok", "id": filter_id}


@router.post("/prompt-filters/{filter_id}/move")
async def prompt_filters_move(filter_id: str, request: Request, user=Depends(require_admin)):
    """Move a prompt-filter between shared baseline and world overlay.

    Body: ``{"target": "shared"|"world"}``.

    target=shared:
      - read the current effective filter (world override wins over shared)
      - write it to ``shared/prompt_filters/filters.json``, replacing the
        existing entry with that id (or appending)
      - delete the world overlay row so the shared entry is now the
        canonical version

    target=world:
      - read the current effective filter (typically from shared)
      - write it as a world overlay row (so it can be edited per-world
        without touching the shared baseline)
      - the shared entry stays put; the world row simply shadows it
    """
    import json as _json
    from app.core.db import transaction
    from app.core.prompt_filters import _load_shared, _load_world, _SHARED_FILE

    body = await request.json()
    target = (body.get("target") or "").strip().lower()
    if target not in ("shared", "world"):
        raise HTTPException(status_code=400, detail="target must be 'shared' or 'world'")

    # Resolve the canonical filter to move — world override wins over shared.
    world = {(e.get("id") or "").strip(): e for e in _load_world() if e.get("id")}
    shared = {(e.get("id") or "").strip(): e for e in _load_shared() if e.get("id")}
    src = world.get(filter_id) or shared.get(filter_id)
    if not src:
        raise HTTPException(status_code=404, detail="filter not found")

    # Stripping internal-only keys keeps both stores tidy.
    clean = {k: v for k, v in src.items() if k not in ("source", "_origin", "meta")}

    if target == "shared":
        _SHARED_FILE.parent.mkdir(parents=True, exist_ok=True)
        try:
            existing = _json.loads(_SHARED_FILE.read_text(encoding="utf-8")) if _SHARED_FILE.exists() else {}
        except Exception:
            existing = {}
        filters = list(existing.get("filters") or [])
        replaced = False
        for i, f in enumerate(filters):
            if (f.get("id") or "").strip() == filter_id:
                filters[i] = clean
                replaced = True
                break
        if not replaced:
            filters.append(clean)
        _SHARED_FILE.write_text(
            _json.dumps({"filters": filters}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        with transaction() as conn:
            conn.execute("DELETE FROM prompt_filters WHERE id=?", (filter_id,))
        return {"status": "ok", "id": filter_id, "target": "shared"}

    # target == "world": upsert the resolved filter into the world overlay.
    drops = clean.get("drop_blocks") or []
    with transaction() as conn:
        conn.execute(
            """
            INSERT INTO prompt_filters (id, condition, label, drop_blocks,
                                        prompt_modifier, enabled, meta,
                                        icon, image_modifier)
            VALUES (?, ?, ?, ?, ?, ?, '{}', ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                condition=excluded.condition,
                label=excluded.label,
                drop_blocks=excluded.drop_blocks,
                prompt_modifier=excluded.prompt_modifier,
                enabled=excluded.enabled,
                icon=excluded.icon,
                image_modifier=excluded.image_modifier
            """,
            (
                filter_id,
                (clean.get("condition") or "").strip(),
                (clean.get("label") or "").strip(),
                _json.dumps(drops if isinstance(drops, list) else [], ensure_ascii=False),
                (clean.get("prompt_modifier") or "").strip(),
                1 if clean.get("enabled", True) else 0,
                (clean.get("icon") or "").strip(),
                (clean.get("image_modifier") or "").strip(),
            ),
        )
    return {"status": "ok", "id": filter_id, "target": "world"}


# ── States (prompt-filters block) Import / Export ──

@router.get("/prompt-filters/export")
async def prompt_filters_export(user=Depends(require_admin)):
    """Stream the world-level prompt-filters block as a ZIP."""
    import io as _io
    from fastapi.responses import StreamingResponse
    from app.core.content_io import export_states_to_zip
    zip_bytes = export_states_to_zip()
    return StreamingResponse(
        _io.BytesIO(zip_bytes),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="states.zip"'},
    )


@router.post("/prompt-filters/import")
async def prompt_filters_import(
    file: UploadFile = File(...),
    replace_all: bool = Query(False, description="Wipe existing world filters first"),
    user=Depends(require_admin),
):
    """Import a states ZIP. Default merges; replace_all=true wipes first."""
    from app.core.content_io import import_states_from_zip
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Only ZIP files are allowed")
    content = await file.read()
    try:
        return import_states_from_zip(content, replace_all=replace_all)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/settings/data")
async def settings_data(user=Depends(require_admin)):
    """Return full config with sensitive fields masked.

    Empty fields are pre-filled with their schema default so the user
    immediately sees which fallback value applies.
    """
    import copy
    data = copy.deepcopy(config.get_all())
    _apply_schema_defaults(data)
    return config.mask_sensitive(data)


@router.get("/settings/raw")
async def settings_raw(user=Depends(require_admin)):
    """Return full config without masking (for save round-trip).

    Empty fields are pre-filled with their schema default so the admin UI
    immediately shows what value would apply if left untouched.
    """
    import copy
    data = copy.deepcopy(config.get_all())
    _apply_schema_defaults(data)
    return data


@router.post("/settings/lora-library/clear-discovered")
async def lora_library_clear_discovered(user=Depends(require_admin)):
    """Removes every discovered entry from the LoRA library (manual entries
    stay). Reset helper — e.g. to re-test the per-backend LoRA filter with a
    clean discovery run. Persists server-side so a following sync works on
    the cleared state."""
    data = config.get_all()
    ig = data.setdefault("image_generation", {})
    triggers = ig.get("lora_triggers") or []
    kept = [e for e in triggers
            if not (isinstance(e, dict) and (e.get("source") or "") == "discovered")]
    removed = len(triggers) - len(kept)
    if removed:
        ig["lora_triggers"] = kept
        config.save(data)
    return {"removed": removed, "lora_triggers": kept}


@router.post("/settings/lora-library/sync")
async def lora_library_sync(user=Depends(require_admin)):
    """Runs LoRA discovery against every backend with a LoRA listing and
    reconciles the library (add discovered / flag manual missing / drop
    vanished untouched discoveries). Returns the updated library so the
    editor can refresh in place."""
    import asyncio
    from app.core.lora_library import sync_lora_library
    result = await asyncio.to_thread(sync_lora_library)
    result["lora_triggers"] = config.get("image_generation.lora_triggers", []) or []
    return result


def _diff_top_level_sections(current: dict, merged: dict) -> list:
    """Liefert die Top-Level-Schluessel, deren Inhalt sich zwischen
    current und merged geaendert hat. JSON-Vergleich, weil sub-arrays/dicts
    beliebig verschachtelt sein koennen.
    """
    import json
    keys = set(current.keys()) | set(merged.keys())
    changed = []
    for k in keys:
        if json.dumps(current.get(k), sort_keys=True, default=str) != \
           json.dumps(merged.get(k), sort_keys=True, default=str):
            changed.append(k)
    return sorted(changed)


def _apply_section_reloads(changed_keys: list) -> list:
    """Ruft punktuell die zur jeweiligen Sektion passenden Reload-Funktionen
    auf. Errors werden geloggt, aber nie geworfen — Save selbst bleibt erfolgreich.

    Returns: Liste der tatsaechlich getriggerten Reload-Labels fuer das UI.
    """
    if not changed_keys:
        return []

    from app.core.log import get_logger as _gl
    _log = _gl("admin_settings")
    triggered = []

    def _run(label: str, fn):
        try:
            fn()
            triggered.append(label)
            _log.info("settings_save: reloaded '%s' (trigger: %s)", label, changed_keys)
        except Exception as e:
            _log.warning("settings_save: reload '%s' failed: %s", label, e)

    # Provider manager: providers + image_generation (image backends get
    # their own channels, so both sections affect the channel setup).
    if "providers" in changed_keys or "image_generation" in changed_keys:
        from app.core.provider_manager import reload_provider_manager
        _run("providers", reload_provider_manager)

    # Skill-Manager: skills + image_generation (Image-Skill liest Backends
    # aus os.environ-Bloecken, die nur beim Skill-Init gelesen werden).
    if "skills" in changed_keys or "image_generation" in changed_keys:
        from app.core.dependencies import _skill_manager
        if _skill_manager is not None:
            _run("skills", _skill_manager.reload_skills)

    # TTS-Service.
    if "tts" in changed_keys:
        from app.core.tts_service import reload_tts_service
        _run("tts", reload_tts_service)

    # Video backends live in image_generation.backends now, so the image
    # service reload above (image_generation changed_keys) covers them — no
    # separate animation hook anymore.

    return triggered


@router.post("/settings/save")
async def settings_save(request: Request, user=Depends(require_admin)):
    """Save config. Fields with masked values (***...) are kept from current config."""
    new_data = await request.json()

    # Merge: keep current values for masked sensitive fields
    current = config.get_all()
    merged = _merge_sensitive(new_data, current)
    # Protect fields in sub_array/is_dict items (e.g. image backends) that the
    # frontend omits on save when the CONFIG value is undefined.
    _preserve_unsent_subarray_fields(merged, current)

    # Structural validation (e.g. llm_routing order uniqueness)
    err = _validate_llm_routing(merged.get("llm_routing"))
    if err:
        raise HTTPException(status_code=400, detail=err)

    # Diagnose: was kommt im llm_routing wirklich an?
    try:
        _routing_in = merged.get("llm_routing") or []
        _task_log = []
        for _e in _routing_in:
            if not isinstance(_e, dict):
                continue
            for _t in (_e.get("tasks") or []):
                if isinstance(_t, dict) and _t.get("task"):
                    _task_log.append(
                        f"{_t.get('task')}@{_t.get('order','?')}->"
                        f"{_e.get('provider','?')}/{_e.get('model','?')}")
        from app.core.log import get_logger as _gl
        _gl("admin_settings").info(
            "settings_save: llm_routing %d Eintraege, %d Task-Mappings: %s",
            len(_routing_in), len(_task_log), _task_log)
    except Exception:
        pass

    _autofill_imagegen_defaults(merged)

    # Diff VOR config.save berechnen — current spiegelt noch den Pre-Save-State.
    changed_sections = _diff_top_level_sections(current, merged)

    config.save(merged)
    # Env sofort aktualisieren — vermeidet Server-Restart-Pflicht fuer Felder
    # die ueber os.environ.get() gelesen werden.
    try:
        config._flatten_to_env(merged)
    except Exception as _ee:
        # Nicht hart fehlschlagen — Save selbst war erfolgreich.
        from app.core.log import get_logger as _gl
        _gl("admin_settings").warning("env-flatten after save failed: %s", _ee)

    # Punktuelle Service-Reloads basierend auf geaenderten Sektionen.
    # In Thread auslagern: einige Reloads pingen Provider/Backends synchron
    # (z.B. ImageBackend.check_availability) und wuerden sonst den Event-Loop
    # mehrere Sekunden blockieren.
    reloaded = await asyncio.to_thread(_apply_section_reloads, changed_sections)

    msg = "Configuration saved (env updated)."
    if reloaded:
        msg += " Reloaded: " + ", ".join(reloaded) + "."
    return {
        "status": "success",
        "message": msg,
        "changed_sections": changed_sections,
        "reloaded": reloaded,
    }


@router.get("/settings/llm-tasks")
async def settings_llm_tasks(user=Depends(require_admin)):
    """Liefert die Liste bekannter LLM-Task-Typen fuer den Admin-UI-Selector."""
    from app.core.llm_tasks import TASK_TYPES, CATEGORY_LABELS
    return [
        {
            "id": tid,
            "label": t.get("label", tid),
            "category": t.get("category", ""),
            "category_label": CATEGORY_LABELS.get(str(t.get("category", "")), ""),
            "thinking": bool(t.get("thinking")),
        }
        for tid, t in TASK_TYPES.items()
    ]


@router.get("/settings/llm-task-state")
async def llm_task_state_get(user=Depends(require_admin)):
    from app.core.llm_task_state import (
        disabled_tasks, runtime_disabled_tasks, get_presets)
    return {
        "disabled": disabled_tasks(),
        "runtime_disabled": runtime_disabled_tasks(),
        "presets": get_presets(),
    }


@router.post("/settings/llm-task-state/runtime-preset")
async def llm_task_state_runtime_preset(request: Request, user=Depends(require_admin)):
    """Aktiviert ein Preset als Runtime-Disable (nicht persistent)."""
    data = await request.json()
    preset = (data.get("preset") or "").strip()
    from app.core.llm_task_state import activate_preset_runtime, clear_runtime
    if not preset or preset == "none":
        clear_runtime()
        return {"status": "cleared"}
    tasks = activate_preset_runtime(preset)
    return {"status": "ok", "preset": preset, "disabled": tasks}


def _autofill_imagegen_defaults(cfg: Dict[str, Any]) -> None:
    """When the user has at least one image-gen backend, fill empty
    outfit/expression/location default-backend fields with the first enabled
    backend. Does not overwrite existing selections."""
    img = cfg.get("image_generation") or {}
    backends = img.get("backends") or []
    if not isinstance(backends, list) or not backends:
        return
    chosen = next(
        (b.get("name") for b in backends
         if isinstance(b, dict) and b.get("enabled") and b.get("name")),
        None,
    ) or next(
        (b.get("name") for b in backends
         if isinstance(b, dict) and b.get("name")),
        None,
    )
    if not chosen:
        return
    target = chosen
    for field in ("outfit_imagegen_default",
                  "expression_imagegen_default",
                  "location_imagegen_default"):
        if not img.get(field):
            img[field] = target
    cfg["image_generation"] = img


def _validate_llm_routing(routing) -> str:
    """Prueft llm_routing: pro (task, order) darf es nur einen Eintrag geben.

    Returns leere String wenn OK, sonst Fehlermeldung.
    """
    if not isinstance(routing, list):
        return ""
    seen: dict = {}  # (task, order) -> entry_index
    for idx, entry in enumerate(routing):
        if not isinstance(entry, dict):
            continue
        # Disabled-Eintraege werden zur Laufzeit ignoriert -> auch
        # Order-Konflikte zwischen disabled+enabled sind erlaubt.
        if entry.get("enabled") is False:
            continue
        tasks = entry.get("tasks") or []
        if not isinstance(tasks, list):
            continue
        for t in tasks:
            if not isinstance(t, dict):
                continue
            task_id = t.get("task")
            order = t.get("order")
            if not task_id or order is None:
                continue
            key = (task_id, int(order))
            if key in seen:
                return (f"LLM Routing: task '{task_id}' mit order {order} "
                        f"ist doppelt (Eintrag #{seen[key]+1} und #{idx+1}).")
            seen[key] = idx
    return ""


@router.get("/settings/schema")
async def settings_schema(user=Depends(require_admin)):
    """Return field schema for UI rendering."""
    return get_schema()


@router.get("/settings/use-case-defaults")
async def settings_use_case_defaults(user=Depends(require_admin)):
    """Eingebaute Use-Case-Style-Defaults (pro use_case × Familie) — dienen in
    der Admin-UI als grauer Placeholder bei leerem Feld."""
    from app.core.config import _DEFAULT_IMAGE_USE_CASES, _PROMPT_STYLE_FAMILIES
    return {
        "use_cases": list(_DEFAULT_IMAGE_USE_CASES.keys()),
        "families": _PROMPT_STYLE_FAMILIES,
        "defaults": _DEFAULT_IMAGE_USE_CASES,
    }


@router.get("/settings/imagegen-targets")
async def imagegen_targets(user=Depends(require_admin)):
    """Returns the list of image-gen targets for admin selects (backends only).

    Format: [{"value": "CivitAI", "label": "...", "type": "backend", "available": True}, ...]
    """
    try:
        from app.core.dependencies import get_skill_manager
        from app.imagegen.service import get_image_service
        img = get_image_service()
        if not img.enabled:
            return {"targets": []}
    except Exception as e:
        return {"targets": [], "error": str(e)}

    out = []
    for b in img.backends:
        if not b.instance_enabled:
            continue
        # These selects pick IMAGE render targets — skip video backends.
        if getattr(b, "MEDIA_TYPE", "image") != "image":
            continue
        out.append({
            "value": b.name,
            "label": f"{b.name} ({b.api_type})",
            "type": "backend",
            "available": bool(b.available),
        })
    return {"targets": out}


@router.get("/templates/list")
async def templates_list(user=Depends(require_admin)):
    """List all .md files under shared/templates/llm/."""
    from app.core.template_preview import list_templates
    return {"templates": list_templates()}


@router.get("/templates/file")
async def templates_read(path: str, user=Depends(require_admin)):
    from app.core.template_preview import read_template
    try:
        return {"path": path, "content": read_template(path)}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Template not found: {path}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/templates/file")
async def templates_save(request: Request, user=Depends(require_admin)):
    body = await request.json()
    path = (body.get("path") or "").strip()
    content = body.get("content")
    if not path or content is None:
        raise HTTPException(status_code=400, detail="path + content required")
    from app.core.template_preview import save_template
    try:
        save_template(path, content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"status": "saved", "path": path}


@router.get("/templates/render")
async def templates_render(path: str, agent: str = "", avatar: str = "",
                           user=Depends(require_admin)):
    """Render the template at ``path`` against real production data for
    the given agent + avatar."""
    from app.core.template_preview import render_with_real_data
    return render_with_real_data(path, agent, avatar)


@router.get("/templates", response_class=HTMLResponse)
async def templates_page(user=Depends(require_admin)):
    """Template playground: top bar + 2-column editor/preview."""
    return _TEMPLATES_PAGE_HTML


_TEMPLATES_PAGE_HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Templates</title>
<link rel="stylesheet" href="/static/admin/templates.css">
</head>
<body>
<div class="topbar">
  <label>Template</label>
  <select id="sel-template"></select>
  <label>Avatar</label>
  <select id="sel-avatar"></select>
  <label>Agent</label>
  <select id="sel-agent"></select>
  <button id="btn-save" class="primary">Save</button>
  <button id="btn-render">Refresh preview</button>
  <span id="status">—</span>
</div>
<div class="cols">
  <div class="col">
    <div class="col-header">Edit (raw markdown)</div>
    <textarea id="editor" spellcheck="false" placeholder="Pick a template above…"></textarea>
  </div>
  <div class="col">
    <div class="col-header">Preview (real data, what production would build)</div>
    <pre class="preview" id="preview">—</pre>
    <div class="note" id="note">—</div>
  </div>
</div>

<script src="/static/admin/templates.js"></script>
</body>
</html>
"""


@router.get("/settings/imagegen-backends/{backend_name}/models")
async def imagegen_backend_models(backend_name: str,
                                  api_type: str = "", api_url: str = "", api_key: str = "",
                                  user=Depends(require_admin)):
    """Returns the model list for an image-generation backend (cloud).

    - Together / openai_diffusion / localai / openai_chat: live list via /v1/models
    - CivitAI: currently only the configured backend.model (no API listing)

    Optional query params (api_type/api_url/api_key) override the saved
    config — so the UI can load models right after entering a URL,
    without saving first.
    """
    img_gen = config.get("image_generation", {}) or {}
    backends = img_gen.get("backends", []) or []
    b = next((x for x in backends if x.get("name") == backend_name), None) or {}
    # Live form values take precedence, fallback = saved config.
    api_type = (api_type or b.get("api_type") or "").lower()
    api_key = api_key if api_key else b.get("api_key", "")
    api_url = (api_url or b.get("api_url") or "").rstrip("/")
    cur_model = b.get("model", "")
    if not api_url:
        return {"backend": backend_name, "models": [], "error": "Keine API URL"}
    models: list = []
    # Video backends want video models, image backends want image models.
    _want_type = "video" if api_type in ("localai_video", "together_video", "openai_video") else "image"
    try:
        if api_type in ("together", "openai_diffusion", "localai", "openai_chat",
                        "localai_video", "together_video", "openai_video"):
            base = api_url if api_url.endswith("/v1") else (api_url + "/v1")
            # api_key optional for localai/localai_video (LocalAI without auth);
            # gateway/Together need it
            _hdrs = {"Authorization": f"Bearer {api_key}"} if api_key else {}
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{base}/models", headers=_hdrs)
                if resp.status_code == 200:
                    data = resp.json()
                    items = data.get("data", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
                    for m in items:
                        if not isinstance(m, dict):
                            continue
                        # Keep models with the wanted type (or no declared type).
                        if m.get("type") and m.get("type") != _want_type:
                            continue
                        mid = m.get("id") or m.get("name")
                        if mid:
                            models.append(mid)
            models.sort()
        elif api_type == "civitai":
            # CivitAI has no useful model listing via API — return only the
            # configured AIR URN as the single option.
            if cur_model:
                models = [cur_model]
    except Exception as e:
        return {"backend": backend_name, "models": [], "error": str(e)}
    # Always include cur_model (even if it is not in the list)
    if cur_model and cur_model not in models:
        models.insert(0, cur_model)
    return {"backend": backend_name, "models": models, "current": cur_model}


@router.get("/settings/providers/{provider_name}/models")
async def provider_models(provider_name: str, user=Depends(require_admin)):
    """Fetch available models from a provider (live query).

    Reuses Provider.list_models(), so the SAME serverless/chat/vision filter as
    the rest of the app applies — non-serverless models (which cannot be invoked:
    'Unable to access non-serverless model') are excluded from the list.
    """
    from app.core.provider_manager import get_provider_manager
    provider = get_provider_manager().get_provider(provider_name)
    if not provider:
        raise HTTPException(404, f"Provider '{provider_name}' not found")
    try:
        # list_models() macht ggf. einen sync HTTP-Call (Cache-Miss/Refresh) →
        # in einen Thread auslagern, damit der Event-Loop frei bleibt.
        items = await asyncio.to_thread(provider.list_models, True)
        models = sorted({(m.get("name") or "") for m in (items or [])
                         if isinstance(m, dict) and m.get("name")})
        vision = sorted({(m.get("name") or "") for m in (items or [])
                         if isinstance(m, dict) and m.get("name") and m.get("vision")})
        return {"provider": provider_name, "models": models, "vision": vision}
    except Exception as e:
        return {"provider": provider_name, "models": [], "error": str(e)}


@router.get("/settings/providers-list")
async def providers_list(user=Depends(require_admin)):
    """Namen aller konfigurierten Provider — fuer den Suitability-Test-Picker."""
    return {"providers": [p.get("name", "") for p in config.get("providers", [])
                          if p.get("name")]}


@router.get("/settings/llm-suitability-checks")
async def llm_suitability_checks(user=Depends(require_admin)):
    """Metadaten der Eignungs-Checks (id/label/category) — fuer die UI-Vorschau."""
    from app.core.model_suitability import list_checks
    return {"checks": list_checks()}


@router.get("/settings/llm-suitability-cases")
async def llm_suitability_cases(user=Depends(require_admin)):
    """Info zum eingefrorenen Fixture-Satz (Anzahl Faelle, pro Task, Build-Zeit)."""
    from app.core.model_suitability import cases_info
    return cases_info()


@router.post("/settings/llm-suitability-cases/rebuild")
async def llm_suitability_cases_rebuild(user=Depends(require_admin)):
    """Extrahiert den Fixture-Satz neu aus logs/llm_calls.jsonl."""
    from app.core.model_suitability import build_cases_from_log
    return await asyncio.to_thread(build_cases_from_log)


@router.post("/settings/llm-suitability-test/start")
async def llm_suitability_test_start(request: Request, user=Depends(require_admin)):
    """Startet den Eignungstest fuer EIN Modell asynchron im Hintergrund und gibt
    den initialen Status zurueck. Fortschritt/Ergebnis via .../status pollen.
    Das Gesamtergebnis wird am Ende in model_capabilities.json gespeichert."""
    from app.core.model_suitability import start_test
    body = await request.json()
    provider = str((body or {}).get("provider") or "").strip()
    model = str((body or {}).get("model") or "").strip()
    if not model:
        raise HTTPException(400, "model required")
    full = f"{provider}::{model}" if provider else model
    return start_test(full)


@router.get("/settings/llm-suitability-test/status")
async def llm_suitability_test_status(provider: str = "", model: str = "",
                                      user=Depends(require_admin)):
    """Aktueller Status/Fortschritt eines (laufenden oder fertigen) Tests."""
    from app.core.model_suitability import get_job
    if not model:
        raise HTTPException(400, "model required")
    full = f"{provider}::{model}" if provider else model
    job = get_job(full)
    return job or {"model": full, "status": "idle"}


@router.get("/settings/llm-suitability-test/jobs")
async def llm_suitability_test_jobs(user=Depends(require_admin)):
    """Alle bekannten Test-Jobs (laufend/fertig/fehler) — fuer die 'laufende
    Tests'-Liste. Ohne Check-Details (nur Kurzstatus)."""
    from app.core.model_suitability import list_jobs
    jobs = []
    for j in list_jobs():
        s = j.get("summary") or {}
        jobs.append({
            "model": j.get("model", ""),
            "status": j.get("status", ""),
            "done": j.get("done", 0),
            "total": j.get("total", 0),
            "score": s.get("score", ""),
            "verdict": s.get("verdict") or {},
        })
    return {"jobs": jobs}


@router.post("/settings/validate")
async def settings_validate(request: Request, user=Depends(require_admin)):
    """Validate config and return list of issues."""
    from app.core.config_validator import validate_config
    data = await request.json()
    issues = validate_config(data)
    return {"issues": issues, "errors": sum(1 for i in issues if i["level"] == "error"), "warnings": sum(1 for i in issues if i["level"] == "warning")}


@router.get("/settings/restart-pending")
async def settings_restart_pending(user=Depends(require_admin)):
    """Liste der Felder, die seit dem letzten Server-Start veraendert wurden
    und nur durch einen Restart wirksam werden.
    """
    return {"pending": config.restart_pending_fields()}


@router.post("/settings/memory-consolidate")
async def settings_memory_consolidate(request: Request, user=Depends(require_admin)):
    """Triggert Memory-Konsolidierung sofort.

    Body (alles optional):
      - character: Wenn gesetzt, NUR fuer diesen Character. Sonst: alle.
      - phase2_iterations: Wieviel mal Phase 2 hintereinander pro Character laufen
        soll (Default 1). Pro Iteration werden bis zu 3 Tage Episodics
        konsolidiert. Hilfreich um grosse Backlogs in einem Rutsch abzubauen.
    """
    body = await request.json() if request.headers.get('content-type','').startswith('application/json') else {}
    character = (body.get('character') or '').strip()
    iterations = max(1, min(20, int(body.get('phase2_iterations', 1))))

    from app.core.background_queue import get_background_queue
    from app.models.character import list_available_characters

    targets = [character] if character else list_available_characters()
    bq = get_background_queue()
    submitted = 0
    for ch in targets:
        for _ in range(iterations):
            bq.submit(
                task_type="memory_consolidation",
                payload={"character_name": ch},
                priority=30,
                agent_name=ch,
                deduplicate=False)  # explizit kein dedup damit alle iter laufen
            submitted += 1
    return {"status": "success", "submitted": submitted, "characters": len(targets), "iterations": iterations}


# ── Image Post-Processing (Downscale Migration) ───────────────────────

def _format_bytes(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    if n < 1024 * 1024 * 1024:
        return f"{n / (1024 * 1024):.1f} MB"
    return f"{n / (1024 * 1024 * 1024):.2f} GB"


def _summarize_migrate(result: dict) -> dict:
    """Add human-readable byte sizes to the result for the admin UI."""
    if not result.get("ok"):
        return result
    enriched = dict(result)
    enriched["bytes_before_human"] = _format_bytes(result["bytes_before"])
    enriched["bytes_after_human"] = _format_bytes(result["bytes_after"])
    enriched["bytes_saved_human"] = _format_bytes(result["bytes_saved"])
    if result["bytes_before"]:
        enriched["saved_pct"] = round(
            100 * result["bytes_saved"] / result["bytes_before"], 1)
    else:
        enriched["saved_pct"] = 0
    by_bucket = enriched.get("by_bucket") or {}
    for name, b in by_bucket.items():
        b["bytes_before_human"] = _format_bytes(b["bytes_before"])
        b["bytes_after_human"] = _format_bytes(b["bytes_after"])
        b["bytes_saved"] = b["bytes_before"] - b["bytes_after"]
        b["bytes_saved_human"] = _format_bytes(b["bytes_saved"])
    return enriched


def _parse_world_scope(request: Request) -> str:
    """Read optional ?world_scope=current|all (default current).

    Items ignore this — they live in shared/ and are cross-world by design.
    """
    raw = (request.query_params.get("world_scope") or "current").strip().lower()
    if raw not in ("current", "all"):
        raise HTTPException(
            status_code=400,
            detail="world_scope must be 'current' or 'all'")
    return raw


@router.post("/image-postprocess/dryrun")
async def image_postprocess_dryrun(request: Request, user=Depends(require_admin)):
    """Scan items or map-tagged gallery images without writing.

    Query:
      * ``scope=item|map``                   — what to scan
      * ``world_scope=current|all`` (map only) — default current world only
    Returns per-bucket and totals: files scanned/resized + estimated bytes saved.
    Map scope only walks gallery images whose ``image_type=="map"``;
    location backgrounds are ignored.
    """
    scope = (request.query_params.get("scope") or "").strip().lower()
    if scope not in ("item", "map"):
        raise HTTPException(status_code=400, detail="scope must be item or map")
    world_scope = _parse_world_scope(request)
    from app.core.image_postprocess import migrate_tree
    result = migrate_tree(scope, dry_run=True, world_scope=world_scope)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "scan failed"))
    return _summarize_migrate(result)


@router.post("/image-postprocess/migrate")
async def image_postprocess_migrate(request: Request, user=Depends(require_admin)):
    """Re-encode images in place. Destructive — originals are not kept.

    Query:
      * ``scope=item|map``
      * ``world_scope=current|all`` (map only) — default current world only
    """
    scope = (request.query_params.get("scope") or "").strip().lower()
    if scope not in ("item", "map"):
        raise HTTPException(status_code=400, detail="scope must be item or map")
    world_scope = _parse_world_scope(request)
    from app.core.image_postprocess import migrate_tree
    result = migrate_tree(scope, dry_run=False, world_scope=world_scope)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "migration failed"))
    return _summarize_migrate(result)


# ── Agent Loop ────────────────────────────────────────────────────────

@router.get("/agent-loop/status")
async def agent_loop_status(user=Depends(require_admin)):
    """Return AgentLoop status for the admin panel.

    Mirrors ``AgentLoop.status()``: running, paused, current agent,
    remaining round, recent turns. Pause source is the task_queue
    'default' pause flag (DB-persistent across restarts).
    """
    from app.core.agent_loop import get_agent_loop
    return get_agent_loop().status()


@router.post("/agent-loop/pause")
async def agent_loop_pause(user=Depends(require_admin)):
    """Pause the AgentLoop (and the task_queue 'default' it shares).

    The pause is persistent — survives restart because it lives in the
    world DB via ``task_queue._is_paused``.
    """
    from app.core.task_queue import get_task_queue
    tq = get_task_queue()
    if tq:
        tq.pause_queue("default")
    return {"status": "paused"}


@router.post("/agent-loop/resume")
async def agent_loop_resume(user=Depends(require_admin)):
    """Resume the AgentLoop."""
    from app.core.task_queue import get_task_queue
    tq = get_task_queue()
    if tq:
        tq.resume_queue("default")
    return {"status": "running"}


@router.post("/agent-loop/bump")
async def agent_loop_bump(request: Request, user=Depends(require_admin)):
    """Manually bump a character — they think on the next slot.

    Body: {"character": "<name>"}
    Useful for debugging / forcing immediate attention without forced_thoughts.
    """
    body = await request.json()
    name = (body.get("character") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="character required")
    from app.core.agent_loop import get_agent_loop
    ok = get_agent_loop().bump(name)
    return {"status": "queued" if ok else "skipped", "character": name}


@router.get("/agent-loop", response_class=HTMLResponse)
async def agent_loop_page(user=Depends(require_admin)):
    """Minimal HTML panel for the AgentLoop: status + pause toggle + recent turns."""
    from fastapi.responses import HTMLResponse as _HTMLResp
    return _HTMLResp(_AGENT_LOOP_HTML, headers={"Cache-Control": "no-store, no-cache, must-revalidate"})


_AGENT_LOOP_HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Agent Loop</title>
<link rel="stylesheet" href="/static/admin/agent-loop.css">
</head>
<body>
<h1>Agent Loop</h1>
<div class="bar">
  <button id="btn-pause" onclick="togglePause()">Pause</button>
  <span id="status-label" class="label">loading…</span>
</div>

<div class="section">
  <h2>Current</h2>
  <div class="data" id="current">—</div>
</div>

<div class="section">
  <h2>Bump (priority)</h2>
  <div id="bumped" class="data">—</div>
</div>

<div class="section">
  <h2>Round (remaining)</h2>
  <div id="round" class="data">—</div>
</div>

<div class="section recent">
  <h2>Recent turns</h2>
  <table id="recent-table"><thead><tr><th>Agent</th><th>Started</th><th>Dur</th><th>Outcome</th><th>Tools / Intents</th><th>Preview</th></tr></thead><tbody></tbody></table>
</div>

<script src="/static/admin/agent-loop.js"></script>
</body>
</html>
"""


def _apply_schema_defaults(data: dict) -> None:
    """Prefills empty config fields with their schema defaults.

    Iterates over SECTIONS from config_schema and fills missing or empty
    values whenever a 'default' is defined — so the admin user immediately
    sees which fallback would be active.
    """
    schema = get_schema()
    for section_key, section_def in schema.items():
        # Virtual sections (e.g. llm_simple) have no config field of their
        # own — don't create one, or an empty {} lands in config.json.
        if section_def.get("virtual"):
            continue
        is_array = section_def.get("is_array", False)
        fields = section_def.get("fields", {})
        # sub_arrays (e.g. image_generation.backends): fill defaults on each
        # item, honoring applicable_for/visible_when so type-specific fields
        # don't get materialized on items they never render for.
        for sub_key, sub_def in (section_def.get("sub_arrays") or {}).items():
            sub_fields = (sub_def or {}).get("fields", {})
            section_data = data.get(section_key)
            items = section_data.get(sub_key) if isinstance(section_data, dict) else None
            if sub_fields and isinstance(items, list):
                for item in items:
                    if isinstance(item, dict):
                        _fill_item_defaults(item, sub_fields)
        if is_array:
            items = data.get(section_key)
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                _fill_defaults(item, fields)
                for nested_key, nested_def in fields.items():
                    if isinstance(nested_def, dict) and nested_def.get("is_array"):
                        nested_items = item.get(nested_key)
                        if isinstance(nested_items, list):
                            nested_fields = nested_def.get("item_fields", {})
                            for ni in nested_items:
                                if isinstance(ni, dict):
                                    _fill_defaults(ni, nested_fields)
        else:
            section_data = data.get(section_key)
            if not isinstance(section_data, dict):
                # Section fehlt oder ist None → frisch anlegen, NICHT in Top-Level
                # droppen (das wuerde die Schema-Felder ausserhalb ihrer Section
                # ablegen, das Frontend rendert sie dann gar nicht oder crasht).
                section_data = {}
                data[section_key] = section_data
            _fill_defaults(section_data, fields)


def _fill_item_defaults(item: dict, fields: dict) -> None:
    """Like _fill_defaults, but skips fields the item never renders:
    `applicable_for` mismatching the item's api_type, and `visible_when`
    conditions on sibling values (evaluated in field order, so a default
    filled earlier — e.g. category='generate' — gates later fields).
    Placeholder-type fields are never materialized (_PLACEHOLDER_TYPES)."""
    for key, field_def in fields.items():
        if not isinstance(field_def, dict):
            continue
        if field_def.get("type") in _PLACEHOLDER_TYPES:
            continue
        applicable = field_def.get("applicable_for")
        if applicable and (item.get("api_type") or "") not in applicable:
            continue
        cond = field_def.get("visible_when")
        if isinstance(cond, dict) and any(
                (item.get(k) or "") != v for k, v in cond.items()):
            continue
        default = field_def.get("default")
        if default is None:
            continue
        current = item.get(key)
        if current is None or current == "":
            item[key] = default
            logger.debug("Config-Default gesetzt (item): %s = %r", key, default)


# Field types whose default is shown GREYED as a placeholder in the empty
# field instead of being materialized (user directive 2026-07-06, like the
# use-case styles editor): writing the default in would persist it on save
# and freeze future built-in updates. Bool/select cannot display a
# placeholder and keep real default values.
_PLACEHOLDER_TYPES = {"str", "text", "int", "float", "number"}


def _fill_defaults(obj: dict, fields: dict) -> None:
    """Sets missing/empty values in obj to the field default (bool/select
    only — see _PLACEHOLDER_TYPES) and clears legacy-default leftovers."""
    for key, field_def in fields.items():
        if not isinstance(field_def, dict):
            continue
        current = obj.get(key)
        # Legacy cleanup: a stored value that is just an old shipped default
        # (persisted by the former prefill) counts as "not customized" —
        # clear it so the placeholder + current built-in apply again.
        legacy = field_def.get("legacy_defaults")
        if legacy and isinstance(current, str) and current.strip() in legacy:
            obj[key] = ""
            continue
        if field_def.get("type") in _PLACEHOLDER_TYPES:
            continue
        default = field_def.get("default")
        if default is None:
            continue
        if current is None or current == "":
            obj[key] = default
            logger.debug("Config-Default gesetzt: %s = %r", key, default)


def _preserve_unsent_subarray_fields(merged: dict, current: dict) -> None:
    """Bewahrt Schema-Felder in sub_array/is_dict-Items, wenn der Payload sie
    weglaesst.

    Frontend-Bug: `setVal()` aktualisiert CONFIG nur bei `onchange`. Wenn ein
    Feld vor dem ersten Edit undefined ist (z.B. weil ein neues Schema-Feld
    in einer alten Welt-Config noch fehlt) und der User es nie anfasst,
    bleibt CONFIG undefined → JSON.stringify laesst den Key weg →
    `_merge_sensitive` wertet den fehlenden Key als 'absichtlich geloescht'.

    We walk all schema `sub_arrays` (e.g. image_generation.backends) and
    carry missing fields over from the current config.
    """
    schema = get_schema()
    for sec_key, sec_def in schema.items():
        sub_arrays = sec_def.get("sub_arrays") or {}
        if not sub_arrays:
            continue
        cur_sec = current.get(sec_key)
        new_sec = merged.get(sec_key)
        if not isinstance(cur_sec, dict) or not isinstance(new_sec, dict):
            continue
        for sub_key, sub_def in sub_arrays.items():
            field_keys = list((sub_def.get("fields") or {}).keys())
            if not field_keys:
                continue
            cur_sub = cur_sec.get(sub_key)
            new_sub = new_sec.get(sub_key)
            if cur_sub is None or new_sub is None:
                continue
            if sub_def.get("is_dict"):
                if not isinstance(cur_sub, dict) or not isinstance(new_sub, dict):
                    continue
                for item_id, new_item in new_sub.items():
                    cur_item = cur_sub.get(item_id)
                    if not isinstance(cur_item, dict) or not isinstance(new_item, dict):
                        continue
                    for f in field_keys:
                        if f not in new_item and f in cur_item:
                            new_item[f] = cur_item[f]
            else:
                if not isinstance(cur_sub, list) or not isinstance(new_sub, list):
                    continue
                for i, new_item in enumerate(new_sub):
                    if i >= len(cur_sub):
                        break
                    cur_item = cur_sub[i]
                    if not isinstance(cur_item, dict) or not isinstance(new_item, dict):
                        continue
                    for f in field_keys:
                        if f not in new_item and f in cur_item:
                            new_item[f] = cur_item[f]


def _merge_sensitive(new: Any, current: Any) -> Any:
    """Recursively merge, keeping current values where new has masked placeholders.

    WICHTIG: Keys die im neuen Dict FEHLEN wurden bewusst geloescht und
    werden NICHT aus current wiederhergestellt. Nur bei Leaf-Werten mit
    '***'-Maskierung greift der Sensitive-Schutz.
    """
    if isinstance(new, dict) and isinstance(current, dict):
        result = {}
        # Nur Keys aus new uebernehmen — fehlende Keys = geloescht.
        for key in new:
            if key in current:
                result[key] = _merge_sensitive(new[key], current[key])
            else:
                result[key] = new[key]
        return result
    if isinstance(new, list) and isinstance(current, list):
        return [
            _merge_sensitive(new[i], current[i]) if i < len(current) else new[i]
            for i in range(len(new))
        ]
    # If new value is a masked placeholder, keep current
    if isinstance(new, str) and new.startswith("***"):
        return current
    return new


def _build_settings_html() -> str:
    """Build the complete admin settings HTML page."""
    return '''<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Admin Settings</title>
<link rel="stylesheet" href="/static/admin/settings.css">
</head>
<body>

<nav class="sidebar">
    <h1>Admin</h1>
    <div id="world-badge" style="margin: 4px 0 12px 8px; padding: 4px 8px; background:#1f3a5f; color:#79c0ff; font-size:12px; border-radius:4px; display:inline-block;">world: <span id="world-name">…</span></div>
    <div class="nav-section-label">Server-Einstellungen</div>
    <div id="nav-links"></div>
    <div class="nav-section-label">Verwaltung</div>
    <a href="#" data-section="_users" onclick="event.preventDefault(); activateIframe('_users', '/admin/users', 'User-Verwaltung')"><span class="nav-icon">👥</span> User-Verwaltung</a>
    <a href="#" data-section="_models" onclick="event.preventDefault(); activateIframe('_models', '/admin/models', 'Model Capabilities')"><span class="nav-icon">🧩</span> Model Capabilities</a>
    <a href="#" data-section="_agent_loop" onclick="event.preventDefault(); activateIframe('_agent_loop', '/admin/agent-loop', 'Agent Loop')"><span class="nav-icon">🔄</span> Agent Loop</a>
    <a href="#" data-section="_templates" onclick="event.preventDefault(); activateIframe('_templates', '/admin/templates', 'LLM Templates')"><span class="nav-icon">📄</span> LLM Templates</a>
    <div class="nav-section-label">Logs & Monitoring</div>
    <a href="#" data-section="_dashboard" onclick="event.preventDefault(); activateIframe('_dashboard', '/dashboard', 'Dashboard')"><span class="nav-icon">📊</span> Dashboard</a>
    <a href="#" data-section="_llm_stats" onclick="event.preventDefault(); activateIframe('_llm_stats', '/admin/llm-stats', 'LLM Stats')"><span class="nav-icon">📈</span> LLM Stats</a>
    <a href="#" data-section="_llm_log" onclick="event.preventDefault(); activateIframe('_llm_log', '/logs/llm', 'LLM Log')"><span class="nav-icon">📝</span> LLM Log</a>
    <a href="#" data-section="_image_log" onclick="event.preventDefault(); activateIframe('_image_log', '/logs/image-prompts', 'Image Prompt Log')"><span class="nav-icon">🖼</span> Image Prompt Log</a>
</nav>

<div class="main">
    <div id="restart-banner" class="restart-banner" style="display:none;">
        <strong>Server restart required</strong> — the following settings changed since the server started and only take effect after a restart:
        <span id="restart-banner-fields"></span>
    </div>
    <div class="toolbar" id="settings-toolbar">
        <button class="btn btn-primary" onclick="saveConfig()" id="btn-save">Save</button>
        <button class="btn" onclick="validateConfig()" id="btn-validate" style="border-color:#d29922; color:#d29922;">Validate</button>
        <span class="spacer"></span>
        <span id="status-msg" style="font-size: 12px; color: #8b949e;"></span>
    </div>
    <div class="content" id="content">
        <div class="loading"><div class="spinner"></div><p style="margin-top: 12px;">Loading configuration...</p></div>
    </div>
</div>

<div class="toast" id="toast"></div>

<script src="/static/admin/settings.js"></script>
</body>
</html>'''


def _build_users_html() -> str:
    """User management page (admin-only)."""
    return '''<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<title>User-Verwaltung</title>
<link rel="stylesheet" href="/static/admin/users.css">
</head>
<body>

<h1>User-Verwaltung</h1>
<div class="toolbar">
    <button class="btn btn-primary" onclick="openEdit(null)">+ Neuer User</button>
</div>

<table id="users-table">
    <thead>
        <tr><th>Benutzername</th><th>Rolle</th><th>Characters</th><th>Letzter Login</th><th></th></tr>
    </thead>
    <tbody id="users-tbody">
        <tr><td colspan="5" style="text-align:center;color:#8b949e;">Loading…</td></tr>
    </tbody>
</table>

<div class="modal-bg" id="modal-bg">
    <div class="modal">
        <h2 id="modal-title">User anlegen</h2>
        <div class="error-msg" id="modal-error"></div>
        <div class="field">
            <label>Benutzername</label>
            <input type="text" id="edit-username" autocomplete="off">
        </div>
        <div class="field">
            <label>Rolle</label>
            <select id="edit-role">
                <option value="user">User</option>
                <option value="admin">Admin</option>
            </select>
        </div>
        <div class="field">
            <label id="edit-password-label">Passwort</label>
            <input type="password" id="edit-password" autocomplete="new-password">
        </div>
        <div class="field">
            <label style="display:flex;align-items:center;gap:8px;">
                Zugeordnete Characters
                <button type="button" class="btn btn-sm" onclick="toggleAllChars(true)">Alle</button>
                <button type="button" class="btn btn-sm" onclick="toggleAllChars(false)">None</button>
            </label>
            <div class="chars-box" id="edit-chars-box"></div>
        </div>
        <div class="modal-actions">
            <button class="btn" onclick="closeEdit()">Cancel</button>
            <button class="btn btn-primary" onclick="saveEdit()">Save</button>
        </div>
    </div>
</div>

<div class="toast" id="toast"></div>

<script src="/static/admin/users.js"></script>
</body>
</html>'''


def _build_llm_stats_html() -> str:
    """LLM call statistics — read-only report with time-range/character filter."""
    return '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>LLM Stats</title>
<link rel="stylesheet" href="/static/admin/llm-stats.css">
</head>
<body>

<h1>LLM Call Statistik</h1>
<p class="hint">Aggregat aus <code>llm_call_stats</code>. Zeitraum + Character filterbar. Aufgeschluesselt nach Task x Model x Provider; mit Toggle auch nach Character.</p>

<div class="filter-bar">
    <div class="preset-row">
        <button class="btn" data-preset="1h" onclick="applyPreset('1h')">1h</button>
        <button class="btn" data-preset="24h" onclick="applyPreset('24h')">24h</button>
        <button class="btn" data-preset="7d" onclick="applyPreset('7d')">7d</button>
        <button class="btn" data-preset="30d" onclick="applyPreset('30d')">30d</button>
    </div>
    <label>From <input type="datetime-local" id="from-input"></label>
    <label>To <input type="datetime-local" id="to-input"></label>
    <label>Task <input type="text" id="task-filter" placeholder="substring..." style="width:140px;"></label>
    <label>Character
        <select id="agent-select" multiple size="3"></select>
    </label>
    <label><input type="checkbox" id="group-by-agent"> nach Character aufschluesseln</label>
    <button class="btn btn-primary" onclick="loadData()">Apply</button>
</div>

<div class="summary" id="summary"></div>
<div id="error-box"></div>

<table id="stats-table">
    <thead id="stats-thead"></thead>
    <tbody id="stats-tbody"><tr><td class="empty" colspan="20">Loading…</td></tr></tbody>
</table>

<script src="/static/admin/llm-stats.js"></script>
</body>
</html>'''


