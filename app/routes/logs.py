"""Log Viewer - LLM-Aufrufe als durchsuchbare Webseite"""
import json
from pathlib import Path
from fastapi import APIRouter, Query, Depends
from fastapi.responses import HTMLResponse
from typing import Dict, Any
from app.core.log import get_logger
from app.core.auth_dependency import require_admin

logger = get_logger("logs_route")

router = APIRouter(prefix="/logs", tags=["logs"],
                   dependencies=[Depends(require_admin)])

LOG_FILE = Path("./logs/llm_calls.jsonl")


@router.get("/llm", response_class=HTMLResponse)
def llm_log_viewer():
    """LLM Log Viewer - Hauptseite."""
    return HTMLResponse(content=_build_viewer_html())


@router.get("/llm/data")
def llm_log_data(
    limit: int = Query(100, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    task: str = Query("", description="Filter by task type"),
    model: str = Query("", description="Filter by model"),
    character: str = Query("", description="Filter by character"),
    provider: str = Query("", description="Filter by provider"),
    errors_only: bool = Query(False, description="Nur fehlgeschlagene Calls"),
    search: str = Query("", description="Volltextsuche")) -> Dict[str, Any]:
    """JSON-API fuer Log-Eintraege."""
    if not LOG_FILE.exists():
        return {"entries": [], "total": 0, "tasks": [], "models": [], "providers": []}

    entries = []
    all_tasks = set()
    all_models = set()
    all_characters = set()
    all_providers = set()

    with open(LOG_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                all_tasks.add(obj.get("task", ""))
                all_models.add(obj.get("model", ""))
                svc = obj.get("service", "")
                if svc:
                    all_characters.add(svc)
                prov = obj.get("provider", "")
                if prov:
                    all_providers.add(prov)

                if task and obj.get("task") != task:
                    continue
                if model and obj.get("model") != model:
                    continue
                if character and obj.get("service") != character:
                    continue
                if provider and obj.get("provider", "") != provider:
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

    # Neueste zuerst
    entries.reverse()
    total = len(entries)
    page = entries[offset:offset + limit]

    return {
        "entries": page,
        "total": total,
        "offset": offset,
        "limit": limit,
        "tasks": sorted(all_tasks),
        "models": sorted(all_models),
        "characters": sorted(all_characters),
        "providers": sorted(all_providers),
    }


IMAGE_LOG_FILE = Path("./logs/image_prompts.jsonl")


@router.get("/image-prompts", response_class=HTMLResponse)
def image_prompt_log_viewer():
    """Image Prompt Log Viewer - Hauptseite."""
    return HTMLResponse(content=_build_image_viewer_html())


@router.get("/image-prompts/data")
def image_prompt_log_data(
    limit: int = Query(100, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    character: str = Query("", description="Filter by character"),
    backend: str = Query("", description="Filter by backend"),
    model: str = Query("", description="Filter by model"),
    errors_only: bool = Query(False, description="Nur fehlgeschlagene Generierungen"),
    search: str = Query("", description="Volltextsuche")) -> Dict[str, Any]:
    """JSON-API fuer Image-Prompt Log-Eintraege."""
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
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>LLM Log Viewer</title>
<link rel="stylesheet" href="/static/admin/logs-viewer.css">
</head>
<body>

<div class="toolbar">
    <select id="taskFilter"><option value="">Alle Tasks</option></select>
    <select id="providerFilter"><option value="">Alle Provider</option></select>
    <select id="modelFilter"><option value="">Alle Models</option></select>
    <select id="characterFilter"><option value="">Alle Characters</option></select>
    <label style="color:#c9d1d9;font-size:13px;display:flex;align-items:center;gap:4px;cursor:pointer;">
        <input type="checkbox" id="errorsOnly" /> Errors only
    </label>
    <input type="text" id="searchInput" placeholder="Suche..." />
    <button onclick="doSearch()">Suchen</button>
    <button onclick="resetFilters()">Reset</button>
    <span class="count" id="countLabel"></span>
    <a href="/dashboard" style="margin-left:auto;color:#58a6ff;font-size:13px;text-decoration:none;">Dashboard</a>
</div>

<div class="entries" id="entries"></div>

<div class="pager">
    <button id="prevBtn" onclick="prevPage()" disabled>Zurueck</button>
    <span id="pageLabel" style="color:#8b949e;font-size:13px;line-height:32px;"></span>
    <button id="nextBtn" onclick="nextPage()" disabled>Weiter</button>
</div>

<script src="/static/admin/logs-viewer.js"></script>
</body>
</html>'''
