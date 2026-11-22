"""Smoke: cut-first — the pattern pieces of a template top without its drape (``app/core/garment_template_cut.py``).

Usage:
    ./.venv/bin/python scripts/smoke_template_cut_first.py

No server, no world DB opened, no Blender, no hub job: a throwaway ``paths.init``, the item / picture / Blender run
stubbed. The real Blender proof (cut-only islands == drape islands, bytes) is ``scripts/smoke_template_cut_islands_
equal.py``. Every expectation is derived by hand below.

[1] The cut signature's content — what ``garment_template_build.run`` reads before the ``cut_only`` return:
    [1.1] the builder: every ``prm[...]`` / ``prm.get(...)`` key read in ``run`` before the top's ``if cut_only:`` (the
          last one in ``run``; the fitted kinds' branch returns at the first, step 3a) is one of
          progress_file, spec, lower_offsets, lower_shapes, torso_half_m, thickness, uv_mode, node, slit, cut_only —
          none of fabric, drape_quality, frames, poses, shape_groups, smooth_weights, render (read after it); and
          ``inp["front"]`` / ``inp["back"]`` (the views) only after it.
    [1.2] the parameters: ``build_args`` of a top with fabric "medium" and with "stiff" (same spec) differ in exactly
          the keys {"fabric", "drape_quality"} (medium bending 0.3 vs stiff 2.0, both quality 6 -> drape_quality
          round(6 * 1.5) = 9 for both — the key still differs because ``fabric`` does); ``panel_spec`` of both on a
          real body's measurements (Dario's, a literal below) is the same dict. So ``DRAPE_ONLY`` = ("fabric",).
    [1.3] ``cut_sig`` = md5[:12] of json({"params": keyed_params minus fabric, "version": TEMPLATE_VERSION (10),
          "uv_pattern": a top's ``TOP_UV_PATTERN_SHA``, "base": base sha, "lower": sorted tokens}, sort_keys, compact) —
          recomputed here from the formula; ``TOP_UV_PATTERN_SHA`` = md5[:12] of ``uv_pattern.py`` at c926b67f0 (``git
          show``; the base the tops were last cut with, so a top's recorded ``cut_sig`` from before step 3a stays the
          current one — no re-drape of every top, decision D7 b); a fitted piece (briefs) keys md5 of the CURRENT
          ``uv_pattern.py`` (``UV_PATTERN_SHA``); unchanged by fabric / opacity / texture / sleeve_print / fly and by the
          ORDER of the lower tokens; changed by length_m, sleeves, neckline, fit, neck_depth_m, the base sha and a lower
          token (``slit`` is no top field: ``validate_params`` resets it, so it never reaches a top's key).
          ``tsig`` of the same inputs DOES change with fabric (the drape is keyed by it, the cut is not).
[2] ``state`` / ``run`` / ``schedule`` in a temp storage, ``cut_key`` stubbed to sig "c1" (a ready key) and the Blender
    run stubbed (writes a 2-island payload: front 20 x 30 cm, back 20 x 30 cm, 10 px/cm, atlas 512):
    [2.1] nothing on disk -> "missing" with ``NOT_CUT``; a blocked key (sig None, reason NO_PATTERN) -> "blocked".
    [2.2] ``schedule`` -> "cutting" at once (the stub run waits on an event); ``state`` -> "cutting" with ``CUTTING``;
          a second ``schedule`` starts nothing (1 run); NO ``piece_jobs`` claim while it runs (holder ""), and a held
          "cut" claim of the piece does not stop a schedule of another key.
    [2.3] after the run: "ready", ``islands_path`` = templates/cut/<item>_c1.islands.json, ``islands_sha`` = sha256
          of its bytes = the stub's bytes, ``cut_at`` the record's stamp, ``wall_s`` 0.5; the pattern sheet
          ``<item>_c1.pattern.png`` exists (2-island sheet, 512 px wide); a further ``schedule`` starts nothing.
    [2.4] a run that judged its input ("rejected") -> "failed" with CUT_FAILED; ``schedule`` does not run it again.
          A run that judged nothing ("timeout") -> "missing" with CUT_LEFT; ``schedule`` within RETRY_AFTER_S (300 s)
          starts nothing.
    [2.5] ``run`` itself (Blender stubbed, no colliders, the plain body): it hands the builder the plain body with no
          colliders and writes the islands bytes, the sheet and the record (cut sig, wall 11.8 s, islands sha256,
          base sha, ``UV_PATTERN_SHA``); a ready cut is kept (no Blender); "rejected" -> a failed record; "timeout" ->
          no record, "missing" with CUT_LEFT.
[3] ``garment_cut_texture.dialog_state`` WITHOUT a drape (drape "missing", not worn) and the ready cut of [2.3]:
    ``pattern_reason`` "", ``cutting`` False, ``cut_at`` = the record's stamp, ``blocked_reason`` "" (picture, media,
    chain all in place), ``can_generate`` True, ``plan.total`` 2 (front + back, a back view exists, the item 1200 px)
    and ``islands_sha`` = the cut's; ``pattern_sheet_file`` = the cut's sheet. While cutting (another item):
    ``pattern_reason`` CUTTING, ``cutting`` True, ``plan`` None, ``can_generate`` False.
[4] The atlas across drapes (``garment_template.cut_info`` / ``atlas_for``): a ready cut record + atlas for csig(A)
    (A = the [2.3] islands sha, made 2026-11-21T10:00): drape 1 (islands A, tsig t1, 09:00) -> texture "cut", the
    atlas bytes; a RE-DRAPE of the same cut (islands A, tsig t2 — new views, 11:00) -> "cut", the same csig and bytes;
    a drape of ANOTHER cut (islands B) made 09:00, before the atlas, whose record carries cut_sig "old0" while the
    piece's cut is "c1" (a Build re-drapes it, ``cut_behind``) -> "projection", cut_state "drape_behind" with
    CUT_DRAPE_BEHIND_TEXT, ``atlas_for`` None, ``texture_warning`` carries it; the same drape WITHOUT a cut_sig (a
    fallback drape, or one from before cut-first) and one whose cut_sig IS the current "c1" -> "drape_other" with
    CUT_DRAPE_OTHER_TEXT (no Build re-drapes them, so the row must not promise one); the same drape B made 11:00
    (after the atlas: the cut changed since) -> "stale" (the atlas is out of date), never the atlas.
[5] Review findings 2026-11-21 — what the cut is keyed by (``sig_of`` / ``cut_key``), collider states stubbed
    (``collider_states``: one lower template layer "bra1" with drape key "tb"; no own-mesh fit; no chest shaping):
    [5.1] a strapless top (kind top, shoulders strapless: ``has_bodice`` False) -> ``cut_key`` sig None with
          NO_PATTERN_STRAPLESS before any profile / body is read; ``state`` "blocked"; ``schedule`` runs nothing;
          ``sig_of`` the same reason. A skirt keeps NO_PATTERN.
    [5.2] the bra "missing" (the next Build drapes it first) -> ``sig_of`` (None, WAITING_LOWER); with
          ``wait=False`` (the drape's record) the sig of tokens ["bra1:tb"] = cut_sig(TOP, "b0", ["bra1:tb"]).
    [5.3] the bra "ready" -> tokens ["bra1:tb", "collider:bra1"] (under_tokens gives "bra1:tb"; the top is no fitted
          kind and has no jacket allowance, so nothing more); the bra "failed" -> ["bra1:tb"] (a failed layer is no
          collider of the drape either, so the cut goes on without it) — so ready != failed, and failed == the
          wait=False sig of [5.2].
    [5.4] ``cut_key`` of a worn top over the missing bra (base "b0", worn set stubbed) -> sig None, WAITING_LOWER;
          ``state`` "blocked" with it; ``schedule`` starts nothing.
[6] A drape of another cut is stale (``garment_template.cut_behind`` in ``drape_state``; ``_key`` stubbed to tsig
    "tz", a ready accepted drape GLB + record of "tz" on disk):
    [6.1] record cut_sig "cA", current sig "cA" -> "ready"; current "cB" -> "missing" with CUT_REDRAPE, ``tsig`` still
          "tz" (the Build drapes again under the same key — no tsig change, no other drape moves).
    [6.2] a record without cut_sig (before cut-first / a fallback drape) -> "ready" for any current sig.
    [6.3] the current cut has no sig (a lower layer still to be draped) -> "ready" (the Build drapes that layer first).
    [6.4] finding 2 in full: a top's flattening key ``TOP_UV_PATTERN_SHA`` changed (patched to "ffffffffffff"),
          everything else equal -> the sig from ``sig_of`` differs from the recorded one -> ``cut_behind`` True; with
          the real key -> False. ``UV_PATTERN_SHA`` patched (a change of ``uv_pattern.py`` that leaves the tops'
          islands alone — step 3a's) -> a top is NOT behind, a briefs piece's ``cut_sig`` does change.
    [6.5] the bra becomes ready after the top was draped without it (record = wait=False sig of [5.2]) ->
          ``cut_behind`` True (the top is laid out of the bra next Build).
    [6.6] ``_build_drape`` records ``sig_of(..., wait=False)`` (source check: the drape stores what it WAS laid out of).
    [6.7] Live E2E 2026-11-21 (Kai): the chest shaping's token comes from the ITEM (``bust_shaping.key_tokens`` —
          stubbed here to give "shape:x" only when it is handed an item). ``sig_of`` with ``item`` None reads the item
          (``inventory.get_item`` stubbed) -> the same sig as with the item handed = cut_sig(TOP, "b0", ["bra1:tb",
          "shape:x", "collider:bra1"]), and a drape recorded with it is NOT behind for ``cut_behind(..., item=None)``
          (the Build's plan) — before, every Build re-drapes the shirt as "cut anew".
"""
import hashlib
import subprocess
import json
import os
import re
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
_tmp = tempfile.mkdtemp(prefix="smoke_cut_first_")
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

