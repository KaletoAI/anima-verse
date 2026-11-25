#!/usr/bin/env python3
"""Read-only measurement of the client-execution load of a running server.

Measures, over one window of N seconds, what the server spends on work the
clients could do themselves: its CPU time, the client-execution routes
(``/play/pos``, ``/play/worldmap``, ``/play/orders``), the travel-ticker beats
and the prop-action ``advance()`` / ``_advance_run`` / ``_validate`` steps (the
``hot_path client_exec_routes`` and ``hot_path client_exec_ticker`` lines of
``logs/main.log``), and — with ``--client-log`` — how long the native client
took for its first visible step (``[native] first_step ...`` lines).

It only READS: ``/proc/<pid>/stat``, ``/proc/<pid>/cmdline`` and the growth of
the two log files. No world DB, no HTTP, nothing is started or stopped.

Scenario to run while measuring (the same each time, so runs compare): the
avatar walks freely for 60 s and then takes an armchair; three NPCs go to
bed one after another; an overland journey is running. Recommended window:
``--seconds 420`` (the hot_path lines come once a minute and the first one of
the window is dropped, so a window under 180 s leaves too few lines — the
script warns on stderr).

Usage:
    ./.venv/bin/python scripts/measure_client_execution.py record --seconds 420 \\
        [--pid PID] [--log logs/main.log] [--client-log <export>/logs/native-<time>.log] \\
        [--label TEXT] [--out PATH]

Without ``--pid`` the server PID is read from ``.pids/main.pid`` (start.sh writes
the uvicorn process there, not the ``sg`` wrapper). The PID must be the
uvicorn Python process itself. Output goes to stdout; ``--out`` additionally
appends it to a file under the heading ``## <label> — <ISO time>``.

Rates: every hot_path line holds the counts of the minute BEFORE it, so the
first line of the window counts events from before the window started — it
is dropped; the rest is summed and divided by the time between the first and
the last line (midnight wraps). A log that SHRINKS during the window (rotated
by a restart) aborts the run.
"""
from __future__ import annotations

import argparse
import os
import re
import statistics
import sys
import time
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MIN_SECONDS = 180
DAY_S = 24 * 3600

_HOT_PATH_RE = re.compile(r"^(\d\d):(\d\d):(\d\d) \[hot_path\] INFO hot_path (\S+)((?: \S+=\d+)*)\s*$")
_FIRST_STEP_RE = re.compile(
    r"\[native\] first_step source=(\S+) (?:ms=([0-9.]+) frames=\d+|timeout)\s*$")


class LogShrunk(RuntimeError):
    """A log file is smaller now than at the start of the window (rotated)."""


def cpu_ticks(stat_text: str) -> int:
    """utime + stime (fields 14 and 15, 1-based) of a /proc/<pid>/stat text.

    The command name may contain spaces and parentheses, so the fields are
    split after the LAST ")": there field 3 (state) is index 0, so utime and
    stime are index 11 and 12."""
    tail = stat_text[stat_text.rindex(")") + 1:].split()
    return int(tail[11]) + int(tail[12])


def parse_hot_path(text: str, name: str) -> list[tuple[int, dict[str, int]]]:
    """The ``hot_path <name> k=v ...`` lines of a log text as
    (seconds of the day, {key: count}); every other line is ignored."""
    out: list[tuple[int, dict[str, int]]] = []
    for line in text.splitlines():
        mo = _HOT_PATH_RE.match(line)
        if not mo or mo.group(4) != name:
            continue
        t = int(mo.group(1)) * 3600 + int(mo.group(2)) * 60 + int(mo.group(3))
        counts: dict[str, int] = {}
        for part in mo.group(5).split():
            key, _, val = part.rpartition("=")
            counts[key] = counts.get(key, 0) + int(val)
        out.append((t, counts))
    return out


