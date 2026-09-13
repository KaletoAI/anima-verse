"""Shared animation clips — layout and discovery (core, route-free).

Clips live in ``shared/models/clips`` (see the README there for the hard file
requirements: Mixamo FBX "Without Skin", one rig source, 52-bone rig). The
layout is ``[<set>/]<kind>[_<n>].<ext>``:

* the KIND is the semantic category an activity maps to (walk, sit, …) and
  is the WHOLE file name without its extension — only a trailing ``_<number>``
  is cut off, because that is the numbering of several clips of one kind;
* the SET is the figure the clip was authored for (female, male, animal,
  lady, …) and comes from the DIRECTORY: one level of subdirectories below
  the clips root, one directory per set. Clips lying in the root itself are
  the neutral ones (set "").

A PAIR clip — two files recorded together, one per partner — carries the
ROLE as a ``__a`` / ``__b`` suffix of the stem: ``handshake__a.fbx`` and
``handshake__b.fbx`` are the two halves of the kind ``handshake``. The double
underscore is the role separator and nothing else (a single ``_`` stays part
of the kind). A pair kind has no solo file; it is played by two figures at a
shared anchor, in lockstep. Next to the files a JSON SIDECAR (written by
``scripts/clip_import_cmu.py``) holds duration, frame rate and the anchor
geometry: for a file ``<stem>.fbx`` it is ``<stem>.json`` when that exists —
so a numbered variant may carry its own numbers — and the shared
``<kind>.json`` otherwise; ``clip_meta()`` reads it.

Both vocabularies are OPEN — a new kind is just a new file, a new set just a
new directory, nothing is hardcoded. Which set a character uses (and the
fallback chain when its set lacks a kind) is ``app/core/animation_sets.py``.

TWO libraries, same layout (``app.core.paths``): ``shared/models/clips`` is
the FREE one — redistributable clips (CMU-derived), tracked in git — and
``shared/models/clips-licensed`` the LICENSED one — Mixamo downloads and
bought packs, usable in the game but not redistributable, gitignored, per
installation. Every entry carries ``source`` (``free``/``licensed``) and the
same ``[<set>/]<file>`` in both libraries resolves to the LICENSED file: whoever
installs a premium pack wants it played. A licensed clip's ``url`` carries a
``licensed/`` prefix, which is how the route tells the two apart.

This module is the ONE place that scans the clip directories; the assets
route, the animation sets and the pose presets all read from here.

It also owns the LOCOMOTION mapping (``shared/config/locomotion_clips.json``):
which clip kind every figure — NPC and avatar alike — plays for the three
locomotion roles ``walk`` / ``run`` / ``idle``. The server never names a
locomotion clip per character (only the activity pose comes from the catalog),
so the roles are the client's default vocabulary, and this file is where an
admin swaps that vocabulary for other kinds of the library. Shared across
every world like the clips themselves (the model-capabilities rule of
CLAUDE.md), tracked in git; a ground's own ``move_anim`` / ``idle_anim``
(``shared/terrain/types.json``) keeps its precedence over these roles.
"""
import json
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

from app.core.log import get_logger
from app.core.paths import (get_animation_clips_dir, get_animation_clips_dirs,
                            get_config_dir, get_licensed_clips_dir)

logger = get_logger(__name__)

CLIP_EXTS = (".fbx", ".glb", ".gltf")
PAIR_ROLES = ("a", "b")
ROLE_SEPARATOR = "__"
LIBRARIES = ("free", "licensed")
#: The locomotion roles a figure plays without the server naming a clip. The
#: DEFAULT kind of a role is the role's own name — an empty or missing entry
#: in the mapping file means exactly that.
LOCOMOTION_ROLES = ("walk", "run", "idle")

# A kind is a file stem: lowercase, spaces allowed (they exist in the shipped
# library), but never the pair-role separator and never a path separator.
KIND_RE = re.compile(r"^[a-z0-9][a-z0-9 _-]*$")
# A set is a DIRECTORY name — same alphabet without spaces; "" is the root.
SET_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
# ``<kind>__<role>[_<n>]`` — the parts a rename has to keep apart.
_STEM_RE = re.compile(r"^(?P<kind>.*?)(?:__(?P<role>[ab]))?(?P<num>_\d+)?$")
# The variant numbering — cut from a file stem, refused inside a kind.
_NUM_SUFFIX_RE = re.compile(r"_\d+$")


class ClipLibraryError(Exception):
    """Bad input for a library operation (route: 400)."""


class ClipNotFound(ClipLibraryError):
    """The addressed clip does not exist (route: 404)."""


class ClipExists(ClipLibraryError):
    """The target name is already taken (route: 409)."""


