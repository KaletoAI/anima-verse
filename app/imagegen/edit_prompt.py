"""Edit prompts — the ONE place that knows how an image model addresses its reference images.

Design: ``docs/edit-prompts.md``. Every render with reference images passes ``normalise`` at the central handoff
(``ImageBackend.generate``), whatever wrote its prompt; a producer that wants a prompt tuned per model writes it as an
``EditPrompt`` (a sectioned template, or refs/result/keep/transfers for the generic renderers).

Dialects (a backend config field ``prompt_dialect``; ``auto`` resolves through ``DIALECT_BY_MODEL``, the only place
a model name appears):

- ``picture_edit`` — ``<Picture N>``; the form ``Edit <Picture 1>. <result>. Keep <list> exactly as it is.``; the
  engine node prepends ``Edit <Picture 1>. `` to a prompt that does not start with ``Edit <Picture N>``, so the
  normaliser writes that prefix itself and the logged prompt is what the engine encodes.
- ``picture_subject`` — ``<Picture N>``; one paragraph in subject form: ``X in <Picture 1> is <Subject 1>`` → ``The
  target image shows …`` → one relation per subject (``partially / fully preserved``, ``supplies … transferred to``).
- ``image_tag`` — ``<image1>``, ``<image2>`` with two or more images; ONE image is "the image" (no tag); the
  instruction first, each image's role named, what stays as a positive ``keep … unchanged``.
- ``ordinal`` — "the first image", "the second image"; one image is "the image" (every other backend).

Producers write the canonical token ``<ref N>`` (N = the slot number of ``input_reference_image_N``); the old
spellings ("the first image", "image 2", ``<Picture 2>``, ``<image2>``, ``@image2``) are recognised as well. No engine
ever sees ``<ref N>``. ``<ref N>`` names a SLOT and is rendered as that slot's POSITION among the slotted references
(the backends send them sorted by N), so a gap in the slot numbers never shifts a token onto the wrong picture; every
other spelling already names a position (what the engine sees), which keeps ``normalise`` idempotent.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from app.core.log import get_logger

logger = get_logger("edit_prompt")

DIALECTS = ("picture_edit", "picture_subject", "image_tag", "ordinal")
#: The config field's choices (``config_schema`` backend entry ``prompt_dialect``).
DIALECT_SETTINGS = ("auto",) + DIALECTS
DEFAULT_DIALECT = "ordinal"

#: ``auto``: a lower-case substring of the backend's ``model`` -> its dialect; the first hit wins. The ONLY place in
#: the program where a model name decides the reference wording (``scripts/smoke_edit_prompt_table.py`` guards it).
DIALECT_BY_MODEL: Tuple[Tuple[str, str], ...] = (
    ("p-h3", "picture_edit"),
    ("minimax-h3", "picture_subject"),
    ("qwen2.1", "image_tag"),
    ("qwen-image-2.1", "image_tag"),
)

ORDINALS = ("first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth",
            "eleventh", "twelfth", "thirteenth", "fourteenth", "fifteenth", "sixteenth")

_SLOT_KEY = re.compile(r"^input_reference_image_(\d+)$")

_N = r"(1[0-6]|[1-9])"
_ORD = "|".join(ORDINALS)
#: Every spelling of a reference mention -> one alternative with ONE number / ordinal group. Order matters: the
#: bracket tokens first, "the reference image 2" before the bare "the reference image".
_MENTION_PARTS = (
    ("ref", rf"<ref\s*{_N}>"),
    ("picture", rf"<picture\s*{_N}>"),
    ("tag", rf"<image\s*{_N}>"),
    ("at", rf"@image{_N}\b"),
    ("numbered", rf"(?:\bthe\s+)?\b(?:reference\s+)?(?:image|picture)\s+{_N}\b"),
    ("ordinal", rf"\bthe\s+({_ORD})\s+(?:reference\s+)?(?:image|picture)\b"),
    ("single", r"\bthe\s+reference\s+(?:image|picture)\b"),
)
_MENTIONS = re.compile("|".join(f"(?P<{name}>{pat})" for name, pat in _MENTION_PARTS), re.IGNORECASE)

#: Every reference token a rendered prompt may carry — the prompt limit's LLM must keep each one and its cut never
#: ends inside one (``app/imagegen/prompt_limit.py``).
TOKEN_RE = re.compile(
    rf"<ref\s*\d+>|<Picture\s*\d+>|<image\s*\d+>|<Subject\s*\d+>|@image\d+"
    rf"|\bthe (?:{_ORD}|reference) image\b",
    re.IGNORECASE)

_SENTENCE_SPLIT = re.compile(r"((?<=[.!?])\s+|\n+)")
#: The engine node's own test (ComfyUI ``nodes_minimax_h3.PH3_IMAGE_EDIT_VERBATIM``): a prompt starting like this is
#: encoded as it is; any other gets ``Edit <Picture 1>. `` in front.
_PH3_VERBATIM = re.compile(r"\s*(Edit <Picture \d+>|subject_definitions:)")
_PH3_LOWER_EDIT = re.compile(r"^(\s*)edit(?= <Picture \d+>)", re.IGNORECASE)
_EDIT_THE_IMAGE = re.compile(r"^\s*Edit the image\.\s*", re.IGNORECASE)


# ---------------------------------------------------------------------------------------------------- dialect


def _setting(backend: Any) -> str:
    return str(getattr(backend, "prompt_dialect_setting", "") or "").strip().lower()


def resolve_dialect(backend: Any) -> Tuple[str, str]:
    """``(dialect, source)``: the configured value (source "config") unless it is ``auto`` / empty / unknown, else
    the first ``DIALECT_BY_MODEL`` hit on the backend's model id ("auto"), else ``ordinal`` ("default")."""
    setting = _setting(backend)
    if setting in DIALECTS:
        return setting, "config"
    model = str(getattr(backend, "model", "") or "").lower()
    for needle, dialect in DIALECT_BY_MODEL:
        if needle in model:
            return dialect, "auto"
    return DEFAULT_DIALECT, "default"


