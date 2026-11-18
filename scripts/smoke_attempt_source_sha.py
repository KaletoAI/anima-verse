"""Smoke: "Use this" / re-gate offer only an image attempt made from the source image accepted NOW (A198, review 05
#3), and a shell piece's drafted left/right attempt must follow the current front like the back (review 05 #8).

Usage:
    ./.venv/bin/python scripts/smoke_attempt_source_sha.py

No server, no world DB: ``garment_store.garment_path`` maps (step, view) to temp files, ``_accepted`` is True.
Derived by hand from ``attempt_inputs``' rule ("another edit reads the source step's accepted image of the view and
must be made from it"):
  ghost front (source: the worn front, sha W):
    [1] sidecar source_sha256 == W                                  -> usable ("")
    [2] sidecar source_sha256 == sha of another worn image          -> EARLIER_SOURCE
        (pre-fix: usable — its created_at T3 is LATER than the worn final's T1 when worn #1 was taken by hand)
    [3] no source_sha256 (stored before A198), created_at after the source -> usable (legacy rule)
    [4] no source_sha256, created_at before the source               -> EARLIER_SOURCE
  worn LEFT (A185 side view, drafted from the worn front, sha F):
    [5] front_sha256 != F                                            -> EARLIER_FRONT (pre-fix: "" as a base edit)
    [6] front_sha256 == F, fit composite                             -> usable
  [7] ``_same_source``: unknown on either side -> True.

Pre-fix proof: at e846d7d02 [2] and [5] return "" (usable).
"""
import hashlib
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import garment_clothing, garment_images as gi, garment_store as gs  # noqa: E402

FAILED = []


def check(label, ok, detail=""):
    print(("OK   " if ok else "FAIL ") + label + ("" if ok else f"  -> {detail}"))
    if not ok:
        FAILED.append(label)


with tempfile.TemporaryDirectory(prefix="a198-source-") as tmp:
    root = Path(tmp)
    gs.garment_path = lambda c, i, f, part, step="", view="", **k: root / f"{step}_{view}.png"
    gi._kind_module = lambda item_id: garment_clothing
    gi._accepted = lambda path: True
    worn = root / "worn_front.png"
    worn.write_bytes(b"worn #1 taken by hand")
    gs.write_record(worn.with_suffix(".json"), {"accepted": True, "created_at": "2026-11-18T10:00:00+00:00"})
    W = hashlib.sha256(worn.read_bytes()).hexdigest()
    other = hashlib.sha256(b"worn #2").hexdigest()
    later, earlier = "2026-11-18T12:00:00+00:00", "2026-11-18T09:00:00+00:00"

    def why(step, view, sidecar):
        return gi.attempt_inputs("Demo", "item_x", "0123456789ab", step, view, sidecar)[0]

    check("[1] same source -> usable", why("ghost", "front", {"source_sha256": W, "created_at": later}) == "")
    got = why("ghost", "front", {"source_sha256": other, "created_at": later})
    check("[2] other source -> EARLIER_SOURCE", got == gi.EARLIER_SOURCE, got)
    check("[3] legacy, made later -> usable", why("ghost", "front", {"created_at": later}) == "")
    got = why("ghost", "front", {"created_at": earlier})
    check("[4] legacy, made earlier -> EARLIER_SOURCE", got == gi.EARLIER_SOURCE, got)
    got = why("worn", "left", {"front_sha256": other, "fit": "composite"})
    check("[5] side view from an older front -> EARLIER_FRONT", got == gi.EARLIER_FRONT, got)
    got = why("worn", "left", {"front_sha256": W, "fit": "composite"})
    check("[6] side view from the current front -> usable", got == "", got)
    check("[7] unknown -> same", gi._same_source({}, W) and gi._same_source({"source_sha256": W}, ""))

print()
print("FAILED: %d — %s" % (len(FAILED), "; ".join(FAILED)) if FAILED else "all OK")
sys.exit(1 if FAILED else 0)
