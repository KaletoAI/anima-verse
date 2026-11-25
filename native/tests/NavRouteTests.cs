using System;
using System.Collections.Generic;
using AnimaNative.Nav;
using AnimaNative.Overview;
using AnimaNative.Scatter;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>
/// <see cref="NavClamp"/>, <see cref="NavRoutePlanner"/> and <see cref="NavRoute"/> on <see cref="FakePathProvider"/>
/// worlds. Expectations derived by hand:
/// <code>
///   clamp: tol 0.02, eps 1e-4, distances horizontal; a Closest whose |dy| ≥ storeyHeight/2 counts as infinitely far
///     mesh x 0…10, z 0…10, hole x 4…6, z 4…6:
///       (5, 3.9) → (5, 4.1): dTo = 0.1 > tol, dFrom = 0, 0.1 > 0 + eps, dFrom ≤ tol → Closest(5, 4.1) = (5, 4.0)
///       (5, 4.5) → (5, 4.3): dFrom = 0.5 (to z 4 or z 6 … nearest edge z 4 at 0.5), dTo = 0.3 ≤ 0.5 → to
///       (5, 4.3) → (5, 4.6): dFrom = 0.3, dTo = 0.4 > 0.3 + eps, dFrom > tol → from
///       (5, 4.3) → (5.1, 4.3): both 0.3 (x edges are 0.9 / 1.1 away) → to
///   planner: on mesh = horizontal distance to Closest ≤ 0.3; unreachable = path end > 0.5 from the goal
///     furniture hole x 4…8, z 4…5.5, click (6, 4.6): edges z 4 at 0.6, z 5.5 at 0.9, x 4 / 8 at 2 → Goal (6, 0, 4)
///     outside doors (0, 5), (10, 5), from (2, 0, 5), target (−3, 0, 5): via (0, 5) = Query 2 + straight 3 = 5;
///       via (10, 5) = 8 + 13 = 21 → (0, 5) wins, Length 5
///   route: corners reached at &lt; 0.2 m horizontal, a link start at &lt; 0.4 m (3D); stuck = &lt; 0.05 m/s for 2 s:
///     standing still with dt 0.5 → ticks 1–3 None, tick 4 (2.0 s) Replan, ticks 5–7 None, tick 8 Abort
/// </code>
/// </summary>
public class NavRouteTests
{
    private const double Eps = 1e-9;

    private static FakePathProvider Room() => new FakePathProvider().Mesh(0, 0, 10, 10);

    private static void Same(P2 expected, P2 actual)
    {
        Assert.Equal(expected.X, actual.X, Eps);
        Assert.Equal(expected.Z, actual.Z, Eps);
    }

    private static void Same(Vec3 expected, Vec3 actual)
    {
        Assert.Equal(expected.X, actual.X, Eps);
        Assert.Equal(expected.Y, actual.Y, Eps);
        Assert.Equal(expected.Z, actual.Z, Eps);
    }

    private static bool AllInside(double x, double z) => true;

    private static bool InsideRoom(double x, double z) => x >= 0 && x <= 10 && z >= 0 && z <= 10;

    // ---- NavClamp -------------------------------------------------------------------------------------------------

    [Fact]
    public void OnMeshStepPassesThrough()
        => Same(new P2(5.2, 5), NavClamp.Step(new P2(5, 5), new P2(5.2, 5), 0, 3, Room()));

    [Fact]
    public void StepIntoObstacleSlidesToEdge()
        => Same(new P2(5, 4.0), NavClamp.Step(new P2(5, 3.9), new P2(5, 4.1), 0, 3, Room().Hole(4, 4, 6, 6)));

    [Fact]
    public void OffMeshStartMayApproachMesh()
        => Same(new P2(5, 4.3), NavClamp.Step(new P2(5, 4.5), new P2(5, 4.3), 0, 3, Room().Hole(4, 4, 6, 6)));

    [Fact]
    public void OffMeshStartMayNotGoDeeper()
        => Same(new P2(5, 4.3), NavClamp.Step(new P2(5, 4.3), new P2(5, 4.6), 0, 3, Room().Hole(4, 4, 6, 6)));

    [Fact]
    public void ParallelInsideObstacleIsStable()
        => Same(new P2(5.1, 4.3), NavClamp.Step(new P2(5, 4.3), new P2(5.1, 4.3), 0, 3, Room().Hole(4, 4, 6, 6)));