def parse_clip_name(filename: str) -> str:
    """The clip KIND from a file name — the whole stem, lowercased, minus a
    trailing ``_<number>``.

    ONLY that numbering suffix is decoration; hyphens and inner underscores
    belong to the kind. Splitting at them was the bug of 2026-08-13: it filed
    ``swim-idle.fbx`` under "swim" (two clips of one kind, the wrong one played
    while moving) and ``treading-water.fbx`` under "treading", so the kind an
    author writes into ``idle_anim`` existed nowhere. The set is NOT read from
    the name (it is the directory).

        walk.fbx             -> "walk"
        walk_02.fbx          -> "walk"
        swim-idle.fbx        -> "swim-idle"
        treading-water.fbx   -> "treading-water"
        spell_casting.fbx    -> "spell_casting"
        Sit_A.fbx            -> "sit_a"
    """
    return parse_clip_role(filename)[0]


def parse_clip_role(filename: str) -> Tuple[str, str]:
    """``(kind, role)`` from a file name — role ``"a"``/``"b"`` for the half of
    a pair clip (``kiss__b.fbx`` → ``("kiss", "b")``), ``""`` for a solo clip.
    The numbering suffix is cut BEFORE the role is read, so ``hug__a_02.fbx``
    is a second take of the A half."""
    stem = Path(filename).stem.strip().lower()
    stem = _NUM_SUFFIX_RE.sub("", stem) or stem
    head, sep, tail = stem.rpartition(ROLE_SEPARATOR)
    if sep and head and tail in PAIR_ROLES:
        return head, tail
    return stem, ""


def clip_entries() -> List[Dict[str, Any]]:
    """Every clip of both libraries as ``{kind, role, set, source, rel, path}``.

    Per library: the root (set "") plus exactly ONE level of subdirectories
    (the directory name, lowercased, is the set). Hidden files and
    directories (``.`` prefix) are skipped, as is anything without a clip
    extension. ``rel`` is ``[<set>/]<file>``; the same ``rel`` in both
    libraries yields ONE entry, the licensed one.
    """
    def _files_of(directory: Path, cset: str, source: str) -> List[Dict[str, Any]]:
        out = []
        for p in sorted(directory.iterdir()):
            if p.name.startswith(".") or not p.is_file():
                continue
            if p.suffix.lower() not in CLIP_EXTS:
                continue
            kind, role = parse_clip_role(p.name)
            rel = f"{cset}/{p.name}" if cset else p.name
            out.append({"kind": kind, "role": role, "set": cset,
                        "source": source, "rel": rel, "path": p})
        return out

    by_rel: Dict[str, Dict[str, Any]] = {}
    for root, source in get_animation_clips_dirs():
        if not root.exists():
            continue
        found = _files_of(root, "", source)
        for d in sorted(root.iterdir()):
            if d.name.startswith(".") or not d.is_dir():
                continue
            found.extend(_files_of(d, d.name.strip().lower(), source))
        for e in found:
            # free is scanned first; a licensed twin replaces it
            by_rel[e["rel"]] = e
    return sorted(by_rel.values(), key=lambda e: (e["set"], e["rel"]))


def clip_files() -> List[Path]:
    """Every clip file in the shared directory (all sets), sorted."""
    return [e["path"] for e in clip_entries()]


def clip_kinds() -> List[str]:
    """The animation kinds that actually exist right now."""
    return sorted({e["kind"] for e in clip_entries()} - {""})


def pair_kinds() -> List[str]:
    """Kinds that exist as a COMPLETE pair (both halves present in one set)."""
    halves: Dict[Tuple[str, str], set] = {}
    for e in clip_entries():
        if e["role"]:
            halves.setdefault((e["set"], e["kind"]), set()).add(e["role"])
    return sorted({k for (_s, k), roles in halves.items() if roles >= set(PAIR_ROLES)})


