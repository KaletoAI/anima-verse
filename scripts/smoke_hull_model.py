"""Hull job/storage/export contract, without a server.

The fixture spans 10 x 8 metres, with floors at 0 and 3 m. Placement must
preserve scale 1, XZ box centre and minimum Y. Two tiers mean two distinct
files and two pinned selections. A moved window changes geometry; a prop
cannot change the facade fingerprint. The two default styles are fachwerk
and modern; Modern jobs include both blind and facade_module slots. Every material object has exactly one
primitive, with UV and colour corner attributes and measured cutout padding.
Usage: ./.venv/bin/python scripts/smoke_hull_model.py [--out DIR]
"""
import argparse
import json
from pathlib import Path
import shutil
import struct
import sys
import tempfile
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core import paths


def main() -> None:
    """Exercise the job, gallery, status and optional installed Blender."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="smoke-hull-") as temporary:
        root = Path(temporary)
        paths.init(root)
        from app.core import db, hull_model, hull_styles, location_model3d, scene_recipe
        from app.core.hull_facts import hull_facts
        from app.core.hull_geometry import build_hull
        from app.core.model_store import read_sidecar
        from app.models.world import upsert_location, get_location_by_id
        from app.blender import runner
        from _hull_fixtures import stepped_house, without_outline
        db.init_schema()
        location = stepped_house()
        location["name"] = "Hull smoke"
        loc_id = location["id"]
        assert upsert_location(location, sync_world=False)
        desc = {"style": "fachwerk", "seed": 4}
        job = hull_model.build_job(loc_id, desc, tex_dir=root / "tex1")
        other = hull_model.build_job(loc_id, desc, tex_dir=root / "tex2")
        assert set(job["tiers"]) == {"full", "low"}
        style = hull_styles.get_style("fachwerk")
        facts = hull_facts(location, loc_id)
        assert job["extras"]["interior_cutout_padding_m"] == build_hull(
            facts, style, job["description"], tier="full")["padding_m"]
        assert {k: v for k, v in job.items() if k != "textures"} == {
            k: v for k, v in other.items() if k != "textures"}
        for key, path in job["textures"].items():
            assert Path(path).is_file()
            assert Path(path).read_bytes() == Path(other["textures"][key]).read_bytes()
        for tier in job["tiers"]:
            vertices = [ [x, z, -y] for mesh in job["tiers"][tier]["meshes"]
                        for x, y, z in mesh["vertices"] ]
            low = [min(point[i] for point in vertices) for i in range(3)]
            high = [max(point[i] for point in vertices) for i in range(3)]
            placement = job["placement"][tier]
            spec = scene_recipe._building_model(location, location["map3d"], placement, 10)
            assert abs(spec["max_m"] - max(high[0] - low[0], high[2] - low[2])) < 1e-4
            assert abs(spec["anchor"][0] - (low[0] + high[0]) / 2) < 1e-4
            assert abs(spec["anchor"][1] - (low[2] + high[2]) / 2) < 1e-4
            assert abs(spec["bottom_y"] - low[1]) < 1e-4
        with patch("app.core.surface_textures.base_texture_file", return_value=None):
            fallback = hull_model.build_job(loc_id, desc, tex_dir=root / "missing")
            assert all(mat["texture"] is None for mat in fallback["materials"])
        meta = location_model3d.save_hull_model(loc_id, b"glTF", b"glTF",
            placement_full=job["placement"]["full"], placement_low=job["placement"]["low"],
            description=job["description"], fingerprint=job["fingerprint"], style_id="fachwerk")
        full = location_model3d.find_building_model(loc_id, tier="full")
        low_file = location_model3d.find_building_model(loc_id, tier="low")
        assert full != low_file and full.name == meta["filename"]
        assert read_sidecar(low_file)["tier"] == "low"
        selection = json.loads((full.parent / "selection.json").read_text())
        assert selection["building"] == {"full": full.name, "low": low_file.name}
        assert read_sidecar(full)["plan_hull"] is True
        # Consumer check: the flag must reach the scene spec through the client meta.
        from app.core.scene_recipe import compose_scene
        from app.models.world import get_location_by_id
        client = location_model3d.get_client_meta(loc_id)
        assert client.get("plan_hull") is True, client
        stored = get_location_by_id(loc_id)
        scene = compose_scene(stored, plan_width_m=location_model3d.derive_plan_width_m(
            loc_id, stored["map3d"]), building_meta=client)
        building = next(m for m in scene["models"] if m["role"] == "building")
        assert building.get("plan_hull") is True and building.get("cutouts"), building
        assert hull_model.hull_status(loc_id)["stale"] is False
        location["rooms"][0]["props"] = [{"id": "chair", "x": 3}]
        assert upsert_location(location, sync_world=False)
        assert hull_model.hull_status(loc_id)["stale"] is False
        location["rooms"][0]["layout"]["openings"][0]["at"] = 0.7
        assert upsert_location(location, sync_world=False)
        assert hull_model.hull_status(loc_id)["stale"] is True
        assert hull_model.hull_status(loc_id)["active"] is True
        assert full.read_bytes() == b"glTF"
        assert hull_model.build_job("missing", desc)["error"] == "not_found"
        assert hull_model.build_job(loc_id, desc, without_outline())["error"] == "no_outline"
        assert hull_model.build_job(loc_id, {"style": "missing"})["error"] == "unknown_style"
        assert hull_model.apply_wall_kinds(loc_id, style)
        written = get_location_by_id(loc_id)
        assert written["map3d"]["wall_kind"] == style["materials"]["wall"]
        assert written["map3d"]["outline"] == location["map3d"]["outline"]
        assert written["map3d"]["level_walls"] == {"0": style["materials"]["wall_ground"]}
        plain_style = {**style, "materials": {**style["materials"], "wall_ground": ""}}
        assert hull_model.apply_wall_kinds(loc_id, plain_style)
        assert "level_walls" not in get_location_by_id(loc_id)["map3d"]
        with patch.object(runner, "is_available", return_value=False):
            assert hull_model.generate_hull(loc_id, desc)["error"] == "blender_unavailable"
        queue = Mock()
        queue.track_start.return_value = "hull-task"
        with patch("threading.Thread") as thread, patch("app.core.task_queue.get_task_queue", return_value=queue), patch.object(hull_model, "generate_hull", return_value={"ok": False, "error": "test failure"}):
            assert hull_model.trigger_hull_generation(loc_id, desc)
            assert hull_model.hull_status(loc_id)["pending"]
            assert not hull_model.trigger_hull_generation(loc_id, desc)
            thread.call_args.kwargs["target"]()
            assert not hull_model.hull_status(loc_id)["pending"]
            queue.track_finish.assert_called_once_with("hull-task", error="test failure")
        if not runner.is_available():
            print("SKIP Blender: binary unavailable")
        else:
            if args.out:
                args.out.mkdir(parents=True, exist_ok=True)
            for style_id in (hull_styles.load_styles() if args.out else ("fachwerk", "modern")):
                with patch.object(hull_model, "timeout_s", return_value=600):
                    result = hull_model.generate_hull(loc_id, {"style": style_id, "seed": 4})
                assert result["ok"], result
                expected_job = hull_model.build_job(loc_id, {"style": style_id, "seed": 4}, tex_dir=root / "verify")
                if style_id == 'modern':
                    assert {'blind','facade_module'} <= {m['name'] for m in expected_job['materials']}
                boxes = []
                for tier in ("full", "low"):
                    file = location_model3d.find_building_model(loc_id, tier=tier)
                    blob = file.read_bytes()
                    length = struct.unpack_from("<I", blob, 12)[0]
                    document = json.loads(blob[20:20 + length])
                    assert document.get("images"), "textured GLB must embed images"
                    assert all("bufferView" in image and "uri" not in image for image in document["images"])
                    for node in document["nodes"]:
                        if "mesh" in node:
                            assert node["extras"]["interior_cutout_padding_m"] == expected_job["extras"]["interior_cutout_padding_m"]
                            assert len(document["meshes"][node["mesh"]]["primitives"]) == 1
                    accessors = []
                    for mesh in document["meshes"]:
                        for primitive in mesh["primitives"]:
                            assert {"COLOR_0", "TEXCOORD_0"} <= primitive["attributes"].keys()
                            accessors.append(document["accessors"][primitive["attributes"]["POSITION"]])
                    boxes.append([min(a["min"][i] for a in accessors) for i in (0, 2)] +
                                 [max(a["max"][i] for a in accessors) for i in (0, 2)])
                    if args.out:
                        shutil.copyfile(file, args.out / f"hull_{style_id}_{tier}.glb")
                assert all(abs(a - b) < 1e-4 for a, b in zip(*boxes)), boxes
                print(f"PASS Blender {style_id}", flush=True)
        print("PASS hull model")


if __name__ == "__main__":
    main()
