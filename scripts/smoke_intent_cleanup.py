#!/usr/bin/env python3
"""Intent cleanup against temporary storage.

Usage: ./.venv/bin/python scripts/smoke_intent_cleanup.py

Hand-derived expectations: equal normalized titles keep the newest timestamp,
then larger id on ties. Empty titles never group. At D001 09:00 self now gets
D001 10:00, self standing D004 09:00, human now/standing D002/D008 09:00;
at_time at D002 10:00 gets D002 11:00. Three plans at cap two evict the
priority-five plan. Preview writes nothing and matches application exactly.
End-all expires admin/package rows but spares managed rows.
"""
import asyncio
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    with tempfile.TemporaryDirectory(prefix="intent-cleanup-") as tmp:
        from app.core import paths
        paths.init(Path(tmp))
        paths.init_instance(Path(tmp) / "instance")
        from app.core import config, db
        config.load(Path(tmp) / "config.json")
        db.init_schema()
        from app.models import intents
        from app.core.game_time import GameTime
        fixed = GameTime.parse("Y0001-D001T09:00:00")

        def create(iid, title, **kwargs):
            stamp = kwargs.pop("stamp", "2026-01-01T00:00:00+00:00")
            with patch.object(intents, "utc_now_iso", return_value=stamp):
                return intents.create_intent(intent_id=iid, owner="demo", title=title, **kwargs)

        def clear():
            for row in intents.list_intents():
                assert intents.delete_intent(row["id"])

        def apply(**options):
            before = intents.list_intents()
            preview = intents.cleanup_intents(**options)
            assert intents.list_intents() == before, "preview wrote rows"
            actual = intents.cleanup_intents(**options, dry_run=False)
            assert actual == {**preview, "dry_run": False}, (preview, actual)
            return actual

        with patch.object(intents, "game_time", return_value=fixed), patch.object(
                intents, "is_managed_intent", side_effect=lambda it: bool(it["meta"].get("managed"))), patch.dict(
                config._CONFIG, {"intents": {"max_active_self": 0, "max_active_player": 0}}):
            create("old", "Buy bread!", stamp="2026-01-01T00:00:01+00:00")
            for iid in ("new-a", "new-z"):
                create(iid, "buy_bread", stamp="2026-01-01T00:00:02+00:00", meta={"origin": "marker"})
            create("blank-a", "")
            create("blank-b", "!!!")
            for iid, meta in (("admin", {"origin": "admin"}), ("package", {"origin": "package_goal"}), ("managed", {"managed": True})):
                create(iid, "Buy bread", meta=meta)
            intents.create_intent(intent_id="guest", owner="", title="Buy bread", participants={"demo": {}})
            create("done", "Buy bread", status="done")
            result = apply(owner="demo")
            assert result["counts"] == {"duplicate": 2, "deadline": 3}, result
            assert {it["id"] for it in result["items"] if it["action"] == "duplicate"} == {"old", "new-a"}
            for iid in ("old", "new-a"):
                assert intents.get_intent(iid)["meta"]["expired_reason"] == "duplicate"
            for iid in ("admin", "package", "managed", "guest"):
                row = intents.get_intent(iid)
                assert row["status"] == "active" and not row["expires_at"], row
            assert intents.cleanup_intents("demo")["items"] == []
            print("PASS newest/tie winner, empty titles, exemptions, ownership and dry-run parity")
            clear()
            cases = [("self-now", "character", {"kind": "now"}, "Y0001-D001T10:00:00"),
                     ("self-standing", "character", {"kind": "standing"}, "Y0001-D004T09:00:00"),
                     ("player-now", "human", {"kind": "now"}, "Y0001-D002T09:00:00"),
                     ("player-standing", "human", {"kind": "standing"}, "Y0001-D008T09:00:00"),
                     ("timed", "character", {"kind": "at_time", "run_date": "Y0001-D002T10:00:00"}, "Y0001-D002T11:00:00")]
            for iid, source, trigger, expected in cases:
                create(iid, iid, source=source, trigger=trigger)
                assert intents.default_intent_expiry(trigger, source) == expected
            create("existing", "Existing", expires_at="Y0001-D010T09:00:00")
            assert apply(owner="demo")["counts"] == {"deadline": 5}
            for iid, _, _, expected in cases:
                assert intents.get_intent(iid)["expires_at"] == expected
            assert intents.get_intent("existing")["expires_at"] == "Y0001-D010T09:00:00"
            clear()
            create("unlimited", "Unlimited")
            with patch.dict(config._CONFIG, {"intents": {"self_intent_ttl_days": 0}}):
                assert intents.cleanup_intents("demo")["items"] == []
            print("PASS exact game deadlines, preserved deadlines and zero TTL")
            clear()
            for iid, priority in (("worst", 5), ("middle", 3), ("best", 1)):
                create(iid, iid, priority=priority)
            with patch.dict(config._CONFIG, {"intents": {"max_active_self": 2}}):
                result = apply(owner="demo", set_deadlines=False)
                assert result["items"] == [{"id": "worst", "owner": "demo", "title": "worst", "action": "cap"}], result
            for iid, meta in (("admin", {"origin": "admin"}), ("package", {"origin": "package_goal"}), ("managed", {"managed": True})):
                create(iid, iid, meta=meta)
            for dry_run in (True, False):
                try:
                    intents.cleanup_intents(end_all=True, dry_run=dry_run)
                except ValueError:
                    pass
                else:
                    raise AssertionError("end_all accepted empty owner")
            assert apply(owner="demo", end_all=True)["counts"] == {"cleanup": 4}
            assert intents.get_intent("managed")["status"] == "active"
            print("PASS cap simulation and end_all owner/managed guards")
            clear()
            create("duplicate-old", "Same plan", priority=1)
            create("duplicate-new", "same_plan", stamp="2026-01-01T00:00:01+00:00")
            create("worst", "Worst", priority=5)
            create("best", "Best", priority=1)
            create("player-old", "Player old", source="human", priority=5)
            create("player-new", "Player new", source="human", priority=1)
            with patch.dict(config._CONFIG, {"intents": {"max_active_self": 2, "max_active_player": 1}}):
                result = apply(owner="demo")
                assert result["counts"] == {"duplicate": 1, "deadline": 5, "cap": 2}, result
                assert {it["id"] for it in result["items"] if it["action"] == "cap"} == {"worst", "player-old"}
                assert intents.get_intent("duplicate-new")["status"] == "active"
            print("PASS caps after merging, separate player cap and combined preview parity")
            clear()
            create("owned", "Owned")
            intents.create_intent(intent_id="unowned", owner="", title="Owned")
            assert apply()["counts"] == {"deadline": 2}
            from app.routes.intents import _cleanup_route_sync, cleanup_route
            from fastapi import HTTPException
            for body in ([], {"owner": 1}, {"end_all": True}, {"dry_run": "false"}, {"set_deadlines": None}):
                try:
                    _cleanup_route_sync(body)
                except HTTPException as exc:
                    assert exc.status_code == 400
                else:
                    raise AssertionError(f"accepted invalid body: {body}")
            async def async_body():
                return {"owner": "demo"}
            request = type("Request", (), {"json": lambda self: async_body()})()
            with patch("app.routes.intents.asyncio.to_thread", new_callable=AsyncMock,
                       return_value={"dry_run": True, "items": [], "counts": {}}) as threaded:
                assert asyncio.run(cleanup_route(request))["dry_run"] is True
                threaded.assert_awaited_once_with(_cleanup_route_sync, {"owner": "demo"})
            print("PASS all-owner scope, route validation and thread dispatch")


if __name__ == "__main__":
    main()
