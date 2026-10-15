#!/usr/bin/env python3
"""Smoke run for hub jobs that survive a restart of Anima (docs/hub-job-resume.md,
spec docs/superpowers/specs/2026-10-13-hub-job-resume-design.md).

No server and no real gateway: the world is a temp dir (``paths.init`` before
any world import), the gateway is a local ``http.server`` speaking the job
protocol (POST /v1/generations → 202 {job_id}; GET /v1/jobs/{id}; GET
/v1/jobs/{id}/result/{n}; POST /v1/jobs/{id}/cancel), and a "restart" is
simulated the way a process death looks to the record: a ``_Died``
BaseException right after the job id was stored (it passes every
``except Exception``, so no record is settled), then a NEW process id, NEW
backend objects and a NEW service — only the world DB and the record's
directory stay.

What is expected, derived by hand from the spec (section numbers):

  A1 (§ 5.1)  a staged video render POSTs once; while it runs the record holds
              exactly one stage job: phase "submitted", the job id the fake
              gave out ("job-1"), backend "hub-video", owner "thread"; after the
              publish the record AND its directory are gone.
  A2 (§ 5.2)  restart after the POST: collecting the same stage makes 0 POSTs
              and ≥ 1 GET of /v1/jobs/job-2, and the MP4 lands at the normal
              target, byte-identical to the fake's result.
  A3 (§ 5.3)  a job the gateway forgot answers 404; the attach poll needs 3 in
              a row (the same cap as a live poll) → HubJobLost, the backend is
              NOT in cooldown, the thread record is deleted.
  A4 (§ 5.4)  two 503s and one dropped connection are "unreachable", not lost:
              the 4th GET sees "done" and the video is collected.
  A5 (§ 5.8)  submitted 25 h ago → HubJobLost before any HTTP request (GET
              count of that job stays 0).
  A6 (finding) submitted 2 h ago, job done: still collected — the time budget
              (queue + run, 2 × 60 s here) only applies to a job still
              queued/running, never to one that is done.
  A7 (D1)     a stage left in "posting" by an earlier process → HubJobLost
              "interrupted … submission", 0 POSTs.
  A8 (D2)     a stage only "claimed" by an earlier process (it waited for its
              GPU slot) → submitted normally: exactly 1 POST.
  A9 (D3)     a second operation on the same subject → HubOpBusy.
  A10 (finding) a claimed stage whose routed backend has no job protocol →
              HubJobLost, nothing submitted again.
  A11 mesh    the mesh attach restores the uploaded inputs' sha256 from the
              record: a job view reporting a FOREIGN input hash is refused
              (GatewayInputMismatchError), our own hash is collected.

  B1 (§ 3.4)  run_on_backend re-raises HubJobLost as itself: no cooldown, no
              BackendFailedError. run_routed renders exactly once.
  B2          TaskQueue: a handler raising HubJobLost with max_retries=2 ends
              "failed" with retry_count 0 (one run, no retry).
  B3          Improvements: a HubJobLost step is "skipped" after ONE attempt
              (MAX_ATTEMPTS is 2 for any other error).
  B4          face retexture: a lost UPSCALE job ends the whole correction
              (raised, no face job submitted) instead of "upscale failed,
              project the raw photo".

  C1 (§ 5.7 + § 0 chain) task-owned character mesh, worn signature "sigA":
              mesh done, static mesh published (checkpoint), rig submitted,
              process dies. After the restart the character wears "sigB"; the
              re-run handler calls generate_for_current_outfit(name) WITHOUT a
              signature → it resumes the record: the rig is COLLECTED (prepare
              = "attach"), the T-pose lookup and the mesh job do not run again
              (mesh calls stay 1), the rigged model lands as sigA.glb, nothing
              is written for sigB, the record is gone.
  C1b         the same chain owned by a thread: a second start meanwhile raises
              HubOpBusy (D3/D11), and the kind's registered resume entry —
              what the resumer calls — collects the rig and publishes.
  C2 (§ 0 preprocessing) prop mesh: the source render runs once; after the
              restart the resumed run renders nothing and the gallery gains
              exactly ONE file.
  C3 (§ 0 face) face retexture dying in its rig job leaves the corrected
              source, its sidecar and the replacement mask in the record's
              directory (the staging dir is gone); the resume publishes them.
  C4 (§ 5.5 + § 3.6) start_resumer: a thread-owned prop record is resumed and
              its guard (props._generating) is taken BEFORE start_resumer
              returns; its prop was deleted, so the stage ends before any
              poll and its recorded hub job is cancelled; a task-owned record of a PAUSED queue is collected ahead
              (raw blobs in the record dir, 0 POSTs), its handler not run; a
              failed thread record is reported and deleted; an unknown kind is
              dropped and its hub job cancelled.
  C4b         a record whose mesh stage is done and whose rig job is out:
              only the rig counts as in flight (collected ahead / cancelled).
  C5 (§ 5.6)  pose animation: progress + an open record with a submitted job →
              the handler attaches (no cancel, no LLM, no second submission)
              and ends in awaiting_choice.
  C6 (D8)     a task's lost job stays a tombstone: the same handler meets it
              again as HubJobLost (no new job); the task's end deletes it.
  C7 (D4)     a task that ended without resuming its record hands it to a
              thread (continued); a cancelled pending task drops it and
              cancels the hub job.
  C8 (§ 3.8)  a held display row survives the 20-min reaper; a cancelled one
              is not overwritten by track_finish_if_open.

Usage:  ./.venv/bin/python scripts/smoke_hub_job_resume.py
"""
import hashlib
import json
import os
import sys
import tempfile
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_TMP = tempfile.mkdtemp(prefix="smoke-hub-resume-")
from app.core import paths  # noqa: E402
paths.init(_TMP)