def dialect_of(backend: Any) -> str:
    """The backend's reference dialect (``resolve_dialect`` without its source)."""
    return resolve_dialect(backend)[0]


def render_ref(n: int, dialect: str, total: int) -> str:
    """The token of reference ``n`` (1-based position) in ``dialect`` when ``total`` references are slotted."""
    n = int(n)
    if dialect in ("picture_edit", "picture_subject"):
        return f"<Picture {n}>"
    if total <= 1:
        return "the image"
    if dialect == "image_tag":
        return f"<image{n}>"
    return f"the {ORDINALS[n - 1]} image" if 1 <= n <= len(ORDINALS) else f"image {n}"


# ---------------------------------------------------------------------------------------------------- lint

#: ``extra_params`` keys a ``picture_subject`` model fixes itself (6 steps / cfg 1 in its workflow).
_FIXED_SAMPLING_KEYS = ("steps", "num_inference_steps", "cfg", "cfg_scale", "guidance_scale")
#: The native edge of an ``image_tag`` model (it renders at the request width).
IMAGE_TAG_NATIVE_PX = 2048


def lint_backend(backend: Any) -> List[Dict[str, str]]:
    """What the backend entry sets against its dialect's request parameters — ``[{"code", "level", "text"}]``
    (level "warning" / "info"); never blocks a render. Shown in the routing overview, written into a cut-texture job
    record, logged nowhere else."""
    dialect = dialect_of(backend)
    extra = getattr(backend, "extra_params", None) or {}
    if not isinstance(extra, dict):
        extra = {}
    out: List[Dict[str, str]] = []
    if dialect == "picture_edit" and extra.get("use_prompt_upsampler") is not False:
        out.append({"code": "upsampler_on", "level": "warning",
                    "text": "The prompt upsampler is on: it rewrites the prompt and invents content. Set extra "
                            "params {\"use_prompt_upsampler\": false}."})
    if dialect == "image_tag":
        width = 0
        try:
            width = int(getattr(backend, "width", 0) or 0)
        except (TypeError, ValueError):
            width = 0
        if width and width < IMAGE_TAG_NATIVE_PX:
            out.append({"code": "below_native", "level": "info",
                        "text": f"Renders at {width} px; the model's native size is {IMAGE_TAG_NATIVE_PX} "
                                "(about 4x the time — worth it for texture jobs, not for chat photos)."})
        cfg = extra.get("cfg")
        if cfg is not None and cfg != 1 and cfg != 1.0:
            out.append({"code": "cfg_not_1", "level": "info",
                        "text": f"cfg {cfg}: without a negative prompt the model wants cfg 1."})
    if dialect == "picture_subject":
        keys = [k for k in _FIXED_SAMPLING_KEYS if k in extra]
        if keys:
            out.append({"code": "fixed_sampling", "level": "warning",
                        "text": f"{', '.join(keys)} in extra params: the model's steps and cfg are fixed."})
    return out


