#!/usr/bin/env python3
"""Smoke run for the clip LIBRARY view — sidecar data in the listing plus the
delete / rename / move operations behind the Poses tab (app/core/animation_clips.py).

Builds a throwaway FREE and LICENSED library and points ANIMATION_CLIPS_DIR /
ANIMATION_CLIPS_LICENSED_DIR at them BEFORE the app modules are imported — the
real shared/models/clips* are never read and never touched. The core functions
are exercised directly; the routes are thin wrappers over exactly these calls
(their only own job is the status mapping 400/404/409).

The fixture (dummy .fbx bytes, real JSON sidecars):

    free/                          licensed/
      walk.fbx                       wave.fbx      + wave.json
      walk_02.fbx                    dance.fbx     (no sidecar)
      walk.json
      hug__a.fbx  hug__b.fbx
      hug.json
      wave.fbx                       (shadowed by the licensed twin)
      female/sit.fbx
      female/sit.json

Expected values, derived by hand from that fixture and the layout rules:

* SEVEN entries: the eight free+licensed files minus the ONE shadowed twin —
  ``wave.fbx`` exists in both libraries and the same rel yields the licensed
  file (licensed wins), so the free wave.fbx is not an entry of its own.
* ``walk.json`` says fps 30 / frames 90, hence duration_s = 90/30 = 3.0 s;
  ``walk_02.fbx`` is a numbering variant of the SAME kind "walk" and therefore
  reports the same 3.0 s / 30 / 90 from that one shared sidecar.
* ``loop`` is true for walk (top-level ``loop: true``) and for hug (only
  ``geometry.loop`` is set), false for sit (``loop: false``) and for dance
  (no sidecar at all).
* ``origin``: walk.json carries a CMU database string -> "cmu"; hug.json and
  sit.json carry ``source.bone_map`` -> "unity-humanoid"; dance.fbx has no
  sidecar -> "unknown".
* Deleting ``walk.fbx`` leaves 1 file of kind walk (walk_02.fbx), so walk.json
  STAYS; deleting walk_02.fbx afterwards leaves 0, so walk.json goes.
* Deleting ``hug__a.fbx`` deletes 2 files (both halves) and hug.json with them.
* Renaming walk -> stroll while walk_02.fbx stays behind: walk.json is COPIED
  to stroll.json (kind rewritten to "stroll"), the original keeps kind "walk".
* Moving female/sit.fbx to the root moves sit.json with it (nothing of kind
  sit is left in female/) and removes the then-empty female/ directory.

Usage:  ./.venv/bin/python scripts/smoke_clip_library.py
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FREE = Path(tempfile.mkdtemp(prefix="clip-lib-free-"))
LICENSED = Path(tempfile.mkdtemp(prefix="clip-lib-licensed-"))
WORLD = Path(tempfile.mkdtemp(prefix="clip-lib-world-"))
# MUST be set before paths is imported — otherwise the smoke would edit the
# repo's real clip libraries.
os.environ["ANIMATION_CLIPS_DIR"] = str(FREE)
os.environ["ANIMATION_CLIPS_LICENSED_DIR"] = str(LICENSED)

from app.core import paths  # noqa: E402

paths.init(WORLD)

from app.core import animation_clips as ac  # noqa: E402

FAILURES = []

CMU_DB = "CMU Graphics Lab Motion Capture Database (mocap.cs.cmu.edu)"


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'OK ' if ok else 'FAIL'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


def raises(label: str, exc, fn) -> None:
    """The call must raise exactly this error class."""
    try:
        fn()
    except exc as e:
        check(label, True, type(e).__name__)
    except Exception as e:                                   # wrong class
        check(label, False, f"raised {type(e).__name__}: {e}")
    else:
        check(label, False, "no error raised")


def write_sidecar(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def build_tree() -> None:
    """(Re)builds the fixture from scratch — every test group starts clean."""
    for root in (FREE, LICENSED):
        shutil.rmtree(root, ignore_errors=True)
        root.mkdir(parents=True, exist_ok=True)

    (FREE / "walk.fbx").write_bytes(b"free-walk")
    (FREE / "walk_02.fbx").write_bytes(b"free-walk-2")
    write_sidecar(FREE / "walk.json", {
        "kind": "walk", "pair": False, "fps": 30, "frames": 90,
        "duration_s": 3.0, "loop": True,
        "geometry": {"in_place": True},
        "source": {"database": CMU_DB, "takes": ["07_01"]}})

    (FREE / "hug__a.fbx").write_bytes(b"free-hug-a")
    (FREE / "hug__b.fbx").write_bytes(b"free-hug-b")
    write_sidecar(FREE / "hug.json", {
        "kind": "hug", "pair": True, "roles": ["a", "b"], "fps": 30,
        "frames": 60, "duration_s": 2.0,
        "geometry": {"loop": {"min_s": 2.0}, "anchor_frame": 30},
        "source": {"format": "fbx", "bone_map": "unity-humanoid"}})

    (FREE / "wave.fbx").write_bytes(b"free-wave")          # shadowed twin

    (FREE / "female").mkdir()
    (FREE / "female" / "sit.fbx").write_bytes(b"free-female-sit")
    write_sidecar(FREE / "female" / "sit.json", {
        "kind": "sit", "pair": False, "fps": 24, "frames": 48,
        "duration_s": 2.0, "loop": False, "geometry": {"in_place": True},
        "source": {"format": "fbx", "bone_map": "unity-humanoid"}})

    (LICENSED / "wave.fbx").write_bytes(b"licensed-wave")
    write_sidecar(LICENSED / "wave.json", {
        "kind": "wave", "pair": False, "fps": 30, "frames": 45,
        "duration_s": 1.5, "loop": False, "geometry": {},
        "source": {"format": "fbx", "bone_map": "unity-humanoid"}})
    (LICENSED / "dance.fbx").write_bytes(b"licensed-dance")


def views_by_rel() -> dict:
    return {(e["source"], e["rel"]): ac.clip_view(e) for e in ac.clip_entries()}


def test_listing() -> None:
    print("\nListing — the fields the library view reads")
    build_tree()
    views = views_by_rel()
    check("7 entries (8 files, the free wave.fbx shadowed by the licensed one)",
          len(views) == 7, str(sorted(r for _s, r in views)))
    check("licensed wins for wave.fbx",
          ("licensed", "wave.fbx") in views and ("free", "wave.fbx") not in views)

    walk = views[("free", "walk.fbx")]
    check("walk: 90 frames / 30 fps = 3.0 s",
          (walk["duration_s"], walk["fps"], walk["frames"]) == (3.0, 30, 90),
          str((walk["duration_s"], walk["fps"], walk["frames"])))
    check("walk: loop true, sidecar present, origin cmu",
          (walk["loop"], walk["has_sidecar"], walk["origin"])
          == (True, True, "cmu"), str(walk["origin"]))
    check("walk: rel/library/url",
          (walk["rel"], walk["library"], walk["source"], walk["url"])
          == ("walk.fbx", "free", "free", "/assets/animation-clips/walk.fbx"),
          walk["url"])

    variant = views[("free", "walk_02.fbx")]
    check("walk_02 shares the walk sidecar (kind walk, 3.0 s)",
          (variant["kind"], variant["duration_s"], variant["fps"])
          == ("walk", 3.0, 30), str(variant["duration_s"]))

    hug = views[("free", "hug__a.fbx")]
    check("hug__a: role a, loop from geometry.loop, origin unity-humanoid",
          (hug["role"], hug["loop"], hug["origin"], hug["duration_s"])
          == ("a", True, "unity-humanoid", 2.0), str(hug["origin"]))

    dance = views[("licensed", "dance.fbx")]
    check("dance without sidecar: numbers null, loop false, origin unknown",
          (dance["duration_s"], dance["fps"], dance["frames"], dance["loop"],
           dance["has_sidecar"], dance["origin"])
          == (None, None, None, False, False, "unknown"),
          str(dance["duration_s"]))
    check("dance url carries the licensed/ prefix",
          dance["url"] == "/assets/animation-clips/licensed/dance.fbx",
          dance["url"])

    sit = views[("free", "female/sit.fbx")]
    check("female/sit: set female, rel with directory, loop false",
          (sit["set"], sit["rel"], sit["loop"], sit["duration_s"])
          == ("female", "female/sit.fbx", False, 2.0), sit["rel"])
    check("female/sit url carries the set segment",
          sit["url"] == "/assets/animation-clips/female/sit.fbx", sit["url"])


def test_delete() -> None:
    print("\nDelete — pair halves and the shared sidecar")
    build_tree()
    res = ac.delete_clip("free", "walk.fbx")
    check("delete walk.fbx removes exactly that file",
          res["deleted"] == ["walk.fbx"] and not (FREE / "walk.fbx").exists(),
          str(res["deleted"]))
    check("walk.json STAYS while walk_02.fbx is left",
          (FREE / "walk.json").is_file() and (FREE / "walk_02.fbx").is_file()
          and res["sidecar_removed"] is False)

    res = ac.delete_clip("free", "walk_02.fbx")
    check("deleting the last variant takes walk.json with it",
          not (FREE / "walk.json").exists() and res["sidecar_removed"] is True)

    res = ac.delete_clip("free", "hug__a.fbx")
    check("deleting one pair half deletes BOTH halves + the sidecar",
          res["deleted"] == ["hug__a.fbx", "hug__b.fbx"]
          and not (FREE / "hug__b.fbx").exists()
          and not (FREE / "hug.json").exists(), str(res["deleted"]))

    res = ac.delete_clip("free", "female/sit.fbx")
    check("a set clip reports its set and takes its sidecar",
          (res["set"], res["kind"], res["deleted"])
          == ("female", "sit", ["female/sit.fbx"])
          and not (FREE / "female" / "sit.json").exists(), str(res))

    res = ac.delete_clip("licensed", "wave.fbx")
    check("the licensed library is deleted from independently",
          not (LICENSED / "wave.fbx").exists() and (FREE / "wave.fbx").is_file(),
          str(res["library"]))

    raises("delete of a missing file -> ClipNotFound", ac.ClipNotFound,
           lambda: ac.delete_clip("free", "nope.fbx"))
    raises("delete with a path escape -> ClipLibraryError", ac.ClipLibraryError,
           lambda: ac.delete_clip("free", "../walk.fbx"))
    raises("delete from an unknown library -> ClipLibraryError",
           ac.ClipLibraryError, lambda: ac.delete_clip("trial", "walk.fbx"))
    raises("delete of a non-clip file -> ClipLibraryError", ac.ClipLibraryError,
           lambda: ac.delete_clip("free", "walk.json"))


def test_rename_kind() -> None:
    print("\nRename — the kind, the sidecar and its kind field")
    build_tree()
    clips = ac.rename_clip("free", "walk.fbx", kind="stroll")
    check("one clip comes back, renamed",
          len(clips) == 1 and clips[0]["kind"] == "stroll"
          and clips[0]["rel"] == "stroll.fbx", str([c["rel"] for c in clips]))
    check("the file moved", (FREE / "stroll.fbx").is_file()
          and not (FREE / "walk.fbx").exists())
    check("the sidecar was COPIED (walk_02.fbx still needs walk.json)",
          (FREE / "stroll.json").is_file() and (FREE / "walk.json").is_file())
    new = json.loads((FREE / "stroll.json").read_text(encoding="utf-8"))
    old = json.loads((FREE / "walk.json").read_text(encoding="utf-8"))
    check("the copy carries the new kind, the original the old one",
          (new["kind"], old["kind"]) == ("stroll", "walk"),
          f"{new['kind']} / {old['kind']}")
    check("the renamed clip reads the copied numbers (3.0 s)",
          clips[0]["duration_s"] == 3.0 and clips[0]["origin"] == "cmu",
          str(clips[0]["duration_s"]))

    clips = ac.rename_clip("free", "hug__a.fbx", kind="cuddle")
    check("a pair renames both halves at once",
          sorted(c["rel"] for c in clips) == ["cuddle__a.fbx", "cuddle__b.fbx"],
          str(sorted(c["rel"] for c in clips)))
    check("nothing of the old kind is left, so the sidecar MOVED",
          (FREE / "cuddle.json").is_file() and not (FREE / "hug.json").exists()
          and json.loads((FREE / "cuddle.json").read_text(
              encoding="utf-8"))["kind"] == "cuddle")

    clips = ac.rename_clip("free", "walk_02.fbx", kind="stroll")
    check("a numbering variant keeps its _02",
          [c["rel"] for c in clips] == ["stroll_02.fbx"]
          and (FREE / "stroll_02.fbx").is_file(), str([c["rel"] for c in clips]))
    check("the target sidecar stays the one that was already there",
          json.loads((FREE / "stroll.json").read_text(
              encoding="utf-8"))["kind"] == "stroll"
          and not (FREE / "walk.json").exists())


def test_move_set() -> None:
    print("\nMove — between sets and between libraries")
    build_tree()
    clips = ac.rename_clip("free", "wave.fbx", cset="male")
    check("moving into a new set creates the directory",
          (FREE / "male" / "wave.fbx").is_file()
          and not (FREE / "wave.fbx").exists()
          and clips[0]["rel"] == "male/wave.fbx", clips[0]["rel"])
    check("the moved clip reports its set and url",
          (clips[0]["set"], clips[0]["url"])
          == ("male", "/assets/animation-clips/male/wave.fbx"), clips[0]["url"])

    clips = ac.rename_clip("free", "female/sit.fbx", cset="")
    check("moving to the root moves the sidecar along",
          (FREE / "sit.fbx").is_file() and (FREE / "sit.json").is_file()
          and clips[0]["rel"] == "sit.fbx", clips[0]["rel"])
    check("the emptied set directory is gone", not (FREE / "female").exists())

    clips = ac.rename_clip("free", "walk.fbx", to_library="licensed")
    check("free -> licensed moves the file into the other library",
          (LICENSED / "walk.fbx").is_file() and not (FREE / "walk.fbx").exists()
          and clips[0]["library"] == "licensed", clips[0]["library"])
    check("the licensed url prefix comes with it",
          clips[0]["url"] == "/assets/animation-clips/licensed/walk.fbx",
          clips[0]["url"])
    check("walk_02.fbx stays behind and keeps its sidecar, the copy went along",
          (FREE / "walk_02.fbx").is_file() and (FREE / "walk.json").is_file()
          and (LICENSED / "walk.json").is_file())


def test_validation() -> None:
    print("\nValidation — collisions, escapes, bad names")
    build_tree()
    raises("renaming onto an existing file -> ClipExists", ac.ClipExists,
           lambda: ac.rename_clip("licensed", "dance.fbx", kind="wave"))
    raises("renaming a missing file -> ClipNotFound", ac.ClipNotFound,
           lambda: ac.rename_clip("free", "nope.fbx", kind="walk"))
    raises("path escape -> ClipLibraryError", ac.ClipLibraryError,
           lambda: ac.rename_clip("free", "../walk.fbx", kind="walk"))
    raises("absolute path -> ClipLibraryError", ac.ClipLibraryError,
           lambda: ac.rename_clip("free", "/etc/passwd", kind="walk"))
    raises("uppercase/punctuation in the kind -> ClipLibraryError",
           ac.ClipLibraryError,
           lambda: ac.rename_clip("free", "walk.fbx", kind="Walk!"))
    raises("the pair separator in the kind -> ClipLibraryError",
           ac.ClipLibraryError,
           lambda: ac.rename_clip("free", "walk.fbx", kind="walk__a"))
    raises("a slash in the kind -> ClipLibraryError", ac.ClipLibraryError,
           lambda: ac.rename_clip("free", "walk.fbx", kind="a/b"))
    raises("an empty kind -> ClipLibraryError", ac.ClipLibraryError,
           lambda: ac.rename_clip("free", "walk.fbx", kind=""))
    raises("a space in the set -> ClipLibraryError", ac.ClipLibraryError,
           lambda: ac.rename_clip("free", "walk.fbx", cset="my set"))
    raises("an unknown target library -> ClipLibraryError", ac.ClipLibraryError,
           lambda: ac.rename_clip("free", "walk.fbx", to_library="trial"))
    # Spaces are part of the kind alphabet on purpose — clip files whose name
    # is a short phrase exist, so a rename must not refuse one.
    check("a kind with a space is legal",
          ac.rename_clip("free", "walk.fbx", kind="climbing a ladder"
                         )[0]["kind"] == "climbing a ladder")
    check("nothing was moved by the refused calls",
          not (FREE / "walk__a.fbx").exists()
          and (FREE / "walk_02.fbx").is_file())


def main() -> int:
    check("ANIMATION_CLIPS_DIR is honoured",
          paths.get_animation_clips_dir() == FREE,
          str(paths.get_animation_clips_dir()))
    check("ANIMATION_CLIPS_LICENSED_DIR is honoured",
          paths.get_licensed_clips_dir() == LICENSED,
          str(paths.get_licensed_clips_dir()))
    test_listing()
    test_delete()
    test_rename_kind()
    test_move_set()
    test_validation()
    print(f"\n{'FAILED: ' + ', '.join(FAILURES) if FAILURES else 'all checks passed'}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        shutil.rmtree(FREE, ignore_errors=True)
        shutil.rmtree(LICENSED, ignore_errors=True)
        shutil.rmtree(WORLD, ignore_errors=True)
