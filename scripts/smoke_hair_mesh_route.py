#!/usr/bin/env python3
"""Smoke: the img2hair category, the hair_mesh occasion and ImageService.generate_hair.

Usage:  ./.venv/bin/python scripts/smoke_hair_mesh_route.py

Plan: docs/superpowers/plans/2026-11-09-hairdeck-hair.md, Task 1 (HairDeck as a
second hair method). No server, no network, no world DB: the storage is a temp
dir, the backends are fakes in a real BackendPool (parts 2/3) or a real
OpenAIMeshBackend whose gateway boundary (submit_job / _collect) is stubbed
(part 4). The chain rules come through routing's test seam ``_rules``; the
character profile through a patched ``get_character_profile``.

EXPECTED VALUES, DERIVED BY HAND FROM THE TASK BRIEF
[1] Catalog + schema.
    get_occasion("hair_mesh") carries exactly
      category "img2hair", media "mesh", character_scoped True,
      char_spec_field "hair_mesh_workflow", char_spec_fallback "",
      requires_chain False,
      hint "Hair cards from one image of the character (e.g. HairDeck)."
    The image-backend "category" select of config_schema lists "img2hair".
    A note field shows only for category img2hair and names HairDeck.
[2] Review Focus 5 — pool separation. Pool: "Trellis" (mesh/img2mesh, cost 0)
    and "HairDeck" (mesh/img2hair, cost 0), both enabled and available; every
    chain empty. backend_fits demands category == the occasion's category for
    mesh media, so:
      mesh_humanoid, mesh_creature, mesh_object, mesh_building, mesh_garment
        -> "Trellis" each (the empty-chain pick = cheapest FITTING backend;
           HairDeck never fits);
      hair_mesh -> "HairDeck" (Trellis does not fit an img2hair occasion).
    Also config._mesh_routing_occasions (the seed rule "an img2mesh backend
    serves all five mesh occasions") gives [] for a lone img2hair entry.
[3] Character "Kira" with outfit_imagegen.hair_mesh_workflow = "Hair*" and the
    world chain ["HairDeck"]: chain_for("hair_mesh", "Kira") ==
      [("Hair*", "character", 0), ("HairDeck", "rule", 1)].
    Without a character: [("HairDeck", "rule", 1)].
    The field is not read by any other occasion: chain_for("mesh_humanoid",
    "Kira") with no rules and no mesh_workflow == [].
[4] generate_hair on a real OpenAIMeshBackend (category img2hair, alias schema
    image slot input_image, params input_name/seed/input_variations/input_steps/
    input_cfg/input_export_vrm; extra_params {"input_steps": 30,
    "input_bogus": 1}). The stubbed gateway answers with the 9 results of the
    real job ~/claude-out/hairdeck/job.json, in its order:
      hair_seed42_nohead.glb  hair_seed42.glb  cards_seed42.json
      chains_seed42.json  info.json  prep.png  model_input.png
      hair_seed42_chains.glb  hair_seed42_nohead_chains.glb
    (The plan's Global Constraints list 7 names = "8 results" in the brief;
    the real alias also delivers the two *_chains.glb, so 9 is the true count.)
    a. The request: images == {"input_image": base64(profile bytes)};
       params == {"input_name": "Kira_hair-r<6 hex>", "seed": 42,
                  "input_steps": 30} — input_bogus is not declared, dropped.
    b. Every file is written as <output_dir>/<gateway name> with the exact
       blob (blob i = b"blob-<i>-<name>").
    c. result["files"] lists the 9 names in the gateway's order, each with
       its mime and that path; backend "HairDeck"; job_id "job-hair-1";
       route["routing"]["occasion"] == "hair_mesh".
    d. Hub resume: with a collected job attached (files + blobs of the same
       9 results, backend "HairDeck", job "old-job", route {"routing": {...}})
       nothing is submitted (submit count unchanged), all 9 files are written,
       job_id "old-job", route == the attached route.
    e. A gateway name that is not a plain file name ("../evil.glb") is refused
       with a ValueError and nothing lands outside output_dir.
    f. A missing input image raises FileNotFoundError before any submit.
"""
import atexit
import base64
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _scratch(prefix):
    p = tempfile.mkdtemp(prefix=prefix)
    atexit.register(shutil.rmtree, p, ignore_errors=True)
    return p


os.environ["ANIMATION_CLIPS_DIR"] = _scratch("hair-route-clips-")
from app.core import paths  # noqa: E402
paths.init(_scratch("hair-route-storage-"))
_INSTANCE = tempfile.mkdtemp(prefix="hair-route-instance-")
atexit.register(shutil.rmtree, _INSTANCE, ignore_errors=True)
paths.init_instance(_INSTANCE)

from app.imagegen.base import ImageBackend  # noqa: E402
from app.imagegen.selection import BackendPool  # noqa: E402
from app.imagegen import routing  # noqa: E402
from app.imagegen import occasions as occ  # noqa: E402

FAILS = []


