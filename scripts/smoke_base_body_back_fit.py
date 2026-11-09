#!/usr/bin/env python3
"""Smoke: the base-body routing occasions, the back-fit references and the
fit's noise gate (user decisions 2026-11-09).

Usage:
    ./.venv/bin/python scripts/smoke_base_body_back_fit.py

Runs without the server, against a temp storage dir; no render, no matte.
Expected values, derived by hand:

[1] Occasion catalog. Five character-scoped image occasions with
    (char_spec_field, fallback field(s)):
      base_front         base_front_workflow, then tpose_workflow, workflow
      base_view          base_view_workflow, then tpose_view_workflow
      outfit_front       outfit_front_workflow, then tpose_view_workflow
      outfit_back_draft  outfit_back_draft_workflow, then tpose_view_workflow
      outfit_back        outfit_back_workflow, then tpose_view_workflow
    spec_fields lists them in that order. Only outfit_back needs a reference
    slot. Hints: base_front names the non-turbo model, outfit_back the noise
    check and no model, outfit_back_draft "only its clothing", the other two
    none. All five are in MESH_INPUT_OCCASIONS. outfit_back renders with the
    use case outfit_fit, whose style and negative are empty in both families.
[2] Seeding (config._apply_file_migrations on a union whose routing holds
    tpose = ["a*"], tpose_view = ["b*"], outfit_back = ["mine"]):
    base_front = ["a*"], base_view / outfit_front / outfit_back_draft =
    ["b*"], outfit_back stays ["mine"]. A second run changes nothing. Without
    a tpose_view chain the four tpose_view seeds stay absent.
[3] Per-character resolution (routing._character_spec, profile stubbed):
    outfit_imagegen {workflow "w", tpose_workflow "t", tpose_view_workflow
    "v"} -> base_front "t", base_view "v", outfit_back "v"; adding
    base_front_workflow "bf" and outfit_back_workflow "ob" -> "bf" / "ob";
    with only workflow "w": base_front "w" (the tpose rule), base_view ""
    (views never fall to the render match).
[4] Fit references (base_body.fit_canvas, render size 1024 x 1024):
    base cut-out 6 x 10, figure alpha 255 on x 2..3, y 2..7 (bbox (2,2,4,8),
    height 6); draft cut-out 20 x 20, figure on x 4..9, y 0..11 (bbox
    (4,0,10,12), 6 x 12). Canvas height 10, width max(6, round(10 * 1024 /
    1024) = 10, 3) = 10; base pasted at x (10 - 6) // 2 = 2 -> its bbox
    (4,2,6,8). Draft figure scaled by 6 / 12 to 3 x 6, centred on the base
    figure's centre x 2 + (2 + 4) / 2 = 5 -> x round(5 - 1.5) = 4, y = 2 ->
    bbox (4,2,7,8). Size (512, 1024): width max(6, 5, 3) = 6, base at 0 ->
    bbox (2,2,4,8), draft at round(3 - 1.5) = 2 -> (2,2,5,8). A cut-out
    without a figure: ValueError. cut_out keeps an image that has a matte
    (no matte call).
[5] Noise on the figure (base_body_gates.figure_noise_arrays): 1024 x 1024
    grey, a checkerboard 128 +/- a on the figure x 300..699, y 100..899
    (alpha 255, the rest 0). Inside, every 3x3 box holds 5 pixels of the
    centre's sign and 4 of the other -> box mean = centre -/+ 8a/9 off,
    residual exactly 8a/9. Head = rows 100 .. 100 + int(0.12 * 800) = 196
    (exclusive), eroded by 4 (cross, border 0): rows 104..191, columns
    304..695 = 88 * 392 = 34496 pixels, all interior. a = 18 -> 16.0,
    a = 27 -> 24.0, a = 36 -> 32.0. Whole image alpha 255 or 0: None.
    noise_gate on saved files (height 1024: no resample): base a = 18, fit
    a = 27 -> score 24 / 16 = 1.5 <= 1.75 ok; fit a = 36 -> 2.0, not ok;
    flat base (0) and flat fit -> reference floor 0.05, score 0.0 ok. An
    opaque RGB fit: ok, score None, reason "fit not measurable".
[6] Choice and warning: best_fit_attempt([fail, pass]) -> (1, True);
    [guard ok noise 2.4, guard ok noise 1.9] -> (1, False); [guard fails
    noise 1.0, guard ok noise 3.0] -> (1, False) (the view matters first);
    fit_gate_warning(2, noise fails) = "Dressed back may be grainy (back
    check failed after 2 attempts)"; guard and noise fail, 1 attempt ->
    "... turned toward the camera and grainy (back check failed after 1
    attempt)".
[7] Extra reference slots (service.slot_extra_references, the containment
    gate stubbed to accept paths containing "/ok/"): {slot 1} + [ok/d.png]
    on a 2-slot backend -> input_reference_image_2 = ok/d.png; on a 1-slot
    backend BackendNotApplicableError "needs 2 reference slots"; no own slot
    or a refused path -> ValueError.
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {repr(got)[:160]}" + ("" if ok else f" — expected {repr(want)[:300]}"))
    if not ok:
        FAILS.append(label)


def checkerboard(a: int, alpha_figure: bool = True):
    import numpy as np
    grey = np.full((1024, 1024), 128.0)
    alpha = np.zeros((1024, 1024), dtype=np.uint8)
    ys, xs = np.mgrid[100:900, 300:700]
    grey[100:900, 300:700] = 128 + a * np.where((ys + xs) % 2 == 0, 1, -1)
    alpha[100:900, 300:700] = 255 if alpha_figure else 0
    return grey, alpha


def save_rgba(path: Path, grey, alpha) -> Path:
    import numpy as np
    from PIL import Image
    g = grey.astype(np.uint8)
    Image.fromarray(np.dstack([g, g, g, alpha]), "RGBA").save(path)
    return path


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="smoke_back_fit_"))
    os.environ["STORAGE_DIR"] = str(tmp / "world")
    os.environ["INSTANCE_DIR"] = str(tmp / "instance")
    from app.core import paths
    paths.init(str(tmp / "world"))
    import numpy as np
    from PIL import Image
    from app.core import base_body, base_body_gates as gates, config
    from app.imagegen import occasions, routing, service
    from app.imagegen.base import BackendNotApplicableError

    print("[1] occasion catalog")
    want = {"base_front": ["base_front_workflow", "tpose_workflow", "workflow"],
            "base_view": ["base_view_workflow", "tpose_view_workflow"],
            "outfit_front": ["outfit_front_workflow", "tpose_view_workflow"],
            "outfit_back_draft": ["outfit_back_draft_workflow", "tpose_view_workflow"],
            "outfit_back": ["outfit_back_workflow", "tpose_view_workflow"]}
    for occ, fields in want.items():
        d = occasions.OCCASIONS[occ]
        check(f"{occ} spec fields", list(occasions.spec_fields(d)), fields)
        check(f"{occ} scoped image", (d.get("character_scoped"), d.get("media")), (True, "image"))
        check(f"{occ} mesh input", occ in occasions.MESH_INPUT_OCCASIONS, True)
    check("ref slot", [o for o in want if occasions.OCCASIONS[o].get("needs_ref_slot")], ["outfit_back"])
    hints = {o: occasions.OCCASIONS[o].get("hint") or "" for o in want}
    check("hints", ("non-turbo" in hints["base_front"], "noise check" in hints["outfit_back"],
                    "turbo" in hints["outfit_back"], "only its clothing" in hints["outfit_back_draft"],
                    hints["base_view"], hints["outfit_front"]), (True, True, False, True, "", ""))
    check("fit use case", occasions.OCCASIONS["outfit_back"].get("style_use_cases"), ["outfit_fit"])
    for family in ("natural", "keywords"):
        p = config.get_use_case_prompts("outfit_fit", "flux" if family == "natural" else "sdxl")
        check(f"outfit_fit {family} empty", (p["prompt_style"], p["prompt_negative"]), ("", ""))

    print("[2] seeding")
    union = {"image_generation": {"routing": {"tpose": ["a*"], "tpose_view": ["b*"], "outfit_back": ["mine"]}}}
    config._apply_file_migrations(union)
    r = union["image_generation"]["routing"]
    check("seeded", [r.get(k) for k in ("base_front", "base_view", "outfit_front", "outfit_back_draft",
                                          "outfit_back")],
          [["a*"], ["b*"], ["b*"], ["b*"], ["mine"]])
    check("second run unchanged", config._migrate_base_body_routing(union), False)
    only_tpose = {"image_generation": {"routing": {"tpose": ["a*"]}}}
    config._migrate_base_body_routing(only_tpose)
    check("no tpose_view source", sorted(only_tpose["image_generation"]["routing"]), ["base_front", "tpose"])

    print("[3] per-character resolution")
    import app.models.character as character_module
    real_profile = character_module.get_character_profile
    record = {}
    character_module.get_character_profile = lambda name: {"outfit_imagegen": dict(record)}
    try:
        def spec(occ):
            return routing._character_spec(occasions.OCCASIONS[occ], "Demo")
        record.update({"workflow": "w", "tpose_workflow": "t", "tpose_view_workflow": "v"})
        check("fallbacks", [spec(o) for o in ("base_front", "base_view", "outfit_back")], ["t", "v", "v"])
        record.update({"base_front_workflow": "bf", "outfit_back_workflow": "ob"})
        check("own fields", [spec(o) for o in ("base_front", "outfit_back", "outfit_back_draft")],
              ["bf", "ob", "v"])
        record.clear()
        record["workflow"] = "w"
        check("render match only", [spec(o) for o in ("base_front", "base_view")], ["w", ""])
    finally:
        character_module.get_character_profile = real_profile

    print("[4] fit references")
    base = Image.new("RGBA", (6, 10), (0, 0, 0, 0))
    for x in range(2, 4):
        for y in range(2, 8):
            base.putpixel((x, y), (10, 200, 10, 255))
    draft = Image.new("RGBA", (20, 20), (0, 0, 0, 0))
    for x in range(4, 10):
        for y in range(0, 12):
            draft.putpixel((x, y), (200, 10, 10, 255))
    b, d = base_body.fit_canvas(base, draft, (1024, 1024))
    check("square: sizes", (b.size, d.size), ((10, 10), (10, 10)))
    check("square: bboxes", (b.getchannel("A").getbbox(), d.getchannel("A").getbbox()), ((4, 2, 6, 8), (4, 2, 7, 8)))
    b, d = base_body.fit_canvas(base, draft, (512, 1024))
    check("portrait: bboxes", (b.size, b.getchannel("A").getbbox(), d.getchannel("A").getbbox()),
          ((6, 10), (2, 2, 4, 8), (2, 2, 5, 8)))
    try:
        base_body.fit_canvas(base, Image.new("RGBA", (4, 4), (0, 0, 0, 0)), (1024, 1024))
        check("empty draft", "no error", "ValueError")
    except ValueError:
        check("empty draft", "ValueError", "ValueError")
    base.save(tmp / "base.png")
    real_rembg = character_module.run_rembg
    calls = []
    character_module.run_rembg = lambda *a, **k: calls.append(a) or b""
    try:
        cut = base_body.cut_out(tmp / "base.png")
        check("matted image kept", (calls, cut.getchannel("A").getbbox()), ([], (2, 2, 4, 8)))
    finally:
        character_module.run_rembg = real_rembg

    print("[5] noise on the figure")
    for a, want_noise in ((18, 16.0), (27, 24.0), (36, 32.0)):
        got = gates.figure_noise_arrays(*checkerboard(a))
        check(f"a={a} head", round(got["head"], 9), want_noise)
    check("all background", gates.figure_noise_arrays(*checkerboard(18, alpha_figure=False)), None)
    grey, _ = checkerboard(18)
    check("all figure", gates.figure_noise_arrays(grey, np.full((1024, 1024), 255, np.uint8)), None)
    from scipy import ndimage
    head = np.zeros((1024, 1024), bool)
    head[100:196, 300:700] = True
    head = ndimage.binary_erosion(head, iterations=4, border_value=0)
    check("head region", (int(head.sum()), np.where(head.any(axis=1))[0][[0, -1]].tolist(),
                          np.where(head.any(axis=0))[0][[0, -1]].tolist()), (34496, [104, 191], [304, 695]))
    base_png = save_rgba(tmp / "b18.png", *checkerboard(18))
    g = gates.noise_gate(save_rgba(tmp / "f27.png", *checkerboard(27)), base_png)
    check("fit 27 vs 18", (g["ok"], g["score"], g["noise"], g["reference_noise"]), (True, 1.5, 24.0, 16.0))
    g = gates.noise_gate(save_rgba(tmp / "f36.png", *checkerboard(36)), base_png)
    check("fit 36 vs 18", (g["ok"], g["score"]), (False, 2.0))
    g = gates.noise_gate(save_rgba(tmp / "f0.png", *checkerboard(0)), save_rgba(tmp / "b0.png", *checkerboard(0)))
    check("flat vs flat", (g["ok"], g["score"]), (True, 0.0))
    Image.new("RGB", (64, 64), (90, 90, 90)).save(tmp / "opaque.png")
    g = gates.noise_gate(tmp / "opaque.png", base_png)
    check("opaque fit", (g["ok"], g["score"], g.get("reason")), (True, None, "fit not measurable"))

    print("[6] choice and warning")
    ok = {"ok": True, "guard": {"ok": True}, "noise": {"ok": True, "score": 1.0}}

    def bad(guard_ok, score):
        return {"ok": False, "guard": {"ok": guard_ok}, "noise": {"ok": score <= 1.75, "score": score}}
    check("first passing", base_body.best_fit_attempt([bad(True, 2.4), ok]), (1, True))
    check("lowest noise", base_body.best_fit_attempt([bad(True, 2.4), bad(True, 1.9)]), (1, False))
    check("view first", base_body.best_fit_attempt([bad(False, 1.0), bad(True, 3.0)]), (1, False))
    check("grainy warning", base_body.fit_gate_warning(2, bad(True, 2.4)),
          "Dressed back may be grainy (back check failed after 2 attempts)")
    check("both warning", base_body.fit_gate_warning(1, bad(False, 2.4)),
          "Dressed back may be turned toward the camera and grainy (back check failed after 1 attempt)")

    print("[7] extra reference slots")
    import app.core.model_refs as model_refs
    real_gate = model_refs.checked_reference_override
    model_refs.checked_reference_override = lambda name, path: path if "/ok/" in path else None

    class Backend:
        name = "stub"

        def __init__(self, slots):
            self.ref_slot_count = slots
    try:
        own = {"input_reference_image_1": "/x/ok/base.png"}
        check("two slots", service.slot_extra_references(own, ["/x/ok/d.png"], Backend(2), "Demo"),
              {"input_reference_image_1": "/x/ok/base.png", "input_reference_image_2": "/x/ok/d.png"})
        for label, args, err in (("one slot", (own, ["/x/ok/d.png"], Backend(1)), BackendNotApplicableError),
                                 ("no own slot", ({}, ["/x/ok/d.png"], Backend(4)), ValueError),
                                 ("refused path", (own, ["/elsewhere/d.png"], Backend(4)), ValueError)):
            try:
                service.slot_extra_references(*args, "Demo")
                check(label, "no error", err.__name__)
            except err as e:
                check(label, (type(e).__name__, getattr(e, "reason", None) if err is BackendNotApplicableError
                              else None),
                      (err.__name__, "needs 2 reference slots" if err is BackendNotApplicableError else None))
    finally:
        model_refs.checked_reference_override = real_gate

    print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
