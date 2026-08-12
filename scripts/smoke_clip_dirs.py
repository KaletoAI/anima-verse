#!/usr/bin/env python3
"""Smoke run for the directory-based animation-clip sets (Block K).

Builds a throwaway clip tree and points ANIMATION_CLIPS_DIR at it — the real
shared/models/clips is never touched. Covers the discovery
(app/core/animation_clips.py), the listing URLs and the serving-path
validation (app/routes/assets.py).

Usage:  ./.venv/bin/python scripts/smoke_clip_dirs.py
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

CLIPS = Path(tempfile.mkdtemp(prefix="clip-dirs-smoke-"))
WORLD = Path(tempfile.mkdtemp(prefix="clip-dirs-world-"))
# MUST be set before paths is imported/initialised — otherwise the smoke would
# scan the repo's real clip library.
os.environ["ANIMATION_CLIPS_DIR"] = str(CLIPS)

from app.core import paths  # noqa: E402

paths.init(WORLD)

from app.core import animation_clips as ac  # noqa: E402
from app.routes import assets  # noqa: E402

FAILURES = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


def build_tree() -> None:
    """Root clip + two set directories + the things discovery must ignore."""
    (CLIPS / "sit.fbx").write_bytes(b"root-sit")
    (CLIPS / "male").mkdir()
    (CLIPS / "male" / "sit.fbx").write_bytes(b"male-sit")
    (CLIPS / "Lady").mkdir()          # directory name is lowercased into the set
    (CLIPS / "Lady" / "dance_02.fbx").write_bytes(b"lady-dance")
    # Ignored: not a clip extension, hidden file, hidden directory, and a
    # second nesting level (only ONE level of sets exists).
    (CLIPS / "README.md").write_text("not a clip", encoding="utf-8")
    (CLIPS / ".DS_Store").write_bytes(b"junk")
    (CLIPS / ".hidden").mkdir()
    (CLIPS / ".hidden" / "walk.fbx").write_bytes(b"hidden")
    (CLIPS / "male" / "deeper").mkdir()
    (CLIPS / "male" / "deeper" / "walk.fbx").write_bytes(b"too-deep")


def test_discovery() -> None:
    print("\n[1] clip_entries()")
    entries = ac.clip_entries()
    got = sorted((e["set"], e["kind"], e["path"].name) for e in entries)
    check("exactly the three real clips are found", len(entries) == 3, str(got))
    check("the root clip has the empty set", ("", "sit", "sit.fbx") in got)
    check("a set clip carries its directory", ("male", "sit", "sit.fbx") in got)
    check("the set is lowercased", ("lady", "dance", "dance_02.fbx") in got)
    check("the trailing number is not part of the kind",
          all(e["kind"] != "dance_02" for e in entries))
    check("non-clip files are ignored",
          all(e["path"].suffix == ".fbx" for e in entries))
    check("hidden files and directories are ignored",
          all(not any(part.startswith(".") for part in e["path"].parts)
              for e in entries))
    check("a second directory level is not scanned",
          all("deeper" not in e["path"].parts for e in entries))

    print("\n[2] the derived lists")
    check("clip_kinds", ac.clip_kinds() == ["dance", "sit"], str(ac.clip_kinds()))
    check("clip_sets", ac.clip_sets() == ["lady", "male"], str(ac.clip_sets()))
    check("clip_files returns the same files",
          len(ac.clip_files()) == 3
          and all(isinstance(p, Path) for p in ac.clip_files()))

    print("\n[3] the same kind exists per set (the chain has something to pick)")
    sits = {e["set"] for e in ac.clip_entries() if e["kind"] == "sit"}
    check("sit.fbx exists neutral AND for male", sits == {"", "male"}, str(sits))


def test_listing() -> None:
    print("\n[4] listing URLs")
    data = assets.list_animation_clips()
    urls = {c["url"] for c in data["clips"]}
    check("a set clip's URL carries the set segment",
          "/assets/animation-clips/male/sit.fbx" in urls, str(sorted(urls)))
    check("a root clip's URL is unchanged",
          "/assets/animation-clips/sit.fbx" in urls)
    check("the lowercased set is used in the URL, not the directory case",
          "/assets/animation-clips/lady/dance_02.fbx" in urls)
    check("the payload shape is unchanged",
          set(data) == {"clips", "kinds", "clip_sets", "sets"}, str(sorted(data)))
    check("per-clip fields are unchanged",
          set(data["clips"][0]) == {"kind", "set", "name", "filename", "url", "size"},
          str(sorted(data["clips"][0])))
    check("clip_sets lists only sets that have clips",
          data["clip_sets"] == ["lady", "male"], str(data["clip_sets"]))
    check("sets merges the base sets with the discovered ones",
          data["sets"] == ["animal", "female", "lady", "male"], str(data["sets"]))


def test_serving() -> None:
    print("\n[5] serving-path validation")
    ok_root = assets.resolve_clip_path("sit.fbx")
    ok_set = assets.resolve_clip_path("male/sit.fbx")
    check("a root clip resolves", ok_root is not None and ok_root.exists())
    check("a set clip resolves", ok_set is not None and ok_set.exists())
    check("the two 'sit' clips are different files",
          ok_root != ok_set and ok_root.read_bytes() != ok_set.read_bytes())

    for bad, why in [
        ("../secrets.json", "parent traversal"),
        ("male/../../secrets.json", "traversal via a set"),
        ("a/b/c.fbx", "three segments"),
        ("male/deeper/walk.fbx", "a real file one level too deep"),
        ("", "empty path"),
        ("male/", "trailing slash"),
        ("/sit.fbx", "leading slash"),
        ("male\\sit.fbx", "backslash separator"),
        ("README.md", "not a clip extension"),
        (".DS_Store", "hidden non-clip"),
    ]:
        check(f"rejected: {why}", assets.resolve_clip_path(bad) is None, repr(bad))

    print("\n[6] a legal path that simply is not there")
    missing = assets.resolve_clip_path("male/nope.fbx")
    check("resolves but does not exist (route answers 404, not 400)",
          missing is not None and not missing.is_file())


def main() -> int:
    build_tree()
    check("ANIMATION_CLIPS_DIR is honoured",
          paths.get_animation_clips_dir() == CLIPS,
          str(paths.get_animation_clips_dir()))
    test_discovery()
    test_listing()
    test_serving()
    print(f"\n{'FAILED: ' + ', '.join(FAILURES) if FAILURES else 'all checks passed'}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        shutil.rmtree(CLIPS, ignore_errors=True)
        shutil.rmtree(WORLD, ignore_errors=True)