def check(label, got, expected):
    ok = got == expected
    print(f"  {'OK  ' if ok else 'FAIL'} {label}: {got!r}"
          + ("" if ok else f" (expected {expected!r})"))
    if not ok:
        FAILS.append(label)


class Fake(ImageBackend):
    def __init__(self, name, media="mesh", category="img2mesh", cost=0):
        super().__init__(name, "http://localhost", float(cost), "fake", "FAKE_HAIR_ROUTE_")
        self.MEDIA_TYPE = media
        self.category = category
        self.ref_slot_count = 1
        self.instance_enabled = True
        self._available = True

    def check_availability(self):
        return self.available

    def _generate(self, prompt, negative_prompt, params):
        return [b"x"]


RULES = {}
routing._rules = lambda occasion: list(RULES.get(occasion, []))

JOB_RESULTS = [
    ("hair_seed42_nohead.glb", "model/gltf-binary", "file"),
    ("hair_seed42.glb", "model/gltf-binary", "file"),
    ("cards_seed42.json", "application/json", "file"),
    ("chains_seed42.json", "application/json", "file"),
    ("info.json", "application/json", "file"),
    ("prep.png", "image/png", "image"),
    ("model_input.png", "image/png", "image"),
    ("hair_seed42_chains.glb", "model/gltf-binary", "file"),
    ("hair_seed42_nohead_chains.glb", "model/gltf-binary", "file"),
]
NAMES = [n for n, _m, _k in JOB_RESULTS]
BLOBS = [f"blob-{i}-{n}".encode() for i, n in enumerate(NAMES)]


def part1():
    print("[1] catalog + schema")
    if "hair_mesh" not in occ.occasion_ids():
        check("hair_mesh in catalog", False, True)
        return
    o = occ.get_occasion("hair_mesh")
    check("hair_mesh values",
          (o["category"], o["media"], o["character_scoped"], o["char_spec_field"],
           o["char_spec_fallback"], o.get("requires_chain"), o.get("hint")),
          ("img2hair", "mesh", True, "hair_mesh_workflow", "", False,
           "Hair cards from one image of the character (e.g. HairDeck)."))
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
    check("img2hair in category choices",
          "img2hair" in (fields.get("category") or {}).get("choices", []), True)
    notes = [f for f in fields.values() if isinstance(f, dict) and f.get("type") == "note"
             and (f.get("visible_when") or {}).get("category") == "img2hair"]
    check("img2hair note present", len(notes), 1)
    check("img2hair note names HairDeck",
          bool(notes) and "HairDeck" in str(notes[0].get("text")), True)


def part2():
    print("[2] pool separation (empty chains)")
    pool = BackendPool([Fake("Trellis", category="img2mesh"),
                        Fake("HairDeck", category="img2hair")])
    RULES.clear()
    for oid in ("mesh_humanoid", "mesh_creature", "mesh_object", "mesh_building",
                "mesh_garment"):
        r = routing.resolve_image_route(oid, pool=pool)
        check(f"{oid} never HairDeck", r.backend.name if r.backend else None, "Trellis")
    if "hair_mesh" in occ.occasion_ids():
        r = routing.resolve_image_route("hair_mesh", pool=pool)
        check("hair_mesh -> HairDeck", r.backend.name if r.backend else None, "HairDeck")
    else:
        check("hair_mesh resolvable", False, True)
    from app.core import config
    check("img2hair entry seeds no mesh occasion",
          config._mesh_routing_occasions("*", [{"name": "HairDeck", "api_type": "openai_mesh",
                                                "category": "img2hair"}]), [])


def part3():
    print("[3] per-character hair_mesh_workflow is position 0")
    if "hair_mesh" not in occ.occasion_ids():
        check("hair_mesh in catalog", False, True)
        return
    profiles = {"Kira": {"outfit_imagegen": {"hair_mesh_workflow": "Hair*"}}}
    RULES.clear()
    RULES["hair_mesh"] = ["HairDeck"]
    with patch("app.models.character.get_character_profile",
               side_effect=lambda name: profiles.get(name, {})):
        check("chain with character", routing.chain_for("hair_mesh", "Kira"),
              [("Hair*", "character", 0), ("HairDeck", "rule", 1)])
        check("chain without character", routing.chain_for("hair_mesh", ""),
              [("HairDeck", "rule", 1)])
        check("mesh_humanoid ignores the hair field",
              routing.chain_for("mesh_humanoid", "Kira"), [])
    RULES.clear()


def _hair_backend():
    from app.imagegen.backends.openai_mesh import OpenAIMeshBackend
    os.environ["SMOKE_HAIR_MESH_EXTRA_PARAMS"] = json.dumps({"input_steps": 30, "input_bogus": 1})
    b = OpenAIMeshBackend("HairDeck", "http://gateway.invalid", 0, "SMOKE_HAIR_MESH_",
                          model="HairDeck")
    b.category = "img2hair"
    b.instance_enabled = True
    b._available = True
    b._image_slots = ["input_image"]
    b._alias_param_names = {"input_name", "seed", "input_variations", "input_steps",
                            "input_cfg", "input_export_vrm"}
    return b


