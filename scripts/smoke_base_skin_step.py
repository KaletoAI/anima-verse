#!/usr/bin/env python3
"""The skin detail step of the base front (app/core/base_skin.py; spike
claude-out/kai-base-skin/edit-step/).

Usage:
    ./.venv/bin/python scripts/smoke_base_skin_step.py

Runs against a THROWAWAY storage + instance directory — no world, no hub, no
GPU, no matte model, no server. The edit render
(``expression_regen.render_character_image``) and the matte
(``app.models.character.run_rembg``) are stubs.

Expected numbers, by hand:

[A] ``frequency_transfer`` on a synthetic figure, 200 x 400 px: a head disc
    (centre (100, 40), radius 22) on a body rectangle (x 60..139, y 60..379),
    flat colour (200, 160, 140), transparent elsewhere. Figure top 18, height
    362; head row 18 + int(0.05 * 362) = 36, its run x 79..121 -> centre 100,
    half width 21; face box y 14 .. 18 + int(0.115 * 362) + int(0.03 * 400)
    = 71, x 100 - 26 = 74 .. 126.
    [A1] fine noise transfers: the edit = the neutral + white noise sigma 10
         (one value per pixel, R = G = B, seed 1). The neutral is flat, so the
         output's change is the edit's high-pass: noise minus its Gaussian
         blur at sigma 3. For white noise var(n - g*n) = sigma^2 (1 - 2 g(0)
         + sum g^2), g(0) = 1/(2 pi 9) = 0.01768, sum g^2 = 1/(4 pi 9) =
         0.00884 -> std ratio sqrt(0.9735) = 0.987. The guard never fires:
         the noise's L* band (G3 - G15) has std ~ 0.09 x its L* std (~4 L*),
         far under 3 L*. In the body interior (x 80..119, y 120..359, >= 20 px
         from every edge and the face, feather weight ~1): std(out - neutral)
         / std(edit - neutral) in [0.95, 1.0].
    [A2] a new blob larger than sigma does not transfer: the edit = the
         neutral with a disc of radius 8 at (100, 220) darker by 40 on R, G
         and B (L* 15 darker). Its band (G3 - G15 of L*) departs by
         15 x (1 - e^(-64/18)) - 15 x (1 - e^(-64/450)) = 12.7 L* at the
         centre and > 3 L* out to r ~ 9, so the guard drops r <= ~9 + 6 =
         15; the feather (sigma 4) leaves a weight <= Phi(-(15 - 6)/4) =
         0.012 at r <= 6 -> |out - neutral| <= 40 x 0.012 = 0.5 there (max
         <= 1 after rounding). Only the rim's own high-pass leaks at a
         weight <= Phi(-7/4) = 0.04 — sub-sigma, no shape: the output's band
         departs by <= 5 % of the edit's 12.7 L*. Without the guard
         (``SKIN_GUARD_DL`` = inf) the disc's own high-pass comes through:
         max >= 10.
    [A3] the protected face is unchanged: with the [A1] noise, inside the
         face box AND the figure, both shrunk by 12 px (feather weight <=
         Phi(-12/4) = 0.0013, noise high-pass <= ~45 -> < 0.1): max |out -
         neutral| <= 1 (rounding). The alpha of ``transfer_detail``'s result
         is the neutral's, byte for byte.
    [A4] ``transfer_detail`` registers: the [A1] edit shifted by (+3, +2) px
         (alpha too) comes back with registration scale 1.0, dx -3, dy -2;
         an edit whose figure is a different shape (the body 30 px wide
         instead of 80: 1520 + 9600 of 1520 + 25600 px, the disc's overlap
         with the rectangle counted once -> IoU ~0.41 < 0.9) -> ValueError,
         the step is refused.
[B] the fingerprint: ``base_character`` / ``base_prompt`` stubbed to fixed
    texts; switch OFF -> md5 of exactly ``{view: [character, prompt,
    negative]}`` (the fingerprint of a base without the step); switch ON ->
    another value, and a male profile (body hair clause) gives another one
    than a female; OFF, male and female are equal.
[C] the fallback: ``after_front_render`` on a stored front (100 x 300,
    the [A] figure scaled) with the switch ON —
    [C1] the edit raises ``BackendBusyError`` -> the front's bytes unchanged,
         ``skin_step`` {applied False, outcome "busy"}, the neutral copy
         stored (same bytes); the function returns the front.
    [C2] the edit raises RuntimeError -> outcome "failed"; returns None ->
         "failed" with "the edit rendered nothing".
    [C3] switch OFF -> no edit call, no neutral file, outcome "off".
    [C4] a landing edit (stub: the padded reference + noise sigma 10; matte
         stub: the neutral alpha at the centred pad position) -> ONE call,
         occasion "outfit_front", use case "outfit_edit", postprocess False,
         the size ``_tpose_size()``, prompt ``skin_prompt`` (a female: no
         body hair clause); the front changed, its alpha unchanged; the
         neutral copy = the old front; record applied, registration (1.0, 0,
         0), the edit's ``final_prompt`` recorded.
[D] cost: ``base_rebuild_steps`` of a plan with all four views and no model
    -> view front, skin front, view back, view left, view right = 5 hub jobs
    with the switch ON, 4 without (the skin step is one image edit).
[E] ``ImageBackend.generate`` writes the prompt the engine received into the
    caller's ``log_meta["final_prompt"]`` (no LoRA, no fold: the prompt as
    sent) — the image meta's source.

Fails on 136313bb: there is no app/core/base_skin.py, base_body has no "skin
front" step, and ImageBackend.generate never writes ``final_prompt`` back.
"""
import hashlib
import io
import json
import math
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS = []
OLD = "136313bb"


