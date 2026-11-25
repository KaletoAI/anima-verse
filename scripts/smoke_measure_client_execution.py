#!/usr/bin/env python3
"""Smoke run for the READ-ONLY client-execution measurement script.

``scripts/measure_client_execution.py`` reads the server's CPU ticks from
``/proc/<pid>/stat``, the ``hot_path`` lines that grew in ``logs/main.log``
and the ``[native] first_step`` lines of the native client log, and renders
one Markdown table. This smoke checks its pure functions only — no server,
no world, no DB, no HTTP. Every expectation is derived by hand below.

Hand-derived expectations
-------------------------

[M1] "4242 (python3) S 1 2 3 4 5 6 7 8 9 10 300 50 0 0 ..." -> split after
     the LAST ")": index 0 = "S", 1..10 = "1".."10", index 11 = "300"
     (utime, field 14), index 12 = "50" (stime, field 15) -> 300 + 50 = 350.
[M1b] "4242 (uvicorn (w) 1) S 1 2 3 4 5 6 7 8 9 10 300 50 0 0" -> the
     command name itself holds ")" ; splitting after the LAST ")" gives the
     same tail as M1 -> 350.
[M2] client_exec_routes lines at 10:00:05 (pos=100), 10:01:05 (pos=180,
     worldmap=20), 10:02:05 (pos=180, worldmap=20). The first line covers a
     window that began before the first timestamp, so it is dropped; sums
     pos = 180 + 180 = 360, worldmap = 20 + 20 = 40; span = 10:02:05 -
     10:00:05 = 120 s -> rates per minute pos = 360 / 120 * 60 = 180.0,
     worldmap = 40 / 120 * 60 = 20.0 (pos per second = 180 / 60 = 3.0),
     sums == {pos: 360, worldmap: 40}, span_s == 120.
[M3] midnight: 23:59:30 beat=12, 00:00:30 beat=12 -> 00:00:30 is 30 s and
     23:59:30 is 86370 s; the difference wraps (30 - 86370 + 86400) = 60 s.
     First line dropped -> 12 / 60 * 60 = 12.0 per minute, span_s == 60.
[M4] one single line -> None; render_table shows "n/a" for its rows.
[M5] client log with click_walk ms=20.0, prop_offer ms=1450.0, prop_offer
     timeout -> [("click_walk", 20.0), ("prop_offer", 1450.0),
     ("prop_offer", None)]; table: median of {20.0, 1450.0} = (20.0 +
     1450.0) / 2 = 735.0 ms, n = 2, timeouts = 1.
[M6] lines of other names ("hot_path notify ...") and non-hot_path lines
     are ignored: parse_hot_path(text, "client_exec_routes") returns only the
     three M2 lines.
[M7] is_server_cmdline: "/x/.venv/bin/python -m uvicorn app.server:app"
     -> True (basename "python", argument "uvicorn"); "sg render -c 'exec
     setsid ... uvicorn ...'" -> False (first argument "sg");
     "/usr/bin/python3 -m http.server" -> False (no uvicorn argument).
[M8] read_growth on a temp file: start size 10, file now 25 bytes -> exactly
     the 15 new bytes; start 25, file now 5 bytes -> LogShrunk.

Usage:  ./.venv/bin/python scripts/smoke_measure_client_execution.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import measure_client_execution as m  # noqa: E402

FAILS = []


def check(label, got, want):
    ok = got == want
    print(f"[{'ok' if ok else 'FAIL'}] {label}: {got!r}" + ("" if ok else f" (want {want!r})"))
    if not ok:
        FAILS.append(label)


def hp(ts, name, rest):
    return f"{ts} [hot_path] INFO hot_path {name} {rest}"


# [M1] / [M1b]
check("M1 cpu_ticks", m.cpu_ticks("4242 (python3) S 1 2 3 4 5 6 7 8 9 10 300 50 0 0 0 0"), 350)
check("M1b cpu_ticks last paren", m.cpu_ticks("4242 (uvicorn (w) 1) S 1 2 3 4 5 6 7 8 9 10 300 50 0 0"), 350)

# [M2] + [M6]
routes_text = "\n".join([
    "10:00:00 [main] INFO server started",
    hp("10:00:05", "client_exec_routes", "POST:/play/pos=100"),
    hp("10:00:30", "notify", "presence:x.y=4"),
    hp("10:01:05", "client_exec_routes", "POST:/play/pos=180 GET:/play/worldmap=20"),
    "10:01:10 [hot_path] INFO something else client_exec_routes POST:/play/pos=9",
    hp("10:02:05", "client_exec_routes", "POST:/play/pos=180 GET:/play/worldmap=20"),
    hp("10:02:06", "client_exec_routes_x", "POST:/play/pos=7"),
])
lines = m.parse_hot_path(routes_text, "client_exec_routes")
check("M6 only the three named lines", lines, [
    (36005, {"POST:/play/pos": 100}),
    (36065, {"POST:/play/pos": 180, "GET:/play/worldmap": 20}),
    (36125, {"POST:/play/pos": 180, "GET:/play/worldmap": 20}),
])
w = m.window_rates(lines)
check("M2 rates", w and w["rates"], {"POST:/play/pos": 180.0, "GET:/play/worldmap": 20.0})
check("M2 sums", w and w["sums"], {"POST:/play/pos": 360, "GET:/play/worldmap": 40})
check("M2 span", w and w["span_s"], 120)

# [M3]
mid = m.parse_hot_path("\n".join([hp("23:59:30", "client_exec_ticker", "beat=12"),
                                  hp("00:00:30", "client_exec_ticker", "beat=12")]),
                       "client_exec_ticker")
w3 = m.window_rates(mid)
check("M3 rates", w3 and w3["rates"], {"beat": 12.0})
check("M3 span", w3 and w3["span_s"], 60)

# [M4]
one = m.parse_hot_path(hp("10:00:05", "client_exec_ticker", "beat=12"), "client_exec_ticker")
check("M4 one line -> None", m.window_rates(one), None)

# [M5]
client_text = "\n".join([
    "some godot line",
    "[native] first_step source=click_walk ms=20.0 frames=1",
    "[native] first_step source=prop_offer ms=1450.0 frames=87",
    "[native] first_step source=prop_offer timeout",
])
steps = m.first_steps(client_text)
check("M5 first_steps", steps, [("click_walk", 20.0), ("prop_offer", 1450.0), ("prop_offer", None)])

table = m.render_table({
    "measure_s": 120,
    "cpu_s_per_min": None,
    "routes": w,
    "ticker": m.window_rates(one),   # M4: a single line -> n/a
    "first_steps": steps,
})
rows = {ln.split("|")[1].strip(): [c.strip() for c in ln.split("|")[2:-1]]
        for ln in table.splitlines() if ln.startswith("|") and not ln.startswith("|---")}
check("M2 table pos/s", rows.get("`/play/pos`/s", [None])[0], "3.0")
check("M2 table pos/min", rows.get("`/play/pos`/min", [None])[:3], ["180.0", "360", "120"])
check("M2 table worldmap/min", rows.get("`/play/worldmap`/min", [None])[0], "20.0")
check("M2 table orders/min absent key -> 0.0", rows.get("`/play/orders`/min", [None])[0], "0.0")
check("M4 table cpu n/a", rows.get("Server CPU s/min", [None])[0], "n/a")
check("M4 table beats n/a", rows.get("Ticker beats/min", [None])[0], "n/a")
check("M4 table advance n/a", rows.get("`advance()`/min", [None])[0], "n/a")
first = [v for k, v in rows.items() if k.startswith("First step")]
check("M5 table median", first and first[0][0], "735.0 ms (n=2, timeouts=1)")

# [M7]
check("M7 python uvicorn", m.is_server_cmdline(b"/x/.venv/bin/python\0-m\0uvicorn\0app.server:app\0"), True)
check("M7 sg wrapper", m.is_server_cmdline(
    b"sg\0render\0-c\0exec setsid /x/.venv/bin/python -m uvicorn app.server:app\0"), False)
check("M7 no uvicorn", m.is_server_cmdline(b"/usr/bin/python3\0-m\0http.server\0"), False)

# [M8]
with tempfile.TemporaryDirectory() as td:
    p = os.path.join(td, "log.txt")
    with open(p, "wb") as f:
        f.write(b"0123456789")
    start = os.path.getsize(p)
    with open(p, "ab") as f:
        f.write(b"ABCDEFGHIJKLMNO")
    check("M8 growth", m.read_growth(p, start), "ABCDEFGHIJKLMNO")
    with open(p, "wb") as f:
        f.write(b"short")
    try:
        m.read_growth(p, 25)
        check("M8 shrunk raises", "no raise", "LogShrunk")
    except m.LogShrunk:
        check("M8 shrunk raises", "LogShrunk", "LogShrunk")

if FAILS:
    print(f"FAIL: {len(FAILS)} check(s): {', '.join(FAILS)}")
    sys.exit(1)
print("PASS")
