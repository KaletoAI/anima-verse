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


def derive_bindings(document: dict, variant: dict, *, poses: dict | None = None) -> list[dict]:
    """Derive every action's eligible body markers from its entry presentation.

    Empty bindings are useful to author previews; composition only publishes a
    binding on its matching markers. No author-maintained references are read.
    """
    from app.core.pose_catalog import get_catalog
    from app.core.prop_action_access import entry_pose
    from app.core.world_ops import _capacity
    poses = get_catalog('pose') if poses is None else poses
    result = []
    actions = document.get('actions', [])
    markers = variant.get('markers', [])
    if not isinstance(actions, list) or not isinstance(markers, list):
        return []
    for action in actions:
        if not isinstance(action, dict):
            continue
        key = entry_pose(action)
        group = 'lie' if action.get('ability') == 'sleep' else poses.get(key if isinstance(key, str) else '', {}).get('group')
        required = 2 if action.get('ability') == 'pair' else action.get('participants', 1)
        mids = [m['id'] for m in markers
                if isinstance(m, dict) and m.get('id') and group and m.get('group') == group
                and type(required) is int and _capacity(m.get('capacity')) >= required
                and isinstance(m.get('exclude_actions', []), list)
                and action.get('id') not in m.get('exclude_actions', [])]
        result.append(dict(action_id=action.get('id'), variant_uid=variant.get('uid'),
                           marker_ids=mids, supported=bool(mids),
                           validation='local_valid' if mids else 'repair_required',
                           reason='' if mids else 'no_matching_place'))
    return result


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
    from app.core.pose_catalog import get_catalog
    pose_catalog = (get_catalog('pose') if catalogs is None else catalogs['poses']) if actions else {}
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
        if 'action_bindings' in variant:
            issue(p + '.action_bindings', 'unknown_field', 'Unsupported author field')
        marker_rows = rows(variant.get('markers', []), p + '.markers')
        for marker_index, marker in enumerate(marker_rows):
            if not isinstance(marker, dict):
                continue
            exclusions = rows(marker.get('exclude_actions', []), f'{p}.markers.{marker_index}.exclude_actions')
            if any(not isinstance(aid, str) or aid not in action_map for aid in exclusions):
                issue(f'{p}.markers.{marker_index}.exclude_actions', 'invalid_action_reference', 'Unknown excluded action')
            if 'access' not in marker:
                continue
            from app.core.world_ops import _capacity
            access = marker['access']
            marker_path = f'{p}.markers.{marker_index}.access'
            roles = {'actor', 'partner'} if _capacity(marker.get('capacity')) >= 2 else {'actor'}
            if not isinstance(access, dict) or set(access) - roles:
                issue(marker_path, 'invalid_access', 'Expected role overrides; partner requires two slots')
                continue
            for role, point in access.items():
                if (not isinstance(point, dict) or set(point) != {'x', 'z', 'yaw'}
                        or not all(number(point.get(key)) for key in ('x', 'z', 'yaw'))):
                    issue(marker_path + '.' + role, 'invalid_access_point', 'Expected finite local x, z and yaw')
    if any(i['severity'] == 'error' for i in issues):
        return issues
    active = [v for v in prop.get('model_variants', []) if isinstance(v, dict) and v.get('active', True)]
    matched = {b['action_id'] for v in active for b in derive_bindings(prop, v, poses=pose_catalog) if b['marker_ids']}
    for i, action in enumerate(actions):
        if isinstance(action, dict) and action.get('enabled') and action.get('id') not in matched:
            issues.append(dict(path=f'actions.{i}', code='no_matching_place',
                               message='No matching place on any variant', severity='warning'))
    return issues