def check(label, got, want=True):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}" + ("" if ok else f" — expected {want!r}"))
    if not ok:
        FAILS.append(label)


def baseline_proof():
    print(f"[0] fails on {OLD}")
    gone = subprocess.run(["git", "cat-file", "-e", f"{OLD}:app/core/base_skin.py"], cwd=ROOT,
                          capture_output=True).returncode != 0
    check("no base_skin.py", gone)
    body = subprocess.run(["git", "show", f"{OLD}:app/core/base_body.py"], cwd=ROOT, capture_output=True,
                          text=True).stdout
    check("no skin front step", bool(body) and "skin front" not in body)
    backend = subprocess.run(["git", "show", f"{OLD}:app/imagegen/base.py"], cwd=ROOT, capture_output=True,
                             text=True).stdout
    check("no final_prompt write-back", bool(backend) and 'log_meta["final_prompt"]' not in backend)


SKIN = (200, 160, 140)


def figure(width=200, height=400, *, body=(60, 140), disc=((100, 40), 22), rect_rows=(60, 380)):
    yy, xx = np.mgrid[0:height, 0:width]
    (cx, cy), r = disc
    mask = (xx - cx) ** 2 + (yy - cy) ** 2 <= r * r
    mask |= (xx >= body[0]) & (xx < body[1]) & (yy >= rect_rows[0]) & (yy < rect_rows[1])
    rgb = np.zeros((height, width, 3), dtype=np.float64) + 128.0
    rgb[mask] = SKIN
    return rgb, mask


def noise(shape, sigma=10.0, seed=1):
    n = np.random.default_rng(seed).normal(0.0, sigma, shape[:2])
    return np.repeat(n[..., None], 3, axis=2)


def rgba(rgb, mask):
    from PIL import Image
    im = Image.fromarray(np.clip(rgb, 0, 255).round().astype(np.uint8), "RGB")
    im.putalpha(Image.fromarray((mask * 255).astype(np.uint8), "L"))
    return im


