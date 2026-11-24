#!/usr/bin/env python3
"""Smoke run for the HOT-PATH STATISTICS (server hot paths, stage 1, task 0).

``app/core/hot_path_stats`` collects measurements (``record``) and event
counts (``count``) and writes at most one ``hot_path`` line per name and
minute to the log (``flush``). ``GET /play/worldmap`` records its phases,
``sync_topics.notify`` counts its callers. Statistics must never disturb the
measured path: a logger that throws must not reach a caller.

Runs against a THROWAWAY storage directory — never a real world, no server,
no LLM. Every case sets the flush clock itself (``_last_flush = t0``) and
flushes with an explicit ``now``, so no case depends on wall-clock timing.

Hand-derived expectations
-------------------------

[H1] record("worldmap", {"build_ms": v}) for v = 1..20, flush(now=t0+61):
     median of 1..20 = (10 + 11) / 2 = 10.5; nearest-rank p95 =
     ceil(0.95 * 20) = 19th value = 19 ->
     ["hot_path worldmap n=20 build_ms_p50=10.5 build_ms_p95=19.0"]
[H2] flush again one minute later -> [] (the first flush emptied it).
[H3] count("notify", "presence:moved") x3, count("notify", "self:avatars")
     x1 -> ["hot_path notify presence:moved=3 self:avatars=1"]
     (descending by n).
[H4] the same two counts, flush(now=t0+30) -> [] (60 s not over), and the
     data stays: flush(now=t0+61) -> the H3 line.
[H5] 42 keys k01..k42 with n = 42..1 (k01 = 42, ..., k40 = 3, k41 = 2,
     k42 = 1): the first 40 are named (k01=42 ... k40=3), the rest folds
     into other = 2 + 1 = 3.
[H5b] tie: b = 2, a = 2, c = 1 -> "hot_path tie a=2 b=2 c=1" (equal n
     alphabetically).
[H7] a logger whose info() raises, flush clock 120 s in the past (so record
     and count flush on their own): neither record nor count raises, and an
     explicit flush returns a list instead of raising.
[H6] tmp world, one location "Hot Inn" at (10, 10), one character "hp_npc"
     standing in it: build_worldmap_payload(show_all=True, timings=t) ->
     t has exactly the six keys characters, locations, locations_read,
     model_sig, motion, world_props; every value >= 0;
     t["motion"] <= t["characters"] + 0.5 and
     t["model_sig"] <= t["characters"] + 0.5 (both are summed INSIDE the
     character loop; 0.5 ms timer tolerance). The payload built WITH timings
     equals the one built without (everything but the ``sync`` block, whose
     clock age is a stopwatch): measuring changes no field.
[H8] sync_topics.notify("presence", to=Avatar("A")) from the function
     ``fire`` of this script (module ``__main__``) with ONE connection bound
     to avatar A -> counter lines
       "hot_path notify presence:__main__.fire=1"
       "hot_path notify_woke presence=1"
     (the caller is the first frame outside sync_topics, cut to
     <last module part>.<function>; one connection woke for one topic).
[H9] play_worldmap(admin, all=1) records ONE worldmap sample: n=1 and the
     keys bytes, build_ms, encode_ms plus the six phases of H6 -> nine
     ``<key>_p50`` entries; bytes_p50 == len(response.body) (one sample:
     p50 = p95 = that value).

Usage:  ./.venv/bin/python scripts/smoke_hot_path_stats.py
"""
import os
import re
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="hot-path-stats-smoke-"))
CLIPS = Path(tempfile.mkdtemp(prefix="hot-path-stats-clips-"))
os.environ["ANIMATION_CLIPS_DIR"] = str(CLIPS)

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import db  # noqa: E402
db.init_schema()

from app.core import hot_path_stats as hps  # noqa: E402

FAILURES = []
CHECKED = 0


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'✓' if ok else '✗'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


def reset() -> float:
    """Empty the collector and pin its flush clock to now; returns t0."""
    hps.flush(now=hps._last_flush + 10_000.0)
    t0 = time.monotonic()
    hps._last_flush = t0
    return t0


def h1_h2():
    print("\n[H1/H2] measurement line, then empty")
    t0 = reset()
    for v in range(1, 21):
        hps.record("worldmap", {"build_ms": float(v)})
    check("H1 line", hps.flush(now=t0 + 61),
          ["hot_path worldmap n=20 build_ms_p50=10.5 build_ms_p95=19.0"])
    check("H2 emptied", hps.flush(now=t0 + 122), [])


def h3_h4():
    print("\n[H3/H4] counter line; no flush before 60 s")
    t0 = reset()
    for _ in range(3):
        hps.count("notify", "presence:moved")
    hps.count("notify", "self:avatars")
    check("H3 line", hps.flush(now=t0 + 61),
          ["hot_path notify presence:moved=3 self:avatars=1"])
    t1 = reset()
    for _ in range(3):
        hps.count("notify", "presence:moved")
    hps.count("notify", "self:avatars")
    check("H4 too early", hps.flush(now=t1 + 30), [])
    check("H4 kept", hps.flush(now=t1 + 61),
          ["hot_path notify presence:moved=3 self:avatars=1"])


