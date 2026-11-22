"""Smoke (real Blender, CPU, 0 hub jobs): the world's tops keep the cut they have on main (commit 84feba712) unless a
collar or a placket is set — plan group B, phases E + F, review of stage 3.

Usage:
    ./.venv/bin/python scripts/smoke_template_cut_tops_main.py --bodies <dir with COPIES of base*.glb> \
        [--only NAME ...] [--instance <instance dir, default <repo>/instance>] [--keep]

``--bodies`` holds copies of the characters' current base bodies under their own file names (``base10d67a5c.glb``
Tilda, ``base4b00ccc7.glb`` Dario, ``base634402e5.glb`` Kai, ``base5fe6bd6a.glb`` Ylva) — never a live world folder.
The base checkout is ``git archive 84feba712`` (``app`` + ``shared``) unpacked into a temp folder: an EXPLICIT commit,
never ``HEAD`` (a fix committed on this branch would otherwise compare with itself). Every cut is a cut-only run
(``build_args`` + ``cut_only``) of ``validate_params`` of the piece's stored params, no lower layers, in each checkout
with its own ``garment_template`` and builder.

The rule (``garment_template.neck_rules`` / ``neck_piece``): a top is cut by the neck-ring rules of phases E + F only
with a ``collar`` or a ``placket``; without either it takes the builder's path from before the phases. So, derived:

[1] the five tops on ``texture`` "cut" in the world, as stored (collar none, no placket): Tilda's Buttoned Cream Blouse
    (crew), Dario's Worn Linen Shirt (V 5 cm) and Embroidered Green Shirt (crew 15 cm), Kai's T-Shirt (crew), Ylva's
    Laced Linen Blouse (off-shoulder) — ``islands.json`` byte-identical to the base checkout's, no ``marks.json``
    written (a line is only written for a placket), and ``garment_template_cut.cut_sig`` (and ``tsig``) the same 12
    hex in both checkouts for the same base sha and lower layers — nothing goes stale on the merge.
[2] Dario's Worn Linen Shirt with ``placket`` "buttons": the phase rules apply — B8, a V never keeps the neckband, so
    the islands are exactly {front, back, sleeve_l, sleeve_r} (main's cut has a ``band``), ``marks.json`` holds
    ``centre_front`` on ``front``, and its ``cut_sig`` differs from [1]'s (the key gains ``"neck"``).
[3] Ylva's off-shoulder blouse with ``placket`` "buttons": an off-shoulder top has no neck ring — the islands are the
    same bytes as [1]'s and its ``cut_sig`` is [1]'s (B11 cuts it once more under the same sig). It gets no line: its
    front is laced (A229 cuts the centre front faces away from the band down ``lace_depth_m``), so no ``centre_front``
    is written and ``placket_atlas`` leaves its atlas as it is ("no marks").
[4] keys only (no Blender): a jacket and a dress always carry ``"neck"`` in their cut key (the B8 depth rule and the
    smooth collar ring reach them: the version that keys it), a covered top only with a collar or a placket, a
    strapped / off-shoulder top never.
"""
import argparse
import io
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
BASE_COMMIT = "84feba712"
FAILS = []


def check(label, ok, detail=""):
    print(("OK   " if ok else "FAIL ") + label + (f"  ({detail})" if detail != "" else ""))
    if not ok:
        FAILS.append(label)


_COMMON = {"flare": 0.3, "waist_height": "natural", "slit": "none", "slit_m": 0.0, "band_m": 0.025,
           "band_drop_m": 0.05, "lacing": "none", "lace_depth_m": 0.15, "front": "closed", "collar": "none",
           "fabric": "medium", "opacity": 0.4, "texture": "cut", "sleeve_print": "plain"}
