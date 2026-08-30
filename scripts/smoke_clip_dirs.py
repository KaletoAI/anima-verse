#!/usr/bin/env python3
"""Smoke run for the directory-based animation-clip sets (Block K).

Builds a throwaway clip tree and points ANIMATION_CLIPS_DIR at it — the real
shared/models/clips is never touched. Covers the discovery
(app/core/animation_clips.py), the listing URLs and the serving-path
validation (app/routes/assets.py), and — part [8] — that a MISSING clip
library breaks nothing beyond "no animations play".

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
    # A hyphenated kind, so the derived lists prove the rule too and not only
    # the parser unit above: this is ONE kind called "swim-idle".
    (CLIPS / "swim-idle.fbx").write_bytes(b"root-swim-idle")
    # Ignored: not a clip extension, hidden file, hidden directory, and a
    # second nesting level (only ONE level of sets exists).
    (CLIPS / "README.md").write_text("not a clip", encoding="utf-8")
    (CLIPS / ".DS_Store").write_bytes(b"junk")
    (CLIPS / ".hidden").mkdir()
    (CLIPS / ".hidden" / "walk.fbx").write_bytes(b"hidden")
    (CLIPS / "male" / "deeper").mkdir()
    (CLIPS / "male" / "deeper" / "walk.fbx").write_bytes(b"too-deep")
    # A PAIR clip: two halves of ONE kind "hug" + its sidecar, and a lone half
    # ("kiss__a" without a "kiss__b") that must not count as a pair.
    (CLIPS / "hug__a.fbx").write_bytes(b"hug-a")
    (CLIPS / "hug__b.fbx").write_bytes(b"hug-b")
    (CLIPS / "hug.json").write_text(
        '{"kind": "hug", "pair": true, "fps": 30, "frames": 60, "duration_s": 2.0,'
        ' "geometry": {"root_distance_m": 0.5}}', encoding="utf-8")
    (CLIPS / "kiss__a.fbx").write_bytes(b"kiss-a-only")


def test_parse() -> None:
    """The KIND rule itself, hand-derived from the layout ``[<set>/]<kind>[_<n>]``.

    The kind is the whole stem minus a trailing ``_<number>``; hyphens and
    inner underscores BELONG to it. Everything below is derived from that one
    sentence, not recorded from the output:

        walk.fbx            -> walk              (nothing to cut)
        walk_2.fbx          -> walk              (the numbering suffix)
        walk_02.fbx         -> walk              (leading zero, same suffix)
        Walk_02.FBX         -> walk              (lower-cased, suffix stripped)
        swim-idle.fbx       -> swim-idle         (a hyphen is part of the kind)
        treading-water.fbx  -> treading-water
        spell_casting.fbx   -> spell_casting     (an inner underscore stays)
        circle-crunch_2.fbx -> circle-crunch     (both rules at once)
        sit_a.fbx           -> sit_a             (only DIGITS are a numbering)
        walk2.fbx           -> walk2             (no underscore, no suffix)
        "  walk .fbx"       -> walk              (the name is trimmed)
        _7.fbx              -> _7                (cutting it would leave
                                                  nothing — the stem stands)
    """
    print("\n[0] parse_clip_name — the kind is the file name, minus _<number>")
    for name, want in [
        ("walk.fbx", "walk"),
        ("walk_2.fbx", "walk"),
        ("walk_02.fbx", "walk"),
        ("Walk_02.FBX", "walk"),
        ("swim-idle.fbx", "swim-idle"),
        ("treading-water.fbx", "treading-water"),
        ("spell_casting.fbx", "spell_casting"),
        ("circle-crunch_2.fbx", "circle-crunch"),
        ("sit_a.fbx", "sit_a"),
        ("walk2.fbx", "walk2"),
        ("  walk .fbx", "walk"),
        ("_7.fbx", "_7"),
    ]:
        got = ac.parse_clip_name(name)
        check(f"{name} -> {want}", got == want, got)

    # RED COUNTER-PROBE: the bug this rule replaces was a split at the first
    # separator. Re-run that old rule here — it must DISAGREE on exactly the
    # names the finding was about, otherwise this smoke would pass with the
    # bug still in place.
    def old_split(filename: str) -> str:
        import re
        stem = Path(filename).stem.strip().lower()
        tokens = [t for t in re.split(r"[\s_\-.]+", stem) if t]
        return tokens[0] if tokens else stem

    for name, old in [("swim-idle.fbx", "swim"),
                      ("treading-water.fbx", "treading"),
                      ("spell_casting.fbx", "spell")]:
        check(f"RED PROBE: the old split filed {name} as {old!r}",
              old_split(name) == old and ac.parse_clip_name(name) != old,
              ac.parse_clip_name(name))
    check("RED PROBE: and the two rules still agree on walk_2.fbx",
          old_split("walk_2.fbx") == ac.parse_clip_name("walk_2.fbx") == "walk")


def test_discovery() -> None:
    print("\n[1] clip_entries()")
    entries = ac.clip_entries()
    got = sorted((e["set"], e["kind"], e["path"].name) for e in entries)
    check("exactly the seven real clips are found", len(entries) == 7, str(got))
    check("the root clip has the empty set", ("", "sit", "sit.fbx") in got)
    check("a hyphen is part of the kind, not a separator",
          ("", "swim-idle", "swim-idle.fbx") in got)
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
    check("clip_kinds lists a pair kind ONCE, a lone half too",
          ac.clip_kinds() == ["dance", "hug", "kiss", "sit", "swim-idle"],
          str(ac.clip_kinds()))
    check("clip_sets", ac.clip_sets() == ["lady", "male"], str(ac.clip_sets()))
    check("clip_files returns the same files",
          len(ac.clip_files()) == 7
          and all(isinstance(p, Path) for p in ac.clip_files()))

    print("\n[2b] pair clips")
    for name, want in (("hug__a.fbx", ("hug", "a")), ("hug__b_02.fbx", ("hug", "b")),
                       ("spell_casting.fbx", ("spell_casting", "")),
                       ("x__c.fbx", ("x__c", "")), ("__a.fbx", ("__a", ""))):
        check(f"parse_clip_role({name}) == {want}", ac.parse_clip_role(name) == want,
              str(ac.parse_clip_role(name)))
    roles = sorted((e["kind"], e["role"]) for e in ac.clip_entries() if e["role"])
    check("entries carry the role", roles == [("hug", "a"), ("hug", "b"), ("kiss", "a")],
          str(roles))
    check("pair_kinds needs BOTH halves", ac.pair_kinds() == ["hug"], str(ac.pair_kinds()))
    meta = ac.clip_meta("hug") or {}
    check("clip_meta reads the sidecar", meta.get("duration_s") == 2.0
          and meta.get("geometry", {}).get("root_distance_m") == 0.5, str(meta))
    check("clip_meta is None without a sidecar", ac.clip_meta("sit") is None)

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
    check("the payload shape",
          set(data) == {"clips", "kinds", "pair_kinds", "pairs", "clip_sets", "sets"},
          str(sorted(data)))
    check("per-clip fields",
          set(data["clips"][0]) == {"kind", "role", "set", "source", "library",
                                    "rel", "name", "filename", "url", "size",
                                    "has_sidecar", "origin", "duration_s",
                                    "fps", "frames", "loop"},
          str(sorted(data["clips"][0])))
    check("pairs carries the sidecar of every complete pair",
          data["pair_kinds"] == ["hug"] and data["pairs"]["hug"]["duration_s"] == 2.0
          and data["pairs"]["hug"]["geometry"]["root_distance_m"] == 0.5,
          str(data["pairs"]))
    check("a pair half's URL is the plain file",
          "/assets/animation-clips/hug__b.fbx" in urls)
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


def test_licensed() -> None:
    """The second library: `<ANIMATION_CLIPS_DIR>-licensed` (no second env var
    set here). Hand-derived: a licensed `walk.fbx` is a NEW kind in the union;
    a licensed `sit.fbx` SHADES the free root sit (same rel) — the entry's
    source flips to licensed, its url gets the `licensed/` prefix, and the
    free file keeps serving nothing; `male/sit.fbx` (free only) stays free.
    Serving: `licensed/walk.fbx` and `licensed/male/x.fbx` resolve inside the
    licensed dir, `licensed/../sit.fbx` and a third segment are refused."""
    print("\n[7] the licensed library")
    lic = Path(str(CLIPS) + "-licensed")
    check("licensed dir derives from ANIMATION_CLIPS_DIR",
          paths.get_licensed_clips_dir() == lic, str(paths.get_licensed_clips_dir()))
    lic.mkdir()
    (lic / "walk.fbx").write_bytes(b"lic-walk")
    (lic / "sit.fbx").write_bytes(b"lic-sit")
    (lic / "male").mkdir()
    (lic / "male" / "x.fbx").write_bytes(b"lic-male-x")
    entries = {e["rel"]: e for e in ac.clip_entries()}
    check("walk comes from the licensed library", entries["walk.fbx"]["source"] == "licensed")
    check("the licensed sit shades the free sit (one entry, licensed)",
          entries["sit.fbx"]["source"] == "licensed"
          and entries["sit.fbx"]["path"].read_bytes() == b"lic-sit")
    check("male/sit stays free", entries["male/sit.fbx"]["source"] == "free")
    check("kinds are the union", "x" in ac.clip_kinds() and "walk" in ac.clip_kinds())
    data = assets.list_animation_clips()
    urls = {c["rel"] if "rel" in c else c["url"]: c for c in data["clips"]}
    by_url = {c["url"]: c for c in data["clips"]}
    check("licensed url carries the prefix",
          "/assets/animation-clips/licensed/sit.fbx" in by_url
          and "/assets/animation-clips/sit.fbx" not in by_url, str(sorted(by_url)))
    check("licensed set clip url", "/assets/animation-clips/licensed/male/x.fbx" in by_url)
    del urls
    ok = assets.resolve_clip_path("licensed/walk.fbx")
    check("licensed/walk.fbx resolves into the licensed dir",
          ok is not None and ok.read_bytes() == b"lic-walk")
    ok2 = assets.resolve_clip_path("licensed/male/x.fbx")
    check("licensed/male/x.fbx resolves", ok2 is not None and ok2.is_file())
    check("licensed/../sit.fbx is refused", assets.resolve_clip_path("licensed/../sit.fbx") is None)
    check("a third segment is refused", assets.resolve_clip_path("licensed/male/deep/x.fbx") is None)
    check("plain sit.fbx still resolves into the FREE dir (the file exists there)",
          assets.resolve_clip_path("sit.fbx") == (CLIPS / "sit.fbx").resolve())


def test_no_library() -> None:
    """NO clip library at all — the folder may be emptied or deleted.

    Hand-derived from the one rule "clips are content, the pipeline is not":
    everything that LISTS clips answers with an empty result and nothing
    raises, while everything that CONVERTS clips is unaffected, because its
    reference skeleton lives outside the libraries (``shared/models/rig/``).
    So, with both libraries pointed at directories that do not exist:

        clip_entries / clip_kinds / pair_kinds / clip_sets   []
        clip_meta("hug")                                     None
        available_animation_kinds()                          []
        GET /assets/animation-clips   kinds/pair_kinds/clip_sets [], pairs {},
                                      sets ["animal","female","male"]
                                      (the base sets follow from character
                                      data, not from files)
        resolve_clip_path("sit.fbx")  a path that is not a file (route: 404)
        cmu_import.default_rig()      the reference skeleton, unchanged

    and with the reference skeleton itself gone, ``default_rig()`` raises —
    it never falls back onto a clip or a figure.
    """
    print("\n[8] no clip library at all")
    from app.core import cmu_import, expression_pose_maps as epm
    free, lic = os.environ["ANIMATION_CLIPS_DIR"], os.environ.get(
        "ANIMATION_CLIPS_LICENSED_DIR", "")
    rig = CLIPS.parent / "rig-smoke-reference.fbx"
    # Not a real FBX: default_rig() only decides whether the file is THERE.
    rig.write_bytes(b"reference-skeleton-stand-in")
    os.environ["ANIMATION_CLIPS_DIR"] = str(CLIPS) + "-gone"
    os.environ["ANIMATION_CLIPS_LICENSED_DIR"] = str(CLIPS) + "-gone-licensed"
    os.environ["ANIMATION_RIG_FILE"] = str(rig)
    try:
        check("clip_entries is empty, not an error", ac.clip_entries() == [])
        check("no kinds, no pairs, no sets",
              ac.clip_kinds() == [] and ac.pair_kinds() == [] and ac.clip_sets() == [])
        check("clip_meta finds no sidecar", ac.clip_meta("hug") is None)
        check("available_animation_kinds is empty",
              epm.available_animation_kinds() == [])
        data = assets.list_animation_clips()
        check("the listing route answers empty",
              data["clips"] == [] and data["kinds"] == []
              and data["pair_kinds"] == [] and data["pairs"] == {}
              and data["clip_sets"] == [], str(data["kinds"]))
        check("the base sets survive without a single file",
              data["sets"] == ["animal", "female", "male"], str(data["sets"]))
        missing = assets.resolve_clip_path("sit.fbx")
        check("a clip request resolves but is not there (404, not 500)",
              missing is not None and not missing.is_file())
        check("default_rig() is unaffected — it is not in a library",
              cmu_import.default_rig() == rig, str(cmu_import.default_rig()))
        rig.unlink()
        try:
            cmu_import.default_rig()
            check("without the reference skeleton default_rig() raises", False)
        except cmu_import.ClipImportError as e:
            check("without the reference skeleton default_rig() raises",
                  "reference skeleton missing" in str(e), str(e))
    finally:
        os.environ["ANIMATION_CLIPS_DIR"] = free
        if lic:
            os.environ["ANIMATION_CLIPS_LICENSED_DIR"] = lic
        else:
            os.environ.pop("ANIMATION_CLIPS_LICENSED_DIR", None)
        os.environ.pop("ANIMATION_RIG_FILE", None)
        rig.unlink(missing_ok=True)


def main() -> int:
    build_tree()
    check("ANIMATION_CLIPS_DIR is honoured",
          paths.get_animation_clips_dir() == CLIPS,
          str(paths.get_animation_clips_dir()))
    test_parse()
    test_discovery()
    test_listing()
    test_serving()
    test_licensed()
    test_no_library()
    print(f"\n{'FAILED: ' + ', '.join(FAILURES) if FAILURES else 'all checks passed'}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        shutil.rmtree(CLIPS, ignore_errors=True)
        shutil.rmtree(str(CLIPS) + "-licensed", ignore_errors=True)
        shutil.rmtree(WORLD, ignore_errors=True)