from PIL import Image  # noqa: E402

from app.core import garment_cut_texture as gct  # noqa: E402
from app.core import garment_template as gt  # noqa: E402
from app.core import garment_template_cut as gtc  # noqa: E402
from app.core import piece_jobs  # noqa: E402
from app.models.character import get_character_dir  # noqa: E402

FAILS = []


def check(label, ok, detail=""):
    print(("OK   " if ok else "FAIL ") + label + (f"  ({detail})" if not ok and detail != "" else ""))
    if not ok:
        FAILS.append(label)


# ---------------------------------------------------------------------------------------------------- [1]
BUILD = (ROOT / "app" / "blender" / "scripts" / "garment_template_build.py").read_text(encoding="utf-8")
run_src = BUILD[BUILD.index("def run(a):"):]
cut_at = run_src.rindex("if cut_only:")
before = run_src[:cut_at]
read = set(re.findall(r'prm\["(\w+)"\]', before)) | set(re.findall(r'prm\.get\("(\w+)"', before))
allowed = {"progress_file", "spec", "lower_offsets", "lower_shapes", "torso_half_m", "thickness", "uv_mode", "node",
           "slit", "cut_only"}
check("[1.1] the cut reads only the cut's build args", read <= allowed and "spec" in read and "slit" in read,
      sorted(read))
drape_only_args = {"fabric", "drape_quality", "frames", "poses", "shape_groups", "smooth_weights", "render"}
check("[1.1] no drape arg is read before the cut ends", not (read & drape_only_args), sorted(read & drape_only_args))
check("[1.1] the views are read only after the cut", 'inp["front"]' not in before and 'inp["back"]' not in before
      and 'inp["front"]' in run_src[cut_at:])