from app.core import db  # noqa: E402
db.init_schema()

from app.core import hub_ops  # noqa: E402
from app.core.timeutils import utc_now  # noqa: E402
from app.imagegen import service as service_mod  # noqa: E402
from app.imagegen.base import (BackendFailedError, GatewayInputMismatchError,  # noqa: E402
                               HubJobLost)
from app.imagegen.selection import BackendPool  # noqa: E402

FAILURES = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


class _Died(BaseException):
    """The process going down: passes every ``except Exception``."""


# ── the fake hub ─────────────────────────────────────────────────────────
VIDEO = b"\x00\x00\x00\x18ftypmp42" + b"v" * 4000


class Hub:
    def __init__(self):
        self.lock = threading.Lock()
        self.reset()

    def reset(self):
        self.n = 0
        self.jobs = {}
        self.posts = 0
        self.gets = {}
        self.cancels = []
        self.next_mode = "done"
        self.next_results = None

    def new_job(self, mode="done", results=None, inputs=None):
        with self.lock:
            self.n += 1
            jid = f"job-{self.n}"
            self.jobs[jid] = {"mode": mode, "polls": 0, "inputs": inputs or [],
                              "results": results if results is not None else [VIDEO]}
            return jid


HUB = Hub()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, code, body):
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        if self.path == "/v1/generations":
            HUB.posts += 1
            jid = HUB.new_job(HUB.next_mode, HUB.next_results)
            return self._json(202, {"job_id": jid})
        if self.path.endswith("/cancel"):
            HUB.cancels.append(self.path.split("/")[3])
            return self._json(200, {"ok": True})
        self._json(404, {})

    def do_GET(self):
        parts = self.path.strip("/").split("/")
        if self.path == "/v1/models":
            return self._json(200, {"data": []})
        if len(parts) >= 3 and parts[:2] == ["v1", "jobs"]:
            jid = parts[2]
            job = HUB.jobs.get(jid)
            if len(parts) == 5 and parts[3] == "result":
                if not job:
                    return self._json(404, {})
                blob = job["results"][int(parts[4])]
                self.send_response(200)
                self.send_header("Content-Length", str(len(blob)))
                self.end_headers()
                self.wfile.write(blob)
                return
            HUB.gets[jid] = HUB.gets.get(jid, 0) + 1
            if not job or job["mode"] == "404":
                return self._json(404, {"detail": "unknown job"})
            job["polls"] += 1
            mode = job["mode"]
            if mode == "flaky" and job["polls"] <= 3:
                if job["polls"] == 2:
                    self.close_connection = True     # a dropped connection
                    self.connection.close()
                    return
                return self._json(503, {"detail": "down"})
            if mode == "running":
                return self._json(200, {"status": "running", "job_id": jid})
            results = [{"n": i, "name": f"result_{i}.bin", "url": f"/v1/jobs/{jid}/result/{i}",
                        "mime": "video/mp4", "sha256": hashlib.sha256(b).hexdigest()}
                       for i, b in enumerate(job["results"])]
            return self._json(200, {"status": "done", "job_id": jid, "results": results,
                                    "input_images": job["inputs"]})
        self._json(404, {})


SERVER = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=SERVER.serve_forever, daemon=True).start()
HUB_URL = f"http://127.0.0.1:{SERVER.server_address[1]}"

for prefix in ("HUBV_", "HUBM_"):
    os.environ[f"{prefix}POLL_INTERVAL"] = "0.05"
    os.environ[f"{prefix}MAX_WAIT"] = "60"
    os.environ[f"{prefix}MAX_QUEUE_WAIT"] = "60"
os.environ["HUBM_CATEGORY"] = "img2mesh"


def fresh_service():
    """A NEW process' service: new backend objects on the same gateway."""
    from app.imagegen.backends.openai_mesh import OpenAIMeshBackend
    from app.imagegen.backends.openai_video import OpenAIVideoBackend
    from app.imagegen.service import ImageService
    video = OpenAIVideoBackend("hub-video", HUB_URL, 0, "HUBV_", model="Video-Alias")
    mesh = OpenAIMeshBackend("hub-mesh", HUB_URL, 0, "HUBM_", model="Mesh-Alias")
    svc = object.__new__(ImageService)
    svc._pool = BackendPool([video, mesh], agent_instances_provider=lambda name: {})
    svc.run_on_backend_channel = lambda backend, fn, **kw: fn()
    service_mod._service = svc
    return svc, video, mesh


def restart():
    """What survives a restart: the DB and the files. Nothing else."""
    hub_ops._PROCESS_ID = uuid.uuid4().hex
    return fresh_service()


def still() -> Path:
    p = Path(_TMP) / "still.png"
    if not p.exists():
        from PIL import Image
        Image.new("RGB", (16, 16), (200, 10, 10)).save(p)
    return p


def video_op(subject):
    op = hub_ops.create("smoke_video", subject, {"source": str(still())}, label="smoke")
    return op


def render(svc, op, target):
    return hub_ops.execute(op, lambda: {"ok": svc.generate_video(
        str(still()), "wave", str(target), backend_glob="hub-video",
        hub_stage=op.stage("video"))})


def ops_count():
    return len(hub_ops.list_ops())


# ═════════════════════════════════════════════════════════════════════════
print("\nA — the job protocol (fake hub, real service and backends)")
svc, video, mesh = fresh_service()

# A1
op = video_op("a1")
seen = {}
orig = video._collect


def peek(job_id, **kw):
    seen.update(hub_ops.get(op.op_id).jobs().get("video") or {})
    return orig(job_id, **kw)


