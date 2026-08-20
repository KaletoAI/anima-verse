#!/usr/bin/env python3
"""Imports CMU Graphics Lab mocap takes as shared animation clips.

Fetches the ASF/AMC files of one take (solo) or of two takes recorded together
(pair), retargets them onto the Mixamo rig with Blender (headless,
``app/blender/scripts/cmu_clip.py``) and drops the resulting FBX files plus
the ``<kind>.json`` sidecar into the shared clips directory — or any ``--out``.

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
    --fps <n>         output frame rate (default 30)
    --cache <dir>     where the downloaded ASF/AMC files are kept
                      (default: storage-independent ~/.cache/anima-verse/cmu)
    --rig <fbx>       Mixamo skeleton to drive (default: the library's own
                      idle.fbx, so the new clip shares the skeleton — and the
                      standing hip height the client normalises on — with
                      every other clip; x-bot.fbx when no idle clip exists)

A pair is written as ``<kind>__a.fbx`` + ``<kind>__b.fbx`` (A = first take);
the sidecar records the anchor geometry both clips share.
"""
import argparse
import json
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.blender import runner  # noqa: E402
from app.core import paths  # noqa: E402

CMU_BASE = "https://mocap.cs.cmu.edu/subjects"


def fetch(url: str, dest: Path) -> Path:
    """Downloads once; the CMU server ships an incomplete certificate chain,
    so a failed verification falls back to an unverified fetch — the data is
    public and its integrity is checked by the parser, not by TLS."""
    if dest.is_file() and dest.stat().st_size > 0:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            dest.write_bytes(r.read())
    except (urllib.error.URLError, ssl.SSLError) as e:
        print(f"  verified fetch failed ({e}); retrying without verification")
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(url, timeout=60, context=ctx) as r:
            dest.write_bytes(r.read())
    if dest.stat().st_size < 100:
        raise SystemExit(f"download of {url} looks empty — wrong take id?")
    return dest


def take_files(take: str, cache: Path) -> tuple:
    subject, _, trial = take.partition("_")
    if not (subject.isdigit() and trial.isdigit()):
        raise SystemExit(f"take must look like 18_01, got {take!r}")
    asf = fetch(f"{CMU_BASE}/{subject}/{subject}.asf", cache / f"{subject}.asf")
    amc = fetch(f"{CMU_BASE}/{subject}/{take}.amc", cache / f"{take}.amc")
    return asf, amc


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
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--cache", default=str(Path.home() / ".cache" / "anima-verse" / "cmu"))
    ap.add_argument("--rig", default="")
    a = ap.parse_args()

    kind = a.kind.strip().lower()
    if "__" in kind or not kind:
        raise SystemExit("kind must not be empty or contain '__' (the role separator)")
    cache = Path(a.cache)
    if a.rig:
        rig = Path(a.rig)
    else:
        # The library's own skeleton first: the client measures every clip's
        # standing hip height against the library median (figures.ts
        # adaptExternalClips), so a clip on a shorter rig (x-bot, hips 104 cm
        # vs 113 cm) would be read as "crouching" and sink into the ground.
        rig = paths.get_animation_clips_dir() / "idle.fbx"
        if not rig.is_file():
            rig = paths.get_test_figure_dir() / "x-bot.fbx"
    if not rig.is_file():
        raise SystemExit(f"rig not found: {rig}")
    out = Path(a.out) if a.out else paths.get_animation_clips_dir()
    if a.set:
        out = out / a.set.strip().lower()

    print(f"fetching take(s) into {cache}")
    inputs = {"rig": rig}
    takes = [a.take_a]
    if a.take_b:
        takes.append(a.take_b)
        for role, take in zip("ab", takes):
            asf, amc = take_files(take, cache)
            inputs[f"asf_{role}"] = asf
            inputs[f"amc_{role}"] = amc
    else:
        inputs["asf"], inputs["amc"] = take_files(a.take_a, cache)

    params = {"kind": kind, "fps": a.fps, "start_s": a.start, "end_s": a.end,
              "anchor_s": a.anchor, "in_place": bool(a.in_place),
              "source_takes": takes}
    st = runner.status()
    if not st["executable"]:
        raise SystemExit("no Blender executable found (image_generation.blender_executable)")
    print(f"retargeting with Blender {st['version']} → {out}")
    out.mkdir(parents=True, exist_ok=True)
    res = runner.run("cmu_clip", inputs=inputs, params=params, out_dir=out,
                     timeout_s=900)
    if not res["ok"]:
        print(f"FAILED: {res['error']}")
        return 1
    side = res["data"]
    print(json.dumps(side, indent=1, ensure_ascii=False))
    for slot, path in res["outputs"].items():
        print(f"  wrote {slot}: {path}")
    print(f"done in {res['seconds']:.1f}s — {side['frames']} frames, {side['duration_s']} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
