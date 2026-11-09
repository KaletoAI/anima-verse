#!/usr/bin/env python3
"""Smoke: the per-character collision-capsule region scales — stored, recomputed, nothing else touched
(``POST /characters/{c}/model3d/collision/scales``, ``model3d.set_model3d_options`` key ``collision_scales``,
``collision.recompute_character``).

Usage:
    ./.venv/bin/python scripts/smoke_collision_scales_route.py

Runs without the server, against a temp storage dir (``paths.init`` before any world-DB import); the route's
blocking body ``_set_character_collision_scales_sync`` is called directly, its admin gate is checked on the
registered route. No world DB of a real world, no Blender.

FIXTURE — character ``demo`` with three stored full models (the synthetic body of
``scripts/smoke_collision_capsules.py``: leg rings r 0.06 → leg capsule 0.066, arm rings 0.04 → 0.046):
  base00000001.glb   the base body (own model), sidecar {rig mixamo};
  aaaaaaaaaaaa.glb   an outfit on the base-body pipeline, sidecar {rig mixamo, source base_body,
                     base_signature base00000001, base_model_sha256 = sha of the base file, mesh_backend "x"},
                     carrying the base's record at the default scales;
  cccccccccccc.glb   a generic-rig model (gets no capsules).
plus 2D files (images/portrait.png, model3d/refs/tpose.png). ``model3d._current_base`` is pinned to
(base00000001, sha of the base) — the character is on the base-body pipeline.

Expected, derived by hand:
[1] Save {"scales": {"leg": 1.2}}:
    options.collision_scales = {leg 1.2, arm 1.0, torso 1.0, head 1.0}; the profile stores the deviation only,
    model3d_opts.collision_scales = {"leg": 1.2}; the other profile keys are unchanged.
    models: base00000001 FIRST (it owns the set), then aaaaaaaaaaaa, cccccccccccc (none).
    Base record: source own, scales.leg 1.2, left_thigh r = 0.066 × 1.2 = 0.0792, left_upper_arm 0.046.
    Outfit record: source base, sha256 = the base's sha, base_signature base00000001, left_thigh 0.0792 —
    the inherited set follows the override (refitted, 2 fits in all: base + outfit).
    Generic: {"ok": True, "count": 0, "none": True}, its sidecar has no collision key.
    2D untouched: every file under the character dir except the two humanoid sidecars has the same sha256
    as before (GLBs, renders, the generic sidecar); the humanoid sidecars differ only in the key ``collision``.
[2] The same save again → 0 fits (every record current), answer unchanged.
[3] Save {"scales": {}} → profile without collision_scales, base left_thigh back to 0.066.
[4] Refused (400) and nothing stored: {"scales": {"leg": 1.6}}, {"scales": {"tail": 1.0}}, {"scales": {"arm": "x"}},
    {} and {"scales": {}, "x": 1}; unknown character → 404.
[5] The route is registered with ``require_admin`` as a dependency.
"""
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok ' if ok else 'FAIL'} {label}" + ("" if ok else f"\n       got:  {got!r}\n       want: {want!r}"))
    if not ok:
        FAILS.append(label)