def section_transfer():
    from scipy import ndimage
    from app.core import base_skin as s
    print("[A] the transfer")
    neutral, mask = figure()
    face = s.face_region(mask)
    rows, cols = np.where(face.any(1))[0], np.where(face.any(0))[0]
    check("face box", (int(rows[0]), int(rows[-1]) + 1, int(cols[0]), int(cols[-1]) + 1), (14, 71, 74, 126))

    n = noise(neutral.shape)
    edit = neutral + n
    out, rec = s.frequency_transfer(neutral, edit, mask, mask)
    inner = (slice(120, 360), slice(80, 120))
    ratio = float((out - neutral)[inner].std() / (edit - neutral)[inner].std())
    print(f"       [A1] std ratio {ratio:.4f} (by hand 0.987), guarded share {rec['guarded_share']}")
    check("[A1] fine noise transfers", 0.95 <= ratio <= 1.0)

    yy, xx = np.mgrid[0:mask.shape[0], 0:mask.shape[1]]
    disc = (xx - 100) ** 2 + (yy - 220) ** 2 <= 64
    blob = neutral.copy()
    blob[disc] -= 40.0
    out, _rec = s.frequency_transfer(neutral, blob, mask, mask)
    centre = (xx - 100) ** 2 + (yy - 220) ** 2 <= 36
    check("[A2] blob centre unchanged (max |diff|, r <= 6)", int(np.abs(out.round() - neutral)[centre].max()) <= 1)
    band_n = s._band(s._lstar(neutral))
    depth_edit = float(-(s._band(s._lstar(blob)) - band_n).min())
    depth_out = float(np.abs(s._band(s._lstar(out)) - band_n).max())
    print(f"       [A2] band departure edit {depth_edit:.2f} L* (by hand 12.7), output {depth_out:.2f} L*")
    check("[A2] the blob's shape does not transfer", depth_out <= 0.05 * depth_edit)
    guard = s.SKIN_GUARD_DL
    try:
        s.SKIN_GUARD_DL = math.inf
        raw, _rec = s.frequency_transfer(neutral, blob, mask, mask)
    finally:
        s.SKIN_GUARD_DL = guard
    check("[A2] without the guard it would", float(np.abs(raw - neutral)[disc].max()) >= 10)

    out, _rec = s.frequency_transfer(neutral, edit, mask, mask)
    core = ndimage.binary_erosion(face & mask, iterations=12)
    check("[A3] face core not empty", bool(core.sum() > 50))
    check("[A3] face unchanged (max |diff|)", int(np.abs(out.round() - neutral)[core].max()) <= 1)
    neutral_im = rgba(neutral, mask)
    detailed, rec = s.transfer_detail(neutral_im, rgba(edit, mask))
    check("[A3] alpha is the neutral's", detailed.getchannel("A").tobytes() == neutral_im.getchannel("A").tobytes())

    shifted = np.roll(np.roll(edit, 2, axis=0), 3, axis=1)
    smask = np.roll(np.roll(mask, 2, axis=0), 3, axis=1)
    _img, rec = s.transfer_detail(neutral_im, rgba(shifted, smask))
    check("[A4] registration", (rec["registration"]["scale"], rec["registration"]["dx"], rec["registration"]["dy"]),
          (1.0, -3, -2))
    thin, tmask = figure(body=(85, 115))
    try:
        s.transfer_detail(neutral_im, rgba(thin, tmask))
        check("[A4] another silhouette refused", False)
    except ValueError as e:
        check("[A4] another silhouette refused", "silhouette" in str(e))


def set_switch(config, paths, on):
    paths.get_config_path().write_text(json.dumps({"base_body": {"skin_detail_step": on}}))
    config.load(paths.get_config_path(), instance_path=paths.get_instance_dir() / "config.json")


