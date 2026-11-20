using System;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.Json.Serialization;
using AnimaNative.Figures;
using AnimaNative.Tests.Vectors;
using Xunit;
using static AnimaNative.Tests.ScatterVectorAdapters;

namespace AnimaNative.Tests;

/// <summary>
/// shared/test-vectors/pair_scale.json against <see cref="PairScale"/> (hand derivations: scripts/smoke_pair_scale.mjs,
/// [8] = client3d/scripts/smoke_pair_root_sets.mjs [B] as the pure composition).
/// <code>
///   TS fn              C#                                          shape translation
///   pairFigureScale    PairScale.FigureScale                       height: number | null | undefined (= null) | NaN
///   pairPivotOf        PairScale.PivotOf                           the stored value as a JsonElement (undefined = default;
///                                                                  NaN serialised as the string "NaN": rejected either way)
///   scalePairRoot      PairScale.ScaleRoot                         {x, z} ↔ (X, Z), pivot {x, z} ↔ PairXZ
///   scalePairShift     PairScale.ScaleShift                        {x, z} ↔ (X, Z)
///   pairContactPoint   PivotOf + FigureScale + ScaleRoot           (p, pivot cm, height) → p' + a·(C − p), the body-fixed
///                                                                  contact point after scaling (= C)
///   pairPlacedRoot     FigureScale + ScaleRoot + PairClip.AnchorPoint   FigureManager.TickPair's order: scale, then the anchor
/// </code>
/// </summary>
public class PairScaleVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("pair_scale"));
    private static readonly JsonSerializerOptions NamedFloats = new() { NumberHandling = JsonNumberHandling.AllowNamedFloatingPointLiterals };

    private static double N(JsonNode? n) => VectorCompare.Num(n);
    private static bool IsUndefined(JsonNode? n) => n is JsonValue v && v.TryGetValue(out JsonElement e) && e.ValueKind == JsonValueKind.Undefined;
    private static double? Height(JsonNode? n) => n is null || IsUndefined(n) ? null : N(n);
    private static (double X, double Z) Xz(JsonNode? n) => (N(n!["x"]), N(n["z"]));
    private static PairXZ Pivot(JsonNode? n) => new(N(n!["x"]), N(n["z"]));
    private static JsonObject Out((double X, double Z) p) => new() { ["x"] = p.X, ["z"] = p.Z };

    private static JsonElement Element(JsonNode? n)
    {
        if (IsUndefined(n)) return default;
        return n is null ? JsonDocument.Parse("null").RootElement : JsonSerializer.SerializeToElement(n, NamedFloats);
    }

    private static readonly System.Collections.Generic.Dictionary<string, Func<JsonArray, JsonNode?>> Dispatch = new()
    {
        ["pairFigureScale"] = a => PairScale.FigureScale(Height(Arity(a, 1, 1)[0])),
        ["pairPivotOf"] = a => { var p = PairScale.PivotOf(Element(Arity(a, 1, 1)[0])); return Out((p.X, p.Z)); },
        ["scalePairRoot"] = a => Out(PairScale.ScaleRoot(Xz(Arity(a, 3, 3)[0]), Pivot(a[1]), N(a[2]))),
        ["scalePairShift"] = a => Out(PairScale.ScaleShift(Xz(Arity(a, 2, 2)[0]), N(a[1]))),
        ["pairContactPoint"] = a =>
        {
            var p = Xz(Arity(a, 3, 3)[0]);
            var c = PairScale.PivotOf(Element(a[1]));
            double s = PairScale.FigureScale(Height(a[2]));
            var q = PairScale.ScaleRoot(p, c, s);
            return Out((q.X + s * (c.X - p.X), q.Z + s * (c.Z - p.Z)));
        },
        ["pairPlacedRoot"] = a =>
        {
            var r = PairScale.ScaleRoot(Xz(Arity(a, 4, 4)[0]), Pivot(a[1]), PairScale.FigureScale(Height(a[2])));
            var anchor = a[3]!;
            return Out(PairClip.AnchorPoint(N(anchor["x"]), N(anchor["z"]), N(anchor["yaw"]), r.X, r.Z));
        },
    };

    public static TheoryData<string> Cases => VectorFile.Labels("pair_scale");

    [Theory]
    [MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, Dispatch);

    [Fact]
    public void EveryFunctionIsDispatched() => Assert.Empty(File.Value.MissingFunctions(Dispatch));

    [Fact]
    public void AllFortyTwoCasesAreConsumed() => Assert.Equal(42, File.Value.Cases.Count);

    /// <summary>[3] beyond the vector: a == 1 returns the very input (no arithmetic) — the bit-identity of a 1.70 m figure.</summary>
    [Fact]
    public void ScaleOneIsBitIdentical()
    {
        var p = (0.1 + 0.2, -0.3 / 7);
        Assert.Equal(p, PairScale.ScaleRoot(p, new PairXZ(0.12, 0.3), PairScale.FigureScale(1.7)));
        Assert.Equal(p, PairScale.ScaleShift(p, PairScale.FigureScale(null)));
    }

    /// <summary>The listing's <c>pair_pivot_cm</c> reaches the clip source entry; a row without one has the origin.</summary>
    [Fact]
    public void ListingCarriesThePivot()
    {
        using var listing = JsonDocument.Parse("""
            {"clips":[{"kind":"hug","role":"a","set":"","url":"/a.fbx","pair_pivot_cm":[12,30]},
                      {"kind":"hug","role":"b","set":"","url":"/b.fbx","pair_pivot_cm":null},
                      {"kind":"idle","set":"","url":"/i.fbx"}]}
            """);
        var entries = ClipLibraryRules.ParseEntries(listing.RootElement);
        Assert.Equal(new PairXZ(0.12, 0.3), entries[0].PairPivot);
        Assert.Equal(PairScale.Origin, entries[1].PairPivot);
        Assert.Equal(PairScale.Origin, entries[2].PairPivot);
    }
}
