#!/usr/bin/env python3
"""Smoke: the avatar's open plans for the 3D HUD (``GET /play/intents``).

Usage: ./.venv/bin/python scripts/smoke_play_intents.py

Runs against a throwaway storage dir; no server, no real world.

Hand-derived expectations, game clock fixed at Y0001-D001T09:00:00 (day
index 0), default calendar, 24h clock, avatar "Ann":

  MATCH — owner == "Ann" OR "Ann" is a KEY of participants, nothing else:
    own-*, far, guest-tomorrow (Bob's plan, Ann a participant)  -> listed
    anna     participants {"Anna": {}}           -> NOT listed (prefix)
    role-ann participants {"Cid": {"role": "Ann"}} -> NOT listed; the SQL LIKE
             on the JSON blob does hit it ('"Ann"' is in the text)
    ann-low  participants {"ann": {}}            -> NOT listed; SQLite LIKE is
             case-insensitive and hits it too
    done     status done                         -> NOT listed (not open)

  DESCRIPTION — only for Ann's own plans; guest-tomorrow's "surprise" is "".

  WHEN / SORT KEY (game seconds; now = -1, untimed = None):
    own-now        kind now                 -> "Now",            -1
    own-early      D001 12:30               -> "12:30",          12.5*3600 = 45000
    own-late       D001 18:00               -> "18:00",          18*3600   = 64800
    guest-tomorrow D002 08:00 (day index 1) -> "Tomorrow 08:00", 86400+28800 = 115200
    far            D005 07:00 (day index 4) -> full label,       4*86400+25200 = 370800
    own-standing-1 standing, priority 1     -> "",               None
    own-standing-2 standing, priority 2     -> "",               None

  ORDER: timed ascending by key, then untimed by priority:
    own-now, own-early, own-late, guest-tomorrow, far, own-standing-1,
    own-standing-2

  SPECTATOR: no active character -> {"avatar": "", "intents": []}.

  TOLD TO THE AVATAR (parse_and_apply_intent_markers, told_to="Ann"; owner
  "Cy", who has no other plans — Bob's would trip the active-plan cap):
    Cy writes "[INTENT: Surprise for Ann | a cake | when=standing]" in a
    chat turn with Ann -> Ann becomes a participant (role "told by Cy"),
    so Ann's plan list holds "Surprise for Ann", owner Cy, description "".
    Cy writes "[INTENT: Fishing trip | rods | when=standing]" with told_to=""
    -> participants {"Cy"} only, not in Ann's list.
    told_to == the owner ("Cy") adds nobody besides Cy.
"""
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("PASS " if ok else "FAIL ") + label + ("" if ok else f": got {got!r}, want {want!r}"))
    if not ok:
        FAILS.append(label)