def near(label, got, want, tol=0.0004):
    ok = got is not None and abs(got - want) <= tol
    print(f"  {'ok ' if ok else 'FAIL'} {label}: {got} ≈ {want} (±{tol})")
    if not ok:
        FAILS.append(label)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def radius(path: Path, cid: str):
    record = json.loads(path.with_suffix(".json").read_text()).get("collision") or {}
    return next((c["r"] for c in record.get("capsules") or [] if c["id"] == cid), None)


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="smoke_collision_scales_"))
    os.environ["STORAGE_DIR"] = str(tmp / "world")
    os.environ["INSTANCE_DIR"] = str(tmp / "instance")
    os.environ["ANIMATION_CLIPS_DIR"] = str(tmp / "clips")
    os.environ["ANIMATION_RIG_FILE"] = str(tmp / "reference.fbx")
    from app.core import paths
    paths.init(str(tmp / "world"))
    paths.init_instance(tmp / "instance")
    from fastapi import HTTPException

    from app.core import collision, db, model3d
    from app.core.keyed_lock import keyed_lock
    from app.models.character import get_character_dir, get_character_profile, save_character_profile
    from app.routes import characters as routes

    spec = importlib.util.spec_from_file_location("smoke_collision_capsules", ROOT / "scripts/smoke_collision_capsules.py")
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    body = fixture.make_body()

    db.init_schema()
    char_dir = get_character_dir("demo")
    char_dir.mkdir(parents=True, exist_ok=True)
    with keyed_lock("character_profile", "demo"):
        assert save_character_profile("demo", {"name": "demo", "height": 170,
                                               "model3d_opts": {"auto_generate": True}})
    d = model3d.get_model3d_dir("demo")
    d.mkdir(parents=True, exist_ok=True)
    base = d / "base00000001.glb"
    base.write_bytes(body)
    base.with_suffix(".json").write_text(json.dumps({"rig": "mixamo"}))
    base_sha = sha(base)
    outfit = d / "aaaaaaaaaaaa.glb"
    outfit.write_bytes(body)
    base_record = {**collision.fit_capsules(body), "source": "own", "sha256": base_sha, "computed_at": "t"}
    outfit.with_suffix(".json").write_text(json.dumps({
        "rig": "mixamo", "source": "base_body", "base_signature": "base00000001", "base_model_sha256": base_sha,
        "mesh_backend": "x", "collision": base_record}))
    generic = d / "cccccccccccc.glb"
    generic.write_bytes(body)
    generic.with_suffix(".json").write_text(json.dumps({"rig": "generic"}))
    (char_dir / "images").mkdir(exist_ok=True)
    (char_dir / "images" / "portrait.png").write_bytes(b"\x89PNG portrait")
    (d / "refs").mkdir(exist_ok=True)
    (d / "refs" / "tpose.png").write_bytes(b"\x89PNG tpose")
    model3d._current_base = lambda name: ("base00000001", base_sha)

    sidecars = {base.with_suffix(".json"), outfit.with_suffix(".json")}

    def snapshot():
        return {str(p.relative_to(char_dir)): sha(p) for p in sorted(char_dir.rglob("*"))
                if p.is_file() and p not in sidecars and "profile" not in p.name}

    def sidecar_rest(path):
        return {k: v for k, v in json.loads(path.with_suffix(".json").read_text()).items() if k != "collision"}

    files_before = snapshot()
    rest_before = {p.name: sidecar_rest(p) for p in (base, outfit)}
    profile_before = get_character_profile("demo")

    fits = []
    real_fit = collision.fit_capsules

    def counting_fit(data, *, scales=None):
        fits.append(scales)
        return real_fit(data, scales=scales)

    collision.fit_capsules = counting_fit

    print("[1] save leg 1.2")
    out = routes._set_character_collision_scales_sync("demo", {"scales": {"leg": 1.2}})
    check("options: all four regions", out["options"]["collision_scales"],
          {"leg": 1.2, "arm": 1.0, "torso": 1.0, "head": 1.0})
    profile = get_character_profile("demo")
    check("profile stores the deviation only", profile["model3d_opts"].get("collision_scales"), {"leg": 1.2})
    check("other model options kept", profile["model3d_opts"].get("auto_generate"), True)
    check("other profile keys unchanged",
          {k: v for k, v in profile.items() if k != "model3d_opts"},
          {k: v for k, v in profile_before.items() if k != "model3d_opts"})
    check("models: base first", list(out["models"]), ["base00000001", "aaaaaaaaaaaa", "cccccccccccc"])
    base_rec = json.loads(base.with_suffix(".json").read_text())["collision"]
    check("base record", (base_rec["source"], base_rec["scales"]["leg"]), ("own", 1.2))
    near("base left_thigh", radius(base, "left_thigh"), 0.0792)
    near("base left_upper_arm", radius(base, "left_upper_arm"), 0.046)
    outfit_rec = json.loads(outfit.with_suffix(".json").read_text())["collision"]
    check("outfit record follows the base identity",
          (outfit_rec["source"], outfit_rec["sha256"], outfit_rec["base_signature"], outfit_rec["scales"]["leg"]),
          ("base", base_sha, "base00000001", 1.2))
    near("outfit left_thigh", radius(outfit, "left_thigh"), 0.0792)
    check("two fits (base + outfit)", len(fits), 2)
    check("generic: none", out["models"]["cccccccccccc"], {"ok": True, "count": 0, "none": True})
    check("generic: no collision key", "collision" in json.loads(generic.with_suffix(".json").read_text()), False)
    check("answer per humanoid model", (out["models"]["base00000001"]["count"], out["models"]["aaaaaaaaaaaa"]["source"]),
          (12, "base"))
    check("2D and model files untouched", snapshot(), files_before)
    check("sidecars: only the collision key changed", {p.name: sidecar_rest(p) for p in (base, outfit)}, rest_before)

    print("[2] the same save again")
    n = len(fits)
    again = routes._set_character_collision_scales_sync("demo", {"scales": {"leg": 1.2}})
    check("nothing refitted", len(fits) - n, 0)
    check("same answer", again["models"], out["models"])

    print("[3] reset")
    routes._set_character_collision_scales_sync("demo", {"scales": {}})
    check("profile without collision_scales", "collision_scales" in get_character_profile("demo")["model3d_opts"], False)
    near("base left_thigh back", radius(base, "left_thigh"), 0.066)
    near("outfit left_thigh back", radius(outfit, "left_thigh"), 0.066)

    print("[4] refused")
    routes._set_character_collision_scales_sync("demo", {"scales": {"arm": 0.8}})
    stored = get_character_profile("demo")["model3d_opts"].get("collision_scales")
    for bad in ({"scales": {"leg": 1.6}}, {"scales": {"tail": 1.0}}, {"scales": {"arm": "x"}}, {},
                {"scales": {}, "x": 1}):
        try:
            routes._set_character_collision_scales_sync("demo", bad)
            check(f"{bad!r} → 400", "accepted", 400)
        except HTTPException as exc:
            check(f"{bad!r} → 400", exc.status_code, 400)
    check("nothing stored by a refused save", get_character_profile("demo")["model3d_opts"].get("collision_scales"),
          stored)
    try:
        routes._set_character_collision_scales_sync("nobody", {"scales": {}})
        check("unknown character → 404", "accepted", 404)
    except HTTPException as exc:
        check("unknown character → 404", exc.status_code, 404)
    collision.fit_capsules = real_fit

    print("[5] admin only")
    from app.core.auth_dependency import require_admin
    route = next(r for r in routes.router.routes
                 if getattr(r, "path", "").endswith("/model3d/collision/scales"))
    check("require_admin dependency", any(dep.call is require_admin for dep in route.dependant.dependencies), True)
    check("POST only", route.methods, {"POST"})

    print("FAIL" if FAILS else "OK", f"({len(FAILS)} failures)" if FAILS else "")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
