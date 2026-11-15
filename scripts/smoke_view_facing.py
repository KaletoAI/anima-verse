#!/usr/bin/env python3
"""Ruling A91: which way a side view's figure faces, the automatic mirror of a sure-wrong one and the manual
Mirror toggle (``app/core/view_facing.py``; the hooks in ``base_body`` / ``model_refs``; the two mirror routes).

Usage:
    ./.venv/bin/python scripts/smoke_view_facing.py

Runs against a THROWAWAY storage + instance directory — no world DB, no hub, no GPU, no server: every socket
connect raises, so a check that reached out would fail loudly. The real side views are three small
silhouette copies in ``scripts/fixtures/view_facing/`` (a dressed left view, a dressed right view, a cat's
right view of a live world, 320 px high, alpha only).

THE CONVENTION (``view_facing`` module docstring): the ``left`` view faces the LEFT edge of the image, the
``right`` view the RIGHT edge.

THE DETECTOR, by hand (``measure_mask``): in the bottom ``FOOT_BAND`` = 12 % of the figure each connected part
splits into its top ``LEG_ROWS`` = 30 % (the leg, its mean x) and its bottom ``SOLE_ROWS`` = 30 % (the sole,
its min/max x); part score = ((max − leg) − (leg − min)) / (max − min), weighted by area;
confidence = min(1, |score| / 0.4), halved when a part of |score| ≥ 0.15 points the other way.

Synthetic figure (``figure()``): 400 rows (top row 0, bottom 399), so the band is rows 399 − int(0.12·400) =
351 … 399 = 49 rows; a leg x 100…119 from row 300 down to 389, a foot rows 390…399 x 95…159 (toes to the
right). The band holds ONE part (leg + foot), rows 0…48 of the band: leg rows y ≤ 0 + 0.3·49 = 14.7 → band rows
0…14, all x 100…119 → leg = 109.5; sole rows y ≥ 48 − 14.7 = 33.3 → band rows 34…48 = image rows 385…399:
x 100…119 (385…389) and 95…159 (390…399) → min 95, max 159.

[1] Synthetic silhouettes.
    a) toes right: score = ((159 − 109.5) − (109.5 − 95)) / 64 = 35 / 64 = 0.546875 → 0.547, facing right,
       confidence 1.0 (0.547 ≥ 0.4); judged ``ok`` as a right view, ``wrong`` as a left view.
    b) the same mirrored: score −0.547, facing left.
    c) a short toe, foot x 95…134: score = ((134 − 109.5) − 14.5) / 39 = 10 / 39 = 0.2564 → 0.256, confidence
       0.2564 / 0.4 = 0.641 < AUTO_CONFIDENCE 0.75 → ``unsure`` either way.
    d) a stride: the a) leg + foot and, x + 150, its mirror image about its own leg (leg x 250…269, foot
       x 210…274, the same pixel count): parts [0.547, −0.547], score 0, confidence 0 → ``unsure``.
    e) no matte (an RGB image) → None; a figure 100 px high (< MIN_FIGURE_PX 120) → None; ``judge`` of None
       → ``unsure``.
[2] The real copies (hand-labelled on the full-size views): dressed_left faces left, dressed_right faces right,
    animal_right faces right — each ``ok`` for its view with confidence ≥ 0.75; each mirrored copy ``wrong``.
[3] The Mirror round trip on a stored view ``tpose_left_<BSIG>.png`` (an RGBA PNG carrying a text chunk, so a
    re-encode of the same pixels gives OTHER bytes) with a sidecar {created_at, prompt_fingerprint, base_signature}:
    toggle 1 → ``mirrored`` True; the file's pixels = the original's flipped left-right; ``mirrored/<name>`` =
    the original bytes; the sidecar gains ``mirrored`` {auto False, original_sha256, mirrored_sha256} and
    ``mirror_changed_at``, its other keys unchanged. Toggle 2 → the file is the ORIGINAL BYTES (sha equal), the
    kept original is gone, no ``mirrored`` key, the other keys still unchanged. A file re-rendered under a
    stale record (record kept, bytes replaced) is not restorable: turning back flips its pixels instead.
[4] The automatic path (``auto_correct`` / ``match_facing``): a toes-left image as a RIGHT view (sure wrong) →
    mirrored, record {auto True, confidence 1.0, reason "faced the left edge; the right view faces the right
    edge"}, the file then measures facing right; the same image as a LEFT view → None, bytes unchanged; the c)
    image (unsure) as a left view → None, bytes unchanged. A draft for the RIGHT view composited onto a base
    right view that measures facing LEFT (sure) follows the base: a toes-right draft is mirrored to face left,
    and no original is kept (no ``mirrored/`` dir).
[5] Freshness and fingerprints. ``model_overview.base_model_freshness`` of a model recording the left view's
    sha: ``current`` before the mirror, ``stale`` (changed_views [left]) after it, ``current`` again after the
    toggle back. ``base_view_freshness`` of the view (its sidecar's created_at vs the front's, the recorded
    prompt fingerprint vs the current one) is ``current`` before and after — the mirror never makes the view
    re-render. ``dressed_changed`` of a model built 2000-01-01 from a view created 1999-12-31: [] before the
    mirror, [left] after it (``mirror_changed_at``). ``mirror_followup`` (``model3d`` stubbed: stages
    [mesh, rig]): no model → no_model/0; a model built from the current bytes → stale/2; mirrored, the model
    built from the original → restores/0; a model built from a third content → already_stale/2; a model
    without the view → unused/0.
[6] ``base_body.mirror_base_view`` (base signature stubbed): "back" → ValueError; a reserved view
    (``reserve_views``) → MirrorRefused; then toggle → {mirrored True, facing.state "ok"... of the flipped toes-
    left image as a left view = toes right → "wrong"}; the route maps 400/404/409. The cache GC lists the kept
    original under the base signature (``outfit_cache_gc._ref_files``).
[6b] The worn outfit's side view (``model_refs.mirror_outfit_view``, off the pipeline, outfit state stubbed): the
    route mirrors a toes-left right view → facing right, ``ok``; again → turned back; ``tpose_back`` → 400; on
    the pipeline a view that is a copy of the body's view (``dressed_view_source`` ``plain``) → 400 with
    ``MIRROR_COPY_REFUSED``. Follow-up (``outfit_mirror_followup``): pipeline painted → repaint/0, a copy →
    copy/0; off it without a model → no_model/0, with one (stages mesh, upscale, face, rig) → model/4.
[7] The hooks are wired: the base side view render (``generate_base_images``) calls ``auto_correct`` for a side
    view, the off-pipeline extra views (``generate_model_ref_images``) too, the dressed view's two draft paths
    (``_dress_view``: the stored draft and a new one) call ``match_facing``.
"""
import hashlib
import inspect
import io
import json
import os
import shutil
import socket
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FIXTURES = ROOT / "scripts" / "fixtures" / "view_facing"

