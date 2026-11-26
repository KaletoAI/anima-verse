#!/usr/bin/env python3
"""Smoke: World Dev free mode — Effort and the Claude default budget.

Usage:  ./.venv/bin/python scripts/smoke_world_dev_effort.py

Plan docs/superpowers/plans/2026-11-25-world-dev-free-remove-schema-modes.md,
Task 2. The schema chat had an Effort picker (Anthropic output_config.effort)
and a 65536-token default budget for Claude models when neither the UI nor the
LLM routing named one; the free mode takes both over. A temp world (paths.init
BEFORE any world-DB import, STORAGE_DIR / INSTANCE_DIR / ANIMATION_CLIPS_DIR
temp dirs); no server, no network: Anthropic clients are constructed with a
dummy key and never call the API (the resume case overrides astream).

WHAT IS CHECKED, and where every expected value comes from
----------------------------------------------------------

(a) anthropic_budget(is_anthropic, requested, routed) — the rule moved from
    the schema chat: the per-reply cap the user sent wins; else the routing
    entry's; else, for a Claude model only, 65536 (thinking counts against
    max_tokens):
      (True, None, None) -> 65536   nothing named, Claude
      (True, None, 4096) -> 4096    routing entry
      (True, 2000, None) -> 2000    the user's cap
      (True, 2000, 4096) -> 2000    the user's cap beats the routing entry
      (False, None, None) -> None   not Claude: nothing invented
      (False, None, 4096) -> 4096   routing entry
    EFFORT_LEVELS == ("low", "medium", "high", "xhigh", "max") and
    ANTHROPIC_DEFAULT_MAX_TOKENS == 65536 (the Anthropic Messages API levels
    and the old route constant).
(b) apply_effort: on AnthropicLLMClient(model="demo", api_key="x") with
    "high" -> extra_params["output_config"] == {"effort": "high"} (merged by
    llm_client.merge_extra_params); with "" -> extra_params unchanged ({}, the
    constructor's default); on a non-Anthropic stub with extra_params {} and
    "high" -> still {} (other providers ignore effort).
(c) Route: a throwaway FastAPI app with only the world_dev router,
    require_admin overridden, the run manager's llm_factory returning a
    FakeLLM for "fake-model". The FakeLLM answers "Done." (no tool call): turn
    1 ends as a hard failure and the run closes itself as rolled_back, so the
    one-open-run rule does not 409 the next case.
      effort "high"  -> 200, run row effort "high"
      effort "bogus" -> 400 (D8), and the run count is unchanged
      no effort      -> 200, run row effort ""
(d) Factory wiring: llm_router.create_llm_instance is replaced by a stub that
    returns a stub instance (max_tokens as given below) whose create_llm()
    returns AnthropicLLMClient(model="demo", api_key="x").
      _default_llm_factory("demo", "", None), stub max_tokens None
          -> routed None -> 65536 on llm AND instance
      same, stub max_tokens 4096 -> routed 4096 -> 4096 on both
      _default_llm_factory("demo", "", 2000) (the stub then carries 2000, as
          create_llm_instance does with an explicit cap) -> 2000 on both
(e) Resume path: a RunManager whose 3-argument llm_factory records its calls
    and returns a fresh FakeAnthropic (an AnthropicLLMClient subclass whose
    astream plays a script) plus None. start(..., effort="high") with the script
    [create_location "Demo Effort", "Built."] -> awaiting_review, row effort
    "high", the start client carries output_config {"effort": "high"}. A NEW
    RunManager (restart simulation: no in-memory state) sends message "more";
    the factory is called once more with ("fake-model", "fake", None) and the
    client it returned carries output_config {"effort": "high"} — the
    message call names no effort, so it can only come from the run row.
(f) RunManager.start's own effort check (the route's 400 catches a bogus
    value first, so (c) never reaches it): a RunManager whose factory counts
    its calls; start(..., effort="bogus") raises ValueError, the factory was
    called 0 times (the check runs before the model is resolved) and the run
    count is unchanged. A direct create_run(..., effort=" HIGH ") stores
    "high" (normalised like start and the route); that row is then closed via
    wr.set_status(..., "rolled_back") so no open run is left behind.
"""
import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="smoke_wd_effort_"))
os.environ["STORAGE_DIR"] = str(STORAGE)
INSTANCE = Path(tempfile.mkdtemp(prefix="smoke_wd_effort_inst_"))
os.environ["INSTANCE_DIR"] = str(INSTANCE)
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="smoke_wd_effort_clips_")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
paths.init_instance(INSTANCE)
from app.core import config  # noqa: E402
config.load(STORAGE / "config.json")
from app.core import db  # noqa: E402
db.init_schema()

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core import llm_router  # noqa: E402
from app.core import world_dev_agent as wa  # noqa: E402
from app.core import world_dev_runs as wr  # noqa: E402
from app.core.auth_dependency import require_admin  # noqa: E402
from app.core.llm_client import AnthropicLLMClient, LLMChunk  # noqa: E402
from app.routes import world_dev as world_dev_route  # noqa: E402

