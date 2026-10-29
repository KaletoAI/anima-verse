using System;
using System.Text.Json;
using AnimaNative.Overview;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>
/// <see cref="OverviewControl"/> — the input rules of engine.ts (bindInput + the camera half of frame())
/// with numbers derived BY HAND below each case (not recorded from the code). The ground hits are given
/// directly, so these cases test the rules, not a ray; the Godot side (rays, frustum shift, synthetic
/// input) is checked headless in native/Check/OverviewCheck.cs.
/// </summary>
public class OverviewControlTests
{
    private const double Eps = 1e-12;

    private static OverviewControl At(double x, double y, double z, double dist, double yaw = 0)
    {
        var c = new OverviewControl();
        c.JumpTo(new Vec3(x, y, z), dist);
        c.Yaw = c.TargetYaw = yaw;
        return c;
    }

    [Fact]
    public void StartsLikeTheEngine()
    {
        // engine.ts: target (0,0,0), dist = targetDist = 80, yaw = targetYaw = π/4, pitchOffset 0.
        var c = new OverviewControl();
        Assert.Equal(new Vec3(0, 0, 0), c.Target);
        Assert.Equal(80, c.Dist);
        Assert.Equal(80, c.TargetDist);
        Assert.Equal(Math.PI / 4, c.Yaw);
        Assert.Equal(Math.PI / 4, c.TargetYaw);
        Assert.Equal(0, c.PitchOffset);
    }

    [Fact]
    public void WheelInPullsTowardsTheCursorOutDoesNot()
    {
        // In: deltaY −100 → targetDist 10·e^−0.12 = 8.869204367171575; k = 1 − e^−0.12 = 0.11307956328284252,
        // target (0,2,0) → hit (10,·,−20) by k: (1.1307956…, 2 − 2k = 1.773840873…, −2.2615912…).
        var c = At(0, 2, 0, 10);
        int asked = 0;
        c.Wheel(-100, () => { asked++; return new Vec3(10, 0, -20); });
        double k = 1 - Math.Exp(-0.12);
        Assert.Equal(1, asked);
        Assert.Equal(8.869204367171575, c.TargetDist, 12);
        Assert.Equal(10 * k, c.Target.X, 12);
        Assert.Equal(2 - 2 * k, c.Target.Y, 12);
        Assert.Equal(-20 * k, c.Target.Z, 12);

        // Out: +100 → 10·e^0.12; the target stays and the hit is never asked for.
        var o = At(0, 2, 0, 10);
        o.Wheel(100, () => { asked++; return new Vec3(10, 0, -20); });
        Assert.Equal(1, asked);
        Assert.Equal(10 * Math.Exp(0.12), o.TargetDist, 12);
        Assert.Equal(new Vec3(0, 2, 0), o.Target);
    }

    [Fact]
    public void WheelClampsAtTheLensLimits()
    {
        // 149·e^0.12 > 150 → 150; 0.85·e^−0.12 = 0.7539 < 0.8 → 0.8 (and the pull uses 1 − 0.8/0.85).
        var c = At(0, 0, 0, 149);
        c.Wheel(100, () => null);
        Assert.Equal(150, c.TargetDist);
        var n = At(0, 0, 0, 0.85);
        n.Wheel(-100, () => new Vec3(1, 0, 0));
        Assert.Equal(0.8, n.TargetDist);
        Assert.Equal(1 - 0.8 / 0.85, n.Target.X, 12);
    }

    [Fact]
    public void BareLeftDragOrbitsWithoutPanningOrGroundHit()
    {
        var c = At(1, 2, 3, 20);
        c.PointerDown(PointerButton.Left, 100, 100);
        Assert.False(c.PointerMove(104, 100));
        Assert.Equal(-.02, c.TargetYaw, 12);
        Assert.Equal(new Vec3(1, 2, 3), c.Target);
        Assert.True(c.PointerUp(PointerButton.Left)); // exactly 4 px still picks
        c.PointerDown(PointerButton.Left, 100, 100);
        c.PointerMove(103, 104);
        c.PointerMove(100, 100); // returning never turns a drag back into a click
        Assert.Equal(new Vec3(1, 2, 3), c.Target);
        Assert.False(c.PointerUp(PointerButton.Left));
    }

