#!/usr/bin/env python3
"""Smoke: fix round 2 of Task 11g (plan 2026-11-12-unified-worn-pieces) —
Ruling C2 (a stored MODEL fit is stale: re-made by the composite from its
stored draft, or removed — never served) and Ruling C3 (the composite's
alignment IoU is measured outside the garment), with the composite fixes
they needed (a skin-coloured garment is no skin; a skirt's flare needs no
skin test). Ruling C4 (the Build) is ``smoke_figure_build_plan.py`` [9].

Usage:
    ./.venv/bin/python scripts/smoke_model_fit_remake.py

Runs without a server, a hub or a GPU: a temp world (``paths.init`` first,
STORAGE_DIR / INSTANCE_DIR temp dirs), synthetic RGBA figures, the garment
chain's draft step stubbed. Section [3] reads Ylva's two stored drafts of
the Anima Divide world when that world is on this machine (copies in the
temp dir; skipped otherwise).

Fixture (400 rows x 300 columns, transparent, rows / columns half-open):
    skin SKIN (224, 172, 140) = Lab (74.6, 14.4, 23.6) (``view_composite._lab``),
    shadow SHADOW (135, 92, 63) on the feet = Lab L 43.1 — skin in shade;
    head rows 40..100 cols 125..175, neck 100..110 cols 140..160, torso
    110..230 cols 100..200, arms 115..230 cols 80..100 / 200..220, legs
    230..340 cols 105..140 / 160..195, feet 340..360 (same cols, SHADOW).
    The leg gap: cols 140..160, rows 230..360.
    BROWN (140, 95, 65) = Lab (44.4, 14.8, 24.5): a leather skirt — its
    chroma is 0.68 from the skin's (well inside SKIN_MAHA 3 x sqrt(1.5)
    = 3.67 of the skin model: the base skin's spread is the 1.0 floor), its
    L 44.4 is above the skin model's lower bound (the feet's L 43.1 is the
    2nd percentile, minus 8 = 35.1): BY COLOUR IT IS SKIN, like Ylva's
    leather wrap skirt (2026-11-13) — but 30.2 darker than the skin it covers.
    DRAFT = the base + a BROWN skirt rows 200..320 cols 100..200: it bridges
    the leg gap (rows 230..320) and is 5 px wider than the legs.

Expected, derived by hand:

[1] C3 + the skirt: compose(base, DRAFT) -> ok, ``iou`` 1.0 — outside the
    garment (mask + flare, grown by IOU_MARGIN 12) the draft IS the base:
    no disagreement is left to count. The flare is the skirt between the
    legs (bridged rows 230..320 lie in FLARE_BAND 0.40..0.92 of the height
    320: rows 168..334): ``flare_px`` > 0; the skirt over the legs is
    garment (ΔL 30.2 > SKIN_SAME_DL 15): coverage >= 0.9; in the composite
    at least 95 % of the skirt box is BROWN (within 12 per channel).
    ``alignment_iou`` by hand: two 10 x 10 squares, one moved by 3 px —
    xor 60 px, union 130 -> plain IoU 70/130 = 0.5385; with garment = the
    whole of both, margin 0 -> nothing left -> 1.0; with an empty garment,
    tolerance 0 -> 0.5385, tolerance 2 -> the 3 px wide strips survive an
    opening with a 5 px disk? no (3 < 5) -> 1.0.
[2] C3 keeps refusing a draft that does not line up: the skirt draft with
    both arms raised (rows 20..120 instead of 115..230) -> ok False, reason
    "the draft does not line up" (iou < 0.93): the arms lie outside the
    garment. A turned draft (Ylva's side view as the draft of her back, [3])
    too.
[3] Ylva's drafts (only when the world is here): the drafts of 77d513da244d
    and obb3af5eb3 on base5fe6bd6a's back pass (iou >= 0.93, ok True) — at
    ff011edf both were refused (IoU 0.902 / 0.901, log 2026-11-13 09:43) —
    and her left base view as the draft of her back is refused.
[4] Fails on the old code (ff011edf's view_composite, ``git show``): the
    skirt draft of [1] is refused — no flare (the skirt read as skin) and
    coverage < 0.5.
[5] C2 readers: ``is_model_fit`` — {fit_gate} True, {fit_gate, fit
    "composite"} False, {} False, a non-dict False. ``_view_current`` of a
    record that matches its base: True; the same with ``fit_gate`` and no
    ``fit``: False. ``shape_view_shas`` of a stored shape back: its sha;
    after the sidecar becomes a model fit: "". ``dressed_image`` of a stored
    back: the path; as a model fit: None.
[6] C2 re-make (``model_fit_remake.remake_view``), a character's
    model_refs: base front/back of BSIG, the outfit front tpose_<SIG>, its
    draft drafts/tpose_back_<SIG> (= DRAFT, sidecar front_sha256 = the
    front's sha), the stored back tpose_back_<SIG> = the BASE back (the
    nude model fit) with a model-fit sidecar (fit_gate, back_draft +
    sha, base_signature BSIG, dressed True, outfit_body {"body_id": "x"}):
    (a) "remade": the sidecar has fit "composite", composite ok, outfit_body
    kept, remade_from_model_fit True, no prompt; the image is no longer the
    base back (the skirt box is BROWN); a second call -> "current".
    (b) the draft's front_sha256 names another front -> "removed: its draft
    follows another front"; image and sidecar gone, the draft stays.
    (c) a draft that does not line up (arms raised) -> "removed: the
    composite of its draft failed …"; gone.
    (d) dressed False (a copy without paint) -> removed.
    (e) the texture store's back (model_refs/texture, draft in
    texture/drafts, front texture/tpose_<TSIG>) -> "remade".
[7] ``remake_once``: the first call returns {Demo: …} (one view re-made)
    and sets the world flag; the second returns None.
[8] Garment worn backs: ``stale_model_fit`` True for an accepted drafted
    back without fit "composite", False with it, False for a copy
    (copied_from), False for the front. ``_follows_front`` of the model fit
    False even with the current front_sha256. ``remake_model_fit_back``:
    the draft step stubbed — accepting: "remade", called with stored_only
    True; refusing (StoredDraftUnusable): "removed: …", the back and the
    later back steps gone. ff011edf's ``_follows_front`` (``git show``)
    accepts the model fit: True. The base it composites onto: the current
    base back without a group base copy, else the group's own
    (``garment_source.base_copy``). A materialised copy (``copied_from`` =
    the source fsig "abcdef123456", its own fsig "000000aaaaaa" sorts
    first): stale; ``remake_model_fit_backs`` re-makes the source first and
    copies its back over the copy ("remade" both; the copy holds the
    source's bytes, ``copied_from`` kept, fit "composite", its ghost back
    gone); with the source refused the copy is removed as well.
[9] Stored draft first in ``_dress_view`` (C2: no hub job): the stored
    draft follows the front -> composited, the draft render stub NOT called,
    the view published with fit "composite"; ``reuse_draft`` False (the
    Regenerate button) -> one draft render.
"""
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OLD = "ff011edf"
FAILS: list = []
SKIN = (224, 172, 140)
SHADOW = (135, 92, 63)
BROWN = (140, 95, 65)
BODY = [(40, 100, 125, 175), (100, 110, 140, 160), (110, 230, 100, 200), (115, 230, 80, 100), (115, 230, 200, 220),
        (230, 340, 105, 140), (230, 340, 160, 195), (340, 360, 105, 140, SHADOW), (340, 360, 160, 195, SHADOW)]
