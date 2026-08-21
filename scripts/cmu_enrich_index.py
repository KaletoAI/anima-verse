#!/usr/bin/env python3
"""Measures, tags and groups every CMU take into ``_catalog.json``.

The trial clip archive (``scripts/cmu_convert_all.py``) knows a clip's path and
duration and nothing else. A catalog browser needs to ANSWER QUESTIONS: show me
the standing idles, the fast locomotion, the loopable takes, the ones that stay
on the spot. This script computes that from the ORIGINAL ASF/AMC recordings —
not from the converted FBX — so it runs while (or before) the conversion does,
needs no Blender, and measures the actor rather than the retargeted rig.

    shared/models/clips-trial/_catalog.json

One file, everything a browser needs: per take the measured metrics (posture,
energy, travel, duration class, loop seam), a 40-point hip-height sparkline,
the tags derived from the CMU descriptions, its duplicate group, and the clip
path if ``_index.json`` already has one.

HEURISTICS (all measured on a 30 Hz sampling of the take, in the actor's own
scale — every length is divided by the ACTOR's leg length, so a tall and a
short subject standing read the same number):

* ``hips_rel`` — height of the root above the frame's lowest joint, over the
  leg length (``lhipjoint + lfemur + ltibia``). Standing is ~0.9.
* posture per frame: ``> 0.85`` standing · ``< 0.35`` lying · in between
  sitting or kneeling, split by where the feet are: a seat puts them clearly
  IN FRONT of the hips (mean foot offset along the root's forward direction
  ``> 0.2`` leg lengths), kneeling keeps them under or behind. The take's
  posture is the majority class, or ``mixed`` when more than 20 % of the
  frames fall into a different class.
* energy: mean speed of hands, feet and head (m/s) — ``< 0.15`` static,
  ``< 0.45`` calm, ``< 1.2`` moderate, else fast. Sampling at 30 Hz smooths
  single-frame spikes; ``speed_max_m_s`` is the peak of that same mean signal.
* travel: root movement in XZ. ``travel_m`` is start→end, ``path_m`` the walked
  length. ``< 0.5 m`` in-place · ``< 3 m`` walks · else travels (on the
  start→end distance, so pacing back and forth stays "in-place").
* ``loop_seam`` — the best cut of the take into a cycle, using the same
  distance as the Blender clip cutter (``app/blender/scripts/cmu_clip.py``
  ``_pose_distance``: summed rotation angle of the limb/torso bones plus the
  hip height difference). Searched on the 30 Hz samples with a step of 2 and a
  minimum window of 1 s, on the first 40 s of long takes — the search is
  quadratic. ``loopable`` is ``loop_seam < 1.0``.

Resumable: a take whose AMC has not changed since its record was written keeps
its measurements; everything derived from the catalog (tags, groups, pair
state, clip path) is rebuilt on every run, so a re-run after more downloads or
more conversions refreshes those without re-measuring. Takes whose originals
are not on disk yet are skipped and picked up by the next run.

Usage:
    ./.venv/bin/python scripts/cmu_enrich_index.py [options]

    # the full run, four processes
    nohup ./.venv/bin/python scripts/cmu_enrich_index.py --jobs 4 \
        > logs/cmu_enrich.log 2>&1 &

Options:
    --catalog <file>  CMU catalog (default: shared/models/cmu_catalog.json)
    --src <dir>       downloaded originals (default: shared/models/mocap-src/cmu)
    --out <dir>       clip archive holding _index.json/_catalog.json
                      (default: shared/models/clips-trial)
    --only <list>     comma-separated take ids (e.g. 07_01,14_30)
    --jobs <n>        worker processes (default 1)
    --force           re-measure even when the record is up to date
    --limit <n>       stop after n measured takes (a smoke run)
"""
import argparse
import importlib.util
import json
import math
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.blender.scripts import _cmu  # noqa: E402
from app.core import paths  # noqa: E402
from app.core.timeutils import utc_now  # noqa: E402

CREDIT = ("The data used in this project was obtained from mocap.cs.cmu.edu. "
          "The database was created with funding from NSF EIA-0196217.")

