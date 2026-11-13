#!/usr/bin/env python3
"""The Base body tab's "Run all" and the face settings saved on their own (Task UI1 of
docs/superpowers/plans/2026-11-12-unified-worn-pieces.md; rules R1 "Run all skips what is current", R3 "settings
are saved without running anything").

Usage:
    ./.venv/bin/python scripts/smoke_base_body_run_all.py

Runs against a THROWAWAY storage directory (``paths.init(<tmp>)`` before any world module is imported) — no
world, no hub, no server, no thread that renders. The producers are stubs; what is checked is the judgement and the
wiring of ``figure_build.base_run_all`` / ``start_base_run_all`` / ``_face_retexture_pending``,
``model3d.set_model3d_options`` / ``remembered_face_controls`` and the route ``POST …/base-body/run-all``.

Expected, by hand from the brief and the code it reuses:

[1] ``base_run_all`` off the pipeline → kind "", steps [], hub_jobs 0.
[2] The plain body is outdated: ``base_refresh_plan(missing=True)`` = views [back, left], model True; skin step
    OFF; ``mesh_hub_stages`` = [mesh, rig] → ``base_rebuild_steps`` = view back 1, view left 1, mesh 1, rig 1 →
    kind "plain_body", steps [{view back, 1}, {view left, 1}, {mesh, 1}, {rig, 1}], hub_jobs 4 (the
    ``base_rebuild_cost`` sum — the Build's own arithmetic).
[3] Plain body current, face cleanup due (``face_cleanup_state`` can_reapply, follow_up face_retexture),
    ``mesh_hub_stages`` = [mesh, upscale, face, rig] → kind "face_cleanup", steps [cleanup 0, upscale 1, face 1,
    rig 1], hub_jobs 3; with follow_up "rerig" → steps [cleanup 0, rig 1], hub_jobs 1.
[4] Plain body current, cleanup not due, face retexture missing (``_face_retexture_pending`` True),
    ``mesh_hub_stages`` = [mesh, face, rig] → kind "face_retexture", steps [face 1, rig 1], hub_jobs 2; a stage
    list WITHOUT "face" (no face route known) still plans [face, rig] (2).
[5] Everything current → kind "", hub_jobs 0. A plan that raises → kind "", hub_jobs None, note
    "cost unknown — boom".
[6] ``_face_retexture_pending`` on files in the tmp dir: switch off → False; switch on, no stored model → False;
    model without its ``unrigged/<sig>.glb`` → False; with it and no record → True; record "applied" → False;
    "failed" → True; "reverted" → False; "skipped" → False; a non-humanoid rig ("generic") → False.
[7] ``start_base_run_all``: a Build running → "building"; nothing due → "current"; off the pipeline → "off";
    face cleanup due → ``trigger_face_cleanup(c, bsig)`` called once, "started"; its "already_running" → "busy";
    face retexture due → ``trigger_face_retexture(c, bsig)`` (no explicit values: the remembered ones), "started".
    Plain body due (views back, left): "started"; while the run is held the views back and left report
    ``running`` (``base_status``), the front does not; a second start → "busy"; the character's ``build_lock``
    is held; after the release: views idle, lock free, ``base_run_all(..)['last']`` = {error: "", …},
    ``_run_step`` got the step ``plain_body`` with explicit True. ``build_lock`` held by someone else →
    "building". A 3D run going (``generation_running``) → "busy" and the lock is released again.
[8] Face settings (rule R3): ``set_model3d_options(c, {face_controls: {strength: 0.8, feather: 0.18,
    render_resolution: 768, yaw: 0}})`` stores only the deviation {strength: 0.8}; the defaults again → the key
    is gone; ``{yaw: 200}`` → ValueError (bounds −180..180), nothing stored; ``{face_photo: {balance: 0.5}}``
    stores {balance: 0.5} (only deviations from 1.0). ``remembered_face_controls`` = the stored over the defaults
    {strength 0.8, feather 0.18, render_resolution 768, yaw 0}; a stored set that no longer validates
    ({yaw: 999}) → the defaults.
[9] Route through FastAPI (``require_admin`` overridden): started → 202 {status: started, kind}; current → 202;
    building / busy / off → 409 with the reason as ``detail``; failed → 503; a ValueError of a face redo → 409.
"""
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_tmp = Path(tempfile.mkdtemp(prefix="smoke_run_all_"))
from app.core import paths  # noqa: E402
paths.init(str(_tmp))

