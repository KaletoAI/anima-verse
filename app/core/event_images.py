"""Event illustration pipeline.

Renders images for disruption/danger events that overlay the location's
background while the event lasts. The "after" image on resolution is
produced here too.

Flow:
1. ``trigger_event_image(event_id, location_id, image_prompt)`` is called
   when an event spawns. With a background image and a backend of the
   ``event`` occasion available, an image is rendered and ``image_path`` is
   set in the event payload.
2. ``trigger_event_resolved_image(event_id, ...)`` is called on the
   ``resolve_event`` path. Output: ``resolved_image_path``.
3. ``get_effective_background_event(location_id)`` returns the path the
   ``/locations/{id}/background`` endpoint prefers — the event image while an
   unresolved event is active, the resolved image in the linger window, else
   the endpoint falls back to the normal location background.

The backend comes from the ``event`` occasion of the image routing
(``app/imagegen/routing.py``): its chain, re-run on the next entry after a
backend failure. Every event image has a sidecar ``<image>.json`` with the
backend that rendered it and the routing marks (``routing``, and
``fallback_from`` behind the intended entry).
"""

from __future__ import annotations

import json
import os
import random
import threading
import time
from datetime import datetime

from app.core.timeutils import parse_iso, utc_now
from pathlib import Path
from typing import Any, Dict, Optional

from app.core.log import get_logger
from app.core.paths import get_storage_dir

logger = get_logger("event_images")


# ---------------------------------------------------------------------------
# Pfade
# ---------------------------------------------------------------------------

def get_events_image_dir() -> Path:
    d = get_storage_dir() / "events"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _event_image_filename(event_id: str, resolved: bool) -> str:
    return f"{event_id}_resolved.png" if resolved else f"{event_id}.png"


def _event_image_path(event_id: str, resolved: bool) -> Path:
    return get_events_image_dir() / _event_image_filename(event_id, resolved)


# ---------------------------------------------------------------------------
# Effective Background Lookup
# ---------------------------------------------------------------------------

def get_effective_background_event(location_id: str) -> Optional[Path]:
    """Wenn ein aktives oder gerade-aufgeloestes (im Linger-Fenster)
    disruption/danger-Event mit Bild an dieser Location existiert,
    liefert diese Funktion den Pfad zum Event-Bild. Sonst None.

    Liefert den am juengsten erstellten Match — falls mehrere
    disruption/danger-Events (z.B. eines davon resolved+lingernd, eines
    aktiv) gleichzeitig existieren, gewinnt das aktive.
    """
    if not location_id:
        return None
    try:
        from app.models.events import list_events
    except Exception:
        return None

    try:
        linger_min = int(os.environ.get("EVENT_RESOLVED_IMAGE_LINGER_MINUTES", "30"))
    except (TypeError, ValueError):
        linger_min = 30

    candidates = []
    for evt in list_events(location_id=location_id):
        if evt.get("location_id") != location_id:
            continue
        cat = evt.get("category", "")
        if cat not in ("disruption", "danger"):
            continue
        candidates.append(evt)

    # Aktive Events bevorzugt vor resolved Events; innerhalb beider
    # Gruppen das juengste.
    active = [e for e in candidates if not e.get("resolved")]
    resolved = [e for e in candidates if e.get("resolved")]

    def _created(e):
        return e.get("created_at", "")

    if active:
        active.sort(key=_created, reverse=True)
        for evt in active:
            img = evt.get("image_path")
            if img and Path(img).exists():
                return Path(img)
        # Aktive Events ohne fertiges Bild → kein Swap. Wir warten.

    # Resolved-Linger: zeige resolved_image_path solange linger-Fenster offen.
    if resolved:
        resolved.sort(key=_created, reverse=True)
        for evt in resolved:
            resolved_at = evt.get("resolved_at")
            if not resolved_at:
                continue
            try:
                age_sec = (utc_now() - parse_iso(resolved_at)).total_seconds()
            except (TypeError, ValueError):
                continue
            if age_sec > linger_min * 60:
                continue
            # NUR ein echtes "Nachher"-Bild zeigen. KEIN Fallback aufs Danger-Bild
            # (image_path) — ein gelöstes Event soll sofort zum Standard-Hintergrund
            # zurück, nicht das alte Gefahren-Bild weiter anzeigen.
            rimg = evt.get("resolved_image_path")
            if rimg and Path(rimg).exists():
                return Path(rimg)

    return None


