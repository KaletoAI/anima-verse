#!/usr/bin/env python3
"""Smoke: the decision-model admin surface — schema section + the three
routes (development_instructions/plan-decision-models.md § 3.2).

Usage:  ./.venv/bin/python scripts/smoke_decision_admin.py

The route functions are called directly (no HTTP, no session); config is set
in memory. Storage is a throwaway dir initialised first.

EXPECTATIONS, DERIVED BY HAND
A  SECTIONS["decision"]: field "enabled" default False; sub-array "endpoints"
   with fields name, url, api_key, model, enabled; api_key is a sensitive
   password field AND "api_key" is in config.SENSITIVE_FIELDS (so it goes to
   secrets.json); pages endpoints / points / shadow, the last two custom.
B  points route: the three core points are listed, registered, origin "core";
   a configured-only id "plug_x" is listed with registered False; endpoint
   names in config order ["e1", "e2"].
C  stats route: days 0 -> 1, days 500 -> 90; after one record_call for point
   "p", endpoint "e1" the row (p, e1, '') has calls 1.
D  test route: unknown name -> ok False, error "unknown endpoint".
"""
import asyncio
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_TMP = Path(tempfile.mkdtemp(prefix="smoke_decision_admin_"))
from app.core import paths  # noqa: E402
paths.init(str(_TMP))
from app.core.db import init_schema  # noqa: E402
init_schema()

from app.core import config, decision_log  # noqa: E402
from app.core.config_schema import SECTIONS  # noqa: E402
import app.core.decision_points  # noqa: E402,F401
from app.routes import admin_settings as AS  # noqa: E402

decision_log.LOG_FILE = _TMP / "decisions.jsonl"
FAILS = []


def check(name, got, want):
    ok = got == want
    print(f"  [{'OK  ' if ok else 'FAIL'}] {name}" + ("" if ok else f" — got {got!r}, want {want!r}"))
    if not ok:
        FAILS.append(name)


print("=== A schema ===")
sec = SECTIONS.get("decision") or {}
check("A enabled default", sec.get("fields", {}).get("enabled", {}).get("default"), False)
ep = sec.get("sub_arrays", {}).get("endpoints", {}).get("fields", {})
check("A endpoint fields", sorted(ep), ["api_key", "enabled", "model", "name", "url"])
check("A api_key password", ep.get("api_key", {}).get("type"), "password")
check("A api_key sensitive", ep.get("api_key", {}).get("sensitive"), True)
check("A api_key -> secrets", "api_key" in config.SENSITIVE_FIELDS, True)
check("A pages", [p["id"] for p in sec.get("pages", [])], ["endpoints", "points", "shadow"])
check("A custom pages", [p["id"] for p in sec.get("pages", []) if p.get("custom")], ["points", "shadow"])

print("=== B points ===")
config._CONFIG["decision"] = {"enabled": True,
                              "endpoints": [{"name": "e1", "url": "http://127.0.0.1:1"},
                                            {"name": "e2", "url": "http://127.0.0.1:2"}],
                              "points": {"plug_x": {"mode": "off"}}}
res = AS.settings_decision_points(user=None)
by_id = {p["id"]: p for p in res["points"]}
for pid in ("thought_skip", "pose_match", "expression_match"):
    check(f"B {pid} registered", (by_id.get(pid) or {}).get("registered"), True)
    check(f"B {pid} origin", (by_id.get(pid) or {}).get("origin"), "core")
check("B plug_x unregistered", (by_id.get("plug_x") or {}).get("registered"), False)
check("B endpoints", res["endpoints"], ["e1", "e2"])

print("=== C stats ===")
check("C clamp low", AS.settings_decision_stats(days=0, user=None)["days"], 1)
check("C clamp high", AS.settings_decision_stats(days=500, user=None)["days"], 90)
decision_log.record_call(point="p", mode="shadow", endpoint="e1", key="", step=1, duration_ms=10,
                         error="", answers={"turn": ("idle", 0.9)}, min_confidence=0.7,
                         questions={"turn": "choice"}, server_confidence={}, state_chars=5, trace=None)
rows = [r for r in AS.settings_decision_stats(days=7, user=None)["rows"]
        if (r["point"], r["endpoint"], r["question"]) == ("p", "e1", "")]
check("C calls", rows[0]["calls"] if rows else None, 1)

print("=== D test ===")


class Req:
    async def json(self):
        return {"name": "nope"}


out = asyncio.run(AS.settings_decision_test(Req(), user=None))
check("D unknown", (out["ok"], out["error"]), (False, "unknown endpoint"))

print(f"\n{'ALL CHECKS PASSED' if not FAILS else f'{len(FAILS)} CHECK(S) FAILED'}")
sys.exit(1 if FAILS else 0)
