#!/usr/bin/env python3
"""``set_world_frozen`` only acts when the flag really changes (SIM-1).

Usage:
    ./.venv/bin/python scripts/smoke_world_frozen_idempotent.py

Runs against a THROWAWAY storage directory — never touches a real world.
``ANIMATION_CLIPS_DIR`` is redirected before the app modules are imported.

WHY THIS EXISTS. ``app/models/world.py::set_world_frozen`` used to persist
the flag and call ``timeutils.on_freeze_change`` on EVERY call, whatever the
old value was. The hook re-anchors the game clock, and re-anchoring for an
unchanged state moves it: a second freeze adds the whole frozen real span x
factor, a second unfreeze subtracts the span since the unfreeze. Two open
Game-Admin tabs, a browser back or a repeated POST are enough to send the
state that is already set.

``scripts/smoke_world_freeze_clock.py`` pins the arithmetic of the hook's own
guard (the persisted ``anchors_frozen`` marker) — it stubs ``app.models.world``
out entirely and therefore cannot reach the SETTER. This check is the other
half: the setter itself, on a real (throwaway) world_kv.

Hand-derived expectations. ``is_world_frozen()`` reads the persisted flag,
which starts at "0" (the default of ``get_world_setting``):

    call              flag before -> after   world_kv write   hook call
    set(False)  #1        0 -> 0                  no              no
    set(True)   #1        0 -> 1                  yes             yes(True)
    set(True)   #2        1 -> 1                  no              no
    set(False)  #2        1 -> 0                  yes             yes(False)
    set(False)  #3        0 -> 0                  no              no
    set(True)   #3        0 -> 1                  yes             yes(True)

So over that sequence: exactly 3 writes of ``world_frozen`` and exactly 3
hook calls, with the arguments [True, False, True], and the flag ends at
True. The old code made 6 writes and 6 hook calls — the three no-ops are the
ones that used to move the clock.

The hook and the world_kv writer are replaced by counting stand-ins for the
run: this check is about WHETHER the setter acts, not about what the hook
computes (that is the other script's job).
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STORAGE = Path(tempfile.mkdtemp(prefix="frozen-idem-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="frozen-idem-clips-")

from app.core import paths  # noqa: E402
paths.init(STORAGE)
from app.core import db  # noqa: E402
db.init_schema()

from app.core import timeutils  # noqa: E402
from app.models import world as world_model  # noqa: E402

FAILURES: list = []


def check(label, got, want) -> None:
    if got == want:
        print(f"  [ok] {label}: {got!r}")
    else:
        print(f"  [FAIL] {label}: {got!r} != {want!r}")
        FAILURES.append(f"{label}: {got!r} != {want!r}")


def main() -> int:
    print("=" * 72)
    print("set_world_frozen is idempotent (SIM-1)")
    print("=" * 72)

    hook_calls: list = []
    flag_writes: list = []

    real_hook = timeutils.on_freeze_change
    real_set = world_model.set_world_setting

    def spy_hook(frozen):
        hook_calls.append(bool(frozen))

    def spy_set(key, value):
        if key == world_model.WORLD_FROZEN_KEY:
            flag_writes.append(value)
        return real_set(key, value)

    timeutils.on_freeze_change = spy_hook
    world_model.set_world_setting = spy_set
    try:
        check("the world starts thawed", world_model.is_world_frozen(), False)
        world_model.set_world_frozen(False)     # no-op
        check("a no-op unfreeze writes nothing", flag_writes, [])
        check("...and calls no hook", hook_calls, [])

        world_model.set_world_frozen(True)      # acts
        check("freeze #1 persists the flag", world_model.is_world_frozen(), True)
        check("...with one write", flag_writes, ["1"])
        check("...and one hook call", hook_calls, [True])

        world_model.set_world_frozen(True)      # no-op
        check("freeze #2 writes nothing more", flag_writes, ["1"])
        check("...and calls no hook", hook_calls, [True])
        check("...and leaves the world frozen",
              world_model.is_world_frozen(), True)

        world_model.set_world_frozen(False)     # acts
        check("unfreeze #1 persists the flag",
              world_model.is_world_frozen(), False)
        check("...with a second write", flag_writes, ["1", "0"])
        check("...and a second hook call", hook_calls, [True, False])

        world_model.set_world_frozen(False)     # no-op
        check("unfreeze #2 writes nothing more", flag_writes, ["1", "0"])
        check("...and calls no hook", hook_calls, [True, False])

        world_model.set_world_frozen(True)      # acts
        check("the flag can be set again afterwards",
              world_model.is_world_frozen(), True)
        check("three writes over the whole sequence",
              flag_writes, ["1", "0", "1"])
        check("three hook calls, in the right order",
              hook_calls, [True, False, True])

        check("the setter still answers None (the callers' shape)",
              world_model.set_world_frozen(False), None)
    finally:
        timeutils.on_freeze_change = real_hook
        world_model.set_world_setting = real_set

    print("\n" + "=" * 72)
    if FAILURES:
        print(f"FAIL — {len(FAILURES)} check(s):")
        for f in FAILURES:
            print(f"  {f}")
        return 1
    print("PASS — all checks green.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        shutil.rmtree(STORAGE, ignore_errors=True)
