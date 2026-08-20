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

Usage:  ./.venv/bin/python scripts/smoke_prop_variants.py
"""
import ast
import io
import os
import sys
import tempfile
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
    # storey 0, slab 0: this smoke asserts the variant bookkeeping of the spec
    # (`variants` / `model_variants` / `variant`), never its `bottom_y` — and
    # the slab feeds nothing but that.
    return _prop_models(recipe, 0.0, 0.0)[0]


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
