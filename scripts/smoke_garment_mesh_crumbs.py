#!/usr/bin/env python3
"""The garment mesh gate leaves crumbs out and a stored raw is judged again
(app/core/garment_mesh.py, GATE_VERSION 2, 2026-11-12).

Usage:
    ./.venv/bin/python scripts/smoke_garment_mesh_crumbs.py

Runs against a THROWAWAY storage directory with a copy of the repo's ``human``
package — no real world, no hub, no server, no Blender (``runner.run`` is
stubbed as in ``smoke_garment_mesh.py``: "measure" counts the triangles, "lod"
copies the input, so the prepared GLB is the raw's bytes).

Live case: Kai's "Black Lederjacket" — the prepared mesh's largest component
carried 0.9619 of the area (65 components; 57 crumbs below 0.002 with 0.55 %,
7 seam strips beside the body), refused by the old gate 0.98 although it was
right. The fit's weld step drops components below 0.002 of the area anyway
(``garment_fit.drop_small``), so the gate now measures without them and
refuses only below 0.90.

Fixtures (disjoint axis-aligned squares in z = 0, area = side^2; total 1.0):
    JACKET: main 0.96 + strip 0.03 + 10 crumbs of 0.001.
        crumbs: 10 x 0.001 = 0.01 < 0.002 each -> dropped, 10 components;
        kept area 0.96 + 0.03 = 0.99, 2 components;
        largest share without crumbs 0.96 / 0.99 = 0.969697 >= 0.90 -> accepted;
        largest share of the whole 0.96 (the OLD gate number: 0.96 < 0.98 -> refused).
    SPLIT: main 0.85 + half-sleeve 0.14 + 10 crumbs of 0.001.
        kept 0.99; share 0.85 / 0.99 = 0.858586 < 0.90 -> refused.

[1] component_numbers(JACKET): largest_component_share 0.969697,
    largest_component_share_all 0.96, dropped_share 0.01, dropped_components 10,
    components_kept 2 (all +- 1e-5, float32 positions).
[2] generate with the service writing JACKET (fsig "0000000000a1"): 1 call,
    accepted; prepared bytes == JACKET (the crumbs stay in the file, the fit
    drops them); record: largest_component_share 0.969697,
    largest_component_share_all 0.96, dropped_share 0.01, dropped_components
    10, min_component_share 0.90, crumb_share 0.002, gate_version 2.
[3] SPLIT on both attempts (fsig "0000000000a2"): 2 calls, MeshGateRefused,
    record accepted False, share 0.858586, gate_version 2, reason names
    "crumbs left out".
[4] Stored raw re-judged (fsig "0000000000a3"): raw = JACKET written AFTER
    the cut-outs, the step record as the old gate left it (accepted False, no
    gate_version, attempts [1: share 0.9619, 2: share 0.9619], backend
    "UniForge3D-Multiview", routing {"occasion": "mesh_garment",
    "position": 1}). generate (no force): 0 service calls, runner
    ["measure", "lod"] on the raw; accepted; attempts = [one entry, attempt 2
    (the last gated attempt — the raw is the last attempt's), stored_raw True,
    ok True, share 0.969697, backend "UniForge3D-Multiview", routing as
    stored]; earlier_attempts = the 2 old entries; gate_version 2.
[4b] The same, but the record is the CURRENT gate's refusal (gate_version 2):
    not judged again -> the mesher runs (service writes JACKET: 1 call,
    accepted at attempt 1, no stored_raw).
[4c] The raw OLDER than the front cut-out (mtime - 10 s), record of the old
    gate: not judged again -> 1 service call.
[4d] force=True with an old-gate record: 1 service call, no stored_raw.
[5] The fit gates the same number with the same limit:
    garment_fit.CLOTHING_GATES["largest_component_share"] == ("min", 0.90, ...)
    and is garment_mesh.MIN_COMPONENT_SHARE; the jacket's 0.9697 passes it,
    0.8586 refuses.
[6] Fails on the old code: garment_mesh.py of commit c473a962 (pinned, the
    state before this change) judges JACKET by its whole-area share 0.96 and
    refuses it (reason non-empty); the new code accepts it.
"""
import importlib.util
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

