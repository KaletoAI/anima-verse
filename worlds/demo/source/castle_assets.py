#!/usr/bin/env python3
"""Self-authored Hogwarts exterior and Hagrid cottage, for Blender 4.2 LTS.

Run: tools/blender -b --python castle_assets.py -- --output DIRECTORY
No network, external assets, add-ons, .blend saves, or import-time scene changes.

Copyright (c) 2026 the Anima Verse demo contributors. Geometry, pixel textures,
and this generator are original procedural work. Hogwarts and Hagrid are fictional
references: this is an unofficial fan depiction, not a licensed commercial asset,
not an architectural survey, and not extracted film/game geometry or imagery.

Coordinates inside Blender are metres, Z-up, +Y north. Exported glTF is Y-up,
so world (x, y-up, z-south) = Blender (x, z-up, -y). The castle's open quad and
south entrance are actual empty space, not a solid pedestal disguised by paint.
The four authored rooms share their footprints and openings with build_world.py.
Their textured masonry shells contain real revealed openings and separate glazing.
"""

import argparse
import json
import math
from pathlib import Path
import struct
import sys
import tempfile
import zlib


PROVENANCE = (
    "Self-authored procedural Blender geometry/textures; film reference only; "
    "no extracted/downloaded assets. Unofficial fictional fan depiction, "
    "not licensed commercial assets."
)

# Single source for native rooms and the persistent facade, in exported x/z metres.
# Edge order follows [[0,0],[w,0],[w,d],[0,d]]; all opening heights use the 3m
# world datum as their zero, not an extra per-room floor offset.
CASTLE_ROOMS = {
    "Eingangshalle": {
        "rect": (40, -65, 14, 20.2), "wall_top": 24,
        "openings": [
            (2, .5, 3, 3.5, 0, "door", "outside"),
            (3, 1 - 9 / 20.2, 3, 3.5, 0, "door", "Verbindungsgalerie"),
            (0, .5, 2.4, 5.6, 3, "window", "outside"),
            (1, .25, 2.4, 5.6, 3, "window", "outside"),
            (1, .75, 2.4, 5.6, 3, "window", "outside"),
        ],
    },
    "Verbindungsgalerie": {
        "rect": (-40, -65, 80, 18), "wall_top": 24,
        "openings": [
            (1, .5, 3, 3.5, 0, "door", "Eingangshalle"),
            (2, 1 - 8 / 80, 3, 3.5, 0, "door", "Turmhalle"),
            *[(0, at, 2.4, 5.6, 3, "window", "outside")
              for at in (.15, .325, .5, .675, .85)],
            *[(2, at, 2.4, 5.6, 3, "window", "outside")
              for at in (.25, .425, .6, .775)],
            (3, .5, 2.4, 5.6, 3, "window", "outside"),
        ],
    },
    "Turmhalle": {
        "rect": (-40, -47, 16, 35), "wall_top": 24,
        "openings": [
            (0, .5, 3, 3.5, 0, "door", "Verbindungsgalerie"),
            (2, .75, 3, 3.5, 0, "door", "Große Halle"),
            *[(edge, at, 2.4, 5.6, 3, "window", "outside")
              for edge in (1, 3) for at in (.3, .7)],
        ],
    },
    "Große Halle": {
        "rect": (-64, -12, 30, 64), "wall_top": 24,
        "openings": [
            (0, 28 / 30, 3, 3.5, 0, "door", "Turmhalle"),
            *[(1, (z + 12) / 64, 3.2, 10, 10.8, "window", "outside")
              for z in (-1, 8, 17, 26, 35, 44)],
            *[(3, (52 - z) / 64, 3.2, 10, 10.8, "window", "outside")
              for z in (-1, 8, 17, 26, 35, 44)],
        ],
    },
}


def castle_room_openings(name, resolve_room):
    """Native authoring payload; reciprocal doors and facade windows never drift."""
    return [
        {"edge": edge, "at": at, "width_m": width, "height_m": height,
         "sill_m": sill, "type": kind,
         "to": target if target == "outside" else resolve_room(target)}
        for edge, at, width, height, sill, kind, target in CASTLE_ROOMS[name]["openings"]
    ]


def write_texture(path, kind, size=256, tint=(1, 1, 1)):
    """Write deterministic original RGB PNGs using only Python's standard library."""
    pixels = bytearray()
    for y in range(size):
        pixels.append(0)  # PNG unfiltered scanline
        for x in range(size):
            noise = ((x * 374761393 + y * 668265263) ^ (x * y * 1274126177)) & 0xFFFFFFFF
            grain = (noise % 19) - 9
            if kind == "stone":
                course = y // 32
                xx = (x + (32 if course % 2 else 0)) % 64
                block = ((x + (32 if course % 2 else 0)) // 64 + course * 7) % 11
                mortar = y % 32 < 2 or xx < 2
                base = (87, 82, 70) if mortar else (163 + block * 2, 151 + block * 2, 126 + block)
                grain += -19 if noise % 137 == 0 else 0
            elif kind == "slate":
                row = y // 32
                xx = (x + (16 if row % 2 else 0)) % 32
                tile = ((x + row * 16) // 32 + row * 3) % 7
                seam = y % 32 < 2 or xx < 1
                base = (21, 29, 32) if seam else (48 + tile * 2, 62 + tile * 2, 68 + tile * 3)
                grain = grain // 2 + (3 if y % 32 == 3 else 0)
            elif kind == "wood":
                seam = x % 43 < 2
                wave = math.sin(x * 0.31 + math.sin(y * 0.04) * 0.9)
                knot = math.sin(math.hypot((x % 85) - 35, (y % 128 - 56) * 0.4) * 0.75)
                base = (42, 29, 19) if seam else (97 + int(wave * 10 + knot * 4), 66 + int(wave * 7), 39)
                grain //= 3
            else:  # opaque leaded glass, suitable for a distant exterior
                lead = (x + y) % 64 < 3 or (x - y) % 64 < 3
                pane = ((x + y) // 64 + (x - y) // 64) % 4
                base = (29, 34, 34) if lead else ((115, 106, 72) if pane == 0 else (64, 80, 77))
                grain //= 4
            pixels.extend(max(0, min(255, int((c + grain) * t))) for c, t in zip(base, tint))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes(pixels), 9))
        + chunk(b"IEND", b"")
    )


