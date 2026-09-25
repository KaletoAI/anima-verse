#!/usr/bin/env python3
"""Smoke run for collecting a finished gateway mesh job by its id afterwards.

No server, no gateway, no world content: the storage root is a temp dir, the
gateway is a stub behind ``requests.get``, and the service method runs against
a hand-built stand-in for the backend pool.

What is expected, derived by hand from the job protocol
(``app/imagegen/backends/_gateway_job.py``, mesh-client-spec § 1/§ 2) and the
feature's contract (``model3d.fetch_job_for_current_outfit``):

  id    — the admin pastes the id as the log prints it: "Job 466a4e41b73d".
          The prefix is dropped; only [A-Za-z0-9_-] (4..128 chars, starting
          alphanumeric) reaches the gateway URL, anything else is "" —
          "../x" must never become a path segment.
  view  — GET /v1/jobs/{id}: 404 = the gateway does not know the job
          ("unknown"); queued/running = nothing is downloaded, the progress is
          handed back; failed = its error text; done = every result file is
          downloaded, checked against its sha256 and handed up with its
          name/kind (a checksum mismatch discards the job: "error").
  rig   — the rig the job REPORTS decides what is stored (§ 2 rule 2): a
          mixamo job stores ONLY the GLB, its basecolor map is auxiliary. A
          job whose rig is not what the character needs is refused
          ("rig_mismatch") — a wrong-rig mesh binds unusably.
  gate  — each gateway is asked once even when several aliases share it; a
          gateway that does not know the job hands over to the next one.
  owner — the gateway checks the job's OWNER on every read (AI-Hub
          ``_require_job_owner``): a job of another gateway user answers 403
          "not your job". That is "forbidden", not "unknown" — the job exists,
          our key may not read it — and it ends the search like a hit.
  full  — the job view carries the full ``job_id``; when the gateway resolves
          a shortened id, the full one is what gets reported and stored.

Usage:  ./.venv/bin/python scripts/smoke_mesh_fetch_job.py
"""
import hashlib
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_TMP = tempfile.mkdtemp(prefix="smoke-fetch-job-")
from app.core import paths  # noqa: E402
paths.init(_TMP)

import app.imagegen.backends.openai_mesh as openai_mesh  # noqa: E402
from app.core.model3d import normalize_job_id  # noqa: E402
from app.imagegen.backends.openai_mesh import OpenAIMeshBackend  # noqa: E402
from app.imagegen.service import ImageService  # noqa: E402

FAILURES = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


# --- (a) job id normalisation ---------------------------------------------
print("\n(a) job id as pasted")
check("'Job 466a4e41b73d' -> bare id",
      normalize_job_id("Job 466a4e41b73d") == "466a4e41b73d")
check("surrounding blanks dropped",
      normalize_job_id("  466a4e41b73d \n") == "466a4e41b73d")
check("'job: abc_12-x' -> 'abc_12-x'",
      normalize_job_id("job: abc_12-x") == "abc_12-x")
check("'../etc' refused", normalize_job_id("../etc") == "")
check("slash inside refused", normalize_job_id("abcd/ef") == "")
check("3 chars refused (min 4)", normalize_job_id("abc") == "")
check("empty refused", normalize_job_id("") == "")


# --- (b) the job view, stubbed gateway --------------------------------------
class _Resp:
    def __init__(self, status: int, json_body=None, content: bytes = b""):
        self.status_code = status
        self._json = json_body
        self.content = content if content else (b"{}" if json_body is not None else b"")
        self.headers = {}

    def json(self):
        return self._json


GLB = b"glTF" + b"\0" * 200       # > 100 bytes: the download floor
PNG = b"\x89PNG" + b"\0" * 200
ROUTES = {}                       # url -> _Resp
CALLS = []


def _fake_get(url, headers=None, timeout=None):
    CALLS.append(url)
    return ROUTES.get(url, _Resp(404))


openai_mesh.requests.get = _fake_get


def mk_backend(name: str, api_url: str, rig: str = "mixamo") -> OpenAIMeshBackend:
    prefix = "SMOKE_FETCH_"
    os.environ[f"{prefix}MESH_RIG"] = rig
    b = OpenAIMeshBackend(name=name, api_url=api_url, cost=1,
                          env_prefix=prefix, model=name)
    b._alias_param_names = set()
    return b


GW = "http://gw.invalid"
b = mk_backend("Trellis2-Humanoid-Low", GW)

print("\n(b) job view")
r = b.fetch_job("nope1234")
check("404 -> unknown", r.get("status") == "unknown", str(r))

ROUTES[f"{GW}/v1/jobs/run12345"] = _Resp(200, {"status": "running",
                                                "progress": 0.42,
                                                "elapsed_s": 97})
CALLS.clear()
r = b.fetch_job("run12345")
check("running -> status running", r.get("status") == "running", str(r))
check("progress handed back", r.get("progress") == 0.42)
check("nothing downloaded while running",
      CALLS == [f"{GW}/v1/jobs/run12345"] and "blobs" not in r, str(CALLS))

ROUTES[f"{GW}/v1/jobs/fail1234"] = _Resp(200, {"status": "failed",
                                                "error": "node 12 exploded"})
r = b.fetch_job("fail1234")
check("failed -> error text", r.get("status") == "failed"
      and "node 12" in r.get("error", ""), str(r))

