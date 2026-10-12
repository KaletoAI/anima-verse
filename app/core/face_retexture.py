"""Read-only eligibility and reference-photo preparation for face projection."""
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


def photo_path(character: str, signature: str, meta: dict) -> Path:
    from app.models.character import get_character_dir
    root = get_character_dir(character) / 'model_refs'
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


def check(character: str, signature: str) -> dict:
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
    return {'ok': not problems, 'problems': problems, 'warnings': warnings}


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
