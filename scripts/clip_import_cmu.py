#!/usr/bin/env python3
"""Imports CMU Graphics Lab mocap takes as shared animation clips.

Locates the ASF/AMC files of one take (solo) or of two takes recorded together
(pair), retargets them onto the Mixamo rig with Blender (headless,
``app/blender/scripts/cmu_clip.py``) and drops the resulting FBX files plus
the ``<kind>.json`` sidecar into the shared clips directory — or any ``--out``.

This is the CLI face of ``app/core/cmu_import.py``; the Poses admin tab's CMU
catalog browser does the same import through the same functions. Originals
already downloaded to ``shared/models/mocap-src/cmu`` are used as they are;
only a take missing there is fetched from CMU into ``--cache``.

The CMU database is free to copy, modify and redistribute (also commercially;
only reselling the data itself is excluded) and asks for the credit the
sidecar carries. That makes it the one mocap source whose clips may travel
WITH the repository, unlike the Mixamo library.

Usage:
    ./.venv/bin/python scripts/clip_import_cmu.py <kind> <take> [<take_b>] [options]

    # pair: subjects 18 (A) and 19 (B), take 01 — "walk, shake hands"
    ./.venv/bin/python scripts/clip_import_cmu.py handshake 18_01 19_01

    # pair: salsa (subjects 60/61), only the dancing part of the take
    ./.venv/bin/python scripts/clip_import_cmu.py salsa 60_01 61_01 --start 2

    # solo, horizontal root travel removed ("In Place")
    ./.venv/bin/python scripts/clip_import_cmu.py dance 55_02 --in-place

Options:
    --set <name>      write into the set subdirectory (female, male, …)
    --out <dir>       target directory (default: the shared clips directory)
    --start/--end <s> keep only this window of the take (seconds)
    --anchor <s>      pair: second that defines the anchor frame
                      (default: when the two roots are closest)
    --in-place        solo: strip the horizontal root travel
    --source-fps <n>  capture rate of the take (default: the catalog's value,
                      120 without one; 326 takes were captured at 60 Hz)
    --loop <s>        solo: cut to the best-closing window of at least <s>
                      seconds (end pose closest to start pose) and ease the
                      last frames into the first — a seamless cycle for
                      walk/run/idle-type clips
    --fps <n>         output frame rate (default 30)
    --cache <dir>     where the downloaded ASF/AMC files are kept
                      (default: storage-independent ~/.cache/anima-verse/cmu)
    --rig <fbx>       Mixamo skeleton to drive (default: the first idle.fbx of
                      the free, then the licensed library, so the new clip
                      shares the skeleton — and the standing hip height the
                      client normalises on — with every other clip; x-bot.fbx
                      when no idle clip exists)

A pair is written as ``<kind>__a.fbx`` + ``<kind>__b.fbx`` (A = first take);
the sidecar records the anchor geometry both clips share.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.blender import runner  # noqa: E402
from app.core import paths  # noqa: E402
from app.core.cmu_import import (ClipImportError, convert_take,  # noqa: E402
                                 default_cache_dir, default_rig)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("kind")
    ap.add_argument("take_a")
    ap.add_argument("take_b", nargs="?")
    ap.add_argument("--set", default="")
    ap.add_argument("--out", default="")
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--end", type=float, default=None)
    ap.add_argument("--anchor", type=float, default=None)
    ap.add_argument("--in-place", action="store_true")
    ap.add_argument("--loop", type=float, default=None)
    ap.add_argument("--source-fps", type=float, default=None,
                    help="capture rate; default: from shared/models/cmu_catalog.json, else 120")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--cache", default=str(default_cache_dir()))
    ap.add_argument("--rig", default="")
    a = ap.parse_args()

    out_dir = Path(a.out) if a.out else paths.get_animation_clips_dir()
    rig = Path(a.rig) if a.rig else default_rig()
    st = runner.status()
    print(f"fetching take(s) into {a.cache} (originals under "
          f"{paths.get_mocap_source_dir()} are used when present)")
    print(f"retargeting with Blender {st['version']} on rig {rig} -> {out_dir}")
    try:
        res = convert_take(a.kind, a.take_a, a.take_b or "", out_dir=out_dir,
                           clip_set=a.set, start_s=a.start, end_s=a.end,
                           anchor_s=a.anchor, in_place=a.in_place, loop_s=a.loop,
                           source_fps=a.source_fps, fps=a.fps, rig=rig,
                           cache=Path(a.cache))
    except ClipImportError as e:
        print(f"FAILED: {e}")
        return 1
    side = res["sidecar"]
    print(json.dumps(side, indent=1, ensure_ascii=False))
    for slot, path in res["outputs"].items():
        print(f"  wrote {slot}: {path}")
    print(f"done in {res['seconds']:.1f}s — {side['frames']} frames, "
          f"{side['duration_s']} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
