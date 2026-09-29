"""Central image routing — per render occasion ONE ordered backend chain.

The chain of an occasion = the character's own backend match (position 0,
character-scoped occasions only, when set) + ``image_generation.routing
[<occasion>]`` (positions 1..n). Resolution runs BEFORE the prompt is built:
the first entry that names a backend that fits the occasion, is enabled, is
not switched off for the character and is available right now wins; inside
one glob the cheapest (``BackendPool.pick_lowest_cost``). An EMPTY chain takes
the cheapest available backend of the occasion's kind (position None, no
fallback); a configured chain with nothing usable raises ``NoRouteError`` —
never a silent slide onto the cheapest (possibly paid) backend.

The INTENDED entry (``intended_entry``) is the first chain entry that is not
skipped for a CONFIGURATION reason (``CONFIG_SKIP_STATUSES``: matches no
backend, wrong kind, backend disabled, switched off for the character). A
render is a fallback — and gets ``fallback_from`` in its meta — only when it
ran behind that entry, i.e. a RUNTIME failure (cooldown / offline / a failed
attempt in this call) skipped it. A typo or a wrong-kind entry in front of
the chain is configuration the admin overview shows, never a fallback.
``intended_spec_for`` applies the configuration filters alone (availability
ignored), so a cooldown never changes the intended spec.

Spec: development_instructions/plan-image-routing.md § 3 (+ review notes and
the binding coordinator decision 2).
``explain_image_routing`` never probes (it reads the cached availability and
the cooldowns); only a real render probes the intended entry's candidates once.
"""
import fnmatch
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.core.log import get_logger
from app.imagegen.occasions import backend_fits, catalog_payload, get_occasion

logger = get_logger("image_routing")

STATUS_OK = "ok"
STATUS_COOLDOWN = "cooldown"
STATUS_UNAVAILABLE = "unavailable"
STATUS_DISABLED = "disabled"
STATUS_DISABLED_FOR_CHARACTER = "disabled_for_character"
STATUS_WRONG_KIND = "wrong_kind"
STATUS_NO_MATCH = "no_match"

STATUS_TEXT: Dict[str, str] = {
    STATUS_OK: "ok",
    STATUS_COOLDOWN: "cooling down",
    STATUS_UNAVAILABLE: "offline",
    STATUS_DISABLED: "backend disabled",
    STATUS_DISABLED_FOR_CHARACTER: "switched off for this character",
    STATUS_WRONG_KIND: "wrong kind of backend",
    STATUS_NO_MATCH: "matches no backend",
}

# Statuses that skip an entry for a CONFIGURATION reason — such an entry is
# never the intended one and never marks a render as a fallback.
CONFIG_SKIP_STATUSES = frozenset({STATUS_NO_MATCH, STATUS_WRONG_KIND,
                                  STATUS_DISABLED, STATUS_DISABLED_FOR_CHARACTER})


class NoRouteError(RuntimeError):
    """A configured chain has no usable entry right now (or the empty chain
    finds no backend of the occasion's kind). Carries the evaluated chain."""

    def __init__(self, occasion: str, chain: List[Dict[str, Any]]):
        self.occasion = occasion
        self.chain = list(chain)
        if self.chain:
            detail = ", ".join(f"{row['spec']} ({STATUS_TEXT.get(row['status'], row['status'])})"
                               for row in self.chain)
        else:
            detail = "no backend of this kind is available"
        super().__init__(f"no backend available for {occasion}: {detail}")


@dataclass
class Route:
    """The resolved backend of one render.

    ``intended_spec`` / ``first_position`` describe the INTENDED entry
    (``intended_entry``: the first chain entry not skipped for a
    configuration reason); both are "" / None for an empty chain.
    ``is_fallback`` is True only when the render runs behind that entry."""
    occasion: str
    backend: Any                       # ImageBackend
    position: Optional[int]            # 0 = character, 1..n = rule, None = empty chain
    spec: str
    intended_spec: str
    first_position: Optional[int]
    chain: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def is_fallback(self) -> bool:
        return (self.position is not None and self.first_position is not None
                and self.position != self.first_position)


def normalize_spec(spec: Any) -> str:
    """One stored chain entry in canonical form: the legacy ``workflow:``
    prefix is rewritten like ``workflow_spec_migration`` does, ``backend:``
    is dropped, whitespace trimmed."""
    from app.core.workflow_spec_migration import strip_legacy_workflow_prefix
    s = strip_legacy_workflow_prefix(spec)
    s = str(s or "").strip()
    if s.lower().startswith("backend:"):
        s = s[len("backend:"):].strip()
    return s


