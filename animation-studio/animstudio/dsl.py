"""The authoring language: one module per animation defines ``ANIM``.

Values are degrees per DOF (see rig.DRIVES) plus ``hips_drop_cm``. A Key
states only what CHANGES: every key is laid over ``base`` and all earlier
keys (carry-forward). ``loop=True`` closes the cycle itself — the first key
is repeated at t = duration, so keys must lie in [0, duration).
"""
import math
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple, Union

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


Point = Tuple[float, float, float]


@dataclass(frozen=True)
class HandTarget:
    """The hand's head (wrist) reaches ``at`` — metres in clip space (X the
    figure's left, Y up, Z front, origin on the floor at the armature
    origin) — during ``span`` (seconds, None = the whole clip), with a
    FADE_S (0.15 s) fade at each inner edge of the span. ``pole`` is the
    direction the elbow points (default down and back). ``validate`` keeps
    the span inside [0, duration], long enough for its fades and, on a
    loop, touching both ends or neither.

    ``at`` is either one point (x, y, z) or KEYS ``((t, (x, y, z)), ...)``:
    times in seconds, strictly increasing, within [0, duration]; the point
    is eased between keys per component, ALWAYS with smoothstep (unlike DOF
    keys there is no per-key ``ease``), held before the first and after the
    last key. On a loop the first key
    is repeated at t = duration (so keys must lie before it)."""
    side: str
    at: Union[Point, Sequence[Tuple[float, Point]]]
    span: Optional[Tuple[float, float]] = None
    pole: Tuple[float, float, float] = (0.0, -1.0, -1.0)


@dataclass(frozen=True)
class FeetPlanted:
    """The ankles stay where frame 0 puts them in XZ, at the rest ankle
    height; the knees bend (forward) to make up for ``hips_drop_cm`` and
    body motion. The foot (with its toes) keeps its FRAME-0 world rotation
    for the whole clip — a planted foot does not turn with the body, and
    ankle/toe DOFs keyed later have no effect on a planted side."""
    sides: Tuple[str, ...] = ("l", "r")


@dataclass(frozen=True)
class FootTarget:
    """The ankle (the Foot bone's head) reaches ``at`` — metres in clip
    space, a point or keys exactly like ``HandTarget.at`` (smoothstep
    between keys; key it every frame for a straight, even path) — for the
    whole clip; the knee bends toward ``pole`` (default forward). The foot
    takes a WORLD rotation of its own instead of following the leg:
    ``yaw`` degrees toes outward, then ``pitch`` degrees toes up (a number,
    or keys ``((t, deg), ...)`` eased like ``at``). The toes keep their own
    ``<s>_toes_flex`` relative to the foot; ``<s>_ankle_flex`` has no
    effect. For a gait in place (walking, running): with
    ``Animation.treadmill_mps`` the planted foot moves back at that speed."""
    side: str
    at: Union[Point, Sequence[Tuple[float, Point]]]
    pitch: Union[float, Sequence[Tuple[float, float]]] = 0.0
    yaw: float = 0.0
    pole: Tuple[float, float, float] = (0.0, 0.0, 1.0)


@dataclass(frozen=True)
class PartnerTarget:
    """PAIR clips only: the hand's head (wrist) reaches a point on the
    PARTNER's body — ``offset`` (metres) in the frame of the partner's torso
    bone ``bone`` (X the partner's left, Y up, Z the partner's front, turned
    with that bone), so the hand stays on the partner's back while both
    bodies move. Only torso bones (``PARTNER_BONES``): their pose comes from
    DOFs alone, never from an IK goal, so the two figures can aim at each
    other without a cycle. ``span`` / ``pole`` as in HandTarget; ``fade_s``
    is the fade at each inner span edge (default FADE_S)."""
    side: str
    bone: str
    offset: Union[Point, Sequence[Tuple[float, Point]]]
    span: Optional[Tuple[float, float]] = None
    pole: Tuple[float, float, float] = (0.0, -1.0, -1.0)
    fade_s: float = FADE_S


#: The partner bones a PartnerTarget may name (no IK ever moves them).
PARTNER_BONES = ("Hips", "Spine", "Spine1", "Spine2", "Neck", "Head")


