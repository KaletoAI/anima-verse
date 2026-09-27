#!/usr/bin/env python3
"""Smoke: decision points for invitations — an invited NPC accepts or declines.

Usage:  ./.venv/bin/python scripts/smoke_decision_invites.py

Section A — ``pair_invite`` (package ``interact``): an ORDINARY NPC invited
to a pair activity. With the point active the decision model may settle the
invitation at once (``resolve_invite``); with no confident answer, or the
point inactive, the NPC is woken exactly as before (``bump`` with the hint
that names ``InteractWith ... answer=no``).

Everything the hook reaches is stubbed at module level, so no LLM, no
network, no decision endpoint, no world data: ``decision.is_active`` /
``decide`` / ``record_outcome`` / ``mark_taken`` are recorders,
``decision_points.invite_state`` returns ``{"situation": "stub"}`` (A8 tests
the real one with its own inputs stubbed), ``interaction_engine.resolve_invite``
returns the status each case picks, and the agent loop is a FakeLoop that
records ``bump``. Storage is a throwaway dir initialised before any app import.

EXPECTATIONS, DERIVED BY HAND (Halvard invites Kira to "shaking hands").
A0  importing the package's on_load module registers point "pair_invite"
    with origin "interact", min confidence 0.75, timeout 3.0.
A1  point inactive -> decide is never called; Kira is bumped once and the
    hint still carries "answer=no" (the usual path, byte for byte).
A2  active, answer accept (0.9), resolve -> "started":
    resolve_invite("i2", True) once; mark_taken("pair_invite", "i2"); no bump;
    NO narrator line from the hook (start_interaction writes its own).
A3  active, accept, resolve -> "cannot" and the row is back on "pending"
    (the engine's "ask again in a minute"): no mark_taken; Kira is bumped
    so she answers in her own turn (the outcome is recorded then).
A3b active, accept, resolve -> "cannot" and the row is "stale" (asleep,
    travelling — the question is CLOSED): nobody can answer it any more, so
    waking Kira would only make her call the verb back into a fresh
    counter-invitation. Settled: mark_taken, no bump.
A4  active, answer decline: resolve_invite("i4", False); mark_taken; no bump
    at all (controller ruling: the inviter learns it from its own tool result).
    Exactly ONE narrator line (record_utterance, speaker STORYTELLER_SPEAKER,
    source "interaction", anchor Kira) in Kira's place harbour/deck — lang
    "en" makes t() return the English key, so the content is
    "Kira does not want to shaking hands with Halvard right now."
A4b decision_points.invite_state raises inside _decide_invite -> the hook
    returns normally and Kira is bumped (the usual path); no resolve.
A5  active, decide -> None: Kira is bumped; resolve_invite not called.
A6  invitee player-controlled -> decide not called (a player answers in the UI).
A7  invitee a temporary NPC -> decide not called; the auto-accept path runs:
    resolve_invite("i7", True).
A8  the real invite_state (build_thought_context and get_relationship stubbed):
    (a) the stored row has the INVITER Tom as character_a and the invitee Kira
        as character_b, so Kira->Tom is ``sentiment_b_to_a`` = 0.3 ->
        sentiment_label "positive"; the wrong direction (a_to_b = -0.8) would
        read "very negative". Strength 72 is in 60..100 -> "strong"; type
        "friend" -> "friend". The line is exactly
        "Kira toward Tom: friend, strong bond (72/100), feels positive about Tom."
    (b) no row -> "Kira and Tom do not know each other well yet."
    offer "to dance together" -> state["offer"] = "Tom invites Kira to dance together",
    so it starts with "Tom invites Kira to "; the situation comes from
    thought_state and contains "Character: Kira".
A9  InteractWith called back by Kira (open invitation i9):
    accept -> record_outcome("pair_invite", "i9", {"answer": "accept"}),
    recorded BEFORE resolve_invite runs; "answer": "no" -> {"answer": "decline"}.
A10 _answered_at_once for an ORDINARY NPC (not temporary): row "declined" ->
    "Kira does not want to shaking hands right now."; row "pending" -> "".

Section B — ``party_join`` (package ``party``): Halvard invites the NPC Kira
to come along (InviteToParty). The party ENGINE is real: section B puts the
real location getters back, creates the schema and seeds Halvard, Kira and
Brann at location "loc_harbour" (room ""), so create_pending_invite /
add_to_party / resolve_pending_invite really run against the throwaway
world.db. The decision layer, invite_state, the agent loop and the narrator
recorder stay the stubs of section A; lang "en" -> t() returns the key.

EXPECTATIONS, DERIVED BY HAND:
B0  importing plugins.party.register registers "party_join" with origin
    "party", min confidence 0.75, timeout 3.0.
B1  inactive -> decide never called; one pending row Halvard->Kira; Kira
    bumped once, the hint carries "answer=no"; the result is the usual
    "Halvard invites Kira to come along."
B2  active, accept; Halvard already leads Brann -> the offer is
    "to come along with the group (the group: Brann)"; decide keyed by the
    row's invite_id. Kira joins through _join: get_party_of(Kira) is a
    follower of Halvard, members [Brann, Kira]. ORDER: for that key the
    recorders see "taken" BEFORE "outcome" (_join records accept for the
    still-pending row; mark_taken must already have resolved it). No bump.
    Result contains "agrees and joins"; the join's own narrator line
    "Kira joins Halvard's party." is written (one line, from _join).
B3  active, decline -> the row is "declined", Kira in no party,
    mark_taken("party_join", id), no bump, result contains "declines".
    Exactly ONE narrator line: speaker STORYTELLER_SPEAKER, source "party",
    anchor Kira, location "loc_harbour", room "", content
    "Kira does not want to come along with Halvard."
B4  active, decide -> None -> Kira bumped as today, offer
    "to come along with the group" (no party yet), no mark_taken.
B5  Kira player-controlled -> decide never called; no bump (the UI asks).
B6  JoinParty(leader=Halvard, answer=no) by Kira with an open invitation ->
    record_outcome("party_join", id, {"answer": "decline"}); row "declined";
    no party; reply contains "turns down".
B7  JoinParty(answer=no) with NO invitation -> reply
    "Halvard has not invited Kira."; no outcome; no party.
B8  JoinParty(leader=Halvard) accept with an open invitation ->
    record_outcome("party_join", id, {"answer": "accept"}); Kira follows
    Halvard.
B9  Kira a TEMPORARY NPC, point active, answer accept ready -> decide never
    called (a temporary NPC is never made a follower); the usual path is
    unchanged: one bump attempt at Kira, result
    "Halvard invites Kira to come along.", Kira in no party.
"""
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_TMP = Path(tempfile.mkdtemp(prefix="smoke_decision_invites_"))
from app.core import paths  # noqa: E402
paths.init(str(_TMP))

