#!/usr/bin/env python3
"""Worn gate version 2 of an own-mesh garment (app/core/garment_gates.py
``worn_gate`` / ``head_zone`` / ``WORN_GATE_VERSION``, garment_clothing.py
``GATE_VERSIONS``, garment_images.py ``_regate_stored``).

Why: Kai's "Black Lederjacket" (2026-11-10) — a correct fitted jacket back
was refused twice: "body outside the garment changed colour: 10.3 >= 8.0;
head changed: 0.088 of the head > 0.05". The edit model tints the skin
warmer, a colour that never reaches the mesh (worn -> ghost -> mesh -> CPU
fit); and the head zone ended at the chin row y0 + 0.13·Hb, under which the
stand-up collar at the nape of a BACK view still lies. Version 2: the colour
is recorded, never refused; the head zone ends at the neck's narrowest row;
the outline check is unchanged; a refused worn view re-gates its stored
attempts of an older version before anything renders again.

Usage:
    ./.venv/bin/python scripts/smoke_garment_worn_regate.py

Throwaway storage + instance, a copy of the ``human`` package; no world, no
hub, no GPU, no server. REAL: the gates, run_edit_step, garments.run_garment.
Stubbed: the renderer (records every call; a draft or fit renders COLLAR,
a ghost renders nothing), ``character.run_rembg`` (every pixel more than
2 away from grey 128 is figure), ``get_image_service`` (raises: no image job
may reach it).

Fixture, W 1024 x H 1200 on grey 128, skin (200, 160, 140):
  BASE = head disc centre (512, 160) r 60 (rows 100..220) + neck cols
         [487, 537) rows [190, 280) (50 px) + torso cols [392, 632) rows
         [280, 1100) (240 px) -> y0 100, Hb 999; chin row int(100 + 0.13 x
         999) = 229, shoulder row int(100 + 0.19 x 999) = 289; smoothing
         window round(0.005 x 999) = 5 rows.
  Row widths (mask px): the disc chord 2·floor(sqrt(3600 - d²)) + 1, d =
         row - 160, joined with the neck's x - 512 in [-25, 24]: rows <= 214
         the chord covers the neck (d <= 54: sqrt(3600 - 2916) = 26.2 >= 25)
         — row 211: 63, 212: 59, 213: 57, 214: 53 (hw 26); row 215 (hw 23):
         -25..24 = 50; rows 215..279: 50; rows >= 280: 240.
  5-row means: s(215) = (57 + 53 + 50 + 50 + 50) / 5 = 52.0, s(216) = (53 +
         4 x 50) / 5 = 50.6, s(217..277) = 50, s(289) = 240. Head's widest
         row in rows 100..228: the 5-row windows holding row 160 (121 px;
         d = ±1..±4: hw 59 -> 119) mean (4 x 119 + 121) / 5 = 119.4; the
         first is row 158. Narrowest between 158 and 289: 50. Clear neck: 50
         <= 0.85 x 119.4 = 101.5 and 240 >= 1.25 x 50 = 62.5. First row with
         s <= 50 x 1.02 = 51.0: row 216 (s(215) = 52.0 > 51.0) -> head zone =
         figure rows < 216, rule "neck", t = (216 - 100) / 999 = 0.1161 —
         13 rows above the chin row 229.
  Head area A = the disc rows 100..215 (d = -60..55) Σ (2·floor(sqrt(3600 -
         d²)) + 1) = 11156 + the neck's 3 px outside the chord on row 215
         (x - 512 = -25, -24, 24) = 11159.
  JACKET(r) = BASE with the torso rows [280, 700) and the neck rows [r, 280)
         in black (20, 20, 20): |ΔRGB| to skin (180 + 140 + 120) / 3 = 146.7
         > 20 -> the garment region; the figure outline is unchanged (XOR 0).
  COLLAR = JACKET(216): a collar up the neck that starts ON the neck row —
         the zone is the rows above it -> head_garment 0.0 -> accepted (the
         chin-row zone held rows 216..228 of it, 13 x 50 = 650 px).
  HIGH   = JACKET(196): 20 rows of the collar in the zone, 20 x 50 = 1000 px
         minus the region opening's cut corners (3 px at each top corner of
         the band, a 2-iteration cross opening) = 994 -> head_garment 994 /
         11159 = 0.0891 > 0.05 -> refused "head changed: 0.089 of the head".
  TINTED = COLLAR with every other figure pixel (230, 166, 128): |ΔRGB|
         (30 + 6 + 12) / 3 = 16.0 (< 20: not garment, >= the old 8.0) ->
         outside_dRGB 16.0 recorded, ok True, no reasons.
  NO_NECK = the disc + torso of smoke_garment_clothing_images.py (disc
         (512, 200) r 100, torso cols [392, 632) rows [300, 1100)): the disc
         narrows down to the shoulder row 289 (still in the disc) -> its 5-row
         mean there is the narrowest and the shoulder row is not wider ->
         rule "chin", row 229, t (229 - 100) / 999 = 0.1291.

[1] head_zone + gate numbers as derived above; limits("clothing") worn has
    no outside_dRGB limit (its chip is information); every worn record
    carries gate_version 2; GATE_VERSIONS["worn"] = WORN_GATE_VERSION = 2.
[2] Drafted back, the next chain run (garments.run_garment, no steps): the
    worn front is accepted (COLLAR, record of the current gate), the back has
    two stored fit attempts — try1 HIGH, try2 TINTED — with version-1 records
    (no gate_version, refused for colour), fitted from the current front
    (front_sha256). The run re-gates them: try1 refused "head changed",
    try2 accepted -> the final back = try2's file, attempt 2, gates.first
    refused / gates.second ok with regated_from 1, gate_version 2; the final
    record keeps front_sha256 / draft / draft_sha256 of try2. No worn render,
    no draft, no image service call; the run goes on to the ghost (the stub
    renders nothing there -> refused at "ghost"; the persisted failure is the
    ghost's, no longer the worn one).
[3] Regenerate (steps "worn", view "back", force) on the same staging:
    the same re-gate, no worn render.
[4] Stored attempts fitted from ANOTHER front (front_sha256 differs): not
    re-gated -> draft + fit render ("worn bd", "worn b1"; the fit = COLLAR,
    accepted, no regated_from).
[5] Stored attempts of the CURRENT version, refused: no re-gate — Regenerate
    renders ("worn bd", "worn b1").
[6] Worn FRONT (an edit, not drafted): try1 TINTED with a version-1 record,
    no final -> run_edit_step accepts it with no render, regated_from 1.
"""
import io
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

