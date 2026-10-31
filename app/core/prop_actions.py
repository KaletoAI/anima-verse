"""Prop action authoring contract. Validation is read-only and never executes actions."""
import math
import re
from collections import OrderedDict
from copy import deepcopy
from threading import RLock
from time import monotonic
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
        # A pair needs its pose's ``places`` slots on ONE marker: 2, or 1 when
        # the pose shares a place (one seat for both, e.g. one on the other's lap).
        required = (int(poses.get(key if isinstance(key, str) else '', {}).get('places') or 2)
                    if action.get('ability') == 'pair' else action.get('participants', 1))
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


def validate_document(prop: dict, *, catalogs: dict | None = None, pack: bool = False) -> list[Issue]:
    """Return issues; optional read-only catalog snapshot avoids world DB getters.

    The ``pack-`` id prefix is reserved for package actions: an author action
    may not use it, ``pack`` validates a package's own definition, and the
    runtime document (:func:`effective_document`) names its package actions in
    ``action_sources``. An exclusion may name a package action that is not
    loaded right now — the package may be off in this world."""
    from app.core.prop_action_sources import PACK_PREFIX
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
        # ``name_<lang>`` / ``description_<lang>``: the localized data-field
        # convention (``i18n.localized``) — a package names its actions so.
        fields(action, {'id', 'name', 'description', 'enabled', 'ability', 'pose_key',
                        'participants', 'presence', 'interrupt_on_presence_change',
                        'phases', 'requirements', 'effects'}
               | {k for k in action if isinstance(k, str) and re.fullmatch(r'(name|description)_[a-z]{2}', k)
                  and isinstance(action[k], str)}, p)
        if text(action.get('id')):
            action_map[action['id']] = action
            if (action['id'].startswith(PACK_PREFIX) and not pack
                    and action['id'] not in (prop.get('action_sources') or {})):
                issue(p + '.id', 'invalid_id', 'The pack- prefix is reserved for package actions')
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
    # Package actions this prop does not want (a throne that is no seat for
    # them); only package ids — an own action is switched off with ``enabled``.
    if any(not isinstance(aid, str) or not aid.startswith(PACK_PREFIX)
           for aid in rows(prop.get('exclude_actions', []), 'exclude_actions')):
        issue('exclude_actions', 'invalid_action_reference', 'Only package actions can be excluded here')
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
            if any(not isinstance(aid, str) or (aid not in action_map and not aid.startswith(PACK_PREFIX))
                   for aid in exclusions):
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


def effective_document(document: dict) -> dict:
    """The prop as the RUNTIME sees it: its own actions plus every loaded
    package action whose ``match`` admits it and that it does not exclude
    (``exclude_actions``), with ``action_sources`` = ``{action id: package}``.
    The same object back when nothing is added — so a world without package
    actions sees exactly its raw documents and revisions. Authoring, save
    validation and every export read the RAW document (plan-pack-prop-actions.md)."""
    from app.core.prop_action_sources import _current, matches
    packs = _current()[0]
    if not packs or not isinstance(document, dict):
        return document
    excluded = document.get('exclude_actions') if isinstance(document.get('exclude_actions'), list) else []
    own = {a.get('id') for a in document.get('actions') or [] if isinstance(a, dict)}
    added = [p for p in packs if p['action']['id'] not in own and p['action']['id'] not in excluded
             and matches(p['match'], document)]
    if not added:
        return document
    result = dict(document)
    result['actions'] = [*(document.get('actions') or []), *(deepcopy(p['action']) for p in added)]
    result['action_sources'] = {p['action']['id']: p['owner'] for p in added}
    return result


def package_actions_for(document: dict) -> list[dict]:
    """The package actions the prop editor lists for this (draft) document:
    every loaded one whose ``match`` admits the prop, excluded or not, read
    only — the editor never copies them into the draft."""
    from app.core.prop_action_sources import _current, matches
    from app.plugins import registry
    excluded = document.get('exclude_actions') if isinstance(document.get('exclude_actions'), list) else []
    rows = []
    for entry in _current()[0]:
        if not matches(entry['match'], document):
            continue
        action, package = entry['action'], registry.get_package(entry['owner'])
        label = str(getattr(package, 'manifest', {}).get('capability_label') or '') or entry['owner']
        rows.append(dict(id=action['id'], name=action['name'], description=action.get('description', ''),
                         ability=action['ability'], participants=action['participants'],
                         pose_key=action.get('pose_key', ''), package=entry['owner'], package_label=label,
                         excluded=action['id'] in excluded))
    return rows


