#!/usr/bin/env python3
"""Smoke: chain resolution of the central image routing (app/imagegen/routing.py).

Usage:  ./.venv/bin/python scripts/smoke_image_routing_resolve.py

Spec: development_instructions/plan-image-routing.md § 3 + review notes, and
the binding coordinator decision 2 / plan review B1+B2 (the INTENDED entry).
No server, no network, no world DB: fake backends in a real BackendPool; the
three look-ups the resolver makes outside the pool (the chain rules from the
config, the character's own backend match, the character's backend switches)
are replaced by the module's test seams `_rules`, `_character_spec`,
`_character_switches`.

THE POOL (name — media/category/rig/ref slots, cost, state)
  Flux Big    image img2img ref1  cost 3  available
  Flux Cheap  image img2img ref1  cost 1  available
  Qwen A      image img2img ref1  cost 0  COOLDOWN (mark_unhealthy)
  Qwen B      image txt2img ref1  cost 0  available
  Inpaint X   image inpaint ref1  cost 0  available
  Ref0        image txt2img ref0  cost 2  available
  Off         image txt2img ref1  cost 0  instance_enabled False
  Vid         video txt2img       cost 0  available
  Mesh-H      mesh img2mesh mixamo cost 0 available
  Mesh-O      mesh img2mesh none   cost 1 available
  Shrink      mesh mesh2mesh none  cost 0 available

THE RULES, BY HAND
  § 3: chain = [character match @0 if the occasion is character-scoped and
  set] + rules @1..n; the first `ok` entry wins; inside a glob the cheapest.
  Decision 2 / B1: the INTENDED entry = the first chain row whose status is
  NOT a configuration skip (no_match, wrong_kind, disabled,
  disabled_for_character) — i.e. ok / cooldown / unavailable (an `exclude`
  hit counts as cooldown). `intended_spec` / `first_position` come from it;
  `is_fallback` = the used position differs from it. So a render is marked
  (`fallback_from`) only when a RUNTIME failure skipped an earlier entry;
  a typo or a wrong-kind entry in front is configuration, never a fallback.
  B2: `intended_spec_for` applies the configuration filters only
  (matched -> fits -> enabled -> allowed) and ignores availability, so a
  cooldown never changes it.

EXPECTATIONS, DERIVED BY HAND
 1. photo rules ["Qwen A", "Flux*"], no character:
    Qwen A -> cooldown (runtime, so it is the intended entry); Flux* -> ok,
    cheapest of {Flux Big 3, Flux Cheap 1} = Flux Cheap. position 2,
    intended "Qwen A", first_position 1, is_fallback True;
    statuses [cooldown, ok].
 2. same rules, character spec "Flux Big": position 0 wins -> Flux Big,
    intended "Flux Big", is_fallback False.
 3. + the character switches Flux Big OFF: @0 disabled_for_character
    (configuration, not intended), @1 Qwen A cooldown (runtime -> intended
    "Qwen A", first_position 1), @2 Flux* -> Flux Cheap (the switch restricts
    EVERY entry, Flux Big is gone from the glob too). position 2,
    is_fallback True.
 4. mesh_object rules ["Mesh-H", "Shrink", "Mesh-O"]: wrong_kind (rig),
    wrong_kind (mesh2mesh), ok -> Mesh-O position 3. Both skips are
    configuration -> intended "Mesh-O", first_position 3, is_fallback False,
    route_meta without "fallback_from".
 5. location rules ["Inpaint X"]: wrong_kind, nothing ok -> NoRouteError,
    message "no backend available for location: Inpaint X (wrong kind of backend)".
 6. timevariant rules ["Ref0", "Flux Cheap"]: Ref0 wrong_kind (no ref slot,
    configuration), Flux Cheap ok position 2 -> intended "Flux Cheap",
    is_fallback False, no "fallback_from".
 7. event, no rules (not character-scoped): EMPTY chain -> cheapest available
    image non-inpaint enabled backend = Qwen B (cost 0; Qwen A cools, Inpaint X
    and Off excluded). position None, intended "", route_meta ==
    {"routing": {"occasion": "event", "position": None, "spec": ""}}.
 8. item rules ["Nope*"]: no_match -> NoRouteError.
 9. item rules ["Off"]: disabled -> NoRouteError.
10. photo rules ["*"] (no character): has_ref False -> cheapest image render
    backend available = Qwen B (0); has_ref True -> img2img preferred among
    the glob's live matches {Flux Big, Flux Cheap} -> Flux Cheap.
11. photo rules ["Flux*"], exclude=("Flux Cheap",) -> Flux Big; its status
    row stays "ok".
12. route_meta of case 1 ==
    {"routing": {"occasion": "photo", "position": 2, "spec": "Flux*"},
     "fallback_from": {"occasion": "photo", "intended_spec": "Qwen A", "position": 1}}
    route_meta of case 2 has no "fallback_from".
13. explain_image_routing(): probes NOTHING (check_availability calls stay 0);
    for photo with case-1 rules: resolved "Flux Cheap", position 2,
    via "chain", reason "order 2 — order 1 skipped: cooling down",
    intended_spec "Qwen A" (the cooled entry is runtime, still intended).
    For event (no rules): via "cheapest", resolved "Qwen B".
    For location with ["Inpaint X"]: via "none", resolved None,
    intended_spec "" (the only row is a configuration skip).
14. resolve_image_route(..., probe=True) probes the INTENDED entry's
    candidates only (the first entry passing the configuration filters), and
    of those only the ones that are neither in `exclude` nor cooling down
    (character-disabled ones are already out of the allowed set) — after a
    failure the intended entry IS the dead backend, a re-entry must not wait
    on it. Probe counters reset before each sub-case:
    a. case-1 rules ["Qwen A", "Flux*"]: intended = Qwen A (cooldown), its
       only candidate cools -> Qwen A 0 calls; Flux Big / Flux Cheap belong
       to a later entry -> 0, 0.
    b. ["Nope*", "Flux Cheap"]: intended "Flux Cheap" (Nope* is no_match)
       -> Flux Cheap 1 call, Flux Big 0.
    c. ["Qwen*"]: matched {Qwen A, Qwen B}, both fit photo -> Qwen A cools
       -> 0, Qwen B 1.
    d. ["Flux*"], exclude=("Flux Cheap",) -> Flux Big 1, Flux Cheap 0.
    e. ["Flux*"], character "someone" (no @0 spec), switch Flux Big OFF ->
       allowed {Flux Cheap} -> Flux Cheap 1, Flux Big 0.
15. normalize_spec: "backend:Flux*" -> "Flux*"; "workflow:Z-Image" -> "Z-Image"
    (the legacy rewrite, workflow_spec_migration); "workflow:" -> "";
    "  " -> "".
16. resolve_spec("photo", "Flux Big") -> ("ok", Flux Big);
    resolve_spec("photo", "Inpaint X") -> ("wrong_kind", None).
    The round-robin key is built from the NORMALISED spec, so
    resolve_spec("photo", "backend:Flux*") and resolve_spec("photo", "Flux*")
    both call pick_lowest_cost with rotation_key "route:photo:Flux*" (one
    counter, not two).
17. resolve_image_route("mesh_low") raises UnknownOccasionError.
18. empty chain honours the character switches: profile (character-scoped)
    with no character spec and no rules, switches turn Qwen B OFF ->
    live = {Flux Big 3, Flux Cheap 1, Ref0 2} -> cheapest Flux Cheap.
19. (decision 2) photo rules ["Qwen 2511", "Flux*"]: "Qwen 2511" matches no
    backend (no_match, configuration) -> Flux* ok -> Flux Cheap position 2;
    intended "Flux*", first_position 2, is_fallback False, route_meta ==
    {"routing": {"occasion": "photo", "position": 2, "spec": "Flux*"}}.
20. (decision 2) photo rules ["Flux Big", "Flux Cheap"] with Flux Big put in
    cooldown by mark_unhealthy: Flux Big cooldown (runtime -> intended,
    first_position 1), Flux Cheap ok position 2 -> is_fallback True,
    fallback_from == {"occasion": "photo", "intended_spec": "Flux Big",
    "position": 1}; intended_spec_for("photo") == "Flux Big".
21. (B2) intended_spec_for:
    a. rules ["Qwen A", "Flux*"] (Qwen A cooling) -> "Qwen A" — a cooldown
       never moves the intended entry;
    b. rules ["Nope*", "Flux*"] -> "Flux*" (no_match is not intended);
    c. rules ["Qwen A", "Flux*"], character spec "Flux Big" switched OFF for
       the character -> @0 disabled_for_character -> "Qwen A";
    d. rules ["Nope*", "Inpaint X", "Off"] -> "" (every entry is a
       configuration skip); no rules -> "" (empty chain).
    e. it is the same value Route and explain carry: for case-1 rules
       intended_spec_for == route.intended_spec == explain_occasion's
       intended_spec == "Qwen A".
22. intended_entry on rows [no_match, wrong_kind, disabled,
    disabled_for_character] -> None; on [wrong_kind, unavailable, ok] -> the
    unavailable row.
23. (review focus 4 at a RULE position — case 3 cannot show it, Flux Cheap
    is the cheaper glob match there anyway) photo, character "someone" with
    NO character spec (so no @0 entry):
    a. rules ["Flux*"], switches turn Flux Cheap OFF: matched {Flux Big,
       Flux Cheap}, both fit + enabled, allowed = {Flux Big} -> Flux Big
       (cost 3, the cheaper Flux Cheap must NOT be taken), position 1,
       statuses ["ok"].
    b. rules ["Flux Big"], switches turn Flux Big OFF: matched {Flux Big},
       allowed {} -> disabled_for_character; nothing ok -> NoRouteError,
       chain statuses ["disabled_for_character"].
24. (review focus 2 for a RUNTIME failure) photo rules ["Qwen A"], no
    character, Qwen A cooling (mark_unhealthy at setup) while Qwen B,
    Flux Cheap and Flux Big are live: the only entry is cooldown, the chain
    is configured -> NoRouteError with chain statuses ["cooldown"], the row's
    backend "" and ZERO pick_lowest_cost calls on the pool — no other backend
    was chosen (no slide onto the cheapest / a paid one). Message
    "no backend available for photo: Qwen A (cooling down)".
"""
import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _scratch(prefix):
    p = tempfile.mkdtemp(prefix=prefix)
    atexit.register(shutil.rmtree, p, ignore_errors=True)
    return p


