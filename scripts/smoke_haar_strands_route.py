#!/usr/bin/env python3
"""Smoke: the txt2hair category, the hair_strands occasion, ImageService.generate_strands
and the strand-file reader (app/core/strand_file.py).

Usage:  ./.venv/bin/python scripts/smoke_haar_strands_route.py
        HAAR_SAMPLE_JOB_DIR=<dir> ./.venv/bin/python scripts/smoke_haar_strands_route.py

Plan: docs/superpowers/plans/2026-11-13-strand-hair.md, Task 11 (H3, the hub contract);
spec docs/superpowers/specs/2026-11-13-strand-hair-design.md § 6.3.3; Ruling H-R6.
No server, no world DB, no network: the storage and the instance are temp dirs, the
gateway boundary of a real OpenAIMeshBackend (submit_job / _collect) is stubbed, and
socket.connect / getaddrinfo raise and count — part [7] proves zero outbound.

The fixture scripts/fixtures/haar_qmtest_s7/ is REAL data, trimmed: hub job
8132167be0a744a5b6c0890e891132cf (alias HAAR, input_name qmtest_haar_s7, prompt
"shoulder-length wavy hair", seed 7), strands numpy.linspace(0, 11151, 16) of 11152
with all 100 points, its head_prior.obj cut to the first 64 faces, info.json with
strands = 16. HAAR_SAMPLE_JOB_DIR may point at the job's FULL files (named
qmtest_haar_s7_strands.npy, qmtest_haar_s7_head.obj, info.json) — part [8b].

EXPECTED VALUES, DERIVED BY HAND FROM THE BRIEF / SPEC § 6.3.3
[1] backend_fits("hair_strands", mesh/txt2hair) True; mesh/img2hair False;
    mesh/img2mesh False; backend_fits("hair_mesh", mesh/txt2hair) False; also
    mesh_humanoid + txt2hair False. The occasion: media mesh, category txt2hair,
    character_scoped, char_spec_field "hair_strands_workflow", requires_chain False,
    label "3D hair — strands from text", covers "Hair mode HAAR"; its hint tells how to
    add the entry (openai_mesh, HAAR, txt2hair) and names CC BY-NC 4.0 (H-R6).
    Schema: "txt2hair" is a category choice, one note visible for txt2hair names HAAR
    and CC BY-NC 4.0, the extra_params description names txt2hair.
    Pool Trellis (img2mesh) + HairDeck (img2hair) + HAAR (txt2hair), empty chains:
    hair_strands -> HAAR, hair_mesh -> HairDeck, mesh_humanoid -> Trellis;
    list_strand_backends == [HAAR]; list_hair_backends == [HairDeck].
[2] _strand_alias_params({"prompt": "long wavy hair", "seed": 2, "mesh_name":
    "demo_haar_s2"}) with declared {input_name, input_prompt, seed, input_steps} and
    extra_params {"input_steps": 30, "input_foo": 1}
      == {"input_name": "demo_haar_s2", "input_prompt": "long wavy hair", "seed": 2,
          "input_steps": 30}
    An unreadable schema (no names) sends everything blind: + "input_foo": 1.
    extra_params {"input_prompt": "x", "seed": 9} never override the job's own values.
[3] generate_strands("long wavy hair", …, params {"seed": 2, "mesh_name":
    "demo_haar_s2"}): one submit; the job body has no "images" and no "files" key; its
    params == {"input_name": "demo_haar_s2-r<6 hex>", "input_prompt": "long wavy hair",
    "seed": 2, "input_steps": 30}; model "HAAR"; mode "async".
[4] The stubbed gateway answers with the three files (blobs = the fixture's bytes):
    demo_haar_s2_strands.npy, demo_haar_s2_head.obj, info.json — each written into
    output_dir byte-exact, result files in that order, backend "HAAR", job_id
    "job-haar-1", route occasion "hair_strands"; read_strand_job(output_dir) reads N 16,
    P 100. Hub resume: an attached job is stored without a new submit.
    A file named "../x" -> ValueError, nothing written (output_dir not even created).
    A job with no files -> GatewayRejectedError "Strand job returned no files".
[5] An explicit backend_glob naming an unavailable entry -> ValueError
    "Selected strand backend is unavailable — no automatic fallback", no submit.
[6] image_generation.enabled False -> MediaGenerationDisabled, nothing queued (the
    GPU queue's submit_gpu_task is never called) and nothing submitted.
[7] Zero outbound: the socket guard was never hit.
[8] Reader (Ruling H-R6: P from the shape, .npy and .ply):
    a. the fixture dir: strands (16, 100, 3) float32 = info strands/points; head 64
       faces; every strand's root (point 0) higher than its tip (point P-1): the alias
       delivers root first in +y-up space, and shoulder-length hair hangs.
    b. the same 16 strands written as binary-LE PLY and as ASCII PLY read back
       identical to the .npy.
    c. P is never assumed: a (3, 7, 3) array reads P = 7; a (4, 5, 2) array and an
       info.json with points 128 against P = 100 are refused (StrandFileError).
    d. (only with HAAR_SAMPLE_JOB_DIR) the full sample: N 11152, P 100 = info.json,
       head 5023 vertices; every root within 0.03 m of a head vertex (the head is
       "the template head/scalp the strands are rooted on"); every tip below its root.
"""
import atexit
import json
import os
import shutil
import socket
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