SKIRT = (200, 320, 100, 200, BROWN)
ARMS_UP = [p for p in BODY if not (p[0] == 115 and p[2] in (80, 200))] + [(20, 120, 80, 100), (20, 120, 200, 220)]


def _main_tree() -> Path:
    """The main working tree (a linked git worktree has no ``worlds/``): the parent of the common git dir."""
    import subprocess
    out = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                         capture_output=True, text=True).stdout.strip()
    return Path(out).parent if out else ROOT


YLVA = _main_tree() / "worlds" / "Anima Divide" / "characters" / "Ylva Nordwind" / "model_refs"
BSIG, SIG, TSIG = "base1234abcd", "aaaaaaaaaaaa", "tex111111111111"[:15]


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


def figure(parts, rows=400, cols=300):
    a = np.zeros((rows, cols, 4))
    for y0, y1, x0, x1, *colour in parts:
        a[y0:y1, x0:x1, :3] = colour[0] if colour else SKIN
        a[y0:y1, x0:x1, 3] = 255
    return a


def save(arr, path: Path) -> Path:
    from PIL import Image
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.clip(np.round(arr), 0, 255).astype(np.uint8), "RGBA").save(path)
    return path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def brown_share(img: np.ndarray) -> float:
    """Share of the skirt over the figure and between the legs (rows 200..318, cols 105..195: the 5 px it is
    wider than the legs lie outside the base outline, which the composite keeps; the hem row feathers) that
    is BROWN within 12 per channel, alpha >= 250."""
    box = img[200:318, 105:195]
    return float(((np.abs(box[..., :3] - BROWN).max(axis=-1) <= 12) & (box[..., 3] >= 250)).mean())


