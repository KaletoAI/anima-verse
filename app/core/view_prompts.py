"""The VIEW vocabulary of mesh-input renders — shared by props and locations.

A multi-view img2mesh alias takes up to four images of one subject: front,
back, left, right (``openai_mesh.select_slot_images`` maps them onto the
alias' slots). Characters render their extra views through
``model_refs.py`` (``tpose_back`` / ``tpose_side``); props and location
models go through here. Same shape as the T-pose precedent:

* the FRONT keeps the base use case (``prop``, ``building``, ``room_model`` …),
* the BACK gets ``<base>_back`` — its own style and its own negative, because
  a rear render fails in its own way,
* LEFT and RIGHT share ``<base>_side``; the side itself is said in a phrase
  prepended to the subject (early tokens steer diffusion).

Gallery image types of a location model source are ``building-<view>``.
The character path is deliberately NOT moved onto this module (2026-09-02).
"""
from typing import Any

VIEWS = ("front", "back", "left", "right")
EXTRA_VIEWS = ("back", "left", "right")

_VIEW_PREFIX = {
    "front": "",
    "back": "seen directly from behind, the rear side facing the camera",
    "left": "seen from the left side, the left flank facing the camera",
    "right": "seen from the right side, the right flank facing the camera",
}

BUILDING_TYPES = tuple(f"building-{v}" for v in VIEWS)


def is_view(name: Any) -> bool:
    """True for one of the four view names (exact, lower-case)."""
    return isinstance(name, str) and name in VIEWS


def view_use_case(base: str, view: str) -> str:
    """The use case a render of ``view`` composes from, given the FRONT's
    base use case. Raises ``ValueError`` for an unknown view — a typo must
    not silently render a front."""
    if not is_view(view):
        raise ValueError(f"unknown view: {view!r}")
    if view == "front":
        return base
    return f"{base}_back" if view == "back" else f"{base}_side"


def view_prefix(view: str) -> str:
    """The phrase prepended to the subject for this view ('' for front)."""
    if not is_view(view):
        raise ValueError(f"unknown view: {view!r}")
    return _VIEW_PREFIX[view]


def view_subject(view: str, subject: str) -> str:
    """``subject`` with the view phrase in front of it — the front unchanged."""
    prefix = view_prefix(view)
    subject = (subject or "").strip()
    if not prefix:
        return subject
    return f"{prefix}, {subject}" if subject else prefix


def building_type(view: str) -> str:
    """Gallery image type of a location model source seen from ``view``."""
    if not is_view(view):
        raise ValueError(f"unknown view: {view!r}")
    return f"building-{view}"


def building_view(image_type: Any) -> str:
    """The view a gallery image type names ('' when it is not a building
    view type — ``day``, ``map_2d`` and the retired bare ``building`` alike)."""
    if isinstance(image_type, str) and image_type in BUILDING_TYPES:
        return image_type[len("building-"):]
    return ""
