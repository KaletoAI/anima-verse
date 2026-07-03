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
    "retrospective_block", "instagram_pending_block", "effects_block",
    "recent_chat_block", "outfit_self_block", "outfit_avatar_block",
    "room_items_block", "inventory_block", "present_people_block",
    "known_locations_block", "travel_block", "available_activities_block",
    "daily_schedule_block",
]


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
        "block_keys": _PROMPT_FILTER_BLOCK_KEYS,
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
            {"code": "backend:LocalAI-Flux", "text": "A specific image backend (exact name or glob after 'backend:')"},
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
        for topic in topics.values():
            for it in topic.get("items", []):
                if it.get("code") in repl:
                    it["code"] = repl[it["code"]]
    except Exception as _se:
        logger.debug("Dynamische Stat-Keys fuer Help-Topics fehlgeschlagen: %s", _se)
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
    valid = set(_PROMPT_FILTER_BLOCK_KEYS)
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

    Leere Felder werden mit Schema-Defaults vorbelegt, damit der User
    sofort sieht welcher Fallback-Wert greift.
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

    # Provider-Manager: providers + image_generation (Backends sind ueber
    # SKILL_IMAGEGEN_N_GPU_PROVIDER an Provider-GPUs gebunden).
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

    # Animation backends (together).
    if "animation" in changed_keys:
        from app.skills.animate import reload_animate_services
        _run("animation", reload_animate_services)

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
    target = f"backend:{chosen}"
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

    Format: [{"value": "backend:CivitAI", "label": "...", "type": "backend", "available": True}, ...]
    """
    try:
        from app.core.dependencies import get_skill_manager
        sm = get_skill_manager()
        img = sm.get_skill("image_generation")
        if not img:
            return {"targets": []}
    except Exception as e:
        return {"targets": [], "error": str(e)}

    out = []
    for b in img.backends:
        if not b.instance_enabled:
            continue
        out.append({
            "value": f"backend:{b.name}",
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
<style>
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; background:#0d1117; color:#c9d1d9; margin:0; padding:0; height:100vh; display:flex; flex-direction:column; }
.topbar { display:flex; gap:8px; align-items:center; padding:10px 14px; background:#161b22; border-bottom:1px solid #30363d; flex-wrap:wrap; }
.topbar select, .topbar button { background:#0d1117; color:#c9d1d9; border:1px solid #30363d; padding:6px 10px; border-radius:4px; font-size:12px; }
.topbar select { min-width:200px; }
.topbar button { cursor:pointer; }
.topbar button:hover { background:#21262d; }
.topbar button.primary { background:#238636; border-color:#238636; color:#fff; }
.topbar button.primary:hover { background:#2ea043; }
.topbar label { font-size:11px; color:#8b949e; }
#status { margin-left:auto; font-size:11px; color:#8b949e; }
#status.ok { color:#3fb950; }
#status.err { color:#f85149; }
.cols { flex:1; display:flex; min-height:0; }
.col { flex:1; display:flex; flex-direction:column; min-width:0; }
.col + .col { border-left:1px solid #30363d; }
.col-header { padding:6px 10px; background:#161b22; border-bottom:1px solid #30363d; font-size:11px; color:#8b949e; }
textarea, pre.preview { flex:1; margin:0; padding:10px; background:#0d1117; color:#c9d1d9; border:0; outline:0; font-family: ui-monospace, SFMono-Regular, monospace; font-size:12px; line-height:1.5; resize:none; white-space:pre-wrap; word-break:break-word; overflow:auto; }
textarea:focus { background:#010409; }
.note { padding:6px 10px; background:#161b22; border-top:1px solid #30363d; font-size:11px; color:#8b949e; }
.kind-chat { color:#58a6ff; }
.kind-tasks { color:#a5a5a5; }
.no-preview { opacity:0.5; }
</style>
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

<script>
let _state = { templates: [], characters: [], dirty: false };

function setStatus(msg, kind) {
  const el = document.getElementById('status');
  el.textContent = msg;
  el.className = kind || '';
}

async function loadTemplates() {
  const r = await fetch('/admin/templates/list');
  if (!r.ok) { setStatus('list failed: ' + r.status, 'err'); return; }
  const d = await r.json();
  _state.templates = d.templates || [];
  const sel = document.getElementById('sel-template');
  sel.innerHTML = '';
  let lastKind = '';
  for (const t of _state.templates) {
    if (t.kind !== lastKind) {
      const og = document.createElement('optgroup');
      og.label = t.kind;
      og.id = 'optgroup-' + t.kind;
      sel.appendChild(og);
      lastKind = t.kind;
    }
    const o = document.createElement('option');
    o.value = t.path;
    o.textContent = t.path.split('/').pop().replace('.md', '') + (t.has_preview ? '' : '  (no preview)');
    if (!t.has_preview) o.classList.add('no-preview');
    document.getElementById('optgroup-' + t.kind).appendChild(o);
  }
}

async function loadCharacters() {
  const r = await fetch('/characters/list');
  if (!r.ok) return;
  const d = await r.json();
  const chars = d.characters || [];
  const av = document.getElementById('sel-avatar');
  const ag = document.getElementById('sel-agent');
  av.innerHTML = '<option value="">(none)</option>';
  ag.innerHTML = '';
  for (const c of chars) {
    const oa = document.createElement('option'); oa.value = c; oa.textContent = c; av.appendChild(oa);
    const og = document.createElement('option'); og.value = c; og.textContent = c; ag.appendChild(og);
  }
  if (chars.length >= 2) av.value = chars[0];
  if (chars.length >= 1) ag.value = chars[chars.length >= 2 ? 1 : 0];
}

async function loadFile(path) {
  setStatus('loading…');
  try {
    const r = await fetch('/admin/templates/file?path=' + encodeURIComponent(path));
    if (!r.ok) throw new Error(await r.text());
    const d = await r.json();
    document.getElementById('editor').value = d.content || '';
    _state.dirty = false;
    setStatus('loaded', 'ok');
    await render();
  } catch (e) {
    setStatus('load failed: ' + e.message, 'err');
  }
}

async function saveFile() {
  const path = document.getElementById('sel-template').value;
  const content = document.getElementById('editor').value;
  if (!path) return;
  setStatus('saving…');
  try {
    const r = await fetch('/admin/templates/file', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path, content }),
    });
    if (!r.ok) throw new Error(await r.text());
    _state.dirty = false;
    setStatus('saved', 'ok');
    await render();
  } catch (e) {
    setStatus('save failed: ' + e.message, 'err');
  }
}

async function render() {
  const path = document.getElementById('sel-template').value;
  const avatar = document.getElementById('sel-avatar').value;
  const agent = document.getElementById('sel-agent').value;
  if (!path) return;
  setStatus('rendering…');
  try {
    const r = await fetch(`/admin/templates/render?path=${encodeURIComponent(path)}&agent=${encodeURIComponent(agent)}&avatar=${encodeURIComponent(avatar)}`);
    const d = await r.json();
    const prev = document.getElementById('preview');
    const note = document.getElementById('note');
    if (d.ok) {
      prev.textContent = d.output || '(empty)';
      note.textContent = d.note || '';
      setStatus('rendered', 'ok');
    } else {
      prev.textContent = '(no output)';
      note.textContent = d.note || 'preview failed';
      setStatus('preview failed', 'err');
    }
  } catch (e) {
    setStatus('render failed: ' + e.message, 'err');
  }
}

document.getElementById('sel-template').addEventListener('change', e => loadFile(e.target.value));
document.getElementById('sel-avatar').addEventListener('change', render);
document.getElementById('sel-agent').addEventListener('change', render);
document.getElementById('btn-save').addEventListener('click', saveFile);
document.getElementById('btn-render').addEventListener('click', render);
document.getElementById('editor').addEventListener('input', () => { _state.dirty = true; setStatus('unsaved changes'); });

(async () => {
  await Promise.all([loadTemplates(), loadCharacters()]);
  const sel = document.getElementById('sel-template');
  if (sel.options.length) {
    sel.value = sel.options[0].value;
    await loadFile(sel.value);
  }
})();
</script>
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
    try:
        if api_type in ("together", "openai_diffusion", "localai", "openai_chat"):
            base = api_url if api_url.endswith("/v1") else (api_url + "/v1")
            # api_key optional for localai (LocalAI without auth); gateway/Together need it
            _hdrs = {"Authorization": f"Bearer {api_key}"} if api_key else {}
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{base}/models", headers=_hdrs)
                if resp.status_code == 200:
                    data = resp.json()
                    items = data.get("data", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
                    for m in items:
                        if not isinstance(m, dict):
                            continue
                        if m.get("type") and m.get("type") != "image":
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
<style>
body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; background:#0d1117; color:#c9d1d9; margin:0; padding:20px; }
h1 { font-size:18px; margin-top:0; }
.bar { display:flex; gap:8px; align-items:center; margin-bottom:16px; padding:10px; background:#161b22; border:1px solid #30363d; border-radius:6px; }
.bar button { background:#238636; color:#fff; border:0; padding:6px 12px; border-radius:4px; cursor:pointer; font-size:13px; }
.bar button.paused { background:#da3633; }
.bar .label { color:#8b949e; font-size:12px; }
.section { margin-bottom:14px; padding:10px; background:#161b22; border:1px solid #30363d; border-radius:6px; }
.section h2 { font-size:13px; margin:0 0 6px; color:#58a6ff; }
.section .data { font-family: ui-monospace, SFMono-Regular, monospace; font-size:12px; color:#c9d1d9; white-space:pre-wrap; }
.recent table { width:100%; font-size:12px; border-collapse:collapse; }
.recent th, .recent td { text-align:left; padding:4px 6px; border-bottom:1px solid #21262d; vertical-align:top; }
.recent th { color:#8b949e; font-weight:500; }
.outcome-ok { color:#3fb950; }
.outcome-timeout { color:#d29922; }
.outcome-skip    { color:#6e7681; }
.outcome-err { color:#f85149; }
.tag { display:inline-block; padding:1px 6px; margin:1px 3px 1px 0; border-radius:3px; font-size:11px; background:#21262d; color:#8b949e; }
.tag.tool { background:#1f3a5f; color:#79c0ff; }
.tag.intent { background:#3a2f5f; color:#d2a8ff; }
.preview { color:#8b949e; font-style:italic; max-width:380px; word-break:break-word; }
.muted { color:#484f58; }
</style>
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

<script>
let _state = null;

let _loadCounter = 0;

async function load() {
  _loadCounter++;
  const lbl = document.getElementById('status-label');
  if (lbl && lbl.textContent === 'loading…') {
    lbl.textContent = 'fetching… (#' + _loadCounter + ')';
  }
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 8000);
  try {
    const r = await fetch('/admin/agent-loop/status', {
      signal: ctrl.signal,
      cache: 'no-store',
      credentials: 'same-origin',
    });
    clearTimeout(timer);
    if (!r.ok) {
      let body = '';
      try { body = (await r.text()).slice(0, 200); } catch(_) {}
      if (lbl) lbl.textContent = 'HTTP ' + r.status + (body ? ' — ' + body : '');
      return;
    }
    _state = await r.json();
    render();
  } catch(e) {
    clearTimeout(timer);
    if (lbl) lbl.textContent = (e.name === 'AbortError')
      ? "timeout — server didn't respond in 8s (call #" + _loadCounter + ")"
      : "error: " + e.message + " (call #" + _loadCounter + ")";
    console.error('[agent-loop load failed]', e);
  }
}

// Verifiziere dass der Script ueberhaupt laeuft — wenn 'loading…' nach 1s
// nicht ersetzt wurde, gab es einen Pre-Init-Error.
setTimeout(() => {
  const lbl = document.getElementById('status-label');
  if (lbl && lbl.textContent === 'loading…') {
    lbl.textContent = 'JS ran but fetch never started (check console)';
  }
}, 1500);

function render() {
  const s = _state || {};
  const btn = document.getElementById('btn-pause');
  const lbl = document.getElementById('status-label');
  if (s.paused) {
    btn.textContent = 'Resume';
    btn.classList.add('paused');
    lbl.textContent = 'PAUSED — Loop is sleeping. Persistent across restarts.';
  } else if (s.standby) {
    btn.textContent = 'Pause';
    btn.classList.remove('paused');
    lbl.textContent = "STANDBY — no 'thought' LLM reachable. Loop polls every 30s.";
  } else if (s.running) {
    btn.textContent = 'Pause';
    btn.classList.remove('paused');
    lbl.textContent = 'Running.';
  } else {
    btn.textContent = 'Pause';
    btn.classList.remove('paused');
    lbl.textContent = 'Loop not started.';
  }
  document.getElementById('current').textContent = s.current_agent || '(idle)';
  const bumped = s.bumped || [];
  document.getElementById('bumped').textContent = bumped.length ? bumped.join(' → ') : '(none)';
  const round = s.remaining_in_round || [];
  document.getElementById('round').textContent = round.length ? round.join(' → ') : '(round empty — refilling on next pick)';
  const tbody = document.querySelector('#recent-table tbody');
  tbody.innerHTML = '';
  for (const r of (s.recent || []).slice().reverse()) {
    const tr = document.createElement('tr');
    let cls = 'outcome-ok';
    if (r.outcome && r.outcome.startsWith('error')) cls = 'outcome-err';
    else if (r.outcome === 'timeout' || r.outcome === 'no_llm') cls = 'outcome-timeout';
    else if (r.outcome === 'in_chat_skip') cls = 'outcome-skip';
    const tools = (r.tools || []).map(t => `<span class="tag tool">${escapeHtml(t)}</span>`).join('');
    const intents = (r.intents || []).map(i => `<span class="tag intent">${escapeHtml(i)}</span>`).join('');
    const tagsCell = (tools + intents) || '<span class="muted">—</span>';
    // Link zum LLM Log: nur fuer Outcomes wo tatsaechlich ein LLM-Call lief.
    // Auto-Sleep / in_chat_skip / no_llm haben keinen Eintrag im LLM-Log.
    const _llmRanOutcomes = !(
      (r.outcome || '').startsWith('auto_sleep') ||
      r.outcome === 'in_chat_skip' || r.outcome === 'no_llm'
    );
    let logLink = '';
    if (_llmRanOutcomes && r.agent && r.started_at) {
      // Search-Filter: ISO-Format mit "T" + Minute des Turn-Starts (matcht
      // das Roh-Format in llm_calls.jsonl 'starttime'). Beispiel:
      // "2026-05-05T13:35". Der LLM-Log-Viewer liest die URL-Params, wendet
      // Filter an und auto-expanded den ersten Treffer.
      const tsMin = (r.started_at || '').slice(0, 16);
      const url = '/logs/llm?character=' + encodeURIComponent(r.agent)
                + '&search=' + encodeURIComponent(tsMin);
      // Wir versuchen die Admin-Sidebar-Navigation (parent.activateIframe) zu
      // nutzen — dann wird im Admin-Layout NUR der iframe-Inhalt getauscht
      // und Sidebar-Links bleiben erhalten. Fallback: direkte Navigation
      // (z.B. wenn Agent-Loop standalone geoeffnet wurde).
      const onclick = "event.preventDefault();"
        + " try { if (window.parent && window.parent.activateIframe) {"
        + " window.parent.activateIframe('_llm_log', '" + url + "', 'LLM Log'); return; } } catch(e) {}"
        + " window.location = '" + url + "';";
      logLink = ` <a href="${url}" onclick="${onclick}" title="Im LLM-Log oeffnen" style="margin-left:6px;text-decoration:none;color:#58a6ff;">🔍</a>`;
    }
    const preview = r.preview
      ? `<span class="preview">${escapeHtml(r.preview)}</span>${logLink}`
      : (logLink ? `<span class="muted">—</span>${logLink}` : '<span class="muted">—</span>');
    let startedShort = '';
    if (r.started_at) {
      const _d = new Date(r.started_at);
      startedShort = isNaN(_d.getTime()) ? r.started_at.replace('T', ' ').split('.')[0]
        : _d.toLocaleString('de-DE', {month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit'});
    }
    tr.innerHTML = `<td>${escapeHtml(r.agent)}</td><td>${escapeHtml(startedShort)}</td><td>${r.duration_s}s</td><td class="${cls}">${escapeHtml(r.outcome)}</td><td>${tagsCell}</td><td>${preview}</td>`;
    tbody.appendChild(tr);
  }
}

function escapeHtml(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }

async function togglePause() {
  const ep = (_state && _state.paused) ? '/admin/agent-loop/resume' : '/admin/agent-loop/pause';
  try { await fetch(ep, { method: 'POST' }); } catch(e) {}
  await load();
}

load();
setInterval(load, 5000);
</script>
</body>
</html>
"""


def _apply_schema_defaults(data: dict) -> None:
    """Fuellt leere Config-Felder mit Schema-Defaults vor.

    Iteriert ueber SECTIONS aus config_schema und traegt fehlende oder leere
    Werte ein, wenn ein 'default' definiert ist — damit der Admin-User sofort
    sieht, welcher Fallback aktiv waere.
    """
    schema = get_schema()
    for section_key, section_def in schema.items():
        # Virtuelle Sections (z.B. llm_simple) haben kein eigenes Config-Feld —
        # nicht anlegen, sonst landet ein leeres {} in config.json.
        if section_def.get("virtual"):
            continue
        is_array = section_def.get("is_array", False)
        fields = section_def.get("fields", {})
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


def _fill_defaults(obj: dict, fields: dict) -> None:
    """Setzt fehlende/leere Werte in obj auf den field-default."""
    for key, field_def in fields.items():
        if not isinstance(field_def, dict):
            continue
        default = field_def.get("default")
        if default is None:
            continue
        current = obj.get(key)
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
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #0d1117; color: #c9d1d9; display: flex; height: 100vh; overflow: hidden; }

