"""Model capabilities — lookup for model abilities (tool calling, vision, ...).

Reads ``shared/config/model_capabilities.json`` and offers substring matching
(the longest match wins, mirroring ``tool_formats.MODEL_FORMAT_LIBRARY``).

The file is SHARED across every world and tracked in git: what a model can do
and how it scored in the suitability test describes the model plus the hardware
behind it, never the world it was tested from. Old per-world files are folded
in once by ``model_capabilities_migration``.
"""
import json
import threading
from typing import Any, Dict, Optional

from app.core.log import get_logger

logger = get_logger("model_capabilities")

from app.core.paths import (
    get_model_capabilities_path as _caps_path,
    get_model_capabilities_outputs_path as _outputs_path,
)

_cache: Optional[Dict[str, Any]] = None
# Serializes read-modify-write on the JSON file — otherwise parallel test jobs
# (different providers) can overwrite each other while saving.
_write_lock = threading.RLock()


def _load() -> Dict[str, Any]:
    """Loads the capabilities file (lazy, cached)."""
    global _cache
    if _cache is not None:
        return _cache
    if not _caps_path().exists():
        _cache = {}
        return _cache
    try:
        with open(_caps_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        _cache = data.get("models", {})
    except Exception as e:
        logger.error("Failed to load %s: %s", _caps_path(), e)
        _cache = {}
    return _cache


def _load_full_file() -> Dict[str, Any]:
    """Loads the complete JSON file (including _comment etc.)."""
    if not _caps_path().exists():
        return {"_comment": "Model Capabilities.", "models": {}}
    try:
        with open(_caps_path(), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"_comment": "Model Capabilities.", "models": {}}


def _save_full_file(data: Dict[str, Any]) -> None:
    """Saves the complete JSON file and invalidates the caches."""
    global _cache, _suit_cache
    _caps_path().parent.mkdir(parents=True, exist_ok=True)
    with open(_caps_path(), "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    _cache = None
    _suit_cache = None


def invalidate_cache() -> None:
    """Drops the in-process caches — call after writing the file elsewhere."""
    global _cache, _suit_cache
    _cache = None
    _suit_cache = None


# Suitability test results: kept apart from the capability patterns and keyed by
# the full "Provider::Model" (lowercased) — so the same model on different
# hardware keeps separate results (speed above all) and they do NOT overwrite
# each other. Capabilities (tool_calling/vision/notes) stay shared model-wide
# via substring match.
_suit_cache: Optional[Dict[str, Any]] = None


def _load_suit() -> Dict[str, Any]:
    global _suit_cache
    if _suit_cache is not None:
        return _suit_cache
    _suit_cache = _load_full_file().get("suitability", {}) or {}
    return _suit_cache


def get_all_suitability() -> Dict[str, Any]:
    """All suitability results (key = 'provider::model' lowercased)."""
    return dict(_load_suit())


def get_suitability(model_full: str) -> Dict[str, Any]:
    """Suitability result for one concrete 'Provider::Model' (or {})."""
    return _load_suit().get((model_full or "").lower(), {})


def save_suitability(model_full: str, result: Dict[str, Any]) -> None:
    """Saves/updates the suitability result for 'Provider::Model'.

    Lock-protected so parallel test jobs do not overwrite each other.
    """
    with _write_lock:
        data = _load_full_file()
        data.setdefault("suitability", {})[(model_full or "").lower()] = result
        _save_full_file(data)


# --- Raw test outputs -------------------------------------------------------
# The suitability test replays REAL logged prompts, so a model's raw answer
# quotes characters and plot from the world it ran against. Useful for tuning
# templates, impossible to share — it lives in a gitignored sidecar file next to
# the results, keyed the same way.


def _load_outputs_file() -> Dict[str, Any]:
    path = _outputs_path()
    if not path.exists():
        return {"_comment": "Raw suitability test answers — local only.", "outputs": {}}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"_comment": "Raw suitability test answers — local only.", "outputs": {}}


def get_raw_outputs(model_full: str) -> Dict[str, str]:
    """Raw answers of one 'Provider::Model' run, keyed by check id."""
    return (_load_outputs_file().get("outputs") or {}).get((model_full or "").lower(), {})


def save_raw_outputs(model_full: str, outputs: Dict[str, str]) -> None:
    """Stores the raw answers of one test run in the local sidecar file."""
    if not outputs:
        return
    with _write_lock:
        data = _load_outputs_file()
        data.setdefault("outputs", {})[(model_full or "").lower()] = outputs
        _outputs_path().parent.mkdir(parents=True, exist_ok=True)
        with open(_outputs_path(), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)


def get_model_capabilities(model_name: str) -> Dict[str, Any]:
    """Resolves the capabilities for a model via substring match.

    The longest match wins. Falls back to the '_default' entry.

    Args:
        model_name: Full model name (e.g. "OllamaChat::mistral:7b",
                     "mistral:7b", "hf.co/Example/Some-Model-GGUF:Q4_K_M")

    Returns:
        Dict of capabilities: tool_calling, vision, notes_de, ...
    """
    models = _load()
    if not model_name or not models:
        return models.get("_default", {})

    # Strip the provider prefix (e.g. "OllamaChat::mistral:7b" -> "mistral:7b")
    if "::" in model_name:
        model_name = model_name.split("::", 1)[1]

    model_lower = model_name.lower()

    # Exact match first
    if model_lower in models:
        return models[model_lower]

    # Substring match (the longest match wins)
    best_match = ""
    best_caps = models.get("_default", {})

    for pattern, caps in models.items():
        if pattern.startswith("_"):
            continue
        if pattern.lower() in model_lower and len(pattern) > len(best_match):
            best_match = pattern
            best_caps = caps

    return best_caps


def get_all_capabilities() -> Dict[str, Any]:
    """Returns every entry (for the admin page)."""
    return dict(_load())


def save_model_capability(pattern: str, capabilities: Dict[str, Any]) -> None:
    """Saves/updates one entry in model_capabilities.json."""
    with _write_lock:
        data = _load_full_file()
        if "models" not in data:
            data["models"] = {}
        data["models"][pattern] = capabilities
        _save_full_file(data)


def delete_model_capability(pattern: str) -> bool:
    """Deletes an entry. Returns True if it existed."""
    with _write_lock:
        data = _load_full_file()
        models = data.get("models", {})
        if pattern in models and not pattern.startswith("_"):
            del models[pattern]
            _save_full_file(data)
            return True
        return False
