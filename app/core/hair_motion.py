"""Hair chains of the character as a core motion source (plan docs/superpowers/plans/2026-11-12-hairdeck-spring-chains.md,
Task 5).

A HairDeck fit binds the hair cards to HairDeck's spring chains and records them in its ``report.chains``
(``garment_hairdeck._bind_chains``: per chain ``index``, ``bones``, ``weighted``, ``stiffness``, ``rigid``). This
module turns that summary of the SERVED hair into motion groups for ``extension_rig.motion_payload`` — core hair,
not a skill package (R1) — one group ``hair_c<CC>`` per chain, solved by the client's existing spring solver
(``packages/scene-render/src/secondaryMotion.ts``).

- The group's bones are the chain's weighted joints minus the rigid ones, never the unweighted ``_end`` leaf
  (Ruling H4: the solver skips a whole group with an unweighted bone).
- HairDeck's per-chain ``stiffness`` (0.2–0.75) times the character's Stiffness factor maps linearly to the spring
  frequency (``HAIR_FREQ_PER_STIFFNESS`` Hz per unit, measured in the spike, Ruling H1a), clamped to
  ``HAIR_FREQ_MIN_HZ``..``HAIR_FREQ_MAX_HZ``; the damping ratio is a constant ``HAIR_ZETA``.
- Swing and Stiffness are profile keys (Ruling H7): ``hair_swing`` (``""`` = on, ``"off"``) and ``hair_stiffness``
  (``""`` = 1.0, else a factor within ``STIFFNESS_LIMITS``). They change only the motion, never the fit.
"""
from __future__ import annotations

import math
import os
import threading
from typing import Any, Dict, Optional, Tuple

PROFILE_SWING = "hair_swing"
PROFILE_STIFFNESS = "hair_stiffness"
#: The stored value of ``PROFILE_SWING`` that turns the swing off; anything else is on.
SWING_OFF = "off"
#: The bounds of the Stiffness factor (× HairDeck's per-chain stiffness).
STIFFNESS_LIMITS: Tuple[float, float] = (0.5, 2.0)
DEFAULT_STIFFNESS = 1.0

#: Spring frequency per unit of effective stiffness (Ruling H1a: AR(2) natural frequency 1.01/1.64/2.66 Hz at
#: stiffness 0.2/0.4/0.75 in the spike).
HAIR_FREQ_PER_STIFFNESS = 3.7
HAIR_FREQ_MIN_HZ = 0.8
HAIR_FREQ_MAX_HZ = 6.0
#: Damping ratio of every hair chain (the spike confirmed ≈ 0.5).
HAIR_ZETA = 0.5
#: Hair is light: a small gravity, a swing cap and a small static droop.
HAIR_GRAVITY = 0.15
HAIR_MAX_DEG = 35.0
HAIR_SAG_MAX_DEG = 10.0

#: Motion group id of one chain (``CC`` = HairDeck's chain index, as in the joint names).
GROUP_ID = "hair_c{index:02d}"

# character -> ((character, garments/ st_mtime_ns, item id), chains summary or None)
_SERVED: Dict[str, Tuple[Tuple[str, int, str], Optional[Dict[str, Any]]]] = {}
_SERVED_LOCK = threading.Lock()


