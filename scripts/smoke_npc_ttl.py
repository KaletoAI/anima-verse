#!/usr/bin/env python3
"""Smoke run for the temporary-NPC TTL readout (plan-npc-leben-bugs, task 1).

Throwaway storage, throwaway world DB, throwaway task queue — no server, no
real world is touched. The GAME clock is frozen (``set_game_factor(0.0)`` +
``set_game_time``), so every number below is exact and reproducible; there is
no system clock anywhere in this feature.

THE RULE, by hand. ``npc_ops.remaining_span(expires_at)`` answers the pair the
Game-Admin list renders, and ``npc_summary`` carries it as ``remaining_hours``
+ ``remaining_label``:

    left            = GameTime.parse(expires_at) - game_time()   → GameDuration
    remaining_hours = round(left.total_seconds / 3600, 2)        (may be < 0)
    remaining_label = "{h}h {m}m"  for a full hour or more, with the minutes
                                   dropped when they are 0 ("2h", never "2h 0m")
                      "{m}m"       below one hour
                      "expired"    when nothing is left
                      ""           when there is no stamp at all

    No stamp ("" — the NPC lives until an admin deletes it) answers
    ``(None, "")``. A NEGATIVE span is a real state, not an error: the sweep
    runs on a tick, so an NPC can be past its stamp and still standing, and the
    list has to say so instead of quietly showing nothing.

    The boundary "exactly nothing left" follows ``is_expired`` (``game_time()
    >= stamp``), so a span of 0 s reads "expired" too — label and the row's
    ``expired`` flag can never disagree about the same instant.

THE CLOCK, by hand. The world starts at Year 1, Day 1, 00:00 (= 0 game
seconds) and a game day is 24·3600 = 86 400 s. This run freezes it at

    T0 = 10 days + 12 h = 10·86 400 + 43 200 = 907 200 s   (Year 1, Day 11, 12:00)

and moves it only by whole, hand-counted spans.

  [1] TTL 2.5 h, stamped by the real creation path. ``expiry_stamp(2.5)`` is
      T0 + 2.5·3600 = T0 + 9 000 s = 916 200 s (Day 11, 14:30), so with the
      clock still at T0 the span is 9 000 s:
        remaining_hours  9000/3600      = 2.5
        remaining_label  9000 = 2 h + 1 800 s = 2 h 30 min → "2h 30m"
        expired          False
      Both values also ride in ``npc_summary`` — that is the payload
      `GET /npc/list` hands the list.

  [2] The clock, not the stamp, moves. Advancing the game clock by 2 h to
      T0 + 7 200 s leaves 916 200 − 914 400 = 1 800 s on the SAME stamp:
        remaining_hours  1800/3600      = 0.5
        remaining_label  under one hour → minutes only → "30m"

  [3] Whole hours drop the minutes. A stamp at clock + 7 200 s:
        remaining_hours  2.0     remaining_label "2h"   (never "2h 0m")

  [4] Minutes round DOWN to whole minutes, hours to 2 decimals. A stamp at
      clock + 100 s:
        remaining_hours  round(100/3600, 2) = round(0.0277…, 2) = 0.03
        remaining_label  100 s = 1 min 40 s → whole minutes → "1m"

  [5] No stamp = no readout. ``ttl_hours`` 0/None writes ``expires_at = ""``
      (``expiry_stamp``), and the pair is ``(None, "")`` — NOT 0/"expired".
      An NPC without a TTL is not an expired NPC.

  [6] A stamp in the PAST. Clock at T0, stamp at T0 − 3 600 s:
        remaining_hours  −3600/3600     = −1.0
        remaining_label  "expired"
        expired          True
      The row still exists — the sweep has not run yet.

  [7] The boundary. Stamp exactly equal to the clock: span 0 s →
        remaining_hours  0.0     remaining_label "expired"    expired True
      matching ``is_expired``'s ``>=`` at that same instant.

  [8] Junk is not a stamp. A profile carrying ``expires_at = "soon"`` answers
      ``(None, "")`` and ``expired False`` — the same as no stamp, so a
      hand-edited profile cannot crash the list.

THE LIFETIME EDIT, by hand (task 2). ``expires_at`` is a GAME stamp and only
the server owns that clock, so the admin never types one: the config form
sends ``lifetime`` (``default|permanent|custom``) plus ``lifetime_hours``, and
``character_ops.apply_profile_update`` RECOMPUTES the stamp before it writes
the profile. The rule, in full:

    permanent → expires_at = ""            npc_permanent = True
    custom    → expires_at = expiry_stamp(lifetime_hours)   npc_permanent = False
                (no usable number yet → the MODE is kept and only the stamp
                 falls back to the default TTL, see [15])
    default   → expires_at = expiry_stamp(wanderer_ttl_hours() if the profile
                is a wanderer else slot_ttl_hours())        npc_permanent = False

The branch fires ONLY for a temporary NPC and ONLY when the save carries
``lifetime`` or ``lifetime_hours``; every other save leaves the stamp alone.

  [9] PERMANENT. An NPC stamped for 4 h (T0 + 14 400 s) is made permanent:
        expires_at      ""            (the empty stamp means "never")
        npc_permanent   True
        remaining pair  (None, "")    — no TTL is not an expired TTL ([5])
        npc_summary.permanent  True
      and ``sweep_expired_npcs`` leaves it standing, because the sweep asks
      ``is_expired("")`` → False (unchanged from task 1).

 [10] CUSTOM. With the clock frozen at T0 = 907 200 s, ``lifetime custom``
      + ``lifetime_hours 3`` writes T0 + 3·3 600 = 907 200 + 10 800
      = 918 000 s = Year 1, Day 11, 15:00 → "Y0001-D011T15:00:00", and
      ``remaining_span`` reads (3.0, "3h"). ``npc_permanent`` goes back to
      False — making an NPC mortal again is the same one edit.
      [10b] The HOURS alone are an edit too: a save carrying only
      ``lifetime_hours 1`` on an NPC whose mode already is ``custom`` restamps
      to T0 + 3 600 = 910 800 s = Day 11, 13:00.
      [10c] ``lifetime_hours 0`` is not a lifetime → the default rule below.

 [11] DEFAULT reads the WORLD's TTL config, not a constant. With
      ``npc.slot_ttl_game_hours = 6`` a settled NPC restamps to T0 + 6·3 600
      = 928 800 s = Day 11, 18:00; with ``npc.wanderer_ttl_game_hours = 9`` a
      profile carrying ``npc_wanderer`` restamps to T0 + 9·3 600 = 939 600 s
      = Day 11, 21:00. Two lifetimes, one dropdown entry — which one applies
      is the NPC's own kind.

 [12] THE FLAG SURVIVES THE POOL. ``pool_npc`` empties ``expires_at`` and
      keeps every other key, so a permanent NPC comes back out of the pool
      permanent: ``revive_from_pool(..., ttl_hours=5)`` leaves the stamp ""
      instead of writing T0 + 5 h. A NON-permanent sheet is stamped as ever:
      T0 + 5·3 600 = 925 200 s = Day 11, 17:00.

 [13] NOT A TEMPORARY NPC, no branch. A full character (template
      ``human-roleplay``) saved with ``lifetime: "permanent"`` keeps whatever
      ``expires_at`` it had and gets NO ``npc_permanent`` — the recompute is
      temp-NPC bookkeeping, and ``is_temporary_npc`` is the only gate (never
      a name or a template string in code).

 [14] AN UNRELATED SAVE NEVER RESTARTS A LIFETIME. Saving ``standing_task``
      on a temporary NPC leaves the stamp from [12] byte for byte — otherwise
      every edit in the config form would quietly give the NPC a fresh day.

 [15] THE FORM SAVES ONE FIELD PER REQUEST (``TemplateField`` commits a select
      the moment it changes; both renderers post ``{fields: {<key>: value}}``),
      so picking "custom" ALWAYS arrives without any hours. Two calls, exactly
      as the form makes them, with the slot TTL at 6 h from [10c]:
        1) ``{"lifetime": "custom"}``      → mode stays "custom", and only the
           STAMP falls back: T0 + 6·3 600 = 928 800 s = Day 11, 18:00
        2) ``{"lifetime_hours": 3}``       → the stored mode is read back as
           "custom" → T0 + 3·3 600 = 918 000 s = Day 11, 15:00
      Writing "default" back in step 1 would shut the dropdown, hide the hours
      field and make step 2 stamp the default TTL again — the custom lifetime
      would be unreachable through the UI.

 [16] A PERMANENT SHEET IS NOT POOL STOCK. ``take_from_pool`` hands automatic
      spawns a recycled character sheet; a sheet an admin made permanent is a
      kept character, not spare parts, so it is skipped — for a named role AND
      for the empty role a wanderer spawn asks with. With ONLY a permanent
      sheet pooled both questions answer None; once a mortal sheet of the same
      role joins it, both answer that one.

 [17] AND IT NEVER WALKS INTO THE POOL BY ITSELF EITHER. ``_settle_wanderer``
      ends a wanderer's arrival with a 50/50 coin: turn around, or into the
      pool. For a PERMANENT wanderer the pool half is a one-way door — [16]
      just proved ``take_from_pool`` skips such a sheet — so the coin is not
      tossed at all and the turn-around is unconditional.

      A HAND-DRAWN WORLD for this section, the smallest one an arrival needs:
      one grass rectangle from (−60, −60) to (300, 300) and two placed
      locations, each a 10 m square around its anchor —

          INN     anchor (0, 0)     footprint x,z ∈ [−5, 5]
          MARKET  anchor (100, 0)   footprint x,z ∈ [95, 105]

      Both wanderers stand at (100, 0), i.e. inside MARKET's footprint, so
      ``current_location`` derives to MARKET; both carry ``wander_target``
      MARKET and ``wander_origin`` INN and no journey — the exact "arrived"
      state the tick reacts to. ``random.random`` is pinned to 0.9, which is
      NOT < 0.5, so the coin says "pool" for anybody who is asked:

        Yarrow  (permanent) → the coin is never tossed. Target and origin swap
                              to INN/MARKET, a fresh journey to INN, status
                              still "" (alive) and the tick answers True.
        Thistle (mortal)    → the coin says pool: status "pooled", and the tick
                              answers True as it always did.

      A permanent wanderer with NO origin to turn back to is the third case:
      Bramble, permanent, ``wander_origin`` "" — there is no road back, so the
      tick answers FALSE (nothing settled, it stands and is asked again next
      tick) and it is still alive. The mortal sheet in that same state is the
      one that lands in the pool.

 [18] A CUSTOM LIFETIME SURVIVES THE REVIVE. ``revive_from_pool`` stamps the
      TTL its CALLER hands in (the slot's, the wanderer's), which overwrote the
      hours an admin had typed: the dropdown kept saying "custom, 3 hours"
      while the NPC actually died after the slot's TTL, on every single revive.
      The sheet's own decision wins now, exactly as ``permanent`` does in [12]:
        Marrow  lifetime custom + lifetime_hours 3, pooled, revived with
                ``ttl_hours=5`` → T0 + 3·3 600 = 918 000 s = Day 11, 15:00,
                NOT T0 + 5 h (Day 11, 17:00).
        Sorrel  lifetime custom + lifetime_hours 0 — not a lifetime at all
                ([10c]) → the caller's 5 h stand: Day 11, 17:00.
      ``default`` is unchanged and stays proven by [12]'s Rook.

 [19] THE MODE ALONE MAKES A SHEET PERMANENT, AND THE SWEEP HEALS IT.
      ``npc_permanent`` is younger than the ``lifetime`` dropdown, so a sheet
      made permanent before the flag existed carries the MODE and no flag —
      and an older revive stamped exactly such a sheet with a fresh TTL, which
      the sweep then read as a real lifetime. Every reader asks
      ``npc_ops.is_permanent_npc`` now, so:

        Ember   lifetime "permanent", NO npc_permanent key, expires_at
                T0 − 3 600 s = 903 600 s = Day 11, 11:00 (an hour in the past,
                so ``is_expired`` says True). ``sweep_expired_npcs`` leaves it
                ALIVE (status "") and HEALS the sheet: expires_at "" and
                npc_permanent True, so the admin list stops showing
                "expires in …" beside "permanent". Pooling it would be a
                one-way door — [16] proves ``take_from_pool`` skips it.
        Ash     no mode, no flag, the SAME past stamp → pooled by that very
                same sweep call (status "pooled"), unchanged behaviour.

Usage:  ./.venv/bin/python scripts/smoke_npc_ttl.py
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="npcttl-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="npcttl-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import config, db  # noqa: E402
config.load(STORAGE / "config.json")
db.init_schema()

from app.core import embedding, npc_ops, npc_spawn  # noqa: E402
from app.core.character_ops import apply_profile_update  # noqa: E402
from app.core.game_time import GameDuration, GameTime  # noqa: E402
from app.core.npc_ops import (apply_npc, expiry_stamp,  # noqa: E402
                              is_expired, npc_summary, remaining_span,
                              sweep_expired_npcs)
from app.core.npc_pool import (pool_npc, revive_from_pool,  # noqa: E402
                               take_from_pool)
from app.core.task_queue import get_task_queue  # noqa: E402
from app.core.timeutils import set_game_factor, set_game_time  # noqa: E402
from app.models import terrain  # noqa: E402
from app.models.character import (get_character_current_location,  # noqa: E402
                                  get_character_profile,
                                  get_character_status,
                                  list_temporary_npcs,
                                  save_character_profile, set_character_pos)
from app.models.world import (_load_world_data, _save_world_data,  # noqa: E402
                              add_location, update_location_position)

# Offline: no embedding model is downloaded for the pose catalog.
embedding.embed = lambda text: None

# No worker threads in a smoke — nothing here executes a queued task.
get_task_queue()._started = True

FAILURES = []
CHECKED = 0


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'OK ' if ok else 'FAIL'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


# ── the frozen clock ────────────────────────────────────────────────────────

set_game_factor(0.0)
T0 = GameTime(0) + GameDuration.of(days=10, hours=12)
check("the frozen clock stands where the docstring says",
      T0.total_seconds, 907200)
set_game_time(T0)


def set_npc_cfg(**values) -> None:
    """Merge keys into this throwaway world's ``npc`` config section."""
    cfg = config.get_all()
    cfg.setdefault("npc", {}).update(values)
    config.save(cfg, STORAGE / "config.json")


