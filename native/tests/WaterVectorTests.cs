using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json.Nodes;
using AnimaNative.Scatter;
using AnimaNative.Tests.Vectors;
using AnimaNative.Water;
using Xunit;
using static AnimaNative.Tests.E3VectorAdapters;
using static AnimaNative.Tests.SceneVectorAdapters;
using static AnimaNative.Tests.ScatterVectorAdapters;

namespace AnimaNative.Tests;

/// <summary>
/// shared/test-vectors/water.json against the native water (hand derivations: client3d/scripts/smoke_water_shade.mjs,
/// smoke_water_plane.mjs, smoke_waterfall.mjs, smoke_world_height.mjs; TS sources client3d/src/scene/waterShade.ts,
/// waterPlaneMath.ts, waterRaster.ts, waterfall.ts, packages/scene-render/src/waterfall.ts, materials.ts).
///
/// <code>
///   TS fn              C#                          shape translation
///   waterInside        WaterShade.Inside
///   waterOpaqueDepthM  WaterShade.OpaqueDepthM     the depth value as the terrain payload hands it (meta.water_depth_effective)
///   waterLookFrom      WaterShade.LookFrom         spec → JsonElement; WaterLook ↔ {tint: [r, g, b], skyMix, …}
///   packWaterLook      WaterShade.Pack             WaterLook objects → WaterLook
///   waveNormalSample   WaterShade.WaveNormalSample
/// </code>
/// </summary>
public class WaterVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("water"));

    /// <summary>The bed depth the way the native client receives it: as <c>meta.water_depth_effective</c> of an area,
    /// read by the terrain payload parser.</summary>
    private static double? Depth(JsonNode? raw)
    {
        var area = new JsonObject { ["meta"] = new JsonObject { ["water_depth_effective"] = raw?.DeepClone() } };
        return TerrainPayload.Parse(Element(new JsonObject { ["areas"] = new JsonArray(area) })).Areas[0].WaterDepthEffective;
    }

    private static JsonObject LookJson(WaterLook l) => new()
    {
        ["tint"] = new JsonArray(l.Tint.R, l.Tint.G, l.Tint.B), ["skyMix"] = l.SkyMix, ["waveM"] = l.WaveM,
        ["speed"] = l.Speed, ["flowSpeed"] = l.FlowSpeed, ["opaqueDepthM"] = l.OpaqueDepthM,
        ["roughness"] = l.Roughness, ["metalness"] = l.Metalness,
    };

    private static WaterLook Look(JsonNode? o)
    {
        var t = VectorCompare.NumList(Key(o, "tint"));
        return new WaterLook((t[0], t[1], t[2]), Num(Key(o, "skyMix")), Num(Key(o, "waveM")), Num(Key(o, "speed")),
                             Num(Key(o, "flowSpeed")), Num(Key(o, "opaqueDepthM")), Num(Key(o, "roughness")), Num(Key(o, "metalness")));
    }

    private static readonly Dictionary<string, Func<JsonArray, JsonNode?>> Dispatch = WithValues(new()
    {
        ["waterInside"] = a => WaterShade.Inside(Num(Arity(a, 1, 1)[0])),
        ["waterOpaqueDepthM"] = a => WaterShade.OpaqueDepthM(Depth(Arity(a, 1, 1)[0])),
        ["waterLookFrom"] = a =>
        {
            Arity(a, 2, 2);
            return LookJson(WaterShade.LookFrom(a[0] is null ? null : Element(a[0]), Depth(a[1])));
        },
        ["packWaterLook"] = a => Floats(WaterShade.Pack(((JsonArray)Arity(a, 1, 1)[0]!).Select(Look).ToList())),
        ["waveNormalSample"] = a =>
        {
            Arity(a, 2, 3);
            return Bytes(WaterShade.WaveNormalSample(Int(a[0]), Int(a[1]), Arg(a, 2) is { } n ? Int(n) : 256));
        },
    });

    public static TheoryData<string> Cases => DispatchedLabels("water", Dispatch);

    [Theory, MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, Dispatch);

    /// <summary>The fns native has not ported yet — the next commit ports them; nothing is skipped silently.</summary>
    [Fact]
    public void PendingFunctions() => AssertPending(File.Value, Dispatch,
        "waterAbsorb", "waterFoamAt", "waterSurface", "waterShallowRamp", "waterProfileOf", "waterProfileOfValue",
        "waterShoreAlpha", "waterFoam", "waterEdgeFade", "waterfallsFrom", "waterfallsFromValue", "strokeWidthM",
        "rasterLevelAt", "rasterSdAt", "rasterKindAt", "rasterFlowAt", "waterBilinear", "waterfallQuad", "waterLevelAt");
}
