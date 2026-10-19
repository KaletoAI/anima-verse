"""Build a door GLB (nodes frame/leaf) from finished meshes; geometry belongs to Python core."""
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
    material.diffuse_color = (*spec["color"], spec["alpha"])
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
    job = json.loads(Path(args["inputs"]["job"]).read_text(encoding="utf-8"))
    _common.reset_scene()
    materials = {spec["name"]: _material(spec, args["inputs"]) for spec in job["materials"]}
    objects = {spec["name"]: _object(spec, materials, {}) for spec in job["meshes"]}
    for spec in job["meshes"]:
        if spec["name"] != spec["node"]:
            objects[spec["name"]].parent = objects[spec["node"]]
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects.values():
        obj.select_set(True)
    target = Path(args["out_dir"]) / "model.glb"
    bpy.ops.export_scene.gltf(filepath=str(target), export_format="GLB", use_selection=True,
                              export_extras=True, export_vertex_color="ACTIVE")
    outputs = {"model": str(target)}
    if job["mode"] == "thumbnail":
        from mathutils import Vector
        scene = bpy.context.scene
        # Cycles on the CPU: Workbench shows textured materials flat grey, and EEVEE
        # needs a display headless servers do not have.
        scene.render.engine = "CYCLES"
        scene.cycles.device = "CPU"
        scene.cycles.samples = 24
        scene.cycles.use_denoising = False
        scene.render.resolution_x = scene.render.resolution_y = 256
        scene.render.resolution_percentage = 100
        scene.render.film_transparent = False
        if scene.world is None:
            scene.world = bpy.data.worlds.new("Preview")
        scene.world.use_nodes = True
        background = scene.world.node_tree.nodes["Background"]
        background.inputs[0].default_value = (.75, .77, .8, 1)
        background.inputs[1].default_value = 1.0
        sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN"))
        sun.data.energy = 3.0
        sun.rotation_euler = (.9, .2, -.5)
        scene.collection.objects.link(sun)
        points = [Vector(point) for spec in job["meshes"] for point in spec["vertices"]]
        low = Vector([min(p[i] for p in points) for i in range(3)])
        high = Vector([max(p[i] for p in points) for i in range(3)])
        center = (low + high) / 2
        camera_data = bpy.data.cameras.new("Preview")
        camera = bpy.data.objects.new("Preview", camera_data)
        scene.collection.objects.link(camera)
        camera.location = center + Vector((3, -6, 2.4))
        camera.rotation_euler = (center-camera.location).to_track_quat("-Z", "Y").to_euler()
        camera_data.type = "ORTHO"
        camera_data.ortho_scale = (high-low).length * 1.2
        scene.camera = camera
        image = Path(args["out_dir"]) / "thumbnail.png"
        scene.render.image_settings.file_format = "PNG"
        scene.render.filepath = str(image)
        bpy.ops.render.render(write_still=True)
        outputs["thumbnail"] = str(image)
    return {}, outputs


_common.main(build)
