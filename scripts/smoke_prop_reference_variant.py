#!/usr/bin/env python3
"""Smoke run for the REFERENCE VARIANT of a prop source render (2026-09-05).

No world, no DB, no server, no GPU: a throwaway props directory in /tmp gets
two variants written through the real store, and `props.reference_front` is
asked WHICH picture the next render would slot as its appearance reference.
The route half (`world._view_args`) is asked what it makes of a request body.
Every expectation is derived BY HAND from one law, never from what the code
prints:

    THE REFERENCE IS A PICTURE OF ANOTHER VERSION OF THE OBJECT, NEVER THE
    FILE THIS RENDER IS ABOUT TO WRITE. A render fed its own output is not a
    version of anything; a reference that is simply missing is not an error
    either — the render falls back to text alone.

Identity is decided on the FILE, not on the index: `None` and a negative index
both resolve to the PRIMARY variant, so two different numbers can name one and
the same picture, and the law has to catch that too.

Hand-derived setup:

    variant 0   front image  F0            (the primary variant)
    variant 1   no image at first

From the law, case by case — `→` is what `reference_front` must answer:

  (a) front render of variant 1, reference 0      → F0
      The new feature: a version of variant 0 is authored in variant 1. F0 is
      not the file being written (that is variant 1's front), so it stands.
  (b) front render of variant 0, reference 0      → None
      Same file. This is the render that would overwrite F0.
  (c) front render of variant 0, no reference     → None
      "No reference" means the variant's own front, which for a FRONT render
      is again F0 — so the plain re-render keeps rendering from text, exactly
      as it did before this feature existed.
  (d) front render of variant 0, reference -1     → None
      -1 is the primary variant, and the primary variant IS variant 0. The
      index differs, the file does not.
  (e) back render of variant 0, no reference      → F0
      The historic behaviour of the extra views, unchanged: the back is
      written to its own file, so the front beside it is a legal reference.
  (f) front render of variant 1, no reference     → None
      Variant 1 has no front image at this point — nothing to reference.
  (g) front render of variant 1, reference 7      → None
      A stale index from an old client is the same kind of miss as (f), and
      must not raise.

Then variant 1 is GIVEN a front image F1, which flips exactly two answers:

  (h) front render of variant 1, reference 1      → None   (now its own file)
  (i) front render of variant 1, reference 0      → F0     (still (a))
  (j) back render of variant 1, reference 0       → F0
      Cross-variant works on an extra view too — nothing in the law is about
      the view.

And the request body (`_view_args`), where one trap decides the feature:

  (k) an ABSENT reference_variant is None, not 0. 0 is a real variant index.
  (l) reference_variant 0 survives as 0, not as None — the falsy-index trap.
  (m) "2" (a string, which is what JSON from a <select> can look like) is 2.
  (n) a non-numeric reference_variant is a 400, not a silent None.

And the wire between the two — the chain a route really walks:

  (o) `_generate` hands `reference_variant` down to the source render
      untouched. The parsing and the decision are both right above; a value
      dropped in the middle would make them both irrelevant.

Usage:  ./.venv/bin/python scripts/smoke_prop_reference_variant.py
"""
import io
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

WORLD = Path(tempfile.mkdtemp(prefix="prop-ref-variant-smoke-"))
os.environ["STORAGE_DIR"] = str(WORLD)

from app.core import paths  # noqa: E402

paths.init(WORLD)

from app.core import props as store  # noqa: E402

FAILURES = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


def png_bytes(color) -> bytes:
    """A tiny PNG — the stand-in for a rendered product shot."""
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), color).save(buf, "PNG")
    return buf.getvalue()


