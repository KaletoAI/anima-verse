#!/usr/bin/env python3
"""Author the self-contained Hogwarts arrival demo through the public HTTP API.

Run ONCE against a newly bootstrapped, empty, FROZEN isolated world whose private
media master switch is already off::

    python3 build_world.py --url http://127.0.0.1:PORT \
        --assets /absolute/generated-assets \
        --credentials-file /private/admin.json --work-dir /private/build-record

The credentials file contains {"username": "...", "password": "..."}; this
program neither bootstraps users nor reads installation settings. Credentials
and cookies are never written to the build record or printed. Every CONTENT
request body is saved before sending; authentication is recorded only redacted.
The record is private build evidence, not a directory to ship with the demo.

There is deliberately no resume/retry mode: map/location/character creation is
not replay-safe. After any failure discard the isolated world and start with a
new work directory. The exclusive build-started.json marker prevents replay.
There are no import-time actions, third-party imports, LLM calls, marketplace
installs, shared writes, generated-ID assumptions, or runtime asset-directory
references. Both asset manifests and every model are checked before mutation.

Supported API limitations (source-checked):
* World props are decorative, not transport/collision mechanics. Boats and the
  stationary train do not offer rides. The western shore is the real land route.
* Surface-texture uploads write shared/surface_textures, so they are NOT used.
  Native terrain uses world-local types, colors and water/relief metadata; room
  materials are the engine's untextured defaults. Model textures are embedded.
* The manifest contract has no humanoid meshes. Characters are real clothed
  human-roleplay records with eight soul files, inventory and own painted PNG
  portraits; this author does not pretend to upload a 52-joint character rig.
* Building upload can schedule server-local Blender LOD/surface processing. A
  controller must wait for those jobs and exercise the real 3D client, then stop
  the server and sanitize users/auth/sessions/queues before shipping. A new
  installation must use the app's normal first-user bootstrap, never a bundled
  password. This script does not perform that offline shipping operation.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import http.cookiejar
import json
import math
import os
from pathlib import Path
import re
import struct
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zlib


PROVENANCE = "Self-authored procedural geometry/textures; no extracted/downloaded assets"
MANIFEST_ASSETS = {
    "castle-manifest.json": {"hogwarts-castle": "building", "hagrid-hut": "building"},
    "arrival-manifest.json": {
        "station": "building", "hogwarts-express": "prop", "boathouse": "building",
        "rowboat": "prop", "jetty": "prop", "bench": "prop", "lantern": "prop",
        "luggage": "prop", "signpost": "prop", "pine": "prop",
        "broadleaf": "prop", "stone-gate": "prop",
    },
}
SOUL_HEADINGS = {
    "personality": "Personality", "presence": "Presence", "tasks": "Tasks",
    "roleplay_rules": "Roleplay rules", "beliefs": "Beliefs", "lessons": "Lessons learned",
    "goals": "Personal Goals", "soul": "Soul",
}
BRIEFING = """Die Welt ist eine deutschsprachige, sichere Hogwarts-Ankunftsszene am ersten
Schultag eines neuen Schuljahrs, im Spätnachmittag des frühen Herbstes. Hogwarts
ist die vertraute schottische Schule aus der Filmvorstellung: ein asymmetrisches
Schloss aus Sandstein mit steilen Schieferdächern, großer Halle, Türmen und einem
wirklich offenen Innenhof. Hogsmeade ist der kleine ländliche Ankunftsbahnhof,
nicht King's Cross. Der rote Hogwarts-Express steht dort als unbewegtes Schaustück.
Südlich liegen Waldweg und Anlegestelle am Schwarzen See. Das Bootshaus liegt am
Nordufer; Hagrids Hütte westlich des Schlosses, das Steintor vor dem Schloss.
Ein durchgehend trockener Wanderweg führt vom Bahnhof um das WESTLICHE Seeufer,
über die Uferbank und Hagrids Hütte zum Tor, Bootshaus und Schlosshof. Es gibt
keine Straße quer über den See. Die Boote sind festliegende Dekoration: erzählt
von traditionellen Überfahrten, behauptet aber keine steuerbaren Boote, Fähren,
Fahrkartenautomatik oder Zugfahrten, die diese Demo nicht implementiert.

Alles bleibt SFW und für alle Altersgruppen geeignet: keine Sexualisierung,
kein Entkleidungsspiel, keine romantischen Angebote an Minderjährige, keine
explizite Gewalt. Alle vier ausgearbeiteten Rollen sind Erwachsene; Schülerinnen
und Schüler existieren nur als respektvoll beschriebener Hintergrund. Niemand
muss eine Kinderrolle übernehmen. Die Besucherin Johanna Falk ist eine erwachsene
Restauratorin mit Einladung und der vorgesehene Spieleravatar. Rubeus Hagrid
bewohnt seine Hütte, Professorin Minerva McGonagall begrüßt am Schloss, die
originale Stationsvorsteherin Elspeth Rowan betreut den Bahnhof. Diese Figuren
sind eigenständig gestaltete Interpretationen, keine Nachbildungen realer
Schauspielergesichter. Wissen und Beziehungen stehen in ihren Seelenprofilen.

