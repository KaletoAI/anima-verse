"""Batch job: pre-warm the 3D chain for ALL outfit-piece COMBINATIONS of one
character.

Normally a mesh only ever comes into being for the combination the character
is CURRENTLY wearing — the outfit-change trigger renders the T-pose reference
and the auto-mesh hook turns it into a model. That means a 3D client sees a
model pop in the first time each combination is worn.

This job fills the caches up front, without dressing the character: the cache
signature of a combination (``_equipped_signature``) is computable from its
pieces alone, and both ``model_refs.generate_model_ref_images`` and
``model3d.generate_for_current_outfit`` accept that signature as an override.
Per combination, serially: T-pose reference (if missing) → mesh (if missing).

What a COMBINATION is (user decision 2026-07-27): every outfit piece in the
character's inventory is an option in the slot it declares first; per slot one
piece OR nothing, and the combinations are the cartesian product over the
slots. Saved outfit SETS play no role any more. The counts are large by
design — four figures are normal, seven happen — so:

* combinations are NEVER materialised as a list; they are enumerated lazily
  and COUNTED arithmetically;
* the run is one persistent queue task at low priority, so ordinary work
  always goes first;
* it is restart-proof without a state machine of its own: the caches say what
  is done, and a task the queue resets to pending after a crash simply skips
  everything cached and continues.

Deliberate scope:

* Items (sword, glasses, …) are IGNORED — a combination renders with its
  clothing pieces only (``items=[]``). Combinations including a carried item
  are still produced live by the existing auto-trigger when they are worn.
* The T-pose render runs regardless of the character's per-image auto toggles:
  those govern the automatic outfit-change render, while the batch always
  needs the mesh input.
* The all-empty combination is skipped (nothing to dress).
"""

import hashlib
import itertools
import sqlite3
import threading
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

from app.core.log import get_logger
from app.core.timeutils import utc_now_iso

logger = get_logger(__name__)

TASK_TYPE = "outfit_combos"
#: Queue priority of a batch run. The queue sorts ``priority ASC`` and the
#: default is 20 — 50 means "after everything normal".
PRIORITY_LOW = 50
#: Above this many combinations the exact missing count (one md5 per
#: combination) is not worth computing; the dialog then says "up to".
MAX_EXACT_COMBOS = 5000
#: Flat allowance for the T-pose render, added to the measured mesh duration.
TPOSE_SECONDS = 60.0
#: Used when no mesh has ever been generated (no history to average).
FALLBACK_SECONDS_PER_COMBO = 240.0

_lock = threading.Lock()
# character -> progress record of the RUNNING process; survives the run so the
# dialog can still show the result of the last batch. Empty after a restart —
# the counts come from the caches, this is only the live detail view.
_status: Dict[str, Dict[str, Any]] = {}


# ── Options and combinations ────────────────────────────────────────────

def combo_options(character_name: str) -> Dict[str, List[Dict[str, str]]]:
    """Every outfit piece in the character's inventory, grouped by slot.

    The slot is the piece's FIRST declared one — the same mapping the wardrobe
    uses when a piece is actually put on. Returns ``{slot: [{item_id, name},
    …]}``, slots and pieces sorted so the dialog is stable.
    """
    from app.models.inventory import get_character_inventory
    by_slot: Dict[str, List[Dict[str, str]]] = {}
    try:
        entries = (get_character_inventory(character_name) or {}).get("inventory") or []
    except Exception:
        logger.exception("Outfit combos %s: inventory unreadable", character_name)
        return {}
    for entry in entries:
        if entry.get("item_category") != "outfit_piece":
            continue
        slots = ((entry.get("outfit_piece") or {}).get("slots")) or []
        if not slots:
            continue
        item_id = str(entry.get("item_id") or "")
        if not item_id:
            continue
        row = {"item_id": item_id,
               "name": str(entry.get("item_name") or item_id)}
        bucket = by_slot.setdefault(str(slots[0]), [])
        if not any(r["item_id"] == item_id for r in bucket):
            bucket.append(row)
    for bucket in by_slot.values():
        bucket.sort(key=lambda r: (r["name"].lower(), r["item_id"]))
    return {slot: by_slot[slot] for slot in sorted(by_slot)}