# ---------------------------------------------------------------------------------------------------- normaliser


def slots_of(params: Optional[Dict[str, Any]]) -> List[int]:
    """The sorted slot numbers N of ``params["reference_images"]`` keys ``input_reference_image_N`` that carry an
    image (``input_mask`` and empty values are not references)."""
    out = []
    for key, value in ((params or {}).get("reference_images") or {}).items():
        m = _SLOT_KEY.match(str(key))
        if m and value:
            out.append(int(m.group(1)))
    return sorted(set(out))


def ordered_references(params: Optional[Dict[str, Any]]) -> List[Tuple[str, Any]]:
    """``params["reference_images"]`` as ``(key, value)`` pairs in the order a backend sends them: the
    ``input_reference_image_N`` slots by N, then every other key (``input_mask``) in its own order — so ``<ref N>``
    rendered as position N is the N-th image the engine sees."""
    items = list(((params or {}).get("reference_images") or {}).items())

    def key(kv: Tuple[str, Any]) -> Tuple[int, int]:
        m = _SLOT_KEY.match(str(kv[0]))
        return (0, int(m.group(1))) if m else (1, 0)
    return sorted(items, key=key)


def _mention_position(m: "re.Match[str]", slots: Sequence[int]) -> Optional[int]:
    """The 1-based POSITION a mention names among the sent ``slots`` — ``<ref N>`` by its slot (0 when slot N is not
    sent), every other spelling as written (it may exceed ``len(slots)``); None for "the reference image" with more
    than one slot (not guessed)."""
    kind = m.lastgroup
    if kind == "single":
        return 1 if len(slots) == 1 else None
    if kind == "ordinal":
        word = re.search(rf"\b(?:{_ORD})\b", m.group(0), re.IGNORECASE).group(0)
        return ORDINALS.index(word.lower()) + 1
    num = int(re.search(r"\d+", m.group(0)).group(0))
    if kind == "ref":
        return slots.index(num) + 1 if num in slots else 0
    return num


def _at_sentence_start(text: str, pos: int) -> bool:
    before = text[:pos].rstrip()
    return not before or before[-1] in ".!?:\n"


def _cased(replacement: str, sentence_start: bool) -> str:
    if replacement[:1].isalpha() and sentence_start:
        return replacement[0].upper() + replacement[1:]
    return replacement


def _split_sentences(text: str) -> List[str]:
    """Sentences and their separators, alternating (``"".join`` gives ``text`` back)."""
    return _SENTENCE_SPLIT.split(text)


