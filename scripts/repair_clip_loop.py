#!/usr/bin/env python3
"""Eases the tail of loop clips into their head, in place
(``app/blender/scripts/clip_loop_blend.py``) — for loop clips whose source
is gone (Kimodo/Meshy imports), so the converter's loop search cannot cut
them again. Measured 2026-10-24: `forehead-wiping` and `cleaning-table`
jumped 6 cm, `sitting-at-the-table` 8 cm at their seam.

Usage:
    ./.venv/bin/python scripts/repair_clip_loop.py <clip.fbx> [...]          # DRY RUN
    ./.venv/bin/python scripts/repair_clip_loop.py --apply <clip.fbx> [...]

Options:
    --apply             write. Without it NOTHING is touched.
    --blend-frames <k>  the blend window (default 8, the converter's)
    --min-seam <cm>     only clips whose seam is at least this (default 2)

Only git-tracked clips whose sidecar says ``loop: true`` (a pair: name both
halves, each is blended into its own first frame). The sidecar gets
``source.loop_blended`` (file -> blend frames) and ``source.loop_blended_at``.
"""
import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.blender import runner                         # noqa: E402
from app.core.timeutils import utc_now                  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def sidecar_of(clip: Path) -> Path:
    stem = clip.stem
    for role in ("__a", "__b"):
        if stem.endswith(role):
            stem = stem[: -len(role)]
    return clip.with_name(stem + ".json")


def indent_of(path: Path) -> int:
    lines = path.read_text(encoding="utf-8").splitlines()
    return max(1, len(lines[1]) - len(lines[1].lstrip(" "))) if len(lines) > 1 else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("files", nargs="+")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--blend-frames", type=int, default=8)
    ap.add_argument("--min-seam", type=float, default=2.0)
    a = ap.parse_args()
    clips = [Path(f).resolve() for f in a.files]
    rel = [str(c.relative_to(ROOT)) for c in clips]
    tracked = set(subprocess.run(["git", "-C", str(ROOT), "ls-files", "--", *rel],
                                 capture_output=True, text=True, check=True).stdout.split("\n"))
    for c, r in zip(clips, rel):
        if r not in tracked:
            print(f"refused (not tracked by git): {r}")
            return 2
        side = sidecar_of(c)
        if not side.is_file() or not json.loads(side.read_text(encoding="utf-8")).get("loop"):
            print(f"refused (no loop clip): {r}")
            return 2
    with tempfile.TemporaryDirectory(prefix="clip-loop-") as tmp:
        inputs = {f"src_{i}": c for i, c in enumerate(clips)}
        res = runner.run("clip_loop_blend", inputs=inputs,
                         params={"blend_frames": a.blend_frames, "dry_run": True},
                         out_dir=Path(tmp), timeout_s=900)
        if not res["ok"]:
            print(f"error: {res['error']}")
            return 1
        todo = {}
        for slot, clip in inputs.items():
            d = res["data"]["clips"][slot]
            print(f"{clip.name}: seam {d.get('seam_before_cm')} cm" + (f" ({d['skipped']})" if d.get("skipped") else ""))
            if not d.get("skipped") and d["seam_before_cm"] >= a.min_seam:
                todo[slot] = clip
        if not a.apply or not todo:
            print(f"{len(todo)} clip(s) {'would be blended' if not a.apply else 'to blend'}")
            return 0
        res = runner.run("clip_loop_blend", inputs=todo, params={"blend_frames": a.blend_frames},
                         out_dir=Path(tmp), timeout_s=900)
        if not res["ok"]:
            print(f"error: {res['error']}")
            return 1
        for slot, clip in todo.items():
            d = res["data"]["clips"][slot]
            shutil.copyfile(res["outputs"][slot], clip)
            side = sidecar_of(clip)
            doc = json.loads(side.read_text(encoding="utf-8"))
            src = doc.setdefault("source", {})
            src.setdefault("loop_blended", {})[clip.name] = a.blend_frames
            src["loop_blended_at"] = utc_now().date().isoformat()
            side.write_text(json.dumps(doc, indent=indent_of(side)), encoding="utf-8")
            print(f"  {clip.name}: seam {d['seam_before_cm']} -> {d['seam_after_cm']} cm, "
                  f"untouched frames {d['untouched_max_deg']} deg — written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