_OFFERS_TTL_S = 3.0
_offers_cache = OrderedDict()
_offers_lock = RLock()
_offers_generation = 0


def invalidate_offers_cache():
    """Called after every committed run/claim transaction, including cleanup."""
    global _offers_generation
    with _offers_lock:
        _offers_generation += 1
        _offers_cache.clear()


def _offers_version():
    from app.core import db
    conn = db.get_connection()
    with _offers_lock:
        generation = _offers_generation
    return (str(db.get_db_path()), conn, conn.execute('PRAGMA data_version').fetchone()[0],
            conn.total_changes, generation)


def _offers_key(actor, lang, location, room, query, version):
    """Conservative invalidation: any DB write also invalidates eligibility.

    data_version observes OTHER connections, total_changes this connection.
    Keep connection identity in the key: PRAGMA counters are connection-local.
    This covers claims even from another server process, profiles, occupancy,
    frozen state, item bonuses and world catalog edits without polling runs.
    """
    from app.core import paths, scene_recipe, terrain_types, door_models, prop_action_sources
    from app.core.timeutils import game_time
    from app.models import character, world, world_props, terrain
    from app.core import places
    position = character.get_character_pos(actor) or {}
    present = sorted({actor, *(name for name, _ in places._present(location, room))})
    timed = any(query.profile(name).get('active_conditions') for name in present)
    shared = paths.get_shared_dir()
    # Published prop writers invalidate this existing token immediately.
    # Other file-backed admission catalogs have no shared generation counter.
    files = tuple(scene_recipe._dir_stat_sig(directory, depth=depth) for directory, depth in
                  [(shared / 'templates', 2), (shared / 'config', 0),
                   (shared / 'prompt_filters', 0), (shared / 'stats', 1),
                   (shared / 'terrain', 1),
                   *[(root, 1) for root, _ in paths.get_animation_clips_dirs()]])
    return (*version, actor, lang,
            tuple(round(float(position.get(axis, 0)), 2) for axis in ('x', 'z')),
            location, room, world.world_generation(), world_props.world_props_generation(),
            terrain.terrain_generation(), terrain_types.types_generation(), door_models.generation(),
            scene_recipe.prop_lib_token(), scene_recipe.season_token(), files,
            prop_action_sources.signature(),
            str(game_time()) if timed else None)


