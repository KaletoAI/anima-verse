#!/usr/bin/env python3
"""The beard-free HairDeck input (app/core/garment_beard.py): trigger, gate, cache, prompt, fingerprint and
the HairDeck job that sends the edited picture.

Usage:
    ./.venv/bin/python scripts/smoke_hairdeck_beard_free.py

Runs against a THROWAWAY storage + instance directory with a copy of the repo's ``human`` package — no real
world, no hub, no GPU, no server. Stubs: the image service (``generate_hair`` = recorder writing the files of a
HairDeck job, ``pool`` = one fake img2hair backend "HairDeck" with extra_params {"input_steps": 30}),
``expression_regen.render_character_image`` (recorder that writes an edit of the square reference) and
``garment_images._mask`` (the synthetic figure mask below, for every picture — the BiRefNet model is not run).

THE SYNTHETIC PORTRAIT (640×640, square, so the edit canvas is the picture itself: side 640, offset (0, 0)):
white background; the figure = rows 40..639 × cols 170..469 (a 300-px-wide head running out of the frame),
grey (128) with 8-row black/white stripes in rows 40..199 (the "hair").

EXPECTED VALUES, DERIVED BY HAND
[1] mentions_facial_hair (whole words, a term right after "no"/"without (a|an|any)"/"not", at most one word
    between, is denied): "light stubble", "short beard", "full beard", "mustache", "bearded", "a trimmed
    moustache", "stubbly chin", "goatee" -> True; "clean-shaven", "no beard", "without a moustache", "no
    visible beard", "short brunette hair", "long sideburns", "Beardsley" -> False.
[2] facial_hair_texts on profile dicts (human package: slot facial_hair applies to gender male only, its
    always text is "{style}"): male + style "light stubble" -> ["light stubble"]; male + "clean-shaven" ->
    []; female + "short beard" -> [] (the slot does not apply); male without the slot, appearance "tall, a
    full beard, green eyes" -> ["a full beard"]; male, appearance "no beard. short hair" -> [];
    hsig_inputs: {"beard_free": 1} for the first, {} for the second.
[3] head_frame of the figure: y0 40, width 300 (every row is 300 wide), cx (170 + 469) / 2 = 319.5. Nose row
    = 40 + 0.88·300 = 304; pool k = round(300 / 128) = 2. Zone = the half-ellipse below row 304, semi-axes
    a = 0.43·300 = 129, b = (2.0 − 0.88)·300 = 336 (it ends at row 640, inside the frame).
    beard_gate:
    a. the edit adds 40 to rows 360..560 × cols 260..379 (inside the zone with ≥ 2 px margin: at row 560
       the oval's half-width is 129·sqrt(1 − (256/336)²) = 83.6 > 60 + 2) -> outside_dRGB 0.0, upper_xor 0.0,
       beard_dRGB ≈ 40 · (201·120) / (π·129·336/2) = 40 · 24120 / 68084 = 14.2 (pooling: within 12.5..16) -> ok.
    b. the same edit shifted 8 rows down (picture AND mask, the top filled with background — no wrap-around):
       upper_xor = 8·300 / (264·300) = 0.0303 > 0.015,
       outside_dRGB > 7 (the stripes swap in the hair) -> refused with both reasons.
    c. the unchanged picture -> beard_dRGB 0.0 < 4 -> refused "beard not removed".
[4] beard_free_input (job folder F): cached(F, P) None first; one render call with bare_prompt = PROMPT =
    "Keep the image exactly as it is. Remove the beard; the chin and cheeks are clean-shaven.",
    extra_negative "beard, moustache, stubble", occasion "garment_view", image_use_case "garment_edit",
    character_loras False, postprocess False, 640×640 -> accepted, F/beard_free.png, record {accepted True,
    version 1, source_sha256 = sha256(P), attempt 1}. Again: no render call (cache by sha), same path.
    Another picture P2: cached None, a new render. A no-op edit model: ATTEMPTS = 2 render calls, both
    refused -> (P2, record accepted False); note() starts "Beard removal refused".
[5] garment_hsig of Demo (male, hair item, method hairdeck): with "light stubble" =
    md5({"beard_free": 1, "extra_params": {"input_steps": 30}, "profile_image": sha256(Demo_1.png),
    "version": 1}, sorted keys)[:12]; with "clean-shaven" the same payload without "beard_free"; the fsig
    differs between the two and returns to the first value when "light stubble" is set again.
[6] _run_hairdeck with "light stubble": ONE render (the beard-free edit), ONE generate_hair call whose image is
    raw/<item>_<hsig>/beard_free.png; the job record says input "beard_free", input_sha256 = sha256 of that
    file, notes ["input_alpha", "Beard removed from the HairDeck input (the 2D look keeps it)"].
    hairdeck_image_path(input) = that file; hairdeck_panel input_source "beard_free". With "clean-shaven":
    hairdeck_image_path(input) = the profile picture, input_source "profile", and _run_hairdeck sends the
    profile picture with no render and record input "profile".
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


def sha(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


SIZE = 640
MASK = np.zeros((SIZE, SIZE), bool)
MASK[40:, 170:470] = True


def portrait(shade: int = 128) -> np.ndarray:
    img = np.full((SIZE, SIZE, 3), 255, np.uint8)
    img[MASK] = shade
    for y in range(40, 200):
        img[y, 170:470] = 0 if (y // 8) % 2 else 255
    return img


def beard_edit(img: np.ndarray) -> np.ndarray:
    out = img.astype(np.int16)
    out[360:561, 260:380] += 40
    return np.clip(out, 0, 255).astype(np.uint8)


def shift_down(values: np.ndarray, rows: int, fill) -> np.ndarray:
    out = np.empty_like(values)
    out[:rows] = fill
    out[rows:] = values[:-rows]
    return out


def save(img: np.ndarray, path: Path) -> Path:
    from PIL import Image
    Image.fromarray(img).save(path)
    return path


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="hairdeck-beard-") as tmp:
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

        from app.core import base_body, expression_regen, garment_beard as gb, garment_hair, garment_images, garments
        from app.core import garment_store as gs
        from app.core.keyed_lock import keyed_lock
        from app.imagegen import service
        from app.models.character import get_character_images_dir, get_character_profile, save_character_profile
        from PIL import Image

        # --- stubs -----------------------------------------------------------------
        RENDERS, HAIR_CALLS = [], []
        edit_mode = {"fn": beard_edit}

        def fake_render(character_name, *, output_stem, reference_image, override_width, override_height, **kw):
            RENDERS.append({"character": character_name, "w": override_width, "h": override_height, **kw})
            with Image.open(reference_image) as im:
                ref = np.asarray(im.convert("RGB"))
            out = Path(f"{output_stem}.png")
            save(edit_mode["fn"](ref), out)
            out.with_suffix(".json").write_text(json.dumps({"service": "Fake Qwen", "model": "fake-qwen"}))
            return out

        expression_regen.render_character_image = fake_render
        garment_images._mask = lambda path, size: MASK.copy()

        backend = SimpleNamespace(name="HairDeck", MEDIA_TYPE="mesh", category="img2hair", instance_enabled=True,
                                  effective_cost=0, extra_params={"input_steps": 30})

        class FakeService:
            pool = SimpleNamespace(backends=[backend])

            def generate_hair(self, image_path, output_dir, *, backend_glob="", character_name="", params=None,
                              hub_stage=None):
                seed = int((params or {}).get("seed"))
                HAIR_CALLS.append({"image": str(image_path), "seed": seed})
                files = []
                for name in (f"hair_seed{seed}_nohead.glb", f"hair_seed{seed}.glb", "info.json"):
                    path = Path(output_dir) / name
                    path.write_text(json.dumps({"ok": True, "notes": ["input_alpha"]}) if name == "info.json"
                                    else name)
                    files.append({"name": name})
                return {"files": files, "backend": "HairDeck", "route": {}, "job_id": "job"}

        service.get_image_service = lambda: FakeService()

        # --- [1] wording ------------------------------------------------------------
        print("[1] mentions_facial_hair")
        for text, want in [("light stubble", True), ("short beard", True), ("full beard", True), ("mustache", True),
                           ("bearded", True), ("a trimmed moustache", True), ("stubbly chin", True),
                           ("goatee", True), ("clean-shaven", False), ("no beard", False),
                           ("without a moustache", False), ("no visible beard", False),
                           ("short brunette hair", False), ("long sideburns", False), ("Beardsley", False)]:
            check(repr(text), gb.mentions_facial_hair(text), want)

        # --- [2] profiles -----------------------------------------------------------
        print("[2] facial_hair_texts")
        base = {"template": "human-roleplay", "age": 30, "height": 180,
                "body_slots": {"skin": {"tone": "light"}, "hair": {"length": "short", "color": "brown"}}}

        def prof(gender, style=None, appearance=""):
            p = json.loads(json.dumps(base))
            p.update(gender=gender, character_appearance=appearance)
            if style is not None:
                p["body_slots"]["facial_hair"] = {"style": style}
            return p

        check("save Probe", save_character_profile("Probe", prof("male"), create_new=True), True)
        check("male light stubble", gb.facial_hair_texts("Probe", profile=prof("male", "light stubble")),
              ["light stubble"])
        check("male clean-shaven", gb.facial_hair_texts("Probe", profile=prof("male", "clean-shaven")), [])
        check("female short beard (slot n/a)", gb.facial_hair_texts("Probe", profile=prof("female", "short beard")),
              [])
        check("appearance clause", gb.facial_hair_texts(
            "Probe", profile=prof("male", appearance="tall, a full beard, green eyes")), ["a full beard"])
        check("appearance denial", gb.facial_hair_texts(
            "Probe", profile=prof("male", appearance="no beard. short hair")), [])
        check("hsig_inputs stubble", gb.hsig_inputs("Probe", profile=prof("male", "light stubble")),
              {"beard_free": 1})
        check("hsig_inputs clean", gb.hsig_inputs("Probe", profile=prof("male", "clean-shaven")), {})

        # --- [3] gate ---------------------------------------------------------------
        print("[3] beard_gate")
        src = portrait()
        check("head_frame", gb.head_frame(MASK), {"y0": 40.0, "width": 300.0, "cx": 319.5})
        a = gb.beard_gate(src, MASK, beard_edit(src), MASK)
        check("a ok", a["ok"], True)
        check("a outside / xor / pool / nose", (a["outside_dRGB"], a["upper_xor"], a["pool"], a["zone"]["nose_row"]),
              (0.0, 0.0, 2, 304))
        check("a beard_dRGB in 12.5..16", 12.5 <= a["beard_dRGB"] <= 16.0, True)
        b = gb.beard_gate(src, MASK, shift_down(beard_edit(src), 8, 255), shift_down(MASK, 8, False))
        check("b refused", b["ok"], False)
        check("b xor", b["upper_xor"], 0.0303)
        check("b reasons", [r.split(" (")[0] for r in b["reasons"]],
              ["face or hair outside the beard changed", "head outline changed"])
        c = gb.beard_gate(src, MASK, src, MASK)
        check("c reasons", c["reasons"], ["beard not removed (ΔRGB 0.0 < 4.0)"])

        # --- [4] edit + cache -------------------------------------------------------
        print("[4] beard_free_input")
        check("prompt", gb.PROMPT, "Keep the image exactly as it is. Remove the beard; the chin and cheeks are "
                                   "clean-shaven.")
        pics = root / "pics"
        pics.mkdir()
        p1 = save(src, pics / "p1.png")
        job = root / "job"
        check("cached before", gb.cached(job, p1), None)
        sent, record = gb.beard_free_input("Probe", p1, job)
        check("sent", sent, job / gb.RESULT_NAME)
        check("renders 1", len(RENDERS), 1)
        call = RENDERS[0]
        check("render call", (call["bare_prompt"], call["extra_negative"], call["occasion"], call["image_use_case"],
                              call["character_loras"], call["postprocess"], call["w"], call["h"]),
              (gb.PROMPT, "beard, moustache, stubble", "garment_view", "garment_edit", False, False, 640, 640))
        check("record", (record["accepted"], record["version"], record["source_sha256"], record["attempt"]),
              (True, 1, sha(p1), 1))
        sent2, _ = gb.beard_free_input("Probe", p1, job)
        check("cache hit: no render", (len(RENDERS), sent2), (1, job / gb.RESULT_NAME))
        p2 = save(portrait(120), pics / "p2.png")
        check("other picture: not cached", gb.cached(job, p2), None)
        edit_mode["fn"] = lambda img: img
        sent3, rec3 = gb.beard_free_input("Probe", p2, job)
        check("no-op edits: renders", len(RENDERS), 1 + gb.ATTEMPTS)
        check("refused -> source", (sent3, rec3["accepted"], len(rec3["attempts"])), (p2, False, 2))
        check("refused note", gb.note(rec3).startswith("Beard removal refused"), True)
        edit_mode["fn"] = beard_edit

        # --- [5] fingerprint --------------------------------------------------------
        print("[5] hsig / fsig")
        check("create Demo", save_character_profile("Demo", prof("male", "light stubble"), create_new=True), True)
        images = get_character_images_dir("Demo")
        images.mkdir(parents=True, exist_ok=True)
        demo_pic = save(src, images / "Demo_1.png")

        def set_profile(**values):
            with keyed_lock("character_profile", "Demo"):
                stored = get_character_profile("Demo")
                for key, value in values.items():
                    if key == "facial_hair":
                        stored.setdefault("body_slots", {})["facial_hair"] = {"style": value}
                    else:
                        stored[key] = value
                check(f"profile {sorted(values)}", save_character_profile("Demo", stored), True)

        set_profile(profile_image="Demo_1.png", hair_method="hairdeck")
        base_body.set_pipeline("Demo", True)
        hid = garment_hair.ensure_hair_item("Demo")

        def md5(payload):
            return hashlib.md5(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                          default=str).encode("utf-8")).hexdigest()[:12]

        plain = {"profile_image": sha(demo_pic), "extra_params": {"input_steps": 30}, "version": 1}
        h_beard = gs.garment_hsig("Demo", hid)
        check("hsig with stubble", h_beard, md5({**plain, "beard_free": 1}))
        f_beard = gs.garment_fsig("Demo", hid)
        set_profile(facial_hair="clean-shaven")
        h_clean = gs.garment_hsig("Demo", hid)
        check("hsig clean-shaven", h_clean, md5(plain))
        check("fsig changes", gs.garment_fsig("Demo", hid) != f_beard, True)
        set_profile(facial_hair="light stubble")
        check("fsig back", gs.garment_fsig("Demo", hid), f_beard)

        # --- [6] the HairDeck job ---------------------------------------------------
        print("[6] _run_hairdeck")
        renders0 = len(RENDERS)
        profile = get_character_profile("Demo")
        folder = garments._run_hairdeck("Demo", hid, h_beard, profile, 1, 42)
        check("job folder", folder, gs.hairdeck_dir("Demo", hid, h_beard))
        check("one edit render", len(RENDERS) - renders0, 1)
        check("generate_hair image", HAIR_CALLS[-1]["image"], str(folder / gb.RESULT_NAME))
        rec = gs.read_record(folder / gs.HAIRDECK_RECORD)
        check("record input", (rec["input"], rec["input_sha256"], rec["accepted"]),
              ("beard_free", sha(folder / gb.RESULT_NAME), True))
        check("record notes", rec["notes"], ["input_alpha", "Beard removed from the HairDeck input (the 2D look keeps it)"])
        check("image path input", garments.hairdeck_image_path("Demo", hid, "input"), folder / gb.RESULT_NAME)
        check("panel input_source", garments.hairdeck_panel("Demo", hid)["input_source"], "beard_free")
        set_profile(facial_hair="clean-shaven")
        check("clean: image path input", garments.hairdeck_image_path("Demo", hid, "input"), demo_pic)
        check("clean: panel input_source", garments.hairdeck_panel("Demo", hid)["input_source"], "profile")
        renders1 = len(RENDERS)
        folder2 = garments._run_hairdeck("Demo", hid, h_clean, get_character_profile("Demo"), 1, 42)
        check("clean: no render, sends the picture", (len(RENDERS) - renders1, HAIR_CALLS[-1]["image"]),
              (0, str(demo_pic)))
        check("clean: record input", gs.read_record(folder2 / gs.HAIRDECK_RECORD)["input"], "profile")

    print("\nALL OK" if not FAILS else f"\nFAILED: {FAILS}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
