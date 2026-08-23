#!/usr/bin/env python3
"""Smoke run for the player quest book (`GET /play/story-arcs`) and the
relationship field the Others panel shows.

Runs against a THROWAWAY storage directory — it never touches a real world.

Usage:  ./.venv/bin/python scripts/smoke_play_story_arcs.py

--------------------------------------------------------------------------
Seed (hand-derived, all timestamps forced so the ordering is deterministic —
`utc_now_iso` only has second resolution, so arcs written in the same second
would otherwise tie):

  Avatar = "Alia", NPC = "Borin"  (alphabetical: Alia sorts first, so the
  relationship row stores character_a="Alia" and sentiment_a_to_b is the
  avatar -> NPC direction).

  Arc X   active,   participants [Alia, Borin], updated_at 2026-08-05T10:00
          one beat, seed + next_beat_hint set
  Arc X2  active,   participants [Alia],        updated_at 2026-08-05T12:00
  Arc Y   active,   participants [Borin, Cara], updated_at 2026-08-05T14:00
  Arc Z01..Z12  resolved, participants [Alia, Borin],
          updated_at 2026-08-01T00:00 + i hours (i = 1..12),
          resolution "Ende <i>", Z01 also carries character_outcomes +
          sequel_seed.

Expectations, derived by hand from the contract:

  build_player_story_arcs("Alia")["arcs"]:
    - Y is absent (Alia is not a participant)
    - active first, by updated_at DESCENDING  -> [X2 (12:00), X (10:00)]
    - then AT MOST 10 resolved, by updated_at DESCENDING
      -> Z12, Z11, Z10, Z09, Z08, Z07, Z06, Z05, Z04, Z03
      (Z02 and Z01 fall off the cap)
    - so the id list is exactly:
      [X2, X, Z12, Z11, Z10, Z09, Z08, Z07, Z06, Z05, Z04, Z03]  (12 entries)
    - X carries id/title/status/current_state/tension/beats/participants/
      updated_at and NO "resolution"
    - X["beats"][0] has exactly the keys {beat, timestamp, summary}
    - Z12 carries "resolution" == "Ende 12"
    - NO entry carries seed / next_beat_hint / character_outcomes /
      sequel_seed  (the spoiler block list)

  build_player_story_arcs("") == {"arcs": []}     (no avatar)
  build_player_story_arcs("Dorn")["arcs"] == []   (participant of nothing;
      Cara would NOT do — she is a participant of arc Y)

  relation_summary("Alia", "Borin") == {"type": "ally", "strength": 42,
                                        "sentiment": 0.75}
      -> type/strength come from update_relationship_manual, sentiment is
         sentiment_self_to_other, i.e. sentiment_a_to_b rounded to 3 digits.
  relation_summary("Alia", "Unbekannt") is None
  relation_summary("", "Borin") is None
  build_relation_map("Alia")["Borin"] == the same dict

  Orientation flip — "Ada" sorts BEFORE "Alia", so that row stores
  character_a="Ada" and the avatar is the b side. The avatar's own sentiment
  is then sentiment_b_to_a, NOT sentiment_a_to_b:
  relation_summary("Alia", "Ada") == {"type": "rival", "strength": 7,
                                      "sentiment": -0.125}
      -> a_to_b is 0.5 (Ada -> Alia) and must NOT be the emitted value.

Finally the same at the consumer: `/play/story-arcs` is registered, the route
returns the same id list, and `/play/others` carries the relation dict on the
present character. Those two characters are created LAST on purpose so the
relation checks run against a world that has no character records at all —
build_relation_map must not depend on the characters existing.
"""
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="play-story-arcs-smoke-"))

from app.core import paths  # noqa: E402

paths.init(STORAGE)

from app.core import db  # noqa: E402

db.init_schema()

from app.core.world_ops import build_player_story_arcs  # noqa: E402
from app.core.world_ops import build_relation_map, relation_summary  # noqa: E402
from app.models import story_arcs as sa  # noqa: E402
from app.models.relationship import (get_relationship,  # noqa: E402
                                     save_relationships,
                                     update_relationship_manual)

AVATAR = "Alia"
NPC = "Borin"
OTHER = "Cara"      # participant of arc Y
STRANGER = "Dorn"   # participant of nothing
FLIPPED = "Ada"     # sorts BEFORE the avatar -> avatar lands on the b side

SPOILERS = ("seed", "next_beat_hint", "character_outcomes", "sequel_seed")

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


def set_updated_at(arc_id: str, stamp: str) -> None:
    """Force an arc's updated_at through the model's own persistence path."""
    data = sa._load()
    for arc in data["arcs"]:
        if arc["id"] == arc_id:
            arc["updated_at"] = stamp
    sa._save(data)


