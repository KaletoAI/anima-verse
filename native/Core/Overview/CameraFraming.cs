namespace AnimaNative.Overview;

/// <summary>
/// Port of the zoom range and the pitch curve of client3d/src/scene/cameraFraming.ts — what the
/// camera FRAMES. The TS module keeps <c>basePitchDeg</c> apart from cameraMath.ts because the
/// embodied framing shares it; the C# split follows it so the next port (eye height, the
/// first-person lens) lands beside it. Vectors: shared/test-vectors/camera.json [3a..3h].
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
}