class Geometry:
    """Accumulate by material: few draw calls, no thousands of Blender operators."""

    def __init__(self, bpy, materials):
        self.bpy = bpy
        self.materials = materials
        self.parts = {name: [[], [], []] for name in materials}
        self.interior_cutout_padding_m = 0
        self.lod_preserve_materials = ()

    def mesh(self, material, vertices, faces, uv_faces=None):
        verts, polys, coords = self.parts[material]
        offset = len(verts)
        verts.extend(vertices)
        scale = 4.0 if material in ("stone", "trim", "paving") else 2.5
        for face_index, face in enumerate(faces):
            polys.append(tuple(offset + index for index in face))
            if uv_faces is not None:
                coords.append(uv_faces[face_index])
                continue
            # Face-local orthonormal projection gives metre-consistent, unstretched UVs.
            from mathutils import Vector
            origin = Vector(vertices[face[0]])
            u = Vector(vertices[face[1]]) - origin
            if u.length < 1e-8:
                u = Vector((1, 0, 0))
            u.normalize()
            normal = Vector((0, 0, 1))
            for index in face[2:]:
                candidate = u.cross(Vector(vertices[index]) - origin)
                if candidate.length > 1e-8:
                    normal = candidate.normalized()
                    break
            v = normal.cross(u)
            coords.append([((Vector(vertices[index]) - origin).dot(u) / scale,
                            (Vector(vertices[index]) - origin).dot(v) / scale) for index in face])

    def box(self, material, center, size, angle=0):
        cx, cy, cz = center
        sx, sy, sz = (n / 2 for n in size)
        cosine, sine = math.cos(angle), math.sin(angle)
        vertices = []
        for x, y, z in ((-sx, -sy, -sz), (sx, -sy, -sz), (sx, sy, -sz), (-sx, sy, -sz),
                        (-sx, -sy, sz), (sx, -sy, sz), (sx, sy, sz), (-sx, sy, sz)):
            vertices.append((cx + x * cosine - y * sine, cy + x * sine + y * cosine, cz + z))
        self.mesh(material, vertices, [(3, 2, 1, 0), (0, 1, 5, 4), (1, 2, 6, 5),
                                       (2, 3, 7, 6), (3, 0, 4, 7), (4, 5, 6, 7)])

    def cylinder(self, material, x, y, bottom, top, radius, top_radius=None, sides=32,
                 angle=0, y_scale=1.0):
        upper = radius if top_radius is None else top_radius
        vertices = []
        for z, r in ((bottom, radius), (top, upper)):
            vertices.extend((x + r * math.cos(angle + i * math.tau / sides),
                             y + r * math.sin(angle + i * math.tau / sides) * y_scale, z)
                            for i in range(sides))
        faces = [tuple(reversed(range(sides))), tuple(range(sides, sides * 2))]
        uv = [[(vertices[i][0] / 4, vertices[i][1] / 4) for i in face] for face in faces]
        slant = math.hypot(top - bottom, radius - upper)
        for i in range(sides):
            j = (i + 1) % sides
            faces.append((i, j, j + sides, i + sides))
            u0, u1 = i / sides * math.tau * radius / 4, (i + 1) / sides * math.tau * radius / 4
            uv.append([(u0, 0), (u1, 0), (u1, slant / 4), (u0, slant / 4)])
        self.mesh(material, vertices, faces, uv)

    def beam(self, material, start, end, width, depth=None):
        from mathutils import Vector
        a, b = Vector(start), Vector(end)
        direction = b - a
        if direction.length < 1e-7:
            return
        rotation = direction.to_track_quat("Z", "Y")
        half_w, half_d = width / 2, (width if depth is None else depth) / 2
        vertices = []
        for z in (0, direction.length):
            for x, y in ((-half_w, -half_d), (half_w, -half_d), (half_w, half_d), (-half_w, half_d)):
                vertices.append(tuple(a + rotation @ Vector((x, y, z))))
        self.mesh(material, vertices, [(3, 2, 1, 0), (0, 1, 5, 4), (1, 2, 6, 5),
                                       (2, 3, 7, 6), (3, 0, 4, 7), (4, 5, 6, 7)])

    def roof(self, x, y, width, length, eave, ridge, angle=0):
        # Long ridge along local Y; solid gable ends and slate planes.
        cosine, sine = math.cos(angle), math.sin(angle)
        def point(a, b, z):
            return (x + a * cosine - b * sine, y + a * sine + b * cosine, z)
        w, l = width / 2, length / 2
        vertices = [point(-w, -l, eave), point(w, -l, eave), point(w, l, eave),
                    point(-w, l, eave), point(0, -l, ridge), point(0, l, ridge)]
        self.mesh("slate", vertices, [(0, 4, 5, 3), (4, 1, 2, 5)])
        self.mesh("stone", vertices, [(0, 1, 4), (2, 3, 5)])
        self.beam("metal", point(0, -l, ridge + 0.06), point(0, l, ridge + 0.06), 0.18)
        for side in (-1, 1):
            self.beam("trim", point(side * w, -l, eave), point(side * w, l, eave), 0.28)

    def emit(self, label):
        bpy = self.bpy
        objects = []
        for material, (vertices, faces, uv_faces) in self.parts.items():
            if not vertices:
                continue
            mesh = bpy.data.meshes.new(f"{label}-{material}-mesh")
            mesh.from_pydata(vertices, [], faces)
            mesh.materials.append(self.materials[material])
            mesh.update()
            uv = mesh.uv_layers.new(name="AuthoredUV")
            for polygon, face_uv in zip(mesh.polygons, uv_faces):
                for loop_index, coordinate in zip(polygon.loop_indices, face_uv):
                    uv.data[loop_index].uv = coordinate
            obj = bpy.data.objects.new(f"{label}-{material}", mesh)
            bpy.context.collection.objects.link(obj)
            obj["provenance"] = PROVENANCE
            if self.interior_cutout_padding_m:
                obj["interior_cutout_padding_m"] = self.interior_cutout_padding_m
            if material in self.lod_preserve_materials:
                obj["lod_preserve"] = True
            objects.append(obj)
        return objects


