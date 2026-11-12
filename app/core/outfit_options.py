"""Per-outfit options beside the worn pieces — two: the boot hem (boots spec
``docs/superpowers/specs/2026-11-11-footwear-boots-mens-design.md`` § 8, § 20; plan Task 10) and the open / closed
state of the worn closable pieces (``piece_state``, unified-worn-pieces spec Addendum A, plan Task 11a; below the
boot hem sections).

**Live state**: the profile key ``equipped_options`` = ``{"boot_hem": "tucked" | "over" | null}`` beside
``equipped_pieces``. ``null`` means ``over`` for every shaft class (§ 20.2: no per-class default) — the trousers
fall over the boot shaft; ``tucked`` is the explicit per-outfit choice: the trouser leg is cut inside the collar
(``garment_layers``). Written through ``set_boot_hem`` under the profile lock; the routes
``GET`` / ``POST /characters/{name}/outfit-options`` (admin and the character's player, like an equip).

**When the choice exists** (``hem_eligible`` / ``hem_applicable``): a worn boot — a footwear fit whose record is
SPLIT (``split.is_boot``) with a shaft class other than ``none`` — and a worn own-mesh ``bottom`` piece with an
accepted fit that is no skirt (the fit's ``report.skirt``, ``garment_fit.is_skirt``). Painted trousers are never
"over" (§ 20.1): with them the boot is simply outside the painted shin and nothing is offered. A skirt or a dress
is layered over the shaft by the ordinary layer order and has no mode.

**Saved outfits** (``outfits_sets``): the ``options`` key ``{boot_hem}`` rides in the row's ``meta``;
``add_character_outfit`` stores what it is given, a new set without ``options`` the live value;
``apply_outfit_set`` restores it (an old row without ``options`` applies ``null``).

The mode is an ASSEMBLY input, not an outfit-signature input (§ 8.2): it changes neither the bare outfit model nor
the painted body — only the trousers' layered fit — so ``garment_assembly._wanted`` reads it from the profile and
``_state`` carries it, and a toggle rebuilds the assembly in seconds.

**Open / closed** (``piece_state``, plan 2026-11-12-unified-worn-pieces Task 11a, D-A1 / D-A2): an outfit piece
whose item is ``closable`` (``garment_set.closable_of``) is worn ``closed`` (the default) or ``open``. The profile
stores only the open set — ``equipped_options.piece_state = {item_id: "open"}``; "closed" pops the key. A stored
"open" counts only while the item is worn AND closable (``piece_states`` filters), so turning ``closable`` off on
the item falls back to closed without a write. ``inventory.equip_piece`` pops the equipped item's entry (a newly
worn piece is closed). Closed is the identity state: every key and every text is unchanged by it — 2D image
prompts and the chat outfit line included (ruling A7: closed says nothing); only "open" adds — ``OPEN_WORDS`` to
the piece text (``outfit_renderer.piece_text``) and ``open:<ids>`` to the outfit signature. An open piece covers
nothing in front (D-A4, ruling A8): ``outfit_renderer.covering_pieces`` is the one rule every coverage check reads
(the bare-slot summary, the outfit-decision hint, body-slot exposure and with it the image prompts). A toggle
is a worn-state change (``set_piece_state`` + ``inventory._notify_outfit_changed`` in the route: history, SSE, the
automatic Build), never an item edit. Saved sets carry ``options.piece_state`` beside ``boot_hem``;
``apply_saved_options`` restores both (a set without ``piece_state`` applies ``{}`` = all closed).
"""
import re
from typing import Any, Dict, Optional, Tuple

from app.core.log import get_logger

logger = get_logger("outfit_options")

#: The profile key holding the per-outfit options, and the boot hem key inside it.
OPTIONS_KEY = "equipped_options"
BOOT_HEM_KEY = "boot_hem"
#: The two hem modes; ``None`` in the profile reads as ``HEM_DEFAULT``.
HEM_MODES: Tuple[str, ...] = ("tucked", "over")
HEM_DEFAULT = "over"
#: The outfit-piece slot of the trousers the hem applies to.
TROUSERS_SLOT = "bottom"
#: The Wardrobe warning when a tucked pair did not fit into the shaft (``garment_layers`` fallback ``too_wide``).
TOO_WIDE_WARNING = "{trousers}: too wide to tuck into {boot} — worn over it"
#: The Wardrobe warning when the boot's shaft ends too close to the ankle to tuck into (``garment_layers`` fallback
#: ``shaft_too_low``).
SHAFT_TOO_LOW_WARNING = "{boot}: the shaft is too low to tuck {trousers} into — worn over it"