OUTBOUND = []
_real_connect = socket.socket.connect


def _guard_connect(self, address):
    OUTBOUND.append(("connect", address))
    raise OSError(f"smoke socket guard: outbound connect to {address!r}")


def _guard_getaddrinfo(host, *args, **kwargs):
    OUTBOUND.append(("getaddrinfo", host))
    raise socket.gaierror(f"smoke socket guard: lookup of {host!r}")


socket.socket.connect = _guard_connect
socket.getaddrinfo = _guard_getaddrinfo


def _scratch(prefix):
    p = tempfile.mkdtemp(prefix=prefix)
    atexit.register(shutil.rmtree, p, ignore_errors=True)
    return p


os.environ["ANIMATION_CLIPS_DIR"] = _scratch("haar-route-clips-")
from app.core import paths  # noqa: E402
paths.init(_scratch("haar-route-storage-"))
paths.init_instance(_scratch("haar-route-instance-"))

import numpy as np  # noqa: E402

from app.imagegen.base import ImageBackend  # noqa: E402
from app.imagegen.selection import BackendPool  # noqa: E402
from app.imagegen import routing  # noqa: E402
from app.imagegen import occasions as occ  # noqa: E402

FAILS = []
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "haar_qmtest_s7"


def check(label, got, expected):
    ok = got == expected
    print(f"  {'OK  ' if ok else 'FAIL'} {label}: {got!r}"
          + ("" if ok else f" (expected {expected!r})"))
    if not ok:
        FAILS.append(label)


class Fake(ImageBackend):
    def __init__(self, name, media="mesh", category="img2mesh", available=True):
        super().__init__(name, "http://localhost", 0.0, "fake", "FAKE_HAAR_ROUTE_")
        self.MEDIA_TYPE = media
        self.category = category
        self.ref_slot_count = 1
        self.instance_enabled = True
        self._available = available

    def check_availability(self):
        return self.available

    def _generate(self, prompt, negative_prompt, params):
        return [b"x"]


RULES = {}
routing._rules = lambda occasion: list(RULES.get(occasion, []))


def _kind(cat):
    return {"media": "mesh", "category": cat, "ref_slot_count": 1}