MAIN = "Kira-rabc123_00001_.glb"
BASE = "Kira-rabc123_00001__basecolor.png"
ROUTES[f"{GW}/v1/jobs/done1234"] = _Resp(200, {
    "status": "done", "rig": "mixamo", "model": "Trellis2-Humanoid-Low",
    "elapsed_s": 412,
    # alphabetical order: the basecolor name sorts after the main one here,
    # but position must not matter anyway
    "results": [
        {"n": 0, "url": "/v1/jobs/done1234/result/0", "name": MAIN,
         "kind": "model", "sha256": hashlib.sha256(GLB).hexdigest()},
        {"n": 1, "url": "/v1/jobs/done1234/result/1", "name": BASE,
         "kind": "image", "sha256": hashlib.sha256(PNG).hexdigest()},
    ]})
ROUTES[f"{GW}/v1/jobs/done1234/result/0"] = _Resp(200, content=GLB)
ROUTES[f"{GW}/v1/jobs/done1234/result/1"] = _Resp(200, content=PNG)
r = b.fetch_job("done1234")
check("done -> 2 blobs", r.get("status") == "done"
      and r.get("blobs") == [GLB, PNG], str({k: v for k, v in r.items() if k != "blobs"}))
check("file names handed up",
      [f["name"] for f in r.get("files") or []] == [MAIN, BASE])
check("job rig reported", r.get("rig") == "mixamo")

ROUTES[f"{GW}/v1/jobs/bad12345"] = _Resp(200, {
    "status": "done", "rig": "mixamo",
    "results": [{"n": 0, "url": "/v1/jobs/bad12345/result/0", "name": MAIN,
                 "kind": "model", "sha256": "0" * 64}]})
ROUTES[f"{GW}/v1/jobs/bad12345/result/0"] = _Resp(200, content=GLB)
r = b.fetch_job("bad12345")
check("sha256 mismatch -> error, no blobs",
      r.get("status") == "error" and "blobs" not in r, str(r))

ROUTES[f"{GW}/v1/jobs/foreign12"] = _Resp(403, {"detail": "not your job"})
r = b.fetch_job("foreign12")
check("403 -> forbidden, gateway reason kept",
      r.get("status") == "forbidden" and "not your job" in r.get("error", ""),
      str(r))

# a gateway that resolves the short form answers with the FULL id
FULL = "466a4e41b73d4e31a1ccb07c4ed31b12"
ROUTES[f"{GW}/v1/jobs/466a4e41b73d"] = _Resp(200, {"job_id": FULL,
                                                    "status": "running"})
r = b.fetch_job("466a4e41b73d")
check("short id asked -> full id reported", r.get("job_id") == FULL, str(r))


# --- (c) service: gateway choice, rig gate, storing -------------------------
print("\n(c) service.fetch_mesh_job")
GW2 = "http://gw2.invalid"
b_twin = mk_backend("Trellis2-Humanoid-High", GW)       # same gateway as b
b_other = mk_backend("Other-Humanoid", GW2)
b_generic = mk_backend("Trellis2-Generic-Low", GW, rig="generic")


class _Pool:
    """Stand-in for the ImageService instance: only what fetch_mesh_job reads."""
    _store_mesh_files = staticmethod(ImageService._store_mesh_files)

    def __init__(self, meshes):
        self.meshes = meshes

    def list_mesh_backends(self, rig=""):
        return list(self.meshes)

    def list_available_backends(self, media="image", **_kw):
        return list(self.meshes)

    def _wait_for_explicit_backend(self, name, media="image", **_kw):
        return next((m for m in self.meshes if m.name == name), None)


out_dir = Path(_TMP) / "out"
CALLS.clear()
# the TWIN alias answers for gw1 — the label must still name the alias the
# job view reports, not whichever sibling on that gateway was asked
pool = _Pool([b_other, b_twin, b])
res = ImageService.fetch_mesh_job(pool, "done1234",
                                  str(out_dir / "sig1.fbx"), rig="mixamo")
views = [c for c in CALLS if c.endswith("/v1/jobs/done1234")]
check("unknown on gw2 -> asked gw1 next, each gateway once",
      views == [f"{GW2}/v1/jobs/done1234", f"{GW}/v1/jobs/done1234"], str(views))
check("stored", res.get("status") == "stored", str(res))
stored = Path(res.get("path") or "/nonexistent")
check("model stored as .glb (suffix from the delivered name)",
      stored.name == "sig1.glb" and stored.read_bytes() == GLB, str(stored))
check("mixamo: basecolor NOT stored",
      not res.get("texture_path") and not (out_dir / "sig1.png").exists())
check("backend label = the alias the job names",
      res.get("backend") == "Trellis2-Humanoid-Low", str(res.get("backend")))

res = ImageService.fetch_mesh_job(pool, "done1234",
                                  str(out_dir / "sig2.fbx"), rig="generic")
check("mixamo job for a generic character -> rig_mismatch",
      res.get("status") == "rig_mismatch"
      and not (out_dir / "sig2.glb").exists(), str(res))

res = ImageService.fetch_mesh_job(pool, "run12345",
                                  str(out_dir / "sig3.fbx"), rig="mixamo")
check("running job -> running, nothing stored",
      res.get("status") == "running" and not list(out_dir.glob("sig3.*")),
      str(res))

CALLS.clear()
res = ImageService.fetch_mesh_job(_Pool([b, b_other]), "foreign12",
                                  str(out_dir / "sig5.fbx"), rig="mixamo")
check("forbidden ends the search (gw2 not asked)",
      res.get("status") == "forbidden"
      and not any(c.startswith(GW2) for c in CALLS), str(CALLS))

res = ImageService.fetch_mesh_job(_Pool([b_generic]), "zzzz9999",
                                  str(out_dir / "sig4.fbx"), rig="generic")
check("no gateway knows the job -> unknown", res.get("status") == "unknown",
      str(res))

shutil.rmtree(_TMP, ignore_errors=True)
print()
if FAILURES:
    print(f"FAILED: {len(FAILURES)} check(s)")
    sys.exit(1)
print("OK")
