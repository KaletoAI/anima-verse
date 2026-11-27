"""The core's built-in quest types and the evaluation context they read (quest system stages 1 and 2).

Registered once under the owner ``"core"`` by :func:`register` (the catalog contract of
``app/core/quest_catalog.py``). Every type is generic: no stat, item or package is named here; stat keys and
expressions are data of the template.

READ RULE (plan Global Constraints, Review Focus 4): location, room and inventory are read for the ACTING BODY
(``QuestContext.avatar``); facts are read for its MIND (``QuestContext.mind`` = ``mind_of(avatar)``), and a bound
character is compared by ITS mind, so "has spoken with" survives a body swap on either side.

OBJECTS & TARGETS (stage 2): ``QuestContext.objects`` maps each effect key of the run to the ref of its first live
object (marker rows excluded). Target parameters (``holds_item``, ``knows_secret``, ``found_item``, ``near_object``)
resolve a key against ``ctx.bindings`` first and then ``ctx.objects``, answering unavailable when a role is unbound
or an object is not live yet.

THREE STATES: every ``evaluate`` answers a ``ConditionResult``; it is unavailable (never false) when its role or
target is unbound, missing or malformed, or when its read fails: a failed read is not a "no". Reasons are English.

The catalog fills declared defaults in and drops an absent parameter without a default before it calls
``evaluate`` / ``validate``, so parameters are read with ``params.get``.
"""
from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from app.core.activity_engine import ConditionIssue, ConditionResult
from app.core.game_time import GameDuration, GameTime
from app.core.log import get_logger

logger = get_logger("quest_types")

OWNER = "core"
#: The comparison operators of ``stat_compare``.
STAT_OPS = (">=", "<=", ">", "<", "=")
#: The fact kind ``spoke_with`` reads (written by the engine on ``utterance.heard``).
FACT_SPOKE_WITH = "spoke_with"
#: The fact kind ``found_item`` reads (written by the engine on ``item.discovered``).
FACT_FOUND = "found"
#: Maximum length of an ``llm_judgement`` criterion.
MAX_JUDGEMENT_CRITERION_CHARS = 500


def found_subject(location_id: str, room_id: str, item_id: str) -> str:
    """Subject string of a ``found`` fact for one room placement."""
    return f"{location_id}/{room_id}/{item_id}"


@dataclass(frozen=True)
class QuestContext:
    avatar: str            # acting body
    mind: str              # mind_of(avatar)
    profile: dict
    location_id: str
    room_id: str
    now: GameTime
    bindings: dict         # role key -> binding (D6)
    run: dict              # the run row (started_game_ts for elapsed time)
    objects: dict = dataclasses.field(default_factory=dict)  # effect_key -> ref of the run's first live object (markers excluded)


def build_context(avatar: str, run: dict) -> QuestContext | None:
    """The context of ``avatar`` for ``run``, read once: the strict profile, its location/room, the strict game
    clock and the run's live object refs. None when the profile, clock or run objects cannot be read."""
    from app.core.linked_characters import mind_of
    from app.core.timeutils import game_time
    from app.models.character import get_character_profile
    from app.models.quests import live_object_refs
    name = (avatar or "").strip()
    if not name:
        return None
    run = run if isinstance(run, dict) else {}
    run_id = str(run.get("id") or "")
    try:
        profile = get_character_profile(name, strict=True)
        now = game_time(strict=True)
        objects = live_object_refs(run_id) if run_id else {}
    except Exception as e:  # noqa: BLE001 - an unreadable avatar has no context, the caller skips it
        logger.warning("quest context for %s unavailable: %s", name, e)
        return None
    if not isinstance(profile, dict) or not profile:
        return None
    bindings = run.get("bindings")
    return QuestContext(
        avatar=name, mind=mind_of(name), profile=profile,
        location_id=str(profile.get("current_location") or ""),
        room_id=str(profile.get("current_room") or ""),
        now=now, bindings=bindings if isinstance(bindings, dict) else {}, run=run,
        objects=objects)


