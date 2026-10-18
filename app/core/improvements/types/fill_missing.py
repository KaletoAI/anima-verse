"""Improvement type: generate the assets a subject simply does not have yet.

The counterpart of :mod:`model_replace` — that one replaces what exists, this
one fills the holes.  A subject only counts as a hole when the generation could
actually run: a prop without its product shot and a location without a building
image have nothing to be generated FROM, so they are not candidates at all
instead of failing twice and being skipped.
"""
from typing import Any, Dict, List

from app.core import model3d
from app.core.improvements.base import (Candidate, CandidateBusy,
                                        ImprovementType, ParamField)
from app.core.improvements.types import subjects
from app.imagegen.occasions import mesh_occasion_for_rig

SUBJECTS = [
    {"value": "character_model", "label": "Character models"},
    {"value": "building_model", "label": "Building models"},
    {"value": "prop_model", "label": "Prop models"},
    {"value": "prop_images", "label": "Prop images"},
    {"value": "character_expressions", "label": "Character expressions"},
    {"value": "clothing_images", "label": "Clothing images"},
]


def _require_route(occasion: str, character: str = "") -> None:
    """The occasion's chain must resolve right now; the producer then renders
    ROUTED (backend "") and falls back along the chain on a failure. Nothing
    available is load, not a defect — the step waits.

    With automatic backend selection, each candidate kind names
    its mesh occasion: a character the one of its rig (``mesh_humanoid`` /
    ``mesh_creature``), a building ``mesh_building``, a prop
    ``mesh_object``. ``character`` applies that character's render-target
    override, so a passing check uses the same routing context as the producer."""
    if not subjects.default_mesh_backend(occasion, character):
        raise CandidateBusy(f"no backend available for {occasion} right now")


def _missing_character_models() -> List[Candidate]:
    return [Candidate(f"character:{n}", n) for n in subjects.characters()
            if subjects.character_model(n) is None]


def _missing_buildings() -> List[Candidate]:
    out = []
    for location in subjects.locations():
        loc_id = location.get("id") or ""
        if not loc_id or subjects.building_model(loc_id) is not None:
            continue
        if not subjects.building_source_image(loc_id):
            continue
        out.append(Candidate(f"location:{loc_id}",
                             location.get("name") or loc_id))
    return out


def _missing_prop_models() -> List[Candidate]:
    out = []
    for prop in subjects.props():
        prop_id = prop.get("id") or ""
        if not prop_id or subjects.prop_model(prop_id) is not None:
            continue
        if not subjects.prop_has_source(prop_id):
            continue
        out.append(Candidate(f"prop:{prop_id}", prop.get("name") or prop_id))
    return out


def _missing_prop_images() -> List[Candidate]:
    out = []
    for prop in subjects.props():
        prop_id = prop.get("id") or ""
        if not prop_id:
            continue
        variants = subjects.prop_variants(prop_id)
        name = prop.get("name") or prop_id
        for entry in variants:
            index = int(entry.get("index") or 0)
            ident = subjects.prop_ident(prop_id, index)
            if not subjects.prop_has_source(ident):
                label = name if len(variants) < 2 else f"{name} · variant {index + 1}"
                out.append(Candidate(f"prop:{ident}", label))
    return out


def _missing_expressions() -> List[Candidate]:
    return [Candidate(f"character:{n}", n) for n in subjects.characters()
            if subjects.expression_missing(n)]


def _missing_clothing_images() -> List[Candidate]:
    return [Candidate(f"item:{item['id']}", item.get("name") or item["id"])
            for item in subjects.clothing_items()
            if not subjects.clothing_image_done(item["id"])]


#: subject → (the subjects still missing it, "does it have it now?", generate it)
_HANDLERS: Dict[str, tuple] = {
    "character_model": (
        _missing_character_models,
        lambda ident: subjects.character_model(ident) is not None,
        lambda ident: (_require_route(mesh_occasion_for_rig(model3d.required_rig(ident)),
                                      character=ident),
                       subjects.generate_character_model(ident, "")),
    ),
    "building_model": (
        _missing_buildings,
        lambda ident: subjects.building_model(ident) is not None,
        lambda ident: (_require_route("mesh_building"),
                       subjects.generate_building_model(ident, "")),
    ),
    "prop_model": (
        _missing_prop_models,
        lambda ident: subjects.prop_model(ident) is not None,
        lambda ident: (_require_route("mesh_object"),
                       subjects.generate_prop_model(ident, "")),
    ),
    "prop_images": (_missing_prop_images, subjects.prop_has_source,
                    subjects.generate_prop_image),
    "character_expressions": (
        _missing_expressions,
        lambda ident: not subjects.expression_missing(ident),
        subjects.generate_expression,
    ),
    "clothing_images": (
        _missing_clothing_images,
        subjects.clothing_image_done,
        subjects.generate_clothing_image,
    ),
}


class FillMissing(ImprovementType):
    id = "fill_missing"
    label = "Generate missing assets"

    @property
    def params_schema(self) -> List[ParamField]:
        auto = [{"value": "", "label": "Auto (routing)"}]
        return [
            ParamField("subject", "Subject", "subject_kind", SUBJECTS),
            ParamField("mesh_backend", "Mesh backend", "mesh_backend",
                       auto + subjects.mesh_backend_options(), required=False,
                       show_if={"subject": ["character_model", "building_model", "prop_model"]}),
            ParamField("image_backend", "Image backend", "image_backend",
                       auto + subjects.image_backend_options(), required=False,
                       show_if={"subject": ["prop_images", "clothing_images"]}),
        ]

    def find_candidates(self, params: Dict[str, Any]) -> List[Candidate]:
        find, _has, _generate = _HANDLERS[params["subject"]]
        return sorted(find(), key=lambda c: (c.label.lower(), c.key))

    def is_done(self, candidate: Candidate, params: Dict[str, Any]) -> bool:
        _find, has, _generate = _HANDLERS[params["subject"]]
        return has(candidate.key.split(":", 1)[1])

    def apply(self, candidate: Candidate, params: Dict[str, Any],
              task_id: str) -> None:
        _find, _has, generate = _HANDLERS[params["subject"]]
        ident = candidate.key.split(":", 1)[1]
        subject = params["subject"]
        backend = params.get("mesh_backend", "")
        if subject in ("character_model", "building_model", "prop_model") and backend:
            producer = {"character_model": subjects.generate_character_model,
                        "building_model": subjects.generate_building_model,
                        "prop_model": subjects.generate_prop_model}[subject]
            producer(ident, backend)
        elif subject in ("prop_images", "clothing_images"):
            generate(ident, params.get("image_backend", ""))
        else:
            generate(ident)
