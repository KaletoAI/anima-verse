"""Improvement type: re-render the images a FALLBACK backend made.

A routed render that could not run on its occasion chain's intended entry is
marked in its image meta (``fallback_from = {occasion, intended_spec,
position}``, plan-image-routing.md § 4). This type lists those images on every
scan — straight from the metas, nothing is stored — and re-renders each one
EXPLICITLY on the backend the intended spec resolves to right now (no further
fallback, so the replacement carries no marker).

While the intended spec resolves to nothing (still cooling down, offline),
``apply`` raises ``CandidateBusy``: the step stays pending and is tried again
on a later tick. Done = a replacement exists (``source_file`` = the
candidate) without a marker; for a portrait: the current profile image has no
marker.
"""
from typing import Any, Dict, List, Optional

from app.core.improvements.base import (Candidate, CandidateBusy,
                                        ImprovementType, ParamField)
from app.core.improvements.types import subjects

SUBJECTS = [
    {"value": "character_images", "label": "Character portraits"},
    {"value": "character_gallery", "label": "Character gallery"},
    {"value": "location_gallery", "label": "Location gallery images"},
]


def _occasion_options() -> List[Dict[str, str]]:
    from app.imagegen.occasions import catalog_payload
    return [{"value": o["id"], "label": o["label"]}
            for o in catalog_payload() if o["media"] == "image"]


def _wanted(marker: Optional[Dict[str, Any]], occasion: str) -> bool:
    if not marker:
        return False
    return not occasion or marker.get("occasion") == occasion


class FallbackRerender(ImprovementType):
    id = "fallback_rerender"
    label = "Re-render fallback images"

    @property
    def params_schema(self) -> List[ParamField]:
        return [ParamField("subject", "Subject", "subject_kind", SUBJECTS),
                ParamField("occasion", "Only this occasion", "enum",
                           _occasion_options(), required=False)]

    # ── candidates ────────────────────────────────────────────────────
    def find_candidates(self, params: Dict[str, Any]) -> List[Candidate]:
        subject, occasion = params["subject"], params.get("occasion", "")
        out: List[Candidate] = []
        if subject == "character_images":
            for name in subjects.characters():
                prof = subjects.character_profile(name) or {}
                if prof.get("prompt") and _wanted(prof.get("fallback_from"), occasion):
                    out.append(Candidate(f"character:{name}", name))
        elif subject == "character_gallery":
            for name in subjects.characters():
                for img in subjects.character_gallery_images(name):
                    if _wanted(img["fallback_from"], occasion):
                        out.append(Candidate(f"gallery:{name}:{img['filename']}",
                                             f"{name} / {img['filename']}"))
        else:
            for loc in subjects.locations():
                loc_id = loc.get("id") or ""
                if not loc_id:
                    continue
                for img in subjects.gallery_images(loc_id):
                    if _wanted(img["fallback_from"], occasion):
                        out.append(Candidate(f"location:{loc_id}:{img['filename']}",
                                             f"{loc.get('name') or loc_id} / {img['filename']}"))
        out = [c for c in out if not self.is_done(c, params)]
        return sorted(out, key=lambda c: (c.label.lower(), c.key))

    def is_done(self, candidate: Candidate, params: Dict[str, Any]) -> bool:
        kind, ident = candidate.key.split(":", 1)
        if kind == "character":
            return not (subjects.character_profile(ident) or {}).get("fallback_from")
        if kind == "gallery":
            name, filename = ident.split(":", 1)
            # The replacement may be the current PORTRAIT, which the gallery
            # listing leaves out: a re-rendered portrait turns the old one
            # (still marked) into a gallery image whose replacement already
            # exists.
            prof = subjects.character_profile(name) or {}
            if prof.get("source_file") == filename and not prof.get("fallback_from"):
                return True
            return any(g["source_file"] == filename and not g["fallback_from"]
                       for g in subjects.character_gallery_images(name))
        loc_id, filename = ident.split(":", 1)
        return any(g["source_file"] == filename and not g["fallback_from"]
                   for g in subjects.gallery_images(loc_id))

    # ── work ──────────────────────────────────────────────────────────
    def _marker(self, kind: str, ident: str) -> Dict[str, Any]:
        if kind == "character":
            return (subjects.character_profile(ident) or {}).get("fallback_from") or {}
        if kind == "gallery":
            name, filename = ident.split(":", 1)
            row = next((g for g in subjects.character_gallery_images(name)
                        if g["filename"] == filename), None)
            return (row or {}).get("fallback_from") or {}
        loc_id, filename = ident.split(":", 1)
        row = next((g for g in subjects.gallery_images(loc_id)
                    if g["filename"] == filename), None)
        return (row or {}).get("fallback_from") or {}

    def apply(self, candidate: Candidate, params: Dict[str, Any], task_id: str) -> None:
        from app.imagegen.routing import STATUS_TEXT, resolve_spec
        from app.imagegen.service import render_has_reference_image
        kind, ident = candidate.key.split(":", 1)
        marker = self._marker(kind, ident)
        if not marker:
            return          # no marker any more — nothing to do (done on the next scan)
        spec = str(marker.get("intended_spec") or "").strip()
        occasion = str(marker.get("occasion") or "").strip()
        if not spec or not occasion:
            # A marker without its intended entry is a defect of the image's
            # bookkeeping, not load — waiting would keep the step pending forever.
            raise RuntimeError(f"fallback marker without occasion/intended spec: {marker!r}")
        character = ident if kind == "character" else (
            ident.split(":", 1)[0] if kind == "gallery" else "")
        # Resolve BEFORE the producer: "not available yet" must reach the engine
        # as CandidateBusy (step stays pending), never as a failed attempt.
        # has_ref as the routed character render computed it, so a glob over
        # txt2img + img2img backends prefers the same kind.
        status, backend = resolve_spec(occasion, spec, character=character,
                                       has_ref=render_has_reference_image(character))
        if backend is None:
            raise CandidateBusy(
                f"{spec} for {occasion} is not available "
                f"({STATUS_TEXT.get(status, status)})")
        if kind == "character":
            subjects.regenerate_profile(ident, backend.name)
        elif kind == "gallery":
            name, filename = ident.split(":", 1)
            subjects.regenerate_character_gallery_image(name, filename, backend.name)
        else:
            loc_id, filename = ident.split(":", 1)
            subjects.regenerate_gallery_image(loc_id, filename, backend.name)