FAILS = []
GREY = (128, 128, 128)
SKIN = (200, 160, 140)
BLACK = (20, 20, 20)
TINT = (230, 166, 128)
W, H = 1024, 1200
OLD_REASON = "body outside the garment changed colour: 16.0 >= 8.0"


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


def png(arr) -> bytes:
    from PIL import Image
    out = io.BytesIO()
    Image.fromarray(arr).save(out, format="PNG")
    return out.getvalue()


def mask_of(rgb):
    return (np.abs(rgb.astype(np.int16) - 128) > 2).any(2)


def canvas():
    rgb = np.zeros((H, W, 3), dtype=np.uint8)
    rgb[:] = GREY
    return rgb


def base():
    rgb = canvas()
    yy, xx = np.mgrid[0:H, 0:W]
    rgb[(xx - 512) ** 2 + (yy - 160) ** 2 <= 60 ** 2] = SKIN
    rgb[190:280, 487:537] = SKIN
    rgb[280:1100, 392:632] = SKIN
    return rgb


def jacket(r):
    rgb = base()
    rgb[280:700, 392:632] = BLACK
    rgb[r:280, 487:537] = BLACK
    return rgb


BASE = base()
COLLAR = jacket(216)
HIGH = jacket(196)
TINTED = COLLAR.copy()
TINTED[mask_of(BASE) & ~(COLLAR == BLACK).all(2)] = TINT
NO_NECK = canvas()
_yy, _xx = np.mgrid[0:H, 0:W]
NO_NECK[(_xx - 512) ** 2 + (_yy - 200) ** 2 <= 100 ** 2] = SKIN
NO_NECK[300:1100, 392:632] = SKIN


