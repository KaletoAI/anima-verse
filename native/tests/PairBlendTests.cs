using System;
using System.Collections.Generic;
using System.Text.Json.Nodes;
using AnimaNative.Figures;
using AnimaNative.Tests.Vectors;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>Hand derivations: client3d/scripts/smoke_pair_blend.mjs; same vectors in both apps.</summary>
public class PairBlendTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("pair_blend"));
    public static TheoryData<string> Cases => VectorFile.Labels("pair_blend");
    private static PairPose Pose(JsonNode? n) => new(VectorCompare.Num(n!["x"]), VectorCompare.Num(n["y"]),
        VectorCompare.Num(n["z"]), VectorCompare.Num(n["yaw"]));
    public static readonly Dictionary<string, Func<JsonArray, JsonNode?>> Dispatch = new()
    {
        ["pairBlend"] = a => {
            var p = PairBlend.Sample(Pose(a[0]), Pose(a[1]), VectorCompare.Num(a[2]));
            return new JsonObject { ["weight"]=p.Weight, ["x"]=p.Pose.X, ["y"]=p.Pose.Y, ["z"]=p.Pose.Z, ["yaw"]=p.Pose.Yaw };
        },
    };
    [Theory, MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, Dispatch);
    [Fact]
    public void EveryFunctionIsDispatched() => Assert.Empty(File.Value.MissingFunctions(Dispatch));
}
