"""Re-run the face cleanup on humanoid sources cleaned by an older version of it (``face_cleanup.VERSION``).

The cleanup itself is local (CPU); the model is then rebuilt from the cleaned source — a re-rig, or the face
retexture chain when the model carries one — and those are hub jobs, estimated per candidate. A source whose
mesher original is retained is cleaned again from that original (as "Re-apply face cleanup"); one cleaned before
the original was kept (``model3d.MESHER_MISSING``) is cleaned again from its own stored bytes: the smoothing and
pocket step of version 4 runs, the lip colour corrected once already stays."""
from typing import Any, Dict, List

from app.core.improvements.base import Candidate, CandidateBusy, ImprovementType, ParamField
from app.core.improvements.types import subjects


def split_key(key: str) -> tuple:
    name, signature, version = key.removeprefix('character:').rsplit(':', 2)
    return name, signature, version


class FaceCleanupRerun(ImprovementType):
    id = 'face_cleanup_rerun'
    label = 'Re-run face cleanup'

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
        from app.core.model3d import face_cleanup_rerun_state
        out = []
        names = [params['character']] if params.get('character') else subjects.characters()
        for name in names:
            state = face_cleanup_rerun_state(name)
            if state is None:
                continue
            start = 'the stored mesh (no mesher original kept)' if state['from_stored'] else "the mesher's original"
            out.append(Candidate(f"character:{name}:{state['signature']}:{state['version']}",
                                 f"{name} · {state['signature'][:8]}", hub_jobs=len(state['jobs']),
                                 note=f"Cleanup v{state['version']} → current from {start}, then "
                                      + ' → '.join(state['jobs'])))
        return sorted(out, key=lambda c: (c.label.lower(), c.key))

    def is_done(self, candidate: Candidate, params: Dict[str, Any]) -> bool:
        from app.core.model3d import face_cleanup_rerun_state
        name, signature, _version = split_key(candidate.key)
        state = face_cleanup_rerun_state(name)
        return state is None or state['signature'] != signature

    def apply(self, candidate: Candidate, params: Dict[str, Any], task_id: str) -> None:
        from app.core import model3d
        from app.imagegen.base import BackendBusyError
        name, signature, _version = split_key(candidate.key)
        with model3d._lock:
            if name in model3d._generating:
                raise CandidateBusy(f'{name}: model generation already running')
            model3d._generating.add(name, 'Face cleanup (Improvements)')
        try:
            state = model3d.face_cleanup_rerun_state(name)
            if state is None or state['signature'] != signature:
                return
            if state['follow_up'] == 'face_retexture':
                from app.core.face_retexture import blocking_problems, check, runnable
                problems = blocking_problems(check(name, signature)) + runnable(name)['problems']
            else:
                from app.imagegen.routing import chain_candidates
                from app.imagegen.service import get_image_service
                problems = [] if chain_candidates('rig_humanoid', pool=get_image_service().pool) else [
                    {'message': 'No humanoid rig route is configured.'}]
            if problems:
                raise BackendBusyError('; '.join(p['message'] for p in problems))
            result = model3d.run_face_cleanup(name, signature, state['follow_up'],
                                              from_stored=state['from_stored'], track_id=task_id)
            if not result.get('ok'):
                raise RuntimeError(result.get('error') or 'Face cleanup failed')
        finally:
            with model3d._lock:
                model3d._generating.discard(name)
