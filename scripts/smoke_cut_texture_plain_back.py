#!/usr/bin/env python3
"""Smoke: a PLAIN back gets no back job — the back panel is the front panel's fabric (live E2E 2026-11-21: P-H3
invented a collar and a button placket on Dario's plain back, fold shading and a colour fringe on Tilda's).

Usage:
    ./.venv/bin/python scripts/smoke_cut_texture_plain_back.py

Throwaway STORAGE_DIR / INSTANCE_DIR, no world, no hub, no Blender, no BiRefNet (the pictures carry their cut-out
alpha), no server, no network. The code under test is the real ``garment_cut_texture`` (``is_plain_back``,
``detail_of_view``, ``job_plan``, ``_estimate_jobs``, ``build_state``, ``panel_fabric``, ``fill_fabric``,
``fill_plain_back``, ``compose``, ``generate``, ``recompose``), ``figure_build._cut_texture_step`` / ``cost`` and
``garment_template_cut.ensure``. Every number is derived by hand below.

Pictures (RGBA, transparent background): PLAIN = an 800 x 800 picture with one (40, 40, 150) block (100..700)^2;
PRINTED = the same block with light (220, 220, 220) stripes 24 px high every 48 px over its middle 400 x 400.

[1] The decision (``PLAIN_BACK_DETAIL`` 0.20, at or below = plain):
    - ``is_plain_back``: the measured backs Kai 0.0175, Tilda 0.0536, Dario 0.158 -> plain; exactly 0.20 -> plain;
      0.2001 and the knit cardigan 0.246 -> not; None / "x" (nothing measured) -> not.
    - ``detail_of_view(PLAIN)``: one flat colour, no L* gradient anywhere -> 0.0 -> plain. ``detail_of_view(PRINTED)``:
      every stripe edge is a 0 -> ~88 L* step; at the 128 px scale the 400 px print is ~85 px with a stripe edge every
      ~3.4 px, the Gaussian (sigma 1) spreads each over ~3 px > 4 L*/px -> most of the print's 85 px rows, the print
      ~45 % of the eroded garment -> about 0.4-0.5, far above 0.20 -> decorated.
    - the measure is cached by the file's stat: a second call measures nothing (``picture_reference`` count stays 1);
      a rewritten file (another size) is measured again (2).
[2] The counts (islands front + back, no csig yet so nothing is re-used; ``_plan_one`` / ``job_plan``):
    - back view PLAIN, item 1200 px (>= 1024, no upscale): back_view 0, upscale 0, front 1, back 0 -> total 1,
      ``back_plain`` True; ``redo`` has "front" only (no Redo back for a plain back).
    - back view PRINTED: front 1 + back 1 = 2, ``back_plain`` False, ``redo`` front and back.
    - no back view: back_view 1 + front 1 + back 1 (counted until it is measured) = 3.
    - back view PLAIN, item 600 px: upscale 1 + front 1 = 2 — the live expectation for Dario / Tilda.
    - ``_estimate_jobs`` (the pattern not cut yet): PLAIN + 600 px -> 0 + 1 + 1 + 0 = 2; PRINTED + 600 px -> 3; no
      back view + 600 px -> 1 + 1 + 1 + 1 = 4.
    - ``build_state`` due with the PLAIN back and 600 px: jobs 2 (= plan total); ``figure_build._cut_texture_step``:
      label "Texture from cut · Cream Blouse (+2 image jobs, up to 3 when an attempt is rejected)" (``max`` = total 2 +
      the front job's second attempt 1 x (CUT_ATTEMPTS 2 - 1) = 3, key isolation 2026-11-25), jobs 2; ``figure_build.cost`` of that step: hub_jobs 2,
      note "2 hub jobs (estimate, retries extra) — +2 image jobs for the cut texture".
[3] ``fill_plain_back`` on a 400 px atlas, px_per_cm 10 (bleed 1 cm = 10 px): islands front (20..200)^2, sleeve_l
    x 20..100 / y 220..300 (front job), back x 220..380 / y 20..200 (back job). The front answer: the front panel
    a 1-px checker of A (120, 60, 30) and B (130, 70, 40) — a fine weave — the rest white.
    - ``panel_fabric`` of it: the patch is a window of the checker (only A and B in it).
    - the back island: every pixel's colour is one the SAME fabric gives the sleeve through ``fill_fabric`` (the same
      patch and the same shift: the colour sets are equal); ``state`` "ready", ``source`` "fabric".
    - the bleed: x 220..379 grown by 10 -> column 389 is fabric, column 390 white (outside); y 210 (200 + 10 - 1 =
      209 is the last grown row) -> row 209 fabric, row 210 white at x 300.
    - one colour at the side seam: the mean of the front panel's column 199 and of the back's column 220 (both the
      checker re-centred on the panel's base colour) differ by < 2 per channel.
    - ``compose`` keeps the front panel's own pixels (A / B unchanged) and puts the back fabric on the back island.
    - a front without a fabric patch (``_fabric`` {"skipped": "no main panel"}) -> "rejected", reason
      ``PLAIN_BACK_REASON`` "No fabric patch for the plain back: no main panel".
[4] ``generate`` end-to-end on the same islands (the routed render stubbed: it answers the template with every
    non-white pixel set to A — a counted "image job"; ``apply_after`` False):
    - PLAIN back view: 1 render ("front"); record "ready"; ``jobs.back`` = {"state": "ready", "source": "fabric"};
      ``back_plain.plain`` True; the atlas exists; no ``.raw_back.png`` / ``.template_back.png``; the atlas' back
      island centre equals the front panel's colour (+-2, the Lab round trip).
    - ``only="back"`` again: 0 renders (the front answer re-used, the back is the fabric), still "ready".
    - ``recompose``: 0 renders, "ready", the back again "fabric".
    - PRINTED back view (another back sha -> another csig): 2 renders ("front", "back"); the BACK job's detail gate
      limit = ``detail_limit(detail of the PRINTED view)`` = 3 x d + 0.04 — its OWN Picture 2, not the item's (the
      item picture is flat: its limit would be 0.04).
[5] ``garment_template_cut.ensure`` (cut_key / state / the runner stubbed): the cut's record "failed" ->
    ``ensure`` returns it without running (an automatic Build, 0 runs); ``retry_failed=True`` runs it ONCE (1 run)
    and returns the state after it ("ready"); a second ``ensure`` with ``retry_failed`` on a cut that failed again
    runs once more (2) — one run per call, never a loop.
"""
import io
import json
import os
import socket
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS = []
CONNECTS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