def part1():
    print("[1] catalog, schema, pool separation")
    fits = occ.backend_fits
    if "hair_strands" not in occ.occasion_ids():
        check("hair_strands in catalog", False, True)
        return
    check("hair_strands + txt2hair", fits("hair_strands", _kind("txt2hair")), True)
    check("hair_strands + img2hair", fits("hair_strands", _kind("img2hair")), False)
    check("hair_strands + img2mesh", fits("hair_strands", _kind("img2mesh")), False)
    check("hair_mesh + txt2hair", fits("hair_mesh", _kind("txt2hair")), False)
    check("mesh_humanoid + txt2hair", fits("mesh_humanoid", _kind("txt2hair")), False)
    o = occ.get_occasion("hair_strands")
    check("occasion values",
          (o["media"], o["category"], o["character_scoped"], o["char_spec_field"],
           o["char_spec_fallback"], o.get("requires_chain"), o["label"], o["covers"]),
          ("mesh", "txt2hair", True, "hair_strands_workflow", "", False,
           "3D hair — strands from text", "Hair mode HAAR"))
    hint = o.get("hint", "")
    check("hint: how to add the entry + license",
          all(w in hint for w in ("openai_mesh", "HAAR", "txt2hair", "CC BY-NC 4.0")), True)

    from app.core.config_schema import SECTIONS
    found = {}

    def walk(node):
        if isinstance(node, dict):
            cat = node.get("category")
            if isinstance(cat, dict) and isinstance(cat.get("choices"), list) \
                    and "img2mesh" in cat["choices"]:
                found["fields"] = node
                return
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
    walk(SECTIONS)
    fields = found.get("fields") or {}
    check("txt2hair in category choices",
          "txt2hair" in (fields.get("category") or {}).get("choices", []), True)
    check("category description names txt2hair",
          "'txt2hair'" in str((fields.get("category") or {}).get("description")), True)
    notes = [f for f in fields.values() if isinstance(f, dict) and f.get("type") == "note"
             and (f.get("visible_when") or {}).get("category") == "txt2hair"]
    check("one txt2hair note", len(notes), 1)
    check("note names HAAR + license",
          bool(notes) and all(w in str(notes[0].get("text")) for w in ("HAAR", "CC BY-NC 4.0")),
          True)
    check("extra_params description names txt2hair",
          "txt2hair" in str((fields.get("extra_params") or {}).get("description")), True)

    pool = BackendPool([Fake("Trellis", category="img2mesh"),
                        Fake("HairDeck", category="img2hair"),
                        Fake("HAAR", category="txt2hair")])
    RULES.clear()
    for oid, want in (("hair_strands", "HAAR"), ("hair_mesh", "HairDeck"),
                      ("mesh_humanoid", "Trellis"), ("mesh_object", "Trellis")):
        r = routing.resolve_image_route(oid, pool=pool)
        check(f"{oid} -> {want}", r.backend.name if r.backend else None, want)
    from app.imagegen.service import ImageService
    service = ImageService.__new__(ImageService)
    service._pool = pool
    check("list_strand_backends", [b.name for b in service.list_strand_backends()], ["HAAR"])
    check("list_hair_backends", [b.name for b in service.list_hair_backends()], ["HairDeck"])
    from app.core import config
    check("txt2hair entry seeds no mesh occasion",
          config._mesh_routing_occasions("*", [{"name": "HAAR", "api_type": "openai_mesh",
                                                "category": "txt2hair"}]), [])


def _haar_backend(extra=None, names=None):
    from app.imagegen.backends.openai_mesh import OpenAIMeshBackend
    os.environ["SMOKE_HAAR_MESH_EXTRA_PARAMS"] = json.dumps(
        extra if extra is not None else {"input_steps": 30, "input_foo": 1})
    b = OpenAIMeshBackend("HAAR", "http://gateway.invalid", 0, "SMOKE_HAAR_MESH_", model="HAAR")
    b.category = "txt2hair"
    b.instance_enabled = True
    b._available = True
    b._alias_param_names = set(names if names is not None
                               else {"input_name", "input_prompt", "seed", "input_steps"})
    return b


