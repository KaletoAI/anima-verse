#!/usr/bin/env python3
"""The face-view reference state shown BEFORE a face retexture (``model3d.face_info`` -> ``face_reference``,
``face_retexture.reference_info``) and its surface in ModelFaceActions; expectations by hand.

Usage: ./.venv/bin/python scripts/smoke_face_view_state.py

Throwaway storage, no server, no hub. ``model_refs.current_profile_image`` is replaced by a stub that returns a
file under a temp character directory (the real one reads the profile from the world DB).

The rule (``reference_info``): the face view ``model_refs/face_view.png`` is the reference only when its sidecar
carries ``image_sha256`` == sha256 of the file AND ``reference_sha256`` == sha256 of the current profile picture;
otherwise the run silently takes the front view. ``face_info`` exposes that choice as
``face_reference = {reference, face_available, face_problem}`` so the tab can say it before a run.

Hand-derived expectations:
[1] no profile picture -> reference "front", face_available False, problem code "no_profile_image";
[2] profile picture, no face view -> "front", "no_face_photo";
[3] face view whose sidecar has no image hash -> "face_unverified";
[4] face view rendered from an OLDER profile picture (reference_sha256 of other bytes) -> "face_stale" — the
    user's case: the projection would use the small face of the full-body front view;
[5] face view current (both hashes match) -> reference "face", face_available True, face_problem None;
[6] the payload survives a broken state: ``face_info`` on a character directory without a model_refs folder still
    returns the key (never raises).
[7] UI contract (text of the sources): ModelFaceActions.tsx renders ``faceReferenceNotice`` with the strings
    "Face view stale (built from an older profile picture)", "No face view", "the front view would be used" and a
    "Regenerate face view" button that posts to ``model-refs/generate`` with view "face" (the face view card's own
    route); the notice sits in the face section (data-face-reference) AND in the retexture dialog (beside the
    reference select); FieldModel3D.tsx declares ``face_reference`` on Model3DInfo; de.json translates the new
    strings; ``faceViewRegenerable`` offers the button for face_stale / no_face_photo / face_unverified but not for
    no_profile_image / face_rendering (the function's four branches, read from the source).
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
    image = Image.new("RGB", (8, 8), (seed % 256, 100, 50))
    out = io.BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="face-view-state-") as tmp:
        root = Path(tmp)
        os.environ["STORAGE_DIR"] = str(root / "world")
        os.environ["INSTANCE_DIR"] = str(root / "instance")
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "instance")
        from app.core import model_refs
        from app.core.model3d import face_info
        from app.models.character import get_character_dir

        name = "Demo"
        cdir = get_character_dir(name, create=True)
        (cdir / "images").mkdir(parents=True, exist_ok=True)
        models = cdir / "model3d"
        (models / "unrigged").mkdir(parents=True, exist_ok=True)
        sig = "0abc0abc0abc"
        (models / f"{sig}.glb").write_bytes(b"glTF-model")
        (models / f"{sig}.json").write_text(json.dumps({"rig": "mixamo"}))
        (models / "unrigged" / f"{sig}.glb").write_bytes(b"glTF-src")
        (models / "unrigged" / f"{sig}.json").write_text(json.dumps({"source_image": f"tpose_{sig}.png"}))
        refs = cdir / "model_refs"
        refs.mkdir(exist_ok=True)
        profile = {"path": None}
        model_refs.current_profile_image = lambda character, *, profile=None, _p=profile: _p["path"]

        def state():
            return (face_info(name, models / f"{sig}.glb") or {}).get("face_reference")

        print("[1] no profile picture")
        s = state()
        check("front, no_profile_image", (s["reference"], s["face_available"], (s["face_problem"] or {}).get("code")),
              ("front", False, "no_profile_image"))

        print("[2] profile picture, no face view")
        picture = cdir / "images" / "profile.png"
        picture.write_bytes(png_bytes(1))
        profile["path"] = picture
        s = state()
        check("front, no_face_photo", (s["reference"], s["face_available"], (s["face_problem"] or {}).get("code")),
              ("front", False, "no_face_photo"))

        print("[3] face view without an image hash")
        face = refs / "face_view.png"
        face.write_bytes(png_bytes(2))
        face.with_suffix(".json").write_text(json.dumps({"reference_sha256": hashlib.sha256(picture.read_bytes()).hexdigest()}))
        s = state()
        check("front, face_unverified", (s["reference"], (s["face_problem"] or {}).get("code")), ("front", "face_unverified"))

        print("[4] face view from an older profile picture")
        face.with_suffix(".json").write_text(json.dumps({"image_sha256": hashlib.sha256(face.read_bytes()).hexdigest(),
                                                         "reference_sha256": hashlib.sha256(png_bytes(9)).hexdigest()}))
        s = state()
        check("front, face_stale", (s["reference"], s["face_available"], (s["face_problem"] or {}).get("code")),
              ("front", False, "face_stale"))
        check("stale message names the profile picture", "profile picture changed" in (s["face_problem"] or {}).get("message", ""), True)

        print("[5] face view current")
        face.with_suffix(".json").write_text(json.dumps({"image_sha256": hashlib.sha256(face.read_bytes()).hexdigest(),
                                                         "reference_sha256": hashlib.sha256(picture.read_bytes()).hexdigest()}))
        s = state()
        check("face, available", (s["reference"], s["face_available"], s["face_problem"]), ("face", True, None))

        print("[6] never raises")
        other = get_character_dir("Bare", create=True) / "model3d"
        other.mkdir(parents=True, exist_ok=True)
        (other / f"{sig}.glb").write_bytes(b"glTF")
        s = (face_info("Bare", other / f"{sig}.glb") or {})
        check("key present without model_refs", "face_reference" in s and (s["face_reference"] or {}).get("reference") in ("front", None), True)

    print("[7] UI contract")
    actions = (ROOT / "frontend/src/tabs/characters/ModelFaceActions.tsx").read_text(encoding="utf-8")
    field = (ROOT / "frontend/src/tabs/characters/FieldModel3D.tsx").read_text(encoding="utf-8")
    de = json.loads((ROOT / "shared/languages/de.json").read_text(encoding="utf-8"))
    translations = de.get("translations") if isinstance(de.get("translations"), dict) else de
    for needle in ("Face view stale (built from an older profile picture)", "No face view", "the front view would be used",
                   "Regenerate face view", "model-refs/generate", "view: 'face'", "data-face-reference",
                   "faceReferenceNotice({ reference: faceCheck.reference"):
        check(f"ModelFaceActions has {needle!r}", needle in actions, True)
    check("FieldModel3D declares face_reference", "face_reference?: FaceReferenceState | null" in field, True)
    for key in ("Face view stale (built from an older profile picture)", "the front view would be used", "No face view",
                "Regenerate face view", "Face view requested"):
        check(f"de.json translates {key!r}", bool(translations.get(key)), True)
    regenerable = re.search(r"export function faceViewRegenerable\((.*?)\n}\n", actions, re.S)
    body = regenerable.group(0) if regenerable else ""
    check("regenerable excludes no_profile_image and face_rendering", "'no_profile_image'" in body and "'face_rendering'" in body
          and "!ref.face_available" in body, True)

    print()
    if FAILS:
        print(f"FAILED: {len(FAILS)}")
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
