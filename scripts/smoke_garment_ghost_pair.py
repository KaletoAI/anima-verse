#!/usr/bin/env python3
"""The hair-only pair of the hair edit chain: front and back must end at the
same height (``garment_gates.bottoms_agree``), and a run whose base views
change underneath it stops (app/core/garments.py, app/core/garment_images.py).

User-test finding 2026-11-09 (Kira, method edit_chain): the chain stopped at
``ghost`` with "front and back hair end at different heights" (front bottom
0.27734 H, back 0.24805 H, |Δ| 0.0293 > 0.05 × 0.25586 = 0.0128) after BOTH
views had been accepted on their own. Nothing rendered again: every later Run
skipped both accepted views and refused at once — a dead end without a forced
regenerate. A second run failed at ``ghost front`` with w_ratio 0.842 / 0.826
because the base front view was regenerated (844 → 712 px wide, same base
signature) while the chain ran: the haired image of the OLD base was gated
against the NEW one (712 / 844 = 0.844).

Usage:
    ./.venv/bin/python scripts/smoke_garment_ghost_pair.py

Runs against a THROWAWAY storage + instance directory with a copy of the
repo's ``human`` package — no real world, no hub, no GPU, no server. The image
gates and ``run_edit_step`` are REAL; stubbed: the renderer (writes the planned
image), ``character.run_rembg`` (every pixel more than 2 away from grey 128),
``garment_images.cut_out`` / ``garment_mesh.generate`` / ``garments._fit``
(recorders — the steps after ``ghost`` are not under test).

The same scenarios run a second time in a subprocess on the OLD orchestration
(``git show cf329f47:app/core/garments.py``, the commit before this fix);
their expected old results are listed below and checked, so the smoke shows
the fix, not just the current output.

Geometry (the fixture of smoke_garment_chain.py), W 1024 x H 1200 on grey:
  BASE   head disc centre (512, 200) r 100 + torso cols [392, 632) rows
         [300, 1100) in skin -> base mask rows 100 .. 1099: y0 100, Hb 999;
         hair_ref rows < int(100 + 0.22 x 999) = 319, chin row
         int(100 + 0.13 x 999) = 229.
  HAIRED BASE + hair rect cols [404, 620) rows [92, 200) -> hair_ref bbox
         [404, 92, 619, 199] (a rectangle survives opening/closing).
  ghost(end) = grey + the hair rect + a tail cols [440, 584) rows [200, end]:
         bbox [404, 92, 619, end] -> top_dy 0, centre_dx 0, w_ratio 1.0, the
         tail is hair-coloured (|ΔRGB| to skin 106.7 > 20) -> body_left 0:
         every ghost passes its own gate; bottom = end / 1200,
         hair_h = (end - 92) / 1200 (5 digits).
  BACK  = ghost(299): bottom 0.24917, hair_h 0.1725
  LONG  = ghost(399): bottom 0.3325,  hair_h 0.25583
          vs BACK: |Δ| 0.08333 > 0.05 x 0.25583 = 0.01279 -> disagree
  MATCH = ghost(305): bottom 0.25417, hair_h 0.1775
          vs BACK: |Δ| 0.005 <= 0.05 x 0.1775 = 0.00888 -> agree

[1] Fresh run, every front ghost LONG, the back BACK.
    new: haired f1, haired b1, ghost f1 (LONG, no back yet: accepted),
         ghost b1 (accepted), pair disagrees -> the front again against the
         back: f1, f2 both LONG, refused with the reason "hair ends at another
         height than in the back view: |Δ| 0.0833 H > 0.0128 H (front 0.3325,
         back 0.24917)" -> {ok False, step ghost}, 6 renders, gates
         {view front, attempts 2}.
    old: 4 renders, {ok False, step ghost}, error "front and back hair end at
         different heights".
[2] Run again, the next front ghost MATCH.
    new: 1 render (ghost f1), ok True, ran starts [ghost, cutout, ...],
         accepted front bottom 0.25417.
    old: 0 renders, {ok False, step ghost} — the dead end.
[3] Forced front ghost (steps ghost, view front), plan [LONG, MATCH], the back
    stays: the front is checked against the back right away.
    new: 2 renders, attempt 1 refused with the bottom reason, attempt 2
         accepted, ok True.
    old (from its own state after [2], i.e. still the dead end: both views
         accepted, they disagree): the forced front LONG is accepted at
         attempt 1, the pair disagrees -> 1 render, ok False, step ghost.
[4] Forced haired step; the renderer rewrites the base front view (one torso
    pixel, same signature, new sha -> new fsig) while the haired front renders.
    new: 1 render, {ok False, step haired, error INPUTS_CHANGED_ERROR}.
    old: carries on under the stale fsig: 4 renders (haired f/b, ghost f/b),
         ok True.
[5] Plain run after [4]: the new fsig; 4 renders (haired f/b, ghost f MATCH,
    ghost b), ok True, result fsig = the current garment_fsig. (new only)
"""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

