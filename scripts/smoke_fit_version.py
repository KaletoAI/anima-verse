#!/usr/bin/env python3
"""Smoke: the fit-version rule of the clothing fit (``garment_fit.expected_fit_version``, ``FIT_VERSION``) — every
ruling that bumped the clothing version and the records each one keeps current, in one table per ruling.

Usage:
    ./.venv/bin/python scripts/smoke_fit_version.py

No server, no world DB, no hub, no GLB: pure record checks plus the A199 geodesic walk on a synthetic mesh. Each
section below is one former smoke (or the version section of one); a failing section does not stop the next, the
run exits non-zero and names every failed section. Every expectation is derived by hand:

[A] ROOM ALLOWANCE (formerly smoke_fit_room_version; A198 bumps clothing to 19 and keeps every room-free fit current,
    ``garment_fit.room_may_change``).
  A174 (2c9d19f6c) moves a FIXED width allowance (``allowance`` not "auto") and a DEPTH allowance (``depth`` not 0)
  to ``room_offset`` after the clearance pass. Auto width with depth 0 passes ``room=None`` -> X unchanged, and the
  old code passed ``ease_z=None`` / ``allowance="auto"`` -> the same: such a fit is unchanged bit for bit. A shell
  takes no settings. So:
    [1] version 18, allowance 10            -> due: expected 19
    [2] version 18, allowance auto, depth 3 -> due: 19
    [3] version 18, allowance auto, depth 0 -> current: 18
    [4] version 18, no fit_settings         -> defaults (auto, 0) -> current: 18
    [5] version 18, shell with allowance 10 -> shell ignores it -> current: 18
    [6] version 17, unseeded opening, allowance 6 -> the chain would keep 17, but room changes -> 19
    [7] version 17, unseeded opening, defaults -> chain keeps 17
    [8] version 19 anything                 -> 19
  A199 (clothing 20): the records carry ``sleeve_vertices`` 0 (they never walked, ``walk_may_change``), so a due one
  reads ``FIT_VERSION["clothing"]`` and [8] keeps 19.
  Pre-fix proof: at e846d7d02 FIT_VERSION["clothing"] == 18 and [1]/[2]/[6] read current (18 / 18 / 17).

[B] GEODESIC WALK (formerly smoke_fit_walk_version; the walks of the clothing fit count each mesh edge once — A199
    bumps clothing to 20 and keeps every fit that never walked current, ``garment_fit.walk_may_change``; review 06#9).
  Walk (``sleeve_cuffs``, ``SLEEVE_CUFF_REACH_M`` = 0.10 m, k = 1): a row t0..t4 at x = 0, 0.03, .., 0.12 m, one
  row 0.2 m above and one 0.2 m below. Each edge t_i -> t_i+1 is listed as (t_i, t_i+1) by BOTH its faces
  (the upper face and the lower face wind opposite ways). t0 is the sleeve, everything else a cuff candidate, all
  on arm part 1. A detour through the other rows is >= 0.4 m, beyond the reach. Each edge once: t1..t3 lie at
  0.03 / 0.06 / 0.09 <= 0.10 -> 3 cuff vertices; t4 (0.12) is out. Each edge twice (the old sum): 0.06 / 0.12 -> 1.
  [W1] cuffs == {t1, t2, t3}.
  [W2] ``_walk_edges`` lists each undirected edge once: 2 faces (0,1,2), (0,1,3) -> 5 edges.
  Version rule (clothing 20; 19 = ``CLOTHING_WALK_UNCHANGED``):
    [1] v19, transfer sleeve_vertices 12                 -> due: 20
    [2] v19, sleeve_vertices 0, sleeves.blend present    -> due: 20
    [3] v19, sleeve_vertices 0, trunk.blend present      -> due: 20
    [4] v19, sleeve_vertices 0, no blend                 -> current: 19
    [5] v19, no transfer report                          -> due: 20
    [6] v19 shell (no transfer)                          -> current: 19
    [7] v18 room-free, never walked                      -> the room rule keeps 18
    [8] v18 room-free, sleeve_vertices 5                 -> due: 20
    [9] v20 anything                                     -> 20
  Pre-fix proof: at 26977eda5 FIT_VERSION["clothing"] == 19 and [W1] gives only t1 (the doubled edges).

[C] TRUNK (formerly section [6] of smoke_trunk_fit, Ruling A83): FIT_VERSION clothing 18 (Ruling A114; 17 by Ruling
    A84, section [D]), CLOTHING_TRUNK_UNCHANGED 15. With nothing on an arm (report ``transfer.sleeve_share`` 0, so
    Ruling A84 changed nothing either), ``expected_fit_version`` of a clothing record of version 15 whose own metrics
    keep Auto as generated (Kira's blazer's numbers torso_gap 0.0138 / front 0.0126) -> 15 (it stays current); the
    blouse's (0.0232 / 0.0381) -> 17 (due); room 0.031 / front 0.010 -> 17; no metrics -> 15 (nothing to lay on);
    version 14 -> 17; version 16 -> 16; version 17 -> 17; the version 15 record with sleeves (sleeve share 0.3762)
    -> 17; a hair record -> FIT_VERSION hair 16. ("17" / "due" read ``FIT_VERSION["clothing"]`` today: every
    record carries sleeve_vertices 0 — never walked, A199 — so the older chain decides.)

[D] ARMPIT SEAM (formerly section [4] of smoke_armpit_seam, Ruling A84): FIT_VERSION clothing 18 (17 stays current
    without a seeded opening, Ruling A114), CLOTHING_SEAM_UNCHANGED 16, CLOTHING_TRUNK_UNCHANGED 15.
    ``expected_fit_version`` of a clothing record:
      v16 with ``report.transfer.sleeve_share`` 0 -> 16 (current: nothing rode an arm);
      v16 with sleeve_share 0.3762 (Kira's blazer) -> 17; v16 without a report -> 17 (may have sleeves);
      v15, sleeve_share 0, trunk kept (torso_gap 0.0138 / front 0.0126) -> 15; v15, sleeve_share 0, the blouse's
      trunk numbers (0.0232 / 0.0381) -> 17; v15, sleeve_share 0.2960, trunk kept -> 17; v14, sleeve_share 0 -> 17;
      v17 -> 17; a hair record keeps FIT_VERSION hair.

[E] SEEDED OPENING (formerly section [3] of smoke_opening_near_ring, Ruling A114): FIT_VERSION clothing 18; a
    version 17 record is current unless its opening report has a recess component with a seed (or without a
    ``seeds`` number): {seeds 450} -> 18, {seeds 0} -> 17, a ``shown`` component -> 17, no opening report -> 17,
    version 16 with sleeves -> 18; a version 18 record with seeds -> 18. (A198's version 19 keeps a room-free 18
    current, so "18" reads ``FIT_VERSION["clothing"]`` for the due ones.)

[F] OPENINGS (formerly section [6] of smoke_opening_shallow_lining, Ruling A51 and after): FIT_VERSION clothing 18
    (18 Ruling A114's seeds, 13 was Ruling A51's openings, 14 Ruling A72's repaired donors — A51's exemption of a
    version 12 record without a deep opening went with it —, 15 Ruling A76's kept sheet order, which changes every
    clothing fit, 16 Ruling A83's trunk laid onto the body, 17 Ruling A84's armpit seam). Every clothing record
    below 15 expects 17 (stale) — version 12 with a kept deep component, with a shallow one, with all left out,
    without an opening report; versions 11, 13 and 14 —; version 15 and 16 records without a sleeve share in their
    report 17 (they may have had sleeves, section [D]); a version 15 record with sleeve share 0 and no trunk metrics
    15 (Ruling A83's ``CLOTHING_TRUNK_UNCHANGED``), a version 16 record with sleeve share 0 16 (Ruling A84's
    ``CLOTHING_SEAM_UNCHANGED``); hair / footwear unchanged. No ``CLOTHING_OPENING_UNCHANGED`` (the A51 exemption)
    is left.
"""
import sys
import tempfile
import traceback
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths  # noqa: E402