def _no_connect(*a, **k):
    CONNECTS.append(a)
    raise OSError("network disabled in this smoke")


socket.create_connection = _no_connect

CHAR, ITEM = "Tilda", "shirt"
A, B = (120, 60, 30), (130, 70, 40)


def picture(path: Path, printed: bool) -> Path:
    im = Image.new("RGBA", (800, 800), (0, 0, 0, 0))
    im.paste((40, 40, 150, 255), (100, 100, 700, 700))
    if printed:
        for y in range(200, 600, 48):
            im.paste((220, 220, 220, 255), (200, y, 600, y + 24))
    im.save(path)
    return path


def isl(name, x0, y0, x1, y1):
    return {"name": name, "verts_px": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]], "tris": [[0, 1, 2], [0, 2, 3]],
            "bbox_px": [x0, y0, x1, y1]}


PAYLOAD = {"atlas_px": 400, "px_per_cm": 10.0, "seams": [],
           "islands": [isl("front", 20, 20, 200, 200), isl("sleeve_l", 20, 220, 100, 300),
                       isl("back", 220, 20, 380, 200)]}


def section_decision(tmp: Path):
    from app.core import cut_texture_post as post
    from app.core import garment_cut_texture as gct
    print("[1] the decision")
    check("[1] threshold", gct.PLAIN_BACK_DETAIL, 0.20)
    check("[1] measured plain backs + the edge",
          [gct.is_plain_back(v) for v in (0.0175, 0.0536, 0.158, 0.20)], [True, True, True, True])
    check("[1] above / unknown", [gct.is_plain_back(v) for v in (0.2001, 0.246, None, "x")], [False] * 4)
    plain = picture(tmp / "plain.png", False)
    printed = picture(tmp / "printed.png", True)
    check("[1] PLAIN view: detail 0.0 -> plain", (gct.detail_of_view(plain), gct.is_plain_back(
        gct.detail_of_view(plain))), (0.0, True))
    d = gct.detail_of_view(printed)
    check("[1] PRINTED view: 0.4 .. 0.5 -> decorated", (0.4 <= d <= 0.5, gct.is_plain_back(d)), (True, False))
    calls = []
    real = post.picture_reference

    def counted(*a, **k):
        calls.append(1)
        return real(*a, **k)
    post.picture_reference = counted
    try:
        again = tmp / "again.png"
        picture(again, False)
        gct.detail_of_view(again)
        gct.detail_of_view(again)
        check("[1] cached by the file's stat: measured once", len(calls), 1)
        Image.new("RGBA", (400, 400), (0, 0, 0, 0)).save(again)
        gct.detail_of_view(again)
        check("[1] a rewritten file is measured again", len(calls), 2)
    finally:
        post.picture_reference = real
    return plain, printed