BEFORE = "cf329f47"
FAILS = []
GREY = (128, 128, 128)
SKIN = (200, 160, 140)
HAIR = (90, 60, 30)
W, H = 1024, 1200
BOTTOM_REASON = ("hair ends at another height than in the back view: |Δ| 0.0833 H > 0.0128 H "
                 "(front 0.3325, back 0.24917)")


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


def canvas():
    rgb = np.zeros((H, W, 3), dtype=np.uint8)
    rgb[:] = GREY
    return rgb


def figure(rgb):
    yy, xx = np.mgrid[0:H, 0:W]
    rgb[(xx - 512) ** 2 + (yy - 200) ** 2 <= 100 ** 2] = SKIN
    rgb[300:1100, 392:632] = SKIN
    return rgb


def hair(rgb):
    rgb[92:200, 404:620] = HAIR
    return rgb


def ghost(end):
    rgb = hair(canvas())
    rgb[200:end + 1, 440:584] = HAIR
    return rgb


BASE = figure(canvas())
BASE_TOUCHED = BASE.copy()
BASE_TOUCHED[700, 512] = (201, 160, 140)
HAIRED = hair(figure(canvas()))
BACK, LONG, MATCH = ghost(299), ghost(399), ghost(305)


def rembg_stub(data, model="u2net", **kwargs):
    from PIL import Image
    with Image.open(io.BytesIO(data)) as im:
        arr = np.asarray(im.convert("RGB")).astype(np.int16)
    mask = (np.abs(arr - 128) > 2).any(2)
    return png((mask * 255).astype(np.uint8))


def load_old_garments():
    """``app.core.garments`` as of ``BEFORE``, registered under its own name."""
    source = subprocess.run(["git", "show", f"{BEFORE}:app/core/garments.py"], cwd=ROOT, capture_output=True,
                            text=True, check=True).stdout
    module = types.ModuleType("app.core.garments")
    module.__file__ = str(ROOT / "app/core/garments.py")
    sys.modules["app.core.garments"] = module
    exec(compile(source, f"{BEFORE}:app/core/garments.py", "exec"), module.__dict__)
    import app.core as core
    core.garments = module
    return module


