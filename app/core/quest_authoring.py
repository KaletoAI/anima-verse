"""Quest authoring pipeline core: draft -> structure -> validate -> repair (quest stage 3).

Turns a short brief into a validated quest template and proposed role bindings
without writing anything to storage or submitting background jobs. Runs at most
one repair round when validation reports issues: a repair ``RuntimeError`` keeps
the prior issues alongside ``llm_failed``, and an unparseable repair when a
prior template exists records ``repair_unparsed`` without discarding an
otherwise acceptable admin draft.
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.core import llm_router, quest_catalog, quest_context, quest_engine, quest_types
from app.core.layout_prompt import extract_json_block
from app.core.log import get_logger
from app.core.prompt_templates import render_task

logger = get_logger("quest_authoring")

TASK_DRAFT = "quest_draft"
TASK_STRUCTURE = "quest_structure"
FENCE = "quest"
DRAFT_MAX_TOKENS = 1500
STRUCTURE_MAX_TOKENS = 4000
MAX_GAP_LINES = 30
PHASES = ("draft", "structure", "validate", "repair", "done")

_BLOCKING_PARSE_CODES = frozenset({"no_block", "bad_json", "shape", "too_large", "unknown_key"})
_FENCE_RE = re.compile(r"```json:quest")


def _issue(path: str, code: str, message: str) -> Dict[str, str]:
    return {"path": path, "code": code, "message": message}


def _emit(progress: Optional[Callable[[str], Any]], phase: str) -> None:
    if not callable(progress):
        return
    try:
        progress(phase)
    except Exception:  # noqa: BLE001 — progress callbacks never break authoring
        pass


def _parse_quest_block(text: str) -> Tuple[Optional[Dict[str, Any]], List[Dict[str, str]]]:
    """Extract ``{"template": {...}, "bindings": {...}}`` from a ``json:quest`` fence."""
    raw = str(text or "")
    try:
        parsed = extract_json_block(raw, FENCE)
    except TypeError:
        return None, [_issue("", "bad_json", "The json:quest block must contain a JSON object")]
    if parsed is None:
        if _FENCE_RE.search(raw):
            return None, [_issue("", "bad_json", "The json:quest block could not be parsed as JSON")]
        return None, [_issue("", "no_block", "Answer did not contain a ```json:quest block")]
    if not isinstance(parsed, dict) or not isinstance(parsed.get("template"), dict):
        return None, [_issue("", "bad_json", "The json:quest block must be an object with a 'template' object")]
    raw_bindings = parsed.get("bindings")
    if raw_bindings is not None and not isinstance(raw_bindings, dict):
        return None, [_issue("", "bad_json", "'bindings' in the json:quest block must be an object")]
    return {"template": parsed["template"], "bindings": dict(raw_bindings or {})}, []


def _issues(
    obj: Dict[str, Any],
    *,
    mode: str,
    giver: str,
    avatar: str,
) -> Tuple[Dict[str, Any], Dict[str, Any], List[Dict[str, str]]]:
    """Validate and clean a parsed ``{"template", "bindings"}`` object."""
    from app.models import quests

    raw_template = obj.get("template") if isinstance(obj.get("template"), dict) else {}
    bindings = dict(obj.get("bindings") or {}) if isinstance(obj.get("bindings"), dict) else {}
    issues: List[Dict[str, str]] = []

    allowed_keys = set(quests.TEMPLATE_CONTENT_KEYS)
    template: Dict[str, Any] = {}
    for key, value in raw_template.items():
        if key in allowed_keys:
            template[key] = value
        else:
            issues.append(_issue(str(key), "unknown_key", f"Unknown template field '{key}'"))

    shape_msg = quest_engine.check_template_fields(template)
    if shape_msg:
        issues.append(_issue("", "shape", shape_msg))
        return template, bindings, issues

    size = len(json.dumps(template, ensure_ascii=False).encode("utf-8"))
    if size > quest_engine.MAX_TEMPLATE_BYTES:
        issues.append(_issue(
            "",
            "too_large",
            f"The template is {size // 1024} KiB — at most {quest_engine.MAX_TEMPLATE_BYTES // 1024} KiB",
        ))

    issues.extend(quest_engine.validate_template(template))

    giver_role = template.get("giver_role")
    giver_role_str = giver_role.strip() if isinstance(giver_role, str) else ""
    if giver and giver_role_str:
        bindings[giver_role_str] = {"name": giver}

    role_kinds: Dict[str, str] = {}
    raw_roles = template.get("roles") if isinstance(template.get("roles"), list) else []
    for role in raw_roles:
        if isinstance(role, dict):
            rkey = role.get("key")
            if isinstance(rkey, str) and rkey.strip() and rkey not in role_kinds:
                role_kinds[rkey] = str(role.get("kind") or "")

    if mode == "admin":
        clean_bindings: Dict[str, Any] = {}
        for rkey, binding in bindings.items():
            kind = role_kinds.get(rkey)
            if not kind:
                continue
            try:
                if not quest_types.check_binding(kind, binding):
                    clean_bindings[rkey] = binding
            except Exception:  # noqa: BLE001 — drop unreadable/invalid default bindings silently
                continue
        bindings = clean_bindings
    else:
        if not giver_role_str:
            issues.append(_issue("giver_role", "giver_required", "An automatic quest must set giver_role"))
        if template.get("start_condition"):
            issues.append(_issue(
                "start_condition",
                "not_allowed_auto",
                "An automatic quest cannot have a start_condition",
            ))
        for prefix, entries, _pos in quest_engine.effect_positions(template):
            for j, entry in enumerate(entries):
                if isinstance(entry, dict) and entry.get("type") == quest_catalog.CREATE_PROP_TYPE:
                    issues.append(_issue(
                        f"{prefix}.{j}.type",
                        "not_allowed_auto",
                        f"An automatic quest cannot use {quest_catalog.CREATE_PROP_TYPE}",
                    ))
        try:
            issues.extend(quest_engine.check_bindings(template, bindings))
        except Exception as e:  # noqa: BLE001
            issues.append(_issue("bindings", "unavailable", str(e)))
        if not issues:
            issues.extend(quest_engine.dry_check(template, bindings, avatar))

    return template, bindings, issues


def _format_gaps(issues: List[Dict[str, str]]) -> str:
    lines = [
        f"- {i.get('path') or '(root)'}: {i.get('message') or i.get('code')}"
        for i in issues[:MAX_GAP_LINES]
    ]
    if len(issues) > MAX_GAP_LINES:
        lines.append(f"- … {len(issues) - MAX_GAP_LINES} more")
    return "\n".join(lines)


def _is_ok(mode: str, template: Optional[Dict[str, Any]], issues: List[Dict[str, str]]) -> bool:
    if not isinstance(template, dict):
        return False
    if mode == "auto":
        return len(issues) == 0
    return not any(
        quest_engine.blocking_issue(i) or str(i.get("code") or "") in _BLOCKING_PARSE_CODES
        for i in issues
    )


def generate(
    brief: str,
    *,
    giver: str | None = None,
    avatar: str | None = None,
    mode: str = "admin",
    progress: Optional[Callable[[str], Any]] = None,
) -> Dict[str, Any]:
    """Turn ``brief`` into a validated quest template and bindings without writing anything.

    ``mode`` must be ``"admin"`` or ``"auto"``. In ``"auto"`` mode, both ``giver``
    and ``avatar`` are required. Runs at most one repair call if the first
    structured answer has issues: if the repair call raises ``RuntimeError``,
    earlier issues are preserved alongside ``llm_failed``; if the repair answer
    fails to parse while a prior template dict exists, that template and its
    issues are kept and ``repair_unparsed`` (non-blocking in ``"admin"`` mode)
    is appended. Returns ``{"ok", "template", "bindings", "issues", "phase"}``.
    """
    if mode not in ("admin", "auto"):
        raise ValueError(f"mode must be 'admin' or 'auto', got {mode!r}")
    brief_text = (brief or "").strip() if isinstance(brief, str) else ""
    if not brief_text:
        raise ValueError("brief must not be empty")

    giver_name = (giver or "").strip() if isinstance(giver, str) else ""
    avatar_name = (avatar or "").strip() if isinstance(avatar, str) else ""
    if mode == "auto" and (not giver_name or not avatar_name):
        return {
            "ok": False,
            "template": None,
            "bindings": {},
            "issues": [_issue("", "bad_request", "Auto mode requires both giver and avatar")],
            "phase": "draft",
        }

    ctx = quest_context.build(giver_name or None, brief_text)
    rendered_ctx = quest_context.render(ctx)
    catalog_text = "\n".join(ctx["catalog"])
    role_kinds_text = ", ".join(ctx["role_kinds"])
    agent = giver_name or "QuestAuthor"

    # 1. Draft (prose)
    _emit(progress, "draft")
    try:
        sys_draft, usr_draft = render_task(
            "quest_draft",
            brief=brief_text,
            context=rendered_ctx,
            giver=giver_name,
            language=ctx["language"],
            mode=mode,
        )
        draft_resp = llm_router.llm_call(
            TASK_DRAFT,
            sys_draft,
            usr_draft,
            agent_name=agent,
            label="quest draft",
            max_tokens=DRAFT_MAX_TOKENS,
        )
    except RuntimeError as e:
        return {
            "ok": False,
            "template": None,
            "bindings": {},
            "issues": [_issue("", "llm_failed", str(e)[:300])],
            "phase": "draft",
        }
    draft_text = str(getattr(draft_resp, "content", "") or "").strip()
    if not draft_text:
        return {
            "ok": False,
            "template": None,
            "bindings": {},
            "issues": [_issue("", "empty_draft", "The draft model returned an empty response")],
            "phase": "draft",
        }

    # 2. Structure (JSON)
    _emit(progress, "structure")
    try:
        sys_struct, usr_struct = render_task(
            "quest_structure",
            draft=draft_text,
            context=rendered_ctx,
            catalog=catalog_text,
            role_kinds=role_kinds_text,
            giver=giver_name,
            avatar=avatar_name,
            mode=mode,
        )
        struct_resp = llm_router.llm_call(
            TASK_STRUCTURE,
            sys_struct,
            usr_struct,
            agent_name=agent,
            label="quest structure",
            max_tokens=STRUCTURE_MAX_TOKENS,
        )
    except RuntimeError as e:
        return {
            "ok": False,
            "template": None,
            "bindings": {},
            "issues": [_issue("", "llm_failed", str(e)[:300])],
            "phase": "structure",
        }
    raw_struct = str(getattr(struct_resp, "content", "") or "")

    # 3. Validate
    _emit(progress, "validate")
    parsed_obj, parse_issues = _parse_quest_block(raw_struct)
    if parsed_obj is not None:
        template: Optional[Dict[str, Any]]
        template, bindings, issues = _issues(
            parsed_obj, mode=mode, giver=giver_name, avatar=avatar_name,
        )
    else:
        template, bindings, issues = None, {}, parse_issues

    stopped_phase = "structure"

    # 4. Repair (at most ONE round)
    if issues:
        _emit(progress, "repair")
        stopped_phase = "repair"
        prev_json = (
            json.dumps(parsed_obj, ensure_ascii=False, indent=2)
            if parsed_obj is not None
            else raw_struct
        )
        try:
            sys_rep, usr_rep = render_task(
                "quest_structure_repair",
                previous_json=prev_json,
                gaps=_format_gaps(issues),
                catalog=catalog_text,
                context=rendered_ctx,
                role_kinds=role_kinds_text,
                giver=giver_name,
                avatar=avatar_name,
                mode=mode,
            )
            rep_resp = llm_router.llm_call(
                TASK_STRUCTURE,
                sys_rep,
                usr_rep,
                agent_name=agent,
                label="quest structure repair",
                max_tokens=STRUCTURE_MAX_TOKENS,
            )
        except RuntimeError as e:
            return {
                "ok": False,
                "template": template,
                "bindings": bindings,
                "issues": list(issues) + [_issue("", "llm_failed", str(e)[:300])],
                "phase": "repair",
            }
        raw_rep = str(getattr(rep_resp, "content", "") or "")
        rep_obj, rep_parse_issues = _parse_quest_block(raw_rep)
        if rep_obj is None:
            if isinstance(template, dict):
                issues = list(issues) + [
                    _issue(
                        str(pi.get("path") or ""),
                        "repair_unparsed",
                        f"The repair answer was unusable: {pi.get('message') or ''}",
                    )
                    for pi in rep_parse_issues
                ]
            else:
                issues = list(issues) + rep_parse_issues
        else:
            template, bindings, issues = _issues(
                rep_obj, mode=mode, giver=giver_name, avatar=avatar_name,
            )

    ok = _is_ok(mode, template, issues)
    if ok:
        _emit(progress, "done")
        return {
            "ok": True,
            "template": template,
            "bindings": bindings,
            "issues": issues,
            "phase": "done",
        }
    return {
        "ok": False,
        "template": template,
        "bindings": bindings,
        "issues": issues,
        "phase": stopped_phase,
    }


JOB_TASK_TYPE = "quest_generate"
MAX_BRIEF_CHARS = 2000


class GenerateBusy(RuntimeError):
    """A ``quest_generate`` job is already pending or running in the task queue."""


def submit(brief: str, giver: str | None = None) -> str:
    """Validate ``brief`` and ``giver`` and enqueue an admin quest-generation job."""
    from app.core.task_queue import get_task_queue
    from app.models.character import character_exists

    if not isinstance(brief, str) or not brief.strip():
        raise ValueError("brief must not be empty")
    if len(brief) > MAX_BRIEF_CHARS:
        raise ValueError(f"brief must be at most {MAX_BRIEF_CHARS} characters")
    if giver is not None and not isinstance(giver, str):
        raise ValueError("giver must be a string")
    giver_str = giver or ""
    if giver_str and not character_exists(giver_str):
        raise ValueError(f"unknown character '{giver_str}'")

    tq = get_task_queue()
    if tq.has_pending_task(JOB_TASK_TYPE):
        raise GenerateBusy("a quest is already being generated")
    return tq.submit(
        JOB_TASK_TYPE,
        {"brief": brief, "giver": giver_str},
        queue_name=JOB_TASK_TYPE,
        max_retries=0,
    )


def _handle(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Task-queue handler for ``quest_generate``: author and store an admin draft."""
    import sqlite3
    from app.core.task_queue import get_task_queue
    from app.models import quests

    tq = get_task_queue()
    tid = payload["_task_id"]
    progress = tq.get_task_progress(tid)
    if progress:
        raise RuntimeError("interrupted by restart — start the generation again")

    def update(phase: str, **fields: Any) -> None:
        progress.update(phase=phase, **fields)
        tq.update_task_progress(tid, progress)

    update("", state="running")
    brief = payload.get("brief", "")
    giver = payload.get("giver") or None
    try:
        result = generate(brief, giver=giver, mode="admin", progress=lambda ph: update(ph))
    except ValueError as e:
        final: Dict[str, Any] = {
            "phase": str(progress.get("phase") or ""),
            "state": "failed",
            "ok": False,
            "template_id": "",
            "title": "",
            "bindings": {},
            "issues": [_issue("", "bad_request", str(e))],
        }
        progress.clear()
        progress.update(final)
        tq.update_task_progress(tid, progress)
        return dict(final)

    template = result.get("template")
    issues = list(result.get("issues") or [])
    saved_tpl: Optional[Dict[str, Any]] = None
    if (
        isinstance(template, dict)
        and quest_engine.check_template_fields(template) is None
        and isinstance(template.get("title"), str)
        and bool(template["title"].strip())
        and len(json.dumps(template, ensure_ascii=False).encode("utf-8")) <= quest_engine.MAX_TEMPLATE_BYTES
    ):
        content = {k: template[k] for k in quests.TEMPLATE_CONTENT_KEYS if k in template}
        try:
            saved_tpl = quests.create_template(**content, origin="admin", state="draft")
        except (TypeError, ValueError, OverflowError, sqlite3.Error) as e:
            issues.append(_issue("", "store_failed", str(e)))

    if saved_tpl is not None:
        final = {
            "phase": "done",
            "state": "done",
            "ok": bool(result.get("ok")),
            "template_id": str(saved_tpl["id"]),
            "title": str(saved_tpl.get("title") or ""),
            "bindings": dict(result.get("bindings") or {}),
            "issues": issues,
        }
    else:
        final = {
            "phase": str(result.get("phase") or ""),
            "state": "failed",
            "ok": False,
            "template_id": "",
            "title": "",
            "bindings": {},
            "issues": issues,
        }
    progress.clear()
    progress.update(final)
    tq.update_task_progress(tid, progress)
    return dict(final)