def part2():
    print("[2] _strand_alias_params")
    b = _haar_backend()
    if not hasattr(b, "_strand_alias_params"):
        check("_strand_alias_params exists", False, True)
        return
    req = {"prompt": "long wavy hair", "seed": 2, "mesh_name": "demo_haar_s2"}
    check("declared", b._strand_alias_params(req),
          {"input_name": "demo_haar_s2", "input_prompt": "long wavy hair", "seed": 2,
           "input_steps": 30})
    blind = _haar_backend(names=set())
    check("unreadable schema sends blind", blind._strand_alias_params(req),
          {"input_name": "demo_haar_s2", "input_prompt": "long wavy hair", "seed": 2,
           "input_steps": 30, "input_foo": 1})
    own = _haar_backend(extra={"input_prompt": "x", "seed": 9, "input_name": "y"})
    check("extra_params never override the job", own._strand_alias_params(req),
          {"input_name": "demo_haar_s2", "input_prompt": "long wavy hair", "seed": 2})
    check("build_alias_params dispatches", b.build_alias_params(req),
          b._strand_alias_params(req))


FILES = [("demo_haar_s2_strands.npy", "application/octet-stream", "file"),
         ("demo_haar_s2_head.obj", "model/obj", "file"),
         ("info.json", "application/json", "file")]


def _fixture_blobs():
    return [(FIXTURE / "qmtest_haar_s7_strands.npy").read_bytes(),
            (FIXTURE / "qmtest_haar_s7_head.obj").read_bytes(),
            (FIXTURE / "info.json").read_bytes()]


