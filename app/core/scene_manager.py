"""Szenen-Lebenszyklus (plan-room-conversation §7).

- ``touch`` öffnet/aktualisiert die Szene eines Raums bei jeder Äußerung
  (aufgerufen aus ``perception.record_utterance``).
- ``run_idle_consolidation`` schließt verebbte Szenen: LLM-Summary der Roh-
  Äußerungen → Szenen-Erinnerung in jedem Teilnehmer-Gedächtnis → Perceptions
  prunen. Der Agent-Loop ruft das periodisch (in einem Thread).

Konsolidierung ist event-getrieben (Szenen-Ende), nicht 6h-Batch — der Batch
bleibt nur Sicherheitsnetz. Roh-Wahrnehmungen sind vergänglich (nach der Summary
verworfen); Utterances bleiben als kanonische Wahrheit für die Beobachter-Sicht.
"""
from __future__ import annotations

from typing import Dict, Any

from app.core.log import get_logger
from app.core.timeutils import utc_now, utc_now_iso
from app.core.perception import STORYTELLER_SPEAKER

logger = get_logger("scene_manager")

# Stille-Schwelle, ab der eine offene Szene als verebbt gilt und geschlossen wird.
SCENE_IDLE_SEC = 600  # 10 min


def touch(location_id: str, room_id: str, speaker: str, ts: str = "") -> int:
    """Szene des Raums öffnen/aktualisieren. Best-effort, nie blockierend."""
    try:
        from app.models import scene_store
        return scene_store.touch_scene(location_id, room_id, speaker, ts or utc_now_iso())
    except Exception as e:  # noqa: BLE001
        logger.debug("scene touch failed (%s/%s): %s", location_id, room_id, e)
        return 0


def run_idle_consolidation(skip_room_keys=None) -> int:
    """Schließt + konsolidiert alle verebbten offenen Szenen. Gibt die Anzahl
    konsolidierter Szenen zurück. Synchron (LLM + DB) — vom Loop via to_thread.

    ``skip_room_keys``: Menge von „loc/room"-Keys, die NICHT konsolidiert werden
    (Räume mit ausstehender Pflicht-Antwort) — sonst wird der Stream geprunt,
    bevor der adressierte Character antworten konnte."""
    from datetime import timedelta
    from app.models import scene_store
    skip = skip_room_keys or set()
    cutoff = (utc_now() - timedelta(seconds=SCENE_IDLE_SEC)).isoformat(timespec="seconds")
    try:
        idle = scene_store.get_idle_open_scenes(cutoff)
    except Exception as e:  # noqa: BLE001
        logger.debug("get_idle_open_scenes failed: %s", e)
        return 0
    n = 0
    for scene in idle:
        key = f"{scene.get('location_id', '')}/{scene.get('room_id', '')}"
        if key in skip:
            logger.debug("scene %s nicht konsolidiert: offene Pflicht-Antwort im Raum",
                         scene.get("id"))
            continue
        try:
            consolidate_scene(scene)
            n += 1
        except Exception as e:  # noqa: BLE001
            logger.warning("scene %s consolidation failed: %s", scene.get("id"), e)
    return n