def part4():
    print("[4] generate_hair")
    from app.imagegen.service import ImageService
    if not hasattr(ImageService, "generate_hair"):
        check("ImageService.generate_hair exists", False, True)
        return
    backend = _hair_backend()
    service = ImageService.__new__(ImageService)
    service._pool = BackendPool([backend])
    work = Path(_scratch("hair-route-work-"))
    image = work / "profile.png"
    image_bytes = b"\x89PNG-profile-bytes"
    image.write_bytes(image_bytes)
    payloads = []

    def submit(_backend, _url, payload, _label, **kwargs):
        payloads.append(payload)
        return "job-hair-1"

    def collect(job_id, **kwargs):
        backend._tls.result_files = [{"name": n, "mime": m, "kind": k} for n, m, k in JOB_RESULTS]
        return list(BLOBS)

    def plain_generate(prompt, negative, params, **kwargs):
        return backend._generate(prompt, negative, params)

    RULES.clear()
    with (patch("app.imagegen.backends.openai_mesh.submit_job", side_effect=submit),
          patch.object(backend, "_collect", side_effect=collect),
          patch.object(backend, "generate", side_effect=plain_generate),
          patch.object(ImageService, "run_on_backend_channel",
                       staticmethod(lambda b, fn, **kw: fn()))):
        out = work / "out"
        result = service.generate_hair(str(image), str(out), character_name="Kira",
                                       params={"seed": 42})
        check("one submit", len(payloads), 1)
        p = payloads[0] if payloads else {}
        check("a. images", p.get("images"),
              {"input_image": base64.b64encode(image_bytes).decode()})
        params = dict(p.get("params") or {})
        name = params.pop("input_name", "")
        check("a. input_name prefix", name.startswith("Kira_hair-r") and len(name) == len("Kira_hair-r") + 6, True)
        check("a. params", params, {"seed": 42, "input_steps": 30})
        check("b. every file written",
              [(out / n).read_bytes() if (out / n).is_file() else None for n in NAMES], BLOBS)
        check("c. names in gateway order", [f["name"] for f in result["files"]], NAMES)
        check("c. mimes", [f["mime"] for f in result["files"]], [m for _n, m, _k in JOB_RESULTS])
        check("c. paths", [f["path"] for f in result["files"]], [str(out / n) for n in NAMES])
        check("c. backend + job", (result["backend"], result["job_id"]), ("HairDeck", "job-hair-1"))
        check("c. route occasion", (result.get("route") or {}).get("routing", {}).get("occasion"),
              "hair_mesh")

        # d. hub resume: a collected job is stored, nothing is submitted.
        attached = {"files": [{"name": n, "mime": m, "kind": k} for n, m, k in JOB_RESULTS],
                    "blobs": list(BLOBS), "backend": "HairDeck", "job_id": "old-job",
                    "route": {"routing": {"occasion": "hair_mesh", "position": 1, "spec": "HairDeck"}}}
        out2 = work / "resumed"
        with patch.object(ImageService, "_hub_attached", staticmethod(lambda st: attached)):
            resumed = service.generate_hair(str(work / "gone.png"), str(out2),
                                            character_name="Kira", params={"seed": 42},
                                            hub_stage=SimpleNamespace())
        check("d. no new submit", len(payloads), 1)
        check("d. files written", [(out2 / n).read_bytes() if (out2 / n).is_file() else None
                                   for n in NAMES], BLOBS)
        check("d. job + route", (resumed["job_id"], resumed["route"]),
              ("old-job", attached["route"]))
        check("d. names in order", [f["name"] for f in resumed["files"]], NAMES)

        # e. a hostile gateway name never leaves output_dir.
        bad = dict(attached, files=[{"name": "../evil.glb", "mime": "model/gltf-binary"}],
                   blobs=[b"evil"])
        out3 = work / "hostile" / "inner"
        err = ""
        with patch.object(ImageService, "_hub_attached", staticmethod(lambda st: bad)):
            try:
                service.generate_hair(str(image), str(out3), hub_stage=SimpleNamespace())
            except ValueError as e:
                err = type(e).__name__
        check("e. hostile name refused", err, "ValueError")
        check("e. nothing outside", (work / "hostile" / "evil.glb").exists(), False)

        # f. missing input image.
        err = ""
        try:
            service.generate_hair(str(work / "missing.png"), str(work / "o4"), character_name="Kira")
        except FileNotFoundError as e:
            err = type(e).__name__
        check("f. missing image", err, "FileNotFoundError")
        check("f. still one submit", len(payloads), 1)


def main():
    part1()
    part2()
    part3()
    part4()
    print()
    if FAILS:
        print(f"FAIL: {len(FAILS)} check(s): {', '.join(FAILS)}")
        sys.exit(1)
    print("PASS: hair_mesh occasion, img2hair pool separation, per-character match, generate_hair")


if __name__ == "__main__":
    main()
