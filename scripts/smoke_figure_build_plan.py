#!/usr/bin/env python3
"""The Build — one action that brings the delivered figure to the wanted one
(plan docs/superpowers/plans/2026-11-12-unified-worn-pieces.md Task 7,
``app/core/figure_build.py``, ``app/routes/figure.py``).

Usage:
    ./.venv/bin/python scripts/smoke_figure_build_plan.py

Runs against a THROWAWAY storage + instance directory — no world, no hub, no
GPU, no Blender, no server. Sections [1]–[6] stub the resolver and every
producer by tables (a small model of the world, ``World`` below: the plain
body, the stored shape, which own-mesh pieces have their mesh, which views
exist, the outfit model's recorded figure); the producers record their calls
and change the world as the real ones would. [0] and [7] use the real code.

Stub constants: ``dressed_views()`` = front + back, so ``dressed_view_jobs()``
= 1 + (2 − 1) = 2 (the front edit + one draft per other view; its composite
onto the base view is CPU, Task 11g — was 1 + 2·(2 − 1) = 3 with the model
fit); ``mesh_hub_stages`` = [mesh, rig] (2); the skin step is
off (``base_skin.enabled`` False). Pieces: Blouse (painted), Coat (in_body),
Tailored Black (``trousers``, own mesh; its chain ``run_estimate`` = 6 hub
jobs until it is meshed).

Expected, by hand from the brief's cost rules (plain body =
``base_rebuild_steps`` of the refresh plan; interim / texture = 2 when their
views are missing, else 0; shape = views 2 when its views are missing + mesh
+ rig; pieces / hair = ``run_estimate``; fits / assemble = 0; a rebuilt plain
body makes every view and the stored shape count as missing):

[0] ``base_refresh_plan(missing=True)``: no stored front → reason
    ``missing``, views front/back/left/right, model True; without
    ``missing`` → reason "" (the improvement's roster is unchanged). Views
    current, no base model → ``missing``, views [], model True.
    ``dressed_view_jobs()`` == 2 (front + back), 4 with the side views on
    (1 + 3 drafts).
[1] Everything built → ``plan == []``, ``cost.hub_jobs == 0``, GET status
    ``up_to_date``.
[2] Base missing + coat in_body + trousers own (no mesh) + blouse painted →
    plain_body (views 4 + mesh + rig = 6), interim (ruling A11, task 11c-2:
    the trousers are in the body meanwhile, so the interim is the shape
    INTERIM of {coat, trousers}, not stored: its views 2 + mesh + rig 2 +
    texture views 2 = 6), shape (2 + 2 = 4), pieces trousers (6), texture
    (2), fits (0), assemble (0) → ``hub_jobs == 24`` (6 + 6 + 4 + 6 + 2), in that order; shape and texture
    carry ``manual`` = ``figure.TAKE_OUT`` (they take the trousers out).
[3] Review Focus 2: hair switched body → HairDeck on a haired base
    (``older_prompts``) with the blouse painted → plain_body (4 + 2 = 6),
    hair (``run_estimate`` HairDeck 1), texture (2: the views follow the
    rebuilt body), fits (0), assemble (0) → 9.
[4] ``run_estimate`` None for the trousers → ``hub_jobs is None``, the note
    names "Tailored Black".
[5] Review Focus 5: ``start`` while the run is in step "shape" → "queued";
    a third call → still "queued" and ONE follow-up kept; after the run the
    follow-up re-plans to [] and ends at once; every producer ran once per
    step (the sequence below; the interim builds its shape INTERIM first,
    ``interim_shape``, and no chain runs before the pieces step — ruling
    A14), a fourth ``start`` answers "current".
[6] ``pieces`` fails for the trousers → texture, fits, assemble still run;
    ``failed == {"pieces": {"error": "mesh refused", "item_id":
    "trousers"}}``. ``shape`` failing skips texture only (pieces, fits,
    assemble run; ``skipped == ["texture"]``).
[7] Routes through the real gate (``auth_gate_middleware`` + a stubbed
    session, as ``smoke_auth_gate``) and a real throwaway world: admin GET
    ``/characters/Kira/figure`` → 200 with every key of the brief; a player
    allowed to see Kira → 403 on the GET and on POST …/figure/build; admin
    POST build for a character off the pipeline (Mara, an animal) → 409 with
    the reason OFF_PIPELINE "No figure — the figure is for humanoid characters
    only".
[8] Fails on the old code: ``app/core/figure_build.py`` does not exist at
    bc07100f and ``base_body.dressed_view_jobs`` is not defined there.
"""
import contextlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

