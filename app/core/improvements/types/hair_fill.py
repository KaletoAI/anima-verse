"""``hair_fill`` — the hair mesh of characters on the base-body pipeline that
have hair text but no hair mesh, made at idle time (spec
docs/superpowers/specs/2026-11-11-improvements-figure-pipeline-design.md § 6.5).

A subject is a character on the pipeline with a ready base and hair text
(``garment_hair.hair_description`` — a bald character has none) that has no
hair item at all, or wears its hair item without an accepted fit on the
current base for the current method (``garments.hair_summary`` status
``missing``; a served older fit is ``stale`` — ``fit_refit`` or the chain's
own trigger handles it). A hair item the character owns but took off in the
Hair tab is no subject (``garments._ensure_hair``'s rule). The method is the
character's (``garment_hair.hair_method``, the world default) — read, never
set.

The cost before start is ``garments.run_estimate`` of the worn item; without
an item yet, the full chain of the method (``garments.HUB_JOBS``: edit chain
5, HairDeck 1, subtract 3).

No automatic re-spend: a persisted chain failure of the item's current fsig
(``garments.cached_failure``) excludes it, and a run that ends refused —
HairDeck's ``NO_HAIR_ERROR``, a gate, any non-load failure — raises
``CandidateRefused``. Load (a run queued or in flight, an occasion that
resolves to nothing right now, a chain result ``retry_later``) is busy.
"""
from typing import Any, Dict, List, Optional, Tuple

from app.core.improvements.base import (Candidate, CandidateBusy, CandidateRefused, ImprovementType,
                                        ParamField)
from app.core.improvements.types import subjects
from app.core.improvements.types.garment_fill import _in_flight, _judge

#: The occasions each hair method renders on (spec § 5.3); HairDeck's job
#: runs on the ``hair_mesh`` occasion (``ImageService.generate_hair``).
OCCASIONS: Dict[str, Tuple[str, ...]] = {"edit_chain": ("garment_view", "hair_views_mesh"),
                                         "subtract": ("garment_view", "hair_source_mesh"),
                                         "hairdeck": ("hair_mesh",)}
#: The method as the Hair tab names it.
METHOD_LABEL = {"edit_chain": "hair views", "hairdeck": "HairDeck", "subtract": "subtract"}


def _profile(name: str) -> Dict[str, Any]:
    from app.models.character import get_character_profile
    return get_character_profile(name) or {}


def _subject(name: str, profile: Dict[str, Any]) -> Optional[Tuple[Optional[str], str]]:
    """``(worn hair item id or None, method)`` when the character wants a hair
    mesh — hair text, and no hair item at all or a worn one whose fit is
    ``missing`` — else None. A worn item's in-flight run is judged by the
    caller."""
    from app.core import garment_hair, garments
    if not garment_hair.hair_description(name, profile=profile):
        return None
    method = garment_hair.hair_method(name, profile=profile)
    summary = garments.hair_summary(name, profile=profile)
    if summary is None:
        # No worn hair item: a subject only when it owns none either (an
        # item taken off in the Hair tab stays off).
        return None if garment_hair.find_hair_item(name, profile) is not None else (None, method)
    if summary.get("status") != "missing":
        return None
    item_id = str(summary["item_id"])
    if garments.cached_failure(name, item_id, profile=profile) is not None:
        return None
    return item_id, method


def _estimate(name: str, item_id: Optional[str], method: str, profile: Dict[str, Any]) -> Dict[str, Any]:
    """``run_estimate`` of the worn item; without one, the method's full chain."""
    from app.core import garments
    if item_id:
        return garments.run_estimate(name, item_id, profile=profile)
    costs = garments.HUB_JOBS.get(f"hair:{method}")
    if not costs:
        return {"hub_jobs": None, "note": f"no cost table for hair by {method}"}
    parts = " + ".join(f"{step} {n}" for step, n in costs.items() if n) or "no hub job"
    return {"hub_jobs": sum(costs.values()), "note": f"new hair item: {parts}"}


def _require_routes(method: str, name: str) -> None:
    """Every occasion the method renders on must resolve right now; nothing
    available is load — the step waits."""
    for occasion in OCCASIONS.get(method, ()):
        if not subjects.default_mesh_backend(occasion, name):
            raise CandidateBusy(f"no backend available for {occasion} right now")


class HairFill(ImprovementType):
    id = "hair_fill"
    label = "Generate hair meshes"
    needs_media = True

    @property
    def params_schema(self) -> List[ParamField]:
        return [
            ParamField("character", "Character", "enum",
                       [{"value": "", "label": "All characters"}] +
                       [{"value": n, "label": n} for n in subjects.characters()], required=False),
        ]

    def validate(self, params: Dict[str, Any]) -> Dict[str, Any]:
        out = super().validate(params)
        if out.get("character") and out["character"] not in subjects.characters():
            raise ValueError("Character not found")
        return out

    def _names(self, params: Dict[str, Any]) -> List[str]:
        names = subjects.pipeline_characters()
        if params.get("character"):
            names = [n for n in names if n == params["character"]]
        return names

    def _wanted(self, name: str, profile: Dict[str, Any]) -> Optional[Tuple[Optional[str], str]]:
        subject = _subject(name, profile)
        if subject is None or (subject[0] and _in_flight(name, subject[0])):
            return None
        return subject

    # --- candidates ------------------------------------------------------------

    def find_candidates(self, params: Dict[str, Any]) -> List[Candidate]:
        out: List[Candidate] = []
        for name in self._names(params):
            profile = _profile(name)
            subject = self._wanted(name, profile)
            if subject is None:
                continue
            item_id, method = subject
            est = _estimate(name, item_id, method, profile)
            out.append(Candidate(f"character:{name}", f"{name} · {METHOD_LABEL.get(method, method)}",
                                 hub_jobs=est.get("hub_jobs"), note=str(est.get("note") or "")))
        return sorted(out, key=lambda c: (c.label.lower(), c.key))

    def is_done(self, candidate: Candidate, params: Dict[str, Any]) -> bool:
        name = candidate.key.split(":", 1)[1]
        return name not in self._names(params) or self._wanted(name, _profile(name)) is None

    # --- apply -----------------------------------------------------------------

    def apply(self, candidate: Candidate, params: Dict[str, Any], task_id: str) -> None:
        from app.core import garment_hair, garments
        name = candidate.key.split(":", 1)[1]
        # Made, refused or taken off meanwhile: nothing to spend — the next
        # scan closes the step.
        subject = _subject(name, _profile(name))
        if subject is None:
            return
        item_id, method = subject
        if item_id and _in_flight(name, item_id):
            raise CandidateBusy(f"{name}: a hair run is in flight")
        _require_routes(method, name)
        if not item_id:
            try:
                item_id = garment_hair.ensure_hair_item(name)
            except ValueError as e:
                raise CandidateRefused(f"hair item — {e}") from e
        _judge(garments.run_garment(name, item_id))
