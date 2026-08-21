#!/usr/bin/env python3
"""Smoke run for a prop's MODEL VARIANTS (E2.3, § B2-Nachtrag).

No world, no DB, no server: a throwaway props directory in /tmp gets prop
records and GLB stubs written through the real store, and the store plus the
scene composer are asked what they answer. Every expected value is derived BY
HAND from the contract (docs/schnittstellen-3d.md, "Nachtrag 2026-08-19 (§ B2)"),
never from what the code currently prints:

  - a prop without the variant key has exactly ONE variant, the primary one,
    and every unqualified read still resolves to it;
  - generating APPENDS: the first mesh fills the existing empty slot, the
    second one a fresh variant, and at the cap the last variant takes it;
  - the cap is on ACTIVE variants and comes from
    `image_generation.prop_variant_max` (default 4);
  - `variants == model_variants[0]` on every placement spec — the primary
    variant contract that keeps unchanged consumers rendering;
  - the primary variant keeps its bare URL, a further one carries
    `?variant=<i>&tier=<t>` (ONE `?`, then `&`) — and `<i>` is the variant's
    OWN store index, not its position, so switching variant 1 off must leave
    the second payload entry pointing at `?variant=2`;
  - the scatter formula is `(scatter_seed + instance) mod count`. HAND
    CALCULATION with 3 active variants and scatter_seed 7, instances 0…5:

        (7 + 0) mod 3 = 7 mod 3  = 1
        (7 + 1) mod 3 = 8 mod 3  = 2
        (7 + 2) mod 3 = 9 mod 3  = 0
        (7 + 3) mod 3 = 10 mod 3 = 1
        (7 + 4) mod 3 = 11 mod 3 = 2
        (7 + 5) mod 3 = 12 mod 3 = 0

    → 1, 2, 0, 1, 2, 0.

THE SOURCE IMAGE FOLLOWS THE MESH (2026-08-20). A variant is a whole version
of the object, so the product shot it was meshed from belongs to it. The file
name is derived BY HAND from the stored mesh stem, by the same suffix:

    variant 0  stem `model`     → `source.png`      (the historic name)
    variant 1  stem `model-v2`  → `source-v2.png`
    variant 2  stem `model-v3`  → `source-v3.png`

The stem is what the name follows, NOT the list position — deleting a middle
variant must not rename its neighbour's picture any more than it renames its
meshes. From that one law the rest is derivable and checked below:

  - a render into variant 1 writes `source-v2.png` and leaves `source.png`
    byte-identical; the re-mesh of variant 1 feeds `source-v2.png` to the
    mesher, never variant 0's picture (that was the defect: one image, so an
    older variant's re-mesh produced a mesh of the wrong object);
  - deleting variant 1 removes `source-v2.png` and nothing else;
  - the scene-asset pipeline hands its cutout to the SAME writer with the
    run's target variant, so a later re-mesh reproduces that very picture —
    with its alpha, because the cutout is transparent outside the object.

THE LIBRARY LIST FLAGS INCOMPLETE VARIANTS (2026-08-20). The admin record
carries three counts over the ACTIVE variants — `variants_total`,
`variants_missing_mesh`, `variants_missing_image` — and nothing else: the row
badge says THAT a variant is missing something, the variant strip in the detail
says which. HAND CASE, three active variants:

    variant 0   mesh + source image     complete
    variant 1   mesh, no source image   → variants_missing_image
    variant 2   source image, no mesh   → variants_missing_mesh

    → variants_total 3, variants_missing_mesh 1, variants_missing_image 1

A switched-off variant renders nowhere, so it cannot be missing anything
either: switching variant 2 off leaves 2 / 0 / 1.

WHERE THE PICTURE WAS TAKEN (2026-08-20). A source image is either a product
shot (the object alone on neutral ground) or a scene-context cutout (drawn into
a rendered spot and cut back out of it). The second carries that spot's light
and ground, so the two are not interchangeable and the admin has to see which
is which. The contract is deliberately the CHEAP one, and section 16 derives it
by hand from that choice:

    origin ABSENT  → product shot     (every image ever written; no migration)
    origin "scene_context" + origin_location / origin_location_id / origin_ts

From "absence is the product shot" three things follow and are checked:

  - the ordinary generation chain writes NO origin key at all — not an empty
    one, because an empty key and an absent key would mean the same thing and
    only one of them may exist;
  - the origin survives `list_variants`, i.e. the variant-list SANITIZER: it
    rebuilds every entry from a whitelist, so a key it does not know is
    silently dropped on the next write to ANY variant of the same prop;
  - a re-render as a product shot CLEARS it, on the variant entry and on the
    master record alike — a stale location would keep pointing at a spot the
    new picture was never taken at.

THE IN-FLIGHT GUARD IS PER (PROP, VARIANT) (2026-08-20). A variant is a whole
version of the object, so a run belongs to ONE of them — the guard key is
``prop | store variant index | backend``, and what it protects against is the
DOUBLE START of the same job, nothing else. From that one law follows what is
checked in section 17, and the user finding it comes from:

  - two variants of the same prop generate side by side (the GPU channel
    serializes the backend work; the guard is not a second queue);
  - the same variant on the same backend a second time is refused;
  - an unqualified run resolves ``None`` to the PRIMARY variant's index, so the
    plain route and the primary variant's own route are the SAME key — one
    picture, one job;
  - the admin is told WHICH variant runs, by STORE index: rendering variant 3's
    image put "Generating…" on variant 1 as long as the state was a per-prop
    boolean. A switched-off variant keeps its index, so the mapping case is
    checked with one variant off — indices, never positions;
  - adding a slot during a run is ACCEPTED (it appends at the end and renumbers
    nothing), while deleting or toggling the RUNNING variant is refused — a
    delete would take the files the job is writing and renumber its neighbours.

SEASON-TAGGED VARIANTS (E2c, 2026-08-20). A variant may name the seasons it
depicts; EFFECTIVELY active = manually active AND (no tag OR the world's
current season among them), matched case-insensitively against the season's
key and names. Section 18 derives its cases by hand from the shipped calendar
(4 seasons × 30 days, spring/summer/autumn/winter → season starts 0/30/60/90,
so day-of-year 5/35/65/95 is day 5 of spring/summer/autumn/winter):

  - a birch with variants [untagged, "Winter", "Spring"+"SUMMER"] renders
    [0, 1] in winter, [0, 2] in spring AND in summer (the tag "SUMMER" is
    matched lowercased), and [0] in autumn;
  - an oak with ONLY tagged variants ["Summer"] / ["Winter"] moves its PRIMARY
    variant with the season — and the bare `/model` URL, which is what every
    payload publishes as element 0, has to serve that same mesh;
  - in autumn NEITHER oak variant matches: the manual set stands, because a
    placement must never become a hole (props._effective_indices);
  - the library badges (`variants_total`) stay on the MANUAL set — a summer
    variant without a mesh is still a to-do while the world is in winter;
  - INERTNESS, twice over: an untagged prop answers byte-identically in every
    season, and a world whose calendar has no seasons ignores every tag;
  - the SCENE signature carries the season, so a season change reaches a
    polling client even where nothing stored has moved.

Usage:  ./.venv/bin/python scripts/smoke_prop_variants.py
"""
import ast
import io
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

