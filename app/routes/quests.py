"""Admin routes for the quest system (stage 1): templates, runs and the type catalog.

A thin HTTP adapter over `app.models.quests` (storage), `app.core.quest_catalog` (types),
`app.core.quest_engine` (validation, start, cancel), `app.core.quest_effects` (retry) and
`app.core.quest_authoring` (background LLM draft generation via `POST /quests/generate` and
`GET /quests/generate/jobs`); it does auth, parsing and the HTTP mapping only.
Admin-only for reads AND writes (templates carry GM notes): `"/quests"` is on the gate's `_ADMIN_PREFIXES`
and the router carries `Depends(require_admin)` as the second layer. The player's quest book is
`GET /play/quests`, never this router.

Errors answer `{"detail": ...}`; a refusal with issues carries them unchanged as
`{"detail": {"code", "issues": [{"path", "code", "message"}]}}`. Template edits follow the revision
convention: `PUT` needs `base_revision` (428 `revision_required`, 409 `stale`).

Every error detail is an object with a `code` (`bad_json`, `bad_request`, `busy`, `not_found`, `revision_required`,
`stale`, `invalid`, `has_open_runs`, `refused`, `too_large`) and, except for the issue lists, a `message`.

The ready rule of `PUT`: the RESULTING template is checked — stored fields merged with the body — and when its
state is `ready` it must have no issues, else 422 `invalid` and nothing is written. That holds even when the body
does not name `state`, so a ready template that became invalid without an edit (a package whose type it uses was
unloaded) answers 422 to every plain edit. The way out is to send `"state": "draft"` in the same `PUT` as the fix;
set it `ready` again once its issues are gone.
"""
import asyncio
import json
import sqlite3
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Request

from app.core import quest_authoring, quest_catalog, quest_effects, quest_engine
from app.core.auth_dependency import require_admin
from app.models import quests

router = APIRouter(prefix="/quests", tags=["quests"], dependencies=[Depends(require_admin)])

#: The fields `POST /quests/templates` accepts (`create_template`'s content keywords).
_CREATE_KEYS = quests.TEMPLATE_CONTENT_KEYS
#: How many ended runs `GET /quests/runs` lists after the open ones.
_ENDED_RUNS_LIMIT = 50
#: The largest /quests request body (a template is copied into every run's snapshot; 256 KiB is far above any
#: hand-written quest).
_MAX_BODY_BYTES = 256 * 1024
#: What the store raises for a value it cannot write — a 400, never a 500 (e.g. a JSON value nested deeper than
#: SQLite's `json_valid` accepts fails the table's CHECK as an IntegrityError).
_STORE_REFUSALS = (TypeError, ValueError, OverflowError, sqlite3.Error)


def _not_found(what: str, ident: str) -> HTTPException:
    return HTTPException(404, {"code": "not_found", "message": f"{what} '{ident}' does not exist"})


def _bad(message: str) -> HTTPException:
    return HTTPException(400, {"code": "bad_request", "message": message})


async def _json(request: Request) -> Any:
    """The parsed request body; a malformed, empty or too deeply nested one is 400 `bad_json`, never a 500, and
    one larger than `_MAX_BODY_BYTES` is 413 `too_large`."""
    raw = await request.body()
    if len(raw) > _MAX_BODY_BYTES:
        raise HTTPException(413, {"code": "too_large",
                                  "message": f"the body is larger than {_MAX_BODY_BYTES // 1024} KiB"})
    try:
        return json.loads(raw)
    except (ValueError, RecursionError):
        raise HTTPException(400, {"code": "bad_json", "message": "the body is not valid JSON"})


def _body_dict(body: Any) -> Dict[str, Any]:
    if not isinstance(body, dict):
        raise _bad("body must be a JSON object")
    return body


def _with_issues(template: Dict[str, Any]) -> Dict[str, Any]:
    return {**template, "issues": quest_engine.validate_template(template)}


def _label(canonical: str, lang: str) -> str:
    """The finished display label of a canonical GAME stamp; "" when unset or unreadable."""
    if not canonical:
        return ""
    from app.core.game_time import GameTime
    try:
        return GameTime.parse(canonical).display_label(lang)
    except ValueError:
        return ""


