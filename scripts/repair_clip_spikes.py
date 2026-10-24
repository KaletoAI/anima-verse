#!/usr/bin/env python3
"""Clears one- and two-frame GLITCHES out of the free clip library in place
(``app/blender/scripts/clip_despike.py``): a joint that turns more than
``_cmu.SPIKE_DEG`` (10 deg) into a frame and back out of it, landing where
it started — the knee a leg IK flipped for one frame, a toe that snapped.
Measured 2026-10-24 on the CMU clips: `waiting` (male) LeftLeg at 14.4 s,
`sleeping-side` forearm on frame 1, `yoga` and `drinking` toes. The
converter repairs new clips itself (``cmu_clip._bake``); this script brings
the existing ones up to that state without converting them again, so their
window, loop cut and roll repair stay as they are.

Usage:
    ./.venv/bin/python scripts/repair_clip_spikes.py               # DRY RUN over the library
    ./.venv/bin/python scripts/repair_clip_spikes.py --apply       # repair what the dry run finds
    ./.venv/bin/python scripts/repair_clip_spikes.py <clip.fbx> [...]          # only these (dry run)
    ./.venv/bin/python scripts/repair_clip_spikes.py --apply <clip.fbx> [...]

Options:
    --apply          write. Without it NOTHING is touched.
    --max-deg <deg>  the spike threshold (default 10)
    --timeout <s>    Blender timeout per run (default 900)

Which clips: the clips of ``shared/models/clips`` (subdirectories included)
that git TRACKS — git keeps the original, so no ``.bak`` is written, and a
local, untracked clip is never rewritten. Naming a file that git does not
track is refused.

Applying: the repaired clip is written to a temporary file by Blender, which
verifies it in the scene (frames without a repair, and bones that neither
were repaired nor hang on one, within 0.05 deg of the import); only then is
the library file replaced. The sidecar gets ``source.despiked`` (file ->
bone -> repaired frames, 0-based) and ``source.despiked_at``.

Needs Blender (auto-discovered, or image_generation.blender_executable). No
server, no world DB.
"""
import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.blender import runner                         # noqa: E402
from app.core.timeutils import utc_now                  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
LIBRARY = ROOT / "shared/models/clips"


def sidecar_of(clip: Path) -> Path:
    stem = clip.stem
    for role in ("__a", "__b"):
        if stem.endswith(role):
            stem = stem[: -len(role)]
    return clip.with_name(stem + ".json")


def indent_of(path: Path) -> int:
    """The indent a JSON file is written with (the converter writes 1, the
    Poses tab 2) — a rewrite keeps the file's own layout."""
    lines = path.read_text(encoding="utf-8").splitlines()
    if len(lines) > 1:
        return max(1, len(lines[1]) - len(lines[1].lstrip(" ")))
    return 1


def tracked(paths: List[Path]) -> List[Path]:
    """The given files git tracks (repo-relative check, any cwd)."""
    rel = [str(p.resolve().relative_to(ROOT)) for p in paths]
    out = subprocess.run(["git", "-C", str(ROOT), "ls-files", "--", *rel],
                         capture_output=True, text=True, check=True).stdout.split("\n")
    known = {ROOT / x for x in out if x}
    return [p for p in paths if p.resolve() in known]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("files", nargs="*")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--max-deg", type=float, default=10.0)
    ap.add_argument("--timeout", type=int, default=900)
    a = ap.parse_args()

    if a.files:
        clips = [Path(f).resolve() for f in a.files]
        untracked = sorted(set(clips) - set(tracked(clips)))
        if untracked:
            print("refused (not tracked by git): " + ", ".join(map(str, untracked)))
            return 2
    else:
        clips = tracked(sorted(LIBRARY.rglob("*.fbx")))
    if not clips:
        print("no clips")
        return 0

    with tempfile.TemporaryDirectory(prefix="clip-despike-") as tmp:
        inputs = {f"src_{i}": c for i, c in enumerate(clips)}
        res = runner.run("clip_despike", inputs=inputs,
                         params={"max_deg": a.max_deg, "dry_run": not a.apply},
                         out_dir=Path(tmp), timeout_s=a.timeout)
        if not res["ok"]:
            print(f"error: {res['error']}")
            return 1
        data = res["data"]["clips"]
        hits = 0
        for slot, clip in inputs.items():
            rep = data[slot]["repaired"]
            if not rep:
                continue
            hits += 1
            n = sum(len(v) for v in rep.values())
            print(f"{clip.relative_to(LIBRARY)}: {n} key(s) — "
                  + ", ".join(f"{b} {v}" for b, v in sorted(rep.items())))
            if not a.apply:
                continue
            out = res["outputs"].get(slot)
            if not out:
                print(f"  error: no file written for {clip.name}")
                return 1
            shutil.copyfile(out, clip)
            side = sidecar_of(clip)
            if side.is_file():
                doc = json.loads(side.read_text(encoding="utf-8"))
                src = doc.setdefault("source", {})
                src.setdefault("despiked", {})[clip.name] = rep
                src["despiked_at"] = utc_now().date().isoformat()
                side.write_text(json.dumps(doc, indent=indent_of(side)), encoding="utf-8")
            print(f"  written ({data[slot].get('verify')})")
        print(f"{hits} of {len(clips)} clip(s) {'repaired' if a.apply else 'would be repaired'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
