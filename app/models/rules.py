"""World rules: configurable blocks, forced actions, discovery and modifiers.

Conditions use the activity expression syntax. Rules are stored in world.db
with a shared baseline from shared/rules/rules.json."""
import json
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from app.core.log import get_logger
from app.core.db import get_connection, transaction
from app.core.i18n import localized

logger = get_logger("rules")


def _user_lang() -> str:
    """Active user's UI language for rule-message localization.

    Lazy import to avoid circular dependency with ``app.models.account`` —
    ``account`` itself reads rule data via the storage layer at startup.
    """
    try:
        from app.models.account import get_user_profile
        return (get_user_profile().get("system_language") or "en").strip() or "en"
    except Exception:
        return "en"


def _get_shared_rules_path() -> Path:
    """Shared baseline, overlaid by world rules with matching IDs."""
    return Path(__file__).resolve().parent.parent.parent / "shared" / "rules" / "rules.json"


def _load_shared_rules() -> List[Dict[str, Any]]:
    """Read shared rules, returning an empty list for missing or invalid data."""
    path = _get_shared_rules_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        rules = data.get("rules", []) if isinstance(data, dict) else []
        # Origin marker lets the UI distinguish shared and world entries.
        for r in rules:
            r["_origin"] = "shared"
        return rules
    except Exception as e:
        logger.warning("shared/rules/rules.json laden fehlgeschlagen: %s", e)
        return []


