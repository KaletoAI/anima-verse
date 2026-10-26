using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using AnimaNative.Figures;
using AnimaNative.Overview;
using AnimaNative.Tests.Vectors;
using Xunit;
using static AnimaNative.Tests.ScatterVectorAdapters;

namespace AnimaNative.Tests;

/// <summary>
/// The adapters of client3d/scripts/secondaryVectorDispatch.mjs (Task 33), mirrored for the native port:
/// <code>
///   TS fn                   C#                                  shape translation
///   stepSecondaryParticle   SecondaryMotion.StepParticle        [x,y,z] arrays ↔ V3, params = the explicit MotionGroup
///   softMotionAngle         SecondaryMotion.SoftMotionAngle
///   blendMotionParams       SecondaryMotion.BlendParams         MotionGroup ↔ JSON (only the expected keys compare)
///   secondaryChain          MotionRig + SecondaryMotion         bones {name, parent, matrix (column-major local bind)} →
///                                                               rig under an identity base; one skin over every bone
///                                                               in input order, boneInverse = inverse bind world,
///                                                               bindMatrix = identity; Float32 positions/weights;
///                                                               Update(dt) × frames; world matrices + the two ring
///                                                               samples (half width, midpoint distance)
/// </code>
/// </summary>
internal static class SecondaryVectorAdapters
{
    private static double N(JsonNode? n) => VectorCompare.Num(n);
    private static V3 Vec(JsonNode? n) => new(N(n![0]), N(n[1]), N(n[2]));
    private static JsonArray Arr(V3 v) => new(v.X, v.Y, v.Z);

    public static JsonElement Element(JsonNode? n) => JsonDocument.Parse(n!.ToJsonString()).RootElement.Clone();
    public static MotionGroup Group(JsonNode? n) => MotionGroup.Parse(Element(n));

    /// <summary>The chain fixture through the production solver (secondaryVectorDispatch.mjs <c>chainValue</c>).</summary>
    public static JsonObject Chain(JsonNode? node)
    {
        var d = (JsonObject)node!;
        var bones = (JsonArray)d["bones"]!;
        var names = bones.Select(b => Str(b!["name"])).ToList();
        var parents = bones.Select(b => b!["parent"] is { } p ? (int)N(p) : -1).ToList();
        var rig = new MotionRig(names, parents);
        for (int i = 0; i < bones.Count; i++)
        {
            // three: Matrix4.fromArray(matrix).decompose(position, quaternion, scale), then compose on update.
            var m = MotionMath.FromElements(((JsonArray)bones[i]!["matrix"]!).Select(x => N(x)).ToArray());
            var (p, q, s) = RigMath.Decompose(m);
            rig.Local[i] = RigMath.Compose(p, q, s);
        }
        rig.UpdateWorld();
        var inverses = rig.World.Select(w => w.Inverted()).ToArray();
        float[] F(string k) => ((JsonArray)d[k]!).Select(x => (float)N(x)).ToArray();
        var skin = new MotionSkin(Enumerable.Range(0, names.Count).ToArray(), inverses, F("positions"),
                                  ((JsonArray)d["indices"]!).Select(x => (int)N(x)).ToArray(), F("weights"));
        var motion = new SecondaryMotion(rig, skin.JointNodes, SecondaryMotion.MeasureCentroids(new[] { skin }), _ => null,
                                         MotionPayload.Parse(Element(d["payload"])));
        int frames = (int)N(d["frames"]);
        double dt = N(d["dt"]);
        for (int i = 0; i < frames; i++) motion.Update(dt);
        rig.UpdateWorld();
        V3 Vertex(int i)
        {
            var raw = new V3(skin.Positions[i * 3], skin.Positions[i * 3 + 1], skin.Positions[i * 3 + 2]);
            var sum = V3.Zero;
            for (int j = 0; j < 4; j++)
            {
                double w = skin.Weights[i * 4 + j];
                if (w == 0) continue;
                int k = skin.Joints[i * 4 + j];
                sum += rig.World[k].Times(inverses[k]).Apply(raw) * w;
            }
            return sum;
        }
        var samples = new JsonArray();
        foreach (var pair in (JsonArray)d["pairs"]!)
        {
            var a = Vertex((int)N(pair![0]));
            var b = Vertex((int)N(pair[1]));
            samples.Add(new JsonObject { ["halfWidth"] = a.DistanceTo(b) / 2, ["distance"] = ((a + b) * 0.5).Length() });
        }
        return new JsonObject
        {
            ["matrices"] = new JsonArray(rig.World.Select(w => (JsonNode?)new JsonArray(w.Elements().Select(x => (JsonNode?)x).ToArray())).ToArray()),
            ["samples"] = samples,
        };
    }