@dataclass(frozen=True)
class Catalog:
    key: str
    group: str
    prompt: str
    synonyms: Sequence[str] = ()
    #: Synonyms of THIS pose that today belong to another pose and are moved
    #: here deliberately on publish (e.g. "umarmen" from "comforting").
    take_over: Sequence[str] = ()
    #: ``key`` is an EXISTING pose that this clip replaces: publish re-points
    #: it (prompt, animation, group new; its synonyms and other fields such
    #: as ``label_de`` kept, the new synonyms added) instead of refusing the
    #: taken key.
    repoint: bool = False
    #: German display label (the Poses tab shows it). REQUIRED for a pair
    #: pose — the controller labels shipped pair poses from it
    #: (scripts/smoke_pose_labels.py).
    label_de: str = ""


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
    #: m/s of an IN-PLACE gait (walking, running): the clip stays on the
    #: spot, so a planted foot moves back (-Z) at the speed the figure travels;
    #: the foot_slide check measures it against a floor running back at this
    #: speed instead of a still one. 0 = the floor stands still.
    treadmill_mps: float = 0.0


@dataclass
class Role:
    """One half of a pair, authored in its OWN clip space (front +Z) like a
    solo clip; the pair puts it into the shared frame."""
    base: Pose = field(default_factory=Pose)
    keys: List[Key] = field(default_factory=list)
    layers: List = field(default_factory=list)
    ik: List = field(default_factory=list)


@dataclass
class PairAnimation:
    """Two figures, one clip pair ``<kind>__a`` / ``<kind>__b``.

    Authoring frame: A stands at x = -distance_m / 2 facing +X, B at
    +distance_m / 2 facing -X (``distance_m`` = hips apart along their
    facing), each ``stagger_m / 2`` to its OWN right (A towards +Z, B
    towards -Z) — the lateral offset that lets two heads pass each other in
    an embrace. A negative stagger moves each to its own LEFT, so the two
    right hands meet right of each body's midline (a handshake). Each role's own clip space (X its left, Z its front) is
    turned into that frame. The bake then turns the whole pair so that +X
    runs from A's hips to B's (spec docs/schnittstellen-3d.md § A8a), so
    with a stagger both face a little off that line. ``anchor_s`` is the
    moment the sidecar names as the contact (the full embrace)."""
    kind: str
    duration_s: float
    loop: bool
    catalog: Catalog
    a: Role
    b: Role
    distance_m: float
    stagger_m: float = 0.0
    anchor_s: float = 0.0
    fps: int = 30

    def role_anim(self, role: str) -> Animation:
        r = self.a if role == "a" else self.b
        return Animation(kind=self.kind, duration_s=self.duration_s, loop=self.loop,
                         catalog=self.catalog, base=r.base, keys=r.keys, layers=r.layers,
                         ik=r.ik, fps=self.fps)


def validate_pair(pair: PairAnimation) -> None:
    if pair.catalog.group != "stand":
        raise StudioError("pair clips support catalog.group 'stand' only")
    if not 0.1 <= pair.distance_m <= 2.0:
        raise StudioError("distance_m must be within 0.1..2.0")
    if not -0.5 <= pair.stagger_m <= 0.5:
        raise StudioError("stagger_m must be within -0.5..0.5")
    if not 0.0 <= pair.anchor_s <= pair.duration_s:
        raise StudioError("anchor_s must lie within [0, duration]")
    if not str(pair.catalog.label_de).strip():
        raise StudioError("a pair pose needs catalog.label_de (its German display label)")
    for role in ("a", "b"):
        try:
            validate(pair.role_anim(role))
        except StudioError as e:
            raise StudioError(f"role {role}: {e}")


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
    if not 0.0 <= anim.treadmill_mps <= 8.0:
        raise StudioError("treadmill_mps must be within 0..8")
    planted = {s for g in anim.ik if isinstance(g, FeetPlanted) for s in g.sides}
    footed = [g.side for g in anim.ik if isinstance(g, FootTarget)]
    if planted & set(footed) or len(footed) != len(set(footed)):
        raise StudioError("one foot takes one goal: FeetPlanted or a single FootTarget per side")
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
        if isinstance(goal, PartnerTarget):
            if goal.bone not in PARTNER_BONES:
                raise StudioError(f"ik PartnerTarget {goal.side}: bone must be one of "
                                  f"{PARTNER_BONES}")
            _validate_target(anim, goal.side, goal.offset, "PartnerTarget")
            if not 0.05 <= goal.fade_s <= 2.0:
                raise StudioError(f"ik PartnerTarget {goal.side}: fade_s must be 0.05..2.0")
        span = getattr(goal, "span", None)
        if span is not None:
            _validate_span(anim, goal.side, span, getattr(goal, "fade_s", FADE_S),
                           type(goal).__name__)
        if isinstance(goal, HandTarget):
            _validate_target(anim, goal.side, goal.at)
        if isinstance(goal, FootTarget):
            _validate_target(anim, goal.side, goal.at, "FootTarget")
            if not isinstance(goal.pitch, (int, float)):
                _validate_target(anim, goal.side,
                                 [(k[0], (float(k[1]), 0.0, 0.0)) if isinstance(k, (tuple, list))
                                  and len(k) == 2 and isinstance(k[1], (int, float)) else k
                                  for k in goal.pitch], "FootTarget pitch")
    for o in _layers(anim):
        if not _known(o.dof):
            raise StudioError(f"layer: unknown DOF {o.dof!r}")
        if o.period_s <= 0:
            raise StudioError(f"layer {o.dof}: period_s must be > 0")


