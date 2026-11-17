#!/usr/bin/env python3
"""Smoke: what an inbox import leaves in the clip library besides its own
outputs (review 04#3).

Blender is stood in for (``runner.run`` / ``runner.status`` patched, the
source probe ``_prepare_source`` patched to a fixed family); every directory
is temporary — ANIMATION_CLIPS_DIR, ANIMATION_CLIPS_LICENSED_DIR,
ANIMATION_CLIPS_INBOX_DIR and ANIMATION_RIG_FILE point into one temp dir.

Usage: ./.venv/bin/python scripts/smoke_fbx_import_library_state.py

[A] ``import_alt`` and a concurrent sidecar edit (04#3). The scene ``hug``
    (licensed, pair, sidecar ``hug.json`` with source files a.fbx/b.fbx and
    role anchors a [0, 0], b [0.5, 0]) gets the alt ``b~wave``. The alt run
    reads the sidecar, then waits for the library lock that a second thread
    holds; that thread sets ``loop`` (``set_clip_loop``) and releases. The
    stand-in run answers the scene's anchors unchanged (drift 0).
    Expected: ``hug.json`` has ``loop: true`` (the edit survives) AND
    ``alts.b == ["wave"]`` AND ``source.alt_takes["b~wave"]``; the file
    ``hug__b~wave.fbx`` exists. The old code wrote its pre-wait copy back:
    ``loop`` gone.
[B] same, but the concurrent edit is an orient that moved role b's anchor
    to [0.6, 0] (a re-measure after a turn). The rebuilt frame (b at
    [0.5, 0]) is 0.1 m off the CURRENT scene > 0.005 m → refused with
    ClipImportError, no ``hug__b~cheer.fbx``, sidecar unchanged
    (b anchor 0.6, no alt "cheer"). The old code checked against the
    pre-wait anchors (drift 0) and published the alt into a stale frame.
"""
import json
import os
import sys
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

TMP = Path(tempfile.mkdtemp(prefix="fbx-import-state-"))
FREE, LICENSED, INBOX = TMP / "free", TMP / "licensed", TMP / "inbox"
RIG = TMP / "rig.fbx"
os.environ["ANIMATION_CLIPS_DIR"] = str(FREE)
os.environ["ANIMATION_CLIPS_LICENSED_DIR"] = str(LICENSED)
os.environ["ANIMATION_CLIPS_INBOX_DIR"] = str(INBOX)
os.environ["ANIMATION_RIG_FILE"] = str(RIG)

from app.core import paths  # noqa: E402

paths.init(TMP / "world")

from app.core import db  # noqa: E402

db.init_schema()

from app.core import animation_clips as clips  # noqa: E402
from app.core import fbx_import  # noqa: E402
from app.core.cmu_import import ClipImportError  # noqa: E402
from app.core.keyed_lock import keyed_lock  # noqa: E402

FAIL = []


