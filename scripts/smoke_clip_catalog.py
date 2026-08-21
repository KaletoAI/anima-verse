#!/usr/bin/env python3
"""Smoke run for the CMU clip-catalog browser (plan-clip-import.md step 1).

Builds a throwaway trial archive and a throwaway clip library and points
ANIMATION_CLIPS_TRIAL_DIR / ANIMATION_CLIPS_DIR at them — the real
shared/models/clips and shared/models/clips-trial are never touched. Covers
app/core/clip_catalog.py plus the three routes in app/routes/assets.py.

The expectations are derived by hand from the two rules the feature rests on:

RULE 1 — "the trial archive mirrors the CMU category tree, one level deeper
than a clip library". A trial reference is therefore ``<main>/<sub>/<file>``:

    x.fbx                     ok   (1 segment)
    locomotion/x.fbx          ok   (2)
    locomotion/walk/07_01.fbx ok   (3, the real shape)
    a/b/c/d.fbx               NO   (4 — one segment too many)
    ../secrets.json           NO   (traversal)
    locomotion/../../x.fbx    NO   (traversal through a segment)
    locomotion/walk/07_01.txt NO   (not a clip extension)
    ""                        NO   (empty)

  and — the point of the whole separation — a trial clip is in NO library:
  ``/assets/animation-clips`` must not list a single one of them.

RULE 2 — "a kind is a file stem, and one kind exists once per set". So the
import refuses:

    kind "walk__a"  -> 422  (``__`` is the pair role separator)
    kind "a/b"      -> 422  (a path separator would leave the library)
    kind ""         -> 422  (empty)
    kind "idle"     -> 409  when the library already has idle.fbx and
                            overwrite is not set; 200 with overwrite

The Blender run itself is monkeypatched here: this smoke checks the ROUTE
contract (validation, status file, listing entry), not the retargeter. With
``--real <take>`` it additionally runs one true conversion when Blender and
the CMU originals are present.

Usage:
    ./.venv/bin/python scripts/smoke_clip_catalog.py [--real 07_01]
"""
import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

CLIPS = Path(tempfile.mkdtemp(prefix="clip-catalog-clips-"))
TRIAL = Path(tempfile.mkdtemp(prefix="clip-catalog-trial-"))
WORLD = Path(tempfile.mkdtemp(prefix="clip-catalog-world-"))
# MUST be set before paths is imported — otherwise the smoke would read the
# repo's real (gitignored, user-provided) archives.
os.environ["ANIMATION_CLIPS_DIR"] = str(CLIPS)
os.environ["ANIMATION_CLIPS_TRIAL_DIR"] = str(TRIAL)

from app.core import paths  # noqa: E402

paths.init(WORLD)

from fastapi import HTTPException  # noqa: E402

from app.blender import runner  # noqa: E402
from app.core import clip_catalog, cmu_import  # noqa: E402
from app.routes import assets  # noqa: E402

FAILURES = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


def status_of(call) -> int:
    """HTTP status a route call ends with (200 when it returns normally)."""
    try:
        call()
        return 200
    except HTTPException as e:
        return e.status_code