import app.core.pose_catalog as PC  # noqa: E402
import app.core.thought_context as TC  # noqa: E402
import app.models.account as ACC  # noqa: E402
import app.models.character as C  # noqa: E402
import app.models.relationship as REL  # noqa: E402
import app.core.perception as PERC  # noqa: E402
from app.core import agent_loop, decision, decision_points  # noqa: E402
from app.core import interaction_engine as IE  # noqa: E402
from app.core.decision import Answer, Decision  # noqa: E402
from app.plugins.context import PluginContext  # noqa: E402

POINT = "pair_invite"
INVITER, INVITEE, KEY = "Halvard", "Kira", "shaking hands"

FAILS = []


def check(name, got, want):
    ok = got == want
    print(f"  [{'OK  ' if ok else 'FAIL'}] {name}" + ("" if ok else f" — got {got!r}, want {want!r}"))
    if not ok:
        FAILS.append(name)


# ── Recorders / stubs ───────────────────────────────────────────────────────

EVENTS = []          # (kind, args) in call order, across all recorders
ACTIVE = [False]
DECISION = [None]
RESOLVE_RESULT = [{}]
INVITE_ROW = [{}]
PLAYERS = set()
TEMPS = set()


def _events(kind):
    return [args for k, args in EVENTS if k == kind]


class FakeLoop:
    def bump(self, name, **kwargs):
        EVENTS.append(("bump", (name, kwargs.get("hint", ""))))
        return True


LOOP = FakeLoop()
agent_loop.get_agent_loop = lambda: LOOP

decision.is_active = lambda pid: (EVENTS.append(("is_active", pid)) or ACTIVE[0])


