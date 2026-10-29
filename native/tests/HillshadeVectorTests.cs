using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using AnimaNative.World;
using AnimaNative.Tests.Vectors;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>Task 55 / E7-T10: shared hand-derived hillshade vectors catch lamp/gradient inversion, border errors,
/// exaggeration, invalid fields and RGBA order; the source smoke carries the derivations, JSON the sole expectations.</summary>
public class HillshadeVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("hillshade"));
    public static TheoryData<string> Cases => VectorFile.Labels("hillshade");
    private static HillshadeImage? Image(JsonArray a)
    {
        HeightGrid? grid = null;
        if (a[0] is { } field)
        {
            using var doc = JsonDocument.Parse(field.ToJsonString());
            grid = HeightGrid.Parse(doc.RootElement, World.Json.Num(doc.RootElement, "step_m"));
        }
        return Hillshade.Build(grid, a.Count > 1 ? a[1] as JsonObject : null);
    }
    private static readonly Dictionary<string, Func<JsonArray, JsonNode?>> Dispatch = new()
    {
        ["hillshadeImage"] = a => Image(a)?.ToJson(),
        ["hillshadePixel"] = a =>
        {
            var image = Image(a)!;
            int p = (a[3]!.GetValue<int>() * image.Cols + a[2]!.GetValue<int>()) * 4;
            return new JsonArray(image.Data.Skip(p).Take(4).Select(b => (JsonNode?)JsonValue.Create((int)b)).ToArray());
        },
    };
    [Theory, MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, Dispatch);
}
