"""House specifications and in-memory locations for the existing hull pipeline."""
from copy import deepcopy
import math
from typing import Any
from pathlib import Path
import threading

from app.core import door_styles, hull_styles, surface_textures
from app.core.hull_util import tone

HOUSE_DEFAULTS: dict = {
    "style": "steinhaus", "storeys": 2, "storey_m": 3.0, "units": 1,
    "unit_overrides": [], "wall": "", "door": {"style": "", "at": 0.5},
    "balconies": None, "overrides": {},
}


def _number(value, low, high, default):
    try:
        value = float(value)
    except (ValueError, TypeError, OverflowError):
        return default
    return max(low, min(high, value)) if math.isfinite(value) else default


def _dict(value):
    return value if isinstance(value, dict) else {}


def _choice(value, choices, default):
    return value if isinstance(value, str) and value in choices else default


def validate_house_spec(raw: Any, footprint_m: tuple[float, float]) -> dict:
    """Clamp a house spec; dimensions remain external to the stored spec."""
    width, depth = footprint_m
    if not (math.isfinite(width) and math.isfinite(depth) and width > 0 and depth > 0):
        raise ValueError("footprint")
    raw = _dict(raw)
    result = deepcopy(HOUSE_DEFAULTS)
    desc = hull_styles.validate_description(raw, hull_styles.load_styles())
    result.update(desc)
    result['storeys'] = int(_number(raw.get('storeys'), 1, 12, 2))
    result['storey_m'] = _number(raw.get('storey_m'), 2.6, 4.5, 3.0)
    result['units'] = min(int(_number(raw.get('units'), 1, 8, 1)),
                          max(1, math.floor(width / 2.5)))
    entries = raw.get('unit_overrides')
    entries = entries if isinstance(entries, list) else []
    result['unit_overrides'] = []
    for index in range(result['units']):
        entry = _dict(entries[index]) if index < len(entries) else {}
        result['unit_overrides'].append({key: colour for key in
            ('tint', 'door_color', 'roof_tint') if (colour := tone(entry.get(key), ''))})
    wall = raw.get('wall')
    result['wall'] = surface_textures.safe_kind(wall) if isinstance(wall, str) else ''
    door = _dict(raw.get('door'))
    result['door'] = {
        'style': _choice(door.get('style'), door_styles.load_door_styles(), ''),
        'at': _number(door.get('at'), .1, .9, .5),
    }
    balcony = _dict(raw.get('balconies'))
    if balcony and balcony.get('edge', 'front') == 'front':
        levels = balcony.get('storeys')
        levels = levels if isinstance(levels, list) else []
        result['balconies'] = {
            'edge': 'front',
            'storeys': sorted({lv for lv in levels if type(lv) is int
                               and 1 <= lv < result['storeys']}),
            'layout': _choice(balcony.get('layout'), ('per_window', 'continuous'), 'per_window'),
            'depth_m': _number(balcony.get('depth_m'), .5, 1.6, .9),
            'railing': _choice(balcony.get('railing'), ('iron', 'solid', 'glass'), 'iron'),
        }
    return result


def synthetic_locations(spec: dict, footprint_m: tuple[float, float]) -> list[dict]:
    """Split the centred footprint along x; edge 2 always faces +z.

    Corridor rooms use the server's ensure_floor_rooms shape. Their extent is
    the complement of ordinary rooms within the map outline, so no layout is
    needed to cover the whole footprint.
    """
    width, depth = footprint_m
    count = spec['units']
    locations = []
    for index in range(count):
        left = -width / 2 + index * width / count
        right = -width / 2 + (index + 1) * width / count
        opening = dict(type='door', level=0, edge=2, at=spec['door']['at'],
                       width_m=1.0, height_m=2.1)
        if spec['door']['style']:
            opening['door_style'] = spec['door']['style']
        map3d = dict(outline=[[left,-depth/2], [right,-depth/2],
                              [right,depth/2], [left,depth/2]],
                     storey_height_m=spec['storey_m'], hull_openings=[opening])
        if spec['wall']:
            map3d['wall_kind'] = spec['wall']
        locations.append(dict(id=f'house-unit-{index}', name=f'House unit {index}',
            map3d=map3d, rooms=[dict(id='__floor__0', level=0, name='',
                                   description='', activities=[])]))
    return locations


