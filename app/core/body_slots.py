"""Body-slot engine — executes species-package slot declarations.

The core owns only the PRINCIPLE that a character has appearance and
anatomy (plan-body-slots.md, user decision): storage, visibility rules,
prompt integration and topology resolution live here — WHICH slots,
attributes, clothing-slot topology and UI silhouette exist is declared by
species packages (plugin.yaml ``body_slots`` / ``piece_slots`` /
``silhouette``, scoped by the package-level ``apply_to`` template
selector). This code knows no slot, attribute or species name; a new
species (e.g. a talking dragon) is a new content package, zero core change.

Decisions wired in (dialog 2026-07-08):
- F1: binary visibility. ``always``/``covered`` fragments flow into the
  GENERAL person description (carries clothed appearance differences); ``exposed`` renders only while uncovered.
- F2: species packages define the FULL slot topology, including which
  clothing slots exist (``piece_slots_for_character``; core
  ``VALID_PIECE_SLOTS`` is only the fallback without a species package).
- F3: slot fragments are sent along even when a reference image is
  attached (callers do not filter them out).

A slot may declare ``back: true`` — its anatomy is visible from BEHIND as
well. A render that shows the character's back (the T-pose back view) keeps
only those exposed fragments and their LoRAs; the rest describe the front
and would drag the figure around toward the camera.

A character dressed by free text (template without an outfit system, e.g.
``npc-temporary``) has no pieces to cover a slot: its slots are covered while
it is dressed (``outfit_worn``) and exposed once it is undressed. An
attribute may declare a template-scoped ``default`` (``apply_to`` +
``value``/``by``) that fills an unset value in the EXPOSED fragment only —
visible anatomy has to be named, while covered the character's own
appearance text speaks; a default resolving to "" lets the word vanish
instead of dropping the fragment. A package may declare ``undressed_prompt``,
the text an undressed free-text character says in place of the core's
"no clothes".
"""
from string import Formatter
from typing import Any, Dict, List, Optional, Tuple

from app.core.log import get_logger

logger = get_logger("body_slots")


# ---------------------------------------------------------------------------
# Species resolution
# ---------------------------------------------------------------------------

def _template_matches(pkg, template_name: str, tmpl: Dict[str, Any]) -> bool:
    """Whether a package's species content applies to a template.

    Package-level ``apply_to`` wins; without it the package's character
    fragments decide (same selector semantics)."""
    from app.models.character_template import fragment_applies
    if pkg.apply_to is not None:
        return fragment_applies({"apply_to": pkg.apply_to}, template_name, tmpl)
    return any(fragment_applies(f, template_name, tmpl)
               for f in pkg.character_fragments)


def _species_packages_for(profile: Dict[str, Any]) -> List[Any]:
    """Packages whose species content (slots/silhouette/topology) applies
    to this character's template."""
    tmpl_name = (profile.get("template") or "").strip()
    if not tmpl_name:
        return []
    try:
        from app.plugins.registry import packages
        from app.models.character_template import get_template
    except Exception:
        return []
    tmpl = get_template(tmpl_name) or {}
    out = []
    for pkg in packages():
        if not (pkg.body_slots or pkg.piece_slots or pkg.silhouette
                or pkg.undressed_prompt):
            continue
        try:
            if _template_matches(pkg, tmpl_name, tmpl):
                out.append(pkg)
        except Exception as e:
            logger.debug("species match failed for package %s: %s", pkg.id, e)
    return out


def normalize_condition_value(value):
    """Missing and explicit null match null only; strings are case-insensitive."""
    return None if value is None else str(value).strip().lower()


def _slot_applies(spec, profile: Dict[str, Any]) -> bool:
    """Per-slot ``applies_to`` filter (profile-field conditions, e.g.
    gender) — case-insensitive string comparison."""
    for field_name, allowed in (spec.applies_to or {}).items():
        values = (profile.get("body_slots") or {}).get(spec.id) or {}
        if field_name.startswith("attributes."):
            value = values.get(field_name[len("attributes."):])
        elif field_name in spec.attributes:
            value = values.get(field_name)
        else:
            value = profile.get(field_name)
        val = normalize_condition_value(value)
        if val not in [normalize_condition_value(a) for a in allowed]:
            return False
    return True


