using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using AnimaNative.World;
using AnimaNative.Tests.Vectors;
using Xunit;
using static AnimaNative.Tests.ScatterVectorAdapters;
using static AnimaNative.Tests.Vectors.VectorCompare;

namespace AnimaNative.Tests;

/// <summary>Task 40 (E4-T5): all shared world-prop cases; the spec adapter only translates the native record.</summary>
public sealed class WorldPropVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("world_props"));
    private static JsonElement Row(JsonNode? n) => JsonSerializer.SerializeToElement(n);
    private static readonly IReadOnlyDictionary<string, Func<JsonArray, JsonNode?>> Dispatch =
        new Dictionary<string, Func<JsonArray, JsonNode?>>
        {
            ["worldPropLodCfg"] = a => { var c = WorldPropMath.LodCfg(Cfg(Arity(a, 1, 1)[0]));
                return new JsonObject { ["nearM"] = c.NearM, ["farM"] = c.FarM, ["cullM"] = c.CullM }; },
            ["worldPropTier"] = a => JsonValue.Create(AnimaNative.Scatter.ScatterLod.InstanceTier(
                Num(Arity(a, 3, 3)[0]), Tier(a[1]), WorldPropMath.LodCfg(Cfg(a[2])))),
            ["worldPropBottom"] = a => JsonValue.Create(WorldPropMath.Bottom(Row(Arity(a, 2, 2)[0]), Num(a[1]))),
            ["worldPropSceneSpec"] = a => {
                var s = WorldPropMath.SceneSpec(Row(Arity(a, 2, 2)[0]), Num(a[1]));
                return new JsonObject { ["role"] = s.Role, ["measure"] = s.Measure, ["max_m"] = s.MaxM,
                    ["anchor"] = new JsonArray(s.AnchorX, s.AnchorZ), ["bottom_y"] = s.BottomY,
                    ["variant"] = s.Variant, ["model_variants"] = JsonSerializer.SerializeToNode(s.ModelVariants) };
            },
        };
    public static TheoryData<string> Cases => VectorFile.Labels("world_props");
    [Theory, MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, Dispatch);
    [Fact] public void EveryFunctionIsDispatched() => Assert.Empty(File.Value.MissingFunctions(Dispatch));
}
