"""System Load Dashboard — Uebersicht ueber LLM- und Bildgenerierungs-Last.

Liest logs/llm_calls.jsonl und logs/image_prompts.jsonl, aggregiert die Daten
und stellt sie als interaktive Timeline mit Chart.js dar.
"""
import json
from datetime import datetime, timedelta

from app.core.timeutils import parse_iso, utc_now
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, Query, Depends
from fastapi.responses import HTMLResponse
from app.core.log import get_logger
from app.core.auth_dependency import require_admin

logger = get_logger("dashboard")

router = APIRouter(prefix="/dashboard", tags=["dashboard"],
                   dependencies=[Depends(require_admin)])

LLM_LOG = Path("./logs/llm_calls.jsonl")
IMAGE_LOG = Path("./logs/image_prompts.jsonl")


def _get_systems() -> List[Dict[str, Any]]:
    """Laedt System-Konfiguration aus ProviderManager (basierend auf .env)."""
    try:
        from app.core.provider_manager import get_provider_manager
        return get_provider_manager().get_systems_config()
    except Exception:
        return []


def _read_jsonl(path: Path, cutoff: str = "") -> List[Dict[str, Any]]:
    """Liest JSONL-Datei und filtert nach cutoff-Zeitpunkt."""
    if not path.exists():
        return []
    entries = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if cutoff and entry.get("endtime", entry.get("starttime", "")) < cutoff:
                continue
            entries.append(entry)
    return entries


@router.get("/data")
def dashboard_data(hours: int = Query(24, ge=0)):
    """Liefert aggregierte Dashboard-Daten als JSON."""
    cutoff = ""
    if hours > 0:
        cutoff = (utc_now() - timedelta(hours=hours)).isoformat(timespec="seconds")

    # LLM Calls laden
    raw_llm = _read_jsonl(LLM_LOG, cutoff)
    llm_calls = []
    for e in raw_llm:
        llm_calls.append({
            "starttime": e.get("starttime", ""),
            "endtime": e.get("endtime", ""),
            "duration_s": e.get("duration_s", 0),
            "task": e.get("task", ""),
            "model": e.get("model", ""),
            "provider": e.get("provider", ""),
            "service": e.get("service", ""),
            "tokens_in": e.get("tokens", {}).get("input", 0),
            "tokens_out": e.get("tokens", {}).get("output", 0),
        })

    # Image Calls laden
    raw_img = _read_jsonl(IMAGE_LOG, cutoff)
    image_calls = []
    for e in raw_img:
        be = e.get("backend", {})
        st = e.get("starttime", "")
        et = e.get("endtime", "")
        dur = 0.0
        if st and et:
            try:
                dur = (parse_iso(et) - parse_iso(st)).total_seconds()
            except (ValueError, TypeError):
                pass
        image_calls.append({
            "starttime": st,
            "endtime": et,
            "duration_s": round(dur, 2),
            "backend": be.get("name", ""),
            "backend_type": be.get("type", ""),
            "service": e.get("service", ""),
            "model": e.get("model", ""),
        })

    # Zeitraum
    all_starts = [c["starttime"] for c in llm_calls + image_calls if c.get("starttime")]
    all_ends = [c["endtime"] for c in llm_calls + image_calls if c.get("endtime")]
    time_start = min(all_starts) if all_starts else ""
    time_end = max(all_ends) if all_ends else ""

    return {
        "time_range": {"start": time_start, "end": time_end},
        "llm_calls": llm_calls,
        "image_calls": image_calls,
        "systems": _get_systems(),
    }


