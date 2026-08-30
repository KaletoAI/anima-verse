#!/usr/bin/env python3
"""Converts every CMU take into the trial clip library, sorted by category.

Reads ``shared/models/cmu_catalog.json`` and the originals fetched by
``scripts/cmu_fetch_all.py``, retargets each take onto the project's reference
skeleton with the same Blender script the single-take import uses
(``app/blender/scripts/cmu_clip.py``) and writes

    shared/models/clips-trial/<main-category>/<sub-category>/<id>.fbx
                                                            /<id>.json

Takes that no category lists land under ``uncategorized/``. A take recorded
with two people is converted ONCE, as a pair, from the A side: it produces
``<id_a>__a.fbx`` + ``<id_a>__b.fbx`` and keeps the two skeletons in the frame
they were recorded in; the B side is not converted on its own. Solo takes are
converted in place (no horizontal root travel) and without loop cutting — this
is a browsing archive, not a curated set.

Resumable: an existing FBX is skipped. A take that fails is recorded in
``_errors.json`` and the run continues. ``_index.json`` collects what a catalog
browser needs — id, category path, clip path, duration, pair flag, description.

Usage:
    ./.venv/bin/python scripts/cmu_convert_all.py [options]

    # one category only, three Blender runs in parallel
    ./.venv/bin/python scripts/cmu_convert_all.py --only-main 3 --jobs 3

Options:
    --catalog <file>  catalog to read (default: shared/models/cmu_catalog.json)
    --src <dir>       downloaded originals (default: shared/models/mocap-src/cmu)
    --out <dir>       clip target (default: shared/models/clips-trial)
    --rig <fbx>       skeleton to drive (default: the reference skeleton
                      shared/models/rig/reference.fbx)
    --only-main <n>   restrict to one main category id
    --only <list>     comma-separated take ids (e.g. 18_01,55_02)
    --jobs <n>        parallel Blender runs (default 1)
    --fps <n>         output frame rate (default 30)
    --timeout <s>     per-take Blender timeout (default 1800)
    --limit <n>       stop after n conversions (a smoke run)
"""
import argparse
import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.blender import runner  # noqa: E402
from app.core import paths  # noqa: E402

UNCATEGORIZED = "uncategorized"


def slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    return s or "misc"


def rig_path(explicit: str) -> Path:
    """The skeleton every clip is driven on — the project's reference rig.

    All clips must share ONE skeleton: the client normalises a clip against the
    library's standing hip height, so a clip baked on a shorter rig would read
    as "crouching" and sink into the ground. Which is why the reference is a
    file of its own (``shared/models/rig/``) and not picked out of the clip
    library.
    """
    return Path(explicit) if explicit else paths.get_rig_file()


def category_dir(take: dict, mains: dict, subs: dict) -> str:
    """Relative "<main>/<sub>" directory a take is filed under."""
    if not take["categories"]:
        return UNCATEGORIZED
    key = take["categories"][0]
    main_id = key.split("/")[0]
    return f"{slug(mains.get(main_id, main_id))}/{slug(subs.get(key, key))}"


def amc_frames(path: Path) -> int:
    """Number of frames in an AMC — every frame opens with its bare number."""
    n = 0
    try:
        with open(path, "r", errors="replace") as fh:
            for line in fh:
                if line.strip().isdigit():
                    n += 1
    except OSError:
        return -1
    return n


def confirm_pairs(takes: list, src: Path) -> set:
    """Take ids that really are one recording seen from two skeletons.

    The catalog pairs subjects by their descriptions, which over-reaches: two
    people who each walked once for the camera read the same as two people who
    walked TOGETHER. Simultaneous capture is what settles it — both AMC files
    then hold exactly the same number of frames.
    """
    confirmed = set()
    by_id = {t["id"]: t for t in takes}
    for take in takes:
        if take["pair_role"] != "a" or not take["pair_partner"]:
            continue
        partner = by_id.get(take["pair_partner"])
        if not partner:
            continue
        a = amc_frames(src / take["subject_dir"] / Path(take["amc"]).name)
        b = amc_frames(src / partner["subject_dir"] / Path(partner["amc"]).name)
        if a > 0 and a == b:
            confirmed.add(take["id"])
    return confirmed


