"""The quest engine — template checks, start/cancel, signal-driven evaluation, the safety tick (quest stage 1).

Storage is ``app/models/quests.py``, the type catalog ``app/core/quest_catalog.py``, the built-in types and the
evaluation context ``app/core/quest_types.py``. This module is the only subscriber of the quest signals (plan D9,
tag ``"quest_engine"``).

THREADING (D11). The hook listeners run in the emitting thread (``play_say`` emits on the event loop), so they do
nothing but put the event payload on ONE queue; a single daemon worker thread takes it from there: it writes the
"spoke with" fact on ``utterance.heard`` and the "found" fact on ``item.discovered``, evaluates and runs the tick.
:func:`drain` waits until the queue is empty (tests).

EVALUATION. :func:`evaluate` looks at one avatar: only a player-controlled character fulfils anything (an NPC
entering the bound room changes nothing). Steps are sequential: per hidden/open run only the CURRENT expression is
read, and only when it listens to the signal (``""`` = every run). A hidden run whose start condition passes for an
avatar that meets the prerequisites is opened (no announcement, D15); an open run whose prerequisites AND current step pass records the step for this
avatar and goes on with the next step in the same call, whatever the signal was (a cascade of already true steps
ends in one call). A run reads only its ``template_snapshot`` (D2): editing the template never changes a running
quest. Evaluation is skipped while no hidden/open run exists; that count is loaded from storage on first use (never
assumed 0 after a restart) and reloaded after every start, open, end and tick.

TICK (D10, D11). :func:`tick` is the ``world_tick`` listener body, run on the worker. The periodic runner already gates
``world_tick`` on world freeze / queue pause, so the tick has no freeze check of its own, and a signal from a
player's own action is evaluated while frozen too. Order: expiry, then the reference check over every not-ended run
(``preparing``, ``hidden``, ``open``: a binding that no longer resolves makes the run ``broken``; so does a type that is
not registered at TWO consecutive ticks — including owed effect positions — and a live run object whose ``exists`` check
returns ``False`` at TWO consecutive ticks), then a full re-evaluation for every avatar. The reference check
runs BEFORE the re-evaluation, so no type evaluates a binding the check would reject.
A STORAGE failure during the check is not evidence that an entity is gone: that run is skipped for this tick (not
checked, not evaluated), never marked broken. The full re-evaluation is also what catches inventory writes that
emit no signal (an item definition deleted, a character import or reset).

EFFECTS (D8-D10). A template with ``setup_effects`` starts in state ``preparing``; the background effects worker
(:mod:`app.core.quest_effects`) applies setup, step ``on_done`` and ``reward`` payouts outside this worker, moves a
prepared run to ``hidden`` or ``open`` (stamping start/expiry and announcing it when it opens), and removes
non-permanent objects of ended runs. Every end site calls :func:`_after_run_ended` (withdraw announcement + wake the
effects worker).

TIME LIMIT. A signal never records a step of an open run past its ``expires_at``: the tick (which does not run while
the queue is paused) ends it ``failed``.

PLACEHOLDERS. A player text (title, summary, step text/hint, the lock text) may name a role as ``{role}``;
:func:`render_text` replaces it with the label frozen on the run at start (``binding_labels``).

PUSH (D15). Every state change ends in :func:`_quests_changed`, outside locks and transactions. A step notifies only
the avatar that fulfilled it; a run that opens at once (or opens from ``preparing``) is announced with a global world
event (the author's title and summary) whose id is kept on the run; when an announced run ends cancelled, failed or
broken that event is deleted, best effort.
"""
from __future__ import annotations

import dataclasses
import queue
import threading
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.core import quest_catalog
from app.core.log import get_logger

logger = get_logger("quest_engine")

HOOK_TAG = "quest_engine"
#: The hook events the engine subscribes to (D9).
SIGNALS = ("character.entered_room", "inventory.changed", "utterance.heard", "secret.learned", "item.discovered", "world_tick")
#: The run states the engine evaluates.
LIVE_STATES = ("hidden", "open")
#: The lock reason when the author left ``locked_text`` empty (D8).
DEFAULT_LOCKED_TEXT = "You do not meet the requirements."
#: Ended states whose announcement is taken back (D15).
_WITHDRAWN_STATES = ("cancelled", "failed", "broken")


class QuestRefused(Exception):
    """A run could not start; ``issues`` are ``{"path", "code", "message"}`` dicts."""

    def __init__(self, issues: List[Dict[str, str]]):
        super().__init__("; ".join(f"{i.get('path')}: {i.get('message')}" for i in issues) or "refused")
        self.issues = list(issues)


def _issue(path: str, code: str, message: str) -> Dict[str, str]:
    return {"path": path, "code": code, "message": message}


def _prefixed(prefix: str, issues: Iterable[Dict[str, str]]) -> List[Dict[str, str]]:
    return [{**i, "path": prefix + i.get("path", "")} for i in issues]


def _blank(value: Any) -> bool:
    return not isinstance(value, str) or not value.strip()


def _prerequisites(snapshot: dict) -> dict:
    prereq = snapshot.get("prerequisites")
    return prereq if isinstance(prereq, dict) else {}


def _steps(snapshot: dict) -> list:
    steps = snapshot.get("steps")
    return steps if isinstance(steps, list) else []


# --- Role placeholders -------------------------------------------------------------------------

def _scan_text(text: str) -> List[Tuple[str, str]]:
    """The parts of a player text: ("lit", text) and ("role", key) for each ``{key}``. ``{{`` and ``}}`` are
    literal braces. Raises ValueError on a single ``{`` without its ``}`` (or with a brace or nothing inside), and
    on a single ``}``."""
    parts: List[Tuple[str, str]] = []
    lit: List[str] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == "{":
            if text.startswith("{{", i):
                lit.append("{")
                i += 2
                continue
            end = text.find("}", i + 1)
            key = text[i + 1:end] if end > 0 else ""
            if end < 0 or not key or "{" in key:
                raise ValueError(f"unbalanced '{{' at character {i + 1}")
            if lit:
                parts.append(("lit", "".join(lit)))
                lit = []
            parts.append(("role", key))
            i = end + 1
        elif c == "}":
            if not text.startswith("}}", i):
                raise ValueError(f"unbalanced '}}' at character {i + 1}")
            lit.append("}")
            i += 2
        else:
            lit.append(c)
            i += 1
    if lit:
        parts.append(("lit", "".join(lit)))
    return parts