BASELINE = "bc07100f"
FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


BSIG = "base1234abcd"
SHAPE = "ob11111111"
INTERIM = "ob22222222"   # the interim shape of {coat, trousers} (ruling A11: trousers in the body meanwhile)
SIG = "sig000000001"
NAMES = {"blouse": "Silk Blouse", "coat": "Wool Coat", "trousers": "Tailored Black", "hair_kira": "Hair"}


class World:
    """The tables the stubs read and the producers change."""

    def __init__(self, *, base="ok", in_body=(), painted=(), own=(), hair="body", shape_stored=True,
                 meshed=None, hair_done=True, views=None, model=True, estimate=None):
        self.base = base                      # "ok" | "missing" | "older"
        self.in_body, self.painted, self.own = tuple(in_body), tuple(painted), tuple(own)
        self.hair = hair                      # wanted hair: "body" | "hairdeck"
        self.shape_stored = shape_stored      # the wanted shape SHAPE
        self.interim_stored = False           # the interim shape INTERIM
        self.meshed = set(own if meshed is None else meshed)
        self.hair_done = hair_done
        self.estimate = dict(estimate or {})  # item -> hub jobs (None = unknown) while not meshed
        self.fail = {}                        # producer -> error
        self.calls = []
        self.block = None                     # (producer, entered Event, release Event)
        self.views = set()
        self.model_fig = None
        if views is None:
            self.views.add(self.key(self.delivered()))
        if model:
            self.model_fig = self.delivered().as_dict()

    def wanted(self):
        from app.core import figure
        meshed = bool(self.in_body)
        return figure.Figure(signature=SIG, bsig=BSIG, shape=SHAPE if meshed else BSIG,
                             texture=f"tex:{SHAPE if meshed else BSIG}:{','.join(self.painted)}" if self.painted else "",
                             in_body=self.in_body, painted=self.painted, own=self.own,
                             hair="hairdeck" if self.hair == "hairdeck" else "body",
                             pieces={f"s{i}": p for i, p in enumerate((*self.in_body, *self.painted, *self.own))})

    def stored(self, shape):
        """Whether the meshed shape ``shape`` is stored (``figure._shape_stored``)."""
        if self.base != "ok":
            return False
        return self.shape_stored if shape == SHAPE else self.interim_stored if shape == INTERIM else False

    def delivered(self):
        """Ruling A11 (task 11c-2): an own-mesh piece without its mesh is in the body shape meanwhile — the
        interim shape INTERIM, stored or not; without such a piece the wanted shape when stored, else the
        plain body with the in-body set painted (rule 1). A manual Build's view (no kept shape)."""
        from app.core import figure
        w = self.wanted()
        own = tuple(i for i in w.own if i in self.meshed and self.base == "ok")
        pending = tuple(sorted(set(w.own) - set(own)))
        interim = {}
        painted = set(w.painted)
        in_body = w.in_body
        if pending:
            in_body = tuple(sorted({*w.in_body, *pending}))
            shape = INTERIM
            interim.update({i: figure.INTERIM_IN_BODY for i in pending})
        else:
            shape = w.shape if (w.shape == BSIG or self.stored(SHAPE)) else BSIG
            if shape != w.shape:
                in_body = ()
                painted.update(w.in_body)
                interim.update({i: figure.INTERIM_PAINTED.format(what=figure.WHAT_SHAPE) for i in w.in_body})
        hair = w.hair if (w.hair == "body" or self.hair_done) else "body"
        painted_t = tuple(sorted(painted))
        return replace(w, shape=shape, in_body=in_body, painted=painted_t, own=own, interim=interim, hair=hair,
                       in_body_own=pending,
                       texture=("tex:" + shape + ":" + ",".join(painted_t)) if painted_t else "")

    @staticmethod
    def key(fig):
        return (fig.shape, fig.texture, tuple(fig.own))

    def record(self, name, *args):
        self.calls.append(name if not args else f"{name} {' '.join(str(a) for a in args)}")
        if self.block and self.block[0] == name:
            self.block[1].set()
            self.block[2].wait(10)
        if name in self.fail:
            return self.fail[name]
        return None


