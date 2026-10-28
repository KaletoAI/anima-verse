using System;
using AnimaNative.Embody;
using AnimaNative.Overview;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>Task 48 / E7-T3: engine.ts camera order and mode lifecycle, hand-derived from the browser constants.</summary>
public class EmbodyCameraTests
{
    [Fact]
    public void EnterFollowsEyesAndExitReturnsToFeet()
    {
        var c = new OverviewControl();
        var root = new Vec3(10, 2, 20);
        var eye = new Vec3(10, 3.598, 20); // 2 + .94 * 1.7
        var mode = new EmbodyMode(c, () => root, () => eye);
        Assert.True(mode.Enter());
        c.KeyDown("w");
        for (int i = 0; i < 200; i++) c.Step(.05);
        Assert.Equal(7, c.Dist, 10);
        Assert.Equal(eye, c.Target);
        var before = c.TargetDist;
        c.ZoomTo(new Vec3(100, 0, 100));
        Assert.Equal(before, c.TargetDist);
        mode.Exit();
        c.ReleaseKeys();
        for (int i = 0; i < 200; i++) c.Step(.05);
        Assert.Equal(70, c.Dist, 10);
        Assert.Equal(root, c.Target);
        Assert.Null(c.Follow);
        Assert.Null(c.ZoomCap);
    }

    [Fact]
    public void CapToastsOncePerSuccessfulEntryAndNeverMovesTargetToCursor()
    {
        var c = new OverviewControl();
        var mode = new EmbodyMode(c, () => new Vec3(0, 0, 0), () => new Vec3(0, 1.598, 0));
        int hints = 0, hits = 0;
        mode.CapHint += () => hints++;
        mode.Enter();
        for (int i = 0; i < 100; i++) c.Wheel(100, () => { hits++; return new Vec3(80, 0, 80); });
        Assert.Equal(34, c.TargetDist);
        Assert.Equal(1, hints);
        mode.Enter(); // repeated entry is a no-op, including the hint latch
        c.Wheel(100, () => null);
        Assert.Equal(1, hints);
        c.Wheel(-100, () => { hits++; return new Vec3(80, 0, 80); });
        Assert.Equal(0, hits);
        mode.Exit(); mode.Enter();
        c.Wheel(10000, () => null);
        Assert.Equal(2, hints);
    }

    [Fact]
    public void FollowRunsAfterFlyAndIsAskedOncePerStep()
    {
        var c = new OverviewControl();
        c.JumpTo(new Vec3(0, 0, 0), 7);
        c.FlyTo(new Vec3(10, 0, 0), 7);
        int calls = 0;
        c.Follow = () => { calls++; return new Vec3(20, 0, 0); };
        c.KeyDown("w");
        c.Step(.1);
        double fly = 10 * CameraMath.FlyEase(CameraMath.FlyAdvance(0, .1));
        Assert.Equal(fly + (20 - fly) * (1 - Math.Exp(-.6)), c.Target.X, 12);
        Assert.Equal(0, c.Target.Z);
        Assert.Equal(1, calls);
    }

    [Fact]
    public void FirstPersonWaitsForEasedZoomAndContinuousThresholdThenUsesExactEye()
    {
        var c = new OverviewControl();
        var eye = new Vec3(10, 2, 30);
        c.JumpTo(eye, 7);
        new EmbodyMode(c, () => eye, () => eye).Enter();
        c.Wheel(-10000, () => null);
        Assert.Equal(.8, c.TargetDist);
        c.Step(.1);
        Assert.False(c.FirstPerson);
        c.Dist = c.TargetDist = 1.2;
        c.Step(.1); c.Step(.079);
        Assert.False(c.FirstPerson);
        var pose = c.Step(.001);
        Assert.True(c.FirstPerson);
        Assert.Equal(eye, pose.Position);
        eye = new Vec3(11, 3, 31);
        c.Step(.01);
        Assert.Equal(eye, c.Target); // engine.placeFirstPerson copies its exact lens into target too.
        c.TargetDist = 1.8;
        c.Step(.1); c.Step(.08);
        Assert.False(c.FirstPerson);
        Assert.True(Distance(c.Pose().Position, c.Target) >= 2 - 1e-12);
    }

    [Fact]
    public void BareLeftDragOrbitsWithFourPixelClickSlop()
    {
        var c = new OverviewControl { OrbitOnDrag = true };
        c.PointerDown(PointerButton.Left, false, false, false, 0, 0, () => throw new Exception("no pan ray"));
        c.PointerMove(3, 0, () => null);
        Assert.True(c.PointerUp(PointerButton.Left));
        c.PointerDown(PointerButton.Left, false, false, false, 0, 0, () => null);
        c.PointerMove(5, 0, () => null);
        Assert.False(c.PointerUp(PointerButton.Left));
    }

    private static double Distance(Vec3 a, Vec3 b) => Math.Sqrt(Math.Pow(a.X-b.X, 2)+Math.Pow(a.Y-b.Y, 2)+Math.Pow(a.Z-b.Z, 2));
}
