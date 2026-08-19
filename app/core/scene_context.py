"""The CONTEXT RENDER — one placement spot of a location, rendered with a
KNOWN camera (``docs/scene-context-render.md``).

This is stage 1 of the scene-context pipeline (``analyse-worldclaw.md``): an
asset is not generated on neutral ground any more but INTO its own place —
same light, same style, same scale. For that the image model needs a picture
of the spot, and the pipeline behind it needs to know EXACTLY which camera
took that picture. Everything after this stage (inpaint, cut-out, image-to-3D,
re-placement) is metric only because the sidecar written here says what the
camera was.

THE DIVISION OF LABOUR is the one the Blender runner already uses elsewhere:
this module decides, ``app/blender/scripts/scene_context.py`` executes. The
script builds meshes from finished vertex lists, sets the camera and the sun
to the numbers it is handed, renders, and writes the sidecar VERBATIM plus the
render settings it actually used. It computes no geometry of its own, so a
number in the sidecar can always be traced back to a function in here.

THE FRAME is the location's own SCENE frame — the very frame
``scene_recipe.compose_scene`` emits: origin at the anchor pin, x east, y up,
z south, metres. The pin transform (``pos_x``/``pos_z``/``yaw_deg``) travels
in the sidecar beside it, so a world coordinate is one
``world_geometry.local_to_world`` away and nothing has to be re-derived.
The scene frame is also where the payload's y values live, so the WORLD relief
under the location (``world_geometry.ground_y``) is not added to the geometry;
it is recorded at the pin instead.

Blender is Z-up, so every vector handed over is converted ONCE, here:

    (x, y, z)_scene  ->  (x, -z, y)_blender

which is a proper rotation (both frames are right-handed), and its transpose
brings a rotation matrix back. No second convention exists on the Blender side.
"""

import json
import math
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from app.core.log import get_logger

logger = get_logger(__name__)

Vec2 = Tuple[float, float]
Vec3 = Tuple[float, float, float]
Mat3 = Tuple[Vec3, Vec3, Vec3]

# ── Contract constants ──────────────────────────────────────────────────

#: Focal length of the context camera in millimetres. 50 mm on a 36 mm sensor
#: is the classic "normal" lens: wide enough to show the surroundings a prop
#: has to match, narrow enough that the perspective does not warp the object
#: the edit model is asked to draw.
DEFAULT_LENS_MM = 50.0
#: Sensor height in millimetres. The camera is fitted VERTICALLY, so this is
#: the number both fx and fy derive from and the image aspect never changes
#: the focal length in pixels.
SENSOR_MM = 36.0
#: Camera elevation above the horizontal, degrees — a three-quarter view.
#: Low enough to keep a silhouette against the background, high enough that
#: the footprint is a visible surface rather than a line.
DEFAULT_ELEVATION_DEG = 35.0
#: Camera azimuth RELATIVE to the target's own yaw, degrees. 45° is the
#: three-quarter angle: two sides of an oriented object are visible at once.
DEFAULT_AZIMUTH_OFFSET_DEG = 45.0
#: How much of the image HEIGHT the target's enclosing sphere fills.
DEFAULT_FILL = 0.40
#: Square by default — an inpaint mask and a crop both behave better without
#: an aspect to keep track of.
DEFAULT_SIZE_PX = 1024
#: Cycles samples. This is a context plate for an image model, not a beauty
#: render; noise below the edit model's own noise floor is wasted time.
DEFAULT_SAMPLES = 48
#: Terrain patch: cells per side and how much larger than the visible frame
#: the patch is. 1.5 covers the frame plus what a slight camera error would
#: reveal at the edges.
TERRAIN_CELLS = 32
TERRAIN_SPAN_FACTOR = 1.5
#: Everything within this multiple of the patch radius is imported/built —
#: recipe primitives and existing meshes alike.
CONTENT_RADIUS_FACTOR = 1.0
#: The scale reference: a 1 m grid on the ground and a figure of the contract's
#: own height (``scene_recipe.FIGURE_HEIGHT_M``) beside the spot.
GRID_STEP_M = 1.0
GRID_LINE_WIDTH_M = 0.025
GRID_LIFT_M = 0.02
FIGURE_RADIUS_M = 0.19
#: How far BESIDE the target the reference figure stands: the target's own
#: radius plus this, at 90° to the camera azimuth (out of the way of the spot
#: the edit model has to fill).
FIGURE_CLEARANCE_M = 0.8

#: Highest the sun climbs at local noon, degrees. A world calendar has no
#: latitude, so this is a world constant rather than a computation.
SUN_MAX_ELEVATION_DEG = 60.0
#: The night light ("moonlight-ish low sun") never gets higher than this.
MOON_MAX_ELEVATION_DEG = 28.0
#: Never let the light lie flat on the ground: a sun at 0° casts shadows of
#: infinite length and lights nothing.
MIN_ELEVATION_DEG = 6.0

#: Sun/sky energies. Night trades sun for ambient on purpose — a moonlit scene
#: with a daylight contrast ratio is a black picture with two lit faces.
DAY_SUN_STRENGTH = 4.0
DAY_SKY_STRENGTH = 0.5
DAY_SKY_COLOR = (0.45, 0.62, 0.88)
NIGHT_SUN_STRENGTH = 0.30
NIGHT_SKY_STRENGTH = 0.80
NIGHT_SKY_COLOR = (0.12, 0.16, 0.28)
#: Sun disc colour at zenith and at the horizon; mixed by elevation over
#: ``SUN_WARM_BELOW_DEG``.
SUN_COLOR_HIGH = (1.0, 0.96, 0.90)
SUN_COLOR_LOW = (1.0, 0.72, 0.45)
SUN_WARM_BELOW_DEG = 25.0
MOON_COLOR = (0.60, 0.68, 1.0)
#: Angular diameter of the light source, degrees — a soft shadow edge without
#: a second light.
SUN_ANGLE_DEG = 1.5
NIGHT_ANGLE_DEG = 3.0

#: Material colours for the parts that are not a stored mesh. Plates and walls
#: use the contract's own palette (``scene_recipe.STYLE``) so the context plate
#: shows the same shell the 3D client shows.
TERRAIN_COLOR = (0.34, 0.33, 0.28)
GRID_COLOR = (0.82, 0.82, 0.80)
FIGURE_COLOR = (0.55, 0.55, 0.58)

#: Sidecar format version — the pipeline stages after this one read it.
SIDECAR_VERSION = 1


# ── Linear algebra (pure, hand-checkable) ───────────────────────────────

