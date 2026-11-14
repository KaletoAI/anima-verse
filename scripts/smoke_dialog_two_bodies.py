#!/usr/bin/env python3
"""Ruling A67: the piece dialog's body switch offers the base body and the CURRENT body only — never an older body
shape the piece was once fitted on.

Usage:
    ./.venv/bin/python scripts/smoke_dialog_two_bodies.py

Runs against a THROWAWAY storage + instance directory — no world, no hub, no GPU, no server. Tables (named per
case): ``figure.wanted_figure`` (a stand-in with ``shape`` / ``own`` / ``in_body``), ``garment_store.stored_groups``
(the piece's files per body), ``garment_footwear.stored_outfit_bodies`` (the stored rigged bodies),
``garment_store._garment_kind`` ("clothing"); ``fit_attempts._entry`` / ``_derived_entry`` / ``shape_names`` are
stand-ins that echo the body (what an entry SAYS about its fit is covered by smoke_fit_user_accept.py and
smoke_refit_selected_body.py). Expected values, derived by hand from Ruling A67:

[1] ``dialog_shape(Demo, jacket)`` — the shape the worn outfit calls for (wanted figure), else "":
    a) wanted shape = the base signature "base1234abcd" (plain)                          -> ("", False)
    b) wanted B, jacket an own-mesh piece of it (own {jacket}), stored [A, B, C]         -> (B, True)
    c) wanted B, own {jacket}, stored [A, C] (B not built yet)                           -> (B, False)
    d) wanted B, jacket NOT own, files of the jacket on A and C only (old shapes)        -> ("", False)
    e) wanted B, jacket NOT own, a file of the jacket on B, stored [A, B, C]             -> (B, True)
    f) wanted B, jacket in_body (meshed into B), files on B                              -> ("", False)
    g) wanted_figure raises                                                              -> ("", False)
[2] ``bodies(Demo, jacket)`` with three stored shapes A, B, C, the jacket fitted on all three plus the base, wanted
    B, own {jacket}: keys exactly ["plain", B], roles ["base", "current"], refit_block ["", ""]; no A, no C.
[3] Wanted = plain (case 1a) with the same three stored shapes: keys exactly ["plain"], role "base" — one body,
    so the client shows no selector (frontend: scripts/check_dialog_two_bodies.mjs).
[4] Wanted B not built (case 1c), the stand-in entry "missing": keys ["plain", B]; B's refit_block and reason =
    CURRENT_NOT_BUILT = "This body shape is not built yet — the Figure tab's Build makes it"; the base's "".
[5] A derived-shoe entry of the current body (Ruling A40) stays right after it: keys ["plain", B, B + "-derived"],
    roles base / current / current.
[6] ``garment_footwear._fits`` (the footwear rows) with stored [A, B, C], wanted B (own): body ids [bsig, B]; with
    B not stored: [bsig] (a row needs the stored body).
[7] Fails on the old code (1fb1f40bb, pinned): its fit_attempts.py lists every stored shape (``def _bodies_of(``)
    and has no ``dialog_shape``; its garment_footwear ``_fits`` loops over ``stored_outfit_bodies``.
"""
import os
import subprocess
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
BASELINE = "1fb1f40bb"
A, B, C = "ob0000000a", "ob0000000b", "ob0000000c"
BSIG = "base1234abcd"
FAILS: list = []


def check(label: str, got, want=True) -> None:
    ok = got == want
    print(f"  {'ok  ' if ok else 'FAIL'} {label}" + ("" if ok else f" — got {got!r}, want {want!r}"))
    if not ok:
        FAILS.append(label)


