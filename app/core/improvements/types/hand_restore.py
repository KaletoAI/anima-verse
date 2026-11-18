"""``hand_restore`` — the finger reset (``model3d._auto_hands``) on stored Mixamo models that predate it.

The rigger bends the fingers it is given; the reset puts them back where the mesher had them, per hand only when
its gate finds the result better and nothing worse. New models get it after normalize; this type offers every
stored full model it applies to and has not run on: rig ``mixamo``, an unrigged source kept beside it
(``model3d._unrigged_source``), and no ``hands`` step under the current ``model3d.HANDS_VERSION``
(``model3d.hands_decided``, on the model and on its clean prerig source). CPU only — ``needs_media`` is False.

The run (``model3d.restore_model_hands``) follows the re-run paths of ``repair_model_weights``: the prerig source
first, then a model with applied extension bones is rebuilt from it (bones, covered variant, collision capsules,
distance tier), any other model is reset in place with its collision capsules, measurement and derived distance
tier. What is built against the body's hand geometry follows here: a changed BASE body hands its body change to
the Build (``model3d.after_base_face_change`` — outfit models stale by ``base_model_sha256``, the worn pieces
refit, as after a face correction); a changed OUTFIT body refits its garments (``outfit_bodies.refit_body``) and
asks the Build once (the posture-match precedent, ``outfit_bodies.match_stale_postures``).

A model whose gate refused both hands, or whose rigger left them alone, is DONE for this version: the step is
recorded, the model drops off the list and the entry's step closes as fulfilled — it is never offered again
until ``HANDS_VERSION`` is raised. The key is ``character:<name>:<signature>:<token>``, the token over the
version and the stored model's generation (sidecar ``created_at`` and ``job_id``): a model built anew, or a raised
version, is a new step. A character whose 3D run is in flight is withheld (``base.Listing``).
"""
from typing import Any, Dict, List, Tuple

from app.core.improvements.base import Candidate, CandidateBusy, ImprovementType, Listing, ParamField
from app.core.improvements.types import subjects

#: What a step costs, per model (measured 2026-11-18 on the Anima Divide models: 2-4 s per Blender run).
ESTIMATE = ("CPU only, no hub job — about 2-4 s of Blender per file (prerig source and model); a model with "
            "extension bones is then rebuilt with its distance tier (about 5-60 s); a changed base body hands "
            "its body change to the Build, like a face correction")


def split_key(key: str) -> Tuple[str, str]:
    """``(name, signature)`` of ``character:<name>:<signature>:<token>`` (no part holds ":")."""
    parts = key.removeprefix("character:").split(":")
    return parts[0], parts[1] if len(parts) > 1 else ""


def model_token(meta: Dict[str, Any]) -> str:
    """The key token: the reset's version and the stored model's generation (its sidecar)."""
    from app.core.model3d import HANDS_VERSION
    return subjects.key_token(HANDS_VERSION, meta.get("created_at") or "", meta.get("job_id") or "")


def _due(path) -> bool:
    """The reset applies to the stored full model ``path`` and has not run on it (or its prerig source) under
    the current version."""
    from app.core import model3d
    from app.core.model_store import read_sidecar
    if not path.is_file() or path.suffix.lower() != ".glb":
        return False
    meta = read_sidecar(path)
    if meta.get("rig") != "mixamo" or model3d._unrigged_source(path) is None:
        return False
    prerig = path.parent / "prerig" / path.name
    return not model3d.hands_decided(meta) or (prerig.is_file() and not model3d.hands_decided(read_sidecar(prerig)))


def result_line(name: str, record: Dict[str, Any]) -> str:
    """The step's result: per hand what was done, the gate's reasons in plain words."""
    from app.core.model_overview import hand_lines
    parts = []
    for line in hand_lines(record):
        reasons = f" ({'; '.join(line['reasons'])})" if line["reasons"] else ""
        parts.append(f"{line['label']}: {line['text'].lower()}{reasons}")
    return f"{name}: " + (" · ".join(parts) if parts else "nothing recorded")


class HandRestore(ImprovementType):
    id = "hand_restore"
    label = "Restore the fingers"
    needs_media = False

    @property
    def params_schema(self) -> List[ParamField]:
        return [ParamField("character", "Character", "enum",
                           [{"value": "", "label": "All characters"}] +
                           [{"value": n, "label": n} for n in subjects.characters()], required=False)]

    def validate(self, params: Dict[str, Any]) -> Dict[str, Any]:
        out = super().validate(params)
        if out.get("character") and out["character"] not in subjects.characters():
            raise ValueError("Character not found")
        return out

    def find_candidates(self, params: Dict[str, Any]) -> List[Candidate]:
        return self.list_candidates(params).candidates

    def list_candidates(self, params: Dict[str, Any]) -> Listing:
        """Withheld (``base.Listing``): a character whose 3D run is in flight — its models may change under
        the scan."""
        from app.core import model3d
        from app.core.model_store import read_sidecar
        names = [params["character"]] if params.get("character") else subjects.characters()
        out: List[Candidate] = []
        withheld: List[str] = []
        for name in names:
            with model3d._lock:
                busy = name in model3d._generating
            if busy:
                withheld.append(f"character:{name}")
                continue
            for path in model3d.extension_rebuild_targets(name)[0]:
                if not _due(path):
                    continue
                out.append(Candidate(f"character:{name}:{path.stem}:{model_token(read_sidecar(path))}",
                                     f"{name} · {path.stem[:8]}", hub_jobs=0, note=ESTIMATE))
        return Listing(sorted(out, key=lambda c: (c.label.lower(), c.key)), tuple(withheld))

    def is_done(self, candidate: Candidate, params: Dict[str, Any]) -> bool:
        from app.core.model3d import get_model3d_dir
        name, signature = split_key(candidate.key)
        return not _due(get_model3d_dir(name) / f"{signature}.glb")

    def apply(self, candidate: Candidate, params: Dict[str, Any], task_id: str) -> str:
        from app.core import model3d
        from app.core.base_body import is_base_signature, is_outfit_body_signature
        name, signature = split_key(candidate.key)
        with model3d._lock:
            if name in model3d._generating:
                raise CandidateBusy(f"{name}: model generation already running")
            model3d._generating.add(name, "Finger reset (Improvements)")
        try:
            if self.is_done(candidate, params):
                return f"{name}: already done"
            result = model3d.restore_model_hands(name, signature)
            if not result.get("ok"):
                raise RuntimeError(result.get("error") or "Finger reset failed")
            if result.get("changed") and not result.get("followed_up"):
                if is_base_signature(signature):
                    model3d.after_base_face_change(name, signature)
                elif is_outfit_body_signature(signature):
                    from app.core import figure, figure_build, outfit_bodies
                    outfit_bodies.refit_body(name, signature)
                    figure.invalidate()
                    figure_build.request(name, "body_change")
            return result_line(name, result.get("hands") or {})
        finally:
            with model3d._lock:
                model3d._generating.discard(name)