def main() -> int:
    print("\n[1] one prop, two variants, only the first one has a picture")
    pid = store.create_prop(name="Tree")["id"]
    idx = store.add_variant(pid)
    check("the second variant is index 1", idx == 1, str(idx))
    store.save_source_image(pid, png_bytes((10, 90, 10)), 0,
                            backend="bA", prompt="a summer tree")
    f0 = store.source_path(pid, 0)
    check("variant 0 has a front image", f0 is not None)
    check("variant 1 has none yet", store.source_path(pid, 1) is None)
    check("the primary variant is 0", store.primary_variant(pid) == 0,
          str(store.primary_variant(pid)))

    print("\n[2] which picture a render would reference")
    ref = store.reference_front
    check("(a) front of variant 1 referencing 0 → variant 0's front",
          ref(pid, 1, "front", 0) == f0, str(ref(pid, 1, "front", 0)))
    check("(b) front of variant 0 referencing 0 → nothing (its own file)",
          ref(pid, 0, "front", 0) is None, str(ref(pid, 0, "front", 0)))
    check("(c) front of variant 0 with no reference → nothing",
          ref(pid, 0, "front", None) is None, str(ref(pid, 0, "front", None)))
    check("(d) front of variant 0 referencing -1 (= primary = 0) → nothing",
          ref(pid, 0, "front", -1) is None, str(ref(pid, 0, "front", -1)))
    check("(e) back of variant 0 with no reference → its own front",
          ref(pid, 0, "back", None) == f0, str(ref(pid, 0, "back", None)))
    check("(f) front of variant 1 with no reference → nothing (it has none)",
          ref(pid, 1, "front", None) is None, str(ref(pid, 1, "front", None)))
    check("(g) front of variant 1 referencing a variant that does not exist"
          " → nothing", ref(pid, 1, "front", 7) is None,
          str(ref(pid, 1, "front", 7)))

    print("\n[3] variant 1 gets its own picture")
    store.save_source_image(pid, png_bytes((200, 200, 220)), 1,
                            backend="bA", prompt="a winter tree")
    f1 = store.source_path(pid, 1)
    check("variant 1 now has a front image of its own", f1 is not None)
    check("...and it is a different file from variant 0's", f1 != f0,
          f"{f1} vs {f0}")
    check("(h) front of variant 1 referencing 1 → nothing (its own file now)",
          ref(pid, 1, "front", 1) is None, str(ref(pid, 1, "front", 1)))
    check("(i) front of variant 1 referencing 0 → variant 0's front",
          ref(pid, 1, "front", 0) == f0, str(ref(pid, 1, "front", 0)))
    check("(j) back of variant 1 referencing 0 → variant 0's front",
          ref(pid, 1, "back", 0) == f0, str(ref(pid, 1, "back", 0)))

    print("\n[4] what the request body means (_view_args)")
    from fastapi import HTTPException
    from app.routes.world import _view_args
    view, front_ref, ref_variant, views = _view_args({})
    check("(k) an empty body: front view, no reference, no reference variant",
          (view, front_ref, ref_variant, views) == ("front", False, None, []),
          str((view, front_ref, ref_variant, views)))
    _, front_ref, ref_variant, _ = _view_args(
        {"front_reference": True, "reference_variant": 0})
    check("(l) reference_variant 0 survives as 0, not as None",
          front_ref is True and ref_variant == 0, str(ref_variant))
    _, _, ref_variant, _ = _view_args({"reference_variant": "2"})
    check("(m) the string \"2\" becomes the index 2", ref_variant == 2,
          str(ref_variant))
    try:
        _view_args({"reference_variant": "winter"})
        check("(n) a non-numeric reference_variant is rejected", False,
              "no HTTPException")
    except HTTPException as e:
        check("(n) a non-numeric reference_variant is rejected with 400",
              e.status_code == 400, str(e.status_code))

    print("\n[5] the value survives the chain (_generate → _render_source)")
    seen = {}

    def fake_render(prop_id, backend_glob, prompt, negative, variant=None, **kw):
        seen.update({"variant": variant, **kw})
        return True

    real = store._render_source
    store._render_source = fake_render
    try:
        store._generate(pid, "a winter tree", "", "", "", image_only=True,
                        variant=1, view="front", front_reference=True,
                        reference_variant=0)
    finally:
        store._render_source = real
    check("(o) the render is told to reference variant 0",
          seen.get("reference_variant") == 0, str(seen))
    check("(o) ...for the front view of variant 1, with the switch on",
          (seen.get("variant"), seen.get("view"), seen.get("front_reference"))
          == (1, "front", True), str(seen))

    print()
    if FAILURES:
        print(f"FAILED ({len(FAILURES)}): " + "; ".join(FAILURES))
        return 1
    print("OK — the reference is another version's picture, never the file "
          "being written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
