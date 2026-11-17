"""A191 — the arm never hides the flank from a shell's side view; a shell made with side views by the old merge is due.

Usage: ./.venv/bin/python scripts/smoke_shell_side_occlusion.py   (no server, no world DB)

Cause (A191, Glut's Schuppen-BH): the base side view is a profile with the arm hanging beside the trunk. The side
z-buffers were built from EVERY body sample, so from the +x / -x camera the arm (in front of the flank) was the
front-most surface and the flank under it was never "seen" within the 1.5 cm depth window — exactly the band the
piece-only side view shows (it removes the arm). On a copy of Glut the side views added 350 / 401 vertices and moved
flank coverage 0.743 -> 0.769; without the arm as occluder 551 / 549 and 0.829 (report a191).

Expected values derived by hand:
[O1] ``occluding_samples``: mesh of 2 faces — face 0 = arm (vertices 0,1,2 armw 1.0, at x = 0.20), face 1 = trunk
     (vertices 3,4,5 armw 0.0, at x = 0.10). Samples on faces [0, 0, 1].
       front "f" / back "b": all 3 samples.
       side "l" / "r": only the trunk sample (x = 0.10) — the arm's two are no occluders.
     A face with one vertex at armw 0.3 counts as arm (``ARM_MAX`` 0.3, max over its vertices >= 0.3); armw 0.29 -> trunk.
[O2] the depth window as the shell reads it: a flank point at x = 0.10 seen from the +x camera (toward 1) is "seen"
     when 0.10 >= zbuf - 0.015. With the arm in the buffer zbuf = 0.20 -> 0.10 >= 0.185 False (the old behaviour);
     with the trunk only zbuf = 0.10 -> 0.10 >= 0.085 True.
[O3] ``construction_due``: inputs {shell_version 2, no sides} -> False; {shell_version 1} -> True;
     {2, fit_settings shell_sides True, no shell_sides_version} -> True (Glut's live shell: due -> Re-fit);
     {2, sides True, shell_sides_version 1} -> False; {2, sides False, shell_sides_version absent} -> False.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tempfile  # noqa: E402

from app.core import paths  # noqa: E402

paths.init(tempfile.mkdtemp(prefix="smoke_a191_shell_"))
import numpy as np  # noqa: E402

from app.core import garment_shell as gsh  # noqa: E402

failed = []


def check(name, got, want):
    ok = got == want
    print(("ok   " if ok else "FAIL ") + f"{name}: got {got!r} want {want!r}")
    if not ok:
        failed.append(name)


# [O1]
faces = np.array([[0, 1, 2], [3, 4, 5]])
armw = np.array([1.0, 1.0, 1.0, 0.0, 0.0, 0.0])
X = np.array([[0.20, 1.0, 0.0], [0.20, 1.1, 0.0], [0.10, 1.0, 0.0]])
tri = np.array([0, 0, 1])
for v in ("f", "b"):
    check(f"O1 {v} keeps all", len(gsh.occluding_samples(v, X, tri, faces, armw)), 3)
for v in ("l", "r"):
    got = gsh.occluding_samples(v, X, tri, faces, armw)
    check(f"O1 {v} trunk only", [round(float(x), 2) for x in got[:, 0]], [0.10])
check("O1 ARM_MAX", gsh.ARM_MAX, 0.3)
w2 = np.array([0.3, 0.0, 0.0, 0.29, 0.0, 0.0])
check("O1 0.3 is arm, 0.29 trunk", len(gsh.occluding_samples("l", X, tri, faces, w2)), 1)

# [O2]
flank = 0.10
old_z = float(X[:, 0].max())
new_z = float(gsh.occluding_samples("l", X, tri, faces, armw)[:, 0].max())
check("O2 old zbuf hides the flank", flank >= old_z - 0.015, False)
check("O2 new zbuf sees the flank", flank >= new_z - 0.015, True)

# [O3]
V = gsh.SHELL_VERSION
check("O3 plain", gsh.construction_due({"shell_version": V}), False)
check("O3 old version", gsh.construction_due({"shell_version": V - 1}), True)
check("O3 sides, no sides version", gsh.construction_due({"shell_version": V, "fit_settings": {"shell_sides": True}}), True)
check("O3 sides, current", gsh.construction_due({"shell_version": V, "fit_settings": {"shell_sides": True},
                                                 "shell_sides_version": gsh.SIDES_VERSION}), False)
check("O3 sides off", gsh.construction_due({"shell_version": V, "fit_settings": {"shell_sides": False}}), False)
check("O3 SIDES_VERSION", gsh.SIDES_VERSION, 1)

print("FAILED: " + ", ".join(failed) if failed else "all passed")
sys.exit(1 if failed else 0)