def build_tree() -> None:
    """A trial archive of three takes (one solo converted, one pair, one not
    converted yet) plus a clip library that already holds ``idle``."""
    (CLIPS / "idle.fbx").write_bytes(b"library-idle")

    loco = TRIAL / "locomotion" / "walk"
    loco.mkdir(parents=True)
    (loco / "07_01.fbx").write_bytes(b"trial-07-01")
    inter = TRIAL / "human-interaction" / "two-subjects"
    inter.mkdir(parents=True)
    (inter / "18_01__a.fbx").write_bytes(b"trial-18-01-a")
    (inter / "18_01__b.fbx").write_bytes(b"trial-18-01-b")
    (TRIAL / "notes.txt").write_text("not a clip", encoding="utf-8")

    catalog = {
        "generated": "2026-08-21T00:00:00+00:00",
        "source": "cmu",
        "credit": "The data used in this project was obtained from mocap.cs.cmu.edu.",
        "tags": {"walk": {"label": "Walking", "count": 2}},
        "facets": {"posture": ["standing"], "energy": ["calm"],
                   "travel": ["walks"], "duration": ["short"]},
        "groups": {"walk": {"label": "walk", "take_ids": ["07_01", "09_01"]}},
        "takes": [
            {"id": "07_01", "subject": 7, "trial": 1, "description": "walk",
             "subject_description": "walk", "categories": ["1/1"],
             "category_labels": ["Locomotion / walk"], "tags": ["walk"],
             "group": "walk", "framerate": 120, "duration_s": 3.5, "frames": 420,
             "pair": False, "pair_role": "", "pair_partner": "",
             "clip": "locomotion/walk/07_01.fbx",
             "metrics": {"posture": "standing", "energy": "calm",
                         "travel": "walks", "duration_class": "short",
                         "loop_seam": 0.4, "loopable": True},
             "sparkline": [0.9] * 40},
            {"id": "18_01", "subject": 18, "trial": 1,
             "description": "walk, shake hands (2 subjects - subject A)",
             "subject_description": "human interaction", "categories": ["1/1"],
             "category_labels": ["Human Interaction / two subjects"],
             "tags": ["walk", "two-subjects"], "group": "walk-shake-hands",
             "framerate": 60, "duration_s": 2.5, "frames": 150,
             "pair": True, "pair_role": "a", "pair_partner": "19_01",
             "clip": "human-interaction/two-subjects/18_01__a.fbx",
             "metrics": {"posture": "standing", "energy": "moderate",
                         "travel": "in-place", "duration_class": "short",
                         "loop_seam": 4.4, "loopable": False},
             "sparkline": [0.98] * 40},
            # Measured but NOT converted yet — the partial state the browser
            # has to survive.
            {"id": "09_01", "subject": 9, "trial": 1, "description": "run",
             "subject_description": "run", "categories": ["1/2"],
             "category_labels": ["Locomotion / run"], "tags": ["run"],
             "group": "walk", "framerate": 120, "duration_s": 1.2, "frames": 144,
             "pair": False, "pair_role": "", "pair_partner": "",
             "clip": None,
             "metrics": {"posture": "standing", "energy": "fast",
                         "travel": "travels", "duration_class": "short",
                         "loop_seam": 0.9, "loopable": True},
             "sparkline": [1.0] * 40},
        ],
    }
    (TRIAL / "_catalog.json").write_text(json.dumps(catalog), encoding="utf-8")


def fake_run(script, *, inputs=None, params=None, out_dir=None, timeout_s=0):
    """Stands in for the Blender retargeter: writes the files the real script
    writes (``<kind>.fbx`` or the two halves, plus ``<kind>.json``) and reports
    the same result shape."""
    kind = (params or {}).get("kind", "x")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    pair = "asf_b" in (inputs or {})
    stems = [f"{kind}__a", f"{kind}__b"] if pair else [kind]
    outputs = {}
    for stem in stems:
        p = out / f"{stem}.fbx"
        p.write_bytes(b"fake-" + stem.encode())
        outputs[stem] = str(p)
    side = {"kind": kind, "pair": pair, "fps": params.get("fps"),
            "frames": 90, "duration_s": 3.0,
            "source_takes": params.get("source_takes"),
            "in_place": params.get("in_place"),
            "loop_s": params.get("loop_s"),
            "start_s": params.get("start_s"), "end_s": params.get("end_s"),
            "source_fps": params.get("source_fps")}
    sc = out / f"{kind}.json"
    sc.write_text(json.dumps(side), encoding="utf-8")
    outputs["sidecar"] = str(sc)
    return {"ok": True, "error": "", "data": side, "outputs": outputs,
            "seconds": 0.01}