def arch_outline(width, height, spring, segments=10):
    """Pointed two-centre Gothic arch, counterclockwise in a facade's u/z plane."""
    a, rise = width / 2, height - spring
    centre = (rise * rise - a * a) / (2 * a)
    radius = centre + a
    end_angle = math.atan2(rise, -centre)
    points = [(-a, 0), (a, 0)]
    right = []
    for i in range(segments + 1):
        theta = math.pi + (end_angle - math.pi) * i / segments
        left_x = centre + radius * math.cos(theta)
        right.append((-left_x, spring + radius * math.sin(theta)))
    points.extend(right)
    points.extend((-u, z) for u, z in reversed(right[:-1]))
    return points


def facade_point(x, y, normal, u, z, offset=0):
    nx, ny = normal
    return (x - ny * u + nx * offset, y + nx * u + ny * offset, z)


def window(g, x, y, bottom, width, height, normal, door=False):
    """Raised stone voussoirs, recessed dark pane, mullions and Gothic outline."""
    spring = height * 0.62
    inner = arch_outline(width, height, spring)
    thickness = max(0.14, width * 0.10)
    outer = [(u, z - thickness) for u, z in arch_outline(width + thickness * 2,
                                                        height + thickness * 2,
                                                        spring + thickness)]
    vertices = [facade_point(x, y, normal, u, bottom + z, 0.07) for u, z in inner]
    g.mesh("wood" if door else "glass", vertices, [tuple(range(len(vertices)))],
           [[((u + width / 2) / 2, z / 2) for u, z in inner]])
    ring = ([facade_point(x, y, normal, u, bottom + z, 0.19) for u, z in inner]
            + [facade_point(x, y, normal, u, max(0.0, bottom + z), 0.19) for u, z in outer])
    n = len(inner)
    g.mesh("trim", ring, [(i, (i + 1) % n, (i + 1) % n + n, i + n) for i in range(n)])
    p = lambda u, z: facade_point(x, y, normal, u, bottom + z, 0.22)
    g.beam("metal" if door else "trim", p(0, 0), p(0, height - 0.25), max(0.07, width * 0.035))
    for z in ((height * 0.35, height * 0.65) if not door else (height * 0.2, height * 0.55)):
        g.beam("metal" if door else "trim", p(-width / 2 + 0.08, z), p(width / 2 - 0.08, z), 0.08)
    if width > 3 and not door:
        for u in (-width / 4, width / 4):
            g.beam("trim", p(u, 0), p(u, height * 0.84), 0.12)


def room_edge(rect, edge):
    """Blender edge origin, unit tangent, outward normal and length."""
    x, z, width, depth = rect
    corners = ((x, -z), (x + width, -z), (x + width, -z - depth), (x, -z - depth))
    a, b = corners[edge], corners[(edge + 1) % 4]
    length = math.dist(a, b)
    tangent = ((b[0] - a[0]) / length, (b[1] - a[1]) / length)
    return a, tangent, (-tangent[1], tangent[0]), length


def shared_wall_spans(rect, edge, earlier_rooms):
    """Keep one owner for each shared wall, including partially touching edges."""
    origin, tangent, _, length = room_edge(rect, edge)
    spans = []
    for other in earlier_rooms:
        for other_edge in range(4):
            start, direction, _, span = room_edge(other["rect"], other_edge)
            if abs(tangent[0] * direction[0] + tangent[1] * direction[1] + 1) > 1e-7:
                continue
            delta = (start[0] - origin[0], start[1] - origin[1])
            if abs(delta[0] * tangent[1] - delta[1] * tangent[0]) > 1e-7:
                continue
            end = (start[0] + direction[0] * span - origin[0],
                   start[1] + direction[1] * span - origin[1])
            lo, hi = sorted((delta[0] * tangent[0] + delta[1] * tangent[1],
                             end[0] * tangent[0] + end[1] * tangent[1]))
            if min(length, hi) - max(0, lo) > 1e-7:
                spans.append((max(0, lo), min(length, hi)))
    return spans


def revealed_window(g, center, normal, width, height, sill, depth):
    """Transparent pane inside a real rectangular aperture, with dressed reveals."""
    x, y = center
    p = lambda u, h, offset=0: facade_point(x, y, normal, u, sill + h, offset)
    pane = [p(-width / 2, 0), p(width / 2, 0),
            p(width / 2, height), p(-width / 2, height)]
    g.mesh("room-glass", pane, [(0, 1, 2, 3)],
           [[(0, 0), (width / 2, 0), (width / 2, height / 2), (0, height / 2)]])
    # Frames sit OUTSIDE the nominal aperture; no sill or cornice crosses a door.
    tangent = (-normal[1], normal[0])
    angle = math.atan2(tangent[1], tangent[0])
    for u in (-width / 2 - .10, width / 2 + .10):
        q = p(u, height / 2)
        g.box("trim", q, (.20, depth + .12, height + .4), angle)
    for h in (-.10, height + .10):
        g.box("trim", p(0, h), (width, depth + .12, .20), angle)
    # Fine lead and a pointed stone tracery arch, not an opaque infill panel.
    for offset in (-depth / 2 - .04, depth / 2 + .04):
        g.beam("metal", p(0, 0, offset), p(0, height, offset), .065)
        g.beam("metal", p(-width / 2, height * .55, offset),
               p(width / 2, height * .55, offset), .065)
        curve = arch_outline(width - .18, height - .12, height * .62)[2:]
        for a, b in zip(curve, curve[1:]):
            g.beam("trim", p(*a, offset), p(*b, offset), .10)