TMP = Path(tempfile.mkdtemp(prefix="smoke_view_facing_"))
os.environ["STORAGE_DIR"] = str(TMP / "world")
os.environ["INSTANCE_DIR"] = str(TMP / "instance")
os.environ["ANIMATION_CLIPS_DIR"] = str(TMP / "clips")
os.environ["ANIMATION_RIG_FILE"] = str(TMP / "reference.fbx")


def _no_net(*_a, **_kw):
    raise RuntimeError("outbound connection attempted")


socket.socket.connect = _no_net
socket.create_connection = _no_net

from app.core import paths  # noqa: E402

paths.init(TMP / "world")
paths.init_instance(TMP / "instance")

import numpy as np  # noqa: E402
from PIL import Image, ImageOps, PngImagePlugin  # noqa: E402

from app.core import view_facing as vf  # noqa: E402

FAILS = []
BSIG = "base0123abcd"


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


def figure(toe_to: int = 160, stride: bool = False) -> np.ndarray:
    """The synthetic figure of the docstring (toes right); ``toe_to`` the foot's end (exclusive)."""
    m = np.zeros((400, 400), dtype=bool)
    m[0:100, 150:220] = True          # head
    m[100:300, 100:270 if stride else 130] = True   # torso
    m[300:390, 100:120] = True        # leg
    m[390:400, 95:toe_to] = True      # foot
    if stride:
        m[300:390, 250:270] = True    # second leg
        m[390:400, 210:275] = True    # its foot, toes left (mirror of 95…159 about 109.5, + 150)
    return m