def _stiffness_value(raw: Any) -> Optional[float]:
    """A Stiffness factor as float, None for empty. ValueError for a non-number or one beyond ``STIFFNESS_LIMITS``."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    if isinstance(raw, bool):
        raise ValueError("hair stiffness must be a number or empty")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise ValueError("hair stiffness must be a number or empty") from None
    lo, hi = STIFFNESS_LIMITS
    if not math.isfinite(value) or not lo <= value <= hi:
        raise ValueError(f"hair stiffness must be within {lo:g}..{hi:g}")
    return value


def settings(profile: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """``{"swing": bool, "stiffness": float}`` of the profile keys ``hair_swing`` / ``hair_stiffness``. Swing is on
    unless the stored value is ``"off"``; a stiffness that is empty, no number or beyond ``STIFFNESS_LIMITS`` counts
    as ``DEFAULT_STIFFNESS``."""
    profile = profile or {}
    try:
        stiffness = _stiffness_value(profile.get(PROFILE_STIFFNESS))
    except ValueError:
        stiffness = None
    return {"swing": str(profile.get(PROFILE_SWING) or "") != SWING_OFF,
            "stiffness": DEFAULT_STIFFNESS if stiffness is None else stiffness}


def set_hair_motion(character_name: str, swing: Any, stiffness: Any) -> bool:
    """Store Swing (a bool; stored as ``""`` = on / ``"off"``) and the Stiffness factor (a number within
    ``STIFFNESS_LIMITS``; None, ``""`` or 1.0 = the default, stored as ``""``) in ONE read-modify-write under the
    profile lock. ValueError for a non-bool swing or an invalid stiffness — nothing is stored then. The save
    result; True without a save when unchanged. Only the motion payload changes: nothing is re-fitted."""
    from app.core.keyed_lock import keyed_lock
    from app.models.character import get_character_profile, save_character_profile
    if not isinstance(swing, bool):
        raise ValueError("hair swing must be true or false")
    value = _stiffness_value(stiffness)
    wanted = {PROFILE_SWING: "" if swing else SWING_OFF,
              PROFILE_STIFFNESS: "" if value is None or value == DEFAULT_STIFFNESS else value}
    with keyed_lock("character_profile", character_name):
        profile = get_character_profile(character_name) or {}
        changed = False
        for key, stored in wanted.items():
            if profile.get(key, "") != stored:
                profile[key] = stored
                changed = True
        return bool(save_character_profile(character_name, profile)) if changed else True


def freq_zeta(stiffness: float) -> Tuple[float, float]:
    """``(freq_hz, zeta)`` of an effective stiffness (HairDeck's per-chain value × the Stiffness factor):
    ``HAIR_FREQ_PER_STIFFNESS`` × stiffness clamped to ``HAIR_FREQ_MIN_HZ``..``HAIR_FREQ_MAX_HZ``, and
    ``HAIR_ZETA``."""
    freq = HAIR_FREQ_PER_STIFFNESS * float(stiffness)
    return max(HAIR_FREQ_MIN_HZ, min(HAIR_FREQ_MAX_HZ, freq)), HAIR_ZETA


def served_chains(character_name: str, profile: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """``report.chains`` of the newest accepted HairDeck fit of the worn hair (``garments._newest_fit``), None for
    the hair method ``body``, without worn hair, without such a fit or for a fit from before the spring chains.

    Cached per (character, ``garments/`` directory ``st_mtime_ns``, worn item id): a fit or record write replaces a
    file in that directory, so an unchanged directory costs one ``stat`` per worldmap poll. The item id of the key
    is the profile's raw hair slot entry; whether it is the character's own hair (``garment_hair.worn_hair_id``,
    an inventory read) is resolved on a miss only."""
    from app.core import garment_hair
    from app.core import garment_store as gs
    if garment_hair.hair_method(character_name, profile=profile) == garment_hair.BODY_METHOD:
        return None
    worn = (profile or {}).get("equipped_mesh_pieces")
    raw = worn.get(garment_hair.HAIR_KIND) if isinstance(worn, dict) else None
    if not raw:
        return None
    try:
        stamp = os.stat(gs._root(character_name)).st_mtime_ns  # a read path never creates garments/
    except OSError:
        return None
    key = (character_name, stamp, str(raw))
    with _SERVED_LOCK:
        hit = _SERVED.get(character_name)
    if hit is not None and hit[0] == key:
        return hit[1]
    from app.core import garments
    chains: Optional[Dict[str, Any]] = None
    item_id = garment_hair.worn_hair_id(character_name, profile)
    if item_id:
        newest = garments._newest_fit(character_name, item_id, gs.HAIRDECK)
        found = ((newest[1].get("report") or {}).get("chains")) if newest else None
        chains = found if isinstance(found, dict) else None
    with _SERVED_LOCK:
        _SERVED[character_name] = (key, chains)
    return chains


def _defaults() -> Dict[str, Any]:
    """Every ``MOTION_FIELDS`` value of a ``RigSpec`` without declarations (``flatten_floor`` resolved to
    ``squash[0]`` as ``extension_rig.declared_motion_groups`` does)."""
    from app.core.extension_rig import MOTION_FIELDS
    from app.plugins.registry import RigSpec
    spec = RigSpec(id="hair", op="hair", chains=[])
    out = {key: getattr(spec, key) for key in MOTION_FIELDS}
    if out["flatten_floor"] is None:
        out["flatten_floor"] = out["squash"][0]
    return out


def motion_groups(chains: Optional[Dict[str, Any]], settings: Dict[str, Any], *,
                  gravity_scale: float = 1.0) -> Dict[str, Dict[str, Any]]:
    """The motion groups of a chain summary (``served_chains``), pure. One group ``hair_c<CC>`` per chain whose
    ``bones`` are its ``weighted`` joints minus its ``rigid`` ones, never the ``_end`` leaf, in chain order; a
    chain without such a bone (or malformed) is left out. Values: every ``MOTION_FIELDS`` default of ``RigSpec``,
    then ``freq_zeta(stiffness × settings["stiffness"])``, ``HAIR_GRAVITY``, ``HAIR_MAX_DEG``, ``HAIR_SAG_MAX_DEG``;
    ``scale_axis`` the default, ``rigid_tail`` 0, ``rest_deg`` 0, ``gravity_scale`` the profile's (the caller's),
    ``hair`` True. ``{}`` when Swing is off or without chains."""
    from app.core.rig_contract import HAIR_CHAIN_JOINT_RE
    if not settings.get("swing") or not isinstance(chains, dict):
        return {}
    factor = float(settings.get("stiffness", DEFAULT_STIFFNESS))
    defaults = None
    out: Dict[str, Dict[str, Any]] = {}
    for chain in chains.get("chains") or []:
        try:
            index = int(chain["index"])
            stiffness = float(chain["stiffness"])
            weighted = [str(b) for b in chain.get("weighted") or []]
            rigid = {str(b) for b in chain.get("rigid") or []}
        except (TypeError, ValueError, KeyError, AttributeError):
            continue
        if index < 0 or not math.isfinite(stiffness):
            continue
        bones = []
        for bone in weighted:
            match = HAIR_CHAIN_JOINT_RE.match(bone)
            if match and int(match.group(1)) == index and match.group(2) != "end" and bone not in rigid:
                bones.append(bone)
        if not bones:
            continue
        if defaults is None:
            defaults = _defaults()
        freq, zeta = freq_zeta(stiffness * factor)
        out[GROUP_ID.format(index=index)] = {
            "bones": bones, **defaults, "freq_hz": freq, "zeta": zeta, "gravity": HAIR_GRAVITY,
            "max_deg": HAIR_MAX_DEG, "sag_max_deg": HAIR_SAG_MAX_DEG, "scale_axis": "centroid", "rigid_tail": 0,
            "rest_deg": 0.0, "gravity_scale": float(gravity_scale), "hair": True}
    return out


def panel(character_name: str, profile: Dict[str, Any], newest: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """The Hair tab's spring-chain block for the newest HairDeck fit record ``newest`` (None without a fit):
    ``{count, links, swing, stiffness, limits, fitted}`` — ``count`` the bound chains of the fit (None when
    ``fitted`` is False: no fit, or one from before the spring chains), ``links`` how many joints swing (the motion
    groups' bones, counted with Swing on), ``swing`` / ``stiffness`` the stored settings, ``limits`` the
    Stiffness bounds."""
    current = settings(profile)
    chains = ((newest or {}).get("report") or {}).get("chains")
    fitted = isinstance(chains, dict)
    groups = motion_groups(chains, {**current, "swing": True}) if fitted else {}
    count = chains.get("count") if fitted else None
    return {"count": int(count) if isinstance(count, (int, float)) and not isinstance(count, bool) else
            (None if not fitted else 0),
            "links": sum(len(group["bones"]) for group in groups.values()),
            "swing": current["swing"], "stiffness": current["stiffness"], "limits": list(STIFFNESS_LIMITS),
            "fitted": fitted}