def normalise(prompt: str, params: Optional[Dict[str, Any]], backend: Any) -> Tuple[str, Dict[str, Any]]:
    """The pass-through every render with reference images takes (``ImageBackend.generate``): ``(prompt, meta)``.

    1. No slotted reference -> the prompt comes back byte-identical (meta ``{"refs": []}``).
    2. Every recognised mention (``_MENTIONS``) is rendered in the backend's dialect (``render_ref`` of its position).
    3. Never invents: a mention of a slot that is not sent drops its SENTENCE while another sentence remains
       (``dropped``); a lone sentence keeps it, in ordinal wording (``unresolved`` note). Nothing else is added except
       the ``picture_edit`` prefix ``Edit <Picture 1>. `` (what the engine node would prepend).
    4. Notes only: ``unused`` slots (sent, never named), ``free_text`` (picture_subject without subject form),
       ``role_missing`` (image_tag, two or more images, no canvas named), ``keep_missing`` (picture_edit).
    Idempotent: ``normalise`` of its own output changes nothing."""
    slots = slots_of(params)
    dialect, source = resolve_dialect(backend)
    meta: Dict[str, Any] = {"dialect": dialect, "dialect_source": source, "refs": list(slots)}
    if not slots or not prompt:
        return prompt, meta
    total = len(slots)

    def valid(pos: Optional[int]) -> bool:
        return pos is not None and 1 <= pos <= total

    # 1. sentences holding a mention of a slot that is not sent are dropped (while another sentence remains)
    parts = _split_sentences(prompt)
    sentences = [i for i in range(0, len(parts), 2) if parts[i].strip()]
    dropped: List[str] = []
    keep_idx = set(range(len(parts)))
    for i in sentences:
        bad = [m.group(0) for m in _MENTIONS.finditer(parts[i])
               if _mention_position(m, slots) is not None and not valid(_mention_position(m, slots))]
        if bad and len([j for j in sentences if j in keep_idx]) > 1:
            dropped.append(parts[i].strip())
            keep_idx.discard(i)
            # the separator after it (or, for the last sentence, the one before it) goes with it
            if i + 1 < len(parts):
                keep_idx.discard(i + 1)
            elif i - 1 >= 0:
                keep_idx.discard(i - 1)
    text = "".join(parts[i] for i in range(len(parts)) if i in keep_idx) if dropped else prompt

    # 2. render every mention
    rewrites = 0
    unresolved: List[str] = []
    named: set = set()
    out: List[str] = []
    last = 0
    for m in _MENTIONS.finditer(text):
        pos = _mention_position(m, slots)
        if pos is None:
            continue
        original = m.group(0)
        if valid(pos):
            named.add(slots[pos - 1])
            token = render_ref(pos, dialect, total)
        elif m.lastgroup == "ref":
            unresolved.append(original)
            n = int(re.search(r"\d+", original).group(0))
            token = render_ref(n, "ordinal", max(2, n))
        else:
            unresolved.append(original)
            continue
        token = _cased(token, _at_sentence_start(text, m.start()))
        out.append(text[last:m.start()])
        out.append(token)
        last = m.end()
        if token != original:
            rewrites += 1
    out.append(text[last:])
    text = "".join(out)

    notes: List[str] = []
    prefixed = False
    if dialect == "picture_edit":
        if not _PH3_VERBATIM.match(text) and _PH3_LOWER_EDIT.match(text):
            text = _PH3_LOWER_EDIT.sub(r"\1Edit", text, count=1)      # "edit <Picture 1> …": the node's own form
        if not _PH3_VERBATIM.match(text):
            text = "Edit <Picture 1>. " + _EDIT_THE_IMAGE.sub("", text, count=1).lstrip()
            prefixed = True
        if not re.search(r"\bkeep\b", text, re.IGNORECASE):
            notes.append("keep_missing")
    elif dialect == "picture_subject":
        if "<Subject" not in text:
            notes.append("free_text")
    elif dialect == "image_tag":
        if total >= 2 and not re.search(r"\bcanvas\b", text, re.IGNORECASE):
            notes.append("role_missing")
    unused = [n for n in slots if n not in named]
    if unused:
        notes.append("unused")
    if unresolved:
        notes.append("unresolved")
    meta.update({"rewrites": rewrites, "prefixed": prefixed, "dropped": dropped, "unused": unused,
                 "unresolved": unresolved, "notes": notes,
                 "roles": dict((params or {}).get("reference_roles") or {})})
    if rewrites or dropped or prefixed:
        logger.info("%s: edit prompt in dialect %s (%s) — %d mention(s) rewritten%s%s%s",
                    getattr(backend, "name", "?"), dialect, source, rewrites,
                    ", prefix added" if prefixed else "",
                    f", {len(dropped)} sentence(s) dropped (slot not sent)" if dropped else "",
                    f", notes {', '.join(notes)}" if notes else "")
    return text, meta


# ---------------------------------------------------------------------------------------------------- structured