def seed() -> dict:
    ids = {}

    arc_x = sa.create_arc("Der verlorene Ring", [AVATAR, NPC],
                          seed="Ein Ring verschwindet.", tension=3,
                          first_beat_hint="Spuren im Schnee", max_beats=5)
    sa.advance_arc(arc_x["id"], beat_summary="Alia findet eine Spur.",
                   new_state="Die Spur fuehrt nach Norden.", tension=3,
                   next_beat_hint="Der Haendler luegt")
    set_updated_at(arc_x["id"], "2026-08-05T10:00:00+00:00")
    ids["X"] = arc_x["id"]

    arc_x2 = sa.create_arc("Allein unterwegs", [AVATAR],
                           seed="Alia zieht los.", tension=1)
    set_updated_at(arc_x2["id"], "2026-08-05T12:00:00+00:00")
    ids["X2"] = arc_x2["id"]

    arc_y = sa.create_arc("Ohne die Spielerin", [NPC, OTHER],
                          seed="Borin und Cara streiten.", tension=2)
    set_updated_at(arc_y["id"], "2026-08-05T14:00:00+00:00")
    ids["Y"] = arc_y["id"]

    for i in range(1, 13):
        arc = sa.create_arc(f"Abgeschlossen {i}", [AVATAR, NPC],
                            seed=f"Anfang {i}", tension=2)
        if i == 1:
            sa.resolve_arc(arc["id"], resolution=f"Ende {i}",
                           character_outcomes={AVATAR: "klueger"},
                           sequel_seed="Es geht weiter")
        else:
            sa.resolve_arc(arc["id"], resolution=f"Ende {i}")
        set_updated_at(arc["id"], f"2026-08-01T{i:02d}:00:00+00:00")
        ids[f"Z{i:02d}"] = arc["id"]

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
    return ids


def main() -> int:
    ids = seed()

    print("build_player_story_arcs(avatar)")
    payload = build_player_story_arcs(AVATAR)
    arcs = payload.get("arcs", [])
    expected_order = [ids["X2"], ids["X"]] + [ids[f"Z{i:02d}"]
                                              for i in range(12, 2, -1)]
    check("arc id order", [a.get("id") for a in arcs], expected_order)
    check("arc count", len(arcs), 12)
    check("arc Y excluded", ids["Y"] in [a.get("id") for a in arcs], False)

    by_id = {a.get("id"): a for a in arcs}
    x = by_id.get(ids["X"], {})
    check("X title", x.get("title"), "Der verlorene Ring")
    check("X status", x.get("status"), "active")
    check("X current_state", x.get("current_state"),
          "Die Spur fuehrt nach Norden.")
    check("X tension", x.get("tension"), 3)
    check("X participants", x.get("participants"), [AVATAR, NPC])
    check("X updated_at", x.get("updated_at"), "2026-08-05T10:00:00+00:00")
    check("X has no resolution", "resolution" in x, False)
    check("X beat keys", sorted(x.get("beats", [{}])[0].keys()),
          ["beat", "summary", "timestamp"])
    check("X beat number", x.get("beats", [{}])[0].get("beat"), 1)

    z12 = by_id.get(ids["Z12"], {})
    check("Z12 status", z12.get("status"), "resolved")
    check("Z12 resolution", z12.get("resolution"), "Ende 12")

    print("spoiler block list")
    leaked = sorted({key for arc in arcs for key in SPOILERS if key in arc})
    check("no spoiler keys anywhere", leaked, [])
    # Z01 (which carries character_outcomes + sequel_seed) is beyond the cap,
    # so check the block list against the raw arc too.
    raw_ids = {a["id"] for a in sa.get_all_arcs()}
    check("seeded arcs still complete in the model", len(raw_ids), 15)

    print("edge cases")
    check("no avatar", build_player_story_arcs(""), {"arcs": []})
    check("stranger has no arcs", build_player_story_arcs(STRANGER)["arcs"], [])

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

    # --- at the consumer: the routes themselves -------------------------
    # Both characters only come into existence HERE — the checks above must
    # run while the world is still empty, because build_memory_relationships
    # drops partners that no longer exist.
    print("routes")
    from app.models.account import set_active_character
    from app.models.character import save_character_profile
    from app.models.world import add_location, list_locations
    from app.routes.play import play_others, play_story_arcs, router

    check("story-arcs route registered",
          "/play/story-arcs" in {r.path for r in router.routes}, True)

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

    route_arcs = play_story_arcs(user=None)
    check("route arc ids", [a["id"] for a in route_arcs["arcs"]],
          expected_order)

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
