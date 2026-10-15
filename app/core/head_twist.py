"""Head forward twist about its own +Y, relative to Hips +Z.

Angles are raw world-frame measurements (Head is measured before Neck correction).
Only the GLB JSON chunk is read; geometry and inverse bind buffers stay on disk.
"""
import hashlib
import json
import math
import struct
from functools import lru_cache
from pathlib import Path


def bone_name(name):
    return name.lower().replace('mixamorig', '').replace(':', '')


def twist_degrees(matrix, forward):
    """Signed angle between projected reference and bone +Z about bone +Y."""
    def dot(a, b):
        return sum(x * y for x, y in zip(a, b))
    def unit(v):
        length = math.sqrt(dot(v, v))
        if length < 1e-10:
            raise ValueError('Degenerate head twist frame')
        return [x / length for x in v]
    axis = unit([matrix[i][1] for i in range(3)])
    def project(v):
        d = dot(v, axis)
        return unit([v[i] - d * axis[i] for i in range(3)])
    ref = project(forward)
    front = project([matrix[i][2] for i in range(3)])
    cross = [ref[1]*front[2]-ref[2]*front[1], ref[2]*front[0]-ref[0]*front[2],
             ref[0]*front[1]-ref[1]*front[0]]
    return math.degrees(math.atan2(dot(cross, axis), dot(ref, front)))


def _multiply(a, b):
    return [[sum(a[i][k]*b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def twists_from_json(doc):
    nodes = doc.get('nodes', [])
    parents = {child: i for i, node in enumerate(nodes) for child in node.get('children', [])}
    joints = {j for skin in doc.get('skins', []) for j in skin.get('joints', [])}
    @lru_cache(None)
    def world(i):
        node = nodes[i]
        if 'matrix' in node:
            m = node['matrix']
            local = [[m[j*4+i] for j in range(3)] for i in range(3)]
        else:
            x, y, z, w = node.get('rotation', [0, 0, 0, 1])
            local = [[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                     [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                     [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]]
            scale = node.get('scale', [1, 1, 1])
            local = [[local[i][j]*scale[j] for j in range(3)] for i in range(3)]
        return _multiply(world(parents[i]), local) if i in parents else local
    # Keep unrelated armatures separate, even when they reuse joint names.
    for skin in doc.get('skins', []):
        named = {bone_name(nodes[i].get('name', '')): i for i in skin.get('joints', []) if i in joints}
        if all(n in named for n in ('hips', 'neck', 'head')):
            hips = world(named['hips'])
            forward = [hips[i][2] for i in range(3)]
            return {n: twist_degrees(world(named[n]), forward) for n in ('neck', 'head')}
    return {}


@lru_cache(maxsize=128)
def _read(path, mtime_ns, size):
    with open(path, 'rb') as stream:
        magic, version, total = struct.unpack('<4sII', stream.read(12))
        if magic != b'glTF' or version != 2:
            return {}
        length, kind = struct.unpack('<II', stream.read(8))
        if kind != 0x4E4F534A or length > total - 20:
            return {}
        return twists_from_json(json.loads(stream.read(length)))


def read_head_twist(path):
    try:
        path = Path(path)
        st = path.stat()
        return dict(_read(str(path.resolve()), st.st_mtime_ns, st.st_size))
    except (OSError, ValueError, KeyError, IndexError, TypeError, RecursionError, struct.error):
        return {}


@lru_cache(maxsize=128)
def _sha256(path, mtime_ns, size):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tpose_status(match, meta, photo):
    """Compare the retained source with the same photo lookup used for face repair."""
    if match != 'exact':
        return 'other_outfit'
    if not meta.get('source_image_sha256') or photo is None:
        return 'unknown'
    try:
        photo = Path(photo)
        st = photo.stat()
        if _sha256(str(photo.resolve()), st.st_mtime_ns, st.st_size) != meta['source_image_sha256']:
            return 'changed'
        if 'view_images_sha256' in meta:
            for view, name in (meta.get('view_images') or {}).items():
                if Path(name).name != name:
                    continue
                current = photo.parent / name
                if not current.is_file():
                    return 'changed'
                stat = current.stat()
                if _sha256(str(current.resolve()), stat.st_mtime_ns, stat.st_size) != meta['view_images_sha256'].get(view):
                    return 'changed'
            return 'current'
        from app.core.timeutils import parse_iso
        created = parse_iso(meta['created_at'].replace('Z', '+00:00')).timestamp()
        for name in (meta.get('view_images') or {}).values():
            if Path(name).name != name:
                continue
            view = photo.parent / name
            if not view.is_file() or view.stat().st_mtime > created:
                return 'changed'
        return 'current'
    except (OSError, ValueError, KeyError, TypeError):
        return 'unknown'
