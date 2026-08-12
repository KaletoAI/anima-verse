#!/usr/bin/env python3
"""Smoke run for the shared model gallery (app/core/model_store.py).

No world, no DB, no server: a throwaway directory in /tmp gets model files
and selections written by hand, and the gallery is asked what it resolves.
Expected values are derived from the CONTRACT (plan-3d-lod-und-betreten.md,
docs/schnittstellen-3d.md v5.3 Nr. 16), not from what the code currently
prints:

  - a file nobody selected is the DEFAULT tier (the pre-selection store
    behaviour: newest file wins),
  - a file selected for `low` is `low` — and is NOT the implicit default any
    more, even when it is the newest file,
  - a tier the subject does not have falls back in the order full → low,
  - `__none__` on the default tier switches the WHOLE subject off (that is
    the admin's "render nothing"), while an empty non-default tier just
    ceases to exist,
  - the signature covers EVERY tier: a new low file must move it (with the
    old single-file signature the clients never noticed one).

The prop store is checked through the same lens: two uploads, two tiers, one
record — plus the admin gallery on top of it (list/select/delete/serve), where
a superseded file stays listed but serves no tier, and deleting a tier's file
lets that tier cease to exist instead of dangling.

Usage:  ./.venv/bin/python scripts/smoke_model_store.py
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

WORLD = Path(tempfile.mkdtemp(prefix="model-store-smoke-"))
os.environ["STORAGE_DIR"] = str(WORLD)

from app.core import paths  # noqa: E402

paths.init(WORLD)

from app.core.model_store import (DEFAULT_TIER, ModelGallery,  # noqa: E402
                                  SEL_NONE, write_sidecar)

FAILURES = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


def put(g: ModelGallery, name: str, created_at: str) -> Path:
    """A model file with a hand-written sidecar (created_at drives the sort)."""
    g.dir.mkdir(parents=True, exist_ok=True)
    p = g.dir / name
    p.write_bytes(b"glTF-stub")
    write_sidecar(p, {"created_at": created_at, "source": "upload",
                      "format": "glb"})
    return p


def gal(d: Path) -> ModelGallery:
    """A FRESH instance — the memo is per instance, by contract."""
    return ModelGallery(d, "building")


def main() -> int:
    d = WORLD / "locations" / "loc" / "model3d"

    print("\n[1] empty gallery")
    g = gal(d)
    check("no files, no active model", g.find() is None)
    check("no tiers", g.tiers() == {}, str(g.tiers()))
    check("nothing is 'none selected' either", not g.none_selected())

    print("\n[2] a file nobody selected is the default tier")
    put(g, "building_100.glb", "2026-01-01T00:00:00+00:00")
    old = put(g, "building_090.glb", "2025-01-01T00:00:00+00:00")
    g = gal(d)
    check("the NEWEST file is active", (g.find() or Path()).name == "building_100.glb",
          str(g.find()))
    check("both files are listed, newest first",
          [p.name for p in g.files()] == ["building_100.glb", "building_090.glb"],
          str([p.name for p in g.files()]))
    check("tiers() reports exactly the default tier",
          {t: p.name for t, p in g.tiers().items()} == {"full": "building_100.glb"},
          str({t: p.name for t, p in g.tiers().items()}))
    sig_full_only = g.signature()

    print("\n[3] a low selection is low — and stops being the implicit full")
    g = gal(d)
    check("selecting the older file for low succeeds", g.select(old.name, "low"))
    g = gal(d)
    check("low resolves to the low file", (g.find("low") or Path()).name == old.name,
          str(g.find("low")))
    check("full still resolves to the unclaimed newest file",
          (g.find("full") or Path()).name == "building_100.glb", str(g.find("full")))
    check("both tiers are published",
          sorted(g.tiers()) == ["full", "low"], str(sorted(g.tiers())))
    check("the signature moved (it covers every tier)",
          g.signature() != sig_full_only,
          f"{sig_full_only} -> {g.signature()}")
    check("...and is stable for an unchanged state",
          g.signature() == gal(d).signature())

    print("\n[4] fallback: an unknown/missing tier gets the best available one")
    g = gal(d)
    check("an unknown tier falls back to full",
          (g.find("ultra") or Path()).name == "building_100.glb", str(g.find("ultra")))
    check("without fallback an unknown tier is simply absent",
          g.find("ultra", fallback=False) is None)
    check("a path escape is not a filename",
          not g.matches("../../etc/passwd") and not g.matches("room_x_1.glb"))

    print("\n[5] the __none__ sentinel is the admin's master switch")
    g = gal(d)
    check("deselecting the default tier writes the sentinel", g.select("", DEFAULT_TIER))
    g = gal(d)
    check("the sentinel is stored", g.selection().get(DEFAULT_TIER) == SEL_NONE,
          str(g.selection()))
    check("none_selected is True", g.none_selected())
    check("no tier resolves any more — not even the low file",
          g.find() is None and g.find("low") is None)
    check("...and tiers() is empty (the payload gets no variants)", g.tiers() == {})
    g = gal(d)
    g.select("building_100.glb", DEFAULT_TIER)
    g = gal(d)
    check("selecting again clears the sentinel",
          (g.find() or Path()).name == "building_100.glb" and not g.none_selected())
    g = gal(d)
    check("an empty NON-default tier just disappears", g.select("", "low"))
    check("...and low falls back to full afterwards",
          (gal(d).find("low") or Path()).name == "building_100.glb")
    check("a file that does not exist is never selectable",
          not gal(d).select("building_999.glb"))

    print("\n[6] deleting re-points the selection instead of dangling")
    g = gal(d)
    g.select(old.name, "low")
    g = gal(d)
    check("deleting the active full file works", g.delete("building_100.glb"))
    g = gal(d)
    check("the default tier moved to the newest remaining file",
          (g.find() or Path()).name == old.name, str(g.find()))
    check("the sidecar went with it",
          not (d / "building_100.json").exists())
    g = gal(d)
    check("deleting everything leaves nothing selected",
          g.delete() and gal(d).find() is None)

    print("\n[7] props: two uploads, two tiers, one record")
    from app.core import props
    prop = props.create_prop(name="Smoke Chair", width_m=0.5, depth_m=0.5,
                             height_m=1.0)
    pid = prop["id"]
    check("a fresh prop has no mesh",
          props.get_prop(pid)["has_model"] is False
          and props.get_prop(pid)["model_tiers"] == [])
    props.save_uploaded_glb(pid, b"glTF-full")
    props.save_uploaded_glb(pid, b"glTF-low", "low")
    rec = props.get_prop(pid)
    check("both tiers are reported", rec["model_tiers"] == ["full", "low"],
          str(rec["model_tiers"]))
    check("has_model follows the selection", rec["has_model"] is True)
    check("full and low are DIFFERENT files",
          props.model_path(pid, "full") != props.model_path(pid, "low"),
          f'{props.model_path(pid, "full")} / {props.model_path(pid, "low")}')
    check("the full file is the one uploaded as full",
          props.model_path(pid, "full").read_bytes() == b"glTF-full")
    check("the low file is the one uploaded as low",
          props.model_path(pid, "low").read_bytes() == b"glTF-low")
    sig = rec["model_signature"]
    props.save_uploaded_glb(pid, b"glTF-low-2", "low")
    check("a new LOW mesh moves the prop's model signature",
          props.get_prop(pid)["model_signature"] != sig,
          f'{sig} -> {props.get_prop(pid)["model_signature"]}')
    check("the master record carries no per-run mesh fields any more",
          not {"face_num", "texture_size"} & set(props.read_sidecar(pid)),
          str(sorted(props.read_sidecar(pid))))

    print("\n[8] props: the admin gallery (Etappe 2)")
    # State after [7]: THREE uploads on this prop — #1 selected for full,
    # #2 for nothing any more (superseded), #3 for low.
    full_name = props.model_path(pid, "full").name
    low_name = props.model_path(pid, "low").name
    listed = props.list_models(pid)
    by_name = {m["filename"]: m for m in listed}
    check("all three stored meshes are listed", len(listed) == 3,
          str(sorted(by_name)))
    check("exactly one entry is the active (no-tier-requested) file",
          [m["filename"] for m in listed if m["active"]] == [full_name],
          str([m["filename"] for m in listed if m["active"]]))
    check("the full file serves exactly the full tier",
          by_name[full_name]["selected_for"] == ["full"],
          str(by_name[full_name]["selected_for"]))
    check("the newest low upload serves exactly the low tier",
          by_name[low_name]["selected_for"] == ["low"],
          str(by_name[low_name]["selected_for"]))
    superseded = [n for n in by_name if n not in (full_name, low_name)]
    check("the superseded upload serves NO tier (it stays listed)",
          len(superseded) == 1 and by_name[superseded[0]]["selected_for"] == [],
          str(superseded))
    check("each file reports the tier it was MADE for",
          by_name[full_name]["tier"] == "full"
          and by_name[low_name]["tier"] == "low",
          f'{by_name[full_name]["tier"]} / {by_name[low_name]["tier"]}')
    info = props.get_model_info(pid)
    check("get_model_info publishes both tiers", info["tiers"] == ["full", "low"],
          str(info["tiers"]))
    check("...and nothing is switched off", info["none_selected"] is False)

    check("a stored file is servable by name",
          props.model_file_path(pid, low_name) is not None)
    check("a path escape / foreign stem is not",
          props.model_file_path(pid, "../../sidecar.json") is None
          and props.model_file_path(pid, "building_1.glb") is None)

    check("deselecting the default tier switches the whole prop off",
          props.select_model(pid, "", "full"))
    off = props.get_model_info(pid)
    check("...none_selected is reported and no tier is left",
          off["none_selected"] is True and off["tiers"] == [], str(off["tiers"]))
    check("selecting a file again brings it back",
          props.select_model(pid, full_name, "full")
          and props.get_model_info(pid)["tiers"] == ["full", "low"])
    check("a file that is not in this gallery is never selectable",
          not props.select_model(pid, "model_999.glb", "low"))

    check("deleting the low file works", props.delete_model(pid, low_name))
    after = props.get_model_info(pid)
    check("...the low tier ceases to exist (no dangling selection)",
          after["tiers"] == ["full"], str(after["tiers"]))
    check("...and only two files remain", len(after["models"]) == 2,
          str([m["filename"] for m in after["models"]]))
    check("low now falls back to the full mesh",
          props.model_path(pid, "low").name == full_name,
          str(props.model_path(pid, "low")))

    print(f"\n{'FAILED: ' + ', '.join(FAILURES) if FAILURES else 'all checks passed'}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        shutil.rmtree(WORLD, ignore_errors=True)