video._collect = peek
target = Path(_TMP) / "out" / "a1.mp4"
res = render(svc, op, target)
video._collect = orig
check("A1 one POST", HUB.posts == 1, str(HUB.posts))
check("A1 the stage record while running: submitted job-1 on hub-video",
      seen.get("phase") == "submitted" and seen.get("job_id") == "job-1"
      and seen.get("backend") == "hub-video", str(seen))
check("A1 owner is a thread outside a queue handler", op.owner_kind == "thread", op.owner_kind)
check("A1 published: record and directory gone",
      res.get("ok") and hub_ops.get(op.op_id) is None and not op.dir.exists(), str(res))

# A2
HUB.reset()
HUB.next_mode = "running"
op = video_op("a2")
target = Path(_TMP) / "out" / "a2.mp4"


def die(job_id, **kw):
    raise _Died()


video._collect = die
try:
    render(svc, op, target)
except _Died:
    pass
check("A2 the dead process left the record with job-1",
      (hub_ops.get(op.op_id).jobs().get("video") or {}).get("job_id") == "job-1")
HUB.jobs["job-1"]["mode"] = "done"
posts_before = HUB.posts
svc, video, mesh = restart()
op = hub_ops.get(op.op_id)
res = render(svc, op, target)
check("A2 0 POSTs after the restart", HUB.posts == posts_before, f"{HUB.posts - posts_before}")
check("A2 >= 1 GET of the recorded job", HUB.gets.get("job-1", 0) >= 1, str(HUB.gets))
check("A2 the MP4 at the normal target, byte-identical",
      res.get("ok") and target.read_bytes() == VIDEO)
check("A2 record gone", hub_ops.get(op.op_id) is None)


def recorded(subject, mode, *, hours_ago=0.0, phase="submitted", backend="hub-video"):
    """A record as a dead process left it: one stage, a job on the fake hub."""
    op = video_op(subject)
    jid = HUB.new_job(mode) if phase == "submitted" else ""
    stamp = (utc_now().timestamp() - hours_ago * 3600)
    from datetime import datetime, timezone
    iso = datetime.fromtimestamp(stamp, tz=timezone.utc).isoformat(timespec="seconds")

    def put(state):
        job = {"phase": phase, "backend": backend, "api_url": HUB_URL, "pid": "dead-process"}
        if phase == "submitted":
            job.update(job_id=jid, submitted_at=iso, attach_params={}, route={})
        if phase == "claimed":
            job.update(claimed_at=iso)
        state.setdefault("jobs", {})["video"] = job
    op.update_state(put)
    return hub_ops.get(op.op_id), jid


# A3
HUB.reset()
svc, video, mesh = restart()
op, jid = recorded("a3", "404")
try:
    render(svc, op, Path(_TMP) / "out" / "a3.mp4")
    check("A3 404 → HubJobLost", False, "no exception")
except HubJobLost as e:
    check("A3 404 → HubJobLost", "Hub job lost" in str(e), str(e))
check("A3 three GETs before giving up", HUB.gets.get(jid) == 3, str(HUB.gets))
check("A3 no backend cooldown", not video.in_cooldown())
check("A3 thread record deleted", hub_ops.get(op.op_id) is None)

# A4
HUB.reset()
op, jid = recorded("a4", "flaky")
target = Path(_TMP) / "out" / "a4.mp4"
res = render(svc, op, target)
check("A4 503 + dropped connection are not lost: collected",
      res.get("ok") and target.read_bytes() == VIDEO, str(res))
check("A4 the 4th poll saw done", HUB.gets.get(jid) == 4, str(HUB.gets))

# A5
HUB.reset()
op, jid = recorded("a5", "done", hours_ago=25)
try:
    render(svc, op, Path(_TMP) / "out" / "a5.mp4")
    check("A5 25 h old → HubJobLost", False, "no exception")
except HubJobLost as e:
    check("A5 25 h old → HubJobLost", "24 h" in str(e), str(e))
check("A5 no HTTP request for it", HUB.gets.get(jid, 0) == 0, str(HUB.gets))

# A6
HUB.reset()
op, jid = recorded("a6", "done", hours_ago=2)
target = Path(_TMP) / "out" / "a6.mp4"
res = render(svc, op, target)
check("A6 2 h old, done: collected despite the 120 s budget", res.get("ok"), str(res))

# A7
HUB.reset()
op, _ = recorded("a7", "done", phase="posting")
try:
    render(svc, op, Path(_TMP) / "out" / "a7.mp4")
    check("A7 posting gap → HubJobLost", False, "no exception")
except HubJobLost as e:
    check("A7 posting gap → HubJobLost", "submission" in str(e), str(e))
check("A7 0 POSTs", HUB.posts == 0, str(HUB.posts))

# A8
HUB.reset()
op, _ = recorded("a8", "done", phase="claimed")
res = render(svc, op, Path(_TMP) / "out" / "a8.mp4")
check("A8 a claimed-only stage is submitted normally: 1 POST",
      res.get("ok") and HUB.posts == 1, f"{res} posts={HUB.posts}")

# A9
op1 = video_op("a9")
try:
    video_op("a9")
    check("A9 second operation on the subject → HubOpBusy", False)
except hub_ops.HubOpBusy:
    check("A9 second operation on the subject → HubOpBusy", True)
hub_ops.delete(op1)

# A10
from app.imagegen.base import ImageBackend  # noqa: E402


class ThirdParty(ImageBackend):
    MEDIA_TYPE = "video"

    def check_availability(self):
        return True

    def _generate(self, *a):
        return [VIDEO]


svc._pool.backends.append(ThirdParty("third-party", "http://elsewhere", 0, "video_x", "TPV_"))
HUB.reset()
op, _ = recorded("a10", "done", phase="claimed")
op.update_state(lambda st: st["jobs"]["video"].update(route_backend="third-party"))
try:
    render(svc, op, Path(_TMP) / "out" / "a10.mp4")
    check("A10 a claimed stage on a non-hub backend → HubJobLost", False, "no exception")
