#!/usr/bin/env python3
"""Smoke: an alt half FOLLOWS its scene (review 04#4) — the import window and
the orientation bakes are recorded in the sidecar and replayed by
``fbx_import.import_alt``; a sidecar without that record is refused.

Usage: ./.venv/bin/python scripts/smoke_clip_alt_follow.py

Pure Python, no Blender, no server: ``runner.run`` / ``runner.status`` and the
source probe ``_prepare_source`` are stood in for, and every directory is
temporary (ANIMATION_CLIPS_DIR, ANIMATION_CLIPS_LICENSED_DIR,
ANIMATION_CLIPS_INBOX_DIR and ANIMATION_RIG_FILE point into one temp dir).
The real ``clip_orient`` maths is checked in Blender by
``scripts/smoke_clip_orient.py``; here the stand-in applies the contract its
docstring writes out, ``p' = Ry(yaw)·Rx(tilt)·Rz(roll)·(p + s) + (0, h, 0)``,
to a fake clip file that holds two root positions (cm): ``start`` (frame 0)
and ``anchor`` (the anchor frame). The ``fbx_clip`` stand-in writes, per role,
the PRE-bake roots

    a  start (0, 90, -10)   anchor (0, 90, 0)
    b  start (50, 90, -10)  anchor (50, 90, 0)       an alt of b: the same

and counts frames from the window it is given: a 10 s take at 30 fps,
``frames = round(((end or 10) - start) * 30)``.

cos 10 = 0.98481, sin 10 = 0.17365. Rx(a): y' = y cos - z sin,
z' = y sin + z cos. Ry(90): x' = z, z' = -x.

[A] orient_clip RECORDS each bake, in order, in source.rebuild.orient_bakes
    (a pair ``tw`` whose sidecar has the block with an empty list):
    1. tilt 10 + height 5      -> {yaw 0, tilt 10, roll 0, height 5}
    2. yaw 90 + partner shift [5, 0, -10]
                               -> {yaw 90, tilt 0, roll 0, height 0,
                                   role_shift_cm {b: [5, 0, -10]}}
    3. renderer-only shift_cm [25, -40] (no Blender run) -> nothing appended
    so the list has exactly the two entries 1, 2. A group ``gr`` turned with
    role_shift_cm {a: [0, 0, 5]} records role_shift_cm {a: [0, 0, 5]}. A
    sidecar WITHOUT the block (``old``) stays without it after an orient.

[B] import_alt REPLAYS them. Scene ``hug``: rebuild window [1.5, 4.0], import
    dial yaw 12.5 (geometry.yaw_deg 102.5 = 12.5 + the later 90),
    level_head true, bakes 1 and 2 of [A]; frames = (4.0 - 1.5) * 30 = 75.
    The fbx_clip run must get start_s 1.5, end_s 4.0, yaw_deg 12.5 (NOT
    102.5), level_head true, export_roles true. Then two clip_orient runs:
      bake 1 on anchor a (0, 90, 0): y = 90 . 0.98481 = 88.6329,
             z = 90 . 0.17365 = 15.6285, + 5 -> (0, 93.6329, 15.6285)
             anchor b -> (50, 93.6329, 15.6285)
             start b (50, 90, -10): y = 88.6329 + 1.7365 = 90.3694 + 5
             = 95.3694, z = 15.6285 - 9.8481 = 5.7804 -> (50, 95.3694, 5.7804)
      bake 2 (b and b~wave shifted by (5, 0, -10) first, then Ry(90)):
             anchor a (0, 93.6329, 15.6285) -> (15.6285, 93.6329, 0)
             anchor b (55, 93.6329, 5.6285) -> (5.6285, 93.6329, -55)
             start b (55, 95.3694, -4.2196) -> (-4.2196, 95.3694, -55)
    The sidecar's stored anchors are those of the library halves after the
    same two bakes: a [0.156, 0.0], b [0.056, -0.55] m -> drift 0, accepted.
    Expected: the published alt file's anchor root is (5.6285, 93.6329, -55)
    — the tilt and the 5 cm lift are IN it (unreplayed it would be
    (50, 90, 0)); geometry.alts["b~wave"] = start [-0.042, -0.55], anchor
    [0.056, -0.55]; orient_bakes_replayed 2; the library halves untouched.

[C] the CONFIRMED old failure, height only: scene ``lift`` with window
    [0, None] (frames 300) and one bake {height 5}. A lift moves no XZ, so the
    old XZ-only drift check passed and published the alt at anchor y 90. Now
    the alt's anchor root is (50, 95, 0).

[D] the window, alone: scene ``cut`` with window [2.0, 3.0] (frames 30), no
    bakes. The fbx_clip run gets start_s 2.0 / end_s 3.0 (the old code sent
    0 / None — the whole 300-frame take) and no export_roles; accepted, no
    clip_orient run at all.

[E] refusals, nothing written and the sidecar byte-identical each time, and
    NO Blender run started:
    - ``old``: no source.rebuild (written before the record existed) — the
      message says the window and the bakes are not recorded and to
      re-import the clip;
    - ``half``: a rebuild block without orient_bakes — same refusal.
    And with a Blender run: ``long``, window [0, None] but the sidecar says
    frames 80 while the rebuild gives 300 -> refused naming "300 frames
    instead of 80".

[F] a bake that lands while the alt import WAITS for the library lock is
    replayed: ``wait`` (window [0, None], frames 300, no bakes when the alt
    import reads it); the lock holder runs a height-5 bake into the
    sidecar's record (anchors stay, a lift moves no XZ). Expected: one
    clip_orient replay, the alt's anchor root (50, 95, 0).

The old code fails [B] (window / dial / no replay), [C] (alt at y 90),
[D] (start_s 0, end_s None) and [E] (no refusal: it built the alt) — by the
reasoning above; [A] fails because orient_clip recorded nothing.
"""
import json
import math
import os
import sys
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

