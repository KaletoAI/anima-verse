"""Usage: .venv/bin/python scripts/smoke_mesh_part_signature.py

Hand-derived: raw 'base' hashes to 593616de1533; adding the literal token
'|mesh:fixture.slot=on' produces a distinct key. A covering outfit adds no
token. Both recorded variants remain valid independent of today's switch.
Fallback must reject the opposite token even with the same outfit pieces.
"""
import hashlib
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths
with tempfile.TemporaryDirectory() as tmp:
    paths.init(tmp)
    from app.core import model_refs as mr, body_slots as bs, model3d as m3
    from app.core.outfit_cache_gc import _entry_valid, read_manifest
    from app.plugins.registry import BodySlotSpec, MeshPartSpec
    import json
    slot = BodySlotSpec('slot', 'fixture', covered_by=['cover'], mesh_part=MeshPartSpec(
        'switch', 'part', 'flat slot', 'size', {}, {}))
    profile = {'body_slots': {'slot': {'switch': 'on'}}}
    with patch.object(bs, 'slots_for_character', return_value=[slot]), patch('app.models.character.get_character_profile', return_value=profile), patch('app.core.outfit_renderer.is_free_text_wardrobe', return_value=False), patch.object(mr, 'outfit_signature_raw', return_value='base'):
        on = mr.mesh_signature({}, [], 'fixture', mr.mesh_variant('fixture', {}))
        assert mr.mesh_variant('fixture', {}) == '|mesh:fixture.slot=on'
        assert on == hashlib.md5(b'base|mesh:fixture.slot=on').hexdigest()[:12]
        from app.core.expression_regen import _cache_key
        with patch('app.core.expression_regen.resolve_expression_key', return_value='neutral'), patch(
                'app.core.expression_regen._canonical_pose_key', return_value='pose'):
            expression_on = _cache_key('', '', '', {}, [], state_fp='')
            assert expression_on == hashlib.md5(b'neutral:pose:base').hexdigest()[:12]
        profile['body_slots']['slot']['switch'] = 'off'
        off = mr.mesh_signature({}, [], 'fixture', mr.mesh_variant('fixture', {}))
        assert off == '593616de1533' and off != on
        assert mr.outfit_signature({}, [], 'fixture') == off
        with patch('app.core.expression_regen.resolve_expression_key', return_value='neutral'), patch(
                'app.core.expression_regen._canonical_pose_key', return_value='pose'):
            assert _cache_key('', '', '', {}, [], state_fp='') == expression_on
        refs = Path(tmp) / 'model_refs'
        refs.mkdir()
        (refs / (f'pose_{off}-pstate.png')).write_bytes(b'fixture')
        with patch.object(mr, 'current_outfit_state', return_value=({}, [], on)), patch.object(
                mr, 'state_fingerprint', return_value='state'), patch(
                'app.models.character.get_character_dir', return_value=Path(tmp)):
            assert mr.find_ref_image('fixture', 'pose').name == f'pose_{off}-pstate.png'

        profile['body_slots']['slot']['switch'] = 'on'
        assert mr.mesh_signature({'cover': 'item'}, [], 'fixture', mr.mesh_variant('fixture', {'cover': 'item'})) == off
        for sig, variant in ((on, '|mesh:fixture.slot=on'), (off, '')):
            side = Path(tmp) / (sig + '.json')
            side.write_text(json.dumps(dict(pieces={}, items=[], mesh_variant=variant)))
            assert _entry_valid(sig, read_manifest(side), set(), lambda: set(), 'fixture')
        directory = Path(tmp) / 'models'
        directory.mkdir()
        (directory / (off + '.glb')).write_bytes(b'fixture')
        with patch.object(m3, 'current_outfit_state', return_value=({}, [], on)), patch.object(m3, 'get_model3d_dir', return_value=directory), patch.object(m3, '_stored_manifest', return_value=dict(pieces={}, items=[], mesh_variant='')):
            assert m3.find_model3d_serving('fixture') == (None, '')
# The rig step rebuilds the model sidecar from a key list of the unrigged one; the
# variant must be on that list or a generated model reaches the GC without it and is
# judged stale (found on a real run: unrigged sidecar had it, the model had not).
import ast, inspect
tree = ast.parse(inspect.getsource(m3))
carried = [node for node in ast.walk(tree) if isinstance(node, ast.Tuple)
           and {"pieces", "items", "source_image"} <= {getattr(e, "value", None) for e in node.elts}]
assert carried and all("mesh_variant" in {getattr(e, "value", None) for e in node.elts} for node in carried), carried
print('PASS mesh_part signature: distinct exposed, same covered, GC both, fallback isolated, rig keeps the variant')
