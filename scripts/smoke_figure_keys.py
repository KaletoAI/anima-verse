#!/usr/bin/env python3
"""The figure resolver ``app/core/figure.py`` (plan
``docs/superpowers/plans/2026-11-12-unified-worn-pieces.md`` Task 4; spec
``docs/superpowers/specs/2026-11-12-unified-worn-pieces-design.md``,
builder-check ruling 1): the worn sets per mode, the SHAPE key (the in-body
set including in-body hair) and the TEXTURE key (the painted set). The
mesh-input token ``model_refs.mesh_items_token`` stays mode-blind (Ruling
4a): only own-mesh pieces change it, as at BASE.

Usage:
    ./.venv/bin/python scripts/smoke_figure_keys.py

Runs against a THROWAWAY storage + instance directory — no real world, no
hub, no GPU, no server. Nothing is written to a world DB.

Stubs: ``inventory.get_item`` and ``motion_item_cache.item_snapshot`` serve
the four items below; ``base_body.is_base_pipeline`` -> True (the character
is on the pipeline); ``base_body.dress_text`` -> ``"wear:" + "+".join(sorted
visible ids)`` where the visible ids are the worn piece ids minus
``mesh_items`` (``""`` when none is left); ``base_body.side_views_dressed``
-> False; ``base_body.dressed_views`` -> ("front", "back"). The REAL
``texture_inputs`` / ``texture_signature`` run on those stubs (they call
the module globals). The hair method comes from the profile key
``hair_method`` ("body" = the hair is in the body, "hairdeck" = not).

Fixture: character "Demo", bsig = "base0123abcd" (a base signature,
``base_body.BASE_SIG_RE``), variant "rigged". Items (category outfit_piece):
coat [outer] mode in_body, blouse [top] mode painted, boots [feet] mode
own_mesh (kind footwear: feet alone), trousers [bottom] mode own_mesh (kind
clothing). Worn PIECES = {outer: coat, top: blouse, feet: boots, bottom:
trousers}.

Canonical JSON below = json.dumps(.., sort_keys=True, separators=(",", ":"),
ensure_ascii=False); h8/h12 = the first 8/12 hex of its sha256.

Expected, derived by hand from the brief:

[1] worn_sets(PIECES): in_body ("coat",), painted ("blouse",), own {boots:
    footwear, trousers: clothing}, hair_in_body True (method body),
    hair_item "" (no hair item worn).
[2] Shape key. Coat switched to painted (nothing in the body) -> shape_key ==
    bsig == "base0123abcd" and is_plain True. With the coat in the body:
    "ob" + h8({"base_signature": "base0123abcd", "base_variant": "rigged",
    "dress_text": {"back": "wear:coat", "front": "wear:coat"}, "hair_in_body":
    True, "side_views": False, "version": 2}) = "ob82e8f156" (the dress text
    leaves out painted + own = blouse, boots, trousers); is_plain False;
    it matches base_body.OUTFIT_BODY_RE.
[3] Blouse in_body as well -> dress_text "wear:blouse+coat" -> "oba82e1f92"
    (!= "ob82e8f156"). Blouse own_mesh instead of painted -> still
    "ob82e8f156" (painted and own never enter the shape).
[4] Texture key. Plain body (coat painted): == base_body.texture_signature(
    base_body.texture_inputs("Demo", pieces=PIECES, items=[], variant="rigged",
    mesh_effective=["boots", "trousers"], bsig=bsig)) — today's tsig — and,
    by hand, "tex" + h12({"version": 1, "base_signature": "base0123abcd",
    "base_variant": "rigged", "side_views": False, "dress_text": {"back":
    "wear:blouse+coat", "front": "wear:blouse+coat"}}) = "tex06c6eeeaa12a".
    On the coat's shape "ob82e8f156": "tex" + h12({"version": 1, "shape":
    "ob82e8f156", "base_variant": "rigged", "dress_text": {"back":
    "wear:blouse", "front": "wear:blouse"}}) = "texe57feda37703" (covers the
    blouse only); with the blouse own_mesh nothing is painted there -> "".
[5] Hair: the same in-body set (coat) with hair_method "hairdeck" ->
    hair_in_body False -> "ob" + h8(<[2]'s dict with "hair_in_body": False>)
    = "ob386b6362" != "ob82e8f156". Wearing its own hair item "hair_demo"
    (garment kind hair, owner Demo) in equipped_mesh_pieces: hair_item
    "hair_demo" under hairdeck (own unchanged: hair is no outfit piece), ""
    under body (the hair is in the body).
[6] mesh_items_token stays mode-blind (Ruling 4a: the dressed views are the
    same images whether a piece is painted or in the body, so the mesh-input
    signature must not change with that mode). The current function equals
    the BASE function (``git show aeadce9c:app/core/model_refs.py`` loaded as
    a temp module, same stubs) for every case below, and by hand:
    PIECES with the coat painted AND with the coat in the body ->
    "|meshitems:boots,trousers|worn:bottom=trousers;feet=boots;outer=coat;
    top=blouse" both times (no "|inbody:"); {outer: coat, top: blouse} worn
    with the coat in the body (no own piece) -> ""; with the blouse own_mesh
    as well -> "|meshitems:blouse|worn:outer=coat;top=blouse".
    Fails-on-old-code proof: app/core/figure.py is absent at aeadce9c ([0]).
"""
import copy
import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

