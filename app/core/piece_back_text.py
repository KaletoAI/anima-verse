"""The back description of an outfit piece (plan
``docs/superpowers/plans/2026-11-12-unified-worn-pieces.md``, Task 11e,
Ruling V1 as amended by the user: "hinten ist optional").

An outfit piece's ``prompt_fragment`` is its FRONT description, owned by the
user and kept as written for the 2D images — it may name what only the front
shows (a neckline, front buttons, what an opening reveals) or the scene the
piece is meant for ("business setting"). Quoted unchanged into the back of
the piece's own garment chain (``garment_clothing``: the worn back's draft
and fit, the ghost back), such words turned the figure around: hub job
d21ef8c0 (2026-11-12, "Garment Kira worn back") showed the front with its
open neckline on both back attempts and the gates refused them ("back shows
the front opening").

``prompt_fragment_back`` (``FIELD``) is an OPTIONAL item field written only
by the user (the Items editor: "Description (back)") or by the one-time
migration below — never derived behind a render. Every BACK and SIDE render
that quotes the piece's text uses it (``back_text``); an empty field means
the front text, exactly as before. Front renders and every 2D image keep the
front text byte for byte.

The editor's "Suggest" button (``suggest``, route
``POST /inventory/items/suggest-back-text``) asks the LLM task ``TASK``
(template ``shared/templates/llm/tasks/piece_back_text.md``) for a proposal
and puts it into the field WITHOUT saving: the user edits and saves it.

ONE-TIME MIGRATION (``migrate_once``, user 2026-11-12: "du setzt die
Rückseite für alle"): every outfit piece with an empty back field gets the
same derivation; the template first answers whether the front text has any
front-only or scene words (``CHANGE: no`` / ``yes``). Only a piece that has
some gets a back text — every other piece keeps its empty field and with it
its keys (``garment_clothing.fsig_inputs`` names the back only when it is
set and differs from the front). Two scopes, two markers, like
``figure_migration.redefault_modes_once``: the WORLD's items once per world
(world_kv ``WORLD_FLAG``), the SHARED library once for all worlds (top-level
key ``SHARED_KEY`` of ``shared/items/items.json``, written with
``inventory._save_shared_items(meta=…)``). It runs in a background thread
after boot (``start_migration``) with queued LLM calls at background
priority — never blocking the start, never inside a GPU worker, also in a
frozen world (it is no simulation). A run that stops midway resumes at the
next boot: a piece whose field is filled now is skipped, a marker is set
only when every piece of its scope was answered; an LLM failure leaves that
piece empty, logs one WARNING and is retried at the next boot. One INFO line
per written piece, one summary line. Pieces of the test characters are
processed like every other piece: their back/side keys may change, and only
a Build the user starts re-renders them.
"""
from __future__ import annotations

import re
import threading
from typing import Any, Dict, List, Optional, Tuple

from app.core.log import get_logger

logger = get_logger("piece_back_text")

#: The item field: the piece's back description ("" / absent = the front text).
FIELD = "prompt_fragment_back"
#: The LLM task (``llm_tasks.TASK_TYPES``) and its template (``tasks/<TEMPLATE>.md``).
TASK = "piece_back_text"
TEMPLATE = "piece_back_text"
#: The answer is one short line — a cap against a model that rambles or loops.
MAX_TOKENS = 200
#: A back text may be a few words longer than the front (a rephrasing), never
#: a new description: beyond this it is refused as unusable.
MAX_EXTRA_WORDS = 3
#: The views that read the back text: the back and both sides.
BACK_VIEWS = ("back", "left", "right", "side")

#: world_kv flag of the world's items / top-level key of the shared library file.
WORLD_FLAG = "derived_piece_back_texts"
SHARED_KEY = "derived_piece_back_texts"
#: Seconds the boot thread waits before its first LLM call: the provider queues settle first.
START_DELAY_S = 30.0

_CHANGE_RE = re.compile(r"^\s*\**\s*CHANGE\s*\**\s*:\s*\**\s*(yes|no)\b", re.IGNORECASE | re.MULTILINE)
_BACK_RE = re.compile(r"^\s*\**\s*BACK\s*\**\s*:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)
_THINK_RE = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)

_warned: set = set()
_warned_lock = threading.Lock()


def normalise(text: Any) -> str:
    """Whitespace collapsed, no trailing full stop — the form
    ``garment_clothing.fragment`` gives the front text."""
    return " ".join(str(text or "").split()).rstrip(".").strip()