def make_npc(name: str, *, ttl_hours=None) -> str:
    """A living temporary NPC through the real creation path, gate off."""
    set_npc_cfg(require_assets=False)
    apply_npc({"character_name": name,
               "character_appearance": "a lean figure in a patched coat",
               "face_appearance": "a narrow face, dark eyes",
               "outfit_description": "a patched brown coat",
               "standing_task": "watching the road"},
              "", ttl_hours=ttl_hours, created_by="smoke_npc_ttl")
    return name


def stamp_at(name: str, offset: GameDuration) -> str:
    """Put ``expires_at`` ``offset`` away from the CURRENT game clock."""
    profile = get_character_profile(name) or {}
    profile["expires_at"] = (npc_ops.game_time() + offset).canonical()
    save_character_profile(name, profile)
    return profile["expires_at"]


# ---------------------------------------------------------------------------
print("\n[1] a 2.5 h TTL, read straight off the creation path")

make_npc("Torvin", ttl_hours=2.5)
STAMP = (get_character_profile("Torvin") or {}).get("expires_at")
check("expiry_stamp(2.5) is T0 + 9000 s",
      GameTime.parse(STAMP).total_seconds, 916200)
check("the stamp reads as Day 11, 14:30", STAMP, "Y0001-D011T14:30:00")
check("remaining_span at T0", remaining_span(STAMP), (2.5, "2h 30m"))

