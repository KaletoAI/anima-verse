"""One-way action ingress and pre-activation inventory; never starts execution.

``local_valid`` only checks a binding's own footprint, NOT a route through a
room. Missing orientation/geometry is repair_required and never supported.
"""
import copy
import json
import math
import sqlite3
from uuid import NAMESPACE_URL, uuid4, uuid5

def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _catalog_snapshot() -> dict:
    """Copy existing DB/WAL once, then SELECT read-only without touching source.

    SQLite WAL readers can create/update -shm even in mode=ro. Inventory runs
    off a private disposable copy instead; source change tokens bracket copying.
    Not used by imports, offers or ordinary author validation.
    """
    import shutil
    import tempfile
    from pathlib import Path
    from app.core.db import get_db_path
    from app.core import pose_catalog, prompt_filters
    from app.models.character_template import list_templates, get_template
    from app.core.stat_rules import template_rules
    world_poses, world_groups, world_conditions = {}, {}, {}
    database = get_db_path()
    wal = database.with_name(database.name + '-wal')

    def token(path):
        try:
            stat = path.stat()
            return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
        except FileNotFoundError:
            return None

    before = (token(database), token(wal))
    if before[0] is not None:
        with tempfile.TemporaryDirectory(prefix='prop-action-catalog-') as temporary:
            target = Path(temporary) / 'world.db'
            shutil.copyfile(database, target)
            if before[1] is not None:
                shutil.copyfile(wal, target.with_name(target.name + '-wal'))
            if before != (token(database), token(wal)):
                raise ValueError('World catalog changed while copying; snapshot is inconsistent')
            connection = sqlite3.connect(target.as_uri() + '?mode=ro', uri=True)
            try:
                tables = {row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")}
                if pose_catalog.WORLD_TABLE in tables:
                    for kind, key, raw in connection.execute(
                            f'SELECT kind,key,doc FROM {pose_catalog.WORLD_TABLE} '
                            "WHERE axis='pose' AND kind IN ('entry','group')"):
                        document = json.loads(raw)
                        if not isinstance(document, dict):
                            raise ValueError(f'Unreadable world pose: {key}')
                        (world_poses if kind == 'entry' else world_groups)[key] = document
                if 'prompt_filters' in tables:
                    world_conditions = {row[0]: bool(row[1]) for row in connection.execute(
                        'SELECT id,enabled FROM prompt_filters')}
            finally:
                connection.close()
    elif before[1] is not None:
        raise ValueError('World catalog has WAL but no database')
    conditions = {row['id']: row.get('enabled', True)
                  for row in prompt_filters._load_shared() if row.get('id')}
    conditions.update(world_conditions)
    return dict(poses=pose_catalog._load('pose', world=world_poses),
                groups=pose_catalog._load_groups(world=world_groups),
                conditions={key for key, enabled in conditions.items() if enabled},
                stats={key for row in list_templates()
                       for key in template_rules(get_template(row['name']) or {})})


def _access(variant, markers):
    """Suggest one common ground approach outside the oriented local footprint."""
    width, depth = variant.get('width_m'), variant.get('depth_m')
    if not all(_finite(v) and v > 0 for v in (width, depth)) or not markers:
        return {}, 'repair_required'
    if any(not isinstance(m.get('at'), list) or len(m['at']) != 3
           or not all(_finite(v) for v in m['at']) for m in markers):
        return {}, 'repair_required'
    facings = [marker.get('facing') for marker in markers]
    if not all(_finite(v) for v in facings) or len({v % 360 for v in facings}) != 1:
        return {}, 'repair_required'
    angle = math.radians(facings[0])
    # Ray/rectangle intersection + 45cm actor clearance. Coordinates already
    # are oriented local metres: do not apply the raw mesh orientation again.
    sx, sz = math.sin(angle), math.cos(angle)
    edges = [half / abs(component) for half, component in
             ((width / 2, sx), (depth / 2, sz)) if abs(component) > 1e-9]
    distance = min(edges) + .45
    return {'actor': {'x': round(sx * distance, 6), 'z': round(sz * distance, 6),
                      'yaw': (facings[0] + 180) % 360}}, 'local_valid'


def normalize_import(document: dict, *, catalogs: dict | None = None) -> dict:
    """Return a validated canonical sidecar, or raise before the caller writes.

    Absence of ``actions`` identifies legacy author data. An explicit empty
    list means decorative, including newly created/autofurnished props. Existing
    action IDs, marker anchors and dependency references are retained. Unsafe
    access points stay visible but their binding is downgraded, never relocated.
    """
    from app.core.prop_field_migration import move_fields_to_variants, _rename_sidecar_place_groups
    from app.core.prop_actions import validate_document
    from app.core.props import PropDocumentInvalid, _VARIANT_STEM_RE
    from app.core.pose_catalog import activity_catalog
    from app.core.world_ops import _place_ref
    if not isinstance(document, dict):
        raise PropDocumentInvalid([dict(path='', code='invalid_type', message='Expected a sidecar object', severity='error')])
    result = copy.deepcopy(document)
    raw_variants = result.get('model_variants')
    if 'model_variants' in result and (
            not isinstance(raw_variants, list) or not raw_variants
            or any(not isinstance(v, dict) for v in raw_variants)):
        raise PropDocumentInvalid([dict(path='model_variants', code='invalid_type',
            message='Expected a nonempty list of variant objects', severity='error')])
    stems = set()
    for index, variant in enumerate(raw_variants or []):
        stem = variant.get('stem')
        if not isinstance(stem, str) or not _VARIANT_STEM_RE.fullmatch(stem) or stem in stems:
            raise PropDocumentInvalid([dict(path=f'model_variants.{index}.stem',
                code='invalid_variant_stem', message='Expected a unique supported model stem',
                severity='error')])
        stems.add(stem)
    # The store shapes marker IDs when it writes. Refuse any input whose IDs
    # would change (or collide) before that lossy boundary can break bindings.
    marker_homes = [('markers', result.get('markers', []))] + [
        (f'model_variants.{i}.markers', variant.get('markers', []))
        for i, variant in enumerate(raw_variants or [])]
    for path, markers in marker_homes:
        if not isinstance(markers, list):
            raise PropDocumentInvalid([dict(path=path, code='invalid_type',
                message='Expected a marker list', severity='error')])
        seen_markers = set()
        for index, marker in enumerate(markers):
            identity = marker.get('id') if isinstance(marker, dict) else None
            canonical = isinstance(identity, str) and bool(identity) and _place_ref(identity) == identity
            duplicate = canonical and identity in seen_markers
            if not canonical or duplicate:
                raise PropDocumentInvalid([dict(path=f'{path}.{index}.id',
                    code='duplicate_marker_id' if duplicate else 'invalid_marker_id',
                    message='Expected a unique canonical stored marker ID', severity='error')])
            seen_markers.add(identity)
    move_fields_to_variants(result, known_groups=None if catalogs is None else catalogs['groups'])
    variants = result.setdefault('model_variants', [{'stem': 'model', 'active': True}])
    _rename_sidecar_place_groups(result)
    # Do not sanitize author bindings through a lossy projection before validation.
    # Missing identities are legacy; malformed/duplicate supplied identities fail.
    for variant in variants:
        if 'uid' not in variant:
            variant['uid'] = str(uuid4())
        variant.setdefault('action_bindings', [])
    if 'actions' not in result:
        result['actions'] = []
        catalog = activity_catalog(catalog=None if catalogs is None else catalogs['poses'])
        prop_key = result.get('id') or result.get('prop_id') or next(
            (v['uid'] for v in variants if isinstance(v, dict)), '')
        for key, pose in sorted(catalog.items()):
            if not pose.get('solo', True) or not pose.get('group'):
                continue
            matches = [(variant, [m for m in variant.get('markers', [])
                                  if isinstance(m, dict) and m.get('group') == pose['group']])
                       for variant in variants if isinstance(variant, dict)]
            matches = [(variant, markers) for variant, markers in matches if markers]
            if not matches:
                continue
            aid = str(uuid5(NAMESPACE_URL, f'anima:prop-action:{prop_key}:{key}'))
            label = 'Schlafpose (ohne Schlafzustand)' if key == 'sleeping' else pose.get('label') or key
            result['actions'].append(dict(id=aid, name=label,
                description='', enabled=True, ability='pose', pose_key=key,
                participants=1, presence='any', interrupt_on_presence_change=False,
                phases=[], requirements=[], effects=[]))
            for variant, markers in matches:
                points, validation = _access(variant, markers)
                variant['action_bindings'].append(dict(action_id=aid,
                    variant_uid=variant['uid'], supported=validation == 'local_valid',
                    marker_ids=[m.get('id') for m in markers], access_points=points,
                    validation=validation))
    issues = validate_document(result, catalogs=catalogs)
    if issues:
        raise PropDocumentInvalid(issues)
    from app.core.room_stand import BODY_R_M, _in_footprint
    for variant in variants:
        width, depth = variant.get('width_m'), variant.get('depth_m')
        measurable = all(_finite(v) and v > 0 for v in (width, depth))
        box = dict(at=[0, 0], yaw=0, width_m=width, depth_m=depth)
        for binding in variant['action_bindings']:
            if binding['supported'] and binding['validation'] != 'local_valid':
                binding['supported'] = False
            elif binding['supported'] and (
                    not measurable or any(_in_footprint(point['x'], point['z'], box, BODY_R_M)
                                          for point in binding['access_points'].values())):
                # Keep the authored point visible for repair, never move it to
                # a guessed working position or mistake this for a room route.
                binding.update(supported=False, validation='repair_required')
    return result


def migrate_actions(dry_run: bool = True) -> dict:
    """Inventory before activation; optionally persist each valid normalized prop.

    Raw file reads intentionally bypass UID-persisting public getters. A failed
    document is reported, not partially repaired. This function never activates
    a runtime reader, sets sleeping, or asserts concrete-room route validity.
    """
    from app.core import props
    report = dict(dry_run=dry_run, runtime_activated=False, changed=0, props=[], issues=[])
    # This snapshot deliberately bypasses all lazy DB connection creation.
    try:
        catalogs = _catalog_snapshot() if dry_run else None
    except (OSError, ValueError, sqlite3.Error) as error:
        report['issues'].append(dict(code='catalog_snapshot_unavailable', message=str(error)))
        return report
    for pid in props._all_prop_ids():
        with props._author_mutex(pid):
            path = props._prop_dir(pid) / props.SIDECAR_NAME
            try:
                original = json.loads(path.read_text(encoding='utf-8'))
                if not isinstance(original, dict):
                    raise props.PropDocumentInvalid([dict(path='', code='invalid_type',
                        message='Expected a sidecar object', severity='error')])
                # IDs in real packs can be absent from the sidecar; use its store
                # identity for deterministic action IDs without adding a field.
                seeded = copy.deepcopy(original)
                seeded['id'] = pid
                normalized = normalize_import(seeded, catalogs=catalogs)
                if 'id' in original:
                    normalized['id'] = original['id']
                else:
                    normalized.pop('id', None)
            except (OSError, ValueError, TypeError) as error:
                report['issues'].append(dict(prop_id=pid, issues=getattr(error, 'issues', []), message=str(error)))
                continue
            changed = normalized != original
            bindings = [binding for variant in normalized['model_variants']
                        for binding in variant.get('action_bindings', [])]
            report['props'].append(dict(prop_id=pid, changed=changed,
                variants=len(normalized['model_variants']), actions=len(normalized['actions']),
                offers=len(bindings), repair_required=sum(b['validation'] == 'repair_required' for b in bindings),
                route_checked=False, document=normalized))
            report['changed'] += int(changed)
            if changed and not dry_run:
                props._write_sidecar(pid, normalized)
    return report


def compose_binding(binding: dict, *, placement: dict, revision: str) -> dict:
    """Binding provenance and location-local XZ approach; Y is added by room floor."""
    result = copy.deepcopy(binding)
    result['supported'] = binding['supported'] and binding['validation'] == 'local_valid'
    angle = math.radians(placement['yaw'])
    cos, sin = math.cos(angle), math.sin(angle)
    px, pz = placement['at']
    result['access_points'] = {role: dict(
        x=round(px + point['x'] * cos + point['z'] * sin, 6),
        z=round(pz - point['x'] * sin + point['z'] * cos, 6),
        yaw=(point['yaw'] + placement['yaw']) % 360)
        for role, point in binding['access_points'].items()}
    result.update(placement_id=placement['id'], prop_id=placement['prop_id'],
                  definition_revision=revision, route_checked=False)
    return result