def clip_meta(kind: str, cset: str = "",
              stem: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """The sidecar of a clip (duration, fps, pair geometry), None when there is
    none. Looked up in the set directory, then the root.

    THE SIDECAR RULE: for a file ``<stem>.fbx`` the sidecar is ``<stem>.json``
    when that file exists, else the shared ``<kind>.json``. So a numbered
    variant may carry its OWN numbers (``idle_02.fbx`` + ``idle_02.json``) and
    only falls back to the numbers of its kind when it does not. Callers that
    know only a kind (the pair geometry of the listing, the interaction
    engine) pass no ``stem`` and get exactly the old behaviour.
    """
    names = [stem] if stem and stem != kind else []
    names.append(kind)
    candidates = []
    for name in names:
        # licensed first — the sidecar belongs to the file that wins
        for root, _source in reversed(get_animation_clips_dirs()):
            if cset:
                candidates.append(root / cset / f"{name}.json")
            candidates.append(root / f"{name}.json")
    for path in candidates:
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return None
            return data if isinstance(data, dict) else None
    return None


def clip_sets() -> List[str]:
    """The sets that actually have clips — i.e. the non-empty subdirectories."""
    return sorted({e["set"] for e in clip_entries()} - {""})


# ── The locomotion mapping: role → clip kind ─────────────────────────────

def locomotion_clips_path() -> Path:
    """``shared/config/locomotion_clips.json`` — world-independent like the
    clips it points at, tracked in git."""
    return get_config_dir() / "locomotion_clips.json"


def _read_locomotion_file(path: Path) -> Dict[str, Any]:
    """The raw mapping file as a dict; ``{}`` when it is absent or junk (a
    broken file must never leave every figure without a walk)."""
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        logger.warning("locomotion mapping %s unreadable, using defaults: %s",
                       path, e)
        return {}
    if not isinstance(data, dict):
        logger.warning("locomotion mapping %s is not an object, using defaults",
                       path)
        return {}
    return data


def load_locomotion_clips(path: Optional[Path] = None) -> Dict[str, str]:
    """The RESOLVED mapping ``{walk, run, idle} → kind`` — every role present,
    never empty: a missing, empty or non-string entry is the role's own name.

    This is what the API delivers and what the client plays; the file itself
    may hold ``""`` for "default". ``path`` exists for the smoke check, which
    must never touch the real file.
    """
    raw = _read_locomotion_file(path or locomotion_clips_path())
    out = {}
    for role in LOCOMOTION_ROLES:
        value = raw.get(role)
        kind = value.strip().lower() if isinstance(value, str) else ""
        out[role] = kind or role
    return out


def _solo_kinds() -> set:
    """Kinds that exist as a SOLO clip (any set, either library) — a pair
    kind is played by two figures at a shared anchor and cannot be a
    locomotion clip."""
    return {e["kind"] for e in clip_entries() if not e["role"]}


def save_locomotion_clips(changes: Dict[str, Any],
                          path: Optional[Path] = None) -> Dict[str, str]:
    """Merges ``changes`` (``{role: kind}``) into the mapping file and returns
    the resolved mapping.

    Only the roles named in ``changes`` are touched. A kind is normalised like
    a rename target (lowercase, the ``_validate_kind`` alphabet) and must exist
    as a SOLO clip somewhere in the two libraries — a role pointing at a file
    nobody has would leave every figure standing. ``""`` (or ``None``) resets
    the role to its default and is NOT validated against the library: the
    default may legitimately be missing (a library without a ``run`` clip
    falls back through the client's chain, as it always did). Anything that
    is not a known role is an error, not silently dropped.
    """
    if not isinstance(changes, dict):
        raise ClipLibraryError("object expected: {walk?, run?, idle?}")
    unknown = sorted(set(changes) - set(LOCOMOTION_ROLES))
    if unknown:
        raise ClipLibraryError(
            f"unknown locomotion role(s) {', '.join(unknown)} "
            f"(one of {', '.join(LOCOMOTION_ROLES)})")
    resolved_changes: Dict[str, str] = {}
    solo = None
    for role, raw in changes.items():
        if raw is None or (isinstance(raw, str) and not raw.strip()):
            resolved_changes[role] = ""
            continue
        if not isinstance(raw, str):
            raise ClipLibraryError(f"{role}: a clip kind (string) is expected")
        kind = _validate_kind(raw)
        if solo is None:
            solo = _solo_kinds()
        if kind not in solo:
            raise ClipLibraryError(
                f"{role}: no solo clip of kind '{kind}' in any library")
        resolved_changes[role] = kind

    target = path or locomotion_clips_path()
    data = _read_locomotion_file(target)
    # Keep only the known roles in the file — an old or hand-edited key has
    # no reader and would only confuse the next editor.
    data = {role: data.get(role) if isinstance(data.get(role), str) else ""
            for role in LOCOMOTION_ROLES}
    data.update(resolved_changes)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                      encoding="utf-8")
    logger.info("locomotion clips saved: %s", data)
    return load_locomotion_clips(target)


# ── Transitions: the clip that has to play BETWEEN two clips ─────────────

#: Wildcard in a transition rule: "whatever comes next" on the ``to`` side is
#: an EXIT clip, "whatever came before" on the ``from`` side an ENTER clip.
TRANSITION_ANY = "*"


def clip_transitions_path() -> Path:
    """``shared/config/clip_transitions.json`` — beside the locomotion
    mapping and for the same reason: it points at clips, and the clips are
    world-independent, so this is too.

    A separate file rather than a key in the locomotion mapping: that file is
    rewritten to exactly the known roles on every save, so anything else in it
    would be dropped by the next edit.
    """
    return get_config_dir() / "clip_transitions.json"


def _read_transitions_file(path: Path) -> List[Dict[str, Any]]:
    """The raw rule list; ``[]`` when the file is absent or junk — no
    transition is a working state, a crash here would take every figure's
    animation with it."""
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        logger.warning("clip transitions %s unreadable, ignoring: %s", path, e)
        return []
    rules = data.get("transitions") if isinstance(data, dict) else data
    return rules if isinstance(rules, list) else []


