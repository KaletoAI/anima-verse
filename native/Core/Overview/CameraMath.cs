using System;

namespace AnimaNative.Overview;

/// <summary>
/// A point or direction in world metres, double precision. Not <see cref="System.Numerics.Vector3"/>
/// (single precision: the camera vectors are checked to 1e-9) and not Godot's (the core is
/// Godot-free); the scene converts at its edge.
/// </summary>
public readonly record struct Vec3(double X, double Y, double Z);

/// <summary>The rectangle the server places the world in (<c>world_bounds</c>), in metres.</summary>
public readonly record struct BoundsXZ(double MinX, double MaxX, double MinZ, double MaxZ);

/// <summary>The result of one orbit drag: the yaw to ease to and the free pitch.</summary>
public readonly record struct OrbitState(double TargetYaw, double PitchOffset);

/// <summary>
/// Port of client3d/src/scene/cameraMath.ts — the OVERVIEW camera's arithmetic: the boot
/// framing of the world, the wheel zoom and its limits, the pull towards the cursor, the
/// per-frame easing, the fly-to curve, the orbit drag, the pitch limits and the lens pose.
/// Same operations in the same order as the TS, so the results agree to the last bit where
/// the platform's <c>Math</c> does. Vectors: shared/test-vectors/camera.json (hand derivations
/// in client3d/scripts/smoke_camera_math.mjs).
/// </summary>
public static class CameraMath
{
    /// <summary>The three.js clamp, <c>max(lo, min(hi, v))</c>: a <paramref name="lo"/> above
    /// <paramref name="hi"/> answers <paramref name="lo"/>, as <c>THREE.MathUtils.clamp</c> does.</summary>
    private static double Clamp(double v, double lo, double hi) => Math.Max(lo, Math.Min(hi, v));

    /// <summary><c>THREE.MathUtils.DEG2RAD</c>, spelled the same way.</summary>
    private const double Deg2Rad = Math.PI / 180;

    // ---- framing the world ----------------------------------------------------------------

    /// <summary>Half the vertical field of view of the map camera, in radians.</summary>
    public const double CameraHalfFov = (22.5 * Math.PI) / 180;
    /// <summary>Air around the bounds, as a factor on the fitted radius.</summary>
    public const double CameraFitMargin = 1.15;
    /// <summary>Fit distance for a world with nothing placed.</summary>
    public const double CameraFitEmpty = 70;

    /// <summary>Centre of <c>world_bounds</c> on the ground plane, or the origin when nothing is placed.</summary>
    public static (double X, double Z) WorldCentreXZ(BoundsXZ? b)
    {
        double x = b is BoundsXZ bx ? (bx.MinX + bx.MaxX) / 2 : 0;
        double z = b is BoundsXZ bz ? (bz.MinZ + bz.MaxZ) / 2 : 0;
        return (x, z);
    }

    /// <summary>
    /// Camera distance at which <c>world_bounds</c> fits the picture (bounding sphere over
    /// sin 22.5°, 15 % margin), clamped to [<see cref="CameraFraming.MinDist"/>,
    /// <see cref="CameraFraming.MaxDist"/>]; <see cref="CameraFitEmpty"/> without bounds or for a
    /// zero / non-finite radius.
    /// </summary>
    public static double FitDistance(BoundsXZ? b)
    {
        if (b is not BoundsXZ w) return CameraFitEmpty;
        double r = double.Hypot(w.MaxX - w.MinX, w.MaxZ - w.MinZ) / 2;
        if (!double.IsFinite(r) || r <= 0) return CameraFitEmpty;
        return Clamp((r * CameraFitMargin) / Math.Sin(CameraHalfFov), CameraFraming.MinDist, CameraFraming.MaxDist);
    }

    // ---- zoom --------------------------------------------------------------------------------

    /// <summary>Wheel sensitivity: a notch of deltaY 100 scales the distance by e^0.12.</summary>
    public const double WheelZoomRate = 0.0012;

    /// <summary>The zoom factor of one wheel event, <c>e^(deltaY · 0.0012)</c>.</summary>
    public static double WheelFactor(double deltaY) => Math.Exp(deltaY * WheelZoomRate);

    /// <summary>The highest distance the user may zoom to: the cap, never beyond MaxDist, never below the floor.</summary>
    public static double ZoomCeiling(double floor, double? cap)
        => Math.Max(floor, cap is double c ? Math.Min(c, CameraFraming.MaxDist) : CameraFraming.MaxDist);

    /// <summary>The lowest distance the camera may be set to: the floor, never below MinDist.</summary>
    public static double ZoomFloorOf(double? floor)
        => floor is double f ? Math.Max(f, CameraFraming.MinDist) : CameraFraming.MinDist;

