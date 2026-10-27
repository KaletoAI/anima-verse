"""Targeted RP stat extraction over canonical, server-owned source identities.

The existing chat-state LLM evaluates every required source/recipient pair in
one response. This module grants no authority to narrative names or model
actors: targets come from publication receipts, and factors/caps are applied
locally after parsing. Each pair commits independently through the durable
receipt model; failed pairs never publish their reserved RAM budget.
"""
from __future__ import annotations

from copy import deepcopy

from app.core.log import get_logger
from app.core.stat_sources import StatExtractionContext, StatSource

logger = get_logger("chat_stat_effects")


def _ordered_sources(context: StatExtractionContext) -> tuple[StatSource, ...]:
    """Deduplicate canonical events without accepting conflicting identities."""
    sources = {}
    for source in context.sources:
        if not isinstance(source, StatSource) or not source.event_id:
            raise ValueError("Stat context contains a source without a canonical event identity")
        previous = sources.setdefault(source.event_id, source)
        if previous != source:
            raise ValueError("Stat context contains conflicting records for one event")
    return tuple(sorted(sources.values(), key=lambda source: (source.order, source.event_id)))


def _recipients(context: StatExtractionContext, source: StatSource) -> tuple[str, ...]:
    """Ownership is frozen at publication, not inferred from a current avatar."""
    owner = context.character
    if source.medium == "self":
        if (source.actor is None and source.event_id == context.self_event_id
                and source.allowed_targets == (owner,)
                and not source.avatar_audience and not source.avatar_targets):
            return (owner,)
        return ()
    if source.actor == owner:
        return tuple(sorted({name for name in source.avatar_targets
                             if name != owner and name in source.allowed_targets
                             and name in source.avatar_audience}))
    if owner in source.allowed_targets and owner not in source.avatar_audience:
        return (owner,)
    return ()


def _profile_snapshot(names: set[str]) -> tuple[dict[str, dict], dict[str, dict], dict[str, Exception]]:
    """Read every required profile/config once; never substitute default state."""
    from app.models.character import get_character_config, get_character_profile

    profiles, configs, errors = {}, {}, {}
    for name in sorted(names):
        try:
            profile = get_character_profile(name, strict=True)
            config = get_character_config(name, profile=profile, strict=True)
        except LookupError as error:
            # A deleted/unknown actor has no rule role. The recipient caller
            # separately requires a real profile before it can commit anything.
            errors[name] = error
        except Exception as error:
            errors[name] = error
            logger.warning("Cannot snapshot RP stat character %s: %s", name, error)
        else:
            profiles[name], configs[name] = profile, config
    return profiles, configs, errors


def _stat_keys(name: str, profile: dict, config: dict) -> set[str]:
    """Eligible keys are declared AND stored; English prompt text is not a schema."""
    from app.models.character_template import get_template, is_feature_enabled

    if not is_feature_enabled(name, "status_effects_enabled", profile=profile, config=config):
        return set()
    template = get_template(profile.get("template", ""))
    status = profile.get("status_effects")
    if not template or not isinstance(status, dict):
        return set()
    return {field["key"] for section in template.get("sections", [])
            for field in section.get("fields", [])
            if field.get("store") == "status_effects"
            and isinstance(field.get("key"), str) and field["key"] in status}


