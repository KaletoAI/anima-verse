"""Fit the collision capsules of humanoid models that have none or an outdated set, and apply changed channels
(declarations, per-character overrides — ``collision.channels_current``; a changed exposure —
``collision.exposure_current``).

A candidate is one stored model, key ``character:<name>:<signature>:<token>``. The token (``wanted_token``) is the
fingerprint of what ``is_done`` compares the stored record against: the record version, the model identity
(``collision.identity``), the character's scales, the extension groups and the wanted ``channels_sig``. A standing
entry therefore offers a model whose set went stale AGAIN (new channels, a rebuilt model) as a new step, while a
model whose step is done and whose inputs did not change is not offered again. A key of the older shape without a
token (``character:<name>:<signature>``) still parses (``split_key``)."""
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from app.core.improvements.base import Candidate, CandidateBusy, ImprovementType, ParamField
from app.core.improvements.types import subjects


def split_key(key: str) -> Tuple[str, str]:
    """``(name, signature)`` of ``character:<name>:<signature>[:<token>]`` (names and signatures hold no ":")."""
    parts = key.removeprefix('character:').split(':')
    return parts[0], parts[1] if len(parts) > 1 else ''


def wanted_token(name: str, path: Path, meta: Dict[str, Any]) -> str:
    """12 hex over the inputs a current record must match (``collision.record_state``): the record version, the
    model identity, the character's scales, the extension groups, the wanted channels' signature and, when any, the
    channels the worn pieces cover now."""
    from app.core import collision, collision_channels
    from app.models.character import get_character_profile
    profile = get_character_profile(name) or {}
    wanted, channels_sig = collision_channels.wanted_channels(name, path, meta, profile=profile)
    inputs = [collision.VERSION, list(collision.identity(path, meta)),
              collision.character_scales(name, profile=profile),
              [entry['group'] for entry in collision.extension_chains(meta)], channels_sig]
    # The channels the worn pieces cover now (``collision.exposure_current``) — only when there are any, so the
    # token of a model without covered channels stays the one it always had.
    exposed = collision_channels.exposure(meta)
    covered = sorted(str(entry['id']) for entry in wanted if not exposed(entry))
    if covered:
        inputs.append(covered)
    return hashlib.sha256(json.dumps(inputs, sort_keys=True).encode('utf-8')).hexdigest()[:12]


class CollisionCapsules(ImprovementType):
    id = 'collision_capsules'
    label = 'Collision capsules'

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
                candidate = Candidate(f'character:{name}:{signature}', f'{name} · {signature[:8]}')
                if self.is_done(candidate, params):
                    continue
                path = get_model3d_dir(name) / f'{signature}.glb'
                token = wanted_token(name, path, read_sidecar(path))
                out.append(Candidate(f'{candidate.key}:{token}', candidate.label))
        return sorted(out, key=lambda c: (c.label.lower(), c.key))

    def is_done(self, candidate: Candidate, params: Dict[str, Any]) -> bool:
        from app.core import collision
        from app.core.model3d import get_model3d_dir
        from app.core.model_store import read_sidecar
        name, signature = split_key(candidate.key)
        path = get_model3d_dir(name) / f'{signature}.glb'
        if not path.is_file():
            return True
        meta = read_sidecar(path)
        if not collision.applies(path, meta):
            return True
        state = collision.record_state(name, path, meta)
        return state['current'] and state['channels_current'] and state['exposure_current']

    def apply(self, candidate: Candidate, params: Dict[str, Any], task_id: str) -> None:
        from app.core import collision, model3d
        name, signature = split_key(candidate.key)
        # Held for the whole fit, like the other model-writing types: no Build or rebuild of the character starts
        # while the capsules are fitted from its model file (``collision.ensure`` takes no guard itself).
        with model3d._lock:
            if name in model3d._generating:
                raise CandidateBusy(f'{name}: model generation already running')
            model3d._generating.add(name, 'Collision capsules (Improvements)')
        try:
            if self.is_done(candidate, params):
                return
            record = collision.ensure(name, signature, apply_channels=True)
            if record is None:
                raise CandidateBusy(f'{name}: model replaced while fitting')
            if record.get('error'):
                raise RuntimeError(record['error'])
        finally:
            with model3d._lock:
                model3d._generating.discard(name)