def _decide(point_id, state, questions, *, key=None, then=None):
    EVENTS.append(("decide", (point_id, key, sorted(questions))))
    return DECISION[0]


decision.decide = _decide
decision.record_outcome = lambda pid, key, actual: EVENTS.append(("outcome", (pid, key, actual)))
decision.mark_taken = lambda pid, key: EVENTS.append(("taken", (pid, key)))

_REAL_INVITE_STATE = getattr(decision_points, "invite_state", None)
decision_points.invite_state = lambda invitee, inviter, offer: (
    EVENTS.append(("state", (invitee, inviter, offer))) or {"situation": "stub"})


def _resolve(invite_id, accept, *a, **k):
    EVENTS.append(("resolve", (invite_id, accept)))
    return RESOLVE_RESULT[0]


IE.resolve_invite = _resolve
IE.get_invite = lambda invite_id: INVITE_ROW[0]
IE.cancel_invite = lambda invite_id: EVENTS.append(("cancel", invite_id))
ACC.is_player_controlled = lambda name: name in PLAYERS
C.is_temporary_npc = lambda name: name in TEMPS
PC.get_catalog = lambda axis: {KEY: {"prompt": "two people shake hands firmly"}}
C.get_character_language = lambda name: "en"
_REAL_LOC = C.get_character_current_location   # section B puts them back
_REAL_ROOM = C.get_character_current_room
C.get_character_current_location = lambda name="", profile=None: "harbour"
C.get_character_current_room = lambda name, profile=None: "deck"
PERC.record_utterance = lambda **kw: EVENTS.append(("narrate", kw))

import plugins.interact.register as REG  # noqa: E402 — registers the point + hook
from plugins.interact.skill import InteractSkill  # noqa: E402


def answer(value, confidence=0.9):
    return Decision(answers={"answer": Answer(value=value, p_yes=None, confidence=confidence,
                                              distribution={value: confidence})})


def invite(invite_id, *, active, decision_=None, resolve=None, row=None):
    EVENTS.clear()
    ACTIVE[0] = active
    DECISION[0] = decision_
    RESOLVE_RESULT[0] = resolve or {}
    INVITE_ROW[0] = row or {}
    REG._on_invited(invite_id=invite_id, inviter=INVITER, invitee=INVITEE, pose_key=KEY)


print("A0 registration")
spec = next((p for p in decision.registered_points() if p.point_id == POINT), None)
check("A0 pair_invite registered", spec is not None, True)
if spec:
    check("A0 origin/min_conf/timeout",
          (spec.origin, spec.default_min_confidence, spec.default_timeout_s),
          ("interact", 0.75, 3.0))

print("A1 point inactive -> the usual bump")
invite("i1", active=False)
check("A1 decide not called", _events("decide"), [])
check("A1 no state built", _events("state"), [])
bumps = _events("bump")
check("A1 bumped once", [b[0] for b in bumps], [INVITEE])
check("A1 hint carries answer=no", bool(bumps) and "answer=no" in bumps[0][1], True)

print("A2 active, accept, started")
invite("i2", active=True, decision_=answer("accept"), resolve={"status": "started"})
check("A2 decide asked with key i2", _events("decide"), [(POINT, "i2", ["answer"])])
check("A2 state offer", [s[2] for s in _events("state")],
      ["to shaking hands together (two people shake hands firmly)"])
check("A2 resolve(i2, True)", _events("resolve"), [("i2", True)])
check("A2 mark_taken", _events("taken"), [(POINT, "i2")])
check("A2 no bump", _events("bump"), [])
check("A2 no narrator line from the hook", _events("narrate"), [])

print("A3 active, accept, cannot (row back on pending)")
invite("i3", active=True, decision_=answer("accept"),
       resolve={"status": "cannot", "reason": "seat taken"}, row={"status": "pending"})
check("A3 resolve(i3, True)", _events("resolve"), [("i3", True)])
check("A3 no mark_taken", _events("taken"), [])
check("A3 Kira bumped", [b[0] for b in _events("bump")], [INVITEE])

print("A3b active, accept, cannot (row stale — question closed)")
invite("i3b", active=True, decision_=answer("accept"),
       resolve={"status": "cannot", "reason": "asleep"}, row={"status": "stale"})
