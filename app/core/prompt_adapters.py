"""Model-spezifische Prompt-Adapter.

Jeder Image-Backend (Z-Image, Qwen, Flux) erwartet einen anderen Prompt-Stil.
Diese Adapter rendern den strukturierten `PromptVariables`-Zustand deterministisch
in den jeweiligen Ziel-Stil. Optional kann ein LLM-Enhancer den Template-Output
ueberschreiben (gesteuert ueber die Workflow-Konfiguration, nicht pro Character).

Architektur:
    PromptVariables (strukturiert)
        ↓ render_<target_model>()
    Template-Prompt (deterministisch)
        ↓ maybe_enhance_via_llm() — optional, via Workflow-Config
    Finaler Prompt → Image-Backend
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional, Tuple

from app.core.log import get_logger
from app.core.prompt_builder import PromptVariables

logger = get_logger("prompt_adapters")


# Valid target-model values. Set via the backend config field `image_family`.
TARGET_MODELS = ("z_image", "qwen", "flux")


def get_target_model(image_family: str = "", backend_model: str = "") -> str:
    """Determines the target model from the backend's image family.

    Args:
        image_family: Value from the backend config (natural/keywords).
        backend_model: Model ID/URN of the backend (e.g.
            "Qwen/Qwen-Image-2.0", "black-forest-labs/FLUX.2-pro",
            "urn:air:zimageturbo:checkpoint:civitai:..."). Used as the last
            fallback, derived from the model name.

    Returns:
        "z_image" | "qwen" | "flux". Default "z_image" when unknown.
    """
    normalized = (image_family or "").strip().lower().replace("-", "_").replace(" ", "_")
    # Image family (natural/keywords) -> render target. keywords = comma tags
    # (z_image renderer), natural = prose/labeled sections (qwen renderer,
    # identical to flux).
    if normalized == "keywords":
        return "z_image"
    if normalized == "natural":
        return "qwen"
    if normalized in TARGET_MODELS:
        return normalized

    # Fallback: derive from the backend model name.
    # IMPORTANT: order — check z_image before qwen, because Z-Image models
    # appear on CivitAI URNs as "zimage..." (NOT as "qwen") and would
    # otherwise be misclassified as qwen.
    if backend_model:
        bm = backend_model.lower()
        if "z_image" in bm or "z-image" in bm or "zimage" in bm:
            return "z_image"
        if "qwen" in bm and "image" in bm:
            # only Qwen-Image models (not Qwen text LLMs) count as the qwen style
            return "qwen"
        if "flux" in bm:
            return "flux"

    return "z_image"  # conservative default




#: The sentence every picture of two or more people carries once (plan point 1): a person drawn twice is the most
#: common failure of a group render. Not added when the style or the scene already says it.
ONCE_RULE = "Each person appears once."
_ONCE_SAID = ("appears once", "appears exactly once", "appear once", "appear exactly once")


def _once_said(pv: PromptVariables) -> bool:
    text = f"{pv.prompt_style} {pv.scene_prompt}".lower()
    return any(p in text for p in _ONCE_SAID)


def _person_ref(pv: PromptVariables, idx: int, text: str) -> str:
    """``text`` of person ``idx`` (it starts with the person's label, ``"Kai, …"``) with the slot that holds the
    person's picture right after the label: ``"Kai (the person in <ref 2>), …"``. Only the label at the START is
    marked, never a later mention of the name; a person without a slot keeps ``text``."""
    slot = (pv.person_slot or {}).get(idx)
    if not slot or not text or idx < 1 or idx > len(pv.persons):
        return text
    person = pv.persons[idx - 1]
    label = person.actor_label or person.name
    if not label or not text.startswith(label):
        return text
    return f"{label} (the person in <ref {slot}>){text[len(label):]}"


def _item_refs(pv: PromptVariables) -> str:
    """``"the chair from <ref 4>, the lamp from <ref 5>"`` for the items in a slot; empty without one."""
    return ", ".join(f"the {name} from <ref {slot}>"
                     for name, slot in sorted((pv.item_slot_of or {}).items(), key=lambda kv: kv[1]) if name)


def _person_with_outfit(pv: PromptVariables, idx: int, natural: bool) -> str:
    """Baut Personen-Beschreibung fuer einen Slot. `natural`=True liefert Satz."""
    person_txt = _person_ref(pv, idx, pv.prompt_persons.get(idx, ""))
    outfit_txt = pv.prompt_outfits.get(idx, "")
    if not natural:
        parts = [p for p in (person_txt, outfit_txt) if p]
        return ", ".join(parts)

    # Natural language: the outfit as its own sentence
    if person_txt and outfit_txt:
        return f"{person_txt}. {outfit_txt}"
    return person_txt or outfit_txt


def dict_to_canonical(data: Dict[str, Any]) -> PromptVariables:
    """Rekonstruiert PromptVariables aus einem gespeicherten canonical-Dict.

    Inverse zu canonical_to_dict. Wird vom Re-Creation-Dialog genutzt, damit
    Bilder mit den ORIGINAL-Werten neu erzeugt werden koennen (nicht mit dem
    aktuellen Character-State).
    """
    from app.core.prompt_builder import Person  # lokaler Import gegen Zirkularitaet
    pv = PromptVariables()
    pv.persons = [
        Person(
            name=p.get("name", ""),
            appearance=p.get("appearance", ""),
            gender=p.get("gender", ""),
            actor_label=p.get("label", "") or p.get("name", ""),
            is_agent=bool(p.get("is_agent", False)),
            is_user=bool(p.get("is_user", False)))
        for p in (data.get("persons") or [])
    ]
    pv.prompt_persons = {int(k): v for k, v in (data.get("person_prompts") or {}).items()}
    pv.prompt_outfits = {int(k): v for k, v in (data.get("outfits") or {}).items()}
    pv.prompt_pose = data.get("pose", "") or ""
    pv.prompt_expression = data.get("expression", "") or ""
    pv.scene_prompt = data.get("scene", "") or ""
    pv.prompt_mood = data.get("mood", "") or ""
    pv.prompt_activity = data.get("activity", "") or ""
    pv.prompt_location = data.get("location", "") or ""
    pv.personality = data.get("personality_hint", "") or ""
    pv.profile_image_hint = data.get("profile_image_hint", "") or ""
    pv.prompt_style = data.get("style", "") or ""
    pv.negative_prompt = data.get("negative", "") or ""
    return pv


def canonical_to_dict(pv: PromptVariables) -> Dict[str, Any]:
    """Serialisiert PromptVariables in ein JSON-taugliches Dict fuer Metadaten."""
    return {
        "persons": [
            {
                "label": p.actor_label or p.name,
                "name": p.name,
                "appearance": p.appearance,
                "gender": p.gender,
                "is_agent": p.is_agent,
            }
            for p in pv.persons
        ],
        "person_prompts": dict(pv.prompt_persons),
        "outfits": dict(pv.prompt_outfits),
        "pose": pv.prompt_pose,
        "expression": pv.prompt_expression,
        "scene": pv.scene_prompt,
        "mood": pv.prompt_mood,
        "activity": pv.prompt_activity,
        "location": pv.prompt_location,
        "personality_hint": pv.personality,
        "profile_image_hint": pv.profile_image_hint,
        "style": pv.prompt_style,
        "negative": pv.negative_prompt,
    }


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

def render_z_image(pv: PromptVariables) -> Dict[str, str]:
    """Z-Image / SDXL-Stil: Komma-Keywords."""
    parts = []

    for idx in sorted(pv.prompt_persons.keys()):
        parts.append(_person_with_outfit(pv, idx, natural=False))

    if pv.prompt_pose:
        parts.append(pv.prompt_pose)
    if pv.prompt_expression:
        parts.append(pv.prompt_expression)
    if pv.scene_prompt:
        parts.append(pv.scene_prompt)
    if pv.prompt_mood:
        parts.append(pv.prompt_mood)
    if pv.prompt_activity:
        parts.append(pv.prompt_activity)
    _loc_clean = _clean_location_for_prompt(pv.prompt_location)
    if _loc_clean:
        parts.append(_loc_clean)
    if pv.room_slot:
        parts.append(f"the place in <ref {pv.room_slot}>")
    _items = _item_refs(pv)
    if _items:
        parts.append(_items)
    if len([p for p in pv.prompt_persons.values() if p]) >= 2 and not _once_said(pv):
        parts.append(ONCE_RULE.rstrip(".").lower())
    if pv.personality:
        parts.append(pv.personality[:200])
    if pv.profile_image_hint:
        parts.append(pv.profile_image_hint)

    without_style = ", ".join(p for p in parts if p)
    style_full = pv.prompt_style.strip().rstrip(".").strip() or "photorealistic"
    positive = f"{style_full}, {without_style}" if without_style else style_full
    return {
        "input_prompt_positiv": positive,
        "input_prompt_negativ": pv.negative_prompt,
        "prompt_without_style": without_style,
    }


def _outfit_clause(outfit_txt: str) -> str:
    """Extrahiert den Outfit-Teil aus "Name is wearing X" → "wearing X"."""
    if not outfit_txt:
        return ""
    if " is wearing " in outfit_txt:
        _, desc = outfit_txt.split(" is wearing ", 1)
        return f"wearing {desc.strip()}"
    return outfit_txt


def _clean_location_for_prompt(loc: str) -> str:
    """Bereinigt Location-String fuer den Prompt:
    - Strippt Raum-/Location-Name-Praefix ("Hauptraum, A cozy living room...") → "A cozy living room..."
    - Strippt Klammer-Form ("Hauptraum (A cozy ...)") → "A cozy ..."
    - Entfernt "no people"/"no text"/"no person"/"no humans" am Ende
    - Entfernt fuehrendes "setting:"-Label (von alten Backfill-Werten)
    """
    if not loc:
        return ""
    import re as _re
    s = loc.strip()
    # Fuehrendes "setting:" Label entfernen (alte Backfill-Werte)
    s = _re.sub(r"^\s*setting\s*:\s*", "", s, flags=_re.IGNORECASE)
    # "Name, Description" — when the name is short and the description clearly longer
    parts = s.split(",", 1)
    if len(parts) == 2:
        head, rest = parts[0].strip(), parts[1].strip()
        if len(head) <= 25 and len(rest) > 30:
            s = rest
    # "Name (Description)" → "Description"
    m = _re.match(r"^([^(]{1,25})\(\s*(.+?)\s*\)\s*$", s)
    if m:
        s = m.group(2)
    # "no people"/"no text"/"no person"/"no humans" am Ende entfernen
    s = _re.sub(r"[,\s]+no\s+(people|text|person|humans|one)\s*\.?\s*$", "", s, flags=_re.IGNORECASE)
    return s.strip(", .").strip()


#: The head nouns that make a style's first comma token a NOUN PHRASE ("RAW photo", "photorealistic portrait") rather
#: than an adjective ("photorealistic"). A noun phrase names the picture itself, so the summary line must not stack
#: a second picture noun onto it ("A RAW photo group photo of …").
_PICTURE_NOUNS = frozenset((
    "photo", "photograph", "photography", "portrait", "shot", "snapshot", "selfie", "picture", "image", "scene",
    "render", "rendering", "view", "painting", "illustration", "drawing", "artwork", "still", "frame", "model",
))
_NUM_WORDS = {2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine"}


def _with_article(phrase: str) -> str:
    """``phrase`` with a capitalised indefinite article in front ("An oil painting", "A RAW photo")."""
    return ("An " if phrase[:1].lower() in "aeiou" else "A ") + phrase


def summary_line(style_word: str, persons: int, location: str = "") -> str:
    """The first line of a labeled-sections prompt: what the picture is, who is in it, and where.

    ``style_word`` is the first comma token of the use case's style and comes in two kinds:

    * an ADJECTIVE ("photorealistic", the old default) — it qualifies the picture noun the line adds itself:
      "A photorealistic group photo of two people in a cafe." (unchanged since the format exists);
    * a NOUN PHRASE — it starts with an article ("a candid photograph taken with a 35mm lens", every natural-family
      style) or ends in a picture noun ("RAW photo", "photorealistic portrait"). It already names the picture, so
      the line names the subject after it instead of adding a second picture noun:
      "A candid photograph taken with a 35mm lens, showing a group of two people in a cafe."

    ``persons`` = 0 is a scene without people, 1 one person, more a group. The caller strips the location.
    """
    words = style_word.split()
    first = words[0].lower() if words else ""
    last = words[-1].lower().strip(".:;") if words else ""
    if first in ("a", "an", "the") and len(words) > 1:
        head = words[0][:1].upper() + style_word[1:]
    elif last in _PICTURE_NOUNS:
        head = _with_article(style_word)
    else:
        # Adjective form — byte-identical to the line before the noun-phrase rule.
        if persons == 0:
            line = f"{_with_article(style_word)} scene"
        elif persons == 1:
            line = f"{_with_article(style_word)} photo of a person"
        else:
            line = f"{_with_article(style_word)} group photo of {_NUM_WORDS.get(persons, str(persons))} people"
        return (f"{line} in {location}" if location else line) + "."
    if persons == 0:
        line = f"{head}, set in {location}" if location else head
        return line + "."
    who = "a person" if persons == 1 else f"a group of {_NUM_WORDS.get(persons, str(persons))} people"
    return f"{head}, showing {who}" + (f" in {location}" if location else "") + "."


def _render_labeled_sections(pv: PromptVariables) -> Dict[str, str]:
    """Gemeinsames Labeled-Sections-Format fuer Qwen und Flux.

    Aufbau:
        {Summary-Zeile}

        Characters:
        - {Name1}: {appearance}, wearing {outfit}.
        - {Name2}: {appearance}, wearing {outfit}.

        Action: {pose}, {expression}. {activity}. {scene}.
        Setting: {location}.
        Style: {prompt_style complete} [, {mood} atmosphere].
    """
    sections: list[str] = []

    # --- Style + summary adjective from pv.prompt_style ---
    # The whole field goes into the style line. For the summary we take the
    # first comma token as the adjective (e.g. "photorealistic" from
    # "photorealistic, 8k, cinematic lighting").
    style_full = pv.prompt_style.strip().rstrip(".").strip() or "photorealistic"
    style_word = style_full.split(",", 1)[0].strip() or "photorealistic"
    n = len([p for p in pv.prompt_persons.values() if p])
    _loc_clean = _clean_location_for_prompt(pv.prompt_location)
    sections.append(summary_line(style_word, n, _loc_clean))

    # --- Characters ---
    if pv.prompt_persons:
        char_lines = ["Characters:"]
        for idx in sorted(pv.prompt_persons.keys()):
            person_txt = _person_ref(pv, idx, pv.prompt_persons.get(idx, "").strip())
            outfit_clause = _outfit_clause(pv.prompt_outfits.get(idx, "").strip())
            if not person_txt:
                continue
            line = f"- {person_txt}"
            if outfit_clause:
                line += f", {outfit_clause}"
            if not line.endswith("."):
                line += "."
            char_lines.append(line)
        if len(char_lines) > 2 and not _once_said(pv):
            char_lines.append(ONCE_RULE)
        if len(char_lines) > 1:
            sections.append("\n".join(char_lines))

    # --- Action ---
    action_parts = []
    if pv.prompt_pose:
        action_parts.append(pv.prompt_pose)
    if pv.prompt_expression:
        action_parts.append(f"{pv.prompt_expression} expression")
    if pv.prompt_activity:
        action_parts.append(pv.prompt_activity)
    if pv.scene_prompt:
        action_parts.append(pv.scene_prompt)
    if action_parts:
        sections.append("Action: " + ", ".join(action_parts) + ".")

    # --- Mood (its own line, not in the style) ---
    if pv.prompt_mood:
        sections.append(f"Mood: {pv.prompt_mood}.")

    # --- Setting ---
    # The location text is dropped when the room picture sits in a slot
    # (apply_exclusion_rules); the text then names that picture instead.
    if _loc_clean:
        sections.append(f"Setting: {_loc_clean}.")
    elif pv.room_slot:
        sections.append(f"Setting: the place shown in <ref {pv.room_slot}>.")
    _items = _item_refs(pv)
    if _items:
        sections.append(f"Objects: {_items}.")

    # --- Style (komplett aus Config) ---
    sections.append(f"Style: {style_full}.")

    # --- Personality (optional) ---
    if pv.personality:
        sections.append(f"Body language: {pv.personality[:200]}.")
    if pv.profile_image_hint:
        sections.append(pv.profile_image_hint)

    full = "\n\n".join(sections)
    return {
        "input_prompt_positiv": full,
        "input_prompt_negativ": pv.negative_prompt,
        "prompt_without_style": full,
    }


def render_qwen(pv: PromptVariables) -> Dict[str, str]:
    """Qwen: Labeled-Sections-Format (strukturiert mit Characters/Action/Setting/Style)."""
    return _render_labeled_sections(pv)


def render_flux(pv: PromptVariables) -> Dict[str, str]:
    """Flux (2.x / 4B / 9B): Labeled-Sections-Format (identisch zu Qwen)."""
    return _render_labeled_sections(pv)


_RENDERERS = {
    "z_image": render_z_image,
    "qwen": render_qwen,
    "flux": render_flux,
}


def render(pv: PromptVariables, target_model: str) -> Dict[str, str]:
    """Dispatch an den passenden Adapter."""
    renderer = _RENDERERS.get(target_model, render_z_image)
    return renderer(pv)


# ---------------------------------------------------------------------------
# Optional LLM enhancer (central, not per character)
# ---------------------------------------------------------------------------

def maybe_enhance_via_llm(
    template_prompt: str,
    pv: PromptVariables,
    *,
    target_model: str,
    prompt_instruction: str = "") -> Tuple[str, str]:
    """Optionale LLM-Veredelung des Template-Prompts.

    Enhancer nur aktiv wenn:
      - `prompt_instruction` gesetzt (Workflow-Config, zentral)
      - globale LLM-Instance mit task="image_prompt" vorhanden

    Args:
        template_prompt: Ergebnis des deterministischen Adapters.
        pv: PromptVariables fuer Kontext.
        target_model: "z_image" | "qwen" | "flux".
        prompt_instruction: Freitext-Anweisung aus Workflow-Config.

    Returns:
        (final_prompt, method) wobei method in {"template", "template+llm"}.
    """
    if not prompt_instruction.strip():
        return template_prompt, "template"

    logger.info("prompt_enhance: target_model=%s", target_model)
    try:
        from app.core.llm_router import llm_call
        from app.core.prompt_templates import render_task
        system, user = render_task(
            "image_prompt_enhance",
            target_model=target_model,
            prompt_instruction=prompt_instruction.strip(),
            template_prompt=template_prompt)
        response = llm_call(
            task="image_prompt",
            system_prompt=system,
            user_prompt=user)
        enhanced = (response.content or "").strip()
        if not enhanced:
            return template_prompt, "template"
        return enhanced, "template+llm"
    except RuntimeError as e:
        logger.debug("prompt_enhance: kein LLM fuer image_prompt verfuegbar (%s)", e)
        return template_prompt, "template"
    except Exception as e:
        logger.warning("prompt_enhance fehlgeschlagen, Template wird verwendet: %s", e)
        return template_prompt, "template"