def run_arm(arm: str) -> dict:
    """Run the scenarios on the ``new`` or the ``old`` orchestration; returns
    the observations (JSON-able)."""
    obs = {}
    with tempfile.TemporaryDirectory(prefix=f"ghost-pair-{arm}-") as tmp:
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

        garments = load_old_garments() if arm == "old" else __import__("app.core.garments", fromlist=["x"])
        from app.core import base_body, expression_regen, garment_hair, garment_images, garment_mesh
        from app.core import garment_store as gs
        from app.models import character as charmod
        from app.models.character import (get_character_dir, get_character_images_dir, get_character_profile,
                                          save_character_profile)

        renders = []
        plan = {"front": [], "swap_base": False}
        refs_holder = {}
        charmod.run_rembg = rembg_stub

        def recorder(character_name, *, output_stem, **kw):
            g = kw["sidecar_extra"]["garment"]
            renders.append(f"{g['step']} {g['view'][0]}{g['attempt']}")
            if g["step"] == "haired":
                arr = HAIRED
                if plan["swap_base"] and g["view"] == "front":
                    plan["swap_base"] = False
                    (refs_holder["refs"] / f"tpose_{refs_holder['bsig']}.png").write_bytes(png(BASE_TOUCHED))
            elif g["view"] == "back":
                arr = BACK
            else:
                arr = plan["front"].pop(0) if plan["front"] else MATCH
            side = kw["override_width"]
            out_canvas = np.full((kw["override_height"], side, 3), 128, dtype=np.uint8)
            dy, dx = (out_canvas.shape[0] - arr.shape[0]) // 2, (side - arr.shape[1]) // 2
            out_canvas[dy:dy + arr.shape[0], dx:dx + arr.shape[1]] = arr
            out = Path(str(output_stem) + ".png")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(png(out_canvas))
            out.with_suffix(".json").write_text(json.dumps({"seed": 1000 + g["attempt"], **kw["sidecar_extra"]}))
            return out

        expression_regen.render_character_image = recorder

        def cut_out(character_name, item_id, fsig, view, *, force=False):
            path = gs.garment_path(character_name, item_id, fsig, "image", step="cutout", view=view)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"cutout")
            gs.write_record(path.with_suffix(".json"), {"accepted": True})
            return path

        garment_images.cut_out = cut_out
        garment_mesh.generate = lambda *a, **k: None
        garments._fit = lambda *a, **k: None

        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                 "character_appearance": "slender",
                 "body_slots": {"skin": {"tone": "light"}, "eyes": {"color": "blue"},
                                "build": {"type": "athletic"},
                                "hair": {"length": "medium", "color": "blonde"}}}
        save_character_profile("Demo", human, create_new=True)
        images = get_character_images_dir("Demo")
        images.mkdir(parents=True, exist_ok=True)
        (images / "Demo_1.png").write_bytes(png(np.full((8, 8, 3), 60, dtype=np.uint8)))
        stored = get_character_profile("Demo")
        stored["profile_image"] = "Demo_1.png"
        save_character_profile("Demo", stored)
        base_body.set_pipeline("Demo", True)
        hid = garment_hair.ensure_hair_item("Demo")
        refs = get_character_dir("Demo") / "model_refs"
        refs.mkdir(parents=True, exist_ok=True)
        bsig = base_body.base_signature("Demo")
        refs_holder.update(refs=refs, bsig=bsig)
        for v in base_body.BASE_VIEWS:
            stem = f"tpose_{bsig}" if v == "front" else f"tpose_{v}_{bsig}"
            (refs / f"{stem}.png").write_bytes(png(BASE))
            (refs / f"{stem}.json").write_text(json.dumps({"base_signature": bsig}))

        def front_record(fsig):
            return gs.read_record(gs.garment_path("Demo", hid, fsig, "image", step="ghost", view="front")
                                  .with_suffix(".json"))

        def accepted_bottom(fsig):
            rec = front_record(fsig)
            gate = (rec.get("gates") or {}).get(("first", "second")[int(rec.get("attempt") or 1) - 1]) or {}
            return [rec.get("accepted"), gate.get("bottom")]

        def run(label, **kw):
            del renders[:]
            res = garments.run_garment("Demo", hid, **kw)
            gates = res.get("gates") or {}
            attempts = gates.get("attempts") if isinstance(gates, dict) else None
            obs[label] = {"renders": list(renders), "ok": res.get("ok"), "step": res.get("step"),
                          "error": res.get("error"), "fsig": res.get("fsig"), "ran": res.get("ran"),
                          "gates_view": gates.get("view") if isinstance(gates, dict) else None,
                          "attempt_reasons": [a.get("reasons") for a in attempts] if attempts else None}
            return res

        f1 = gs.garment_fsig("Demo", hid)
        obs["f1"] = f1
        plan["front"] = [LONG, LONG, LONG]
        run("1")
        obs["1"]["front"] = accepted_bottom(f1)
        plan["front"] = [MATCH]
        run("2")
        obs["2"]["front"] = accepted_bottom(f1)
        plan["front"] = [LONG, MATCH]
        run("3", steps="ghost", view="front", force=True)
        obs["3"]["front"] = accepted_bottom(f1)
        plan["front"] = []
        plan["swap_base"] = True
        run("4", steps="haired", force=True)
        obs["4"]["current_fsig"] = gs.garment_fsig("Demo", hid)
        if arm == "new":
            run("5")
            obs["5"]["current_fsig"] = gs.garment_fsig("Demo", hid)
            from app.core import garment_gates as gg
            obs["unit"] = {"agree_none": gg.bottoms_reason({"bottom": 0.25417, "hair_h": 0.1775},
                                                           {"bottom": 0.24917, "hair_h": 0.1725}),
                           "missing_none": gg.bottoms_reason({"reasons": ["no hair"]}, {"bottom": 0.2}),
                           "gap": gg.bottoms_gap({"bottom": 0.3325, "hair_h": 0.25583},
                                                 {"bottom": 0.24917, "hair_h": 0.1725})}
    return obs