def _resolve_filter(options: Dict[str, List[Dict[str, str]]],
                    slots_filter: Optional[Dict[str, Any]],
                    ) -> Tuple[Dict[str, List[Optional[str]]], str]:
    """Filter → the option list per slot, or an error message.

    A filter entry is a list of item ids plus ``null`` for "slot stays empty".
    A slot the filter does not mention keeps ALL its options (including empty),
    so an empty filter means "everything". Unknown item ids and empty lists are
    rejected — silently dropping them would render a different set than the
    dialog showed.
    """
    resolved: Dict[str, List[Optional[str]]] = {}
    raw = slots_filter if isinstance(slots_filter, dict) else {}
    for slot, pieces in options.items():
        known = [p["item_id"] for p in pieces]
        if slot not in raw:
            resolved[slot] = [None, *known]
            continue
        picked = raw.get(slot)
        if not isinstance(picked, list) or not picked:
            return {}, f"slot '{slot}': at least one option must stay selected"
        choices: List[Optional[str]] = []
        for value in picked:
            if value is None or value == "":
                if None not in choices:
                    choices.append(None)
                continue
            item_id = str(value)
            if item_id not in known:
                return {}, f"slot '{slot}': unknown piece '{item_id}'"
            if item_id not in choices:
                choices.append(item_id)
        if not choices:
            return {}, f"slot '{slot}': at least one option must stay selected"
        resolved[slot] = choices
    for slot in raw:
        if slot not in options:
            return {}, f"unknown slot '{slot}'"
    return resolved, ""


def count_combos(choices: Dict[str, List[Optional[str]]]) -> int:
    """How many combinations the choices produce — ARITHMETICALLY, never by
    enumerating. The all-empty combination is subtracted when it is reachable
    (i.e. every slot may stay empty); it dresses nothing and is skipped."""
    if not choices:
        return 0
    total = 1
    for opts in choices.values():
        total *= len(opts)
    if all(None in opts for opts in choices.values()):
        total -= 1
    return max(0, total)


def _iter_combos(choices: Dict[str, List[Optional[str]]],
                 coherent_only: bool = False,
                 ) -> Iterator[Dict[str, str]]:
    """Lazy enumeration: yields ``{slot: item_id}`` per combination, empty
    slots left out. The all-empty combination is skipped.

    ``coherent_only`` additionally drops combinations whose visible pieces
    share no outfit type (app/core/outfit_coherence.py) — a party shirt with
    work trousers is a render nobody wants. Still lazy: the filter sits in the
    generator, so a million-combination product is never materialised.
    """
    slots = list(choices)
    is_coherent = None
    if coherent_only:
        from app.core.outfit_coherence import is_coherent as _ic
        is_coherent = _ic
    for picks in itertools.product(*(choices[s] for s in slots)):
        pieces = {slot: pid for slot, pid in zip(slots, picks) if pid}
        if not pieces:
            continue
        if is_coherent is not None and not is_coherent(pieces):
            continue
        yield pieces


def _signature(pieces: Dict[str, str]) -> str:
    """Cache signature of a combination — identical to what
    ``model_refs.current_outfit_state`` produces for the worn state (colors
    and other meta are not part of it)."""
    from app.core.expression_regen import _equipped_signature
    return hashlib.md5(_equipped_signature(pieces, []).encode()).hexdigest()[:12]


def _combo_label(pieces: Dict[str, str],
                 names: Dict[str, str]) -> str:
    """Readable name of a combination for status and log — ``top: Shirt ·
    feet: Boots``; the empty state of a slot is simply absent."""
    if not pieces:
        return "(nothing)"
    return " · ".join(f"{slot}: {names.get(pid, pid)}"
                      for slot, pid in sorted(pieces.items()))


# ── Caches: what already exists ─────────────────────────────────────────

def _mesh_signatures(character_name: str) -> set:
    """Signatures that already HAVE a mesh — read once from the directory
    instead of stat-ing per combination (that is what makes a million-entry
    run affordable, and what makes the job restart-proof)."""
    from app.core.model3d import MODEL_EXTS
    from app.models.character import get_character_dir
    out = set()
    d = get_character_dir(character_name) / "model3d"
    if not d.exists():
        return out
    for p in d.iterdir():
        if p.is_file() and p.suffix.lower() in MODEL_EXTS:
            out.add(p.stem)
    return out


