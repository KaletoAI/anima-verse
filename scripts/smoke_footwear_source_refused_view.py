#!/usr/bin/env python3
"""A shoe whose SOURCE was refused (A187 ``source_failure``: the insole step found no insole in an accepted mesh) has
no fit, so nothing on the footwear panel can fit or adjust it — the panel and the figure say which step refused it
instead of offering an allowance that changes nothing (Ylva's Black Platform Boots, 2026-11-25: mesh "Accepted",
insole refused ``insole_cover 0.1728 < 0.8`` on a hollow platform sole, the allowance box still offered Width / Length
sliders and Save, the fit row said only "see its steps above").

Usage:
    ./.venv/bin/python scripts/smoke_footwear_source_refused_view.py

Throwaway storage + instance (``paths.init(<tmp>)`` before any world module), no world DB, no hub, no server. The shoe
source record is written to the store as ``footwear_source`` writes it; ``inventory.get_item_image_path`` returns None
(no item image -> ``item_image_sha256`` "" -> the source of seed 0 is ``ssig_for(item, 0)``). ``fit_attempts.fit_status``
is stubbed where a body row / the figure reads it (its own A187 split is covered by the footwear smokes).

Expected, derived by hand:

[1] ``garment_footwear.allowance_view`` with no shown fit (``fsig`` "", ``preview_fsig`` ""): record {} ->
    ``applied`` None, ``frame`` None, ``due`` False, and
    - source record {source, empty, cutout, mesh accepted; insole accepted False, failure "gate", gates.reasons
      ["insole_cover 0.1728 < 0.8 (share of the footprint with a tracked insole)"], no ``error``} ->
      ``refused_step`` = the first item step with ``accepted`` False = "insole", its error = the reasons joined ->
      ``blocked`` = {"step": "insole", "error": "insole_cover 0.1728 < 0.8 (share of the footprint with a tracked
      insole)"};
    - the same record with the insole accepted -> no refused step -> ``blocked`` None;
    - an insole refused by LOAD (``failure`` "load": busy, retried later) -> not a refusal -> ``blocked`` None.
[2] ``fit_attempts._entry`` of the plain body, ``fit_status`` = {state missing, failure None, source_failure {step
    "insole", error "No insole found in the shoe mesh"}}: status "missing", reason ``SHOE_STEP_REFUSED``,
    reason_detail "insole — No insole found in the shoe mesh" (was "" — the row named no step).
[3] ``figure_build._plain_fit_refusal``: the same status -> (``PIECE_SOURCE_REFUSED``, "insole — No insole found in
    the shoe mesh"); a refused FIT (failure {step "fit", error "visible_poke 0.02 > 0.005"}, no source failure) ->
    (``PIECE_REFUSED_PLAIN``, "visible_poke 0.02 > 0.005"); neither -> ("", "").
[4] UI (static): ``FootwearAllowance.tsx`` marks the ``blocked`` state (``data-footwear-allowance-blocked``) and names
    the refused step BEFORE the slider rows (since 2026-11-25 "Adjust shoe" the sliders stay below it: what is saved
    applies to the first fit, and the step can be accepted anyway); ``FootwearSteps.tsx`` warns on the mesh row when the
    mesh is accepted and the insole refused (``data-footwear-mesh-refused-by="insole"``); every string is in
    ``shared/languages/de.json``.

Fails on the old code (commit 9c73e57cf): ``allowance_view`` has no ``blocked`` key, the body row's reason_detail is
"", ``_plain_fit_refusal`` returns the bare error string (the figure called a refused shoe step "Its fit on the base
body was refused").
"""
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS = []
OLD = "9c73e57cf"
ITEM = "item_boots"
INSOLE_REASON = "insole_cover 0.1728 < 0.8 (share of the footprint with a tracked insole)"
NO_INSOLE = "No insole found in the shoe mesh"


