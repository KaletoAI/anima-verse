#!/usr/bin/env python3
"""Smoke run for the foreign-FBX import inbox (plan-clip-import.md steps 1+3).

Builds a throwaway inbox and two throwaway clip libraries and points
ANIMATION_CLIPS_INBOX_DIR / ANIMATION_CLIPS_DIR / ANIMATION_CLIPS_LICENSED_DIR
at them — the real shared/models/clips*, which hold user-provided binaries
that exist nowhere else, are never touched. Covers app/core/fbx_import.py plus
the four inbox routes in app/routes/assets.py.

The expectations are derived by hand from the four rules the feature rests on:

RULE 1 — "the probe reads NODE NAMES out of the bytes, no Blender". An FBX
keeps its node names as printable ASCII, so a file that contains the four
signature names of a family IS that family:

    contains Hips + Left_UpperLeg + Left_UpperArm + Chest -> unity-humanoid
    contains only Hips/Bone_01/…                          -> "" (unknown rig)
    + Left_IndexProximal                                  -> has_fingers True
    file name contains tpose/t-pose/rest/bind             -> reference pose

  bone_count counts the family's OWN names found: the synthetic file below
  carries 6 of them (Hips, Chest, Left_UpperLeg, Left_UpperArm, Left_Hand,
  Left_IndexProximal), so bone_count == 6 exactly.

RULE 2 — "a pair is two files whose NAMES say so". Female_/Male_, _A/_B,
__a/__b, _L/_R — and only when the partner really lies in the inbox:

    Female_Dance.fbx  + Male_Dance.fbx      -> partner suggested
    take_A.fbx        + take_B.fbx          -> partner suggested
    Female_Solo.fbx   (no Male_Solo.fbx)    -> "" (no suggestion)

RULE 3 — "a kind is a file stem, and one kind exists once per library and
set". So the import refuses ``__``, path separators and an empty kind (422),
and a kind the target library already has (409) unless overwrite is set.

RULE 4 — "a foreign file is licensed until its owner says otherwise". The
default target is the LICENSED library; the free (tracked, redistributable)
one needs redistributable=True — 400 without it.

The Blender run itself is monkeypatched here: this smoke checks the ROUTE and
core contract (probe, suggestions, validation, target rule, what reaches the
converter), not the retargeter. With ``--real`` it additionally runs one TRUE
pair conversion, if the real inbox holds two Female_/Male_ files plus a
reference pose and Blender is installed.

Usage:
    ./.venv/bin/python scripts/smoke_fbx_import.py [--real]
"""
import argparse
import asyncio
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

INBOX = Path(tempfile.mkdtemp(prefix="fbx-import-inbox-"))
FREE = Path(tempfile.mkdtemp(prefix="fbx-import-free-"))
LICENSED = Path(tempfile.mkdtemp(prefix="fbx-import-licensed-"))
WORLD = Path(tempfile.mkdtemp(prefix="fbx-import-world-"))
# MUST be set before paths is imported — otherwise the smoke would write into
# the repo's real (gitignored, user-provided) libraries.
os.environ["ANIMATION_CLIPS_INBOX_DIR"] = str(INBOX)
os.environ["ANIMATION_CLIPS_DIR"] = str(FREE)
os.environ["ANIMATION_CLIPS_LICENSED_DIR"] = str(LICENSED)

from app.core import paths  # noqa: E402

paths.init(WORLD)

from fastapi import HTTPException  # noqa: E402

from app.blender import runner  # noqa: E402
from app.core import fbx_import  # noqa: E402
from app.routes import assets  # noqa: E402

FAILURES = []

#: The four names a unity-humanoid file must carry, plus two more so the bone
#: count and the finger flag have something to find.
UNITY_NAMES = ("Hips", "Chest", "Left_UpperLeg", "Left_UpperArm",
               "Left_Hand", "Left_IndexProximal")


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


def fake_fbx(names, extra: bytes = b"") -> bytes:
    """A byte blob shaped like a binary FBX for the probe: the node names
    separated by the NUL bytes a binary FBX puts between them."""
    body = b"Kaydara FBX Binary  \x00\x1a\x00"
    for name in names:
        body += name.encode() + b"\x00\x01Model\x00"
    return body + extra