os.environ["ANIMATION_CLIPS_DIR"] = _scratch("routing-resolve-clips-")
from app.core import paths  # noqa: E402
paths.init(_scratch("routing-resolve-storage-"))

from app.imagegen.base import ImageBackend  # noqa: E402
from app.imagegen.selection import BackendPool  # noqa: E402
from app.imagegen import routing  # noqa: E402
from app.imagegen.occasions import UnknownOccasionError  # noqa: E402

FAILS = []


def check(label, got, expected):
    ok = got == expected
    print(f"  {'OK  ' if ok else 'FAIL'} {label}: {got!r}"
          + ("" if ok else f" (expected {expected!r})"))
    if not ok:
        FAILS.append(label)


class Fake(ImageBackend):
    def __init__(self, name, media="image", category="txt2img", cost=0,
                 ref=1, rig="", enabled=True):
        super().__init__(name, "http://localhost", float(cost), "fake", "FAKE_ROUTING_")
        self.MEDIA_TYPE = media
        self.category = category
        self.ref_slot_count = ref
        if rig:
            self.mesh_rig = rig
        self.instance_enabled = enabled
        self._available = True
        self.probes = 0

    def check_availability(self):
        self.probes += 1
        return self.available

    def _generate(self, prompt, negative_prompt, params):
        return [b"x"]