def room_envelopes(g):
    """Perforated, metre-UV masonry; no boolean operators or backing solid boxes."""
    depth = .60
    earlier = []
    for room in CASTLE_ROOMS.values():
        rect, top = room["rect"], room["wall_top"]
        # A thin ceiling closes the inhabited volume under the overhanging roofs;
        # the decorative roof pitch alone would leave a gap over the wall heads.
        x, z, width, length = rect
        g.box("stone", (x + width / 2, -z - length / 2, top + .15),
              (width + depth, length + depth, .30))
        for edge in range(4):
            origin, tangent, normal, length = room_edge(rect, edge)
            shared = shared_wall_spans(rect, edge, earlier)
            openings = [(at * length - width / 2, at * length + width / 2,
                         sill, sill + height, kind)
                        for e, at, width, height, sill, kind, _ in room["openings"] if e == edge]
            horizontal = sorted({0, length, *(u for lo, hi in shared for u in (lo, hi)),
                                 *(u for lo, hi, _, _, _ in openings for u in (lo, hi))})
            vertical = sorted({0, top, *(h for _, _, low, high, _ in openings for h in (low, high))})
            angle = math.atan2(tangent[1], tangent[0])
            for lo, hi in zip(horizontal, horizontal[1:]):
                mid = (lo + hi) / 2
                if any(a < mid < b for a, b in shared):
                    continue
                for low, high in zip(vertical, vertical[1:]):
                    h = (low + high) / 2
                    if any(a < mid < b and c < h < d for a, b, c, d, _ in openings):
                        continue
                    center = (origin[0] + tangent[0] * mid,
                              origin[1] + tangent[1] * mid, h)
                    g.box("stone", center, (hi - lo, depth, high - low), angle)
            for lo, hi, low, high, kind in openings:
                mid = (lo + hi) / 2
                if kind != "window" or any(a < mid < b for a, b in shared):
                    continue
                center = (origin[0] + tangent[0] * mid, origin[1] + tangent[1] * mid)
                revealed_window(g, center, normal, hi - lo, high - low, low, depth)
        earlier.append(room)


def arcade(g, start, end, z=0, opening=5.0, spring=3.2, rise=3.2, top=7.0, depth=1.0):
    """True open arch: only piers and spandrels, no hidden face across passage."""
    from mathutils import Vector
    a, b = Vector((start[0], start[1], 0)), Vector((end[0], end[1], 0))
    tangent = (b - a).normalized()
    normal = Vector((-tangent.y, tangent.x, 0))
    center = (a + b) / 2
    span = (b - a).length
    pier = max(0.3, (span - opening) / 2)
    angle = math.atan2(tangent.y, tangent.x)
    for sign in (-1, 1):
        p = center + tangent * sign * (span / 2 - pier / 2)
        g.box("stone", (p.x, p.y, z + top / 2), (pier, depth, top), angle)
        g.box("trim", (p.x, p.y, z + 0.18), (pier + 0.22, depth + 0.22, 0.36), angle)
        g.box("trim", (p.x, p.y, z + spring - 0.10), (pier + 0.18, depth + 0.18, 0.22), angle)
    # Arch outline's upper perimeter, ordered from right spring over apex to left.
    curve = arch_outline(opening, spring + rise, spring)[2:]
    def point(u, v, h):
        p = center + tangent * u + normal * v
        return (p.x, p.y, z + h)
    for (u1, h1), (u2, h2) in zip(curve, curve[1:]):
        vertices = [point(u1, -depth / 2, h1), point(u2, -depth / 2, h2),
                    point(u2, -depth / 2, top), point(u1, -depth / 2, top),
                    point(u1, depth / 2, h1), point(u2, depth / 2, h2),
                    point(u2, depth / 2, top), point(u1, depth / 2, top)]
        g.mesh("stone", vertices, [(0, 1, 2, 3), (7, 6, 5, 4), (0, 4, 5, 1), (3, 2, 6, 7)])
        # Thin lighter dressed-stone ribs make the arch legible from the court.
        for v in (-depth / 2 - 0.05, depth / 2 + 0.05):
            g.beam("trim", point(u1, v, h1 + 0.1), point(u2, v, h2 + 0.1), 0.20)


