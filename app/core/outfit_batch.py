"""Batch job: pre-warm the 3D chain for ALL saved outfits of one character.

Normally a mesh only ever comes into being for the combination the character
is CURRENTLY wearing — the outfit-change trigger renders the T-pose reference
and the auto-mesh hook turns it into a model. That means a 3D client sees a
model pop in the first time each outfit is worn.

This job fills the caches up front, without dressing the character: the cache
signature of a saved outfit (``_equipped_signature``) is computable from its
pieces alone, and both ``model_refs.generate_model_ref_images`` and
``model3d.generate_for_current_outfit`` accept that signature as an override.
Per outfit, serially: T-pose reference (if missing) → mesh (if missing).

Deliberate scope (plan-outfit-batch.md):

* Items (sword, glasses, …) are IGNORED — an outfit renders with its clothing
  pieces only (``items=[]``). Combinations that include a carried item are
  still produced live by the existing auto-trigger when they are worn.
* The T-pose render runs regardless of the character's per-image auto toggles:
  those govern the automatic outfit-change render, while the batch always
  needs the mesh input.
* No DB state. The caches make the job idempotent — a restart mid-run just
  means starting it again, everything finished is skipped. Progress lives in
  this module plus one tracked queue task.
"""

import hashlib
import threading
from typing import Any, Dict, List, Optional

from app.core.log import get_logger
from app.core.timeutils import utc_now_iso

logger = get_logger(__name__)

_lock = threading.Lock()
# character -> progress record; survives the run so the dialog can still show
# the result of the last batch until the next one starts.
_status: Dict[str, Dict[str, Any]] = {}


# ── Plan ────────────────────────────────────────────────────────────────

def _pieces_by_slot(outfit: Dict[str, Any]) -> Dict[str, str]:
    """Piece-ID list of a saved outfit → slot->item_id map, the same mapping
    the wardrobe does when the outfit is actually put on (first declared slot
    of each piece wins)."""
    from app.models.inventory import get_item
    out: Dict[str, str] = {}
    for pid in (outfit.get("pieces") or []):
        slots = (((get_item(pid) or {}).get("outfit_piece") or {}).get("slots") or [])
        if slots:
            out[slots[0]] = pid
    return out


def _signature(pieces: Dict[str, str]) -> str:
    """Cache signature of a combination — identical to what
    ``model_refs.current_outfit_state`` produces for the worn state (colors
    and other meta are not part of it)."""
    from app.core.expression_regen import _equipped_signature
    return hashlib.md5(_equipped_signature(pieces, []).encode()).hexdigest()[:12]


def _plan_rows(character_name: str) -> List[Dict[str, Any]]:
    """Full plan including the piece map each row would render with."""
    from app.core.model3d import find_model3d
    from app.core.model_refs import find_ref_image
    from app.models.character import get_character_outfits

    rows: List[Dict[str, Any]] = []
    first_with_sig: Dict[str, str] = {}
    for outfit in (get_character_outfits(character_name) or []):
        outfit_id = str(outfit.get("id") or "")
        name = str(outfit.get("name") or "").strip() or outfit_id[:8]
        pieces = _pieces_by_slot(outfit)
        if not pieces:
            # Pure text outfits carry nothing the renderer could dress — they
            # would all collapse onto the same (empty) signature.
            rows.append({"outfit_id": outfit_id, "name": name, "pieces": {},
                         "signature": None, "has_ref": False, "has_model": False,
                         "skip_reason": "no pieces", "duplicate_of": None})
            continue
        sig = _signature(pieces)
        duplicate_of = first_with_sig.get(sig)
        if duplicate_of is None:
            first_with_sig[sig] = outfit_id
        rows.append({
            "outfit_id": outfit_id,
            "name": name,
            "pieces": pieces,
            "signature": sig,
            "has_ref": bool(find_ref_image(character_name, "tpose", sig)),
            "has_model": bool(find_model3d(character_name, sig)),
            "skip_reason": "",
            # Two outfits with the same pieces share one cache entry — the
            # second is reported, not rendered.
            "duplicate_of": duplicate_of,
        })
    return rows


def plan(character_name: str) -> List[Dict[str, Any]]:
    """Per saved outfit: its combination signature and what already exists —
    ``{outfit_id, name, signature, has_ref, has_model, skip_reason,
    duplicate_of}``. Read-only, cheap enough to poll."""
    return [{k: v for k, v in row.items() if k != "pieces"}
            for row in _plan_rows(character_name)]


# ── Status ──────────────────────────────────────────────────────────────

def _idle_status() -> Dict[str, Any]:
    return {"running": False, "stop_requested": False, "total": 0, "done": 0,
            "current": None, "results": [], "started_at": "", "finished_at": ""}


def get_status(character_name: str) -> Dict[str, Any]:
    """Snapshot of this character's batch (idle record when it never ran)."""
    with _lock:
        st = _status.get(character_name)
        if not st:
            return _idle_status()
        snapshot = dict(st)
        snapshot["current"] = dict(st["current"]) if st.get("current") else None
        snapshot["results"] = [dict(r) for r in st.get("results") or []]
        return snapshot


def _set_current(character_name: str, row: Optional[Dict[str, Any]],
                 step: str = "") -> None:
    with _lock:
        st = _status.get(character_name)
        if not st:
            return
        st["current"] = (None if row is None else
                         {"outfit_id": row["outfit_id"], "name": row["name"],
                          "step": step})


