"""Signature-keyed door assets and a single non-blocking Blender worker.

Retention and build timestamps use SYSTEM time, never the game clock.
"""
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import tempfile
import threading

from app.blender import runner
from app.core import paths, surface_textures
from app.core.door_geometry import build_door
from app.core.door_styles import load_door_styles, validate_door_style
from app.core.hull_util import tone, tone_to_linear
from app.core.log import get_logger
from app.core.media_cleanup import contained, remove_owned_dir
from app.core.timeutils import utc_now

logger = get_logger(__name__)
_run_blender = runner.run
_lock = threading.RLock()
_queue = queue.Queue()
_pending = set()
_failed = set()
_worker = None
_generation = 0


def safe_signature(sig):
    """Accept only the cache's exact sixteen lowercase hex digits."""
    return sig if isinstance(sig, str) and re.fullmatch(r'[0-9a-f]{16}', sig) else ''


def _root():
    return paths.get_storage_dir() / 'door_models'


def _directory(root, sig):
    target = root / sig
    if not safe_signature(sig) or not contained(root, target) or target.is_symlink():
        raise ValueError('unsafe door cache path')
    return target


def _dimensions(width, height, thickness):
    return [round(float(value) + 0.0, 2) for value in (width, height, thickness)]


def door_signature(style, width, height, thickness, piece, outside, color):
    """Hash normalized style, centimetre dimensions and resolved file identities."""
    style = validate_door_style(style)
    identities = {}
    for role in ('leaf_material', 'frame_material'):
        kind = style[role]
        source = None if kind.startswith('#') else surface_textures.base_texture_file(kind)
        if source and source.is_file():
            stat = source.stat()
            identities[role] = [str(source.resolve()), stat.st_mtime_ns, stat.st_size,
                                surface_textures.texture_size_m(source)]
        else:
            identities[role] = None
    payload = [style, _dimensions(width, height, thickness), piece, outside,
               tone(color, '') or None, identities]
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()[:16]


def model_path(sig):
    """Return an existing contained model, or None for unsafe/missing paths."""
    if not safe_signature(sig):
        return None
    root = _root()
    try:
        target = _directory(root, sig) / 'model.glb'
        return target if contained(root, target) and target.is_file() else None
    except (ValueError, OSError):
        return None


def _cached(root, sig):
    try:
        directory = _directory(root, sig)
        meta = directory / 'meta.json'
        model = directory / 'model.glb'
        if not all(contained(root, p) and p.is_file() for p in (meta, model)):
            return None
        data = json.loads(meta.read_text(encoding='utf-8'))
        result = {key: data[key] for key in ('sig', 'leaf_bbox', 'size_m')}
        if result['sig'] != sig:
            return None
        now = utc_now().timestamp()
        if now - meta.stat().st_mtime >= 86400:
            os.utime(meta, (now, now))
        return {**result, 'url': f'/assets/doors/{sig}/model'}
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _materials(style, color, directory):
    """Resolve physical texture scale, deterministic tint and linear colours."""
    from PIL import Image
    materials, inputs, sizes = [], {}, {}
    for name, role in (('door_leaf', 'leaf_material'), ('door_frame', 'frame_material')):
        value = style[role]
        source = None if value.startswith('#') else surface_textures.base_texture_file(value)
        texture = None
        base = tone_to_linear((color if name == 'door_leaf' and color else value)
                              if value.startswith('#') else '#ffffff')
        if source and source.is_file():
            sizes[name] = surface_textures.texture_size_m(source)
            tints = [style['leaf_tint'] or '#ffffff'] if name == 'door_leaf' else ['#ffffff']
            if name == 'door_leaf' and color:
                tints.append(color)
            factors = [1., 1., 1.]
            for tint in tints:
                for index, start in enumerate((1,3,5)):
                    factors[index] *= int(tint[start:start+2],16)/255
            with Image.open(source) as image:
                channels = image.convert('RGB').split()
                tinted = Image.merge('RGB', tuple(channel.point([
                    max(0,min(255,round(value*factor))) for value in range(256)])
                    for channel, factor in zip(channels,factors)))
                # A leaf is about 1 x 2 m: 512 px keeps the planks sharp and the GLB small.
                tinted.thumbnail((512, 512), Image.LANCZOS)
                target = directory / f'{name}.png'
                tinted.save(target, format='PNG')
            texture = f'texture_{name}'
            inputs[texture] = target
            base = [1.,1.,1.]
        materials.append(dict(name=name, texture=texture, color=base, alpha=1., roughness=.8))
    materials.extend([
        dict(name='glass',texture=None,color=tone_to_linear('#a9c4cf'),alpha=.35,roughness=.06),
        dict(name='hardware',texture=None,color=tone_to_linear(style['hardware_color']),alpha=1.,roughness=.3)])
    return materials, inputs, sizes


def _meshes(parts):
    merged = {}
    for part in parts:
        node, material = part['node'], part['material']
        name = node if material == f'door_{node}' else f'{node}_{material}'
        mesh = merged.setdefault((node,material),dict(name=name,node=node,material=material,
                                                    vertices=[],faces=[],uvs=[],colors=[]))
        offset = len(mesh['vertices'])
        mesh['vertices'].extend([[x,-z,y] for x,y,z in part['vertices']])
        mesh['faces'].extend([[i+offset for i in face] for face in part['faces']])
        mesh['uvs'].extend(part['uvs']); mesh['colors'].extend(part['colors'])
    return [merged[key] for key in sorted(merged)]