def _player_texts(template: dict) -> List[Tuple[str, Any]]:
    """(D7 path, value) of every text a player may read and that may carry role placeholders (``gm_notes`` never),
    including effect ``text`` parameters whose spec does not declare ``"placeholders": False``."""
    out: List[Tuple[str, Any]] = [("title", template.get("title")), ("summary", template.get("summary"))]
    for i, step in enumerate(_steps(template)):
        if isinstance(step, dict):
            out += [(f"steps.{i}.text", step.get("text")), (f"steps.{i}.hint", step.get("hint"))]
    out.append(("prerequisites.locked_text", _prerequisites(template).get("locked_text")))
    positions = effect_positions(template)
    if positions:
        known = quest_catalog.types()
        for prefix, entries, _position in positions:
            for j, entry in enumerate(entries):
                if not isinstance(entry, dict) or not isinstance(entry.get("type"), str):
                    continue
                t = known.get(entry["type"])
                if t is None:
                    continue
                params = entry.get("params")
                if not isinstance(params, dict):
                    continue
                for spec in t.params:
                    if spec.get("type") == "text" and spec.get("placeholders") is not False:
                        key = spec.get("key")
                        if key in params:
                            out.append((f"{prefix}.{j}.params.{key}", params[key]))
    return out


def render_text(text: str, run: dict) -> str:
    """``text`` with each ``{role}`` replaced by the run's frozen ``binding_labels`` (the role key itself when the
    run has no label for it) and ``{{``/``}}`` as single braces. A text that does not scan (only a template that
    never passed validation can hold one) is returned unchanged."""
    if not isinstance(text, str) or not text:
        return text if isinstance(text, str) else ""
    labels = (run or {}).get("binding_labels")
    labels = labels if isinstance(labels, dict) else {}
    try:
        parts = _scan_text(text)
    except ValueError:
        return text
    return "".join(value if kind == "lit" else str(labels.get(value) or value) for kind, value in parts)


def _binding_labels(template: dict, bindings: dict) -> Dict[str, str]:
    """One display label per bound role, read once at start (frozen on the run): character -> its name, location ->
    the location's name, room -> the room's name, item -> the item's name. The strict readers of
    ``quest_types.check_binding``; a label that cannot be read falls back to the id."""
    from app.models.inventory import get_item
    from app.models.world import get_location_by_id, get_room_by_id
    out: Dict[str, str] = {}
    roles = template.get("roles") if isinstance(template.get("roles"), list) else []
    for role in roles:
        if not isinstance(role, dict) or _blank(role.get("key")):
            continue
        key, kind = role["key"], role.get("kind")
        b = bindings.get(key) if isinstance(bindings.get(key), dict) else {}
        fallback = str(b.get("name") or b.get("item_id") or b.get("room_id") or b.get("location_id") or key)
        label = ""
        try:
            if kind == "character":
                label = str(b.get("name") or "")
            elif kind == "item":
                item = get_item(str(b.get("item_id") or ""), strict=True) or {}
                label = str(item.get("name") or "")
            elif kind in ("location", "room"):
                location = get_location_by_id(str(b.get("location_id") or ""), strict=True) or {}
                if kind == "location":
                    label = str(location.get("name") or "")
                else:
                    room = (get_room_by_id(location, str(b.get("room_id") or "")) if location else None) or {}
                    label = str(room.get("name") or "")
        except Exception as e:  # noqa: BLE001 - a label is display only, the id stands in
            logger.warning("quest start: label of role %r unreadable: %s", key, e)
        out[key] = label.strip() or fallback
    return out


# --- Template and binding checks --------------------------------------------------------------

def effect_positions(template: dict) -> List[Tuple[str, list, str]]:
    """``(path prefix, entry list, payout position)`` for every non-empty effect list of ``template`` in position
    order: ``setup_effects`` (``"setup"``), ``steps.<i>.on_done`` (``"step:<i>"``), ``rewards`` (``"reward"``).
    Non-list values are skipped here (:func:`validate_template` reports them)."""
    if not isinstance(template, dict):
        return []
    out: List[Tuple[str, list, str]] = []
    setup = template.get("setup_effects")
    if isinstance(setup, list) and setup:
        out.append(("setup_effects", setup, "setup"))
    for i, step in enumerate(_steps(template)):
        if isinstance(step, dict):
            on_done = step.get("on_done")
            if isinstance(on_done, list) and on_done:
                out.append((f"steps.{i}.on_done", on_done, f"step:{i}"))
    rewards = template.get("rewards")
    if isinstance(rewards, list) and rewards:
        out.append(("rewards", rewards, "reward"))
    return out


def _parse_nonneg(text: str, where: str) -> int:
    if not text.isascii() or not text.isdigit():
        raise ValueError(f"Unknown scope position: {where!r}")
    return int(text)