def _ref_signatures(character_name: str, kind: str = "tpose") -> set:
    """Signatures that already have a reference render of this kind."""
    from app.core.model_refs import _IMAGE_EXTS
    from app.models.character import get_character_dir
    out = set()
    d = get_character_dir(character_name) / "model_refs"
    if not d.exists():
        return out
    prefix = f"{kind}_"
    for p in d.iterdir():
        if p.is_file() and p.suffix.lower() in _IMAGE_EXTS \
                and p.stem.startswith(prefix):
            out.add(p.stem[len(prefix):])
    return out


# ── Time estimate ───────────────────────────────────────────────────────

def _query_tasks(sql: str, params: Iterable[Any] = ()) -> List[sqlite3.Row]:
    """Read-only peek into the queue DB. The queue has no public query API for
    "tasks of this type/agent", and this module needs two of those: the
    double-start guard and the duration history."""
    from app.core.task_queue import _get_db_path
    try:
        conn = sqlite3.connect(str(_get_db_path()))
        conn.row_factory = sqlite3.Row
        try:
            return conn.execute(sql, tuple(params)).fetchall()
        finally:
            conn.close()
    except Exception as e:
        logger.debug("outfit_batch task query failed: %s", e)
        return []


def estimate_seconds_per_combo() -> float:
    """Seconds one combination costs: the average of the last 10 finished mesh
    generations (that is the expensive half) plus a flat T-pose allowance. No
    history → a conservative fallback, so the dialog never shows "0 s"."""
    rows = _query_tasks(
        """SELECT duration_s FROM tasks
           WHERE task_type='model3d_generation' AND status='completed'
                 AND duration_s > 0
           ORDER BY completed_at DESC LIMIT 10""")
    values = [float(r["duration_s"]) for r in rows if r["duration_s"]]
    if not values:
        return FALLBACK_SECONDS_PER_COMBO
    return sum(values) / len(values) + TPOSE_SECONDS


def combo_stats(character_name: str,
                slots_filter: Optional[Dict[str, Any]] = None,
                force: bool = False,
                coherent_only: bool = True) -> Dict[str, Any]:
    """``{total, total_exact, missing, missing_exact, est_seconds, error}``.

    Without the coherence filter ``total`` is arithmetic and therefore instant
    at any size. WITH it there is nothing to multiply — whether a combination
    matches depends on its pieces — so the total has to be counted by
    enumeration, which is only affordable up to ``MAX_EXACT_COMBOS``. Above
    that the arithmetic (unfiltered) total is reported as an upper bound and
    ``total_exact`` is False, so the dialog says "up to" on the total too.

    ``missing`` needs one signature per combination and is exact under the
    same ceiling. With ``force`` everything is re-rendered, so missing ==
    total by definition.
    """
    options = combo_options(character_name)
    choices, error = _resolve_filter(options, slots_filter)
    if error:
        return {"total": 0, "total_exact": True, "missing": 0,
                "missing_exact": True, "est_seconds": 0.0, "error": error}
    gross = count_combos(choices)
    per = estimate_seconds_per_combo()
    total = gross
    total_exact = True
    if gross > MAX_EXACT_COMBOS:
        missing = gross
        exact = bool(force)
        total_exact = not coherent_only
    else:
        # UNIQUE signatures: combinations differing only in fully COVERED
        # pieces (boxers under trousers) share one signature since the
        # visibility normalisation in _equipped_signature — they are one
        # render, so they must be one unit of "missing" too.
        have = set() if force else _mesh_signatures(character_name)
        signatures = set()
        missing_sigs = set()
        for pieces in _iter_combos(choices, coherent_only):
            sig = _signature(pieces)
            signatures.add(sig)
            if sig not in have:
                missing_sigs.add(sig)
        if coherent_only:
            total = len(signatures)
        missing = len(missing_sigs)
        exact = True
    return {"total": total, "total_exact": total_exact, "missing": missing,
            "missing_exact": exact, "est_seconds": round(missing * per, 1),
            "error": ""}


# ── Status of the live process ──────────────────────────────────────────

