using System;
using System.Collections.Generic;
using AnimaNative.Nav;
using AnimaNative.Orders;
using AnimaNative.Overview;
using AnimaNative.Scatter;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>
/// <see cref="AvoidanceClamp"/> and the avoidance input of <see cref="OrderWalk"/> (plan E3 Task 11) on
/// <see cref="FakePathProvider"/> worlds. Expectations derived by hand:
/// <code>
///   clamp = NavClamp.Step (tol 0.02, eps 1e-4, horizontal distances), then the walls; the final piece is never clamped
///     mesh x 0…10, z 0…10:
///       (5, 9.9) → (5.3, 10.2): dTo = 0.2 (closest (5.3, 10)) &gt; tol, dFrom = 0 → slides onto the edge (5.3, 10.0)
///       the same as the final piece: (5.3, 10.2) unchanged, the walls are not asked
///     hole x 4…6, z 4…6 (eroded furniture):
///       (3.9, 5) → (4.1, 5.2): dTo = 0.1 (closest (4, 5.2) on the edge x 4) &gt; tol, dFrom = 0 → (4.0, 5.2): it glides
///       along the furniture's edge instead of stopping
///     walls after the mesh: (5, 5) → (5.2, 5) stays on the mesh, a wall at x 5.1 (walls = min(x, 5.1)) → (5.1, 5)
///   radius: mixamo 0.25; generic 1.2 × 0.5 → 0.6; generic without a footprint (0 × 0) → 0.25
///   the walk (Dt 0.1, 1 m/s, path (1, 5) → (9, 5) on mesh x 0…10, z 0…10):
///     step 1 without an answer: (1.1, 5), desired (1, 0)
///     step 2 with the answer desired (1, 0) → safe (0.6, 0.8): path step (1.2, 5) + (−0.4, 0.8)·0.1 = (1.16, 5.08);
///       desired stays the path's (1, 0)
///     an answer equal to its desired velocity changes nothing: (1.2, 5)
///   gait clip rate = speed / 1.4 within [0.25, 3]: 1.4 → 1, 0.7 → 0.5, 0.1 → 0.25, 10 → 3
///   along the north edge (path (1, 9.95) → (9, 9.95)): the answer desired (1, 0) → safe (0, 1) gives (1.1, 9.95) +
///     (−1, 1)·0.1 = (1.0, 10.05), 0.05 off the mesh → clamped onto (1.0, 10.0)
/// </code>
/// </summary>
public class AvoidanceClampTests
{
    private const double Eps = 1e-9;
    private const double Dt = 0.1;
    private static readonly IReadOnlyDictionary<string, ILinkRide> NoRides = new Dictionary<string, ILinkRide>();
    private static readonly Func<P2, P2, P2> NoWalls = (_, to) => to;

    private static FakePathProvider Room() => new FakePathProvider().Mesh(0, 0, 10, 10);

    private static void Same(P2 expected, P2 actual)
    {
        Assert.Equal(expected.X, actual.X, Eps);
        Assert.Equal(expected.Z, actual.Z, Eps);
    }

    [Fact]
    public void ASafeVelocityIntoAWallKeepsThePointOnTheMesh()
        => Same(new P2(5.3, 10.0), AvoidanceClamp.Step(new P2(5, 9.9), new P2(5.3, 10.2), 0, 3, Room(), NoWalls, false));

    [Fact]
    public void TheFinalPieceIsNotClamped()
    {
        bool asked = false;
        var got = AvoidanceClamp.Step(new P2(5, 9.9), new P2(5.3, 10.2), 0, 3, Room(), (_, to) => { asked = true; return to; }, true);
        Same(new P2(5.3, 10.2), got);
        Assert.False(asked);
    }

    [Fact]
    public void ATargetInsideFurnitureGlidesAlongItsEdge()
        => Same(new P2(4.0, 5.2), AvoidanceClamp.Step(new P2(3.9, 5), new P2(4.1, 5.2), 0, 3, Room().Hole(4, 4, 6, 6), NoWalls, false));

