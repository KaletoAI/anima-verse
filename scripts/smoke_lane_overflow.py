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
