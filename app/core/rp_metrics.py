"""Deterministic roleplay metrics — what code can measure without a judge.

Pure functions over reply texts (no I/O, no LLM). Used by ``rp_test`` and
checked by ``scripts/smoke_rp_metrics.py`` with hand-derived numbers.

Repetition uses the game's OWN repetition definition (``history_manager``:
``repetition_keys`` = opening signature + every sentence of >= 30 normalized
characters, ``repetition_shingles`` = word 4-grams, share 0.3), so the test and
the reactive anti-loop mean the same thing by "repeats itself".

Semantic judgements (prose, character, logic) are NOT made here: a word list
cannot tell good prose from bad, so those belong to the judge model.
"""
import difflib
import re
from statistics import median
from typing import Any, Dict, Iterable, List, Optional, Sequence

from app.utils.history_manager import (REPETITION_SHINGLE_SHARE, fuzzy_signature,
                                       repetition_keys, repetition_shingles)

_WORD = re.compile(r"[^\W\d_]+(?:['’-][^\W\d_]+)*")
_ACTION = re.compile(r"\*[^*\n]+\*")
_QUOTE = re.compile(r"[„“\"«»][^„“”\"«»\n]+[“”\"«»]")
_MOOD = re.compile(r"\*\*\s*(?:I\s+feel|Ich\s+f[üu]hle)\s+([^*]+?)\s*\*\*", re.I)
_IMAGE_MD = re.compile(r"!\[[^\]]*\]\(")
_THINK = re.compile(r"</?think>|^\s*(?:okay|ok|alright|so),?\s+(?:the user|let me|i need to|we need to)"
                    r"|^\s*(?:let me think|we need to|the user (?:wants|asks|says))", re.I)
_TOOL = re.compile(r"<tool\b|<tool_call>|</?tool_(?:call|result)>|\[(?:TOOL|ACTION|CALL)\s*:", re.I)
# Characters outside the scripts a German/English reply uses: a burst of them is
# the multi-script token salad measured at temperature 1.10 (2026-08-03).
_FOREIGN_SCRIPT = re.compile(r"[Ѐ-ӿ֐-ۿऀ-෿฀-໿"
                             r"぀-ヿ㐀-鿿가-힯]")
# Assistant voice only. A character may well say "I can't help you" — that is
# roleplay, not a refusal; only the AI identity or refusing THE ROLEPLAY counts.
_ASSISTANT = re.compile(r"\b(?:as an ai|as a language model|i(?:'m| am) an ai\b|als (?:eine )?ki\b|"
                        r"als sprachmodell|"
                        r"(?:continue|engage in|participate in) (?:this|the) (?:role-?play|scenario)|"
                        r"(?:dieses|das|diesem) rollenspiel (?:nicht )?(?:fortsetzen|weiterführen|weiterspielen))", re.I)
_FIRST_PERSON = re.compile(r"\b(?:ich|mich|mir|mein\w*|i|me|my)\b", re.I)
_QUOTED = re.compile(r"[„\"“«»](.+?)[“\"”«»]", re.S)
_CAT_SOUNDS = re.compile(r"^(?:m+i*a+u+|mi+a+u+|m+r+[pr]*|mrr+[a-z]*|purr+|schnurr+[a-z]*|fauch+[a-z]*|"
                         r"hiss+|chirp+|meow+|mau+|grr+|prr+|rrr+|mrau+|mi+e+p+)$", re.I)

_SIGNALS = {
    "de": set("der die das den dem des ein eine einer einen einem eines ich du er sie es wir ihr ist sind war "
              "waren und oder aber auch auf im am an zu zum zur mit von vom für bei aus nach vor über unter "
              "durch ohne um als wie nicht nur noch schon so sich mich dich mir dir mein dein".split()),
    "en": set("the a an this that these those i you he she it we they is are was were be been and or but also "
              "on at to with from for by of if then than not only still so myself your our their its his her "
              "into over under through without about".split()),
}
LANG_MIN_WORDS = 12

# Discipline weights: the score is 100 minus weight x failure RATE per kind.
DISCIPLINE_WEIGHTS = {"tool_syntax": 100, "thinking_leak": 100, "empty": 100, "language": 100,
                      "name_prefix": 60, "image_markdown": 60, "truncated": 60, "mood_marker": 40,
                      "player_agency": 100}
LENGTH_RATIO_LIMIT = 0.6
LENGTH_PENALTY = 15


def words(text: str) -> List[str]:
    return _WORD.findall(text or "")


def strip_actions(text: str) -> str:
    return _ACTION.sub(" ", text or "")


