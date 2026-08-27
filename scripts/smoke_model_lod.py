#!/usr/bin/env python3
"""Smoke run for the CPU distance-mesh build of props and location models.

No server, no Blender, no real world: a throwaway storage directory in /tmp
holds the stores (with a throwaway world.db for the location records), and
every Blender stage of the ingest — ``refine.build_static_lod`` above all, the
surface bake of spec-surface-height § 5 included — is REPLACED by a fake that
records its calls and hands back a stub blob. What is checked is therefore the
STORE semantics around the reduction; the Blender step itself has its own
smokes (``smoke_blender_*``).

Expected behaviour, derived from the design decisions of
``development_instructions/done/plan-distance-mesh-props-dioramen.md``:

  - a subject without a full model answers ``no_model`` and builds nothing,
  - a build writes a NEW gallery file, selects it as ``low`` and leaves the
    full mesh untouched; its sidecar carries ratio/tris/tris_before,
  - the result dict names the numbers the panel shows (ok, tier, ratio, tris,
    tris_before, size, size_before),
  - the ratio DEFAULT is the configured one per kind (prop 0.25, room 0.5,
    building 0.5), an explicit ratio wins,
  - RED counter-check: a second build WITHOUT force does not run at all (the
    fake is not called a second time and the low selection stays put) —
  - ...while ``force=True`` runs, adds ANOTHER file and re-points the
    selection to it; the previous low file stays in the gallery (history),
  - the background trigger obeys "build distance meshes on demand": switched
    off it never calls the fake, switched on it builds the missing low tier,
    and it does nothing at all once a low tier exists,
  - the demand comes from the PAYLOAD BUILD, not from the serving route: the
    two reads that hand a client a tier list (``props.model_tiers`` and
    ``location_model3d.get_client_meta``) ask for a missing low mesh, and stop
    asking once it is there,
  - a FAILED build is remembered in-process: the automatic path skips that
    subject from then on, even after the reduction works again — only the
    admin's ``force`` tries anyway, and a success clears the entry,
  - at most two background builds run at a time ACROSS the stores; with every
    slot busy nothing is started and no in-flight key stays stuck (the next
    demand builds), and a candidate that is rejected AFTER taking its slot
    (no mesh at all) hands it back.

Usage:  ./.venv/bin/python scripts/smoke_model_lod.py
"""
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

WORLD = Path(tempfile.mkdtemp(prefix="model-lod-smoke-"))
os.environ["ANIMATION_CLIPS_DIR"] = tempfile.mkdtemp(prefix="model-lod-clips-")

from app.core import paths  # noqa: E402

paths.init(WORLD)

from app.core import db  # noqa: E402

db.init_schema()

from app.blender import refine  # noqa: E402
from app.core import location_model3d, props  # noqa: E402
from app.core.model_store import read_sidecar  # noqa: E402

FAILURES = []
# Every call the stores made into the reduction, as (source file name, ratio).
CALLS = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


def fake_build_static_lod(path, ratio):
    """Stand-in for the Blender stage: no mesh, just a record and a stub."""
    CALLS.append((Path(path).name, float(ratio)))
    return {"ok": True, "blob": b"glTF-reduced", "tris": 2500,
            "tris_before": 10000, "error": ""}


def fake_failing(path, ratio):
    CALLS.append((Path(path).name, float(ratio)))
    return {"ok": False, "blob": b"", "tris": None, "tris_before": None,
            "error": "no blender executable found"}


