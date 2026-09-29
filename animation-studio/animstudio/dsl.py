"""The authoring language: one module per animation defines ``ANIM``.

Values are degrees per DOF (see rig.DRIVES) plus ``hips_drop_cm``. A Key
states only what CHANGES: every key is laid over ``base`` and all earlier
keys (carry-forward). ``loop=True`` closes the cycle itself — the first key
is repeated at t = duration, so keys must lie in [0, duration).
"""
import math
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from animstudio import StudioError
from animstudio import rig

GROUPS = ("stand", "seat", "ground", "lie")
#: Seconds a HandTarget fades in/out at each INNER edge of its span.
FADE_S = 0.15
EASES: Dict[str, Callable[[float], float]] = {
    "linear": lambda u: u,
    "in": lambda u: u * u,
    "out": lambda u: 1.0 - (1.0 - u) ** 2,
    "in_out": lambda u: u * u * (3.0 - 2.0 * u),
}


class Pose(dict):
    """DOF name -> degrees (``hips_drop_cm`` in cm)."""

    def __init__(self, **values: float):
        super().__init__({k: float(v) for k, v in values.items()})

    def __or__(self, other: "Pose") -> "Pose":
        return Pose(**{**self, **other})


@dataclass(frozen=True)
class Key:
    t: float
    pose: Pose
    ease: str = "in_out"


@dataclass(frozen=True)
class Oscillator:
    """Adds ``amp · sin(2π (t / period_s + phase))`` degrees to one DOF."""
    dof: str
    amp: float
    period_s: float
    phase: float = 0.0


def Breath(amp: float = 1.0, period_s: float = 4.0) -> List[Oscillator]:
    """Chest rise: the spine straightens, the shoulders lift a little."""
    return [Oscillator("spine_flex", -amp, period_s),
            Oscillator("l_clav_raise", amp * 0.5, period_s),
            Oscillator("r_clav_raise", amp * 0.5, period_s)]


@dataclass(frozen=True)
class HandTarget:
    """The hand's head (wrist) reaches ``at`` — metres in clip space (X the
    figure's left, Y up, Z front, origin on the floor at the armature
    origin) — during ``span`` (seconds, None = the whole clip), with a
    FADE_S (0.15 s) fade at each inner edge of the span. ``pole`` is the
    direction the elbow points (default down and back). ``validate`` keeps
    the span inside [0, duration], long enough for its fades and, on a
    loop, touching both ends or neither."""
    side: str
    at: Tuple[float, float, float]
    span: Optional[Tuple[float, float]] = None
    pole: Tuple[float, float, float] = (0.0, -1.0, -1.0)


@dataclass(frozen=True)
class FeetPlanted:
    """The ankles stay where frame 0 puts them in XZ, at the rest ankle
    height; the knees bend (forward) to make up for ``hips_drop_cm`` and
    body motion. The foot keeps its world rotation."""
    sides: Tuple[str, ...] = ("l", "r")


@dataclass(frozen=True)
class Catalog:
    key: str
    group: str
    prompt: str
    synonyms: Sequence[str] = ()


@dataclass
class Animation:
    kind: str
    duration_s: float
    loop: bool
    catalog: Catalog
    base: Pose = field(default_factory=Pose)
    keys: List[Key] = field(default_factory=list)
    layers: List = field(default_factory=list)
    ik: List = field(default_factory=list)
    fps: int = 30
    #: cm the finished clip is lifted after the floor normalisation. A joint
    #: skeleton has no body thickness: run_takes puts the lowest JOINT on the
    #: floor, so a lying body ends with its hips ~4 cm up where the lie place
    #: type expects ~20 (root_drop is calibrated on the shipped clips). For
    #: group "lie" set ~16; everything else keeps 0.
    lift_cm: float = 0.0


def _layers(anim: Animation) -> List[Oscillator]:
    out: List[Oscillator] = []
    for layer in anim.layers:
        out.extend(layer if isinstance(layer, (list, tuple)) else [layer])
    return out


def _known(dof: str) -> bool:
    return dof in rig.DRIVES or dof == "hips_drop_cm"


