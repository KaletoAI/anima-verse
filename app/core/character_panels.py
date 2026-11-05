"""Package character panels — a package's own editor on a character's Skills tab.

A skill package that needs more than flat per-character config fields (a list
of entries with pickers, a test button, ...) registers a PANEL PROVIDER from its
``on_load`` module::

    from app.core import hooks
    from app.core.character_panels import panel_capability
    hooks.register_provider(panel_capability("<package id>"), provider, owner="<package id>")

``provider`` is an object (or module) with four methods; the core serves them
through the admin routes in ``app/routes/character_panels.py`` and Game-Admin
renders the answer generically (``frontend/src/tabs/characters/PackagePanel.tsx``):

- ``describe(character, lang) -> dict`` — the whole panel:
  ``{"title", "intro", "tabs": [Tab]?, "cards": [Card],
  "create": {"label", "fields": [Field]} | None}``
- ``save(character, card_id, values, lang) -> {"ok", "error"?, "card_id"?}``
  (``card_id`` None = create)
- ``delete(character, card_id, lang) -> {"ok", "error"?}``
- ``action(character, card_id, action_id, lang) -> {"ok", "message"?, "error"?}``

Every string the provider answers is shown as it stands: the provider
translates its own labels with ``app.core.i18n.t(en, lang)``. The core never
names a package (R1): it only builds the capability string from the package id
the URL names, and with no provider every function here raises
``PanelNotFound`` (the routes answer 404, the Skills tab shows no panel).

The core does the generic part of a save so no provider has to repeat it: the
submitted values are reduced to the keys the card (or the create form)
declares, coerced to the field's type, and checked against ``required`` and
``min``/``max``. A failed check answers ``{"ok": False, "error": ...}`` and the
provider is not called. Docs: ``docs/plugins.md`` → "Character panels",
``docs/skill-core-api.md`` → "Character panels".
"""
from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional

from app.core import hooks
from app.core.i18n import t
from app.core.log import get_logger

logger = get_logger("character_panels")

#: Capability prefix of a panel provider: ``character_panel:<package id>``.
CAPABILITY_PREFIX = "character_panel:"

#: The renderer's whole vocabulary. Values: ``item``/``condition``/``backend``
#: = one id string, ``items``/``characters`` = a list of strings, ``loras`` = a
#: list of ``{"name", "strength"}``.
FIELD_TYPES = frozenset({
    "text", "textarea", "int", "bool", "item", "items", "condition", "characters",
    "backend", "loras",
})

#: Presentation-only field attributes: handed to the renderer exactly as the
#: provider gave them (only when given), never checked here.
_LAYOUT_KEYS = ("tab", "width", "rows")

#: Bounds of a LoRA strength; a value outside is clamped.
LORA_STRENGTH_MIN = -4.0
LORA_STRENGTH_MAX = 4.0

_LIST_TYPES = frozenset({"items", "characters"})
_LANG_RE = re.compile(r"^[a-z]{2,3}(?:-[a-z0-9]{2,8})?$")


class PanelNotFound(LookupError):
    """No provider for the package, or the character does not exist."""


class PanelContractError(RuntimeError):
    """The provider answered something outside the panel contract."""


def panel_capability(package_id: str) -> str:
    """The provider capability string of a package: ``character_panel:<id>``."""
    return f"{CAPABILITY_PREFIX}{package_id}"


def get_panel_provider(package_id: str) -> Any:
    """The registered provider of a package, or ``None``."""
    pid = str(package_id or "").strip()
    if not pid:
        return None
    return hooks.get_provider(panel_capability(pid))


def has_panel(package_id: str) -> bool:
    """Whether a package registered a character panel."""
    return get_panel_provider(package_id) is not None


def normalize_lang(lang: Any) -> str:
    """A UI language code as the routes receive it; anything odd → ``en``."""
    code = str(lang or "").strip().lower()
    return code if _LANG_RE.match(code) else "en"


# ---------------------------------------------------------------------------
# Contract normalization
# ---------------------------------------------------------------------------

def _s(value: Any) -> str:
    return "" if value is None else str(value)