def build_inbox() -> None:
    """Six files: a pair (Female_/Male_), an _A/_B pair, a lone Female_ file,
    an unknown rig and a reference pose."""
    for name in ("Female_Dance.fbx", "Male_Dance.fbx", "take_A.fbx",
                 "take_B.fbx", "Female_Solo.fbx"):
        (INBOX / name).write_bytes(fake_fbx(UNITY_NAMES))
    (INBOX / "Tpose.fbx").write_bytes(fake_fbx(UNITY_NAMES))
    (INBOX / "strange.fbx").write_bytes(fake_fbx(("Bone_01", "Bone_02", "Root")))
    (INBOX / "notes.txt").write_text("not a clip", encoding="utf-8")
    # a library the import can collide with
    (LICENSED / "idle.fbx").write_bytes(b"library-idle")


def fake_run(script, *, inputs=None, params=None, out_dir=None, timeout_s=0):
    """Stands in for the Blender retargeter: writes the files the real script
    writes (``<kind>.fbx`` or the two halves, plus ``<kind>.json``) and reports
    the same result shape. The sidecar echoes what it was handed, so the
    checks can see WHAT reached the converter."""
    kind = (params or {}).get("kind", "x")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    pair = "src_b" in (inputs or {})
    stems = [f"{kind}__a", f"{kind}__b"] if pair else [kind]
    outputs = {}
    for stem in stems:
        p = out / f"{stem}.fbx"
        p.write_bytes(b"fake-" + stem.encode())
        outputs[stem] = str(p)
    side = {"kind": kind, "pair": pair, "script": script,
            "slots": sorted(inputs or {}),
            "rest_name": Path((inputs or {}).get("rest", "")).name,
            "params": dict(params or {})}
    sc = out / f"{kind}.json"
    sc.write_text(json.dumps(side), encoding="utf-8")
    outputs["sidecar"] = str(sc)
    return {"ok": True, "error": "", "data": side, "outputs": outputs,
            "seconds": 0.01}


def imp(body):
    class Req:
        async def json(self):
            return body
    return asyncio.run(assets.post_clips_inbox_import(Req(), None))


def test_probe() -> None:
    print("\n[1] probe — skeleton family out of the bytes (RULE 1)")
    p = fbx_import.probe_fbx(INBOX / "Female_Dance.fbx")
    check("a unity-humanoid file is recognised",
          p["skeleton_family"] == "unity-humanoid", str(p))
    check("bone_count counts the family's own names (6 planted)",
          p["bone_count"] == 6, str(p["bone_count"]))
    check("fingers are seen", p["has_fingers"] is True, str(p))
    check("and it is no reference pose", p["is_rest_candidate"] is False)
    q = fbx_import.probe_fbx(INBOX / "strange.fbx")
    check("an unknown rig stays unknown", q["skeleton_family"] == "", str(q))
    check("with no bones and no fingers",
          q["bone_count"] == 0 and q["has_fingers"] is False, str(q))
    r = fbx_import.probe_fbx(INBOX / "Tpose.fbx")
    check("Tpose.fbx is a reference-pose candidate", r["is_rest_candidate"] is True)
    for name in ("hero_t-pose.fbx", "REST.fbx", "bindpose.fbx", "A-Pose.fbx"):
        check(f"…so is {name}", fbx_import.is_rest_name(name) is True)
    for name in ("walk.fbx", "Female_Dance.fbx"):
        check(f"…and {name} is not", fbx_import.is_rest_name(name) is False)
    missing = fbx_import.probe_fbx(INBOX / "gone.fbx")
    check("a missing file probes to an error, not an exception",
          "error" in missing and missing["skeleton_family"] == "", str(missing))

    print("\n[2] listing")
    entries = fbx_import.inbox_entries()
    names = [e["name"] for e in entries]
    check("only the FBX files are listed, sorted",
          names == ["Female_Dance.fbx", "Female_Solo.fbx", "Male_Dance.fbx",
                    "strange.fbx", "take_A.fbx", "take_B.fbx", "Tpose.fbx"],
          str(names))
    check("each entry carries size, mtime and the probe",
          all({"name", "size", "mtime", "probe"} <= set(e) for e in entries))
    route = assets.get_clips_inbox(None)
    check("the route adds the pair suggestion per entry",
          all("pair" in e for e in route["entries"]))
    check("and names the reference pose",
          route["rest_suggestion"] == "Tpose.fbx", str(route["rest_suggestion"]))
    check("the inbox directory is the throwaway one",
          route["dir"] == str(INBOX), route["dir"])