def build_stat_targets(context: StatExtractionContext) -> dict:
    """Build opaque prompt tokens and their non-serialized canonical authority."""
    from app.core.stat_effects import build_stat_list
    from app.models.chat_stat_evaluations import has_evaluation

    sources = _ordered_sources(context)
    candidates = [(source, recipient) for source in sources
                  for recipient in _recipients(context, source)
                  if not has_evaluation(source.event_id, recipient)]
    profiles, configs, errors = _profile_snapshot({recipient for _, recipient in candidates})
    for error in errors.values():
        if not isinstance(error, LookupError):
            raise error
    eligible = {}
    for name, profile in profiles.items():
        keys = _stat_keys(name, profile, configs[name])
        if not keys:
            continue
        enabled, stat_list = build_stat_list(name, profile=profile, config=configs[name])
        if enabled and stat_list:
            eligible[name] = (keys, stat_list)

    result = {"stat_sources": [], "stat_targets": [], "required_stat_pairs": [], "pair_map": {}}
    source_tokens, target_tokens = {}, {}
    for source, recipient in candidates:
        if recipient not in eligible:
            continue
        if source.event_id not in source_tokens:
            token = f"S{len(source_tokens)}"
            source_tokens[source.event_id] = token
            result["stat_sources"].append({
                "id": token, "actor": source.actor, "text": source.content, "medium": source.medium,
            })
        if recipient not in target_tokens:
            token = f"T{len(target_tokens)}"
            target_tokens[recipient] = token
            result["stat_targets"].append({
                "id": token, "name": recipient, "stat_list": eligible[recipient][1],
            })
        event, target = source_tokens[source.event_id], target_tokens[recipient]
        result["required_stat_pairs"].append({"event": event, "target": target})
        result["pair_map"][(event, target)] = {
            "source": source, "recipient": recipient, "keys": eligible[recipient][0],
        }
    return result


def _validated_deltas(deltas: object, keys: set[str]) -> dict[str, int]:
    if not isinstance(deltas, dict):
        raise ValueError("Each stat result requires a deltas object (empty {} is allowed)")
    result = {}
    for key, delta in deltas.items():
        if not isinstance(key, str) or key not in keys:
            raise ValueError(f"Stat result contains an undeclared or unavailable stat key: {key!r}")
        if type(delta) is not int or not -100 <= delta <= 100:
            raise ValueError(f"Stat delta for {key!r} must be an integer from -100 to 100, not a boolean or float")
        result[key] = delta
    return result


def parse_stat_results(data: dict, targets: dict) -> list[dict]:
    """Reject the entire stat section unless every required pair occurs once."""
    if not isinstance(data, dict) or not isinstance(data.get("stat_results"), list):
        raise ValueError("Chat stat contract requires stat_results: [{event,target,deltas}]; legacy flat stats are unsupported")
    pair_map = targets["pair_map"]
    seen, results = set(), []
    for item in data["stat_results"]:
        if not isinstance(item, dict) or set(item) != {"event", "target", "deltas"}:
            raise ValueError("Each stat result must contain exactly event, target and deltas; actors/factors are server-owned")
        event, target = item["event"], item["target"]
        if not isinstance(event, str) or not isinstance(target, str) or (event, target) not in pair_map:
            raise ValueError("Stat result uses an unknown event/target token; use only the required_stat_pairs shown")
        pair = event, target
        if pair in seen:
            raise ValueError("Stat result repeats an event/target pair; return every required pair exactly once")
        authority = pair_map[pair]
        deltas = _validated_deltas(item["deltas"], authority["keys"])
        seen.add(pair)
        results.append({"source": authority["source"], "recipient": authority["recipient"], "deltas": deltas})
    if seen != set(pair_map):
        raise ValueError("Stat results omit required event/target pairs; return an explicit empty deltas object for no effect")
    return results


