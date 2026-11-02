#!/usr/bin/env python3
"""The interaction blob names its MEMBERS (plan-gruppen-animationen.md G2b):
``interaction.members`` ``{role: name}`` replaces ``interaction.partner``.
Against a temporary world only.

Usage: ./.venv/bin/python scripts/smoke_interaction_members.py

Fixture: Ann, Bob, Cid, Dee as plain characters.
[1] MIGRATION. Ann holds the old blob {role "a", partner "Bob"}, Bob
    {role "b", partner "Ann"}; Cid holds only an old
    last_interaction_result {partner "Dee"}; Dee holds nothing.
    migrate_members_once() -> 3 (Ann, Bob, Cid). Ann's blob: members
    {a: Ann, b: Bob}, no partner; Bob's: members {a: Ann, b: Bob} (his
    own role b plus the other half a); Cid's result is gone; Dee untouched.
    A second run -> 0.
[2] READING. get_interaction(Ann) is the blob; others_of(Ann) ["Bob"],
    partner_of(Bob) "Ann", describe(Ann) "x with Bob"; a blob whose
    members do not name the character at its own role reads as None
    (Cid with {role a, members {a: Dee, b: Cid}}), so does one with a
    single member. join_names: [] "", [A] "A", [A, B] "A and B",
    [A, B, C] "A, B and C".
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FAILS = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: {got!r}" + ("" if ok else f" (want {want!r})"))
    if not ok:
        FAILS.append(label)


def main():
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["STORAGE_DIR"] = tmp
        from app.core import paths
        paths.init(tmp)
        from app.core.db import init_schema
        init_schema()
        from app.core import interaction_engine as IE
        from app.models.character import get_character_profile, save_character_profile

        def profile(name, **fields):
            save_character_profile(name, {"template": "human-default", **fields}, create_new=True)

        stamp = "Y0001-D001T00:00:00"
        base = {"id": "x1", "kind": "hug", "pose_key": "x", "started_at_game": stamp}
        profile("Ann", interaction=dict(base, role="a", partner="Bob"))
        profile("Bob", interaction=dict(base, role="b", partner="Ann"))
        profile("Cid", last_interaction_result={"interaction_id": "old", "partner": "Dee"})
        profile("Dee")
        dee_before = get_character_profile("Dee")

        print("[1] migration")
        check("rewritten", IE.migrate_members_once(), 3)
        ann = get_character_profile("Ann")["interaction"]
        bob = get_character_profile("Bob")["interaction"]
        check("Ann members", (ann.get("members"), "partner" in ann), ({"a": "Ann", "b": "Bob"}, False))
        check("Bob members", (bob.get("members"), "partner" in bob), ({"a": "Ann", "b": "Bob"}, False))
        check("old result dropped", "last_interaction_result" in get_character_profile("Cid"), False)
        check("Dee untouched", get_character_profile("Dee"), dee_before)
        check("second run", IE.migrate_members_once(), 0)

        print("[2] reading")
        check("get_interaction", (IE.get_interaction("Ann") or {}).get("id"), "x1")
        check("others_of", IE.others_of(IE.get_interaction("Ann"), "Ann"), ["Bob"])
        check("partner_of", IE.partner_of(IE.get_interaction("Bob"), "Bob"), "Ann")
        check("describe", IE.describe("Ann"), "x with Bob")
        cid = get_character_profile("Cid")
        cid["interaction"] = dict(base, role="a", members={"a": "Dee", "b": "Cid"})
        save_character_profile("Cid", cid)
        check("wrong own role", IE.get_interaction("Cid"), None)
        cid["interaction"] = dict(base, role="a", members={"a": "Cid"})
        save_character_profile("Cid", cid)
        check("single member", IE.get_interaction("Cid"), None)
        check("join_names", [IE.join_names(n) for n in ([], ["A"], ["A", "B"], ["A", "B", "C"])],
              ["", "A", "A and B", "A, B and C"])

    print('\nFAILED: ' + ', '.join(FAILS) if FAILS else '\nall checks passed')
    return 1 if FAILS else 0


if __name__ == '__main__':
    sys.exit(main())