def scope_at(template: dict, where: str) -> quest_catalog.Scope:
    """The reachable :class:`quest_catalog.Scope` at template position ``where`` (D4): ``"start"``, ``"prereq"``,
    ``"step:<i>"``, ``"on_done:<i>:<j>"``, ``"setup:<j>"``, or ``"reward:<j>"``. Raises ``ValueError`` for any other
    position string. One catalog read per call."""
    tpl = template if isinstance(template, dict) else {}
    setup = tpl.get("setup_effects") if isinstance(tpl.get("setup_effects"), list) else []
    step_effects = [step.get("on_done") if isinstance(step, dict) and isinstance(step.get("on_done"), list) else []
                    for step in _steps(tpl)]
    rewards = tpl.get("rewards") if isinstance(tpl.get("rewards"), list) else []

    if where in ("start", "prereq"):
        reachable = list(setup)
    elif isinstance(where, str) and where.startswith("step:"):
        parts = where.split(":")
        if len(parts) != 2:
            raise ValueError(f"Unknown scope position: {where!r}")
        idx = _parse_nonneg(parts[1], where)
        reachable = list(setup)
        for s_idx in range(min(idx, len(step_effects))):
            reachable.extend(step_effects[s_idx])
    elif isinstance(where, str) and where.startswith("on_done:"):
        parts = where.split(":")
        if len(parts) != 3:
            raise ValueError(f"Unknown scope position: {where!r}")
        idx = _parse_nonneg(parts[1], where)
        j = _parse_nonneg(parts[2], where)
        reachable = list(setup)
        for s_idx in range(min(idx, len(step_effects))):
            reachable.extend(step_effects[s_idx])
        if idx < len(step_effects):
            reachable.extend(step_effects[idx][:j])
    elif isinstance(where, str) and where.startswith("setup:"):
        parts = where.split(":")
        if len(parts) != 2:
            raise ValueError(f"Unknown scope position: {where!r}")
        j = _parse_nonneg(parts[1], where)
        reachable = list(setup[:j])
    elif isinstance(where, str) and where.startswith("reward:"):
        parts = where.split(":")
        if len(parts) != 2:
            raise ValueError(f"Unknown scope position: {where!r}")
        j = _parse_nonneg(parts[1], where)
        reachable = list(setup)
        for entries in step_effects:
            reachable.extend(entries)
        reachable.extend(rewards[:j])
    else:
        raise ValueError(f"Unknown scope position: {where!r}")

    roles: Dict[str, str] = {}
    raw_roles = tpl.get("roles") if isinstance(tpl.get("roles"), list) else []
    for role in raw_roles:
        if isinstance(role, dict):
            key = role.get("key")
            if not _blank(key) and key not in roles:
                roles[key] = str(role.get("kind") or "")

    known = quest_catalog.types()
    objects: Dict[str, str] = {}
    for entry in reachable:
        if isinstance(entry, dict):
            key = entry.get("key")
            if isinstance(key, str) and key and key not in objects:
                t = known.get(entry.get("type")) if isinstance(entry.get("type"), str) else None
                objects[key] = quest_catalog.entry_object_kind(
                    t, entry.get("params") if isinstance(entry.get("params"), dict) else {}
                ) if t is not None else ""

    later: set = set()
    for entries in [setup, *step_effects, rewards]:
        for entry in entries:
            if isinstance(entry, dict):
                key = entry.get("key")
                if isinstance(key, str) and key and key not in objects:
                    later.add(key)

    return quest_catalog.Scope(roles=roles, objects=objects, later=frozenset(later))


def _expressions(template: dict) -> List[Tuple[str, Any, Tuple[str, ...], str]]:
    """(path, expression, allowed type kinds, scope position) of every expression position of a template (D7)."""
    out: List[Tuple[str, Any, Tuple[str, ...], str]] = []
    for i, step in enumerate(_steps(template)):
        if isinstance(step, dict):
            out.append((f"steps.{i}.condition", step.get("condition") or {}, ("condition",), f"step:{i}"))
    out.append(("start_condition", template.get("start_condition") or {}, ("condition",), "start"))
    out.append(("prerequisites.condition", _prerequisites(template).get("condition") or {},
                ("condition", "prerequisite"), "prereq"))
    return out


#: The largest `time_limit_s` SQLite can store (a signed 64-bit integer).
MAX_TIME_LIMIT_S = 2 ** 63 - 1


def check_template_fields(body: Dict[str, Any]) -> Optional[str]:
    """Why a template body cannot be stored as sent, or None: a text field (`title`, `summary`, `gm_notes`,
    `giver_role`) that is not text, a container field (`quests.TEMPLATE_CONTAINERS`) that is not its expected list or
    object type, or a `time_limit_s` that is not a whole number SQLite can store. Only the keys present are checked.
    Used by the admin route (400) and the World Dev free mode (a refusal) alike."""
    from app.models import quests
    for key in ("title", "summary", "gm_notes", "giver_role"):
        if key in body and not isinstance(body[key], str):
            return f"{key} must be text"
    for key, kind in quests.TEMPLATE_CONTAINERS.items():
        if key in body and not isinstance(body[key], kind):
            return f"'{key}' must be {'a list' if kind is list else 'an object'} (leave it out for none)"
    if "time_limit_s" in body:
        limit = body["time_limit_s"]
        if isinstance(limit, bool) or not isinstance(limit, int) or not 0 <= limit <= MAX_TIME_LIMIT_S:
            return "time_limit_s is a whole number of seconds, 0 or more"
    return None


def _effect_scope_where(position: str, index: int) -> str:
    if position == "setup":
        return f"setup:{index}"
    if position == "reward":
        return f"reward:{index}"
    return f"on_done:{position.split(':', 1)[1]}:{index}"


