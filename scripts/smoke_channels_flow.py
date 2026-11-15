#!/usr/bin/env python3
"""Where a saved channel setting becomes due and what applies it (cross-person collision, plan Task 15;
docs/superpowers/plans/2026-11-14-cross-person-collision.md; ruling R4 "the Channels panel's Save stores only").

Usage:
    ./.venv/bin/python scripts/smoke_channels_flow.py

Runs against a THROWAWAY storage directory (``paths.init(<tmp>)`` before any world module is imported) — no world,
no hub, no server, no thread that renders. The stores the judgement reads (``collision.channels_due``, the base
refresh plan, the declarations) are stubs; what is checked is the wiring in ``figure_build`` (Run all, the Build
step), ``model_overview.outfit_model_steps`` and ``collision_channels.declarations_info``.

Expected, by hand from the brief, the spec (Part 6) and the code they name:

[1] Base Run all, everything else current, ``collision.channels_due`` True → kind "collision", steps
    [("collision", 0)], hub_jobs 0 (CPU only), the note names "channel settings changed". ``channels_due`` False →
    kind "", hub_jobs 0 ("Everything is current"). ``channels_due`` raising → the same "" (a plan never fails on it).
    A plain body outdated at the same time → kind "plain_body" (an earlier kind wins: its rig refits the set, which
    resolves the channels).
[2] ``start_base_run_all`` of kind collision → {status started, kind collision}; while the step is held the
    character's ``build_lock`` is held and ``base_run_all(..)['running']`` is True; ``_run_step`` got the step
    "collision" with explicit True; after the release: lock free, running False, ``last.error`` "". The lock held by
    someone else → "building"; a 3D run going (``generation_running``) → "busy" and the lock free again.
[3] ``_run_collision`` (the Build's runner): not due → "" and ``recompute_character`` NOT called; due →
    ``recompute_character(c, apply_channels=True)`` once, ""; a model failing ("sig1": "unreadable") → the error
    "Collision capsules not recomputed — sig1: unreadable". ``STEP_ORDER`` ends with "collision", the step is in
    ``SLOT_STEPS`` and ``UNPINNED_STEPS``, has no ``DEPENDS`` entry and is not a ``STOP_STEPS`` member;
    ``STEP_LABELS["collision"]`` == ``COLLISION_LABEL``.
[4] ``outfit_model_steps`` of an outfit model with a capsule record (30 capsules, one channel): the collision row is
    "due" with the detail starting "Channel settings changed — recompute to apply" when ``collision_current`` True
    and ``channels_current`` False; "done" when both True; "warning" (outdated, NOT due) when ``collision_current``
    False — before Task 15 the outfit row never read the channels.
[5] ``declarations_info(c, None, {})`` with one declared region ("demo:channel", joint Hips): one entry, placement
    None, reason "No base model yet" (``NO_MODEL``); with a model path and a record that places it ("declared") →
    placement "declared", reason ""; a record without it → reason "Not computed".
"""
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_tmp = Path(tempfile.mkdtemp(prefix="smoke_channels_flow_"))
from app.core import paths  # noqa: E402
paths.init(str(_tmp))

from app.core import base_body, base_skin, collision, collision_channels, extension_rig, figure_build, model3d  # noqa: E402
from app.core import model_overview  # noqa: E402

FAILS = []


def check(label, got, want=True):
    ok = got == want
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + ("" if ok else f"  — got {got!r}, want {want!r}"))
    if not ok:
        FAILS.append(label)


class Patch:
    """Set attributes for the block, restore them after."""
    def __init__(self, *triples):
        self.triples, self.saved = triples, []

    def __enter__(self):
        for obj, name, value in self.triples:
            self.saved.append((obj, name, getattr(obj, name)))
            setattr(obj, name, value)
        return self

    def __exit__(self, *exc):
        for obj, name, value in reversed(self.saved):
            setattr(obj, name, value)


C, BSIG = "Mia", "b0123456789a"
PROFILE = {"name": C}
REFRESH = {"signature": BSIG, "views": [], "model": False, "reason": ""}
STATE = {"due": True}


def boom(*a, **k):
    raise RuntimeError("boom")


def world(*, refresh=None, due=None):
    """Everything else current; ``collision.channels_due`` from ``STATE`` (or the callable ``due``)."""
    return Patch(
        (figure_build, "on_pipeline", lambda c, profile=None: True),
        (base_body, "base_refresh_plan", lambda c, profile=None, missing=False: dict(refresh or REFRESH)),
        (base_skin, "enabled", lambda: False),
        (model3d, "mesh_hub_stages", lambda c, s: ["mesh", "rig"]),
        (model3d, "face_cleanup_state", lambda c, s: {"can_reapply": False}),
        (model3d, "mesh_repair_state", lambda c, s: None),
        (model3d, "extension_settings_changed", lambda c, s: ""),
        (figure_build, "_face_retexture_pending", lambda c, s: ""),
        (collision, "channels_due", due or (lambda c: STATE["due"])),
    )


def brief(p):
    return [p["kind"], [(s["name"], s["jobs"]) for s in p["steps"]], p["hub_jobs"]]


def plan():
    return figure_build.base_run_all(C, profile=PROFILE)


# [1]
with world():
    p = plan()
    check("[1] channels due → kind collision", brief(p), ["collision", [("collision", 0)], 0])
    check("[1] the note says why", "channel settings changed" in (p.get("note") or ""))
    STATE["due"] = False
    check("[1] nothing due → everything current", brief(plan()), ["", [], 0])
    STATE["due"] = True
with world(due=boom):
    check("[1] unreadable channels state → current", brief(plan()), ["", [], 0])
