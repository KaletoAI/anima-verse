using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json.Nodes;
using AnimaNative.Sky;
using AnimaNative.Tests.Vectors;
using Xunit;
using static AnimaNative.Tests.E3VectorAdapters;
using static AnimaNative.Tests.SceneVectorAdapters;
using static AnimaNative.Tests.ScatterVectorAdapters;

namespace AnimaNative.Tests;

/// <summary>
/// shared/test-vectors/fog_veil.json against <see cref="FogVeil"/> (hand derivations:
/// client3d/scripts/smoke_fog_veil.mjs; TS source client3d/src/scene/fogVeilMath.ts).
///
/// <code>
///   TS fn           C#                   shape translation
///   fogCellOf       FogVeil.CellOf
///   fogParseCell    FogVeil.ParseCell    (cx, cz) ↔ [cx, cz] | null
///   fogGrid         FogVeil.Grid         FogGrid ↔ {cx0, cz0, cols, rows} | null
///   fogTexUv        FogVeil.TexUv        (u, v) ↔ [u, v]
///   fogTexIndex     FogVeil.TexIndex
///   fogHeightAlpha  FogVeil.HeightAlpha
///   fogVeilAlpha    FogVeil.VeilAlpha
///   e3Constants     E3VectorAdapters.Constants
/// </code>
/// </summary>
public class FogVeilVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("fog_veil"));

    private static FogGrid Grid(JsonNode? g) => new(Num(Key(g, "cx0")), Num(Key(g, "cz0")), Num(Key(g, "cols")), Num(Key(g, "rows")));

    private static readonly Dictionary<string, Func<JsonArray, JsonNode?>> Dispatch = new()
    {
        ["fogCellOf"] = a => FogVeil.CellOf(Num(Arity(a, 1, 1)[0])),
        ["fogParseCell"] = a => FogVeil.ParseCell(Str(Arity(a, 1, 1)[0])) is { } c ? new JsonArray(c.Cx, c.Cz) : null,
        ["fogGrid"] = a => FogVeil.Grid(((JsonArray)Arity(a, 1, 1)[0]!).Select(Str)) is { } g
            ? new JsonObject { ["cx0"] = g.Cx0, ["cz0"] = g.Cz0, ["cols"] = g.Cols, ["rows"] = g.Rows } : null,
        ["fogTexUv"] = a =>
        {
            var (u, v) = FogVeil.TexUv(Num(Arity(a, 3, 3)[0]), Num(a[1]), Grid(a[2]));
            return new JsonArray(u, v);
        },
        ["fogTexIndex"] = a => FogVeil.TexIndex(Num(Arity(a, 3, 3)[0]), Num(a[1]), Grid(a[2])),
        ["fogHeightAlpha"] = a => FogVeil.HeightAlpha(Num(Arity(a, 1, 1)[0])),
        ["fogVeilAlpha"] = a => FogVeil.VeilAlpha(Num(Arity(a, 2, 2)[0]), Num(a[1])),
        ["e3Constants"] = a =>
        {
            Arity(a, 0, 0);
            return Constants();
        },
    };

    public static TheoryData<string> Cases => VectorFile.Labels("fog_veil");

    [Theory, MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, Dispatch);

    /// <summary>Every fn of the file has a C# port in the table.</summary>
    [Fact]
    public void EveryFunctionDispatched() => AssertAllDispatched(File.Value, Dispatch);
}
