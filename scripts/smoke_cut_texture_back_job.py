#!/usr/bin/env python3
"""Smoke: the Texture tab's back job — the payload with and without a back job, and the forced back job's key
(user question 2026-11-27: "the back template / back answer pictures are never filled" — a plain back view has no
back job; "Render back job…" forces one per piece).

Usage:
    ./.venv/bin/python scripts/smoke_cut_texture_back_job.py

Throwaway STORAGE_DIR / INSTANCE_DIR, no world, no hub, no server, no network. The code under test is the real
``garment_cut_texture`` (``csig``, ``csig_for``, ``back_forced_of``, ``predecessor_fit``, ``reused_jobs``,
``job_plan``, ``generate``, ``set_back_job``, ``dialog_state``) and the real route bodies of ``app/routes/figure.py``
(``_template_cut_body``, ``set_template_cut_back_job``). Stubbed: the cut state (one ready pattern), the item (its
params in a dict, its picture a file), the back view (a file), the routed render (it answers the template with every
non-white pixel set to A — one counted "image job"), the media switch / routing chain, ``figure.invalidate``.
Every expected value is derived by hand below.

Pictures: the item 1200 x 1200 (>= ``MIN_ITEM_SIDE`` 1024: no upscale), one A block. The back view 800 x 800, one
flat (40, 40, 150) block on transparent — no L* gradient anywhere, so its detail is 0.0 <= ``PLAIN_BACK_DETAIL``
0.20: PLAIN. Islands: front (20..200)^2, sleeve_l, back x 220..380 / y 20..200 on a 400 px atlas.

[A] The key. ``csig`` = md5("islands|item|back|prompt|POST_VERSION")[:12]; the forced back job appends
    "|back_job:render" — so an unforced key is byte-for-byte the one made before the flag existed, and the forced key
    differs. ``csig_for``: back_job "auto" -> the unforced key; "render" -> the forced key; "render" on a pattern
    WITHOUT a back panel -> the unforced no-back key (back sha "", no flag: nothing to force).
[F] The count of "Render back job…" (``plan.force_back``, review finding 2026-11-27: the button said "1 image job"
    and "the front answer is kept" although nothing was made yet). ``force_back`` = ``_plan_one`` with only="back"
    under the FORCED key, offered only while the back is plain. Before anything is made: no record under either key,
    so no front answer to keep -> front 1, back 1, upscale 0 (item 1200 px), total 2, reused []; with an item picture
    of 800 px (< ``MIN_ITEM_SIDE`` 1024) and the front to render -> upscale 1, total 3. After [B] made the front:
    the unforced record fits the forced key "cross" -> front 0, back 1, total 1, reused ["front"]. While forced [C]
    the back is not plain -> force_back None. Back to "auto" [D] -> again front 0, back 1, total 1, reused ["front"].
[B] Without a back job (back_job "auto", plain back view): ``generate`` renders ["front"] (1 job); the route payload
    (``_template_cut_body``): csig = the unforced key; back_plain True, back_measured_plain True, back_forced False,
    back_detail 0.0, plain_back_limit 0.20; files template_back False, raw_back False, back_ref True (the back view is
    written as Picture 2 whenever there is a back panel); urls template_back "" / raw_back "" / back_ref
    ".../cut/back_ref.png?v=<key>"; the plan back 0, redo only "front"; current True.
[C] "Render back job…" (route ``/cut/back-job`` {back_job "render", render true}): ``start`` is asked once with
    only="back"; the param is "render"; the payload's csig = the forced key, its record {} (nothing made under it),
    back_plain False, back_measured_plain True, back_forced True; the plan: front 0 (the front answer of the unforced
    key is re-used, ``predecessor_fit`` "cross"), back 1, total 1, reused ["front"], redo "back" and "front".
    ``generate(only="back")`` then renders ["back"] (0 front renders); record "ready", ``back_forced`` True, the back
    job's entry is an answer (no ``source`` "fabric"); payload files template_back / raw_back / back_ref True, urls
    with ?v=<forced key>; current True; "Redo back job" counts back 1 and keeps the front (reused ["front"]).
[D] Back to "auto" (no render, 0 jobs): ``start`` is not asked; csig = the unforced key again and its record is still
    "ready" (current True) — the plain atlas is not lost; the forced record stays on disk too.
[E] ``predecessor_fit`` / ``reused_jobs`` across the flag: the unforced record against the forced key -> "cross",
    against its own key -> "same"; a record without a back sha never fits "cross". With only the FORCED record on disk,
    ``reused_jobs`` for the unforced key takes its front (``reused_from`` = the forced key) but NOT its back answer
    (a forced back belongs to the other atlas), although that back is "ready" with its raw file.
[G] ``gt.back_job_of`` (effective policy from ``BACK_JOB_DEFAULTS``, trousers -> "render", every other kind -> "front"):
    {"kind": "trousers"} -> "render"; {"kind": "trousers", "back_job": "front"} -> "front"; {"kind": "top"} -> "front";
    {"kind": "top", "back_job": "render"} -> "render"; None -> "front".
[H] ``gct.back_key_forced`` truth table (the flag that goes into ``csig``: explicit "render" on any kind, or "auto" on
    a kind defaulting to "render" over a measured plain back):
      trousers auto + True -> True; trousers auto + False -> False; trousers auto + None -> False;
      trousers front + True -> False; trousers render + False -> True;
      top auto + True -> False; top front + True -> False; top render + False -> True.
[I] Trousers default ("kind": "trousers", "back_job": "auto", same plain back view):
    ``csig`` = md5("isl000|<item>|<back>|<trousers prompt>|<POST_VERSION>|back_job:render")[:12] (the FORCED key,
    because trousers default to "render" and the back measures plain); ``_template_cut_body`` returns that csig,
    back_forced True, back_plain False, back_job "auto", back_job_default "render"; ``generate`` renders
    ["front", "back"]. Calling ``/cut/back-job`` with {"back_job": "front"} stores "front" and moves the payload's csig
    to the UNFORCED trousers key (no "|back_job:render"), back_plain True, back_forced False, back_job "front",
    back_job_default "render", plan["back"] 0. Calling ``/cut/back-job`` with {"back_job": "bogus"} raises HTTP 400.
"""
import hashlib
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

