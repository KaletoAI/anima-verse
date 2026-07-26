"""Prompt composition — ONE builder for every "style + subject" render.

Until now each render path glued its prompt together with an f-string:
``f"{style}, {subject}"``, plus whatever extra clause the caller injected
afterwards. The café-kitchen case (2026-07-26) showed what that costs: the
style frame arrived first with an inviting placeholder ("with all of its
furniture and decor"), the subject landed ~60 tokens later as an
afterthought, its German negation clause ("Ohne Tische und Stühle") DREW
the very tables it wanted gone, and the room's real size — which the server
knows — never reached the model.

This module composes instead of concatenating:

- **Subject slot** — a use-case style may carry ``{subject}``; the subject
  is woven into the style sentence there instead of being appended.
- **Hints as data** — shape/size/proportion arrive as :class:`ShapeHint`
  objects and are rendered per family (prose vs. comma tags), always
  PREPENDED: early tokens steer diffusion.
- **Negation guard** — standalone negation clauses in the SUBJECT are moved
  into the negative prompt and reported as a warning. Never a silent
  rewrite (that waits for the LLM stage), and never applied to the style:
  the curated styles negate on purpose ("no walls").

Pure builder: no I/O, no DB. The only outside call is the existing
use-case style resolution (in-memory config).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# Below this length ratio a floor plan counts as square enough that the
# verbal multiplier says nothing worth saying.
RATIO_MIN = 1.3
# From here on the plan reads as a corridor rather than merely elongated.
RATIO_NARROW = 2.5


@dataclass
class ShapeHint:
    """The footprint of the thing being rendered, as DATA.

    ``long_m``/``short_m`` are real metres (None = the location has no scale
    anchor, so only the proportion is known); ``ratio`` carries that
    proportion when the metres do not. ``surface`` is the plate the subject
    stands on ("floor slab" indoors, "ground base" outdoors).
    """

    shape: str                      # "rectangular" | "square" | …
    long_m: Optional[float] = None  # real size in metres (None = unknown)
    short_m: Optional[float] = None
    surface: str = "floor slab"     # room_model_outdoor: "ground base"
    fills_frame: bool = True
    ratio: Optional[float] = None   # long/short when the metres are unknown


@dataclass
class Composed:
    """The finished prompt plus everything the caller has to pass on."""

    prompt: str
    negative: str
    warnings: List[str] = field(default_factory=list)
    # use_case, family, style_had_slot, hint_rendered, negations_moved —
    # merged into the caller's log_meta so image_prompts.jsonl can be diffed.
    meta: Dict[str, Any] = field(default_factory=dict)


# ── Hint rendering ────────────────────────────────────────────────────────

def _ratio_of(hint: ShapeHint) -> Optional[float]:
    if hint.ratio and hint.ratio > 0:
        return float(hint.ratio)
    if hint.long_m and hint.short_m and hint.short_m > 0:
        return float(hint.long_m) / float(hint.short_m)
    return None


def _metres(value: float) -> str:
    """Half-metre precision — a diffusion model cannot follow "1.87 m", and an
    exact fraction reads as noise (finding 2026-07-26)."""
    v = round(float(value) * 2) / 2
    return str(int(v)) if float(v).is_integer() else f"{v:g}"


def _qualifier(ratio: Optional[float]) -> str:
    if ratio is None or ratio < RATIO_MIN:
        return ""
    return "long narrow" if ratio >= RATIO_NARROW else "elongated"


def _length_clause(ratio: Optional[float]) -> str:
    """The VERBAL multiplier — "about 2 times as long as it is wide". Only
    from RATIO_MIN on; below that the measurements alone say enough."""
    if ratio is None or ratio < RATIO_MIN:
        return ""
    mult = round(ratio * 2) / 2
    if mult < 2:
        return "noticeably longer than it is wide"
    txt = str(int(mult)) if float(mult).is_integer() else f"{mult:g}"
    return f"about {txt} times as long as it is wide"


def _article(word: str) -> str:
    return "an" if word[:1].lower() in "aeiou" else "a"


def render_hint(hint: ShapeHint, family: str) -> str:
    """One hint as a prompt clause, in the family's own voice."""
    ratio = _ratio_of(hint)
    plan = " ".join(x for x in (_qualifier(ratio), (hint.shape or "").strip()) if x)
    plan = f"{plan} floor plan".strip()
    have_size = bool(hint.long_m and hint.short_m)
    if family == "natural":
        head = f"{_article(plan)} {plan}"
        if have_size:
            head += (f" roughly {_metres(hint.short_m)} by "
                     f"{_metres(hint.long_m)} metres")
        parts = [head]
        clause = _length_clause(ratio)
        if clause:
            parts.append(clause)
        if hint.fills_frame:
            parts.append(f"the {hint.surface} fills the frame edge to edge")
        return ", ".join(parts)
    # keywords: tags only — the qualifier already carries the proportion,
    # a verbal multiplier would read as prose in a tag list.
    parts = [plan]
    if have_size:
        parts.append(f"{_metres(hint.short_m)} by {_metres(hint.long_m)} "
                     f"meters footprint")
    if hint.fills_frame:
        parts.append("fills the frame edge to edge")
    return ", ".join(parts)