/* ── Sidebar ── */
.sidebar {
    width: 220px; min-width: 220px; background: #161b22; border-right: 1px solid #30363d;
    overflow-y: auto; padding: 12px 0;
}
.sidebar h1 { font-size: 15px; padding: 8px 16px; color: #58a6ff; border-bottom: 1px solid #30363d; margin-bottom: 8px; }
.sidebar a {
    display: block; padding: 7px 16px; color: #8b949e; text-decoration: none;
    font-size: 13px; border-left: 3px solid transparent; transition: all 0.15s;
}
.sidebar a:hover { color: #c9d1d9; background: #1c2128; }
.sidebar a.active { color: #58a6ff; border-left-color: #58a6ff; background: #1c2128; }
.sidebar .nav-icon { margin-right: 6px; }
.sidebar a.nav-sub { padding: 5px 16px 5px 30px; font-size: 12px; }
.sidebar a.nav-sub .nav-icon { color: #6e7681; margin-right: 4px; }
.sidebar a.nav-sub.active .nav-icon { color: #58a6ff; }
.sidebar .nav-section-label {
    padding: 10px 16px 4px; margin-top: 10px; font-size: 11px; font-weight: 700;
    color: #8b949e; text-transform: uppercase; letter-spacing: 0.8px;
    border-top: 1px solid #30363d;
}
.sidebar .nav-section-label:first-of-type { margin-top: 4px; border-top: none; }

/* ── Main ── */
.main { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
.toolbar {
    background: #161b22; border-bottom: 1px solid #30363d;
    padding: 10px 20px; display: flex; gap: 10px; align-items: center;
}
.toolbar .spacer { flex: 1; }
.content { flex: 1; overflow-y: auto; padding: 20px; }

/* ── Restart Banner & Pill ── */
.restart-banner {
    background: #d2992222; border-bottom: 1px solid #d29922;
    color: #f0d97c; padding: 10px 20px; font-size: 13px; line-height: 1.5;
}
.restart-banner strong { color: #d29922; }
.restart-banner code {
    background: #0d1117; padding: 1px 6px; border-radius: 4px;
    font-size: 12px; color: #e6edf3; margin: 0 2px;
}
.restart-pill {
    display: inline-block; margin-left: 8px; padding: 1px 7px;
    border-radius: 10px; font-size: 10px; font-weight: 600;
    background: #d2992222; color: #d29922; border: 1px solid #d2992255;
    vertical-align: middle; text-transform: uppercase; letter-spacing: 0.4px;
}

/* ── Buttons ── */
.btn {
    background: #21262d; color: #c9d1d9; border: 1px solid #30363d;
    padding: 6px 14px; border-radius: 6px; cursor: pointer; font-size: 13px;
    display: inline-flex; align-items: center; gap: 4px;
}
.btn:hover { background: #30363d; }
.btn-primary { background: #238636; border-color: #2ea043; color: #fff; }
.btn-primary:hover { background: #2ea043; }
.btn-danger { background: #da3633; border-color: #f85149; color: #fff; }
.btn-danger:hover { background: #b62324; }
.btn-sm { padding: 4px 8px; font-size: 12px; }

/* ── Section ── */
.section { display: none; }
.section.active { display: block; }
.section-title { font-size: 18px; font-weight: 600; margin-bottom: 16px; color: #e6edf3; }
.subsection { margin: 16px 0; padding: 16px; background: #161b22; border: 1px solid #30363d; border-radius: 8px; }
.subsection-title { font-size: 14px; font-weight: 600; margin-bottom: 12px; color: #58a6ff; }

/* ── Form Fields ── */
.field { margin-bottom: 12px; display: flex; align-items: flex-start; gap: 12px; }
.field label { width: 180px; min-width: 180px; font-size: 13px; color: #8b949e; padding-top: 7px; text-align: right; }
.field .input-wrap { flex: 1; }
.field input[type="text"], .field input[type="number"], .field input[type="password"],
.field select, .field textarea {
    width: 100%; background: #0d1117; color: #c9d1d9; border: 1px solid #30363d;
    padding: 6px 10px; border-radius: 6px; font-size: 13px; font-family: inherit;
}
.field input:focus, .field select:focus, .field textarea:focus { border-color: #58a6ff; outline: none; }
.field textarea { min-height: 60px; resize: vertical; }
.field .desc { font-size: 11px; color: #6e7681; margin-top: 3px; }
.field input[type="checkbox"] { margin-top: 8px; }

/* Toggle for password */
.pw-wrap { position: relative; }
.pw-wrap input { padding-right: 36px; }
.pw-toggle {
    position: absolute; right: 8px; top: 50%; transform: translateY(-50%);
    background: none; border: none; color: #8b949e; cursor: pointer; font-size: 14px;
}

/* ── Array Items (Providers, Backends) ── */
.array-item {
    border: 1px solid #30363d; border-radius: 8px; margin-bottom: 12px;
    background: #0d1117;
}
.array-item-header {
    display: flex; align-items: center; padding: 8px 12px;
    background: #161b22; border-radius: 8px 8px 0 0; cursor: pointer;
    border-bottom: 1px solid #30363d;
}
.array-item-header .title { flex: 1; font-weight: 600; font-size: 13px; }
.array-item-header .badge { font-size: 11px; color: #8b949e; margin-right: 8px; }
.array-item-body { padding: 12px; display: none; }
.array-item.open .array-item-body { display: block; }
.array-item-header .chevron { transition: transform 0.2s; color: #8b949e; }
.array-item.open .array-item-header .chevron { transform: rotate(90deg); }

/* ── Master-detail (backends) ── */
.md-grid { display: grid; grid-template-columns: minmax(280px, 38%) 1fr; gap: 16px; align-items: start; }
.md-list { background: #0d1117; border: 1px solid #30363d; border-radius: 8px; padding: 8px; }
.md-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.md-table th { text-align: left; padding: 6px 8px; color: #8b949e; font-weight: 600;
    border-bottom: 1px solid #30363d; font-size: 11px; text-transform: uppercase; letter-spacing: .03em; }
.md-row { cursor: pointer; }
.md-row td { padding: 7px 8px; border-bottom: 1px solid #21262d; color: #c9d1d9; }
.md-row:hover td { background: #161b22; }
.md-row.active td { background: rgba(31,111,235,0.15); }
.md-row.active td:first-child { box-shadow: inset 2px 0 0 #58a6ff; font-weight: 600; }
.md-status.on { color: #3fb950; }
.md-status.off { color: #8b949e; }
.md-empty { color: #484f58; }
.md-detail { background: #0d1117; border: 1px solid #30363d; border-radius: 8px; padding: 14px; }
.md-detail-head { display: flex; align-items: center; margin-bottom: 12px; padding-bottom: 8px;
    border-bottom: 1px solid #30363d; }
.md-detail-title { font-weight: 600; font-size: 14px; color: #58a6ff; }
.md-empty-detail { color: #8b949e; padding: 28px 12px; text-align: center; }
@media (max-width: 900px) { .md-grid { grid-template-columns: 1fr; } }

/* ── LoRA-Trigger Editor: dark searchable combobox ── */
.lora-row input[type="text"] {
    background: #0d1117; color: #c9d1d9; border: 1px solid #30363d;
    padding: 6px 10px; border-radius: 6px; font-size: 13px; font-family: inherit;
}
.lora-row input[type="text"]:focus { border-color: #58a6ff; outline: none; }
.lt-combo { position: relative; }
.lt-dd {
    display: none; position: absolute; left: 0; right: 0; top: 100%; z-index: 50;
    margin-top: 2px; max-height: 240px; overflow-y: auto;
    background: #161b22; border: 1px solid #30363d; border-radius: 6px;
    box-shadow: 0 8px 24px rgba(0,0,0,0.5);
}
.lt-opt { padding: 6px 10px; font-size: 13px; color: #c9d1d9; cursor: pointer; white-space: nowrap;
    overflow: hidden; text-overflow: ellipsis; }
.lt-opt:hover, .lt-opt.active { background: rgba(31,111,235,0.18); }
.lt-dd-empty { padding: 6px 10px; font-size: 12px; color: #6e7681; }

/* LoRA rows */
.lora-row { display: flex; gap: 8px; margin-bottom: 6px; align-items: center; }
.lora-row input:first-child { flex: 3; }
.lora-row input:last-child { flex: 1; max-width: 80px; }

/* GPU rows */
.gpu-row { display: flex; gap: 8px; margin-bottom: 6px; align-items: center; }
.gpu-row input, .gpu-row select { flex: 1; }

/* ── Toast ── */
.toast {
    position: fixed; bottom: 20px; right: 20px; padding: 12px 20px;
    border-radius: 8px; font-size: 13px; z-index: 1000;
    opacity: 0; transition: opacity 0.3s; pointer-events: none;
}
.toast.show { opacity: 1; }
.toast.success { background: #238636; color: #fff; }
.toast.error { background: #da3633; color: #fff; }

/* ── Loading ── */
.loading { text-align: center; padding: 60px; color: #8b949e; }
.spinner { display: inline-block; width: 24px; height: 24px; border: 3px solid #30363d; border-top-color: #58a6ff; border-radius: 50%; animation: spin 0.8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

/* Status indicator */
.status-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 4px; }
.status-dot.on { background: #3fb950; }
.status-dot.off { background: #6e7681; }

/* Validation results */
.validate-results { margin: 16px 0; padding: 16px; background: #161b22; border: 1px solid #30363d; border-radius: 8px; }
.validate-results h3 { font-size: 14px; margin-bottom: 10px; }
.validate-results.has-errors h3 { color: #f85149; }
.validate-results.all-ok h3 { color: #3fb950; }
.validate-issue { padding: 6px 10px; margin: 4px 0; border-radius: 4px; font-size: 13px; display: flex; align-items: flex-start; gap: 8px; }
.validate-issue.error { background: #da363322; border-left: 3px solid #f85149; }
.validate-issue.warning { background: #d2992222; border-left: 3px solid #d29922; }
.validate-issue .badge { font-size: 11px; font-weight: 600; padding: 1px 6px; border-radius: 3px; white-space: nowrap; }
.validate-issue.error .badge { background: #da363344; color: #f85149; }
.validate-issue.warning .badge { background: #d2992244; color: #d29922; }
.validate-issue .section-link { color: #58a6ff; cursor: pointer; font-size: 12px; text-decoration: underline; margin-left: auto; white-space: nowrap; }

/* Embedded iframe for tool pages */
.content iframe { width: 100%; height: 100%; border: none; }
.content.iframe-mode { padding: 0; overflow: hidden; }
</style>
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

<script>
let CONFIG = {};
let SCHEMA = {};
let USE_CASE_DEFAULTS = { use_cases: [], families: [], defaults: {} };
let PROVIDERS_CACHE = {};
let PROVIDERS_VISION = {};  // provName -> Set(vision model names)
let ACTIVE_SECTION = null;
// Wenn ein Array-Item per User-Klick aufgeklappt wurde, halten wir den
// Pfad hier fest. So bleibt der Zustand ueber renderSection()-Rerenders
// (z.B. nach api_type-Wechsel via triggers_rerender) erhalten.
const OPEN_ITEMS = new Set();
// Master-Detail: pro Sub-Array-Pfad der aktuell ausgewaehlte Item-Pfad.
const SELECTED_ITEM = {};
function toggleArrayItem(el, path) {
    const isOpen = el.parentElement.classList.toggle('open');
    if (isOpen) OPEN_ITEMS.add(path);
    else OPEN_ITEMS.delete(path);
}

// ── Init ──
async function init() {
    try {
        const [dataResp, schemaResp] = await Promise.all([
            fetch('/admin/settings/raw', { credentials: 'same-origin' }),
            fetch('/admin/settings/schema', { credentials: 'same-origin' })
        ]);
        if (dataResp.status === 401 || dataResp.status === 403) {
            const ret = encodeURIComponent(window.location.pathname + window.location.hash);
            window.location.href = '/?return=' + ret;
            return;
        }
        CONFIG = await dataResp.json();
        SCHEMA = await schemaResp.json();
        try {
            const ucResp = await fetch('/admin/settings/use-case-defaults', { credentials: 'same-origin' });
            if (ucResp.ok) USE_CASE_DEFAULTS = await ucResp.json();
        } catch (e) { /* defaults bleiben leer */ }
        buildNav();
        // Activate first section
        const first = Object.keys(SCHEMA)[0];
        if (first) activateSection(first);
        // Restart-Banner: nach Init pruefen, ob etwas pending ist (z.B. wenn
        // ein anderer Tab kuerzlich gespeichert hat).
        loadRestartPending();
    } catch (e) {
        document.getElementById('content').innerHTML = '<div class="loading" style="color:#f85149;">Error loading config: ' + e.message + '</div>';
    }
}

function authHeaders() {
    // Cookie-basiert: Browser sendet Session-Cookie automatisch. Nur Content-Type explizit setzen.
    return { 'Content-Type': 'application/json' };
}

// ── Navigation ──
function buildNav() {
    const nav = document.getElementById('nav-links');
    nav.innerHTML = '';
    for (const [key, sec] of Object.entries(SCHEMA)) {
        const a = document.createElement('a');
        a.href = '#' + key;
        // nav_sub: als eingerueckter Unterpunkt rendern (z.B. LLM Routing unter
        // der einfachen LLM-Models-Seite).
        if (sec.nav_sub) {
            a.className = 'nav-sub';
            a.innerHTML = '<span class="nav-icon">›</span> ' + sec.label;
        } else {
            a.innerHTML = '<span class="nav-icon">' + (sec.icon || '') + '</span> ' + sec.label;
        }
        a.dataset.section = key;
        a.onclick = (e) => { e.preventDefault(); activateSection(key); };
        nav.appendChild(a);
        // Sub-arrays (e.g. backends) as indented sub-items — each gets its
        // own page (key "<sec>::<arr>").
        if (sec.sub_arrays) {
            for (const [arrKey, arrDef] of Object.entries(sec.sub_arrays)) {
                const subKey = key + '::' + arrKey;
                const sa = document.createElement('a');
                sa.className = 'nav-sub';
                sa.href = '#' + subKey;
                sa.innerHTML = '<span class="nav-icon">›</span> ' + arrDef.label;
                sa.dataset.section = subKey;
                sa.onclick = (e) => { e.preventDefault(); activateSection(subKey); };
                nav.appendChild(sa);
            }
        }
    }
}

function activateSection(key) {
    ACTIVE_SECTION = key;
    // Update nav
    document.querySelectorAll('.sidebar a').forEach(a => a.classList.remove('active'));
    const link = document.querySelector('.sidebar a[data-section="' + key + '"]');
    if (link) link.classList.add('active');
    // Show settings toolbar, restore content mode
    document.getElementById('settings-toolbar').style.display = 'flex';
    const content = document.getElementById('content');
    content.classList.remove('iframe-mode');
    // Render section
    renderSection(key);
}

function activateIframe(key, url, title) {
    ACTIVE_SECTION = key;
    // Update nav
    document.querySelectorAll('.sidebar a').forEach(a => a.classList.remove('active'));
    const link = document.querySelector('.sidebar a[data-section="' + key + '"]');
    if (link) link.classList.add('active');
    // Hide settings toolbar
    document.getElementById('settings-toolbar').style.display = 'none';
    // Load iframe
    const content = document.getElementById('content');
    content.classList.add('iframe-mode');
    content.innerHTML = '<iframe src="' + url + '" title="' + esc(title) + '"></iframe>';
}

// World-Badge im Sidebar — auf jeder Seite + iframe-Children einsehbar.
fetch('/admin/world-name', { credentials: 'same-origin', cache: 'no-store' })
  .then(r => r.ok ? r.json() : null)
  .then(d => {
      const el = document.getElementById('world-name');
      if (el && d && d.world) el.textContent = d.world;
  })
  .catch(() => {});

// ── Render Section ──
// Master-Detail-Editor fuer image_generation.use_cases (links Use-Case-Liste,
// rechts Familien × Style/Negative/Instruction). Leeres Feld zeigt den
// eingebauten Default als grauen Placeholder.
function renderUseCasesMasterDetail(path) {
    const D = USE_CASE_DEFAULTS || { use_cases: [], families: [], defaults: {} };
    const ucs = D.use_cases || [];
    let sel = SELECTED_ITEM[path];
    if (ucs.indexOf(sel) === -1) sel = ucs.length ? ucs[0] : null;
    SELECTED_ITEM[path] = sel;
    let html = '<p class="hint" style="opacity:.7;margin-bottom:12px">'
          + 'Style / Negative / Instruction pro Use-Case × Familie. Leeres Feld = eingebauter Default (grau). '
          + 'Which family applies is determined by the <b>Image Family</b> of the backend.</p>';
    html += '<div class="md-grid"><div class="md-list"><table class="md-table"><thead><tr><th>Use-Case</th></tr></thead><tbody>';
    for (const uc of ucs) {
        const active = (uc === sel) ? ' active' : '';
        html += '<tr class="md-row' + active + '" onclick="selectMasterItem(\\'' + path + '\\', \\'' + uc + '\\')"><td>' + esc(uc) + '</td></tr>';
    }
    html += '</tbody></table></div>';
    html += '<div class="md-detail">' + renderUseCaseDetail(sel) + '</div></div>';
    return html;
}

function renderUseCaseDetail(uc) {
    if (!uc) return '<div class="md-empty-detail">Use-Case links auswaehlen.</div>';
    const D = USE_CASE_DEFAULTS || { families: [], defaults: {} };
    const FIELDS = [['prompt_style', 'Style'], ['prompt_negative', 'Negative'], ['prompt_instruction', 'Instruction']];
    let html = '<div class="md-detail-head"><span class="md-detail-title">' + esc(uc) + '</span></div>';
    for (const fam of (D.families || [])) {
        html += '<div style="margin:4px 0 16px 0;padding-left:8px;border-left:2px solid var(--border,#30363d)">';
        html += '<div style="opacity:.6;font-size:.8em;text-transform:uppercase;letter-spacing:.05em;margin-bottom:6px">' + esc(fam) + '</div>';
        for (const fp of FIELDS) {
            const fld = fp[0], lbl = fp[1];
            const p = 'image_generation.use_cases.' + uc + '.styles.' + fam + '.' + fld;
            const val = getVal(p) || '';
            const def = (((D.defaults || {})[uc] || {})[fam] || {})[fld] || '';
            // „Copy default": fuellt das leere Feld mit dem eingebauten Default,
            // damit man ihn als Ausgangspunkt bearbeiten kann (sonst nur grauer
            // Placeholder). Nur anbieten, wenn ein Default existiert und das Feld
            // leer ist (kein versehentliches Ueberschreiben eigener Eingaben).
            const copyBtn = (def && !val)
                ? ' <button type="button" class="btn btn-sm" '
                  + 'style="margin-left:8px;font-size:.72em;padding:1px 6px;vertical-align:middle" '
                  + 'title="Copy the built-in default into this field to edit it" '
                  + 'onclick="copyUseCaseDefault(\\'' + p + '\\', \\'' + uc + '\\', \\'' + fam + '\\', \\'' + fld + '\\')">Copy default</button>'
                : '';
            html += '<div class="field" style="margin-bottom:8px"><label style="font-size:.8em;opacity:.8">' + esc(lbl) + copyBtn + '</label>';
            html += '<textarea rows="2" style="width:100%;font-family:inherit;resize:vertical" '
                  + 'placeholder="' + esc(def) + '" '
                  + 'onchange="setVal(\\'' + p + '\\', this.value)">' + esc(val) + '</textarea></div>';
        }
        html += '</div>';
    }
    return html;
}

// „Copy default": schreibt den eingebauten Use-Case-Default in das Feld, damit
// man ihn bearbeiten kann. uc/fam/fld bestimmen den Default, p ist der Setz-Pfad.
function copyUseCaseDefault(p, uc, fam, fld) {
    const D = USE_CASE_DEFAULTS || { defaults: {} };
    const def = (((D.defaults || {})[uc] || {})[fam] || {})[fld] || '';
    if (!def) return;
    setVal(p, def);
    renderSection(ACTIVE_SECTION);
}

// Repository: LoRA -> Aktivierungs-Wort. Liste von {lora, word}; wird vom
// Image-Creation-Code automatisch in den Prompt aufgenommen, sobald das LoRA
// genutzt wird. Speicherung in image_generation.lora_triggers (per Welt).
function renderLoraTriggersEditor(path) {
    const items = getVal(path) || [];
    let html = '<p class="hint" style="opacity:.7;margin-bottom:12px">'
             + 'Zentrale LoRA-Liste der Welt. Pro LoRA ein Aktivierungs-Wort: sobald ein Bild dieses '
             + 'LoRA nutzt, wird das Wort automatisch dem Prompt vorangestellt (Map, Character, …). '
             + 'Alle LoRA-Dropdowns in der UI ziehen ihre Vorschlaege aus dieser Liste.</p>';
    html += '<p class="hint" style="opacity:.7;margin-bottom:12px">'
             + 'Backends with a <b>LoRA Query URL</b> fetch their LoRA list live from that endpoint; '
             + 'for all other backends enter the LoRA names here <b>manually</b>. They are applied via the '
             + 'prompt syntax <code>&lt;lora:Name:Weight&gt;</code> or the activation word.</p>';
    html += '<div style="margin-bottom:12px">'
          + '<button class="btn btn-sm" onclick="addLoraTrigger(\\'' + path + '\\')">+ Add</button></div>';
    if (!items.length) {
        html += '<div class="md-empty">Noch keine Eintraege. „+ Add", dann LoRA-Namen tippen/suchen.</div>';
    }
    for (let i = 0; i < items.length; i++) {
        const it = items[i] || {};
        const ip = path + '[' + i + ']';
        html += '<div class="lora-row" style="display:flex;gap:8px;align-items:flex-start;margin-bottom:6px">';
        // 1. Spalte: Endpoint-Zuordnung (Backend-Name) — leer = fuer alle Backends.
        // Verhindert, dass eine LoRA beim falschen Backend (anderes Modell) erscheint.
        html += '<select title="Endpoint (Backend) — leer = alle" style="flex:2;min-width:0;background:#0d1117;color:#c9d1d9;border:1px solid #30363d;border-radius:6px;padding:6px" onchange="setVal(\\'' + ip + '.endpoint\\', this.value)">';
        html += '<option value="">— Alle Endpoints —</option>';
        for (const be of ((CONFIG.image_generation && CONFIG.image_generation.backends) || [])) {
            const bn = be.name || '';
            if (!bn) continue;
            html += '<option value="' + esc(bn) + '"' + (bn === (it.endpoint || '') ? ' selected' : '') + '>' + esc(bn) + '</option>';
        }
        html += '</select>';
        // 2. Spalte: LoRA-Name. Eigene dunkle Such-Combobox statt nativem <select>
        // (das rendert die Optionsliste OS-seitig weiss). Freitext erlaubt.
        html += '<div class="lt-combo" style="flex:3;min-width:0">';
        html += '<input type="text" class="lt-lora-input" autocomplete="off" value="' + esc(it.lora || '') + '" '
              + 'placeholder="LoRA-Name — tippen zum Suchen oder frei notieren" style="width:100%" '
              + 'oninput="ltFilter(this, \\'' + ip + '\\')" '
              + 'onfocus="ltFilter(this, \\'' + ip + '\\')" '
              + 'onkeydown="ltKey(event, this, \\'' + ip + '\\')" '
              + 'onblur="ltBlur(this)">';
        html += '<div class="lt-dd"></div>';
        html += '</div>';
        // 3. Spalte: Aktivierungs-Wort.
        html += '<input type="text" value="' + esc(it.word || '') + '" placeholder="Aktivierungs-Wort" '
              + 'style="flex:2;min-width:0" onchange="setVal(\\'' + ip + '.word\\', this.value)">';
        html += '<button class="btn btn-sm" title="Kopieren (z.B. fuer anderen Endpoint)" onclick="copyLoraTrigger(\\'' + path + '\\', ' + i + ')">⧉</button>';
        html += '<button class="btn btn-sm btn-danger" title="Loeschen" onclick="removeItem(\\'' + ip + '\\')">✕</button>';
        html += '</div>';
    }
    return html;
}

function addLoraTrigger(path) {
    const arr = _ensureContainer(path, 'array');
    arr.push({ lora: '', word: '', endpoint: '' });
    renderSection(ACTIVE_SECTION);
}

// Dupliziert einen LoRA-Eintrag (gleiche LoRA + Wort) direkt darunter — danach
// nur den Endpoint umstellen, um dieselbe LoRA fuer ein anderes Backend zu nutzen.
function copyLoraTrigger(path, i) {
    const arr = _ensureContainer(path, 'array');
    const src = arr[i] || {};
    arr.splice(i + 1, 0, { lora: src.lora || '', word: src.word || '', endpoint: src.endpoint || '' });
    renderSection(ACTIVE_SECTION);
}

// Suggestion list for the LoRA search combobox. There is no server-side LoRA
// scan anymore — suggestions are the LoRA names already entered in the list
// (useful when reusing the same LoRA for another endpoint).
function ltSuggestions() {
    const items = (CONFIG.image_generation && CONFIG.image_generation.lora_triggers) || [];
    const seen = {};
    const out = [];
    for (const it of items) {
        const n = (it && it.lora) ? String(it.lora) : '';
        if (n && !seen[n]) { seen[n] = true; out.push(n); }
    }
    return out;
}

// Fill the dropdown below the input, filtered by the typed text.
function ltFilter(inp, ip) {
    setVal(ip + '.lora', inp.value);  // apply free text immediately
    const dd = inp.nextElementSibling;
    if (!dd) return;
    const q = (inp.value || '').toLowerCase();
    const all = ltSuggestions();
    const opts = q ? all.filter(function (m) { return m.toLowerCase().indexOf(q) !== -1; }) : all;
    if (!all.length) {
        dd.innerHTML = '<div class="lt-dd-empty">No suggestions — type the LoRA name manually</div>';
        dd.style.display = 'block';
        return;
    }
    if (!opts.length) {
        dd.innerHTML = '<div class="lt-dd-empty">Kein Treffer — Eingabe wird als Freitext gespeichert</div>';
        dd.style.display = 'block';
        return;
    }
    let h = '';
    for (let i = 0; i < opts.length && i < 80; i++) {
        h += '<div class="lt-opt" data-v="' + esc(opts[i]) + '" '
           + 'onmousedown="ltPick(this, \\'' + ip + '\\')">' + esc(opts[i]) + '</div>';
    }
    dd.innerHTML = h;
    dd.style.display = 'block';
}

// Auswahl per Maus (onmousedown feuert vor onblur, daher kein Race).
function ltPick(el, ip) {
    const v = el.getAttribute('data-v');
    const dd = el.parentElement;
    const inp = dd.previousElementSibling;
    inp.value = v;
    setVal(ip + '.lora', v);
    dd.style.display = 'none';
}

// Tastatur: Pfeil hoch/runter markiert, Enter uebernimmt, Esc schliesst.
function ltKey(ev, inp, ip) {
    const dd = inp.nextElementSibling;
    if (!dd || dd.style.display === 'none') return;
    const opts = dd.querySelectorAll('.lt-opt');
    if (!opts.length) return;
    let idx = -1;
    for (let i = 0; i < opts.length; i++) { if (opts[i].classList.contains('active')) { idx = i; break; } }
    if (ev.key === 'ArrowDown') { ev.preventDefault(); idx = Math.min(idx + 1, opts.length - 1); }
    else if (ev.key === 'ArrowUp') { ev.preventDefault(); idx = Math.max(idx - 1, 0); }
    else if (ev.key === 'Enter') {
        if (idx >= 0) { ev.preventDefault(); ltPick(opts[idx], ip); }
        return;
    } else if (ev.key === 'Escape') { dd.style.display = 'none'; return; }
    else { return; }
    for (let i = 0; i < opts.length; i++) opts[i].classList.toggle('active', i === idx);
    opts[idx].scrollIntoView({ block: 'nearest' });
}

function ltBlur(inp) {
    // Verzoegert schliessen, damit ein Klick auf eine Option noch ankommt.
    setTimeout(function () { const dd = inp.nextElementSibling; if (dd) dd.style.display = 'none'; }, 150);
}

function renderSection(key) {
    // Compound-Key "<section>::<subArray>" -> eigene Sub-Array-Seite.
    if (key.indexOf('::') !== -1) { renderSubArrayPage(key); return; }
    // Einfache, kategorie-basierte LLM-Seite (befuellt CONFIG.llm_routing).
    if (key === 'llm_simple') { renderLlmSimpleEditor(); return; }
    const sec = SCHEMA[key];
    // null und undefined beide auf Default fallen lassen — sonst wirft
    // renderFields(null, ...) bei data[fKey] einen TypeError.
    const cfgVal = CONFIG[key];
    const data = (cfgVal !== undefined && cfgVal !== null) ? cfgVal : (sec.is_array ? [] : {});
    const content = document.getElementById('content');

    let html = '<div class="section active">';
    html += '<h1 class="section-title">' + (sec.icon || '') + ' ' + sec.label + '</h1>';

    // Top-level fields (skip for array sections — fields are rendered per item)
    if (sec.fields && !sec.is_array) {
        html += renderFields(sec.fields, data, key);
    }

    // Subsections
    if (sec.subsections) {
        for (const [subKey, sub] of Object.entries(sec.subsections)) {
            const subData = data[subKey] || {};
            html += '<div class="subsection">';
            html += '<div class="subsection-title">' + sub.label + '</div>';
            html += renderFields(sub.fields, subData, key + '.' + subKey);
            html += '</div>';
        }
    }

    // Sub-arrays (backends, catalogs) are NOT rendered here — each has its
    // own nav sub-item (see buildNav /
    // renderSubArrayPage), damit die Hauptseite nicht ueberladen ist.

    // Array sections (providers)
    if (sec.is_array) {
        if (key === 'llm_routing') {
            // Zweispaltig: links Editor, rechts Task-View (read-only)
            html += '<div style="display:grid; grid-template-columns: 1fr 1fr; gap:20px;">';
            html += '<div>';
            html += '<div style="margin-bottom: 12px;">';
            html += '<button class="btn btn-sm" onclick="addArrayItem(\\'' + key + '\\', \\'array\\')">+ Add LLM</button>';
            html += '</div>';
            html += renderArrayItems(sec, data || [], key);
            html += '</div>';
            html += '<div>';
            html += '<div class="subsection-title" style="margin-bottom:8px;">Sichtweise pro Task</div>';
            html += '<div id="llm-task-view"><div class="desc">Loading…</div></div>';
            html += '</div>';
            html += '</div>';
            // Der Tool-/Helper-Eignungstest lebt jetzt unter "Model Capabilities".
            html += '<div class="desc" style="margin-top:16px;">🧪 The Tool/Helper suitability test moved to <a href="/admin/models" target="_blank" style="color:#58a6ff;">Model Capabilities</a>.</div>';
            setTimeout(() => renderLlmTaskView(data || []), 0);
        } else {
            html += '<div style="margin-bottom: 12px;">';
            html += '<button class="btn btn-sm" onclick="addArrayItem(\\'' + key + '\\', \\'array\\')">+ Add ' + sec.label + '</button>';
            html += '</div>';
            html += renderArrayItems(sec, data || [], key);
        }
    }

    html += '</div>';
    content.innerHTML = html;
    // image_preview-Felder Meta nachladen (kein <script> via innerHTML moeglich)
    populateImagePreviewMetas();
}

// Eigene Seite fuer ein einzelnes Sub-Array (z.B. image_generation::backends).
function renderSubArrayPage(key) {
    const sep = key.indexOf('::');
    const parentKey = key.slice(0, sep);
    const arrKey = key.slice(sep + 2);
    const sec = SCHEMA[parentKey];
    const arrDef = sec && sec.sub_arrays ? sec.sub_arrays[arrKey] : null;
    const content = document.getElementById('content');
    if (!sec || !arrDef) { content.innerHTML = '<div class="section active"></div>'; return; }
    const parentData = (CONFIG[parentKey] && typeof CONFIG[parentKey] === 'object') ? CONFIG[parentKey] : {};
    const path = parentKey + '.' + arrKey;
    const items = parentData[arrKey] || (arrDef.is_dict ? {} : []);

    let html = '<div class="section active">';
    html += '<h1 class="section-title">' + (sec.icon || '') + ' ' + sec.label + ' — ' + arrDef.label + '</h1>';
    if (arrDef.use_cases_editor) {
        html += renderUseCasesMasterDetail(path);
    } else if (arrDef.lora_triggers_editor) {
        html += renderLoraTriggersEditor(path);
    } else if (arrDef.master_detail) {
        html += renderMasterDetail(arrDef, items, path);
    } else {
        html += '<div style="margin-bottom:12px;"><button class="btn btn-sm" onclick="addArrayItem(\\'' + path + '\\', \\'' + (arrDef.is_dict ? 'dict' : 'array') + '\\')">+ Add</button></div>';
        if (arrDef.is_dict) html += renderDictItems(arrDef, items, path);
        else html += renderArrayItems(arrDef, items, path);
    }
    html += '</div>';
    content.innerHTML = html;
    populateImagePreviewMetas();
}

async function populateImagePreviewMetas() {
    const els = document.querySelectorAll('.image-preview-meta[data-meta-url]');
    for (const el of els) {
        const url = el.dataset.metaUrl;
        if (!url) continue;
        try {
            const r = await fetch(url);
            if (!r.ok) continue;
            const d = await r.json();
            if (d.has_frame && d.bbox && d.frame_size) {
                el.textContent = 'Frame ' + d.frame_size[0] + '×' + d.frame_size[1]
                    + ' — Window ' + d.bbox.w + '×' + d.bbox.h
                    + ' @ (' + d.bbox.x + ',' + d.bbox.y + ')'
                    + (d.generated_at ? ' — generiert ' + d.generated_at : '');
            } else {
                el.textContent = 'Noch nicht generiert.';
            }
        } catch (e) { /* ignore */ }
    }
}

// ── Einfache, kategorie-basierte LLM-Seite ──────────────────────────────
// Eine Provider+Model-Auswahl pro Job-Typ; befuellt CONFIG.llm_routing
// (order=1) automatisch. Embedding kann "Internal (built-in)" sein → schreibt
// stattdessen CONFIG.embedding.
const LLM_SIMPLE_CATS = [
    {key:'chat',      label:'Chat & Roleplay',           desc:'The main model your characters chat and roleplay with. Pick your biggest / best writing model.'},
    {key:'tool',      label:'Tools & Decisions',         desc:'Structured decisions and tool-calling (intent, events, outfit generation). Needs a model that reliably follows instructions / returns clean JSON.'},
    {key:'helper',    label:'Helper (small jobs)',       desc:'Cheap background work: summaries, translation, image-prompt cleanup. A small / fast model is fine here.'},
    {key:'image',     label:'Vision (read images)',      desc:'Looks at generated images (recognition / analysis). Needs a vision-capable model.'},
    {key:'embedding', label:'Similarity (pose matching)',desc:'Turns text into vectors so similar poses reuse the same image. Can run built-in on CPU — no server needed.'},
];
const LLM_SIMPLE_TEMP = { chat:0.8, tool:0.1, helper:0.5, image:0.3, embedding:0 };
const LLM_SIMPLE_INTERNAL = '__internal__';
let LLM_SIMPLE_SEL = {};

async function renderLlmSimpleEditor() {
    const content = document.getElementById('content');
    content.innerHTML = '<div class="section active"><h1 class="section-title">🧭 LLM Models (Simple)</h1><div class="desc">Loading…</div></div>';
    const tasks = await loadLlmTasks();
    llmSimpleDetect(tasks);

    let html = '<div class="section active">';
    html += '<h1 class="section-title">🧭 LLM Models (Simple)</h1>';
    html += '<div class="desc" style="margin-bottom:14px;">Pick one provider + model per job type. This fills the '
         + '<a href="#llm_routing" onclick="event.preventDefault(); activateSection(\\'llm_routing\\')" style="color:#58a6ff;">Advanced LLM Routing</a> '
         + 'automatically (as primary / order 1). Use the advanced page only for fallbacks and per-task tuning. Press <b>Save</b> when done.</div>';

    const providers = CONFIG.providers || [];
    for (const cat of LLM_SIMPLE_CATS) {
        const sel = LLM_SIMPLE_SEL[cat.key] || {};
        html += '<div class="subsection">';
        html += '<div class="subsection-title">' + esc(cat.label) + '</div>';
        html += '<div class="desc" style="margin-bottom:8px;">' + esc(cat.desc) + '</div>';
        html += '<div style="display:flex; gap:10px; flex-wrap:wrap; align-items:center;">';
        // Provider
        html += '<select id="llmsimple-prov-' + cat.key + '" onchange="llmSimpleSetProvider(\\'' + cat.key + '\\', this.value)">';
        html += '<option value="">— none —</option>';
        if (cat.key === 'embedding') {
            html += '<option value="' + LLM_SIMPLE_INTERNAL + '"' + (sel.provider === LLM_SIMPLE_INTERNAL ? ' selected' : '') + '>Internal (built-in — no setup)</option>';
        }
        for (const p of providers) {
            html += '<option value="' + esc(p.name) + '"' + (p.name === sel.provider ? ' selected' : '') + '>' + esc(p.name) + ' (' + esc(p.type) + ')</option>';
        }
        html += '</select>';
        // Model
        html += '<select id="llmsimple-model-' + cat.key + '" onchange="llmSimpleSetModel(\\'' + cat.key + '\\', this.value)" style="min-width:240px;">';
        html += '<option value="' + esc(sel.model || '') + '" selected>' + esc(sel.model || '— select —') + '</option>';
        html += '</select>';
        html += '<button class="btn btn-sm" onclick="llmSimpleLoadModels(\\'' + cat.key + '\\')">Load Models</button>';
        html += '</div>';
        html += '</div>';
    }
    html += '</div>';
    content.innerHTML = html;
    // Model-Dropdowns initial fuellen (aus Cache / interne Choices)
    for (const cat of LLM_SIMPLE_CATS) llmSimplePopulateModels(cat.key, false);
}

function llmSimpleDetect(tasks) {
    LLM_SIMPLE_SEL = {};
    const routing = CONFIG.llm_routing || [];
    const catOf = {};
    for (const t of (tasks || [])) catOf[t.id] = t.category;
    for (const cat of LLM_SIMPLE_CATS) {
        const tally = {};
        for (const e of routing) {
            if (e.enabled === false) continue;
            for (const t of (e.tasks || [])) {
                if ((t.order || 1) !== 1) continue;
                if (catOf[t.task] !== cat.key) continue;
                const k = (e.provider || '') + '\\u0000' + (e.model || '');
                tally[k] = (tally[k] || 0) + 1;
            }
        }
        let best = null, bestN = 0;
        for (const k in tally) if (tally[k] > bestN) { bestN = tally[k]; best = k; }
        if (best) {
            const parts = best.split('\\u0000');
            LLM_SIMPLE_SEL[cat.key] = { provider: parts[0], model: parts[1] };
        }
    }
    // Embedding: interne Config gewinnt ueber Routing-Detection
    const emb = CONFIG.embedding || {};
    if (emb.backend === 'internal') {
        LLM_SIMPLE_SEL.embedding = { provider: LLM_SIMPLE_INTERNAL, model: emb.internal_model || '' };
    }
}

function llmSimpleSetProvider(cat, val) {
    LLM_SIMPLE_SEL[cat] = { provider: val, model: '' };
    const m = document.getElementById('llmsimple-model-' + cat);
    if (m) m.innerHTML = '<option value="" selected>— select —</option>';
    llmSimplePopulateModels(cat, true);
    llmSimpleRebuild();
}

function llmSimpleSetModel(cat, val) {
    if (!LLM_SIMPLE_SEL[cat]) LLM_SIMPLE_SEL[cat] = {};
    LLM_SIMPLE_SEL[cat].model = val;
    llmSimpleRebuild();
}

function llmSimplePopulateModels(cat, autoload) {
    const sel = LLM_SIMPLE_SEL[cat] || {};
    const el = document.getElementById('llmsimple-model-' + cat);
    if (!el) return;
    const cur = sel.model || '';
    // Interne Embedding-Modelle: Choices aus dem Schema
    if (sel.provider === LLM_SIMPLE_INTERNAL) {
        const f = ((SCHEMA.embedding || {}).fields || {}).internal_model || {};
        const choices = f.choices || [];
        let opts = '<option value="">— select —</option>';
        for (const c of choices) opts += '<option value="' + esc(c) + '"' + (c === cur ? ' selected' : '') + '>' + esc(c) + '</option>';
        el.innerHTML = opts;
        if (!cur && choices.length) {
            LLM_SIMPLE_SEL[cat].model = choices[0];
            el.value = choices[0];
            llmSimpleRebuild();
        }
        return;
    }
    if (!sel.provider) { el.innerHTML = '<option value="">— select provider —</option>'; return; }
    const models = PROVIDERS_CACHE[sel.provider];
    if (models && models.length) {
        const vis = PROVIDERS_VISION[sel.provider] || new Set();
        let opts = '<option value="">— select —</option>';
        for (const m of models) opts += '<option value="' + esc(m) + '"' + (m === cur ? ' selected' : '') + '>' + esc(m) + (vis.has(m) ? ' (vision)' : '') + '</option>';
        el.innerHTML = opts;
        if (cur && !models.includes(cur)) {
            el.innerHTML = '<option value="' + esc(cur) + '" selected>' + esc(cur) + ' (not on server)</option>' + opts;
        }
    } else if (autoload) {
        llmSimpleLoadModels(cat);
    }
}

async function llmSimpleLoadModels(cat) {
    const sel = LLM_SIMPLE_SEL[cat] || {};
    if (sel.provider === LLM_SIMPLE_INTERNAL) { llmSimplePopulateModels(cat, false); return; }
    if (!sel.provider) { toast('Select a provider first', 'error'); return; }
    const el = document.getElementById('llmsimple-model-' + cat);
    if (el) el.innerHTML = '<option>Loading…</option>';
    if (!PROVIDERS_CACHE[sel.provider] || !PROVIDERS_CACHE[sel.provider].length) {
        try {
            const resp = await fetch('/admin/settings/providers/' + encodeURIComponent(sel.provider) + '/models', { credentials: 'same-origin' });
            const data = await resp.json();
            if (data.error) toast('Error: ' + data.error, 'error');
            const list = data.models || [];
            if (list.length) {
                PROVIDERS_CACHE[sel.provider] = list;
                PROVIDERS_VISION[sel.provider] = new Set(data.vision || []);
            }
        } catch (e) { toast('Failed to load models: ' + e.message, 'error'); }
    }
    llmSimplePopulateModels(cat, false);
}

// Schreibt CONFIG.llm_routing (order=1) + CONFIG.embedding aus LLM_SIMPLE_SEL.
function llmSimpleRebuild() {
    const tasks = LLM_TASKS_CACHE || [];
    const byCat = {};
    for (const t of tasks) (byCat[t.category] = byCat[t.category] || []).push(t.id);
    // Kopie ziehen, dann alle order==1-Zuordnungen entfernen (Fallbacks bleiben)
    let routing = (CONFIG.llm_routing || []).map(e => Object.assign({}, e, { tasks: (e.tasks || []).slice() }));
    for (const e of routing) e.tasks = (e.tasks || []).filter(t => (t.order || 1) !== 1);
    for (const cat of LLM_SIMPLE_CATS) {
        const sel = LLM_SIMPLE_SEL[cat.key] || {};
        if (cat.key === 'embedding' && sel.provider === LLM_SIMPLE_INTERNAL) continue;
        if (!sel.provider || !sel.model) continue;
        const ids = byCat[cat.key] || [];
        if (!ids.length) continue;
        let entry = routing.find(e => e.provider === sel.provider && e.model === sel.model);
        if (!entry) {
            entry = { provider: sel.provider, model: sel.model, enabled: true, temperature: LLM_SIMPLE_TEMP[cat.key], tasks: [] };
            routing.push(entry);
        }
        if (!entry.tasks) entry.tasks = [];
        for (const id of ids) entry.tasks.push({ task: id, order: 1 });
    }
    // Leer gewordene Eintraege entfernen (ausser sie sind nur zum Preload da)
    routing = routing.filter(e => (e.tasks && e.tasks.length) || e.preload_on_startup);
    CONFIG.llm_routing = routing;
    // Embedding-Config
    if (!CONFIG.embedding) CONFIG.embedding = {};
    const e = LLM_SIMPLE_SEL.embedding || {};
    if (e.provider === LLM_SIMPLE_INTERNAL) {
        CONFIG.embedding.backend = 'internal';
        if (e.model) CONFIG.embedding.internal_model = e.model;
    } else if (e.provider && e.model) {
        CONFIG.embedding.backend = 'external';
    } else {
        CONFIG.embedding.backend = 'auto';
    }
}

async function renderLlmTaskView(entries) {
    const tasks = await loadLlmTasks();
    const view = document.getElementById('llm-task-view');
    if (!view) return;

    // State vom Server laden (runtime + persistent + presets)
    let state = { disabled: [], runtime_disabled: [], presets: {} };
    try {
        const r = await fetch('/admin/settings/llm-task-state', { credentials: 'same-origin' });
        if (r.ok) state = await r.json();
    } catch (e) {}

    // Persistent disabled aus CONFIG (UI-Quelle fuer Toggles)
    const persistentDisabled = new Set(
        ((CONFIG.llm_task_state || {}).disabled_tasks || [])
    );
    const runtimeDisabled = new Set(state.runtime_disabled || []);

    // task_id -> [{order, provider, model, llmDisabled}]
    const byTask = {};
    for (const entry of (entries || [])) {
        if (!entry || typeof entry !== 'object') continue;
        const prov = entry.provider || '';
        const mod = entry.model || '';
        const llmDisabled = entry.enabled === false;
        for (const t of (entry.tasks || [])) {
            if (!t || !t.task) continue;
            (byTask[t.task] = byTask[t.task] || []).push({
                order: t.order || 999,
                provider: prov,
                model: mod,
                llmDisabled: llmDisabled,
            });
        }
    }
    for (const k in byTask) byTask[k].sort((a, b) => a.order - b.order);

    let html = '';
    // Preset-Selector (runtime, nicht persistent — gilt nur fuer diese Server-Session)
    html += '<div style="margin-bottom:10px; padding:8px 10px; background:#161b22; border:1px solid #30363d; border-radius:6px;">';
    html += '<div style="font-size:12px; color:#8b949e; margin-bottom:6px;">Runtime preset (not persistent):</div>';
    html += '<select id="llm-task-preset" onchange="applyTaskPreset(this.value)" style="background:#0d1117; color:#c9d1d9; border:1px solid #30363d; padding:6px; border-radius:4px; width:100%;">';
    html += '<option value="none">— none (all tasks active) —</option>';
    for (const p of Object.keys(state.presets || {})) {
        html += '<option value="' + esc(p) + '">' + esc(p) + ' — ' + (state.presets[p] || []).length + ' tasks off</option>';
    }
    html += '</select>';
    if (runtimeDisabled.size) {
        html += '<div style="font-size:11px; color:#d29922; margin-top:4px;">Active: ' + runtimeDisabled.size + ' tasks runtime-disabled</div>';
    }
    html += '</div>';

    // Sortierung nach Category (chat → tool → helper → image), innerhalb
    // dann nach Label. So sind groessere Modelle (chat) oben, kleine
    // Helfer unten — entspricht der Lese-Erwartung "wer braucht was".
    const _CAT_ORDER = { chat: 0, tool: 1, helper: 2, image: 3, embedding: 4 };
    // Per-Category Farben fuer Border + Badge:
    //   chat:   blau    — grosse Modelle
    //   tool:   violett — strukturierte Outputs
    //   helper: gruen   — kleine/billige Modelle
    //   image:  orange  — Vision / Bild-IO
    const _CAT_COLORS = {
        chat:   { bg: '#1f3a5f', fg: '#79c0ff', border: '#30547a' },
        tool:   { bg: '#3a2f5f', fg: '#d2a8ff', border: '#54497a' },
        helper: { bg: '#1c3a2c', fg: '#7ee787', border: '#2d553f' },
        image:  { bg: '#5a3a1f', fg: '#ffaa66', border: '#7a543d' },
        embedding: { bg: '#3a1f4f', fg: '#c879ff', border: '#54387a' },
        '':     { bg: '#21262d', fg: '#8b949e', border: '#30363d' },
    };
    const sortedTasks = [...tasks].sort((a, b) => {
        const ao = _CAT_ORDER[a.category] ?? 99;
        const bo = _CAT_ORDER[b.category] ?? 99;
        if (ao !== bo) return ao - bo;
        return (a.label || '').localeCompare(b.label || '');
    });

    let _lastCat = null;
    for (const t of sortedTasks) {
        // Category-Header bei Wechsel
        if (t.category !== _lastCat) {
            _lastCat = t.category;
            const cc = _CAT_COLORS[t.category] || _CAT_COLORS[''];
            html += '<div style="margin:14px 0 6px 0; padding:4px 10px; '
                 + 'background:' + cc.bg + '; color:' + cc.fg + '; '
                 + 'border-left:3px solid ' + cc.fg + '; border-radius:3px; '
                 + 'font-size:11px; font-weight:600; letter-spacing:0.3px; '
                 + 'text-transform:uppercase;">'
                 + esc(t.category_label || 'Other') + '</div>';
        }

        const rows = byTask[t.id] || [];
        const isEmpty = rows.length === 0;
        const isPersistDisabled = persistentDisabled.has(t.id);
        const isRuntimeDisabled = runtimeDisabled.has(t.id);
        const disabledStyle = (isPersistDisabled || isRuntimeDisabled) ? 'opacity:0.5;' : '';
        const cc = _CAT_COLORS[t.category] || _CAT_COLORS[''];
        html += '<div style="margin-bottom:6px; padding:8px 10px; background:#0d1117; '
             + 'border:1px solid #30363d; border-left:3px solid ' + cc.fg + '; '
             + 'border-radius:6px; ' + disabledStyle + '">';
        html += '<div style="display:flex; justify-content:space-between; align-items:center;">';
        let catBadge = '';
        if (t.category_label) {
            catBadge = ' <span style="font-size:10px; color:' + cc.fg
                 + '; font-weight:400; background:' + cc.bg
                 + '; padding:1px 6px; border-radius:8px; margin-left:4px;">'
                 + esc(t.category_label) + '</span>';
        }
        html += '<div style="font-size:12px; color:#58a6ff; font-weight:600;">' + esc(t.label) + catBadge + ' <span style="color:#6e7681; font-weight:400;">— ' + esc(t.id) + '</span></div>';
        html += '<label style="display:inline-flex; align-items:center; gap:4px; font-size:11px; color:#8b949e; cursor:pointer;">';
        html += '<input type="checkbox" ' + (isPersistDisabled ? '' : 'checked') + ' onchange="toggleTaskPersistent(\\'' + t.id + '\\', !this.checked)"> active';
        html += '</label>';
        html += '</div>';
        if (isRuntimeDisabled) {
            html += '<div style="font-size:11px; color:#d29922;">runtime-disabled (preset)</div>';
        }
        if (isEmpty) {
            // pose_embedding laeuft ueber CONFIG.embedding (eingebautes fastembed/ONNX
            // oder externer /v1/embeddings-Provider), NICHT ueber llm_routing. Bei
            // internem/auto-Backend ist "no LLM assigned" irrefuehrend -> echten Status zeigen.
            const _emb = CONFIG.embedding || {};
            const _embBackend = (_emb.backend || 'auto');
            if (t.id === 'pose_embedding' && _embBackend !== 'external') {
                const _m = _emb.internal_model || 'bge-small-en';
                const _lbl = _embBackend === 'auto' ? 'built-in (auto)' : 'built-in';
                html += '<div class="desc" style="color:#3fb950;">' + _lbl + ' embedding — ' + esc(_m) + ' (CPU, no LLM needed)</div>';
            } else {
                html += '<div class="desc" style="color:#d29922;">no LLM assigned</div>';
            }
        } else {
            html += '<div style="margin-top:4px;">';
            for (const r of rows) {
                const rowStyle = r.llmDisabled
                    ? 'font-size:12px; color:#6e7681; display:flex; gap:8px; text-decoration:line-through;'
                    : 'font-size:12px; color:#c9d1d9; display:flex; gap:8px;';
                html += '<div style="' + rowStyle + '">';
                html += '<span style="color:#6e7681; min-width:22px;">' + r.order + '.</span>';
                html += '<span>' + esc(r.provider) + ' / ' + esc(r.model) + '</span>';
                if (r.llmDisabled) {
                    html += '<span style="color:#d29922; text-decoration:none;">(LLM disabled)</span>';
                }
                html += '</div>';
            }
            html += '</div>';
        }
        html += '</div>';
    }
    view.innerHTML = html;
}

function toggleTaskPersistent(taskId, disable) {
    if (!CONFIG.llm_task_state) CONFIG.llm_task_state = { disabled_tasks: [] };
    const arr = CONFIG.llm_task_state.disabled_tasks || [];
    const idx = arr.indexOf(taskId);
    if (disable && idx < 0) arr.push(taskId);
    if (!disable && idx >= 0) arr.splice(idx, 1);
    CONFIG.llm_task_state.disabled_tasks = arr;
    toast('Change only takes effect after save', 'success');
    renderLlmTaskView(CONFIG.llm_routing || []);
}

async function applyTaskPreset(preset) {
    try {
        const resp = await fetch('/admin/settings/llm-task-state/runtime-preset', {
            method: 'POST',
            headers: authHeaders(),
            body: JSON.stringify({ preset: preset }),
        });
        const data = await resp.json();
        if (preset === 'none') {
            toast('Runtime preset cleared', 'success');
        } else {
            toast('Runtime preset "' + preset + '" active (' + (data.disabled || []).length + ' tasks off)', 'success');
        }
        renderLlmTaskView(CONFIG.llm_routing || []);
    } catch (e) {
        toast('Preset error: ' + e.message, 'error');
    }
}

// ── Render Fields ──
function renderFields(fields, data, path) {
    let html = '';
    for (const [fKey, f] of Object.entries(fields)) {
        // Schema-level Sichtbarkeit: ein Feld mit `applicable_for` wird nur
        // angezeigt, wenn `data.api_type` (oder ein anderes Geschwister-Feld,
        // falls spaeter erweitert) in der Liste enthalten ist. Solange kein
        // api_type gesetzt ist, blenden wir spezifische Felder aus — der
        // Nutzer waehlt erst den Typ, dann tauchen die passenden Felder auf.
        if (Array.isArray(f.applicable_for) && f.applicable_for.length) {
            const cur = (data && data.api_type) || '';
            if (!cur || !f.applicable_for.includes(cur)) {
                continue;
            }
        }
        if (f.type === 'group_header') {
            // Visueller Trenner ohne Daten-Binding (gruppiert nachfolgende Felder)
            html += '<div class="subsection-title" style="margin-top:18px;">' + f.label + '</div>';
            continue;
        }
        if (f.type === 'button') {
            // Action-Button — kein Daten-Binding, ruft Endpoint mit
            // body aus angegebenen Geschwister-Feldern auf.
            const btnId = 'btn-' + (path + '.' + fKey).replace(/\\W+/g, '-');
            const bodyFrom = JSON.stringify(f.body_from || []);
            const confirmMsg = f.confirm ? esc(f.confirm) : '';
            const previewUrl = f.preview_url ? esc(f.preview_url) : '';
            html += '<div class="field">';
            html += '<label></label>';
            html += '<div class="input-wrap">';
            html += '<button type="button" id="' + btnId + '" class="btn btn-primary" '
                + 'onclick="runActionButton(\\'' + esc(f.endpoint) + '\\', \\'' + (f.method || 'POST') + '\\', '
                + '\\'' + path + '\\', ' + bodyFrom.replace(/"/g, '&quot;') + ', \\'' + confirmMsg + '\\', this, \\'' + previewUrl + '\\')">'
                + esc(f.label) + '</button>';
            if (f.description) html += '<div class="desc">' + f.description + '</div>';
            html += '</div></div>';
            continue;
        }
        if (f.type === 'image_preview') {
            // Live-Preview eines Bild-Endpoints (z.B. generiertes Frame)
            const imgId = 'img-' + (path + '.' + fKey).replace(/\\W+/g, '-');
            const url = esc(f.url);
            const metaUrl = f.meta_url ? esc(f.meta_url) : '';
            html += '<div class="field">';
            html += '<label>' + esc(f.label) + '</label>';
            html += '<div class="input-wrap">';
            html += '<div id="' + imgId + '-wrap" class="image-preview-wrap" style="background:'
                + ' repeating-conic-gradient(#777 0% 25%, #555 0% 50%) 50% / 16px 16px;'
                + ' display:inline-block; padding:6px; border:1px solid #444; border-radius:6px; max-width:300px;">';
            html += '<img id="' + imgId + '" src="' + url + '?_=' + Date.now() + '" '
                + 'style="max-width:280px; max-height:380px; display:block;" '
                + 'onerror="this.style.display=\\'none\\'; this.nextElementSibling.style.display=\\'block\\';">';
            html += '<div style="display:none; color:#888; font-size:12px; padding:20px;">noch nicht generiert</div>';
            html += '</div>';
            if (metaUrl) {
                // Meta-URL als data-attribute hinterlegen — populateImagePreviewMetas()
                // wird nach renderSection aufgerufen und befuellt alle solche Elemente.
                html += '<div id="' + imgId + '-meta" class="desc image-preview-meta" '
                    + 'data-meta-url="' + metaUrl + '" '
                    + 'style="margin-top:6px; font-family:monospace; font-size:11px;"></div>';
            }
            if (f.description) html += '<div class="desc">' + f.description + '</div>';
            html += '</div></div>';
            continue;
        }
        if (f.type === 'array' && fKey === 'gpus') {
            html += renderGpuField(data[fKey] || [], path + '.' + fKey);
            continue;
        }
        if (f.type === 'task_order_list') {
            html += renderTaskOrderList(data[fKey] || [], path + '.' + fKey, f);
            continue;
        }
        const val = data[fKey] !== undefined ? data[fKey] : (f.default !== undefined ? f.default : '');
        const fullPath = path + '.' + fKey;
        const pill = f.requires_restart
            ? ' <span class="restart-pill" title="Changing this value requires a server restart">restart</span>'
            : '';
        // Felder, die bei Embedding-Eintraegen (Tasks der Gruppe "embedding")
        // irrelevant sind (temperature/max_tokens) — per Post-Pass ein-/ausgeblendet.
        const embedAttr = f.hide_for_embedding ? ' data-embedhide-entry="' + path + '"' : '';
        html += '<div class="field"' + embedAttr + '>';
        html += '<label for="f-' + fullPath + '">' + f.label + pill + '</label>';
        html += '<div class="input-wrap">';
        html += renderInput(f, val, fullPath);
        if (f.description) html += '<div class="desc">' + f.description + '</div>';
        html += '</div></div>';
    }
    return html;
}

function renderInput(f, val, path) {
    const id = 'f-' + path;
    switch (f.type) {
        case 'bool':
            return '<input type="checkbox" id="' + id + '" ' + (val ? 'checked' : '') + ' onchange="setVal(\\'' + path + '\\', this.checked)">';
        case 'int':
            return '<input type="number" id="' + id + '" value="' + esc(val) + '" '
                + (f.min !== undefined ? 'min="' + f.min + '" ' : '')
                + (f.max !== undefined ? 'max="' + f.max + '" ' : '')
                + 'step="1" onchange="setVal(\\'' + path + '\\', parseInt(this.value) || 0)">';
        case 'float':
            return '<input type="number" id="' + id + '" value="' + esc(val) + '" '
                + (f.min !== undefined ? 'min="' + f.min + '" ' : '')
                + (f.max !== undefined ? 'max="' + f.max + '" ' : '')
                + 'step="' + (f.step || 0.1) + '" onchange="setVal(\\'' + path + '\\', parseFloat(this.value) || 0)">';
        case 'select':
            let opts = (f.choices || []).map(c => '<option value="' + esc(c) + '"' + (c == val ? ' selected' : '') + '>' + esc(c) + '</option>').join('');
            const onChg = f.triggers_rerender
                ? "setVal('" + path + "', this.value); renderSection(ACTIVE_SECTION)"
                : "setVal('" + path + "', this.value)";
            return '<select id="' + id + '" onchange="' + onChg + '">' + opts + '</select>';
        case 'password':
            return '<div class="pw-wrap"><input type="password" id="' + id + '" value="' + esc(val) + '" onchange="setVal(\\'' + path + '\\', this.value)">'
                + '<button class="pw-toggle" type="button" onclick="togglePw(this)">👁</button></div>';
        case 'text':
            return '<textarea id="' + id + '" onchange="setVal(\\'' + path + '\\', this.value)">' + esc(val) + '</textarea>';
        case 'provider_select':
            return renderProviderSelect(val, path);
        case 'gpu_select':
            return renderGpuSelect(val, path);
        case 'model_select':
            return renderModelSelect(val, path);
        case 'imagegen_select':
            return renderImagegenSelect(val, path);
        case 'imagegen_backend_select':
            return renderImagegenBackendSelect(val, path);
        case 'imagegen_model_select':
            return renderImagegenModelSelect(val, path);
        case 'imagegen_model':
            return renderImagegenModelCombo(val, path);
        case 'imagegen_target_select':
            return renderImagegenTargetSelect(val, path);
        default: // str
            return '<input type="text" id="' + id + '" value="' + esc(val) + '" '
                + (f.placeholder ? 'placeholder="' + esc(f.placeholder) + '" ' : '')
                + 'onchange="setVal(\\'' + path + '\\', this.value)">';
    }
}

function renderProviderSelect(val, path) {
    const providers = CONFIG.providers || [];
    let opts = '<option value="">— Auto —</option>';
    for (const p of providers) {
        opts += '<option value="' + esc(p.name) + '"' + (p.name === val ? ' selected' : '') + '>' + esc(p.name) + ' (' + p.type + ')</option>';
    }
    return '<select id="f-' + path + '" onchange="setVal(\\'' + path + '\\', this.value); refreshModelSelect(\\'' + path + '\\')">' + opts + '</select>';
}

function renderGpuSelect(val, path) {
    const providers = CONFIG.providers || [];
    let opts = '<option value="">— None —</option>';
    for (const p of providers) {
        const gpus = p.gpus || [];
        for (let i = 0; i < gpus.length; i++) {
            const g = gpus[i];
            const key = p.name + ':' + i;
            const label = g.label || ('GPU ' + i);
            const vram = g.vram_gb ? ' — ' + g.vram_gb + ' GB' : '';
            opts += '<option value="' + esc(key) + '"' + (key === val ? ' selected' : '') + '>' + esc(p.name) + ' / ' + esc(label) + vram + '</option>';
        }
    }
    return '<select id="f-' + path + '" onchange="setVal(\\'' + path + '\\', this.value)">' + opts + '</select>';
}

function renderModelSelect(val, path) {
    // Provider wird zur Klick-Zeit aus dem Geschwister-Feld gelesen (nicht zur
    // Render-Zeit eingebrannt), sonst zeigt der Button nach einem Provider-
    // Wechsel weiter auf den alten Provider und holt die falsche Modell-Liste.
    let select = '<select id="f-' + path + '" onchange="setVal(\\'' + path + '\\', this.value)">';
    select += '<option value="' + esc(val) + '" selected>' + esc(val || '— select —') + '</option>';
    select += '</select>';
    select += ' <button class="btn btn-sm" onclick="loadModels(\\'' + path + '\\')">Load Models</button>';
    return select;
}

function renderImagegenSelect(val, path) {
    // Default MATCH: combobox with glob suggestions "backend:<name>" + free
    // text (values are "backend:<glob>" or bare globs). Resolved via
    // resolve_imagegen_target -> match_backend (by availability).
    const backends = CONFIG.image_generation?.backends || [];
    const sugg = new Set();
    for (const be of backends) {
        if (be.enabled === false) continue;  // do not suggest disabled backends
        sugg.add('backend:' + be.name);
    }
    let opts = '';
    for (const s of sugg) opts += '<option value="' + esc(s) + '">';
    return '<input type="text" id="f-' + path + '" list="dl-' + path + '" value="' + esc(val || '') + '" placeholder="e.g. backend:LocalAI-Flux" onchange="setVal(\\'' + path + '\\', this.value)"><datalist id="dl-' + path + '">' + opts + '</datalist>';
}

function renderImagegenBackendSelect(val, path) {
    // ALL image backends (Together, CivitAI, LocalAI, ...)
    const backends = CONFIG.image_generation?.backends || [];
    let opts = '<option value="">— None —</option>';
    for (const be of backends) {
        const lbl = be.name + (be.api_type ? ' (' + be.api_type + ')' : '');
        opts += '<option value="' + esc(be.name) + '"' + (be.name === val ? ' selected' : '') + '>' + esc(lbl) + '</option>';
    }
    // onchange: setVal + Geschwister-Modell-Select neu fuellen falls vorhanden
    return '<select id="f-' + path + '" onchange="setVal(\\'' + path + '\\', this.value); refreshImagegenModelSelect(\\'' + path + '\\')">' + opts + '</select>';
}

// Geschwister-Modell-Select neu laden wenn Backend gewechselt wird
function refreshImagegenModelSelect(backendPath) {
    const parts = backendPath.split('.');
    parts[parts.length - 1] = 'model';
    const modelPath = parts.join('.');
    const modelEl = document.getElementById('f-' + modelPath);
    if (!modelEl) return;
    const backendName = getVal(backendPath) || '';
    if (!backendName) {
        modelEl.innerHTML = '<option value="">— Backend zuerst waehlen —</option>';
        return;
    }
    loadImagegenBackendModels(modelPath, backendName);
}

let IMAGEGEN_MODELS_CACHE = {};

async function loadImagegenBackendModels(path, backendName) {
    const sel = document.getElementById('f-' + path);
    if (!sel) return;
    const currentVal = sel.value || getVal(path) || '';
    if (!IMAGEGEN_MODELS_CACHE[backendName]) {
        sel.innerHTML = '<option>Loading...</option>';
        try {
            const resp = await fetch('/admin/settings/imagegen-backends/' + encodeURIComponent(backendName) + '/models',
                { credentials: 'same-origin' });
            const data = await resp.json();
            if (data.error) toast('Loading models failed: ' + data.error, 'error');
            const list = data.models || [];
            if (list.length > 0) IMAGEGEN_MODELS_CACHE[backendName] = list;
        } catch (e) {
            toast('Loading models failed: ' + e.message, 'error');
        }
    }
    const models = IMAGEGEN_MODELS_CACHE[backendName] || [];
    let opts = '<option value="">— Backend-Default —</option>';
    for (const m of models) {
        opts += '<option value="' + esc(m) + '"' + (m === currentVal ? ' selected' : '') + '>' + esc(m) + '</option>';
    }
    if (currentVal && !models.includes(currentVal)) {
        opts = '<option value="' + esc(currentVal) + '" selected>' + esc(currentVal) + ' (custom)</option>' + opts;
    }
    sel.innerHTML = opts;
}

// Backend selection for imagegen_target_select fields.
// Value format: "backend:<name>" (as served by /settings/imagegen-targets)
let IMAGEGEN_TARGETS_CACHE = null;

async function loadImagegenTargets() {
    if (IMAGEGEN_TARGETS_CACHE) return IMAGEGEN_TARGETS_CACHE;
    try {
        const r = await fetch('/admin/settings/imagegen-targets', { credentials: 'same-origin' });
        const d = await r.json();
        IMAGEGEN_TARGETS_CACHE = d.targets || [];
    } catch {
        IMAGEGEN_TARGETS_CACHE = [];
    }
    return IMAGEGEN_TARGETS_CACHE;
}

function renderImagegenTargetSelect(val, path) {
    // Initial mit aktuellem Wert rendern; Liste wird async nachgeladen
    let html = '<select id="f-' + path + '" onchange="setVal(\\'' + path + '\\', this.value)">';
    if (val) html += '<option value="' + esc(val) + '" selected>' + esc(val) + '</option>';
    html += '<option value="">— Auto (Cloud bevorzugt) —</option>';
    html += '</select>';
    // Async populate
    setTimeout(async () => {
        const targets = await loadImagegenTargets();
        const sel = document.getElementById('f-' + path);
        if (!sel) return;
        let opts = '<option value="">— Auto (Cloud bevorzugt) —</option>';
        for (const t of targets) {
            const dis = t.available ? '' : ' disabled';
            const tag = t.available ? '' : ' (offline)';
            const sl = t.value === val ? ' selected' : '';
            opts += '<option value="' + esc(t.value) + '"' + sl + dis + '>' + esc(t.label + tag) + '</option>';
        }
        sel.innerHTML = opts;
    }, 0);
    return html;
}

function renderImagegenModelSelect(val, path) {
    // Backend aus Geschwister-Feld lesen
    const parts = path.split('.');
    parts[parts.length - 1] = 'backend';
    const backendPath = parts.join('.');
    const backendName = getVal(backendPath) || '';
    let html = '<select id="f-' + path + '" onchange="setVal(\\'' + path + '\\', this.value)">';
    if (val) {
        html += '<option value="' + esc(val) + '" selected>' + esc(val) + '</option>';
    } else {
        html += '<option value="">— Backend-Default —</option>';
    }
    html += '</select>';
    html += ' <button class="btn btn-sm" onclick="loadImagegenBackendModels(\\'' + path + '\\', \\'' + esc(backendName) + '\\')">Load Models</button>';
    return html;
}

// Editierbares Modell-Combo fuer Image-Backends: Freitext (CivitAI-URN, manuelles
// Tippen) + Datalist-Vorschlaege ueber "Load Models" (holt /v1/models vom Backend).
function renderImagegenModelCombo(val, path) {
    // base = das Backend-Item (z.B. image_generation.backends.2); name/api_* werden
    // zur Klick-Zeit aus den Geschwister-Feldern gelesen, damit "URL eintragen ->
    // Load Models" auch OHNE vorheriges Speichern funktioniert.
    const parts = path.split('.');
    const base = parts.slice(0, -1).join('.');
    const dlId = 'dl-' + path.replace(/[^a-zA-Z0-9]/g, '-');
    let html = '<input type="text" list="' + dlId + '" id="f-' + path + '" value="' + esc(val) + '" placeholder="z.B. flux.2-klein-4b" onchange="setVal(\\'' + path + '\\', this.value)">';
    html += '<datalist id="' + dlId + '"></datalist>';
    html += ' <button class="btn btn-sm" type="button" onclick="loadImagegenModelCombo(\\'' + path + '\\', \\'' + base + '\\')">Load Models</button>';
    return html;
}

async function loadImagegenModelCombo(path, base) {
    const name = getVal(base + '.name') || '';
    const apiType = getVal(base + '.api_type') || '';
    const apiUrl = getVal(base + '.api_url') || '';
    const apiKey = getVal(base + '.api_key') || '';
    const dlId = 'dl-' + path.replace(/[^a-zA-Z0-9]/g, '-');
    const dl = document.getElementById(dlId);
    if (!dl) return;
    if (!apiUrl) { toast('Bitte zuerst die API URL eintragen', 'error'); return; }
    try {
        const qs = new URLSearchParams({ api_type: apiType, api_url: apiUrl, api_key: apiKey }).toString();
        const resp = await fetch('/admin/settings/imagegen-backends/' + encodeURIComponent(name || '_new') + '/models?' + qs, { credentials: 'same-origin' });
        const data = await resp.json();
        if (data.error) { toast('Load Models: ' + data.error, 'error'); return; }
        const list = data.models || [];
        dl.innerHTML = list.map(m => '<option value="' + esc(m) + '"></option>').join('');
        toast(list.length ? (list.length + ' Modelle geladen') : 'Keine Modelle gefunden', list.length ? 'success' : 'error');
    } catch (e) {
        toast('Load Models fehlgeschlagen: ' + e.message, 'error');
    }
}

// ── Array/Dict Items ──
// _itemLabel: gleiche Logik wie in renderArrayItem — fuer Sortierung.
// labelField darf ein String ODER ein Array sein. Bei Array gewinnt der erste
// nicht-leere Wert (z.B. ["name", "model"] -> name wenn gesetzt, sonst model).
function _itemLabel(item, labelField, fallback) {
    if (!item) return String(fallback || '');
    const fields = Array.isArray(labelField) ? labelField : [labelField];
    for (const f of fields) {
        const v = item[f];
        if (v !== undefined && v !== null && String(v).trim() !== '') return String(v);
    }
    return String(fallback || '');
}

function renderArrayItems(def, items, path) {
    let html = '<div id="arr-' + path + '">';
    // Index erhalten (Pfade referenzieren echten Array-Index), Reihenfolge
    // alphabetisch wenn def.sort_alphabetically gesetzt ist.
    const order = items.map((it, i) => ({ idx: i, label: _itemLabel(it, def.item_label_field, 'Item ' + i) }));
    if (def.sort_alphabetically) {
        order.sort((a, b) => a.label.localeCompare(b.label, undefined, { sensitivity: 'base' }));
    }
    for (const o of order) {
        html += renderArrayItem(def, items[o.idx], path + '[' + o.idx + ']', o.idx, def.item_label_field);
    }
    html += '</div>';
    return html;
}

function renderDictItems(def, items, path) {
    let html = '<div id="arr-' + path + '">';
    const entries = Object.entries(items).map(([k, item]) => ({ key: k, item, label: _itemLabel(item, def.item_label_field, k) }));
    if (def.sort_alphabetically) {
        entries.sort((a, b) => a.label.localeCompare(b.label, undefined, { sensitivity: 'base' }));
    }
    for (const e of entries) {
        html += renderArrayItem(def, e.item, path + '.' + e.key, e.key, def.item_label_field);
    }
    html += '</div>';
    return html;
}

function renderArrayItem(def, item, path, index, labelField) {
    const label = _itemLabel(item, labelField, 'Item ' + index);
    const openClass = OPEN_ITEMS.has(path) ? ' open' : '';
    let html = '<div class="array-item' + openClass + '" id="item-' + path + '">';
    html += '<div class="array-item-header" onclick="toggleArrayItem(this, \\'' + path + '\\')">';
    html += '<span class="chevron">▶</span> ';
    html += '<span class="title" style="margin-left:6px;">' + esc(label) + '</span>';
    if (item.enabled === false) html += '<span class="badge">deaktiviert</span>';
    if (item.type) html += '<span class="badge">' + esc(item.type || item.api_type || '') + '</span>';
    html += '<button class="btn btn-sm" style="margin-left:8px;" title="Als neuen Eintrag duplizieren" onclick="event.stopPropagation(); duplicateItem(\\'' + path + '\\')">⧉</button>';
    html += '<button class="btn btn-sm btn-danger" style="margin-left:4px;" onclick="event.stopPropagation(); removeItem(\\'' + path + '\\')">✕</button>';
    html += '</div>';
    html += '<div class="array-item-body">';
    html += renderFields(def.fields, item, path);
    html += '</div></div>';
    return html;
}

// ── Master-detail (table left, editor right) ──
// Returns the ordered entry list for array OR dict sub-arrays. Each entry
// carries its full path (image_generation.backends[0] or dict-keyed paths) —
// identical to the paths renderArrayItem/setVal use.
function _mdOrder(def, items, path) {
    let order;
    if (def.is_dict) {
        order = Object.entries(items || {}).map(([k, it]) => ({
            itemPath: path + '.' + k, item: it,
            label: _itemLabel(it, def.item_label_field, k),
        }));
    } else {
        order = (items || []).map((it, i) => ({
            itemPath: path + '[' + i + ']', item: it,
            label: _itemLabel(it, def.item_label_field, 'Item ' + i),
        }));
    }
    if (def.sort_alphabetically) {
        order.sort((a, b) => a.label.localeCompare(b.label, undefined, { sensitivity: 'base' }));
    }
    return order;
}

function renderMdCell(col, item) {
    const v = item ? item[col.field] : undefined;
    if (col.kind === 'status') {
        const on = v !== false;
        return '<span class="md-status ' + (on ? 'on' : 'off') + '">' + (on ? '● on' : '○ off') + '</span>';
    }
    if (v === undefined || v === null || v === '') return '<span class="md-empty">—</span>';
    return esc(String(v));
}

function renderMasterDetail(def, items, path) {
    const order = _mdOrder(def, items, path);
    // Aktuelle Auswahl validieren — sonst ersten Eintrag waehlen.
    let sel = SELECTED_ITEM[path];
    if (!order.some(o => o.itemPath === sel)) sel = order.length ? order[0].itemPath : null;
    SELECTED_ITEM[path] = sel;

    const cols = def.list_columns || [{ field: def.item_label_field || 'name', label: 'Name' }];

    let html = '<div class="md-grid">';
    // Links: Tabelle
    html += '<div class="md-list">';
    html += '<table class="md-table"><thead><tr>';
    for (const c of cols) html += '<th>' + esc(c.label) + '</th>';
    html += '</tr></thead><tbody>';
    for (const o of order) {
        const active = (o.itemPath === sel) ? ' active' : '';
        html += '<tr class="md-row' + active + '" onclick="selectMasterItem(\\'' + path + '\\', \\'' + o.itemPath + '\\')">';
        for (const c of cols) html += '<td>' + renderMdCell(c, o.item) + '</td>';
        html += '</tr>';
    }
    if (!order.length) {
        html += '<tr><td colspan="' + cols.length + '"><span class="md-empty">Keine Eintraege</span></td></tr>';
    }
    html += '</tbody></table>';
    html += '<button class="btn btn-sm" style="margin-top:10px;" onclick="addArrayItem(\\'' + path + '\\', \\'' + (def.is_dict ? 'dict' : 'array') + '\\')">+ Add</button>';
    html += '</div>';
    // Rechts: Detail
    html += '<div class="md-detail" id="detail-' + path + '">';
    html += renderMasterDetailBody(def, items, path, sel);
    html += '</div>';
    html += '</div>';
    return html;
}

function renderMasterDetailBody(def, items, path, sel) {
    if (!sel) return '<div class="md-empty-detail">Eintrag links auswaehlen oder neu anlegen.</div>';
    let item;
    if (def.is_dict) {
        item = (items || {})[sel.slice(path.length + 1)];
    } else {
        const m = sel.match(/\\[(\\d+)\\]$/);
        item = m ? (items || [])[parseInt(m[1], 10)] : null;
    }
    if (!item) return '<div class="md-empty-detail">Eintrag links auswaehlen oder neu anlegen.</div>';

    const label = _itemLabel(item, def.item_label_field, 'Eintrag');
    let html = '<div class="md-detail-head">';
    html += '<span class="md-detail-title">' + esc(label) + '</span>';
    html += '<span style="flex:1;"></span>';
    html += '<button class="btn btn-sm" title="Als neuen Eintrag duplizieren" onclick="duplicateItem(\\'' + sel + '\\')">⧉</button>';
    html += '<button class="btn btn-sm btn-danger" style="margin-left:4px;" title="Loeschen" onclick="removeItem(\\'' + sel + '\\')">✕</button>';
    html += '</div>';
    html += renderFields(def.fields, item, sel);
    return html;
}

function selectMasterItem(path, itemPath) {
    SELECTED_ITEM[path] = itemPath;
    renderSection(ACTIVE_SECTION);
}

// ── Task/Order List (llm_routing.tasks) ──
let LLM_TASKS_CACHE = null;

async function loadLlmTasks(forceRefresh) {
    if (LLM_TASKS_CACHE && !forceRefresh) return LLM_TASKS_CACHE;
    try {
        // cache-bust per Query-Param damit Browser nicht aus dem HTTP-Cache
        // serviert (z.B. nach Server-Neustart mit neuen Sub-Tasks).
        const resp = await fetch('/admin/settings/llm-tasks?_=' + Date.now(),
            { credentials: 'same-origin', cache: 'no-store' });
        LLM_TASKS_CACHE = await resp.json();
    } catch (e) {
        LLM_TASKS_CACHE = [];
    }
    return LLM_TASKS_CACHE;
}

function renderTaskOrderList(items, path, f) {
    // items: [{task: 'chat_stream', order: 1}, ...]
    let html = '<div class="field"><label>' + f.label + '</label><div class="input-wrap">';
    if (f.description) html += '<div class="desc" style="margin-bottom:6px;">' + f.description + '</div>';
    html += '<div id="tasks-' + path + '">';
    for (let i = 0; i < items.length; i++) {
        html += renderTaskOrderRow(items[i] || {}, path, i);
    }
    html += '</div>';
    html += '<div style="margin-top:6px; display:flex; flex-wrap:wrap; gap:4px;">';
    html += '<button class="btn btn-sm" onclick="addTaskOrderRow(\\'' + path + '\\')">+ Task</button>';
    html += '<button class="btn btn-sm" title="Add all Image-Input tasks not yet assigned" onclick="addTaskGroup(\\'' + path + '\\', \\'image\\')">+ All Image</button>';
    html += '<button class="btn btn-sm" title="Add all Tool tasks not yet assigned" onclick="addTaskGroup(\\'' + path + '\\', \\'tool\\')">+ All Tools</button>';
    html += '<button class="btn btn-sm" title="Add all Large Chat Model tasks not yet assigned" onclick="addTaskGroup(\\'' + path + '\\', \\'chat\\')">+ All Chat</button>';
    html += '<button class="btn btn-sm" title="Add all Small Helper tasks not yet assigned" onclick="addTaskGroup(\\'' + path + '\\', \\'helper\\')">+ All Helper</button>';
    html += '<button class="btn btn-sm" title="Add all Embedding tasks not yet assigned" onclick="addTaskGroup(\\'' + path + '\\', \\'embedding\\')">+ All Embedding</button>';
    html += '<button class="btn btn-sm" title="Add all Tool/Helper tasks that run WITHOUT thinking" onclick="addTaskGroupByThinking(\\'' + path + '\\', false)">+ All No-Thinking</button>';
    html += '<button class="btn btn-sm" title="Add all Tool/Helper tasks that should run WITH thinking (🧠)" onclick="addTaskGroupByThinking(\\'' + path + '\\', true)">+ All Thinking 🧠</button>';
    html += '</div>';
    // Bulk-Action: alle Task-Orders dieses LLMs auf einen Wert setzen
    html += '<div style="margin-top:6px; display:flex; align-items:center; gap:6px;">';
    html += '<span style="font-size:12px; color:#8b949e;">Set order for all tasks:</span>';
    html += '<input type="number" id="bulk-order-input-' + path + '" min="1" step="1" placeholder="1" style="max-width:70px;">';
    html += '<button class="btn btn-sm" onclick="setAllTaskOrders(\\'' + path + '\\')">Apply</button>';
    html += '</div>';
    html += '</div></div>';
    // Async: Dropdowns fuellen nachdem DOM da ist
    setTimeout(() => populateTaskSelects(path), 0);
    return html;
}

function renderTaskOrderRow(item, path, i) {
    const task = item.task || '';
    const order = (item.order !== undefined ? item.order : 1);
    let html = '<div class="gpu-row" id="taskrow-' + path + '-' + i + '">';
    html += '<select data-taskrow="' + path + '-' + i + '" style="flex:3;" onchange="setVal(\\'' + path + '[' + i + '].task\\', this.value)">';
    html += '<option value="' + esc(task) + '" selected>' + esc(task || '— select —') + '</option>';
    html += '</select>';
    html += '<input type="number" value="' + order + '" min="1" step="1" style="max-width:70px;" title="Order" onchange="setVal(\\'' + path + '[' + i + '].order\\', parseInt(this.value) || 1)">';
    html += '<button class="btn btn-sm btn-danger" onclick="removeTaskOrderRow(\\'' + path + '\\', ' + i + ')">✕</button>';
    html += '</div>';
    return html;
}

async function populateTaskSelects(path) {
    const tasks = await loadLlmTasks();
    // Group tasks by category for guidance — show grouped <optgroup>s in the dropdown.
    const order = ['image', 'tool', 'chat', 'helper', 'embedding', ''];
    const grouped = {};
    for (const t of tasks) {
        const cat = t.category || '';
        (grouped[cat] = grouped[cat] || []).push(t);
    }
    const selects = document.querySelectorAll('select[data-taskrow^="' + path + '-"]');
    selects.forEach(sel => {
        const current = sel.value;
        let opts = '<option value="">— select —</option>';
        for (const cat of order) {
            const list = grouped[cat];
            if (!list || !list.length) continue;
            const groupLabel = list[0].category_label || 'Other';
            opts += '<optgroup label="' + esc(groupLabel) + '">';
            for (const t of list) {
                opts += '<option value="' + esc(t.id) + '"' + (t.id === current ? ' selected' : '') + '>'
                     + esc(t.label) + (t.thinking ? ' 🧠' : '') + ' — ' + esc(t.id) + '</option>';
            }
            opts += '</optgroup>';
        }
        sel.innerHTML = opts;
    });
    applyEmbedVisibility();
}

// True, wenn der Routing-Eintrag mindestens einen Task der Gruppe "embedding"
// bedient (Embedding-Modelle nutzen kein temperature/max_tokens).
function _entryIsEmbedding(data) {
    if (!data || !Array.isArray(data.tasks) || !data.tasks.length) return false;
    const cache = LLM_TASKS_CACHE || [];
    const embedIds = new Set(cache.filter(t => t.category === 'embedding').map(t => t.id));
    if (!embedIds.size) embedIds.add('pose_embedding');  // Fallback bis Cache geladen
    return data.tasks.some(it => it && embedIds.has(it.task));
}

// Blendet temperature/max_tokens bei Embedding-Eintraegen aus (Post-Pass, damit
// es auch live beim Hinzufuegen/Entfernen des Tasks toggelt).
function applyEmbedVisibility() {
    document.querySelectorAll('[data-embedhide-entry]').forEach(el => {
        const entryPath = el.getAttribute('data-embedhide-entry');
        const entry = getVal(entryPath);
        el.style.display = _entryIsEmbedding(entry) ? 'none' : '';
    });
}

function addTaskOrderRow(path) {
    const obj = _ensureContainer(path, 'array');
    // order=1 is the default primary slot. Increase only when this LLM is meant
    // as a fallback for a task another LLM already serves at order=1.
    obj.push({ task: '', order: 1 });
    rerenderTaskOrderList(path);
}

async function addTaskGroup(path, category) {
    const tasks = await loadLlmTasks();
    const obj = _ensureContainer(path, 'array');
    const existing = new Set((obj || []).map(it => it && it.task).filter(Boolean));
    let added = 0;
    for (const t of tasks) {
        if (t.category !== category) continue;
        if (existing.has(t.id)) continue;
        obj.push({ task: t.id, order: 1 });
        added++;
    }
    rerenderTaskOrderList(path);
    if (added) toast('Added ' + added + ' task' + (added === 1 ? '' : 's'), 'success');
    else toast('All tasks of this group are already assigned', 'success');
}

// Bulk-add tool/helper tasks by their thinking-group (gateway thinking vs
// no-thinking alias). wantThinking=true → only tasks flagged thinking; false →
// the rest of tool/helper. Chat/image/embedding tasks are never included here.
async function addTaskGroupByThinking(path, wantThinking) {
    const tasks = await loadLlmTasks();
    const obj = _ensureContainer(path, 'array');
    const existing = new Set((obj || []).map(it => it && it.task).filter(Boolean));
    let added = 0;
    for (const t of tasks) {
        if (t.category !== 'tool' && t.category !== 'helper') continue;
        if (!!t.thinking !== !!wantThinking) continue;
        if (existing.has(t.id)) continue;
        obj.push({ task: t.id, order: 1 });
        added++;
    }
    rerenderTaskOrderList(path);
    if (added) toast('Added ' + added + ' task' + (added === 1 ? '' : 's'), 'success');
    else toast('All tasks of this group are already assigned', 'success');
}

function removeTaskOrderRow(path, index) {
    const parts = parsePath(path);
    let obj = CONFIG;
    for (const p of parts) obj = obj[p];
    obj.splice(index, 1);
    rerenderTaskOrderList(path);
}

function setAllTaskOrders(path) {
    const inputEl = document.getElementById('bulk-order-input-' + path);
    if (!inputEl) return;
    const order = parseInt(inputEl.value, 10);
    if (!order || order < 1) {
        toast('Please enter an order value >= 1', 'error');
        return;
    }
    const parts = parsePath(path);
    let obj = CONFIG;
    for (const p of parts) obj = obj && obj[p];
    if (!Array.isArray(obj) || !obj.length) {
        toast('No tasks assigned', 'error');
        return;
    }
    for (const it of obj) {
        if (it && typeof it === 'object') it.order = order;
    }
    rerenderTaskOrderList(path);
    toast('Order=' + order + ' fuer alle ' + obj.length + ' Tasks gesetzt', 'success');
}

function rerenderTaskOrderList(path) {
    // Re-render nur den Tasks-Container statt die ganze Section — damit
    // das umgebende Array-Item offen bleibt.
    const parts = parsePath(path);
    let obj = CONFIG;
    for (const p of parts) obj = obj && obj[p];
    const items = Array.isArray(obj) ? obj : [];
    const wrap = document.getElementById('tasks-' + path);
    if (!wrap) { renderSection(ACTIVE_SECTION); return; }
    let html = '';
    for (let i = 0; i < items.length; i++) {
        html += renderTaskOrderRow(items[i] || {}, path, i);
    }
    wrap.innerHTML = html;
    populateTaskSelects(path);
    // Sichtweise rechts mit aktualisieren wenn wir im llm_routing-Tab sind
    if (ACTIVE_SECTION === 'llm_routing') {
        renderLlmTaskView(CONFIG.llm_routing || []);
    }
}

// ── GPU Field ──
function renderGpuField(gpus, path) {
    // Backend-Kontext: image_generation.backends[N].gpus — die GPU dort ist nur
    // Anzeige/Beszel-Mapping (kein types-Feld, max_concurrent lebt auf dem
    // Backend selbst), deshalb die Spalten weglassen.
    const isBackend = path.indexOf('image_generation.backends') !== -1;
    const label = isBackend ? 'GPUs (optional — Anzeige/Beszel)' : 'GPUs';
    let html = '<div class="field"><label>' + label + '</label><div class="input-wrap">';
    html += '<div id="gpu-' + path + '">';
    for (let i = 0; i < gpus.length; i++) {
        const g = gpus[i];
        html += '<div class="gpu-row">';
        html += '<input type="text" value="' + esc(g.label || '') + '" placeholder="Label" style="max-width:120px;" onchange="setVal(\\'' + path + '[' + i + '].label\\', this.value)">';
        html += '<input type="number" value="' + (g.vram_gb || 0) + '" placeholder="VRAM GB" style="max-width:80px;" onchange="setVal(\\'' + path + '[' + i + '].vram_gb\\', parseInt(this.value))">';
        html += '<input type="text" value="' + esc(g.match_name || '') + '" placeholder="Match-Name (z.B. 4070)" title="Case-insensitive Substring im Beszel-GPU-Namen — wird zuerst probiert (stabil ueber Reboots)" style="max-width:140px;" onchange="setVal(\\'' + path + '[' + i + '].match_name\\', this.value)">';
        html += '<input type="text" value="' + esc(g.device || '') + '" placeholder="Device (Fallback)" title="Beszel device-id — nur noetig wenn Match-Name nicht eindeutig greift (z.B. zwei gleiche Modelle, oder Beszel meldet falschen Namen)" style="max-width:100px;opacity:0.7;" onchange="setVal(\\'' + path + '[' + i + '].device\\', this.value)">';
        if (!isBackend) {
            const typesStr = Array.isArray(g.types) ? g.types.join(',') : (g.types || '');
            html += '<input type="text" value="' + esc(typesStr) + '" placeholder="ollama,openai" onchange="setVal(\\'' + path + '[' + i + '].types\\', this.value.split(\\',\\').map(s=>s.trim()))">';
            html += '<input type="number" value="' + (g.max_concurrent || 1) + '" placeholder="MC" title="Max Concurrent" min="1" max="50" style="max-width:55px;" onchange="setVal(\\'' + path + '[' + i + '].max_concurrent\\', parseInt(this.value) || 1)">';
        }
        html += '<button class="btn btn-sm btn-danger" onclick="removeSubItem(\\'' + path + '\\', ' + i + ')">✕</button>';
        html += '</div>';
    }
    html += '</div>';
    html += '<button class="btn btn-sm" style="margin-top:4px;" onclick="addGpu(\\'' + path + '\\')">+ GPU</button>';
    html += '</div></div>';
    return html;
}

// ── Data Access ──
function setVal(path, value) {
    const parts = parsePath(path);
    let obj = CONFIG;
    for (let i = 0; i < parts.length - 1; i++) {
        const p = parts[i];
        if (obj[p] === undefined) {
            obj[p] = (typeof parts[i+1] === 'number') ? [] : {};
        }
        obj = obj[p];
    }
    obj[parts[parts.length - 1]] = value;
}

function getVal(path) {
    const parts = parsePath(path);
    let obj = CONFIG;
    for (const p of parts) {
        if (obj === undefined || obj === null) return undefined;
        obj = obj[p];
    }
    return obj;
}

function parsePath(path) {
    // "providers[0].name" => ["providers", 0, "name"]
    const result = [];
    for (const part of path.split('.')) {
        const m = part.match(/^([^\\[]+)(?:\\[(\\d+)\\])?$/);
        if (m) {
            result.push(m[1]);
            if (m[2] !== undefined) result.push(parseInt(m[2]));
        } else {
            result.push(part);
        }
    }
    return result;
}

function setLoraVal(path, index, field, value) {
    const parts = parsePath(path);
    let obj = CONFIG;
    for (const p of parts) {
        if (obj[p] === undefined) obj[p] = [];
        obj = obj[p];
    }
    while (obj.length <= index) obj.push({ file: '', strength: 1 });
    obj[index][field] = value;
}

// Walks `path` inside CONFIG, creating any missing levels. Intermediate levels
// are always created as {}; only the leaf takes the requested `leafType`
// ('array' or 'dict'). Returns the leaf container.
function _ensureContainer(path, leafType) {
    const parts = parsePath(path);
    let obj = CONFIG;
    for (let i = 0; i < parts.length; i++) {
        const p = parts[i];
        if (obj[p] === undefined) {
            obj[p] = (i === parts.length - 1)
                ? (leafType === 'dict' ? {} : [])
                : {};
        }
        obj = obj[p];
    }
    return obj;
}

// ── Actions ──
function addArrayItem(path, type) {
    const obj = _ensureContainer(path, type);
    if (type === 'dict') {
        const id = prompt('New entry key:');
        if (!id) return;
        // Keep the key dot-free: the editor addresses fields via dot notation
        // and split('.') breaks on a dot INSIDE the key. The display name
        // keeps the original input.
        const key = id.replace(/[.\\[\\]]/g, ' ').replace(/\\s+/g, ' ').trim();
        if (!key) { toast('Invalid key', 'error'); return; }
        if (obj[key] !== undefined) { toast('Entry already exists: ' + key, 'error'); return; }
        obj[key] = { name: id };
        // Select the new entry in the master-detail view (no-op for accordion).
        SELECTED_ITEM[path] = path + '.' + key;
    } else {
        if (path === 'llm_routing') {
            obj.push({ name: '', enabled: true, preload_on_startup: false, provider: '', model: '', temperature: 0.7, tasks: [] });
        } else if (path === 'content_marketplace.catalogs') {
            obj.push({ name: '', url: '', auth_token: '', enabled: true });
        } else {
            obj.push({ name: 'New', enabled: true, gpus: [] });
        }
        SELECTED_ITEM[path] = path + '[' + (obj.length - 1) + ']';
    }
    renderSection(ACTIVE_SECTION);
}

function removeItem(path) {
    if (!confirm('Remove this item?')) return;
    const parts = parsePath(path);
    let obj = CONFIG;
    for (let i = 0; i < parts.length - 1; i++) {
        obj = obj[parts[i]];
    }
    const last = parts[parts.length - 1];
    if (typeof last === 'number') {
        obj.splice(last, 1);
    } else {
        delete obj[last];
    }
    // Auswahl im Master-Detail zuruecksetzen — renderMasterDetail faellt dann
    // auf den ersten verbliebenen Eintrag zurueck.
    const arrPath = (typeof last === 'number')
        ? path.replace(/\\[\\d+\\]$/, '')
        : path.replace(/\\.[^.\\[\\]]+$/, '');
    delete SELECTED_ITEM[arrPath];
    renderSection(ACTIVE_SECTION);
}

// Duplicates an array or dict entry (LLM routing, backends, ...). For dicts
// a new key is prompted; for arrays the clone is appended after the original.
// `name` fields get a "(Kopie)" suffix so the duplicate is distinguishable.
function duplicateItem(path) {
    const parts = parsePath(path);
    let parent = CONFIG;
    for (let i = 0; i < parts.length - 1; i++) {
        parent = parent[parts[i]];
    }
    const last = parts[parts.length - 1];
    const original = (typeof last === 'number') ? parent[last] : parent[last];
    if (!original) { toast('Eintrag nicht gefunden', 'error'); return; }
    // Deep clone — Defaults sollen nicht mit dem Original geteilt werden.
    const copy = JSON.parse(JSON.stringify(original));
    if (copy && typeof copy === 'object' && 'name' in copy && copy.name) {
        copy.name = String(copy.name) + ' (Kopie)';
    }
    if (typeof last === 'number') {
        // Array: direkt hinter Original einfuegen
        parent.splice(last + 1, 0, copy);
        const arrPath = path.replace(/\\[\\d+\\]$/, '');
        SELECTED_ITEM[arrPath] = arrPath + '[' + (last + 1) + ']';
    } else {
        // Dict: neuen Key vom User abfragen — punktfrei halten (Dot-Notation
        // im Editor zerbricht sonst, s. addArrayItem).
        const rawKey = prompt('Neuer Schluessel fuer den Klon:', String(last) + '_copy');
        if (!rawKey) return;
        const newKey = rawKey.replace(/[.\\[\\]]/g, ' ').replace(/\\s+/g, ' ').trim();
        if (!newKey) { toast('Ungueltiger Schluessel', 'error'); return; }
        if (parent[newKey] !== undefined) { toast('Schluessel existiert bereits: ' + newKey, 'error'); return; }
        parent[newKey] = copy;
        const arrPath = path.replace(/\\.[^.\\[\\]]+$/, '');
        SELECTED_ITEM[arrPath] = arrPath + '.' + newKey;
    }
    renderSection(ACTIVE_SECTION);
}

function removeSubItem(path, index) {
    const parts = parsePath(path);
    let obj = CONFIG;
    for (const p of parts) obj = obj[p];
    obj.splice(index, 1);
    renderSection(ACTIVE_SECTION);
}

function addGpu(path) {
    const parts = parsePath(path);
    let obj = CONFIG;
    for (const p of parts) {
        if (obj[p] === undefined) obj[p] = [];
        obj = obj[p];
    }
    const isBackend = path.indexOf('image_generation.backends') !== -1;
    const item = isBackend
        ? { vram_gb: 0, label: '', match_name: '', device: '' }
        : { vram_gb: 0, types: ['openai'], match_name: '', device: '' };
    obj.push(item);
    renderSection(ACTIVE_SECTION);
}

async function loadModels(path, provName) {
    if (!provName) {
        // Try to detect from sibling
        const parts = path.split('.');
        parts[parts.length - 1] = 'provider';
        provName = getVal(parts.join('.'));
    }
    if (!provName) { toast('Select a provider first', 'error'); return; }

    const sel = document.getElementById('f-' + path);
    if (!sel) return;
    const currentVal = sel.value;

    // Cache: leere Listen NICHT cachen (sonst blockt eine fehlgeschlagene
    // Abfrage alle Retry-Versuche bis zum Page-Reload).
    if (!PROVIDERS_CACHE[provName] || PROVIDERS_CACHE[provName].length === 0) {
        sel.innerHTML = '<option>Loading...</option>';
        try {
            const resp = await fetch('/admin/settings/providers/' + encodeURIComponent(provName) + '/models', { credentials: 'same-origin' });
            const data = await resp.json();
            if (data.error) { toast('Error: ' + data.error, 'error'); }
            const list = data.models || [];
            if (list.length > 0) {
                PROVIDERS_CACHE[provName] = list;
                PROVIDERS_VISION[provName] = new Set(data.vision || []);
            } else {
                delete PROVIDERS_CACHE[provName];
            }
        } catch (e) {
            toast('Failed to load models: ' + e.message, 'error');
            delete PROVIDERS_CACHE[provName];
        }
    }

    const models = PROVIDERS_CACHE[provName];
    const vis = PROVIDERS_VISION[provName] || new Set();
    let opts = '<option value="">— select —</option>';
    for (const m of models) {
        opts += '<option value="' + esc(m) + '"' + (m === currentVal ? ' selected' : '') + '>' + esc(m) + (vis.has(m) ? ' (vision)' : '') + '</option>';
    }
    sel.innerHTML = opts;
    if (currentVal && !models.includes(currentVal)) {
        sel.innerHTML = '<option value="' + esc(currentVal) + '" selected>' + esc(currentVal) + ' (not on server)</option>' + opts;
    }
}

function refreshModelSelect(provPath) {
    // When provider changes, clear model cache
    const parts = provPath.split('.');
    parts[parts.length - 1] = 'model';
    const modelPath = parts.join('.');
    const provName = getVal(provPath);
    if (provName) loadModels(modelPath, provName);
}

async function validateConfig() {
    const btn = document.getElementById('btn-validate');
    btn.disabled = true;
    btn.textContent = 'Validating...';
    try {
        const resp = await fetch('/admin/settings/validate', {
            method: 'POST',
            headers: authHeaders(),
            body: JSON.stringify(CONFIG)
        });
        const result = await resp.json();
        const issues = result.issues || [];
        const content = document.getElementById('content');

        let html = '<div class="validate-results ' + (result.errors > 0 ? 'has-errors' : 'all-ok') + '">';
        if (issues.length === 0) {
            html += '<h3>No issues found</h3>';
        } else {
            html += '<h3>' + result.errors + ' errors, ' + result.warnings + ' warnings</h3>';
            for (const issue of issues) {
                html += '<div class="validate-issue ' + issue.level + '">';
                html += '<span class="badge">' + (issue.level === 'error' ? 'ERROR' : 'WARN') + '</span>';
                html += '<span>' + esc(issue.message) + '</span>';
                html += '<span class="section-link" onclick="activateSection(\\'' + issue.section + '\\')">' + issue.section + '</span>';
                html += '</div>';
            }
        }
        html += '</div>';

        // Show below current section or as standalone
        if (ACTIVE_SECTION && !ACTIVE_SECTION.startsWith('_')) {
            content.insertAdjacentHTML('afterbegin', html);
        } else {
            content.innerHTML = html;
        }
        if (result.errors > 0) toast(result.errors + ' errors found', 'error');
        else if (result.warnings > 0) toast(result.warnings + ' Warnungen', 'success');
        else toast('Alles OK!', 'success');
    } catch (e) {
        toast('Validation failed: ' + e.message, 'error');
    }
    btn.disabled = false;
    btn.textContent = 'Validate';
}

// Generischer Action-Button-Handler — schickt POST/DELETE/etc an einen Endpoint
// mit Body aus angegebenen Geschwister-Feldern. Genutzt von schema-Type "button".
async function runActionButton(endpoint, method, path, bodyFrom, confirmMsg, btn, previewUrl) {
    if (confirmMsg && !confirm(confirmMsg)) return;
    const body = {};
    // Werte aus DOM lesen (frischste Quelle — auch wenn User getippt aber
    // noch nicht gespeichert hat). Fallback auf CONFIG, dann auf
    // f-input-element.value als letzten Strohhalm fuer Defaults.
    for (const fld of (bodyFrom || [])) {
        const sibling = path + '.' + fld;
        let v = undefined;
        // 1. Versuche das DOM-Input direkt
        const el = document.getElementById('f-' + sibling);
        if (el && 'value' in el) {
            v = el.value;
        }
        // 2. Fallback: gespeicherter CONFIG-Wert
        if (v === undefined || v === null || v === '') {
            v = getVal(sibling);
        }
        if (v !== undefined && v !== null && v !== '') body[fld] = v;
    }
    const origLabel = btn.textContent;
    btn.disabled = true;
    btn.textContent = '⏳ ' + origLabel;
    try {
        const opts = { method, headers: authHeaders(), credentials: 'same-origin' };
        if (method !== 'GET' && method !== 'DELETE') {
            opts.headers['Content-Type'] = 'application/json';
            opts.body = JSON.stringify(body);
        }
        const resp = await fetch(endpoint, opts);
        const data = await resp.json().catch(() => ({}));
        if (resp.ok) {
            const detail = data.bbox ? ` (bbox ${data.bbox.w}×${data.bbox.h})` : '';
            toast((data.status || 'OK') + detail, 'success');
            // Preview-Bild neu laden (Cache-Bust via Timestamp) und Meta refreshen
            if (previewUrl) {
                document.querySelectorAll('img[src^="' + previewUrl + '"]').forEach(img => {
                    img.src = previewUrl + '?_=' + Date.now();
                    img.style.display = '';
                    if (img.nextElementSibling) img.nextElementSibling.style.display = 'none';
                });
                if (typeof populateImagePreviewMetas === 'function') {
                    populateImagePreviewMetas();
                }
            }
        } else {
            toast('Error: ' + (data.detail || data.error || resp.status), 'error');
        }
    } catch (e) {
        toast('Call failed: ' + e.message, 'error');
    }
    btn.disabled = false;
    btn.textContent = origLabel;
}

async function saveConfig() {
    const btn = document.getElementById('btn-save');
    btn.disabled = true;
    btn.textContent = 'Saving...';
    try {
        const resp = await fetch('/admin/settings/save', {
            method: 'POST',
            headers: authHeaders(),
            body: JSON.stringify(CONFIG)
        });
        const result = await resp.json();
        if (resp.ok) {
            // URL/key changes should apply immediately, without a page reload:
            // invalidate the provider and imagegen backend model caches.
            for (const k of Object.keys(PROVIDERS_CACHE)) delete PROVIDERS_CACHE[k];
            for (const k of Object.keys(IMAGEGEN_MODELS_CACHE)) delete IMAGEGEN_MODELS_CACHE[k];
            toast(result.message || 'Saved!', 'success');
            // Nach Save pruefen, ob restart-pflichtige Felder veraendert wurden.
            loadRestartPending();
        } else {
            toast('Error: ' + (result.detail || result.message), 'error');
        }
    } catch (e) {
        toast('Save failed: ' + e.message, 'error');
    }
    btn.disabled = false;
    btn.textContent = 'Save';
}

async function loadRestartPending() {
    try {
        const resp = await fetch('/admin/settings/restart-pending', { credentials: 'same-origin' });
        if (!resp.ok) return;
        const data = await resp.json();
        renderRestartBanner(data.pending || []);
    } catch (e) {
        // Banner-Anzeige ist nicht kritisch — bei Fehler nicht stoeren.
    }
}

function renderRestartBanner(pending) {
    const banner = document.getElementById('restart-banner');
    const slot = document.getElementById('restart-banner-fields');
    if (!banner || !slot) return;
    if (!pending || pending.length === 0) {
        banner.style.display = 'none';
        slot.innerHTML = '';
        return;
    }
    slot.innerHTML = pending.map(p => '<code>' + esc(p) + '</code>').join(' ');
    banner.style.display = 'block';
}

function togglePw(btn) {
    const input = btn.parentElement.querySelector('input');
    input.type = input.type === 'password' ? 'text' : 'password';
}

// ── Helpers ──
function esc(s) {
    if (s === null || s === undefined) return '';
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function toast(msg, type) {
    const t = document.getElementById('toast');
    t.textContent = msg;
    t.className = 'toast ' + type + ' show';
    setTimeout(() => t.classList.remove('show'), 3000);
}

// Start
init();
</script>
</body>
</html>'''


def _build_users_html() -> str:
    """User-Verwaltungs-Seite (Admin-only)."""
    return '''<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<title>User-Verwaltung</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #0d1117; color: #c9d1d9; padding: 20px; }
h1 { font-size: 18px; margin-bottom: 16px; color: #e6edf3; }
.toolbar { margin-bottom: 16px; }
.btn { background: #21262d; color: #c9d1d9; border: 1px solid #30363d; padding: 6px 14px; border-radius: 6px; cursor: pointer; font-size: 13px; }
.btn:hover { background: #30363d; }
.btn-primary { background: #238636; border-color: #2ea043; color: #fff; }
.btn-primary:hover { background: #2ea043; }
.btn-danger { background: #da3633; border-color: #f85149; color: #fff; }
.btn-danger:hover { background: #b62324; }
.btn-sm { padding: 4px 8px; font-size: 12px; }

table { width: 100%; border-collapse: collapse; background: #161b22; border: 1px solid #30363d; border-radius: 8px; overflow: hidden; }
th, td { padding: 10px 14px; text-align: left; border-bottom: 1px solid #30363d; }
th { background: #1c2128; font-size: 12px; color: #8b949e; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; }
tr:last-child td { border-bottom: none; }
tr:hover { background: #1c2128; }
.role-admin { color: #58a6ff; font-weight: 600; }
.role-user { color: #8b949e; }
.chars { font-size: 11px; color: #8b949e; }
td .actions { display: flex; gap: 6px; }

.modal-bg { position: fixed; inset: 0; background: rgba(0,0,0,0.6); display: none; align-items: center; justify-content: center; z-index: 1000; }
.modal-bg.show { display: flex; }
.modal { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 20px; width: 480px; max-width: 92vw; max-height: 90vh; overflow-y: auto; }
.modal h2 { font-size: 16px; margin-bottom: 14px; color: #e6edf3; }
.field { margin-bottom: 12px; }
.field label { display: block; font-size: 12px; color: #8b949e; margin-bottom: 4px; }
.field input, .field select { width: 100%; background: #0d1117; color: #c9d1d9; border: 1px solid #30363d; padding: 6px 10px; border-radius: 6px; font-size: 13px; }
.field input:focus, .field select:focus { border-color: #58a6ff; outline: none; }
.chars-box {
    max-height: 160px; overflow-y: auto; overflow-x: hidden;
    border: 1px solid #30363d; padding: 8px; border-radius: 6px;
    background: #0d1117;
}
/* Eigene Klasse statt Tag-Selector — kein Cascading-Risiko */
.char-row {
    display: block !important;
    width: 100% !important;
    padding: 3px 0 !important;
    margin: 0 !important;
    font-size: 12px;
    color: #c9d1d9 !important;
    cursor: pointer;
    text-align: left !important;
    white-space: nowrap;
    line-height: 1.6;
}
.char-row > input[type="checkbox"] {
    display: inline-block !important;
    margin: 0 8px 0 0 !important;
    padding: 0 !important;
    vertical-align: middle !important;
    float: none !important;
    width: auto !important;
    min-width: 0 !important;
}
.char-row > span {
    display: inline-block !important;
    vertical-align: middle !important;
    color: #c9d1d9 !important;
}
.modal-actions { display: flex; gap: 8px; justify-content: flex-end; margin-top: 14px; border-top: 1px solid #30363d; padding-top: 12px; }
.error-msg { color: #f85149; font-size: 12px; margin-bottom: 8px; display: none; }
.toast { position: fixed; bottom: 20px; right: 20px; background: #238636; color: #fff; padding: 10px 16px; border-radius: 6px; font-size: 13px; opacity: 0; transition: opacity 0.3s; pointer-events: none; z-index: 2000; }
.toast.show { opacity: 1; }
.toast.error { background: #da3633; }
</style>
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

<script>
let USERS = [];
let CHARS = [];
let EDIT_ID = null;

async function loadAll() {
    try {
        const [uResp, cResp] = await Promise.all([
            fetch('/auth/users'),
            fetch('/characters/list'),
        ]);
        if (uResp.status === 401 || uResp.status === 403) {
            const ret = encodeURIComponent(window.location.pathname);
            window.location.href = '/?return=' + ret;
            return;
        }
        USERS = (await uResp.json()).users || [];
        CHARS = (await cResp.json()).characters || [];
        renderTable();
    } catch (e) {
        toast('Error loading: ' + e.message, 'error');
    }
}

function renderTable() {
    const tb = document.getElementById('users-tbody');
    if (!USERS.length) {
        tb.innerHTML = '<tr><td colspan="5" style="text-align:center;color:#8b949e;">No users</td></tr>';
        return;
    }
    tb.innerHTML = USERS.map(u => {
        const charList = (u.allowed_characters || []).join(', ') || '—';
        const roleClass = u.role === 'admin' ? 'role-admin' : 'role-user';
        return '<tr>' +
            '<td>' + escapeHtml(u.username) + '</td>' +
            '<td class="' + roleClass + '">' + escapeHtml(u.role) + '</td>' +
            '<td class="chars">' + escapeHtml(charList) + '</td>' +
            '<td>' + escapeHtml(u.last_login || '—') + '</td>' +
            '<td class="actions">' +
                '<button class="btn btn-sm" onclick="openEdit(\\'' + u.id + '\\')">Edit</button>' +
                '<button class="btn btn-sm btn-danger" onclick="deleteUser(\\'' + u.id + '\\')">Del</button>' +
            '</td>' +
        '</tr>';
    }).join('');
}

function openEdit(userId) {
    EDIT_ID = userId;
    const u = userId ? USERS.find(x => x.id === userId) : null;
    document.getElementById('modal-title').textContent = u ? 'User bearbeiten' : 'User anlegen';
    document.getElementById('edit-username').value = u ? u.username : '';
    document.getElementById('edit-role').value = u ? u.role : 'user';
    document.getElementById('edit-password').value = '';
    document.getElementById('edit-password-label').textContent = u ? 'Passwort (leer = nicht aendern)' : 'Passwort';
    document.getElementById('modal-error').style.display = 'none';

    const assigned = new Set(u ? u.allowed_characters : []);
    document.getElementById('edit-chars-box').innerHTML = CHARS.map(c =>
        '<label class="char-row"><input type="checkbox" value="' + escapeHtml(c) + '"' + (assigned.has(c) ? ' checked' : '') + '><span>' + escapeHtml(c) + '</span></label>'
    ).join('');
    document.getElementById('modal-bg').classList.add('show');
}

function toggleAllChars(checked) {
    document.querySelectorAll('#edit-chars-box input[type="checkbox"]').forEach(cb => { cb.checked = !!checked; });
}

function closeEdit() {
    document.getElementById('modal-bg').classList.remove('show');
    EDIT_ID = null;
}

async function saveEdit() {
    const username = document.getElementById('edit-username').value.trim();
    const role = document.getElementById('edit-role').value;
    const password = document.getElementById('edit-password').value;
    const chars = Array.from(document.querySelectorAll('#edit-chars-box input:checked')).map(i => i.value);
    const err = document.getElementById('modal-error');
    err.style.display = 'none';

    if (!username) { err.textContent = 'Benutzername erforderlich'; err.style.display = 'block'; return; }
    if (!EDIT_ID && !password) { err.textContent = 'Passwort erforderlich'; err.style.display = 'block'; return; }

    try {
        let resp;
        if (EDIT_ID) {
            const body = { username, role, allowed_characters: chars };
            if (password) body.password = password;
            resp = await fetch('/auth/users/' + EDIT_ID, {
                method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
            });
        } else {
            resp = await fetch('/auth/users', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ username, password, role, allowed_characters: chars })
            });
        }
        if (!resp.ok) {
            const d = await resp.json().catch(() => ({}));
            err.textContent = d.detail || 'Save error';
            err.style.display = 'block';
            return;
        }
        closeEdit();
        toast(EDIT_ID ? 'User aktualisiert' : 'User angelegt');
        await loadAll();
    } catch (e) {
        err.textContent = 'Verbindungsfehler: ' + e.message;
        err.style.display = 'block';
    }
}

async function deleteUser(userId) {
    const u = USERS.find(x => x.id === userId);
    if (!u) return;
    if (!confirm('Really delete user "' + u.username + '"?')) return;
    try {
        const resp = await fetch('/auth/users/' + userId, { method: 'DELETE' });
        if (!resp.ok) {
            const d = await resp.json().catch(() => ({}));
            toast(d.detail || 'Error', 'error');
            return;
        }
        toast('User deleted');
        await loadAll();
    } catch (e) { toast('Error: ' + e.message, 'error'); }
}

function escapeHtml(s) {
    return String(s).replace(/[&<>"\\']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function toast(msg, type) {
    const t = document.getElementById('toast');
    t.textContent = msg;
    t.className = 'toast ' + (type === 'error' ? 'error' : '') + ' show';
    setTimeout(() => t.classList.remove('show'), 2500);
}

loadAll();
</script>
</body>
</html>'''


def _build_llm_stats_html() -> str:
    """LLM-Call-Statistik — read-only Auswertung mit Zeitraum-/Character-Filter."""
    return '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>LLM Stats</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #0d1117; color: #c9d1d9; padding: 20px; }
h1 { font-size: 18px; margin-bottom: 8px; color: #e6edf3; }
.hint { font-size: 12px; color: #8b949e; margin-bottom: 16px; }

.filter-bar { display: flex; flex-wrap: wrap; gap: 10px; align-items: center;
    background: #161b22; border: 1px solid #30363d; border-radius: 8px;
    padding: 10px 14px; margin-bottom: 14px; }
.filter-bar label { font-size: 12px; color: #8b949e; display: inline-flex; align-items: center; gap: 6px; }
.filter-bar input, .filter-bar select { background: #0d1117; color: #c9d1d9;
    border: 1px solid #30363d; padding: 5px 8px; border-radius: 5px; font-size: 12px; }
.filter-bar input[type="datetime-local"] { font-family: inherit; }
.filter-bar select[multiple] { min-width: 180px; min-height: 70px; }

.btn { background: #21262d; color: #c9d1d9; border: 1px solid #30363d;
    padding: 5px 12px; border-radius: 5px; cursor: pointer; font-size: 12px; }
.btn:hover { background: #30363d; }
.btn-primary { background: #1f6feb; border-color: #388bfd; color: #fff; }
.btn-primary:hover { background: #388bfd; }
.btn.active { background: #1f6feb; border-color: #388bfd; color: #fff; }

.preset-row { display: flex; gap: 4px; }
.summary { font-size: 12px; color: #8b949e; margin-bottom: 10px; }

table { width: 100%; border-collapse: collapse; background: #161b22;
    border: 1px solid #30363d; border-radius: 8px; overflow: hidden; font-size: 12px; }
th, td { padding: 6px 8px; border-bottom: 1px solid #30363d; text-align: right; white-space: nowrap; }
th { background: #1c2128; color: #8b949e; font-weight: 600; text-transform: uppercase;
    letter-spacing: 0.4px; font-size: 11px; cursor: pointer; user-select: none; }
th:hover { color: #c9d1d9; }
th.left, td.left { text-align: left; }
th .arrow { color: #58a6ff; margin-left: 2px; }
tr:last-child td { border-bottom: none; }
tr:hover { background: #1c2128; }
td.task { font-family: monospace; color: #d2a8ff; }
td.model { font-family: monospace; color: #79c0ff; }
td.provider { color: #8b949e; }
td.agent { color: #ffa657; }
td.dim { color: #6e7681; }

.empty { text-align: center; padding: 40px; color: #8b949e; }
.error { color: #f85149; padding: 10px; background: #da363322; border-radius: 6px; margin: 10px 0; }
</style>
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

<script>
let CURRENT_ROWS = [];
let SORT_KEY = "calls";
let SORT_DIR = -1;

function isoLocal(dt) {
    const pad = n => String(n).padStart(2, "0");
    return dt.getFullYear() + "-" + pad(dt.getMonth()+1) + "-" + pad(dt.getDate())
        + "T" + pad(dt.getHours()) + ":" + pad(dt.getMinutes());
}

function applyPreset(p) {
    const now = new Date();
    let from = new Date(now);
    if (p === "1h") from.setHours(now.getHours() - 1);
    else if (p === "24h") from.setHours(now.getHours() - 24);
    else if (p === "7d") from.setDate(now.getDate() - 7);
    else if (p === "30d") from.setDate(now.getDate() - 30);
    document.getElementById("from-input").value = isoLocal(from);
    document.getElementById("to-input").value = isoLocal(now);
    document.querySelectorAll(".preset-row .btn").forEach(b => b.classList.remove("active"));
    const btn = document.querySelector(".preset-row .btn[data-preset='" + p + "']");
    if (btn) btn.classList.add("active");
    loadData();
}

function buildQuery() {
    const fromVal = document.getElementById("from-input").value;
    const toVal = document.getElementById("to-input").value;
    const task = document.getElementById("task-filter").value.trim();
    const agentSel = document.getElementById("agent-select");
    const agents = Array.from(agentSel.selectedOptions).map(o => o.value).filter(v => v);
    const grouped = document.getElementById("group-by-agent").checked;
    const params = new URLSearchParams();
    if (fromVal) params.set("from", fromVal.length === 16 ? fromVal + ":00" : fromVal);
    if (toVal) params.set("to", toVal.length === 16 ? toVal + ":00" : toVal);
    if (task) params.set("task", task);
    if (agents.length) params.set("agents", agents.join(","));
    if (grouped) params.set("group_by_agent", "1");
    return params.toString();
}

async function loadData() {
    const errBox = document.getElementById("error-box");
    errBox.innerHTML = "";
    document.getElementById("stats-tbody").innerHTML =
        '<tr><td class="empty" colspan="20">Loading…</td></tr>';
    try {
        const q = buildQuery();
        const resp = await fetch("/admin/llm-stats/data?" + q, { credentials: "same-origin" });
        if (resp.status === 401 || resp.status === 403) {
            const ret = encodeURIComponent(window.location.pathname);
            window.location.href = "/?return=" + ret;
            return;
        }
        if (!resp.ok) throw new Error("HTTP " + resp.status);
        const data = await resp.json();
        CURRENT_ROWS = data.rows || [];
        updateAgentDropdown(data.agents || []);
        renderSummary(data);
        renderTable();
    } catch (e) {
        errBox.innerHTML = '<div class="error">Error: ' + escapeHtml(e.message) + "</div>";
        document.getElementById("stats-tbody").innerHTML = "";
    }
}

function updateAgentDropdown(agents) {
    const sel = document.getElementById("agent-select");
    const prev = new Set(Array.from(sel.selectedOptions).map(o => o.value));
    sel.innerHTML = "";
    for (const a of agents) {
        const opt = document.createElement("option");
        opt.value = a;
        opt.textContent = a;
        if (prev.has(a)) opt.selected = true;
        sel.appendChild(opt);
    }
}

function renderSummary(data) {
    const total = CURRENT_ROWS.reduce((s, r) => s + r.calls, 0);
    const groups = CURRENT_ROWS.length;
    const grouped = data.group_by_agent ? "Task x Model x Provider x Character" : "Task x Model x Provider";
    document.getElementById("summary").textContent =
        groups + " Gruppen, " + total + " Calls insgesamt | Gruppierung: " + grouped
        + " | Zeitraum: " + data.from + " bis " + data.to;
}

function renderTable() {
    const grouped = document.getElementById("group-by-agent").checked;
    const thead = document.getElementById("stats-thead");
    const tbody = document.getElementById("stats-tbody");

    const cols = [
        { key: "task",             label: "Task",          cls: "left" },
        { key: "model",            label: "Model",         cls: "left" },
        { key: "provider",         label: "Provider",      cls: "left" }
    ];
    if (grouped) cols.push({ key: "agent_name", label: "Character", cls: "left" });
    cols.push(
        { key: "calls",            label: "Calls" },
        { key: "avg_duration",     label: "avg s" },
        { key: "min_duration",     label: "min s" },
        { key: "max_duration",     label: "max s" },
        { key: "p90_duration",     label: "p90 s" },
        { key: "avg_in_tokens",    label: "avg in" },
        { key: "avg_out_tokens",   label: "avg out" },
        { key: "avg_max_tokens",   label: "cfg max out" },
        { key: "avg_total_tokens", label: "avg in+out" },
        { key: "max_in_tokens",    label: "peak in" },
        { key: "max_total_tokens", label: "peak in+out" }
    );

    let th = "<tr>";
    for (const c of cols) {
        const isSort = c.key === SORT_KEY;
        const arrow = isSort ? '<span class="arrow">' + (SORT_DIR > 0 ? "↑" : "↓") + "</span>" : "";
        th += '<th class="' + (c.cls || "") + '" onclick="sortBy(\\'' + c.key + '\\')">'
            + escapeHtml(c.label) + arrow + "</th>";
    }
    th += "</tr>";
    thead.innerHTML = th;

    const sorted = CURRENT_ROWS.slice().sort((a, b) => {
        const va = a[SORT_KEY], vb = b[SORT_KEY];
        if (typeof va === "number") return (va - vb) * SORT_DIR;
        return String(va || "").localeCompare(String(vb || "")) * SORT_DIR;
    });

    if (!sorted.length) {
        tbody.innerHTML = '<tr><td class="empty" colspan="' + cols.length + '">No data in the selected period</td></tr>';
        return;
    }

    tbody.innerHTML = sorted.map(r => {
        let row = "<tr>";
        row += '<td class="left task">' + escapeHtml(r.task) + "</td>";
        row += '<td class="left model">' + escapeHtml(r.model) + "</td>";
        row += '<td class="left provider">' + escapeHtml(r.provider || "—") + "</td>";
        if (grouped) row += '<td class="left agent">' + escapeHtml(r.agent_name || "—") + "</td>";
        row += "<td>" + r.calls + "</td>";
        row += "<td>" + r.avg_duration.toFixed(2) + "</td>";
        row += "<td>" + r.min_duration.toFixed(2) + "</td>";
        row += "<td>" + r.max_duration.toFixed(2) + "</td>";
        row += "<td>" + r.p90_duration.toFixed(2) + "</td>";
        row += "<td>" + r.avg_in_tokens + "</td>";
        row += "<td>" + r.avg_out_tokens + "</td>";
        const cfg = r.avg_max_tokens;
        row += '<td class="' + (cfg ? "" : "dim") + '">' + (cfg || "—") + "</td>";
        row += "<td>" + r.avg_total_tokens + "</td>";
        row += "<td>" + r.max_in_tokens + "</td>";
        row += "<td>" + r.max_total_tokens + "</td>";
        row += "</tr>";
        return row;
    }).join("");
}

function sortBy(key) {
    if (SORT_KEY === key) SORT_DIR = -SORT_DIR;
    else { SORT_KEY = key; SORT_DIR = -1; }
    renderTable();
}

function escapeHtml(s) {
    return String(s == null ? "" : s)
        .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

applyPreset("24h");
</script>
</body>
</html>'''