B = {b.name: b for b in [
    Fake("Flux Big", category="img2img", cost=3),
    Fake("Flux Cheap", category="img2img", cost=1),
    Fake("Qwen A", category="img2img", cost=0),
    Fake("Qwen B", category="txt2img", cost=0),
    Fake("Inpaint X", category="inpaint", cost=0),
    Fake("Ref0", category="txt2img", cost=2, ref=0),
    Fake("Off", category="txt2img", cost=0, enabled=False),
    Fake("Vid", media="video", category="txt2img"),
    Fake("Mesh-H", media="mesh", category="img2mesh", rig="mixamo"),
    Fake("Mesh-O", media="mesh", category="img2mesh", rig="none", cost=1),
    Fake("Shrink", media="mesh", category="mesh2mesh", rig="none"),
]}
B["Qwen A"].mark_unhealthy("smoke", 300)
POOL = BackendPool(list(B.values()), agent_instances_provider=lambda n: {})

RULES = {}
CHAR_SPEC = {"value": ""}
SWITCHES = {"value": {}}
routing._rules = lambda occasion: list(RULES.get(occasion, []))
routing._character_spec = lambda occ_def, character: (
    CHAR_SPEC["value"] if character and occ_def.get("character_scoped") else "")
routing._character_switches = lambda character: SWITCHES["value"] if character else {}