def _run_row(run: Dict[str, Any], lang: str) -> Dict[str, Any]:
    snapshot = run.get("template_snapshot") or {}
    steps = snapshot.get("steps") if isinstance(snapshot.get("steps"), list) else []
    step_log = [{**entry, "game_label": _label(str(entry.get("game_ts") or ""), lang)}
                for entry in run.get("step_log") or [] if isinstance(entry, dict)]
    run_id = str(run.get("id") or "")
    objects = [
        {"kind": o.get("kind"), "label": o.get("label") or "", "permanent": bool(o.get("permanent")),
         "status": o.get("status")}
        for o in quests.list_objects(run_id)
        if o.get("kind") != "marker"
    ]
    payouts = [
        {"position": p.get("position"), "state": p.get("state"), "issues": p.get("issues") or []}
        for p in quests.list_payouts(states=(), run_id=run_id)
    ]
    if run.get("state") == "open":
        judgements = [
            {
                "mind": j.get("mind") or "",
                "avatar": j.get("avatar") or "",
                "state": j.get("state") or "",
                "reason": j.get("reason") or "",
                "judged_at": j.get("judged_at") or None,
            }
            for j in quests.list_judgements(run_id, step=int(run.get("current_step") or 0))
        ]
    else:
        judgements = []
    return {
        "id": run.get("id"),
        "title": quest_engine.render_text(str(snapshot.get("title") or ""), run),
        "state": run.get("state"),
        "current_step": run.get("current_step"),
        "step_count": len(steps),
        "step_log": step_log,
        "bindings": run.get("bindings") or {},
        "binding_labels": run.get("binding_labels") or {},
        "issues": run.get("issues") or [],
        "started_game_label": _label(run.get("started_game_ts") or "", lang),
        "expires_label": _label(run.get("expires_at") or "", lang),
        "objects": objects,
        "payouts": payouts,
        "judgements": judgements,
    }


# --- Catalog --------------------------------------------------------------------------------------

@router.get("/catalog")
def get_catalog() -> Dict[str, Any]:
    """The registered quest types (public descriptors) plus the role kinds."""
    return {**quest_catalog.catalog_payload(), "role_kinds": list(quest_catalog.ROLE_KINDS)}


# --- Templates ------------------------------------------------------------------------------------

@router.get("/templates")
def list_templates_route() -> Dict[str, List[Dict[str, Any]]]:
    """Every template as a list row, newest first, with its count of not yet ended runs."""
    rows = []
    for t in quests.list_templates():
        rows.append({
            "id": t["id"], "title": t.get("title") or "", "state": t.get("state"), "origin": t.get("origin"),
            "revision": t.get("revision"), "updated_at": t.get("updated_at"),
            "open_runs": quests.count_runs(quests.RUN_OPEN_STATES, template_id=t["id"]),
        })
    return {"templates": rows}


@router.get("/templates/{template_id}")
def get_template_route(template_id: str) -> Dict[str, Any]:
    """The full template (GM notes included) plus its authoring issues."""
    template = quests.get_template(template_id)
    if template is None:
        raise _not_found("Quest template", template_id)
    return _with_issues(template)


@router.post("/templates")
async def create_template_route(request: Request):
    """Create a template; it always starts as a `draft` of origin `admin`."""
    body = await _json(request)
    return await asyncio.to_thread(_create_template_sync, body)


def _create_template_sync(body: Any) -> Dict[str, Any]:
    body = _body_dict(body)
    unknown = sorted(set(body) - set(_CREATE_KEYS))
    if unknown:
        raise _bad(f"not a quest template field: {', '.join(unknown)}")
    if not isinstance(body.get("title"), str) or not body["title"].strip():
        raise _bad("title is required")
    msg = quest_engine.check_template_fields(body)
    if msg:
        raise _bad(msg)
    try:
        template = quests.create_template(**body)
    except _STORE_REFUSALS as e:
        raise _bad(str(e))
    return _with_issues(template)


@router.put("/templates/{template_id}")
async def update_template_route(template_id: str, request: Request):
    """Edit the editable keys of a template against `base_revision`. A template whose resulting state is
    `ready` must have no issues (422 `invalid`)."""
    body = await _json(request)
    return await asyncio.to_thread(_update_template_sync, template_id, body)


def _update_template_sync(template_id: str, body: Any) -> Dict[str, Any]:
    body = dict(_body_dict(body))
    if "base_revision" not in body:
        raise HTTPException(428, {"code": "revision_required", "message":
                                  "base_revision missing — load the template first (field revision)"})
    base = body.pop("base_revision")
    if isinstance(base, bool) or not isinstance(base, int):
        raise _bad("base_revision must be an integer")
    unknown = sorted(set(body) - set(quests.EDITABLE_TEMPLATE_KEYS))
    if unknown:
        raise _bad(f"not editable on a quest template: {', '.join(unknown)}")
    if "state" in body and body["state"] not in ("draft", "ready"):
        raise _bad("state is draft or ready")
    msg = quest_engine.check_template_fields(body)
    if msg:
        raise _bad(msg)
    current = quests.get_template(template_id)
    if current is None:
        raise _not_found("Quest template", template_id)
    if int(current.get("revision") or 0) != base:
        raise HTTPException(409, {"code": "stale", "current": current.get("revision"),
                                  "message": "The template changed since it was loaded"})
    merged = {**current, **body}
    if merged.get("state") == "ready":
        issues = quest_engine.validate_template(merged)
        if issues:
            raise HTTPException(422, {"code": "invalid", "issues": issues})
    try:
        updated = quests.update_template(template_id, body, base_revision=base)
    except quests.StaleRevision as e:
        raise HTTPException(409, {"code": "stale", "current": e.current,
                                  "message": "The template changed since it was loaded"})
    except KeyError:
        raise _not_found("Quest template", template_id)
    except _STORE_REFUSALS as e:
        raise _bad(str(e))
    return _with_issues(updated)