def main() -> int:
    if len(sys.argv) > 2 and sys.argv[1] == "--arm":
        print("OBS " + json.dumps(run_arm(sys.argv[2])))
        return 0
    proc = subprocess.run([sys.executable, __file__, "--arm", "old"], cwd=ROOT, capture_output=True, text=True)
    line = next((ln for ln in proc.stdout.splitlines() if ln.startswith("OBS ")), None)
    if line is None:
        print(proc.stdout[-3000:], proc.stderr[-3000:])
        check("old arm ran", None, "observations")
        print("FAILED: " + ", ".join(FAILS))
        return 1
    old = json.loads(line[4:])
    new = run_arm("new")
    from app.core.garments import INPUTS_CHANGED_ERROR

    print("[1] fresh run, every front ghost LONG")
    check("new renders", new["1"]["renders"],
          ["haired f1", "haired b1", "ghost f1", "ghost b1", "ghost f1", "ghost f2"])
    check("new refused at ghost front", (new["1"]["ok"], new["1"]["step"], new["1"]["gates_view"]),
          (False, "ghost", "front"))
    check("new attempt reasons", new["1"]["attempt_reasons"], [[BOTTOM_REASON], [BOTTOM_REASON]])
    check("new front stays the old accepted LONG", new["1"]["front"], [True, 0.3325])
    check("old renders", old["1"]["renders"], ["haired f1", "haired b1", "ghost f1", "ghost b1"])
    check("old refusal", (old["1"]["ok"], old["1"]["step"], old["1"]["error"]),
          (False, "ghost", "front and back hair end at different heights"))

    print("[2] run again, the next front ghost MATCH")
    check("new renders", new["2"]["renders"], ["ghost f1"])
    check("new ok", (new["2"]["ok"], (new["2"]["ran"] or [])[:2]), (True, ["ghost", "cutout"]))
    check("new accepted front", new["2"]["front"], [True, 0.25417])
    check("old: dead end", (old["2"]["renders"], old["2"]["ok"], old["2"]["step"]), ([], False, "ghost"))

    print("[3] forced front ghost against the kept back")
    check("new renders", new["3"]["renders"], ["ghost f1", "ghost f2"])
    check("new ok", new["3"]["ok"], True)
    check("new accepted front", new["3"]["front"], [True, 0.25417])
    check("old: LONG accepted, pair refused", (old["3"]["renders"], old["3"]["ok"], old["3"]["step"]),
          (["ghost f1"], False, "ghost"))

    print("[4] base front view rewritten during the haired front render")
    check("new renders", new["4"]["renders"], ["haired f1"])
    check("new refused", (new["4"]["ok"], new["4"]["step"], new["4"]["error"]),
          (False, "haired", INPUTS_CHANGED_ERROR))
    check("new fsig moved on", new["4"]["current_fsig"] != new["f1"], True)
    check("old carries on under the stale fsig",
          (old["4"]["renders"], old["4"]["ok"], old["4"]["fsig"] == old["f1"],
           old["4"]["current_fsig"] != old["f1"]),
          (["haired f1", "haired b1", "ghost f1", "ghost b1"], True, True, True))

    print("[5] plain run on the new fsig")
    check("renders", new["5"]["renders"], ["haired f1", "haired b1", "ghost f1", "ghost b1"])
    check("ok on the current fsig", (new["5"]["ok"], new["5"]["fsig"] == new["5"]["current_fsig"]), (True, True))

    print("[6] garment_gates.bottoms_reason / bottoms_gap")
    check("agree -> None", new["unit"]["agree_none"], None)
    check("unmeasured -> None", new["unit"]["missing_none"], None)
    gap = new["unit"]["gap"]
    check("gap", [round(gap[0], 5), round(gap[1], 5)], [0.08333, 0.01279])

    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