def part3_to_6():
    print("[3]-[6] generate_strands")
    from app.imagegen.service import ImageService
    from app.imagegen.base import GatewayRejectedError, MediaGenerationDisabled
    if not hasattr(ImageService, "generate_strands"):
        check("ImageService.generate_strands exists", False, True)
        return
    backend = _haar_backend()
    service = ImageService.__new__(ImageService)
    service._pool = BackendPool([backend])
    work = Path(_scratch("haar-route-work-"))
    blobs = _fixture_blobs()
    payloads = []
    answer = {"files": list(FILES), "blobs": blobs}

    def submit(_backend, _url, payload, _label, **kwargs):
        payloads.append(payload)
        return "job-haar-1"

    def collect(job_id, **kwargs):
        backend._tls.result_files = [{"name": n, "mime": m, "kind": k}
                                     for n, m, k in answer["files"]]
        return list(answer["blobs"])

    def plain_generate(prompt, negative, params, **kwargs):
        return backend._generate(prompt, negative, params)

    RULES.clear()
    with (patch("app.imagegen.backends.openai_mesh.submit_job", side_effect=submit),
          patch.object(backend, "_collect", side_effect=collect),
          patch.object(backend, "generate", side_effect=plain_generate),
          patch.object(ImageService, "run_on_backend_channel",
                       staticmethod(lambda b, fn, **kw: fn()))):
        out = work / "out"
        result = service.generate_strands("long wavy hair", str(out), character_name="Demo",
                                          params={"seed": 2, "mesh_name": "demo_haar_s2"})
        print("[3] the job body")
        check("one submit", len(payloads), 1)
        p = payloads[0] if payloads else {}
        check("no images key", "images" in p, False)
        check("no files key", "files" in p, False)
        check("model + mode", (p.get("model"), p.get("mode")), ("HAAR", "async"))
        params = dict(p.get("params") or {})
        name = params.pop("input_name", "")
        check("input_name = demo_haar_s2-r<6 hex>",
              name.startswith("demo_haar_s2-r") and len(name) == len("demo_haar_s2-r") + 6, True)
        check("params", params, {"input_prompt": "long wavy hair", "seed": 2, "input_steps": 30})

        print("[4] files, resume, hostile name, empty job")
        names = [n for n, _m, _k in FILES]
        check("every file written byte-exact",
              [(out / n).is_file() and (out / n).read_bytes() == raw
               for n, raw in zip(names, blobs)], [True, True, True])
        check("names in gateway order", [f["name"] for f in result["files"]], names)
        check("paths", [f["path"] for f in result["files"]], [str(out / n) for n in names])
        check("backend + job", (result["backend"], result["job_id"]), ("HAAR", "job-haar-1"))
        check("route occasion",
              (result.get("route") or {}).get("routing", {}).get("occasion"), "hair_strands")
        from app.core.strand_file import read_strand_job
        job = read_strand_job(out)
        check("reader on the written job (N, P)", job["strands"].shape, (16, 100, 3))

        attached = {"files": [{"name": n, "mime": m, "kind": k} for n, m, k in FILES],
                    "blobs": list(blobs), "backend": "HAAR", "job_id": "old-job",
                    "route": {"routing": {"occasion": "hair_strands", "position": 1,
                                          "spec": "HAAR"}}}
        out2 = work / "resumed"
        with patch.object(ImageService, "_hub_attached", staticmethod(lambda st: attached)):
            resumed = service.generate_strands("long wavy hair", str(out2),
                                               hub_stage=SimpleNamespace())
        check("resume: no new submit", len(payloads), 1)
        check("resume: files + job + route",
              ([(out2 / n).is_file() and (out2 / n).read_bytes() == raw
                for n, raw in zip(names, blobs)], resumed["job_id"], resumed["route"]),
              ([True, True, True], "old-job", attached["route"]))

        answer["files"] = [("../x", "application/octet-stream", "file")]
        answer["blobs"] = [b"evil-bytes-" * 20]
        out3 = work / "hostile" / "inner"
        err = ""
        try:
            service.generate_strands("long wavy hair", str(out3), backend_glob="HAAR",
                                     params={"seed": 2, "mesh_name": "demo_haar_s2"})
        except ValueError as e:
            err = type(e).__name__
        check("'../x' refused", err, "ValueError")
        check("nothing written", ((work / "hostile" / "x").exists(), out3.exists()),
              (False, False))

        answer["files"], answer["blobs"] = [], []
        err = ""
        try:
            service.generate_strands("long wavy hair", str(work / "empty"), backend_glob="HAAR",
                                     params={"seed": 2})
        except GatewayRejectedError as e:
            err = str(e)
        check("empty job", err, "Strand job returned no files")

        print("[5] explicit pick of an unavailable entry")
        n_before = len(payloads)
        offline = Fake("HAAR-offline", category="txt2hair", available=False)
        service._pool = BackendPool([backend, offline])
        err = ""
        try:
            service.generate_strands("long wavy hair", str(work / "o5"),
                                     backend_glob="HAAR-offline", params={"seed": 2})
        except ValueError as e:
            err = str(e)
        check("no automatic fallback", err,
              "Selected strand backend is unavailable — no automatic fallback")
        check("no submit", len(payloads), n_before)

    print("[6] media master switch off")
    from app.core import config
    real_get = config.get
    queued = []
    n_before = len(payloads)
    service._pool = BackendPool([backend])
    with (patch.object(config, "get", side_effect=lambda key, default=None:
                       False if key == "image_generation.enabled" else real_get(key, default)),
          patch("app.core.llm_queue.get_llm_queue",
                return_value=SimpleNamespace(submit_gpu_task=lambda **kw: queued.append(kw))),
          patch("app.imagegen.backends.openai_mesh.submit_job", side_effect=submit)):
        err = ""
        for glob in ("", "HAAR"):
            try:
                service.generate_strands("long wavy hair", str(work / "o6"), backend_glob=glob,
                                         params={"seed": 2})
            except MediaGenerationDisabled as e:
                err += type(e).__name__ + ";"
        check("MediaGenerationDisabled (routed + explicit)", err,
              "MediaGenerationDisabled;MediaGenerationDisabled;")
        check("nothing queued", len(queued), 0)
        check("nothing submitted", len(payloads), n_before)


def _write_ply(path, strands, binary):
    n, p, _ = strands.shape
    xyz = strands.reshape(-1, 3).astype("<f4")
    head = (f"ply\nformat {'binary_little_endian' if binary else 'ascii'} 1.0\n"
            f"comment strands root first\nelement vertex {n * p}\n"
            "property float x\nproperty float y\nproperty float z\n"
            f"element strand {n}\nend_header\n").encode("ascii")
    if binary:
        body = xyz.tobytes()
    else:
        body = "".join(f"{x!r} {y!r} {z!r}\n" for x, y, z in xyz.tolist()).encode("ascii")
    path.write_bytes(head + body)