def png_bytes(mask: np.ndarray, text: str = "") -> bytes:
    """An RGBA PNG of ``mask`` (skin colour, alpha 255 inside, 0 outside), optionally with a text chunk."""
    h, w = mask.shape
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    rgba[..., 0], rgba[..., 1], rgba[..., 2] = 200, 160, 140
    rgba[..., 3] = np.where(mask, 255, 0)
    rgba[mask, 0] = (np.arange(w)[None, :].repeat(h, 0)[mask] % 251).astype(np.uint8)  # asymmetric pixels
    out = io.BytesIO()
    info = PngImagePlugin.PngInfo()
    if text:
        info.add_text("note", text)
    Image.fromarray(rgba, "RGBA").save(out, format="PNG", pnginfo=info)
    return out.getvalue()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def pixels(path: Path) -> np.ndarray:
    with Image.open(path) as im:
        return np.asarray(im.convert("RGBA"))


def section1():
    print("[1] synthetic silhouettes")
    a = vf.measure_mask(figure())
    check("a) toes right", (a["facing"], a["score"], a["confidence"], a["parts"]), ("right", 0.547, 1.0, [0.547]))
    check("a) judged as right / left view", (vf.judge("right", a), vf.judge("left", a)), ("ok", "wrong"))
    b = vf.measure_mask(figure()[:, ::-1])
    check("b) mirrored", (b["facing"], b["score"]), ("left", -0.547))
    c = vf.measure_mask(figure(toe_to=135))
    check("c) short toe", (c["facing"], c["score"], c["confidence"]), ("right", 0.256, 0.641))
    check("c) unsure either way", (vf.judge("right", c), vf.judge("left", c)), ("unsure", "unsure"))
    d = vf.measure_mask(figure(stride=True))
    check("d) stride parts", sorted(d["parts"]), [-0.547, 0.547])
    check("d) stride score/confidence/judge", (d["score"], d["confidence"], vf.judge("left", d)), (0.0, 0.0, "unsure"))
    rgb = TMP / "rgb.png"
    Image.new("RGB", (100, 400), (128, 128, 128)).save(rgb)
    check("e) no matte", vf.measure(rgb), None)
    check("e) too small", vf.measure_mask(figure()[::4, ::4]), None)
    check("e) judge of None", vf.judge("left", None), "unsure")


def section2():
    print("[2] real copies")
    for name, view, facing in (("dressed_left", "left", "left"), ("dressed_right", "right", "right"),
                               ("animal_right", "right", "right")):
        with Image.open(FIXTURES / f"{name}.png") as im:
            mask = np.asarray(im.convert("L")) > 127
        m = vf.measure_mask(mask)
        check(f"{name} facing / judge", (m["facing"], vf.judge(view, m)), (facing, "ok"))
        check(f"{name} confidence ≥ 0.75", m["confidence"] >= vf.AUTO_CONFIDENCE, True)
        check(f"{name} mirrored judged wrong", vf.judge(view, vf.measure_mask(mask[:, ::-1])), "wrong")


def stored_view(name: str, mask: np.ndarray, *, text: str = "rendered") -> Path:
    refs = TMP / "world" / "characters" / "Demo" / "model_refs"
    refs.mkdir(parents=True, exist_ok=True)
    path = refs / name
    path.write_bytes(png_bytes(mask, text))
    path.with_suffix(".json").write_text(json.dumps({
        "created_at": "1999-12-31T00:00:00+00:00", "prompt_fingerprint": "291f62eddcee",
        "base_signature": BSIG}), encoding="utf-8")
    return path