def plan(catalog: dict, src: Path, out: Path, args) -> list:
    """Which takes to convert, in catalog order, pairs folded onto their A side."""
    mains, subs = catalog["main_categories"], catalog["sub_categories"]
    by_id = {t["id"]: t for t in catalog["takes"]}
    only = {x for x in args.only.replace(" ", "").split(",") if x} if args.only else set()
    pairs = confirm_pairs(catalog["takes"], src)
    jobs = []
    for take in catalog["takes"]:
        if take["pair_role"] == "b" and take["pair_partner"] in pairs:
            continue                                   # converted with its A side
        if only and take["id"] not in only:
            continue
        rel = category_dir(take, mains, subs)
        if args.only_main and not (take["categories"] and
                                   take["categories"][0].split("/")[0] == str(args.only_main)):
            continue
        partner = by_id.get(take["pair_partner"]) if take["id"] in pairs else None
        target = out / rel
        files = {"asf": src / take["subject_dir"] / Path(take["asf"]).name,
                 "amc": src / take["subject_dir"] / Path(take["amc"]).name}
        if partner:
            files = {"asf_a": files["asf"], "amc_a": files["amc"],
                     "asf_b": src / partner["subject_dir"] / Path(partner["asf"]).name,
                     "amc_b": src / partner["subject_dir"] / Path(partner["amc"]).name}
        jobs.append({"take": take, "partner": partner, "rel": rel,
                     "dir": target, "inputs": files,
                     "probe": target / (f"{take['id']}__a.fbx" if partner
                                        else f"{take['id']}.fbx")})
    return jobs


def index_record(job: dict, sidecar: dict, args, seconds: float) -> dict:
    """One `_index.json` entry — what a catalog browser needs about a clip."""
    take = job["take"]
    partner = job["partner"]
    return {
        "id": take["id"],
        "category": job["rel"],
        "clip": str(job["probe"].relative_to(args.out_root)),
        "duration_s": sidecar.get("duration_s", 0.0),
        "frames": sidecar.get("frames", 0),
        "pair": bool(partner),
        "pair_takes": [take["id"], partner["id"]] if partner else [],
        "description": take["description"],
        "subject": take["subject"],
        "trial": take["trial"],
        "source_framerate": take.get("framerate", 0),
        # The capture rate is handed to the converter (``source_fps``), so a
        # 60 Hz take plays at its real speed; the factor stays in the index
        # only to tell a clip converted BEFORE that fix (2026-08-21) apart.
        "speed_factor": 1.0,
        "seconds": round(seconds, 1),
    }