check("A3b mark_taken", _events("taken"), [(POINT, "i3b")])
check("A3b no bump", _events("bump"), [])

print("A4 active, decline")
invite("i4", active=True, decision_=answer("decline"), resolve={"status": "declined"})
check("A4 resolve(i4, False)", _events("resolve"), [("i4", False)])
check("A4 mark_taken", _events("taken"), [(POINT, "i4")])
check("A4 no bump at all", _events("bump"), [])
narr = _events("narrate")
check("A4 exactly one narrator line", len(narr), 1)
if narr:
    n = narr[0]
    check("A4 narrator line fields",
          (n.get("speaker"), n.get("source"), n.get("anchor"), n.get("location_id"),
           n.get("room_id"), n.get("volume")),
          (PERC.STORYTELLER_SPEAKER, "interaction", INVITEE, "harbour", "deck",
           PERC.VOLUME_NORMAL))
    check("A4 narrator content", n.get("content"),
          "Kira does not want to shaking hands with Halvard right now.")

print("A4b invite_state raises -> usual path")
_stub_state = decision_points.invite_state


def _boom(*a, **k):
    raise RuntimeError("state failed")


decision_points.invite_state = _boom
invite("i4b", active=True, decision_=answer("decline"), resolve={"status": "declined"})
decision_points.invite_state = _stub_state
check("A4b no resolve", _events("resolve"), [])
check("A4b Kira bumped", [b[0] for b in _events("bump")], [INVITEE])

print("A5 active, no confident answer")
invite("i5", active=True, decision_=None)
check("A5 decide called", len(_events("decide")), 1)
check("A5 no resolve", _events("resolve"), [])
check("A5 Kira bumped", [b[0] for b in _events("bump")], [INVITEE])

print("A6 invitee player-controlled")
PLAYERS.add(INVITEE)
invite("i6", active=True, decision_=answer("accept"), resolve={"status": "started"})
PLAYERS.clear()
check("A6 decide not called", _events("decide"), [])
check("A6 no resolve", _events("resolve"), [])

print("A7 invitee temporary NPC")
TEMPS.add(INVITEE)
invite("i7", active=True, decision_=answer("decline"), resolve={"status": "started"})
TEMPS.clear()
check("A7 decide not called", _events("decide"), [])
check("A7 auto-accept resolve(i7, True)", _events("resolve"), [("i7", True)])

print("A8 the real invite_state")
check("A8 invite_state exists", callable(_REAL_INVITE_STATE), True)
TC.build_thought_context = lambda name, *a, **k: {
    "character_name": name, "location_name": "Harbour", "activity": "standing",
    "feeling": "calm", "time_of_day": "10:00", "game_date": "Spring, day 3"}
REL_ROW = [None]
REL.get_relationship = lambda a, b: REL_ROW[0]
REL_ROW[0] = {"character_a": "Tom", "character_b": "Kira", "type": "friend",
              "strength": 72, "sentiment_a_to_b": -0.8, "sentiment_b_to_a": 0.3}
if callable(_REAL_INVITE_STATE):
    st = _REAL_INVITE_STATE("Kira", "Tom", "to dance together")
    check("A8a relationship line", st.get("relationship"),
          "Kira toward Tom: friend, strong bond (72/100), feels positive about Tom.")
    check("A8a offer prefix", str(st.get("offer", "")).startswith("Tom invites Kira to "), True)
    check("A8a offer text", st.get("offer"), "Tom invites Kira to dance together")
    check("A8a situation from thought_state", "Character: Kira" in str(st.get("situation")), True)
    REL_ROW[0] = None
    st = _REAL_INVITE_STATE("Kira", "Tom", "to dance together")
    check("A8b no row", st.get("relationship"), "Kira and Tom do not know each other well yet.")
    q = decision_points.invite_questions("Kira", "Tom")
    check("A8 questions", (sorted(q), sorted(q["answer"].options)),
          (["answer"], ["accept", "decline"]))

print("A9 InteractWith called back records the outcome")
C.list_available_characters = lambda *a, **k: [INVITER, INVITEE]
PC.resolve_to_catalog = lambda *a, **k: (KEY, "exact")
IE.partner_poses = lambda *a, **k: [(KEY, "handshake")]
IE.find_pending_invite = lambda *a, **k: {
    "invite_id": "i9", "actor": INVITER, "partner": INVITEE, "pose_key": KEY}