    public static readonly Dictionary<string, Func<JsonArray, JsonNode?>> Dispatch = new()
    {
        ["stepSecondaryParticle"] = a =>
        {
            Arity(a, 6, 6);
            var (p, v) = SecondaryMotion.StepParticle(Vec(a[0]), Vec(a[1]), Vec(a[2]), Vec(a[3]), Group(a[4]), N(a[5]));
            return new JsonObject { ["p"] = Arr(p), ["v"] = Arr(v) };
        },
        ["softMotionAngle"] = a => SecondaryMotion.SoftMotionAngle(N(Arity(a, 2, 2)[0]), N(a[1])),
        ["blendMotionParams"] = a => SecondaryMotion.BlendParams(Group(Arity(a, 3, 3)[0]), Group(a[1]), N(a[2])).ToJson(),
        ["secondaryChain"] = a => Chain(Arity(a, 1, 1)[0]),
    };
}

/// <summary>shared/test-vectors/secondary_particle.json (hand derivations: client3d/scripts/smoke_secondary_motion.mjs S1–S6).</summary>
public class SecondaryParticleVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("secondary_particle"));
    public static TheoryData<string> Cases => VectorFile.Labels("secondary_particle");

    [Theory]
    [MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, SecondaryVectorAdapters.Dispatch);

    [Fact]
    public void EveryFunctionIsDispatched() => Assert.Empty(File.Value.MissingFunctions(SecondaryVectorAdapters.Dispatch));
}

/// <summary>shared/test-vectors/secondary_angle.json (A1–A3).</summary>
public class SecondaryAngleVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("secondary_angle"));
    public static TheoryData<string> Cases => VectorFile.Labels("secondary_angle");

    [Theory]
    [MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, SecondaryVectorAdapters.Dispatch);

    [Fact]
    public void EveryFunctionIsDispatched() => Assert.Empty(File.Value.MissingFunctions(SecondaryVectorAdapters.Dispatch));
}

/// <summary>shared/test-vectors/secondary_params.json (B1–B4).</summary>
public class SecondaryParamsVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("secondary_params"));
    public static TheoryData<string> Cases => VectorFile.Labels("secondary_params");

    [Theory]
    [MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, SecondaryVectorAdapters.Dispatch);

    [Fact]
    public void EveryFunctionIsDispatched() => Assert.Empty(File.Value.MissingFunctions(SecondaryVectorAdapters.Dispatch));
}

/// <summary>shared/test-vectors/secondary_chain.json (C1–C4).</summary>
public class SecondaryChainVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("secondary_chain"));
    public static TheoryData<string> Cases => VectorFile.Labels("secondary_chain");

    [Theory]
    [MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, SecondaryVectorAdapters.Dispatch);

    [Fact]
    public void EveryFunctionIsDispatched() => Assert.Empty(File.Value.MissingFunctions(SecondaryVectorAdapters.Dispatch));
}

/// <summary>
/// The runtime rules around the vectors, every number derived by hand here: the anchor blend
/// (scripts/smoke_extension_rig_anchor_blend.mjs), the resets (far / gap / frozen) on a one-link swing, and the
/// skinned-normal correction.
/// </summary>
public class SecondaryRuntimeTests
{
    private const double Tol = 1e-6;

    private static MotionGroup Group(string json) => MotionGroup.Parse(JsonDocument.Parse(json).RootElement);

