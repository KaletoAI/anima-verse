#!/usr/bin/env python3
"""Smoke: the texture from cut is a real step of the character's Build (user test 2026-11-21 — Tilda's and Dario's
shirts were draped by the Build and stayed on the projection until someone clicked "Make texture from cut").

Usage:
    ./.venv/bin/python scripts/smoke_cut_texture_build.py

Throwaway STORAGE_DIR / INSTANCE_DIR, no world, no hub, no Blender, no server, no network (every socket connect is
counted and must stay 0). The figure resolver and the producers are stubbed by small tables; the code under test is
the real ``figure_build.plan`` / ``cost`` / ``_open_group`` / ``_run_planned`` / ``_prestart_cut_texture`` and the real
``garment_cut_texture.build_state`` / ``run_for_build`` / ``build_start`` / ``build_join`` plus
``cut_texture_post.drop_strays``. Every number below is derived by hand.

The item "shirt" ("Cream Blouse") is a worn template top, ``texture`` "cut"; its drape is ready (no ``template``
step), the outfit model's recorded figure is the delivered one (nothing else to assemble).

[1] build_state (the step's inputs; ``garment_template_cut.cut_key`` / ``state``, ``job_plan``, ``read_record``,
    ``atlas_path``, ``item_sha``, ``back_view``, ``_item_side`` stubbed):
    - texture "projection" -> "off", 0 jobs.
    - cut ready, no record for the csig, ``job_plan`` total 2 (front + back; the back view exists, the item is
      1200 px >= 1024 so no upscale) -> "due", 2 jobs, estimate False.
    - cut not made yet ("missing"), no back view, item 600 px (< 1024: one upscale) -> "due", estimate True,
      jobs = 1 (back view) + 1 (upscale) + 2 (front, back) = 4.
    - lower layer still to drape (``cut_key`` sig None, reason ``WAITING_LOWER``) -> "due", estimate True, 4 jobs.
    - not a pattern kind (sig None, reason ``NO_PATTERN``) -> "off".
    - record "ready", atlas on disk, same sleeve option -> "done"; other sleeve option -> "compose" (0 jobs).
    - record "rejected" with reason "Back: coverage 0.65 < 0.97", job_plan total 1 (the front answer passed and is
      re-used) -> "failed", reason kept, 1 job.
    - the cut failed -> "failed" with the cut's reason ``CUT_FAILED.format(error="boom")``.
[2] plan / cost / open steps (``figure_build.plan`` on the stubbed figure):
    - "done" -> ``plan == []`` (the Build is current).
    - "due" 2 jobs -> [("cut_texture", "shirt", 2), ("assemble", 0)]: label "Texture from cut · Cream Blouse (+2 image
      jobs)"; ``cost`` hub_jobs 2 and the note "2 hub jobs (estimate, retries extra) — +2 image jobs for the cut
      texture"; ``_open_group`` of the plan: count 2, hub_jobs 2, hold False.
    - "failed" (1 job) -> the step "… (+1 image jobs) — failed — Retry" with ``failed`` = the reason; an automatic
      plan's runnable steps (``_runnable(steps, False)``) are [] — a cached failure is never re-spent automatically —
      and the open steps hold it (hold True, why = the reason); a manual plan runs it (runnable = cut_texture +
      assemble).
    - "compose" -> the step "Texture from cut · Cream Blouse: compose again (CPU, 0 hub jobs)", 0 jobs.
[3] run_for_build (``generate`` / ``recompose`` stubbed: they record the call and return a record):
    - due, media on, a chain -> ``generate`` once with ``apply_after`` False (the Build assembles), ok True; afterwards
      the piece is free again (``piece_jobs.holder`` "") and the dialog's ``status`` is not running.
    - media off -> not ok, reason ``MEDIA_OFF``, ``generate`` not called; an empty chain -> ``BLOCKED_ROUTING``.
    - cached failure, automatic -> not ok, reason kept, no ``generate``; manual -> ``generate`` once.
    - compose -> ``recompose`` once, no ``generate``, also with media off (CPU only).
    - NO DOUBLE SUBMIT: the dialog's flow runs (``_running`` "running" + ``piece_jobs`` claim "cut"); the Build's run
      waits (poll 0.02 s); the dialog flow ends and its record is ready (build_state -> "done") -> the Build's run
      answers ok without calling ``generate`` at all (0 calls). A view flow holds the piece ("view:back") for longer
      than the wait (0.2 s) -> not ok, reason ``BUILD_BUSY`` naming the view.
    - ``build_start`` twice while the first runs -> True, then False (reused); ``build_join`` -> its result;
      ``generate`` ran once.
[4] _run_planned with a drape AND the cut texture planned ([template shirt, cut_texture shirt, assemble]): the drape
    runner sleeps 0.3 s; the cut flow starts BEFORE the drape ends (it runs beside it — ``_prestart_cut_texture``),
    the cut_texture step joins it, the assembly runs after both; ``generate`` ran once. An automatic run of a plan
    whose cut_texture step is a cached failure does not pre-start anything (0 ``build_start`` calls) and records
    the step failed with its reason; a pattern that cannot be cut yet (sig None) is not pre-started either.
[6] Review minors 2026-11-21:
    (a) a Build that breaks out between ``_prestart_cut_texture`` and the cut_texture step (the base views change while
        the drape runs: Ruling A26 b stops it there, cut_texture and assemble skipped) leaves NO entry in ``garment_cut_texture._build_runs`` once the pre-started run ends (it was released by the
        Build's end); a later ``build_join`` therefore RUNS (generate count 1 -> 2) instead of returning the old
        result. ``build_release`` of a finished entry -> True and gone; of none -> False.
    (b) a failed CUT (``build_state`` "failed", ``retry`` "cut", jobs = the estimate: back view present but not
        measured plain (the stub's back.png does not exist) -> 0 + 0 (1200 px) + front 1 + back 1 = 2, estimate True):
        an automatic Build -> not ok, ``ensure`` not called; a manual one -> ``ensure`` called with
        ``retry_failed`` True, the cut is ready again, ``generate`` once, ok. A rejected record -> ``retry`` "jobs";
        no item picture -> ``retry`` "" and a manual Build runs nothing (no ``ensure``, no ``generate``), reason
        ``BLOCKED_PICTURE``.
    (c) the dialog's ``status`` after a Build run whose record came back "rejected": ``error`` "" (the reason is the
        record's, like a dialog flow), not running; after a run that RAISED: ``error`` = the raised text.
[5] drop_strays (``cut_texture_post``): mask = a 100 x 100 square (rows/cols 20..119) in a 256 canvas.
    - answer = the square in place + a separate 60 x 60 block (rows/cols 160..219): the kept piece covers the mask
      fully (1.0 >= 0.5) -> the block is dropped; strays = 3600 / 10000 = 0.36; the returned foreground equals the
      mask; ``resample_register`` then finds the identity map (coverage 1.0) instead of a box spanning both pieces
      (without the drop the box fit is (219 - 20 + 1) / 100 = 2.0x).
    - answer = the square shifted right by 60 px (cols 80..179: covers 40 of the mask's 100 columns = 0.4 < 0.5) +
      the block -> nothing dropped (strays 0.0): the model moved the panel, the registration must see everything.
    - one piece only -> nothing to drop (strays 0.0).
"""
import contextlib
import os
import socket
import sys
import tempfile
import threading
import time
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS = []
CONNECTS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


