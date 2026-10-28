using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json.Nodes;
using AnimaNative.Scatter;
using AnimaNative.Tests.Vectors;
using Xunit;
using static AnimaNative.Tests.ScatterVectorAdapters;
using static AnimaNative.Tests.Vectors.VectorCompare;

namespace AnimaNative.Tests;

/// <summary>Task 38 (E4-T3): the browser's impostor arithmetic, without Godot. Adapters only translate shapes;
/// the 44 shared cases catch window seams, thinning, framing, Y-only corners and retry/refuse drift.</summary>
public sealed class ImpostorVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("impostors"));
    private static readonly IReadOnlyDictionary<string, Func<JsonArray, JsonNode?>> Dispatch =
        new Dictionary<string, Func<JsonArray, JsonNode?>>
        {
            ["impostorInWindow"] = a => JsonValue.Create(ScatterLod.ImpostorInWindow(Num(Arity(a, 2, 2)[0]), Cfg(a[1]))),
            ["impostorShare"] = a => JsonValue.Create(ScatterLod.ImpostorShare(Num(Arity(a, 2, 2)[0]), Cfg(a[1]))),
            ["impostorVisible"] = a => JsonValue.Create(ScatterLod.ImpostorVisible(Int(Arity(a, 3, 3)[0]), Num(a[1]), Cfg(a[2]))),
            ["impostorWindowSpan"] = a => JsonValue.Create(ScatterLod.ImpostorWindowSpan(Num(Arity(a, 1, 1)[0]))),
            ["impostorReachM"] = a => JsonValue.Create(ScatterLod.ImpostorReachM(Num(Arity(a, 1, 1)[0]))),
            ["impostorYaw"] = a => JsonValue.Create(ScatterLod.ImpostorYaw(Num(Arity(a, 4, 4)[0]), Num(a[1]), Num(a[2]), Num(a[3]))),
            ["impostorFrame"] = a => ScatterLod.ImpostorFrame(Num(Arity(a, 2, 2)[0]), Num(a[1])) is { } f
                ? new JsonObject { ["spanH"] = f.SpanH, ["aspect"] = f.Aspect } : null,
            ["impostorQuad"] = a =>
            {
                Arity(a, 2, 2);
                if (a[1] is not JsonObject o || o.Any(k => k.Key is not ("spanH" or "aspect")))
                    throw new ArgumentException("expected frame {spanH, aspect}");
                var q = ScatterLod.ImpostorQuad(Num(a[0]), new ImpostorFrame(Num(o["spanH"]), Num(o["aspect"])));
                return new JsonObject { ["w"] = q.W, ["h"] = q.H, ["centreY"] = q.CentreY };
            },
            ["impostorCorners"] = a => new JsonArray(ScatterLod.ImpostorCorners(
                Num(Arity(a, 7, 7)[0]), Num(a[1]), Num(a[2]), Num(a[3]), Num(a[4]), Num(a[5]), Num(a[6]))
                .Select(p => (JsonNode?)new JsonArray(p.X, p.Y, p.Z)).ToArray()),
            ["impostorBakeVerdict"] = a => JsonValue.Create(ScatterLod.ImpostorBakeVerdict(Str(Arity(a, 1, 1)[0]))),
        };

    public static TheoryData<string> Cases => VectorFile.Labels("impostors");
    [Theory, MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, Dispatch);
    [Fact]
    public void EveryFunctionIsDispatched() => Assert.Empty(File.Value.MissingFunctions(Dispatch));

    /// <summary>A restart at share 1 or an inclusive near edge would change the set of trees at the seam.</summary>
    [Theory]
    [InlineData(35, 45, 120)]
    [InlineData(10, 20, 60)]
    public void CullSeamKeepsTheThinnedSet(double near, double far, double cull)
    {
        var cfg = new ScatterLodCfg(near, far, cull);
        Assert.False(ScatterLod.ImpostorInWindow(cull, cfg));
        Assert.Equal(ScatterLod.InstanceShare(cull, cfg), ScatterLod.ImpostorShare(cull + 1e-9, cfg), 10);
        for (int i = 0; i < 10000; i++)
            Assert.Equal(ScatterLod.InstanceVisible(i, cull, cfg), ScatterLod.ImpostorVisible(i, cull + 1e-9, cfg));
    }
}