SAMPLE_FPS = 30.0          # every measurement runs on this sampling
SPARKLINE_POINTS = 40
LOOP_MAX_S = 40.0          # the seam search never looks past this
LOOP_MIN_S = 1.0           # shortest window that may count as a cycle
LOOP_STEP = 2              # sample step of the seam search
LOOPABLE_MAX = 1.0
LEG_BONES = ("lhipjoint", "lfemur", "ltibia")
SPEED_BONES = ("lhand", "rhand", "lfoot", "rfoot", "head")
# Same bones the Blender clip cutter compares (cmu_clip.LOOP_BONES).
LOOP_BONES = ("lfemur", "ltibia", "lfoot", "rfemur", "rtibia", "rfoot", "lhumerus",
              "lradius", "rhumerus", "rradius", "lowerback", "thorax", "upperneck")

POSTURE_STANDING = 0.85    # hips_rel above this: standing
POSTURE_LYING = 0.35       # below this: lying
SEAT_FORWARD = 0.2         # feet this far in front of the hips (leg lengths): sitting
MIXED_SHARE = 0.2          # >20 % of frames off the majority class: "mixed"

ENERGY_STEPS = ((0.15, "static"), (0.45, "calm"), (1.2, "moderate"))
TRAVEL_STEPS = ((0.5, "in-place"), (3.0, "walks"))
DURATION_STEPS = ((3.0, "short"), (12.0, "medium"))

POSTURE_VALUES = ["standing", "sitting", "kneeling", "lying", "mixed"]
ENERGY_VALUES = ["static", "calm", "moderate", "fast"]
TRAVEL_VALUES = ["in-place", "walks", "travels"]
DURATION_VALUES = ["short", "medium", "long"]

# ---------------------------------------------------------------------- tags
#
# Order is documentation only — a take collects EVERY rule it matches, plus a
# tag for its CMU main category. Matching is case-insensitive and on word
# boundaries, over the take description AND the subject description (the
# subject line is what says "2 subjects" or "salsa" for the takes whose own
# description is a bare "walk"). An entry starting with "re:" is a raw regex
# fragment, used where a word has to exclude a longer one ("sit" must not fire
# on "sit-up", which is an exercise).
TAG_RULES = [
    ("walk", "Walking", ["walk", "walking", "stroll", "stride", "march"]),
    ("run", "Running", ["run", "running", "jog", "jogging", "sprint"]),
    ("jump", "Jumping", ["jump", "jumps", "jumping", "hop", "hops", "leap", "skip"]),
    ("climb", "Climbing", ["climb", "climbing", "ladder", "hang", "hanging"]),
    ("dance", "Dancing", ["dance", "dancing", "salsa", "ballet", "waltz", "jete",
                          "arabesque", "pirouette"]),
    ("sports", "Sports", ["basketball", "soccer", "football", "golf", "tennis",
                          "volleyball", "baseball", "frisbee", "boxing", "punch",
                          "kick", "swordplay", "sword"]),
    ("martial", "Martial arts", ["karate", "kung fu", "martial", "tai chi"]),
    ("exercise", "Exercise", ["push-up", "pushup", "jumping jack", "squat", "sit-up",
                              "situp", "stretch", "exercise", "workout", "yoga",
                              "balance"]),
    ("sit", "Sitting", ["re:sit(?!-?up)", "sitting", "stool", "chair"]),
    ("lie", "Lying", ["lie", "lying", "laying", "lay down", "sleep", "nap", "roll"]),
    ("stand", "Standing", ["stand", "standing", "wait", "idle", "static pose"]),
    ("gesture", "Gestures", ["wave", "point", "gesture", "salute", "clap", "nod",
                             "shrug"]),
    ("conversation", "Conversation", ["conversation", "talk", "talking", "explain",
                                      "argue", "quarrel"]),
    ("carry", "Carrying", ["carry", "carrying", "lift", "pick up", "box", "suitcase",
                           "bag", "drag", "push", "pull"]),
    ("everyday", "Everyday actions", ["drink", "eat", "wash", "clean", "dig", "plant",
                                      "sweep", "mop", "window", "phone", "read",
                                      "write"]),
    ("interact-object", "Object interaction", ["door", "stool", "stepstool", "table",
                                               "bench", "ball", "rope", "umbrella",
                                               "chair"]),
    ("pantomime", "Pantomime", ["pantomime", "mime", "vignette", "animal behaviors",
                                "insect", "monkey", "chicken", "bird"]),
    ("two-subjects", "Two subjects", ["2 subjects", "two subjects", "subject a",
                                      "subject b", "link arms", "shake hands",
                                      "salsa"]),
    ("emotion", "Emotion", ["happy", "sad", "angry", "laugh", "cry", "fear", "scared",
                            "emotional", "bored", "tired", "yawn"]),
    ("fall", "Falling", ["fall", "falling", "trip", "stumble", "faint", "collapse"]),
    ("crawl", "Crawling", ["crawl", "creep", "duck"]),
    ("swim", "Swimming", ["swim", "swimming"]),
    ("test", "Test & calibration", ["test", "calibration", "range of motion", "t-pose"]),
]
UNTAGGED = "untagged"