def convert(job: dict, rig: Path, args) -> dict:
    """Runs one take through Blender and returns an index/error record."""
    take = job["take"]
    missing = [str(p) for p in job["inputs"].values() if not Path(p).is_file()]
    if missing:
        return {"id": take["id"], "error": "missing source files: " + ", ".join(missing)}
    inputs = {"rig": rig}
    inputs.update({k: Path(v) for k, v in job["inputs"].items()})
    params = {"kind": take["id"], "fps": args.fps, "start_s": 0.0, "end_s": None,
              "anchor_s": None, "in_place": not job["partner"], "loop_s": None,
              "source_fps": float(take.get("framerate") or 120),
              "source_takes": [take["id"]] + ([job["partner"]["id"]] if job["partner"] else [])}
    job["dir"].mkdir(parents=True, exist_ok=True)
    res = runner.run("cmu_clip", inputs=inputs, params=params, out_dir=job["dir"],
                     timeout_s=args.timeout)
    if not res["ok"]:
        return {"id": take["id"], "error": str(res["error"])[:2000]}
    return index_record(job, res["data"] or {}, args, res["seconds"])


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--catalog", default="")
    ap.add_argument("--src", default="")
    ap.add_argument("--out", default="")
    ap.add_argument("--rig", default="")
    ap.add_argument("--only-main", type=int, default=0)
    ap.add_argument("--only", default="")
    ap.add_argument("--jobs", type=int, default=1)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    shared = paths.get_shared_dir() / "models"
    catalog_path = Path(args.catalog) if args.catalog else shared / "cmu_catalog.json"
    if not catalog_path.is_file():
        raise SystemExit(f"catalog not found: {catalog_path} — run scripts/cmu_catalog.py first")
    src = Path(args.src) if args.src else shared / "mocap-src" / "cmu"
    out = Path(args.out) if args.out else shared / "clips-trial"
    args.out_root = out
    rig = rig_path(args.rig)
    if not rig.is_file():
        raise SystemExit(f"rig not found: {rig} — see shared/models/rig/README.md")
    st = runner.status()
    if not st["executable"]:
        raise SystemExit("no Blender executable found (image_generation.blender_executable)")

    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    jobs = plan(catalog, src, out, args)
    out.mkdir(parents=True, exist_ok=True)
    index_path, errors_path = out / "_index.json", out / "_errors.json"
    index = {}
    if index_path.is_file():
        index = {e["id"]: e for e in json.loads(index_path.read_text(encoding="utf-8"))}
    errors = {}
    if errors_path.is_file():
        errors = {e["id"]: e for e in json.loads(errors_path.read_text(encoding="utf-8"))}

    # An FBX from an earlier run that the index does not know (index deleted,
    # run killed between clip and flush) is re-indexed from its own sidecar
    # instead of being converted again.
    for job in jobs:
        take_id = job["take"]["id"]
        side = job["dir"] / f"{take_id}.json"
        if job["probe"].is_file() and take_id not in index and side.is_file():
            try:
                index[take_id] = index_record(job, json.loads(side.read_text(encoding="utf-8")),
                                              args, 0.0)
            except Exception as e:
                print(f"  sidecar unreadable for {take_id}: {e}", flush=True)

    todo = [j for j in jobs if not j["probe"].is_file()]
    if args.limit:
        todo = todo[:args.limit]
    print(f"Blender {st['version']} · rig {rig}", flush=True)
    print(f"{len(jobs)} takes planned, {len(jobs) - len(todo)} already converted, "
          f"{len(todo)} to do → {out}", flush=True)

    lock = threading.Lock()
    counter = {"ok": 0, "fail": 0}
    started = time.time()

    def flush() -> None:
        index_path.write_text(json.dumps(sorted(index.values(), key=lambda e: e["id"]),
                                         indent=1, ensure_ascii=False), encoding="utf-8")
        errors_path.write_text(json.dumps(sorted(errors.values(), key=lambda e: e["id"]),
                                          indent=1, ensure_ascii=False), encoding="utf-8")

    def work(job: dict) -> None:
        take_id = job["take"]["id"]
        try:
            rec = convert(job, rig, args)
        except Exception as e:                       # never let one take stop the run
            rec = {"id": take_id, "error": f"{type(e).__name__}: {e}"}
        with lock:
            if "error" in rec:
                errors[take_id] = rec
                counter["fail"] += 1
                print(f"  FAIL {take_id} ({job['rel']}): {rec['error'][:200]}", flush=True)
            else:
                index[take_id] = rec
                errors.pop(take_id, None)
                counter["ok"] += 1
                print(f"  ok   {take_id} ({job['rel']}) {rec['duration_s']}s clip "
                      f"in {rec['seconds']}s", flush=True)
            n = counter["ok"] + counter["fail"]
            if n % 10 == 0 or n == len(todo):
                flush()
                rate = n / max(1e-6, time.time() - started)
                print(f"  -- {n}/{len(todo)} done ({counter['fail']} failed), "
                      f"{rate * 3600:.0f}/h", flush=True)

    if args.jobs > 1:
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            list(pool.map(work, todo))
    else:
        for job in todo:
            work(job)

    # Takes converted by an earlier run keep their index entry; drop entries
    # whose clip has since been deleted so the index never lies.
    for take_id in [k for k, e in index.items() if not (out / e["clip"]).is_file()]:
        index.pop(take_id)
    flush()
    print(f"done: {counter['ok']} converted, {counter['fail']} failed, "
          f"{len(index)} clips in the index", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