def load_transitions(path: Optional[Path] = None) -> List[Dict[str, str]]:
    """The transition rules as ``[{from, to, kind}]``, junk entries dropped.

    Order is the file's own — :func:`resolve_transition` decides by
    specificity, not by position, so a hand-edited file cannot become
    order-dependent behind the editor's back.
    """
    out: List[Dict[str, str]] = []
    seen = set()
    for raw in _read_transitions_file(path or clip_transitions_path()):
        if not isinstance(raw, dict):
            continue
        src = str(raw.get("from") or "").strip().lower()
        dst = str(raw.get("to") or "").strip().lower()
        kind = str(raw.get("kind") or "").strip().lower()
        if not src or not dst or not kind:
            continue
        if (src, dst) in seen:
            continue
        seen.add((src, dst))
        out.append({"from": src, "to": dst, "kind": kind,
                    "accel": _accel(raw.get("accel"))})
    return out


def _accel(raw: Any) -> float:
    """How fast the figure gets up to speed WHILE the bridge plays, as a
    fraction of its normal speed gained per second.

    ``0`` — the default — means it never gains any: the figure stays put for
    the whole clip, which is what standing up out of a seat looks like. ``1``
    reaches full speed after a second, ``0.5`` after two. Anything above 8
    would be indistinguishable from an instant start and is capped there.
    """
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 0.0
    if not value > 0:
        return 0.0
    return round(min(value, 8.0), 3)


def resolve_transition(from_kind: Any, to_kind: Any,
                       rules: Optional[List[Dict[str, Any]]] = None
                       ) -> Optional[Dict[str, Any]]:
    """The RULE that applies when a figure goes from ``from_kind`` to
    ``to_kind`` — ``None`` when nothing is configured.

    The whole rule, not just its clip: what happens during the bridge depends
    on ``accel`` as much as on ``kind``, and two lookups for one answer is how
    the two start to disagree.

    Most specific rule wins, and the order is fixed rather than the file's:

    1. both named — the transition between exactly these two,
    2. ``from`` named, ``to`` the wildcard — the EXIT clip of a state
       ("standing up after sitting, whatever comes next"),
    3. ``to`` named, ``from`` the wildcard — the ENTER clip of a state.

    A switch onto the SAME clip is never a transition: a figure that keeps
    walking must not stand up first.
    """
    src = str(from_kind or "").strip().lower()
    dst = str(to_kind or "").strip().lower()
    if not src or not dst or src == dst:
        return None
    table = load_transitions() if rules is None else rules
    exact = wild_to = wild_from = None
    for r in table:
        rs, rd = r.get("from", ""), r.get("to", "")
        if rs == src and rd == dst:
            exact = r
            break
        if rs == src and rd == TRANSITION_ANY and wild_to is None:
            wild_to = r
        elif rs == TRANSITION_ANY and rd == dst and wild_from is None:
            wild_from = r
    return exact or wild_to or wild_from


def save_transitions(entries: Any,
                     path: Optional[Path] = None) -> List[Dict[str, str]]:
    """Replaces the whole rule list and returns what is now stored.

    The whole list, not a merge: the rules are few and the editor shows all of
    them, so a partial write would only invite two editors to disagree about
    what "the list" is.

    ``kind`` must exist as a SOLO clip — a rule pointing at a file nobody has
    would stall a figure between two states. ``from``/``to`` are NOT checked
    against the library: they are the kinds a pose or a ground happens to
    name, and a world may carry clips this installation does not. Both sides
    wildcard is refused — that rule would fire on every single clip change.
    """
    if not isinstance(entries, list):
        raise ClipLibraryError("a list of {from, to, kind} is expected")
    out: List[Dict[str, str]] = []
    seen = set()
    solo = None
    for i, raw in enumerate(entries):
        if not isinstance(raw, dict):
            raise ClipLibraryError(f"rule {i + 1}: an object is expected")
        src = str(raw.get("from") or "").strip().lower()
        dst = str(raw.get("to") or "").strip().lower()
        if not src or not dst:
            raise ClipLibraryError(f"rule {i + 1}: 'from' and 'to' are required")
        if src == TRANSITION_ANY and dst == TRANSITION_ANY:
            raise ClipLibraryError(
                f"rule {i + 1}: '{TRANSITION_ANY}' on both sides would fire on "
                "every clip change — name at least one side")
        for side, value in (("from", src), ("to", dst)):
            if value != TRANSITION_ANY:
                _validate_kind(value)
        kind = _validate_kind(raw.get("kind"))
        if solo is None:
            solo = _solo_kinds()
        if kind not in solo:
            raise ClipLibraryError(
                f"rule {i + 1}: no solo clip of kind '{kind}' in any library")
        if (src, dst) in seen:
            raise ClipLibraryError(
                f"rule {i + 1}: '{src}' to '{dst}' is already ruled")
        seen.add((src, dst))
        out.append({"from": src, "to": dst, "kind": kind,
                    "accel": _accel(raw.get("accel"))})

    target = path or clip_transitions_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"transitions": out}, indent=2,
                                 ensure_ascii=False) + "\n", encoding="utf-8")
    logger.info("clip transitions saved: %d rule(s)", len(out))
    return out


