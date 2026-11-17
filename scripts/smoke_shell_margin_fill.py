"""A184 — the shell's "Take from the body" (``shell_margin``) and "Fill holes up to" (``shell_fill``) settings.

Usage: ./.venv/bin/python scripts/smoke_shell_margin_fill.py   (no server, no world DB)

Expected values derived by hand:
[M1] ``_bridge_mm``: the bridge margin is metres; a real margin m grows by the setting and clamps to [-5, 5+M] mm.
     M = 6: 0.002 m -> 2 + 6 = 8 mm; -0.004 m -> -4 + 6 = 2 mm; the "no bridge" value -0.01 m stays -10 -> clamp -5;
     0.02 m -> 20 + 6 = 26 -> clamp 11.  M = 0: 0.002 -> 2; -0.01 -> -5 (the pre-A184 numbers).
[M2] ``_fill_glints``: a 100x100 mask with a 4x4 (16 px) and a 10x10 (100 px) hole; mask area 10000-116 = 9884,
     0.1 % = 9.884 px -> with max_px 0 neither hole is filled (16 > 9.884); max_px 20 fills the 16-px hole only;
     max_px 101 fills both.  At 1.2 mm/px a pixel is 0.0144 cm², so "Fill holes up to 2 cm²" = 2*100/1.44 = 138.9
     px -> fills a 100-px hole (1.44 cm²).
[M3] choices: shell_margin 0/3/6/10/15 default 3, shell_fill 0/2/5/10/20/50 default 2; a value off the list or a
     bool reads the default; validate refuses 4 and True with ValueError.
[M5] the region excludes arms and hands only: the default ``arm_tokens`` of ``build_shell`` are ("Arm", "Hand") —
     a "Shoulder" token dropped every strap over the trapezius (Glut's bra, A184).
[M4] due: a shell fit made with margin 3 is due when the setting is 6; a generated-mesh fit is not
     (``garment_fit_settings.changed`` drops the shell keys for a non-shell piece).
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
from app.core import garment_shell as gs, garment_fit_settings as fs

fails = 0


def check(name, got, want):
    global fails
    ok = got == want
    fails += not ok
    print(f"{'ok  ' if ok else 'FAIL'} {name}: got {got!r} want {want!r}")


got = [round(float(x), 6) for x in gs._bridge_mm(np.array([0.002, -0.004, -0.01, 0.02]), 6.0)]
check("[M1] margin 6", got, [8.0, 2.0, -5.0, 11.0])
check("[M1] margin 0", [round(float(x), 6) for x in gs._bridge_mm(np.array([0.002, -0.01]), 0.0)], [2.0, -5.0])

m = np.ones((100, 100), bool)
m[10:14, 10:14] = False
m[50:60, 50:60] = False
check("[M2] max_px 0 fills none", int((~gs._fill_glints(m, 0)).sum()), 116)
check("[M2] max_px 20 fills the 16-px hole", int((~gs._fill_glints(m, 20)).sum()), 100)
check("[M2] max_px 101 fills both", int((~gs._fill_glints(m, 101)).sum()), 0)
check("[M2] 2 cm² at 1.2 mm/px fills a 100-px hole", int((~gs._fill_glints(m, 2 * 100.0 / 1.2 ** 2)).sum()), 0)

check("[M3] margin choices", (gs.MARGIN_CHOICES, gs.MARGIN_DEFAULT), ((0, 3, 6, 10, 15), 3))
check("[M3] fill choices", (gs.FILL_CHOICES, gs.FILL_DEFAULT), ((0, 2, 5, 10, 20, 50), 2))
check("[M3] off-list reads default", (gs.shell_margin_choice({"shell_margin": 4}),
                                     gs.shell_fill_choice({"shell_fill": True})), (3, 2))
check("[M3] normalise", {k: fs.normalise({"shell_margin": 10, "shell_fill": 20})[k]
                         for k in ("shell_margin", "shell_fill")}, {"shell_margin": 10, "shell_fill": 20})
for bad in ({"shell_margin": 4}, {"shell_fill": True}):
    try:
        fs.validate(bad)
        check(f"[M3] validate {bad}", "accepted", "ValueError")
    except ValueError:
        check(f"[M3] validate {bad}", "ValueError", "ValueError")
check("[M3] validate ok", fs.validate({"shell_margin": 6, "shell_fill": 0}), {"shell_margin": 6, "shell_fill": 0})

record = {"inputs": {"fit_settings": {"shell_margin": 3}, "mesh_shape": "shell"}}
profile = {fs.SETTINGS_KEY: {"x": {"shell_margin": 6}}}
fs.current_shape = lambda settings, item_id: shape  # noqa: E731 — the item's mode, without a world DB
shape = gs.SHELL
check("[M4] shell piece due", fs.changed(record, profile, "x"), True)
shape = gs.AS_GENERATED
record_gen = {"inputs": {"fit_settings": {"shell_margin": 3}}}
check("[M4] generated piece not due", fs.changed(record_gen, profile, "x"), False)
import inspect
check("[M5] arm tokens", inspect.signature(gs.build_shell).parameters["arm_tokens"].default, ("Arm", "Hand"))
print("all pass" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