def old_module(rel: str, name: str):
    source = subprocess.run(["git", "-C", str(ROOT), "show", f"{OLD}:{rel}"], capture_output=True, text=True).stdout
    spec = importlib.util.spec_from_loader(name, loader=None)
    module = importlib.util.module_from_spec(spec)
    exec(compile(source, f"{OLD}:{rel}", "exec"), module.__dict__)
    return module


def composite_sections(tmp: Path):
    from app.core import view_composite as vc
    base, draft = figure(BODY), figure(BODY + [SKIRT])
    print("[1] C3: the skin-coloured skirt lines up outside the garment")
    out, rec = vc.composite_arrays(base, draft)
    check("ok, iou 1.0", (rec["ok"], rec["iou"], rec["reasons"]), (True, 1.0, []))
    check("flare between the legs", rec["flare_px"] > 0, True)
    check("coverage >= 0.9 (the skirt over the legs is garment)", rec["coverage"]["score"] >= 0.9, True)
    check("the skirt box is brown in the composite (>= 95 %)", brown_share(out) >= 0.95, True)
    a = np.zeros((20, 20), bool)
    b = np.zeros((20, 20), bool)
    a[5:15, 5:15] = True
    b[5:15, 8:18] = True
    check("alignment_iou: no garment, tolerance 0", round(vc.alignment_iou(a, b, np.zeros_like(a), margin=0,
                                                                          tolerance=0), 4), round(70 / 130, 4))
    check("alignment_iou: all garment", vc.alignment_iou(a, b, a | b, margin=0), 1.0)
    check("alignment_iou: 3 px strips under the 2 px tolerance", vc.alignment_iou(a, b, np.zeros_like(a), margin=0),
          1.0)

    print("[2] C3 still refuses a draft that does not line up")
    _out, rec = vc.composite_arrays(base, figure(ARMS_UP + [SKIRT]))
    check("arms raised: refused, not aligned", (rec["ok"], rec["iou"] < vc.IOU_MIN,
                                                [r.split(" (")[0] for r in rec["reasons"]]),
          (False, True, [vc.NOT_ALIGNED]))

    print("[3] Ylva's stored drafts")
    back = YLVA / "tpose_back_base5fe6bd6a.png"
    if not back.is_file():
        print("  SKIP the Anima Divide world is not on this machine")
    else:
        copy = tmp / "ylva"
        copy.mkdir()
        shutil.copy(back, copy / "base.png")
        for sig in ("77d513da244d", "obb3af5eb3"):
            shutil.copy(YLVA / "drafts" / f"tpose_back_{sig}.png", copy / f"{sig}.png")
            rec = vc.compose(copy / "base.png", copy / f"{sig}.png", copy / f"out_{sig}.png")
            print(f"       {sig}: iou {rec['iou']} (full {rec.get('iou_full')}), coverage "
                  f"{rec['coverage'].get('score')}, flare {rec['flare_px']}")
            check(f"{sig}: passes", (rec["ok"], rec["iou"] >= vc.IOU_MIN), (True, True))
        shutil.copy(YLVA / "tpose_left_base5fe6bd6a.png", copy / "left.png")
        rec = vc.compose(copy / "base.png", copy / "left.png", copy / "out_left.png")
        check("her side view as the draft of her back: refused, not aligned",
              (rec["ok"], any(r.startswith(vc.NOT_ALIGNED) for r in rec["reasons"])), (False, True))

    print(f"[4] fails on {OLD}")
    old = old_module("app/core/view_composite.py", "view_composite_old")
    _out, rec = old.composite_arrays(base, draft)
    check(f"{OLD}: the skirt refused, no flare, coverage < 0.5",
          (rec["ok"], rec["flare_px"], rec["coverage"]["score"] < 0.5), (False, 0, True))