W = None   # the World of the running section


def install_stubs():
    """Point the modules figure_build reads at the World ``W``."""
    from app.core import (base_body, base_skin, figure, garment_assembly, garment_hair, garment_refit, garments,
                          model3d, task_queue)
    from app.models import inventory

    base_body.is_base_pipeline = lambda c, profile=None: c == "Kira"
    # The World's Kira has no DB row: the Build's strict profile read (fix round T12-F1, ruling F13 e) gets
    # the empty profile the non-strict read gave before — the stubs below never read it.
    from app.core import figure_build
    figure_build._read_profile = lambda c: {}
    figure._delivered = lambda c, *, profile, pieces=None, items=None, **_kw: (W.wanted(), W.delivered())
    base_skin.enabled = lambda: False
    model3d.mesh_hub_stages = lambda c, sig: ["mesh", "rig"]
    base_body.dressed_views = lambda: ("front", "back")

    def refresh_plan(c, *, profile=None, missing=False):
        plan = {"signature": BSIG, "views": [], "model": False, "reason": ""}
        if W.base == "missing":
            return {**plan, "views": list(base_body.BASE_VIEWS), "model": True, "reason": "missing"}
        if W.base == "older":
            return {**plan, "views": list(base_body.BASE_VIEWS), "model": True, "reason": "older_prompts"}
        return plan
    base_body.base_refresh_plan = refresh_plan
    figure._shape_stored = lambda c, shape, bsig: W.stored(shape)
    base_body.shape_view = lambda c, v, shape, bsig: (Path("v") if W.stored(shape) else None)
    base_body.dressed_image = lambda c, v, sig, bsig, fig=None: (
        Path("v") if W.base == "ok" and W.key(fig) in W.views else None)

    def run_estimate(c, item_id, profile=None):
        if item_id == "hair_kira":
            done = W.hair_done
            return {"steps": [] if done else ["hairdeck", "fit"], "hub_jobs": 0 if done else 1, "note": "hairdeck 1"}
        if item_id in W.meshed:
            return {"steps": [], "hub_jobs": 0, "note": "nothing to run"}
        jobs = W.estimate.get(item_id, 6)
        if jobs is None:
            return {"steps": [], "hub_jobs": None, "note": "no item image"}
        return {"steps": ["worn", "ghost", "mesh", "fit"], "hub_jobs": jobs, "note": "worn 3 + ghost 2 + mesh 1"}
    garments.run_estimate = run_estimate
    garments.cached_failure = lambda c, item_id, profile=None: None
    garment_hair.find_hair_item = lambda c, profile=None: {"id": "hair_kira"}
    garment_hair.hair_method = lambda c, profile=None: W.hair
    garment_refit.work_count = lambda c, profile=None: 0
    model3d.find_model3d = lambda c, sig=None, include_stale=False: Path("m.glb") if W.model_fig else None
    model3d._read_sidecar = lambda path: {"figure": W.model_fig} if W.model_fig else {}
    inventory.get_item = lambda iid: {"id": iid, "name": NAMES.get(iid, iid)}

    # --- producers ---
    def base_images(c, view=None, force=False, raise_load=False):
        err = W.record("base_images")
        return {v: None if err else f"tpose_{v}" for v in base_body.BASE_VIEWS}
    base_body.generate_base_images = base_images

    def base_model(c, force=False, raise_load=False):
        err = W.record("base_model")
        if err:
            return {"ok": False, "error": err}
        W.base = "ok"
        return {"ok": True}
    base_body.generate_base_model = base_model

    def dressed(c, *, pieces, items, signature, force=False, view=None, raise_load=False):
        err = W.record("dressed")
        if err:
            raise RuntimeError(err)
        W.views.add(W.key(W.delivered()))
        return {"front": "f", "back": "b"}
    base_body.generate_dressed_images = dressed
    base_body.ensure_figure_views = lambda c, sig: None

    def prepare(c, fig, *, items=None, rebuild=False, signature=""):
        err = W.record("shape" if fig.shape == SHAPE else "interim_shape")
        if err:
            return {"ok": False, "error": err, "body_id": fig.shape}
        if fig.shape == SHAPE:
            W.shape_stored = True
        else:
            W.interim_stored = True
        return {"ok": True, "body_id": fig.shape}
    base_body.prepare_shape = prepare

    def run_queued(c, ids, explicit=False):
        out = {}
        for i in ids:
            err = W.record("chain", i)
            if err:
                out[i] = {"ok": False, "error": err}
            else:
                if i == "hair_kira":
                    W.hair_done = True
                W.meshed.add(i)
                out[i] = {"ok": True}
        return out
    garments.run_queued = run_queued
    garment_hair.ensure_hair_item = lambda c: (W.record("hair_item"), "hair_kira")[1]
    garment_refit.refit_character = lambda c: (W.record("refit"), [])[1]
    garment_refit.tracked = lambda c, run: run()

    def outfit_model(c, *, force=False, signature=None, prepare=True, **kw):
        err = W.record("model", "prepare" if prepare else "no-prepare")
        if err:
            return {"ok": False, "error": err}
        W.model_fig = W.delivered().as_dict()
        return {"ok": True}
    model3d.generate_for_current_outfit = outfit_model
    garment_assembly.schedule = lambda c, sig=None: (W.record("schedule"), True)[1]

    @contextlib.contextmanager
    def slot(c, poll_s=1.0):
        W.calls.append("slot")
        yield
    model3d.generation_slot = slot

    class Tracks:
        def track_start(self, *a, **k):
            return "t1"

        def track_update_label(self, tid, label):
            pass

        def track_finish(self, tid, error=""):
            pass
    task_queue.get_task_queue = lambda: Tracks()