BASE = "aeadce9c"
FAILS = []
BSIG = "base0123abcd"


def check(label, got, want):
    ok = got == want
    print(("  OK   " if ok else "  FAIL ") + f"{label}: {got!r}" + ("" if ok else f" — expected {want!r}"))
    if not ok:
        FAILS.append(label)


def _item(item_id, slots, mode):
    return {"id": item_id, "name": item_id.title(), "category": "outfit_piece",
            "outfit_piece": {"slots": list(slots), "mesh_mode": mode}}


ITEMS = {"coat": _item("coat", ["outer"], "in_body"),
         "blouse": _item("blouse", ["top"], "painted"),
         "boots": _item("boots", ["feet"], "own_mesh"),
         "trousers": _item("trousers", ["bottom"], "own_mesh")}
ITEMS["hair_demo"] = {"id": "hair_demo", "name": "Hair", "category": "garment", "owner": "Demo",
                      "garment": {"kind": "hair"}}
PIECES = {"outer": "coat", "top": "blouse", "feet": "boots", "bottom": "trousers"}


def set_mode(item_id, mode):
    ITEMS[item_id]["outfit_piece"]["mesh_mode"] = mode


def profile(method="body", pieces=None):
    return {"model_pipeline": "base_body", "hair_method": method,
            "equipped_pieces": dict(PIECES if pieces is None else pieces), "equipped_mesh_pieces": {}}


def stub_dress_text(character_name, view, *, pieces, items, profile=None, mesh_items=()):
    meshed = {str(i) for i in mesh_items or ()}
    visible = sorted({str(i) for i in (pieces or {}).values() if i and str(i) not in meshed})
    return ("wear:" + "+".join(visible)) if visible else ""


