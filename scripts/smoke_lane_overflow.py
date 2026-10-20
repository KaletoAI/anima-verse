#!/usr/bin/env python3
"""Lane overflow primitives, without a server, LLM or network.

Usage: ./.venv/bin/python scripts/smoke_lane_overflow.py

Section A expectations, derived by hand:
A1 An unknown pool has no lanes or waiters: not saturated, not created.
A2 With one lane, busy=1 and waiting=0 is not saturated; parking one
   waiter gives busy=1 of 1 and waiting=1 >= 1, hence saturated.
A3 Two P/m -> Q/n moves add 2 outgoing and 2 incoming, with the opposite
   counters and an untouched pool at 0. Noting creates no pools. Reset
   removes both pools and counters, so recreated pools report 0 again.
A4 Leaving P/m then Q/n gives two distinct left pools and first origin P/m;
   the frozen original stays empty, and leaving P/m again adds nothing.
A5 thought and storyteller are background; chat_stream and npc_talk are chat.
A6 The threshold defaults to 60 seconds, accepts_overflow to true. The live
   threshold follows config changes to 17 and 0; 0 must stay 0 (off).
A7 Typed wait/overflow exceptions retain the supplied arrival=10, wait=60,
   target and immutable overflow state for the later callers.

Section B expectations, derived by hand:
B1 Free A is first. B2 A has 1 busy lane and 1 waiter (1 >= 1);
B rejects overflow, so C wins only with opt-in; calls at system times
100 and 159.9 log once; at 160 (60 s elapsed) the second log is allowed.
B3 C busy leaves no target. B4 Chat stays on A. B5 Threshold 0 disables
both paths. B6 Excluding A leaves C; excluding A+C leaves no target.
B7 B has 2 lanes: 1 busy, 1 chat-hot for 10 < 120 s, hence 0 free
for background under R4; C busy also has 0. B8 Overrides stay pinned.
B9 An unrouted thought child borrows thought's chain and task identity.
B10 Explanation switches are [true, false, true], one per entry; disabled,
missing, unavailable and cooled-down C leaves no usable target.

Section C expectations, derived by hand (real clock for thread plumbing):
C1 One CHAT blocker occupies the only lane. Cancellation at 0.2 s removes
   the waiter within one <=5 s slice (6 s deadline). After release and 1 s,
   busy=0, registrations=0, queue unpaused and serialize gate unclaimed.
C2 Grant then cancel leaves one orphan; closing it returns busy/tasks to 0.
C3 A 0.3 s budget from the supplied arrival expires with that same stamp,
   waiting=0, no registration, no queue pause and no gate claim.
C4 With a fake clock, 62 s = 12 slices of 5 s + 2 s, one wait log at
   60 s and 13 stale checks. Without cancel/budget, nested waits still use
   60-s slices: three timeouts log two WARNINGs then one ERROR.
"""
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def section_a():
    from app.core import config, llm_lanes as lanes
    from app.core.config_schema import SECTIONS

    clock = lambda: 10.0
    manager = lanes.LaneManager(now=clock, lane_count=lambda _key: 1)
    assert manager.pool_saturated("P/m") is False
    assert "P/m" not in manager.snapshot()["pools"]
    print("PASS A1 unknown pool")

    held = manager.acquire_lane("P/m", "chat:demo", lanes.Priority.CHAT, timeout=0)
    thread = None
    errors = []

    def wait():
        try:
            handle = manager.acquire_lane("P/m", "chat:other", lanes.Priority.CHAT, timeout=None)
            handle.release()
        except Exception as exc:
            errors.append(exc)

    try:
        assert manager.pool_saturated("P/m") is False
        thread = threading.Thread(target=wait, daemon=True)
        thread.start()
        deadline = time.monotonic() + 3
        while manager.snapshot()["pools"]["P/m"]["waiting"] != 1:
            assert time.monotonic() < deadline, "waiter did not park"
            time.sleep(0.01)
        assert manager.pool_saturated("P/m") is True
        print("PASS A2 saturation")
    finally:
        held.release()
        if thread is not None:
            thread.join(3)
            assert not thread.is_alive(), "waiter did not finish"
        assert not errors, errors

    manager.note_overflow("P/m", "Q/n")
    manager.note_overflow("P/m", "Q/n")
    assert "Q/n" not in manager.snapshot()["pools"]
    for pool in ("Q/n", "R/o"):
        manager.acquire_lane(pool, "chat:demo", timeout=0).release()
    pools = manager.snapshot()["pools"]
    assert (pools["P/m"]["overflowed_out"], pools["P/m"]["overflowed_in"]) == (2, 0)
    assert (pools["Q/n"]["overflowed_out"], pools["Q/n"]["overflowed_in"]) == (0, 2)
    assert (pools["R/o"]["overflowed_out"], pools["R/o"]["overflowed_in"]) == (0, 0)
    manager.reset()
    for pool in ("P/m", "Q/n"):
        manager.acquire_lane(pool, "chat:demo", timeout=0).release()
        state = manager.snapshot()["pools"][pool]
        assert (state["overflowed_out"], state["overflowed_in"]) == (0, 0)
    print("PASS A3 overflow counters and reset")

    original = lanes.Overflow()
    overflow = original.leaving("P/m").leaving("Q/n")
    assert overflow.left == frozenset({"P/m", "Q/n"})
    assert overflow.origin == "P/m"
    assert original.left == frozenset() and original.origin == ""
    assert overflow.leaving("P/m") == overflow
    print("PASS A4 overflow history")

    for task, expected in (("thought", True), ("chat_stream", False),
                           ("npc_talk", False), ("storyteller", True)):
        assert lanes.is_background(task) is expected, task
    print("PASS A5 background classes")

    assert lanes.LaneRules().overflow_after == 60.0
    schema = SECTIONS["lanes"]
    assert schema["scope"] == "instance"
    field = schema["fields"]["overflow_after_seconds"]
    assert (field["type"], field["default"], field["min"], field["max"]) == ("int", 60, 0, 3600)
    routing = SECTIONS["llm_routing"]
    assert routing["fields"]["accepts_overflow"]["default"] is True
    page = next(page for page in routing["pages"] if page["id"] == "llms")
    fields = page["fields"]
    assert fields[fields.index("max_concurrent") + 1] == "accepts_overflow"
    for value in (17, 0):
        with patch.object(config, "get_section", return_value={"overflow_after_seconds": value}):
            assert lanes.configured_lane_rules().overflow_after == float(value)
    print("PASS A6 config and schema")

    expired = lanes.LaneWaitExpired(10.0)
    assert expired.arrived == 10.0
    assert isinstance(lanes.LaneWaitCancelled(), Exception)
    target = object()
    moved = lanes.LaneOverflow(target, overflow, 60.0)
    assert moved.target is target and moved.overflow is overflow
    assert moved.waited_s == 60.0
    print("PASS A7 typed exceptions")