def validate_template(template: dict) -> list[dict]:
    """Every authoring issue of ``template`` as ``{"path", "code", "message"}`` (paths per D7), including empty step
    conditions (D1), ``giver_role`` (D3), and effect lists ``setup_effects`` / ``steps[i].on_done`` / ``rewards``
    (D2, D4). No world entity is read; ``check_expression`` and ``check_effects`` already run each type's
    ``validate(params, None)``."""
    if not isinstance(template, dict):
        return [_issue("", "shape", "A quest template must be an object")]
    issues: List[Dict[str, str]] = []
    if _blank(template.get("title")):
        issues.append(_issue("title", "required", "The quest needs a title"))
    roles = template.get("roles") if isinstance(template.get("roles"), list) else []
    seen_roles: set = set()
    role_kinds: Dict[str, Any] = {}
    for i, role in enumerate(roles):
        role = role if isinstance(role, dict) else {}
        key = role.get("key")
        if _blank(key):
            issues.append(_issue(f"roles.{i}.key", "required", "A role needs a key"))
        elif key in seen_roles:
            issues.append(_issue(f"roles.{i}.key", "duplicate", f"Role key '{key}' is used twice"))
        else:
            seen_roles.add(key)
            role_kinds[key] = role.get("kind")
        if role.get("kind") not in quest_catalog.ROLE_KINDS:
            issues.append(_issue(f"roles.{i}.kind", "bad_kind",
                                 f"A role kind is one of {', '.join(quest_catalog.ROLE_KINDS)}"))
    giver = template.get("giver_role", "")
    if giver is None:
        giver = ""
    if giver != "":
        if not isinstance(giver, str) or role_kinds.get(giver) != "character":
            issues.append(_issue("giver_role", "unknown_role",
                                 f"The giver role '{giver}' is not a character role of this quest"))
    steps = _steps(template)
    if not steps:
        issues.append(_issue("steps", "required", "The quest needs at least one step"))
    seen_steps: set = set()
    for i, step in enumerate(steps):
        step = step if isinstance(step, dict) else {}
        sid = step.get("id")
        if _blank(sid):
            issues.append(_issue(f"steps.{i}.id", "required", "A step needs an id"))
        elif sid in seen_steps:
            issues.append(_issue(f"steps.{i}.id", "duplicate", f"Step id '{sid}' is used twice"))
        else:
            seen_steps.add(sid)
        if _blank(step.get("text")):
            issues.append(_issue(f"steps.{i}.text", "required", "A step needs a text"))
        cond = step.get("condition")
        if not isinstance(cond, dict) or not cond:
            issues.append(_issue(f"steps.{i}.condition", "required", "A step needs a condition"))
    for path, text in _player_texts(template):
        if not isinstance(text, str):
            continue
        try:
            parts = _scan_text(text)
        except ValueError as e:
            issues.append(_issue(path, "bad_text", f"Write a brace as {{{{ or }}}}: {e}"))
            continue
        for kind, key in parts:
            if kind == "role" and key not in seen_roles:
                issues.append(_issue(path, "unknown_role", f"'{{{key}}}' is not a role of this quest"))
    for path, expr, kinds, where in _expressions(template):
        issues.extend(_prefixed(path, quest_catalog.check_expression(
            expr, scope_at(template, where), allowed_kinds=kinds)))
    for field in ("setup_effects", "rewards"):
        if field in template and template[field] is not None and not isinstance(template[field], list):
            issues.append(_issue(field, "shape", f"'{field}' must be a list"))
    for i, step in enumerate(steps):
        if isinstance(step, dict) and "on_done" in step and step["on_done"] is not None \
                and not isinstance(step["on_done"], list):
            issues.append(_issue(f"steps.{i}.on_done", "shape", "'on_done' must be a list"))
    props_before = 0
    earlier_keys: set = set()
    for prefix, entries, position in effect_positions(template):
        issues.extend(quest_catalog.check_effects(
            entries,
            lambda j, pos=position: scope_at(template, _effect_scope_where(pos, j)),
            path=prefix,
            reward=(position == "reward"),
            props_before=props_before,
            setup=(position == "setup"),
        ))
        props_before += sum(1 for e in entries if isinstance(e, dict)
                            and e.get("type") == quest_catalog.CREATE_PROP_TYPE)
        list_keys: set = set()
        for j, entry in enumerate(entries):
            if not isinstance(entry, dict):
                continue
            key = entry.get("key")
            if isinstance(key, str) and key and key not in seen_roles:
                if key not in list_keys and key in earlier_keys:
                    issues.append(_issue(f"{prefix}.{j}.key", "duplicate", f"Effect key '{key}' is used twice"))
                list_keys.add(key)
        earlier_keys.update(list_keys)
    known = quest_catalog.types()
    start = template.get("start_condition") or {}
    for leaf_path, leaf in quest_catalog.walk(start):
        t = known.get(leaf["type"])
        if t is not None and t.needs_open_run:
            issues.append(_issue(f"start_condition{leaf_path}.type", "not_allowed_here",
                                 f"'{t.label}' counts from the opening and cannot be a start condition"))
    # A hidden run (non-empty start condition) opens only once its prerequisites pass, so a type that is
    # unavailable until the run has opened would keep it hidden forever there; with an empty start condition the
    # run is open from the start and the type is fine.
    prereq_expr = _prerequisites(template).get("condition") or {}
    if start and prereq_expr:
        for leaf_path, leaf in quest_catalog.walk(prereq_expr):
            t = known.get(leaf["type"])
            if t is not None and t.needs_open_run:
                issues.append(_issue(
                    f"prerequisites.condition{leaf_path}.type", "not_allowed_here",
                    f"'{t.label}' counts from the opening; with a start condition the run opens only once the "
                    f"prerequisites pass, so it would stay hidden forever"))
    limit = template.get("time_limit_s")
    limit = 0 if limit is None else limit
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
        issues.append(_issue("time_limit_s", "bad_value", "The time limit is a whole number of seconds, 0 or more"))
    return issues


