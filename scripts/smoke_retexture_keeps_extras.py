"""Smoke: the JPEG re-encode (``retexture.py``) keeps glTF extras (A166).

Usage: ./.venv/bin/python scripts/smoke_retexture_keeps_extras.py

A procedural part's material carries ``extras.attached_part``; the base-colour
reader (``base_body._base_color_targets``) skips such materials. Blender's glTF
exporter drops extras unless ``export_extras=True`` — the re-encoded outfit
model then had two base-colour images and every assembly failed with
"Expected exactly one base-colour image, found 2" (Gelina, 2026-11-17; proven on
a copy: the HEAD script reproduced it, the fixed one kept ``attached_part``).
Static check of the export call plus the reader rule on a hand-built document."""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
tree = ast.parse((ROOT / "app/blender/scripts/retexture.py").read_text())
calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "gltf"]
assert len(calls) == 1, calls
kw = {k.arg: k.value for k in calls[0].keywords}
assert isinstance(kw.get("export_extras"), ast.Constant) and kw["export_extras"].value is True, "export_extras missing"

from app.core.base_body import _base_color_targets  # noqa: E402
doc = {"images": [{"mimeType": "image/png"}, {"mimeType": "image/png"}], "textures": [{"source": 0}, {"source": 1}],
       "materials": [{"pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}},
                     {"pbrMetallicRoughness": {"baseColorTexture": {"index": 1}}}],
       "meshes": [{"primitives": [{"material": 0}, {"material": 1}]}], "nodes": [{"mesh": 0}]}
try:
    _base_color_targets(doc)
    raise AssertionError("two body materials must be refused")
except ValueError:
    pass
doc["materials"][1]["extras"] = {"attached_part": "x"}
assert _base_color_targets(doc) == (0, {0: "core"})
print("OK smoke_retexture_keeps_extras")
