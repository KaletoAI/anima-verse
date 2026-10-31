"""Log viewer - LLM calls as a searchable web page."""
import json
from pathlib import Path
from fastapi import APIRouter, Query, Depends, Body, HTTPException
from fastapi.responses import HTMLResponse
from typing import Dict, Any
from app.core.log import get_logger
from app.core.auth_dependency import require_admin
from app.core.llm_log_replay import ReplayError, group_entries, read_entries, replay_entry

logger = get_logger("logs_route")

router = APIRouter(prefix="/logs", tags=["logs"],
                   dependencies=[Depends(require_admin)])

LOG_FILE = Path("./logs/llm_calls.jsonl")


@router.get("/llm", response_class=HTMLResponse)
def llm_log_viewer():
    """LLM log viewer - main page."""
    return HTMLResponse(content=_build_viewer_html())


@router.get("/llm/data")
def llm_log_data(
    limit: int = Query(100, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    task: str = Query("", description="Filter by task type"),
    model: str = Query("", description="Filter by model"),
    character: str = Query("", description="Filter by character"),
    provider: str = Query("", description="Filter by provider"),
    errors_only: bool = Query(False, description="Failed calls only"),
    search: str = Query("", description="Full-text search")) -> Dict[str, Any]:
    """Return original calls with all persistent comparisons attached.

    Grouping precedes filtering and pagination. Comparisons never count as
    standalone calls or trace members, including when a filter matches one.
    """
    entries = []
    all_tasks = set()
    all_models = set()
    all_characters = set()
    all_providers = set()
    trace_counts: Dict[str, int] = {}

    for obj in group_entries(read_entries(LOG_FILE)):
        all_tasks.add(obj.get("task", ""))
        tid = obj.get("trace_id", "")
        if tid:
            trace_counts[tid] = trace_counts.get(tid, 0) + 1
        svc = obj.get("service", "")
        if svc:
            all_characters.add(svc)
        variants = [obj, *obj["comparisons"]]
        for variant in variants:
            all_models.add(variant.get("model", ""))
            prov = variant.get("provider", "")
            if prov:
                all_providers.add(prov)

        if task and obj.get("task") != task:
            continue
        if model and not any(v.get("model") == model for v in variants):
            continue
        if character and obj.get("service") != character:
            continue
        if provider and not any(v.get("provider") == provider for v in variants):
            continue
        if errors_only and not any(v.get("error") for v in variants):
            continue
        if search and search.lower() not in json.dumps(obj, ensure_ascii=False).lower():
            continue
        entries.append(obj)

    entries.reverse()
    total = len(entries)
    page = entries[offset:offset + limit]

    page_traces = {t for t in (e.get("trace_id", "") for e in page) if t}

    return {
        "entries": page,
        "total": total,
        "offset": offset,
        "limit": limit,
        "tasks": sorted(all_tasks),
        "models": sorted(all_models),
        "characters": sorted(all_characters),
        "providers": sorted(all_providers),
        "trace_totals": {t: trace_counts.get(t, 0) for t in page_traces},
    }


@router.post("/llm/replay")
def llm_log_replay(
    entry_id: str = Body(..., min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"),
    provider: str = Body(..., min_length=1, max_length=512),
    model: str = Body(..., min_length=1, max_length=512),
    temperature: float = Body(..., ge=0, le=2),
    max_tokens: int = Body(..., ge=0),
    top_p: float | None = Body(None, ge=0, le=1),
    frequency_penalty: float | None = Body(None, ge=-2, le=2),
) -> Dict[str, Any]:
    """Replay a server-side log record; response tools are never executed."""
    if not provider.strip() or not model.strip():
        raise HTTPException(status_code=400, detail="Provider and model must not be blank.")
    try:
        comparison = replay_entry(
            LOG_FILE, entry_id=entry_id, provider=provider, model=model,
            temperature=temperature, max_tokens=max_tokens, top_p=top_p,
            frequency_penalty=frequency_penalty)
    except ReplayError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
    return {"comparison": comparison}


IMAGE_LOG_FILE = Path("./logs/image_prompts.jsonl")


@router.get("/image-prompts", response_class=HTMLResponse)
def image_prompt_log_viewer():
    """Image prompt log viewer - main page."""
    return HTMLResponse(content=_build_image_viewer_html())


@router.get("/image-prompts/data")
def image_prompt_log_data(
    limit: int = Query(100, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    character: str = Query("", description="Filter by character"),
    backend: str = Query("", description="Filter by backend"),
    model: str = Query("", description="Filter by model"),
    errors_only: bool = Query(False, description="Failed generations only"),
    search: str = Query("", description="Full-text search")) -> Dict[str, Any]:
    """JSON API for image prompt log entries."""
    if not IMAGE_LOG_FILE.exists():
        return {"entries": [], "total": 0, "characters": [], "backends": [], "models": []}

    entries = []
    all_characters = set()
    all_backends = set()
    all_models = set()

    with open(IMAGE_LOG_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                svc = obj.get("service", "")
                if svc:
                    all_characters.add(svc)
                bn = (obj.get("backend") or {}).get("name", "")
                if bn:
                    all_backends.add(bn)
                mn = obj.get("model", "")
                if mn:
                    all_models.add(mn)

                if character and obj.get("service") != character:
                    continue
                if backend and (obj.get("backend") or {}).get("name") != backend:
                    continue
                if model and obj.get("model") != model:
                    continue
                if errors_only and not obj.get("error"):
                    continue
                if search:
                    haystack = json.dumps(obj, ensure_ascii=False).lower()
                    if search.lower() not in haystack:
                        continue

                entries.append(obj)
            except json.JSONDecodeError:
                continue

    entries.reverse()
    total = len(entries)
    page = entries[offset:offset + limit]

    return {
        "entries": page,
        "total": total,
        "offset": offset,
        "limit": limit,
        "characters": sorted(all_characters),
        "backends": sorted(all_backends),
        "models": sorted(all_models),
    }


def _build_image_viewer_html() -> str:
    return '''<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Image Prompt Log Viewer</title>
<link rel="stylesheet" href="/static/admin/logs-image.css">
</head>
<body>

<div class="toolbar">
    <select id="characterFilter"><option value="">Alle Characters</option></select>
    <select id="backendFilter"><option value="">Alle Backends</option></select>
    <select id="modelFilter"><option value="">Alle Models</option></select>
    <label style="color:#c9d1d9;font-size:13px;display:flex;align-items:center;gap:4px;cursor:pointer;">
        <input type="checkbox" id="errorsOnly" /> Errors only
    </label>
    <input type="text" id="searchInput" placeholder="Suche..." />
    <button onclick="doSearch()">Suchen</button>
    <button onclick="resetFilters()">Reset</button>
    <span class="count" id="countLabel"></span>
</div>

<div class="entries" id="entries"></div>

<div class="pager">
    <button id="prevBtn" onclick="prevPage()" disabled>Zurueck</button>
    <span id="pageLabel" style="color:#8b949e;font-size:13px;line-height:32px;"></span>
    <button id="nextBtn" onclick="nextPage()" disabled>Weiter</button>
</div>

<script src="/static/admin/logs-image.js"></script>
</body>
</html>'''


def _build_viewer_html() -> str:
    return '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>LLM Log Viewer</title>
<link rel="stylesheet" href="/static/admin/logs-viewer.css">
</head>
<body>

<div class="toolbar">
    <select id="taskFilter"><option value="">All tasks</option></select>
    <select id="providerFilter"><option value="">All providers</option></select>
    <select id="modelFilter"><option value="">All models</option></select>
    <select id="characterFilter"><option value="">All characters</option></select>
    <label style="color:#c9d1d9;font-size:13px;display:flex;align-items:center;gap:4px;cursor:pointer;">
        <input type="checkbox" id="errorsOnly" /> Errors only
    </label>
    <label style="color:#c9d1d9;font-size:13px;display:flex;align-items:center;gap:4px;cursor:pointer;"
           title="Group all LLM calls of one turn (same trace id) under one header">
        <input type="checkbox" id="groupTraces" checked /> Group by trace
    </label>
    <input type="text" id="searchInput" placeholder="Search..." />
    <button onclick="doSearch()">Search</button>
    <button onclick="resetFilters()">Reset</button>
    <span class="count" id="countLabel"></span>
    <a href="/dashboard" style="margin-left:auto;color:#58a6ff;font-size:13px;text-decoration:none;">Dashboard</a>
</div>

<div class="entries" id="entries"></div>

<div class="pager">
    <button id="prevBtn" onclick="prevPage()" disabled>Previous</button>
    <span id="pageLabel" style="color:#8b949e;font-size:13px;line-height:32px;"></span>
    <button id="nextBtn" onclick="nextPage()" disabled>Next</button>
</div>

<script src="/static/admin/logs-viewer.js"></script>
</body>
</html>'''


@router.get("/tools", response_class=HTMLResponse)
def tool_log_viewer():
    """Admin-only tool outcome viewer."""
    return HTMLResponse(content=_build_tools_viewer_html())


@router.get("/tools/data")
def tool_log_data(
    limit: int = Query(100, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    character: str = Query(""), tool: str = Query(""),
    status: str = Query(""), source: str = Query(""),
    search: str = Query(""),
) -> Dict[str, Any]:
    """Summaries ignore tool/status filters; entry pagination applies last."""
    from app.core import tool_call_log
    rows = []
    try:
        with tool_call_log.LOG_FILE.open(encoding="utf-8") as stream:
            for line in stream:
                try:
                    row = json.loads(line)
                except (ValueError, TypeError):
                    continue
                if isinstance(row, dict):
                    rows.append(row)
    except FileNotFoundError:
        pass
    options = {key: sorted({str(row.get(key) or "") for row in rows} - {""})
               for key in ("character", "tool", "source")}
    filtered = []
    summaries = {}
    for row in rows:
        if character and row.get("character") != character:
            continue
        if source and row.get("source") != source:
            continue
        if search and search.lower() not in json.dumps(row, ensure_ascii=False).lower():
            continue
        name = str(row.get("tool") or "")
        item = summaries.setdefault(name, dict(tool=name, total=0, by_status={}))
        item["total"] += 1
        state = str(row.get("status") or "")
        item["by_status"][state] = item["by_status"].get(state, 0) + 1
        if tool and row.get("tool") != tool:
            continue
        if status and row.get("status") != status:
            continue
        filtered.append(row)
    summary = list(summaries.values())
    for item in summary:
        item["fail_rate"] = round(
            (item["total"] - item["by_status"].get("ok", 0)) / item["total"], 3)
    summary.sort(key=lambda item: (
        -(item["total"] - item["by_status"].get("ok", 0)), item["tool"]))
    filtered.reverse()
    return dict(entries=filtered[offset:offset + limit], total=len(filtered),
                offset=offset, limit=limit, characters=options["character"],
                tools=options["tool"], statuses=list(tool_call_log.STATUSES),
                sources=options["source"], summary=summary)


def _build_tools_viewer_html() -> str:
    return '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Tool Call Log</title>
<link rel="stylesheet" href="/static/admin/logs-tools.css">
</head>
<body>
<div class="toolbar">
    <label>Character <select id="characterFilter"><option value="">All characters</option></select></label>
    <label>Tool <select id="toolFilter"><option value="">All tools</option></select></label>
    <label>Status <select id="statusFilter"><option value="">All statuses</option></select></label>
    <label>Source <select id="sourceFilter"><option value="">All sources</option></select></label>
    <input type="search" id="searchInput" placeholder="Search..." aria-label="Search tool calls">
    <button id="searchBtn">Search</button>
    <button id="resetBtn">Reset</button>
    <span id="countLabel" role="status"></span>
    <a href="/logs/llm">LLM Logs</a>
</div>
<main>
<div id="summary"></div>
<div id="entries"></div>
<div class="pager">
    <button id="prevBtn" disabled>Previous</button>
    <span id="pageLabel"></span>
    <button id="nextBtn" disabled>Next</button>
</div>
</main>
<script src="/static/admin/logs-tools.js"></script>
</body>
</html>'''
