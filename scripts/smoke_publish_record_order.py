#!/usr/bin/env python3
"""A publish never pairs new bytes with the previous record (A207, review finding 05#7 — the footwear rule of
07#5 carried to ``garment_images._publish``, ``garment_from_worn`` and ``garments._publish_fit``).

Usage:
    ./.venv/bin/python scripts/smoke_publish_record_order.py

No server, no world DB, no Blender: a throwaway storage + instance root (``paths.init`` first); ``garment_path``,
the graft (``refit_pool.run``), the decimation and the later-step drops are stubs onto a temp folder. ``os.replace``
is spied: at the moment the new bytes take the published name, the spy notes whether that name's ``.json`` exists.

EXPECTED, from the rule "old record out -> bytes in -> new record written":
[R1] ``_publish`` of an attempt over a final with an OLD image + OLD record: at the swap no record exists; after
     it the final is the attempt's bytes and its record ``accepted`` with ``attempt`` 2.
     FAILS on the old code (commit 8fa2d763f): ``shutil.copyfile`` straight onto the final while the OLD record
     was still there (no swap at all — the spy sees nothing, the final was half-written in place).
[R2] the same publish with ``write_record`` crashing -> the error propagates; the final has NO record (reads as not
     accepted: ``garment_store.accepted_image`` False), never the new image under the OLD record; no temp file left.
[R3] ``_publish_fit`` over an OLD fit + OLD record: at the swap no record exists; afterwards the fit is the graft's
     bytes and the record the new one (``fit_version`` from the stub, 7).
     FAILS on the old code (commit 8fa2d763f): the record was still the OLD one at the swap.
[R4] ``garment_from_worn``'s publish (source order — the path needs the real worn/base images): the
     ``final.with_suffix(".json").unlink`` comes before ``os.replace(tmp, final)`` in ``make``'s source.
"""
import inspect
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = Path(tempfile.mkdtemp(prefix="smoke_publish_order_")).resolve()
os.environ["STORAGE_DIR"] = str(TMP / "storage")
os.environ["INSTANCE_DIR"] = str(TMP / "instance")
from app.core import paths  # noqa: E402
paths.init(str(TMP / "storage"))
paths.init_instance(str(TMP / "instance"))

from app.core import garment_images as gi  # noqa: E402
from app.core import garment_store as gs  # noqa: E402
from app.core import garments, refit_pool, garment_fit, fit_attempts, garment_from_worn  # noqa: E402
from app.blender import refine  # noqa: E402

fails = []


def check(tag, ok, msg=""):
    print(f"[{tag}] {'PASS' if ok else 'FAIL'} {msg}")
    if not ok:
        fails.append(tag)


G = TMP / "g"
G.mkdir()
seen = {}
_real_replace = os.replace


def spy(src, dst, *a, **k):
    d = Path(dst)
    if d.suffix in (".png", ".glb"):
        seen[d.name] = d.with_suffix(".json").exists()
    return _real_replace(src, dst, *a, **k)


os.replace = spy
gi._drop_later = lambda *a, **k: None

# R1
final, att = G / "final.png", G / "att.try2.png"
final.write_bytes(b"OLD")
final.with_suffix(".json").write_text(json.dumps({"accepted": True, "attempt": 1}))
att.write_bytes(b"NEW-IMAGE")
att.with_suffix(".json").write_text(json.dumps({"gate": {"ok": True}}))
seen.clear()
gi._publish("C", "item_x", "0123456789ab", "worn", "back", object(), att, final, [{"ok": True}], 2)
rec = json.loads(final.with_suffix(".json").read_text())
check("R1", seen.get("final.png") is False and final.read_bytes() == b"NEW-IMAGE" and rec.get("attempt") == 2
      and rec.get("accepted") is True, f"record at swap {seen.get('final.png')} rec {rec}")

# R2
final.write_bytes(b"OLD")
final.with_suffix(".json").write_text(json.dumps({"accepted": True, "attempt": 1}))
_real_wr = gs.write_record


def boom(path, record):
    raise OSError("disk full")


gs.write_record = boom
try:
    gi._publish("C", "item_x", "0123456789ab", "worn", "back", object(), att, final, [{"ok": True}], 2)
    raised = False
except OSError:
    raised = True
gs.write_record = _real_wr
temps = [p.name for p in G.glob(".final*")]
check("R2", raised and not final.with_suffix(".json").exists() and not gs.accepted_image(final) and temps == [],
      f"raised {raised} record {final.with_suffix('.json').exists()} temps {temps}")

# R3
fitp, lowp = G / "fit.glb", G / "low" / "fit.glb"
fitp.write_bytes(b"OLD-FIT")
fitp.with_suffix(".json").write_text(json.dumps({"old": True}))


def garment_path(c, item, fsig, part, body=""):
    return fitp if part == "fit" else lowp


gs.garment_path = garment_path


def fake_run(fn, rigged, garment, name, meta, out, material_overrides=None):
    Path(out).write_bytes(b"NEW-FIT")
    return 100


refit_pool.run = fake_run
garment_fit.fit_version_for = lambda kind, method: 7
refine.lod_ratio = lambda kind: 0.5
refine.decimate_to = lambda *a, **k: {"ok": False, "error": "stub"}
fit_attempts.drop = lambda *a, **k: None


class R:
    garment = None


seen.clear()
garments._publish_fit("C", "item_x", "clothing", "0123456789ab", "bsig", b"", R(), {"method": "m"},
                      schedule=False)
rec = json.loads(fitp.with_suffix(".json").read_text())
check("R3", seen.get("fit.glb") is False and fitp.read_bytes() == b"NEW-FIT" and rec.get("fit_version") == 7
      and "old" not in rec, f"record at swap {seen.get('fit.glb')} rec {rec}")

# R4
src = inspect.getsource(garment_from_worn)
i_unlink = src.find('final.with_suffix(".json").unlink(missing_ok=True)')
i_swap = src.find("os.replace(tmp, final)")
check("R4", 0 <= i_unlink < i_swap, f"unlink at {i_unlink}, swap at {i_swap}")

os.replace = _real_replace
print("FAIL" if fails else "ALL PASS", fails)
sys.exit(1 if fails else 0)
