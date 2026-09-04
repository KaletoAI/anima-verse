#!/usr/bin/env python3
"""Smoke run for the LOCOMOTION mapping — which clip kind every figure plays
for the roles walk / run / idle (app/core/animation_clips.py,
``load_locomotion_clips`` / ``save_locomotion_clips``; the route
``PUT /assets/animation-clips/locomotion`` is a thin wrapper over the saver
and ``GET /assets/animation-clips`` delivers the loader's answer as
``locomotion``).

Builds a throwaway FREE library and points ANIMATION_CLIPS_DIR /
ANIMATION_CLIPS_LICENSED_DIR at it BEFORE the app modules are imported, and
hands every load/save a TEMPORARY mapping file — the real
``shared/config/locomotion_clips.json`` is read once, read-only, in the last
group and never written.

The fixture (dummy .fbx bytes, no sidecars needed):

    free/
      walk.fbx  run.fbx  idle.fbx        the three default kinds
      stroll.fbx                          a solo alternative for "walk"
      jog_02.fbx                          kind "jog" (only a numbered variant)
      hug__a.fbx  hug__b.fbx              a PAIR kind — no solo file
      female/sit.fbx                      a set clip, kind "sit"

Expected values, derived by hand from the fixture and the rules:

* NO mapping file → the resolved mapping is the identity
  ``{walk: walk, run: run, idle: idle}`` — every role is its own default.
* A file ``{"walk": "stroll", "run": "", "idle": null, "fly": "x"}`` resolves
  to ``{walk: stroll, run: run, idle: idle}``: an empty string and a
  non-string are both "default", an unknown key is ignored on READ.
* A junk file (``[1, 2]`` / unparsable text) resolves to the identity —
  a broken file must never leave every figure without a walk.
* Saving ``{"run": "jog"}`` onto the file above answers
  ``{walk: stroll, run: jog, idle: idle}`` — MERGE, the untouched walk stays
  "stroll"; ``jog`` counts as existing although only ``jog_02.fbx`` exists,
  because the kind of a numbered variant is the stem without ``_02``.
* The written file then holds exactly the three roles
  ``{"walk": "stroll", "run": "jog", "idle": ""}`` — the junk key "fly" is
  dropped, the untouched idle stays the empty default.
* Saving ``{"walk": " Stroll "}`` normalises to "stroll" (trim + lowercase).
* Saving ``{"idle": "sit"}`` succeeds — the kind exists in the ``female`` set,
  a set clip counts as existing.
* Saving ``{"walk": ""}`` and ``{"walk": None}`` both reset walk to its
  default "walk" WITHOUT checking the library, and the file stores ``""``.
* Refused with ClipLibraryError (route: 400): a kind no file backs
  (``{"idle": "nope"}``), a PAIR kind (``{"idle": "hug"}``), an unknown role
  (``{"fly": "walk"}``), a non-string kind (``{"run": 3}``), a kind outside
  the rename alphabet (``{"run": "wa__lk"}``, ``{"run": "run_02"}``), and a
  non-object body (``["walk"]``). None of them changes the file: the mapping
  after the refused calls is still the one before them.
* The REAL ``shared/config/locomotion_clips.json`` parses as an object whose
  keys are all known roles (read-only check).

Usage:  ./.venv/bin/python scripts/smoke_locomotion_clips.py
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FREE = Path(tempfile.mkdtemp(prefix="loco-free-"))
LICENSED = Path(tempfile.mkdtemp(prefix="loco-licensed-"))
WORLD = Path(tempfile.mkdtemp(prefix="loco-world-"))
CONF = Path(tempfile.mkdtemp(prefix="loco-conf-"))
# MUST be set before paths is imported — otherwise the smoke would read the
# repo's real clip libraries.
os.environ["ANIMATION_CLIPS_DIR"] = str(FREE)
os.environ["ANIMATION_CLIPS_LICENSED_DIR"] = str(LICENSED)

from app.core import paths  # noqa: E402

paths.init(WORLD)

from app.core import animation_clips as ac  # noqa: E402

FAILURES = []
MAPPING = CONF / "locomotion_clips.json"
IDENTITY = {"walk": "walk", "run": "run", "idle": "idle"}


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


def build_tree() -> None:
    for root in (FREE, LICENSED):
        shutil.rmtree(root, ignore_errors=True)
        root.mkdir(parents=True, exist_ok=True)
    for name in ("walk", "run", "idle", "stroll", "jog_02", "hug__a", "hug__b"):
        (FREE / f"{name}.fbx").write_bytes(b"clip")
    (FREE / "female").mkdir()
    (FREE / "female" / "sit.fbx").write_bytes(b"clip")


def load() -> dict:
    return ac.load_locomotion_clips(MAPPING)


def save(changes) -> dict:
    return ac.save_locomotion_clips(changes, MAPPING)


def stored() -> dict:
    return json.loads(MAPPING.read_text(encoding="utf-8"))


def test_load() -> None:
    print("\n[load]")
    MAPPING.unlink(missing_ok=True)
    check("no file -> identity", load() == IDENTITY, str(load()))

    MAPPING.write_text(json.dumps({"walk": "stroll", "run": "", "idle": None,
                                   "fly": "x"}), encoding="utf-8")
    got = load()
    check("empty / None / unknown key resolve to the defaults",
          got == {"walk": "stroll", "run": "run", "idle": "idle"}, str(got))

    MAPPING.write_text("[1, 2]", encoding="utf-8")
    check("a list is junk -> identity", load() == IDENTITY, str(load()))
    MAPPING.write_text("{not json", encoding="utf-8")
    check("unparsable text -> identity", load() == IDENTITY, str(load()))


def test_save() -> None:
    print("\n[save]")
    MAPPING.write_text(json.dumps({"walk": "stroll", "run": "", "idle": None,
                                   "fly": "x"}), encoding="utf-8")
    got = save({"run": "jog"})
    check("merge: run=jog, walk stays stroll, idle default",
          got == {"walk": "stroll", "run": "jog", "idle": "idle"}, str(got))
    check("file holds exactly the three roles, junk key dropped",
          stored() == {"walk": "stroll", "run": "jog", "idle": ""},
          str(stored()))
    check("the loader agrees with the saver's answer", load() == got)

    got = save({"walk": " Stroll "})
    check("kind is trimmed + lowercased", got["walk"] == "stroll", got["walk"])

    got = save({"idle": "sit"})
    check("a set clip (female/sit) counts as existing", got["idle"] == "sit",
          got["idle"])

    got = save({"walk": ""})
    check("empty string resets walk to its default", got["walk"] == "walk",
          got["walk"])
    check("... and the file stores the empty default", stored()["walk"] == "",
          str(stored()))
    save({"walk": "stroll"})
    got = save({"walk": None})
    check("None resets walk to its default too", got["walk"] == "walk",
          got["walk"])

    # A default that has NO file is still allowed — the client's fallback
    # chain covers it, as it always did.
    (FREE / "run.fbx").unlink()
    got = save({"run": ""})
    check("resetting to a default without a file is allowed",
          got["run"] == "run", got["run"])
    raises("but pointing at the missing 'run' explicitly is refused",
           ac.ClipLibraryError, lambda: save({"run": "run"}))
    (FREE / "run.fbx").write_bytes(b"clip")


def test_validation() -> None:
    print("\n[validation]")
    MAPPING.write_text(json.dumps({"walk": "stroll", "run": "jog", "idle": ""}),
                       encoding="utf-8")
    before = load()
    raises("a kind no file backs", ac.ClipLibraryError,
           lambda: save({"idle": "nope"}))
    raises("a pair kind is no locomotion clip", ac.ClipLibraryError,
           lambda: save({"idle": "hug"}))
    raises("an unknown role", ac.ClipLibraryError,
           lambda: save({"fly": "walk"}))
    raises("a non-string kind", ac.ClipLibraryError,
           lambda: save({"run": 3}))
    raises("the pair separator inside a kind", ac.ClipLibraryError,
           lambda: save({"run": "wa__lk"}))
    raises("a numbering suffix inside a kind", ac.ClipLibraryError,
           lambda: save({"run": "run_02"}))
    raises("a non-object body", ac.ClipLibraryError,
           lambda: save(["walk"]))
    check("nothing changed through the refused calls", load() == before,
          str(load()))
    check("the file is untouched too",
          stored() == {"walk": "stroll", "run": "jog", "idle": ""},
          str(stored()))


def test_real_file() -> None:
    print("\n[repo file, read-only]")
    real = ac.locomotion_clips_path()
    check("shared/config/locomotion_clips.json exists", real.is_file(), str(real))
    try:
        data = json.loads(real.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        check("parses as JSON", False, str(e))
        return
    check("is an object with known roles only",
          isinstance(data, dict)
          and set(data) <= set(ac.LOCOMOTION_ROLES), str(data))
    resolved = ac.load_locomotion_clips()
    check("resolves to a full mapping",
          set(resolved) == set(ac.LOCOMOTION_ROLES)
          and all(resolved.values()), str(resolved))


def main() -> int:
    check("ANIMATION_CLIPS_DIR is honoured",
          paths.get_animation_clips_dir() == FREE,
          str(paths.get_animation_clips_dir()))
    build_tree()
    test_load()
    test_save()
    test_validation()
    test_real_file()
    print(f"\n{'FAILED: ' + ', '.join(FAILURES) if FAILURES else 'all checks passed'}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        for d in (FREE, LICENSED, WORLD, CONF):
            shutil.rmtree(d, ignore_errors=True)