    private const string Defaults = "\"freq_hz\":2,\"zeta\":0.3,\"gravity\":0,\"gravity_scale\":1,\"gain\":0,\"max_deg\":0,"
        + "\"sag_max_deg\":0,\"spill_max_deg\":0,\"head_sag\":1,\"axis_gain\":[1,1,1],\"flatten\":0,\"stretch\":0,\"spread\":0,"
        + "\"flatten_floor\":1,\"spill\":0,\"translate\":0,\"squash\":[1,1],\"length\":1,\"girth\":1,\"rest_deg\":0,"
        + "\"rest_max_deg\":90,\"straighten_deg\":0,\"freetext_clothing_gain\":1";

    private static MotionPayload Payload(string bones, string extra = "")
        => MotionPayload.Parse(JsonDocument.Parse($"{{\"rev\":\"t\",\"groups\":{{\"g\":{{{Defaults}{extra},\"bones\":{bones}}}}}}}").RootElement)!;

    /// <summary>Root → S1 → S2 → B (identity rotations, S2 1 above S1, B 1 in front of S2), one vertex on B.</summary>
    private static (MotionRig Rig, SecondaryMotion Motion) BlendRig(IReadOnlyDictionary<string, double>? blend)
    {
        var rig = new MotionRig(new[] { "mixamorigSpine1", "mixamorigSpine2", "B" }, new[] { -1, 0, 1 });
        rig.Local[0] = Affine.Identity;
        rig.Local[1] = Affine.Translation(0, 1, 0);
        rig.Local[2] = Affine.Translation(0, 0, 1);
        rig.UpdateWorld();
        var skin = new MotionSkin(new[] { 0, 1, 2 }, rig.World.Select(w => w.Inverted()).ToArray(), new[] { 0f, 1f, 1.5f },
                                  new[] { 2, 0, 0, 0 }, new[] { 1f, 0, 0, 0 });
        var motion = new SecondaryMotion(rig, skin.JointNodes, SecondaryMotion.MeasureCentroids(new[] { skin }),
                                         n => n == 2 ? blend : null, Payload("[\"B\"]"));
        return (rig, motion);
    }

    private static void Near(V3 got, double x, double y, double z, string what)
        => Assert.True(got.DistanceTo(new V3(x, y, z)) < 1e-5, $"{what}: ({got.X}, {got.Y}, {got.Z}) vs ({x}, {y}, {z})");

    private static Affine TurnS2(double deg) => RigMath.Compose(new V3(0, 1, 0), Quat.FromAxisAngle(new V3(1, 0, 0), deg * Math.PI / 180), new V3(1, 1, 1));

    [Fact]
    public void AnchorBlendFollowsTheShareWeightedBones()
    {
        double s20 = Math.Sin(20 * Math.PI / 180), c20 = Math.Cos(20 * Math.PI / 180);
        double s10 = Math.Sin(10 * Math.PI / 180), c10 = Math.Cos(10 * Math.PI / 180);
        // Without a blend B follows S2: head (0, 1 − sin20, cos20), +Z turned 20°.
        var (rig, motion) = BlendRig(null);
        rig.Local[1] = TurnS2(20);
        motion.Update(1.0 / 60);
        Near(rig.World[2].Position(), 0, 1 - s20, c20, "parent only: head");
        Near(rig.World[2].ApplyLinear(new V3(0, 0, 1)).Normalized(), 0, -s20, c20, "parent only: turn");
        // {S1: .5, S2: .5} (+ an unknown name, ignored): at bind the head stays (0, 1, 1); S2 at 20° gives the half
        // head (0, (2 − sin20)/2, (1 + cos20)/2) and half the turn (q10 exactly).
        (rig, motion) = BlendRig(new Dictionary<string, double> { ["mixamorig:Spine1"] = .5, ["mixamorig:Spine2"] = .5, ["mixamorig:Missing"] = .3 });
        motion.Update(1.0 / 60);
        Near(rig.World[2].Position(), 0, 1, 1, "blend at bind");
        rig.Local[1] = TurnS2(20);
        motion.Update(1.0 / 60);
        Near(rig.World[2].Position(), 0, (2 - s20) / 2, (1 + c20) / 2, "blend: head");
        Near(rig.World[2].ApplyLinear(new V3(0, 0, 1)).Normalized(), 0, -s10, c10, "blend: turn");
        // Moving the base by (5, 0, 0) moves both deltas alike: the head by exactly (5, 0, 0).
        rig.Base = Affine.Translation(5, 0, 0);
        motion.Update(1.0 / 60);
        Near(rig.World[2].Position(), 5, (2 - s20) / 2, (1 + c20) / 2, "blend: moved base");
    }

