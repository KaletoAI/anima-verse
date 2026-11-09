#!/usr/bin/env python3
"""Smoke: the model side overview (steps) and the image freshness badges
(app/core/model_overview.py).

Usage:
    ./.venv/bin/python scripts/smoke_model_overview.py

Runs without the server, against a temp storage dir; no render, no Blender.
Expected values, derived by hand from the fixtures below:

[1] base_model_steps on fixture A (a base model sidecar; front hand gate
    failed twice, kept attempt 2 with score 0.07, limit 0.05; covered variant
    file present but built from another prerig source):
      hand_gate        warning "palms may face the camera — kept attempt 2 of 2
                       without a pass", numbers score 0.07 limit 0.05 attempts 2
      mesh             done "MV · 4 views" (source + back/left/right)
      face_retexture   done "FR · face view", texels_replaced 400
      dark_gate        done "passed after a retry (retry kept) · 1.2 % dark vs
                       photo 0.4 %" (0.012 / 0.004 as percent, one decimal)
      rig              done "mixamo · RG"
      head_twist       done "corrected 5.5°": head -6.0 -> -0.5 = -5.5, neck
                       -1.0 -> -1.0 = 0; the larger magnitude is 5.5
      normalize        done "×1.2500 · 1.70 m", height 1.36 -> 1.7
      limb_weights     done "12 vertices repaired"
      extension_rig    done "g1, g2", groups 2
      covered_variant  warning "without g2 · built from another clean source"
      texture          done "2.0 MB saved" (2097152 bytes / 1048576)
      measure          done "120,000 tris · 56 bones · h 1.70 m"
    Variants: face failed "boom" -> one face row, failed, no dark_gate row;
    face applied without a dark_gate -> dark_gate "missing"; dark_gate ok
    False -> warning starting with its warning text.
[2] outfit_model_steps on fixture B (built on base1/S1 while the current
    base is base2/S2; rigged although the pieces call for covered and no
    covered variant existed; left view turned and left out; back fit kept
    without a pass; back refit kept 5.9 -> 3.1; hair fitted under fsig f1
    while the current fsig is f2):
      base             warning "base1 · older base body (now base2)"
      variant          warning "rigged · hidden by Long coat · shown through
                       Sheer top (exposed detail) · No covered variant"
      dressed_front    done "view check front · ΔE 2.9"
      dressed_back     warning = the fit gate's warning; noise 1.9 (attempt 2)
      dressed_left     warning "turned around — left out of the model · view
                       check front · re-rendered"
      back_refit       done "refit kept: ΔE 5.9 → 3.1"
      retexture        done "coverage 25.0 % · unseen 50.0 % · ΔE front 2.9 ·
                       ΔE back 3.1" (both <= 4.0)
      face_texels      done "120 of 4,000 texels"
      rig              done "mixamo · RG · from the base model"
      extension_rig    done "g1 · inherited from the base model" (same
                       fingerprint and attempted_at as the base's)
      garment_hair1    warning "Bob · hairdeck · fsig f1 · older fit"
      garment_warnings warning "full: joint missing"
      measure          done; lod done "20,000 tris"
    Back refit without a record: back ΔE 5.9 > 4.0 -> "missing" (built
    before the refit); ΔE 3.0 -> skipped "not needed (ΔE 3.0 ≤ 4.0)".
    A back ΔE of 5.0 in the proof -> retexture warning "… · poor
    registration: back".
[3] freshness rules (pure):
      dressed  {b1, sha x} vs (b1, x) current; vs (b1, y) stale "Made from
               an older base view"; vs (b2, x) stale "Made from an older base
               body"; {} missing
      draft    {b1, front f} vs (b1, f) current; (b1, g) stale "Made from an
               older dressed front"; (b2, g) stale both, base first
      base view back 16:00 vs front 17:00 stale "Made from an older front
               view"; back 18:00 current; the front itself current; no stamp
               missing
      base model {F, back B} vs current {F, B} current; back B2 stale "Base
               views re-rendered since this model"; no source sha missing
      model3d  nearest + stale_base detail_changed -> stale "Stand-in: model
               of another outfit · Built for another body detail under the
               clothing"; old path tpose changed -> "Pose render changed since
               this model"; pipeline + views newer -> "Dressed views
               re-rendered since this model"; old path tpose unknown ->
               missing; exact pipeline -> current
      hair     no preview missing; accepted current-fsig fit current; refused
               fit with colour+placement reasons -> stale "Hair colour changed
               · Hair placement changed"; no reasons -> "An older fit is shown"
      dressed_newer  model 16:00, a view 16:05 -> True; a view 15:00 -> False
[4] IO on a temp world (character "Ann", base signature base0000aaaa):
    base front written 10:00 with a passing hand gate, base back 09:00, base
    model sidecar = fixture A with the real hashes of front + back, covered
    variant built from the stored prerig bytes:
      annotate_base_info: image_meta front current, back stale "Made from an
      older front view"; model.steps[0] hand_gate done "passed on attempt 1 of
      1"; covered_variant done "without g2"; model.freshness current.
      The front rewritten with other bytes -> model.freshness stale "Base
      views re-rendered since this model".
    annotate_hair: every image and attempt current, the fit step untouched,
    preview current, the other method's preview stale "Fitted on an older
    base model".
    annotate_model3d_info with filename "../x": no steps (path refused),
    freshness current. Garbage payloads come back without raising.
[5] Wiring: the four info routes in app/routes/characters.py call their
    annotate_* function (AST).
"""
import ast
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FAILS = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok ' if ok else 'FAIL'} {label}" + ("" if ok else f"\n       got:  {got!r}\n       want: {want!r}"))
    if not ok:
        FAILS.append(label)


