#!/usr/bin/env python3
"""Repairs the arm ROLL SPLIT of library clips in place — the forearm's roll
against the upper arm is moved onto the upper arm (``app/blender/scripts/
clip_roll.py``), every world orientation but the upper arm's own roll stays.

Why: until 2026-09-04 the positional FBX retarget (``fbx_clip.py``) built
the upper arm's rest frame on the palm axis and its posed frame on the elbow's
bend normal, 96.9 / 77.0 deg apart on MOB1, so every MOB1 clip carries an
upper arm rolled by +31 … +140 deg and a forearm rolled back by -51 … -114 deg
against it. The net is right (the hand lands within 1.0 deg of the source),
the split is invented — and linear blend skinning pinches a joint to
cos(twist/2): `mob1-walk` shoulder 0.42, elbow 0.57 of the radius. The
converter is fixed (`_elbow_axis`), but 9 of the 10 MOB1 sources are gone, so
the existing files are redistributed instead of reconverted. Measured on
`mob1-stand-relaxed-idle-v2` the redistribution lands the upper arm at
+32.2/-22.9 deg where the source holds +31.8/-23.0.

Usage:
    ./.venv/bin/python scripts/repair_clip_roll.py                # DRY RUN over both libraries
    ./.venv/bin/python scripts/repair_clip_roll.py --apply        # repair what the dry run flags
    ./.venv/bin/python scripts/repair_clip_roll.py <clip.fbx> […] # only these files (dry run)
    ./.venv/bin/python scripts/repair_clip_roll.py --apply <clip.fbx>

Options:
    --apply             write. Without it NOTHING is touched: the run only
                        measures and prints what would happen.
    --threshold <deg>   a clip is flagged when the forearm's roll against the
                        upper arm exceeds this anywhere (default 10; the
                        CMU clips sit at 0.1, the MOB1 clips at 51 … 114).
    --min-cos <x>       ALSO flag a clip whose smaller cos(θ/2) (shoulder or
                        elbow) lies below x — the selection for the balanced
                        re-split of clips whose forearm is not rolled at all
                        (CMU: 23 of 33 lie below 0.90).
    --target <deg>      the forearm roll that is to remain (default 0.0):
                        one number, ``L:<deg>,R:<deg>`` per arm, or
                        ``balance`` — per clip and per arm the value that
                        makes cos(shoulder/2) and cos(elbow/2) equal
                        (searched on the per-frame series, 0.25 deg grid). Rolls
                        about one axis add, so a target τ leaves the upper
                        arm with (upper + forearm − τ); the τ that makes the
                        shoulder's and the elbow's cos(θ/2) equal maximises
                        the smaller of the two. Measured on the Unity pairs
                        (constant offsets from a bent-elbow Tpose.fbx): with
                        τ = 0 `resting-cowgir__b` would trade an elbow of
                        0.050 for a shoulder of 0.335; with L:46.5,R:-70.5
                        both sides sit at 0.918 / 0.817.
    --rig <fbx>         the T-pose reference skeleton (default
                        shared/models/rig/reference.fbx)
    --timeout <s>       Blender timeout per run (default 900)
    --file-pos-limit <cm>
                        joint-position deviation the WRITTEN file may show
                        against the original once it is re-imported (default
                        0.01, see below)

The rule that gates every repair, checked PER ARM on the dry-run numbers: the
smaller of the two cos(θ/2) (shoulder, elbow) must be larger afterwards, and a
shoulder that stood at or above 0.80 may not fall below it. A clip that fails
the rule on either arm is reported and left alone.

Two position limits, because the check measures two different things. IN
THE SCENE — the pose before the keys were rewritten against the pose after,
same Blender session — the redistribution is exact: measured <= 0.0001 cm on
all ten MOB1 clips, and there the limit stays at 0.001 cm; that is the strict
check of the arithmetic. OVER THE FILE — the written clip re-imported and
compared with the original — the same measurement also contains Blender's
float32 bone maths on the way through the FBX, and that costs 0.00122 cm at
`mob1-walk`'s LeftFoot WITHOUT any change at all (null round trip: import,
export unchanged, measure against the original). A limit below the noise of
the transport checks the file format, not the calculation; that 9 of the 10
clips stayed under 0.001 cm was chance. 0.01 cm is 0.1 mm on a 1.80 m figure,
an order of magnitude above the measured noise and far below anything
visible — so that is the file-level default.

Which clips: without file arguments both libraries (``shared/models/clips``
and ``shared/models/clips-licensed``, subdirectories included) are MEASURED
and a clip is chosen by its numbers, never by name. Two data-driven
exceptions: a clip whose sidecar names ``bone_map`` ``unity-humanoid`` (the
Unity pairs) is never chosen automatically — the correct split there is only
proven for `standing-lotus` — and a clip the sidecar marks as
``roll_repaired`` is not rolled a second time. Naming a file lifts the Unity
exception; a repaired file is only rolled again with ``--again`` (a re-split
to another target is legitimate, an accidental second pass with the default
target 0 would undo a balanced split).

Applying: the repaired clip is written to a temporary file, that file is
re-imported and verified with the same measurement (forearm roll at the
target, every other bone's world orientation within 0.05 deg of the original,
joints within 0.01 cm — see the two limits above), the original is copied to
``<name>.fbx.bak`` next to it, and only then replaced. The sidecar gets ``source.roll_repaired`` with
the date and the moved angles. An existing ``.bak`` is never overwritten —
such a clip is skipped and reported.

The CMU clips (``shared/models/clips``, tracked in git) get the same
balanced split, for a different reason: their forearm carries EXACTLY 0 roll
against the upper arm in every clip, because the ASF skeleton gives the radius
no twist degree of freedom — the whole pronation is folded into the humerus
by the format, not by the actor (a person pronates the forearm). Measured
`putting on a dress`: upper arm 122 deg, forearm 0, shoulder cos 0.481. Giving
the split back is anatomically truer, not less true, and the world pose stays
untouched as always. The sidecar records the reason per family
(``source.roll_repair_reason``).

Needs Blender (auto-discovered, or image_generation.blender_executable). No
server, no world DB.
"""
import argparse
import json
import math
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.blender import runner                         # noqa: E402
from app.core import paths                              # noqa: E402
from app.core.timeutils import utc_now                  # noqa: E402

