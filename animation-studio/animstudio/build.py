"""Source file -> compiled take -> proc_clip -> out/<kind>/ + build.json.

build.json carries the numeric checks (animstudio.checks) of the compiled
source and of the baked clip's measurement; ``ok`` is true only when every
check passed."""
import hashlib
import importlib.util
import json
from dataclasses import asdict
from pathlib import Path
from typing import Optional, Union

import animstudio
from animstudio import StudioError
from animstudio.checks import Check, pair_checks, run_checks
from animstudio.compile import compile_anim, compile_pair, take_document
from animstudio.dsl import Animation, PairAnimation
from animstudio.rig import load_rest


def source_path(kind: str) -> Path:
    return animstudio.ANIMS / f"{kind}.py"


def spec_sha(kind: str) -> str:
    return hashlib.sha256(source_path(kind).read_bytes()).hexdigest()


def load_anim(kind: str) -> Union[Animation, PairAnimation]:
    path = source_path(kind)
    if not path.is_file():
        raise StudioError(f"no source {path}")
    spec = importlib.util.spec_from_file_location(f"anim_{kind.replace('-', '_')}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    anim = getattr(mod, "ANIM", None)
    if not isinstance(anim, (Animation, PairAnimation)):
        raise StudioError(f"{path.name} defines no ANIM = Animation(...) or PairAnimation(...)")
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
    if isinstance(anim, PairAnimation):
        return _build_pair(kind, anim, sha)
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
    measure = json.loads(Path(res["outputs"]["measure"]).read_text(encoding="utf-8"))
    sidecar = json.loads(Path(res["outputs"]["sidecar"]).read_text(encoding="utf-8"))
    checks = run_checks(anim, compiled, measure, sidecar)
    report = {"kind": kind, "spec_sha": sha, "ok": all(c.ok for c in checks),
              "checks": [asdict(c) for c in checks],
              "fbx": res["outputs"][kind], "sidecar": res["outputs"]["sidecar"]}
    (out / "build.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    return report


def _build_pair(kind: str, pair: PairAnimation, sha: str) -> dict:
    """Both roles -> one proc_clip run (``run_takes`` with two takes writes
    ``<kind>__a.fbx`` / ``__b.fbx`` + one sidecar). The solo checks run per
    role on its own measurement (prefixed ``a:`` / ``b:``), the pair checks
    on the compiled bodies in the pair frame."""
    from app.blender import runner
    from app.core import paths
    rest = load_rest()
    cp = compile_pair(pair, rest)
    out = animstudio.OUT / kind
    out.mkdir(parents=True, exist_ok=True)
    inputs = {"rig": paths.get_rig_file()}
    for role in ("a", "b"):
        take = out / f"take_{role}.json"
        take.write_text(json.dumps(take_document(rest, getattr(cp, role), cp.transforms[role])),
                        encoding="utf-8")
        inputs[f"take_{role}"] = take
    source = {"format": "procedural", "author": "animation-studio",
              "spec": f"animation-studio/anims/{kind}.py", "spec_sha": sha}
    res = runner.run("proc_clip", inputs=inputs,
                     params={"kind": kind, "source": source, "anchor_s": pair.anchor_s},
                     out_dir=out, timeout_s=1800)
    if not res["ok"]:
        raise StudioError(f"proc_clip failed: {res['error']}")
    sidecar = json.loads(Path(res["outputs"]["sidecar"]).read_text(encoding="utf-8"))
    checks: list = []
    for role in ("a", "b"):
        measure = json.loads(Path(res["outputs"][f"measure_{role}"]).read_text(encoding="utf-8"))
        for c in run_checks(pair.role_anim(role), getattr(cp, role), measure, sidecar):
            checks.append(Check(f"{role}:{c.name}", c.ok, c.value, c.limit, c.detail))
    checks.extend(pair_checks({r: cp.pair_frames(r) for r in ("a", "b")}))
    report = {"kind": kind, "spec_sha": sha, "pair": True, "ok": all(c.ok for c in checks),
              "checks": [asdict(c) for c in checks],
              "fbx": [res["outputs"][f"{kind}__a"], res["outputs"][f"{kind}__b"]],
              "sidecar": res["outputs"]["sidecar"]}
    (out / "build.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    return report