def window_rates(lines: list[tuple[int, dict[str, int]]]) -> dict | None:
    """Rates per minute over a window of hot_path lines.

    The first line is dropped (its counts belong to the minute before the
    window), the others are summed; the span is last minus first timestamp,
    wrapped at midnight. None with fewer than 2 lines."""
    if len(lines) < 2:
        return None
    span = 0
    for (t0, _), (t1, _) in zip(lines, lines[1:]):
        span += (t1 - t0) % DAY_S
    if span <= 0:
        return None
    sums: dict[str, int] = {}
    for _, counts in lines[1:]:
        for key, val in counts.items():
            sums[key] = sums.get(key, 0) + val
    rates = {key: val / span * 60.0 for key, val in sums.items()}
    return {"rates": rates, "sums": sums, "span_s": span}


def is_server_cmdline(raw: bytes) -> bool:
    """True when a /proc/<pid>/cmdline (NUL-separated) is the uvicorn Python
    process itself — not a ``sg`` or ``bash`` wrapper around it."""
    args = [a.decode("utf-8", "replace") for a in raw.split(b"\0") if a]
    if not args or not os.path.basename(args[0]).startswith("python"):
        return False
    return any(a == "uvicorn" or a.endswith("/uvicorn") for a in args[1:])


def read_growth(path, start_size) -> str:
    """What was appended to ``path`` after byte offset ``start_size``;
    raises LogShrunk when the file is smaller now."""
    size = os.path.getsize(path)
    if size < start_size:
        raise LogShrunk(f"{path} shrank from {start_size} to {size} bytes (rotated?)")
    with open(path, "rb") as f:
        f.seek(start_size)
        return f.read(size - start_size).decode("utf-8", "replace")


def first_steps(text: str) -> list[tuple[str, float | None]]:
    """(source, ms) per ``[native] first_step`` line; ms None for a timeout."""
    out: list[tuple[str, float | None]] = []
    for line in text.splitlines():
        mo = _FIRST_STEP_RE.search(line)
        if mo:
            out.append((mo.group(1), float(mo.group(2)) if mo.group(2) is not None else None))
    return out


def _fmt(v, digits=1) -> str:
    if v is None:
        return "n/a"
    if isinstance(v, int):
        return str(v)
    return f"{v:.{digits}f}"


def _route_cells(win: dict | None, route: str, per_second: bool = False) -> tuple:
    if win is None:
        return None, None, None
    raw = sum(v for k, v in win["sums"].items() if k.endswith(":" + route))
    rate = raw / win["span_s"] * (1.0 if per_second else 60.0)
    return rate, raw, win["span_s"]


def _key_cells(win: dict | None, key: str) -> tuple:
    if win is None:
        return None, None, None
    raw = win["sums"].get(key, 0)
    return raw / win["span_s"] * 60.0, raw, win["span_s"]


def render_table(r: dict) -> str:
    """Markdown table of one measurement. ``r`` holds measure_s, cpu_s_per_min,
    cpu_s (optional), routes / ticker (window_rates results or None) and
    first_steps (list or None)."""
    measure = r.get("measure_s")
    routes = r.get("routes")
    ticker = r.get("ticker")
    rows: list[tuple[str, tuple]] = [
        ("Server CPU s/min", (r.get("cpu_s_per_min"), r.get("cpu_s"), None)),
        ("`/play/pos`/s", _route_cells(routes, "/play/pos", per_second=True)),
        ("`/play/pos`/min", _route_cells(routes, "/play/pos")),
        ("`/play/worldmap`/min", _route_cells(routes, "/play/worldmap")),
        ("`/play/orders`/min", _route_cells(routes, "/play/orders")),
        ("Ticker beats/min", _key_cells(ticker, "beat")),
        ("`advance()`/min", _key_cells(ticker, "advance")),
        ("`_advance_run`/min", _key_cells(ticker, "advance_run")),
        ("`_validate` in advance/min", _key_cells(ticker, "advance_validate")),
    ]
    lines = ["| Metric | Value | Raw sum | Log line span s | Measured s |",
             "|---|---|---|---|---|"]
    for label, (value, raw, span) in rows:
        lines.append(f"| {label} | {_fmt(value)} | {_fmt(raw)} | {_fmt(span)} | {_fmt(measure)} |")
    steps = r.get("first_steps")
    if steps is None:
        step_cell = "n/a"
    else:
        done = [ms for _, ms in steps if ms is not None]
        timeouts = sum(1 for _, ms in steps if ms is None)
        median = f"{statistics.median(done):.1f} ms" if done else "n/a"
        step_cell = f"{median} (n={len(done)}, timeouts={timeouts})"
    lines.append(f"| First step median | {step_cell} | n/a | n/a | {_fmt(measure)} |")
    return "\n".join(lines) + "\n"