from app.core import base_body, base_skin, figure_build, model3d  # noqa: E402

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


def world(*, pipeline=True, refresh=None, cleanup=None, pending=False, stages=("mesh", "rig")):
    """The stubs every case shares; ``refresh`` the base refresh plan, ``cleanup`` the face cleanup state."""
    return Patch(
        (figure_build, "on_pipeline", lambda c, profile=None: pipeline),
        (base_body, "base_refresh_plan", lambda c, profile=None, missing=False: dict(refresh or REFRESH)),
        (base_skin, "enabled", lambda: False),
        (model3d, "mesh_hub_stages", lambda c, s: list(stages)),
        (model3d, "face_cleanup_state", lambda c, s: dict(cleanup or {"can_reapply": False})),
        (figure_build, "_face_retexture_pending", lambda c, s: pending),
    )


def plan():
    return figure_build.base_run_all(C, profile=PROFILE)


def brief(p):
    return [p["kind"], [(s["name"], s["jobs"]) for s in p["steps"]], p["hub_jobs"]]


# [1]
with world(pipeline=False):
    check("[1] off the pipeline", brief(plan()), ["", [], 0])

# [2]
with world(refresh={"signature": BSIG, "views": ["back", "left"], "model": True, "reason": "views"}):
    check("[2] plain body outdated", brief(plan()),
          ["plain_body", [("view back", 1), ("view left", 1), ("mesh", 1), ("rig", 1)], 4])

# [3]
with world(cleanup={"can_reapply": True, "follow_up": "face_retexture"}, stages=("mesh", "upscale", "face", "rig")):
    check("[3] face cleanup due", brief(plan()),
          ["face_cleanup", [("cleanup", 0), ("upscale", 1), ("face", 1), ("rig", 1)], 3])
with world(cleanup={"can_reapply": True, "follow_up": "rerig"}):
    check("[3] face cleanup due, re-rig follow-up", brief(plan()), ["face_cleanup", [("cleanup", 0), ("rig", 1)], 1])

# [4]
with world(pending=True, stages=("mesh", "face", "rig")):
    check("[4] face retexture missing", brief(plan()), ["face_retexture", [("face", 1), ("rig", 1)], 2])
with world(pending=True, stages=("mesh", "rig")):
    check("[4] no face stage known → face + rig", brief(plan()), ["face_retexture", [("face", 1), ("rig", 1)], 2])

# [5]
with world():
    check("[5] everything current", brief(plan()), ["", [], 0])


def boom(*a, **k):
    raise RuntimeError("boom")


with world(), Patch((base_body, "base_refresh_plan", boom)):
    p = plan()
    check("[5] unreadable plan", [p["kind"], p["hub_jobs"], p["note"]], ["", None, "cost unknown — boom"])

# [6]
mdir = _tmp / "m3d"
(mdir / "unrigged").mkdir(parents=True)
model = mdir / f"{BSIG}.glb"
records = {"rec": None}
opts = {"face_before_rig": False}
with Patch((model3d, "get_model3d_options", lambda c: dict(opts)),
           (model3d, "required_rig", lambda c, *a, **k: "mixamo"),
           (model3d, "find_model3d", lambda c, s: model if model.exists() else None),
           (model3d, "_read_sidecar", lambda path: ({"face_retexture": records["rec"]} if records["rec"] else {}))):
    pend = lambda: figure_build._face_retexture_pending(C, BSIG)  # noqa: E731
    check("[6] switch off", pend(), False)
    opts["face_before_rig"] = True
    check("[6] no stored model", pend(), False)
    model.write_bytes(b"glb")
    check("[6] no unrigged source", pend(), False)
    (mdir / "unrigged" / f"{BSIG}.glb").write_bytes(b"src")
    check("[6] no record", pend(), True)
    for status, want in (("applied", False), ("failed", True), ("reverted", False), ("skipped", False)):
        records["rec"] = {"status": status}
        check(f"[6] record {status}", pend(), want)
    records["rec"] = None
    with Patch((model3d, "required_rig", lambda c, *a, **k: "generic")):
        check("[6] not humanoid", pend(), False)