class Stubs:
    back = None
    side = 1200


def install_counts(plain: Path, printed: Path):
    from app.core import garment_cut_texture as gct
    gct.back_view = lambda c, i: Stubs.back
    gct._item_side = lambda iid: Stubs.side


def section_counts(plain: Path, printed: Path):
    from app.core import figure_build as fb
    from app.core import garment_cut_texture as gct
    from app.core import garment_template as gt
    from app.core import garment_template_cut as gtc
    from app.models import inventory
    print("[2] the counts")
    install_counts(plain, printed)
    isl2 = {"islands": [{"name": "front"}, {"name": "back"}]}

    def plan():
        p = gct.job_plan(CHAR, ITEM, isl2, "")
        return (p["back_view"], p["upscale"], p["front"], p["back"], p["total"], p["back_plain"], sorted(p["redo"]))
    Stubs.back, Stubs.side = plain, 1200
    check("[2] plain back, 1200 px -> 1 job, no Redo back", plan(), (0, 0, 1, 0, 1, True, ["front"]))
    Stubs.back = printed
    check("[2] printed back -> 2 jobs", plan(), (0, 0, 1, 1, 2, False, ["back", "front"]))
    Stubs.back = None
    check("[2] no back view -> 3 (back counted)", plan(), (1, 0, 1, 1, 3, False, ["back", "front"]))
    Stubs.back, Stubs.side = plain, 600
    check("[2] plain back, 600 px -> upscale + front = 2", plan(), (0, 1, 1, 0, 2, True, ["front"]))
    est = []
    for back in (plain, printed, None):
        Stubs.back = back
        est.append(gct._estimate_jobs(CHAR, ITEM))
    check("[2] _estimate_jobs plain / printed / none (600 px)", est, [2, 3, 4])

    # build_state -> the Build's step and its cost
    Stubs.back, Stubs.side = plain, 600
    gt.params_of = lambda item: {"kind": "top", "texture": "cut", "sleeve_print": "plain"}
    inventory.get_item = lambda iid: {"id": iid, "name": "Cream Blouse"}
    gtc.cut_key = lambda c, i, profile=None, item=None: {"sig": "cutsig000001", "reason": ""}
    gtc.state = lambda c, i, key=None: {"state": "ready", "reason": "", "islands_sha": "isl",
                                        "islands_path": Path("x.json")}
    real_islands_of, real_item_sha, real_csig_for = gct._islands_of, gct.item_sha, gct.csig_for
    gct._islands_of = lambda pattern: isl2
    gct.item_sha = lambda iid: "itemsha"
    gct.csig_for = lambda c, i, sha, islands=None, has_back_panel=None, **kw: None
    try:
        st = gct.build_state(CHAR, ITEM)
        check("[2] build_state due 2", (st["state"], st["jobs"], st["estimate"]), ("due", 2, False))
        step = fb._cut_texture_step(CHAR, ITEM)
        check("[2] the Build's step", (step.label, step.jobs), ("Texture from cut · Cream Blouse (+2 image jobs, up to 3 when an attempt is rejected)", 2))
        cost = fb.cost(CHAR, [step])
        check("[2] the cost note", (cost["hub_jobs"], cost["note"]),
              (2, "2 hub jobs (estimate, retries extra) — +2 image jobs for the cut texture"))
    finally:
        gct._islands_of, gct.item_sha, gct.csig_for = real_islands_of, real_item_sha, real_csig_for


def front_answer(size=400):
    """The front job's post-processed image: the front panel a 1-px A/B checker, the rest white."""
    from app.core import garment_cut_texture as gct
    img = np.full((size, size, 3), 255, np.uint8)
    labels = gct.job_labels(PAYLOAD, size, "front")
    front = gct._part_mask(PAYLOAD, labels, ("front",))
    yy, xx = np.mgrid[0:size, 0:size]
    checker = ((yy + xx) % 2 == 0)
    img[front & checker] = A
    img[front & ~checker] = B
    return img, labels, front


