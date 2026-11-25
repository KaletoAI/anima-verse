"""Smoke: the cut follows the drape's A200 fallback (stage "layers", 2026-11-22).

Usage:
    ./.venv/bin/python scripts/smoke_cut_own_fallback.py

Live finding (stage 2, Kai's leather jacket over his generated jeans): the drape with the jeans as an own-mesh collider
fails its stretch gate in "full" (1.521) and "shrunk" (4.457) and lands "dropped" — laid out without the jeans — while
the cut-only run laid the panels out WITH them: islands 13.98 against 14.00 px/cm, the cut atlas belonged to other
islands and was never applied ("drape_other"). Laying every attempt out of the full colliders (and moving only the
cloth run's) was measured on a copy and rejected: the islands matched, but "dropped" then failed too (stretch 1.465)
and the jacket had no drape at all. So the CUT follows the mode the drape landed in. No server, no world DB opened,
no Blender, no hub job: a throwaway ``paths.init``, the pieces / records / Blender run stubbed. Derived by hand:

[1] ``garment_template_cut.sig_of`` with ``own_mode``: the tokens of ``cut_sig`` are the under tokens + one
    ``collider:<item>`` per ready template layer, and "shrunk" / "dropped" add ``own:<mode>`` when an own-mesh fit is
    among the under tokens (a ``:fit:`` token): with under ["jeans:fit:f1"] and no template layer the sig is
    ``cut_sig(params, base_sha, ["jeans:fit:f1", "own:dropped"])``; "full" gives ``cut_sig(.., ["jeans:fit:f1"])`` (the
    sig every existing cut has — nothing re-cuts); a piece without a fit token gets no own token even with "dropped".
[2] ``garment_template.own_fallback_mode``: the accepted drape of the current key records ``inner_collider.mode``
    "dropped" -> "dropped"; "shrunk" -> "shrunk"; "full" or no ``inner_collider`` -> "full"; no drape of the current key
    but a stand-in with "dropped" (``cut_stand_in``) -> "dropped"; under tokens without a fit -> "full" (no file read).
[3] ``garment_template_cut.run`` with ``cut_key`` giving ``own_mode``: "dropped" hands the Blender run NO own-mesh
    collider; "shrunk" hands it with ``own_offset`` = ``INNER_SHRINK_M`` (-0.008); "full" with 0.0 — the arguments of
    ``drape_with_fallback``'s attempt of that mode. The record notes ``own_mode``.
[4] ``run_blender``'s build args: template drape D + own O at -0.008 -> ``lower_offsets`` [0.0, -0.008] and
    ``lower_shapes`` in the same order; no own -> ``lower_offsets`` [] (``build_args`` stores ``list(None or [])``), as
    the drape's "dropped" attempt (offsets None).
[5] Source: ``_build_drape`` records ``sig_of(..., own_mode=inner["mode"])`` in every mode (on 4ee6ac1ab only
    ``inner["mode"] == "full"`` recorded a cut_sig); ``figure_build._prestart_cut_texture`` does not start the flow
    beside the drape of a piece with an own-mesh fit under it (a ``:fit:`` token of ``cut_key``'s ``under``; the
    mode is known only after the drape), before ``build_start``; ``cut_key`` passes ``own_fallback_mode`` to ``sig_of`` and returns it as ``own_mode``.
"""
import inspect
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_tmp = tempfile.mkdtemp(prefix="smoke_cut_own_fallback_")
os.environ.setdefault("STORAGE_DIR", os.path.join(_tmp, "world"))
os.environ.setdefault("INSTANCE_DIR", os.path.join(_tmp, "instance"))

from app.core import paths  # noqa: E402

_world = Path(_tmp) / "world"
_inst = Path(_tmp) / "instance"
paths.init(_world)
paths.init_instance(_inst)
(_world / "config.json").write_text("{}", encoding="utf-8")
(_inst / "config.json").write_text("{}", encoding="utf-8")
from app.core import config as _cfg  # noqa: E402

_cfg.load(_world / "config.json", _inst / "config.json")

from app.core import garment_template as gt  # noqa: E402
from app.core import garment_template_cut as gtc  # noqa: E402
from app.core.garment_store import write_record  # noqa: E402