row = npc_summary("Torvin")
check("npc_summary carries the hours", row["remaining_hours"], 2.5)
check("npc_summary carries the label", row["remaining_label"], "2h 30m")
check("npc_summary is not expired", row["expired"], False)

# ---------------------------------------------------------------------------
print("\n[2] the CLOCK moves, the stamp does not")

set_game_time(T0 + GameDuration.of(hours=2))
check("the same stamp now has 30 minutes left",
      remaining_span(STAMP), (0.5, "30m"))
check("npc_summary agrees",
      (npc_summary("Torvin")["remaining_hours"],
       npc_summary("Torvin")["remaining_label"]), (0.5, "30m"))

set_game_time(T0)      # back to the frozen instant for everything below

# ---------------------------------------------------------------------------
print("\n[3] whole hours drop the minutes")

check("a stamp two hours out",
      remaining_span((T0 + GameDuration.of(hours=2)).canonical()), (2.0, "2h"))

# ---------------------------------------------------------------------------
print("\n[4] under an hour: whole minutes, hours to two decimals")

check("a stamp 100 seconds out",
      remaining_span((T0 + GameDuration.of(seconds=100)).canonical()),
      (0.03, "1m"))

# ---------------------------------------------------------------------------
print("\n[5] no stamp is not an expired stamp")

