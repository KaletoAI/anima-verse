#!/usr/bin/env python3
"""Smoke: the quest type catalog (`app/core/quest_catalog.py`).

Quest system stage 1, Task 2. No storage, no server, no LLM: the catalog is a
pure registry on `hooks.register_provider` plus expression walking. All
types here are STUBS registered by two fake owners "A" and "B"; every expected
value is derived by hand from the plan's Task 2 interface and D5/D7, not
recorded from a run.

Usage:
    ./.venv/bin/python scripts/smoke_quest_catalog.py

WHAT IS CHECKED, and where every expected value comes from
----------------------------------------------------------

  (a) REGISTRATION. Owner A's contributor returns two types ("a_one",
      "a_two"), owner B's one ("b_one") → all three ids are in `types()`,
      `get("a_one").kind == "condition"`. A second contributor that answers an
      id already taken ("a_one" again, registered by owner "DUP" after A) does
      NOT replace it (duplicate id: first wins) and is logged as ONE warning
      naming the id, even though the catalog is rebuilt on each of the
      following calls (types() twice, get() once). `catalog_payload()` puts "a_one" under
      "conditions" and the prerequisite "b_one" under "prerequisites", and its
      descriptors carry no callable (json.dumps succeeds).

  (b) OWNER CLEANUP. DUP is unregistered first (else its "a_one" would take
      over), then `hooks.unregister_owned_providers("A")` → "a_one" and "a_two"
      are gone, "b_one" stays. The catalog is rebuilt on every call (no
      cache), so the removal is visible at once, without any other call.

  (c) ISOLATION. A contributor of owner "BOOM" that raises → `types()` still holds
      "b_one", and the failure is logged (one ERROR record).

  (d) check_expression TABLE. Roles: giver (character), place (room),
      thing (item). Stub type "at" (condition) has params
      `place` (role, role_kinds [location, room], required) and `count`
      (int, min 1, max 5, default 1). Stub "pre" is a prerequisite.
      Paths are relative to the expression root (D7): a root leaf's issue is
      ".type" or ".params.<key>", inside groups ".all.<i>", ".not".
        {"type": "nope"}                               → unknown_type   at ".type"
        at, place="ghost"                              → unknown_role   at ".params.place"
        at, place="thing" (an item)                    → wrong_role_kind at ".params.place"
        at, params {}                                  → missing_param  at ".params.place"
        at, place="place", count=0 (0 < min 1)         → bad_param      at ".params.count"
        {"all": "x"}                                   → shape          at ""
        {"type": "pre"} with allowed_kinds ("condition",) → wrong_kind  at ".type"
        the same with ("condition", "prerequisite")    → []
        {"all": [at(place), {"not": at(place, count=2)}]} → []
        {"any": [at(place), {"not": {"type": "nope"}}]} → unknown_type at ".any.1.not.type"
        {}                                             → []
      A type's own validate (stub "v", param n: int, default 3):
        validate answers ConditionIssue("too_far", ...) → [("too_far", ".type")]
        validate raises                                → [("bad_param", ".type")]
        validate answers a non-issue (a str)           → [("bad_param", ".type")] (never raises out)
        n="x" (a generic bad_param)                    → [("bad_param", ".params.n")] and validate
                                                         is NOT called (its call counter stays 0)
        validate receives n=3 when n is omitted and when n is None (the default).

  (d2) DEFAULTS REACH evaluate. Stub "cnt" (param count: int, default 1)
      records the params evaluate gets: {"count": None} → count 1,
      {} → count 1, {"count": 4} → count 4. A None / blank value is "absent"
      for the check, so it must not hide the default in evaluation either.

  (e) evaluate_expression TRUTH TABLE (Review Focus 5), stub types
      T (passes), F (fails), U (unavailable), X (evaluate raises):
        all[T,T]=(True,True)  all[T,F]=(True,False)  any[F,T]=(True,True)
        any[T,U]=(False,False) — unavailable is contagious even though T passes
        not F=(True,True)  not U=(False,False)  X=(False,False)  {}=(True,True)
        an unregistered type id → (False,False) with "not registered" in the reason.
      Every child is evaluated: all[F,T] calls T too (a counter on T rises by 1).

  (f) signals_of. T declares ("s.one",), F ("s.two",), U ("s.one", "s.three")
      → signals_of({"all": [T, {"not": F}, {"any": [U]}]}) ==
      {"s.one", "s.two", "s.three"} (the union); an unknown type adds nothing.
"""
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app  # noqa: E402

assert Path(app.__file__).resolve().is_relative_to(ROOT), \
    f"app imported from {app.__file__}, not from {ROOT}"

from app.core import hooks  # noqa: E402
from app.core import quest_catalog as qc  # noqa: E402
from app.core.activity_engine import ConditionResult  # noqa: E402

failures = []


def check(label, cond, detail=""):
    if not cond:
        failures.append(label)
    print(("  ok   " if cond else "  FAIL ") + label + (f" — {detail}" if detail and not cond else ""))


