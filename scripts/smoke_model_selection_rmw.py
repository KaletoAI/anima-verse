#!/usr/bin/env python3
"""Smoke run for three fixes found while auditing the prop export (2026-10-02).

No server, no DB, no GPU: a throwaway directory in /tmp. Every expectation is
derived BY HAND below, never from what the code prints.

THE FINDING (live, ``pine-tree``, 2026-09-05). A variant was deleted while two
variants behind it were generating. Afterwards ``selection.json`` named the
deleted stem again, pointing at two files that no longer existed, and one
job's record had landed in the variant behind its own. Two causes:

  (A) ``ModelGallery`` memoizes ``selection.json`` per instance, and a mesh
      job holds its gallery for minutes. Its final ``select`` wrote the WHOLE
      memo back — the stem that ``forget`` had removed meanwhile came back,
      and anything another stem had selected in between was lost.
  (B) ``delete_variant`` refused only while THE deleted variant generated, yet
      a delete renumbers every variant BEHIND it, and a job finishes by index.

Plus one bug in ``publish_pack``:

  (C) its "nothing to commit" branch read an undefined name (a NameError → 500
      instead of ``no_change``), and the branch could never be reached anyway:
      every export stamps ``exported_at`` into its manifest, so the ZIP always
      differed. ``marketplace_store.content_hash`` leaves exactly that stamp out.

Hand-derived cases:

[1] stale memo (A). Files ``model_1.glb``, ``model-v2_1.glb``,
    ``model-v2_2.glb``, ``model-v3_1.glb``.
    - selection after setup: {model: {full: model_1}, model-v2: {full: model-v2_1}}
    - gallery S (stem model-v2) READS the selection → its memo holds both stems.
    - another gallery forgets ``model`` → file: {model-v2: {full: model-v2_1}}
    - another gallery selects ``model-v3_1`` → file adds model-v3.
    - S now selects ``model-v2_2`` as low. The file must read exactly
        {model-v2: {full: model-v2_1, low: model-v2_2}, model-v3: {full: model-v3_1}}
      — ``model`` stays gone (old code: back), ``model-v3`` stays (old code: lost).
    - ``delete`` through a stale gallery follows the same rule.
    - no temp file is left behind by the atomic write.

[2] delete gate (B). Variants 0..3, a job running on index 2:
        delete 0 → blocked (2 is behind it)     delete 1 → blocked
        delete 2 → blocked (it is the job)      delete 3 → free (in front of it
                                                 nothing moves for the job)
    No job at all → nothing blocked.

[3] content hash (C). Two exports of the same files an hour apart differ only
    in ``exported_at`` → SAME hash. One changed byte in a file → different.
    A changed manifest field other than ``exported_at`` → different.

Usage:  ./.venv/bin/python scripts/smoke_model_selection_rmw.py
"""
import io
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

WORLD = Path(tempfile.mkdtemp(prefix="model-sel-rmw-smoke-"))
os.environ["STORAGE_DIR"] = str(WORLD)

from app.core import paths  # noqa: E402

paths.init(WORLD)

from app.core.model_store import ModelGallery  # noqa: E402

FAILURES = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


def sel_file(d: Path) -> dict:
    return json.loads((d / "selection.json").read_text(encoding="utf-8"))


def main() -> int:
    print("\n[1] a stale gallery never writes its memo back")
    d = WORLD / "props" / "tree"
    d.mkdir(parents=True)
    for name in ("model_1.glb", "model-v2_1.glb", "model-v2_2.glb",
                 "model-v3_1.glb"):
        (d / name).write_bytes(b"glb")
    ModelGallery(d, "model").select("model_1.glb")
    ModelGallery(d, "model-v2").select("model-v2_1.glb")
    stale = ModelGallery(d, "model-v2")
    check("the long-lived gallery read both stems",
          set(stale._read_all()) == {"model", "model-v2"},
          str(sorted(stale._read_all())))
    ModelGallery(d, "model").forget()
    ModelGallery(d, "model-v3").select("model-v3_1.glb")
    check("select through the stale gallery succeeds",
          stale.select("model-v2_2.glb", "low"))
    want = {"model-v2": {"full": "model-v2_1.glb", "low": "model-v2_2.glb"},
            "model-v3": {"full": "model-v3_1.glb"}}
    got = sel_file(d)
    check("the forgotten stem stays gone, the new stem survives",
          got == want, json.dumps(got, sort_keys=True))

    stale2 = ModelGallery(d, "model-v2")
    stale2._read_all()
    ModelGallery(d, "model-v3").forget()
    stale2.delete("model-v2_2.glb")
    want = {"model-v2": {"full": "model-v2_1.glb"}}
    got = sel_file(d)
    check("delete through a stale gallery: low dropped, model-v3 stays gone",
          got == want, json.dumps(got, sort_keys=True))
    leftovers = sorted(p.name for p in d.iterdir() if p.name.endswith(".tmp"))
    check("no temp file left behind", not leftovers, str(leftovers))

    print("\n[2] a delete is blocked by a job on it or behind it")
    from app.core import props
    pid = "gate-test"
    with props._lock:
        props._generating.add(f"{pid}|2|mesh-*|")
    try:
        got = [props.variant_delete_blocked(pid, i) for i in range(4)]
        check("job on 2 → delete 0,1,2 blocked, 3 free",
              got == [True, True, True, False], str(got))
    finally:
        with props._lock:
            props._generating.discard(f"{pid}|2|mesh-*|")
    got = [props.variant_delete_blocked(pid, i) for i in range(4)]
    check("no job → nothing blocked", got == [False] * 4, str(got))

    print("\n[3] the content hash ignores the export stamp only")
    from app.core.marketplace_store import content_hash as _pack_content_hash

    def pack(stamp: str, body: bytes, name: str = "Tree") -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("files/model_1.glb", body)
            zf.writestr("manifest.json", json.dumps(
                {"type": "prop", "prop_name": name, "exported_at": stamp}))
        return buf.getvalue()

    a = pack("2026-10-02T10:00:00Z", b"glb")
    b = pack("2026-10-02T11:00:00Z", b"glb")
    check("the two ZIPs themselves differ", a != b)
    check("same files, other stamp → same hash",
          _pack_content_hash(a) == _pack_content_hash(b))
    check("one changed byte → other hash",
          _pack_content_hash(a) != _pack_content_hash(
              pack("2026-10-02T10:00:00Z", b"glB")))
    check("another manifest field changed → other hash",
          _pack_content_hash(a) != _pack_content_hash(
              pack("2026-10-02T10:00:00Z", b"glb", name="Pine")))

    print("\nall checks passed" if not FAILURES
          else f"\n{len(FAILURES)} check(s) FAILED: {FAILURES}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