FIXTURE_A = {
    "source_image": "tpose_base0000aaaa.png",
    "view_images": {"back": "b.png", "left": "l.png", "right": "r.png"},
    "source_image_sha256": "F", "view_images_sha256": {"back": "B"},
    "base": True, "mesh_backend": "MV", "rig": "mixamo", "rig_backend": "RG",
    "face_retexture": {"status": "applied", "backend": "FR", "reference": "face",
                       "baked": {"texels_replaced": 400, "body_texels_recolored": 9000},
                       "dark_gate": {"ok": True, "retried": True, "chosen": "retry", "dark_share": 0.012,
                                     "photo_dark_share": 0.004, "excess": 0.008, "limit": 0.01,
                                     "retry_yaw": 12.0}},
    "blender": {"steps": ["normalize", "limb_weights"], "scale": 1.25, "target_height_m": 1.7,
                "before": {"dims_m": [0.5, 0.3, 1.36]}, "after": {"dims_m": [0.6, 0.4, 1.7]},
                "head_twist": {"before": {"head": -6.0, "neck": -1.0}, "after": {"head": -0.5, "neck": -1.0},
                               "corrected": True},
                "limb_weights": {"vertices": 12, "fully_foreign": 3, "unresolved": 0}},
    "extension_rig": {"status": "applied", "groups": ["g1", "g2"]},
    "covered_variant": {"status": "built", "groups_removed": ["g2"]},
    "refined": {"retexture": True, "bytes_saved": 2097152},
    "measured": {"tris": 120000, "bones": 56, "dims_m": [0.6, 0.4, 1.7]},
}

FIXTURE_B = {
    "source": "base_body", "base_signature": "base1", "base_model_sha256": "S1", "base_variant": "rigged",
    "covered_missing": True, "dressed": True,
    "source_image": "tpose_o1.png", "view_images": {"back": "tpose_back_o1.png"},
    "view_guard": {"front": {"ok": True, "best": "front", "scores": {"front": 0.98}},
                   "back": {"ok": True, "best": "back", "scores": {"back": 0.95}},
                   "left": {"ok": False, "best": "front", "scores": {"left": 0.6}, "rerendered": True}},
    "back_refit": {"limit": 4.0, "attempts": [{"unchanged_delta_e": 5.9}, {"unchanged_delta_e": 3.1}], "chosen": 2},
    "retexture_proof": {"views": {"front": {"dressed_alignment": {"unchanged_delta_e": 2.9}},
                                  "back": {"dressed_alignment": {"unchanged_delta_e": 3.1}}},
                        "texels": {"garment_share_of_exposed": 0.25,
                                   "unseen_filled_share_of_exposed_garment": 0.5,
                                   "unobserved_share_of_exposed": 0.3},
                        "face_texels_restored": 120, "face_mask_texels": 4000},
    "rig": "mixamo", "rig_backend": "RG",
    "extension_rig": {"status": "applied", "groups": ["g1"], "fingerprint": "X", "attempted_at": "t1"},
    "garment_warnings": ["full: joint missing"],
    "measured": {"tris": 90000, "bones": 54, "dims_m": [0.5, 0.3, 1.7]},
}
BACK_WARNING = "Dressed back may be grainy (back check failed after 2 attempts)"