# ── The library view: one clip as the listing (and the editor) sees it ────

def _origin(meta: Optional[Dict[str, Any]]) -> str:
    """Where the clip came from, in one word: ``cmu`` for a CMU-derived take,
    otherwise the skeleton family the FBX import retargeted from
    (``unity-humanoid``, …), ``unknown`` without a sidecar."""
    src = (meta or {}).get("source")
    if not isinstance(src, dict):
        return "unknown"
    database = str(src.get("database") or "")
    if "CMU" in database:
        return "cmu"
    return str(src.get("bone_map") or "") or "unknown"


def clip_loops(meta: Optional[Dict[str, Any]]) -> bool:
    """Does this clip REPEAT, or does it hold its last frame?

    The sidecar's own ``loop`` is the answer whenever it is there — including
    an explicit ``false`` against the ``geometry.loop`` the import measured:
    that flag is the ADMIN's decision, taken after the import in the Poses
    tab (plan-animationen-echtzeit-stehplatz.md E5), and a measurement must
    never overrule it. Only without it does the import's own finding count.
    """
    if not isinstance(meta, dict):
        return False
    if "loop" in meta:
        return bool(meta["loop"])
    geometry = meta.get("geometry")
    return bool(isinstance(geometry, dict) and geometry.get("loop"))


def clip_view(entry: Dict[str, Any]) -> Dict[str, Any]:
    """One ``clip_entries()`` entry as the API delivers it — the file facts
    plus what its sidecar knows.

    The sidecar is looked up exactly the way playback looks it up
    (``clip_meta``: ``<stem>.json`` before the shared ``<kind>.json``, set
    directory before the library root, licensed before free), so a numbered
    variant reports its OWN numbers when it has a sidecar and those of its
    kind otherwise. Without any sidecar the numeric fields are ``None`` —
    that is a normal state, not an error.
    """
    path: Path = entry["path"]
    meta = clip_meta(entry["kind"], entry["set"], stem=path.stem)
    return {
        "kind": entry["kind"],
        "role": entry["role"],
        "set": entry["set"],
        "source": entry["source"],
        "library": entry["source"],
        "rel": entry["rel"],
        "name": path.stem,
        "filename": path.name,
        # Percent-encoded PER SEGMENT: clip file names are free text and do
        # contain spaces ("standing washing.fbx"), so the raw rel is not a
        # usable URL. Clients take this string as it is — they never encode
        # it a second time and never rebuild it from name + set.
        "url": "/assets/animation-clips/"
               + ("licensed/" if entry["source"] == "licensed" else "")
               + "/".join(quote(seg) for seg in entry["rel"].split("/")),
        "size": path.stat().st_size,
        "has_sidecar": meta is not None,
        "origin": _origin(meta),
        "duration_s": (meta or {}).get("duration_s"),
        "fps": (meta or {}).get("fps"),
        "frames": (meta or {}).get("frames"),
        "loop": clip_loops(meta),
    }


# ── Editing the libraries: delete, rename, move ──────────────────────────

def library_root(library: str) -> Path:
    """The directory of ``free`` / ``licensed``; anything else is an error."""
    lib = str(library or "").strip().lower()
    if lib == "free":
        return get_animation_clips_dir()
    if lib == "licensed":
        return get_licensed_clips_dir()
    raise ClipLibraryError(f"unknown library '{library}' (free|licensed)")


def resolve_clip(library: str, rel: str) -> Path:
    """``[<set>/]<file>`` inside one library → the file path.

    The same hardening as the serving route: at most one set segment, no empty
    segment, no ``.``/``..``, no backslash, only clip extensions, and the
    resolved path must stay inside the library (``resolve()`` on both sides,
    so a symlink pointing out is refused too). The file need not exist —
    that is the caller's 404.
    """
    base = library_root(library)
    segments = str(rel or "").split("/")
    if not 1 <= len(segments) <= 2:
        raise ClipLibraryError("path must be [<set>/]<file>")
    for seg in segments:
        if not seg or seg in (".", "..") or "\\" in seg:
            raise ClipLibraryError("invalid path segment")
    base = base.resolve()
    path = base.joinpath(*segments).resolve()
    if not path.is_relative_to(base):
        raise ClipLibraryError("path escapes the library")
    if path.suffix.lower() not in CLIP_EXTS:
        raise ClipLibraryError(f"not a clip file ({', '.join(CLIP_EXTS)})")
    return path