@dataclass(frozen=True)
class Ref:
    """One slotted reference: ``slot`` = the N of ``input_reference_image_N``; ``role`` canvas / identity / room /
    item / material / composition / view_source; ``label`` what it shows ("the flat sewing pattern of a T-shirt")."""
    slot: int
    role: str
    label: str = ""


@dataclass(frozen=True)
class Transfer:
    """``source`` supplies ``prop`` ("the exact colour and fine weave") to ``target`` (slots)."""
    source: int
    prop: str
    target: int


_REF_TOKEN = re.compile(r"<ref\s*(\d+)>", re.IGNORECASE)


def _sentence(text: str) -> str:
    text = " ".join(str(text or "").split())
    if not text:
        return ""
    text = text[0].upper() + text[1:] if text[0].isalpha() else text
    return text if text[-1] in ".!?" else text + "."


def _join_list(items: Sequence[str]) -> str:
    items = [str(i).strip() for i in items if str(i).strip()]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


@dataclass
class EditPrompt:
    """A structured edit prompt. ``sections`` (from ``from_template``) holds a finished text per dialect and wins;
    without it the generic renderer of the dialect builds the text from ``refs`` / ``result`` / ``keep`` /
    ``transfers`` / ``details`` (each may hold ``<ref N>``)."""
    refs: List[Ref]
    result: str = ""
    keep: List[str] = field(default_factory=list)
    transfers: List[Transfer] = field(default_factory=list)
    details: List[str] = field(default_factory=list)
    sections: Optional[Dict[str, str]] = None

    # ---- tokens
    def _position(self, slot: int) -> int:
        order = sorted({r.slot for r in self.refs})
        return order.index(slot) + 1 if slot in order else slot

    def token(self, slot: int, dialect: str) -> str:
        return render_ref(self._position(slot), dialect, len({r.slot for r in self.refs}))

    def _tokens(self, text: str, dialect: str) -> str:
        def sub(m: "re.Match[str]") -> str:
            tok = self.token(int(m.group(1)), dialect)
            return _cased(tok, _at_sentence_start(m.string, m.start()))
        return _REF_TOKEN.sub(sub, str(text or ""))

    def _canvas(self) -> Optional[Ref]:
        return next((r for r in self.refs if r.role == "canvas"), self.refs[0] if self.refs else None)

    # ---- renderers
    def render(self, dialect: str) -> str:
        if dialect not in DIALECTS:
            raise ValueError(f"unknown dialect {dialect!r}")
        if self.sections:
            if dialect in self.sections:
                return self.sections[dialect]
            if "ordinal" in self.sections:
                return self.sections["ordinal"]
        return {"picture_edit": self._render_picture_edit, "picture_subject": self._render_picture_subject,
                "image_tag": self._render_image_tag, "ordinal": self._render_ordinal}[dialect]()

    def _keep_sentence(self, dialect: str, tail: str) -> str:
        if not self.keep:
            return ""
        return _sentence(self._tokens(f"Keep {_join_list(self.keep)} {tail}", dialect))

    def _render_ordinal(self) -> str:
        d = "ordinal"
        parts = [_sentence(self._tokens(self.result, d))]
        parts += [_sentence(self._tokens(t, d)) for t in self.details]
        parts.append(self._keep_sentence(d, "unchanged"))
        return " ".join(p for p in parts if p)

    def _render_picture_edit(self) -> str:
        d = "picture_edit"
        canvas = self._canvas()
        parts = [f"Edit {self.token(canvas.slot, d) if canvas else '<Picture 1>'}.",
                 _sentence(self._tokens(self.result, d))]
        parts += [_sentence(self._tokens(t, d)) for t in self.details]
        parts.append(self._keep_sentence(d, "exactly as it is" if len(self.keep) <= 1 else "exactly as they are"))
        return " ".join(p for p in parts if p)

    def _render_image_tag(self) -> str:
        d = "image_tag"
        parts = [_sentence(self._tokens(self.result, d))]
        role_words = {"canvas": "the canvas", "material": "the material source", "identity": "the person",
                      "room": "the place", "item": "the object", "composition": "the composition",
                      "view_source": "the view to change"}
        if len(self.refs) >= 2:
            for r in self.refs:
                role = role_words.get(r.role, r.role)
                label = f": {self._tokens(r.label, d)}" if r.label else ""
                parts.append(_sentence(f"{self.token(r.slot, d)} is {role}{label}"))
        for t in self.transfers:
            parts.append(_sentence(f"Take {self._tokens(t.prop, d)} from {self.token(t.source, d)} "
                                   f"onto {self.token(t.target, d)}"))
        parts += [_sentence(self._tokens(t, d)) for t in self.details]
        parts.append(self._keep_sentence(d, "unchanged"))
        return " ".join(p for p in parts if p)

    def _render_picture_subject(self) -> str:
        d = "picture_subject"
        subject = {r.slot: i + 1 for i, r in enumerate(self.refs)}

        def subj(slot: int) -> str:
            return f"<Subject {subject[slot]}>"
        parts = []
        for r in self.refs:
            label = self._tokens(r.label, d) if r.label else "the image"
            parts.append(_sentence(f"{label} in {self.token(r.slot, d)} is {subj(r.slot)}"))
        parts.append(_sentence(f"The target image shows {self._tokens(self.result, d)}"))
        canvas = self._canvas()
        if canvas is not None:
            if self.keep:
                parts.append(_sentence(f"{subj(canvas.slot)} is partially preserved; "
                                       f"{self._tokens(_join_list(self.keep), d)} remain exactly"))
            else:
                parts.append(_sentence(f"{subj(canvas.slot)} is partially preserved"))
        sources = set()
        for t in self.transfers:
            sources.add(t.source)
            parts.append(_sentence(f"{subj(t.source)} supplies {self._tokens(t.prop, d)} transferred to "
                                   f"{subj(t.target)}"))
        for r in self.refs:
            if canvas is not None and r.slot == canvas.slot:
                continue
            if r.slot not in sources:
                parts.append(_sentence(f"{subj(r.slot)} serves only as a reference"))
        parts += [_sentence(self._tokens(t, d)) for t in self.details]
        return " ".join(p for p in parts if p)


