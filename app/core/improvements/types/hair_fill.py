"""``hair_fill`` — the hair mesh of characters on the base-body pipeline that
have hair text but no hair mesh, made at idle time (spec
docs/superpowers/specs/2026-11-11-improvements-figure-pipeline-design.md § 6.5).

A subject is a character on the pipeline with a ready base whose WORN
hairstyle (``garment_hair.worn_hairstyle``, plan 2026-11-12-unified-worn-pieces
Task 13) is HairDeck hair without an accepted fit on the current base
(``garments.hair_summary`` status ``missing``; a served older fit is ``stale``
— ``fit_refit`` or the chain's own trigger handles it). The mode is the
hairstyle's — read, never set. A character that wears no hairstyle, or one
in the body mesh (mode ``body``), is never a subject: it has no hair mesh to
make.

The cost before start is ``garments.run_estimate`` of the worn hairstyle.

No automatic re-spend: a persisted chain failure of the item's current fsig
(``garments.cached_failure``) excludes it, and a run that ends refused —
HairDeck's ``NO_HAIR_ERROR``, a gate, any non-load failure — raises
``CandidateRefused``. Load (a run queued or in flight, an occasion that
resolves to nothing right now, a chain result ``retry_later``) is busy.
"""
from typing import Any, Dict, List, Optional, Tuple

from app.core.improvements.base import (Candidate, CandidateBusy, ImprovementType,
                                        ParamField)
from app.core.improvements.types import subjects
from app.core.improvements.types.garment_fill import _in_flight, _judge

#: The occasions each hair mode renders on (spec § 5.3); HairDeck's job
#: runs on the ``hair_mesh`` occasion (``ImageService.generate_hair``).
OCCASIONS: Dict[str, Tuple[str, ...]] = {"body": (), "hairdeck": ("hair_mesh",)}


def _profile(name: str) -> Dict[str, Any]:
    from app.models.character import get_character_profile
    return get_character_profile(name) or {}


def _subject(name: str, profile: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    """``(worn hairstyle id, its name)`` when its HairDeck fit is ``missing``,
    else None. Its in-flight run is judged by the caller."""
    from app.core import garment_hair, garments
    item = garment_hair.worn_hairstyle(name, profile)
    if item is None or garment_hair.hairstyle_mode(item) != garment_hair.HAIRDECK_MODE:
        return None  # no hairstyle worn, or its hair is in the body mesh: no hair mesh, no run
    if not garment_hair.hairstyle_description(item):
        return None
    summary = garments.hair_summary(name, profile=profile)
    if summary is None or summary.get("status") != "missing":
        return None
    item_id = str(summary["item_id"])
    if garments.cached_failure(name, item_id, profile=profile) is not None:
        return None
    return item_id, str(item.get("name") or "Hairstyle")


def _require_routes(method: str, name: str) -> None:
    """Every occasion the mode renders on must resolve right now; nothing
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

    def _wanted(self, name: str, profile: Dict[str, Any]) -> Optional[Tuple[str, str]]:
        subject = _subject(name, profile)
        if subject is None or _in_flight(name, subject[0]):
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
            item_id, label = subject
            from app.core import garments
            est = garments.run_estimate(name, item_id, profile=profile)
            out.append(Candidate(f"character:{name}", f"{name} · {label} (HairDeck)",
                                 hub_jobs=est.get("hub_jobs"), note=str(est.get("note") or "")))
        return sorted(out, key=lambda c: (c.label.lower(), c.key))

    def is_done(self, candidate: Candidate, params: Dict[str, Any]) -> bool:
        name = candidate.key.split(":", 1)[1]
        return name not in self._names(params) or self._wanted(name, _profile(name)) is None

    # --- apply -----------------------------------------------------------------

    def apply(self, candidate: Candidate, params: Dict[str, Any], task_id: str) -> None:
        from app.core import garments
        name = candidate.key.split(":", 1)[1]
        # Made, refused or taken off meanwhile: nothing to spend — the next
        # scan closes the step.
        subject = _subject(name, _profile(name))
        if subject is None:
            return
        item_id, _label = subject
        if _in_flight(name, item_id):
            raise CandidateBusy(f"{name}: a hair run is in flight")
        _require_routes("hairdeck", name)
        _judge(garments.run_garment(name, item_id))