# [7]
calls = []
hold = threading.Event()
ran = threading.Event()


def run_step(c, step, explicit):
    calls.append(("run_step", c, step.name, explicit))
    ran.set()
    hold.wait(5)
    return ""


common = ((figure_build, "_read_profile", lambda c: PROFILE),
          (figure_build, "_tracked", lambda c, label: (None, "")),
          (figure_build, "_run_step", run_step),
          (base_body, "base_signature", lambda c, profile=None: BSIG),
          (model3d, "generation_running", lambda c: False),
          (model3d, "trigger_face_cleanup", lambda c, s: calls.append(("cleanup", c, s)) or {"status": "generating"}),
          (model3d, "trigger_face_retexture", lambda c, s, **k: calls.append(("face", c, s, k)) or
           {"status": "generating"}))
with world(), Patch(*common):
    with Patch((figure_build, "running", lambda c: True)):
        check("[7] a Build runs", figure_build.start_base_run_all(C)["status"], "building")
    check("[7] nothing due", figure_build.start_base_run_all(C), {"status": "current"})
with world(pipeline=False), Patch(*common):
    check("[7] off the pipeline", figure_build.start_base_run_all(C)["status"], "off")
with world(cleanup={"can_reapply": True, "follow_up": "rerig"}), Patch(*common):
    calls.clear()
    check("[7] cleanup started", figure_build.start_base_run_all(C), {"status": "started", "kind": "face_cleanup"})
    check("[7] cleanup trigger", calls, [("cleanup", C, BSIG)])
    with Patch((model3d, "trigger_face_cleanup", lambda c, s: {"status": "already_running"})):
        check("[7] cleanup already running", figure_build.start_base_run_all(C)["status"], "busy")
with world(pending=True, stages=("mesh", "face", "rig")), Patch(*common):
    calls.clear()
    check("[7] face started", figure_build.start_base_run_all(C), {"status": "started", "kind": "face_retexture"})
    check("[7] face trigger without explicit values", calls, [("face", C, BSIG, {})])
with world(refresh={"signature": BSIG, "views": ["back", "left"], "model": True, "reason": "views"}), Patch(*common):
    calls.clear()
    check("[7] plain body started", figure_build.start_base_run_all(C), {"status": "started", "kind": "plain_body"})
    ran.wait(5)
    status = base_body.base_status(C)
    check("[7] planned views running", [status[v]["running"] for v in ("front", "back", "left", "right")],
          [False, True, True, False])
    check("[7] second start busy", figure_build.start_base_run_all(C)["status"], "busy")
    check("[7] build_lock held", figure_build.build_lock(C).locked(), True)
    check("[7] plan says running", figure_build.base_run_all(C, profile=PROFILE)["running"], True)
    hold.set()
    for _ in range(50):
        if not figure_build.base_run_all(C, profile=PROFILE)["running"]:
            break
        threading.Event().wait(0.05)
    status = base_body.base_status(C)
    check("[7] views idle after", any(status[v]["running"] for v in status), False)
    check("[7] lock free after", figure_build.build_lock(C).locked(), False)
    last = figure_build.base_run_all(C, profile=PROFILE)["last"] or {}
    check("[7] last outcome", [last.get("error"), bool(last.get("finished_at"))], ["", True])
    check("[7] the Build's plain_body step, explicit", calls, [("run_step", C, "plain_body", True)])
    lock = figure_build.build_lock(C)
    lock.acquire()
    try:
        check("[7] build_lock held elsewhere", figure_build.start_base_run_all(C)["status"], "building")
    finally:
        lock.release()
    with Patch((model3d, "generation_running", lambda c: True)):
        check("[7] a 3D run going", figure_build.start_base_run_all(C)["status"], "busy")
    check("[7] lock released after the refusal", figure_build.build_lock(C).locked(), False)

