"""Usage: .venv/bin/python scripts/smoke_lod_disabled_groups.py

The distance tier re-measures only ENABLED captured extension groups.
Hand-derived: groups a (pair_protrusion, enabled), b (pair_tip, disabled)
and p (inset_part, enabled, a built part) -> the low-tier measurement gets
exactly [a]. With a disabled as well, nothing is left to measure: no
extension_bones run, and the LOD still succeeds (the old filter measured
the disabled groups, found them absent and failed the whole rebuild with
"Low tier metrics failed"). Blender, validation and groups are patched;
storage is a temp dir initialised before any world module import.
"""
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths

with tempfile.TemporaryDirectory() as tmp:
    paths.init(tmp)
    from app.core.db import init_schema
    init_schema()
    from app.core import model3d, extension_rig
    from app.blender import runner
    model_dir = Path(tmp) / "characters" / "demo" / "model3d"
    model_dir.mkdir(parents=True)
    source = model_dir / "sig.glb"
    source.write_bytes(b"glb")
    (model_dir / "sig.json").write_text(json.dumps({"rig": "mixamo", "extension_rig": {"status": "applied"}}))
    calls = []

    def fake_run(script, inputs=None, params=None, out_dir=None, timeout_s=None, **_):
        calls.append((script, params))
        if script == "lod":
            low = Path(out_dir) / "low.glb"
            low.write_bytes(b"low")
            return {"ok": True, "outputs": {"model": str(low)}, "data": {"stages": [{"tris": 1, "tris_before": 4}]}}
        return {"ok": True, "data": {"status": "applied", "metrics": {}}}

    def groups(enabled_a):
        return lambda *_a, **_k: [
            {"id": "a", "op": "pair_protrusion", "enabled": enabled_a},
            {"id": "b", "op": "pair_tip", "enabled": False},
            {"id": "p", "op": "inset_part", "enabled": True}]

    with patch.object(model3d, "_validator_for", return_value=lambda blob: {"ok": True}), \
            patch("app.core.model_validate.rig_frames_preserved", return_value={"ok": True}), \
            patch.object(runner, "run", side_effect=fake_run):
        with patch.object(extension_rig, "resolved_extension_groups", groups(True)):
            result = model3d.build_lod("demo", "sig", ratio=.25)
        assert result["ok"], result
        measured = [p["groups"] for s, p in calls if s == "extension_bones"]
        assert [[g["id"] for g in m] for m in measured] == [["a"]], measured
        calls.clear()
        with patch.object(extension_rig, "resolved_extension_groups", groups(False)):
            result = model3d.build_lod("demo", "sig", ratio=.25)
        assert result["ok"], result
        assert [s for s, _ in calls] == ["lod"], calls
print("PASS LOD measures only enabled captured groups; none left = no measurement, LOD ok")
