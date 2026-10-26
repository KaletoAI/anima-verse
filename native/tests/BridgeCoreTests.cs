using System;
using System.Collections.Generic;
using System.Linq;
using AnimaNative.Figures;
using AnimaNative.Overview;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>
/// The Task 31 core parts without a shared vector, derived by hand here:
///   • <c>groundOffsetOf</c> — the cases of client3d/scripts/smoke_clip_ground.mjs [1], verbatim;
///   • <see cref="ClipGround.Measure"/> on a hand-built skinned rig (one bone, two vertices);
///   • the probe sampler (<see cref="RigPose"/>) against three's interpolants (lerp / slerpFlat, clamped);
///   • the turn bake of <see cref="FootLockMeasure.Relock"/> on the vector skeleton with a turning pelvis.
/// </summary>
public class BridgeCoreTests
{
    /// <summary>
    /// The browser's relock hysteresis (footLockMeasure.ts <c>RELOCK_MIN_GAIN_CM</c> = 0.1): no vector case puts a rebuilt
    /// path within 0.1 cm of its import, so the number itself is pinned here (mutation probe of Task 31).
    /// </summary>
    [Fact]
    public void RelockGainIsTheBrowsers() => Assert.Equal(0.1, FootLockMeasure.RelockMinGainCm);

    // ---- clipGround [1] ----

    [Theory]
    [InlineData(0.30, 0.00, 0.30)]    // the swim case: the body hangs 30 cm over the anchor
    [InlineData(0.00, 0.00, 0.00)]    // authored on the floor
    [InlineData(0.146, 0.00, 0.146)]  // laying: the same subtraction
    [InlineData(-0.05, 0.00, 0.00)]   // a crouch below the bind pose is not lifted
    [InlineData(0.30, 0.10, 0.20)]    // only the difference counts
    [InlineData(0.05, 0.30, 0.00)]    // a bind pose above the clip: the crouch case
    public void GroundOffsetOfIsThePositiveDifference(double clipMinY, double bindMinY, double want)
        => Assert.Equal(want, ClipGround.GroundOffsetOf(clipMinY, bindMinY), 12);

    [Fact]
    public void GroundOffsetOfANonMeasurementIsZero()
    {
        Assert.Equal(0, ClipGround.GroundOffsetOf(double.NaN, 0));
        Assert.Equal(0, ClipGround.GroundOffsetOf(0.3, double.NaN));
        Assert.Equal(0, ClipGround.GroundOffsetOf(double.PositiveInfinity, 0));
    }

    /// <summary>25 poses over the duration, played by a LOOPING action: f = 24 wraps to 0 (three's LoopRepeat).</summary>
    [Fact]
    public void SampleTimesWrapTheLastPose()
    {
        var t = ClipGround.SampleTimes(2.4);
        Assert.Equal(25, t.Length);
        Assert.Equal(0, t[0]);
        Assert.Equal(1.2, t[12], 12);
        Assert.Equal(2.3, t[23], 12);
        Assert.Equal(0, t[24], 12);
    }

    /// <summary>
    /// One bone "Hips" resting at (0, 1, 0); a skin of two vertices at mesh (0, 0, 0) and (0, 1, 0), each fully on the
    /// bone, bind pose = the bone's rest inverse (a translation by −1): at rest the skinned points are the mesh points,
    /// bindMinY = 0. A clip holding the hips at y 1.3 lifts both by 0.3 → offset 0.3; one at y 0.8 lowers them → 0
    /// (never negative); a clip that only rises mid-way still samples its first pose (y 1.0) → 0.
    /// </summary>
    [Fact]
    public void MeasureFindsTheLowestSkinnedPoint()
    {
        var rig = new ProbeRig(Affine.Identity, new[] { new ProbeNode("Hips", -1, true, new V3(0, 1, 0), Quat.Identity, new V3(1, 1, 1)) });
        var skin = new ProbeSkin
        {
            Rest = new float[] { 0, 0, 0, 0, 1, 0 }, Bones = new[] { 0, 0 }, Weights = new[] { 1f, 1f }, Slots = 1,
            BindNodes = new[] { 0 }, BindPoses = new[] { Affine.Translation(0, -1, 0) }, Frame = Affine.Identity,
        };
        ProbeClip Hold(double y) => new()
        {
            Name = $"y{y}", Duration = 1,
            Tracks = new() { new ProbeTrack { Node = "Hips", Prop = "position", Times = new[] { 0f, 1f }, Values = new[] { 0f, (float)y, 0f, 0f, (float)y, 0f } } },
        };
        var up = Hold(1.3);
        var down = Hold(0.8);
        var mid = new ProbeClip
        {
            Name = "mid", Duration = 2,
            Tracks = new() { new ProbeTrack { Node = "Hips", Prop = "position", Times = new[] { 0f, 1f, 2f }, Values = new[] { 0f, 1f, 0f, 0f, 1.5f, 0f, 0f, 1f, 0f } } },
        };
        ClipGround.Measure(new[] { up, down, mid }, rig, new[] { skin });
        Assert.Equal(0.3, up.GroundOffset, 5);
        Assert.Equal(0, down.GroundOffset);
        Assert.Equal(0, mid.GroundOffset);
    }