_real_connect = socket.create_connection


def _no_connect(*a, **k):
    CONNECTS.append(a)
    raise OSError("network disabled in this smoke")


socket.create_connection = _no_connect

CHAR = "Tilda"
ITEM = "shirt"


class State:
    """The tables the stubs read."""

    def __init__(self):
        self.texture = "cut"
        self.cut = {"sig": "cutsig000001", "reason": ""}
        self.cut_state = {"state": "ready", "reason": "", "islands_sha": "isl", "islands_path": Path("x.json")}
        self.plan_total = 2
        self.record = {}
        self.atlas = False
        self.sleeve = "plain"
        self.back_view = True
        self.side = 1200
        self.media = True
        self.chain = ["P-H3-Image"]


S = State()


def install():
    from app.core import garment_cut_texture as gct
    from app.core import garment_template as gt
    from app.core import garment_template_cut as gtc
    from app.imagegen import base as imgbase
    from app.imagegen import routing
    from app.models import inventory
    gt.params_of = lambda item: {"kind": "top", "texture": S.texture, "sleeve_print": S.sleeve}
    inventory.get_item = lambda iid: {"id": iid, "name": "Cream Blouse"}
    gtc.cut_key = lambda c, i, profile=None, item=None: dict(S.cut)
    gtc.state = lambda c, i, key=None: dict(S.cut_state)
    gtc.ensure = lambda c, i, timeout_s=0, **k: dict(S.cut_state)
    gct._islands_of = lambda pattern: {"islands": [{"name": "front"}, {"name": "back"}]}
    gct.item_sha = lambda iid: "itemsha"
    gct.csig_for = lambda c, i, sha, islands=None, has_back_panel=None: "csig00000001"
    gct.read_record = lambda c, i, sig: dict(S.record)
    # "max" = "total": the stub counts no second attempt (key isolation 2026-11-25 reads it for the label)
    gct.job_plan = lambda c, i, islands=None, islands_sha="": {"total": S.plan_total, "max": S.plan_total}

    class _Atlas:
        def is_file(self):
            return S.atlas
    gct.atlas_path = lambda c, i, sig: _Atlas()
    gct.back_view = lambda c, i: Path("back.png") if S.back_view else None
    gct._item_side = lambda iid: S.side
    imgbase.media_generation_enabled = lambda: S.media
    routing.chain_for = lambda occasion: list(S.chain)


