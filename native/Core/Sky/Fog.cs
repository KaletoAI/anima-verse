namespace AnimaNative.Sky;

/// <summary>
/// The distance fog the browser draws (<c>client3d/src/scene/fogConstants.ts</c>): three's linear fog over
/// view-space depth, a smoothstep from 220 m to 520 m — the shared horizon of scene fog, minimap and tile prefetch.
/// </summary>
public static class Fog
{
    /// <summary><c>FOG_NEAR_M</c> / <c>FOG_FAR_M</c>.</summary>
    public const double NearM = 220, FarM = 520;

    /// <summary><c>fogFactor(depth)</c>: 0 up to the near edge, 1 from the far edge, smoothstep between.</summary>
    public static double Factor(double depth)
    {
        if (depth <= NearM) return 0;
        if (depth >= FarM) return 1;
        double t = (depth - NearM) / (FarM - NearM);
        return t * t * (3 - 2 * t);
    }
}
