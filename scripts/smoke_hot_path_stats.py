#!/usr/bin/env python3
"""Smoke run for the hot-path statistics (server-hot-paths Stufe 1, Task 0).

``app/core/hot_path_stats`` collects measurements (``record``) and event
counters (``count``) and turns them into one log line per name and minute
(``flush``). ``build_worldmap_payload(timings=…)`` fills the phase times the
``GET /play/worldmap`` line reports.

Runs against a THROWAWAY storage directory — never a real world, no server,
no LLM, no HTTP.

Hand-derived expectations
-------------------------

t0 = the monotonic time the store was last flushed (set by the smoke).

[H1] record("worldmap", {"build_ms": v}) for v = 1..20, then
     flush(now=t0+61):
       n = 20 samples
       p50 = median of 1..20 = (10 + 11) / 2 = 10.5
       p95 nearest-rank: ceil(0.95 * 20) = ceil(19) = 19 -> the 19th
           value of the sorted list = 19 -> "19.0"
     -> exactly one line
        "hot_path worldmap n=20 build_ms_p50=10.5 build_ms_p95=19.0"
[H2] flush right afterwards -> [] (and a flush another minute later, at
     t0+122, is [] as well: the store was emptied, not only rate-limited).
[H3] count("notify", "presence:moved") x3, count("notify", "self:avatars") x1
     -> "hot_path notify presence:moved=3 self:avatars=1" (descending by n).
[H4] Before [H3]'s line is taken: flush(now=last+30) is before the 60 s are
     over -> [], the counts stay; flush(now=last+61) then yields [H3]'s line.
[H5] 42 distinct keys k01..k42 with n = 42..1 (k01 = 42, ..., k40 = 3,
     k41 = 2, k42 = 1): the first 40 are named (k01=42 ... k40=3), the rest
     is summed: other = 2 + 1 = 3 -> 41 "key=n" tokens after "hot_path keys",
     the last one "other=3".
[H5b] Tie: b=2, a=2, c=1 -> equal n alphabetical -> "hot_path tie a=2 b=2 c=1".
[H7] A logger whose info() raises (patched): record/count still return
     normally even when their call triggers the flush; flush itself returns
     its lines without raising.
[H6] tmp world with one placed location and one character standing there:
     build_worldmap_payload(show_all=True, timings=t) -> t has exactly the six
     keys characters, locations, locations_read, model_sig, motion,
     world_props; every value >= 0; t["motion"] <= t["characters"] + 0.5
     (motion is summed INSIDE the character loop, 0.5 ms timer tolerance).
     Without timings the payload builds as before (no error).

Usage:  ./.venv/bin/python scripts/smoke_hot_path_stats.py
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="hot-path-stats-smoke-"))
CLIPS = Path(tempfile.mkdtemp(prefix="hot-path-stats-clips-"))
# Never look at the repo's real animation clips (they are user data).
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
    print(f"  {'ok ' if ok else 'BAD'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


def reset(t0: float) -> None:
    """Empty the store and pretend the last flush happened at t0."""
    with hps._lock:
        hps._measures.clear()
        hps._counts.clear()
        hps._last_flush = t0


def main() -> int:
    t0 = hps._clock()

    print("\n[H1] measurement line")
    reset(t0)
    for v in range(1, 21):
        hps.record("worldmap", {"build_ms": v})
    check("H1 line", hps.flush(now=t0 + 61),
          ["hot_path worldmap n=20 build_ms_p50=10.5 build_ms_p95=19.0"])

    print("\n[H2] emptied")
    check("H2 flush right after", hps.flush(), [])
    check("H2 flush a minute later", hps.flush(now=t0 + 122), [])

    print("\n[H3]/[H4] counters, rate limit keeps the data")
    last = t0 + 122
    for _ in range(3):
        hps.count("notify", "presence:moved")
    hps.count("notify", "self:avatars")
    check("H4 flush before 60 s", hps.flush(now=last + 30), [])
    check("H3 line", hps.flush(now=last + 61),
          ["hot_path notify presence:moved=3 self:avatars=1"])

    print("\n[H5] at most 40 keys, rest as other")
    reset(t0)
    for i in range(1, 43):
        for _ in range(43 - i):
            hps.count("keys", f"k{i:02d}")
    lines = hps.flush(now=t0 + 61)
    check("H5 one line", len(lines), 1)
    toks = lines[0].split()[2:] if lines else []
    check("H5 token count", len(toks), 41)
    check("H5 first", toks[0] if toks else None, "k01=42")
    check("H5 40th", toks[39] if len(toks) > 39 else None, "k40=3")
    check("H5 last", toks[-1] if toks else None, "other=3")

    print("\n[H5b] tie order")
    reset(t0)
    for k, n in (("b", 2), ("a", 2), ("c", 1)):
        for _ in range(n):
            hps.count("tie", k)
    check("H5b line", hps.flush(now=t0 + 61), ["hot_path tie a=2 b=2 c=1"])

    print("\n[H7] a throwing logger never reaches the caller")

    class _Boom:
        def info(self, *a, **k):
            raise RuntimeError("logger down")

    real_logger = hps.logger
    hps.logger = _Boom()
    try:
        reset(t0 - 1000)            # the next record/count triggers a flush
        raised = None
        try:
            hps.record("boom", {"x": 1})
            reset(t0 - 1000)
            hps.count("boom", "k")
            reset(t0 - 1000)
            hps.record("boom", {"x": "not a number"})
            hps.record("boom", None)
            hps.count("boom", "k")
            reset(t0)
            hps.count("boom", "k")
            out = hps.flush(now=t0 + 61)
        except Exception as e:      # pragma: no cover - the failure case
            raised = e
            out = None
        check("H7 nothing raised", raised, None)
        check("H7 flush still returns its line", out, ["hot_path boom k=1"])
    finally:
        hps.logger = real_logger

    print("\n[H6] worldmap phase timings")
    from app.core.world_ops import build_worldmap_payload
    from app.models.character import (save_character_current_location,
                                      save_character_profile)
    from app.models.world import add_location, update_location_position
    loc = add_location(name="Stats Inn", description="hot path smoke")["id"]
    update_location_position(loc, 10.0, 10.0)
    save_character_profile("demo", {"current_location": ""}, create_new=True)
    save_character_current_location("demo", loc)
    t = {}
    payload = build_worldmap_payload(show_all=True, timings=t)
    check("H6 keys", sorted(t), ["characters", "locations", "locations_read",
                                 "model_sig", "motion", "world_props"])
    check("H6 all >= 0", all(isinstance(v, float) and v >= 0 for v in t.values()),
          True)
    check("H6 motion within characters", t.get("motion", 1e9) <= t.get("characters", -1) + 0.5,
          True)
    check("H6 payload has the location", [e["id"] for e in payload["locations"]], [loc])
    check("H6 payload has the character", [c["name"] for c in payload["characters"]],
          ["demo"])
    plain = build_worldmap_payload(show_all=True)
    check("H6 without timings same locations", [e["id"] for e in plain["locations"]], [loc])
    print(f"      timings: {t}")

    print(f"\n{CHECKED} checks, {len(FAILURES)} failed")
    if FAILURES:
        print("FAILED: " + ", ".join(FAILURES))
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