def section_b():
    from contextlib import ExitStack
    from types import SimpleNamespace
    from app.core import llm_lanes as lanes, llm_router as router

    now = [100.0]
    manager = lanes.LaneManager(now=lambda: now[0],
        lane_count=lambda key: 2 if key == "B/b" else 1, rules=lanes.LaneRules)
    routing = [{"provider": p, "model": p.lower(), "tasks": [
        {"task": "thought", "order": i}, {"task": "chat_stream", "order": i}]}
        for i, p in enumerate("ABC", 1)]
    routing[1]["accepts_overflow"] = False
    routing[1]["tasks"] = [{"task": "thought", "order": 2}]
    providers = {p: SimpleNamespace(available=True, type="openai", api_base="", api_key="") for p in "ABC"}
    held, errors = [], []
    thread = None
    original_override = router._resolve_character_override

    def wait():
        try:
            manager.acquire_lane("A/a", "chat:waiter", lanes.Priority.CHAT).release()
        except Exception as exc:
            errors.append(exc)

    with ExitStack() as stack:
        for obj, name, value in (
            (lanes, "_manager", manager), (lanes, "configured_lane_rules", lanes.LaneRules),
            (router, "_load_routing", lambda: routing),
            (router, "get_provider_manager", lambda: SimpleNamespace(get_provider=providers.get)),
            (router, "disabled_providers", lambda: set()),
            (router, "_model_cooled_down", lambda p, m: False)):
            stack.enter_context(patch.object(obj, name, value))
        stack.enter_context(patch("app.core.llm_task_state.is_enabled", return_value=True))
        stack.enter_context(patch.object(router, "_resolve_character_override", return_value=None))
        try:
            assert router.resolve_llm("thought", overflow=True).provider_name == "A"
            print("PASS B1 regular first choice")
            held.append(manager.acquire_lane("A/a", "chat:blocker", lanes.Priority.CHAT, timeout=0))
            thread = threading.Thread(target=wait, daemon=True)
            thread.start()
            deadline = time.monotonic() + 3
            while not manager.pool_saturated("A/a"):
                assert time.monotonic() < deadline, "waiter did not park"
                time.sleep(0.01)
            with patch.object(router, "_OVERFLOW_LOGGED", {}), patch.object(router.logger, "info") as log:
                with patch.object(router.time, "monotonic", side_effect=[100.0, 159.9, 160.0]):
                    for expected_logs in (1, 1, 2):
                        assert router.resolve_llm("thought", overflow=True).provider_name == "C"
                        assert log.call_count == expected_logs
            assert router.resolve_llm("thought").provider_name == "A"
            print("PASS B2 saturated skip and rate limit")
            c = manager.acquire_lane("C/c", "thought:blocker", timeout=0)
            held.append(c)
            assert router.resolve_llm("thought", overflow=True).provider_name == "A"
            print("PASS B3 no free target")
            c.release()
            held.remove(c)
            assert router.resolve_llm("chat_stream", overflow=True).provider_name == "A"
            assert router.overflow_target("chat_stream") is None
            print("PASS B4 chat never moves")
            with patch.object(lanes, "configured_lane_rules", return_value=lanes.LaneRules(overflow_after=0)):
                assert router.resolve_llm("thought", overflow=True).provider_name == "A"
                assert router.overflow_target("thought", exclude_pools={"A/a"}) is None
            print("PASS B5 overflow off")
            assert router.overflow_target("thought", exclude_pools={"A/a"}).provider_name == "C"
            assert router.overflow_target("thought", exclude_pools={"A/a", "C/c"}) is None
            print("PASS B6 excluded pools")
            routing[1]["accepts_overflow"] = True
            held.append(manager.acquire_lane("B/b", "thought:blocker", timeout=0))
            manager.acquire_lane("B/b", "chat:demo", lanes.Priority.CHAT, timeout=0).release()
            now[0] += 10
            held.append(manager.acquire_lane("C/c", "thought:blocker", timeout=0))
            assert manager.free_lanes("B/b", lanes.cache_key_for("thought", "demo"), lanes.lane_priority_for("thought")) == 0
            assert router.overflow_target("thought", "demo", exclude_pools={"A/a"}) is None
            print("PASS B7 conversation hold")
            pinned = router.LLMInstance("A", "a", pinned=True)
            with patch.object(router, "_resolve_character_override", return_value=pinned):
                assert router.resolve_llm("thought", "demo", overflow=True) is pinned
                assert pinned.pinned is True
            with patch("app.models.character.get_character_config", return_value={"llm_routing_overrides": {"thought": "A::a"}}), patch.object(router, "get_llm_instance_by_name", return_value=router.LLMInstance("A", "a", _provider=providers["A"])):
                assert original_override("thought", "demo").pinned is True
            print("PASS B8 pinned override")
            for handle in held[1:]:
                handle.release()
            del held[1:]
            routing[1]["accepts_overflow"] = False
            alt = router.overflow_target("thought_child", exclude_pools={"A/a"})
            assert alt.provider_name == "C" and alt.tasks == ["thought"]
            assert router.resolve_llm("thought_child", overflow=True).provider_name == "C"
            print("PASS B9 fallback chain")
            explanation = router.explain_routing({"llm_routing": routing}, provider_lookup=providers.get,
                cooled_down=lambda p, m: False, disabled=set(), runtime_disabled=set())
            chain = next(t for t in explanation["tasks"] if t["task"] == "thought")["chain"]
            assert [e["accepts_overflow"] for e in chain] == [True, False, True]
            for change in ({"enabled": False}, {"provider": "missing"}):
                with patch.dict(routing[2], change):
                    assert router.overflow_target("thought", exclude_pools={"A/a"}) is None
            with patch.object(providers["C"], "available", False):
                assert router.overflow_target("thought", exclude_pools={"A/a"}) is None
            with patch.object(router, "_model_cooled_down", side_effect=lambda p, m: p == "C"):
                assert router.overflow_target("thought", exclude_pools={"A/a"}) is None
            with patch.object(router, "disabled_providers", return_value={"C"}):
                assert router.overflow_target("thought", exclude_pools={"A/a"}) is None
            print("PASS B10 explanation and unusable targets")
        finally:
            for handle in reversed(held):
                handle.release()
            if thread is not None:
                thread.join(3)
                assert not thread.is_alive(), "waiter did not finish"
            assert not errors, errors


