#!/usr/bin/env python3
"""Smoke: app.core.decision — the Jev-protocol client
(development_instructions/plan-decision-models.md §§ 2, 5, 9).

Usage:  ./.venv/bin/python scripts/smoke_decision_client.py

A fake decision server runs in a thread on 127.0.0.1 (http.server). Its
answers are the REAL shapes measured on 2026-09-23 against jev-serve.py
(spec § 1): the Laya path answers with Laya's confidence semantics
(1 - normalised entropy for choice/score), the openjev path with openjev's
(largest probability). Config is set in memory (config._CONFIG), never written.

EXPECTATIONS, DERIVED BY HAND (own confidence rule, spec § 2.3):
  laya   turn     choice idle, probs act .1321 / idle .8679  -> conf .8679
         addressed noul .2616                                -> value False, conf .7384
         mood     score .5039, probs .6021/.2919/.1060        -> conf .6021
  openjev turn    idle .9917 -> conf .9917; addressed .0028 -> False, conf .9972;
         mood     .315, probs .7195/.2460/.0345               -> conf .7195
A  master switch off            -> None, 0 requests, no JSONL file.
B  unregistered point           -> None, 0 requests.
C  mode off                     -> None, 0 requests.
D  on + laya, min .7            -> keys {turn, addressed} (mood .6021 < .7 dropped).
   Laya's own server confidence for turn is .4369: under THAT rule the answer
   would be dropped — the client must use .8679.
E  on + openjev, min .7         -> keys {turn, addressed, mood}; mood value .315.
F  shadow [laya, openjev]       -> None; after the pool drains: +1 request each.
F2 shadow on /slow (1.5 s)      -> decide returns in < 0.2 s.
G  on [laya, openjev]           -> only laya asked (+1), openjev +0.
H  on /slow, timeout .5         -> None, returns in < 1.4 s.
I  /broken (not JSON) -> None, error bad_json; /badchoice -> schema;
   /badsum (.5 + .6) -> schema; /http500a -> http_500.
J  /http500b: 3 calls -> 3 requests, then blocked: 4th call -> still 3
   requests, endpoint_status blocked_for_s > 0. Block forced to expire ->
   5th call -> 4 requests.
K  Choice with ONE option       -> None, 0 requests.
L  chained on /pose: step 1 group -> seat (.9), then() asks entry -> reading
   (.8) -> answers {group, entry}, 2 requests.
M  same with min .95: group .9 dropped -> then() gets {} -> 1 request, answers {}.
N  request body: model "" and header "Authorization: Bearer k" when api_key "k".
O  probe_endpoint("laya") -> ok, answer value "idle".
P  shadow [laya, openjev] with key; outcome {"turn": "idle"} -> both agree 1.
"""
import json
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_TMP = Path(tempfile.mkdtemp(prefix="smoke_decision_client_"))
from app.core import paths  # noqa: E402
paths.init(str(_TMP))
from app.core.db import init_schema  # noqa: E402
init_schema()
from app.core import config, decision, decision_log  # noqa: E402

decision_log.LOG_FILE = _TMP / "decisions.jsonl"

LAYA = {
    "turn": {"type": "choice", "choice": "idle", "probabilities": {"act": 0.1321, "idle": 0.8679}, "confidence": 0.4369},
    "addressed": {"type": "noul", "noul": 0.2616, "confidence": 0.7384},
    "mood": {"type": "score", "score": 0.5039, "probabilities": {"0": 0.6021, "1": 0.2919, "2": 0.106}, "confidence": 0.1783},
}
OPENJEV = {
    "turn": {"type": "choice", "choice": "idle", "probabilities": {"act": 0.0083, "idle": 0.9917}, "confidence": 0.9917},
    "addressed": {"type": "noul", "noul": 0.0028, "confidence": 0.9972},
    "mood": {"type": "score", "score": 0.315, "probabilities": {"0": 0.7195, "1": 0.246, "2": 0.0345}, "confidence": 0.7195},
}
COUNTS = {}
LAST = {}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        base = self.path.split("/v1/")[0].strip("/")
        COUNTS[base] = COUNTS.get(base, 0) + 1
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        LAST[base] = {"body": body, "auth": self.headers.get("Authorization")}
        qs = body["questions"]
        if base == "slow":
            time.sleep(1.5)
        if base == "broken":
            return self._send(200, b"not json")
        if base.startswith("http500"):
            return self._send(500, b"{}")
        if base in ("laya", "slow"):
            ans = {q: LAYA[q] for q in qs}
        elif base == "openjev":
            ans = {q: OPENJEV[q] for q in qs}
        elif base == "badchoice":
            ans = {"turn": {"type": "choice", "choice": "maybe", "probabilities": {"act": 0.5, "idle": 0.5}}}
        elif base == "badsum":
            ans = {"turn": {"type": "choice", "choice": "idle", "probabilities": {"act": 0.5, "idle": 0.6}}}
        elif base == "pose":
            ans = {}
            for q, spec in qs.items():
                keys = list(spec["criteria"])
                pick = "seat" if q == "group" else "reading"
                rest = [k for k in keys if k != pick]
                hi = 0.9 if q == "group" else 0.8
                probs = {k: (1 - hi) / len(rest) for k in rest}
                probs[pick] = hi
                ans[q] = {"type": "choice", "choice": pick, "probabilities": probs}
        else:
            ans = {}
        self._send(200, json.dumps({"answers": ans}).encode())

    def _send(self, code, data):
        self.send_response(code)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_address[1]}"