DEFAULT_THRESHOLD_DEG = 10.0
VERIFY_TWIST_DEG = 0.05        # residual forearm roll a written file may keep
MAX_OTHER_DEV_DEG = 0.05
MAX_POS_DEV_CM = 0.001         # in the scene: the redistribution itself (measured <= 0.0001 cm)
FILE_POS_DEV_CM = 0.01         # over the file: plus Blender's float32 round trip (0.00122 cm unchanged)


def sidecar_of(clip: Path) -> Path:
    stem = clip.stem
    for role in ("__a", "__b"):
        if stem.endswith(role):
            stem = stem[: -len(role)]
    return clip.with_name(stem + ".json")


def read_sidecar(clip: Path) -> dict:
    p = sidecar_of(clip)
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def library_clips() -> List[Path]:
    out: List[Path] = []
    for d, _source in paths.get_animation_clips_dirs():
        if d.is_dir():
            out.extend(sorted(p for p in d.rglob("*.fbx") if p.is_file()))
    return out


def pinch(deg: float) -> float:
    """Linear blend skinning's cross-section factor at a joint's 50/50 point
    for a twist of ``deg``: cos(deg / 2)."""
    return math.cos(math.radians(abs(deg)) / 2.0)


def measure(rig: Path, clips: List[Path], target, timeout: int) -> Dict[Path, dict]:
    """One Blender start for all clips: ``{clip: data}`` (dry run)."""
    if not clips:
        return {}
    inputs = {"rig": rig}
    slots = {}
    for i, c in enumerate(clips):
        slot = f"src_{i}"
        inputs[slot] = c
        slots[slot] = c
    res = runner.run("clip_roll", inputs=inputs,
                     params={"dry_run": True, "target_twist_deg": target},
                     timeout_s=timeout)
    if not res["ok"]:
        raise SystemExit(f"measurement failed: {res.get('error')}")
    data = res["data"].get("clips") or {}
    return {slots[s]: data[s] for s in slots if s in data}


def parse_target(text: str):
    """``"12.5"`` → 12.5; ``"L:33.25,R:-47.75"`` → {"L": 33.25, "R": -47.75}."""
    text = str(text or "0").strip()
    if text.lower() == "balance":
        return "balance"
    if ":" not in text:
        return float(text)
    out = {}
    for part in text.split(","):
        k, v = part.split(":", 1)
        k = k.strip().upper()
        if k not in ("L", "R"):
            raise SystemExit(f"--target: expected L:<deg>,R:<deg>, got {text!r}")
        out[k] = float(v)
    return {"L": out.get("L", 0.0), "R": out.get("R", 0.0)}


