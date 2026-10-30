"""One authoritative access resolver for prop execution and author previews."""
import math


def entry_pose(action: dict) -> str:
    phases = action.get('phases') or []
    return (phases[0].get('pose_key', '') if action.get('ability') == 'combined' and isinstance(phases, list) and phases and isinstance(phases[0], dict)
            else action.get('pose_key', ''))


def slot_access(place: dict, slot: int, role: str, action: dict,
                profile: dict, point=None) -> tuple[dict | None, str]:
    """Resolve one chosen slot in the place's coordinate frame, on its floor.

    Overrides already share that frame after composition. The entry clip faces
    the marker; subtracting its measured travel gives the exact start point.
    ``point`` replaces the slot position as the entry target — a pair sharing
    one place enters at its clip role point (``plan_interaction_at``).
    """
    override = place.get('access', {}).get(role)
    if override is not None:
        return dict(override), ''
    from app.core.prop_action_engine import _entry_capability
    from app.core.animation_clips import clip_travel_m, clip_ref_height_m
    from app.core.room_stand import bridge_start_point
    from app.core.height import height_cm
    capability, reason = _entry_capability(entry_pose(action))
    if reason:
        return None, reason
    kind, _ = capability
    yaw = float(place.get('facing') or 0)
    x, z = bridge_start_point(place['slots'][slot] if point is None else point, clip_travel_m(kind), yaw,
                              height_cm(profile), clip_ref_height_m(kind))
    return dict(x=x, z=z, yaw=yaw, y=place['floor_y']), ''


def compose_access(access: dict, placement: dict) -> dict:
    """Oriented footprint metres to location metres; mesh fix is already applied."""
    angle = math.radians(placement['yaw'])
    cos, sin = math.cos(angle), math.sin(angle)
    px, pz = placement['at']
    return {role: dict(x=round(px + point['x'] * cos + point['z'] * sin, 6),
                       z=round(pz - point['x'] * sin + point['z'] * cos, 6),
                       yaw=(point['yaw'] + placement['yaw']) % 360)
            for role, point in access.items()}


def preview_access(document: dict, *, prop_id: str = "") -> dict:
    """Reference 1.70m figure, oriented local metres, no world writes or routing."""
    from app.core.prop_actions import derive_bindings
    from app.core.room_recipe import compose_prop_marker
    from app.core.scene_recipe import marker_slots, FIGURE_HEIGHT_M
    stored = {}
    file_fixes = {}
    if prop_id:
        from app.core import props
        stored = props.read_sidecar(prop_id, read_only=True)
        for index, variant in enumerate(stored.get('model_variants', [])):
            gallery = props.model_gallery(prop_id, index)
            model = gallery.find(props.DEFAULT_TIER, fallback=False) if gallery else None
            file_fixes[variant['uid']] = props.file_areas(model).get('rotation')
    result = {}
    for action in document.get('actions', []):
        variants = result.setdefault(action['id'], {})
        for variant in document.get('model_variants', []):
            binding = next((b for b in derive_bindings(document, variant)
                            if b['action_id'] == action['id']), None)
            if binding is None:
                continue
            markers = variants.setdefault(variant['uid'], {})
            dims = [variant.get(k) for k in ('width_m', 'depth_m', 'height_m')]
            bbox = variant.get('bbox') or document.get('bbox') or stored.get('bbox')
            if not bbox or not all(isinstance(v, (float, int)) and v > 0 for v in dims):
                continue
            for marker in variant.get('markers', []):
                if marker['id'] not in binding['marker_ids']:
                    continue
                composed = compose_prop_marker(bbox=bbox, rotation=variant.get('rotation', file_fixes.get(variant['uid'])),
                    dims=dims, frac=marker['at'], facing=marker.get('facing'),
                    placement_yaw=0, placement_offset_y=0)
                place = dict(slots=marker_slots(composed['offset_m'], composed['facing'],
                    marker.get('capacity', 1), marker.get('spacing_m', .6), marker.get('slot_axis')),
                    facing=composed['facing'], floor_y=0,
                    access={role: dict(point, y=0) for role, point in marker.get('access', {}).items()})
                slots = markers.setdefault(marker['id'], {})
                for slot in range(len(place['slots'])):
                    roles = slots.setdefault(str(slot), {})
                    for role in ('actor', 'partner') if action.get('participants') == 2 else ('actor',):
                        point, reason = slot_access(place, slot, role, action, {'height': FIGURE_HEIGHT_M * 100})
                        if not reason:
                            roles[role] = {k: point[k] for k in ('x', 'z', 'yaw')}
                            roles[role]['source'] = 'override' if role in place['access'] else 'auto'
    return result
