"""One-time consolidation of the per-world model capability files.

``model_capabilities.json`` used to live next to every world under
``worlds/<world>/``. What it holds — whether a model can call tools or see
images, and how it scored in the suitability test — describes the MODEL and the
hardware serving it, never the world it happened to be tested from. So the
results are folded into one shared file, ``shared/config/model_capabilities.json``,
which is tracked in git.

The merge is content-driven, not last-writer-wins:

* ``suitability`` (key ``provider::model``) — the entry with the greater
  ``tested_date`` wins; an entry carrying a date beats one without; on a tie the
  file modified more recently wins.
* ``models`` (capability patterns) — entries that carry no information at all
  (``{}``, or every field null/empty) are dropped instead of migrated; two
  informative entries are decided by file mtime.
* Whatever the shared file already holds takes part in the same comparison, so
  results pulled in from git are never blindly overwritten.

The raw model answers inside the test results (``checks[].output``) are split
off into the gitignored sidecar file — the test replays REAL logged prompts, so
those answers quote the world's characters and plot and must never reach a
shared, committed file. Scores, verdicts and timings stay.

Each source file is renamed to ``*.migrated`` afterwards, which is what makes
this run exactly once per world file.
"""
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.core.log import get_logger
from app.core.paths import (
    get_model_capabilities_path,
    get_shared_dir,
    get_storage_dir,
)

logger = get_logger("model_capabilities_migration")

CAPS_FILENAME = "model_capabilities.json"
_DEFAULT_COMMENT = (
    "Model capabilities and suitability test results, shared across all worlds."
)


def has_capability_info(caps: Optional[Dict[str, Any]]) -> bool:
    """True when a capability entry actually says something about a model.

    A row the admin page saved without filling anything in looks like
    ``{"tool_calling": null, "vision": null, "notes_de": ""}`` — structurally
    present, informationally empty. Those are noise, not results.
    """
    if not isinstance(caps, dict) or not caps:
        return False
    if caps.get("tool_calling") is not None or caps.get("vision") is not None:
        return True
    if (caps.get("notes_de") or "").strip():
        return True
    if (caps.get("tool_instruction") or "").strip():
        return True
    return any(k.startswith("tested_") for k in caps)


def _tested_date(entry: Any) -> str:
    """The ``tested_date`` of a suitability entry ('' when absent)."""
    if not isinstance(entry, dict):
        return ""
    return str(entry.get("tested_date") or "")


def merge_capability_sources(
    sources: List[Tuple[Dict[str, Any], float]],
) -> Tuple[Dict[str, Any], Dict[str, int]]:
    """Merges capability files into one payload.

    Args:
        sources: ``(file content, mtime)`` pairs. The shared file's own content
            belongs in here too — it competes under the same rules.

    Returns:
        ``(merged payload, stats)``.
    """
    models: Dict[str, Any] = {}
    model_mtime: Dict[str, float] = {}
    suitability: Dict[str, Any] = {}
    suit_mtime: Dict[str, float] = {}
    dropped: set = set()
    stats = {"models": 0, "suitability": 0, "dropped_empty": 0, "conflicts": 0}

    for data, mtime in sources:
        if not isinstance(data, dict):
            continue

        for pattern, caps in (data.get("models") or {}).items():
            if pattern.startswith("_"):
                # Meta rows such as "_default" carry no per-model result; keep
                # the one from the most recently touched file.
                if pattern not in models or mtime > model_mtime[pattern]:
                    models[pattern] = caps
                    model_mtime[pattern] = mtime
                continue
            if not has_capability_info(caps):
                dropped.add(pattern)
                continue
            if pattern not in models:
                models[pattern] = caps
                model_mtime[pattern] = mtime
                continue
            stats["conflicts"] += 1
            if mtime > model_mtime[pattern]:
                models[pattern] = caps
                model_mtime[pattern] = mtime

        for key, entry in (data.get("suitability") or {}).items():
            if key not in suitability:
                suitability[key] = entry
                suit_mtime[key] = mtime
                continue
            stats["conflicts"] += 1
            new_date = _tested_date(entry)
            old_date = _tested_date(suitability[key])
            if new_date > old_date or (new_date == old_date and mtime > suit_mtime[key]):
                suitability[key] = entry
                suit_mtime[key] = mtime

    stats["models"] = len([k for k in models if not k.startswith("_")])
    stats["suitability"] = len(suitability)
    # A pattern that is empty in one file but informative in another is kept,
    # not counted as dropped.
    stats["dropped_empty"] = len(dropped - set(models))
    return {
        "_comment": _DEFAULT_COMMENT,
        "models": models,
        "suitability": suitability,
    }, stats