def wrap(deg: float) -> float:
    while deg > 180.0:
        deg -= 360.0
    while deg <= -180.0:
        deg += 360.0
    return deg


def balanced_target(series: dict) -> float:
    """The forearm roll τ (deg) that maximises min(cos(shoulder/2), cos(elbow/2))
    on one arm — rolls about one axis add, so the upper arm ends at
    upper + forearm − τ per frame."""
    up, fo = series["upper"], series["forearm"]

    def score(tau):
        sh = max(abs(wrap(u + f - tau)) for u, f in zip(up, fo))
        return min(pinch(sh), pinch(tau))
    best, best_s = 0.0, score(0.0)
    t = -180.0
    while t <= 180.0:
        sc = score(t)
        if sc > best_s + 1e-9:
            best, best_s = t, sc
        t += 0.25
    return best


def predicted(d: dict, target) -> dict:
    """Per arm the shoulder/elbow cos before and after a repair to ``target``,
    from the dry-run series (exact up to the FBX round trip)."""
    out = {}
    for S in ("L", "R"):
        a = d["arms"][S]
        tau = target[S] if isinstance(target, dict) else float(target)
        up, fo = a["series"]["upper"], a["series"]["forearm"]
        sh_before = max(abs(u) for u in up)
        el_before = max(abs(f) for f in fo)
        sh_after = max(abs(wrap(u + f - tau)) for u, f in zip(up, fo))
        out[S] = {"tau": tau, "shoulder_before": pinch(sh_before), "elbow_before": pinch(el_before),
                  "shoulder_after": pinch(sh_after), "elbow_after": pinch(tau)}
    return out


def rule_holds(pred: dict) -> Tuple[bool, str]:
    """Per arm: the smaller cos must grow, and a shoulder at/above 0.80 must
    stay there."""
    for S, p in pred.items():
        before = min(p["shoulder_before"], p["elbow_before"])
        after = min(p["shoulder_after"], p["elbow_after"])
        if after <= before + 1e-9:
            return False, f"{S}: min cos {before:.3f} -> {after:.3f} does not improve"
        if p["shoulder_before"] >= 0.80 and p["shoulder_after"] < 0.80:
            return False, f"{S}: shoulder {p['shoulder_before']:.3f} -> {p['shoulder_after']:.3f} falls below 0.80"
    return True, ""


def side_max(d: dict, key: str) -> Tuple[float, float]:
    return (d["arms"]["L"][key]["max_abs"], d["arms"]["R"][key]["max_abs"])


def print_table(rows: List[Tuple[Path, dict, str, object]], root: Path) -> None:
    head = (f"{'clip':<44} | {'FA/UA L':>8} {'R':>7} | {'UA/clav L':>9} {'R':>7} | {'target L':>8} {'R':>7} "
            f"| {'shoulder L':>14} {'R':>14} | {'elbow L':>14} {'R':>14} | status")
    print(head)
    print("-" * len(head))
    for clip, d, status, target in rows:
        name = str(clip.relative_to(root)) if root in clip.parents else clip.name
        if d is None:
            print(f"{name:<44} | {'':>16} | {'':>17} | {'':>16} | {'':>29} | {'':>29} | {status}")
            continue
        L, R = d["arms"]["L"], d["arms"]["R"]
        fa_b = (L["forearm_twist_before"]["max_abs"], R["forearm_twist_before"]["max_abs"])
        ua_b = (L["upper_twist_before"]["max_abs"], R["upper_twist_before"]["max_abs"])
        p = predicted(d, target)
        cell = lambda S, k: f"{p[S][k + '_before']:.3f} -> {p[S][k + '_after']:.3f}"   # noqa: E731
        print(f"{name:<44} | {fa_b[0]:8.1f} {fa_b[1]:7.1f} | {ua_b[0]:9.1f} {ua_b[1]:7.1f} | {p['L']['tau']:8.2f} {p['R']['tau']:7.2f} "
              f"| {cell('L', 'shoulder'):>14} {cell('R', 'shoulder'):>14} | {cell('L', 'elbow'):>14} {cell('R', 'elbow'):>14} | {status}")