def _stop_requested(character_name: str) -> bool:
    with _lock:
        return bool((_status.get(character_name) or {}).get("stop_requested"))


def stop(character_name: str) -> bool:
    """Asks the running batch to stop AFTER the current outfit (the GPU jobs
    themselves run to completion — there is no kill). False when nothing is
    running."""
    with _lock:
        st = _status.get(character_name)
        if not st or not st.get("running"):
            return False
        st["stop_requested"] = True
    logger.info("Outfit batch %s: stop requested", character_name)
    return True


# ── Run ─────────────────────────────────────────────────────────────────

def _render_one(character_name: str, row: Dict[str, Any],
                force: bool) -> Dict[str, Any]:
    """T-pose reference + mesh for one combination. Returns the result record;
    never raises — a broken outfit must not end the batch."""
    from app.core.model3d import generate_for_current_outfit
    from app.core.model_refs import find_ref_image, generate_model_ref_images

    sig = row["signature"]
    result = {"outfit_id": row["outfit_id"], "name": row["name"],
              "ok": False, "cached": False, "error": ""}
    try:
        _set_current(character_name, row, "ref")
        # Independent of the per-character auto toggles: those decide what an
        # outfit CHANGE renders, the batch always needs the mesh input.
        generate_model_ref_images(character_name, kinds=("tpose",), force=force,
                                  pieces=row["pieces"], items=[], signature=sig)
        if not find_ref_image(character_name, "tpose", sig):
            result["error"] = "T-pose render failed"
            return result

        _set_current(character_name, row, "mesh")
        res = generate_for_current_outfit(character_name, force=force,
                                          signature=sig)
        if not res.get("ok"):
            result["error"] = str(res.get("error") or "mesh generation failed")
            return result
        result["ok"] = True
        result["cached"] = bool(res.get("cached"))
    except Exception as e:  # noqa: BLE001 — one bad outfit must not kill the run
        logger.exception("Outfit batch %s: outfit %s failed",
                         character_name, row["name"])
        result["error"] = f"{type(e).__name__}: {e}"[:300]
    return result


def _run(character_name: str, rows: List[Dict[str, Any]], force: bool) -> None:
    from app.core.task_queue import get_task_queue

    tq = None
    task_id = ""
    try:
        tq = get_task_queue()
        task_id = tq.track_start("outfit_batch", f"Outfits: {character_name}",
                                 agent_name=character_name)
    except Exception:
        tq, task_id = None, ""

    failed = 0
    done = 0
    try:
        for idx, row in enumerate(rows, 1):
            if _stop_requested(character_name):
                logger.info("Outfit batch %s: stopped after %d/%d outfits",
                            character_name, done, len(rows))
                break
            if tq and task_id:
                try:
                    tq.track_update_label(
                        task_id,
                        f"Outfits: {character_name} — {idx}/{len(rows)} {row['name']}")
                except Exception:
                    pass
            result = _render_one(character_name, row, force)
            done += 1
            if not result["ok"]:
                failed += 1
            with _lock:
                st = _status.get(character_name)
                if st:
                    st["results"].append(result)
                    st["done"] = done
        logger.info("Outfit batch %s: %d outfit(s) processed, %d failed",
                    character_name, done, failed)
    finally:
        _set_current(character_name, None)
        with _lock:
            st = _status.get(character_name)
            if st:
                st["running"] = False
                st["finished_at"] = utc_now_iso()
        if tq and task_id:
            try:
                tq.track_finish(
                    task_id,
                    error=(f"{failed} of {done} outfit(s) failed" if failed else ""))
            except Exception:
                pass


def start(character_name: str, outfit_ids: List[str],
          force: bool = False) -> Dict[str, Any]:
    """Starts the batch for the selected outfits in a background thread.

    Outfits without usable pieces are dropped, and a signature is rendered
    only once even when several selected outfits share it. Returns
    ``{"ok": True, "count": n}`` or ``{"ok": False, "error": …}`` —
    ``error="already running"`` is the double-start guard.
    """
    selected = {str(i) for i in (outfit_ids or [])}
    rows: List[Dict[str, Any]] = []
    seen: set = set()
    for row in _plan_rows(character_name):
        if row["outfit_id"] not in selected or row["skip_reason"]:
            continue
        # Dedupe over the SELECTION, not over the whole plan: picking only the
        # second of two identical outfits must still render it.
        if row["signature"] in seen:
            continue
        seen.add(row["signature"])
        rows.append(row)
    if not rows:
        return {"ok": False, "error": "no renderable outfits selected"}

    with _lock:
        if (_status.get(character_name) or {}).get("running"):
            return {"ok": False, "error": "already running"}
        _status[character_name] = {
            "running": True, "stop_requested": False, "total": len(rows),
            "done": 0, "current": None, "results": [],
            "started_at": utc_now_iso(), "finished_at": ""}

    logger.info("Outfit batch %s: starting %d outfit(s), force=%s",
                character_name, len(rows), force)
    threading.Thread(target=_run, args=[character_name, rows, force],
                     daemon=True, name=f"outfit-batch-{character_name}").start()
    return {"ok": True, "count": len(rows)}
