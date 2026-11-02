"""Export resolved library animations on the reference rig as centimetre BVH."""
import math
from pathlib import Path
import tempfile
from typing import Optional

from app.blender import runner
from app.core import paths
from app.core.animation_clips import clip_entries


def export_clip_bvh(kind: str, cset: str, out_path: Path, *,
                    start_s: float = 0.0, end_s: Optional[float] = None,
                    fps: int = 30) -> dict:
    """Resolve set before neutral, retaining the winning library's provenance."""
    if isinstance(fps, bool) or not isinstance(fps, int) or fps <= 0:
        raise ValueError("fps must be a positive integer")
    if not math.isfinite(start_s) or start_s < 0:
        raise ValueError("start_s must be finite and nonnegative")
    if end_s is not None and (not math.isfinite(end_s) or end_s <= start_s):
        raise ValueError("end_s must be finite and greater than start_s")
    entries = clip_entries()
    entry = None
    for wanted in dict.fromkeys((cset.strip().lower(), "")):
        matches = [e for e in entries if e["kind"] == kind and e["set"] == wanted
                   and e["path"].suffix.lower() == ".fbx"]
        if matches:
            entry = matches[0]
            break
    if entry is None:
        raise ValueError(f"library clip not found: {kind!r} (set {cset!r})")
    out_path = Path(out_path)
    with tempfile.TemporaryDirectory(prefix="clip-bvh-export-") as temporary:
        result = runner.run("clip_to_bvh", inputs={"clip": entry["path"],
                                                  "rig": paths.get_rig_file()},
                            params={"start_s": start_s, "end_s": end_s, "fps": fps},
                            out_dir=Path(temporary), timeout_s=900)
        if not result["ok"]:
            raise RuntimeError(f"BVH export failed: {result['error']}")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(Path(result["outputs"]["bvh"]).read_bytes())
    return {**result["data"], "source_rel": entry["rel"], "library": entry["source"]}