@router.get("/activity")
def activity_feed(hours: int = Query(24, ge=0)):
    """Aggregierter Activity-Feed: Instagram, Reaktionen, Story Arcs, Gedanken-Nachrichten."""
    cutoff = ""
    if hours > 0:
        cutoff = (utc_now() - timedelta(hours=hours)).isoformat(timespec="seconds")

    events = []

    # 1. Instagram Posts + Kommentare
    try:
        from app.models.instagram import load_feed
        feed = load_feed()
        for post in feed:
            ts = post.get("timestamp", "")
            if cutoff and ts < cutoff:
                continue
            events.append({
                "type": "instagram_post",
                "timestamp": ts,
                "character": post.get("agent_name", ""),
                "summary": (post.get("caption", "") or "")[:150],
                "detail": ", ".join(post.get("hashtags", [])[:5]),
            })
            for comment in post.get("comments", []):
                cts = comment.get("timestamp", "")
                if cutoff and cts < cutoff:
                    continue
                events.append({
                    "type": "instagram_reaction",
                    "timestamp": cts,
                    "character": comment.get("author", ""),
                    "summary": (comment.get("text", "") or "")[:150],
                    "detail": f"auf Post von {post.get('agent_name', '')}",
                })
    except Exception as e:
        logger.debug("Activity: Instagram error: %s", e)

    # 2. Story Arcs + Beats
    try:
        from app.models.story_arcs import get_all_arcs
        for arc in get_all_arcs():
            ts = arc.get("created_at", "")
            if not (cutoff and ts < cutoff):
                events.append({
                    "type": "story_arc",
                    "timestamp": ts,
                    "character": ", ".join(arc.get("participants", [])),
                    "summary": f"Arc gestartet: {arc.get('title', '')}",
                    "detail": arc.get("seed", "")[:120],
                    "meta": {"status": arc.get("status"), "tension": arc.get("tension")},
                })
            for beat in arc.get("beats", []):
                bts = beat.get("timestamp", "")
                if cutoff and bts < cutoff:
                    continue
                beat_meta = {}
                scene_img = beat.get("scene_image")
                if scene_img and scene_img.get("filename") and scene_img.get("character"):
                    beat_meta["image_url"] = (
                        f"/characters/{scene_img['character']}/images/"
                        f"{scene_img['filename']}"
                    )
                events.append({
                    "type": "story_beat",
                    "timestamp": bts,
                    "character": ", ".join(arc.get("participants", [])),
                    "summary": f"Beat {beat.get('beat', '?')}: {beat.get('summary', '')[:120]}",
                    "detail": arc.get("title", ""),
                    **({"meta": beat_meta} if beat_meta else {}),
                })
            if arc.get("status") == "resolved" and arc.get("resolution"):
                rts = arc.get("updated_at", "")
                if not (cutoff and rts < cutoff):
                    events.append({
                        "type": "story_resolved",
                        "timestamp": rts,
                        "character": ", ".join(arc.get("participants", [])),
                        "summary": f"Arc abgeschlossen: {arc.get('title', '')}",
                        "detail": (arc.get("resolution", "") or "")[:120],
                    })
    except Exception as e:
        logger.debug("Activity: Story Arcs error: %s", e)

    # 3. Gedanken-Nachrichten + Social Dialogs (aus Notifications)
    try:
        from app.models.notifications import get_notifications
        notifs = get_notifications(limit=200)
        for n in notifs:
            ts = n.get("timestamp", "")
            if cutoff and ts < cutoff:
                continue
            trigger = (n.get("metadata") or {}).get("trigger", "")
            if trigger == "thought":
                events.append({
                    "type": "thought",
                    "timestamp": ts,
                    "character": n.get("character", ""),
                    "summary": (n.get("content", "") or "")[:150],
                    "detail": "",
                })
    except Exception as e:
        logger.debug("Activity: Notifications error: %s", e)

    # 4. (frueher: Social Dialogs aus log geparst — entfaellt, da sie jetzt
    #     normale Chat-Eintraege sind, siehe plan-thoughts-and-conversation.md)

    # Nach Zeitstempel sortieren (neueste zuerst)
    events.sort(key=lambda e: e.get("timestamp", ""), reverse=True)

    return {
        "events": events[:200],
        "total": len(events),
    }


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def dashboard_page():
    """Rendert die Dashboard-HTML-Seite."""
    return HTMLResponse(content=_build_dashboard_html())