DARIO_MEAS = {"arm_c": [[0.05, 0.4891], [0.15, 0.4499], [0.25, 0.4275], [0.35, 0.3874], [0.5, 0.3448],
                        [0.65, 0.3457], [0.8, 0.2763], [0.97, 0.2291]], "arm_len": 0.5607, "band_c": 1.22,
              "band_y": 1.425, "floor_y": -0.0, "height": 1.9, "hip_c": 1.0603, "hip_y": 0.955,
              "joints": {"leftarm": [0.2081, 1.508, 0.0138], "leftforearm": [0.4789, 1.5019, 0.0144],
                         "lefthand": [0.7741, 1.5103, 0.0246], "neck": [-0.0081, 1.5787, 0.0557],
                         "rightarm": [-0.2161, 1.5154, 0.0044], "rightforearm": [-0.4825, 1.5129, 0.004],
                         "righthand": [-0.7713, 1.5261, 0.0075], "spine2": [-0.0064, 1.3825, 0.0406]},
              "neck_c": 0.7568, "neck_y": 1.5787, "shoulder_w": 0.5042, "shoulder_y": 1.5117,
              "torso": [[0.76, 0.9983], [0.8, 1.0103], [0.9, 1.0175], [1.0, 1.0537], [1.1, 0.9926], [1.2, 0.8599],
                        [1.3, 1.0054], [1.4, 1.215], [1.42, 1.2216], [1.5, 1.1678]],
              "upper_arm_c": 0.4275, "waist_c": 0.8584, "waist_y": 1.195, "wrist_c": 0.2291}
TOP = gt.validate_params({"kind": "top", "length_m": 0.53, "sleeves": "long", "neckline": "v",
                          "neck_depth_m": 0.07, "shoulders": "covered", "fit": 0.6, "sleeve_fit": 0.5,
                          "fabric": "medium"})[0]
STIFF = {**TOP, "fabric": "stiff"}
spec_m = gt.panel_spec(TOP, DARIO_MEAS)
spec_s = gt.panel_spec(STIFF, DARIO_MEAS)
check("[1.2] panel_spec does not read the fabric", json.dumps(spec_m, sort_keys=True, default=str)
      == json.dumps(spec_s, sort_keys=True, default=str))
ba_m = gt.build_args(TOP, spec_m, item_id="it")
ba_s = gt.build_args(STIFF, spec_s, item_id="it")
diff = {k for k in set(ba_m) | set(ba_s) if json.dumps(ba_m.get(k), sort_keys=True, default=str)
        != json.dumps(ba_s.get(k), sort_keys=True, default=str)}
check("[1.2] fabric changes only the cloth args (fabric, drape_quality)", diff <= {"fabric", "drape_quality"}
      and "fabric" in diff, sorted(diff))
check("[1.2] DRAPE_ONLY is ('fabric',)", gtc.DRAPE_ONLY == ("fabric",), gtc.DRAPE_ONLY)
check("[1.2] uv_mode pattern for a top; PATTERN_KINDS = top + the fitted kinds (step 3a)",
      ba_m["uv_mode"] == "pattern" and gt.PATTERN_KINDS == ("top",) + gt.FITTED_KINDS, gt.PATTERN_KINDS)

uvp_sha = hashlib.md5((ROOT / "app" / "blender" / "scripts" / "uv_pattern.py").read_bytes()).hexdigest()[:12]
try:
    top_sha = hashlib.md5(subprocess.run(["git", "-C", str(ROOT), "show", "c926b67f0:app/blender/scripts/uv_pattern.py"],
                                         capture_output=True, check=True).stdout).hexdigest()[:12]
except (OSError, subprocess.CalledProcessError) as e:
    print(f"NOTE [1.3] git show c926b67f0 failed ({e}): the top's key is taken from the constant")
    top_sha = gtc.TOP_UV_PATTERN_SHA