def check_bindings(template: dict, bindings: dict, *, strict: bool = False) -> list[dict]:
    """The issues of ``bindings`` for ``template``: every role bound in its D6 shape to an entity that exists
    (``quest_types.check_binding``, path ``bindings.<role key>``), and each expression leaf and effect entry's
    ``validate(params, bindings)`` (path ending in ``.type``). A type that is not registered adds nothing here
    (:func:`validate_template` and the tick report it).

    RAISES on a storage error: a failed read is not a missing entity, so the caller must not turn it into an issue.
    A type validator that raises becomes a ``bad_param`` issue (the start refuses); with ``strict=True`` (the tick) it
    re-raises instead, because a raising validator is no evidence that a reference is gone and ``broken`` is final."""
    from app.core import quest_types
    template = template if isinstance(template, dict) else {}
    bindings = bindings if isinstance(bindings, dict) else {}
    issues: List[Dict[str, str]] = []
    roles = template.get("roles") if isinstance(template.get("roles"), list) else []
    for role in roles:
        if not isinstance(role, dict) or _blank(role.get("key")):
            continue
        key = role["key"]
        if key not in bindings:
            issues.append(_issue(f"bindings.{key}", "unbound", f"Role '{key}' is not bound"))
            continue
        for found in quest_types.check_binding(str(role.get("kind") or ""), bindings[key]):
            issues.append(_issue(f"bindings.{key}", str(found.code), str(found.message)))
    known = quest_catalog.types()
    for path, expr, _kinds, _where in _expressions(template):
        for leaf_path, leaf in quest_catalog.walk(expr):
            t = known.get(leaf["type"])
            if t is None or t.validate is None:
                continue
            where = f"{path}{leaf_path}.type"
            try:
                own = t.validate(quest_catalog._with_defaults(t, leaf.get("params") or {}), bindings) or []
                issues.extend(_issue(where, str(i.code), str(i.message)) for i in own)
            except Exception as e:  # noqa: BLE001 - a package's validator never breaks the check
                if strict:
                    raise
                logger.exception("validate of quest type %r failed", t.id)
                issues.append(_issue(where, "bad_param", f"'{t.label}' could not check its parameters: {e}"))
    for prefix, entries, _position in effect_positions(template):
        for j, entry in enumerate(entries):
            if not isinstance(entry, dict) or not isinstance(entry.get("type"), str):
                continue
            t = known.get(entry["type"])
            if t is None or t.validate is None:
                continue
            where = f"{prefix}.{j}.type"
            params = entry.get("params") if isinstance(entry.get("params"), dict) else {}
            try:
                own = t.validate(quest_catalog._with_defaults(t, params), bindings) or []
                issues.extend(_issue(where, str(i.code), str(i.message)) for i in own)
            except Exception as e:  # noqa: BLE001 - a package's validator never breaks the check
                if strict:
                    raise
                logger.exception("validate of quest type %r failed", t.id)
                issues.append(_issue(where, "bad_param", f"'{t.label}' could not check its parameters: {e}"))
    return issues


def _unregistered(template: dict, *, owed: Iterable[str] = ()) -> List[Dict[str, str]]:
    """One issue per expression leaf whose type is not registered now, plus one per effect entry whose payout
    position is in ``owed`` (an effect type matters only while its position is still owed: setup of a preparing run,
    an unapplied payout — wired by a later task). Reads the catalog strictly: a contributor that raises raises here
    (the tick skips that run), it is not read as "type gone"."""
    known = quest_catalog.types(strict=True)
    tpl = template if isinstance(template, dict) else {}
    issues = [_issue(f"{path}{leaf_path}.type", "type_not_registered",
                     f"Quest type '{leaf['type']}' is not registered")
              for path, expr, _kinds, _where in _expressions(tpl)
              for leaf_path, leaf in quest_catalog.walk(expr) if leaf["type"] not in known]
    owed_set = set(owed)
    if owed_set:
        for prefix, entries, position in effect_positions(tpl):
            if position not in owed_set:
                continue
            for j, entry in enumerate(entries):
                if not isinstance(entry, dict):
                    continue
                type_id = entry.get("type")
                if isinstance(type_id, str) and type_id and type_id not in known:
                    issues.append(_issue(f"{prefix}.{j}.type", "type_not_registered",
                                         f"Quest type '{type_id}' is not registered"))
    return issues


# --- How many runs are live ----------------------------------------------------------------------

_live_lock = threading.Lock()
_live_count: Optional[int] = None  # None = not loaded yet (a fresh process)
#: Ids of the not-ended runs that named an unregistered type at the previous tick (only the tick reads and writes it).
_missing_type_runs: set = set()
#: Ids of the live run objects whose ``exists`` check returned False at the previous tick (only the tick touches it).
_missing_object_ids: set = set()


def _refresh_live() -> int:
    """Read AND store the count under one lock, so an older read never overwrites a newer one."""
    from app.models.quests import count_runs
    global _live_count
    with _live_lock:
        _live_count = count_runs(LIVE_STATES)
        return _live_count


def _has_live_runs() -> bool:
    with _live_lock:
        known = _live_count
    return (_refresh_live() if known is None else known) > 0


def has_live_runs() -> bool:
    """Whether any run is hidden or open (cached count; the cheap early-out of prompt builders)."""
    return _has_live_runs()


# --- Push and side effects (always outside locks and transactions) -------------------------------

def _quests_changed() -> None:
    """The ONE push of the engine: every bound avatar's quest book listens to ``notices`` (D15)."""
    from app.core import sync_topics
    sync_topics.avatars(sync_topics.bound_avatars(), "notices")


def _withdraw_announcement(run_id: str) -> None:
    """Delete the news event of an announced run that ended cancelled/failed/broken (best effort)."""
    try:
        from app.models.events import delete_event
        from app.models.quests import get_run
        run = get_run(run_id) or {}
        if run.get("news_event_id") and run.get("state") in _WITHDRAWN_STATES:
            delete_event(run["news_event_id"])
    except Exception as e:  # noqa: BLE001
        logger.warning("quest run %s: withdrawing the announcement failed: %s", run_id, e)


def _after_run_ended(run_id: str) -> None:
    """One end path (D10): withdraw the announcement (if any) and wake the effects worker for cleanup."""
    _withdraw_announcement(run_id)
    try:
        from app.core import quest_effects
        quest_effects.wake()
    except Exception as e:  # noqa: BLE001
        logger.warning("quest run %s: waking the effects worker failed: %s", run_id, e)


def _announce(run: dict) -> None:
    """Announce a run that opened at once in the world news (global event, D15) and keep the event id on the run.
    The text is the author's own title and summary."""
    from app.models.events import add_event
    from app.models.quests import set_run_field
    snap = run.get("template_snapshot") or {}
    title = render_text(str(snap.get("title") or ""), run).strip()
    summary = render_text(str(snap.get("summary") or ""), run).strip()
    try:
        event = add_event(f"{title}: {summary}" if summary else title, location_id=None, category="social")
        set_run_field(run["id"], "news_event_id", event["id"])
    except Exception as e:  # noqa: BLE001 - a failed announcement never undoes the start
        logger.warning("quest run %s: announcement failed: %s", run.get("id"), e)


