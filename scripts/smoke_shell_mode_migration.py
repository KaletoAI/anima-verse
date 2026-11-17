"""Smoke: A168 — "Shell from the body" becomes its own mode (``app/core/shell_mode_migration.py``).

Usage:
    ./.venv/bin/python scripts/smoke_shell_mode_migration.py   (no server, no world DB; pure ``judge``)

Expected by hand from the rule (shell when a character stored ``mesh_shape: "shell"``, or close-fitting —
every slot in {underwear_top, underwear_bottom, legs}, no covers, not closable — and nobody stored
``"as_generated"``; only pieces in mode own_mesh are judged):

  briefs, own_mesh, no stored choice              -> shell   (the old Auto made shells of it)
  briefs, own_mesh, one wearer stored as_generated -> None   (stays own mesh)
  jeans (bottom), own_mesh, a wearer stored shell -> shell
  jeans (bottom), own_mesh, no stored choice      -> None
  briefs, mode painted                            -> None   (only own-mesh pieces are judged)
  briefs, mode shell already                      -> None
  a hair garment (category garment)               -> None
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
TMP = tempfile.mkdtemp(prefix="smoke_shell_mode_")
os.environ["STORAGE_DIR"] = TMP
os.environ["INSTANCE_DIR"] = TMP
from app.core import paths  # noqa: E402

paths.init(TMP)
from app.core.shell_mode_migration import judge  # noqa: E402

FAILS = []


def piece(slots, mode, covers=()):
    return {"category": "outfit_piece", "outfit_piece": {"slots": list(slots), "covers": list(covers),
                                                         "mesh_mode": mode}}


cases = [
    ("briefs own_mesh, no choice", piece(["underwear_bottom"], "own_mesh"), [], "shell"),
    ("briefs own_mesh, as_generated stored", piece(["underwear_bottom"], "own_mesh"), ["auto", "as_generated"], None),
    ("jeans own_mesh, shell stored", piece(["bottom"], "own_mesh", ["underwear_bottom"]), ["shell"], "shell"),
    ("jeans own_mesh, no choice", piece(["bottom"], "own_mesh", ["underwear_bottom"]), [], None),
    ("briefs painted", piece(["underwear_bottom"], "painted"), ["shell"], None),
    ("briefs already shell", piece(["underwear_bottom"], "shell"), [], None),
    ("hair garment", {"category": "garment", "garment": {"kind": "hair"}}, [], None),
]
for name, item, choices, want in cases:
    got = judge(item, choices)
    print(("ok   " if got == want else "FAIL ") + f"{name}: {got!r}")
    if got != want:
        FAILS.append(name)
print("FAILED: " + ", ".join(FAILS) if FAILS else "all pass")
sys.exit(1 if FAILS else 0)