def _validate_span(anim: Animation, side: str, span, fade: float = FADE_S,
                   what: str = "HandTarget") -> None:
    """A hand-goal span must lie inside the clip, must not snap at a loop's
    seam and must be long enough to reach full weight past its fades."""
    a, b = (float(v) for v in span)
    dur = anim.duration_s
    if not 0.0 <= a < b <= dur:
        raise StudioError(f"ik {what} {side}: span ({a:g}, {b:g}) must satisfy "
                          f"0 <= a < b <= duration ({dur:g})")
    at_start, at_end = abs(a) < 1e-9, abs(b - dur) < 1e-9
    if anim.loop and at_start != at_end:
        raise StudioError(f"ik {what} {side}: span ({a:g}, {b:g}) touches only one end "
                          "of a loop - the hand snaps at the seam (cover both ends or neither)")
    inner = (not at_start) + (not at_end)
    if b - a < inner * fade - 1e-9:
        raise StudioError(f"ik {what} {side}: span ({a:g}, {b:g}) is shorter than its "
                          f"{inner} fade(s) of {fade:g}s - it never reaches full weight")


def _is_point(v) -> bool:
    return (isinstance(v, (tuple, list)) and len(v) == 3
            and all(isinstance(c, (int, float)) and not isinstance(c, bool) for c in v))


def _validate_target(anim: Animation, side: str, at, what: str = "HandTarget") -> None:
    """A point, or keys ``(t, point)`` with increasing times inside the clip."""
    if _is_point(at):
        return
    where = f"ik {what} {side}"
    if not isinstance(at, (tuple, list)) or not at:
        raise StudioError(f"{where}: at must be a point (x, y, z) or a non-empty "
                          "list of (t, (x, y, z)) keys")
    last = None
    for k in at:
        if not (isinstance(k, (tuple, list)) and len(k) == 2
                and isinstance(k[0], (int, float)) and _is_point(k[1])):
            raise StudioError(f"{where}: key {k!r} is not (t, (x, y, z))")
        t = float(k[0])
        if last is not None and t <= last:
            raise StudioError(f"{where}: key times must increase (at {t:g})")
        if t < 0 or t > anim.duration_s or (anim.loop and t >= anim.duration_s):
            raise StudioError(f"{where}: key at {t:g} outside [0, duration"
                              f"{')' if anim.loop else ']'}")
        last = t


def target_at(anim: Animation, goal, t: float) -> Point:
    """The target point (metres) of a HandTarget / FootTarget (``at``) or
    the offset of a PartnerTarget at time ``t``."""
    return _eased(anim, goal.offset if isinstance(goal, PartnerTarget) else goal.at, t)


def pitch_at(anim: Animation, goal: FootTarget, t: float) -> float:
    """A FootTarget's pitch (degrees toes up) at time ``t``."""
    if isinstance(goal.pitch, (int, float)):
        return float(goal.pitch)
    return _eased(anim, [(kt, (kv, 0.0, 0.0)) for kt, kv in goal.pitch], t)[0]


def _eased(anim: Animation, at, t: float) -> Point:
    """A point, or keys ``(t, point)`` eased with smoothstep, held outside
    them and closed back to the first key on a loop."""
    if _is_point(at):
        return tuple(float(c) for c in at)
    keys = [(float(kt), tuple(float(c) for c in kp)) for kt, kp in at]
    if anim.loop:
        keys.append((anim.duration_s, keys[0][1]))
    if t <= keys[0][0]:
        return keys[0][1]
    if t >= keys[-1][0]:
        return keys[-1][1]
    for (t0, p0), (t1, p1) in zip(keys, keys[1:]):
        if t0 <= t <= t1:
            u = EASES["in_out"]((t - t0) / (t1 - t0))
            return tuple(a + (b - a) * u for a, b in zip(p0, p1))
    return keys[-1][1]


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
