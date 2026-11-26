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
      "b_one", and the failure is logged (one ERROR record). `types(strict=True)` re-raises the same
      RuntimeError instead (the tick's reference check reads a hiccup as "skip", never as "type gone").

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
      Depth cap (review R5, MAX_DEPTH 16; the root is depth 0, each group level +1):
        at(place) under 16 nested "not"s (the leaf at depth 16) → []
        the same under 17 "not"s → ONE issue ("shape", ".not" x 17) — the node at depth 17 is not entered
        the same under 1200 "not"s → still that one issue, and no RecursionError (one Python frame per level
        would exceed the default limit of 1000)
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

  (g) EFFECTS & TARGET PARAM (stage 2, Task 2; D2, D4, D12). Owner "test" registers
      effect stubs mk_item (object_kind "item", param name: str req), put
      (object_kind "room_item", param item: target role_kinds [item] object_kinds
      [item] req), create_prop (object_kind "world_prop", param name: str req);
      condition stubs g_cond (no params) and g_near (param obj: target role_kinds []
      object_kinds [world_prop] req). Roles: giver=character, thing=item.
      check_effects (path "setup_effects", reward False unless noted):
        1. [mk_item key "giver"] (role namespace clash)   → [("duplicate", "setup_effects.0.key")]
        2. [mk_item key "Box"] (uppercase violates regex) → [("bad_key", "setup_effects.0.key")]
        3. [type "nope" key "a"]                          → [("unknown_type", "setup_effects.0.type")]
                                                            with "Unknown effect type" in message
        4. [g_cond key "a"] (condition in effect list)    → [("wrong_kind", "setup_effects.0.type")]
        5. [put "p" item="b", mk_item "b"] (forward ref)  → [("not_yet_created", "setup_effects.0.params.item")]
        6. [create_prop "pr", put "p" item="pr"] (kind)   → [("wrong_kind", "setup_effects.1.params.item")]
        7. [put "p" item="thing"] (item role accepted)    → []
        8. [put "p" item="giver"] (character role wrong)  → [("wrong_kind", "setup_effects.0.params.item")]
        9. [put "p" item="ghost"] (nowhere in scope)      → [("unknown_target", "setup_effects.0.params.item")]
       10. reward=True path "rewards" permanent=False     → [("not_allowed_here", "rewards.0.permanent")];
           same with reward=False path "setup_effects"    → [];
           reward=True permanent omitted                  → [];
           permanent="yes" (reward=False)                 → [("bad_value", "setup_effects.0.permanent")]
       11. 21 mk_item entries e0..e20 (> MAX_EFFECTS 20)  → [("too_many", "setup_effects")]
       12. 4 create_prop p0..p3 (> MAX_CREATE_PROP 3)     → [("too_many", "setup_effects.3.type")];
           1 create_prop with props_before=3              → [("too_many", "setup_effects.0.type")]
       13. [mk_item "a", mk_item "a"] (same-list dup)     → [("duplicate", "setup_effects.1.key")]
       14. ["x"]                                          → [("shape", "setup_effects.0")];
           [mk_item "a" + extra key "foo"]                → [("shape", "setup_effects.0")];
           [mk_item without "key"]                        → [("required", "setup_effects.0.key")];
           {} (not a list)                                → [("shape", "setup_effects")]
      Target in a condition: check_expression(g_near(obj=X), Scope(roles, {pr:world_prop, it:item}, {zz}),
      allowed_kinds=("condition",)): X="pr" → []; X="it" → [("wrong_kind", ".params.obj")];
      X="zz" → [("not_yet_created", ".params.obj")]; X="nope" → [("unknown_target", ".params.obj")];
      X="thing" → [("wrong_kind", ".params.obj")] (role_kinds empty → no role accepted).
      public_descriptor(mk_item)["object_kind"] == "item" and json.dumps succeeds;
      "target" in PARAM_TYPES.
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
      {"id", "kind", "label", "description", "params", "signals", "needs_open_run", "object_kind"})
check("needs_open_run defaults to False", qc.public_descriptor(qc.get("a_two"))["needs_open_run"] is False)
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
try:
    qc.types(strict=True)
    strict_raised = ""