def recent_jobs(limit: int = 10) -> List[Dict[str, Any]]:
    """Expose recent ``quest_generate`` jobs without internal payload fields."""
    from app.core.task_queue import get_task_queue

    out: List[Dict[str, Any]] = []
    for task in get_task_queue().list_recent_tasks(JOB_TASK_TYPE, limit=limit):
        payload = task.get("payload") if isinstance(task.get("payload"), dict) else {}
        progress = task.get("progress") if isinstance(task.get("progress"), dict) else {}
        raw_bindings = progress.get("bindings")
        raw_issues = progress.get("issues")
        out.append({
            "task_id": str(task.get("task_id") or ""),
            "status": str(task.get("status") or ""),
            "phase": str(progress.get("phase") or ""),
            "state": str(progress.get("state") or ""),
            "ok": bool(progress.get("ok", False)),
            "template_id": str(progress.get("template_id") or ""),
            "title": str(progress.get("title") or ""),
            "bindings": dict(raw_bindings) if isinstance(raw_bindings, dict) else {},
            "issues": list(raw_issues) if isinstance(raw_issues, list) else [],
            "error": str(task.get("error") or ""),
            "created_at": task.get("created_at"),
            "completed_at": task.get("completed_at"),
            "request": {
                "brief": str(payload.get("brief") or ""),
                "giver": str(payload.get("giver") or ""),
            },
        })
    return out


def register() -> None:
    """Register the ``quest_generate`` task-queue handler."""
    from app.core.task_queue import get_task_queue

    get_task_queue().register_handler(JOB_TASK_TYPE, _handle)

