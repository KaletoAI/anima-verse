"""Fold negative-prompt terms into the positive prompt.

Distilled / guidance-free models (Z-Image Turbo, Flux, Qwen-Image) render
without CFG and therefore have NO negative conditioning: whatever travels in
``negative_prompt`` is dropped by the backend without a trace. Those backends
carry ``supports_negative_prompt = false`` in the config; the central handoff
(:meth:`app.imagegen.base.ImageBackend.generate`) then folds every negative
term into the positive prompt as an explicit negation instead of losing it —
"no fog, no trees" is at least a token the model reads.

Pure function, no config and no backend access: prompt + negative + family
in, folded prompt + the folded items out. The family decides the SHAPE only
(prose sentence vs. comma tags), exactly like the prompt adapters.
"""
from __future__ import annotations

import re
from typing import List, Tuple

# A leading negation the caller already wrote into the negative ("no fog") —
# stripped so the fold does not produce "no no fog".
_NEG_PREFIX = re.compile(r"^(?:no|without)\s+", re.IGNORECASE)


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
