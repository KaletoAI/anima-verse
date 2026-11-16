#!/usr/bin/env python3
"""A163: the face view is the default face texture source and a run renders it first when it is missing or stale;
the choice face / front is one stored per-character setting (Base body settings). Expectations by hand.

Usage: ./.venv/bin/python scripts/smoke_face_source_a163.py

Throwaway storage, no server, no hub, 0 outbound requests: ``model_refs.current_profile_image`` and
``model_refs.generate_face_view`` are stubs (the stub writes face_view.png + its sidecar the way the real render
publishes it: ``image_sha256`` of the file, ``reference_sha256`` of the profile picture), the profile store is a dict.

Hand-derived expectations:
[1] no stored option -> ``face_retexture.stored_source`` "face"; ``set_model3d_options({"face_source": "front"})``
    stores "front", "face" removes the key again (only deviations stored); "side" is a ValueError.
[2] profile picture, no face view, source face: ``reference_info(..., "")`` -> reference "face" (NOT "front":
    the old silent fallback), problem "no_face_photo"; ``face_view_due`` "no_face_photo".
[3] source front -> reference "front", ``face_view_due`` "" (the front view needs no face view).
[4] ``ensure_face_view`` with the face view missing: the stub is called exactly once with force False, afterwards
    the view is current -> returns None, ``face_view_due`` "".
[5] stale (profile picture replaced — the Tilda case): due "face_stale"; ensure renders once more -> None.
[6] unverified (sidecar without image hash): ensure calls the render with force True (the plain render would
    return the old file because its reference hash still matches).
[7] the render fails (stub raises) -> ensure returns code "face_view_failed" with the reason; the reference stays
    "face" (no fallback).
[8] cost: ``model3d._mesh_hub_stages`` with the face planned and the face view due = mesh, face view, face, rig
    (face view + face never upscaled: ``use_upscale("face", None)`` False) = 4 jobs; with the view current =
    mesh, face, rig = 3; with source front = mesh, upscale, face, rig = 4.
[9] UI contract: FaceSettings posts ``face_source`` and shows "Face texture source"; the retexture dialog no
    longer has a reference <select> and sends no ``reference`` query; the routes take no ``reference`` parameter;
    ``runAllStep('face view')`` has a label; de.json translates the new strings.
"""
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


