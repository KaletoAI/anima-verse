#!/usr/bin/env python3
"""Smoke: how the clip-library writers of ``app/core/animation_clips.py``
write (review 04#6).

All libraries, the world and the transition seed are temporary
(ANIMATION_CLIPS_DIR / ANIMATION_CLIPS_LICENSED_DIR / ANIMATION_CLIPS_INBOX_DIR
/ ANIMATION_RIG_FILE in one temp dir, ``clip_transitions_path`` patched). No
Blender: only renderer-side edits are made.

Usage: ./.venv/bin/python scripts/smoke_clip_library_writes.py

[6] Every sidecar / transition-seed write is staged and renamed in (04#6).
    ``Path.write_text`` is watched: a write whose file name does not start
    with "." (``sibling_stage`` names its stage ``.<name>.<random>.tmp``)
    into the temp tree is a truncate-in-place write a concurrent reader can
    catch half done. Writers run: set_clip_loop, set_clip_loop_count,
    set_clip_role_gender, set_clip_contact_target, set_clip_bend_limits,
    set_clip_root_angle, set_clip_height_offsets, mark_clip_checked,
    orient_clip (shift_cm only), save_transitions, migrate_contact_target_words,
    rename_clip (the moved sidecar's kind is rewritten).
    Expected: 0 in-place writes (the old code wrote every one of them in
    place); each value landed (loop true, loop_count 3, role_gender a male /
    b female, height ground 5, checked.prop "bench", shift [10, 0], the
    renamed sidecar's kind "cuddle", one sidecar migrated from the old
    contact word "head_front"); the
    sidecars written over a 0644 file are still 0644 (a stage is created
    0600 by mkstemp — copying the mode keeps them readable).
"""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

TMP = Path(tempfile.mkdtemp(prefix="clip-library-writes-"))
FREE, LICENSED = TMP / "free", TMP / "licensed"
os.environ["ANIMATION_CLIPS_DIR"] = str(FREE)
os.environ["ANIMATION_CLIPS_LICENSED_DIR"] = str(LICENSED)
os.environ["ANIMATION_CLIPS_INBOX_DIR"] = str(TMP / "inbox")
os.environ["ANIMATION_RIG_FILE"] = str(TMP / "rig.fbx")

from app.core import paths  # noqa: E402

paths.init(TMP / "world")

from app.core import db  # noqa: E402

db.init_schema()

from app.core import animation_clips as clips  # noqa: E402

TRANSITIONS = TMP / "transitions.json"
FAIL = []


def check(label, ok, detail=""):
    print(f"{'ok  ' if ok else 'FAIL'} {label}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        FAIL.append(label)


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_fixture():
    FREE.mkdir(parents=True, exist_ok=True)
    (FREE / "walk.fbx").write_bytes(b"walk")
    (FREE / "walk.json").write_text(json.dumps({"kind": "walk", "fps": 30}), encoding="utf-8")
    for role in ("a", "b"):
        (FREE / f"hug__{role}.fbx").write_bytes(b"hug-" + role.encode())
    (FREE / "hug.json").write_text(json.dumps({
        "kind": "hug", "pair": True, "roles": ["a", "b"], "fps": 30,
        "contact_relations": [{"part": "b", "at": "a", "target": "head_front"}],
        "geometry": {"roles": {"a": {"anchor_xz_m": [0, 0]}, "b": {"anchor_xz_m": [0.5, 0]}}},
    }), encoding="utf-8")
    for name in ("walk.json", "hug.json"):
        os.chmod(FREE / name, 0o644)
    clips.reload_clip_caches()


def test_atomic_writes():
    print("[6] every sidecar and seed write is staged and renamed in")
    in_place = []
    real_write_text = Path.write_text

    def watched(self, *args, **kwargs):
        if str(self).startswith(str(TMP)) and not self.name.startswith("."):
            in_place.append(self.name)
        return real_write_text(self, *args, **kwargs)

    with patch.object(Path, "write_text", watched):
        clips.set_clip_loop("free", "walk.fbx", True)
        clips.set_clip_loop_count("free", "walk.fbx", 3)
        clips.set_clip_role_gender("free", "hug__a.fbx", {"a": "male", "b": "female"})
        migrated = clips.migrate_contact_target_words()
        clips.set_clip_contact_target("free", "hug__a.fbx", None)
        clips.set_clip_bend_limits("free", "hug__a.fbx", None)
        clips.set_clip_root_angle("free", "hug__a.fbx", None)
        clips.set_clip_height_offsets("free", "walk.fbx", {"ground": 5})
        clips.mark_clip_checked("free", "hug__a.fbx", clips.validate_orientation_check(
            {"prop": "bench", "place": "seat", "dyaw": 0, "dpos": 0}))
        clips.orient_clip("free", "walk.fbx", shift_cm=[10, 0])
        clips.save_transitions([], path=TRANSITIONS)
        clips.rename_clip("free", "hug__a.fbx", kind="cuddle")
    check("no write truncated a file in place", in_place == [], str(sorted(set(in_place))))

    walk = read(FREE / "walk.json")
    check("walk.json: loop true, loop_count 3, ground +5, shift [10, 0]",
          walk.get("loop") is True and walk.get("loop_count") == 3
          and (walk.get("height_offsets_cm") or {}).get("ground") == 5
          and (walk.get("geometry") or {}).get("shift_cm") == [10.0, 0.0], str(walk))
    cuddle = read(FREE / "cuddle.json")
    check("the renamed pair's sidecar carries kind cuddle, its genders and its check",
          cuddle.get("kind") == "cuddle"
          and cuddle.get("role_gender") == {"a": "male", "b": "female"}
          and (cuddle.get("geometry") or {}).get("checked", {}).get("prop") == "bench", str(cuddle))
    check("the old contact word was migrated (one sidecar), then cleared",
          migrated == 1 and "contact_relations" not in cuddle,
          f"{migrated} {cuddle.get('contact_relations')}")
    check("the transition seed holds the saved (empty) list",
          read(TRANSITIONS) == {"transitions": []}, TRANSITIONS.read_text())
    check("walk.json kept its 0644 mode", (FREE / "walk.json").stat().st_mode & 0o777 == 0o644,
          oct((FREE / "walk.json").stat().st_mode & 0o777))
    check("no stage file was left behind",
          not [p.name for p in FREE.iterdir() if p.name.startswith(".")],
          str([p.name for p in FREE.iterdir()]))


def main():
    write_fixture()
    with patch.object(clips, "clip_transitions_path", return_value=TRANSITIONS):
        test_atomic_writes()
    print("FAIL" if FAIL else "PASS", f"({len(FAIL)} failing)" if FAIL else "")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