except HubJobLost as e:
    check("A10 a claimed stage on a non-hub backend → HubJobLost", "third-party" in str(e), str(e))
check("A10 nothing submitted", HUB.posts == 0)
svc._pool.backends.pop()

# A11
HUB.reset()
ours = hashlib.sha256(b"our upload").hexdigest()
for label, reported, want_ok in (("foreign", "f" * 64, False), ("own", ours, True)):
    jid = HUB.new_job("done", results=[b"glTF" + b"x" * 200], inputs=[{"sha256": reported}])
    try:
        blobs = mesh.attach(jid, {"input_sha256s": [ours]}, since=time.time())
        ok = bool(blobs)
    except GatewayInputMismatchError:
        ok = False
    check(f"A11 mesh attach, {label} input hash → {'collected' if want_ok else 'refused'}",
          ok == want_ok)


# ═════════════════════════════════════════════════════════════════════════
print("\nB — HubJobLost is terminal in every layer")
calls = []


def lost_op(b):
    calls.append(b.name)
    raise HubJobLost("gone")


try:
    svc.run_on_backend(video, lost_op)
    check("B1 run_on_backend re-raises HubJobLost", False)
except HubJobLost:
    check("B1 run_on_backend re-raises HubJobLost (not BackendFailedError)", True)
except BackendFailedError:
    check("B1 run_on_backend re-raises HubJobLost (not BackendFailedError)", False)
check("B1 no cooldown", not video.in_cooldown())

from app.imagegen import routing  # noqa: E402

fake_route = routing.Route("video", video, 0, "hub-video", "hub-video", 0, [])
with patch.object(routing, "resolve_image_route", lambda *a, **k: fake_route):
    calls.clear()
    try:
        routing.run_routed("video", lambda b: svc.run_on_backend(b, lost_op))
    except HubJobLost:
        pass
check("B1 run_routed renders exactly once", calls == ["hub-video"], str(calls))

# B2
from app.core.task_queue import get_task_queue  # noqa: E402
tq = get_task_queue()


def lost_handler(payload):
    raise HubJobLost("job gone")


tq.register_handler("smoke_lost", lost_handler)
tq.start()
tid = tq.submit("smoke_lost", {}, max_retries=2)
for _ in range(200):
    if tq.task_status(tid) == "failed":
        break
    time.sleep(0.05)
with tq._connect() as conn:
    row = conn.execute("SELECT status, retry_count FROM tasks WHERE task_id=?", (tid,)).fetchone()
check("B2 task failed without retry", row["status"] == "failed" and row["retry_count"] == 0,
      dict(row).__repr__())

# B3
from app.core.improvements import engine  # noqa: E402


class _Type:
    def apply(self, candidate, params, task_id):
        raise HubJobLost("gone")


marks = []
with patch.object(engine.store, "get", lambda i: {"id": i, "type_id": "t", "params": {},
                                                  "failed_count": 0, "done_count": 0,
                                                  "mode": "standing", "status": "open"}), \
        patch.object(engine.store, "list_steps", lambda i: [{"candidate_key": "k", "candidate_label": "k",
                                                             "attempts": 0}]), \
        patch.object(engine.store, "mark_result", lambda *a, **k: marks.append(k.get("status"))), \
        patch.object(engine.store, "update", lambda *a, **k: None), \
        patch.object(engine.registry, "get", lambda t: _Type()):
    engine.handle_step({"improvement_id": "imp", "candidate_key": "k", "_task_id": ""})
check("B3 improvement step skipped after one attempt", marks == ["skipped"], str(marks))

# B4
from app.core import model3d  # noqa: E402
from app.core import face_retexture  # noqa: E402
from app.models.character import get_character_dir  # noqa: E402

char_dir = get_character_dir("demo", create=True)
(char_dir / "model3d" / "unrigged").mkdir(parents=True, exist_ok=True)
(char_dir / "model3d" / "unrigged" / "sigF.glb").write_bytes(b"glTF-original")


class _UpLost:
    face_calls = 0
    backends = []

    def upscale_image(self, *a, **k):
        raise HubJobLost("upscale job gone")

    def generate_face_retexture(self, *a, **k):
        _UpLost.face_calls += 1
        return {"ok": False}


with patch.object(service_mod, "get_image_service", lambda: _UpLost()), \
        patch.object(face_retexture, "check", lambda *a: {"problems": [], "ok": True}), \
        patch.object(face_retexture, "runnable", lambda *a: {"problems": [], "ok": True}), \
        patch.object(face_retexture, "photo_path", lambda *a: still()):
    try:
        model3d.face_retexture_model("demo", "sigF")
        check("B4 a lost upscale ends the face retexture", False, "no exception")
    except HubJobLost:
        check("B4 a lost upscale ends the face retexture", True)
check("B4 no face job submitted", _UpLost.face_calls == 0)
check("B4 no record left", not [o for o in hub_ops.list_ops() if o.kind == "face_retexture"])


# ═════════════════════════════════════════════════════════════════════════
print("\nC — pipelines, resumer, owners")
from app.core import task_queue as tq_mod  # noqa: E402


class StageBackend:
    """What a hub backend reports into a stage: a name and an api_url."""
    def __init__(self, name):
        self.name = name
        self.api_url = HUB_URL


