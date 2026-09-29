"""Dumps the REST of the reference skeleton for the animation studio.

Invoked through ``app.blender.runner.run("rig_rest", inputs={"rig": …})``.
Writes ``rig_rest.json``: per bone (short name, the ``mixamorig:`` prefix
cut) its parent, head, tail and 3x3 rest rotation — all in ARMATURE space
(Y up, +Z the figure's front, +X the figure's left, centimetres), the space
``cmu_clip`` solves in. Floats go out with full precision, so a pure-Python
forward kinematics on these numbers reproduces Blender's.
"""
import json
import sys
from pathlib import Path

_SCRIPTS_DIR = str(Path(__file__).parent)
sys.path.insert(0, _SCRIPTS_DIR)
import _common                                                # noqa: E402
import cmu_clip                                               # noqa: E402
sys.path.remove(_SCRIPTS_DIR)


def _short(name: str) -> str:
    return name[len(cmu_clip.PREFIX):] if name.startswith(cmu_clip.PREFIX) else name


def run(job):
    arm = cmu_clip._load_rig(job["inputs"]["rig"])
    bones = {}
    for b in arm.data.bones:
        m = b.matrix_local
        bones[_short(b.name)] = {
            "parent": _short(b.parent.name) if b.parent else None,
            "head": [float(v) for v in b.head_local],
            "tail": [float(v) for v in b.tail_local],
            "rot": [[float(m[r][c]) for c in range(3)] for r in range(3)],
        }
    out = Path(job["out_dir"]) / "rig_rest.json"
    out.write_text(json.dumps({"source": "shared/models/rig/reference.fbx",
                               "bones": bones}, indent=1), encoding="utf-8")
    return {"bones": len(bones)}, {"rig_rest": str(out)}


if __name__ == "__main__":
    _common.main(run)