FAILS = []


def check(label, ok, detail=""):
    print(("OK   " if ok else "FAIL ") + label + (f"  ({detail})" if detail != "" else ""))
    if not ok:
        FAILS.append(label)


CHAR, ITEM = "demo", "jacket1"
JACKET = gt.validate_params({"kind": "jacket", "front": "open", "sleeves": "long"})[0]
UNDER = ["jeans:fit:f1"]

# [1]
with patch.object(gt, "collider_states", lambda *a, **k: []), \
        patch.object(gt, "under_tokens", lambda *a, **k: list(UNDER)):
    s_drop = gtc.sig_of(CHAR, ITEM, JACKET, base_sha="b0", lower=["jeans"], item={}, own_mode="dropped")[0]
    s_shr = gtc.sig_of(CHAR, ITEM, JACKET, base_sha="b0", lower=["jeans"], item={}, own_mode="shrunk")[0]
    s_full = gtc.sig_of(CHAR, ITEM, JACKET, base_sha="b0", lower=["jeans"], item={}, own_mode="full")[0]
check("[1] dropped adds own:dropped", s_drop == gtc.cut_sig(JACKET, base_sha="b0", lower=UNDER + ["own:dropped"]))
check("[1] shrunk adds own:shrunk", s_shr == gtc.cut_sig(JACKET, base_sha="b0", lower=UNDER + ["own:shrunk"]))
check("[1] full is the sig a cut has without the stage", s_full == gtc.cut_sig(JACKET, base_sha="b0", lower=UNDER))
check("[1] three different cuts", len({s_drop, s_shr, s_full}) == 3)
with patch.object(gt, "collider_states", lambda *a, **k: []), \
        patch.object(gt, "under_tokens", lambda *a, **k: ["top1:tz"]):
    s_nofit = gtc.sig_of(CHAR, ITEM, JACKET, base_sha="b0", lower=["top1"], item={}, own_mode="dropped")[0]
check("[1] no own-mesh fit: no own token", s_nofit == gtc.cut_sig(JACKET, base_sha="b0", lower=["top1:tz"]))

# [2]
folder = gt.templates_dir(CHAR)
folder.mkdir(parents=True, exist_ok=True)
glb = gt.drape_path(CHAR, ITEM, "tz")


def put(**extra):
    glb.write_bytes(b"glb")
    write_record(glb.with_suffix(".json"), {"item_id": ITEM, "tsig": "tz", "accepted": True, **extra})


key_fit = lambda *a, **k: ("tz", None, {}, JACKET, list(UNDER))  # noqa: E731
with patch.object(gt, "_key", key_fit), patch.object(gt, "cut_stand_in", lambda *a, **k: None):
    for mode, want in (("dropped", "dropped"), ("shrunk", "shrunk"), ("full", "full")):
        put(inner_collider={"mode": mode, "failed": []})
        got = gt.own_fallback_mode(CHAR, ITEM, base_sha="b0", lower=["jeans"], item={})
        check(f"[2] drape mode {mode} -> {want}", got == want, got)
    put()
    check("[2] no inner_collider -> full", gt.own_fallback_mode(CHAR, ITEM, base_sha="b0", lower=["jeans"],
                                                                item={}) == "full")
glb.unlink()
glb.with_suffix(".json").unlink()
with patch.object(gt, "_key", key_fit), \
        patch.object(gt, "cut_stand_in", lambda *a, **k: {"tsig": "tq", "path": Path("x"),
                                                          "record": {"inner_collider": {"mode": "dropped"}}}):
    got = gt.own_fallback_mode(CHAR, ITEM, base_sha="b0", lower=["jeans"], item={})
    check("[2] the stand-in's mode", got == "dropped", got)
with patch.object(gt, "_key", lambda *a, **k: ("tz", None, {}, JACKET, ["top1:tz"])), \
        patch.object(gt, "cut_stand_in", lambda *a, **k: 1 / 0):
    check("[2] no fit under it -> full, nothing read",
          gt.own_fallback_mode(CHAR, ITEM, base_sha="b0", lower=["top1"], item={}) == "full")

