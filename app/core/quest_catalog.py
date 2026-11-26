"""The quest type catalog — the types a quest expression or effect list is made of, on the provider registry.

A quest template's conditions (steps, start condition) and prerequisites are EXPRESSIONS (plan D7)::

    {}                                   # true
    {"type": <type id>, "params": {...}} # a leaf: one registered type
    {"all": [expr, ...]}
    {"any": [expr, ...]}
    {"not": expr}

A template's ``setup_effects``, ``steps[i].on_done`` and ``rewards`` are EFFECT LISTS (stage 2, plan D2), each entry::

    {"key": str, "type": <type id>, "params": {...}, "permanent": bool}  # permanent defaults to False

A TYPE is a :class:``QuestType`` of one of three kinds (``KINDS``: ``condition``, ``prerequisite``, ``effect``). The
core names no package (R1): a package (and the core's own built-ins, ``app/core/quest_types.py``) registers ONE
contributor per owner with :func:``register`` — a function that answers the list of ALL that owner's types (the
provider registry keeps one contributor per (capability, owner); the pattern of ``app/core/view_postprocess.py``). The
loader's ``unregister_owned_providers(<package id>)`` removes them; :func:``types`` is rebuilt from the registry on
EVERY call (the provider registry has no change counter to cache against), so an unloaded package's types are gone at
once and a leaf naming one evaluates as "type not registered" (unavailable).

PARAMETERS (D5) are a list of dicts in the ``config_schema`` field vocabulary plus ``key``:
``key, type, label, description, default, min, max, step, choices, choice_labels, required``; ``type`` is one of
:data:``PARAM_TYPES``. A ``role`` field holds a role KEY of the template (never a world entity id) and may restrict the
role's kind with ``role_kinds``. A ``target`` field (stage 2, D4) holds either a role key (its kind in ``role_kinds``)
or a reachable effect key (its type's ``object_kind`` in ``object_kinds``), checked against a :class:``Scope`` built
for that position. A ``text`` parameter accepts ``{role_key}`` placeholders unless its spec sets
``"placeholders": False`` (for JSON-valued text parameters). :func:``check_expression`` and :func:``check_effects`` do
the generic checks; a type's own ``validate`` runs only on a leaf that passed them, with ``bindings=None`` at template
time (D4).

EVALUATION is three-state (``ConditionResult(available, passed, reason)`` of ``app.core.activity_engine``): unavailable
is contagious through ``all`` / ``any`` / ``not``, which evaluate EVERY child (the strict rule of
``evaluate_condition_strict``). A type that is not registered, has no ``evaluate``, raises or answers something that is
not a ``ConditionResult`` is unavailable — never passed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

from app.core.activity_engine import ConditionIssue, ConditionResult
from app.core.log import get_logger

logger = get_logger("quest_catalog")

#: The hook capability whose contributors answer the quest types of one owner.
CAPABILITY = "quest.types"
KINDS = ("condition", "prerequisite", "effect")
ROLE_KINDS = ("character", "location", "room", "item")
PARAM_TYPES = ("str", "text", "int", "float", "bool", "select", "role", "target")

EFFECT_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
MAX_EFFECTS = 20
MAX_CREATE_PROP = 3
#: The core's own built-in effect type id (D2 per-template limit).
CREATE_PROP_TYPE = "create_prop"
EFFECT_ENTRY_KEYS = ("key", "type", "params", "permanent")

#: The payload key of each kind in :func:``catalog_payload``.
_PAYLOAD_KEYS = {"condition": "conditions", "prerequisite": "prerequisites", "effect": "effects"}
_GROUPS = ("all", "any")
#: How deep groups may nest. :func:``check_expression`` reports a deeper node as a ``shape`` issue and goes no
#: further, so such an expression never becomes ready and the unbounded walkers (walk, evaluate) never see it.
MAX_DEPTH = 16
#: Duplicate ids already logged: the catalog is rebuilt on every call, the warning is written once per id.
_logged_duplicates: set[str] = set()


@dataclass(frozen=True)
class QuestType:
    id: str
    kind: str                                   # one of KINDS
    label: str
    description: str                            # one line, also for the later LLM prompt
    params: tuple[dict, ...] = ()               # D5
    signals: tuple[str, ...] = ()
    validate: Callable[[dict, dict | None], list[ConditionIssue]] | None = None
    evaluate: Callable[[dict, "QuestContext"], ConditionResult] | None = None
    #: True for a type that can only be read once the run has opened (it counts from ``started_game_ts``): it is
    #: refused in a start condition, where a hidden run has not opened yet and the type would stay unavailable.
    needs_open_run: bool = False
    #: An effect type's apply runs on the effects worker (a later task).
    apply: Callable[[dict, "EffectContext"], list["CreatedObject"]] | None = None
    #: The kind of the first object the effect records, the one a target param resolves to ("" = it records no object).
    object_kind: str = ""


@dataclass(frozen=True)
class Scope:
    """Role keys and effect keys reachable at one template position (D4).

    ``roles`` maps each role key to its role kind; ``objects`` maps each reachable effect key to its type's
    ``object_kind`` (``""`` for an effect that records no object or has an unknown type); ``later`` holds effect keys
    defined by the template that are not reachable at this position, so a ``target`` naming one reports
    ``not_yet_created`` instead of ``unknown_target``.
    """
    roles: Dict[str, str]
    objects: Dict[str, str]
    later: frozenset = frozenset()


# --- Registry -------------------------------------------------------------------------

def register(owner: str, contributor: Callable[[], List[QuestType]]) -> None:
    """Register the contributor of ``owner`` (it answers ALL of the owner's types). A second call by the same owner
    replaces the first; ``hooks.unregister_owned_providers(owner)`` removes it."""
    from app.core import hooks
    hooks.register_provider(CAPABILITY, contributor, owner=owner, multiple=True)


def types(*, strict: bool = False) -> Dict[str, QuestType]:
    """id -> type of every type registered now, rebuilt on every call (no cache). A contributor that raises is
    skipped (logged) — with ``strict=True`` it re-raises instead, for a caller that must not read a missing type
    as "not registered" (the tick's reference check: a hiccup is no evidence that a package is gone); an entry that is not a :class:``QuestType`` with an id and a known kind is dropped (logged); of
    two types with the same id the first registered wins (logged once per id)."""
    from app.core import hooks
    out: Dict[str, QuestType] = {}
    for fn in hooks.get_providers(CAPABILITY):
        try:
            answer = fn()
        except Exception:  # noqa: BLE001 — one package never hides the others
            if strict:
                raise
            logger.exception("A %s contributor failed", CAPABILITY)
            continue
        for t in (answer if isinstance(answer, (list, tuple)) else [answer]):
            if not isinstance(t, QuestType) or not t.id or t.kind not in KINDS:
                logger.warning("A %s contributor answered an invalid type: %r", CAPABILITY, t)
                continue
            if t.id in out:
                if t.id not in _logged_duplicates:
                    _logged_duplicates.add(t.id)
                    logger.warning("Quest type id %r registered twice — the first registration is kept", t.id)
                continue
            out[t.id] = t
    return out


def get(type_id: str) -> Optional[QuestType]:
    return types().get(type_id)


def public_descriptor(t: QuestType) -> Dict[str, Any]:
    """The JSON-safe part of a type (no callable): the admin form and, later, the LLM prompt read it."""
    return {"id": t.id, "kind": t.kind, "label": t.label, "description": t.description,
            "params": [{k: v for k, v in dict(p).items() if not callable(v)} for p in t.params],
            "signals": list(t.signals), "needs_open_run": bool(t.needs_open_run),
            "object_kind": t.object_kind}


def catalog_payload() -> Dict[str, List[Dict[str, Any]]]:
    """``{"conditions": [...], "prerequisites": [...], "effects": [...]}`` of public descriptors, sorted by label."""
    out: Dict[str, List[Dict[str, Any]]] = {key: [] for key in _PAYLOAD_KEYS.values()}
    for t in sorted(types().values(), key=lambda t: (t.label.lower(), t.id)):
        out[_PAYLOAD_KEYS[t.kind]].append(public_descriptor(t))
    return out


# --- Expressions --------------------------------------------------------------------------

def _is_leaf(expr: Any) -> bool:
    return isinstance(expr, dict) and "type" in expr


def _shape_error(expr: Any) -> str:
    """"" when ``expr`` has a valid shape AT ITS OWN LEVEL (children are checked by the caller), else why not."""
    if not isinstance(expr, dict):
        return "An expression must be an object"
    if not expr:
        return ""
    keys = set(expr)
    if "type" in keys:
        if not keys <= {"type", "params"}:
            return f"A condition may only have 'type' and 'params', not {sorted(keys - {'type', 'params'})}"
        if not isinstance(expr["type"], str) or not expr["type"]:
            return "'type' must be a type id"
        if not isinstance(expr.get("params", {}), dict):
            return "'params' must be an object"
        return ""
    if len(keys) != 1 or not keys <= {"all", "any", "not"}:
        return "An expression is {}, a condition, or exactly one of 'all', 'any', 'not'"
    (op,) = keys
    if op in _GROUPS:
        if not isinstance(expr[op], list) or not expr[op]:
            return f"'{op}' must be a non-empty list of expressions"
        return ""
    return "" if isinstance(expr["not"], dict) else "'not' must be an expression"


def _children(expr: dict) -> Iterator[Tuple[str, Any]]:
    """(relative path, child) of a well-shaped group expression."""
    for op in _GROUPS:
        if op in expr:
            for i, child in enumerate(expr[op]):
                yield f".{op}.{i}", child
    if "not" in expr:
        yield ".not", expr["not"]


def walk(expr: dict) -> Iterator[Tuple[str, dict]]:
    """(path, leaf) for every ``{"type", "params"}`` leaf; paths relative to ``expr`` ("" = the root itself, D7).
    Malformed parts are skipped (:func:``check_expression`` reports them)."""
    def rec(path: str, node: Any) -> Iterator[Tuple[str, dict]]:
        if _shape_error(node) or not node:
            return
        if _is_leaf(node):
            yield path, node
            return
        for sub, child in _children(node):
            yield from rec(path + sub, child)
    yield from rec("", expr)


def _with_defaults(t: QuestType, params: dict) -> dict:
    """The leaf's params over the declared defaults (a key the author left out takes its default)."""
    merged = {p["key"]: p.get("default") for p in t.params if "key" in p and p.get("default") is not None}
    # An absent value (None / blank, as the check reads it) never hides the default it was accepted for.
    merged.update({k: v for k, v in (params or {}).items() if not _absent(v)})
    return merged


def _issue(path: str, code: str, message: str) -> Dict[str, str]:
    return {"path": path, "code": code, "message": message}


def _absent(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _check_param(path: str, spec: dict, value: Any, scope: Scope) -> Optional[Dict[str, str]]:
    """The generic check of one present parameter value against its spec (D5); None = fine."""
    key, ptype = spec.get("key"), spec.get("type", "str")
    label = spec.get("label") or key
    if ptype in ("str", "text"):
        if not isinstance(value, str):
            return _issue(path, "bad_param", f"{label} must be text")
    elif ptype in ("int", "float"):
        number_ok = isinstance(value, int) if ptype == "int" else isinstance(value, (int, float))
        if isinstance(value, bool) or not number_ok:
            return _issue(path, "bad_param", f"{label} must be {'a whole number' if ptype == 'int' else 'a number'}")
        if spec.get("min") is not None and value < spec["min"]:
            return _issue(path, "bad_param", f"{label} must be at least {spec['min']}")
        if spec.get("max") is not None and value > spec["max"]:
            return _issue(path, "bad_param", f"{label} must be at most {spec['max']}")
    elif ptype == "bool":
        if not isinstance(value, bool):
            return _issue(path, "bad_param", f"{label} must be yes or no")
    elif ptype == "select":
        if value not in (spec.get("choices") or []):
            return _issue(path, "bad_param", f"{label} must be one of {list(spec.get('choices') or [])}")
    elif ptype == "role":
        if not isinstance(value, str) or value not in scope.roles:
            return _issue(path, "unknown_role", f"{label}: '{value}' is not a role of this quest")
        allowed = spec.get("role_kinds") or []
        if allowed and scope.roles[value] not in allowed:
            return _issue(path, "wrong_role_kind",
                          f"{label}: role '{value}' is a {scope.roles[value]}, expected {' or '.join(allowed)}")
    elif ptype == "target":
        if not isinstance(value, str):
            return _issue(path, "bad_param", f"{label} must be a key")
        if value in scope.roles:
            allowed_roles = spec.get("role_kinds") or []
            if scope.roles[value] not in allowed_roles:
                expected = " or ".join(allowed_roles) if allowed_roles else "none"
                return _issue(path, "wrong_kind",
                              f"{label}: role '{value}' is a {scope.roles[value]}, expected {expected}")
        elif value in scope.objects:
            allowed_objects = spec.get("object_kinds") or []
            if scope.objects[value] not in allowed_objects:
                actual = scope.objects[value] or "no object"
                expected = " or ".join(allowed_objects) if allowed_objects else "none"
                return _issue(path, "wrong_kind",
                              f"{label}: '{value}' is {actual}, expected {expected}")
        elif value in scope.later:
            return _issue(path, "not_yet_created", f"{label}: '{value}' is created only later")
        else:
            return _issue(path, "unknown_target",
                          f"{label}: '{value}' is neither a role nor an effect key of this quest")
    else:
        return _issue(path, "bad_param", f"{label}: the type declares an unknown parameter type '{ptype}'")
    return None


def _check_leaf(path: str, leaf: dict, scope: Scope, allowed_kinds: Tuple[str, ...],
                known: Dict[str, QuestType]) -> List[Dict[str, str]]:
    t = known.get(leaf["type"])
    if t is None:
        return [_issue(path + ".type", "unknown_type", f"Unknown {allowed_kinds[0]} type '{leaf['type']}'")]
    if t.kind not in allowed_kinds:
        return [_issue(path + ".type", "wrong_kind",
                       f"'{t.label}' is a {t.kind}, not allowed here (allowed: {', '.join(allowed_kinds)})")]
    params = leaf.get("params") or {}
    issues: List[Dict[str, str]] = []
    declared = {p.get("key") for p in t.params}
    for key in sorted(set(params) - declared):
        issues.append(_issue(f"{path}.params.{key}", "bad_param", f"'{t.label}' has no parameter '{key}'"))
    for spec in t.params:
        key = spec.get("key")
        value = params.get(key)
        if _absent(value):
            if spec.get("required") and spec.get("default") is None:
                issues.append(_issue(f"{path}.params.{key}", "missing_param",
                                     f"{spec.get('label') or key} is required"))
            continue
        bad = _check_param(f"{path}.params.{key}", spec, value, scope)
        if bad:
            issues.append(bad)
    if issues or t.validate is None:
        return issues
    try:
        own = t.validate(_with_defaults(t, params), None) or []
        return [_issue(path + ".type", str(i.code), str(i.message)) for i in own]
    except Exception as e:  # noqa: BLE001 — a package's validator (or its answer) never breaks the check
        logger.exception("validate of quest type %r failed", t.id)
        return [_issue(path + ".type", "bad_param", f"'{t.label}' could not check its parameters: {e}")]


def check_expression(expr: dict, scope: Scope, *, allowed_kinds: Tuple[str, ...]) -> List[Dict[str, str]]:
    """Every issue of ``expr`` as ``{"path", "code", "message"}``; paths relative to ``expr`` (D7: "" = the root, the
    caller prefixes its own position). ``scope`` names the roles and reachable effect objects at this position;
    ``allowed_kinds`` the type kinds this position accepts. Codes: shape, unknown_type, wrong_kind, missing_param,
    bad_param, unknown_role, wrong_role_kind, unknown_target, not_yet_created — plus whatever code a type's own
    ``validate`` names (reported at ``.type``)."""
    known = types()  # one catalog snapshot for the whole check
    issues: List[Dict[str, str]] = []

    def rec(path: str, node: Any, depth: int) -> None:
        if depth > MAX_DEPTH:
            issues.append(_issue(path, "shape", f"Expressions nest at most {MAX_DEPTH} levels deep"))
            return
        err = _shape_error(node)
        if err:
            issues.append(_issue(path, "shape", err))
            return
        if not node:
            return
        if _is_leaf(node):
            issues.extend(_check_leaf(path, node, scope, tuple(allowed_kinds), known))
            return
        for sub, child in _children(node):
            rec(path + sub, child, depth + 1)

    rec("", expr, 0)
    return issues


def check_effects(effects: Any, scope_for: Callable[[int], Scope], *, path: str, reward: bool,
                  props_before: int = 0) -> List[Dict[str, str]]:
    """Every issue of one effect list (D2), with absolute paths built from ``path`` (e.g. ``setup_effects.1.key``).
    ``scope_for(i)`` answers the reachable :class:`Scope` of entry ``i``; ``reward=True`` refuses ``permanent=False``;
    ``props_before`` is how many ``create_prop`` entries earlier lists of the same template already used."""
    if not isinstance(effects, list):
        return [_issue(path, "shape", "An effect list must be a list")]
    known = types()  # one catalog snapshot for the whole check
    issues: List[Dict[str, str]] = []
    if len(effects) > MAX_EFFECTS:
        issues.append(_issue(path, "too_many", f"At most {MAX_EFFECTS} effects per list"))
    allowed_entry_keys = set(EFFECT_ENTRY_KEYS)
    seen_keys: set[str] = set()
    prop_count = props_before
    for i, entry in enumerate(effects):
        p = f"{path}.{i}"
        if not isinstance(entry, dict):
            issues.append(_issue(p, "shape", "An effect must be an object"))
            continue
        if not set(entry) <= allowed_entry_keys:
            issues.append(_issue(p, "shape", "An effect may only have key, type, params, permanent"))
            continue
        if "params" in entry and not isinstance(entry["params"], dict):
            issues.append(_issue(f"{p}.params", "shape", "'params' must be an object"))
            continue
        if not isinstance(entry.get("type"), str) or not entry["type"]:
            issues.append(_issue(f"{p}.type", "shape", "'type' must be a type id"))
            continue
        scope = scope_for(i)
        key = entry.get("key")
        if _absent(key):
            issues.append(_issue(f"{p}.key", "required", "An effect needs a key"))
        elif not isinstance(key, str) or not EFFECT_KEY_PATTERN.match(key):
            issues.append(_issue(f"{p}.key", "bad_key",
                                 "A key is a-z, 0-9 and _, starting with a letter, at most 40 characters"))
        elif key in scope.roles:
            issues.append(_issue(f"{p}.key", "duplicate", f"Effect key '{key}' is already used by a role"))
        elif key in seen_keys:
            issues.append(_issue(f"{p}.key", "duplicate", f"Effect key '{key}' is used twice"))
        else:
            seen_keys.add(key)
        issues.extend(_check_leaf(p, {"type": entry["type"], "params": entry.get("params") or {}},
                                  scope, ("effect",), known))
        if entry["type"] == CREATE_PROP_TYPE:
            prop_count += 1
            if prop_count > MAX_CREATE_PROP:
                issues.append(_issue(f"{p}.type", "too_many",
                                     f"At most {MAX_CREATE_PROP} {CREATE_PROP_TYPE} effects per quest"))
        if "permanent" in entry:
            perm = entry["permanent"]
            if not isinstance(perm, bool):
                issues.append(_issue(f"{p}.permanent", "bad_value", "'permanent' must be yes or no"))
            elif reward and perm is False:
                issues.append(_issue(f"{p}.permanent", "not_allowed_here", "A reward is always permanent"))
    return issues


def evaluate_expression(expr: dict, ctx: "QuestContext") -> ConditionResult:
    """Three-state value of ``expr`` (see the module docstring); never raises. One catalog snapshot per call."""
    return _evaluate(expr, ctx, types())


def _evaluate(expr: Any, ctx: "QuestContext", known: Dict[str, QuestType]) -> ConditionResult:
    if _shape_error(expr):
        return ConditionResult(False, False, "Malformed expression")
    if not expr:
        return ConditionResult(True, True, "")
    if _is_leaf(expr):
        return _evaluate_leaf(expr, ctx, known)
    if "not" in expr:
        inner = _evaluate(expr["not"], ctx, known)
        if not inner.available:
            return inner
        return ConditionResult(True, not inner.passed, "" if not inner.passed else "not: the condition holds")
    op = "all" if "all" in expr else "any"
    results = [_evaluate(child, ctx, known) for child in expr[op]]  # EVERY child, no short cut
    missing = [r for r in results if not r.available]
    if missing:
        return ConditionResult(False, False, "; ".join(r.reason for r in missing if r.reason))
    passed = all(r.passed for r in results) if op == "all" else any(r.passed for r in results)
    reason = "" if passed else "; ".join(r.reason for r in results if not r.passed and r.reason)
    return ConditionResult(True, passed, reason)


def _evaluate_leaf(leaf: dict, ctx: "QuestContext", known: Dict[str, QuestType]) -> ConditionResult:
    type_id = leaf["type"]
    t = known.get(type_id)
    if t is None:
        return ConditionResult(False, False, f"Quest type '{type_id}' is not registered")
    if t.evaluate is None:
        return ConditionResult(False, False, f"Quest type '{type_id}' cannot be evaluated")
    try:
        result = t.evaluate(_with_defaults(t, leaf.get("params") or {}), ctx)
    except Exception as e:  # noqa: BLE001 — a failing type is unavailable, never passed
        logger.exception("evaluate of quest type %r failed", type_id)
        return ConditionResult(False, False, f"Quest type '{type_id}' failed: {e}")
    if not isinstance(result, ConditionResult):
        logger.warning("evaluate of quest type %r answered %r, not a ConditionResult", type_id, result)
        return ConditionResult(False, False, f"Quest type '{type_id}' answered no result")
    return result


def signals_of(expr: dict) -> set[str]:
    """The union of the signals every registered leaf type of ``expr`` declares (unknown types add none)."""
    known = types()
    out: set[str] = set()
    for _path, leaf in walk(expr):
        t = known.get(leaf["type"])
        if t is not None:
            out.update(t.signals)
    return out
