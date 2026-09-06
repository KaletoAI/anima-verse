"""Classify HOW the props of the library are mounted (plan-furnish-v2.md § 2
B1, decision E3).

``mount`` (floor / wall / ceiling / surface) is what lets the furnish solver
hang a picture on a wall and put a candle on a table. A stock that grew before
the field existed says nothing at all, and typing four hundred answers by hand
is not an authoring task anybody does — so the LLM proposes them in one run
and the admin confirms or corrects each guess in the Props tab
(``mount_suggested``).

It lives beside ``props`` rather than inside it because it is a different kind
of work: ``props`` is the record store, this is one LLM job over it.

THE ANSWER REFERS TO SHORT REFS, never to prop ids. A slug like
``chair-3f9a12`` is exactly the kind of token a model rewrites on the way out,
and a rewritten id would silently classify the wrong prop; ``#1 … #n`` is
short enough to be copied and is mapped back here. Every batch numbers from
``#1``, because every batch is its own prompt.
"""

from typing import Any, Dict, List, Optional

from app.core import props
from app.core.llm_json import llm_json
from app.core.log import get_logger
from app.core.prompt_templates import render_task

logger = get_logger(__name__)

#: How many props one LLM call classifies. One line per prop, so the limit is
#: not the context but the answer: a model asked for two hundred entries at
#: once starts dropping them silently, and a dropped entry is indistinguishable
#: from "did not answer".
BATCH_MAX = 40

TASK = "prop_mount_classify"


def _batch_items(prop_ids: List[str],
                 library: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The prompt rows of ONE batch: ``{ref, name, category, w/d/h, tags}``
    with ``ref`` numbered from ``#1`` (plus the ``prop_id`` the answer is
    mapped back to, which never reaches the prompt)."""
    items: List[Dict[str, Any]] = []
    for pid in prop_ids:
        rec = library[pid]
        items.append({"ref": f"#{len(items) + 1}", "prop_id": pid,
                      "name": rec.get("name") or pid,
                      "category": rec.get("category") or "",
                      "width_m": rec.get("width_m"),
                      "depth_m": rec.get("depth_m"),
                      "height_m": rec.get("height_m"),
                      "tags": rec.get("tags") or []})
    return items


def validate_mounts(answer: Any, items: List[Dict[str, Any]]) -> Dict[str, str]:
    """``{prop_id: mount}`` of everything the answer said that this batch can
    use — the guard between the model and the sidecars.

    Three things are dropped, each without failing the run: a ref the batch
    never handed out (the model invented one, or answered for an earlier
    batch), a kind that is not one of :data:`props.MOUNT_KINDS`, and a second
    answer for a ref that was already answered (the first one stands). A
    dropped entry leaves its prop unclassified, which is exactly the state it
    was in — never a wrong mount written with confidence.
    """
    by_ref = {item["ref"]: item["prop_id"] for item in items}
    out: Dict[str, str] = {}
    rows = answer.get("mounts") if isinstance(answer, dict) else None
    if not isinstance(rows, list):
        rows = answer.get("_list") if isinstance(answer, dict) else None
    if not isinstance(rows, list):
        return out
    for row in rows:
        if not isinstance(row, dict):
            continue
        ref = str(row.get("ref") or "").strip()
        if not ref.startswith("#"):
            ref = f"#{ref}"
        pid = by_ref.get(ref)
        if not pid or pid in out:
            continue
        kind = str(row.get("mount") or "").strip().lower()
        if kind not in props.MOUNT_KINDS:
            logger.info("prop mount: %s answered unknown kind %r for %s",
                        TASK, kind, ref)
            continue
        out[pid] = kind
    return out


def classify_mounts(prop_ids: Optional[List[str]] = None) -> Dict[str, Any]:
    """Ask the LLM how the given props are mounted and STORE what comes back
    as a suggestion — ``{"classified": n, "mounts": {prop_id: mount},
    "unresolved": [prop_id, …]}``.

    ``prop_ids`` ``None`` = every prop that has no ``mount`` yet; a list
    re-classifies exactly those, whatever they say today (that is the "do it
    again for these" the admin has). The props are asked for in batches of at
    most :data:`BATCH_MAX`, each batch its own prompt with its own
    ``#1 … #n``.

    Synchronous: the caller is a button, not a job. An empty selection does
    nothing at all — no LLM call, no write — and answers with zeros, which is
    what the route turns into its 409.

    ``unresolved`` are the props of the selection the model did not answer
    for (or answered with an unusable ref or kind). They stay exactly as they
    were; nothing partial is written over them.

    EVERY BATCH STANDS ON ITS OWN. A batch is written the moment it is
    validated, and a batch whose call fails — two unparsable answers, a dead
    provider — is caught, logged and leaves its props in ``unresolved``; that
    is what the return contract already says about props nobody answered for.
    A four-hundred-prop library is ten calls, and losing nine good ones to the
    tenth would make the button unusable exactly where it is needed most.

    The ONE case that raises is "no batch got through at all": then there is
    no partial answer to report, and the caller must hear WHY instead of
    reading a successful zero. The first failure is re-raised as it was
    (``LlmJsonError`` for an unparsable answer); the route maps it to a 502
    with its message.
    """
    # ONE listing, which is also the one directory walk this job does:
    # everything the prompt needs (name, category, the three metres, tags) and
    # the ``mount`` the default selection is made by are on the lean record.
    library = {p["id"]: p for p in props.list_props()}
    # A prop the world no longer has is dropped silently: the caller's list may
    # be older than the library, and a stale id is not an error the admin can
    # act on.
    ids = [pid for pid in (prop_ids if prop_ids is not None
                           else [k for k, rec in library.items()
                                 if not rec.get(props.MOUNT_KEY)])
           if pid in library]
    mounts: Dict[str, str] = {}
    if not ids:
        return {"classified": 0, "mounts": {}, "unresolved": []}

    batches = 0
    done = 0
    first_error: Optional[BaseException] = None
    for start in range(0, len(ids), BATCH_MAX):
        batches += 1
        items = _batch_items(ids[start:start + BATCH_MAX], library)
        # The prompt gets the rows WITHOUT their prop ids: the answer must
        # refer to the refs, so the ids are never in front of the model.
        rows = [{k: v for k, v in item.items() if k != "prop_id"}
                for item in items]
        system, user = render_task(TASK, props=rows)
        try:
            answer = llm_json(TASK, system, user,
                              f"Prop mount classify ({len(items)} props)")
        except Exception as e:  # noqa: BLE001 — one batch must not cost the rest
            logger.warning("prop mount: batch %d of %d failed (%s: %s) — its "
                           "props stay unclassified", batches,
                           -(-len(ids) // BATCH_MAX), type(e).__name__, e)
            if first_error is None:
                first_error = e
            continue
        done += 1
        batch = validate_mounts(answer, items)
        # Written HERE, per batch: the value is a GUESS until the admin has
        # looked at it — that is the whole difference between this write and a
        # manual patch, which clears the flag.
        for pid, kind in batch.items():
            props.set_suggested_mount(pid, kind)
        mounts.update(batch)

    if first_error is not None and done == 0:
        raise first_error

    unresolved = [pid for pid in ids if pid not in mounts]
    logger.info("prop mount: %d of %d props classified, %d unresolved",
                len(mounts), len(ids), len(unresolved))
    return {"classified": len(mounts), "mounts": mounts,
            "unresolved": unresolved}
