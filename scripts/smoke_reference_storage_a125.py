#!/usr/bin/env python3
"""User rules 2026-11-16 (with Ruling A125): reference pictures made FOR a figure — generated or uploaded as a
reference (record origin "generated" / "upload") — are stored in ``model_refs/references``, never the gallery; the
ones a record uses that still lie in the gallery are MOVED there once (``move_gallery_references``, run at boot).
A picture picked from the gallery (origin "gallery") stays there; unreferenced pictures stay untouched.

Usage:
    ./.venv/bin/python scripts/smoke_reference_storage_a125.py

Throwaway storage (``paths.init(<tmp>)`` before any world import); the folder and profile readers are stubbed —
no world.db, no server, no outbound request.

Expected, by hand (character "Demo", gallery G = <tmp>/images, refs R = <tmp>/model_refs):
[1] store_reference(Demo, PNG, ".png", "fullbody") -> "Demo_<stamp>_fullbody.png" in R/references; G empty;
    ".gif" -> ValueError.
[2] image_path: {that name, origin generated} -> R/references/<name>; {B.png, origin gallery} with G/B.png ->
    G/B.png; {B.png, origin generated} -> None (no fallback to the gallery); {"../x.png", gallery} -> None.
[3] reference_url: R/references/<name> -> "/characters/Demo/figure/reference-image/<name>?v=<mtime_ns>"; G/B.png
    -> "/characters/Demo/images/B.png?v=…".
[4] move: G = {A.png, A.json, B.png, C.png, E.png, U.png}; profile_image E.png; records full_body {A.png,
    generated}, outfits {k1: B.png gallery, k2: C.png upload, k3: D.png generated (no file), k4: E.png
    generated}. -> moved [A.png, C.png] (A with its A.json); G afterwards = {B.png, E.png, U.png}; R/references
    gains A.png, A.json, C.png; image_path of A / C now resolves in R/references. A second run moves nothing.
"""
import io
import os
import socket
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
FAILS = []


def check(label, ok, detail=""):
    print(f"{'ok ' if ok else 'FAIL'} {label} {detail}")
    if not ok:
        FAILS.append(label)


def _refuse(self, *a, **k):  # noqa: ANN001
    raise OSError("outbound connection refused by the smoke")


socket.socket.connect = _refuse


def png() -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (1, 2, 3)).save(buf, format="PNG")
    return buf.getvalue()


def main():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        os.environ["STORAGE_DIR"] = str(tmp / "world")
        from app.core import paths
        paths.init(str(tmp / "world"))
        from app.core import model_refs, outfit_references as orf
        from app.models import character
        gallery, refs = tmp / "images", tmp / "model_refs"
        gallery.mkdir()
        refs.mkdir()
        profile = {}
        character.get_character_images_dir = lambda name: gallery
        character.get_character_profile = lambda name: profile
        model_refs.get_model_refs_dir = lambda name: refs
        R = refs / "references"

        name = orf.store_reference("Demo", png(), ".png", "fullbody")
        check("[1] stored in model_refs/references", (R / name).is_file()
              and name.startswith("Demo_") and name.endswith("_fullbody.png"), name)
        check("[1] gallery untouched", list(gallery.iterdir()) == [])
        try:
            orf.store_reference("Demo", png(), ".gif", "fullbody")
            check("[1] .gif refused", False)
        except ValueError:
            check("[1] .gif refused", True)

        (gallery / "B.png").write_bytes(png())

        def rec(image, origin):
            return {"image": image, "sha256": "x", "origin": origin}
        check("[2] generated in references", orf.image_path("Demo", rec(name, "generated")) == (R / name).resolve())
        check("[2] pick in the gallery", orf.image_path("Demo", rec("B.png", "gallery")) == (gallery / "B.png").resolve())
        check("[2] no gallery fallback", orf.image_path("Demo", rec("B.png", "generated")) is None)
        check("[2] escape refused", orf.image_path("Demo", rec("../x.png", "gallery")) is None)

        url = orf.reference_url("Demo", (R / name).resolve())
        check("[3] stored url", url == f"/characters/Demo/figure/reference-image/{name}?v={(R / name).stat().st_mtime_ns}",
              url)
        check("[3] gallery url", orf.reference_url("Demo", (gallery / "B.png").resolve())
              .startswith("/characters/Demo/images/B.png?v="))

        for f in ("A.png", "C.png", "E.png", "U.png"):
            (gallery / f).write_bytes(png())
        (gallery / "A.json").write_text("{}")
        profile.update({"profile_image": "E.png", "full_body_reference": rec("A.png", "generated"),
                        "outfit_references": {"k1": rec("B.png", "gallery"), "k2": rec("C.png", "upload"),
                                              "k3": rec("D.png", "generated"), "k4": rec("E.png", "generated")}})
        moved = orf.move_gallery_references("Demo")
        check("[4] moved A and C", sorted(moved) == ["A.png", "C.png"], moved)
        check("[4] gallery keeps B, E, U", sorted(f.name for f in gallery.iterdir()) == ["B.png", "E.png", "U.png"],
              sorted(f.name for f in gallery.iterdir()))
        check("[4] references gain A, A.json, C", all((R / f).is_file() for f in ("A.png", "A.json", "C.png")))
        check("[4] records resolve", orf.image_path("Demo", rec("A.png", "generated")) == (R / "A.png").resolve()
              and orf.image_path("Demo", rec("C.png", "upload")) == (R / "C.png").resolve())
        check("[4] idempotent", orf.move_gallery_references("Demo") == [])
    print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
