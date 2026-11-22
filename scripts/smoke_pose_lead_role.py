#!/usr/bin/env python3
"""The pose catalog field ``lead_role`` (pair scene spec 2026-11-22): which clip
role of a multi-person pose leads the scene. Against a temporary world and a
private copy of the shared catalog only.

Usage: ./.venv/bin/python scripts/smoke_pose_lead_role.py

Fixture. Shared (private copy of the file): ``standing`` (solo, default) and
``duet`` (participants 2, animation "duet"). World layer: ``hug``
(participants 2, animation "hug") and ``trio`` (participants 3, animation
"trio"). The clip role assignment is patched: role_gender of every clip =
{"a": "g1", "b": "g2"} (neutral fixture words).

[1] LOADER. No pose stores a lead role: lead_role_of hug/duet/trio = "a"
    (the first role), standing = "" (a solo pose has no lead), an unknown
    key = "". Stored "C" on trio reads "c"; stored "c" on the pair hug is not
    one of its roles a, b -> "" and lead_role_of falls back to "a"; stored
    "a" on the solo pose reads "".
[2] MIGRATION WITHOUT PROVIDER. No ``pose.lead_role_default`` registered:
    returns 0, nothing stored, lead_role_of hug still "a".
[3] MIGRATION WITH PROVIDER. A fake provider answers "b" for every pose of
    2 and "" for the trio. Asked once per multi-person pose without the
    field: hug, duet, trio = 3 calls, each with roles ROLES[:participants]
    (hug ["a", "b"], trio ["a", "b", "c"]) and the patched role_gender.
    Stored: hug in the WORLD layer, duet in the SHARED file (the store it came
    from), trio nothing (empty answer). Returns 2. lead_role_of hug = duet =
    "b", trio = "a". The shared file gains duet.lead_role and nothing else;
    the world layer gains no duet copy.
    A second run asks only the trio again (1 call: still no field) and
    returns 0. A provider answer outside every pose's roles ("d" — hug
    and trio are asked, neither has a role d) is not stored either (returns 0).
[4] ROUTE. PUT hug lead_role "c" -> 400 (a pair has a, b); PUT hug "a" ->
    stored "a"; PUT hug "" -> the field removed; PUT standing "a" -> 400
    (solo); PUT standing "" -> 200. POST of a 3-person pose with lead_role
    "c" stores "c"; with "d" -> 400; a non-string -> 400. Setting trio2 to
    participants 2 drops a stored "c" (no longer a role); to 1 drops any
    lead_role. GET /poses rows carry lead_role ("" when not stored).
"""
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FAILS = []


def check(label, got, want):
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}: {got!r}" + ("" if ok else f" (want {want!r})"))
    if not ok:
        FAILS.append(label)


def status_of(fn, *args):
    from fastapi import HTTPException
    try:
        fn(*args)
    except HTTPException as e:
        return e.status_code
    return 200


def main():
    with tempfile.TemporaryDirectory() as tmp:
        from app.core import paths
        paths.init(tmp)
        from app.core.db import init_schema
        init_schema()
        from app.core import hooks
        from app.core import pose_catalog as pc
        original = pc.catalog_path
        private = Path(tmp) / "pose_catalog.json"
        shared_doc = {"groups": {
            "stand": {"label": "Stand", "default": "standing", "needs_place": False}},
            "entries": {
                "standing": {"prompt": "standing", "animation": "idle", "group": "stand", "_default": True},
                "duet": {"prompt": "duet", "animation": "duet", "group": "stand",
                         "participants": 2, "places": 2}}}
        private.write_text(json.dumps(shared_doc))
        pc.catalog_path = lambda axis: private if axis == "pose" else original(axis)
        world = {
            "hug": {"prompt": "hug", "animation": "hug", "group": "stand", "participants": 2, "places": 2},
            "trio": {"prompt": "trio", "animation": "trio", "group": "stand", "participants": 3, "places": 3},
        }
        pc.replace_world_entries("pose", world)
        pc.reload_catalogs()
        gender = {"a": "g1", "b": "g2"}
        try:
            with patch("app.core.animation_clips.clip_role_gender", return_value=dict(gender)), \
                    patch("app.core.animation_clips.role_counts", return_value={"hug": 2, "duet": 2, "trio": 3}):
                run(pc, hooks, world, shared_doc, private, gender)
        finally:
            hooks._providers.pop("pose.lead_role_default", None)
            pc.catalog_path = original
            pc.reload_catalogs()

    print('\nFAILED: ' + ', '.join(FAILS) if FAILS else '\nall checks passed')
    return 1 if FAILS else 0