    [Fact]
    public void DeeperWithinEpsilonPasses()
        // dFrom = 0.3, dTo = 0.30005 ≤ 0.3 + 1e-4 → to
        => Same(new P2(5.1, 4.30005), NavClamp.Step(new P2(5, 4.3), new P2(5.1, 4.30005), 0, 3, Room().Hole(4, 4, 6, 6)));

    [Fact]
    public void DeeperBeyondEpsilonStays()
        // dFrom = 0.3, dTo = 0.3002 > 0.3 + 1e-4, dFrom > tol → from
        => Same(new P2(5, 4.3), NavClamp.Step(new P2(5, 4.3), new P2(5.1, 4.3002), 0, 3, Room().Hole(4, 4, 6, 6)));

    [Fact]
    public void OtherStoreyIsNotOnMesh()
    {
        // The mesh lies directly above (Closest.Y = y + 3, storey height 3 → |dy| = 3 ≥ 1.5): neither point counts.
        var upstairs = new FakePathProvider { ClosestYOffset = 3 }.Mesh(0, 0, 10, 10);
        Same(new P2(5, 5), NavClamp.Step(new P2(5, 5), new P2(5.2, 5), 0, 3, upstairs));
    }

    // ---- NavRoutePlanner ------------------------------------------------------------------------------------------

    private static readonly Vec3 A = new(1, 0, 1), B = new(3, 0, 1), L1 = new(5, 0, 1), L2 = new(5, 0, 5), C = new(9, 0, 9);

    private static NavPlan LinkPlan()
    {
        var nav = Room().Answer(A, C, new[] { A, B, L1, L2, C }, new ulong[] { 0, 0, 65536, 0, 0 }, 20);
        return NavRoutePlanner.Plan(nav, A, C, AllInside, Array.Empty<P2>(), 0)!;
    }

    [Fact]
    public void PlanSplitsAtLink()
    {
        var plan = LinkPlan();
        Assert.NotNull(plan);
        Assert.Equal(3, plan.Steps.Count);
        var w0 = Assert.IsType<NavWalk>(plan.Steps[0]);
        Assert.Equal(new[] { A, B, L1 }, w0.Points);
        var link = Assert.IsType<NavLink>(plan.Steps[1]);
        Assert.Equal(65536UL, link.Owner);
        Same(L1, link.Start);
        Same(L2, link.End);
        var w1 = Assert.IsType<NavWalk>(plan.Steps[2]);
        Assert.Equal(new[] { L2, C }, w1.Points);
        Same(C, plan.Goal);
        Assert.Equal(20, plan.Length, Eps);
    }

    [Fact]
    public void UnreachableReturnsNull()
    {
        var end = new Vec3(9, 0, 8.4); // 0.6 short of C
        var nav = Room().Answer(A, C, new[] { A, end }, new ulong[] { 0, 0 }, 10);
        Assert.Null(NavRoutePlanner.Plan(nav, A, C, AllInside, Array.Empty<P2>(), 0));
    }

    [Fact]
    public void ClickIntoFurnitureStopsAtEdge()
    {
        var nav = Room().Hole(4, 4, 8, 5.5);
        var plan = NavRoutePlanner.Plan(nav, A, new Vec3(6, 0, 4.6), AllInside, Array.Empty<P2>(), 0);
        Assert.NotNull(plan);
        var edge = new Vec3(6, 0, 4);
        Same(edge, plan!.Goal);
        Same(edge, nav.Queries[^1].To);
        var walk = Assert.IsType<NavWalk>(Assert.Single(plan.Steps));
        Same(edge, walk.Points[^1]);
        Assert.Equal(Math.Sqrt(5 * 5 + 3 * 3), plan.Length, Eps);
    }

    [Fact]
    public void OutsideTargetRoutesViaOutsideDoor()
    {
        var from = new Vec3(2, 0, 5);
        var door = new Vec3(0, 0, 5);
        var mid = new Vec3(1, 0, 5);
        var target = new Vec3(-3, 0, 5);
        var nav = Room().Answer(from, door, new[] { from, mid, door }, new ulong[] { 0, 0, 0 }, 2);
        var plan = NavRoutePlanner.Plan(nav, from, target, InsideRoom, new[] { new P2(0, 5), new P2(10, 5) }, 0);
        Assert.NotNull(plan);
        Same(target, plan!.Goal);
        Assert.Equal(5, plan.Length, Eps);
        var walk = Assert.IsType<NavWalk>(Assert.Single(plan.Steps));
        Assert.Equal(new[] { from, mid, door, target }, walk.Points);
    }

    [Fact]
    public void OutsideTargetWithoutDoorFallsBack()
        => Assert.Null(NavRoutePlanner.Plan(Room(), new Vec3(2, 0, 5), new Vec3(-3, 0, 5), InsideRoom, Array.Empty<P2>(), 0));