def offers(actor: str, *, lang: str = "en") -> list[dict]:
    """Actual same-room actions, including blocked entries and partner checks.

    Read only: use published geometry without bbox/LOD/door generation. Never
    call request or reserve a slot to discover whether an action is possible.
    """
    from app.core import places, props, prop_action_engine as engine
    from app.core.room_recipe import compose_recipe
    from app.core.i18n import localized
    from app.models.world import get_location_by_id
    version = _offers_version()
    cacheable = not version[1].in_transaction
    query = places._GeometryQuery(cache_profiles=True)
    location_id, room_id = places.where(actor, profile=query.profile(actor))
    loc = get_location_by_id(location_id) if location_id else None
    room = next((r for r in (loc or {}).get("rooms", []) if r.get("id") == room_id), None)
    if not room:
        return []
    cache_key = _offers_key(actor, lang, location_id, room_id, query, version)
    with _offers_lock:
        hit = _offers_cache.get(cache_key)
        if cacheable and hit and monotonic() < hit[0]:
            return deepcopy(hit[1])
    recipe = compose_recipe(room, [r for r in loc["rooms"] if r is not room],
                            map3d=loc.get("map3d") or {}, read_only=True)
    present = sorted(name for name, _ in places._present(location_id, room_id) if name != actor)
    # Which actions have a place on which placement (``derive_bindings`` via
    # the composed markers). An action without one is no offer at all: it
    # could only ever answer "this place does not support the pose" — and a
    # package action reaches every prop, fitting or not.
    bound = {(marker.get("placement_id"), binding.get("action_id"))
             for marker in (recipe or {}).get("prop_markers", [])
             for binding in marker.get("action_bindings", [])}
    # How far each piece is from the actor (metres, to its nearest place):
    # the panel names the piece by it when one action stands on several.
    # The actor's position is part of the cache key.
    from app.models.character import get_character_pos
    here = get_character_pos(actor)
    distance = {}
    for place in query.room_places(location_id, room_id) if here else []:
        if place.get("placement_id") and place.get("slots"):
            d = math.dist((here["x"], here["z"]), places.centre_of(place))
            distance[place["placement_id"]] = min(d, distance.get(place["placement_id"], d))
    result = []
    for placement in (recipe or {}).get("placements", []):
        pid = placement.get("prop_id", "")
        document = query.prop_document(pid)
        revision = props._document_revision(document)
        target = dict(location_id=location_id, room_id=room_id,
                      placement_id=placement.get("id", ""), variant_uid=placement.get("variant_uid", ""))
        for action in document.get("actions", []):
            if (target["placement_id"], action.get("id")) not in bound:
                continue
            pair = action.get("participants") == 2
            # Not meant for this figure (no clip for its pose): not offered
            # at all, rather than shown and played as the group's fallback.
            if (not pair and action.get("ability") != "pair"
                    and not engine.animated_for(actor, action, profile=query.profile(actor))):
                continue
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
                               prop_label=localized(document, "name", lang) or pid,
                               distance_m=(round(distance[target["placement_id"]], 1)
                                           if target["placement_id"] in distance else None),
                               target=target, label=localized(action, "name", lang) or action["name"],
                               description=localized(action, "description", lang) or action.get("description", ""),
                               enabled=checked["enabled"], reason=checked["reason"], required_partner=pair,
                               available_targets=targets, effects=action.get("effects", [])))
    # Capture the entire key before reading; a concurrent mutation must never
    # publish an older snapshot under a newer version. Lazy readers can write,
    # so recheck before publishing as well.
    if cacheable and not version[1].in_transaction and _offers_key(
            actor, lang, location_id, room_id, query, _offers_version()) == cache_key:
        with _offers_lock:
            if cache_key[4] == _offers_generation:
                _offers_cache[cache_key] = (monotonic() + _OFFERS_TTL_S, deepcopy(result))
                _offers_cache.move_to_end(cache_key)
                while len(_offers_cache) > 128:
                    _offers_cache.popitem(last=False)
    return result


def _requestable(actor: str) -> list:
    """The offers ``actor`` can request NOW, each fact once: a pair offer
    with its enabled ``partners``, no enabled/reason/available_targets, the
    target fields only inside ``target``. Blocked offers stay out: a room
    with a few chairs and a package's pair poses lists hundreds of them
    (every partner, every place), which once grew a prompt past 200 KB per
    call. The player panel still shows them with their reason."""
    rows = []
    for offer in offers(actor):
        if offer["required_partner"]:
            partners = [t["partner"] for t in offer["available_targets"] if t["enabled"]]
            if not partners:
                continue
        elif not offer["enabled"]:
            continue
        row = {k: v for k, v in offer.items()
               if k not in ("enabled", "reason", "available_targets", "placement_id", "variant_uid")
               and v not in ("", [], None)}
        if offer["required_partner"]:
            row["partners"] = partners
        rows.append(row)
    return rows


def piece_label(target: dict, lang: str = "en") -> str:
    """The name of the furniture piece a target points at ("Stone Bench"),
    the same name :func:`offers` gives it; ``""`` when it is gone."""
    from app.core import places
    from app.core.i18n import localized
    from app.core.props import read_sidecar
    try:
        pid = next((place.get("prop_id") for place in
                    places.room_places(target["location_id"], target["room_id"])
                    if place.get("placement_id") == target["placement_id"]), None)
    except (KeyError, TypeError):
        return ""
    if not pid:
        return ""
    return localized(read_sidecar(pid, read_only=True) or {}, "name", lang) or pid