    [Fact]
    public void OrbitTurnsOnTheFirstPixelAndClicksUnderFourPixels()
    {
        // Left orbits: 3 px right → targetYaw −0.015 rad, 2 px down → pitchOffset +0.5°. hypot(3,2) ≤ 4 → click.
        var c = At(0, 0, 0, 20);
        c.PointerDown(PointerButton.Left, 10, 10);
        Assert.False(c.PointerMove(13, 12));
        Assert.Equal(-0.015, c.TargetYaw, 12);
        Assert.Equal(0.5, c.PitchOffset, 12);
        Assert.True(c.PointerUp(PointerButton.Left));

        // Right button, 5 px: a drag (5 > 4), and a right release is never a click anyway.
        var r = At(0, 0, 0, 20);
        r.PointerDown(PointerButton.Right, 0, 0);
        r.PointerMove(5, 0);
        Assert.Equal(-0.025, r.TargetYaw, 12);
        Assert.False(r.PointerUp(PointerButton.Right));
        r.PointerDown(PointerButton.Middle, 0, 0);
        Assert.False(r.PointerUp(PointerButton.Middle));

        // The slop is measured from the START: 3 px out and 3 px back still moved 3 px → click.
        var b = At(0, 0, 0, 20);
        b.PointerDown(PointerButton.Left, 0, 0);
        b.PointerMove(3, 0);
        b.PointerMove(0, 0);
        Assert.True(b.PointerUp(PointerButton.Left));
    }

    [Fact]
    public void PitchOffsetIsClampedToThirtyFiveDegrees()
    {
        // 200 px down = +50° → clamped to 35.
        var c = At(0, 0, 0, 20);
        c.PointerDown(PointerButton.Middle, 0, 0);
        c.PointerMove(0, 200);
        Assert.Equal(35, c.PitchOffset);
    }

    [Fact]
    public void KeysTurnAndZoom()
    {
        // q: +π/4, e: −π/4 (twice q, once e = +π/4); +: 20·0.8 = 16; −: 16·1.25 = 20; 149 · 1.25 → 150.
        var c = At(0, 0, 0, 20);
        c.KeyDown("q");
        c.KeyDown("q");
        c.KeyDown("e");
        Assert.Equal(Math.PI / 4, c.TargetYaw, 12);
        c.KeyDown("+");
        Assert.Equal(16, c.TargetDist, 12);
        c.KeyDown("-");
        Assert.Equal(20, c.TargetDist, 12);
        var f = At(0, 0, 0, 149);
        f.KeyDown("-");
        Assert.Equal(150, f.TargetDist);
    }

    [Fact]
    public void StepEasesYawAndDistance()
    {
        // Q then one frame of 0.05 s: yaw = π/4 · (1 − e^−0.4) = 0.2589300303525642 (lerp from 0).
        var c = At(0, 0, 0, 40);
        c.KeyDown("q");
        c.Step(0.05);
        Assert.Equal(0.2589300303525642, c.Yaw, 12);
        // A frame longer than 0.1 s counts as 0.1: dist 40 → 20 by (1 − e^−0.8) = 0.5506710358827784 → 28.986579…
        var d = At(0, 0, 0, 40);
        d.TargetDist = 20;
        d.Step(5);
        Assert.Equal(40 - 20 * (1 - Math.Exp(-0.8)), d.Dist, 12);
    }

    [Fact]
    public void KeyPanMovesAlongTheViewAtTheEasedDistance()
    {
        // yaw 0: forward (−sin 0, 0, −cos 0) = (0,0,−1), right (cos 0, 0, −sin 0) = (1,0,0).
        // w for 0.1 s at dist 40: 40 · 0.9 · 0.1 = 3.6 m → z −3.6; d adds +3.6 on x; w+s cancel.
        var c = At(0, 0, 0, 40);
        c.KeyDown("w");
        c.Step(0.1);
        Assert.Equal(-3.6, c.Target.Z, 12);
        c.KeyUp("w");
        c.KeyDown("arrowright");
        c.Step(0.1);
        Assert.Equal(3.6, c.Target.X, 12);
        c.ReleaseKeys();
        c.KeyDown("w");
        c.KeyDown("s");
        var before = c.Target;
        c.Step(0.1);
        Assert.Equal(before.Z, c.Target.Z, 12);
        // yaw π/2: forward (−1, 0, ~0) → w moves −x by 3.6.
        var y = At(0, 0, 0, 40, Math.PI / 2);
        y.KeyDown("w");
        y.Step(0.1);
        Assert.Equal(-3.6, y.Target.X, 12);
    }

    [Fact]
    public void ZoomToFliesInSixHundredTwentyFiveMilliseconds()
    {
        // Root (10,2,−5) → aim (10, 2.85, −5) at 4.5 m. Steps of 0.1 s: t = 0.16 after one (smoothstep
        // 3·0.0256 − 2·0.004096 = 0.068608), 1 after seven (0.16·7 = 1.12 → 1): exactly on the point.
        var c = At(0, 0, 0, 40);
        c.ZoomTo(new Vec3(10, 2, -5));
        Assert.Equal(4.5, c.TargetDist);
        Assert.True(c.Flying);
        c.Step(0.1);
        Assert.Equal(10 * 0.068608, c.Target.X, 12);
        for (int i = 0; i < 6; i++) c.Step(0.1);
        Assert.Equal(new Vec3(10, 2.85, -5), c.Target);
        Assert.False(c.Flying);
    }