def slots_for_character(character_name: str,
                        profile: Optional[Dict[str, Any]] = None) -> List[Any]:
    """All BodySlotSpecs that apply to this character (species + applies_to).
    ``profile`` overrides the stored profile (callers that only have a
    profile dict, e.g. the outfit renderer's variant path)."""
    if profile is None:
        try:
            from app.models.character import get_character_profile
            profile = get_character_profile(character_name) or {}
        except Exception:
            return []
    specs: List[Any] = []
    for pkg in _species_packages_for(profile):
        for spec in pkg.body_slots:
            if _slot_applies(spec, profile):
                specs.append(spec)
    return specs


# ---------------------------------------------------------------------------
# Values (per character, in the profile — master data, not runtime state)
# ---------------------------------------------------------------------------

def slot_values(character_name: str) -> Dict[str, Dict[str, Any]]:
    """Stored attribute values: ``{slot_id: {attr: value}}``."""
    try:
        from app.models.character import get_character_profile
        profile = get_character_profile(character_name) or {}
    except Exception:
        return {}
    vals = profile.get("body_slots")
    return dict(vals) if isinstance(vals, dict) else {}


def set_slot_value(character_name: str, slot_id: str, attr: str, value: Any) -> bool:
    """Editor API: store one attribute value (empty value removes it)."""
    from app.core.keyed_lock import keyed_lock
    from app.models.character import get_character_profile, save_character_profile
    # Read AND write under the per-character profile lock (DATA-3): the save
    # rewrites the whole profile_json blob, so a stale read here drops every
    # field a concurrent writer stored. Leaf span, nothing else locks inside.
    with keyed_lock("character_profile", character_name):
        profile = get_character_profile(character_name) or {}
        vals = dict(profile.get("body_slots") or {})
        slot = dict(vals.get(slot_id) or {})
        if value in (None, ""):
            slot.pop(attr, None)
        else:
            slot[attr] = value
        if slot:
            vals[slot_id] = slot
        else:
            vals.pop(slot_id, None)
        profile["body_slots"] = vals
        return save_character_profile(character_name, profile)


# ---------------------------------------------------------------------------
# Visibility & prompt fragments
# ---------------------------------------------------------------------------

def is_slot_exposed(spec, profile: Dict[str, Any]) -> bool:
    """Exposed = none of the covering clothing slots holds a piece.
    Slots without ``covered_by`` count as exposed (always visible). A
    free-text wardrobe has no pieces: there the binary dressed state decides
    (``outfit_worn`` off = every covered slot is exposed)."""
    if not spec.covered_by:
        return True
    from app.core.outfit_renderer import is_free_text_wardrobe, is_outfit_worn
    if is_free_text_wardrobe(profile):
        return not is_outfit_worn(profile)
    equipped = dict(profile.get("equipped_pieces") or {})
    return not any(equipped.get(slot) for slot in spec.covered_by)


def attribute_default(decl: Dict[str, Any], profile: Dict[str, Any]) -> Optional[str]:
    """The template-scoped fallback of one slot attribute, or None.

    Declared as ``default: {apply_to: <selector>, value: <text>,
    by: {<profile field>: {<field value>: <text>}}}``: ``by`` is tried
    first (case-insensitive), ``value`` is the rest; an unmatched default
    without ``value`` resolves to "" (the word vanishes). None = no default
    applies to this character's template — the attribute stays required."""
    spec = decl.get("default")
    if not isinstance(spec, dict):
        return None
    tmpl_name = (profile.get("template") or "").strip()
    if not tmpl_name:
        return None
    try:
        from app.models.character_template import fragment_applies, get_template
        if not fragment_applies({"apply_to": spec.get("apply_to")}, tmpl_name,
                                get_template(tmpl_name) or {}):
            return None
    except Exception:
        return None
    for field_name, table in (spec.get("by") or {}).items():
        if not isinstance(table, dict):
            continue
        own = normalize_condition_value(profile.get(field_name))
        for key, text in table.items():
            if normalize_condition_value(key) == own:
                return str(text or "").strip()
    return str(spec.get("value") or "").strip()