class StubService:
    """Stage-aware stand-in for the image service: a FRESH stage submits
    (records a job, then — when ``die`` is set — the process dies); a stage
    with a recorded job of an earlier process is collected (``attach``)."""

    def __init__(self):
        self.mesh_calls = 0
        self.rig_calls = []
        self.die = set()
        self.backends = []

    def _stage(self, stage, name, write):
        verdict = stage.prepare() if stage is not None else "submit"
        if verdict == "submit":
            if stage is not None:
                stage.submitted(StageBackend("hub-mesh"), f"{name}-{uuid.uuid4().hex[:4]}", {})
            if name in self.die:
                self.die.discard(name)
                raise _Died()
        write()
        return verdict

    def generate_mesh(self, *, source_image_path, output_path, hub_stage=None, **kw):
        self.mesh_calls += 1
        self._stage(hub_stage, "mesh", lambda: Path(output_path).write_bytes(b"glTF-static"))
        return {"ok": True, "path": output_path, "format": "glb", "rig": "none",
                "backend": "hub-mesh", "filename": "m.glb", "stages": []}

    def generate_rig(self, *, mesh_path, output_path, rig, hub_stage=None, **kw):
        verdict = self._stage(hub_stage, "rig", lambda: Path(output_path).write_bytes(b"glTF-rigged"))
        self.rig_calls.append(verdict)
        return {"ok": True, "path": output_path, "format": "glb", "rig": rig,
                "backend": "hub-rig", "filename": "r.glb"}

    def list_mesh_backends(self):
        return [StageBackend("hub-mesh")]


def in_task(task_id):
    class _Ctx:
        def __enter__(self):
            tq_mod._worker_ctx.task_id = task_id

        def __exit__(self, *a):
            tq_mod._worker_ctx.task_id = ""
    return _Ctx()


tpose = Path(_TMP) / "tpose_sigA.png"
from PIL import Image  # noqa: E402
Image.new("RGB", (8, 8), (1, 2, 3)).save(tpose)
worn = {"sig": "sigA"}
ok_check = lambda *a, **k: {"ok": True, "errors": [], "warnings": []}  # noqa: E731
patches = [
    patch.object(model3d, "required_rig", lambda name: "mixamo"),
    patch.object(model3d, "current_outfit_state", lambda name: ({}, [], worn["sig"])),
    patch.object(model3d, "find_ref_image", lambda name, kind, sig: tpose if sig == "sigA" else None),
    patch("app.core.model_refs.enabled_tpose_views", lambda name: []),
    patch("app.core.mesh_source.validate_source", ok_check),
    patch("app.core.model_validate.validate_glb", ok_check),
    patch.object(model3d, "_auto_retexture", lambda *a, **k: None),
    patch.object(model3d, "_auto_normalize", lambda *a, **k: None),
    patch.object(model3d, "_auto_extension_rig", lambda *a, **k: {"ok": True}),
    patch.object(model3d, "_attach_measurement", lambda *a, **k: None),
    patch.object(model3d, "request_lod", lambda *a, **k: None),
    patch("app.core.extension_rig.extension_metadata", lambda name, **kw: {}),
]
for p in patches:
    p.start()

# C1
stub = StubService()
stub.die.add("rig")
with patch.object(service_mod, "get_image_service", lambda: stub), in_task("task_npc"):
    try:
        model3d.generate_for_current_outfit("demo")
    except _Died:
        pass
mdir = model3d.get_model3d_dir("demo")
rec = [o for o in hub_ops.list_ops() if o.kind == "character_mesh"]
check("C1 record left: mesh + checkpoint done, rig submitted, owner task_npc",
      len(rec) == 1 and rec[0].done("mesh") and rec[0].done("checkpoint")
      and rec[0].jobs().get("rig", {}).get("job_id") and rec[0].owner == "task_npc",
      str([(o.kind, o.state.get("done"), o.owner) for o in rec]))
check("C1 the static mesh is published as sigA.glb (the checkpoint)",
      (mdir / "sigA.glb").read_bytes() == b"glTF-static")
restart()
worn["sig"] = "sigB"
with patch.object(service_mod, "get_image_service", lambda: stub), in_task("task_npc"):
    res = model3d.generate_for_current_outfit("demo")
check("C1 resumed with the frozen signature", res.get("ok") and res.get("path", "").endswith("sigA.glb"),
      str(res))
check("C1 the rig was collected, not submitted again", stub.rig_calls == ["attach"], str(stub.rig_calls))
check("C1 no second mesh job, no T-pose lookup for sigB", stub.mesh_calls == 1, str(stub.mesh_calls))
check("C1 the rigged model is sigA.glb, nothing for sigB",
      (mdir / "sigA.glb").read_bytes() == b"glTF-rigged" and not list(mdir.glob("sigB.*")))
check("C1 record gone", not [o for o in hub_ops.list_ops() if o.kind == "character_mesh"])

# C1b — the same chain owned by a THREAD (admin button, auto-mesh hook, a
# task's hand-over): the resumer's registered entry continues it.
stub = StubService()
stub.die.add("rig")
worn["sig"] = "sigA"
with patch.object(service_mod, "get_image_service", lambda: stub):
    try:
        model3d.generate_for_current_outfit("demo", force=True)
    except _Died:
        pass
    rec = [o for o in hub_ops.list_ops() if o.kind == "character_mesh"]
    check("C1b thread record left with its rig job", len(rec) == 1 and rec[0].owner_kind == "thread"
          and rec[0].jobs().get("rig", {}).get("job_id"))
    # D3: while it is open, a second start of the same work is refused.
    try:
        model3d.generate_for_current_outfit("demo", force=True)
        check("C1b a second start raises HubOpBusy", False)
    except hub_ops.HubOpBusy:
        check("C1b a second start raises HubOpBusy (improvements: busy, no attempt)", True)
    restart()
    res = hub_ops.get_kind("character_mesh").resume(hub_ops.get(rec[0].op_id))
