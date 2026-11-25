#!/usr/bin/env python3
"""Smoke run: a wanderer's arrival re-checks the world after a long retry.

Runs against a THROWAWAY storage directory; every collaborator of
``npc_spawn._settle_wanderer`` is replaced by a hand-written fake, so no world,
no LLM and no route search is touched.

Background (2026-11-25): the retry ``_send_wanderer`` builds a route, which
can take up to the search budget (minutes on the largest world). Two things
can change in that window, and the arrival used to act on the state it read
BEFORE the retry:

  [1] An avatar starts talking to the wanderer while the retry searches.
      Fakes: profile {wander_target: "B", wander_origin: "A"}, current
      location "B2" (not the target), the FIRST ``_in_chat`` answer is False,
      every later one True; ``_send_wanderer`` fails; the coin
      (``random.random``) = 0.9, so no turn-around (0.9 >= 0.5). By hand: the
      arrival must ask ``_in_chat`` again before pooling, gets True and
      leaves the wanderer standing -> result False, pool_npc called 0 times.
      (Old code: it pooled -> True, 1 call.)

  [2] The wanderer vanished (TTL sweep) while the retry searched. Fakes:
      the FIRST profile read returns {wander_target: "B", wander_origin: "A"},
      every later read None; location "B2"; ``_in_chat`` always False; the
      coin = 0.1 (< 0.5 -> turn around). By hand: under the lock the fresh
      read is empty -> nothing is written and nothing is sent -> result
      False, save_character_profile called 0 times, _send_wanderer called
      once (the retry only), pool_npc 0 times. (Old code: it saved the
      two keys into an empty profile -> 1 save, a resurrected sheet.)

  [3] The ordinary case still pools: same as [1] but ``_in_chat`` always
      False -> True, pool_npc called once with "wanderer arrived".

Usage:  ./.venv/bin/python scripts/smoke_wanderer_settle_late.py
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="wanderer-settle-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="wanderer-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)

from app.core import npc_actions, npc_ops, npc_pool, npc_spawn  # noqa: E402
from app.models import character  # noqa: E402

FAILURES = []
CHECKED = 0


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    if actual == expected:
        print(f"  ✓ {label}: {actual!r}")
    else:
        FAILURES.append(label)
        print(f"  ✗ {label}: got {actual!r}, expected {expected!r}")


class Fakes:
    def __init__(self, profiles, chats, coin):
        self.profiles = list(profiles)   # successive read answers
        self.chats = list(chats)         # successive _in_chat answers
        self.coin = coin
        self.saves = []
        self.sends = []
        self.pools = []

    def get_profile(self, _name):
        return self.profiles.pop(0) if len(self.profiles) > 1 else self.profiles[0]

    def in_chat(self, _name):
        return self.chats.pop(0) if len(self.chats) > 1 else self.chats[0]

    def install(self):
        saved = {
            (character, "get_character_profile"): character.get_character_profile,
            (character, "get_character_current_location"):
                character.get_character_current_location,
            (character, "save_character_profile"): character.save_character_profile,
            (npc_actions, "_in_chat"): npc_actions._in_chat,
            (npc_ops, "is_permanent_npc"): npc_ops.is_permanent_npc,
            (npc_pool, "pool_npc"): npc_pool.pool_npc,
            (npc_spawn, "_send_wanderer"): npc_spawn._send_wanderer,
            (npc_spawn.random, "random"): npc_spawn.random.random,
        }
        character.get_character_profile = self.get_profile
        character.get_character_current_location = lambda _n: "B2"
        character.save_character_profile = (
            lambda n, p: self.saves.append((n, dict(p))) or True)
        npc_actions._in_chat = self.in_chat
        npc_ops.is_permanent_npc = lambda _p: False
        npc_pool.pool_npc = lambda n, reason="": self.pools.append((n, reason))
        npc_spawn._send_wanderer = (
            lambda n, t: self.sends.append((n, t)) and False)
        npc_spawn.random.random = lambda: self.coin
        return saved


def run(fakes):
    saved = fakes.install()
    try:
        return npc_spawn._settle_wanderer("Wanderer")
    finally:
        for (mod, attr), value in saved.items():
            setattr(mod, attr, value)


PROFILE = {"wander_target": "B", "wander_origin": "A"}

print("[1] an avatar starts talking during the retry")
f = Fakes([dict(PROFILE)], [False, True], 0.9)
check("result", run(f), False)
check("pool_npc calls", f.pools, [])

print("[2] the wanderer vanished during the retry")
f = Fakes([dict(PROFILE), None], [False], 0.1)
check("result", run(f), False)
check("saves", f.saves, [])
check("sends (the retry only)", f.sends, [("Wanderer", "B")])
check("pool_npc calls", f.pools, [])

print("[3] the ordinary arrival still pools")
f = Fakes([dict(PROFILE)], [False], 0.9)
check("result", run(f), True)
check("pool_npc calls", f.pools, [("Wanderer", "wanderer arrived")])

print()
if FAILURES:
    print(f"FAILED — {len(FAILURES)} of {CHECKED} checks:")
    for x in FAILURES:
        print("  -", x)
    sys.exit(1)
print(f"OK — {CHECKED} checks passed")