paths.init(tempfile.mkdtemp(prefix="smoke_fit_version_"))
from app.core import garment_fit as gf  # noqa: E402

FAILED = []          # (section, label)
_SECTION = ["-"]


def check(label, ok, detail=""):
    print(("OK   " if ok else "FAIL ") + label + ("" if ok else f"  -> {detail}"))
    if not ok:
        FAILED.append((_SECTION[0], label))


def section(name, fn):
    """Run one section; a crash is recorded and the next section still runs."""
    _SECTION[0] = name
    print(f"\n=== {name}")
    try:
        fn()
    except Exception:  # noqa: BLE001 — a crashed section is a failed section, the others still run
        traceback.print_exc()
        FAILED.append((name, "crashed"))


def table(prefix, cases):
    for label, record, want in cases:
        got = gf.expected_fit_version(record)
        check(f"{prefix} {label} -> {want}", got == want, got)


def section_room():
    unseeded = {"components": [{"by": "recess", "dropped": True, "seeds": 0}], "faces": 0}

    def rec(v, settings=None, shell=False, opening=None):
        inputs = {}
        if settings is not None:
            inputs["fit_settings"] = settings
        if shell:
            inputs["mesh_shape"] = "shell"
        r = {"kind": "clothing", "fit_version": v, "inputs": inputs,
             "report": {"transfer": {"sleeve_share": 0.3, "sleeve_vertices": 0}}}
        if opening is not None:
            r["report"]["opening"] = opening
        return r

    check("FIT_VERSION clothing >= 19", gf.FIT_VERSION["clothing"] >= 19, gf.FIT_VERSION)
    due = gf.FIT_VERSION["clothing"]   # A199: 20; the records below never walked (sleeve_vertices 0)
    table("[A]", [
        ("[1] fixed width", rec(18, {"allowance": 10, "depth": 0}), due),
        ("[2] depth", rec(18, {"allowance": "auto", "depth": 3}), due),
        ("[3] room-free", rec(18, {"allowance": "auto", "depth": 0}), 18),
        ("[4] no settings", rec(18), 18),
        ("[5] shell", rec(18, {"allowance": 10, "depth": 0}, shell=True), 18),
        ("[6] 17 with room", rec(17, {"allowance": 6, "depth": 0}, opening=unseeded), due),
        ("[7] 17 room-free", rec(17, {"allowance": "auto", "depth": 0}, opening=unseeded), 17),
        ("[8] 19", rec(19, {"allowance": 10, "depth": 3}), 19),
    ])


