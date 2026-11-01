"""Image Prompt Logger — schreibt alle Bildgenerierungs-Prompts als JSONL nach logs/image_prompts.jsonl.

Jeder Eintrag enthaelt: Start/End-Timestamp, Agent, User, Original-Prompt, Final-Prompt,
Negative-Prompt, Backend, erkannte Appearances, Kontext-Daten.
"""
import json
import threading
from datetime import datetime, timedelta

from app.core.timeutils import utc_now
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.log import get_logger

logger = get_logger("img_prompt_log")

LOG_DIR = Path("./logs")
LOG_FILE = LOG_DIR / "image_prompts.jsonl"
_lock = threading.Lock()


def log_image_prompt(
    agent_name: str = "", original_prompt: str = "",
    final_prompt: str = "",
    negative_prompt: str = "",
    backend_name: str = "",
    backend_type: str = "",
    model: str = "",
    appearances: Optional[List[Dict[str, str]]] = None,
    agent_mentioned: bool = False,
    auto_enhance: bool = True,
    context: Optional[Dict[str, str]] = None,
    duration_s: float = 0.0,
    seed: int = 0,
    pose_prompt: str = "",
    expression_prompt: str = "",
    loras: Optional[List[Dict[str, Any]]] = None,
    reference_images: Optional[Dict[str, str]] = None,
    # Neue PromptBuilder-Variablen
    prompt_persons: Optional[Dict[int, str]] = None,
    prompt_outfits: Optional[Dict[int, str]] = None,
    prompt_mood: str = "",
    prompt_activity: str = "",
    prompt_location: str = "",
    actor_labels: Optional[List[str]] = None,
    workflow_type: str = "",
    entry_point: str = "",
    compose: Optional[Dict[str, Any]] = None,
    negative_folded: Optional[List[str]] = None,
    media: str = "",
    error: str = "",
    pose_checked_from: str = ""):
    """Log one image-generation prompt as a JSONL line.

    Args:
        agent_name: character name
        original_prompt: the original prompt (before enhancement)
        final_prompt: the final prompt (with appearances, prefix, suffix etc.)
        negative_prompt: negative prompt
        backend_name: name of the backend used (e.g. "LocalSD", "ComfyUI")
        backend_type: backend type (e.g. "a1111", "comfyui", "mammouth")
        model: model name (e.g. the checkpoint on A1111, the model on Mammouth)
        appearances: the detected appearances [{name, appearance}]
        agent_mentioned: whether the agent was detected in the prompt
        auto_enhance: whether auto-enhancement was active
        context: context data (outfit, feeling, activity, location)
        duration_s: generation duration in seconds
        reference_images: reference images {slot_title: file_path}
        compose: composition meta of prompt_compose.compose
            (use_case, family, style_had_slot, hint_rendered,
            negations_moved) — the basis of the numeric prompt verification
        negative_folded: terms this run folded from the negative into the
            prompt (backend without a negative input,
            supports_negative_prompt=false). Empty/None = nothing folded.
        media: "video" / "mesh" for non-image backends (empty = image).
            Without this parameter the central logger raised a (swallowed)
            TypeError for every video/mesh generation — they NEVER showed
            up in the log.
        pose_checked_from: the subject prompt BEFORE the LLM pose check
            (app/imagegen/pose_check.py) rewrote it; empty = no rewrite.
    """
    end_time = utc_now()
    start_time = end_time - timedelta(seconds=duration_s) if duration_s > 0 else end_time
    entry: Dict[str, Any] = {
        "starttime": start_time.isoformat(timespec="seconds"),
        "endtime": end_time.isoformat(timespec="seconds") if duration_s > 0 else "",
        "service": agent_name,
        "user_id": "",
        "backend": {
            "name": backend_name,
            "type": backend_type,
        },
        "model": model,
        "original_prompt": original_prompt,
        "final_prompt": final_prompt,
        "negative_prompt": negative_prompt,
        "appearances": [
            {"name": p.get("name", ""), "appearance": p.get("appearance", "")[:200]}
            for p in (appearances or [])
        ],
        "agent_mentioned": agent_mentioned,
        "auto_enhance": auto_enhance,
        "context": context or {},
        "seed": seed,
        "pose_prompt": pose_prompt,
        "expression_prompt": expression_prompt,
        "loras": [
            {"name": l.get("name", ""), "strength": l.get("strength", 1.0)}
            for l in (loras or [])
            if l.get("name") and l["name"] != "None"
        ],
        "reference_images": {
            slot: Path(path).name if path else ""
            for slot, path in (reference_images or {}).items()
        },
        # PromptBuilder-Variablen (separate Prompt-Teile)
        "prompt_variables": {
            "persons": prompt_persons or {},
            "outfits": prompt_outfits or {},
            "mood": prompt_mood,
            "activity": prompt_activity,
            "location": prompt_location,
            "actor_labels": actor_labels or [],
            "workflow_type": workflow_type,
            "entry_point": entry_point,
        },
    }
    if compose:
        entry["compose"] = compose
    if negative_folded:
        entry["negative_folded"] = list(negative_folded)
    if media:
        entry["media"] = media
    if error:
        entry["error"] = error
    if pose_checked_from:
        entry["pose_checked_from"] = pose_checked_from

    # JSONL schreiben
    with _lock:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # Kurze Zeile fuer strukturiertes Logging
    app_names = ", ".join(p.get("name", "?") for p in (appearances or []))
    lora_names = ", ".join(l.get("name", "?") for l in (loras or []) if l.get("name") and l["name"] != "None")
    ref_summary = ", ".join(f"{s.split('_')[-1]}={Path(p).name}" for s, p in (reference_images or {}).items() if p) or "none"
    if error:
        logger.error(
            "%s | %s | FEHLER: %s | prompt=%s...",
            agent_name, backend_name or "?", error[:200], original_prompt[:80])
    else:
        logger.info(
            "%s | %s | appearances=[%s] | refs=[%s] | loras=[%s] | prompt=%s...",
            agent_name, backend_name, app_names or "none", ref_summary, lora_names or "none", original_prompt[:80])
