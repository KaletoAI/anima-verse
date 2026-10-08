"""Canonical base joint identity shared by declarations and validation."""
import json
import re
from pathlib import Path


def norm_bone_name(name: str) -> str:
    """Match scene-render clipRetarget.normBoneName exactly."""
    return re.sub(r"^mixamorig:?", "", name, flags=re.I).replace(":", "").lower()


BASE_JOINT_NAMES = tuple(json.loads(
    (Path(__file__).resolve().parents[2] / "shared/models/rig/joints.json")
    .read_text(encoding="utf-8")))
BASE_JOINT_KEYS = frozenset(norm_bone_name(n) for n in BASE_JOINT_NAMES)