    [Fact]
    public void StartOutsideFootprintFallsBack()
        => Assert.Null(NavRoutePlanner.Plan(Room(), new Vec3(-3, 0, 5), new Vec3(2, 0, 5), InsideRoom, new[] { new P2(0, 5) }, 0));

    [Fact]
    public void SinglePointPathIsNoPlan()
    {
        // Query answers one point (start = goal): no section to follow → null, never a plan NavRoute rejects.
        var p = new Vec3(3, 0, 3);
        var nav = Room().Answer(p, p, new[] { p }, new ulong[] { 0 }, 0);
        Assert.Null(NavRoutePlanner.Plan(nav, p, p, AllInside, Array.Empty<P2>(), 0));
    }

    [Fact]
    public void StandingAtFurnitureEdgeIsNoPlan()
    {
        // Already at the edge (6, 4): Query(from, edge) answers the one point → null.
        var edge = new Vec3(6, 0, 4);
        var nav = Room().Hole(4, 4, 8, 5.5).Answer(edge, edge, new[] { edge }, new ulong[] { 0 }, 0);
        Assert.Null(NavRoutePlanner.Plan(nav, edge, new Vec3(6, 0, 4.6), AllInside, Array.Empty<P2>(), 0));
    }

    [Fact]
    public void OffMeshStartToMeshTargetQueriesFromStart()
    {
        // Start (5, 5) inside hole x 4…6, z 4…6 (1 m from the mesh), target (9, 9) on it → case 1 from the real start.
        var nav = Room().Hole(4, 4, 6, 6);
        var from = new Vec3(5, 0, 5);
        var plan = NavRoutePlanner.Plan(nav, from, C, AllInside, Array.Empty<P2>(), 0);
        Assert.NotNull(plan);
        Same(from, nav.Queries[^1].From);
        Same(C, plan!.Goal);
    }

    [Fact]
    public void BothOffMeshFallsBack()
    {
        var nav = Room().Hole(4, 4, 8, 8);
        Assert.Null(NavRoutePlanner.Plan(nav, new Vec3(5, 0, 5), new Vec3(7, 0, 7), AllInside, Array.Empty<P2>(), 0));
    }

    // ---- NavRoute -------------------------------------------------------------------------------------------------

    private static NavRoute Straight()
    {
        var nav = Room();
        var plan = NavRoutePlanner.Plan(nav, new Vec3(0, 0, 0), new Vec3(10, 0, 0), AllInside, Array.Empty<P2>(), 0)!;
        return new NavRoute(plan);
    }

    [Fact]
    public void StuckTwiceAborts()
    {
        var route = Straight();
        var still = new Vec3(0, 0, 0);
        var events = new List<NavRouteEvent>();
        for (int i = 0; i < 8; i++)
            events.Add(route.Tick(still, 0.5));
        Assert.Equal(new[]
        {
            NavRouteEvent.None, NavRouteEvent.None, NavRouteEvent.None, NavRouteEvent.Replan,
            NavRouteEvent.None, NavRouteEvent.None, NavRouteEvent.None, NavRouteEvent.Abort,
        }, events);
    }

    [Fact]
    public void MovingIsNotStuck()
    {
        var route = Straight();
        for (int i = 1; i <= 8; i++)
            Assert.Equal(NavRouteEvent.None, route.Tick(new Vec3(0.1 * i, 0, 0), 0.5)); // 0.2 m/s
    }

    [Fact]
    public void DeviationReplans()
    {
        var route = Straight();
        Assert.Equal(NavRouteEvent.None, route.Tick(new Vec3(4, 0, 0.9), 1));
        Assert.Equal(NavRouteEvent.Replan, route.Tick(new Vec3(5, 0, 1.2), 1));
    }

    [Fact]
    public void ArrivesAtGoal()
    {
        var route = Straight();
        Assert.Equal(NavRouteEvent.None, route.Tick(new Vec3(9.7, 0, 0), 1));
        Assert.False(route.Done);
        Assert.Equal(NavRouteEvent.Arrived, route.Tick(new Vec3(9.85, 0, 0), 1));
        Assert.True(route.Done);
    }