#: the stored params of the world's tops (the fields a top reads; the rest are other kinds' defaults)
PIECES = {
    "tilda_blouse": ("base10d67a5c.glb", dict(_COMMON, kind="top", length_m=0.29, shoulders="covered", sleeves="elbow",
                                              sleeve_fit=0.68, fit=0.4, neckline="crew", neck_depth_m=0.0)),
    "dario_linen": ("base4b00ccc7.glb", dict(_COMMON, kind="top", length_m=0.5, shoulders="covered", sleeves="elbow",
                                             sleeve_fit=0.3, fit=0.3, neckline="v", neck_depth_m=0.05)),
    "dario_embroidered": ("base4b00ccc7.glb", dict(_COMMON, kind="top", length_m=0.5, shoulders="covered",
                                                   sleeves="long", sleeve_fit=0.3, fit=0.6, neckline="crew",
                                                   neck_depth_m=0.15)),
    "kai_tshirt": ("base634402e5.glb", dict(_COMMON, kind="top", length_m=0.55, shoulders="covered", sleeves="short",
                                            sleeve_fit=0.3, fit=0.11, neckline="crew", neck_depth_m=0.0)),
    "ylva_blouse": ("base5fe6bd6a.glb", dict(_COMMON, kind="top", length_m=0.35, shoulders="off_shoulder",
                                             sleeves="elbow", band_m=0.033, band_drop_m=0.08, lacing="front",
                                             lace_depth_m=0.28, sleeve_fit=0.77, fit=0.3, neckline="crew",
                                             neck_depth_m=0.0)),
}

_SUB = r'''
import json, sys
from pathlib import Path
repo, body, out, raw, inst = sys.argv[1:6]
sys.path.insert(0, repo)
from app.core import paths
paths.init(str(Path(out) / "storage"))
from app.blender import runner
runner.use_instance_config(Path(inst))
from app.core import garment_template as gt
from app.core import garment_template_cut as gtc
params = gt.validate_params(json.loads(raw))[0]
keys = {"cut_sig": gtc.cut_sig(params, base_sha="b" * 12, lower=["lower:x"]),
        "tsig": gt.tsig(params, base_sha="b" * 12, texture_sha="t" * 12, lower=["lower:x"])}
ok = True
if body != "-":
    spec = gt.panel_spec(params, gt.measure_body(Path(body).read_bytes()))
    args = gt.build_args(params, spec, item_id="same")
    args["cut_only"] = True
    res = runner.run(gt.SCRIPT, inputs={"body": Path(body)}, params=args, out_dir=Path(out), timeout_s=600)
    ok = bool(res.get("ok"))
print("RESULT", json.dumps({"ok": ok, **keys}))
'''


def run_in(repo: Path, body, out: Path, raw: dict, inst: str) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    p = subprocess.run([sys.executable, "-c", _SUB, str(repo), str(body) if body else "-", str(out), json.dumps(raw),
                        inst], capture_output=True, text=True, cwd=str(repo))
    line = [x for x in p.stdout.splitlines() if x.startswith("RESULT ")]
    if not line:
        print(p.stdout[-1500:], p.stderr[-1500:])
        return {"ok": False}
    got = json.loads(line[-1][7:])
    got["islands"] = (out / "islands.json").read_bytes() if (out / "islands.json").is_file() else None
    got["marks"] = json.loads((out / "marks.json").read_text()) if (out / "marks.json").is_file() else None
    return got


def base_checkout(tmp: Path) -> Path:
    """``app`` + ``shared`` of ``BASE_COMMIT`` unpacked into ``tmp/base``."""
    dest = tmp / "base"
    dest.mkdir()
    raw = subprocess.run(["git", "-C", str(ROOT), "archive", BASE_COMMIT, "app", "shared"], capture_output=True,
                         check=True).stdout
    with tarfile.open(fileobj=io.BytesIO(raw)) as tf:
        tf.extractall(dest, filter="data")
    return dest


