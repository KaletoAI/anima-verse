"""Source file -> compiled take -> proc_clip -> out/<kind>/ + build.json."""
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Optional

import animstudio
from animstudio import StudioError
from animstudio.compile import compile_anim, take_document
from animstudio.dsl import Animation
from animstudio.rig import load_rest


def source_path(kind: str) -> Path:
    return animstudio.ANIMS / f"{kind}.py"


def spec_sha(kind: str) -> str:
    return hashlib.sha256(source_path(kind).read_bytes()).hexdigest()


def load_anim(kind: str) -> Animation:
    path = source_path(kind)
    if not path.is_file():
        raise StudioError(f"no source {path}")
    spec = importlib.util.spec_from_file_location(f"anim_{kind.replace('-', '_')}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    anim = getattr(mod, "ANIM", None)
    if not isinstance(anim, Animation):
        raise StudioError(f"{path.name} defines no ANIM = Animation(...)")
    if anim.kind != kind:
        raise StudioError(f"ANIM.kind {anim.kind!r} != file name {kind!r}")
    return anim


def build(kind: str, *, anim: Optional[Animation] = None) -> dict:
    """Compiles and bakes one animation. ``anim`` bypasses the source file
    (smokes); a real build always reads anims/<kind>.py."""
    from app.blender import runner
    from app.core import paths
    if anim is None:
        anim = load_anim(kind)
        sha = spec_sha(kind)
    else:
        sha = ""
    compiled = compile_anim(anim, load_rest())
    out = animstudio.OUT / kind
    out.mkdir(parents=True, exist_ok=True)
    take = out / "take.json"
    take.write_text(json.dumps(take_document(load_rest(), compiled)), encoding="utf-8")
    source = {"format": "procedural", "author": "animation-studio",
              "spec": f"animation-studio/anims/{kind}.py", "spec_sha": sha}
    res = runner.run("proc_clip", inputs={"take": take, "rig": paths.get_rig_file()},
                     params={"kind": kind, "source": source}, out_dir=out, timeout_s=900)
    if not res["ok"]:
        raise StudioError(f"proc_clip failed: {res['error']}")
    report = {"kind": kind, "spec_sha": sha, "ok": True, "checks": [],
              "fbx": res["outputs"][kind], "sidecar": res["outputs"]["sidecar"]}
    (out / "build.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    return report