def back_field(item: Optional[Dict[str, Any]]) -> str:
    """The piece's own back text (``FIELD``, normalised); "" when unset."""
    return normalise((item or {}).get(FIELD))


def back_text(item: Optional[Dict[str, Any]]) -> str:
    """What a back or side render quotes for the piece: its back text when
    set, else its front text (``prompt_fragment``) — both normalised."""
    return back_field(item) or normalise((item or {}).get("prompt_fragment"))


def view_text(item: Optional[Dict[str, Any]], view: str) -> str:
    """The piece's text for ``view``: the front text for ``front``, the back
    text (``back_text``) for every view of ``BACK_VIEWS``. ValueError for
    another view."""
    if view == "front":
        return normalise((item or {}).get("prompt_fragment"))
    if view in BACK_VIEWS:
        return back_text(item)
    raise ValueError(f"no piece view {view!r}")


def distinct_back(item: Optional[Dict[str, Any]]) -> str:
    """The back text when the piece has one that differs from its front text
    — what the keys of its back renders add (``garment_clothing.fsig_inputs``);
    "" otherwise (no field, or a field equal to the front: the old keys)."""
    back = back_field(item)
    return back if back and back != normalise((item or {}).get("prompt_fragment")) else ""


# --- The derivation (Suggest and the migration) ------------------------------------


def parse_answer(answer: str, front: str) -> Optional[Tuple[bool, str]]:
    """``(changed, back text)`` of the template's answer: ``(False, "")`` for
    ``CHANGE: no`` (or a BACK equal to the front), ``(True, text)`` for
    ``CHANGE: yes`` with a usable ``BACK:`` line; None for an answer that is
    neither (no CHANGE line, yes without BACK, an empty or overlong BACK)."""
    text = _THINK_RE.sub("", answer or "")
    found = list(_CHANGE_RE.finditer(text))
    if not found:
        return None
    if found[-1].group(1).lower() == "no":
        return False, ""
    backs = list(_BACK_RE.finditer(text[found[-1].end():]))
    if not backs:
        return None
    back = normalise(backs[0].group(1).strip().strip("\"'`"))
    if not back:
        return None
    if back.lower() == normalise(front).lower():
        return False, ""
    if len(back.split()) > len(normalise(front).split()) + MAX_EXTRA_WORDS:
        return None
    return True, back


def derive(front: str, *, name: str = "", priority: Optional[int] = None,
           label: str = "") -> Tuple[bool, str]:
    """Ask the LLM (``TASK``) whether the front text ``front`` has front-only
    or scene words and, if so, for the back text: ``(changed, text)`` as
    ``parse_answer``. ``(False, "")`` for an empty front without a call.
    RuntimeError when the LLM fails, is not routed or answers unusably."""
    front = normalise(front)
    if not front:
        return False, ""
    from app.core.llm_router import llm_call
    from app.core.prompt_templates import render_task
    system, user = render_task(TEMPLATE, front_text=front, piece_name=normalise(name))
    response = llm_call(task=TASK, system_prompt=system, user_prompt=user, max_tokens=MAX_TOKENS,
                        priority=priority, label=label or "piece_back_text")
    parsed = parse_answer(str(getattr(response, "content", "") or ""), front)
    if parsed is None:
        raise RuntimeError("the LLM answer had no usable CHANGE / BACK line")
    return parsed


def suggest(front: str, *, name: str = "") -> Dict[str, Any]:
    """The editor's proposal for the back field — nothing is saved:
    ``{"text": back text or "", "changed": bool}`` (``changed`` False: the
    front text has nothing front-only, the field may stay empty).
    RuntimeError as ``derive``."""
    changed, text = derive(front, name=name, label="piece_back_text:suggest")
    return {"text": text, "changed": changed}


def _warn_once(key: str, message: str, *args: Any) -> None:
    with _warned_lock:
        if key in _warned:
            return
        _warned.add(key)
    logger.warning(message, *args)


# --- One-time migration (module docstring) -------------------------------------------


