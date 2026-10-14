"""System Load Dashboard — overview of LLM and image generation load.

Read and aggregate call logs into an interactive Chart.js timeline.
"""
import json
from datetime import datetime, timedelta

from app.core.timeutils import parse_iso, utc_now
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import quote

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
    """Load system configuration from ProviderManager."""
    try:
        from app.core.provider_manager import get_provider_manager
        return get_provider_manager().get_systems_config()
    except Exception:
        return []


def _read_jsonl(path: Path, cutoff: str = "") -> List[Dict[str, Any]]:
    """Read JSONL entries and filter by cutoff timestamp."""
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


@router.get("/request-timing")
def request_timing_data():
    """Return recent per-route request timing statistics."""
    from app.core.request_timing import route_stats
    return {"routes": route_stats()}


@router.get("/data")
def dashboard_data(hours: int = Query(24, ge=0)):
    """Return aggregated dashboard data as JSON."""
    cutoff = ""
    if hours > 0:
        cutoff = (utc_now() - timedelta(hours=hours)).isoformat(timespec="seconds")

    # Load LLM calls
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

    # Load image calls
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

    # Time range
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
    """Aggregated activity feed: Instagram, reactions, story arcs and thoughts."""
    cutoff = ""
    if hours > 0:
        cutoff = (utc_now() - timedelta(hours=hours)).isoformat(timespec="seconds")

    events = []

    # 1. Instagram posts and comments
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
                    "detail": f"on a post by {post.get('agent_name', '')}",
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
                    "summary": f"Arc started: {arc.get('title', '')}",
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
                    # Both segments are DATA (a character name, a stored file
                    # name): percent-encode them, or a name with a space, a
                    # "#" or a "?" builds a URL that points somewhere else.
                    beat_meta["image_url"] = (
                        f"/characters/{quote(str(scene_img['character']), safe='')}"
                        f"/images/{quote(str(scene_img['filename']), safe='')}"
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
                        "summary": f"Arc resolved: {arc.get('title', '')}",
                        "detail": (arc.get("resolution", "") or "")[:120],
                    })
    except Exception as e:
        logger.debug("Activity: Story Arcs error: %s", e)

    # 3. Thought messages and social dialogs (from notifications)
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

    # Social dialogs are ordinary chat entries now
    # (see plan-thoughts-and-conversation.md).

    # Sort by timestamp (newest first)
    events.sort(key=lambda e: e.get("timestamp", ""), reverse=True)

    return {
        "events": events[:200],
        "total": len(events),
    }


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def dashboard_page():
    """Renders the dashboard HTML page."""
    from app.core.timeutils import clock_body_attrs
    # The clock settings reach the page's JS through <body data-…>, substituted
    # per request so a changed setting needs no more than a reload.
    html = _build_dashboard_html().replace("{clock_attrs}", clock_body_attrs())
    return HTMLResponse(content=html)


def _build_dashboard_html() -> str:
    return '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>System Load Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<link rel="stylesheet" href="/static/admin/dashboard.css">
</head>
<body {clock_attrs}>

<div class="header">
    <h1>System Load Dashboard</h1>
    <div class="time-btns">
        <button class="time-btn" data-hours="1">1h</button>
        <button class="time-btn" data-hours="6">6h</button>
        <button class="time-btn active" data-hours="24">24h</button>
        <button class="time-btn" data-hours="168">7d</button>
        <button class="time-btn" data-hours="0">All</button>
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
        <div class="chart-title">System load (seconds per time window)</div>
        <div class="chart-wrap"><canvas id="loadChart"></canvas></div>
    </div>

    <div class="chart-section">
        <div class="chart-title">Concurrent tasks</div>
        <div class="chart-wrap"><canvas id="concChart"></canvas></div>
    </div>

    <div style="display:grid; grid-template-columns: 1fr 1fr; gap: 16px;">
        <div class="chart-section">
            <div class="chart-title">LLM by task type</div>
            <div class="chart-wrap"><canvas id="taskChart"></canvas></div>
        </div>
        <div class="chart-section">
            <div class="chart-title">Load per system (LLM vs images)</div>
            <div class="chart-wrap"><canvas id="provChart"></canvas></div>
        </div>
    </div>

    <div class="chart-section">
        <div class="chart-title">LLM by model (total duration in seconds)</div>
        <div class="chart-wrap" style="height:auto;min-height:260px;"><canvas id="modelDurChart"></canvas></div>
    </div>

    <div class="chart-section" style="overflow-x:auto;">
        <div class="chart-title">Model statistics</div>
        <table class="detail-table" id="modelStatsTable">
            <thead>
                <tr>
                    <th data-mcol="model">Model</th>
                    <th data-mcol="count">Calls</th>
                    <th data-mcol="total_dur">Total (s)</th>
                    <th data-mcol="avg_dur">&#8960; Duration (s)</th>
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
            <div class="chart-title">&#8960; Execution time per model (seconds)</div>
            <div class="chart-wrap" style="height:auto;min-height:260px;"><canvas id="modelAvgChart"></canvas></div>
        </div>
        <div class="chart-section">
            <div class="chart-title">Output tokens/s per model</div>
            <div class="chart-wrap" style="height:auto;min-height:260px;"><canvas id="modelTokChart"></canvas></div>
        </div>
    </div>

    <div class="table-section" style="overflow-x:auto;">
        <h3>Request timing</h3>
        <table class="detail-table">
            <thead><tr><th>Route</th><th>Method</th><th>n</th><th>p50 ms</th><th>p95 ms</th><th>max ms</th><th>errors</th><th>aborted</th><th>streams</th></tr></thead>
            <tbody id="requestTimingBody"></tbody>
        </table>
    </div>

    <div class="activity-section">
        <h3>Autonomous activity</h3>
        <div class="activity-stats" id="activityStats"></div>
        <div class="activity-feed" id="activityFeed">
            <div class="activity-empty">Loading…</div>
        </div>
    </div>

    <div class="table-section">
        <h3>All calls</h3>
        <table class="detail-table" id="detailTable">
            <thead>
                <tr>
                    <th data-col="starttime">Time</th>
                    <th data-col="type">Type</th>
                    <th data-col="system">System</th>
                    <th data-col="model">Model</th>
                    <th data-col="task">Task</th>
                    <th data-col="service">Agent</th>
                    <th data-col="duration_s">Duration</th>
                    <th data-col="tokens">Tokens</th>
                </tr>
            </thead>
            <tbody id="detailBody"></tbody>
        </table>
    </div>
</div>

<script src="/static/admin/clock-format.js"></script>
<script src="/static/admin/dashboard.js"></script>
</body>
</html>'''