def section_c():
    import asyncio
    import os
    from contextlib import ExitStack
    from types import SimpleNamespace
    from app.core import paths, llm_lanes as lanes

    with tempfile.TemporaryDirectory(prefix="lane-c-") as root, ExitStack() as stack:
        # Copy the integration smoke's storage/log/DB isolation before imports.
        stack.enter_context(patch.dict(os.environ, {"ANIMATION_CLIPS_DIR": root}))
        paths.init(root)
        from app.core import provider_manager as pm_mod, provider_queue as pq_mod, llm_queue as lq_mod
        from app.core.llm_queue import get_llm_queue
        from app.core.provider import Provider
        from app.utils import llm_logger, llm_stats
        stack.enter_context(patch.object(llm_logger, "LOG_DIR", Path(root)))
        stack.enter_context(patch.object(llm_logger, "LOG_FILE", Path(root) / "llm_calls.jsonl"))
        stack.enter_context(patch.object(pq_mod, "_attach_duration_estimate", lambda task: None))
        stack.enter_context(patch.object(llm_stats, "record_call", lambda *a, **kw: None))
        manager = lanes.LaneManager(lane_count=lambda key: 1,
            rules=lambda: lanes.LaneRules(affinity_wait=0, conversation_hold=0))
        stack.enter_context(patch.object(lanes, "_manager", manager))
        provider = Provider(name="P", type="openai", api_base="http://stub",
                            api_key="", max_concurrent=1, timeout=30)
        queue = pq_mod.ProviderQueue(provider, queue_name="P", max_concurrent=1,
                                    chat_pause_enabled=False, serialize_group="")
        pm = pm_mod.ProviderManager()
        pm.providers["P"] = provider
        pm.channels["P"] = queue
        pm._queues["P"] = queue
        stack.enter_context(patch.object(pm_mod, "_provider_manager", pm))
        facade = get_llm_queue()
        instance = SimpleNamespace(provider_name="P", model="m")
        gate = threading.Semaphore(1)
        queue._serialize_gate = gate
        def pool():
            return manager.snapshot()["pools"]["P/m"]
        def clean():
            assert queue._chat_tasks == {} and queue._chat_lanes == {}
            assert queue._chat_active.is_set() and not queue._holds_serialize_gate
            assert gate.acquire(blocking=False), "serialize gate claimed"
            gate.release()

        blocker = manager.acquire_lane("P/m", "chat:blocker", lanes.Priority.CHAT, timeout=0)
        async def cancelled_wait():
            pending = asyncio.create_task(facade.register_chat_active_async(
                "demo", instance, task_type="thought"))
            await asyncio.sleep(0.2)
            assert pool()["waiting"] == 1
            pending.cancel()
            try:
                await pending
            except asyncio.CancelledError:
                pass
            deadline = time.monotonic() + 6
            while pool()["waiting"]:
                if time.monotonic() >= deadline:
                    blocker.release()
                    await asyncio.sleep(0.2)
                    raise AssertionError("cancelled waiter still parked")
                await asyncio.sleep(0.01)
            clean()
        try:
            with patch.object(pq_mod.logger, "handle") as queue_log, \
                    patch.object(lq_mod.logger, "handle") as facade_log:
                asyncio.run(cancelled_wait())
                assert all(call.args[0].levelno <= 10
                           for log in (queue_log, facade_log)
                           for call in log.call_args_list), "cancelled wait logged above DEBUG"
        finally:
            blocker.release()
        time.sleep(1)
        assert pool()["busy"] == 0
        clean()
        print("PASS C1 cancelled wait leaves no registration or lane")

        async def granted_race():
            original = facade.register_chat_active
            caller = None
            loop = asyncio.get_running_loop()
            def grant_then_cancel(*args, **kwargs):
                task_id = original(*args, **kwargs)
                # Cancel before to_thread delivers the already granted id.
                loop.call_soon_threadsafe(caller.cancel)
                return task_id
            with patch.object(facade, "register_chat_active", grant_then_cancel):
                caller = asyncio.create_task(facade.register_chat_active_async(
                    "demo", instance, task_type="thought"))
                try:
                    await caller
                    raise AssertionError("race did not cancel caller")
                except asyncio.CancelledError:
                    pass
                deadline = time.monotonic() + 3
                while queue._chat_tasks:
                    assert time.monotonic() < deadline, "orphan not closed"
                    await asyncio.sleep(0.01)
                await asyncio.sleep(0)
            assert pool()["busy"] == 0
            clean()
        asyncio.run(granted_race())
        print("PASS C2 granted lane is closed after cancellation race")

        blocker = manager.acquire_lane("P/m", "chat:blocker", lanes.Priority.CHAT, timeout=0)
        arrived = manager.now()
        try:
            try:
                queue.register_chat_active("demo", model="m", task_type="thought",
                                           max_wait=0.3, arrived=arrived)
                raise AssertionError("bounded wait registered")
            except lanes.LaneWaitExpired as exc:
                assert exc.arrived == arrived
            assert 0.3 <= manager.now() - arrived < 1.0
            assert pool()["waiting"] == 0 and pool()["busy"] == 1
            clean()
        finally:
            blocker.release()
        print("PASS C3 bounded wait preserves arrival and registers nothing")

        # Pin cadence and slice lengths without spending a minute on a clock.
        class SlicedManager:
            def __init__(self, failures):
                self.stamp = 100.0
                self.failures = failures
                self.timeouts = []
            def now(self):
                return self.stamp
            def sync_from_config(self, key):
                pass
            def acquire_lane(self, *args, timeout, **kwargs):
                self.timeouts.append(timeout)
                if len(self.timeouts) > self.failures:
                    return "handle"
                self.stamp += timeout
                raise lanes.LaneTimeout()

        sliced = SlicedManager(13)
        with patch.object(lanes, "_manager", sliced), \
                patch.object(queue, "_check_stale_chat") as stale, \
                patch.object(pq_mod.logger, "error") as error, \
                patch.object(pq_mod.logger, "warning") as warning:
            try:
                queue._wait_for_lane("P/m", "thought:demo", lanes.Priority.LOW,
                                     "thought", arrived=100, max_wait=62,
                                     cancel=threading.Event())
                raise AssertionError("fake bounded wait registered")
            except lanes.LaneWaitExpired as exc:
                assert exc.arrived == 100
            assert sliced.timeouts == [5.0] * 12 + [2.0]
            assert stale.call_count == 13 and error.call_count == 1
            assert error.call_args.args[-2] == 60.0
            warning.assert_not_called()
        sliced = SlicedManager(3)
        with patch.object(lanes, "_manager", sliced), \
                patch.object(queue, "_check_stale_chat") as stale, \
                patch.object(pq_mod.logger, "error") as error, \
                patch.object(pq_mod.logger, "warning") as warning:
            assert queue._wait_for_lane("P/m", "tool:demo", lanes.Priority.NORMAL,
                                        "tool", nested=True) == ("handle", 100.0)
            assert sliced.timeouts == [60.0] * 4
            assert stale.call_count == 3
            assert warning.call_count == 2 and error.call_count == 1
        print("PASS C4 short slices retain wait cadence and nested defaults")