def _split_stem(stem: str) -> Tuple[str, str, str]:
    """``(kind, role, numbering)`` of a file stem — ``hug__a_02`` →
    ``("hug", "a", "_02")``. The three parts a rename recombines."""
    m = _STEM_RE.match(stem.strip().lower())
    if not m:                                                # pragma: no cover
        return stem.strip().lower(), "", ""
    return m.group("kind") or stem, m.group("role") or "", m.group("num") or ""


def _pair_partner(path: Path) -> Optional[Path]:
    """The other half of a pair clip (``kiss__a`` ↔ ``kiss__b``), None when the
    clip is a solo one or the partner file is missing."""
    kind, role, num = _split_stem(path.stem)
    if not role:
        return None
    other = PAIR_ROLES[0] if role == PAIR_ROLES[1] else PAIR_ROLES[1]
    partner = path.with_name(f"{kind}{ROLE_SEPARATOR}{other}{num}{path.suffix}")
    return partner if partner.is_file() else None


def _kind_files(directory: Path, kind: str) -> List[Path]:
    """Every clip file of one kind still lying in one directory — the numbered
    variants and both pair halves. Asked AFTER a delete or a move, so what it
    returns is what still needs the shared ``<kind>.json``."""
    if not directory.is_dir():
        return []
    return [p for p in sorted(directory.iterdir())
            if p.is_file() and p.suffix.lower() in CLIP_EXTS
            and parse_clip_role(p.name)[0] == kind]


def _own_sidecar(path: Path) -> Optional[Path]:
    """The sidecar belonging to THIS file alone — ``walk_02.json`` next to
    ``walk_02.fbx``. None when the stem IS the kind (then the sidecar is the
    shared ``<kind>.json``, which the kind rules own) or when there is none."""
    if path.stem.strip().lower() == parse_clip_role(path.name)[0]:
        return None
    sidecar = path.with_suffix(".json")
    return sidecar if sidecar.is_file() else None


def _validate_kind(raw: Any) -> str:
    kind = str(raw or "").strip().lower()
    if ROLE_SEPARATOR in kind:
        raise ClipLibraryError(
            f"kind must not contain '{ROLE_SEPARATOR}' (the pair role separator)")
    if _NUM_SUFFIX_RE.search(kind):
        # A kind ending in _<n> would be parsed back as the kind without it:
        # renaming to "walk_02" produces "walk_02.fbx", which the layout reads
        # as the second variant of "walk". The numbering is not nameable.
        raise ClipLibraryError(
            "kind must not end in '_<number>' — that suffix is the numbering "
            "of several clips of one kind, not part of the kind itself")
    if not KIND_RE.match(kind):
        raise ClipLibraryError(
            "kind must be lowercase letters, digits, space, '-' or '_'")
    return kind


def _validate_set(raw: Any) -> str:
    cset = str(raw or "").strip().lower()
    if not cset:
        return ""                                    # the neutral root
    if not SET_RE.match(cset):
        raise ClipLibraryError(
            "set must be lowercase letters, digits, '-' or '_'")
    return cset


def reload_clip_caches() -> None:
    """Re-read what caches the clip vocabulary. The pose dropdown and the
    animation-set fallback read from the preset caches — an edited library has
    to be visible at once, not after a restart (same reload the clip import
    does)."""
    try:
        from app.core import expression_pose_maps as epm
        epm.reload_presets()
    except Exception as e:                                   # pragma: no cover
        logger.warning("preset reload after clip library change failed: %s", e)
    try:
        from app.core import pose_catalog
        pose_catalog.reload_catalogs()
    except Exception as e:                                   # pragma: no cover
        logger.warning("pose catalog reload after clip library change failed: %s", e)


def delete_clip(library: str, rel: str) -> Dict[str, Any]:
    """Removes one clip from one library — both halves when it is a pair.

    A sidecar that belongs to THIS file alone (``walk_02.json`` next to
    ``walk_02.fbx``) goes with it. The shared ``<kind>.json`` goes only when NO
    file of that kind is left in the same directory: numbered variants without
    an own sidecar share it, and the last one takes it along. A set directory
    that lost its last file is no set any more and is removed with it (never a
    library root).
    """
    path = resolve_clip(library, rel)
    if not path.is_file():
        raise ClipNotFound(f"{rel} does not exist in the {library} library")
    kind, _role = parse_clip_role(path.name)
    root = library_root(library).resolve()
    cset = path.parent.name if path.parent.resolve() != root else ""

    targets = [path]
    partner = _pair_partner(path)
    if partner is not None:
        targets.append(partner)
    sidecars_removed = []
    for p in targets:
        own = _own_sidecar(p)
        p.unlink(missing_ok=True)
        if own is not None:
            own.unlink(missing_ok=True)
            sidecars_removed.append(own.name)

    sidecar = path.parent / f"{kind}.json"
    sidecar_removed = False
    if sidecar.is_file() and not _kind_files(path.parent, kind):
        sidecar.unlink(missing_ok=True)
        sidecar_removed = True
        sidecars_removed.append(sidecar.name)

    if cset and path.parent.is_dir() and not any(path.parent.iterdir()):
        path.parent.rmdir()

    reload_clip_caches()
    deleted = sorted(f"{cset}/{p.name}" if cset else p.name for p in targets)
    logger.info("clip deleted: %s (%s library)", ", ".join(deleted), library)
    return {"deleted": deleted, "kind": kind, "set": cset, "library": library,
            "sidecar_removed": sidecar_removed,
            "sidecars_removed": sorted(sidecars_removed)}


