#!/usr/bin/env python3
"""Smoke: what an inbox import leaves in the clip library besides its own
outputs (review 04#3, 04#5, 04#10; the CMU import for 04#5 too).

Blender is stood in for (``runner.run`` / ``runner.status`` patched, the
source probe ``_prepare_source`` patched to a fixed family); every directory
is temporary — ANIMATION_CLIPS_DIR, ANIMATION_CLIPS_LICENSED_DIR,
ANIMATION_CLIPS_INBOX_DIR and ANIMATION_RIG_FILE point into one temp dir.

Usage: ./.venv/bin/python scripts/smoke_fbx_import_library_state.py

[A] ``import_alt`` and a concurrent sidecar edit (04#3). The scene ``hug``
    (licensed, pair, sidecar ``hug.json`` with source files a.fbx/b.fbx and
    role anchors a [0, 0], b [0.5, 0]) gets the alt ``b~wave``. The alt run
    reads the sidecar, then waits for the library lock that a second thread
    holds; that thread sets ``loop`` (``set_clip_loop``) and releases. The
    stand-in run answers the scene's anchors unchanged (drift 0).
    Expected: ``hug.json`` has ``loop: true`` (the edit survives) AND
    ``alts.b == ["wave"]`` AND ``source.alt_takes["b~wave"]``; the file
    ``hug__b~wave.fbx`` exists. The old code wrote its pre-wait copy back:
    ``loop`` gone.
[B] same, but the concurrent edit is an orient that moved role b's anchor
    to [0.6, 0] (a re-measure after a turn). The rebuilt frame (b at
    [0.5, 0]) is 0.1 m off the CURRENT scene > 0.005 m → refused with
    ClipImportError, no ``hug__b~cheer.fbx``, sidecar unchanged
    (b anchor 0.6, no alt "cheer"). The old code checked against the
    pre-wait anchors (drift 0) and published the alt into a stale frame.
[C] overwrite import of a GROUP kind as a pair (04#5). Before, in the
    licensed root: ``dance__a/b/c.fbx``, the alt ``dance__b~x.fbx``, the
    role sidecar ``dance__a.json``, a stray ``dance.glb``, the numbered
    takes ``dance__a_02.fbx`` / ``dance__b_02.fbx``, and the other kinds
    ``dance-slow.fbx`` + ``dance-slow.json`` and ``dancer.fbx``. The import
    writes ``dance__a.fbx``, ``dance__b.fbx``, ``dance.json``.
    Expected afterwards: role c, the alt, the role sidecar and the .glb are
    gone (they are kind "dance", unnumbered, not written); the numbered
    takes and the other kinds stay byte-identical; the new halves carry the
    new bytes. The old code removed nothing.
[D] the pair ``hug`` (with alt ``b~wave`` from [A]) re-imported as a SOLO
    with overwrite: afterwards the only clip file of kind hug is ``hug.fbx``
    (beside ``hug.json``, now a solo sidecar) — no ``hug__a``, ``hug__b``,
    ``hug__b~wave``.
[E] two probes (``preview=True``) one after the other, A from a.fbx, B from
    b.fbx (04#10). Each answers its own URL
    ``/assets/clips-inbox/preview-clip/<12 hex>-preview.fbx``; the tokens
    differ, and AFTER B ran A's URL still resolves (``preview_clip_path``)
    to A's file (b"preview-a.fbx"), B's to B's. The old code wrote every
    probe to ``.preview/preview.fbx`` and deleted the folder's files first:
    both URLs were the same name and A's served B's bytes.
    ``preview_clip_path`` refuses ``preview.fbx`` (no token), a token with
    a path part, a non-probe name; a run directory last touched 2 h ago is
    swept by the next probe, one touched 10 min ago stays (PREVIEW_KEEP_S =
    3600 s).
[F] the CMU import (``cmu_import.convert_take``, ``take_files`` stubbed,
    the ``cmu_clip`` run stood in for) re-imports the GROUP ``wave`` of the
    free root as a pair with overwrite. Before: ``wave__a/b/c.fbx``, the alt
    ``wave__c~x.fbx``, the role sidecar ``wave__b.json``, the numbered take
    ``wave__a_02.fbx`` and the other kind ``wave-hand.fbx``. The run writes
    ``wave__a.fbx``, ``wave__b.fbx``, ``wave.json``. Expected afterwards:
    exactly those three plus ``wave__a_02.fbx`` and ``wave-hand.fbx``
    (unchanged bytes). The old CMU path removed nothing.
[G] the free pair ``bow`` (``bow__a/b.fbx``, alt ``bow__b~deep.fbx``,
    ``bow.json``) re-imported from ONE take (a solo) with overwrite: the only
    clip file of kind bow afterwards is ``bow.fbx``.
"""
import json
import os
import sys
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