def tower(g, x, y, radius, wall_top, peak, sides=32, satellites=0, windows=True, bottom=0):
    g.cylinder("stone", x, y, bottom, wall_top,
               radius * (1 - .06 * bottom / wall_top), radius * .94, sides)
    for z, r, h in ((0.35, radius + 0.45, 0.7), (wall_top * 0.36, radius * 0.99 + 0.14, 0.42),
                    (wall_top * 0.70, radius * 0.97 + 0.12, 0.45), (wall_top - 0.55, radius * 0.95 + 0.4, 0.65)):
        if z - h / 2 >= bottom:
            g.cylinder("trim", x, y, z - h / 2, z + h / 2, r, sides=sides)
    eave_radius = radius * 1.04
    g.cylinder("slate", x, y, wall_top, peak - 0.8, eave_radius, 0.16, sides)
    # Layered lead collars and delicate needle, without geometry-heavy shingle instances.
    for fraction in (0.12, 0.52):
        z = wall_top + (peak - wall_top - 0.8) * fraction
        r = eave_radius * (1 - fraction) + 0.16 * fraction
        g.cylinder("metal", x, y, z, z + 0.18, r + 0.05, r, sides)
    g.cylinder("metal", x, y, peak - 0.8, peak, 0.14, 0.025, 8)
    if windows:
        # Align panes to the actual faceted shaft, not a tangent outside its corners.
        for z in (wall_top * 0.20, wall_top * 0.45, wall_top * 0.72):
            if z < bottom:
                continue
            for i in range(0, sides, max(1, sides // 8)):
                theta = (i + 0.5) * math.tau / sides
                t = (z + 2) / wall_top
                r = radius * (1 - 0.06 * t) * math.cos(math.pi / sides)
                nx, ny = math.cos(theta), math.sin(theta)
                window(g, x + r * nx, y + r * ny, z, min(radius * 0.29, 2.1),
                       min(6.0, wall_top * 0.14), (nx, ny))
    for i in range(satellites):
        theta = math.tau * i / satellites + 0.4
        sx, sy = x + radius * 0.85 * math.cos(theta), y + radius * 0.85 * math.sin(theta)
        r = radius * 0.20
        base = wall_top * 0.68
        g.cylinder("stone", sx, sy, base, wall_top + 3.0, r, sides=16)
        g.cylinder("slate", sx, sy, wall_top + 3.0, wall_top + (peak - wall_top) * 0.68,
                   r * 1.2, 0.06, 16)


def hall(g):
    # Tall, narrow Great Hall, with an eastern aisle and exceptionally steep nave roof.
    room = CASTLE_ROOMS["Große Halle"]
    left, north, width, length = room["rect"]
    x, y, wall = left + width / 2, -north - length / 2, room["wall_top"]
    g.roof(x, y, width + 2, length + 2, wall, 43)
    for sign in (-1, 1):
        surface_x = x + sign * width / 2
        for yy in range(-44, 9, 9):
            bx = surface_x + sign * 1.1
            g.box("stone", (bx, yy + 4.1, 9.5), (2.2, 1.5, 19))
            g.mesh("trim", [(bx - 1.1, yy + 3.3, 19), (bx + 1.1, yy + 3.3, 19),
                            (bx + sign * 0.6, yy + 3.3, 23), (bx - 1.1, yy + 4.9, 19),
                            (bx + 1.1, yy + 4.9, 19), (bx + sign * 0.6, yy + 4.9, 23)],
                   [(0, 1, 2), (5, 4, 3), (0, 3, 4, 1), (1, 4, 5, 2), (2, 5, 3, 0)])
        # Stone crest pinnacles along the eaves.
        for yy in (-49, -31, -13, 5):
            g.cylinder("trim", surface_x, yy, 23.5, 26.5, 0.42, 0.13, 8)
    # Open side aisle retains the stepped roof without backing the hall's glazing.
    g.roof(-70, -20, 11, 60, 6, 10)
    for yy in (-48, -35.5, -22, -8.5, 9):
        g.box("stone", (-74.7, yy, 3), (.60, 1.2, 6))
    for sx, sy in ((-64, -52), (-34, -52), (-64, 12), (-34, 12)):
        tower(g, sx, sy, 1.65, 26, 34, 16, windows=False, bottom=24)
    # Vented roof lantern and stone chimney clusters.
    g.box("stone", (-49, -12, 44), (4, 6, 6))
    for sx in (-51.04, -46.96):
        for yy in (-13.5, -10.5):
            window(g, sx, yy, 43, 0.8, 2.5, (-1 if sx < -49 else 1, 0))
    g.roof(-49, -12, 5.5, 7.5, 47, 52)


def build_castle(g):
    # Clip the whole 0.60m wall plus projecting tracery when native rooms replace it.
    g.interior_cutout_padding_m = .45
    g.lod_preserve_materials = ("room-glass",)
    room_envelopes(g)
    hall(g)
    # Continuous north gallery and entrance roofs cover their actual room extents.
    for name in ("Verbindungsgalerie", "Eingangshalle"):
        room = CASTLE_ROOMS[name]
        x, z, w, d = room["rect"]
        if w > d:
            g.roof(x + w / 2, -z - d / 2, d + 1.5, w + 1.5, 24, 38, angle=math.pi / 2)
        else:
            g.roof(x + w / 2, -z - d / 2, w + 1.5, d + 1.5, 24, 38)
    # A corbelled transition supports the historic drum above the inhabited plinth.
    # All of it starts at the ceiling: no solid cylinder occupies the native room.
    x, z, w, d = CASTLE_ROOMS["Turmhalle"]["rect"]
    base = CASTLE_ROOMS["Turmhalle"]["wall_top"]
    shoulder = base + 6
    lower, upper = [], []
    for i in range(48):
        dx, dy = math.cos(i * math.tau / 48), math.sin(i * math.tau / 48)
        tx = ((x + w + 29) / dx if dx > 1e-8 else
              (x + 29) / dx if dx < -1e-8 else math.inf)
        ty = ((-z - 36) / dy if dy > 1e-8 else
              (-z - d - 36) / dy if dy < -1e-8 else math.inf)
        radius = min(tx, ty)
        lower.append((-29 + dx * radius, 36 + dy * radius, base))
        drum_radius = 14.7 * (1 - .06 * shoulder / 67)
        upper.append((-29 + dx * drum_radius, 36 + dy * drum_radius, shoulder))
    g.mesh("stone", lower + upper,
           [(i, (i + 1) % 48, (i + 1) % 48 + 48, i + 48) for i in range(48)])
    tower(g, -29, 36, 14.7, 67, 98, 48, satellites=5, bottom=shoulder)
    # Astronomy tower has an octagonal upper observatory and a lower attached turret.
    tower(g, 84, 44, 11.8, 55, 82, 32, satellites=3)
    g.cylinder("stone", 84, 44, 47, 59, 12.2, 11.8, 8, angle=math.pi / 8)
    for i in range(8):
        theta = i * math.tau / 8 + math.pi / 4
        r = 12.2 * math.cos(math.pi / 8)
        window(g, 84 + r * math.cos(theta), 44 + r * math.sin(theta), 50, 3.6, 7.2,
               (math.cos(theta), math.sin(theta)))
    tower(g, 99, 26, 3.5, 38, 55, 24)
    tower(g, -88, 43, 11, 39, 63, 32, satellites=2)
    tower(g, -83, -29, 7.1, 28, 47, 24)
    tower(g, 78, -32, 7.3, 29, 49, 24)
    # Rear cross-wing and east chapel do not overlap any authored room footprint.
    for x, y, w, d, h, ridge in ((-63, 53, 27, 25, 26, 41),
                                (82, -3, 23, 38, 19, 33)):
        g.box("stone", (x, y, h / 2), (w, d, h))
        if w > d * 1.5:
            g.roof(x, y, d + 1.5, w + 1.5, h, ridge, angle=math.pi / 2)
        else:
            g.roof(x, y, w + 1.5, d + 1.5, h, ridge)
        for z in (0.5, h * 0.50, h - 0.4):
            g.box("trim", (x, y, z), (w + 0.3, d + 0.3, 0.4))
        for sign in (-1, 1):
            for xx in range(math.ceil(x - w / 2 + 4), math.floor(x + w / 2 - 2), 7):
                for zz in (5, 14):
                    window(g, xx, y + sign * d / 2, zz, 2.2, 5.6, (0, sign))
        for yy in range(math.ceil(y - d / 2 + 5), math.floor(y + d / 2 - 2), 8):
            window(g, x + w / 2, yy, 6, 2.4, 7, (1, 0))
    # Clock gable on north range, using hand-authored radial stone dial geometry.
    g.box("stone", (31, 44.9, 19), (12, 3.2, 38))
    g.roof(31, 44.9, 13.2, 5.0, 38, 46)
    g.cylinder("trim", 31, 44.9, 38, 39, 0.8, sides=12)
    # Dial faces toward the courtyard; no font or image dependency.
    dial_vertices = [(31, 43.15, 31)]
    dial_vertices.extend((31 + 3.5 * math.cos(i * math.tau / 48), 43.15,
                          31 + 3.5 * math.sin(i * math.tau / 48)) for i in range(48))
    g.mesh("slate", dial_vertices, [(0, i + 1, (i + 1) % 48 + 1) for i in range(48)])
    for i in range(12):
        theta = i * math.tau / 12
        g.beam("trim", (31 + 2.8 * math.sin(theta), 43.10, 31 + 2.8 * math.cos(theta)),
               (31 + 3.2 * math.sin(theta), 43.10, 31 + 3.2 * math.cos(theta)), 0.16)
    g.beam("metal", (31, 43.02, 31), (30.0, 43.02, 32.6), 0.20)
    g.beam("metal", (31, 43.02, 31), (33.3, 43.02, 30.4), 0.14)
    window(g, 31, 43.25, 0.1, 4.8, 10, (0, -1), door=True)
    # Open court: a thin paved surface only, with arcaded covered walks around it.
    g.box("paving", (30, 17, 0.05), (54, 44, 0.1))
    for i in range(8):
        x0, x1 = 3 + i * 6.75, 3 + (i + 1) * 6.75
        arcade(g, (x0, 39.0), (x1, 39.0), opening=5.5)
    g.roof(30, 41.6, 7.0, 56.0, 7, 10.0, angle=math.pi / 2)
    for side in (0, 60):
        for i in range(6):
            y0, y1 = -5 + i * (44 / 6), -5 + (i + 1) * (44 / 6)
            arcade(g, (side, y0), (side, y1), opening=6.0)
        g.roof(side, 17, 7.0, 46.0, 7, 10)
    # South arcade deliberately has one broad entrance bay, clear x25..35.
    south_piers = (3, 10, 17, 24, 36, 43, 50, 57)
    for a, b in zip(south_piers, south_piers[1:]):
        arcade(g, (a, -5), (b, -5), opening=10.5 if a == 24 else 5.7,
               spring=3.2, rise=5.5 if a == 24 else 3.2, top=9.4)
    g.roof(30, -8.5, 8, 56, 9.4, 12.6, angle=math.pi / 2)
    # Main gatehouse, real 10m wide / 10m high passage, not a closed doorway panel.
    arcade(g, (17, -54), (43, -54), opening=10.5, spring=10.2, rise=6, top=17, depth=10)
    g.roof(30, -54, 12, 28, 17, 27, angle=math.pi / 2)
    for sx in (18.0, 42.0):
        tower(g, sx, -54, 4.6, 23, 37, 24)
        window(g, sx, -58.61, 11, 1.6, 4.5, (0, -1))
    # Narrow stone bridges attach ranges without obstructing the public approach.
    g.box("stone", (65, 52, 9), (7, 10, 18))
    g.roof(65, 52, 8, 11, 18, 27)
    # Rear chimneys: distinct flues, not decorative cubes floating above a roof.
    for sx in (10, 46, -67):
        g.box("stone", (sx, 55, 32), (2.5, 3, 19))
        for dx in (-0.65, 0.65):
            g.box("trim", (sx + dx, 55, 42.5), (0.85, 1.9, 3))
    # Grounded low boundary walls establish exact 210m x 150m bounds.
    # No floor slab exists outside the actual quad and no wall seals the entrance.
    for sx in (-104.4, 104.4):
        g.box("stone", (sx, 0, 1.2), (1.2, 150, 2.4))
        g.box("trim", (sx, 0, 2.45), (1.2, 150, 0.1))
    g.box("stone", (0, 74.4, 1.2), (210, 1.2, 2.4))
    for a, b in ((-105, 24), (36, 105)):
        g.box("stone", ((a + b) / 2, -74.4, 1.2), (b - a, 1.2, 2.4))
    for sx in (-99, -75, -51, -3, 21, 39, 63, 87, 99):
        for sy in (-74.4, 74.4):
            # Pillars stay inside declared bounds and outside the clear entry strip.
            g.box("trim", (sx, sy, 1.6), (1.0, 1.0, 3.2))


def build_hut(g):
    # Broad octagonal stone cottage: original fan interpretation of the paired roof form.
    # Slightly elliptical in plan so porch + rear roof fit a roughly 10 x 9m footprint.
    # Hollow wall shell, not a capped cylinder: the south facet is a true open doorway.
    for i in range(8):
        if i == 5:  # south facet, replaced below with a pierced Gothic portal
            continue
        a, b = math.pi / 8 + i * math.tau / 8, math.pi / 8 + (i + 1) * math.tau / 8
        outer = [(4.0 * math.cos(t), 4.0 * math.sin(t) * 0.86) for t in (a, b)]
        inner = [(3.72 * math.cos(t), 3.72 * math.sin(t) * 0.86) for t in (a, b)]
        vertices = [(x, y, z) for z in (0, 4.5) for x, y in outer + list(reversed(inner))]
        g.mesh("stone", vertices, [(0, 1, 5, 4), (2, 3, 7, 6), (1, 2, 6, 5),
                                    (3, 0, 4, 7), (4, 5, 6, 7), (3, 2, 1, 0)])
    g.cylinder("paving", 0, 0, 0, 0.08, 3.72, sides=8, angle=math.pi / 8, y_scale=0.86)
    g.cylinder("trim", 0, 0, 4.25, 4.57, 4.04, sides=8, angle=math.pi / 8, y_scale=0.86)
    g.cylinder("slate", 0, 0, 4.5, 8.1, 5.0, 0.18, 32, y_scale=0.82)
    g.cylinder("metal", 0, 0, 8.05, 8.4, 0.18, 0.04, 8)
    # A smaller overlapping scullery roof on the west side creates the familiar uneven cottage.
    # The solid pantry stays outside the declared central furnishing rectangle.
    g.box("stone", (-3.725, 0.6, 1.85), (1.45, 3.4, 3.7))
    g.cylinder("slate", -2.6, 0.6, 3.7, 5.9, 2.25, 0.10, 24, y_scale=0.85)
    # Tall crooked chimney emerges through the roof and has a genuinely hollow top.
    g.box("stone", (2.0, 0.8, 6.0), (1.0, 1.05, 4.0))
    g.box("trim", (2.0, 0.8, 7.9), (1.25, 1.28, 0.24))
    for dx, dy, sx, sy in ((-0.45, 0, 0.20, 1.05), (0.45, 0, 0.20, 1.05),
                           (0, -0.425, 0.70, 0.20), (0, 0.425, 0.70, 0.20)):
        g.box("stone", (2 + dx, 0.8 + dy, 8.17), (sx, sy, 0.5))
    g.box("slate", (2, 0.8, 7.99), (0.70, 0.70, 0.02))
    # Facade planes are aligned to the octagon's south and east facets.
    south_plane = -4.0 * math.cos(math.pi / 8) * 0.86
    half_facet = 4.0 * math.sin(math.pi / 8)
    arcade(g, (-half_facet, south_plane), (half_facet, south_plane),
           opening=1.95, spring=3.15, rise=1.05, top=4.5, depth=0.50)
    g.box("trim", (0, south_plane, 0.04), (1.8, 0.6, 0.08))
    window(g, 4.0 * math.cos(math.pi / 8), 0, 1.3, 1.15, 1.55, (1, 0))
    window(g, 0, 4.0 * math.cos(math.pi / 8) * 0.86, 1.3, 1.2, 1.7, (0, 1))
    # Ground-level open porch, plank deck, timber posts and braced slate canopy.
    g.box("wood", (0, -4.0, 0.10), (3.4, 1.8, 0.20))
    g.roof(0, -4.0, 3.8, 1.8, 3.5, 4.3)
    for sx in (-1.55, 1.55):
        g.box("wood", (sx, -4.65, 1.80), (0.16, 0.16, 3.4))
        g.beam("wood", (sx, -4.65, 2.8), (sx * 0.62, -4.65, 3.5), 0.12)
    # Handmade bench beside, not across, the entrance; rain barrel with hoops.
    g.box("wood", (-2.3, -3.5, 0.7), (1.45, 0.55, 0.14))
    for sx in (-2.8, -1.8):
        g.box("wood", (sx, -3.5, 0.34), (0.12, 0.40, 0.68))
    g.cylinder("wood", 3.45, -2.5, 0, 1.1, 0.48, sides=16)
    for z in (0.14, 0.86):
        g.cylinder("metal", 3.45, -2.5, z, z + 0.07, 0.50, sides=16)
    # Five deliberately chunky split logs rather than particle systems or downloaded props.
    for i in range(5):
        g.beam("wood", (-3.5 + i * 0.17, -2.8, 0.10), (-3.5 + i * 0.17, -1.65, 0.10), 0.18)


def create_materials(bpy, texture_dir):
    definitions = {
        "stone": ("stone", (1.0, 0.98, 0.94, 1), 0.94, 0.0),
        "trim": ("stone", (1.0, 1.0, 1.0, 1), 0.84, 0.0),
        "paving": ("stone", (0.65, 0.68, 0.66, 1), 0.96, 0.0),
        "slate": ("slate", (0.87, 0.94, 1.0, 1), 0.78, 0.0),
        "wood": ("wood", (1.0, 0.93, 0.80, 1), 0.86, 0.0),
        "glass": ("glass", (0.8, 0.9, 0.84, 1), 0.32, 0.12),
        "room-glass": ("glass", (0.86, 0.94, 0.94, .32), 0.18, 0.05),
        "metal": ("slate", (0.36, 0.36, 0.34, 1), 0.57, 0.65),
    }
    materials = {}
    for name, (texture, tint, roughness, metallic) in definitions.items():
        path = texture_dir / f"original-{name}.png"
        write_texture(path, texture, tint=tint[:3])
        image = bpy.data.images.load(str(path), check_existing=False)
        image.name = f"Original procedural {name} PNG"
        image.colorspace_settings.name = "sRGB"
        image.pack()
        material = bpy.data.materials.new(f"Original {name}")
        material.use_nodes = True
        material.diffuse_color = tint
        material.use_backface_culling = False
        bsdf = material.node_tree.nodes.get("Principled BSDF")
        bsdf.inputs["Roughness"].default_value = roughness
        bsdf.inputs["Metallic"].default_value = metallic
        if name == "room-glass":
            bsdf.inputs["Alpha"].default_value = tint[3]
            material.surface_render_method = "BLENDED"
        tex = material.node_tree.nodes.new("ShaderNodeTexImage")
        tex.image = image
        tex.extension = "REPEAT"
        # Direct image link keeps exported material fully glTF-PBR-compatible.
        # Dark lead/roof values are authored in each PNG, not unsupported shader noise.
        material.node_tree.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
        if name == "glass":
            material.node_tree.links.new(tex.outputs["Color"], bsdf.inputs["Emission Color"])
            bsdf.inputs["Emission Strength"].default_value = 0.12
        materials[name] = material
    return materials


def export_asset(bpy, output, logical_name, materials, builder, description, recenter=True):
    # The output contains only authored meshes, with no cameras, rigs, lights or default cube.
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    geometry = Geometry(bpy, materials)
    builder(geometry)
    objects = geometry.emit(logical_name)
    low = [min(vertex.co[axis] for obj in objects for vertex in obj.data.vertices) for axis in range(3)]
    high = [max(vertex.co[axis] for obj in objects for vertex in obj.data.vertices) for axis in range(3)]
    offset = ((low[0] + high[0]) / 2 if recenter else 0,
              (low[1] + high[1]) / 2 if recenter else 0, low[2])
    for obj in objects:
        for vertex in obj.data.vertices:
            for axis in range(3):
                vertex.co[axis] -= offset[axis]
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    path = output / f"{logical_name}.glb"
    bpy.ops.export_scene.gltf(
        filepath=str(path), export_format="GLB", use_selection=True,
        export_yup=True, export_texcoords=True, export_normals=True,
        export_materials="EXPORT", export_image_format="AUTO",
        export_animations=False, export_skins=False, export_morph=False,
        export_cameras=False, export_lights=False, export_extras=True,
    )
    return {
        "file": path.name,
        "width_m": round(high[0] - low[0], 5),
        "depth_m": round(high[1] - low[1], 5),
        "height_m": round(high[2] - low[2], 5),
        "kind": "building",
        "description": description,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path, help="Destination for two GLBs and castle-manifest.json")
    args = parser.parse_args(argv)
    import bpy  # Blender dependency is deliberately delayed until explicit execution.
    output = args.output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    bpy.context.scene.unit_settings.system = "METRIC"
    bpy.context.scene.unit_settings.scale_length = 1.0
    with tempfile.TemporaryDirectory(prefix="hogwarts-original-png-") as temporary:
        materials = create_materials(bpy, Path(temporary))
        castle = export_asset(
            bpy, output, "hogwarts-castle", materials, build_castle,
            "Eigenständig modellierte, inoffizielle Film-Hogwarts-Fanansicht: großer Treppenturm, "
            "Große Halle, Astronomieturm, Schieferdächer, Spitzbogenfenster, Strebepfeiler und "
            "begehbarer offener Kreuzganghof mit echtem südlichem Tordurchgang. Vier begehbare "
            "Raumhüllen mit echten Fensteröffnungen, Laibungen und durchsichtiger Verglasung.",
            recenter=False,
        )
        hut = export_asset(
            bpy, output, "hagrid-hut", materials, build_hut,
            "Eigenständig gestaltete achteckige Steinhütte mit ungleichen Schieferdächern, hohem "
            "Schornstein, offenem südlichem Torbogen, hohlem Innenraum, Holzveranda, Bank, "
            "Regentonne und Holzvorrat; inoffizielle Fanansicht.",
        )
    manifest = {
        "assets": {"hogwarts-castle": castle, "hagrid-hut": hut},
        "provenance": PROVENANCE,
        "geometry": {
            "coordinate_system": "GLB local metres: x east, y up, z south. Blender source (x,y,z) maps to GLB (x,z,-y).",
            "hogwarts-castle": {
                "ground_origin": [0, 0, 0],
                "bounds_xz": [-105, -75, 105, 75],
                "courtyard_polygon_xz": [[3, -39], [57, -39], [57, 5], [3, 5]],
                "unobstructed_courtyard_rect_xz": [8, -34, 52, 0],
                "courtyard_floor_y": 0.1,
                "courtyard_recommended_center_xz": [30, -17],
                "south_cloister_passage_rect_xz": [25, 5, 35, 13],
                "entry_approach_rect_xz": [25, 13, 35, 75],
                "gatehouse_passage_rect_xz": [25, 49, 35, 59],
                "gatehouse_clear_height_m": 10,
                "entry_boundary_xz": [30, 75],
                "entry_recommended_center_xz": [30, 64],
                "authored_rooms": CASTLE_ROOMS,
                "native_storey_height_m": 24,
                "authored_wall_thickness_m": .6,
                "notes": "The courtyard and approach have no solid building bases. Four inhabited room footprints have hollow masonry shells with real revealed windows and separate transparent glass; their exact openings also author the native layout.",
            },
            "hagrid-hut": {
                "ground_origin": [0, 0, 0],
                "bounds_xz": [-5, -4.5, 5, 4.5],
                "porch_facing": "south (+local z)",
                "porch_floor_y": 0.20,
                "interior_floor_y": 0.08,
                "unobstructed_interior_rect_xz": [-2.2, -2.4, 2.2, 1.6],
                "door_center_xz": [0, 4 * math.cos(math.pi / 8) * 0.86 - 0.4],
                "door_wall_rect_xz": [-0.85, 4 * math.cos(math.pi / 8) * 0.86 - 0.65,
                                      0.85, 4 * math.cos(math.pi / 8) * 0.86 - 0.15],
                "door_clear_width_m": 1.7,
                "door_clear_height_m": 3.0,
                "entry_corridor_rect_xz": [-0.85, 1.6, 0.85, 4.5],
                "interior_polygon_xz": [
                    [3.72 * math.cos(math.pi / 8 + i * math.tau / 8),
                     -3.72 * math.sin(math.pi / 8 + i * math.tau / 8) * 0.86 - 0.4]
                    for i in range(8)
                ],
                "notes": "The main cottage has hollow walls and a true open south door; its central rectangle is clear for native room furnishing. The solid west pantry lies outside that rectangle.",
            },
        },
    }
    (output / "castle-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Authored {castle['file']}, {hut['file']} and castle-manifest.json in {output}")


if __name__ == "__main__":
    main(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:])
