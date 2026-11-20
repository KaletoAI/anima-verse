"""Boot migration (2026-11-20): a state's ``bone_pose`` names a package pose instead of carrying raw values.

Before, ``prompt_filters.bone_pose`` was ``{<group id>: {rest_deg?, gravity?, …, length?, girth?}}``; now the
values belong to the package as a named pose of the group (``rigs[].poses``) and a state stores
``{<group id>: "<pose id>"}``. Each world row is rewritten once, by format (a string value is already migrated):

- a dict whose values are EXACTLY those of a pose the group declares (the pose's ``rigid`` flag aside) → that pose
  id (several equal poses: the first id in sorted order);
- a dict that matches no declared pose while the group declares exactly one pose → that pose id, with a WARNING
  naming the state, the group and the dropped values;
- a group that declares no pose (or several, none matching), or a value that is neither a dict nor a string → the
  entry is removed, with a WARNING;
- a group no visible package declares → the entry is LEFT as it is, with a WARNING: its package may be disabled
  only for now, and a later boot with the package migrates it (no reader uses a dict value).

The declarations are the manifests' (``loader.declared_packages``), so it runs before or after discovery alike.
Idempotent: a migrated world changes nothing.
"""
import json

from app.core.log import get_logger

logger = get_logger("bone_pose_migration")


def declared_group_poses():
    """``{group id: {pose id: values}}`` over every visible package's rig groups."""
    from app.plugins.loader import declared_packages
    return {rig.id: dict(rig.poses) for package in declared_packages()
            for slot in package.body_slots for rig in slot.rigs}


def _same(pose, values):
    """A declared pose (its ``rigid`` aside) carries exactly these raw values."""
    from app.core.prompt_filters import POSE_RIGID
    own = {key: value for key, value in pose.items() if key != POSE_RIGID}
    if set(own) != set(values):
        return False
    return all(not isinstance(values[key], bool) and isinstance(values[key], (int, float))
               and float(values[key]) == own[key] for key in own)


def migrate_entry(state_id, group_id, value, groups):
    """The new value of one ``bone_pose`` entry: a pose id, None (remove it) or ``value`` unchanged."""
    if isinstance(value, str):
        return value
    if group_id not in groups:
        logger.warning("State %r: bone_pose group %r is declared by no loaded package — left as it is for a later "
                       "boot: %s", state_id, group_id, json.dumps(value, sort_keys=True))
        return value
    poses = groups[group_id]
    if not isinstance(value, dict):
        logger.warning("State %r: bone_pose.%s is neither a pose id nor a value object — removed: %r",
                       state_id, group_id, value)
        return None
    for pose_id in sorted(poses):
        if _same(poses[pose_id], value):
            return pose_id
    if len(poses) == 1:
        (pose_id,) = poses
        logger.warning("State %r: bone_pose.%s matches no declared pose — named the group's only pose %r; the state's "
                       "own values %s are dropped (the pose's are %s)", state_id, group_id, pose_id,
                       json.dumps(value, sort_keys=True), json.dumps(poses[pose_id], sort_keys=True))
        return pose_id
    logger.warning("State %r: bone_pose.%s %s — removed; dropped values: %s", state_id, group_id,
                   "the group declares no pose" if not poses else
                   f"matches none of the declared poses ({', '.join(sorted(poses))})",
                   json.dumps(value, sort_keys=True))
    return None


def migrate_bone_pose_names(groups=None):
    """Rewrite every world ``prompt_filters.bone_pose`` to pose ids (module docstring). Returns how many rows
    changed. ``groups``: {group id: {pose id: values}}, default the visible packages' declarations."""
    from app.core.db import transaction
    if groups is None:
        groups = declared_group_poses()
    changed = 0
    with transaction() as conn:
        for state_id, raw in conn.execute("SELECT id, bone_pose FROM prompt_filters").fetchall():
            try:
                pose = json.loads(raw or "{}")
            except (TypeError, ValueError):
                logger.warning("State %r: bone_pose is no JSON — left as it is", state_id)
                continue
            if not isinstance(pose, dict):
                continue
            new = {}
            for group_id, value in pose.items():
                result = migrate_entry(state_id, group_id, value, groups)
                if result is not None:
                    new[group_id] = result
            if new != pose:
                conn.execute("UPDATE prompt_filters SET bone_pose=? WHERE id=?",
                             (json.dumps(new, ensure_ascii=False), state_id))
                changed += 1
    if changed:
        from app.core.prompt_filters import invalidate_filter_snapshot
        invalidate_filter_snapshot()
    return changed
