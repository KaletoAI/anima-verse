"""Strict Influence rule diagnostics and deterministic RP-only multipliers.

This module does not call an LLM or write character state. Callers supply the
apply snapshot; the ordinary modify-rule cache and factor semantics are separate.
"""
from __future__ import annotations

import math
from typing import Any

FACTOR_MIN = 0.1
FACTOR_MAX = 5.0
DIRECTIONS = ("increase", "decrease", "both")


def _issue(path: str, code: str, message: str) -> dict:
    return {"path": path, "code": code, "message": message}


def _number(value: Any) -> bool:
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def validate_influence_rule(rule: dict) -> list[dict]:
    """Return hard shape/syntax errors, not world-dependent missing references."""
    from app.core.activity_engine import validate_condition_expression
    if not isinstance(rule, dict):
        return [_issue("rule", "shape", "Rule must be an object.")]
    errors = []
    if rule.get("type") != "influence":
        return [_issue("type", "type", "Expected an influence rule.")]
    if not isinstance(rule.get("name"), str) or not rule["name"].strip():
        errors.append(_issue("name", "required", "Rule name is required."))
    if "id" in rule and (not isinstance(rule["id"], str) or not rule["id"].strip()):
        errors.append(_issue("id", "shape", "Rule ID must be a nonempty string."))
    for key in ("character", "target", "modify", "force_action"):
        if key in rule:
            errors.append(_issue(key, "conflicting_field", f"{key} is not allowed on influence rules."))
    for key in ("condition", "actor_condition"):
        expression = rule.get(key, "")
        if not isinstance(expression, str):
            errors.append(_issue(key, "shape", "Condition must be a string."))
        else:
            errors.extend(_issue(key, item.code, item.message)
                          for item in validate_condition_expression(expression))
    spec = rule.get("influence")
    if not isinstance(spec, dict):
        errors.append(_issue("influence", "shape", "Influence must be an object."))
    else:
        for key in spec.keys() - {"actor", "recipient", "stat", "direction", "factor"}:
            errors.append(_issue(f"influence.{key}", "unknown_field", "Unknown influence field."))
        for key in ("actor", "recipient", "stat"):
            if not isinstance(spec.get(key), str):
                errors.append(_issue(f"influence.{key}", "shape", f"{key} must be a string."))
        if isinstance(spec.get("stat"), str) and not spec["stat"].strip():
            errors.append(_issue("influence.stat", "required", "Stat key is required."))
        if spec.get("direction") not in DIRECTIONS:
            errors.append(_issue("influence.direction", "direction", "Choose increase, decrease or both."))
        value = spec.get("factor")
        if not _number(value) or not FACTOR_MIN <= value <= FACTOR_MAX:
            errors.append(_issue("influence.factor", "factor", "Factor must be a finite number from 0.1 to 5."))
    pairs = rule.get("pair_conditions", [])
    if not isinstance(pairs, list):
        errors.append(_issue("pair_conditions", "shape", "Pair conditions must be an array."))
    else:
        for index, pair in enumerate(pairs):
            path = f"pair_conditions.{index}"
            if not isinstance(pair, dict):
                errors.append(_issue(path, "shape", "Pair condition must be an object."))
                continue
            kind = pair.get("kind")
            if kind == "relationship":
                allowed = {"kind", "op", "value"}
                if pair.get("op") not in (">", "<", "="):
                    errors.append(_issue(f"{path}.op", "operator", "Choose >, < or =."))
                value = pair.get("value")
                if not _number(value) or not 0 <= value <= 100:
                    errors.append(_issue(f"{path}.value", "range", "Relationship strength must be a number from 0 to 100."))
            elif kind == "attraction":
                allowed = {"kind", "observer"}
                if pair.get("observer") not in ("actor", "recipient"):
                    errors.append(_issue(f"{path}.observer", "role", "Observer must be actor or recipient."))
            else:
                allowed = {"kind"}
                errors.append(_issue(f"{path}.kind", "kind", "Unknown pair condition kind."))
            for key in pair.keys() - allowed:
                errors.append(_issue(f"{path}.{key}", "unknown_field", "Unknown pair condition field."))
    return errors


def _template_stats(template: dict | None) -> dict[str, str]:
    return {field["key"]: str(field.get("label") or field["key"])
            for section in (template or {}).get("sections", [])
            for field in section.get("fields", [])
            if field.get("store") == "status_effects" and isinstance(field.get("key"), str)}