def islands_of(raw: bytes) -> list:
    return sorted(i["name"] for i in json.loads(raw)["islands"])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bodies", required=True)
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--instance", default=str(ROOT / "instance"), help="the instance dir (Blender's settings), read")
    ap.add_argument("--keep", action="store_true")
    a = ap.parse_args()
    tmp = Path(tempfile.mkdtemp(prefix="smoke-cut-tops-main-"))
    try:
        # [4] keys only, this checkout
        from app.core import paths
        paths.init(str(tmp / "storage"))
        from app.core import garment_template as gt
        top = gt.validate_params(PIECES["kai_tshirt"][1])[0]
        check("[4] a covered top without collar / placket: no neck rules, no neck key",
              not gt.neck_rules(top) and not gt.neck_piece(top))
        check("[4] a covered top with a placket: neck rules and the neck key",
              gt.neck_rules(dict(top, placket="buttons")) and gt.neck_piece(dict(top, placket="buttons")))
        check("[4] a covered top with a stand collar: neck rules and the neck key",
              gt.neck_rules(dict(top, collar="stand")) and gt.neck_piece(dict(top, collar="stand")))
        off = gt.validate_params(PIECES["ylva_blouse"][1])[0]
        check("[4] an off-shoulder top with a placket: neck rules (its line), never the neck key",
              gt.neck_rules(dict(off, placket="buttons")) and not gt.neck_piece(dict(off, placket="buttons")))
        for kind in ("jacket", "dress"):
            p_ = gt.validate_params({"kind": kind, "shoulders": "covered", "neckline": "crew"})[0]
            check(f"[4] a {kind} always carries the neck key", gt.neck_rules(p_) and gt.neck_piece(p_))
        args = gt.build_args(top, {"row_y": [0.0]}, item_id="x")
        check("[4] build_args of a top without collar / placket has no neck_rules", "neck_rules" not in args)

        base = base_checkout(tmp)
        bodies = Path(a.bodies)
        first = {}
        for name, (body_file, raw) in PIECES.items():
            if a.only and name not in a.only:
                continue
            body = bodies / body_file
            mine = run_in(ROOT, body, tmp / f"{name}_this", raw, a.instance)
            old = run_in(base, body, tmp / f"{name}_base", raw, a.instance)
            ok = mine.get("ok") and old.get("ok") and mine.get("islands") and old.get("islands")
            check(f"[1] {name}: runs in both checkouts", bool(ok))
            if not ok:
                continue
            first[name] = mine
            check(f"[1] {name}: islands.json byte-identical to {BASE_COMMIT}", mine["islands"] == old["islands"],
                  f"{islands_of(mine['islands'])} vs {islands_of(old['islands'])}")
            check(f"[1] {name}: no marks.json without a placket", mine["marks"] is None)
            check(f"[1] {name}: cut_sig unchanged ({old['cut_sig']})", mine["cut_sig"] == old["cut_sig"],
                  mine["cut_sig"])
            check(f"[1] {name}: tsig unchanged", mine["tsig"] == old["tsig"])
        if "dario_linen" in first:
            body_file, raw = PIECES["dario_linen"]
            got = run_in(ROOT, bodies / body_file, tmp / "dario_linen_placket", dict(raw, placket="buttons"),
                         a.instance)
            check("[2] dario_linen + placket: runs", bool(got.get("ok") and got.get("islands")))
            if got.get("islands"):
                check("[2] islands {back, front, sleeve_l, sleeve_r} (B8: a V never keeps the band)",
                      islands_of(got["islands"]) == ["back", "front", "sleeve_l", "sleeve_r"],
                      islands_of(got["islands"]))
                lines = (got["marks"] or {}).get("lines") or {}
                check("[2] marks: centre_front on front", set(lines) == {"centre_front"}
                      and lines["centre_front"]["island"] == "front", sorted(lines))
                check("[2] cut_sig differs from the piece without a placket",
                      got["cut_sig"] != first["dario_linen"]["cut_sig"])
        if "ylva_blouse" in first:
            body_file, raw = PIECES["ylva_blouse"]
            got = run_in(ROOT, bodies / body_file, tmp / "ylva_blouse_placket", dict(raw, placket="buttons"),
                         a.instance)
            check("[3] ylva_blouse + placket: runs", bool(got.get("ok") and got.get("islands")))
            if got.get("islands"):
                check("[3] islands the same bytes as without a placket",
                      got["islands"] == first["ylva_blouse"]["islands"])
                check("[3] cut_sig the same as without a placket", got["cut_sig"] == first["ylva_blouse"]["cut_sig"])
                lines = (got["marks"] or {}).get("lines") or {}
                check("[3] no centre_front line on the laced front", "centre_front" not in lines, sorted(lines))
    finally:
        if a.keep:
            print("work dir", tmp)
        else:
            shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{len(FAILS)} FAILED: {FAILS}" if FAILS else "\nALL OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