def check(label, ok, detail=""):
    print(f"{'ok  ' if ok else 'FAIL'} {label}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        FAIL.append(label)


def fake_prepare_source(path, take, *, name=None, src_family=""):
    return "unity-humanoid", {"index": take, "take_name": "", "name": name or path.name}


def fake_status():
    return {"executable": "fixture"}


ANCHORS = {"a": [0.0, 0.0], "b": [0.5, 0.0]}


def fake_run(script, *, inputs=None, params=None, out_dir=None, timeout_s=0):
    """The fbx_clip contract for ``export: alts``: only the alt file, and the
    scene's role points as rebuilt from its sources (ANCHORS)."""
    out = Path(out_dir)
    outputs = {}
    for alt in params.get("alts") or []:
        stem = f"{params['kind']}__{alt['role']}~{alt['name']}"
        (out / f"{stem}.fbx").write_bytes(b"alt-" + stem.encode())
        outputs[stem] = str(out / f"{stem}.fbx")
    data = {"geometry": {"roles": {r: {"anchor_xz_m": list(v)} for r, v in ANCHORS.items()},
                         "alts": {f"{a['role']}~{a['name']}": {"start_xz_m": [0, 0]}
                                  for a in params.get("alts") or []}}}
    return {"ok": True, "outputs": outputs, "data": data, "seconds": 0.1}


def write_scene():
    LICENSED.mkdir(parents=True, exist_ok=True)
    for role in ("a", "b"):
        (LICENSED / f"hug__{role}.fbx").write_bytes(b"half-" + role.encode())
    meta = {"kind": "hug", "pair": True, "roles": ["a", "b"], "fps": 30, "loop": False,
            "geometry": {"roles": {r: {"anchor_xz_m": list(v)} for r, v in ANCHORS.items()},
                         "anchor_s": 0.5},
            "source": {"format": "fbx", "files": ["a.fbx", "b.fbx"], "takes": [None, None]}}
    (LICENSED / "hug.json").write_text(json.dumps(meta), encoding="utf-8")
    clips.reload_clip_caches()


def sidecar():
    return json.loads((LICENSED / "hug.json").read_text(encoding="utf-8"))


def alt_with_concurrent_edit(alt, edit):
    """Run ``import_alt`` for ``alt`` in a thread while another thread holds
    the library lock; ``edit`` runs in the holder after the import asked for
    the lock (it has read the sidecar by then)."""
    asked = threading.Event()
    real_lock = fbx_import.library_write_lock

    @contextmanager
    def signalling_lock(destination):
        asked.set()
        with real_lock(destination):
            yield

    taken, release = threading.Event(), threading.Event()

    def holder():
        with keyed_lock("clip_library", "write"):
            taken.set()
            asked.wait(10)
            edit()
            release.wait(0.2)

    outcome = {}

    def importer():
        try:
            outcome["result"] = fbx_import.import_alt(
                "hug", "b", alt, {"name": "alt.fbx", "take": None}, target="licensed")
        except ClipImportError as e:
            outcome["error"] = str(e)

    with patch.object(fbx_import, "library_write_lock", signalling_lock):
        h = threading.Thread(target=holder)
        h.start()
        taken.wait(10)
        i = threading.Thread(target=importer)
        i.start()
        h.join(20)
        i.join(20)
    return outcome


def test_alt_keeps_concurrent_edit():
    print("[A] import_alt keeps a sidecar edit made while it waited")
    write_scene()
    outcome = alt_with_concurrent_edit(
        "wave", lambda: clips.set_clip_loop("licensed", "hug__a.fbx", True))
    check("the alt import succeeded", "result" in outcome, str(outcome))
    meta = sidecar()
    check("loop: true survived the alt import", meta.get("loop") is True, str(meta.get("loop")))
    check("alts.b names the new alt", (meta.get("alts") or {}).get("b") == ["wave"],
          str(meta.get("alts")))
    check("source.alt_takes records it",
          "b~wave" in ((meta.get("source") or {}).get("alt_takes") or {}), str(meta.get("source")))
    check("the alt file was written", (LICENSED / "hug__b~wave.fbx").is_file())


def test_alt_checks_current_frame():
    print("[B] import_alt checks the frame against the CURRENT sidecar")

    def orient():
        meta = sidecar()
        meta["geometry"]["roles"]["b"]["anchor_xz_m"] = [0.6, 0.0]
        (LICENSED / "hug.json").write_text(json.dumps(meta), encoding="utf-8")

    outcome = alt_with_concurrent_edit("cheer", orient)
    check("the alt import was refused", "error" in outcome and "nothing was written" in outcome["error"],
          str(outcome))
    check("no alt file was written", not (LICENSED / "hug__b~cheer.fbx").exists())
    meta = sidecar()
    check("the sidecar keeps the moved anchor and no alt 'cheer'",
          meta["geometry"]["roles"]["b"]["anchor_xz_m"] == [0.6, 0.0]
          and "cheer" not in ((meta.get("alts") or {}).get("b") or []), str(meta))


def main():
    INBOX.mkdir(parents=True, exist_ok=True)
    for name in ("a.fbx", "b.fbx", "alt.fbx"):
        (INBOX / name).write_bytes(b"source")
    RIG.write_bytes(b"rig")
    with patch.object(fbx_import, "_prepare_source", fake_prepare_source), \
         patch.object(fbx_import.runner, "status", fake_status), \
         patch.object(fbx_import.runner, "run", fake_run):
        test_alt_keeps_concurrent_edit()
        test_alt_checks_current_frame()
    print("FAIL" if FAIL else "PASS", f"({len(FAIL)} failing)" if FAIL else "")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
