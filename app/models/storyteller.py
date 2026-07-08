"""Storyteller configuration per world.

Configures the storyteller pipeline (act engine): which skills may fire,
which chat mode the agent runs in (rp_first / single / no_tools), which
LLM task is routed.

Storage: ``storage/<world>/storyteller.json`` — single JSON object,
filled with defaults on first read.

The offerable skill list is DYNAMIC — every loaded skill can be toggled
for the storyteller (no hardcoded skill ids here, R1). Defaults keep the
whitelist deliberately small: the storyteller is a GM tool, not a full
chat partner — only the "world action" seeds below start enabled, and
communication/movement verbs stay off (the avatar moves via UI, dialogue
runs through regular chat sessions)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from app.core.log import get_logger
from app.core.paths import get_storage_dir

logger = get_logger("storyteller")


def _known_skill_ids() -> list:
    """SKILL_IDs of all currently loaded skills — the storyteller
    whitelist offers exactly the world's skills (packages included)
    instead of a hardcoded list. Ids missing from a stored config
    default to the seed value (False unless listed in _DEFAULTS)."""
    try:
        from app.core.dependencies import get_skill_manager
        ids = sorted({s.SKILL_ID for s in get_skill_manager().skills
                      if getattr(s, "SKILL_ID", "")})
        if ids:
            return ids
    except Exception as e:
        logger.debug("storyteller: skill enumeration failed: %s", e)
    return sorted(_DEFAULTS["enabled_skills"].keys())


_DEFAULTS: Dict[str, Any] = {
    "chat_mode": "rp_first",
    "llm_task": "storyteller",
    # Seed values: only the "world action" skills start enabled; every
    # other loaded skill defaults to False.
    "enabled_skills": {
        "outfit_change": True,
        "image_generation": True,
        "consume_item": True,
    },
}

_VALID_MODES = {"rp_first", "single", "no_tools"}


def _path() -> Path:
    sd = get_storage_dir()
    sd.mkdir(parents=True, exist_ok=True)
    return sd / "storyteller.json"


def _normalize(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Merge mit Defaults + Validierung."""
    out: Dict[str, Any] = {
        "chat_mode": _DEFAULTS["chat_mode"],
        "llm_task": _DEFAULTS["llm_task"],
        "enabled_skills": {k: bool(_DEFAULTS["enabled_skills"].get(k, False))
                           for k in _known_skill_ids()},
    }
    if not isinstance(cfg, dict):
        return out

    mode = str(cfg.get("chat_mode") or "").strip().lower()
    if mode in _VALID_MODES:
        out["chat_mode"] = mode

    task = str(cfg.get("llm_task") or "").strip()
    if task:
        out["llm_task"] = task

    skills = cfg.get("enabled_skills") or {}
    if isinstance(skills, dict):
        for k in out["enabled_skills"]:
            if k in skills:
                out["enabled_skills"][k] = bool(skills[k])
    return out


def get_storyteller_config() -> Dict[str, Any]:
    """Liest die Storyteller-Config der aktuellen Welt. Fehlende Felder
    werden mit Defaults gefüllt, damit Aufrufer nicht null-checken
    müssen."""
    p = _path()
    if not p.exists():
        return _normalize({})
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return _normalize(data if isinstance(data, dict) else {})
    except Exception as e:
        logger.warning("storyteller load failed: %s", e)
        return _normalize({})


def save_storyteller_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Persistiert die Storyteller-Config der aktuellen Welt. Werte werden
    auf bekannte Felder beschränkt und auf gültige Modi/Skills normiert."""
    cleaned = _normalize(cfg or {})
    p = _path()
    p.write_text(json.dumps(cleaned, ensure_ascii=False, indent=2),
                 encoding="utf-8")
    return cleaned


def list_skill_keys() -> list:
    """Stable order of all offerable skill keys — for the UI."""
    return _known_skill_ids()
