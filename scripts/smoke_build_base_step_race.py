#!/usr/bin/env python3
"""Ruling A26 of the unified worn pieces (ledger
``.superpowers/sdd/2026-11-12-unified-worn-pieces/progress.md``): a Build never
runs beside a base-body step.

Why (live, 2026-11-13 20:28-20:30): the user started Kai's base SKIN step (a
hub image job, it reserves the base front), clicked Build 79 s later; the skin
step rewrote ``tpose_base….png`` 60 s into the Build, the Build's dressed front
landed 30 s after that with the OLD base front's sha in its sidecar →
``current("front")`` None → the back draft skipped → the Build failed "Front and
back views missing — not meshed from the nothing alone (Render the dressed front
first …)" although the front had just been rendered; one paid hub job wasted.
A20 refused base steps DURING a Build, nothing refused a Build during a base step.

Usage:
    ./.venv/bin/python scripts/smoke_build_base_step_race.py

Throwaway storage + EMPTY instance (never the real ``instance/``), a copy of the
``human`` package, one character "Demo". Network blocked: every socket connect /
DNS lookup / ``requests`` send raises and is COUNTED — the count must be 0. The
hub jobs of a Build step are a stub backend whose calls are counted.

Expected, derived by hand from Ruling A26:

[1] (a) A Build with a base step in flight. The real ``base_skin.start_skin_step``
    (its edit held on an Event = the hub job in flight) reserves the front from
    its click on:
    - ``base_step_in_flight`` = "Base body skin step";
    - manual ``start`` → ``{"status": "base_busy", "reason": "Base body skin step
      is running — Build once it is done"}``; nothing started, no worker;
    - the route ``POST …/figure/build`` → 409 with that text; ``…/model3d/build-current``
      (``model3d_pipeline.build_current_outfit``) → LookupError with it (the
      route's 409); "Re-fit" → ``base_busy`` with it;
    - automatic (``request(…, "outfit_change")``) → True (kept), ``state()``
      ``deferred`` "outfit_change", no worker; a second request keeps ONE waiter;
    - the skin step ends → the waiter starts the automatic Build ONCE (the run
      stub records ``("outfit_change", automatic=True)``), ``deferred`` None.
    - the other registries name their step: a base view render "Base body back
      view render", the base model "Base body model (mesh + rig)", a labelled
      generation guard "Face retexture", Run all "Base body Run all"; an
      UNLABELLED guard (a Build's own ``generation_slot``) is no base step ("").
[2] (b) A base front replaced mid-Build (real ``_run_planned``; plan [shape,
    pieces, assemble], 5 + 4 + 0 stub jobs; base views = real files):
    - unchanged: all three steps run, 9 stub calls, failed {};
    - the shape step's stub job runs, then the skin step lands (front rewritten)
      and the step fails with the old "views missing" text → failed
      {"shape": "Base body changed during the Build (shape) — Build again"},
      skipped [pieces, assemble], 5 stub calls in all — 0 after the stop;
    - the same with the shape step succeeding → the same stop and message;
    - the front rewritten before the first step (right after the snapshot) →
      stopped at "shape" before it ran: 0 stub calls;
    - the Build's OWN plain body step rewriting the front is no change (plan
      [plain_body, shape]: both run, failed {});
    - a run that finds a base step in flight at its start (a follow-up): manual →
      failed {"build": BASE_STEP_RUNNING text}, no step ran.
[3] (c) The stale-front texts:
    - ``views_missing_message(["front", "back"], [], stale=["front"])`` =
      "Dressed front is stale — the base front changed; back view missing";
    - without stale: "Front and back views missing — nothing to mesh from";
      ``(["back"], ["front"])`` stays "Back view missing — not meshed from the front alone";
    - ``stale_views``: a dressed front (``tpose_obshape01``) whose sidecar records
      the old base front's sha → ["front"]; recorded = current → [];
    - ``figure_build._dressed`` on a stale stored front, the back missing, the
      recorded failure ``DRESSED_FRONT_STALE`` → "Dressed front is stale — the base
      front changed; Views missing: back — nothing is painted or assembled without
      them" (the redundant reason dropped).
"""
import contextlib
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
from collections import deque
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

# --- Network block (before anything else is imported) -----------------------------------------------------------

OUTBOUND = []
_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex


def _blocked(what):
    OUTBOUND.append(what)
    raise OSError(f"smoke: outbound request blocked ({what})")


def _connect(self, address):
    if self.family == getattr(socket, "AF_UNIX", None):
        return _real_connect(self, address)
    _blocked(f"connect {address!r}")