def route(occ, **kw):
    return routing.resolve_image_route(occ, pool=POOL, **kw)


def statuses(r):
    return [row["status"] for row in r.chain]


print("resolve")
RULES = {"photo": ["Qwen A", "Flux*"]}
r1 = route("photo")
check("1 backend", r1.backend.name, "Flux Cheap")
check("1 position/intended/first", (r1.position, r1.intended_spec, r1.first_position), (2, "Qwen A", 1))
check("1 is_fallback", r1.is_fallback, True)
check("1 statuses", statuses(r1), ["cooldown", "ok"])

CHAR_SPEC["value"] = "Flux Big"
r2 = route("photo", character="someone")
check("2 character wins", (r2.backend.name, r2.position, r2.intended_spec, r2.is_fallback),
      ("Flux Big", 0, "Flux Big", False))

SWITCHES["value"] = {"Flux Big": {"enabled": False}}
r3 = route("photo", character="someone")
check("3 switch restricts every entry", (r3.backend.name, r3.position),
      ("Flux Cheap", 2))
check("3 intended skips the switched-off @0",
      (r3.intended_spec, r3.first_position, r3.is_fallback), ("Qwen A", 1, True))
check("3 statuses", statuses(r3), ["disabled_for_character", "cooldown", "ok"])
CHAR_SPEC["value"] = ""
SWITCHES["value"] = {}

RULES = {"mesh_object": ["Mesh-H", "Shrink", "Mesh-O"]}
r4 = route("mesh_object")
check("4 rig/category filter", (r4.backend.name, r4.position, statuses(r4)),
      ("Mesh-O", 3, ["wrong_kind", "wrong_kind", "ok"]))
check("4 wrong kinds are configuration",
      (r4.intended_spec, r4.first_position, r4.is_fallback), ("Mesh-O", 3, False))
check("4 no fallback_from", "fallback_from" in routing.route_meta(r4), False)

RULES = {"location": ["Inpaint X"]}
try:
    route("location")
    check("5 NoRouteError", "no exception", "NoRouteError")
except routing.NoRouteError as e:
    check("5 message", str(e),
          "no backend available for location: Inpaint X (wrong kind of backend)")

RULES = {"timevariant": ["Ref0", "Flux Cheap"]}
r6 = route("timevariant")
check("6 ref slot filter", (r6.backend.name, r6.position, statuses(r6)),
      ("Flux Cheap", 2, ["wrong_kind", "ok"]))
check("6 intended / not a fallback", (r6.intended_spec, r6.is_fallback), ("Flux Cheap", False))
check("6 no fallback_from", "fallback_from" in routing.route_meta(r6), False)

RULES = {}
r7 = route("event")
check("7 empty chain -> cheapest", (r7.backend.name, r7.position, r7.intended_spec),
      ("Qwen B", None, ""))
check("7 route_meta", routing.route_meta(r7),
      {"routing": {"occasion": "event", "position": None, "spec": ""}})

for label, rules in (("8 no_match", ["Nope*"]), ("9 disabled", ["Off"])):
    RULES = {"item": rules}
    try:
        route("item")
        check(label, "no exception", "NoRouteError")
    except routing.NoRouteError as e:
        check(label, [row["status"] for row in e.chain], [label.split()[1]])

RULES = {"photo": ["*"]}
check("10 glob without ref", route("photo").backend.name, "Qwen B")
check("10 glob with ref prefers img2img", route("photo", has_ref=True).backend.name, "Flux Cheap")

RULES = {"photo": ["Flux*"]}
r11 = route("photo", exclude=("Flux Cheap",))
check("11 exclude", (r11.backend.name, statuses(r11)), ("Flux Big", ["ok"]))

check("12 route_meta fallback", routing.route_meta(r1),
      {"routing": {"occasion": "photo", "position": 2, "spec": "Flux*"},
       "fallback_from": {"occasion": "photo", "intended_spec": "Qwen A", "position": 1}})
check("12 route_meta no fallback", "fallback_from" in routing.route_meta(r2), False)

print("explain")
for b in B.values():
    b.probes = 0
