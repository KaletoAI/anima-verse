#!/usr/bin/env python3
"""(Re)generates animation-studio/rig_rest.json from the reference rig.

Usage: ./.venv/bin/python scripts/make_rig_rest.py

Run it whenever shared/models/rig/reference.fbx changes — a new reference
means reconverting the clip library anyway (rig README). Needs Blender.
No world: storage is a throwaway directory.
"""
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core import paths                                   # noqa: E402
paths.init(tempfile.mkdtemp(prefix="rig-rest-world-"))

from app.blender import runner                               # noqa: E402


def main() -> int:
    out = Path(tempfile.mkdtemp(prefix="rig-rest-out-"))
    res = runner.run("rig_rest", inputs={"rig": paths.get_rig_file()},
                     out_dir=out, timeout_s=300)
    if not res["ok"]:
        print("FAIL:", res["error"])
        return 1
    dst = ROOT / "animation-studio" / "rig_rest.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(res["outputs"]["rig_rest"], dst)
    print(f"OK {res['data']['bones']} bones -> {dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