def wait_for(cond, seconds: float = 5.0) -> bool:
    """The background trigger runs in a thread — give it a moment."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(0.05)
    return cond()


def main() -> int:
    refine.build_static_lod = fake_build_static_lod
    # The OTHER ingest stages would run the real Blender over the stub bytes.
    # They are not what this checks, and a smoke must not depend on a binary.
    refine.auto_retexture_enabled = lambda: False
    refine.auto_bake_vc_enabled = lambda: False
    # Since spec-surface-height § 5 a landing also bakes the model's walking
    # surface — another Blender stage, and one that takes a LOD SLOT. Faked
    # here for both reasons: this smoke counts slots.
    from app.core import model_surface  # noqa: PLC0415
    model_surface.bake_surface = lambda *a, **k: None
    # "Build distance meshes on demand" stays OFF for [1]-[5] and [7]: the
    # explicit build is the admin's own action and must ignore that switch —
    # and with the automatic trigger silent, every recorded call below is one
    # the explicit path made.
    refine.auto_lod_enabled = lambda: False
    # The stores ask the config for their ratios; a temp world has none, so
    # these are the schema defaults the admin page shows.
    ratio_prop = refine.lod_ratio("prop")
    ratio_room = refine.lod_ratio("room")
    ratio_building = refine.lod_ratio("building")

    print("\n[0] the configured targets are per kind")
    check("prop reduces hardest", ratio_prop == 0.25, str(ratio_prop))
    check("a room diorama tolerates less", ratio_room == 0.5, str(ratio_room))
    check("a building like a room", ratio_building == 0.5, str(ratio_building))

    print("\n[1] a prop without a mesh builds nothing")
    prop = props.create_prop(name="Lod Chair", width_m=0.5, depth_m=0.5,
                             height_m=1.0)
    pid = prop["id"]
    res = props.build_low_tier(pid, force=True)
    check("ok is False and the reason is no_model",
          res["ok"] is False and res["error"] == "no_model", str(res))
    check("the reduction was never called", CALLS == [], str(CALLS))

    print("\n[2] the build writes a NEW file and selects it as low")
    props.save_uploaded_glb(pid, b"glTF-full")
    full_name = props.model_path(pid, "full").name
    CALLS.clear()
    # No force: the low tier does not exist yet, and the on-demand switch is
    # off — the explicit build runs anyway.
    res = props.build_low_tier(pid)
    check("ok", res["ok"] is True, str(res))
    check("it reduced the FULL mesh at the prop ratio",
          CALLS == [(full_name, ratio_prop)], str(CALLS))
    check("the result names tier, ratio and both triangle counts",
          (res["tier"], res["ratio"], res["tris"], res["tris_before"])
          == ("low", ratio_prop, 2500, 10000), str(res))
    check("...and both file sizes",
          res["size"] == len(b"glTF-reduced")
          and res["size_before"] == len(b"glTF-full"),
          f'{res["size"]} / {res["size_before"]}')
    low_path = props.model_path(pid, "low")
    check("low resolves to the reduced bytes",
          low_path.read_bytes() == b"glTF-reduced", str(low_path))
    check("the full mesh is untouched",
          props.model_path(pid, "full").read_bytes() == b"glTF-full")
    check("full and low are different files", low_path.name != full_name)
    side = read_sidecar(low_path)
    check("the sidecar records the reduction",
          (side.get("source"), side.get("tier"), side.get("lod_ratio"),
           side.get("tris"), side.get("tris_before"), side.get("source_file"))
          == ("lod", "low", ratio_prop, 2500, 10000, full_name), str(side))
    listed = {m["filename"]: m for m in props.list_models(pid)}
    check("the gallery row carries the numbers the panel shows",
          listed[low_path.name]["tris"] == 2500
          and listed[low_path.name]["lod_ratio"] == ratio_prop,
          str(listed[low_path.name]))
    check("...and the full row carries none",
          listed[full_name]["tris"] == 0
          and listed[full_name]["lod_ratio"] == 0.0, str(listed[full_name]))
    check("the panel payload carries the Blender gate",
          "usable" in (props.get_model_info(pid).get("blender") or {}),
          str(props.get_model_info(pid).get("blender")))

    print("\n[3] RED counter-check: without force an existing low is kept")
    CALLS.clear()
    res = props.build_low_tier(pid)
    check("ok is False", res["ok"] is False, str(res))
    check("the reduction was NOT called a second time", CALLS == [],
          str(CALLS))
    check("the low selection still points at the first build",
          props.model_path(pid, "low").name == low_path.name)
    check("no third file appeared", len(props.list_models(pid)) == 2,
          str(sorted(m["filename"] for m in props.list_models(pid))))

    print("\n[4] force rebuilds into a NEW file, the old one stays")
    CALLS.clear()
    time.sleep(1.1)  # the gallery names files by second — force a new name
    res = props.build_low_tier(pid, ratio=0.4, force=True)
    check("ok", res["ok"] is True, str(res))
    check("the explicit ratio wins over the configured default",
          CALLS == [(full_name, 0.4)], str(CALLS))
    check("...and is what the result reports", res["ratio"] == 0.4, str(res))
    new_low = props.model_path(pid, "low")
    check("low points at the NEW file", new_low.name != low_path.name,
          f"{low_path.name} -> {new_low.name}")
    names = {m["filename"] for m in props.list_models(pid)}
    check("the previous low file is still in the gallery",
          low_path.name in names and len(names) == 3, str(sorted(names)))
    check("...but serves no tier any more",
          [m["selected_for"] for m in props.list_models(pid)
           if m["filename"] == low_path.name] == [[]])

    print("\n[5] a failing reduction stores nothing")
    refine.build_static_lod = fake_failing
    CALLS.clear()
    res = props.build_low_tier(pid, force=True)
    check("ok is False and the reason is passed through",
          res["ok"] is False and "blender" in res["error"], str(res))
    check("no file was added", len(props.list_models(pid)) == 3,
          str(len(props.list_models(pid))))
    check("low still points at the last good build",
          props.model_path(pid, "low").name == new_low.name)
    refine.build_static_lod = fake_build_static_lod

    print("\n[6] the background trigger obeys the on-demand switch")
    prop2 = props.create_prop(name="Lod Table", width_m=1.0, depth_m=1.0,
                             height_m=0.8)
    pid2 = prop2["id"]
    CALLS.clear()
    # save_uploaded_glb runs the whole ingest, the trigger with it.
    props.save_uploaded_glb(pid2, b"glTF-full-2")
    check("switched off, nothing is built",
          not wait_for(lambda: bool(CALLS), 0.5) and CALLS == [], str(CALLS))
    check("...and the prop has no low tier",
          props.model_tiers(pid2) == ["full"], str(props.model_tiers(pid2)))
    refine.auto_lod_enabled = lambda: True
    props.request_low_tier(pid2)
    check("switched on, the missing low tier is built in the background",
          wait_for(lambda: props.model_tiers(pid2) == ["full", "low"]),
          str(props.model_tiers(pid2)))
    CALLS.clear()
    props.request_low_tier(pid2)
    check("a second trigger with a low tier present does nothing",
          not wait_for(lambda: bool(CALLS), 0.5), str(CALLS))

    print("\n[7] the demand comes from the PAYLOAD, not from the serving route")
    from app.models.world import add_location, add_room
    refine.auto_lod_enabled = lambda: False
    prop3 = props.create_prop(name="Lod Lamp", width_m=0.3, depth_m=0.3,
                              height_m=1.4)
    pid3 = prop3["id"]
    props.save_uploaded_glb(pid3, b"glTF-full-3")
    seam_loc = add_location(name="Seam Hall", description="smoke")["id"]
    location_model3d.save_uploaded_building(seam_loc, b"glTF-full-seam")
    check("both subjects start without a distance mesh",
          props.model_tiers(pid3) == ["full"]
          and sorted(location_model3d.get_client_meta(seam_loc)["tiers"]) == ["full"])
    refine.auto_lod_enabled = lambda: True
    # The two reads every client payload goes through: the prop's tier list
    # (scatter entries, room placements, the prop library) and the location
    # model's client meta (model/meta route, scene-recipe inputs).
    CALLS.clear()
    props.model_tiers(pid3)
    check("listing a prop's tiers asks for the missing low mesh",
          wait_for(lambda: props.model_tiers(pid3) == ["full", "low"]),
          str(props.model_tiers(pid3)))
    CALLS.clear()
    location_model3d.get_client_meta(seam_loc)
    check("reading a location model's client meta does the same",
          wait_for(lambda: sorted(
              location_model3d.get_client_meta(seam_loc)["tiers"])
              == ["full", "low"]),
          str(location_model3d.get_client_meta(seam_loc)["tiers"]))
    CALLS.clear()
    props.model_tiers(pid3)
    location_model3d.get_client_meta(seam_loc)
    check("with both tiers there, no payload asks again",
          not wait_for(lambda: bool(CALLS), 0.5), str(CALLS))

    print("\n[8] a failed build is remembered, force may still try")
    prop4 = props.create_prop(name="Lod Bench", width_m=1.2, depth_m=0.5,
                              height_m=0.5)
    pid4 = prop4["id"]
    refine.auto_lod_enabled = lambda: False
    props.save_uploaded_glb(pid4, b"glTF-full-4")
    refine.auto_lod_enabled = lambda: True
    refine.build_static_lod = fake_failing
    CALLS.clear()
    props.request_low_tier(pid4)
    check("the first automatic attempt runs", wait_for(lambda: bool(CALLS)),
          str(CALLS))
    CALLS.clear()
    props.request_low_tier(pid4)
    props.model_tiers(pid4)
    check("...after the failure the automatic path skips the prop",
          not wait_for(lambda: bool(CALLS), 0.5), str(CALLS))
    refine.build_static_lod = fake_build_static_lod
    CALLS.clear()
    props.model_tiers(pid4)
    check("...even with a working reduction again (the memory holds)",
          not wait_for(lambda: bool(CALLS), 0.5), str(CALLS))
    CALLS.clear()
    res = props.build_low_tier(pid4, force=True)
    check("the admin's button ignores the memory", res["ok"] is True, str(res))
    check("...and the entry is gone after the success",
          pid4 not in props._lod_failed, str(props._lod_failed))

    print("\n[9] at most two background builds at a time (all stores)")
    slots = [refine.take_lod_slot(), refine.take_lod_slot()]
    check("two slots are free at rest", slots == [True, True], str(slots))
    check("...and the third is not", refine.take_lod_slot() is False)
    prop5 = props.create_prop(name="Lod Crate", width_m=0.6, depth_m=0.6,
                              height_m=0.6)
    pid5 = prop5["id"]
    refine.auto_lod_enabled = lambda: False
    props.save_uploaded_glb(pid5, b"glTF-full-5")
    refine.auto_lod_enabled = lambda: True
    CALLS.clear()
    props.request_low_tier(pid5)
    check("with every slot busy nothing is started",
          not wait_for(lambda: bool(CALLS), 0.5), str(CALLS))
    refine.free_lod_slot()
    refine.free_lod_slot()
    props.request_low_tier(pid5)
    check("...and the next demand builds it (no key stayed stuck)",
          wait_for(lambda: props.model_tiers(pid5) == ["full", "low"]),
          str(props.model_tiers(pid5)))
    # A candidate that turns out not to be one takes its slot BEFORE the
    # gallery is read (that is the point of the order — a full sweep must not
    # parse a GLB per subject while the limit is exhausted), so it has to give
    # the slot back on the way out.
    empty = props.create_prop(name="Lod Ghost", width_m=0.2, depth_m=0.2,
                              height_m=0.2)["id"]
    CALLS.clear()
    props.request_low_tier(empty)
    check("a prop without a mesh starts nothing",
          not wait_for(lambda: bool(CALLS), 0.3), str(CALLS))
    slots = [refine.take_lod_slot(), refine.take_lod_slot()]
    check("...and its slot came back (both are free again)",
          slots == [True, True], str(slots))
    refine.free_lod_slot()
    refine.free_lod_slot()

    print("\n[10] the same contract for a room diorama and a building")
    refine.auto_lod_enabled = lambda: False  # back to the explicit path alone
    loc_id = add_location(name="Smoke Hall", description="smoke")["id"]
    room_id_ = add_room(loc_id, "Hall")["id"]
    for room_id, kind_ratio in (("", ratio_building), (room_id_, ratio_room)):
        what = room_id and "room" or "building"
        location_model3d.save_uploaded_building(
            loc_id, b"glTF-full-loc", room_id=room_id)
        CALLS.clear()
        res = location_model3d.build_low_tier(loc_id, room_id, force=True)
        check(f"{what}: ok", res["ok"] is True, str(res))
        check(f"{what}: reduced at its own configured ratio",
              [r for _n, r in CALLS] == [kind_ratio], str(CALLS))
        low = location_model3d.find_building_model(loc_id, room_id, "low")
        full = location_model3d.find_building_model(loc_id, room_id, "full")
        check(f"{what}: low is a new file with the reduced bytes",
              low is not None and low != full
              and low.read_bytes() == b"glTF-reduced", str(low))
        side = read_sidecar(low)
        check(f"{what}: the sidecar names the subject",
              side.get("location") == loc_id
              and side.get("room", "") == room_id, str(side))
        rows = {m["filename"]: m for m in
                location_model3d.list_models(loc_id, room_id)}
        check(f"{what}: the gallery row carries the numbers",
              rows[low.name]["tris"] == 2500
              and rows[low.name]["lod_ratio"] == kind_ratio,
              str(rows[low.name]))
        CALLS.clear()
        res = location_model3d.build_low_tier(loc_id, room_id)
        check(f"{what}: without force the existing low is kept (RED)",
              res["ok"] is False and CALLS == [], str(res))
    info = location_model3d.get_building_info(loc_id)
    check("the building panel payload carries the Blender gate",
          "usable" in (info.get("blender") or {}), str(info.get("blender")))

    print(f"\n{'FAILED: ' + ', '.join(FAILURES) if FAILURES else 'all checks passed'}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        shutil.rmtree(WORLD, ignore_errors=True)
