using System;
using System.Collections.Generic;
using AnimaNative.Overview;
using AnimaNative.Scatter;

namespace AnimaNative.Nav;

/// <summary>One section of a planned route: a walk over corners or one off-mesh link (stairs, lift hop).</summary>
public abstract record NavStep;

/// <summary>Walk the corners in order; <c>Points[0]</c> is where the section starts.</summary>
public sealed record NavWalk(IReadOnlyList<Vec3> Points) : NavStep;

/// <summary>Ride the link <see cref="Owner"/> from <see cref="Start"/> to <see cref="End"/> (the client's ride owns it).</summary>
public sealed record NavLink(ulong Owner, Vec3 Start, Vec3 End) : NavStep;

/// <summary>A route: its sections, the goal it ends at and its length in metres.</summary>
public sealed record NavPlan(IReadOnlyList<NavStep> Steps, Vec3 Goal, double Length);

/// <summary>
/// Plans a click walk inside a building over the navigation map. A <c>null</c> plan means "no navmesh route": the
/// caller keeps today's straight walk (with its <c>Blocked</c>/<c>PlayerBlocked</c> checks).
/// </summary>
public static class NavRoutePlanner
{
    /// <summary>A point within this horizontal distance of the mesh counts as on it.</summary>
    public const double OnMeshM = 0.3;

    /// <summary>A path that ends farther than this from its goal did not reach it.</summary>
    public const double UnreachableM = 0.5;

    /// <summary>
    /// A closest point more than this far above or below counts as another storey (half a standard 3 m storey;
    /// the planner is not given the scene's storey height).
    /// </summary>
    private const double OtherStoreyM = 1.5;

    /// <summary>
    /// Cases: (1) target on the mesh → <c>Query(from, to)</c>, <c>null</c> when it ends more than
    /// <see cref="UnreachableM"/> short; (2) start on the mesh, target outside the footprint → the shortest
    /// <c>Query(from, door)</c> + straight door → target over all reachable outside doors, <c>null</c> without one;
    /// (3) start on the mesh, target inside the footprint but off the mesh (furniture) → walk to <c>Closest(to)</c>,
    /// which becomes the goal; (4) start outside the footprint → <c>null</c>; (5) both off the mesh → <c>null</c>.
    /// A start inside the footprint but off the mesh with a target on the mesh is case 1 (the map snaps the start).
    /// A path without a single section (one point: start = goal, or already standing at the furniture edge) is
    /// <c>null</c> too, so the planner never hands a walk (<see cref="AnimaNative.Orders.OrderWalk"/>) a plan without a section; the caller's straight
    /// walk arrives at once. In case 1 the goal stays the clicked point even when the path ends up to
    /// <see cref="UnreachableM"/> short of it: the route reports <c>Arrived</c> at its last corner.
    /// </summary>
    public static NavPlan? Plan(IPathProvider nav, Vec3 from, Vec3 to, Func<double, double, bool> insideFootprint,
                                IReadOnlyList<P2> outsideDoors, double outsideY)
    {
        if (!insideFootprint(from.X, from.Z))
            return null;
        bool fromOn = OnMesh(nav, from), toOn = OnMesh(nav, to);
        if (toOn)
        {
            var path = nav.Query(from, to);
            return Reaches(path, to) ? Make(path.Points, path.Owners, to, path.Length) : null;
        }
        if (!fromOn)
            return null;
        if (!insideFootprint(to.X, to.Z))
            return ViaOutsideDoor(nav, from, to, outsideDoors, outsideY);
        var edge = nav.Closest(to);
        if (!(Math.Abs(edge.Y - to.Y) < OtherStoreyM))
            return null; // the nearest mesh point lies on another storey
        var toEdge = nav.Query(from, edge);
        return Reaches(toEdge, edge) ? Make(toEdge.Points, toEdge.Owners, edge, toEdge.Length) : null;
    }

    private static NavPlan? ViaOutsideDoor(IPathProvider nav, Vec3 from, Vec3 to, IReadOnlyList<P2> doors, double outsideY)
    {
        NavPlan? best = null;
        foreach (var d in doors)
        {
            var door = new Vec3(d.X, outsideY, d.Z);
            var path = nav.Query(from, door);
            if (!Reaches(path, door))
                continue;
            double length = path.Length + Horizontal(door, to);
            if (best is not null && length >= best.Length)
                continue;
            var points = new List<Vec3>(path.Points) { to };
            var owners = new List<ulong>(path.Owners) { 0 };
            best = Make(points, owners, to, length) ?? best;
        }
        return best;
    }

    /// <summary>A plan of the path's sections, or null when the path has none (a route needs at least one).</summary>
    private static NavPlan? Make(IReadOnlyList<Vec3> points, IReadOnlyList<ulong> owners, Vec3 goal, double length)
    {
        var steps = Split(points, owners);
        return steps.Count == 0 ? null : new NavPlan(steps, goal, length);
    }

    private static bool OnMesh(IPathProvider nav, Vec3 p)
    {
        var c = nav.Closest(p);
        return Math.Abs(c.Y - p.Y) < OtherStoreyM && Horizontal(c, p) <= OnMeshM;
    }

    private static bool Reaches(NavPath path, Vec3 goal)
        => path.Points.Count > 0 && Horizontal(path.Points[^1], goal) <= UnreachableM;

    internal static double Horizontal(Vec3 a, Vec3 b) => Math.Sqrt((a.X - b.X) * (a.X - b.X) + (a.Z - b.Z) * (a.Z - b.Z));

    /// <summary>
    /// Cuts a path at its link points: <c>Owners[i] ≠ 0</c> closes the walk at <c>Points[i]</c>, emits
    /// <c>NavLink(Owners[i], Points[i], Points[i + 1])</c> and starts the next walk at <c>Points[i + 1]</c>.
    /// A walk of a single point (a path that starts or ends on a link) is dropped.
    /// </summary>
    private static List<NavStep> Split(IReadOnlyList<Vec3> points, IReadOnlyList<ulong> owners)
    {
        var steps = new List<NavStep>();
        var walk = new List<Vec3>();
        for (int i = 0; i < points.Count; i++)
        {
            walk.Add(points[i]);
            ulong owner = i < owners.Count ? owners[i] : 0;
            if (owner == 0 || i + 1 >= points.Count)
                continue;
            if (walk.Count >= 2)
                steps.Add(new NavWalk(walk));
            steps.Add(new NavLink(owner, points[i], points[i + 1]));
            walk = new List<Vec3>();
        }
        if (walk.Count >= 2)
            steps.Add(new NavWalk(walk));
        return steps;
    }
}