def _fail(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(2)


def _read_pid(arg_pid: int | None) -> int:
    if arg_pid is not None:
        return arg_pid
    pid_file = os.path.join(ROOT, ".pids", "main.pid")
    try:
        with open(pid_file) as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        _fail(f"no server PID in {pid_file} — is the server running? Check ./start.sh --status")
    return -1  # unreachable


def _read_stat(pid: int) -> int:
    with open(f"/proc/{pid}/stat") as f:
        return cpu_ticks(f.read())


def record(args) -> int:
    seconds = int(args.seconds)
    if seconds <= 0:
        _fail("--seconds must be positive")
    if seconds < MIN_SECONDS:
        print(f"warning: --seconds {seconds} < {MIN_SECONDS}: too few hot_path lines for a rate "
              f"(420 recommended)", file=sys.stderr)
    pid = _read_pid(args.pid)
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            cmdline = f.read()
    except OSError:
        _fail(f"process {pid} not found — check ./start.sh --status")
    if not is_server_cmdline(cmdline):
        _fail(f"PID {pid} is not the uvicorn Python process (sg wrapper?)")

    log_path = args.log if os.path.isabs(args.log) else os.path.join(ROOT, args.log)
    if not os.path.isfile(log_path):
        _fail(f"server log {log_path} not found")
    client_log = args.client_log
    if client_log and not os.path.isfile(client_log):
        _fail(f"client log {client_log} not found")

    ticks0 = _read_stat(pid)
    log_size0 = os.path.getsize(log_path)
    client_size0 = os.path.getsize(client_log) if client_log else 0
    t0 = time.monotonic()
    end = t0 + seconds
    while True:
        left = end - time.monotonic()
        if left <= 0:
            break
        time.sleep(min(60.0, left))
        elapsed = time.monotonic() - t0
        if elapsed < seconds:
            print(f"... {int(elapsed)} / {seconds} s", file=sys.stderr)
    try:
        ticks1 = _read_stat(pid)
    except OSError:
        _fail(f"process {pid} ended during the measurement")
    try:
        log_text = read_growth(log_path, log_size0)
        client_text = read_growth(client_log, client_size0) if client_log else None
    except LogShrunk as exc:
        _fail(f"{exc} — the measurement is void, run it again")

    cpu_s = (ticks1 - ticks0) / os.sysconf("SC_CLK_TCK")
    result = {
        "measure_s": seconds,
        "cpu_s": cpu_s,
        "cpu_s_per_min": cpu_s * 60.0 / seconds,
        "routes": window_rates(parse_hot_path(log_text, "client_exec_routes")),
        "ticker": window_rates(parse_hot_path(log_text, "client_exec_ticker")),
        "first_steps": first_steps(client_text) if client_text is not None else None,
    }
    table = render_table(result)
    sys.stdout.write(table)
    if args.out:
        stamp = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        with open(args.out, "a", encoding="utf-8") as f:
            f.write(f"\n## {args.label or 'measurement'} — {stamp}\n\n{table}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    rec = sub.add_parser("record", help="measure one window")
    rec.add_argument("--seconds", type=int, required=True)
    rec.add_argument("--pid", type=int)
    rec.add_argument("--log", default="logs/main.log")
    rec.add_argument("--client-log")
    rec.add_argument("--label", default="")
    rec.add_argument("--out")
    args = ap.parse_args(argv)
    if args.cmd == "record":
        return record(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