def load_base_model_refs():
    src = subprocess.run(["git", "show", f"{BASE}:app/core/model_refs.py"], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout
    path = Path(os.environ["SMOKE_TMP"]) / "model_refs_base.py"
    path.write_text(src)
    spec = importlib.util.spec_from_file_location("model_refs_base", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="figure-keys-") as tmp:
        root = Path(tmp)
        os.environ["SMOKE_TMP"] = tmp
        os.environ["ANIMATION_CLIPS_DIR"] = str(root / "clips")
        os.environ["ANIMATION_RIG_FILE"] = str(root / "reference.fbx")
        from app.core import paths
        paths.init(root / "world")
        paths.init_instance(root / "instance")

        from app.core import base_body, garment_set, motion_item_cache, model_refs
        from app.models import inventory
        inventory.get_item = lambda item_id, **_kw: copy.deepcopy(ITEMS.get(str(item_id)))
        motion_item_cache.item_snapshot = lambda **_kw: copy.deepcopy(ITEMS)
        base_body.is_base_pipeline = lambda *_a, **_kw: True
        base_body.dress_text = stub_dress_text
        base_body.side_views_dressed = lambda: False
        base_body.dressed_views = lambda: ("front", "back")

        print("[0] the module")
        exists_at_base = subprocess.run(["git", "cat-file", "-e", f"{BASE}:app/core/figure.py"], cwd=ROOT,
                                        capture_output=True).returncode == 0
        check(f"app/core/figure.py absent at {BASE}", exists_at_base, False)
        try:
            from app.core import figure
        except ImportError as e:
            check("import app.core.figure", str(e), "importable")
            print(f"\nFAILED ({len(FAILS)}): " + ", ".join(FAILS))
            return 1
        check("SHAPE_VERSION", figure.SHAPE_VERSION, 2)

        print("[1] worn_sets")
        sets = figure.worn_sets("Demo", profile=profile())
        check("in_body", sets.in_body, ("coat",))
        check("painted", sets.painted, ("blouse",))
        check("own", sets.own, {"boots": "footwear", "trousers": "clothing"})
        check("hair_in_body", sets.hair_in_body, True)
        check("hair_item", sets.hair_item, "")
        check("pieces= overrides the profile", figure.worn_sets(
            "Demo", pieces={"top": "blouse"}, profile=profile()).painted, ("blouse",))

        def key(method="body", pieces=None):
            p = profile(method, pieces)
            s = figure.worn_sets("Demo", pieces=p["equipped_pieces"], profile=p)
            return s, figure.shape_key("Demo", s, bsig=BSIG, variant="rigged", profile=p), p

        print("[2] shape key")
        set_mode("coat", "painted")
        _, plain, _ = key()
        check("nothing in the body -> bsig", plain, BSIG)
        check("is_plain(bsig)", figure.is_plain(plain), True)
        set_mode("coat", "in_body")
        _, coat_shape, p = key()
        check("coat in the body", coat_shape, "ob82e8f156")
        check("is_plain(coat shape)", figure.is_plain(coat_shape), False)
        check("OUTFIT_BODY_RE", bool(base_body.OUTFIT_BODY_RE.fullmatch(coat_shape)), True)
        s = figure.worn_sets("Demo", profile=p)
        check("shape_inputs", figure.shape_inputs("Demo", s, bsig=BSIG, variant="rigged", profile=p),
              {"version": 2, "base_signature": BSIG, "base_variant": "rigged", "hair_in_body": True,
               "side_views": False, "dress_text": {"front": "wear:coat", "back": "wear:coat"}})

        print("[3] painted / own never enter the shape")
        set_mode("blouse", "in_body")
        check("blouse in the body", key()[1], "oba82e1f92")
        set_mode("blouse", "own_mesh")
        check("blouse own_mesh", key()[1], "ob82e8f156")
        set_mode("blouse", "painted")
        check("blouse painted", key()[1], "ob82e8f156")

        print("[4] texture key")
        set_mode("coat", "painted")
        s, shape, p = key()
        tex = figure.texture_key("Demo", s, shape=shape, bsig=BSIG, variant="rigged", items=[], profile=p)
        today = base_body.texture_signature(base_body.texture_inputs(
            "Demo", pieces=PIECES, items=[], variant="rigged", mesh_effective=["boots", "trousers"], bsig=BSIG,
            profile=p))
        check("plain body == today's tsig", tex, today)
        check("plain body by hand", tex, "tex06c6eeeaa12a")
        set_mode("coat", "in_body")
        s, shape, p = key()
        check("coat shape", shape, "ob82e8f156")
        check("on the coat's shape", figure.texture_key("Demo", s, shape=shape, bsig=BSIG, variant="rigged",
                                                         items=[], profile=p), "texe57feda37703")
        set_mode("blouse", "own_mesh")
        s, shape, p = key()
        check("blouse own_mesh: nothing painted", figure.texture_key(
            "Demo", s, shape=shape, bsig=BSIG, variant="rigged", items=[], profile=p), "")
        set_mode("blouse", "painted")

        print("[5] hair in the body is part of the shape")
        s, shape, _ = key(method="hairdeck")
        check("hairdeck: hair_in_body", s.hair_in_body, False)
        check("hairdeck shape", shape, "ob386b6362")
        check("differs from the haired shape", shape != "ob82e8f156", True)
        haired = profile("hairdeck")
        haired["equipped_mesh_pieces"] = {"hair": "hair_demo"}
        check("hairdeck: the worn hair item", figure.worn_sets("Demo", profile=haired).hair_item, "hair_demo")
        check("hairdeck: the hair item is no piece", figure.worn_sets("Demo", profile=haired).own,
              {"boots": "footwear", "trousers": "clothing"})
        haired["hair_method"] = "body"
        check("body: a leftover hair item is not served", figure.worn_sets("Demo", profile=haired).hair_item, "")

        print("[6] mesh_items_token stays mode-blind (Ruling 4a)")
        base_refs = load_base_model_refs()
        p = profile()
        full = "|meshitems:boots,trousers|worn:bottom=trousers;feet=boots;outer=coat;top=blouse"
        two = {"outer": "coat", "top": "blouse"}
        cases = [("coat painted", "coat", "painted", PIECES, full),
                 ("coat in the body", "coat", "in_body", PIECES, full),
                 ("in-body coat, no own piece", "coat", "in_body", two, ""),
                 ("in-body coat + own-mesh blouse", "blouse", "own_mesh", two,
                  "|meshitems:blouse|worn:outer=coat;top=blouse")]
        for label, item_id, mode, pieces, want in cases:
            set_mode(item_id, mode)
            now = model_refs.mesh_items_token("Demo", pieces, profile=p)
            check(f"{label}: by hand", now, want)
            check(f"{label}: == {BASE}", now, base_refs.mesh_items_token("Demo", pieces, profile=p))
        set_mode("blouse", "painted")

    if FAILS:
        print(f"\nFAILED ({len(FAILS)}): " + ", ".join(FAILS))
        return 1
    print("\nALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