WORLD = Path(tempfile.mkdtemp(prefix="prop-variants-smoke-"))
os.environ["STORAGE_DIR"] = str(WORLD)

from app.core import paths  # noqa: E402

paths.init(WORLD)

from app.core import props as store  # noqa: E402
from app.core.model_store import write_sidecar  # noqa: E402
from app.core.scene_recipe import _prop_models  # noqa: E402

FAILURES = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {label}{f' — {detail}' if detail else ''}")
    if not ok:
        FAILURES.append(label)


def put_mesh(prop_id: str, variant, tier: str = "full") -> str:
    """A stored GLB stub in ONE variant's gallery, selected for ``tier``.

    Deliberately NOT through the generation chain: this smoke is about the
    variant bookkeeping, and a GPU job has no place in it. The bytes are a
    stub, so nothing here may measure them (the store only measures the
    PRIMARY variant, and a stub simply yields no bbox)."""
    g = store.model_gallery(prop_id, variant)
    assert g is not None
    p = g.new_path()
    p.write_bytes(b"glTF-stub")
    write_sidecar(p, {"created_at": "2026-08-19T10:00:00+00:00",
                      "source": "upload", "format": "glb", "tier": tier})
    g.select(p.name, tier)
    return p.name


def png_bytes(color, *, alpha: bool = False) -> bytes:
    """A tiny PNG — the stand-in for a rendered product shot / a cutout."""
    from PIL import Image
    img = Image.new("RGBA" if alpha else "RGB", (32, 32),
                    (*color, 0) if alpha else color)
    if alpha:
        # Opaque in the middle, transparent around it — a cutout's shape.
        for x in range(8, 24):
            for y in range(8, 24):
                img.putpixel((x, y), (*color, 255))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


# ── The GPU stand-ins for the generation chain ──────────────────────────
# The chain is two GPU steps around pure bookkeeping, and only the bookkeeping
# is under test here: WHICH file the render writes and WHICH file the mesher
# is handed. Both steps are replaced by stubs that record their inputs, so the
# real `_generate` runs from end to end without a backend.

MESH_INPUTS: list = []


class FakeBackend:
    name = "fake-image"
    api_type = "fake"
    image_family = ""
    model = ""

    def generate(self, prompt, negative, params, log_meta=None):
        return [png_bytes((10, 200, 30))]


class FakeQueue:
    def submit_gpu_task(self, **kw):
        return kw["callable_fn"]()


class FakeService:
    def resolve_imagegen_target(self, glob):
        return FakeBackend()

    def _select_backend(self):
        return FakeBackend()

    def generate_mesh(self, *, source_image_path, output_path, **kw):
        MESH_INPUTS.append(Path(source_image_path).name)
        Path(output_path).write_bytes(b"glTF-stub")
        return {"ok": True, "path": output_path, "format": "glb",
                "rig": "none", "backend": "fake-mesh"}


def install_fakes() -> None:
    import app.core.llm_queue as llm_queue
    import app.core.model3d as model3d
    import app.imagegen.service as image_service
    image_service.get_image_service = lambda: FakeService()
    llm_queue.get_llm_queue = lambda: FakeQueue()
    model3d.list_mesh_backends = lambda rig: {"default": "fake-mesh",
                                              "backends": []}


def scene_asset_writes_cutout_with_variant() -> bool:
    """Does ``scene_asset._attempt`` hand its cutout to the prop store WITH
    the run's variant?

    The pipeline step itself needs an image backend and a GPU, so the wiring
    is read out of the source instead: the call must be
    ``save_source_image(prop_id, <cutout bytes>, variant, …)``. A call that
    dropped the third argument would write into the PRIMARY variant — the very
    defect this law exists against, and one no pure check downstream could
    see."""
    src = Path(__file__).resolve().parents[1] / "app" / "core" / "scene_asset.py"
    tree = ast.parse(src.read_text())
    for fn in ast.walk(tree):
        if not (isinstance(fn, ast.FunctionDef) and fn.name == "_attempt"):
            continue
        for node in ast.walk(fn):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "save_source_image"):
                continue
            args = node.args
            return (len(args) >= 3
                    and isinstance(args[2], ast.Name)
                    and args[2].id == "variant")
    return False