    /// <summary>
    /// A one-link swing: anchor → c1 → c2, c1 carries a ring at y −0.5 (lever L = 0.5), gravity 0, freq 2 Hz, ζ 1,
    /// gain 1, max_deg 180. The base steps along +x at 3 m/s for one 1/30 s frame: the particle follows vector [S3]
    /// (p = 0.03422162311801544 while the target moved 0.1), so it trails by d = 0.1 − 0.0342216 = 0.0657784 and the
    /// lever tilts by atan(d / L) = 7.4946° (soft limit: knee 90°, linear). axis_gain 1 and translate 0: rotation only.
    /// </summary>
    private static (MotionRig Rig, SecondaryMotion Motion) Swing()
    {
        var rig = new MotionRig(new[] { "anchor", "c1", "c2" }, new[] { -1, 0, 1 });
        rig.Local[0] = Affine.Identity;
        rig.Local[1] = Affine.Identity;
        rig.Local[2] = Affine.Translation(0, -1, 0);
        rig.UpdateWorld();
        var pos = new[] { .1f, -.5f, 0, -.1f, -.5f, 0, 0, -.5f, .1f, 0, -.5f, -.1f };
        var skin = new MotionSkin(new[] { 0, 1, 2 }, rig.World.Select(w => w.Inverted()).ToArray(), pos,
                                  new[] { 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0 },
                                  new[] { 1f, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0 });
        var payload = MotionPayload.Parse(JsonDocument.Parse("{\"rev\":\"s\",\"groups\":{\"swing\":{\"bones\":[\"c1\"],\"freq_hz\":2,"
            + "\"zeta\":1,\"gravity\":0,\"gravity_scale\":1,\"translate\":0,\"flatten\":0,\"sag_max_deg\":180,\"spill\":0,\"gain\":1,"
            + "\"max_deg\":180,\"squash\":[0.1,3],\"rest_deg\":0,\"rest_max_deg\":90}}}").RootElement);
        var motion = new SecondaryMotion(rig, skin.JointNodes, SecondaryMotion.MeasureCentroids(new[] { skin }), _ => null, payload);
        return (rig, motion);
    }

    /// <summary>The tilt of c1's lever (its −Y axis) towards −x, degrees.</summary>
    private static double Tilt(MotionRig rig)
    {
        var down = rig.World[1].ApplyLinear(new V3(0, -1, 0));
        return Math.Atan2(-down.X, -down.Y) * 180 / Math.PI;
    }

    private const double S3 = 0.03422162311801544;
    private static readonly double TrailDeg = Math.Atan((0.1 - S3) / 0.5) * 180 / Math.PI;

    [Fact]
    public void ABaseStepSwingsTheLinkLikeTheParticleVector()
    {
        var (rig, motion) = Swing();
        Assert.Equal(1, motion.ParticleCount);
        motion.Update(1.0 / 30);   // first frame: the particle starts at its target
        Assert.Equal(0, Tilt(rig), 9);
        rig.Base = Affine.Translation(0.1, 0, 0);
        motion.Update(1.0 / 30);
        Assert.Equal(7.494608, TrailDeg, 5);
        Assert.Equal(TrailDeg, Tilt(rig), 6);
        // No scale: rotation only (|columns| = 1).
        Assert.Equal(1, rig.World[1].ApplyLinear(new V3(1, 0, 0)).Length(), 9);
        Assert.Equal(1, rig.World[1].ApplyLinear(new V3(0, 1, 0)).Length(), 9);
        // c2 (not driven) rides on c1: its head at c1's head + R·(0, −1, 0).
        Near(rig.World[2].Position(), 0.1 - Math.Sin(TrailDeg * Math.PI / 180), -Math.Cos(TrailDeg * Math.PI / 180), 0, "c2 head");
    }

