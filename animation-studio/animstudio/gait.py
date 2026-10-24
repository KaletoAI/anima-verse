"""A gait IN PLACE (walking, running): the two foot paths, the toe roll and
the height the hips may have, sampled once per frame — the source turns
them into ``FootTarget`` keys and DOF keys.

The clip stays on the spot, so the floor is a belt running back (-Z) at
``speed_mps`` (``Animation.treadmill_mps`` = the same number). Per foot the
cycle phase φ runs 0..1 (the right foot half a cycle behind the left):

* contact, φ in [0, stance): the foot is carried back by the belt. It rolls
  over three pivots that stay on the belt — the HEEL while the toes come
  down from ``heel_pitch`` (φ < roll_in), the whole sole while flat, the
  BALL while the heel rises to ``toe_pitch`` (φ > roll_out). The ankle is
  the pivot minus the turned pivot offset, so a pivot never slides.
* swing, φ in [stance, 1): a cubic Hermite from the toe-off ankle to the
  heel-strike ankle with the end velocities of the contact path (no kink),
  lifted by ``lift_cm`` · sin²(π u^0.6) — the foot leaves the floor at
  once (a ball dragged along under the contact height slides) and is
  highest early in the swing; the pitch runs on the same Hermite from
  toe_pitch back to heel_pitch. ``land_cm_s`` gives the height a downward
  end velocity (the only kink: the foot stops on the floor).

The toes lie flat on the floor while the ball is the pivot (toes_flex =
-pitch) and relax over the first half of the swing.

``hips_max_drop`` is not a height but the LEAST hips_drop_cm at which every
planted leg keeps ``knee_min_deg`` of bend (hip joint at its rest place,
pelvis turns ignored — the ik check reads the real residual).
"""
import math
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from animstudio.rig import load_rest

#: Pivot offsets from the ankle with the foot flat (cm, rig rest): the ball
#: is the ToeBase head; the heel, which has no joint, is taken under the
#: ankle, 4 cm behind it, on the floor.
FPS = 30


@dataclass
class GaitFrames:
    t: List[float]
    ankle: Dict[str, List[Tuple[float, float, float]]] = field(default_factory=dict)   # m
    pitch: Dict[str, List[float]] = field(default_factory=dict)
    toes: Dict[str, List[float]] = field(default_factory=dict)
    contact: Dict[str, List[bool]] = field(default_factory=dict)
    hips_min_drop: List[float] = field(default_factory=list)                         # cm


def _rot(p_deg: float, v: Tuple[float, float]) -> Tuple[float, float]:
    """(y, z) of an offset after the foot turns ``p_deg`` toes up."""
    a = math.radians(p_deg)
    y, z = v
    return (math.cos(a) * y + math.sin(a) * z, -math.sin(a) * y + math.cos(a) * z)


def _ease(u: float) -> float:
    u = max(0.0, min(1.0, u))
    return u * u * (3.0 - 2.0 * u)


def _hermite(p0, p1, m0, m1, u):
    h00 = 2 * u ** 3 - 3 * u ** 2 + 1
    h10 = u ** 3 - 2 * u ** 2 + u
    h01 = -2 * u ** 3 + 3 * u ** 2
    h11 = u ** 3 - u ** 2
    return h00 * p0 + h10 * m0 + h01 * p1 + h11 * m1