check("C1b the thread resume entry publishes (rig collected)",
      res.get("ok") and stub.rig_calls == ["attach"]
      and (mdir / "sigA.glb").read_bytes() == b"glTF-rigged", str(res))
check("C1b record gone", hub_ops.get(rec[0].op_id) is None)

# C2
from app.core import props  # noqa: E402
pid = props.create_prop(name="Crate")["id"]
renders = []


def fake_render(prop_id, *a, **k):
    renders.append(prop_id)
    props.save_source_image(prop_id, tpose.read_bytes(), 0, backend="fake", prompt="crate")
    return True


stub = StubService()
stub.die.add("mesh")
with patch.object(service_mod, "get_image_service", lambda: stub), \
        patch.object(props, "_render_source", fake_render), \
        patch.object(props, "_areas_after_landing", lambda *a, **k: None), \
        patch.object(props, "_autofill_slots", lambda *a, **k: None), \
        patch.object(props, "bake_surfaces", lambda *a, **k: None), \
        patch.object(props, "_retexture_file", lambda *a, **k: None), \
        in_task("task_prop"):
    try:
        props._generate(pid, "a crate", "", "", "hub-mesh", variant=0)
    except _Died:
        pass
    restart()
    gallery_before = len(props.model_gallery(pid, 0).files())
    res = props._generate(pid, "a crate", "", "", "hub-mesh", variant=0)
check("C2 the source was rendered once", renders == [pid], str(renders))
check("C2 the resume collected the mesh", res.get("ok") and stub.mesh_calls == 2, str(res))
check("C2 exactly one gallery file was added",
      len(props.model_gallery(pid, 0).files()) == gallery_before + 1,
      f"{gallery_before} -> {len(props.model_gallery(pid, 0).files())}")

# C3
import numpy as np  # noqa: E402
stub = StubService()
stub.die.add("rig")


class FaceStub(StubService):
    def upscale_image(self, image, **k):
        raise AssertionError("upscale off in this case")

    def generate_face_retexture(self, mesh_path, image, output_dir, params, backend, name,
                                hub_stage=None):
        self._stage(hub_stage, "face", lambda: None)
        out = Path(output_dir) / "corrected.glb"
        out.write_bytes(b"glTF-corrected")
        return {"ok": True, "path": str(out), "compare_path": "", "backend": "hub-face",
                "job_id": "face-1", "result_sha256": "x", "result_url": ""}


face = FaceStub()
face.die.add("rig")
(mdir / "unrigged" / "sigF.glb").write_bytes(b"glTF-original")
with patch.object(service_mod, "get_image_service", lambda: face), \
        patch.object(face_retexture, "check", lambda *a: {"problems": [], "ok": True}), \
        patch.object(face_retexture, "runnable", lambda *a: {"problems": [], "ok": True}), \
        patch.object(face_retexture, "photo_path", lambda *a: still()), \
        patch.object(face_retexture, "MAX_BYTES", 10 ** 9), \
        patch("app.core.mesh_source.validate_face_source",
              lambda raw, original=False: {"ok": True, "errors": [], "triangles": 1}), \
        patch.object(face_retexture, "bake_face_texture",
                     lambda orig, raw, replacement_masks=None: (
                         replacement_masks.append(np.ones((2, 2), dtype=bool)) or (b"glTF-baked", {"px": 4}))), \
        patch.object(face_retexture, "face_texture_preserved", lambda *a, **k: True), \
        patch.object(face_retexture, "prepare_snapshot", lambda *a, **k: None):
    try:
        model3d.face_retexture_model("demo", "sigF", upscale=False)
    except _Died:
        pass
    rec = [o for o in hub_ops.list_ops() if o.kind == "face_retexture"]
    durable = rec and all((rec[0].dir / p).is_file() for p in
                          ("source/sigF.glb", "source/sigF.json", "bake/mask.npy"))
    check("C3 corrected source, sidecar and mask are in the record's directory", bool(durable),
          str(rec and sorted(str(p.relative_to(rec[0].dir)) for p in rec[0].dir.rglob("*") if p.is_file())))
    check("C3 the corrected source is the BAKED one",
          bool(rec) and (rec[0].dir / "source/sigF.glb").read_bytes() == b"glTF-baked")
    restart()
    # A manual call does NOT adopt a thread's record (D3: the target is busy)…
    try:
        model3d.face_retexture_model("demo", "sigF", upscale=False)
        check("C3 a manual second start is refused while the record is open", False)
    except hub_ops.HubOpBusy as e:
        check("C3 a manual second start is refused while the record is open", True, str(e))
    # …the resumer's entry for the kind continues it.
    res = hub_ops.get_kind("face_retexture").resume(hub_ops.get(rec[0].op_id))
check("C3 resumed (the thread resumer's entry) and published",
      res.get("ok") and (mdir / "facefix" / "sigF.glb").read_bytes() == b"glTF-baked", str(res))
check("C3 rig collected, not resubmitted", face.rig_calls[-1:] == ["attach"], str(face.rig_calls))
for p in patches:
    p.stop()

# C4
HUB.reset()
svc, video, mesh = restart()
from app.core import location_model3d  # noqa: E402,F401  (registers its kinds)
thread_op = hub_ops.create("prop_mesh", "prop:smoke|0|x|", {
    "prop_id": "gone-prop", "variant": 0, "guard_key": "gone-prop|0|x|",
    "src": "inputs/none.png"}, label="Prop: gone")
jid_gone = HUB.new_job("running")
thread_op.update_state(lambda st: st.setdefault("jobs", {}).update(mesh={
    "phase": "submitted", "job_id": jid_gone, "backend": "hub-mesh", "api_url": HUB_URL,
    "submitted_at": utc_now().isoformat(timespec="seconds"), "pid": "dead-process"}))