# --- Bindings ------------------------------------------------------------------------------

#: role kind -> the keys its binding must carry (D6).
_BINDING_KEYS = {"character": ("name",), "location": ("location_id",),
                 "room": ("location_id", "room_id"), "item": ("item_id",)}


def _filled(binding: Any, keys: Tuple[str, ...]) -> bool:
    return isinstance(binding, dict) and all(
        isinstance(binding.get(k), str) and binding[k].strip() for k in keys)


def check_binding(kind: str, binding: dict) -> list[ConditionIssue]:
    """The issues of one role binding: a malformed binding, or no entity of that kind under it.

    Strict readers: a STORAGE failure raises. It is not evidence that the entity is gone, so a caller that
    marks runs broken must not turn it into an issue. A dormant linked body exists; a pooled NPC does not."""
    keys = _BINDING_KEYS.get(kind)
    if keys is None:
        return [ConditionIssue("bad_binding", f"Unknown role kind '{kind}'")]
    if not _filled(binding, keys):
        return [ConditionIssue("bad_binding", f"A {kind} binding needs {', '.join(keys)}")]
    if kind == "character":
        from app.models.character import list_available_characters
        name = binding["name"]
        if name not in list_available_characters(include_dormant=True, strict=True):
            return [ConditionIssue("unknown_character", f"Character '{name}' does not exist")]
        return []
    if kind == "item":
        from app.models.inventory import get_item
        if get_item(binding["item_id"], strict=True) is None:
            return [ConditionIssue("unknown_item", f"Item '{binding['item_id']}' does not exist")]
        return []
    from app.models.world import get_location_by_id, get_room_by_id
    location = get_location_by_id(binding["location_id"], strict=True)
    if location is None:
        return [ConditionIssue("unknown_location", f"Location '{binding['location_id']}' does not exist")]
    if kind == "room" and get_room_by_id(location, binding["room_id"]) is None:
        return [ConditionIssue("unknown_room",
                               f"Room '{binding['room_id']}' does not exist in '{binding['location_id']}'")]
    return []


def _bound(ctx: QuestContext, params: dict, param: str,
           *need: str) -> Tuple[Optional[dict], Optional[ConditionResult]]:
    """(binding, None) for the role named by ``params[param]``, or (None, an unavailable result)."""
    role = params.get(param)
    binding = (ctx.bindings or {}).get(role) if isinstance(role, str) else None
    if not _filled(binding, need):
        return None, ConditionResult(False, False, f"Role '{role}' is not bound")
    return binding, None


def _target(ctx: QuestContext, params: dict, param: str,
            *need: str) -> Tuple[Optional[dict], Optional[ConditionResult]]:
    """(binding_or_ref, None) for the role or live object named by ``params[param]``, or (None, unavailable)."""
    key = params.get(param)
    if not isinstance(key, str) or not key:
        return None, ConditionResult(False, False, f"'{key}' is not bound or does not exist yet")
    bindings = ctx.bindings or {}
    if key in bindings:
        binding = bindings[key]
        if not _filled(binding, need):
            return None, ConditionResult(False, False, f"Role '{key}' is not bound")
        return binding, None
    objects = ctx.objects or {}
    if key in objects:
        ref = objects[key]
        if not _filled(ref, need):
            return None, ConditionResult(False, False, f"Object '{key}' is malformed")
        return ref, None
    return None, ConditionResult(False, False, f"'{key}' is not bound or does not exist yet")


def _avatar_point(ctx: QuestContext) -> Optional[Tuple[float, float]]:
    """The avatar's current world point in metres (journey-aware)."""
    from app.core.timeutils import motion_time
    from app.core.travel_engine import get_journey, journey_state
    from app.models.character import get_character_pos
    journey = get_journey(ctx.avatar, profile=dict(ctx.profile))
    if journey:
        x, z = journey_state(journey["waypoints"], journey["started_at_s"], motion_time())["pos"]
        return float(x), float(z)
    pos = get_character_pos(ctx.avatar, strict=True)
    return (pos["x"], pos["z"]) if pos else None