def section_fingerprint(config, paths):
    from app.core import base_body
    print("[B] the fingerprint")
    real = base_body.base_character, base_body.base_prompt
    base_body.base_character = lambda name, view, profile=None: "block" if view == "front" else None
    base_body.base_prompt = lambda name, view, profile=None: (f"prompt {view}", "negative")
    try:
        male, female = {"gender": "male"}, {"gender": "female"}
        set_switch(config, paths, False)
        plain = {v: ["block" if v == "front" else None, f"prompt {v}", "negative"] for v in base_body.BASE_VIEWS}
        want = hashlib.md5(json.dumps(plain, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:12]
        off_m = base_body.prompt_fingerprint("X", profile=male)
        off_f = base_body.prompt_fingerprint("X", profile=female)
        check("off = the fingerprint without the step", off_m, want)
        check("off: male = female", off_f, off_m)
        set_switch(config, paths, True)
        on_m = base_body.prompt_fingerprint("X", profile=male)
        on_f = base_body.prompt_fingerprint("X", profile=female)
        check("on changes the fingerprint", on_m != off_m and on_f != off_f)
        check("on: male (body hair) != female", on_m != on_f)
    finally:
        base_body.base_character, base_body.base_prompt = real


def section_fallback(config, paths, root):
    from PIL import Image
    from app.core import base_skin, expression_regen
    from app.core.model_refs import _tpose_size
    from app.imagegen.base import BackendBusyError
    import app.models.character as character
    print("[C] the fallback and the landing edit")
    refs = root / "refs"
    refs.mkdir()
    front = refs / "tpose_base12345678.png"
    neutral_rgb, nmask = figure(100, 300, body=(30, 70), disc=((50, 30), 16), rect_rows=(44, 290))
    original = rgba(neutral_rgb, nmask)
    calls = []
    mode = {"m": "busy"}
    pad_mask = {}

    def stub(character_name, *, output_stem, **kw):
        calls.append(kw)
        if mode["m"] == "busy":
            raise BackendBusyError("Fake is busy")
        if mode["m"] == "error":
            raise RuntimeError("backend broke")
        if mode["m"] == "none":
            return None
        with Image.open(kw["reference_image"]) as im:
            ref = np.asarray(im.convert("RGB"), dtype=np.float64)
        w, h = kw["override_width"], kw["override_height"]
        x0, y0 = (w - 100) // 2, (h - 300) // 2
        m = np.zeros((h, w), dtype=bool)
        m[y0:y0 + 300, x0:x0 + 100] = nmask
        pad_mask["m"] = m
        out = output_stem.with_suffix(".png")
        Image.fromarray(np.clip(ref + noise(ref.shape, seed=2), 0, 255).round().astype(np.uint8)).save(out)
        out.with_suffix(".json").write_text(json.dumps({"service": "Fake", "model": "fake-edit",
                                                        "final_prompt": "FINAL " + kw["bare_prompt"]}))
        return out

    def matte(data, model="", **kw):
        buf = io.BytesIO()
        Image.fromarray((pad_mask["m"] * 255).astype(np.uint8), "L").save(buf, "PNG")
        return buf.getvalue()

    def reset_front():
        original.save(front)
        front.with_suffix(".json").write_text(json.dumps({"created_at": "Y0001-D001", "prompt_fingerprint": "f"}))
        for p in refs.glob("tpose_neutral_*"):
            p.unlink()

    real = expression_regen.render_character_image, character.run_rembg
    expression_regen.render_character_image, character.run_rembg = stub, matte
    profile = {"gender": "female"}
    try:
        set_switch(config, paths, True)
        before = hashlib.sha256(original.tobytes()).hexdigest()
        for m, outcome, error in (("busy", "busy", None), ("error", "failed", "backend broke"),
                                  ("none", "failed", "the edit rendered nothing")):
            reset_front()
            mode["m"] = m
            sha = front.read_bytes()
            got = base_skin.after_front_render("Demo", front, bsig="base12345678", profile=profile)
            rec = json.loads(front.with_suffix(".json").read_text())["skin_step"]
            check(f"[C] {m}: returns the front", got, front)
            check(f"[C] {m}: front bytes unchanged", front.read_bytes() == sha)
            check(f"[C] {m}: record", (rec["applied"], rec["outcome"]), (False, outcome))
            if error:
                check(f"[C] {m}: error", rec["error"], error)
            check(f"[C] {m}: neutral stored", (refs / "tpose_neutral_base12345678.png").read_bytes() == sha)
            check(f"[C] {m}: sidecar kept", json.loads(front.with_suffix(".json").read_text())["prompt_fingerprint"],
                  "f")
        reset_front()
        set_switch(config, paths, False)
        calls.clear()
        base_skin.after_front_render("Demo", front, bsig="base12345678", profile=profile)
        check("[C3] off: no edit", len(calls), 0)
        check("[C3] off: no neutral", list(refs.glob("tpose_neutral_*")), [])
        check("[C3] off: record", json.loads(front.with_suffix(".json").read_text())["skin_step"]["outcome"], "off")

        set_switch(config, paths, True)
        reset_front()
        mode["m"] = "ok"
        calls.clear()
        base_skin.after_front_render("Demo", front, bsig="base12345678", profile=profile)
        check("[C4] one edit call", len(calls), 1)
        kw = calls[0]
        check("[C4] occasion / use case / postprocess",
              (kw["occasion"], kw["image_use_case"], kw["postprocess"]), ("outfit_front", "outfit_edit", False))
        check("[C4] size", (kw["override_width"], kw["override_height"]), tuple(_tpose_size()))
        check("[C4] prompt", kw["bare_prompt"], base_skin.skin_prompt(profile))
        check("[C4] no body hair for a female", "body hair" in kw["bare_prompt"], False)
        rec = json.loads(front.with_suffix(".json").read_text())["skin_step"]
        check("[C4] record", (rec["applied"], rec["outcome"]), (True, "applied"))
        check("[C4] registration", rec["registration"], {"scale": 1.0, "dx": 0, "dy": 0})
        check("[C4] final_prompt recorded", rec["edit"]["final_prompt"], "FINAL " + base_skin.skin_prompt(profile))
        with Image.open(front) as im:
            new = im.convert("RGBA")
        check("[C4] front changed", hashlib.sha256(new.tobytes()).hexdigest() != before)
        check("[C4] alpha unchanged", new.getchannel("A").tobytes() == original.getchannel("A").tobytes())
        with Image.open(refs / "tpose_neutral_base12345678.png") as im:
            check("[C4] neutral = the old front", hashlib.sha256(im.convert("RGBA").tobytes()).hexdigest(), before)
    finally:
        expression_regen.render_character_image, character.run_rembg = real


def section_cost(config, paths):
    from app.core import base_body
    print("[D] cost")
    plan = {"signature": "base12345678", "views": list(base_body.BASE_VIEWS), "model": False,
            "reason": "older_prompts"}
    set_switch(config, paths, True)
    steps = base_body.base_rebuild_steps("X", plan)
    check("on: steps", steps, [("view front", 1), ("skin front", 1), ("view back", 1), ("view left", 1),
                               ("view right", 1)])
    cost = base_body.base_rebuild_cost("X", plan=plan)
    check("on: hub jobs", cost["hub_jobs"], 5)
    check("on: note names the step", "skin front" in cost["note"])
    set_switch(config, paths, False)
    check("off: hub jobs", base_body.base_rebuild_cost("X", plan=plan)["hub_jobs"], 4)


def section_final_prompt():
    from app.imagegen.base import ImageBackend
    import app.utils.image_prompt_logger as ipl
    print("[E] final_prompt at the central handoff")

    class Fake(ImageBackend):
        def __init__(self):
            super().__init__("Fake", "http://localhost", 0.0, "fake", "FAKE_")

        def check_availability(self):
            return True

        def _generate(self, prompt, negative_prompt, params):
            return [b"png"]

    real = ipl.log_image_prompt
    ipl.log_image_prompt = lambda **kw: None
    try:
        meta = {}
        Fake().generate("a prompt", "", {"occasion": "outfit_front"}, log_meta=meta)
        check("log_meta final_prompt", meta.get("final_prompt"), "a prompt")
    finally:
        ipl.log_image_prompt = real


def main():
    baseline_proof()
    with tempfile.TemporaryDirectory(prefix="base-skin-step-") as tmp:
        root = Path(tmp)
        os.environ["STORAGE_DIR"] = str(root / "world")
        os.environ["INSTANCE_DIR"] = str(root / "instance")
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "instance")
        from app.core import config
        set_switch(config, paths, True)
        section_transfer()
        section_fingerprint(config, paths)
        section_fallback(config, paths, root)
        section_cost(config, paths)
        section_final_prompt()
    print()
    if FAILS:
        print(f"{len(FAILS)} failure(s): {', '.join(FAILS)}")
        sys.exit(1)
    print("ALL OK")


if __name__ == "__main__":
    main()
