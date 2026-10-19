#!/usr/bin/env python3
"""Exact-clock smoke; all storage is temporary.

Hand calculation (anchor G0 = epoch + 100 game seconds):
factor 2, real +10.3 -> elapsed 20.6, rounded 21, fraction -0.4.
factor 1, real +7.2 -> 7 + 0.2; frozen or factor 0 -> 0 + 0.
Real -1.2 -> rounded -1, G0 becomes 99, fraction -0.2.
Anchor 1 at real -1.2 and anchor 0 at -0.2 both clamp exact time to
zero, so their fraction is 0. A 30 m / 30 s journey at 21 - 0.4 s
has walked 20.6 m; a start at G0+25 is still pending at G0+21.2.
The missing API fails on Task 1 commit 0d4c1c88.
"""
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    with tempfile.TemporaryDirectory(prefix="game-time-exact-") as tmp:
        from app.core import paths
        paths.init(Path(tmp))
        from app.core import db
        db.init_schema()
        from app.core import timeutils as tu
        from app.core.timeutils import game_time_exact
        from app.core.game_time import EPOCH, GameDuration
        from app.core.travel_engine import journey_state
        from app.models.world import set_world_frozen

        real = datetime(2026, 1, 1, tzinfo=timezone.utc)
        g0 = EPOCH + GameDuration(100)
        count = 0

        def check(label, actual, expected):
            nonlocal count
            assert actual == expected, f"{label}: {actual!r} != {expected!r}"
            count += 1
            print(f"PASS {label}: {actual!r}")

        for label, anchor, factor, delta, frozen, seconds, fraction in (
            ("factor 2", g0, 2, 10.3, False, 121, -0.4),
            ("factor 1", g0, 1, 7.2, False, 107, 0.2),
            ("frozen", g0, 2, 10.3, True, 100, 0.0),
            ("factor zero unfrozen", g0, 0, 10.3, False, 100, 0.0),
            ("negative elapsed", g0, 1, -1.2, False, 99, -0.2),
            ("clamped negative", EPOCH + GameDuration(1), 1, -1.2, False, 0, 0.0),
            ("clamped rounded zero", EPOCH, 1, -0.2, False, 0, 0.0),
        ):
            set_world_frozen(frozen)
            tu._persist_game_anchors(real, anchor, factor, frozen)
            with patch.object(tu, "utc_now", return_value=real + timedelta(seconds=delta)):
                gt, frac = game_time_exact()
                check(label + " rounded", gt.total_seconds, seconds)
                check(label + " fraction", round(frac, 6), fraction)
                check(label + " game_time unchanged", tu.game_time(), gt)
        wps = [[0, 0, 0], [30, 0, 30]]
        check("offset progress", journey_state(wps, g0.canonical(),
              g0 + GameDuration(21), offset_s=-0.4)["progress_m"], 20.6)
        check("not started", journey_state(wps, (g0 + GameDuration(25)).canonical(),
              g0 + GameDuration(21), offset_s=0.2)["progress_m"], 0.0)
        print(f"OK — {count} checks passed")


if __name__ == "__main__":
    main()
