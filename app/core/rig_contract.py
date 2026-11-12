"""Canonical base joint identity shared by declarations and validation.

Besides the base joints and the declared extension groups, a skin may carry HairDeck spring-chain joints
(plan 2026-11-12-hairdeck-spring-chains): ``HairGen_c<CC>_<KK>`` (segment bones) plus a leaf ``HairGen_c<CC>_end``
per chain. They are declared by RULE, not by a list: ``HAIR_CHAIN_JOINT_RE`` names them and ``hair_chain_parent``
gives each one's parent (``_00`` under ``mixamorig:Head``, ``_KK`` under ``_KK-1``, ``_end`` under the chain's
highest ``_KK``).
"""
import json
import re
from pathlib import Path
from typing import Iterable, Optional


def norm_bone_name(name: str) -> str:
    """Match scene-render clipRetarget.normBoneName exactly."""
    return re.sub(r"^mixamorig:?", "", name, flags=re.I).replace(":", "").lower()


BASE_JOINT_NAMES = tuple(json.loads(
    (Path(__file__).resolve().parents[2] / "shared/models/rig/joints.json")
    .read_text(encoding="utf-8")))
BASE_JOINT_KEYS = frozenset(norm_bone_name(n) for n in BASE_JOINT_NAMES)

#: A HairDeck spring-chain joint: chain ``CC``, segment bone ``KK`` or the chain's leaf ``end``.
HAIR_CHAIN_JOINT_RE = re.compile(r"^HairGen_c(\d{2})_(\d{2}|end)$")
#: The parent of every chain's first joint ``_00``.
HAIR_CHAIN_ROOT_PARENT = "mixamorig:Head"


def hair_chain_parent(name: str, present: Iterable[str]) -> Optional[str]:
    """The parent of the hair-chain joint ``name``: ``_00`` -> ``mixamorig:Head``; ``_KK`` -> ``_KK-1``; ``_end``
    -> the highest ``_KK`` of the same chain in ``present`` (the skin's joint names), None when there is none.
    None for a name that is no hair-chain joint."""
    m = HAIR_CHAIN_JOINT_RE.match(str(name))
    if not m:
        return None
    chain, seg = m.group(1), m.group(2)
    if seg == "00":
        return HAIR_CHAIN_ROOT_PARENT
    if seg != "end":
        return f"HairGen_c{chain}_{int(seg) - 1:02d}"
    best = -1
    for other in present:
        o = HAIR_CHAIN_JOINT_RE.match(str(other))
        if o and o.group(1) == chain and o.group(2) != "end":
            best = max(best, int(o.group(2)))
    return f"HairGen_c{chain}_{best:02d}" if best >= 0 else None