def section3():
    print("[3] the Mirror round trip")
    path = stored_view(f"tpose_left_{BSIG}.png", figure()[:, ::-1])
    original = path.read_bytes()
    before = vf.read_sidecar(path)
    check("re-encode differs (text chunk)", vf.mirrored_bytes(vf.mirrored_bytes(original)) != original, True)
    r1 = vf.toggle_mirror(path)
    meta = vf.read_sidecar(path)
    check("toggle 1 mirrored", r1["mirrored"], True)
    check("pixels flipped", bool((pixels(path) == np.asarray(ImageOps.mirror(Image.open(io.BytesIO(original))
                                                                            .convert("RGBA")))).all()), True)
    check("original kept byte for byte", (path.parent / "mirrored" / path.name).read_bytes() == original, True)
    check("record", (meta["mirrored"]["auto"], meta["mirrored"]["original_sha256"],
                     meta["mirrored"]["mirrored_sha256"]), (False, sha(original), sha(path.read_bytes())))
    check("other sidecar keys unchanged", {k: meta[k] for k in before}, before)
    check("mirror_changed_at stamped", bool(meta.get("mirror_changed_at")), True)
    check("restorable", vf.restorable(path), True)
    r2 = vf.toggle_mirror(path)
    meta = vf.read_sidecar(path)
    check("toggle 2 turned back", r2["mirrored"], False)
    check("ORIGINAL BYTES restored", sha(path.read_bytes()), sha(original))
    check("kept original gone", (path.parent / "mirrored" / path.name).exists(), False)
    check("no record", "mirrored" in meta, False)
    check("other keys still unchanged", {k: meta[k] for k in before}, before)
    # A re-render under a stale record: not restorable, turning back flips the new pixels.
    vf.toggle_mirror(path)
    rendered = png_bytes(figure(), "re-rendered")
    path.write_bytes(rendered)
    check("stale record not restorable", vf.restorable(path), False)
    vf.toggle_mirror(path)
    check("turned back by flipping", bool((pixels(path) == pixels_of(rendered)[:, ::-1]).all()), True)
    path.write_bytes(original)


def pixels_of(data: bytes) -> np.ndarray:
    return np.asarray(Image.open(io.BytesIO(data)).convert("RGBA"))


def section4():
    print("[4] the automatic path")
    path = stored_view(f"tpose_right_{BSIG}.png", figure()[:, ::-1])
    record = vf.auto_correct("right", path)
    check("sure wrong right view mirrored", (record or {}).get("auto"), True)
    check("record reason / confidence", (record["reason"], record["confidence"]),
          ("faced the left edge; the right view faces the right edge", 1.0))
    check("now faces right", vf.measure(path)["facing"], "right")
    left = stored_view(f"tpose_left_{BSIG}.png", figure()[:, ::-1])
    data = left.read_bytes()
    check("right-facing left view untouched", (vf.auto_correct("left", left), left.read_bytes() == data), (None, True))
    unsure = stored_view("tpose_left_0123456789ab.png", figure(toe_to=135))
    data = unsure.read_bytes()
    check("unsure view untouched", (vf.auto_correct("left", unsure), unsure.read_bytes() == data), (None, True))
    drafts = TMP / "drafts"
    drafts.mkdir(exist_ok=True)
    base = drafts / "base_right.png"
    base.write_bytes(png_bytes(figure()[:, ::-1]))           # the base right view faces LEFT (sure)
    draft = drafts / "tpose_right_0123456789ab.png"
    draft.write_bytes(png_bytes(figure()))                    # the draft faces right (the convention)
    check("draft follows its base view", ((vf.match_facing("right", draft, base) or {}).get("auto"),
                                          vf.measure(draft)["facing"]), (True, "left"))
    check("no original kept for a draft", (drafts / "mirrored").exists(), False)