def section_d():
    """D: 1 s stands in for 60 s; the rule is the threshold, not its value.

    One busy lane on A and free C gives one hop after 1 <= t < 3 seconds.
    Both busy for 2.5 s give two checks (allow three for scheduling), never
    hundreds; arrival age remains >=2 s. Releasing C gives a hop by 1.5 s;
    releasing A gives no hop. Chat, off, pinned and no opt-in stay on A.
    D7 Fake arrivals 100,101,102 give budgets 1,2,None after live off; all
    rounds carry the same cancel flag. D8 A->C resets arrival from 100 to
    101; the next search excludes both A and C, retaining origin A. D9 A
    second-round cancellation leaves only the first routing call. D10 One tuple orphan closes
    one id. D11 One moved log has origin A/a; the unmoved log omits it.
    """
    from contextlib import ExitStack
    from app.core import paths, llm_lanes as lanes, llm_router as router
    with tempfile.TemporaryDirectory(prefix="lane-d-") as root, ExitStack() as stack:
        paths.init(root)
        from app.core import provider_manager as pm_mod, provider_queue as pq_mod
        from app.core.provider import Provider
        from app.utils import llm_stats
        stack.enter_context(patch.object(pq_mod, "_attach_duration_estimate", lambda task: None))
        stack.enter_context(patch.object(llm_stats, "record_call", lambda *a, **kw: None))
        threshold = [1.0]
        rules = lambda: lanes.LaneRules(affinity_wait=0, conversation_hold=0,
                                        overflow_after=threshold[0])
        manager = lanes.LaneManager(lane_count=lambda key: 1, rules=rules)
        stack.enter_context(patch.object(lanes, "_manager", manager))
        stack.enter_context(patch.object(lanes, "configured_lane_rules", rules))
        pm = pm_mod.ProviderManager()
        for name in "AC":
            provider = Provider(name=name, type="openai", api_base="http://stub",
                                api_key="", max_concurrent=1, timeout=30)
            queue = pq_mod.ProviderQueue(provider, queue_name=name, max_concurrent=1,
                                         chat_pause_enabled=False, serialize_group="")
            pm.providers[name] = provider
            pm.channels[name] = pm._queues[name] = queue
        inst = router.LLMInstance("A", "a", tasks=["thought"])
        alt = router.LLMInstance("C", "c", tasks=["thought"])
        def target(*args, exclude_pools, **kwargs):
            if "C/c" not in exclude_pools and manager.free_lanes(
                    "C/c", "thought:demo", lanes.lane_priority_for("thought")):
                return alt
            return None
        stack.enter_context(patch.object(router, "overflow_target", side_effect=target))

        def run_case(code, *, both=False, release="", task="thought", overflow=True,
                     pinned=False, off=False):
            threshold[0] = 0 if off else 1
            inst.pinned = pinned
            a = manager.acquire_lane("A/a", "chat:blocker", lanes.Priority.CHAT, timeout=0)
            c = manager.acquire_lane("C/c", "chat:blocker", lanes.Priority.CHAT, timeout=0) if both else None
            result, errors = [], []
            def register():
                try:
                    result.append(pm.register_chat_active(inst, "demo", task_type=task,
                                                          overflow=overflow))
                except Exception as exc:
                    errors.append(exc)
            started = time.monotonic()
            thread = threading.Thread(target=register, daemon=True)
            with patch.object(router, "overflow_target", wraps=target) as lookup:
                thread.start()
                try:
                    if release:
                        time.sleep(2.5)
                        assert not result and not errors, (result, errors)
                        if both:
                            assert 2 <= lookup.call_count <= 3, lookup.call_count
                            assert manager.snapshot()["pools"]["A/a"]["waiting_calls"][0]["waiting_s"] >= 2
                        else:
                            lookup.assert_not_called()
                        (c if release == "C" else a).release()
                    thread.join(1.5 if release else 3)
                    assert not thread.is_alive() and not errors, errors
                    returned = result[0]
                    task_id, actual = returned if overflow else (returned, inst)
                    expected = "C" if not release or release == "C" else "A"
                    assert actual.provider_name == expected
                    assert pm.chat_overflow_from(task_id) == ("A/a" if expected == "C" else "")
                    if not release:
                        assert 1 <= time.monotonic() - started < 3
                    if not overflow:
                        assert isinstance(returned, str)
                    pm.register_chat_done(task_id)
                    assert manager.snapshot()["pools"]["A/a"]["waiting"] == 0
                finally:
                    a.release()
                    if c:
                        c.release()
                    thread.join(6)
            print(f"PASS {code}")
        run_case("D1 background hops")
        pools = manager.snapshot()["pools"]
        assert pools["A/a"]["overflowed_out"] == pools["C/c"]["overflowed_in"] == 1
        run_case("D2a no spin; C opens", both=True, release="C")
        run_case("D2b original arrival; A opens", both=True, release="A")
        run_case("D3 chat stays", task="chat_stream", release="A")
        run_case("D4 off stays", off=True, release="A")
        run_case("D5 legacy string", overflow=False, release="A")
        run_case("D6 pinned stays", pinned=True, release="A")

        # Fake-clock rounds pin the live-off transition without timing races:
        # elapsed 0 -> budget 1; elapsed 1 -> budget 2; then off -> unbounded.
        clock = [100.0]
        rounds = []
        cancel = threading.Event()
        inst.pinned = False
        threshold[0] = 1
        def live_round(*args, **kwargs):
            rounds.append(kwargs)
            assert kwargs["arrived"] == 100 and kwargs["cancel"] is cancel
            if len(rounds) <= 2:
                clock[0] += 1
                if len(rounds) == 2:
                    threshold[0] = 0
                raise lanes.LaneWaitExpired(100)
            return "fake-id"
        with patch.object(manager, "now", side_effect=lambda: clock[0]), \
                patch.object(pm._queues["A"], "register_chat_active", side_effect=live_round), \
                patch.object(router, "overflow_target", return_value=None):
            assert pm.register_chat_active(inst, "demo", task_type="thought",
                                           overflow=True, cancel=cancel) == ("fake-id", inst)
        assert [r["max_wait"] for r in rounds] == [1, 2, None]
        print("PASS D7 live off and cancellation flag across rounds")

        threshold[0] = 1
        clock[0] = 100
        seen = []
        def hop_round(*args, **kwargs):
            assert kwargs["cancel"] is cancel
            if not seen:
                clock[0] += 1
                raise lanes.LaneWaitExpired(kwargs["arrived"])
            assert kwargs["arrived"] == 101
            assert kwargs["overflow_from"] == "A/a"
            if len(seen) == 1:
                clock[0] += 1
                raise lanes.LaneWaitExpired(kwargs["arrived"])
            return "moved-id"
        def hop_target(*args, exclude_pools, **kwargs):
            seen.append(exclude_pools)
            return alt if len(seen) == 1 else None
        with patch.object(manager, "now", side_effect=lambda: clock[0]), \
                patch.object(pm._queues["A"], "register_chat_active", side_effect=hop_round), \
                patch.object(pm._queues["C"], "register_chat_active", side_effect=hop_round), \
                patch.object(router, "overflow_target", side_effect=hop_target):
            assert pm.register_chat_active(inst, "demo", task_type="thought",
                                           overflow=True, cancel=cancel) == ("moved-id", alt)
        assert seen == [{"A/a"}, {"A/a", "C/c"}]
        print("PASS D8 hop excludes departed pools and restarts arrival")

        # A later round must still observe cancellation before routing again.
        cancel_rounds = []
        def cancel_round(*args, **kwargs):
            cancel_rounds.append(kwargs)
            if len(cancel_rounds) == 2:
                cancel.set()
            raise lanes.LaneWaitExpired(kwargs["arrived"])
        with patch.object(pm._queues["A"], "register_chat_active", side_effect=cancel_round), \
                patch.object(router, "overflow_target", return_value=None) as lookup:
            try:
                pm.register_chat_active(inst, "demo", task_type="thought",
                                        overflow=True, cancel=cancel)
                raise AssertionError("cancelled boundary registered")
            except lanes.LaneWaitCancelled:
                pass
            assert lookup.call_count == 1 and len(cancel_rounds) == 2
            assert cancel_rounds[0]["arrived"] == cancel_rounds[1]["arrived"]
        print("PASS D9 cancellation after no-target retry")

        from concurrent.futures import Future
        from app.core.llm_queue import get_llm_queue
        facade = get_llm_queue()
        orphan = Future()
        orphan.set_result(("orphan-id", alt))
        with patch.object(facade, "register_chat_done") as close:
            facade._close_orphaned_registration(orphan)
            close.assert_called_once_with("orphan-id")
        print("PASS D10 tuple orphan unwrap")

        from app.core.streaming import StreamingAgent
        from app.utils import llm_logger
        from types import SimpleNamespace
        import json
        agent = StreamingAgent.__new__(StreamingAgent)
        agent.log_task, agent.agent_name, agent.chat_task_id = "thought", "demo", "log-id"
        log_file = Path(root) / "llm_calls.jsonl"
        with patch.object(pm_mod, "_provider_manager", pm), \
                patch.object(pm, "chat_overflow_from", return_value="A/a") as origin, \
                patch.object(agent, "_resolve_provider", return_value="C"), \
                patch.object(agent, "_lane_fields", return_value=(0, "thought:demo")), \
                patch.object(llm_logger, "LOG_DIR", Path(root)), \
                patch.object(llm_logger, "LOG_FILE", log_file):
            agent._log_llm_call(SimpleNamespace(model="c", max_tokens=10),
                                "system", "user", "response", "LLM", time.monotonic())
            origin.assert_called_once_with("log-id")
            llm_logger.log_llm_call(task="thought", model="a")
        entries = [json.loads(line) for line in log_file.read_text().splitlines()]
        assert entries[0]["overflow_from"] == "A/a" and entries[0]["provider"] == "C"
        assert "overflow_from" not in entries[1]
        print("PASS D11 streaming JSONL provenance only when nonempty")