def apply_one(rig: Path, clip: Path, side: dict, target, timeout: int,
              file_pos_limit: float = FILE_POS_DEV_CM) -> Optional[str]:
    """Repairs one clip in place; returns an error text, None on success."""
    bak = clip.with_name(clip.name + ".bak")
    if bak.exists():
        return f"backup already exists, not touching: {bak}"
    fps = int(side.get("fps") or 30)
    with tempfile.TemporaryDirectory(prefix="clip-roll-") as tmp:
        out_dir = Path(tmp)
        res = runner.run("clip_roll", inputs={"rig": rig, "src": clip},
                         params={"target_twist_deg": target, "fps": fps,
                                 "max_other_dev_deg": MAX_OTHER_DEV_DEG,
                                 "max_pos_dev_cm": MAX_POS_DEV_CM},
                         out_dir=out_dir, timeout_s=timeout)
        if not res["ok"]:
            return f"repair run failed: {res.get('error')}"
        written = Path(res["outputs"].get("src") or "")
        if not written.is_file():
            return "the repair run declared no file"
        # the written FILE, re-imported and measured against the original
        ver = runner.run("clip_roll", inputs={"rig": rig, "src": written, "ref": clip},
                         params={"dry_run": True, "target_twist_deg": target, "fps": fps,
                                 "max_other_dev_deg": MAX_OTHER_DEV_DEG,
                                 "max_pos_dev_cm": file_pos_limit},
                         timeout_s=timeout)
        if not ver["ok"]:
            return f"verification of the written file failed: {ver.get('error')}"
        v = (ver["data"].get("clips") or {}).get("src") or {}
        # what a second pass would still move = the written file's forearm roll
        # against the target, per arm (a per-arm target is not 0)
        resid = max(side_max(v, "moved")) if v else float("inf")
        vs = v.get("vs_ref") or {}
        problems = []
        if resid > VERIFY_TWIST_DEG:
            problems.append(f"forearm roll in the written file still {resid:.3f} deg off the target")
        if vs.get("max_other_rot_deg", float("inf")) > MAX_OTHER_DEV_DEG:
            problems.append(f"{vs.get('worst_other_bone')} differs {vs.get('max_other_rot_deg')} deg from the original")
        if vs.get("max_pos_cm", float("inf")) > file_pos_limit:
            problems.append(f"{vs.get('worst_pos_bone')} differs {vs.get('max_pos_cm')} cm from the original")
        if v.get("frames") != side.get("frames", v.get("frames")):
            problems.append(f"frame count {v.get('frames')} vs sidecar {side.get('frames')}")
        if problems:
            return "verification: " + "; ".join(problems)
        shutil.copy2(clip, bak)
        shutil.move(str(written), str(clip))
        moved = {s: (res["data"]["clips"]["src"]["arms"][s]["moved"]["mean"]) for s in ("L", "R")}
        _mark_sidecar(clip, moved, target)
        print(f"    written: {clip}\n    backup:  {bak}\n    moved: L {moved['L']:+.1f} deg, R {moved['R']:+.1f} deg;"
              f" residual forearm roll {resid:.3f} deg; other bones within {vs.get('max_other_rot_deg')} deg,"
              f" joints within {vs.get('max_pos_cm')} cm")
    return None


REASONS = {
    "cmu": "CMU/ASF gives the radius no twist dof, so the source folds all pronation into "
           "the humerus (forearm roll exactly 0); the balanced split hands it back",
    "mixamo-noprefix": "positional FBX retarget before _elbow_axis (2026-09-04) rolled the "
                       "upper arm by the palm/bend-normal angle and the forearm back",
    "unity-humanoid": "rest-delta against Tpose.fbx (elbow 43.9 deg, palms 50 deg pronated) "
                      "baked constant per-arm roll offsets",
}


def _reason(src: dict) -> str:
    if src.get("database"):
        return REASONS["cmu"]
    return REASONS.get(str(src.get("bone_map") or ""), "roll redistributed between upper arm and forearm")


