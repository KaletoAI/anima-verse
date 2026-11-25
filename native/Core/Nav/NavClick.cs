using System;
using AnimaNative.Overview;
using AnimaNative.Scatter;

namespace AnimaNative.Nav;

/// <summary>
/// The avatar's ground click (plan 2026-11-25-client-ausfuehrung-e2, Task 6): where a view ray meets a floor plane or
/// the ground. The ray direction need not be normalised — the hit point does not depend on its length.
/// Hand derivations: tests/NavClickTests.cs.
/// </summary>
public static class NavClick
{
    /// <summary>
    /// The ray <c>origin + t·dir</c> cut with the plane <c>y = planeY</c>: <c>t = (planeY − origin.Y) / dir.Y</c>.
    /// <c>null</c> when the ray does not point down (<c>dir.Y ≥ −1e-6</c>) or the plane lies behind it (<c>t ≤ 0</c>).
    /// </summary>
    public static P2? FloorHit(Vec3 origin, Vec3 dir, double planeY)
    {
        if (!(dir.Y < -1e-6))
            return null;
        double t = (planeY - origin.Y) / dir.Y;
        if (!(t > 0))
            return null;
        return new P2(origin.X + t * dir.X, origin.Z + t * dir.Z);
    }

    /// <summary>
    /// Two cuts (review N-W5): first the plane <c>y = firstY</c> (h1), then the plane at the ground height under h1,
    /// <c>groundAt(h1.X, h1.Z)</c>. <c>null</c> when either cut is <c>null</c>. On flat ground equal to
    /// <c>FloorHit(groundAt)</c>; on a slope one correction step towards the true intersection.
    /// </summary>
    public static P2? GroundHit(Vec3 origin, Vec3 dir, double firstY, Func<double, double, double> groundAt)
    {
        if (FloorHit(origin, dir, firstY) is not { } h1)
            return null;
        return FloorHit(origin, dir, groundAt(h1.X, h1.Z));
    }
}