def undressed_prompt(profile: Dict[str, Any]) -> str:
    """The package-declared text of an undressed free-text character ("" =
    none declared for this template; the caller keeps its own)."""
    for pkg in _species_packages_for(profile or {}):
        if pkg.undressed_prompt:
            return pkg.undressed_prompt
    return ""


def _format_if_complete(text: str, values: Dict[str, str]) -> str:
    """Render ``{attr}`` placeholders; empty result when any referenced
    attribute has no value (a half-filled fragment is worse than none)."""
    if not text:
        return ""
    try:
        fields = [f for _, f, _, _ in Formatter().parse(text) if f]
    except ValueError:
        return ""
    if any(not (values.get(f) or "").strip() for f in fields):
        return ""
    try:
        return text.format(**values).strip()
    except (KeyError, IndexError):
        return ""


def mesh_part_active(spec, profile: Dict[str, Any]) -> bool:
    """Whether an applicable slot selects its procedural part variant."""
    return bool(spec.mesh_part and _slot_applies(spec, profile)
                and any(spec is slot for slot in slots_for_character("", profile=profile))
                and ((profile.get("body_slots") or {}).get(spec.id) or {}).get(spec.mesh_part.switch) == "on")


def prompt_fragments(character_name: str,
                     face_only: bool = False,
                     profile: Optional[Dict[str, Any]] = None,
                     back_view: bool = False,
                     mesh_input: bool = False) -> Dict[str, List[str]]:
    """Prompt fragments for all applicable slots.

    Returns ``{"general": [...], "exposed": [...]}`` — general carries
    ``always`` plus (while covered) ``covered`` fragments and belongs into
    the person description (F1); exposed renders only while uncovered.
    ``face_only`` keeps only slots declared ``face: true`` (portrait/
    expression prompts — hair/eyes/skin, never body or NSFW slots).
    ``back_view`` keeps only EXPOSED fragments of slots declared
    ``back: true`` (a render seen from behind); the general fragments are
    unaffected — they describe the whole person, not one side of it.
    """
    specs = slots_for_character(character_name, profile=profile)
    if face_only:
        specs = [s for s in specs if getattr(s, "face", False)]
    if not specs:
        return {"general": [], "exposed": []}
    if profile is None:
        try:
            from app.models.character import get_character_profile
            profile = get_character_profile(character_name) or {}
        except Exception:
            return {"general": [], "exposed": []}
    stored = profile.get("body_slots")
    stored = dict(stored) if isinstance(stored, dict) else {}

    general: List[str] = []
    exposed: List[str] = []

    def _render(tpl: str, vals: Dict[str, str], lenient: bool = False,
                optional: frozenset = frozenset()) -> str:
        """Attribute placeholders are REQUIRED (missing value -> the whole
        fragment drops) — unless ``lenient`` (the per-character
        exposed_always flag): then empty attributes simply vanish from the
        text ('exposed {size} part' -> 'exposed part'); ``optional``
        names the attributes a template default stands in for, which vanish
        the same way. Every OTHER
        {placeholder} resolves OPTIONALLY from the character's state flags:
        value-carrying flags (body_reaction="shivering") render their string,
        unset/boolean flags render empty — whitespace artifacts squashed."""
        if not tpl:
            return ""
        import re as _re
        placeholders = _re.findall(r"\{(\w+)\}", tpl)
        if not lenient and any(ph in vals and ph not in optional
                               and not (vals.get(ph) or "").strip()
                               for ph in placeholders):
            return ""
        merged = dict(vals)
        for ph in placeholders:
            if ph not in merged:
                if ph == "height":
                    # Height is a profile field in CENTIMETRES now (it used to
                    # be a word in this very slot). Prompts want the word, so
                    # the number is rendered as the phrase it always was.
                    from app.core.height import height_phrase
                    merged[ph] = height_phrase(profile, character_name)
                    continue
                v = profile.get(ph)
                merged[ph] = v.strip() if isinstance(v, str) else ""
        try:
            out = tpl.format(**merged)
        except (KeyError, IndexError, ValueError):
            return ""
        out = _re.sub(r"\s{2,}", " ", out)
        out = _re.sub(r"\s+,", ",", out)
        return out.strip(" ,")

    for spec in specs:
        slot_stored = stored.get(spec.id) or {}
        vals = {attr: str(slot_stored.get(attr, "") or "")
                for attr in spec.attributes}
        frag = _render(spec.prompt.get("always", ""), vals)
        if frag:
            general.append(frag)
        if is_slot_exposed(spec, profile) and not (back_view and not spec.back):
            # Per-character override of the exposed fragment (stored under
            # the reserved 'exposed_prompt' slot value); the manifest text
            # is only the default. Placeholders resolve in both.
            tpl = (str(slot_stored.get("exposed_prompt", "") or "").strip()
                   or spec.prompt.get("exposed", ""))
            if mesh_input and mesh_part_active(spec, profile):
                tpl = spec.mesh_part.tpose_prompt
            exposed_vals = dict(vals)
            defaulted = set()
            for attr, decl in spec.attributes.items():
                if not exposed_vals[attr].strip():
                    fallback = attribute_default(decl, profile)
                    if fallback is not None:
                        exposed_vals[attr] = fallback
                        defaulted.add(attr)
            frag = _render(tpl, exposed_vals, lenient=bool(slot_stored.get("exposed_always")),
                           optional=frozenset(defaulted))
            if frag:
                exposed.append(frag)
        else:
            frag = _render(spec.prompt.get("covered", ""), vals)
            if frag:
                general.append(frag)
    return {"general": general, "exposed": exposed}