CALLS = {"generate": [], "recompose": []}


def stub_flows(delay=0.0, record_state="ready"):
    from app.core import garment_cut_texture as gct
    CALLS["generate"].clear()
    CALLS["recompose"].clear()

    def generate(c, i, *, only=None, apply_after=True):
        CALLS["generate"].append((time.monotonic(), apply_after))
        time.sleep(delay)
        return {"state": record_state, "reason": "" if record_state == "ready" else "Back: coverage 0.65 < 0.97"}

    def recompose(c, i, *, accept=None, apply_after=True):
        CALLS["recompose"].append(apply_after)
        return {"state": "ready", "reason": ""}
    gct.generate = generate
    gct.recompose = recompose


def section_state():
    from app.core import garment_cut_texture as gct
    from app.core import garment_template_cut as gtc
    print("[1] build_state")
    S.__init__()
    S.texture = "projection"
    check("[1] projection -> off", gct.build_state(CHAR, ITEM)["state"], "off")
    S.__init__()
    st = gct.build_state(CHAR, ITEM)
    check("[1] cut ready, nothing made -> due 2", (st["state"], st["jobs"], st["estimate"]), ("due", 2, False))
    S.cut_state = {"state": "missing", "reason": gtc.NOT_CUT}
    S.back_view, S.side = False, 600
    st = gct.build_state(CHAR, ITEM)
    check("[1] not cut, no back view, small item -> due 4 (estimate)", (st["state"], st["jobs"], st["estimate"]),
          ("due", 4, True))
    S.cut = {"sig": None, "reason": gtc.WAITING_LOWER}
    st = gct.build_state(CHAR, ITEM)
    check("[1] waiting for the lower layers -> due 4 (estimate)", (st["state"], st["jobs"], st["estimate"]),
          ("due", 4, True))
    S.cut = {"sig": None, "reason": gtc.NO_PATTERN}
    check("[1] not a pattern kind -> off", gct.build_state(CHAR, ITEM)["state"], "off")
    S.__init__()
    S.record, S.atlas = {"state": "ready", "sleeve_print": "plain"}, True
    check("[1] ready + atlas -> done", gct.build_state(CHAR, ITEM)["state"], "done")
    S.sleeve = "picture"
    st = gct.build_state(CHAR, ITEM)
    check("[1] other sleeve option -> compose 0", (st["state"], st["jobs"]), ("compose", 0))
    S.__init__()
    S.record, S.plan_total = {"state": "rejected", "reason": "Back: coverage 0.65 < 0.97"}, 1
    st = gct.build_state(CHAR, ITEM)
    check("[1] rejected -> failed 1 with its reason", (st["state"], st["jobs"], st["reason"]),
          ("failed", 1, "Back: coverage 0.65 < 0.97"))
    S.__init__()
    S.cut_state = {"state": "failed", "reason": gtc.CUT_FAILED.format(error="boom")}
    st = gct.build_state(CHAR, ITEM)
    check("[1] cut failed -> failed", (st["state"], st["reason"]), ("failed", gtc.CUT_FAILED.format(error="boom")))


