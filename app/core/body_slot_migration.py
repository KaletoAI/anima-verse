"""Body-slot migration — template-select values become slot values.

World-specific and ON DEMAND (user decision, plan-body-slots.md): never
runs automatically; the admin triggers it per world (Game-Admin → Setup)
after a dry-run preview. Two things happen per character:

1. Profile field values are copied into body-slot attribute values. The
   field→attribute mapping is DECLARED by the species packages
   (attribute ``migrate_from`` + optional ``migrate_skip`` value list) —
   this code knows no field or slot name (R1/R4).
2. The migrated ``{field}`` tokens are cleaned out of the appearance
   texts: the texts are comma-segment lists ("{skin_color} skin, {size}
   height, …"), so any segment containing a migrated token is dropped —
   the slot fragments now carry that information (F1). Untouched tokens
   (e.g. {gender}) stay.

Already-set slot values are never overwritten; running twice is safe.
"""
import re
from typing import Any, Dict, List, Tuple

from app.core.log import get_logger

logger = get_logger("body_slot_migration")

_TEXT_FIELDS = ("character_appearance", "face_appearance")


def _mappings_for(character_name: str) -> List[Tuple[Any, str, str, List[str]]]:
    """Declared migrations: [(slot_spec, attr_key, profile_field, skip_values)]."""
    from app.core.body_slots import slots_for_character
    out = []
    for spec in slots_for_character(character_name):
        for attr, decl in spec.attributes.items():
            field = str(decl.get("migrate_from") or "").strip()
            if field:
                skip = [str(x).strip().lower()
                        for x in (decl.get("migrate_skip") or [])]
                out.append((spec, attr, field, skip))
    return out


# Generic attribute glue words: a segment whose remainder (after removing
# the migrated tokens) consists only of these carries no information of its
# own ("{hair_color} hair" -> "hair") and is dropped entirely. Anything else
# in the remainder is real content and stays ("{size} young {gender} goblin"
# -> "young {gender} goblin").
_GLUE_WORDS = {
    "hair", "haare", "haar", "eyes", "eye", "augen", "auge", "skin", "haut",
    "colored", "coloured", "color", "colour", "farbe", "farbene", "farbige",
    "build", "built", "figur", "statur", "körperbau", "koerperbau",
    "tall", "groß", "gross",
    # animal attribute glue (cat package fields)
    "fur", "fell", "pelz", "ears", "ohren", "tail", "schwanz", "markings",
}


def _clean_text(text: str, fields: set) -> Tuple[str, List[str]]:
    """Remove migrated {field} tokens from the appearance text.

    Per comma segment (comma + space — decimal commas like "1,20" stay
    intact): tokens are stripped out of the segment; the segment itself is
    only dropped when nothing but attribute glue words remains. This keeps
    surrounding content that shared a segment with a token.
    """
    if not text or "{" not in text:
        return text, []
    patterns = [re.compile(r"\{" + re.escape(f) + r"\}") for f in fields]
    keep, dropped = [], []
    changed = False
    for seg in re.split(r",\s", text):
        if not any(p.search(seg) for p in patterns):
            keep.append(seg.strip())
            continue
        changed = True
        cleaned = seg
        for p in patterns:
            cleaned = p.sub("", cleaned)
        cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" -–—")
        words = [w for w in re.findall(r"[\wäöüÄÖÜß{}]+", cleaned)]
        substantial = [w for w in words if w.lower() not in _GLUE_WORDS]
        if cleaned and substantial:
            keep.append(cleaned)
            dropped.append(f"{seg.strip()} → {cleaned}")
        else:
            dropped.append(seg.strip())
    if not changed:
        return text, []
    new = ", ".join(s for s in keep if s)
    return new, dropped


