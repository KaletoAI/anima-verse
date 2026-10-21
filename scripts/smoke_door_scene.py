"""Door scene contract, no Blender/server, temporary storage only.

Resolution rows follow spec 3.1 in order. For along=(1,0), centre=(2,3),
width=.9, jambs are 1.55/2.45; casing anchors 1.48/2.52. Ry(0) maps +z
south, outward=(0,-1), so outside=-1; Ry(180) flips +z north, outside=+1.
Double width 1.8 has jambs 1.1/2.9: A anchor=1.03; B=2.9-.005=2.895,
y=.025 above base. A size is 1.8+.14=1.94 by 2.1+.07=2.17; B leaf width
(1.8-.015)/2=.8925, height=2.1-.025-.005=2.07. Hull thickness is the
recipe contour .07, room .07. Metadata below is a boundary fixture; real
geometry is independently checked by smoke_door_geometry.py.
"""
from copy import deepcopy
import math
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch, MagicMock
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths


def main():
    with tempfile.TemporaryDirectory() as tmp:
        paths.init(tmp)
        from app.core import scene_recipe as sr, door_models as dm, hull_styles as hs
        from app.core.door_styles import load_door_styles
        from app.core import world_ops as wo
        styles = load_door_styles()
        assert hasattr(sr, "door_choice"), "missing unified door resolution"
        choose = sr.door_choice
        opts = dict(default_prop_id="default-prop", default_door_style="panel",
                    hull_door_styles={"door_style":"castle", "interior_door_style":"plank",
                                      "shop_door_style":"glazed"}, exterior=True, shop=False)
        rows = [({"prop_id":"own", "door_style":"glass", "door_prop":"none"}, {}, {"prop":"own"}),
                ({"door_style":"glass", "door_prop":"none"}, {}, {"style":"glass"}),
                ({"door_prop":"none"}, {}, {}),
                ({}, {}, {"prop":"default-prop"}),
                ({}, {"default_prop_id":""}, {"style":"panel"}),
                ({}, {"default_prop_id":"", "default_door_style":""}, {"style":"castle"}),
                ({}, {"default_prop_id":"", "default_door_style":"", "exterior":False}, {"style":"plank"}),
                ({}, {"default_prop_id":"", "default_door_style":"", "shop":True}, {"style":"glazed"}),
                ({}, {"default_prop_id":"", "default_door_style":"", "hull_door_styles":{}}, {"style":"panel"}),
                ({}, {"default_prop_id":"", "default_door_style":"", "hull_door_styles":{}, "exterior":False}, {"style":"interior"}),
                ({"type":"window"}, {}, {}), ({"type":"passage"}, {}, {})]
        for op, overrides, expected in rows:
            assert choose(op, **{**opts, **overrides}) == expected, (op, overrides)
        assert sr.door_prop_id({"door_prop":"none"}, "p") == ""
        expected = {"fachwerk":("plank","interior","glazed"), "steinhaus":("panel","interior","glazed"),
                    "holzhuette":("plank","plank","glazed"), "burg":("castle","plank","glazed"),
                    "modern":("glass","interior","glass")}
        for key, values in expected.items():
            import json
            raw = json.loads((hs.SHARED_DIR / (key+".json")).read_text())
            got = hs.validate_style(raw, key)
            assert tuple(got[k] for k in ("door_style","interior_door_style","shop_door_style")) == values
        assert hs.validate_style({"door_style":"bad"}, "test")["door_style"] == "panel"
        assert hs.validate_description({"overrides":{"door_color":"#123456"}}, {})["overrides"]["door_color"] == "#123456"
        op = dict(edge="N",at=.5,type="door",width_m=.9,height_m=2.1,door_style="glass")
        assert wo._sanitize_opening(op)["door_style"] == "glass"
        assert "door_style" not in wo._sanitize_opening({**op,"door_style":"../bad"})
        assert wo.safe_door_style_id("glass") == "glass" and wo.safe_door_style_id("bad") == ""

        door = dict(level=0, at_world=[2,3], along=[1,0], width_m=.9, height_m=2.1,
                    base_y=0, rooms=["a"], _door_prop=sr._door_prop_of({"door_style":"glazed"}))
        leaf = {"min":[.075,.025,-.0225], "max":[.965,2.095,.0225]}
        calls = []
        def built(style, w, h, t, *, piece="single", outside=1, color=None):
            calls.append((style,w,h,t,piece,outside,color))
            from app.core.door_geometry import build_door
            geometry = build_door(style,w,h,t,piece=piece,outside=outside)
            return dict(sig=piece, size_m=geometry["size_m"], leaf_bbox=geometry["leaf_bbox"])
        with patch.object(dm,"ensure_door_model",side_effect=built):
            specs,_ = sr._door_prop_models([door], door_styles=styles)
            a = specs[0]
            assert (a["role"], a["id"], a["measure"], a["fix_euler"]) == ("prop","door:single","fit",None)
            assert all(abs(x-y)<1e-9 for x,y in zip(a["size_m"],[1.04,2.17])) and a["anchor"] == [1.48,3]
            assert all(abs(a["door"]["leaf_bbox"][key][i]-leaf[key][i])<1e-9 for key in ("min","max") for i in range(3)) and a["slots"] == {"glass":{"preset":"glass"}}
            assert a["variants"] == sr._variants("/assets/doors/single/model", ["full"])
            assert calls[-1][3:6] == (.07,"single",-1)
            right = deepcopy(door); right["_door_prop"]["hinge"] = "right"
            b = sr._door_prop_models([right],door_styles=styles)[0][0]
            assert b["anchor"] == [2.52,3] and b["yaw_deg"] == 180 and b["door"]["swing"] == -1
            assert calls[-1][5] == 1
            assert math.cos(math.radians(b["yaw_deg"]))*calls[-1][5] == -1  # world z = outward
            double = deepcopy(door); double["width_m"] = 1.8
            pair = sr._door_prop_models([double],door_styles=styles)[0]
            assert len(pair)==2 and [p["door"]["opening"] for p in pair]==[0,0]
            assert pair[0]["anchor"] == [1.03,3] and pair[1]["anchor"] == [2.895,3]
            assert pair[1]["bottom_y"] == .025 and pair[1]["door"]["hinge"] == "right"
            assert [c[4] for c in calls[-2:]] == ["double_a","double_b"]
            # In world x, A ends at 1.03+.9675=1.9975, B starts at
            # 2.895-.8925=2.0025: .005 central clearance, two jamb pivots.
            a_end = pair[0]["anchor"][0]+pair[0]["door"]["leaf_bbox"]["max"][0]
            b_start = pair[1]["anchor"][0]-pair[1]["door"]["leaf_bbox"]["max"][0]
            assert abs(a_end-1.9975)<1e-9 and abs(b_start-2.0025)<1e-9
            double["_door_prop"]["hinge"] = "right"
            pair = sr._door_prop_models([double],door_styles=styles)[0]
            assert pair[0]["anchor"] == [2.97,3] and pair[1]["anchor"] == [1.105,3]
            assert [p["door"]["hinge"] for p in pair] == ["right","left"]
            assert [c[5] for c in calls[-2:]] == [1,-1]

        location = {"id":"loc", "map3d":{"outline":[[-5,-5],[5,-5],[5,5],[-5,5]], "storey_height_m":3},
                    "rooms":[{"id":"a","layout":{"x":-5,"y":-5,"w":4,"d":4,"level":0,
                              "openings":[op]}}]}
        with patch.object(dm,"ensure_door_model",return_value=None) as missing:
            scene = sr.compose_scene(location,plan_width_m=10)
            assert missing.called, "missing model must enqueue through ensure"
            assert not [m for m in scene["models"] if m["id"].startswith("door:")]
            assert all(not w.get("door_prop") for w in scene["walls"] if w.get("leaf"))
        with patch.object(dm,"ensure_door_model",side_effect=built):
            scene = sr.compose_scene(location,plan_width_m=10)
            assert [m for m in scene["models"] if m["id"].startswith("door:")]
            assert all(w.get("door_prop") for w in scene["walls"] if w.get("leaf"))
            # Geometry, not the target/outside flag: on-contour N is exterior,
            # room S is internal even if its connectivity says outside.
            location["rooms"][0]["layout"]["openings"] = [{**op,"door_style":""}, {**op,"edge":"S","door_style":""}]
            calls.clear()
            sr.compose_scene(location,plan_width_m=10,building_meta={"plan_hull":True,"hull_style":hs.validate_style({"door_style":"castle","interior_door_style":"plank","shop_door_style":"glazed"}, "test"),"hull_shopfront":True,"hull_door_color":"#123456"})
            ids = [c[0]["id"] if isinstance(c[0],dict) else c[0] for c in calls]
            assert sorted(ids)==["glazed","plank"], ids
            assert all(c[-1]=="#123456" for c in calls)
        # Location create/update use the same style-id sanitizer; only
        # persistence is stubbed, so no world database or route is opened.
        from app.models import world
        from app.core import places
        record = {"id":"loc", "name":"Location", "rooms":[]}
        with patch.object(wo,"add_location",return_value=record),              patch.object(wo,"get_location_by_id",return_value=record),              patch.object(world,"_load_world_data",return_value={"locations":[record]}),              patch.object(world,"upsert_location"), patch.object(places,"invalidate"):
            wo.create_location_with_extras({"name":"Location","default_door_style":"glass"})
            assert record["default_door_style"] == "glass"
            wo.update_location_with_extras("loc",{"default_door_style":"plank"})
            assert record["default_door_style"] == "plank"
            wo.update_location_with_extras("loc",{"default_door_style":"../missing"})
            assert record["default_door_style"] == ""
        # Catalog is read once per composition, including a double door.
        import app.core.door_styles as ds
        with patch.object(ds,"load_door_styles",wraps=load_door_styles) as load,              patch.object(dm,"load_door_styles",side_effect=AssertionError("per-door style load")),              patch.object(dm,"ensure_door_model",side_effect=built):
            sr.compose_scene(location,plan_width_m=10)
            assert load.call_count == 1
        # Cache boundary accepts the already-loaded catalog entry, without
        # another disk read, and returns its real sig/URL contract.
        import json
        sig = dm.door_signature(styles["panel"],.9,2.1,.07,"single",-1,None)
        directory = Path(tmp)/"door_models"/sig
        directory.mkdir(parents=True)
        (directory/"model.glb").write_bytes(b"cache boundary fixture")
        (directory/"meta.json").write_text(json.dumps(dict(sig=sig,size_m=[1.04,2.17],leaf_bbox=leaf)))
        with patch.object(dm,"load_door_styles",side_effect=AssertionError("per-door style load")):
            cached = dm.ensure_door_model(styles["panel"],.9,2.1,.07,outside=-1)
            assert cached["sig"] == sig and cached["url"] == "/assets/doors/"+sig+"/model"

        # Hull doors use the contour thickness (.07), their ring's outward
        # normal, and storey-0 shop style. Reverse winding flips outside.
        from app.models.world import floor_room_id
        hull = {"id":"hull", "map3d":{**location["map3d"],"hull_openings":[
            dict(edge=0,at=.5,type="door",width_m=.9,height_m=2.1)]},
            "rooms":[{"id":floor_room_id(0)}]}
        hull_meta = {"plan_hull":True,"hull_style":{"door_style":"castle",
            "interior_door_style":"plank","shop_door_style":"glazed"},
            "hull_shopfront":True,"hull_door_color":"#123456"}
        with patch.object(dm,"ensure_door_model",side_effect=built):
            calls.clear()
            sc = sr.compose_scene(hull,plan_width_m=10,building_meta=hull_meta)
            assert calls[0][0]["id"] == "glazed" and calls[0][3:6] == (.07,"single",-1)
            assert all(w.get("door_prop") for w in sc["walls"] if w.get("leaf"))
            hull["map3d"]["outline"] = list(reversed(hull["map3d"]["outline"]))
            calls.clear()
            sr.compose_scene(hull,plan_width_m=10,building_meta=hull_meta)
            assert calls[0][5] == 1
            hull["map3d"]["outline"] = list(reversed(hull["map3d"]["outline"]))
            calls.clear()
            sr.compose_scene(hull,plan_width_m=10,building_meta={**hull_meta,"plan_hull":False})
            assert calls[0][0]["id"] == "panel" and calls[0][-1] is None
            upper = deepcopy(hull)
            upper["rooms"] = [{"id":floor_room_id(1)}]
            upper["map3d"]["hull_openings"][0]["level"] = 1
            calls.clear()
            sr.compose_scene(upper,plan_width_m=10,building_meta=hull_meta)
            assert calls[0][0]["id"] == "castle"  # shop never upstairs
        # Missing second double piece keeps the whole flat leaf visible.
        wide = deepcopy(hull); wide["map3d"]["hull_openings"][0]["width_m"] = 1.8
        def half_built(*args, **kwargs):
            return None if kwargs["piece"] == "double_b" else built(*args, **kwargs)
        with patch.object(dm,"ensure_door_model",side_effect=half_built):
            sc = sr.compose_scene(wide,plan_width_m=10)
            assert not [m for m in sc["models"] if m["id"].startswith("door:")]
            assert all(not w.get("door_prop") for w in sc["walls"] if w.get("leaf"))
        # Active model description is the source of the exported hull fields.
        from app.core import location_model3d as lm
        gallery = MagicMock()
        gallery.find.return_value = Path(tmp)/"active.glb"
        gallery.tiers.return_value = []
        gallery.signature.return_value = "active"
        active = {"plan_hull":True,"hull":{"description":{"style":"modern",
            "overrides":{"shopfront":True,"door_color":"#abcdef"}},"walls":{"0":"brick"}}}
        with patch.object(lm,"_owner_id",return_value="loc"), patch.object(lm,"_gallery",return_value=gallery),              patch.object(lm,"read_sidecar",return_value=active), patch.object(lm,"_demand_low"),              patch.object(hs,"get_style",return_value=hull_meta["hull_style"]) as get:
            meta = lm.get_client_meta("loc")
            get.assert_called_once_with("modern")
            assert meta["hull_shopfront"] is True and meta["hull_door_color"] == "#abcdef"
            assert meta["hull_walls"] == {"0":"brick"} and meta["hull_style"] == hull_meta["hull_style"]
            gallery.find.return_value = None
            assert lm.get_client_meta("loc") is None
        # The same opening sanitizer serves hull openings.
        clean = wo._sanitize_map3d({**hull["map3d"],"hull_openings":[{
            **hull["map3d"]["hull_openings"][0],"door_style":"glass"}]})
        assert clean["hull_openings"][0]["door_style"] == "glass"
        # Two faces .10 m apart are one shared wall (mirror tolerance .15),
        # even though facade colinearity uses .09. Both flat leaves must hide.
        shared = {"id":"shared", "map3d":location["map3d"], "rooms":[
            {"id":"a", "layout":{"x":-4,"y":-4,"w":4,"d":4,"level":0,
                "openings":[{**op,"edge":"S","to":"b"}]}},
            {"id":"b", "layout":{"x":-4,"y":.1,"w":4,"d":4,"level":0}}]}
        with patch.object(dm,"ensure_door_model",side_effect=built):
            sc = sr.compose_scene(shared,plan_width_m=10)
            assert len(sc["doorways"]) == 1
            leaves = [w for w in sc["walls"] if w.get("leaf") and w.get("room_id") in ("a","b")]
            assert len(leaves) == 2 and all(w.get("door_prop") for w in leaves), leaves
        # Isolate unrelated fingerprint inputs: no world DB is opened.
        with patch.object(sr,"prop_lib_token",return_value=""), patch.object(sr,"_dir_stat_sig",return_value=""), \
             patch("app.models.terrain.terrain_sig",return_value=""), patch("app.core.heightfield.current_sig",return_value=""), \
             patch("app.core.surface_textures.library_kinds",return_value=[]), patch("app.core.pose_catalog.get_groups",return_value={}):
            with patch.object(dm,"generation",return_value=1): one=sr.scene_fingerprint(location,"")
            with patch.object(dm,"generation",return_value=2): two=sr.scene_fingerprint(location,"")
            assert one != two
        assert sr.SCENE_RECIPE_VERSION == 16
        print("PASS door scene: resolution, styles, sanitizers, placement, fallback, exterior, fingerprint, v16")

if __name__ == "__main__":
    main()