def _profile_stats(profile: dict) -> dict[str, str]:
    from app.models.character_template import get_template
    name = profile.get("template")
    return _template_stats(get_template(name)) if name else {}


def _catalog_stats() -> dict[str, str]:
    """Read the template catalog without re-reading character profiles."""
    from app.models.character_template import get_template, list_templates
    stats = {}
    for entry in list_templates():
        stats.update(_template_stats(get_template(entry["name"])))
    return stats


def influence_options() -> dict:
    """Describe dynamic authoring choices without a second character catalog."""
    from app.models.character import get_character_profile, list_available_characters
    from app.core.hooks import get_provider
    stats = _catalog_stats()
    # Nonselectable templates may still own existing characters.
    for name in list_available_characters(strict=True):
        stats.update(_profile_stats(get_character_profile(name, strict=True) or {}))
    attraction = get_provider("romantic_attraction") is not None
    return {"stats": [{"key": key, "label": stats[key]} for key in sorted(stats)],
            "pair_conditions": [
                {"kind": "relationship", "available": True, "reason": ""},
                {"kind": "attraction", "available": attraction,
                 "reason": "" if attraction else "Romantic attraction capability is unavailable."}],
            "directions": list(DIRECTIONS), "factor_min": FACTOR_MIN, "factor_max": FACTOR_MAX}


def _role_result(expression: str, name: str, profile: dict):
    from app.core.activity_engine import evaluate_condition_strict
    return evaluate_condition_strict(expression, name,
                                     profile.get("current_location") or "",
                                     profile.get("current_room") or "", profile=profile)


def influence_rule_status(rule: dict) -> dict:
    """Report unavailable current-world references, preserving their stored values.

    A false condition is not an availability problem. Wildcards are available if
    at least one current candidate supplies the references needed by that role.
    """
    from app.models.character import get_character_profile, list_available_characters
    from app.core.hooks import get_provider
    errors = validate_influence_rule(rule)
    if errors:
        return {"available": False, "reasons": errors}
    reasons = []
    try:
        names = set(list_available_characters(strict=True))
    except Exception as error:
        return {"available": False, "reasons": [
            _issue("influence", "read_error", f"Character references unavailable: {error}")]}
    spec = rule["influence"]
    for role, expression_key in (("actor", "actor_condition"), ("recipient", "condition")):
        bound = spec[role]
        candidates = [bound] if bound else sorted(names)
        if bound and bound not in names:
            reasons.append(_issue(f"influence.{role}", "missing_character", f"Character is unavailable: {bound}"))
            continue
        expression = rule.get(expression_key, "")
        available = not expression
        role_reasons = []
        stat_available = role != "recipient"
        for name in candidates:
            try:
                profile = get_character_profile(name, strict=True) or {}
            except Exception as error:
                reasons.append(_issue(f"influence.{role}", "read_error", f"Character profile unavailable: {error}"))
                continue
            if role == "recipient" and spec["stat"] in _profile_stats(profile):
                stat_available = True
            if expression:
                result = _role_result(expression, name, profile)
                available |= result.available
                if not result.available:
                    role_reasons.append(result.reason)
        if not available:
            reasons.append(_issue(expression_key, "unavailable_condition",
                                  "; ".join(dict.fromkeys(role_reasons)) or "No available character for this condition."))
        if not stat_available:
            # A fresh world can author a wildcard rule using a shipped template.
            try:
                known = _catalog_stats() if not bound else {}
            except Exception as error:
                reasons.append(_issue("influence.stat", "read_error", f"Stat catalog unavailable: {error}"))
                known = {}
            if spec["stat"] not in known:
                reasons.append(_issue("influence.stat", "missing_stat", f"Stat is unavailable: {spec['stat']}"))
    if any(pair["kind"] == "attraction" for pair in rule.get("pair_conditions", [])):
        if get_provider("romantic_attraction") is None:
            reasons.append(_issue("pair_conditions", "missing_capability", "Romantic attraction capability is unavailable."))
    return {"available": not reasons, "reasons": reasons}


def _pair_strength(actor: str, recipient: str) -> float:
    """Read the exact pair, preserving legitimate absence but not reader errors."""
    from app.models.relationship import get_relationship
    relationship = get_relationship(actor, recipient, strict=True)
    if relationship is None:
        return 0.0
    strength = relationship.get("strength")
    if not _number(strength) or not 0 <= strength <= 100:
        raise ValueError("Relationship strength is unavailable.")
    return strength