def section5():
    print("[5] freshness and fingerprints")
    from app.core import base_body, model3d, model_overview
    path = stored_view(f"tpose_left_{BSIG}.png", figure()[:, ::-1])
    left0 = sha(path.read_bytes())
    meta = {"source_image_sha256": "frontsha", "view_images_sha256": {"left": left0}}
    shas = lambda: {"front": "frontsha", "left": sha(path.read_bytes())}  # noqa: E731
    check("model current before", model_overview.base_model_freshness(meta, shas())["state"], model_overview.CURRENT)
    side = vf.read_sidecar(path)
    view_state = lambda: model_overview.base_view_freshness(  # noqa: E731
        "left", vf.read_sidecar(path)["created_at"], "1999-12-30T00:00:00+00:00",
        prompts=(vf.read_sidecar(path)["prompt_fingerprint"], side["prompt_fingerprint"]))["state"]
    check("view current before", view_state(), model_overview.CURRENT)
    check("dressed_changed before", model_overview.dressed_changed("2000-01-01T00:00:00+00:00",
                                                                   {"left": vf.read_sidecar(path)}), [])
    stages = {"n": ["mesh", "rig"]}
    model3d.mesh_hub_stages = lambda *_a, **_kw: list(stages["n"])
    model = {"meta": None}
    model3d.find_model3d = lambda *_a, **_kw: TMP / "model.glb" if model["meta"] is not None else None
    model3d._read_sidecar = lambda _p: dict(model["meta"] or {})
    base_body.side_views_dressed = lambda: False
    follow = lambda: (lambda f: (f["kind"], f["jobs"]))(base_body.mirror_followup("Demo", "left", BSIG, path))  # noqa: E731
    check("follow-up without a model", follow(), ("no_model", 0))
    model["meta"] = meta
    check("follow-up: model built from these bytes", follow(), ("stale", 2))
    vf.toggle_mirror(path)
    after = model_overview.base_model_freshness(meta, shas())
    check("model stale after the mirror", (after["state"], [c["view"] for c in after.get("changed_views") or []]),
          (model_overview.STALE, ["left"]))
    check("view still current after the mirror", view_state(), model_overview.CURRENT)
    changed = model_overview.dressed_changed("2000-01-01T00:00:00+00:00", {"left": vf.read_sidecar(path)})
    check("dressed_changed after the mirror", [c["view"] for c in changed], ["left"])
    check("follow-up: turning back restores the model's view", follow(), ("restores", 0))
    model["meta"] = {"source_image_sha256": "frontsha", "view_images_sha256": {"left": "othersha"}}
    check("follow-up: model already stale", follow(), ("already_stale", 2))
    model["meta"] = {"source_image_sha256": "frontsha", "view_images_sha256": {}}
    check("follow-up: model without the view", follow(), ("unused", 0))
    vf.toggle_mirror(path)
    check("model current after the toggle back", model_overview.base_model_freshness(meta, shas())["state"],
          model_overview.CURRENT)


def section6():
    print("[6] mirror_base_view, the route, the cache GC")
    from fastapi import HTTPException
    from app.core import base_body, figure_build, model3d, outfit_cache_gc
    from app.routes import characters as routes
    base_body.base_signature = lambda *_a, **_kw: BSIG
    figure_build.running = lambda *_a, **_kw: False
    model3d.generation_running = lambda *_a, **_kw: False
    path = stored_view(f"tpose_left_{BSIG}.png", figure()[:, ::-1])
    try:
        base_body.mirror_base_view("Demo", "back")
        check("back refused", "no error", "ValueError")
    except ValueError as e:
        check("back refused", str(e), base_body.MIRROR_SIDES_ONLY)
    base_body.reserve_views("Demo", ("right",))
    try:
        base_body.mirror_base_view("Demo", "left")
        check("busy refused", "no error", "MirrorRefused")
    except base_body.MirrorRefused as e:
        check("busy refused", str(e), base_body.MIRROR_BUSY)
    try:
        routes.mirror_character_base_body_view("Demo", "left", _={})
    except HTTPException as e:
        check("route busy → 409", e.status_code, 409)
    base_body.release_views("Demo", ("right",))
    out = routes.mirror_character_base_body_view("Demo", "left", _={})
    check("route mirrors", (out["mirrored"], out["facing"]["facing"], out["facing"]["state"]),
          (True, "right", "wrong"))
    check("tile: mirrored by hand, restorable", (out["facing"]["mirrored"]["auto"], out["facing"]["restorable"]),
          (False, True))
    files = [p.relative_to(path.parent).as_posix() for p in outfit_cache_gc._ref_files("Demo").get(BSIG, [])]
    check("GC lists the kept original", f"mirrored/{path.name}" in files, True)
    for view, code in (("back", 400), ("right", 404)):
        (path.parent / f"tpose_right_{BSIG}.png").unlink(missing_ok=True)
        try:
            routes.mirror_character_base_body_view("Demo", view, _={})
            check(f"route {view} → {code}", 200, code)
        except HTTPException as e:
            check(f"route {view} → {code}", e.status_code, code)
    out = routes.mirror_character_base_body_view("Demo", "left", _={})
    check("route turns back", (out["mirrored"], out["facing"]["state"]), (False, "ok"))