def consolidate_scene(scene: Dict[str, Any]) -> None:
    """Eine verebbte Szene konsolidieren: LLM-Summary → Teilnehmer-Gedächtnis →
    Perceptions prunen → als consolidated markieren."""
    from app.models import scene_store
    from app.models.memory import add_memory

    sid = scene.get("id")
    utterances = scene_store.get_scene_utterances(scene)
    # The storyteller (narration) is not a character → no participant memory.
    # Its lines stay in the transcript (context).
    participants = [p for p in (scene.get("participants") or []) if p and p != STORYTELLER_SPEAKER]

    # Leere Szene (nur Geflüster-Meta o.ä. / nichts Inhaltliches) → ohne Summary
    # schließen, aber trotzdem prunen, damit sie nicht offen bleibt.
    lines = []
    for u in utterances:
        sp = (u.get("speaker") or "").strip()
        content = (u.get("content") or "").strip()
        if sp and content:
            lines.append(f"{sp}: {content}")

    summary = ""
    if lines and participants:
        summary = _summarize(scene, lines)
        if not summary:
            # LLM summary failed for a scene WITH content: leave the scene
            # OPEN (no prune, no mark_consolidated) so the next idle pass
            # retries. Closing it with an empty summary would prune the raw
            # perceptions AND hide the scene from every recap
            # (summary != '' filter) — the conversation would vanish.
            # Safety valve: after 24h of failed retries give up and close
            # without a summary (logged as ERROR) so a permanently broken
            # consolidation LLM cannot hammer the queue forever.
            _last = scene.get("last_activity_ts") or ""
            _too_old = False
            try:
                from app.core.timeutils import parse_iso, utc_now as _unow
                _too_old = bool(_last) and (
                    (_unow() - parse_iso(_last)).total_seconds() > 24 * 3600)
            except Exception:
                pass
            if not _too_old:
                logger.warning("Szene %s: Summary-LLM lieferte nichts — Szene "
                               "bleibt offen für Retry (%d Äußerungen)",
                               sid, len(lines))
                return
            logger.error("Szene %s: Summary scheitert seit >24h — schließe ohne "
                         "Summary (%d Äußerungen gehen aus dem Recap verloren)",
                         sid, len(lines))

    if summary:
        for p in participants:
            try:
                add_memory(
                    p, summary, memory_type="episodic", importance=3,
                    tags=["scene"], context="scene",
                    extra_meta={"location_id": scene.get("location_id", ""),
                                "room_id": scene.get("room_id", ""),
                                "participants": participants,
                                "scene_id": sid})
            except Exception as e:  # noqa: BLE001
                logger.debug("scene-memory add failed for %s: %s", p, e)

    pruned = 0
    try:
        pruned = scene_store.prune_scene_perceptions(scene)
    except Exception as e:  # noqa: BLE001
        logger.debug("scene %s prune failed: %s", sid, e)
    try:
        scene_store.mark_consolidated(sid, summary)
    except Exception as e:  # noqa: BLE001
        logger.debug("scene %s mark_consolidated failed: %s", sid, e)
    logger.info("Szene %s konsolidiert (%d Äußerungen, %d Teilnehmer, %d Perceptions gepruned)",
                sid, len(lines), len(participants), pruned)


def _summarize(scene: Dict[str, Any], lines: list) -> str:
    """LLM-Summary der Szene (wiederverwendetes Konsolidierungs-Muster)."""
    try:
        from app.core.llm_router import llm_call
        from app.core.prompt_templates import render_task
        from app.models.world import get_location_by_id
        loc = get_location_by_id(scene.get("location_id", "")) or {}
        loc_name = loc.get("name", "") or scene.get("location_id", "")
        room_name = ""
        for r in (loc.get("rooms") or []):
            if (r.get("id") or "") == scene.get("room_id", ""):
                room_name = r.get("name", "") or ""
                break
        # Sprache aus den Teilnehmern ableiten → Summary in der Spielsprache
        # (sonst defaultet die LLM auf Englisch).
        lang_instruction = ""
        try:
            from app.models.character import get_character_language, LANGUAGE_MAP
            _parts = [p for p in (scene.get("participants") or [])
                      if p and p != STORYTELLER_SPEAKER]
            if _parts:
                _code = (get_character_language(_parts[0]) or "en").strip()
                lang_instruction = f"\nWrite the summary in {LANGUAGE_MAP.get(_code, 'English')}."
        except Exception:
            pass
        sys_prompt, user_prompt = render_task(
            "consolidation_scene",
            location_name=loc_name, room_name=room_name,
            participants=", ".join(scene.get("participants") or []),
            transcript="\n".join(lines[:200]),
            lang_instruction=lang_instruction)
        resp = llm_call(task="consolidation", system_prompt=sys_prompt,
                        user_prompt=user_prompt)
        return (resp.content or "").strip() if resp else ""
    except Exception as e:  # noqa: BLE001
        logger.warning("scene summary LLM failed: %s", e)
        return ""