make_npc("Brenna", ttl_hours=None)
check("expiry_stamp writes nothing for no TTL", expiry_stamp(None), "")
check("remaining_span of an empty stamp", remaining_span(""), (None, ""))
never = npc_summary("Brenna")
check("npc_summary of a TTL-less NPC",
      (never["expires_at"], never["remaining_hours"],
       never["remaining_label"], never["expired"]), ("", None, "", False))

# ---------------------------------------------------------------------------
print("\n[6] a stamp in the past — the row is still there")

past = stamp_at("Brenna", GameDuration.of(hours=-1))
check("the past stamp", past, "Y0001-D011T11:00:00")
check("remaining_span went negative", remaining_span(past), (-1.0, "expired"))
gone = npc_summary("Brenna")
check("npc_summary of an NPC past its stamp",
      (gone["remaining_hours"], gone["remaining_label"], gone["expired"]),
      (-1.0, "expired", True))

# ---------------------------------------------------------------------------
print("\n[7] the boundary follows is_expired")

now_stamp = stamp_at("Brenna", GameDuration.ZERO)
check("nothing left reads as expired", remaining_span(now_stamp),
      (0.0, "expired"))
check("and is_expired says the same at that instant",
      is_expired(now_stamp), True)

# ---------------------------------------------------------------------------
print("\n[8] junk on the profile is not a stamp")