@router.delete("/templates/{template_id}")
async def delete_template_route(template_id: str):
    """Delete a template; refused (409 `has_open_runs`) while one of its runs has not ended."""
    return await asyncio.to_thread(_delete_template_sync, template_id)


def _delete_template_sync(template_id: str) -> Dict[str, bool]:
    if quests.get_template(template_id) is None:
        raise _not_found("Quest template", template_id)
    if quests.count_runs(quests.RUN_OPEN_STATES, template_id=template_id) > 0:
        raise HTTPException(409, {"code": "has_open_runs",
                                  "message": "End the open runs of this template before deleting it"})
    if not quests.delete_template(template_id):
        raise _not_found("Quest template", template_id)
    return {"ok": True}


@router.post("/templates/{template_id}/start")
async def start_template_route(template_id: str, request: Request,
                               user: Dict[str, Any] = Depends(require_admin)):
    """Start a run of a `ready` template with `{"bindings": {role: binding}}`."""
    body = await _json(request)
    return await asyncio.to_thread(_start_sync, template_id, body, str(user.get("username") or ""))


def _start_sync(template_id: str, body: Any, started_by: str) -> Dict[str, Any]:
    bindings = _body_dict(body).get("bindings", {})
    if not isinstance(bindings, dict):
        raise _bad("bindings must be an object")
    if quests.get_template(template_id) is None:
        raise _not_found("Quest template", template_id)
    try:
        return quest_engine.start_run(template_id, bindings, started_by=started_by)
    except quest_engine.QuestRefused as e:
        raise HTTPException(422, {"code": "refused", "issues": e.issues})


# --- Runs -----------------------------------------------------------------------------------------

@router.get("/runs")
def list_runs_route(state: str = "", lang: str = "en") -> Dict[str, List[Dict[str, Any]]]:
    """Runs as list rows: every not yet ended run first, then the newest ended ones (at most 50).
    `state` narrows the list to that one state."""
    all_states = quests.RUN_OPEN_STATES + quests.RUN_ENDED_STATES
    if state and state not in all_states:
        raise _bad(f"state is one of {', '.join(all_states)}")
    if state:
        limit = 0 if state in quests.RUN_OPEN_STATES else _ENDED_RUNS_LIMIT
        runs = quests.list_runs(states=(state,), limit=limit)
    else:
        runs = (quests.list_runs(states=quests.RUN_OPEN_STATES)
                + quests.list_runs(states=quests.RUN_ENDED_STATES, limit=_ENDED_RUNS_LIMIT))
    return {"runs": [_run_row(r, lang) for r in runs]}


@router.post("/runs/{run_id}/cancel")
async def cancel_run_route(run_id: str):
    """End a not yet ended run as `cancelled`; `ok` is False when it had ended or is unknown."""
    return {"ok": await asyncio.to_thread(quest_engine.cancel_run, run_id)}


@router.post("/runs/{run_id}/retry")
async def retry_run_route(run_id: str):
    """Re-arms every failed payout of a not-ended (or done) run and clears a preparing run's issues."""
    return {"ok": await asyncio.to_thread(quest_effects.retry, run_id)}


# --- Authoring ------------------------------------------------------------------------------------

@router.post("/generate", status_code=202)
async def generate_quest_route(request: Request) -> Dict[str, str]:
    """Enqueue a background LLM quest-authoring job (`quest_generate`)."""
    body = _body_dict(await _json(request))
    brief = body.get("brief")
    if not isinstance(brief, str):
        raise _bad("brief must be text")
    giver = body.get("giver")
    if giver is not None and not isinstance(giver, str):
        raise _bad("giver must be text")
    try:
        task_id = await asyncio.to_thread(quest_authoring.submit, brief, giver)
    except ValueError as e:
        raise _bad(str(e))
    except quest_authoring.GenerateBusy:
        raise HTTPException(409, {"code": "busy", "message": "a quest is already being generated"})
    return {"task_id": task_id}


@router.get("/generate/jobs")
async def list_generate_jobs_route(request: Request) -> Dict[str, List[Dict[str, Any]]]:
    """Recent `quest_generate` jobs (`limit` 1..50, default 10)."""
    raw = request.query_params.get("limit")
    if raw is None or raw == "":
        n = 10
    else:
        try:
            n = int(raw)
        except ValueError:
            raise _bad("limit must be an integer between 1 and 50")
        if not 1 <= n <= 50:
            raise _bad("limit must be an integer between 1 and 50")
    return {"jobs": await asyncio.to_thread(quest_authoring.recent_jobs, n)}