def rename_clip(library: str, rel: str, *, kind: Optional[str] = None,
                cset: Optional[str] = None,
                to_library: Optional[str] = None,
                overwrite: bool = False) -> List[Dict[str, Any]]:
    """Renames a clip and/or moves it to another set or library.

    A pair moves as a pair (both halves), a numbered variant keeps its
    ``_<n>``. The sidecars follow: one belonging to a single file
    (``walk_02.json``) travels with that file and is renamed with it, the
    shared ``<kind>.json`` MOVES when nothing of the old kind stays behind and
    is COPIED when other variants still need it. The ``kind`` field is
    rewritten with the new name in both cases. An existing sidecar at the
    target is left untouched — it belongs to the variants already there.

    A name already taken at the target is a ``ClipExists`` — unless
    ``overwrite`` says the admin answered the question with "Replace": then
    the file lying there is deleted before the move, together with the sidecar
    belonging to it ALONE, for every half of a pair alike (``_clear_replaced``).

    Returns the moved clips as listing views.
    """
    src = resolve_clip(library, rel)
    if not src.is_file():
        raise ClipNotFound(f"{rel} does not exist in the {library} library")
    src_root = library_root(library).resolve()
    old_set = src.parent.name if src.parent.resolve() != src_root else ""
    old_kind, _role, _num = _split_stem(src.stem)

    new_kind = _validate_kind(kind) if kind is not None else old_kind
    new_set = _validate_set(cset) if cset is not None else old_set
    new_library = str(to_library or library).strip().lower()
    if new_library not in LIBRARIES:
        raise ClipLibraryError(f"unknown library '{to_library}' (free|licensed)")

    dest_dir = library_root(new_library).resolve() / new_set if new_set \
        else library_root(new_library).resolve()

    sources = [src]
    partner = _pair_partner(src)
    if partner is not None:
        sources.append(partner)

    moves: List[Tuple[Path, Path]] = []
    replaced: List[Path] = []
    for p in sources:
        _k, role, num = _split_stem(p.stem)
        name = new_kind + (f"{ROLE_SEPARATOR}{role}" if role else "") + num + p.suffix
        dest = dest_dir / name
        if dest.resolve() == p.resolve():
            continue                                  # nothing to do for this half
        if dest.exists():
            if not overwrite:
                raise ClipExists(
                    f"{new_set + '/' if new_set else ''}{name} already exists "
                    f"in the {new_library} library")
            replaced.append(dest)
        moves.append((p, dest))
    if not moves:
        return [_view_of(src, new_set, new_library)]        # nothing changed

    dest_dir.mkdir(parents=True, exist_ok=True)
    if replaced:
        gone = _clear_replaced(replaced, dest_dir, new_kind)
        logger.info("clip replaced at the target: %s (%s%s, %s library)",
                    ", ".join(gone), f"{new_set}/" if new_set else "",
                    new_kind, new_library)
    # Only a file WITHOUT a sidecar of its own still depends on the shared
    # <kind>.json — one that brings its own must not drag a copy along.
    needs_shared = False
    for source, dest in moves:
        own = _own_sidecar(source)
        needs_shared = needs_shared or own is None
        shutil.move(str(source), str(dest))
        if own is not None:
            _take_own_sidecar(own, dest.with_suffix(".json"), new_kind)

    _move_sidecar(src.parent, old_kind, dest_dir, new_kind, needed=needs_shared)

    # A set directory that lost its last file is no set any more.
    if old_set and src.parent.is_dir() and not any(src.parent.iterdir()):
        src.parent.rmdir()

    reload_clip_caches()
    logger.info("clip renamed: %s%s (%s) -> %s%s (%s)",
                f"{old_set}/" if old_set else "", old_kind, library,
                f"{new_set}/" if new_set else "", new_kind, new_library)
    return [_view_of(dest, new_set, new_library) for _s, dest in moves]


