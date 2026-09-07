"""Stage 1 of the furnishing job, inverted: the room's NEED first, the
library second (plan-furnish-v2.md § 2 B3, decision E4).

Until v1 the library got the first bite: one stage picked from the catalog, the
next was left with the remaining budget and was forbidden to propose anything
the catalog already named. A medieval kitchen therefore pulled in a modern
dining chair, because the fitting chair could neither be picked nor built. Now
``furnish_needs`` writes what the room needs WITHOUT seeing the catalog, and
``furnish_match`` maps at most one library piece onto each need — strictly:
same purpose, compatible style, same mount, size within ±40 %. Everything
unmatched is built.

This module is the validation half of that stage: what a need may say, which
catalog a match may choose from and which match survives the arithmetic. It is
pure — no DB, no LLM, no world lookups — so the job orchestrator
(``room_furnish``) keeps only the phases and the prompts keep only the wording.

THE CODE DECIDES WHAT A FILTER CAN DECIDE (constraint 4): the setting filter
(no trees indoors), the mount equality and the size tolerance are checked
here, after the model has answered. The prompt asks for them so the answer is
usually right; the check is what makes it true.
"""

from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.core.log import get_logger

logger = get_logger(__name__)

#: Cap on the number of needs one room may carry — replaces v1's two caps
#: (one for the library picks, one for the invented pieces), which only
#: existed because the two stages competed for one budget.
MAX_NEEDS = 16
#: Cap per need — a table for twelve is a table for twelve, thirteen chairs
#: are a hallucination.
MAX_COUNT = 12
MIN_DIM_M = 0.05
MAX_DIM_M = 5.0
#: How far a library piece's largest dimension may differ from the need's,
#: relative to the need (±40 %, plan § 2 B3).
DIM_TOLERANCE = 0.4
#: How much of a variant's generation subject travels as the catalog's style
#: hint. Long enough to name material and colour, short enough that a catalog
#: of 100 props stays one screen per 10 props.
CATALOG_STYLE_CHARS = 60

#: Categories that belong OUTSIDE (B8). An indoor room never gets them, and
#: that is a filter, not a judgement call — the model used to pick trees for a
#: living room because the catalog was all the library had. Singular, lower
#: case, one word wherever the thing has one — the same vocabulary the prop
#: library is classified in, so a whole house or a tuft of grass is caught
#: here just like a tree.
OUTDOOR_CATEGORIES = ("deciduous tree", "evergreen tree", "tree", "bush",
                      "shrub", "grass", "forest floor", "rock", "terrain",
                      "building")
#: …and the tag that says the same thing on a prop of any category.
OUTDOOR_TAG = "outdoor"

#: The fillable panels a need may ask for, with the one line the prompt shows.
#: Derived from ``props.AREA_KINDS`` minus ``leaf`` (the door-leaf cut, which
#: is geometry and never a wish of a piece of furniture).
KEY_AREA_MEANINGS: Dict[str, str] = {
    "picture": "a flat face that shows an image — painting, poster, screen",
    "glass": "a transparent or reflecting pane — mirror, glazed door, window",
}


def key_area_kinds() -> List[Dict[str, str]]:
    """The key-area kinds a need may ask for, as ``{key, meaning}`` for the
    prompt — every colour kind the props module knows, ``leaf`` excluded."""
    from app.core.props import AREA_KINDS, LEAF_KIND
    return [{"key": k, "meaning": KEY_AREA_MEANINGS.get(k, k)}
            for k in AREA_KINDS if k != LEAF_KIND]


def _allowed_key_areas() -> List[str]:
    return [k["key"] for k in key_area_kinds()]


# ── small coercions ─────────────────────────────────────────────────────

