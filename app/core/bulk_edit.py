"""One request, many edits — the shared half of the map editor's batch save.

The map editor keeps a LOCAL DRAFT and writes it in one go (plan
``plan-map-save-batch.md``): painting used to PUT every brush stroke, and each
of those writes settled water, re-rastered the relief, moved a signature and
made every client refetch. A world drawn in twenty strokes paid that twenty
times for one result.

What the three object kinds (painted terrain areas, height areas, world props)
share is exactly this module: how a batch is SPLIT into what may be written and
what must be refused, before anything is written at all. Everything else —
which sanitizer runs, which caches a write drops, what a cap allows — stays in
the model that owns the objects, because none of it is the same twice.

TWO REFUSALS, AND THEY ARE NOT ERRORS. A batch answers 200 even when parts of
it were refused: the request as a whole succeeded, and the client keeps exactly
the refused objects in its buffer.

* ``REASON_CHANGED`` — the object carries the ``updated_at`` its editor loaded
  and the stored one is different: somebody else saved it in the meantime.
  Optimistic concurrency, per object, no lock across sessions (§ 5 of the plan).
  An upsert WITHOUT an ``updated_at`` is not checked — that is a deliberate
  overwrite, the way the singular PUT has always behaved.
* ``REASON_GONE`` — the object is not stored at all any more. The singular PUT
  answers 404 here for a reason worth keeping: every store is an upsert, so a
  stale write would otherwise raise a deleted area from the dead under its old
  id.

A DELETE OF SOMETHING ALREADY GONE IS A SUCCESS, not a refusal: the goal state
is what the client asked for, and reporting it as an error would leave a buffer
entry nothing can ever clear.

IDS STAY THE SERVER'S. A new object travels with a client-side ``temp_id`` and
NO ``id``; the sanitizer mints the real one exactly as the POST route does, and
the answer names both so the editor can swap its placeholder.
"""

from typing import Any, Callable, Dict, List, Mapping, Tuple

#: The stored version differs from the one the client loaded.
REASON_CHANGED = "changed on the server"
#: The object is no longer stored — an upsert must not resurrect it.
REASON_GONE = "deleted on the server"


class GoneError(Exception):
    """A write that must REPLACE an existing object found none stored.

    The SINGULAR half of :data:`REASON_GONE`, so that both halves of the same
    rule live in one module: a batch reports the refusal per object, a singular
    PUT raises this and its route answers 404. Every store here is an upsert,
    so without the rule a stale PUT arriving after a DELETE would raise the
    object from the dead under its old id.

    The models raise it from INSIDE the write statement (``must_exist=True`` →
    a plain ``UPDATE`` whose ``rowcount`` is 0), never from a lookup before it:
    a check-then-write leaves exactly the window a DELETE fits through, and
    since those routes moved into the threadpool (2026-08-24) two of them
    really do run at once.

    ``str(exc)`` is the 404 detail — hence the object's name, not an id.
    """

    def __init__(self, what: str = "object") -> None:
        super().__init__(f"{what} not found")
        self.what = what


def plan_batch(upserts: Any, deletes: Any, stamps: Mapping[str, str],
               sanitize: Callable[[Dict[str, Any]], Dict[str, Any]],
               ) -> Tuple[List[Dict[str, Any]], List[str],
                          List[Dict[str, Any]]]:
    """Split one bulk body into ``(prepared, delete_ids, rejected)``.

    Nothing here touches the database — that is the point: the caller opens ONE
    transaction afterwards and writes what came back, so a body that is half
    junk cannot leave a half-written world behind.

    ``stamps`` is ``{id: updated_at}`` of everything currently stored (the
    model's own ``*_stamps()`` reader). ``sanitize`` is the model's existing
    single-object sanitizer, called verbatim — a batch must not be a second,
    laxer way into the same table.

    ``prepared`` entries are ``{"temp_id", "obj", "is_new"}``: ``is_new`` says
    the object had no id of its own, which is what a cap (world props) has to
    count and what an editor swaps its placeholder for.
    """
    prepared: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    for raw in (upserts if isinstance(upserts, list) else []):
        if not isinstance(raw, dict):
            rejected.append({"op": "upsert", "id": "", "temp_id": "",
                             "reason": "entry must be an object"})
            continue
        temp_id = str(raw.get("temp_id") or "").strip()
        obj_id = str(raw.get("id") or "").strip()
        ref = {"op": "upsert", "id": obj_id, "temp_id": temp_id}
        if obj_id:
            if obj_id not in stamps:
                rejected.append({**ref, "reason": REASON_GONE})
                continue
            loaded = str(raw.get("updated_at") or "")
            if loaded and loaded != stamps[obj_id]:
                rejected.append({**ref, "reason": REASON_CHANGED})
                continue
        # The two transport keys never reach a sanitizer: they say WHICH object
        # this is and WHEN it was read, not what it looks like.
        body = {k: v for k, v in raw.items()
                if k not in ("temp_id", "updated_at")}
        if not obj_id:
            body.pop("id", None)
        try:
            obj = sanitize(body)
        except ValueError as exc:
            rejected.append({**ref, "reason": str(exc)})
            continue
        prepared.append({"temp_id": temp_id, "obj": obj,
                         "is_new": not obj_id})

    delete_ids: List[str] = []
    for raw in (deletes if isinstance(deletes, list) else []):
        if isinstance(raw, str):
            raw = {"id": raw}
        if not isinstance(raw, dict):
            rejected.append({"op": "delete", "id": "", "temp_id": "",
                             "reason": "entry must be an object"})
            continue
        obj_id = str(raw.get("id") or "").strip()
        ref = {"op": "delete", "id": obj_id, "temp_id": ""}
        if not obj_id:
            rejected.append({**ref, "reason": "delete needs an id"})
            continue
        if obj_id in stamps:
            loaded = str(raw.get("updated_at") or "")
            if loaded and loaded != stamps[obj_id]:
                rejected.append({**ref, "reason": REASON_CHANGED})
                continue
        # …and an id that is not stored any more falls through on purpose: the
        # world already looks the way the client asked for.
        delete_ids.append(obj_id)
    return prepared, delete_ids, rejected
