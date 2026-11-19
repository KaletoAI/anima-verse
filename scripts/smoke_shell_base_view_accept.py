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

base.write_bytes(b"base-view-two")
check(sbv.current("C", "left", BSIG, "arms_up", base) is None, "a new base view voids the pick")
check(sbv.refusals("C", "item") == [], "attempts of the old base are not listed")
try:
    sbv.use_attempt("C", "item", "left", 2)
    check(False, "use on a stale attempt refused")
except sbv.AttemptUnusable:
    check(True, "use on a stale attempt refused")

print("FAILED" if FAILS else "ALL OK")
sys.exit(1 if FAILS else 0)