def _idle_status() -> Dict[str, Any]:
    return {"running": False, "total": 0, "done": 0, "skipped": 0, "failed": 0,
            "current": None, "results": [], "started_at": "", "finished_at": ""}


def get_status(character_name: str) -> Dict[str, Any]:
    """Snapshot of this character's batch process (idle record when it never
    ran in THIS server session — the queue state and the cache counts are the
    restart-proof part, this is the live detail)."""
    with _lock:
        st = _status.get(character_name)
        if not st:
            return _idle_status()
        snapshot = dict(st)
        snapshot["current"] = dict(st["current"]) if st.get("current") else None
        snapshot["results"] = [dict(r) for r in st.get("results") or []]
        return snapshot


def _set_current(character_name: str, label: str, step: str = "") -> None:
    with _lock:
        st = _status.get(character_name)
        if st is not None:
            st["current"] = {"name": label, "step": step} if label else None


# ── Queue state ─────────────────────────────────────────────────────────

def queue_state(character_name: str) -> Dict[str, Any]:
    """``{state: pending|running|none, task_id}`` for this character's batch —
    read from the queue DB, so it is correct across restarts."""
    rows = _query_tasks(
        """SELECT task_id, status FROM tasks
           WHERE task_type=? AND agent_name=? AND status IN ('pending','running')
           ORDER BY CASE status WHEN 'running' THEN 0 ELSE 1 END LIMIT 1""",
        (TASK_TYPE, character_name))
    if not rows:
        return {"state": "none", "task_id": ""}
    return {"state": str(rows[0]["status"]), "task_id": str(rows[0]["task_id"])}


def stop(character_name: str) -> bool:
    """Cancels the pending/running batch task. The run stops BETWEEN two
    combinations — a GPU job already handed out runs to completion."""
    state = queue_state(character_name)
    if state["state"] == "none":
        return False
    from app.core.task_queue import get_task_queue
    ok = get_task_queue().cancel_task(state["task_id"])
    if ok:
        logger.info("Outfit combos %s: cancelled (%s)",
                    character_name, state["task_id"])
    return ok


# ── Run ─────────────────────────────────────────────────────────────────

def _render_one(character_name: str, pieces: Dict[str, str], signature: str,
                label: str, force: bool) -> Dict[str, Any]:
    """T-pose reference + mesh for one combination. Returns the result record;
    never raises — a broken combination must not end the batch."""
    from app.core.model3d import generate_for_current_outfit
    from app.core.model_refs import find_ref_image, generate_model_ref_images

    result = {"signature": signature, "name": label, "ok": False,
              "cached": False, "error": ""}
    try:
        _set_current(character_name, label, "ref")
        # Independent of the per-character auto toggles: those decide what an
        # outfit CHANGE renders, the batch always needs the mesh input.
        generate_model_ref_images(character_name, kinds=("tpose",), force=force,
                                  pieces=pieces, items=[], signature=signature)
        if not find_ref_image(character_name, "tpose", signature):
            result["error"] = "T-pose render failed"
            return result

        _set_current(character_name, label, "mesh")
        res = generate_for_current_outfit(character_name, force=force,
                                          signature=signature)
        if not res.get("ok"):
            result["error"] = str(res.get("error") or "mesh generation failed")
            return result
        result["ok"] = True
        result["cached"] = bool(res.get("cached"))
    except Exception as e:  # noqa: BLE001 — one bad combination must not kill the run
        logger.exception("Outfit combos %s: combination %s failed",
                         character_name, label)
        result["error"] = f"{type(e).__name__}: {e}"[:300]
    return result