def test_pairs() -> None:
    print("\n[3] pair suggestion (RULE 2)")
    cases = [
        ("Female_Dance.fbx", "Male_Dance.fbx"),
        ("Male_Dance.fbx", "Female_Dance.fbx"),
        ("take_A.fbx", "take_B.fbx"),
        ("take_B.fbx", "take_A.fbx"),
        ("Female_Solo.fbx", ""),          # no Male_Solo.fbx in the inbox
        ("Tpose.fbx", ""),                # no pattern at all
        ("strange.fbx", ""),
    ]
    for name, want in cases:
        got = fbx_import.pair_suggestion(name)
        check(f"{name} -> {want or '(none)'}", got == want, got or "(none)")
    check("__a/__b is a pattern too (candidate names, no file needed)",
          "hug__b.fbx" in fbx_import.partner_names("hug__a.fbx"),
          str(fbx_import.partner_names("hug__a.fbx")))
    check("…and _L/_R", "cam_r.fbx" in fbx_import.partner_names("cam_L.fbx"),
          str(fbx_import.partner_names("cam_L.fbx")))
    check("the longer suffix wins: __a does not also propose _a -> _b",
          fbx_import.partner_names("hug__a.fbx") == ["hug__b.fbx"],
          str(fbx_import.partner_names("hug__a.fbx")))


def test_path_limits() -> None:
    print("\n[4] path limits — the inbox talks in bare names")
    for bad, why in [
        ("../secrets.json", "parent traversal"),
        ("sub/walk.fbx", "a directory"),
        ("sub\\walk.fbx", "a backslash"),
        ("", "empty"),
        (".hidden.fbx", "a dotfile"),
        ("notes.txt", "not a clip extension"),
        ("..", "the parent itself"),
    ]:
        try:
            fbx_import.safe_inbox_name(bad)
            check(f"rejected: {why}", False, repr(bad))
        except fbx_import.ClipImportError:
            check(f"rejected: {why}", True, repr(bad))
    check("a plain name passes",
          fbx_import.safe_inbox_name("Female_Dance.fbx") == "Female_Dance.fbx")
    check("the DELETE route answers 400 on a path, not a traversal",
          status_of(lambda: assets.delete_clips_inbox("../x.fbx", None)) == 400)

    print("\n[5] an inbox file is in NO library")
    listing = assets.list_animation_clips()
    names = {c["filename"] for c in listing["clips"]}
    check("the clip listing holds only the library clip",
          names == {"idle.fbx"}, str(sorted(names)))
    check("and the clip route does not reach into the inbox",
          assets.resolve_clip_path("Female_Dance.fbx") is None
          or not assets.resolve_clip_path("Female_Dance.fbx").is_file())


