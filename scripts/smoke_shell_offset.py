"""Smoke: the per-piece shell offset (A166).

Usage: ./.venv/bin/python scripts/smoke_shell_offset.py

Glut's scale bra: the shell lay at a constant 4 mm on the skin (over_skin p50 = p95 = 4.0 mm) — molded cups look
painted on. ``shell_offset`` (mm, choices 4/6/8/10/12/16, default 4) is a fit setting; measured on a copy, the same
shell at 10 mm reads over_skin p50 = p95 = 10.0 mm and inside_share 0.0005 (4 mm: 0.00508). Checks by hand:
  default / missing / bad value -> 4; 10 -> 10; validate(7) refused; a record without the key = made at 4;
  a shell made at 4 with the setting 10 is due; the same pair on a piece that is NOT a shell is not due."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.core import garment_fit_settings as fs, garment_shell as gsh  # noqa: E402

assert gsh.shell_offset_choice(None) == 4 and gsh.shell_offset_choice({"shell_offset": 7}) == 4
assert gsh.shell_offset_choice({"shell_offset": 10}) == 10
assert fs.validate({"shell_offset": 10}) == {"shell_offset": 10}
try:
    fs.validate({"shell_offset": 7})
    raise AssertionError("7 mm must be refused")
except ValueError:
    pass
assert fs.recorded({"inputs": {"fit_settings": {}}})["shell_offset"] == 4
rec = {"inputs": {"fit_settings": {}, "mesh_shape": "shell"}}
# A168: the shape is the item's mode (no setting) — stand in for the item's mode here.
MODE = {"x": "shell"}
fs.current_shape = lambda settings, item_id: MODE[item_id]
prof = {fs.SETTINGS_KEY: {"x": {"shell_offset": 10}}}
assert fs.changed(rec, prof, "x") is True
MODE["x"] = "as_generated"
rec2 = {"inputs": {"fit_settings": {}, "mesh_shape": "as_generated"}}
prof2 = {fs.SETTINGS_KEY: {"x": {"shell_offset": 10}}}
assert fs.changed(rec2, prof2, "x") is False
print("OK smoke_shell_offset")