def png_bytes(seed: int) -> bytes:
    import io
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", (8, 8), (seed % 256, 100, 50)).save(out, "PNG")
    return out.getvalue()


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="face-source-a163-") as tmp:
        root = Path(tmp)
        os.environ["STORAGE_DIR"] = str(root / "world")
        os.environ["INSTANCE_DIR"] = str(root / "instance")
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "instance")
        from app.core import face_retexture, model3d, model_refs
        import app.models.character as character_model
        from app.models.character import get_character_dir

        name = "Demo"
        cdir = get_character_dir(name, create=True)
        (cdir / "images").mkdir(parents=True, exist_ok=True)
        refs = cdir / "model_refs"
        refs.mkdir(exist_ok=True)
        profiles = {name: {}}
        character_model.get_character_profile = lambda n, *a, **k: profiles.get(n, {})
        character_model.save_character_profile = lambda n, p, *a, **k: profiles.__setitem__(n, p) or True
        picture = cdir / "images" / "profile.png"
        picture.write_bytes(png_bytes(1))
        model_refs.current_profile_image = lambda character, *, profile=None: picture
        face = refs / "face_view.png"
        calls = []
        fail = {"on": False}

        def fake_render(character, force=False, render=None):
            calls.append(force)
            if fail["on"]:
                raise RuntimeError("route down")
            face.write_bytes(png_bytes(40 + len(calls)))
            face.with_suffix(".json").write_text(json.dumps({
                "image_sha256": hashlib.sha256(face.read_bytes()).hexdigest(),
                "reference_sha256": hashlib.sha256(picture.read_bytes()).hexdigest()}))
            return face
        model_refs.generate_face_view = fake_render

        print("[1] the stored setting")
        check("default face", face_retexture.stored_source(name), "face")
        model3d.set_model3d_options(name, {"face_source": "front"})
        check("front stored", (profiles[name].get("model3d_opts") or {}).get("face_source"), "front")
        check("stored_source front", face_retexture.stored_source(name), "front")
        model3d.set_model3d_options(name, {"face_source": "face"})
        check("face = default, key removed", "face_source" in (profiles[name].get("model3d_opts") or {}), False)
        try:
            model3d.set_model3d_options(name, {"face_source": "side"})
            check("invalid refused", False, True)
        except ValueError:
            check("invalid refused", True, True)

        print("[2] missing face view, source face")
        info = face_retexture.reference_info(name, "abc", {})
        check("reference stays face", (info["reference"], (info["face_problem"] or {}).get("code")), ("face", "no_face_photo"))
        check("due", face_retexture.face_view_due(name), "no_face_photo")

        print("[3] source front")
        model3d.set_model3d_options(name, {"face_source": "front"})
        check("front, not due", (face_retexture.reference_info(name, "abc", {})["reference"], face_retexture.face_view_due(name)), ("front", ""))
        check("ensure does nothing", (face_retexture.ensure_face_view(name), calls), (None, []))
        model3d.set_model3d_options(name, {"face_source": "face"})

        print("[4] ensure renders the missing view first")
        check("ensure -> None", face_retexture.ensure_face_view(name), None)
        check("one render, force False", calls, [False])
        check("current now", face_retexture.face_view_due(name), "")

        print("[5] profile picture replaced -> stale")
        picture.write_bytes(png_bytes(2))
        check("due stale", face_retexture.face_view_due(name), "face_stale")
        check("ensure -> None", face_retexture.ensure_face_view(name), None)
        check("rendered again", calls, [False, False])

        print("[6] unverified -> forced render")
        face.with_suffix(".json").write_text(json.dumps({"reference_sha256": hashlib.sha256(picture.read_bytes()).hexdigest()}))
        check("due unverified", face_retexture.face_view_due(name), "face_unverified")
        check("ensure -> None", face_retexture.ensure_face_view(name), None)
        check("forced", calls[-1], True)

        print("[7] render fails -> visible problem, no fallback")
        picture.write_bytes(png_bytes(3))
        fail["on"] = True
        problem = face_retexture.ensure_face_view(name) or {}
        check("code", problem.get("code"), "face_view_failed")
        check("reason named", "route down" in problem.get("message", ""), True)
        check("reference still face", face_retexture.reference_info(name, "abc", {})["reference"], "face")
        fail["on"] = False

        print("[8] cost line")
        model3d._face_route_ok = lambda c: True
        check("due: mesh, face view, face, rig", model3d._mesh_hub_stages(name, "abc", True), ["mesh", "face view", "face", "rig"])
        face_retexture.ensure_face_view(name)
        check("current: mesh, face, rig", model3d._mesh_hub_stages(name, "abc", True), ["mesh", "face", "rig"])
        model3d.set_model3d_options(name, {"face_source": "front"})
        check("front: mesh, upscale, face, rig", model3d._mesh_hub_stages(name, "abc", True), ["mesh", "upscale", "face", "rig"])

    print("[9] UI / route contract")
    settings = (ROOT / "frontend/src/tabs/characters/FaceSettings.tsx").read_text(encoding="utf-8")
    actions = (ROOT / "frontend/src/tabs/characters/ModelFaceActions.tsx").read_text(encoding="utf-8")
    model_ts = (ROOT / "frontend/src/tabs/characters/baseBodyModel.ts").read_text(encoding="utf-8")
    routes = (ROOT / "app/routes/characters.py").read_text(encoding="utf-8")
    check("FaceSettings saves face_source", "setOption('face_source'" in settings and "Face texture source" in settings, True)
    check("dialog has no reference select", "setFaceReference" in actions or "reference: faceReference" in actions, False)
    check("routes take no reference query", bool(re.search(r'reference: str = Query\(', routes)), False)
    check("run-all label", "case 'face view':" in model_ts, True)
    de = json.loads((ROOT / "shared/languages/de.json").read_text(encoding="utf-8"))["translations"]
    for key in ("Face texture source", "Face view (default)", "Face view current", "+1 image job (face view)",
                "the next run renders it first", "Face view (from the profile picture)"):
        check(f"de.json {key!r}", bool(de.get(key)), True)

    print()
    if FAILS:
        print(f"FAILED: {len(FAILS)}")
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