# ── Negation guard ────────────────────────────────────────────────────────

# Deliberately conservative: only the four clause openers that actually show
# up in room/location texts, DE + EN.
_NEG_LEAD = re.compile(
    r"^\s*(?:ohne|kein(?:e|en|er|em|es)?|without|no)\b[\s:]*", re.IGNORECASE)
# The same openers anywhere in a sentence — used for the "warning only" case.
_NEG_ANY = re.compile(
    r"\b(?:ohne|kein(?:e|en|er|em|es)?|without|no)\b", re.IGNORECASE)
# A trailing clause: everything from a comma/dash + negation opener to the
# end of the sentence.
_NEG_TAIL = re.compile(
    r"[,;—–-]\s*(?:ohne|kein(?:e|en|er|em|es)?|without|no)\b[^.!?]*$",
    re.IGNORECASE)
# Sentence tokenizer that keeps the terminator with its sentence.
_SENTENCE = re.compile(r"[^.!?\n]+[.!?]*", re.DOTALL)
_ITEM_SPLIT = re.compile(r",|\bund\b|\band\b|\boder\b|\bor\b", re.IGNORECASE)


def _negated_items(clause: str) -> List[str]:
    """The bare noun phrases of a negation clause — "Keine Tische, keine
    Stühle" -> ["Tische", "Stühle"]. No translation (that waits for the LLM
    stage), so the tags keep the subject's language."""
    txt = _NEG_LEAD.sub("", clause.strip().strip(".!?,;:—–- "))
    out: List[str] = []
    for piece in _ITEM_SPLIT.split(txt):
        piece = _NEG_LEAD.sub("", piece.strip()).strip(" .!?,;:—–-")
        if piece:
            out.append(piece)
    return out


def split_negations(subject: str) -> tuple:
    """(cleaned subject, moved items, mid-sentence negations).

    A negation that IS a sentence, or a trailing clause of one, is removed
    and its nouns handed back for the negative prompt. A negation word in the
    middle of a sentence is only reported — cutting there would maim the
    sentence, and rewriting is the LLM stage's job.
    """
    subject = (subject or "").strip()
    # Nothing to negate -> hand the text back untouched (byte-identical).
    if not subject or not _NEG_ANY.search(subject):
        return subject, [], []
    kept: List[str] = []
    moved: List[str] = []
    inline: List[str] = []
    for raw in _SENTENCE.findall(subject):
        core = raw.strip()
        if not core:
            continue
        if _NEG_LEAD.match(core):
            moved.extend(_negated_items(core))
            continue
        # Peel off trailing negation clauses (there may be several).
        term = core[-1] if core[-1:] in ".!?" else ""
        body = core
        while True:
            tail = _NEG_TAIL.search(body.rstrip(".!?").rstrip())
            if not tail:
                break
            moved.extend(_negated_items(tail.group(0)))
            body = body[:tail.start()].rstrip()
        if not body:
            continue
        if term and not body.endswith(term):
            body += term
        if _NEG_ANY.search(body):
            inline.append(body)
        kept.append(body)
    cleaned = re.sub(r"\s{2,}", " ", " ".join(kept)).strip()
    return cleaned, moved, inline


# ── Tag helpers ───────────────────────────────────────────────────────────

