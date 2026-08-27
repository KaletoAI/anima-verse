"""Improvement type: render every image a given image backend made again, on
another one.

The 2D counterpart of :mod:`model_replace` — same occasion (a better or cheaper
backend is configured, the world is full of pictures from the old one), same
derivation: nothing is listed anywhere, the candidate set comes out of the
images' own meta on every scan.

The subject of ``character_images`` is the PORTRAIT, not the whole gallery: it
is the one image the world actually shows everywhere, and the expressions are
derived from it — a re-rendered portrait plus a cleared expression cache moves
a character's whole face onto the new backend.  A ``location_gallery``
candidate is a single gallery FILE instead, because a location's images are
independent pictures with their own prompts.
"""
from typing import Any, Dict, List

from app.core.improvements.base import Candidate, ImprovementType, ParamField
from app.core.improvements.types import subjects

SUBJECTS = [
    {"value": "character_images", "label": "Character portraits"},
    {"value": "location_gallery", "label": "Location gallery images"},
]


def _profile_backend(name: str) -> str:
    return str((subjects.character_profile(name) or {}).get("backend") or "")


def _gallery_backend(ident: str) -> str:
    location_id, _sep, filename = ident.partition(":")
    for image in subjects.gallery_images(location_id):
        if image["filename"] == filename:
            return image["backend"]
    return ""


def _rerender_gallery(ident: str, backend: str) -> None:
    location_id, _sep, filename = ident.partition(":")
    subjects.regenerate_gallery_image(location_id, filename, backend)


#: candidate kind → (which backend made it, render it again on another one) —
#: the whole kind-specific part of this type.
_HANDLERS = {
    "character": (_profile_backend, subjects.regenerate_profile),
    "location": (_gallery_backend, _rerender_gallery),
}


class ImageRerender(ImprovementType):
    id = "image_rerender"
    label = "Re-render images by backend"
    params_schema = [
        ParamField("subject", "Subject", "subject_kind", SUBJECTS),
        ParamField("source_backend", "Re-render images made by",
                   "image_backend"),
        ParamField("target_backend", "Render with", "image_backend"),
    ]

    def validate(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """The base contract plus the one rule that makes this type mean
        anything: re-rendering a backend INTO ITSELF would leave every
        candidate instantly done, and a standing entry would render the same
        images for the rest of the world's life."""
        out = super().validate(params)
        if out["source_backend"] == out["target_backend"]:
            raise ValueError("source and target backend must differ")
        return out

    def find_candidates(self, params: Dict[str, Any]) -> List[Candidate]:
        subject = params["subject"]
        source = params["source_backend"]
        out: List[Candidate] = []
        if subject == "character_images":
            for name in subjects.characters():
                profile = subjects.character_profile(name)
                # No prompt, no render: a hand-uploaded portrait has nothing
                # this type could generate FROM.
                if (profile and profile["backend"] == source
                        and profile["prompt"]):
                    out.append(Candidate(f"character:{name}", name))
        else:
            for location in subjects.locations():
                loc_id = location.get("id") or ""
                if not loc_id:
                    continue
                loc_label = location.get("name") or loc_id
                for image in subjects.gallery_images(loc_id):
                    if image["backend"] != source:
                        continue
                    out.append(Candidate(
                        f"location:{loc_id}:{image['filename']}",
                        f"{loc_label} / {image['filename']}"))
        # The contract is "every subject NOT yet done".  `validate` already
        # rules out source == target, but params come back out of the store as
        # stored — an entry written before that rule existed must not hand the
        # engine work that is finished.
        out = [c for c in out if not self.is_done(c, params)]
        return sorted(out, key=lambda c: (c.label.lower(), c.key))

    def is_done(self, candidate: Candidate, params: Dict[str, Any]) -> bool:
        """Whether the subject's CURRENT image was made by the target backend.

        For a character that is the profile image, which the re-render swaps —
        so this flips to True.  For a gallery image it is that very file, and
        a re-render leaves it alone (the new picture is a new file), so it
        stays False; the engine closes such a step because ``apply`` returned,
        not because this said so.
        """
        kind, ident = candidate.key.split(":", 1)
        current_backend, _rerender = _HANDLERS[kind]
        return current_backend(ident) == params["target_backend"]

    def apply(self, candidate: Candidate, params: Dict[str, Any],
              task_id: str) -> None:
        kind, ident = candidate.key.split(":", 1)
        _current_backend, rerender = _HANDLERS[kind]
        rerender(ident, params["target_backend"])
