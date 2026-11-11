#!/usr/bin/env python3
"""A prompt-WORDING change never orphans a stored base body (app/core/base_body.py).

Usage:
    ./.venv/bin/python scripts/smoke_base_identity.py

Throwaway storage with the repo's ``human`` package, one character ``Demo``
(female, 30, 168 cm, olive skin, green eyes, athletic) with a profile image.
No server, no backend: the base views are stub PNG files with hand-written
sidecars, exactly as ``generate_base_images`` writes them.

The incident (2026-11-11): commit ad341e95 reworded the base prompts, and
``base_signature`` hashed the prompt texts — after the restart every
character got a new signature, the Base body tab was empty although every
file was still on disk, and every outfit model built on the old signature
counted as stale. The rule now: the signature covers what the base IS
(``base_identity``: appearance, profile image, BASE_BODY_VERSION); the
wording is a ``prompt_fingerprint`` in the sidecar and only shows as the
freshness note ``OLDER_PROMPTS``. Expectations, derived from that rule:

[1] base_identity and prompt_fingerprint are the documented shapes
    ("base" + 8 hex; 12 hex). Rewording a prompt (BASE_VIEW_PROMPTS["back"]
    patched to another sentence) leaves base_identity unchanged and changes
    prompt_fingerprint; a different profile image changes base_identity.
[2] Nothing stored: base_signature == base_identity (the name the next
    render gets).
[3] A LEGACY set (sidecars with base_signature only — no base_identity, no
    prompt_fingerprint — rendered from the current profile image) stored
    under some other name "basefeedface": base_signature resolves to
    "basefeedface" (newest legacy set whose reference is the current profile
    image), base_info reports it with the front and back tiles, and after
    model_overview.annotate_base_info every tile's freshness is
    {"state": "stale", "reason": OLDER_PROMPTS} — current, with the note.
    This is the check that FAILS on ad341e95: there the signature was the
    prompt hash and the legacy name was never found again (signature !=
    "basefeedface", every image None).
[4] A legacy set whose reference was ANOTHER profile image is not taken
    (base_signature == identity).
[5] A set rendered by the new code under a name that is not the identity
    (a re-render of a legacy set keeps its name): its sidecar carries
    base_identity == identity -> it is found; one with a foreign identity is
    not. With the current prompt_fingerprint in the sidecar the front tile
    is {"state": "current"}; the back tile rendered with an older
    fingerprint is stale with OLDER_PROMPTS, a back older than the front is
    stale with "Made from an older front view" (that reason wins).
[6] Under the reworded prompt the resolution of [5] still holds
    (base_signature unchanged) and the front tile shows OLDER_PROMPTS.
[7] A set stored under the identity name itself wins over any legacy set.
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS = []
#: The commit whose signature hashed the prompt texts — never HEAD.
BEFORE = "ad341e95"


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}" + ("" if ok else f" — expected {want!r}"))
    if not ok:
        FAILS.append(label)


PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def write_set(refs: Path, signature: str, *, reference: str, created: str, extra=None, back_created=None):
    """The four base views of ``signature`` with sidecars as the render writes them."""
    for view, kind in (("front", "tpose"), ("back", "tpose_back"), ("left", "tpose_left"), ("right", "tpose_right")):
        stem = refs / f"{kind}_{signature}"
        stem.with_suffix(".png").write_bytes(PNG + view.encode())
        meta = {"base_signature": signature, "created_at": created if view == "front" else (back_created or created),
                "reference_images": {"input_reference_image_1": reference if view == "front" else f"tpose_{signature}.png"},
                "model": "stub", **(extra or {})}
        stem.with_suffix(".json").write_text(json.dumps(meta))


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="base-identity-") as tmp:
        root = Path(tmp)
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        paths.get_config_path().write_text(json.dumps({"packages": {"enabled": "human"}}))
        from app.core import config
        config.load(paths.get_config_path(), instance_path=root / "instance/config.json")
        from app.core import db
        db.init_schema()
        plugins = root / "plugins"
        shutil.copytree(ROOT / "plugins" / "human", plugins / "human")
        from app.plugins.loader import discover_packages
        discover_packages(plugins, force=True)

        from app.core import base_body, model_overview
        from app.core.model_refs import get_model_refs_dir
        from app.models.character import get_character_images_dir, get_character_profile, save_character_profile

        name = "Demo"
        profile = {"template": "human-default", "gender": "female", "age": 30, "height": 168,
                   "model_pipeline": "base_body",
                   "body_slots": {"skin": {"tone": "olive"}, "eyes": {"color": "green"},
                                  "build": {"type": "athletic"}, "hair": {"length": "long", "color": "brunette"}}}
        check("create", save_character_profile(name, profile, create_new=True), True)
        images = get_character_images_dir(name)
        images.mkdir(parents=True, exist_ok=True)
        (images / "Demo_1.png").write_bytes(PNG + b"1" * 100)
        (images / "Demo_2.png").write_bytes(PNG + b"2" * 200)
        stored = get_character_profile(name)
        stored["profile_image"] = "Demo_1.png"
        check("save image", save_character_profile(name, stored), True)
        stored = get_character_profile(name)
        refs = get_model_refs_dir(name)
        refs.mkdir(parents=True, exist_ok=True)

        print("[1] identity vs fingerprint")
        identity = base_body.base_identity(name, profile=stored)
        fingerprint = base_body.prompt_fingerprint(name, profile=stored)
        check("identity shape", (identity.startswith("base"), len(identity),
                                 all(c in "0123456789abcdef" for c in identity[4:])), (True, 12, True))
        check("fingerprint shape", (len(fingerprint), all(c in "0123456789abcdef" for c in fingerprint)), (12, True))
        original_back = base_body.BASE_VIEW_PROMPTS["back"]
        base_body.BASE_VIEW_PROMPTS["back"] = "The same person seen from behind in the same pose."
        try:
            check("rewording keeps the identity", base_body.base_identity(name, profile=stored), identity)
            check("rewording changes the fingerprint",
                  base_body.prompt_fingerprint(name, profile=stored) != fingerprint, True)
        finally:
            base_body.BASE_VIEW_PROMPTS["back"] = original_back
        other_image = dict(stored, profile_image="Demo_2.png")
        check("another profile image changes the identity",
              base_body.base_identity(name, profile=other_image) != identity, True)

        print("[2] nothing stored")
        check("signature = identity", base_body.base_signature(name, profile=stored), identity)

        print("[3] a legacy set is found again and carries the note")
        write_set(refs, "basefeedface", reference="Demo_1.png", created="2026-11-09T18:00:00+00:00")
        check("signature = legacy name", base_body.base_signature(name, profile=stored), "basefeedface")
        info = base_body.base_info(name)
        check("info signature", info["signature"], "basefeedface")
        check("front + back tiles", (info["images"]["front"] is not None, info["images"]["back"] is not None),
              (True, True))
        info = model_overview.annotate_base_info(name, info)
        check("every tile: stale + OLDER_PROMPTS",
              {v: (m or {}).get("freshness") for v, m in info["image_meta"].items()},
              {v: {"state": "stale", "reason": base_body.OLDER_PROMPTS} for v in base_body.BASE_VIEWS})
        check("prompts_current false", base_body.prompts_current(name, "basefeedface", profile=stored), False)

        print("[4] a legacy set of another profile image is not taken")
        for f in refs.glob("*feedface*"):
            f.unlink()
        write_set(refs, "basefeedface", reference="Demo_2.png", created="2026-11-09T18:00:00+00:00")
        check("signature = identity", base_body.base_signature(name, profile=stored), identity)
        for f in refs.glob("*feedface*"):
            f.unlink()

        print("[5] a set that names its identity")
        write_set(refs, "basec0ffee00", reference="Demo_1.png", created="2026-11-11T10:00:00+00:00",
                  extra={"base_identity": "baseffffffff", "prompt_fingerprint": fingerprint})
        check("foreign identity: not taken", base_body.base_signature(name, profile=stored), identity)
        for f in refs.glob("*c0ffee00*"):
            f.unlink()
        write_set(refs, "basec0ffee00", reference="Demo_1.png", created="2026-11-11T10:00:00+00:00",
                  extra={"base_identity": identity, "prompt_fingerprint": fingerprint})
        (refs / "tpose_back_basec0ffee00.json").write_text(json.dumps({
            "base_signature": "basec0ffee00", "created_at": "2026-11-11T10:05:00+00:00",
            "base_identity": identity, "prompt_fingerprint": "000000000000"}))
        (refs / "tpose_left_basec0ffee00.json").write_text(json.dumps({
            "base_signature": "basec0ffee00", "created_at": "2026-11-11T09:00:00+00:00",
            "base_identity": identity, "prompt_fingerprint": fingerprint}))
        check("own identity: taken", base_body.base_signature(name, profile=stored), "basec0ffee00")
        check("prompts_current true", base_body.prompts_current(name, "basec0ffee00", profile=stored), True)
        info = model_overview.annotate_base_info(name, base_body.base_info(name))
        fresh = {v: (m or {}).get("freshness") for v, m in info["image_meta"].items()}
        check("front current", fresh["front"], {"state": "current", "reason": ""})
        check("back: older prompts", fresh["back"], {"state": "stale", "reason": base_body.OLDER_PROMPTS})
        check("left: older than the front wins", fresh["left"],
              {"state": "stale", "reason": model_overview.OLDER_FRONT_VIEW})
        check("right current", fresh["right"], {"state": "current", "reason": ""})

        print("[6] reworded prompt: same set, note on the front")
        base_body.BASE_VIEW_PROMPTS["back"] = "The same person seen from behind in the same pose."
        try:
            check("signature unchanged", base_body.base_signature(name, profile=stored), "basec0ffee00")
            info = model_overview.annotate_base_info(name, base_body.base_info(name))
            check("front: older prompts", (info["image_meta"]["front"] or {}).get("freshness"),
                  {"state": "stale", "reason": base_body.OLDER_PROMPTS})
        finally:
            base_body.BASE_VIEW_PROMPTS["back"] = original_back

        print("[7] the identity name itself wins")
        write_set(refs, identity, reference="Demo_1.png", created="2026-11-11T12:00:00+00:00",
                  extra={"base_identity": identity, "prompt_fingerprint": fingerprint})
        check("signature = identity", base_body.base_signature(name, profile=stored), identity)

    print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
