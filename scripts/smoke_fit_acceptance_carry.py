#!/usr/bin/env python3
"""Ruling A72b: a user's acceptance of a refused clothing fit CARRIES OVER to a refit of the same piece on the same
body when the refusal is the same set of gates, each value no worse than the accepted one by more than
``fit_attempts.CARRY_TOLERANCE`` (0.005); an acceptance the earlier rule voided is recovered once from the log.

Usage:
    ./.venv/bin/python scripts/smoke_fit_acceptance_carry.py

Runs against a THROWAWAY storage + instance directory — no world, no hub, no Blender, no server. ``fit_attempts``
and ``garment_store`` (paths, records, ``stored_groups``) are real; stubbed: ``fit_attempts._current`` ("" = the
attempt is current, the readers' rule is ``smoke_fit_user_accept``'s), ``refine.decimate_to`` (copies the file),
``garment_assembly.schedule`` (records the character).

Fixture: "Demo", clothing item ``item_jeans`` (fsig F = 825e34df4aaf), the plain body ("") and the body shape
``ob0000000a``. A refusal's gates = ``{reasons, limits (CLOTHING_GATES kinds), metrics}`` as ``garments`` passes
them. The plain body's fit path holds the fit "old-fit" (the one an acceptance displaces); the failure record of
the first refusal is R0 = {"error": "fit refused — deep_push_share 0.1512 > 0.12 (...)"}.

Expected, derived by hand from the ruling:

[1] ``carries`` (accepted deep_push_share 0.1512, a "max" gate):
      new 0.1512 -> True (same); 0.156 -> True (+0.0048 <= 0.005); 0.157 -> False (+0.0058);
      0.10 -> True (better); {deep 0.1512, max_push_m 0.11} -> False (another set); {} -> False;
    a "min" gate (largest_component_share accepted 0.85): 0.846 -> True (-0.004), 0.844 -> False (-0.006);
    ``refused_values`` of a limb refusal ("left leg: off the thigh — ...", no such limit) -> None, and
    ``carries(None, x)`` -> False.
[2] Attempt A (bytes "attempt-A", deep 0.1512): ``store(carry=True)`` -> False (no acceptance yet). The user
    accepts it (``_accept_locked``): the fit path holds "attempt-A", ``user_accepted.attempt_sha256`` = sha(A),
    prev = "old-fit", the failure record is gone.
[3] The refit makes attempt B (bytes "attempt-B", deep 0.1512 — the fit version 14 refit of 2026-11-14):
    ``store(carry=True)`` -> True; the fit path holds "attempt-B", ``accepted`` True, ``user_accepted``: ``at``
    unchanged, ``attempt_sha256`` sha(B), ``failure`` R0 kept, ``carried`` one entry (how "refit", from sha(A));
    prev still "old-fit"; no failure record; the attempt record is B's.
[4] Attempt C (deep 0.157, +0.0058 worse): -> False; the acceptance is void: the fit path holds "old-fit" again,
    the failure record R0 is back, no prev.
[5] Re-accepted C, then attempt D with the same values but ``carry=False`` (a caller that does not carry,
    footwear): -> False, void ("old-fit" back).
[6] Re-accepted D, then a limb refusal E (no numeric gate): -> False, void.
[7] Body shape ``ob0000000a``: accepted attempt G (deep 0.225), refit H (deep 0.225, bytes differ) -> True, the
    body's fit path holds H; ``undo`` -> the body's fit path empty (nothing was displaced there), the failure back.
[8] ``voided_acceptances`` on the log lines (oldest first) — key K = ("Demo", item_jeans, F, ""):
      K accepted (E1 = deep 0.1512), K void + its own undo line          -> listed with E1
      coat: accepted, void + undo, accepted again                        -> not listed
      cap: accepted, the user's own undo                                 -> not listed
      shirt: accepted, carried over                                      -> not listed
    ``logged_refusal(E1)`` -> reasons ["deep_push_share 0.1512 > 0.12 (share ...)"], limits {deep: [max, 0.12]},
    metrics {deep: 0.1512}; a limb error -> None.
[9] ``recover_voided_acceptances`` with that log under logs/archive/main_20261114_221141.log + logs/main.log, the
    plain body holding "old-fit" and the CURRENT attempt J (deep 0.1512, no acceptance): -> [("Demo", item_jeans,
    "")]; the fit path holds J with ``user_accepted`` (carried how "recovered from the log", reasons of E1), prev =
    "old-fit", the failure record gone; the assembly scheduled for Demo once. A second call -> [] (once per world:
    world_kv marker); ``force`` -> [] as well (J is accepted now). With J worse (deep 0.16) a forced run recovers
    nothing.
"""
import hashlib
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FAILS = []
FSIG = "825e34df4aaf"
ITEM = "item_jeans"
SHAPE = "ob0000000a"
LABEL = "share of vertices pushed out more than 3 cm"


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def deep(value):
    return f"deep_push_share {value:g} > 0.12 ({LABEL})"


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="fit-accept-carry-") as tmp:
        root = Path(tmp)
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "instance")
        import shutil
        from app.blender import refine
        from app.core import db, fit_attempts as fa, garment_assembly, garment_fit, garment_store as gs
        from app.models import character as character_model
        db.init_schema()
        character_model.get_character_dir("Demo", create=True)
        refine.decimate_to = lambda src, _target, dst, **_kw: (shutil.copyfile(src, dst), {"ok": True, "tris": 1})[1]
        scheduled = []
        garment_assembly.schedule = lambda name, *_a, **_kw: scheduled.append(name)
        fa._current = lambda *_a, **_kw: ""
        limits = {k: [kind, limit] for k, (kind, limit, _l) in garment_fit.CLOTHING_GATES.items()}
        FV = garment_fit.FIT_VERSION["clothing"]

        def v(**values):
            return {k: (kind, float(x)) for k, (kind, x) in values.items()}

        print("[1] carries")
        acc = v(deep_push_share=("max", 0.1512))
        for new, want in ((0.1512, True), (0.156, True), (0.157, False), (0.10, True)):
            check(f"deep {new}", fa.carries(acc, v(deep_push_share=("max", new))), want)
        check("another set", fa.carries(acc, v(deep_push_share=("max", 0.1512), max_push_m=("max", 0.11))), False)
        check("empty", fa.carries(acc, {}), False)
        acc_min = v(largest_component_share=("min", 0.85))
        check("min 0.846", fa.carries(acc_min, v(largest_component_share=("min", 0.846))), True)
        check("min 0.844", fa.carries(acc_min, v(largest_component_share=("min", 0.844))), False)
        limb = "left leg: off the thigh — 0.1478 of its vertices beyond the limb + 4 cm (source 0.0, limit +0.1)"
        check("limb refusal has no values", fa.refused_values([limb], {"limits": limits}, {}), None)
        check("carries(None, x)", fa.carries(None, acc), False)

        def path(part, body=""):
            return gs.garment_path("Demo", ITEM, FSIG, part, body=body)

        fit, prev, failed = path("fit"), path(fa.PREV), path("failed")
        fit.parent.mkdir(parents=True, exist_ok=True)
        R0 = {"error": "fit refused — " + deep(0.1512), "step": "fit"}

        def reset_plain():
            for p in (fit, fit.with_suffix(".json"), prev, prev.with_suffix(".json"), failed):
                p.unlink(missing_ok=True)
            fit.write_bytes(b"old-fit")
            gs.write_record(fit.with_suffix(".json"), {"accepted": True, "kind": "clothing", "item_id": ITEM,
                                                       "fsig": FSIG, "fit_version": FV - 1})
            gs.write_record(failed, R0)

        def attempt(data: bytes, reasons, metrics, *, body="", carry=True):
            src = root / "attempt.glb"
            src.write_bytes(data)
            gates = {"ok": False, "reasons": list(reasons), "limits": limits, "metrics": dict(metrics)}
            return fa.store("Demo", ITEM, FSIG, body=body, kind="clothing",
                            record={"kind": "clothing", "item_id": ITEM, "fsig": FSIG, "fit_version": FV,
                                    "metrics": dict(metrics), "body_id": body or "base0123abcd"},
                            error="fit refused — " + "; ".join(reasons), gates=gates, glb=src, tris=10, carry=carry)

        def accept(body=""):
            with fa._lock("Demo", body):
                fa._accept_locked("Demo", ITEM, body, {})

        def block(body=""):
            return gs.read_record(path("fit", body).with_suffix(".json")).get("user_accepted") or {}

        def read(p):
            return p.read_bytes() if p.is_file() else None

        print("[2] the first acceptance")
        reset_plain()
        check("A stored, nothing to carry", attempt(b"attempt-A", [deep(0.1512)], {"deep_push_share": 0.1512}), False)
        accept()
        check("fit = A", read(fit), b"attempt-A")
        check("accepted sha", block().get("attempt_sha256"), sha(b"attempt-A"))
        check("prev = old-fit", read(prev), b"old-fit")
        check("failure moved into the block", (failed.is_file(), (block().get("failure") or {}).get("error")),
              (False, R0["error"]))
        at = block().get("at")

        print("[3] the refit keeps the same refusal -> carried")
        check("B carried", attempt(b"attempt-B", [deep(0.1512)], {"deep_push_share": 0.1512}), True)
        rec = gs.read_record(fit.with_suffix(".json"))
        check("fit = B", read(fit), b"attempt-B")
        check("accepted", rec.get("accepted"), True)
        check("block", (block().get("at") == at, block().get("attempt_sha256"),
                        (block().get("failure") or {}).get("error"), block().get("fit_version")),
              (True, sha(b"attempt-B"), R0["error"], FV))
        check("carried", [(c.get("how"), c.get("from_attempt_sha256")) for c in block().get("carried") or []],
              [("refit", sha(b"attempt-A"))])
        check("prev still old-fit", read(prev), b"old-fit")
        check("no failure record", failed.is_file(), False)
        check("the attempt is B", (fa.attempt_of("Demo", ITEM, "")[1].get("attempt") or {}).get("glb_sha256"),
              sha(b"attempt-B"))

        print("[4] worse by 0.0058 -> void")
        check("C not carried", attempt(b"attempt-C", [deep(0.157)], {"deep_push_share": 0.157}), False)
        check("fit = old-fit", read(fit), b"old-fit")
        check("failure R0 back", gs.read_record(failed).get("error"), R0["error"])
        check("no prev", prev.is_file(), False)

        print("[5] a caller that does not carry -> void")
        accept()
        check("accepted C", block().get("attempt_sha256"), sha(b"attempt-C"))
        check("D, carry False", attempt(b"attempt-D", [deep(0.157)], {"deep_push_share": 0.157}, carry=False), False)
        check("fit = old-fit", read(fit), b"old-fit")

        print("[6] a limb refusal -> void")
        accept()
        check("accepted D", block().get("attempt_sha256"), sha(b"attempt-D"))
        check("E limb", attempt(b"attempt-E", [limb], {"deep_push_share": 0.05}), False)
        check("fit = old-fit", read(fit), b"old-fit")

        print("[7] a body shape")
        bfit = path("fit", SHAPE)
        check("G stored", attempt(b"attempt-G", [deep(0.225)], {"deep_push_share": 0.225}, body=SHAPE), False)
        accept(SHAPE)
        check("body fit = G", read(bfit), b"attempt-G")
        check("H carried", attempt(b"attempt-H", [deep(0.225)], {"deep_push_share": 0.225}, body=SHAPE), True)
        check("body fit = H", read(bfit), b"attempt-H")
        fa.undo("Demo", ITEM, SHAPE)
        check("undo: the body's fit path empty", bfit.is_file(), False)

        print("[8] voided_acceptances / logged_refusal")
        e1 = "fit refused — " + deep(0.1512)
        lines = [
            f"22:04:15 [fit_attempts] INFO Fit Demo/{ITEM} ({FSIG}) on plain body accepted by the user (refused: {e1})",
            f"23:47:28 [fit_attempts] INFO Fit acceptance Demo/{ITEM} ({FSIG}) on plain body void: a new attempt differs",
            f"23:47:28 [fit_attempts] INFO Fit Demo/{ITEM} ({FSIG}) on plain body: the user's acceptance undone",
            f"10:00:00 [fit_attempts] INFO Fit Demo/item_coat ({FSIG}) on plain body accepted by the user (refused: {e1})",
            f"10:00:01 [fit_attempts] INFO Fit acceptance Demo/item_coat ({FSIG}) on plain body void: a new attempt differs",
            f"10:00:01 [fit_attempts] INFO Fit Demo/item_coat ({FSIG}) on plain body: the user's acceptance undone",
            f"10:00:05 [fit_attempts] INFO Fit Demo/item_coat ({FSIG}) on plain body accepted by the user (refused: {e1})",
            f"10:01:00 [fit_attempts] INFO Fit Demo/item_cap ({FSIG}) on plain body accepted by the user (refused: {e1})",
            f"10:01:05 [fit_attempts] INFO Fit Demo/item_cap ({FSIG}) on plain body: the user's acceptance undone",
            f"10:02:00 [fit_attempts] INFO Fit Demo/item_shirt ({FSIG}) on {SHAPE} accepted by the user (refused: {e1})",
            f"10:02:05 [fit_attempts] INFO Fit Demo/item_shirt ({FSIG}) on {SHAPE}: the user's acceptance carried over "
            f"to the refit (refused: {e1})",
        ]
        check("voided", fa.voided_acceptances(lines), {("Demo", ITEM, FSIG, ""): e1})
        check("logged_refusal", fa.logged_refusal(e1),
              {"reasons": [deep(0.1512)], "gates": {"limits": {"deep_push_share": ["max", 0.12]},
                                                    "metrics": {"deep_push_share": 0.1512}}})
        check("limb error", fa.logged_refusal("fit on the outfit body refused — " + limb), None)

        print("[9] the recovery")
        logs = root / "logs"
        (logs / "archive").mkdir(parents=True)
        (logs / "archive" / "main_20261114_221141.log").write_text(lines[0] + "\n" + "22:05:00 [garments] INFO x\n")
        (logs / "main.log").write_text("\n".join(lines[1:3]) + "\n")
        reset_plain()
        for files in fa._attempt_files("Demo", ITEM, "").values():
            fa._remove_attempt(files)
        check("J stored, nothing to carry", attempt(b"attempt-J", [deep(0.1512)], {"deep_push_share": 0.1512}),
              False)
        check("recovered", fa.recover_voided_acceptances(logs), [("Demo", ITEM, "")])
        check("fit = J", read(fit), b"attempt-J")
        check("block", (block().get("reasons"), [c.get("how") for c in block().get("carried") or []],
                        [c.get("from_reasons") for c in block().get("carried") or []]),
              ([deep(0.1512)], ["recovered from the log"], [[deep(0.1512)]]))
        check("prev = old-fit, failure gone", (read(prev), failed.is_file()), (b"old-fit", False))
        check("assembly scheduled", scheduled, ["Demo"])
        check("once per world", fa.recover_voided_acceptances(logs), [])
        check("forced: J is accepted already", fa.recover_voided_acceptances(logs, force=True), [])
        reset_plain()
        for files in fa._attempt_files("Demo", ITEM, "").values():
            fa._remove_attempt(files)
        attempt(b"attempt-K", [deep(0.16)], {"deep_push_share": 0.16})
        check("forced, K worse: nothing", fa.recover_voided_acceptances(logs, force=True), [])
        check("fit = old-fit", read(fit), b"old-fit")

    print("\nALL OK" if not FAILS else f"\nFAILED ({len(FAILS)}): " + ", ".join(FAILS))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
