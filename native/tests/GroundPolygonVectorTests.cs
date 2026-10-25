using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json.Nodes;
using AnimaNative.Scatter;
using AnimaNative.Tests.Vectors;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>
/// shared/test-vectors/ground_polygons.json against the C# ring helpers of <see cref="ScatterMath"/>
/// (hand derivations: client3d/scripts/smoke_ground_math.mjs; TS source:
/// packages/scene-render/src/groundAreas.ts).
///
/// <code>
///   TS fn          C#
///   signedArea     ScatterMath.SignedArea
///   polygonArea    ScatterMath.PolygonArea
///   cleanRing      ScatterMath.CleanRing
/// </code>
///
/// A ring is the TS <c>Point2[]</c>, <c>[[x, z], …]</c>. The adapters translate that shape to
/// <see cref="P2"/> and back; they never reinterpret a value.
/// </summary>
public class GroundPolygonVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("ground_polygons"));

    private static readonly Dictionary<string, Func<JsonArray, JsonNode?>> Dispatch = new()
    {
        ["signedArea"] = args => JsonValue.Create(ScatterMath.SignedArea(Ring(Single(args)))),
        ["polygonArea"] = args => JsonValue.Create(ScatterMath.PolygonArea(Ring(Single(args)))),
        ["cleanRing"] = args => RingJson(ScatterMath.CleanRing(Ring(Single(args)))),
    };

    /// <summary>The one argument of a one-argument function (a stray second one is a shape error).</summary>
    private static JsonNode? Single(JsonArray args)
        => args.Count == 1 ? args[0] : throw new ArgumentException($"expected 1 argument, got {args.Count}");

    /// <summary><c>[[x, z], …]</c> → points; a point must be exactly two numbers.</summary>
    private static List<P2> Ring(JsonNode? node)
        => node is JsonArray a
            ? a.Select(p => p is JsonArray xz && xz.Count == 2
                ? new P2(VectorCompare.Num(xz[0]), VectorCompare.Num(xz[1]))
                : throw new ArgumentException($"expected a point [x, z], got {VectorCompare.Show(p)}")).ToList()
            : throw new ArgumentException($"expected a ring, got {VectorCompare.Show(node)}");

    private static JsonArray RingJson(IEnumerable<P2> ring)
        => new(ring.Select(p => (JsonNode?)new JsonArray(p.X, p.Z)).ToArray());

    public static TheoryData<string> Cases => VectorFile.Labels("ground_polygons");

    [Theory]
    [MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, Dispatch);

    [Fact]
    public void EveryFunctionIsDispatched()
        => Assert.Empty(File.Value.MissingFunctions(Dispatch));
}
