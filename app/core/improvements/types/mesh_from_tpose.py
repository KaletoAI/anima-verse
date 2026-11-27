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
``model3d.generate_for_current_outfit`` reads for this path — "tpose_animal"
being a use-case style rather than a file kind) and ``model3d/<sig>.<ext>`` does
not — for a character OFF the base-body pipeline only.

A character ON the pipeline (``base_body.is_base_pipeline``: every humanoid
since Ruling A13, a temporary NPC excepted) never takes this path:
``model3d`` builds its outfit model through ``base_body.build_outfit_model``
after ``prepare_outfit_figure``, ignores the backend this type was given, and
that work belongs to the character's Figure Build — the one action that spends
jobs on a figure. For such a character ``tpose_<sig>`` is the dressed view of a
combination, not an input waiting for a mesh. So the type never lists one, and
a step stored for one before the rule changed is WRONG (``invalid_reason``):
the engine drops it instead of running it (``engine.remove_invalid``).

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

#: Seconds one character's judgement may take in ``release_invalid`` before it is abandoned (nothing deleted).
COLLECT_BUDGET_S = 60.0


def split_key(key: str) -> tuple:
    """``"<character>:<signature>[:<token>]"`` → ``(character, signature)``."""
    parts = str(key or "").split(KEY_SEP)
    return parts[0], parts[1] if len(parts) > 1 else ""


def tpose_token(name: str, signature: str) -> str:
    """The key token: the identity of the T-pose render the mesh is made from."""
    from app.core.model_refs import find_ref_image
    return subjects.file_token(find_ref_image(name, "tpose", signature))


#: ``invalid_reason`` of a step whose character is on the base-body pipeline.
FIGURE_BUILD = "Humanoids get their outfit models from the Figure Build"
#: ``invalid_reason`` of a key that names no outfit combination (a retired state fork, no signature).
NOT_A_COMBINATION = "Not an outfit combination"


def _on_figure_pipeline(name: str) -> bool:
    from app.core import base_body
    return base_body.is_base_pipeline(name)


def _short_signature(signature: str) -> str:
    """Readable prefix of a neutral outfit signature for the candidate label."""
    return signature[:8]


class MeshFromTpose(ImprovementType):
    id = "mesh_from_tpose"
    label = "Generate 3D models from T-pose renders"
    description = ("For characters off the base-body pipeline, such as animals. "
                   "Humanoids get their outfit models from the Figure Build.")

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
            if _on_figure_pipeline(name):
                continue
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

    def invalid_reason(self, key: str, params: Dict[str, Any]) -> str:
        name, signature = split_key(key)
        from app.core.model_refs import is_state_fork
        if not signature or is_state_fork(signature):
            return NOT_A_COMBINATION
        return FIGURE_BUILD if _on_figure_pipeline(name) else ""

    def release_invalid(self, keys: List[str], params: Dict[str, Any], *,
                        explicit: bool, dry_run: bool) -> Dict[str, Any]:
        """A wrong step's own files are the T-pose renders of its combination — but only when nothing else
        reaches them. The artefact graph's judge decides that (``artefact_graph.collect`` over exactly
        these signatures): a combination the character can still wear (``producible outfit``) or wears
        keeps its renders, because they are the dressed views the Figure Build reads; an unreachable one
        goes, with the GC's own locks and its containment under the character directory. A pass the
        judge could not finish (over budget, work in progress unreadable) deletes nothing."""
        from app.core import artefact_graph
        from app.core.paths import get_storage_dir
        from app.models.character import get_character_dir
        storage = get_storage_dir().resolve()
        by_name: Dict[str, List[str]] = {}
        for key in keys:
            name, signature = split_key(key)
            if name and signature and signature not in by_name.setdefault(name, []):
                by_name[name].append(signature)
        out: Dict[str, Any] = {"files": 0, "bytes": 0, "kept": []}
        for name, signatures in sorted(by_name.items()):
            root = get_character_dir(name).resolve()
            if not root.is_relative_to(storage) or root == storage:
                out["kept"] += [{"key": f"{name}{KEY_SEP}{s}", "why": "outside the world"} for s in signatures]
                continue
            report = artefact_graph.collect(name, dry_run=dry_run, explicit=explicit, automatic=not explicit,
                                            keys=signatures, reason="invalid improvement steps",
                                            budget_s=COLLECT_BUDGET_S)
            if report.get("aborted"):
                out["kept"] += [{"key": f"{name}{KEY_SEP}{s}", "why": report["aborted"]} for s in signatures]
                continue
            orphans = list(report.get("orphans") or [])
            orphan_keys = {e["key"] for e in orphans}
            skipped = {e["key"]: e["why"] for e in report.get("skipped") or []}
            for signature in signatures:
                if signature not in orphan_keys:
                    out["kept"].append({"key": f"{name}{KEY_SEP}{signature}", "why": "still reached"})
                elif signature in skipped:
                    out["kept"].append({"key": f"{name}{KEY_SEP}{signature}", "why": skipped[signature]})
            if dry_run:
                gone = [e for e in orphans if e["key"] not in skipped]
                out["files"] += sum(int(e["files"]) for e in gone)
                out["bytes"] += sum(int(e["bytes"]) for e in gone)
            else:
                out["files"] += int(report.get("deleted_files") or 0)
                out["bytes"] += int(report.get("freed_bytes") or 0)
        return out

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