def section6b():
    print("[6b] the outfit view's Mirror (model_refs.mirror_outfit_view) and its follow-up")
    from fastapi import HTTPException
    from app.core import base_body, model3d, model_refs
    from app.routes import characters as routes
    sig = "0123456789ab"
    model_refs.current_outfit_state = lambda *_a, **_kw: ({}, [], sig)
    base_body.is_base_pipeline = lambda *_a, **_kw: False
    path = stored_view(f"tpose_right_{sig}.png", figure()[:, ::-1])
    out = routes.mirror_character_model_ref_view("Demo", "tpose_right", _={})
    check("outfit right view mirrored", (out["mirrored"], out["info"]["facing"]["facing"],
                                         out["info"]["facing"]["state"]), (True, "right", "ok"))
    check("outfit right view turned back", routes.mirror_character_model_ref_view("Demo", "tpose_right",
                                                                                   _={})["mirrored"], False)
    try:
        routes.mirror_character_model_ref_view("Demo", "tpose_back", _={})
    except HTTPException as e:
        check("route tpose_back → 400", e.status_code, 400)
    base_body.is_base_pipeline = lambda *_a, **_kw: True
    base_body.dressed_view_source = lambda *_a, **_kw: {"source": "plain", "shape": BSIG, "jobs": 0}
    try:
        routes.mirror_character_model_ref_view("Demo", "tpose_right", _={})
    except HTTPException as e:
        check("a copy of the body's view → 400", (e.status_code, e.detail), (400, model_refs.MIRROR_COPY_REFUSED))
    follow = model_refs.outfit_mirror_followup
    check("follow-up: pipeline painted", follow("Demo", sig, pipeline=True, source={"source": "painted"}),
          {"kind": "repaint", "jobs": 0})
    check("follow-up: pipeline copy", follow("Demo", sig, pipeline=True, source={"source": "shape"}),
          {"kind": "copy", "jobs": 0})
    model3d.find_model3d = lambda *_a, **_kw: None
    check("follow-up: off the pipeline, no model", follow("Demo", sig, pipeline=False), {"kind": "no_model", "jobs": 0})
    model3d.find_model3d = lambda *_a, **_kw: path
    model3d.mesh_hub_stages = lambda *_a, **_kw: ["mesh", "upscale", "face", "rig"]
    check("follow-up: off the pipeline, a model", follow("Demo", sig, pipeline=False), {"kind": "model", "jobs": 4})


def section7():
    print("[7] the hooks are wired")
    from app.core import base_body, model_refs
    gen = inspect.getsource(base_body.generate_base_images)
    check("base side view render → auto_correct", "view_facing.auto_correct(v, Path(path))" in gen, True)
    refs = inspect.getsource(model_refs.generate_model_ref_images)
    check("off-pipeline side view → auto_correct", "view_facing.auto_correct(view, Path(view_path))" in refs, True)
    dress = inspect.getsource(base_body._dress_view)
    check("dressed drafts → match_facing (stored + new)", dress.count("view_facing.match_facing("), 2)


def main():
    try:
        section1()
        section2()
        section3()
        section4()
        section5()
        section6()
        section6b()
        section7()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    print(f"\n{len(FAILS)} failure(s)" + (": " + ", ".join(FAILS) if FAILS else ""))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