def get_effective_background_event_text(location_id: str) -> str:
    """Description of the ACTIVE event whose image is currently swapped in
    as the location background (same selection as
    get_effective_background_event's active branch). Empty during the
    resolved-linger window — the aftermath image speaks for itself, an
    'ongoing' line would contradict it — and while no event image is
    ready (no swap, normal background)."""
    if not location_id:
        return ""
    try:
        from app.models.events import list_events
    except Exception:
        return ""
    candidates = [e for e in list_events(location_id=location_id)
                  if e.get("location_id") == location_id
                  and e.get("category", "") in ("disruption", "danger")
                  and not e.get("resolved")]
    candidates.sort(key=lambda e: e.get("created_at", ""), reverse=True)
    for evt in candidates:
        img = evt.get("image_path")
        if img and Path(img).exists():
            return (evt.get("text") or "").strip()
    return ""


# ---------------------------------------------------------------------------
# Subscribers fuer SSE (Background-Ready Push)
# ---------------------------------------------------------------------------

import asyncio
from typing import AsyncIterator, List, Tuple

_subscribers: List[Tuple[asyncio.Queue, asyncio.AbstractEventLoop]] = []
_subs_lock = threading.Lock()


def publish_image_ready(event_id: str, location_id: str, kind: str) -> None:
    """Broadcast: Event-Bild fertig. ``kind`` ist 'event' oder 'resolved'."""
    payload = {"event_id": event_id, "location_id": location_id, "kind": kind}
    with _subs_lock:
        subs = list(_subscribers)
    for q, loop in subs:
        try:
            loop.call_soon_threadsafe(q.put_nowait, payload)
        except Exception as e:
            logger.debug("publish_image_ready: %s", e)


async def subscribe() -> AsyncIterator[Dict[str, Any]]:
    loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue()
    entry = (q, loop)
    with _subs_lock:
        _subscribers.append(entry)
    try:
        while True:
            yield await q.get()
    finally:
        with _subs_lock:
            if entry in _subscribers:
                _subscribers.remove(entry)


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------

def _read_image_dimensions(path: Path) -> Optional[tuple]:
    """Liest (width, height) des Referenzbildes. Bei Fehler None."""
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        with Image.open(path) as im:
            return im.size  # (width, height)
    except Exception as e:
        logger.debug("Konnte Bildgroesse nicht lesen (%s): %s", path, e)
        return None