def _candidates(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Outfit pieces with a front text and an empty back field."""
    return [it for it in items if isinstance(it, dict) and it.get("category") == "outfit_piece"
            and it.get("id") and normalise(it.get("prompt_fragment")) and not back_field(it)]


def _write(item_id: str, front: str, text: str) -> bool:
    """Write ``text`` into the back field of ``item_id`` through the normal
    item saver (``inventory.update_item``) under the item write lock — only
    when the field is still empty and the front text is still ``front``
    (the user may have edited the piece meanwhile). True when written."""
    from app.models import inventory
    with inventory.item_write_lock():
        item = inventory.get_item(item_id) or {}
        if back_field(item) or normalise(item.get("prompt_fragment")) != front:
            logger.info("Back text of %s not written: the piece was edited meanwhile", item_id)
            return False
        return inventory.update_item(item_id, {FIELD: text}) is not None


def _run_scope(items: List[Dict[str, Any]], where: str, out: Dict[str, Any]) -> bool:
    """Derive the back text of every candidate of ``items``; True when every
    one was answered (written, same, or edited meanwhile)."""
    from app.core.llm_queue import Priority
    complete = True
    for item in _candidates(items):
        item_id = str(item["id"])
        front = normalise(item.get("prompt_fragment"))
        try:
            changed, text = derive(front, name=str(item.get("name") or ""), priority=Priority.LOW,
                                   label=f"piece_back_text:{item_id}")
        except Exception as e:  # noqa: BLE001 — one piece never stops the others
            complete = False
            out["failed"].append(item_id)
            _warn_once(f"migrate:{item_id}", "Back text of %s (%s) not derived — stays empty, retried at the "
                       "next start: %s", item_id, where, e)
            continue
        if not changed:
            out["same"].append(item_id)
            continue
        try:
            written = _write(item_id, front, text)
        except Exception as e:  # noqa: BLE001
            complete = False
            out["failed"].append(item_id)
            logger.warning("Back text of %s (%s) not saved — retried at the next start: %s", item_id, where, e)
            continue
        if written:
            out["written"][item_id] = text
            logger.info("Back text of %s (%s): %r -> %r", item_id, where, front, text)
    return complete


def migrate_once() -> Optional[Dict[str, Any]]:
    """The one-time migration (module docstring). None when both scopes are
    done, else ``{written: {item id: text}, same: [...], failed: [...],
    world: "done" | "already" | "incomplete", shared: ...}``. An item list or
    marker that cannot be read raises before any LLM call."""
    from app.core.timeutils import utc_now_iso
    from app.models import inventory
    from app.models.world import get_world_setting, set_world_setting
    world_done = bool(get_world_setting(WORLD_FLAG, strict=True))
    shared_done = bool(inventory.get_shared_items_meta(strict=True).get(SHARED_KEY))
    if world_done and shared_done:
        return None
    world_items = [] if world_done else inventory._load_items(strict=True)
    shared_items = [] if shared_done else inventory._load_shared_items(strict=True)
    out: Dict[str, Any] = {"written": {}, "same": [], "failed": [],
                           "world": "already" if world_done else "done",
                           "shared": "already" if shared_done else "done"}
    if not world_done:
        if _run_scope(world_items, "world", out):
            set_world_setting(WORLD_FLAG, utc_now_iso())
        else:
            out["world"] = "incomplete"
    if not shared_done:
        if _run_scope(shared_items, "shared", out):
            try:
                with inventory.item_write_lock():
                    inventory._save_shared_items(inventory._load_shared_items(strict=True),
                                                 meta={SHARED_KEY: utc_now_iso()})
            except Exception as e:  # noqa: BLE001 — the next start asks the same-answer pieces again
                out["shared"] = "incomplete"
                logger.warning("Back texts: the shared library marker was not saved: %s", e)
        else:
            out["shared"] = "incomplete"
    logger.info("Back texts derived (world %s, shared %s): %d written, %d need none, %d failed",
                out["world"], out["shared"], len(out["written"]), len(out["same"]), len(out["failed"]))
    return out


def _migrate_in_background(delay: float) -> None:
    import time
    if delay > 0:
        time.sleep(delay)
    try:
        migrate_once()
    except Exception as e:  # noqa: BLE001 — retried at the next start
        logger.warning("Back text migration failed (retried at the next start): %s", e)


def start_migration(delay: float = START_DELAY_S) -> Optional[threading.Thread]:
    """Start ``migrate_once`` in a daemon thread after ``delay`` seconds
    (the boot never waits for it). None when both markers are set already."""
    from app.models import inventory
    from app.models.world import get_world_setting
    if get_world_setting(WORLD_FLAG) and inventory.get_shared_items_meta().get(SHARED_KEY):
        return None
    thread = threading.Thread(target=_migrate_in_background, args=(delay,), name="piece-back-texts",
                              daemon=True)
    thread.start()
    return thread