def exposed_slot_loras(character_name: str,
                       profile: Optional[Dict[str, Any]] = None,
                       equipped_pieces: Optional[Dict[str, str]] = None,
                       back_view: bool = False,
                       mesh_input: bool = False) -> List[Dict[str, Any]]:
    """LoRAs of currently EXPOSED body slots (lora_select attribute values),
    merged into image-generation inputs by
    the variant/expression path. Replaces the former per-clothing-slot
    override LoRAs. Works purely from ``profile`` when no name is given
    (outfit renderer's variant path); ``equipped_pieces`` overrides the
    profile's equipped state (outfit-set previews). ``back_view`` follows the
    fragments: a LoRA whose slot is not visible from behind would render what
    the prompt no longer asks for."""
    if profile is None:
        try:
            from app.models.character import get_character_profile
            profile = get_character_profile(character_name) or {}
        except Exception:
            return []
    specs = slots_for_character(character_name, profile=profile)
    if not specs:
        return []
    if equipped_pieces is not None:
        profile = dict(profile)
        profile["equipped_pieces"] = equipped_pieces
    stored = profile.get("body_slots")
    stored = dict(stored) if isinstance(stored, dict) else {}
    out: List[Dict[str, Any]] = []
    seen = set()
    for spec in specs:
        if not is_slot_exposed(spec, profile):
            continue
        if back_view and not spec.back:
            continue
        if mesh_input and mesh_part_active(spec, profile):
            for attr, decl in spec.attributes.items():
                name = str((stored.get(spec.id) or {}).get(attr, "") or "").strip()
                if decl.get("type") == "lora_select" and name and name.lower() != "none":
                    logger.info("Mesh input part dropped LoRA %s", name)
            continue
        for attr, decl in spec.attributes.items():
            if str(decl.get("type", "")) != "lora_select":
                continue
            slot_vals = stored.get(spec.id) or {}
            name = str(slot_vals.get(attr, "") or "").strip()
            if name and name.lower() != "none" and name not in seen:
                try:
                    strength = float(slot_vals.get(f"{attr}_strength") or 1.0)
                except (TypeError, ValueError):
                    strength = 1.0
                out.append({"name": name, "strength": strength})
                seen.add(name)
    return out