def _mark_sidecar(clip: Path, moved: Dict[str, float], target) -> None:
    p = sidecar_of(clip)
    side = read_sidecar(clip)
    if not side:
        print(f"    (no sidecar at {p.name} — nothing marked)")
        return
    src = side.setdefault("source", {})
    src["roll_repair_reason"] = _reason(src)
    files = list(src.get("roll_repaired_files") or [])
    if clip.name not in files:
        files.append(clip.name)
    src["roll_repaired"] = True
    src["roll_repaired_at"] = utc_now().date().isoformat()
    src["roll_repaired_files"] = files
    per = dict(src.get("roll_moved_deg") or {})
    per[clip.name] = {"L": round(moved["L"], 2), "R": round(moved["R"], 2)}
    src["roll_moved_deg"] = per
    tg = dict(src.get("roll_target_deg") or {})
    tg[clip.name] = target if isinstance(target, dict) else {"L": target, "R": target}
    src["roll_target_deg"] = tg
    p.write_text(json.dumps(side, indent=1), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("files", nargs="*", help="clip files (default: measure both libraries)")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--again", action="store_true", help="roll a file the sidecar marks as repaired once more")
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD_DEG)
    ap.add_argument("--min-cos", type=float, default=None)
    ap.add_argument("--target", default="0", help="deg, or L:<deg>,R:<deg>")
    ap.add_argument("--rig", default="")
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--file-pos-limit", type=float, default=FILE_POS_DEV_CM)
    a = ap.parse_args()
    a.target = parse_target(a.target)

    st = runner.status()
    if not st["executable"]:
        print("no Blender executable found (image_generation.blender_executable)")
        return 1
    rig = Path(a.rig) if a.rig else paths.get_shared_dir() / "models" / "rig" / "reference.fbx"
    if not rig.is_file():
        print(f"reference skeleton missing: {rig}")
        return 1
    root = paths.get_shared_dir() / "models"

    explicit = [Path(f).resolve() for f in a.files]
    for f in explicit:
        if not f.is_file():
            print(f"no such file: {f}")
            return 1
    candidates = explicit or library_clips()
    rows: List[Tuple[Path, Optional[dict], str, object]] = []
    to_measure: List[Path] = []
    sidecars: Dict[Path, dict] = {}
    for clip in candidates:
        side = read_sidecar(clip)
        sidecars[clip] = side
        src = side.get("source") or {}
        if not explicit and src.get("bone_map") == "unity-humanoid":
            rows.append((clip, None, "skipped: Unity pair — repair only by naming the file", None))
            continue
        if clip.name in (src.get("roll_repaired_files") or []) and not (explicit and a.again):
            rows.append((clip, None, f"skipped: already repaired {src.get('roll_repaired_at', '')}"
                         + (" — name it with --again to re-split" if explicit else ""), None))
            continue
        to_measure.append(clip)

    print(f"{'APPLY' if a.apply else 'DRY RUN'}: measuring {len(to_measure)} clip(s) "
          f"(Blender {st.get('version', '')}, threshold {a.threshold} deg"
          f"{f', min cos {a.min_cos}' if a.min_cos is not None else ''}, target {a.target})")
    data = measure(rig, to_measure, 0.0, a.timeout * max(1, len(to_measure) // 10 + 1))
    flagged: List[Tuple[Path, object]] = []
    for clip in to_measure:
        d = data.get(clip)
        if d is None:
            rows.append((clip, None, "not measured", None))
            continue
        target = a.target
        if target == "balance":
            target = {S: balanced_target(d["arms"][S]["series"]) for S in ("L", "R")}
        pred = predicted(d, target)
        worst_twist = max(side_max(d, "forearm_twist_before"))
        min_cos = min(min(p["shoulder_before"], p["elbow_before"]) for p in pred.values())
        selected = worst_twist > a.threshold or (a.min_cos is not None and min_cos < a.min_cos)
        if not selected:
            rows.append((clip, d, "ok", target))
            continue
        ok, why = rule_holds(pred)
        if not ok:
            rows.append((clip, d, f"RULE FAILS, left alone — {why}", target))
            continue
        flagged.append((clip, target))
        rows.append((clip, d, "REPAIR" if a.apply else "would repair", target))
    rows.sort(key=lambda r: -(max(side_max(r[1], "forearm_twist_before")) if r[1] else -1))
    print_table(rows, root)
    print(f"\n{len(flagged)} clip(s) flagged")
    if not a.apply:
        if flagged:
            print("dry run — nothing written. Re-run with --apply to repair them.")
        return 0

    failures = 0
    for clip, target in flagged:
        print(f"\n== {clip.relative_to(root) if root in clip.parents else clip}  target {target}")
        err = apply_one(rig, clip, sidecars.get(clip) or {}, target, a.timeout, a.file_pos_limit)
        if err:
            failures += 1
            print(f"    NOT replaced — {err}")
    print(f"\n{len(flagged) - failures} of {len(flagged)} repaired; backups lie next to the clips as <name>.fbx.bak")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