except RuntimeError as e:
    strict_raised = str(e)
check("types(strict=True) re-raises", strict_raised == "contributor exploded", strict_raised)
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


ROLE_SCOPE = qc.Scope({r["key"]: r["kind"] for r in ROLES}, {})


def at(**params):
    return {"type": "at", "params": params}


def codes(expr, kinds=COND):
    return [(i["code"], i["path"]) for i in qc.check_expression(expr, ROLE_SCOPE, allowed_kinds=kinds)]


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


def nested_not(depth):
    expr = at(place="place")
    for _ in range(depth):
        expr = {"not": expr}
    return expr


check("16 nested nots → []", codes(nested_not(16)) == [], str(codes(nested_not(16))))
check("17 nested nots → one shape issue at the 17th level",
      codes(nested_not(17)) == [("shape", ".not" * 17)], str(codes(nested_not(17))))
try:
    deep = codes(nested_not(1200))
except RecursionError:
    deep = "RecursionError"
check("1200 nested nots → the same one issue, no RecursionError", deep == [("shape", ".not" * 17)], str(deep)[:80])
for issue in qc.check_expression(at(place="ghost"), ROLE_SCOPE, allowed_kinds=COND):
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

# --- (g) effects and target param ---------------------------------------------------
print("(g) effects and target param")
G_ROLES = {"giver": "character", "thing": "item"}
G_KINDS = {"mk_item": "item", "put": "room_item", "create_prop": "world_prop"}
qc.register("test", lambda: [
    stub("mk_item", kind="effect", object_kind="item",
         params=({"key": "name", "type": "str", "label": "Name", "required": True},)),
    stub("put", kind="effect", object_kind="room_item",
         params=({"key": "item", "type": "target", "label": "Item",
                  "role_kinds": ["item"], "object_kinds": ["item"], "required": True},)),
    stub("create_prop", kind="effect", object_kind="world_prop",
         params=({"key": "name", "type": "str", "label": "Name", "required": True},)),
    stub("g_cond", kind="condition"),
    stub("g_near", kind="condition",
         params=({"key": "obj", "type": "target", "label": "Obj",
                  "role_kinds": [], "object_kinds": ["world_prop"], "required": True},)),
])


def _scope_for(entries):
    def _at(i):
        objects = {}
        for e in entries[:i]:
            if isinstance(e, dict) and isinstance(e.get("key"), str) and e["key"] and e["key"] not in objects:
                objects[e["key"]] = G_KINDS.get(e.get("type"), "")
        later = frozenset(
            e["key"] for e in entries[i:]
            if isinstance(e, dict) and isinstance(e.get("key"), str) and e["key"] and e["key"] not in objects
        )
        return qc.Scope(G_ROLES, objects, later)
    return _at


def eff_codes(entries, *, path="setup_effects", reward=False, props_before=0):
    sf = _scope_for(entries) if isinstance(entries, list) else (lambda _i: qc.Scope(G_ROLES, {}))
    return sorted((i["code"], i["path"]) for i in
                  qc.check_effects(entries, sf, path=path, reward=reward, props_before=props_before))


def mk_item(key, **extra):
    return {"key": key, "type": "mk_item", "params": {"name": "Box"}, **extra}


def put(key, item, **extra):
    return {"key": key, "type": "put", "params": {"item": item}, **extra}


def mk_prop(key, **extra):
    return {"key": key, "type": "create_prop", "params": {"name": "Rock"}, **extra}


check("1. key collides with role", eff_codes([mk_item("giver")]) == [("duplicate", "setup_effects.0.key")],
      str(eff_codes([mk_item("giver")])))
check("2. bad_key uppercase", eff_codes([mk_item("Box")]) == [("bad_key", "setup_effects.0.key")],
      str(eff_codes([mk_item("Box")])))
unk_issues = qc.check_effects([{"key": "a", "type": "nope", "params": {}}],
                              _scope_for([{"key": "a", "type": "nope", "params": {}}]),
                              path="setup_effects", reward=False)