def main():
    with tempfile.TemporaryDirectory(prefix="play-intents-") as tmp:
        from app.core import paths
        paths.init(Path(tmp))
        paths.init_instance(Path(tmp) / "instance")
        from app.core import config, db
        config.load(Path(tmp) / "config.json")
        db.init_schema()
        from app.models import intents
        from app.core.game_time import GameTime
        fixed = GameTime.parse("Y0001-D001T09:00:00")

        def at(stamp):
            return {"kind": "at_time", "run_date": stamp}

        rows = [
            ("own-late", "Ann", {}, at("Y0001-D001T18:00:00"), 3, "active"),
            ("own-early", "Ann", {}, at("Y0001-D001T12:30:00"), 4, "active"),
            ("guest-tomorrow", "Bob", {"Ann": {"role": "guest"}}, at("Y0001-D002T08:00:00"), 3, "active"),
            ("own-standing-2", "Ann", {}, {"kind": "standing"}, 2, "active"),
            ("own-standing-1", "Ann", {}, {"kind": "standing"}, 1, "active"),
            ("own-now", "Ann", {}, {"kind": "now"}, 5, "active"),
            ("far", "Ann", {}, at("Y0001-D005T07:00:00"), 3, "active"),
            ("anna", "Bob", {"Anna": {}}, {"kind": "standing"}, 3, "active"),
            ("role-ann", "Bob", {"Cid": {"role": "Ann"}}, {"kind": "standing"}, 3, "active"),
            ("ann-low", "Bob", {"ann": {}}, {"kind": "standing"}, 3, "active"),
            ("done", "Ann", {}, {"kind": "standing"}, 3, "done"),
        ]
        for iid, owner, parts, trig, prio, status in rows:
            intents.create_intent(intent_id=iid, owner=owner, title=iid,
                                  description=f"secret of {iid}", participants=parts,
                                  trigger=trig, priority=prio, status=status)

        raw = {it["id"] for it in intents.list_intents(owner="Ann", status="active")}
        check("LIKE pre-filter hits role-ann (why the exact match exists)",
              "role-ann" in raw, True)

        with patch.object(intents, "game_time", return_value=fixed):
            plans = intents.player_plans("Ann", "en")
        by_id = {p["id"]: p for p in plans}

        check("order", [p["id"] for p in plans],
              ["own-now", "own-early", "own-late", "guest-tomorrow", "far",
               "own-standing-1", "own-standing-2"])
        for excluded in ("anna", "role-ann", "ann-low", "done"):
            check(f"{excluded} not listed", excluded in by_id, False)
        check("guest description hidden", by_id["guest-tomorrow"]["description"], "")
        check("guest own flag", by_id["guest-tomorrow"]["own"], False)
        check("guest owner", by_id["guest-tomorrow"]["owner"], "Bob")
        check("own description shown", by_id["own-late"]["description"], "secret of own-late")
        expected = {
            "own-now": ("Now", -1), "own-early": ("12:30", 45000),
            "own-late": ("18:00", 64800), "guest-tomorrow": ("Tomorrow 08:00", 115200),
            "own-standing-1": ("", None), "own-standing-2": ("", None),
        }
        for iid, (label, key) in expected.items():
            check(f"{iid} when", by_id[iid]["when"], label)
            check(f"{iid} sort_key", by_id[iid]["sort_key"], key)
        far = by_id["far"]
        check("far sort_key", far["sort_key"], 370800)
        check("far label is a full date with the clock",
              "07:00" in far["when"] and far["when"] != "07:00"
              and not far["when"].startswith("Tomorrow"), True)

        told = intents.parse_and_apply_intent_markers(
            "Cy", "[INTENT: Surprise for Ann | a cake | when=standing]", told_to="Ann")
        quiet = intents.parse_and_apply_intent_markers(
            "Cy", "[INTENT: Fishing trip | rods | when=standing]")
        selfish = intents.parse_and_apply_intent_markers(
            "Cy", "[INTENT: Mend the net | twine | when=standing]", told_to="Cy")
        check("told_to: participants", sorted((told[0].get("participants") or {})), ["Ann", "Cy"])
        check("told_to: role", told[0]["participants"]["Ann"]["role"], "told by Cy")
        check("no told_to: participants", sorted((quiet[0].get("participants") or {})), ["Cy"])
        check("told_to owner: participants", sorted((selfish[0].get("participants") or {})), ["Cy"])
        with patch.object(intents, "game_time", return_value=fixed):
            listed = {p["title"]: p for p in intents.player_plans("Ann", "en")}
        check("told plan listed for Ann", "Surprise for Ann" in listed, True)
        check("told plan description hidden", listed.get("Surprise for Ann", {}).get("description"), "")
        check("quiet plan not listed for Ann", "Fishing trip" in listed, False)

        from app.routes import play
        with patch("app.models.account.get_active_character", return_value=""):
            check("spectator gets nothing", play.play_intents(user={}),
                  {"avatar": "", "intents": []})

    if FAILS:
        print(f"\n{len(FAILS)} check(s) failed")
        sys.exit(1)
    print("\nall checks passed")


if __name__ == "__main__":
    main()