def wait_idle(fb, name="Kira", timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if not fb.state(name)["running"]:
            return True
        time.sleep(0.02)
    return False


def names(steps):
    return [(s.name, s.item_id, s.jobs) if s.item_id else (s.name, s.jobs) for s in steps]


def real_sections(root: Path):
    """[0]: the base_body helpers, real code under stubbed reads."""
    from app.core import base_body, model3d, model_overview
    print("[0] base_refresh_plan(missing=True), dressed_view_jobs, rebuild_cost")
    saved = (base_body.base_prompts_freshness, base_body.base_view_states, model3d.find_model3d,
             base_body.base_model_sha256, base_body.side_views_dressed, base_body.base_signature)
    try:
        base_body.base_signature = lambda c, profile=None: BSIG
        base_body.base_prompts_freshness = lambda c, profile=None: {"state": model_overview.MISSING}
        plan = base_body.base_refresh_plan("Kira", profile={}, missing=True)
        check("[0] no front: reason", plan["reason"], "missing")
        check("[0] no front: views", plan["views"], ["front", "back", "left", "right"])
        check("[0] no front: model", plan["model"], True)
        check("[0] no front without missing=True: reason", base_body.base_refresh_plan("Kira", profile={})["reason"], "")
        base_body.base_prompts_freshness = lambda c, profile=None: {"state": model_overview.CURRENT}
        base_body.base_view_states = lambda c, profile=None: {v: {"state": model_overview.CURRENT}
                                                              for v in base_body.BASE_VIEWS}
        model3d.find_model3d = lambda c, sig=None, include_stale=False: None
        base_body.base_model_sha256 = lambda c, bsig: ""
        plan = base_body.base_refresh_plan("Kira", profile={}, missing=True)
        check("[0] no model: (reason, views, model)", (plan["reason"], plan["views"], plan["model"]),
              ("missing", [], True))
        check("[0] no model without missing=True: reason", base_body.base_refresh_plan("Kira", profile={})["reason"],
              "")
        base_body.side_views_dressed = lambda: False
        check("[0] dressed_view_jobs front+back", base_body.dressed_view_jobs(), 2)
        base_body.side_views_dressed = lambda: True
        check("[0] dressed_view_jobs with the sides", base_body.dressed_view_jobs(), 4)
    finally:
        (base_body.base_prompts_freshness, base_body.base_view_states, model3d.find_model3d,
         base_body.base_model_sha256, base_body.side_views_dressed, base_body.base_signature) = saved


def stub_sections():
    global W
    from app.core import figure
    from app.core import figure_build as fb
    install_stubs()

    print("[1] everything built")
    W = World(in_body=("coat",), painted=("blouse",), own=("trousers",))
    check("[1] plan", fb.plan("Kira", profile={}), [])
    check("[1] cost hub_jobs", fb.cost("Kira")["hub_jobs"], 0)
    check("[1] status", fb.figure_info("Kira")["status"], "up_to_date")

    print("[2] base missing + coat in_body + trousers own (no mesh)")
    W = World(base="missing", in_body=("coat",), painted=("blouse",), own=("trousers",), shape_stored=False,
              meshed=(), model=False)
    steps = fb.plan("Kira", profile={})
    check("[2] steps", names(steps), [("plain_body", 6), ("interim", 6), ("shape", 4), ("pieces", "trousers", 6),
                                      ("texture", 2), ("fits", 0), ("assemble", 0)])
    check("[2] plain body label", steps[0].label, "Plain body: views 4 + mesh + rig")
    check("[2] interim label (ruling A11: the trousers in the body meanwhile)", steps[1].label,
          "Interim body shape (own mesh in the body until ready): views 2 + mesh + rig + texture views 2")
    check("[2] piece label", steps[3].label, "Own mesh · Tailored Black")
    check("[2] shape / texture take the trousers out: manual", [s.manual for s in steps if s.name in
                                                                ("shape", "texture")], [figure.TAKE_OUT] * 2)
    check("[2] hub_jobs", fb.cost("Kira", steps)["hub_jobs"], 24)
    check("[2] step order follows STEP_ORDER",
          [s.name for s in steps] == sorted((s.name for s in steps), key=fb.STEP_ORDER.index), True)

    print("[3] hair body -> HairDeck on a haired base (older prompts)")
    W = World(base="older", painted=("blouse",), hair="hairdeck", hair_done=False)
    steps = fb.plan("Kira", profile={})
    check("[3] steps", names(steps), [("plain_body", 6), ("hair", "hair_kira", 1), ("texture", 2), ("fits", 0),
                                      ("assemble", 0)])
    check("[3] hub_jobs", fb.cost("Kira", steps)["hub_jobs"], 9)

    print("[4] run_estimate unknown for one piece")
    W = World(base="missing", in_body=("coat",), painted=("blouse",), own=("trousers",), shape_stored=False,
              meshed=(), model=False, estimate={"trousers": None})
    c = fb.cost("Kira")
    check("[4] hub_jobs", c["hub_jobs"], None)
    check("[4] note names the piece", "Tailored Black" in c["note"], True)

    print("[5] start twice / three times while the run is in step shape")
    W = World(base="missing", in_body=("coat",), painted=("blouse",), own=("trousers",), shape_stored=False,
              meshed=(), model=False)
    entered, release = threading.Event(), threading.Event()
    W.block = ("shape", entered, release)
    check("[5] first start", fb.start("Kira", reason="manual")["status"], "started")
    check("[5] the run reached the shape step", entered.wait(5), True)
    check("[5] state step", (fb.state("Kira")["step"] or {}).get("name"), "shape")
    check("[5] second start", fb.start("Kira", reason="manual")["status"], "queued")
    check("[5] third start", fb.start("Kira", reason="outfit_change")["status"], "queued")
    check("[5] one follow-up kept", fb.state("Kira")["queued"], 1)
    release.set()
    check("[5] the runs ended", wait_idle(fb), True)
    check("[5] producer calls (once per step; the follow-up re-planned to [] and ran nothing)", W.calls, [
        "slot", "base_images", "base_model",
        "slot", "interim_shape", "dressed", "model no-prepare",
        "slot", "shape",
        "chain trousers",
        "slot", "dressed",
        "refit",
        "slot", "model no-prepare", "schedule"])
    check("[5] plan now", fb.plan("Kira", profile={}), [])
    check("[5] failed", fb.state("Kira")["failed"], {})
    check("[5] fourth start", fb.start("Kira", reason="manual")["status"], "current")

    print("[6] a failed piece / a failed shape")
    W = World(in_body=("coat",), painted=("blouse",), own=("trousers",), shape_stored=False, meshed=(),
              model=False)
    W.fail["chain"] = "mesh refused"
    fb.start("Kira", reason="manual")
    check("[6] pieces run ended", wait_idle(fb), True)
    ran = [c for c in W.calls if c != "slot"]
    check("[6] pieces: texture, fits, assemble still ran", ran, [
        "interim_shape", "dressed", "model no-prepare", "shape", "chain trousers", "dressed", "refit",
        "model no-prepare", "schedule"])
    check("[6] pieces: failed", fb.state("Kira")["failed"],
          {"pieces": {"error": "mesh refused", "item_id": "trousers"}})
    check("[6] pieces: GET status failed", fb.figure_info("Kira")["status"], "failed")
    row = [r for r in fb.figure_info("Kira")["worn"] if r["item_id"] == "trousers"][0]
    check("[6] pieces: worn row", (row["state"], row["failure"], row["interim"]), ("failed", "mesh refused", True))

    W = World(in_body=("coat",), painted=("blouse",), own=("trousers",), shape_stored=False, meshed=(),
              model=False)
    W.fail["shape"] = "mesh backend refused"
    fb.start("Kira", reason="manual")
    check("[6] shape run ended", wait_idle(fb), True)
    ran = [c for c in W.calls if c != "slot"]
    check("[6] shape: only texture skipped", ran, [
        "interim_shape", "dressed", "model no-prepare", "shape", "chain trousers", "refit", "model no-prepare",
        "schedule"])
    st = fb.state("Kira")
    check("[6] shape: failed", st["failed"], {"shape": {"error": "mesh backend refused", "item_id": ""}})
    check("[6] shape: skipped", st["skipped"], ["texture"])
    check("[6] DEPENDS", fb.DEPENDS, {"interim": {"plain_body"}, "shape": {"plain_body"},
                                      "pieces": {"plain_body"}, "hair": {"plain_body"},
                                      "texture": {"plain_body", "shape"}, "fits": {"plain_body"},
                                      "assemble": {"plain_body"}})


KEYS = {"pipeline", "humanoid", "auto_build", "status", "changes", "cost", "build", "wanted", "delivered",
        "served_url", "worn", "hair", "body"}


def route_section(root: Path):
    """[7]: real resolver, real gate, a throwaway world (runs in a fresh process: the stubs above patched
    module attributes for good)."""
    print("[7] routes")
    import hashlib
    from fastapi import FastAPI, Request
    from fastapi.testclient import TestClient
    from app.core import auth_dependency, base_body, figure_build as fb, glb_delivery, model_refs
    from app.models import inventory
    from app.models.character import get_character_dir, save_character_profile
    from app.routes import figure as figure_route

    model_refs.schedule_outfit_render = lambda *a, **k: None
    glb_delivery.delivery_path = lambda path, **kw: path
    human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168}
    check("[7] create Kira", save_character_profile("Kira", dict(human), create_new=True), True)
    # Mara is an animal: since Task 11h (Ruling A13) only a non-humanoid is off the pipeline.
    check("[7] create Mara", save_character_profile("Mara", {"template": "animal-default"}, create_new=True), True)
    bsig = base_body.base_signature("Kira")
    cdir = get_character_dir("Kira")
    mdir, refs = cdir / "model3d", cdir / "model_refs"
    mdir.mkdir(parents=True, exist_ok=True)
    refs.mkdir(parents=True, exist_ok=True)
    (mdir / f"{bsig}.glb").write_bytes(b"glb-Kira")
    (mdir / f"{bsig}.json").write_text(json.dumps({"base": True, "rig": "mixamo", "signature": bsig,
                                                   "format": "glb", "source": "generated"}))
    for v in base_body.BASE_VIEWS:
        stem = f"tpose_{bsig}" if v == "front" else f"tpose_{v}_{bsig}"
        (refs / f"{stem}.png").write_bytes(hashlib.sha256(v.encode()).digest())
        (refs / f"{stem}.json").write_text(json.dumps({"base_signature": bsig}))
    iid = inventory.add_item(name="Silk Blouse", category="outfit_piece", prompt_fragment="a silk blouse",
                             outfit_piece={"slots": ["top"], "covers": [], "outfit_types": ["casual"],
                                           "mesh_mode": "painted"})["id"]
    inventory.add_to_inventory("Kira", iid)
    check("[7] Kira wears the blouse", inventory.equip_piece("Kira", iid, source="smoke")["status"], "ok")

    users = {"user": {"id": "u_user", "username": "demo", "role": "user", "allowed_characters": ["Kira", "Mara"]},
             "admin": {"id": "u_admin", "username": "demo", "role": "admin", "allowed_characters": []}}

    def session_user(request: Request):
        return users.get(request.headers.get("x-test-user", ""))
    auth_dependency._get_session_user = session_user
    app = FastAPI()
    app.middleware("http")(auth_dependency.auth_gate_middleware)
    app.middleware("http")(auth_dependency.user_context_middleware)
    app.include_router(figure_route.router)
    client = TestClient(app)

    r = client.get("/characters/Kira/figure", headers={"x-test-user": "admin"})
    check("[7] admin GET status code", r.status_code, 200)
    print("    payload:", json.dumps({k: (r.json() or {}).get(k) for k in ("status", "cost", "changes", "body", "hair")})[:1500])
    body = r.json() if r.status_code == 200 else {}
    check("[7] admin GET keys", sorted(KEYS - set(body)), [])
    check("[7] admin GET pipeline", body.get("pipeline"), True)
    check("[7] admin GET status is one of four",
          body.get("status") in ("up_to_date", "changes", "building", "failed"), True)
    check("[7] admin GET worn rows name the blouse", [w.get("item_id") for w in body.get("worn") or []], [iid])
    check("[7] admin GET cost has hub_jobs", "hub_jobs" in (body.get("cost") or {}), True)
    check("[7] admin GET build state keys", sorted(body.get("build") or {}),
          sorted(["running", "step", "queued", "failed", "skipped", "reason", "finished_at"]))
    check("[7] player GET", client.get("/characters/Kira/figure", headers={"x-test-user": "user"}).status_code, 403)
    check("[7] player POST build",
          client.post("/characters/Kira/figure/build", headers={"x-test-user": "user"}).status_code, 403)
    r = client.post("/characters/Mara/figure/build", headers={"x-test-user": "admin"})
    check("[7] admin POST build off the pipeline", r.status_code, 409)
    check("[7] 409 names the reason", str(r.json().get("detail") or ""), fb.OFF_PIPELINE)
    check("[7] admin GET unknown character",
          client.get("/characters/Nobody/figure", headers={"x-test-user": "admin"}).status_code, 404)


