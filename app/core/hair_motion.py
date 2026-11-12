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
- Swing and Stiffness are profile keys: ``hair_swing`` (``"on"`` / ``"off"``, ``""`` = ``HAIR_SWING_DEFAULT``) and
  ``hair_stiffness`` (``""`` = 1.0, else a factor within ``STIFFNESS_LIMITS``). Stiffness changes only the motion.
  Swing is a FIT input (Ruling H11, replacing H7's "motion only"): with Swing off the fit writes today's skin
  (``garment_fit.hair_weights``' Head -> Neck -> Spine2 rows, no chain joint, no binding) and the payload has no
  hair group; with Swing on the chain-bound cards ride their chain joints. ``garment_store.garment_fsig`` holds
  Swing only when it is on, so a fit made with Swing off keeps the fingerprint it had before Swing was a fit input
  (the boot refit sweep refits it under that fingerprint), and toggling it refits on the CPU
  (``routes/characters.py`` ``/hair/motion``).
- A chain of a Swing-on fit carries ``anchor_blend`` (``garment_hairdeck._anchor_blend``: per joint the Head /
  Neck / Spine2 row that reproduces today's skin over the chain's vertices): the client puts each joint at that
  blend of the three bones and adds its swing scaled to the row's Head share (``secondaryMotion.ts``, HAIR CHAINS),
  so at rest the hair is where today's skin puts it. The rigid joints below keep their rows (carried, no swing).
- RIGID joints (Ruling H10): a chain joint whose rest (bind) position lies inside the head collision capsule rides
  the head and is left out of its group. The fit records ``rigid: []``; the served summary fills it at payload time
  from the joints stored in the fit GLB (``rigid_joints``: the same head capsule ``collision.fit_capsules`` gives
  the client, with the character's region scales), so no re-fit is needed.
"""
from __future__ import annotations

import logging
import math
import os
import threading
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

logger = logging.getLogger(__name__)

PROFILE_SWING = "hair_swing"
PROFILE_STIFFNESS = "hair_stiffness"
#: The stored values of ``PROFILE_SWING``; anything else (``""``) means ``HAIR_SWING_DEFAULT``.
SWING_ON = "on"
SWING_OFF = "off"
#: Swing of a character that never chose (Ruling H11, 2026-11-12): OFF — the fit is then today's hair, byte for
#: byte in its skin. It flips to True only when the acceptance (plan 2026-11-12-hairdeck-spring-chains, Task 8)
#: shows the Swing-on hair's penetration at most today's + 1 percentage point in the worst pose
#: (``scripts/check_garment_collision.mjs --motion``, hair ``excess``). Flipping it changes the fit fingerprint
#: of every character on the default (``garment_store.garment_fsig``): their hair is refitted at the next run.
HAIR_SWING_DEFAULT = False
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

#: Profile keys whose value is part of the served-chains cache key (with the worn hair id and the head capsule
#: scale): a change of the character's hair invalidates the cached summary even when ``garments/`` is unchanged.
HAIR_PROFILE_KEYS = ("hair_method", "hair_forward_m", "hair_tilt_deg", "hair_width_scale", PROFILE_SWING)

# character -> (cache key, chains summary or None)
_SERVED: Dict[str, Tuple[Tuple[Any, ...], Optional[Dict[str, Any]]]] = {}
_SERVED_LOCK = threading.Lock()
# (fit GLB path, st_mtime_ns, st_size, head scale) -> rigid joint names
_RIGID: Dict[Tuple[str, int, int, float], FrozenSet[str]] = {}
_RIGID_LOCK = threading.Lock()


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


def swing_on(profile: Optional[Dict[str, Any]]) -> bool:
    """Swing of the profile key ``hair_swing``: ``"on"`` True, ``"off"`` False, anything else
    ``HAIR_SWING_DEFAULT``. A fit input (Ruling H11)."""
    stored = str((profile or {}).get(PROFILE_SWING) or "")
    return True if stored == SWING_ON else False if stored == SWING_OFF else HAIR_SWING_DEFAULT


def settings(profile: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """``{"swing": bool, "stiffness": float}`` of the profile keys ``hair_swing`` / ``hair_stiffness``. Swing:
    ``swing_on``; a stiffness that is empty, no number or beyond ``STIFFNESS_LIMITS`` counts as
    ``DEFAULT_STIFFNESS``."""
    profile = profile or {}
    try:
        stiffness = _stiffness_value(profile.get(PROFILE_STIFFNESS))
    except ValueError:
        stiffness = None
    return {"swing": swing_on(profile), "stiffness": DEFAULT_STIFFNESS if stiffness is None else stiffness}


def set_hair_motion(character_name: str, swing: Any, stiffness: Any) -> bool:
    """Store Swing (a bool; stored as ``"on"`` / ``"off"`` — an explicit choice survives a change of
    ``HAIR_SWING_DEFAULT``) and the Stiffness factor (a number within ``STIFFNESS_LIMITS``; None, ``""`` or 1.0 =
    the default, stored as ``""``) in ONE read-modify-write under the profile lock. ValueError for a non-bool swing
    or an invalid stiffness — nothing is stored then. The save result; True without a save when unchanged.
    Stiffness changes only the motion payload; Swing is a fit input (the caller starts the CPU refit)."""
    from app.core.keyed_lock import keyed_lock
    from app.models.character import get_character_profile, save_character_profile
    if not isinstance(swing, bool):
        raise ValueError("hair swing must be true or false")
    value = _stiffness_value(stiffness)
    wanted = {PROFILE_SWING: SWING_ON if swing else SWING_OFF,
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
    return round(max(HAIR_FREQ_MIN_HZ, min(HAIR_FREQ_MAX_HZ, freq)), 3), round(HAIR_ZETA, 3)


def rigid_joints(fit_glb: bytes, *, scales: Optional[Dict[str, Any]] = None) -> FrozenSet[str]:
    """The hair-chain joints (``rig_contract.HAIR_CHAIN_JOINT_RE``, never an ``_end`` leaf) of a fit GLB whose REST
    position lies inside the body's head collision capsule (Ruling H10). Rest position = the joint's bind position
    (inverse of its inverse bind matrix — the space the capsules are fitted in); the capsule is
    ``collision.fit_capsules(fit_glb, scales=scales)``'s ``head`` (the body only: ``glb_mesh.body_arrays`` skips
    the grafted hair), i.e. the capsule the client collides with. Inside = closer to its segment than its radius.
    Empty without a head capsule or without chain joints. ValueError for a file without a skin."""
    import numpy as np
    from app.core import collision, glb_mesh
    from app.core.rig_contract import HAIR_CHAIN_JOINT_RE, norm_bone_name
    parsed = glb_mesh._parse(fit_glb, "Model")
    gltf = parsed["gltf"]
    skins, nodes = gltf.get("skins") or [], gltf.get("nodes") or []
    if not skins or "inverseBindMatrices" not in skins[0]:
        raise ValueError("The fit has no skin with inverse bind matrices")
    names = [str(nodes[j].get("name") or "") for j in skins[0].get("joints") or []]
    chain = [i for i, name in enumerate(names)
             if (m := HAIR_CHAIN_JOINT_RE.match(name)) and m.group(2) != "end"]
    if not chain:
        return frozenset()
    head = next((c for c in collision.fit_capsules(fit_glb, scales=scales)["capsules"] if c.get("id") == "head"),
                None)
    if head is None:
        return frozenset()
    positions = np.linalg.inv(collision._matrices(parsed, skins[0]["inverseBindMatrices"]))[:, :3, 3]
    index = {norm_bone_name(n): i for i, n in reversed(list(enumerate(names)))}
    a = positions[index[norm_bone_name(head["a"])]]
    b = np.asarray(head["b_pos"], np.float64) if head.get("b_pos") else positions[index[norm_bone_name(head["b"])]]
    points = positions[chain]
    ab = b - a
    t = np.clip(((points - a) @ ab) / float(ab @ ab), 0.0, 1.0) if float(ab @ ab) > 1e-12 else np.zeros(len(chain))
    distance = np.linalg.norm(points - (a + t[:, None] * ab), axis=1)
    return frozenset(names[i] for i, d in zip(chain, distance) if d < float(head["r"]))


def _rigid_of_fit(path: Optional[Path], head_scale: float) -> Optional[FrozenSet[str]]:
    """``rigid_joints`` of the fit GLB at ``path`` with the head capsule scaled by ``head_scale`` (every other
    region at its default — only the head capsule is read), cached per (path, mtime, size, scale). None when the
    file is missing or unreadable (logged once per file identity): the caller keeps the recorded list."""
    if path is None:
        return None
    try:
        stat = os.stat(path)
    except OSError:
        return None
    key = (str(path), stat.st_mtime_ns, stat.st_size, float(head_scale))
    with _RIGID_LOCK:
        if key in _RIGID:
            return _RIGID[key]
    from app.core import collision
    try:
        rigid: Optional[FrozenSet[str]] = rigid_joints(Path(path).read_bytes(),
                                                       scales={**collision.default_scales(), "head": head_scale})
    except Exception as exc:  # noqa: BLE001 — a fit we cannot read keeps its recorded rigid list
        logger.warning("Hair chains: rigid joints of %s not computed: %s", Path(path).name, exc)
        rigid = None
    with _RIGID_LOCK:
        if len(_RIGID) > 256:
            _RIGID.clear()
        _RIGID[key] = rigid
    return rigid


def _head_scale(character_name: str, profile: Optional[Dict[str, Any]]) -> float:
    from app.core import collision
    return float(collision.character_scales(character_name, profile=profile or {}).get("head", 1.0))


def with_rigid(chains: Optional[Dict[str, Any]], rigid: Optional[FrozenSet[str]]) -> Optional[Dict[str, Any]]:
    """A copy of a chain summary whose every chain's ``rigid`` is its recorded list plus the names of ``rigid``
    among its ``bones`` (chain order kept, never an ``_end`` leaf). ``chains`` itself when ``rigid`` is None or
    ``chains`` no dict."""
    from app.core.rig_contract import HAIR_CHAIN_JOINT_RE
    if rigid is None or not isinstance(chains, dict):
        return chains
    out = dict(chains)
    rows: List[Any] = []
    for chain in chains.get("chains") or []:
        if not isinstance(chain, dict):
            rows.append(chain)
            continue
        recorded = [str(b) for b in chain.get("rigid") or []]
        added = [str(b) for b in chain.get("bones") or [] if str(b) in rigid and str(b) not in recorded
                 and (m := HAIR_CHAIN_JOINT_RE.match(str(b))) and m.group(2) != "end"]
        rows.append({**chain, "rigid": recorded + added})
    out["chains"] = rows
    return out


def served_chains(character_name: str, profile: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """``report.chains`` of the newest accepted HairDeck fit of the worn hair (``garments._newest_fit``), None for
    the hair method ``body``, without worn hair, without such a fit or for a fit from before the spring chains.
    With Swing off ``motion_groups`` emits nothing whatever this fit is; a fit made with Swing off has no weighted
    joint, so it gives no group either.

    Cached per (character, ``garments/`` directory ``st_mtime_ns``, worn item id): a fit or record write replaces a
    file in that directory, so an unchanged directory costs one ``stat`` per worldmap poll. The item id of the key
    is the profile's raw hair slot entry; whether it is the character's own hair (``garment_hair.worn_hair_id``,
    an inventory read) is resolved on a miss only. The key also holds the profile's hair (``HAIR_PROFILE_KEYS``)
    and the head capsule scale, so a change of either is a miss.

    Each chain's ``rigid`` is filled from the fit GLB (``rigid_joints``, Ruling H10)."""
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
    head_scale = _head_scale(character_name, profile)
    key = (character_name, stamp, str(raw), tuple(str((profile or {}).get(k, "")) for k in HAIR_PROFILE_KEYS),
           head_scale)
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
        if isinstance(found, dict):
            chains = with_rigid(found, _rigid_of_fit(newest[0], head_scale))
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
    chain without such a bone is left out unless it has an ``anchor_blend`` (then its group has ``bones`` [] and
    only carries the rows of its rigid joints); a malformed chain is left out. Values: every ``MOTION_FIELDS`` default of ``RigSpec``,
    then ``freq_zeta(stiffness × settings["stiffness"])``, ``HAIR_GRAVITY``, ``HAIR_MAX_DEG``, ``HAIR_SAG_MAX_DEG``;
    ``scale_axis`` the default, ``rigid_tail`` 0, ``rest_deg`` 0, ``gravity_scale`` the profile's (the caller's),
    ``hair`` True, and the chain's ``anchor_blend`` when the fit recorded one — ``{bone: {body joint: share}}`` of
    the chain's weighted joints, its rigid ones included (today's skin row at each bone, ``garment_hairdeck._anchor_blend``) with ``anchor_from`` =
    ``hair_chains.HEAD_PARENT`` (the bone every chain hangs from: its share of a row is the share of the swing the
    client shows at that bone).
    ``{}`` when Swing is off or without chains; a fit made with Swing off has no weighted joint, so no group."""
    from app.core.hair_chains import HEAD_PARENT
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
            raw_blend = chain.get("anchor_blend") or {}
            blend = {str(bone): {str(k): float(v) for k, v in row.items()
                                 if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
                                 and v > 0}
                     for bone, row in raw_blend.items() if isinstance(row, dict)}
        except (TypeError, ValueError, KeyError, AttributeError):
            continue
        if index < 0 or not math.isfinite(stiffness):
            continue
        bones = []
        for bone in weighted:
            match = HAIR_CHAIN_JOINT_RE.match(bone)
            if match and int(match.group(1)) == index and match.group(2) != "end" and bone not in rigid:
                bones.append(bone)
        # every joint of the chain but the leaf: a carried (rigid) one rides today's skin without a swing
        joints = {b for b in weighted if (m := HAIR_CHAIN_JOINT_RE.match(b)) and int(m.group(1)) == index
                  and m.group(2) != "end"}
        blend = {bone: row for bone, row in blend.items() if bone in joints and row}
        if not bones and not blend:
            continue
        if defaults is None:
            defaults = _defaults()
        freq, zeta = freq_zeta(stiffness * factor)
        out[GROUP_ID.format(index=index)] = {
            "bones": bones, **defaults, "freq_hz": freq, "zeta": zeta, "gravity": HAIR_GRAVITY,
            "max_deg": HAIR_MAX_DEG, "sag_max_deg": HAIR_SAG_MAX_DEG, "scale_axis": "centroid", "rigid_tail": 0,
            "rest_deg": 0.0, "gravity_scale": float(gravity_scale), "hair": True,
            **({"anchor_blend": blend, "anchor_from": HEAD_PARENT} if blend else {})}
    return out


def panel(character_name: str, profile: Dict[str, Any], newest: Optional[Dict[str, Any]],
          path: Optional[Path] = None) -> Dict[str, Any]:
    """The Hair tab's spring-chain block for the newest HairDeck fit record ``newest`` (None without a fit) stored
    at ``path`` (its GLB; its joints in the head capsule do not count as swinging links, as in ``served_chains``):
    ``{count, links, swing, stiffness, limits, fitted}`` — ``count`` the bound chains of the fit (None when
    ``fitted`` is False: no fit, or one from before the spring chains), ``links`` how many joints swing (the motion
    groups' bones, counted with Swing on), ``swing`` / ``stiffness`` the stored settings, ``limits`` the
    Stiffness bounds."""
    current = settings(profile)
    chains = ((newest or {}).get("report") or {}).get("chains")
    fitted = isinstance(chains, dict)
    if fitted and path is not None:
        chains = with_rigid(chains, _rigid_of_fit(path, _head_scale(character_name, profile)))
    groups = motion_groups(chains, {**current, "swing": True}) if fitted else {}
    count = chains.get("count") if fitted else None
    return {"count": int(count) if isinstance(count, (int, float)) and not isinstance(count, bool) else
            (None if not fitted else 0),
            "links": sum(len(group["bones"]) for group in groups.values()),
            "swing": current["swing"], "stiffness": current["stiffness"], "limits": list(STIFFNESS_LIMITS),
            "fitted": fitted}
