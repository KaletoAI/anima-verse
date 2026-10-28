namespace AnimaNative.Overview;

/// <summary>
/// Port of client3d/src/scene/cameraFraming.ts — zoom ranges, pitch curve, eye point and view/body yaw.
/// Task 47 (E7-T2) completes the embodied framing beside the overview curve so both modes use the same
/// arithmetic; the caller owns camera placement and the FirstPersonZoom instance. Vectors: camera.json.
/// </summary>
public static class CameraFraming
{
    /// <summary>Closest the camera may get to its target (metres).</summary>
    public const double MinDist = 0.8;
    /// <summary>Furthest the camera may get from its target (metres).</summary>
    public const double MaxDist = 150;
    /// <summary>Pitch at the near end of the zoom in the overview (degrees).</summary>
    public const double OverviewNearPitchDeg = 18;
    /// <summary>Pitch at the far end of the zoom, shared by both modes (degrees).</summary>
    public const double FarPitchDeg = 62;
    /// <summary>Pitch at the near end while embodied (degrees).</summary>
    public const double EmbodyNearPitchDeg = 8;

    /// <summary>The cameraFraming.ts clamp, <c>v &lt; lo ? lo : v &gt; hi ? hi : v</c>.</summary>
    private static double Clamp(double v, double lo, double hi) => v < lo ? lo : v > hi ? hi : v;

    /// <summary>
    /// How steeply the camera looks down at <paramref name="dist"/>, in degrees, before the free
    /// pitch is added: <c>near + (62 − near) · √zoomK</c>, zoomK normalised against
    /// <see cref="MinDist"/>..<see cref="MaxDist"/> and clamped to [0, 1].
    /// </summary>
    public static double BasePitchDeg(double dist, double nearPitchDeg = OverviewNearPitchDeg)
    {
        double zoomK = Clamp((dist - MinDist) / (MaxDist - MinDist), 0, 1);
        return nearPitchDeg + (FarPitchDeg - nearPitchDeg) * System.Math.Sqrt(zoomK);
    }
    /// <summary>Task 47 (E7-T2): cameraFraming.ts embodied framing constants; camera.json.</summary>
    public const double EmbodyMinDist = MinDist, ThirdPersonMinDist = 2, EyeFraction = 0.94,
                        EyeHeadFraction = 0.45, EyeForwardFraction = 0.055, BodyTurnDeg = 60;

    public static double EyeHeight(double heightM) => heightM * EyeFraction;

    /// <summary>Rest eye point in the figure's own +Z frame; absent crown falls back to standing eye height.</summary>
    public static Vec3 RestEyePoint(Vec3 head, Vec3? crown, double heightM)
        => new(head.X, crown is Vec3 c ? head.Y + (c.Y - head.Y) * EyeHeadFraction : EyeHeight(heightM),
               head.Z + heightM * EyeForwardFraction);

    public static double ViewHeading(double cameraYaw) => System.Math.Atan2(-System.Math.Sin(cameraYaw), -System.Math.Cos(cameraYaw));

    /// <summary>Strictly past the wrapped threshold, turn the standing body to the unwrapped view yaw.</summary>
    public static double? BodyYawForView(double bodyYaw, double viewYaw, double thresholdDeg = BodyTurnDeg)
    {
        double d = (viewYaw - bodyYaw) % (System.Math.PI * 2);
        if (d > System.Math.PI) d -= System.Math.PI * 2;
        if (d < -System.Math.PI) d += System.Math.PI * 2;
        return System.Math.Abs(d) > thresholdDeg * System.Math.PI / 180 ? viewYaw : null;
    }
}

/// <summary>Task 47 (E7-T2): cameraFraming.ts continuous 180ms zoom hysteresis (1.2m enter, 1.8m leave), camera.json.</summary>
public sealed class FirstPersonZoom
{
    public bool Active { get; private set; }
    private double _pendingSeconds;

    public bool Update(double distance, bool enabled, double dt)
    {
        if (!enabled) { Active = false; _pendingSeconds = 0; return false; }
        bool switching = Active ? distance >= 1.8 : distance <= 1.2;
        if (!switching) { _pendingSeconds = 0; return Active; }
        _pendingSeconds += dt;
        if (_pendingSeconds >= 0.18 - 1e-9) { Active = !Active; _pendingSeconds = 0; }
        return Active;
    }
}