RULES = {"photo": ["Qwen A", "Flux*"], "location": ["Inpaint X"]}
ex = {o["id"]: o for o in routing.explain_image_routing(pool=POOL)["occasions"]}
check("13 explain probes nothing", sum(b.probes for b in B.values()), 0)
check("13 photo", (ex["photo"]["resolved"], ex["photo"]["position"], ex["photo"]["via"],
                   ex["photo"]["reason"]),
      ("Flux Cheap", 2, "chain", "order 2 — order 1 skipped: cooling down"))
check("13 photo intended_spec", ex["photo"]["intended_spec"], "Qwen A")
check("13 event", (ex["event"]["via"], ex["event"]["resolved"]), ("cheapest", "Qwen B"))
check("13 location", (ex["location"]["via"], ex["location"]["resolved"],
                      ex["location"]["intended_spec"]), ("none", None, ""))
check("13 explain_occasion is the same row",
      routing.explain_occasion("photo", pool=POOL), ex["photo"])



def reset_probes():
    for b in B.values():
        b.probes = 0


reset_probes()
RULES = {"photo": ["Qwen A", "Flux*"]}
route("photo", probe=True)
check("14a intended entry cools -> nothing probed",
      (B["Qwen A"].probes, B["Flux Big"].probes, B["Flux Cheap"].probes), (0, 0, 0))
reset_probes()
RULES = {"photo": ["Nope*", "Flux Cheap"]}
route("photo", probe=True)
check("14b probe skips a no_match entry",
      (B["Flux Cheap"].probes, B["Flux Big"].probes), (1, 0))
reset_probes()
RULES = {"photo": ["Qwen*"]}
route("photo", probe=True)
check("14c cooling candidate not probed, sibling is",
      (B["Qwen A"].probes, B["Qwen B"].probes), (0, 1))
reset_probes()
RULES = {"photo": ["Flux*"]}
route("photo", probe=True, exclude=("Flux Cheap",))
check("14d excluded candidate not probed",
      (B["Flux Big"].probes, B["Flux Cheap"].probes), (1, 0))
reset_probes()
SWITCHES["value"] = {"Flux Big": {"enabled": False}}
route("photo", probe=True, character="someone")
check("14e character-disabled candidate not probed",
      (B["Flux Cheap"].probes, B["Flux Big"].probes), (1, 0))
SWITCHES["value"] = {}
reset_probes()

check("15 backend prefix", routing.normalize_spec("backend:Flux*"), "Flux*")
check("15 workflow prefix", routing.normalize_spec("workflow:Z-Image"), "Z-Image")
check("15 bare workflow", routing.normalize_spec("workflow:"), "")
check("15 blank", routing.normalize_spec("  "), "")

st, be = routing.resolve_spec("photo", "Flux Big", pool=POOL)
check("16 resolve_spec ok", (st, be.name if be else None), ("ok", "Flux Big"))
check("16 resolve_spec wrong kind", routing.resolve_spec("photo", "Inpaint X", pool=POOL),
      ("wrong_kind", None))
_keys = []
_orig_pick16 = POOL.pick_lowest_cost


def _recording_pick(candidates, rotation_key="default"):
    _keys.append(rotation_key)
    return _orig_pick16(candidates, rotation_key)


POOL.pick_lowest_cost = _recording_pick
try:
    routing.resolve_spec("photo", "backend:Flux*", pool=POOL)
    routing.resolve_spec("photo", "Flux*", pool=POOL)
finally:
    POOL.pick_lowest_cost = _orig_pick16
check("16 one rotation key per normalised spec", _keys,
      ["route:photo:Flux*", "route:photo:Flux*"])

try:
    route("mesh_low")
    check("17 unknown occasion", "no exception", "UnknownOccasionError")
except UnknownOccasionError:
    check("17 unknown occasion", True, True)

RULES = {}
SWITCHES["value"] = {"Qwen B": {"enabled": False}}
check("18 empty chain honours switches", route("profile", character="someone").backend.name,
      "Flux Cheap")
SWITCHES["value"] = {}

print("intended entry (decision 2 / B1 / B2)")
RULES = {"photo": ["Qwen 2511", "Flux*"]}
r19 = route("photo")
check("19 typo in front is configuration",
      (r19.backend.name, r19.position, r19.intended_spec, r19.first_position, r19.is_fallback),
      ("Flux Cheap", 2, "Flux*", 2, False))
check("19 route_meta without fallback_from", routing.route_meta(r19),
      {"routing": {"occasion": "photo", "position": 2, "spec": "Flux*"}})

