#!/usr/bin/env python3
"""Smoke run for the relationship field the Others panel shows
(`world_ops.relation_summary`, `world_ops.build_relation_map` and
`GET /play/others`).

The checks were split out of the former smoke_play_story_arcs.py unchanged
when the story arc engine left (quest system stage 1, D16): the quest book
has its own smoke now (smoke_play_quests.py).

Runs against a THROWAWAY storage directory — it never touches a real world.

Usage:  ./.venv/bin/python scripts/smoke_play_relations.py

--------------------------------------------------------------------------
Seed (hand-derived):

  Avatar = "Alia", NPC = "Borin"  (alphabetical: Alia sorts first, so the
  relationship row stores character_a="Alia" and sentiment_a_to_b is the
  avatar -> NPC direction).

Expectations, derived by hand from the contract:

  relation_summary("Alia", "Borin") == {"type": "ally", "strength": 42,
                                        "sentiment": 0.75}
      -> type/strength come from update_relationship_manual, sentiment is
         sentiment_self_to_other, i.e. sentiment_a_to_b rounded to 3 digits.
  relation_summary("Alia", "Unbekannt") is None
  relation_summary("", "Borin") is None
  build_relation_map("Alia")["Borin"] == the same dict
  build_relation_map("") == {}

  Orientation flip — "Ada" sorts BEFORE "Alia", so that row stores
  character_a="Ada" and the avatar is the b side. The avatar's own sentiment
  is then sentiment_b_to_a, NOT sentiment_a_to_b:
  relation_summary("Alia", "Ada") == {"type": "rival", "strength": 7,
                                      "sentiment": -0.125}
      -> a_to_b is 0.5 (Ada -> Alia) and must NOT be the emitted value.

Finally the same at the consumer: `/play/others` carries the relation dict
on the present character. Those two characters are created LAST on purpose so
the relation checks run against a world that has no character records at all
— build_relation_map must not depend on the characters existing.
"""
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

STORAGE = Path(tempfile.mkdtemp(prefix="play-relations-smoke-"))

import app  # noqa: E402

assert Path(app.__file__).resolve().is_relative_to(ROOT), f"app imported from {app.__file__}, not {ROOT}"

from app.core import paths  # noqa: E402

paths.init(STORAGE)

from app.core import db  # noqa: E402

db.init_schema()

from app.core.world_ops import build_relation_map, relation_summary  # noqa: E402
from app.models.relationship import (get_relationship,  # noqa: E402
                                     save_relationships,
                                     update_relationship_manual)

AVATAR = "Alia"
NPC = "Borin"
FLIPPED = "Ada"     # sorts BEFORE the avatar -> avatar lands on the b side

FAILURES = []
CHECKED = 0


def check(label: str, actual, expected) -> None:
    global CHECKED
    CHECKED += 1
    ok = actual == expected
    print(f"  {'OK ' if ok else 'FAIL'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


def seed() -> None:
    update_relationship_manual(AVATAR, NPC, rel_type="ally", strength=42)
    rel = get_relationship(AVATAR, NPC)
    # character_a is the alphabetically first name -> Alia -> a_to_b is
    # avatar -> NPC.
    assert rel["character_a"] == AVATAR, rel["character_a"]
    rel["sentiment_a_to_b"] = 0.75
    rel["sentiment_b_to_a"] = -0.25
    save_relationships([rel])

    # Same again with the orientation flipped: "Ada" sorts before "Alia", so
    # character_a is the PARTNER and the avatar's own sentiment sits in
    # sentiment_b_to_a.
    update_relationship_manual(FLIPPED, AVATAR, rel_type="rival", strength=7)
    rel_f = get_relationship(AVATAR, FLIPPED)
    assert rel_f["character_a"] == FLIPPED, rel_f["character_a"]
    rel_f["sentiment_a_to_b"] = 0.5       # Ada -> Alia (must NOT be emitted)
    rel_f["sentiment_b_to_a"] = -0.125    # Alia -> Ada (the avatar's view)
    save_relationships([rel_f])


def main() -> int:
    seed()

    print("relation_summary")
    expected_rel = {"type": "ally", "strength": 42, "sentiment": 0.75}
    check("avatar -> npc", relation_summary(AVATAR, NPC), expected_rel)
    check("unknown partner", relation_summary(AVATAR, "Unbekannt"), None)
    check("no avatar", relation_summary("", NPC), None)
    check("relation map lookup", build_relation_map(AVATAR).get(NPC),
          expected_rel)
    check("relation map without avatar", build_relation_map(""), {})

    expected_flip = {"type": "rival", "strength": 7, "sentiment": -0.125}
    check("flipped orientation (avatar is the b side)",
          relation_summary(AVATAR, FLIPPED), expected_flip)
    check("flipped orientation in the map",
          build_relation_map(AVATAR).get(FLIPPED), expected_flip)

    # --- at the consumer: the route itself -------------------------------
    # Both characters only come into existence HERE — the checks above must
    # run while the world is still empty, because build_memory_relationships
    # drops partners that no longer exist.
    print("routes")
    from app.models.account import set_active_character
    from app.models.character import save_character_profile
    from app.models.world import add_location, list_locations
    from app.routes.play import play_others

    add_location(name="Testhalle", description="Eine leere Halle.",
                 rooms=[{"id": "r1", "name": "Halle"}])
    loc_id = list_locations()[0]["id"]
    for name in (AVATAR, NPC):
        save_character_profile(name, {"name": name,
                                      "current_location": loc_id,
                                      "current_room": "r1"}, create_new=True)
    set_active_character(AVATAR)

    others = play_others(user=None)
    check("others avatar", others.get("avatar"), AVATAR)
    check("others relation", [(c["name"], c.get("relation"))
                              for c in others.get("characters", [])],
          [(NPC, expected_rel)])

    print()
    if FAILURES:
        print(f"FAILED: {len(FAILURES)}/{CHECKED} — {', '.join(FAILURES)}")
        return 1
    print(f"OK: {CHECKED} checks passed")
    return 0


if __name__ == "__main__":
    try:
        code = main()
    finally:
        shutil.rmtree(STORAGE, ignore_errors=True)
    sys.exit(code)
