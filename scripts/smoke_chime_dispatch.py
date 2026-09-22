#!/usr/bin/env python3
"""Who gets bumped for a room utterance — the selection inside
``AgentLoop.dispatch_room_reactions`` (plan-gespraechs-auswahl.md § 3.2, T4).

Usage:
    ./.venv/bin/python scripts/smoke_chime_dispatch.py

Runs WITHOUT the server and without a real world DB: the storage directory is
redirected to a throwaway temp world before the first app import, so the
tracked worlds/demo/world.db is never opened. Everything the dispatch reads
from the world is stubbed — the room roster, the avatar flag, the travel
target, the open-air neighbours, the conversation pairs, the relationships
and the location — so what remains under test is the REAL selection logic of
``dispatch_room_reactions``. No LLM runs: a bump is in-memory bookkeeping.

THE SCENE, by hand: the taproom ``gasthaus/schankstube``. Present are Liesa,
Karl Schnaps, Luisa, Oskar and Rosi; the avatar Kai speaks (or, in [4], an
NPC does). The location carries ``chattiness`` 0.5 — the world default, set
explicitly so no config read can move the numbers. Nobody has a relationship
with anybody, so every candidate carries the no-relationship strength 10.

THE FORMULA (§ 3.2), evaluated by hand for this scene:

    rel  = 0.5 + strength/100 = 0.5 + 10/100          = 0.60
    aim  = 0.3 when the line HAS addressees, else 1.0
    score = chattiness x rel x aim
          = 0.5 x 0.6 x 0.3 = 0.09   (targeted line)
          = 0.5 x 0.6 x 1.0 = 0.30   (line to the room)

    p_any = max(score) — or 1.0 when ``always_someone`` (E6: avatar to the
    room). Draw r in [0, 1): r >= p_any -> nobody, else ONE candidate,
    weighted by score.

THE RNG is a stub with a fixed draw and a fixed pick index (documented per
case), so "r >= 0.09" and "r < 0.09" are the two halves of the draw, not a
seed whose value would have to be read off an output.

THE BACKSTOP must stay out of the way, so each case builds a FRESH AgentLoop
(``_room_ai_turns`` empty = 0 hops spent). The floor-mode rule matters for
the case layout: an avatar present in the room while an NPC speaks
(``is_avatar=False``) lowers the effective backstop to 1 — the FIRST round
still runs, every further one falls silent. Case [4] therefore has no avatar
in the room at all, and cases [1]-[3], [5], [6] are avatar lines
(``is_avatar=True``), which reset the budget instead of spending it.

Hand-derived expectations:

  [1] TARGETED LINE, NOBODY CHIMES IN. Kai says "Hallo Liesa" to Liesa.
      Obligatory = the addressee present = ["Liesa"]. Candidates are the
      four others, each 0.09; ``always_someone`` is False (the line HAS an
      addressee), so p_any = 0.09. Draw r = 0.5 >= 0.09 -> nobody. Result
      obligatory ["Liesa"], chime []. This is the whole point of the strand:
      before it, all four were bumped and "Hallo Liesa" produced five
      answers. "Luisa" is NOT a match for "Liesa" — different word, and a
      first name is never resolved to a full name anyway.

  [2] THE SAME LINE, THE OTHER HALF OF THE DRAW. r = 0.05 < 0.09 -> exactly
      ONE of the four chimes in, and it is never Liesa (she is the addressee
      and answers obligatorily, so she is not even a candidate). With the
      stub's pick index 0 it is the first candidate, Karl Schnaps — but the
      case asserts the RULE (exactly one, from the candidate set, not the
      addressee), not the pick.

  [3] TO THE ROOM, SO SOMEONE ALWAYS ANSWERS (E6). Kai says "Guten Abend
      zusammen" with no addressee. Nobody is obliged; all five are
      candidates at 0.30, and because the avatar must never talk into the
      void p_any = 1.0. Even the draw r = 0.5, which would kill a 0.30
      chance, yields exactly ONE chime.

  [4] EVERYBODY IS BUSY -> SILENCE. Karl Schnaps (an NPC, no avatar in the
      room) says something to the room. Liesa<->Luisa and Oskar<->Rosi are
      standing in two foreign pairs, and none of those partners is the
      speaker, so every candidate scores 0. p_any = 0 and the weighted pick
      has nothing to pick from -> chime []. A forced draw could not help
      here either: ``always_someone`` cannot conjure a speaker out of zeros.

  [5] BEING NAMED BEATS EVERYTHING. Kai says "Karl Schnaps, was meinst du?"
      to Liesa. Karl is mid-pair with Oskar and the line is targeted
      (aim 0.3), so by score alone he would be a 0.0 busy candidate — but
      his FULL name stands in the line, which makes him part of it: chime
      ["Karl Schnaps"], for r = 0.99 as well as for r = 0.0. Liesa still
      answers obligatorily.

  [6] A WHISPER DISTRIBUTES NO CHIMES. The same room-wide avatar line as
      [3], whispered: no addressee, ``always_someone`` would be True — and
      the chime list is still empty, because a private volume never invites
      bystanders. Obligatory stays empty too (no addressee).

  [7] THE SECOND CHIME SOURCE IS PAIR-GATED (§ 3.3).
      ``_maybe_active_conversation_chime`` turns an autonomous THOUGHT turn
      into a spoken one when a fresh foreign line stands in the character's
      room stream — that is the back door through which the round-robin
      would walk back in. Rosi's stream carries one line of Kai's, 0 seconds
      old (the window stays 240 s of SYSTEM time: it is the loop's cadence,
      not world time), and the gate is asked four times:
        (a) the line went to Liesa and Luisa, Rosi has no partner
            -> None (a foreign pair is none of Rosi's business),
        (b) the line went to Rosi itself                  -> a chime dict,
        (c) the line carries no addressees at all (room)  -> a chime dict,
        (d) the line went to Liesa, and Liesa is Rosi's own partner
            -> a chime dict (Rosi is part of that conversation).
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Storage MUST be redirected BEFORE the first app import: otherwise the
# default world is worlds/demo, which is tracked in git.
STORAGE = Path(tempfile.mkdtemp(prefix="chime-dispatch-storage-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(
    prefix="chime-dispatch-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)

from app.core import agent_loop as al  # noqa: E402
from app.core import chime_select  # noqa: E402
from app.core import conversation_pairs  # noqa: E402
from app.core import perception  # noqa: E402
from app.core import room_entry  # noqa: E402
from app.models import account, character, relationship, world  # noqa: E402

LOC = "gasthaus"
ROOM = "schankstube"
AVATAR = "Kai"
PRESENT = ["Liesa", "Karl Schnaps", "Luisa", "Oskar", "Rosi"]

FAILED = []


def check(name, got, expected):
    ok = got == expected
    print(f"  [{'OK  ' if ok else 'FAIL'}] {name}"
          + ("" if ok else f" — got {got!r}, expected {expected!r}"))
    if not ok:
        FAILED.append(name)


def check_true(name, cond, detail=""):
    check(name + (f" ({detail})" if detail else ""), bool(cond), True)


class FixedRandom:
    """An RNG with a fixed draw and a fixed pick — the two decisions
    ``select_chimer`` makes, pinned so a case is arithmetic, not luck."""

    def __init__(self, draw: float, pick: int = 0):
        self.draw = draw
        self.pick = pick

    def random(self) -> float:
        return self.draw

    def choices(self, population, weights=None, k=1):
        return [population[self.pick % len(population)]]


_REAL_SELECT = chime_select.select_chimer


def use_rng(draw: float, pick: int = 0) -> None:
    """Make the dispatch's selection draw a known number."""
    def _select(candidates, **kwargs):
        kwargs.pop("rng", None)
        return _REAL_SELECT(candidates, rng=FixedRandom(draw, pick), **kwargs)
    chime_select.select_chimer = _select