def section_walk():
    check("FIT_VERSION clothing 20", gf.FIT_VERSION["clothing"] == 20, gf.FIT_VERSION)
    check("CLOTHING_WALK_UNCHANGED 19", gf.CLOTHING_WALK_UNCHANGED == 19)
    check("reach 0.10 m (the walk below assumes it)", abs(gf.SLEEVE_CUFF_REACH_M - 0.10) < 1e-12,
          gf.SLEEVE_CUFF_REACH_M)

    # the walk
    xs = [0.0, 0.03, 0.06, 0.09, 0.12]
    T = [(x, 0.0, 0.0) for x in xs]
    U = [(x, 0.2, 0.0) for x in xs]
    B = [(x, -0.2, 0.0) for x in xs]
    Q = np.array(T + U + B, np.float64)
    t, u, b = (lambda i: i), (lambda i: 5 + i), (lambda i: 10 + i)
    faces = []
    for i in range(4):
        faces += [(t(i), t(i + 1), u(i)), (u(i), t(i + 1), u(i + 1)),     # upper face lists (t_i, t_i+1)
                  (t(i), t(i + 1), b(i)), (b(i), t(i + 1), b(i + 1))]     # lower face lists it the same way
    sleeve = np.zeros(len(Q), bool)
    sleeve[t(0)] = True
    upper = np.zeros(len(Q), bool)
    cuff = gf.sleeve_cuffs(Q, np.zeros((1, 3)), np.array([1]), np.array(faces), upper, sleeve, 1.0)
    check("[W1] cuffs t1, t2, t3", sorted(np.nonzero(cuff)[0].tolist()) == [1, 2, 3], np.nonzero(cuff)[0].tolist())
    E = gf._walk_edges(np.array([[0, 1, 2], [0, 1, 3]]))
    check("[W2] 5 undirected edges", len(E) == 5 and len({tuple(e) for e in E.tolist()}) == 5, E.tolist())

    # the version rule
    def rec(v, transfer=None, shell=False, settings=None):
        inputs = {}
        if shell:
            inputs["mesh_shape"] = "shell"
        if settings is not None:
            inputs["fit_settings"] = settings
        r = {"kind": "clothing", "fit_version": v, "inputs": inputs, "report": {}}
        if transfer is not None:
            r["report"]["transfer"] = transfer
        return r

    free = {"allowance": "auto", "depth": 0}
    table("[B]", [
        ("[1] sleeve vertices", rec(19, {"sleeve_vertices": 12}), 20),
        ("[2] sleeve blend", rec(19, {"sleeve_vertices": 0, "sleeves": {"blend": {"band_vertices": 3}}}), 20),
        ("[3] trunk blend", rec(19, {"sleeve_vertices": 0, "trunk": {"blend": {"band_vertices": 3}}}), 20),
        ("[4] never walked", rec(19, {"sleeve_vertices": 0, "trunk": {"applied": "generated"}}), 19),
        ("[5] no transfer report", rec(19), 20),
        ("[6] shell", rec(19, shell=True), 19),
        ("[7] v18 room-free, never walked", rec(18, {"sleeve_vertices": 0, "sleeve_share": 0.3}, settings=free), 18),
        ("[8] v18 room-free, sleeve vertices", rec(18, {"sleeve_vertices": 5}, settings=free), 20),
        ("[9] v20", rec(20, {"sleeve_vertices": 7}), 20),
    ])