def install_figure():
    from app.core import base_body, figure, figure_build, garment_refit
    from app.core.figure import Figure
    fig = Figure(signature="sig1", bsig="b1", shape="b1", texture="tex1", in_body=(), own=(ITEM,),
                 pieces={"top": ITEM}, template=(ITEM,))
    base_body.is_base_pipeline = lambda c, profile=None: True
    figure._delivered = lambda c, profile=None, **k: (fig, fig)
    figure.is_plain = lambda shape: True
    base_body.base_refresh_plan = lambda c, profile=None, missing=False: {}
    base_body.dressed_view_jobs = lambda: 0
    figure_build._profile_of = lambda c, p: p or {}
    figure_build._read_profile = lambda c: {}
    figure_build._mesh_repair_due = lambda c, b: False
    figure_build._tip_smoothing_due = lambda c, b: False
    figure_build._views_missing = lambda c, d, s: False
    figure_build._assemble_held = lambda c, s, d: None
    figure_build._collision_due = lambda c: False
    figure_build._model_figure = lambda c, s: fig
    figure_build._template_step = lambda c, i, d, p: None
    garment_refit.work_count = lambda c, profile=None: 0
    return fig


def names(steps):
    return [(s.name, s.item_id, s.jobs) if s.item_id else (s.name, s.jobs) for s in steps]


def section_plan():
    from app.core import figure_build as fb
    print("[2] plan / cost / open steps")
    install_figure()
    S.__init__()
    S.record, S.atlas = {"state": "ready", "sleeve_print": "plain"}, True
    check("[2] done -> nothing to build", fb.plan(CHAR), [])
    S.__init__()
    steps = fb.plan(CHAR)
    check("[2] due -> cut_texture + assemble", names(steps), [("cut_texture", ITEM, 2), ("assemble", 0)])
    check("[2] label", steps[0].label, "Texture from cut · Cream Blouse (+2 image jobs)")
    cost = fb.cost(CHAR, steps)
    check("[2] cost", (cost["hub_jobs"], cost["note"]),
          (2, "2 hub jobs (estimate, retries extra) — +2 image jobs for the cut texture"))
    grp = fb._open_group(steps)
    check("[2] open steps", (grp["count"], grp["hub_jobs"], grp["hold"]), (2, 2, False))
    S.record, S.plan_total = {"state": "rejected", "reason": "Back: coverage 0.65 < 0.97"}, 1
    steps = fb.plan(CHAR, explicit=False)
    check("[2] failed label", steps[0].label, "Texture from cut · Cream Blouse (+1 image jobs)" + fb.FAILED_SUFFIX)
    check("[2] failed reason", steps[0].failed, "Back: coverage 0.65 < 0.97")
    check("[2] automatic runnable: nothing", names(fb._runnable(steps, False)), [])
    grp = fb._open_group(fb.plan(CHAR))
    check("[2] open steps hold it", (grp["hold"], grp["steps"][0]["why"]), (True, "Back: coverage 0.65 < 0.97"))
    check("[2] manual runnable", [s.name for s in fb._runnable(fb.plan(CHAR), True)], ["cut_texture", "assemble"])
    S.__init__()
    S.record, S.atlas, S.sleeve = {"state": "ready", "sleeve_print": "plain"}, True, "picture"
    steps = fb.plan(CHAR)
    check("[2] compose", (steps[0].label, steps[0].jobs),
          ("Texture from cut · Cream Blouse: compose again (CPU, 0 hub jobs)", 0))


