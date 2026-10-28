using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json.Nodes;
using AnimaNative.Overview;
using AnimaNative.Tests.Vectors;
using Xunit;
using static AnimaNative.Tests.ScatterVectorAdapters;

namespace AnimaNative.Tests;

/// <summary>
/// shared/test-vectors/camera.json against the C# ports <see cref="CameraMath"/> and
/// <see cref="CameraFraming"/> (hand derivations: client3d/scripts/smoke_camera_math.mjs; TS sources:
/// client3d/src/scene/cameraMath.ts and cameraFraming.ts).
///
/// <code>
///   TS fn              C#                              shape translation
///   fitDistance        CameraMath.FitDistance          {min_x,max_x,min_z,max_z} | null → BoundsXZ?
///   worldCentreXZ      CameraMath.WorldCentreXZ        BoundsXZ? ; (X, Z) → [x, z]
///   basePitchDeg       CameraFraming.BasePitchDeg      omitted nearPitchDeg → the C# default
///   clampPitchDeg      CameraMath.ClampPitchDeg
///   wheelZoom          CameraMath.WheelZoom            number | null → double?
///   zoomTowardCursor   CameraMath.ZoomTowardCursor     [x,y,z] ↔ Vec3, [x,z] | null → (X, Z)?
///   damp               CameraMath.Damp
///   flyAdvance         CameraMath.FlyAdvance
///   flyEase            CameraMath.FlyEase
///   orbitStep          CameraMath.OrbitStep            OrbitState → {targetYaw, pitchOffset}
///   cameraPose         CameraMath.CameraPose           Vec3 → {pos: [x, y, z]}
/// </code>
///
/// Ported without a case of their own (reached through the cases above): WheelFactor, ZoomFloorOf,
/// ZoomCeiling, ClampZoom (inside WheelZoom), OrbitOffset (inside CameraPose).
/// </summary>
public class CameraVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("camera"));

    private static readonly Dictionary<string, Func<JsonArray, JsonNode?>> Dispatch = new()
    {
        ["fitDistance"] = a => JsonValue.Create(CameraMath.FitDistance(BoundsOrNull(Arity(a, 1, 1)[0]))),
        ["worldCentreXZ"] = a =>
        {
            var (x, z) = CameraMath.WorldCentreXZ(BoundsOrNull(Arity(a, 1, 1)[0]));
            return new JsonArray(x, z);
        },
        ["basePitchDeg"] = a =>
        {
            Arity(a, 1, 2);
            double dist = VectorCompare.Num(a[0]);
            var near = Arg(a, 1);
            return JsonValue.Create(near is null
                ? CameraFraming.BasePitchDeg(dist)
                : CameraFraming.BasePitchDeg(dist, VectorCompare.Num(near)));
        },
        ["clampPitchDeg"] = a => JsonValue.Create(CameraMath.ClampPitchDeg(
            VectorCompare.Num(Arity(a, 1, 2)[0]), BoolOrFalse(Arg(a, 1)))),
        ["wheelZoom"] = a => JsonValue.Create(CameraMath.WheelZoom(
            VectorCompare.Num(Arity(a, 4, 4)[0]), VectorCompare.Num(a[1]),
            VectorCompare.NumOrNull(a[2]), VectorCompare.NumOrNull(a[3]))),
        ["zoomTowardCursor"] = a => Vec3Json(CameraMath.ZoomTowardCursor(
            Vec(Arity(a, 4, 4)[0]), HitOrNull(a[1]), VectorCompare.Num(a[2]), VectorCompare.Num(a[3]))),
        ["damp"] = a => JsonValue.Create(CameraMath.Damp(VectorCompare.Num(Arity(a, 1, 1)[0]))),
        ["flyAdvance"] = a => JsonValue.Create(CameraMath.FlyAdvance(
            VectorCompare.Num(Arity(a, 2, 2)[0]), VectorCompare.Num(a[1]))),
        ["flyEase"] = a => JsonValue.Create(CameraMath.FlyEase(VectorCompare.Num(Arity(a, 1, 1)[0]))),
        ["orbitStep"] = a =>
        {
            var s = CameraMath.OrbitStep(VectorCompare.Num(Arity(a, 4, 5)[0]), VectorCompare.Num(a[1]),
                                         VectorCompare.Num(a[2]), VectorCompare.Num(a[3]), BoolOrFalse(Arg(a, 4)));
            return new JsonObject { ["targetYaw"] = s.TargetYaw, ["pitchOffset"] = s.PitchOffset };
        },
        ["cameraPose"] = a => new JsonObject
        {
            ["pos"] = Vec3Json(CameraMath.CameraPose(Vec(Arity(a, 4, 4)[0]), VectorCompare.Num(a[1]),
                                                     VectorCompare.Num(a[2]), VectorCompare.Num(a[3]))),
        },
    };

    // ---- shapes -------------------------------------------------------------------------------

    /// <summary>The TS <c>BoundsXZ | null</c> (<c>world_bounds</c>, snake_case keys).</summary>
    private static BoundsXZ? BoundsOrNull(JsonNode? node)
    {
        if (node is null) return null;
        if (node is not JsonObject o || o.Count != 4)
            throw new ArgumentException($"expected {{min_x, max_x, min_z, max_z}}, got {VectorCompare.Show(node)}");
        return new BoundsXZ(VectorCompare.Num(o["min_x"]), VectorCompare.Num(o["max_x"]),
                            VectorCompare.Num(o["min_z"]), VectorCompare.Num(o["max_z"]));
    }

    /// <summary>The TS <c>Vec3</c> tuple <c>[x, y, z]</c>.</summary>
    private static Vec3 Vec(JsonNode? node)
        => node is JsonArray v && v.Count == 3
            ? new Vec3(VectorCompare.Num(v[0]), VectorCompare.Num(v[1]), VectorCompare.Num(v[2]))
            : throw new ArgumentException($"expected [x, y, z], got {VectorCompare.Show(node)}");

    private static JsonArray Vec3Json(Vec3 v) => new(v.X, v.Y, v.Z);

    /// <summary>The cursor's ground hit <c>[x, z] | null</c>.</summary>
    private static (double X, double Z)? HitOrNull(JsonNode? node)
    {
        if (node is null) return null;
        var p = Point(node);
        return (p.X, p.Z);
    }

    /// <summary>A boolean; the TS default parameter <c>false</c> when not given.</summary>
    private static bool BoolOrFalse(JsonNode? node)
        => node is null ? false
            : node is JsonValue v && v.TryGetValue(out System.Text.Json.JsonElement el)
              && el.ValueKind is System.Text.Json.JsonValueKind.True or System.Text.Json.JsonValueKind.False
                ? el.ValueKind == System.Text.Json.JsonValueKind.True
                : throw new ArgumentException($"expected a boolean, got {VectorCompare.Show(node)}");

    // Task 46 adds TS-first E7 cases; Task 47 removes this explicit deferral
    // when their production ports arrive. Unknown functions still fail below.
    private static readonly HashSet<string> DeferredE7Functions = new(StringComparer.Ordinal)
    {
        "firstPersonZoomSequence", "restEyePoint", "eyeHeight", "viewHeading",
        "bodyYawForView", "zoomFloorOf", "zoomCeiling",
    };

    public static TheoryData<string> Cases
    {
        get
        {
            var rows = new TheoryData<string>();
            foreach (var c in File.Value.Cases.Where(c => !DeferredE7Functions.Contains(c.Fn)))
                rows.Add(c.Label);
            return rows;
        }
    }

    [Theory]
    [MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, Dispatch);

    [Fact]
    public void EveryFunctionIsDispatched()
        => Assert.Empty(File.Value.MissingFunctions(Dispatch).Except(DeferredE7Functions));

    [Fact]
    public void EveryDeferredE7FunctionHasVectors()
        => Assert.Empty(DeferredE7Functions.Except(File.Value.Cases.Select(c => c.Fn)));

    /// <summary>The constants the TS module exports, pinned to the same numbers.</summary>
    [Fact]
    public void ConstantsMatchTheTsModule()
    {
        Assert.Equal(0.8, CameraFraming.MinDist);
        Assert.Equal(150, CameraFraming.MaxDist);
        Assert.Equal(22.5 * Math.PI / 180, CameraMath.CameraHalfFov);
        Assert.Equal(1.15, CameraMath.CameraFitMargin);
        Assert.Equal(70, CameraMath.CameraFitEmpty);
        Assert.Equal(0.0012, CameraMath.WheelZoomRate);
        Assert.Equal(0.1, CameraMath.MaxFrameDt);
        Assert.Equal(1.6, CameraMath.FlyRate);
        Assert.Equal(0.005, CameraMath.OrbitYawPerPx);
        Assert.Equal(0.25, CameraMath.OrbitPitchDegPerPx);
        Assert.Equal(35, CameraMath.PitchOffsetLimitDeg);
        Assert.Equal(85, CameraMath.FirstPersonPitchOffsetLimitDeg);
    }

    /// <summary><c>wheelZoom</c> is exactly <c>clampZoom(targetDist · wheelFactor(deltaY))</c> (task 6 report, item 4).</summary>
    [Fact]
    public void WheelZoomIsClampOfFactor()
    {
        foreach (var (d, dy, floor, cap) in new (double, double, double?, double?)[]
                 { (80, 100, null, null), (30, 200, 0.8, 34), (2.2, -200, 2, null), (5, 0, 2, 1) })
            Assert.Equal(CameraMath.ClampZoom(d * CameraMath.WheelFactor(dy), floor, cap),
                         CameraMath.WheelZoom(d, dy, floor, cap));
    }
}