def boot_hem(profile: Optional[Dict[str, Any]]) -> str:
    """The boot hem mode of a profile: ``tucked`` or ``over`` (a missing / null / unknown value is ``over``)."""
    options = (profile or {}).get(OPTIONS_KEY)
    mode = options.get(BOOT_HEM_KEY) if isinstance(options, dict) else None
    return mode if mode in HEM_MODES else HEM_DEFAULT


def normalise_hem(mode: Any) -> Optional[str]:
    """``tucked`` / ``over`` / ``None`` for a value that is one of those (or null / ""); ValueError otherwise."""
    if mode is None or mode == "":
        return None
    if isinstance(mode, str) and mode in HEM_MODES:
        return mode
    raise ValueError(f"boot_hem must be one of {', '.join(HEM_MODES)} or null")


def set_boot_hem(character_name: str, mode: Optional[str]) -> bool:
    """Store the boot hem mode (``tucked`` / ``over`` / ``None`` = the default) in the profile under the profile
    lock; True when saved. ValueError for another value."""
    from app.core.keyed_lock import keyed_lock
    from app.models.character import get_character_profile, save_character_profile
    value = normalise_hem(mode)
    with keyed_lock("character_profile", character_name):
        profile = get_character_profile(character_name)
        if not profile:
            return False
        options = dict(profile.get(OPTIONS_KEY) or {}) if isinstance(profile.get(OPTIONS_KEY), dict) else {}
        options[BOOT_HEM_KEY] = value
        profile[OPTIONS_KEY] = options
        return bool(save_character_profile(character_name, profile))


def apply_saved_options(character_name: str, outfit: Dict[str, Any]) -> bool:
    """Apply a saved set's ``options`` to the profile — the boot hem and the open / closed state; a set without
    them (or with an unknown hem) stores null = the default hem, a set without ``piece_state`` applies ``{}`` = every
    piece closed. Called by the apply-outfit-set routes inside their profile lock (the lock is re-entrant), AFTER
    the pieces (an equip closes the piece it puts on). True when saved."""
    from app.core.keyed_lock import keyed_lock
    from app.models.character import get_character_profile, save_character_profile
    options = outfit.get("options") if isinstance(outfit.get("options"), dict) else {}
    try:
        mode = normalise_hem(options.get(BOOT_HEM_KEY))
    except ValueError:
        mode = None
    state = clean_piece_state_map(options.get(PIECE_STATE_KEY))
    with keyed_lock("character_profile", character_name):
        profile = get_character_profile(character_name)
        if not profile:
            return False
        stored = dict(profile.get(OPTIONS_KEY) or {}) if isinstance(profile.get(OPTIONS_KEY), dict) else {}
        stored[BOOT_HEM_KEY] = mode
        stored[PIECE_STATE_KEY] = state
        profile[OPTIONS_KEY] = stored
        return bool(save_character_profile(character_name, profile))


# ---------------------------------------------------------------------------
# Open / closed (module docstring, last section)
# ---------------------------------------------------------------------------

#: The key of the open / closed map inside ``OPTIONS_KEY``.
PIECE_STATE_KEY = "piece_state"
OPEN, CLOSED = "open", "closed"
PIECE_STATES: Tuple[str, ...] = (OPEN, CLOSED)
#: The state words of a piece's text (rulings A1 / A6: neutral words) — they reach every text, mesh inputs
#: included. Closed has none (ruling A7): a closed piece reads as it did before the option existed.
OPEN_WORDS = "worn open"
#: Words in a prompt fragment that already name the state (ruling A6: the Wardrobe hints that the toggle adds to
#: them; the fragment is never edited automatically).
_STATE_WORDS_RE = re.compile(r"\b(?:open|opened|closed|unbuttoned|buttoned|unzipped|zipped)\b", re.IGNORECASE)


def normalise_piece_state(state: Any) -> str:
    """``open`` / ``closed`` for a value that is one of those; ValueError otherwise."""
    if isinstance(state, str) and state in PIECE_STATES:
        return state
    raise ValueError(f"state must be one of {', '.join(PIECE_STATES)}")


def clean_piece_state_map(raw: Any) -> Dict[str, str]:
    """The stored shape of a state map: ``{item_id: "open"}`` — every other value (closed, unknown) dropped."""
    if not isinstance(raw, dict):
        return {}
    return {str(k): OPEN for k, v in raw.items() if k and v == OPEN}


def _stored_map(profile: Optional[Dict[str, Any]]) -> Dict[str, str]:
    options = (profile or {}).get(OPTIONS_KEY)
    return clean_piece_state_map(options.get(PIECE_STATE_KEY) if isinstance(options, dict) else None)


