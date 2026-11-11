#!/usr/bin/env python3
"""Smoke: the per-item shoe source store and its steps source -> empty -> cutout -> mesh -> insole
(app/core/footwear_source.py; plan docs/superpowers/plans/2026-11-10-footwear-rigid-shoes.md, Tasks 4 + 5;
spec docs/superpowers/specs/2026-11-10-footwear-rigid-shoes-design.md § 5.2, § 5.3, § 5.6).

Usage:  ./.venv/bin/python scripts/smoke_footwear_source.py

Throwaway storage (``paths.init(<tmp>/world)`` before any world module), an empty world + instance
config, no world DB, no hub, no server. Stubbed: ``get_image_service()`` (counters for upscale, edit
generate and generate_mesh), ``routing.run_routed`` (calls ``render`` once with the fake edit backend,
returns a real ``Route`` at position 1), ``inventory.get_item_image_path`` (fixture files under
``<tmp>/items``), ``character.run_rembg`` (the matte = every pixel whose darkest channel is < 200, i.e.
not the white background) and ``refine.decimate_to`` (copies the raw GLB). ``prompt_compose.compose``
is the real one.

Fixture images (RGBA, transparent background like the real item images):
    shoe(s)       canvas 232s x 256s, a dark (30,30,30) rectangle x in [20s, 212s), y in [140s, 240s)
                  -> footprint L = 192s, height H = 100s, aspect 1.92 (inside 1.1..2.4), one component.
    worn(s)       shoe(s) + a skin (225,180,150) column x in [100s, 140s), y in [0, 140s), touching the
                  shoe -> one component reaching row 0.
    big           1200 x 1100, the dark rectangle x in [100, 1100), y in [500, 1000).
The stub upscaler scales x4 with NEAREST (no ringing), so the upscaled 232x256 item is 928 x 1024
(long side 1024 >= MIN_SIDE: no Lanczos top-up) and equals shoe(4) / worn(4) flattened on white.

Expected, by hand:
[S1] source. Item A = shoe(1): 232 x 256 < 1024 -> exactly 1 upscale call, upscaled.png 928 x 1024,
     pixels = shoe(4) on white; record source accepted, backend "FakeUp", routing.occasion "upscale".
     Item BIG: long side 1200 >= 1024 -> 0 upscale calls; upscaled.png = the image itself flattened on
     white (1200 x 1100, pixel-identical), record upscale.status "not_needed".
[S2] no shortcut. A's upscaled image is already one clean shoe (one rectangle 768 x 400: single_share 1.0,
     aspect 1.92, no leg), yet the edit runs: exactly 1 edit call (the side view is part of what the edit
     makes). The stub answers shoe(4) on white -> iou_below_topline: the same rectangle on both sides -> 1.0
     -> accepted at attempt 1; empty.png == empty.try1.png, record empty {accepted, 1 attempt, failure None},
     no ``skipped`` key.
     The prompt the backend gets (use case footwear_source, shipped default, family natural; the style has
     no {subject} slot -> "style, subject"; the negation guard moves only the trailing clause "no foot or
     leg" -> foot, leg, already in the use-case negative):
       prompt   = "product photo, single shoe, plain white background, even studio light, the same shoe,
                   alone and empty, seen exactly from the side, toe pointing to the left, plain white
                   background"
       negative = "foot, leg, skin, person, pair of shoes, second shoe, shadow clutter"
[S2b] the real cause of a failed upscale: upscale_image raises NoRouteError("upscale", FakeUp* cooling
     down) chained from BackendFailedError(FakeUp, "FakeUp: job u1 failed: ComfyUI: node 3 IrisUpscale: CUDA
     out of memory") -> Lanczos fallback (accepted), upscale {status "lanczos", reason = the
     BackendFailedError text}, no "cooling down" in it (item L = shoe(1)).
[S3] Item W = worn(1). Upscaled matte: one component 768 wide, rows 0..959 (960 tall). Leg: the middle
     [round(.35*768)=269, round(.65*768)=499) holds the column (offsets 320..479) at height 960 against the
     counter 400 -> excess 560 > .05*768 = 38.4 -> leg; aspect 768/960 = 0.8 also out. -> edit called.
     The stub answers shoe(4) on white: one 768 x 400 rectangle, no leg; iou_below_topline: the item kept
     below the empty shoe's top edge (400 rows over its 768 columns) = the rectangle, the leg column above it
     drops out -> 1.0.
     -> accepted at attempt 1: 1 edit call, occasion "footwear_empty", has_ref True, pool = svc.pool,
     params seed 0*1000 + 1 = 1, reference_images {"input_reference_image_1": <upscaled.png>}, the prompt
     carries the use case style "product photo, single shoe" and "the same shoe, alone and empty";
     empty.try1.png + .json written, empty.png = the try; record routing.position 1.
     Item R = worn(1) with the stub answering worn(4) both times -> leg both times -> refused after
     exactly 2 calls (seeds 1, 2), run_source {ok False, step "empty"}, record empty accepted False with
     2 attempts (each leg True), empty.try1/2 kept, no empty.png, cutout/mesh not run.
[S4] cutout of W: the stub matte of empty.png is the 768 x 400 rectangle at x [80, 848), y [560, 960).
     Square crop: side int(1.15 * 768) = 883 < 1024 -> Lanczos to 1024 x 1024; RGBA; the alpha box keeps
     the aspect 768/400 = 1.92 (+-0.02). No service call (counters unchanged).
[S5] mesh of W: generate_mesh called once with occasion "mesh_footwear", face_num 100000, material
     "dielectric", alpha "opaque", no view_images, source = cutout.png, output = raw.glb, mesh_name
     "footwear-<W>"; decimate_to(raw, 60000, <candidate>, merge_vertices=True) (TARGET_TRIS 60 000 since the P3
     acceptance: 30 000 collapsed a real pump's cavity).
     The GLB: box A 0.25 x 0.13 x 0.09 m, box B 0.10 x 0.02 x 0.05 m centred inside A (24 tris).
     Areas: A = 2(.25*.13 + .25*.09 + .13*.09) = 2(.0325 + .0225 + .0117) = .1334;
            B = 2(.10*.02 + .10*.05 + .02*.05) = 2(.002 + .005 + .001) = .016.
     largest share = .1334 / .1494 = 0.89290; component_share (B lies inside A's box) = 1.0 >= 0.98.
     mesh_iou: the side silhouette of a box is a filled rectangle, the cut-out alpha a rectangle; both
     are cropped to their bbox and resampled -> 1.0 (+-0.02) >= 0.80. -> accepted, prepared.glb exists.
     Item X = shoe(1), its empty edit answered with shoe(4) (accepted, 1.0 as in S2): box B moved OUTSIDE A
     (x offset 0.5 m) on both attempts -> component_share = 0.89290 <
     0.98 -> 2 mesher calls, refused, no prepared.glb.
     The same run goes on to the insole of the two boxes (footwear_insole, L = 0.25, AIR = 0.00625,
     TOL = 0.00875; 240 stations x int(240 * 0.09 / 0.25) = 86 columns): A's top (0.13) faces up with
     nothing above, B's top (0.03) faces up with 0.10 of air -> both candidates. Seed station 132
     (x = 0.1381, inside B's x [0.075, 0.175]): B's columns (|z| <= 0.025: j = 19..66, 48 columns) start
     at 0.03, the rest at 0.13; past B's ends B's columns lose the track (0.10 > TOL) and the second pass
     gives them the station median 0.13 -> insole_cover 1.0. Forefoot x >= 0.62 L = 0.155 (stations
     149..239, 91): covered only where the insole is B's top under A's top, stations 149..167 (x <=
     0.175) x 48 columns -> vamp_cover = 19 * 48 / (91 * 86) = 912 / 7826 = 0.1165 < 0.6. Opening: the
     topline is A's top edge 0.13 at every station; the profile (the middle columns j 22..63, all in B) is
     0.03 at B's stations 72..167 (x in [0.0753, 0.1747]) and 0.13 elsewhere -> walls >= AIR above the
     insole at 96 of 240 stations -> opening_share 0.4 < 0.5 -> the closed box is SOLID (that reason wins
     over vamp_cover) -> run_source {ok False, step "insole", ran ["mesh"]}, the error starts with
     SOLID_REFUSED, insole.json written with gates.refusal SOLID_REFUSED, record insole accepted False.
[S5b] the wedge pump of scripts/_footwear_fixtures.py written as W's prepared.glb, run_source(W,
     steps=["insole"], force=True) -> ok, ran ["insole"], 0 service calls, record insole accepted with
     version 2 and nominal pitch 30.61 deg (smoke_footwear_insole [I1]); insole.json heel_seat_h_m 0.09.
[S6] second run_source(W) -> ran == [], 0 calls of any kind. regenerate(W, "mesh") -> seed 1, new ssig =
     ssig_for(W, 1) != old; upscaled/empty/cutout copied (bytes equal) with copied_from = old ssig, no
     mesh record in the new folder; the next run_source -> mesh runs (exactly 1 mesher call, 0 upscale,
     0 edit) and the two boxes' insole is refused again -> {ok False, ssig new, ran ["mesh"]}.
[S7] ssig_for(A, 0) == md5(json.dumps({"image": sha256(A file), "version": 2, "seed": 0},
     sort_keys=True))[:12]; current(A) == {"ssig": that, "seed": 0} before any regenerate.
[S8] anti-goal: every item image file's sha256 and mtime_ns are unchanged after S1-S6.
[S9] item_dir("../evil") -> ValueError (safe_item_id); item_dir(A) lies under root().
"""
import hashlib
import io
import json
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