def gait(*, duration_s: float, speed_mps: float, stance: float, heel_pitch: float,
         toe_pitch: float, lift_cm: float, roll_in: float = 0.08, roll_out: float = 0.55,
         width_cm: float = 10.0, centre_cm: float = 0.0, knee_min_deg: float = 8.0,
         phase: float = 0.0, land_cm_s: float = 0.0) -> GaitFrames:
    """``roll_in`` / ``roll_out`` are fractions OF THE CONTACT (heel pivot
    until roll_in·stance, ball pivot from roll_out·stance); ``centre_cm`` is
    where the flat ankle passes at mid-contact (Z, + = in front of the
    hips); ``width_cm`` the ankle's X from the midline; ``phase`` is the
    left foot's phase at t = 0 (start a loop in a flat contact: the
    importer's foot plant lowers a heel-strike frame and would open the
    seam); ``land_cm_s`` the speed the foot comes DOWN with at touchdown
    (a run: the foot drops onto the floor instead of gliding in low, where
    the ball would count as planted while still moving)."""
    rest = load_rest()
    ankle0 = rest.head["LeftFoot"]
    ball = (rest.head["LeftToeBase"][1] - ankle0[1], rest.head["LeftToeBase"][2] - ankle0[2])
    heel = (-ankle0[1], -4.0)
    hip_y = rest.head["LeftUpLeg"][1]
    hip_z = rest.head["LeftUpLeg"][2]
    l1 = float(((rest.head["LeftLeg"] - rest.head["LeftUpLeg"]) ** 2).sum() ** 0.5)
    l2 = float(((rest.head["LeftFoot"] - rest.head["LeftLeg"]) ** 2).sum() ** 0.5)
    k = math.radians(knee_min_deg)
    leg_max = math.sqrt(l1 * l1 + l2 * l2 + 2 * l1 * l2 * math.cos(k))
    belt = speed_mps * 100.0 * duration_s           # cm per cycle
    z_mid = centre_cm + belt * stance / 2.0         # flat ankle Z at φ = 0
    a_in, a_out = roll_in * stance, roll_out * stance

    def contact(phi: float) -> Tuple[float, float, float]:
        """(y, z, pitch) of the ankle in contact."""
        flat_z = z_mid - belt * phi
        if phi < a_in:
            p = heel_pitch * (1.0 - _ease(phi / a_in))
            piv = heel
        elif phi > a_out:
            p = toe_pitch * _ease((phi - a_out) / (stance - a_out))
            piv = ball
        else:
            return ankle0[1], flat_z, 0.0
        ry, rz = _rot(p, piv)
        # pivot on the floor at flat_z + its flat offset; ankle = pivot - turned offset
        return -ry + 0.0, flat_z + piv[1] - rz, p

    def deriv(phi: float, h: float = 1e-4):
        a, b = contact(phi - h), contact(phi + h)
        return [(bb - aa) / (2 * h) for aa, bb in zip(a, b)]

    y0, z0, p0 = contact(stance - 1e-9)
    y1, z1, p1 = contact(0.0)
    d0 = deriv(stance - 2e-4)
    d1 = deriv(2e-4)
    span = 1.0 - stance

    def at(phi: float):
        phi %= 1.0
        if phi < stance:
            y, z, p = contact(phi)
            toes = -p if phi > a_out else 0.0
            return y, z, p, toes, True
        u = (phi - stance) / span
        z = _hermite(z0, z1, d0[1] * span, d1[1] * span, u)
        y = _hermite(y0, y1, d0[0] * span, (d1[0] - land_cm_s * duration_s) * span, u) \
            + lift_cm * math.sin(math.pi * u ** 0.6) ** 2
        p = _hermite(p0, p1, d0[2] * span, d1[2] * span, u)
        toes = -p0 * (1.0 - _ease(u / 0.5))
        return y, z, p, toes, False

    n = int(round(duration_s * FPS))
    out = GaitFrames(t=[i / FPS for i in range(n)])
    for side, sx, off in (("l", 1.0, phase), ("r", -1.0, phase + 0.5)):
        out.ankle[side], out.pitch[side], out.toes[side], out.contact[side] = [], [], [], []
        for t in out.t:
            y, z, p, toes, c = at(t / duration_s + off)
            out.ankle[side].append((sx * width_cm / 100.0, y / 100.0, z / 100.0))
            out.pitch[side].append(p)
            out.toes[side].append(toes)
            out.contact[side].append(c)
    for i in range(n):
        need = 0.0
        for side in ("l", "r"):
            if not out.contact[side][i]:
                continue
            x, y, z = (c * 100.0 for c in out.ankle[side][i])
            dx = abs(x) - rest.head["LeftUpLeg"][0]
            dz = z - hip_z
            top = y + math.sqrt(max(0.0, leg_max ** 2 - dx * dx - dz * dz))
            need = max(need, hip_y - top)
        out.hips_min_drop.append(need)
    return out


def bob(g: GaitFrames, *, low_phase: float, base_cm: float, amp_cm: float = 0.0,
        margin_cm: float = 0.5) -> List[float]:
    """hips_drop_cm per frame: ``base_cm`` plus a bob twice per cycle,
    deepest (``+amp``) at cycle phase ``low_phase`` and half a cycle later.
    ``amp_cm`` 0 = the least amplitude at which every frame keeps
    ``margin_cm`` above ``hips_min_drop`` (a walk: deepest at double
    support); a larger given amplitude is kept (a run: deepest at
    mid-stance). Raises when ``base_cm`` alone is too high for a frame the
    bob cannot reach."""
    n = len(g.t)
    shape = [0.5 * (1.0 + math.cos(4.0 * math.pi * (i / n - low_phase))) for i in range(n)]
    amp = amp_cm
    for i in range(n):
        need = g.hips_min_drop[i] + margin_cm - base_cm
        if need > amp * shape[i] + 1e-9:
            if shape[i] < 0.05:
                raise ValueError(f"frame {i}: base {base_cm} cm too high (needs "
                                 f"{g.hips_min_drop[i] + margin_cm:.1f}) where the bob is ~0")
            amp = need / shape[i]
    return [base_cm + amp * s for s in shape]
