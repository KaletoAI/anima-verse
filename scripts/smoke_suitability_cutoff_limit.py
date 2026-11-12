#!/usr/bin/env python3
"""The cut-off warning names the max_tokens actually sent; truncation never
keeps a run unsaved; an unsaved run says why BEFORE any cut-off warning.

Usage: ./.venv/bin/python scripts/smoke_suitability_cutoff_limit.py

Background (2026-11-12, flint q3 on Evo-X2): the job ran with Max tokens 900
and "Thinking up to" 1200 per group. 17 of 42 answers at the recommended
setting (thinking off — the model thought anyway) hit 900, and the detail view
said "cut off ... (Max tokens 900)" on top; the user read 1200 as the limit.
The run was not saved because llama-swap answered 27 of 87 requests with 502
(infra rule) — that line stood BELOW the cut-off warning, so the warning read
as the reason the run was missing.

Stub provider (local HTTP, driven by the real LLMClient): the user prompt CUT
always ends with finish_reason=length, FAST with stop. Each request records
the max_tokens it carried. Concurrency 1, every case once.

[A] Max tokens 1200, thinking off, cases CUT + FAST: 2 requests, both carry
    max_tokens 1200 on the wire. CUT's run records max_tokens_sent 1200 and
    fails "truncated (finish_reason=length)". Summary: truncated_runs 1,
    truncated_limits [1200], saved True — and the capability table holds the
    result with truncated_limits [1200] (truncation is the model's answer,
    not an outage).
[B] Same, helpers "Thinking up to" 300: CUT fails off, escalates to 300. The
    budgeted call sends max_tokens 300 (thought), is cut, continues with
    max_tokens 1200 (answer), is cut again -> that run's max_tokens_sent is
    1200 (the limit of the request whose finish_reason it reports). Wire
    sequence: 1200 (CUT off), 1200 (FAST off), 300, 1200. Stub answers carry
    no reasoning, so escalation stops there (thinking_ineffective).
[C] Detail view (static/admin/models.js in a node vm), a done job with
    saved False, not_saved_reason "27 of 87 requests failed at the provider",
    17 of 42 runs cut, truncated_limits [900], Max tokens 900, thinking up to
    1200: the "Not saved: 27 of 87" line comes BEFORE "17 of 42 answers were
    cut off", the warning says "sent with max_tokens 900" and that "Thinking
    up to" 1200 caps only the thinking.
[D] Fails on the old code (commit 136313bb, before this fix): its
    models.js renders the cut-off warning BEFORE the not-saved line and never
    explains the thinking cap; its model_suitability summary of [A] has no
    truncated_limits.
"""
import importlib.util
import json
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
BEFORE = "136313bb"

_tmp = tempfile.TemporaryDirectory(prefix="suit-cutoff-")
from app.core import paths  # noqa: E402
paths.init(Path(_tmp.name) / "world")
paths.init_instance(Path(_tmp.name) / "instance")

from app.core import model_capabilities as caps  # noqa: E402
from app.core import model_suitability as suit  # noqa: E402
from app.core.llm_client import LLMClient  # noqa: E402

wire = []