task_id = tq.submit("smoke_paused", {}, queue_name="smoke-paused")
tq.pause_queue("smoke-paused")
with in_task(task_id):
    task_op = hub_ops.create("smoke_video", "c4-task", {"source": str(still())}, label="c4")
jid_task = HUB.new_job("done")
task_op.update_state(lambda st: st.setdefault("jobs", {}).update(video={
    "phase": "submitted", "job_id": jid_task, "backend": "hub-video", "api_url": HUB_URL,
    "submitted_at": utc_now().isoformat(timespec="seconds"), "attach_params": {}, "route": {},
    "pid": "dead-process"}))
failed_op = hub_ops.create("smoke_video", "c4-failed", {}, label="c4f")
hub_ops.fail(failed_op, "it broke", keep=True)
unknown_op = hub_ops.create("no_such_kind", "c4-unknown", {}, label="c4u")
jid_unknown = HUB.new_job("running")
unknown_op.update_state(lambda st: st.setdefault("jobs", {}).update(video={
    "phase": "submitted", "job_id": jid_unknown, "backend": "hub-video", "api_url": HUB_URL,
    "submitted_at": utc_now().isoformat(timespec="seconds"), "pid": "dead-process"}))
hub_ops.register_kind("smoke_video", resume=lambda op: hub_ops.resume(op, lambda: {"ok": True}),
                      track_type="smoke")
from app.core import props as props_mod  # noqa: E402
gate = threading.Event()
real_resume = hub_ops.get_kind("prop_mesh").resume
hub_ops.register_kind("prop_mesh", resume=lambda op: (gate.wait(5), real_resume(op))[1],
                      track_type="model3d_generation", reserve=props_mod._op_reserve)
handler_runs = []
tq.register_handler("smoke_paused", lambda payload: handler_runs.append(1))
counts = hub_ops.start_resumer()
check("C4 the thread record's guard is taken before start_resumer returns",
      "gone-prop|0|x|" in props_mod._generating)
gate.set()
for _ in range(100):
    task_rec = hub_ops.get(task_op.op_id)
    if task_rec and task_rec.jobs().get("video", {}).get("collected"):
        break
    time.sleep(0.05)
task_rec = hub_ops.get(task_op.op_id)
check("C4 the paused task's job is collected ahead (raw blob in the record)",
      task_rec is not None and (task_rec.dir / "jobs" / "video" / "0.bin").read_bytes() == VIDEO,
      str(task_rec and task_rec.jobs()))
check("C4 ... with 0 POSTs and its handler not run", HUB.posts == 0 and not handler_runs)
check("C4 the failed thread record was reported and deleted", hub_ops.get(failed_op.op_id) is None)
for _ in range(100):
    if jid_unknown in HUB.cancels:
        break
    time.sleep(0.05)
check("C4 an unknown kind is dropped and its hub job cancelled",
      hub_ops.get(unknown_op.op_id) is None and jid_unknown in HUB.cancels, str(HUB.cancels))
for _ in range(100):
    if hub_ops.get(thread_op.op_id) is None:
        break
    time.sleep(0.05)
for _ in range(100):
    if jid_gone in HUB.cancels:
        break
    time.sleep(0.05)
check("C4 the thread record was resumed (and ended: its prop is gone)",
      hub_ops.get(thread_op.op_id) is None and "gone-prop|0|x|" not in props_mod._generating)
check("C4 ... and the job of the deleted target was cancelled (§ 3.6)",
      jid_gone in HUB.cancels and HUB.gets.get(jid_gone, 0) == 0, str(HUB.cancels))
check("C4 counts", counts.get("resumed") == 1 and counts.get("collecting") == 1, str(counts))

# C4b — a two-stage record: the collection ahead picks the stage IN FLIGHT,
# never the finished stage whose job id the record still carries.
two = hub_ops.create("smoke_video", "c4b", {}, label="c4b")
two.update_state(lambda st: st.setdefault("jobs", {}).update(
    mesh={"phase": "submitted", "job_id": "job-mesh", "pid": "dead-process"},
    rig={"phase": "submitted", "job_id": "job-rig", "pid": "dead-process"}))
two.complete("mesh", {})
check("C4b only the rig stage is in flight", list(hub_ops._in_flight(hub_ops.get(two.op_id))) == ["rig"],
      str(list(hub_ops._in_flight(hub_ops.get(two.op_id)))))
hub_ops.delete(two)

# C5
from app.core import pose_animation as pa  # noqa: E402
ptid = "task_" + uuid.uuid4().hex[:12]
with tq._connect() as conn:
    conn.execute("INSERT INTO tasks (task_id, task_type, status, payload, created_at, queue_name) "
                 "VALUES (?, 'pose_animation', 'running', '{}', '2026-10-13T00:00:00', 'pose_animation')",
                 (ptid,))
    conn.commit()
tq.update_task_progress(ptid, {"phase": "hub", "hub_job": "job-x", "backend": "hub-anim"})
meta = {"generator": "g", "model_revision": "r", "motion_source": "reference_rig",
        "caption_style": "object", "segment_seconds": 2.0, "max_variants": 4,
        "license": "L", "credit": "C"}
rig_file = Path(_TMP) / "rig.fbx"
rig_file.write_bytes(b"Kaydara FBX Binary  rig")
with in_task(ptid):
    pop = hub_ops.create("pose_animation", f"pose_animation:{ptid}", {
        "mode": "entry", "key": "waving", "entry": {"group": "stand"}, "prepared_entry": None,
        "captions": ["wave"], "loop": False, "seed": 1, "backend": "hub-anim", "variants": 1,
        "meta": meta, "source_file": str(rig_file), "raw_text": ""}, label="Pose animation: waving")