TMP = Path(tempfile.mkdtemp(prefix="clip-alt-follow-"))
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
CALLS = []
TOL = 1e-3          # cm; the stand-in computes in double precision

PRE = {"a": {"start": [0.0, 90.0, -10.0], "anchor": [0.0, 90.0, 0.0]},
       "b": {"start": [50.0, 90.0, -10.0], "anchor": [50.0, 90.0, 0.0]}}


def check(label, ok, detail=""):
    print(f"{'ok  ' if ok else 'FAIL'} {label}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        FAIL.append(label)


def close(a, b, tol=TOL):
    return len(a) == len(b) and all(abs(x - y) <= tol for x, y in zip(a, b))


# ── the clip_orient contract, written out by hand ────────────────────────
def orient(p, s, yaw, tilt, roll, h):
    x, y, z = (p[0] + s[0], p[1] + s[1], p[2] + s[2])
    a = math.radians(roll)
    x, y = x * math.cos(a) - y * math.sin(a), x * math.sin(a) + y * math.cos(a)
    a = math.radians(tilt)
    y, z = y * math.cos(a) - z * math.sin(a), y * math.sin(a) + z * math.cos(a)
    a = math.radians(yaw)
    x, z = x * math.cos(a) + z * math.sin(a), -x * math.sin(a) + z * math.cos(a)
    return [x, y + h, z]


def fake_prepare_source(path, take, *, name=None, src_family=""):
    return "unity-humanoid", {"index": take, "take_name": "", "name": name or path.name}


def fake_status():
    return {"executable": "fixture"}


def fake_run(script, *, inputs=None, params=None, out_dir=None, timeout_s=0):
    out = Path(out_dir)
    CALLS.append((script, dict(params or {})))
    if script == "clip_orient":
        outputs, data = {}, {}
        for slot, src in (inputs or {}).items():
            if slot == "rig":
                continue
            doc = json.loads(Path(src).read_text(encoding="utf-8"))
            s = (params.get("slot_shift_cm") or {}).get(slot) or [0.0, 0.0, 0.0]
            moved = {k: orient(v, s, params.get("yaw_deg", 0.0), params.get("tilt_deg", 0.0),
                               params.get("roll_deg", 0.0), params.get("height_cm", 0.0))
                     for k, v in doc.items()}
            (out / f"{slot}.fbx").write_text(json.dumps(moved), encoding="utf-8")
            outputs[slot] = str(out / f"{slot}.fbx")
            data[slot] = {"root_after": moved["start"], "root_after_anchor": moved["anchor"]}
        return {"ok": True, "outputs": outputs, "data": {"clips": data}, "seconds": 0.1}
    assert script == "fbx_clip" and params.get("export") == "alts", params
    kind, end = params["kind"], params["end_s"]
    frames = int(round(((10.0 if end is None else end) - params["start_s"]) * 30))
    keys = [f"{a['role']}~{a['name']}" for a in params["alts"]]
    if params.get("export_roles"):
        keys = list(params["roles"]) + keys
    outputs = {}
    for key in keys:
        stem = f"{kind}__{key}"
        (out / f"{stem}.fbx").write_text(json.dumps(PRE[key.split("~")[0]]), encoding="utf-8")
        outputs[stem] = str(out / f"{stem}.fbx")
    xz = {r: {"start_xz_m": [v["start"][0] / 100, v["start"][2] / 100],
              "anchor_xz_m": [v["anchor"][0] / 100, v["anchor"][2] / 100]} for r, v in PRE.items()}
    data = {"frames": frames, "geometry": {
        "roles": {r: xz[r] for r in params["roles"]},
        "alts": {f"{a['role']}~{a['name']}": xz[a["role"]] for a in params["alts"]}}}
    return {"ok": True, "outputs": outputs, "data": data, "seconds": 0.1}


def write_pair(directory, kind, *, rebuild, frames, anchors, roles=("a", "b"), yaw=None):
    directory.mkdir(parents=True, exist_ok=True)
    for r in roles:
        (directory / f"{kind}__{r}.fbx").write_text(json.dumps(PRE[r if r in PRE else "a"]),
                                                    encoding="utf-8")
    source = {"format": "fbx", "files": [f"{r}.fbx" for r in roles], "takes": [None] * len(roles)}
    if rebuild is not None:
        source["rebuild"] = rebuild
    geometry = {"anchor_s": 0.5, "anchor_frame": 15,
                "roles": {r: {"start_xz_m": [0, 0], "anchor_xz_m": list(v)} for r, v in anchors.items()}}
    if yaw is not None:
        geometry["yaw_deg"] = yaw
    meta = {"kind": kind, "pair": True, "roles": list(roles), "fps": 30, "frames": frames,
            "loop": False, "geometry": geometry, "source": source}
    (directory / f"{kind}.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    clips.reload_clip_caches()


def rebuild(window=(0.0, None), yaw=0.0, level_head=False, bakes=()):
    return {"window_s": list(window), "yaw_deg": yaw, "level_head": level_head,
            "orient_bakes": [dict(b) for b in bakes]}


def sidecar(directory, kind):
    return json.loads((directory / f"{kind}.json").read_text(encoding="utf-8"))


def file_doc(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


BAKE1 = {"yaw_deg": 0.0, "tilt_deg": 10.0, "roll_deg": 0.0, "height_cm": 5.0}
BAKE2 = {"yaw_deg": 90.0, "tilt_deg": 0.0, "roll_deg": 0.0, "height_cm": 0.0,
         "role_shift_cm": {"b": [5.0, 0.0, -10.0]}}
PRE_ANCHORS = {"a": [0.0, 0.0], "b": [0.5, 0.0]}


def test_record():
    print("[A] orient_clip records every bake in order")
    write_pair(FREE, "tw", rebuild=rebuild(), frames=300, anchors=PRE_ANCHORS)
    clips.orient_clip("free", "tw__a.fbx", tilt_deg=10.0, height_cm=5.0, with_finales=False)
    clips.orient_clip("free", "tw__a.fbx", yaw_deg=90.0, role_shift_cm={"b": [5.0, 0.0, -10.0]},
                      with_finales=False)
    clips.orient_clip("free", "tw__b.fbx", shift_cm=[25, -40], with_finales=False)
    got = sidecar(FREE, "tw")["source"]["rebuild"]["orient_bakes"]
    check("the list holds exactly bake 1 then bake 2", got == [BAKE1, BAKE2], str(got))
    write_pair(FREE, "gr", rebuild=rebuild(), frames=300, roles=("a", "b", "c"),
               anchors={"a": [0, 0], "b": [0.5, 0], "c": [0, 0.5]})
    clips.orient_clip("free", "gr__b.fbx", role_shift_cm={"a": [0.0, 0.0, 5.0]}, with_finales=False)
    got = sidecar(FREE, "gr")["source"]["rebuild"]["orient_bakes"]
    check("a group records its role shift", got == [
        {"yaw_deg": 0.0, "tilt_deg": 0.0, "roll_deg": 0.0, "height_cm": 0.0,
         "role_shift_cm": {"a": [0.0, 0.0, 5.0]}}], str(got))
    write_pair(FREE, "old", rebuild=None, frames=300, anchors=PRE_ANCHORS)
    clips.orient_clip("free", "old__a.fbx", height_cm=5.0, with_finales=False)
    check("a sidecar without the block stays without it",
          "rebuild" not in sidecar(FREE, "old")["source"], str(sidecar(FREE, "old")["source"]))


def run_alt(kind, alt="wave"):
    try:
        return fbx_import.import_alt(kind, "b", alt, {"name": "alt.fbx", "take": None},
                                     target="licensed")
    except ClipImportError as e:
        return {"error": str(e)}


def fbx_params():
    return [p for s, p in CALLS if s == "fbx_clip"]


def orient_calls():
    return [p for s, p in CALLS if s == "clip_orient"]


def test_replay():
    print("[B] import_alt replays window, dial and bakes")
    write_pair(LICENSED, "hug", rebuild=rebuild((1.5, 4.0), 12.5, True, (BAKE1, BAKE2)),
               frames=75, anchors={"a": [0.156, 0.0], "b": [0.056, -0.55]}, yaw=102.5)
    halves = {r: (LICENSED / f"hug__{r}.fbx").read_bytes() for r in ("a", "b")}
    CALLS.clear()
    res = run_alt("hug")
    check("the alt import succeeded", "error" not in res, str(res))
    p = fbx_params()[0] if fbx_params() else {}
    check("fbx_clip got the window 1.5 .. 4.0", p.get("start_s") == 1.5 and p.get("end_s") == 4.0,
          f"{p.get('start_s')} .. {p.get('end_s')}")
    check("fbx_clip got the import dial 12.5, not 102.5", p.get("yaw_deg") == 12.5, str(p.get("yaw_deg")))
    check("fbx_clip got level_head and export_roles",
          p.get("level_head") is True and p.get("export_roles") is True, str(p))
    check("two clip_orient replays, in order",
          [(c["tilt_deg"], c["height_cm"], c["yaw_deg"]) for c in orient_calls()]
          == [(10.0, 5.0, 0.0), (0.0, 0.0, 90.0)], str(orient_calls()))
    doc = file_doc(LICENSED / "hug__b~wave.fbx") if (LICENSED / "hug__b~wave.fbx").is_file() else {}
    check("the alt's anchor root is (5.6285, 93.6329, -55)",
          close(doc.get("anchor") or [], [5.6285, 93.6329, -55.0]), str(doc))
    check("the alt's start root is (-4.2196, 95.3694, -55)",
          close(doc.get("start") or [], [-4.2196, 95.3694, -55.0]), str(doc))
    meta = sidecar(LICENSED, "hug")
    geo = (meta["geometry"].get("alts") or {}).get("b~wave") or {}
    check("geometry.alts b~wave = start [-0.042, -0.55], anchor [0.056, -0.55]",
          geo == {"start_xz_m": [-0.042, -0.55], "anchor_xz_m": [0.056, -0.55]}, str(geo))
    check("orient_bakes_replayed is 2", res.get("orient_bakes_replayed") == 2, str(res))
    check("the scene's halves are untouched",
          all((LICENSED / f"hug__{r}.fbx").read_bytes() == halves[r] for r in ("a", "b")))
    check("the bakes list is unchanged", meta["source"]["rebuild"]["orient_bakes"] == [BAKE1, BAKE2])


def test_height_only():
    print("[C] a height-only bake reaches the alt")
    write_pair(LICENSED, "lift", rebuild=rebuild(bakes=({"yaw_deg": 0.0, "tilt_deg": 0.0,
                                                          "roll_deg": 0.0, "height_cm": 5.0},)),
               frames=300, anchors=PRE_ANCHORS)
    CALLS.clear()
    res = run_alt("lift")
    check("the alt import succeeded", "error" not in res, str(res))
    doc = file_doc(LICENSED / "lift__b~wave.fbx") if (LICENSED / "lift__b~wave.fbx").is_file() else {}
    check("the alt's anchor root is (50, 95, 0)", close(doc.get("anchor") or [], [50.0, 95.0, 0.0]),
          str(doc))


def test_window_only():
    print("[D] the import window reaches the alt run")
    write_pair(LICENSED, "cut", rebuild=rebuild((2.0, 3.0)), frames=30, anchors=PRE_ANCHORS)
    CALLS.clear()
    res = run_alt("cut")
    check("the alt import succeeded", "error" not in res, str(res))
    p = fbx_params()[0] if fbx_params() else {}
    check("fbx_clip got start_s 2.0 / end_s 3.0", p.get("start_s") == 2.0 and p.get("end_s") == 3.0,
          str(p))
    check("no export_roles and no clip_orient run without bakes",
          not p.get("export_roles") and not orient_calls(), str(CALLS))


def test_refusals():
    print("[E] a sidecar without the record is refused, a frame-count mismatch too")
    cases = {"old": None, "half": {"window_s": [0.0, None], "yaw_deg": 0.0, "level_head": False}}
    for kind, block in cases.items():
        write_pair(LICENSED, kind, rebuild=block, frames=300, anchors=PRE_ANCHORS)
        before = (LICENSED / f"{kind}.json").read_bytes()
        CALLS.clear()
        res = run_alt(kind)
        err = res.get("error") or ""
        check(f"{kind}: refused, saying the record is missing and to re-import",
              "does not record the import window" in err and "re-import" in err, str(res))
        check(f"{kind}: no Blender run", not CALLS, str(CALLS))
        check(f"{kind}: no alt file", not (LICENSED / f"{kind}__b~wave.fbx").exists())
        check(f"{kind}: sidecar unchanged", (LICENSED / f"{kind}.json").read_bytes() == before)
    write_pair(LICENSED, "long", rebuild=rebuild(), frames=80, anchors=PRE_ANCHORS)
    before = (LICENSED / "long.json").read_bytes()
    res = run_alt("long")
    check("long: refused with 300 frames instead of 80",
          "300 frames instead of 80" in (res.get("error") or ""), str(res))
    check("long: no alt file", not (LICENSED / "long__b~wave.fbx").exists())
    check("long: sidecar unchanged", (LICENSED / "long.json").read_bytes() == before)


def test_bake_while_waiting():
    print("[F] a bake recorded while the alt import waits is replayed")
    write_pair(LICENSED, "wait", rebuild=rebuild(), frames=300, anchors=PRE_ANCHORS)
    asked, taken = threading.Event(), threading.Event()
    real_lock = fbx_import.library_write_lock

    @contextmanager
    def signalling_lock(destination):
        asked.set()
        with real_lock(destination):
            yield

    def holder():
        with keyed_lock("clip_library", "write"):
            taken.set()
            asked.wait(10)
            meta = sidecar(LICENSED, "wait")
            meta["source"]["rebuild"]["orient_bakes"].append(
                {"yaw_deg": 0.0, "tilt_deg": 0.0, "roll_deg": 0.0, "height_cm": 5.0})
            (LICENSED / "wait.json").write_text(json.dumps(meta), encoding="utf-8")

    outcome = {}
    CALLS.clear()
    with patch.object(fbx_import, "library_write_lock", signalling_lock):
        h = threading.Thread(target=holder)
        h.start()
        taken.wait(10)
        i = threading.Thread(target=lambda: outcome.update(run_alt("wait")))
        i.start()
        h.join(20)
        i.join(20)
    check("the alt import succeeded", "error" not in outcome, str(outcome))
    check("one clip_orient replay", len(orient_calls()) == 1, str(orient_calls()))
    doc = file_doc(LICENSED / "wait__b~wave.fbx") if (LICENSED / "wait__b~wave.fbx").is_file() else {}
    check("the alt's anchor root is (50, 95, 0)", close(doc.get("anchor") or [], [50.0, 95.0, 0.0]),
          str(doc))


def main():
    INBOX.mkdir(parents=True, exist_ok=True)
    for name in ("a.fbx", "b.fbx", "c.fbx", "alt.fbx"):
        (INBOX / name).write_bytes(b"source")
    RIG.write_bytes(b"rig")
    with patch.object(fbx_import, "_prepare_source", fake_prepare_source), \
         patch.object(fbx_import.runner, "status", fake_status), \
         patch("app.blender.runner.run", fake_run):
        test_record()
        test_replay()
        test_height_only()
        test_window_only()
        test_refusals()
        test_bake_while_waiting()
    print("FAIL" if FAIL else "PASS", f"({len(FAIL)} failing)" if FAIL else "")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