def _safe_dims(width: int, height: int) -> tuple:
    """Snap to multiples of 8 (diffusion latent constraint), cap at 2048."""
    w = max(64, min(2048, (width // 8) * 8))
    h = max(64, min(2048, (height // 8) * 8))
    return w, h


def _do_generate(event_id: str,
                  location_id: str,
                  image_prompt: str,
                  resolved: bool) -> Optional[Path]:
    """Synchronous generation (already serialized in the queue).

    Returns the path of the stored image, or None. The image gets a sidecar
    ``<image>.json`` = ``{"backend", "backend_type", "routing",
    "fallback_from"?}``.
    """
    from app.models.world import get_background_path
    from app.models.events import update_event_fields

    # Reference image: the location's current background. The day/night
    # image matching the GAME calendar is picked inside get_background_path
    # — same logic as the /background endpoint, so the event image never
    # gets a day/night-wrong template.
    bg_path = get_background_path(location_id)
    if not bg_path or not bg_path.exists():
        logger.info("Event image [%s]: no background — skip", event_id)
        return None

    dims = _read_image_dimensions(bg_path)
    if not dims:
        logger.info("Event image [%s]: background dimensions unknown — skip", event_id)
        return None
    w, h = _safe_dims(*dims)

    from app.imagegen.routing import route_meta, run_routed
    from app.imagegen.service import get_image_service
    svc = get_image_service()
    if not svc.enabled:
        logger.warning("Event image [%s]: image service not available", event_id)
        return None

    # Open-air locations get the world calendar's weather into the prompt;
    # an interior does not (the event happens inside, the storm does not).
    from app.models.world import get_location_by_id, resolve_indoor_flag
    _outdoor = resolve_indoor_flag(get_location_by_id(location_id) or {},
                                   None) == "outdoor"
    from app.core.prompt_compose import compose as _compose
    from app.core.prompt_compose import outdoor_conditions as _conditions

    def _render(b):
        """Prompt, negative and reference slot built FOR ``b`` — the routing
        calls it again with the next backend after a failure."""
        composed = _compose(use_case="event", subject=image_prompt, backend=b,
                            conditions=_conditions(_outdoor))
        for _w in composed.warnings:
            logger.info("Prompt composer (event): %s", _w)
        params: Dict[str, Any] = {
            "width": w, "height": h,
            # The generation must not come from a cache — fresh seed per run.
            "seed": random.randint(1, 2**31 - 1),
        }
        # The location background as the reference — where the backend has
        # a slot for it.
        if int(getattr(b, "ref_slot_count", 0) or 0) >= 1:
            params["reference_images"] = {"input_reference_image_1": str(bg_path)}
        _log_meta = {"agent_name": f"Event {event_id}",
                     "original_prompt": image_prompt, "auto_enhance": False,
                     "compose": composed.meta}

        def _op(bb):
            # EVERY backend goes through the backend's GPU channel — two
            # generations must never run in parallel on one backend.
            return svc.run_on_backend_channel(
                bb, lambda: bb.generate(composed.prompt, composed.negative, params,
                                        log_meta=_log_meta),
                task_type="event_image", agent_name="system",
                label=f"Event: {event_id}{' (after)' if resolved else ''}")
        return svc.run_on_backend(b, op=_op)

    try:
        (images, used), route = run_routed("event", _render, has_ref=True,
                                           pool=svc.pool)
    except Exception as e:
        # Nothing usable in the chain, the routed backend(s) failed, load,
        # the media switch — logged with the real reason.
        logger.error("Event image [%s] failed: %s", event_id, e)
        return None

    out_path = _event_image_path(event_id, resolved)
    try:
        out_path.write_bytes(images[0])
        out_path.with_suffix(".json").write_text(json.dumps(
            {"backend": used.name, "backend_type": used.api_type,
             **route_meta(route)}), encoding="utf-8")
    except Exception as e:
        logger.error("Event image [%s] could not be stored: %s", event_id, e)
        return None

    field = "resolved_image_path" if resolved else "image_path"
    update_event_fields(event_id, **{field: str(out_path)})
    publish_image_ready(event_id, location_id, "resolved" if resolved else "event")
    logger.info("Event image [%s] %s rendered: %s (%dx%d, via %s)",
                event_id, "resolved" if resolved else "active", out_path.name,
                w, h, used.name)
    # Post-processing hand-off (pull model), fire-and-forget. No bytes sent.
    try:
        from app.core import postprocess_trigger
        postprocess_trigger.trigger(out_path, "event")
    except Exception as _pp_err:
        logger.debug("[EventImage] postprocess trigger skipped: %s", _pp_err)
    return out_path


def trigger_event_image(event_id: str,
                         location_id: str,
                         image_prompt: str,
                         resolved: bool = False) -> None:
    """Fire-and-forget Event-Bild-Generierung.

    Wird sowohl vom synchronen ``_generate_event``-Hot-Path als auch von
    Background-Threads aufgerufen — Generation wird in den GPU-Queue
    (submit_gpu_task) verschoben, das hier startet nur einen Thread, der
    die Submission macht. Der Thread blockiert bis das Bild geschrieben
    ist.
    """
    if not event_id or not location_id or not image_prompt:
        return

    def _run():
        try:
            _do_generate(event_id, location_id, image_prompt, resolved)
        except Exception as e:
            logger.error("Event-Bild [%s] Thread-Fehler: %s", event_id, e, exc_info=True)

    threading.Thread(target=_run, daemon=True, name=f"event-image-{event_id[:8]}").start()


def trigger_event_resolved_image(event_id: str,
                                  location_id: str,
                                  resolved_image_prompt: str) -> None:
    """Wie ``trigger_event_image`` — generiert das After-Bild bei Resolution."""
    trigger_event_image(event_id, location_id, resolved_image_prompt, resolved=True)


def trigger_resolved_image_from_text(event_id: str) -> None:
    """Hook fuer ``resolve_event``: erzeugt das After-Bild aus
    ``resolved_text`` + Ursprungs-Image-Prompt.

    Laeuft in einem Background-Thread, damit der Resolve-Pfad nicht
    blockiert. Bei fehlendem Background oder fehlender ``image_prompt``-
    Saat (Event ohne Bild beim Spawn — z.B. Welt-Daten-Lueck) wird
    sauber abgebrochen.
    """
    def _run():
        try:
            from app.models.events import get_event
            evt = get_event(event_id)
            if not evt:
                return
            loc_id = evt.get("location_id") or ""
            if not loc_id:
                return
            if evt.get("category") not in ("disruption", "danger"):
                return
            # Konsistenz: kein "After"-Bild ohne sichtbares "Before"-Bild.
            # Wenn der Ursprungs-Render nie geliefert hat (kein Background
            # zur Spawn-Zeit, Cache-Hit, Backend-Fehler), bleibt die
            # Location bei ihrem normalen Bild.
            if not evt.get("image_path"):
                return

            resolved_text = (evt.get("resolved_text") or "").strip()
            original_image_prompt = (evt.get("metadata", {}) or {}).get("image_prompt", "")

            new_prompt = _generate_resolved_image_prompt(
                event_text=evt.get("text", ""),
                resolved_text=resolved_text,
                original_image_prompt=original_image_prompt)
            if not new_prompt:
                return
            _do_generate(event_id, loc_id, new_prompt, resolved=True)
        except Exception as e:
            logger.error("Event-Resolved-Bild [%s] Fehler: %s", event_id, e, exc_info=True)

    threading.Thread(target=_run, daemon=True, name=f"event-image-resolved-{event_id[:8]}").start()


def _generate_resolved_image_prompt(event_text: str,
                                     resolved_text: str,
                                     original_image_prompt: str) -> str:
    """Tool-LLM: erzeugt einen englischen Bild-Prompt fuer das After-Bild.

    Ist klein gehalten — gibt bei Fehler einen einfachen Fallback zurueck
    (Ursprung minus "smoke/fire/danger" Schlagworte), damit das Bild
    nicht ausfaellt nur weil das LLM gerade nicht antwortet.
    """
    from app.core.llm_router import llm_call
    from app.core.prompt_templates import render_task

    try:
        sys_prompt, user_prompt = render_task(
            "random_event_resolved_image",
            event_text=event_text or "",
            resolved_text=resolved_text or "",
            original_image_prompt=original_image_prompt or "")
        response = llm_call(
            task="random_event",
            system_prompt=sys_prompt,
            user_prompt=user_prompt,
            agent_name="system")
        text = (response.content or "").strip()
        # Code-Fences abschneiden, Quotes trimmen, Markdown-Artefakte raus.
        import re as _re
        text = _re.sub(r"```[a-z]*\s*|\s*```", "", text).strip()
        text = text.strip('"').strip("'").strip()
        if text and len(text) > 10:
            return text
    except Exception as e:
        logger.debug("resolved_image_prompt LLM-Fehler: %s", e)

    # Fallback: Original-Prompt mit "aftermath"-Marker
    if original_image_prompt:
        return f"aftermath of: {original_image_prompt} — now resolved, calm, no active threat"
    return ""