profile = get_character_profile("Brenna") or {}
profile["expires_at"] = "soon"
save_character_profile("Brenna", profile)
junk = npc_summary("Brenna")
check("a hand-edited profile cannot crash the list",
      (junk["remaining_hours"], junk["remaining_label"], junk["expired"]),
      (None, "", False))

# ---------------------------------------------------------------------------
print("\n[9] the lifetime edit: permanent")

SABLE = make_npc("Sable", ttl_hours=4)
check("stamped for four hours first",
      (get_character_profile(SABLE) or {}).get("expires_at"),
      "Y0001-D011T16:00:00")

apply_profile_update(SABLE, {"fields": {"lifetime": "permanent"}})
sable = get_character_profile(SABLE) or {}
check("permanent empties the stamp", sable.get("expires_at"), "")
check("and raises the flag", sable.get("npc_permanent"), True)
check("the mode is stored as picked", sable.get("lifetime"), "permanent")
row = npc_summary(SABLE)
check("npc_summary says permanent", row["permanent"], True)
check("with no span and no expiry",
      (row["remaining_hours"], row["remaining_label"], row["expired"]),
      (None, "", False))
sweep_expired_npcs()
check("the sweep leaves a permanent NPC standing",
      SABLE in list_temporary_npcs(), True)

# ---------------------------------------------------------------------------
print("\n[10] the lifetime edit: custom hours")

apply_profile_update(SABLE, {"fields": {"lifetime": "custom",
                                        "lifetime_hours": 3}})
sable = get_character_profile(SABLE) or {}
check("three game hours from T0", sable.get("expires_at"),
      "Y0001-D011T15:00:00")
check("the stamp is T0 + 10800 s",
      GameTime.parse(sable["expires_at"]).total_seconds, 918000)
check("the flag comes back down", sable.get("npc_permanent"), False)
check("the span reads three hours",
      remaining_span(sable["expires_at"]), (3.0, "3h"))