def _build_dashboard_html() -> str:
    return '''<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>System Load Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<link rel="stylesheet" href="/static/admin/dashboard.css">
</head>
<body>

<div class="header">
    <h1>System Load Dashboard</h1>
    <div class="time-btns">
        <button class="time-btn" data-hours="1">1h</button>
        <button class="time-btn" data-hours="6">6h</button>
        <button class="time-btn active" data-hours="24">24h</button>
        <button class="time-btn" data-hours="168">7d</button>
        <button class="time-btn" data-hours="0">Alle</button>
    </div>
    <div class="header-links">
        <a href="/">Chat</a>
        <a href="/admin/llm-stats">LLM Stats</a>
        <a href="/logs/llm">LLM Logs</a>
        <a href="/logs/image-prompts">Image Logs</a>
    </div>
</div>

<div class="content">
    <div class="cards" id="cards"><div class="loading">Loading data…</div></div>

    <div class="chart-section">
        <div class="chart-title">System-Auslastung (Sekunden pro Zeitfenster)</div>
        <div class="chart-wrap"><canvas id="loadChart"></canvas></div>
    </div>

    <div class="chart-section">
        <div class="chart-title">Gleichzeitige Tasks</div>
        <div class="chart-wrap"><canvas id="concChart"></canvas></div>
    </div>

    <div style="display:grid; grid-template-columns: 1fr 1fr; gap: 16px;">
        <div class="chart-section">
            <div class="chart-title">LLM nach Task-Typ</div>
            <div class="chart-wrap"><canvas id="taskChart"></canvas></div>
        </div>
        <div class="chart-section">
            <div class="chart-title">Last pro System (LLM vs Bilder)</div>
            <div class="chart-wrap"><canvas id="provChart"></canvas></div>
        </div>
    </div>

    <div class="chart-section">
        <div class="chart-title">LLM Auswertung nach Modell (Gesamtdauer in Sekunden)</div>
        <div class="chart-wrap" style="height:auto;min-height:260px;"><canvas id="modelDurChart"></canvas></div>
    </div>

    <div class="chart-section" style="overflow-x:auto;">
        <div class="chart-title">Modell-Statistiken</div>
        <table class="detail-table" id="modelStatsTable">
            <thead>
                <tr>
                    <th data-mcol="model">Modell</th>
                    <th data-mcol="count">Aufrufe</th>
                    <th data-mcol="total_dur">Gesamt (s)</th>
                    <th data-mcol="avg_dur">&#8960; Dauer (s)</th>
                    <th data-mcol="min_dur">Min (s)</th>
                    <th data-mcol="max_dur">Max (s)</th>
                    <th data-mcol="p90_dur">P90 (s)</th>
                    <th data-mcol="tokens_in">Tokens In</th>
                    <th data-mcol="tokens_out">Tokens Out</th>
                    <th data-mcol="avg_tok_s">&#8960; Tok/s Out</th>
                </tr>
            </thead>
            <tbody id="modelStatsBody"></tbody>
        </table>
    </div>

    <div style="display:grid; grid-template-columns: 1fr 1fr; gap: 16px;">
        <div class="chart-section">
            <div class="chart-title">&#8960; Ausfuehrungszeit pro Modell (Sekunden)</div>
            <div class="chart-wrap" style="height:auto;min-height:260px;"><canvas id="modelAvgChart"></canvas></div>
        </div>
        <div class="chart-section">
            <div class="chart-title">Tokens/s Output pro Modell</div>
            <div class="chart-wrap" style="height:auto;min-height:260px;"><canvas id="modelTokChart"></canvas></div>
        </div>
    </div>

    <div class="activity-section">
        <h3>Autonome Aktivitaeten</h3>
        <div class="activity-stats" id="activityStats"></div>
        <div class="activity-feed" id="activityFeed">
            <div class="activity-empty">Loading…</div>
        </div>
    </div>

    <div class="table-section">
        <h3>Alle Aufrufe</h3>
        <table class="detail-table" id="detailTable">
            <thead>
                <tr>
                    <th data-col="starttime">Zeit</th>
                    <th data-col="type">Typ</th>
                    <th data-col="system">System</th>
                    <th data-col="model">Model</th>
                    <th data-col="task">Task</th>
                    <th data-col="service">Agent</th>
                    <th data-col="duration_s">Dauer</th>
                    <th data-col="tokens">Tokens</th>
                </tr>
            </thead>
            <tbody id="detailBody"></tbody>
        </table>
    </div>
</div>

<script src="/static/admin/dashboard.js"></script>
</body>
</html>'''