def apply_chat_stat_results(context: StatExtractionContext, results: list[dict]) -> list[dict]:
    """Apply source-ordered pairs with one snapshot and one atomic commit each.

    All authority, deltas and factors are resolved before the first write. No
    LLM/provider/capability executes under a budget or character-profile lock.
    The receipt model owns targeted sync after its database commit.
    """
    from app.core.keyed_lock import keyed_lock
    from app.core.stat_influence import influence_factor
    from app.core.stat_rules import reserve_chat_deltas, round_half_away
    from app.core.timeutils import game_time
    from app.models.chat_stat_evaluations import commit_evaluation, has_evaluation
    from app.models.rules import load_rules

    sources = {source.event_id: source for source in _ordered_sources(context)}
    pending, seen = [], set()
    for result in results:
        if not isinstance(result, dict) or set(result) != {"source", "recipient", "deltas"}:
            raise ValueError("Parsed RP stat result must contain source, recipient and deltas")
        source, recipient = result["source"], result["recipient"]
        if (not isinstance(source, StatSource) or sources.get(source.event_id) != source
                or not isinstance(recipient, str) or recipient not in _recipients(context, source)):
            raise ValueError("RP stat result is not authorized by this extractor's canonical sources")
        pair = source.event_id, recipient
        if pair in seen:
            raise ValueError("RP stat application repeats an event/recipient pair")
        seen.add(pair)
        pending.append(result)
    if not pending:
        return []
    pending.sort(key=lambda result: (result["source"].order, result["source"].event_id, result["recipient"]))

    try:
        now = game_time(strict=True)
        game_ts, game_hour = now.canonical(), now.total_seconds // 3600
        rules = deepcopy(load_rules(strict=True))
    except Exception:
        logger.warning("Cannot snapshot RP influence clock/rules; no pairs were applied", exc_info=True)
        return [{"event_id": result["source"].event_id, "recipient": result["recipient"],
                 "status": "failed", "changes": {}} for result in pending]
    names = {result["recipient"] for result in pending}
    names.update(result["source"].actor for result in pending if result["source"].actor)
    profiles, configs, errors = _profile_snapshot(names)
    keys = {name: _stat_keys(name, profile, configs[name]) for name, profile in profiles.items()}
    plans = []
    for result in pending:
        source, recipient = result["source"], result["recipient"]
        if recipient not in profiles or not keys.get(recipient):
            plans.append((result, None, None))
            continue
        actor_error = errors.get(source.actor)
        if actor_error is not None and not isinstance(actor_error, LookupError):
            plans.append((result, None, None))
            continue
        deltas = _validated_deltas(result["deltas"], keys[recipient])
        modified, cause = {}, {}
        try:
            for key, base in deltas.items():
                influence = influence_factor(source.actor, recipient, key, base, rules=rules, profiles=profiles)
                delta = round_half_away(base * influence["factor"])
                modified[key] = delta
                cause[key] = {
                    "actor": source.actor, "base_delta": base, "modified_delta": delta,
                    "factor": influence["factor"], "rules": influence["rules"],
                }
        except Exception:
            logger.warning("RP stat factor calculation failed for %s (%s)", recipient, source.event_id, exc_info=True)
            plans.append((result, None, None))
        else:
            plans.append((result, modified, cause))

    applied = []
    for result, modified, cause in plans:
        source, recipient = result["source"], result["recipient"]
        outcome = {"status": "failed", "changes": {}}
        try:
            if has_evaluation(source.event_id, recipient):
                outcome = {"status": "duplicate", "changes": {}}
            elif modified is not None:
                turning_points = {key for key, base in result["deltas"].items() if abs(base) >= 30}
                with reserve_chat_deltas(recipient, modified, turning_points=turning_points,
                                         game_hour=game_hour) as reservation:
                    with keyed_lock("character_profile", recipient):
                        if has_evaluation(source.event_id, recipient):
                            outcome = {"status": "duplicate", "changes": {}}
                        else:
                            for key, details in cause.items():
                                details["capped_delta"] = reservation.deltas.get(key, 0)
                            outcome = commit_evaluation(
                                source.event_id, recipient, reservation.deltas, game_ts=game_ts,
                                metadata={"source": "chat", "event_id": source.event_id, "cause": cause},
                            )
                            if outcome["status"] in {"applied", "unchanged"}:
                                reservation.commit()
        except Exception:
            logger.warning("RP stat application failed for %s (%s)", recipient, source.event_id, exc_info=True)
        applied.append({"event_id": source.event_id, "recipient": recipient, **outcome})
    return applied