def put_view(refs: Path, stem: str, img, meta) -> Path:
    path = save(img, refs / f"{stem}.png")
    path.with_suffix(".json").write_text(json.dumps(meta), encoding="utf-8")
    return path


def stage_character(refs: Path, *, draft_img=None, draft_front_sha=None, extra=None, where: str = "") -> Path:
    """The model_refs of [6] (``where`` "texture": the texture store); returns the stored back."""
    base = figure(BODY)
    put_view(refs, f"tpose_{BSIG}", base, {"base_signature": BSIG})
    base_back = put_view(refs, f"tpose_back_{BSIG}", base, {"base_signature": BSIG})
    folder = refs / where if where else refs
    sig = TSIG if where else SIG
    front = put_view(folder, f"tpose_{sig}", figure(BODY + [SKIRT]), {"base_signature": BSIG, "dressed": True})
    draft = put_view(folder / "drafts", f"tpose_back_{sig}", figure(BODY + [SKIRT]) if draft_img is None else draft_img,
                     {"front_sha256": draft_front_sha or sha(front), "base_signature": BSIG, "dressed": True})
    meta = {"prompt": "edit the first image", "base_signature": BSIG, "dressed": True,
            "base_image_sha256": sha(base_back), "back_draft": draft.name, "back_draft_sha256": sha(draft),
            "fit_gate": {"ok": True, "chosen": 1, "attempts": []}, "outfit_body": {"body_id": "x"},
            **({"texture_signature": TSIG} if where else {}), **(extra or {})}
    return put_view(folder, f"tpose_back_{sig}", base, meta)


