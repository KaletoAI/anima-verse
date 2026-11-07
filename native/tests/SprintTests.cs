using System.Collections.Generic;
using AnimaNative.Embody;
using AnimaNative.Figures;
using AnimaNative.Overview;
using AnimaNative.Scatter;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>
/// Shift runs the avatar — the C# half of client3d/scripts/smoke_locomotion_clip.mjs [4], the same hand-derived numbers.
/// <c>SprintHeld</c>: true only for 'shift' held AND a key direction. <c>NpcWalk.Step(..., sprint)</c> on a goal 1 m away
/// (dist 1 &lt; RunDistance 6) at dt 0.1, pace 1: walk 3.4 × 0.1 = 0.34 m, run 3.4 × 0.1 × 1.8 = 0.612 m; with the
/// 2.5× avatar factor 3.4 × 0.1 × 2.5 × 1.8 = 1.53 m, capped at the 1 m goal → 1. Swim and walk-only ground and
/// reckoning ignore the key (0.34), and the default (no sprint argument) is the old walk.
/// </summary>
public class SprintTests
{
    private static readonly P2 North = new(0, -1);

    [Fact]
    public void SprintNeedsShiftAndADirection()
    {
        Assert.True(Walk.SprintHeld(new HashSet<string> { "shift", "w" }, North));
        Assert.False(Walk.SprintHeld(new HashSet<string> { "w" }, North));
        Assert.False(Walk.SprintHeld(new HashSet<string> { "shift" }, null));
    }

    private static (bool Running, double Step) At(string movement, bool reckoning, double pace, bool sprint)
    {
        var plan = NpcWalk.Goal(new Vec3(0, 0, 0), new Vec3(1, 0, 0), new List<Vec3>());
        var r = NpcWalk.Step(plan, movement, reckoning, .1, pace, 1, null, sprint);
        return (r.Running, System.Math.Round(r.Step, 6));
    }

    [Fact]
    public void TheKeyRunsInsideRunDistanceWhereTheGroundAllows()
    {
        Assert.Equal(1.8, NpcWalk.RunFactor);
        Assert.Equal((false, .34), At("walk_run", false, 1, false));
        Assert.Equal((true, .612), At("walk_run", false, 1, true));
        Assert.Equal((true, 1.0), At("walk_run", false, 2.5, true));
        Assert.Equal((false, .34), At("swim", false, 1, true));
        Assert.Equal((false, .34), At("walk", false, 1, true));
        Assert.Equal((false, .34), At("walk_run", true, 1, true));
        var plan = NpcWalk.Goal(new Vec3(0, 0, 0), new Vec3(1, 0, 0), new List<Vec3>());
        var d = NpcWalk.Step(plan, "walk_run", false, .1, 1, 1);
        Assert.Equal((false, .34), (d.Running, System.Math.Round(d.Step, 6)));
    }
}
