using System;
using AnimaNative.Overview;
using AnimaNative.Scatter;

namespace AnimaNative.Nav;

/// <summary>
/// The per-frame navmesh clamp of the avatar's step inside a building. All distances are horizontal; the
/// provider's <see cref="IPathProvider.Closest"/> (3D, over all storeys) only counts when it lies on the avatar's own
/// storey (<c>|Closest.Y − y| &lt; storeyHeight / 2</c>), otherwise the point is infinitely far from the mesh — a mesh
/// point directly above or below the avatar is not "on the mesh".
/// </summary>
public static class NavClamp
{
    /// <summary>A point this close to the mesh counts as on it.</summary>
    public const double OnMeshTolM = 0.02;

    /// <summary>"Not deeper" slack: keeps a walk parallel to an obstacle edge independent of float noise.</summary>
    public const double DeeperEpsM = 1e-4;

    /// <summary>
    /// The rule: <c>dTo ≤ tol</c> → <paramref name="to"/>; <c>dTo ≤ dFrom + eps</c> → <paramref name="to"/> (back
    /// towards the mesh, or not deeper into the obstacle); else <c>dFrom ≤ tol</c> → <c>Closest(to)</c> (slides along
    /// the edge); else <paramref name="from"/>. A <paramref name="to"/> that is off every mesh of this storey never
    /// moves (an infinite <c>dTo</c> neither passes nor slides).
    /// </summary>
    public static P2 Step(P2 from, P2 to, double y, double storeyHeight, IPathProvider nav)
    {
        var (dTo, cTo) = Distance(to, y, storeyHeight, nav);
        if (dTo <= OnMeshTolM)
            return to;
        if (double.IsPositiveInfinity(dTo))
            return from;
        var (dFrom, _) = Distance(from, y, storeyHeight, nav);
        if (dTo <= dFrom + DeeperEpsM)
            return to;
        return dFrom <= OnMeshTolM ? cTo : from;
    }

    private static (double Dist, P2 Closest) Distance(P2 p, double y, double storeyHeight, IPathProvider nav)
    {
        var c = nav.Closest(new Vec3(p.X, y, p.Z));
        if (!(Math.Abs(c.Y - y) < storeyHeight / 2))
            return (double.PositiveInfinity, p);
        return (Math.Sqrt((c.X - p.X) * (c.X - p.X) + (c.Z - p.Z) * (c.Z - p.Z)), new P2(c.X, c.Z));
    }
}