def test_catalog_route() -> None:
    print("\n[1] GET /assets/clip-catalog — catalog + status merged")
    data = assets.get_clip_catalog(None)
    ids = [k["id"] for k in data["takes"]]
    check("all three takes come through", ids == ["07_01", "18_01", "09_01"], str(ids))
    check("the vocabularies travel along",
          set(data) >= {"tags", "facets", "groups", "takes", "credit"},
          str(sorted(data)))
    blank = data["takes"][0]["status"]
    check("a take with no review state gets the blank one",
          blank == {"favorite": False, "rejected": False, "imported": []}, str(blank))
    check("a take without a converted clip keeps clip=None and no urls",
          data["takes"][2]["clip"] is None and data["takes"][2]["clip_urls"] == {},
          str(data["takes"][2]["clip_urls"]))
    check("a solo take's preview url is its trial path",
          data["takes"][0]["clip_urls"] ==
          {"solo": "/assets/animation-clips/trial/locomotion/walk/07_01.fbx"},
          str(data["takes"][0]["clip_urls"]))
    check("a pair take gets BOTH halves (the b half is derived from the a path)",
          data["takes"][1]["clip_urls"] == {
              "a": "/assets/animation-clips/trial/human-interaction/two-subjects/18_01__a.fbx",
              "b": "/assets/animation-clips/trial/human-interaction/two-subjects/18_01__b.fbx"},
          str(data["takes"][1]["clip_urls"]))


def test_status_route() -> None:
    print("\n[2] PUT /assets/clip-catalog/{take}/status — persisted, field-wise")
    import asyncio

    class Req:
        def __init__(self, body):
            self._body = body

        async def json(self):
            return self._body

    def put(take_id, body):
        return asyncio.run(assets.put_clip_catalog_status(take_id, Req(body), None))

    r = put("07_01", {"favorite": True})
    check("favorite is set", r["status"]["favorite"] is True, str(r))
    check("the status file exists", clip_catalog.status_path().is_file())
    r = put("07_01", {"rejected": True})
    check("rejecting does NOT clear the favorite (independent booleans)",
          r["status"] == {"favorite": True, "rejected": True, "imported": []}, str(r))
    r = put("07_01", {"favorite": False})
    check("un-favoriting leaves the rejection alone",
          r["status"]["favorite"] is False and r["status"]["rejected"] is True, str(r))
    on_disk = json.loads(clip_catalog.status_path().read_text(encoding="utf-8"))
    check("it really is on disk, keyed by take id",
          on_disk["takes"]["07_01"]["rejected"] is True, str(on_disk))
    merged = assets.get_clip_catalog(None)["takes"][0]["status"]
    check("and the catalog route merges it back in",
          merged["rejected"] is True and merged["favorite"] is False, str(merged))
    put("07_01", {"rejected": False})


def test_trial_paths() -> None:
    print("\n[3] trial path validation (RULE 1)")
    for good in ("07_01.fbx", "locomotion/07_01.fbx", "locomotion/walk/07_01.fbx"):
        check(f"accepted: {good}", clip_catalog.resolve_trial_path(good) is not None)
    real = clip_catalog.resolve_trial_path("locomotion/walk/07_01.fbx")
    check("a real trial clip resolves to the file",
          real is not None and real.read_bytes() == b"trial-07-01")
    for bad, why in [
        ("a/b/c/d.fbx", "four segments"),
        ("../secrets.json", "parent traversal"),
        ("locomotion/../../x.fbx", "traversal through a segment"),
        ("", "empty path"),
        ("locomotion/", "trailing slash"),
        ("/x.fbx", "leading slash"),
        ("locomotion\\walk\\x.fbx", "backslash separator"),
        ("notes.txt", "not a clip extension"),
        ("locomotion/walk/07_01.txt", "wrong extension, right depth"),
    ]:
        check(f"rejected: {why}", clip_catalog.resolve_trial_path(bad) is None, repr(bad))

    print("\n[4] a trial clip is in NO library")
    listing = assets.list_animation_clips()
    names = {c["filename"] for c in listing["clips"]}
    check("the clip listing holds only the library clip",
          names == {"idle.fbx"}, str(sorted(names)))
    check("no trial url leaked into the listing",
          not any("trial" in c["url"] for c in listing["clips"]))
    check("and the plain clip route does not reach into the trial archive",
          assets.resolve_clip_path("locomotion/walk/07_01.fbx") is None)


