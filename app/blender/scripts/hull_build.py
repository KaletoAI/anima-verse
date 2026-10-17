"""Execute finished hull meshes and materials; geometry belongs to Python core."""
import json
from pathlib import Path
import sys

_SCRIPTS_DIR = str(Path(__file__).parent)
sys.path.insert(0, _SCRIPTS_DIR)
import _common
sys.path.remove(_SCRIPTS_DIR)
import bpy


def _material(spec: dict, inputs: dict):
    """Create the supplied material, embedding its optional image on export."""
    material = bpy.data.materials.new(spec["name"])
    shader = material.node_tree.nodes.get("Principled BSDF")
    shader.inputs["Base Color"].default_value = (*spec["color"], spec["alpha"])
    shader.inputs["Alpha"].default_value = spec["alpha"]
    shader.inputs["Roughness"].default_value = spec["roughness"]
    if spec["alpha"] < 1:
        material.surface_render_method = "DITHERED"
    if spec["texture"]:
        texture = material.node_tree.nodes.new("ShaderNodeTexImage")
        texture.image = bpy.data.images.load(str(inputs[spec["texture"]]), check_existing=True)
        material.node_tree.links.new(texture.outputs["Color"], shader.inputs["Base Color"])
    return material


def _object(spec: dict, materials: dict, extras: dict):
    """Copy vertices, faces and corner attributes into a single-material object."""
    mesh = bpy.data.meshes.new(spec["name"])
    mesh.from_pydata(spec["vertices"], [], spec["faces"])
    mesh.update()
    obj = bpy.data.objects.new(spec["name"], mesh)
    bpy.context.scene.collection.objects.link(obj)
    mesh.materials.append(materials[spec["material"]])
    uv_layer = mesh.uv_layers.new(name="UVMap")
    colors = mesh.color_attributes.new(name="Color", type="BYTE_COLOR", domain="CORNER")
    mesh.color_attributes.active_color = colors
    for polygon, uvs, shades in zip(mesh.polygons, spec["uvs"], spec["colors"]):
        for index, uv, shade in zip(polygon.loop_indices, uvs, shades):
            uv_layer.data[index].uv = uv
            colors.data[index].color = (shade, shade, shade, 1.0)
    for key, value in extras.items():
        obj[key] = value
    return obj


def build(args: dict) -> tuple:
    """Export each tier's objects as a GLB with extras, UVs and vertex colours."""
    job = json.loads(Path(args["inputs"]["job"]).read_text(encoding="utf-8"))
    _common.reset_scene()
    materials = {spec["name"]: _material(spec, args["inputs"]) for spec in job["materials"]}
    data, outputs = {}, {}
    for tier, payload in job["tiers"].items():
        bpy.ops.object.select_all(action="DESELECT")
        objects = [_object(spec, materials, job["extras"]) for spec in payload["meshes"]]
        for obj in objects:
            obj.select_set(True)
        target = Path(args["out_dir"]) / job["export"][tier]
        bpy.ops.export_scene.gltf(filepath=str(target), export_format="GLB", use_selection=True,
                                  export_extras=True, export_vertex_color="ACTIVE")
        vertices = [point for spec in payload["meshes"] for point in spec["vertices"]]
        data[tier] = {"tris": sum(len(face) - 2 for spec in payload["meshes"] for face in spec["faces"]),
                      "bytes": target.stat().st_size,
                      "bbox": [min(point[i] for point in vertices) for i in range(3)] +
                              [max(point[i] for point in vertices) for i in range(3)]}
        outputs[tier] = str(target)
    return data, outputs


_common.main(build)