def check(label, got, want):
    ok = got == want
    print(f"  {'ok ' if ok else 'BAD'} {label}: {got!r}" + ("" if ok else f" (want {want!r})"))
    if not ok:
        FAILS.append(label)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="footwear-refused-view-") as tmp:
        root = Path(tmp)
        os.environ["STORAGE_DIR"] = str(root / "world")
        os.environ["INSTANCE_DIR"] = str(root / "inst")
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "inst")
        from app.core import fit_attempts as fa, figure_build as fb, footwear_source as fs
        from app.core import garment_footwear as gf
        from app.core.garment_store import write_record
        from app.models import inventory
        inventory.get_item_image_path = lambda _item_id: None

        ssig = fs.ssig_for(ITEM, 0)
        folder = fs.source_dir(ITEM, ssig)
        folder.mkdir(parents=True)

        def record(insole):
            steps = {s: {"accepted": True, "gates": {}} for s in ("source", "empty", "cutout", "mesh")}
            steps["insole"] = insole
            write_record(folder / "record.json", {"steps": steps})

        print("[1] allowance_view without a fit")
        record({"accepted": False, "failure": "gate", "gates": {"ok": False, "reasons": [INSOLE_REASON]}})
        view = gf.allowance_view("Demo", ITEM, {}, "", "")
        check("applied", view["applied"], None)
        check("frame", view["frame"], None)
        check("due", view["due"], False)
        check("blocked (insole refused)", view.get("blocked"), {"step": "insole", "error": INSOLE_REASON})
        record({"accepted": True, "gates": {"ok": True}})
        check("blocked (insole accepted)", gf.allowance_view("Demo", ITEM, {}, "", "").get("blocked", "absent"), None)
        record({"accepted": False, "failure": fs.LOAD, "gates": {}})
        check("blocked (load)", gf.allowance_view("Demo", ITEM, {}, "", "").get("blocked", "absent"), None)

        print("[2] the plain body row names the refused shoe step")
        source = {"step": "insole", "error": NO_INSOLE}
        status = {"fsig": "0123456789ab", "state": "missing", "failure": None, "body_sha": "", "base_fit_sha": "",
                  "source_failure": source}
        fa.fit_status = lambda *_a, **_k: dict(status)
        fa.attempt_of = lambda *_a, **_k: None
        fa.body_label = lambda *_a, **_k: "Plain body"
        entry = fa._entry("Demo", ITEM, "", {})
        check("status", entry["status"], "missing")
        check("reason", entry["reason"], fa.SHOE_STEP_REFUSED)
        check("reason_detail", entry["reason_detail"], "insole — No insole found in the shoe mesh")

        print("[3] the figure's missing reason")
        check("source refused", fb._plain_fit_refusal("Demo", ITEM, {}),
              (fb.PIECE_SOURCE_REFUSED, "insole — No insole found in the shoe mesh"))
        status.update(failure={"step": "fit", "error": "visible_poke 0.02 > 0.005"}, source_failure=None)
        check("fit refused", fb._plain_fit_refusal("Demo", ITEM, {}),
              (fb.PIECE_REFUSED_PLAIN, "visible_poke 0.02 > 0.005"))
        status.update(failure=None)
        check("neither", fb._plain_fit_refusal("Demo", ITEM, {}), ("", ""))

    print("[4] UI")
    chars = ROOT / "frontend/src/tabs/characters"
    allowance = (chars / "FootwearAllowance.tsx").read_text(encoding="utf-8")
    steps = (chars / "FootwearSteps.tsx").read_text(encoding="utf-8")
    blocked_at = allowance.find("data-footwear-allowance-blocked")
    check("blocked state named before the slider rows", 0 < blocked_at < allowance.find("{row('width')}"), True)
    check("mesh row warning", 'data-footwear-mesh-refused-by="insole"' in steps, True)
    de = json.loads((ROOT / "shared/languages/de.json").read_text(encoding="utf-8"))
    de = de.get("translations", de)
    for key in ("No fit yet: the shoe itself was refused at its “{step}” step. Accept that step anyway or regenerate "
                "it in the steps beside; what you save here applies to the first fit.",
                "This mesh passed its own checks, but the Insole step refused it — no fit can be made from it. "
                "Regenerate the mesh (1 mesh job), or accept the insole anyway.",
                fb.PIECE_SOURCE_REFUSED):
        check(f"de.json {key[:40]}…", key in de, True)

    print("FAIL: " + ", ".join(FAILS) if FAILS else "OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
