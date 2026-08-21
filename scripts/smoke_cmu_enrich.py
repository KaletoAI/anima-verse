#!/usr/bin/env python3
"""Smoke run for the CMU take enrichment (``scripts/cmu_enrich_index.py``).

Usage:  ./.venv/bin/python scripts/smoke_cmu_enrich.py

Runs WITHOUT Blender and without the converted FBX: it measures five known
takes straight from the downloaded ASF/AMC originals under
``shared/models/mocap-src/cmu`` and compares them with what the CMU
descriptions say those takes contain. If the originals are not on disk the
script says so and exits 0 — it has nothing to measure, not a failure.

Every expectation below is derived BY HAND from the CMU catalog entry of the
take and from the heuristics documented in ``cmu_enrich_index``; nothing here
is a recording of the script's own output.

===========================================================================
[1] 07_01 — "walk", 120 Hz
===========================================================================
A single walk across the capture volume. Hand derivation:

* The actor walks upright the whole time, so the hips stay near the top of
  their range (hips_rel ≈ 0.9 … 0.97, always above the 0.85 standing line)
  → posture "standing", never "mixed".
* Walking is locomotion: the root leaves where it started. Two to three steps
  of ~0.7 m give some 2–4 m start→end, which is over the 0.5 m "in-place"
  line → travel is "walks" or "travels" (measured: ~3.5 m).
* A walking pace moves feet and hands at about 1–2 m/s → energy "moderate"
  or "fast", certainly not "static"/"calm".
* 316 frames at 120 Hz = 2.63 s → duration_class "short" (< 3 s).
* Description "walk" → tag "walk"; CMU main category 3 "Locomotion" adds
  the category tag "locomotion".

===========================================================================
[2] 14_30 — "sit on stepstool, ankle on other knee, hand on chin"
===========================================================================
The actor walks in, sits down on the stool, sits for a while, gets up again.
So the take contains BOTH a standing and a sitting stretch, each far more than
20 % of its frames → posture must be "mixed", and the hip band must span the
two: hips_rel_max above the 0.85 standing line, hips_rel_min clearly below it
(sitting on a stool puts the hips at roughly half a leg length).
Description contains "sit" → tag "sit", and "stepstool" → "interact-object".

===========================================================================
[3] 77_16 — "laying down, getting up, careful ready pose", 60 Hz
===========================================================================
Starts on the floor: the hips are then barely above the ground, well under the
0.35 lying line (hips_rel_min ≈ 0.1). The actor gets up, so the take again
holds two classes → posture "lying" or "mixed", and the sparkline must START
low (first value < 0.35) and END high (last value > 0.5).
"laying" → tag "lie".

===========================================================================
[4] 60_01 / 61_01 — "salsa dance", a CONFIRMED pair at 60 Hz
===========================================================================
Two actors captured at the same time; both AMCs hold 2242 frames, which is
what makes the catalog's pairing guess a fact. Hand derivation:

    2242 frames / 60 Hz = 37.37 s          (NOT 2242/120 = 18.7 s —
                                            the framerate comes from the
                                            catalog entry, never assumed)

→ pair True for both, roles "a" and "b", partners pointing at each other,
framerate 60, duration 37.4 s ± 0.1, duration_class "long", tag "dance"
(and "two-subjects", because the subject description says "salsa").

===========================================================================
[5] 18_01 / 19_01 — "walk, shake hands (2 subjects - subject A/B)"
===========================================================================
Also a confirmed pair (both 303 frames). Their descriptions carry both
"2 subjects" and "shake hands" → tag "two-subjects"; "walk" → tag "walk".
Both belong to the SAME duplicate group: the normalisation drops the
"(2 subjects - subject A)" suffix, so "walk, shake hands" is what is left of
both.

===========================================================================
[6] The tag rules and the sparkline shape
===========================================================================
Checked against literal strings, no files involved: "jog around the block"
→ run, "sit-up" is an exercise and NOT sitting, "T-pose calibration" → test,
a description matching nothing → "untagged". And every measured take carries
exactly 40 sparkline values, each a finite float.
"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

_spec = importlib.util.spec_from_file_location("cmu_enrich_index",
                                               ROOT / "scripts" / "cmu_enrich_index.py")
CE = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(CE)

import json  # noqa: E402

SRC = ROOT / "shared" / "models" / "mocap-src" / "cmu"
CATALOG = ROOT / "shared" / "models" / "cmu_catalog.json"

FAILURES = []
CHECKED = 0


def check(label, actual, expected, tol=None):
    global CHECKED
    CHECKED += 1
    if tol is None:
        ok = (actual in expected) if isinstance(expected, set) else actual == expected
    else:
        ok = abs(actual - expected) <= tol
    print(f"  {'OK  ' if ok else 'FAIL'} {label}: {actual!r}"
          + ("" if ok else f" — expected {expected!r}"))
    if not ok:
        FAILURES.append(label)


def measure(take: dict) -> dict:
    asf = SRC / take["subject_dir"] / Path(take["asf"]).name
    amc = SRC / take["subject_dir"] / Path(take["amc"]).name
    return CE.measure(asf, amc, float(take.get("framerate") or 120))


def main() -> int:
    if not CATALOG.is_file():
        print(f"catalog missing ({CATALOG}) — run scripts/cmu_catalog.py first; nothing to check")
        return 0
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    by_id = {t["id"]: t for t in catalog["takes"]}
    mains = catalog["main_categories"]
    wanted = ["07_01", "14_30", "77_16", "60_01", "61_01", "18_01", "19_01"]
    missing = [tid for tid in wanted
               if not (SRC / by_id[tid]["subject_dir"]
                       / Path(by_id[tid]["amc"]).name).is_file()]
    if missing:
        print(f"originals not downloaded ({', '.join(missing)}) under {SRC} — "
              "run scripts/cmu_fetch_all.py; nothing to check")
        return 0

    m = {tid: measure(by_id[tid]) for tid in wanted}
    tags = {tid: CE.tags_for(by_id[tid], mains) for tid in wanted}
    pairs = CE.load_confirm_pairs()(catalog["takes"], SRC)
    _groups, group_of = CE.build_groups(catalog["takes"])

    print("\n[1] 07_01 — a plain walk")
    w = m["07_01"]["metrics"]
    check("07_01 posture", w["posture"], "standing")
    check("07_01 hips_rel_median above the standing line", w["hips_rel_median"] > 0.85, True)
    check("07_01 travel class", w["travel"], {"walks", "travels"})
    check("07_01 travel_m (2–4 m of walking)", 2.0 < w["travel_m"] < 4.5, True)
    check("07_01 energy", w["energy"], {"moderate", "fast"})
    check("07_01 duration_s = 316/120", m["07_01"]["duration_s"], 2.633, tol=0.01)
    check("07_01 duration_class", w["duration_class"], "short")
    check("07_01 tags", sorted(tags["07_01"]), ["locomotion", "walk"])

    print("\n[2] 14_30 — sits down and gets up again")
    s = m["14_30"]["metrics"]
    check("14_30 posture", s["posture"], "mixed")
    check("14_30 hips span standing", s["hips_rel_max"] > 0.85, True)
    check("14_30 hips span sitting", s["hips_rel_min"] < 0.7, True)
    check("14_30 has tag sit", "sit" in tags["14_30"], True)
    check("14_30 has tag interact-object", "interact-object" in tags["14_30"], True)

    print("\n[3] 77_16 — starts on the floor")
    L = m["77_16"]["metrics"]
    check("77_16 posture", L["posture"], {"lying", "mixed"})
    check("77_16 hips_rel_min below the lying line", L["hips_rel_min"] < 0.35, True)
    check("77_16 sparkline starts lying", m["77_16"]["sparkline"][0] < 0.35, True)
    check("77_16 sparkline ends upright", m["77_16"]["sparkline"][-1] > 0.5, True)
    check("77_16 has tag lie", "lie" in tags["77_16"], True)

    print("\n[4] 60_01 / 61_01 — the salsa pair at 60 Hz")
    check("60_01 confirmed as a pair", "60_01" in pairs, True)
    check("60_01 role", by_id["60_01"]["pair_role"], "a")
    check("61_01 role", by_id["61_01"]["pair_role"], "b")
    check("60_01 partner", by_id["60_01"]["pair_partner"], "61_01")
    check("61_01 partner", by_id["61_01"]["pair_partner"], "60_01")
    check("60_01 framerate", by_id["60_01"]["framerate"], 60)
    check("60_01 frames", m["60_01"]["frames"], 2242)
    check("60_01 duration_s = 2242/60", m["60_01"]["duration_s"], 37.4, tol=0.1)
    check("61_01 duration_s = 2242/60", m["61_01"]["duration_s"], 37.4, tol=0.1)
    check("60_01 duration_class", m["60_01"]["metrics"]["duration_class"], "long")
    check("60_01 has tag dance", "dance" in tags["60_01"], True)

    print("\n[5] 18_01 / 19_01 — walk and shake hands")
    check("18_01 confirmed as a pair", "18_01" in pairs, True)
    check("18_01 has tag two-subjects", "two-subjects" in tags["18_01"], True)
    check("19_01 has tag two-subjects", "two-subjects" in tags["19_01"], True)
    check("18_01 has tag walk", "walk" in tags["18_01"], True)
    check("18_01/19_01 share one duplicate group",
          group_of["18_01"] == group_of["19_01"] == "walk-shake-hands", True)

    print("\n[6] tag rules on literal strings")
    def tag_of(desc, subject=""):
        return sorted(CE.tags_for({"description": desc, "subject_description": subject,
                                   "categories": []}, mains))
    check("'jog around the block' → run", tag_of("jog around the block"), ["run"])
    check("'sit-up' is exercise, not sitting", tag_of("sit-ups on the floor"), ["exercise"])
    check("'T-pose calibration' → test", tag_of("T-pose calibration"), ["test"])
    check("'sitting on a chair' → sit + interact-object",
          tag_of("sitting on a chair"), ["interact-object", "sit"])
    check("nothing matches → untagged", tag_of("zzz qqq"), ["untagged"])
    check("normalised description drops the subject suffix",
          CE.normalize_desc("walk, shake hands (2 subjects - subject B)"),
          "walk shake hands")

    print("\n[6b] every measured take has a 40-point sparkline")
    check("sparkline lengths", sorted({len(v["sparkline"]) for v in m.values()}), [40])
    check("sparkline values are finite floats",
          all(isinstance(x, float) and x == x and abs(x) < 10
              for v in m.values() for x in v["sparkline"]), True)

    print(f"\n{CHECKED} checks, {len(FAILURES)} failures")
    if FAILURES:
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