def set_clip_loop(library: str, rel: str, loop: bool) -> List[Dict[str, Any]]:
    """Writes the LOOP flag of a clip — the admin's decision after the import
    (E5): loop = repeat the clip, no loop = hold its last frame.

    The flag belongs to the KIND in its set, not to a single file: it is
    written into the shared ``<kind>.json`` beside the clip, so both halves of
    a pair (``hug__a`` / ``hug__b``) and every numbered variant of the kind
    play the same way. A variant carrying a sidecar of its OWN is written too
    — otherwise it would be the one file in the set that ignores the switch.

    Without a shared sidecar there is nowhere to put it: a clip whose numbers
    were never written cannot be given a flag (``ClipLibraryError``). Returns
    the touched clips as listing views.
    """
    path = resolve_clip(library, rel)
    if not path.is_file():
        raise ClipNotFound(f"{rel} does not exist in the {library} library")
    kind, _role = parse_clip_role(path.name)
    root = library_root(library).resolve()
    cset = path.parent.name if path.parent.resolve() != root else ""
    sidecar = path.parent / f"{kind}.json"
    if not sidecar.is_file():
        raise ClipLibraryError(
            f"'{kind}' has no sidecar {sidecar.name} — the loop flag is stored "
            "there, so the clip has to be (re-)imported first")
    files = _kind_files(path.parent, kind)
    targets = [sidecar] + [s for s in (_own_sidecar(p) for p in files)
                           if s is not None]
    for target in targets:
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise ClipLibraryError(f"{target.name} is not readable: {e}")
        if not isinstance(data, dict):
            raise ClipLibraryError(f"{target.name} is not an object")
        data["loop"] = bool(loop)
        target.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                          encoding="utf-8")
    reload_clip_caches()
    logger.info("clip loop flag: %s%s (%s) -> %s", f"{cset}/" if cset else "",
                kind, library, bool(loop))
    return [_view_of(p, cset, library) for p in files]


def _view_of(path: Path, cset: str, library: str) -> Dict[str, Any]:
    """The listing view of one file that was just written — built from the
    path, not from a rescan: a free clip shadowed by a licensed twin would
    otherwise not appear in ``clip_entries()`` at all."""
    kind, role = parse_clip_role(path.name)
    rel = f"{cset}/{path.name}" if cset else path.name
    return clip_view({"kind": kind, "role": role, "set": cset,
                      "source": library, "rel": rel, "path": path})


def _move_sidecar(src_dir: Path, old_kind: str, dest_dir: Path,
                  new_kind: str, *, needed: bool = True) -> None:
    """Takes the shared ``<kind>.json`` along with the files that just moved.

    It MOVES when no file of the old kind is left in the source directory and
    COPIES when there still are numbered variants sharing it. A sidecar
    already sitting at the target wins — those are the numbers of the clips
    that were there first.

    ``needed`` is False when every moved file brought a sidecar of ITS OWN:
    the shared one is then only taken along when it would otherwise dangle in
    the source directory, and never copied to a kind nothing reads it for.
    """
    sidecar = src_dir / f"{old_kind}.json"
    if not sidecar.is_file():
        return
    orphaned = not _kind_files(src_dir, old_kind)
    if not needed and not orphaned:
        return
    target = dest_dir / f"{new_kind}.json"
    if target.exists() and target.resolve() != sidecar.resolve():
        if orphaned:
            sidecar.unlink(missing_ok=True)
        return
    if orphaned:
        shutil.move(str(sidecar), str(target))
    else:
        shutil.copy2(str(sidecar), str(target))
    if new_kind != old_kind:
        _rewrite_sidecar_kind(target, new_kind)


def _clear_replaced(targets: List[Path], dest_dir: Path, kind: str) -> List[str]:
    """Clears the way for an OVERWRITING move — the admin's "Replace".

    Every file being replaced goes with the sidecar that belongs to it alone
    (``walk_02.json``), one half of a pair like the other. The shared
    ``<kind>.json`` beside them goes only when NO file of that kind is left in
    the target directory after the deletions: while other variants remain it
    is theirs, not the replaced file's, and the incoming sidecar must not
    overwrite their numbers.

    Returns the names removed, for the log line of the caller.
    """
    removed: List[str] = []
    for dest in targets:
        own = _own_sidecar(dest)
        dest.unlink(missing_ok=True)
        removed.append(dest.name)
        if own is not None:
            own.unlink(missing_ok=True)
            removed.append(own.name)
    shared = dest_dir / f"{kind}.json"
    if shared.is_file() and not _kind_files(dest_dir, kind):
        shared.unlink(missing_ok=True)
        removed.append(shared.name)
    return removed


def _take_own_sidecar(sidecar: Path, target: Path, new_kind: str) -> None:
    """Moves the sidecar of ONE file (``walk_02.json``) to the name that file
    now has (``stroll_02.json``) and rewrites its ``kind``. A sidecar already
    lying at the target wins — it belongs to the file that was there first."""
    if target.exists() and target.resolve() != sidecar.resolve():
        return
    if target.resolve() != sidecar.resolve():
        shutil.move(str(sidecar), str(target))
    _rewrite_sidecar_kind(target, new_kind)


def _rewrite_sidecar_kind(target: Path, new_kind: str) -> None:
    """Puts the new kind into a sidecar that was just moved or copied."""
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if isinstance(data, dict) and data.get("kind") != new_kind:
        data["kind"] = new_kind
        target.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                          encoding="utf-8")