def colours(img, mask):
    return {tuple(int(v) for v in c) for c in np.unique(img[mask].reshape(-1, 3), axis=0)}


def section_fill():
    from app.core import cut_texture_post as post
    from app.core import garment_cut_texture as gct
    print("[3] fill_plain_back")
    size, ppc = 400, 10.0
    img, labels, front = front_answer(size)
    fabric = gct.panel_fabric(img, PAYLOAD, labels, "front", ppc)
    check("[3] the patch is the checker", colours(fabric["patch"], np.ones(fabric["patch"].shape[:2], bool)), {A, B})
    fmask = labels > 0
    fgrown = post.dilate(fmask, 10) | fmask
    sleeved, fill = gct.fill_fabric(img, labels, fgrown, PAYLOAD, "front", ppc, fabric=fabric)
    front_res = {"state": "ready", "_image": sleeved, "_grown": fgrown, "_mask": fmask, "_fabric": fabric}
    res = gct.fill_plain_back(front_res, PAYLOAD, size, ppc, 0.05)
    entry = gct.plain_back_entry(res)
    check("[3] ready, source fabric", (res["state"], entry["state"], entry["source"]), ("ready", "ready", "fabric"))
    blabels = gct.job_labels(PAYLOAD, size, "back")
    back = blabels > 0
    sleeve = gct._part_mask(PAYLOAD, labels, ("sleeve_l",))
    check("[3] back colours = sleeve colours (one fabric)", colours(res["_image"], back), colours(sleeved, sleeve))
    out = res["_image"]
    check("[3] bleed: col 389 fabric, col 390 white", (tuple(out[100, 389]) != (255, 255, 255),
                                                        tuple(int(v) for v in out[100, 390])), (True, (255, 255, 255)))
    check("[3] bleed: row 209 fabric, row 210 white", (tuple(out[209, 300]) != (255, 255, 255),
                                                        tuple(int(v) for v in out[210, 300])), (True, (255, 255, 255)))
    atlas = gct.compose({"front": front_res, "back": res}, size)
    seam = np.abs(atlas[20:200, 199].astype(float).mean(0) - atlas[20:200, 220].astype(float).mean(0))
    check("[3] side seam: one colour (< 2 per channel)", bool((seam < 2).all()), True)
    check("[3] compose keeps the front panel", colours(atlas, front), {A, B})
    check("[3] compose puts the fabric on the back", colours(atlas, back), colours(res["_image"], back))
    bad = gct.fill_plain_back({**front_res, "_fabric": {"skipped": "no main panel"}}, PAYLOAD, size, ppc, 0.05)
    check("[3] no patch -> rejected", (bad["state"], bad["reason"]),
          ("rejected", "No fabric patch for the plain back: no main panel"))