def section_run():
    from app.core import garment_cut_texture as gct
    from app.core import piece_jobs
    print("[3] run_for_build")
    S.__init__()
    stub_flows()
    res = gct.run_for_build(CHAR, ITEM, explicit=False)
    check("[3] due -> generate once, apply_after False", (res["ok"], [a for _t, a in CALLS["generate"]]),
          (True, [False]))
    check("[3] piece free afterwards", (piece_jobs.holder(CHAR, ITEM), gct.status(CHAR, ITEM)["running"]),
          ("", False))
    stub_flows()
    S.media = False
    res = gct.run_for_build(CHAR, ITEM, explicit=True)
    check("[3] media off", (res["ok"], res["reason"], len(CALLS["generate"])), (False, gct.MEDIA_OFF, 0))
    S.media, S.chain = True, []
    res = gct.run_for_build(CHAR, ITEM, explicit=True)
    check("[3] empty chain", (res["ok"], res["reason"], len(CALLS["generate"])), (False, gct.BLOCKED_ROUTING, 0))
    S.__init__()
    S.record = {"state": "rejected", "reason": "Back: coverage 0.65 < 0.97"}
    res = gct.run_for_build(CHAR, ITEM, explicit=False)
    check("[3] cached failure, automatic", (res["ok"], res["reason"], len(CALLS["generate"])),
          (False, "Back: coverage 0.65 < 0.97", 0))
    res = gct.run_for_build(CHAR, ITEM, explicit=True)
    check("[3] cached failure, manual retries", (res["ok"], len(CALLS["generate"])), (True, 1))
    S.__init__()
    stub_flows()
    S.record, S.atlas, S.sleeve, S.media = {"state": "ready", "sleeve_print": "plain"}, True, "picture", False
    res = gct.run_for_build(CHAR, ITEM, explicit=False)
    check("[3] compose", (res["ok"], len(CALLS["recompose"]), len(CALLS["generate"])), (True, 1, 0))

    # no double submit: the dialog's own flow holds the piece
    S.__init__()
    stub_flows()
    key = (CHAR, ITEM)
    with gct._lock:
        gct._running[key] = "running"
    piece_jobs.claim(CHAR, ITEM, "cut")
    out = {}
    th = threading.Thread(target=lambda: out.update(gct.run_for_build(CHAR, ITEM, explicit=False, poll_s=0.02)))
    th.start()
    time.sleep(0.15)
    check("[3] waits while the dialog's flow runs", th.is_alive(), True)
    S.record, S.atlas = {"state": "ready", "sleeve_print": "plain"}, True   # the dialog's flow made it
    with gct._lock:
        gct._running[key] = "done"
    piece_jobs.release(CHAR, ITEM, "cut")
    th.join(5)
    check("[3] then reads its record, no second submit", (out.get("ok"), len(CALLS["generate"])), (True, 0))
    S.__init__()
    piece_jobs.claim(CHAR, ITEM, "view:back")
    res = gct.run_for_build(CHAR, ITEM, explicit=False, wait_s=0.2, poll_s=0.02)
    check("[3] a view flow holds the piece too long", (res["ok"], res["reason"]),
          (False, gct.BUILD_BUSY.format(reason=piece_jobs.REASONS["view:back"])))
    piece_jobs.release(CHAR, ITEM, "view:back")

    stub_flows(delay=0.3)
    first = gct.build_start(CHAR, ITEM, explicit=False)
    second = gct.build_start(CHAR, ITEM, explicit=False)
    res = gct.build_join(CHAR, ITEM, explicit=False)
    check("[3] build_start twice -> True, False; one generate", (first, second, res["ok"], len(CALLS["generate"])),
          (True, False, True, 1))


def section_run_planned():
    from app.core import cpu_progress, figure_build as fb, generation_pause, model3d
    from app.core import garment_cut_texture as gct
    from app.core import garment_template_cut as gtc
    print("[4] _run_planned: the cut texture runs beside the drape")
    install_figure()
    S.__init__()
    stub_flows(delay=0.1)
    events = []
    template = fb.Step("template", "Template drape · Cream Blouse", 0, ITEM)
    fb._template_step = lambda c, i, d, p: template
    fb._tracked = lambda c, label: (None, "")
    fb._pin = lambda c, w: None
    fb._check_pin = lambda c: None
    fb._base_snapshot = lambda c: None
    fb._base_changed = lambda c, snap: []
    fb.base_step_in_flight = lambda c: ""
    generation_pause.is_paused = lambda c: False
    model3d.generation_slot = lambda c, **k: contextlib.nullcontext()
    gtc.cut_key = lambda c, i, profile=None, item=None: dict(S.cut)

    def drape(c, step, explicit=False):
        events.append(("drape_start", time.monotonic()))
        time.sleep(0.3)
        events.append(("drape_end", time.monotonic()))
        fb._template_step = lambda *a: None
        return ""

    def assemble(c, step, explicit=False):
        events.append(("assemble", time.monotonic()))
        return ""
    real_gen = gct.generate

    def generate(c, i, *, only=None, apply_after=True):
        events.append(("cut_start", time.monotonic()))
        return real_gen(c, i, only=only, apply_after=apply_after)
    gct.generate = generate
    fb._RUNNERS["template"] = drape
    fb._RUNNERS["assemble"] = assemble
    fb._run_planned(CHAR, "test", {}, automatic=False)
    when = dict(events)
    order = [e for e, _t in sorted(events, key=lambda x: x[1])]
    check("[4] plan ran template, cut_texture, assemble",
          fb.state(CHAR)["failed"], {})
    check("[4] the cut flow started before the drape ended", when.get("cut_start", 9e9) < when.get("drape_end", 0),
          True)
    check("[4] assembly after both", order[-1], "assemble")
    check("[4] generate once", len(CALLS["generate"]), 1)

    # an automatic run with a cached failure pre-starts nothing
    started = []
    real_start = gct.build_start
    gct.build_start = lambda c, i, explicit: (started.append(i), True)[1]
    S.record, S.plan_total = {"state": "rejected", "reason": "Back: coverage 0.65 < 0.97"}, 1
    fb._template_step = lambda c, i, d, p: template
    fb._run_planned(CHAR, "auto", {}, automatic=True)
    check("[4] automatic + cached failure: nothing pre-started", started, [])
    check("[4] automatic + cached failure: recorded with its reason",
          fb.state(CHAR)["failed"].get("cut_texture", {}).get("error"), "Back: coverage 0.65 < 0.97")
    S.record = {}
    S.cut = {"sig": None, "reason": gtc.WAITING_LOWER}
    later = fb.Step("cut_texture", "x", 4, ITEM)
    fb._prestart_cut_texture(CHAR, template, [later], True)
    check("[4] a pattern that cannot be cut yet is not pre-started", started, [])
    S.cut = {"sig": "cutsig000001", "reason": ""}
    fb._prestart_cut_texture(CHAR, template, [later], True)
    check("[4] ... and one that can is", started, [ITEM])
    gct.build_start = real_start
    gct.generate = real_gen


