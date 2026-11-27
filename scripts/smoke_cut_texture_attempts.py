#!/usr/bin/env python3
"""Smoke: attempt 2 of a cut-texture job runs on the routing chain's SECOND entry, in that backend's dialect
(docs/edit-prompts.md §7, ``routing.gate_attempts``, ``garment_cut_texture.generate``).

Usage:
    ./.venv/bin/python scripts/smoke_cut_texture_attempts.py

Throwaway STORAGE_DIR / INSTANCE_DIR and config, no world DB, no hub, no server, no network (socket connects are
refused and counted). The code under test is the REAL chain: ``garment_cut_texture.generate`` -> ``_routed_render``
-> ``routing.run_routed`` (rules stubbed to the chain below) -> a ``BackendPool`` of two fake ``ImageBackend``s ->
``ImageBackend.generate`` (with the edit-prompt normaliser) -> ``_generate`` (the fake answer) -> ``post_job`` (the
real gates). Stubbed around it: the cut pattern, the item picture, the piece name, ``figure.invalidate``.

Fixture: islands front (20..200)^2 and sleeve_l x 20..100 / y 220..300 on a 400 px atlas (no back panel -> one job,
"front"); item 1200 x 1200 with an (120, 60, 30) block (no upscale: >= 1024). Fake backends: "a1" model
"P-H3-Image" (dialect picture_edit), "b2" model "MiniMax-H3-Image" (picture_subject), both img2img, 2 slots. A GOOD
answer is the template with every non-white pixel set to (120, 60, 30) (passes the gates); a WHITE answer is all
white (coverage 0.00 < 0.97 -> "rejected").

Expected, derived by hand from the rules (``CUT_ATTEMPTS`` 2, ``ATTEMPT_SEED_STEP`` 1000, ``attempt_order``):

[1] chain [a1, b2]; a1 answers WHITE, b2 GOOD:
    - renders: a1 then b2; the seeds s and s + 1000 (s = int(csig[:8], 16) % 2^31);
    - a1 got "Edit <Picture 1>. Texture the sewing pattern in <Picture 1> with the fabric of the T-shirt in
      <Picture 2>. …" (picture_edit), b2 "The flat sewing pattern of a T-shirt on a white background in <Picture 1> is
      <Subject 1>; …" (picture_subject, the normaliser leaves both as they are);
    - record "ready"; ``jobs.front.attempts`` = [{1, a1, picture_edit, "rejected"}, {2, b2, picture_subject,
      "ready"}]; attempt 2's routing meta ``attempt_entry`` {"attempt": 2, "aimed_position": 2, "position": 2} and no
      ``fallback_from``; attempt 1's has neither;
    - the job's top-level fields are attempt 2's (backend b2, dialect picture_subject, attempt 2);
    - files ``.raw_front.a1.png`` (white) and ``.raw_front.a2.png``; ``.raw_front.png`` = the a2 bytes;
    - ``recompose(accept="front", attempt=1)`` makes attempt 1 the job's answer: ``.raw_front.png`` = the a1 bytes,
      the entry's backend a1, dialect picture_edit, attempt 1 (the white answer is then forced through, accepted).
[2] chain [a1, b2]; a1 GOOD: one render (a1), ``attempts`` has one entry, no attempt_entry, "ready".
[3] chain [a1, b2]; a1 raises BackendBusyError: "failed", reason "Front: The backend is busy …", b2 never called,
    ``attempts`` = [{1, "failed"}] — a failure never renders attempt 2.
[4] chain [a1] (one entry); both answers WHITE: two renders on a1 with seeds s and s + 1000; "rejected"; attempt 2's
    ``attempt_entry`` {"attempt": 2, "aimed_position": 1, "position": 1} (clamped to the only entry), no fallback_from.
[5] chain [a1, b2]; a1 WHITE, b2 busy: attempt 2 failed -> the job keeps attempt 1's "rejected" answer (the record
    "rejected", not "failed"); ``attempts`` [rejected, failed]; ``.raw_front.png`` = the a1 bytes.
[6] ``job_plan`` of the front-only pattern (nothing re-used): front 1, total 1, max 1 + 1 = 2.
[7] ``gate_attempts(3)``: ``current_attempt()`` inside the body 1, 2, 3; after a ``break`` in attempt 2 and after the
    loop it is 1 again.
"""
import io
import json
import os
import socket
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

FAILS = []
CONNECTS = []


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}"[:300] + ("" if ok else f" — expected {want!r}"[:300]))
    if not ok:
        FAILS.append(label)


def _no_connect(*a, **k):
    CONNECTS.append(a)
    raise OSError("network disabled in this smoke")


socket.create_connection = _no_connect

CHAR, ITEM = "Tilda", "shirt"
A = (120, 60, 30)


def isl(name, x0, y0, x1, y1):
    return {"name": name, "verts_px": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]], "tris": [[0, 1, 2], [0, 2, 3]],
            "bbox_px": [x0, y0, x1, y1]}