    [Fact]
    public void WheelAndDragAbortAFly()
    {
        var c = At(0, 0, 0, 40);
        c.FlyTo(new Vec3(100, 0, 0), 10);
        c.Wheel(100, () => null);
        Assert.False(c.Flying);
        c.FlyTo(new Vec3(100, 0, 0), 10);
        c.PointerDown(PointerButton.Right, 0, 0);
        c.PointerMove(1, 0);
        Assert.False(c.Flying);
        // A fly's distance ignores the cap but not the lens: 500 → 150.
        c.FlyTo(new Vec3(0, 0, 0), 500);
        Assert.Equal(150, c.TargetDist);
    }

    [Fact]
    public void PoseFollowsTheBasePitchCurve()
    {
        // dist 40: base pitch 18 + 44·√(39.2/149.2) = 40.55336239889695°; yaw 0 → camera at
        // (0, 40 sin p, 40 cos p) above the target.
        var c = At(1, 2, 3, 40);
        var pose = c.Pose();
        double p = 40.55336239889695 * Math.PI / 180;
        Assert.Equal(40.55336239889695, pose.PitchDeg, 12);
        Assert.Equal(1, pose.Position.X, 12);
        Assert.Equal(2 + 40 * Math.Sin(p), pose.Position.Y, 12);
        Assert.Equal(3 + 40 * Math.Cos(p), pose.Position.Z, 12);
        // Free pitch −35 at the near end: 18 − 35 = −17 → clamped to 8°.
        c.PitchOffset = -35;
        c.JumpTo(new Vec3(0, 0, 0), 0.8);
        Assert.Equal(8, c.Pose().PitchDeg);
    }

    [Fact]
    public void FrameWorldUsesCentreGroundAndFit()
    {
        // Bounds 0..40 × 0..30: centre (20, 15), r = 25 → 25·1.15 / sin 22.5° = 75.12974…; ground sampled there.
        var c = new OverviewControl();
        c.FrameWorld(new BoundsXZ(0, 40, 0, 30), (x, z) => x + z);
        Assert.Equal(new Vec3(20, 35, 15), c.Target);
        Assert.Equal(25 * 1.15 / Math.Sin(22.5 * Math.PI / 180), c.Dist, 12);
        Assert.Equal(c.Dist, c.TargetDist);
        // No bounds: origin at 70 m.
        c.FrameWorld(null, (_, _) => 4);
        Assert.Equal(new Vec3(0, 4, 0), c.Target);
        Assert.Equal(70, c.Dist);
    }

    [Fact]
    public void SaveRestoreRoundTrips()
    {
        var c = At(1, 2, 3, 33, 0.5);
        c.PitchOffset = 7;
        var s = c.Save();
        c.KeyDown("w");
        c.Target = new Vec3(9, 9, 9);
        c.TargetDist = 100;
        c.Restore(s);
        Assert.Equal(s, c.Save());
        Assert.Empty(c.KeysDown);
    }

    [Fact]
    public void HitGroundIsThreeRayIntersectPlane()
    {
        // From (0,10,0) along (0.6,−0.8,0): t = 12.5 → (7.5, 0, 0). Upwards: none. Parallel: only on the plane.
        var h = OverviewControl.HitGround(new Vec3(0, 10, 0), new Vec3(0.6, -0.8, 0));
        Assert.NotNull(h);
        Assert.Equal(7.5, h!.Value.X, 12);
        Assert.Equal(0, h.Value.Y, 12);
        Assert.Null(OverviewControl.HitGround(new Vec3(0, 10, 0), new Vec3(0, 1, 0)));
        Assert.Null(OverviewControl.HitGround(new Vec3(0, 10, 0), new Vec3(1, 0, 0)));
        Assert.Equal(new Vec3(3, 0, 4), OverviewControl.HitGround(new Vec3(3, 0, 4), new Vec3(1, 0, 0)));
    }

    [Fact]
    public void WorldBoundsParse()
    {
        BoundsXZ? Of(string json) { using var d = JsonDocument.Parse(json); return OverviewControl.WorldBoundsOf(d.RootElement); }
        Assert.Equal(new BoundsXZ(-104, 300, -203, 134),
                     Of("""{"world_bounds": {"min_x": -104.0, "min_z": -203.0, "max_x": 300.0, "max_z": 134.0}}"""));
        Assert.Null(Of("""{"world_bounds": null}"""));
        Assert.Null(Of("""{}"""));
        Assert.Null(Of("""{"world_bounds": {"min_x": 0, "max_x": 1, "min_z": 0}}"""));
        Assert.Null(Of("""{"world_bounds": {"min_x": "0", "max_x": 1, "min_z": 0, "max_z": 1}}"""));
    }
}