def section_minors():
    from app.core import figure_build as fb
    from app.core import garment_cut_texture as gct
    print("[6] review minors")
    # (a) a Build that breaks out after the pre-start
    install_figure()
    S.__init__()
    stub_flows(delay=0.3)
    template = fb.Step("template", "Template drape · Cream Blouse", 0, ITEM)
    fb._template_step = lambda c, i, d, p: template

    moved = {"on": False}

    def drape(c, step, explicit=False):
        moved["on"] = True          # the base views change while it drapes: the Build stops after this step
        return ""
    real_drape, real_changed = fb._RUNNERS["template"], fb._base_changed
    fb._RUNNERS["template"] = drape
    fb._base_changed = lambda c, snap: ["front"] if moved["on"] else []
    try:
        fb._run_planned(CHAR, "test", {}, automatic=False)
        check("[6a] the Build stopped after the drape", fb.state(CHAR)["skipped"][:1], ["cut_texture"])
        with gct._lock:
            entry = gct._build_runs.get((CHAR, ITEM))
        check("[6a] the pre-started run is released (still running)", bool(entry and entry.get("released")), True)
        entry["thread"].join(5)
        with gct._lock:
            left = (CHAR, ITEM) in gct._build_runs
        check("[6a] ... and gone once it ended", (left, len(CALLS["generate"])), (False, 1))
        res = gct.build_join(CHAR, ITEM, explicit=False)
        check("[6a] the next join runs again", (res["ok"], len(CALLS["generate"])), (True, 2))
        gct.build_start(CHAR, ITEM, explicit=False)
        with gct._lock:
            th = gct._build_runs[(CHAR, ITEM)]["thread"]
        th.join(5)
        check("[6a] build_release of a finished run -> True, gone; again -> False",
              (gct.build_release(CHAR, ITEM), (CHAR, ITEM) in gct._build_runs, gct.build_release(CHAR, ITEM)),
              (True, False, False))
    finally:
        fb._RUNNERS["template"], fb._base_changed = real_drape, real_changed
        fb._template_step = lambda c, i, d, p: None

    # (b) a manual Build re-runs only what failed
    from app.core import garment_template_cut as gtc
    ensured = []

    def ensure(c, i, timeout_s=0, retry_failed=False, **k):
        ensured.append(retry_failed)
        if retry_failed:
            S.cut_state = {"state": "ready", "reason": "", "islands_sha": "isl", "islands_path": Path("x.json")}
        return dict(S.cut_state)
    real_ensure = gtc.ensure
    gtc.ensure = ensure
    try:
        S.__init__()
        stub_flows()
        S.cut_state = {"state": "failed", "reason": gtc.CUT_FAILED.format(error="boom")}
        st = gct.build_state(CHAR, ITEM)
        check("[6b] failed cut: retry cut, jobs 2 (estimate)", (st["state"], st["retry"], st["jobs"], st["estimate"]),
              ("failed", "cut", 2, True))
        res = gct.run_for_build(CHAR, ITEM, explicit=False)
        check("[6b] automatic: skipped, no ensure", (res["ok"], ensured, len(CALLS["generate"])), (False, [], 0))
        res = gct.run_for_build(CHAR, ITEM, explicit=True)
        check("[6b] manual: the cut once more, then generate", (res["ok"], ensured, len(CALLS["generate"])),
              (True, [True], 1))
        S.__init__()
        S.record = {"state": "rejected", "reason": "Back: coverage 0.65 < 0.97"}
        check("[6b] rejected record: retry jobs", gct.build_state(CHAR, ITEM)["retry"], "jobs")
        S.__init__()
        stub_flows()
        ensured.clear()
        real_sha = gct.item_sha
        gct.item_sha = lambda iid: None
        try:
            st = gct.build_state(CHAR, ITEM)
            res = gct.run_for_build(CHAR, ITEM, explicit=True)
        finally:
            gct.item_sha = real_sha
        check("[6b] no picture: nothing to re-run", (st["retry"], res["ok"], res["reason"], ensured,
                                                     len(CALLS["generate"])),
              ("", False, gct.BLOCKED_PICTURE, [], 0))
    finally:
        gtc.ensure = real_ensure

    # (c) the dialog's status after a Build run
    S.__init__()
    stub_flows(record_state="rejected")
    res = gct.run_for_build(CHAR, ITEM, explicit=False)
    st = gct.status(CHAR, ITEM)
    check("[6c] rejected record: no flow error", (res["ok"], res["reason"], st["error"], st["running"]),
          (False, "Back: coverage 0.65 < 0.97", "", False))

    def boom(c, i, *, only=None, apply_after=True):
        raise RuntimeError("the hub fell over")
    gct.generate = boom
    S.__init__()
    res = gct.run_for_build(CHAR, ITEM, explicit=False)
    check("[6c] a raised run: its text is the flow error", (res["ok"], gct.status(CHAR, ITEM)["error"]),
          (False, "the hub fell over"))