def _pairs_pass(pairs: list[dict], actor: str, recipient: str) -> bool:
    from app.core.hooks import get_provider
    strength = None
    for pair in pairs:
        if pair["kind"] == "relationship":
            if strength is None:
                strength = _pair_strength(actor, recipient)
            value = pair["value"]
            if not {">": strength > value, "<": strength < value, "=": strength == value}[pair["op"]]:
                return False
        else:
            provider = get_provider("romantic_attraction")
            if provider is None:
                return False
            observer, subject = ((recipient, actor) if pair["observer"] == "recipient" else (actor, recipient))
            # Only a real bool is the provider contract; error/None is not true.
            if provider(observer, subject) is not True:
                return False
    return True


def influence_factor(actor: str | None, recipient: str, stat: str, base_delta: int,
                     *, rules: list[dict], profiles: dict[str, dict]) -> dict:
    """Multiply matching unique rules, returning a stable trace and bounded product."""
    neutral = {"factor": 1.0, "rules": []}
    if not actor or actor == recipient or not base_delta:
        return neutral
    actor_profile, recipient_profile = profiles.get(actor), profiles.get(recipient)
    if not actor_profile or not recipient_profile:
        return neutral
    if stat not in _profile_stats(recipient_profile) or stat not in (recipient_profile.get("status_effects") or {}):
        return neutral
    direction = "increase" if base_delta > 0 else "decrease"
    matched = {}
    for rule in rules:
        if not isinstance(rule, dict) or rule.get("type") != "influence" or validate_influence_rule(rule):
            continue
        rid = rule.get("id")
        if not rid or rid in matched:
            continue
        spec = rule["influence"]
        if (spec["actor"] and spec["actor"] != actor or spec["recipient"] and spec["recipient"] != recipient
                or spec["stat"] != stat or spec["direction"] not in (direction, "both")):
            continue
        try:
            recipient_result = _role_result(rule.get("condition", ""), recipient, recipient_profile)
            actor_result = _role_result(rule.get("actor_condition", ""), actor, actor_profile)
            if not (recipient_result.available and recipient_result.passed and actor_result.available and actor_result.passed):
                continue
            if not _pairs_pass(rule.get("pair_conditions", []), actor, recipient):
                continue
        except Exception:
            # Local readers/providers may fail, but failure never grants a factor.
            continue
        matched[rid] = {"id": rid, "name": rule["name"], "factor": float(spec["factor"])}
    trace = [matched[key] for key in sorted(matched)]
    product = math.prod(entry["factor"] for entry in trace)
    if not math.isfinite(product) or product == 0:
        # Extremely large rule sets can overflow before opposing factors cancel.
        log_factor = math.fsum(math.log(entry["factor"]) for entry in trace)
        product = math.exp(max(math.log(FACTOR_MIN), min(math.log(FACTOR_MAX), log_factor)))
    factor = max(FACTOR_MIN, min(FACTOR_MAX, product))
    return {"factor": factor, "rules": trace}


def project_stat_metadata(metadata: dict, *, include_rule_details: bool = False) -> dict:
    """Copy effects metadata without exposing private rule/event provenance."""
    if not isinstance(metadata, dict):
        return {}
    projected = dict(metadata)
    if not include_rule_details:
        projected.pop("event_id", None)
    if "cause" not in metadata:
        return projected
    causes = {}
    raw_causes = metadata.get("cause")
    if isinstance(raw_causes, dict):
        for stat, cause in raw_causes.items():
            if not isinstance(stat, str) or not isinstance(cause, dict):
                continue
            actor = cause.get("actor")
            numeric_keys = ("base_delta", "modified_delta", "capped_delta", "factor")
            if actor is not None and not isinstance(actor, str):
                continue
            if not all(_number(cause.get(key)) for key in numeric_keys):
                continue
            entry = {"actor": actor, **{key: cause[key] for key in numeric_keys}}
            if include_rule_details and isinstance(cause.get("rules"), list):
                entry["rules"] = [
                    {"id": rule["id"], "name": rule["name"], "factor": rule["factor"]}
                    for rule in cause["rules"]
                    if isinstance(rule, dict) and isinstance(rule.get("id"), str)
                    and isinstance(rule.get("name"), str) and _number(rule.get("factor"))
                ]
            causes[stat] = entry
    projected["cause"] = causes
    return projected