    [Fact]
    public void LinkWaitsForFinish()
    {
        var route = new NavRoute(LinkPlan());
        Same(B, route.Next!.Value);
        Same(C, route.Final);
        Assert.Equal(NavRouteEvent.None, route.Tick(B, 1));
        Same(L1, route.Next!.Value);
        Assert.Equal(NavRouteEvent.AtLink, route.Tick(new Vec3(4.7, 0, 1), 1)); // 0.3 from L1
        Assert.True(route.RideRequested);
        Assert.Null(route.Next);
        Assert.IsType<NavLink>(route.Current);
        route.LinkResult(true);
        for (int i = 0; i < 6; i++)
            Assert.Equal(NavRouteEvent.None, route.Tick(new Vec3(4.7, 0, 1), 1)); // waiting: no stuck, no deviation
        Assert.Null(route.Next);
        Assert.IsType<NavLink>(route.Current);
        route.LinkFinished();
        Assert.IsType<NavWalk>(route.Current);
        Same(C, route.Next!.Value);
        Same(C, route.Final);
        Assert.Equal(NavRouteEvent.None, route.Tick(L2, 1));
        Assert.Equal(NavRouteEvent.Arrived, route.Tick(C, 1));
        Assert.True(route.Done);
    }

    [Fact]
    public void ZeroFrameIsNeutralForStuck()
    {
        // 3 still ticks of 0.5 s (1.5 s), a dt 0 frame, then one more 0.5 s → 2.0 s → Replan.
        var route = Straight();
        var still = new Vec3(0, 0, 0);
        for (int i = 0; i < 3; i++)
            Assert.Equal(NavRouteEvent.None, route.Tick(still, 0.5));
        Assert.Equal(NavRouteEvent.None, route.Tick(still, 0));
        Assert.Equal(NavRouteEvent.Replan, route.Tick(still, 0.5));
    }

    [Fact]
    public void RidingIgnoresDeviationAndStuck()
    {
        // While riding, the avatar may be far from every walk segment (stairs go up/sideways) and slow.
        var route = new NavRoute(LinkPlan());
        route.Tick(B, 1);
        Assert.Equal(NavRouteEvent.AtLink, route.Tick(new Vec3(4.7, 0, 1), 1));
        route.LinkResult(true);
        Assert.Equal(NavRouteEvent.None, route.Tick(new Vec3(5, 2, 3), 1)); // 2 m off the A–L1 line
        for (int i = 0; i < 6; i++)
            Assert.Equal(NavRouteEvent.None, route.Tick(new Vec3(5, 2, 3), 1));
    }

    [Fact]
    public void LinkFirstRouteThatNeverReachesTheLinkAborts()
    {
        // Path [L1, L2, C] with the link on its first point: the leading one-point walk is dropped, the route starts
        // with Link(L1, L2). Standing still 4 m from L1 with dt 0.5: tick 1 sets the baseline, ticks 2–5 count
        // 0.5 s each → Replan at tick 5 (2 s), ticks 6–9 → Abort at tick 9.
        var nav = Room().Answer(A, C, new[] { L1, L2, C }, new ulong[] { 65536, 0, 0 }, 16);
        var route = new NavRoute(NavRoutePlanner.Plan(nav, A, C, AllInside, Array.Empty<P2>(), 0)!);
        Assert.IsType<NavLink>(route.Current);
        var events = new List<NavRouteEvent>();
        for (int i = 0; i < 9; i++)
            events.Add(route.Tick(A, 0.5));
        Assert.Equal(new[]
        {
            NavRouteEvent.None, NavRouteEvent.None, NavRouteEvent.None, NavRouteEvent.None, NavRouteEvent.Replan,
            NavRouteEvent.None, NavRouteEvent.None, NavRouteEvent.None, NavRouteEvent.Abort,
        }, events);
    }

    [Fact]
    public void LinkFirstRouteRequestsRideWhenClose()
    {
        var nav = Room().Answer(A, C, new[] { L1, L2, C }, new ulong[] { 65536, 0, 0 }, 16);
        var route = new NavRoute(NavRoutePlanner.Plan(nav, A, C, AllInside, Array.Empty<P2>(), 0)!);
        Assert.Equal(NavRouteEvent.AtLink, route.Tick(new Vec3(4.8, 0, 1), 1)); // 0.2 from L1
        Assert.True(route.RideRequested);
    }

    [Fact]
    public void LinkRejectedAborts()
    {
        var route = new NavRoute(LinkPlan());
        Assert.Equal(NavRouteEvent.None, route.Tick(B, 1));
        Assert.Equal(NavRouteEvent.AtLink, route.Tick(new Vec3(4.7, 0, 1), 1));
        route.LinkResult(false);
        Assert.Equal(NavRouteEvent.Abort, route.Tick(new Vec3(4.7, 0, 1), 1));
    }
}