    [Fact]
    public void FrozenCarriesTheParticleAndKeepsTheTrail()
    {
        var (rig, motion) = Swing();
        motion.Update(1.0 / 30);
        rig.Base = Affine.Translation(0.1, 0, 0);
        motion.Update(1.0 / 30);
        // Frozen: p += T1 − T0 — the deviation stays exactly what it was, however far or long the base moves.
        rig.Base = Affine.Translation(0.2, 0, 0);
        motion.Update(1.0 / 30, frozen: true);
        Assert.Equal(TrailDeg, Tilt(rig), 6);
        motion.Update(1.0, frozen: true);   // a long frozen gap is no reset either
        Assert.Equal(TrailDeg, Tilt(rig), 6);
    }

    [Fact]
    public void GapFarAndResetSnapToTheTarget()
    {
        var (rig, motion) = Swing();
        motion.Update(1.0 / 30);
        rig.Base = Affine.Translation(0.1, 0, 0);
        motion.Update(1.0 / 30);
        Assert.True(Tilt(rig) > 7);
        // dt > 0.25: reset — the particle stands on its target, no swing.
        rig.Base = Affine.Translation(0.2, 0, 0);
        motion.Update(0.251);
        Assert.Equal(0, Tilt(rig), 9);
        // Reset() (the host's jump > 2 m): the next frame starts at the target although the base moved 3 m in 1/30 s.
        rig.Base = Affine.Translation(3.2, 0, 0);
        motion.Reset();
        motion.Update(1.0 / 30);
        Assert.Equal(0, Tilt(rig), 9);
        // Without the reset that same 3 m step (90 m/s) would swing it hard.
        rig.Base = Affine.Translation(6.2, 0, 0);
        motion.Update(1.0 / 30);
        Assert.True(Tilt(rig) > 45, $"tilt {Tilt(rig)}");
        // far: reset and gain 0 — no swing while the base keeps stepping.
        rig.Base = Affine.Translation(6.3, 0, 0);
        motion.Update(1.0 / 30, far: true);
        Assert.Equal(0, Tilt(rig), 9);
        rig.Base = Affine.Translation(6.4, 0, 0);
        motion.Update(1.0 / 30, far: true);
        Assert.Equal(0, Tilt(rig), 9);
    }

    [Fact]
    public void ConfigureWithoutTheBonesLetsGo()
    {
        var (rig, motion) = Swing();
        Assert.Contains(1, motion.Owned);
        motion.Configure(MotionPayload.Parse(JsonDocument.Parse("{\"rev\":\"x\",\"groups\":{}}").RootElement));
        Assert.Empty(motion.Owned);
        Assert.Equal(0, motion.ParticleCount);
        Assert.False(SecondaryMotion.Matches(rig, MotionPayload.Parse(JsonDocument.Parse("{\"rev\":\"x\",\"groups\":{\"g\":{\"bones\":[\"nope\"]}}}").RootElement)));
        Assert.True(SecondaryMotion.Matches(rig, MotionPayload.Parse(JsonDocument.Parse("{\"rev\":\"x\",\"groups\":{\"g\":{\"bones\":[\"mixamorig:C1\"]}}}").RootElement)));
    }

    // ---- skinned normals ----------------------------------------------------------------------------------------

    private static Affine Diag(double x, double y, double z) => new(x, 0, 0, 0, y, 0, 0, 0, z, 0, 0, 0);

