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

The skill packages' subsections are part of the schema view under
``skills.subsections``. Installed manifest metadata remains available before
and after discovery (``loader.manifest_config_schemas()``, imports no package
code), even for disabled packages. Active registry schemas overlay that
inventory — dormant endpoint settings therefore keep their instance scope.

On top of the scope rules sit the two operations the config layers are
written with: ``prune`` keeps only what differs from what ships
(``shipped_default``), ``split_by_scope`` sorts a config into its instance
and its world part.
"""

import copy
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
    """Split a dotted path, dropping array indices (``x[0]``, ``x.3``).

    A digit-only segment is ALWAYS taken as a list index and dropped — a
    config dict key made of digits cannot be addressed by a dotted path.
    """
    out = []
    for seg in str(path or "").split("."):
        seg = _INDEX_RE.sub("", seg).strip()
        if seg and not seg.isdigit():
            out.append(seg)
    return out


# (key, view): the schema view of the current discovery state. Rebuilt when
# discovery runs or the registry changes, never frozen on the pre-discovery
# view.
_view_cache: Tuple[Any, Optional[Dict[str, Any]]] = (None, None)


def _schema_view() -> Dict[str, Any]:
    """The schema with the skill packages' subsections under ``skills``.

    Installed manifests provide side-effect-free metadata even for packages
    disabled in this world. Active registry subsections overlay that inventory
    after discovery. Read-only: shared with the schema module, never mutate it.
    """
    global _view_cache
    # Lazy: the app.plugins package pulls in the loader and app.skills.base.
    from app.plugins import loader, registry
    discovered = loader.is_discovered()
    key = (True, registry.generation()) if discovered else (False,)
    cached_key, view = _view_cache
    if view is not None and cached_key == key:
        return view
    from app.core.config_schema import SECTIONS
    subs = loader.manifest_config_schemas()
    if discovered:
        subs.update(registry.config_subsections())
    view = dict(SECTIONS)
    if subs:
        skills = dict(view.get("skills") or {})
        # Package subsections win on collision, as in get_schema().
        skills["subsections"] = {**(skills.get("subsections") or {}), **subs}
        view["skills"] = skills
    _view_cache = (key, view)
    return view


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
    return _resolve_parts(_segments(path))


def _resolve_parts(parts) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """``_resolve`` on already split keys (a dict key may contain a dot)."""
    if not parts:
        return None, None
    root = parts[0]
    if root in EXTRA_ROOTS:
        return None, EXTRA_ROOTS[root]
    node = _schema_view().get(root)
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
    return _scope_at(*_resolve(path))


def _scope_at(node: Optional[Dict[str, Any]], scope: Optional[str]) -> Optional[str]:
    if scope is None:
        return None
    if node is None:
        return scope
    scopes = _subtree_scopes(node, scope)
    if len(scopes) > 1:
        return MIXED
    return next(iter(scopes))


# ---------------------------------------------------------------------------
# Shipped defaults, prune, split
# ---------------------------------------------------------------------------

_DROP = object()


def _use_case_seed() -> Dict[str, Any]:
    """What ``config._seed_default_use_cases`` writes for one shipped use case."""
    from app.core.config import _PROMPT_STYLE_FAMILIES
    return {
        "styles": {fam: {"prompt_style": "", "prompt_negative": "",
                         "prompt_instruction": ""} for fam in _PROMPT_STYLE_FAMILIES},
        "llm_compose": False,
    }


def _list_default(parts: Tuple[str, ...]) -> Tuple[bool, Any]:
    """The four list defaults that do not come from the schema."""
    if parts == ("providers",):
        from app.core.config import _DEFAULT_PROVIDERS
        return True, copy.deepcopy(_DEFAULT_PROVIDERS)
    if parts == ("content_marketplace", "catalogs"):
        from app.core.config import _DEFAULT_MARKETPLACE_CATALOGS
        return True, copy.deepcopy(_DEFAULT_MARKETPLACE_CATALOGS)
    if parts == ("image_generation", "backends"):
        from app.core.config import _default_mesh_backend_entries
        return True, _default_mesh_backend_entries()
    if parts == ("game_seasons",):
        from app.core.game_time import default_seasons_config
        return True, default_seasons_config()
    return False, None


def _fields_node(parts: Tuple[str, ...]) -> Optional[Dict[str, Any]]:
    """The schema section or subsection at ``parts`` — a node whose keys are
    fields. ``None`` for anything else: an array section, a sub_array, a key
    the schema does not know (page-written data such as ``routing``)."""
    if not parts:
        return None
    node = _schema_view().get(parts[0])
    if not isinstance(node, dict) or node.get("virtual") or node.get("is_array"):
        return None
    for seg in parts[1:]:
        node = (node.get("subsections") or {}).get(seg)
        if not isinstance(node, dict):
            return None
    return node


def _is_pseudo_name(name: Any) -> bool:
    return isinstance(name, str) and name.startswith("_")


def _shipped_default_parts(parts: Tuple[str, ...]) -> Tuple[bool, Any]:
    if not parts or any(not isinstance(p, str) or not p for p in parts):
        return False, None
    has, value = _list_default(parts)
    if has:
        return True, value
    if len(parts) == 3 and parts[:2] == ("image_generation", "use_cases"):
        from app.core.config import _DEFAULT_IMAGE_USE_CASES
        if parts[2] in _DEFAULT_IMAGE_USE_CASES:
            return True, _use_case_seed()
        return False, None
    if len(parts) < 2:
        return False, None
    node = _fields_node(parts[:-1])
    name = parts[-1]
    if node is None or _is_pseudo_name(name):
        return False, None
    fdef = (node.get("fields") or {}).get(name)
    if (not isinstance(fdef, dict) or fdef.get("type") in _PSEUDO_FIELD_TYPES
            or "default" not in fdef):
        return False, None
    return True, copy.deepcopy(fdef["default"])


def shipped_default(path: str) -> Tuple[bool, Any]:
    """``(True, value)`` when the config value at ``path`` has a shipped
    default, else ``(False, None)``. The value is a copy.

    Sources, and only these:

    - the schema ``default`` of a field — of a section or of a subsection,
      skill packages' subsections included (from the manifests before
      discovery). Pseudo fields (``_`` name, ``note``/``group_header``) and
      fields inside array items never have one;
    - the four list defaults outside the schema: ``providers`` (the example
      seed), ``content_marketplace.catalogs``,
      ``image_generation.backends`` (the mesh seed), ``game_seasons``;
    - ``image_generation.use_cases.<uc>`` for a SHIPPED use case: the empty
      seed structure ``config._seed_default_use_cases`` writes. A custom use
      case has none — the seeding would not bring it back.

    A path naming a list entry (``game_seasons.0``, ``providers[1].name``)
    has no default: a list is one value.
    """
    parts = [p.strip() for p in str(path or "").split(".")]
    if any(_INDEX_RE.search(p) or p.isdigit() for p in parts):
        return False, None
    return _shipped_default_parts(tuple(parts))


def _same(a: Any, b: Any) -> bool:
    """Equality that never matches a bool against a number (``1 != True``)."""
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    if isinstance(a, (dict, list)) or isinstance(b, (dict, list)):
        return False
    return a == b


def _prune_value(value: Any, parts: Tuple[str, ...]) -> Any:
    if isinstance(value, dict) and not value:
        return _DROP
    has, default = _shipped_default_parts(parts)
    if has:
        # A value with a shipped default is ONE value: dropped when equal,
        # kept whole otherwise (a changed use case keeps all its keys).
        return _DROP if _same(value, default) else copy.deepcopy(value)
    if not isinstance(value, dict):
        # Scalars without a default and every list stay — nothing inside a
        # list entry is pruned.
        return copy.deepcopy(value)
    drop_pseudo = _fields_node(parts) is not None
    out: Dict[str, Any] = {}
    for key, child in value.items():
        if drop_pseudo and _is_pseudo_name(key):
            continue
        kept = _prune_value(child, parts + (key,))
        if kept is not _DROP:
            out[key] = kept
    return out if out else _DROP


def prune(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """A copy of ``cfg`` without what ships anyway.

    Removes values equal to their ``shipped_default`` (a bool default only
    matches a bool), pseudo fields (``_`` keys of a schema section or
    subsection) and empty dicts at any depth. Keeps ``[]`` (an emptied list
    is a deviation), every list as one value — nothing inside a list entry is
    touched — and ``_`` keys of page-written data such as ``routing``.
    Root keys are never pseudo fields; an unknown root is kept unless it is
    empty.
    """
    out: Dict[str, Any] = {}
    for root, value in (cfg or {}).items():
        kept = _prune_value(value, (root,))
        if kept is not _DROP:
            out[root] = kept
    return out


def _put(target: Dict[str, Any], parts: Tuple[str, ...], value: Any) -> None:
    for seg in parts[:-1]:
        target = target.setdefault(seg, {})
    target[parts[-1]] = value


def _split_into(parts: Tuple[str, ...], value: Any, instance: Dict[str, Any],
                world: Dict[str, Any]) -> None:
    node, declared = _resolve_parts(list(parts))
    scope = _scope_at(node, declared)
    if scope == MIXED and isinstance(value, dict):
        for key, child in value.items():
            _split_into(parts + (key,), child, instance, world)
        return
    if scope == MIXED:
        # Not a dict where the schema expects children: it stays with the
        # scope an unknown key directly under the node would get.
        scope = _inherited(declared)
    _put(instance if scope == INSTANCE else world, parts, copy.deepcopy(value))


def split_by_scope(cfg: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any], list]:
    """Sort a config into ``(instance_part, world_part, unknown_roots)``.

    Recursive: a node whose scope is ``MIXED`` is split per child, at any
    depth (``skills.searx.url`` instance, ``skills.searx.enabled`` world); a
    node of one scope moves as a whole. Unknown roots (rule 1) go to neither
    part and are listed in input order. Both parts are copies. A ``MIXED``
    node with no keys (``skills: {}``) lands in neither part — pruning would
    drop it anyway.
    """
    instance: Dict[str, Any] = {}
    world: Dict[str, Any] = {}
    unknown: list = []
    for root, value in (cfg or {}).items():
        if _resolve_parts([root])[1] is None:
            unknown.append(root)
            continue
        _split_into((root,), value, instance, world)
    return instance, world, unknown


# ---------------------------------------------------------------------------
# Per-scope views for the two admin surfaces
# ---------------------------------------------------------------------------

_LAYOUT_TYPES = ("group_header", "note")
_ACTION_TYPES = ("button", "image_preview")


def _is_data_field(name: str, fdef: Any) -> bool:
    return (isinstance(fdef, dict) and not _is_pseudo_name(name)
            and fdef.get("type") not in _LAYOUT_TYPES + _ACTION_TYPES)


def _keeps(path: str, scope: str) -> bool:
    got = scope_of(path)
    return got == scope or got == MIXED


def _filter_fields(fields: Dict[str, Any], prefix: str, declared: str,
                   scope: str) -> Dict[str, Any]:
    """The fields of one node that belong to ``scope`` — layout fields
    follow the data fields around them (see Task 1 rules)."""
    items = list(fields.items())
    kept_data = {name for name, fdef in items
                 if _is_data_field(name, fdef) and _keeps(f"{prefix}.{name}", scope)}
    out: Dict[str, Any] = {}
    for i, (name, fdef) in enumerate(items):
        if not isinstance(fdef, dict):
            continue
        ftype = fdef.get("type")
        if _is_data_field(name, fdef):
            if name in kept_data:
                out[name] = copy.deepcopy(fdef)
        elif ftype == "group_header":
            for nxt, ndef in items[i + 1:]:
                if isinstance(ndef, dict) and ndef.get("type") == "group_header":
                    break
                if nxt in kept_data:
                    out[name] = copy.deepcopy(fdef)
                    break
        elif ftype == "note":
            prev = next((p for p, pdef in reversed(items[:i])
                         if _is_data_field(p, pdef)), None)
            if prev is not None and prev in kept_data:
                out[name] = copy.deepcopy(fdef)
        elif _inherited(declared) == scope:   # button, image_preview, _ names
            out[name] = copy.deepcopy(fdef)
    return out


def _filter_node(node: Dict[str, Any], path: str, declared: str,
                 scope: str) -> Dict[str, Any]:
    """A filtered copy of one section/subsection node (MIXED or matching)."""
    out = {k: copy.deepcopy(v) for k, v in node.items()
           if k not in ("fields", "subsections", "sub_arrays", "pages")}
    if node.get("fields"):
        fields = _filter_fields(node["fields"], path, declared, scope)
        if fields:
            out["fields"] = fields
    for kind in ("subsections", "sub_arrays"):
        kept = {}
        for name, child in (node.get(kind) or {}).items():
            if not isinstance(child, dict):
                continue
            cpath = f"{path}.{name}"
            got = scope_of(cpath)
            if got == scope:
                kept[name] = copy.deepcopy(child)
            elif got == MIXED:
                sub = _filter_node(child, cpath, child.get("scope") or _inherited(declared), scope)
                if sub.get("fields") or sub.get("subsections") or sub.get("sub_arrays") or sub.get("pages"):
                    kept[name] = sub
        if kept:
            out[kind] = kept
    pages = []
    for page in node.get("pages") or []:
        p = copy.deepcopy(page)
        p["fields"] = [f for f in page.get("fields") or [] if f in (out.get("fields") or {})]
        p["sub_arrays"] = [a for a in page.get("sub_arrays") or [] if a in (out.get("sub_arrays") or {})]
        if p.get("custom"):
            if declared == scope:
                pages.append(p)
        elif p["fields"] or p["sub_arrays"]:
            pages.append(p)
    if pages:
        out["pages"] = pages
    return out


def schema_for(scope: str) -> Dict[str, Any]:
    """The schema view restricted to ``scope`` ("instance" or "world").

    A section of that scope stays whole, a section of the other scope goes,
    a MIXED section is filtered down to its ``scope`` part (fields,
    subsections, sub_arrays, pages). The virtual sections (``llm_simple``)
    are UI pages of the instance's LLM routing and stay in the instance view
    only. A deep copy — callers may mutate it.
    """
    if scope not in (INSTANCE, WORLD):
        raise ValueError(f"scope must be {INSTANCE!r} or {WORLD!r}: {scope!r}")
    out: Dict[str, Any] = {}
    for root, node in _schema_view().items():
        if not isinstance(node, dict):
            continue
        if node.get("virtual"):
            if scope == INSTANCE:
                out[root] = copy.deepcopy(node)
            continue
        got = scope_of(root)
        if got == scope:
            out[root] = copy.deepcopy(node)
        elif got == MIXED:
            sub = _filter_node(node, root, node["scope"], scope)
            if sub.get("fields") or sub.get("subsections") or sub.get("sub_arrays") or sub.get("pages"):
                out[root] = sub
    return out


def _tree_fields(node: Dict[str, Any], parts: Tuple[str, ...],
                 into: Dict[str, Any]) -> None:
    for name, fdef in (node.get("fields") or {}).items():
        if not _is_data_field(name, fdef):
            continue
        has, value = _shipped_default_parts(parts + (name,))
        if has:
            into[name] = value
    for name, child in (node.get("subsections") or {}).items():
        sub: Dict[str, Any] = {}
        _tree_fields(child, parts + (name,), sub)
        if sub:
            into[name] = sub
    for name in (node.get("sub_arrays") or {}):
        has, value = _shipped_default_parts(parts + (name,))
        if has:
            into[name] = value


def shipped_tree(scope: str) -> Dict[str, Any]:
    """What ships for ``scope``, as one config-shaped dict.

    Built only from ``shipped_default`` (schema defaults, the four list
    defaults, the use-case seed of every shipped use case), walked over
    ``schema_for(scope)``. A section or subsection without any default is
    absent; a list without a shipped default (``llm_routing``) is absent — the
    UI reads "absent" as "Reset removes the key".
    """
    from app.core.config import _DEFAULT_IMAGE_USE_CASES
    out: Dict[str, Any] = {}
    for root, node in schema_for(scope).items():
        if node.get("virtual"):
            continue
        if node.get("is_array"):
            has, value = _shipped_default_parts((root,))
            if has:
                out[root] = value
            continue
        part: Dict[str, Any] = {}
        _tree_fields(node, (root,), part)
        if root == "image_generation" and "use_cases" in (node.get("sub_arrays") or {}):
            part["use_cases"] = {uc: _shipped_default_parts((root, "use_cases", uc))[1]
                                 for uc in _DEFAULT_IMAGE_USE_CASES}
        if part:
            out[root] = part
    return out


def override_paths(pruned_part: Dict[str, Any]) -> list[str]:
    """The dotted paths at which a PRUNED config part deviates from what ships.

    A value with a shipped default is one path (a changed use case, a season
    list), a list is one path, a dict without a default is descended. The
    UI marks a field "Instance"/"World" when its path, an ancestor or a
    descendant of it is in this list.
    """
    out: list = []

    def walk(value: Any, parts: Tuple[str, ...]) -> None:
        has, _default = _shipped_default_parts(parts)
        if isinstance(value, dict) and value and not has:
            for key, child in value.items():
                walk(child, parts + (str(key),))
        else:
            out.append(".".join(parts))

    for root, value in (pruned_part or {}).items():
        walk(value, (str(root),))
    return sorted(out)
