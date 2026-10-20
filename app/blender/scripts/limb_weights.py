"""Repair a normalised model; export only when weights changed."""
import sys
from pathlib import Path

_SCRIPTS_DIR = str(Path(__file__).parent)
sys.path.insert(0, _SCRIPTS_DIR)
import _common
_common.app_root_on_path()
from _limb_weights import repair
sys.path.remove(_SCRIPTS_DIR)

import bpy


def limb_weights(args):
    src = args['inputs']['model']
    _common.reset_scene()
    _common.import_model(src)
    report = repair()
    if not report['vertices']:
        return report, {}
    path = Path(args['out_dir']) / Path(src).name
    bpy.ops.export_scene.gltf(filepath=str(path), export_format='GLB')
    return report, {'model': str(path)}


_common.main(limb_weights)