Magie ist Teil des Alltags, keine Erlaubnis, technische Fähigkeiten zu erfinden.
Man zeigt Wege, erklärt Schultraditionen, hilft mit Koffern, achtet auf den
Abstand zum kalten Wasser und fragt, bevor fremdes Eigentum benutzt wird.
Ausgearbeitete begehbare Schlosszonen sind Torweg, südlicher Kreuzgang und Hof;
das vollständige Schlossinnere wird ausdrücklich nicht simuliert. Räume und
Gegenstände sollen beim Namen genannt werden. Keine vorgetäuschten Geheimräume,
keine erfundenen Fahr- oder Bootsaktionen. Die Welt bleibt zunächst eingefroren;
erst der Betreiber entscheidet über den Beginn der autonomen Simulation.
""".rstrip()


class BuildError(RuntimeError):
    """A checked authoring contract was not satisfied; never replay a write."""


def require(condition, message):
    if not condition:
        raise BuildError(message)


def dump_json(path: Path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise BuildError("Unexpected HTTP redirect refused (no credential forwarding)")


class Client:
    def __init__(self, url: str, work_dir: Path):
        parsed = urllib.parse.urlsplit(url)
        require(parsed.scheme in ("http", "https") and parsed.hostname,
                "--url must be an explicit HTTP(S) server origin")
        require(not parsed.username and not parsed.password and not parsed.query
                and not parsed.fragment and parsed.path in ("", "/"),
                "--url must be an origin, without credentials, path, query or fragment")
        self.url = url.rstrip("/")
        self.work_dir = work_dir
        self.cookies = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            NoRedirect(), urllib.request.HTTPCookieProcessor(self.cookies))
        self.sequence = 0
        self.endpoints = set()

    def request(self, method: str, path: str, payload=None, *, upload: Path | None = None,
                fields=None, confidential=False):
        require(path.startswith("/") and not path.startswith("//"), "Invalid API path")
        self.sequence += 1
        self.endpoints.add((method, path))
        slug = re.sub(r"[^a-zA-Z0-9_-]", "_", path).strip("_")[:120]
        stem = self.work_dir / f"{self.sequence:04d}-{method.lower()}-{slug}"
        headers = {"Accept": "application/json"}
        body = None
        if upload is not None:
            content = upload.read_bytes()
            boundary = "hogwarts-" + uuid.uuid4().hex
            chunks = []
            for key, value in (fields or {}).items():
                chunks.append((f"--{boundary}\r\nContent-Disposition: form-data; "
                               f'name="{key}"\r\n\r\n{value}\r\n').encode())
            mime = "model/gltf-binary" if upload.suffix == ".glb" else "image/png"
            chunks.extend([
                (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
                 f'filename="{upload.name}"\r\nContent-Type: {mime}\r\n\r\n').encode(),
                content, f"\r\n--{boundary}--\r\n".encode(),
            ])
            body = b"".join(chunks)
            headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
            # The exact multipart body, including model bytes, exists BEFORE send.
            stem.with_suffix(".multipart").write_bytes(body)
            recorded = {"fields": fields or {}, "file": upload.name,
                        "sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)}
        elif payload is not None:
            body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
            recorded = {"authentication": "redacted"} if confidential else payload
        else:
            recorded = None
        dump_json(stem.with_suffix(".request.json"),
                  {"method": method, "path": path, "payload": recorded})
        request = urllib.request.Request(self.url + path, data=body, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=900) as response:
                raw = response.read()
                require(response.headers.get_content_type() == "application/json",
                        f"{method} {path}: expected JSON, not a login page")
                result = json.loads(raw)
        except urllib.error.HTTPError as error:
            if not confidential:
                stem.with_suffix(".error.txt").write_bytes(error.read())
            raise BuildError(f"{method} {path}: HTTP {error.code}; stopped, no replay") from None
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            raise BuildError(f"{method} {path}: {type(error).__name__}; stopped, no replay") from None
        if not confidential:
            dump_json(stem.with_suffix(".response.json"), result)
        if isinstance(result, dict):
            require(result.get("valid") is not False, f"{path}: invalid preview; inspect response")
            require(result.get("status") not in ("error", "failed"), f"{path}: failed write")
            require(not result.get("warnings"), f"{path}: contract warnings; inspect response")
            require(not result.get("rejected"), f"{path}: rejected bulk entries; inspect response")
            require(not result.get("errors"), f"{path}: API errors; inspect response")
        return result

    def get(self, path, *, confidential=False):
        return self.request("GET", path, confidential=confidential)

    def post(self, path, payload):
        return self.request("POST", path, payload)

    def put(self, path, payload):
        return self.request("PUT", path, payload)

    def upload(self, path, filename, **fields):
        return self.request("POST", path, upload=filename, fields=fields)


def validate_glb(path: Path):
    content = path.read_bytes()
    require(20 <= len(content) <= 100 * 1024 * 1024, f"Invalid model size: {path.name}")
    magic, version, length = struct.unpack_from("<4sII", content)
    require(magic == b"glTF" and version == 2 and length == len(content),
            f"Invalid GLB header: {path.name}")
    json_len, chunk_type = struct.unpack_from("<II", content, 12)
    require(chunk_type == 0x4E4F534A, f"Missing GLB JSON chunk: {path.name}")
    document = json.loads(content[20:20 + json_len])
    require(not document.get("skins"), f"Static asset has a rig: {path.name}")
    require(document.get("meshes") and document.get("images"),
            f"Static model needs meshes and embedded images: {path.name}")
    for image in document["images"]:
        require("uri" not in image and "bufferView" in image,
                f"External or missing image data: {path.name}")
    require(all("uri" not in buffer for buffer in document.get("buffers", [])),
            f"External GLB buffers: {path.name}")


def load_assets(directory: Path):
    assets = {}
    manifests = {}
    for filename, expected in MANIFEST_ASSETS.items():
        manifest = json.loads((directory / filename).read_text(encoding="utf-8"))
        require(isinstance(manifest.get("provenance"), str) and manifest["provenance"],
                f"{filename}: provenance missing")
        entries = manifest.get("assets", {})
        require(set(expected).issubset(entries), f"{filename}: required assets missing")
        for key, kind in expected.items():
            spec = copy.deepcopy(entries[key])
            require(spec.get("kind") == kind, f"{key}: wrong manifest kind")
            require(spec.get("file") == f"{key}.glb", f"{key}: unexpected filename")
            for dimension in ("width_m", "depth_m", "height_m"):
                value = spec.get(dimension)
                require(isinstance(value, (int, float)) and not isinstance(value, bool)
                        and math.isfinite(value) and value > 0, f"{key}: invalid {dimension}")
            require(spec.get("description"), f"{key}: missing description")
            path = (directory / spec["file"]).resolve()
            require(path.parent == directory.resolve(), f"{key}: asset escapes --assets")
            validate_glb(path)
            spec["path"] = path
            spec["geometry"] = copy.deepcopy((manifest.get("geometry") or {}).get(key,{ }))
            assets[key] = spec
        manifests[filename] = manifest
    require(200 <= assets["hogwarts-castle"]["width_m"] <= 220,
            "Castle manifest violates agreed 210m silhouette")
    require(70 <= assets["hogwarts-express"]["depth_m"] <= 95,
            "Train must be 70–95m long on local z")
    hut_geometry = assets["hagrid-hut"]["geometry"]
    require(hut_geometry.get("door_clear_width_m") == 1.7
            and hut_geometry.get("door_clear_height_m",0) >= 3
            and hut_geometry.get("unobstructed_interior_rect_xz") == [-2.2,-2.4,2.2,1.6],
            "Hut requires the final hollow-shell manifest with a real 3m-high doorway; regenerate assets")
    castle_geometry = assets["hogwarts-castle"]["geometry"]
    require(castle_geometry.get("unobstructed_courtyard_rect_xz") == [8,-34,52,0]
            and castle_geometry.get("entry_approach_rect_xz") == [25,13,35,75],
            "Castle courtyard/entry geometry differs from the approved usable-layout contract")
    return assets, manifests


def png_bytes(width, height, pixels):
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + bytes(pixels[y * width * 3:(y + 1) * width * 3])
                   for y in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def make_furniture(directory: Path):
    """Small permanent furnishings; explicit solid joinery, own embedded wood grain."""
    def box(x, y, z, w, h, d, color="wood"):
        return (x, y, z, w, h, d, color)
    legs = [box(x, .39, z, .12, .78, .12) for x in (-.65, .65) for z in (-.30, .30)]
    chair = [box(0, .46, 0, .56, .10, .58), box(0, .76, -.25, .56, .48, .08)]
    chair += [box(x, .23, z, .07, .46, .07) for x in (-.23, .23) for z in (-.23, .23)]
    shelf = [box(x, .95, 0, .09, 1.90, .42) for x in (-.605, .605)]
    shelf += [box(0, y, 0, 1.30, .08, .42) for y in (.04, .63, 1.25, 1.86)]
    shelf += [box(0, .95, -.19, 1.30, 1.90, .04)]
    for row in (.30, .89, 1.51):
        for index in range(8):
            shelf.append(box(-.49 + index * .14, row, -.02, .105, .40, .29,
                             ("green", "red", "cream")[index % 3]))
    definitions = {
        "cottage-table": ("Schwerer Hütten-Eichentisch", "furniture", [box(0, .82, 0, 1.6, .08, .8)] + legs),
        "oak-chair": ("Eichenstuhl", "furniture", chair),
        "bookcase": ("Regal mit Schulbüchern", "furniture", shelf),
        "cottage-bed": ("Hagrids breites Hüttenbett", "furniture", [
            box(0, .23, 0, 1.8, .46, 2.65), box(0, .54, .12, 1.76, .18, 2.36, "green"),
            box(0, .72, -1.22, 1.8, .72, .14), box(0, .69, -.88, 1.35, .13, .40, "cream")]),
        "writing-desk": ("Stationsschreibtisch", "furniture", [
            box(0, .77, 0, 1.7, .10, .8), box(-.60, .36, 0, .43, .72, .72),
            box(.60, .36, 0, .43, .72, .72), box(0, .84, -.12, .48, .04, .30, "cream")]),
        "hearth": ("Steinerner Hüttenherd", "furniture", [
            box(0, .09, 0, 1.55, .18, .65, "stone"),
            box(-.60, .72, -.04, .29, 1.25, .57, "stone"),
            box(.60, .72, -.04, .29, 1.25, .57, "stone"),
            box(0, 1.31, -.04, 1.55, .18, .57, "stone"),
            box(0, .65, -.29, .94, 1.15, .06, "black"),
            box(-.12, .26, -.06, .65, .16, .19, "wood")]),
        "school-trunk": ("Schultruhe aus dunklem Holz", "furniture", [
            box(0, .29, 0, 1.0, .58, .62),
            box(-.30, .30, 0, .055, .60, .64, "brass"),
            box(.30, .30, 0, .055, .60, .64, "brass"),
            box(0, .36, .33, .13, .16, .035, "brass")]),
    }
    palette = {"wood": (.43, .25, .11, 1), "green": (.14, .27, .20, 1),
               "red": (.40, .12, .12, 1), "cream": (.85, .78, .61, 1),
               "stone": (.48, .46, .40, 1), "black": (.055, .05, .045, 1),
               "brass": (.68, .49, .19, 1)}
    pixels = bytearray()
    for y in range(64):
        for x in range(64):
            tone = int(231 + 14 * math.sin(x * .73 + math.sin(y * .17)))
            pixels.extend((tone, max(0, tone - 6), max(0, tone - 15)))
    texture = png_bytes(64, 64, pixels)
    result = {}
    faces = [((0, 0, 1), (4, 5, 6, 7)), ((0, 0, -1), (1, 0, 3, 2)),
             ((1, 0, 0), (5, 1, 2, 6)), ((-1, 0, 0), (0, 4, 7, 3)),
             ((0, 1, 0), (3, 7, 6, 2)), ((0, -1, 0), (0, 1, 5, 4))]
    for logical, (name, category, parts) in definitions.items():
        bounds = [(min(p[i] - p[i+3]/2 for p in parts), max(p[i] + p[i+3]/2 for p in parts))
                  for i in range(3)]
        origin = [(bounds[0][0]+bounds[0][1])/2, bounds[1][0], (bounds[2][0]+bounds[2][1])/2]
        parts = [(x-origin[0],y-origin[1],z-origin[2],w,h,d,color)
                 for x,y,z,w,h,d,color in parts]
        binary = bytearray()
        views, accessors, primitives = [], [], []
        def view(data, target=None):
            binary.extend(b"\x00" * ((-len(binary)) % 4))
            record = {"buffer": 0, "byteOffset": len(binary), "byteLength": len(data)}
            if target:
                record["target"] = target
            views.append(record)
            binary.extend(data)
            return len(views) - 1
        def accessor(values, components, typ, count, target, minimum=None, maximum=None):
            index = view(struct.pack("<" + components * len(values), *values), target)
            record = {"bufferView": index, "componentType": 5126 if components == "f" else 5123,
                      "count": count, "type": typ}
            if minimum is not None:
                record.update(min=minimum, max=maximum)
            accessors.append(record)
            return len(accessors) - 1
        for material, color in enumerate(palette):
            positions, normals, uvs, indices = [], [], [], []
            for x, y, z, w, h, d, part_color in parts:
                if part_color != color:
                    continue
                corners = [(x + sx * w / 2, y + sy * h / 2, z + sz * d / 2)
                           for sx, sy, sz in ((-1,-1,-1),(1,-1,-1),(1,1,-1),(-1,1,-1),
                                              (-1,-1,1),(1,-1,1),(1,1,1),(-1,1,1))]
                for normal, corner_indices in faces:
                    start = len(positions) // 3
                    for corner, uv in zip(corner_indices, ((0,0),(1,0),(1,1),(0,1))):
                        positions.extend(corners[corner])
                        normals.extend(normal)
                        uvs.extend(uv)
                    indices.extend(start + i for i in (0,1,2,0,2,3))
            if not positions:
                continue
            mins = [min(positions[i::3]) for i in range(3)]
            maxs = [max(positions[i::3]) for i in range(3)]
            pa = accessor(positions, "f", "VEC3", len(positions)//3, 34962, mins, maxs)
            na = accessor(normals, "f", "VEC3", len(normals)//3, 34962)
            ua = accessor(uvs, "f", "VEC2", len(uvs)//2, 34962)
            ia = accessor(indices, "H", "SCALAR", len(indices), 34963)
            primitives.append({"attributes": {"POSITION": pa, "NORMAL": na, "TEXCOORD_0": ua},
                               "indices": ia, "material": material})
        image_view = view(texture)
        document = {"asset": {"version": "2.0", "generator": "Hogwarts own stdlib furniture author"},
                    "scene": 0, "scenes": [{"nodes": [0]}], "nodes": [{"mesh": 0, "name": name}],
                    "meshes": [{"primitives": primitives}], "bufferViews": views,
                    "accessors": accessors, "images": [{"bufferView": image_view, "mimeType": "image/png"}],
                    "textures": [{"source": 0}], "materials": [
                        {"name": key, "pbrMetallicRoughness": {"baseColorFactor": list(value),
                         "baseColorTexture": {"index": 0}, "metallicFactor": .55 if key == "brass" else 0,
                         "roughnessFactor": .68}} for key, value in palette.items()],
                    "buffers": [{"byteLength": len(binary)}]}
        encoded = json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        encoded += b" " * ((-len(encoded)) % 4)
        binary.extend(b"\x00" * ((-len(binary)) % 4))
        content = (struct.pack("<4sII", b"glTF", 2, 28 + len(encoded) + len(binary))
                   + struct.pack("<II", len(encoded), 0x4E4F534A) + encoded
                   + struct.pack("<II", len(binary), 0x004E4942) + binary)
        path = directory / f"{logical}.glb"
        path.write_bytes(content)
        bounds = [(min(p[i] - p[i+3]/2 for p in parts), max(p[i] + p[i+3]/2 for p in parts))
                  for i in range(3)]
        # Tuple order is center x,y,z then width,height,depth.
        result[logical] = {"file": path.name, "path": path, "kind": "prop", "name": name,
                           "category": category, "width_m": bounds[0][1] - bounds[0][0],
                           "depth_m": bounds[2][1] - bounds[2][0],
                           "height_m": bounds[1][1] - bounds[1][0],
                           "description": name + "; eigenständig modellierte Holz-/Steinmöbel, eingebettete eigene Textur."}
    return result


def rect(x0, z0, x1, z1):
    return [[x0, z0], [x1, z0], [x1, z1], [x0, z1]]


def place_specs(assets):
    castle = assets["hogwarts-castle"]
    cw, cd = castle["width_m"], castle["depth_m"]
    return [
        {"key": "station", "name": "Bahnhof Hogsmeade", "pos": (-440,570),
         "boundary": rect(-41,-50,41,50), "asset": "station", "indoor": "outdoor",
         "description": "Der ländliche Bahnhof Hogsmeade besteht aus warmem Sandstein, dunklen Giebeln und grün-cremefarbenem Holzwerk. Östlich des Gebäudes steht der rote Hogwarts-Express still am langen Bahnsteig. Unter dem Vordach riecht es nach feuchtem Holz und Kohle; vom nördlichen Ausgang führt der Waldweg zum See. Elspeth Rowan hilft mit Gepäck und erklärt den trockenen Weg zum Schloss.",
         "activity": "ankommen, Gepäck ordnen, nach dem Schlossweg fragen und auf der Bank warten",
         "rooms": [
             ("Bahnsteig", "Der breite Bahnsteig zwischen Stationsgebäude und stehendem Express bietet Platz zum Ankommen. Der Bahnsteigrand bleibt frei; der Zug ist ein unbewegtes Ausstellungsstück.", "outdoor"),
             ("Wartesaal", "Im geschützten Wartesaal stehen Holzbänke und Reisekoffer. Helle Fenster blicken auf den Bahnsteig; eine seitliche Tür führt in das kleine Fahrkartenbüro.", "indoor"),
             ("Fahrkartenbüro", "Elspeths kleines Büro enthält einen hölzernen Schreibtisch, Ablagen und das Stationsbuch. Hier werden Auskünfte gegeben und verlorene Koffer notiert, keine simulierten Zugfahrten verkauft.", "indoor")],
         "entry": "Bahnsteig"},
        {"key": "south", "name": "Südliche Seeanlegestelle", "pos": (-245,455),
         "boundary": rect(-15,-17,15,17), "indoor": "outdoor",
         "description": "Eine trockene, kiesige Landzunge schiebt sich am Südufer zwischen Schilf und dunkles Wasser. Ein schmaler Holzsteg und festliegende Ruderboote erinnern an die traditionelle Ankunft über den See. Hinter den Booten ist die Silhouette von Hogwarts zu sehen. Der sichere Weg führt zu Fuß westlich um den See; Boote sind hier Dekoration, keine benutzbare Transportfunktion.",
         "activity": "Schlossblick genießen, die Ankunftstradition besprechen und auf dem trockenen Ufer bleiben",
         "rooms": [("Uferplatz", "Der feste Kiesplatz am Steg bietet einen ruhigen Aussichtspunkt auf den Schwarzen See. Eine Bank und eine Laterne markieren den Treffpunkt; die nasse Kante ist kein Einstieg für einen erfundenen Fährdienst.", "outdoor")], "entry": "Uferplatz"},
        {"key": "shore", "name": "Westlicher Uferweg", "pos": (-455,220),
         "boundary": rect(-14,-18,14,18), "indoor": "outdoor",
         "description": "Auf der trockenen Westseite des Schwarzen Sees läuft der Kiesweg zwischen Kiefern und Heide. Durch die Stämme glitzert Wasser; auf der anderen Seite zeichnen sich Schlossdächer ab. Eine Bank bietet eine Pause auf dem echten Landweg vom Bahnhof zu Hagrids Hütte. Der Weg ist sanft geneigt und bleibt abseits der steilen Hügel.",
         "activity": "eine Gehpause einlegen, sich orientieren und dem Uferweg folgen",
         "rooms": [("Aussichtsbank", "Die Bank steht auf einer ebenen Wegaufweitung mit Blick zwischen zwei Kiefern. Ein Wegweiser zeigt nach Süden zum Bahnhof und nach Norden zu Hagrids Hütte und Hogwarts.", "outdoor")], "entry": "Aussichtsbank"},
        {"key": "hut", "name": "Hagrids Hütte", "pos": (-90,-125),
         "boundary": rect(-5,-4.5,5,4.5), "asset": "hagrid-hut", "indoor": "indoor",
         "description": "Hagrids kleine Hütte liegt westlich des Schlosses am Rand einer Birken- und Kieferngruppe. Grober Stein, ein rauchloser Schornstein und eine südliche Holzveranda rahmen die schwere Eingangstür. Innen stehen übergroße, schlichte Möbel, ein Herd und Hagrids Bett. Vom Vorplatz führt ein trockener Pfad zum Schlosstor und westlich hinunter zum Seeufer.",
         "activity": "Hagrid besuchen, Tee besprechen, Werkzeug ordnen und Wege über das Gelände erklären",
         "rooms": [("Eingangsgang", "Der kurze freie Eingangsgang verbindet die südliche Holzveranda durch das echte drei Meter hohe Portal mit der Wohnstube. Der Durchgang bleibt ohne Möbel, damit auch Hagrid sicher eintreten kann.", "indoor"),
                   ("Wohnstube", "Die behagliche Wohnstube wird von einem schweren Eichentisch und einem steinernen Herd bestimmt. Ein Regal enthält Bücher über magische Tiere. Die Türen zum Eingangsgang und zur Schlafnische bleiben frei.", "indoor"),
                   ("Schlafnische", "Hinter einem breiten Durchgang liegt Hagrids breites Bett mit einer grünen Wolldecke. Eine Schultruhe hält persönliche Dinge zusammen; dieser private Ruheplatz ist kein öffentlicher Treffpunkt.", "indoor")], "entry": "Eingangsgang"},
        {"key": "gate", "name": "Steintor und Schlosswiese", "pos": (170,-50),
         "boundary": rect(-25,-14,40,17), "indoor": "outdoor",
         "description": "Ein steinernes Tor mit offenem Durchgang markiert den Zugang zur Schlosswiese. Nach Norden steigt der Weg sanft zum südlichen Schlosseingang; westlich liegt Hagrids Hütte, südwestlich das Bootshaus. Niedrige Mauersockel, Rasen und Laternen geben der freien Fläche einen erkennbaren Maßstab. Hier begrüßt McGonagall erwachsene Gäste und erklärt die Hausordnung.",
         "activity": "Gäste begrüßen, Schulregeln erklären und den weiteren Weg wählen",
         "rooms": [("Torwiese", "Vor dem offenen Steintor ist genug trockener Platz, um anzuhalten. Bänke stehen seitlich des Wegs; die Mitte bleibt für Ankommende frei.", "outdoor")], "entry": "Torwiese"},
        {"key": "boathouse", "name": "Bootshaus am Nordufer", "pos": (85,-15),
         "boundary": rect(-9.5,-7.2,9.5,7.2), "asset": "boathouse", "indoor": "indoor",
         "description": "Das hölzerne und steinerne Bootshaus steht auf festem Grund am Nordufer. Seine zum Wasser gerichteten Tore sind offen; draußen ragt ein Steg nach Süden. Im geschützten Schuppen lagern Ruder, Seile und ein ruhendes Boot. Der tatsächliche Weg zum Schloss verläuft auf dem Land über das Steintor, nicht durch eine behauptete Bootsmechanik.",
         "activity": "Boote und Seile betrachten, Hagrids Arbeit kennenlernen und sicher am Ufer bleiben",
         "rooms": [("Bootsschuppen", "Der offene Bootsschuppen ist ein trockener Arbeitsraum mit breitem Tor zum südlichen Ufer. Ein ruhendes Ruderboot, Kisten und eine Laterne lassen die traditionelle Nutzung erkennen. Die mittlere Gasse zum Tor bleibt frei.", "indoor")], "entry": "Bootsschuppen"},
        {"key": "castle", "name": "Hogwarts Schloss", "pos": (170,-150),
         "boundary": rect(-cw/2,-cd/2,cw/2,cd/2), "asset": "hogwarts-castle", "indoor": "outdoor",
         "description": "Hogwarts erhebt sich mit großer Halle, kantigem Treppenturm, hohen Spitzdächern und ungleichen Türmen über dem nördlichen Seeufer. Sandstein, Strebepfeiler und schmale gotische Fenster geben dem Schloss seine vertraute Silhouette. Der südliche Torweg führt wirklich durch das offene Torhaus und den Kreuzgang in einen freien Innenhof. Diese Demo arbeitet Hof und Ankunftszonen aus; vollständige Schlossinnenräume und bewegliche Treppen werden nicht behauptet.",
         "activity": "durch das Torhaus eintreten, den Innenhof erkunden und sich zum Schuljahrsbeginn orientieren",
         "rooms": [("Torweg", "Der befestigte südliche Torweg läuft bei lokal x=30 durch den freien Torhausbogen. Seitlich stehen hohe Schlosswände, vor einem liegt der offene Durchgang zum Kreuzgang. Der Weg ist eine wirkliche offene Außenfläche, kein geschlossener Fantasieraum.", "outdoor"),
                   ("Südlicher Kreuzgang", "Unter dem südlichen Arkadenabschnitt verbindet eine freie Gasse den Torweg mit dem Hof. Sandsteinpfeiler rahmen den Blick auf Himmel und Türme; die Mitte bleibt unmöbliert und begehbar.", "outdoor"),
                   ("Offener Innenhof", "Im gepflasterten Innenhof stehen Bänke und ein paar sorgfältig geordnete Schultruhen am Rand. Der Himmel bleibt offen, die Mitte frei. Von hier erkennt man die große Halle im Westen und den Treppenturm im Nordwesten, ohne ein vollständiges Schlossinneres vorauszusetzen.", "outdoor")], "entry": "Torweg"},
    ]


def terrain_types():
    return {
        "hw_meadow": {"name": "Schottische Schlosswiese", "color": "#718452", "passable": True,
                      "speed_factor": 1, "surface": "", "meta": {"undergrowth": .18, "sway_m": .04}},
        "hw_heather": {"name": "Heide und Hochland", "color": "#807466", "passable": True,
                       "speed_factor": .8, "surface": "", "meta": {"undergrowth": .38, "sway_m": .07}},
        "hw_woodland": {"name": "Lichter Kiefernwald", "color": "#3d5943", "passable": True,
                        "speed_factor": .8, "surface": "", "meta": {"undergrowth": .40, "sway_m": .08}},
        "hw_gravel": {"name": "Trockener Kiesweg", "color": "#b4a48b", "passable": True,
                      "speed_factor": 1, "surface": "", "meta": {}},
        "hw_shore": {"name": "Kiesiges Seeufer", "color": "#9c9786", "passable": True,
                     "speed_factor": .85, "surface": "", "meta": {}},
        "hw_shallows": {"name": "Flacher Ufersaum", "color": "#627e83", "passable": False,
                        "speed_factor": .5, "surface": "", "meta": {"water": True, "water_depth_m": .6,
                         "shore_ramp_m": 8, "swim_from_m": 1}},
        "hw_lake": {"name": "Schwarzer See", "color": "#203e4b", "passable": False,
                    "speed_factor": .3, "surface": "", "meta": {"water": True, "water_depth_m": 9,
                     "shore_ramp_m": 20, "swim_from_m": 1}},
    }


def inside_polygon(x, z, polygon):
    inside = False
    for (ax,az),(bx,bz) in zip(polygon, polygon[1:] + polygon[:1]):
        if (az > z) != (bz > z) and x < (bx-ax)*(z-az)/(bz-az)+ax:
            inside = not inside
    return inside


def check_dry_geography(data):
    """Reject an accidental dry causeway before any world mutation."""
    water = [a["polygon"] for a in data["terrain_areas"] if a["kind"] in ("hw_shallows","hw_lake")]
    for location in data["locations"]:
        require(not any(inside_polygon(location["pos_x"],location["pos_z"],poly) for poly in water),
                f"Authored location pin is in water: {location['name']}")
        for x,z in location["boundary"]:
            require(not any(inside_polygon(location["pos_x"]+x,location["pos_z"]+z,poly) for poly in water),
                    f"Authored building boundary is in water: {location['name']}")
    for area in data["terrain_areas"]:
        stroke = area.get("stroke")
        if not stroke:
            continue
        for (ax,az),(bx,bz) in zip(stroke["points"],stroke["points"][1:]):
            length = math.hypot(bx-ax,bz-az)
            steps = max(1,math.ceil(length))
            nx,nz = (bz-az)/length,-(bx-ax)/length
            for i in range(steps+1):
                for side in (-.5,0,.5):
                    x = ax + (bx-ax)*i/steps + side*stroke["width_m"]*nx
                    z = az + (bz-az)*i/steps + side*stroke["width_m"]*nz
                    require(not any(inside_polygon(x,z,poly) for poly in water),
                            f"Authored dry path crosses the lake: {area['label']}")


def map_payload(places):
    lake = [[-390,140],[-285,-10],[-80,-60],[60,-20],[60,15],[110,25],[160,50],
            [260,240],[180,460],[-30,540],[-180,500],[-220,470],[-225,435],
            [-265,435],[-280,465],[-350,410],[-400,300]]
    inner = [[round(-60 + (x+60)*.88, 2), round(235 + (z-235)*.88, 2)] for x,z in lake]
    outer = [[round(-60 + (x+60)*1.04, 2), round(235 + (z-235)*1.04, 2)] for x,z in lake]
    def area(kind, label, poly, order):
        return {"kind": kind, "label": label, "polygon": poly, "z_order": order}
    areas = [
        area("hw_meadow", "Schlossland und Ankunftsgebiet", rect(-800,-500,700,900), 0),
        area("hw_heather", "Westliche Heidehänge", rect(-790,-400,-525,800), 1),
        area("hw_heather", "Östliche Hochlandhänge", rect(335,-340,690,780), 1),
        area("hw_woodland", "Kiefernwald am Westweg", [[-670,-110],[-520,-80],[-495,60],[-500,440],[-545,605],[-680,650]], 2),
        area("hw_woodland", "Wald oberhalb des Bahnhofs", rect(-535,460,-480,760), 2),
        area("hw_woodland", "Östliche Baumgruppen", [[320,65],[490,20],[595,380],[360,570],[290,430]], 2),
        area("hw_woodland", "Hagrids kleiner Hain", rect(-180,-205,-117,-80), 2),
        area("hw_shore", "Kiesufer des Schwarzen Sees", outer, 3),
        area("hw_shallows", "Flacher Saum des Schwarzen Sees", lake, 4),
        area("hw_lake", "Tiefes Wasser des Schwarzen Sees", inner, 5),
    ]
    paths = [
        ("Bahnhof zum südlichen Ufer", [[-440,570],[-440,515],[-360,495],[-300,495],[-245,470],[-245,455]], 5),
        ("Trockener Westuferweg", [[-440,570],[-470,490],[-470,385],[-455,220],[-445,100],[-400,45],[-340,-30],[-235,-85],[-90,-125]], 6),
        ("Hütte zum Steintor", [[-90,-125],[-30,-110],[50,-90],[125,-55],[170,-50]], 5),
        ("Bootshaus zum Steintor", [[85,-15],[100,-25],[130,-40],[170,-50]], 5),
        ("Schlossauffahrt", [[170,-50],[200,-65],[200,-75]], 7),
    ]
    for label, points, width in paths:
        areas.append({"kind": "hw_gravel", "label": label, "z_order": 6,
                      "stroke": {"points": points, "width_m": width, "style": "straight"}})
    areas.append(area("hw_gravel", "Trockener Stationsvorplatz", rect(-460,515,-400,625), 6))
    return {"summary": "Drei Ankunftsregionen: Hogsmeade im Süden, Schwarzer See mit trockenem Westuferweg, Hogwarts mit Hütte und Schlosswiese im Norden.",
            "bounds": {"min_x": -800, "min_z": -500, "max_x": 700, "max_z": 900},
            "terrain_areas": areas,
            "height_areas": [
                {"label": "Sanftes Schlossplateau", "polygon": rect(35,-300,340,-90), "height_m": 18, "falloff_m": 90},
                {"label": "Hagrids trockener Hügel", "polygon": rect(-185,-215,-40,-90), "height_m": 5, "falloff_m": 95},
                {"label": "Westliche schottische Hügel", "polygon": [[-790,-350],[-650,-410],[-565,-240],[-595,40],[-735,105]], "height_m": 43, "falloff_m": 125},
                {"label": "Östliche Hochlandkuppe", "polygon": [[425,-220],[615,-265],[680,-55],[560,90],[405,5]], "height_m": 46, "falloff_m": 145},
                {"label": "Südliche Heiderücken", "polygon": rect(-730,710,-260,850), "height_m": 24, "falloff_m": 120},
            ],
            "locations": [{"name": p["name"], "description": p["description"],
                           "pos_x": p["pos"][0], "pos_z": p["pos"][1], "yaw_deg": 0,
                           "boundary": p["boundary"], "indoor": p["indoor"], "danger_level": 0}
                          for p in places]}


def location_payload(spec):
    english = {
        "station": "rural Scottish sandstone railway station, green and cream trim, gabled canopy, stationary crimson steam train, long gravel platform",
        "south": "dry gravel promontory at a Scottish black lake, wooden landing stage and moored rowing boats, distant gothic castle",
        "shore": "dry western lakeside gravel trail through Scots pines and heather, timber resting bench, distant castle towers",
        "hut": "small rough stone Scottish gamekeeper cottage, slate roof, chimney and southern timber porch",
        "gate": "open stone gateway on the grassy grounds of a Scottish gothic castle, low stone walls and gravel paths",
        "boathouse": "Scottish lakeside timber and stone boat shed on dry northern shore, open water-facing doors, wooden jetty",
        "castle": "asymmetric Scottish gothic castle of warm sandstone, great hall, grand staircase tower, astronomy towers, slate roofs and open paved courtyard",
    }[spec["key"]]
    return {"name": spec["name"], "description": spec["description"], "danger_level": 0,
            "indoor": spec["indoor"], "decency": "public", "swim_allowed": False,
            "style_hint": "Schottischer Sandstein, Schiefer, patiniertes Holz; sichere Ankunft im frühen Herbst",
            "activity_hint": spec["activity"],
            "image_prompt_day": english + ", late afternoon in early autumn, no people, no text",
            "image_prompt_night": english + ", cool autumn night, warm lanterns, no people, no text",
            "image_prompt_building": english + ", complete structure from outside, no people, no text",
            "rooms": [{"name": name, "description": description, "indoor": indoor,
                       "decency": "private" if name == "Schlafnische" else "public",
                       "swim_allowed": False, "activity_hint": spec["activity"],
                       "style_hint": "Sandstein und dunkles Holz, frühes schottisches Herbstlicht",
                       "image_prompt_day": english + ", quiet " + ("interior" if indoor == "indoor" else "outdoor gathering area") + ", afternoon, no people, no text",
                       "image_prompt_night": english + ", lantern lit at night, no people, no text"}
                      for name, description, indoor in spec["rooms"]]}


def location_index(client):
    rows = client.get("/world/locations")["locations"]
    result = {}
    for row in rows:
        require(row["name"] not in result, "Duplicate location names found; no replay allowed")
        result[row["name"]] = row
    return result


def room_id(location, name):
    matches = [room["id"] for room in location["rooms"] if room["name"] == name]
    require(len(matches) == 1, f"Room identity not unique: {location['name']} / {name}")
    return matches[0]


def furnishing(prop_ids, logical, x, z, yaw=0, *, label=None, offset=0):
    return {"prop_id": prop_ids[logical], "at": [x,z], "yaw": yaw,
            "offset_y": offset, "label": label or logical}


def layout_payload(spec, location, prop_ids):
    def prop(key, x, z, yaw=0, **kwargs):
        return furnishing(prop_ids, key, x,z,yaw, **kwargs)
    def opening(edge, target, width=1.2, at=.5, height=2.3):
        return {"edge": edge, "at": at, "width_m": width, "height_m": height,
                "sill_m": 0, "type": "door", "to": target}
    def room(name, x,z,w,d, *, outdoor=False, props=None, openings=None, outline=None, floor_y=0):
        result = {"id": room_id(location,name), "x": x, "y": z, "w": w, "d": d,
                  "level": 0, "props": props or [], "openings": openings or []}
        result["outline"] = outline if outline is not None else [[0,0],[w,0],[w,d],[0,d]]
        if floor_y:
            result["floor_offset_y"] = floor_y
        if outdoor:
            result["always_visible"] = True
            result["no_walls"] = True
        return result
    key = spec["key"]
    rooms, boundary = [], []
    if key == "castle":
        # Exact asset-author contract: x25..35,z13..75 is open through gatehouse;
        # quad x8..52,z-34..0 is unobstructed. Do not wall an outdoor passage.
        rooms = [
            room("Torweg",25,13,10,62,outdoor=True, props=[prop("lantern",1.1,49),prop("lantern",8.9,49)]),
            room("Südlicher Kreuzgang",25,1,10,12,outdoor=True),
            room("Offener Innenhof",8,-34,44,34,outdoor=True,floor_y=.10,props=[
                prop("bench",5,4),prop("bench",39,4,180),prop("bench",5,29),prop("bench",39,29,180),
                prop("school-trunk",4,13),prop("school-trunk",4,15),prop("lantern",39,17)])]
        x0, x1 = spec["boundary"][0][0], spec["boundary"][1][0]
        boundary = [{"edge": 2, "at": (x1-30)/(x1-x0), "width_m": 8,
                     "room": room_id(location,"Torweg")}]
    elif key == "hut":
        living, sleeping = room_id(location,"Wohnstube"), room_id(location,"Schlafnische")
        entrance = room_id(location,"Eingangsgang")
        # Three genuine rectangular zones follow the hollow shell: two interior
        # rooms and the separate south connector to the centered open portal.
        # Shared edges do not make any pair of their bounding boxes overlap.
        rooms = [
            room("Eingangsgang",-.85,1.6,1.7,2.77814-1.6,floor_y=.08,
                 openings=[opening(2,"outside",1.7,height=3.0),
                           opening(0,living,.9,at=.475/1.7,height=3.0)]),
            room("Wohnstube",-2.2,-2.4,2.3,4,floor_y=.08,
                 props=[prop("cottage-table",1.15,2.0),prop("oak-chair",1.15,3.0,180),
                        prop("hearth",.40,.82,90),prop("bookcase",1.5,.25),prop("lantern",.3,3.5)],
                 openings=[opening(2,entrance,.9,at=.475/2.3,height=3.0),
                           opening(1,sleeping,1.2,at=.825,height=3.0)]),
            room("Schlafnische",.1,-2.4,2.1,4,floor_y=.08,
                 props=[prop("cottage-bed",1.05,1.3),prop("school-trunk",1.1,3.55),
                        prop("lantern",1.9,3.75)],
                 openings=[opening(3,living,1.2,at=.175,height=3.0)])]
        boundary = [{"edge":2,"at":.5,"width_m":1.7,"room":entrance}]
    elif key == "station":
        waiting, office = room_id(location,"Wartesaal"), room_id(location,"Fahrkartenbüro")
        rooms = [
            room("Bahnsteig",-18,-47,46,94,outdoor=True,
                 outline=[[35,0],[46,0],[46,94],[0,94],[0,50],[35,50]],
                 props=[prop("bench",37.3,14,90),prop("bench",37.3,36,90),
                        prop("bench",37.3,70,90),prop("bench",9,57),
                        prop("luggage",39,32),prop("luggage",6,60),
                        prop("lantern",36.1,8),prop("lantern",36.1,85),prop("signpost",41,4)]),
            room("Wartesaal",-14.9,-4.48,14.9,6.75,floor_y=.30,
                 props=[prop("bench",3,1.1),prop("bench",3,5.5,180),
                        prop("luggage",12.9,1.2),prop("lantern",.4,3.3)],
                 openings=[opening(2,"outside",1.5,at=4.6/14.9), opening(1,office,1.2)]),
            room("Fahrkartenbüro",0,-4.48,14.9,6.75,floor_y=.30,
                 props=[prop("writing-desk",9,2.4),prop("oak-chair",9,1.25),
                        prop("bookcase",13,.35),prop("school-trunk",12,5.5)],
                 openings=[opening(3,waiting,1.2),opening(2,"outside",1.5,at=10.3/14.9)])]
        boundary = [{"edge":2,"at":(41-20)/82,"width_m":6,"room":room_id(location,"Bahnsteig")}]
    elif key == "boathouse":
        rid = room_id(location,"Bootsschuppen")
        rooms = [room("Bootsschuppen",-8,-5.95,16,10,floor_y=.36,
                 props=[prop("rowboat",3.2,2.0,90),prop("school-trunk",13.8,2),
                        prop("luggage",13.8,4),prop("lantern",15.2,7.5)],
                 openings=[opening(2,"outside",5.0,at=.275),opening(2,"outside",5.0,at=.725)])]
        boundary = [{"edge":2,"at":(9.5-3.6)/19,"width_m":5,"room":rid},
                    {"edge":2,"at":(9.5+3.6)/19,"width_m":5,"room":rid}]
    else:
        name = spec["entry"]
        x0,z0 = spec["boundary"][0]
        x1,z1 = spec["boundary"][2]
        w,d = x1-x0,z1-z0
        props = [prop("bench",4,5),prop("lantern",2,5),prop("signpost",w-3,d-4)]
        if key == "south":
            props += [prop("luggage",5,d-5)]
        if key == "gate":
            props += [prop("bench",w-5,5,180)]
        rooms = [room(name,x0,z0,w,d,outdoor=True,props=props)]
    return {"summary": "Erdgeschossige, erreichbare Ankunftszonen mit freien Wegen und eigenen Möbeln.",
            "entry_room": room_id(location,spec["entry"]), "rooms": rooms,
            "boundary_openings": boundary, "stairs": []}


def add_props(client, assets):
    ids = {}
    categories = {"pine":"vegetation", "broadleaf":"vegetation", "hogwarts-express":"vehicle",
                  "rowboat":"vehicle", "jetty":"structure", "stone-gate":"structure"}
    for logical, spec in assets.items():
        if spec["kind"] != "prop":
            continue
        response = client.post("/world/props", {
            "name": spec.get("name", logical.replace("-", " ").title()),
            "category": spec.get("category", categories.get(logical,"decoration")),
            "width_m": spec["width_m"], "depth_m": spec["depth_m"], "height_m": spec["height_m"],
            "mount": "floor", "description": spec["description"], "tags": ["hogwarts-demo", "self-authored"]})
        pid = response["prop"]["id"]
        require(isinstance(pid,str) and pid, "Missing server prop ID")
        ids[logical] = pid
        client.upload(f"/world/props/{pid}/variants/0/upload", spec["path"], tier="full")
        detail = client.get(f"/world/props/{pid}")["prop"]
        require(detail["id"] == pid, f"Prop readback mismatch: {logical}")
        variants = client.get(f"/world/props/{pid}/variants")["variants"]
        require(any(v.get("index") == 0 and v.get("has_model") for v in variants),
                f"Prop variant model did not persist: {logical}")
    return ids


def decorate_terrain(client, prop_ids):
    areas = client.get("/world/terrain-areas")["areas"]
    edits = []
    groves = {"Kiefernwald am Westweg": (.11, "pine"),
              "Wald oberhalb des Bahnhofs": (.10, "pine"),
              "Östliche Baumgruppen": (.09, "broadleaf"),
              "Hagrids kleiner Hain": (.15, "broadleaf")}
    for area in areas:
        meta = copy.deepcopy(area.get("meta") or {})
        label = meta.get("label", "")
        if label not in groves and area["kind"] not in ("hw_lake", "hw_shallows"):
            continue
        meta.pop("water_level_effective",None)
        meta.pop("water_profile",None)
        if label in groves:
            density, tree = groves[label]
            meta["scatter"] = [{"density_per_100m2": density, "min_spacing_m": 9,
                                "model": f"/assets/props/{prop_ids[tree]}/model"}]
        if area["kind"] in ("hw_lake", "hw_shallows"):
            meta["water_level"] = 0
            meta["water_depth_m"] = 9 if area["kind"] == "hw_lake" else .6
            meta["shore_ramp_m"] = 20 if area["kind"] == "hw_lake" else 8
        edits.append({"id": area["id"], "kind": area["kind"], "polygon": area["polygon"],
                      "z_order": area["z_order"], "meta": meta})
    require(len(edits) == len(groves)+2, "Terrain label/readback contract failed")
    result = client.put("/world/terrain-areas/bulk", {"upserts": edits,"deletes":[]})
    require(len(result["saved"]) == len(edits), "Incomplete terrain bulk save")
    readback = client.get("/world/terrain-areas")["areas"]
    require(sum(bool((a.get("meta") or {}).get("scatter")) for a in readback) == len(groves),
            "Vegetation scatter did not persist")


def outdoor_props(client, prop_ids):
    # Docks sit at the authored bank cutouts, not at location pins in deep water.
    placements = [
        ("hogwarts-express",-408,570,0,0), ("stone-gate",170,-50,0,0),
        ("jetty",-245,436,0,.10), ("rowboat",-237,437,0,.08),
        ("rowboat",-253,437,0,.08), ("jetty",85,26,0,.10),
        ("rowboat",92,27,0,.08), ("bench",-270,480,25,0),
        ("lantern",-447,515,0,0), ("lantern",-360,492,0,0),
        ("lantern",-469,390,0,0), ("lantern",-449,110,0,0),
        ("lantern",-340,-31,0,0), ("lantern",-25,-108,0,0),
        ("lantern",120,-55,0,0), ("lantern",194,-72,0,0),
        ("signpost",-440,510,0,0), ("signpost",-342,-31,0,0),
        ("signpost",104,-27,0,0), ("signpost",180,-47,0,0),
    ]
    # Hand-placed near-field trees frame the regions; terrain scatter fills groves.
    placements += [("pine",x,z,angle,0) for x,z,angle in [
        (-468,540,12),(-465,600,140),(-425,640,65),(-315,490,26),
        (-281,448,80),(-458,300,15),(-470,160,110),(-392,25,70),
        (-198,-106,40),(-151,-60,120),(67,-57,30),(310,-100,80)]]
    placements += [("broadleaf",x,z,angle,0) for x,z,angle in [
        (-112,-95,30),(-65,-154,110),(126,-90,45),(233,-55,70),
        (122,2,25),(-281,492,75)]]
    upserts = [{"temp_id": f"outdoor-{i}", "prop_id": prop_ids[key], "x":x, "z":z,
                "yaw_deg":yaw, "offset_y":offset, "variant":0}
               for i,(key,x,z,yaw,offset) in enumerate(placements)]
    result = client.put("/world/world-props/bulk", {"upserts":upserts,"deletes":[]})
    require(len(result["saved"]) == len(upserts), "Outdoor bulk placement incomplete")
    require(all(row.get("world_prop",{}).get("id") for row in result["saved"]),
            "Outdoor placement server IDs missing")
    rows = client.get("/world/world-props")["world_props"]
    require(len(rows) == len(upserts) and all(not row.get("missing") for row in rows),
            "Outdoor prop readback has missing models or placements")


def cast_specs():
    return [
        {"name":"Rubeus Hagrid", "gender":"male", "age":63, "height":260,
         "home":"hut", "room":"Wohnstube", "start":"hut", "start_room":"Wohnstube",
         "role":"Wildhüter, Hüttenbewohner und freundlicher Wegführer", "chat":"rp_first",
         "body":"Ein sehr großer, breitschultriger erwachsener Mann mit wettergegerbter heller Haut, kräftigen Händen, langem dunklem lockigem Haar und einem dichten langen Bart. Warmherziger Blick, vorsichtige Bewegungen; eigenständige Gestaltung ohne Schauspielerähnlichkeit.",
         "face":"Erwachsenes breites Gesicht, freundliche dunkle Augen, wettergegerbte Haut, lange dunkle Locken und dichter Bart; keine Ähnlichkeit mit einem realen Schauspieler.",
         "nature":"Du bist herzlich, praktisch und loyal. Deine gewaltige Erscheinung macht dich manchmal verlegen; gerade deshalb bewegst du dich behutsam und lässt anderen Zeit. Begeisterung für magische Tiere darf nie die Sicherheit von Gästen verdrängen.",
         "presence":"Deine tiefe Stimme und dein dichter Bart fallen zuerst auf. Du kniest dich lieber zu einem abgestellten Koffer als ihn jemandem ungefragt wegzunehmen. In deiner Hütte riecht es nach Holz und Tee; du bietest einen Sitzplatz an und hörst zu.",
         "tasks":"Halte die Hütte und ihre Wege in Ordnung, begrüße Gäste, erkläre den trockenen Westuferweg und begleite sie nur mit Zustimmung. Am Bootshaus kennst du Seile, Ruder und die Tradition der Überfahrt; die dekorativen Boote dieser Demo bedienst du nicht als erfundene Spielfunktion.",
         "beliefs":"Freundlichkeit ist wichtiger als gesellschaftlicher Rang. Magische Tiere verdienen Respekt und Abstand. McGonagalls klare Regeln schützen die Schule; du behandelst ihre Entscheidungen nicht als Einladung zum heimlichen Umgehen.",
         "lessons":"Gute Absichten ersetzen keine Vorsicht. Du hast gelernt, Fremde nicht mit Fachwissen zu überrollen und ein Nein sofort zu respektieren. Was du nicht weißt, gibst du offen zu, statt einen verborgenen Raum oder eine Funktion zu erfinden.",
         "goals":"Am ersten Abend sollen Ankommende warm, orientiert und sicher sein. Zeige Johanna auf Wunsch den Hof und erkläre, wie sich das Schloss in den schottischen Hang einfügt. Räume später deine Werkzeuge und das Stationsgepäck ordentlich weg.",
         "soul":"Dein Zuhause ist die Hütte westlich von Hogwarts. Minerva McGonagall kennst du als strenge, verlässliche Kollegin, Elspeth Rowan als Stationsvorsteherin. Johanna Falk ist eine erwachsene Restauratorin und heute neu hier. Du kennst Bahnhof, beide Uferstellen, Westweg, Tor und Hof, aber keine nicht ausgearbeiteten Innenräume.",
         "palette":((104,77,48),(65,45,30)), "outfit":"Hagrids Arbeitskleidung",
         "clothes":[("underwear_top","Hagrids Unterhemd","cream cotton undershirt"),
                    ("underwear_bottom","Hagrids Unterhose","plain cotton boxer shorts"),
                    ("top","Hagrids Wollhemd","brown checked long-sleeved wool shirt"),
                    ("bottom","Hagrids Arbeitshose","dark brown heavy work trousers"),
                    ("feet","Hagrids Lederstiefel","large weathered brown leather work boots"),
                    ("outer","Hagrids Mantel","long patched dark umber wool coat")],
         "items":[("Hagrids Hüttenbund","key","Ein schwerer eigener Schlüsselbund für Hagrids Hütte; keine erfundene automatische Schließmechanik."),
                  ("Wildhüter-Notizbuch","tool","Hagrids Notizen zu Wegen, Wetter und Tierbeobachtungen am See.")]},
        {"name":"Minerva McGonagall", "gender":"female", "age":56, "height":174,
         "home":"castle", "room":"Offener Innenhof", "start":"gate", "start_room":"Torwiese",
         "role":"Professorin und verantwortliche Gastgeberin", "chat":"",
         "body":"Eine aufrecht stehende erwachsene Frau mit schmalem, reifem Gesicht, heller Haut, grauen Augen und dunklem, von einzelnen grauen Strähnen durchzogenem Haar in einem straffen Knoten. Präzise Haltung, ruhige Hände; eigenständige Gesichtsgestaltung, keine Schauspielerähnlichkeit.",
         "face":"Reifes schmales Gesicht, graue Augen hinter einer feinen rechteckigen Brille, straffer dunkler Haarknoten mit grauen Strähnen, würdevoller wacher Ausdruck; originelles Gesicht.",
         "nature":"Du bist diszipliniert, gerecht und aufmerksam. Deine knappe Sprache wirkt zunächst streng, aber du bemerkst Unsicherheit und erklärst Regeln geduldig. Du beschämst niemanden und belohnst ehrliche Fragen mit klaren Antworten.",
         "presence":"Du stehst aufrecht und beobachtest, bevor du sprichst. Kleine Gesten und eine trockene Bemerkung tragen mehr als lautes Auftreten. Begrüße Johanna als erwachsene Fachfrau, nicht als Schülerin, und erläutere den Anlass ihres Besuchs.",
         "tasks":"Empfange Gäste auf der Torwiese, halte den Zugang zum Hof frei und erkläre höflich die Sicherheits- und Hausregeln. Besprich mit Johanna die sichtbaren Sandsteinfassaden, Dächer und den offenen Hof. Behaupte keine vollständigen Schlossinnenräume oder beweglichen Treppenfunktionen.",
         "beliefs":"Würde und Sicherheit gelten für jeden Gast. Regeln müssen begründet werden können. Hagrids Wärme und seine Ortskenntnis ergänzen deine Ordnung; Elspeths zuverlässige Stationsarbeit ist wichtig für einen ruhigen Schuljahrsbeginn.",
         "lessons":"Strenge ohne Zuhören verfehlt ihren Zweck. Erwachsenengäste brauchen andere Erklärungen als Kinder. Bei Unklarheiten beschreibst du nur tatsächlich vorhandene Wege und Gegenstände und versprichst keine technische Magie.",
         "goals":"Führe einen ruhigen, freundlichen Schuljahrsbeginn herbei. Johanna soll die begehbaren Ankunftszonen und ihre Grenzen verstehen. Sorge dafür, dass Gepäck nicht vor Türen liegt und niemand am kalten See unnötige Risiken eingeht.",
         "soul":"Du bist Professorin an Hogwarts und heute Ansprechpartnerin für Gäste. Hagrid ist dein langjähriger Kollege, Elspeth Rowan eine respektierte Stationsvorsteherin. Johanna Falk ist zur Besichtigung historischer Steinoberflächen eingeladen, nicht deine Schülerin. Deine ausgearbeiteten Aufenthaltsorte sind Torwiese und Hof.",
         "palette":((25,69,52),(53,51,47)), "outfit":"McGonagalls Tagesrobe",
         "clothes":[("underwear_top","Minervas Unterhemd","plain ivory cotton camisole"),
                    ("underwear_bottom","Minervas Unterwäsche","plain full coverage cotton briefs"),
                    ("top","Minervas hochgeschlossene Bluse","high-necked ivory blouse with long sleeves"),
                    ("bottom","Minervas langer Rock","ankle-length charcoal wool skirt"),
                    ("feet","Minervas Schnürstiefel","closed black leather lace-up ankle boots"),
                    ("outer","Minervas grüne Robe","long forest green academic robe"),
                    ("head","Minervas Spitzhut","plain dark green pointed academic hat")],
         "items":[("Minervas Empfangsliste","tool","Die Gästeliste für den Schuljahrsbeginn mit Johanna Falks Besuchstermin."),
                  ("Minervas eigener Zauberstab","tool","Ein schlichter persönlicher Zauberstab; kein Ersatz für nicht implementierte Mechaniken.")]},
        {"name":"Elspeth Rowan", "gender":"female", "age":47, "height":168,
         "home":"station", "room":"Fahrkartenbüro", "start":"station", "start_room":"Fahrkartenbüro",
         "role":"Stationsvorsteherin von Hogsmeade", "chat":"rp_first",
         "body":"Eine erwachsene schottische Frau mit kräftiger alltagstauglicher Statur, sommersprossiger heller Haut, haselbraunen Augen und kupferrotem, bereits leicht ergrautem Haar in einem lockeren Knoten. Freundliches reifes Gesicht und wetterfeste Haltung; vollständig originale Person.",
         "face":"Eigenständiges reifes Gesicht mit Sommersprossen, haselbraunen Augen, kupferrotem Haar mit silbernen Strähnen, freundlich entschlossener Mund.",
         "nature":"Du bist zuverlässig, humorvoll und unaufgeregt. Du merkst dir Menschen und die Koffer, die sie tragen, ohne neugierig in Privates einzudringen. Unter Zeitdruck sprichst du noch klarer statt lauter.",
         "presence":"Du begrüßt Ankommende mit einem kurzen Nicken und bietest konkrete Hilfe an. Dein Blick wandert zuerst zur sicheren Bahnsteigkante und zu freistehenden Gepäckstücken. Erkläre Entfernungen in Schritten und Wegpunkten, nicht in mysteriösen Abkürzungen.",
         "tasks":"Betreue Bahnhof, Wartesaal und Büro. Hilf Johanna beim Orientieren, notiere Fundsachen und zeige den nördlichen Waldweg. Sage ausdrücklich, dass der Express in dieser Demo stillsteht und dass der trockene Westuferweg alle Regionen verbindet.",
         "beliefs":"Pünktlichkeit ist eine Form von Rücksicht, aber kein Grund, jemanden zurückzulassen. Ein klarer Wegweiser hilft mehr als große Worte. Du respektierst McGonagalls Schulregeln und Hagrids Ortskenntnis.",
         "lessons":"Nasse Steine am See sind kein geeigneter Weg für jemanden mit Koffern. Frage, ob Hilfe erwünscht ist, bevor du Gepäck nimmst. Versprich weder einen bald abfahrenden Zug noch eine spielbare Bootsüberfahrt.",
         "goals":"Alle neuen Gäste sollen vor Einbruch der Dunkelheit wissen, wo sie sind. Erkläre Johanna Bahnhof, südliche Anlegestelle und den sicheren Landweg. Schließe den Tag mit einem ordentlichen Wartesaal und einem vollständigen Stationsbuch ab.",
         "soul":"Du bist eine originale 47-jährige Stationsvorsteherin aus der Gegend. McGonagall kennst du beruflich, Hagrid von vielen ruhigen Ankunftstagen. Johanna Falk triffst du heute zum ersten Mal und kennst nur ihre Einladung. Dein Wissen umfasst Bahnhof, Südsteg und den beschilderten Westuferweg; zu Schlossarchiven erfindest du keine Details.",
         "palette":((43,78,65),(141,76,46)), "outfit":"Elspeths Stationsuniform",
         "clothes":[("underwear_top","Elspeths Unterhemd","plain cream cotton undershirt"),
                    ("underwear_bottom","Elspeths Unterwäsche","plain full coverage cotton briefs"),
                    ("top","Elspeths Uniformhemd","cream collared long-sleeved station shirt"),
                    ("bottom","Elspeths Uniformhose","dark green tailored work trousers"),
                    ("feet","Elspeths Arbeitsschuhe","closed polished dark brown leather shoes"),
                    ("outer","Elspeths Stationsjacke","dark green practical station jacket with brass buttons"),
                    ("head","Elspeths Schirmmütze","dark green railway peaked cap without a commercial logo")],
         "items":[("Hogsmeader Stationsbuch","tool","Elspeths eigenes Buch für Auskünfte, Fundsachen und Ankunftsnotizen."),
                  ("Elspeths Messingpfeife","tool","Eine kleine Messingpfeife an einer Kordel; nur ein persönliches Stationsutensil.")]},
        {"name":"Johanna Falk", "gender":"female", "age":32, "height":172,
         "home":"station", "room":"Wartesaal", "start":"station", "start_room":"Bahnsteig",
         "role":"Eingeladene erwachsene Restauratorin und Besucheravatar", "chat":"",
         "body":"Eine erwachsene Frau mit mittlerem Körperbau, warm olivfarbener Haut, braunen Augen und kinnlangem dunkelbraunem welligem Haar. Reifes offenes Gesicht, kleine Lachfalten und neugierige, ruhige Haltung; vollständig originelles Aussehen.",
         "face":"Originales Gesicht einer 32-jährigen Frau mit warm olivfarbener Haut, braunen Augen, dunklem welligem kinnlangem Haar und dezenten Lachfalten.",
         "nature":"Du bist neugierig, sorgfältig und respektvoll. Als erwachsene Restauratorin interessierst du dich für Material, Handwerk und Geschichte, nicht für gefährliche Mutproben. Du stellst konkrete Fragen und akzeptierst Grenzen.",
         "presence":"Du beobachtest Steinoberflächen und Holzverbindungen mit geübtem Blick. Deine ruhige Gesprächsweise macht aus Unsicherheit eine ehrliche Frage. Als Spieleravatar bleiben Entscheidungen bei der spielenden Person; erzwinge weder Ziel noch Handlung.",
         "tasks":"Komme am Bahnhof an, orientiere dich mit Elspeths Hilfe und besuche nach eigener Wahl Ufer, Hagrid und den Schlosshof. Zeige deine Einladung, bevor du Arbeitsräume beanspruchst. Notiere sichtbare Fassadendetails, ohne Gegenstände mitzunehmen.",
         "beliefs":"Historische Orte leben von Menschen und sorgfältiger Pflege. Eigentum und persönliche Grenzen sind zu achten. Fachwissen bedeutet auch, eine unbekannte magische Konstruktion nicht ungefragt anzufassen.",
         "lessons":"Du hast aus früheren Projekten gelernt, erst zu fragen, dann zu messen. Ein langer trockener Weg ist einem riskanten Abkürzungsversuch vorzuziehen. Der Ausstellungszug und die festliegenden Boote sind keine benutzbaren Transportmittel.",
         "goals":"Lerne Hogwarts als erwachsene Gästin kennen und besprich mit McGonagall die zugänglichen Ankunftszonen. Finde einen eigenen Eindruck vom See und den Sandsteinbauten. Die Reihenfolge entscheidet die spielende Person.",
         "soul":"Du bist Johanna Falk, eine 32-jährige selbstständige Restauratorin und heute erstmals in Hogsmeade. McGonagall hat dich zur Sichtung des zugänglichen Hofmauerwerks eingeladen; ihr kennt euch bisher aus Briefen. Hagrid und Elspeth kennst du anfangs nur dem Namen nach. Der Wartesaal ist dein vorläufiger Treffpunkt, keine erfundene dauerhafte Wohnung. Eine einfache Ankunftsskizze gibt dir Kenntnis des beschilderten Geländes, nicht seiner Geheimnisse.",
         "palette":((69,88,105),(54,41,35)), "outfit":"Johannas wetterfeste Reisekleidung",
         "clothes":[("underwear_top","Johannas Unterhemd","plain grey cotton camisole"),
                    ("underwear_bottom","Johannas Unterwäsche","plain full coverage cotton briefs"),
                    ("top","Johannas Wollpullover","oatmeal long-sleeved wool sweater"),
                    ("bottom","Johannas Reisehose","dark charcoal practical travel trousers"),
                    ("feet","Johannas Wanderstiefel","closed brown leather walking boots"),
                    ("outer","Johannas Regenmantel","knee-length muted blue waxed travel coat")],
         "items":[("Johannas Einladung nach Hogwarts","quest","Ein höflicher Brief McGonagalls an die erwachsene Restauratorin Johanna Falk zur Besichtigung des zugänglichen Hofmauerwerks."),
                  ("Johannas Skizzenbuch","tool","Ein persönliches Skizzenbuch für Steinprofile, Dachlinien und eigene Reisebeobachtungen."),
                  ("Ankunftsskizze des Schulgeländes","tool","Johannas einfache eigene Wegskizze: Bahnhof, Südufer, trockener Westuferweg, Hütte, Tor, Bootshaus und Hof.")]},
    ]


def character_payload(spec):
    rules = (f"Du verkörperst {spec['name']}, eine eindeutig erwachsene Person. Sprich Deutsch; "
             "schreibe natürliche, präzise Dialoge und erfinde keine Spielerentscheidungen. "
             "Respektiere Zustimmung, Eigentum und alle SFW-Grenzen. Keine Sexualisierung, "
             "keine Entkleidung, keine explizite Gewalt. Beschreibe nur vorhandene Orte und "
             "unterstützte Handlungen. Zug und Boote sind dekorativ; nutze für tatsächliche "
             "Ortswechsel die trockenen Wege. Behaupte weder eine Fahrt noch die Ausführung "
             "einer nicht verfügbaren Fähigkeit. Beziehungen sind Wissen, kein Allwissen.")
    sections = {key: f"# {heading}\n\n{rules if key == 'roleplay_rules' else spec['nature' if key == 'personality' else key]}\n"
                for key, heading in SOUL_HEADINGS.items()}
    return {"character_name":spec["name"],"template":"human-roleplay", "language":"de",
            "gender":spec["gender"],"age":spec["age"],"height":spec["height"],
            "dialogue_style":"Deutsch, warm und konkret; " + spec["role"],
            "character_appearance":spec["body"],"face_appearance":spec["face"],
            "popularity":65,"trustworthiness":90,"social_dialog_probability":35,
            "_extra_soul_md":sections,
            "outfits":[{"name":spec["outfit"],"locations":[],"activities":[],"excluded_locations":[],
                        "pieces":[{"slots":[slot],"name":name,"prompt_fragment":prompt}
                                  for slot,name,prompt in spec["clothes"]]}]}


def paint_portrait(path: Path, spec):
    """Own flat-color bookplate art, not an actor photo or a fake generated image."""
    w,h = 384,512
    pixels = bytearray(w*h*3)
    coat,hair = spec["palette"]
    skin = (192,147,111) if spec["name"] == "Johanna Falk" else (218,176,141)
    for y in range(h):
        for x in range(w):
            noise = ((x*13 + y*7) % 9)-4
            c = (max(0,205-y//10+noise),max(0,211-y//12+noise),max(0,191-y//15+noise))
            i = 3*(y*w+x)
            pixels[i:i+3] = bytes(c)
    def ellipse(cx,cy,rx,ry,c):
        for y in range(max(0,int(cy-ry)),min(h,int(cy+ry)+1)):
            for x in range(max(0,int(cx-rx)),min(w,int(cx+rx)+1)):
                if ((x-cx)/rx)**2+((y-cy)/ry)**2 <= 1:
                    i=3*(y*w+x); pixels[i:i+3]=bytes(c)
    def line(x0,y0,x1,y1,c,thickness=2):
        steps=max(abs(x1-x0),abs(y1-y0),1)
        for step in range(steps+1):
            t=step/steps
            ellipse(round(x0+(x1-x0)*t),round(y0+(y1-y0)*t),thickness,thickness,c)
    # Lake and castle bookplate framing is our own geometric ornament.
    for x,y,rx,ry in ((56,117,23,55),(326,130,26,66),(75,164,42,28),(308,179,42,27)):
        ellipse(x,y,rx,ry,(143,157,146))
    ellipse(192,480,155,143,coat)
    ellipse(192,323,35,43,skin)
    ellipse(192,205,87,114,hair)
    ellipse(192,221,64,91,skin)
    ellipse(192,144,74,34,hair)
    if spec["name"] == "Rubeus Hagrid":
        ellipse(192,287,79,87,hair)
        ellipse(192,244,42,22,skin)
        for x in range(142,246,15):
            line(x,280,x+8,345,(91,65,43),2)
    if spec["name"] == "Minerva McGonagall":
        ellipse(260,154,24,34,hair)
        for x in (163,221):
            ellipse(x,216,26,18,(83,85,74)); ellipse(x,216,23,15,skin)
        line(187,214,197,214,(75,77,68),2)
        line(149,264,175,266,(167,127,107),1)
        line(208,266,233,264,(167,127,107),1)
    for x in (165,219):
        ellipse(x,217,6,4,(49,52,44))
        line(x-12,204,x+11,202,hair,2)
    line(193,225,185,249,(165,117,86),2)
    line(177,274,207,274,(124,79,64),2)
    line(156,351,190,397,(204,198,169),4)
    line(228,351,194,397,(204,198,169),4)
    line(192,402,192,505,tuple(max(0,c-28) for c in coat),2)
    for y in (419,453,487):
        ellipse(211,y,4,4,(186,153,85))
    path.write_bytes(png_bytes(w,h,pixels))


def configure_skills(client, name):
    root = "/characters/" + urllib.parse.quote(name,safe="")
    available = client.get(root + "/skills/available")["skills"]
    skills = {row["skill_id"]:row for row in available}
    required = {"act","setlocation","go_to_character","talk_to","outfit_change",
                "consume_item","interact","send_message","notify_user",
                "invite_to_party","join_party","leave_party"}
    require(required.issubset(skills), f"{name}: required standard character skills missing")
    # Turn OFF every inherited nonessential skill, notably render/network and
    # intimacy skills. No optional/private skill package is needed by this cast.
    enabled = required | ({"sleep","wakeup"} & skills.keys())
    for skill_id,row in skills.items():
        desired = skill_id in enabled
        require(not desired or not row.get("blocked_reason"),
                f"{name}: standard skill dependency is blocked: {skill_id}")
        if bool(row.get("enabled")) != desired:
            client.put(root + "/skills/" + urllib.parse.quote(skill_id,safe="") + "/enabled",
                       {"enabled":desired})
    readback = client.get(root + "/skills/available")["skills"]
    require({row["skill_id"] for row in readback if row.get("enabled")} == enabled,
            f"{name}: skill enable/disable readback mismatch")


def author_characters(client, places, generated):
    cast = cast_specs()
    ids = [location["id"] for location in places.values()]
    for spec in cast:
        payload = {"json":character_payload(spec),"type_hint":"character"}
        client.post("/world-dev/preview-json",payload)
        client.post("/world-dev/apply-json",payload)
        root = "/characters/" + urllib.parse.quote(spec["name"],safe="")
        client.post(root + "/config",{"fields":{"chat_mode":spec["chat"],"importance":2,
                    "roles":spec["role"],"romantic_interests":"", "avatar_only_presence":"false"}})
        home,start = places[spec["home"]],places[spec["start"]]
        client.post(root + "/home-location",{"home_location":home["id"],
                    "home_room":room_id(home,spec["room"])})
        client.put(root + "/known-locations",{"known_locations":ids})
        client.post(root + "/place-on-map",{"location_id":start["id"],
                    "current_room":room_id(start,spec["start_room"])})
        client.post(root + "/profile",{"fields":{"decency_preference":"public",
                    "current_feeling":"Aufmerksam und freundlich beim Schuljahrsbeginn."}})
        invroot = "/inventory/characters/" + urllib.parse.quote(spec["name"],safe="")
        client.post(invroot + "/apply-outfit-set",{"name":spec["outfit"]})
        equipped = client.get(invroot + "/equipped")["equipped_pieces"]
        expected_slots = {slot for slot,_,_ in spec["clothes"]}
        require(expected_slots.issubset(equipped) and all(equipped[s] for s in expected_slots),
                f"{spec['name']}: outfit not fully equipped")
        inventory = client.get(invroot)["inventory"]
        owned = {entry["item_id"] for entry in inventory}
        require(set(equipped.values()).issubset(owned),f"{spec['name']}: equipped clothing not owned")
        for name,category,description in spec["items"]:
            item = client.post("/inventory/items",{"name":name,"description":description,
                        "category":category,"rarity":"unique","stackable":False,
                        "max_stack":1,"transferable":True,"image_prompt":"a single modest personal object, isolated, no text"})["item"]
            client.post(invroot,{"item_id":item["id"],"quantity":1,
                        "obtained_from":spec["name"],"obtained_method":"manual"})
        configure_skills(client,spec["name"])
        portrait = generated / (spec["name"].replace(" ","-") + ".png")
        paint_portrait(portrait,spec)
        client.upload(root + "/images",portrait)
        profile = client.get(root + "/profile")["profile"]
        require(profile.get("template") == "human-roleplay" and int(profile.get("age",0)) >= 18,
                f"{spec['name']}: full adult character profile not stored")
        require(profile.get("language") == "de" and profile.get("profile_image"),
                f"{spec['name']}: German profile or portrait missing")
        config = client.get(root + "/config")["config"]
        require(set(config.get("known_locations",[])) == set(ids),f"{spec['name']}: location knowledge missing")
        for section,heading in SOUL_HEADINGS.items():
            raw = client.get(root + "/soul/file/" + section)["raw"]
            require(raw.startswith("# " + heading) and len(raw.strip()) > len(heading)+40,
                    f"{spec['name']}: soul section missing: {section}")
        final_inventory = client.get(invroot)["inventory"]
        names = {entry["item_name"] for entry in final_inventory}
        require(all(name in names for name,_,_ in spec["items"]),
                f"{spec['name']}: owned personal items missing")
    # Grounded, directional forms of address; no unavailable relationship-strength API.
    for a,b,outgoing,incoming in [
        ("Rubeus Hagrid","Minerva McGonagall","Professorin McGonagall","Hagrid"),
        ("Elspeth Rowan","Rubeus Hagrid","Hagrid","Elspeth"),
        ("Johanna Falk","Minerva McGonagall","Professorin McGonagall","Frau Falk"),
        ("Johanna Falk","Elspeth Rowan","Frau Rowan","Frau Falk"),
    ]:
        client.put("/characters/" + urllib.parse.quote(a,safe="") + "/relationships/"
                   + urllib.parse.quote(b,safe="") + "/address",{"outgoing":outgoing,"incoming":incoming})
    return [spec["name"] for spec in cast]


def configure_world(client):
    settings = client.get("/admin/world-settings")
    values = copy.deepcopy(settings["values"])
    values["game_calendar"] = {"year_label":"Schuljahr {n}","week_days":"Montag,Dienstag,Mittwoch,Donnerstag,Freitag,Samstag,Sonntag",
                               "day_bucket_noon":12,"day_bucket_evening":17}
    values["game_seasons"] = [
        {"key":"early_autumn","name":"Frühherbst","days":60,"sunrise":"06:30","sunset":"19:45",
         "temperature":"mild","weather":"dry","weather_note":"Kühler schottischer Wind, tiefe goldene Nachmittagssonne, feuchte Ufersteine."},
        {"key":"winter","name":"Winter","days":90,"sunrise":"08:20","sunset":"16:10",
         "temperature":"freezing","weather":"snow","weather_note":"Frost auf den Wiesen und Schnee auf den Schieferdächern."},
        {"key":"spring","name":"Frühling","days":90,"sunrise":"06:05","sunset":"20:10",
         "temperature":"mild","weather":"rain","weather_note":"Helle Schauer, frisches Laub und weicher Boden abseits der Wege."},
        {"key":"summer","name":"Sommer","days":90,"sunrise":"04:45","sunset":"21:50",
         "temperature":"mild","weather":"dry","weather_note":"Lange helle Abende und ruhiger Wind über dem See."},
        {"key":"late_summer","name":"Spätsommer","days":35,"sunrise":"05:50","sunset":"20:25",
         "temperature":"mild","weather":"dry","weather_note":"Reife Heide, erste kühle Nächte und Vorbereitungen für ein neues Schuljahr."},
    ]
    values.setdefault("game",{})["default_terrain_kind"] = "hw_meadow"
    values.setdefault("npc",{})["auto_spawn_enabled"] = False
    values.setdefault("random_events",{})["enabled"] = False
    values.setdefault("story_engine",{})["enabled"] = False
    client.put("/admin/world-settings",{"values":values,"resets":[]})
    readback = client.get("/admin/world-settings")
    require(readback["values"].get("game_calendar") == values["game_calendar"], "Calendar not stored")
    require(readback["values"].get("game_seasons") == values["game_seasons"], "Seasons not stored")
    client.put("/admin/world-setup",{"description":BRIEFING})
    require(client.get("/admin/world-setup")["description"] == BRIEFING,"World briefing not stored")
    client.post("/world/game-time",{"game_time":"Y0001-D001T16:40:00"})
    client.get("/world/game-time")


def fresh_world_guard(client, credentials):
    require(client.get("/health").get("status") == "healthy", "Target server is not healthy")
    client.request("POST","/auth/login",credentials,confidential=True)
    status = client.get("/auth/status",confidential=True)
    user = status.get("user") or {}
    require(status.get("authenticated") and user.get("role") == "admin"
            and user.get("username") == credentials["username"] and user.get("id"),
            "The explicit credentials must authenticate the isolated world's admin")
    require(client.get("/world/freeze-status").get("frozen") is True,
            "Refusing a live world: controller must create a frozen isolated world")
    for path,key in [("/world/locations","locations"),("/characters/list","characters"),
                     ("/world/terrain-areas","areas"),("/world/height-areas","areas"),
                     ("/world/world-props","world_props"),("/world/props","props"),
                     ("/inventory/items","items")]:
        require(not client.get(path)[key],f"Fresh-world guard: {path} is not empty; no automatic replay")
    require(not client.get("/admin/world-setup").get("description","").strip(),
            "Fresh-world guard: world already has an authored briefing")
    return user["id"]


def build(args):
    assets_dir = args.assets.resolve()
    work = args.work_dir.resolve()
    require(not (work / "build-started.json").exists(),
            "This work directory already attempted a build; discard world and use a new directory")
    require(not work.exists() or not any(work.iterdir()), "--work-dir must be new or empty")
    work.mkdir(parents=True,exist_ok=True,mode=0o700)
    os.chmod(work,0o700)
    require(not args.credentials_file.resolve().is_relative_to(work),
            "Credentials must be outside the build-record directory")
    raw_credentials = json.loads(args.credentials_file.read_text(encoding="utf-8"))
    credentials = {key:raw_credentials.get(key) for key in ("username","password")}
    require(all(isinstance(value,str) and value.strip() for value in credentials.values()),
            "Credentials file must contain nonempty username and password strings")
    assets,manifests = load_assets(assets_dir)
    generated = work / "generated"
    generated.mkdir()
    assets.update(make_furniture(generated))
    for spec in assets.values():
        validate_glb(spec["path"])
    dump_json(work / "input-manifests.json",manifests)
    dump_json(work / "furniture-manifest.json",{"provenance":PROVENANCE,
                "assets":{key:{k:v for k,v in spec.items() if k != "path"}
                          for key,spec in assets.items() if spec["path"].parent == generated}})
    places = place_specs(assets)
    authored_map = map_payload(places)
    check_dry_geography(authored_map)
    for character in cast_specs():
        character_payload(character)
    client = Client(args.url,work)
    user_id = fresh_world_guard(client,credentials)
    del credentials,raw_credentials
    # Exclusive marker is deliberately durable even if a later write fails.
    dump_json(work / "build-started.json",{"url":client.url,"replay_safe":False,
                "instruction":"On failure discard isolated world; do not replay this directory."})
    for kind,spec in terrain_types().items():
        client.put("/world/terrain-types/"+kind,spec)
    configure_world(client)
    map_body = {"map_data":authored_map,"mode":"merge","snapshot":False}
    client.post("/world-dev/preview-map",map_body)
    client.post("/world-dev/apply-map",map_body)
    stubs = location_index(client)
    require(set(stubs) == {spec["name"] for spec in places},"Map stub count/identity mismatch")
    for spec in places:
        payload = {"json":location_payload(spec),"type_hint":"location"}
        client.post("/world-dev/preview-json",payload)
        client.post("/world-dev/apply-json",payload)
    locations = location_index(client)
    prop_ids = add_props(client,assets)
    for spec in places:
        location = locations[spec["name"]]
        body = {"location_id":location["id"],"layout_data":layout_payload(spec,location,prop_ids),"snapshot":False}
        client.post("/world-dev/preview-layout",body)
        client.post("/world-dev/apply-layout",body)
        if spec.get("asset"):
            asset = assets[spec["asset"]]
            root = "/world/locations/"+location["id"]+"/model3d"
            client.upload(root+"/upload",asset["path"],tier="full")
            real_width = max(asset["width_m"],asset["depth_m"])
            client.post(root+"/width",{"width_m":real_width})
            metadata = client.get("/play/locations/"+location["id"]+"/model/meta")
            require(abs(float(metadata.get("width_m",0))-real_width) < .01,
                    f"{spec['name']}: model real width readback mismatch")
    decorate_terrain(client,prop_ids)
    outdoor_props(client,prop_ids)
    locations = location_index(client)
    keyed = {spec["key"]:locations[spec["name"]] for spec in places}
    for spec in places:
        location = keyed[spec["key"]]
        require(location.get("entry_room") == room_id(location,spec["entry"]),
                f"{spec['name']}: entry room not stored")
        for name,_,_ in spec["rooms"]:
            matching = next(room for room in location["rooms"] if room["name"] == name)
            require(matching.get("layout",{}).get("w",0) > 0,f"{name}: layout not stored")
    names = author_characters(client,keyed,generated)
    client.request("PATCH","/auth/users/"+urllib.parse.quote(str(user_id),safe=""),
                   {"allowed_characters":names})
    client.post("/account/switch-character",{"character_name":"Johanna Falk"})
    account = client.get("/account/characters")
    require(account["active_character"] == "Johanna Falk" and set(names).issubset(account["characters"]),
            "Avatar account access/selection failed")
    access = client.get("/auth/status",confidential=True).get("user") or {}
    require(set(access.get("allowed_characters",[])) == set(names),"User character access did not persist")
    require(client.get("/world/freeze-status").get("frozen") is True,"World unexpectedly unfrozen")
    dump_json(work / "build-result.json",{
        "world_frozen":True,"avatar":"Johanna Falk","characters":names,
        "locations":{key:{"id":loc["id"],"name":loc["name"],"entry_room":loc.get("entry_room"),
                          "rooms":{room["name"]:room["id"] for room in loc["rooms"]}}
                     for key,loc in keyed.items()},
        "prop_ids":prop_ids,"endpoints":[{"method":method,"path":path}
                                         for method,path in sorted(client.endpoints)],
        "limitations":["Stationary decorative train/boats; no transport mechanics.",
                       "World props decorative; no collision guarantee.",
                       "No shared surface textures; native world-local terrain materials.",
                       "Adult characters have profiles/owned clothing/soul/portraits, no uploaded humanoid rig.",
                       "Controller must verify Blender jobs/scene problems and 3D UI, then sanitize offline before shipping."]})
    print("Hogwarts content authored and read back; world remains frozen. Private record: " + str(work))


def main():
    parser = argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url",required=True,help="Explicit isolated server origin; never auto-discovered")
    parser.add_argument("--assets",required=True,type=Path,help="Directory with both generated manifests and GLBs")
    parser.add_argument("--credentials-file",required=True,type=Path,help="Private JSON username/password; never printed")
    parser.add_argument("--work-dir",required=True,type=Path,help="New/empty private payload and readback record")
    args = parser.parse_args()
    try:
        build(args)
    except (BuildError,OSError,ValueError,KeyError,TypeError) as error:
        # Values supplied by credentials JSON must never escape via exception text.
        if isinstance(error,BuildError):
            print("Build stopped: " + str(error),file=sys.stderr)
        else:
            print("Build stopped: " + type(error).__name__ + "; inspect private payload/readback files. No replay.",file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