def character_plan(character_name: str) -> Dict[str, Any]:
    """Dry-run for one character: value copies + text cleanups."""
    from app.models.character import get_character_profile
    profile = get_character_profile(character_name) or {}
    values = dict(profile.get("body_slots") or {})

    copies: List[Dict[str, str]] = []
    fields: set = set()
    for spec, attr, field, skip in _mappings_for(character_name):
        fields.add(field)  # token cleanup covers ALL declared fields
        raw = str(profile.get(field, "") or "").strip()
        if not raw or raw.lower() in skip:
            continue
        if str((values.get(spec.id) or {}).get(attr, "")).strip():
            continue  # already set — never overwrite
        copies.append({"slot": spec.id, "attr": attr,
                       "field": field, "value": raw})

    texts: Dict[str, Dict[str, Any]] = {}
    if fields:
        for tf in _TEXT_FIELDS:
            txt = str(profile.get(tf, "") or "")
            new, dropped = _clean_text(txt, fields)
            if dropped:
                texts[tf] = {"before": txt, "after": new, "dropped": dropped}

    plan = {"character": character_name, "copies": copies, "texts": texts,
            "changes": bool(copies or texts)}
    if plan["changes"]:
        try:
            plan["prompt_preview"] = _prompt_preview(character_name, profile,
                                                     copies, texts)
        except Exception as e:
            logger.debug("prompt preview failed for %s: %s", character_name, e)
    return plan


def _prompt_preview(character_name: str, profile: Dict[str, Any],
                    copies: List[Dict[str, str]],
                    texts: Dict[str, Dict[str, Any]]) -> Dict[str, str]:
    """Resulting prompts before/after — computed on a SIMULATED profile,
    nothing is saved. Lets the admin judge the migration by its actual
    effect (scene + face prompt) instead of the raw text diff."""
    import copy as _copy
    from app.models.character import get_character_appearance
    from app.models.character_template import get_template, resolve_profile_tokens
    from app.core.body_slots import appearance_suffix
    from app.core.character_ops import _resolve_face_prompt

    tmpl = get_template(profile.get("template", "")) if profile.get("template") else None

    def _join(text: str, suffix: str) -> str:
        text = (text or "").strip().strip(",")
        return f"{text}, {suffix}" if (text and suffix) else (text or suffix)

    scene_before = _join(get_character_appearance(character_name) or "",
                         appearance_suffix(character_name))
    face_before = _resolve_face_prompt(profile, character_name, tmpl)

    sim = _copy.deepcopy(profile)
    slots = dict(sim.get("body_slots") or {})
    for c in copies:
        slot_vals = dict(slots.get(c["slot"]) or {})
        slot_vals[c["attr"]] = c["value"]
        slots[c["slot"]] = slot_vals
    sim["body_slots"] = slots
    for tf, info in (texts or {}).items():
        sim[tf] = info["after"]

    scene_raw = str(sim.get("character_appearance") or "")
    if "{" in scene_raw:
        scene_raw = resolve_profile_tokens(scene_raw, sim, template=tmpl,
                                           target_key="character_appearance")
    scene_after = _join(scene_raw, appearance_suffix(character_name, profile=sim))
    face_after = _resolve_face_prompt(sim, character_name, tmpl)

    return {"scene_before": scene_before, "scene_after": scene_after,
            "face_before": face_before, "face_after": face_after}


def apply_character(character_name: str) -> Dict[str, Any]:
    """Apply the plan for one character (values + text cleanup)."""
    from app.core.body_slots import set_slot_value
    from app.models.character import get_character_profile, save_character_profile
    plan = character_plan(character_name)
    if not plan["changes"]:
        return plan
    for c in plan["copies"]:
        set_slot_value(character_name, c["slot"], c["attr"], c["value"])
    if plan["texts"]:
        profile = get_character_profile(character_name) or {}
        for tf, info in plan["texts"].items():
            profile[tf] = info["after"]
        save_character_profile(character_name, profile)
    logger.info("body-slot migration applied for %s: %d values, %d texts",
                character_name, len(plan["copies"]), len(plan["texts"]))
    return plan


def world_plan() -> Dict[str, Any]:
    """Dry-run over all characters of the active world."""
    from app.models.character import list_available_characters
    plans = []
    for name in list_available_characters():
        try:
            p = character_plan(name)
        except Exception as e:
            logger.warning("migration plan failed for %s: %s", name, e)
            continue
        if p["changes"]:
            plans.append(p)
    return {"characters": plans, "total": len(plans)}


def apply_world() -> Dict[str, Any]:
    """Apply the migration for all characters of the active world."""
    from app.models.character import list_available_characters
    applied = []
    for name in list_available_characters():
        try:
            p = apply_character(name)
        except Exception as e:
            logger.warning("migration apply failed for %s: %s", name, e)
            continue
        if p["changes"]:
            applied.append(p)
    return {"characters": applied, "total": len(applied)}
