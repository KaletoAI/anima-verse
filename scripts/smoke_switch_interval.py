#!/usr/bin/env python3
"""GIL switch interval: the server sets 0.5 ms, and that keeps a SELECT cheap under CPU load.

Usage: ./.venv/bin/python scripts/smoke_switch_interval.py
Needs no world and no server.

Why: a thread that drops the GIL for a syscall waits up to one switch interval PER CPU-bound
thread to get it back. Measured 2026-11-25 with four CPU-bound threads: a SELECT costs 42 ms on
average at Python's default of 5 ms and 8.5 ms at 0.5 ms (single runs: 308 ms against 0.5 ms).

  [W1] app/server.py assigns GIL_SWITCH_INTERVAL_S = 0.0005 and calls setswitchinterval with it
       before its first "from app" import (AST — importing app.server would need a world).

No timing is asserted: the effect is bimodal on a multi-core host (in some runs the measuring
thread never loses the GIL at either interval — 0.0 / 11.6 / 19.5 ms in three runs of the same
check), so a bound either flickers or proves nothing. The measurement is repeatable by hand with
four CPU-bound threads and a loop of SELECTs under sys.setswitchinterval(0.005) and (0.0005).
"""
import ast
import sys
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

print("FAILED" if failed else "Switch interval checks passed")
sys.exit(1 if failed else 0)