    /// <summary>A wanted distance clamped into [floor, ceiling]; null = the engine's own limits.</summary>
    public static double ClampZoom(double dist, double? floor, double? cap)
    {
        double lo = ZoomFloorOf(floor);
        return Clamp(dist, lo, ZoomCeiling(lo, cap));
    }

    /// <summary>The distance one wheel event asks for: <c>ClampZoom(targetDist · WheelFactor(deltaY))</c>.</summary>
    public static double WheelZoom(double targetDist, double deltaY, double? floor, double? cap)
        => ClampZoom(targetDist * WheelFactor(deltaY), floor, cap);

    /// <summary>
    /// Zooming IN pulls the aim point towards the ground point <paramref name="hit"/> (on y = 0)
    /// by <c>1 − newDist / oldDist</c>; zooming out, standing still or a miss leaves it.
    /// </summary>
    public static Vec3 ZoomTowardCursor(Vec3 target, (double X, double Z)? hit, double oldDist, double newDist)
    {
        if (hit is not (double hx, double hz) || !(newDist < oldDist)) return target;
        double k = 1 - newDist / oldDist;
        return new Vec3(
            target.X + (hx - target.X) * k,
            target.Y + (0 - target.Y) * k,
            target.Z + (hz - target.Z) * k);
    }

    // ---- easing ------------------------------------------------------------------------------

    /// <summary>The longest frame step the camera eases over, in seconds.</summary>
    public const double MaxFrameDt = 0.1;

    /// <summary>The per-frame share of the remaining gap: <c>1 − e^(−8 · min(dt, 0.1))</c>.</summary>
    public static double Damp(double dt) => 1 - Math.Exp(-8 * Math.Min(dt, MaxFrameDt));

    /// <summary>How fast a fly-to runs through its curve, per second (0.625 s in all).</summary>
    public const double FlyRate = 1.6;

    /// <summary>The fly parameter after a frame of <paramref name="dt"/> seconds, stopping at 1.</summary>
    public static double FlyAdvance(double t, double dt) => Math.Min(1, t + dt * FlyRate);

    /// <summary>The fly-to curve: smoothstep <c>3t² − 2t³</c>.</summary>
    public static double FlyEase(double t) => t * t * (3 - 2 * t);

    // ---- orbit and pose ------------------------------------------------------------------------

    /// <summary>Radians of yaw per pixel of horizontal drag.</summary>
    public const double OrbitYawPerPx = 0.005;
    /// <summary>Degrees of free pitch per pixel of vertical drag.</summary>
    public const double OrbitPitchDegPerPx = 0.25;
    /// <summary>How far the free pitch may leave the base curve, in degrees.</summary>
    public const double PitchOffsetLimitDeg = 35;
    /// <summary>The same limit in first person.</summary>
    public const double FirstPersonPitchOffsetLimitDeg = 85;

    /// <summary>One orbit drag: dragging right lowers the yaw, dragging down raises the free pitch (clamped).</summary>
    public static OrbitState OrbitStep(double targetYaw, double pitchOffset, double dx, double dy, bool firstPerson = false)
    {
        double limit = firstPerson ? FirstPersonPitchOffsetLimitDeg : PitchOffsetLimitDeg;
        return new OrbitState(
            targetYaw - dx * OrbitYawPerPx,
            Clamp(pitchOffset + dy * OrbitPitchDegPerPx, -limit, limit));
    }

    /// <summary>The drawn pitch held in [8°, 85°]; in first person [−85°, 85°].</summary>
    public static double ClampPitchDeg(double deg, bool firstPerson = false) => Clamp(deg, firstPerson ? -85 : 8, 85);

    /// <summary>
    /// The unit vector from the target to the lens at <paramref name="yaw"/> (radians, 0 = camera
    /// on +Z) and <paramref name="pitchDeg"/> above the horizon. A struct return allocates
    /// nothing, so the TS <c>out</c> tuple has no C# counterpart.
    /// </summary>
    public static Vec3 OrbitOffset(double yaw, double pitchDeg)
    {
        double p = pitchDeg * Deg2Rad;
        return new Vec3(Math.Sin(yaw) * Math.Cos(p), Math.Sin(p), Math.Cos(yaw) * Math.Cos(p));
    }

    /// <summary>Where the lens stands: <c>target + OrbitOffset(yaw, pitchDeg) · dist</c> (the TS <c>{pos}</c>).</summary>
    public static Vec3 CameraPose(Vec3 target, double dist, double yaw, double pitchDeg)
    {
        var o = OrbitOffset(yaw, pitchDeg);
        return new Vec3(target.X + o.X * dist, target.Y + o.Y * dist, target.Z + o.Z * dist);
    }
}