FAILED = []


def check(label, got, expected):
    ok = got == expected
    print(f"  {'OK  ' if ok else 'FAIL'} {label}: {got!r}" + ("" if ok else f" (expected {expected!r})"))
    if not ok:
        FAILED.append(label)


def near(label, got, want, tol):
    ok = got is not None and abs(float(got) - want) <= tol
    print(f"  {'OK  ' if ok else 'FAIL'} {label}: {got!r}" + ("" if ok else f" (expected {want} +- {tol})"))
    if not ok:
        FAILED.append(label)


# --- fixtures ---------------------------------------------------------------------------------------------------------

def shoe(s, *, worn=False):
    from PIL import Image, ImageDraw
    im = Image.new("RGBA", (232 * s, 256 * s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rectangle([20 * s, 140 * s, 212 * s - 1, 240 * s - 1], fill=(30, 30, 30, 255))
    if worn:
        d.rectangle([100 * s, 0, 140 * s - 1, 140 * s - 1], fill=(225, 180, 150, 255))
    return im


def big():
    from PIL import Image, ImageDraw
    im = Image.new("RGBA", (1200, 1100), (0, 0, 0, 0))
    ImageDraw.Draw(im).rectangle([100, 500, 1099, 999], fill=(30, 30, 30, 255))
    return im


def flat(im):
    from PIL import Image
    out = Image.new("RGB", im.size, (255, 255, 255))
    out.paste(im.convert("RGB"), mask=im.getchannel("A"))
    return out


def png(im) -> bytes:
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def box(lo, hi):
    """8 vertices, 12 outward triangles of an axis-aligned box."""
    x0, y0, z0 = lo
    x1, y1, z1 = hi
    P = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
         (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    F = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4),
         (3, 6, 2), (3, 7, 6), (0, 4, 7), (0, 7, 3), (1, 2, 6), (1, 6, 5)]
    return P, F


def two_boxes(inside=True) -> bytes:
    from app.core import glb_mesh
    pa, fa = box((0.0, 0.0, -0.045), (0.25, 0.13, 0.045))
    off = 0.0 if inside else 0.5
    pb, fb = box((0.075 + off, 0.01, -0.025), (0.175 + off, 0.03, 0.025))
    P = pa + pb
    F = fa + [(a + 8, b + 8, c + 8) for a, b, c in fb]
    return glb_mesh.static_glb(P, F, [(0.0, 0.0)] * len(P))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --- stubs ------------------------------------------------------------------------------------------------------------

class EditBackend:
    name = "FakeEdit"
    api_type = "fake"
    image_family = "natural"
    model = ""
    ref_slot_count = 1
    max_side = 2048

    def __init__(self):
        self.calls = []
        self.answers = []          # one callable per call (popped); the last one repeats

    def generate(self, prompt, negative, params, log_meta=None):
        self.calls.append({"prompt": prompt, "negative": negative, "params": dict(params)})
        answer = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        return [answer()]


class Service:
    enabled = True

    def __init__(self, edit):
        self.pool = object()
        self.edit = edit
        self.upscales = 0
        self.meshes = []
        self.mesh_answer = lambda: two_boxes(True)

    def upscale_image(self, image_bytes, *, character_name="", **_kw):
        from PIL import Image
        self.upscales += 1
        with Image.open(io.BytesIO(image_bytes)) as im:
            up = im.convert("RGB").resize((im.width * 4, im.height * 4), Image.NEAREST)
        return {"bytes": png(up), "backend": "FakeUp", "scale": 4, "status": "applied",
                "in": [up.width // 4, up.height // 4], "out": [up.width, up.height],
                "routing": {"occasion": "upscale", "position": 1, "spec": "FakeUp*"}}

    def run_on_backend(self, backend, op, character_name=""):
        return op(backend), backend

    def run_on_backend_channel(self, backend, gen_fn, **_kw):
        return gen_fn()

    def generate_mesh(self, source_image_path, output_path, **kw):
        self.meshes.append({"source_image_path": source_image_path, "output_path": output_path, **kw})
        Path(output_path).write_bytes(self.mesh_answer())
        return {"ok": True, "path": output_path, "backend": "FakeMesh",
                "routing": {"occasion": kw.get("occasion"), "position": 1, "spec": "FakeMesh*"}}

    def counts(self):
        return (self.upscales, len(self.edit.calls), len(self.meshes))


def fake_rembg(data, model="u2net", **kwargs):
    import numpy as np
    from PIL import Image
    with Image.open(io.BytesIO(data)) as im:
        rgba = im.convert("RGBA")
    arr = np.asarray(rgba)
    matte = ((arr[..., :3].min(axis=2) < 200) & (arr[..., 3] > 0)).astype(np.uint8) * 255
    if kwargs.get("only_mask"):
        return png(Image.fromarray(matte, "L"))
    out = rgba.copy()
    out.putalpha(Image.fromarray(matte, "L"))
    return png(out)


DECIMATE_CALLS = []


def fake_decimate(path_in, target_tris, out, *, merge_vertices=False):
    DECIMATE_CALLS.append({"target": target_tris, "merge_vertices": merge_vertices, "out": str(out)})
    shutil.copyfile(path_in, out)
    return {"ok": True, "path": str(out), "tris_before": 24, "tris": 24, "ratio": 0.999, "error": ""}


# --- main -------------------------------------------------------------------------------------------------------------

def main():
    import numpy as np
    from PIL import Image
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "instance")
        from app.core import config
        world_cfg = root / "world" / "config.json"
        inst_cfg = root / "instance" / "config.json"
        world_cfg.write_text("{}", encoding="utf-8")
        inst_cfg.write_text("{}", encoding="utf-8")
        config.load(world_cfg, inst_cfg)

        items = root / "items"
        items.mkdir()
        fixtures = {"shoe_a": shoe(1), "shoe_big": big(), "shoe_w": shoe(1, worn=True),
                    "shoe_r": shoe(1, worn=True), "shoe_x": shoe(1), "shoe_l": shoe(1)}
        files = {}
        for iid, im in fixtures.items():
            p = items / f"{iid}.png"
            im.save(p, format="PNG")
            files[iid] = p
        before = {iid: (sha(p), p.stat().st_mtime_ns) for iid, p in files.items()}

        edit = EditBackend()
        svc = Service(edit)
        routed = []

        from app.imagegen.routing import Route

        def fake_run_routed(occasion, render, *, character="", has_ref=False, pool=None, **_kw):
            routed.append({"occasion": occasion, "has_ref": has_ref, "pool_is_svc": pool is svc.pool})
            result = render(edit)
            return result, Route(occasion=occasion, backend=edit, position=1, spec="FakeEdit*",
                                 intended_spec="FakeEdit*", first_position=1)

        with patch("app.models.inventory.get_item_image_path", lambda iid: str(files.get(iid, ""))), \
             patch("app.imagegen.service.get_image_service", lambda: svc), \
             patch("app.imagegen.routing.run_routed", fake_run_routed), \
             patch("app.models.character.run_rembg", fake_rembg), \
             patch("app.blender.refine.decimate_to", fake_decimate):
            from app.core import footwear_source as fs

            print("[S7] ssig")
            want = hashlib.md5(json.dumps({"image": before["shoe_a"][0], "version": 2, "seed": 0},
                                          sort_keys=True).encode()).hexdigest()[:12]
            check("ssig_for(A, 0)", fs.ssig_for("shoe_a", 0), want)
            check("current(A)", fs.current("shoe_a"), {"ssig": want, "seed": 0})
            check("current_ssig(A)", fs.current_ssig("shoe_a"), want)
            check("constants", (fs.FOOTWEAR_SOURCE_VERSION, fs.MIN_SIDE, fs.EMPTY_ATTEMPTS, fs.EDIT_OCCASION,
                                fs.MESH_OCCASION, fs.USE_CASE, fs.TARGET_TRIS, fs.FACE_NUM, fs.ITEM_STEPS),
                  (2, 1024, 2, "footwear_empty", "mesh_footwear", "footwear_source", 60000, 100000,
                   ("source", "empty", "cutout", "mesh", "insole")))
            check("EMPTY_PROMPT", fs.EMPTY_PROMPT,
                  "the same shoe, alone and empty, seen exactly from the side, "
                  "toe pointing to the left, plain white background, no foot or leg")

            print("[S9] item_dir safety")
            try:
                fs.item_dir("../evil")
                check("item_dir('../evil') raises", False, True)
            except ValueError:
                check("item_dir('../evil') raises", True, True)
            check("item_dir under root", fs.item_dir("shoe_a").resolve().parent == fs.root().resolve(), True)
            check("root", fs.root(), paths.get_storage_dir() / "footwear")

            print("[S1] source")
            res = fs.run_source("shoe_a", steps=["source"])
            ssig_a = fs.current_ssig("shoe_a")
            d = fs.source_dir("shoe_a", ssig_a)
            check("A ok", (res.get("ok"), res.get("ran")), (True, ["source"]))
            check("A upscale calls", svc.upscales, 1)
            with Image.open(d / "upscaled.png") as up:
                check("A upscaled size", up.size, (928, 1024))
                check("A upscaled = shoe(4) on white",
                      bool(np.array_equal(np.asarray(up.convert("RGB")), np.asarray(flat(shoe(4))))), True)
            rec = fs.step_record("shoe_a", ssig_a, "source")
            check("A source record", (rec.get("accepted"), rec.get("backend"),
                                      (rec.get("routing") or {}).get("occasion")), (True, "FakeUp", "upscale"))
            res = fs.run_source("shoe_big", steps=["source"])
            dbig = fs.source_dir("shoe_big", fs.current_ssig("shoe_big"))
            check("BIG ok", res.get("ok"), True)
            check("BIG upscale calls (still 1)", svc.upscales, 1)
            with Image.open(dbig / "upscaled.png") as up:
                check("BIG upscaled = image on white",
                      (up.size, bool(np.array_equal(np.asarray(up.convert("RGB")), np.asarray(flat(big())))),),
                      ((1200, 1100), True))
            check("BIG upscale status",
                  (fs.step_record("shoe_big", fs.current_ssig("shoe_big"), "source").get("upscale") or {})
                  .get("status"), "not_needed")

            print("[S2] no shortcut: the edit always runs")
            edit.answers = [lambda: png(flat(shoe(4)))]
            res = fs.run_source("shoe_a", steps=["empty"])
            check("A empty ok", (res.get("ok"), res.get("ran")), (True, ["empty"]))
            check("A edit calls", len(edit.calls), 1)
            check("A empty.png == try1", (d / "empty.png").read_bytes() == (d / "empty.try1.png").read_bytes(),
                  True)
            rec = fs.step_record("shoe_a", ssig_a, "empty")
            check("A empty record", (rec.get("accepted"), len(rec.get("attempts") or []), rec.get("failure"),
                                     "skipped" in rec), (True, 1, None, False))
            check("A step_done empty", fs.step_done("shoe_a", ssig_a, "empty"), True)
            check("A prompt", edit.calls[-1]["prompt"],
                  "product photo, single shoe, plain white background, even studio light, the same shoe, "
                  "alone and empty, seen exactly from the side, toe pointing to the left, plain white background")
            check("A negative", edit.calls[-1]["negative"],
                  "foot, leg, skin, person, pair of shoes, second shoe, shadow clutter")

            print("[S2b] the real cause of a failed upscale")
            from app.imagegen.base import BackendFailedError
            from app.imagegen.routing import NoRouteError
            up_cause = "FakeUp: job u1 failed: ComfyUI: node 3 IrisUpscale: CUDA out of memory"
            no_route = NoRouteError("upscale", [{"spec": "FakeUp*", "status": "cooldown"}])
            no_route.__cause__ = BackendFailedError(type("B", (), {"name": "FakeUp"})(), RuntimeError(up_cause))
            real_upscale = svc.upscale_image

            def dead_upscale(*_a, **_kw):
                raise no_route
            svc.upscale_image = dead_upscale
            try:
                res = fs.run_source("shoe_l", steps=["source"])
            finally:
                svc.upscale_image = real_upscale
            rec = fs.step_record("shoe_l", fs.current_ssig("shoe_l"), "source")
            check("L source accepted (Lanczos)", (res.get("ok"), rec.get("accepted")), (True, True))
            check("L upscale status", rec.get("upscale", {}).get("status"), "lanczos")
            check("L upscale reason text", rec.get("upscale", {}).get("reason"), up_cause)

            print("[S3] edit")
            edit.answers = [lambda: png(flat(shoe(4)))]
            res = fs.run_source("shoe_w", steps=["source", "empty"])
            ssig_w = fs.current_ssig("shoe_w")
            dw = fs.source_dir("shoe_w", ssig_w)
            check("W ok", (res.get("ok"), res.get("ran")), (True, ["source", "empty"]))
            check("W edit calls", len(edit.calls), 2)
            check("W routed", routed[-1], {"occasion": "footwear_empty", "has_ref": True, "pool_is_svc": True})
            call = edit.calls[-1]
            check("W seed", call["params"].get("seed"), 1)
            check("W reference", call["params"].get("reference_images"),
                  {"input_reference_image_1": str(dw / "upscaled.png")})
            check("W prompt style", "product photo, single shoe" in call["prompt"], True)
            check("W prompt subject", "the same shoe, alone and empty" in call["prompt"], True)
            rec = fs.step_record("shoe_w", ssig_w, "empty")
            check("W empty record", (rec.get("accepted"), len(rec.get("attempts") or []),
                                     (rec.get("routing") or {}).get("position")), (True, 1, 1))
            g = rec.get("gates") or {}
            near("W iou_below_topline", g.get("iou_below_topline"), 1.0, 0.01)
            check("W try files", ((dw / "empty.try1.png").is_file(), (dw / "empty.try1.json").is_file()),
                  (True, True))
            check("W empty.png = try1", (dw / "empty.png").read_bytes() == (dw / "empty.try1.png").read_bytes(),
                  True)
            first_attempt_gate = (rec.get("attempts") or [{}])[0].get("gates") or {}
            check("W attempt gate ok", first_attempt_gate.get("ok"), True)

            edit.answers = [lambda: png(flat(shoe(4, worn=True)))]
            n0 = len(edit.calls)
            res = fs.run_source("shoe_r")
            ssig_r = fs.current_ssig("shoe_r")
            dr = fs.source_dir("shoe_r", ssig_r)
            check("R refused", (res.get("ok"), res.get("step")), (False, "empty"))
            check("R edit calls", len(edit.calls) - n0, 2)
            check("R seeds", [c["params"].get("seed") for c in edit.calls[n0:]], [1, 2])
            rec = fs.step_record("shoe_r", ssig_r, "empty")
            check("R record", (rec.get("accepted"), [bool((a.get("gates") or {}).get("leg"))
                                                     for a in rec.get("attempts") or []]), (False, [True, True]))
            check("R tries kept", ((dr / "empty.try1.png").is_file(), (dr / "empty.try2.png").is_file()),
                  (True, True))
            check("R no empty.png", (dr / "empty.png").exists(), False)
            check("R cutout not run", (dr / "cutout.png").exists(), False)
            check("R gates in result", isinstance(res.get("gates"), dict) and bool(res.get("error")), True)

            print("[S4] cutout")
            c0 = svc.counts()
            res = fs.run_source("shoe_w", steps=["cutout"])
            check("W cutout ok", (res.get("ok"), res.get("ran")), (True, ["cutout"]))
            check("W cutout no service call", svc.counts(), c0)
            with Image.open(dw / "cutout.png") as cut:
                check("W cutout mode/size", (cut.mode, cut.size), ("RGBA", (1024, 1024)))
                x0, y0, x1, y1 = cut.getchannel("A").point(lambda v: 255 if v >= 128 else 0).getbbox()
                near("W cutout alpha aspect", (x1 - x0) / (y1 - y0), 1.92, 0.02)

            print("[S5] mesh")
            from app.core import footwear_insole as fi
            res = fs.run_source("shoe_w")
            check("W mesh ran, insole refused", (res.get("ok"), res.get("step"), res.get("ran")),
                  (False, "insole", ["mesh"]))
            check("W insole error", str(res.get("error", "")).startswith(fi.SOLID_REFUSED), True)
            check("W mesher calls", len(svc.meshes), 1)
            m = svc.meshes[-1]
            check("W mesh args", (m.get("occasion"), m.get("face_num"), m.get("material"), m.get("alpha"),
                                  m.get("view_images"), m.get("mesh_name")),
                  ("mesh_footwear", 100000, "dielectric", "opaque", None, "footwear-shoe_w"))
            check("W mesh paths", (m["source_image_path"], m["output_path"]),
                  (str(dw / "cutout.png"), str(dw / "raw.glb")))
            check("W decimate", (DECIMATE_CALLS[-1]["target"], DECIMATE_CALLS[-1]["merge_vertices"]), (60000, True))
            rec = fs.step_record("shoe_w", ssig_w, "mesh")
            g = rec.get("gates") or {}
            check("W mesh accepted", (rec.get("accepted"), rec.get("backend"),
                                      (rec.get("routing") or {}).get("occasion")), (True, "FakeMesh", "mesh_footwear"))
            near("W largest share", g.get("largest_share"), 0.1334 / 0.1494, 1e-4)
            near("W component_share", g.get("component_share"), 1.0, 1e-6)
            near("W mesh_iou", g.get("mesh_iou"), 1.0, 0.02)
            check("W prepared.glb", (dw / "prepared.glb").is_file(), True)
            check("W no candidate left", [p.name for p in dw.iterdir() if "candidate" in p.name], [])
            ins = json.loads((dw / "insole.json").read_text(encoding="utf-8"))
            check("W insole.json written", (ins.get("version"), (ins.get("gates") or {}).get("refusal")),
                  (2, fi.SOLID_REFUSED))
            near("W boxes insole_cover", ins.get("insole_cover"), 1.0, 1e-6)
            near("W boxes vamp_cover", ins.get("vamp_cover"), 912 / 7826, 1e-6)
            near("W boxes opening_share", ins.get("opening_share"), 96 / 240, 1e-6)
            rec = fs.step_record("shoe_w", ssig_w, "insole")
            check("W insole record refused", (rec.get("accepted"), (rec.get("gates") or {}).get("refusal")),
                  (False, fi.SOLID_REFUSED))
            check("W step_done insole", fs.step_done("shoe_w", ssig_w, "insole"), False)

            print("[S5b] insole of the wedge pump")
            from _footwear_fixtures import wedge
            from app.core import glb_mesh
            wp, wf = wedge()
            (dw / "prepared.glb").write_bytes(glb_mesh.static_glb(wp, wf, np.zeros((len(wp), 2))))
            c0 = svc.counts()
            res = fs.run_source("shoe_w", steps=["insole"], force=True)
            check("W insole ok", (res.get("ok"), res.get("ran")), (True, ["insole"]))
            check("W insole no service call", svc.counts(), c0)
            rec = fs.step_record("shoe_w", ssig_w, "insole")
            check("W insole record", (rec.get("accepted"), rec.get("version")), (True, 2))
            near("W insole pitch", (rec.get("nominal") or {}).get("pitch_deg"), 30.61, 0.1)
            ins = json.loads((dw / "insole.json").read_text(encoding="utf-8"))
            near("W insole.json heel seat", (ins.get("nominal") or {}).get("heel_seat_h_m"), 0.09, 1e-5)
            check("W step_done insole", fs.step_done("shoe_w", ssig_w, "insole"), True)

            svc.mesh_answer = lambda: two_boxes(False)
            edit.answers = [lambda: png(flat(shoe(4)))]
            n0 = len(svc.meshes)
            res = fs.run_source("shoe_x")
            ssig_x = fs.current_ssig("shoe_x")
            check("X refused", (res.get("ok"), res.get("step")), (False, "mesh"))
            check("X mesher calls", len(svc.meshes) - n0, 2)
            rec = fs.step_record("shoe_x", ssig_x, "mesh")
            near("X component_share", (rec.get("gates") or {}).get("component_share"), 0.1334 / 0.1494, 1e-4)
            check("X no prepared", (fs.source_dir("shoe_x", ssig_x) / "prepared.glb").exists(), False)
            svc.mesh_answer = lambda: two_boxes(True)

            print("[S6] cache + regenerate")
            c0 = svc.counts()
            res = fs.run_source("shoe_w")
            check("W rerun ran", (res.get("ok"), res.get("ran")), (True, []))
            check("W rerun calls", svc.counts(), c0)
            new = fs.regenerate("shoe_w", "mesh")
            check("regenerate ssig", (new != ssig_w, new, fs.current("shoe_w")),
                  (True, fs.ssig_for("shoe_w", 1), {"ssig": fs.ssig_for("shoe_w", 1), "seed": 1}))
            dn = fs.source_dir("shoe_w", new)
            for step, name in (("source", "upscaled.png"), ("empty", "empty.png"), ("cutout", "cutout.png")):
                check(f"copied {name}", (dn / name).read_bytes() == (dw / name).read_bytes(), True)
                check(f"copied_from {step}", fs.step_record("shoe_w", new, step).get("copied_from"), ssig_w)
            check("no mesh in new", (fs.step_record("shoe_w", new, "mesh"), (dn / "prepared.glb").exists()),
                  ({}, False))
            c0 = svc.counts()
            res = fs.run_source("shoe_w")
            check("W after regenerate", (res.get("ok"), res.get("ssig"), res.get("step"), res.get("ran")),
                  (False, new, "insole", ["mesh"]))
            up, ed, me = svc.counts()
            check("W after regenerate calls", (up - c0[0], ed - c0[1], me - c0[2]), (0, 0, 1))

            print("[S8] item images untouched")
            for iid, p in files.items():
                check(f"{iid} sha/mtime", (sha(p), p.stat().st_mtime_ns), before[iid])

    if FAILED:
        print(f"\n{len(FAILED)} check(s) failed: {FAILED}")
        sys.exit(1)
    print("\nALL PASS")


if __name__ == "__main__":
    main()
