"""Improvement type: turn every T-pose render that has no mesh yet into one.

The occasion this exists for: a character's outfit changes produce a T-pose
reference render per worn combination (``model_refs/tpose_<signature>``), but a
mesh is only ever made for the combinations something actually asked for.  Over
a long-running world that leaves a pile of finished render inputs whose model
was never generated — exactly the work an idle queue should do.

The counterpart of ``fill_missing``'s "character models", one level finer: that
one asks "does this character have a model AT ALL" and works on the combination
it is wearing right now, this one works on every STORED combination.

The candidate set is the mirror image of what the producer resolves: a
combination is a candidate when ``model_refs/tpose_<sig>`` exists (the one input
``model3d.generate_for_current_outfit`` reads — for humanoids and animals alike,
"tpose_animal" being a use-case style rather than a file kind) and
``model3d/<sig>.<ext>`` does not.  Nothing else can be generated, and nothing
generatable is left out.

The key is ``<character>:<signature>:<token>``, the token over the T-pose
render's file identity (name, size, mtime — ``subjects.file_token``): a
combination whose render was purged and made anew (an outfit piece edit keeps
the ID-based signature) is a new reason, a new step, also after the step of
the old render was given up. A key of the older shape ``<character>:
<signature>`` still parses (``split_key``).
"""
from typing import Any, Dict, List

from app.core.improvements.base import Candidate, ImprovementType, ParamField
from app.core.improvements.types import subjects

#: Separates the parts of a candidate key. None of them contains one: a
#: signature and a token are hex, a character name may not hold ":"
#: (``character_name.validate_character_name``).
KEY_SEP = ":"


def split_key(key: str) -> tuple:
    """``"<character>:<signature>[:<token>]"`` → ``(character, signature)``."""
    parts = str(key or "").split(KEY_SEP)
    return parts[0], parts[1] if len(parts) > 1 else ""


def tpose_token(name: str, signature: str) -> str:
    """The key token: the identity of the T-pose render the mesh is made from."""
    from app.core.model_refs import find_ref_image
    return subjects.file_token(find_ref_image(name, "tpose", signature))


def _short_signature(signature: str) -> str:
    """Readable prefix of a neutral outfit signature for the candidate label."""
    return signature[:8]


class MeshFromTpose(ImprovementType):
    id = "mesh_from_tpose"
    label = "Generate 3D models from T-pose renders"

    @property
    def params_schema(self) -> List[ParamField]:
        """Read fresh on every access, never frozen at import: the mesh
        backends are admin config and are added, renamed and removed while the
        server runs, so a schema built once would offer backends that are gone
        and hide the ones just configured.  ``GET /improvements/types`` and
        ``validate`` both go through this property, so the offered list and the
        accepted list can never drift apart."""
        return [ParamField("backend", "Generate with", "mesh_backend",
                           subjects.mesh_backend_options())]

    def find_candidates(self, params: Dict[str, Any]) -> List[Candidate]:
        """The difference IS the contract's "not yet done" filter: a signature
        that has a mesh is subtracted, which is the same disk question
        :meth:`is_done` asks — so no separate pass over it is needed."""
        out: List[Candidate] = []
        for name in subjects.characters():
            # Two directory reads per character, no stat per combination —
            # a character can carry hundreds of stored combinations.
            missing = (subjects.character_tpose_signatures(name)
                       - subjects.character_model_signatures(name))
            for signature in missing:
                out.append(Candidate(
                    KEY_SEP.join((name, signature, tpose_token(name, signature))),
                    f"{name} · {_short_signature(signature)}"))
        return sorted(out, key=lambda c: (c.label.lower(), c.key))

    def subject_character(self, key: str) -> str:
        return split_key(key)[0]

    def is_done(self, candidate: Candidate, params: Dict[str, Any]) -> bool:
        name, signature = split_key(candidate.key)
        from app.core.model_refs import is_state_fork
        return is_state_fork(signature) or subjects.character_model_exists(name, signature)

    def apply(self, candidate: Candidate, params: Dict[str, Any],
              task_id: str) -> None:
        name, signature = split_key(candidate.key)
        from app.core.model_refs import is_state_fork
        if not signature or is_state_fork(signature):
            raise RuntimeError(f"{name}{KEY_SEP}{signature}: not an outfit combination")
        try:
            subjects.generate_character_model(name, params["backend"],
                                              signature)
        except RuntimeError as e:
            # The producer's own words ("no_tpose_input") say nothing about
            # WHICH combination failed, and the step log is a list of them.
            raise RuntimeError(f"{name}{KEY_SEP}{signature}: {e}") from e
