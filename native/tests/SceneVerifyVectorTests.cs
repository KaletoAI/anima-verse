using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json.Nodes;
using AnimaNative.Scene;
using AnimaNative.Tests.Vectors;
using Xunit;
using static AnimaNative.Tests.SceneVectorAdapters;
using static AnimaNative.Tests.ScatterVectorAdapters;

namespace AnimaNative.Tests;

/// <summary>
/// shared/test-vectors/scene_verify.json against <see cref="SceneVerify"/> (hand derivations:
/// client3d/scripts/smoke_scene_verify.mjs; TS source: packages/scene-render/src/verify.ts + primitives.ts).
///
/// <code>
///   TS fn            C#                           shape translation
///   inFrame          SceneVerify.InFrame          {min:{x,y,z}, max:{x,y,z}} ↔ VBox, {x,y,z} → Vec3
///   primitiveRows    SceneVerify.PrimitiveRows    [{field, actual, target}] → VerifyMeasurement
///   placementRows    SceneVerify.PlacementRows    spec → ScenePayload.ParseModel
///   wallTargets      SceneVerify.WallTargets      wall → ScenePayload walls[0]; serialised {field, target}
/// </code>
/// </summary>
public class SceneVerifyVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("scene_verify"));

    private static readonly Dictionary<string, Func<JsonArray, JsonNode?>> Dispatch = new()
    {
        ["inFrame"] = a =>
        {
            Arity(a, 2, 3);
            return BoxJson(SceneVerify.InFrame(Box(a[0]), XYZ(a[1]), Arg(a, 2) is { } y ? Num(y) : 0));
        },
        ["primitiveRows"] = a => ResultJson(SceneVerify.PrimitiveRows(Str(Arity(a, 2, 2)[0]),
            ((JsonArray)a[1]!).Select(m => new VerifyMeasurement(Str(Key(m, "field")), Num(Key(m, "actual")), Num(Key(m, "target")))).ToList())),
        ["placementRows"] = a =>
        {
            Arity(a, 4, 6);
            return ResultJson(SceneVerify.PlacementRows(Box(a[0]), XYZ(a[1]), Spec(a[2]), XYZ(a[3]),
                Arg(a, 4) is { } fy ? Num(fy) : 0, Arg(a, 5) is { } gl ? Num(gl) : 0));
        },
        ["wallTargets"] = a => new JsonArray(SceneVerify.WallTargets(SceneOf("walls", Arity(a, 1, 1)[0]).Walls.Single())
            .Select(t => (JsonNode?)new JsonObject { ["field"] = t.Field, ["target"] = t.Target }).ToArray()),
    };

    private static VBox Box(JsonNode? n) => new(XYZ(Key(n, "min")), XYZ(Key(n, "max")));

    private static JsonObject BoxJson(VBox b) => new() { ["min"] = Obj(b.Min), ["max"] = Obj(b.Max) };

    private static JsonObject ResultJson(VerifyResult r) => new()
    {
        ["checked"] = r.Checked,
        ["rows"] = new JsonArray(r.Rows.Select(x => (JsonNode?)new JsonObject
        {
            ["object"] = x.Object, ["field"] = x.Field, ["actual"] = x.Actual, ["target"] = x.Target, ["delta"] = x.Delta,
        }).ToArray()),
    };

    public static TheoryData<string> Cases => VectorFile.Labels("scene_verify");

    [Theory]
    [MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, Dispatch);

    [Fact]
    public void EveryFunctionIsDispatched() => Assert.Empty(File.Value.MissingFunctions(Dispatch));
}
