#!/usr/bin/env python3
"""Numeric check of the ROOT-MOTION import modes — ``root_motion`` =
``strip`` / ``keep`` / ``foot_lock`` in ``app/blender/scripts/cmu_clip.py``
(``run_takes``) and the pass that measures/rebuilds the travel,
``app/blender/scripts/clip_root_motion.py``.

Usage:
    ./.venv/bin/python scripts/smoke_clip_root_motion.py

Needs Blender (``app.blender.runner.is_available()``) and the CMU source of
subject 111 (``shared/models/mocap-src/cmu/111/111.asf`` + ``111_11.amc``);
without either it prints SKIP and exits 0. The pair case [8] additionally
needs 18_01 + 19_01 and is skipped on its own when they are missing. No
server, no world DB, no clip library: every conversion writes into a temp
directory, never into ``shared/models/clips``.

Every conversion goes through ``runner.run("cmu_clip", …)`` exactly like
``app/core/cmu_import.py::convert_take``; every written FBX is measured a
second time by ``runner.run("clip_root_motion", params={"measure_only": True})``
— the drift of the planted contact points in the FILE, not in the scene the
importer wrote it from.

EXPECTATIONS, DERIVED BY HAND
=============================
Take 111_11 "get up from chair", 120 fps, 4.767 s. The catalog measures its
root travel as travel_m 0.412 (start→end) — the hips move forward over the
feet while standing up. Rig/actor leg ratio of this take: hips_scale 1.1914
(today's sidecar).

[1] strip:     travel_m == [0, 0] (±0.005); max_drift_cm >= 20 — the feet slide
               back by (most of) the travel while they are planted. That is
               the defect, measured, and the RED counter-probe of this file.
[2] keep:      |travel_m| within 0.412 · 1.1914 ± 0.08 m (the actor's travel,
               scaled by the leg ratio; ±0.08 for the window and the rig
               feet) — i.e. 0.41 … 0.57; max_drift_cm <= 6 (report only: the
               recorded hips path is the actor's, not the rig's).
[3] foot_lock: max_drift_cm <= 1.5 (MAX_LOCK_DRIFT_CM); travel_m points
               FORWARD: z > 0.25 and |x| < 0.15 (the figure stands up in
               front of the chair, not beside it).
[4] foot_lock: contact_s is non-empty and covers the last second of the take
               (the figure ends standing on both feet).
[5] every mode: ref_height_m == 2.011 ± 0.01 (reference rig, standing
               height from the rest pose: highest bone head over the lowest
               foot point). The rest of shared/models/rig/reference.fbx puts
               the crown joint (HeadTop_End head) at 201.11 cm and the lowest
               foot point (the Toe_End heads) at -0.01 cm → 2.011 m. The
               crown joint is also where a character mesh is measured for
               its height_cm (model3d normalisation), so the ratio
               height_cm / ref_height_m compares like with like.
               (First derivation said 1.60 … 1.95, a human stature — but the
               reference skeleton is a 2 m figure: hips at 113.03 cm per its
               README, 0.56 of 201.)
[6] every mode: no "in_place" key in geometry.
[7] every mode: the vertical profile is untouched — hips Y per frame of
               keep/foot_lock equals strip within 0.01 cm (the pass writes
               XZ only).
[8] pair (18_01 handshake, if present): root_motion param ignored, no
               geometry.root_motion key, roles/anchor as before.
[9] loop_s=1.5 together with root_motion=foot_lock: the run fails (ok False)
               with an error naming both parameters.
[10] foot_lock, the SIDECAR number is the FILE's number: |sidecar − file|
               <= 0.05 cm for the whole take AND for the take trimmed at
               start_s 1.533 (the window rule's start, 1.733 − 0.2 s: it drops
               the seated contact span). Both measurements run the same
               contact rule on keys equal within 0.001 cm, so the only
               tolerance needed is the sidecar's 0.01 rounding. Trimmed take:
               max_drift_cm <= 1.5 in the file too. (Before the fix the
               measuring job read the contact heights from the clip file's
               own rest, which is not the rig's: 0.97 sidecar vs 2.83 file.)
               The measuring job's ref_height_m equals the sidecar's 2.011
               (same rig rest).
[11] get-up-bed (Meshy biped, yaw 180, level_head, foot_lock — the source in
               shared/models/clips-inbox/Meshy_AI_default_biped/, SKIP when
               absent; it is local data, not tracked): the whole take passes
               (max_drift_cm <= 1.5, sidecar == file within 0.05 cm). Before
               the dominant-contact rule (_root_motion.foot_lock_path) it was
               refused at 2.02 cm: a shuffling left foot at ~2 cm height
               (weight 0.83–0.97) dragged the planted right foot.
"""
import math
import os
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.blender import runner            # noqa: E402

