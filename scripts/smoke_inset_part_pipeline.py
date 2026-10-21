#!/usr/bin/env python3
"""Hand-derived optional-op isolation: attached + inset + capture yields AIC.

The declared groups deliberately arrive reversed. Expected runner order is A,
I, C; companions belong only to A. A failed I that writes garbage must restore
A before C, hence AC; a failed A still permits IC. With only I failing the
clean source replaces stale model bytes. Each part timeout is 600 seconds. Build 1 metadata must become stale when
the inset builder advances, while attached-only fingerprints stay identical.
"""
from contextlib import ExitStack
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    from app.core import paths
    with tempfile.TemporaryDirectory(prefix='inset-pipeline-') as tmp:
        root = Path(tmp)
        paths.init(root / 'world')
        from app.core import model3d, extension_rig
        from app.blender import refine
        from app.core.rig_contract import BASE_JOINT_NAMES
        from scripts.smoke_extension_rig_p0 import glb
        old_inset = extension_rig.extension_rig_fingerprint([{'id': 'inset', 'op': 'inset_part'}])
        attached_identity = extension_rig.extension_rig_fingerprint([{'id': 'part', 'op': 'attached_part'}])
        with patch.dict(extension_rig.PART_BUILDS, {'inset_part': 1}):
            assert extension_rig.extension_rig_fingerprint([{'id': 'inset', 'op': 'inset_part'}]) != old_inset
            assert extension_rig.extension_rig_fingerprint([{'id': 'part', 'op': 'attached_part'}]) == attached_identity
        clean = glb(['mixamorig:' + name for name in BASE_JOINT_NAMES])
        source = root / 'prerig/model.glb'
        source.parent.mkdir()
        path = root / 'model.glb'
        def group(name, op):
            return dict(id=name, op=op, params={}, chains=[], enabled=True)
        attached = group('part', 'attached_part')
        inset = group('inset', 'inset_part')
        companion = group('pods', 'attached_part_bone')
        capture = group('capture', 'fixture')
        for failed, only_inset, expected in ((None, False, b'AIC'), ('inset_part', False, b'AC'),
                                             ('attached_part', False, b'IC'), ('inset_part', True, b'')):
            groups = [inset] if only_inset else [capture, inset, companion, attached]
            calls = []
            source.write_bytes(clean)
            path.write_bytes(b'stale')
            def run(staged, operation, params, **kwargs):
                calls.append((operation, [g['id'] for g in params['groups']]))
                if operation != 'extension_bones':
                    assert kwargs['timeout_s'] == 600
                if operation == failed:
                    staged.write_bytes(b'garbage')
                    raise RuntimeError('fixture failure')
                staged.write_bytes(staged.read_bytes() + {'attached_part': b'A', 'inset_part': b'I', 'extension_bones': b'C'}[operation])
                return {'applied': True, 'data': {'metrics': {}}}
            with ExitStack() as stack:
                stack.enter_context(patch('app.models.character.get_character_profile', return_value={}))
                stack.enter_context(patch.object(extension_rig, 'rig_groups_for', return_value=groups))
                stack.enter_context(patch.object(extension_rig, 'resolved_extension_groups', return_value=groups))
                stack.enter_context(patch.object(model3d, '_auto_normalize'))
                stack.enter_context(patch.object(model3d, '_validator_for', return_value=lambda blob: {'ok': blob.startswith(clean), 'errors': []}))
                stack.enter_context(patch.object(refine, 'apply_script', side_effect=run))
                meta = {'rig': 'mixamo'}
                result = model3d._auto_extension_rig('fixture', path, meta)
            assert result['ok'] and result['applied'], result
            assert path.read_bytes() == clean + expected
            assert calls == ([('inset_part', ['inset'])] if only_inset else [
                ('attached_part', ['part', 'pods']), ('inset_part', ['inset']), ('extension_bones', ['capture'])]), calls
            for declaration in (inset,) if only_inset else (attached, inset):
                metrics = meta['extension_rig']['metrics'][declaration['id']]
                assert metrics['status'] == ('failed' if declaration['op'] == failed else 'applied')
                if declaration['op'] == failed:
                    assert metrics['reason'] == 'fixture failure'
        print('PASS inset_part pipeline order AIC, independent failure AC/IC, clean fallback, 600s timeout')


if __name__ == '__main__':
    main()