    [Fact]
    public void GirthTwoTiltsTheStockNormalBy36Point87Degrees()
    {
        // C1's link: M = diag(2, 1, 2). n = (1, 1, 0)/√2: stock ∝ (2, 1, 0) at atan(1/2) = 26.565° above x, the
        // browser's ∝ (0.5, 1, 0) at atan(2) = 63.435°: 36.870° apart = 2·atan(2) − 90°, the largest over all normals.
        var m = Diag(2, 1, 2);
        var n = new V3(1, 1, 0).Normalized();
        Assert.Equal(36.869898, SkinNormals.ErrorDeg(m, n), 5);
        Assert.Equal(36.869898, SkinNormals.MaxErrorDeg(m), 5);
        Assert.Equal(0, SkinNormals.Correct(m, SkinNormals.Stock(m, n)).DistanceTo(SkinNormals.Browser(m, n)), 12);
        // A radial normal of the ring (no axial part) is not affected: (1, 0, 0) → (1, 0, 0) both ways.
        Assert.Equal(0, SkinNormals.ErrorDeg(m, new V3(1, 0, 0)), 9);
    }

    [Fact]
    public void TheCorrectionIsExactForBlendedShearedMatrices()
    {
        // A rotated, sheared, translated matrix (the paired-flatten case is a symmetric scale in an oblique frame).
        var r = RigMath.Compose(new V3(1, 2, 3), Quat.FromAxisAngle(new V3(0, 1, 0), .7), new V3(1, 1, 1));
        var s = new Affine(1.3, .2, 0, .2, .7, .1, 0, .1, 1.1, 0, 0, 0);
        var m = r.Times(s);
        foreach (var n in new[] { new V3(1, 0, 0), new V3(0, 1, 0), new V3(.3, -.5, .8).Normalized(), new V3(-1, 1, 1).Normalized() })
            Assert.Equal(0, SkinNormals.Correct(m, SkinNormals.Stock(m, n)).DistanceTo(SkinNormals.Browser(m, n)), 12);
        // Rotation and uniform scale: no error at all (rigid/uniform parity, smoke_secondary_motion.mjs).
        var uniform = RigMath.Compose(V3.Zero, Quat.FromAxisAngle(new V3(0, 1, 0), .7), new V3(2, 2, 2));
        Assert.Equal(0, SkinNormals.MaxErrorDeg(uniform), 6);
        Assert.Equal(0, SkinNormals.ErrorDeg(uniform, new V3(.3, -.5, .8).Normalized()), 6);
    }

    [Fact]
    public void ErrorOverTheBrowsersScaleRange()
    {
        // Singular values of an oblique symmetric scale: a rotated diag(1.45, 0.83, 0.83) still has σ 1.45 / 0.83.
        var q = Quat.FromAxisAngle(new V3(1, 2, 3).Normalized(), .9);
        var rot = RigMath.Compose(V3.Zero, q, new V3(1, 1, 1));
        var sym = rot.Times(Diag(1.45, 1 / Math.Sqrt(1.45), 1 / Math.Sqrt(1.45))).Times(RigMath.Compose(V3.Zero, q.Inverse(), new V3(1, 1, 1)));
        var (lo, hi) = SkinNormals.SingularRange(sym);
        Assert.Equal(1 / Math.Sqrt(1.45), lo, 9);
        Assert.Equal(1.45, hi, 9);
        // squash max 1.45 (perpendicular 1/√1.45): k = 1.45^1.5 = 1.74603 → 2·atan(k) − 90° = 30.40°.
        Assert.Equal(30.3981, SkinNormals.MaxErrorDeg(sym), 3);
        // A bounce of s = 1.1: k = 1.1^1.5 = 1.15369 → 8.16°.
        Assert.Equal(8.1635, SkinNormals.MaxErrorDeg(Diag(1.1, 1 / Math.Sqrt(1.1), 1 / Math.Sqrt(1.1))), 3);
        // Length 1.5 (C2): k = 1.5 → 22.62°.
        Assert.Equal(22.6199, SkinNormals.MaxErrorDeg(Diag(1, 1.5, 1)), 3);
    }

    [Fact]
    public void ShaderArrayIsColumnMajor()
    {
        var m = new Affine(1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12);
        var packed = SkinNormals.PackColumns(new[] { m }, 2);
        Assert.Equal(new float[] { 1, 2, 3, 4, 5, 6, 7, 8, 9, 1, 0, 0, 0, 1, 0, 0, 0, 1 }, packed);
    }
}