def set_world(present=PRESENT, partners=None, avatars=(AVATAR,),
              chattiness=0.5):
    """Stub everything the dispatch reads from the world."""
    room_entry.characters_in_room = lambda loc, room: list(present)
    character.get_character_current_location = lambda name: LOC
    character.get_movement_target = lambda name: ""
    account.is_player_controlled = lambda name: name in avatars
    perception.nearby_in_the_open = lambda name: []
    conversation_pairs.partners_in_room = lambda loc, room: dict(partners or {})
    relationship.get_relationship = lambda a, b: None
    world.get_location_by_id = lambda loc: {"id": LOC, "chattiness": chattiness}
    al._is_respond_eligible = lambda name: True
    al._halt_addressed_wanderer = lambda name: False


def dispatch(speaker, content, addressees, is_avatar, volume="normal"):
    loop = al.AgentLoop()          # fresh backstop budget per case
    return loop.dispatch_room_reactions(
        speaker=speaker, content=content, volume=volume,
        location_id=LOC, room_id=ROOM, addressees=addressees,
        is_avatar=is_avatar)


# ── [1] targeted line, draw above 0.09 ──────────────────────────────────
print("[1] 'Hallo Liesa' — only Liesa answers (r = 0.5 >= 0.09)")
set_world()
use_rng(0.5)
res = dispatch(AVATAR, "Hallo Liesa", ["Liesa"], True)
check("the addressee answers", res["obligatory"], ["Liesa"])
check("and nobody chimes in", res["chime"], [])