def describe_backend(b: Any) -> Dict[str, Any]:
    """Kind + live state of an instantiated backend (admin datalist, fits)."""
    media = getattr(b, "MEDIA_TYPE", "image") or "image"
    rs = b.runtime_status() if hasattr(b, "runtime_status") else {}
    return {
        "name": b.name,
        "media": media,
        "category": (getattr(b, "category", "") or "").lower(),
        "rig": ((getattr(b, "mesh_rig", "") or "mixamo").lower()
                if media == "mesh" else ""),
        "ref_slot_count": int(getattr(b, "ref_slot_count", 0) or 0),
        "image_family": getattr(b, "image_family", "") or "",
        "enabled": bool(getattr(b, "instance_enabled", True)),
        "runtime_status": rs,
    }


def describe_config_backend(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Kind of a CONFIG backend entry (save validator — the entry may not be
    instantiated yet)."""
    from app.imagegen.registry import BACKEND_REGISTRY
    cls = BACKEND_REGISTRY.get(str(entry.get("api_type") or "").strip().lower())
    media = getattr(cls, "MEDIA_TYPE", "image") if cls else "image"
    ref = entry.get("ref_slot_count")
    if ref in (None, ""):
        ref = getattr(cls, "DEFAULT_REF_SLOT_COUNT", 0) if cls else 0
    return {
        "name": str(entry.get("name") or ""),
        "media": media,
        "category": str(entry.get("category") or "").lower(),
        "rig": (str(entry.get("mesh_rig") or "mixamo").lower() if media == "mesh" else ""),
        "ref_slot_count": int(ref or 0),
        "enabled": entry.get("enabled", True) is not False,
    }


# ── test seams: looked up at call time, replaced in the smokes ───────────

def _rules(occasion: str) -> List[str]:
    from app.core import config
    rules = config.get("image_generation.routing", {}) or {}
    chain = rules.get(occasion) if isinstance(rules, dict) else None
    return list(chain) if isinstance(chain, list) else []


def _character_spec(occ_def: Dict[str, Any], character: str) -> str:
    if not character or not occ_def.get("character_scoped"):
        return ""
    try:
        from app.models.character import get_character_profile
        ovr = (get_character_profile(character) or {}).get("outfit_imagegen") or {}
    except Exception:
        return ""
    if not isinstance(ovr, dict):
        return ""
    spec = normalize_spec(ovr.get(occ_def.get("char_spec_field") or "workflow"))
    if not spec and occ_def.get("char_spec_fallback"):
        spec = normalize_spec(ovr.get(occ_def["char_spec_fallback"]))
    return spec


def _character_switches(character: str) -> Dict[str, Any]:
    """The per-character backend switches, READ ONLY (the pool's provider
    auto-creates the config file — a pure explain must not write)."""
    if not character:
        return {}
    try:
        from app.models.character import get_character_skill_config
        return (get_character_skill_config(character, "image_generation")
                or {}).get("instances") or {}
    except Exception:
        return {}


# ── resolution ──────────────────────────────────────────────────────────

def _pool(pool: Any = None) -> Any:
    if pool is not None:
        return pool
    from app.imagegen.service import get_image_service
    return get_image_service().pool


def chain_for(occasion: str, character: str = "") -> List[Tuple[str, str, int]]:
    """``[(spec, source, position)]`` — source "character" (position 0) or
    "rule" (1..n). Empty and duplicate entries are dropped."""
    occ = get_occasion(occasion)
    out: List[Tuple[str, str, int]] = []
    cs = _character_spec(occ, character)
    if cs:
        out.append((cs, "character", 0))
    seen = set()
    pos = 0
    for raw in _rules(occasion):
        s = normalize_spec(raw)
        if not s or s.lower() in seen:
            continue
        seen.add(s.lower())
        pos += 1
        out.append((s, "rule", pos))
    return out


def intended_entry(chain_rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The INTENDED chain row: the first one whose status is not a
    configuration skip (``CONFIG_SKIP_STATUSES``) — so ok / cooldown /
    unavailable, an ``exclude`` hit included. None when every row is a
    configuration skip (or the chain is empty)."""
    for row in chain_rows:
        if row.get("status") not in CONFIG_SKIP_STATUSES:
            return row
    return None


def _allowed(b: Any, switches: Dict[str, Any]) -> bool:
    return bool((switches.get(b.name) or {}).get("enabled", True))


def _prefer_img2img(live: List[Any], has_ref: bool) -> List[Any]:
    if not has_ref:
        return live
    img2img = [b for b in live if (getattr(b, "category", "") or "") == "img2img"]
    return img2img or live


def _config_filter(occasion: str, spec: str, backends: List[Any],
                   switches: Dict[str, Any]) -> Tuple[Optional[str], List[Any], List[str]]:
    """The CONFIGURATION filters of one chain entry, in order matched ->
    fits -> enabled -> allowed. Returns ``(skip_status, allowed, names)``:
    ``skip_status`` is one of ``CONFIG_SKIP_STATUSES`` or None when the entry
    passes; ``names`` is every backend name the glob matched."""
    pl = spec.lower()
    matched = [b for b in backends if fnmatch.fnmatch(b.name.lower(), pl)]
    names = [b.name for b in matched]
    if not matched:
        return STATUS_NO_MATCH, [], names
    fitting = [b for b in matched if backend_fits(occasion, describe_backend(b))]
    if not fitting:
        return STATUS_WRONG_KIND, [], names
    enabled = [b for b in fitting if getattr(b, "instance_enabled", True)]
    if not enabled:
        return STATUS_DISABLED, [], names
    allowed = [b for b in enabled if _allowed(b, switches)]
    if not allowed:
        return STATUS_DISABLED_FOR_CHARACTER, [], names
    return None, allowed, names


def _evaluate(occasion: str, spec: str, backends: List[Any],
              switches: Dict[str, Any], exclude: set,
              has_ref: bool) -> Tuple[str, List[Any], List[str]]:
    """Status of ONE chain entry plus its live candidates and every name the
    glob matched (for the admin page)."""
    skip, allowed, names = _config_filter(occasion, spec, backends, switches)
    if skip is not None:
        return skip, [], names
    live = [b for b in allowed if b.name not in exclude and b.available]
    if not live:
        cooled = any(b.name in exclude or b.in_cooldown() for b in allowed)
        return (STATUS_COOLDOWN if cooled else STATUS_UNAVAILABLE), [], names
    if any(ch in spec for ch in "*?["):
        live = _prefer_img2img(live, has_ref)
    return STATUS_OK, live, names


def intended_spec_for(occasion: str, character: str = "", pool: Any = None) -> str:
    """The spec of the INTENDED chain entry (see ``intended_entry``) from the
    configuration filters alone — availability is ignored, so a cooldown or
    an offline backend never changes it. "" for an empty chain or when every
    entry is a configuration skip. The one source Route, the overview and
    the scene signature agree on."""
    get_occasion(occasion)                       # UnknownOccasionError
    backends = list(_pool(pool).backends)
    switches = _character_switches(character)
    rows = []
    for spec, _source, pos in chain_for(occasion, character):
        skip, _allowed_b, _names = _config_filter(occasion, spec, backends, switches)
        # A configuration-passing entry counts as ok here (availability ignored).
        rows.append({"spec": spec, "position": pos, "status": skip or STATUS_OK})
    row = intended_entry(rows)
    return row["spec"] if row else ""


def _cheapest_no_rotation(live: List[Any]) -> Any:
    return sorted(live, key=lambda b: b.effective_cost)[0] if live else None


def _empty_chain_pick(occasion: str, backends: List[Any], switches: Dict[str, Any],
                      exclude: set, has_ref: bool, pool: Any, rotate: bool) -> Any:
    live = [b for b in backends
            if backend_fits(occasion, describe_backend(b))
            and getattr(b, "instance_enabled", True) and _allowed(b, switches)
            and b.name not in exclude and b.available]
    live = _prefer_img2img(live, has_ref)
    if not live:
        return None
    if rotate:
        return pool.pick_lowest_cost(live, rotation_key=f"route:{occasion}:*")
    return _cheapest_no_rotation(live)


def resolve_image_route(occasion: str, *, character: str = "",
                        has_ref: bool = False, exclude: Iterable[str] = (),
                        probe: bool = False, pool: Any = None) -> Route:
    """Resolve the chain of ``occasion`` to ONE backend (see module doc).

    ``exclude``: backend names that already failed in this routed call.
    ``probe``: run ``check_availability`` once on the INTENDED entry's
    candidates — the first entry that passes the configuration filters (a
    real render does; the overview never does)."""
    get_occasion(occasion)                       # UnknownOccasionError
    p = _pool(pool)
    backends = list(p.backends)
    switches = _character_switches(character)
    excl = set(exclude or ())
    entries = chain_for(occasion, character)

    if probe:
        for spec, _source, _pos in entries:
            skip, allowed, _names = _config_filter(occasion, spec, backends, switches)
            if skip is None:
                for b in allowed:
                    b.check_availability()
                break

    if not entries:
        b = _empty_chain_pick(occasion, backends, switches, excl, has_ref, p, rotate=True)
        if b is None:
            raise NoRouteError(occasion, [])
        return Route(occasion, b, None, "", "", None, [])

    chain: List[Dict[str, Any]] = []
    chosen: Optional[Tuple[Any, int, str]] = None
    for spec, source, pos in entries:
        status, live, names = _evaluate(occasion, spec, backends, switches, excl, has_ref)
        row = {"spec": spec, "source": source, "position": pos, "status": status,
               "backend": "", "matches": names}
        if status == STATUS_OK:
            if chosen is None:
                b = p.pick_lowest_cost(live, rotation_key=f"route:{occasion}:{spec}")
                chosen = (b, pos, spec)
                row["backend"] = b.name
            else:
                row["backend"] = _cheapest_no_rotation(live).name
        chain.append(row)
    if chosen is None:
        raise NoRouteError(occasion, chain)
    intended = intended_entry(chain)
    return Route(occasion, chosen[0], chosen[1], chosen[2],
                 intended["spec"] if intended else "",
                 intended["position"] if intended else None, chain)


def resolve_spec(occasion: str, spec: str, *, character: str = "",
                 has_ref: bool = False, pool: Any = None) -> Tuple[str, Any]:
    """Resolve ONE spec with the occasion's filters (no chain, no fallback) —
    the fallback re-render (R3) runs the INTENDED spec explicitly."""
    get_occasion(occasion)
    p = _pool(pool)
    status, live, _names = _evaluate(occasion, normalize_spec(spec), list(p.backends),
                                     _character_switches(character), set(), has_ref)
    if status != STATUS_OK:
        return status, None
    return status, p.pick_lowest_cost(live, rotation_key=f"route:{occasion}:{spec}")


def _pos_label(position: Optional[int]) -> str:
    return "character match" if position == 0 else f"order {position}"


def _explain_one(row: Dict[str, Any], character: str, backends: List[Any],
                 switches: Dict[str, Any], p: Any) -> Dict[str, Any]:
    oid = row["id"]
    entries = chain_for(oid, character)
    chain, resolved, position = [], None, None
    for spec, source, pos in entries:
        status, live, names = _evaluate(oid, spec, backends, switches, set(), False)
        b = _cheapest_no_rotation(live) if status == STATUS_OK else None
        chain.append({"spec": spec, "source": source, "position": pos,
                      "status": status, "status_text": STATUS_TEXT[status],
                      "backend": b.name if b else "", "matches": names})
        if b is not None and resolved is None:
            resolved, position = b.name, pos
    if not entries:
        b = _empty_chain_pick(oid, backends, switches, set(), False, p, rotate=False)
        via = "cheapest" if b else "none"
        resolved = b.name if b else None
        reason = ("empty chain — cheapest available backend of this kind" if b
                  else "empty chain — no backend of this kind is available")
    elif resolved is None:
        via = "none"
        reason = "no backend available: " + ", ".join(
            f"{r['spec']} ({r['status_text']})" for r in chain)
    else:
        via = "chain"
        skipped = [r for r in chain if r["position"] < position]
        reason = _pos_label(position)
        if skipped:
            reason += " — " + ", ".join(
                f"{_pos_label(r['position'])} skipped: {r['status_text']}" for r in skipped)
    intended = intended_entry(chain)
    return {**row, "chain": chain, "resolved": resolved, "position": position,
            "via": via, "reason": reason,
            "intended_spec": intended["spec"] if intended else ""}


def explain_occasion(occasion: str, character: str = "", pool: Any = None) -> Dict[str, Any]:
    """``explain_image_routing`` for ONE occasion (dialog preselection, the
    LoRA list of a character render, the mesh dialogs' default)."""
    get_occasion(occasion)
    p = _pool(pool)
    row = next(r for r in catalog_payload() if r["id"] == occasion)
    return _explain_one(row, character, list(p.backends),
                        _character_switches(character), p)


def explain_image_routing(character: str = "", pool: Any = None) -> Dict[str, Any]:
    """Per occasion: the chain with a status per entry and what a render would
    use right now. Never probes, never advances the round-robin."""
    p = _pool(pool)
    backends = list(p.backends)
    switches = _character_switches(character)
    return {"character": character,
            "occasions": [_explain_one(row, character, backends, switches, p)
                          for row in catalog_payload()]}


def route_meta(route: Optional[Route]) -> Dict[str, Any]:
    """The meta fields every routed generation stores next to ``backend``:
    ``routing`` always; ``fallback_from`` (with the INTENDED spec and
    position) only when the render ran behind the intended entry."""
    if route is None:
        return {}
    meta: Dict[str, Any] = {"routing": {"occasion": route.occasion,
                                        "position": route.position,
                                        "spec": route.spec}}
    if route.is_fallback:
        meta["fallback_from"] = {"occasion": route.occasion,
                                 "intended_spec": route.intended_spec,
                                 "position": route.first_position}
    return meta