def run(pc, hooks, world, shared_doc, private, gender):
    from app.core.pose_lead_role_migration import migrate_lead_role_once

    print("[1] loader")
    check("defaults", {k: pc.lead_role_of(k) for k in ("hug", "duet", "trio", "standing", "nope")},
          {"hug": "a", "duet": "a", "trio": "a", "standing": "", "nope": ""})
    pc.replace_world_entries("pose", dict(
        world, trio=dict(world["trio"], lead_role="C"), hug=dict(world["hug"], lead_role="c"),
        standing={"prompt": "standing", "animation": "idle", "group": "stand",
                  "_default": True, "lead_role": "a"}))
    pc.reload_catalogs()
    cat = pc.get_catalog("pose")
    check("normalized", {k: cat[k]["lead_role"] for k in ("trio", "hug", "standing")},
          {"trio": "c", "hug": "", "standing": ""})
    check("fallback", (pc.lead_role_of("hug"), pc.lead_role_of("trio"), pc.lead_role_of("standing")),
          ("a", "c", ""))
    pc.replace_world_entries("pose", world)
    pc.reload_catalogs()

    print("[2] migration without provider")
    hooks._providers.pop("pose.lead_role_default", None)
    check("returns", migrate_lead_role_once(), 0)
    check("nothing stored", any("lead_role" in e for e in pc.world_entries("pose").values()), False)
    check("still a", pc.lead_role_of("hug"), "a")

    print("[3] migration with provider")
    calls = []

    def fake(pose_key, roles, role_gender):
        calls.append((pose_key, list(roles), dict(role_gender)))
        return "b" if len(roles) == 2 else ""
    hooks.register_provider("pose.lead_role_default", fake)
    check("returns", migrate_lead_role_once(), 2)
    check("asked", sorted(calls), [("duet", ["a", "b"], gender), ("hug", ["a", "b"], gender),
                                   ("trio", ["a", "b", "c"], gender)])
    check("lead roles", {k: pc.lead_role_of(k) for k in ("hug", "duet", "trio")},
          {"hug": "b", "duet": "b", "trio": "a"})
    rows = pc.world_entries("pose")
    check("world hug", rows["hug"].get("lead_role"), "b")
    check("no world duet", "duet" in rows, False)
    check("trio nothing", "lead_role" in rows["trio"], False)
    on_disk = json.loads(private.read_text())
    want = json.loads(json.dumps(shared_doc))
    want["entries"]["duet"]["lead_role"] = "b"
    check("shared file", on_disk, want)
    calls.clear()
    check("second run", migrate_lead_role_once(), 0)
    check("second run asks", [c[0] for c in calls], ["trio"])
    hooks.register_provider("pose.lead_role_default", lambda pose_key, roles, role_gender: "d")
    pc.replace_world_entries("pose", world)
    pc.reload_catalogs()
    check("invalid answer", migrate_lead_role_once(), 0)
    check("hug unchanged", "lead_role" in pc.world_entries("pose")["hug"], False)
    hooks._providers.pop("pose.lead_role_default", None)

    print("[4] route")
    from app.routes import poses as R
    check("pair c", status_of(R._update_entry_sync, "hug", "pose", {}, {"lead_role": "c"}), 400)
    R._update_entry_sync("hug", "pose", {}, {"lead_role": "a"})
    check("pair a", pc.world_entries("pose")["hug"].get("lead_role"), "a")
    R._update_entry_sync("hug", "pose", {}, {"lead_role": ""})
    check("pair cleared", "lead_role" in pc.world_entries("pose")["hug"], False)
    check("solo a", status_of(R._update_entry_sync, "standing", "pose", {}, {"lead_role": "a"}), 400)
    check("solo empty", status_of(R._update_entry_sync, "standing", "pose", {}, {"lead_role": ""}), 200)
    body = {"axis": "pose", "key": "trio2", "prompt": "trio2", "animation": "trio",
            "group": "stand", "participants": 3, "places": 3, "store": "world"}
    check("create d", status_of(R._create_entry_sync, {}, dict(body, lead_role="d")), 400)
    check("create non-string", status_of(R._create_entry_sync, {}, dict(body, lead_role=2)), 400)
    R._create_entry_sync({}, dict(body, lead_role="c"))
    check("created c", pc.world_entries("pose")["trio2"].get("lead_role"), "c")
    R._update_entry_sync("trio2", "pose", {}, {"participants": 2})
    check("to pair drops c", "lead_role" in pc.world_entries("pose")["trio2"], False)
    R._update_entry_sync("trio2", "pose", {}, {"lead_role": "b"})
    R._update_entry_sync("trio2", "pose", {}, {"participants": 1})
    check("to solo drops", "lead_role" in pc.world_entries("pose")["trio2"], False)
    R._update_entry_sync("hug", "pose", {}, {"lead_role": "b"})
    rows = {r["key"]: r for r in R.list_entries(axis="pose", _={}, set_id="")["entries"]}
    check("rows", (rows["hug"]["lead_role"], rows["trio"]["lead_role"], rows["standing"]["lead_role"]),
          ("b", "", ""))


if __name__ == '__main__':
    sys.exit(main())
