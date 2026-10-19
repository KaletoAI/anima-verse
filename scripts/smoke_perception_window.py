#!/usr/bin/env python3
"""Smoke subjective perception windows with inclusive game-time bounds.

Usage: ./.venv/bin/python scripts/smoke_perception_window.py

Hand-derived expectations: Ana hears four lines at 10:00, 10:05, 10:05,
and 10:30. The equal-bound 10:05 window contains exactly two; the full
window contains four, in insertion order for equal stamps. Ben hears one
separate line, so his window contains only that line. A fifth Ana perception
has no game stamp and cannot enter either window. Subjective content differs
from canonical content and must be preserved. A limit of two selects the
first two chronological rows; a zero limit and reversed bounds select none.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
STORAGE = Path(tempfile.mkdtemp(prefix="perception-window-"))
from app.core import paths
paths.init(STORAGE)
paths.init_instance(STORAGE / "instance")
from app.core import config, db
config.load(STORAGE / "config.json")
db.init_schema()
from app.models import perception_store as store


def insert(perceiver, clock, content):
    stamp = "Y0001-D001T" + clock if clock else ""
    uid = store.insert_utterance(ts="2026-10-20T10:00:00", speaker="Ana",
                                 location_id="park", room_id="bench", volume="normal",
                                 addressees=[], content="Canonical line", game_ts=stamp)
    store.insert_perceptions(uid, [{"perceiver": perceiver, "ts": "2026-10-20T10:00:00",
                                    "kind": "heard", "content": content}])


for clock, content in [("10:00:00", "First"), ("10:05:00", "Second"),
                       ("10:05:00", "Third"), ("10:30:00", "Fourth")]:
    insert("Ana", clock, content)
insert("Ben", "10:05:00", "Ben heard this")
insert("Ana", "", "Unstamped")
start = "Y0001-D001T10:00:00"
instant = "Y0001-D001T10:05:00"
end = "Y0001-D001T10:30:00"
rows = store.get_character_stream_between("Ana", instant, instant)
assert len(rows) == 2
assert [r["content"] for r in rows] == ["Second", "Third"]
assert all(r["speaker"] == "Ana" and r["kind"] == "heard" and
           r["location_id"] == "park" and r["room_id"] == "bench" for r in rows)
assert rows == sorted(rows, key=lambda r: r["game_ts"])
full = store.get_character_stream_between("Ana", start, end)
assert len(full) == 4
assert [r["content"] for r in full] == ["First", "Second", "Third", "Fourth"]
assert store.get_character_stream_between("Ben", start, end)[0]["content"] == "Ben heard this"
assert len(store.get_character_stream_between("Ben", start, end)) == 1
assert store.get_character_stream_between("Ana", start, end, limit=2) == full[:2]
assert store.get_character_stream_between("Ana", start, end, limit=0) == []
assert store.get_character_stream_between("Ana", end, start) == []
print("PASS: perception window")