def unit_description(spec: dict, index: int) -> dict:
    """Return RAW overrides, including fields validated by later hull tasks."""
    if not 0 <= index < spec['units']:
        raise IndexError(index)
    overrides = deepcopy(spec['overrides'])
    # One seed for the whole row: the hull draws the roof overhang from it,
    # so per-unit seeds would give a jagged eaves line; tints vary the units.
    roof = hull_styles.get_style(spec['style'])['roof']
    overrides.setdefault('roof_form', roof['forms'][0])
    overrides.setdefault('pitch_deg', sum(roof['pitch_deg']) / 2)
    overrides.update(storeys_total=spec['storeys'], blind_windows=True, blind_recess=True)
    overrides.update(deepcopy(spec['unit_overrides'][index]))
    # Rectangle edges 1 and 3 face +x and -x respectively.
    overrides['party_edges'] = ([3] if index > 0 else []) + (
        [1] if index < spec['units'] - 1 else [])
    if spec['units'] > 1:
        overrides['ridge'] = 'width'
    if spec['balconies'] is not None:
        overrides['balconies'] = deepcopy(spec['balconies'])
    return dict(style=spec['style'], seed=spec.get('seed', 0), overrides=overrides)


# The guard covers the whole prop, including builds of different variants.
_running: set[str] = set()
_running_lock = threading.Lock()


def set_house_spec(prop_id: str, variant: int, raw: Any) -> dict:
    """Save a validated specification through the prop author transaction."""
    from app.core import props
    return props.set_variant_house(prop_id, variant, raw)


def _build_locations(spec: dict, footprint_m) -> list[dict]:
    """Inset external wall baselines so outer shell faces meet the footprint."""
    from app.core.hull_walls import wall_offsets
    locations = synthetic_locations(spec, footprint_m)
    outer = wall_offsets(hull_styles.get_style(spec['style']), 0)[1]
    for i, loc in enumerate(locations):
        ring = loc['map3d']['outline']
        for index, point in enumerate(ring):
            if i == 0 and index in (0, 3):
                point[0] += outer
            if i == spec['units'] - 1 and index in (1, 2):
                point[0] -= outer
            point[1] += outer if index in (0, 1) else -outer
    return locations


def house_job(prop_id: str, variant: int, *, tex_dir: Path) -> dict:
    """Merge synthetic unit jobs in Blender coordinates (x, -z, y)."""
    import hashlib
    import json
    from app.core import hull_model, props
    ctx = props._edit_variant(prop_id, variant)
    if not ctx or not ctx[2][ctx[3]].get('house'):
        raise ValueError('save the house spec first')
    house = ctx[2][ctx[3]]['house']
    spec, footprint = house['spec'], house['footprint_m']
    job = {'kind': 'house', 'tiers': {t: {'meshes': []} for t in ('full', 'low')},
           'materials': [], 'textures': {}, 'extras': {},
           'export': {'full': 'house_full.glb', 'low': 'house_low.glb'},
           'description': deepcopy(spec)}
    for i, loc in enumerate(_build_locations(spec, footprint)):
        unit = hull_model.build_job(f'house-unit-{i}', unit_description(spec, i),
                                    location=loc, tex_dir=Path(tex_dir) / f'u{i}')
        if not unit.get('ok', True):
            raise ValueError(unit.get('error') or 'unit build failed')
        for mat in unit['materials']:
            mat = deepcopy(mat)
            mat['name'] = f'u{i}/' + mat['name']
            if mat.get('texture'):
                mat['texture'] = f'u{i}_' + mat['texture']
            job['materials'].append(mat)
        job['textures'].update({f'u{i}_{key}': path for key, path in unit['textures'].items()})
        for tier in job['tiers']:
            for mesh in unit['tiers'][tier]['meshes']:
                mesh = deepcopy(mesh)
                mesh['name'] = f'u{i}/' + mesh['name']
                mesh['material'] = f'u{i}/' + mesh['material']
                job['tiers'][tier]['meshes'].append(mesh)
    for tier, payload in job['tiers'].items():
        points = [p for mesh in payload['meshes'] for p in mesh['vertices']]
        if not points:
            raise ValueError('empty house geometry')
        hx = max(abs(p[0]) for p in points)
        hz = max(abs(p[1]) for p in points)
        floor = min(p[2] for p in points)
        for sign in (1, -1):
            x, z = sign * hx, sign * hz
            payload['meshes'].append({
                'name': f'bounds_keeper_{tier}_{sign}', 'material': job['materials'][0]['name'],
                'vertices': [[x, -z, floor], [x-sign*.02, -z, floor],
                             [x, -(z-sign*.02), floor]], 'faces': [[0, 1, 2]],
                'uvs': [[[0, 0], [1, 0], [0, 1]]], 'colors': [[1, 1, 1]]})
    job['fingerprint'] = hashlib.sha256(json.dumps(
        {'spec': spec, 'footprint_m': footprint,
         'tiers': job['tiers'], 'materials': job['materials']}, sort_keys=True).encode()).hexdigest()
    return job