TMP = Path(tempfile.mkdtemp(prefix="fbx-import-state-"))
FREE, LICENSED, INBOX = TMP / "free", TMP / "licensed", TMP / "inbox"
RIG = TMP / "rig.fbx"
os.environ["ANIMATION_CLIPS_DIR"] = str(FREE)
os.environ["ANIMATION_CLIPS_LICENSED_DIR"] = str(LICENSED)
os.environ["ANIMATION_CLIPS_INBOX_DIR"] = str(INBOX)
os.environ["ANIMATION_RIG_FILE"] = str(RIG)

from app.core import paths  # noqa: E402

paths.init(TMP / "world")

from app.core import db  # noqa: E402

db.init_schema()

from app.core import animation_clips as clips  # noqa: E402
from app.core import fbx_import  # noqa: E402
from app.core.cmu_import import ClipImportError  # noqa: E402
from app.core.keyed_lock import keyed_lock  # noqa: E402

FAIL = []


def check(label, ok, detail=""):
    print(f"{'ok  ' if ok else 'FAIL'} {label}" + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        FAIL.append(label)


def fake_prepare_source(path, take, *, name=None, src_family=""):
    return "unity-humanoid", {"index": take, "take_name": "", "name": name or path.name}


def fake_status():
    return {"executable": "fixture"}


ANCHORS = {"a": [0.0, 0.0], "b": [0.5, 0.0]}


def fake_run(script, *, inputs=None, params=None, out_dir=None, timeout_s=0):
    """The fbx_clip contract. ``export: alts``: only the alt file, and the
    scene's role points as rebuilt from its sources (ANCHORS). Otherwise one
    file per role (or the solo file) plus ``<kind>.json``."""
    out = Path(out_dir)
    outputs = {}
    if script == "cmu_clip":
        kind, pair = params["kind"], "asf_a" in (inputs or {})
        for stem in ([f"{kind}__a", f"{kind}__b"] if pair else [kind]):
            (out / f"{stem}.fbx").write_bytes(b"cmu-" + stem.encode())
            outputs[stem] = str(out / f"{stem}.fbx")
        side = {"kind": kind, "pair": pair, "roles": ["a", "b"] if pair else []}
        (out / f"{kind}.json").write_text(json.dumps(side), encoding="utf-8")
        outputs["sidecar"] = str(out / f"{kind}.json")
        return {"ok": True, "outputs": outputs, "data": side, "seconds": 0.1}
    if params.get("export") != "alts":
        kind, roles = params["kind"], params.get("roles") or []
        for stem in ([f"{kind}__{r}" for r in roles] or [kind]):
            data = (b"preview-" + Path(inputs["src"]).name.encode() if kind == "preview"
                    else b"new-" + stem.encode())
            (out / f"{stem}.fbx").write_bytes(data)
            outputs[stem] = str(out / f"{stem}.fbx")
        side = {"kind": kind, "pair": bool(roles), "roles": roles}
        (out / f"{kind}.json").write_text(json.dumps(side), encoding="utf-8")
        outputs["sidecar"] = str(out / f"{kind}.json")
        return {"ok": True, "outputs": outputs, "data": side, "seconds": 0.1}
    for alt in params.get("alts") or []:
        stem = f"{params['kind']}__{alt['role']}~{alt['name']}"
        (out / f"{stem}.fbx").write_bytes(b"alt-" + stem.encode())
        outputs[stem] = str(out / f"{stem}.fbx")
    data = {"geometry": {"roles": {r: {"anchor_xz_m": list(v)} for r, v in ANCHORS.items()},
                         "alts": {f"{a['role']}~{a['name']}": {"start_xz_m": [0, 0]}
                                  for a in params.get("alts") or []}}}
    return {"ok": True, "outputs": outputs, "data": data, "seconds": 0.1}


def write_scene():
    LICENSED.mkdir(parents=True, exist_ok=True)
    for role in ("a", "b"):
        (LICENSED / f"hug__{role}.fbx").write_bytes(b"half-" + role.encode())
    meta = {"kind": "hug", "pair": True, "roles": ["a", "b"], "fps": 30, "loop": False,
            "geometry": {"roles": {r: {"anchor_xz_m": list(v)} for r, v in ANCHORS.items()},
                         "anchor_s": 0.5},
            "source": {"format": "fbx", "files": ["a.fbx", "b.fbx"], "takes": [None, None]}}
    (LICENSED / "hug.json").write_text(json.dumps(meta), encoding="utf-8")
    clips.reload_clip_caches()


def sidecar():
    return json.loads((LICENSED / "hug.json").read_text(encoding="utf-8"))


def alt_with_concurrent_edit(alt, edit):
    """Run ``import_alt`` for ``alt`` in a thread while another thread holds
    the library lock; ``edit`` runs in the holder after the import asked for
    the lock (it has read the sidecar by then)."""
    asked = threading.Event()
    real_lock = fbx_import.library_write_lock

    @contextmanager
    def signalling_lock(destination):
        asked.set()
        with real_lock(destination):
            yield

    taken, release = threading.Event(), threading.Event()

    def holder():
        with keyed_lock("clip_library", "write"):
            taken.set()
            asked.wait(10)
            edit()
            release.wait(0.2)

    outcome = {}

    def importer():
        try:
            outcome["result"] = fbx_import.import_alt(
                "hug", "b", alt, {"name": "alt.fbx", "take": None}, target="licensed")
        except ClipImportError as e:
            outcome["error"] = str(e)

    with patch.object(fbx_import, "library_write_lock", signalling_lock):
        h = threading.Thread(target=holder)
        h.start()
        taken.wait(10)
        i = threading.Thread(target=importer)
        i.start()
        h.join(20)
        i.join(20)
    return outcome


def test_alt_keeps_concurrent_edit():
    print("[A] import_alt keeps a sidecar edit made while it waited")
    write_scene()
    outcome = alt_with_concurrent_edit(
        "wave", lambda: clips.set_clip_loop("licensed", "hug__a.fbx", True))
    check("the alt import succeeded", "result" in outcome, str(outcome))
    meta = sidecar()
    check("loop: true survived the alt import", meta.get("loop") is True, str(meta.get("loop")))
    check("alts.b names the new alt", (meta.get("alts") or {}).get("b") == ["wave"],
          str(meta.get("alts")))
    check("source.alt_takes records it",
          "b~wave" in ((meta.get("source") or {}).get("alt_takes") or {}), str(meta.get("source")))
    check("the alt file was written", (LICENSED / "hug__b~wave.fbx").is_file())


def test_alt_checks_current_frame():
    print("[B] import_alt checks the frame against the CURRENT sidecar")

    def orient():
        meta = sidecar()
        meta["geometry"]["roles"]["b"]["anchor_xz_m"] = [0.6, 0.0]
        (LICENSED / "hug.json").write_text(json.dumps(meta), encoding="utf-8")

    outcome = alt_with_concurrent_edit("cheer", orient)
    check("the alt import was refused", "error" in outcome and "nothing was written" in outcome["error"],
          str(outcome))
    check("no alt file was written", not (LICENSED / "hug__b~cheer.fbx").exists())
    meta = sidecar()
    check("the sidecar keeps the moved anchor and no alt 'cheer'",
          meta["geometry"]["roles"]["b"]["anchor_xz_m"] == [0.6, 0.0]
          and "cheer" not in ((meta.get("alts") or {}).get("b") or []), str(meta))


def names_of_kind(directory, *kinds):
    return sorted(p.name for p in directory.iterdir()
                  if p.is_file() and any(p.name.startswith(k) for k in kinds))


def test_overwrite_group_as_pair():
    print("[C] overwrite import of a group kind as a pair removes the old shape")
    before = {"dance__a.fbx": b"old-a", "dance__b.fbx": b"old-b", "dance__c.fbx": b"old-c",
              "dance__b~x.fbx": b"old-alt", "dance__a.json": b"{}", "dance.glb": b"old-glb",
              "dance__a_02.fbx": b"take2-a", "dance__b_02.fbx": b"take2-b",
              "dance-slow.fbx": b"slow", "dance-slow.json": b"{}", "dancer.fbx": b"dancer",
              "dance.json": json.dumps({"kind": "dance", "roles": ["a", "b", "c"]}).encode()}
    for name, data in before.items():
        (LICENSED / name).write_bytes(data)
    clips.reload_clip_caches()
    fbx_import.import_fbx("dance", [{"name": "a.fbx", "take": None}, {"name": "b.fbx", "take": None}],
                          overwrite=True, target="licensed")
    got = names_of_kind(LICENSED, "dance")
    want = sorted(["dance__a.fbx", "dance__b.fbx", "dance.json", "dance__a_02.fbx",
                   "dance__b_02.fbx", "dance-slow.fbx", "dance-slow.json", "dancer.fbx"])
    check("only the new pair, the numbered takes and the other kinds are left", got == want,
          f"{got} != {want}")
    check("the numbered takes and other kinds are untouched",
          all((LICENSED / n).read_bytes() == before[n] for n in
              ("dance__a_02.fbx", "dance__b_02.fbx", "dance-slow.fbx", "dance-slow.json", "dancer.fbx")))
    check("the halves are the new ones",
          (LICENSED / "dance__a.fbx").read_bytes() == b"new-dance__a"
          and (LICENSED / "dance__b.fbx").read_bytes() == b"new-dance__b")


def test_overwrite_pair_as_solo():
    print("[D] overwrite import of a pair kind as a solo removes the halves and alts")
    check("the pair and its alt are there before", all(
        (LICENSED / n).is_file() for n in ("hug__a.fbx", "hug__b.fbx", "hug__b~wave.fbx")))
    fbx_import.import_fbx("hug", [{"name": "a.fbx", "take": None}], overwrite=True,
                          target="licensed")
    got = sorted(p.name for p in LICENSED.iterdir()
                 if p.is_file() and p.suffix.lower() in clips.CLIP_EXTS
                 and clips.parse_clip_role(p.name)[0] == "hug")
    check("only hug.fbx is left of kind hug", got == ["hug.fbx"], str(got))
    check("hug.json is the solo sidecar",
          json.loads((LICENSED / "hug.json").read_text()).get("pair") is False)


def test_previews_do_not_collide():
    import time
    print("[E] each probe keeps its own files and URL")
    a = fbx_import.import_fbx("x", [{"name": "a.fbx", "take": None}], preview=True)
    b = fbx_import.import_fbx("x", [{"name": "b.fbx", "take": None}], preview=True)
    ua, ub = a["urls"]["solo"], b["urls"]["solo"]
    import re
    shape = re.compile(r"^/assets/clips-inbox/preview-clip/[0-9a-f]{12}-preview\.fbx$")
    check("both URLs have the probe shape", bool(shape.match(ua) and shape.match(ub)), f"{ua} {ub}")
    check("the two probes have different URLs", ua != ub, ua)
    pa = fbx_import.preview_clip_path(ua.rsplit("/", 1)[1])
    pb = fbx_import.preview_clip_path(ub.rsplit("/", 1)[1])
    check("A's URL still serves A's file after B ran",
          pa is not None and pa.read_bytes() == b"preview-a.fbx", str(pa))
    check("B's URL serves B's file", pb is not None and pb.read_bytes() == b"preview-b.fbx", str(pb))
    token = ua.rsplit("/", 1)[1][:12]
    for name in ("preview.fbx", f"{token}-../preview.fbx", f"{token}-walk.fbx", f"{token}-preview__z.fbx"):
        check(f"preview_clip_path refuses {name!r}", fbx_import.preview_clip_path(name) is None)
    root = fbx_import.preview_dir()
    old_run, young_run = root / "0123456789ab", root / "ba9876543210"
    for run, age in ((old_run, 7200), (young_run, 600)):
        run.mkdir()
        (run / "preview.fbx").write_bytes(b"x")
        os.utime(run, (time.time() - age, time.time() - age))
    fbx_import.import_fbx("x", [{"name": "a.fbx", "take": None}], preview=True)
    check("a run directory 2 h old is swept by the next probe", not old_run.exists())
    check("a run directory 10 min old stays", (young_run / "preview.fbx").is_file())
    check("A's run (seconds old) stays", pa.is_file())


def test_cmu_overwrite_removes_old_shape():
    from app.core import cmu_import
    print("[F] CMU overwrite import of a group kind as a pair removes the old shape")
    FREE.mkdir(parents=True, exist_ok=True)
    before = {"wave__a.fbx": b"old-a", "wave__b.fbx": b"old-b", "wave__c.fbx": b"old-c",
              "wave__c~x.fbx": b"old-alt", "wave__b.json": b"{}", "wave__a_02.fbx": b"take2",
              "wave-hand.fbx": b"hand",
              "wave.json": json.dumps({"kind": "wave", "roles": ["a", "b", "c"]}).encode()}
    for name, data in before.items():
        (FREE / name).write_bytes(data)
    clips.reload_clip_caches()
    stub = TMP / "take.asf", TMP / "take.amc"
    with patch.object(cmu_import, "take_files", return_value=stub):
        cmu_import.convert_take("wave", "01_01", "01_02", overwrite=True, source_fps=120)
        got = names_of_kind(FREE, "wave")
        want = sorted(["wave__a.fbx", "wave__b.fbx", "wave.json", "wave__a_02.fbx", "wave-hand.fbx"])
        check("only the new pair, the numbered take and the other kind are left", got == want,
              f"{got} != {want}")
        check("the numbered take and the other kind are untouched",
              all((FREE / n).read_bytes() == before[n] for n in ("wave__a_02.fbx", "wave-hand.fbx")))
        check("the halves are the new ones", (FREE / "wave__a.fbx").read_bytes() == b"cmu-wave__a")

        print("[G] CMU overwrite import of a pair kind as a solo removes the halves and alts")
        for name in ("bow__a.fbx", "bow__b.fbx", "bow__b~deep.fbx"):
            (FREE / name).write_bytes(b"old")
        (FREE / "bow.json").write_text(json.dumps({"kind": "bow", "pair": True}), encoding="utf-8")
        clips.reload_clip_caches()
        cmu_import.convert_take("bow", "02_01", overwrite=True, source_fps=120)
        got = sorted(p.name for p in FREE.iterdir()
                     if p.is_file() and p.suffix.lower() in clips.CLIP_EXTS
                     and clips.parse_clip_role(p.name)[0] == "bow")
        check("only bow.fbx is left of kind bow", got == ["bow.fbx"], str(got))


def main():
    INBOX.mkdir(parents=True, exist_ok=True)
    for name in ("a.fbx", "b.fbx", "alt.fbx"):
        (INBOX / name).write_bytes(b"source")
    RIG.write_bytes(b"rig")
    with patch.object(fbx_import, "_prepare_source", fake_prepare_source), \
         patch.object(fbx_import.runner, "status", fake_status), \
         patch.object(fbx_import.runner, "run", fake_run):
        test_alt_keeps_concurrent_edit()
        test_alt_checks_current_frame()
        test_overwrite_group_as_pair()
        test_overwrite_pair_as_solo()
        test_previews_do_not_collide()
        test_cmu_overwrite_removes_old_shape()
    print("FAIL" if FAIL else "PASS", f"({len(FAIL)} failing)" if FAIL else "")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