def store_sections(tmp: Path):
    from app.core import base_body, model_fit_remake
    from app.core.model_refs import get_model_refs_dir
    from app.models.character import get_character_dir
    print("[5] C2 readers refuse a model fit")
    check("is_model_fit", [base_body.is_model_fit(r) for r in ({"fit_gate": {}}, {"fit_gate": {}, "fit": "composite"},
                                                               {}, None)], [True, False, False, False])
    get_character_dir("Demo", create=True)
    refs = get_model_refs_dir("Demo")
    back = stage_character(refs)
    base_back = refs / f"tpose_back_{BSIG}.png"
    current = {"base_signature": BSIG, "base_image_sha256": sha(base_back)}
    check("_view_current: composite / model fit",
          (base_body._view_current({**current, "fit": "composite", "fit_gate": {}}, BSIG, base_back),
           base_body._view_current({**current, "fit_gate": {}}, BSIG, base_back)), (True, False))
    shape_back = put_view(refs, "tpose_back_ob12345678", figure(BODY), {**current, "fit": "composite",
                                                                       "fit_gate": {}})
    put_view(refs, "tpose_ob12345678", figure(BODY), {**current, "base_image_sha256": sha(refs / f"tpose_{BSIG}.png")})
    check("shape_view_shas: composite", base_body.shape_view_shas("Demo", "ob12345678", BSIG)["back"], sha(shape_back))
    shape_back.with_suffix(".json").write_text(json.dumps({**current, "fit_gate": {}}), encoding="utf-8")
    check("shape_view_shas: model fit", base_body.shape_view_shas("Demo", "ob12345678", BSIG)["back"], "")
    fig = SimpleNamespace(bsig=BSIG, shape=BSIG, own=(), left_out={})
    meta = json.loads(back.with_suffix(".json").read_text())
    back.with_suffix(".json").write_text(json.dumps({**meta, "fit": "composite"}), encoding="utf-8")
    real_views = base_body.dressed_views
    base_body.dressed_views = lambda: ("front", "back")
    try:
        check("dressed_image: composite", base_body.dressed_image("Demo", "back", SIG, BSIG, fig=fig), back)
        back.with_suffix(".json").write_text(json.dumps(meta), encoding="utf-8")
        check("dressed_image: model fit", base_body.dressed_image("Demo", "back", SIG, BSIG, fig=fig), None)
    finally:
        base_body.dressed_views = real_views

    print("[6] C2 re-make from the stored draft")
    outcome = model_fit_remake.remake_view("Demo", back)
    new = json.loads(back.with_suffix(".json").read_text())
    from PIL import Image
    img = np.asarray(Image.open(back).convert("RGBA"), dtype=np.float64)
    check("(a) remade", outcome, "remade")
    check("(a) sidecar", (new.get("fit"), (new.get("composite") or {}).get("ok"), new.get("outfit_body"),
                          new.get("remade_from_model_fit"), "prompt" in new),
          ("composite", True, {"body_id": "x"}, True, False))
    check("(a) the skirt put on (>= 95 % brown)", brown_share(img) >= 0.95, True)
    check("(a) again: current", model_fit_remake.remake_view("Demo", back), "current")
    shutil.rmtree(refs)
    refs.mkdir()
    back = stage_character(refs, draft_front_sha="0" * 64)
    outcome = model_fit_remake.remake_view("Demo", back)
    check("(b) draft of another front: removed", (outcome, back.exists(), back.with_suffix(".json").exists(),
                                                  (refs / "drafts" / back.name).exists()),
          ("removed: its draft follows another front", False, False, True))
    shutil.rmtree(refs)
    refs.mkdir()
    back = stage_character(refs, draft_img=figure(ARMS_UP + [SKIRT]))
    outcome = model_fit_remake.remake_view("Demo", back)
    check("(c) a draft that does not line up: removed", (outcome.startswith("removed: the composite of its draft "
                                                                            "failed"), back.exists()), (True, False))
    shutil.rmtree(refs)
    refs.mkdir()
    back = stage_character(refs, extra={"dressed": False})
    check("(d) a copy without paint: removed", (model_fit_remake.remake_view("Demo", back).startswith("removed"),
                                                back.exists()), (True, False))
    shutil.rmtree(refs)
    refs.mkdir()
    back = stage_character(refs, where="texture")
    check("(e) the texture store's back: remade", model_fit_remake.remake_view("Demo", back), "remade")

    print("[7] remake_once")
    from app.models import character
    from app.models.world import get_world_setting
    shutil.rmtree(refs)
    refs.mkdir()
    stage_character(refs)
    character.list_available_characters = lambda **_kw: ["Demo"]
    first = model_fit_remake.remake_once()
    check("first: Demo, one view re-made", sorted((first or {}).get("Demo", {}).get("views", {}).values()), ["remade"])
    check("flag set", bool(get_world_setting(model_fit_remake.FLAG)), True)
    check("second: None", model_fit_remake.remake_once(), None)