def _connect_ex(self, address):
    if self.family == getattr(socket, "AF_UNIX", None):
        return _real_connect_ex(self, address)
    _blocked(f"connect_ex {address!r}")


socket.socket.connect = _connect
socket.socket.connect_ex = _connect_ex
socket.getaddrinfo = lambda host, *a, **k: _blocked(f"getaddrinfo {host!r}")
socket.create_connection = lambda address, *a, **k: _blocked(f"create_connection {address!r}")
try:
    import requests

    requests.Session.send = lambda self, request, **kw: _blocked(f"requests {request.method} {request.url}")
except ImportError:  # pragma: no cover
    pass

FAILS = []
BSIG = "base0001aaaa"
NAME = "Demo"


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:400] + ("" if ok else f" — expected {want!r}"[:400]))
    if not ok:
        FAILS.append(label)


def wait_until(fn, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if fn():
            return True
        time.sleep(0.02)
    return False


class StubHub:
    """The hub jobs of a Build step: counted, never sent anywhere."""

    def __init__(self):
        self.calls = []
        self.lock = threading.Lock()

    def job(self, what):
        with self.lock:
            self.calls.append(what)


def refs_dir():
    from app.models.character import get_character_dir
    d = get_character_dir(NAME) / "model_refs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_png(path: Path, colour) -> None:
    """Written as the producers write (a new file moved over the old one — ``_write_atomic``)."""
    from PIL import Image
    staged = path.with_name(path.stem + ".tmp.png")
    Image.new("RGB", (8, 8), colour).save(staged)
    os.replace(staged, path)


def write_base(front_colour=(200, 160, 140)) -> None:
    d = refs_dir()
    write_png(d / f"tpose_{BSIG}.png", front_colour)
    write_png(d / f"tpose_back_{BSIG}.png", (190, 150, 130))


# --- [1] a Build with a base step in flight ----------------------------------------------------------------------

def section_refuse() -> None:
    from fastapi import HTTPException
    from app.core import base_body, base_skin, figure_build, model3d, model3d_pipeline
    from app.core.figure_build import Step
    from app.routes import figure as figure_routes
    print("[1] a Build with a base step in flight")

    runs = []
    hold = threading.Event()
    steps = [Step("shape", "Body shape", 5)]
    with contextlib.ExitStack() as stack:
        stack.enter_context(patch.object(figure_build, "_read_profile", lambda c: {}))
        stack.enter_context(patch.object(figure_build, "on_pipeline", lambda c, profile=None: True))
        stack.enter_context(patch.object(figure_build, "auto_build_on", lambda c, profile=None: True))
        stack.enter_context(patch.object(figure_build, "plan", lambda *a, **k: list(steps)))
        stack.enter_context(patch.object(figure_build, "_run",
                                         lambda c, reason, automatic=False: runs.append((reason, automatic))))
        stack.enter_context(patch.object(figure_build, "DEFERRED_POLL_S", 0.02))
        stack.enter_context(patch.object(base_skin, "apply_skin_step", lambda c: hold.wait(10)))

        check("nothing in flight", figure_build.base_step_in_flight(NAME), "")
        base_skin.start_skin_step(NAME)   # the click: the front is reserved from now on
        want = "Base body skin step is running — Build once it is done"
        check("named", figure_build.base_step_in_flight(NAME), "Base body skin step")
        check("manual start refused", figure_build.start(NAME, reason="manual"),
              {"status": "base_busy", "reason": want})
        check("no worker", figure_build.running(NAME), False)
        try:
            figure_routes.build_figure(NAME, {})
            got = (200, None)
        except HTTPException as e:
            got = (e.status_code, e.detail)
        check("route figure/build: 409 with the step", got, (409, want))
        try:
            model3d_pipeline.build_current_outfit(NAME)
            got = None
        except LookupError as e:
            got = str(e)
        check("build-current: LookupError (409) with the step", got, want)
        check("Re-fit refused", figure_build.refit(NAME, "item_x"), {"status": "base_busy", "reason": want})

        check("automatic: kept (deferred)", figure_build.request(NAME, "outfit_change"), True)
        check("automatic: kept again, one waiter", figure_build.request(NAME, "outfit_change"), True)
        waiters = [t for t in threading.enumerate() if t.name == f"figure-build-deferred-{NAME}"]
        check("one waiter thread", len(waiters), 1)
        check("state: deferred", figure_build.state(NAME)["deferred"], "outfit_change")
        check("state: not running", figure_build.state(NAME)["running"], False)
        check("nothing ran yet", runs, [])

        hold.set()   # the skin step's hub job ends
        check("the deferred Build starts once the step is done",
              wait_until(lambda: runs == [("outfit_change", True)]), True)
        wait_until(lambda: not figure_build.running(NAME))
        time.sleep(0.1)
        check("exactly once", runs, [("outfit_change", True)])
        check("state: deferred cleared", figure_build.state(NAME)["deferred"], None)
        check("nothing in flight after", figure_build.base_step_in_flight(NAME), "")

    print("[1b] every base registry names its step")
    base_body.reserve_views(NAME, ["back"])
    try:
        check("a base view render", figure_build.base_step_in_flight(NAME), "Base body back view render")
    finally:
        base_body.release_views(NAME, ["back"])
    with base_body._status_lock:
        base_body._model_running[NAME] = BSIG
    try:
        check("the base model", figure_build.base_step_in_flight(NAME), "Base body model (mesh + rig)")
    finally:
        with base_body._status_lock:
            base_body._model_running.pop(NAME, None)
    with model3d._lock:
        model3d._generating.add(NAME, "Face retexture")
    try:
        check("a labelled generation guard", figure_build.base_step_in_flight(NAME), "Face retexture")
    finally:
        with model3d._lock:
            model3d._generating.discard(NAME)
    check("guard released: label gone", model3d._generating.what.get(NAME), None)
    with model3d.generation_slot(NAME):
        check("an unlabelled guard (a Build's slot) is no base step", figure_build.base_step_in_flight(NAME), "")
    with figure_build._lock:
        figure_build._run_all_active.add(NAME)
    try:
        check("Run all", figure_build.base_step_in_flight(NAME), "Base body Run all")
    finally:
        with figure_build._lock:
            figure_build._run_all_active.discard(NAME)


# --- [2] a base front replaced mid-Build -------------------------------------------------------------------------

class _Fig:
    shape = "obshape01"
    signature = "sigK"
    bsig = BSIG
    texture = ""
    hair = "body"
    in_body = ()
    own = ()
    pieces = {}

    def as_dict(self):
        return {"signature": self.signature, "shape": self.shape}


def section_mid_build() -> None:
    from app.core import base_body, figure, figure_build
    from app.core.figure_build import Step
    print("[2] a base front replaced mid-Build")
    hub = StubHub()
    plan_now = {"steps": []}
    behaviour = {}

    def shape_runner(c, step, explicit=False):
        for i in range(5):
            hub.job(f"shape {i}")
        if behaviour.get("skin_lands_in_shape"):
            write_base((10, 20, 30))   # the skin step's edit lands on the base front
        return behaviour.get("shape_error", "")

    def pieces_runner(c, step, explicit=False):
        for i in range(4):
            hub.job(f"pieces {i}")
        return ""

    def assemble_runner(c, step, explicit=False):
        return ""

    def plain_runner(c, step, explicit=False):
        write_base((40, 50, 60))   # the Build's own plain body: new base views (and its own skin step)
        return ""

    def run(steps, *, automatic=False, tracked=None):
        write_base()
        hub.calls.clear()
        plan_now["steps"] = steps
        with figure_build._lock:
            figure_build._queues[NAME] = deque()
            figure_build._active.add(NAME)
        try:
            with patch.object(figure_build, "_tracked", tracked or (lambda c, label: (None, ""))):
                figure_build._run_planned(NAME, "manual", {}, automatic=automatic)
        finally:
            with figure_build._lock:
                figure_build._queues.pop(NAME, None)
                figure_build._active.discard(NAME)
        st = figure_build.state(NAME)
        return {k: v["error"] for k, v in st["failed"].items()}, st["skipped"], len(hub.calls)

    runners = {"shape": shape_runner, "pieces": pieces_runner, "assemble": assemble_runner,
               "plain_body": plain_runner}
    three = [Step("shape", "Body shape", 5), Step("pieces", "Own mesh · Jacket", 4, item_id="x"),
             Step("assemble", "Assemble", 0)]
    changed = "Base body changed during the Build (shape) — Build again"
    with contextlib.ExitStack() as stack:
        stack.enter_context(patch.object(figure, "_delivered", lambda c, profile=None, **k: (_Fig(), _Fig())))
        stack.enter_context(patch.object(figure_build, "plan", lambda *a, **k: list(plan_now["steps"])))
        stack.enter_context(patch.object(figure_build, "_check_pin", lambda c: None))
        stack.enter_context(patch.object(figure_build, "_wait_base_views", lambda c, **k: []))
        stack.enter_context(patch.object(figure_build, "_now", lambda c: ({}, _Fig(), _Fig(), [])))
        stack.enter_context(patch.object(base_body, "base_signature", lambda c, profile=None: BSIG))
        stack.enter_context(patch.dict(figure_build._RUNNERS, runners))

        behaviour.clear()
        check("unchanged base: every step runs", run(three), ({}, [], 9))

        behaviour.update(skin_lands_in_shape=True, shape_error=base_body.views_missing_message(
            ["front", "back"], [], base_body.DRESSED_FRONT_FIRST))
        check("skin step lands in the shape step (it fails): stopped, the true reason, 0 calls after",
              run(three), ({"shape": changed}, ["pieces", "assemble"], 5))

        behaviour.update(skin_lands_in_shape=True, shape_error="")
        check("skin step lands in the shape step (it succeeds): stopped the same",
              run(three), ({"shape": changed}, ["pieces", "assemble"], 5))

        behaviour.clear()

        def land_after_snapshot(c, label):
            write_base((10, 20, 30))   # between the run's snapshot and its first step
            return None, ""

        check("changed before the first step: stopped before it ran, 0 calls",
              run(three, tracked=land_after_snapshot), ({"shape": changed}, ["pieces", "assemble"], 0))

        check("the Build's own plain body is no change",
              run([Step("plain_body", "Plain body", 6), Step("shape", "Body shape", 5)]), ({}, [], 5))

        base_body.reserve_views(NAME, ["front"], step=base_body.SKIN_STEP)
        try:
            check("a run that finds a base step in flight at its start (manual): not run",
                  run(three), ({"build": "Base body skin step is running — Build once it is done"},
                               ["shape", "pieces", "assemble"], 0))
        finally:
            base_body.release_views(NAME, ["front"])


# --- [3] the stale-front texts -----------------------------------------------------------------------------------

def section_texts() -> None:
    from app.core import base_body, figure_build
    print("[3] stale, not missing")
    check("stale front + missing back", base_body.views_missing_message(["front", "back"], [], stale=["front"]),
          "Dressed front is stale — the base front changed; back view missing")
    check("nothing there", base_body.views_missing_message(["front", "back"], []),
          "Front and back views missing — nothing to mesh from")
    check("unchanged rule", base_body.views_missing_message(["back"], ["front"]),
          "Back view missing — not meshed from the front alone")
    check("two stale", base_body.views_missing_message(["front", "back"], [], stale=["front", "back"]),
          "Dressed front and back are stale — the base front and back changed")

    write_base()
    d = refs_dir()
    base_front = d / f"tpose_{BSIG}.png"
    old_sha = base_body.file_sha256(base_front)
    dressed = d / "tpose_obshape01.png"
    write_png(dressed, (1, 2, 3))
    dressed.with_suffix(".json").write_text(json.dumps({"base_signature": BSIG, "base_image_sha256": old_sha,
                                                        "dressed": True}))
    check("recorded = current: not stale", base_body.stale_views(NAME, "obshape01", ["front", "back"]), [])
    write_base((10, 20, 30))   # the skin step rewrote the base front
    check("the base front changed: stale", base_body.stale_views(NAME, "obshape01", ["front", "back"]), ["front"])

    # The Build's dressed-views step on that state (outfit signature "obshape01" here: one stored front).
    with patch.object(figure_build, "_now", lambda c: ({}, _Fig(), _Fig(), [])), \
            patch.object(base_body, "generate_dressed_images", lambda *a, **k: {}), \
            patch.object(base_body, "dressed_views", lambda: ("front", "back")), \
            patch.object(base_body, "dressed_image", lambda *a, **k: None), \
            patch.object(base_body, "outfit_failure", lambda c, s: base_body.DRESSED_FRONT_STALE):
        fig = _Fig()
        fig.signature = "obshape01"
        check("_dressed names the stale front", figure_build._dressed(NAME, fig),
              "Dressed front is stale — the base front changed; Views missing: back — nothing is painted or "
              "assembled without them")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="build-base-race-") as tmp:
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
        from app.models.character import save_character_profile
        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                 "character_appearance": "slender"}
        check("create Demo", save_character_profile(NAME, human, create_new=True), True)

        section_refuse()
        section_mid_build()
        section_texts()

    check("outbound requests", OUTBOUND, [])
    print(f"\n{len(FAILS)} failure(s)")
    for label in FAILS:
        print("  -", label)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