pop.update_state(lambda st: st.setdefault("jobs", {}).update(animation={
    "phase": "submitted", "job_id": "job-x", "backend": "hub-anim", "api_url": HUB_URL,
    "submitted_at": utc_now().isoformat(timespec="seconds"), "pid": "dead-process"}))


class AnimStub:
    def __init__(self):
        self.verdicts = []

    def generate_mesh_animation(self, source, captions, seed, *, route, variants, hub_stage=None, **k):
        self.verdicts.append((route, hub_stage.prepare()))
        return {"ok": True, "blobs": [b"Kaydara FBX Binary  clip"], "results": [{"ok": True}],
                "backend": "hub-anim", "job_id": "job-x"}

    def resolve_animation_backend(self, name):
        raise AssertionError("no route lookup on an attach")


anim = AnimStub()
cancels = []
with patch.object(pa, "get_image_service", lambda: anim), \
        patch.object(pa, "prepare_motion", lambda *a, **k: (_ for _ in ()).throw(AssertionError("LLM"))), \
        patch.object(pa, "_cancel_lost_job", lambda *a: cancels.append(a)), \
        patch.object(pa.animation_clips, "reserve_kind", lambda key, pose_key: "waving"), \
        patch.object(pa, "_build_candidate", lambda *a, **k: {"ok": True, "reasons": [], "frames": 10,
                                                             "duration_s": 1.0, "fbx": "c.fbx",
                                                             "sidecar": "c.json"}), \
        in_task(ptid):
    result = pa._handle({"_task_id": ptid, "mode": "entry", "key": "waving"})
check("C5 attached (no route, no cancel, no LLM)", anim.verdicts == [(None, "attach")] and not cancels,
      str(anim.verdicts))
check("C5 ends awaiting_choice", result.get("state") == "awaiting_choice"
      and tq.get_task_progress(ptid).get("state") == "awaiting_choice", str(result))
check("C5 record gone", hub_ops.get(pop.op_id) is None)

# C6
HUB.reset()
svc, video, mesh = restart()
t6 = tq.submit("smoke_tomb", {}, queue_name="smoke-paused")
with in_task(t6):
    op6 = hub_ops.create("smoke_video", "c6", {"source": str(still())}, label="c6")
jid6 = HUB.new_job("404")
op6.update_state(lambda st: st.setdefault("jobs", {}).update(video={
    "phase": "submitted", "job_id": jid6, "backend": "hub-video", "api_url": HUB_URL,
    "submitted_at": utc_now().isoformat(timespec="seconds"), "attach_params": {}, "route": {},
    "pid": "dead-process"}))
op6 = hub_ops.get(op6.op_id)
try:
    render(svc, op6, Path(_TMP) / "out" / "c6.mp4")
except HubJobLost:
    pass
tomb = hub_ops.get(op6.op_id)
check("C6 the task's lost job stays as a tombstone", tomb is not None and tomb.status == "failed")
with in_task(t6):
    found = hub_ops.find_open("smoke_video", lambda i: True)
    try:
        hub_ops.raise_failed(found)
        check("C6 the re-run meets HubJobLost again", False)
    except HubJobLost:
        check("C6 the re-run meets HubJobLost again (no new job)", HUB.posts == 0)
hub_ops.release_task_ops(t6)
check("C6 the task's end deletes the tombstone", hub_ops.get(op6.op_id) is None)

# C7
resumed = []
hub_ops.register_kind("smoke_video", resume=lambda op: resumed.append(op.op_id) or {"ok": True},
                      track_type="smoke")
t7 = "task_" + uuid.uuid4().hex[:12]
with in_task(t7):
    op7 = hub_ops.create("smoke_video", "c7", {}, label="c7")
hub_ops.release_task_ops(t7)
for _ in range(50):
    if resumed:
        break
    time.sleep(0.05)
check("C7 a finished task hands its record to a thread", resumed == [op7.op_id]
      and hub_ops.get(op7.op_id).owner_kind == "thread")
hub_ops.delete(hub_ops.get(op7.op_id))
t7b = tq.submit("smoke_tomb", {}, queue_name="smoke-paused")
with in_task(t7b):
    op7b = hub_ops.create("smoke_video", "c7b", {}, label="c7b")
jid7 = HUB.new_job("running")
op7b.update_state(lambda st: st.setdefault("jobs", {}).update(video={
    "phase": "submitted", "job_id": jid7, "backend": "hub-video", "api_url": HUB_URL,
    "submitted_at": utc_now().isoformat(timespec="seconds"), "pid": "dead-process"}))
tq.cancel_task(t7b)
for _ in range(100):
    if jid7 in HUB.cancels and hub_ops.get(op7b.op_id) is None:
        break
    time.sleep(0.05)
check("C7 cancelling the pending task drops the record and cancels the hub job",
      hub_ops.get(op7b.op_id) is None and jid7 in HUB.cancels, str(HUB.cancels))

# C8
row = tq.track_start("smoke_track", "held", start_running=True)
tq.track_hold(row)
with tq._connect() as conn:
    conn.execute("UPDATE tasks SET started_at='2026-01-01T00:00:00+00:00', "
                 "created_at='2026-01-01T00:00:00+00:00' WHERE task_id=?", (row,))
    conn.commit()
tq._reap_stale_tracked_runtime()
check("C8 a held row survives the stale reaper", tq.task_status(row) == "running")
tq.track_cancel(row)
tq.track_finish_if_open(row, error="")
check("C8 a cancelled row is not overwritten", tq.task_status(row) == "cancelled")


SERVER.shutdown()
print()
if FAILURES:
    print(f"FAILED ({len(FAILURES)}):")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("all hub-job resume checks passed")