    // ---- the probe sampler ----

    /// <summary>
    /// Vector keys (0, 0, 0) at 0 s and (2, 4, 6) at 1 s: t 0.25 → (0.5, 1, 1.5); before / after the keys → clamped.
    /// Quaternion keys identity and 90° about +Y: half-way is 45° about +Y = (0, sin 22.5°, 0, cos 22.5°).
    /// </summary>
    [Fact]
    public void SamplerInterpolatesLikeThree()
    {
        var pos = new ProbeTrack { Node = "B", Prop = "position", Times = new[] { 0f, 1f }, Values = new[] { 0f, 0f, 0f, 2f, 4f, 6f } };
        Assert.Equal(new V3(0.5, 1, 1.5), RigPose.SampleVector(pos, 0.25));
        Assert.Equal(new V3(0, 0, 0), RigPose.SampleVector(pos, -1));
        Assert.Equal(new V3(2, 4, 6), RigPose.SampleVector(pos, 3));
        double s = Math.Sin(Math.PI / 4), c = Math.Cos(Math.PI / 4);
        var rot = new ProbeTrack { Node = "B", Prop = "quaternion", Times = new[] { 0f, 1f }, Values = new[] { 0f, 0f, 0f, 1f, 0f, (float)s, 0f, (float)c } };
        var q = RigPose.SampleQuat(rot, 0.5);
        Assert.Equal(Math.Sin(Math.PI / 8), q.Y, 6);
        Assert.Equal(Math.Cos(Math.PI / 8), q.W, 6);
    }

    /// <summary>A child at (0, 0, 1) under a root turned 90° about +Y lies at (1, 0, 0) (x' = z·sin 90°).</summary>
    [Fact]
    public void WorldMatricesChainDownTheRig()
    {
        double h = Math.Sqrt(0.5);
        var rig = new ProbeRig(Affine.Identity, new[]
        {
            new ProbeNode("Root", -1, true, new V3(0, 0, 0), new Quat(0, h, 0, h), new V3(1, 1, 1)),
            new ProbeNode("Child", 0, true, new V3(0, 0, 1), Quat.Identity, new V3(1, 1, 1)),
        });
        var p = new RigPose(rig).WorldPosition(1);
        Assert.Equal(1, p.X, 9);
        Assert.Equal(0, p.Z, 9);
        var (pos, q, scale) = RigMath.Decompose(RigMath.Compose(new V3(1, 2, 3), new Quat(0, h, 0, h), new V3(2, 2, 2)));
        Assert.Equal(new V3(1, 2, 3), pos);
        Assert.Equal(h, q.Y, 9);
        Assert.Equal(2, scale.X, 9);
        var inv = RigMath.Inverse(RigMath.Compose(new V3(1, 2, 3), new Quat(0, h, 0, h), new V3(2, 2, 2)));
        var back = RigMath.Apply(inv, RigMath.Apply(RigMath.Compose(new V3(1, 2, 3), new Quat(0, h, 0, h), new V3(2, 2, 2)), new V3(5, -1, 7)));
        Assert.Equal(5, back.X, 9);
        Assert.Equal(-1, back.Y, 9);
        Assert.Equal(7, back.Z, 9);
    }

    // ---- the turn bake ----