def piece_states(profile: Optional[Dict[str, Any]],
                 pieces: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """``{item_id: "open"}`` for the worn (``pieces``, else the profile's ``equipped_pieces``) closable items the
    profile stores open — a stored "open" of an item not worn now, or no longer closable, does not count."""
    from app.core.garment_set import closable_of
    from app.models.inventory import get_item
    stored = _stored_map(profile)
    if not stored:
        return {}
    if pieces is None:
        pieces = (profile or {}).get("equipped_pieces")
    worn = {str(v) for v in (pieces or {}).values() if v} if isinstance(pieces, dict) else set()
    return {iid: OPEN for iid in sorted(stored) if iid in worn and closable_of(get_item(iid))}


def piece_state_of(profile: Optional[Dict[str, Any]], item_id: str) -> str:
    """``open`` or ``closed`` — the state a worn piece has now (``piece_states``); closed for anything else."""
    return OPEN if piece_states(profile).get(str(item_id or "")) == OPEN else CLOSED


def drop_piece_state(profile: Dict[str, Any], item_id: str) -> None:
    """Remove ``item_id`` from the profile's stored open set IN PLACE (``inventory.equip_piece``: a newly worn
    piece is closed). The caller saves the profile."""
    options = profile.get(OPTIONS_KEY)
    if not isinstance(options, dict):
        return
    stored = options.get(PIECE_STATE_KEY)
    if isinstance(stored, dict) and item_id in stored:
        options = dict(options)
        options[PIECE_STATE_KEY] = {k: v for k, v in stored.items() if k != item_id}
        profile[OPTIONS_KEY] = options


def set_piece_state(character_name: str, item_id: str, state: str) -> bool:
    """Store the open / closed state of a worn closable piece (``closed`` pops the key) under the profile lock;
    True when saved. ValueError for a bad state, an item that is not closable, or a piece not worn now. The caller
    notifies the worn-state change (``inventory._notify_outfit_changed``)."""
    from app.core.garment_set import closable_of
    from app.core.keyed_lock import keyed_lock
    from app.models.character import get_character_profile, save_character_profile
    from app.models.inventory import get_item
    value = normalise_piece_state(state)
    item_id = str(item_id or "").strip()
    if not closable_of(get_item(item_id)):
        raise ValueError(f"{item_id or 'item'}: not closable")
    with keyed_lock("character_profile", character_name):
        profile = get_character_profile(character_name)
        if not profile:
            return False
        pieces = profile.get("equipped_pieces") if isinstance(profile.get("equipped_pieces"), dict) else {}
        if item_id not in {str(v) for v in pieces.values() if v}:
            raise ValueError(f"{item_id}: not worn now")
        options = dict(profile.get(OPTIONS_KEY) or {}) if isinstance(profile.get(OPTIONS_KEY), dict) else {}
        stored = clean_piece_state_map(options.get(PIECE_STATE_KEY))
        if value == OPEN:
            stored[item_id] = OPEN
        else:
            stored.pop(item_id, None)
        options[PIECE_STATE_KEY] = stored
        profile[OPTIONS_KEY] = options
        return bool(save_character_profile(character_name, profile))


def with_piece_state(profile: Dict[str, Any], piece_state: Optional[Dict[str, str]]) -> Dict[str, Any]:
    """A copy of ``profile`` whose stored state map is ``piece_state`` (open entries only) — for a caller that
    renders or keys a state other than the live one (a saved set, a figure's delivered state). The input is not
    changed; only the ``equipped_options`` level is copied."""
    out = dict(profile or {})
    options = dict(out.get(OPTIONS_KEY) or {}) if isinstance(out.get(OPTIONS_KEY), dict) else {}
    options[PIECE_STATE_KEY] = clean_piece_state_map(piece_state)
    out[OPTIONS_KEY] = options
    return out


def with_item_state(profile: Dict[str, Any], item_id: str, state: str) -> Dict[str, Any]:
    """A copy of ``profile`` whose state map is its live one (``piece_states``) with ``item_id`` in ``state`` —
    the profile of a garment run for one state of one worn piece (plan Task 11b: every text and fingerprint of
    the run reads it). ``state`` of a piece that is not worn or not closable has no effect (``piece_states``
    counts only worn closable pieces). ValueError for a bad state."""
    value = normalise_piece_state(state)
    current = dict(piece_states(profile))
    if value == OPEN:
        current[str(item_id)] = OPEN
    else:
        current.pop(str(item_id), None)
    return with_piece_state(profile, current)


def fragment_names_state(fragment: Any) -> bool:
    """Whether a prompt fragment already names an open / closed state (ruling A6: the Wardrobe hints "the
    description already says open/closed — the toggle adds to it")."""
    return bool(isinstance(fragment, str) and _STATE_WORDS_RE.search(fragment))


def closable_worn(profile: Optional[Dict[str, Any]]) -> list:
    """The worn closable pieces of a profile: ``[{item_id, name, state, names_state}]`` in slot order of first
    appearance — what the outfit-options GET shows beside the stored map."""
    from app.core.garment_set import closable_of
    from app.models.inventory import get_item
    pieces = (profile or {}).get("equipped_pieces")
    states = piece_states(profile)
    out, seen = [], set()
    for iid in ((pieces or {}).values() if isinstance(pieces, dict) else ()):
        iid = str(iid or "")
        if not iid or iid in seen:
            continue
        seen.add(iid)
        item = get_item(iid)
        if not closable_of(item):
            continue
        out.append({"item_id": iid, "name": (item or {}).get("name") or iid,
                    "state": states.get(iid, CLOSED),
                    "names_state": fragment_names_state((item or {}).get("prompt_fragment"))})
    return out


def is_boot_record(record: Optional[Dict[str, Any]]) -> bool:
    """Whether a footwear fit record is a split boot with a shaft class other than ``none`` — a fit that
    serves a shaft node the trousers can be tucked into or layered over."""
    if not isinstance(record, dict):
        return False
    split = record.get("split") if isinstance(record.get("split"), dict) else {}
    shaft = record.get("shaft") if isinstance(record.get("shaft"), dict) else {}
    cls = shaft.get("class")
    return bool(split.get("is_boot")) and isinstance(cls, str) and cls != "none"


def is_skirt_record(record: Optional[Dict[str, Any]]) -> bool:
    """Whether a clothing fit record says the piece hangs as a skirt (``report.skirt``, ``garment_fit.is_skirt``)."""
    if not isinstance(record, dict):
        return False
    report = record.get("report") if isinstance(record.get("report"), dict) else {}
    return bool(report.get("skirt"))


def hem_eligible(boot_record: Optional[Dict[str, Any]],
                 trousers_record: Optional[Dict[str, Any]]) -> Tuple[bool, str]:
    """``(applicable, reason)`` of a boot fit record and a trousers fit record (either may be None): the one
    rule behind ``hem_applicable`` and the assembly (``garment_assembly._wanted``)."""
    if not is_boot_record(boot_record):
        return False, "no boot worn (a footwear fit split at the ankle with a shaft)"
    if not isinstance(trousers_record, dict):
        return False, "no own-mesh trousers worn with an accepted fit (painted trousers stay inside the boot)"
    if is_skirt_record(trousers_record):
        return False, "the bottom piece is a skirt or a dress — layered by the ordinary layer order"
    return True, ""


def hem_applicable(character_name: str, *, profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """What the Wardrobe shows: ``{applicable, boot_item, trousers_item, reason, mode}`` for the pieces the
    character wears NOW — the feet piece with a boot fit on the current base model and the own-mesh ``bottom``
    piece with an accepted, non-skirt fit there. ``mode`` is the stored choice (``boot_hem``) either way."""
    from app.core import base_body, garment_store
    from app.core.garment_set import FOOTWEAR_SLOT, OWN_MESH, mesh_mode_of
    from app.models.inventory import get_item
    if profile is None:
        from app.models.character import get_character_profile
        profile = get_character_profile(character_name) or {}
    out: Dict[str, Any] = {"applicable": False, "boot_item": None, "trousers_item": None, "reason": "",
                           "mode": boot_hem(profile)}
    pieces = profile.get("equipped_pieces") if isinstance(profile.get("equipped_pieces"), dict) else {}
    feet = str(pieces.get(FOOTWEAR_SLOT) or "")
    bottom = str(pieces.get(TROUSERS_SLOT) or "")
    base = base_body.current_base(character_name, profile=profile)
    if not base or not base[1]:
        out["reason"] = "no base model"
        return out

    def own_mesh_fit(item_id: str) -> Optional[Dict[str, Any]]:
        if not item_id:
            return None
        if mesh_mode_of(get_item(item_id)) != OWN_MESH:
            return None
        try:
            fit = garment_store.accepted_fit(character_name, item_id, base_model_sha=base[1], profile=profile)
        except ValueError:
            return None
        return fit[1] if fit else None
    boot_rec = own_mesh_fit(feet)
    trousers_rec = own_mesh_fit(bottom)
    ok, reason = hem_eligible(boot_rec, trousers_rec)
    out.update(applicable=ok, reason=reason, boot_item=feet if is_boot_record(boot_rec) else None,
               trousers_item=bottom if (ok and bottom) else None)
    return out