def _piece_lines(rows: list) -> list:
    """One line per furniture NAME with its action names (a pair action with
    its partners) — what an LLM decides on. Several pieces of one name are
    one line: which of them is used is the server's choice (the nearest
    usable one, :func:`execute`)."""
    pieces: dict = {}
    for row in rows:
        labels = pieces.setdefault(row.get("prop_label") or "Furniture", {})
        partners = labels.setdefault(row.get("label") or "", [])
        partners += [p for p in row.get("partners", []) if p not in partners]
    return [f"- {prop}: " + ", ".join(f"{label} (with {', '.join(partners)})" if partners else label
                                      for label, partners in labels.items())
            for prop, labels in pieces.items()]


def _own_lines(actor: str) -> list:
    """The actor's own running or waiting furniture actions, in words."""
    from app.core.prop_action_engine import state_for
    state = state_for(actor)
    lines = []
    for run in state["current"]:
        other = run["partner"] if run["actor"] == actor else run["actor"]
        piece = piece_label(run["target"])
        lines.append(f"You are doing: {run['label']}" + (f" with {other}" if other else "")
                     + (f" on {piece}" if piece else ""))
    for run in state["outgoing"]:
        piece = piece_label(run["target"])
        lines.append(f"You asked {run['partner']} for {run['label']}"
                     + (f" on {piece}" if piece else "") + " — waiting for the answer")
    return lines


def narrative_block(actor: str) -> str:
    """The offers for a reader that writes prose and calls no tool — the
    roleplay reply of ``rp_first``, whose separate tool LLM turns the prose
    into the action afterwards::

        Furniture here (just describe what you do with it):
        - Stone Bench: Sit, Lie down
        - Bed: Cuddle (with Mia)

    ``""`` when nothing can be requested and nothing is running."""
    lines = _piece_lines(_requestable(actor)) + _own_lines(actor)
    if not lines:
        return ""
    return "\n".join(["Furniture here (just describe what you do with it):", *lines])


def prompt_block(actor: str) -> str:
    """The furniture context of every LLM that calls tools: furniture and
    action NAMES only — what a decision needs. Ids, revisions and targets
    stay with the server, which resolves a named request at execution
    (:func:`execute`); an earlier version carried them all and grew to
    15 KB per prompt."""
    lines = _piece_lines(_requestable(actor)) or ["(none available right now)"]
    return "\n".join([
        "<prop_actions_contract>",
        'Furniture actions here. Use one: PropAction {"furniture": "<name>", "action": "<action>", '
        '"partner": "<name, only for an action with partners>"}; stop your own: PropAction {"stop": true}. '
        "A request starts walking there; a pair starts when the partner agrees.",
        *lines, *_own_lines(actor),
        "</prop_actions_contract>"])


def replace_contract(text: str, replacement: str) -> str:
    """``text`` with its :func:`prompt_block` section swapped for
    ``replacement`` — for a prompt rendered before its reader was known to
    call no tool (an rp_first thought's roleplay call)."""
    start = text.find("<prop_actions_contract>")
    end = text.find("</prop_actions_contract>", start)
    if start < 0 or end < 0:
        return text
    return text[:start] + replacement + text[end + len("</prop_actions_contract>"):]


def npc_action_response_contract() -> str:
    """The JSON envelope the NPC director answers with for a furniture
    action — names, like every LLM reader (:func:`prompt_block`)."""
    return ("<npc_action_response_contract>\n"
            "For a furniture action, answer with ONLY this JSON object instead of the "
            'room/activity/pose answer: {"prop_action": {"furniture": "<name>", "action": "<action>", '
            '"partner": "<name or empty>"}}; to stop your own: {"prop_action": {"stop": true}}.\n'
            "</npc_action_response_contract>")