    /// <summary>
    /// The skeleton of foot_lock_measure.json (fixture "a": hips at (0, 100, 0), UpLegs at ±10 on x) with the pelvis
    /// turning θ(t) = 90° · t / T about +Y over 11 keys. The heading of L = R_y(θ)·(20, 0, 0) = (20 cos θ, 0, −20 sin θ)
    /// is atan2(20 cos θ, −20 sin θ) − π/2 = θ, so ψ = θ and ψ_end = 90°. Baked: the hips' local rotation
    /// R_y(−ψ)·R_y(θ) = identity on every key, the hips position stays on the pivot's vertical (0, 100, 0), the turn
    /// is stored with the pivot = the hips' rest point.
    /// </summary>
    [Fact]
    public void TurnIsTakenOutOfTheHipsAndStored()
    {
        var bones = new (string Name, string? Parent, V3 Pos)[]
        {
            ("mixamorigHips", null, new V3(0, 100, 0)), ("Legs", "mixamorigHips", new V3(0, 0, 0)),
            ("mixamorigLeftUpLeg", "Legs", new V3(10, 0, 0)), ("mixamorigLeftLeg", "mixamorigLeftUpLeg", new V3(0, -46, 0)),
            ("mixamorigLeftFoot", "mixamorigLeftLeg", new V3(0, -46, 0)), ("mixamorigLeftToeBase", "mixamorigLeftFoot", new V3(0, -5, 12)),
            ("mixamorigLeftToe_End", "mixamorigLeftToeBase", new V3(0, -3, 6)),
            ("mixamorigRightUpLeg", "Legs", new V3(-10, 0, 0)), ("mixamorigRightLeg", "mixamorigRightUpLeg", new V3(0, -46, 0)),
            ("mixamorigRightFoot", "mixamorigRightLeg", new V3(0, -46, 0)), ("mixamorigRightToeBase", "mixamorigRightFoot", new V3(0, -5, 12)),
            ("mixamorigRightToe_End", "mixamorigRightToeBase", new V3(0, -3, 6)),
        };
        var names = bones.Select(b => b.Name).ToList();
        var rig = new ProbeRig(Affine.Identity, bones.Select(b => new ProbeNode(b.Name, b.Parent is null ? -1 : names.IndexOf(b.Parent), true,
                                                                                 b.Pos, Quat.Identity, new V3(1, 1, 1))).ToList());
        const int n = 11;
        double dur = 1.0 / 3;
        var times = Enumerable.Range(0, n).Select(i => (float)(dur * i / (n - 1))).ToArray();
        var pos = Enumerable.Range(0, n).SelectMany(_ => new[] { 0f, 100f, 0f }).ToArray();
        var rot = Enumerable.Range(0, n).SelectMany(i =>
        {
            double th = Math.PI / 2 * i / (n - 1);
            return new[] { 0f, (float)Math.Sin(th / 2), 0f, (float)Math.Cos(th / 2) };
        }).ToArray();
        var clip = new ProbeClip
        {
            Name = "turning", Duration = dur,
            Tracks = new()
            {
                new ProbeTrack { Node = "mixamorigHips", Prop = "position", Times = times, Values = pos },
                new ProbeTrack { Node = "mixamorigHips", Prop = "quaternion", Times = times, Values = rot },
            },
            Path = new RootPath(times, new float[n * 2]),
        };
        var reports = FootLockMeasure.Relock(new[] { clip }, rig, 1);
        Assert.Single(reports);
        Assert.Equal(90, reports[0].TurnDeg!.Value, 3);
        Assert.NotNull(clip.Turn);
        Assert.Equal(new V3(0, 100, 0), clip.Turn!.Pivot);
        for (int i = 0; i < n; i++) Assert.Equal(Math.PI / 2 * i / (n - 1), clip.Turn.Yaw[i], 5);
        var hipsRot = clip.Tracks.Single(t => t.Node == "mixamorigHips" && t.Prop == "quaternion");
        var hipsPos = clip.Tracks.Single(t => t.Node == "mixamorigHips" && t.Prop == "position");
        Assert.True(hipsRot.Rewritten && hipsPos.Rewritten);
        for (int i = 0; i < n; i++)
        {
            Assert.Equal(1, Math.Abs(hipsRot.Values[i * 4 + 3]), 5);
            Assert.Equal(100, hipsPos.Values[i * 3 + 1], 4);
            Assert.Equal(0, hipsPos.Values[i * 3], 4);
        }
        // Switched off: measured nothing, stored nothing ('switched off').
        var off = new ProbeClip { Name = "off", Duration = dur, Tracks = clip.Tracks.Select(t => t).ToList(), Path = new RootPath(times, new float[n * 2]) };
        off.Tracks[0] = new ProbeTrack { Node = "mixamorigHips", Prop = "position", Times = times, Values = pos };
        off.Tracks[1] = new ProbeTrack { Node = "mixamorigHips", Prop = "quaternion", Times = times, Values = rot };
        var r2 = FootLockMeasure.Relock(new[] { off }, rig, 1, null, turn: false);
        Assert.Null(r2[0].TurnDeg);
        Assert.Equal("switched off", r2[0].TurnReason);
        Assert.Null(off.Turn);
    }
}