check("npc_summary is mortal again", npc_summary(SABLE)["permanent"], False)

print("[10b] the hours alone are an edit too")
apply_profile_update(SABLE, {"fields": {"lifetime_hours": 1}})
check("one game hour from T0",
      (get_character_profile(SABLE) or {}).get("expires_at"),
      "Y0001-D011T13:00:00")

print("[10c] zero hours is no usable number — the stamp falls back")
set_npc_cfg(slot_ttl_game_hours=6, wanderer_ttl_game_hours=9)
apply_profile_update(SABLE, {"fields": {"lifetime": "custom",
                                        "lifetime_hours": 0}})
sable = get_character_profile(SABLE) or {}
check("it falls back to the slot TTL", sable.get("expires_at"),
      "Y0001-D011T18:00:00")
check("but the picked mode is kept", sable.get("lifetime"), "custom")

# ---------------------------------------------------------------------------
print("\n[11] the lifetime edit: default reads the world's TTL config")

apply_profile_update(SABLE, {"fields": {"lifetime": "default"}})
check("slot TTL 6 h → Day 11, 18:00",
      (get_character_profile(SABLE) or {}).get("expires_at"),
      "Y0001-D011T18:00:00")

sable = get_character_profile(SABLE) or {}
sable["npc_wanderer"] = True
save_character_profile(SABLE, sable)
apply_profile_update(SABLE, {"fields": {"lifetime": "default"}})
check("a WANDERER gets the wanderer TTL 9 h → Day 11, 21:00",
      (get_character_profile(SABLE) or {}).get("expires_at"),
      "Y0001-D011T21:00:00")
sable = get_character_profile(SABLE) or {}
sable["npc_wanderer"] = False
save_character_profile(SABLE, sable)

# ---------------------------------------------------------------------------
print("\n[12] the flag survives the pool, the revive does not re-stamp")

apply_profile_update(SABLE, {"fields": {"lifetime": "permanent"}})
check("pooled", pool_npc(SABLE, reason="smoke"), True)
pooled = get_character_profile(SABLE) or {}
check("pooling keeps the flag", pooled.get("npc_permanent"), True)
check("and empties the stamp as ever", pooled.get("expires_at"), "")
check("revived", revive_from_pool(SABLE, "", ttl_hours=5), True)
check("a permanent NPC comes back without a lifetime",
      (get_character_profile(SABLE) or {}).get("expires_at"), "")

ROOK = make_npc("Rook", ttl_hours=2)
check("pooled", pool_npc(ROOK, reason="smoke"), True)
check("revived", revive_from_pool(ROOK, "", ttl_hours=5), True)
check("a mortal NPC is stamped exactly as before",
      (get_character_profile(ROOK) or {}).get("expires_at"),
      "Y0001-D011T17:00:00")

# ---------------------------------------------------------------------------
print("\n[13] a full character never enters the branch")

save_character_profile("demo_full", {
    "character_name": "demo_full", "template": "human-roleplay",
    "expires_at": "Y0001-D011T13:00:00"}, create_new=True)
apply_profile_update("demo_full", {"fields": {"lifetime": "permanent"}})
full = get_character_profile("demo_full") or {}
check("the stamp is untouched", full.get("expires_at"),
      "Y0001-D011T13:00:00")
check("and no NPC flag was invented", full.get("npc_permanent"), None)

# ---------------------------------------------------------------------------
print("\n[14] an unrelated save never restarts a lifetime")

apply_profile_update(ROOK, {"fields": {"standing_task": "sweeping the yard"}})
rook = get_character_profile(ROOK) or {}
check("the stamp survives an ordinary edit", rook.get("expires_at"),
      "Y0001-D011T17:00:00")
check("and the edit itself landed", rook.get("standing_task"),
      "sweeping the yard")

# ---------------------------------------------------------------------------
print("\n[15] the form saves ONE field per request — custom in two calls")

WREN = make_npc("Wren", ttl_hours=1)
apply_profile_update(WREN, {"fields": {"lifetime": "custom"}})
wren = get_character_profile(WREN) or {}
check("call 1 keeps the picked mode", wren.get("lifetime"), "custom")
check("call 1 stamps the default TTL for now", wren.get("expires_at"),
      "Y0001-D011T18:00:00")
