#!/usr/bin/env python3
"""Self-authored Hogwarts arrival/grounds assets for Blender 4.2.

Run: blender -b --python arrival_assets.py -- --output /absolute/assets/path
Only the explicit CLI builds files. No downloaded imagery, fonts, meshes or
runtime packages are used. Blender's built-in vector font supplies signage.
All sizes below are metres in Blender Z-up; export is glTF Y-up. The measured,
ground-centred result, rather than a nominal design size, goes in the manifest.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import random
import struct
import sys
import tempfile
import zlib


PROVENANCE = (
    "Self-authored procedural Blender geometry/textures; film reference only; "
    "no extracted/downloaded assets"
)


def png_bytes(size, pixels):
    """Encode original RGB pixels without a third-party imaging dependency."""
    def chunk(kind, payload):
        return (struct.pack(">I", len(payload)) + kind + payload
                + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF))
    rows = b"".join(b"\0" + bytes(pixels[y * size * 3:(y + 1) * size * 3])
                    for y in range(size))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b""))


def make_materials(bpy, directory):
    """Small tileable, self-authored albedo PNGs with metallic/roughness PBR."""
    specs = {
        "stone": ((151, 132, 100), "masonry", .88, 0),
        "granite": ((122, 127, 120), "masonry", .91, 0),
        "brick": ((112, 61, 42), "masonry", .88, 0),
        "slate": ((49, 61, 66), "slate", .83, 0),
        "wood": ((109, 72, 39), "wood", .8, 0),
        "oak": ((151, 107, 57), "wood", .75, 0),
        "bark": ((76, 62, 45), "bark", .98, 0),
        "pine": ((36, 72, 44), "leaf", .92, 0),
        "leaf": ((69, 103, 43), "leaf", .92, 0),
        "leaf-light": ((96, 121, 51), "leaf", .94, 0),
        "green": ((31, 70, 52), "paint", .55, .1),
        "cream": ((220, 210, 172), "paint", .6, 0),
        "crimson": ((130, 24, 32), "paint", .39, .25),
        "black": ((23, 28, 29), "paint", .45, .45),
        "steel": ((108, 117, 120), "paint", .3, .8),
        "gold": ((184, 137, 49), "paint", .31, .65),
        "glass": ((42, 74, 84), "glass", .22, .25),
        "lamp": ((244, 193, 98), "glass", .28, .05),
        "leather": ((86, 43, 28), "leather", .72, 0),
        "coal": ((29, 28, 25), "masonry", .97, 0),
    }
    result = {}
    for index, (name, (base, pattern, roughness, metal)) in enumerate(specs.items()):
        rng = random.Random(4300 + index)
        size = 128
        pixels = bytearray()
        for y in range(size):
            for x in range(size):
                delta = rng.uniform(-6, 6)
                if pattern == "masonry":
                    row = y // 32
                    xx = (x + (row % 2) * 32) % 64
                    delta += -31 if y % 32 < 3 or xx < 3 else ((row * 13 + x // 64 * 7) % 15 - 7)
                elif pattern == "slate":
                    delta += -18 if y % 32 < 2 or (x + 16 * (y // 32)) % 32 < 2 else 0
                elif pattern in ("wood", "bark"):
                    delta += math.sin(x * .36 + math.sin(y * .049) * 2.2) * 12
                    delta += math.sin(x * 1.7 + math.sin(y * .11)) * 4
                    if pattern == "bark" and x % 17 < 2:
                        delta -= 20
                elif pattern == "leaf":
                    delta += math.sin(x * .48) * math.cos(y * .41) * 12
                elif pattern == "glass":
                    delta += 10 * math.sin((x + y) / 128 * math.tau)
                elif pattern == "leather":
                    delta += 4 * math.sin(x * 1.5) * math.cos(y * 1.7)
                pixels.extend(max(0, min(255, round(channel + delta))) for channel in base)
        image_path = directory / (name + ".png")
        image_path.write_bytes(png_bytes(size, pixels))
        image = bpy.data.images.load(str(image_path), check_existing=False)
        image.name = "Original " + name + " albedo"
        image.pack()
        material = bpy.data.materials.new(name)
        material.use_nodes = True
        material.diffuse_color = tuple(v / 255 for v in base) + (1,)
        shader = material.node_tree.nodes.get("Principled BSDF")
        shader.inputs["Roughness"].default_value = roughness
        shader.inputs["Metallic"].default_value = metal
        texture = material.node_tree.nodes.new("ShaderNodeTexImage")
        texture.image = image
        texture.interpolation = "Linear"
        texture.extension = "REPEAT"
        material.node_tree.links.new(texture.outputs["Color"], shader.inputs["Base Color"])
        if name == "lamp":
            material.node_tree.links.new(texture.outputs["Color"], shader.inputs["Emission Color"])
            shader.inputs["Emission Strength"].default_value = .65
        result[name] = material
    return result


class Mesh:
    """One material-batched mesh per asset, with explicit planar face UVs."""
    def __init__(self, name, materials):
        self.name = name
        self.materials = materials
        self.names = list(materials)
        self.vertices = []
        self.faces = []
        self.face_materials = []
        self.smooth = []
        self.texts = []

    def face(self, points, material, smooth=False):
        start = len(self.vertices)
        self.vertices.extend(tuple(p) for p in points)
        self.faces.append(tuple(range(start, start + len(points))))
        self.face_materials.append(self.names.index(material))
        self.smooth.append(smooth)

    def box(self, center, size, material, yaw=0):
        x, y, z = center
        a, b, c = (v / 2 for v in size)
        co, si = math.cos(yaw), math.sin(yaw)
        points = []
        for xx, yy, zz in ((-a, -b, -c), (a, -b, -c), (a, b, -c), (-a, b, -c),
                           (-a, -b, c), (a, -b, c), (a, b, c), (-a, b, c)):
            points.append((x + co * xx - si * yy, y + si * xx + co * yy, z + zz))
        for ids in ((3, 2, 1, 0), (0, 1, 5, 4), (1, 2, 6, 5),
                    (2, 3, 7, 6), (3, 0, 4, 7), (4, 5, 6, 7)):
            self.face([points[i] for i in ids], material)

    def beam(self, start, end, radius, material, radius_end=None, sides=10):
        from mathutils import Vector
        start, end = Vector(start), Vector(end)
        axis = (end - start).normalized()
        u = axis.cross(Vector((0, 0, 1)))
        if u.length < .01:
            u = axis.cross(Vector((0, 1, 0)))
        u.normalize()
        v = axis.cross(u).normalized()
        r2 = radius if radius_end is None else radius_end
        rings = [[p + (u * math.cos(i * math.tau / sides) + v * math.sin(i * math.tau / sides)) * r
                  for i in range(sides)] for p, r in ((start, radius), (end, r2))]
        self.face(list(reversed(rings[0])), material)
        self.face(rings[1], material)
        for i in range(sides):
            j = (i + 1) % sides
            self.face((rings[0][i], rings[0][j], rings[1][j], rings[1][i]), material, True)

    def ellipsoid(self, center, radii, material, segments=12, rings=7, seed=0):
        rng = random.Random(seed)
        grid = []
        for j in range(rings + 1):
            phi = math.pi * j / rings
            row = []
            for i in range(segments):
                theta = math.tau * i / segments
                wobble = 1 + rng.uniform(-.09, .09) if 0 < j < rings else 1
                row.append((center[0] + radii[0] * math.sin(phi) * math.cos(theta) * wobble,
                            center[1] + radii[1] * math.sin(phi) * math.sin(theta) * wobble,
                            center[2] + radii[2] * math.cos(phi) * wobble))
            grid.append(row)
        for j in range(rings):
            for i in range(segments):
                k = (i + 1) % segments
                if j == 0:
                    self.face((grid[0][i], grid[1][i], grid[1][k]), material, True)
                elif j == rings - 1:
                    self.face((grid[j][i], grid[j + 1][i], grid[j][k]), material, True)
                else:
                    self.face((grid[j][i], grid[j + 1][i], grid[j + 1][k], grid[j][k]), material, True)

    def torus(self, center, major, minor, material, axis="z", segments=20, tube=6):
        rows = []
        for i in range(segments):
            a = i * math.tau / segments
            row = []
            for j in range(tube):
                b = j * math.tau / tube
                p = ((major + minor * math.cos(b)) * math.cos(a),
                     (major + minor * math.cos(b)) * math.sin(a), minor * math.sin(b))
                if axis == "x":
                    p = (p[2], p[0], p[1])
                elif axis == "y":
                    p = (p[0], p[2], p[1])
                row.append(tuple(center[k] + p[k] for k in range(3)))
            rows.append(row)
        for i in range(segments):
            for j in range(tube):
                self.face((rows[i][j], rows[(i + 1) % segments][j],
                           rows[(i + 1) % segments][(j + 1) % tube], rows[i][(j + 1) % tube]), material, True)

    def gable(self, center, width, depth, eave, rise, material, ridge="x"):
        """Closed pitched roof prism, with an optional cross-gable orientation."""
        x, y, z = center
        a, b = width / 2, depth / 2
        p = [(x-a, y-b, z+eave), (x+a, y-b, z+eave),
             (x+a, y+b, z+eave), (x-a, y+b, z+eave),
             (x-a, y, z+eave+rise), (x+a, y, z+eave+rise)]
        if ridge == "y":
            p = [(x+(py-y), y+(px-x), pz) for px, py, pz in p]
        for ids in ((0, 1, 5, 4), (4, 5, 2, 3), (0, 4, 3), (1, 2, 5), (3, 2, 1, 0)):
            self.face([p[i] for i in ids], material)

    def text(self, words, center, size, material="cream", side="front"):
        self.texts.append((words, center, size, material, side))

    def object(self, bpy):
        mesh = bpy.data.meshes.new(self.name)
        mesh.from_pydata(self.vertices, [], self.faces)
        mesh.materials.clear()
        for material in self.materials.values():
            mesh.materials.append(material)
        mesh.update()
        uv = mesh.uv_layers.new(name="UVMap")
        for polygon, material_index, smooth in zip(mesh.polygons, self.face_materials, self.smooth):
            polygon.material_index = material_index
            polygon.use_smooth = smooth
            n = polygon.normal
            dominant = max(range(3), key=lambda i: abs(n[i]))
            axes = ((1, 2), (0, 2), (0, 1))[dominant]
            tex_scale = 1.2 if self.names[material_index] in ("stone", "granite", "brick", "slate") else .5
            for loop in polygon.loop_indices:
                vertex = mesh.vertices[mesh.loops[loop].vertex_index].co
                uv.data[loop].uv = (vertex[axes[0]] / tex_scale, vertex[axes[1]] / tex_scale)
        obj = bpy.data.objects.new(self.name, mesh)
        bpy.context.collection.objects.link(obj)
        objects = [obj]
        for words, center, size, material, side in self.texts:
            curve = bpy.data.curves.new("Original lettering", "FONT")
            curve.body = words
            curve.size = size
            curve.align_x = "CENTER"
            curve.align_y = "CENTER"
            curve.extrude = .0015
            curve.resolution_u = 4
            curve.materials.append(self.materials[material])
            lettering = bpy.data.objects.new(words, curve)
            bpy.context.collection.objects.link(lettering)
            lettering.location = center
            yaw = {"front": 0, "side": math.pi / 2, "left": -math.pi / 2}[side]
            lettering.rotation_euler = (math.pi / 2, 0, yaw)
            bpy.context.view_layer.objects.active = lettering
            lettering.select_set(True)
            bpy.ops.object.convert(target="MESH")
            lettering = bpy.context.view_layer.objects.active
            if not lettering.data.uv_layers:
                layer = lettering.data.uv_layers.new(name="UVMap")
                for loop in lettering.data.loops:
                    p = lettering.data.vertices[loop.vertex_index].co
                    layer.data[loop.index].uv = (p.x, p.y)
            lettering.select_set(False)
            objects.append(lettering)
        return objects


def window(mesh, x, y, z, width=1.2, height=1.7, trim="cream"):
    mesh.box((x, y, z), (width, .07, height), "glass")
    for xx in (-width / 2, width / 2):
        mesh.box((x+xx, y-.06, z), (.09, .12, height+.16), trim)
    for zz in (-height / 2, 0, height / 2):
        mesh.box((x, y-.07, z+zz), (width+.1, .12, .08), trim)
    mesh.box((x, y-.08, z), (.06, .13, height), trim)
    mesh.box((x, y-.13, z-height/2-.1), (width+.3, .34, .14), "stone")


def station(mesh):
    mesh.box((0, .35, .15), (31.5, 9.8, .3), "granite")
    # Thin perimeter walls leave real interior space and two clear entrances.
    mesh.box((0, 4.4, 2.3), (30.6, .4, 4.3), "stone")
    for x in (-15.1, 15.1):
        mesh.box((x, .825, 2.3), (.4, 7.55, 4.3), "stone")
    for left, right in ((-15.3, -5.35), (-3.85, 3.85), (5.35, 15.3)):
        mesh.box(((left+right)/2, -2.55, 2.3), (right-left, .4, 4.3), "stone")
        mesh.box(((left+right)/2, -2.57, .55), (right-left, .44, .45), "brick")
    for x in (-4.6, 4.6):
        mesh.box((x, -2.55, 3.9), (1.5, .4, 1.1), "stone")
    mesh.gable((0, .95, 0), 31.5, 8, 4.5, 2.15, "slate")
    for x in (-11.4, 0, 11.4):
        # Projecting gabled bays break up the long Goathland-style roofline.
        for xx in (-2.35, 2.35):
            mesh.box((x+xx, -2.72, 2.65), (.3, .25, 4.7), "stone")
        mesh.gable((x, .8, 0), 7.8, 5.5, 4.95, 2.5, "slate", ridge="y")
        mesh.face(((x-2.5, -3.105, 4.95), (x+2.5, -3.105, 4.95),
                   (x, -3.105, 7.22)), "stone")
        mesh.box((x+1.5, 2.7, 6.65), (.8, .85, 2.6), "brick")
        mesh.box((x+1.5, 2.7, 7.92), (1.0, 1.0, .18), "stone")
        for potx in (-.21, .21):
            mesh.beam((x+1.5+potx, 2.7, 7.98), (x+1.5+potx, 2.7, 8.42), .12, "brick")
    for x in (-13.2, -9.5, -7.0, -4.6, 0, 4.6, 7, 9.5, 13.2):
        if x in (-4.6, 4.6):
            # Open leaves extend inside, preserving the full 1.5 m doorway.
            mesh.box((x+.7, -1.95, 1.8), (.1, 1.35, 2.9), "green")
            mesh.beam((x+.63, -1.35, 1.6), (x+.63, -1.35, 1.75), .025, "gold")
            for xx in (-.79, .79):
                mesh.box((x+xx, -2.8, 1.8), (.1, .12, 3.05), "cream")
            mesh.box((x, -2.8, 3.35), (1.68, .12, .1), "cream")
        else:
            window(mesh, x, -2.79, 2.55, 1.24, 1.8)
    # Pitched green canopy, posts, braces and scalloped valance.
    mesh.face(((-15.8, -2.75, 4.12), (15.8, -2.75, 4.12),
               (15.8, -5.55, 3.67), (-15.8, -5.55, 3.67)), "green")
    mesh.box((0, -5.55, 3.61), (31.6, .13, .23), "cream")
    for x in range(-15, 16, 3):
        mesh.beam((x, -5.28, .3), (x, -5.28, 3.72), .075, "green")
        for dx in (-.65, .65):
            mesh.beam((x, -5.28, 3.04), (x+dx, -5.28, 3.62), .04, "green")
        mesh.box((x, -5.28, .45), (.22, .22, .3), "cream")
    for i in range(80):
        mesh.box((-15.6 + i * .395, -5.56, 3.43), (.23, .1, .16), "cream")
    for x in (-10, 10):
        mesh.box((x, -5.66, 3.2), (3.8, .12, .68), "green")
        mesh.text("HOGSMEADE", (x, -5.735, 3.2), .43)
    mesh.box((0, -2.86, 4.1), (4.1, .12, .5), "green")
    mesh.text("TICKETS  /  FAHRKARTEN", (0, -2.94, 4.1), .22)
    # Platform paving edge and drain preserve a usable open forecourt.
    for x in range(-15, 16):
        mesh.box((x, -5.68, .18), (.94, .25, .12), "cream")


def wheel(mesh, y, radius, drive=False):
    z = radius + .08
    for side in (-1, 1):
        x = side * 1.04
        mesh.beam((x-.12, y, z), (x+.12, y, z), radius, "black", sides=24)
        outer = side * 1.19
        mesh.torus((outer, y, z), radius-.075, .062, "steel", axis="x", segments=24)
        mesh.beam((outer-side*.025, y, z), (outer+side*.05, y, z), .16, "crimson", sides=14)
        if drive:
            for i in range(12):
                a = i * math.tau / 12
                mesh.beam((outer, y, z), (outer, y+math.cos(a)*(radius-.12), z+math.sin(a)*(radius-.12)),
                          .036, "crimson", sides=6)
    mesh.beam((-1.13, y, z), (1.13, y, z), .09, "steel")


def train(mesh):
    # Boiler and locomotive front face point toward local -Y (glTF +Z).
    mesh.box((0, -32.4, 1.22), (2.8, 13.3, .32), "black")
    mesh.beam((0, -36.8, 2.55), (0, -28.25, 2.55), 1.06, "crimson", sides=32)
    mesh.beam((0, -38.0, 2.55), (0, -36.7, 2.55), 1.08, "black", sides=32)
    mesh.beam((0, -38.13, 2.55), (0, -38.02, 2.55), .88, "black", sides=32)
    mesh.torus((0, -38.15, 2.55), .9, .045, "steel", axis="y", segments=32)
    mesh.beam((0, -38.2, 2.55), (0, -38.28, 2.55), .12, "gold")
    for y in (-36.5, -34.0, -31.4, -29.0):
        mesh.torus((0, y, 2.55), 1.075, .038, "gold", axis="y", segments=28)
    mesh.beam((0, -37.15, 3.25), (0, -37.15, 4.45), .3, "black", radius_end=.4, sides=20)
    mesh.torus((0, -37.15, 4.44), .4, .055, "steel")
    for y in (-33.7, -31.2):
        mesh.beam((0, y, 3.4), (0, y, 3.95), .31, "gold", radius_end=.26, sides=18)
        mesh.ellipsoid((0, y, 3.96), (.28, .28, .17), "gold")
    for side in (-1, 1):
        mesh.beam((side*1.04, -36.8, 3.1), (side*1.04, -28.4, 3.1), .033, "gold")
        for y in (-35.8, -33.8, -31.8, -29.8):
            mesh.beam((side*.97, y, 3.03), (side*1.08, y, 3.14), .03, "gold")
    for y in (-35.2, -33.3, -31.4):
        wheel(mesh, y, .91, True)
    for y in (-37.1, -27.0):
        wheel(mesh, y, .52)
    for side in (-1, 1):
        mesh.beam((side*1.29, -35.2, .86), (side*1.29, -31.4, .86), .08, "steel", sides=8)
        mesh.beam((side*1.33, -36.5, 1.3), (side*1.33, -33.2, .86), .055, "steel", sides=8)
        mesh.beam((side*1.07, -36.6, 1.35), (side*1.07, -35.5, 1.35), .23, "black")
        mesh.box((side*1.17, -29.0, 1.65), (.42, 1.15, .12), "black")
        for z in (.64, .96, 1.28):
            mesh.box((side*1.35, -27.9, z), (.5, .62, .09), "steel")
    # Cab: open side windows between actual pillars, a curved barrel roof.
    mesh.box((0, -27.4, 1.9), (2.9, 3.2, 1.25), "crimson")
    for side in (-1, 1):
        for y in (-28.8, -26.0):
            mesh.box((side*1.38, y, 3.15), (.16, .18, 1.45), "crimson")
        mesh.box((side*1.38, -27.4, 3.88), (.17, 3.05, .17), "gold")
        mesh.box((side*1.38, -27.4, 2.62), (.18, 3.05, .14), "gold")
    mesh.box((0, -28.84, 3.18), (2.7, .12, 1.4), "black")
    for x in (-.8, .8):
        window(mesh, x, -28.94, 3.18, .62, .81, "gold")
    barrel_roof(mesh, -27.4, 3.45, 3.5, 3.88, .56, "black")
    mesh.box((0, -39, 1.25), (3.15, .22, .43), "crimson")
    for x in (-1, 1):
        mesh.beam((x, -39.1, 1.2), (x, -39.65, 1.2), .17, "black")
        mesh.beam((x, -39.66, 1.2), (x, -39.75, 1.2), .27, "steel")
    mesh.beam((0, -39.08, 1.7), (0, -39.22, 1.7), .15, "lamp")
    mesh.box((0, -38.2, 3.3), (1.5, .08, .3), "crimson")
    mesh.text("HOGWARTS EXPRESS", (0, -38.25, 3.3), .105, "gold")
    mesh.box((0, -38.23, 2.1), (.8, .07, .22), "crimson")
    mesh.text("5972", (0, -38.28, 2.1), .16, "gold")
    # Tender has a genuinely open top with individually modeled coal lumps.
    mesh.box((0, -21.3, 1.35), (2.95, 7.8, .35), "black")
    for x in (-1.43, 1.43):
        mesh.box((x, -21.3, 2.5), (.16, 7.55, 2.0), "crimson")
        for z in (1.7, 3.4):
            mesh.box((x*1.01, -21.3, z), (.04, 7.5, .055), "gold")
    for y in (-25.0, -17.6):
        mesh.box((0, y, 2.5), (2.8, .15, 2), "crimson")
    for y in (-23.7, -21.5, -19.2):
        wheel(mesh, y, .61)
    rng = random.Random(5972)
    for i in range(48):
        mesh.ellipsoid((rng.uniform(-1.1, 1.1), rng.uniform(-24.4, -18.1), rng.uniform(2.9, 3.3)),
                       (.28, .4, .22), "coal", segments=7, rings=4, seed=i)
    for side in (-1, 1):
        mesh.text("HOGWARTS", (side*1.53, -21.3, 2.55), .3, "gold", "side" if side > 0 else "left")
    for coach_index, cy in enumerate((-4.5, 20.5), 1):
        coach(mesh, cy, coach_index)
    for y in (-25.6, -16.8, 7.8):
        mesh.beam((0, y-.6, 1.05), (0, y+.6, 1.05), .11, "black")


def barrel_roof(mesh, y, width, length, base_z, rise, material):
    points = []
    for i in range(17):
        t = math.pi * i / 16
        points.append((-width/2 * math.cos(t), base_z + rise * math.sin(t)))
    for i in range(16):
        a, b = points[i], points[i+1]
        mesh.face(((a[0], y-length/2, a[1]), (b[0], y-length/2, b[1]),
                   (b[0], y+length/2, b[1]), (a[0], y+length/2, a[1])), material, True)
    for end in (-1, 1):
        cap = [(x, y+end*length/2, z) for x, z in points]
        mesh.face(cap if end == -1 else list(reversed(cap)), material)


def coach(mesh, cy, number):
    mesh.box((0, cy, 1.2), (2.98, 23.5, .32), "black")
    mesh.box((0, cy, 2.02), (3.05, 23.5, 1.34), "crimson")
    # Upper walls are built around the windows, not window-coloured boxes.
    for side in (-1, 1):
        sx = side*1.5
        mesh.box((sx, cy, 3.87), (.12, 23.5, .25), "crimson")
        for z in (1.52, 2.68, 3.74):
            mesh.box((side*1.58, cy, z), (.035, 23.4, .045), "gold")
        for i in range(11):
            y = cy-10.5+i*2.1
            mesh.box((sx, y, 3.2), (.1, 1.62, .95), "glass")
            for yy in (-.86, .86):
                mesh.box((side*1.56, y+yy, 3.22), (.08, .12, 1.1), "gold")
            mesh.box((side*1.56, y, 3.42), (.08, 1.75, .05), "gold")
        for i in range(12):
            mesh.box((sx, cy-11.55+i*2.1, 3.22), (.16, .37, 1.12), "crimson")
        for y in (cy-10.9, cy+10.9):
            mesh.box((side*1.61, y, 2.03), (.07, .07, .35), "gold")
            for z in (.57, .87):
                mesh.box((side*1.62, y, z), (.43, .8, .07), "black")
        mesh.text("HOGWARTS EXPRESS", (side*1.61, cy, 2.12), .25, "gold", "side" if side > 0 else "left")
    for y in (cy-11.74, cy+11.74):
        mesh.box((0, y, 2.65), (2.9, .13, 2.4), "crimson")
        mesh.box((0, y+( .1 if y > cy else -.1), 2.7), (.85, .24, 2.1), "black")
        for side in (-1, 1):
            mesh.beam((side*1.0, y, 1.2), (side*1.0, y+(.45 if y > cy else -.45), 1.2), .15, "black")
    for center in (cy-7.8, cy+7.8):
        mesh.box((0, center, .95), (2.45, 3.6, .3), "black")
        for dy in (-1.05, 1.05):
            wheel(mesh, center+dy, .55)
        for side in (-1, 1):
            mesh.beam((side*1.24, center-1.4, .92), (side*1.24, center+1.4, .92), .12, "black")
    barrel_roof(mesh, cy, 3.28, 24, 3.98, .55, "black")
    for y in range(-9, 10, 3):
        mesh.ellipsoid((0, cy+y, 4.53), (.18, .34, .11), "steel", segments=8, rings=4)


def boathouse(mesh):
    # Open water-facing entrance (-Y); no hidden solid wall across the doors.
    mesh.box((0, .3, .18), (18, 11.4, .36), "granite")
    for x in (-8.5, 8.5):
        mesh.box((x, .2, 2.7), (1, 10.8, 5.1), "stone")
        for y in (-4.5, -.8, 3.5):
            mesh.box((x*1.035, y, 2.25), (1.25, .65, 4.15), "stone")
    mesh.box((0, 5.35, 2.75), (17, .7, 5.15), "stone")
    for x in (-7.2, 0, 7.2):
        mesh.box((x, -5, 2.7), (1.25, .8, 5.1), "stone")
    mesh.box((0, -5, 5.0), (17, .8, .65), "stone")
    mesh.gable((0, .2, 0), 18.5, 12.1, 5.25, 3.8, "slate")
    mesh.box((0, .2, 9.05), (18.5, .2, .18), "granite")
    for x in (-7.65, 7.65):
        # Hinged leaves standing open against the outside piers.
        mesh.box((x, -6.5, 2.35), (.18, 3.3, 4.0), "wood")
        for y in (-7.6, -5.4):
            mesh.box((x, y, 2.35), (.23, .12, 3.9), "black")
        mesh.beam((x, -7.9, .55), (x, -5.1, 4.1), .06, "black")
    for x in (-5.7, -3.1, 3.1, 5.7):
        mesh.beam((x, -4.9, 4.9), (x, 4.7, 4.9), .13, "wood")
    for x in (-4, 4):
        window(mesh, x, 4.94, 3.3, 1.2, 1.6, "wood")
    mesh.box((0, -5.5, 5.0), (4.3, .13, .52), "wood")
    mesh.text("BOOTSHAUS", (0, -5.59, 5.0), .39)
    for x in (-7.8, 7.8):
        mesh.beam((x, -5.6, .36), (x, -5.6, 1.05), .11, "black")
        mesh.torus((x, -5.6, 1.05), .2, .035, "steel", axis="y")


def rowboat(mesh):
    # Clinker-built open hull: nested longitudinal ribs/planks, solid gunwales.
    stations = [(-2, .04), (-1.75, .39), (-1.25, .64), (-.6, .74),
                (.3, .73), (1.1, .59), (1.7, .34), (2, .045)]
    levels = [(.12, .06), (.18, .34), (.32, .66), (.53, .9), (.72, 1.0)]
    for side in (-1, 1):
        for level in range(len(levels)-1):
            z0, factor0 = levels[level]
            z1, factor1 = levels[level+1]
            for i in range(len(stations)-1):
                y0, w0 = stations[i]
                y1, w1 = stations[i+1]
                mesh.face(((side*w0*factor0, y0, z0), (side*w1*factor0, y1, z0),
                           (side*w1*factor1, y1, z1), (side*w0*factor1, y0, z1)), "oak")
                # Real interior faces with a 24 mm timber thickness.
                mesh.face(((side*(w0*factor1-.024), y0, z1), (side*(w1*factor1-.024), y1, z1),
                           (side*max(.005,w1*factor0-.024), y1, z0),
                           (side*max(.005,w0*factor0-.024), y0, z0)), "wood")
                mesh.beam((side*w0*factor1, y0, z1), (side*w1*factor1, y1, z1), .014, "wood", sides=5)
        for i in range(len(stations)-1):
            y0, w0 = stations[i]
            y1, w1 = stations[i+1]
            mesh.beam((side*w0, y0, .72), (side*w1, y1, .72), .045, "wood", sides=8)
    mesh.beam((0, -2, .12), (0, 2, .12), .04, "wood")
    for y, width in ((-1.2, .57), (-.45, .69), (.5, .67), (1.3, .47)):
        mesh.box((0, y, .17), (width*1.45, .12, .07), "wood")
        for side in (-1, 1):
            mesh.beam((side*.12, y, .17), (side*width*.96, y, .67), .024, "oak", sides=6)
    for y, width in ((-.95, 1.15), (.45, 1.3)):
        mesh.box((0, y, .53), (width, .28, .055), "oak")
    # Oars stowed longitudinally, with tapered blades rather than loose sticks.
    for x in (-.3, .3):
        mesh.beam((x, -1.55, .78), (x, 1.0, .78), .024, "oak", sides=8)
        mesh.face(((x-.045, .85, .78), (x+.045, .85, .78),
                   (x+.115, 1.62, .78), (x-.115, 1.62, .78)), "oak")
    for side in (-1, 1):
        mesh.torus((side*.73, -.2, .75), .042, .012, "steel", axis="y", segments=10, tube=5)
    mesh.beam((0, -1.98, .15), (0, -1.98, .8), .038, "wood")
    mesh.beam((0, 1.98, .15), (0, 1.98, .79), .038, "wood")


def jetty(mesh):
    for i in range(44):
        mesh.box((0, -5.375+i*.25, .78), (3, .235, .13), "wood")
    for x in (-1.15, 1.15):
        mesh.box((x, 0, .58), (.18, 11, .28), "wood")
        for y in (-5.15, -2.0, 2.0, 5.15):
            mesh.beam((x, y, 0), (x, y, 1.38), .13, "wood", radius_end=.12, sides=10)
            mesh.torus((x, y, 1.19), .135, .022, "steel", segments=10)
    for side in (-1, 1):
        for y in (-4.4, 4.4):
            mesh.beam((side*1.3, y, .84), (side*1.3, y, 1.02), .045, "black")
            mesh.beam((side*1.3, y-.15, 1.03), (side*1.3, y+.15, 1.03), .04, "black")
    # Access ramp, with its low end actually touching the local ground plane.
    mesh.face(((-1.5, 5.2, .82), (1.5, 5.2, .82), (1.5, 6.5, 0), (-1.5, 6.5, 0)), "wood")


def bench(mesh):
    for y in (-.23, -.07, .09, .25):
        mesh.box((0, y, .48), (1.9, .135, .065), "oak")
    for z in (.71, .91, 1.11):
        mesh.box((0, .29, z), (1.9, .065, .145), "oak")
    for x in (-.7, .7):
        for y in (-.2, .2):
            mesh.beam((x, y*1.35, .03), (x, y, .46), .045, "green")
            mesh.box((x, y*1.35, .035), (.16, .17, .07), "green")
        mesh.beam((x, .23, .4), (x, .3, 1.2), .035, "green")
        mesh.beam((x, -.29, .7), (x, .29, .7), .035, "green")
        mesh.beam((x, -.24, .46), (x, -.24, .7), .03, "green")
        for z in (.73, 1.12):
            mesh.beam((x, .24, z), (x, .2, z), .014, "gold", sides=6)
    mesh.beam((-.7, 0, .25), (.7, 0, .25), .03, "green")


def lantern(mesh):
    mesh.box((0, 0, .035), (.28, .28, .07), "black")
    mesh.box((0, 0, .255), (.21, .21, .34), "lamp")
    for x in (-.12, .12):
        for y in (-.12, .12):
            mesh.beam((x, y, .07), (x, y, .44), .013, "black", sides=6)
    for z in (.09, .42):
        mesh.box((0, 0, z), (.29, .29, .026), "black")
    for side in (-1, 1):
        mesh.beam((-.12, side*.126, .1), (.12, side*.126, .42), .007, "black", sides=5)
    corners = [(-.15, -.15, .43), (.15, -.15, .43),
               (.15, .15, .43), (-.15, .15, .43)]
    for i in range(4):
        mesh.face((corners[i], corners[(i+1) % 4], (0, 0, .52)), "black")
    mesh.torus((0, 0, .535), .055, .009, "black", axis="y", segments=16)
    mesh.beam((0, 0, .08), (0, 0, .17), .025, "gold")


def street_lamp(mesh):
    """Grounded roadside iron standard: .64 m square footprint, 4.08 m tall."""
    # Broad stone footing and stepped cast-iron shoe sit on, not above, ground.
    mesh.box((0, 0, .08), (.64, .64, .16), "granite")
    mesh.box((0, 0, .19), (.52, .52, .06), "stone")
    mesh.box((0, 0, .25), (.42, .42, .06), "black")
    mesh.beam((0, 0, .28), (0, 0, .55), .19, "black",
              radius_end=.14, sides=16)
    for x in (-.16, .16):
        for y in (-.16, .16):
            mesh.beam((x, y, .28), (x, y, .30), .022, "steel", sides=6)

    # A substantial tapered mast, with twelve raised longitudinal iron flutes.
    mesh.beam((0, 0, .50), (0, 0, 2.83), .13, "black",
              radius_end=.075, sides=24)
    for i in range(12):
        angle = i * math.tau / 12
        co, si = math.cos(angle), math.sin(angle)
        mesh.beam((.126 * co, .126 * si, .57),
                  (.077 * co, .077 * si, 2.73), .014, "black",
                  radius_end=.009, sides=6)
    for z, radius in ((.52, .145), (.61, .137), (2.71, .092), (2.81, .105)):
        mesh.torus((0, 0, z), radius, .018, "black", segments=24)

    # Four swept corbels visibly carry the wide lantern tray from the mast.
    for i in range(4):
        angle = math.pi / 4 + i * math.pi / 2
        co, si = math.cos(angle), math.sin(angle)
        profile = ((.075, 2.60), (.12, 2.69), (.20, 2.77),
                   (.265, 2.85), (.265, 2.94))
        for (r0, z0), (r1, z1) in zip(profile, profile[1:]):
            mesh.beam((r0 * co, r0 * si, z0),
                      (r1 * co, r1 * si, z1), .023, "black", sides=8)
    mesh.beam((0, 0, 2.79), (0, 0, 2.95), .105, "black",
              radius_end=.15, sides=16)
    mesh.box((0, 0, 2.95), (.54, .54, .06), "black")

    # Tall, outward-flared warm glass panes, not the portable lantern geometry.
    lower = [(-.19, -.19, 2.98), (.19, -.19, 2.98),
             (.19, .19, 2.98), (-.19, .19, 2.98)]
    upper = [(-.25, -.25, 3.65), (.25, -.25, 3.65),
             (.25, .25, 3.65), (-.25, .25, 3.65)]
    mesh.face(list(reversed(lower)), "black")
    mesh.face(upper, "black")
    for i in range(4):
        j = (i + 1) % 4
        mesh.face((lower[i], lower[j], upper[j], upper[i]), "lamp")
        mesh.beam(lower[i], upper[i], .023, "black", sides=8)
        mesh.beam(lower[i], lower[j], .022, "black", sides=8)
        mesh.beam(upper[i], upper[j], .025, "black", sides=8)
        midpoint_low = tuple((lower[i][k] + lower[j][k]) / 2 for k in range(3))
        midpoint_high = tuple((upper[i][k] + upper[j][k]) / 2 for k in range(3))
        mesh.beam(midpoint_low, midpoint_high, .010, "black", sides=6)

    # Overhanging weather cap, raised vent and solid pointed finial; no handle.
    mesh.box((0, 0, 3.68), (.60, .60, .06), "black")
    eaves = [(-.30, -.30, 3.71), (.30, -.30, 3.71),
             (.30, .30, 3.71), (-.30, .30, 3.71)]
    crown = [(-.07, -.07, 3.89), (.07, -.07, 3.89),
             (.07, .07, 3.89), (-.07, .07, 3.89)]
    for i in range(4):
        j = (i + 1) % 4
        mesh.face((eaves[i], eaves[j], crown[j], crown[i]), "black")
    mesh.box((0, 0, 3.91), (.14, .14, .04), "black")
    mesh.torus((0, 0, 3.945), .045, .015, "black", segments=16)
    mesh.beam((0, 0, 3.93), (0, 0, 4.08), .045, "black",
              radius_end=0, sides=12)


def house_table(mesh):
    """Dark oak house row, long axis Y: 2.90 × 30.00 × .86 m, grounded."""
    # Four long planks with visible seams and cross-grain breadboard ends.
    for x in (-.45, -.15, .15, .45):
        for i in range(10):
            y = -14.88 + (i + .5) * 2.976
            mesh.box((x, y, .82), (.296, 2.972, .08), "wood")
    for y in (-14.94, 14.94):
        mesh.box((0, y, .82), (1.20, .12, .08), "wood")
    for x in (-.46, .46):
        mesh.box((x, 0, .71), (.10, 29.40, .14), "wood")

    # Continuous two-plank seats leave generous sitting space beside the table.
    for side in (-1, 1):
        seat_x = side * 1.25
        for offset in (-.096, .096):
            mesh.box((seat_x + offset, 0, .44), (.188, 30, .08), "wood")
        mesh.box((seat_x, 0, .33), (.10, 29.40, .14), "wood")

    # Repeated stout trestles: grounded feet, splayed legs and transverse caps.
    stations = (-14.1, -9.4, -4.7, 0, 4.7, 9.4, 14.1)
    for y in stations:
        mesh.box((0, y, .06), (1.12, .28, .12), "wood")
        mesh.box((0, y, .74), (1.16, .22, .08), "wood")
        for side in (-1, 1):
            mesh.beam((side * .43, y, .12), (side * .31, y, .70),
                      .085, "wood", sides=4)
        mesh.box((0, y, .26), (.84, .14, .12), "wood")
        for side in (-1, 1):
            x = side * 1.25
            mesh.box((x, y, .05), (.40, .25, .10), "wood")
            mesh.box((x, y, .37), (.38, .20, .06), "wood")
            for offset in (-.12, .12):
                mesh.beam((x + offset, y, .10),
                          (x + offset * .55, y, .34), .045, "wood", sides=4)
            # Recessed wooden pegs show seat-to-trestle joinery, not ornaments.
            for offset in (-.096, .096):
                mesh.beam((x + offset, y, .475), (x + offset, y, .48),
                          .012, "oak", sides=8)
        for x in (-.45, .45):
            mesh.beam((x, y, .855), (x, y, .86), .014, "oak", sides=8)

    # Longitudinal stretchers and knee braces tie the trestles into real frames.
    mesh.box((0, 0, .26), (.14, 28.40, .14), "wood")
    for y0, y1 in zip(stations, stations[1:]):
        for y, direction in ((y0, 1), (y1, -1)):
            mesh.beam((0, y, .31), (0, y + direction * .65, .70),
                      .055, "wood", sides=4)
            for side in (-1, 1):
                x = side * 1.25
                mesh.beam((x, y, .13), (x, y + direction * .45, .34),
                          .035, "wood", sides=4)


def luggage(mesh):
    # Domed school trunk, brass corners/straps, leather suitcase on top.
    mesh.box((0, 0, .25), (.9, .55, .5), "leather")
    # Barrel-roof helper is long along Y; use it for a real curved trunk lid.
    barrel_roof(mesh, 0, .9, .55, .5, .12, "leather")
    for x in (-.32, .32):
        mesh.box((x, -.282, .28), (.04, .025, .54), "gold")
        mesh.box((x, .282, .28), (.04, .025, .54), "gold")
        mesh.box((x, 0, .62), (.04, .57, .025), "gold")
        mesh.box((x, -.305, .43), (.085, .025, .12), "gold")
        mesh.box((x, -.321, .43), (.035, .02, .055), "black")
    for x in (-.43, .43):
        for y in (-.26, .26):
            for z in (.045, .48):
                mesh.box((x, y, z), (.09, .07, .09), "gold")
    mesh.beam((-.14, -.31, .26), (.14, -.31, .26), .025, "wood")
    mesh.box((.04, .02, .81), (.61, .38, .36), "wood", yaw=.13)
    for x in (-.18, .25):
        mesh.box((x, -.19, .81), (.045, .025, .35), "leather")
    mesh.torus((.04, .02, 1.025), .07, .015, "leather", axis="y", segments=12)
    mesh.box((.08, -.229, .82), (.15, .018, .1), "cream")
    mesh.text("HOGWARTS", (.08, -.241, .82), .022, "black")


def signpost(mesh):
    mesh.beam((0, 0, 0), (0, 0, 2.75), .09, "wood", radius_end=.065, sides=10)
    mesh.ellipsoid((0, 0, 2.8), (.12, .12, .12), "wood", segments=10, rings=5)
    for words, z, direction in (("HOGWARTS", 2.45, 1), ("HOGSMEADE", 1.94, -1), ("BOOTSHAUS", 1.43, 1)):
        x = direction*.25
        left, right = x-.95, x+.95
        outline = [(left, z-.18), (right, z-.18), (right+.23, z), (right, z+.18), (left, z+.18)]
        if direction < 0:
            outline = [(-px+2*x, zz) for px, zz in outline]
        mesh.face([(px, -.1, zz) for px, zz in reversed(outline)], "green")
        mesh.face([(px, .035, zz) for px, zz in outline], "green")
        for i in range(len(outline)):
            a, b = outline[i], outline[(i+1) % len(outline)]
            mesh.face(((a[0], -.1, a[1]), (b[0], -.1, b[1]), (b[0], .035, b[1]), (a[0], .035, a[1])), "wood")
        mesh.text(words, (x, -.112, z), .235)
        for xx in (-.06, .06):
            mesh.beam((xx, -.115, z), (xx, -.13, z), .017, "gold", sides=8)
    for angle in range(5):
        a = angle * math.tau / 5
        mesh.beam((0, 0, .3), (.26*math.cos(a), .26*math.sin(a), .025), .035, "wood")


def pine(mesh):
    rng = random.Random(117)
    # Irregular trunk and roots; every foliage cluster has a supporting branch.
    path = [(0, 0, 0), (.08, -.04, 3), (-.07, .04, 6), (.12, .05, 9.3), (.02, 0, 12.8)]
    for i in range(len(path)-1):
        mesh.beam(path[i], path[i+1], .24*(1-i*.22), "bark", radius_end=.24*(1-(i+1)*.22), sides=11)
    for i in range(7):
        a = i * math.tau / 7
        mesh.beam((0, 0, .45), (.85*math.cos(a), .85*math.sin(a), .02), .1, "bark", radius_end=.025)
    cluster = 0
    for tier in range(8):
        h = 3.1 + tier*1.12
        reach = 2.75 - tier*.29
        for branch in range(5):
            a = branch * math.tau / 5 + tier*.63 + rng.uniform(-.15, .15)
            end = (math.cos(a)*reach, math.sin(a)*reach, h+.3)
            fork = (end[0]*.55, end[1]*.55, h+.12)
            mesh.beam((0, 0, h), fork, .065, "bark", radius_end=.038, sides=7)
            mesh.beam(fork, end, .038, "bark", radius_end=.008, sides=6)
            for t in (.56, .94):
                center = (end[0]*t, end[1]*t, h+.35+t*.2)
                mesh.ellipsoid(center, (.68+(1-t)*.2, .64, .48), "pine", segments=9, rings=5, seed=cluster)
                cluster += 1
    mesh.ellipsoid((.02, 0, 12.15), (.49, .45, .93), "pine", segments=10, rings=6, seed=915)


def broadleaf(mesh):
    rng = random.Random(219)
    trunk = [(0, 0, 0), (.1, .08, 2.9), (-.18, .1, 5.0), (.25, .15, 7.2), (.35, .1, 10.8)]
    for i in range(len(trunk)-1):
        mesh.beam(trunk[i], trunk[i+1], .43-i*.09, "bark", radius_end=.34-i*.08, sides=12)
    for i in range(8):
        a = i * math.tau / 8
        mesh.beam((0, 0, .7), (1.35*math.cos(a), 1.35*math.sin(a), .03), .16, "bark", radius_end=.035)
    for i in range(12):
        a = i * 2.39996
        height = 4.1 + i*.46
        reach = 3.35 if i < 7 else 2.7
        elbow = (math.cos(a)*reach*.56, math.sin(a)*reach*.56, height+1.25)
        end = (math.cos(a)*reach, math.sin(a)*reach, height+2.1)
        mesh.beam((0, .1, height), elbow, .18-i*.008, "bark", radius_end=.075, sides=9)
        mesh.beam(elbow, end, .075, "bark", radius_end=.018, sides=7)
        for branch in range(3):
            aa = a+(branch-1)*.6
            tip = (end[0]+math.cos(aa)*.7, end[1]+math.sin(aa)*.7, end[2]+rng.uniform(.3, 1))
            mesh.beam(elbow, tip, .035, "bark", radius_end=.008, sides=6)
            mesh.ellipsoid(tip, (1.35, 1.22, 1.25), "leaf-light" if (i+branch) % 4 == 0 else "leaf",
                           segments=10, rings=6, seed=i*3+branch)
    mesh.ellipsoid((.2, .1, 11), (1.5, 1.5, 1.4), "leaf", segments=11, rings=7, seed=918)


def stone_gate(mesh):
    # Walk-through arch with individually cut voussoirs and open central span.
    opening = 4.2
    for x in (-3.15, 3.15):
        mesh.box((x, 0, 2.2), (1.5, 1.6, 4.4), "granite")
        mesh.box((x, 0, .16), (1.8, 1.9, .32), "granite")
        mesh.box((x, 0, 4.25), (1.9, 1.95, .3), "stone")
        mesh.gable((x, 0, 0), 1.95, 1.95, 4.45, .72, "slate")
        mesh.ellipsoid((x, 0, 5.33), (.23, .23, .28), "granite", segments=10, rings=5)
    inner, outer, spring = opening/2, opening/2+.48, 3.0
    for i in range(17):
        a, b = i*math.pi/17+.006, (i+1)*math.pi/17-.006
        section = [(inner*math.cos(a), spring+inner*math.sin(a)),
                   (outer*math.cos(a), spring+outer*math.sin(a)),
                   (outer*math.cos(b), spring+outer*math.sin(b)),
                   (inner*math.cos(b), spring+inner*math.sin(b))]
        mesh.face([(x, -.6, z) for x, z in section], "stone")
        mesh.face([(x, .6, z) for x, z in reversed(section)], "granite")
        for j in range(4):
            p, q = section[j], section[(j+1) % 4]
            mesh.face(((p[0], -.6, p[1]), (q[0], -.6, q[1]), (q[0], .6, q[1]), (p[0], .6, p[1])), "granite")
    for side in (-1, 1):
        mesh.box((side*2.35, 0, 1.5), (.5, 1.2, 3), "stone")
        mesh.box((side*5.2, .1, 1), (2.8, .9, 2), "granite")
        mesh.box((side*5.2, .1, 2.02), (2.95, 1.05, .15), "stone")
        # Open iron gate leaves lie along the wall, never block the entry.
        for i in range(8):
            x = side*(3.7+i*.32)
            mesh.beam((x, -.55, .25), (x, -.55, 2.6), .025, "black", sides=6)
            mesh.beam((x, -.55, 2.6), (x, -.55, 2.75), .055, "black", radius_end=0, sides=4)
        for z in (.5, 2.3):
            mesh.beam((side*3.7, -.55, z), (side*5.94, -.55, z), .035, "black")
    mesh.box((0, -.69, 5.32), (2.7, .16, .43), "green")
    mesh.text("HOGWARTS", (0, -.79, 5.32), .3, "gold")


BUILDERS = {
    "station": (station, "building", "Goathland-inspirierter Bahnhof Hogsmeade aus Sandstein mit Giebeln, grünem Bahnsteigdach, Fahrkartentüren und lesbaren Schildern."),
    "hogwarts-express": (train, "prop", "Stationärer karminroter Hogwarts Express: Dampflokomotive 5972, offener Kohletender und zwei Reisezugwagen; Längsachse lokales glTF-Z, kein Fahrmechanismus."),
    "boathouse": (boathouse, "building", "Steinernes Bootshaus am Schwarzen See, Schieferdach, offenstehende Holztore und zwei echte offene Einfahrten zur Wasserseite."),
    "rowboat": (rowboat, "prop", "Offenes hölzernes Klinker-Ruderboot mit Rippen, Sitzbänken, Dollborden und verstauten Rudern; dekorativ, ohne Fahrmechanik."),
    "jetty": (jetty, "prop", "Drei Meter breiter Holzsteg mit einzeln modellierten Planken, Pfählen, Beschlägen und abgesenkter Landrampe."),
    "bench": (bench, "prop", "Eichenholzbank mit vier Sitzlatten, Rückenlehne, grünen Metallfüßen und Armstützen."),
    "lantern": (lantern, "prop", "Kleine tragbare Laterne mit warmen Scheiben, schwarzem Metallrahmen, Pyramidenhaube und Tragering; ohne exportierte Lichtquelle."),
    "street-lamp": (street_lamp, "prop", "Bodenständige 4,08 Meter hohe Straßenlaterne mit steinernem Sockel, kanneliertem Eisenmast, vier Tragkonsolen, warmen Glasscheiben und spitzer Wetterhaube; ohne exportierte Lichtquelle."),
    "house-table": (house_table, "prop", "30 Meter lange dunkle Eichentafel mit vier Plankenbahnen, Hirnleisten, kräftigen Böcken, Streben und zwei durchgehenden Sitzbänken; Längsachse lokales glTF-Z."),
    "luggage": (luggage, "prop", "Schulkoffer mit gewölbtem Lederdeckel, Messingbeschlägen und aufgesetztem Reisekoffer mit Hogwarts-Etikett."),
    "signpost": (signpost, "prop", "Hölzerner Wegweiser mit lesbaren grünen Pfeilschildern Hogwarts, Hogsmeade und Bootshaus."),
    "pine": (pine, "prop", "Schottische Waldkiefer mit verzweigtem Stamm, Wurzelanläufen und vielen räumlichen Nadelkronen statt flacher Pyramiden."),
    "broadleaf": (broadleaf, "prop", "Unregelmäßiger Laubbaum mit sichtbaren Wurzelanläufen, Astgabeln, kleinen Zweigen und organisch gegliederter grüner Krone."),
    "stone-gate": (stone_gate, "prop", "Begehbares steinernes Schlosstor mit echtem Rundbogendurchgang, einzelnen Bogensteinen, Pfeilern und seitlich geöffneten Eisenflügeln."),
}


def export_asset(bpy, name, builder, materials, output):
    from mathutils import Vector
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    mesh = Mesh(name, materials)
    builder(mesh)
    objects = mesh.object(bpy)
    bpy.context.view_layer.update()
    points = [obj.matrix_world @ Vector(corner) for obj in objects for corner in obj.bound_box]
    lo = [min(p[k] for p in points) for k in range(3)]
    hi = [max(p[k] for p in points) for k in range(3)]
    # Centre width/depth and put the exact lowest modeled point at ground zero.
    offset = Vector((-(lo[0]+hi[0])/2, -(lo[1]+hi[1])/2, -lo[2]))
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.location += offset
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    # One unrigged mesh/object and material primitives keep draw calls bounded.
    bpy.ops.object.join()
    root = bpy.context.view_layer.objects.active
    bpy.context.scene.cursor.location = (0, 0, 0)
    bpy.ops.object.origin_set(type="ORIGIN_CURSOR")
    bpy.context.view_layer.update()
    bpy.ops.export_scene.gltf(
        filepath=str(output / (name + ".glb")), export_format="GLB",
        use_selection=True, export_yup=True, export_texcoords=True,
        export_normals=True, export_materials="EXPORT", export_image_format="AUTO",
        export_animations=False, export_skins=False, export_morph=False,
        export_cameras=False, export_lights=False,
        export_extras=False, export_apply=True,
    )
    return {
        "file": name + ".glb",
        "width_m": round(hi[0]-lo[0], 6),
        "depth_m": round(hi[1]-lo[1], 6),
        "height_m": round(hi[2]-lo[2], 6),
        "kind": BUILDERS[name][1],
        "description": BUILDERS[name][2],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    import bpy
    if bpy.app.version < (4, 2, 0):
        raise RuntimeError("Blender 4.2 or newer is required")
    output = args.output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    bpy.context.scene.unit_settings.system = "METRIC"
    bpy.context.scene.unit_settings.scale_length = 1
    # Packed images remain resident for all twelve independent GLB exports.
    with tempfile.TemporaryDirectory(prefix="original-hogwarts-arrival-") as temp:
        materials = make_materials(bpy, Path(temp))
        assets = {}
        for name, (builder, _kind, _description) in BUILDERS.items():
            assets[name] = export_asset(bpy, name, builder, materials, output)
    manifest = {"assets": assets, "provenance": PROVENANCE}
    (output / "arrival-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:])