# --- Types -----------------------------------------------------------------------------------

def _at_place(params: dict, ctx: QuestContext) -> ConditionResult:
    binding, missing = _bound(ctx, params, "place", "location_id")
    if missing:
        return missing
    if ctx.location_id != binding["location_id"]:
        return ConditionResult(True, False, "Not at the place")
    room = binding.get("room_id") or ""
    if room and ctx.room_id != room:
        return ConditionResult(True, False, "Not in the room")
    return ConditionResult(True, True, "")


def _holds_item(params: dict, ctx: QuestContext) -> ConditionResult:
    from app.models.inventory import get_item_quantity
    binding, missing = _target(ctx, params, "item", "item_id")
    if missing:
        return missing
    count = params.get("count") or 1
    try:
        held = get_item_quantity(ctx.avatar, binding["item_id"], strict=True)
    except Exception as e:  # noqa: BLE001 - a failed read is unavailable, not "holds none"
        return ConditionResult(False, False, f"Inventory unavailable: {e}")
    if held >= count:
        return ConditionResult(True, True, "")
    return ConditionResult(True, False, f"Holds {held} of {count}")


def _compare(left: int, op: str, right: int) -> bool:
    return {">=": left >= right, "<=": left <= right, ">": left > right,
            "<": left < right, "=": left == right}[op]


def _stat_compare(params: dict, ctx: QuestContext) -> ConditionResult:
    from app.core.stat_boosts import effective_stat
    stat, op, value = params.get("stat"), params.get("op"), params.get("value")
    if not isinstance(stat, str) or not stat or op not in STAT_OPS \
            or not isinstance(value, int) or isinstance(value, bool):
        return ConditionResult(False, False, "The stat comparison is incomplete")
    try:
        current = effective_stat(ctx.profile, stat, strict=True)
    except Exception as e:  # noqa: BLE001
        return ConditionResult(False, False, f"Stat '{stat}' unavailable: {e}")
    if current is None:
        return ConditionResult(False, False, f"Stat '{stat}' unavailable")
    if _compare(current, op, value):
        return ConditionResult(True, True, "")
    return ConditionResult(True, False, f"{stat} is {current} (needs {op} {value})")


def _spoke_with(params: dict, ctx: QuestContext) -> ConditionResult:
    from app.core.linked_characters import mind_of
    from app.models.quests import fact_last_at, has_fact
    binding, missing = _bound(ctx, params, "character", "name")
    if missing:
        return missing
    target_mind = mind_of(binding["name"])
    if params.get("since_step"):
        since = str((ctx.run or {}).get("step_started_at") or "")
        if since:
            try:
                last_at = fact_last_at(ctx.mind, FACT_SPOKE_WITH, target_mind)
            except Exception as e:  # noqa: BLE001
                return ConditionResult(False, False, f"Facts unavailable: {e}")
            if last_at and last_at > since:
                return ConditionResult(True, True, "")
            return ConditionResult(True, False, f"Has not spoken with {binding['name']} since this step began")
    try:
        spoke = has_fact(ctx.mind, FACT_SPOKE_WITH, target_mind)
    except Exception as e:  # noqa: BLE001
        return ConditionResult(False, False, f"Facts unavailable: {e}")
    if spoke:
        return ConditionResult(True, True, "")
    return ConditionResult(True, False, f"Has not spoken with {binding['name']}")


