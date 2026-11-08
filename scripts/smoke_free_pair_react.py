#!/usr/bin/env python3
"""Smoke: a FREE pair pose started without asking (consent "react") — the
twin of a furniture pair run requested with consent "react".

Usage:  ./.venv/bin/python scripts/smoke_free_pair_react.py

The invitation table, the reaction state machine, the relationship booking
and the route are real (a throwaway world initialised before any world-DB
import). What lies past them is stubbed at module level: the pair start
(``interaction_engine.start_interaction`` records its calls, or raises
``TooFarApart`` when FAR is set), the walk over (``_walk_to_partner`` -> True),
``check_can_pair`` (BLOCKED per partner), the room narration (a recorder on
``perception.record_utterance``), languages ("en"), the hook bus (``emit``
recorded) and the ``pair_reaction`` provider (a recorder; the model never
runs). Every case uses its own pair, so each relationship starts fresh.

EXPECTATIONS, DERIVED BY HAND (constants of ``app.core.pair_reaction``:
REACTION_WAIT_S 60 system seconds, sentiment step 0.05 per feeling step,
romantic step 0.02, resisted actor -0.03; ``record_interaction`` books
sentiment_a = partner -> actor, sentiment_b = actor -> partner):

 1 POST /play/interact with consent "maybe" -> 400; with no consent the
   request is "ask" (case 10).
 2 react, NPC partner, provider present -> answer status "reacting"; ONE row
   inviter Ann / invitee Bob / pose hug, status "reacting"; the provider is
   asked ONCE with {kind "interaction", reference <invite id>, actor Ann,
   partner Bob}; NO "interaction.invited" (nobody is asked); the room hears
   "Ann approaches Bob: hug." (the pose has no catalog label, its key is
   its label); nothing started yet; outgoing_invite_of(Ann) is that row
   (the HUD shows it waiting, with a way to take it back);
   pair_reaction.pending -> {"action": "hug", "piece": ""}.
 3 react(Bob, accept, feeling 2, line) -> "started": start_interaction once
   with (Ann, Bob, hug), row "accepted", the line is told to the room as it
   is; Bob -> Ann +0.10, Ann -> Bob 0.0. A second answer -> "not_waiting"
   and books nothing (Bob -> Ann stays 0.10); pending -> None.
 4 Ann -> Cid, react(Cid, resist, feeling -2) -> "resisted" / reason
   "partner_resisted": nothing started, row "declined" with reason
   "partner_resisted", last_answer_of(Ann) is that declined row;
   Cid -> Ann -0.10, Ann -> Cid -0.03.
 5 react by someone else (Ann answering her own) -> refused "not_partner";
   accept "yes" (not a bool) -> refused "invalid_response"; the row still
   waits.
 6 no provider registered -> "started" at once (no wait), provider not asked.
 7 a player-controlled partner (Dee) -> "started" at once, provider not asked.
 8 no answer: 59 s later settle_approaches changes nothing (still
   "reacting"); 61 s later it goes on as accepted -> row "accepted",
   start_interaction called with (Ann, Fay, hug); nothing is booked.
 9 too far: react(accept) -> "approaching", row "approaching".
10 consent "ask" is unchanged: status "asked", row "pending",
   "interaction.invited" emitted once, the provider is not asked, the room
   hears "Ann suggests hug to Hal."
11 double click: a second react start of the same pair while it waits
   answers the same invite id, the provider is asked once, one row.
12 taken back while it waits: cancel_invite -> True, row "cancelled"; the
   late answer -> "not_waiting", books nothing (Ivy -> Ann 0.0).
13 blocked pair (check_can_pair "Jo is asleep") -> 409 with that detail,
   no row written.
14 the interact package: reaction_prompt("interaction", ...) renders with an
   empty piece (StrictUndefined holds) — 'Right now: Ann starts "hug" with
   Kai, without asking.' — and is None once answered;
   pair_reaction.answer with an unknown kind -> refused "invalid_kind".
15 a react pair accepted but blocked on start (Lea asleep by then): answer
   "cannot" with that reason, row "failed" / consent "react", nothing
   started, and the room hears the ACTOR's attempt — "Ann wanted to start
   hug with Lea, but it is not possible (Lea is asleep)." — never the
   invitation line "Lea would like to, ..." (nobody asked Lea).
16 the ask twin: Ann asks Mo, Mo is blocked by the time he says yes ->
   "cannot", row "failed" / consent "ask", and the invitation line stays
   "Mo would like to, but hug with Ann is not possible (Mo is asleep)."
   (consent of a row: case 2's / 10's rows read "react" / "ask"; case 9's
   walk keeps "react" while "approaching".)
"""
import sys
import tempfile
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_TMP = Path(tempfile.mkdtemp(prefix="smoke_free_pair_react_"))
from app.core import paths  # noqa: E402
paths.init(str(_TMP))
from app.core import db  # noqa: E402
db.init_schema()

