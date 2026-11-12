#!/usr/bin/env python3
"""A model test never vanishes: a hung request fails its case, a dead provider
ends the run visibly, and every ended test stays listed until dismissed.

Usage: ./.venv/bin/python scripts/smoke_suitability_test_never_vanishes.py

Background (2026-11-12): two tools tests of a flint build on a llama-swap
provider (timeout 900 s) each had three requests hang; after ~15 min the
client timed out and llama-swap answered every later request with 502. Both
runs ended "done" but unsaved (infra rule) and dropped out of the queue list
ten minutes later — the user saw the test "simply disappear".

The provider here is a local stub HTTP server driven by the REAL LLMClient
(so the per-case timeout really travels through openai/httpx as a read
timeout). Its answer depends on the user prompt: FAST -> "ok" (stop), CUT ->
"par" (finish_reason=length), HANG -> no answer until the smoke ends, DOWN ->
HTTP 502. model_test.case_timeout_seconds is 1 s. Every case runs once, no
thinking stages (thinking_max 0), concurrency 1 — so requests go out one
after another and every count below follows from the case list alone.

[A] FAST, CUT, HANG: 3 requests. FAST passes; CUT fails "truncated
    (finish_reason=length)"; HANG fails "no answer within 1 s (request timed
    out)" — a failed case, NOT infra. Summary: requests 3, infra_runs 0,
    timed_out_runs 1, truncated_runs 1, score "1/3", saved True (no infra
    error). The run ends in < 6 s (1 s timeout + slack).
[B] HANG1, HANG2, HANG3, FAST: answer timeouts in a row 1, 2; 2 > concurrency
    1 -> abort after HANG2. Requests sent: exactly 2 (HANG3 and FAST are never
    sent). Last event: type "error", message starting "The provider stopped
    answering: 2 requests in a row got no answer within 1 s", carrying the
    two finished cases [HANG1, HANG2], both failed. Ends in < 8 s.
[C] FAST, DOWN: DOWN's 502 is an infrastructure error, so the run is done
    but unsaved, and says why: not_saved_reason starts "1 of 2 requests
    failed at the provider" and names "Error code: 502".
[D] Through the queue: [B] as job 1 -> status "error", error/outcome = the
    abort message, 2 checks kept; [C] as job 2 -> status "done", saved False,
    outcome starting "Not saved: 1 of 2 requests failed at the provider".
    The disk rows keep both as ended rows with that outcome. Moving both
    finished_at stamps two hours back and restarting: both load as the SAME
    ended status (not "interrupted"), and the jobs route still lists both
    (finished_ago_s >= 7200) with outcome and saved. dismiss_job: an unknown
    id -> False; each id -> True; the second dismiss -> False; afterwards the
    list and the disk are empty. The dismiss route declares require_admin.
[E] Fails on the old code (commit ffa02768, before this fix), loaded from
    ``git show ffa02768:app/core/model_suitability.py`` as its own module:
    (1) scenario [A] is still running after 6 s — the old client never got a
    per-case timeout, so HANG waits for the 120 s client default;
    (2) its _persist_queue writes zero rows for an ended "error" job — the
    restart forgot it.

No server, no world DB of a real world: storage, instance and the capability
files are temporary.
"""
import importlib.util
import inspect
import json
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
BEFORE = "ffa02768"

_tmp = tempfile.TemporaryDirectory(prefix="suit-vanish-")
from app.core import paths  # noqa: E402
paths.init(Path(_tmp.name) / "world")
paths.init_instance(Path(_tmp.name) / "instance")

from app.core import model_capabilities as caps  # noqa: E402
from app.core import model_suitability as suit  # noqa: E402
from app.core.llm_client import LLMClient  # noqa: E402

release = threading.Event()
requests_seen = []