def placement(prop_id: str, **extra) -> dict:
    """A room-recipe placement of one prop, as `_prop_models` receives it."""
    prop = store.get_prop(prop_id) or {}
    entry = {
        "prop_id": prop_id,
        "at": [1.0, 2.0],
        "yaw": 0.0,
        "offset_y": 0.0,
        "has_model": bool(prop.get("has_model")),
        "dims": {"width_m": prop.get("width_m", 1.0),
                 "depth_m": prop.get("depth_m", 1.0),
                 "height_m": prop.get("height_m", 1.0)},
        "model_tiers": prop.get("model_tiers") or [],
        "variant_tiers": prop.get("variant_tiers") or [],
    }
    entry.update(extra)
    return entry


def spec_of(prop_id: str, **extra) -> dict:
    """The finished placement spec the payload carries for one placement."""
    recipe = {"room_id": "r1", "level": 0, "always_visible": True,
              "placements": [placement(prop_id, **extra)]}
    # storey 0: this smoke asserts the variant bookkeeping of the spec
    # (`variants` / `model_variants` / `variant`), never its `bottom_y`. The
    # ``slab`` argument is gone with "Ein Boden" E5a — storey 0 has no plate.
    return _prop_models(recipe, 0.0)[0]


# ── Season fixture (E2c) ────────────────────────────────────────────────
# The world clock lives in world_kv and this smoke has no DB, so the two
# inputs of `game_time.current_season_tokens` are set directly: the CALENDAR
# (the shipped default — 4 seasons × 30 days, spring/summer/autumn/winter)
# and the INSTANT. That is the fixture, not the code under test: everything
# below reads the season through the real resolution.
#
# The instant is derived BY HAND. Season starts are the cumulative lengths
# 0/30/60/90, so day-of-year `i × 30 + 5` (1-based) is day 5 of season i:
#
#     spring -> day  5   summer -> day 35
#     autumn -> day 65   winter -> day 95
#
# and a GameTime counts whole seconds from Year 1 Day 1 00:00, so day D at
# noon is `(D - 1) × 86400 + 43200`. Winter: 94 × 86400 + 43200 = 8_164_800.

SEASON_KEYS = ("spring", "summer", "autumn", "winter")


def set_season(key: str) -> None:
    """Put the world into season ``key`` (see the hand derivation above)."""
    from app.core import game_time as gt
    from app.core import timeutils
    gt._CALENDAR_CACHE = gt.Calendar.default()
    day = SEASON_KEYS.index(key) * 30 + 5
    gt._SMOKE_NOW = gt.GameTime((day - 1) * gt.DAY_SECONDS + 12 * 3600)
    timeutils.game_time = lambda: gt._SMOKE_NOW


def set_no_seasons() -> None:
    """A world whose calendar has NO seasons at all — the inert case."""
    from app.core import game_time as gt
    gt._CALENDAR_CACHE = gt.Calendar(seasons=())


