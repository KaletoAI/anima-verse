"""A210 smoke: refused attempts of a shell piece's base view variant stay on disk, are listed, and "Use this one"
makes one the variant until the base view changes.

Usage:
    ./.venv/bin/python scripts/smoke_shell_base_view_accept.py

Runs without the server, on a temp storage dir; the base view lookup (``_views_of``) and the variant path
(``path_of``) are pointed at that dir, everything else is the module's own code.

Expected values, derived by hand from the spec (A210 + ``shell_base_views`` docstring):
- attempt N of variant ``arms_up`` of ``tpose_left_<bsig>`` lives at ``tpose_left_<bsig>.arms_up.try<N>.png`` — and
  ``ensure`` renders to ``stem + ".png"`` with ``stem = kept.with_suffix("")``, which must give that same path back
  (the old ``target.with_name(stem.try N).with_suffix(".png")`` cut ".tryN" and gave the variant's own path);
- a run with 2 refused attempts lists 1 view, ``accepted_by_user`` 0, attempts [1, 2] both usable;
- "Use this one" on attempt 1: the variant's bytes equal try1's bytes, ``current`` returns the variant path, the
  record says ``accepted`` and ``user_accepted``; the list then shows the view with ``accepted_by_user`` 1 and attempt
  1 ``in_use``;
- review M1: after picking attempt 1, ``current_sha`` is sha(b"try1"); picking attempt 2 makes it sha(b"try2"), so a
  worn view recorded with the attempt-1 sha is not ``_same_variant`` any more (stale), one without a sha still is;
- review M2: with ``garment_store.char_lock`` held, "Use this one" raises ``UseBusy``; over a variant that passed its
  own gate (accepted, no user_accepted) it raises ``AttemptUnusable``;
- review L1: ``_clear_attempts`` removes try1/try2 + their sidecars + attempts.json; an attempt recorded as a render
  failure is not usable even with a file on disk;
- gate (A210, min 0.70, margin 0.05): 0.74 vs 0.666 passes (diff 0.074); 0.588 vs 0.736 fails (below 0.70 and
  worse than rest); 0.72 vs 0.69 fails on the margin (diff 0.03); 0.70 vs 0.65 passes (exactly both limits);
- new base view content: ``current`` is None, the list is empty (the stored attempts were made from the old base),
  and "Use this one" raises ``AttemptUnusable``.
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

tmp = Path(tempfile.mkdtemp(prefix="smoke_a210_"))
os.environ["STORAGE_DIR"] = str(tmp)
from app.core import paths  # noqa: E402
paths.init(str(tmp))

from app.core import shell_base_views as sbv  # noqa: E402

FAILS = []


def check(cond, label):
    print(("ok   " if cond else "FAIL ") + label)
    if not cond:
        FAILS.append(label)


refs = tmp / "refs"
(refs / sbv.VARIANT_DIR).mkdir(parents=True)
base = refs / "tpose_left_bX.png"
base.write_bytes(b"base-view-one")
BSIG = "bX"


def path_of(character_name, view, bsig, variant):
    return refs / sbv.VARIANT_DIR / f"tpose_{view}_{bsig}.{variant}.png"


sbv.path_of = path_of
sbv._views_of = lambda c, i, p: [("left", "arms_up", BSIG, base)]

kept = sbv.attempt_path("C", "left", BSIG, "arms_up", 1)
check(kept.name == "tpose_left_bX.arms_up.try1.png", f"attempt path {kept.name}")
check(kept.with_suffix("").parent / (kept.with_suffix("").name + ".png") == kept, "ensure's render stem round-trips")

prompt = sbv.edit_text("arms_up")[0]
for n in (1, 2):
    sbv.attempt_path("C", "left", BSIG, "arms_up", n).write_bytes(f"try{n}".encode())
records = [{"attempt": 1, "ok": False, "reasons": ["the arms do not match the raised pose (silhouette IoU 0.74 posed vs "
                                                   "0.666 at rest; needs ≥ 0.8 and better than at rest)"]},
           {"attempt": 2, "ok": False, "reasons": ["the arms do not match the raised pose (IoU 0.588)"]}]
sbv._write_attempts("C", "left", BSIG, "arms_up", base, prompt, records)

listed = sbv.refusals("C", "item")
check(len(listed) == 1 and listed[0]["accepted_by_user"] == 0, f"one refused view, none taken: {listed}")
check([a["attempt"] for a in listed[0]["attempts"]] == [1, 2] and all(a["usable"] for a in listed[0]["attempts"]),
      "attempts 1 and 2 listed and usable")
check(sbv.current("C", "left", BSIG, "arms_up", base) is None, "nothing current before the click")

res = sbv.use_attempt("C", "item", "left", 1)
target = path_of("C", "left", BSIG, "arms_up")
check(res["attempt"] == 1 and res["user_accepted"], f"use result {res}")
check(target.read_bytes() == b"try1", "variant bytes are attempt 1's")
check(sbv.current("C", "left", BSIG, "arms_up", base) == target, "current holds the user's pick")
rec = sbv._record(target)
check(rec.get("accepted") is True and rec.get("user_accepted") is True, "record accepted + user_accepted")
listed = sbv.refusals("C", "item")
check(len(listed) == 1 and listed[0]["accepted_by_user"] == 1
      and [a["in_use"] for a in listed[0]["attempts"]] == [True, False], f"pick shown in use: {listed}")

import hashlib  # noqa: E402
from app.core import garment_images as gi, garment_shell as gsh, garment_store as gst  # noqa: E402
sha1, sha2 = hashlib.sha256(b"try1").hexdigest(), hashlib.sha256(b"try2").hexdigest()
check(sbv.current_sha("C", "item", "left") == sha1, "current_sha is attempt 1's")
sbv.use_attempt("C", "item", "left", 2)
check(sbv.current_sha("C", "item", "left") == sha2, "after picking attempt 2 current_sha is attempt 2's")
check(not gi._same_variant({"base_variant": "arms_up", "base_variant_sha256": sha1}, "arms_up", sha2),
      "a worn view made on attempt 1 is not the same variant any more")
check(gi._same_variant({"base_variant": "arms_up"}, "arms_up", sha2), "a worn view without a sha counts as same")
check(not gi._same_variant({"base_variant": ""}, "arms_up", sha2), "another variant name is not the same")

lock = gst.char_lock("C")
lock.acquire()
try:
    sbv.use_attempt("C", "item", "left", 1)
    check(False, "use while a run writes is refused")
except sbv.UseBusy:
    check(True, "use while a run writes is refused")
finally:
    lock.release()
rec = sbv._record(target)
rec.pop("user_accepted")
target.with_suffix(".json").write_text(__import__("json").dumps(rec), encoding="utf-8")
try:
    sbv.use_attempt("C", "item", "left", 1)
    check(False, "use over a variant that passed its gate is refused")
except sbv.AttemptUnusable:
    check(True, "use over a variant that passed its gate is refused")

check(gsh.arms_up_ok(0.74, 0.666), "gate: 0.74 vs 0.666 passes")
check(not gsh.arms_up_ok(0.588, 0.736), "gate: 0.588 vs 0.736 fails")
check(not gsh.arms_up_ok(0.72, 0.69), "gate: 0.72 vs 0.69 fails on the margin")
check(gsh.arms_up_ok(0.70, 0.65), "gate: 0.70 vs 0.65 passes at both limits")

base.write_bytes(b"base-view-two")
check(sbv.current("C", "left", BSIG, "arms_up", base) is None, "a new base view voids the pick")
check(sbv.refusals("C", "item") == [], "attempts of the old base are not listed")
try:
    sbv.use_attempt("C", "item", "left", 2)
    check(False, "use on a stale attempt refused")
except sbv.AttemptUnusable:
    check(True, "use on a stale attempt refused")

# L1
sbv._write_attempts("C", "left", BSIG, "arms_up", base, prompt,
                    [{"attempt": 1, "ok": False, "reasons": ["render failed"], "render_failed": True},
                     {"attempt": 2, "ok": False, "reasons": ["x"]}])
sbv.attempt_path("C", "left", BSIG, "arms_up", 1).write_bytes(b"stale")
listed = sbv.refusals("C", "item")
check([a["usable"] for a in listed[0]["attempts"]] == [False, True], f"a render failure is not usable: {listed}")
sbv.attempt_path("C", "left", BSIG, "arms_up", 1).with_suffix(".json").write_text("{}")
sbv._clear_attempts("C", "left", BSIG, "arms_up")
left = sorted(p.name for p in (refs / sbv.VARIANT_DIR).iterdir() if ".try" in p.name or "attempts" in p.name)
check(left == [], f"run start clears the old attempts: {left}")

print("FAILED" if FAILS else "ALL OK")
sys.exit(1 if FAILS else 0)