def _time_elapsed(params: dict, ctx: QuestContext) -> ConditionResult:
    hours = params.get("hours")
    started = str((ctx.run or {}).get("started_game_ts") or "")
    if not isinstance(hours, int) or isinstance(hours, bool):
        return ConditionResult(False, False, "Hours are missing")
    if not started:
        return ConditionResult(False, False, "The quest has not opened")
    try:
        due = GameTime.parse(started) + GameDuration.of(hours=hours)
    except Exception as e:  # noqa: BLE001 - a malformed stamp is unavailable
        return ConditionResult(False, False, f"Start time unreadable: {e}")
    if ctx.now >= due:
        return ConditionResult(True, True, "")
    return ConditionResult(True, False, "Not enough time has passed")


def _expression(params: dict, ctx: QuestContext) -> ConditionResult:
    from app.core.activity_engine import evaluate_condition_strict
    expr = params.get("expression")
    if not isinstance(expr, str) or not expr.strip():
        return ConditionResult(False, False, "The expression is empty")
    return evaluate_condition_strict(expr, ctx.avatar, ctx.location_id, ctx.room_id, profile=ctx.profile)


def _validate_expression(params: dict, bindings: dict | None) -> List[ConditionIssue]:
    from app.core.activity_engine import validate_condition_expression
    expr = params.get("expression")
    return validate_condition_expression(expr) if isinstance(expr, str) else []


def _knows_secret(params: dict, ctx: QuestContext) -> ConditionResult:
    from app.core.linked_characters import mind_of
    from app.models import secrets
    ref, missing = _target(ctx, params, "secret", "owner", "secret_id")
    if missing:
        return missing
    try:
        secret = secrets.get_secret(ref["owner"], ref["secret_id"])
    except Exception as e:  # noqa: BLE001
        return ConditionResult(False, False, f"Secrets unavailable: {e}")
    if secret is None:
        return ConditionResult(False, False, "The secret is gone")
    if mind_of(ctx.avatar) == mind_of(ref["owner"]) or secrets.knows(secret, ctx.avatar):
        return ConditionResult(True, True, "")
    return ConditionResult(True, False, "Does not know the secret")


def _found_item(params: dict, ctx: QuestContext) -> ConditionResult:
    from app.models.quests import has_fact
    ref, missing = _target(ctx, params, "placement", "location_id", "room_id", "item_id")
    if missing:
        return missing
    subject = found_subject(ref["location_id"], ref["room_id"], ref["item_id"])
    try:
        found = has_fact(ctx.mind, FACT_FOUND, subject)
    except Exception as e:  # noqa: BLE001
        return ConditionResult(False, False, f"Facts unavailable: {e}")
    if found:
        return ConditionResult(True, True, "")
    return ConditionResult(True, False, "Has not found it")


def _near_object(params: dict, ctx: QuestContext) -> ConditionResult:
    from app.models import world_props
    ref, missing = _target(ctx, params, "object")
    if missing:
        return missing
    key = params.get("object")
    if _filled(ref, ("placement_id",)):
        placement_id = ref["placement_id"]
        try:
            rows = world_props.list_world_props()
        except Exception as e:  # noqa: BLE001
            return ConditionResult(False, False, f"World props unavailable: {e}")
        row = next((r for r in rows if r.get("id") == placement_id), None)
        if row is None:
            return ConditionResult(False, False, "The object is gone")
        try:
            point = _avatar_point(ctx)
        except Exception as e:  # noqa: BLE001
            return ConditionResult(False, False, f"Position unavailable: {e}")
        if point is None:
            return ConditionResult(True, False, "Has no position on the map")
        px, pz = point
        distance = math.hypot(px - row["x"], pz - row["z"])
        radius = params.get("radius_m")
        if radius is None:
            radius = 10
        if distance <= radius:
            return ConditionResult(True, True, "")
        return ConditionResult(True, False, f"{distance:.1f} m away (needs {radius:g} m)")
    if _filled(ref, ("location_id", "room_id")):
        if ctx.location_id == ref["location_id"] and ctx.room_id == ref["room_id"]:
            return ConditionResult(True, True, "")
        return ConditionResult(True, False, "Not in the room")
    return ConditionResult(False, False, f"Object '{key}' has no position")