def build_house_variant(prop_id: str, variant: int) -> dict:
    """Run the generic hull executor and land both tiers as one house model."""
    import json
    import tempfile
    from app.blender import runner
    from app.core import props
    from app.core.hull_util import timeout_s
    from app.core.scene_recipe import invalidate_prop_lib_token
    failure = {'ok': False, 'error': '', 'file': ''}
    if not runner.is_available():
        return {**failure, 'error': 'blender_unavailable'}
    try:
        with tempfile.TemporaryDirectory(prefix='av-house-') as temporary:
            directory = Path(temporary)
            job = house_job(prop_id, variant, tex_dir=directory / 'textures')
            job_file = directory / 'job.json'
            job_file.write_text(json.dumps(job, sort_keys=True), encoding='utf-8')
            out = directory / 'out'
            out.mkdir()
            result = runner.run('hull_build', inputs={'job': job_file, **job['textures']},
                                out_dir=out, timeout_s=timeout_s())
            if not result.get('ok'):
                return {**failure, 'error': str(result.get('error') or 'build failed')}
            outputs = result.get('outputs') or {}
            files = {t: Path(outputs.get(t) or '') for t in ('full', 'low')}
            if not all(p.is_file() for p in files.values()):
                return {**failure, 'error': 'no glb produced'}
            blobs = {t: p.read_bytes() for t, p in files.items()}
            bounds = props.glb_bounds(blobs['full'])
            if bounds is None:
                return {**failure, 'error': 'unmeasurable glb'}
            dims = dict(zip(('width_m', 'height_m', 'depth_m'),
                            (b-a for a, b in zip(*bounds))))
            if any(v <= 0 for v in dims.values()):
                return {**failure, 'error': 'empty glb bounds'}
            filename = props.save_house_models(prop_id, variant, blobs, job['description'], job['fingerprint'])
            props.set_variant_dims(prop_id, variant, dims)
        props._store_bbox(prop_id, variant, landing=True)
        invalidate_prop_lib_token()
        return {'ok': True, 'error': '', 'file': filename}
    except Exception as error:
        return {**failure, 'error': str(error)}


def trigger_house_build(prop_id: str, variant: int) -> bool:
    """Start one tracked daemon build per prop, releasing the guard on failure."""
    from app.core import props
    prop_id = props.safe_prop_id(prop_id)
    with _running_lock:
        if prop_id in _running:
            return False
        _running.add(prop_id)

    def run():
        from app.core.task_queue import get_task_queue
        task_id, error = '', ''
        try:
            name = props.read_sidecar(prop_id).get('name') or prop_id
            try:
                task_id = get_task_queue().track_start(
                    'model3d_generation', f'House: {name} v{variant}', start_running=True)
            except Exception:
                pass
            result = build_house_variant(prop_id, variant)
            error = '' if result.get('ok') else str(result.get('error') or 'failed')
        except Exception as exc:
            error = str(exc)
        finally:
            with _running_lock:
                _running.discard(prop_id)
            if task_id:
                try:
                    get_task_queue().track_finish(task_id, error=error)
                except Exception:
                    pass
    try:
        threading.Thread(target=run, daemon=True).start()
    except Exception:
        with _running_lock:
            _running.discard(prop_id)
        raise
    return True
