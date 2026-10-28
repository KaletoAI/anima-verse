"""One-way action ingress and pre-activation inventory; never starts execution.

``local_valid`` checks body-slot group and participant capacity, never routing.
Access is derived independently for every selected slot at runtime.
"""
import copy
import json
import sqlite3
from uuid import NAMESPACE_URL, uuid4, uuid5


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


def normalize_import(document: dict, *, catalogs: dict | None = None) -> dict:
    """Return a validated canonical sidecar, or raise before the caller writes.

    Absence of ``actions`` identifies legacy author data. An explicit empty
    list means decorative, including newly created/autofurnished props. Existing
    action IDs, marker anchors and dependency references are retained. Old
    binding access points are discarded because author provenance is unknowable.
    """
    from app.core.prop_field_migration import move_fields_to_variants, _rename_sidecar_place_groups
    from app.core.prop_actions import validate_document, derive_bindings
    from app.core.props import PropDocumentInvalid, _VARIANT_STEM_RE
    from app.core.pose_catalog import activity_catalog, get_groups
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
    # Preserve supplied identities until validation.
    # Missing identities are legacy; malformed/duplicate supplied identities fail.
    for variant in variants:
        if 'uid' not in variant:
            variant['uid'] = str(uuid4())
    if 'actions' not in result:
        result['actions'] = []
        catalog = activity_catalog(catalog=None if catalogs is None else catalogs['poses'])
        prop_key = result.get('id') or result.get('prop_id') or next(
            (v['uid'] for v in variants if isinstance(v, dict)), '')
        groups = get_groups() if catalogs is None else catalogs['groups']
        for group, definition in sorted(groups.items()):
            key = definition.get('default')
            pose = catalog.get(key, {})
            if not pose.get('solo', True) or pose.get('group') != group:
                continue
            matches = [(variant, [m for m in variant.get('markers', [])
                                  if isinstance(m, dict) and m.get('group') == pose['group']])
                       for variant in variants if isinstance(variant, dict)]
            matches = [(variant, markers) for variant, markers in matches if markers]
            if not matches:
                continue
            aid = str(uuid5(NAMESPACE_URL, f'anima:prop-action:{prop_key}:{key}'))
            label = pose.get('label') or key
            result['actions'].append(dict(id=aid, name=label,
                description='', enabled=True, ability='pose', pose_key=key,
                participants=1, presence='any', interrupt_on_presence_change=False,
                phases=[], requirements=[], effects=[]))
    from app.core.pose_catalog import get_catalog
    poses = (get_catalog('pose') if catalogs is None else catalogs['poses']) if result['actions'] else {}
    prop_key = result.get('id') or result.get('prop_id') or variants[0]['uid']
    legacy_keys = set(poses) | {a.get('pose_key') for a in result['actions']
                                    if isinstance(a, dict) and isinstance(a.get('pose_key'), str)}
    legacy_ids = {str(uuid5(NAMESPACE_URL, f'anima:prop-action:{prop_key}:{key}')) for key in legacy_keys}
    for variant in variants:
        eligible = {b['action_id']: b['marker_ids'] for b in derive_bindings(result, variant, poses=poses)}
        old_bindings = variant.pop('action_bindings', [])
        for binding in old_bindings if isinstance(old_bindings, list) else []:
            if not isinstance(binding, dict) or binding.get('supported') is not False:
                continue
            aid = binding.get('action_id')
            if not isinstance(aid, str) or aid in legacy_ids:
                continue
            for marker in variant.get('markers', []):
                if marker.get('id') in eligible.get(aid, []):
                    excluded = marker.setdefault('exclude_actions', [])
                    if aid not in excluded:
                        excluded.append(aid)
    issues = validate_document(result, catalogs=catalogs)
    if any(i["severity"] == "error" for i in issues):
        raise PropDocumentInvalid(issues)
    return result