def baseline_section():
    print(f"[8] fails on {BASELINE}")
    shown = subprocess.run(["git", "-C", str(ROOT), "cat-file", "-e", f"{BASELINE}:app/core/figure_build.py"],
                           capture_output=True)
    check(f"[8] figure_build.py absent at {BASELINE}", shown.returncode != 0, True)
    body = subprocess.run(["git", "-C", str(ROOT), "show", f"{BASELINE}:app/core/base_body.py"],
                          capture_output=True, text=True).stdout
    check(f"[8] base_body.py at {BASELINE} readable", "def base_refresh_plan" in body, True)
    check(f"[8] no dressed_view_jobs at {BASELINE}", "def dressed_view_jobs" in body, False)


def setup(root: Path):
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


def main() -> int:
    part = sys.argv[1] if len(sys.argv) > 1 else ""
    if not part:
        # The stubbed sections patch module attributes for good: the real-route section runs in its own process.
        codes = [subprocess.run([sys.executable, __file__, p]).returncode for p in ("stubs", "routes")]
        baseline_section()
        if any(codes) or FAILS:
            print(f"\nFAIL: {', '.join(FAILS) or 'see above'}")
            return 1
        print("\nPASS")
        return 0
    with tempfile.TemporaryDirectory(prefix=f"figure-build-{part}-") as tmp:
        root = Path(tmp)
        setup(root)
        if part == "stubs":
            real_sections(root)
            stub_sections()
        else:
            route_section(root)
    if FAILS:
        print(f"FAIL ({part}): {', '.join(FAILS)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
