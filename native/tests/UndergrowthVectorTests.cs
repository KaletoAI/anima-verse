using System;
using System.Linq;
using System.Text.Json.Nodes;
using AnimaNative.Scatter;
using AnimaNative.Tests.Vectors;
using Xunit;
using static AnimaNative.Tests.E3VectorAdapters;
using static AnimaNative.Tests.ScatterVectorAdapters;
using static AnimaNative.Tests.SceneVectorAdapters;

namespace AnimaNative.Tests;

/// <summary>
/// shared/test-vectors/undergrowth.json against the native undergrowth (hand derivation:
/// native/tests/Derivations/undergrowth.md). Until E3 the file had no C# consumer and ran only in the
/// browser scene's JS smoke; E3 deleted that scene, so this class is the vector's executor now.
///
/// <code>
///   TS fn                        C#                                 shape translation
///   wantedUndergrowthCells       UndergrowthMath.WantedCells        (x, z[, radius]) → ["cx,cz", …] nearest first
///   undergrowthCellSeed          UndergrowthMath.CellSeed
///   undergrowthDensityPer100m2   ScatterLod.UgDensityPer100m2
///   undergrowthCellCount         ScatterLod.UgCellCount
///   undergrowthHeight            ScatterLod.UgHeight
///   undergrowthShare             ScatterLod.UgShare
///   undergrowthVisible           ScatterLod.UgVisible               (index, dist)
///   undergrowthTint              UndergrowthMath.Tint               (r, g, b) → [r, g, b]
///   undergrowthShade             UndergrowthMath.Shade
///   undergrowthTexel             UndergrowthMath.TexturePixels      (row, col[, channel]) → RGBA or one byte
///   undergrowthRowInk            UndergrowthMath.TexturePixels      Σ alpha / 255 over one row
///   undergrowthGeometry          UndergrowthMath.Geometry + Normal  {positions, normals, indices}
/// </code>
/// </summary>
public class UndergrowthVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("undergrowth"));
    private static readonly Lazy<byte[]> Pixels = new(() => UndergrowthMath.TexturePixels());

    private static JsonArray Triples(float[] v) =>
        new(Enumerable.Range(0, v.Length / 3)
            .Select(i => (JsonNode?)new JsonArray((double)v[i * 3], (double)v[i * 3 + 1], (double)v[i * 3 + 2])).ToArray());

    private static readonly System.Collections.Generic.Dictionary<string, Func<JsonArray, JsonNode?>> Dispatch = new()
    {
        ["wantedUndergrowthCells"] = a =>
        {
            Arity(a, 2, 3);
            var cells = Arg(a, 2) is { } r
                ? UndergrowthMath.WantedCells(Num(a[0]), Num(a[1]), Num(r))
                : UndergrowthMath.WantedCells(Num(a[0]), Num(a[1]));
            return new JsonArray(cells.Select(c => (JsonNode?)UndergrowthMath.CellKey(c.Cx, c.Cz)).ToArray());
        },
        ["undergrowthCellSeed"] = a => UndergrowthMath.CellSeed(Str(Arity(a, 3, 3)[0]), Int(a[1]), Int(a[2])),
        ["undergrowthDensityPer100m2"] = a => ScatterLod.UgDensityPer100m2(Num(Arity(a, 1, 1)[0])),
        ["undergrowthCellCount"] = a => ScatterLod.UgCellCount(Num(Arity(a, 1, 1)[0])),
        ["undergrowthHeight"] = a => ScatterLod.UgHeight(Num(Arity(a, 1, 1)[0])),
        ["undergrowthShare"] = a => ScatterLod.UgShare(Num(Arity(a, 1, 1)[0])),
        ["undergrowthVisible"] = a => ScatterLod.UgVisible(Int(Arity(a, 2, 2)[0]), Num(a[1])),
        ["undergrowthTint"] = a =>
        {
            var (r, g, b) = UndergrowthMath.Tint(Num(Arity(a, 1, 1)[0]));
            return new JsonArray(r, g, b);
        },
        ["undergrowthShade"] = a => UndergrowthMath.Shade(Num(Arity(a, 2, 2)[0]), Num(a[1])),
        ["undergrowthTexel"] = a =>
        {
            Arity(a, 2, 3);
            int o = (Int(a[0]) * UndergrowthMath.TexSize + Int(a[1])) * 4;
            var px = Pixels.Value;
            return Arg(a, 2) is { } ch
                ? px[o + Int(ch)]
                : new JsonArray(px[o], px[o + 1], px[o + 2], px[o + 3]);
        },
        ["undergrowthRowInk"] = a =>
        {
            int row = Int(Arity(a, 1, 1)[0]), n = UndergrowthMath.TexSize;
            var px = Pixels.Value;
            double ink = 0;
            for (int c = 0; c < n; c++) ink += px[(row * n + c) * 4 + 3] / 255.0;
            return ink;
        },
        ["undergrowthGeometry"] = a =>
        {
            var (pos, _, index) = UndergrowthMath.Geometry(Num(Arity(a, 1, 1)[0]));
            var normals = Enumerable.Range(0, pos.Length / 3).SelectMany(_ => UndergrowthMath.Normal).ToArray();
            return new JsonObject
            {
                ["positions"] = Triples(pos),
                ["normals"] = Triples(normals),
                ["indices"] = new JsonArray(index.Select(i => (JsonNode?)(double)i).ToArray()),
            };
        },
    };

    public static TheoryData<string> Cases => VectorFile.Labels("undergrowth");

    [Theory, MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, Dispatch);

    [Fact]
    public void EveryFunctionIsDispatched() => AssertAllDispatched(File.Value, Dispatch);
}
