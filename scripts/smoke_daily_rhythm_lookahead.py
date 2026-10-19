#!/usr/bin/env python3
"""Verify daily rhythm lookahead against hand-derived block boundaries.

Fixture: sleep 23–06, Home/work 08–12, Home/tidy 14, Cafe/post 15,
Home/evening 18–21; every other hour is free. Thus boundaries are
07, 08, 13, 14, 15, 16, 18, 22, 23, with sleep crossing midnight.

By hand, the current block plus three successors gives:
1. At 09: work until 13, free at 13, tidy at 14, post at 15.
2. At 02: sleep until 07, free at 07, work at 08, free at 13.
3. At 22: free until 23, sleep 23–07, free at 07, work at 08.
4. At Cafe at 15: post until 16, free at 16, evening at 18, free at 22.
Only the first future place different from here AND the current block gets
the exact set-off sentence below.
5. A deleted Cafe at 15 leaves role post until 16, then free at 16,
evening at 18, free at 22. With no role either, all 24 hours merge into
one free block and the output is empty. These are literal expectations,
not snapshots. Additional boundary checks pin the 24-hour horizon and gates. A second
fixture has Cafe roles at 09 (first), 10 (second), 11 (third), then free
at 12: distinct roles prevent merging. At Home, the current Cafe block
gets the current-place note; 10 and 11 get none (the same trip).

Home config is Home, so sleep appends ", at home: Home". At Home at 02,
the boundaries are sleep until 07, free 07, Home/work 08, free 13.
At Cafe at 02 only current sleep gets the current-place note: work at 08
has the same destination. At Cafe at 22, free ends at 23, sleep 23–07
gets the only set-off note, then free 07 and work 08 get none.
Off-map, empty and deleted homes omit the suffix and sleep notes; at Cafe,
work at 08 then gets the first set-off note. An empty world must also
leave an unknown home unresolved, without an orphan warning.

Literal sleep expectations derived from those boundaries (two-space indent):
At Home, 02:
  now, until 07:00 — you usually sleep around now, at home: Home
  07:00 — free, nothing planned
  08:00 — location: Home, role: work
  13:00 — free, nothing planned
At Cafe, 02:
  now, until 07:00 — you usually sleep around now, at home: Home — you are not there right now; getting there takes in-world time
  07:00 — free, nothing planned
  08:00 — location: Home, role: work
  13:00 — free, nothing planned
At Cafe, 22:
  now, until 23:00 — free, nothing planned
  23:00 — you usually sleep (until 07:00), at home: Home — you are not there; set off in time, getting there takes in-world time
  07:00 — free, nothing planned
  08:00 — location: Home, role: work
Without a usable home at Cafe, 02:
  now, until 07:00 — you usually sleep around now
  07:00 — free, nothing planned
  08:00 — location: Home — you are not there; set off in time, getting there takes in-world time, role: work
  13:00 — free, nothing planned
Without a usable home at Cafe, 22:
  now, until 23:00 — free, nothing planned
  23:00 — you usually sleep (until 07:00)
  07:00 — free, nothing planned
  08:00 — location: Home — you are not there; set off in time, getting there takes in-world time, role: work
An all-sleep day in an empty world spans the full horizon at 02:
  now, until 02:00 — you usually sleep around now

Usage: ./.venv/bin/python scripts/smoke_daily_rhythm_lookahead.py
"""
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths

STORAGE = Path(tempfile.mkdtemp(prefix="rhythm-lookahead-"))
paths.init(STORAGE)
from app.core import db, thought_context
from app.core.game_time import GameTime
from app.models.world import add_location, list_locations, replace_all_locations
from app.models.character import (
    save_character_profile, save_character_current_location,
    save_character_daily_schedule, save_character_config,
)

db.init_schema()
HOME = add_location("Home", "fixture")["id"]
CAFE = add_location("Cafe", "fixture")["id"]
NAME = "Rhythm Smoke"
save_character_profile(NAME, {"language": "en"}, create_new=True)
save_character_current_location(NAME, HOME)
assert save_character_config(NAME, {"home_location": HOME})
SLOTS = ([{"hour": h, "sleep": True} for h in [23, *range(7)]]
         + [{"hour": h, "location": HOME, "role": "work"} for h in range(8, 13)]
         + [{"hour": 14, "location": HOME, "role": "tidy"},
            {"hour": 15, "location": CAFE, "role": "post"}]
         + [{"hour": h, "location": HOME, "role": "evening"} for h in range(18, 22)])


def schedule(slots, enabled=True):
    save_character_daily_schedule(NAME, {"enabled": enabled, "slots": slots})


