using AnimaNative.Embody;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>
/// First-step probe: the time from an order (click walk, prop offer) to the avatar's first centimetre.
/// Hand derivation against MoveThresholdM 0.01 m and TimeoutS 10 s; every Sample after Arm counts one frame.
/// [F1] armed at t=10 at (0,0): 10.016 at x 0.005 is 0.005 m &lt; 0.01 → null (frame 1); 10.032 at x 0.02 is 0.02 m
///      &gt; 0.01 → hit after (10.032-10)·1000 = 32.0 ms, frame 2; the probe disarms, a further Sample is null.
/// [F2] never armed: Sample is null and counts no frame (a later Arm + hit reports frame 1).
/// [F3] re-arming before a hit: armed "a" at t=0 at (0,0), one sample; re-armed "b" at t=5 at (1,1). Sample(5.016,1,1)
///      is null (0 m from the new start, 1.41 m from the old); Sample(5.032,1.02,1) → ("b", 32.0, 2) — the old start
///      time would give 5032 ms and the old frame count 3.
/// [F4] armed "prop_offer" at t=0 at (1,1), never moving: at 10.0 s elapsed equals TimeoutS, not more → null;
///      at 10.5 → ("prop_offer", null, 2) and the probe disarms.
/// [F5] diagonal: start (0,0), sample at (0.008,0.008) is hypot = 0.008·√2 = 0.0113 m &gt; 0.01 → hit.
/// </summary>
public class FirstStepProbeTests
{
    [Fact]
    public void F1_FirstCentimetreAfterTwoFrames()
    {
        var p = new FirstStepProbe();
        p.Arm("click_walk", 10.0, 0, 0);
        Assert.True(p.Armed);
        Assert.Null(p.Sample(10.016, 0.005, 0));
        var r = p.Sample(10.032, 0.02, 0);
        Assert.NotNull(r);
        Assert.Equal("click_walk", r!.Source);
        Assert.Equal(32.0, r.LatencyMs!.Value, 1e-6);
        Assert.Equal(2, r.Frames);
        Assert.False(p.Armed);
        Assert.Null(p.Sample(10.048, 1, 0));
    }

    [Fact]
    public void F2_UnarmedSamplesNothingAndCountsNoFrame()
    {
        var p = new FirstStepProbe();
        Assert.False(p.Armed);
        Assert.Null(p.Sample(1.0, 5, 5));
        Assert.Null(p.Sample(2.0, 9, 9));
        p.Arm("click_walk", 3.0, 0, 0);
        var r = p.Sample(3.016, 0.02, 0);
        Assert.Equal(1, r!.Frames);
    }

    [Fact]
    public void F3_RearmReplacesSourceStartAndFrames()
    {
        var p = new FirstStepProbe();
        p.Arm("a", 0, 0, 0);
        Assert.Null(p.Sample(0.1, 0, 0));
        p.Arm("b", 5, 1, 1);
        Assert.Null(p.Sample(5.016, 1, 1));
        var r = p.Sample(5.032, 1.02, 1);
        Assert.Equal("b", r!.Source);
        Assert.Equal(32.0, r.LatencyMs!.Value, 1e-6);
        Assert.Equal(2, r.Frames);
    }

    [Fact]
    public void F4_TimeoutOnlyPastTenSeconds()
    {
        var p = new FirstStepProbe();
        p.Arm("prop_offer", 0, 1, 1);
        Assert.Null(p.Sample(10.0, 1, 1));
        var r = p.Sample(10.5, 1, 1);
        Assert.Equal(new FirstStepResult("prop_offer", null, 2), r);
        Assert.False(p.Armed);
    }

    [Fact]
    public void F5_DiagonalDistanceCounts()
    {
        var p = new FirstStepProbe();
        p.Arm("click_walk", 0, 0, 0);
        var r = p.Sample(0.016, 0.008, 0.008);
        Assert.NotNull(r);
        Assert.Equal(16.0, r!.LatencyMs!.Value, 1e-6);
    }
}