def section_e():
    """E: only background turns opt in; player actions keep their model.

    E1 two calls yield the hand-derived flags [True, False]: explicit opt-in
    and the default. E2 expects one overflow keyword on the first thought
    registration and none on tool re-registration, which must reuse _llm_inst.
    E3 expects True on all three Act skill calls and zero overflow keywords on
    player route calls. E2/E3 are structural checks because a live thought or
    route/tool turn needs a world and an LLM; AST checks pin caller policy
    without running those dependencies or making network calls.
    """
    import ast
    import asyncio
    from app.core import act_engine

    recorded = []
    async def recorder(actor, text, scope, overflow=False):
        recorded.append((actor, text, scope, overflow))
        return {}
    with patch.object(act_engine, "_perform_act", side_effect=recorder):
        asyncio.run(act_engine.perform_act("demo", "x", "here", overflow=True))
        asyncio.run(act_engine.perform_act("demo", "x", "here"))
    assert recorded == [("demo", "x", "here", True),
                        ("demo", "x", "here", False)], recorded
    print("PASS E1 act overflow flag reaches guarded pipeline")

    repo = Path(__file__).resolve().parents[1]
    def tree(relative):
        return ast.parse((repo / relative).read_text(encoding="utf-8"))
    def calls(node, name):
        return sorted((n for n in ast.walk(node) if isinstance(n, ast.Call)
                       and ((isinstance(n.func, ast.Name) and n.func.id == name)
                            or (isinstance(n.func, ast.Attribute)
                                and n.func.attr == name))),
                      key=lambda n: (n.lineno, n.col_offset))
    def keywords(call):
        return {kw.arg: kw.value for kw in call.keywords}

    thought = tree("app/core/thoughts.py")
    registrations = calls(thought, "register_chat_active_async")
    opted = [n for n in registrations if "overflow" in keywords(n)]
    assert len(opted) == 1 and opted[0] is registrations[0]
    queued = next(n for n in ast.walk(thought)
                  if isinstance(n, ast.AsyncFunctionDef)
                  and n.name == "_tool_executor_queued")
    repeated = calls(queued, "register_chat_active_async")
    assert len(repeated) == 1
    kw = keywords(repeated[0])
    assert "overflow" not in kw
    assert isinstance(kw.get("llm_instance"), ast.Name)
    assert kw["llm_instance"].id == "_llm_inst"
    print("PASS E2 thought opts in once and reuses its turn instance")

    skill_calls = calls(tree("plugins/act/skill.py"), "perform_act")
    assert skill_calls
    for call in skill_calls:
        value = keywords(call).get("overflow")
        assert isinstance(value, ast.Constant) and value.value is True
    for relative in ("app/routes/characters.py", "app/routes/play.py"):
        route_calls = calls(tree(relative), "perform_act")
        assert route_calls, relative
        assert all("overflow" not in keywords(call) for call in route_calls), relative
    print("PASS E3 NPC acts opt in; player routes keep default")


def main():
    from app.core import paths

    failed = False
    with tempfile.TemporaryDirectory(prefix="smoke_lane_overflow_") as root:
        paths.init(root)
        for name, section in sorted(globals().copy().items()):
            if name.startswith("section_") and callable(section):
                try:
                    section()
                except Exception as exc:
                    print(f"FAIL {name}: {type(exc).__name__}: {exc}")
                    failed = True
    return int(failed)


if __name__ == "__main__":
    sys.exit(main())