def _named_request(actor: str, payload: dict) -> dict:
    """A request by NAMES (``furniture`` + ``action`` [+ ``partner``]) on the
    usable piece of that name nearest to the actor, resolved against the
    current offers — the LLM never handles ids, revisions or targets."""
    def refused(reason, **extra):
        return dict(status="refused", execution_id="", reason=reason, **extra)
    furniture = str(payload.get("furniture") or "").strip().lower()
    action = str(payload.get("action") or "").strip().lower()
    partner = str(payload.get("partner") or "").strip()
    rows = [o for o in offers(actor)
            if (o["prop_label"] or "Furniture").strip().lower() == furniture
            and o["label"].strip().lower() == action]
    if not rows:
        return refused("no_such_offer", available=_piece_lines(_requestable(actor)))

    def verdict(row):
        if not row["required_partner"]:
            return row["enabled"], row["reason"]
        choice = next((t for t in row["available_targets"] if t["partner"].lower() == partner.lower()), None)
        if choice is None:
            return False, "partner_required" if not partner else "partner_not_available"
        return choice["enabled"], choice["reason"]

    rows.sort(key=lambda row: row["distance_m"] if row["distance_m"] is not None else float("inf"))
    usable = [row for row in rows if verdict(row)[0]]
    if not usable:
        return refused(verdict(rows[0])[1])
    row = usable[0]
    exact = dict(operation="request", action_id=row["action_id"], revision=row["definition_revision"],
                 target=row["target"])
    if row["required_partner"]:
        exact["partner"] = next(t["partner"] for t in row["available_targets"]
                                if t["partner"].lower() == partner.lower())
    # The answer goes back to the LLM: what happened, in names.
    result = execute(actor, exact)
    return dict(status=result["status"], furniture=row["prop_label"], action=row["label"],
                **({"partner": exact["partner"]} if "partner" in exact else {}),
                **({"reason": result["reason"]} if result.get("reason") else {}))


def _stop_own(actor: str) -> dict:
    """``{"stop": true}``: end the actor's own running or waiting actions."""
    from app.core import prop_action_engine as engine
    state = engine.state_for(actor)
    runs = [run for run in state["current"] + state["outgoing"] if run["can_cancel"]]
    if not runs:
        return dict(status="refused", execution_id="", reason="nothing_to_stop")
    results = [engine.cancel(actor, run["execution_id"]) for run in runs]
    return dict(status=results[-1]["status"], stopped=[run["label"] for run in runs])


def execute(actor: str, payload: dict) -> dict:
    """Structured NPC/tool adapter; no selected actor or geometric overrides."""
    from app.core import prop_action_engine as engine
    refused = dict(status="refused", execution_id="", reason="invalid_request")
    if not isinstance(payload, dict):
        return refused
    # The LLM form (prompt_block): names, or a stop of the own actions.
    if set(payload) == {"stop"} and payload["stop"] is True:
        return _stop_own(actor)
    if "furniture" in payload or "action" in payload:
        if set(payload) - {"furniture", "action", "partner"}:
            return refused
        return _named_request(actor, payload)
    operation = payload.get("operation")
    if operation == "cancel":
        if set(payload) != {"operation", "execution_id"} or not isinstance(payload["execution_id"], str):
            return refused
        return engine.cancel(actor, payload["execution_id"])
    if operation != "request" or set(payload) - {
            "operation", "action_id", "revision", "target", "partner", "request_id"}:
        return refused
    from app.core.skill_gate import blocked_reason, charge
    request_id = payload.get("request_id", "")
    with engine.request_guard(actor, request_id):
        # The engine resolves replay identity/conflicts before current-world
        # eligibility. Exhaustion must not hide an already admitted request.
        previous = (engine.store.by_request(actor, request_id)
                    if isinstance(actor, str) and isinstance(request_id, str) else None)
        if not previous:
            reason = blocked_reason(actor, "prop_action")
            if reason:
                return dict(status="refused", execution_id="", reason=reason)
        result, created = engine.request_with_creation(
            actor, payload.get("target"), payload.get("action_id"),
            payload.get("revision"), payload.get("partner", ""), request_id)
        if created and result["status"] not in ("failed", "cancelled"):
            charge(actor, "prop_action")
    if created:
        # Invitation callbacks deferred by the outer guard may have advanced
        # the run. Return the same current projection as the HTTP adapter.
        result = engine._result(engine.store.get(result["execution_id"]))
    return result