from fastapi import HTTPException  # noqa: E402
from app.core import hooks, pair_reaction, perception  # noqa: E402
from app.core import interaction_engine as IE  # noqa: E402
import app.models.account as ACC  # noqa: E402
import app.models.character as C  # noqa: E402
from app.routes import play  # noqa: E402

FAILS = []


def check(name, got, want):
    ok = got == want
    print(f"  [{'OK  ' if ok else 'FAIL'}] {name}" + ("" if ok else f" — got {got!r}, want {want!r}"))
    if not ok:
        FAILS.append(name)


# ── stubs ────────────────────────────────────────────────────────────────
POSE = "hug"
AVATAR = "Ann"
PLAYERS = {AVATAR}
BLOCKED = {}
FAR = set()
STARTED = []
LINES = []
EMITTED = []
ASKED = []

ACC.is_player_controlled = lambda name: name in PLAYERS
ACC.get_active_character = lambda: AVATAR
C.get_character_language = lambda name: "en"
perception.record_utterance = lambda **kw: LINES.append(kw["content"])
_real_emit = hooks.emit
hooks.emit = lambda event, **kw: EMITTED.append((event, kw))
IE.partner_poses = lambda *a, **k: [(POSE, "hug")]
IE.check_can_pair = lambda actor, partner, pose_key="": BLOCKED.get(partner, "")
IE._walk_to_partner = lambda inv: True


def _start(actor, partner, pose_key, *, invite_id="", arrived=False):
    if partner in FAR:
        raise IE.TooFarApart(f"{partner} is too far away")
    STARTED.append((actor, partner, pose_key))
    return {"id": f"pair-{len(STARTED)}", "pose_key": pose_key}


IE.start_interaction = _start
play._interact_blocked = lambda avatar: ""
play._interact_charge = lambda avatar: None


def provide():
    hooks.register_provider("pair_reaction", lambda **kw: ASKED.append(kw), owner="smoke")


def unprovide():
    hooks._providers.pop("pair_reaction", None)


def route(**body):
    try:
        return play._play_interact_sync(body)
    except HTTPException as e:
        return {"http": e.status_code, "detail": e.detail}


def row(invite_id):
    return IE.get_invite(invite_id) or {}


def rows_of(inviter, invitee):
    return [r[0] for r in db.get_connection().execute(
        "SELECT status FROM interaction_invites WHERE inviter=? AND invitee=?",
        (inviter, invitee)).fetchall()]


def sentiment(source, target):
    from app.models.relationship import get_relationship
    rel = get_relationship(source, target) or {}
    first = rel.get("character_a") == source
    return round(rel.get("sentiment_a_to_b" if first else "sentiment_b_to_a", 0.0), 4)


def reset():
    STARTED.clear(), LINES.clear(), EMITTED.clear(), ASKED.clear()


provide()

print("1 consent validation")
check("consent 'maybe' -> 400", route(partner="Bob", pose=POSE, consent="maybe").get("http"), 400)
check("no row written", rows_of(AVATAR, "Bob"), [])

print("2 react start, NPC partner, provider present")
reset()
r = route(partner="Bob", pose=POSE, consent="react")
iid = r.get("invite_id", "")
check("status reacting", r.get("status"), "reacting")
check("row reacting", (row(iid).get("inviter"), row(iid).get("invitee"), row(iid).get("pose_key"),
                       row(iid).get("status")), (AVATAR, "Bob", POSE, "reacting"))