def _notify_step(avatar: str, run: dict, step_index: int) -> None:
    """Tell the avatar that fulfilled the step, and nobody else (D15). Never raises: the step is recorded already,
    and a failed notice must not keep the run's push from happening."""
    try:
        _store_step_notice(avatar, run, step_index)
    except Exception as e:  # noqa: BLE001
        logger.warning("quest run %s: the step %s notice for %s failed: %s", run.get("id"), step_index, avatar, e)


def _store_step_notice(avatar: str, run: dict, step_index: int) -> None:
    from app.core.i18n import t
    from app.models.character import get_character_language
    from app.models.notifications import create_notification
    snap = run.get("template_snapshot") or {}
    steps = _steps(snap)
    try:
        lang = get_character_language(avatar)
    except Exception:  # noqa: BLE001 - an unreadable profile gets the English text
        lang = ""
    if run.get("state") == "done":
        text = t("Quest complete: {title}", lang).replace("{title}", render_text(str(snap.get("title") or ""), run))
    else:
        step = steps[step_index] if 0 <= step_index < len(steps) and isinstance(steps[step_index], dict) else {}
        text = t("Quest step done: {step}", lang).replace("{step}", render_text(str(step.get("text") or ""), run))
    if not create_notification(avatar, text, notification_type="quest",
                               metadata={"run_id": run.get("id"), "step": step_index}, once_unread=True):
        logger.warning("quest run %s: the step %s notice for %s was not stored", run.get("id"), step_index, avatar)


# --- Start / cancel / a deleted character --------------------------------------------------------

def _expiry(snapshot: dict, now) -> str:
    """The canonical expiry stamp ``time_limit_s`` after ``now``; "" without a limit."""
    from app.core.game_time import GameDuration
    limit = snapshot.get("time_limit_s") or 0
    if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
        return ""
    return (now + GameDuration.of(seconds=limit)).canonical()


def start_run(template_id: str, bindings: dict, *, started_by: str = "") -> dict:
    """Start a run of the ``ready`` template ``template_id`` with ``bindings``, or raise :class:`QuestRefused`.

    The template is frozen as the run's snapshot. When the template has ``setup_effects``, the store creates the
    run in state ``preparing`` and this wakes the effects worker without announcing it (the worker announces it
    once setup finishes and the run opens). Otherwise, with a start condition the run is ``hidden``; without one
    it is ``open`` at once (``started_game_ts`` stamped by the store, ``expires_at`` from ``time_limit_s``) and
    announced.
    """
    from app.core.timeutils import game_time
    from app.models import quests
    template = quests.get_template(template_id)
    if template is None:
        raise QuestRefused([_issue("", "unknown_template", f"Quest template '{template_id}' does not exist")])
    if template.get("state") != "ready":
        raise QuestRefused([_issue("state", "not_ready", "Only a ready template can be started")])
    issues = validate_template(template) + check_bindings(template, bindings)
    if issues:
        raise QuestRefused(issues)
    hidden = bool(template.get("start_condition"))
    run = quests.create_run(template=template, bindings=dict(bindings), state="hidden" if hidden else "open",
                            started_by=started_by,
                            expires_at="" if hidden else _expiry(template, game_time()),
                            binding_labels=_binding_labels(template, bindings))
    if run["state"] == "open":
        _announce(run)
        run = quests.get_run(run["id"]) or run
    elif run["state"] == "preparing":
        try:
            from app.core import quest_effects
            quest_effects.wake()
        except Exception as e:  # noqa: BLE001
            logger.warning("quest run %s: waking the effects worker failed: %s", run["id"], e)
    _refresh_live()
    _quests_changed()
    return run


def cancel_run(run_id: str) -> bool:
    """End a not yet ended run as ``cancelled`` (its announcement goes); False when it had ended or is unknown."""
    from app.models.quests import set_run_state
    if not set_run_state(run_id, "cancelled"):
        return False
    _after_run_ended(run_id)
    _refresh_live()
    _quests_changed()
    return True


def on_character_deleted(name: str) -> None:
    """Every not yet ended run that binds ``name`` to a character role turns ``broken`` (``delete_character``
    step 0b; the fast path in front of the tick's reference check)."""
    from app.models.quests import RUN_OPEN_STATES, list_runs, set_run_state
    changed: List[str] = []
    for run in list_runs(states=RUN_OPEN_STATES):
        roles = (run.get("template_snapshot") or {}).get("roles") or []
        bindings = run.get("bindings") or {}
        keys = [r["key"] for r in roles if isinstance(r, dict) and r.get("kind") == "character"
                and isinstance(bindings.get(r.get("key")), dict) and bindings[r["key"]].get("name") == name]
        issues = [_issue(f"bindings.{key}", "unknown_character", f"Character '{name}' was deleted") for key in keys]
        if issues and set_run_state(run["id"], "broken", issues=issues):
            changed.append(run["id"])
    for run_id in changed:
        _after_run_ended(run_id)
    if changed:
        _refresh_live()
        _quests_changed()


# --- Evaluation ----------------------------------------------------------------------------------

def _passes(expr: Any, ctx) -> bool:
    result = quest_catalog.evaluate_expression(expr, ctx)
    return bool(result.available and result.passed)


def _listens(expr: Any, signal: str) -> bool:
    return not signal or signal in quest_catalog.signals_of(expr)