def interest_alias_tables(character_name: str) -> List[Any]:
    """Attraction alias tables from the character's slot declarations.

    Each slot attribute may declare ``interest_aliases``
    ({canonical_value: [phrase, ...]}). Returns
    [(phrases_tuple, "slot.attr", {canonical_value}), ...] — the
    relationship engine matches phrases in the OTHER side's
    romantic_interests text against this character's slot values. SFW
    basics live in the human package, explicit slang in the NSFW pack —
    no alias table is hardcoded in core (R1)."""
    out: List[Any] = []
    for spec in slots_for_character(character_name):
        for attr, decl in spec.attributes.items():
            aliases = decl.get("interest_aliases")
            if not isinstance(aliases, dict):
                continue
            for canonical, phrase_list in aliases.items():
                if not isinstance(phrase_list, list):
                    continue
                phrases = tuple(str(p).lower() for p in phrase_list
                                if isinstance(p, str) and str(p).strip())
                if phrases:
                    out.append((phrases, f"{spec.id}.{attr}",
                                {str(canonical).lower()}))
    # Height left the human package for a core profile field (app/core/height.py)
    # — core carries its attraction aliases now, injected under the SAME
    # build.height key the slot used before the move (the value comes from
    # slot_attr_values below, derived from the cm field via describe()).
    from app.core.height import HEIGHT_INTEREST_ALIASES
    for canonical, phrase_list in HEIGHT_INTEREST_ALIASES.items():
        phrases = tuple(str(p).lower() for p in phrase_list if str(p).strip())
        if phrases:
            out.append((phrases, "build.height", {str(canonical).lower()}))
    return out


def slot_attr_values(character_name: str) -> Dict[str, str]:
    """Flat {"slot.attr": value} map of the character's stored slot values
    (lowercased) — the attraction engine's attribute source."""
    out: Dict[str, str] = {}
    vals = slot_values(character_name)
    for spec in slots_for_character(character_name):
        for attr, decl in spec.attributes.items():
            if str(decl.get("type", "")) == "lora_select":
                continue  # technical, never an attraction attribute
            v = str((vals.get(spec.id) or {}).get(attr, "") or "").strip().lower()
            if v:
                out[f"{spec.id}.{attr}"] = v
    # Height is a core profile field now; derive its bucket word (the value the
    # build.height aliases match against) from the cm field. "" for a
    # non-humanoid or an unset height — no build.height entry, no match.
    from app.core.height import height_word
    from app.models.character import get_character_profile
    word = height_word(get_character_profile(character_name) or {}, character_name)
    if word:
        out["build.height"] = word
    return out


def all_interest_alias_phrases() -> List[str]:
    """Example phrases from ALL loaded species packages' body-slot
    interest_aliases — for the romantic-interests help panel. SFW basics
    (human: hair/build) plus, when installed, the NSFW pack's explicit
    slang. Deduped, one representative phrase per canonical value."""
    from app.plugins.registry import packages
    out: List[str] = []
    seen = set()
    for pkg in packages():
        for spec in getattr(pkg, "body_slots", []) or []:
            for attr, decl in spec.attributes.items():
                aliases = decl.get("interest_aliases")
                if not isinstance(aliases, dict):
                    continue
                for phrases in aliases.values():
                    if isinstance(phrases, list) and phrases:
                        first = str(phrases[0]).strip()
                        if first and first.lower() not in seen:
                            seen.add(first.lower())
                            out.append(first)
    # Height moved to a core field — add its example phrases too, so the help
    # panel still shows that size preferences work.
    from app.core.height import HEIGHT_INTEREST_ALIASES
    for phrases in HEIGHT_INTEREST_ALIASES.values():
        first = str(phrases[0]).strip() if phrases else ""
        if first and first.lower() not in seen:
            seen.add(first.lower())
            out.append(first)
    return out


