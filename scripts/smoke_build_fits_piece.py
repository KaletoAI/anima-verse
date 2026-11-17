"""Smoke: the piece dialog waits for a running Build only when that Build fits the piece (A166).

Usage: ./.venv/bin/python scripts/smoke_build_fits_piece.py

Glut's briefs (2026-11-17): a Build planned before the briefs' fit became due ran for 15 minutes; the fit row said
"Waits for the running Build — it fits this piece too" although its plan had no step of the briefs. Hand-derived
cases of ``figure_build.fits_piece`` (plan = the run's steps, ``index`` 1-based = the step in flight):
  no Build                                  -> False
  plan [pieces A, texture, fits], at 1      -> A True, B False
  same plan, at step 2 (A's chain is past)  -> A False
  B's chain running now (_own_chains)       -> B True
Plus: saving fit settings asks for a Build (``figure_build.request(.., "fit_settings")`` in the route), and
``dismiss_failure`` drops the last run's failure of one step only."""
import ast
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
tmp = tempfile.mkdtemp()
os.environ.setdefault("STORAGE_DIR", tmp)
from app.core import paths  # noqa: E402
paths.init(tmp)
from app.core import figure_build as fb  # noqa: E402

c = "demo"
ok = 0


def check(name, got, want):
    global ok
    assert got == want, f"{name}: got {got!r}, want {want!r}"
    ok += 1


check("no build", fb.fits_piece(c, "A"), False)
steps = [{"name": "pieces", "item_id": "A"}, {"name": "texture", "item_id": ""}, {"name": "fits", "item_id": ""}]
with fb._lock:
    fb._active.add(c)
    fb._current[c] = {"reason": "x", "step": {"index": 1}, "steps": steps}
check("A planned", fb.fits_piece(c, "A"), True)
check("B not planned", fb.fits_piece(c, "B"), False)
with fb._lock:
    fb._current[c]["step"] = {"index": 2}
check("A past", fb.fits_piece(c, "A"), False)
with fb._lock:
    fb._own_chains[c] = {"B"}
check("B chain runs", fb.fits_piece(c, "B"), True)
with fb._lock:
    fb._active.discard(c)
    fb._own_chains.pop(c, None)
    fb._current.pop(c, None)
    fb._last[c] = {"failed": {"assemble": {"error": "x", "item_id": ""}, "texture": {"error": "y", "item_id": ""}}}
fb._notify_build_changed = lambda: None
check("dismiss texture", fb.dismiss_failure(c, "texture"), True)
check("assemble kept", sorted(fb.state(c)["failed"]), ["assemble"])
check("dismiss again", fb.dismiss_failure(c, "texture"), False)

src = (ROOT / "app/routes/characters.py").read_text()
fn = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef)
          and "set_fit_settings" in ast.get_source_segment(src, n) and "fit_settings" in n.name)
check("route requests a Build", '"fit_settings")' in ast.get_source_segment(src, fn)
      and "figure_build.request(" in ast.get_source_segment(src, fn), True)
print(f"OK smoke_build_fits_piece ({ok} checks)")