PAYLOAD = {"atlas_px": 400, "px_per_cm": 10.0, "seams": [],
           "islands": [isl("front", 20, 20, 200, 200), isl("sleeve_l", 20, 220, 100, 300)]}


def good(params):
    with Image.open(params["reference_images"]["input_reference_image_1"]) as t:
        arr = np.asarray(t.convert("RGB")).copy()
    arr[(255 - arr.astype(int)).max(-1) > 24] = A
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="PNG")
    return buf.getvalue()


def white(params):
    buf = io.BytesIO()
    Image.new("RGB", (400, 400), (255, 255, 255)).save(buf, format="PNG")
    return buf.getvalue()


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="smoke-cut-attempts-"))
    os.environ["STORAGE_DIR"] = str(root / "world")
    os.environ["INSTANCE_DIR"] = str(root / "instance")
    os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
    from app.core import paths
    paths.init(root / "world")
    paths.init_instance(root / "instance")
    paths.get_config_path().parent.mkdir(parents=True, exist_ok=True)
    paths.get_config_path().write_text("{}")
    from app.core import config
    config.load(paths.get_config_path(), instance_path=root / "instance" / "config.json")

    from app.core import figure
    from app.core import garment_cut_texture as gct
    from app.imagegen import base as _base
    from app.imagegen import routing
    from app.imagegen import service as _service
    from app.imagegen.base import BackendBusyError, ImageBackend
    from app.imagegen.selection import BackendPool

    class Fake(ImageBackend):
        def __init__(self, name, model):
            super().__init__(name, "http://localhost", 0.0, "fake", "FAKE_CUT_ATTEMPT_")
            self.model, self.category, self.ref_slot_count = model, "img2img", 2
            self._available = True
            self.prompt_char_limit = 100000
            self.answer = good
            self.calls = []

        def check_availability(self):
            return True

        def _generate(self, prompt, negative_prompt, params):
            self.calls.append({"prompt": prompt, "seed": params.get("seed")})
            if self.answer == "busy":
                raise BackendBusyError(f"{self.name} busy")
            return [self.answer(params)]

    RULES = {}
    routing._rules = lambda occasion: list(RULES.get(occasion, []))
    routing._character_spec = lambda occ_def, character, overrides=None: ""
    _base.image_overflow_after_seconds = lambda: 0

    class Service:
        def __init__(self, pool):
            self.pool = pool

        def run_on_backend(self, b, op):
            return self.pool.run_on_backend(b, op=op)

        def run_on_backend_channel(self, b, fn, **k):
            return fn()

    # the cut, the item, the piece
    islands_path = root / "islands.json"
    islands_path.write_text(json.dumps(PAYLOAD))
    item_png = root / "item.png"
    im = Image.new("RGBA", (1200, 1200), (0, 0, 0, 0))
    im.paste((*A, 255), (200, 200, 1000, 1000))
    im.save(item_png)
    cut = root / "cut"
    gct.cut_dir = lambda c: cut
    gct._ready_pattern = lambda c, i: {"islands_sha": "isl000", "islands_path": islands_path, "cut_sig": "cutsig"}
    gct._item_path = lambda iid: item_png
    gct._item_matte = lambda: None
    gct.piece_name = lambda iid: "T-shirt"
    gct.sleeve_print_of = lambda iid: "plain"
    gct.csig_for = lambda c, i, sha, islands=None, has_back_panel=None, **kw: gct.csig(sha, gct._item_sha(i), "")
    gct.current_csig = lambda c, i: gct.csig("isl000", gct._item_sha(i), "")
    figure.invalidate = lambda *a, **k: None

    def run(chain, a1_answer, b2_answer):
        a1, b2 = Fake("a1", "P-H3-Image"), Fake("b2", "MiniMax-H3-Image")
        a1.answer, b2.answer = a1_answer, b2_answer
        pool = BackendPool([a1, b2])
        _service.get_image_service = lambda: Service(pool)
        RULES["garment_cut_texture"] = list(chain)
        for f in cut.glob("*") if cut.is_dir() else []:
            f.unlink()
        rec = gct.generate(CHAR, ITEM, apply_after=False)
        return rec, a1, b2

    sig = gct.csig("isl000", gct._item_sha(ITEM), "")
    seed = int(sig[:8], 16) % 2 ** 31
    stem = gct._stem(CHAR, ITEM, sig)

    print("[1] attempt 1 rejected on a1 -> attempt 2 on b2")
    rec, a1, b2 = run(["a1", "b2"], white, good)
    check("[1] renders a1 then b2, seeds s / s+1000",
          ([c["seed"] for c in a1.calls], [c["seed"] for c in b2.calls]), ([seed], [seed + 1000]))
    check("[1] a1 prompt picture_edit", a1.calls[0]["prompt"].startswith(
        "Edit <Picture 1>. Texture the sewing pattern in <Picture 1> with the fabric of the T-shirt in <Picture 2>."),
        True)
    check("[1] b2 prompt picture_subject", b2.calls[0]["prompt"].startswith(
        "The flat sewing pattern of a T-shirt on a white background in <Picture 1> is <Subject 1>; "), True)
    front = rec["jobs"]["front"]
    tries = front.get("attempts") or []
    check("[1] record ready", rec["state"], "ready")
    check("[1] attempts", [(t["attempt"], t.get("backend"), t.get("dialect"), t["state"]) for t in tries],
          [(1, "a1", "picture_edit", "rejected"), (2, "b2", "picture_subject", "ready")])
    check("[1] attempt 2 routing", ((tries[1]["routing"] or {}).get("attempt_entry"), "fallback_from" in tries[1]["routing"]),
          ({"attempt": 2, "aimed_position": 2, "position": 2}, False))
    check("[1] attempt 1 routing plain", ("attempt_entry" in tries[0]["routing"], "fallback_from" in tries[0]["routing"]),
          (False, False))
    check("[1] the job's fields are attempt 2's", (front["backend"], front["dialect"], front["attempt"]),
          ("b2", "picture_subject", 2))
    a1_raw, a2_raw = gct._file(stem, ".raw_front.a1.png"), gct._file(stem, ".raw_front.a2.png")
    check("[1] both answers kept", (a1_raw.is_file(), a2_raw.is_file()), (True, True))
    check("[1] the current answer is attempt 2", gct._file(stem, ".raw_front.png").read_bytes() == a2_raw.read_bytes(),
          True)
    rec2 = gct.recompose(CHAR, ITEM, accept="front", attempt=1, apply_after=False)
    f2 = rec2["jobs"]["front"]
    check("[1] use attempt 1: its answer and fields", (gct._file(stem, ".raw_front.png").read_bytes()
                                                       == a1_raw.read_bytes(), f2["backend"], f2["dialect"],
                                                       f2["attempt"]), (True, "a1", "picture_edit", 1))

    print("[2] attempt 1 passes")
    rec, a1, b2 = run(["a1", "b2"], good, good)
    tries = rec["jobs"]["front"].get("attempts") or []
    check("[2] one render", (len(a1.calls), len(b2.calls), len(tries), rec["state"]), (1, 0, 1, "ready"))
    check("[2] no attempt_entry", "attempt_entry" in tries[0]["routing"], False)

    print("[3] a failure is never retried")
    rec, a1, b2 = run(["a1", "b2"], "busy", good)
    check("[3] failed, b2 never called", (rec["state"], rec["reason"].startswith("Front: The backend is busy"),
                                          len(b2.calls)), ("failed", True, 0))
    check("[3] attempts", [(t["attempt"], t["state"]) for t in rec["jobs"]["front"].get("attempts") or []],
          [(1, "failed")])

    print("[4] a single-entry chain: attempt 2 on the same backend, another seed")
    rec, a1, b2 = run(["a1"], white, good)
    tries = rec["jobs"]["front"].get("attempts") or []
    check("[4] two renders on a1", [c["seed"] for c in a1.calls], [seed, seed + 1000])
    check("[4] rejected", (rec["state"], [t["state"] for t in tries]), ("rejected", ["rejected", "rejected"]))
    check("[4] attempt_entry clamped", ((tries[1]["routing"] or {}).get("attempt_entry"),
                                        "fallback_from" in tries[1]["routing"]),
          ({"attempt": 2, "aimed_position": 1, "position": 1}, False))

    print("[5] attempt 2 fails: attempt 1's answer stays")
    rec, a1, b2 = run(["a1", "b2"], white, "busy")
    tries = rec["jobs"]["front"].get("attempts") or []
    check("[5] rejected, not failed", (rec["state"], rec["jobs"]["front"]["state"]), ("rejected", "rejected"))
    check("[5] attempts", [(t["attempt"], t["state"]) for t in tries], [(1, "rejected"), (2, "failed")])
    check("[5] the answer is attempt 1's", gct._file(stem, ".raw_front.png").read_bytes()
          == gct._file(stem, ".raw_front.a1.png").read_bytes(), True)

    print("[6] job_plan counts attempt 2")
    plan = gct.job_plan(CHAR, ITEM, PAYLOAD, "")
    check("[6] front 1, total 1, max 2", (plan["front"], plan["total"], plan["max"]), (1, 1, 2))

    print("[7] gate_attempts restores the attempt")
    seen = []
    for a in routing.gate_attempts(3):
        seen.append(routing.current_attempt())
    check("[7] 1, 2, 3 then 1", (seen, routing.current_attempt()), ([1, 2, 3], 1))
    seen = []
    for a in routing.gate_attempts(3):
        seen.append(routing.current_attempt())
        if a == 2:
            break
    check("[7] break in attempt 2 -> 1 again", (seen, routing.current_attempt()), ([1, 2], 1))

    check("network connects", len(CONNECTS), 0)
    import shutil
    shutil.rmtree(root, ignore_errors=True)
    print("FAILED: " + ", ".join(FAILS) if FAILS else "ALL OK")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
