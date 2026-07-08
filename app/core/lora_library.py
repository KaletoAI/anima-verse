"""Per-world LoRA library sync — the library is the single source for every
LoRA selection (game admin + player UI).

The library lives in ``image_generation.lora_triggers``; entries are
``{lora, word, endpoint, source, missing}``:

- ``source``: "discovered" (added by this sync) or "manual" (user-created;
  missing field counts as manual for backward compatibility).
- ``missing``: True when the entry's LoRA no longer exists on its backend.

Reconciliation rules (user decision 2026-07-06):
- Names reported by a backend but absent from the library are added with
  ``source="discovered"``.
- Entries whose LoRA vanished from their backend: manual entries (and
  user-touched discovered ones — non-empty trigger word) are kept and
  flagged ``missing``; untouched discovered entries are removed.
- Entries with an empty endpoint ("all backends") or an endpoint without a
  LoRA listing (civitai/together) are never touched — unverifiable.
- A scan returning no names (backend down/unreachable/empty) leaves that
  backend's entries untouched instead of mass-flagging them missing.
"""
import threading
from typing import Any, Dict, List

from app.core import config
from app.core.log import get_logger

logger = get_logger("lora_library")

_sync_lock = threading.Lock()


def sync_lora_library() -> Dict[str, Any]:
    """Reconciles the LoRA library against all discoverable image backends.

    Returns ``{"changed", "added", "removed", "missing", "scanned"}`` —
    ``missing`` is the number of entries currently flagged missing on the
    scanned backends, ``scanned`` the backend names that delivered a list.
    """
    result: Dict[str, Any] = {"changed": False, "added": 0, "removed": 0,
                              "missing": 0, "scanned": []}
    try:
        from app.imagegen.service import get_image_service
        imagegen = get_image_service()
    except Exception as e:
        logger.debug("lora sync: image service unavailable: %s", e)
        return result
    if not imagegen.enabled:
        return result

    with _sync_lock:
        data = config.get_all()
        ig = data.setdefault("image_generation", {})
        triggers: List[Any] = ig.get("lora_triggers")
        if not isinstance(triggers, list):
            triggers = []
        changed = False

        for b in getattr(imagegen, "backends", []):
            if not getattr(b, "instance_enabled", True):
                continue
            if not getattr(b, "lora_url", ""):
                continue
            try:
                names = [str(n).strip() for n in (b.fetch_loras() or [])
                         if n and str(n).strip()]
            except Exception as e:
                logger.warning("lora sync: %s fetch failed: %s", b.name, e)
                continue
            if not names:
                # Down/unreachable or genuinely empty — indistinguishable, so
                # leave this backend's entries alone (no mass "missing").
                logger.info("lora sync: %s returned no LoRAs — skipped", b.name)
                continue
            result["scanned"].append(b.name)
            nameset = set(names)
            known = {(e.get("lora") or "").strip()
                     for e in triggers
                     if isinstance(e, dict) and (e.get("endpoint") or "") == b.name}

            # New discoveries
            for n in names:
                if n not in known:
                    triggers.append({"lora": n, "word": "", "endpoint": b.name,
                                     "source": "discovered", "missing": False})
                    result["added"] += 1
                    changed = True

            # Reconcile existing entries of this backend
            kept: List[Any] = []
            for e in triggers:
                if not isinstance(e, dict) or (e.get("endpoint") or "") != b.name:
                    kept.append(e)
                    continue
                lname = (e.get("lora") or "").strip()
                if lname in nameset:
                    if e.get("missing"):
                        e["missing"] = False
                        changed = True
                    kept.append(e)
                    continue
                source = (e.get("source") or "manual").strip()
                touched = bool((e.get("word") or "").strip())
                if source == "discovered" and not touched:
                    result["removed"] += 1
                    changed = True
                    continue  # vanished from the backend — drop silently
                if not e.get("missing"):
                    e["missing"] = True
                    changed = True
                result["missing"] += 1
                kept.append(e)
            triggers = kept

        if changed:
            ig["lora_triggers"] = triggers
            config.save(data)
            logger.info("lora sync: +%d added, -%d removed, %d missing "
                        "(scanned: %s)", result["added"], result["removed"],
                        result["missing"], ", ".join(result["scanned"]) or "-")
        result["changed"] = changed
    return result