def validate(anim: Animation) -> None:
    """Raises StudioError naming the first problem."""
    if anim.fps != 30:
        raise StudioError("fps must be 30 (the library rate)")
    if anim.duration_s <= 0:
        raise StudioError("duration_s must be > 0")
    frames = anim.duration_s * anim.fps
    if anim.loop and abs(frames - round(frames)) > 1e-9:
        raise StudioError(f"loop: duration_s * fps = {frames:g} is no whole frame count "
                          "- the last frame would miss the closing key")
    if anim.catalog.group not in GROUPS:
        raise StudioError(f"catalog.group must be one of {GROUPS}")
    if "/" in anim.catalog.key:
        raise StudioError("catalog.key must not contain '/'")
    if not 0.0 <= anim.lift_cm <= 40.0:
        raise StudioError("lift_cm must be within 0..40")
    last = -1.0
    for k in anim.keys:
        if k.ease not in EASES:
            raise StudioError(f"key at {k.t}: unknown ease {k.ease!r}")
        if k.t <= last:
            raise StudioError(f"key times must increase (at {k.t})")
        if k.t < 0 or k.t > anim.duration_s or (anim.loop and k.t >= anim.duration_s):
            raise StudioError(f"key at {k.t} outside [0, duration"
                              f"{')' if anim.loop else ']'}")
        last = k.t
        for dof in k.pose:
            if not _known(dof):
                raise StudioError(f"key at {k.t}: unknown DOF {dof!r}")
    for dof in anim.base:
        if not _known(dof):
            raise StudioError(f"base: unknown DOF {dof!r}")
    for goal in anim.ik:
        sides = getattr(goal, "sides", None) or (getattr(goal, "side", None),)
        if any(s not in ("l", "r") for s in sides):
            raise StudioError(f"ik {type(goal).__name__}: side must be 'l' or 'r'")
        span = getattr(goal, "span", None)
        if span is not None:
            _validate_span(anim, goal.side, span)
    for o in _layers(anim):
        if not _known(o.dof):
            raise StudioError(f"layer: unknown DOF {o.dof!r}")
        if o.period_s <= 0:
            raise StudioError(f"layer {o.dof}: period_s must be > 0")


def _validate_span(anim: Animation, side: str, span) -> None:
    """A HandTarget span must lie inside the clip, must not snap at a loop's
    seam and must be long enough to reach full weight past its fades."""
    a, b = (float(v) for v in span)
    dur = anim.duration_s
    if not 0.0 <= a < b <= dur:
        raise StudioError(f"ik HandTarget {side}: span ({a:g}, {b:g}) must satisfy "
                          f"0 <= a < b <= duration ({dur:g})")
    at_start, at_end = abs(a) < 1e-9, abs(b - dur) < 1e-9
    if anim.loop and at_start != at_end:
        raise StudioError(f"ik HandTarget {side}: span ({a:g}, {b:g}) touches only one end "
                          "of a loop - the hand snaps at the seam (cover both ends or neither)")
    inner = (not at_start) + (not at_end)
    if b - a < inner * FADE_S - 1e-9:
        raise StudioError(f"ik HandTarget {side}: span ({a:g}, {b:g}) is shorter than its "
                          f"{inner} fade(s) of {FADE_S}s - it never reaches full weight")


def _resolved_keys(anim: Animation) -> List[Tuple[float, Dict[str, float], str]]:
    # Every DOF named anywhere starts at its rest value 0 (then base), so a
    # DOF first named in a later key ramps from 0 instead of holding its value
    # from t = 0, and a loop's closing key brings it back.
    named = set(anim.base).union(*(k.pose for k in anim.keys))
    acc: Dict[str, float] = {**{d: 0.0 for d in named}, **anim.base}
    out = []
    for k in anim.keys:
        acc = {**acc, **k.pose}
        out.append((k.t, dict(acc), k.ease))
    if anim.loop and out:
        out.append((anim.duration_s, dict(out[0][1]), out[0][2]))
    return out


def values_at(anim: Animation, t: float) -> Dict[str, float]:
    keys = _resolved_keys(anim)
    values: Dict[str, float] = dict(anim.base)
    if keys:
        dofs = set().union(*(k[1] for k in keys))
        for dof in dofs:
            pts = [(kt, kv[dof], ke) for kt, kv, ke in keys if dof in kv]
            if t <= pts[0][0]:
                values[dof] = pts[0][1]
                continue
            if t >= pts[-1][0]:
                values[dof] = pts[-1][1]
                continue
            for (t0, v0, _e0), (t1, v1, e1) in zip(pts, pts[1:]):
                if t0 <= t <= t1:
                    u = (t - t0) / (t1 - t0) if t1 > t0 else 1.0
                    values[dof] = v0 + (v1 - v0) * EASES[e1](u)
                    break
    for o in _layers(anim):
        values[o.dof] = values.get(o.dof, 0.0) + o.amp * math.sin(
            2.0 * math.pi * (t / o.period_s + o.phase))
    return values