def _handle_outfit_combos(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Queue handler: enumerate, skip what the caches already have, render the
    rest serially. Cancellation is checked BETWEEN combinations, so a stop
    never leaves a half-written cache entry."""
    from app.core.task_queue import get_task_queue

    character_name = str(payload.get("character") or "")
    force = bool(payload.get("force"))
    # Stored in the payload, so a run resumed after a restart filters exactly
    # as it was started. Absent (a task queued before CO3) = unfiltered, which
    # is what those runs were started as.
    coherent_only = bool(payload.get("coherent_only"))
    task_id = str(payload.get("_task_id") or "")
    options = combo_options(character_name)
    choices, error = _resolve_filter(options, payload.get("slots"))
    if error:
        raise ValueError(error)
    names = {p["item_id"]: p["name"]
             for pieces in options.values() for p in pieces}
    total = count_combos(choices)
    have = _mesh_signatures(character_name)

    tq = get_task_queue()
    with _lock:
        _status[character_name] = {
            "running": True, "total": total, "done": 0, "skipped": 0,
            "failed": 0, "current": None, "results": [],
            "started_at": utc_now_iso(), "finished_at": ""}

    done = skipped = failed = 0
    cancelled = False
    logger.info("Outfit combos %s: %d combination(s), force=%s, %d cached",
                character_name, total, force, len(have))
    try:
        for pieces in _iter_combos(choices, coherent_only):
            if task_id and tq.is_task_cancelled(task_id):
                cancelled = True
                logger.info("Outfit combos %s: cancelled after %d/%d",
                            character_name, done + skipped, total)
                break
            signature = _signature(pieces)
            if not force and signature in have:
                skipped += 1
                with _lock:
                    st = _status.get(character_name)
                    if st:
                        st["skipped"] = skipped
                continue
            label = _combo_label(pieces, names)
            result = _render_one(character_name, pieces, signature, label, force)
            done += 1
            if result["ok"]:
                have.add(signature)
            else:
                failed += 1
            with _lock:
                st = _status.get(character_name)
                if st:
                    st["done"] = done
                    st["failed"] = failed
                    # Only the tail is kept — a run of a million combinations
                    # must not grow an unbounded list in memory.
                    st["results"].append(result)
                    if len(st["results"]) > 50:
                        del st["results"][:-50]
        logger.info("Outfit combos %s: %d rendered (%d failed), %d cached, "
                    "%d total%s", character_name, done, failed, skipped, total,
                    " — cancelled" if cancelled else "")
    finally:
        _set_current(character_name, "")
        with _lock:
            st = _status.get(character_name)
            if st:
                st["running"] = False
                st["finished_at"] = utc_now_iso()
    return {"total": total, "rendered": done, "skipped": skipped,
            "failed": failed, "cancelled": cancelled}


def start(character_name: str, slots_filter: Optional[Dict[str, Any]] = None,
          force: bool = False, coherent_only: bool = True) -> Dict[str, Any]:
    """Submits the batch as ONE persistent queue task at low priority.

    Returns ``{"ok": True, "task_id": …, "total": …, "missing": …,
    "est_seconds": …}`` or ``{"ok": False, "error": …}`` —
    ``error="already running"`` is the double-start guard (at most one
    pending/running batch per character). ``coherent_only`` travels IN the
    payload, so a run resumed after a restart filters as it was started.
    """
    options = combo_options(character_name)
    if not options:
        return {"ok": False, "error": "no outfit pieces in this inventory"}
    choices, error = _resolve_filter(options, slots_filter)
    if error:
        return {"ok": False, "error": error}
    stats = combo_stats(character_name, slots_filter, force, coherent_only)
    if not stats["total"]:
        return {"ok": False, "error": "the filter yields no combination"}
    if queue_state(character_name)["state"] != "none":
        return {"ok": False, "error": "already running"}

    from app.core.task_queue import get_task_queue
    task_id = get_task_queue().submit(
        task_type=TASK_TYPE,
        payload={"character": character_name,
                 "slots": {slot: list(opts) for slot, opts in choices.items()},
                 "force": force, "coherent_only": coherent_only},
        queue_name="default", agent_name=character_name,
        priority=PRIORITY_LOW, max_retries=0)
    if not task_id:
        return {"ok": False, "error": "queue rejected the task"}
    logger.info("Outfit combos %s: queued %s — %d combination(s), force=%s, "
                "coherent_only=%s", character_name, task_id, stats["total"],
                force, coherent_only)
    return {"ok": True, "task_id": task_id, "total": stats["total"],
            "total_exact": stats["total_exact"], "missing": stats["missing"],
            "missing_exact": stats["missing_exact"],
            "est_seconds": stats["est_seconds"]}


def register_outfit_batch_handler() -> None:
    """Registers the queue handler. Called at server startup."""
    from app.core.task_queue import get_task_queue
    get_task_queue().register_handler(TASK_TYPE, _handle_outfit_combos)
    logger.info("Outfit-Combos-Handler registriert")
