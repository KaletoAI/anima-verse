using System;
using AnimaNative.Overview;
using AnimaNative.Scatter;

namespace AnimaNative.Nav;

/// <summary>
/// The per-frame navmesh clamp of the avatar's step inside a building. All distances are horizontal: the mesh point
/// is asked straight below/above the point (<see cref="IPathProvider.ClosestOnVertical"/> over the band
/// <c>y ± storeyHeight / 2</c>), so a mesh whose few large polygons only meet the terrain at their corners never
/// counts a point standing above or below the polygon plane as "off the mesh" (final review E2, I-1). The answer only
/// counts when it lies on the avatar's own storey (<c>|c.Y − y| &lt; storeyHeight / 2</c>), otherwise the point is
/// infinitely far from the mesh — a mesh point directly above or below the avatar is not "on the mesh".
/// </summary>
public static class NavClamp
{
    /// <summary>A point this close to the mesh counts as on it.</summary>
    public const double OnMeshTolM = 0.02;

    /// <summary>"Not deeper" slack: keeps a walk parallel to an obstacle edge independent of float noise.</summary>
    public const double DeeperEpsM = 1e-4;

    /// <summary>
    /// The rule: <c>dTo ≤ tol</c> → <paramref name="to"/>; an infinite <c>dTo</c> → <paramref name="from"/> while
    /// <paramref name="from"/> stands on this storey's mesh, else <paramref name="to"/> (the clamp only holds an avatar
    /// that is on the mesh of its storey — one that is off every mesh of it is never frozen); <c>dTo ≤ dFrom + eps</c> →
    /// <paramref name="to"/> (back towards the mesh, or not deeper into the obstacle); else <c>dFrom ≤ tol</c> →
    /// <c>Closest(to)</c> (slides along the edge); else <paramref name="from"/>.
    /// </summary>
    public static P2 Step(P2 from, P2 to, double y, double storeyHeight, IPathProvider nav)
    {
        var (dTo, cTo) = Distance(to, y, storeyHeight, nav);
        if (dTo <= OnMeshTolM)
            return to;
        var (dFrom, _) = Distance(from, y, storeyHeight, nav);
        if (double.IsPositiveInfinity(dTo))
            return double.IsPositiveInfinity(dFrom) ? to : from;
        if (dTo <= dFrom + DeeperEpsM)
            return to;
        return dFrom <= OnMeshTolM ? cTo : from;
    }

    private static (double Dist, P2 Closest) Distance(P2 p, double y, double storeyHeight, IPathProvider nav)
    {
        double half = storeyHeight / 2;
        var c = nav.ClosestOnVertical(new Vec3(p.X, y, p.Z), half);
        if (!(Math.Abs(c.Y - y) < half))
            return (double.PositiveInfinity, p);
        return (Math.Sqrt((c.X - p.X) * (c.X - p.X) + (c.Z - p.Z) * (c.Z - p.Z)), new P2(c.X, c.Z));
    }
}