FAILS = []


def check(label, cond, detail=None):
    print(("  ok   " if cond else "  FAIL ") + label
          + ("" if cond or detail is None else f"   -> {detail!r}"))
    if not cond:
        FAILS.append(label)


def section(name, fn):
    """Run one case; an exception (e.g. a missing function) is a failure."""
    print(name)
    try:
        fn()
    except Exception as e:  # noqa: BLE001 — reported as a failure
        check(f"{name} raised", False, f"{type(e).__name__}: {e}")


async def _active(llm_instance):
    return None


wa._chat_active = _active
wa._chat_done = lambda task_id: None


def create(name):
    return ('<tool name="create_location">{"data": {"name": "' + name + '", '
            '"rooms": [{"name": "Main"}]}}</tool>')


# ── (a) ──────────────────────────────────────────────────────────────────
def case_a():
    check("(a) EFFORT_LEVELS", wa.EFFORT_LEVELS == ("low", "medium", "high", "xhigh", "max"),
          wa.EFFORT_LEVELS)
    check("(a) ANTHROPIC_DEFAULT_MAX_TOKENS", wa.ANTHROPIC_DEFAULT_MAX_TOKENS == 65536)
    b = wa.anthropic_budget
    check("(a) Claude, nothing named -> 65536", b(True, None, None) == 65536, b(True, None, None))
    check("(a) Claude, routed 4096 -> 4096", b(True, None, 4096) == 4096)
    check("(a) Claude, requested 2000 -> 2000", b(True, 2000, None) == 2000)
    check("(a) Claude, requested beats routed", b(True, 2000, 4096) == 2000)
    check("(a) not Claude, nothing -> None", b(False, None, None) is None)
    check("(a) not Claude, routed 4096 -> 4096", b(False, None, 4096) == 4096)


# ── (b) ──────────────────────────────────────────────────────────────────
class _Stub:
    def __init__(self):
        self.extra_params = {}


def case_b():
    c = AnthropicLLMClient(model="demo", api_key="x")
    wa.apply_effort(c, "high")
    check("(b) Anthropic + high -> output_config.effort high",
          c.extra_params.get("output_config") == {"effort": "high"}, c.extra_params)
    c2 = AnthropicLLMClient(model="demo", api_key="x")
    wa.apply_effort(c2, "")
    check("(b) empty effort leaves extra_params unchanged", c2.extra_params == {}, c2.extra_params)
    s = _Stub()
    wa.apply_effort(s, "high")
    check("(b) non-Anthropic ignores effort", s.extra_params == {}, s.extra_params)


# ── (c) ──────────────────────────────────────────────────────────────────
class FakeLLM:
    async def astream(self, messages):
        yield LLMChunk(content="Done.")


def _route_factory(model, provider, max_tokens):
    return (FakeLLM(), None) if model == "fake-model" else None


def _run_count():
    return len(wr.list_runs()) if hasattr(wr, "list_runs") else None


def _settle_row(run_id, timeout=20.0):
    for _ in range(int(timeout / 0.02)):
        run = wr.get_run(run_id)
        if run and run["status"] != "running" and not wa.get_run_manager().is_busy(run_id):
            return run
        time.sleep(0.02)
    return wr.get_run(run_id)


def case_c():
    wa.get_run_manager().llm_factory = _route_factory
    app = FastAPI()
    app.include_router(world_dev_route.router)
    app.dependency_overrides[require_admin] = lambda: {"id": "u_admin", "role": "admin"}
    body = {"task": "Build a well", "model": "fake-model", "provider": "fake"}
    with TestClient(app) as c:
        r = c.post("/world-dev/free/start", json={**body, "effort": "high"})
        rid = r.json().get("run_id", "") if r.status_code == 200 else ""
        check("(c) effort high -> 200", r.status_code == 200 and rid, r.text)
        run = _settle_row(rid) if rid else None
        check("(c) row effort high", bool(run) and run.get("effort") == "high",
              run and run.get("effort"))
        check("(c) run closed (no open run left)", wr.open_run() is None, wr.open_run())

        before = _run_count()
        r = c.post("/world-dev/free/start", json={**body, "effort": "bogus"})
        check("(c) effort bogus -> 400", r.status_code == 400, (r.status_code, r.text))
        check("(c) bogus created no run row", _run_count() == before, (before, _run_count()))
        check("(c) bogus left no open run", wr.open_run() is None)

        r = c.post("/world-dev/free/start", json=body)
        rid = r.json().get("run_id", "") if r.status_code == 200 else ""
        check("(c) no effort -> 200", r.status_code == 200 and rid, r.text)
        run = _settle_row(rid) if rid else None
        check("(c) row effort ''", bool(run) and run.get("effort") == "",
              run and run.get("effort"))


