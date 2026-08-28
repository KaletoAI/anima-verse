"""Improvement type: re-generate every 3D model that a given mesh backend made.

The occasion this exists for: a better (or cheaper) mesh backend is configured,
and the world is full of models from the old one.  The subject is *whatever the
sidecar says made it* — no list is kept anywhere, the candidate set is derived
from the stored models every scan.
"""
from typing import Any, Dict, List

from app.core.improvements.base import Candidate, ImprovementType, ParamField
from app.core.improvements.types import subjects

SUBJECTS = [
    {"value": "character", "label": "Character models"},
    {"value": "location", "label": "Building models"},
    {"value": "prop", "label": "Prop models"},
]

#: subject → (read the active model, generate a new one) — the whole
#: kind-specific part of this type.
_HANDLERS = {
    "character": (subjects.character_model, subjects.generate_character_model),
    "location": (subjects.building_model, subjects.generate_building_model),
    "prop": (subjects.prop_model, subjects.generate_prop_model),
}


class ModelReplace(ImprovementType):
    id = "model_replace"
    label = "Replace 3D models by backend"
    params_schema = [
        ParamField("subject", "Subject", "subject_kind", SUBJECTS),
        ParamField("source_backend", "Replace models made by", "mesh_backend"),
        ParamField("target_backend", "Generate with", "mesh_backend"),
    ]

    def validate(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """The base contract plus the one rule that makes this type mean
        anything: replacing a backend BY ITSELF would leave every candidate
        instantly done, and a standing entry would regenerate the same models
        for the rest of the world's life."""
        out = super().validate(params)
        if out["source_backend"] == out["target_backend"]:
            raise ValueError("source and target backend must differ")
        return out

    def find_candidates(self, params: Dict[str, Any]) -> List[Candidate]:
        subject = params["subject"]
        source = params["source_backend"]
        out: List[Candidate] = []
        if subject == "character":
            for name in subjects.characters():
                model = subjects.character_model(name)
                if model and model.get("backend") == source:
                    out.append(Candidate(f"character:{name}", name))
        elif subject == "location":
            for location in subjects.locations():
                loc_id = location.get("id") or ""
                if not loc_id:
                    continue
                model = subjects.building_model(loc_id)
                if model and model.get("backend") == source:
                    out.append(Candidate(f"location:{loc_id}",
                                         location.get("name") or loc_id))
        else:
            # EVERY MODEL VARIANT, not only the primary one
            # (spec-bild-props-v2.md E5): a prop carries several meshes of the
            # same object, and a variant made by the old backend is exactly as
            # much of a candidate as the first one.
            #
            # THE IDENT ALWAYS STATES THE INDEX, variant 0 included (ruling
            # V8). "The primary variant" is the first EFFECTIVELY ACTIVE one
            # and moves with the season tags, so a candidate that named itself
            # by that would read one variant's mesh and re-mesh another's the
            # moment a season turned. A bare ident is only ever READ (legacy
            # keys), never written here.
            for prop in subjects.props():
                prop_id = prop.get("id") or ""
                if not prop_id:
                    continue
                name = prop.get("name") or prop_id
                variants = subjects.prop_variants(prop_id)
                for entry in variants:
                    index = int(entry.get("index") or 0)
                    ident = subjects.prop_ident(prop_id, index)
                    model = subjects.prop_model(ident)
                    if not (model and model.get("backend") == source):
                        continue
                    # A one-variant prop IS the object — naming its single
                    # version would be noise in a list of a hundred props.
                    label = (name if len(variants) < 2
                             else f"{name} · variant {index + 1}")
                    out.append(Candidate(f"prop:{ident}", label))
        # The contract is "every subject NOT yet done".  `validate` already
        # rules out the case where source and target are the same backend, but
        # params come back out of the store as stored — an entry written before
        # that rule existed must not hand the engine work that is finished.
        out = [c for c in out if not self.is_done(c, params)]
        return sorted(out, key=lambda c: (c.label.lower(), c.key))

    def is_done(self, candidate: Candidate, params: Dict[str, Any]) -> bool:
        kind, ident = candidate.key.split(":", 1)
        read, _generate = _HANDLERS[kind]
        model = read(ident)
        return bool(model) and model.get("backend") == params["target_backend"]

    def apply(self, candidate: Candidate, params: Dict[str, Any],
              task_id: str) -> None:
        kind, ident = candidate.key.split(":", 1)
        _read, generate = _HANDLERS[kind]
        generate(ident, params["target_backend"])
