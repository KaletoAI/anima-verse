#!/usr/bin/env python3
"""Pair tip settings are saved without a rebuild; the rebuild is its own step (Task UI2 gap 3 of
docs/superpowers/plans/2026-11-12-unified-worn-pieces.md; rule R3 "a setting is saved on its own, nothing runs",
R2 "a single step re-runs even when current", R1 "Run all picks up what a saved setting made due").

Usage:
    ./.venv/bin/python scripts/smoke_extension_tip_save_due.py

Runs against a THROWAWAY storage directory (``paths.init(<tmp>)`` before any world module is imported) — no world,
no Blender, no server. The profile store is a dict; the rebuild worker (``extension_tip._apply``) is replaced by a
recorder; the extension fingerprint is replaced by ``json.dumps(overrides, sort_keys=True)`` of the per-model
overrides (``effective_extension_overrides`` → ``model3d_opts.extension_rig_models[sig]``) so every expected
value below is written out by hand.

[1] ``extension_tip.save_tip_override(C, sig, "Tip", tip)`` stores ``extension_rig_models[sig]["Tip"]["tip"]`` (the
    validated value) and starts NO rebuild (the recorder stays empty, no slot taken). While a rebuild of C runs
    (slot taken) → RuntimeError(REBUILD_RUNNING), nothing stored.
[2] ``model3d.extension_settings_changed``: a sidecar without ``extension_rig`` → False (never built: its own run
    builds it); attempted with fingerprint '{}' while the store holds the tip of [1] → the fingerprint now is
    '{"Tip": {"tip": …}}' ≠ '{}' → True; the stored state built with exactly that → False.
[3] ``extension_tip.start_tip_rebuild``: an unknown signature → ValueError; a known one → True and the recorder got
    (C, sig) once; a second start while the first holds the slot → False.
[4] ``figure_build.base_run_all`` with the plain body current, no cleanup, no face step, the mesh repair current
    (Ruling A34) and the settings of [1]
    newer than the build → kind "extension_rig", steps [extension 0], hub_jobs 0; ``start_base_run_all`` →
    ``{"status": "started", "kind": "extension_rig"}`` and the recorder got (C, BSIG); with the slot taken →
    "busy". Built with the saved settings → kind "".
[5] Routes (FastAPI, ``require_admin`` overridden): POST …/model3d/extension-tip {signature, group, tip} → 200
    {tip, due: True} and no rebuild started; POST …/model3d/extension-tip/apply {signature} → 202 {started: true}
    and one rebuild; again while it runs → 409 REBUILD_RUNNING; the save while it runs → 409.

Fails on 55a2a478: AttributeError — module ``extension_tip`` has no attribute ``save_tip_override``.
"""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_tmp = Path(tempfile.mkdtemp(prefix="smoke_tip_save_"))
from app.core import paths  # noqa: E402
paths.init(str(_tmp))
from app.core import db  # noqa: E402
db.init_schema()

from app.core import base_body, base_skin, extension_rig, extension_tip, figure_build, model3d  # noqa: E402
import app.models.character as character_model  # noqa: E402

FAILS = []


def check(label, got, want=True):
    ok = got == want
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + ("" if ok else f"  — got {got!r}, want {want!r}"))
    if not ok:
        FAILS.append(label)


class Patch:
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
store = {C: {"name": C}}
mdir = _tmp / "m3d"
mdir.mkdir()
model = mdir / f"{BSIG}.glb"
model.write_bytes(b"glb")
sidecar = {"value": {}}
rebuilds = []
TIP = {"offsets": [{"up": 2, "out": 0}, {"up": 2, "out": 0}], "mirror": True,
       "disc": {"enabled": False, "color": "#aa5544", "diameter_mm": 28, "soft_mm": 2}}


def record_rebuild(character, signature):
    """The worker's stand-in: records the call and frees the slot, as ``_apply``'s ``finally`` does."""
    rebuilds.append((character, signature))
    with extension_tip._lock:
        extension_tip._running.pop(character, None)


def overrides_of(profile, signature, meta, declarations):
    return ((profile.get("model3d_opts") or {}).get("extension_rig_models") or {}).get(signature) or {}


common = Patch(
    (character_model, "get_character_profile", lambda c, **k: json.loads(json.dumps(store.get(c) or {}))),
    (character_model, "save_character_profile", lambda c, p, **k: store.__setitem__(c, json.loads(json.dumps(p))) or True),
    (extension_tip, "_tip_groups", lambda c, s, **k: [{"id": "Tip", "op": "pair_tip"}]),
    (extension_tip, "_apply", record_rebuild),
    (extension_rig, "rig_groups_for", lambda c, profile=None, mesh_variant=None: []),
    (extension_rig, "effective_extension_overrides", overrides_of),
    (extension_rig, "extension_rig_fingerprint", lambda groups, overrides=None: json.dumps(overrides or {}, sort_keys=True)),
    (model3d, "find_model3d", lambda c, s: model if s == BSIG else None),
    (model3d, "_read_sidecar", lambda path: json.loads(json.dumps(sidecar["value"]))),
)


def stored_tip():
    return ((((store[C].get("model3d_opts") or {}).get("extension_rig_models") or {}).get(BSIG) or {})
            .get("Tip") or {}).get("tip")


def wait_free():
    import time
    for _ in range(100):
        with extension_tip._lock:
            if C not in extension_tip._running:
                return
        time.sleep(0.01)


