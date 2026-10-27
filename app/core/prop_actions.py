"""Prop action authoring contract. Validation is read-only and never executes actions."""
import math
from uuid import UUID
from typing import TypedDict, Literal


class Issue(TypedDict):
    path: str
    code: str
    message: str
    severity: Literal['error', 'warning']

_TYPE_FIELDS = {
    'stat': {'stat', 'op', 'value'},
    'condition': {'condition_id', 'present'},
    'stat_delta': {'stat', 'amount'},
    'mood': {'mood'},
    'condition_add': {'condition_id', 'duration_game_s', 'repeat'},
    'condition_remove': {'condition_id'},
}


def validate_document(prop: dict, *, catalogs: dict | None = None) -> list[Issue]:
    """Return issues; optional read-only catalog snapshot avoids world DB getters."""
    if not isinstance(prop, dict):
        return [dict(path='', code='invalid_type', message='Expected an object', severity='error')]
    from app.models.character_template import list_templates, get_template
    from app.core.stat_rules import template_rules
    from app.core.prompt_filters import load_filters
    if catalogs is None:
        stats = ({key for entry in list_templates() for key in
                  template_rules(get_template(entry['name']) or {})}
                 if prop.get('actions') else set())
        conditions = ({f.get('id') for f in load_filters() if f.get('enabled', True)}
                      if prop.get('actions') else set())
    else:
        stats, conditions = catalogs['stats'], catalogs['conditions']
    issues = []

    def issue(path, code, message):
        issues.append(dict(path=path, code=code, message=message, severity='error'))

    def text(value):
        return isinstance(value, str) and bool(value.strip())

    def number(value, positive=False):
        return (isinstance(value, (int, float)) and not isinstance(value, bool)
                and math.isfinite(value) and (not positive or value > 0))

    def rows(value, path):
        if not isinstance(value, list):
            issue(path, 'invalid_type', 'Expected a list')
            return []
        return value

    def fields(row, allowed, path):
        for key in row.keys() - allowed:
            issue(path + '.' + str(key), 'unknown_field', 'Unsupported author field')

    def identities(entries, path):
        seen = set()
        for i, row in enumerate(entries):
            p = f'{path}.{i}'
            if not isinstance(row, dict):
                issue(p, 'invalid_type', 'Expected an object')
                continue
            key = row.get('id')
            duplicate = isinstance(key, str) and key in seen
            if not text(key) or duplicate:
                issue(p + '.id', 'duplicate_id' if duplicate else 'invalid_id',
                      'IDs must be nonempty and unique')
            if isinstance(key, str):
                seen.add(key)

    actions = rows(prop.get('actions', []), 'actions')
    identities(actions, 'actions')
    action_map = {}
    for i, action in enumerate(actions):
        p = f'actions.{i}'
        if not isinstance(action, dict):
            continue
        fields(action, {'id', 'name', 'description', 'enabled', 'ability', 'pose_key',
                        'participants', 'presence', 'interrupt_on_presence_change',
                        'phases', 'requirements', 'effects'}, p)
        if text(action.get('id')):
            action_map[action['id']] = action
        for field in ('name',):
            if not text(action.get(field)):
                issue(p + '.' + field, 'invalid_text', 'A name is required')
        for field in ('description', 'pose_key'):
            if not isinstance(action.get(field), str):
                issue(p + '.' + field, 'invalid_type', 'Expected text')
        for field in ('enabled', 'interrupt_on_presence_change'):
            if not isinstance(action.get(field), bool):
                issue(p + '.' + field, 'invalid_type', 'Expected boolean')
        ability = action.get('ability')
        if ability not in ('pose', 'combined', 'sleep', 'pair'):
            issue(p + '.ability', 'unsupported_ability', 'Unknown ability')
        pair = ability == 'pair'
        if type(action.get('participants')) is not int or action.get('participants') != (2 if pair else 1):
            issue(p + '.participants', 'unsupported_combination', 'Pair actions require two participants; others one')
        if action.get('presence') not in ('any', 'alone', 'others', 'participants_only'):
            issue(p + '.presence', 'invalid_presence', 'Unknown presence policy')
        phases = rows(action.get('phases'), p + '.phases')
        identities(phases, p + '.phases')
        if (ability == 'combined' and not phases) or (ability != 'combined' and phases):
            issue(p + '.phases', 'unsupported_combination', 'Only combined actions have nonempty phases')
        for j, phase in enumerate(phases):
            if not isinstance(phase, dict):
                continue
            fields(phase, {'id', 'label', 'duration_game_s', 'pose_key'}, f'{p}.phases.{j}')
            if not text(phase.get('label')) or not number(phase.get('duration_game_s'), True) or not isinstance(phase.get('pose_key'), str):
                issue(f'{p}.phases.{j}', 'invalid_phase', 'Phase requires label, pose key and positive finite duration')
        requirements = rows(action.get('requirements'), p + '.requirements')
        identities(requirements, p + '.requirements')
        effects = rows(action.get('effects'), p + '.effects')
        identities(effects, p + '.effects')
        for kind, entries in (('requirements', requirements), ('effects', effects)):
            for j, entry in enumerate(entries):
                q = f'{p}.{kind}.{j}'
                if not isinstance(entry, dict):
                    continue
                if entry.get('target') not in (('actor', 'partner', 'both') if pair else ('actor',)):
                    issue(q + '.target', 'invalid_target', 'Target does not match participants')
                typ = entry.get('type')
                allowed = _TYPE_FIELDS.get(typ, set()) if isinstance(typ, str) else set()
                fields(entry, {'id', 'target', 'type'} | allowed |
                       ({'when'} if kind == 'effects' else set()), q)
                if kind == 'requirements':
                    if typ == 'stat':
                        if not text(entry.get('stat')) or entry['stat'] not in stats:
                            issue(q + '.stat', 'unknown_requirement_reference', 'Unknown stat')
                        if entry.get('op') not in ('lt', 'le', 'eq', 'ge', 'gt') or not number(entry.get('value')):
                            issue(q, 'invalid_requirement', 'Stat requires comparison and finite value')
                    elif typ == 'condition':
                        if not text(entry.get('condition_id')) or entry['condition_id'] not in conditions:
                            issue(q + '.condition_id', 'unknown_requirement_reference', 'Unknown condition')
                        if not isinstance(entry.get('present'), bool):
                            issue(q + '.present', 'invalid_type', 'Expected boolean')
                    else:
                        issue(q + '.type', 'invalid_requirement', 'Unknown requirement type')
                    continue
                when = entry.get('when')
                if when not in ('start', 'success', 'active'):
                    issue(q + '.when', 'invalid_effect', 'Unknown effect timing')
                if when == 'success' and ability in ('pose', 'pair'):
                    issue(q + '.when', 'unsupported_combination', 'This ability has no completion reward')
                if when == 'active' and (typ != 'stat_delta' or ability == 'sleep'):
                    issue(q + '.when', 'unsupported_combination', 'Only awake stat deltas may have active rates')
                if typ == 'stat_delta':
                    if not text(entry.get('stat')) or entry['stat'] not in stats:
                        issue(q + '.stat', 'unknown_stat', 'Unknown stat')
                    if not number(entry.get('amount')):
                        issue(q + '.amount', 'invalid_number', 'Expected finite amount')
                elif typ == 'mood':
                    if not text(entry.get('mood')):
                        issue(q + '.mood', 'invalid_text', 'Mood text is required')
                elif typ in ('condition_add', 'condition_remove'):
                    if not text(entry.get('condition_id')) or entry['condition_id'] not in conditions:
                        issue(q + '.condition_id', 'unknown_condition', 'Unknown condition')
                    if typ == 'condition_add' and (not number(entry.get('duration_game_s'), True) or entry.get('repeat') not in ('refresh', 'ignore')):
                        issue(q, 'invalid_effect', 'Condition addition requires duration and repeat policy')
                else:
                    issue(q + '.type', 'invalid_effect', 'Unknown effect type')
    seen_uids = set()
    for i, variant in enumerate(rows(prop.get('model_variants', []), 'model_variants')):
        p = f'model_variants.{i}'
        if not isinstance(variant, dict):
            issue(p, 'invalid_type', 'Expected an object')
            continue
        uid = variant.get('uid')
        try:
            if not isinstance(uid, str) or str(UUID(uid)) != uid or uid in seen_uids:
                raise ValueError()
            seen_uids.add(uid)
        except (ValueError, TypeError, AttributeError):
            issue(p + '.uid', 'invalid_variant_uid', 'Expected a unique canonical UUID')
        markers = {m['id']: m for m in rows(variant.get('markers', []), p + '.markers')
                   if isinstance(m, dict) and text(m.get('id'))}
        bound = set()
        for j, binding in enumerate(rows(variant.get('action_bindings', []), p + '.action_bindings')):
            q = f'{p}.action_bindings.{j}'
            if not isinstance(binding, dict):
                issue(q, 'invalid_type', 'Expected an object')
                continue
            fields(binding, {'action_id', 'variant_uid', 'supported', 'marker_ids',
                             'access_points', 'validation'}, q)
            aid = binding.get('action_id')
            action = action_map.get(aid) if isinstance(aid, str) else None
            if not action or (isinstance(aid, str) and aid in bound):
                issue(q + '.action_id', 'invalid_action_reference', 'Unknown or duplicate action binding')
            if isinstance(aid, str):
                bound.add(aid)
            if binding.get('variant_uid') != uid:
                issue(q + '.variant_uid', 'invalid_variant_reference', 'Binding must name its owning variant')
            if not isinstance(binding.get('supported'), bool):
                issue(q + '.supported', 'invalid_type', 'Expected boolean')
            if binding.get('validation') not in ('suggested', 'local_valid', 'repair_required'):
                issue(q + '.validation', 'invalid_validation', 'Unknown binding validation state')
            mids = rows(binding.get('marker_ids'), q + '.marker_ids')
            if any(not isinstance(mid, str) or mid not in markers for mid in mids) or len(set(str(m) for m in mids)) != len(mids):
                issue(q + '.marker_ids', 'invalid_marker_reference', 'Markers must exist and be unique')
            access = binding.get('access_points')
            roles = ('actor', 'partner') if action and action.get('participants') == 2 else ('actor',)
            if not isinstance(access, dict) or any(role not in roles for role in access):
                issue(q + '.access_points', 'invalid_access_points', 'Expected role access points')
            else:
                for role, point in access.items():
                    if (not isinstance(point, dict) or set(point) != {'x', 'z', 'yaw'}
                            or not all(number(point.get(key)) for key in ('x', 'z', 'yaw'))):
                        issue(q + '.access_points.' + role, 'invalid_access_point', 'Expected finite local x, z and yaw')
                if binding.get('supported') and (not mids or any(role not in access for role in roles)):
                    issue(q, 'incomplete_binding', 'Supported binding needs markers and every role access')
                if binding.get('supported') and len(roles) == 2:
                    from app.core.world_ops import _capacity
                    if any(_capacity(markers[mid].get('capacity')) < 2
                           for mid in mids if isinstance(mid, str) and mid in markers):
                        issue(q + '.marker_ids', 'incompatible_marker',
                              'Pair alternatives each need two slots on one shared marker')
    return issues