def _relationship_at_least(params: dict, ctx: QuestContext) -> ConditionResult:
    from app.models.relationship import get_relationship
    binding, missing = _bound(ctx, params, "character", "name")
    if missing:
        return missing
    need = params.get("strength")
    if not isinstance(need, int) or isinstance(need, bool):
        return ConditionResult(False, False, "Strength is missing")
    other = binding["name"]
    try:
        rel = get_relationship(ctx.avatar, other, strict=True)
    except Exception as e:  # noqa: BLE001
        return ConditionResult(False, False, f"Relationship unavailable: {e}")
    if rel is None:
        strength = 0.0  # no row is the neutral baseline, as evaluate_condition_strict reads it
    else:
        try:
            strength = float(rel["strength"])
        except (KeyError, TypeError, ValueError):
            return ConditionResult(False, False, f"Relationship strength to {other} unavailable")
    if strength >= need:
        return ConditionResult(True, True, "")
    return ConditionResult(True, False, f"Relationship to {other} is {strength:g} (needs {need})")


def _validate_llm_judgement(params: dict, bindings: dict | None) -> List[ConditionIssue]:
    criterion = params.get("criterion")
    if isinstance(criterion, str) and len(criterion) > MAX_JUDGEMENT_CRITERION_CHARS:
        return [ConditionIssue(
            "too_long",
            f"Criterion must be at most {MAX_JUDGEMENT_CRITERION_CHARS} characters",
        )]
    return []


def _llm_judgement(params: dict, ctx: QuestContext) -> ConditionResult:
    from app.core import quest_engine, quest_judgement
    from app.models.quests import get_judgement
    run = ctx.run or {}
    criterion = quest_engine.render_text(str(params.get("criterion") or ""), run)
    run_id = str(run.get("id") or "")
    if not run_id:
        return ConditionResult(True, False, "Not judged yet")
    step = int(run.get("current_step") or 0)
    key = quest_judgement.criterion_key(criterion)
    try:
        row = get_judgement(run_id, step, key, ctx.mind)
    except Exception as e:  # noqa: BLE001 - a failed read is unavailable
        return ConditionResult(False, False, f"Judgement unavailable: {e}")
    if row is not None and row.get("state") == "yes":
        return ConditionResult(True, True, "")
    quest_judgement.request(ctx, criterion)
    reason = (row.get("reason") or "").strip() if row is not None else ""
    return ConditionResult(True, False, reason or "Not judged yet")


def _role(key: str, label: str, kinds: List[str], description: str) -> Dict[str, Any]:
    return {"key": key, "type": "role", "label": label, "description": description,
            "role_kinds": kinds, "required": True}


