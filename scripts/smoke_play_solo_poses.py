#!/usr/bin/env python3
"""The "Independent actions" of the chat's action tree: ``GET /play/solo-poses``
(``play.solo_poses_payload``) and the clicked pose ``{"pose_key"}`` on
``POST /play/self/activity`` (``play._play_set_activity_sync``).

Usage: ./.venv/bin/python scripts/smoke_play_solo_poses.py

Against a temporary world and a PRIVATE copy of the pose catalog only (the
tracked shared file is never read or written); no server.

Fixture — place types: stand (needs no place, default "standing"),
ground (needs no place, default "kneeling"), seat (needs a place,
default "sitting"). Poses:
  standing  stand   label "Standing", label_de "Aufrecht stehen"
  kneeling  ground  label "Kneeling", label_de "Knien"
  waving    stand   no label at all  -> pose_label falls back to the key
  sitting   seat    label "Sitting"  -> needs a place: NOT listed
  hug       stand   participants 2   -> a pair: NOT listed
  circle    stand   participants 3   -> a group: NOT listed
  swimming  stand   movement-only (movement.MOVEMENT_ONLY_POSES): NOT listed

Hand-derived:
  [1] avatar "Ann", language en -> labels Kneeling, Standing, waving;
      casefolded label order: kneeling, standing, waving.
  [2] language de -> Aufrecht stehen (standing), Knien (kneeling), waving
      (no label_de, no label -> the key); order standing, kneeling, waving —
      a different order than [1], so the list is sorted by LABEL, not by
      catalog or key order.
  [3] spectator (no active character) -> {"avatar": "", "poses": []}.
  [4] pose_key "nope" -> 400; "hug" -> 409 pair_pose, "circle" -> 409
      pair_pose — neither reaches the setter. " WAVING " -> the setter is
      called once with ("Ann", "waving"), answer activity "waving". The
      setter answering False (no free place) -> 409 no_free_place.
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


def refusal(fn, *args):
    """(status, detail) of an HTTPException, (200, None) without one."""
    from fastapi import HTTPException
    try:
        fn(*args)
    except HTTPException as e:
        return e.status_code, e.detail
    return 200, None


def main():
    with tempfile.TemporaryDirectory(prefix="solo-poses-") as tmp:
        from app.core import paths
        paths.init(tmp)
        from app.core.db import init_schema
        init_schema()
        from app.core import pose_catalog as pc
        original = pc.catalog_path
        private = Path(tmp) / "pose_catalog.json"
        private.write_text(json.dumps({
            "groups": {
                "stand": {"label": "Stand", "default": "standing", "needs_place": False},
                "ground": {"label": "Ground", "default": "kneeling", "needs_place": False},
                "seat": {"label": "Seat", "default": "sitting", "needs_place": True}},
            "entries": {
                "standing": {"prompt": "standing", "animation": "idle", "group": "stand",
                             "_default": True, "label": "Standing", "label_de": "Aufrecht stehen"},
                "kneeling": {"prompt": "kneeling", "animation": "kneel", "group": "ground",
                             "label": "Kneeling", "label_de": "Knien"},
                "waving": {"prompt": "waving", "animation": "wave", "group": "stand"},
                "sitting": {"prompt": "sitting", "animation": "sit", "group": "seat",
                            "label": "Sitting"},
                "hug": {"prompt": "hug", "animation": "hug", "group": "stand",
                        "participants": 2, "places": 2},
                "circle": {"prompt": "circle", "animation": "circle", "group": "stand",
                           "participants": 3, "places": 3},
                "swimming": {"prompt": "swimming", "animation": "swim", "group": "stand"},
            }}))
        pc.catalog_path = lambda axis: private if axis == "pose" else original(axis)
        pc.reload_catalogs()
        from app.routes import play

        lang = {"value": "en"}
        active = {"value": "Ann"}
        with patch("app.models.account.get_active_character", lambda: active["value"]), \
                patch("app.models.character.get_character_language",
                      lambda name, **_: lang["value"]):
            print("[1] english")
            check("en", play.solo_poses_payload(), {"avatar": "Ann", "poses": [
                {"key": "kneeling", "label": "Kneeling"},
                {"key": "standing", "label": "Standing"},
                {"key": "waving", "label": "waving"}]})

            print("[2] german")
            lang["value"] = "de"
            check("de", play.solo_poses_payload(), {"avatar": "Ann", "poses": [
                {"key": "standing", "label": "Aufrecht stehen"},
                {"key": "kneeling", "label": "Knien"},
                {"key": "waving", "label": "waving"}]})

            print("[3] spectator")
            active["value"] = ""
            check("spectator", play.solo_poses_payload(), {"avatar": "", "poses": []})

        print("[4] clicked pose key")
        calls = []
        answer = {"value": True}

        def setter(name, pose, *args, **kwargs):
            calls.append((name, pose))
            return answer["value"]

        with patch.object(play, "_require_avatar", lambda: "Ann"), \
                patch("app.models.character.set_pose_intent", setter), \
                patch("app.models.character.is_character_sleeping", lambda name: False), \
                patch("app.models.character.get_character_profile", lambda name: {}):
            run = play._play_set_activity_sync
            check("unknown", refusal(run, {"pose_key": "nope"}), (400, "unknown pose"))
            check("pair", refusal(run, {"pose_key": "hug"}), (409, "pair_pose"))
            check("group", refusal(run, {"pose_key": "circle"}), (409, "pair_pose"))
            check("setter untouched by refusals", calls, [])
            check("answer", run({"pose_key": " WAVING "}),
                  {"ok": True, "activity": "waving", "place": None})
            check("setter call", calls, [("Ann", "waving")])
            answer["value"] = False
            check("no place", refusal(run, {"pose_key": "waving"}), (409, "no_free_place"))
        pc.catalog_path = original
        pc.reload_catalogs()

    if FAILS:
        print(f"FAILED: {len(FAILS)} check(s): {', '.join(FAILS)}")
        sys.exit(1)
    print("OK")


if __name__ == "__main__":
    main()