def _compile(patterns):
    """One regex per tag. A plain pattern also matches its plural ("sit-up"
    catches "sit-ups"); an "re:" pattern is taken as written."""
    parts = []
    for p in patterns:
        if p.startswith("re:"):
            parts.append(p[3:])
        else:
            parts.append(re.escape(p).replace(r"\ ", r"\s+") + "s?")
    return re.compile(r"\b(?:" + "|".join(parts) + r")\b", re.IGNORECASE)


TAG_PATTERNS = [(tag, label, _compile(pats)) for tag, label, pats in TAG_RULES]
TAG_LABELS = {tag: label for tag, label, _ in TAG_RULES}
TAG_LABELS[UNTAGGED] = "Untagged"


def slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return s or "misc"


def tags_for(take: dict, mains: dict) -> list:
    """Every tag rule the two descriptions match, plus the CMU main category."""
    text = f"{take.get('description', '')} | {take.get('subject_description', '')}"
    tags = [tag for tag, _label, rx in TAG_PATTERNS if rx.search(text)]
    if not tags:
        tags.append(UNTAGGED)
    for key in take.get("categories") or []:
        main = mains.get(key.split("/")[0])
        if main:
            tag = slug(main)
            TAG_LABELS.setdefault(tag, main)
            if tag not in tags:
                tags.append(tag)
    return tags


# ------------------------------------------------------------------- grouping

_GROUP_STRIP = re.compile(r"\(?\s*\d*\s*subjects?\s*-?\s*subject\s+[ab]\s*\)?", re.IGNORECASE)