class _Capture(logging.Handler):
    """Keeps the catalog's log records (the deliberate failures stay out of the output)."""

    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


cap = _Capture()
_log = logging.getLogger("quest_catalog")
_log.addHandler(cap)
_log.propagate = False


def stub(type_id, kind="condition", **kw):
    return qc.QuestType(id=type_id, kind=kind, label=type_id.upper(), description=f"stub {type_id}", **kw)


# --- (a) registration ---------------------------------------------------------------
print("(a) registration")
qc.register("A", lambda: [stub("a_one"), stub("a_two", signals=("s.a",))])
qc.register("B", lambda: [stub("b_one", kind="prerequisite")])
qc.register("DUP", lambda: [stub("a_one", kind="effect")])
cap.records.clear()
ids = set(qc.types())
qc.types()
check("a_one, a_two, b_one listed", {"a_one", "a_two", "b_one"} <= ids, str(ids))
check("get(a_one) is A's condition, not DUP's effect", (qc.get("a_one") or stub("x", "effect")).kind == "condition")
dup_logs = [r for r in cap.records if r.levelno == logging.WARNING and "a_one" in r.getMessage()]
check("duplicate id logged once as a warning", len(dup_logs) == 1, str([r.getMessage() for r in cap.records]))
payload = qc.catalog_payload()
check("payload keys", set(payload) == {"conditions", "prerequisites", "effects"}, str(set(payload)))
check("a_one under conditions", "a_one" in [d["id"] for d in payload["conditions"]])
check("b_one under prerequisites", [d["id"] for d in payload["prerequisites"]] == ["b_one"])
try:
    json.dumps(payload)
    ok = True
except TypeError:
    ok = False
check("payload is JSON-safe", ok)
check("descriptor keys", set(qc.public_descriptor(qc.get("a_two"))) ==
      {"id", "kind", "label", "description", "params", "signals"})
check("descriptor signals is a list", qc.public_descriptor(qc.get("a_two"))["signals"] == ["s.a"])

# --- (b) owner cleanup ---------------------------------------------------------------
print("(b) owner cleanup")
hooks.unregister_owned_providers("DUP")
hooks.unregister_owned_providers("A")
ids = set(qc.types())
check("A's types gone", not ({"a_one", "a_two"} & ids), str(ids))
check("B's type stays", "b_one" in ids)
check("get(a_one) is None", qc.get("a_one") is None)

# --- (c) isolation ---------------------------------------------------------------------
print("(c) isolation")


def _boom():
    raise RuntimeError("contributor exploded")


qc.register("BOOM", _boom)
cap.records.clear()
ids = set(qc.types())
check("raising contributor does not hide B", "b_one" in ids, str(ids))
check("failure logged as one ERROR", len([r for r in cap.records if r.levelno == logging.ERROR]) == 1)
hooks.unregister_owned_providers("BOOM")
hooks.unregister_owned_providers("B")

# --- (d) check_expression ------------------------------------------------------------
print("(d) check_expression")
AT_PARAMS = (
    {"key": "place", "type": "role", "label": "Place", "role_kinds": ["location", "room"], "required": True},
    {"key": "count", "type": "int", "label": "Count", "min": 1, "max": 5, "default": 1},
)
qc.register("C", lambda: [stub("at", params=AT_PARAMS), stub("pre", kind="prerequisite")])
ROLES = [{"key": "giver", "kind": "character"}, {"key": "place", "kind": "room"},
         {"key": "thing", "kind": "item"}]
COND = ("condition",)


def at(**params):
    return {"type": "at", "params": params}


def codes(expr, kinds=COND):
    return [(i["code"], i["path"]) for i in qc.check_expression(expr, ROLES, allowed_kinds=kinds)]


TABLE = [
    ("unknown type", {"type": "nope", "params": {}}, COND, [("unknown_type", ".type")]),
    ("undeclared role", at(place="ghost"), COND, [("unknown_role", ".params.place")]),
    ("item role where location/room wanted", at(place="thing"), COND, [("wrong_role_kind", ".params.place")]),
    ("required param absent", at(), COND, [("missing_param", ".params.place")]),
    ("int below min", at(place="place", count=0), COND, [("bad_param", ".params.count")]),
    ("all is not a list", {"all": "x"}, COND, [("shape", "")]),
    ("prerequisite type in a step position", {"type": "pre", "params": {}}, COND, [("wrong_kind", ".type")]),
    ("prerequisite type in a prerequisite position", {"type": "pre", "params": {}},
     ("condition", "prerequisite"), []),
    ("valid nested", {"all": [at(place="place"), {"not": at(place="place", count=2)}]}, COND, []),
    ("nested unknown path", {"any": [at(place="place"), {"not": {"type": "nope", "params": {}}}]}, COND,
     [("unknown_type", ".any.1.not.type")]),
    ("empty expression", {}, COND, []),
]
for label, expr, kinds, want in TABLE:
    got = codes(expr, kinds)
    check(f"{label} → {want}", got == want, str(got))