def test_import() -> None:
    print("\n[5] POST /assets/clip-catalog/{take}/import — validation (RULE 2)")
    import asyncio

    class Req:
        def __init__(self, body):
            self._body = body

        async def json(self):
            return self._body

    def imp(take_id, body):
        return asyncio.run(assets.post_clip_catalog_import(take_id, Req(body), None))

    real_run = runner.run
    cmu_import.runner.run = fake_run
    try:
        for kind, why in [("walk__a", "the pair role separator"),
                          ("a/b", "a path separator"),
                          ("", "empty"),
                          ("walk.fbx", "an extension")]:
            code = status_of(lambda: imp("07_01", {"kind": kind}))
            check(f"422 for kind {kind!r} — {why}", code == 422, str(code))
        check("422 for an unknown take",
              status_of(lambda: imp("99_99", {"kind": "walk"})) == 422)
        check("400 for a target other than 'free'",
              status_of(lambda: imp("07_01", {"kind": "walk", "target": "licensed"})) == 400)
        check("409 for a kind the library already has",
              status_of(lambda: imp("07_01", {"kind": "idle"})) == 409)

        print("\n[6] a solo import")
        res = imp("07_01", {"kind": "stroll", "start_s": 0.5, "end_s": 3.0,
                            "loop_s": 1.5, "in_place": True})
        check("the clip file landed in the library",
              (CLIPS / "stroll.fbx").is_file() and (CLIPS / "stroll.json").is_file())
        check("the answer names the new kind and its listing entry",
              res["kind"] == "stroll" and res["clip"]["url"] ==
              "/assets/animation-clips/stroll.fbx", str(res["clip"]))
        side = res["sidecar"]
        check("the window and the loop reached the converter",
              side["start_s"] == 0.5 and side["end_s"] == 3.0 and side["loop_s"] == 1.5,
              str(side))
        check("in_place reached it too", side["in_place"] is True)
        check("the capture rate came from the CATALOG, not the 120 Hz default",
              side["source_fps"] == 120, str(side["source_fps"]))
        check("only this take was converted",
              side["source_takes"] == ["07_01"], str(side["source_takes"]))
        check("the import is recorded on the take",
              [i["kind"] for i in res["status"]["imported"]] == ["stroll"],
              str(res["status"]))
        check("and the library now offers the kind",
              "stroll" in assets.list_animation_clips()["kinds"])

        print("\n[7] overwrite")
        check("409 without the flag",
              status_of(lambda: imp("07_01", {"kind": "stroll"})) == 409)
        again = imp("07_01", {"kind": "stroll", "overwrite": True})
        check("200 with it", again["kind"] == "stroll")
        traces = again["status"]["imported"]
        check("re-importing the same kind REPLACES the trace, it does not stack",
              len(traces) == 1 and traces[0]["kind"] == "stroll", str(traces))

        print("\n[8] a pair import — both halves, one kind")
        res = imp("18_01", {"kind": "handshake", "in_place": True})
        check("both halves were written",
              (CLIPS / "handshake__a.fbx").is_file()
              and (CLIPS / "handshake__b.fbx").is_file())
        check("the answer flags it as a pair", res["pair"] is True, str(res["pair"]))
        check("the A role first, the partner second",
              res["sidecar"]["source_takes"] == ["18_01", "19_01"],
              str(res["sidecar"]["source_takes"]))
        check("in_place is ignored for a pair (the roots carry the contact)",
              res["sidecar"]["in_place"] is False, str(res["sidecar"]["in_place"]))
        check("the 60 Hz capture rate came from the catalog",
              res["sidecar"]["source_fps"] == 60, str(res["sidecar"]["source_fps"]))
        check("the library sees ONE pair kind",
              assets.list_animation_clips()["pair_kinds"] == ["handshake"],
              str(assets.list_animation_clips()["pair_kinds"]))

        print("\n[9] a set import")
        res = imp("07_01", {"kind": "stroll", "set": "female"})
        check("the same kind is free again in another set",
              (CLIPS / "female" / "stroll.fbx").is_file())
        check("its url carries the set segment",
              res["clip"]["url"] == "/assets/animation-clips/female/stroll.fbx",
              str(res["clip"]["url"]))
        traces = res["status"]["imported"]
        check("the take now carries two traces (neutral and female)",
              sorted((i["kind"], i["set"]) for i in traces)
              == [("stroll", ""), ("stroll", "female")], str(traces))
    finally:
        cmu_import.runner.run = real_run