def _v_sub(a: Sequence[float], b: Sequence[float]) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _v_add(a: Sequence[float], b: Sequence[float]) -> Vec3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _v_dot(a: Sequence[float], b: Sequence[float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _v_cross(a: Sequence[float], b: Sequence[float]) -> Vec3:
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _v_len(a: Sequence[float]) -> float:
    return math.sqrt(_v_dot(a, a))


def _v_unit(a: Sequence[float]) -> Vec3:
    n = _v_len(a)
    if n <= 1e-12:
        return (0.0, 0.0, 0.0)
    return (a[0] / n, a[1] / n, a[2] / n)


def rot_x(deg: float) -> Mat3:
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return ((1.0, 0.0, 0.0), (0.0, c, -s), (0.0, s, c))


def rot_y(deg: float) -> Mat3:
    """Yaw in the SCENE frame — the turning sense of the world map (§ A1.1):
    a local point maps to ``x·cos + z·sin`` / ``−x·sin + z·cos``, exactly
    ``world_geometry.local_to_world`` and three.js' ``Ry(+θ)``."""
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return ((c, 0.0, s), (0.0, 1.0, 0.0), (-s, 0.0, c))


def rot_z(deg: float) -> Mat3:
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return ((c, -s, 0.0), (s, c, 0.0), (0.0, 0.0, 1.0))


def mat_mul(a: Mat3, b: Mat3) -> Mat3:
    return tuple(tuple(sum(a[i][k] * b[k][j] for k in range(3))
                       for j in range(3)) for i in range(3))  # type: ignore


def mat_apply(m: Mat3, v: Sequence[float]) -> Vec3:
    return (m[0][0] * v[0] + m[0][1] * v[1] + m[0][2] * v[2],
            m[1][0] * v[0] + m[1][1] * v[1] + m[1][2] * v[2],
            m[2][0] * v[0] + m[2][1] * v[1] + m[2][2] * v[2])


def mat_transpose(m: Mat3) -> Mat3:
    return tuple(tuple(m[j][i] for j in range(3)) for i in range(3))  # type: ignore


def fix_matrix(fix_euler: Any, *, snap: bool = False) -> Mat3:
    """The orientation fix of a model spec as a rotation matrix (§ B2).

    Euler order ``'YXZ'`` — yaw outermost, tilt and roll in the already-turned
    frame, i.e. ``Ry · Rx · Rz``. That is what ``place()`` in
    ``@anima/scene-render`` applies, and with a single non-zero axis (the usual
    90°-step fix) every order agrees anyway.

    ``snap`` rounds each angle to 90°, which is the MEASURING fix of § B2: how
    big an object is must not depend on a fine angle inflating its
    axis-aligned hull.
    """
    rot = fix_euler if isinstance(fix_euler, dict) else {}

    def ang(axis: str) -> float:
        try:
            v = float(rot.get(axis) or 0.0)
        except (TypeError, ValueError):
            v = 0.0
        return round(v / 90.0) * 90.0 if snap else v

    return mat_mul(mat_mul(rot_y(ang("y")), rot_x(ang("x"))), rot_z(ang("z")))


#: Scene -> Blender: (x, y, z) -> (x, -z, y). Right-handed to right-handed,
#: determinant +1.
_TO_BLENDER: Mat3 = ((1.0, 0.0, 0.0), (0.0, 0.0, -1.0), (0.0, 1.0, 0.0))


def to_blender(v: Sequence[float]) -> Vec3:
    """One scene vector in Blender's Z-up frame."""
    return (float(v[0]), -float(v[2]), float(v[1]))


def mat_to_blender(m: Mat3) -> Mat3:
    """A scene-frame rotation expressed in Blender's frame: ``M · R · Mᵀ``."""
    return mat_mul(mat_mul(_TO_BLENDER, m), mat_transpose(_TO_BLENDER))


def quaternion_of(m: Mat3) -> Tuple[float, float, float, float]:
    """``(w, x, y, z)`` of a rotation matrix whose COLUMNS are the rotated
    basis vectors (Shepperd: the largest diagonal term decides the branch, so
    no division by a near-zero trace)."""
    t = m[0][0] + m[1][1] + m[2][2]
    if t > 0.0:
        s = math.sqrt(t + 1.0) * 2.0
        w = 0.25 * s
        x = (m[2][1] - m[1][2]) / s
        y = (m[0][2] - m[2][0]) / s
        z = (m[1][0] - m[0][1]) / s
    elif m[0][0] > m[1][1] and m[0][0] > m[2][2]:
        s = math.sqrt(1.0 + m[0][0] - m[1][1] - m[2][2]) * 2.0
        w = (m[2][1] - m[1][2]) / s
        x = 0.25 * s
        y = (m[0][1] + m[1][0]) / s
        z = (m[0][2] + m[2][0]) / s
    elif m[1][1] > m[2][2]:
        s = math.sqrt(1.0 + m[1][1] - m[0][0] - m[2][2]) * 2.0
        w = (m[0][2] - m[2][0]) / s
        x = (m[0][1] + m[1][0]) / s
        y = 0.25 * s
        z = (m[1][2] + m[2][1]) / s
    else:
        s = math.sqrt(1.0 + m[2][2] - m[0][0] - m[1][1]) * 2.0
        w = (m[1][0] - m[0][1]) / s
        x = (m[0][2] + m[2][0]) / s
        y = (m[1][2] + m[2][1]) / s
        z = 0.25 * s
    return (w, x, y, z)


def look_at_basis(eye: Sequence[float], target: Sequence[float]) -> Mat3:
    """Camera basis (right, up, back) of an eye looking at a target.

    Returned as a matrix whose ROWS are the three axes in SCENE coordinates —
    which makes it the world→camera rotation: ``v_cam = R · (p − eye)``. The
    convention is the one Blender and OpenGL share: the camera looks along
    ``−z_cam``, ``+y_cam`` is up, ``+x_cam`` is right.

    Straight down (or straight up) has no defined "right" against the world's
    up vector; there the world's SOUTH axis stands in, so a top-down context
    render is still deterministic instead of degenerate.
    """
    back = _v_unit(_v_sub(eye, target))
    if _v_len(back) <= 1e-12:
        back = (0.0, 0.0, 1.0)
    up_ref: Vec3 = (0.0, 1.0, 0.0)
    right = _v_cross(up_ref, back)
    if _v_len(right) < 1e-6:
        right = _v_cross((0.0, 0.0, 1.0), back)
    right = _v_unit(right)
    up = _v_cross(back, right)
    return (right, up, back)


# ── Framing and camera ──────────────────────────────────────────────────

def footprint_radius(footprint: Sequence[Sequence[float]],
                     anchor: Sequence[float]) -> float:
    """Largest horizontal distance from the anchor to a footprint corner."""
    best = 0.0
    for pt in footprint or ():
        dx = float(pt[0]) - float(anchor[0])
        dz = float(pt[1]) - float(anchor[1])
        best = max(best, math.hypot(dx, dz))
    return best


def target_span_m(footprint: Sequence[Sequence[float]],
                  anchor: Sequence[float], height_m: float = 0.0) -> float:
    """The diameter of the smallest sphere around the target's centre that
    holds its footprint corners and its height.

    A SPHERE and not a box, because the framing must not depend on the angle
    it is looked at from: a sphere projects to the same disc from every
    direction, so "the target fills 40 % of the image height" holds at the
    contract's 35° elevation exactly as it would head-on. The centre sits at
    half the target's height, so ``R = √(r_h² + (h/2)²)``.
    """
    r_h = footprint_radius(footprint, anchor)
    half_h = max(float(height_m or 0.0), 0.0) / 2.0
    return 2.0 * math.hypot(r_h, half_h)


def solve_camera(anchor: Sequence[float], span_m: float, *,
                 ground_y: float = 0.0,
                 height_m: float = 0.0,
                 yaw_deg: float = 0.0,
                 elevation_deg: float = DEFAULT_ELEVATION_DEG,
                 azimuth_offset_deg: float = DEFAULT_AZIMUTH_OFFSET_DEG,
                 lens_mm: float = DEFAULT_LENS_MM,
                 sensor_mm: float = SENSOR_MM,
                 width: int = DEFAULT_SIZE_PX,
                 height: int = DEFAULT_SIZE_PX,
                 fill: float = DEFAULT_FILL) -> Dict[str, Any]:
    """THE camera solve — deterministic, pure, one place (§ B5a in spirit).

    ``anchor`` is the target's ground point in the scene frame ``[x, z]``,
    ``ground_y`` the height of the ground under it, ``span_m`` the diameter
    from :func:`target_span_m`.

    Three numbers and nothing else decide the camera:

    * **Distance.** An object of size ``s`` at distance ``d`` projects to
      ``fy · s / d`` pixels, and ``fy = H · f / sensor``. Asking for
      ``fill · H`` pixels therefore gives ::

          d = f · s / (sensor · fill)

      — the image resolution cancels out, so changing the render size reframes
      nothing.
    * **Azimuth.** ``ψ = yaw + 45°`` in map yaw, and the camera stands in the
      direction ``(sin ψ, cos ψ)`` from the target: that is the target's own
      "south" turned by its yaw, so a prop is always seen from the same
      three-quarter angle relative to ITSELF.
    * **Elevation.** ``ε = 35°`` above the horizontal.

    The camera then looks at the target's CENTRE (anchor lifted by half the
    target height), which is what keeps the framing honest for a tall object.
    """
    ax, az = float(anchor[0]), float(anchor[1])
    centre: Vec3 = (ax, float(ground_y) + max(float(height_m or 0.0), 0.0) / 2.0, az)
    lens_mm = float(lens_mm or DEFAULT_LENS_MM)
    sensor_mm = float(sensor_mm or SENSOR_MM)
    fill = float(fill or DEFAULT_FILL)
    span_m = max(float(span_m or 0.0), 1e-3)
    distance = lens_mm * span_m / (sensor_mm * fill)

    psi = float(yaw_deg or 0.0) + float(azimuth_offset_deg or 0.0)
    eps = float(elevation_deg)
    cos_e, sin_e = math.cos(math.radians(eps)), math.sin(math.radians(eps))
    ux = math.sin(math.radians(psi))
    uz = math.cos(math.radians(psi))
    position: Vec3 = (centre[0] + distance * cos_e * ux,
                      centre[1] + distance * sin_e,
                      centre[2] + distance * cos_e * uz)
    basis = look_at_basis(position, centre)

    fy = float(height) * lens_mm / sensor_mm
    fx = fy                                    # square pixels, vertical fit
    cam: Dict[str, Any] = {
        "lens_mm": lens_mm,
        "sensor_mm": sensor_mm,
        "sensor_fit": "vertical",
        "resolution": [int(width), int(height)],
        "fx": fx, "fy": fy,
        "cx": float(width) / 2.0, "cy": float(height) / 2.0,
        "position": [position[0], position[1], position[2]],
        "look_at": [centre[0], centre[1], centre[2]],
        "distance_m": distance,
        "azimuth_deg": psi,
        "elevation_deg": eps,
        # Rows = the camera's axes in SCENE coordinates; v_cam = R·(p − position).
        "rotation_matrix": [list(basis[0]), list(basis[1]), list(basis[2])],
        "fov_v_deg": math.degrees(2.0 * math.atan(sensor_mm / (2.0 * lens_mm))),
        "frame_height_m": span_m / fill,
        "frame_width_m": span_m / fill * (float(width) / float(height)),
        "fill_fraction": fill,
        "span_m": span_m,
    }
    cam["fov_h_deg"] = math.degrees(
        2.0 * math.atan(cam["frame_width_m"] / (2.0 * distance)))
    # Blender takes the camera→world rotation, i.e. the TRANSPOSE of the rows
    # above. Only the WORLD side of it is converted (``M · R``, not
    # ``M · R · Mᵀ``): a camera's own local frame — x right, y up, looking
    # along −z — is the SAME in Blender as it is here, so converting it too
    # would turn the camera a second time. A MESH is the other case: its local
    # frame really is converted, by the glTF importer, which is why
    # :func:`mat_to_blender` is right there and wrong here.
    cam["quaternion_blender"] = list(quaternion_of(
        mat_mul(_TO_BLENDER, mat_transpose(basis))))
    cam["position_blender"] = list(to_blender(position))
    return cam


def project(point: Sequence[float], camera: Dict[str, Any]
            ) -> Tuple[float, float, float]:
    """Scene point -> ``(u_px, v_px, depth_m)``.

    ``depth`` is the distance along the viewing axis; it is NEGATIVE for
    anything behind the camera, and a caller that projects a point which may
    be behind it has to look at that value — the pixel coordinates of such a
    point are meaningless, not merely off-screen.
    """
    basis: Mat3 = tuple(tuple(row) for row in camera["rotation_matrix"])  # type: ignore
    rel = _v_sub(point, camera["position"])
    xc = _v_dot(basis[0], rel)
    yc = _v_dot(basis[1], rel)
    zc = _v_dot(basis[2], rel)
    depth = -zc
    if abs(depth) <= 1e-9:
        return (camera["cx"], camera["cy"], depth)
    u = camera["cx"] + camera["fx"] * xc / depth
    v = camera["cy"] - camera["fy"] * yc / depth
    return (u, v, depth)


def convex_hull(points: Sequence[Sequence[float]]) -> List[List[float]]:
    """Monotone-chain hull of 2D points, counter-clockwise in maths axes
    (which reads clockwise in image axes, where y grows downwards)."""
    pts = sorted({(round(float(p[0]), 6), round(float(p[1]), 6))
                  for p in points or ()})
    if len(pts) <= 2:
        return [list(p) for p in pts]

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: List[Tuple[float, float]] = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper: List[Tuple[float, float]] = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return [list(p) for p in lower[:-1] + upper[:-1]]


def mask_polygon(footprint: Sequence[Sequence[float]], base_y: float,
                 height_m: float, camera: Dict[str, Any], *,
                 dilate_px: float = 0.0) -> List[List[float]]:
    """The target's footprint (and the box over it) projected to PIXELS.

    This is what the inpaint stage paints into: the hull of the footprint
    corners at ``base_y`` plus the same corners at ``base_y + height_m``.
    A hull rather than the outline itself, because the silhouette of a box seen
    from a three-quarter angle is exactly the hull of its eight corners, and a
    mask has no business being concave here.

    ``dilate_px`` grows the hull about its own centroid — the inpaint region
    is deliberately a little larger than the object, so its contact shadow and
    its contact with the ground land inside the region too.
    """
    pts: List[List[float]] = []
    for corner in footprint or ():
        for y in ({float(base_y)} if not height_m
                  else {float(base_y), float(base_y) + float(height_m)}):
            u, v, depth = project((float(corner[0]), y, float(corner[1])), camera)
            if depth > 0:
                pts.append([u, v])
    hull = convex_hull(pts)
    if dilate_px and len(hull) >= 3:
        cx = sum(p[0] for p in hull) / len(hull)
        cy = sum(p[1] for p in hull) / len(hull)
        grown: List[List[float]] = []
        for p in hull:
            dx, dy = p[0] - cx, p[1] - cy
            n = math.hypot(dx, dy) or 1.0
            grown.append([p[0] + dx / n * dilate_px, p[1] + dy / n * dilate_px])
        hull = grown
    return [[round(p[0], 2), round(p[1], 2)] for p in hull]


# ── Sun ─────────────────────────────────────────────────────────────────

def solve_sun(game: Any, *, calendar: Any = None) -> Dict[str, Any]:
    """Where the sun (or the moon) stands at a GAME time, and how bright.

    The world calendar gives sunrise and sunset PER SEASON
    (``game_time.Season``) and nothing else — no latitude, no declination — so
    the arc is derived from those two times alone:

    * ``f`` = how far the day (or the night) has run, 0 at sunrise, 1 at sunset;
    * elevation ``= max_elevation · sin(π f)`` — zero at both ends, highest at
      the middle, so local noon is the midpoint of ITS OWN season's daylight;
    * azimuth ``= 90° − 180° f`` in map yaw: 90° is east, 0° is south, 270° is
      west. The sun rises in the east, stands in the south at noon and sets in
      the west.

    NIGHT runs the same arc with the moon's lower ceiling and trades sun energy
    for ambient: a moonlit context plate has to stay READABLE for an image
    model, and a physically honest 1:10000 contrast is a black picture.
    """
    sunrise = int(getattr(game, "sunrise_min", 6 * 60))
    sunset = int(getattr(game, "sunset_min", 18 * 60))
    minutes = int(getattr(game, "minutes_of_day", 12 * 60))
    day_len = max(sunset - sunrise, 1)
    night = bool(game.is_night(calendar) if calendar is not None
                 else game.is_night())
    if not night:
        frac = (minutes - sunrise) / float(day_len)
        ceiling = SUN_MAX_ELEVATION_DEG
    else:
        night_len = max(24 * 60 - day_len, 1)
        since = (minutes - sunset) % (24 * 60)
        frac = since / float(night_len)
        ceiling = MOON_MAX_ELEVATION_DEG
    frac = min(max(frac, 0.0), 1.0)
    elevation = max(ceiling * math.sin(math.pi * frac), MIN_ELEVATION_DEG)
    azimuth = 90.0 - 180.0 * frac

    cos_e = math.cos(math.radians(elevation))
    direction: Vec3 = (cos_e * math.sin(math.radians(azimuth)),
                       math.sin(math.radians(elevation)),
                       cos_e * math.cos(math.radians(azimuth)))
    if night:
        color = MOON_COLOR
        strength = NIGHT_SUN_STRENGTH
        sky_color, sky_strength = NIGHT_SKY_COLOR, NIGHT_SKY_STRENGTH
        angle = NIGHT_ANGLE_DEG
    else:
        t = min(max(elevation / SUN_WARM_BELOW_DEG, 0.0), 1.0)
        color = tuple(SUN_COLOR_LOW[i] + t * (SUN_COLOR_HIGH[i] - SUN_COLOR_LOW[i])
                      for i in range(3))                      # type: ignore
        strength = DAY_SUN_STRENGTH
        sky_color, sky_strength = DAY_SKY_COLOR, DAY_SKY_STRENGTH
        angle = SUN_ANGLE_DEG
    return {
        "night": night,
        "phase_fraction": frac,
        "elevation_deg": elevation,
        "azimuth_deg": azimuth,
        # Unit vector pointing FROM the scene TOWARDS the light.
        "direction": list(direction),
        "direction_blender": list(to_blender(direction)),
        "color": list(color),
        "strength": strength,
        "angle_deg": angle,
        "sky_color": list(sky_color),
        "sky_strength": sky_strength,
        "sunrise_min": sunrise,
        "sunset_min": sunset,
    }


# ── Mesh builders (scene frame in, Blender vertices out) ────────────────

def _mesh(name: str, vertices: List[Vec3], faces: List[List[int]],
          color: Sequence[float], roughness: float = 0.85) -> Dict[str, Any]:
    return {
        "kind": "mesh", "name": name,
        "vertices": [[round(c, 5) for c in to_blender(v)] for v in vertices],
        "faces": faces,
        "color": [round(float(c), 4) for c in color],
        "roughness": roughness,
    }


def _box_vertices(centre: Vec3, size: Vec3, yaw_deg: float) -> List[Vec3]:
    """Eight corners of a yawed box, scene frame."""
    hx, hy, hz = size[0] / 2.0, size[1] / 2.0, size[2] / 2.0
    rot = rot_y(yaw_deg)
    out: List[Vec3] = []
    for sy in (-1, 1):
        for sx, sz in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            local = (sx * hx, sy * hy, sz * hz)
            out.append(_v_add(centre, mat_apply(rot, local)))
    return out


_BOX_FACES = [[0, 1, 2, 3], [7, 6, 5, 4],
              [0, 4, 5, 1], [1, 5, 6, 2], [2, 6, 7, 3], [3, 7, 4, 0]]


def _prism(outline: Sequence[Sequence[float]], top_y: float,
           thickness: float) -> Tuple[List[Vec3], List[List[int]]]:
    """A plate: the outline at ``top_y``, extruded ``thickness`` downwards."""
    pts = [(float(p[0]), float(p[1])) for p in outline or ()]
    n = len(pts)
    verts: List[Vec3] = [(p[0], top_y, p[1]) for p in pts]
    verts += [(p[0], top_y - max(thickness, 1e-3), p[1]) for p in pts]
    faces: List[List[int]] = [list(range(n)), list(range(2 * n - 1, n - 1, -1))]
    for i in range(n):
        j = (i + 1) % n
        faces.append([i, j, n + j, n + i])
    return verts, faces


def _ribbon(points: Sequence[Vec3], width: float,
            axis: str) -> Tuple[List[Vec3], List[List[int]]]:
    """A flat strip following a polyline on the ground — the grid lines.

    ``axis`` says which horizontal direction the strip is widened along
    (``"x"`` for a line running in z, ``"z"`` for a line running in x), which
    is all a straight axis-aligned grid line needs.
    """
    half = width / 2.0
    verts: List[Vec3] = []
    for p in points:
        if axis == "x":
            verts.append((p[0] - half, p[1], p[2]))
            verts.append((p[0] + half, p[1], p[2]))
        else:
            verts.append((p[0], p[1], p[2] - half))
            verts.append((p[0], p[1], p[2] + half))
    faces = [[2 * i, 2 * i + 1, 2 * i + 3, 2 * i + 2]
             for i in range(len(points) - 1)]
    return verts, faces


# ── Config ──────────────────────────────────────────────────────────────

def render_params(overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The context render's dials — schema defaults, config, then overrides.

    Mirrors ``image_generation.context_render_*`` in ``config_schema.py``;
    the defaults are repeated here so the module also works with no world
    loaded (smokes, CLI).
    """
    def cfg(key: str, default: Any) -> Any:
        try:
            from app.core import config
            val = config.get(f"image_generation.context_render_{key}", None)
        except Exception:
            return default
        return default if val is None or val == "" else val

    params: Dict[str, Any] = {
        "width": int(cfg("width", DEFAULT_SIZE_PX)),
        "height": int(cfg("height", DEFAULT_SIZE_PX)),
        "samples": int(cfg("samples", DEFAULT_SAMPLES)),
        "lens_mm": float(cfg("lens_mm", DEFAULT_LENS_MM)),
        "elevation_deg": float(cfg("elevation_deg", DEFAULT_ELEVATION_DEG)),
        "azimuth_offset_deg": float(cfg("azimuth_offset_deg",
                                        DEFAULT_AZIMUTH_OFFSET_DEG)),
        "fill": float(cfg("fill", DEFAULT_FILL)),
        "grid": bool(cfg("grid", True)),
        "figure": bool(cfg("figure", True)),
        "mask_dilate_px": float(cfg("mask_dilate_px", 0.0)),
        "sensor_mm": SENSOR_MM,
    }
    for key, value in (overrides or {}).items():
        if value is not None:
            params[key] = value
    return params


# ── Target resolution ───────────────────────────────────────────────────

def rect_footprint(anchor: Sequence[float], width_m: float, depth_m: float,
                   yaw_deg: float) -> List[List[float]]:
    """The four corners of a yawed rectangle around an anchor, scene frame."""
    rot = rot_y(yaw_deg)
    hw, hd = float(width_m) / 2.0, float(depth_m) / 2.0
    out: List[List[float]] = []
    for sx, sz in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
        p = mat_apply(rot, (sx * hw, 0.0, sz * hd))
        out.append([float(anchor[0]) + p[0], float(anchor[1]) + p[2]])
    return out


def _dim(dims: Dict[str, Any], long_key: str, short_key: str,
         default: float = 1.0) -> float:
    """One edge length out of a dims block. ``placements[].dims`` spells the
    keys out (``width_m``), ``placeholder_dims`` abbreviates them (``w``) —
    same numbers, two spellings."""
    for key in (long_key, short_key):
        if key in dims and dims[key] is not None:
            try:
                return float(dims[key])
            except (TypeError, ValueError):
                return default
    return default


def resolve_target(scene: Dict[str, Any], target: Dict[str, Any], *,
                   placements: Optional[Sequence[Dict[str, Any]]] = None,
                   height_at: Optional[Callable[[float, float], float]] = None,
                   ) -> Dict[str, Any]:
    """WHICH spot is being rendered, as one flat description.

    Three kinds, all of them ending in the same five numbers (anchor,
    ground height, footprint, height, yaw):

    * ``prop`` — the ``index``-th placement of ``room_id``. The PLACEMENT
      spec in the scene payload owns anchor, yaw and standing height (nothing
      is recomputed from the layout), the recipe placement owns the prop's real
      dims, because a prop with a mesh carries no dims in the payload.
      ``room_id`` may be the GROUND room: a yard placement is a placement.
    * ``spot`` — a free point on the ground with a declared size; the case
      for "put something HERE" without an authored placement.
    * ``building`` — the location's own footprint polygon (``scene.boundary``).

    The prop kind also names the model spec to LEAVE OUT of the render: the
    context plate shows the spot EMPTY, otherwise the edit model is asked to
    draw an object that is already standing there.
    """
    kind = str(target.get("kind") or "prop")
    height_at = height_at or (lambda x, z: 0.0)

    if kind == "building":
        boundary = [[float(p[0]), float(p[1])]
                    for p in (scene.get("boundary") or [])]
        if len(boundary) < 3:
            raise ValueError("location has no boundary polygon")
        xs = [p[0] for p in boundary]
        zs = [p[1] for p in boundary]
        anchor = [(min(xs) + max(xs)) / 2.0, (min(zs) + max(zs)) / 2.0]
        storey = float(scene.get("storey_m") or 3.0)
        return {
            "kind": "building", "room_id": "", "index": -1,
            "anchor": anchor, "ground_y": height_at(anchor[0], anchor[1]),
            "footprint": boundary, "height_m": storey, "yaw_deg": 0.0,
            "exclude_model": {"role": "building"},
        }

    if kind == "spot":
        at = target.get("at") or [0.0, 0.0]
        anchor = [float(at[0]), float(at[1])]
        size = float(target.get("size_m") or 1.0)
        yaw = float(target.get("yaw_deg") or 0.0)
        return {
            "kind": "spot", "room_id": str(target.get("room_id") or ""),
            "index": -1, "anchor": anchor,
            "ground_y": height_at(anchor[0], anchor[1]),
            "footprint": rect_footprint(anchor, size, size, yaw),
            "height_m": float(target.get("height_m") or size),
            "yaw_deg": yaw, "exclude_model": None,
        }

    if kind != "prop":
        raise ValueError(f"unknown context target kind: {kind}")

    room_id = str(target.get("room_id") or "")
    index = int(target.get("index") or 0)
    props = [m for m in (scene.get("models") or [])
             if m.get("role") == "prop" and str(m.get("room_id") or "") == room_id]
    if not 0 <= index < len(props):
        raise ValueError(f"room {room_id!r} has no prop placement #{index}")
    spec = props[index]
    placement = None
    if placements is not None:
        if not 0 <= index < len(placements):
            raise ValueError(f"room {room_id!r} has no recipe placement #{index}")
        placement = placements[index]
    dims = (placement or {}).get("dims") or spec.get("placeholder_dims") or {}
    # An explicit 0 is a real value (a flat placement — a rug, a hatch), so
    # only a MISSING or unreadable dimension falls back to a metre.
    width_m = _dim(dims, "width_m", "w")
    depth_m = _dim(dims, "depth_m", "d")
    height_m = _dim(dims, "height_m", "h")
    anchor = [float(spec["anchor"][0]), float(spec["anchor"][1])]
    yaw = float(spec.get("yaw_deg") or 0.0)
    return {
        "kind": "prop", "room_id": room_id, "index": index,
        "prop_id": str(spec.get("id") or ""),
        "anchor": anchor,
        "ground_y": float(spec.get("bottom_y") or 0.0),
        "footprint": rect_footprint(anchor, width_m, depth_m, yaw),
        "dims_m": [width_m, depth_m, height_m],
        "height_m": height_m,
        "yaw_deg": yaw,
        "exclude_model": {"role": "prop", "room_id": room_id, "index": index},
    }


# ── Scene assembly ──────────────────────────────────────────────────────

def _within(anchor: Sequence[float], point: Sequence[float],
            radius: float) -> bool:
    return math.hypot(float(point[0]) - float(anchor[0]),
                      float(point[1]) - float(anchor[1])) <= radius


def _segment_distance(px: float, pz: float, a: Sequence[float],
                      b: Sequence[float]) -> float:
    """Distance from a point to a SEGMENT (the same formula as the private
    ``world_geometry._point_segment_distance``).

    A wall has to be measured against its whole length, not against its ends:
    a 40 m contour wall running straight past the spot has both its endpoints
    far outside the frame and still crosses the picture.
    """
    ax, az = float(a[0]), float(a[1])
    bx, bz = float(b[0]), float(b[1])
    dx, dz = bx - ax, bz - az
    span = dx * dx + dz * dz
    if span <= 1e-12:
        return math.hypot(px - ax, pz - az)
    t = max(0.0, min(1.0, ((px - ax) * dx + (pz - az) * dz) / span))
    return math.hypot(px - (ax + t * dx), pz - (az + t * dz))


def build_context_scene(location_id: str, target: Dict[str, Any], *,
                        location: Optional[Dict[str, Any]] = None,
                        scene: Optional[Dict[str, Any]] = None,
                        placements: Optional[Sequence[Dict[str, Any]]] = None,
                        game: Any = None,
                        params: Optional[Dict[str, Any]] = None,
                        height_at: Optional[Callable[[float, float], float]] = None,
                        model_files: Optional[Dict[str, str]] = None,
                        ) -> Dict[str, Any]:
    """The whole Blender job for one context render — the brains, no bpy.

    Everything the Blender side needs is decided here: the terrain patch, the
    recipe primitives near the spot, which stored meshes to import, the camera,
    the sun, the scale reference and the sidecar. Pass ``location``/``scene``
    (and ``placements``/``height_at``/``model_files``) to run it without a
    world DB — that is how the smoke checks it.

    Coordinates in the returned job are BLENDER coordinates; the sidecar keeps
    the SCENE frame. That split is deliberate: the Blender script must never
    convert anything, and every number the pipeline reads later is in the frame
    the rest of the server speaks.
    """
    from app.core.scene_recipe import FIGURE_HEIGHT_M, STYLE

    par = render_params(params if isinstance(params, dict) else None)
    if location is None or scene is None:
        location, scene, placements, height_at, model_files = _load_inputs(
            location_id, target)
    height_at = height_at or (lambda x, z: 0.0)
    if game is None:
        from app.core.timeutils import game_time
        game = game_time()

    res = resolve_target(scene, target, placements=placements,
                         height_at=height_at)
    span = target_span_m(res["footprint"], res["anchor"], res["height_m"])
    camera = solve_camera(res["anchor"], span,
                          ground_y=res["ground_y"], height_m=res["height_m"],
                          yaw_deg=res["yaw_deg"],
                          elevation_deg=par["elevation_deg"],
                          azimuth_offset_deg=par["azimuth_offset_deg"],
                          lens_mm=par["lens_mm"], sensor_mm=par["sensor_mm"],
                          width=par["width"], height=par["height"],
                          fill=par["fill"])
    sun = solve_sun(game)

    patch_m = max(camera["frame_width_m"], camera["frame_height_m"]) \
        * TERRAIN_SPAN_FACTOR
    radius = patch_m / 2.0 * CONTENT_RADIUS_FACTOR
    ax, az = res["anchor"][0], res["anchor"][1]

    primitives: List[Dict[str, Any]] = []
    primitives.append(_terrain_patch(ax, az, patch_m, height_at))
    if par["grid"]:
        primitives.extend(_grid_lines(ax, az, patch_m, height_at))
    primitives.extend(_recipe_primitives(scene, (ax, az), radius, STYLE))
    models = _model_primitives(scene, (ax, az), radius, res,
                               model_files or {})
    primitives.extend(models)
    figure_at = None
    if par["figure"]:
        figure_at = _figure_spot(res, camera, span)
        primitives.append({
            "kind": "figure", "name": "scale_figure",
            "at": [round(c, 5) for c in
                   to_blender((figure_at[0],
                               height_at(figure_at[0], figure_at[1]),
                               figure_at[1]))],
            "height_m": FIGURE_HEIGHT_M, "radius_m": FIGURE_RADIUS_M,
            "color": list(FIGURE_COLOR),
        })

    map3d = (location or {}).get("map3d") or {}
    sidecar: Dict[str, Any] = {
        "version": SIDECAR_VERSION,
        "location_id": str(location_id or (location or {}).get("id") or ""),
        "frame": {
            "kind": "location_local",
            "axes": "x=east, y=up, z=south (metres)",
            # The pin exactly as ``world_geometry.placed_boundary`` reads it —
            # NOT ``map3d.rotation``, which turns the building MODEL (§ A1).
            "pin": {
                "x": float((location or {}).get("pos_x") or 0.0),
                "z": float((location or {}).get("pos_z") or 0.0),
                "yaw_deg": float((location or {}).get("yaw_deg") or 0.0),
            },
            # The world relief is a constant under the whole location and is
            # NOT baked into the geometry (the scene payload does not carry it
            # either) — it is recorded so a world coordinate stays derivable.
            "world_ground_y": float((location or {}).get("_world_ground_y") or 0.0),
            "extent_m": float(scene.get("extent_m") or 0.0),
            "storey_m": float(scene.get("storey_m") or 0.0),
        },
        "target": {
            "kind": res["kind"], "room_id": res["room_id"],
            "index": res["index"], "prop_id": res.get("prop_id", ""),
            "anchor": [round(c, 4) for c in res["anchor"]],
            "ground_y": round(res["ground_y"], 4),
            "footprint": [[round(p[0], 4), round(p[1], 4)]
                          for p in res["footprint"]],
            "dims_m": res.get("dims_m"),
            "height_m": round(res["height_m"], 4),
            "yaw_deg": res["yaw_deg"],
            "span_m": round(span, 4),
        },
        "camera": camera,
        "sun": sun,
        "game_time": {
            "canonical": game.canonical(),
            "label": game.label(),
            "season": game.season,
            "time": game.time_hhmm(),
            "day_bucket": game.day_bucket(),
            "is_night": bool(sun["night"]),
        },
        "mask": {
            "polygon_px": mask_polygon(res["footprint"], res["ground_y"],
                                       res["height_m"], camera,
                                       dilate_px=par["mask_dilate_px"]),
            "dilate_px": par["mask_dilate_px"],
        },
        "scale_reference": {
            "grid": bool(par["grid"]), "grid_step_m": GRID_STEP_M,
            "figure": bool(par["figure"]),
            "figure_height_m": FIGURE_HEIGHT_M,
            "figure_at": ([round(c, 4) for c in figure_at]
                          if figure_at else None),
        },
        "content": {
            "terrain_patch_m": round(patch_m, 3),
            "terrain_cells": TERRAIN_CELLS,
            "content_radius_m": round(radius, 3),
            "models": [m["source"] for m in models],
        },
    }
    poly = sidecar["mask"]["polygon_px"]
    if poly:
        sidecar["mask"]["bbox_px"] = [
            round(min(p[0] for p in poly), 2), round(min(p[1] for p in poly), 2),
            round(max(p[0] for p in poly), 2), round(max(p[1] for p in poly), 2)]

    return {
        "render": {
            "width": par["width"], "height": par["height"],
            "samples": par["samples"], "engine": "CYCLES", "device": "CPU",
            "png": "context.png", "sidecar": "context.json",
        },
        "camera": {
            "position": camera["position_blender"],
            "quaternion": camera["quaternion_blender"],
            "lens_mm": camera["lens_mm"], "sensor_mm": camera["sensor_mm"],
            "sensor_fit": "VERTICAL",
        },
        "sun": {
            "direction": sun["direction_blender"], "color": sun["color"],
            "strength": sun["strength"], "angle_deg": sun["angle_deg"],
        },
        "world": {"color": sun["sky_color"], "strength": sun["sky_strength"]},
        "primitives": primitives,
        "sidecar": sidecar,
    }


def _figure_spot(res: Dict[str, Any], camera: Dict[str, Any],
                 span: float) -> Vec2:
    """Where the reference figure stands: beside the target, at 90° to the
    camera azimuth, so it never covers the spot the edit has to fill."""
    psi = float(camera["azimuth_deg"]) + 90.0
    dist = span / 2.0 + FIGURE_CLEARANCE_M
    return (res["anchor"][0] + dist * math.sin(math.radians(psi)),
            res["anchor"][1] + dist * math.cos(math.radians(psi)))


def _terrain_patch(ax: float, az: float, patch_m: float,
                   height_at: Callable[[float, float], float]
                   ) -> Dict[str, Any]:
    """The ground under the spot as a sampled grid mesh."""
    n = TERRAIN_CELLS
    step = patch_m / n
    x0, z0 = ax - patch_m / 2.0, az - patch_m / 2.0
    verts: List[Vec3] = []
    for iz in range(n + 1):
        for ix in range(n + 1):
            x = x0 + ix * step
            z = z0 + iz * step
            verts.append((x, height_at(x, z), z))
    faces: List[List[int]] = []
    for iz in range(n):
        for ix in range(n):
            a = iz * (n + 1) + ix
            faces.append([a, a + 1, a + n + 2, a + n + 1])
    return _mesh("terrain", verts, faces, TERRAIN_COLOR, roughness=0.95)


def _grid_lines(ax: float, az: float, patch_m: float,
                height_at: Callable[[float, float], float]
                ) -> List[Dict[str, Any]]:
    """The 1 m scale grid — thin ribbons draped over the terrain.

    Ribbons and not a shader: the grid has to follow the relief (a straight
    quad over a hill sinks into it), and a mesh that follows the same samples
    the terrain does cannot drift from it.
    """
    x0 = math.ceil((ax - patch_m / 2.0) / GRID_STEP_M) * GRID_STEP_M
    z0 = math.ceil((az - patch_m / 2.0) / GRID_STEP_M) * GRID_STEP_M
    x1, z1 = ax + patch_m / 2.0, az + patch_m / 2.0
    steps = max(int(patch_m / GRID_STEP_M), 1)
    out: List[Dict[str, Any]] = []
    verts: List[Vec3] = []
    faces: List[List[int]] = []

    def add(points: List[Vec3], axis: str) -> None:
        v, f = _ribbon(points, GRID_LINE_WIDTH_M, axis)
        base = len(verts)
        verts.extend(v)
        faces.extend([[i + base for i in face] for face in f])

    def along_z(x: float) -> List[Vec3]:
        pts: List[Vec3] = []
        for i in range(steps + 1):
            z = z0 + i * (z1 - z0) / steps
            pts.append((x, height_at(x, z) + GRID_LIFT_M, z))
        return pts

    def along_x(z: float) -> List[Vec3]:
        pts: List[Vec3] = []
        for i in range(steps + 1):
            x = x0 + i * (x1 - x0) / steps
            pts.append((x, height_at(x, z) + GRID_LIFT_M, z))
        return pts

    x = x0
    while x <= x1 + 1e-6:
        add(along_z(x), "x")
        x += GRID_STEP_M
    z = z0
    while z <= z1 + 1e-6:
        add(along_x(z), "z")
        z += GRID_STEP_M
    if verts:
        out.append(_mesh("scale_grid", verts, faces, GRID_COLOR, roughness=0.9))
    return out


def _recipe_primitives(scene: Dict[str, Any], anchor: Vec2, radius: float,
                       style: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Plates and walls of the scene recipe near the spot.

    The geometry is the payload's, verbatim — a plate is its outline extruded
    by its own thickness, a wall is the box between its two end points. The
    context render does not own a second idea of what a room looks like.
    """
    from app.core.world_geometry import point_in_polygon

    out: List[Dict[str, Any]] = []
    floor = _hex_rgb(style.get("floor_color"), (0.85, 0.82, 0.76))
    wall = _hex_rgb(style.get("wall_color"), (0.81, 0.77, 0.70))
    for i, plate in enumerate(scene.get("plates") or []):
        outline = plate.get("outline") or []
        if len(outline) < 3:
            continue
        # A plate counts when it comes near the spot OR when the spot stands
        # ON it — the plate the target rests on is usually the one whose
        # corners are all outside the frame.
        near = any(_within(anchor, p, radius) for p in outline) \
            or point_in_polygon(anchor[0], anchor[1], outline)
        if not near:
            continue
        thickness = float(plate.get("thickness") or 0.0)
        if thickness <= 0:
            continue                       # texture-only surface (§ A5)
        verts, faces = _prism(outline, float(plate.get("top_y") or 0.0),
                              thickness)
        out.append(_mesh(f"plate_{i}", verts, faces, floor))
    for i, w in enumerate(scene.get("walls") or []):
        a = w.get("from") or [0, 0]
        b = w.get("to") or [0, 0]
        if _segment_distance(anchor[0], anchor[1], a, b) > radius:
            continue
        dx, dz = float(b[0]) - float(a[0]), float(b[1]) - float(a[1])
        length = math.hypot(dx, dz)
        if length <= 1e-3:
            continue
        height = float(w.get("height") or 0.0)
        if height <= 1e-3:
            continue
        base_y = float(w.get("base_y") or 0.0)
        centre = ((float(a[0]) + float(b[0])) / 2.0, base_y + height / 2.0,
                  (float(a[1]) + float(b[1])) / 2.0)
        # A wall runs from a to b; the box is built along local +x and then
        # yawed onto that direction. The map's yaw turns +x towards −z, so the
        # angle of (dx, dz) is atan2(−dz, dx).
        yaw = math.degrees(math.atan2(-dz, dx))
        verts = _box_vertices(centre, (length, height,
                                       float(w.get("thickness") or 0.07)), yaw)
        out.append(_mesh(f"wall_{i}", verts, _BOX_FACES, wall))
    return out


def _model_primitives(scene: Dict[str, Any], anchor: Vec2, radius: float,
                      res: Dict[str, Any],
                      model_files: Dict[str, str]) -> List[Dict[str, Any]]:
    """Stored meshes standing near the spot, as import + place() jobs.

    The TARGET's own model is left out: the plate has to show the spot EMPTY,
    or the edit stage is asked to add an object that is already there.

    ``place()`` (§ B2) is executed on the Blender side, but every angle it
    needs is prepared here: the MEASURING rotation (fix rounded to 90°, plus
    the yaw for ``yawed_xz``) and the DRAWING rotation (the real fix under the
    yaw), each as a quaternion in Blender's frame.
    """
    out: List[Dict[str, Any]] = []
    prop_seen: Dict[str, int] = {}
    for spec in scene.get("models") or []:
        role = str(spec.get("role") or "")
        room_id = str(spec.get("room_id") or "")
        idx = -1
        if role == "prop":
            idx = prop_seen.get(room_id, 0)
            prop_seen[room_id] = idx + 1
        exclude = res.get("exclude_model") or {}
        if exclude and role == exclude.get("role"):
            if role == "building" or (room_id == exclude.get("room_id")
                                      and idx == exclude.get("index")):
                continue
        key = _model_key(role, spec, room_id, idx)
        path = model_files.get(key)
        if not path:
            continue
        anchor_xz = spec.get("anchor") or [0, 0]
        if not _within(anchor, anchor_xz, radius):
            continue
        yaw = float(spec.get("yaw_deg") or 0.0)
        fix_draw = fix_matrix(spec.get("fix_euler"))
        fix_meas = fix_matrix(spec.get("fix_euler"), snap=True)
        measure = str(spec.get("measure") or "xyz")
        meas_rot = mat_mul(rot_y(yaw), fix_meas) if measure == "yawed_xz" \
            else fix_meas
        out.append({
            "kind": "model", "name": f"{role}_{key}",
            "slot": f"m{len(out)}", "source": path,
            "quat_measure": list(quaternion_of(mat_to_blender(meas_rot))),
            "quat_draw": list(quaternion_of(mat_to_blender(
                mat_mul(rot_y(yaw), fix_draw)))),
            "measure": measure,
            "max_m": float(spec.get("max_m") or 1.0),
            # Blender frame: X = scene x, Y = −scene z, Z = scene y.
            "anchor": [float(anchor_xz[0]), -float(anchor_xz[1])],
            "bottom_z": float(spec.get("bottom_y") or 0.0),
        })
    return out


def _model_key(role: str, spec: Dict[str, Any], room_id: str, idx: int) -> str:
    """The lookup key of one model spec in the ``model_files`` map."""
    if role == "building":
        return "building"
    if role == "room":
        return f"room:{room_id}"
    return f"prop:{room_id}:{idx}"


def _hex_rgb(value: Any, fallback: Vec3) -> Vec3:
    """``"#cfc4b2"`` -> linear-ish float RGB. The context plate is a lighting
    reference, not a colour-managed print, so the sRGB curve is approximated
    by the usual 2.2 gamma rather than the exact piecewise transfer."""
    text = str(value or "").strip().lstrip("#")
    if len(text) != 6:
        return fallback
    try:
        rgb = [int(text[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
    except ValueError:
        return fallback
    return tuple(round(c ** 2.2, 4) for c in rgb)          # type: ignore


# ── World-facing entry points ───────────────────────────────────────────

def _load_inputs(location_id: str, target: Dict[str, Any]):
    """Everything the composer needs, straight from the world DB and stores."""
    from app.core.location_model3d import derive_plan_width_m, get_client_meta
    from app.core.relief import scene_ground_lift
    from app.core.room_recipe import compose_recipe
    from app.core.scene_recipe import compose_scene
    from app.core.surface_textures import library_kinds
    from app.core.world_geometry import local_to_world
    from app.models.world import get_location_by_id

    loc = get_location_by_id(location_id)
    if not loc:
        raise ValueError(f"unknown location: {location_id}")
    rooms = [r for r in (loc.get("rooms") or []) if isinstance(r, dict)]
    room_metas: Dict[str, Dict[str, Any]] = {}
    for room in rooms:
        rid = str(room.get("id") or "")
        if not rid or not room.get("layout"):
            continue
        meta = get_client_meta(location_id, room_id=rid)
        if meta:
            room_metas[rid] = meta
    scene = compose_scene(
        loc, plan_width_m=derive_plan_width_m(location_id, loc.get("map3d") or {}),
        building_meta=get_client_meta(location_id) or {},
        room_metas=room_metas, surface_kinds=library_kinds())

    # The pin, read the way ``world_geometry.placed_boundary`` reads it.
    cx = float(loc.get("pos_x") or 0.0)
    cz = float(loc.get("pos_z") or 0.0)
    yaw = float(loc.get("yaw_deg") or 0.0)

    def height_at(lx: float, lz: float) -> float:
        wx, wz = local_to_world(lx, lz, cx, cz, yaw)
        return scene_ground_lift(loc, wx, wz)

    placements = None
    room_id = str(target.get("room_id") or "")
    if str(target.get("kind") or "prop") == "prop" and room_id:
        room = next((r for r in rooms if str(r.get("id") or "") == room_id), None)
        if room is None:
            raise ValueError(f"unknown room: {room_id}")
        recipe = compose_recipe(room, [r for r in rooms if r is not room],
                                variant_seed=int(loc.get("variant_seed") or 0),
                                map3d=loc.get("map3d") or {})
        if not recipe:
            raise ValueError(f"room {room_id} has no layout")
        placements = recipe.get("placements") or []

    model_files = _resolve_model_files(location_id, scene)
    loc = dict(loc)
    loc["_world_ground_y"] = _world_ground_y(cx, cz)
    return loc, scene, placements, height_at, model_files


def _world_ground_y(x: float, z: float) -> float:
    try:
        from app.core.world_geometry import ground_y
        return float(ground_y(x, z))
    except Exception:                      # pragma: no cover - no heightfield
        return 0.0


def _resolve_model_files(location_id: str,
                         scene: Dict[str, Any]) -> Dict[str, str]:
    """Payload model specs -> files on disk.

    The payload speaks URLs (it is a client contract); Blender needs paths, and
    the three roles keep their meshes in three different stores. A model that
    is missing is simply absent from the map — the render then shows the empty
    placement, which is the honest picture.
    """
    from app.core.location_model3d import find_building_model
    from app.core import props as prop_store

    out: Dict[str, str] = {}
    prop_seen: Dict[str, int] = {}
    for spec in scene.get("models") or []:
        role = str(spec.get("role") or "")
        room_id = str(spec.get("room_id") or "")
        path = None
        idx = -1
        if role == "building":
            path = find_building_model(location_id)
        elif role == "room":
            path = find_building_model(location_id, room_id=room_id)
        elif role == "prop":
            # The index counts EVERY prop placement of the room, mesh or not —
            # it is the same running number ``_model_primitives`` derives, and
            # the two must not drift apart.
            idx = prop_seen.get(room_id, 0)
            prop_seen[room_id] = idx + 1
            if spec.get("variants"):
                path = prop_store.model_path(str(spec.get("id") or ""),
                                             variant=_store_variant(spec))
        if path:
            out[_model_key(role, spec, room_id, idx)] = str(path)
    return out


def _store_variant(spec: Dict[str, Any]) -> Any:
    """The prop store's variant index behind a payload ``variant`` position.

    ``models[].variant`` is a POSITION in ``model_variants``; the STORE index
    is what the store keys its meshes by, and switching a variant off makes the
    two differ (§ B2 addendum). Position 0 is always the primary variant.
    """
    pos = int(spec.get("variant") or 0)
    if pos == 0:
        return None
    from app.core import props as prop_store
    entries = prop_store.active_variant_tiers(str(spec.get("id") or ""))
    if 0 <= pos < len(entries):
        return entries[pos].get("variant")
    return None


def render_context(location_id: str, target: Dict[str, Any],
                   out_dir: Any, *,
                   params: Optional[Dict[str, Any]] = None,
                   game: Any = None,
                   job: Optional[Dict[str, Any]] = None,
                   timeout_s: int = 0) -> Dict[str, Any]:
    """Render one context plate and return ``{"png", "sidecar", "job"}``.

    The Blender runner owns the process; everything travels through ONE JSON
    input file plus one slot per mesh to import, and the two results come back
    as declared outputs.
    """
    from app.blender import runner

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if job is None:
        job = build_context_scene(location_id, target, params=params, game=game)

    inputs: Dict[str, Path] = {}
    for prim in job.get("primitives") or []:
        if prim.get("kind") == "model" and prim.get("source"):
            src = Path(str(prim["source"]))
            if src.is_file():
                inputs[str(prim["slot"])] = src
    with tempfile.TemporaryDirectory(prefix="av-context-") as tmp:
        job_file = Path(tmp) / "job.json"
        job_file.write_text(json.dumps(job, ensure_ascii=False),
                            encoding="utf-8")
        inputs["job"] = job_file
        result = runner.run("scene_context", inputs=inputs, out_dir=out_dir,
                            timeout_s=timeout_s or _render_timeout())
    if not result.get("ok"):
        raise RuntimeError(f"context render failed: {result.get('error')}")
    outputs = result.get("outputs") or {}
    logger.info("Context render for %s (%s): %s", location_id,
                target.get("kind"), outputs.get("png"))
    return {"png": outputs.get("png", ""), "sidecar": outputs.get("sidecar", ""),
            "job": job, "data": result.get("data") or {},
            "seconds": result.get("seconds", 0.0)}


def _render_timeout() -> int:
    """A context plate is a real render — the mesh-refinement timeout (120 s)
    is the wrong order of magnitude for it."""
    try:
        from app.core import config
        val = config.get("image_generation.context_render_timeout_s", None)
        if val:
            return int(val)
    except Exception:
        pass
    return 600
