"""Shared colour, JSON, geometry and Blender timeout helpers for the hull."""
import json
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple

Vec2 = Tuple[float, float]


def _r(v: float, nd: int = 4) -> float:
    return round(float(v) + 0.0, nd)


def tone(value: Any, fallback: str) -> str:
    """``#rrggbb`` or the fallback — the one place a colour is parsed.

    Accepts ``#rgb`` too (an LLM writes it often enough) and expands it;
    anything else is not a colour and does not become one.
    """
    s = str(value or "").strip().lower()
    if s.startswith("#"):
        s = s[1:]
    if len(s) == 3 and all(c in "0123456789abcdef" for c in s):
        s = "".join(c * 2 for c in s)
    if len(s) == 6 and all(c in "0123456789abcdef" for c in s):
        return f"#{s}"
    return fallback


def tone_to_linear(tone: str) -> List[float]:
    """``#rrggbb`` -> linear RGB, the space Blender's Base Color lives in.

    sRGB is what a person (and an LLM) names; a principled BSDF is fed linear
    values, so a tone handed over raw comes out washed out. The transfer
    function is the standard sRGB EOTF.
    """
    s = tone.lstrip("#")
    out: List[float] = []
    for i in (0, 2, 4):
        c = int(s[i:i + 2], 16) / 255.0
        out.append(round(c / 12.92 if c <= 0.04045
                         else ((c + 0.055) / 1.055) ** 2.4, 6))
    return out


def convex_hull(points: Sequence[Vec2]) -> List[Vec2]:
    """Monotone-chain hull in the XZ plane, counter-clockwise in (x, z)."""
    pts = sorted(set((round(x, 6), round(z, 6)) for x, z in points))
    if len(pts) < 3:
        return list(pts)

    def cross(o: Vec2, a: Vec2, b: Vec2) -> float:
        return ((a[0] - o[0]) * (b[1] - o[1])
                - (a[1] - o[1]) * (b[0] - o[0]))

    lower: List[Vec2] = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper: List[Vec2] = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def oriented_bbox(points: Sequence[Vec2]) -> Dict[str, Any]:
    """The minimum-area rectangle around a point set (rotating calipers).

    V1 RECTANGULARIZES, and says so: an L-shaped or curved contour is roofed
    by the rectangle that hugs it. A real roof over a concave outline needs a
    straight-skeleton solver, which is a stage of its own — a rectangle is
    honest, deterministic and right for the huts and houses this exists for.

    Returns ``{center, angle_deg, length, depth, u, v}`` where ``u`` is the
    rectangle's long-side direction in the XZ plane, ``length`` its extent
    along ``u`` and ``depth`` along ``v`` (so ``length >= depth`` always).
    """
    hull = convex_hull(points)
    if len(hull) < 3:
        xs = [p[0] for p in points] or [0.0]
        zs = [p[1] for p in points] or [0.0]
        length, depth = max(xs) - min(xs), max(zs) - min(zs)
        return {"center": ((min(xs) + max(xs)) / 2, (min(zs) + max(zs)) / 2),
                "angle_deg": 0.0, "length": max(length, depth),
                "depth": min(length, depth),
                "u": (1.0, 0.0) if length >= depth else (0.0, 1.0),
                "v": (0.0, 1.0) if length >= depth else (-1.0, 0.0)}

    best: Optional[Tuple[float, Dict[str, Any]]] = None
    n = len(hull)
    for i in range(n):
        ax, az = hull[i]
        bx, bz = hull[(i + 1) % n]
        edge = math.hypot(bx - ax, bz - az)
        if edge < 1e-9:
            continue
        ux, uz = (bx - ax) / edge, (bz - az) / edge
        vx, vz = -uz, ux
        su = [p[0] * ux + p[1] * uz for p in hull]
        sv = [p[0] * vx + p[1] * vz for p in hull]
        du, dv = max(su) - min(su), max(sv) - min(sv)
        area = du * dv
        cu, cv = (max(su) + min(su)) / 2, (max(sv) + min(sv)) / 2
        rect = {"center": (cu * ux + cv * vx, cu * uz + cv * vz),
                "u": (ux, uz), "v": (vx, vz), "length": du, "depth": dv}
        # The long side names the rectangle: swapping here means every caller
        # can rely on length >= depth instead of checking.
        if dv > du:
            rect = {"center": rect["center"], "u": (vx, vz), "v": (-ux, -uz),
                    "length": dv, "depth": du}
        if best is None or area < best[0] - 1e-9:
            best = (area, rect)

    rect = best[1] if best else {}
    ux, uz = rect["u"]
    rect["angle_deg"] = _r(math.degrees(math.atan2(uz, ux)), 3)
    rect["center"] = (_r(rect["center"][0]), _r(rect["center"][1]))
    rect["length"] = _r(rect["length"])
    rect["depth"] = _r(rect["depth"])
    return rect


def parse_json(raw: str) -> Optional[Dict[str, Any]]:
    """The first JSON object in a model answer, fences and prose tolerated."""
    text = str(raw or "").strip()
    if text.startswith("```"):
        text = text.split("```")[1] if "```" in text[3:] else text[3:]
        if text.lstrip().lower().startswith("json"):
            text = text.lstrip()[4:]
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        obj = json.loads(text[start:end + 1])
    except ValueError:
        return None
    return obj if isinstance(obj, dict) else None


def timeout_s() -> int:
    """A parametric roof is seconds of work — the mesh-refinement timeout is
    the right order of magnitude here (unlike a Cycles render)."""
    try:
        from app.core import config
        return int(config.get("image_generation.blender_timeout_s", 120) or 120)
    except Exception:
        return 120