    [Fact]
    public void TheWallsClampAfterTheMesh()
    {
        P2? seenFrom = null;
        var got = AvoidanceClamp.Step(new P2(5, 5), new P2(5.2, 5), 0, 3, Room(),
                                      (from, to) => { seenFrom = from; return new P2(Math.Min(to.X, 5.1), to.Z); }, false);
        Same(new P2(5.1, 5), got);
        Same(new P2(5, 5), seenFrom!.Value);
    }

    [Fact]
    public void WithoutAMapOnlyTheWallsClamp()
        => Same(new P2(5.1, 12), AvoidanceClamp.Step(new P2(5, 9.9), new P2(5.3, 12), 0, 3, null, (_, to) => new P2(Math.Min(to.X, 5.1), to.Z), false));

    [Theory]
    [InlineData("mixamo", 1.2, 0.5, 0.25)]
    [InlineData("generic", 1.2, 0.5, 0.6)]
    [InlineData("generic", 0.3, 0.4, 0.2)]
    [InlineData("generic", 0, 0, 0.25)]
    public void Radius(string rig, double w, double d, double want)
        => Assert.Equal(want, AvoidanceClamp.RadiusOf(rig, w, d), Eps);

    [Theory]
    [InlineData(OrderState.Walk, false, AvoidanceMode.Moving)]
    [InlineData(OrderState.Walk, true, AvoidanceMode.Static)]
    [InlineData(OrderState.WaitAccess, false, AvoidanceMode.Static)]
    [InlineData(OrderState.Loop, false, AvoidanceMode.Static)]
    [InlineData(OrderState.Exit, false, AvoidanceMode.Off)]
    [InlineData(OrderState.Entry, false, AvoidanceMode.Off)]
    [InlineData(OrderState.Idle, false, AvoidanceMode.None)]
    [InlineData(OrderState.Abort, false, AvoidanceMode.None)]
    public void Modes(OrderState state, bool frozen, AvoidanceMode want)
        => Assert.Equal(want, AvoidanceClamp.ModeOf(state, frozen));

    [Theory]
    [InlineData(1.4, 1.0)]
    [InlineData(0.7, 0.5)]
    [InlineData(0.1, 0.25)]
    [InlineData(10, 3.0)]
    public void GaitClipRate(double speed, double want)
        => Assert.Equal(want, OrderWalk.ClipRate(speed), Eps);

    private static OrderWalk Walk(double z)
    {
        var plan = new NavPlan(new NavStep[] { new NavWalk(new[] { new Vec3(1, 0, z), new Vec3(9, 0, z) }) }, new Vec3(9, 0, z), 8);
        return new OrderWalk(plan, new Vec3(9, 0, z), 1.0, NoRides);
    }

    [Fact]
    public void TheWalkAddsTheAvoidancesChangeOfVelocityToItsStep()
    {
        var walk = Walk(5);
        var s1 = walk.Step(new Vec3(1, 0, 5), Dt, Room());
        Same(new P2(1.1, 5), new P2(s1.Pos.X, s1.Pos.Z));
        Same(new P2(1, 0), walk.DesiredVelocity);
        walk.Avoidance = (new P2(1, 0), new P2(0.6, 0.8));
        var s2 = walk.Step(s1.Pos, Dt, Room());
        Same(new P2(1.16, 5.08), new P2(s2.Pos.X, s2.Pos.Z));
        Same(new P2(1, 0), walk.DesiredVelocity);
        Assert.Null(walk.Avoidance);
    }

    [Fact]
    public void AnAnswerEqualToItsDesiredVelocityChangesNothing()
    {
        var walk = Walk(5);
        var s1 = walk.Step(new Vec3(1, 0, 5), Dt, Room());
        walk.Avoidance = (new P2(1, 0), new P2(1, 0));
        var s2 = walk.Step(s1.Pos, Dt, Room());
        Same(new P2(1.2, 5), new P2(s2.Pos.X, s2.Pos.Z));
    }

    [Fact]
    public void AnAvoidedStepOffTheMeshIsClampedBack()
    {
        var walk = Walk(9.95);
        walk.Avoidance = (new P2(1, 0), new P2(0, 1));
        var s = walk.Step(new Vec3(1, 0, 9.95), Dt, Room());
        Same(new P2(1.0, 10.0), new P2(s.Pos.X, s.Pos.Z));
    }
}