CHAR, ITEM = "Kai", "jeans"
A = (120, 60, 30)
PARAMS = {"kind": "top", "texture": "cut", "sleeve_print": "plain", "back_job": "auto"}


def isl(name, x0, y0, x1, y1):
    return {"name": name, "verts_px": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]], "tris": [[0, 1, 2], [0, 2, 3]],
            "bbox_px": [x0, y0, x1, y1]}


PAYLOAD = {"atlas_px": 400, "px_per_cm": 10.0, "seams": [],
           "islands": [isl("front", 20, 20, 200, 200), isl("sleeve_l", 20, 220, 100, 300),
                       isl("back", 220, 20, 380, 200)]}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def install(tmp: Path):
    from app.core import figure, garment_template as gt, garment_template_cut as gtc, piece_jobs
    from app.core import garment_cut_texture as gct
    from app.imagegen import base as imagebase, routing
    from app.models import inventory
    islands_path = tmp / "islands.json"
    islands_path.write_text(json.dumps(PAYLOAD))
    item_png = tmp / "item.png"
    im = Image.new("RGBA", (1200, 1200), (0, 0, 0, 0))
    im.paste((*A, 255), (200, 200, 1000, 1000))
    im.save(item_png)
    back_png = tmp / "back_view.png"
    bv = Image.new("RGBA", (800, 800), (0, 0, 0, 0))
    bv.paste((40, 40, 150, 255), (100, 100, 700, 700))
    bv.save(back_png)
    gtc.state = lambda c, i, key=None: {"state": "ready", "reason": "", "cut_sig": "cutsig", "islands_sha": "isl000",
                                        "islands_path": islands_path, "cut_at": "2026-11-27T10:00:00", "wall_s": 1.0}
    gtc.schedule = lambda c, i: None
    gct.current_drape = lambda c, i: {"state": "missing", "reason": "", "tsig": None, "islands_path": None,
                                      "islands_sha": "", "record": {}, "worn": True}
    gct.cut_dir = lambda c: tmp / "cut"
    gct.back_view = lambda c, i: back_png
    gct._item_matte = lambda: None
    gct.piece_name = lambda iid: "Jeans"
    inventory.get_item = lambda iid: {"id": iid, "name": "Jeans", "prompt_fragment": ""}
    inventory.get_item_image_path = lambda iid: str(item_png)
    gt.params_of = lambda item: dict(PARAMS) if item else None
    gt.stored_of = lambda item: dict(PARAMS)

    def set_params(item_id, params, source="user"):
        PARAMS.clear()
        PARAMS.update(params)
    gt.set_params = set_params
    figure.invalidate = lambda *a, **k: None
    imagebase.media_generation_enabled = lambda: True
    routing.chain_for = lambda occ: [("FakeCut", "routing", 0)]
    piece_jobs.holder = lambda c, i: ""
    return islands_path, item_png, back_png


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="smoke-back-job-"))
    os.environ["STORAGE_DIR"] = str(root / "world")
    os.environ["INSTANCE_DIR"] = str(root / "instance")
    from app.core import paths
    paths.init(root / "world")
    paths.init_instance(root / "instance")
    from app.core import cut_texture_post as post
    from app.core import garment_cut_texture as gct
    from app.routes import figure as fr
    _islands, item_png, back_png = install(root)
    fr._template_item = lambda c, i: None

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

    # [A] the key
    print("[A] the key")
    isha, bsha, psha = sha(item_png), sha(back_png), gct.prompt_sha_of("top")
    base = f"isl000|{isha}|{bsha}|{psha}|{post.POST_VERSION}"
    want_plain = hashlib.md5(base.encode()).hexdigest()[:12]
    want_forced = hashlib.md5((base + "|back_job:render").encode()).hexdigest()[:12]
    check("[A] unforced key = the key without the flag", gct.csig("isl000", isha, bsha, psha), want_plain)
    check("[A] forced key appends |back_job:render", gct.csig("isl000", isha, bsha, psha, back_forced=True), want_forced)
    check("[A] csig_for auto", gct.csig_for(CHAR, ITEM, "isl000", PAYLOAD), want_plain)
    PARAMS["back_job"] = "render"
    check("[A] back_forced_of render", gct.back_forced_of(ITEM), True)
    check("[A] csig_for render", gct.csig_for(CHAR, ITEM, "isl000", PAYLOAD), want_forced)
    no_back = {"islands": [i for i in PAYLOAD["islands"] if i["name"] != "back"]}
    check("[A] render without a back panel: no flag, no back sha", gct.csig_for(CHAR, ITEM, "isl000", no_back),
          hashlib.md5(f"isl000|{isha}||{psha}|{post.POST_VERSION}".encode()).hexdigest()[:12])
    PARAMS["back_job"] = "auto"

    # [B] without a back job
    print("[F] the count of Render back job… before anything is made")
    p = fr._template_cut_body(CHAR, ITEM)
    fb = p["plan"]["force_back"]
    check("[F] nothing made: front + back, no reuse", (fb["upscale"], fb["front"], fb["back"], fb["total"], fb["reused"]),
          (0, 1, 1, 2, []))
    real_side = gct._item_side
    gct._item_side = lambda iid: 800
    try:
        fb = gct.job_plan(CHAR, ITEM)["force_back"]
    finally:
        gct._item_side = real_side
    check("[F] small item picture: + upscale", (fb["upscale"], fb["front"], fb["back"], fb["total"]), (1, 1, 1, 3))

    print("[B] the payload without a back job")
    rec = gct.generate(CHAR, ITEM, apply_after=False)
    check("[B] plain: 1 render (front), ready, the unforced key", (renders, rec.get("state"), rec.get("csig")),
          (["front"], "ready", want_plain))
    p = fr._template_cut_body(CHAR, ITEM)
    check("[B] csig", p["csig"], want_plain)
    check("[B] back flags", (p["back_plain"], p["back_measured_plain"], p["back_forced"], p["back_detail"],
                             p["plain_back_limit"]), (True, True, False, 0.0, 0.20))
    check("[B] files", {k: p["files"][k] for k in ("template_back", "raw_back", "back_ref")},
          {"template_back": False, "raw_back": False, "back_ref": True})
    check("[B] urls", (p["urls"]["template_back"], p["urls"]["raw_back"], p["urls"]["back_ref"]),
          ("", "", f"/characters/{CHAR}/figure/template/{ITEM}/cut/back_ref.png?v={want_plain}"))
    check("[B] plan: back 0, redo front only", (p["plan"]["back"], sorted(p["plan"]["redo"])), (0, ["front"]))
    check("[B] current", p["current"], True)
    fb = p["plan"]["force_back"]
    check("[F] front made: Render back job… keeps it", (fb["upscale"], fb["front"], fb["back"], fb["total"], fb["reused"]),
          (0, 0, 1, 1, ["front"]))

    # [C] Render back job…
    print("[C] Render back job…")
    started = []
    real_start = gct.start
    gct.start = lambda c, i, run=None, only=None: started.append(only) or True
    try:
        p = fr.set_template_cut_back_job(CHAR, ITEM, fr.TemplateCutBackJobRequest(back_job="render", render=True), {})
    finally:
        gct.start = real_start
    check("[C] start asked once with only=back", started, ["back"])
    check("[C] the param", PARAMS["back_job"], "render")
    check("[C] csig = forced key, no record yet", (p["csig"], p["record"]), (want_forced, {}))
    check("[C] back flags", (p["back_plain"], p["back_measured_plain"], p["back_forced"]), (False, True, True))
    plan = p["plan"]
    check("[C] plan: front re-used, back 1", (plan["front"], plan["back"], plan["total"], plan["reused"],
                                              sorted(plan["redo"])), (0, 1, 1, ["front"], ["back", "front"]))
    renders.clear()
    rec = gct.generate(CHAR, ITEM, only="back", apply_after=False)
    check("[C] 1 render (back), ready", (renders, rec.get("state"), rec.get("csig")), (["back"], "ready", want_forced))
    check("[C] the record carries the flag; the back is an answer",
          (rec.get("back_forced"), (rec.get("back_plain") or {}).get("forced"), (rec.get("back_plain") or {}).get("plain"),
           rec["jobs"]["back"].get("source"), rec["jobs"]["back"].get("state")), (True, True, False, None, "ready"))
    p = fr._template_cut_body(CHAR, ITEM)
    check("[C] files", {k: p["files"][k] for k in ("template_back", "raw_back", "back_ref")},
          {"template_back": True, "raw_back": True, "back_ref": True})
    check("[C] urls", (p["urls"]["template_back"], p["urls"]["raw_back"]),
          (f"/characters/{CHAR}/figure/template/{ITEM}/cut/template_back.png?v={want_forced}",
           f"/characters/{CHAR}/figure/template/{ITEM}/cut/raw_back.png?v={want_forced}"))
    check("[C] current", p["current"], True)
    check("[F] forced: no Render back job count", p["plan"]["force_back"], None)
    redo_back = p["plan"]["redo"]["back"]
    check("[C] Redo back job: back 1, front kept", (redo_back["back"], redo_back["front"], redo_back["reused"]),
          (1, 0, ["front"]))

    # [D] back to auto
    print("[D] back to auto")
    started.clear()
    gct.start = lambda c, i, run=None, only=None: started.append(only) or True
    try:
        p = fr.set_template_cut_back_job(CHAR, ITEM, fr.TemplateCutBackJobRequest(back_job="auto"), {})
    finally:
        gct.start = real_start
    check("[D] no start, param auto", (started, PARAMS["back_job"]), ([], "auto"))
    check("[D] the unforced key and its ready record", (p["csig"], p["record"].get("state"), p["current"]),
          (want_plain, "ready", True))
    fb = p["plan"]["force_back"]
    check("[F] back to auto: the front is kept again", (fb["front"], fb["back"], fb["total"], fb["reused"]),
          (0, 1, 1, ["front"]))
    check("[D] the forced record stays", gct.read_record(CHAR, ITEM, want_forced).get("state"), "ready")

    # [E] across the flag
    print("[E] predecessor_fit / reused_jobs")
    rec_plain = gct.read_record(CHAR, ITEM, want_plain)
    check("[E] unforced record vs forced key / own key",
          (gct.predecessor_fit(rec_plain, want_forced), gct.predecessor_fit(rec_plain, want_plain)), ("cross", "same"))
    check("[E] no back sha: never cross", gct.predecessor_fit({**rec_plain, "back_sha": ""}, want_forced), None)
    gct._file(gct._stem(CHAR, ITEM, want_plain), ".json").unlink()
    reuse = gct.reused_jobs(CHAR, ITEM, want_plain, ["front", "back"])
    rec_forced = gct.read_record(CHAR, ITEM, want_forced)
    check("[E] the forced back is ready with its answer file",
          (rec_forced["jobs"]["back"]["state"], gct._file(gct._stem(CHAR, ITEM, want_forced), ".raw_back.png").is_file()),
          ("ready", True))
    check("[E] reused for the unforced key: the front only", (sorted(reuse), reuse.get("front", {}).get("reused_from")),
          (["front"], want_forced))

    # [G] gt.back_job_of
    print("[G] gt.back_job_of")
    from app.core import garment_template as gt
    check("[G] trousers default -> render", gt.back_job_of({"kind": "trousers"}), "render")
    check("[G] trousers front -> front", gt.back_job_of({"kind": "trousers", "back_job": "front"}), "front")
    check("[G] top default -> front", gt.back_job_of({"kind": "top"}), "front")
    check("[G] top render -> render", gt.back_job_of({"kind": "top", "back_job": "render"}), "render")
    check("[G] None -> front", gt.back_job_of(None), "front")

    # [H] gct.back_key_forced truth table
    print("[H] gct.back_key_forced truth table")
    for label, params, measured, want in (
        ("trousers auto + plain True", {"kind": "trousers", "back_job": "auto"}, True, True),
        ("trousers auto + plain False", {"kind": "trousers", "back_job": "auto"}, False, False),
        ("trousers auto + plain None", {"kind": "trousers", "back_job": "auto"}, None, False),
        ("trousers front + plain True", {"kind": "trousers", "back_job": "front"}, True, False),
        ("trousers render + plain False", {"kind": "trousers", "back_job": "render"}, False, True),
        ("top auto + plain True", {"kind": "top", "back_job": "auto"}, True, False),
        ("top front + plain True", {"kind": "top", "back_job": "front"}, True, False),
        ("top render + plain False", {"kind": "top", "back_job": "render"}, False, True),
    ):
        check(f"[H] {label}", gct.back_key_forced(params, measured), want)

    # [I] trousers default
    print("[I] trousers default")
    PARAMS.clear()
    PARAMS.update({"kind": "trousers", "texture": "cut", "sleeve_print": "plain", "back_job": "auto"})
    psha_tr = gct.prompt_sha_of("trousers")
    base_tr = f"isl000|{isha}|{bsha}|{psha_tr}|{post.POST_VERSION}"
    want_tr_unforced = hashlib.md5(base_tr.encode()).hexdigest()[:12]
    want_tr_forced = hashlib.md5((base_tr + "|back_job:render").encode()).hexdigest()[:12]
    p = fr._template_cut_body(CHAR, ITEM)
    check("[I] trousers auto payload csig = forced key", p["csig"], want_tr_forced)
    check("[I] trousers auto back flags",
          (p["back_forced"], p["back_plain"], p["back_job"], p["back_job_default"]),
          (True, False, "auto", "render"))
    renders.clear()
    rec = gct.generate(CHAR, ITEM, apply_after=False)
    check("[I] trousers auto generate renders front and back",
          (renders, rec.get("state"), rec.get("csig"), rec.get("back_forced")),
          (["front", "back"], "ready", want_tr_forced, True))
    p = fr.set_template_cut_back_job(CHAR, ITEM, fr.TemplateCutBackJobRequest(back_job="front"), {})
    check("[I] trousers set front: stored and unforced key",
          (PARAMS["back_job"], p["csig"], p["back_plain"], p["back_forced"], p["back_job"], p["back_job_default"],
           p["plan"]["back"]),
          ("front", want_tr_unforced, True, False, "front", "render", 0))
    from fastapi import HTTPException
    bogus_status = None
    try:
        fr.set_template_cut_back_job(CHAR, ITEM, fr.TemplateCutBackJobRequest(back_job="bogus"), {})
    except HTTPException as exc:
        bogus_status = exc.status_code
    check("[I] bogus back_job -> HTTP 400", bogus_status, 400)

    check("network connects", len(CONNECTS), 0)
    print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
