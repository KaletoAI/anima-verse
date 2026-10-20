"""Run the pelvis limb-weight repair on humanoid models rigged before it existed."""
from typing import Any, Dict, List

from app.core.improvements.base import Candidate, CandidateBusy, ImprovementType, ParamField
from app.core.improvements.types import subjects


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
                if not path.is_file() or read_sidecar(path).get('rig') != 'mixamo':
                    continue
                candidate = Candidate(f'character:{name}:{signature}', f'{name} · {signature[:8]}')
                if not self.is_done(candidate, params):
                    out.append(candidate)
        return sorted(out, key=lambda c: (c.label.lower(), c.key))

    def is_done(self, candidate: Candidate, params: Dict[str, Any]) -> bool:
        from app.core.model3d import get_model3d_dir
        from app.core.model_store import read_sidecar
        name, signature = candidate.key.removeprefix('character:').rsplit(':', 1)
        meta = read_sidecar(get_model3d_dir(name) / f'{signature}.glb')
        return 'limb_weights' in ((meta.get('blender') or {}).get('steps') or [])

    def apply(self, candidate: Candidate, params: Dict[str, Any], task_id: str) -> None:
        from app.core import model3d
        name, signature = candidate.key.removeprefix('character:').rsplit(':', 1)
        with model3d._lock:
            if name in model3d._generating:
                raise CandidateBusy(f'{name}: model generation already running')
            model3d._generating.add(name)
        try:
            if self.is_done(candidate, params):
                return
            result = model3d.repair_model_weights(name, signature)
            if not result.get('ok'):
                raise RuntimeError(result.get('error') or 'Weight repair failed')
        finally:
            with model3d._lock:
                model3d._generating.discard(name)
