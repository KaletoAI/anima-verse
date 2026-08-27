"""Smoke: the recycling pool has its OWN size (spec-npc-heimat-zeitfenster § E1).

The pool used to be the living cap in disguise — ``max_pool_size()`` returned
``npc_spawn.max_alive()``, so a world that keeps 10 NPCs alive could keep only
10 sheets in stock. The two numbers answer different questions: the living cap
is "how crowded is the world", the pool size is "how much finished work do I
keep for re-use". This run proves they are separate.

Hand-derived expectations:

  [1] With NO ``npc`` section in the config at all (a fresh throwaway world is
      loaded from a config.json that does not exist, so ``config.get`` finds
      nothing), ``max_pool_size()`` is the schema default 50 and
      ``max_alive()`` is its own schema default 10. 50 != 10 is the whole
      point of the change: before E1 both answers were 10.

  [2] ``max_pool_size=2`` with ``max_alive=10``: three temporary NPCs are
      pooled one after the other. ``pool_npc`` enforces the cap on every way
      in, so the pool holds 1, then 2, then — on the third — 2 again, with the
      LONGEST-pooled sheet deleted for good. The FIFO order is
      ``list_pooled_characters()`` (``ORDER BY updated_at ASC, name ASC``);
      the three names are chosen in alphabetical order so the tiebreak inside
      one clock second gives the same order as the pooling did. So after the
      third pooling: pool == [demo_pool_b, demo_pool_c] and demo_pool_a is
      gone from the world (``delete_character`` swept the row). "Gone" is
      asked at the ROSTER, not at ``get_character_profile`` — that one answers
      an empty skeleton dict for a name it does not know, so it can never
      prove a deletion.

  [3] The living cap is untouched by all of this: ``max_alive()`` still
      answers 10 and ``cap_reached()`` stays False — the three NPCs are in
      the pool, so 0 of 10 seats are taken. A pool of 2 does not shrink the
      world to 2 living NPCs.

  [4] A PERMANENT sheet is invisible to the cap, in both directions
      (plan-npc-leben-bugs task 2). ``take_from_pool`` skips ``npc_permanent``
      sheets, so no spawn will ever claim one again — and since the pool is
      oldest-first, an untouched permanent sheet would sit at the very FRONT
      of the deletion queue and be the first thing an overflow deletes for
      good. The cap counts MORTAL sheets only:

        starting from [2]'s pool [demo_pool_b, demo_pool_c] and cap 2,
        pooling the permanent demo_pool_keep gives THREE rows and deletes
        nothing — there are still only two mortal sheets;
        pooling the mortal demo_pool_d then makes three mortal ones, so the
        oldest MORTAL (demo_pool_b) goes and demo_pool_keep stays.

      Result: the pool is {demo_pool_c, demo_pool_d, demo_pool_keep} and
      demo_pool_keep is still on the Game-Admin pool list (``list_pool``),
      which is where an admin finds it at all.

  [5] AND THE LIST SAYS SO. A pooled sheet that no spawn will ever draw and
      that no cap will ever drop looks exactly like every other row unless the
      payload carries the state, so ``list_pool`` ships ``permanent`` per row
      and ``GET /npc/list`` ships ``limits.pool_used`` — the MORTAL count, the
      only one the cap measures. Straight off [4]'s state, cap 2:

        rows            demo_pool_c False, demo_pool_d False,
                        demo_pool_keep True
        limits.pool_used  2   (three rows, one of them permanent)
        limits.pool_size  2

      so the header reads "2/2" — full, and honestly so. Counting the rows
      instead would say "3/2", a pool over its own cap that will never shrink.

  [6] THE MODE IS THE DECISION, THE FLAG IS DERIVED FROM IT. ``npc_permanent``
      is younger than the ``lifetime`` dropdown, so a sheet made permanent
      before the flag existed (or imported from a pack that only knows the
      mode) carries ``lifetime "permanent"`` and NO flag. Every reader asks
      ``npc_ops.is_permanent_npc``, which accepts either, so such a sheet is
      kept exactly like a flagged one. Straight off [4]/[5]'s state — pool
      [demo_pool_c, demo_pool_d, demo_pool_keep], two mortal sheets, cap 2:

        pooling the mode-only demo_pool_mode gives FOUR rows and deletes
        nothing — there are still only two mortal sheets, so the cap
        (``_enforce_pool_cap``) never fires;
        pooling the mortal demo_pool_lamp then makes three mortal ones, so
        the oldest MORTAL (demo_pool_c) goes;
        both of those carry the slot role "lamplighter", and the mode-only
        one is the OLDER of the two — so ``take_from_pool("lamplighter")``
        answering demo_pool_lamp proves both halves at once: the role match
        works, and the mode-only sheet was stepped over.

      Result: the pool is [demo_pool_d, demo_pool_keep, demo_pool_mode,
      demo_pool_lamp] and the list row for demo_pool_mode says
      ``permanent True``.

  [7] A REVIVE HEALS THE MISSING FLAG INSTEAD OF RESTAMPING THE NPC. This is
      the path the bug ran through: ``revive_from_pool`` read the flag alone,
      found none, and handed the kept sheet a fresh TTL — the sweeper then
      read a real stamp and the admin list showed "expires in …" next to
      "permanent". With the cap out of the way (``max_pool_size=10``) and the
      asset gate off (``require_assets=False``, so the revive is not held
      back for a portrait this throwaway world will never render):

        revive(demo_pool_mode, ttl=3)   expires_at ""   npc_permanent True
        revive(demo_pool_plain, ttl=3)  expires_at = expiry_stamp(3), i.e.
                                        remaining_span (3.0, "3h")

      The first line is the fix (no stamp, and the flag written onto the sheet
      as part of the same save); the second is the unchanged normal case — a
      sheet with neither mode nor flag is stamped with the caller's TTL, which
      3 game hours from now reads as (3.0, "3h") exactly as in
      ``smoke_npc_ttl``.

Usage:  ./.venv/bin/python scripts/smoke_npc_pool_size.py
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="npcpool-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="npcpool-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import config, db  # noqa: E402
config.load(STORAGE / "config.json")
db.init_schema()

from app.core import npc_spawn  # noqa: E402
from app.core.npc_ops import remaining_span  # noqa: E402
from app.core.npc_pool import (list_pool, max_pool_size,  # noqa: E402
                               pool_npc, revive_from_pool, take_from_pool)
from app.core.task_queue import get_task_queue  # noqa: E402
from app.models.character import (get_character_profile,  # noqa: E402
                                  list_available_characters,
                                  list_pooled_characters,
                                  save_character_profile)

# No worker threads in a smoke — nothing here submits a task, but the pool
# would auto-start on the first one.
get_task_queue()._started = True

FAILURES = []
CHECKED = 0


def check(label, actual, expected):
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'OK  ' if ok else 'FAIL'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


def set_npc_config(**values) -> None:
    cfg = config.get_all()
    cfg.setdefault("npc", {}).update(values)
    config.save(cfg, STORAGE / "config.json")


def make_npc(name: str, permanent: bool = False, role: str = "") -> str:
    """A living temporary NPC, the way the apply path leaves one."""
    save_character_profile(name, {
        "character_name": name, "template": "npc-temporary",
        "character_personality": "Dry, economical with words.",
        "standing_task": "tends the bar",
        "outfit_description": "grey linen apron",
        "expires_at": "",
        "npc_permanent": permanent,
        "npc_slot_role": role,
    }, create_new=True)
    return name


def make_mode_only_npc(name: str, role: str = "") -> str:
    """A sheet made permanent BEFORE ``npc_permanent`` existed: mode, no flag.

    The key is absent, not False — that is exactly what an old profile (or a
    content-pack import that only knows the dropdown) looks like on disk.
    """
    save_character_profile(name, {
        "character_name": name, "template": "npc-temporary",
        "character_personality": "Dry, economical with words.",
        "standing_task": "lights the lamps",
        "outfit_description": "grey linen apron",
        "expires_at": "",
        "lifetime": "permanent",
        "npc_slot_role": role,
    }, create_new=True)
    return name


# ---------------------------------------------------------------------------
print("[1] Without any config the pool has its own default")
check("no npc section in this world", config.get("npc.max_pool_size", None), None)
check("the pool default is 50", max_pool_size(), 50)
check("the living cap keeps its own default 10", npc_spawn.max_alive(), 10)

# ---------------------------------------------------------------------------
print("\n[2] A pool of 2 drops the longest-pooled sheet")
set_npc_config(max_pool_size=2, max_alive=10)
check("the configured pool size is read", max_pool_size(), 2)

A, B, C = (make_npc("demo_pool_a"), make_npc("demo_pool_b"),
           make_npc("demo_pool_c"))

check("first in", (pool_npc(A, reason="smoke"), list_pooled_characters()),
      (True, [A]))
check("second in", (pool_npc(B, reason="smoke"), list_pooled_characters()),
      (True, [A, B]))
check("third in, oldest out",
      (pool_npc(C, reason="smoke"), list_pooled_characters()), (True, [B, C]))
check("the dropped sheet is gone for good, the other two are still there",
      sorted(list_available_characters(include_pooled=True)), [B, C])

# ---------------------------------------------------------------------------
print("\n[3] The living cap is unaffected")
check("max_alive is still 10", npc_spawn.max_alive(), 10)
check("nothing living, so the cap is not reached", npc_spawn.cap_reached(), False)
check("…and the count agrees", npc_spawn.alive_npc_count(), 0)

# ---------------------------------------------------------------------------
print("\n[4] A permanent sheet neither counts nor gets deleted")

KEEP = make_npc("demo_pool_keep", permanent=True)
check("the permanent sheet goes in", pool_npc(KEEP, reason="smoke"), True)
check("three rows, and nothing was dropped for a cap of 2",
      sorted(list_pooled_characters()), [B, C, KEEP])

D = make_npc("demo_pool_d")
check("a third MORTAL sheet goes in", pool_npc(D, reason="smoke"), True)
check("the oldest MORTAL went, the permanent one stayed",
      sorted(list_pooled_characters()), [C, D, KEEP])
check("and it really is gone from the world",
      sorted(list_available_characters(include_pooled=True)), [C, D, KEEP])
check("the Game-Admin pool list still shows the kept sheet",
      KEEP in [r["name"] for r in list_pool()], True)
check("but no spawn can claim it", take_from_pool(""), C)

# ---------------------------------------------------------------------------
print("\n[5] The pool list says which sheet is kept, and counts the mortal ones")

from app.routes.npc import list_npcs_route  # noqa: E402

check("every row carries the state",
      sorted((r["name"], r["permanent"]) for r in list_pool()),
      [(C, False), (D, False), (KEEP, True)])
_limits = list_npcs_route()["limits"]
check("the counter beside the size skips the kept sheet",
      (_limits["pool_used"], _limits["pool_size"]), (2, 2))

# ---------------------------------------------------------------------------
print("\n[6] A sheet whose lifetime says permanent is kept without the flag")

MODE = make_mode_only_npc("demo_pool_mode", role="lamplighter")
check("the sheet really carries the mode and NO flag",
      (get_character_profile(MODE).get("lifetime"),
       "npc_permanent" in get_character_profile(MODE)),
      ("permanent", False))
check("the mode-only sheet goes in", pool_npc(MODE, reason="smoke"), True)
check("four rows, and nothing was dropped for a cap of 2",
      sorted(list_pooled_characters()), sorted([C, D, KEEP, MODE]))

LAMP = make_npc("demo_pool_lamp", role="lamplighter")
check("a third MORTAL sheet goes in", pool_npc(LAMP, reason="smoke"), True)
check("the oldest MORTAL went, the mode-only one stayed",
      sorted(list_pooled_characters()), sorted([D, KEEP, MODE, LAMP]))
check("the draw for that role steps over the older mode-only sheet",
      take_from_pool("lamplighter"), LAMP)
check("and the list row says it is kept",
      [r["permanent"] for r in list_pool() if r["name"] == MODE], [True])

# ---------------------------------------------------------------------------
print("\n[7] A revive heals the missing flag instead of restamping the NPC")
# Cap out of the way (nothing more may be deleted) and the asset gate off —
# this throwaway world renders no portraits, so an armed gate would hold every
# revive back before the placement.
set_npc_config(max_pool_size=10, require_assets=False)

check("the mode-only sheet is revived",
      revive_from_pool(MODE, "", ttl_hours=3), True)
_mode = get_character_profile(MODE)
check("no new TTL was stamped on it", _mode.get("expires_at"), "")
check("and the derived flag was written onto the sheet",
      _mode.get("npc_permanent"), True)

PLAIN = make_npc("demo_pool_plain")
check("a sheet with neither mode nor flag goes in",
      pool_npc(PLAIN, reason="smoke"), True)
check("…is revived", revive_from_pool(PLAIN, "", ttl_hours=3), True)
check("…and is stamped with the caller's TTL as before",
      remaining_span(get_character_profile(PLAIN).get("expires_at") or ""),
      (3.0, "3h"))

print(f"\n{CHECKED} checks, {len(FAILURES)} failed")
if FAILURES:
    print("FAILED: " + ", ".join(FAILURES))
    sys.exit(1)
print("all green")