# [8]
store = {C: {"name": C}}
import app.models.character as character_model  # noqa: E402
with Patch((character_model, "get_character_profile", lambda c, **k: dict(store.get(c) or {})),
           (character_model, "save_character_profile", lambda c, p, **k: store.__setitem__(c, dict(p)) or True)):
    model3d.set_model3d_options(C, {"face_controls": {"strength": 0.8, "feather": 0.18,
                                                      "render_resolution": 768, "yaw": 0}})
    check("[8] only the deviation stored", store[C].get("model3d_opts", {}).get("face_controls"), {"strength": 0.8})
    check("[8] remembered controls", model3d.remembered_face_controls(C),
          {"strength": 0.8, "feather": 0.18, "render_resolution": 768, "yaw": 0})
    try:
        model3d.set_model3d_options(C, {"face_controls": {"yaw": 200}})
        check("[8] yaw 200 refused", False)
    except ValueError:
        check("[8] yaw 200 refused", True)
    check("[8] nothing stored by the refusal", store[C]["model3d_opts"]["face_controls"], {"strength": 0.8})
    model3d.set_model3d_options(C, {"face_controls": {"strength": 1, "feather": 0.18, "render_resolution": 768,
                                                      "yaw": 0}})
    check("[8] defaults → key gone", "face_controls" in store[C]["model3d_opts"], False)
    model3d.set_model3d_options(C, {"face_photo": {"balance": 0.5}})
    check("[8] face photo deviation", store[C]["model3d_opts"].get("face_photo"), {"balance": 0.5})
    store[C]["model3d_opts"]["face_controls"] = {"yaw": 999}
    check("[8] invalid stored → defaults", model3d.remembered_face_controls(C),
          {"strength": 1, "feather": 0.18, "render_resolution": 768, "yaw": 0})

# [9]
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app.core.auth_dependency import require_admin  # noqa: E402
from app.routes import figure as figure_route  # noqa: E402

app = FastAPI()
app.include_router(figure_route.router)
app.dependency_overrides[require_admin] = lambda: {"role": "admin"}
client = TestClient(app)
answers = {"value": {"status": "started", "kind": "plain_body"}}


def start(c):
    value = answers["value"]
    if isinstance(value, Exception):
        raise value
    return value


(_tmp / "chars" / C).mkdir(parents=True)
with Patch((figure_route, "get_character_dir", lambda c: _tmp / "chars" / c),
           (figure_build, "start_base_run_all", start)):
    url = f"/characters/{C}/base-body/run-all"
    r = client.post(url)
    check("[9] started", [r.status_code, r.json()], [202, {"status": "started", "kind": "plain_body"}])
    answers["value"] = {"status": "current"}
    check("[9] current", client.post(url).status_code, 202)
    for status in ("building", "busy", "off"):
        answers["value"] = {"status": status, "reason": f"why {status}"}
        r = client.post(url)
        check(f"[9] {status} → 409", [r.status_code, r.json().get("detail")], [409, f"why {status}"])
    answers["value"] = {"status": "failed", "reason": "unread"}
    check("[9] failed → 503", client.post(url).status_code, 503)
    answers["value"] = ValueError("Switch the face cleanup on first.")
    r = client.post(url)
    check("[9] refused face redo → 409", [r.status_code, r.json().get("detail")],
          [409, "Switch the face cleanup on first."])
    check("[9] unknown character → 404", client.post("/characters/Nobody/base-body/run-all").status_code, 404)

print()
if FAILS:
    print(f"FAILED ({len(FAILS)}): " + ", ".join(FAILS))
    sys.exit(1)
print("ALL OK")