def normalize_desc(desc: str) -> str:
    """The take description with everything that only separates DUPLICATES
    removed: the "(2 subjects - subject A)" suffix, digits, punctuation, case
    and repeated spaces. Two takes that normalise to the same string are the
    same action recorded again."""
    s = _GROUP_STRIP.sub(" ", desc or "")
    s = re.sub(r"[0-9]+", " ", s.lower())
    s = re.sub(r"[^a-z]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# -------------------------------------------------------------------- metrics

def _classify(value: float, steps, last: str) -> str:
    for limit, name in steps:
        if value < limit:
            return name
    return last


def _pose_distance(a, b) -> float:
    """Distance of two solved frames — cmu_clip._pose_distance, verbatim:
    summed rotation angle of the limb/torso bones (radians) plus the hips
    height difference (metres)."""
    d = 0.0
    for name in LOOP_BONES:
        ra = a.rot.get(name)
        if ra is None:
            continue
        rb = b.rot[name]
        tr = sum(ra[i][j] * rb[i][j] for i in range(3) for j in range(3))
        d += math.acos(max(-1.0, min(1.0, (tr - 1.0) / 2.0)))
    return d + abs(a.pos["root"][1] - b.pos["root"][1]) / 100.0


def _loop_seam(poses: list, sample_fps: float) -> float:
    """Best seam distance of a window of at least LOOP_MIN_S, or None when the
    take is too short. Quadratic, so it walks the samples in LOOP_STEP steps
    and never looks past LOOP_MAX_S."""
    n = min(len(poses), int(LOOP_MAX_S * sample_fps))
    win = max(2, int(round(LOOP_MIN_S * sample_fps)))
    if n <= win:
        return None
    best = None
    for i in range(0, n - win, LOOP_STEP):
        for j in range(i + win, n, LOOP_STEP):
            d = _pose_distance(poses[i], poses[j])
            if best is None or d < best:
                best = d
    return best


def _sparkline(series: list) -> list:
    """SPARKLINE_POINTS evenly spaced samples of a series (endpoints included)."""
    n = len(series)
    if n == 0:
        return [0.0] * SPARKLINE_POINTS
    if n == 1:
        return [round(series[0], 3)] * SPARKLINE_POINTS
    return [round(series[int(round(k * (n - 1) / (SPARKLINE_POINTS - 1)))], 3)
            for k in range(SPARKLINE_POINTS)]


def measure(asf: Path, amc: Path, framerate: float) -> dict:
    """All measurements of one take, from its originals."""
    sk, frames = _cmu.load_clip(asf, amc)
    n_frames = len(frames)
    if n_frames == 0:
        raise ValueError("AMC has no frames")
    fps = float(framerate or _cmu.CMU_FPS)
    leg = sum(sk.bones[b].length for b in LEG_BONES if b in sk.bones) * sk.unit_cm
    if leg <= 0:
        raise ValueError("skeleton has no leg length")
    step = max(1, int(round(fps / SAMPLE_FPS)))
    sample_fps = fps / step
    poses = [_cmu.solve_frame(sk, frames[i]) for i in range(0, n_frames, step)]

    hips_rel, postures, root_xz, speeds = [], [], [], []
    for pose in poses:
        floor = _cmu.lowest_point_cm(sk, pose)
        root = pose.pos["root"]
        rel = (root[1] - floor) / leg
        hips_rel.append(rel)
        root_xz.append((root[0], root[2]))
        postures.append(_posture_of(sk, pose, rel, leg))
    dt = 1.0 / sample_fps
    for a, b in zip(poses, poses[1:]):
        moved = [math.dist(a.pos[n], b.pos[n]) for n in SPEED_BONES if n in a.pos]
        speeds.append((sum(moved) / max(1, len(moved))) / 100.0 / dt)

    counts = Counter(postures)
    top, top_n = counts.most_common(1)[0]
    posture = "mixed" if (len(postures) - top_n) > MIXED_SHARE * len(postures) else top
    speed_mean = sum(speeds) / len(speeds) if speeds else 0.0
    speed_max = max(speeds) if speeds else 0.0
    travel = math.dist(root_xz[0], root_xz[-1]) / 100.0
    path = sum(math.dist(a, b) for a, b in zip(root_xz, root_xz[1:])) / 100.0
    duration = n_frames / fps
    seam = _loop_seam(poses, sample_fps)
    ordered = sorted(hips_rel)
    return {
        "frames": n_frames,
        "duration_s": round(duration, 3),
        "metrics": {
            "posture": posture,
            "hips_rel_median": round(ordered[len(ordered) // 2], 3),
            "hips_rel_min": round(ordered[0], 3),
            "hips_rel_max": round(ordered[-1], 3),
            "energy": _classify(speed_mean, ENERGY_STEPS, "fast"),
            "speed_mean_m_s": round(speed_mean, 3),
            "speed_max_m_s": round(speed_max, 3),
            "travel": _classify(travel, TRAVEL_STEPS, "travels"),
            "travel_m": round(travel, 3),
            "path_m": round(path, 3),
            "duration_class": _classify(duration, DURATION_STEPS, "long"),
            "loop_seam": None if seam is None else round(seam, 3),
            "loopable": bool(seam is not None and seam < LOOPABLE_MAX),
        },
        "sparkline": _sparkline(hips_rel),
    }


def _posture_of(sk, pose, hips_rel: float, leg: float) -> str:
    """Posture of ONE frame — see the heuristics in the module docstring."""
    if hips_rel > POSTURE_STANDING:
        return "standing"
    if hips_rel < POSTURE_LYING:
        return "lying"
    fx, fz = _cmu.forward_xz(pose)
    root = pose.pos["root"]
    offsets = [((pose.pos[foot][0] - root[0]) * fx + (pose.pos[foot][2] - root[2]) * fz)
               for foot in ("lfoot", "rfoot") if foot in pose.pos]
    forward = (sum(offsets) / len(offsets) / leg) if offsets else 0.0
    return "sitting" if forward > SEAT_FORWARD else "kneeling"


# ------------------------------------------------------------- worker process

_SRC = None


def _init(src: str) -> None:
    global _SRC
    _SRC = Path(src)


def _work(job: tuple) -> dict:
    take_id, subject_dir, asf_name, amc_name, framerate = job
    asf, amc = _SRC / subject_dir / asf_name, _SRC / subject_dir / amc_name
    try:
        out = measure(asf, amc, framerate)
    except Exception as e:                    # never let one take stop the run
        return {"id": take_id, "error": f"{type(e).__name__}: {e}"}
    out["id"] = take_id
    out["amc_mtime"] = round(amc.stat().st_mtime, 3)
    return out


# ------------------------------------------------------------------ assembly

def load_confirm_pairs():
    """``confirm_pairs`` from the converter — the pairing rule must stay ONE
    rule: the catalog's guess counts only when both AMCs hold the same number
    of frames, i.e. the two people really were captured together."""
    path = Path(__file__).resolve().parent / "cmu_convert_all.py"
    spec = importlib.util.spec_from_file_location("cmu_convert_all", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.confirm_pairs


def build_groups(takes: list) -> tuple:
    """Duplicate groups: takes whose normalised description is the same."""
    buckets = {}
    for take in takes:
        norm = normalize_desc(take["description"])
        if not norm:
            continue
        buckets.setdefault(slug(norm), []).append(take)
    groups, of_take = {}, {}
    for key, members in buckets.items():
        label = Counter(t["description"] for t in members).most_common(1)[0][0]
        groups[key] = {"label": label, "take_ids": [t["id"] for t in members]}
        for take in members:
            of_take[take["id"]] = key
    return groups, of_take


def clip_paths(out: Path) -> dict:
    """take id → clip path from ``_index.json``; a pair's B side is the same
    record's ``__b`` file."""
    index_path = out / "_index.json"
    if not index_path.is_file():
        return {}
    try:
        records = json.loads(index_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    clips = {}
    for rec in records:
        clip = rec.get("clip")
        if not clip:
            continue
        clips[rec["id"]] = clip
        takes = rec.get("pair_takes") or []
        if rec.get("pair") and len(takes) == 2 and clip.endswith("__a.fbx"):
            clips[takes[1]] = clip[: -len("__a.fbx")] + "__b.fbx"
    return clips


def build_record(take: dict, mains: dict, subs: dict, pairs: set,
                 group_of: dict, clips: dict, measured: dict) -> dict:
    """One `_catalog.json` take — catalog facts, tags and measurements."""
    role, partner = take.get("pair_role", ""), take.get("pair_partner", "")
    is_pair = bool(partner) and (take["id"] in pairs or partner in pairs)
    cats = take.get("categories") or []
    return {
        "id": take["id"],
        "subject": take["subject"],
        "trial": take["trial"],
        "description": take.get("description", ""),
        "subject_description": take.get("subject_description", ""),
        "categories": cats,
        "category_labels": [f"{mains.get(c.split('/')[0], c)} / {subs.get(c, c)}"
                            for c in cats],
        "tags": tags_for(take, mains),
        "group": group_of.get(take["id"], ""),
        "framerate": take.get("framerate", 0),
        "duration_s": measured["duration_s"],
        "frames": measured["frames"],
        "pair": is_pair,
        "pair_role": role if is_pair else "",
        "pair_partner": partner if is_pair else "",
        "clip": clips.get(take["id"]),
        "metrics": measured["metrics"],
        "sparkline": measured["sparkline"],
        # Not for the browser: lets the next run tell a measurement that is
        # still valid from one whose AMC has been re-downloaded.
        "amc_mtime": measured["amc_mtime"],
    }


def write_catalog(path: Path, records: list, groups: dict) -> None:
    """Writes the whole catalog atomically (a browser may be reading it)."""
    tags = Counter(t for rec in records for t in rec["tags"])
    used = {rec["group"] for rec in records if rec["group"]}
    doc = {
        "generated": utc_now().isoformat(),
        "source": "cmu",
        "credit": CREDIT,
        "tags": {tag: {"label": TAG_LABELS.get(tag, tag), "count": n}
                 for tag, n in sorted(tags.items(), key=lambda kv: (-kv[1], kv[0]))},
        "facets": {"posture": POSTURE_VALUES, "energy": ENERGY_VALUES,
                   "travel": TRAVEL_VALUES, "duration": DURATION_VALUES},
        "groups": {k: v for k, v in sorted(groups.items()) if k in used},
        "takes": sorted(records, key=lambda r: (r["subject"], r["trial"])),
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--catalog", default="")
    ap.add_argument("--src", default="")
    ap.add_argument("--out", default="")
    ap.add_argument("--only", default="")
    ap.add_argument("--jobs", type=int, default=1)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    shared = paths.get_shared_dir() / "models"
    catalog_path = Path(args.catalog) if args.catalog else shared / "cmu_catalog.json"
    if not catalog_path.is_file():
        raise SystemExit(f"catalog not found: {catalog_path} — run scripts/cmu_catalog.py first")
    src = Path(args.src) if args.src else shared / "mocap-src" / "cmu"
    out = Path(args.out) if args.out else shared / "clips-trial"
    out.mkdir(parents=True, exist_ok=True)
    target = out / "_catalog.json"

    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    mains, subs = catalog["main_categories"], catalog["sub_categories"]
    takes = catalog["takes"]
    only = {x for x in args.only.replace(" ", "").split(",") if x} if args.only else set()
    if only:
        takes = [t for t in takes if t["id"] in only]

    groups, group_of = build_groups(catalog["takes"])
    pairs = load_confirm_pairs()(catalog["takes"], src)
    clips = clip_paths(out)
    print(f"{len(catalog['takes'])} takes, {len(pairs)} confirmed pairs, "
          f"{len(groups)} duplicate groups, {len(clips)} clips converted", flush=True)

    # What an earlier run already measured, keyed by id — reused when the AMC
    # has not been touched since.
    cached = {}
    if target.is_file() and not args.force:
        try:
            for rec in json.loads(target.read_text(encoding="utf-8"))["takes"]:
                cached[rec["id"]] = rec
        except Exception as e:
            print(f"  existing catalog unreadable ({e}) — measuring everything", flush=True)

    jobs, measured, missing = [], {}, 0
    for take in takes:
        amc = src / take["subject_dir"] / Path(take["amc"]).name
        if not amc.is_file():
            missing += 1
            continue
        old = cached.get(take["id"])
        if old and "metrics" in old and old.get("amc_mtime", 0) >= round(amc.stat().st_mtime, 3):
            measured[take["id"]] = old
            continue
        jobs.append((take["id"], take["subject_dir"], Path(take["asf"]).name,
                     amc.name, float(take.get("framerate") or _cmu.CMU_FPS)))
    if args.limit:
        jobs = jobs[:args.limit]
    print(f"{len(measured)} still valid, {len(jobs)} to measure, "
          f"{missing} without local originals → {target}", flush=True)

    by_id = {t["id"]: t for t in catalog["takes"]}
    errors = []

    def records() -> list:
        return [build_record(by_id[tid], mains, subs, pairs, group_of, clips, m)
                for tid, m in measured.items() if tid in by_id]

    started = time.time()
    done = 0

    def absorb(res: dict) -> None:
        nonlocal done
        done += 1
        if "error" in res:
            errors.append(res)
            print(f"  FAIL {res['id']}: {res['error'][:200]}", flush=True)
        else:
            measured[res["id"]] = res
        if done % 25 == 0 or done == len(jobs):
            rate = done / max(1e-6, time.time() - started)
            print(f"  -- {done}/{len(jobs)} measured ({len(errors)} failed), "
                  f"{rate * 60:.0f}/min", flush=True)
        if done % 100 == 0:
            write_catalog(target, records(), groups)

    if args.jobs > 1 and len(jobs) > 1:
        import multiprocessing as mp
        with mp.Pool(args.jobs, initializer=_init, initargs=(str(src),)) as pool:
            for res in pool.imap_unordered(_work, jobs, chunksize=1):
                absorb(res)
    else:
        _init(str(src))
        for job in jobs:
            absorb(_work(job))

    recs = records()
    write_catalog(target, recs, groups)
    if errors:
        (out / "_catalog_errors.json").write_text(
            json.dumps(sorted(errors, key=lambda e: e["id"]), indent=1), encoding="utf-8")
    size = target.stat().st_size / 1e6
    print(f"done: {len(recs)} takes in {target} ({size:.1f} MB), "
          f"{len(errors)} failed, {missing} still missing their originals", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