def _opt_int(value: Any) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _field(raw: Any, where: str) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise PanelContractError(f"{where}: field is not an object")
    key = _s(raw.get("key")).strip()
    ftype = _s(raw.get("type")).strip()
    if not key:
        raise PanelContractError(f"{where}: field without key")
    if ftype not in FIELD_TYPES:
        raise PanelContractError(f"{where}: field {key!r} has unknown type {ftype!r}")
    out: Dict[str, Any] = {
        "key": key, "type": ftype, "label": _s(raw.get("label")) or key,
        "hint": _s(raw.get("hint")), "required": bool(raw.get("required")),
        "unit": _s(raw.get("unit")), "filter": _s(raw.get("filter")),
        "placeholder": _s(raw.get("placeholder")),
    }
    out["min"] = _opt_int(raw.get("min"))
    out["max"] = _opt_int(raw.get("max"))
    for lk in _LAYOUT_KEYS:
        if lk in raw:
            out[lk] = raw[lk]
    if ftype == "loras":
        # The LoRA list is scoped to the backend another field of the same
        # card names (the draft value, fallback_field when that is empty).
        out["backend_field"] = _s(raw.get("backend_field")).strip()
        out["fallback_field"] = _s(raw.get("fallback_field")).strip()
        out["target"] = "tpose" if _s(raw.get("target")).strip() == "tpose" else "render"
    return out


def _fields(raw: Any, where: str) -> List[Dict[str, Any]]:
    if raw is None:
        return []
    if not isinstance(raw, (list, tuple)):
        raise PanelContractError(f"{where}: fields is not a list")
    fields = [_field(f, where) for f in raw]
    keys = [f["key"] for f in fields]
    if len(set(keys)) != len(keys):
        raise PanelContractError(f"{where}: duplicate field keys")
    return fields


def _action(raw: Any, where: str) -> Dict[str, Any]:
    if not isinstance(raw, dict) or not _s(raw.get("id")).strip():
        raise PanelContractError(f"{where}: action without id")
    return {"id": _s(raw.get("id")).strip(), "label": _s(raw.get("label")) or _s(raw.get("id")),
            "confirm": _s(raw.get("confirm")), "primary": bool(raw.get("primary"))}


