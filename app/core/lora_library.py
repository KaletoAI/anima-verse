"""Instance LoRA library store and sync — the library is the single source for every
LoRA selection (game admin + player UI).

The library lives in ``<instance>/lora_library.json``; ONE entry per unique
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
import copy
import json
import os
import tempfile
import threading
from typing import Any, Callable, Dict, List, Optional, Sequence

from app.core import config, paths
from app.core.log import get_logger

logger = get_logger("lora_library")

_sync_lock = threading.Lock()


LORA_HISTORY_DIRNAME = ".lora-history"
LORA_HISTORY_KEEP = 50
_store_lock = threading.RLock()
_cache_key = None
_cache_entries: List[dict] = []
_invalid_logged = ""


class LoraLibraryUnavailable(RuntimeError):
    """An instance must be initialized before the library can be written."""


class LoraLibraryConflict(ValueError):
    """A library entry with this exact name already exists."""


def _load() -> List[dict]:
    """The stat-cached entries; raises ``ValueError`` for an unreadable file."""
    global _cache_key, _cache_entries
    with _store_lock:
        if not paths.instance_initialised():
            return []
        path = paths.get_lora_library_path()
        try:
            st = path.stat()
        except FileNotFoundError:
            _cache_key, _cache_entries = None, []
            return _cache_entries
        key = (path, st.st_mtime_ns, st.st_size)
        if key != _cache_key:
            data = config._read_json_file(path)
            if data.get("version") != 1 or not isinstance(data.get("entries"), list):
                raise ValueError(f"Invalid LoRA library: {path}")
            _cache_entries = data["entries"]
            _cache_key = key
        return _cache_entries


def entries() -> List[dict]:
    """Return the stat-cached library entries. Callers must not mutate them.

    An unreadable file reads as empty (renders keep working without LoRAs)
    and is logged; every writer refuses it instead, so it is never replaced."""
    global _invalid_logged
    try:
        return _load()
    except ValueError as exc:
        if _invalid_logged != str(exc):
            _invalid_logged = str(exc)
            logger.error("%s — LoRA library reads as empty until the file is fixed", exc)
        return []


def _mutate(fn: Callable[[List[dict]], bool]) -> List[dict]:
    """Serialize a read–modify–write, backing up only real changes."""
    global _cache_key
    with _store_lock:
        if not paths.instance_initialised():
            raise LoraLibraryUnavailable("LoRA library requires an initialized instance")
        items = copy.deepcopy(_load())
        if fn(items):
            path = paths.get_lora_library_path()
            config.snapshot_layer(path.parent, files=("lora_library.json",),
                                  history_dirname=LORA_HISTORY_DIRNAME,
                                  keep=LORA_HISTORY_KEEP)
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(dir=path.parent, suffix=".json.tmp")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    os.fchmod(stream.fileno(), 0o600)
                    json.dump({"version": 1, "entries": items}, stream,
                              indent=2, ensure_ascii=False)
                os.replace(temporary, path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            _cache_key = None
            with _dropped_lock:
                _dropped_logged.clear()
        return items


def add_manual_entry(lora: str, word: str = "", backends: Sequence[str] = ()) -> dict:
    """Add a manual entry; names are unique, including names containing slashes."""
    entry = {"lora": lora, "word": word, "source": "manual",
             "backends": list(backends), "missing_on": []}
    def add(items):
        if any(e.get("lora") == lora for e in items):
            raise LoraLibraryConflict(f"LoRA already exists: {lora}")
        items.append(entry)
        return True
    _mutate(add)
    return copy.deepcopy(entry)


def update_entry(lora: str, *, word: Optional[str] = None,
                 backends: Optional[Sequence[str]] = None,
                 rename_to: Optional[str] = None) -> dict:
    """Only actual edits make a discovered entry manual (the editor's ltTouch)."""
    updated = {}
    def update(items):
        entry = next((e for e in items if e.get("lora") == lora), None)
        if entry is None:
            raise KeyError(lora)
        if rename_to is not None and rename_to != lora and any(
                e.get("lora") == rename_to for e in items):
            raise LoraLibraryConflict(f"LoRA already exists: {rename_to}")
        before = copy.deepcopy(entry)
        for key, value in (("word", word), ("lora", rename_to),
                           ("backends", list(backends) if backends is not None else None)):
            if value is not None and (entry.get(key) or ([] if key == "backends" else "")) != value:
                entry[key] = value
        if entry != before:
            if entry.get("source") == "discovered":
                entry["source"] = "manual"
            if backends is not None:
                entry["missing_on"] = [b for b in entry.get("missing_on", [])
                                       if b in entry["backends"]]
        updated.update(entry)
        return entry != before
    _mutate(update)
    return updated


def delete_entry(lora: str) -> bool:
    """Remove an entry, returning False for an unknown name."""
    removed = False
    def delete(items):
        nonlocal removed
        kept = [e for e in items if e.get("lora") != lora]
        removed = len(kept) != len(items)
        items[:] = kept
        return removed
    _mutate(delete)
    return removed


def clear_discovered() -> int:
    """Remove discovered entries, preserving manual claims."""
    removed = 0
    def clear(items):
        nonlocal removed
        kept = [e for e in items if e.get("source") != "discovered"]
        removed = len(items) - len(kept)
        items[:] = kept
        return bool(removed)
    _mutate(clear)
    return removed


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
    if not paths.instance_initialised():
        return result
    try:
        from app.imagegen.service import get_image_service
        imagegen = get_image_service()
    except Exception as e:
        logger.debug("lora sync: image service unavailable: %s", e)
        return result
    if not imagegen.enabled:
        return result

    with _sync_lock:
        discoveries = []
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
            discoveries.append((b, names))

        def reconcile(triggers):
            changed = False

            for b, names in discoveries:
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
                triggers[:] = kept

            # Missing count over the scanned backends (for the admin toast).
            for e in triggers:
                if isinstance(e, dict):
                    result["missing"] += sum(
                        1 for x in (e.get("missing_on") or [])
                        if x in result["scanned"])

            if changed:
                # A changed association must be able to warn again (and an
                # obsolete warning must stop repeating) — see warn_dropped_loras.
                with _dropped_lock:
                    _dropped_logged.clear()
                logger.info("lora sync: +%d added, -%d removed, %d missing "
                            "(scanned: %s)", result["added"], result["removed"],
                            result["missing"], ", ".join(result["scanned"]) or "-")
            result["changed"] = changed
            return changed

        _mutate(reconcile)
    return result


class LoraNotAllowedError(ValueError):
    """A LoRA selection the library does not associate with the chosen backend.

    Carries the rejected names so a route can turn it into a 400 without
    re-parsing the message.
    """

    def __init__(self, backend_name: str, names: List[str]):
        self.backend_name = backend_name
        self.names = list(names)
        super().__init__(
            f"The LoRA library does not associate backend "
            f"'{backend_name}' with: {', '.join(self.names)}")


def _split_loras(backend: Any, loras: Any) -> tuple:
    """The ONE association predicate, applied to a whole selection.

    Returns ``(kept, dropped)``: ``kept`` are the ENTRIES that may be sent to
    ``backend`` (in the given order, unchanged — including the "None"
    placeholder of an unused slot and anything that is not a dict, which the
    backends drop themselves), ``dropped`` the NAMES the library does not
    associate with this backend.

    Association = the entry appears in ``get_lora_options`` for this backend,
    which includes entries the sync flagged ``missing_on`` — they stay
    offered, marked "(missing)", the flag can be stale, and a wrong pick
    fails visibly in the render result.
    """
    entries = list(loras or [])
    if not entries:
        return [], []
    from app.core.config import get_lora_options
    named = [(e, str(e.get("name") or "").strip()) for e in entries
             if isinstance(e, dict)]
    named = [(e, n) for e, n in named if n and n != "None"]
    if not named:
        return entries, []
    allowed = {o["name"] for o in get_lora_options(
        getattr(backend, "name", "") or "",
        lora_filter=getattr(backend, "lora_filter", "") or "")}
    bad = {id(e) for e, n in named if n not in allowed}
    kept = [e for e in entries if id(e) not in bad]
    dropped = [n for e, n in named if n not in allowed]
    return kept, dropped


def unassociated_loras(backend: Any, loras: Any) -> List[str]:
    """The picked LoRA names the library does NOT associate with ``backend``
    (see :func:`_split_loras` for the rule)."""
    return _split_loras(backend, loras)[1]


def filter_allowed_loras(backend: Any, loras: Any) -> tuple:
    """``(kept, dropped)`` — the soft half of the gate, for LoRAs that were
    NOT picked in the current request.

    A stored LoRA (per-character image settings, use-case defaults, a slot
    LoRA of a body-slot package) is configuration, not a request: once the
    admin re-points a character at another backend or a LoRA loses its
    association, rejecting the render would break every automatic render of
    that character — expression variants, outfit and T-pose references, the
    agent loop's scene images — permanently, with nothing but a log line.
    So the render runs WITHOUT the unassociated entries; the caller reports
    them through :func:`warn_dropped_loras`.

    An EXPLICIT pick from a dialog keeps the hard reject
    (:func:`assert_loras_allowed`) — there a 400 tells the user what they
    just chose wrongly.
    """
    return _split_loras(backend, loras)


#: In-process memo for :func:`warn_dropped_loras` — one WARNING per
#: (subject, backend, lora name). Cleared whenever the library sync changes
#: something (a re-association must warn again) and capped, so a world with
#: many characters cannot grow it without bound.
_DROP_LOG_CAP = 512
_dropped_logged = set()
_dropped_lock = threading.Lock()


def warn_dropped_loras(backend_name: str, dropped: List[str],
                       subject: str = "") -> List[str]:
    """Reports LoRAs dropped by :func:`filter_allowed_loras` — ONCE per
    (subject, backend, lora), so a rendering loop cannot flood the log.

    ``subject`` is the character/agent the render belongs to. Returns the
    names that were actually logged by this call.
    """
    names = [n for n in (dropped or []) if n]
    if not names:
        return []
    fresh = []
    with _dropped_lock:
        if len(_dropped_logged) >= _DROP_LOG_CAP:
            _dropped_logged.clear()
        for n in names:
            key = (subject or "", backend_name or "", n)
            if key not in _dropped_logged:
                _dropped_logged.add(key)
                fresh.append(n)
    if fresh:
        logger.warning(
            "Stored LoRA %s is not associated with backend '%s'%s — rendering "
            "without it. Either associate it with that backend in "
            "/admin/settings (LoRA library) or remove it from the image "
            "settings that still ask for it.",
            ", ".join(fresh), backend_name or "?",
            f" (render for {subject})" if subject else "")
    return fresh


def assert_loras_allowed(backend: Any, loras: Any) -> None:
    """The server-side LoRA gate — the ONE place its rule lives.

    Every LoRA dropdown is backend-scoped (the library entries of the chosen
    backend only), so this is the safety net for direct API calls: a pick the
    library does not associate with the resolved backend is rejected instead
    of being handed to the gateway, where it either fails with a cryptic
    error or is silently ignored and the user gets an image without the
    expected effect.

    Raises :class:`LoraNotAllowedError` (a ``ValueError``); callers that face
    an HTTP client map it to 400.
    """
    absent = _split_loras(backend, loras)[1]
    if absent:
        raise LoraNotAllowedError(getattr(backend, "name", "") or "", absent)
