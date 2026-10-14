"""Usage: ./.venv/bin/python scripts/smoke_prop_lib_token.py
Two fingerprints in five seconds require one prop walk; invalidation and TTL each add one.
"""
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_tmp = tempfile.TemporaryDirectory()
from app.core import paths
paths.init(Path(_tmp.name))
from app.core import db
db.init_schema()
from app.core import scene_recipe as scene
from app.core import props
clock = [10.0]
original = scene._dir_stat_sig
walks = []
def counted(directory, depth=0):
    if depth == 1:
        walks.append(directory)
    return original(directory, depth)
with patch.object(props, '_props_dir', return_value=Path(_tmp.name) / 'props'), patch.object(scene, '_dir_stat_sig', counted), patch.object(scene.time, 'monotonic', side_effect=lambda: clock[0]):
    scene.invalidate_prop_lib_token()
    scene.scene_fingerprint({}, '')
    scene.scene_fingerprint({}, '')
    assert len(walks) == 1, walks
    scene.invalidate_prop_lib_token()
    scene.scene_fingerprint({}, '')
    assert len(walks) == 2, walks
    clock[0] += 5.01
    scene.scene_fingerprint({}, '')
    assert len(walks) == 3, walks
    props._write_sidecar('rock', {'name': 'Rock'})
    scene.prop_lib_token()
    assert len(walks) == 4, walks
    from app.core.model_store import ModelGallery
    directory = Path(_tmp.name) / 'gallery'
    gallery = ModelGallery(directory, 'model')
    gallery._write_all({})
    scene.prop_lib_token()
    assert len(walks) == 5, walks
    (directory / 'model_1.glb').write_bytes(b'fixture')
    assert gallery.delete('model_1.glb')
    scene.prop_lib_token()
    assert len(walks) == 6, walks
print('smoke_prop_lib_token: OK')
