"""Per-world LoRA library sync — the library is the single source for every
LoRA selection (game admin + player UI).

The library lives in ``image_generation.lora_triggers``; ONE entry per unique
LoRA name (user decision 2026-07-16, plan-lora-library.md):
``{lora, word, source, backends, missing_on}``:

- ``source``: "discovered" (added by this sync) or "manual" (user-created;
  a user-touched discovered entry — non-empty trigger word or edited in the
  library editor — counts as manual).
- ``backends``: backend names associated with this LoRA. ``[]`` on a manual
  entry means "all backends" (offered everywhere, never reconciled — the
  civitai/together case, nothing to verify against).
- ``missing_on``: subset of ``backends`` whose listing no longer reports the
  LoRA. Only ever non-empty on manual/touched entries — untouched discovered
  associations are removed instead. Missing entries stay offered in the
  dialogs, marked "(missing)" (the flag can be stale; a wrong pick fails
  visibly in the render).

Reconciliation rules per scanned backend B:

- Name reported by B, no entry -> new discovered entry with ``backends=[B]``.
- Name reported by B, entry exists (not "all backends") -> ensure B is in
  ``backends``, clear B from ``missing_on``.
- Entry lists B but B no longer reports the name: untouched discovered ->
  drop B (entry removed once ``backends`` empties); manual/touched -> keep B
  and flag it in ``missing_on``.
- A scan returning no names (backend down/unreachable/empty are
  indistinguishable) leaves that backend's associations untouched instead of
  mass-flagging them missing.
"""
import threading
from typing import Any, Dict, List

from app.core import config
from app.core.log import get_logger

logger = get_logger("lora_library")

_sync_lock = threading.Lock()


def _is_touched(entry: Dict[str, Any]) -> bool:
    """Manual entries and user-touched discovered ones survive a vanished
    backend listing (flagged missing) instead of being dropped."""
    if (entry.get("source") or "manual").strip() != "discovered":
        return True
    return bool((entry.get("word") or "").strip())


def sync_lora_library() -> Dict[str, Any]:
    """Reconciles the LoRA library against all discoverable image backends.

    Returns ``{"changed", "added", "removed", "missing", "scanned"}`` —
    ``added``/``removed`` count library entries, ``missing`` the (entry,
    backend) associations currently flagged missing on the scanned backends,
    ``scanned`` the backend names that delivered a list.
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
                # fetch_loras applies the backend's lora_filter itself.
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

            by_name: Dict[str, Dict[str, Any]] = {}
            for e in triggers:
                if isinstance(e, dict):
                    n = (e.get("lora") or "").strip()
                    if n and n not in by_name:
                        by_name[n] = e

            # Reported names: new discoveries + confirmed associations.
            for n in names:
                e = by_name.get(n)
                if e is None:
                    e = {"lora": n, "word": "", "source": "discovered",
                         "backends": [b.name], "missing_on": []}
                    triggers.append(e)
                    by_name[n] = e
                    result["added"] += 1
                    changed = True
                    continue
                backends = e.setdefault("backends", [])
                if not backends:
                    continue  # "all backends" entry — never reconciled
                if b.name not in backends:
                    backends.append(b.name)
                    changed = True
                missing_on = e.get("missing_on") or []
                if b.name in missing_on:
                    e["missing_on"] = [x for x in missing_on if x != b.name]
                    changed = True

            # Associations of B whose LoRA vanished from the listing.
            kept: List[Any] = []
            for e in triggers:
                if not isinstance(e, dict):
                    kept.append(e)
                    continue
                backends = e.get("backends") or []
                lname = (e.get("lora") or "").strip()
                if b.name not in backends or lname in nameset:
                    kept.append(e)
                    continue
                if _is_touched(e):
                    missing_on = e.setdefault("missing_on", [])
                    if b.name not in missing_on:
                        missing_on.append(b.name)
                        changed = True
                    kept.append(e)
                    continue
                remaining = [x for x in backends if x != b.name]
                changed = True
                if remaining:
                    e["backends"] = remaining
                    kept.append(e)
                else:
                    result["removed"] += 1  # last association gone — drop
            triggers = kept

        # Missing count over the scanned backends (for the admin toast).
        for e in triggers:
            if isinstance(e, dict):
                result["missing"] += sum(
                    1 for x in (e.get("missing_on") or [])
                    if x in result["scanned"])

        if changed:
            ig["lora_triggers"] = triggers
            config.save(data)
            logger.info("lora sync: +%d added, -%d removed, %d missing "
                        "(scanned: %s)", result["added"], result["removed"],
                        result["missing"], ", ".join(result["scanned"]) or "-")
        result["changed"] = changed
    return result