with common:
    # [1]
    saved = extension_tip.save_tip_override(C, BSIG, "Tip", TIP)
    check("[1] stored", stored_tip(), saved)
    check("[1] the stored value has the offsets", (saved or {}).get("offsets"), [{"up": 2.0, "out": 0.0}, {"up": 2.0, "out": 0.0}])
    check("[1] no rebuild started", rebuilds, [])
    check("[1] no slot taken", C in extension_tip._running, False)
    with extension_tip._lock:
        extension_tip._running[C] = BSIG
    try:
        extension_tip.save_tip_override(C, BSIG, "Tip", None)
        check("[1] save while a rebuild runs refused", False)
    except RuntimeError as exc:
        check("[1] save while a rebuild runs refused", str(exc), extension_tip.REBUILD_RUNNING)
    check("[1] nothing changed by the refusal", stored_tip(), saved)
    with extension_tip._lock:
        extension_tip._running.pop(C, None)

    # [2]
    check("[2] never built → not changed", model3d.extension_settings_changed(C, model), False)
    sidecar["value"] = {"base": True, "extension_rig": {"attempted": True, "status": "applied", "fingerprint": "{}"}}
    check("[2] built before the save → changed", model3d.extension_settings_changed(C, model), True)
    now = json.dumps({"Tip": {"tip": saved}}, sort_keys=True)
    sidecar["value"]["extension_rig"]["fingerprint"] = now
    check("[2] built with the saved settings → not changed", model3d.extension_settings_changed(C, model), False)

    # [3]
    try:
        extension_tip.start_tip_rebuild(C, "unknown")
        check("[3] unknown model refused", False)
    except ValueError:
        check("[3] unknown model refused", True)
    with extension_tip._lock:
        extension_tip._running[C] = "held"
    check("[3] a second start while one runs", extension_tip.start_tip_rebuild(C, BSIG), False)
    with extension_tip._lock:
        extension_tip._running.pop(C, None)
    check("[3] started", extension_tip.start_tip_rebuild(C, BSIG), True)
    wait_free()
    check("[3] the worker ran once", rebuilds, [(C, BSIG)])
    rebuilds.clear()

    # [4]
    sidecar["value"]["extension_rig"]["fingerprint"] = "{}"
    plan_stubs = Patch(
        (figure_build, "on_pipeline", lambda c, profile=None: True),
        (figure_build, "_read_profile", lambda c: {"name": C}),
        (figure_build, "running", lambda c: False),
        (base_body, "base_signature", lambda c, profile=None: BSIG),
        (base_body, "base_refresh_plan", lambda c, profile=None, missing=False: {
            "signature": BSIG, "views": [], "model": False, "reason": ""}),
        (base_skin, "enabled", lambda: False),
        (model3d, "face_cleanup_state", lambda c, s: {"can_reapply": False}),
        (model3d, "generation_running", lambda c: False),
        (figure_build, "_face_retexture_pending", lambda c, s: ""),
        (figure_build, "_mesh_repair_due", lambda c, s: False))
    with plan_stubs:
        p = figure_build.base_run_all(C, profile={"name": C})
        check("[4] extension rebuild due", [p["kind"], [(s["name"], s["jobs"]) for s in p["steps"]], p["hub_jobs"]],
              ["extension_rig", [("extension", 0)], 0])
        check("[4] start", figure_build.start_base_run_all(C), {"status": "started", "kind": "extension_rig"})
        wait_free()
        check("[4] the rebuild ran", rebuilds, [(C, BSIG)])
        rebuilds.clear()
        with extension_tip._lock:
            extension_tip._running[C] = "held"
        check("[4] slot taken → busy", figure_build.start_base_run_all(C)["status"], "busy")
        with extension_tip._lock:
            extension_tip._running.pop(C, None)
        sidecar["value"]["extension_rig"]["fingerprint"] = now
        check("[4] built with the saved settings → current", figure_build.base_run_all(C, profile={"name": C})["kind"], "")

    # [5]
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.core.auth_dependency import require_admin
    from app.routes import characters as characters_route
    app = FastAPI()
    app.include_router(characters_route.router)
    app.dependency_overrides[require_admin] = lambda: {"role": "admin"}
    client = TestClient(app)
    sidecar["value"]["extension_rig"]["fingerprint"] = "{}"
    (_tmp / "chars" / C).mkdir(parents=True)
    with Patch((characters_route, "get_character_dir", lambda c: _tmp / "chars" / c),
               (base_body, "base_model_info", lambda c, s: {"status": "ready"})):
        r = client.post(f"/characters/{C}/model3d/extension-tip", json={"signature": BSIG, "group": "Tip", "tip": TIP})
        check("[5] save answers", [r.status_code, r.json().get("due"), r.json().get("tip") == saved], [200, True, True])
        check("[5] the save started no rebuild", rebuilds, [])
        with extension_tip._lock:
            extension_tip._running[C] = "held"
        r = client.post(f"/characters/{C}/model3d/extension-tip/apply", json={"signature": BSIG})
        check("[5] apply while one runs", [r.status_code, r.json().get("detail")], [409, extension_tip.REBUILD_RUNNING])
        r = client.post(f"/characters/{C}/model3d/extension-tip", json={"signature": BSIG, "group": "Tip", "tip": None})
        check("[5] save while one runs", r.status_code, 409)
        with extension_tip._lock:
            extension_tip._running.pop(C, None)
        r = client.post(f"/characters/{C}/model3d/extension-tip/apply", json={"signature": BSIG})
        check("[5] apply", [r.status_code, r.json()], [202, {"started": True}])
        wait_free()
        check("[5] one rebuild", rebuilds, [(C, BSIG)])

print("\n" + ("ALL OK" if not FAILS else f"{len(FAILS)} FAILED: " + ", ".join(FAILS)))
sys.exit(1 if FAILS else 0)