def section_generate(tmp: Path, plain: Path, printed: Path):
    from app.core import cut_texture_post as post
    from app.core import figure
    from app.core import garment_cut_texture as gct
    print("[4] generate / recompose")
    islands_path = tmp / "islands.json"
    islands_path.write_text(json.dumps(PAYLOAD))
    item_png = tmp / "item.png"
    im = Image.new("RGBA", (1200, 1200), (0, 0, 0, 0))
    im.paste((*A, 255), (200, 200, 1000, 1000))
    im.save(item_png)
    cut = tmp / "cut"
    gct.cut_dir = lambda c: cut
    gct._ready_pattern = lambda c, i: {"islands_sha": "isl000", "islands_path": islands_path, "cut_sig": "cutsig"}
    gct._item_path = lambda iid: item_png
    gct._item_matte = lambda: None
    gct.piece_name = lambda iid: "T-shirt"
    gct.sleeve_print_of = lambda iid: "plain"
    gct.csig_for = lambda c, i, sha, islands=None, has_back_panel=None: gct.csig(sha, gct._item_sha(i),
                                                                                 gct.back_sha(c, i))
    gct.current_csig = lambda c, i: gct.csig("isl000", gct._item_sha(i), gct.back_sha(c, i))
    figure.invalidate = lambda *a, **k: None
    renders = []

    class Backend:
        name = "FakeCut"
        extra_params = {}

    def routed(item_id, side, prompt_for, template_png, ref_png, seed):
        renders.append(side)
        with Image.open(template_png) as t:
            arr = np.asarray(t.convert("RGB")).copy()
        arr[(255 - arr.astype(int)).max(-1) > 24] = A
        buf = io.BytesIO()
        Image.fromarray(arr).save(buf, format="PNG")
        return buf.getvalue(), Backend(), None, "ordinal", prompt_for("ordinal")
    gct._routed_render = routed

    Stubs.back, Stubs.side = plain, 1200
    rec = gct.generate(CHAR, ITEM, apply_after=False)
    sig = rec.get("csig")
    stem = gct._stem(CHAR, ITEM, sig)
    back = rec.get("jobs", {}).get("back", {})
    check("[4] plain: 1 render (front), ready", (renders, rec.get("state"), rec.get("reason")), (["front"], "ready", ""))
    check("[4] plain: the back is the fabric", (back.get("state"), back.get("source"),
                                                (rec.get("back_plain") or {}).get("plain")), ("ready", "fabric", True))
    check("[4] plain: atlas, no back answer / template", (gct._file(stem, ".atlas.png").is_file(),
                                                         gct._file(stem, ".raw_back.png").is_file(),
                                                         gct._file(stem, ".template_back.png").is_file()),
          (True, False, False))
    with Image.open(gct._file(stem, ".atlas.png")) as a:
        atlas = np.asarray(a.convert("RGB")).astype(int)
    check("[4] plain: the back centre is the front panel's colour (+-2)",
          bool(np.abs(atlas[110, 300] - atlas[110, 110]).max() <= 2), True)
    renders.clear()
    rec = gct.generate(CHAR, ITEM, only="back", apply_after=False)
    check("[4] only=back: 0 renders, ready", (renders, rec.get("state")), ([], "ready"))
    rec = gct.recompose(CHAR, ITEM, apply_after=False)
    check("[4] recompose: 0 renders, ready, fabric back", (renders, rec.get("state"), rec["jobs"]["back"].get("source")),
          ([], "ready", "fabric"))

    Stubs.back = printed
    rec = gct.generate(CHAR, ITEM, apply_after=False)
    det = (rec.get("jobs", {}).get("back", {}).get("metrics") or {}).get("detail") or {}
    d_back = gct.detail_of_view(printed)
    check("[4] printed: 2 renders (front, back)", renders, ["front", "back"])
    check("[4] printed: the back gate's limit is the back view's own", (det.get("reference"), det.get("limit")),
          (d_back, post.detail_limit(d_back)))
    check("[4] ... not the item's (0.04)", det.get("limit") != post.detail_limit(0.0), True)


def section_ensure():
    from app.core import garment_template_cut as gtc
    print("[5] garment_template_cut.ensure")
    seq = {"state": "failed"}
    runs = []
    gtc.cut_key = lambda c, i, profile=None, item=None: {"sig": "cutsig000001", "reason": ""}
    gtc.state = lambda c, i, key=None: {"state": seq["state"], "reason": seq["state"]}

    def runner(c, i):
        runs.append(1)
        seq["state"] = next_state["v"]
    next_state = {"v": "ready"}
    check("[5] failed, automatic: returned as it is, 0 runs", (gtc.ensure(CHAR, ITEM, runner=runner)["state"],
                                                                len(runs)), ("failed", 0))
    check("[5] failed, retry_failed: 1 run, ready", (gtc.ensure(CHAR, ITEM, runner=runner, retry_failed=True)["state"],
                                                     len(runs)), ("ready", 1))
    seq["state"], next_state["v"] = "failed", "failed"
    check("[5] failed again: one run per call", (gtc.ensure(CHAR, ITEM, runner=runner, retry_failed=True)["state"],
                                                 len(runs)), ("failed", 2))


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="smoke-plain-back-"))
    os.environ["STORAGE_DIR"] = str(root / "world")
    os.environ["INSTANCE_DIR"] = str(root / "instance")
    from app.core import paths
    paths.init(root / "world")
    paths.init_instance(root / "instance")
    plain, printed = section_decision(root)
    section_counts(plain, printed)
    section_fill()
    section_generate(root, plain, printed)
    section_ensure()
    check("network connects", len(CONNECTS), 0)
    print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