CMU = ROOT / "shared" / "models" / "mocap-src" / "cmu"
RIG = ROOT / "shared" / "models" / "rig" / "reference.fbx"
SOLO = ("111", "111_11")
PAIR = (("18", "18_01"), ("19", "19_01"))
MODES = ("strip", "keep", "foot_lock")
TIMEOUT_S = 900

CATALOG_TRAVEL_M = 0.412
HIPS_SCALE = 1.1914
KEEP_TOL_M = 0.08
MAX_LOCK_DRIFT_CM = 1.5
STRIP_MIN_DRIFT_CM = 20.0
KEEP_REPORT_DRIFT_CM = 6.0
HIPS_Y_TOL_CM = 0.01
REF_HEIGHT_M = 2.011
REF_HEIGHT_TOL_M = 0.01
SAME_DRIFT_CM = 0.05
TRIM_START_S = 1.533
BED_INBOX = ROOT / "shared" / "models" / "clips-inbox"
BED_NAME = ("Meshy_AI_default_biped/"
            "Meshy_AI_Animation_01a08d2e-b5d6-7307-8fb8-cf575d7b7b5d_without_skin.fbx")

failures = []


def check(label, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'} {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        failures.append(label)


def files(subject, take):
    return CMU / subject / f"{subject}.asf", CMU / subject / f"{take}.amc"


def convert(out_dir: Path, kind: str, **params):
    asf, amc = files(*SOLO)
    p = {"kind": kind, "fps": 30, "source_fps": 120.0, "source_takes": [SOLO[1]]}
    p.update(params)
    return runner.run("cmu_clip", inputs={"rig": RIG, "asf": asf, "amc": amc},
                      params=p, out_dir=out_dir, timeout_s=TIMEOUT_S)


def convert_pair(out_dir: Path, kind: str, **params):
    (sa, ta), (sb, tb) = PAIR
    asf_a, amc_a = files(sa, ta)
    asf_b, amc_b = files(sb, tb)
    p = {"kind": kind, "fps": 30, "source_fps": 120.0, "end_s": 4.0,
         "source_takes": [ta, tb]}
    p.update(params)
    return runner.run("cmu_clip", inputs={"rig": RIG, "asf_a": asf_a, "amc_a": amc_a,
                                          "asf_b": asf_b, "amc_b": amc_b},
                      params=p, out_dir=out_dir, timeout_s=TIMEOUT_S)


def convert_bed(out_dir: Path, kind: str, **params):
    """The bed import through the app's own path (``fbx_import.import_fbx``),
    answered in the runner's result shape."""
    from app.core import fbx_import
    try:
        r = fbx_import.import_fbx(kind, [{"name": BED_NAME, "take": None}],
                                  target="free", redistributable=True, yaw_deg=180,
                                  level_head=True, overwrite=True, out_dir=out_dir,
                                  **params)
    except Exception as e:                    # noqa: BLE001 - reported as a result
        return {"ok": False, "error": str(e), "data": {}, "outputs": {}}
    fbx = sorted(out_dir.glob("*.fbx"))
    return {"ok": True, "error": "", "data": r["sidecar"],
            "outputs": {kind: str(fbx[0])} if fbx else {}}


def measure(fbx: str):
    return runner.run("clip_root_motion", inputs={"rig": RIG, "src": Path(fbx)},
                      params={"fps": 30, "measure_only": True}, timeout_s=TIMEOUT_S)


def covers_last_second(spans, frames, fps=30):
    last = (frames - 1) / fps
    return any(a <= last - 1.0 + 1e-6 and b >= last - 1e-3 for a, b in spans)


def main() -> int:
    if not runner.is_available():
        print("SKIP: Blender is not available")
        return 0
    if not all(p.is_file() for p in files(*SOLO)):
        print(f"SKIP: CMU source {SOLO[1]} missing under {CMU}")
        return 0
    pair_ok = all(p.is_file() for s, t in PAIR for p in files(s, t))
    bed_ok = (BED_INBOX / BED_NAME).is_file()

    with tempfile.TemporaryDirectory(prefix="smoke-clip-root-motion-") as tmp:
        tmp = Path(tmp)
        # Nothing here reads the library, but a stray reader must not see it.
        os.environ["ANIMATION_CLIPS_DIR"] = str(tmp / "clips")
        jobs = {m: (convert, tmp / m, f"gu-{m}", {"root_motion": m}) for m in MODES}
        jobs["trim"] = (convert, tmp / "trim", "gu-trim",
                        {"root_motion": "foot_lock", "start_s": TRIM_START_S})
        if bed_ok:
            # The bed goes through fbx_import, which reads storage paths:
            # a throwaway world and inbox, the source copied in.
            import shutil
            from app.core import paths
            paths.init(str(tmp / "storage"))
            inbox = tmp / "inbox"
            (inbox / BED_NAME).parent.mkdir(parents=True)
            shutil.copy2(BED_INBOX / BED_NAME, inbox / BED_NAME)
            os.environ["ANIMATION_CLIPS_INBOX_DIR"] = str(inbox)
            jobs["bed"] = (convert_bed, tmp / "bed", "gu-bed", {"root_motion": "foot_lock"})
        jobs["loop"] = (convert, tmp / "loop", "gu-loop",
                        {"root_motion": "foot_lock", "loop_s": 1.5})
        if pair_ok:
            jobs["pair_lock"] = (convert_pair, tmp / "pair_lock", "hs",
                                 {"root_motion": "foot_lock"})
            jobs["pair_plain"] = (convert_pair, tmp / "pair_plain", "hs", {})
        with ThreadPoolExecutor(max_workers=4) as pool:
            futs = {k: pool.submit(fn, d, kind, **params)
                    for k, (fn, d, kind, params) in jobs.items()}
            res = {k: f.result() for k, f in futs.items()}
        for m in MODES:
            if not res[m]["ok"]:
                print(f"conversion '{m}' failed: {res[m]['error']}")
                failures.append(f"conversion {m}")
        if failures:
            print(f"\nFAILED: {len(failures)} check(s): " + ", ".join(failures))
            return 1
        extra = [k for k in ("trim", "bed") if k in res and res[k]["ok"]]
        with ThreadPoolExecutor(max_workers=4) as pool:
            futs = {m: pool.submit(measure, res[m]["outputs"][f"gu-{m}"])
                    for m in MODES + tuple(extra)}
            meas = {m: f.result() for m, f in futs.items()}

    side = {m: res[m]["data"] for m in MODES}
    geo = {m: side[m].get("geometry") or {} for m in MODES}
    block = {m: geo[m].get("root_motion") or {} for m in MODES}
    for m in MODES:
        b = block[m]
        mm = meas[m]
        md = mm.get("data") or {}
        print(f"· {m:9s} travel_m {b.get('travel_m')}  max_drift_cm {b.get('max_drift_cm')}"
              f"  (file: {md.get('max_drift_cm')})  ref_height_m {b.get('ref_height_m')}"
              f"  contact_s {b.get('contact_s')}  frames {side[m].get('frames')}"
              f"  hips_scale {geo[m].get('hips_scale')}")
        if not mm["ok"]:
            print(f"  measuring run '{m}' failed: {mm['error']}")
            failures.append(f"measure {m}")

    def num(v):
        return isinstance(v, (int, float)) and math.isfinite(v)

    print("\n[1] strip: no travel, and the planted feet slide (the defect)")
    t = block["strip"].get("travel_m") or [None, None]
    check("travel_m == [0, 0] ± 0.005",
          all(num(v) and abs(v) <= 0.005 for v in t), str(t))
    d = block["strip"].get("max_drift_cm")
    check(f"max_drift_cm >= {STRIP_MIN_DRIFT_CM}", num(d) and d >= STRIP_MIN_DRIFT_CM, str(d))

    print("\n[2] keep: the actor's travel, scaled by the leg ratio")
    t = block["keep"].get("travel_m") or [None, None]
    want = CATALOG_TRAVEL_M * HIPS_SCALE
    length = math.hypot(*t) if all(num(v) for v in t) else None
    check(f"|travel_m| within {want:.3f} ± {KEEP_TOL_M}",
          length is not None and abs(length - want) <= KEEP_TOL_M, str(length))
    d = block["keep"].get("max_drift_cm")
    print(f"  info max_drift_cm {d} ({'within' if num(d) and d <= KEEP_REPORT_DRIFT_CM else 'OVER'}"
          f" the reported {KEEP_REPORT_DRIFT_CM} — report only)")

    print("\n[3] foot_lock: the planted feet hold, the figure walks forward")
    d = block["foot_lock"].get("max_drift_cm")
    check(f"max_drift_cm <= {MAX_LOCK_DRIFT_CM} (sidecar)", num(d) and d <= MAX_LOCK_DRIFT_CM, str(d))
    fd = (meas["foot_lock"].get("data") or {}).get("max_drift_cm")
    check(f"max_drift_cm <= {MAX_LOCK_DRIFT_CM} (measured in the written FBX)",
          num(fd) and fd <= MAX_LOCK_DRIFT_CM, str(fd))
    t = block["foot_lock"].get("travel_m") or [None, None]
    check("travel z > 0.25", num(t[1]) and t[1] > 0.25, str(t))
    check("|travel x| < 0.15", num(t[0]) and abs(t[0]) < 0.15, str(t))

    print("\n[4] foot_lock: contact at the end of the take")
    spans = block["foot_lock"].get("contact_s") or []
    check("contact_s is non-empty", bool(spans), str(spans))
    check("contact_s covers the last second",
          covers_last_second(spans, int(side["foot_lock"].get("frames") or 0)), str(spans))

    print("\n[5] every mode: reference standing height (crown joint over the toes)")
    for m in MODES:
        h = block[m].get("ref_height_m")
        check(f"{m}: ref_height_m == {REF_HEIGHT_M} ± {REF_HEIGHT_TOL_M}",
              num(h) and abs(h - REF_HEIGHT_M) <= REF_HEIGHT_TOL_M, str(h))
    print("\n[6] every mode: no in_place key, a root_motion block with its mode")
    for m in MODES:
        check(f"{m}: no 'in_place' in geometry", "in_place" not in geo[m])
        check(f"{m}: geometry.root_motion.mode == {m!r}", block[m].get("mode") == m,
              str(block[m].get("mode")))

    print("\n[7] every mode: the vertical profile is untouched (file hips Y per frame)")
    ys = {m: (meas[m].get("data") or {}).get("hips_y") or [] for m in MODES}
    for m in ("keep", "foot_lock"):
        same_len = len(ys[m]) == len(ys["strip"]) and ys[m]
        worst = max((abs(a - b) for a, b in zip(ys[m], ys["strip"])), default=math.inf)
        check(f"{m}: hips Y == strip within {HIPS_Y_TOL_CM} cm",
              bool(same_len) and worst <= HIPS_Y_TOL_CM,
              f"{len(ys[m])}/{len(ys['strip'])} frames, worst {worst:.4f} cm")

    print("\n[8] pair: root_motion is ignored")
    if not pair_ok:
        print("  SKIP: 18_01 / 19_01 not under shared/models/mocap-src/cmu")
    else:
        pl, pp = res["pair_lock"], res["pair_plain"]
        check("both pair runs succeeded", pl["ok"] and pp["ok"],
              f"{pl['error']} / {pp['error']}")
        if pl["ok"] and pp["ok"]:
            gl, gp = pl["data"]["geometry"], pp["data"]["geometry"]
            check("no geometry.root_motion", "root_motion" not in gl and "root_motion" not in gp)
            check("no geometry.in_place", "in_place" not in gl)
            for k in ("anchor_frame", "anchor_s", "roles", "root_distance_m", "contact"):
                check(f"{k} as without the parameter", gl.get(k) == gp.get(k) and k in gl,
                      f"{gl.get(k)} vs {gp.get(k)}")

    print("\n[9] loop_s + foot_lock is refused")
    lr = res["loop"]
    err = str(lr.get("error") or "")
    check("the run fails", lr["ok"] is False, err)
    check("the error names loop_s and root_motion",
          "loop_s" in err and "root_motion" in err, err)

    def same_drift(label, key):
        r = res[key]
        check(f"{label}: conversion ok", r["ok"], r["error"])
        if not r["ok"]:
            return
        b = r["data"]["geometry"].get("root_motion") or {}
        md = (meas[key].get("data") or {}) if meas[key]["ok"] else {}
        d, fd = b.get("max_drift_cm"), md.get("max_drift_cm")
        print(f"  · {label}: travel_m {b.get('travel_m')}  sidecar {d}  file {fd}"
              f"  contact_s {b.get('contact_s')}  file ref_height_m {md.get('ref_height_m')}")
        check(f"{label}: max_drift_cm <= {MAX_LOCK_DRIFT_CM} (sidecar)",
              num(d) and d <= MAX_LOCK_DRIFT_CM, str(d))
        check(f"{label}: max_drift_cm <= {MAX_LOCK_DRIFT_CM} (file)",
              num(fd) and fd <= MAX_LOCK_DRIFT_CM, str(fd))
        check(f"{label}: |sidecar − file| <= {SAME_DRIFT_CM} cm",
              num(d) and num(fd) and abs(d - fd) <= SAME_DRIFT_CM, f"{d} vs {fd}")
        check(f"{label}: file ref_height_m == sidecar's",
              md.get("ref_height_m") == b.get("ref_height_m"),
              f"{md.get('ref_height_m')} vs {b.get('ref_height_m')}")

    print("\n[10] foot_lock: the sidecar's drift is the file's drift")
    res["whole"], meas["whole"] = res["foot_lock"], meas["foot_lock"]
    same_drift("whole take", "whole")
    same_drift(f"trimmed at {TRIM_START_S} s", "trim")

    print("\n[11] get-up-bed passes foot_lock")
    if not bed_ok:
        print(f"  SKIP: {BED_NAME} not in {BED_INBOX}")
    else:
        same_drift("bed, whole take", "bed")

    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s): " + ", ".join(failures))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