def check(label, hour, expected):
    with patch.object(thought_context, "game_time", return_value=GameTime.from_parts(1, 1, hour, 30, 0)):
        actual = thought_context._build_daily_schedule_block(NAME)
    assert actual == expected, f"{label}:\n{actual!r}\nexpected:\n{expected!r}"
    print(f"OK {label}")


schedule(SLOTS)
check("1 daytime", 9,
      "  now, until 13:00 — location: Home, role: work\n"
      "  13:00 — free, nothing planned\n"
      "  14:00 — location: Home, role: tidy\n"
      "  15:00 — location: Cafe — you are not there; set off in time, getting there takes in-world time, role: post")
check("2 midnight merge", 2,
      "  now, until 07:00 — you usually sleep around now, at home: Home\n"
      "  07:00 — free, nothing planned\n"
      "  08:00 — location: Home, role: work\n"
      "  13:00 — free, nothing planned")
check("3 tomorrow", 22,
      "  now, until 23:00 — free, nothing planned\n"
      "  23:00 — you usually sleep (until 07:00), at home: Home\n"
      "  07:00 — free, nothing planned\n"
      "  08:00 — location: Home, role: work")
save_character_current_location(NAME, CAFE)
check("4 at Cafe", 15,
      "  now, until 16:00 — location: Cafe, role: post\n"
      "  16:00 — free, nothing planned\n"
      "  18:00 — location: Home — you are not there; set off in time, getting there takes in-world time, role: evening\n"
      "  22:00 — free, nothing planned")
check("sleep away from home", 2,
      "  now, until 07:00 — you usually sleep around now, at home: Home — you are not there right now; getting there takes in-world time\n"
      "  07:00 — free, nothing planned\n"
      "  08:00 — location: Home, role: work\n"
      "  13:00 — free, nothing planned")
check("future sleep away from home", 22,
      "  now, until 23:00 — free, nothing planned\n"
      "  23:00 — you usually sleep (until 07:00), at home: Home — you are not there; set off in time, getting there takes in-world time\n"
      "  07:00 — free, nothing planned\n"
      "  08:00 — location: Home, role: work")
for home in ("__offmap__", "", "deleted-home"):
    assert save_character_config(NAME, {"home_location": home})
    with patch.object(thought_context, "_warn_orphan_slot") as warn:
        check(f"current sleep without home {home!r}", 2,
              "  now, until 07:00 — you usually sleep around now\n"
              "  07:00 — free, nothing planned\n"
              "  08:00 — location: Home — you are not there; set off in time, getting there takes in-world time, role: work\n"
              "  13:00 — free, nothing planned")
        check(f"future sleep without home {home!r}", 22,
              "  now, until 23:00 — free, nothing planned\n"
              "  23:00 — you usually sleep (until 07:00)\n"
              "  07:00 — free, nothing planned\n"
              "  08:00 — location: Home — you are not there; set off in time, getting there takes in-world time, role: work")
    warn.assert_not_called()
assert save_character_config(NAME, {"home_location": HOME})
save_character_current_location(NAME, HOME)
schedule([{"hour": h, "location": CAFE, "role": role}
          for h, role in [(9, "first"), (10, "second"), (11, "third")]])
check("current note and only one following nudge", 9,
      "  now, until 10:00 — location: Cafe — you are not there right now; getting there takes in-world time, role: first\n"
      "  10:00 — location: Cafe, role: second\n"
      "  11:00 — location: Cafe, role: third\n"
      "  12:00 — free, nothing planned")
schedule(SLOTS)
replace_all_locations({"locations": [loc for loc in list_locations() if loc["id"] != CAFE]})
check("5 orphan role", 15,
      "  now, until 16:00 — role: post\n"
      "  16:00 — free, nothing planned\n"
      "  18:00 — location: Home, role: evening\n"
      "  22:00 — free, nothing planned")
schedule([{"hour": 15, "location": CAFE}])
check("5 only free", 15, "")
schedule([])
check("no slots", 9, "")
schedule(SLOTS, enabled=False)
check("disabled", 9, "")
schedule(SLOTS)
with patch("app.models.character_template.is_feature_enabled", return_value=False):
    check("gate off", 9, "")
# A constant day has one block, ending at the 24-hour horizon (09 tomorrow).
schedule([{"hour": h, "location": HOME, "role": "work"} for h in range(24)])
check("constant day horizon", 9, "  now, until 09:00 — location: Home, role: work")
replace_all_locations({"locations": []})
assert save_character_config(NAME, {"home_location": "deleted-home"})
schedule([{"hour": h, "sleep": True} for h in range(24)])
with patch.object(thought_context, "_warn_orphan_slot") as warn:
    check("unknown home in empty world", 2,
          "  now, until 02:00 — you usually sleep around now")
warn.assert_not_called()
print("ALL GREEN")
