#!/usr/bin/env python3
"""The boot sweep that refits garment fits of an older fit algorithm
(app/core/garment_refit.py, garment_fit.FIT_VERSION).

Usage:
    ./.venv/bin/python scripts/smoke_garment_refit_sweep.py

Runs against a THROWAWAY storage + instance directory — no real world, no
hub, no GPU, no Blender, no server process. The FIT is stubbed
(``garments._fit``: a recorder that hands a fixed result to the REAL
``garments._publish_fit``, which writes the fit GLB + record and stamps
``fit_version``); ``glb_mesh.graft`` / ``static_arrays``, ``refine.
decimate_to`` and ``garment_assembly.schedule`` are recorders. Every hub
path is a recorder that counts: ``service.get_image_service``,
``garment_images.run_edit_step``, ``garment_mesh.generate``,
``garments._run_hairdeck``. ``base_body.current_base`` = (B1, SHA),
``garment_store.garment_fsig`` / ``garment_method`` / ``garment_hsig`` come
from fixed tables.

Fixture, character Demo (fsig = 12 hex; FV = FIT_VERSION, hair 2 clothing 6):
  item   kind      stored fsig  current fsig  base sha  fit_version  method
  hA     hair      aaaaaaaaaaaa same          SHA       (none)       edit_chain
  cB     clothing  bbbbbbbbbbbb same          SHA       1            edit_chain
  cC     clothing  cccccccccccc same          SHA       6 (= FV)     edit_chain
  cD     clothing  dddddddddddd eeeeeeeeeeee  SHA       1            edit_chain
  hE     hair      ffffffffffff same          OTHER     (none)       edit_chain
Each edit-chain item has prepared/{item}_{fsig}.glb (bytes b"P"+item) and its
record's inputs.prepared_sha256 = sha256 of those bytes.

[1] outdated_fits(Demo) = [(cB, clothing, bbb.., edit_chain), (hA, hair,
    aaa.., edit_chain)] (sorted by item id: "cB" < "hA") — cC is current, cD is not the current fsig (the
    next chain run's), hE sits on another base model (after_base_model's).
    _fit_state hA / cB = "stale", cC = "accepted".
[2] Run lock held by the smoke: refit_character -> None; sweep([Demo],
    retries 0, pause 0) -> {}; no _fit call, every record unchanged.
[3] Released: sweep([Demo], pause 0) -> {Demo: [cB, hA]}; _fit called for
    cB then hA (the order of [1]), each once; 0 hub calls; 2 assembly
    schedules (one per published fit); exactly 2 log lines "Garment refit
    Demo/<item>" ending "ok", naming "fit_version 1 -> 6" (cB) and "None -> 2" (hA);
    records of hA / cB: accepted, fit_version 2 / 6, base sha SHA; _fit_state
    "accepted"; cC: GLB bytes and record byte-identical, mtime unchanged; cD
    and hE records unchanged. A second sweep -> {} (nothing left).
[4] HairDeck hair hH (method hairdeck, fsig 999999999999, hsig
    888888888888, fit_version 1, served seed 5, stored seeds [3, 5]):
    (a) seed 5 passes -> only seed 5 fitted (attempt 2 = its position), the
        published seed is 5;
    (b) seed 5 refused, seed 3 passes -> fitted 5 then 3, published 3;
    (c) neither passes -> refused: nothing published, a "fit" failure
        recorded for (hH, fsig) on SHA (chain_failure), status failed step
        "fit", the log line ends "refused — ...".
    _run_hairdeck is never called (0) — the sweep never asks HairDeck for
    one more seed.
[5] Too-small refusals from before the scale retry (fsig 777777777777):
    failure records cR / cW (deep_push_share only, no ``scale_retry`` stamp,
    on SHA) are retried; cS (stamped 1), cT (component gate too), cU (on
    OTHER) and hV (hair) are not -> refused_fits = [cR, cW]. The fit refuses
    cR again and accepts cW: refit_character -> [cW], fits [cR, cW], cR's new
    failure carries scale_retry = SCALE_RETRY_VERSION, cW's failure is gone,
    2 log lines "too-small refusal retried widened"; then refused_fits = []
    and a second refit fits nothing (once).
[5b] Outfit body ob0000000a (body sha unchanged, served fsig 777..): body
    failures cR (eligible), cS (stamped), cT (other gate) ->
    refused_body_fits = [(cR, clothing, 777.., ob0000000a)]; fit_on_body
    refuses -> the body failure is stamped, the log names the outfit body,
    refused_body_fits = [] afterwards. 0 hub calls throughout.
"""
import hashlib
import json
import logging
import os
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS = []


