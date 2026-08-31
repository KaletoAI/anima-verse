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
"""
from typing import Any, Dict, List

from app.core.improvements.base import Candidate, ImprovementType, ParamField
from app.core.improvements.types import subjects

#: Separates the character from the outfit signature in a candidate key.  A
#: signature is hex (plus the ``-s`` state fork), so it never contains one —
#: the key is split from the RIGHT, which leaves a character name carrying a
#: colon intact.
KEY_SEP = ":"


def split_key(key: str) -> tuple:
    """``"<character>:<signature>"`` → ``(character, signature)``."""
    name, _sep, signature = str(key or "").rpartition(KEY_SEP)
    return name, signature


def _short_signature(signature: str) -> str:
    """Readable stub of a signature for the candidate label.

    The full key is 12 hex (plus a state fork of 8 more) and a list of them is
    unreadable; eight characters identify one combination well enough to be
    recognised in the step log, and the state fork stays visible — otherwise
    the two entries of one outfit would read identically.
    """
    from app.core.model_refs import STATE_SIG_SEP
    base, sep, state = signature.partition(STATE_SIG_SEP)
    return f"{base[:8]}{STATE_SIG_SEP}{state[:4]}" if sep else base[:8]


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
                           subjects.mesh_backend_options(
                               subjects.CHARACTER_MESH_RIGS))]

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
                    f"{name}{KEY_SEP}{signature}",
                    f"{name} · {_short_signature(signature)}"))
        return sorted(out, key=lambda c: (c.label.lower(), c.key))

    def is_done(self, candidate: Candidate, params: Dict[str, Any]) -> bool:
        name, signature = split_key(candidate.key)
        return subjects.character_model_exists(name, signature)

    def apply(self, candidate: Candidate, params: Dict[str, Any],
              task_id: str) -> None:
        name, signature = split_key(candidate.key)
        if not signature:
            raise RuntimeError(f"{candidate.key}: not an outfit combination")
        try:
            subjects.generate_character_model(name, params["backend"],
                                              signature)
        except RuntimeError as e:
            # The producer's own words ("no_tpose_input") say nothing about
            # WHICH combination failed, and the step log is a list of them.
            raise RuntimeError(f"{candidate.key}: {e}") from e
