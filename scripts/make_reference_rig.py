#!/usr/bin/env python3
"""(Re)builds the retarget REFERENCE SKELETON — `shared/models/rig/reference.fbx`.

Takes any FBX carrying the project's `mixamorig:` armature (a library clip, a
rigged character export), throws everything but the armature away and writes
the result to the rig folder. That file is what every clip conversion is
retargeted onto (`app/core/cmu_import.py:default_rig()`), which is why it lives
outside the clip library: the library may be emptied, replaced or deleted
without taking the importer's reference with it.

Runs Blender headlessly (`app/blender/scripts/rig_export.py`); nothing else is
needed and no world has to exist.

Usage:
    ./.venv/bin/python scripts/make_reference_rig.py [<source.fbx>] [--out <file>]

    # the default source: the library's idle clip
    ./.venv/bin/python scripts/make_reference_rig.py shared/models/clips/idle.fbx
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.blender import runner  # noqa: E402
from app.core import paths  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("source", nargs="?", default="",
                    help="FBX with the mixamorig armature "
                         "(default: the library's idle.fbx)")
    ap.add_argument("--out", default="",
                    help=f"target file (default: {paths.get_rig_file()})")
    a = ap.parse_args()

    src = Path(a.source) if a.source else paths.get_animation_clips_dir() / "idle.fbx"
    out = Path(a.out) if a.out else paths.get_rig_file()
    if not src.is_file():
        print(f"FAILED: no source FBX at {src}")
        return 1

    st = runner.status()
    if not st["executable"]:
        print("FAILED: no Blender executable found "
              "(image_generation.blender_executable)")
        return 1
    print(f"exporting the armature of {src} with Blender {st['version']}")

    out.parent.mkdir(parents=True, exist_ok=True)
    res = runner.run("rig_export", inputs={"src": src},
                     params={"name": out.stem}, out_dir=out.parent,
                     timeout_s=300)
    if not res["ok"]:
        print(f"FAILED: {res['error']}")
        return 1
    written = Path(res["outputs"]["rig"])
    if written != out:
        shutil.move(str(written), str(out))
    data = dict(res["data"])
    names = data.pop("names", [])
    print(json.dumps(data, indent=1))
    print(f"  wrote {out} ({out.stat().st_size} bytes, {len(names)} bones)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