def build_door_model(style_id, width, height, thickness, *, piece='single', outside=1,
                     color=None, mode='model', _style=None, _root_dir=None):
    """Synchronously build an asset; callers composing scenes use ensure instead."""
    style = validate_door_style(_style) if _style is not None else load_door_styles()[style_id]
    width,height,thickness = _dimensions(width,height,thickness)
    color = tone(color, '') or None
    sig = door_signature(style,width,height,thickness,piece,outside,color)
    root = Path(_root_dir) if _root_dir is not None else _root()
    target = _directory(root,sig)
    with tempfile.TemporaryDirectory(prefix='av-door-') as tmp:
        work = Path(tmp)
        materials, inputs, sizes = _materials(style,color,work)
        geometry = build_door(style,width,height,thickness,piece=piece,outside=outside,uv_sizes=sizes)
        job = dict(materials=materials,meshes=_meshes(geometry['parts']),mode=mode)
        job_path = work / 'job.json'
        job_path.write_text(json.dumps(job,sort_keys=True),encoding='utf-8')
        result = _run_blender('door_build',inputs={'job':job_path,**inputs},out_dir=work,timeout_s=120)
        if not result.get('ok'):
            raise RuntimeError(result.get('error','door build failed'))
        model = work / 'model.glb'
        if not model.is_file() or (mode == 'thumbnail' and not (work/'thumbnail.png').is_file()):
            raise RuntimeError('door build missing output')
        meta = dict(sig=sig,style_id=style_id,size_m=[round(v,4) for v in geometry['size_m']],
                    leaf_bbox={k:[round(v,4) for v in box] for k,box in geometry['leaf_bbox'].items()},
                    piece=piece,outside=outside,built_at=utc_now().isoformat())
        target.mkdir(parents=True,exist_ok=True)
        for name in ('model.glb','thumbnail.png'):
            source = work/name
            if source.is_file():
                if not contained(root,target/name) or (target/name).is_symlink():
                    raise ValueError('unsafe door output')
                # Atomic publication, including when /tmp and storage use different devices.
                staging = target / f'.{name}.tmp'
                if staging.is_symlink():
                    raise ValueError('unsafe door staging path')
                staging.write_bytes(source.read_bytes()); staging.replace(target/name)
        staged_meta = target / '.meta.json.tmp'
        if staged_meta.is_symlink() or (target/'meta.json').is_symlink():
            raise ValueError('unsafe door metadata')
        staged_meta.write_text(json.dumps(meta,sort_keys=True),encoding='utf-8')
        staged_meta.replace(target/'meta.json')
    return {**meta,'url':f'/assets/doors/{sig}/model'}


def generation():
    with _lock:
        return _generation


def _work():
    global _generation
    while True:
        key, style, dims, options = _queue.get()
        try:
            build_door_model(style['id'],*dims,_style=style,_root_dir=key[0],**options)
        except Exception:
            with _lock:
                _failed.add(key)
            logger.exception('Door build failed for %s; suppressed until restart',key[1])
        finally:
            with _lock:
                _pending.discard(key)
                _generation += 1
            _queue.task_done()


def ensure_door_model(style_id,width,height,thickness,*,piece='single',outside=1,color=None):
    """Return cached metadata or queue a build; never wait for Blender.

    Accept a style id or a validated style dict from a composition catalog,
    so composing many doors reads the shipped styles only once.
    """
    global _worker
    style = style_id if isinstance(style_id, dict) else load_door_styles().get(style_id)
    if style is None:
        return None
    dims = _dimensions(width,height,thickness)
    sig = door_signature(style,*dims,piece,outside,color)
    root = _root()
    with _lock:
        cached = _cached(root,sig)
        if cached:
            return cached
        key = (root,sig)
        if key not in _pending and key not in _failed:
            _pending.add(key)
            _queue.put((key,style,dims,dict(piece=piece,outside=outside,color=color)))
            if _worker is None:
                _worker = threading.Thread(target=_work,name='door-models',daemon=True)
                _worker.start()
    return None


_thumbnail_lock = threading.Lock()


def style_thumbnail(style_id):
    """Cache one 256px Workbench preview at the prescribed 0.9 x 2.1 x 0.12 size."""
    style = load_door_styles()[style_id]
    sig = door_signature(style,.9,2.1,.12,'single',1,None)
    with _thumbnail_lock:
        target = _directory(_root(),sig)/'thumbnail.png'
        if not contained(_root(),target):
            raise ValueError('unsafe thumbnail')
        if not target.is_file():
            build_door_model(style_id,.9,2.1,.12,mode='thumbnail',_style=style)
        _cached(_root(),sig)
        return target


def sweep_cache():
    """Remove assets unused for seven SYSTEM days, refusing symlink escapes."""
    root = _root()
    cutoff = utc_now().timestamp()-7*86400
    removed = 0
    if not root.is_dir():
        return 0
    with _lock:
        for directory in root.iterdir():
            if not safe_signature(directory.name) or (root,directory.name) in _pending:
                continue
            meta = directory/'meta.json'
            try:
                if contained(root,meta) and meta.stat().st_mtime < cutoff:
                    removed += int(remove_owned_dir(root,directory.name))
            except OSError:
                continue
    return removed