def test_missing_catalog() -> None:
    print("\n[10] no catalog at all")
    path = clip_catalog.catalog_path()
    backup = path.read_bytes()
    path.unlink()
    clip_catalog._catalog_cache["mtime"] = None
    check("404, naming the file to build",
          status_of(lambda: assets.get_clip_catalog(None)) == 404)
    path.write_bytes(backup)
    clip_catalog._catalog_cache["mtime"] = None
    check("and it comes back once the file is there again",
          len(assets.get_clip_catalog(None)["takes"]) == 3)


def test_real(take: str) -> None:
    """One TRUE conversion — only when Blender and the originals are present."""
    print(f"\n[11] real conversion of {take}")
    st = runner.status()
    subject = take.partition("_")[0]
    src = paths.get_mocap_source_dir() / "cmu" / subject / f"{take}.amc"
    # The throwaway library holds a FAKE idle.fbx, so the rig has to be named
    # explicitly — the real library's own skeleton, which is what an import in
    # production would pick.
    repo = Path(__file__).resolve().parents[1]
    rig = next((p for p in [repo / "shared/models/clips/idle.fbx",
                            repo / "shared/models/figure/x-bot.fbx"] if p.is_file()),
               Path("/nonexistent"))
    if not st["executable"] or not src.is_file() or not rig.is_file():
        print(f"  – skipped (blender={bool(st['executable'])}, "
              f"original={src.is_file()}, rig={rig.is_file()})")
        return
    res = cmu_import.convert_take("smoketest", take, out_dir=CLIPS, rig=rig,
                                  start_s=0.0, end_s=2.0, in_place=True)
    side = res["sidecar"]
    check("a clip file was written", (CLIPS / "smoketest.fbx").is_file())
    check("its duration is the requested window (±0.2 s)",
          abs(float(side["duration_s"]) - 2.0) <= 0.2, str(side["duration_s"]))
    check("30 fps out", int(side["fps"]) == 30, str(side["fps"]))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--real", default="", help="take id for a true Blender run")
    a = ap.parse_args()
    build_tree()
    check("ANIMATION_CLIPS_TRIAL_DIR is honoured",
          paths.get_trial_clips_dir() == TRIAL, str(paths.get_trial_clips_dir()))
    test_catalog_route()
    test_status_route()
    test_trial_paths()
    test_import()
    test_missing_catalog()
    if a.real:
        test_real(a.real)
    print(f"\n{'FAILED: ' + ', '.join(FAILURES) if FAILURES else 'all checks passed'}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        shutil.rmtree(CLIPS, ignore_errors=True)
        shutil.rmtree(TRIAL, ignore_errors=True)
        shutil.rmtree(WORLD, ignore_errors=True)