check("provider asked once", ASKED, [dict(kind="interaction", reference=iid, actor=AVATAR, partner="Bob")])
check("no interaction.invited", [e for e, _ in EMITTED if e == "interaction.invited"], [])
check("narration", LINES, ["Ann approaches Bob: hug."])
check("nothing started", STARTED, [])
check("outgoing shows it", (IE.outgoing_invite_of(AVATAR) or {}).get("invite_id"), iid)
check("row consent react", row(iid).get("consent"), "react")
check("pending words", pair_reaction.pending("interaction", iid, AVATAR, "Bob"), {"action": "hug", "piece": ""})

print("3 accept")
reset()
res = IE.react("Bob", iid, True, line="Bob smiles and opens his arms.", feeling=2)
check("started", res.get("status"), "started")
check("start_interaction once", STARTED, [(AVATAR, "Bob", POSE)])
check("row accepted", row(iid).get("status"), "accepted")
check("line told as it is", "Bob smiles and opens his arms." in LINES, True)
check("Bob -> Ann +0.10", sentiment("Bob", AVATAR), 0.1)
check("Ann -> Bob 0", sentiment(AVATAR, "Bob"), 0.0)
again = IE.react("Bob", iid, False, feeling=-2)
check("second answer not_waiting", again.get("status"), "not_waiting")
check("nothing booked twice", sentiment("Bob", AVATAR), 0.1)
check("pending None", pair_reaction.pending("interaction", iid, AVATAR, "Bob"), None)

print("4 resist")
reset()
iid = route(partner="Cid", pose=POSE, consent="react").get("invite_id", "")
res = IE.react("Cid", iid, False, line="Cid steps back.", feeling=-2)
check("resisted", (res.get("status"), res.get("reason")), ("resisted", "partner_resisted"))
check("nothing started", STARTED, [])
check("row declined", (row(iid).get("status"), row(iid).get("reason")), ("declined", "partner_resisted"))
ans = IE.last_answer_of(AVATAR) or {}
check("last answer", (ans.get("invite_id"), ans.get("status")), (iid, "declined"))
check("Cid -> Ann -0.10", sentiment("Cid", AVATAR), -0.1)
check("Ann -> Cid -0.03", sentiment(AVATAR, "Cid"), -0.03)

print("5 wrong partner, bad answer")
iid = route(partner="Eve", pose=POSE, consent="react").get("invite_id", "")
check("not_partner", IE.react(AVATAR, iid, False).get("reason"), "not_partner")
check("invalid_response", IE.react("Eve", iid, "yes").get("reason"), "invalid_response")
check("still waits", row(iid).get("status"), "reacting")
IE.cancel_invite(iid)

print("6 no provider -> no wait")
reset()
unprovide()
r = route(partner="Gus", pose=POSE, consent="react")
check("started at once", r.get("status"), "started")
check("provider not asked", ASKED, [])
check("row accepted", row(r.get("invite_id", "")).get("status"), "accepted")
provide()

print("7 player partner -> no wait")
reset()
PLAYERS.add("Dee")
r = route(partner="Dee", pose=POSE, consent="react")
check("started at once", r.get("status"), "started")
check("provider not asked", ASKED, [])
PLAYERS.discard("Dee")

print("8 no answer -> goes on after the wait")
reset()
iid = route(partner="Fay", pose=POSE, consent="react").get("invite_id", "")
created = row(iid)["created_at"]
from app.core.timeutils import parse_iso  # noqa: E402
base = parse_iso(created)
with patch.object(pair_reaction, "utc_now", lambda: base + timedelta(seconds=59)):
    IE.settle_approaches()
check("59 s: still reacting", row(iid).get("status"), "reacting")
with patch.object(pair_reaction, "utc_now", lambda: base + timedelta(seconds=61)):
    IE.settle_approaches()
check("61 s: accepted", row(iid).get("status"), "accepted")
check("started", STARTED, [(AVATAR, "Fay", POSE)])
check("nothing booked", sentiment("Fay", AVATAR), 0.0)

print("9 too far -> walks over")
reset()
FAR.add("Gil")
iid = route(partner="Gil", pose=POSE, consent="react").get("invite_id", "")
res = IE.react("Gil", iid, True)
check("approaching", res.get("status"), "approaching")
check("row approaching", row(iid).get("status"), "approaching")
check("approach keeps consent react", row(iid).get("consent"), "react")
FAR.discard("Gil")
IE.cancel_invite(iid)