def merge_tags(*parts: str) -> str:
    """Comma tags joined without duplicates (case-insensitive, order kept)."""
    out: List[str] = []
    seen = set()
    for part in parts:
        for tag in (part or "").split(","):
            tag = tag.strip()
            key = tag.lower()
            if tag and key not in seen:
                seen.add(key)
                out.append(tag)
    return ", ".join(out)


# ── Weaving (shared with the LLM stage) ───────────────────────────────────

def weave_subject(style: str, subject: str) -> tuple:
    """(body, warnings) — the subject in its slot, or appended without one.

    ``.replace()``, never ``.format()``: a user style may contain other
    curly braces. The LLM stage reuses this when it has to re-weave a
    frameless answer, so the weaving rule exists exactly once.
    """
    warnings: List[str] = []
    slots = (style or "").count("{subject}")
    if slots:
        # The style sentence continues after the slot — a trailing full stop
        # from the DB text would cut it in half ("… Format., staged on …"),
        # and a leading article keeps its capital mid-sentence ("a wide
        # establishing shot of A cozy corner cafe"). Articles only: a foreign
        # noun ("Küche") must keep its capital.
        woven = (subject or "").strip().rstrip(" .")
        if (style.index("{subject}") > 0
                and woven.split(" ")[0].lower() in ("a", "an", "the")):
            woven = woven[0].lower() + woven[1:]
        body = style.replace("{subject}", woven, 1)
        if slots > 1:
            body = body.replace("{subject}", "")
            warnings.append(
                "The use-case style contains {subject} more than once — "
                "only the first placeholder was filled, the others dropped.")
        return body, warnings
    if style and subject:
        return f"{style}, {subject}", warnings
    return style or subject or "", warnings


def prepend_hints(body: str, hint_block: str) -> str:
    """The hint block in front of the prompt (empty block = unchanged)."""
    if not hint_block:
        return body
    return f"{hint_block}, {body}" if body else hint_block


# ── The composer ──────────────────────────────────────────────────────────

def compose(*, use_case: str, subject: str, backend: Any,
            hints: Optional[List[ShapeHint]] = None,
            negative_extra: str = "",
            style_override: Optional[str] = None) -> Composed:
    """Build the final prompt for one render occasion.

    ``backend`` supplies the family (``image_family``/``model``); ``None`` is
    allowed and resolves to the keywords family. ``style_override`` replaces
    the use case's style (the dialog hands back an edited one).
    """
    from app.core import config as _cfg
    from app.core.prompt_adapters import get_target_model

    backend_family = (getattr(backend, "image_family", "") or "").strip()
    backend_model = (getattr(backend, "model", "") or "").strip()
    ucp = _cfg.resolve_use_case_style(
        use_case, backend_model=backend_model, backend_family=backend_family)
    family = _cfg.image_model_to_family(
        get_target_model(backend_family, backend_model))

    style = (ucp.get("prompt_style", "") if style_override is None
             else style_override) or ""
    subject = (subject or "").strip()
    warnings: List[str] = []

    # 1. Negation guard — subject only, never the style.
    subject, moved, inline = split_negations(subject)
    if moved:
        listed = ", ".join(moved)
        msg = f"Moved negated items to the negative prompt: {listed}."
        if family == "natural":
            msg += (" Flux-class models ignore negatives — describe the "
                    "room positively instead.")
        warnings.append(msg)
    for sentence in inline:
        warnings.append(
            f"Negation inside a sentence, left untouched: \"{sentence}\". "
            f"A diffusion model draws what the negation names — phrase it "
            f"positively.")

    # 2. Subject slot: weave instead of append.
    slots = style.count("{subject}")
    body, weave_warnings = weave_subject(style, subject)
    warnings.extend(weave_warnings)

    # 3. Hints first: early tokens steer diffusion (fix 237f5a1). A hint
    # already present in the text is not repeated.
    rendered: List[str] = []
    for hint in hints or []:
        clause = render_hint(hint, family)
        if clause and clause.lower() not in body.lower():
            rendered.append(clause)
    hint_block = ", ".join(rendered)
    prompt = prepend_hints(body, hint_block)

    negative = merge_tags(ucp.get("prompt_negative", ""),
                          ", ".join(moved), negative_extra)

    return Composed(
        prompt=prompt,
        negative=negative,
        warnings=warnings,
        meta={
            "use_case": use_case,
            "family": family,
            "style_had_slot": bool(slots),
            "hint_rendered": hint_block,
            "negations_moved": moved,
        },
    )