def season_section() -> None:
    from app.core import game_time as gt

    print("\n[18] SEASON-tagged variants (E2c)")
    set_season("winter")
    cal = gt.Calendar.default()
    parts = gt._SMOKE_NOW.parts(cal)
    check("the fixture really lands on winter, day 5",
          cal.seasons[parts.season_index].key == "winter"
          and parts.day_of_season == 5,
          f"{cal.seasons[parts.season_index].key} d{parts.day_of_season}")

    # ── The sanitizer: what a `seasons` field may be ──
    birch = store.create_prop(name="Birch")["id"]
    put_mesh(birch, 0)
    put_mesh(birch, store.target_variant(birch))     # variant 1
    put_mesh(birch, store.target_variant(birch))     # variant 2
    check("three variants to work with", len(store.list_variants(birch)) == 3,
          str([v["stem"] for v in store.list_variants(birch)]))
    store.set_variant_seasons(birch, 1, ["Winter"])
    store.set_variant_seasons(birch, 2, ["Spring", "SUMMER", "spring", "",
                                         None, {"x": 1}])
    vs = store.list_variants(birch)
    check("an untagged variant stores NO key at all",
          store.read_sidecar(birch)["model_variants"][0].get("seasons") is None,
          str(store.read_sidecar(birch)["model_variants"][0]))
    check("tags are kept VERBATIM", vs[1]["seasons"] == ["Winter"],
          str(vs[1]["seasons"]))
    check("case-insensitive dedupe, junk dropped",
          vs[2]["seasons"] == ["Spring", "SUMMER"], str(vs[2]["seasons"]))

    # ── The gate: manually active AND in season ──
    # HAND CASE, world in WINTER:
    #   variant 0  no tag            -> in season (no dependency)
    #   variant 1  ["Winter"]        -> in season
    #   variant 2  ["Spring","SUMMER"] -> OUT
    #   => effective [0, 1]
    check("winter: the untagged and the winter variant render",
          [e["variant"] for e in store.active_variant_tiers(birch)] == [0, 1],
          str([e["variant"] for e in store.active_variant_tiers(birch)]))
    check("...and the recipe list agrees (one gate, not two)",
          [e["variant"] for e in (store.get_prop(birch) or {})["variant_tiers"]]
          == [0, 1])
    check("in_season says which is which",
          [v["in_season"] for v in store.list_variants(birch)]
          == [True, True, False])
    set_season("spring")
    check("spring: the SUMMER/SPRING variant renders instead — [0, 2]",
          [e["variant"] for e in store.active_variant_tiers(birch)] == [0, 2],
          str([e["variant"] for e in store.active_variant_tiers(birch)]))
    check("case-insensitive match: 'SUMMER' finds the summer season",
          (set_season("summer") or
           [e["variant"] for e in store.active_variant_tiers(birch)]) == [0, 2])
    set_season("autumn")
    check("autumn: neither tag matches, only the untagged one is left — [0]",
          [e["variant"] for e in store.active_variant_tiers(birch)] == [0],
          str([e["variant"] for e in store.active_variant_tiers(birch)]))
    store.set_variant_seasons(birch, 1, [])
    check("clearing a tag drops the key and the variant is back",
          store.read_sidecar(birch)["model_variants"][1].get("seasons") is None
          and [e["variant"] for e in store.active_variant_tiers(birch)] == [0, 1])
    store.set_variant_seasons(birch, 1, ["Winter"])

    # ── The primary variant follows the season, and so does the bare URL ──
    # HAND CASE: an oak with a summer and a winter variant and NOTHING
    # untagged. In winter the effective list is [1] alone, so the payload's
    # single `variants` map — the bare URL — has to serve variant 1's mesh.
    oak = store.create_prop(name="Oak")["id"]
    put_mesh(oak, 0)
    put_mesh(oak, store.target_variant(oak))
    store.set_variant_seasons(oak, 0, ["Summer"])
    store.set_variant_seasons(oak, 1, ["Winter"])
    set_season("winter")
    check("winter: the summer variant is gone, the winter one is primary",
          [e["variant"] for e in store.active_variant_tiers(oak)] == [1]
          and store.primary_variant(oak) == 1)
    check("...and the BARE model URL serves that very mesh",
          store.model_path(oak).name == store.model_path(oak, variant=1).name,
          store.model_path(oak).name)
    check("...which is variant 1's stem, not variant 0's",
          store._stem_of(oak) == "model-v2", store._stem_of(oak))
    set_season("summer")
    check("summer: the other way round",
          [e["variant"] for e in store.active_variant_tiers(oak)] == [0]
          and store.primary_variant(oak) == 0
          and store._stem_of(oak) == "model")
    set_season("autumn")
    # DEGENERATE CASE: no variant is in season. The manual set stands — a
    # placement must never become a hole (see props._effective_indices).
    check("autumn: NEITHER matches, so the manual set stands — [0, 1]",
          [e["variant"] for e in store.active_variant_tiers(oak)] == [0, 1],
          str([e["variant"] for e in store.active_variant_tiers(oak)]))

    # ── The library badges stay on the MANUAL set ──
    # The oak has 2 manually active variants all year; in winter only one of
    # them renders, and the row must still say "2".
    set_season("winter")
    rec = store.get_prop(oak) or {}
    check("variants_total counts the manual actives, not the in-season ones",
          rec["variants_total"] == 2, str(rec["variants_total"]))
    check("...while variant_count is what renders now", rec["variant_count"] == 1,
          str(rec["variant_count"]))

    # ── INERTNESS 1: a prop nobody tagged is byte-identical ──
    fir = store.create_prop(name="Fir")["id"]
    put_mesh(fir, 0)
    put_mesh(fir, store.target_variant(fir))
    set_season("spring")
    spring = json.dumps([store.active_variant_tiers(fir),
                         store.list_variants(fir)], sort_keys=True)
    set_season("winter")
    winter = json.dumps([store.active_variant_tiers(fir),
                         store.list_variants(fir)], sort_keys=True)
    check("an untagged prop answers byte-identically in every season",
          spring == winter, spring[:60])

    # ── INERTNESS 2: a world without seasons ignores the tags ──
    set_no_seasons()
    check("no seasons in the world: every tagged variant renders again",
          [e["variant"] for e in store.active_variant_tiers(birch)] == [0, 1, 2]
          and [e["variant"] for e in store.active_variant_tiers(oak)] == [0, 1])
    check("...and in_season is True for all of them",
          [v["in_season"] for v in store.list_variants(birch)]
          == [True, True, True])

    # ── The SCENE signature carries the season ──
    # `_signature` is pure, so the two calls differ in nothing but the clock.
    from app.core.scene_recipe import _signature
    set_season("spring")
    sig_spring = _signature({"map3d": {}}, 0.0, [], {}, {})
    sig_spring2 = _signature({"map3d": {}}, 0.0, [], {}, {})
    set_season("winter")
    sig_winter = _signature({"map3d": {}}, 0.0, [], {}, {})
    check("the scene signature is stable within a season",
          sig_spring == sig_spring2)
    check("...and moves when the season does — polling clients refetch",
          sig_spring != sig_winter, f"{sig_spring[:8]} vs {sig_winter[:8]}")
    set_no_seasons()
    sig_none_a = _signature({"map3d": {}}, 0.0, [], {}, {})
    set_season("winter")
    set_no_seasons()
    check("a world without seasons has ONE signature, whatever the clock says",
          sig_none_a == _signature({"map3d": {}}, 0.0, [], {}, {}))