print("10 ask unchanged")
reset()
r = route(partner="Hal", pose=POSE)
check("asked", r.get("status"), "asked")
check("row pending", rows_of(AVATAR, "Hal"), ["pending"])
check("row consent ask", (IE.outgoing_invite_of(AVATAR) or {}).get("consent"), "ask")
check("interaction.invited once", [e for e, _ in EMITTED if e == "interaction.invited"], ["interaction.invited"])
check("provider not asked", ASKED, [])
check("narration", LINES, ["Ann suggests hug to Hal."])

print("11 double click")
reset()
first = route(partner="Ida", pose=POSE, consent="react")
second = route(partner="Ida", pose=POSE, consent="react")
check("same invite", second.get("invite_id"), first.get("invite_id"))
check("status reacting", second.get("status"), "reacting")
check("asked once", len(ASKED), 1)
check("one row", rows_of(AVATAR, "Ida"), ["reacting"])
IE.cancel_invite(first["invite_id"])

print("12 taken back while it waits")
reset()
iid = route(partner="Ivy", pose=POSE, consent="react").get("invite_id", "")
check("cancel_invite", IE.cancel_invite(iid), True)
check("row cancelled", row(iid).get("status"), "cancelled")
check("late answer", IE.react("Ivy", iid, True, feeling=2).get("status"), "not_waiting")
check("nothing booked", sentiment("Ivy", AVATAR), 0.0)
check("nothing started", STARTED, [])

print("13 blocked")
BLOCKED["Jo"] = "Jo is asleep"
r = route(partner="Jo", pose=POSE, consent="react")
check("409 with the reason", (r.get("http"), r.get("detail")), (409, "Jo is asleep"))
check("no row", rows_of(AVATAR, "Jo"), [])

print("14 the interact package")
from app.core import decision_points, prompt_templates, stat_effects  # noqa: E402
from plugins.interact.reaction import reaction_prompt  # noqa: E402
prompt_templates.register_package_template_dirs(
    [*prompt_templates.template_search_dirs()[1:], ROOT / "plugins/interact/templates/llm"])
decision_points.invite_state = lambda invitee, inviter, offer: {
    "situation": "stub situation", "relationship": "stub relationship"}
stat_effects.build_stat_list = lambda name: ([], "")
iid = route(partner="Kai", pose=POSE, consent="react").get("invite_id", "")
prompt = reaction_prompt("interaction", iid, AVATAR, "Kai")
check("prompt renders", prompt is not None, True)
check("no piece", 'Right now: Ann starts "hug" with Kai, without asking.' in (prompt or ("", ""))[1], True)
IE.react("Kai", iid, True)
check("None once answered", reaction_prompt("interaction", iid, AVATAR, "Kai"), None)
check("unknown kind", pair_reaction.answer("other", iid, "Kai", True).get("reason"), "invalid_kind")

print("15 react accepted, blocked on start -> the actor's attempt is narrated")
reset()
iid = route(partner="Lea", pose=POSE, consent="react").get("invite_id", "")
BLOCKED["Lea"] = "Lea is asleep"
LINES.clear()
res = IE.react("Lea", iid, True)
check("cannot with the reason", (res.get("status"), res.get("reason")), ("cannot", "Lea is asleep"))
check("row failed, consent react", (row(iid).get("status"), row(iid).get("consent")), ("failed", "react"))
check("nothing started", STARTED, [])
check("actor's line", LINES, ["Ann wanted to start hug with Lea, but it is not possible (Lea is asleep)."])
BLOCKED.pop("Lea")

print("16 ask accepted, blocked on start -> the invitation line stays")
reset()
IE.cancel_invite((IE.outgoing_invite_of(AVATAR) or {}).get("invite_id", ""))
iid = IE.create_invite(AVATAR, "Mo", POSE)
BLOCKED["Mo"] = "Mo is asleep"
LINES.clear()
res = IE.resolve_invite(iid, True)
check("cannot", res.get("status"), "cannot")
check("row failed, consent ask", (row(iid).get("status"), row(iid).get("consent")), ("failed", "ask"))
check("invitation line", LINES, ["Mo would like to, but hug with Ann is not possible (Mo is asleep)."])
BLOCKED.pop("Mo")

hooks.emit = _real_emit
print()
if FAILS:
    print(f"FAIL: {len(FAILS)} check(s): {FAILS}")
    sys.exit(1)
print("smoke_free_pair_react: PASS")