def migrate_actions(dry_run: bool = True, *, legacy_bindings: dict | None = None) -> dict:
    """Inventory before activation; optionally persist each valid normalized prop.

    Raw file reads intentionally bypass UID-persisting public getters. A failed
    document is reported, not partially repaired. This function never activates
    a runtime reader, sets sleeping, or asserts concrete-room route validity.
    """
    from app.core import props
    from app.core.prop_actions import derive_bindings
    report = dict(dry_run=dry_run, runtime_activated=False, changed=0, props=[], issues=[],
                  legacy_access_policy='Dropped binding access_points: authored provenance is not reliable')
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
                for variant in seeded.get('model_variants', []):
                    old = (legacy_bindings or {}).get(pid, {}).get(variant.get('stem'))
                    if old is not None:
                        variant['action_bindings'] = copy.deepcopy(old)
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
                        for binding in derive_bindings(normalized, variant)]
            report['props'].append(dict(prop_id=pid, changed=changed,
                variants=len(normalized['model_variants']), actions=len(normalized['actions']),
                offers=len(bindings), repair_required=sum(b['validation'] == 'repair_required' for b in bindings),
                route_checked=False, document=normalized))
            report['changed'] += int(changed)
            if changed and not dry_run:
                props._write_sidecar(pid, normalized)
    return report


def compose_binding(binding: dict, *, placement: dict, revision: str, marker_id: str) -> dict:
    """Copy binding provenance; per-marker access is composed with its marker."""
    result = copy.deepcopy(binding)
    result['supported'] = binding['supported'] and binding['validation'] == 'local_valid'
    result.update(placement_id=placement['id'], prop_id=placement['prop_id'],
                  definition_revision=revision, marker_id=marker_id, route_checked=False)
    return result


def prepare_runtime() -> dict:
    """Complete legacy prerequisites before inventory/application and job startup.

    All writes belong to the current world store. Reused migrations are
    idempotent; action validation never invents IDs before the marker migration.
    """
    from app.core.places_migration import migrate_places_once
    from app.core.prop_field_migration import migrate_prop_fields_once
    from app.core.place_group_migration import migrate_place_groups_once
    from app.core.prop_action_engine import register_owner
    from app.core.log import get_logger
    logger = get_logger("prop_action_migration")
    # Retain migration input before prerequisite store reads project old fields
    # away. These lists only enter normalize_import, never a runtime reader.
    from app.core import props
    legacy_bindings = {}
    for pid in props._all_prop_ids():
        with props._author_mutex(pid):
            try:
                raw = json.loads((props._prop_dir(pid) / props.SIDECAR_NAME).read_text(encoding='utf-8'))
            except (OSError, ValueError):
                continue  # The subsequent inventory reports unreadable documents.
            if not isinstance(raw, dict):
                continue
            variants = raw.get('model_variants', [])
            if isinstance(variants, list):
                legacy_bindings[pid] = {v.get('stem'): copy.deepcopy(v['action_bindings'])
                    for v in variants if isinstance(v, dict) and isinstance(v.get('stem'), str)
                    and 'action_bindings' in v}
    prerequisites = dict(places=migrate_places_once())
    prerequisites["fields"] = migrate_prop_fields_once()
    prerequisites["groups"] = migrate_place_groups_once()
    logger.info("Prop action migration prerequisites: %s", prerequisites)
    inventory = migrate_actions(dry_run=True, legacy_bindings=legacy_bindings)
    logger.info("Prop action migration inventory: %d props, %d changed, %d issues",
                len(inventory["props"]), inventory["changed"], len(inventory["issues"]))
    for issue in inventory["issues"]:
        logger.error("Prop action migration issue: %s", issue)
    if inventory["issues"]:
        raise RuntimeError("Prop action migration requires repair; inspect startup inventory")
    applied = migrate_actions(dry_run=False, legacy_bindings=legacy_bindings)
    if applied["issues"]:
        for issue in applied["issues"]:
            logger.error("Prop action migration application issue: %s", issue)
        raise RuntimeError("Prop action migration application requires repair")
    register_owner()
    return dict(prerequisites=prerequisites, inventory=inventory, applied=applied)