def section_strays():
    import numpy as np
    from PIL import Image
    from app.core import cut_texture_post as post
    print("[5] drop_strays")
    mask = np.zeros((256, 256), bool)
    mask[20:120, 20:120] = True
    arr = np.full((256, 256, 3), 255, np.uint8)
    arr[20:120, 20:120] = (40, 80, 160)
    arr[160:220, 160:220] = (200, 30, 30)
    fg = post.foreground(arr)
    out, kept, strays = post.drop_strays(arr, fg, mask)
    check("[5] block dropped, strays 0.36", (strays, bool((kept == mask).all())), (0.36, True))
    check("[5] the block is white now", tuple(out[190, 190]), (255, 255, 255))
    reg, info = post.resample_register(Image.fromarray(arr), mask)
    ok, met, _reason = post.gate(reg, mask, mask.astype(np.uint8), 10.0)
    check("[5] registered: identity, coverage 1.0", (met["coverage"], round(info["map"][0], 2), info["strays"]),
          (1.0, 1.0, 0.36))
    moved = np.full((256, 256, 3), 255, np.uint8)
    moved[20:120, 80:180] = (40, 80, 160)
    moved[160:220, 190:250] = (200, 30, 30)
    _o, _k, strays = post.drop_strays(moved, post.foreground(moved), mask)
    check("[5] a moved panel (0.4 < 0.5): nothing dropped", strays, 0.0)
    one = np.full((256, 256, 3), 255, np.uint8)
    one[20:120, 20:120] = (40, 80, 160)
    _o, _k, strays = post.drop_strays(one, post.foreground(one), mask)
    check("[5] one piece: nothing to drop", strays, 0.0)


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="smoke-cut-build-"))
    os.environ["STORAGE_DIR"] = str(root / "world")
    os.environ["INSTANCE_DIR"] = str(root / "instance")
    from app.core import paths
    paths.init(root / "world")
    paths.init_instance(root / "instance")
    install()
    section_state()
    section_plan()
    section_run()
    section_run_planned()
    section_minors()
    section_strays()
    check("network connects", len(CONNECTS), 0)
    print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