def _evaluate_run(run: dict, avatar: str, signal: str) -> bool:
    """Carry one run as far as ``avatar`` fulfils it; True when it changed."""
    from app.core import quest_types
    from app.core.timeutils import game_time
    from app.models import quests
    snap = run.get("template_snapshot") or {}
    steps = _steps(snap)
    changed = False
    ctx = None
    prereq = _prerequisites(snap).get("condition") or {}
    if run["state"] == "open" and run.get("expires_at") and game_time().canonical() > run["expires_at"]:
        return False  # past its time limit: nothing is recorded, the tick ends it failed
    if run["state"] == "hidden":
        start = snap.get("start_condition") or {}
        if not _listens(start, signal):
            return False
        ctx = quest_types.build_context(avatar, run)
        # An avatar that fails the prerequisites does not count — it does not open the run either.
        if ctx is None or not _passes(start, ctx) or (prereq and not _passes(prereq, ctx)):
            return False
        now = game_time()
        if not quests.open_run(run["id"], started_game_ts=now.canonical(), expires_at=_expiry(snap, now)):
            return False
        changed = True
        run = quests.get_run(run["id"]) or {}
        signal = ""  # the first step of a run that just opened is read whatever the signal was
    for _ in range(len(steps)):
        index = int(run.get("current_step") or 0)
        if run.get("state") != "open" or not 0 <= index < len(steps):
            break
        step = steps[index] if isinstance(steps[index], dict) else {}
        expr = step.get("condition") or {}
        if not _listens(expr, signal):
            break
        signal = ""  # a cascade reads the next step whatever the signal was
        ctx = quest_types.build_context(avatar, run) if ctx is None else dataclasses.replace(ctx, run=run)
        if ctx is None or (prereq and not _passes(prereq, ctx)) or not _passes(expr, ctx):
            break
        updated = quests.record_step_done(run["id"], index, avatar=avatar, mind=ctx.mind)
        if updated is None:
            break  # another avatar (or the tick) got there first
        changed = True
        run = updated
        if run.get("state") == "done":
            _after_run_ended(run["id"])
        else:
            try:
                from app.core import quest_effects
                quest_effects.wake()
            except Exception as e:  # noqa: BLE001
                logger.warning("quest run %s: waking the effects worker failed: %s", run["id"], e)
        _notify_step(avatar, run, index)
    return changed


def _evaluate(avatar: str, signal: str, skip: frozenset = frozenset()) -> List[str]:
    from app.models.account import is_player_controlled
    from app.models.quests import list_runs
    if not avatar or not is_player_controlled(avatar) or not _has_live_runs():
        return []
    changed: List[str] = []
    failed = False
    for run in reversed(list_runs(states=LIVE_STATES)):  # oldest first
        if run["id"] in skip:
            continue
        try:
            if _evaluate_run(run, avatar, signal):
                changed.append(run["id"])
        except Exception:  # noqa: BLE001 - one run never stops the others
            # It may have failed AFTER a state change (open_run, record_step_done): push as if it changed.
            failed = True
            logger.exception("quest run %s: evaluation for %s failed", run.get("id"), avatar)
    if changed or failed:
        try:
            _refresh_live()
        finally:
            _quests_changed()
    return changed


def evaluate(avatar: str, signal: str = "") -> list[str]:
    """Evaluate every hidden/open run for ``avatar`` whose current expression listens to ``signal`` (``""`` = every
    run); returns the ids of the runs that changed. Nothing for a character that is not an avatar."""
    return _evaluate(avatar, signal)


def avatar_view(run: dict, avatar: str) -> dict:
    """``{"locked", "locked_text"}`` of ``avatar`` for ``run`` (D8): locked while the prerequisites do not pass,
    unavailable included (such an avatar's actions do not count either). The text is the author's ``locked_text``,
    never an evaluator's reason; :data:`DEFAULT_LOCKED_TEXT` when it is empty."""
    from app.core import quest_types
    prereq = _prerequisites((run or {}).get("template_snapshot") or {})
    expr = prereq.get("condition") or {}
    if not expr:
        return {"locked": False, "locked_text": ""}
    ctx = quest_types.build_context(avatar, run)
    if ctx is not None and _passes(expr, ctx):
        return {"locked": False, "locked_text": ""}
    text = prereq.get("locked_text")
    return {"locked": True,
            "locked_text": text.strip() if isinstance(text, str) and text.strip() else DEFAULT_LOCKED_TEXT}


# --- Tick ------------------------------------------------------------------------------------------

def tick() -> None:
    """Expiry, reference check, full re-evaluation (D10, D11); see the module docstring. No freeze check here."""
    from app.core import quest_objects
    from app.core.timeutils import game_time
    from app.models.account import get_all_avatars
    from app.models.quests import RUN_OPEN_STATES, expire_runs, list_objects, list_payouts, list_runs, set_run_state
    global _missing_type_runs, _missing_object_ids
    ended = list(expire_runs(game_time().canonical()))
    skip: set = set()
    missing_now: set = set()
    missing_objects_now: set = set()
    for run in list_runs(states=RUN_OPEN_STATES):
        snap = run.get("template_snapshot") or {}
        try:
            owed = [p["position"] for p in list_payouts(states=("pending",), run_id=run["id"])]
            issues = check_bindings(snap, run.get("bindings") or {}, strict=True)
            unregistered = _unregistered(snap, owed=owed)
            live_objects = list_objects(run["id"], statuses=("live",))
        except Exception as e:  # noqa: BLE001 - a failed read or a raising validator: skip this run this tick
            logger.warning("quest run %s: reference check failed, skipped this tick: %s", run.get("id"), e)
            skip.add(run["id"])
            if run["id"] in _missing_type_runs:
                missing_now.add(run["id"])
            continue
        if unregistered:
            # A type missing from ONE catalog read (a package reloading) is no evidence: broken only when the
            # same run already missed a type at the previous tick.
            missing_now.add(run["id"])
            if run["id"] in _missing_type_runs:
                issues = issues + unregistered
        for obj in live_objects:
            kind = quest_objects.get_kind(str(obj.get("kind") or ""))
            if kind is None:
                continue
            try:
                present = kind.exists(obj.get("ref") or {})
            except Exception as e:  # noqa: BLE001 - unreadable status is not "gone"
                logger.warning("quest run %s: object %s exists check failed: %s", run.get("id"), obj.get("id"), e)
                continue
            if present is False:
                oid = obj["id"]
                missing_objects_now.add(oid)
                if oid in _missing_object_ids:
                    label = obj.get("label") or obj.get("effect_key") or str(oid)
                    issues = issues + [_issue(f"objects.{obj['effect_key']}", "object_gone", f"'{label}' is gone")]
        if issues and set_run_state(run["id"], "broken", issues=issues, from_states=RUN_OPEN_STATES):
            ended.append(run["id"])
    _missing_type_runs = missing_now
    _missing_object_ids = missing_objects_now
    for run_id in ended:
        _after_run_ended(run_id)
    _refresh_live()
    if ended:
        _quests_changed()
    for avatar in sorted(get_all_avatars()):
        _evaluate(avatar, "", frozenset(skip))