def garment_section():
    from app.core import garment_images as gi
    from app.core import garment_store as gs
    print("[8] the garment chain's worn back")
    item, fsig = "item_demo_coat", "abcdef123456"
    gi._kind_module = lambda item_id: SimpleNamespace(EDIT_STEPS={"worn": {"back": "draft", "source": "base"},
                                                                  "ghost": {"source": "worn"}})
    gi._item_kind = lambda item_id: "clothing"
    final = gs.garment_path("Demo", item, fsig, "image", step="worn", view="back")
    front = gs.garment_path("Demo", item, fsig, "image", step="worn", view="front")
    later = gs.garment_path("Demo", item, fsig, "image", step="ghost", view="back")
    for path in (final, front, later):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(path.name.encode())
        gs.write_record(path.with_suffix(".json"), {"accepted": True})
    gs.write_record(final.with_suffix(".json"), {"accepted": True, "front_sha256": sha(front), "draft": "d.png"})
    check("stale_model_fit: model fit / front", (gi.stale_model_fit("Demo", item, fsig, "worn", "back"),
                                                 gi.stale_model_fit("Demo", item, fsig, "worn", "front")), (True, False))
    check("_follows_front of the model fit: False", gi._follows_front("Demo", item, fsig, "worn", final), False)
    old = old_module("app/core/garment_images.py", "garment_images_old")
    old._kind_module = gi._kind_module
    check(f"{OLD}: _follows_front accepts the model fit", old._follows_front("Demo", item, fsig, "worn", final), True)
    gs.write_record(final.with_suffix(".json"), {"accepted": True, "front_sha256": sha(front), "fit": "composite"})
    check("composite: not stale, follows", (gi.stale_model_fit("Demo", item, fsig, "worn", "back"),
                                            gi._follows_front("Demo", item, fsig, "worn", final)), (False, True))
    gs.write_record(final.with_suffix(".json"), {"accepted": True, "copied_from": {"fsig": fsig, "sha256": "x"}})
    check("a copy: not stale", gi.stale_model_fit("Demo", item, fsig, "worn", "back"), False)

    from app.core import base_body
    from app.core.model_refs import get_model_refs_dir
    base_body.base_signature = lambda c, profile=None: BSIG
    save(figure(BODY), get_model_refs_dir("Demo") / f"tpose_back_{BSIG}.png")
    calls = []

    bases = []

    def accepting(*args, **kw):
        calls.append(kw.get("stored_only"))
        bases.append(Path(kw["base"]).name)
        gs.write_record(final.with_suffix(".json"), {"accepted": True, "fit": "composite"})
        return final
    gs.write_record(final.with_suffix(".json"), {"accepted": True, "front_sha256": sha(front)})
    gi._drafted_back = accepting
    check("remake: remade, stored_only", (gi.remake_model_fit_back("Demo", item, fsig, "worn"), calls),
          ("remade", [True]))
    from app.core import garment_source
    group_base = garment_source.base_copy("Demo", item, fsig, "back")
    save(figure(BODY), group_base)
    gs.write_record(final.with_suffix(".json"), {"accepted": True, "front_sha256": sha(front)})
    gi.remake_model_fit_back("Demo", item, fsig, "worn")
    check("remake: onto the current base back without a group base copy, else onto the group's own",
          bases, [f"tpose_back_{BSIG}.png", group_base.name])

    # A materialised copy (``copied_from`` the source fsig as a string) has no draft of its own: it follows its
    # source group's re-made back. Its fsig sorts BEFORE the source's — the rendered backs go first anyway.
    copy_fsig = "000000aaaaaa"
    copy_final = gs.garment_path("Demo", item, copy_fsig, "image", step="worn", view="back")
    copy_later = gs.garment_path("Demo", item, copy_fsig, "image", step="ghost", view="back")
    for path in (copy_final, copy_later):
        path.write_bytes(b"nude copy")
        gs.write_record(path.with_suffix(".json"), {"accepted": True, "copied_from": fsig})
    later.write_bytes(b"ghost of the nude back")
    gs.write_record(later.with_suffix(".json"), {"accepted": True})
    gs.write_record(final.with_suffix(".json"), {"accepted": True, "front_sha256": sha(front)})
    check("a materialised copy of a model fit: stale", gi.stale_model_fit("Demo", item, copy_fsig, "worn", "back"),
          True)

    def remaking(*args, **kw):
        final.write_bytes(b"composite back")
        gs.write_record(final.with_suffix(".json"), {"accepted": True, "fit": "composite",
                                                      "front_sha256": sha(front)})
        later.unlink(missing_ok=True)
        return final
    gi._drafted_back = remaking
    out = gi.remake_model_fit_backs("Demo")
    check("remake_model_fit_backs: source and copy re-made",
          (out.get(final.name), out.get(copy_final.name)), ("remade", "remade"))
    check("the copy holds the source's re-made back, copied_from kept, its later back gone",
          (copy_final.read_bytes(), gs.read_record(copy_final.with_suffix(".json")).get("copied_from"),
           gs.read_record(copy_final.with_suffix(".json")).get("fit"), copy_later.exists()),
          (b"composite back", fsig, "composite", False))
    for path in (copy_final, copy_later):
        path.write_bytes(b"nude copy")
        gs.write_record(path.with_suffix(".json"), {"accepted": True, "copied_from": fsig})
    gs.write_record(final.with_suffix(".json"), {"accepted": True, "front_sha256": sha(front)})
    gi._drafted_back = lambda *a, **kw: (_ for _ in ()).throw(gi.StoredDraftUnusable("refused"))
    out = gi.remake_model_fit_backs("Demo")
    check("source refused: the copy is removed too",
          (out.get(copy_final.name), copy_final.exists(), copy_later.exists(), final.exists()),
          (f"removed: its source back ({fsig}) was not re-made", False, False, False))
    for path in (final, later):
        path.write_bytes(path.name.encode())
        gs.write_record(path.with_suffix(".json"), {"accepted": True})

    def refusing(*args, **kw):
        raise gi.StoredDraftUnusable("no stored draft made from the current front")
    gs.write_record(final.with_suffix(".json"), {"accepted": True, "front_sha256": sha(front)})
    gi._drafted_back = refusing
    check("remake refused: removed, the back and the later back gone",
          (gi.remake_model_fit_back("Demo", item, fsig, "worn"), final.exists(), later.exists(), front.exists()),
          ("removed: no stored draft made from the current front", False, False, True))