SKILL = InteractSkill({}, PluginContext("interact"))


def call_back(**extra):
    EVENTS.clear()
    return SKILL.execute(json.dumps({
        "agent_name": INVITEE, "partner": INVITER, "action": KEY, **extra}))


RESOLVE_RESULT[0] = {"status": "started", "interaction": {"clip_duration_s": 2.0, "loop": False}}
r = call_back()
check("A9 accept outcome", _events("outcome"), [(POINT, "i9", {"answer": "accept"})])
kinds = [k for k, _ in EVENTS if k in ("outcome", "resolve")]
check("A9 outcome before resolve", kinds, ["outcome", "resolve"])
check("A9 reply not an error", "Error" in r, False)
RESOLVE_RESULT[0] = {}
r = call_back(answer="no")
check("A9 decline outcome", _events("outcome"), [(POINT, "i9", {"answer": "decline"})])
check("A9 refusal resolve(i9, False)", _events("resolve"), [("i9", False)])

print("A10 _answered_at_once for an ordinary NPC")
INVITE_ROW[0] = {"status": "declined"}
check("A10 declined", SKILL._answered_at_once(INVITEE, "i10", KEY),
      "Kira does not want to shaking hands right now.")
INVITE_ROW[0] = {"status": "pending"}
check("A10 pending", SKILL._answered_at_once(INVITEE, "i10", KEY), "")

# ── Section B — party_join ──────────────────────────────────────────────────

print()
print("Section B — party_join")
C.get_character_current_location = _REAL_LOC
C.get_character_current_room = _REAL_ROOM
from app.core import db  # noqa: E402
db.init_schema()
from app.core import party_engine as P  # noqa: E402
import plugins.party.register  # noqa: E402,F401 — registers the point
from plugins.party.skill import PartySkill  # noqa: E402

PPOINT = "party_join"
BRANN, PLOC = "Brann", "loc_harbour"
for _n in (INVITER, INVITEE, BRANN):
    C.save_character_profile(_n, {"character_name": _n, "current_location": PLOC,
                                  "current_room": ""}, create_new=True)
_pctx = PluginContext("party")
P_INVITE = PartySkill({}, _pctx, "invite")
P_JOIN = PartySkill({}, _pctx, "join")


def preset():
    for n in (INVITER, INVITEE, BRANN):
        P.leave_party(n)
        P.clear_invites_for(n)
    EVENTS.clear()


def prun(skill, agent, **payload):
    return skill.execute(json.dumps({"agent_name": agent, **payload}))


def pinvite(*, active, decision_=None):
    ACTIVE[0] = active
    DECISION[0] = decision_
    return prun(P_INVITE, INVITER, target=INVITEE)


def decided_key():
    d = _events("decide")
    return d[0][1] if d else None


print("B0 registration")
spec = next((p for p in decision.registered_points() if p.point_id == PPOINT), None)
check("B0 party_join registered", spec is not None, True)
if spec:
    check("B0 origin/min_conf/timeout",
          (spec.origin, spec.default_min_confidence, spec.default_timeout_s),
          ("party", 0.75, 3.0))

print("B1 point inactive -> the usual bump")
preset()
r = pinvite(active=False)
check("B1 decide not called", _events("decide"), [])
check("B1 pending row", (P.find_pending_invite(INVITER, INVITEE) or {}).get("invitee"), INVITEE)
bumps = _events("bump")
check("B1 bumped once", [b[0] for b in bumps], [INVITEE])
check("B1 hint carries answer=no", bool(bumps) and "answer=no" in bumps[0][1], True)
check("B1 result", r, "Halvard invites Kira to come along.")

print("B2 active, accept (Halvard already leads Brann)")
preset()
P.add_to_party(INVITER, BRANN)
EVENTS.clear()
r = pinvite(active=True, decision_=answer("accept"))
k = decided_key()
check("B2 decide keyed by the invite id", bool(k) and str(k).startswith("pinv_"), True)
check("B2 offer names the group", [s[2] for s in _events("state")],
      ["to come along with the group (the group: Brann)"])
