"""Config scope: does a config path belong to the instance or to the world?

The server config is split into two layers. ``instance`` holds what belongs
to the server/host (endpoints, keys, LLM providers, image backends, ports);
``world`` holds what belongs to the simulation of one world (chat rules, NPC
behaviour, calendar). The schema (``app/core/config_schema.py``) declares a
``scope`` on every non-virtual section; a field, sub_array or subsection may
override it, and a skill package does the same in its ``plugin.yaml``.

Resolution rules of ``scope_of(path)``:

1. The first segment is the section. A root that is neither in the schema
   (virtual sections excluded) nor in ``EXTRA_ROOTS`` resolves to ``None``.
2. The deepest explicit ``scope`` wins (field > sub_array/subsection >
   section). A child of a node declared ``mixed`` without its own scope is
   ``world`` — this is how a skill package's subsection defaults (E5).
3. A key the schema does not know inherits the scope of its nearest known
   parent (``image_generation.routing`` -> instance).
4. A node whose subtree holds more than one scope resolves to ``MIXED``.
   ``MIXED`` is never a declaration that sticks: a node declared ``mixed``
   whose children turn out uniform resolves to that one scope. So
   ``scope_of(p) == MIXED`` exactly when ``child_scopes_differ(p)``.

Array indices in a path (``providers.0.api_key``, ``backends[2]``) are
ignored — every item of an array shares the item schema.
"""

import re
from typing import Any, Dict, Optional, Set, Tuple

INSTANCE = "instance"
WORLD = "world"
MIXED = "mixed"

# Config roots outside the schema that still have an owner. llm_task_state is
# read by app/core/llm_task_state.py (persistently disabled LLM tasks) and has
# no settings section of its own.
EXTRA_ROOTS: Dict[str, str] = {"llm_task_state": INSTANCE}

_PSEUDO_FIELD_TYPES = ("note", "group_header")
_INDEX_RE = re.compile(r"\[[^\]]*\]")


def _segments(path: str) -> list:
    """Split a dotted path, dropping array indices (``x[0]``, ``x.3``)."""
    out = []
    for seg in str(path or "").split("."):
        seg = _INDEX_RE.sub("", seg).strip()
        if seg and not seg.isdigit():
            out.append(seg)
    return out


def _children(node: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """The named children of a schema node: fields, sub_arrays, subsections."""
    kids: Dict[str, Dict[str, Any]] = {}
    for name, fdef in (node.get("fields") or {}).items():
        if (not isinstance(fdef, dict) or str(name).startswith("_")
                or fdef.get("type") in _PSEUDO_FIELD_TYPES):
            continue
        kids[name] = fdef
    for kind in ("sub_arrays", "subsections"):
        for name, cdef in (node.get(kind) or {}).items():
            if isinstance(cdef, dict):
                kids[name] = cdef
    return kids


def _inherited(parent_scope: str) -> str:
    """The scope a child without its own declaration gets (rules 2 and 3)."""
    return WORLD if parent_scope == MIXED else parent_scope


def _effective(node: Dict[str, Any], parent_scope: str) -> str:
    return node.get("scope") or _inherited(parent_scope)


def _subtree_scopes(node: Dict[str, Any], scope: str) -> Set[str]:
    """Every concrete scope a value under ``node`` can resolve to.

    Includes the scope an unknown key directly under the node would inherit,
    so a node whose known children all differ from its own scope still counts
    as mixed (its unknown keys stay on the node's side).
    """
    kids = _children(node)
    if not kids:
        return {_inherited(scope)}
    scopes = {_inherited(scope)}
    for child in kids.values():
        scopes |= _subtree_scopes(child, _effective(child, scope))
    return scopes


def _resolve(path: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Walk ``path`` through the schema.

    Returns ``(node, scope)``: the schema node at the path (``None`` once the
    path left the known schema, or for an ``EXTRA_ROOTS`` root) and the scope
    declared or inherited there. ``(None, None)`` for an unknown root.
    """
    parts = _segments(path)
    if not parts:
        return None, None
    root = parts[0]
    if root in EXTRA_ROOTS:
        return None, EXTRA_ROOTS[root]
    # Lazy: get_schema() injects the skill packages' subsections at read time.
    from app.core.config_schema import get_schema
    node = get_schema().get(root)
    if not isinstance(node, dict) or node.get("virtual"):
        return None, None
    scope = node.get("scope")
    if scope not in (INSTANCE, WORLD, MIXED):
        raise ValueError(f"config section {root!r} declares no valid scope: {scope!r}")
    for seg in parts[1:]:
        child = _children(node).get(seg)
        if child is None:
            return None, _inherited(scope)
        scope = _effective(child, scope)
        node = child
    return node, scope


def child_scopes_differ(path: str) -> bool:
    """True when the values under ``path`` belong to more than one scope.

    The helper for splitting a config recursively: where it is True, descend
    into the node's keys; where it is False, the whole subtree goes to
    ``scope_of(path)``. False for an unknown root and for anything outside
    the known schema (an unknown key inherits one scope as a whole).
    """
    node, scope = _resolve(path)
    if node is None or scope is None:
        return False
    return len(_subtree_scopes(node, scope)) > 1


def scope_of(path: str) -> Optional[str]:
    """``INSTANCE``, ``WORLD`` or ``MIXED`` for a dotted config path.

    ``None`` for an unknown root (rule 1). See the module docstring for the
    rules.
    """
    node, scope = _resolve(path)
    if scope is None:
        return None
    if node is None:
        return scope
    scopes = _subtree_scopes(node, scope)
    if len(scopes) > 1:
        return MIXED
    return next(iter(scopes))