# ---------------------------------------------------------------------------------------------------- templates

_SECTION = re.compile(r"^##[ \t]+([a-z_]+)[ \t]*$", re.MULTILINE)


def template_sections(source: str) -> Dict[str, str]:
    """A sectioned template's raw Jinja per ``## <dialect>`` header (text before the first header — the file's
    ``{# … #}`` comment — is not part of any section). Unknown section names raise ``ValueError``."""
    marks = list(_SECTION.finditer(source))
    out: Dict[str, str] = {}
    for i, m in enumerate(marks):
        name = m.group(1)
        if name not in DIALECTS:
            raise ValueError(f"unknown section ## {name}")
        end = marks[i + 1].start() if i + 1 < len(marks) else len(source)
        out[name] = source[m.end():end]
    return out


def _env():
    from jinja2 import StrictUndefined
    from jinja2.sandbox import SandboxedEnvironment
    return SandboxedEnvironment(autoescape=False, undefined=StrictUndefined, trim_blocks=True, lstrip_blocks=True,
                                keep_trailing_newline=False)


def from_source(source: str, refs: Iterable[Ref], **variables: Any) -> EditPrompt:
    """``EditPrompt`` of a sectioned template text: every dialect rendered (its own section, else ``## ordinal``)
    with the global ``ref(n)`` = that dialect's token of slot n, whitespace collapsed to one paragraph. A missing
    variable raises (``StrictUndefined``)."""
    refs = list(refs)
    raw = template_sections(source)
    if "ordinal" not in raw:
        raise ValueError("a sectioned edit-prompt template needs an ## ordinal section")
    ep = EditPrompt(refs=refs)
    env = _env()
    rendered: Dict[str, str] = {}
    for dialect in DIALECTS:
        src = raw.get(dialect, raw["ordinal"])
        text = env.from_string(src).render(ref=lambda n, _d=dialect: ep.token(int(n), _d), **variables)
        rendered[dialect] = " ".join(text.split())
    ep.sections = rendered
    return ep


def from_template(path: Path, refs: Iterable[Ref], **variables: Any) -> EditPrompt:
    """``from_source`` of a shipped sectioned template file."""
    return from_source(Path(path).read_text(encoding="utf-8"), refs, **variables)
