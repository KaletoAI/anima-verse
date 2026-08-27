"""Improvement type: bake the walkable surface of models that have none yet
(spec-surface-height § 5 no. 3).

The BACKLOG path of the feature.  A model that lands today gets its lattice on
landing and a re-dialled orientation fix re-bakes at once; the stock of
dioramas and props that predate all that gets one here — in idle time, one
Blender slot at a time, so a world full of rooms is not a single hour-long
request.

A candidate is simply "a model file whose surface does not read back": absent,
from another file, or baked under another fix all mean the same thing to
:func:`model_surface.read_surface`, and all three want the same bake.
"""
from pathlib import Path
from typing import Any, Dict, List, Tuple

from app.core.improvements.base import (Candidate, CandidateBusy,
                                        ImprovementType, ParamField)
from app.core.improvements.types import subjects

SUBJECTS = [
    {"value": "room_model", "label": "Room models"},
    {"value": "prop_model", "label": "Prop models"},
]

#: How long one step waits for a free Blender slot — the same wait the landing
#: paths use (``props.bake_surfaces``, ``location_model3d.request_surface``).
#: ``apply`` runs in a TaskQueue worker, so waiting is what it is there for;
#: giving up early would only hand the engine an attempt for pure load.
SLOT_WAIT_S = 300.0


def _room_key(location_id: str, room_id: str) -> str:
    return f"room:{location_id}/{room_id}"


def _prop_key(prop_id: str, variant: int) -> str:
    return f"prop:{prop_id}/{variant}"


#: subject → (the models of that kind, how one of them is keyed)
_HANDLERS: Dict[str, tuple] = {
    "room_model": (subjects.room_models, _room_key),
    "prop_model": (subjects.prop_model_variants, _prop_key),
}


def _index(subject: str) -> Dict[str, Tuple[str, Path, Dict[str, Any]]]:
    """``key → (label, model file, orientation fix)`` for every model of this
    subject kind.

    Read fresh on every call: a scan and the apply that follows it are minutes
    apart, and in between the admin may have selected another model, turned the
    prop or deleted the whole subject.
    """
    rows, key_of = _HANDLERS[subject]
    return {key_of(a, b): (label, path, rotation)
            for a, b, label, path, rotation in rows()}


def _forget(subject: str, key: str) -> None:
    """Drop the walk gate's cached lattices, so the server stands on the fresh
    surface instead of the seconds-old "there is none".

    A room knows where it is — only that location's cache goes.  A prop stands
    in many and does not know in which, so its cache goes wholesale; that is
    the same rule ``props.bake_surfaces`` follows, and one recomposition is
    cheaper than a stale metre.
    """
    from app.core.model_surface import forget_surfaces
    if subject == "room_model":
        forget_surfaces(key.split(":", 1)[1].split("/", 1)[0])
    else:
        forget_surfaces()


class SurfaceBake(ImprovementType):
    id = "surface_bake"
    label = "Bake walkable surfaces"
    params_schema = [ParamField("subject", "Subject", "subject_kind", SUBJECTS)]

    def find_candidates(self, params: Dict[str, Any]) -> List[Candidate]:
        from app.core.model_surface import read_surface
        index = _index(params["subject"])
        return sorted((Candidate(key, label)
                       for key, (label, path, rotation) in index.items()
                       if read_surface(path, rotation) is None),
                      key=lambda c: (c.label.lower(), c.key))

    def is_done(self, candidate: Candidate, params: Dict[str, Any]) -> bool:
        from app.core.model_surface import read_surface
        entry = _index(params["subject"]).get(candidate.key)
        return entry is not None and read_surface(entry[1], entry[2]) is not None

    def apply(self, candidate: Candidate, params: Dict[str, Any],
              task_id: str) -> None:
        from app.core.model_surface import bake_surface_result
        subject = params["subject"]
        entry = _index(subject).get(candidate.key)
        if entry is None:
            raise RuntimeError(f"{candidate.key}: no model to bake")
        _label, path, rotation = entry
        # The bake never raises — it answers a reason. Which one it is decides
        # the step's fate, so the plain Optional is not enough here:
        surface, reason = bake_surface_result(path, rotation,
                                              wait_s=SLOT_WAIT_S)
        if reason == "busy":
            # Every Blender slot was taken for SLOT_WAIT_S — load, not a
            # defect. As a failure this would cost the candidate one of its two
            # attempts, and a subject skipped after two of them is never
            # resurrected: a model would lose its floor for good because the
            # machine happened to be busy twice (spec § 10 — "no free slot"
            # leaves the candidate MISSING). The engine leaves a busy step
            # pending without counting an attempt.
            raise CandidateBusy(f"{candidate.key}: no Blender slot")
        if surface is None:
            # A real defect of this subject or of this installation — no
            # Blender, an unreadable model, a script that gave up. Two of those
            # SHOULD skip the candidate instead of retrying forever.
            raise RuntimeError(f"surface bake {reason}: {candidate.key}")
        _forget(subject, candidate.key)
