#!/usr/bin/env python3
"""Smoke: the hot-path holds of package prop actions and the pose catalog.

Usage: ./.venv/bin/python scripts/smoke_prop_action_pose_cache.py

Temp world (``paths.init`` before any world module); the pose catalog is a
private COPY injected through ``pose_catalog.catalog_path``, the real tracked
file is checked byte for byte at the end. Both modules' clocks are replaced by
one injected clock ``T`` (starts at 1000.0), so no check sleeps. The package
``smokepack`` is "loaded" by patching ``registry.get_package``; its source
counts its calls in ``CALLS`` and returns one valid definition "sit back"
(ability pose, pose "sitting") whose description is the variable ``DESC``.

Expected values, derived by hand from the two holds:
  prop_action_sources holds a validated set for HOLD_TTL_S = 5.0 s, keyed by
  (its invalidation counter, registry generation); served while T < deadline.
  pose_catalog checks its file at most every FILE_CHECK_INTERVAL_S = 2.0 s per
  axis; a check is due when T - last >= 2.0; reload_catalogs() forgets the
  last check, the cache and the stamps.

A. Package actions
 A1 register at T=1000 -> the first signature() runs the source: CALLS == 1,
    signature is 16 hex chars, one pack action.
 A2 100 x (signature, pack_actions, _current) at T=1004.9 (< 1005.0)
    -> CALLS still 1, signature unchanged, _current()[0] is the SAME list.
 A3 DESC changes WITHOUT invalidation at T=1004.9 -> signature still the old
    one (the staleness bound); at T=1005.0 (== deadline, not < it) the source
    runs (CALLS 2) and the signature differs. Held again until T=1010.0.
 A4 invalidate() at T=1005.0 -> next read runs the source: CALLS 3.
 A5 config._invalidate_config_derived_caches() (what every config load/save
    calls) -> CALLS 4.
 A6 pose_catalog.reload_catalogs() -> CALLS 5.
 A7 registry.unregister_package("smoke-none") bumps the registry generation
    -> CALLS 6.
 A8 a source that calls invalidate() WHILE it runs: its result is not held
    (published only under the key captured before) -> the next read runs it
    again: CALLS +2 over two reads.

B. Pose catalog (stat counter wraps ``_file_stamp``; T=2000 after reload)
 B1 get_catalog("pose") twice -> the SAME dict (cached-dict contract);
    get_groups() -> an equal dict that is NOT the cache: clearing the copy
    leaves the next get_groups() with both groups ("seat", "stand").
 B2 300 reads (get_catalog, get_groups, pose_label) at T=2001.9 -> 0 stats.
 B3 file rewritten from OUTSIDE with entry "smoke_extern" (label "Extern")
    at T=2001.9 -> not seen, pose_label("smoke_extern") is the key itself;
    at T=2002.0 (last check 2000.0 + 2.0) -> seen, label "Extern", exactly 1
    stat for that read; the held package actions dropped too (CALLS +1 on the
    next signature()).
 B4 world-layer save through the real writer
    ``pose_catalog_edit.write_store("pose", {"entries": {"waving": ...,
    "label": "Wave World"}}, "world")`` at T=2002.5 (no clock step past any
    interval) -> pose_label("waving") == "Wave World" at once; package actions
    re-read (CALLS +1).
 B5 shared-file save through the real writer (write_store, store "shared")
    changing "sitting"'s label to "Sit Shared" at T=2002.5 -> seen at once.
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
from uuid import NAMESPACE_URL, uuid5

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
_tmp = tempfile.mkdtemp(prefix="smoke_prop_action_pose_cache_")
os.environ["STORAGE_DIR"] = _tmp
os.environ["ANIMATION_CLIPS_DIR"] = str(Path(_tmp) / "clips")
from app.core import paths                                            # noqa: E402
paths.init(_tmp)
from app.core import config                                           # noqa: E402
from app.core import pose_catalog as pc                               # noqa: E402
from app.core import prop_action_sources as SRC                       # noqa: E402
from app.core.db import init_schema                                   # noqa: E402
from app.plugins import registry                                      # noqa: E402

FAIL = []
T = [1000.0]
CALLS = [0]
DESC = ["first"]
OWNER = "smokepack"


def check(label, got, want):
    if got != want:
        FAIL.append(f"{label}: got {got!r}, want {want!r}")
    else:
        print(f"PASS {label}")


def definition():
    return dict(id="pack-" + str(uuid5(NAMESPACE_URL, f"anima:pack-action:{OWNER}:sit back")),
                name="Sit back", description=DESC[0], enabled=True, ability="pose",
                pose_key="sitting", participants=1, presence="any",
                interrupt_on_presence_change=False, phases=[], requirements=[], effects=[])


def source():
    CALLS[0] += 1
    return [definition()]


CATALOG = {
    "groups": {"stand": {"label": "Stand", "default": "standing", "needs_place": False},
               "seat": {"label": "Seat", "default": "sitting", "needs_place": True}},
    "entries": {
        "standing": {"prompt": "standing", "synonyms": [], "animation": "standing",
                     "participants": 1, "group": "stand", "_default": True},
        "waving": {"prompt": "waving", "synonyms": [], "animation": "waving",
                   "participants": 1, "group": "stand", "label": "Wave"},
        "sitting": {"prompt": "sitting", "synonyms": [], "animation": "sitting",
                    "participants": 1, "group": "seat", "label": "Sit"}}}

REAL = pc.catalog_path("pose")
REAL_BYTES = REAL.read_bytes()
orig_path, orig_pc_clock, orig_src_clock, orig_stamp = (
    pc.catalog_path, pc._clock, SRC._clock, pc._file_stamp)
try:
    init_schema()
    private = Path(_tmp) / "pose_catalog.json"
    private.write_text(json.dumps(CATALOG, ensure_ascii=False, indent=2), encoding="utf-8")
    pc.catalog_path = lambda axis: private if axis == "pose" else orig_path(axis)
    pc._clock = SRC._clock = lambda: T[0]
    real_get = registry.get_package
    patch.object(registry, "get_package",
                 lambda pid: object() if pid == OWNER else real_get(pid)).start()
    pc.reload_catalogs()

    # ---- A ---------------------------------------------------------------
    SRC.register_source(OWNER, source)
    sig1 = SRC.signature()
    check("A1 first read runs the source", CALLS[0], 1)
    check("A1 signature is 16 hex", (len(sig1), all(c in "0123456789abcdef" for c in sig1)), (16, True))
    check("A1 one pack action", len(SRC.pack_actions()), 1)

    T[0] = 1004.9
    first_list = SRC._current()[0]
    same = all(SRC.signature() == sig1 and len(SRC.pack_actions()) == 1
               and SRC._current()[0] is first_list for _ in range(100))
    check("A2 held within the TTL: no source call", CALLS[0], 1)
    check("A2 same signature and same list object", same, True)

    DESC[0] = "second"
    check("A3 change without invalidate unseen inside the TTL", SRC.signature(), sig1)
    T[0] = 1005.0
    sig2 = SRC.signature()
    check("A3 source re-run at the deadline", CALLS[0], 2)
    check("A3 signature follows the change", sig2 != sig1, True)

    SRC.invalidate()
    SRC.signature()
    check("A4 invalidate() forces a re-read", CALLS[0], 3)

    config._invalidate_config_derived_caches()
    SRC.signature()
    check("A5 config load/save hook forces a re-read", CALLS[0], 4)

    pc.reload_catalogs()
    SRC.signature()
    check("A6 pose catalog reload forces a re-read", CALLS[0], 5)

    registry.unregister_package("smoke-none")
    SRC.signature()
    check("A7 registry change forces a re-read", CALLS[0], 6)

    def racing_source():
        CALLS[0] += 1
        SRC.invalidate()
        return [definition()]
    SRC.register_source(OWNER, racing_source)
    before = CALLS[0]
    SRC.signature()
    SRC.signature()
    check("A8 a result invalidated mid-run is not held", CALLS[0] - before, 2)
    SRC.register_source(OWNER, source)

    # ---- B ---------------------------------------------------------------
    STATS = [0]

    def counting_stamp(axis):
        STATS[0] += 1
        return orig_stamp(axis)
    pc._file_stamp = counting_stamp
    T[0] = 2000.0
    pc.reload_catalogs()
    cat_a = pc.get_catalog("pose")
    cat_b = pc.get_catalog("pose")
    check("B1 get_catalog returns the cached dict", cat_a is cat_b, True)
    groups = pc.get_groups()
    groups.clear()
    check("B1 get_groups hands out a copy", sorted(pc.get_groups()), ["seat", "stand"])

    T[0] = 2001.9
    STATS[0] = 0
    for _ in range(100):
        pc.get_catalog("pose")
        pc.get_groups()
        pc.pose_label("waving")
    check("B2 no stat inside the interval", STATS[0], 0)

    doc = json.loads(private.read_text(encoding="utf-8"))
    doc["entries"]["smoke_extern"] = {"prompt": "x", "synonyms": [], "animation": "idle",
                                      "participants": 1, "group": "stand", "label": "Extern"}
    private.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    check("B3 external edit unseen inside the interval",
          ("smoke_extern" in pc.get_catalog("pose"), pc.pose_label("smoke_extern")),
          (False, "smoke_extern"))
    SRC.signature()
    calls_before = CALLS[0]
    T[0] = 2002.0
    STATS[0] = 0
    check("B3 external edit seen after the interval", pc.pose_label("smoke_extern"), "Extern")
    check("B3 exactly one stat for that read", STATS[0], 1)
    SRC.signature()
    check("B3 detected file change drops the held package actions", CALLS[0] - calls_before, 1)

    from app.core import pose_catalog_edit
    T[0] = 2002.5
    calls_before = CALLS[0]
    world_waving = dict(CATALOG["entries"]["waving"], label="Wave World")
    pose_catalog_edit.write_store("pose", {"entries": {"waving": world_waving}}, "world")
    check("B4 world-layer save seen at once", pc.pose_label("waving"), "Wave World")
    SRC.signature()
    check("B4 catalog save drops the held package actions", CALLS[0] - calls_before, 1)

    shared = pose_catalog_edit.read_store("pose", "shared")
    shared["entries"]["sitting"]["label"] = "Sit Shared"
    pose_catalog_edit.write_store("pose", shared, "shared")
    check("B5 shared-file save seen at once", pc.pose_label("sitting"), "Sit Shared")
except Exception as e:                                                # noqa: BLE001
    import traceback
    traceback.print_exc()
    FAIL.append(f"crashed: {e!r}")
finally:
    patch.stopall()
    SRC.unregister_source(OWNER)
    pc.catalog_path, pc._clock, SRC._clock, pc._file_stamp = (
        orig_path, orig_pc_clock, orig_src_clock, orig_stamp)
    if REAL.read_bytes() != REAL_BYTES:
        FAIL.append("REAL catalog modified")
    shutil.rmtree(_tmp, ignore_errors=True)
print("FAIL:\n" + "\n".join(FAIL) if FAIL else "OK smoke_prop_action_pose_cache")
sys.exit(1 if FAIL else 0)
