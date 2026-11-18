"""Run the pelvis limb-weight repair on humanoid models rigged before it existed.

The key is ``character:<name>:<signature>:<token>``, the token over the stored
model's generation (sidecar ``created_at`` and ``job_id`` — the repair itself
keeps both): a model of the same combination built anew without the repaired
weights is a new reason, a new step, also after the step of the old model was
given up; the step of a model already worked on is not offered again. A key of
the older shape ``character:<name>:<signature>`` still parses (``split_key``).
"""
from typing import Any, Dict, List, Tuple

from app.core.improvements.base import Candidate, CandidateBusy, ImprovementType, ParamField
from app.core.improvements.types import subjects


def split_key(key: str) -> Tuple[str, str]:
    """``(name, signature)`` of ``character:<name>:<signature>[:<token>]`` (no part holds ":")."""
    parts = key.removeprefix('character:').split(':')
    return parts[0], parts[1] if len(parts) > 1 else ''


def model_token(meta: Dict[str, Any]) -> str:
    """The key token: the stored model's generation (its sidecar)."""
    return subjects.key_token(meta.get('created_at') or '', meta.get('job_id') or '')


class RigWeightRepair(ImprovementType):
    id = 'rig_weight_repair'
    label = 'Repair rig weights'

    @property
    def params_schema(self) -> List[ParamField]:
        return [ParamField('character', 'Character', 'enum',
                           [{'value': '', 'label': 'All characters'}] +
                           [{'value': n, 'label': n} for n in subjects.characters()], required=False)]

    def validate(self, params: Dict[str, Any]) -> Dict[str, Any]:
        out = super().validate(params)
        if out.get('character') and out['character'] not in subjects.characters():
            raise ValueError('Character not found')
        return out

    def find_candidates(self, params: Dict[str, Any]) -> List[Candidate]:
        from app.core.model3d import get_model3d_dir
        from app.core.model_store import read_sidecar
        out = []
        names = [params['character']] if params.get('character') else subjects.characters()
        for name in names:
            for signature in subjects.character_model_signatures(name):
                path = get_model3d_dir(name) / f'{signature}.glb'
                if not path.is_file():
                    continue
                meta = read_sidecar(path)
                if meta.get('rig') != 'mixamo':
                    continue
                candidate = Candidate(f'character:{name}:{signature}:{model_token(meta)}',
                                      f'{name} · {signature[:8]}')
                if not self.is_done(candidate, params):
                    out.append(candidate)
        return sorted(out, key=lambda c: (c.label.lower(), c.key))

    def is_done(self, candidate: Candidate, params: Dict[str, Any]) -> bool:
        from app.core.model3d import get_model3d_dir
        from app.core.model_store import read_sidecar
        name, signature = split_key(candidate.key)
        meta = read_sidecar(get_model3d_dir(name) / f'{signature}.glb')
        return 'limb_weights' in ((meta.get('blender') or {}).get('steps') or [])

    def apply(self, candidate: Candidate, params: Dict[str, Any], task_id: str) -> None:
        from app.core import model3d
        name, signature = split_key(candidate.key)
        with model3d._lock:
            if name in model3d._generating:
                raise CandidateBusy(f'{name}: model generation already running')
            model3d._generating.add(name, 'Rig weight repair (Improvements)')
        try:
            if self.is_done(candidate, params):
                return
            result = model3d.repair_model_weights(name, signature)
            if not result.get('ok'):
                raise RuntimeError(result.get('error') or 'Weight repair failed')
        finally:
            with model3d._lock:
                model3d._generating.discard(name)
