using System;
using System.Collections.Generic;
using System.Text.Json.Nodes;
using AnimaNative.Overview;
using AnimaNative.Scene;
using AnimaNative.Tests.Vectors;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>Task 53 / E7-T8: all occlusion.json corridor and fragment probes; derivations live in smoke_occlusion.mjs.</summary>
public class OcclusionVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("occlusion"));
    private static Vec3 Vec(JsonNode? p) => p is JsonArray a
        ? new(VectorCompare.Num(a[0]), VectorCompare.Num(a[1]), VectorCompare.Num(a[2]))
        : new(VectorCompare.Num(p!["x"]), VectorCompare.Num(p["y"]), VectorCompare.Num(p["z"]));
    private static JsonArray Arr(Vec3 p) => new(p.X, p.Y, p.Z);
    private static OcclusionState State(JsonNode p) => new(Vec(p["a"]), Vec(p["b"]), VectorCompare.Num(p["radius"]), VectorCompare.Num(p["strength"]));
    private static readonly Dictionary<string, Func<JsonArray, JsonNode?>> Dispatch = new()
    {
        ["occlusionUniforms"] = a =>
        {
            var s = Occlusion.Uniforms(Vec(a[0]), a[1] is null ? null : Vec(a[1]), a[2]!.GetValue<bool>());
            return new JsonObject { ["a"] = Arr(s.A), ["b"] = Arr(s.B), ["radius"] = s.Radius, ["strength"] = s.Strength };
        },
        ["occlusionHide"] = a => JsonValue.Create(Occlusion.Hide(State(a[0]!), Vec(a[1]), VectorCompare.Num(a[2]))),
        ["occlusionThreshold"] = a => JsonValue.Create(Occlusion.Threshold(VectorCompare.Num(a[0]), VectorCompare.Num(a[1]))),
        ["occlusionDiscard"] = a => JsonValue.Create(VectorCompare.Num(a[0]) > Occlusion.Threshold(VectorCompare.Num(a[1]), VectorCompare.Num(a[2]))),
    };
    public static TheoryData<string> Cases => VectorFile.Labels("occlusion");
    [Theory, MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, Dispatch);
    [Fact]
    public void EveryFunctionIsDispatched() => Assert.Empty(File.Value.MissingFunctions(Dispatch));

    [Fact]
    public void ShaderChainsCutsAndUsesFragmentWorldPosition()
    {
        var cut = CutShader.Inject("shader_type spatial;\nrender_mode cull_back;\nvoid fragment() { ALBEDO = vec3(1.0); }",
            CutShader.Pack(null, null, 0, new CutPlaneData(new Vec3(0,1,0), 0)));
        string code = OcclusionShader.Inject(cut);
        Assert.Contains("av_cut_discard", code);
        Assert.Contains("INV_VIEW_MATRIX * vec4(VERTEX, 1.0)", code);
        Assert.Contains("global uniform float av_occ_strength", code);
        Assert.Contains("av_occ_strength * occ_gate", code);
        Assert.Contains("if (av_occ_hide > av_occ_threshold)", code);
        Assert.Equal(code, OcclusionShader.Inject(code));
    }
}