RULES = {"photo": ["Qwen A", "Flux*"]}
check("21a cooldown keeps the intended entry",
      routing.intended_spec_for("photo", pool=POOL), "Qwen A")
check("21e one source: Route == explain == intended_spec_for",
      (route("photo").intended_spec,
       routing.explain_occasion("photo", pool=POOL)["intended_spec"],
       routing.intended_spec_for("photo", pool=POOL)),
      ("Qwen A", "Qwen A", "Qwen A"))
CHAR_SPEC["value"] = "Flux Big"
SWITCHES["value"] = {"Flux Big": {"enabled": False}}
check("21c switched-off @0 is not intended",
      routing.intended_spec_for("photo", character="someone", pool=POOL), "Qwen A")
CHAR_SPEC["value"] = ""
SWITCHES["value"] = {}
RULES = {"photo": ["Nope*", "Flux*"]}
check("21b no_match is not intended", routing.intended_spec_for("photo", pool=POOL), "Flux*")
RULES = {"photo": ["Nope*", "Inpaint X", "Off"]}
check("21d all configuration skips", routing.intended_spec_for("photo", pool=POOL), "")
RULES = {}
check("21d empty chain", routing.intended_spec_for("photo", pool=POOL), "")

check("22 intended_entry all config skips",
      routing.intended_entry([{"status": s} for s in
                              ("no_match", "wrong_kind", "disabled", "disabled_for_character")]),
      None)
check("22 intended_entry first runtime row",
      routing.intended_entry([{"status": "wrong_kind", "spec": "a"},
                              {"status": "unavailable", "spec": "b"},
                              {"status": "ok", "spec": "c"}]),
      {"status": "unavailable", "spec": "b"})

print("switches at rule positions / dead configured chain (review focus 4 + 2)")
CHAR_SPEC["value"] = ""
RULES = {"photo": ["Flux*"]}
SWITCHES["value"] = {"Flux Cheap": {"enabled": False}}
r23 = route("photo", character="someone")
check("23a switch filters a rule glob", (r23.backend.name, r23.position, statuses(r23)),
      ("Flux Big", 1, ["ok"]))
RULES = {"photo": ["Flux Big"]}
SWITCHES["value"] = {"Flux Big": {"enabled": False}}
try:
    r = route("photo", character="someone")
    check("23b switched-off rule entry", f"routed to {r.backend.name}", "NoRouteError")
except routing.NoRouteError as e:
    check("23b switched-off rule entry", [row["status"] for row in e.chain],
          ["disabled_for_character"])
SWITCHES["value"] = {}

RULES = {"photo": ["Qwen A"]}
_picks = {"n": 0}
_orig_pick = POOL.pick_lowest_cost


def _counting_pick(*a, **kw):
    _picks["n"] += 1
    return _orig_pick(*a, **kw)


POOL.pick_lowest_cost = _counting_pick
try:
    r = route("photo")
    check("24 dead configured chain", f"routed to {r.backend.name}", "NoRouteError")
except routing.NoRouteError as e:
    check("24 statuses", [row["status"] for row in e.chain], ["cooldown"])
    check("24 no backend in the row", [row["backend"] for row in e.chain], [""])
    check("24 message", str(e), "no backend available for photo: Qwen A (cooling down)")
finally:
    POOL.pick_lowest_cost = _orig_pick
check("24 no other backend was picked", _picks["n"], 0)
check("24 live alternatives existed", all(B[n].available for n in ("Qwen B", "Flux Cheap", "Flux Big")),
      True)

# Last: puts Flux Big into a cooldown, restored afterwards.
B["Flux Big"].mark_unhealthy("smoke", 300)
RULES = {"photo": ["Flux Big", "Flux Cheap"]}
r20 = route("photo")
check("20 cooled first entry marks the render",
      (r20.backend.name, r20.position, r20.intended_spec, r20.first_position, r20.is_fallback),
      ("Flux Cheap", 2, "Flux Big", 1, True))
check("20 fallback_from", routing.route_meta(r20).get("fallback_from"),
      {"occasion": "photo", "intended_spec": "Flux Big", "position": 1})
check("20 intended_spec_for ignores the cooldown",
      routing.intended_spec_for("photo", pool=POOL), "Flux Big")
B["Flux Big"]._cooldown_until = 0.0
B["Flux Big"].available = True

print()
if FAILS:
    print(f"{len(FAILS)} check(s) failed: {FAILS}")
    sys.exit(1)
print("all checks passed")
