#!/usr/bin/env python3
"""Smoke run for the COPY of a prop variant's view images (2026-09-02).

No world, no DB, no server: a throwaway props directory in /tmp gets two
variants written through the real store, and `_copy_variant_mesh` is asked what
it leaves behind. Every expectation is derived BY HAND from one law, never from
what the code prints:

    A VARIANT IS ONE VERSION OF THE OBJECT. A copy therefore takes ALL of the
    source's views and NONE of the target's own — a mixed set (front from
    subject A, a left view left over from subject B) would be handed to the
    multi-view mesher as if it were one object, and the bake would be a
    chimera nothing marks as one.

Hand-derived case:

    source  variant 0   front(A) + back(A)
    target  variant 1   front(B) + left(B)          →  _copy_variant_mesh(1, 0)

From the law, position by position:

  (a) the target holds exactly {front, back} afterwards — back arrives because
      the source has it, left GOES because the source has none. Sorted, that is
      ["back", "front"], and `source_path(..., view="left")` is None.
  (b) the bytes are the SOURCE's: target front == front(A), target back ==
      back(A). (The two stubs differ in colour, so a byte compare separates
      them.)
  (c) the provenance travels UNCHANGED, `generated_at` included — the copy
      displays the very same picture, so a fresh date would be a lie. The
      target's `back` record must equal the source's `back` record field for
      field, and the target's front record must name subject A's prompt.
  (d) nothing stale is left in the sidecar: the target's `image_views` entry has
      no `left` key at all. A record that describes a picture which is no longer
      there is worse than none.
  (e) the SOURCE is untouched — a copy reads it, it does not move anything.
  (f) the copy is IDEMPOTENT: running it a second time leaves exactly the same
      set, because every step is "make the target match the source".

Usage:  ./.venv/bin/python scripts/smoke_prop_view_copy.py
"""
import io
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

WORLD = Path(tempfile.mkdtemp(prefix="prop-view-copy-smoke-"))
os.environ["STORAGE_DIR"] = str(WORLD)

from app.core import paths  # noqa: E402

paths.init(WORLD)

from app.core import props as store  # noqa: E402
from app.core.model_store import write_sidecar  # noqa: E402

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
    print("\n[1] two variants, two different subjects")
    pid = store.create_prop(name="Crate")["id"]
    # A mesh in variant 0 — `_copy_variant_mesh` copies the MESH first and the
    # pictures with it; without a file there is nothing to copy.
    g = store.model_gallery(pid, 0)
    p = g.new_path()
    p.write_bytes(b"glTF-stub")
    write_sidecar(p, {"created_at": "2026-09-02T10:00:00+00:00",
                      "source": "upload", "format": "glb", "tier": "full"})
    g.select(p.name, "full")
    idx = store.add_variant(pid)
    check("the second variant is index 1", idx == 1, str(idx))

    front_a, back_a = png_bytes((10, 20, 30)), png_bytes((40, 50, 60))
    store.save_source_image(pid, front_a, 0, backend="bA", prompt="subject A")
    store.save_source_image(pid, back_a, 0, view="back", backend="bA",
                            prompt="A back")
    store.save_source_image(pid, png_bytes((70, 80, 90)), 1, backend="bB",
                            prompt="subject B")
    store.save_source_image(pid, png_bytes((1, 2, 3)), 1, view="left",
                            backend="bB", prompt="B left")
    check("the source holds front + back",
          sorted(store.variant_images(pid, 0)) == ["back", "front"],
          str(sorted(store.variant_images(pid, 0))))
    check("the target holds front + left",
          sorted(store.variant_images(pid, 1)) == ["front", "left"],
          str(sorted(store.variant_images(pid, 1))))

    meta_before = store.read_sidecar(pid)
    src_back_rec = store._image_meta(meta_before, "model", "back")

    print("\n[2] the copy makes the target ONE version of the object")
    store._copy_variant_mesh(pid, 1, 0)
    after = sorted(store.variant_images(pid, 1))
    check("(a) the target holds exactly front + back",
          after == ["back", "front"], str(after))
    check("(a) ...and the left file is gone",
          store.source_path(pid, 1, view="left") is None)
    check("(b) the front bytes are the source's",
          store.source_path(pid, 1).read_bytes() == front_a)
    check("(b) the back bytes are the source's",
          store.source_path(pid, 1, view="back").read_bytes() == back_a)

    meta = store.read_sidecar(pid)
    dst_back = store._image_meta(meta, "model-v2", "back")
    check("(c) the back provenance travels unchanged (generated_at kept)",
          dst_back == src_back_rec, f"{dst_back} vs {src_back_rec}")
    check("(c) the front provenance names subject A",
          store._image_meta(meta, "model-v2").get("prompt") == "subject A",
          str(store._image_meta(meta, "model-v2").get("prompt")))
    entry = [e for e in store._variant_list(meta) if e["stem"] == "model-v2"][0]
    check("(d) no stale `left` record is left behind",
          "left" not in (entry.get(store.IMAGE_VIEWS_KEY) or {}),
          str(entry.get(store.IMAGE_VIEWS_KEY)))
    check("(e) the source variant is untouched",
          sorted(store.variant_images(pid, 0)) == ["back", "front"],
          str(sorted(store.variant_images(pid, 0))))

    print("\n[3] a second copy changes nothing")
    store._copy_variant_mesh(pid, 1, 0)
    check("(f) the copy is idempotent",
          sorted(store.variant_images(pid, 1)) == ["back", "front"],
          str(sorted(store.variant_images(pid, 1))))
    check("(f) ...and the provenance still is the source's",
          store._image_meta(store.read_sidecar(pid), "model-v2", "back")
          == src_back_rec)

    print()
    if FAILURES:
        print(f"FAILED ({len(FAILURES)}): " + "; ".join(FAILURES))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        import shutil
        shutil.rmtree(WORLD, ignore_errors=True)