def rembg_stub(data, model="u2net", **kwargs):
    from PIL import Image
    with Image.open(io.BytesIO(data)) as im:
        rgb = np.asarray(im.convert("RGB"))
    mask = (mask_of(rgb) * 255).astype(np.uint8)
    return png(mask) if kwargs.get("only_mask") else png(np.dstack([rgb, mask]))


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="garment-regate-") as tmp:
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

        from app.core import base_body, expression_regen, garment_assembly, garment_clothing, garment_images
        from app.core import garment_mesh, garments
        from app.core import garment_gates as gg
        from app.core import garment_store as gs
        from app.imagegen import service as imgservice
        from app.models import character as charmod
        from app.models import inventory
        from app.models.character import get_character_dir, save_character_profile
        garment_assembly.schedule = lambda *a, **k: False
        charmod.run_rembg = rembg_stub
        jobs = []

        def no_image_job(*a, **k):
            jobs.append(a)
            raise AssertionError("no image job in this smoke")
        imgservice.get_image_service = no_image_job

        print("[1] head zone + gate")
        check("neck zone", gg.head_zone(mask_of(BASE)), {"row": 216, "rule": "neck", "t": 0.1161})
        check("no neck: chin row", gg.head_zone(mask_of(NO_NECK)), {"row": 229, "rule": "chin", "t": 0.1291})

        def worn(arr, view="back"):
            return gg.worn_gate(BASE, mask_of(BASE), arr, mask_of(arr), view=view)
        collar = worn(COLLAR)
        check("collar under the neck row: no head change",
              (collar["ok"], collar["head_garment"], collar["head_rule"], collar["head_row_t"], collar["reasons"]),
              (True, 0.0, "neck", 0.1161, []))
        high = worn(HIGH)
        check("band above the neck row: refused", (high["ok"], high["head_garment"], high["reasons"]),
              (False, round(994 / 11159, 4), ["head changed: 0.089 of the head > 0.05"]))
        tinted = worn(TINTED)
        check("tinted body: recorded, no colour refusal",
              (tinted["ok"], tinted["outside_dRGB"], tinted["outside_xor"], tinted["head_garment"], tinted["reasons"]),
              (True, 16.0, 0.0, 0.0, []))
        check("record version", (collar["gate_version"], gg.WORN_GATE_VERSION,
                                 garment_clothing.GATE_VERSIONS["worn"]), (2, 2, 2))
        check("no colour limit (chip is information)", "outside_dRGB" in gg.limits("clothing")["worn"], False)
        check("outline limit unchanged", gg.limits("clothing")["worn"]["outside_xor"]["value"], 0.015)

        human = {"template": "human-roleplay", "gender": "male", "age": 30, "height": 180,
                 "character_appearance": "slender",
                 "body_slots": {"skin": {"tone": "light"}, "eyes": {"color": "blue"},
                                "build": {"type": "athletic"}}}
        check("create Demo", save_character_profile("Demo", human, create_new=True), True)
        check("pipeline Demo", base_body.set_pipeline("Demo", True), True)
        jid = inventory.add_item(name="Black Jacket", category="outfit_piece",
                                 prompt_fragment="a black leather jacket with a stand-up collar",
                                 outfit_piece={"slots": ["outer"], "outfit_types": ["casual"], "own_mesh": True})["id"]
        check("inventory", inventory.add_to_inventory("Demo", jid), True)
        refs = get_character_dir("Demo") / "model_refs"
        refs.mkdir(parents=True, exist_ok=True)
        bsig = base_body.base_signature("Demo")
        for v in base_body.BASE_VIEWS:
            stem = f"tpose_{bsig}" if v == "front" else f"tpose_{v}_{bsig}"
            (refs / f"{stem}.png").write_bytes(png(BASE))
            (refs / f"{stem}.json").write_text(json.dumps({"base_signature": bsig}))
        fsig = gs.garment_fsig("Demo", jid)

        renders = []

        def recorder(character_name, *, output_stem, **kw):
            g = kw["sidecar_extra"]["garment"]
            key = f"{g['step']} {g['view'][0]}{g.get('attempt', 'd')}"
            renders.append(key)
            if g["step"] == "ghost":
                return None  # the steps after the worn view are not under test
            if g.get("stage") == "draft":
                out = COLLAR  # a fresh render: its own frame
            else:
                arr = COLLAR  # every fit renders the jacket back
                out = np.full((kw["override_height"], kw["override_width"], 3), 128, dtype=np.uint8)
                dy, dx = (out.shape[0] - arr.shape[0]) // 2, (out.shape[1] - arr.shape[1]) // 2
                out[dy:dy + arr.shape[0], dx:dx + arr.shape[1]] = arr
            path = Path(str(output_stem) + ".png")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(png(out))
            path.with_suffix(".json").write_text(json.dumps(kw["sidecar_extra"]))
            return path

        expression_regen.render_character_image = recorder
        garment_mesh.generate = lambda *a, **k: None
        garments._fit = lambda *a, **k: None

        def image(step, view, attempt=0):
            return gs.garment_path("Demo", jid, fsig, "image", step=step, view=view, attempt=attempt)

        front = image("worn", "front")
        draft_name = garment_images.draft_path("Demo", jid, fsig, "worn").name

        def stage(backs, *, front_sha=None, version=None):
            """The accepted worn front + stored back attempts (no final back)."""
            front.parent.mkdir(parents=True, exist_ok=True)
            front.write_bytes(png(COLLAR))
            gs.write_record(front.with_suffix(".json"), {"accepted": True, "attempt": 1,
                                                         "gates": {"first": {**worn(COLLAR, "front"), "attempt": 1}}})
            sha = front_sha or base_body.file_sha256(front)
            for path in (image("worn", "back"), image("worn", "back").with_suffix(".json")):
                path.unlink(missing_ok=True)
            for n, arr in enumerate(backs, 1):
                target = image("worn", "back", n)
                target.write_bytes(png(arr))
                old = {k: v for k, v in worn(arr).items() if k != "gate_version"}
                old.update(ok=False, reasons=[OLD_REASON], attempt=n)
                if version is not None:
                    old["gate_version"] = version
                gs.write_record(target.with_suffix(".json"), {
                    "garment": {"item_id": jid, "fsig": fsig, "step": "worn", "view": "back", "attempt": n,
                                "stage": "fit"},
                    "front_sha256": sha, "draft": draft_name, "draft_sha256": "d" * 64, "gate": old})
            gs.record_failure("Demo", jid, fsig, step="worn", error="worn back refused — attempt 1: " + OLD_REASON)

        def check_regated(label):
            back = image("worn", "back")
            record = gs.read_record(back.with_suffix(".json"))
            first, second = (record.get("gates") or {}).get("first") or {}, (record.get("gates") or {}).get("second") or {}
            check(f"{label}: back accepted from try2", (record.get("accepted"), record.get("attempt"),
                                                        back.read_bytes() == image("worn", "back", 2).read_bytes()),
                  (True, 2, True))
            check(f"{label}: try1 refused for the head, try2 ok",
                  (first.get("ok"), first.get("reasons"), first.get("regated_from"),
                   second.get("ok"), second.get("regated_from"), second.get("gate_version"), second.get("outside_dRGB")),
                  (False, ["head changed: 0.089 of the head > 0.05"], 1, True, 1, 2, 16.0))
            check(f"{label}: follows the front", (record.get("front_sha256"), record.get("draft"),
                                                  record.get("draft_sha256")),
                  (base_body.file_sha256(front), draft_name, "d" * 64))
            check(f"{label}: try sidecar rewritten",
                  (gs.read_record(image("worn", "back", 1).with_suffix(".json"))["gate"].get("gate_version"),
                   gs.read_record(image("worn", "back", 2).with_suffix(".json"))["gate"].get("ok")), (2, True))

        print("[2] next chain run re-gates the stored back")
        stage([HIGH, TINTED])
        res = garments.run_garment("Demo", jid)
        check("no worn render, no image job", ([k for k in renders if k.startswith("worn")], jobs), ([], []))
        check("run goes on to the ghost", (res.get("ok"), res.get("step")), (False, "ghost"))
        check_regated("run")
        check("failure is the ghost's now", gs.chain_failure("Demo", jid, fsig).get("step"), "ghost")

        print("[3] Regenerate re-gates first")
        del renders[:]
        stage([HIGH, TINTED])
        res = garments.run_garment("Demo", jid, steps="worn", view="back", force=True)
        check("no worn render", ([k for k in renders if k.startswith("worn")], jobs), ([], []))
        check_regated("regenerate")

        print("[4] attempts of another front are not re-gated")
        del renders[:]
        stage([HIGH, TINTED], front_sha="0" * 64)
        res = garments.run_garment("Demo", jid, steps="worn", view="back", force=True)
        check("draft + fit rendered", [k for k in renders if k.startswith("worn")], ["worn bd", "worn b1"])
        record = gs.read_record(image("worn", "back").with_suffix(".json"))
        check("fresh fit accepted", (record.get("accepted"), record.get("attempt"),
                                     "regated_from" in (record.get("gates") or {}).get("first", {})), (True, 1, False))

        print("[5] current-version refusals render again")
        del renders[:]
        stage([HIGH, TINTED], version=2)
        res = garments.run_garment("Demo", jid, steps="worn", view="back", force=True)
        check("draft + fit rendered", [k for k in renders if k.startswith("worn")], ["worn bd", "worn b1"])

        print("[6] worn front (an edit) re-gates too")
        del renders[:]
        for path in (front, front.with_suffix(".json")):
            path.unlink(missing_ok=True)
        try1 = image("worn", "front", 1)
        try1.write_bytes(png(TINTED))
        old = {k: v for k, v in worn(TINTED, "front").items() if k != "gate_version"}
        gs.write_record(try1.with_suffix(".json"), {"gate": {**old, "ok": False, "reasons": [OLD_REASON], "attempt": 1}})
        image("worn", "front", 2).unlink(missing_ok=True)
        got = garment_images.run_edit_step("Demo", jid, fsig, "worn", "front")
        record = gs.read_record(front.with_suffix(".json"))
        first = (record.get("gates") or {}).get("first") or {}
        check("front accepted without a render", (got == front, renders, record.get("accepted"),
                                                  record.get("attempt"), first.get("ok"), first.get("regated_from")),
              (True, [], True, 1, True, 1))

    print("\nFAILED: " + ", ".join(FAILS) if FAILS else "\nall passed")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