def offers(actor: str) -> list[dict]:
    """Actual same-room actions, including blocked entries and partner checks.

    Read only: use published geometry without bbox/LOD/door generation. Never
    call request or reserve a slot to discover whether an action is possible.
    """
    from app.core import places, props, prop_action_engine as engine
    from app.core.room_recipe import compose_recipe
    from app.models.world import get_location_by_id
    location_id, room_id = places.where(actor)
    loc = get_location_by_id(location_id) if location_id else None
    room = next((r for r in (loc or {}).get("rooms", []) if r.get("id") == room_id), None)
    if not room:
        return []
    recipe = compose_recipe(room, [r for r in loc["rooms"] if r is not room],
                            map3d=loc.get("map3d") or {}, read_only=True)
    present = sorted(name for name, _ in places._present(location_id, room_id) if name != actor)
    result = []
    query = places._GeometryQuery()
    for placement in (recipe or {}).get("placements", []):
        pid = placement.get("prop_id", "")
        document = query.prop_document(pid)
        revision = props._document_revision(document)
        target = dict(location_id=location_id, room_id=room_id,
                      placement_id=placement.get("id", ""), variant_uid=placement.get("variant_uid", ""))
        for action in document.get("actions", []):
            pair = action.get("participants") == 2
            targets = []
            if pair:
                for partner in present:
                    checked = engine.check(actor, target, action["id"], revision, partner, _query=query)
                    targets.append(dict(partner=partner, **checked))
                checked = next((t for t in targets if t["enabled"]), None)
                if checked is None:
                    checked = targets[0] if targets else dict(enabled=False, reason="partner_required")
            else:
                checked = engine.check(actor, target, action["id"], revision, _query=query)
            result.append(dict(action_id=action["id"], definition_revision=revision,
                               placement_id=target["placement_id"], variant_uid=target["variant_uid"],
                               target=target, label=action["name"], description=action.get("description", ""),
                               enabled=checked["enabled"], reason=checked["reason"], required_partner=pair,
                               available_targets=targets, effects=action.get("effects", [])))
    return result


def prompt_block(actor: str) -> str:
    """Mandatory executable context shared by every real LLM consumer."""
    import json
    from app.core.prop_action_engine import state_for
    rows = offers(actor)
    return ("<prop_actions_contract>\n"
            "Use PropAction for furniture actions, never SetActivity or a raw pose. "
            "Only enabled offers and enabled exact partners can be requested. "
            "Effects describe real rewards and timing; blocked reasons are authoritative. "
            "Call PropAction with JSON {\"operation\":\"request\",\"action_id\":ID,"
            "\"revision\":DEFINITION_REVISION,\"target\":EXACT_TARGET,\"partner\":NAME_OR_EMPTY}. "
            "An accepted request starts walking, not instant seating or success. "
            "Consent: InteractWith {\"execution_id\":ID,\"answer\":\"yes\"|\"no\"}; "
            "stop: PropAction {\"operation\":\"cancel\",\"execution_id\":ID}. "
            "Never invent IDs, targets, consent or completion.\n"
            "offers=" + json.dumps(rows, ensure_ascii=False, separators=(",", ":")) + "\n"
            "own_state=" + json.dumps(state_for(actor), ensure_ascii=False, separators=(",", ":")) +
            "\n</prop_actions_contract>")


def npc_action_response_contract() -> str:
    """Mandatory JSON envelope understood by the NPC director's real dispatcher."""
    import json
    request = dict(prop_action=dict(operation="request", action_id="<offered action_id>",
        revision="<offered definition_revision>",
        target={key: "<offered " + key + ">" for key in
                ("location_id", "room_id", "placement_id", "variant_uid")},
        partner="<enabled exact partner, or empty string>"))
    cancel = dict(prop_action=dict(operation="cancel", execution_id="<own execution_id>"))
    return ("<npc_action_response_contract>\n"
            "This NPC director does not emit tool syntax. For a furniture action, "
            "replace the ordinary room/activity/pose answer with a SINGLE JSON object "
            "using the prop_action envelope below. Copy exact IDs, revision, target "
            "and an enabled partner from the current offers. A bare tool payload "
            "is not executable here. Do not also set pose, say, pair or action, "
            "and do not change rooms. Use the cancel envelope only for an own run.\n"
            "npc_action_request_shape=" + json.dumps(request, separators=(",", ":")) + "\n"
            "npc_action_cancel_shape=" + json.dumps(cancel, separators=(",", ":")) +
            "\n</npc_action_response_contract>")


def execute(actor: str, payload: dict) -> dict:
    """Structured NPC/tool adapter; no selected actor or geometric overrides."""
    from app.core import prop_action_engine as engine
    refused = dict(status="refused", execution_id="", reason="invalid_request")
    if not isinstance(payload, dict):
        return refused
    operation = payload.get("operation")
    if operation == "cancel":
        if set(payload) != {"operation", "execution_id"} or not isinstance(payload["execution_id"], str):
            return refused
        return engine.cancel(actor, payload["execution_id"])
    if operation != "request" or set(payload) - {
            "operation", "action_id", "revision", "target", "partner", "request_id"}:
        return refused
    return engine.request(actor, payload.get("target"), payload.get("action_id"),
                          payload.get("revision"), payload.get("partner", ""), payload.get("request_id", ""))