def rows_of(steps):
    return [(s["id"], s["status"], s["detail"]) for s in steps]


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="smoke_model_overview_"))
    os.environ["STORAGE_DIR"] = str(tmp / "world")
    os.environ["INSTANCE_DIR"] = str(tmp / "instance")
    from app.core import paths
    paths.init(str(tmp / "world"))
    from app.core import model_overview as mo

    print("[1] base model steps")
    front_meta = {"hand_gate": {"ok": False, "chosen": 2, "limit": 0.05,
                                "attempts": [{"score": 0.09}, {"score": 0.07}]}}
    steps = mo.base_model_steps(FIXTURE_A, front_meta=front_meta, covered_exists=True, covered_current=False)
    check("rows", rows_of(steps), [
        ("hand_gate", "warning", "palms may face the camera — kept attempt 2 of 2 without a pass"),
        ("mesh", "done", "MV · 4 views"),
        ("face_retexture", "done", "FR · face view"),
        ("dark_gate", "done", "passed after a retry (retry kept) · 1.2 % dark vs photo 0.4 %"),
        ("rig", "done", "mixamo · RG"),
        ("head_twist", "done", "corrected 5.5°"),
        ("normalize", "done", "×1.2500 · 1.70 m"),
        ("limb_weights", "done", "12 vertices repaired"),
        ("extension_rig", "done", "g1, g2"),
        ("covered_variant", "warning", "without g2 · built from another clean source"),
        ("texture", "done", "2.0 MB saved"),
        ("measure", "done", "120,000 tris · 56 bones · h 1.70 m"),
    ])
    check("hand numbers", steps[0]["numbers"], {"score": 0.07, "limit": 0.05, "attempts": 2})
    check("face numbers", steps[2]["numbers"]["texels_replaced"], 400.0)
    check("normalize numbers", (steps[6]["numbers"]["height_before_m"], steps[6]["numbers"]["height_after_m"]),
          (1.36, 1.7))
    check("labels", [s["label"] for s in steps][:4],
          ["Front view hand check", "Mesh", "Face retexture", "Black-eye check"])
    failed = {**FIXTURE_A, "face_retexture": {"status": "failed", "error": "boom"}}
    face_rows = [r for r in rows_of(mo.base_model_steps(failed, front_meta=None)) if r[0] in ("face_retexture", "dark_gate")]
    check("face failed", face_rows, [("face_retexture", "failed", "boom")])
    old = {**FIXTURE_A, "face_retexture": {"status": "applied"}}
    check("no dark gate recorded", [r[1] for r in rows_of(mo.base_model_steps(old, front_meta=None))
                                    if r[0] == "dark_gate"], ["missing"])
    dark = {**FIXTURE_A, "face_retexture": {"status": "applied", "dark_gate": {
        "ok": False, "dark_share": 0.05, "photo_dark_share": 0.01, "warning": "dark face"}}}
    row = [r for r in rows_of(mo.base_model_steps(dark, front_meta=None)) if r[0] == "dark_gate"][0]
    check("dark gate warning", (row[1], row[2].startswith("dark face")), ("warning", True))
    check("no front", steps and mo.base_model_steps(FIXTURE_A, front_meta=None)[0]["status"], "missing")

    print("[2] outfit model steps")
    records = {"front": {}, "back": {"fit_gate": {"ok": False, "chosen": 2, "noise_limit": 1.75,
                                                  "attempts": [{"noise": {"score": 2.4}}, {"noise": {"score": 1.9}}],
                                                  "warning": BACK_WARNING}},
               "left": None}
    garments = [{"item_id": "hair1", "name": "Bob", "kind": "hair", "method": "hairdeck", "fsig": "f1",
                 "current_fsig": "f2", "served": True}]
    steps = mo.outfit_model_steps(FIXTURE_B, base=("base2", "S2"),
                                  base_meta={"extension_rig": {"fingerprint": "X", "attempted_at": "t1"}},
                                  wanted_variant="covered", deciders=["Long coat"], shown=["Sheer top"],
                                  dressed_records=records, garments=garments, tiers=["full", "low"],
                                  low_tris=20000, refit_limit=4.0, covered_missing_text="No covered variant")
    check("rows", rows_of(steps), [
        ("base", "warning", "base1 · older base body (now base2)"),
        ("variant", "warning",
         "rigged · hidden by Long coat · shown through Sheer top (exposed detail) · No covered variant"),
        ("dressed_front", "done", "view check front · ΔE 2.9"),
        ("dressed_back", "warning", BACK_WARNING),
        ("dressed_left", "warning", "turned around — left out of the model · view check front · re-rendered"),
        ("back_refit", "done", "refit kept: ΔE 5.9 → 3.1"),
        ("retexture", "done", "coverage 25.0 % · unseen 50.0 % · ΔE front 2.9 · ΔE back 3.1"),
        ("face_texels", "done", "120 of 4,000 texels"),
        ("rig", "done", "mixamo · RG · from the base model"),
        ("extension_rig", "done", "g1 · inherited from the base model"),
        ("garment_hair1", "warning", "Bob · hairdeck · fsig f1 · older fit"),
        ("garment_warnings", "warning", "full: joint missing"),
        ("measure", "done", "90,000 tris · 54 bones · h 1.70 m"),
        ("lod", "done", "20,000 tris"),
    ])
    check("back numbers", {k: steps[3]["numbers"].get(k) for k in ("noise", "noise_limit", "fit_attempts")},
          {"noise": 1.9, "noise_limit": 1.75, "fit_attempts": 2})
    check("hair label", steps[10]["label"], "Hair")
    no_refit = {k: v for k, v in FIXTURE_B.items() if k != "back_refit"}
    no_refit["retexture_proof"] = {**FIXTURE_B["retexture_proof"], "views": {
        "back": {"dressed_alignment": {"unchanged_delta_e": 5.9}}}}
    row = [s for s in mo.outfit_model_steps(no_refit, base=None, base_meta=None, wanted_variant=None, deciders=[],
                                            shown=[], dressed_records={}, garments=[], tiers=[])
           if s["id"] == "back_refit"][0]
    check("refit before the step", row["status"], "missing")
    no_refit["retexture_proof"]["views"]["back"]["dressed_alignment"]["unchanged_delta_e"] = 3.0
    row = [s for s in mo.outfit_model_steps(no_refit, base=None, base_meta=None, wanted_variant=None, deciders=[],
                                            shown=[], dressed_records={}, garments=[], tiers=[])
           if s["id"] == "back_refit"][0]
    check("refit not needed", (row["status"], row["detail"]), ("skipped", "not needed (ΔE 3.0 ≤ 4.0)"))
    poor = {**FIXTURE_B, "retexture_proof": {**FIXTURE_B["retexture_proof"], "views": {
        "back": {"dressed_alignment": {"unchanged_delta_e": 5.0}}}}}
    row = [s for s in mo.outfit_model_steps(poor, base=None, base_meta=None, wanted_variant=None, deciders=[],
                                            shown=[], dressed_records={}, garments=[], tiers=[])
           if s["id"] == "retexture"][0]
    check("poor registration", (row["status"], row["detail"].endswith("poor registration: back")),
          ("warning", True))

    print("[3] freshness rules")
    C, S, M = "current", "stale", "missing"
    st = lambda f: (f["state"], f["reason"])  # noqa: E731
    d = {"base_signature": "b1", "base_image_sha256": "x"}
    check("dressed current", mo.dressed_freshness(d, bsig="b1", base_view_sha="x")["state"], C)
    check("dressed view", st(mo.dressed_freshness(d, bsig="b1", base_view_sha="y")), (S, "Made from an older base view"))
    check("dressed base", st(mo.dressed_freshness(d, bsig="b2", base_view_sha="x")), (S, "Made from an older base body"))
    check("dressed none", mo.dressed_freshness({}, bsig="b1", base_view_sha="x")["state"], M)
    d = {"base_signature": "b1", "front_sha256": "f"}
    check("draft current", mo.draft_freshness(d, bsig="b1", front_sha="f")["state"], C)
    check("draft front", st(mo.draft_freshness(d, bsig="b1", front_sha="g")), (S, "Made from an older dressed front"))
    check("draft both", st(mo.draft_freshness(d, bsig="b2", front_sha="g")),
          (S, "Made from an older base body · Made from an older dressed front"))
    t16, t17, t18 = ("2026-11-09T16:00:00+00:00", "2026-11-09T17:00:00+00:00", "2026-11-09T18:00:00+00:00")
    check("base back older", st(mo.base_view_freshness("back", t16, t17)), (S, "Made from an older front view"))
    check("base back newer", mo.base_view_freshness("back", t18, t17)["state"], C)
    check("base front", mo.base_view_freshness("front", t16, t17)["state"], C)
    check("base no stamp", mo.base_view_freshness("left", "", t17)["state"], M)
    meta = {"source_image_sha256": "F", "view_images_sha256": {"back": "B"}}
    check("base model current", mo.base_model_freshness(meta, {"front": "F", "back": "B", "left": "L"})["state"], C)
    check("base model stale", st(mo.base_model_freshness(meta, {"front": "F", "back": "B2"})),
          (S, "Base views re-rendered since this model"))
    check("base model none", mo.base_model_freshness({}, {"front": "F"})["state"], M)
    check("model3d nearest", st(mo.model3d_freshness({"match": "nearest", "stale_base": True,
                                                      "stale_reason": "detail_changed", "base_signature": "b"})),
          (S, "Stand-in: model of another outfit · Built for another body detail under the clothing"))
    check("model3d pose", st(mo.model3d_freshness({"match": "exact", "tpose_status": "changed"})),
          (S, "Pose render changed since this model"))
    check("model3d views", st(mo.model3d_freshness({"match": "exact", "base_signature": "b"}, views_newer=True)),
          (S, "Dressed views re-rendered since this model"))
    check("model3d unknown", mo.model3d_freshness({"match": "exact", "tpose_status": "unknown"})["state"], M)
    check("model3d current", mo.model3d_freshness({"match": "exact", "base_signature": "b",
                                                   "tpose_status": "unknown"})["state"], C)
    check("hair none", mo.hair_preview_freshness({"preview_url": None})["state"], M)
    check("hair current", mo.hair_preview_freshness({"preview_url": "u", "fsig": "f",
                                                     "steps": {"fit": {"status": "accepted"}}})["state"], C)
    check("hair reasons", st(mo.hair_preview_freshness({"preview_url": "u", "fsig": "f",
                                                        "steps": {"fit": {"status": "refused"}},
                                                        "stale_reasons": ["colour_changed", "placement_changed"]})),
          (S, "Hair colour changed · Hair placement changed"))
    check("hair older", st(mo.hair_preview_freshness({"preview_url": "u", "fsig": None, "stale_reasons": []})),
          (S, "An older fit is shown"))
    check("dressed newer", mo.dressed_newer(t16, {"front": {"created_at": "2026-11-09T16:05:00+00:00"}}), True)
    check("dressed older", mo.dressed_newer(t16, {"front": {"created_at": "2026-11-09T15:00:00+00:00"},
                                                  "back": None}), False)

    print("[4] IO on a temp world")
    bsig = "base0000aaaa"
    char = Path(paths.get_storage_dir()) / "characters" / "Ann"
    refs, models = char / "model_refs", char / "model3d"
    for d in (refs, models / "covered", models / "prerig"):
        d.mkdir(parents=True, exist_ok=True)
    (refs / f"tpose_{bsig}.png").write_bytes(b"front-1")
    (refs / f"tpose_{bsig}.json").write_text(json.dumps({
        "created_at": t17.replace("17:", "10:"), "base_signature": bsig,
        "hand_gate": {"ok": True, "chosen": 1, "limit": 0.05, "attempts": [{"score": 0.03}]}}))
    (refs / f"tpose_back_{bsig}.png").write_bytes(b"back-1")
    (refs / f"tpose_back_{bsig}.json").write_text(json.dumps({"created_at": "2026-11-09T09:00:00+00:00"}))
    sha = lambda b: hashlib.sha256(b).hexdigest()  # noqa: E731
    (models / f"{bsig}.glb").write_bytes(b"glb")
    (models / f"{bsig}.json").write_text(json.dumps({**FIXTURE_A, "source_image_sha256": sha(b"front-1"),
                                                     "view_images_sha256": {"back": sha(b"back-1")}}))
    (models / "prerig" / f"{bsig}.glb").write_bytes(b"prerig")
    (models / "covered" / f"{bsig}.glb").write_bytes(b"covered")
    (models / "covered" / f"{bsig}.json").write_text(json.dumps({"source_sha256": sha(b"prerig")}))
    info = {"signature": bsig, "image_meta": {"front": {"created_at": "2026-11-09T10:00:00+00:00"},
                                              "back": {"created_at": "2026-11-09T09:00:00+00:00"}, "left": None},
            "model": {"status": "ready"}}
    out = mo.annotate_base_info("Ann", info)
    check("front tile", out["image_meta"]["front"]["freshness"]["state"], C)
    check("back tile", st(out["image_meta"]["back"]["freshness"]), (S, "Made from an older front view"))
    check("model step 0", rows_of(out["model"]["steps"])[0], ("hand_gate", "done", "passed on attempt 1 of 1"))
    check("covered current", [r for r in rows_of(out["model"]["steps"]) if r[0] == "covered_variant"],
          [("covered_variant", "done", "without g2")])
    check("model fresh", out["model"]["freshness"]["state"], C)
    (refs / f"tpose_{bsig}.png").write_bytes(b"front-2 longer")
    out = mo.annotate_base_info("Ann", {"signature": bsig, "image_meta": {}, "model": {"status": "ready"}})
    check("model stale", st(out["model"]["freshness"]), (S, "Base views re-rendered since this model"))

    hair = {"garment": {"fsig": "f", "preview_url": "p", "stale_reasons": [],
                        "steps": {"haired": {"front": {"url": "u", "attempts": [{"attempt": 1, "url": "a"}]}},
                                  "fit": {"status": "accepted"}}},
            "hairdeck": {"images": {"input": {"url": "i"}, "prep": None}},
            "other": {"on_current_base": False}}
    out = mo.annotate_hair(hair)
    tile = out["garment"]["steps"]["haired"]["front"]
    check("hair tile", (tile["freshness"]["state"], tile["attempts"][0]["freshness"]["state"]), (C, C))
    check("fit untouched", "freshness" in out["garment"]["steps"]["fit"], False)
    check("hair preview", out["garment"]["preview_freshness"]["state"], C)
    check("hairdeck tile", out["hairdeck"]["images"]["input"]["freshness"]["state"], C)
    check("other preview", st(out["other"]["preview_freshness"]), (S, "Fitted on an older base model"))
    out = mo.annotate_model3d_info("Ann", {"model": {"filename": "../x", "match": "exact", "base_signature": "b"}})
    check("traversal refused", ("steps" in out["model"], out["model"]["freshness"]["state"]), (False, C))
    for fn, payload in ((lambda p: mo.annotate_base_info("Ann", p), {"signature": bsig, "image_meta": "x"}),
                        (lambda p: mo.annotate_model3d_info("Ann", p), {"model": "x"}),
                        (lambda p: mo.annotate_model_refs_info("Ann", p), {"views": 3}),
                        (mo.annotate_hair, {"garment": {"steps": 7}})):
        try:
            fn(payload)
            raised = False
        except Exception:  # noqa: BLE001
            raised = True
        check(f"no raise {sorted(payload)}", raised, False)

    print("[5] route wiring")
    tree = ast.parse((ROOT / "app" / "routes" / "characters.py").read_text(encoding="utf-8"))
    want = {"get_character_base_body": "annotate_base_info", "get_character_model3d": "annotate_model3d_info",
            "get_character_model_refs": "annotate_model_refs_info", "get_character_hair": "annotate_hair"}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in want:
            calls = {n.func.id for n in ast.walk(node) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
            check(f"{node.name} -> {want[node.name]}", want[node.name] in calls, True)
            want[node.name] = None
    check("all four routes found", [k for k, v in want.items() if v], [])

    print(f"\n{'FAILED: ' + ', '.join(FAILS) if FAILS else 'all checks passed'}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
