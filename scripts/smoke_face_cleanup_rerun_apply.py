#!/usr/bin/env python3
"""The improvement "Re-run face cleanup" really runs (app/core/improvements/types/face_cleanup_rerun.py
``apply``; app/core/model3d.py ``face_cleanup_rerun_state``) — review 09#1.

Usage:
    ./.venv/bin/python scripts/smoke_face_cleanup_rerun_apply.py

Runs against a THROWAWAY storage directory (``paths.init`` first); no world, no hub, no server.
``model3d.get_model3d_dir`` / ``get_model3d_options`` / ``required_rig`` / ``face_cleanup_signature`` are
stubs over a temp model directory, ``run_face_cleanup`` is a recorder answering ``{"ok": True}``, the rig
route (``routing.chain_candidates``) answers one entry and ``get_image_service`` is a bare pool holder —
nothing is cleaned, rigged or rendered.

Fixture: character ``X``, signature ``s1``: ``unrigged/s1.glb`` + sidecar ``face_cleanup {status applied,
version VERSION-1}``, switch on, humanoid (``mixamo``), no ``facefix/s1.glb`` and ``face_before_rig`` off
(-> follow-up ``rerig``), no mesher original (-> ``from_stored`` True).

Expected, by hand from the rules:
[1] ``find_candidates({character: X})`` -> one candidate, key ``character:X:s1:<VERSION-1>``.
[2] ``apply`` of it -> returns None AND ``run_face_cleanup`` was called exactly once with
    ``(X, s1, "rerig", from_stored=True, track_id="t1")``; afterwards X is not in ``model3d._generating``.
    (The old ``apply`` took the guard and then asked ``face_cleanup_rerun_state``, which answered None for a
    character in ``_generating`` — its own guard: 0 calls, None returned, the engine closed the step as done.
    Fails on 3f2ce338e with "run_face_cleanup calls: 0".)
[3] Another holder in ``_generating`` (a Build): ``find_candidates`` STILL lists the candidate (a scan that
    drops it closes the pending step as done — ``store.replace_steps_scan``), ``apply`` raises
    ``CandidateBusy`` and ``run_face_cleanup`` is not called; the other holder's guard stays.
[4] The record at the CURRENT version -> no candidate, and ``apply`` of the old key returns None without a
    call (the work is really done).
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
tmp = Path(tempfile.mkdtemp())
os.environ["STORAGE_DIR"] = str(tmp)
os.environ["INSTANCE_DIR"] = str(tmp / "instance")
from app.core import paths  # noqa: E402
paths.init(str(tmp))
from app.core import face_cleanup, model3d  # noqa: E402
from app.core.improvements.base import CandidateBusy  # noqa: E402
from app.core.improvements.types.face_cleanup_rerun import FaceCleanupRerun  # noqa: E402
import app.imagegen.routing as routing  # noqa: E402
import app.imagegen.service as service  # noqa: E402

root = tmp / "m3d"
(root / "unrigged").mkdir(parents=True)
SIG = "s1"
V = face_cleanup.VERSION
(root / "unrigged" / f"{SIG}.glb").write_bytes(b"glb")


def record(version):
    (root / "unrigged" / f"{SIG}.json").write_text(json.dumps({"face_cleanup": {"status": "applied",
                                                                                 "version": version}}))


record(V - 1)
model3d.get_model3d_dir = lambda name: root
model3d.get_model3d_options = lambda name: {"face_cleanup": True}
model3d.required_rig = lambda name: "mixamo"
model3d.face_cleanup_signature = lambda name, signature="": SIG
calls = []


def fake_run(name, signature, follow_up, *, from_stored=False, track_id=""):
    calls.append((name, signature, follow_up, from_stored, track_id))
    return {"ok": True}


model3d.run_face_cleanup = fake_run
routing.chain_candidates = lambda occasion, pool=None: ["rigger"]
service.get_image_service = lambda: type("S", (), {"pool": None})()

fails = 0


def check(label, got, want):
    global fails
    ok = got == want
    fails += not ok
    print("OK  " if ok else "FAIL", label, "->", got, "" if ok else f"(want {want})")


typ = FaceCleanupRerun()
params = {"character": "X"}

print("[1] candidate")
cands = typ.find_candidates(params)
check("candidate keys", [c.key for c in cands], [f"character:X:{SIG}:{V - 1}"])

print("[2] apply runs the re-run")
check("apply returns", typ.apply(cands[0], params, "t1"), None)
check("run_face_cleanup calls", len(calls), 1)
check("call args", calls[:1], [("X", SIG, "rerig", True, "t1")])
check("guard released", "X" in model3d._generating, False)

print("[3] another run holds the character")
calls.clear()
model3d._generating.add("X", "Build")
check("still a candidate", [c.key for c in typ.find_candidates(params)], [f"character:X:{SIG}:{V - 1}"])
try:
    typ.apply(cands[0], params, "t2")
    check("apply raises CandidateBusy", "returned", "CandidateBusy")
except CandidateBusy:
    check("apply raises CandidateBusy", "CandidateBusy", "CandidateBusy")
check("run_face_cleanup calls", len(calls), 0)
check("the other holder keeps its guard", ("X" in model3d._generating, model3d._generating.what.get("X")),
      (True, "Build"))
model3d._generating.discard("X")

print("[4] already at the current version")
record(V)
check("no candidate", typ.find_candidates(params), [])
check("apply returns", typ.apply(cands[0], params, "t3"), None)
check("run_face_cleanup calls", len(calls), 0)

print("FAILED" if fails else "ALL OK")
sys.exit(1 if fails else 0)
