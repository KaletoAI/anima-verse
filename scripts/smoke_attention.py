#!/usr/bin/env python3
"""Hand-derived Task 1 expectations. Usage: ./.venv/bin/python scripts/smoke_attention.py

[a] Awake, alone, no flags -> no distraction condition holds -> False.
[b] Sleeping -> True. [c] Running pair -> True.
[d] Two addressed A/B lines at T: at T+300 seconds both ages are inside
    the inclusive five-minute window -> True; T+301 -> False. Other room -> False.
[e] Registered distracting flag set -> True; unset or distracting=False ->
    False. Unknown flags do nothing. Supplied empty profile stays empty.
[f] Manifest distracting: true -> True; omitted -> False.
[g] r1 -> r2 adds exactly (A, loc, r2); repeated r2 adds zero. Moving to
    other/r3 adds one; repeating other adds zero. Another location using r3
    adds one. Empty room, unknown location and failed writes add zero.
    Callbacks see durable state with world/profile locks free to another thread.
    Under nested caller locks, delivery waits until the outermost release;
    two real changes remain two ordered events, even across an exception.
    A post-write history error cannot suppress the event for a durable move.

Only temporary storage. Unrelated movement side effects are disabled;
profile persistence, room selection, conversations and hook dispatch are real.
"""
import os
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    with tempfile.TemporaryDirectory(prefix="attention-") as tmp:
        os.environ["ANIMATION_CLIPS_DIR"] = str(Path(tmp) / "clips")
        from app.core import paths
        paths.init(tmp)
        from app.core import db
        db.init_schema()
        try:
            from app.core.attention import is_distracted
        except ImportError:
            print("FAIL [a]-[g]: attention.is_distracted is missing")
            return 1
        from app.models import character as chars, world, perception_store
        from app.core import hooks
        from app.core.game_time import GameTime, GameDuration
        from app.core.keyed_lock import keyed_lock
        from app.plugins.registry import FlagSpec, Package, register_package
        from app.plugins.loader import _load_yaml, _parse_package

        base = {"current_location": "loc", "current_room": "r1"}
        assert chars.save_character_profile("A", base, create_new=True)
        assert not is_distracted("A")
        print("PASS [a] awake and alone")
        assert is_distracted("A", profile={**base, "is_sleeping": True})
        print("PASS [b] sleeping")
        pair = dict(id="pair", kind="pair", role="actor", partner="B",
                    started_at_game="Y0001-D001T12:00:00")
        assert is_distracted("A", profile={**base, "interaction": pair})
        print("PASS [c] pair interaction")
        now = GameTime.from_parts(1, 1, 12, 0, 0)
        for speaker, addressee in (("A", "B"), ("B", "A")):
            perception_store.insert_utterance(
                ts="2026-01-01T12:00:00+00:00", speaker=speaker,
                location_id="loc", room_id="r1", volume="normal",
                addressees=[addressee], content="Hello.", game_ts=now.canonical())
        with patch("app.core.timeutils.game_time", return_value=now + GameDuration(300)):
            assert is_distracted("A")
            assert not is_distracted("A", profile={**base, "current_room": "r2"})
        with patch("app.core.timeutils.game_time", return_value=now + GameDuration(301)):
            assert not is_distracted("A")
            spec = FlagSpec(flag="is_focused_test", package_id="attention-test", distracting=True)
            pkg = Package(id="attention-test", dir=Path(tmp), manifest={}, flags=[spec])
            register_package(pkg)
            assert is_distracted("A", profile={**base, spec.flag: True})
            assert not is_distracted("A", profile={**base, spec.flag: False})
            spec.distracting = False
            assert not is_distracted("A", profile={**base, spec.flag: True})
            assert not is_distracted("A", profile={**base, "unknown_test": True})
            assert chars.save_character_profile("A", {**base, "is_sleeping": True})
            assert not is_distracted("A", profile={})
        print("PASS [d] conversation window and room isolation")
        print("PASS [e] registered flag and supplied profile")
        manifest = Path(tmp) / "plugin.yaml"
        manifest.write_text("name: Attention test\nstate_flags:\n  - flag: is_focused_test\n    distracting: true\n  - flag: is_plain_test\n", encoding="utf-8")
        parsed = _parse_package(Path(tmp), _load_yaml(manifest), register_tasks=False)
        assert parsed is not None
        assert [f.distracting for f in parsed.flags] == [True, False]
        print("PASS [f] manifest parsing and default")

        for loc_id, room in (("loc", "r1"), ("other", "r3"), ("third", "r3")):
            world.upsert_location({"id": loc_id, "name": loc_id, "entry_room": room,
                                   "rooms": [{"id": room, "name": room}, {"id": "r2", "name": "r2"}]}, sync_world=False)
        assert chars.save_character_profile("A", base)
        calls, errors = [], []

        def available(lock):
            acquired = lock.acquire(blocking=False)
            if acquired:
                lock.release()
            return acquired

        def entered(character, location_id, room_id):
            calls.append((character, location_id, room_id))
            try:
                with ThreadPoolExecutor(max_workers=1) as pool:
                    for lock in (world.world_write_lock, keyed_lock("character_profile", character)):
                        assert pool.submit(available, lock).result(timeout=2), "hook under lock"
            except Exception as exc:
                errors.append(str(exc))

        hooks.register("character.entered_room", entered, tag="attention-smoke")
        with ExitStack() as stack:
            for target in (
                "app.core.interaction_engine.end_interaction", "app.core.room_stand.stand_up",
                "app.core.outfit_compliance.apply_outfit_compliance",
                "app.core.flag_lifecycle.on_location_change", "app.core.discovery.discover_in_range",
                "app.models.character.record_state_change", "app.models.character._movement_trace",
                "app.models.character._suggest_follow_after_move", "app.models.character.clear_forbidden_slots",
                "app.models.character.add_known_location", "app.models.character._schedule_background_variant",
                "app.models.character._drag_party_followers_to_location",
                "app.models.character._drag_party_followers_to_room",
            ):
                stack.enter_context(patch(target))
            chars.save_character_current_room("A", "r2")
            assert calls == [("A", "loc", "r2")], calls
            assert chars.get_character_current_room("A") == "r2"
            chars.save_character_current_room("A", "r2")
            assert len(calls) == 1
            chars.save_character_current_location("A", "other", sync_pos=False)
            assert calls[-1] == ("A", "other", "r3") and len(calls) == 2
            chars.save_character_current_location("A", "other", sync_pos=False)
            assert len(calls) == 2
            chars.save_character_current_location("A", "third", sync_pos=False)
            assert calls[-1] == ("A", "third", "r3") and len(calls) == 3
            with patch.object(chars, "save_character_profile", return_value=False):
                chars.save_character_current_room("A", "r2")
                chars.save_character_current_location("A", "loc", sync_pos=False)
            assert len(calls) == 3
            chars.save_character_current_room("A", "")
            chars.save_character_current_location("A", "unknown", sync_pos=False)
            assert len(calls) == 3
            assert not errors, errors
            chars.save_character_current_location("A", "loc", sync_pos=False)
            before = len(calls)
            try:
                with world.world_write_lock:
                    with keyed_lock("character_profile", "B"):
                        with keyed_lock("character_profile", "A"):
                            chars.save_character_current_room("A", "r2")
                            chars.save_character_current_room("A", "r1")
                        assert len(calls) == before, "delivery under caller locks"
                    assert len(calls) == before, "delivery under world lock"
                    raise ValueError("unwind caller locks")
            except ValueError:
                pass
            assert calls[before:] == [("A", "loc", "r2"), ("A", "loc", "r1")]
            assert not errors, errors
            for setter, target, expected in (
                (chars.save_character_current_room, "r2", ("A", "loc", "r2")),
                (chars.save_character_current_location, "other", ("A", "other", "r3")),
            ):
                before = len(calls)
                with patch.object(chars, "record_state_change", side_effect=RuntimeError("history failed")):
                    try:
                        setter("A", target)
                    except RuntimeError as exc:
                        assert str(exc) == "history failed"
                assert calls[before:] == [expected], "durable move lost its entry event"
            assert not errors, errors
        print("PASS [g] durable room-entry events, locks and no-ops")
    print("PASS smoke_attention: [a]-[g]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
