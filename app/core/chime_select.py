"""Who may chime in on a line that was not addressed to them.

An utterance in a room obliges its addressees to answer; everyone else is a
bystander. This module decides — server-side, BEFORE any LLM is called —
whether a bystander gets to chime in at all, and which one. At most ONE
bystander per line (plan ``plan-gespraechs-auswahl.md`` § 3.2, decision E2).

The rules, in order:

1. **Busy** — a candidate whose current conversation partner is neither the
   speaker nor one of the addressees is stuck in a foreign pair and scores 0.
2. **Mentioned** — a candidate whose FULL name occurs as a whole word in the
   line is part of that line and wins outright, busy or not; being named by
   the speaker pulls them out of whatever pair they were in. Several
   mentions: the one named first in the text.
3. **Otherwise** ``score = chattiness x rel x aim`` with
   ``rel = 0.5 + strength/100`` (relationship candidate <-> speaker, 0..100;
   without a relationship 10 -> 0.6) and ``aim = AIM_FACTOR`` when the line
   had addressees at all (a targeted line invites third parties much less),
   else 1.0. Clamped to [0, 1].

The draw is ``p_any = max(score)``: with probability ``1 - p_any`` nobody
chimes in, otherwise one candidate is picked weighted by score.

Only the FULL character name counts as a mention — first names are never
resolved to a full name (repo rule, decision E5).

Everything here is pure: candidates (relationship strength, conversation
partner) are assembled by the caller from the world; the only world read is
``effective_chattiness``, which resolves the location override against the
world default.
"""
import logging
import random
import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence

logger = logging.getLogger(__name__)

# A line WITH addressees invites bystanders only a fraction as much as a line
# spoken to the room at large.
AIM_FACTOR = 0.3

# Relationship strength assumed when the two never met: rel = 0.5 + 10/100 = 0.6
NO_RELATIONSHIP_STRENGTH = 10.0

# Fallback whenever neither the location nor the world config yields a number.
DEFAULT_CHATTINESS = 0.5


@dataclass(frozen=True)
class Candidate:
    """One bystander that could chime in.

    ``strength`` is the relationship strength (0..100) towards the speaker,
    ``NO_RELATIONSHIP_STRENGTH`` when the two have no relationship at all.
    ``partner`` is the candidate's current conversation partner (derived from
    the utterance log, see ``conversation_pairs``) or None.
    """

    name: str
    strength: float = NO_RELATIONSHIP_STRENGTH
    partner: Optional[str] = None


def _clamp01(value: float) -> float:
    """Clamp a number into [0, 1]."""
    return 0.0 if value < 0 else (1.0 if value > 1 else float(value))


def mentioned_names(text: str, names: Iterable[str]) -> List[str]:
    """Names whose FULL name occurs as a whole word in ``text``.

    Case-insensitive, ordered by first position in the text. A name that
    contains spaces matches as the whole phrase. A first name alone is never
    matched against a full name (repo rule) — the caller passes exactly the
    names it wants matched, and each is matched literally.
    """
    if not text:
        return []
    found = []
    for name in names:
        if not name or not name.strip():
            continue
        pattern = re.compile(r"\b" + re.escape(name.strip()) + r"\b",
                             re.IGNORECASE)
        match = pattern.search(text)
        if match:
            found.append((match.start(), name))
    found.sort(key=lambda pair: pair[0])
    return [name for _, name in found]


def chime_scores(candidates: Iterable[Candidate], *, speaker: str,
                 addressees: Sequence[str], content: str,
                 chattiness: float) -> Dict[str, float]:
    """Score every candidate in [0, 1] (plan § 3.2 steps 3-5).

    Busy candidates score 0, mentioned ones 1.0, the rest follow the
    chattiness formula. The returned dict carries every candidate, zeros
    included.
    """
    candidates = list(candidates)
    engaged = {speaker} | set(addressees or ())
    mentioned = set(mentioned_names(content or "",
                                    [c.name for c in candidates]))
    aim = AIM_FACTOR if addressees else 1.0
    chattiness = _clamp01(chattiness)

    scores: Dict[str, float] = {}
    for cand in candidates:
        if cand.name in mentioned:
            # Being named makes the candidate part of THIS line — a foreign
            # pair does not shield them.
            scores[cand.name] = 1.0
            continue
        if cand.partner and cand.partner not in engaged:
            scores[cand.name] = 0.0
            continue
        rel = 0.5 + float(cand.strength) / 100.0
        scores[cand.name] = _clamp01(chattiness * rel * aim)
    return scores


def select_chimer(candidates: Iterable[Candidate], *, speaker: str,
                  addressees: Sequence[str], content: str, chattiness: float,
                  always_someone: bool = False,
                  rng: Optional[random.Random] = None) -> Optional[str]:
    """Pick at most ONE bystander that may chime in, or None.

    ``always_someone`` forces the draw to succeed (``p_any = 1.0``) — the
    avatar speaking to the room must never talk into the void (decision E6).
    It cannot conjure a speaker out of nothing: if every score is 0, nobody
    chimes in.
    """
    candidates = list(candidates)
    if not candidates:
        return None
    rng = rng or random.Random()

    mentioned = mentioned_names(content or "", [c.name for c in candidates])
    if mentioned:
        # Named in the line — wins outright, in text order.
        return mentioned[0]

    scores = chime_scores(candidates, speaker=speaker, addressees=addressees,
                          content=content, chattiness=chattiness)
    names = [name for name, score in scores.items() if score > 0]
    if not names:
        return None
    weights = [scores[name] for name in names]

    p_any = 1.0 if always_someone else max(weights)
    if rng.random() >= p_any:
        return None
    return rng.choices(names, weights=weights)[0]


def effective_chattiness(location: Optional[dict]) -> float:
    """Chattiness for a location: its own override, else the world default.

    The location may carry a ``chattiness`` field; empty/missing/unparsable
    falls back to ``chat.chattiness`` from the world config. The result is
    always clamped to [0, 1] — a chat must never die over a bad number.
    """
    try:
        raw = (location or {}).get("chattiness")
        if raw is not None and str(raw).strip() != "":
            try:
                return _clamp01(float(raw))
            except (TypeError, ValueError):
                pass
        from app.core import config as _cfg
        return _clamp01(float(_cfg.get("chat.chattiness", DEFAULT_CHATTINESS)))
    except Exception:
        logger.debug("effective_chattiness fell back to the default",
                     exc_info=True)
        return DEFAULT_CHATTINESS