def _builtin_types() -> list:
    from app.core import quest_effects
    from app.core.quest_catalog import QuestType
    return [
        QuestType(
            id="at_place", kind="condition", label="Is at a place",
            description="The avatar stands at the bound location, or in the bound room.",
            params=(_role("place", "Place", ["location", "room"], "Where the avatar must be"),),
            signals=("character.entered_room",), evaluate=_at_place),
        QuestType(
            id="holds_item", kind="condition", label="Holds an item",
            description="The avatar carries at least the given number of the bound item.",
            params=({"key": "item", "type": "target", "label": "Item",
                     "description": "What the avatar must carry",
                     "role_kinds": ["item"], "object_kinds": ["item"], "required": True},
                    {"key": "count", "type": "int", "label": "Count", "description": "How many at least",
                     "default": 1, "min": 1, "step": 1}),
            signals=("inventory.changed",), evaluate=_holds_item),
        QuestType(
            id="stat_compare", kind="condition", label="Stat compares to a value",
            description="The avatar's effective stat compares true against the value.",
            params=({"key": "stat", "type": "str", "label": "Stat", "description": "The stat key",
                     "required": True},
                    {"key": "op", "type": "select", "label": "Comparison", "choices": list(STAT_OPS),
                     "choice_labels": ["at least", "at most", "more than", "less than", "exactly"],
                     "default": ">="},
                    {"key": "value", "type": "int", "label": "Value", "required": True}),
            signals=("world_tick",), evaluate=_stat_compare),
        QuestType(
            id="spoke_with", kind="condition", label="Has spoken with",
            description="The avatar has spoken with the bound character (remembered by the mind).",
            params=(_role("character", "Character", ["character"], "Who the avatar must speak with"),
                    {"key": "since_step", "type": "bool", "label": "Only since this step began",
                     "description": "Count only a talk after the current step started", "default": False}),
            signals=("utterance.heard",), evaluate=_spoke_with),
        QuestType(
            id="time_elapsed", kind="condition", label="Time has passed",
            description="At least the given number of game hours have passed since the quest opened.",
            params=({"key": "hours", "type": "int", "label": "Hours",
                     "description": "Game hours since the quest opened", "min": 1, "step": 1,
                     "required": True},),
            signals=("world_tick",), evaluate=_time_elapsed, needs_open_run=True),
        QuestType(
            id="expression", kind="condition", label="Condition expression",
            description="An expression of the activity condition grammar holds for the avatar.",
            params=({"key": "expression", "type": "text", "label": "Expression",
                     "description": "e.g. night AND alone", "required": True},),
            signals=("world_tick", "character.entered_room", "inventory.changed"),
            validate=_validate_expression, evaluate=_expression),
        QuestType(
            id="knows_secret", kind="condition", label="Knows a secret",
            description="The avatar knows the secret a quest effect created (through its mind).",
            params=({"key": "secret", "type": "target", "label": "Secret",
                     "description": "Which secret the avatar must know",
                     "role_kinds": [], "object_kinds": ["secret"], "required": True},),
            signals=("secret.learned",), evaluate=_knows_secret),
        QuestType(
            id="found_item", kind="condition", label="Has found a placement",
            description="The avatar has discovered the hidden placement a quest effect made (remembered by the mind).",
            params=({"key": "placement", "type": "target", "label": "Placement",
                     "description": "Which placement the avatar must find",
                     "role_kinds": [], "object_kinds": ["room_item"], "required": True},),
            signals=("item.discovered",), evaluate=_found_item),
        QuestType(
            id="near_object", kind="condition", label="Is near an object",
            description="The avatar is within the radius of a free-standing object the quest created, or in the room of a room object.",
            params=({"key": "object", "type": "target", "label": "Object",
                     "description": "Which object the avatar must be near",
                     "role_kinds": [], "object_kinds": ["world_prop", "room_prop", "room_item"],
                     "required": True},
                    {"key": "radius_m", "type": "float", "label": "Radius (m)",
                     "description": "How close in metres", "min": 1, "max": 200, "default": 10}),
            signals=("character.entered_room", "world_tick"), evaluate=_near_object),
        QuestType(
            id="llm_judgement", kind="condition", label="The scene shows ...",
            description="The tool model judges what the avatar said and heard since this step began against a criterion.",
            params=({"key": "criterion", "type": "text", "label": "What must have happened",
                     "required": True, "placeholders": True},),
            signals=("utterance.spoken", "quest.judged"),
            validate=_validate_llm_judgement, evaluate=_llm_judgement, step_only=True),
        QuestType(
            id="relationship_at_least", kind="prerequisite", label="Relationship at least",
            description="The avatar's relationship strength to the bound character is at least the value (0-100).",
            params=(_role("character", "Character", ["character"], "The other side of the relationship"),
                    {"key": "strength", "type": "int", "label": "Strength", "description": "0 to 100",
                     "min": 0, "max": 100, "step": 1, "required": True}),
            evaluate=_relationship_at_least),
        *quest_effects.builtin_effect_types(),
    ]


def register() -> None:
    """Register the built-in types under the owner ``"core"`` (a second call replaces the first)."""
    from app.core import quest_catalog
    quest_catalog.register(OWNER, _builtin_types)