# ── (d) ──────────────────────────────────────────────────────────────────
class _StubInstance:
    def __init__(self, max_tokens):
        self.max_tokens = max_tokens

    def create_llm(self):
        return AnthropicLLMClient(model="demo", api_key="x")


def case_d():
    real = llm_router.create_llm_instance
    routed = {"value": None}

    def fake_create(task="chat", model="", provider_name="", max_tokens=None, **kw):
        # create_llm_instance keeps the routing entry's value when max_tokens
        # is None and takes the explicit cap otherwise.
        return _StubInstance(max_tokens if max_tokens is not None else routed["value"])

    llm_router.create_llm_instance = fake_create
    try:
        for routed_value, requested, want in ((None, None, 65536), (4096, None, 4096),
                                              (None, 2000, 2000)):
            routed["value"] = routed_value
            res = wa._default_llm_factory("demo", "", requested)
            llm, inst = res if res else (None, None)
            check(f"(d) routed {routed_value}, requested {requested} -> {want} on both",
                  llm is not None and llm.max_tokens == want and inst.max_tokens == want,
                  (getattr(llm, "max_tokens", None), getattr(inst, "max_tokens", None)))
    finally:
        llm_router.create_llm_instance = real


# ── (e) ──────────────────────────────────────────────────────────────────
class FakeAnthropic(AnthropicLLMClient):
    def __init__(self, replies):
        super().__init__(model="demo", api_key="x")
        self.replies = list(replies)

    async def astream(self, messages):
        yield LLMChunk(content=self.replies.pop(0) if self.replies else "Done.")


async def _settle(rm, run_id, timeout=20.0):
    for _ in range(int(timeout / 0.02)):
        run = wr.get_run(run_id)
        if run["status"] != "running" and not rm.is_busy(run_id):
            return run
        await asyncio.sleep(0.02)
    raise AssertionError(f"run {run_id} still running")


def _manager(replies, calls, made):
    rm = wa.RunManager()

    def factory(model, provider, max_tokens):
        calls.append((model, provider, max_tokens))
        client = FakeAnthropic(replies)
        made.append(client)
        return client, None

    rm.llm_factory = factory
    return rm


async def _case_e():
    calls, made = [], []
    rm = _manager([create("Demo Effort"), "Built."], calls, made)
    run_id = await rm.start("build something", "fake-model", "fake", "u1", effort="high")
    run = await _settle(rm, run_id)
    check("(e) awaiting_review", run["status"] == "awaiting_review", (run["status"], run["note"]))
    check("(e) row effort high", run.get("effort") == "high", run.get("effort"))
    check("(e) start client carries effort high",
          made and made[0].extra_params.get("output_config") == {"effort": "high"},
          made and made[0].extra_params)
    calls2, made2 = [], []
    rm2 = _manager(["Nothing to add."], calls2, made2)
    await rm2.message(run_id, "more")
    await _settle(rm2, run_id)
    check("(e) restart re-resolve calls the factory once",
          calls2 == [("fake-model", "fake", None)], calls2)
    check("(e) re-resolved client carries effort high from the row",
          made2 and made2[0].extra_params.get("output_config") == {"effort": "high"},
          made2 and made2[0].extra_params)
    await rm2.accept(run_id)


def case_e():
    asyncio.run(_case_e())


# ── (f) ──────────────────────────────────────────────────────────────────
async def _case_f():
    calls = []
    rm = wa.RunManager()

    def factory(model, provider, max_tokens):
        calls.append((model, provider, max_tokens))
        return FakeLLM(), None

    rm.llm_factory = factory
    before = _run_count()
    raised = None
    try:
        await rm.start("build something", "fake-model", "fake", "u1", effort="bogus")
    except ValueError as e:
        raised = e
    check("(f) start effort bogus raises ValueError", raised is not None, raised)
    check("(f) factory called 0 times", calls == [], calls)
    check("(f) no new run row", _run_count() == before, (before, _run_count()))
    check("(f) no open run", wr.open_run() is None, wr.open_run())


def case_f():
    asyncio.run(_case_f())
    rid = wr.create_run("t", "m", "p", "u1", 5, 1000, None, " HIGH ")
    try:
        got = wr.get_run(rid).get("effort")
        check("(f) create_run normalises ' HIGH ' -> 'high'", got == "high", got)
    finally:
        wr.set_status(rid, "rolled_back")
    check("(f) normalisation row closed", wr.open_run() is None, wr.open_run())


section("(a) anthropic_budget", case_a)
section("(b) apply_effort", case_b)
section("(c) route", case_c)
section("(d) factory wiring", case_d)
section("(e) resume path", case_e)
section("(f) start effort check + create_run normalisation", case_f)

print()
if FAILS:
    print(f"FAILED: {len(FAILS)} check(s)")
    sys.exit(1)
print("all checks passed")
