using System;
using System.Collections.Generic;
using AnimaNative.Embody;
using AnimaNative.Overview;
using AnimaNative.Scatter;
using AnimaNative.Scene;

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
            return Reaches(path, to) ? new NavPlan(Split(path.Points, path.Owners), to, path.Length) : null;
        }
        if (!fromOn)
            return null;
        if (!insideFootprint(to.X, to.Z))
            return ViaOutsideDoor(nav, from, to, outsideDoors, outsideY);
        var edge = nav.Closest(to);
        var toEdge = nav.Query(from, edge);
        return Reaches(toEdge, edge) ? new NavPlan(Split(toEdge.Points, toEdge.Owners), edge, toEdge.Length) : null;
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
            best = new NavPlan(Split(points, owners), to, length);
        }
        return best;
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

/// <summary>What one <see cref="NavRoute.Tick"/> asks of the caller.</summary>
public enum NavRouteEvent { None, AtLink, Replan, Abort, Arrived }

/// <summary>
/// Follows a <see cref="NavPlan"/> frame by frame: advances corners, hands links to the caller's ride and watches
/// for getting stuck (horizontal speed below <see cref="StuckSpeedMS"/> for <see cref="StuckSeconds"/> → Replan, the
/// second time Abort) and for drifting off the current segment (more than <see cref="DeviationM"/> → Replan). While a
/// link section runs, neither stuck time nor deviation counts.
/// </summary>
public sealed class NavRoute
{
    public const double StuckSpeedMS = 0.05, StuckSeconds = 2, DeviationM = 1;
    public const double CornerArriveM = ClickMove.GoalArriveM, LinkArriveM = Stairs.RideArriveM;

    private enum LinkState { None, Requested, Riding, Rejected }

    private readonly NavPlan _plan;
    private int _step, _corner = 1;
    private LinkState _link;
    private bool _aborted;
    private Vec3? _last;
    private double _stuckTime;
    private int _stuckCount;

    public NavRoute(NavPlan plan)
    {
        if (plan.Steps.Count == 0)
            throw new ArgumentException("a route needs at least one step", nameof(plan));
        _plan = plan;
        if (plan.Steps[0] is NavWalk w)
            _last = w.Points[0];
    }

    public NavStep Current => _plan.Steps[Math.Min(_step, _plan.Steps.Count - 1)];

    /// <summary>The next corner to walk to; null during a link section and once done.</summary>
    public Vec3? Next => !Done && Current is NavWalk w ? w.Points[_corner] : null;

    public Vec3 Final => _plan.Goal;

    public bool Done { get; private set; }

    /// <summary>Set by <see cref="NavRouteEvent.AtLink"/> until <see cref="LinkResult"/> answers.</summary>
    public bool RideRequested => _link == LinkState.Requested;

    public NavRouteEvent Tick(Vec3 pos, double dt)
    {
        if (Done)
            return NavRouteEvent.Arrived;
        if (_aborted || _link == LinkState.Rejected)
        {
            _aborted = true;
            return NavRouteEvent.Abort;
        }
        if (Current is NavLink link)
        {
            // A route that begins at a link (or has just walked onto it) asks for the ride once it is close.
            if (_link == LinkState.None && Distance3(pos, link.Start) < LinkArriveM)
            {
                _link = LinkState.Requested;
                return NavRouteEvent.AtLink;
            }
            _last = pos;
            return NavRouteEvent.None;
        }

        var walk = (NavWalk)Current;
        while (true)
        {
            bool last = _corner == walk.Points.Count - 1;
            bool linkNext = last && _step + 1 < _plan.Steps.Count && _plan.Steps[_step + 1] is NavLink;
            var corner = walk.Points[_corner];
            if (linkNext ? Distance3(pos, corner) >= LinkArriveM : NavRoutePlanner.Horizontal(pos, corner) >= CornerArriveM)
                break;
            if (!last)
            {
                _corner++;
                continue;
            }
            if (linkNext)
            {
                _step++;
                _link = LinkState.Requested;
                _stuckTime = 0;
                _last = pos;
                return NavRouteEvent.AtLink;
            }
            if (_step + 1 >= _plan.Steps.Count)
            {
                Done = true;
                return NavRouteEvent.Arrived;
            }
            // Two walks in a row cannot come out of the planner; continue on the next one anyway.
            _step++;
            _corner = 1;
            walk = (NavWalk)Current;
        }

        if (SegmentDistance(pos, walk.Points[_corner - 1], walk.Points[_corner]) > DeviationM)
        {
            _stuckTime = 0;
            _last = pos;
            return NavRouteEvent.Replan;
        }

        var before = _last;
        _last = pos;
        if (before is { } b && dt > 0 && NavRoutePlanner.Horizontal(pos, b) / dt < StuckSpeedMS)
        {
            _stuckTime += dt;
            if (_stuckTime >= StuckSeconds - 1e-9)
            {
                _stuckTime = 0;
                _stuckCount++;
                if (_stuckCount >= 2)
                {
                    _aborted = true;
                    return NavRouteEvent.Abort;
                }
                return NavRouteEvent.Replan;
            }
        }
        else
        {
            _stuckTime = 0;
        }
        return NavRouteEvent.None;
    }

    /// <summary>The caller's answer to <see cref="NavRouteEvent.AtLink"/>: did the ride start?</summary>
    public void LinkResult(bool started)
    {
        if (_link != LinkState.Requested)
            return;
        _link = started ? LinkState.Riding : LinkState.Rejected;
    }

    /// <summary>The ride has ended: continue with the section after the link.</summary>
    public void LinkFinished()
    {
        if (Current is not NavLink link || _link != LinkState.Riding)
            return;
        _link = LinkState.None;
        _stuckTime = 0;
        _last = link.End;
        _step++;
        _corner = 1;
        if (_step >= _plan.Steps.Count)
            Done = true;
    }

    private static double Distance3(Vec3 a, Vec3 b)
        => Math.Sqrt((a.X - b.X) * (a.X - b.X) + (a.Y - b.Y) * (a.Y - b.Y) + (a.Z - b.Z) * (a.Z - b.Z));

    /// <summary>Horizontal distance from <paramref name="p"/> to the segment a → b.</summary>
    private static double SegmentDistance(Vec3 p, Vec3 a, Vec3 b)
    {
        double ex = b.X - a.X, ez = b.Z - a.Z, len2 = ex * ex + ez * ez;
        double t = len2 < 1e-12 ? 0 : Math.Clamp(((p.X - a.X) * ex + (p.Z - a.Z) * ez) / len2, 0, 1);
        double dx = a.X + t * ex - p.X, dz = a.Z + t * ez - p.Z;
        return Math.Sqrt(dx * dx + dz * dz);
    }
}