def h5():
    print("\n[H5/H5b] 40 keys + other; ties alphabetical")
    t0 = reset()
    for i in range(1, 43):
        for _ in range(43 - i):
            hps.count("cnt", f"k{i:02d}")
    named = " ".join(f"k{i:02d}={43 - i}" for i in range(1, 41))
    check("H5 line", hps.flush(now=t0 + 61),
          [f"hot_path cnt {named} other=3"])
    t1 = reset()
    for key, n in (("b", 2), ("a", 2), ("c", 1)):
        for _ in range(n):
            hps.count("tie", key)
    check("H5b line", hps.flush(now=t1 + 61), ["hot_path tie a=2 b=2 c=1"])


def h7():
    print("\n[H7] a throwing logger never reaches the caller")

    class Boom:
        def info(self, *a, **k):
            raise RuntimeError("logger down")

        debug = warning = error = info

    real = hps.logger
    hps.logger = Boom()
    try:
        raised = None
        out = None
        try:
            hps._last_flush = time.monotonic() - 120.0
            hps.record("boom", {"x": 1.0})
            hps._last_flush = time.monotonic() - 120.0
            hps.count("boom", "k")
            hps.count("boom", "k")
            out = hps.flush(now=hps._last_flush + 61)
        except Exception as e:  # noqa: BLE001
            raised = e
        check("H7 nothing raised", raised, None)
        check("H7 explicit flush answers a list", isinstance(out, list), True)
    finally:
        hps.logger = real
    reset()


def _seed_world():
    from app.models.character import (save_character_current_location,
                                      save_character_profile)
    from app.models.world import add_location, update_location_position
    loc = add_location(name="Hot Inn", description="hot path smoke")["id"]
    update_location_position(loc, 10.0, 10.0)
    save_character_profile("hp_npc", {"current_location": ""}, create_new=True)
    save_character_current_location("hp_npc", loc)
    return loc


SIX = ["characters", "locations", "locations_read", "model_sig", "motion",
       "world_props"]


def h6():
    print("\n[H6] build_worldmap_payload fills the six phases")
    from app.core.world_ops import build_worldmap_payload
    t = {}
    with_t = build_worldmap_payload(show_all=True, timings=t)
    check("H6 keys", sorted(t), SIX)
    check("H6 all >= 0", all(v >= 0 for v in t.values()), True)
    check("H6 motion within characters", t["motion"] <= t["characters"] + 0.5, True)
    check("H6 model_sig within characters",
          t["model_sig"] <= t["characters"] + 0.5, True)
    check("H6 one character in the payload",
          [c["name"] for c in with_t["characters"]], ["hp_npc"])
    without = build_worldmap_payload(show_all=True)
    a = {k: v for k, v in with_t.items() if k != "sync"}
    b = {k: v for k, v in without.items() if k != "sync"}
    check("H6 payload unchanged by measuring", a == b, True)


def h8():
    print("\n[H8] notify counts its caller and the woken connections")
    from app.core import sync_topics
    t0 = reset()
    conn = sync_topics.register("u1", "tok", "A", "")
    try:
        def fire():
            sync_topics.notify("presence", to=sync_topics.Avatar("A"))
        fire()
        check("H8 lines", hps.flush(now=t0 + 61),
              ["hot_path notify presence:__main__.fire=1",
               "hot_path notify_woke presence=1"])
    finally:
        sync_topics.unregister(conn)


def h9():
    print("\n[H9] play_worldmap records one worldmap sample")
    from app.core import users
    from app.routes import play
    t0 = reset()
    resp = play.play_worldmap(user={"id": "admin1", "role": users.ROLE_ADMIN,
                                    "settings": {}}, show_all=1)
    lines = hps.flush(now=t0 + 61)
    check("H9 one line", len(lines), 1)
    line = lines[0] if lines else ""
    check("H9 n=1", line.startswith("hot_path worldmap n=1 "), True)
    keys = sorted(re.findall(r"(\w+)_p50=", line))
    check("H9 keys", keys, sorted(["bytes", "build_ms", "encode_ms"] + SIX))
    m = re.search(r"bytes_p50=([0-9.]+)", line)
    check("H9 bytes == len(body)", float(m.group(1)) if m else None,
          float(len(resp.body)))


def main() -> int:
    h1_h2()
    h3_h4()
    h5()
    h7()
    _seed_world()
    h6()
    h8()
    h9()
    print(f"\n{CHECKED - len(FAILURES)}/{CHECKED} checks passed")
    if FAILURES:
        print("FAILED:", ", ".join(FAILURES))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
