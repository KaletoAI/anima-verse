#!/usr/bin/env python3
"""Ruling A82: the footwear piece's Width / Length allowance (``footwear_fit.ALLOWANCE_STEPS``), Length Auto, the
viewer's live preview rule (``frontend/src/tabs/characters/footwearAllowanceModel.ts``) and A72b's carry-over for footwear.

Usage:
    ./.venv/bin/python scripts/smoke_footwear_allowance.py

Runs against a THROWAWAY storage + instance directory — no world, no hub, no Blender, no server, 0 outbound requests.
The fits are real (``footwear_fit.fit_pair`` / ``garment_footwear.fit_compute`` on the synthetic shoes of
``_footwear_fixtures``); ``garment_footwear._fit_attempt`` is wrapped in [4] to refuse chosen lengths. The TypeScript
module is bundled by esbuild and run by ``node`` ([5]).

Fixture: the closed clog ``fx.clog()`` (its insole arc 0.255 m at the fit), the box-foot body ``fx.foot_body_glb()``
(foot length F = 0.25 m), toe room A = ``ALLOW_M`` = 0.005 m.

Expected, derived by hand from the ruling:

[1] Steps (0, 2, 4, 6, 8, 10, 12, 15, 20); ``allowance_shares({"width": 10, "length": 4})`` = (0.10, 0.04); 3 / 25 /
    True / "4" -> ValueError. ``validate_allowance``: {"length": "auto"} ok; {"length": 3}, {"height": 2}, {} and
    {"width": True} -> ValueError.
[2] ``fit_pair`` on the clog:
    - allowance None and {width 0, length 0}: the same record and the same parts (0/0 = fit version 18, nothing due);
      no ``scale.allowance``;
    - Length +10 %: heel room = F x 0.10 = 0.025 m; the insole arc = F x 1.1 + A = 0.28 m (+0 %: F + A = 0.255 m);
      ``size`` = 0.28 / 0.255 = 1.098039; k(+10) / k(+0) = size; the toe room stays 5.0 mm; the width in metres
      k x width factor is unchanged (the factor divided by size): k0 x wf0 = k10 x wf10;
    - Width +10 %: k unchanged, width factor = 1.1 x wf0; ``scale.allowance`` = {width_pct 10, length_pct 0,
      heel_room_m 0, size 1}.
[3] ``garment_fsig`` (storage): Demo wears the footwear item "heels". Auto/Auto = the fingerprint F0 (no
    "allowance" input); ``set_allowance(length 4)`` stores {"heels": {"length": 4}} and changes it (F1 != F0);
    width 6 changes it again; both back to auto -> the profile key gone and the fingerprint F0 again. A stored 3
    reads as auto. A non-footwear item -> ValueError.
[4] Length Auto (``fit_compute``) with ``_fit_attempt`` refusing every length below 4 by "visible_poke ...":
    tried [0, 2, 4], accepted at length_pct 4.0, ``scale.allowance.auto`` = {width auto, length auto, tried_length
    [0, 2, 4]}. Length fixed at 2: no search — tried [2], refused. Refusal by "toe_conform_m ..." (no enclosure
    gate): no search, refused. Every length refused: all nine steps tried, the +0 refusal stands.
[5] The preview rule (TypeScript), frame F 0.25 / A 0.005:
    - shown 0/0 -> W 10 / L 10: r = 0.28 / 0.255 = 1.0980392, dx = 0.25 x (0 - 10) / 100 = -0.025, wz = 1.1;
      the point (0.1, 0.01, 0.02) of the cut frame -> (1.0980392 x 0.1 - 0.025, 0.010980392, 0.022)
      = (0.08480392, 0.010980392, 0.022);
    - shown 10/10 -> 0/0: r = 0.255 / 0.28 = 0.9107143, dx = +0.025, wz = 1 / 1.1 = 0.9090909;
    - ``bindMap`` with the cut frame = identity and the bone inverse = translate(-1, 0, 0) (J = translate(+1)):
      the bind point (1.1, 0.01, 0.02) -> J T J^-1 -> (1 + 0.08480392, 0.010980392, 0.022);
    - ``stepText`` with foot_len 0.2389 m: Length +4 % -> "+4 % = +9.6 mm" (238.9 x 0.04 = 9.556); ball width
      96.0 mm: Width +10 % -> "+10 % = +9.6 mm";
    - ``shoeSide``: "garment_footwear_heels_left_shaft" -> left, "garment_footwear_heels_right" -> right,
      "garment_footwear_heels_mid" -> null, "garment_footwear_boots_left" -> null.
[6] Carry-over for footwear (``fit_attempts``): a footwear gate row {value 0.0231437, limit 0.005} named by the reason
    "visible_poke 0.02314 > 0.005 (...)" -> {"visible_poke": ("max", 0.0231437)}; a row below its limit
    {value 0.4, limit 0.5} -> ("min", 0.4); a range limit [-3, 3] -> None. ``carries``: 0.0231437 -> 0.0281
    (+0.00496) True, -> 0.0282 (+0.00506) False. Store round trip, kind footwear: attempt A refused (no acceptance)
    -> False; accept; attempt B (same value, other bytes) with carry -> True, the fit path holds B; attempt C
    (value 0.03, +0.0069) -> False, the displaced fit back. A slot's attempt (carry False) never carries.
    Fails on the old code (commit cc032dbb8): its ``refused_values`` returns None for the footwear row (it read only
    ``gates["limits"]``), so no footwear acceptance could carry.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

FAILS = []
OLD = "cc032dbb8"


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


def near(label, got, want, tol):
    ok = got is not None and abs(float(got) - float(want)) <= tol
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r} (want {want} ± {tol})")
    if not ok:
        FAILS.append(label)


def raises(label, fn):
    try:
        fn()
    except ValueError:
        print(f"  OK   {label}: ValueError")
        return
    print(f"  FAIL {label}: no ValueError")
    FAILS.append(label)


JS = r"""
import { createRequire } from 'node:module';
import { join } from 'node:path';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
const [root] = process.argv.slice(2);
const require_ = createRequire(join(root, 'scripts', 'x.js'));
let esbuild = null;
for (const cand of ['esbuild', join(root, 'node_modules/esbuild'), join(root, 'frontend/node_modules/esbuild'),
                    join(root, 'client3d/node_modules/esbuild')]) {
  try { esbuild = require_(cand); break } catch { /* next */ }
}
if (!esbuild) { console.error('esbuild not found'); process.exit(2) }
const dir = mkdtempSync(join(tmpdir(), 'smoke-footwear-allowance-'));
const file = join(dir, 'm.mjs');
await esbuild.build({ entryPoints: [join(root, 'frontend/src/tabs/characters/footwearAllowanceModel.ts')], outfile: file,
  bundle: true, format: 'esm', platform: 'neutral', logLevel: 'silent', absWorkingDir: root });