NAMES = ["laya", "openjev", "slow", "broken", "badchoice", "badsum", "http500a", "http500b", "pose"]

FAILS = []


def check(name, got, want):
    ok = got == want
    print(f"  [{'OK  ' if ok else 'FAIL'}] {name}" + ("" if ok else f" — got {got!r}, want {want!r}"))
    if not ok:
        FAILS.append(name)


def setup(enabled=True, points=None, api_key=""):
    config._CONFIG["decision"] = {
        "enabled": enabled,
        "endpoints": [{"name": n, "url": f"{BASE}/{n}", "api_key": api_key if n == "laya" else "",
                       "model": "", "enabled": True} for n in NAMES],
        "points": points or {},
    }


def n(base):
    return COUNTS.get(base, 0)


Q3 = {"turn": decision.Choice("Reason to act?", {"act": "yes", "idle": "no"}),
      "addressed": decision.Noul("Was Kira addressed?"),
      "mood": decision.Score("How tense?", ["calm", "medium", "very tense"])}
STATE = {"document": "Kira sits alone in the kitchen."}
for p in ("t_on", "t_shadow", "t_off", "t_pose"):
    decision.register_point(p, label=p, description="smoke")

print("=== A-C gates ===")
setup(enabled=False, points={"t_on": {"mode": "on", "endpoints": ["laya"]}})
check("A master off -> None", decision.decide("t_on", STATE, Q3), None)
check("A 0 requests", n("laya"), 0)
check("A no jsonl", decision_log.LOG_FILE.exists(), False)
setup(points={"t_on": {"mode": "on", "endpoints": ["laya"]}})
check("B unregistered -> None", decision.decide("nope", STATE, Q3), None)
setup(points={"t_off": {"mode": "off", "endpoints": ["laya"]}})
check("C mode off -> None", decision.decide("t_off", STATE, Q3), None)
check("B/C 0 requests", n("laya"), 0)

print("=== D/E confidence rule ===")
setup(points={"t_on": {"mode": "on", "endpoints": ["laya"], "min_confidence": 0.7}})
d = decision.decide("t_on", STATE, Q3)
check("D keys", sorted(d.answers) if d else None, ["addressed", "turn"])
check("D turn conf", round(d.answers["turn"].confidence, 4), 0.8679)
check("D addressed value", d.answers["addressed"].value, False)
check("D addressed conf", round(d.answers["addressed"].confidence, 4), 0.7384)
setup(points={"t_on": {"mode": "on", "endpoints": ["openjev"], "min_confidence": 0.7}})
d = decision.decide("t_on", STATE, Q3)
check("E keys", sorted(d.answers) if d else None, ["addressed", "mood", "turn"])
check("E mood value", d.answers["mood"].value, 0.315)

print("=== F/G modes ===")
setup(points={"t_shadow": {"mode": "shadow", "endpoints": ["laya", "openjev"]}})
l0, o0 = n("laya"), n("openjev")
check("F shadow -> None", decision.decide("t_shadow", STATE, Q3), None)
decision._wait_shadow(5)
check("F laya +1", n("laya") - l0, 1)
check("F openjev +1", n("openjev") - o0, 1)
setup(points={"t_shadow": {"mode": "shadow", "endpoints": ["slow"], "timeout_s": 3}})
t0 = time.monotonic()
decision.decide("t_shadow", STATE, {"turn": Q3["turn"]})
check("F2 shadow returns fast", time.monotonic() - t0 < 0.2, True)
decision._wait_shadow(5)
setup(points={"t_on": {"mode": "on", "endpoints": ["laya", "openjev"]}})
l0, o0 = n("laya"), n("openjev")
decision.decide("t_on", STATE, Q3)
check("G laya +1", n("laya") - l0, 1)
check("G openjev +0", n("openjev") - o0, 0)