def section_trunk():
    check("[C] FIT_VERSION clothing >= 18, CLOTHING_TRUNK_UNCHANGED 15",
          gf.FIT_VERSION["clothing"] >= 18 and gf.CLOTHING_TRUNK_UNCHANGED == 15, gf.FIT_VERSION)
    due = gf.FIT_VERSION["clothing"]

    def rec(version, room=None, front=None, kind="clothing", share=0.0):
        metrics = {} if room is None else {"torso_gap_p50_m": room, "trunk_front_gap_p50_m": front}
        return {"kind": kind, "fit_version": version, "metrics": metrics,
                # sleeve_vertices 0: never walked (A199 ``walk_may_change``), the older chain decides
                "report": {"transfer": {"sleeve_share": share, "sleeve_vertices": 0}}}
    table("[C]", [
        ("v15 blazer 13.8 / 12.6 mm stays current", rec(15, 0.0138, 0.0126), 15),
        ("v15 blouse 23.2 / 38.1 mm is due", rec(15, 0.0232, 0.0381), due),
        ("v15 room 31 mm is due", rec(15, 0.031, 0.010), due),
        ("v15 without metrics stays current", rec(15), 15),
        ("v14 is due", rec(14, 0.0138, 0.0126), due),
        ("v16 is current", rec(16, 0.0232, 0.0381), 16),
        ("v17 is current", rec(17, 0.0232, 0.0381), 17),
        ("v15 with sleeves is due", rec(15, 0.0138, 0.0126, share=0.3762), due),
        ("hair keeps its own", rec(15, kind="hair"), gf.FIT_VERSION["hair"]),
    ])


def section_seam():
    check("[D] FIT_VERSION clothing 18 (Ruling A114), CLOTHING_SEAM_UNCHANGED 16, CLOTHING_TRUNK_UNCHANGED 15",
          gf.FIT_VERSION["clothing"] >= 18 and gf.CLOTHING_SEAM_UNCHANGED == 16 and gf.CLOTHING_TRUNK_UNCHANGED == 15,
          gf.FIT_VERSION)
    due = gf.FIT_VERSION["clothing"]

    def rec(version, share=None, room=None, front=None, kind="clothing"):
        r = {"kind": kind, "fit_version": version,
             "metrics": {} if room is None else {"torso_gap_p50_m": room, "trunk_front_gap_p50_m": front}}
        if share is not None:
            # sleeve_vertices 0: the record never walked (A199 ``walk_may_change``), so the older chain decides
            r["report"] = {"transfer": {"sleeve_share": share, "sleeve_vertices": 0}}
        return r
    table("[D]", [
        ("v16 nothing on an arm stays current", rec(16, 0.0), 16),
        ("v16 Kira's blazer (0.3762) is due", rec(16, 0.3762), due),
        ("v16 without a report is due", rec(16), due),
        ("v15 nothing on an arm, trunk kept stays current", rec(15, 0.0, 0.0138, 0.0126), 15),
        ("v15 nothing on an arm, the blouse's trunk is due", rec(15, 0.0, 0.0232, 0.0381), due),
        ("v15 with sleeves, trunk kept is due", rec(15, 0.2960, 0.0138, 0.0126), due),
        ("v14 is due", rec(14, 0.0), due),
        ("v17 is current", rec(17, 0.3762), 17),
        ("hair keeps its own", rec(16, kind="hair"), gf.FIT_VERSION["hair"]),
    ])


