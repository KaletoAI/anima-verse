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
///   waterAbsorb        WaterShade.Absorb
///   waterFoamAt        WaterShade.FoamAt
///   waterSurface       WaterShade.Surface
///   waterShallowRamp   WaterShade.ShallowRamp
///   waterShoreAlpha    WaterShade.ShoreAlpha
///   waterFoam          WaterShade.Foam
///   waterEdgeFade      WaterShade.EdgeFade
///   waterProfileOf     WaterProfile.Of             meta → JsonElement; profile ↔ the wire's snake_case object
///   waterLevelAt       WaterProfile.LevelAt        {axis} → its knots
///   waterfallsFrom     Waterfalls.From             profile and width as JSON values (TS unknown)
///   strokeWidthM       Waterfalls.StrokeWidthM
///   waterfallQuad      Waterfalls.Quad             {positions, bottom: [x, z]} | null
///   rasterLevelAt      WaterRaster.LevelAt         $raster → WaterRaster of WaterTileField.Parse tiles; NaN ↔ null
///   rasterSdAt         WaterRaster.SdAt
///   rasterKindAt       WaterRaster.KindAt
///   rasterFlowAt       WaterRaster.FlowAt          (x, z) ↔ [x, z]
///   waterBilinear      WaterRaster.WaterBilinear   {"$number": "NaN"} in, NaN out ↔ null
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

    /// <summary>An unknown-typed JSON argument (TS <c>unknown</c>) as the element the C# port reads; null = absent.</summary>
    private static System.Text.Json.JsonElement? Opt(JsonNode? n) => n is null ? null : Element(n);

    private static List<WaterKnot> Knots(JsonNode? axis)
        => ((JsonArray)axis!).Select(k => { var v = VectorCompare.NumList(k); return new WaterKnot(v[0], v[1], v[2], v[3]); }).ToList();

    private static JsonNode? ProfileJson(WaterProfile? p) => p is null ? null : new JsonObject
    {
        ["level_up"] = p.LevelUp, ["level_down"] = p.LevelDown, ["flow_dir_deg"] = p.FlowDirDeg,
        ["axis_x"] = p.AxisX, ["axis_z"] = p.AxisZ, ["dir_x"] = p.DirX, ["dir_z"] = p.DirZ,
        ["s_min"] = p.SMin, ["s_max"] = p.SMax,
        ["axis"] = new JsonArray(p.Axis.Select(k => (JsonNode?)new JsonArray(k.X, k.Z, k.S, k.Level)).ToArray()),
    };

    private static JsonObject FallJson(Waterfall f) => new()
    {
        ["x"] = f.X, ["z"] = f.Z, ["dirX"] = f.DirX, ["dirZ"] = f.DirZ, ["width"] = f.Width,
        ["topY"] = f.TopY, ["bottomY"] = f.BottomY, ["chordM"] = f.ChordM,
    };

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
        ["waterAbsorb"] = a => WaterShade.Absorb(Num(Arity(a, 3, 3)[0]), Num(a[1]), Num(a[2])),
        ["waterFoamAt"] = a => WaterShade.FoamAt(Num(Arity(a, 3, 3)[0]), Num(a[1]), Num(a[2])),
        ["waterSurface"] = a => WaterShade.Surface(Num(Arity(a, 4, 4)[0]), Num(a[1]), Num(a[2]), Num(a[3])),
        ["waterShallowRamp"] = a => WaterShade.ShallowRamp(Num(Arity(a, 2, 2)[0]), Num(a[1])),
        ["waterShoreAlpha"] = a => WaterShade.ShoreAlpha(Num(Arity(a, 2, 2)[0]), Num(a[1])),
        ["waterFoam"] = a => WaterShade.Foam(Num(Arity(a, 1, 1)[0])),
        ["waterEdgeFade"] = a => WaterShade.EdgeFade(Num(Arity(a, 2, 2)[0]), Num(a[1])),
        ["waterProfileOf"] = a => ProfileJson(WaterProfile.Of(Opt(Arity(a, 1, 1)[0]))),
        ["waterLevelAt"] = a => WaterProfile.LevelAt(Knots(Key(Arity(a, 3, 3)[0], "axis")), Num(a[1]), Num(a[2])),
        ["waterfallsFrom"] = a => new JsonArray(Waterfalls.From(Opt(Arity(a, 2, 2)[0]), Opt(a[1])).Select(f => (JsonNode?)FallJson(f)).ToArray()),
        ["strokeWidthM"] = a => Waterfalls.StrokeWidthM(Opt(Arity(a, 1, 1)[0])),
        ["waterfallQuad"] = a =>
        {
            var f = Arity(a, 1, 1)[0];
            var q = Waterfalls.Quad(new Waterfall(Num(Key(f, "x")), Num(Key(f, "z")), Num(Key(f, "dirX")), Num(Key(f, "dirZ")),
                Num(Key(f, "width")), Num(Key(f, "topY")), Num(Key(f, "bottomY")), Num(Key(f, "chordM"))));
            return q is null ? null : new JsonObject
            {
                ["positions"] = Nums(q.Positions), ["bottom"] = new JsonArray(q.Bottom.X, q.Bottom.Z),
            };
        },
        ["rasterLevelAt"] = a => NumOrNullOut(WaterRaster.LevelAt(Raster(Arity(a, 3, 3)[0]), Num(a[1]), Num(a[2]))),
        ["rasterSdAt"] = a => NumOrNullOut(WaterRaster.SdAt(Raster(Arity(a, 3, 3)[0]), Num(a[1]), Num(a[2]))),
        ["rasterKindAt"] = a => WaterRaster.KindAt(Raster(Arity(a, 3, 3)[0]), Num(a[1]), Num(a[2])),
        ["rasterFlowAt"] = a =>
        {
            var (x, z) = WaterRaster.FlowAt(Raster(Arity(a, 3, 3)[0]), Num(a[1]), Num(a[2]));
            return new JsonArray(x, z);
        },
        ["waterBilinear"] = a =>
        {
            Arity(a, 6, 6);
            return NumOrNullOut(WaterRaster.WaterBilinear(NumTag(a[0]), NumTag(a[1]), NumTag(a[2]), NumTag(a[3]), NumTag(a[4]), NumTag(a[5])));
        },
        ["waveNormalSample"] = a =>
        {
            Arity(a, 2, 3);
            return Bytes(WaterShade.WaveNormalSample(Int(a[0]), Int(a[1]), Arg(a, 2) is { } n ? Int(n) : 256));
        },
    });

    public static TheoryData<string> Cases => VectorFile.Labels("water");

    [Theory, MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, Dispatch);

    /// <summary>Every fn of the file has a C# port in the table.</summary>
    [Fact]
    public void EveryFunctionDispatched() => AssertAllDispatched(File.Value, Dispatch);
}