def check(label, got, want):
    ok = got == want
    print(f"  {'OK  ' if ok else 'FAIL'} {label}: {got!r}" + ("" if ok else f" (want {want!r})"))
    if not ok:
        FAILS.append(label)


class _Lines(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="garment-refit-") as tmp:
        root = Path(tmp)
        os.environ["STORAGE_DIR"] = str(root / "world")
        os.environ["INSTANCE_DIR"] = str(root / "instance")
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "instance")
        from app.core import config
        config.load(paths.get_config_path(), instance_path=root / "instance/config.json")
        from app.core import db
        db.init_schema()

        from app.blender import refine
        from app.core import (base_body, garment_assembly, garment_fit, garment_images, garment_mesh,
                              garment_refit, garments, glb_mesh)
        from app.core import garment_store as gs
        from app.imagegen import service
        from app.models import character as charmod

        SHA, OTHER = "s" * 64, "o" * 64
        FV = garment_fit.FIT_VERSION
        check("FIT_VERSION", FV, {"hair": 2, "clothing": 6})
        charmod.get_character_dir("Demo", create=True)
        garments_root = gs._root("Demo")
        garments_root.mkdir(parents=True, exist_ok=True)

        # --- stubs -----------------------------------------------------------------
        HUB = []

        def hub(name):
            def stub(*a, **k):
                HUB.append(name)
                raise RuntimeError(f"hub call {name} in the refit sweep")
            return stub

        service.get_image_service = hub("image_service")
        garment_images.run_edit_step = hub("run_edit_step")
        garment_mesh.generate = hub("generate_mesh")
        garments._run_hairdeck = hub("run_hairdeck")
        base_body.current_base = lambda name, profile=None: ("B1", SHA)
        base_body._snapshot_base_model = lambda name, bsig: {"rigged": b"RIGGED"}
        charmod.get_character_profile = lambda name: {}
        FSIG = {"hA": "a" * 12, "cB": "b" * 12, "cC": "c" * 12, "cD": "e" * 12, "hE": "f" * 12,
                "hH": "9" * 12}
        METHOD = {"hH": gs.HAIRDECK}
        gs.garment_fsig = lambda name, item_id, profile=None: FSIG[item_id]
        gs.garment_method = lambda name, item_id, profile=None: METHOD.get(item_id, gs.EDIT_CHAIN)
        gs.garment_hsig = lambda name, item_id, profile=None: "8" * 12
        SCHEDULED, DECIMATED = [], []
        garment_assembly.schedule = lambda name, signature=None: SCHEDULED.append(name) or True
        glb_mesh.graft = lambda rigged, garment, name="", extras=None: b"FIT:" + name.encode()
        glb_mesh.static_arrays = lambda blob: (None, [[0, 1, 2]] * 4)
        refine.lod_ratio = lambda kind: 0.5

        def decimate(src, target, out):
            DECIMATED.append(Path(out).name)
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            Path(out).write_bytes(Path(src).read_bytes())
            return {"ok": True, "tris": target, "ratio": 0.5}
        refine.decimate_to = decimate

        FITS = []

        def fit_stub(name, item_id, kind, fsig, bsig, profile):
            FITS.append(item_id)
            old = gs.read_record(gs.garment_path(name, item_id, fsig, "fit").with_suffix(".json"))
            result = types.SimpleNamespace(garment=b"G", metrics={"tris": 4})
            record = {"accepted": True, "kind": kind, "item_id": item_id, "fsig": fsig,
                      "base_signature": bsig, "base_model_sha256": SHA, "inputs": old.get("inputs") or {}}
            return garments._publish_fit(name, item_id, kind, fsig, bsig, b"RIGGED", result, record)
        garments._fit = fit_stub

        # --- fixture ---------------------------------------------------------------
        def put(item_id, kind, fsig, sha, version, method=None, extra=None):
            prepared = gs.garment_path("Demo", item_id, fsig, "prepared")
            prepared.parent.mkdir(parents=True, exist_ok=True)
            prepared.write_bytes(b"P" + item_id.encode())
            fit = gs.garment_path("Demo", item_id, fsig, "fit")
            fit.write_bytes(b"OLD:" + item_id.encode())
            record = {"accepted": True, "kind": kind, "item_id": item_id, "fsig": fsig,
                      "base_signature": "B1", "base_model_sha256": sha,
                      "inputs": {"prepared_sha256": hashlib.sha256(b"P" + item_id.encode()).hexdigest()}}
            if version is not None:
                record["fit_version"] = version
            if method:
                record["method"] = method
            record.update(extra or {})
            gs.write_record(fit.with_suffix(".json"), record)

        put("hA", "hair", "a" * 12, SHA, None)
        put("cB", "clothing", "b" * 12, SHA, 1)
        put("cC", "clothing", "c" * 12, SHA, 6)
        put("cD", "clothing", "d" * 12, SHA, 1)
        put("hE", "hair", "f" * 12, OTHER, None)

        def rec(item_id, fsig):
            return gs.garment_path("Demo", item_id, fsig, "fit").with_suffix(".json").read_text()

        before = {k: rec(k, f) for k, f in
                  (("hA", "a" * 12), ("cB", "b" * 12), ("cC", "c" * 12), ("cD", "d" * 12), ("hE", "f" * 12))}
        c_fit = gs.garment_path("Demo", "cC", "c" * 12, "fit")
        c_bytes, c_mtime = c_fit.read_bytes(), c_fit.stat().st_mtime_ns

        lines = _Lines()
        logging.getLogger(garment_refit.__name__).addHandler(lines)
        logging.getLogger(garment_refit.__name__).setLevel(logging.INFO)

        # --- [1] selection ---------------------------------------------------------
        print("[1] outdated fits")
        check("outdated", garment_refit.outdated_fits("Demo"),
              [("cB", "clothing", "b" * 12, "edit_chain"), ("hA", "hair", "a" * 12, "edit_chain")])
        check("states", [garments._fit_state("Demo", i, f, SHA) for i, f in
                         (("hA", "a" * 12), ("cB", "b" * 12), ("cC", "c" * 12))],
              ["stale", "stale", "accepted"])

        # --- [2] busy ----------------------------------------------------------------
        print("[2] a running chain holds the sweep back")
        lock = gs.char_lock("Demo")
        lock.acquire()
        try:
            check("refit_character busy", garment_refit.refit_character("Demo"), None)
            check("sweep busy", garment_refit.sweep(["Demo"], pause=0, retries=0), {})
        finally:
            lock.release()
        check("no fit while busy", FITS, [])
        check("records unchanged", all(rec(k, json.loads(v)["fsig"]) == v for k, v in before.items()), True)

        # --- [3] the sweep -----------------------------------------------------------
        print("[3] sweep refits the two outdated fits, CPU only")
        check("sweep", garment_refit.sweep(["Demo"], pause=0), {"Demo": ["cB", "hA"]})
        check("fit calls", FITS, ["cB", "hA"])
        check("hub calls", HUB, [])
        check("assembly schedules", SCHEDULED, ["Demo", "Demo"])
        refits = [line for line in lines.lines if line.startswith("Garment refit Demo/")]
        check("log lines", len(refits), 2)
        check("log cB", "fit_version 1 -> 6: ok" in refits[0] and "Demo/cB" in refits[0], True)
        check("log hA", "fit_version None -> 2: ok" in refits[1] and "Demo/hA" in refits[1], True)
        for item_id, fsig, version in (("hA", "a" * 12, 2), ("cB", "b" * 12, 6)):
            r = json.loads(rec(item_id, fsig))
            check(f"{item_id} record", (r.get("accepted"), r.get("fit_version"), r.get("base_model_sha256")),
                  (True, version, SHA))
            check(f"{item_id} state", garments._fit_state("Demo", item_id, fsig, SHA), "accepted")
        check("cC untouched", (c_fit.read_bytes() == c_bytes, c_fit.stat().st_mtime_ns == c_mtime,
                               rec("cC", "c" * 12) == before["cC"]), (True, True, True))
        check("cD / hE untouched", (rec("cD", "d" * 12) == before["cD"], rec("hE", "f" * 12) == before["hE"]),
              (True, True))
        check("second sweep", garment_refit.sweep(["Demo"], pause=0), {})
        check("still no hub call", HUB, [])

        # --- [4] HairDeck ------------------------------------------------------------
        print("[4] HairDeck hair refits from its stored seeds, never asks HairDeck")
        garments._stored_seeds = lambda name, item_id, hsig: [3, 5]
        garments._hairdeck_files = lambda name, item_id, hsig: (Path("hair.glb"), Path("proxy.glb"))
        VERDICT, FITTED, PUBLISHED = {}, [], []

        def fit_seed(name, item_id, hsig, seed, attempt, rigged, profile):
            FITTED.append((seed, attempt))
            ok = VERDICT[seed]
            return {"seed": seed, "result": types.SimpleNamespace(metrics={"max_push_m": 0.01 * seed}),
                    "gates": {"attempt": attempt, "seed": seed, "ok": ok, "reasons": [] if ok else ["too far"]}}
        garments._fit_seed = fit_seed
        garments._publish_hairdeck = (lambda name, item_id, kind, fsig, bsig, hsig, profile, snapshot, fit, fits:
                                      PUBLISHED.append(fit["seed"]))
        h_fsig = "9" * 12

        def hairdeck(verdict):
            put("hH", "hair", h_fsig, SHA, 1, method=gs.HAIRDECK, extra={"inputs": {"seed": 5}})
            gs.clear_failure("Demo", "hH", h_fsig)
            VERDICT.clear(), VERDICT.update(verdict)
            FITTED.clear(), PUBLISHED.clear()
            return garment_refit.refit_character("Demo")

        check("(a) refit", hairdeck({3: True, 5: True}), ["hH"])
        check("(a) fitted / published", (FITTED, PUBLISHED), ([(5, 2)], [5]))
        check("(b) refit", hairdeck({3: True, 5: False}), ["hH"])
        check("(b) fitted / published", (FITTED, PUBLISHED), ([(5, 2), (3, 1)], [3]))
        lines.lines.clear()
        check("(c) refit", hairdeck({3: False, 5: False}), [])
        check("(c) fitted / published", (FITTED, PUBLISHED), ([(5, 2), (3, 1)], []))
        failure = gs.chain_failure("Demo", "hH", h_fsig, base_model_sha=SHA) or {}
        check("(c) failure recorded", failure.get("step"), "fit")
        check("(c) status", (gs.status("Demo", "hH")["failed"] or {}).get("step"), "fit")
        check("(c) log", any(line.startswith("Garment refit Demo/hH") and ": refused — " in line
                             for line in lines.lines), True)
        check("(c) old record kept", json.loads(rec("hH", h_fsig)).get("fit_version"), 1)
        check("no HairDeck / hub call", HUB, [])

        # --- [5] too-small refusals before the scale retry ------------------------------
        print("[5] a too-small clothing refusal from before the scale retry is fitted once more")
        small = "fit refused — deep_push_share 0.1329 > 0.12 (share of vertices pushed out more than 3 cm)"
        other = ("fit refused — largest_component_share 0.9 < 0.98 (area share of the largest component); "
                 "deep_push_share 0.13 > 0.12 (share of vertices pushed out more than 3 cm)")
        KIND = {"cR": "clothing", "cS": "clothing", "cT": "clothing", "cU": "clothing", "cW": "clothing",
                "hV": "hair"}
        FSIG.update({item_id: "7" * 12 for item_id in KIND})
        garments._item_order = lambda name, item_id, profile=None: ({}, KIND[item_id], ())

        def failed(item_id, error, sha=SHA, stamp=None, body=""):
            record = {"item_id": item_id, "fsig": "7" * 12, "step": "fit", "error": error}
            if body:
                record.update(body_id=body, body_sha256="BODY", base_fit_sha256="x", fit_version=6)
            else:
                record["base_model_sha256"] = sha
            if stamp is not None:
                record["scale_retry"] = stamp
            gs.write_record(gs.garment_path("Demo", item_id, "7" * 12, "failed", body=body), record)

        failed("cR", small)                 # eligible
        failed("cW", small)                 # eligible
        failed("cS", small, stamp=1)        # refused WITH the scale retry already
        failed("cT", other)                 # another gate failed too
        failed("cU", small, sha=OTHER)      # on another base model
        failed("hV", small)                 # hair
        check("retry_refusal small / stamped / other",
              [garment_refit.retry_refusal(r) for r in ({"step": "fit", "error": small},
                                                        {"step": "fit", "error": small, "scale_retry": 1},
                                                        {"step": "fit", "error": other},
                                                        {"step": "mesh", "error": small})],
              [True, False, False, False])
        check("refused_fits", garment_refit.refused_fits("Demo"),
              [("cR", "clothing", "7" * 12, "edit_chain"), ("cW", "clothing", "7" * 12, "edit_chain")])

        def fit_small(name, item_id, kind, fsig, bsig, profile):
            if item_id == "cR":
                FITS.append(item_id)
                raise garments._Refused("fit", "fit refused — deep_push_share 0.125 > 0.12 (widened to 1.08)",
                                        {"ok": False, "metrics": {"scale_retry": 1.0, "scale_retry_max": 1.08}})
            return fit_stub(name, item_id, kind, fsig, bsig, profile)
        garments._fit = fit_small
        FITS.clear(), lines.lines.clear()
        check("refit", garment_refit.refit_character("Demo"), ["cW"])
        check("fit calls", FITS, ["cR", "cW"])
        check("cR failure stamped", (gs.chain_failure("Demo", "cR", "7" * 12, base_model_sha=SHA) or {}).get(
            "scale_retry"), garment_fit.SCALE_RETRY_VERSION)
        check("cW failure cleared", gs.chain_failure("Demo", "cW", "7" * 12, base_model_sha=SHA), None)
        check("log", sum(1 for line in lines.lines if "too-small refusal retried widened" in line), 2)
        check("once: nothing left", garment_refit.refused_fits("Demo"), [])
        FITS.clear()
        check("second refit", garment_refit.refit_character("Demo"), [])
        check("no second fit", FITS, [])

        print("[5b] ... and on an outfit body")
        BODY = "ob0000000a"
        failed("cR", small, body=BODY)
        failed("cS", small, stamp=1, body=BODY)
        failed("cT", other, body=BODY)
        garments.body_sha256 = lambda name, body_id: "BODY"
        cw_fit = gs.garment_path("Demo", "cW", "7" * 12, "fit")
        cr_fit = gs.garment_path("Demo", "cR", "7" * 12, "fit")
        cr_fit.write_bytes(b"BASE:cR")
        gs.accepted_fit = lambda name, item_id, base_model_sha="", profile=None: (
            (cr_fit if item_id == "cR" else cw_fit), {"kind": KIND[item_id]})
        check("refused_body_fits", garment_refit.refused_body_fits("Demo"), [("cR", "clothing", "7" * 12, BODY)])
        ON_BODY = []

        def on_body(name, item_id, body_id, base_fit, profile=None, schedule=True):
            ON_BODY.append((item_id, body_id))
            raise garments._Refused("fit", "fit on the outfit body refused — deep_push_share 0.13 > 0.12 (x)", None)
        garments.fit_on_body = on_body
        lines.lines.clear()
        check("refit", garment_refit.refit_character("Demo"), [])
        check("fit_on_body calls", ON_BODY, [("cR", BODY)])
        check("body failure stamped", gs.read_record(gs.garment_path("Demo", "cR", "7" * 12, "failed", body=BODY))
              .get("scale_retry"), garment_fit.SCALE_RETRY_VERSION)
        check("body log", any("on outfit body" in line and "too-small refusal retried widened: refused" in line
                              for line in lines.lines), True)
        check("once on the body", garment_refit.refused_body_fits("Demo"), [])
        check("no hub call", HUB, [])

    print("ALL OK" if not FAILS else f"{len(FAILS)} FAILED: {FAILS}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