# ── [2] the same line, draw below 0.09 ──────────────────────────────────
print("[2] the same line with r = 0.05 < 0.09 — exactly one bystander")
set_world()
use_rng(0.05)
res = dispatch(AVATAR, "Hallo Liesa", ["Liesa"], True)
check("the addressee still answers", res["obligatory"], ["Liesa"])
check("exactly ONE chime", len(res["chime"]), 1)
check_true("the chime is a bystander, not the addressee",
           res["chime"][0] in PRESENT and res["chime"][0] != "Liesa",
           res["chime"][0])

# ── [3] to the room: always someone (E6) ────────────────────────────────
print("[3] 'Guten Abend zusammen' to the room — the player never talks "
      "into the void")
set_world()
use_rng(0.5)
res = dispatch(AVATAR, "Guten Abend zusammen", [], True)
check("nobody is obliged", res["obligatory"], [])
check("but exactly one answers", len(res["chime"]), 1)
check_true("and it is someone present", res["chime"][0] in PRESENT,
           res["chime"][0])

# ── [4] everybody stuck in foreign pairs ────────────────────────────────
print("[4] two foreign pairs in the room — an NPC line reaches nobody")
set_world(present=["Liesa", "Luisa", "Oskar", "Rosi"],
          partners={"Liesa": "Luisa", "Luisa": "Liesa",
                    "Oskar": "Rosi", "Rosi": "Oskar"},
          avatars=())
use_rng(0.0)          # even the friendliest draw cannot save a zero score
res = dispatch("Karl Schnaps", "Was fuer ein Abend, was?", [], False)
check("nobody is obliged", res["obligatory"], [])
check("and nobody chimes in", res["chime"], [])

# ── [5] the mention wins, busy or not, draw or not ──────────────────────
print("[5] 'Karl Schnaps, was meinst du?' — being named beats the draw")
for draw in (0.99, 0.0):
    set_world(partners={"Karl Schnaps": "Oskar", "Oskar": "Karl Schnaps"})
    use_rng(draw)
    res = dispatch(AVATAR, "Karl Schnaps, was meinst du?", ["Liesa"], True)
    check(f"the addressee answers (r = {draw})", res["obligatory"], ["Liesa"])
    check(f"the named one chimes in (r = {draw})", res["chime"],
          ["Karl Schnaps"])

# ── [6] a whisper distributes nothing ───────────────────────────────────
print("[6] the same room-wide line, whispered — no chime at all")
set_world()
use_rng(0.0)
res = dispatch(AVATAR, "Guten Abend zusammen", [], True, volume="whisper")
check("nobody is obliged", res["obligatory"], [])
check("and a whisper invites nobody", res["chime"], [])

# ── [7] the second chime source is pair-gated ───────────────────────────
print("[7] _maybe_active_conversation_chime only picks up its OWN "
      "conversation")
from app.core.timeutils import utc_now  # noqa: E402
from app.models import perception_store  # noqa: E402


def stream_line(addressees):
    """One fresh foreign line in Rosi's room stream (oldest → newest)."""
    meta = {"speaker": AVATAR}
    if addressees is not None:
        meta["addressees"] = list(addressees)
    return [{"speaker": AVATAR, "content": "Noch ein Bier?", "kind": "heard",
             "ts": utc_now().isoformat(), "meta": meta}]


def gate(addressees, partner):
    character.get_character_current_location = lambda name: LOC
    character.get_character_current_room = lambda name: ROOM
    perception_store.get_character_room_stream = \
        lambda who, loc, room, limit=6: stream_line(addressees)
    conversation_pairs.conversation_partner = lambda who, loc, room: partner
    return al.AgentLoop()._maybe_active_conversation_chime("Rosi")


check("(a) a line between two others is not Rosi's turn",
      gate(["Liesa", "Luisa"], None), None)
check_true("(b) a line TO Rosi is",
           (gate(["Rosi"], None) or {}).get("speaker") == AVATAR)
check_true("(c) a line to the room is too",
           (gate(None, None) or {}).get("speaker") == AVATAR)
check_true("(d) and a line to Rosi's own partner is as well",
           (gate(["Liesa"], "Liesa") or {}).get("speaker") == AVATAR)

print()
if FAILED:
    print(f"FAILED ({len(FAILED)}): " + ", ".join(FAILED))
    sys.exit(1)
print("all checks passed")