# [3]
CALLS = []


def fake_run_blender(body_glb, params, *, item_id, out_dir, colliders=None, own=None, over_sleeves=False,
                     own_offset=0.0, **_k):
    CALLS.append({"own": [str(p) for p, _ in own or []], "own_offset": own_offset})
    return {"ok": False, "outcome": "rejected", "error": "stub", "data": {}, "islands": None, "marks": None,
            "log_tail": "", "wall_s": 0.1, "slot_wait_s": 0.0, "measure_s": 0.0}


for mode, want_own, want_off in (("dropped", [], 0.0), ("shrunk", ["O.glb"], -0.008), ("full", ["O.glb"], 0.0)):
    key = {"sig": f"s_{mode}", "reason": "", "params": JACKET, "base": ("base0", "b0"), "base_sha": "b0",
           "lower": ["jeans"], "under": list(UNDER), "item": {}, "own_mode": mode}
    with patch.object(gtc, "cut_key", lambda *a, k=key, **kw: k), \
            patch.object(gt, "collider_states", lambda *a, **k: []), \
            patch.object(gt, "own_colliders", lambda *a, **k: [("jeans", Path("O.glb"))]), \
            patch("app.core.bust_shaping.prepare", lambda body, *a, **k: (body, None, None)), \
            patch.object(gtc, "run_blender", fake_run_blender):
        gtc.run(CHAR, ITEM)
    rec = gtc.read_record(CHAR, ITEM, f"s_{mode}")
    check(f"[3] {mode}: own {want_own} at {want_off}", CALLS[-1] == {"own": want_own, "own_offset": want_off}
          and rec.get("own_mode") == mode, (CALLS[-1], rec.get("own_mode")))

# [4]
ARGS = []
import app.blender.runner as runner  # noqa: E402


def fake_runner(script, *, inputs, params, out_dir, timeout_s):
    ARGS.append((sorted(inputs), params.get("lower_offsets")))
    return {"ok": False, "outputs": {}, "outcome": "rejected", "error": "stub"}


with patch.object(gt, "measure_body", lambda raw: {}), patch.object(gt, "panel_spec", lambda *a, **k: {}), \
        patch.object(gt, "build_args", lambda params, spec, **k: {"lower_offsets": list(k.get("lower_offsets") or []),
                                                                  "lower_shapes": k.get("lower_shapes")}), \
        patch.object(runner, "run", fake_runner):
    body = Path(_tmp) / "b.glb"
    body.write_bytes(b"x")
    gtc.run_blender(body, JACKET, item_id=ITEM, out_dir=Path(_tmp) / "o1", colliders=[(Path("D.glb"), {})],
                    own=[(Path("O.glb"), None)], own_offset=gt.INNER_SHRINK_M)
    gtc.run_blender(body, JACKET, item_id=ITEM, out_dir=Path(_tmp) / "o2", colliders=[(Path("D.glb"), {})], own=[])
check("[4] D + O shrunk -> offsets [0.0, -0.008], inputs lower_0 / lower_1",
      ARGS[0] == (["body", "lower_0", "lower_1"], [0.0, -0.008]), ARGS[0])
check("[4] no own -> offsets [] (the dropped attempt's None)", ARGS[1] == (["body", "lower_0"], []), ARGS[1])

# [5]
src = inspect.getsource(gt._build_drape)
check("[5] _build_drape records sig_of(..., own_mode=inner['mode']) in every mode",
      'own_mode=inner["mode"]' in src and 'inner["mode"] == "full"' not in src)
from app.core import figure_build  # noqa: E402

pre = inspect.getsource(figure_build._prestart_cut_texture)
check("[5] no prestart over an own-mesh fit (a ':fit:' under token)", '":fit:" in t' in pre
      and pre.index('":fit:" in t') < pre.index("build_start("))
ck = inspect.getsource(gtc._cut_key)   # the body behind the read-scope wrapper (read_scope, Task 5)
check("[5] cut_key passes own_fallback_mode and returns own_mode", "own_fallback_mode(" in ck
      and "own_mode=own_mode" in ck)

print("ALL OK" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}")
sys.exit(1 if FAILS else 0)