def test_import() -> None:
    print("\n[6] import validation (RULE 3 + RULE 4)")
    real_run = runner.run
    fbx_import.runner.run = fake_run
    try:
        for kind, why in [("dance__a", "the pair role separator"),
                          ("a/b", "a path separator"),
                          ("", "empty"),
                          ("dance.fbx", "an extension")]:
            code = status_of(lambda: imp({"kind": kind, "files": ["Female_Dance.fbx"]}))
            check(f"422 for kind {kind!r} — {why}", code == 422, str(code))
        check("422 for an unknown rig",
              status_of(lambda: imp({"kind": "odd", "files": ["strange.fbx"]})) == 422)
        check("422 for a file that is not in the inbox",
              status_of(lambda: imp({"kind": "x", "files": ["gone.fbx"]})) == 422)
        check("422 for three files",
              status_of(lambda: imp({"kind": "x", "files": ["a.fbx", "b.fbx", "c.fbx"]})) == 422)
        check("400 when files is not a list",
              status_of(lambda: imp({"kind": "x", "files": "Female_Dance.fbx"})) == 400)
        check("400 for the free library without 'redistributable' (RULE 4)",
              status_of(lambda: imp({"kind": "dance", "files": ["Female_Dance.fbx"],
                                     "target": "free"})) == 400)
        check("422 for an unknown target",
              status_of(lambda: imp({"kind": "dance", "files": ["Female_Dance.fbx"],
                                     "target": "public"})) == 422)
        check("409 for a kind the licensed library already has",
              status_of(lambda: imp({"kind": "idle", "files": ["Female_Dance.fbx"]})) == 409)

        print("\n[7] a solo import — licensed by default")
        res = imp({"kind": "resting", "files": ["Female_Dance.fbx"],
                   "start_s": 0.5, "end_s": 3.0, "loop_s": 1.5, "in_place": True})
        check("the clip landed in the LICENSED library",
              (LICENSED / "resting.fbx").is_file() and (LICENSED / "resting.json").is_file())
        check("and NOT in the free one", not (FREE / "resting.fbx").exists())
        check("the answer names the target", res["target"] == "licensed", str(res["target"]))
        check("its url carries the licensed/ prefix",
              res["clip"]["url"] == "/assets/animation-clips/licensed/resting.fbx",
              str(res["clip"]))
        params = res["sidecar"]["params"]
        check("the window, the loop and in_place reached the converter",
              params["start_s"] == 0.5 and params["end_s"] == 3.0
              and params["loop_s"] == 1.5 and params["in_place"] is True, str(params))
        check("the family is detected by the converter itself (bone_map auto)",
              params["bone_map"] == "auto", str(params["bone_map"]))
        check("30 fps out", params["fps"] == 30, str(params["fps"]))
        check("the source file name travels into the sidecar",
              params["source_name"] == ["Female_Dance.fbx"], str(params["source_name"]))
        check("no rest file was passed",
              res["sidecar"]["slots"] == ["rig", "src"], str(res["sidecar"]["slots"]))
        check("and the library now offers the kind",
              "resting" in assets.list_animation_clips()["kinds"])

        print("\n[8] the reference pose reaches inputs['rest']")
        res = imp({"kind": "resting2", "files": ["Female_Dance.fbx"],
                   "rest_file": "Tpose.fbx"})
        check("the rest slot is filled",
              res["sidecar"]["slots"] == ["rest", "rig", "src"],
              str(res["sidecar"]["slots"]))
        check("with the file that was named",
              res["sidecar"]["rest_name"] == "Tpose.fbx",
              res["sidecar"]["rest_name"])
        check("and the answer reports it", res["rest_file"] == "Tpose.fbx",
              str(res["rest_file"]))
        check("422 for a reference pose that is not in the inbox",
              status_of(lambda: imp({"kind": "resting3", "files": ["Female_Dance.fbx"],
                                     "rest_file": "nope.fbx"})) == 422)

        print("\n[9] a pair import — both halves, one kind")
        res = imp({"kind": "resting-pair", "files": ["Female_Dance.fbx", "Male_Dance.fbx"],
                   "rest_file": "Tpose.fbx", "in_place": True, "loop_s": 2.0})
        check("both halves were written",
              (LICENSED / "resting-pair__a.fbx").is_file()
              and (LICENSED / "resting-pair__b.fbx").is_file())
        check("the answer flags it as a pair", res["pair"] is True)
        check("the A file first, the partner second",
              res["sidecar"]["params"]["source_name"]
              == ["Female_Dance.fbx", "Male_Dance.fbx"],
              str(res["sidecar"]["params"]["source_name"]))
        check("in_place is ignored for a pair (the roots carry the contact)",
              res["sidecar"]["params"]["in_place"] is False)
        check("so is the loop cut",
              res["sidecar"]["params"]["loop_s"] is None,
              str(res["sidecar"]["params"]["loop_s"]))
        check("the two source slots are src_a/src_b",
              res["sidecar"]["slots"] == ["rest", "rig", "src_a", "src_b"],
              str(res["sidecar"]["slots"]))
        check("the library sees ONE pair kind",
              assets.list_animation_clips()["pair_kinds"] == ["resting-pair"],
              str(assets.list_animation_clips()["pair_kinds"]))
        check("422 for a pair of the same file twice",
              status_of(lambda: imp({"kind": "twin",
                                     "files": ["Female_Dance.fbx", "Female_Dance.fbx"]})) == 422)

        print("\n[10] overwrite, set and the free library")
        check("409 without the flag",
              status_of(lambda: imp({"kind": "resting", "files": ["Female_Dance.fbx"]})) == 409)
        again = imp({"kind": "resting", "files": ["Female_Dance.fbx"], "overwrite": True})
        check("200 with it", again["kind"] == "resting")
        res = imp({"kind": "resting", "files": ["Female_Dance.fbx"], "set": "female"})
        check("the same kind is free again in another set",
              (LICENSED / "female" / "resting.fbx").is_file())
        check("its url carries the set segment",
              res["clip"]["url"] == "/assets/animation-clips/licensed/female/resting.fbx",
              str(res["clip"]["url"]))
        res = imp({"kind": "free-take", "files": ["take_A.fbx"],
                   "target": "free", "redistributable": True})
        check("with redistributable the clip goes into the FREE library",
              (FREE / "free-take.fbx").is_file() and res["target"] == "free")
        check("and its url has no licensed/ prefix",
              res["clip"]["url"] == "/assets/animation-clips/free-take.fbx",
              str(res["clip"]["url"]))
    finally:
        fbx_import.runner.run = real_run