print("=== H/I failures ===")
setup(points={"t_on": {"mode": "on", "endpoints": ["slow"], "timeout_s": 0.5}})
t0 = time.monotonic()
check("H timeout -> None", decision.decide("t_on", STATE, {"turn": Q3["turn"]}), None)
check("H returns < 1.4 s", time.monotonic() - t0 < 1.4, True)
for name, err in (("broken", "bad_json"), ("badchoice", "schema"), ("badsum", "schema"), ("http500a", "http_500")):
    setup(points={"t_on": {"mode": "on", "endpoints": [name]}})
    check(f"I {name} -> None", decision.decide("t_on", STATE, {"turn": Q3["turn"]}), None)
    rows = [r for r in decision_log.query_stats(1) if r["endpoint"] == name and r["question"] == ""]
    check(f"I {name} error {err}", rows[0]["errors"].get(err) if rows else None, 1)

print("=== J blocking ===")
setup(points={"t_on": {"mode": "on", "endpoints": ["http500b"]}})
for _ in range(4):
    decision.decide("t_on", STATE, {"turn": Q3["turn"]})
check("J 3 requests then blocked", n("http500b"), 3)
check("J status blocked", decision.endpoint_status().get("http500b", {}).get("blocked_for_s", 0) > 0, True)
decision._blocked_until["http500b"] = time.monotonic() - 1
decision.decide("t_on", STATE, {"turn": Q3["turn"]})
check("J released", n("http500b"), 4)

print("=== K invalid question ===")
setup(points={"t_on": {"mode": "on", "endpoints": ["laya"]}})
l0 = n("laya")
check("K one option -> None", decision.decide("t_on", STATE, {"turn": decision.Choice("x", {"a": "a"})}), None)
check("K 0 requests", n("laya") - l0, 0)

print("=== L/M chained ===")
GROUPS = decision.Choice("Body position?", {"stand": "Standing", "seat": "Seat", "ground": "Ground", "lie": "Lying"})


def then(ans):
    if "group" in ans:
        return {"entry": decision.Choice("Pose?", {"reading": "reading", "sitting": "sitting", "none": "none"})}
    return None


setup(points={"t_pose": {"mode": "on", "endpoints": ["pose"], "min_confidence": 0.6}})
d = decision.decide("t_pose", {"text": "sits and reads"}, {"group": GROUPS}, then=then)
check("L answers", sorted(d.answers) if d else None, ["entry", "group"])
check("L entry", d.answers["entry"].value, "reading")
check("L 2 requests", n("pose"), 2)
setup(points={"t_pose": {"mode": "on", "endpoints": ["pose"], "min_confidence": 0.95}})
d = decision.decide("t_pose", {"text": "sits and reads"}, {"group": GROUPS}, then=then)
check("M answers empty", d.answers if d else None, {})
check("M 1 more request", n("pose"), 3)

print("=== N/O request shape, probe ===")
setup(points={"t_on": {"mode": "on", "endpoints": ["laya"]}}, api_key="k")
decision.decide("t_on", STATE, {"turn": Q3["turn"]})
check("N model empty", LAST["laya"]["body"]["model"], "")
check("N bearer", LAST["laya"]["auth"], "Bearer k")
pr = decision.probe_endpoint("laya")
check("O probe ok", pr["ok"], True)
check("O probe value", (pr["answer"] or {}).get("value"), "idle")

print("=== P shadow + outcome ===")
setup(points={"t_shadow": {"mode": "shadow", "endpoints": ["laya", "openjev"], "min_confidence": 0.7}})
decision.decide("t_shadow", STATE, {"turn": Q3["turn"]}, key="k1")
decision._wait_shadow(5)
decision.record_outcome("t_shadow", "k1", {"turn": "idle"})
rows = {r["endpoint"]: r for r in decision_log.query_stats(1) if r["point"] == "t_shadow" and r["question"] == "turn"}
check("P laya agree", rows.get("laya", {}).get("agree"), 1)
check("P openjev agree", rows.get("openjev", {}).get("agree"), 1)

srv.shutdown()
print(f"\n{'ALL CHECKS PASSED' if not FAILS else f'{len(FAILS)} CHECK(S) FAILED'}")
sys.exit(1 if FAILS else 0)
