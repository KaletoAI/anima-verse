#!/usr/bin/env python3
"""The hair-only pair of the hair edit chain: the back renders first and
gives the front its length, front and back must end at the same height
(``garment_gates.bottoms_agree``), and a run whose base views change
underneath it stops (app/core/garments.py, garment_images.py, garment_hair.py,
garment_gates.py).

User-test finding 2026-11-09 (Kira, method edit_chain): the chain stopped at
``ghost`` with "front and back hair end at different heights" (front bottom
0.27734 H, back 0.24805 H, |Δ| 0.0293 > 0.05 × 0.25586 = 0.0128) after BOTH
views had been accepted on their own. Nothing rendered again: every later Run
skipped both accepted views and refused at once — a dead end without a forced
regenerate. A second run failed at ``ghost front`` with w_ratio 0.842 / 0.826
because the base front view was regenerated (844 → 712 px wide, same base
signature) while the chain ran (712 / 844 = 0.844). After the first fix
(687886bb) the front was retried against the back but kept inventing longer
hair (5 Kira fronts 0.277..0.337 H vs back ~0.248 H): the front hides the
hair's ends behind the body, nothing told the edit how long the hair is. User
decision: the length goes into the front prompt, measured on the back — the
hair-only front (the haired front shows no length; with the phrase it became
a bob and failed its body gate 4 of 4 times on the clone).

Usage:
    ./.venv/bin/python scripts/smoke_garment_ghost_pair.py

Runs against a THROWAWAY storage + instance directory with a copy of the
repo's ``human`` package — no real world, no hub, no GPU, no server. The image
gates, ``hair_length`` and ``run_edit_step`` are REAL; stubbed: the renderer
(writes the planned image, records the prompt), ``character.run_rembg``
(every pixel more than 2 away from grey 128), ``garment_images.cut_out`` /
``garment_mesh.generate`` / ``garments._fit`` (recorders — the steps after
``ghost`` are not under test).

The scenarios run again in subprocesses on earlier code, so the smoke shows
the fixes, not just the current output:
  old  = ``git show cf329f47:app/core/garments.py`` (before both fixes);
  prev = garments / garment_hair / garment_images / garment_gates of
         ``687886bb`` (pair retry, no length phrase, front first).

Geometry (the fixture of smoke_garment_chain.py), W 1024 x H 1200 on grey:
  BASE   head disc centre (512, 200) r 100 + torso cols [392, 632) rows
         [300, 1100) in skin -> base mask rows 100 .. 1099: y0 100, Hb 999;
         hair_ref rows < int(100 + 0.22 x 999) = 319, chin row
         int(100 + 0.13 x 999) = 229, body zone from int(100 + 0.3 x 999) = 399.
  HAIRED      BASE + hair rect cols [404, 620) rows [92, 200) (the front)
  HAIRED_BACK HAIRED + a tail cols [440, 584) rows [200, 299]: nothing below
         row 399 changes (haired gate passes); hair_ref bbox [404, 92, 619, 299].
         hair_length: hair above int(100 + 0.5 x 999) = 599 = rect + tail, one
         component, opened 2 iterations (2 x 1200 / 1536 -> 2), bottom 299 ->
         t = (299 - 100) / 999 = 0.1992 -> band [0.16, 0.205) "at the shoulders".
  ghost(end) = grey + the hair rect + the tail down to row ``end``: bbox
         [404, 92, 619, end] -> top_dy 0, centre_dx 0, w_ratio 1.0, the tail is
         hair-coloured (|ΔRGB| to skin 106.7 > 20) -> body_left 0: every ghost
         passes its own gate; bottom = end / 1200, hair_h = (end - 92) / 1200.
  BACK  = ghost(299): bottom 0.24917, hair_h 0.1725
  LONG  = ghost(399): bottom 0.3325,  hair_h 0.25583
          vs BACK: |Δ| 0.08333 > 0.05 x 0.25583 = 0.01279 -> disagree
  MATCH = ghost(305): bottom 0.25417, hair_h 0.1775
          vs BACK: |Δ| 0.005 <= 0.05 x 0.1775 = 0.00888 -> agree

Front prompts (profile: female, hair slot medium / blonde; t 0.1992):
  ghost front contains "the same background. The hair ends at the shoulders.
  Remove the person completely"; the haired front and both back prompts name
  no length (" ends " absent). prev: the ghost front names none either.

[1] Fresh run, every front ghost LONG, the back BACK.
    new: haired b1, haired f1, ghost b1, ghost f1 + f2 (LONG, gated against the
         back, refused: "hair ends at another height than in the back view:
         |Δ| 0.0833 H > 0.0128 H (front 0.3325, back 0.24917)") ->
         {ok False, step ghost, gates.view front}, 5 renders, no accepted front.
    prev: front first: haired f1, haired b1, ghost f1 (accepted), ghost b1,
         ghost f1 + f2 refused -> 6 renders.
    old: 4 renders, {ok False, step ghost}, "front and back hair end at
         different heights".
[2] Run again, the next front ghost MATCH.
    new: 1 render (ghost f1), ok True, ran starts [ghost, cutout],
         accepted front bottom 0.25417.
    old: 0 renders, {ok False, step ghost} — the dead end.
[3] Forced front ghost (steps ghost, view front), plan [LONG, MATCH].
    new: 2 renders, attempt 1 refused, attempt 2 accepted, ok True.
    old (still the dead end): the forced LONG is accepted at attempt 1, the
         pair disagrees -> 1 render, ok False, step ghost.
[3b] Forced BACK ghost, the back now LONG-shaped (bottom 0.3325), the kept
    front MATCH disagrees -> the front renders again against the new back,
    plan [LONG] -> |Δ| 0 -> accepted. new: 2 renders (ghost b1, ghost f1),
    ok True, front bottom 0.3325. (new only)
[4] Forced haired step; the renderer rewrites the base front view (one torso
    pixel, same signature, new sha -> new fsig) during the FIRST haired render.
    new: 1 render (haired b1), {ok False, step haired, INPUTS_CHANGED_ERROR}.
    old: carries on under the stale fsig: 4 renders (haired f/b, ghost f/b),
         ok True.
[5] Plain run after [4]: the new fsig; haired b1, haired f1, ghost b1,
    ghost f1 (MATCH), ok True, result fsig = the current garment_fsig; the
    front prompts carry the length phrase. (new only)
[6] bottoms_reason / bottoms_gap units; length_phrase per band (hand table):
    t 0.10 "at her chin", 0.18 "at her shoulders", 0.205 / 0.23 "at the top
    of her shoulder blades", 0.27 "at the middle of her shoulder blades", 0.33
    "at the middle of her back", 0.40 "at her waist", 0.50 "below her waist",
    None "".
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

#: The arms on earlier code: commit and the app.core modules taken from it.
ARMS = {"old": ("cf329f47", ("garments",)),
        "prev": ("687886bb", ("garment_gates", "garment_hair", "garment_images", "garments"))}
FAILS = []
GREY = (128, 128, 128)
SKIN = (200, 160, 140)
HAIR = (90, 60, 30)
W, H = 1024, 1200
BOTTOM_REASON = ("hair ends at another height than in the back view: |Δ| 0.0833 H > 0.0128 H "
                 "(front 0.3325, back 0.24917)")
GHOST_FRONT_LENGTH = "the same background. The hair ends at the shoulders. Remove the person completely"


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


def tail(rgb, end):
    rgb[200:end + 1, 440:584] = HAIR
    return rgb


def ghost(end):
    return tail(hair(canvas()), end)


BASE = figure(canvas())
BASE_TOUCHED = BASE.copy()
BASE_TOUCHED[700, 512] = (201, 160, 140)
HAIRED = hair(figure(canvas()))
HAIRED_BACK = tail(hair(figure(canvas())), 299)
BACK, LONG, MATCH = ghost(299), ghost(399), ghost(305)


def rembg_stub(data, model="u2net", **kwargs):
    from PIL import Image
    with Image.open(io.BytesIO(data)) as im:
        arr = np.asarray(im.convert("RGB")).astype(np.int16)
    mask = (np.abs(arr - 128) > 2).any(2)
    return png((mask * 255).astype(np.uint8))


def load_earlier(commit: str, names) -> None:
    """Register ``app.core.<name>`` as of ``commit`` for each name (before
    anything imports them)."""
    import app.core as core
    for name in names:
        rel = f"app/core/{name}.py"
        source = subprocess.run(["git", "show", f"{commit}:{rel}"], cwd=ROOT, capture_output=True, text=True,
                                check=True).stdout
        module = types.ModuleType(f"app.core.{name}")
        module.__file__ = str(ROOT / rel)
        sys.modules[f"app.core.{name}"] = module
        exec(compile(source, f"{commit}:{rel}", "exec"), module.__dict__)
        setattr(core, name, module)


def run_arm(arm: str) -> dict:
    """Run the scenarios on ``new`` or an earlier arm (``ARMS``); returns the
    observations (JSON-able)."""
    if arm in ARMS:
        load_earlier(*ARMS[arm])
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

        from app.core import base_body, expression_regen, garment_hair, garment_images, garment_mesh, garments
        from app.core import garment_store as gs
        from app.models import character as charmod
        from app.models.character import (get_character_dir, get_character_images_dir, get_character_profile,
                                          save_character_profile)

        renders, prompts = [], {}
        plan = {"front": [], "back": [], "swap_base": False}
        refs_holder = {}
        charmod.run_rembg = rembg_stub

        def recorder(character_name, *, output_stem, **kw):
            g = kw["sidecar_extra"]["garment"]
            key = f"{g['step']} {g['view'][0]}{g['attempt']}"
            renders.append(key)
            prompts[key] = kw.get("bare_prompt") or ""
            if g["step"] == "haired":
                arr = HAIRED_BACK if g["view"] == "back" else HAIRED
                if plan["swap_base"]:
                    plan["swap_base"] = False
                    (refs_holder["refs"] / f"tpose_{refs_holder['bsig']}.png").write_bytes(png(BASE_TOUCHED))
            elif g["view"] == "back":
                arr = plan["back"].pop(0) if plan["back"] else BACK
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

        def accepted_bottom(fsig):
            rec = gs.read_record(gs.garment_path("Demo", hid, fsig, "image", step="ghost", view="front")
                                 .with_suffix(".json"))
            gate = (rec.get("gates") or {}).get(("first", "second")[int(rec.get("attempt") or 1) - 1]) or {}
            return [rec.get("accepted"), gate.get("bottom")]

        def run(label, **kw):
            del renders[:]
            prompts.clear()
            res = garments.run_garment("Demo", hid, **kw)
            gates = res.get("gates") or {}
            attempts = gates.get("attempts") if isinstance(gates, dict) else None
            obs[label] = {"renders": list(renders), "ok": res.get("ok"), "step": res.get("step"),
                          "error": res.get("error"), "fsig": res.get("fsig"), "ran": res.get("ran"),
                          "gates_view": gates.get("view") if isinstance(gates, dict) else None,
                          "attempt_reasons": [a.get("reasons") for a in attempts] if attempts else None,
                          "prompts": dict(prompts)}
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
        plan["front"], plan["back"] = [LONG], [LONG]
        run("3b", steps="ghost", view="back", force=True)
        obs["3b"]["front"] = accepted_bottom(f1)
        plan["front"], plan["back"] = [], []
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
                                                 {"bottom": 0.24917, "hair_h": 0.1725}),
                           "length": gg.hair_length(BASE, (np.abs(BASE.astype(int) - 128) > 2).any(2),
                                                    HAIRED_BACK, (np.abs(HAIRED_BACK.astype(int) - 128) > 2).any(2)),
                           "phrases": [garment_hair.length_phrase(t, "her")
                                       for t in (0.10, 0.18, 0.205, 0.23, 0.27, 0.33, 0.40, 0.50, None)]}
    return obs


def earlier(arm: str) -> dict:
    proc = subprocess.run([sys.executable, __file__, "--arm", arm], cwd=ROOT, capture_output=True, text=True)
    line = next((ln for ln in proc.stdout.splitlines() if ln.startswith("OBS ")), None)
    if line is None:
        print(proc.stdout[-3000:], proc.stderr[-3000:])
        check(f"{arm} arm ran", None, "observations")
        return {}
    return json.loads(line[4:])


def has(prompts: dict, key: str, text: str) -> bool:
    return text in (prompts.get(key) or "")


def main() -> int:
    if len(sys.argv) > 2 and sys.argv[1] == "--arm":
        print("OBS " + json.dumps(run_arm(sys.argv[2])))
        return 0
    old, prev = earlier("old"), earlier("prev")
    if not old or not prev:
        print("FAILED: " + ", ".join(FAILS))
        return 1
    new = run_arm("new")
    from app.core.garments import INPUTS_CHANGED_ERROR

    print("[1] fresh run, every front ghost LONG")
    check("new renders", new["1"]["renders"], ["haired b1", "haired f1", "ghost b1", "ghost f1", "ghost f2"])
    check("new refused at ghost front", (new["1"]["ok"], new["1"]["step"], new["1"]["gates_view"]),
          (False, "ghost", "front"))
    check("new attempt reasons", new["1"]["attempt_reasons"], [[BOTTOM_REASON], [BOTTOM_REASON]])
    check("new: no accepted front", new["1"]["front"], [None, None])
    p1 = new["1"]["prompts"]
    check("new ghost front names the length", has(p1, "ghost f2", GHOST_FRONT_LENGTH), True)
    check("new haired front + back prompts name no length",
          [has(p1, k, " ends ") for k in ("haired f1", "haired b1", "ghost b1")], [False, False, False])
    check("prev renders (front first)", prev["1"]["renders"],
          ["haired f1", "haired b1", "ghost f1", "ghost b1", "ghost f1", "ghost f2"])
    pp = prev["1"]["prompts"]
    check("prev ghost front names no length", has(pp, "ghost f2", "hair ends"), False)
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

    print("[3b] forced back ghost, the kept front disagrees")
    check("new renders", new["3b"]["renders"], ["ghost b1", "ghost f1"])
    check("new ok, front follows the back", (new["3b"]["ok"], new["3b"]["front"]), (True, [True, 0.3325]))

    print("[4] base front view rewritten during the first haired render")
    check("new renders", new["4"]["renders"], ["haired b1"])
    check("new refused", (new["4"]["ok"], new["4"]["step"], new["4"]["error"]),
          (False, "haired", INPUTS_CHANGED_ERROR))
    check("new fsig moved on", new["4"]["current_fsig"] != new["f1"], True)
    check("old carries on under the stale fsig",
          (old["4"]["renders"], old["4"]["ok"], old["4"]["fsig"] == old["f1"],
           old["4"]["current_fsig"] != old["f1"]),
          (["haired f1", "haired b1", "ghost f1", "ghost b1"], True, True, True))

    print("[5] plain run on the new fsig")
    check("renders", new["5"]["renders"], ["haired b1", "haired f1", "ghost b1", "ghost f1"])
    check("ok on the current fsig", (new["5"]["ok"], new["5"]["fsig"] == new["5"]["current_fsig"]), (True, True))
    p5 = new["5"]["prompts"]
    check("only the ghost front names the length",
          [has(p5, "haired f1", " ends "), has(p5, "ghost f1", GHOST_FRONT_LENGTH)], [False, True])

    print("[6] units")
    unit = new["unit"]
    check("agree -> None", unit["agree_none"], None)
    check("unmeasured -> None", unit["missing_none"], None)
    check("gap", [round(unit["gap"][0], 5), round(unit["gap"][1], 5)], [0.08333, 0.01279])
    check("hair_length of HAIRED_BACK", unit["length"], {"bottom": 299, "t": 0.1992})
    check("length phrases", unit["phrases"],
          ["at her chin", "at her shoulders", "at the top of her shoulder blades",
           "at the top of her shoulder blades", "at the middle of her shoulder blades",
           "at the middle of her back", "at her waist", "below her waist", ""])

    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
