#!/usr/bin/env python3
"""GIL switch interval: the server sets 0.5 ms, and that keeps a SELECT cheap under CPU load.

Usage: ./.venv/bin/python scripts/smoke_switch_interval.py
Needs no world and no server.

Why: a thread that drops the GIL for a syscall waits up to one switch interval PER CPU-bound
thread to get it back. Measured 2026-11-25 with four CPU-bound threads: one SELECT 308 ms at
Python's default of 5 ms, 0.5 ms at 0.5 ms.

  [W1] app/server.py assigns GIL_SWITCH_INTERVAL_S = 0.0005 and calls setswitchinterval with it
       before its first "from app" import (AST — importing app.server would need a world).
  [W2] with that interval and four CPU-bound threads, 200 SELECTs average under 20 ms each.
       The bound is 40 times the measured value so a loaded host does not flicker; the default
       interval misses it by a factor of 15.
"""
import ast
import os
import sqlite3
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
failed = 0


def ok(label, cond, detail=""):
    global failed
    print(("  OK  " if cond else "  FAIL ") + label + (f" — {detail}" if detail else ""))
    if not cond:
        failed += 1


tree = ast.parse((ROOT / "app" / "server.py").read_text(encoding="utf-8"))
value = None
set_line = None
first_app_import = None
for node in tree.body:
    if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "GIL_SWITCH_INTERVAL_S" for t in node.targets):
        value = ast.literal_eval(node.value)
    if (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute)
            and node.value.func.attr == "setswitchinterval"
            and any(isinstance(a, ast.Name) and a.id == "GIL_SWITCH_INTERVAL_S"
                    for a in node.value.args)):
        set_line = node.lineno
    if (first_app_import is None and isinstance(node, ast.ImportFrom)
            and (node.module or "").startswith("app")):
        first_app_import = node.lineno
ok("[W1] GIL_SWITCH_INTERVAL_S == 0.0005", value == 0.0005, str(value))
ok("[W1] set before the first app import",
   set_line is not None and first_app_import is not None and set_line < first_app_import,
   f"set at {set_line}, first app import at {first_app_import}")

before = sys.getswitchinterval()
sys.setswitchinterval(value or 0.0005)
stop = threading.Event()


def burn():
    x = 0
    while not stop.is_set():
        for k in range(2000):
            x += k * k


with tempfile.TemporaryDirectory() as tmp:
    conn = sqlite3.connect(os.path.join(tmp, "t.db"))
    conn.execute("create table t(a, b)")
    conn.execute("insert into t values (1, 'x')")
    conn.commit()
    threads = [threading.Thread(target=burn, daemon=True) for _ in range(4)]
    for t in threads:
        t.start()
    time.sleep(0.2)
    t0 = time.perf_counter()
    for _ in range(200):
        conn.execute("select * from t").fetchone()
    per_call_ms = (time.perf_counter() - t0) / 200 * 1000
    stop.set()
    for t in threads:
        t.join()
    conn.close()
sys.setswitchinterval(before)
ok("[W2] SELECT under four CPU threads < 20 ms", per_call_ms < 20.0, f"{per_call_ms:.2f} ms per call")

print("FAILED" if failed else "Switch interval checks passed")
sys.exit(1 if failed else 0)