def part8():
    print("[8] reader")
    from app.core import strand_file as sf
    job = sf.read_strand_job(FIXTURE)
    S = job["strands"]
    check("a. fixture shape + dtype", (S.shape, str(S.dtype)), ((16, 100, 3), "float32"))
    check("a. = info strands/points", (job["info"]["strands"], job["info"]["points"]),
          (S.shape[0], S.shape[1]))
    check("a. head faces", job["head_F"].shape, (64, 3))
    check("a. every root above its tip", bool((S[:, 0, 1] > S[:, -1, 1]).all()), True)
    summ = sf.strand_summary(S)
    print(f"       fixture summary: {summ}")

    tmp = Path(_scratch("haar-route-ply-"))
    for binary in (True, False):
        ply = tmp / f"t_{'bin' if binary else 'ascii'}_strands.ply"
        _write_ply(ply, S, binary)
        got = sf.read_strands(ply)
        check(f"b. {'binary' if binary else 'ascii'} PLY == npy",
              (got.shape, bool(np.array_equal(got, S))), (S.shape, True))

    seven = tmp / "seven_strands.npy"
    np.save(seven, np.zeros((3, 7, 3), dtype="<f4") + np.arange(7, dtype="<f4")[None, :, None])
    check("c. P from the shape", sf.read_strands(seven).shape, (3, 7, 3))
    flat = tmp / "flat_strands.npy"
    np.save(flat, np.zeros((4, 5, 2), dtype="<f4"))
    err = ""
    try:
        sf.read_strands(flat)
    except sf.StrandFileError:
        err = "StrandFileError"
    check("c. (4, 5, 2) refused", err, "StrandFileError")
    bad = tmp / "badinfo"
    bad.mkdir()
    shutil.copy(FIXTURE / "qmtest_haar_s7_strands.npy", bad / "b_strands.npy")
    (bad / "info.json").write_text(json.dumps({"strands": 16, "points": 128}))
    err = ""
    try:
        sf.read_strand_job(bad)
    except sf.StrandFileError as e:
        err = str(e)
    check("c. info points 128 vs P 100 refused", "points = 128" in err, True)

    full = os.environ.get("HAAR_SAMPLE_JOB_DIR", "").strip()
    if not full:
        print("  SKIP d. full sample (HAAR_SAMPLE_JOB_DIR not set)")
        return
    job = sf.read_strand_job(full)
    S, V = job["strands"], job["head_V"]
    check("d. N, P", S.shape, (11152, 100, 3))
    check("d. = info.json", (job["info"]["strands"], job["info"]["points"]), (11152, 100))
    check("d. head vertices", V.shape, (5023, 3))
    worst = 0.0
    for chunk in np.array_split(S[:, 0], 32):
        d2 = ((chunk[:, None, :] - V[None, :, :]) ** 2).sum(axis=2).min(axis=1)
        worst = max(worst, float(np.sqrt(d2.max())))
    check("d. every root within 0.03 m of the head", worst < 0.03, True)
    check("d. every tip below its root", bool((S[:, -1, 1] < S[:, 0, 1]).all()), True)
    print(f"       full sample summary: {sf.strand_summary(S)}; worst root-head {worst:.4f} m")


def main():
    for part in (part1, part2, part3_to_6, part8):
        try:
            part()
        except Exception as e:  # a missing piece fails its part, not the whole run
            check(f"{part.__name__} ran", f"{type(e).__name__}: {e}", "no exception")
    print("[7] zero outbound")
    check("socket guard never hit", OUTBOUND, [])
    print()
    if FAILS:
        print(f"FAIL: {len(FAILS)} check(s): {', '.join(FAILS)}")
        sys.exit(1)
    print("PASS: txt2hair category, hair_strands occasion, generate_strands, strand reader")


if __name__ == "__main__":
    main()
