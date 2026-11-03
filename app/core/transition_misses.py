"""The transition clips the figures needed and did not have — the Poses tab's
suggestions.

A figure that switches from one animation to another plays the transition
rule between the two (``animation_clips.resolve_pose_transition``); without
one, the clip snaps. Every pose switch of a player's AVATAR, and of everyone
in an interaction with an avatar, is checked against that table here, and a
switch without a bridge clip is counted in ``transition_misses`` (world.db):
one row per start pose × target pose × clip roles × animation set, with a
count, the last time and the last few people. ``main.log`` gets one line per
miss.

The switches are the server's: a pose set in place (``set_pose_intent``,
from the held pose, else ``standing``; on a journey's arrival from
``walking``), standing up (``clear_pose_intent`` → ``standing``) and setting
off with a pose still held (``travel_engine.departure_bridge`` → ``walking``).
Clips only a client decides (swimming, crawling) are not seen here.

The Poses tab lists the rows that are still uncovered — a rule written since
hides its row without a write — and opens the transition dialog filled in
with one; "Dismiss" hides a row for good.
"""
import json
from typing import Any, Dict, List, Optional

from app.core.db import get_connection, transaction
from app.core.log import get_logger

logger = get_logger(__name__)

STANDING = "standing"
WALKING = "walking"
#: How many names a row keeps (the most recent first).
MAX_NAMES = 5


def note_switch(name: str, from_pose: Any, to_pose: Any, *,
                profile: Optional[Dict[str, Any]] = None) -> None:
    """Count ``name``'s switch from ``from_pose`` to ``to_pose`` when it has
    no bridge clip and ``name`` is an avatar or shares an interaction with
    one. ``profile``: the profile as it was BEFORE the switch (its
    interaction names the people and the role). Never raises."""
    try:
        _note(name, str(from_pose or "").strip().lower(),
              str(to_pose or "").strip().lower(), profile)
    except Exception as e:  # noqa: BLE001 — a suggestion must never break a pose write
        logger.debug("transition miss %s %s -> %s not noted: %s", name, from_pose, to_pose, e)


def _note(name: str, src: str, dst: str, profile: Optional[Dict[str, Any]]) -> None:
    if not name or not src or not dst or src == dst:
        return
    if profile is None:
        from app.models.character import get_character_profile
        profile = get_character_profile(name) or {}
    members = _members(profile, src)
    from app.models.account import get_all_avatars
    avatars = get_all_avatars()
    if name not in avatars and not avatars & set(members.values()):
        return
    from app.core.animation_clips import pose_roles
    role = next((r for r, who in members.items() if who == name), "")
    start_role = role if pose_roles(src) else ""
    target_role = role if pose_roles(dst) else ""
    if covered(src, dst, start_role, target_role):
        return
    from app.core.animation_sets import resolve_sets
    cset = (resolve_sets(name, profile) or [""])[0]
    _count(name, src, dst, start_role, target_role, cset)


def _members(profile: Dict[str, Any], leaving: str) -> Dict[str, str]:
    """``{role: name}`` of the interaction ``profile`` is in — or, when it
    has just ended (``end_interaction`` drops it before the figures stand
    up), of the ended one, as long as ``leaving`` is that one's pose."""
    from app.core.interaction_engine import members_of
    inter = profile.get("interaction")
    if isinstance(inter, dict):
        return members_of(inter)
    last = profile.get("last_interaction_result")
    if isinstance(last, dict) and str(last.get("pose_key") or "").lower() == leaving:
        members = last.get("members")
        if isinstance(members, dict):
            return {str(r): str(n) for r, n in sorted(members.items()) if n}
    return {}


def covered(start: str, target: str, start_role: str = "", target_role: str = "") -> bool:
    """Whether a rule plays an existing bridge clip for this switch — the
    lookup the clients switch by, for the role on the multi-person side."""
    from app.core.animation_clips import clip_meta, resolve_pose_transition, rule_kind
    rule = resolve_pose_transition(start, target)
    kind = rule_kind(rule, start_role or target_role) if rule else ""
    return bool(kind and clip_meta(kind))


def _count(name: str, src: str, dst: str, start_role: str, target_role: str, cset: str) -> None:
    from app.core.timeutils import game_time, utc_now_iso
    now, game = utc_now_iso(), game_time().canonical()
    key = (src, dst, start_role, target_role, cset)
    with transaction() as conn:
        row = conn.execute(
            "SELECT names FROM transition_misses WHERE start_pose=? AND target_pose=? "
            "AND start_role=? AND target_role=? AND cset=?", key).fetchone()
        try:
            names = json.loads(row[0]) if row else []
        except ValueError:
            names = []
        names = [name] + [n for n in names if n != name][:MAX_NAMES - 1]
        conn.execute(
            "INSERT INTO transition_misses (start_pose, target_pose, start_role, target_role, cset, "
            "count, first_seen, last_seen, last_game_ts, names) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?) "
            "ON CONFLICT(start_pose, target_pose, start_role, target_role, cset) DO UPDATE SET "
            "count = count + 1, last_seen = excluded.last_seen, "
            "last_game_ts = excluded.last_game_ts, names = excluded.names",
            (*key, now, now, game, json.dumps(names, ensure_ascii=False)))
    logger.info("transition missing: %s %s%s -> %s%s (set %s)", name, src,
                f" [{start_role}]" if start_role else "", dst,
                f" [{target_role}]" if target_role else "", cset or "neutral")


def suggestions() -> List[Dict[str, Any]]:
    """The rows still uncovered and not dismissed, most frequent first. Each
    says whether the transition dialog can make it (``ready``) and, if not,
    why (``problem``: the pose clip it needs is missing)."""
    rows = get_connection().execute(
        "SELECT start_pose, target_pose, start_role, target_role, cset, count, "
        "first_seen, last_seen, last_game_ts, names FROM transition_misses "
        "WHERE dismissed = 0 ORDER BY count DESC, last_seen DESC").fetchall()
    out = []
    for r in rows:
        start, target, start_role, target_role, cset = r[:5]
        if covered(start, target, start_role, target_role):
            continue
        try:
            names = json.loads(r[9] or "[]")
        except ValueError:
            names = []
        out.append(dict(start_pose=start, target_pose=target, start_role=start_role,
                        target_role=target_role, cset=cset, count=r[5], first_seen=r[6],
                        last_seen=r[7], last_game_ts=r[8], names=names,
                        problem=_problem(start, target, start_role, target_role, cset)))
        out[-1]["ready"] = not out[-1]["problem"]
    return out


def _problem(start: str, target: str, start_role: str, target_role: str, cset: str) -> str:
    """"" when both poses have the clip the transition job starts from."""
    from app.core import pose_transition
    for pose, role in ((start, start_role), (target, target_role)):
        try:
            pose_transition.pose_clip(pose, cset, role)
        except ValueError as e:
            return f"{pose}: {e}"
    return ""


def dismiss(start_pose: str, target_pose: str, start_role: str = "",
            target_role: str = "", cset: str = "") -> bool:
    """Hide one row for good. False when there is no such row."""
    with transaction() as conn:
        cur = conn.execute(
            "UPDATE transition_misses SET dismissed = 1 WHERE start_pose=? AND target_pose=? "
            "AND start_role=? AND target_role=? AND cset=?",
            (start_pose, target_pose, start_role, target_role, cset))
        return cur.rowcount > 0