def _save_shared_rules(rules: List[Dict[str, Any]]):
    """Write the shared baseline without origin markers."""
    old_rules = _load_shared_rules()
    path = _get_shared_rules_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    clean = [{k: v for k, v in r.items() if not k.startswith("_")} for r in rules]
    path.write_text(json.dumps({"rules": clean}, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    _rules_changed(old_rules, clean)


def _load_world_rules() -> List[Dict[str, Any]]:
    """Read world-specific rules from the database."""
    try:
        conn = get_connection()
        rows = conn.execute(
            "SELECT id, text, category, meta FROM rules ORDER BY rowid ASC"
        ).fetchall()
        rules = []
        for r in rows:
            meta = {}
            try:
                meta = json.loads(r[3] or "{}")
            except Exception:
                pass
            meta.setdefault("id", r[0])
            if r[1] and not (meta.get("name") or meta.get("message")):
                meta["message"] = r[1]
            if r[2] and not meta.get("type"):
                meta["type"] = r[2]
            meta["_origin"] = "world"
            rules.append(meta)
        return rules
    except Exception as e:
        logger.warning("_load_world_rules DB-Fehler: %s", e)
        return []


def _normalize_modifiers(rules: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Clamp modify factors for shared data, world data and API writes alike."""
    from app.core.modifiers import clamp_factor
    for rule in rules:
        if rule.get("type") == "modify":
            modifier = rule.get("modify") or {}
            rule["modify"] = {"quantity": str(modifier.get("quantity") or ""),
                              "factor": clamp_factor(modifier.get("factor", 1))}
    return rules


def load_rules() -> List[Dict[str, Any]]:
    """Merge the shared baseline with the world overlay by ID.

    Each entry carries an _origin: shared, world, or world override."""
    shared = _load_shared_rules()
    world = _load_world_rules()
    if not world:
        return _normalize_modifiers(shared)
    if not shared:
        return _normalize_modifiers(world)

    by_id: Dict[str, Dict[str, Any]] = {}
    for r in shared:
        rid = (r.get("id") or "").strip()
        if rid:
            by_id[rid] = r
    for r in world:
        rid = (r.get("id") or "").strip()
        if not rid:
            continue
        if rid in by_id:
            r = dict(r)
            r["_origin"] = "world override"
        by_id[rid] = r
    return _normalize_modifiers(list(by_id.values()))


def save_rules(rules: List[Dict[str, Any]], target_dir: str = "world"):
    """Save rules to the world DB or the shared baseline.

    ``target_dir="world"`` replaces the world layer, deleting absent IDs.
    ``target_dir="shared"`` replaces shared/rules/rules.json for all worlds.
    """
    rules = _normalize_modifiers(rules)
    if target_dir == "shared":
        try:
            _save_shared_rules(rules)
            logger.info("Shared-Rules gespeichert: %d Eintraege", len(rules))
        except Exception as e:
            logger.error("save_rules shared-Fehler: %s", e)
        return

    # Upsert world rules and remove absent IDs.
    try:
        with transaction() as conn:
            old_rows = conn.execute("SELECT id, meta FROM rules").fetchall()
            old_rules = []
            for rid, meta in old_rows:
                try:
                    rule = json.loads(meta or "{}")
                except (TypeError, ValueError):
                    rule = {}
                if not isinstance(rule, dict):
                    rule = {}
                rule["id"] = rid
                old_rules.append(rule)
            existing_ids = {r[0] for r in old_rows}
            new_ids = {r.get("id") for r in rules if r.get("id")}

            for rid in existing_ids - new_ids:
                conn.execute("DELETE FROM rules WHERE id=?", (rid,))

            for rule in rules:
                rid = rule.get("id")
                if not rid:
                    continue
                # Origin markers are presentation metadata; never persist them.
                clean = {k: v for k, v in rule.items() if not k.startswith("_")}
                # Store a readable summary in the text column.
                text = clean.get("name", clean.get("text", ""))
                category = clean.get("type", clean.get("category", ""))
                meta_str = json.dumps(clean, ensure_ascii=False)
                conn.execute("""
                    INSERT INTO rules (id, text, category, meta)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        text=excluded.text,
                        category=excluded.category,
                        meta=excluded.meta
                """, (rid, text, category, meta_str))
    except Exception as e:
        logger.error("save_rules DB-Fehler: %s", e)
        return
    _rules_changed(old_rules, rules)


# Seed missing default rules during initialization or explicit migration.
# Existing IDs remain untouched. Seed data lives in shared/rules/_defaults.json.
def _load_default_rules() -> List[Dict[str, Any]]:
    """Read seed defaults from shared/rules/_defaults.json."""
    path = _get_shared_rules_path().parent / "_defaults.json"
    if not path.exists():
        logger.warning("Seed-File fehlt: %s — keine Defaults", path)
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("rules", [])
    except Exception as e:
        logger.warning("Seed-File konnte nicht gelesen werden (%s): %s", path, e)
        return []


def ensure_default_rules() -> int:
    """Ensure default sleep/wake rules exist in the shared baseline.

    Add only missing IDs from shared/rules/_defaults.json. World overrides
    remain authoritative. Return the number added."""
    try:
        # Check only shared data; world overrides preserve user decisions.
        shared = _load_shared_rules()
        shared_ids = {(r.get("id") or "").strip() for r in shared}
        added = 0
        for default in _load_default_rules():
            rule_id = (default.get("id") or "").strip()
            if not rule_id or rule_id in shared_ids:
                continue
            shared.append(dict(default))
            added += 1
        if added:
            save_rules(shared, target_dir="shared")
            logger.info("Default-Rules in shared baseline geseedet: %d neu", added)
        return added
    except Exception as e:
        logger.warning("ensure_default_rules fehlgeschlagen: %s", e)
        return 0


def add_rule(rule: Dict[str, Any], target_dir: str = "world") -> Dict[str, Any]:
    """Upsert a rule by ID into the world or shared layer.

    Moving a rule requires deleting its old layer and posting to the new one."""
    _normalize_modifiers([rule])
    if not rule.get("id"):
        rule["id"] = f"rule_{uuid.uuid4().hex[:8]}"
    rule_id = rule["id"]
    clean = {k: v for k, v in rule.items() if not k.startswith("_")}
    if target_dir == "shared":
        existing = _load_shared_rules()
        existing = [r for r in existing if r.get("id") != rule_id]
        existing.append(clean)
        save_rules(existing, target_dir="shared")
    else:
        world_only = _load_world_rules()
        world_only = [r for r in world_only if r.get("id") != rule_id]
        world_only.append(clean)
        save_rules(world_only, target_dir="world")
    logger.info("Rule upsert: %s (%s) → %s",
                rule.get("name", "?"), rule_id, target_dir)
    return rule


def update_rule(rule_id: str, updates: Dict[str, Any],
                target_dir: str = "world") -> Optional[Dict[str, Any]]:
    """Update a rule in the requested layer.

    A world update creates an override if the ID exists only in shared data."""
    if target_dir == "shared":
        rules = _load_shared_rules()
        for r in rules:
            if r.get("id") == rule_id:
                r.update({k: v for k, v in updates.items()
                         if k != "id" and not k.startswith("_")})
                save_rules(rules, target_dir="shared")
                logger.info("Shared-Rule aktualisiert: %s", rule_id)
                return r
        return None

    # Update an existing world entry or create an override.
    world_rules = _load_world_rules()
    for r in world_rules:
        if r.get("id") == rule_id:
            r.update({k: v for k, v in updates.items()
                     if k != "id" and not k.startswith("_")})
            save_rules(world_rules, target_dir="world")
            logger.info("Rule aktualisiert: %s", rule_id)
            return r
    # Copy the shared entry and apply updates as a world override.
    shared = _load_shared_rules()
    for r in shared:
        if r.get("id") == rule_id:
            override = {k: v for k, v in r.items() if not k.startswith("_")}
            override.update({k: v for k, v in updates.items()
                            if k != "id" and not k.startswith("_")})
            world_rules.append(override)
            save_rules(world_rules, target_dir="world")
            logger.info("Rule aus Shared in Welt ueberschrieben: %s", rule_id)
            return override
    return None


def delete_rule(rule_id: str, target_dir: str = "") -> bool:
    """Delete a rule from the requested layer.

    An empty target chooses a world override first, then shared. Deleting only
    a world override reveals the shared entry again."""
    if target_dir == "world":
        world_rules = _load_world_rules()
        new = [r for r in world_rules if r.get("id") != rule_id]
        if len(new) < len(world_rules):
            save_rules(new, target_dir="world")
            logger.info("World-Rule geloescht: %s", rule_id)
            return True
        return False
    if target_dir == "shared":
        shared = _load_shared_rules()
        new = [r for r in shared if r.get("id") != rule_id]
        if len(new) < len(shared):
            save_rules(new, target_dir="shared")
            logger.info("Shared-Rule geloescht: %s", rule_id)
            return True
        return False

    # Automatic mode: world first, then shared.
    if delete_rule(rule_id, target_dir="world"):
        return True
    return delete_rule(rule_id, target_dir="shared")


def add_event_rule(event_id: str,
    location_id: str,
    message: str,
    action: str = "leave",
    name: str = "") -> Optional[Dict[str, Any]]:
    """Create a temporary block tied to an event lifetime.

    Event resolution or expiry calls delete_rules_by_event. Action leave blocks
    exits, enter blocks entry, and both blocks both directions."""
    if not event_id or not location_id:
        return None

    if action == "both":
        rules = []
        for sub in ("enter", "leave"):
            r = add_event_rule(event_id, location_id, message, action=sub,
                                name=name)
            if r:
                rules.append(r)
        return rules[0] if rules else None

    rule = {
        "id": f"evtrule_{event_id}_{action}",
        "name": name or f"Event-Block ({action})",
        "type": "block",
        "action": action,
        "target": {"scope": "location", "location_id": location_id},
        "message": message or "Access denied.",
        "event_id": event_id,
    }
    return add_rule(rule, target_dir="world")


def delete_rules_by_event(event_id: str) -> int:
    """Delete event-bound rules and return the number deleted."""
    if not event_id:
        return 0
    deleted = 0
    world_rules = _load_world_rules()
    keep = [r for r in world_rules if r.get("event_id") != event_id]
    if len(keep) != len(world_rules):
        deleted = len(world_rules) - len(keep)
        save_rules(keep, target_dir="world")
        logger.info("delete_rules_by_event: %d Rule(s) zu event=%s entfernt",
                     deleted, event_id)
    return deleted


def get_rule(rule_id: str) -> Optional[Dict[str, Any]]:
    """Return a single rule by id."""
    for r in load_rules():
        if r.get("id") == rule_id:
            return r
    return None


# ============================================================
# BLOCK RULES: check access
# ============================================================

def rule_action(rule: Dict[str, Any]) -> str:
    """The direction a block rule guards: ``enter`` or ``leave``.

    Read leniently: the RulesTab writes the direction into ``target.action``,
    the event path onto the rule itself. Both shapes have to bite, or a rule
    authored in the UI would be checked against the wrong direction.
    """
    target = rule.get("target") or {}
    action = (rule.get("action") or target.get("action") or "").strip()
    return action or "enter"


def _rule_rooms(target: Dict[str, Any]) -> List[str]:
    """The room ids a rule names — RulesTab ``rooms``, event path ``room_ids``."""
    rooms = target.get("room_ids") or target.get("rooms") or []
    if not isinstance(rooms, list):
        return []
    return [str(r) for r in rooms if r]


def _rule_location_rooms(target: Dict[str, Any]) -> Tuple[str, List[str]]:
    """Resolve the editor and event target schemas for checks and notices."""
    location = (target.get("location_id") or target.get("location") or "").strip()
    return location, _rule_rooms(target)


def _names_every_room(location_id: str, room_ids: List[str]) -> bool:
    """True when ``room_ids`` covers every room of the location.

    Only then does a room-limited rule stop the LOCATION itself; otherwise the
    character can route to a room the rule does not name. Corridor rooms count
    like the ground: a location-wide rule has to name them, and the RulesTab
    lists them.
    """
    from app.models.world import get_location_by_id
    loc = get_location_by_id(location_id) or {}
    rooms = [r.get("id", "") for r in (loc.get("rooms") or []) if r.get("id")]
    if not rooms:
        return True
    return all(rid in room_ids for rid in rooms)


def check_access(character_name: str,
    location_id: str,
    room_id: str = "",
    action: str = "enter") -> Tuple[bool, str]:
    """Check every block rule for access to a location/room.

    Returns: (allowed, reason) — False plus the message when blocked.
    """
    from app.core.activity_engine import evaluate_condition

    # The danger level of the target
    target_danger = _get_target_danger_level(location_id, room_id)

    for rule in load_rules():
        if rule.get("type") != "block":
            continue
        if rule_action(rule) != action:
            continue

        # Character filter: a rule may be limited to one character
        rule_char = (rule.get("character") or "").strip()
        if rule_char and rule_char != character_name:
            continue

        # Match the target. Field names are read leniently: the RulesTab
        # stores location/rooms/min_danger_level, the event path
        # location_id/room_ids/min_danger — BOTH schemas have to bite, or the
        # rules authored in the UI would have no effect.
        target = rule.get("target", {})
        scope = target.get("scope", "")
        if scope == "skill":
            continue
        t_loc, t_rooms = _rule_location_rooms(target)

        matched = False
        if scope in ("location", "room") and t_loc and t_loc == location_id:
            # A named room list NARROWS the rule to those rooms — the scope
            # word only says which field carries the target. The RulesTab
            # offers the room multi-select under scope "location" ("no
            # selection means the whole location"), so ignoring the list here
            # locked every other room of the place as well.
            if not t_rooms:
                # Whole location — but a "room" scope without rooms names
                # nothing and stays inert.
                matched = scope == "location"
            elif room_id:
                matched = room_id in t_rooms
            else:
                # Location-level question without a room: the rule stops the
                # location itself only when it covers EVERY room (same idea as
                # any_room below) — otherwise a reachable room remains.
                matched = _names_every_room(location_id, t_rooms)
        elif scope == "any_room":
            # Applies to every room. Two cases:
            #  a) with a concrete room_id -> check that room directly.
            #  b) location level without a room_id -> check whether EVERY room
            #     of the location would block. When at least one room does not
            #     satisfy the condition, the character can route there and
            #     entering the location is allowed (the scheduler / the
            #     SetLocation skill then pick the room that works).
            if room_id:
                matched = True
            elif location_id:
                condition_for_check = rule.get("condition", "")
                if condition_for_check:
                    from app.models.world import get_location_by_id
                    _loc = get_location_by_id(location_id)
                    _rooms = (_loc or {}).get("rooms", []) if _loc else []
                    if _rooms:
                        _all_block = True
                        for _r in _rooms:
                            _rid = _r.get("id", "")
                            _p, _ = evaluate_condition(condition_for_check,
                                                        character_name, location_id, _rid)
                            if not _p:
                                _all_block = False
                                break
                        if _all_block:
                            message = localized(rule, "message", _user_lang()) or "Access denied."
                            logger.info("Rule blockiert %s: %s (alle Raeume)",
                                         character_name, rule.get("name", "?"))
                            return False, message
                        # At least one room is accessible; skip this rule.
                        continue
                else:
                    # No condition: the rule matches every room.
                    matched = True
        elif scope == "danger_level":
            min_danger = int(target.get("min_danger", target.get("min_danger_level", 0)) or 0)
            if target_danger >= min_danger:
                matched = True

        if not matched:
            continue

        # A true condition blocks access. Pass the room for room_has_item atoms.
        condition = rule.get("condition", "")
        if condition:
            passed, _ = evaluate_condition(condition, character_name, location_id, room_id)
            if passed:
                message = localized(rule, "message", _user_lang()) or "Access denied."
                logger.info("Rule blockiert %s: %s (%s)", character_name,
                           rule.get("name", "?"), message[:60])
                return False, message

    return True, ""


def check_leave(character_name: str, *,
                room_only: bool = False,
                target_location_id: str = "",
                target_room_id: str = "") -> Tuple[bool, str]:
    """Check block rules with ``action="leave"`` for the current standpoint.

    Called before every move (SetLocation skill, walk step, scheduler,
    chat narrative extract). It bites when the character may not leave its
    current room or place at all — the pinning/confine use case.

    ``room_only=True`` looks at room-level rules alone — for a room change
    inside the same location, where the location is not left but another
    room of it may still be closed by a room pinning rule.

    A rule is room-level as soon as it NAMES rooms, whichever scope word
    carries them (the RulesTab writes ``scope="location"`` plus a room
    selection, the event path ``scope="room"`` plus ``room_ids``).

    Confine-set semantics (a rule naming several rooms):
        Moving BETWEEN rooms of the same set is allowed (free movement
        inside the confinement). Only leaving the set is blocked. That
        needs a known target — pass ``target_location_id`` /
        ``target_room_id``, otherwise the block is conservative (e.g. in a
        walk step without a known target room).

    Same idea for a whole-location rule: a room change inside the same
    location (target_location_id == cur_loc) does not count as "leave".
    """
    from app.core.activity_engine import evaluate_condition
    from app.models.character import (
        get_character_current_location, get_character_current_room)
    cur_loc = get_character_current_location(character_name) or ""
    if not cur_loc:
        return True, ""
    cur_room = get_character_current_room(character_name) or ""

    for rule in load_rules():
        if rule.get("type") != "block":
            continue
        if rule_action(rule) != "leave":
            continue
        rule_char = (rule.get("character") or "").strip()
        if rule_char and rule_char != character_name:
            continue

        target = rule.get("target", {}) or {}
        scope = target.get("scope", "")
        if scope == "skill":
            continue
        t_loc, rule_room_ids = _rule_location_rooms(target)
        matched = False
        if scope in ("room", "location") and rule_room_ids and cur_room \
                and t_loc == cur_loc and cur_room in rule_room_ids:
            # A named room list makes the rule room-level, whichever scope word
            # carries it. Confine set: moving WITHIN room_ids (same location)
            # is free movement — only leaving the set is blocked.
            if target_location_id and target_location_id == cur_loc \
                    and target_room_id and target_room_id in rule_room_ids:
                continue
            matched = True
        elif scope == "location" and not rule_room_ids and not room_only \
                and t_loc == cur_loc:
            # A room change inside the same location is not "leaving" it.
            if target_location_id and target_location_id == cur_loc:
                continue
            matched = True
        elif scope == "any_room" and cur_room:
            matched = True
        # Danger-level targets do not apply to leaving.
        if not matched:
            continue

        condition = rule.get("condition", "")
        if condition:
            passed, _ = evaluate_condition(condition, character_name, cur_loc, cur_room)
            if not passed:
                continue
        message = localized(rule, "message", _user_lang()) or "You can't leave this place."
        logger.info("Rule blockiert Leave %s: %s (%s)", character_name,
                    rule.get("name", "?"), message[:60])
        return False, message

    return True, ""


def check_followers_leave(leader: str, *,
                          target_location_id: str = "",
                          target_room_id: str = "") -> Tuple[bool, str]:
    """``check_leave`` for every party follower of ``leader``.

    A leader's move drags its followers along (party drag), so a follower
    confined to its place must hold the whole party there — otherwise a
    leave rule only binds a character until someone takes it along. The
    NPC paths get this from ``movement_authority`` (every member passes the
    gate); the avatar's own move routes ask here. The reason names the
    follower, in the same ``"<name>: <reason>"`` form as movement_authority.
    """
    from app.core.party_engine import party_followers
    for follower in party_followers(leader):
        if not follower or follower == leader:
            continue
        ok, reason = check_leave(follower, target_location_id=target_location_id,
                                 target_room_id=target_room_id)
        if not ok:
            return False, f"{follower}: {reason}"
    return True, ""


# ============================================================
# FORCE RULES: check forced actions
# ============================================================

def check_force_rules(character_name: str) -> Optional[Dict[str, Any]]:
    """Return the first matching forced action, or None."""
    from app.core.activity_engine import evaluate_condition
    from app.models.character import get_character_current_location

    location_id = get_character_current_location(character_name) or ""

    # Character-specific rules take precedence over global defaults, so a
    # personal sleep rule cannot be undone immediately by a global wake rule.
    # Rules naming a different character do not apply.
    _all_rules = [r for r in load_rules() if r.get("type") == "force" and r.get("condition")]
    _own_rules: List[Dict[str, Any]] = []
    _global_rules: List[Dict[str, Any]] = []
    for r in _all_rules:
        rc = (r.get("character") or "").strip()
        if not rc:
            _global_rules.append(r)
        elif rc == character_name:
            _own_rules.append(r)
        # Otherwise it belongs to another character; skip it.
    ordered_rules = _own_rules + _global_rules

    for rule in ordered_rules:
        condition = rule.get("condition", "")
        passed, _ = evaluate_condition(condition, character_name, location_id)
        if not passed:
            continue
        force = rule.get("force_action", {})
        if not force:
            continue
        # Matching flags mean this action is already applied. A personal
        # rule suppresses global defaults; a global rule simply yields.
        _set_flags = force.get("set_flags") or {}
        already_applied = False
        if _set_flags:
            from app.models.character import get_state_flags
            _cur_flags = get_state_flags(character_name)
            def _norm(v):
                return v if isinstance(v, str) and v else bool(v)
            already_applied = all(
                _norm(_cur_flags.get(_k)) == _norm(_v)
                for _k, _v in _set_flags.items())
        is_char_specific = bool((rule.get("character") or "").strip())
        if already_applied:
            if is_char_specific:
                logger.debug(
                    "Char-spezifische Force-Rule '%s' bereits aktiv fuer %s "
                    "— globale Regeln blockiert", rule.get("name", "?"),
                    character_name)
                return None
            continue

        logger.info("Zwangs-Regel greift fuer %s: %s", character_name,
                   rule.get("name", "?"))
        _lang = _user_lang()
        return {
            "rule_id": rule.get("id", ""),
            "rule_name": localized(rule, "name", _lang),
            "go_to": force.get("go_to", "stay"),
            # Orthogonal state flags are authoritative, independent of activity text.
            "set_flags": force.get("set_flags") or {},
            "message": localized(rule, "message", _lang),
        }

    return None


def resolve_force_destination(character_name: str,
    go_to: str) -> Tuple[str, str]:
    """Resolve stay, home, sleep_location, or a location ID into location/room IDs."""
    from app.models.character import (
        get_character_config, get_character_current_location,
        get_character_current_room)

    if go_to == "stay":
        loc = get_character_current_location(character_name) or ""
        room = get_character_current_room(character_name) or ""
        return loc, room

    config = get_character_config(character_name)

    if go_to in ("sleep_location", "home"):
        # Home location is also the sleeping place.
        home_loc = config.get("home_location", "")
        home_room = config.get("home_room", "")
        if home_loc:
            return home_loc, home_room
        return _find_nearest_sleep(character_name)

    # "stay" wurde oben behandelt, alles andere ist eine direkte Location-ID

    # Direkte Location-ID
    return go_to, ""


# ============================================================
# DISCOVER RULES: reveal adjacent locations
# ============================================================

def check_discover_rules(character_name: str) -> Optional[Dict[str, Any]]:
    """Check the discover rules and possibly uncover a still-unknown location
    WITHIN SIGHT — ``game.discovery_range_m`` metres of where the character
    stands.

    How it works:
    - Iterates the discover rules in order.
    - Per rule: character filter, condition, then the probability roll.
    - The first rule with a successful roll wins — one random still-unknown
      location in range is then added to the known_locations list.

    METRES, NOT NEIGHBOURS (E6). This used to walk ``get_neighbor_location_ids``
    — the GRID neighbours of the cell one stood in. The seamless world has no
    grid, so that list was always empty and the whole rule type was dead. The
    range now comes from the same setting the deterministic sight pass uses
    (``core/discovery.py``), and the anchor is the character's POINT, not its
    location: out in the wilderness — where there is no current location at
    all, and where one meets new places — is exactly where this has to work.

    What is left for the rule beside that deterministic pass: a CONDITION
    ("attention>80"), a probability, and a MESSAGE. The sight pass reveals
    silently and unconditionally, so in a running world it will normally have
    taken everything in range before a thought turn gets here.

    THE MESSAGE HAS NO READER TODAY. The only caller (``agent_loop``) throws
    the return value away, so the rule's message is composed and returned into
    nothing; what actually reaches the world is the discovery itself (the new
    known_location shows up in the thought context) and the state-history
    entry. Wiring the message up as a perception payload is an open follow-up,
    not something this function does.

    Returns: dict with location_id/location_name/rule_*/message on a hit,
    otherwise None (nothing discovered this round).
    """
    import random as _random
    from app.core.activity_engine import evaluate_condition
    from app.core.discovery import get_discovery_range_m, locations_within
    from app.models.character import (
        get_character_current_location, get_character_pos, get_known_locations,
        add_known_location, record_state_change)
    from app.models.world import (
        list_locations, location_knowledge_gate_open, visibility_context)

    # The avatar discovers like everyone else: with fog of war (§ A12) the
    # player map shows only known_locations, so exempting the avatar would
    # leave it unable to ever uncover the map.
    pos = get_character_pos(character_name)
    if pos is None:
        return None
    range_m = get_discovery_range_m(character_name)
    if range_m <= 0:
        return None
    # May be empty (the wilderness) — it is context for the condition, not a
    # precondition for discovering.
    location_id = get_character_current_location(character_name) or ""

    all_locations = list_locations()
    known = get_known_locations(character_name)
    unknown = locations_within(pos["x"], pos["z"], range_m, all_locations,
                               exclude=known)
    if not unknown:
        return None
    # The KNOWLEDGE GATE applies to the roll as well. ``locations_within``
    # drops what is already known; a place whose ``knowledge_item_id`` the
    # character does not hold is not known either, but it must not enter the
    # pool: the gate would keep it invisible afterwards, so the roll would be
    # burnt AND — the real damage — the secret location's NAME would be
    # written into the state history below, from where admin views and recent
    # activity read it. The silent sight pass needs no such filter (there
    # known and gate are conjunctive, so pre-knowledge does no harm).
    by_id = {(loc.get("id") or ""): loc for loc in all_locations or []}
    _vis_ctx = visibility_context(character_name)
    unknown = [loc_id for loc_id in unknown
               if location_knowledge_gate_open(character_name,
                                               by_id.get(loc_id) or {},
                                               _vis_ctx)]
    if not unknown:
        return None

    for rule in load_rules():
        if rule.get("type") != "discover":
            continue
        rule_char = (rule.get("character") or "").strip()
        if rule_char and rule_char != character_name:
            continue
        condition = (rule.get("condition") or "").strip()
        if condition:
            passed, _ = evaluate_condition(condition, character_name, location_id)
            if not passed:
                continue
        try:
            probability = float(rule.get("probability", 0))
        except (TypeError, ValueError):
            probability = 0.0
        probability = max(0.0, min(1.0, probability))
        if probability <= 0.0 or _random.random() >= probability:
            continue

        discovered_id = _random.choice(unknown)
        add_known_location(character_name, discovered_id)
        loc = by_id.get(discovered_id) or {}
        loc_name = loc.get("name", discovered_id)
        _lang = _user_lang()
        message = (localized(rule, "message", _lang) or "").strip() \
            or f"Discovered a new place: {loc_name}"
        try:
            record_state_change(character_name, "discovery", loc_name,
                metadata={"location_id": discovered_id,
                          "rule_id": rule.get("id", ""),
                          "rule_name": rule.get("name", "")})
        except Exception:
            pass
        logger.info("Discover rule '%s' for %s -> %s",
                    rule.get("name", "?"), character_name, loc_name)
        return {
            "location_id": discovered_id,
            "location_name": loc_name,
            "rule_id": rule.get("id", ""),
            "rule_name": localized(rule, "name", _lang),
            "message": message,
        }

    return None


# ============================================================
# HELPER
# ============================================================

def _get_target_danger_level(location_id: str, room_id: str = "") -> int:
    """Return target danger, with the room overriding its location."""
    try:
        from app.models.world import get_location_by_id
        location = get_location_by_id(location_id)
        if not location:
            return 0

        # Raum-spezifischer danger_level
        if room_id:
            for room in location.get("rooms", []):
                if room.get("id") == room_id:
                    room_danger = room.get("danger_level")
                    if room_danger is not None:
                        return max(0, min(5, int(room_danger)))
                    break

        # Location danger_level
        return max(0, min(5, int(location.get("danger_level", 0))))
    except Exception:
        return 0


def _find_nearest_sleep(character_name: str) -> Tuple[str, str]:
    """Fallback sleep spot when no home_location is set: sleep where you are.

    The old activity-library lookup (a room tagged with a "sleeping"
    activity) is gone — activities are free text now — so there is nothing
    to search for. The character stays at its current location/room.
    Returns: (location_id, room_id) or ("", "").
    """
    try:
        from app.models.character import (
            get_character_current_location, get_character_current_room)
        loc = get_character_current_location(character_name) or ""
        room = get_character_current_room(character_name) or ""
        return loc, room
    except Exception:
        return "", ""


def _rules_changed(old_rules, new_rules) -> None:
    """Notify removed, added and both scopes of changed rules, by stored id."""
    try:
        from app.core.modifiers import invalidate_cache
        invalidate_cache()
    except Exception:
        pass
    try:
        from app.core import sync_topics
        def indexed(rules):
            return {r["id"]: {k: v for k, v in r.items() if not k.startswith("_")}
                    for r in rules if r.get("id")}
        before, after = indexed(old_rules), indexed(new_rules)
        for rid in before.keys() | after.keys():
            if before.get(rid) == after.get(rid):
                continue
            for rule in (before.get(rid), after.get(rid)):
                if rule is None:
                    continue
                target = rule.get("target") or {}
                location, _ = _rule_location_rooms(target)
                character = (rule.get("character") or "").strip()
                if character:
                    to = sync_topics.Avatar(character)
                elif target.get("scope") in ("location", "room") and location:
                    to = sync_topics.AtLocation(location)
                else:
                    to = sync_topics.Everyone()
                sync_topics.notify(("notices", "scene", "world"), to=to)
    except Exception as e:
        logger.debug("rule sync failed: %s", e)