class Stub(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        prompt = body["messages"][-1]["content"]
        requests_seen.append(prompt)
        if prompt.startswith("HANG"):
            release.wait(60)
        if prompt == "DOWN":
            payload, status = {"error": {"message": "upstream gone"}}, 502
        else:
            cut = prompt == "CUT"
            payload, status = {
                "id": "x", "object": "chat.completion", "created": 0, "model": "stub",
                "choices": [{"index": 0, "finish_reason": "length" if cut else "stop",
                             "message": {"role": "assistant", "content": "par" if cut else "ok"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}, 200
        data = json.dumps(payload).encode()
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except OSError:
            pass  # the client gave up (timeout) long ago


server = ThreadingHTTPServer(("127.0.0.1", 0), Stub)
server.daemon_threads = True
threading.Thread(target=server.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{server.server_address[1]}/v1"


def instance(task, model_full, **kwargs):
    def create_llm(**kw):
        # The test's per-case deadline arrives as request_timeout; without it
        # the client keeps its 120 s default (what the old code did).
        return LLMClient(model="stub", api_key="x", api_base=BASE, temperature=kw.get("temperature", 0),
                         max_tokens=kw.get("max_tokens"), request_timeout=kw.get("request_timeout", 120))
    return SimpleNamespace(available=True, provider_name="Stub", create_llm=create_llm)


current = {"cases": []}


def case(marker):
    return dict(id=marker.lower(), group="helpers", task="extraction", system="system",
                user=marker, fmt="text", repeats=1)


def config_get(key, default=None):
    return 1 if key == "model_test.case_timeout_seconds" else default


def stubs(module):
    return [patch("app.core.llm_router.create_llm_instance", side_effect=instance),
            patch.object(module, "load_cases", side_effect=lambda **kw: {"cases": list(current["cases"])}),
            patch.object(module, "runnable_cases", side_effect=lambda: list(current["cases"])),
            patch("app.core.config.get", side_effect=config_get),
            patch.object(caps, "_caps_path", return_value=Path(_tmp.name) / "caps.json"),
            patch.object(caps, "_outputs_path", return_value=Path(_tmp.name) / "outputs.json")]


SETTINGS = {"thinking_max": {"tools": 0, "helpers": 0, "vision": 0}}


def run(module, markers, limit):
    """All events of one run, the request prompts it sent, and its seconds."""
    current["cases"] = [case(m) for m in markers]
    requests_seen.clear()
    start = time.monotonic()
    events = list(module.iter_suitability_results("Stub::m", settings=SETTINGS, concurrency=1))
    elapsed = time.monotonic() - start
    assert elapsed < limit, f"run took {elapsed:.1f} s (limit {limit} s)"
    return events, list(requests_seen), elapsed


def wait_for(predicate, seconds=15):
    deadline = time.monotonic() + seconds
    while not predicate():
        assert time.monotonic() < deadline, "timed out waiting"
        time.sleep(.02)


def main():
    managers = stubs(suit)
    for manager in managers:
        manager.start()
    try:
        caps.invalidate_cache()
        # [A]
        events, sent, elapsed = run(suit, ["FAST", "CUT", "HANG"], 6)
        assert sent == ["FAST", "CUT", "HANG"], sent
        summary = events[-1]["summary"]
        assert events[-1]["type"] == "done"
        checks = {c["id"]: c for c in summary["checks"]}
        assert checks["fast"]["ok"] is True, checks["fast"]["detail"]
        assert checks["cut"]["ok"] is False and checks["cut"]["detail"] == "truncated (finish_reason=length)"
        assert checks["hang"]["ok"] is False and not checks["hang"]["infra"]
        assert checks["hang"]["detail"] == "no answer within 1 s (request timed out)", checks["hang"]["detail"]
        assert checks["hang"]["timed_out_runs"] == 1
        assert (summary["requests"], summary["infra_runs"], summary["timed_out_runs"], summary["truncated_runs"]) == (3, 0, 1, 1)
        assert summary["score"] == "1/3" and summary["saved"] is True, (summary["score"], summary["saved"])
        print(f"[A] hung request failed its case after {elapsed:.1f} s; truncation failed; run saved OK")

        # [B]
        events, sent, elapsed = run(suit, ["HANG1", "HANG2", "HANG3", "FAST"], 8)
        assert sent == ["HANG1", "HANG2"], sent
        last = events[-1]
        assert last["type"] == "error", last
        assert last["message"].startswith(
            "The provider stopped answering: 2 requests in a row got no answer within 1 s"), last["message"]
        assert [c["id"] for c in last["checks"]] == ["hang1", "hang2"]
        assert all(c["ok"] is False for c in last["checks"])
        print(f"[B] dead provider ends the run as an error after 2 requests ({elapsed:.1f} s) OK")

        # [C]
        events, sent, _ = run(suit, ["FAST", "DOWN"], 6)
        summary = events[-1]["summary"]
        assert events[-1]["type"] == "done" and summary["saved"] is False
        assert summary["not_saved_reason"].startswith("1 of 2 requests failed at the provider"), summary["not_saved_reason"]
        assert "Error code: 502" in summary["not_saved_reason"]
        print("[C] infra error: done, not saved, and the reason is reported OK")

        # [D]
        current["cases"] = [case(m) for m in ("HANG1", "HANG2", "HANG3", "FAST")]
        first = suit.enqueue_test("Stub::abort", settings=SETTINGS, concurrency=1)
        wait_for(lambda: suit.get_job(first["job_id"])["status"] not in ("queued", "running"))
        job = suit.get_job(first["job_id"])
        assert job["status"] == "error" and job["error"].startswith("The provider stopped answering"), job
        assert job["outcome"] == job["error"] and len(job["checks"]) == 2
        wait_for(lambda: not suit._ACTIVE_PROVIDERS)
        current["cases"] = [case(m) for m in ("FAST", "DOWN")]
        second = suit.enqueue_test("Stub::down", settings=SETTINGS, concurrency=1)
        wait_for(lambda: suit.get_job(second["job_id"])["status"] not in ("queued", "running"))
        wait_for(lambda: not suit._ACTIVE_PROVIDERS)
        job = suit.get_job(second["job_id"])
        assert job["status"] == "done" and job["saved"] is False
        assert job["outcome"].startswith("Not saved: 1 of 2 requests failed at the provider"), job["outcome"]
        target = paths.get_instance_dir() / "suitability_queue.json"
        rows = json.loads(target.read_text())["jobs"]
        assert [(r["status"], r["outcome"][:12]) for r in rows] == [("error", "The provider"), ("done", "Not saved: 1")], rows
        from app.core.timeutils import utc_now
        from datetime import timedelta
        earlier = (utc_now() - timedelta(hours=2)).isoformat()
        for row in rows:
            row["finished_at"] = earlier
        target.write_text(json.dumps({"jobs": rows}))
        suit._reset_for_tests()
        assert [j["status"] for j in suit.list_jobs()] == ["error", "done"]
        from app.routes import admin_settings as routes
        from app.core.auth_dependency import require_admin
        listed = routes.llm_suitability_test_jobs(user={})["jobs"]
        assert [(j["job_id"], j["status"], j["saved"]) for j in listed] == [
            (first["job_id"], "error", False), (second["job_id"], "done", False)], listed
        assert all(j["finished_ago_s"] >= 7200 and j["outcome"] for j in listed)
        assert inspect.signature(routes.llm_suitability_dismiss).parameters["user"].default.dependency is require_admin
        assert suit.dismiss_job("missing") is False
        assert suit.dismiss_job(first["job_id"]) and suit.dismiss_job(second["job_id"])
        assert suit.dismiss_job(first["job_id"]) is False
        assert suit.list_jobs() == [] and json.loads(target.read_text())["jobs"] == []
        print("[D] ended jobs keep status + reason across a restart and leave only by dismiss OK")
    finally:
        for manager in managers:
            manager.stop()

    # [E] the old code, as its own module
    source = subprocess.run(["git", "show", f"{BEFORE}:app/core/model_suitability.py"], cwd=ROOT,
                            capture_output=True, text=True, check=True).stdout
    spec = importlib.util.spec_from_loader("old_model_suitability", loader=None)
    old = importlib.util.module_from_spec(spec)
    exec(compile(source, "old_model_suitability.py", "exec"), old.__dict__)
    managers = stubs(old)
    for manager in managers:
        manager.start()
    try:
        current["cases"] = [case(m) for m in ("FAST", "CUT", "HANG")]
        finished = threading.Event()
        threading.Thread(target=lambda: (list(old.iter_suitability_results(
            "Stub::m", settings=SETTINGS, concurrency=1)), finished.set()), daemon=True).start()
        assert not finished.wait(6), "old code finished — the proof does not hold"
        release.set()  # let the old run end
        assert finished.wait(15)
        old._JOBS["x"] = {"job_id": "x", "model": "Stub::m", "provider": "Stub", "kind": "tools",
                          "settings": suit.validate_settings(SETTINGS), "concurrency": 1, "status": "error",
                          "enqueued_at": "2026-11-12T10:00:00+00:00", "_cancel": threading.Event()}
        old._persist_queue()
        assert json.loads((paths.get_instance_dir() / "suitability_queue.json").read_text())["jobs"] == []
        print(f"[E] {BEFORE}: the hung request still blocked the run after 6 s, and an ended job "
              "was dropped from disk — both fixed OK")
    finally:
        release.set()
        for manager in managers:
            manager.stop()
    server.shutdown()
    print("PASS: a model test never vanishes")


if __name__ == "__main__":
    main()
