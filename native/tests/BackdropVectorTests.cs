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
/// shared/test-vectors/backdrop.json against <see cref="Backdrop"/> (hand derivations:
/// client3d/scripts/smoke_backdrop_math.mjs; TS source client3d/src/scene/backdropProfile.ts).
///
/// <code>
///   TS fn                 C#                        shape translation
///   layerRadiusM          Backdrop.LayerRadiusM
///   layerHeightFactor     Backdrop.LayerHeightFactor
///   clampBackdropHeightM  Backdrop.ClampHeightM     the value as the payload parser reads it: a finite number or none
///   ridgeDirection        Backdrop.RidgeDirection   (x, z) ↔ [x, z]
///   ridgeProfile          Backdrop.RidgeProfile     arcs [[start, end]]; {"$rng": […]} → a finite stream, absent = seeded
/// </code>
/// </summary>
public class BackdropVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("backdrop"));

    /// <summary><c>typeof h === 'number'</c>: what a JSON number reads as; a string or anything else is no height.</summary>
    private static double? Height(JsonNode? n) => n is null ? null : AnimaNative.World.Json.NumOrNull(Element(n));

    private static readonly Dictionary<string, Func<JsonArray, JsonNode?>> Dispatch = new()
    {
        ["layerRadiusM"] = a => Backdrop.LayerRadiusM(Num(Arity(a, 1, 1)[0])),
        ["layerHeightFactor"] = a => Backdrop.LayerHeightFactor(Num(Arity(a, 1, 1)[0])),
        ["clampBackdropHeightM"] = a => Backdrop.ClampHeightM(Height(Arity(a, 1, 1)[0])),
        ["ridgeDirection"] = a =>
        {
            var (x, z) = Backdrop.RidgeDirection(Num(Arity(a, 1, 1)[0]));
            return new JsonArray(x, z);
        },
        ["ridgeProfile"] = a =>
        {
            Arity(a, 3, 5);
            var arcs = ((JsonArray)a[1]!).Select(p => { var v = VectorCompare.NumList(p); return (v[0], v[1]); }).ToList();
            var rnd = Arg(a, 4) is { } r ? Feed(Key(r, "$rng") ?? throw new ArgumentException("expected a $rng")) : null;
            var pts = Backdrop.RidgeProfile(Num(a[0]), arcs, Height(a[2]), Arg(a, 3) is { } n ? Num(n) : Backdrop.Segments, rnd);
            return new JsonArray(pts.Select(p => (JsonNode?)new JsonObject
                { ["angleDeg"] = p.AngleDeg, ["peakH"] = p.PeakH, ["layer"] = p.Layer }).ToArray());
        },
    };

    public static TheoryData<string> Cases => VectorFile.Labels("backdrop");

    [Theory, MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, Dispatch);

    /// <summary>Every fn of the file has a C# port in the table.</summary>
    [Fact]
    public void EveryFunctionDispatched() => AssertAllDispatched(File.Value, Dispatch);
}