def section_seeded_opening():
    def rec(v, opening=None, share=0.3):
        # sleeve_vertices 0: never walked (A199 ``walk_may_change``, 72ef9bc63), the older chain decides
        r = {"kind": "clothing", "fit_version": v,
             "report": {"transfer": {"sleeve_share": share, "sleeve_vertices": 0}}}
        if opening is not None:
            r["report"]["opening"] = opening
        return r

    seeded = {"components": [{"by": "recess", "dropped": True, "seeds": 450}], "faces": 1181}
    unseeded = {"components": [{"by": "recess", "dropped": True, "seeds": 0}], "faces": 0}
    shown = {"components": [{"by": "shown", "dropped": True}], "faces": 2880}
    nonum = {"components": [{"by": "recess", "dropped": True}], "faces": 12}
    fv = gf.FIT_VERSION["clothing"]  # 18 when written; A198's version 19 keeps a room-free 18 current
    check("[E] FIT_VERSION clothing >= 18", gf.FIT_VERSION["clothing"] >= 18, gf.FIT_VERSION)
    table("[E]", [
        ("v17 seeded recess is due", rec(17, seeded), fv),
        ("v17 unseeded recess stays current", rec(17, unseeded), 17),
        ("v17 shown component stays current", rec(17, shown), 17),
        ("v17 without an opening report stays current", rec(17), 17),
        ("v17 recess without a seeds number is due", rec(17, nonum), fv),
        ("v16 with sleeves is due", rec(16), fv),
        ("v18 seeded stays 18", rec(18, seeded), 18),
    ])


def section_openings():
    kept = {"components": [{"pixels": 100, "recess_px": 5.0, "dropped": False}], "faces": 0}
    shallow = {"components": [{"pixels": 100, "recess_px": 3.0, "dropped": False}], "faces": 0}
    gone = {"components": [{"pixels": 100, "recess_px": 50.0, "dropped": True}], "faces": 12}
    due = gf.FIT_VERSION["clothing"]
    # sleeve_vertices 0: never walked (A199 ``walk_may_change``, 72ef9bc63), the older chain decides
    no_sleeves = {"sleeve_share": 0.0, "sleeve_vertices": 0}
    check("[F] FIT_VERSION clothing 18, no A51 exemption left",
          gf.FIT_VERSION["clothing"] >= 18 and not hasattr(gf, "CLOTHING_OPENING_UNCHANGED"), f"{gf.FIT_VERSION}")
    table("[F]", [
        ("v12 kept deep component", {"kind": "clothing", "fit_version": 12, "report": {"opening": kept}}, due),
        ("v12 shallow component", {"kind": "clothing", "fit_version": 12, "report": {"opening": shallow}}, due),
        ("v12 all left out", {"kind": "clothing", "fit_version": 12, "report": {"opening": gone}}, due),
        ("v12 opening None", {"kind": "clothing", "fit_version": 12, "report": {"opening": None}}, due),
        ("v12 no report", {"kind": "clothing", "fit_version": 12}, due),
        ("v11", {"kind": "clothing", "fit_version": 11, "report": {"opening": gone}}, due),
        ("v13", {"kind": "clothing", "fit_version": 13, "report": {"opening": kept}}, due),
        ("v14", {"kind": "clothing", "fit_version": 14, "report": {"opening": kept}}, due),
        ("v15 without a sleeve share", {"kind": "clothing", "fit_version": 15, "report": {"opening": kept}}, due),
        ("v16 without a sleeve share", {"kind": "clothing", "fit_version": 16, "report": {"opening": kept}}, due),
        ("v15 sleeve share 0", {"kind": "clothing", "fit_version": 15,
                                "report": {"opening": kept, "transfer": dict(no_sleeves)}}, 15),
        ("v16 sleeve share 0", {"kind": "clothing", "fit_version": 16,
                                "report": {"opening": kept, "transfer": dict(no_sleeves)}}, 16),
        ("hair unchanged", {"kind": "hair", "fit_version": 12}, gf.FIT_VERSION["hair"]),
        ("footwear unchanged", {"kind": "footwear", "fit_version": 12, "method": "shoe"},
         gf.FIT_VERSION["footwear"]),
    ])


section("[A] room allowance (A198)", section_room)
section("[B] geodesic walk (A199)", section_walk)
section("[C] trunk (A83)", section_trunk)
section("[D] armpit seam (A84)", section_seam)
section("[E] seeded opening (A114)", section_seeded_opening)
section("[F] openings (A51 .. A84)", section_openings)

print()
if FAILED:
    names = list(dict.fromkeys(s for s, _ in FAILED))
    print(f"FAILED {len(FAILED)} check(s) in {len(names)} section(s): " + ", ".join(names))
    for s, label in FAILED:
        print(f"  {s}: {label}")
    sys.exit(1)
print("ALL OK")