def language_ok(text: str, lang: Optional[str]) -> Optional[bool]:
    """None = not judged (no expected language, or under 12 words). False only
    when another language clearly leads: twice the function-word hits and at
    least three of them."""
    if not lang or lang not in _SIGNALS:
        return None
    tokens = [w.lower() for w in words(text)]
    if len(tokens) < LANG_MIN_WORDS:
        return None
    hits = {key: sum(t in vocab for t in tokens) for key, vocab in _SIGNALS.items()}
    hits["de"] += bool(re.search("[äöüß]", (text or "").lower()))
    own = hits[lang]
    other = max(v for key, v in hits.items() if key != lang)
    return not (other >= 3 and other >= 2 * own)


def script_salad(text: str) -> bool:
    """Five or more characters from scripts a de/en reply never uses."""
    return len(_FOREIGN_SCRIPT.findall(text or "")) >= 5


def mood_marker_ok(raw: str) -> bool:
    """Exactly one ``**I feel <word>**`` (or ``**Ich fühle <word>**``) with ONE word."""
    found = _MOOD.findall(raw or "")
    return len(found) == 1 and len(words(found[0])) == 1


def name_prefix(text: str, character: str) -> bool:
    """The reply opens with a speaker label: "Velumi:" / "**Velumi Kieselglanz:**"."""
    first = (character or "").split()[0] if character else ""
    if not first:
        return False
    head = (text or "").lstrip().lstrip("*").lstrip()
    return bool(re.match(rf"(?:{re.escape(character)}|{re.escape(first)})\s*\**\s*:", head, re.I))


def cat_speech(text: str) -> bool:
    """A creature that cannot talk used human words (outside *actions*): a
    quoted line, or unquoted text in the first person ("Miau. Ich will
    Fisch!"), with more than one word that is not a cat sound. Unquoted
    third-person narration ("Pfote streicht um deine Beine und maunzt.") is
    no speech — the judge's case question covers the unclear rest."""
    def talks(part: str) -> bool:
        return len([w for w in words(part) if not _CAT_SOUNDS.match(w)]) > 1
    rest = strip_actions(text)
    if any(talks(spoken) for spoken in _QUOTED.findall(rest)):
        return True
    unquoted = _QUOTED.sub(" ", rest)
    return bool(_FIRST_PERSON.search(unquoted)) and talks(unquoted)


def refusal(text: str) -> bool:
    from app.core.llm_refusal import detect_refusal
    return bool(detect_refusal(text or "")) or bool(_ASSISTANT.search(text or ""))


def tool_syntax(raw: str, skill_names: Iterable[str] = ()) -> bool:
    """Protocol text in the prose: a tool tag, or a known skill name used like a
    call (``SetActivity pose:…``, ``TalkTo(``, ``TalkTo {``)."""
    if _TOOL.search(raw or ""):
        return True
    names = [re.escape(n) for n in skill_names if n]
    return bool(names) and bool(re.search(rf"\b(?:{'|'.join(names)})\b\s*(?:[:({{]|\w+\s*:)", raw or ""))


def reply_flags(raw: str, clean: str, *, case: Dict[str, Any], finish_reason: Optional[str] = None,
                skill_names: Iterable[str] = ()) -> Dict[str, Any]:
    """Every code check for ONE answer. True = the failure happened; None = not
    applicable to this answer."""
    lang = language_ok(clean, case.get("lang"))
    return {
        "empty": not clean.strip(),
        "truncated": finish_reason == "length",
        "tool_syntax": tool_syntax(raw, skill_names),
        "thinking_leak": bool(_THINK.search(raw or "")),
        "name_prefix": name_prefix(clean, case.get("character", "")),
        "image_markdown": bool(_IMAGE_MD.search(raw or "")),
        "mood_marker": (not mood_marker_ok(raw)) if case.get("mood_marker") else None,
        "language": None if lang is None else not lang,
        "salad": script_salad(raw),
        "refusal": refusal(clean),
        "cat_speech": cat_speech(clean) if case.get("cat_voice") else None,
        "ends_question": clean.rstrip().rstrip("*").rstrip().endswith("?"),
        # The whole reply, actions included — length is what the moment asks for.
        "words": len(words(clean)),
    }


def structure(text: str) -> tuple:
    """Shape of a reply: the order of *action* / "speech" / plain text parts
    (runs collapsed) and whether it ends with a question."""
    parts = []
    pos = 0
    tokens = sorted([(m.start(), m.end(), "A") for m in _ACTION.finditer(text or "")]
                    + [(m.start(), m.end(), "S") for m in _QUOTE.finditer(text or "")])
    for start, end, kind in tokens:
        if start < pos:
            continue
        if (text[pos:start]).strip():
            parts.append("T")
        parts.append(kind)
        pos = end
    if (text or "")[pos:].strip():
        parts.append("T")
    collapsed = [p for i, p in enumerate(parts) if i == 0 or parts[i - 1] != p]
    return tuple(collapsed), (text or "").rstrip().rstrip("*").rstrip().endswith("?")