for issue in qc.check_expression(at(place="ghost"), ROLES, allowed_kinds=COND):
    check("issue has path/code/message", set(issue) == {"path", "code", "message"} and issue["message"])
hooks.unregister_owned_providers("C")

from app.core.activity_engine import ConditionIssue  # noqa: E402

vstate = {"mode": "issue", "calls": 0, "seen": []}


def _validate(params, bindings):
    vstate["calls"] += 1
    vstate["seen"].append(params.get("n"))
    if vstate["mode"] == "raise":
        raise RuntimeError("validate exploded")
    if vstate["mode"] == "junk":
        return ["not an issue"]
    if vstate["mode"] == "ok":
        return []
    return [ConditionIssue("too_far", "n is too far")]


V_PARAMS = ({"key": "n", "type": "int", "label": "N", "default": 3},)
qc.register("V", lambda: [stub("v", params=V_PARAMS, validate=_validate)])
vstate["mode"] = "issue"
got = codes({"type": "v", "params": {}})
check("validate issue reported at .type", got == [("too_far", ".type")], str(got))
vstate["mode"] = "raise"
check("raising validate → bad_param at .type", codes({"type": "v", "params": {}}) == [("bad_param", ".type")])
vstate["mode"] = "junk"
check("non-issue answer → bad_param at .type", codes({"type": "v", "params": {}}) == [("bad_param", ".type")])
vstate.update(mode="ok", calls=0)
check("generic issue → bad_param at .params.n", codes({"type": "v", "params": {"n": "x"}}) ==
      [("bad_param", ".params.n")])
check("validate not called after a generic issue", vstate["calls"] == 0, str(vstate))
vstate["seen"].clear()
codes({"type": "v", "params": {}})
codes({"type": "v", "params": {"n": None}})
check("validate gets the default for omitted and None", vstate["seen"] == [3, 3], str(vstate["seen"]))
hooks.unregister_owned_providers("V")

print("(d2) defaults reach evaluate")
got_params = []


def _cnt(params, ctx):
    got_params.append(dict(params))
    return ConditionResult(True, True, "")


qc.register("D", lambda: [stub("cnt", params=({"key": "count", "type": "int", "default": 1},), evaluate=_cnt)])
for given, want in (({"count": None}, 1), ({}, 1), ({"count": 4}, 4)):
    got_params.clear()
    qc.evaluate_expression({"type": "cnt", "params": given}, None)
    check(f"evaluate params {given} → count {want}", got_params == [{"count": want}], str(got_params))
hooks.unregister_owned_providers("D")

# --- (e) evaluate_expression truth table ------------------------------------------------
print("(e) evaluate_expression")
calls = {"T": 0}


def _t(params, ctx):
    calls["T"] += 1
    return ConditionResult(True, True, "")


def _x(params, ctx):
    raise RuntimeError("evaluate exploded")


qc.register("E", lambda: [
    stub("T", evaluate=_t, signals=("s.one",)),
    stub("F", evaluate=lambda p, c: ConditionResult(True, False, "no"), signals=("s.two",)),
    stub("U", evaluate=lambda p, c: ConditionResult(False, False, "unknown"), signals=("s.one", "s.three")),
    stub("X", evaluate=_x),
])


def leaf(t):
    return {"type": t, "params": {}}


def ev(expr):
    r = qc.evaluate_expression(expr, None)
    return (r.available, r.passed)


TRUTH = [
    ("all[T,T]", {"all": [leaf("T"), leaf("T")]}, (True, True)),
    ("all[T,F]", {"all": [leaf("T"), leaf("F")]}, (True, False)),
    ("any[F,T]", {"any": [leaf("F"), leaf("T")]}, (True, True)),
    ("any[T,U]", {"any": [leaf("T"), leaf("U")]}, (False, False)),
    ("not F", {"not": leaf("F")}, (True, True)),
    ("not U", {"not": leaf("U")}, (False, False)),
    ("X", leaf("X"), (False, False)),
    ("{}", {}, (True, True)),
]
for label, expr, want in TRUTH:
    got = ev(expr)
    check(f"{label} = {want}", got == want, str(got))
r = qc.evaluate_expression(leaf("gone"), None)
check("unregistered type unavailable", (r.available, r.passed) == (False, False) and "not registered" in r.reason,
      repr(r))
calls["T"] = 0
qc.evaluate_expression({"all": [leaf("F"), leaf("T")]}, None)
check("all[F,T] evaluates T too", calls["T"] == 1, str(calls))

# --- (f) signals_of -----------------------------------------------------------------
print("(f) signals_of")
got = qc.signals_of({"all": [leaf("T"), {"not": leaf("F")}, {"any": [leaf("U"), leaf("nope")]}]})
check("union of nested signals", got == {"s.one", "s.two", "s.three"}, str(got))
hooks.unregister_owned_providers("E")

print()
if failures:
    print(f"FAIL — {len(failures)} check(s): {failures}")
    sys.exit(1)
print("PASS — quest catalog")
