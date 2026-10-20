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