def test_delete() -> None:
    print("\n[11] delete")
    (INBOX / "throwaway.fbx").write_bytes(fake_fbx(UNITY_NAMES))
    check("it is listed", "throwaway.fbx" in [e["name"] for e in fbx_import.inbox_entries()])
    r = assets.delete_clips_inbox("throwaway.fbx", None)
    check("the route removes it", r["removed"] is True and not (INBOX / "throwaway.fbx").exists())
    r = assets.delete_clips_inbox("throwaway.fbx", None)
    check("deleting it again is no error, just removed=False", r["removed"] is False)


def test_real() -> None:
    """One TRUE pair conversion out of the REAL inbox — only when Blender and
    the files are there. Expectations from the measurement of 2026-08-21 with
    the local pair (two FBX with a Female_/Male_ prefix) plus the reference
    pose that lies beside them."""
    print("\n[12] real pair conversion out of the live inbox")
    st = runner.status()
    live = paths.get_shared_dir() / "models" / "clips-inbox"
    files = sorted(p.name for p in live.glob("*.fbx")) if live.is_dir() else []
    female = [n for n in files if n.lower().startswith("female_")]
    male = [n for n in files if n.lower().startswith("male_")]
    rest = [n for n in files if fbx_import.is_rest_name(n)]
    rig = paths.get_shared_dir() / "models" / "clips-licensed" / "idle.fbx"
    if not (st["executable"] and female and male and rest and rig.is_file()):
        print(f"  – skipped (blender={bool(st['executable'])}, pair={bool(female and male)}, "
              f"reference pose={bool(rest)}, rig={rig.is_file()})")
        return
    # The live inbox, but a THROWAWAY target: nothing is written into a library.
    os.environ["ANIMATION_CLIPS_INBOX_DIR"] = str(live)
    fbx_import._probe_cache.clear()
    try:
        # The throwaway library holds a FAKE idle.fbx, so the rig is named
        # explicitly — the real library's own skeleton, which is what an
        # import in production picks.
        res = fbx_import.import_fbx("smoketest-pair", [female[0], male[0]],
                                    rest_file=rest[0], target="licensed",
                                    out_dir=LICENSED / "real", rig=rig,
                                    overwrite=True)
    finally:
        os.environ["ANIMATION_CLIPS_INBOX_DIR"] = str(INBOX)
        fbx_import._probe_cache.clear()
    side = res["sidecar"]
    check("both halves were written",
          (LICENSED / "real" / "smoketest-pair__a.fbx").is_file()
          and (LICENSED / "real" / "smoketest-pair__b.fbx").is_file())
    check("the sidecar says pair", side.get("pair") is True, str(side.get("pair")))
    src = side.get("source") or {}
    check("the bone map was detected", src.get("bone_map") == "unity-humanoid",
          str(src.get("bone_map")))
    check("fingers came along", src.get("fingers") is True, str(src.get("fingers")))
    check("the reference pose put it in rest-delta mode",
          src.get("rotation_mode") == "rest-delta", str(src.get("rotation_mode")))
    geo = side.get("geometry") or {}
    dist = geo.get("root_distance_m")
    check("the two roots stand 0.15–0.30 m apart (measured 0.22)",
          isinstance(dist, (int, float)) and 0.15 <= dist <= 0.30, str(dist))
    floor = geo.get("rig_floor_min_cm")
    check("no figure sinks through the floor (rig_floor_min_cm > -1)",
          isinstance(floor, (int, float)) and floor > -1.0, str(floor))
    print(f"  · {res['seconds']:.1f} s, files {res['outputs']}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--real", action="store_true",
                    help="also run one true Blender conversion of the live inbox")
    a = ap.parse_args()
    build_inbox()
    check("ANIMATION_CLIPS_INBOX_DIR is honoured",
          paths.get_clips_inbox_dir() == INBOX, str(paths.get_clips_inbox_dir()))
    check("…and both libraries point at the throwaway dirs",
          paths.get_animation_clips_dir() == FREE
          and paths.get_licensed_clips_dir() == LICENSED)
    test_probe()
    test_pairs()
    test_path_limits()
    test_import()
    test_delete()
    if a.real:
        test_real()
    print(f"\n{'FAILED: ' + ', '.join(FAILURES) if FAILURES else 'all checks passed'}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        shutil.rmtree(INBOX, ignore_errors=True)
        shutil.rmtree(FREE, ignore_errors=True)
        shutil.rmtree(LICENSED, ignore_errors=True)
        shutil.rmtree(WORLD, ignore_errors=True)
