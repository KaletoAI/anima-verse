using System;
using System.Collections.Generic;
using AnimaNative.Nav;
using AnimaNative.Orders;
using AnimaNative.Overview;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>
/// The two clamp rules of <see cref="OrderWalk"/> that plan E3 Task 5 changed (review minor 1): the walk starts at
/// corner 0, so a start off the mesh walks onto the path at the order's speed (the server counts that piece too), and
/// a step that lands no further off the mesh than the figure already stood, plus <see cref="OrderWalk.ClampNoiseM"/>,
/// is not clamped. Speed 1 m/s, frames of 0.1 s; every expectation is derived by hand in the test.
/// </summary>
public class OrderWalkTests
{
    private const double Dt = 0.1;
    private static readonly IReadOnlyDictionary<string, ILinkRide> NoRides = new Dictionary<string, ILinkRide>();

    private static (double ArrivedS, List<WalkStep> Steps) WalkToEnd(OrderWalk walk, Vec3 start, IPathProvider nav, int maxSteps = 200)
    {
        var steps = new List<WalkStep>();
        var p = start;
        for (int i = 1; i <= maxSteps; i++)
        {
            var s = walk.Step(p, Dt, nav);
            steps.Add(s);
            p = s.Pos;
            if (s.Arrived) return (i * Dt - walk.LeftoverS, steps);
        }
        return (double.NaN, steps);
    }

    [Fact]
    public void AStartOffTheMeshIsWalkedOntoThePathNotPushedOnInOneFrame()
    {
        // Mesh x 0…10, z −1…1. The figure stands 0.2 m off its west edge at (−0.2, 0); the path starts on the edge.
        // Corner 0 first: the step goes to (−0.1, 0) — it lies 0.1 off the mesh, no further than the 0.2 the figure
        // stood, so it is not clamped. Length 0.2 + 5 = 5.2 m at 1 m/s → arrival at 5.2 s.
        // (Corner 1 first and the old clamp put the figure onto (0, 0) in the first frame: 5.1 s.)
        var nav = new FakePathProvider().Mesh(0, -1, 10, 1);
        var plan = new NavPlan(new NavStep[] { new NavWalk(new[] { new Vec3(0, 0, 0), new Vec3(5, 0, 0) }) }, new Vec3(5, 0, 0), 5);
        var walk = new OrderWalk(plan, new Vec3(5, 0, 0), 1.0, NoRides);
        var (arrived, steps) = WalkToEnd(walk, new Vec3(-0.2, 0, 0), nav);
        Assert.Equal(-0.1, steps[0].Pos.X, 9);
        Assert.Equal(5.2, arrived, 6);
        Assert.DoesNotContain(steps, s => s.NeedsReplan || s.Stuck);
    }

    [Fact]
    public void MeshEdgeNoiseBelowAMillimetreDoesNotBlock()
    {
        // The path runs along the mesh's north edge but its corners lie 0.5 mm outside it (z = 1.0005, float noise of
        // a boundary corner). Every step lands 0.5 mm off ≤ 0 + ClampNoiseM (1 mm): never clamped, never blocked, so no
        // replan after the 1 s blockade. Length 0.0005 (start → corner 0) + 5 = 5.0005 m → arrival at 5.0005 s.
        var nav = new FakePathProvider().Mesh(0, -1, 10, 1);
        var plan = new NavPlan(new NavStep[] { new NavWalk(new[] { new Vec3(0, 0, 1.0005), new Vec3(5, 0, 1.0005) }) },
                               new Vec3(5, 0, 1.0005), 5);
        var walk = new OrderWalk(plan, new Vec3(5, 0, 1.0005), 1.0, NoRides);
        var (arrived, steps) = WalkToEnd(walk, new Vec3(0, 0, 1.0), nav);
        Assert.Equal(5.0005, arrived, 6);
        Assert.DoesNotContain(steps, s => s.NeedsReplan || s.Stuck);
        Assert.Equal(1.0005, steps[^1].Pos.Z, 9);
    }

    [Fact]
    public void AStepThatLeavesTheMeshBeyondTheNoiseIsStillClamped()
    {
        // From (0, 0) towards (5, 1.2): the path leaves the mesh (z ≤ 1) at x = 5/1.2 = 4.1667. Each frame takes
        // 0.1 · 1.2 / √(5² + 1.2²) = 0.0233 m of z — far more than 1 mm beyond where the figure stood — so every step
        // past the edge is clamped back onto z = 1 (a blockade): z never exceeds 1, and the blockade asks for a replan.
        var nav = new FakePathProvider().Mesh(0, -1, 10, 1);
        var plan = new NavPlan(new NavStep[] { new NavWalk(new[] { new Vec3(0, 0, 0), new Vec3(5, 0, 1.2) }) }, new Vec3(5, 0, 1.2), 5.142);
        var walk = new OrderWalk(plan, new Vec3(5, 0, 1.2), 1.0, NoRides);
        var (_, steps) = WalkToEnd(walk, new Vec3(0, 0, 0), nav, maxSteps: 80);
        Assert.All(steps, s => Assert.True(s.Pos.Z <= 1 + 1e-9, $"z {s.Pos.Z}"));
        Assert.Contains(steps, s => s.NeedsReplan);
    }
}