#: The commit before the crumb rule (fails-on-old-code proof, never HEAD).
OLD_COMMIT = "c473a962"

FAILS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}" + ("" if ok else f" — expected {want!r}"))
    if not ok:
        FAILS.append(label)


def near(label, got, want, tol=1e-5):
    ok = got is not None and abs(float(got) - want) <= tol
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}" + ("" if ok else f" — expected {want} ± {tol}"))
    if not ok:
        FAILS.append(label)


def fixture(main, second):
    from smoke_garment_mesh import make_glb
    quads = [(0.0, math.sqrt(main)), (5.0, math.sqrt(second))]
    quads += [(10.0 + 2.0 * i, math.sqrt(0.001)) for i in range(10)]
    return make_glb(quads)


def main() -> int:
    JACKET, SPLIT = fixture(0.96, 0.03), fixture(0.85, 0.14)
    with tempfile.TemporaryDirectory(prefix="garment-crumbs-") as tmp:
        root = Path(tmp)
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        paths.get_config_path().write_text(json.dumps({"packages": {"enabled": "human"}}))
        from app.core import config
        config.load(paths.get_config_path(), instance_path=root / "instance/config.json")
        from app.core import db
        db.init_schema()
        shutil.copytree(ROOT / "plugins" / "human", root / "plugins" / "human")
        from app.plugins.loader import discover_packages
        discover_packages(root / "plugins", force=True)

        from app.blender import runner
        from app.core import base_body, garment_assembly, garment_fit
        from app.core import garment_mesh as gm
        from app.core import garment_store as gs
        from app.imagegen import service as service_mod
        from app.models import inventory
        from app.models.character import save_character_profile
        from smoke_garment_mesh import Recorder
        garment_assembly.schedule = lambda *a, **k: False

        human = {"template": "human-roleplay", "gender": "male", "age": 30, "height": 180,
                 "character_appearance": "athletic", "body_slots": {"skin": {"tone": "olive"}}}
        check("create Demo", save_character_profile("Demo", human, create_new=True), True)
        check("pipeline Demo", base_body.set_pipeline("Demo", True), True)
        hid = inventory.add_item(name="Jacket", category="outfit_piece", prompt_fragment="a black jacket",
                                 outfit_piece={"slots": ["top"], "covers": ["torso"],
                                               "outfit_types": ["casual"], "mesh_mode": "own_mesh"})["id"]
        check("inventory Jacket", inventory.add_to_inventory("Demo", hid), True)

        def cutouts(fsig):
            out = {}
            for view in ("front", "back"):
                p = gs.garment_path("Demo", hid, fsig, "image", step="cutout", view=view)
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(b"\x89PNG-" + view.encode() + b"-" + fsig.encode())
                out[view] = p
            return out

        rec = Recorder()
        service_mod.get_image_service = lambda: rec
        runner_calls = []

        def fake_run(script, *, inputs=None, params=None, out_dir=None, timeout_s=0):
            src = Path(inputs["model"])
            runner_calls.append((script, src))
            data = src.read_bytes()
            gltf = json.loads(data[20:20 + int.from_bytes(data[12:16], "little")])
            tris = sum(gltf["accessors"][p["indices"]]["count"] // 3
                       for m in gltf["meshes"] for p in m["primitives"])
            if script == "measure":
                return {"ok": True, "error": "", "data": {"tris": tris}, "outputs": {}}
            dst = Path(out_dir) / f"model_lod{tris}.glb"
            shutil.copyfile(src, dst)
            return {"ok": True, "error": "",
                    "data": {"stages": [{"ratio": params["ratios"][0], "tris_before": tris, "tris": tris,
                                         "file": dst.name}], "source_tris": tris},
                    "outputs": {f"lod{tris}": str(dst)}}

        runner.run = fake_run
        runner.version = lambda executable="": "5.2.2"

        print("[1] component_numbers")
        probe = root / "jacket.glb"
        probe.write_bytes(JACKET)
        n = gm.component_numbers(probe)
        near("share without crumbs 0.96/0.99", n["largest_component_share"], 0.96 / 0.99)
        near("share of the whole", n["largest_component_share_all"], 0.96)
        near("dropped share", n["dropped_share"], 0.01)
        check("dropped components", n["dropped_components"], 10)
        check("kept components", n["components_kept"], 2)
        near("largest_component_share = the gate number", gm.largest_component_share(probe), 0.96 / 0.99)

        print("[2] generate accepts the jacket")
        A1 = "0000000000a1"
        cutouts(A1)
        rec.script = [JACKET]
        prepared = gm.generate("Demo", hid, A1)
        check("one call", len(rec.calls), 1)
        check("prepared = raw bytes (crumbs stay in the file)", prepared.read_bytes() == JACKET, True)
        r = gs.read_record(prepared.with_suffix(".json"))
        check("accepted", r.get("accepted"), True)
        near("record share", r.get("largest_component_share"), 0.96 / 0.99)
        near("record share all", r.get("largest_component_share_all"), 0.96)
        near("record dropped share", r.get("dropped_share"), 0.01)
        check("record dropped components", r.get("dropped_components"), 10)
        check("record limits", (r.get("min_component_share"), r.get("crumb_share"), r.get("gate_version")),
              (0.90, 0.002, 2))

        print("[3] a split mesh is refused")
        A2 = "0000000000a2"
        cutouts(A2)
        rec.calls.clear()
        rec.script = [SPLIT]
        refused = None
        try:
            gm.generate("Demo", hid, A2)
        except gm.MeshGateRefused as e:
            refused = e
        check("refused", refused is not None, True)
        check("two calls", len(rec.calls), 2)
        r = gs.read_record(gs.garment_path("Demo", hid, A2, "prepared").with_suffix(".json"))
        check("record refused", (r.get("accepted"), r.get("gate_version")), (False, 2))
        near("record share 0.85/0.99", r.get("largest_component_share"), 0.85 / 0.99)
        check("reason names the crumbs", "crumbs left out" in " ".join((r.get("attempts") or [{}])[0]
                                                                      .get("reasons") or []), True)

        old_attempts = [{"attempt": a, "ok": False, "reasons": ["largest component share 0.9619 < 0.98"],
                         "backend": "UniForge3D-Multiview", "routing": {"occasion": "mesh_garment", "position": 1},
                         "tris_raw": 94469, "tris_prepared": 59194, "ratio": 0.635, "largest_component_share": 0.9619}
                        for a in (1, 2)]
        old_record = {"accepted": False, "kind": "clothing", "item_id": hid, "min_component_share": 0.98,
                      "largest_component_share": 0.9619, "backend": "UniForge3D-Multiview",
                      "routing": {"occasion": "mesh_garment", "position": 1}, "attempts": old_attempts}

        def stored(fsig, record, *, raw_age=0.0):
            cut = cutouts(fsig)
            raw = gs.garment_path("Demo", hid, fsig, "raw")
            raw.parent.mkdir(parents=True, exist_ok=True)
            raw.write_bytes(JACKET)
            newest = max(p.stat().st_mtime for p in cut.values())
            os.utime(raw, (newest + 1.0 - raw_age, newest + 1.0 - raw_age))
            rp = gs.garment_path("Demo", hid, fsig, "prepared").with_suffix(".json")
            rp.parent.mkdir(parents=True, exist_ok=True)
            gs.write_record(rp, record)
            rec.calls.clear()
            runner_calls.clear()
            rec.script = [JACKET]
            return raw

        print("[4] a stored raw refused by the old gate is judged again")
        A3 = "0000000000a3"
        raw = stored(A3, old_record)
        p3 = gm.generate("Demo", hid, A3)
        check("no mesher call", len(rec.calls), 0)
        check("runner on the stored raw", [(s, src == raw) for s, src in runner_calls],
              [("measure", True), ("lod", True)])
        r = gs.read_record(p3.with_suffix(".json"))
        check("accepted", r.get("accepted"), True)
        att = r.get("attempts") or []
        check("one attempt", len(att), 1)
        if att:
            check("entry", (att[0].get("attempt"), att[0].get("stored_raw"), att[0].get("ok"),
                            att[0].get("backend"), att[0].get("routing")),
                  (2, True, True, "UniForge3D-Multiview", {"occasion": "mesh_garment", "position": 1}))
            near("entry share", att[0].get("largest_component_share"), 0.96 / 0.99)
        check("earlier attempts kept", [a.get("attempt") for a in r.get("earlier_attempts") or []], [1, 2])
        check("gate_version", r.get("gate_version"), 2)
        check("prepared = stored raw", p3.read_bytes() == JACKET, True)

        print("[4b] the current gate's refusal is not judged again")
        A4 = "0000000000a4"
        stored(A4, {**old_record, "gate_version": 2})
        p4 = gm.generate("Demo", hid, A4)
        r = gs.read_record(p4.with_suffix(".json"))
        check("mesher runs", len(rec.calls), 1)
        check("fresh attempt", [(a.get("attempt"), a.get("stored_raw")) for a in r.get("attempts") or []],
              [(1, None)])

        print("[4c] a raw older than the cut-outs is not judged again")
        A5 = "0000000000a5"
        stored(A5, old_record, raw_age=11.0)
        gm.generate("Demo", hid, A5)
        check("mesher runs", len(rec.calls), 1)

        print("[4d] force asks the mesher")
        A6 = "0000000000a6"
        stored(A6, old_record)
        p6 = gm.generate("Demo", hid, A6, force=True)
        check("mesher runs", len(rec.calls), 1)
        check("no stored_raw", [a.get("stored_raw") for a in gs.read_record(p6.with_suffix(".json"))
                                .get("attempts") or []], [None])

        print("[5] the fit gates the same number with the same limit")
        G = garment_fit.CLOTHING_GATES["largest_component_share"]
        check("fit limit", G[:2], ("min", 0.90))
        check("fit limit is the mesh limit", G[1] == gm.MIN_COMPONENT_SHARE, True)
        base = {"max_push_m": 0.05, "deep_push_share": 0.05, "rigged_inside_share": 0.0,
                "rigged_push_max_m": 0.0, "rigged_deep_push_share": 0.0}
        check("0.9697 passes the fit gate",
              garment_fit.gate({**base, "largest_component_share": 0.9697}, garment_fit.CLOTHING_GATES)[0], True)
        check("0.8586 refuses at the fit gate",
              garment_fit.gate({**base, "largest_component_share": 0.8586}, garment_fit.CLOTHING_GATES)[0], False)

        print(f"[6] fails on the old code ({OLD_COMMIT})")
        src = subprocess.run(["git", "-C", str(ROOT), "show", f"{OLD_COMMIT}:app/core/garment_mesh.py"],
                             capture_output=True, text=True)
        if src.returncode != 0:
            check("old garment_mesh.py readable", src.stderr.strip(), "")
        else:
            old_file = root / "old_garment_mesh.py"
            old_file.write_text(src.stdout)
            spec = importlib.util.spec_from_file_location("old_garment_mesh", old_file)
            old = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(old)
            near("old gate number = whole-area share", old.largest_component_share(probe), 0.96)
            check("old code refuses the jacket", bool(old._gate(old.largest_component_share(probe))), True)
            check("new code accepts it", gm._gate(gm.largest_component_share(probe)), [])

    if FAILS:
        print("FAILED: " + ", ".join(FAILS))
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
