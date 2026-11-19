"""A237 — a fitted template piece worn over another layer, and template trousers with a boot.

No server, no world DB, no Blender: ``garment_template`` / ``garment_assembly`` / ``outfit_options`` with the item,
profile and fit readers replaced by stubs (``paths.init`` on a temp dir first). Usage:
./.venv/bin/python scripts/smoke_garment_tucked_layers.py

Hand-derived expectations (stub items: ``tr`` straight trousers, ``sk`` skinny full trousers, ``boot`` a footwear
piece whose fit record is a split boot with an ``ankle`` shaft, ``shoe`` a footwear piece with no shaft):

[K1] the drape key of a FITTED kind over a collider layer gains the token ``cut:body`` (it is cut from the body
     alone now): trousers over the own-mesh piece ``o1`` with no fit -> under = ["o1:fit:-", "cut:body"], so its
     key equals ``tsig(params, lower=["o1", "o1:fit:-", "cut:body"])``; a skirt (wrapped, not cut) over the same
     -> ["o1:fit:-"] only; trousers with no collider -> ``tsig(params, lower=["o1"])`` — unchanged.
[B1] ``boot_hem_mode`` / ``boot_collider``: straight trousers + a boot, hem ``over`` -> ("over", "boot", fit path)
     and the boot is a collider; hem ``tucked`` -> ("tucked", ...) and no collider; no hem stored -> ``over``
     (``outfit_options.HEM_DEFAULT``); skinny full trousers (into the shoe anyway) -> None; a shoe without a shaft
     -> None; a top (not trousers) -> None.
[A1] ``garment_assembly._stamp_boot_tucked``: boot + template straight trousers + hem ``tucked`` -> the trousers
     are stamped and ``_under_shoe`` is True; hem ``over`` -> not stamped, ``_under_shoe`` False; skinny full ->
     not stamped but ``_under_shoe`` True (``under_footwear``, A233); a shoe without a shaft -> not stamped.
[W1] ``outfit_options._template_trousers_record``: straight template trousers -> a stand-in record, so
     ``hem_eligible(boot record, it)`` is (True, ""); skinny full -> None; a template top -> None.
[S1] the builder: a fitted piece over lower layers takes its faces from a body-only rest collider (``cut``) and
     lays out over ``ctree`` (body + layers); a boot fit's several footwear nodes are joined into one collider.
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.core import paths  # noqa: E402

paths.init(tempfile.mkdtemp(prefix="a237-"))

from app.core import garment_assembly as ga  # noqa: E402
from app.core import garment_set, garment_store, outfit_options  # noqa: E402
from app.core import garment_template as gt  # noqa: E402
from app.models import character as mchar  # noqa: E402
from app.models import inventory  # noqa: E402

FAILED = []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f"   [{detail}]" if not ok and detail else ""))
    if not ok:
        FAILED.append(name)


def tmpl(params):
    return {"category": "outfit_piece", "outfit_piece": {"slots": ["bottom"], "mesh_mode": "template",
                                                        "template": {"params": params}}}


ITEMS = {
    "tr": tmpl(gt.validate_params({"kind": "trousers"})[0]),
    "sk": tmpl(gt.validate_params({"kind": "trousers", "leg_shape": "skinny", "trouser_length": "full"})[0]),
    "top": tmpl(gt.validate_params({"kind": "top"})[0]),
    "boot": {"slots": ["feet"], "mesh_mode": "own_mesh"},
    "shoe": {"slots": ["feet"], "mesh_mode": "own_mesh"},
}
BOOT_REC = {"split": {"is_boot": True}, "shaft": {"class": "ankle"}}
SHOE_REC = {"split": {"is_boot": False}, "shaft": {"class": "none"}}
PROFILE = {}

inventory.get_item = lambda i: ITEMS.get(i)
mchar.get_character_profile = lambda name: PROFILE
garment_store.accepted_fit = lambda c, i, base_model_sha, **k: (
    (Path(f"/x/{i}.glb"), BOOT_REC if i == "boot" else SHOE_REC) if i in ("boot", "shoe") else None)
_kind = garment_set.garment_kind_of
garment_set.garment_kind_of = lambda it: garment_set.FOOTWEAR if it in (ITEMS["boot"], ITEMS["shoe"]) else _kind(it)

# [K1]
gt.texture_sources = lambda c, i: {"front": "f", "back": "b"}
gt._file_sha = lambda p: "s"
gt.collider_pieces = lambda i, k, lower: []
from app.core import bust_shaping  # noqa: E402
bust_shaping.key_tokens = lambda *a, **k: []
real_own = gt.own_colliders
gt.own_colliders = lambda c, i, k, lower, base_sha: [("o1", None)]
ptr = gt.params_of(ITEMS["tr"])
tex = gt._md5(["s", "s"])
key, _r, _s = gt.key_for("c", "tr", base_sha="b" * 64, lower=["o1"], item=ITEMS["tr"])
check("K1 trousers over a layer: key has cut:body",
      key == gt.tsig(ptr, base_sha="b" * 64, texture_sha=tex, lower=["o1", "o1:fit:-", "cut:body"]))
ITEMS["sk2"] = tmpl(gt.validate_params({"kind": "skirt"})[0])
key, _r, _s = gt.key_for("c", "sk2", base_sha="b" * 64, lower=["o1"], item=ITEMS["sk2"])
check("K1 skirt over a layer: no cut:body",
      key == gt.tsig(gt.params_of(ITEMS["sk2"]), base_sha="b" * 64, texture_sha=tex, lower=["o1", "o1:fit:-"]))
gt.own_colliders = lambda c, i, k, lower, base_sha: []
key, _r, _s = gt.key_for("c", "tr", base_sha="b" * 64, lower=["o1"], item=ITEMS["tr"])
check("K1 trousers with no collider: key unchanged",
      key == gt.tsig(ptr, base_sha="b" * 64, texture_sha=tex, lower=["o1"]))
gt.own_colliders = real_own

# [B1]
PROFILE.clear()
PROFILE["equipped_options"] = {"boot_hem": "over"}
check("B1 over -> mode", gt.boot_hem_mode("c", "tr", "trousers", ["boot"], base_sha="b")
      == ("over", "boot", Path("/x/boot.glb")))
check("B1 over -> boot collider", gt.boot_collider("c", "tr", "trousers", ["boot"], base_sha="b")
      == ("boot", Path("/x/boot.glb")))
PROFILE["equipped_options"] = {"boot_hem": "tucked"}
check("B1 tucked -> mode", (gt.boot_hem_mode("c", "tr", "trousers", ["boot"], base_sha="b") or ("",))[0] == "tucked")
check("B1 tucked -> no collider", gt.boot_collider("c", "tr", "trousers", ["boot"], base_sha="b") is None)
PROFILE.clear()
check("B1 default -> over", (gt.boot_hem_mode("c", "tr", "trousers", ["boot"], base_sha="b") or ("",))[0] == "over")
check("B1 skinny full -> None", gt.boot_hem_mode("c", "sk", "trousers", ["boot"], base_sha="b") is None)
check("B1 shoe without shaft -> None", gt.boot_hem_mode("c", "tr", "trousers", ["shoe"], base_sha="b") is None)
check("B1 top -> None", gt.boot_hem_mode("c", "top", "top", ["boot"], base_sha="b") is None)


# [A1]
def worn(trousers, foot="boot"):
    return [{"item_id": foot, "kind": garment_set.FOOTWEAR, "fit": "/x", "record": BOOT_REC if foot == "boot" else SHOE_REC,
             "item": ITEMS[foot]},
            {"item_id": trousers, "kind": garment_set.CLOTHING, "fit": "/y", "record": {}, "template": True,
             "item": ITEMS[trousers]}]


g = worn("tr")
ga._stamp_boot_tucked(g, {"equipped_options": {"boot_hem": "tucked"}})
check("A1 tucked -> stamped", g[1].get("boot_tucked") is True and ga._under_shoe(g[1]))
g = worn("tr")
ga._stamp_boot_tucked(g, {"equipped_options": {"boot_hem": "over"}})
check("A1 over -> not stamped", not g[1].get("boot_tucked") and not ga._under_shoe(g[1]))
g = worn("sk")
ga._stamp_boot_tucked(g, {"equipped_options": {"boot_hem": "tucked"}})
check("A1 skinny full -> not stamped, under the shoe anyway", not g[1].get("boot_tucked") and ga._under_shoe(g[1]))
g = worn("tr", foot="shoe")
ga._stamp_boot_tucked(g, {"equipped_options": {"boot_hem": "tucked"}})
check("A1 shoe without shaft -> not stamped", not g[1].get("boot_tucked"))

# [W1]
rec = outfit_options._template_trousers_record("tr")
check("W1 straight trousers -> stand-in, eligible", rec is not None and outfit_options.hem_eligible(BOOT_REC, rec)
      == (True, ""))
check("W1 skinny full -> None", outfit_options._template_trousers_record("sk") is None)
check("W1 top -> None", outfit_options._template_trousers_record("top") is None)

# [S1]
fitted = (ROOT / "app/blender/scripts/garment_template_fitted.py").read_text()
build = (ROOT / "app/blender/scripts/garment_template_build.py").read_text()
check("S1 the fitted cut reads the cut collider", "src = cut if cut is not None else col" in fitted
      and "bm.from_mesh(src.data)" in fitted)
check("S1 the builder makes a body-only cut collider over layers",
      "cut = gd.rest_collider(body)[0] if lower else None" in build and "col=col, cut=cut)" in build)
check("S1 a boot's nodes are joined", 'startswith("garment_footwear_")' in build and "bpy.ops.object.join()" in build)

print("FAILED: " + ", ".join(FAILED) if FAILED else "all checks passed")
sys.exit(1 if FAILED else 0)