party = P.get_party_of(INVITEE) or {}
check("B2 Kira follows Halvard", (party.get("role"), party.get("leader"), party.get("members")),
      ("follower", INVITER, [BRANN, INVITEE]))
order = [kind for kind, args in EVENTS if kind in ("taken", "outcome") and args[1] == k]
check("B2 mark_taken before the join's outcome", order, ["taken", "outcome"])
check("B2 mark_taken", _events("taken"), [(PPOINT, k)])
check("B2 no bump", _events("bump"), [])
check("B2 result agrees and joins", "agrees and joins" in r, True)
check("B2 the join's narrator line", [n.get("content") for n in _events("narrate")],
      ["Kira joins Halvard's party."])

print("B3 active, decline")
preset()
r = pinvite(active=True, decision_=answer("decline"))
k = decided_key()
check("B3 row declined", (P.get_invite(k) or {}).get("status"), "declined")
check("B3 Kira in no party", P.get_party_of(INVITEE), None)
check("B3 mark_taken", _events("taken"), [(PPOINT, k)])
check("B3 no bump", _events("bump"), [])
check("B3 result declines", "declines" in r, True)
narr = _events("narrate")
check("B3 exactly one narrator line", len(narr), 1)
if narr:
    n = narr[0]
    check("B3 narrator line fields",
          (n.get("speaker"), n.get("source"), n.get("anchor"), n.get("location_id"),
           n.get("room_id"), n.get("volume")),
          (PERC.STORYTELLER_SPEAKER, "party", INVITEE, PLOC, "", PERC.VOLUME_NORMAL))
    check("B3 narrator content", n.get("content"),
          "Kira does not want to come along with Halvard.")

print("B4 active, no confident answer")
preset()
r = pinvite(active=True, decision_=None)
check("B4 decide called", len(_events("decide")), 1)
check("B4 offer without a group", [s[2] for s in _events("state")],
      ["to come along with the group"])
check("B4 no mark_taken", _events("taken"), [])
check("B4 Kira bumped", [b[0] for b in _events("bump")], [INVITEE])
check("B4 result", r, "Halvard invites Kira to come along.")

print("B5 invitee player-controlled")
preset()
PLAYERS.add(INVITEE)
r = pinvite(active=True, decision_=answer("accept"))
PLAYERS.clear()
check("B5 decide not called", _events("decide"), [])
check("B5 no bump", _events("bump"), [])
check("B5 Kira in no party", P.get_party_of(INVITEE), None)

print("B6 JoinParty answer=no with an open invitation")
preset()
iid = P.create_pending_invite(INVITER, INVITEE)
r = prun(P_JOIN, INVITEE, leader=INVITER, answer="no")
check("B6 decline outcome", _events("outcome"), [(PPOINT, iid, {"answer": "decline"})])
check("B6 row declined", (P.get_invite(iid) or {}).get("status"), "declined")
check("B6 no party", P.get_party_of(INVITEE), None)
check("B6 reply turns down", "turns down" in r, True)

print("B7 JoinParty answer=no without an invitation")
preset()
r = prun(P_JOIN, INVITEE, leader=INVITER, answer="no")
check("B7 reply", r, "Halvard has not invited Kira.")
check("B7 no outcome", _events("outcome"), [])
check("B7 no party", P.get_party_of(INVITEE), None)

print("B8 JoinParty accept with an open invitation")
preset()
iid = P.create_pending_invite(INVITER, INVITEE)
r = prun(P_JOIN, INVITEE, leader=INVITER)
check("B8 accept outcome", _events("outcome"), [(PPOINT, iid, {"answer": "accept"})])
check("B8 Kira follows Halvard", ((P.get_party_of(INVITEE) or {}).get("leader")), INVITER)

print("B9 invitee a temporary NPC")
preset()
TEMPS.add(INVITEE)
r = pinvite(active=True, decision_=answer("accept"))
TEMPS.clear()
check("B9 decide not called", _events("decide"), [])
check("B9 usual bump attempt", [b[0] for b in _events("bump")], [INVITEE])
check("B9 result", r, "Halvard invites Kira to come along.")
check("B9 Kira in no party", P.get_party_of(INVITEE), None)

print()
if FAILS:
    print(f"FAILED: {len(FAILS)} — {', '.join(FAILS)}")
    sys.exit(1)
print("OK")