const m = await import('file://' + file);
rmSync(dir, { recursive: true, force: true });
const I = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1];
const frame0 = { sides: {}, foot_len_m: 0.25, allow_m: 0.005, width_pct: 0, length_pct: 0 };
const frame10 = { ...frame0, width_pct: 10, length_pct: 10 };
const T = m.cutMap(frame0, 10, 10);
const p = [0.1, 0.01, 0.02]; m.applyInPlace(p, T);
const rows = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]];
const B = m.bindMap(rows, [1, 0, 0, -1, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1], T);
const q = [1.1, 0.01, 0.02]; m.applyInPlace(q, B);
const view = { foot_len_m: 0.2389, ball_width_mm: 96.0 };
console.log(JSON.stringify({
  T, point: p, back: m.cutMap(frame10, 0, 0), bind: q,
  shown: [m.isShown(frame0, 0, 0), m.isShown(frame0, 0, 2)],
  inv: m.invAffine([2, 0, 0, 1, 0, 4, 0, 2, 0, 0, 5, 3, 0, 0, 0, 1]), I,
  len4: m.stepText(view, 'length', 4), wid10: m.stepText(view, 'width', 10), none: m.stepText(null, 'length', 4),
  sides: ['garment_footwear_heels_left_shaft', 'garment_footwear_heels_right', 'garment_footwear_heels_mid',
          'garment_footwear_boots_left'].map((n) => m.shoeSide(n, 'heels')),
}));
"""


def run_js():
    with tempfile.TemporaryDirectory(prefix="smoke-footwear-allowance-") as d:
        script = Path(d) / "run.mjs"
        script.write_text(JS)
        r = subprocess.run(["node", str(script), str(ROOT)], capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            print(r.stderr)
            raise SystemExit("node failed — nothing was checked")
        return json.loads(r.stdout)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="footwear-allowance-") as tmp:
        root = Path(tmp)
        os.environ["STORAGE_DIR"] = str(root / "world")
        os.environ["INSTANCE_DIR"] = str(root / "inst")
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "inst")
        paths.get_config_path().write_text(json.dumps({"packages": {"enabled": "human"}}))
        from app.core import config
        config.load(paths.get_config_path(), instance_path=root / "inst/config.json")
        from app.core import db
        db.init_schema()
        plugins = root / "plugins"
        shutil.copytree(ROOT / "plugins" / "human", plugins / "human")
        from app.plugins.loader import discover_packages
        discover_packages(plugins, force=True)

        import numpy as np
        import _footwear_fixtures as fx
        from app.blender import refine
        from app.core import (fit_attempts as fa, footwear_fit as ff, footwear_insole, garment_assembly,
                              garment_footwear as gf, garment_store as gs, glb_mesh, model_refs)
        from app.imagegen import service
        from app.models import inventory
        from app.models.character import get_character_dir, get_character_profile, save_character_profile

        def no_hub(*_a, **_k):
            raise RuntimeError("the allowance must never reach the image service")
        service.get_image_service = no_hub
        model_refs.schedule_outfit_render = lambda *a, **k: None
        garment_assembly.schedule = lambda *_a, **_k: True
        refine.decimate_to = lambda src, _target, dst, **_kw: (shutil.copyfile(src, dst), {"ok": True, "tris": 1})[1]

        # --- [1] ------------------------------------------------------------------------------------------------
        print("[1] steps and validation")
        check("steps", ff.ALLOWANCE_STEPS, (0, 2, 4, 6, 8, 10, 12, 15, 20))
        check("shares", ff.allowance_shares({"width": 10, "length": 4}), (0.1, 0.04))
        for bad in (3, 25, True, "4"):
            raises(f"share {bad!r}", lambda bad=bad: ff.allowance_shares({"length": bad}))
        check("validate auto", gf.validate_allowance({"length": "auto"}), {"length": "auto"})
        for bad in ({"length": 3}, {"height": 2}, {}, {"width": True}):
            raises(f"validate {bad!r}", lambda bad=bad: gf.validate_allowance(bad))

        # --- [2] ------------------------------------------------------------------------------------------------
        print("[2] fit_pair on the clog")
        P, F = fx.clog()
        prepared = glb_mesh.static_glb(P, F, np.zeros((len(P), 2)))
        insole = footwear_insole.analyse(prepared)
        rigged = fx.foot_body_glb()
        body, joints = glb_mesh.body_arrays(rigged), glb_mesh.joint_bind_matrices(rigged)
        shoe = fx.shoe_garment(P, F)
        fits = {key: ff.fit_pair(insole, shoe, body, joints, allowance=a) for key, a in (
            ("none", None), ("00", {"width": 0, "length": 0}), ("L10", {"width": 0, "length": 10}),
            ("W10", {"width": 10, "length": 0}))}

        def blob(fit):
            return json.dumps(fit.record, sort_keys=True, default=str)

        def parts_sha(fit):
            h = hashlib.sha256()
            for side in sorted(fit.parts):
                for part in sorted(fit.parts[side]):
                    mesh = fit.parts[side][part]
                    for field in ("positions", "indices", "normals", "uvs", "joints", "weights"):
                        value = getattr(mesh, field, None)
                        if value is not None:
                            h.update(np.ascontiguousarray(value).tobytes())
            return h.hexdigest()

        check("all accepted", {k: f.ok for k, f in fits.items()}, {"none": True, "00": True, "L10": True, "W10": True})
        check("0/0 record = no allowance", blob(fits["00"]) == blob(fits["none"]), True)
        check("0/0 parts = no allowance", parts_sha(fits["00"]) == parts_sha(fits["none"]), True)
        check("0/0 no scale.allowance", "allowance" in fits["00"].record["scale"], False)
        s0, s10, sw = fits["00"].record["scale"], fits["L10"].record["scale"], fits["W10"].record["scale"]
        near("foot length", s0["foot_len_m"], 0.25, 1e-6)
        near("arc +0", s0["insole_arc_m"], 0.255, 1e-4)
        near("arc +10", s10["insole_arc_m"], 0.28, 1e-4)
        near("size", s10["allowance"]["size"], 0.28 / 0.255, 1e-4)
        near("k ratio", s10["k_m_per_unit"] / s0["k_m_per_unit"], 0.28 / 0.255, 1e-4)
        near("heel room", s10["allowance"]["heel_room_m"], 0.025, 1e-9)
        near("width in metres unchanged", s10["k_m_per_unit"] * s10["width_factor"],
             s0["k_m_per_unit"] * s0["width_factor"], 1e-5)
        check("toe room", [fits[k].record["sides"][s]["toe_room_mm"] for k in ("00", "L10") for s in ("left", "right")],
              [5.0, 5.0, 5.0, 5.0])
        near("W10 k", sw["k_m_per_unit"], s0["k_m_per_unit"], 1e-9)
        near("W10 width factor", sw["width_factor"], 1.1 * s0["width_factor"], 1e-5)
        check("W10 allowance", sw["allowance"], {"width_pct": 10.0, "length_pct": 0.0, "heel_room_m": 0.0, "size": 1.0})

        # --- [3] ------------------------------------------------------------------------------------------------
        print("[3] the fingerprint and the stored settings")
        human = {"template": "human-roleplay", "gender": "female", "age": 30, "height": 168,
                 "character_appearance": "slender", "body_slots": {"skin": {"tone": "olive"}}}
        check("create Demo", save_character_profile("Demo", dict(human), create_new=True), True)

        def item(item_id, slots):
            iid = inventory.add_item(name=item_id.capitalize(), category="outfit_piece", item_id=item_id,
                                     prompt_fragment=f"black {item_id}",
                                     outfit_piece={"slots": slots, "outfit_types": ["casual"], "mesh_mode": "own_mesh"})
            iid = iid["id"]
            folder = inventory._get_item_dir(iid, create=True)
            (folder / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n" + iid.encode())
            inventory.set_item_image(iid, "image.png")
            inventory.add_to_inventory("Demo", iid)
            return iid
        heels, shirt = item("heels", ["feet"]), item("shirt", ["top"])
        F0 = gs.garment_fsig("Demo", heels)
        check("auto: no allowance input", "allowance" in gf.fsig_inputs(
            "Demo", inventory.get_item(heels), profile=get_character_profile("Demo")), False)
        check("set length 4", gf.set_allowance("Demo", heels, {"length": 4}), True)
        check("stored", get_character_profile("Demo").get(gf.ALLOWANCE_KEY), {heels: {"length": 4}})
        F1 = gs.garment_fsig("Demo", heels)
        check("length 4 changes the fingerprint", F1 != F0, True)
        gf.set_allowance("Demo", heels, {"width": 6})
        F2 = gs.garment_fsig("Demo", heels)
        check("width 6 changes it again", F2 not in (F0, F1), True)
        check("read back", gf.allowance(get_character_profile("Demo"), heels), {"width": 6, "length": 4})
        gf.set_allowance("Demo", heels, {"width": "auto", "length": "auto"})
        check("auto again: key gone", gf.ALLOWANCE_KEY in get_character_profile("Demo"), False)
        check("auto again: F0", gs.garment_fsig("Demo", heels), F0)
        check("stored 3 reads as auto", gf.allowance({gf.ALLOWANCE_KEY: {heels: {"length": 3}}}, heels),
              {"width": "auto", "length": "auto"})
        raises("not footwear", lambda: gf.set_allowance("Demo", shirt, {"length": 4}))

        # --- [4] ------------------------------------------------------------------------------------------------
        print("[4] Length Auto")
        real_attempt, real_pair = gf._fit_attempt, ff.fit_pair
        seen = []
        refuse = {"below": 4, "reason": "visible_poke 0.02 > 0.005 (share of the remaining foot vertices ...)"}

        def pair(*a, **k):
            seen.append(int((k.get("allowance") or {}).get("length", 0)))
            return real_pair(*a, **k)

        def att(result, prims, joints_):
            out = real_attempt(result, prims, joints_)
            length = seen[-1]
            if out.get("ok") and length < refuse["below"]:
                reasons = [refuse["reason"]]
                return {**out, "ok": False, "reasons": reasons,
                        "gates": {"ok": False, "reasons": reasons}, "marks": None}
            return out
        ff.fit_pair, gf._fit_attempt = pair, att

        def compute(settings):
            seen.clear()
            return gf.fit_compute(prepared, insole, rigged, None, gf.KIND, heels, "f" * 12, str(root / "out.glb"),
                                  settings)
        try:
            out = compute({"width": "auto", "length": "auto"})
            check("auto: accepted", out.get("ok"), True)
            al = (out.get("record") or {}).get("scale", {}).get("allowance") or {}
            check("auto: tried", sorted(set(seen)), [0, 2, 4])
            check("auto: applied", (al.get("length_pct"), al.get("auto")),
                  (4.0, {"width": "auto", "length": "auto", "tried_length": [0, 2, 4]}))
            out = compute({"width": "auto", "length": 2})
            check("fixed 2: no search", (out.get("ok"), sorted(set(seen))), (False, [2]))
            refuse["reason"] = "toe_conform_m 0.02 > 0.008 (toes ...)"
            out = compute({"width": "auto", "length": "auto"})
            check("other gate: no search", (out.get("ok"), sorted(set(seen))), (False, [0]))
            refuse.update(below=99, reason="visible_poke 0.02 > 0.005 (...)")
            out = compute(None)
            check("none accepted: all steps, +0 stands", (out.get("ok"), sorted(set(seen)), out.get("reasons")),
                  (False, list(ff.ALLOWANCE_STEPS), [refuse["reason"]]))
        finally:
            ff.fit_pair, gf._fit_attempt = real_pair, real_attempt

        # --- [5] ------------------------------------------------------------------------------------------------
        print("[5] the preview rule (TypeScript)")
        js = run_js()
        r = 0.28 / 0.255
        want_T = [r, 0, 0, -0.025, 0, r, 0, 0, 0, 0, 1.1, 0, 0, 0, 0, 1]
        check("T", np.allclose(js["T"], want_T, atol=1e-9), True)
        check("point", np.allclose(js["point"], [0.08480392, 0.010980392, 0.022], atol=1e-8), True)
        check("back", np.allclose(js["back"], [0.255 / 0.28, 0, 0, 0.025, 0, 0.255 / 0.28, 0, 0, 0, 0, 1 / 1.1, 0,
                                               0, 0, 0, 1], atol=1e-9), True)
        check("bind point", np.allclose(js["bind"], [1.08480392, 0.010980392, 0.022], atol=1e-8), True)
        check("isShown", js["shown"], [True, False])
        check("invAffine", np.allclose(js["inv"], [0.5, 0, 0, -0.5, 0, 0.25, 0, -0.5, 0, 0, 0.2, -0.6, 0, 0, 0, 1],
                                       atol=1e-12), True)
        check("step texts", (js["len4"], js["wid10"], js["none"]), ("+4 % = +9.6 mm", "+10 % = +9.6 mm", "+4 %"))
        check("shoeSide", js["sides"], ["left", "right", None, None])

        # --- [6] ------------------------------------------------------------------------------------------------
        print("[6] carry-over for footwear")
        reason = "visible_poke 0.02314 > 0.005 (share of the remaining foot vertices still below the upper's rim)"
        row = {"visible_poke": {"value": 0.0231437, "limit": 0.005, "ok": False}}
        check("row -> max", fa.refused_values([reason], row), {"visible_poke": ("max", 0.0231437)})
        check("row -> min", fa.refused_values(["ball_placement_mm 0.4 < 0.5"],
                                              {"ball_placement_mm": {"value": 0.4, "limit": 0.5}}),
              {"ball_placement_mm": ("min", 0.4)})
        check("range -> None", fa.refused_values(["stand_floor_mm 4 outside"],
                                                 {"stand_floor_mm": {"value": 4.0, "limit": [-3, 3]}}), None)
        acc = {"visible_poke": ("max", 0.0231437)}
        check("+0.00496 carries", fa.carries(acc, {"visible_poke": ("max", 0.0281)}), True)
        check("+0.00506 does not", fa.carries(acc, {"visible_poke": ("max", 0.0282)}), False)
        old = types.ModuleType("fit_attempts_old")
        old.__dict__["__name__"] = "fit_attempts_old"
        exec(subprocess.run(["git", "-C", str(ROOT), "show", f"{OLD}:app/core/fit_attempts.py"], capture_output=True,
                            text=True, check=True).stdout, old.__dict__)
        check(f"old code ({OLD}) cannot read the row", old.refused_values([reason], row), None)

        fa._current = lambda *_a, **_k: ""
        FS = "a1b2c3d4e5f6"
        get_character_dir("Demo", create=True)

        def path(part, body=""):
            return gs.garment_path("Demo", heels, FS, part, body=body)
        fit, failed = path("fit"), path("failed")
        fit.parent.mkdir(parents=True, exist_ok=True)
        fit.write_bytes(b"old-fit")
        gs.write_record(fit.with_suffix(".json"), {"accepted": True, "kind": "footwear", "item_id": heels, "fsig": FS})

        def attempt(data, value, carry=True, slot=""):
            src = root / "attempt.glb"
            src.write_bytes(data)
            why = f"visible_poke {value:.5f} > 0.005 (share ...)"
            gates = {"ok": False, "reasons": [why], "visible_poke": {"value": value, "limit": 0.005, "ok": False}}
            return fa.store("Demo", heels, FS, body="", kind="footwear",
                            record={"kind": "footwear", "item_id": heels, "fsig": FS, "body_id": "base0123abcd"},
                            error="fit refused — " + why, gates=gates, glb=src, tris=10, carry=carry, slot=slot)
        check("A: nothing to carry", attempt(b"shoe-A", 0.0231437), False)
        with fa._lock("Demo", ""):
            fa._accept_locked("Demo", heels, "", {})
        check("fit = A", fit.read_bytes(), b"shoe-A")
        check("B carried", attempt(b"shoe-B", 0.0231437), True)
        check("fit = B", fit.read_bytes(), b"shoe-B")
        check("C worse by 0.0069: void", attempt(b"shoe-C", 0.03), False)
        check("the displaced fit back", fit.read_bytes(), b"old-fit")
        with fa._lock("Demo", ""):
            fa._accept_locked("Demo", heels, "", {})
        check("a caller that does not carry: void", attempt(b"shoe-D", 0.03, carry=False), False)
        check("old-fit again", fit.read_bytes(), b"old-fit")
        _ = failed

    print()
    if FAILS:
        print(f"FAILED: {len(FAILS)} — " + ", ".join(FAILS))
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