with world(refresh={"signature": BSIG, "views": ["back"], "model": True, "reason": "views"}):
    check("[1] an earlier kind wins", plan()["kind"], "plain_body")

# [2]
calls = []
hold, ran = threading.Event(), threading.Event()


def run_step(c, step, explicit):
    calls.append((c, step.name, explicit))
    ran.set()
    hold.wait(5)
    return ""


common = ((figure_build, "_read_profile", lambda c: PROFILE),
          (figure_build, "_run_step", run_step),
          (base_body, "base_signature", lambda c, profile=None: BSIG),
          (model3d, "generation_running", lambda c: False))
with world(), Patch(*common):
    check("[2] start", figure_build.start_base_run_all(C), {"status": "started", "kind": "collision"})
    check("[2] the step runs", ran.wait(5))
    check("[2] build_lock held meanwhile", figure_build.build_lock(C).locked())
    check("[2] running", plan()["running"])
    hold.set()
    for _ in range(200):
        if not plan()["running"]:
            break
        threading.Event().wait(0.01)
    check("[2] step call", calls, [(C, "collision", True)])
    check("[2] lock free after", figure_build.build_lock(C).locked(), False)
    check("[2] running after", plan()["running"], False)
    check("[2] last error", (plan()["last"] or {}).get("error"), "")
    lock = figure_build.build_lock(C)
    lock.acquire()
    try:
        check("[2] a Build holds the lock → building", figure_build.start_base_run_all(C)["status"], "building")
    finally:
        lock.release()
    with Patch((model3d, "generation_running", lambda c: True)):
        check("[2] a 3D run going → busy", figure_build.start_base_run_all(C)["status"], "busy")
    check("[2] lock free after busy", figure_build.build_lock(C).locked(), False)

# [3]
recomputed = []
result = {"models": {"sig1": {"ok": True, "count": 30}}}


def recompute(c, *, apply_channels=False):
    recomputed.append((c, apply_channels))
    return result


step = figure_build.Step("collision", figure_build.COLLISION_LABEL, 0)
with Patch((collision, "recompute_character", recompute)):
    STATE["due"] = False
    with Patch((collision, "channels_due", lambda c: STATE["due"])):
        check("[3] not due → nothing", (figure_build._run_collision(C, step), recomputed), ("", []))
        STATE["due"] = True
        check("[3] due → applied", (figure_build._run_collision(C, step), recomputed), ("", [(C, True)]))
        result["models"] = {"sig1": {"ok": False, "error": "unreadable"}}
        check("[3] a failing model", figure_build._run_collision(C, step),
              "Collision capsules not recomputed — sig1: unreadable")
check("[3] last in STEP_ORDER", figure_build.STEP_ORDER[-1], "collision")
check("[3] slot + unpinned", ("collision" in figure_build.SLOT_STEPS, "collision" in figure_build.UNPINNED_STEPS),
      (True, True))
check("[3] no DEPENDS, no STOP", ("collision" in figure_build.DEPENDS, "collision" in figure_build.STOP_STEPS),
      (False, False))
check("[3] label", figure_build.STEP_LABELS["collision"], figure_build.COLLISION_LABEL)

# [4]
RECORD = {"source": "base", "capsules": [{"id": f"c{i}", "region": "torso", "r": 0.05} for i in range(30)],
          "channels": [{"id": "demo:channel"}]}
META = {"rig": "mixamo", "collision": RECORD}


def collision_row(**kw):
    rows = model_overview.outfit_model_steps(META, base=None, base_meta=None, wanted_variant=None, deciders=[],
                                             shown=[], dressed_records={}, garments=[], tiers=[], **kw)
    row = next(r for r in rows if r["id"] == "collision")
    return row["status"], row["detail"].split(" · ")[0]


check("[4] channels not current → due", collision_row(collision_current=True, channels_current=False),
      ("due", "Channel settings changed — recompute to apply"))
check("[4] both current → done", collision_row(collision_current=True, channels_current=True)[0], "done")
check("[4] capsules outdated → warning, not due", collision_row(collision_current=False, channels_current=False)[0],
      "warning")

# [5]
DECL = {"id": "demo:channel", "bone": "Hips", "offset": [0.0, -0.05, 0.02], "axis": [0.0, 0.0, -1.0], "depth": 0.08,
        "radius": 0.015, "cone_deg": 25.0, "funnel": 0.03, "accepts": ["demo_op"], "min_length": 1.0,
        "compress_min": 0.6, "interaction_kinds": [], "exposed_only": False, "covered_by": [], "from_rig": None}
with Patch((collision_channels, "_any_region_declared", lambda: True),
           (collision_channels, "_profile", lambda c, profile=None: PROFILE),
           (collision_channels, "character_overrides", lambda c, profile=None: {}),
           (extension_rig, "region_declarations_for", lambda c, profile: [dict(DECL)])):
    out = collision_channels.declarations_info(C, None, {})
    check("[5] no model", [(d["id"], d["placement"], d["reason"]) for d in out],
          [("demo:channel", None, "No base model yet")])
    check("[5] NO_MODEL constant", collision_channels.NO_MODEL, "No base model yet")
    model = _tmp / "m.glb"
    placed = collision_channels.declarations_info(C, model, {"collision": {"channels": [
        {"id": "demo:channel", "placement": "declared"}]}})
    check("[5] placed", [(d["placement"], d["reason"]) for d in placed], [("declared", "")])
    bare = collision_channels.declarations_info(C, model, {"collision": {"channels": []}})
    check("[5] not computed", [(d["placement"], d["reason"]) for d in bare], [(None, "Not computed")])

print()
print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL OK")
sys.exit(1 if FAILS else 0)