# --- Listeners and the worker --------------------------------------------------------------------

_queue: "queue.Queue[Tuple[str, Dict[str, Any]]]" = queue.Queue()
_worker_lock = threading.Lock()
_worker: Optional[threading.Thread] = None


def _heard(payload: Dict[str, Any]) -> None:
    """A conversation line of a non-avatar (``source == "loop"``) addressed to avatars that heard it: each such
    avatar's MIND has spoken with the speaker's mind. The fact is written whether or not a run is open (a talk before
    the quest started counts); then the avatar is evaluated."""
    from app.core.linked_characters import mind_of
    from app.core.quest_types import FACT_SPOKE_WITH
    from app.models.quests import add_fact
    speaker = payload.get("speaker") or ""
    if not speaker or payload.get("speaker_is_avatar") or payload.get("source") != "loop":
        return
    heard = set(payload.get("avatars") or [])
    targets = list(dict.fromkeys(a for a in payload.get("addressees") or [] if a in heard and a != speaker))
    for avatar in targets:
        try:
            add_fact(mind_of(avatar), FACT_SPOKE_WITH, mind_of(speaker))
        except Exception as e:  # noqa: BLE001 - one failed write never costs the other targets their fact
            logger.warning("quest engine: the spoke_with fact %s -> %s was not written: %s", avatar, speaker, e)
    for avatar in targets:
        evaluate(avatar, "utterance.heard")


def _learned(payload: Dict[str, Any]) -> None:
    """A mind learned a secret: evaluate every avatar belonging to that mind."""
    from app.core.linked_characters import mind_of
    from app.models.account import get_all_avatars
    knower = payload.get("knower") or ""
    if not isinstance(knower, str) or not knower:
        return
    for avatar in sorted(get_all_avatars()):
        if mind_of(avatar) == knower:
            evaluate(avatar, "secret.learned")


def _found(payload: Dict[str, Any]) -> None:
    """An avatar discovered a hidden room placement: record the ``found`` fact for its mind and evaluate every
    avatar belonging to that mind."""
    from app.core.linked_characters import mind_of
    from app.core.quest_types import FACT_FOUND, found_subject
    from app.models.account import get_all_avatars
    from app.models.quests import add_fact
    character = payload.get("character") or ""
    location_id = payload.get("location_id") or ""
    room_id = payload.get("room_id") or ""
    item_id = payload.get("item_id") or ""
    if not all(isinstance(v, str) and v for v in (character, location_id, room_id, item_id)):
        return
    mind = mind_of(character)
    try:
        add_fact(mind, FACT_FOUND, found_subject(location_id, room_id, item_id))
    except Exception as e:  # noqa: BLE001
        logger.warning("quest engine: the found fact %s -> %s/%s/%s was not written: %s",
                       character, location_id, room_id, item_id, e)
    for avatar in sorted(get_all_avatars()):
        if mind_of(avatar) == mind:
            evaluate(avatar, "item.discovered")


def _handle(event: str, payload: Dict[str, Any]) -> None:
    if event == "world_tick":
        tick()
    elif event == "utterance.heard":
        _heard(payload)
    elif event == "secret.learned":
        _learned(payload)
    elif event == "item.discovered":
        _found(payload)
    elif isinstance(payload.get("character"), str) and payload["character"]:
        evaluate(payload["character"], event)


def _work() -> None:
    while True:
        event, payload = _queue.get()
        try:
            _handle(event, payload)
        except Exception:  # noqa: BLE001 - the worker never dies on one event
            logger.exception("quest engine: handling %s failed", event)
        finally:
            _queue.task_done()


def _enqueue(event: str, payload: Dict[str, Any]) -> None:
    global _worker
    _queue.put((event, dict(payload)))
    with _worker_lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_work, name="quest-engine", daemon=True)
            _worker.start()


def _on_entered_room(**payload: Any) -> None:
    _enqueue("character.entered_room", payload)


def _on_inventory_changed(**payload: Any) -> None:
    _enqueue("inventory.changed", payload)


def _on_utterance_heard(**payload: Any) -> None:
    _enqueue("utterance.heard", payload)


def _on_secret_learned(**payload: Any) -> None:
    _enqueue("secret.learned", payload)


def _on_item_discovered(**payload: Any) -> None:
    _enqueue("item.discovered", payload)


def _on_world_tick(**payload: Any) -> None:
    _enqueue("world_tick", payload)


def register() -> None:
    """Subscribe every event of :data:`SIGNALS` under the tag ``"quest_engine"`` (idempotent: the hook bus keys by
    event + tag)."""
    from app.core import hooks
    hooks.register("character.entered_room", _on_entered_room, tag=HOOK_TAG)
    hooks.register("inventory.changed", _on_inventory_changed, tag=HOOK_TAG)
    hooks.register("utterance.heard", _on_utterance_heard, tag=HOOK_TAG)
    hooks.register("secret.learned", _on_secret_learned, tag=HOOK_TAG)
    hooks.register("item.discovered", _on_item_discovered, tag=HOOK_TAG)
    hooks.register("world_tick", _on_world_tick, tag=HOOK_TAG)


def drain(timeout: float = 5.0) -> bool:
    """Wait until the worker has handled everything queued so far; False on timeout (tests)."""
    with _queue.all_tasks_done:
        return _queue.all_tasks_done.wait_for(lambda: not _queue.unfinished_tasks, timeout)


def _reset_for_tests() -> None:
    """Forget the in-memory state as a fresh process would (smoke only; the queue is drained by the caller)."""
    global _live_count, _missing_type_runs, _missing_object_ids
    with _live_lock:
        _live_count = None
    _missing_type_runs = set()
    _missing_object_ids = set()