apply_profile_update(WREN, {"fields": {"lifetime_hours": 3}})
wren = get_character_profile(WREN) or {}
check("call 2 reads the stored mode and takes the hours",
      wren.get("expires_at"), "Y0001-D011T15:00:00")
check("and the hours are on the profile", wren.get("lifetime_hours"), 3.0)

# ---------------------------------------------------------------------------
print("\n[16] a permanent sheet is not pool stock")

VESPER = make_npc("Vesper", ttl_hours=2)
vesper = get_character_profile(VESPER) or {}
vesper["npc_slot_role"] = "lamplighter"
save_character_profile(VESPER, vesper)
apply_profile_update(VESPER, {"fields": {"lifetime": "permanent"}})
check("pooled", pool_npc(VESPER, reason="smoke"), True)
check("the role stamp survives pooling",
      (get_character_profile(VESPER) or {}).get("npc_slot_role"),
      "lamplighter")
check("a slot spawn does not get it", take_from_pool("lamplighter"), None)
check("and the wanderer spawn's empty role does not either",
      take_from_pool(""), None)

HALDEN = make_npc("Halden", ttl_hours=2)
halden = get_character_profile(HALDEN) or {}
halden["npc_slot_role"] = "lamplighter"
save_character_profile(HALDEN, halden)
check("pooled", pool_npc(HALDEN, reason="smoke"), True)
check("the mortal sheet of the same role is handed out",
      take_from_pool("lamplighter"), HALDEN)
check("and it is what the empty role finds too", take_from_pool(""), HALDEN)

# ---------------------------------------------------------------------------
print("\n[17] a permanent wanderer turns around, it is never pooled")

# The hand-drawn world of the docstring: one ground rectangle and two placed
# 10 m squares. `start_journey` needs passable ground between them, and
# `current_location` is derived from the metre point, so this is the smallest
# fixture an arrival can happen in at all.
INN = add_location("Crossroads Inn", "A stone house at the fork.")["id"]
update_location_position(INN, 0.0, 0.0)
MARKET = add_location("Market Square", "Stalls and shouting.")["id"]
update_location_position(MARKET, 100.0, 0.0)
_world = _load_world_data()
for _loc in _world.get("locations", []):
    if _loc.get("id") in (INN, MARKET):
        _loc["map3d"] = {"plan_width_m": 10.0,
                         "boundary": [[-5.0, -5.0], [5.0, -5.0],
                                      [5.0, 5.0], [-5.0, 5.0]],
                         "boundary_openings": [{"edge": 2, "at": 0.5,
                                                "width_m": 4.0,
                                                "type": "passage"}]}
_save_world_data(_world)
terrain.save_area({"kind": "grass", "z_order": 0,
                   "polygon": [[-60, -60], [300, -60], [300, 300], [-60, 300]]})
config._CONFIG.setdefault("game", {})["travel_speed_m_s"] = 3.0


def arrived_wanderer(name: str, *, origin: str) -> str:
    """A wanderer STANDING at the market, its road behind it, no journey."""
    make_npc(name, ttl_hours=2)
    profile = get_character_profile(name) or {}
    profile.update({"npc_wanderer": True, "wander_target": MARKET,
                    "wander_origin": origin})
    save_character_profile(name, profile)
    set_character_pos(name, 100.0, 0.0)
    return name


_real_random = npc_spawn.random.random
npc_spawn.random.random = lambda: 0.9      # NOT < 0.5 → the coin says "pool"

YARROW = arrived_wanderer("Yarrow", origin=INN)
apply_profile_update(YARROW, {"fields": {"lifetime": "permanent"}})
check("Yarrow has arrived at the market",
      get_character_current_location(YARROW), MARKET)
check("the arrival settles", npc_spawn._settle_wanderer(YARROW), True)
yarrow = get_character_profile(YARROW) or {}
check("the permanent wanderer is NOT pooled",
      get_character_status(YARROW), "")
check("target and origin swapped",
      (yarrow.get("wander_target"), yarrow.get("wander_origin")),
      (INN, MARKET))