def split_raw_outputs(
    payload: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Dict[str, str]]]:
    """Separates the raw model answers from the shareable results.

    The suitability test replays REAL logged prompts, so ``checks[].output``
    quotes the characters and plot of the world it ran against. Scores,
    verdicts, timings and the ``detail`` line say nothing about a world and are
    what actually belongs in the shared file; the raw answers move to the local
    sidecar. Mutates nothing — returns a cleaned copy plus the extracted
    answers keyed ``provider::model`` -> ``check id`` -> answer.
    """
    outputs: Dict[str, Dict[str, str]] = {}
    cleaned = dict(payload)
    suitability: Dict[str, Any] = {}
    for key, entry in (payload.get("suitability") or {}).items():
        if not isinstance(entry, dict):
            suitability[key] = entry
            continue
        entry = dict(entry)
        suit = entry.get("tested_suitability")
        if isinstance(suit, dict) and isinstance(suit.get("checks"), list):
            suit = dict(suit)
            checks = []
            per_model: Dict[str, str] = {}
            for check in suit["checks"]:
                if not isinstance(check, dict):
                    checks.append(check)
                    continue
                check = dict(check)
                raw = check.pop("output", None)
                if raw:
                    per_model[str(check.get("id") or len(per_model))] = raw
                checks.append(check)
            suit["checks"] = checks
            entry["tested_suitability"] = suit
            if per_model:
                outputs[key] = per_model
        suitability[key] = entry
    cleaned["suitability"] = suitability
    return cleaned, outputs


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning("Skipping unreadable %s: %s", path, e)
        return None


def find_world_capability_files() -> List[Path]:
    """Every legacy per-world capabilities file still waiting to be folded in.

    Covers ``worlds/*/`` under the project root plus the active storage
    directory, which a ``--storage`` start can put anywhere.
    """
    found: List[Path] = []
    worlds_dir = get_shared_dir().parent / "worlds"
    if worlds_dir.is_dir():
        found.extend(sorted(worlds_dir.glob("*/" + CAPS_FILENAME)))
    try:
        current = get_storage_dir() / CAPS_FILENAME
    except Exception:
        current = None
    if current is not None and current.is_file() and current not in found:
        found.append(current)
    return [p for p in found if p.is_file()]


def migrate_model_capabilities_once() -> Optional[Dict[str, int]]:
    """Folds all per-world capability files into the shared one.

    Returns the merge stats when something was migrated, otherwise ``None``.
    """
    world_files = find_world_capability_files()
    if not world_files:
        return None

    target = get_model_capabilities_path()
    sources: List[Tuple[Dict[str, Any], float]] = []
    if target.is_file():
        existing = _read_json(target)
        if existing is not None:
            sources.append((existing, target.stat().st_mtime))

    migrated: List[Path] = []
    for path in world_files:
        data = _read_json(path)
        if data is None:
            continue
        sources.append((data, path.stat().st_mtime))
        migrated.append(path)

    if not migrated:
        return None

    merged, stats = merge_capability_sources(sources)
    merged, raw_outputs = split_raw_outputs(merged)
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)

    if raw_outputs:
        from app.core.model_capabilities import save_raw_outputs

        for model_full, per_model in raw_outputs.items():
            save_raw_outputs(model_full, per_model)
    stats["raw_outputs"] = len(raw_outputs)

    for path in migrated:
        try:
            path.rename(path.with_suffix(path.suffix + ".migrated"))
        except Exception as e:
            logger.warning("Could not rename %s: %s", path, e)

    from app.core.model_capabilities import invalidate_cache

    invalidate_cache()
    stats["files"] = len(migrated)
    logger.info(
        "Model capabilities consolidated: %d file(s) -> %s "
        "(%d patterns, %d test results, %d empty entries dropped)",
        stats["files"], target, stats["models"], stats["suitability"],
        stats["dropped_empty"],
    )
    return stats