def run(tmp: Path) -> None:
    from app.core import figure, fit_attempts, garment_footwear, garment_store as gs, garments
    real = {}

    def put(obj, name, value):
        real.setdefault((obj, name), getattr(obj, name))
        setattr(obj, name, value)

    table = {"shape": B, "own": ("jacket",), "in_body": (), "stored": [A, B, C], "files": [A, B, C],
             "raise": False}

    def wanted(_c, **_k):
        if table["raise"]:
            raise RuntimeError("stub")
        return types.SimpleNamespace(shape=table["shape"], own=table["own"], in_body=table["in_body"])

    def groups(_c):
        root = tmp / "garments"
        return {("jacket", "0123456789ab"): [root / "jacket_0123456789ab.glb"]
                + [root / "bodies" / b / "jacket_0123456789ab.glb" for b in table["files"]]}

    def entry(_c, _i, body, _p, _n=None):
        return {"body": body, "key": body or "plain", "label": "Plain body" if not body else "Body shape (Blouse)",
                "status": "missing", "reason": "", "_shown": None}

    derived = {"on": False}

    def derived_entry(_c, _i, body, _p, _n=None):
        return {"body": body, "key": body + fit_attempts.DERIVED_KEY_SUFFIX, "status": "refused",
                "reason": "x", "_shown": None} if derived["on"] else None

    put(figure, "wanted_figure", wanted)
    put(gs, "stored_groups", groups)
    put(gs, "_garment_kind", lambda _i: "clothing")
    put(garment_footwear, "stored_outfit_bodies", lambda _c: list(table["stored"]))
    put(fit_attempts, "_entry", entry)
    put(fit_attempts, "_derived_entry", derived_entry)
    put(fit_attempts, "shape_names", lambda _c, profile=None: {})
    try:
        print("[1] dialog_shape")
        shape = lambda: fit_attempts.dialog_shape("Demo", "jacket", profile={})  # noqa: E731
        table.update(shape=BSIG)
        check("a) plain", shape(), ("", False))
        table.update(shape=B)
        check("b) own, stored", shape(), (B, True))
        table.update(stored=[A, C])
        check("c) own, not built", shape(), (B, False))
        table.update(own=(), stored=[A, B, C], files=[A, C])
        check("d) not own, only old shapes", shape(), ("", False))
        table.update(files=[B])
        check("e) not own, data on the current shape", shape(), (B, True))
        table.update(in_body=("jacket",))
        check("f) in the body", shape(), ("", False))
        table.update(in_body=(), own=("jacket",))
        table["raise"] = True
        check("g) raises", shape(), ("", False))
        table["raise"] = False

        print("[2] three stored shapes, wanted B")
        table.update(shape=B, own=("jacket",), stored=[A, B, C], files=[A, B, C])
        got = fit_attempts.bodies("Demo", "jacket", profile={})
        check("keys", [e["key"] for e in got], ["plain", B])
        check("roles", [e["role"] for e in got], ["base", "current"])
        check("refit_block", [e["refit_block"] for e in got], ["", ""])

        print("[3] wanted plain")
        table.update(shape=BSIG)
        got = fit_attempts.bodies("Demo", "jacket", profile={})
        check("keys", [(e["key"], e["role"]) for e in got], [("plain", "base")])

        print("[4] current body not built")
        table.update(shape=B, stored=[A, C])
        got = fit_attempts.bodies("Demo", "jacket", profile={})
        check("keys", [e["key"] for e in got], ["plain", B])
        check("CURRENT_NOT_BUILT", fit_attempts.CURRENT_NOT_BUILT,
              "This body shape is not built yet — the Figure tab's Build makes it")
        check("B refit_block + reason", (got[1]["refit_block"], got[1]["reason"]),
              (fit_attempts.CURRENT_NOT_BUILT, fit_attempts.CURRENT_NOT_BUILT))
        check("base refit_block", got[0]["refit_block"], "")

        print("[5] the current body's derived shoe")
        table.update(stored=[A, B, C])
        derived["on"] = True
        got = fit_attempts.bodies("Demo", "jacket", profile={})
        check("keys + roles", [(e["key"], e["role"]) for e in got],
              [("plain", "base"), (B, "current"), (B + "-derived", "current")])
        derived["on"] = False

        print("[6] the footwear rows")
        put(garment_footwear, "_fit_info", lambda *_a, **_k: {"status": "missing"})
        put(garments, "body_sha256", lambda _c, b: f"sha-{b}")
        rows = garment_footwear._fits("Demo", "jacket", "0123456789ab", (BSIG, "basesha"), {"status": "accepted"},
                                      profile={})
        check("stored B", [r["body_id"] for r in rows], [BSIG, B])
        table.update(stored=[A, C])
        rows = garment_footwear._fits("Demo", "jacket", "0123456789ab", (BSIG, "basesha"), {"status": "accepted"},
                                      profile={})
        check("B not stored", [r["body_id"] for r in rows], [BSIG])
    finally:
        for (obj, name), value in real.items():
            setattr(obj, name, value)


def old_code() -> None:
    print(f"[7] fails on the old code ({BASELINE})")

    def show(path: str) -> str:
        return subprocess.run(["git", "show", f"{BASELINE}:{path}"], cwd=ROOT, capture_output=True, text=True,
                              check=True).stdout
    fa = show("app/core/fit_attempts.py")
    check(f"{BASELINE}: every stored shape listed", "def _bodies_of(" in fa and "def dialog_shape(" not in fa)
    fw = show("app/core/garment_footwear.py")
    check(f"{BASELINE}: footwear rows per stored body", "for body_id in stored_outfit_bodies(character_name):" in fw)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="dialog-two-bodies-") as tmp:
        os.environ["STORAGE_DIR"] = str(Path(tmp) / "world")
        os.environ["INSTANCE_DIR"] = str(Path(tmp) / "instance")
        from app.core import paths
        paths.init(Path(tmp) / "world")
        paths.init_instance(Path(tmp) / "instance")
        run(Path(tmp))
        old_code()
    print(f"\n{len(FAILS)} failure(s)")
    for label in FAILS:
        print("  -", label)
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
