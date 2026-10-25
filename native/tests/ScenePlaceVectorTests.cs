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
/// shared/test-vectors/scene_place.json against <see cref="PlaceTransform"/> (hand derivations:
/// client3d/scripts/smoke_place_rotation.mjs; TS source: packages/scene-render/src/placeTransform.ts).
///
/// <code>
///   TS fn            C#                        shape translation
///   placeTransform   PlaceTransform.Compute    spec → ScenePayload.ParseModel; MeshBox {min, max, matrix?}
///                                              → MeshBox; result → {fixPos, fitScale, outerScale, outerPos}
/// </code>
/// </summary>
public class ScenePlaceVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("scene_place"));

    private static readonly Dictionary<string, Func<JsonArray, JsonNode?>> Dispatch = new()
    {
        ["placeTransform"] = a =>
        {
            Arity(a, 2, 2);
            var r = PlaceTransform.Compute(Spec(a[0]), Boxes(a[1]));
            return new JsonObject
            {
                ["fixPos"] = Arr(r.FixPos), ["fitScale"] = Arr(r.FitScale),
                ["outerScale"] = r.OuterScale, ["outerPos"] = Arr(r.OuterPos),
            };
        },
    };

    internal static List<MeshBox> Boxes(JsonNode? node)
        => node is JsonArray a
            ? a.Select(b => new MeshBox(V3(Key(b, "min")), V3(Key(b, "max")),
                                        Key(b, "matrix") is { } m ? VectorCompare.NumList(m).ToArray() : null)).ToList()
            : throw new ArgumentException($"expected mesh boxes, got {VectorCompare.Show(node)}");

    public static TheoryData<string> Cases => VectorFile.Labels("scene_place");

    [Theory]
    [MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, Dispatch);

    [Fact]
    public void EveryFunctionIsDispatched() => Assert.Empty(File.Value.MissingFunctions(Dispatch));
}
