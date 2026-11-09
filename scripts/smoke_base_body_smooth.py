#!/usr/bin/env python3
"""Base body: the smooth pass of the front and side views (app/core/base_body.py).

Usage:
    ./.venv/bin/python scripts/smoke_base_body_smooth.py

Runs against a THROWAWAY world + instance with a copy of the repo's ``human``
package — no real world, no image backend, no server, no GPU. Expected
values derived by hand from the brief (2026-11-09) and the code rules:

Fixture ``Demo`` (template human-default, profile image Demo_1.png).
``bsig`` = base_signature(Demo). A recorder replaces
``expression_regen.render_character_image``: it writes an 8x8 RGBA PNG to
``<stem>.png`` — transparent but for pixel (4, 4), which is RAW (200, 0, 0)
for a first render and SMOOTH (0, 200, 0) for a smooth edit (sidecar_extra
carries ``smoothed``) — and a sidecar ``<stem>.json`` = its sidecar_extra.
A reference's pixel (4, 4) tells which image it was made from; its corner
(0, 0) reads grey (128, 128, 128) when it is neutral_view_reference's copy.

[1] generate_base_images("Demo") makes 7 calls, in this order:
      1 front raw:    stem staging/tpose_<bsig> (NOT model_refs itself: a
                      ``.smooth_*`` dir inside it), occasion "tpose", use case
                      "tpose", reference None, bare_prompt base_prompt(front);
      2 front smooth: stem model_refs/tpose_<bsig>, occasion "tpose_view",
                      use case "tpose" (the front's style), bare_prompt ==
                      SMOOTH_PROMPT exactly (the front has no view sentence),
                      reference named tpose_<bsig>.png, grey corner, made
                      from the RAW front (pixel RAW);
      3 back:         stem model_refs/tpose_back_<bsig> directly (no smooth),
                      use case "tpose_back", back_view True, reference made
                      from the SMOOTHED front (pixel SMOOTH);
      4 left raw:     staging/tpose_left_<bsig>, use case "tpose_side",
                      reference = the smoothed front (pixel SMOOTH);
      5 left smooth:  model_refs/tpose_left_<bsig>, occasion "tpose_view",
                      use case "tpose_side", bare_prompt = DRESS_VIEW["left"]
                      + " " + SMOOTH_PROMPT, reference from the RAW left;
      6/7 right raw / right smooth, like left.
    Every smooth call: extra_negative == base_prompt(view)[1], back_view
    False, sidecar_extra {"base_signature": bsig, "smoothed": True}; every
    raw call sidecar_extra {"base_signature": bsig}.
    Afterwards find_ref_image(Demo, "tpose", bsig) is model_refs/
    tpose_<bsig>.png with pixel SMOOTH and sidecar smoothed True; left/right
    stored SMOOTH, back RAW; model_refs holds exactly the 4 images + 4
    sidecars (the staging dirs and the reference copies are gone); status:
    nothing failed.
[2] Failing smooth passes (force): the front smooth RAISES "boom", the left
    smooth returns None. A stale model_refs/tpose_<bsig>.webp is planted
    first. Expected: 7 calls again (the run goes on), result maps every view
    to a path, the stored front is the RAW render as .png (pixel RAW, sidecar
    without "smoothed") and the .webp is gone, back's reference is made from
    the RAW front, left stored RAW, right SMOOTH; status front failed with
    "Smoothing failed, the unsmoothed image is kept: boom", left with
    "Smoothing failed, the unsmoothed image is kept: edit failed", back and
    right not failed; again exactly 4 images + 4 sidecars. A following run
    without failures (force) clears every status.
[3] view="front", force=True: 2 calls (front raw, front smooth), stored
    front SMOOTH; back/left/right are not rendered.
[4] Signature: BASE_BODY_VERSION == 2; changing SMOOTH_PROMPT changes
    base_signature(Demo), restoring it gives bsig again; smooth_prompt("back")
    raises ValueError (back has no smooth pass).
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
RAW, SMOOTH, GREY = (200, 0, 0), (0, 200, 0), (128, 128, 128)
CALLS = []
FAIL_SMOOTH = {}   # view -> "none" | "raise"


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}" + ("" if ok else f" — expected {want!r}"))
    if not ok:
        FAILS.append(label)


def tiny_png(path: Path, colour=RAW) -> None:
    from PIL import Image
    im = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    im.putpixel((4, 4), colour + (255,))
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path)


def pixels(path):
    from PIL import Image
    with Image.open(path) as im:
        rgb = im.convert("RGB")
        return rgb.getpixel((0, 0)), rgb.getpixel((4, 4))


def view_of(stem: Path) -> str:
    name = stem.name.split("_base")[0]
    return "front" if name == "tpose" else name.split("_")[1]


def recorder(character_name, *, output_stem, **kw):
    ref = kw.get("reference_image")
    corner, made_from = pixels(ref) if ref is not None else (None, None)
    smoothing = bool(kw["sidecar_extra"].get("smoothed"))
    view = view_of(output_stem)
    CALLS.append({"stem": output_stem, "view": view, "smooth": smoothing, "ref": ref,
                  "corner": corner, "made_from": made_from, **kw})
    if smoothing and FAIL_SMOOTH.get(view) == "raise":
        raise RuntimeError("boom")
    if smoothing and FAIL_SMOOTH.get(view) == "none":
        return None
    path = output_stem.with_suffix(".png")
    tiny_png(path, SMOOTH if smoothing else RAW)
    output_stem.with_suffix(".json").write_text(json.dumps(kw["sidecar_extra"]))
    return path


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="base-body-smooth-") as tmp:
        root = Path(tmp)
        os.environ["STORAGE_DIR"] = str(root / "world")
        os.environ["INSTANCE_DIR"] = str(root / "instance")
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "instance")
        paths.get_config_path().write_text(json.dumps({"packages": {"enabled": "human"}}))
        from app.core import config
        config.load(paths.get_config_path(), instance_path=root / "instance/config.json")
        from app.core import db
        db.init_schema()
        plugins = root / "plugins"
        shutil.copytree(ROOT / "plugins" / "human", plugins / "human")
        from app.plugins.loader import discover_packages
        discover_packages(plugins, force=True)

        from app.core import base_body, expression_regen, model_refs
        from app.models.character import (get_character_dir, get_character_images_dir,
                                          get_character_profile, save_character_profile)

        human = {"template": "human-default", "gender": "female", "age": 30, "height": 168,
                 "body_slots": {"skin": {"tone": "olive"}, "eyes": {"color": "green"},
                                "build": {"type": "athletic"}}}
        check("create Demo", save_character_profile("Demo", dict(human), create_new=True), True)
        tiny_png(get_character_images_dir("Demo") / "Demo_1.png")
        stored = get_character_profile("Demo")
        stored["profile_image"] = "Demo_1.png"
        check("profile image", save_character_profile("Demo", stored), True)

        refs = get_character_dir("Demo") / "model_refs"
        bsig = base_body.base_signature("Demo")
        stems = {"front": f"tpose_{bsig}", "back": f"tpose_back_{bsig}",
                 "left": f"tpose_left_{bsig}", "right": f"tpose_right_{bsig}"}

        def stored_files():
            return sorted(p.name for p in refs.iterdir())

        want_files = sorted([f"{s}.png" for s in stems.values()] + [f"{s}.json" for s in stems.values()])

        real_render = expression_regen.render_character_image
        expression_regen.render_character_image = recorder
        try:
            print("[1] the call sequence")
            out = base_body.generate_base_images("Demo")
            check("call count", len(CALLS), 7)
            check("sequence", [(c["view"], c["smooth"]) for c in CALLS],
                  [("front", False), ("front", True), ("back", False), ("left", False), ("left", True),
                   ("right", False), ("right", True)])
            check("stem names", [c["stem"].name for c in CALLS],
                  [stems["front"]] * 2 + [stems["back"]] + [stems["left"]] * 2 + [stems["right"]] * 2)
            staged = [c["stem"].parent for c in CALLS]
            check("raw renders staged inside model_refs",
                  [(p != refs, p.parent == refs, p.name.startswith(".smooth_")) for p, c in zip(staged, CALLS)
                   if not c["smooth"] and c["view"] != "back"], [(True, True, True)] * 3)
            check("smooth + back stored in model_refs", [p == refs for p, c in zip(staged, CALLS)
                                                         if c["smooth"] or c["view"] == "back"], [True] * 4)
            check("occasions", [c["occasion"] for c in CALLS],
                  ["tpose", "tpose_view", "tpose_view", "tpose_view", "tpose_view", "tpose_view", "tpose_view"])
            check("use cases", [c["image_use_case"] for c in CALLS],
                  ["tpose", "tpose", "tpose_back", "tpose_side", "tpose_side", "tpose_side", "tpose_side"])
            check("back_view", [bool(c.get("back_view")) for c in CALLS],
                  [False, False, True, False, False, False, False])
            check("front raw reference", CALLS[0]["ref"], None)
            check("reference names", [c["ref"].name for c in CALLS[1:]],
                  [f"{stems['front']}.png"] * 3 + [f"{stems['left']}.png", f"{stems['front']}.png",
                                                   f"{stems['right']}.png"])
            check("references on grey", [c["corner"] for c in CALLS[1:]], [GREY] * 6)
            check("references made from", [c["made_from"] for c in CALLS[1:]],
                  [RAW, SMOOTH, SMOOTH, RAW, SMOOTH, RAW])
            for c in CALLS:
                prompt, negative = base_body.base_prompt("Demo", c["view"])
                want_prompt = base_body.smooth_prompt(c["view"]) if c["smooth"] else prompt
                check(f"{c['view']} {'smooth' if c['smooth'] else 'raw'} prompt", c["bare_prompt"], want_prompt)
                check(f"{c['view']} {'smooth' if c['smooth'] else 'raw'} negative", c["extra_negative"], negative)
                check(f"{c['view']} {'smooth' if c['smooth'] else 'raw'} sidecar_extra", c["sidecar_extra"],
                      {"base_signature": bsig, **({"smoothed": True} if c["smooth"] else {})})
            check("front smooth prompt is the constant", CALLS[1]["bare_prompt"], base_body.SMOOTH_PROMPT)
            check("left smooth prompt", CALLS[4]["bare_prompt"],
                  base_body.DRESS_VIEW["left"] + " " + base_body.SMOOTH_PROMPT)
            front = model_refs.find_ref_image("Demo", "tpose", bsig)
            check("find_ref_image front", front, refs / f"{stems['front']}.png")
            check("stored front is smoothed", pixels(front)[1], SMOOTH)
            check("stored front sidecar", json.loads(front.with_suffix(".json").read_text()),
                  {"base_signature": bsig, "smoothed": True})
            check("stored views", {v: pixels(refs / f"{s}.png")[1] for v, s in stems.items()},
                  {"front": SMOOTH, "back": RAW, "left": SMOOTH, "right": SMOOTH})
            check("result", out, {v: str(refs / f"{s}.png") for v, s in stems.items()})
            check("model_refs content", stored_files(), want_files)
            check("status clean", {v: s["failed"] for v, s in base_body.base_status("Demo").items()},
                  {v: False for v in stems})

            print("[2] failing smooth passes keep the raw view")
            CALLS.clear()
            (refs / f"{stems['front']}.webp").write_bytes(b"stale")
            FAIL_SMOOTH.update(front="raise", left="none")
            out = base_body.generate_base_images("Demo", force=True)
            FAIL_SMOOTH.clear()
            check("call count", len(CALLS), 7)
            check("result", out, {v: str(refs / f"{s}.png") for v, s in stems.items()})
            front = model_refs.find_ref_image("Demo", "tpose", bsig)
            check("front kept raw", (front, pixels(front)[1]), (refs / f"{stems['front']}.png", RAW))
            check("front sidecar is the raw one", json.loads(front.with_suffix(".json").read_text()),
                  {"base_signature": bsig})
            check("back edited from the raw front", CALLS[2]["made_from"], RAW)
            check("stored views", {v: pixels(refs / f"{s}.png")[1] for v, s in stems.items()},
                  {"front": RAW, "back": RAW, "left": RAW, "right": SMOOTH})
            status = base_body.base_status("Demo")
            check("status", {v: (s["failed"], s["error"]) for v, s in status.items()},
                  {"front": (True, "Smoothing failed, the unsmoothed image is kept: boom"),
                   "back": (False, None),
                   "left": (True, "Smoothing failed, the unsmoothed image is kept: edit failed"),
                   "right": (False, None)})
            check("model_refs content (stale .webp gone)", stored_files(), want_files)
            CALLS.clear()
            base_body.generate_base_images("Demo", force=True)
            check("re-run clears the warnings", {v: s["failed"] for v, s in base_body.base_status("Demo").items()},
                  {v: False for v in stems})

            print("[3] a single front re-render is smoothed again")
            CALLS.clear()
            out = base_body.generate_base_images("Demo", view="front", force=True)
            check("calls", [(c["view"], c["smooth"]) for c in CALLS], [("front", False), ("front", True)])
            check("result", out, {"front": str(refs / f"{stems['front']}.png")})
            check("front smoothed", pixels(refs / f"{stems['front']}.png")[1], SMOOTH)
            check("model_refs content", stored_files(), want_files)
        finally:
            expression_regen.render_character_image = real_render
            FAIL_SMOOTH.clear()

        print("[4] the signature")
        check("version", base_body.BASE_BODY_VERSION, 2)
        original = base_body.SMOOTH_PROMPT
        try:
            base_body.SMOOTH_PROMPT = original + " Changed."
            changed = base_body.base_signature("Demo")
        finally:
            base_body.SMOOTH_PROMPT = original
        check("smooth prompt changes the signature", changed != bsig, True)
        check("restored prompt restores it", base_body.base_signature("Demo"), bsig)
        try:
            base_body.smooth_prompt("back")
            check("no back smooth", "no error", "ValueError")
        except ValueError:
            check("no back smooth", "ValueError", "ValueError")

    print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