def _card(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise PanelContractError("card is not an object")
    cid = _s(raw.get("id")).strip()
    if not cid:
        raise PanelContractError("card without id")
    where = f"card {cid!r}"
    values = raw.get("values") or {}
    if not isinstance(values, dict):
        raise PanelContractError(f"{where}: values is not an object")
    badges = raw.get("badges") or []
    if not isinstance(badges, (list, tuple)):
        raise PanelContractError(f"{where}: badges is not a list")
    actions = raw.get("actions") or []
    if not isinstance(actions, (list, tuple)):
        raise PanelContractError(f"{where}: actions is not a list")
    return {
        "id": cid, "title": _s(raw.get("title")), "subtitle": _s(raw.get("subtitle")),
        "badges": [_s(b) for b in badges if _s(b)],
        "fields": _fields(raw.get("fields"), where), "values": dict(values),
        "status": _s(raw.get("status")),
        "actions": [_action(a, where) for a in actions],
        "deletable": bool(raw.get("deletable")),
        "delete_confirm": _s(raw.get("delete_confirm")),
    }


def _tabs(raw: Any) -> List[Dict[str, Any]]:
    if raw is None:
        return []
    if not isinstance(raw, (list, tuple)):
        raise PanelContractError("tabs is not a list")
    out: List[Dict[str, Any]] = []
    for tab in raw:
        if not isinstance(tab, dict) or not _s(tab.get("id")).strip():
            raise PanelContractError("tab without id")
        tid = _s(tab.get("id")).strip()
        out.append({"id": tid, "label": _s(tab.get("label")) or tid, "hint": _s(tab.get("hint"))})
    ids = [tab["id"] for tab in out]
    if len(set(ids)) != len(ids):
        raise PanelContractError("duplicate tab ids")
    return out


def normalize_panel(raw: Any) -> Dict[str, Any]:
    """A provider's ``describe`` answer reduced to the contract.

    Optional keys get their empty default; a missing card/field/action/tab id,
    a field type outside ``FIELD_TYPES`` or a wrong container type raise
    ``PanelContractError``. The layout attributes ``tab``/``width``/``rows`` of
    a field pass through untouched (the renderer falls back on its own)."""
    if not isinstance(raw, dict):
        raise PanelContractError("describe() did not answer an object")
    cards = raw.get("cards") or []
    if not isinstance(cards, (list, tuple)):
        raise PanelContractError("cards is not a list")
    norm_cards = [_card(c) for c in cards]
    ids = [c["id"] for c in norm_cards]
    if len(set(ids)) != len(ids):
        raise PanelContractError("duplicate card ids")
    create = raw.get("create")
    norm_create = None
    if create:
        if not isinstance(create, dict):
            raise PanelContractError("create is not an object")
        norm_create = {"label": _s(create.get("label")),
                       "fields": _fields(create.get("fields"), "create")}
    return {"title": _s(raw.get("title")), "intro": _s(raw.get("intro")),
            "tabs": _tabs(raw.get("tabs")), "cards": norm_cards, "create": norm_create}


def _result(raw: Any, what: str, lang: str, *extra: str) -> Dict[str, Any]:
    if not isinstance(raw, dict) or "ok" not in raw:
        raise PanelContractError(f"{what}() did not answer {{'ok': ...}}")
    out: Dict[str, Any] = {"ok": bool(raw.get("ok")), "error": _s(raw.get("error"))}
    for key in extra:
        if raw.get(key) not in (None, ""):
            out[key] = _s(raw.get(key))
    if not out["ok"] and not out["error"]:
        out["error"] = t("That did not work.", lang)
    return out


# ---------------------------------------------------------------------------
# Value coercion (the generic part of a save)
# ---------------------------------------------------------------------------

def _lora_strength(raw: Any) -> float:
    """A LoRA strength: float clamped to the bounds; non-numeric → 1.0."""
    if isinstance(raw, bool):
        return 1.0
    try:
        val = float(raw.strip() if isinstance(raw, str) else raw)
    except (TypeError, ValueError):
        return 1.0
    if not math.isfinite(val):
        return 1.0
    return max(LORA_STRENGTH_MIN, min(LORA_STRENGTH_MAX, val))


def _coerce_loras(raw: List[Any]) -> List[Dict[str, Any]]:
    """Entries with a non-empty name, first of a name wins; anything else goes."""
    out: List[Dict[str, Any]] = []
    seen: set = set()
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        name = _s(entry.get("name")).strip()
        if not name or name in seen:
            continue
        seen.add(name)
        out.append({"name": name, "strength": _lora_strength(entry.get("strength"))})
    return out


def coerce_values(fields: List[Dict[str, Any]], values: Dict[str, Any], *,
                  creating: bool, lang: str = "en") -> tuple[Dict[str, Any], str]:
    """``(clean values, error)`` for submitted ``values`` against normalized
    ``fields``. Undeclared keys are dropped; ``error`` is ``""`` when every
    present value fits its field. ``creating`` = a required field that is
    absent counts as empty."""
    clean: Dict[str, Any] = {}
    for f in fields:
        key, ftype, label = f["key"], f["type"], f["label"]
        if key not in values:
            if creating and f["required"]:
                return {}, t("{label} is required.", lang).format(label=label)
            continue
        raw = values[key]
        if ftype in ("text", "textarea", "item", "condition", "backend"):
            val: Any = _s(raw).strip()
            empty = not val
        elif ftype == "bool":
            val, empty = bool(raw), False
        elif ftype == "int":
            if raw is None or (isinstance(raw, str) and not raw.strip()):
                val, empty = None, True
            else:
                num = None if isinstance(raw, bool) else _opt_int(
                    raw.strip() if isinstance(raw, str) else raw)
                if num is None or (isinstance(raw, float) and raw != int(raw)):
                    return {}, t("{label}: enter a whole number.", lang).format(label=label)
                if f["min"] is not None and num < f["min"]:
                    return {}, t("{label}: at least {n}.", lang).format(label=label, n=f["min"])
                if f["max"] is not None and num > f["max"]:
                    return {}, t("{label}: at most {n}.", lang).format(label=label, n=f["max"])
                val, empty = num, False
        elif ftype == "loras":
            if raw is None:
                raw = []
            if not isinstance(raw, (list, tuple)):
                return {}, t("{label}: invalid selection.", lang).format(label=label)
            val = _coerce_loras(list(raw))
            empty = not val
        else:  # _LIST_TYPES
            if raw is None:
                raw = []
            if not isinstance(raw, (list, tuple)):
                return {}, t("{label}: invalid selection.", lang).format(label=label)
            seen: List[str] = []
            for v in raw:
                s = _s(v).strip()
                if s and s not in seen:
                    seen.append(s)
            val, empty = seen, not seen
        if empty and f["required"]:
            return {}, t("{label} is required.", lang).format(label=label)
        clean[key] = val
    return clean, ""


# ---------------------------------------------------------------------------
# The four operations (called by the routes)
# ---------------------------------------------------------------------------

def _provider_for(package_id: str, character: str) -> Any:
    provider = get_panel_provider(package_id)
    if provider is None:
        raise PanelNotFound(f"No character panel for package '{package_id}'")
    from app.models.character import character_exists
    if not character_exists(character):
        raise PanelNotFound(f"Character '{character}' not found")
    return provider


def _call(provider: Any, method: str, *args: Any) -> Any:
    fn = getattr(provider, method, None)
    if not callable(fn):
        raise PanelContractError(f"provider has no {method}()")
    return fn(*args)


def describe_panel(package_id: str, character: str, lang: str = "en") -> Dict[str, Any]:
    """The normalized panel of ``package_id`` for ``character``."""
    lang = normalize_lang(lang)
    provider = _provider_for(package_id, character)
    return normalize_panel(_call(provider, "describe", character, lang))


def save_panel_card(package_id: str, character: str, card_id: Optional[str],
                    values: Any, lang: str = "en") -> Dict[str, Any]:
    """Save one card (``card_id`` None/"" = create) → ``{"ok", "error", "card_id"?}``.

    The fields come from a fresh ``describe``: the card's own for an update,
    ``create.fields`` for a create. Values are coerced first; the provider sees
    only declared keys of the right type."""
    lang = normalize_lang(lang)
    provider = _provider_for(package_id, character)
    if not isinstance(values, dict):
        return {"ok": False, "error": t("Invalid values.", lang)}
    panel = normalize_panel(_call(provider, "describe", character, lang))
    cid = _s(card_id).strip() or None
    if cid is None:
        if not panel["create"]:
            return {"ok": False, "error": t("New entries cannot be created here.", lang)}
        fields = panel["create"]["fields"]
    else:
        card = next((c for c in panel["cards"] if c["id"] == cid), None)
        if card is None:
            return {"ok": False, "error": t("This entry no longer exists.", lang)}
        fields = card["fields"]
    clean, error = coerce_values(fields, values, creating=cid is None, lang=lang)
    if error:
        return {"ok": False, "error": error}
    return _result(_call(provider, "save", character, cid, clean, lang), "save", lang, "card_id")


def delete_panel_card(package_id: str, character: str, card_id: str,
                      lang: str = "en") -> Dict[str, Any]:
    """Delete one card → ``{"ok", "error"}``."""
    lang = normalize_lang(lang)
    provider = _provider_for(package_id, character)
    cid = _s(card_id).strip()
    if not cid:
        return {"ok": False, "error": t("This entry no longer exists.", lang)}
    return _result(_call(provider, "delete", character, cid, lang), "delete", lang)


def run_panel_action(package_id: str, character: str, card_id: str, action_id: str,
                     lang: str = "en") -> Dict[str, Any]:
    """Run one card action → ``{"ok", "error", "message"?}``."""
    lang = normalize_lang(lang)
    provider = _provider_for(package_id, character)
    cid, aid = _s(card_id).strip(), _s(action_id).strip()
    if not cid or not aid:
        return {"ok": False, "error": t("This entry no longer exists.", lang)}
    return _result(_call(provider, "action", character, cid, aid, lang), "action", lang, "message")