class Stub(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
        wire.append(body.get("max_tokens"))
        prompt = next(m["content"] for m in body["messages"] if m["role"] == "user")
        cut = prompt == "CUT"
        data = json.dumps({
            "id": "x", "object": "chat.completion", "created": 0, "model": "stub",
            "choices": [{"index": 0, "finish_reason": "length" if cut else "stop",
                         "message": {"role": "assistant", "content": "par" if cut else "ok"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


server = ThreadingHTTPServer(("127.0.0.1", 0), Stub)
server.daemon_threads = True
threading.Thread(target=server.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{server.server_address[1]}/v1"


def instance(task, model_full, **kwargs):
    def create_llm(**kw):
        return LLMClient(model="stub", api_key="x", api_base=BASE, temperature=kw.get("temperature", 0),
                         max_tokens=kw.get("max_tokens"), thinking=kw.get("thinking", False),
                         thinking_budget=kw.get("thinking_budget"))
    return SimpleNamespace(available=True, provider_name="Stub", create_llm=create_llm)


CASES = [dict(id=m.lower(), group="helpers", task="extraction", system="system", user=m, fmt="text", repeats=1)
         for m in ("CUT", "FAST")]


def stubs(module):
    return [patch("app.core.llm_router.create_llm_instance", side_effect=instance),
            patch.object(module, "load_cases", side_effect=lambda **kw: {"cases": list(CASES)}),
            patch.object(module, "runnable_cases", side_effect=lambda: list(CASES)),
            patch.object(caps, "_caps_path", return_value=Path(_tmp.name) / "caps.json"),
            patch.object(caps, "_outputs_path", return_value=Path(_tmp.name) / "outputs.json")]


def run(module, helpers_budget):
    wire.clear()
    settings = {"max_tokens": 1200, "thinking_max": {"tools": 0, "helpers": helpers_budget, "vision": 0}}
    events = list(module.iter_suitability_results("Stub::m", settings=settings, concurrency=1))
    assert events[-1]["type"] == "done", events[-1]
    return events[-1]["summary"], list(wire)


RENDER = r"""
const fs = require('fs'), vm = require('vm');
const elements = new Map();
const el = id => { if (!elements.has(id)) elements.set(id, {value:'', innerHTML:'', textContent:'', checked:false}); return elements.get(id); };
const ctx = {document:{getElementById:el}, setTimeout:()=>0, clearTimeout:()=>{}, console};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(0, 'utf8').replace(/loadData\(\);\s*suitInit\(\);\s*$/, ''), ctx);
const settings = {max_tokens: 900, thinking_max: {tools: 1200, helpers: 1200, vision: 1200}};
ctx.suitRenderJob({status: 'done', model: 'Evo::flint', settings, summary: {scorer_version: 'suitability-5',
    saved: false, infra: true, not_saved_reason: '27 of 87 requests failed at the provider', settings,
    truncated_runs: 17, total_runs: 42, truncated_limits: [900], checks: []}});
process.stdout.write(el('suitDetailStatus').innerHTML);
"""


def render(source: str) -> str:
    return subprocess.run(["node", "-e", RENDER], input=source, capture_output=True, text=True,
                          check=True, cwd=ROOT).stdout


def check_view(html: str) -> None:
    saved_at = html.find("Not saved: 27 of 87")
    cut_at = html.find("17 of 42 answers were cut off")
    assert saved_at >= 0 and cut_at >= 0, html
    assert saved_at < cut_at, "the not-saved reason must come before the cut-off warning"
    assert "sent with max_tokens 900" in html, html
    assert '"Thinking up to" 1200 caps only the thinking' in html, html


def main():
    managers = stubs(suit)
    for manager in managers:
        manager.start()
    try:
        caps.invalidate_cache()
        summary, sent = run(suit, 0)
        assert sent == [1200, 1200], sent
        cut = next(c for c in summary["checks"] if c["id"] == "cut")
        assert cut["runs"][0]["max_tokens_sent"] == 1200
        assert cut["ok"] is False and cut["detail"] == "truncated (finish_reason=length)"
        assert summary["truncated_runs"] == 1 and summary["truncated_limits"] == [1200]
        assert summary["saved"] is True
        stored = caps.get_all_suitability()["stub::m"]["tested_suitability"]
        assert stored["truncated_limits"] == [1200]
        print("[A] max_tokens 1200 reaches the wire, is recorded, and a cut-off run is saved OK")
        summary, sent = run(suit, 300)
        assert sent == [1200, 1200, 300, 1200], sent
        cut = next(c for c in summary["checks"] if c["id"] == "cut")
        staged = cut["stages"][-1]
        assert staged["budget"] == 300 and staged["budget_hits"] == 1, cut["stages"]
        assert summary["truncated_limits"] == [1200], summary["truncated_limits"]
        print("[B] thinking 300 caps the thought request; the answer request carries 1200 OK")
    finally:
        for manager in managers:
            manager.stop()
    check_view(render((ROOT / "static/admin/models.js").read_text()))
    print("[C] not-saved reason first; warning names the sent limit and the thinking cap OK")

    # [D] the old code
    old_js = subprocess.run(["git", "show", f"{BEFORE}:static/admin/models.js"], cwd=ROOT,
                            capture_output=True, text=True, check=True).stdout
    try:
        check_view(render(old_js))
    except AssertionError:
        pass
    else:
        raise AssertionError("old models.js passed the view check — the proof does not hold")
    source = subprocess.run(["git", "show", f"{BEFORE}:app/core/model_suitability.py"], cwd=ROOT,
                            capture_output=True, text=True, check=True).stdout
    old = importlib.util.module_from_spec(importlib.util.spec_from_loader("old_model_suitability", loader=None))
    exec(compile(source, "old_model_suitability.py", "exec"), old.__dict__)
    managers = stubs(old)
    for manager in managers:
        manager.start()
    try:
        summary, _ = run(old, 0)
        assert "truncated_limits" not in summary
    finally:
        for manager in managers:
            manager.stop()
    print(f"[D] {BEFORE}: warning above the not-saved line, no thinking-cap note, no recorded limit — fixed OK")
    server.shutdown()
    print("PASS: cut-off warning names the sent limit; truncation never blocks saving")


if __name__ == "__main__":
    main()