def being_for_character(character_name: str) -> str:
    """Prompt noun for what kind of being the character is ('person',
    'animal', ...) — declared by the species package (manifest ``being``);
    default 'person'. Used by scene composition to phrase subject counts
    correctly ('exactly one person and one animal')."""
    try:
        from app.models.character import get_character_profile
        profile = get_character_profile(character_name) or {}
        for pkg in _species_packages_for(profile):
            if getattr(pkg, "being", ""):
                return pkg.being
    except Exception:
        pass
    return "person"


def appearance_suffix(character_name: str, face_only: bool = False,
                      profile: Optional[Dict[str, Any]] = None,
                      back_view: bool = False,
                      mesh_input: bool = False) -> str:
    """Combined fragment text appended to the character's appearance
    (PromptBuilder; face_only for portrait/expression prompts; ``profile``
    overrides the stored profile for dry-run previews). Empty without
    species packages — safe no-op.

    ``back_view=True`` is a render seen from behind: only exposed fragments
    of slots declared ``back: true`` survive."""
    frags = prompt_fragments(character_name, face_only=face_only,
                             profile=profile, back_view=back_view, mesh_input=mesh_input)
    parts = frags["general"] + frags["exposed"]
    return ", ".join(parts)


# ---------------------------------------------------------------------------
# Topology & silhouette
# ---------------------------------------------------------------------------

def declared_piece_slots(character_name: str) -> Optional[Tuple[Tuple[str, ...], Dict[str, str]]]:
    """Species-declared clothing topology as ``(slot_ids, labels)`` — or
    None when no species package declares one (callers keep their core
    default, including its own display order/labels)."""
    try:
        from app.models.character import get_character_profile
        profile = get_character_profile(character_name) or {}
        for pkg in _species_packages_for(profile):
            if pkg.piece_slots:
                return tuple(pkg.piece_slots), dict(pkg.piece_slot_labels)
    except Exception as e:
        logger.debug("piece slots for %s failed: %s", character_name, e)
    return None


def piece_slots_for_character(character_name: str) -> Tuple[str, ...]:
    """Effective clothing-slot topology: the species package's
    ``piece_slots`` when declared, otherwise the core default
    (inventory.VALID_PIECE_SLOTS)."""
    declared = declared_piece_slots(character_name)
    if declared:
        return declared[0]
    from app.models.inventory import VALID_PIECE_SLOTS
    return tuple(VALID_PIECE_SLOTS)


def silhouette_for_character(character_name: str) -> Optional[Dict[str, Any]]:
    """Silhouette declaration of the character's species package (or None).
    Returns ``{"package_id", "asset", "dir"}`` — the UI route resolves the
    asset file relative to the package dir."""
    try:
        from app.models.character import get_character_profile
        profile = get_character_profile(character_name) or {}
    except Exception:
        return None
    for pkg in _species_packages_for(profile):
        if pkg.silhouette.get("asset"):
            return {"package_id": pkg.id,
                    "asset": pkg.silhouette["asset"],
                    "dir": str(pkg.dir),
                    **{k: v for k, v in pkg.silhouette.items() if k != "asset"}}
    return None


def filter_mesh_input_loras(loras, profile):
    """Drop LoRAs matching active exposed part declarations for mesh inputs."""
    import fnmatch
    patterns = [pattern.casefold()
                for slot in slots_for_character("", profile=profile)
                if mesh_part_active(slot, profile) and is_slot_exposed(slot, profile)
                for pattern in slot.mesh_part.lora_patterns]
    kept = []
    for lora in loras:
        name = str(lora.get("name", ""))
        if any(fnmatch.fnmatchcase(name.casefold(), pattern) for pattern in patterns):
            logger.info("Mesh input part dropped LoRA %s", name)
        else:
            kept.append(lora)
    return kept