def dress_view_section(tmp: Path):
    from app.core import base_body
    from app.core.model_refs import get_model_refs_dir
    print("[9] _dress_view composites the stored draft first")
    refs = get_model_refs_dir("Demo")
    shutil.rmtree(refs)
    refs.mkdir()
    stage_character(refs)
    front = refs / f"tpose_{SIG}.png"
    (refs / f"tpose_back_{SIG}.png").unlink()
    renders = []

    def render_draft(character_name, view, *, stem, **kw):
        renders.append(view)
        return save(figure(BODY + [SKIRT]), Path(f"{stem}.png"))
    base_body.render_draft = render_draft
    views = {v: refs / f"tpose_{'' if v == 'front' else v + '_'}{BSIG}.png" for v in ("front", "back")}
    views.update(left=None, right=None)
    kw = dict(signature=SIG, bsig=BSIG, pieces={}, items=[], profile={}, front=front, base_views=views,
              refs_dir=refs, size=(300, 400))
    path, _warning = base_body._dress_view("Demo", "back", **kw)
    check("stored draft: no render, published as a composite",
          (renders, json.loads(path.with_suffix(".json").read_text()).get("fit")), ([], "composite"))
    base_body._dress_view("Demo", "back", reuse_draft=False, **kw)
    check("Regenerate (reuse_draft False): one draft render", renders, ["back"])


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="model-fit-remake-") as tmp:
        root = Path(tmp)
        os.environ["STORAGE_DIR"] = str(root / "world")
        os.environ["INSTANCE_DIR"] = str(root / "instance")
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "instance")
        from app.core import config, db
        config.load(paths.get_config_path(), instance_path=root / "instance" / "config.json")
        db.init_schema()
        composite_sections(root)
        store_sections(root)
        garment_section()
        dress_view_section(root)
    if FAILS:
        print(f"\nFAILED: {', '.join(FAILS)}")
        return 1
    print("\nALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
