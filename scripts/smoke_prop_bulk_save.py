#!/usr/bin/env python3
"""Smoke run for the prop detail's BATCH SAVE (``props.bulk_update``, 2026-08-25).

Usage:  ./.venv/bin/python scripts/smoke_prop_bulk_save.py

No world, no DB, no server: a throwaway props directory in /tmp gets a prop
written through the real store, and the batch is asked what it does to the
sidecar. Every expected value is derived BY HAND from the rules the field
routes already state, never from what the code currently prints.

---------------------------------------------------------------------------
[1] ONE REQUEST, ONE WRITE
---------------------------------------------------------------------------
That is the whole point of the batch. The panel used to write every field the
moment it lost focus, so authoring one variant — three metres, a subject, a
sink, a season, a marker — was SIX sidecar writes for one thought.

    the same six fields through the single-value setters   -> 6 writes
    the same six fields through `bulk_update`              -> 1 write

Counted by wrapping ``props._write_sidecar``. One is not "fewer", it is the
contract: a half-applied batch must not be a state the file can be in.

---------------------------------------------------------------------------
[2] THE SAME SANITATION, VERBATIM
---------------------------------------------------------------------------
A batch must never be a second, laxer way into the same record — the appliers
ARE the bodies of the single-value setters, so every law they state must hold
here. Hand-derived from those laws, all in ONE body:

    dims    {"width_m": 200}   -> 100.0    clamped to the (0, 100] window
    dims    {"depth_m": 0}     -> UNCHANGED (0.5)   nothing to inherit, so an
                                 unusable number costs the edit, not the size
    …and storing a size clears `dims_estimated` on that entry.

    ground_offset_m -9         -> -5.0     clamped, never refused
    ground_offset_m 0          -> NO KEY   "stands on the ground" IS absence
    description "   "          -> NO KEY   a blank line is not a statement
    markers  [junk, seat]      -> [seat]   invalid entries drop individually
    seasons  []                -> NO KEY   (which also puts variant 0 back in
                                 season, so it is the PRIMARY one again — [5]
                                 reads the record off it)

    general sway_factor 1.0    -> NO KEY   the default is stored as absence
    general tags "a, b, a"     -> ["a", "b"]   split + deduped case-insensitively
    general name "  "          -> UNCHANGED    a prop always has a name

---------------------------------------------------------------------------
[3] A REFUSAL WRITES NOTHING
---------------------------------------------------------------------------
Everything is checked BEFORE anything is stored (the ``plan_batch`` law), so a
body that is half junk cannot leave a half-saved prop behind — the admin would
have no way of telling which half arrived. Each of these raises ValueError (a
400 on the route) and leaves the sidecar BYTE-IDENTICAL, with zero writes:

    general  {"height_m": 2}      the moved-keys rule: the message names the
                                  variant route that owns the field now
    general  {"colour": "red"}    unknown prop field — refused, not ignored:
                                  a green "Saved" over a value that reached
                                  nothing is the worst of the three answers
    variants {"0": {"width_m": 2}}  a variant owns `dims`, not three loose
                                  metres — same rule one level down
    variants {"5": {...}}         this prop has two variants
    variants {"x": {...}}         a variant key is a STORE INDEX
    variants {"0": "nope"}        a patch is an object

    …and the good half of a body whose other half is junk is NOT written.

---------------------------------------------------------------------------
[4] AN EMPTY BODY IS A READ
---------------------------------------------------------------------------
Nothing to do writes nothing (0 writes) and still answers with the record, so
a Save with an empty draft can never move a file's mtime.

---------------------------------------------------------------------------
[5] THE ANSWER IS WHAT WAS STORED
---------------------------------------------------------------------------
The client adopts the answer instead of believing its own draft, so the answer
has to be the SAVED record: after [2] it says name "Long bench" and the primary
variant's clamped 100.0 m width. `sway_factor` reads back as the EFFECTIVE 1.0
even though the key is gone — that is the record's contract, and it is exactly
why the key itself is checked in the sidecar up in [2].
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

WORLD = Path(tempfile.mkdtemp(prefix="prop-bulk-smoke-"))
os.environ["STORAGE_DIR"] = str(WORLD)
os.environ["INSTANCE_DIR"] = str(WORLD / "instance")

from app.core import paths  # noqa: E402

paths.init(WORLD)
paths.init_instance(WORLD / "instance")

from app.core import props as store  # noqa: E402
from app.blender import runner as blender_runner  # noqa: E402
# Surface jobs may finish after an individual patch context. This standalone
# persistence probe never permits a real background Blender process.
blender_runner.is_available = lambda: False

FAILURES = []


def save_current(prop_id, general=None, variants=None):
    """Resolve fixture indices before creating a revision-bound author request."""
    current = store.get_prop(prop_id)
    entries = store.list_variants(prop_id) if current else []
    patches = {}
    for key, patch in (variants or {}).items():
        try:
            patches[entries[int(key)]["uid"]] = patch
        except (ValueError, IndexError):
            patches[str(key)] = patch
    return store.bulk_update(prop_id, general, patches,
                             base_revision=current["revision"] if current else "")

def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


class WriteCounter:
    """Counts the sidecar writes of whatever runs inside the ``with``."""

    def __init__(self) -> None:
        self.n = 0

    def __enter__(self) -> "WriteCounter":
        self._real = store._write_sidecar

        def counting(prop_id, meta):
            self.n += 1
            return self._real(prop_id, meta)

        store._write_sidecar = counting
        return self

    def __exit__(self, *exc) -> None:
        store._write_sidecar = self._real


def refused(label: str, **kwargs) -> None:
    """The body must raise AND leave the sidecar untouched."""
    before = (store._sidecar_path(BENCH) or Path()).read_text(encoding="utf-8")
    with WriteCounter() as w:
        try:
            save_current(BENCH, **kwargs)
            check(label, False, "no ValueError")
            return
        except ValueError as exc:
            reason = str(exc)
    after = (store._sidecar_path(BENCH) or Path()).read_text(encoding="utf-8")
    check(label, before == after and w.n == 0,
          f"{w.n} writes; {reason[:70]}")


def bbox_upload_regression():
    """A real low-only GLB upload still measures and refines estimated sizes."""
    import struct
    from unittest.mock import patch
    from app.blender import refine, runner
    vertices = [(x, y, z) for x in (0., 2.) for y in (0., 4.) for z in (0., 1.)]
    indices = [0, 1, 3, 0, 3, 2, 4, 6, 7, 4, 7, 5,
               0, 4, 5, 0, 5, 1, 2, 3, 7, 2, 7, 6,
               0, 2, 6, 0, 6, 4, 1, 5, 7, 1, 7, 3]
    binary = b"".join(struct.pack("<3f", *vertex) for vertex in vertices)
    binary += struct.pack("<36H", *indices)
    document = {
        "asset": {"version": "2.0"}, "scene": 0, "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0}], "buffers": [{"byteLength": len(binary)}],
        "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": 96, "target": 34962},
                        {"buffer": 0, "byteOffset": 96, "byteLength": 72, "target": 34963}],
        "accessors": [{"bufferView": 0, "componentType": 5126, "count": 8,
                       "type": "VEC3", "min": [0, 0, 0], "max": [2, 4, 1]},
                      {"bufferView": 1, "componentType": 5123, "count": 36, "type": "SCALAR"}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1, "mode": 4}]}],
    }
    encoded = json.dumps(document).encode()
    encoded += b" " * (-len(encoded) % 4)
    chunks = struct.pack("<II", len(encoded), 0x4E4F534A) + encoded
    chunks += struct.pack("<II", len(binary), 0x004E4942) + binary
    blob = struct.pack("<III", 0x46546C67, 2, len(chunks) + 12) + chunks
    measured = []

    def measurement(path):
        measured.append(path)
        return {"tris": 12}

    pid = store.create_prop(name="Low-only bbox fixture")["id"]
    with patch.object(refine, "auto_retexture_enabled", return_value=False), \
         patch.object(refine, "auto_bake_vc_enabled", return_value=False), \
         patch.object(refine, "auto_lod_enabled", return_value=False), \
         patch.object(refine, "measure_file", measurement), \
         patch.object(runner, "is_available", return_value=False):
        check("low-only primary upload succeeds", store.save_uploaded_glb(pid, blob, tier="low", variant=0))
    meta = store.read_sidecar(pid)
    check("low-only upload redistributes the estimated cube from real mesh proportions",
          store.variant_dims(meta) == {"width_m": .5, "depth_m": .25, "height_m": 1.}
          and not store.variant_dims_estimated(meta))
    check("low-only upload persists its bbox and measurement",
          meta.get("bbox") == [2., 4., 1.] and meta.get("measured") == {"tris": 12}
          and measured == [store.model_path(pid)])


def concurrency_regressions():
    """Event-driven interleavings; timeouts bound failures, not scheduling."""
    from threading import Event, Thread, current_thread
    from unittest.mock import patch
    from app.blender import refine, runner

    pid = store.create_prop(name="Lock order fixture")["id"]
    store.add_variant(pid)
    lookup_entered, toggle_entered = Event(), Event()
    failures = []
    real_path, real_pending = store.model_path, store.pending_variants

    def model_path(*args, **kwargs):
        if current_thread().name == "surface-delete":
            lookup_entered.set()
            if not toggle_entered.wait(5):
                raise AssertionError("toggle did not reach generation check")
        return real_path(*args, **kwargs)

    def pending(*args, **kwargs):
        if current_thread().name == "variant-toggle":
            toggle_entered.set()
        return real_pending(*args, **kwargs)

    def capture(fn):
        try:
            fn()
        except Exception as exc:
            failures.append(exc)

    with patch.object(store, "model_path", model_path), patch.object(store, "pending_variants", pending):
        deletion = Thread(name="surface-delete", target=lambda: capture(
            lambda: store.delete_surface_for(pid, 1)), daemon=True)
        toggle = Thread(name="variant-toggle", target=lambda: capture(
            lambda: store.set_variant_active(pid, 1, False)), daemon=True)
        deletion.start()
        check("surface deletion reaches model lookup", lookup_entered.wait(5))
        toggle.start()
        deletion.join(5)
        toggle.join(5)
        check("surface deletion and variant toggle both terminate",
              not deletion.is_alive() and not toggle.is_alive() and not failures,
              str(failures))
    if deletion.is_alive() or toggle.is_alive():
        return

    pid = store.create_prop(name="LOD lock order fixture")["id"]
    store.add_variant(pid)
    gallery = store.model_gallery(pid, 1)
    source = gallery.new_path()
    source.write_bytes(b"lod-fixture")
    gallery.select(source.name, "full")
    lookup_entered, toggle_entered = Event(), Event()
    real_gallery = store.model_gallery
    calls = 0

    def landing_gallery(*args, **kwargs):
        nonlocal calls
        if current_thread().name == "lod-landing":
            calls += 1
            if calls == 2:
                lookup_entered.set()
                if store._lock.locked() and not toggle_entered.wait(5):
                    raise AssertionError("toggle did not reach generation check")
        return real_gallery(*args, **kwargs)

    with patch.object(store, "model_gallery", landing_gallery), \
         patch.object(store, "pending_variants", pending), \
         patch.object(refine, "build_static_lod", return_value={
             "ok": True, "blob": b"reduced-fixture", "tris": 1, "tris_before": 2}):
        landing = Thread(name="lod-landing", target=lambda: capture(
            lambda: store._reduce_to_low(pid, source, .5, 1)), daemon=True)
        toggle = Thread(name="variant-toggle", target=lambda: capture(
            lambda: store.set_variant_active(pid, 1, False)), daemon=True)
        landing.start()
        check("LOD landing reaches fresh gallery lookup", lookup_entered.wait(5))
        toggle.start()
        landing.join(5)
        toggle.join(5)
        check("LOD landing and variant toggle both terminate",
              not landing.is_alive() and not toggle.is_alive() and not failures,
              str(failures))
    if landing.is_alive() or toggle.is_alive():
        return

    cases = [(change_mesh, through_upload, failed_run)
             for change_mesh in (False, True) for through_upload in (False, True)
             for failed_run in (False, True)]
    for change_mesh, through_upload, failed_run in cases:
        pid = store.create_prop(name="Area transaction fixture",
                                key_areas=["picture"] if through_upload else None)["id"]
        gallery = store.model_gallery(pid, 0)
        source = gallery.new_path()
        source.write_bytes(b"external-processing-fixture")
        gallery.select(source.name, "full")
        entered, release, saved = Event(), Event(), Event()
        area_errors, save_errors = [], []
        processed, upload_results, expected_source = [], [], []
        expected_metadata = []

        def run(*args, **kwargs):
            entered.set()
            processed.append(kwargs["inputs"]["model"])
            if not release.wait(10):
                raise AssertionError("test did not release external processor")
            return ({"ok": False, "error": "fixture processing failure"} if failed_run else
                    {"ok": True, "data": {"areas": []}, "outputs": {}})

        def areas():
            try:
                if through_upload:
                    upload_results.append(store.save_uploaded_glb(pid, b"uploaded-fixture", variant=0))
                else:
                    store._areas_run(pid, 0, {"mode": "auto"}, default_source="auto", wait_s=0)
            except Exception as exc:
                area_errors.append(exc)

        def save():
            try:
                revision = store.get_prop(pid)["revision"]
                if not change_mesh:
                    store.bulk_update(pid, {"name": "Authored during processing"},
                                      base_revision=revision)
                if change_mesh:
                    fresh = store.model_gallery(pid, 0)
                    replacement = fresh.new_path()
                    replacement.write_bytes(b"replacement-mesh")
                    store.set_file_areas(replacement, areas=[{
                        "id": "picture_1", "kind": "picture", "size_m": [1, 1],
                        "normal": [0, 0, 1], "source": "manual", "faces": 2}],
                        leaf_bbox={"min": [0, 0, 0], "max": [1, 1, 1]})
                    fresh.select(replacement.name, "full")
                expected_source.append(store.model_path(pid, variant=0))
                expected_metadata.append(store.read_model_sidecar(expected_source[-1]))
            except Exception as exc:
                save_errors.append(exc)
            finally:
                saved.set()

        with patch.object(refine, "unavailable_reason", return_value=""), \
             patch.object(refine, "take_lod_slot", return_value=True), \
             patch.object(refine, "free_lod_slot"), patch.object(runner, "run", run), \
             patch.object(refine, "auto_lod_enabled", return_value=False), \
             patch.object(refine, "auto_retexture_enabled", return_value=False), \
             patch.object(refine, "auto_bake_vc_enabled", return_value=False), \
             patch.object(runner, "is_available", return_value=False), \
             patch.object(store, "_extract_bbox", return_value=None):
            worker = Thread(target=areas, daemon=True)
            worker.start()
            check("area processing starts", entered.wait(5))
            writer = Thread(target=save, daemon=True)
            writer.start()
            save_finished_while_processing = saved.wait(5)
            release.set()
            worker.join(5)
            writer.join(5)
        check("read and draft save finish while external processing is blocked",
              save_finished_while_processing and not save_errors, str(save_errors))
        check("stale area landing is rejected without overwriting the author",
              not worker.is_alive()
              and ((not area_errors and upload_results == [True]) if through_upload else
                   (len(area_errors) == 1 and isinstance(area_errors[0],
                       RuntimeError if failed_run else store.PropRevisionConflict)))
              and store.read_sidecar(pid)["name"] == (
                  "Area transaction fixture" if change_mesh else "Authored during processing"),
              str(area_errors))
        check("stale processing leaves the chosen mesh and its area metadata untouched",
              bool(processed) and not store.areas_sidecar_path(processed[0]).exists()
              and expected_source == [store.model_path(pid, variant=0)]
              and not store.read_model_sidecar(processed[0]).get("areas_error"))
        check("failed or superseded processing preserves the selected mesh metadata",
              expected_metadata == [store.read_model_sidecar(expected_source[-1])])

    # A failure for the still-current source remains visible; guarding stale
    # diagnostics must not turn genuine processing errors into silent success.
    pid = store.create_prop(name="Current failure fixture", key_areas=["picture"])["id"]
    failure_reason = "fixture processing failure"
    with patch.object(refine, "unavailable_reason", return_value=""), \
         patch.object(refine, "take_lod_slot", return_value=True), \
         patch.object(refine, "free_lod_slot"), \
         patch.object(runner, "run", return_value={"ok": False, "error": failure_reason}), \
         patch.object(refine, "auto_lod_enabled", return_value=False), \
         patch.object(refine, "auto_retexture_enabled", return_value=False), \
         patch.object(refine, "auto_bake_vc_enabled", return_value=False), \
         patch.object(runner, "is_available", return_value=False):
        store.save_uploaded_glb(pid, b"current-failure-fixture", variant=0)
    check("a current processing failure retains the original diagnostic",
          store.file_areas(store.model_path(pid))["areas_error"] == failure_reason)


def main() -> int:
    global BENCH
    print("[0] a prop with two variants")
    bench = store.create_prop(name="Bench", category="seating",
                              width_m=2.0, depth_m=0.5, height_m=0.9)["id"]
    BENCH = bench
    second = store.add_variant(bench)
    check("two variants", len(store.list_variants(bench)) == 2,
          str(len(store.list_variants(bench))))

    print("\n[1] one request, one write")
    seat = {"id": "seat1", "group": "seat", "at": [0.5, 0.5, 0.5]}
    with WriteCounter() as singles:
        store.update_prop(bench, {"name": "Bench"})
        store.set_variant_dims(bench, 0, {"width_m": 2.0})
        store.set_variant_description(bench, 0, "a bench")
        store.set_variant_ground_offset(bench, 0, -0.1)
        store.set_variant_seasons(bench, 0, ["Winter"])
        store.set_variant_markers(bench, 0, [seat])
    check("the single-value setters write once each", singles.n == 6,
          str(singles.n))
    with WriteCounter() as batch:
        save_current(
            bench,
            {"name": "Bench"},
            {"0": {"dims": {"width_m": 2.0}, "description": "a bench",
                   "ground_offset_m": -0.1, "seasons": ["Winter"],
                   "markers": [seat]}})
    check("the same six fields as a batch write ONCE", batch.n == 1,
          str(batch.n))

    print("\n[2] the same sanitation, verbatim")
    save_current(
        bench,
        {"name": "  ", "tags": "a, b, A", "sway_factor": 1.0,
         "category": "seating"},
        {"0": {"dims": {"width_m": 200, "depth_m": 0},
               "ground_offset_m": -9, "seasons": [],
               "markers": [{"group": "", "at": [0, 0, 0]}, seat]},
         "1": {"description": "   ", "ground_offset_m": 0, "seasons": []}})
    meta = store.read_sidecar(bench)
    v0, v1 = meta["model_variants"]
    check("200 m is clamped to the 100 m window", v0["width_m"] == 100.0,
          str(v0["width_m"]))
    check("a zero leaves the stored metre standing", v0["depth_m"] == 0.5,
          str(v0["depth_m"]))
    check("storing a size clears dims_estimated",
          v0["dims_estimated"] is False, str(v0.get("dims_estimated")))
    check("-9 m sinks to the -5 m limit", v0["ground_offset_m"] == -5.0,
          str(v0.get("ground_offset_m")))
    check("the invalid marker is dropped, the seat is kept",
          v0["markers"] == [{"id": "seat1", "group": "seat",
                             "at": [0.5, 0.5, 0.5]}],
          json.dumps(v0.get("markers")))
    check("a blank description writes NO key",
          "description" not in v1, json.dumps(v1))
    check("ground offset 0 writes NO key",
          "ground_offset_m" not in v1, json.dumps(v1))
    check("an empty season list writes NO key",
          "seasons" not in v1, json.dumps(v1))
    check("the default sway factor writes NO key",
          "sway_factor" not in meta, json.dumps(meta.get("sway_factor")))
    check("the tags are split and deduped", meta["tags"] == ["a", "b"],
          json.dumps(meta.get("tags")))
    check("a blank name leaves the prop's name standing",
          meta["name"] == "Bench", meta.get("name"))
    # Variant 1 kept everything the ADD copied over — the batch touched three
    # of its fields and nothing else.
    check("an untouched field of a patched variant survives",
          v1["width_m"] == 2.0, str(v1.get("width_m")))

    print("\n[3] a refusal writes nothing")
    refused("a moved field in the general half names the variant route",
            general={"height_m": 2})
    refused("an unknown prop field is refused, not ignored",
            general={"colour": "red"})
    refused("a loose metre on a variant is refused — a variant owns `dims`",
            variants={"0": {"width_m": 2}})
    refused("an index this prop has no variant for",
            variants={"5": {"description": "x"}})
    refused("a variant key that is not a store index",
            variants={"x": {"description": "x"}})
    refused("a patch that is not an object", variants={"0": "nope"})
    refused("the good half of a half-junk body is not written either",
            general={"name": "Never stored"},
            variants={"0": {"nonsense": 1}})

    print("\n[4] an empty body is a read")
    with WriteCounter() as empty:
        rec = save_current(bench)
    check("nothing to do writes nothing", empty.n == 0, str(empty.n))
    check("…and still answers with the record", (rec or {}).get("id") == bench)
    check("an unknown prop is None", save_current("nope-there") is None)

    print("\n[5] the answer is what was stored")
    answer = save_current(bench, {"name": "Long bench"})
    check("the name the batch just stored", answer["name"] == "Long bench",
          str(answer.get("name")))
    check("the primary variant's clamped width", answer["width_m"] == 100.0,
          str(answer.get("width_m")))
    check("and the sway factor reads back as the full amount",
          answer.get("sway_factor") == 1.0, str(answer.get("sway_factor")))

    print("\n[6] revision conflicts and author validation are atomic")
    from copy import deepcopy
    revision = store.get_prop(bench)["revision"]
    store.bulk_update(bench, {"name": "First reader"}, base_revision=revision)
    before = store.read_sidecar(bench)
    try:
        store.bulk_update(bench, {"name": "Stale reader"}, base_revision=revision)
        check("stale reader is rejected", False)
    except store.PropRevisionConflict:
        check("stale reader preserves first save", store.read_sidecar(bench) == before)
    action = dict(id="rest", name="Rest", description="", enabled=True,
                  ability="pose", pose_key="sitting", participants=1, presence="any",
                  interrupt_on_presence_change=False, phases=[], effects=[],
                  requirements=[])
    for label, actions in (
        ("duplicate action IDs", [action, deepcopy(action)]),
        ("unknown condition requirement", [{**action, "requirements": [
            dict(id="req", target="actor", type="condition",
                 condition_id="not-a-real-condition", present=True)]}]),
        ("unknown effect condition", [{**action, "effects": [
            dict(id="fx", target="actor", type="condition_remove",
                 condition_id="not-a-real-condition", when="start")]}]),
        ("solo partner requirement", [{**action, "requirements": [
            dict(id="req", target="partner", type="condition",
                 condition_id="not-a-real-condition", present=True)]}]),
        ("nonfinite phase", [{**action, "ability": "combined", "phases": [
            dict(id="prepare", label="Prepare", duration_game_s=float("nan"), pose_key="")]}]),
    ):
        before = store.read_sidecar(bench)
        try:
            store.bulk_update(bench, {"name": "Must not land"},
                              actions=actions,
                              base_revision=store.get_prop(bench)["revision"])
            check(label, False)
        except store.PropDocumentInvalid as exc:
            check(label, bool(exc.issues) and store.read_sidecar(bench) == before)
    old_uid = store.list_variants(bench)[1]["uid"]
    store.delete_variant(bench, 1)
    replacement = store.add_variant(bench)
    check("delete/recreate never reuses UID",
          store.list_variants(bench)[replacement]["uid"] != old_uid)
    uid = store.list_variants(bench)[0]["uid"]
    with WriteCounter() as action_write:
        answer = store.bulk_update(bench, actions=[action],
                                   variants={uid: {"markers": [{"id": "seat1", "group": "seat", "at": [.5, .5, .5]}]}},
                                   base_revision=store.get_prop(bench)["revision"])
    check("actions and markers land in one write", action_write.n == 1)
    check("actions round-trip", store.get_prop(bench)["actions"] == [action])
    from app.core.prop_actions import derive_bindings
    check("bindings derived", derive_bindings(store.read_sidecar(bench), store.read_sidecar(bench)["model_variants"][0])[0]["marker_ids"] == ["seat1"])
    copied = store.add_variant(bench, 0)
    copied_row = store.list_variants(bench)[copied]
    check("copied markers keep exclusions without stored bindings",
          "action_bindings" not in copied_row and copied_row["markers"][0]["id"] == "seat1")
    from app.routes.world import _prop_bulk_update_sync
    from fastapi import HTTPException
    for label, body, expected_status in (
        ("missing revision", {"general": {"name": "Rejected"}}, 422),
        ("deleted UID", {"base_revision": store.get_prop(bench)["revision"],
                         "variants": {old_uid: {"description": "Wrong owner"}}}, 422),
        ("stale HTTP draft", {"base_revision": revision, "actions": []}, 409),
        ("null actions", {"base_revision": store.get_prop(bench)["revision"], "actions": None}, 422),
    ):
        before = store.read_sidecar(bench)
        try:
            _prop_bulk_update_sync(bench, body)
            check(label, False)
        except HTTPException as exc:
            check(label, exc.status_code == expected_status and store.read_sidecar(bench) == before)
    sleep = {**action, "id": "sleep", "ability": "sleep", "effects": [
        dict(id="asleep", target="actor", type="mood", mood="rested", when="success")]}
    saved_sleep = store.bulk_update(bench, actions=[action, sleep],
                                   base_revision=store.get_prop(bench)["revision"])
    check("real sleep transition allows success effects", saved_sleep["actions"][-1] == sleep)
    before = store.read_sidecar(bench)
    try:
        store.bulk_update(bench, actions=[action, {**sleep, "effects": [
            dict(id="rate", target="actor", type="stat_delta", stat="unknown",
                 amount=1, when="active")]}], base_revision=store.get_prop(bench)["revision"])
        check("sleep custom active regeneration is rejected", False)
    except store.PropDocumentInvalid as exc:
        check("sleep custom active regeneration is rejected",
              any(issue["code"] == "unsupported_combination" for issue in exc.issues)
              and store.read_sidecar(bench) == before)
    bbox_upload_regression()
    concurrency_regressions()
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
