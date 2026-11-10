#!/usr/bin/env python3
"""Smoke: deleting one model's tools-test result removes exactly that model's
result, history and raw answers.

Usage: ./.venv/bin/python scripts/smoke_model_test_delete.py

No server, no network; the capability file and its sidecar are redirected
to a temp dir (the real shared/config files are never touched).

Fixture: models "P::A" and "P::B" each have a current result, "P::A" also
one history entry, raw answers and raw history, plus an RP result.
Expectations, from delete_suitability (pop the key from suitability,
suitability_history, outputs and history; nothing else):
[1] delete_suitability("p::a") -> True (keys are lowercased); A is gone from
    suitability, suitability_history, outputs and history.
[2] B's result and raw answers stay; A's RP result stays (other table).
[3] get_all_suitability() no longer lists A, still lists B (cache invalidated).
[4] a second delete -> False, and the file keeps B.
[5] the route answers {"deleted": True} for B and 400 without a model.
"""
import asyncio
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import paths
paths.init(tempfile.mkdtemp(prefix="smoke_test_delete_world_"))
paths.init_instance(tempfile.mkdtemp(prefix="smoke_test_delete_instance_"))

from app.core import model_capabilities as mc

tmp = Path(tempfile.mkdtemp(prefix="smoke_test_delete_"))
caps, outputs = tmp / "caps.json", tmp / "outputs.json"
mc._caps_path = lambda: caps
mc._outputs_path = lambda: outputs
mc.invalidate_cache()

CURRENT = {"tested_suitability": {"scorer_version": "suitability-6", "model": "P::A"}}
caps.write_text(json.dumps({
    "models": {},
    "suitability": {"p::a": CURRENT, "p::b": {"tested_suitability": {"scorer_version": "suitability-6"}}},
    "suitability_history": {"p::a": [CURRENT]},
    "rp_results": {"p::a": {"overall": 90}},
}), encoding="utf-8")
outputs.write_text(json.dumps({
    "outputs": {"p::a": {"run_id": "1"}, "p::b": {"run_id": "2"}},
    "history": {"p::a": [{"run_id": "0"}]},
    "rp_outputs": {"p::a": {"run_id": "r"}},
}), encoding="utf-8")

assert mc.delete_suitability("P::A") is True, "[1]"
data, raw = json.loads(caps.read_text()), json.loads(outputs.read_text())
assert "p::a" not in data["suitability"] and "p::a" not in data["suitability_history"], data
assert "p::a" not in raw["outputs"] and "p::a" not in raw["history"], raw
print("[1] the model's result, history and raw answers are gone — PASS")

assert "p::b" in data["suitability"] and "p::b" in raw["outputs"], (data, raw)
assert data["rp_results"]["p::a"] == {"overall": 90} and "p::a" in raw["rp_outputs"], (data, raw)
print("[2] other models and the roleplay table stay — PASS")

listed = mc.get_all_suitability()
assert "p::a" not in listed and "p::b" in listed, listed
print("[3] the listing follows at once — PASS")

assert mc.delete_suitability("P::A") is False, "[4]"
assert "p::b" in json.loads(caps.read_text())["suitability"], "[4]"
print("[4] a second delete reports nothing deleted — PASS")

from fastapi import HTTPException
from app.routes.admin_settings import llm_suitability_delete


class Req:
    def __init__(self, body):
        self.body = body

    async def json(self):
        return self.body


assert asyncio.run(llm_suitability_delete(Req({"model": "P::B"}), user=None)) == {"deleted": True}, "[5]"
try:
    asyncio.run(llm_suitability_delete(Req({}), user=None))
    raise AssertionError("[5] no 400")
except HTTPException as exc:
    assert exc.status_code == 400, exc
print("[5] the route deletes and rejects a missing model — PASS")
print("ALL OK")