check("3. unknown effect type",
      sorted((i["code"], i["path"]) for i in unk_issues) == [("unknown_type", "setup_effects.0.type")]
      and "Unknown effect type" in unk_issues[0]["message"],
      str(unk_issues))
check("4. condition in effect list",
      eff_codes([{"key": "a", "type": "g_cond", "params": {}}]) == [("wrong_kind", "setup_effects.0.type")])
check("5. forward ref not_yet_created",
      eff_codes([put("p", "b"), mk_item("b")]) == [("not_yet_created", "setup_effects.0.params.item")])
check("6. wrong object_kind",
      eff_codes([mk_prop("pr"), put("p", "pr")]) == [("wrong_kind", "setup_effects.1.params.item")])
check("7. role key of accepted kind passes", eff_codes([put("p", "thing")]) == [])
check("8. role key of wrong kind",
      eff_codes([put("p", "giver")]) == [("wrong_kind", "setup_effects.0.params.item")])
check("9. unknown target",
      eff_codes([put("p", "ghost")]) == [("unknown_target", "setup_effects.0.params.item")])
check("10a. reward permanent=False refused",
      eff_codes([mk_item("a", permanent=False)], path="rewards", reward=True)
      == [("not_allowed_here", "rewards.0.permanent")])
check("10b. setup permanent=False ok", eff_codes([mk_item("a", permanent=False)]) == [])
check("10c. reward permanent omitted ok", eff_codes([mk_item("a")], path="rewards", reward=True) == [])
check("10d. permanent non-bool bad_value",
      eff_codes([mk_item("a", permanent="yes")]) == [("bad_value", "setup_effects.0.permanent")])
check("11. >20 effects too_many",
      eff_codes([mk_item(f"e{i}") for i in range(21)]) == [("too_many", "setup_effects")])
check("12a. 4 create_prop too_many",
      eff_codes([mk_prop(f"p{i}") for i in range(4)]) == [("too_many", "setup_effects.3.type")])
check("12b. props_before=3 + 1 create_prop too_many",
      eff_codes([mk_prop("p0")], props_before=3) == [("too_many", "setup_effects.0.type")])
check("13. same-list duplicate key",
      eff_codes([mk_item("a"), mk_item("a")]) == [("duplicate", "setup_effects.1.key")])
check("14a. non-dict entry shape", eff_codes(["x"]) == [("shape", "setup_effects.0")])
check("14b. extra entry key shape",
      eff_codes([{**mk_item("a"), "foo": 1}]) == [("shape", "setup_effects.0")])
check("14c. missing key required",
      eff_codes([{"type": "mk_item", "params": {"name": "Box"}}]) == [("required", "setup_effects.0.key")])
check("14d. non-list effects shape", eff_codes({}) == [("shape", "setup_effects")])

g_scope = qc.Scope({"giver": "character", "thing": "item"}, {"pr": "world_prop", "it": "item"}, frozenset({"zz"}))
for target_val, want in (
    ("pr", []),
    ("it", [("wrong_kind", ".params.obj")]),
    ("zz", [("not_yet_created", ".params.obj")]),
    ("nope", [("unknown_target", ".params.obj")]),
    ("thing", [("wrong_kind", ".params.obj")]),
):
    got_t = sorted((i["code"], i["path"]) for i in
                   qc.check_expression({"type": "g_near", "params": {"obj": target_val}}, g_scope,
                                       allowed_kinds=("condition",)))
    check(f"condition target {target_val!r} → {want}", got_t == want, str(got_t))

desc = qc.public_descriptor(qc.get("mk_item"))
check("public_descriptor has object_kind", desc.get("object_kind") == "item", str(desc))
try:
    json.dumps(desc)
    desc_json_ok = True
except TypeError:
    desc_json_ok = False
check("public_descriptor of mk_item is JSON-safe", desc_json_ok)
check("'target' in PARAM_TYPES", "target" in qc.PARAM_TYPES)
hooks.unregister_owned_providers("test")

print()
if failures:
    print(f"FAIL — {len(failures)} check(s): {failures}")
    sys.exit(1)
print("PASS — quest catalog")