def num(value: Any, lo: float, hi: float) -> Optional[float]:
    """The number ``value`` names, rounded to mm — or None when it is not a
    number or leaves ``[lo, hi]``."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return round(v, 3) if lo <= v <= hi else None


def count(value: Any) -> int:
    """1..:data:`MAX_COUNT`; anything unreadable is one piece."""
    try:
        return max(1, min(MAX_COUNT, int(float(value))))
    except (TypeError, ValueError):
        return 1


def valid_marker(raw: Any, groups: Sequence[str]) -> Optional[Dict[str, Any]]:
    """The marker suggestion of a need: a PLACE TYPE of the pose catalog
    (``group``) plus box fractions. The id is minted where the marker is
    stored (``props.sanitize_markers``)."""
    from app.core.props import MARKER_AT_MAX, MARKER_AT_MIN, MARKER_AT_Y_MIN
    if not isinstance(raw, dict):
        return None
    group = str(raw.get("group") or "").strip().lower()
    if not group or group not in groups:
        return None
    at = raw.get("at")
    if not isinstance(at, (list, tuple)) or len(at) != 3:
        at = [0.5, 0.5, 0.5]
    try:
        # Same range as props.sanitize_markers — fractions may leave the box.
        at3 = [round(min(max(float(at[i]),
                             MARKER_AT_Y_MIN if i == 1 else MARKER_AT_MIN),
                         MARKER_AT_MAX), 4)
               for i in range(3)]
    except (TypeError, ValueError):
        at3 = [0.5, 0.5, 0.5]
    return {"group": group, "at": at3}


# ── the need list ───────────────────────────────────────────────────────

def valid_needs(raw: Any, groups: Sequence[str], *, is_yard: bool = False,
                library: Optional[Dict[str, Dict[str, Any]]] = None,
                limit: int = MAX_NEEDS,
                ) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
    """The room's need list, validated. Returns ``(needs, dropped)``.

    Keys are RE-MINTED ``n1..nN`` in list order — the model's own keys are
    read by nothing, and the dialog edits by key, so two entries answering
    ``"n3"`` must not be able to collide.

    ``dropped`` carries what was thrown away with a reason the dialog can
    show: a need the yard cannot hold (no walls, no ceiling — code, not
    prompt), an impossible size, a piece without a generation subject.
    Entries that say nothing at all (no kind) vanish silently; there is
    nothing to report about them.

    ``library`` — when given, the entry's ``prop_id`` is kept if the library
    really has it and ``build`` is derived from it (``confirm`` re-validates
    an ADMIN-edited list, and the client must not be able to declare a piece
    "already built"). Without it the entries carry neither key; the match
    stage adds them.
    """
    needs: List[Dict[str, Any]] = []
    dropped: List[Dict[str, str]] = []
    allowed_areas = _allowed_key_areas()
    from app.core.props import MOUNT_KINDS
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict) or len(needs) >= limit:
            continue
        kind = str(entry.get("kind") or "").strip()[:60]
        if not kind:
            continue
        mount = str(entry.get("mount") or "").strip().lower()
        if mount not in MOUNT_KINDS:
            mount = "floor"
        if is_yard and mount in ("wall", "ceiling"):
            dropped.append({"kind": kind,
                            "reason": "the yard has no walls/ceiling"})
            continue
        dims: Dict[str, float] = {}
        for key in ("width_m", "depth_m", "height_m"):
            v = num(entry.get(key), MIN_DIM_M, MAX_DIM_M)
            if v is None:
                break
            dims[key] = v
        if len(dims) != 3:
            dropped.append({
                "kind": kind,
                "reason": f"unrealistic size (each axis {MIN_DIM_M}–"
                          f"{MAX_DIM_M} m)"})
            continue
        description = str(entry.get("description") or "").strip()[:600]
        if not description:
            dropped.append({"kind": kind,
                            "reason": "no description to generate it from"})
            continue
        need: Dict[str, Any] = {
            "key": f"n{len(needs) + 1}",
            "kind": kind,
            "category": str(entry.get("category") or "").strip()[:40],
            "count": count(entry.get("count")),
            "mount": mount,
            "style": str(entry.get("style") or "").strip()[:60],
            "description": description,
            "marker": valid_marker(entry.get("marker"), groups),
            "key_areas": [k for k in allowed_areas
                          if k in {str(a).strip().lower()
                                   for a in (entry.get("key_areas") or [])
                                   if isinstance(a, (str, bytes))}],
            "from_description": bool(entry.get("from_description")),
            **dims,
        }
        if library is not None:
            pid = str(entry.get("prop_id") or "").strip()
            need["prop_id"] = pid if pid in library else None
            need["build"] = need["prop_id"] is None
        needs.append(need)
    return needs, dropped


def valid_surfaces(raw: Any, kinds: Sequence[str]) -> Optional[Dict[str, str]]:
    """The floor/wall texture proposal (E9, B15), reduced to kinds the
    surface-texture library really has. ``None`` when nothing survives — the
    dialog then shows no surface row at all."""
    if not isinstance(raw, dict):
        return None
    known = set(kinds)
    out = {slot: str(raw.get(slot) or "").strip()
           for slot in ("floor", "wall")}
    out = {slot: kind for slot, kind in out.items() if kind in known}
    return out or None


# ── the catalog and the match ───────────────────────────────────────────

def build_catalog(library: Dict[str, Dict[str, Any]], *, indoor: bool
                  ) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    """The library as prompt lines plus the ``ref → prop id`` map.

    ``ref`` is ``#1``, ``#2``, … and never the slug: the slug is built from
    the name, so a model that "remembers" a piece writes a plausible id that
    does not exist (the field found ``kitchen-cabinet-hanging-a58364`` for
    ``kitchen-cabinet-a58364``) and the pick vanished silently. A short ref
    cannot be guessed, only copied.

    ``indoor`` drops the outdoor categories and everything tagged ``outdoor``
    (B8). An open-air target drops nothing — a yard café has chairs.
    """
    lines: List[Dict[str, Any]] = []
    by_ref: Dict[str, str] = {}
    for prop in library.values():
        category = str(prop.get("category") or "").strip().lower()
        tags = [str(t).strip().lower() for t in (prop.get("tags") or [])]
        if indoor and (category in OUTDOOR_CATEGORIES or OUTDOOR_TAG in tags):
            continue
        ref = f"#{len(lines) + 1}"
        by_ref[ref] = str(prop.get("id") or "")
        # The style hint is the beginning of the variant's generation subject
        # — the one sentence that says what the piece is made of. The lean
        # record carries it as `description` (``props.variant_description`` of
        # the primary variant), so nothing is read twice off a sidecar here.
        style = str(prop.get("description") or "").strip()
        lines.append({
            "ref": ref,
            "name": prop.get("name") or prop.get("id") or ref,
            "category": prop.get("category") or "",
            "mount": prop.get("mount") or "unclassified",
            "width_m": prop.get("width_m"),
            "depth_m": prop.get("depth_m"),
            "height_m": prop.get("height_m"),
            "style": style[:CATALOG_STYLE_CHARS],
            "size_estimated": bool(prop.get("dims_estimated")),
            "tags": prop.get("tags") or [],
        })
    return lines, by_ref


def _largest(dims: Dict[str, Any]) -> float:
    try:
        return max(float(dims.get(k) or 0.0)
                   for k in ("width_m", "depth_m", "height_m"))
    except (TypeError, ValueError):
        return 0.0


def match_fits(need: Dict[str, Any], prop: Dict[str, Any]) -> str:
    """Why this library piece may NOT serve this need — ``""`` when it may.

    The two mechanical halves of the prompt's rule, re-checked in code: the
    mount has to be the same (an unclassified prop stands on the floor, which
    is what the solver assumes too) and the largest dimension has to lie
    within ±40 % of the need's. Purpose and style stay the model's judgement —
    no formula decides whether a bench is a chair.
    """
    need_mount = str(need.get("mount") or "floor")
    prop_mount = str(prop.get("mount") or "") or "floor"
    if need_mount != prop_mount:
        return f"mount {prop_mount} ≠ {need_mount}"
    want = _largest(need)
    have = _largest(prop)
    if want <= 0 or have <= 0:
        return "no size to compare"
    if abs(have - want) > DIM_TOLERANCE * want:
        return (f"size {have:.2f} m vs {want:.2f} m — more than "
                f"{int(DIM_TOLERANCE * 100)} % apart")
    return ""


def valid_matches(raw: Any, needs: Sequence[Dict[str, Any]],
                  by_ref: Dict[str, str],
                  library: Dict[str, Dict[str, Any]]) -> Dict[str, str]:
    """``need key → prop id`` for every match that survives.

    An unknown need key, an unknown ref and a match that fails
    :func:`match_fits` all end as "no match" — the need is built instead,
    which is the cheap outcome. One prop may serve several needs.
    """
    keys = {str(n.get("key") or "") for n in needs}
    by_key = {str(n.get("key") or ""): n for n in needs}
    out: Dict[str, str] = {}
    for entry in raw if isinstance(raw, list) else []:
        if not isinstance(entry, dict):
            continue
        key = str(entry.get("need") or "").strip()
        if key not in keys:
            continue
        ref = str(entry.get("ref") or "").strip()
        pid = by_ref.get(ref) or ""
        prop = library.get(pid)
        if not prop:
            if ref:
                logger.info("furnish_match: %s → unknown ref %r, building it",
                            key, ref)
            continue
        reason = match_fits(by_key[key], prop)
        if reason:
            logger.info("furnish_match: %s → %s refused (%s), building it",
                        key, pid, reason)
            continue
        out[key] = pid
    return out


def attach_matches(needs: List[Dict[str, Any]],
                   matches: Dict[str, str]) -> List[Dict[str, Any]]:
    """Fold the match result into the need list: ``prop_id`` (the library
    piece that serves it, or None) and ``build`` (there is none, so it has to
    be made). Both are DERIVED here and nowhere else."""
    for need in needs:
        pid = matches.get(str(need.get("key") or ""))
        need["prop_id"] = pid or None
        need["build"] = pid is None
    return needs