def main() -> int:
    print("\n[1] a prop without the key has ONE variant — the primary one")
    pine = store.create_prop(name="Pine")["id"]
    vs = store.list_variants(pine)
    check("exactly one variant", len(vs) == 1, str(vs))
    check("it is stem 'model' — the historic file name", vs[0]["stem"] == "model")
    check("it is active and primary", vs[0]["active"] and vs[0]["primary"])
    check("primary_variant() is 0", store.primary_variant(pine) == 0)
    check("no mesh yet, so no tiers", vs[0]["tiers"] == [], str(vs[0]["tiers"]))

    print("\n[2] generating APPENDS: empty slot first, then fresh variants")
    check("the first target is the EXISTING empty slot 0",
          store.target_variant(pine) == 0, str(store.target_variant(pine)))
    put_mesh(pine, 0)
    check("...and slot 0 now carries the mesh",
          store.model_tiers(pine, 0) == ["full"], str(store.model_tiers(pine, 0)))
    nxt = store.target_variant(pine)
    check("the NEXT target is a freshly appended variant 1", nxt == 1, str(nxt))
    put_mesh(pine, 1)
    put_mesh(pine, store.target_variant(pine))
    check("three variants exist", len(store.list_variants(pine)) == 3,
          str([v["stem"] for v in store.list_variants(pine)]))
    check("their stems are model / model-v2 / model-v3",
          [v["stem"] for v in store.list_variants(pine)]
          == ["model", "model-v2", "model-v3"],
          str([v["stem"] for v in store.list_variants(pine)]))
    check("...and every stem has its OWN file, none shared",
          len({store.model_path(pine, variant=i).name for i in range(3)}) == 3)

    print("\n[3] the cap is on ACTIVE variants (config default 4)")
    check("variant_max() is 4", store.variant_max() == 4, str(store.variant_max()))
    put_mesh(pine, store.target_variant(pine))          # fills variant 3
    check("four variants now", len(store.list_variants(pine)) == 4)
    at_cap = store.target_variant(pine)
    check("at the cap the target is the LAST variant, not a fifth one",
          at_cap == 3, str(at_cap))
    check("add_variant() refuses at the cap", store.add_variant(pine) == -1)
    check("...and no fifth variant was written",
          len(store.list_variants(pine)) == 4)
    check("switching one off frees a slot again",
          store.set_variant_active(pine, 3, False)
          and store.add_variant(pine) == 4)
    check("...leaving 5 records but only 4 active",
          len(store.list_variants(pine)) == 5
          and sum(1 for v in store.list_variants(pine) if v["active"]) == 4)
    store.delete_variant(pine, 4)
    store.set_variant_active(pine, 3, True)

    print("\n[4] the last active variant cannot be switched off or deleted")
    stool = store.create_prop(name="Stool")["id"]
    put_mesh(stool, 0)
    check("switching the only variant off is refused",
          not store.set_variant_active(stool, 0, False))
    check("deleting the only variant is refused",
          not store.delete_variant(stool, 0))
    check("...and it is still there with its mesh",
          store.model_tiers(stool, 0) == ["full"])

    print("\n[5] payload: variants == model_variants[0], primary URL unchanged")
    fern = store.create_prop(name="Fern")["id"]
    put_mesh(fern, 0)
    put_mesh(fern, 0, tier="low")
    put_mesh(fern, store.target_variant(fern))
    check("the record lists tiers per active variant, with its store index",
          (store.get_prop(fern) or {}).get("variant_tiers")
          == [{"variant": 0, "tiers": ["full", "low"]},
              {"variant": 1, "tiers": ["full"]}],
          str((store.get_prop(fern) or {}).get("variant_tiers")))
    spec = spec_of(fern)
    check("model_variants has one map per active variant",
          len(spec.get("model_variants") or []) == 2,
          str(spec.get("model_variants")))
    check("variants IS model_variants[0] (the primary variant contract)",
          spec["variants"] == spec["model_variants"][0], str(spec["variants"]))
    check("the primary variant keeps the BARE url + ?tier=",
          spec["variants"] == {"full": f"/assets/props/{fern}/model?tier=full",
                               "low": f"/assets/props/{fern}/model?tier=low"},
          str(spec["variants"]))
    check("a further variant carries ?variant=<i>&tier=<t> — one '?', then '&'",
          spec["model_variants"][1]
          == {"full": f"/assets/props/{fern}/model?variant=1&tier=full"},
          str(spec["model_variants"][1]))
    check("an unqualified placement shows the primary variant",
          spec.get("variant") == 0, str(spec.get("variant")))

    print("\n[6] a ONE-variant prop's spec is unchanged — no new fields")
    one = spec_of(stool)
    check("no model_variants field", "model_variants" not in one, str(one.keys()))
    check("no variant field", "variant" not in one)
    check("variants is the plain tier map",
          one["variants"] == {"full": f"/assets/props/{stool}/model?tier=full"},
          str(one["variants"]))

    print("\n[7] the scatter formula — hand calculation in the docstring")
    expected = [1, 2, 0, 1, 2, 0]
    got = [store.scatter_variant_index(7, i, 3) for i in range(6)]
    check("seed 7, 3 variants, instances 0..5 -> 1,2,0,1,2,0",
          got == expected, f"{got} vs {expected}")
    check("count 0 (a prop with no mesh) answers 0, never a division",
          store.scatter_variant_index(7, 3, 0) == 0)
    check("count 1 always answers 0",
          [store.scatter_variant_index(7, i, 1) for i in range(4)] == [0, 0, 0, 0])
    # …and the resolved index reaches the spec: three variants, seed 7.
    put_mesh(fern, store.target_variant(fern))          # fern now has 3
    check("fern has three active variants now",
          len((store.get_prop(fern) or {}).get("variant_tiers") or []) == 3)
    scattered = [spec_of(fern, scattered=True,
                         variant=store.scatter_variant_index(7, i, 3))["variant"]
                 for i in range(6)]
    check("the spec carries exactly those indices", scattered == expected,
          f"{scattered} vs {expected}")
    check("an out-of-range index WRAPS instead of dropping the placement",
          spec_of(fern, variant=5)["variant"] == 2,
          str(spec_of(fern, variant=5)["variant"]))

    print("\n[8] switching a variant off removes it from the payload")
    store.set_variant_active(fern, 1, False)
    off = spec_of(fern)
    check("two variants left in the payload",
          len(off["model_variants"]) == 2, str(off["model_variants"]))
    check("...and the primary one is untouched",
          off["variants"] == spec["variants"], str(off["variants"]))
    check("the remaining second map is variant 2's url",
          off["model_variants"][1]
          == {"full": f"/assets/props/{fern}/model?variant=2&tier=full"},
          str(off["model_variants"][1]))

    print("\n[9] deleting a variant takes its files, not its neighbour's")
    keep = store.model_path(fern, variant=2)
    check("variant 1's file exists before the delete",
          store.model_path(fern, variant=1) is not None)
    gone = store.model_path(fern, variant=1)
    check("delete_variant succeeds", store.delete_variant(fern, 1))
    check("...its file is gone", not gone.exists())
    check("...the neighbour's file is untouched", keep.exists())
    check("...and the list is two records long",
          [v["stem"] for v in store.list_variants(fern)] == ["model", "model-v3"],
          str([v["stem"] for v in store.list_variants(fern)]))

    print("\n[10] the source image is named after the STEM, like the meshes")
    check("stem 'model' keeps the historic source.png",
          store.source_name("model") == "source.png", store.source_name("model"))
    check("stem 'model-v2' -> source-v2.png",
          store.source_name("model-v2") == "source-v2.png",
          store.source_name("model-v2"))
    check("stem 'model-v3' -> source-v3.png",
          store.source_name("model-v3") == "source-v3.png",
          store.source_name("model-v3"))
    check("a stem this store would never hand out has no image name",
          store.source_name("../etc") == "" and store.source_name("") == "")

    print("\n[11] generating into variant 1 writes ITS image, not variant 0's")
    install_fakes()
    lamp = store.create_prop(name="Lamp")["id"]
    ok0 = store._generate(lamp, "a lamp", "", "fake", "fake-mesh", variant=0)
    d = Path(store.prop_dir(lamp))
    v0_img = d / "source.png"
    check("the first run fills variant 0 through the chain", ok0.get("ok"), str(ok0))
    check("...writing source.png — the historic name, no migration for it",
          v0_img.exists() and not (d / "source-v2.png").exists(),
          str(sorted(p.name for p in d.glob("source*"))))
    v0_before = v0_img.read_bytes()
    check("...and the mesher was handed exactly that file",
          MESH_INPUTS == ["source.png"], str(MESH_INPUTS))

    MESH_INPUTS.clear()
    second = store.target_variant(lamp)
    check("the next run targets a fresh variant 1", second == 1, str(second))
    ok1 = store._generate(lamp, "another lamp", "", "fake", "fake-mesh",
                          variant=second)
    v1_img = d / "source-v2.png"
    check("the second run went through", ok1.get("ok"), str(ok1))
    check("...it wrote source-v2.png (variant 1 = stem model-v2)",
          v1_img.exists(), str(sorted(p.name for p in d.glob("source*"))))
    check("...and left variant 0's picture byte-identical",
          v0_img.read_bytes() == v0_before)
    check("...the mesher for variant 1 was handed variant 1's image",
          MESH_INPUTS == ["source-v2.png"], str(MESH_INPUTS))
    check("source_path() unqualified still answers the PRIMARY image",
          store.source_path(lamp) == v0_img, str(store.source_path(lamp)))
    check("...and each variant answers with its own",
          (store.source_path(lamp, 0), store.source_path(lamp, 1))
          == (v0_img, v1_img))
    check("an index the prop has no variant for has no image",
          store.source_path(lamp, 7) is None)
    vs = store.list_variants(lamp)
    check("the strip gets both images, the primary one WITHOUT a query",
          [v["source_url"] for v in vs]
          == [f"/assets/props/{lamp}/source",
              f"/assets/props/{lamp}/source?variant=1"],
          str([v["source_url"] for v in vs]))
    check("...and each variant's own provenance beside it",
          [v["image"]["prompt"] for v in vs] == ["a lamp", "another lamp"],
          str([v["image"]["prompt"] for v in vs]))
    check("the prop record shows the PRIMARY variant's provenance",
          (store.get_prop(lamp) or {}).get("prompt") == "a lamp",
          str((store.get_prop(lamp) or {}).get("prompt")))

    print("\n[12] a re-mesh reads the image of the variant it refines")
    MESH_INPUTS.clear()
    re0 = store._generate(lamp, "", "", "", "fake-mesh", mesh_only=True,
                          variant=0)
    re1 = store._generate(lamp, "", "", "", "fake-mesh", mesh_only=True,
                          variant=1)
    check("both re-meshes ran", re0.get("ok") and re1.get("ok"),
          f"{re0} / {re1}")
    check("variant 0's re-mesh read source.png, variant 1's source-v2.png",
          MESH_INPUTS == ["source.png", "source-v2.png"], str(MESH_INPUTS))
    check("no image was rendered for a re-mesh (both files unchanged)",
          v0_img.read_bytes() == v0_before)

    print("\n[13] deleting a variant takes ITS image and no other")
    check("delete_variant(1) succeeds", store.delete_variant(lamp, 1))
    check("...source-v2.png is gone", not v1_img.exists())
    check("...source.png is untouched",
          v0_img.exists() and v0_img.read_bytes() == v0_before)
    check("...and the freed slot starts without an image",
          store.add_variant(lamp) == 1 and store.source_path(lamp, 1) is None)

    print("\n[14] the scene-asset cutout becomes the target variant's image")
    # The pipeline picks its variant ONCE per run (`props.target_variant`) and
    # hands the cutout to the same writer — checked here on the writer, and on
    # the call site's wiring, because the pipeline itself needs a GPU.
    stone = store.create_prop(name="Stone")["id"]
    put_mesh(stone, 0)                                  # variant 0 is taken
    target = store.target_variant(stone)
    check("a prop with one meshed variant targets a fresh variant 1",
          target == 1, str(target))
    cutout = png_bytes((200, 30, 30), alpha=True)
    check("the cutout is stored as that variant's source image",
          store.save_source_image(stone, cutout, target, backend="fake-image",
                                  prompt="a stone"))
    sp = store.source_path(stone, target)
    check("...under the name its stem dictates",
          sp is not None and sp.name == "source-v2.png", str(sp))
    check("...variant 0 keeps having none (its mesh was uploaded)",
          store.source_path(stone, 0) is None)
    from PIL import Image
    saved = Image.open(sp)
    check("...and the transparency survived — a cutout is transparent "
          "outside the object",
          saved.mode == "RGBA" and saved.getpixel((0, 0))[3] == 0
          and saved.getpixel((16, 16))[3] == 255,
          f"{saved.mode} {saved.getpixel((0, 0))}")
    MESH_INPUTS.clear()
    store._generate(stone, "", "", "", "fake-mesh", mesh_only=True,
                    variant=target)
    check("...so a later re-mesh of that variant reproduces that picture",
          MESH_INPUTS == ["source-v2.png"], str(MESH_INPUTS))
    check("the pipeline hands the cutout to the writer WITH the run's variant",
          scene_asset_writes_cutout_with_variant())

    print("\n[15] the record counts INCOMPLETE variants — the library badges")
    # Hand case (docstring): three active variants, one without a mesh, one
    # without a source image → 3 / 1 / 1.
    #   variant 0  mesh + image        complete
    #   variant 1  mesh, no image      counts in variants_missing_image
    #   variant 2  image, no mesh      counts in variants_missing_mesh
    crate = store.create_prop(name="Crate")["id"]
    put_mesh(crate, 0)
    store.save_source_image(crate, png_bytes((90, 90, 90)), 0,
                            backend="fake-image", prompt="a crate")
    put_mesh(crate, store.target_variant(crate))         # variant 1: no image
    third = store.add_variant(crate)                     # variant 2: no mesh
    check("the third variant was appended as an empty slot", third == 2, str(third))
    store.save_source_image(crate, png_bytes((80, 60, 40)), third,
                            backend="fake-image", prompt="a crate, again")
    rec = store.get_prop(crate) or {}
    counts = (rec.get("variants_total"), rec.get("variants_missing_mesh"),
              rec.get("variants_missing_image"))
    check("three active variants, one meshless, one imageless -> 3 / 1 / 1",
          counts == (3, 1, 1), str(counts))
    check("...and the meshed ones are exactly total minus the meshless one",
          rec.get("variant_count") == 2
          and rec.get("variants_total") - rec.get("variants_missing_mesh") == 2,
          str(rec.get("variant_count")))
    # A switched-off variant is not rendered anywhere, so it cannot be missing
    # anything either: switching off the meshless variant 2 leaves two active
    # variants, no missing mesh, and variant 1's missing image.
    store.set_variant_active(crate, 2, False)
    rec = store.get_prop(crate) or {}
    counts = (rec.get("variants_total"), rec.get("variants_missing_mesh"),
              rec.get("variants_missing_image"))
    check("switching the meshless variant off -> 2 / 0 / 1",
          counts == (2, 0, 1), str(counts))
    # The counts are ADMIN detail: the lean record is the client's prop
    # library, and a badge is nothing it renders.
    lean = {p["id"]: p for p in store.list_props()}[crate]
    check("the lean record carries none of the three counts",
          not any(k in lean for k in ("variants_total", "variants_missing_mesh",
                                      "variants_missing_image")),
          str(sorted(lean.keys())))

    print("\n[16] the ORIGIN of a picture — product shot vs. scene context")
    # The run stamp is the SCENE run's own start (scene_asset writes
    # `record["started_at"]` here, never a fresh clock read) — a fixed string,
    # so the check has nothing to do with when this smoke runs.
    RUN_TS = "2026-08-20T09:15:00+00:00"
    torch = store.create_prop(name="Torch")["id"]
    store._generate(torch, "a torch", "", "fake", "fake-mesh", variant=0)
    img0 = store.list_variants(torch)[0]["image"]
    check("an ordinary product shot records NO origin",
          img0["origin"] == "" and img0["origin_location"] == "",
          str(img0))
    check("...and writes no origin key onto the sidecar either — absence IS "
          "the product shot",
          not any(k.startswith("source_origin")
                  for k in store.read_sidecar(torch)),
          str(sorted(k for k in store.read_sidecar(torch)
                     if k.startswith("source"))))

    target = store.target_variant(torch)
    check("the scene run targets a fresh variant 1", target == 1, str(target))
    store.save_source_image(torch, png_bytes((240, 180, 40), alpha=True), target,
                            backend="fake-image", prompt="a torch in the mill",
                            origin=store.ORIGIN_SCENE_CONTEXT,
                            origin_location="Old Mill",
                            origin_location_id="old-mill", origin_ts=RUN_TS)
    img1 = store.list_variants(torch)[1]["image"]
    check("a scene cutout is stamped scene_context with its spot and its run",
          (img1["origin"], img1["origin_location"], img1["origin_location_id"],
           img1["origin_ts"])
          == ("scene_context", "Old Mill", "old-mill", RUN_TS), str(img1))
    check("...and variant 0 is untouched by it",
          store.list_variants(torch)[0]["image"]["origin"] == "")

    # The list sanitizer rebuilds EVERY entry from its whitelist on every
    # write, so a third variant's arrival is what would silently drop an
    # unknown key from the second one.
    store.add_variant(torch)
    img1 = store.list_variants(torch)[1]["image"]
    check("the origin survives a rewrite of the variant list",
          (img1["origin"], img1["origin_location"]) == ("scene_context",
                                                        "Old Mill"),
          str(img1))

    store._generate(torch, "a plain torch", "", "fake", "fake-mesh",
                    image_only=True, variant=1)
    img1 = store.list_variants(torch)[1]["image"]
    check("re-rendering it as a product shot CLEARS the origin, spot included",
          (img1["origin"], img1["origin_location"], img1["origin_ts"])
          == ("", "", ""), str(img1))
    check("...and the picture's own provenance moved on with it",
          img1["prompt"] == "a plain torch", str(img1["prompt"]))

    # The base stem keeps its provenance on the MASTER record, and the scene
    # pipeline may well target variant 0 (a prop whose first slot is empty).
    store.save_source_image(torch, png_bytes((240, 180, 40), alpha=True), 0,
                            backend="fake-image", prompt="a torch in the yard",
                            origin=store.ORIGIN_SCENE_CONTEXT,
                            origin_location="Old Mill",
                            origin_location_id="old-mill", origin_ts=RUN_TS)
    meta = store.read_sidecar(torch)
    check("variant 0's origin lands on the master record",
          (meta.get("source_origin"), meta.get("source_origin_location"),
           meta.get("source_origin_location_id"), meta.get("source_origin_ts"))
          == ("scene_context", "Old Mill", "old-mill", RUN_TS),
          str({k: v for k, v in meta.items() if k.startswith("source_origin")}))
    check("...and reads back through the strip like any other variant's",
          store.list_variants(torch)[0]["image"]["origin"] == "scene_context")
    store._generate(torch, "a torch again", "", "fake", "fake-mesh",
                    image_only=True, variant=0)
    check("a product shot over it REMOVES the master keys, not empties them",
          not any(k.startswith("source_origin")
                  for k in store.read_sidecar(torch)),
          str(sorted(k for k in store.read_sidecar(torch)
                     if k.startswith("source"))))
    check("the lean library record still carries no origin at all",
          not any(k.startswith("source_origin") or k == "origin"
                  for k in {p["id"]: p for p in store.list_props()}[torch]))

    print("\n[17] the in-flight guard is per (prop, VARIANT), not per prop")
    # The chain itself is two GPU steps and has no business here — what is
    # under test is the BOOKKEEPING around it. So `_generate` is replaced by a
    # stub that blocks until this smoke lets it go: that is what makes several
    # runs overlap in one process, which is the whole situation the guard is
    # about.
    release = threading.Event()
    started = threading.Semaphore(0)
    ran: list = []
    real_generate = store._generate

    def blocking_generate(prop_id, prompt, negative, image_glob, mesh_glob,
                          **kw):
        ran.append(kw.get("variant"))
        started.release()
        release.wait(10)
        return {"ok": True}

    store._generate = blocking_generate
    try:
        shelf = store.create_prop(name="Shelf")["id"]
        put_mesh(shelf, 0)
        put_mesh(shelf, store.target_variant(shelf))     # variant 1
        put_mesh(shelf, store.target_variant(shelf))     # variant 2
        check("the prop has three variants to run on",
              len(store.list_variants(shelf)) == 3,
              str([v["stem"] for v in store.list_variants(shelf)]))

        ok_v0 = store.trigger_generation(shelf, mesh_backend_glob="fake-mesh",
                                         mesh_only=True, variant=0)
        started.acquire(timeout=5)
        ok_v2 = store.trigger_generation(shelf, mesh_backend_glob="fake-mesh",
                                         mesh_only=True, variant=2)
        started.acquire(timeout=5)
        check("variant 0 starts", ok_v0)
        check("...and variant 2 starts WHILE it runs — two objects, two jobs",
              ok_v2)
        again = store.trigger_generation(shelf, mesh_backend_glob="fake-mesh",
                                         mesh_only=True, variant=0)
        check("...but variant 0 a second time is refused (double-click guard)",
              not again)
        check("...and no third job was started for it",
              sorted(ran) == [0, 2], str(ran))

        check("the aggregate names the prop once",
              store.is_pending() == [shelf], str(store.is_pending()))
        check("the detail gets the STORE indices that run: 0 and 2",
              store.pending_variants().get(shelf) == [0, 2],
              str(store.pending_variants()))
        check("...narrowed to one prop it answers the same",
              store.pending_variants(shelf) == {shelf: [0, 2]},
              str(store.pending_variants(shelf)))
        check("variant_generating() agrees per variant",
              (store.variant_generating(shelf, 0),
               store.variant_generating(shelf, 1),
               store.variant_generating(shelf, 2)) == (True, False, True))

        # THE MAPPING CASE: switching variant 1 off makes store index and
        # display position part company — variant 2 becomes the SECOND active
        # one. The report must stay on the store indices, or the spinner walks
        # to the wrong chip.
        check("a variant that is NOT running can still be switched off",
              store.set_variant_active(shelf, 1, False))
        actives = [v["index"] for v in store.list_variants(shelf) if v["active"]]
        check("...leaving actives 0 and 2, i.e. index 2 at position 1",
              actives == [0, 2], str(actives))
        check("...and the report is STILL 0 and 2, not 0 and 1",
              store.pending_variants().get(shelf) == [0, 2],
              str(store.pending_variants()))
        store.set_variant_active(shelf, 1, True)

        # Adding is a sidecar edit at the END of the list — allowed mid-run.
        added = store.add_variant(shelf)
        check("adding a variant DURING a run is accepted", added == 3,
              str(added))
        check("...and the running jobs still point at 0 and 2",
              store.pending_variants().get(shelf) == [0, 2],
              str(store.pending_variants()))
        check("...the fresh slot may be deleted again, it runs nothing",
              store.delete_variant(shelf, added))

        # Deleting or toggling the RUNNING variant is not.
        check("deleting the running variant 0 is refused",
              not store.delete_variant(shelf, 0))
        check("...and it is still there",
              len(store.list_variants(shelf)) == 3,
              str([v["stem"] for v in store.list_variants(shelf)]))
        check("switching the running variant 0 off is refused",
              not store.set_variant_active(shelf, 0, False))
        check("...switching the running variant 2 off is refused as well",
              not store.set_variant_active(shelf, 2, False))
        check("...and both are still active",
              [v["index"] for v in store.list_variants(shelf) if v["active"]]
              == [0, 1, 2])

        # An unqualified run IS the primary variant's run — one key, one job.
        vase = store.create_prop(name="Vase")["id"]
        put_mesh(vase, 0)
        check("the primary variant of a fresh prop is 0",
              store.primary_variant(vase) == 0)
        plain = store.trigger_generation(vase, prompt="a vase", image_only=True)
        started.acquire(timeout=5)
        check("an unqualified image run starts", plain)
        check("...and reports as the PRIMARY variant's, not as a nameless one",
              store.pending_variants().get(vase) == [0],
              str(store.pending_variants()))
        check("...so naming variant 0 explicitly is refused as a double start",
              not store.trigger_generation(vase, prompt="a vase",
                                           image_only=True, variant=0))
    finally:
        release.set()
        store._generate = real_generate
    # The threads clear their key in a `finally`, so the guard empties by
    # itself — waiting for that is what proves it, not a manual discard.
    for _ in range(200):
        if not store.pending_variants():
            break
        time.sleep(0.01)
    check("every key is released when the runs finish",
          store.pending_variants() == {} and store.is_pending() == [],
          str(store.pending_variants()))

    season_section()

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