cp = {k: v for k, v in gt.keyed_params(TOP).items() if k != "fabric"}
want = hashlib.md5(json.dumps({"params": cp, "version": 10, "uv_pattern": top_sha, "base": "b0", "lower": ["a:1", "b:2"]},
                              sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:12]
k0 = gtc.cut_sig(TOP, base_sha="b0", lower=["b:2", "a:1"])
check("[1.3] cut_sig = the formula (lower sorted)", k0 == want and gt.TEMPLATE_VERSION == 10
      and gtc.UV_PATTERN_SHA == uvp_sha and gtc.TOP_UV_PATTERN_SHA == top_sha, (k0, want, top_sha))
BRF = gt.validate_params({"kind": "briefs"})[0]
cpb = {k: v for k, v in gt.keyed_params(BRF).items() if k != "fabric"}
wantb = hashlib.md5(json.dumps({"params": cpb, "version": 10, "uv_pattern": uvp_sha, "base": "b0", "lower": [],
                                "fitted": gt.FITTED_VERSION, "fitted_pattern": gtc.FITTED_PATTERN_SHA},
                               sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:12]
check("[1.3] a fitted piece keys the current uv_pattern.py", gtc.cut_sig(BRF, base_sha="b0", lower=[]) == wantb)
same = {"fabric": "stiff", "opacity": 0.9, "texture": "cut", "sleeve_print": "picture", "fly": "buttons"}
for field, value in same.items():
    k = gtc.cut_sig({**TOP, field: value}, base_sha="b0", lower=["a:1", "b:2"])
    check(f"[1.3] {field} does not change the cut", k == k0, (field, k, k0))
moved = {"length_m": 0.6, "sleeves": "short", "neckline": "crew", "fit": 0.3, "neck_depth_m": 0.1}
for field, value in moved.items():
    k = gtc.cut_sig(gt.validate_params({**TOP, field: value})[0], base_sha="b0", lower=["a:1", "b:2"])
    check(f"[1.3] {field} changes the cut", k != k0, field)
check("[1.3] the base sha changes the cut", gtc.cut_sig(TOP, base_sha="b1", lower=["a:1", "b:2"]) != k0)
check("[1.3] a lower token changes the cut", gtc.cut_sig(TOP, base_sha="b0", lower=["a:1", "b:3"]) != k0)
check("[1.3] the drape key (tsig) DOES change with the fabric",
      gt.tsig(TOP, base_sha="b0", texture_sha="t", lower=[]) != gt.tsig(STIFF, base_sha="b0", texture_sha="t", lower=[]))

# ---------------------------------------------------------------------------------------------------- [2]
CHAR = "demo"
get_character_dir(CHAR, create=True)
ITEM = "shirtc"
SIG = {"value": "c1"}


def key_stub(character_name, item_id, **_k):
    if item_id == "blocked1":
        return {"sig": None, "reason": gtc.NO_PATTERN}
    return {"sig": f"{SIG['value']}" if item_id == ITEM else f"k{item_id[-1]}", "reason": ""}


def payload(w_cm=20, h_cm=30, ppc=10.0, size=512):
    def box(name, x0, y0):
        w, h = w_cm * ppc, h_cm * ppc
        v = [[x0, y0], [x0 + w, y0], [x0 + w, y0 + h], [x0, y0 + h]]
        return {"name": name, "part": 1 if name == "front" else 2, "verts_px": v, "tris": [[0, 1, 2], [0, 2, 3]],
                "bbox_px": [x0, y0, x0 + w, y0 + h], "loops_px": [v], "area_cm2": w_cm * h_cm, "distortion": {}}
    return {"version": 1, "atlas_px": size, "px_per_cm": ppc, "margin_cm": 1.5,
            "islands": [box("front", 10, 10), box("back", 250, 10)], "seams": []}


PAYLOAD_BYTES = json.dumps(payload(), sort_keys=True, separators=(",", ":")).encode()
RUNS = []
GATE = {"evt": threading.Event(), "outcome": "ok"}


def fake_cut_run(character_name, item_id):
    """Stands for ``gtc.run``'s Blender step: writes what ``run`` writes (islands, sheet, record)."""
    RUNS.append(item_id)
    GATE["evt"].wait(10)
    sig = key_stub(character_name, item_id)["sig"]
    if GATE["outcome"] == "ok":
        gtc._write_atomic(gtc.islands_file(character_name, item_id, sig), PAYLOAD_BYTES)
        gtc._write_atomic(gtc.sheet_file(character_name, item_id, sig),
                          gct._png(gct.render_pattern_sheet(json.loads(PAYLOAD_BYTES))))
        rec = {"state": "ready", "cut_sig": sig, "wall_s": 0.5, "created_at": "2026-11-21T10:00:00+00:00",
               "islands": {"file": gtc.islands_file(character_name, item_id, sig).name,
                           "sha256": hashlib.sha256(PAYLOAD_BYTES).hexdigest(), "px_per_cm": 10.0}}
        gtc._write_atomic(gtc.record_file(character_name, item_id, sig), json.dumps(rec).encode())
    elif GATE["outcome"] == "rejected":
        gtc._write_atomic(gtc.record_file(character_name, item_id, sig),
                          json.dumps({"state": "failed", "error": "boom"}).encode())
    else:
        with gtc._lock:
            gtc._left[(character_name, item_id, sig)] = (time.monotonic(), GATE["outcome"])
    return gtc.state(character_name, item_id)


def wait_idle(item_id, sig, limit=10.0):
    t0 = time.time()
    while time.time() - t0 < limit:
        with gtc._lock:
            if (CHAR, item_id, sig) not in gtc._running:
                return True
        time.sleep(0.02)
    return False


with patch.object(gtc, "cut_key", key_stub):
    s0 = gtc.state(CHAR, ITEM)
    check("[2.1] nothing on disk -> missing, NOT_CUT", s0["state"] == "missing" and s0["reason"] == gtc.NOT_CUT, s0)
    sb = gtc.state(CHAR, "blocked1")
    check("[2.1] a blocked key -> blocked with its reason", sb["state"] == "blocked" and sb["reason"] == gtc.NO_PATTERN)
    check("[2.1] a blocked key is never scheduled", gtc.schedule(CHAR, "blocked1", runner=fake_cut_run)["state"]
          == "blocked" and RUNS == [])

    GATE["evt"].clear()
    r1 = gtc.schedule(CHAR, ITEM, runner=fake_cut_run)
    check("[2.2] schedule -> cutting", r1["state"] == "cutting" and r1["reason"] == gtc.CUTTING, r1)
    time.sleep(0.1)
    sc = gtc.state(CHAR, ITEM)
    check("[2.2] state while it runs -> cutting", sc["state"] == "cutting" and sc["reason"] == gtc.CUTTING, sc)
    gtc.schedule(CHAR, ITEM, runner=fake_cut_run)
    check("[2.2] a second schedule starts nothing", RUNS == [ITEM], RUNS)
    check("[2.2] no piece_jobs claim while the cut runs (CPU, no hub job)", piece_jobs.holder(CHAR, ITEM) == "")
    check("[2.2] a held hub-job claim does not stop a cut", piece_jobs.claim(CHAR, "shirt7", "cut") == ""
          and gtc.schedule(CHAR, "shirt7", runner=fake_cut_run)["state"] == "cutting")
    GATE["evt"].set()
    check("[2.3] the runs end", wait_idle(ITEM, "c1") and wait_idle("shirt7", "k7"))
    piece_jobs.release(CHAR, "shirt7", "cut")
    s3 = gtc.state(CHAR, ITEM)
    ipath = gtc.cut_dir(CHAR) / f"{ITEM}_c1.islands.json"
    check("[2.3] ready with the cut's islands", s3["state"] == "ready" and s3["islands_path"] == ipath
          and s3["islands_sha"] == hashlib.sha256(PAYLOAD_BYTES).hexdigest() == hashlib.sha256(ipath.read_bytes())
          .hexdigest() and s3["cut_at"] == "2026-11-21T10:00:00+00:00" and s3["wall_s"] == 0.5, s3)
    sheet = gtc.cut_dir(CHAR) / f"{ITEM}_c1.pattern.png"
    with Image.open(sheet) as sh:
        check("[2.3] the pattern sheet is written beside the islands", sh.size[0] == 512, sh.size)
    n = len(RUNS)
    check("[2.3] a ready cut is not scheduled again", gtc.schedule(CHAR, ITEM, runner=fake_cut_run)["state"] == "ready"
          and len(RUNS) == n)

    SIG["value"] = "c2"
    GATE["outcome"] = "rejected"
    gtc.schedule(CHAR, ITEM, runner=fake_cut_run)
    wait_idle(ITEM, "c2")
    s4 = gtc.state(CHAR, ITEM)
    check("[2.4] a judged failure -> failed with CUT_FAILED", s4["state"] == "failed"
          and s4["reason"] == gtc.CUT_FAILED.format(error="boom"), s4)
    n = len(RUNS)
    check("[2.4] a failed key is not run again", gtc.schedule(CHAR, ITEM, runner=fake_cut_run)["state"] == "failed"
          and len(RUNS) == n)
    SIG["value"] = "c3"
    GATE["outcome"] = "timeout"
    gtc.schedule(CHAR, ITEM, runner=fake_cut_run)
    wait_idle(ITEM, "c3")
    s5 = gtc.state(CHAR, ITEM)
    check("[2.4] a run that judged nothing -> missing with CUT_LEFT", s5["state"] == "missing"
          and s5["reason"] == gtc.CUT_LEFT.format(outcome="timeout"), s5)
    n = len(RUNS)
    gtc.schedule(CHAR, ITEM, runner=fake_cut_run)
    check("[2.4] not started again within RETRY_AFTER_S", len(RUNS) == n and gtc.RETRY_AFTER_S == 300.0)
    SIG["value"] = "c1"
    GATE["outcome"] = "ok"

# [2.5] the production ``run`` around a stubbed Blender step: what it hands the builder and what it writes
CALLS = []


def fake_run_blender(body_glb, params, *, item_id, out_dir, colliders=None, own=None, over_sleeves=False, **_k):
    CALLS.append({"body": Path(body_glb).name, "kind": params["kind"], "colliders": colliders, "own": own,
                  "over": over_sleeves})
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if RUN_OUTCOME["v"] != "ok":
        return {"ok": False, "outcome": RUN_OUTCOME["v"], "error": "boom", "data": {}, "islands": None,
                "log_tail": "tail", "wall_s": 1.0, "slot_wait_s": 0.0, "measure_s": 0.1}
    (out_dir / "islands.json").write_bytes(PAYLOAD_BYTES)
    return {"ok": True, "outcome": "ok", "error": "", "data": {"script_wall_s": 10.9}, "islands": out_dir / "islands.json",
            "log_tail": "", "wall_s": 11.8, "slot_wait_s": 0.0, "measure_s": 0.3}


RUN_OUTCOME = {"v": "ok"}


def full_key(character_name, item_id, **_k):
    return {"sig": {"run1": "r1", "run2": "r2", "run3": "r3"}[item_id], "reason": "", "params": TOP,
            "base": ("base0", "bsha"), "base_sha": "bsha", "lower": [], "under": [], "item": {}}


with patch.object(gtc, "cut_key", full_key), patch.object(gtc, "run_blender", fake_run_blender), \
        patch("app.core.garment_template.collider_states", lambda *a, **k: []), \
        patch("app.core.garment_template.own_colliders", lambda *a, **k: []), \
        patch("app.core.bust_shaping.prepare", lambda body, *a, **k: (Path(body), None, "")):
    r = gtc.run(CHAR, "run1")
    rec = gtc.read_record(CHAR, "run1", "r1")
    check("[2.5] run: the plain body, no colliders, ready", r["state"] == "ready" and CALLS[-1]["body"] == "base0.glb"
          and CALLS[-1]["colliders"] == [] and CALLS[-1]["own"] == [] and CALLS[-1]["over"] is False, CALLS[-1])
    check("[2.5] run: the record (cut sig, wall, islands sha, base)", rec.get("cut_sig") == "r1"
          and rec.get("wall_s") == 11.8 and rec.get("base_model_sha256") == "bsha"
          and (rec.get("islands") or {}).get("sha256") == hashlib.sha256(PAYLOAD_BYTES).hexdigest()
          and rec.get("uv_pattern") == gtc.TOP_UV_PATTERN_SHA, rec)
    check("[2.5] run: islands bytes and sheet on disk", gtc.islands_file(CHAR, "run1", "r1").read_bytes()
          == PAYLOAD_BYTES and gtc.sheet_file(CHAR, "run1", "r1").is_file())
    n = len(CALLS)
    check("[2.5] run of a ready cut keeps it (no Blender)", gtc.run(CHAR, "run1")["state"] == "ready" and len(CALLS) == n)
    RUN_OUTCOME["v"] = "rejected"
    r2 = gtc.run(CHAR, "run2")
    check("[2.5] a rejected run -> failed record", r2["state"] == "failed"
          and gtc.read_record(CHAR, "run2", "r2").get("outcome") == "rejected", r2)
    RUN_OUTCOME["v"] = "timeout"
    r3 = gtc.run(CHAR, "run3")
    check("[2.5] a timeout -> no record, missing with CUT_LEFT", r3["state"] == "missing"
          and r3["reason"] == gtc.CUT_LEFT.format(outcome="timeout")
          and not gtc.record_file(CHAR, "run3", "r3").exists(), r3)
    RUN_OUTCOME["v"] = "ok"

# ---------------------------------------------------------------------------------------------------- [3] + [4]
_items = Path(_tmp) / "items"
_items.mkdir()
ITEM_PNG = _items / "shirtc.png"
im = Image.new("RGBA", (1200, 1100), (0, 0, 0, 0))
im.paste((150, 40, 40, 255), (200, 200, 1000, 900))
im.save(ITEM_PNG)
BACK_PNG = _items / "shirtc_back.png"
Image.new("RGBA", (800, 800), (40, 40, 150, 255)).save(BACK_PNG)
TEX = {"texture": "cut"}


def fake_get_item(iid):
    return {"id": iid, "category": "outfit_piece", "image": ITEM_PNG.name,
            "outfit_piece": {"template": {"params": {"kind": "top", "sleeves": "short", "texture": TEX["texture"]},
                                          "source": "user"}}}


NO_DRAPE = {"state": "missing", "reason": "Not draped yet", "tsig": None, "islands_path": None, "islands_sha": "",
            "record": {}, "worn": False}


def fake_pattern_cutting(character_name, item_id):
    if item_id == "cutting1":
        return {"state": "cutting", "reason": gtc.CUTTING, "cut_sig": "z9", "islands_path": None, "islands_sha": "",
                "cut_at": "", "wall_s": None, "record": {}}
    return gtc.state(character_name, item_id)


with patch.object(gtc, "cut_key", key_stub), \
        patch("app.models.inventory.get_item", fake_get_item), \
        patch("app.models.inventory.get_item_image_path", lambda iid: str(ITEM_PNG)), \
        patch("app.imagegen.routing.chain_for", lambda occasion, *a, **k: ["FakeCut*"]), \
        patch("app.imagegen.base.media_generation_enabled", lambda: True), \
        patch.object(gct, "back_view", lambda c, i: BACK_PNG), \
        patch.object(gct, "current_drape", lambda c, i: dict(NO_DRAPE)), \
        patch.object(gct, "current_pattern", fake_pattern_cutting):
    d = gct.dialog_state(CHAR, ITEM)
    sha_a = hashlib.sha256(PAYLOAD_BYTES).hexdigest()
    check("[3] no drape: the Pattern line is the cut", d.get("pattern_reason") == "" and d.get("cutting") is False
          and d.get("cut_at") == "2026-11-21T10:00:00+00:00" and d.get("cut_wall_s") == 0.5, d.get("pattern_reason"))
    check("[3] no drape: the button may start", d.get("blocked_reason") == "" and d.get("can_generate") is True,
          d.get("blocked_reason"))
    check("[3] no drape: the plan (front + back) and the cut's islands sha", (d.get("plan") or {}).get("total") == 2
          and d.get("islands_sha") == sha_a and d.get("has_back") is True, d.get("plan"))
    check("[3] the pattern sheet is the cut's", gct.pattern_sheet_file(CHAR, ITEM)
          == gtc.cut_dir(CHAR) / f"{ITEM}_c1.pattern.png")
    dc = gct.dialog_state(CHAR, "cutting1")
    check("[3] while cutting: the Pattern line says so, nothing starts", dc.get("pattern_reason") == gtc.CUTTING
          and dc.get("cutting") is True and dc.get("plan") is None and dc.get("can_generate") is False
          and dc.get("blocked_reason") == gtc.CUTTING, dc.get("pattern_reason"))

    # [4] a ready atlas made from the CUT's islands (sha A)
    item_sha = hashlib.sha256(ITEM_PNG.read_bytes()).hexdigest()
    back_sha = hashlib.sha256(BACK_PNG.read_bytes()).hexdigest()
    csig_a = gct.csig(sha_a, item_sha, back_sha)
    check("[4] csig_for the cut's islands", gct.current_csig(CHAR, ITEM) == csig_a, gct.current_csig(CHAR, ITEM))
    stem = gct._stem(CHAR, ITEM, csig_a)
    ATLAS = b"\x89PNG-atlas-a"
    gct._write_bytes(gct._file(stem, ".atlas.png"), ATLAS)
    gct._write_record(gct._file(stem, ".json"), {"csig": csig_a, "state": "ready", "islands_sha": sha_a,
                                                 "sleeve_print": "plain", "created_at": "2026-11-21T10:00:00+00:00"})
    tdir = gt.templates_dir(CHAR)
    tdir.mkdir(parents=True, exist_ok=True)

    def drape_rec(sha, payload_bytes, tsig, at):
        f = tdir / f"{ITEM}_{tsig}.islands.json"
        f.write_bytes(payload_bytes)
        return {"tsig": tsig, "created_at": at, "islands": {"file": f.name, "sha256": sha, "px_per_cm": 10.0}}

    d1 = drape_rec(sha_a, PAYLOAD_BYTES, "t1", "2026-11-21T09:00:00+00:00")
    a1, i1 = gt.atlas_for(CHAR, ITEM, d1)
    check("[4] a drape of the same cut gets the atlas", a1 == ATLAS and i1.get("texture") == "cut"
          and i1.get("csig") == csig_a, i1)
    d2 = drape_rec(sha_a, PAYLOAD_BYTES, "t2", "2026-11-21T11:00:00+00:00")
    a2, i2 = gt.atlas_for(CHAR, ITEM, d2)
    check("[4] a re-drape of the same cut (new tsig) keeps it", a2 == ATLAS and i2.get("csig") == csig_a, i2)
    pb = json.loads(PAYLOAD_BYTES)
    pb["islands"][0]["verts_px"][1][0] += 10            # another cut: the front panel 1 cm wider
    b_bytes = json.dumps(pb, sort_keys=True, separators=(",", ":")).encode()
    sha_b = hashlib.sha256(b_bytes).hexdigest()
    d3 = {**drape_rec(sha_b, b_bytes, "t3", "2026-11-21T09:00:00+00:00"), "cut_sig": "old0"}
    a3, i3 = gt.atlas_for(CHAR, ITEM, d3)
    check("[4] a drape of another, older cut never gets it: drape_behind", a3 is None
          and i3.get("texture") == "projection" and i3.get("cut_state") == "drape_behind"
          and i3.get("reason") == gt.CUT_DRAPE_BEHIND_TEXT, i3)
    w3 = gt.texture_warning({"coverage": 0.9, "iou": 0.9}, i3)
    check("[4] the figure row says why", (w3 or {}).get("cut", {}).get("state") == "drape_behind"
          and w3["cut"]["text"] == gt.CUT_DRAPE_BEHIND_TEXT, w3)
    for label, rec in (("no cut_sig", {k: v for k, v in d3.items() if k != "cut_sig"}),
                       ("the current cut_sig", {**d3, "cut_sig": "c1"})):
        a5, i5 = gt.atlas_for(CHAR, ITEM, rec)
        check(f"[4] a drape of another cut with {label}: drape_other, no promised re-drape", a5 is None
              and i5.get("cut_state") == "drape_other" and i5.get("reason") == gt.CUT_DRAPE_OTHER_TEXT
              and (gt.texture_warning({"coverage": 0.9, "iou": 0.9}, i5) or {}).get("cut", {}).get("text")
              == gt.CUT_DRAPE_OTHER_TEXT, i5)
    d4 = drape_rec(sha_b, b_bytes, "t4", "2026-11-21T11:00:00+00:00")
    a4, i4 = gt.atlas_for(CHAR, ITEM, d4)
    check("[4] a drape of a NEWER cut than the atlas: stale, never the atlas", a4 is None
          and i4.get("cut_state") == "stale", i4)

# ---------------------------------------------------------------------------------------------------- [5]
STRAPLESS = gt.validate_params({"kind": "top", "shoulders": "strapless", "length_m": 0.3})[0]
check("[5.1] the strapless top has no bodice", gt.has_bodice(STRAPLESS) is False and STRAPLESS["kind"] == "top")


def tmpl_item(params):
    return {"id": "x", "category": "outfit_piece", "outfit_piece": {"template": {"params": params, "source": "user"}}}


def no_profile(*_a, **_k):
    raise AssertionError("cut_key read the profile / body for a piece that is never cut")


with patch("app.models.character.get_character_profile", no_profile), \
        patch("app.core.base_body.current_base", no_profile):
    k51 = gtc.cut_key(CHAR, "strap1", item=tmpl_item(STRAPLESS), profile=None)
    check("[5.1] strapless: no sig, NO_PATTERN_STRAPLESS, no profile read", k51["sig"] is None
          and k51["reason"] == gtc.NO_PATTERN_STRAPLESS, k51["reason"])
    s51 = gtc.state(CHAR, "strap1", key=k51)
    check("[5.1] strapless: state blocked with the plain reason", s51["state"] == "blocked"
          and s51["reason"] == gtc.NO_PATTERN_STRAPLESS, s51)
    ksk = gtc.cut_key(CHAR, "skirt1", item=tmpl_item({"kind": "skirt"}), profile=None)
    check("[5.1] a skirt keeps NO_PATTERN", ksk["sig"] is None and ksk["reason"] == gtc.NO_PATTERN, ksk["reason"])
n = len(RUNS)
with patch.object(gtc, "cut_key", lambda c, i, **k: k51):
    check("[5.1] strapless: schedule runs nothing", gtc.schedule(CHAR, "strap1", runner=fake_cut_run)["state"]
          == "blocked" and len(RUNS) == n)
check("[5.1] sig_of: the same reason for a strapless top",
      gtc.sig_of(CHAR, "strap1", STRAPLESS, base_sha="b0", lower=[]) == (None, gtc.NO_PATTERN_STRAPLESS, []))

BRA = {"state": "missing", "tsig": "tb"}


def bra_states(*_a, **_k):
    return [("bra1", {"id": "bra1"}, dict(BRA))]


STUBS = (patch("app.core.garment_template.collider_states", bra_states),
         patch("app.core.garment_template.own_colliders", lambda *a, **k: []),
         patch("app.core.bust_shaping.key_tokens", lambda *a, **k: []))
for st in STUBS:
    st.start()
check("[5.3] the top is no fitted kind (no cut:body token)", "top" not in gt.FITTED_KINDS)
BRA["state"] = "missing"
check("[5.2] a lower layer still to be draped: no sig, WAITING_LOWER",
      gtc.sig_of(CHAR, "top1", TOP, base_sha="b0", lower=["bra1"]) == (None, gtc.WAITING_LOWER, []))
sig_left = gtc.sig_of(CHAR, "top1", TOP, base_sha="b0", lower=["bra1"], wait=False)[0]
check("[5.2] wait=False: the sig of what the drape was laid out of", sig_left == gtc.cut_sig(TOP, base_sha="b0",
      lower=["bra1:tb"]), sig_left)
BRA["state"] = "ready"
sig_ready, _r, under_ready = gtc.sig_of(CHAR, "top1", TOP, base_sha="b0", lower=["bra1"])
check("[5.3] a ready layer: its token plus collider:bra1", sig_ready == gtc.cut_sig(
      TOP, base_sha="b0", lower=["bra1:tb", "collider:bra1"]) and under_ready == ["bra1:tb"], (sig_ready, under_ready))
BRA["state"] = "failed"
sig_failed = gtc.sig_of(CHAR, "top1", TOP, base_sha="b0", lower=["bra1"])[0]
check("[5.3] a failed layer is no collider: ready != failed == the left-due sig", sig_failed != sig_ready
      and sig_failed == sig_left, (sig_failed, sig_ready, sig_left))


class _Worn:
    pieces = {"top": "top1", "underwear_top": "bra1"}
    own = ["bra1", "top1"]


BRA["state"] = "missing"
with patch("app.core.base_body.current_base", lambda *a, **k: ("base0", "b0")), \
        patch("app.core.figure.worn_sets", lambda *a, **k: _Worn()), \
        patch("app.core.garment_template.lower_layers", lambda own, item_id: ["bra1"]):
    k54 = gtc.cut_key(CHAR, "top1", item=tmpl_item(TOP), profile={"name": CHAR})
    check("[5.4] cut_key over a missing bra: no sig, WAITING_LOWER", k54["sig"] is None
          and k54["reason"] == gtc.WAITING_LOWER and k54["lower"] == ["bra1"], (k54["sig"], k54["reason"]))
    s54 = gtc.state(CHAR, "top1", key=k54)
    n = len(RUNS)
    with patch.object(gtc, "cut_key", lambda c, i, **k: k54):
        sch = gtc.schedule(CHAR, "top1", runner=fake_cut_run)
    check("[5.4] state blocked, schedule starts nothing", s54["state"] == "blocked"
          and s54["reason"] == gtc.WAITING_LOWER and sch["state"] == "blocked" and len(RUNS) == n, (s54, sch))

# ---------------------------------------------------------------------------------------------------- [6]
from app.core.garment_store import write_record  # noqa: E402

tz = gt.drape_path(CHAR, "top6", "tz")
tz.parent.mkdir(parents=True, exist_ok=True)
tz.write_bytes(b"glb")
CUR = {"sig": "cA"}


def set_record(**extra):
    write_record(tz.with_suffix(".json"), {"item_id": "top6", "tsig": "tz", "accepted": True,
                                          "created_at": "2026-11-21T09:00:00+00:00", **extra})


TOP_PROJ = {**TOP, "texture": "projection"}
with patch.object(gt, "_key", lambda *a, **k: ("tz", None, {}, TOP_PROJ, [])), \
        patch.object(gtc, "sig_of", lambda *a, **k: (CUR["sig"], "", [])):
    set_record(cut_sig="cA")
    d61 = gt.drape_state(CHAR, "top6", base_sha="b0", lower=[])
    check("[6.1] same cut -> ready", d61["state"] == "ready" and d61["tsig"] == "tz", d61["state"])
    CUR["sig"] = "cB"
    d61b = gt.drape_state(CHAR, "top6", base_sha="b0", lower=[])
    check("[6.1] another cut -> missing with CUT_REDRAPE under the same tsig", d61b["state"] == "missing"
          and d61b["reason"] == gt.CUT_REDRAPE and d61b["tsig"] == "tz", d61b)
    set_record()
    check("[6.2] a record without cut_sig -> ready", gt.drape_state(CHAR, "top6", base_sha="b0", lower=[])["state"]
          == "ready")
    set_record(cut_sig="cA")
    CUR["sig"] = None
    check("[6.3] no current sig (a layer still to be draped) -> ready",
          gt.drape_state(CHAR, "top6", base_sha="b0", lower=[])["state"] == "ready")

BRA["state"] = "ready"
rec_sig = gtc.sig_of(CHAR, "top6", TOP, base_sha="b0", lower=["bra1"])[0]
check("[6.4] the real flattening key: not behind", gt.cut_behind(CHAR, "top6", {"cut_sig": rec_sig}, TOP,
                                                               base_sha="b0", lower=["bra1"]) is False)
with patch.object(gtc, "TOP_UV_PATTERN_SHA", "ffffffffffff"):
    check("[6.4] a new top flattening: the drape is behind (re-draped by the next Build)",
          gt.cut_behind(CHAR, "top6", {"cut_sig": rec_sig}, TOP, base_sha="b0", lower=["bra1"]) is True)
kb0 = gtc.cut_sig(BRF, base_sha="b0", lower=[])
with patch.object(gtc, "UV_PATTERN_SHA", "ffffffffffff"):
    check("[6.4] uv_pattern.py changed, tops untouched: a top is not behind",
          gt.cut_behind(CHAR, "top6", {"cut_sig": rec_sig}, TOP, base_sha="b0", lower=["bra1"]) is False)
    check("[6.4] ... a fitted piece's cut_sig changes", gtc.cut_sig(BRF, base_sha="b0", lower=[]) != kb0)
check("[6.5] the bra ready after the top was draped without it: behind",
      gt.cut_behind(CHAR, "top6", {"cut_sig": sig_left}, TOP, base_sha="b0", lower=["bra1"]) is True)
for st in STUBS:
    st.stop()
_SHAPED = {"id": "top7", "outfit_piece": {"template": {"params": dict(TOP)}}}
with patch("app.core.garment_template.collider_states", bra_states), \
        patch("app.core.garment_template.own_colliders", lambda *a, **k: []), \
        patch("app.core.bust_shaping.key_tokens", lambda iid, item, lower: ["shape:x"] if item else []), \
        patch("app.models.inventory.get_item", lambda iid: _SHAPED):
    BRA["state"] = "ready"
    s_item = gtc.sig_of(CHAR, "top7", TOP, base_sha="b0", lower=["bra1"], item=_SHAPED)[0]
    s_none = gtc.sig_of(CHAR, "top7", TOP, base_sha="b0", lower=["bra1"])[0]
    check("[6.7] sig_of reads the item when none is handed: the shaping token counts",
          s_none == s_item == gtc.cut_sig(TOP, base_sha="b0", lower=["bra1:tb", "shape:x", "collider:bra1"]),
          (s_none, s_item))
    check("[6.7] a drape recorded with it is not behind for the Build's plan (item None)",
          gt.cut_behind(CHAR, "top7", {"cut_sig": s_item}, TOP, base_sha="b0", lower=["bra1"]) is False)
GT_SRC = (ROOT / "app" / "core" / "garment_template.py").read_text(encoding="utf-8")
bd = GT_SRC[GT_SRC.index("def _build_drape("):]
bd = bd[:bd.index("\ndef ")]
check("[6.6] _build_drape records sig_of(..., wait=False)", "garment_template_cut.sig_of(" in bd
      and "wait=False" in bd and "garment_template_cut.cut_sig(" not in bd)

# [7] Plan group B, B23 — a bodice cut without one marked seam (Lirien's strapped dress with a slit: measured at
#     223dd9ee0 a ``KeyError: 'uv_seam' not found`` — the all-zero edge layer was dropped by ``split_slit``'s bmesh
#     round trip) reads its helper layers through ``_int_layer`` (zeros when the layer is gone) and drops them through
#     ``_drop_layers``: no direct ``me.attributes["uv_seam"]`` access is left in the builder.
check("[7] no direct uv_seam attribute access in the builder", 'attributes["uv_seam"]' not in BUILD)
for fn in ("def pattern_uv_of(", "def pattern_uv_of_fitted("):
    body = BUILD[BUILD.index(fn):]
    body = body[:body.index("\ndef ")]
    check(f"[7] {fn[4:-1]} reads uv_seam through _int_layer and drops through _drop_layers",
          '_int_layer(me, "uv_seam"' in body and "_drop_layers(me," in body)

print()
print("ALL OK" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}")
sys.exit(1 if FAILS else 0)
