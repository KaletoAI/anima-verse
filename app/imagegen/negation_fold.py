"""Fold negative-prompt terms into the positive prompt.

Distilled / guidance-free models (Z-Image Turbo, Flux, Qwen-Image) render
without CFG and therefore have NO negative conditioning: whatever travels in
``negative_prompt`` is dropped by the backend without a trace. Those backends
carry ``supports_negative_prompt = "no"`` (or ``"auto"`` with a natural
family) in the config; the central handoff
(:meth:`app.imagegen.base.ImageBackend.generate`) then folds every negative
term into the positive prompt as an explicit negation instead of losing it —
"no fog, no trees" is at least a token the model reads.

Two pieces live here, and both are the ONE place for their question:

* :func:`fold_negatives` — pure: prompt + negative + family in, folded prompt
  and the folded items out. The family decides the SHAPE only (prose sentence
  vs. comma tags), exactly like the prompt adapters.
* :func:`backend_supports_negative` — resolves the tri-state backend setting
  (``auto``/``yes``/``no``) into the bool every caller needs: the handoff, the
  preview composer and the option payloads the render dialogs read.
"""
from __future__ import annotations

import re
from typing import Any, List, Tuple

# Tri-state setting values, tolerant to what the config bridge produces
# (a real bool, the env string "true"/"false", an empty field, ``None``).
_TRUE_VALUES = ("yes", "true", "1", "on")
_FALSE_VALUES = ("no", "false", "0", "off")

# A leading negation the caller already wrote into the negative ("no fog") —
# stripped so the fold does not produce "no no fog".
_NEG_PREFIX = re.compile(r"^(?:no|without)\s+", re.IGNORECASE)


def resolve_family(image_family: str = "", model: str = "") -> str:
    """Prompt family of a backend: ``"natural"`` or ``"keywords"``.

    The configured ``image_family`` wins; when it is empty the family comes
    from the model name through the SAME chain the prompt composition uses
    (``get_target_model`` -> ``image_model_to_family``: z_image -> keywords,
    qwen/flux -> natural). Falls back to ``"keywords"`` when the config layer
    is unavailable (import-only contexts, smoke scripts).
    """
    family = (image_family or "").strip().lower()
    if family in ("natural", "keywords"):
        return family
    try:
        from app.core.config import image_model_to_family
        from app.core.prompt_adapters import get_target_model
        return image_model_to_family(
            get_target_model(image_family or "", model or ""))
    except Exception:
        return "keywords"


def backend_supports_negative(setting: Any, image_family: str = "",
                              model: str = "") -> bool:
    """Does this backend have a negative input? The ONE resolution rule.

    Args:
        setting: The backend's ``supports_negative_prompt`` config field —
            ``"auto"`` / ``"yes"`` / ``"no"``. Tolerant on purpose: ``None``,
            ``""``, a real bool and the env strings ``"true"``/``"false"``/
            ``"1"``/``"0"`` all resolve, because the value travels through the
            config -> env bridge as a string and older worlds still hold a bool.
        image_family: The backend's configured family (``natural``/``keywords``).
        model: The backend's model id — used when no family is configured.

    Returns:
        ``True`` when a separate negative prompt reaches the engine. For
        ``auto`` the prompt family decides: natural-family models (Flux,
        Qwen-Image) are distilled / guidance-free and have NO negative input,
        keyword-family models (SD/SDXL, A1111, Z-Image with CFG) have one.
        Z-Image **Turbo** is the known exception auto gets wrong — it is
        keyword-family but guidance-free, so it needs an explicit ``"no"``.
    """
    value = "" if setting is None else str(setting).strip().lower()
    if value in _TRUE_VALUES:
        return True
    if value in _FALSE_VALUES:
        return False
    # "" / "auto" / anything unknown -> let the prompt family decide.
    return resolve_family(image_family, model) != "natural"


def _already_negated(prompt_lower: str, item_lower: str) -> bool:
    """True when the prompt already negates this exact item.

    Word-anchored on purpose: the plain substring "no fog" also hits inside
    "casino fog". Only a real negation counts as a duplicate — a POSITIVE
    mention of the word is never interpreted (guessing there would silently
    drop terms the use case wants negated).
    """
    return bool(re.search(r"\b(?:no|without)\s+" + re.escape(item_lower),
                          prompt_lower))


def fold_negatives(prompt: str, negative: str,
                   family: str) -> Tuple[str, List[str]]:
    """Append the negative's terms to the prompt as negations.

    Args:
        prompt: The positive prompt as it would go to the engine.
        negative: The negative prompt, comma-separated (use-case default +
            negations moved out of the subject + dialog input).
        family: ``"natural"`` (prose) or ``"keywords"`` (comma tags);
            anything else is treated as keywords.

    Returns:
        ``(new_prompt, folded_items)``. Items are split on commas, trimmed,
        de-duplicated case-insensitively (order kept) like
        :func:`app.core.prompt_compose.merge_tags`, and terms the prompt
        already negates are skipped. An empty negative (or one that adds
        nothing) hands the prompt back unchanged with an empty list.
    """
    prompt = prompt or ""
    prompt_lower = prompt.lower()
    items: List[str] = []
    seen = set()
    for raw in (negative or "").split(","):
        item = _NEG_PREFIX.sub("", raw.strip()).strip()
        if not item:
            continue
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        if _already_negated(prompt_lower, key):
            continue
        items.append(item)
    if not items:
        return prompt, []

    if (family or "").strip().lower() == "natural":
        clause = "No " + ", no ".join(items) + "."
        base = prompt.rstrip()
        if base and base[-1] not in ".!?":
            base += "."
        new_prompt = f"{base} {clause}" if base else clause
    else:
        tags = ", ".join(f"no {item}" for item in items)
        base = prompt.rstrip().rstrip(",").rstrip()
        new_prompt = f"{base}, {tags}" if base else tags
    return new_prompt, items
