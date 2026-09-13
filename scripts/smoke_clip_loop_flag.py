#!/usr/bin/env python3
"""Smoke run for the LOOP flag of an animation clip (E5 of
plan-animationen-echtzeit-stehplatz.md).

Builds a throwaway clip tree and points ANIMATION_CLIPS_DIR at it — the real
``shared/models/clips`` is never read or written. No server, no world DB.

THE RULE, from which every expectation below is derived by hand:

  * ``clip_loops(meta)`` — the sidecar's own ``loop`` is the answer WHENEVER
    the key is present, including an explicit ``false``. It is the admin's
    decision, taken in the Poses tab after the import, and it outranks the
    ``geometry.loop`` the importer measured. Only WITHOUT the key does that
    measurement count. No sidecar at all = no loop.

        {"loop": false, "geometry": {"loop": {...}}}  -> False
        {"geometry": {"loop": {...}}}                 -> True
        {"loop": true}                                -> True
        {}                                            -> False
        None                                          -> False

  * ``set_clip_loop(library, rel, loop)`` writes that key into the SHARED
    ``<kind>.json`` beside the clip, so it holds for both halves of a pair and
    for every numbered variant of the kind in that set (a variant carrying an
    own sidecar is written too — otherwise it would be the one file ignoring
    the switch). It touches no other set: ``female/dance.json`` and the root
    ``dance.json`` are two flags, not one.

  * A kind without a shared sidecar has nowhere to keep the flag →
    ``ClipLibraryError``; a clip that does not exist → ``ClipNotFound``.

The tree built here (all files are stubs — nothing parses an FBX):

    <root>/dance.fbx        + dance.json     {"geometry": {"loop": {...}}}
    <root>/dance_02.fbx     + dance_02.json  (its own numbers, no loop key)
    <root>/hug__a.fbx  hug__b.fbx + hug.json {"loop": false, geometry.loop}
    <root>/female/dance.fbx + female/dance.json  {"loop": true}
    <root>/wave.fbx         (no sidecar at all)

Derived expectations:

  [1] ``clip_loops`` on the five metas above.
  [2] The listing: ``dance`` (root) loops (measured), both halves of ``hug``
      do NOT (explicit false beats the measurement), ``female/dance`` loops,
      ``wave`` does not (no sidecar). ``dance_02`` reads its OWN sidecar,
      which has no key and no geometry loop -> False.
  [3] ``set_clip_loop("free", "dance.fbx", False)`` writes ``"loop": false``
      into ``dance.json``, and into ``dance_02.json`` — both root views turn
      False while ``female/dance`` stays True. Setting it back to True turns
      both back, still without touching the set.
  [4] A pair is one kind: ``set_clip_loop("free", "hug__b.fbx", True)`` turns
      BOTH halves True, and the returned views are those two files.
  [5] ``wave.fbx`` (no sidecar) raises ClipLibraryError and writes nothing;
      a file that does not exist raises ClipNotFound.

Usage:  ./.venv/bin/python scripts/smoke_clip_loop_flag.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

CLIPS = Path(tempfile.mkdtemp(prefix="clip-loop-smoke-"))
WORLD = Path(tempfile.mkdtemp(prefix="clip-loop-world-"))
# MUST be set before paths is imported — otherwise the smoke would scan (and
# then WRITE INTO) the repo's real clip library.
os.environ["ANIMATION_CLIPS_DIR"] = str(CLIPS)

from app.core import paths  # noqa: E402

paths.init(WORLD)

from app.core import animation_clips as ac  # noqa: E402

FAILURES = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


def write(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def build_tree() -> None:
    (CLIPS / "dance.fbx").write_bytes(b"dance")
    write(CLIPS / "dance.json",
          {"kind": "dance", "fps": 30, "frames": 60, "duration_s": 2.0,
           "geometry": {"loop": {"score": 0.9}}})
    (CLIPS / "dance_02.fbx").write_bytes(b"dance-2")
    write(CLIPS / "dance_02.json",
          {"kind": "dance", "fps": 30, "frames": 45, "duration_s": 1.5})
    (CLIPS / "hug__a.fbx").write_bytes(b"hug-a")
    (CLIPS / "hug__b.fbx").write_bytes(b"hug-b")
    write(CLIPS / "hug.json",
          {"kind": "hug", "pair": True, "fps": 30, "frames": 60,
           "duration_s": 2.0, "loop": False,
           "geometry": {"loop": {"score": 0.8}, "root_distance_m": 0.5}})
    (CLIPS / "female").mkdir()
    (CLIPS / "female" / "dance.fbx").write_bytes(b"female-dance")
    write(CLIPS / "female" / "dance.json",
          {"kind": "dance", "fps": 30, "frames": 60, "duration_s": 2.0,
           "loop": True})
    (CLIPS / "wave.fbx").write_bytes(b"wave")


def views() -> dict:
    """``{rel: loop}`` of the whole library, as the API delivers it."""
    return {v["rel"]: v["loop"] for v in
            (ac.clip_view(e) for e in ac.clip_entries())}


def sidecar(rel: str) -> dict:
    return json.loads((CLIPS / rel).read_text(encoding="utf-8"))


build_tree()

# ── [1] the derivation ──────────────────────────────────────────────────
print("\n[1] clip_loops — an explicit flag beats the measurement")
check("explicit false beats geometry.loop",
      ac.clip_loops({"loop": False, "geometry": {"loop": {"score": 1}}}) is False)
check("geometry.loop alone means loop",
      ac.clip_loops({"geometry": {"loop": {"score": 1}}}) is True)
check("explicit true means loop", ac.clip_loops({"loop": True}) is True)
check("nothing at all means no loop", ac.clip_loops({}) is False)
check("no sidecar means no loop", ac.clip_loops(None) is False)

# ── [2] the listing ─────────────────────────────────────────────────────
print("\n[2] the listing reads it the same way")
v = views()
check("dance (measured) loops", v["dance.fbx"] is True, str(v))
check("dance_02 reads its OWN sidecar -> no loop", v["dance_02.fbx"] is False)
check("both halves of hug hold their last frame",
      v["hug__a.fbx"] is False and v["hug__b.fbx"] is False)
check("female/dance loops", v["female/dance.fbx"] is True)
check("wave has no sidecar -> no loop", v["wave.fbx"] is False)

# ── [3] writing the flag ────────────────────────────────────────────────
print("\n[3] set_clip_loop writes the kind's sidecar")
out = ac.set_clip_loop("free", "dance.fbx", False)
check("the shared sidecar carries the flag", sidecar("dance.json")["loop"] is False,
      str(sidecar("dance.json")))
check("the variant's own sidecar too", sidecar("dance_02.json")["loop"] is False)
check("the sidecar's other numbers survive",
      sidecar("dance.json")["duration_s"] == 2.0
      and sidecar("dance_02.json")["duration_s"] == 1.5)
v = views()
check("both root files read False now",
      v["dance.fbx"] is False and v["dance_02.fbx"] is False, str(v))
check("the female SET was not touched", v["female/dance.fbx"] is True
      and "loop" in sidecar("female/dance.json"))
check("the answer names the touched files",
      sorted(c["rel"] for c in out) == ["dance.fbx", "dance_02.fbx"],
      str([c["rel"] for c in out]))
ac.set_clip_loop("free", "dance_02.fbx", True)
v = views()
check("and back again, from either file of the kind",
      v["dance.fbx"] is True and v["dance_02.fbx"] is True
      and sidecar("dance.json")["loop"] is True)

# ── [4] a pair is ONE kind ──────────────────────────────────────────────
print("\n[4] a pair is one kind, not two files")
out = ac.set_clip_loop("free", "hug__b.fbx", True)
v = views()
check("both halves loop now", v["hug__a.fbx"] is True and v["hug__b.fbx"] is True)
check("the answer carries both halves",
      sorted(c["rel"] for c in out) == ["hug__a.fbx", "hug__b.fbx"],
      str([c["rel"] for c in out]))

# ── [5] refusals ────────────────────────────────────────────────────────
print("\n[5] nowhere to keep it, and nothing to keep it for")
try:
    ac.set_clip_loop("free", "wave.fbx", True)
    check("a clip without a sidecar is refused", False, "no error raised")
except ac.ClipNotFound as e:
    check("a clip without a sidecar is refused", False, f"wrong error: {e}")
except ac.ClipLibraryError as e:
    check("a clip without a sidecar is refused", True, str(e))
check("… and nothing was written", not (CLIPS / "wave.json").exists())
try:
    ac.set_clip_loop("free", "nope.fbx", True)
    check("a missing clip is a 404", False, "no error raised")
except ac.ClipNotFound as e:
    check("a missing clip is a 404", True, str(e))
except ac.ClipLibraryError as e:
    check("a missing clip is a 404", False, f"wrong error: {e}")

print()
if FAILURES:
    print(f"FAILED: {len(FAILURES)} check(s)")
    for f in FAILURES:
        print(f"  - {f}")
    sys.exit(1)
print("all checks passed")
