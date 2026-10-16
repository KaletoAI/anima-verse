"""Eligibility, reference-photo preparation and face texture baking."""
import hashlib
import io
import json
import re
from pathlib import Path

from PIL import Image

MAX_BYTES = 64 * 1024 * 1024


def safe_signature(signature: str) -> str:
    """Accept a single cache key, never a glob or path."""
    if not isinstance(signature, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,128}', signature):
        raise ValueError('Invalid model signature')
    return signature


def read_meta(path: Path) -> dict:
    try:
        value = json.loads(path.with_suffix('.json').read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def photo_path(character: str, signature: str, meta: dict, reference: str = "front") -> Path:
    from app.models.character import get_character_dir
    root = get_character_dir(character) / 'model_refs'
    safe_signature(signature)
    if reference not in ('face', 'front'):
        raise ValueError('Invalid face reference choice')
    if reference == 'face':
        name = 'face_view.png'
    else:
        name = meta.get('source_image') or f'tpose_{signature}.png'
    if not isinstance(name, str) or Path(name).name != name or '\\' in name:
        raise ValueError('Invalid source image name')
    path = root / name
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('Invalid source image path')
    return path


def flatten_photo(raw: bytes) -> bytes:
    """Decode the original photo and flatten alpha onto white as RGB PNG."""
    if len(raw) > MAX_BYTES:
        raise ValueError('Reference photo exceeds the 64 MB upload limit')
    image = Image.open(io.BytesIO(raw))
    image.load()
    rgba = image.convert('RGBA')
    white = Image.new('RGBA', rgba.size, 'white')
    white.alpha_composite(rgba)
    out = io.BytesIO()
    white.convert('RGB').save(out, 'PNG')
    result = out.getvalue()
    if len(result) > MAX_BYTES:
        raise ValueError('Reference photo exceeds the 64 MB upload limit')
    return result


def use_upscale(reference: str, upscale: bool | None) -> bool:
    """Close-ups need no enlargement unless explicitly requested."""
    return reference != 'face' if upscale is None else bool(upscale)


def reference_info(character: str, signature: str, meta: dict, reference: str = '', *,
                   _snapshot: dict | None = None) -> dict:
    """Select a self-verified close-up of the current profile, independent of outfit."""
    if reference not in ('', 'face', 'front'):
        raise ValueError('Invalid face reference choice')
    from app.core.model_refs import current_profile_image
    profile = current_profile_image(character)
    try:
        expected = hashlib.sha256(profile.read_bytes()).hexdigest() if profile else ""
    except OSError:
        expected = ""
    if not expected:
        problem = {'code': 'no_profile_image', 'message': 'No profile picture.',
                   'fix': 'Set a profile picture, then render the face view'}
        selected = reference or 'front'
        return {'reference': selected, 'face_available': False, 'face_problem': problem,
                'problems': [problem] if selected == 'face' else []}
    problem = None
    # The render lock covers minutes of GPU work. Certify the published pair
    # by content instead, then freeze only the bytes that passed this check.
    for attempt in range(3):
        path = photo_path(character, signature, meta, 'face')
        try:
            face_meta = read_meta(path)
            raw = path.read_bytes()
            published_hash = face_meta.get('image_sha256')
            if not published_hash:
                problem = {'code': 'face_unverified', 'message': 'The face view has no image hash.',
                           'fix': 'Regenerate the face view'}
                break
            if hashlib.sha256(raw).hexdigest() != published_hash:
                problem = {'code': 'face_rendering', 'message': 'The face view is being re-rendered.',
                           'fix': 'Wait for the render to finish or regenerate the face view'}
                continue
            image = flatten_photo(raw)
        except (OSError, ValueError, Image.DecompressionBombError):
            problem = {'code': 'no_face_photo', 'message': 'No face view.',
                       'fix': 'Render the face view from the profile picture'}
        else:
            if not expected or face_meta.get('reference_sha256') != expected:
                problem = {'code': 'face_stale', 'message': 'The profile picture changed after the face view was rendered.',
                           'fix': 'Regenerate the face view'}
            else:
                problem = None
                if _snapshot is not None:
                    _snapshot['image'] = image
        break
    selected = reference or ('front' if problem else 'face')
    return {'reference': selected, 'face_available': problem is None,
            'face_problem': problem, 'problems': [problem] if selected == 'face' and problem else []}


def check(character: str, signature: str, reference: str = '', *,
          _snapshot: dict | None = None) -> dict:
    """Report permanent asset properties without probing any backend."""
    from app.core import model3d
    from app.models.character import get_character_dir
    from app.core.mesh_source import validate_face_source
    safe_signature(signature)
    root = getattr(model3d._staging, 'directories', {}).get(character)
    root = root if root is not None else get_character_dir(character) / 'model3d'
    problems, warnings = [], []

    def problem(code, message, fix):
        problems.append({'code': code, 'message': message, 'fix': fix})
    if not any((root / f'{signature}{ext}').is_file() for ext in model3d.MODEL_EXTS):
        problem('no_model', 'No model for this outfit.', 'Generate a model for this outfit first.')
    if model3d.required_rig(character) != 'mixamo':
        problem('not_humanoid', 'This character is not humanoid.', 'Face retexture only works on humanoid (mixamo) character models.')
    source = root / 'unrigged' / f'{signature}.glb'
    choice = reference_info(character, signature, read_meta(source), reference, _snapshot=_snapshot)
    problems.extend(choice['problems'])
    if not source.is_file():
        problem('no_source', 'No retained unrigged mesh source.', "This model predates the mesh/rig split and has no retained unrigged mesh. Regenerate this outfit's model.")
    else:
        if source.stat().st_size > MAX_BYTES:
            problem('too_large', 'The mesh exceeds the 64 MB upload limit.', 'The mesh is too large for the gateway upload. Regenerate with fewer faces.')
        else:
            verdict = validate_face_source(source.read_bytes(), original=True)
            if not verdict['ok']:
                problem('bad_source', 'The retained mesh does not meet the input contract.', "Regenerate this outfit's model.")
                problems[-1]['detail'] = '; '.join(verdict['errors'])
        meta = read_meta(source)
        if choice['reference'] == 'front':
            try:
                raw = photo_path(character, signature, meta).read_bytes()
                flatten_photo(raw)
            except (OSError, ValueError, Image.DecompressionBombError):
                problem('no_photo', 'No usable reference photo.', 'No T-pose render for this outfit. Render it, then regenerate the model so photo and mesh match.')
            else:
                expected = meta.get('source_image_sha256')
                if expected and expected != hashlib.sha256(raw).hexdigest():
                    problem('photo_changed', 'The reference photo has changed.', 'The T-pose was re-rendered after this mesh was made, so photo and mesh no longer match. Regenerate the model.')
                elif not expected:
                    warnings.append({'code': 'photo_unverified', 'message': 'Older model — the photo cannot be verified against the mesh.'})
    if read_meta(root / f'{signature}.glb').get('face_retexture', {}).get('status') == 'applied':
        warnings.append({'code': 'applied', 'message': 'Already corrected — a new run starts again from the original mesh.'})
    return {'ok': not problems, 'problems': problems, 'warnings': warnings,
            **{k: choice[k] for k in ('reference', 'face_available', 'face_problem')}}


def runnable(character: str, backend_glob: str = '') -> dict:
    """Keep temporary routing/availability separate from asset eligibility."""
    from app.imagegen.service import get_image_service
    from app.imagegen.routing import NoRouteError, resolve_image_route, resolve_spec, chain_candidates
    service = get_image_service()
    problems = []
    try:
        if backend_glob:
            _, backend = resolve_spec('face_retexture', backend_glob, character=character, pool=service.pool)
            if backend is None:
                raise NoRouteError('face_retexture', [])
        else:
            resolve_image_route('face_retexture', character=character, probe=True, pool=service.pool)
    except NoRouteError:
        problems.append({'code': 'no_backend', 'message': 'No face retexture backend is available.',
                         'fix': 'Configure a face_retexture backend in /admin/settings → Media Generation.'})
    if not chain_candidates('rig_humanoid', pool=service.pool):
        problems.append({'code': 'no_rigger', 'message': 'No humanoid rig route is configured.',
                         'fix': 'Configure rig_humanoid in /admin/settings → Media Generation → Routing.'})
    return {'ok': not problems, 'problems': problems}


def snapshot_info(root: Path, signature: str) -> dict:
    """Verify a complete, contained rollback manifest before advertising revert."""
    from app.core.model3d import _signature_files, MODEL_EXTS
    safe_signature(signature)
    snapshot = root / 'rollback' / signature
    try:
        if snapshot.is_symlink() or not snapshot.resolve().is_relative_to(root.resolve()):
            raise ValueError('Invalid rollback path')
        manifest = json.loads((snapshot / 'manifest.json').read_text(encoding='utf-8'))
        entries = manifest['files']
        if not isinstance(entries, list) or not entries or not manifest.get('created_at'):
            raise ValueError('Incomplete rollback manifest')
        expected = set()
        allowed = _signature_files(snapshot, signature)
        for entry in entries:
            relative = Path(entry['path'])
            if relative.is_absolute() or '..' in relative.parts or relative not in allowed or relative in expected:
                raise ValueError('Invalid rollback file path')
            path = snapshot / relative
            if path.is_symlink() or not path.resolve().is_relative_to(snapshot.resolve()):
                raise ValueError('Invalid rollback file path')
            raw = path.read_bytes()
            if len(raw) != entry['size'] or hashlib.sha256(raw).hexdigest() != entry['sha256']:
                raise ValueError('Rollback file checksum mismatch')
            expected.add(relative)
        actual = {p.relative_to(snapshot) for p in snapshot.rglob('*') if p.is_file() and p != snapshot / 'manifest.json'}
        if expected != actual or not any(Path(f'{signature}{ext}') in expected for ext in MODEL_EXTS) or Path(f'{signature}.json') not in expected:
            raise ValueError('Incomplete rollback manifest')
        return {'ok': True, 'created_at': manifest['created_at'], 'files': entries}
    except (OSError, ValueError, KeyError, TypeError):
        return {'ok': False, 'error': 'Rollback snapshot is missing or damaged; revert refused.'}


def prepare_snapshot(stage: Path, signature: str) -> None:
    """Copy the before-state outside the staged signature publication set."""
    import shutil
    from app.core.model3d import _signature_files
    from app.core.timeutils import utc_now_iso
    snapshot = stage / '.face-snapshot'
    snapshot.mkdir()
    entries = []
    for relative, source in _signature_files(stage, signature).items():
        target = snapshot / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        raw = target.read_bytes()
        entries.append({'path': relative.as_posix(), 'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
    (snapshot / 'manifest.json').write_text(json.dumps({'created_at': utc_now_iso(), 'files': entries}, indent=2), encoding='utf-8')


def validated_params(params=None) -> dict:
    """Validate the four public controls also for non-UI callers."""
    import math
    defaults = {'strength': 1, 'feather': 0.18, 'render_resolution': 768, 'yaw': 0}
    bounds = {'strength': (0, 1), 'feather': (0, 0.5), 'render_resolution': (256, 2048), 'yaw': (-180, 180)}
    if params is not None and (not isinstance(params, dict) or set(params) - set(defaults)):
        raise ValueError('Unsupported face retexture parameters')
    result = {**defaults, **(params or {})}
    for key, value in result.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not bounds[key][0] <= value <= bounds[key][1]:
            raise ValueError(f'Invalid face retexture parameter: {key}')
    if int(result['render_resolution']) != result['render_resolution']:
        raise ValueError('render_resolution must be an integer')
    result['render_resolution'] = int(result['render_resolution'])
    return result


def _accessor_array(parsed: dict, index: int):
    """Read packed or interleaved GLB accessors without reading stride padding."""
    import numpy as np
    gltf, binary = parsed['gltf'], parsed['bin']
    accessor = gltf['accessors'][index]
    if accessor.get('sparse') is not None:
        raise ValueError('Sparse geometry accessors are unsupported')
    dtype = np.dtype({5120: 'i1', 5121: 'u1', 5122: '<i2', 5123: '<u2',
                      5125: '<u4', 5126: '<f4'}[accessor['componentType']])
    components = {'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4}[accessor['type']]
    view = gltf['bufferViews'][accessor['bufferView']]
    width = dtype.itemsize * components
    count = int(accessor['count'])
    offset = int(accessor.get('byteOffset', 0))
    stride = int(view.get('byteStride', width))
    start = int(view.get('byteOffset', 0))
    if (view.get('buffer', 0) != 0 or count <= 0 or offset < 0 or start < 0
            or stride < width or offset + (count - 1) * stride + width > view['byteLength']
            or start + view['byteLength'] > len(binary)):
        raise ValueError('Geometry accessor is truncated or invalid')
    array = np.ndarray((count, components), dtype=dtype, buffer=binary,
                       offset=start + offset, strides=(stride, dtype.itemsize))
    if accessor.get('normalized') and dtype.kind in 'iu':
        limits = np.iinfo(dtype)
        array = array.astype(np.float64) / limits.max
        if dtype.kind == 'i':
            array = np.maximum(array, -1)
    return array


def _primitive_basecolor(parsed: dict, primitive: dict):
    """Resolve the used material's embedded image, rather than image zero."""
    gltf = parsed['gltf']
    material = gltf['materials'][primitive['material']]
    texture = gltf['textures'][material['pbrMetallicRoughness']['baseColorTexture']['index']]
    image = gltf['images'][texture['source']]
    view = gltf['bufferViews'][image['bufferView']]
    start = int(view.get('byteOffset', 0))
    if view.get('buffer', 0) != 0 or start < 0 or start + view['byteLength'] > len(parsed['bin']):
        raise ValueError('Basecolor bufferView is invalid')
    return image, parsed['bin'][start:start + view['byteLength']]


def bake_face_texture(source_glb: bytes, hub_glb: bytes, *, dilate_px: int = 4,
                      replacement_masks: list | None = None) -> tuple[bytes, dict]:
    """Bake the projected face into the original mesh's basecolor and layout."""
    import struct
    import numpy as np
    from PIL import ImageDraw, ImageFilter
    from app.core.model_validate import parse_glb
    from app.core.mesh_source import validate_face_source, validate_source

    if not isinstance(dilate_px, int) or isinstance(dilate_px, bool) or dilate_px < 0:
        raise ValueError('Face dilation must be a nonnegative integer')
    for raw, original in ((source_glb, True), (hub_glb, False)):
        verdict = validate_face_source(raw, original=original)
        if not verdict['ok']:
            raise ValueError('Invalid face bake mesh: ' + '; '.join(verdict['errors']))
    source, hub = parse_glb(source_glb), parse_glb(hub_glb)
    primitive = source['gltf']['meshes'][0]['primitives'][0]
    primitives = [p for mesh in hub['gltf']['meshes'] for p in mesh['primitives']]
    try:
        positions = _accessor_array(source, primitive['attributes']['POSITION'])
        uvs = _accessor_array(source, primitive['attributes']['TEXCOORD_0'])
        triangles = _accessor_array(source, primitive['indices']).reshape(-1, 3)
        hub_triangles = []
        for face in primitives:
            for name, expected in (('POSITION', positions), ('TEXCOORD_0', uvs)):
                actual = _accessor_array(hub, face['attributes'][name])
                if not np.array_equal(expected, actual):
                    raise ValueError(f'Face retexture changed {name} geometry')
            indices = _accessor_array(hub, face['indices']).reshape(-1, 3)
            if np.any(indices >= len(positions)):
                raise ValueError('Face triangle index exceeds POSITION accessor')
            hub_triangles.append(indices)
        def triangle_set(values):
            # Lexicographically choose a cyclic rotation; preserve winding and multiplicity.
            values = values.astype(np.int64)
            rotations = np.stack([values, np.roll(values, -1, axis=1),
                                  np.roll(values, -2, axis=1)], axis=1)
            order = np.lexsort((rotations[..., 2], rotations[..., 1], rotations[..., 0]), axis=1)
            canonical = rotations[np.arange(len(values)), order[:, 0]]
            return canonical[np.lexsort((canonical[:, 2], canonical[:, 1], canonical[:, 0]))]
        if not np.array_equal(triangle_set(triangles), triangle_set(np.concatenate(hub_triangles))):
            raise ValueError('Face retexture changed the triangle set')
        def check_coordinates(parsed, p):
            info = parsed['gltf']['materials'][p['material']]['pbrMetallicRoughness']['baseColorTexture']
            if info.get('texCoord', 0) != 0:
                raise ValueError('Face bake requires baseColorTexture texCoord = 0')
            if 'KHR_texture_transform' in info.get('extensions', {}):
                raise ValueError('Face bake does not support baseColorTexture KHR_texture_transform')
        check_coordinates(source, primitive)
        _, base_raw = _primitive_basecolor(source, primitive)
        faces = [(p, indices, _primitive_basecolor(hub, p)[1])
                 for p, indices in zip(primitives, hub_triangles)
                 if _primitive_basecolor(hub, p)[1] != base_raw]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError(f'Invalid face bake geometry or basecolor reference: {exc}') from exc
    if not faces:
        raise ValueError('The hub result contains no face texture')
    for face, indices, _ in faces:
        check_coordinates(hub, face)
        face_uvs = uvs[indices]
        if (not np.all(np.isfinite(face_uvs)) or np.any(face_uvs < -1e-6)
                or np.any(face_uvs > 1 + 1e-6)):
            raise ValueError('Face triangle UVs are outside [0, 1]')
    base = Image.open(io.BytesIO(base_raw)).convert('RGBA')
    width, height = base.size
    composite = np.asarray(base).copy()
    replaced = np.zeros((height, width), dtype=bool)
    def coverage(indices):
        mask = Image.new('L', base.size, 0)
        draw = ImageDraw.Draw(mask)
        for triangle in indices:
            draw.polygon([(float(uvs[i, 0]) * width, float(uvs[i, 1]) * height)
                          for i in triangle], fill=255)
        return mask
    all_face_covered = np.zeros((height, width), dtype=bool)
    for _, indices, _ in faces:
        all_face_covered |= np.asarray(coverage(indices)) > 0
    body_covered = np.zeros((height, width), dtype=bool)
    for p, indices in zip(primitives, hub_triangles):
        if not any(p is face for face, _, _ in faces):
            # Body coverage protects body texels from the dilation ring; a
            # wrapped (REPEAT) UV outside [0, 1] would rasterize off the atlas
            # and leave the texels it really samples unprotected.
            body_uvs = uvs[indices]
            if (not np.all(np.isfinite(body_uvs)) or np.any(body_uvs < -1e-6)
                    or np.any(body_uvs > 1 + 1e-6)):
                raise ValueError('Body triangle UVs are outside [0, 1]')
            body_covered |= np.asarray(coverage(indices)) > 0
    for face, indices, raw in faces:
        atlas = Image.open(io.BytesIO(raw)).convert('RGBA')
        if atlas.size != base.size:
            atlas = atlas.resize(base.size, Image.Resampling.LANCZOS)
        mask = coverage(indices)
        face_covered = np.asarray(mask) > 0
        if dilate_px:
            mask = mask.filter(ImageFilter.MaxFilter(2 * dilate_px + 1))
        allowed = face_covered | ((np.asarray(mask) > 0) & (~body_covered | all_face_covered))
        pixels = np.asarray(atlas)
        selected = allowed & (pixels[..., 3] > 0)
        composite[selected, :3] = pixels[selected, :3]
        replaced |= selected
    if not replaced.any():
        raise ValueError('The hub result contains no usable face texture')
    out = io.BytesIO()
    Image.fromarray(composite).save(out, 'PNG')
    png = out.getvalue()
    gltf = source['gltf']
    texture_info = gltf['materials'][primitive['material']]['pbrMetallicRoughness']['baseColorTexture']
    texture_index = texture_info['index']
    original_texture = gltf['textures'][texture_index]
    image_index = original_texture['source']
    image = gltf['images'][image_index]
    image_view = image['bufferView']

    def other_reference(value):
        # Ignore only the exact basecolor slot being replaced. Extension texture
        # slots use the same index convention; unknown references are conservative.
        if value is texture_info:
            return False
        if isinstance(value, dict):
            if value.get('index') == texture_index:
                return True
            return any(other_reference(v) for v in value.values())
        if isinstance(value, list):
            return any(other_reference(v) for v in value)
        return False

    def extension_image_reference(value):
        if isinstance(value, dict):
            return any((k in ('source', 'image', 'imageIndex') and v == image_index)
                       or extension_image_reference(v) for k, v in value.items())
        if isinstance(value, list):
            return any(extension_image_reference(v) for v in value)
        return False

    shared = (other_reference(gltf['materials'])
              or any(i != texture_index and t.get('source') == image_index
                     for i, t in enumerate(gltf['textures']))
              or any(i != image_index and img.get('bufferView') == image_view
                     for i, img in enumerate(gltf['images'])))
    safe_extensions = {
        'KHR_materials_unlit', 'KHR_materials_clearcoat', 'KHR_materials_transmission',
        'KHR_materials_volume', 'KHR_materials_ior', 'KHR_materials_specular',
        'KHR_materials_sheen', 'KHR_materials_emissive_strength',
        'KHR_materials_iridescence', 'KHR_materials_anisotropy',
        'KHR_materials_pbrSpecularGlossiness', 'KHR_materials_dispersion',
    }
    extensions = []

    def collect_extensions(value):
        if isinstance(value, dict):
            for name, extension in value.get('extensions', {}).items():
                extensions.append((name, extension))
            for v in value.values():
                collect_extensions(v)
        elif isinstance(value, list):
            for v in value:
                collect_extensions(v)
    collect_extensions(gltf)
    shared |= any(other_reference(ext) or extension_image_reference(ext)
                  for _, ext in extensions)
    if shared:
        binary = bytearray(source['bin'])
        binary.extend(b'\0' * (-len(binary) % 4))
        gltf['bufferViews'].append({'buffer': 0, 'byteOffset': len(binary), 'byteLength': len(png)})
        binary.extend(png)
        gltf['images'].append({'bufferView': len(gltf['bufferViews']) - 1, 'mimeType': 'image/png'})
        texture = {'source': len(gltf['images']) - 1}
        if 'sampler' in original_texture:
            texture['sampler'] = original_texture['sampler']
        gltf['textures'].append(texture)
        texture_info['index'] = len(gltf['textures']) - 1
    else:
        def buffer_reference(value):
            if isinstance(value, dict):
                return any(k in ('buffer', 'bufferView', 'bufferViews', 'byteOffset', 'byteLength')
                           or buffer_reference(v) for k, v in value.items())
            if isinstance(value, list):
                return any(buffer_reference(v) for v in value)
            return False
        for name in set(gltf.get('extensionsUsed', [])) | set(gltf.get('extensionsRequired', [])):
            if name not in safe_extensions:
                raise ValueError(f'Cannot repack face bake BIN with unsupported extension: {name}')
        for name, extension in extensions:
            if name not in safe_extensions or buffer_reference(extension):
                raise ValueError(f'Cannot repack face bake BIN with buffer references or unsupported extension: {name}')
        binary = bytearray()
        for i, view in enumerate(gltf['bufferViews']):
            if view.get('buffer', 0) != 0:
                raise ValueError('Cannot repack face bake bufferView outside BIN buffer')
            offset, length = int(view.get('byteOffset', 0)), int(view['byteLength'])
            if offset < 0 or length < 0 or offset + length > len(source['bin']):
                raise ValueError('Cannot repack invalid face bake bufferView')
            raw = png if i == image_view else source['bin'][offset:offset + length]
            binary.extend(b'\0' * (-len(binary) % 4))
            view['byteOffset'] = len(binary)
            view['byteLength'] = len(raw)
            binary.extend(raw)
        image.pop('uri', None)
        image['mimeType'] = 'image/png'
    binary.extend(b'\0' * (-len(binary) % 4))
    gltf['buffers'][0]['byteLength'] = len(binary)
    document = json.dumps(gltf, separators=(',', ':')).encode()
    document += b' ' * (-len(document) % 4)
    baked = (struct.pack('<III', 0x46546c67, 2, 28 + len(document) + len(binary))
             + struct.pack('<I4s', len(document), b'JSON') + document
             + struct.pack('<I4s', len(binary), b'BIN\0') + bytes(binary))
    verdict = validate_source(baked)
    if not verdict['ok']:
        raise ValueError('Invalid baked source: ' + '; '.join(verdict['errors']))
    if len(baked) > MAX_BYTES:
        raise ValueError('Baked mesh exceeds the 64 MB rig upload limit')
    if replacement_masks is not None:
        replacement_masks.append(replaced)
    return baked, {'face_primitives': len(faces), 'face_triangles': sum(len(t) for _, t, _ in faces),
                   'texels_replaced': int(replaced.sum()), 'dilate_px': dilate_px}


def face_texture_preserved(baked_glb: bytes, rigged_glb: bytes, *,
                           replacement_mask=None, original_glb: bytes | None = None) -> bool:
    """Compare RGB only inside the face mask using bounded integer row tiles.

    Later re-rigs reconstruct the effective changed texels from retained textures;
    unchanged replacement texels cannot lose a correction and need no comparison.
    """
    import numpy as np
    from app.core.model_validate import parse_glb
    try:
        def decode(parsed, primitive):
            return Image.open(io.BytesIO(_primitive_basecolor(parsed, primitive)[1])).convert('RGB')
        baked, rigged = parse_glb(baked_glb), parse_glb(rigged_glb)
        primitive = baked['gltf']['meshes'][0]['primitives'][0]
        base = decode(baked, primitive)
        base_pixels = np.asarray(base)
        if replacement_mask is None and original_glb is not None:
            original = parse_glb(original_glb)
            original_image = decode(original, original['gltf']['meshes'][0]['primitives'][0])
            if original_image.size != base.size:
                return False
            original_pixels = np.asarray(original_image)
            replacement_mask = np.zeros(base_pixels.shape[:2], dtype=bool)
            for row in range(0, base.height, 256):
                replacement_mask[row:row+256] = np.any(
                    base_pixels[row:row+256] != original_pixels[row:row+256], axis=2)
            del original_pixels, original_image
        if replacement_mask is not None and replacement_mask.shape != base_pixels.shape[:2]:
            return False
        primitives = [p for mesh in rigged['gltf']['meshes'] for p in mesh['primitives']]
        if not primitives:
            return False
        decoded = {}
        for primitive in primitives:
            material = rigged['gltf']['materials'][primitive['material']]
            texture = rigged['gltf']['textures'][material['pbrMetallicRoughness']['baseColorTexture']['index']]
            image_index = texture['source']
            if image_index in decoded:
                continue
            decoded[image_index] = True
            image = decode(rigged, primitive)
            if image.size != base.size:
                image = image.resize(base.size, Image.Resampling.LANCZOS)
            pixels = np.asarray(image)
            total, count = 0, 0
            for row in range(0, base.height, 256):
                diff = np.abs(base_pixels[row:row+256].astype(np.int16)
                              - pixels[row:row+256].astype(np.int16))
                if replacement_mask is not None:
                    diff = diff[replacement_mask[row:row+256]]
                total += int(diff.sum(dtype=np.int64))
                count += diff.size
            if count and total > 2 * count:
                return False
        return True
    except (ValueError, OSError, KeyError, IndexError, TypeError):
        return False
