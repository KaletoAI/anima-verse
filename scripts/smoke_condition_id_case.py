"""Smoke: a condition named by an item matches its definition case-insensitively.

Usage: ./.venv/bin/python scripts/smoke_condition_id_case.py

2026-11-09: a spell item applied "libido increased", the world's condition
id was "libido Increased"; effect validation compared exactly and dropped the
condition without a word. Every other condition match (prompt_filters) is
case-insensitive. Pure functions only — no world, no DB.

Hand-derived expectations:
[1] catalogs hold lowercase ids → "libido increased" and "LIBIDO INCREASED"
    validate ("" = ok); "charmed" (not defined) → "unknown_condition".
[2] applying "libido increased" to a profile that already carries the live
    entry "libido Increased" REFRESHES it: one entry afterwards, not two.
[3] removing "Libido increased" removes that entry: zero entries afterwards.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.effect_application import apply_effects_to_profile, validate_profile_effects
from app.core.game_time import GameTime

catalogs = dict(conditions={"libido increased", "drunk"}, templates={})
add = dict(id="c", type="condition_add", condition_id="libido increased", duration_game_s=3600)

assert validate_profile_effects({}, [add], catalogs) == "", "[1] lowercase name"
assert validate_profile_effects({}, [dict(add, condition_id="LIBIDO INCREASED")], catalogs) == "", "[1] upper"
assert validate_profile_effects({}, [dict(add, condition_id="charmed")], catalogs) == "unknown_condition", "[1] unknown"
print("[1] validation is case-insensitive — PASS")

now = GameTime.parse("Y0001-D001T10:00:00")
profile = dict(active_conditions=[dict(name="libido Increased", started_at=now.canonical(), duration_hours=1)])
out = apply_effects_to_profile(profile, [add], now)
assert len(out["profile"]["active_conditions"]) == 1, out["profile"]["active_conditions"]
assert out["results"]["c"]["refreshed"] is True
print("[2] a differently cased add refreshes the live entry — PASS")

out = apply_effects_to_profile(profile, [dict(add, type="condition_remove", condition_id="Libido increased")], now)
assert out["profile"]["active_conditions"] == [], out["profile"]["active_conditions"]
print("[3] a differently cased remove removes it — PASS")
print("ALL OK")