def _norm(text: str) -> str:
    return fuzzy_signature(text or "", length=10 ** 6)


def _sentence_keys(text: str) -> set:
    return repetition_keys(text) - {fuzzy_signature(text)}


def echo(reply: str, player_line: str) -> bool:
    """Half or more of the player's word 4-grams reappear in the reply. A player
    line under four words cannot be echoed (0)."""
    line = repetition_shingles(player_line or "")
    if not line:
        return False
    return len(line & repetition_shingles(reply or "")) / len(line) >= 0.5


def repetition_series(replies: Sequence[str], prior: Sequence[str] = (),
                      player_lines: Sequence[str] = ()) -> List[Dict[str, Any]]:
    """Per reply, how it relates to the character's EARLIER replies (``prior``
    = replies already in the history, then the series itself, in order).

    - repeat: shares a repetition key, or >= 30 % of its 4-grams were seen
      (the game's count_assistant_repetitions rule);
    - sentence_reuse: share of its sentences (>= 30 normalized chars) seen before;
    - full_copy: >= 90 % similar (difflib, normalized) to one earlier reply;
    - same_shape: same multi-part structure as the reply right before it
      (single-part replies never count — "plain text" is no pattern);
    - echo: see ``echo``.
    """
    seen_keys: set = set()
    seen_shingles: set = set()
    seen_sentences: set = set()
    earlier: List[str] = []
    for text in prior:
        seen_keys |= repetition_keys(text)
        seen_shingles |= repetition_shingles(text)
        seen_sentences |= _sentence_keys(text)
        earlier.append(text)
    out = []
    for index, text in enumerate(replies):
        keys = repetition_keys(text)
        shingles = repetition_shingles(text)
        sentences = _sentence_keys(text)
        share = len(shingles & seen_shingles) / len(shingles) if shingles else 0.0
        norm = _norm(text)
        full = bool(norm) and any(difflib.SequenceMatcher(None, norm, _norm(e)).ratio() >= 0.9 for e in earlier)
        shape = structure(text)
        before = structure(earlier[-1]) if earlier else None
        out.append({
            "repeat": bool(keys & seen_keys) or share >= REPETITION_SHINGLE_SHARE,
            "shingle_share": round(share, 3),
            "sentence_reuse": round(len(sentences & seen_sentences) / len(sentences), 3) if sentences else 0.0,
            "full_copy": full,
            "same_shape": bool(before) and len(shape[0]) >= 2 and shape == before,
            "echo": echo(text, player_lines[index] if index < len(player_lines) else ""),
            "reused_shingles": sorted(" ".join(s) for s in shingles & seen_shingles),
        })
        seen_keys |= keys
        seen_shingles |= shingles
        seen_sentences |= sentences
        earlier.append(text)
    return out


def rate(values: Iterable[Optional[bool]]) -> Optional[float]:
    """Share of True among the applicable (non-None) values; None if none apply."""
    applicable = [bool(v) for v in values if v is not None]
    return sum(applicable) / len(applicable) if applicable else None


def repetition_score(series: Sequence[Dict[str, Any]]) -> Optional[float]:
    """100 − 60·repeat rate − 25·full-copy rate − 15·same-shape rate."""
    if not series:
        return None
    rep = rate(s["repeat"] for s in series)
    full = rate(s["full_copy"] for s in series)
    shape = rate(s["same_shape"] for s in series)
    return round(max(0.0, 100 - 60 * rep - 25 * full - 15 * shape), 1)


def discipline_score(rates: Dict[str, Optional[float]], length_ratio: Optional[float] = None) -> float:
    """100 − Σ weight·failure rate (kinds with no applicable answer count 0),
    − 15 when short moments are not answered shorter than long ones."""
    penalty = sum(DISCIPLINE_WEIGHTS[k] * (rates.get(k) or 0.0) for k in DISCIPLINE_WEIGHTS)
    if length_ratio is not None and length_ratio > LENGTH_RATIO_LIMIT:
        penalty += LENGTH_PENALTY
    return round(max(0.0, 100 - penalty), 1)


def length_ratio(brief_words: Sequence[int], long_words: Sequence[int]) -> Optional[float]:
    """Median words of the brief moments over median words of the long ones."""
    if not brief_words or not long_words or median(long_words) <= 0:
        return None
    return round(median(brief_words) / median(long_words), 3)


def cliche_hits(text: str, cliches: Iterable[str]) -> List[str]:
    low = (text or "").lower()
    return [c for c in cliches if c and c.lower() in low]