check("and it is walking back to the inn",
      (yarrow.get("journey") or {}).get("target"), INN)

THISTLE = arrived_wanderer("Thistle", origin=INN)
check("the mortal one settles too", npc_spawn._settle_wanderer(THISTLE), True)
check("and the very same coin pools it",
      get_character_status(THISTLE), "pooled")

BRAMBLE = arrived_wanderer("Bramble", origin="")
apply_profile_update(BRAMBLE, {"fields": {"lifetime": "permanent"}})
check("with no road back the permanent one settles nothing",
      npc_spawn._settle_wanderer(BRAMBLE), False)
check("but it is still alive", get_character_status(BRAMBLE), "")

CLOVER = arrived_wanderer("Clover", origin="")
check("the mortal sheet in that same state settles",
      npc_spawn._settle_wanderer(CLOVER), True)
check("into the pool", get_character_status(CLOVER), "pooled")

npc_spawn.random.random = _real_random

# ---------------------------------------------------------------------------
print("\n[18] a custom lifetime survives the revive")

MARROW = make_npc("Marrow", ttl_hours=2)
apply_profile_update(MARROW, {"fields": {"lifetime": "custom"}})
apply_profile_update(MARROW, {"fields": {"lifetime_hours": 3}})
check("pooled", pool_npc(MARROW, reason="smoke"), True)
check("revived", revive_from_pool(MARROW, "", ttl_hours=5), True)
check("the revive stamps the sheet's OWN hours, not the caller's TTL",
      (get_character_profile(MARROW) or {}).get("expires_at"),
      "Y0001-D011T15:00:00")
check("and the dropdown still says custom",
      ((get_character_profile(MARROW) or {}).get("lifetime"),
       (get_character_profile(MARROW) or {}).get("lifetime_hours")),
      ("custom", 3.0))

SORREL = make_npc("Sorrel", ttl_hours=2)
_sorrel = get_character_profile(SORREL) or {}
_sorrel.update({"lifetime": "custom", "lifetime_hours": 0})
save_character_profile(SORREL, _sorrel)
check("pooled", pool_npc(SORREL, reason="smoke"), True)
check("revived", revive_from_pool(SORREL, "", ttl_hours=5), True)
check("zero hours are no lifetime — the caller's TTL stands",
      (get_character_profile(SORREL) or {}).get("expires_at"),
      "Y0001-D011T17:00:00")

# ---------------------------------------------------------------------------
print("\n[19] the sweep heals a stale stamp on a mode-only permanent sheet")

PAST = (T0 - GameDuration.of(hours=1)).canonical()
check("the stale stamp is an hour in the past", PAST, "Y0001-D011T11:00:00")
check("and the sweep would read it as expired", is_expired(PAST), True)

EMBER = make_npc("Ember", ttl_hours=2)
_ember = get_character_profile(EMBER) or {}
# The sheet as an OLD profile looks on disk: the admin's dropdown decision,
# and no flag at all — `apply_npc` never writes one, so nothing has to be
# removed here.
_ember.update({"lifetime": "permanent", "expires_at": PAST})
save_character_profile(EMBER, _ember)
check("the sheet carries the mode and no flag",
      (_ember.get("lifetime"), "npc_permanent" in _ember),
      ("permanent", False))

ASH = make_npc("Ash", ttl_hours=2)
_ash = get_character_profile(ASH) or {}
_ash["expires_at"] = PAST
save_character_profile(ASH, _ash)

sweep_expired_npcs()
_ember = get_character_profile(EMBER) or {}
check("the permanent sheet is still alive", get_character_status(EMBER), "")
check("its stale stamp is gone", _ember.get("expires_at"), "")
check("and the derived flag was written onto it",
      _ember.get("npc_permanent"), True)
check("the mortal sheet with the same stamp went into the pool",
      get_character_status(ASH), "pooled")

# ---------------------------------------------------------------------------
print(f"\n{CHECKED - len(FAILURES)}/{CHECKED} checks passed")
if FAILURES:
    print("FAILED: " + ", ".join(FAILURES))
sys.exit(1 if FAILURES else 0)
