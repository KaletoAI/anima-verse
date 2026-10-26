using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using AnimaNative.Ground;
using AnimaNative.Tests.Vectors;
using AnimaNative.World;
using Xunit;
using static AnimaNative.Tests.SceneVectorAdapters;
using static AnimaNative.Tests.ScatterVectorAdapters;

namespace AnimaNative.Tests;

/// <summary>
/// The JSON adapters of the seven E3 vector files (terrain_lod, height_tiles, layer_ground, water, sky_light, backdrop,
/// fog_veil) — the C# twin of <c>client3d/scripts/e3VectorDispatch.mjs</c> / <c>e3VectorSupport.mjs</c>, contract in
/// <c>shared/test-vectors/README.md</c> § "E3 terrain, water and atmosphere". The tags (<c>$map</c>, <c>$set</c>,
/// <c>$grid</c>, <c>$plane</c>, <c>$pyramid</c>, <c>$capGrid</c>, <c>$layerWindow</c>, <c>$raster</c>, <c>$rng</c>,
/// <c>$select</c>, <c>$number</c>) are ordinary argument values, decoded here into the C# inputs; a tag that builds
/// an input through a ported function (<c>$pyramid</c> → <c>buildPyramid</c>, …) calls that port, never a second
/// implementation. A <c>fooValue</c> case calls <c>foo</c> and follows its property path on the JSON result.
/// </summary>
internal static class E3VectorAdapters
{
    /// <summary>Every fn of the file is in the table (a missing one would also fail its cases; this names them all).</summary>
    public static void AssertAllDispatched(VectorFile file, IReadOnlyDictionary<string, Func<JsonArray, JsonNode?>> dispatch)
        => Assert.Empty(file.MissingFunctions(dispatch));

    /// <summary>
    /// <c>e3Constants()</c>: the exported numeric constants of the E3 modules under their TS names, read from the C#
    /// constants (only the keys a case expects are compared).
    /// </summary>
    public static JsonObject Constants()
    {
        var c = new Dictionary<string, double>
        {
            ["LC_EDGE_NOISE_M"] = LayerCut.EdgeNoiseM, ["LC_EDGE_WAVE_M"] = LayerCut.EdgeWaveM,
            ["NG_DETAIL_SCALE"] = NaturalGround.DetailScale, ["NG_DETAIL_OFFSET"] = NaturalGround.DetailOffset,
            ["NG_MIX_M"] = NaturalGround.MixM, ["NG_MIX_MAX"] = NaturalGround.MixMax,
            ["NG_TINT_M"] = NaturalGround.TintM, ["NG_TINT_AMP"] = NaturalGround.TintAmp,
            ["NG_AO_RING_M"] = NaturalGround.AoRingM, ["NG_AO_SPAN_M"] = NaturalGround.AoSpanM,
            ["NG_AO_DOWN"] = NaturalGround.AoDown, ["NG_AO_UP"] = NaturalGround.AoUp,
            ["FOG_CELL_M"] = Sky.FogVeil.CellM, ["FOG_PAD_CELLS"] = Sky.FogVeil.PadCells, ["FOG_BLEND_M"] = Sky.FogVeil.BlendM,
            ["FOG_CLEAR_H_M"] = Sky.FogVeil.ClearHM, ["FOG_FULL_H_M"] = Sky.FogVeil.FullHM,
            ["FOG_ALPHA_MAX"] = Sky.FogVeil.AlphaMax, ["FOG_FADE_S"] = Sky.FogVeil.FadeS, ["FOG_TEX_MAX"] = Sky.FogVeil.TexMax,
            ["FOG_NEAR_M"] = Sky.Fog.NearM, ["FOG_FAR_M"] = Sky.Fog.FarM,
            ["SHADOW_HALF_M"] = Sky.ShadowSnap.HalfM, ["SHADOW_MAP_PX"] = Sky.ShadowSnap.MapPx,
            ["BACKDROP_DIST_M"] = Sky.Backdrop.DistM, ["BACKDROP_LAYER_GAP_M"] = Sky.Backdrop.LayerGapM,
            ["BACKDROP_LAYER_HEIGHT_K"] = Sky.Backdrop.LayerHeightK, ["BACKDROP_LAYERS"] = Sky.Backdrop.Layers,
            ["BACKDROP_SEGMENTS"] = Sky.Backdrop.Segments, ["RIDGE_MIN_SHARE"] = Sky.Backdrop.RidgeMinShare,
            ["RIDGE_TAPER_DEG"] = Sky.Backdrop.RidgeTaperDeg, ["BACKDROP_HEIGHT_MIN_M"] = Sky.Backdrop.HeightMinM,
            ["BACKDROP_HEIGHT_MAX_M"] = Sky.Backdrop.HeightMaxM, ["BACKDROP_HEIGHT_DEFAULT_M"] = Sky.Backdrop.HeightDefaultM,
            ["HEIGHT_TILE_RADIUS_M"] = Terrain.HeightTiles.RadiusM, ["HEIGHT_TILE_CACHE_MAX"] = Terrain.HeightTiles.CacheMax,
            ["HEIGHT_TILE_BATCH_MAX"] = Terrain.HeightTiles.BatchMax,
            ["PATCH_N"] = Terrain.TerrainLod.PatchN, ["MAX_LOD_LEVELS"] = Terrain.TerrainLod.MaxLodLevels,
            ["MIN_LOD_DISTANCE_M"] = Terrain.TerrainLod.MinLodDistanceM, ["MORPH_START"] = Terrain.TerrainLod.MorphStart,
            ["MAX_PIXEL_ERROR"] = Terrain.TerrainLod.MaxPixelError, ["MAX_RANGE_WIDENING"] = Terrain.TerrainLod.MaxRangeWidening,
            ["MAX_NODES"] = Terrain.TerrainLod.MaxNodes, ["LOD_CAP_NONE"] = Terrain.TerrainLod.LodCapNone,
            ["WATER_SD_DRY"] = WaterTileField.SdDry, ["WATER_SD_BAND_M"] = Water.WaterShade.SdBandM,
            ["WATER_EDGE_FADE_M"] = Water.WaterShade.EdgeFadeM, ["WATER_FOAM_BAND_M"] = Water.WaterShade.FoamBandM,
            ["WATER_FOAM_STRENGTH"] = Water.WaterShade.FoamStrength, ["WATER_FOAM_MIN_COVER"] = Water.WaterShade.FoamMinCover,
            ["WATER_SHALLOW_SURFACE_MIN"] = Water.WaterShade.ShallowSurfaceMin,
            ["WATER_MIN_SEE_DEPTH_M"] = Water.WaterShade.MinSeeDepthM, ["WATER_LOOK_TEXELS"] = 3,
            ["WATER_FLOW_SPEED_DEFAULT_M_S"] = Water.WaterShade.FlowSpeedDefault,
            ["WATERFALL_MIN_DROP_M"] = Water.Waterfalls.MinDropM, ["WATERFALL_MIN_SLOPE"] = Water.Waterfalls.MinSlope,
        };
        var o = new JsonObject();
        foreach (var (k, v) in c) o[k] = v;
        return o;
    }

    /// <summary>The labels of <paramref name="file"/> whose fn the table knows — for a second consumer of some fns.</summary>
    public static TheoryData<string> DispatchedLabels(string file, IReadOnlyDictionary<string, Func<JsonArray, JsonNode?>> dispatch)
    {
        var data = new TheoryData<string>();
        foreach (var c in VectorFile.Load(file).Cases)
            if (dispatch.ContainsKey(c.Fn)) data.Add(c.Label);
        return data;
    }

    /// <summary>Add <c>fooValue([fooArgs], path)</c> for every <c>foo</c> of the table.</summary>
    public static Dictionary<string, Func<JsonArray, JsonNode?>> WithValues(Dictionary<string, Func<JsonArray, JsonNode?>> d)
    {
        foreach (var (name, fn) in d.ToList())
            d[name + "Value"] = a => Path(fn((JsonArray)Arity(a, 2, 2)[0]!.DeepClone()), (JsonArray)a[1]!);
        return d;
    }

    /// <summary><c>vectorValue</c>: field names, array indices, and <c>length</c> of an array.</summary>
    public static JsonNode? Path(JsonNode? value, JsonArray path)
    {
        foreach (var step in path)
        {
            if (step is JsonValue v && v.TryGetValue(out JsonElement e) && e.ValueKind == JsonValueKind.String)
            {
                var key = e.GetString()!;
                value = value switch
                {
                    JsonArray arr when key == "length" => arr.Count,
                    JsonObject o => o.TryGetPropertyValue(key, out var x) ? x?.DeepClone() : throw new ArgumentException($"no field {key}"),
                    _ => throw new ArgumentException($"cannot read {key} of {VectorCompare.Show(value)}"),
                };
            }
            else
            {
                int i = Int(step);
                value = value is JsonArray arr && i >= 0 && i < arr.Count
                    ? arr[i]?.DeepClone()
                    : throw new ArgumentException($"no index {i} in {VectorCompare.Show(value)}");
            }
        }
        return value;
    }

    // ---- tags ---------------------------------------------------------------------------------

    /// <summary><c>{"$map": [[key, value], …]}</c> → ordered pairs.</summary>
    public static List<KeyValuePair<string, JsonNode?>> Map(JsonNode? node)
        => Key(node, "$map") is JsonArray pairs
            ? pairs.Select(p => new KeyValuePair<string, JsonNode?>(Str(((JsonArray)p!)[0]), ((JsonArray)p!)[1])).ToList()
            : throw new ArgumentException($"expected a $map, got {VectorCompare.Show(node)}");

    /// <summary><c>{"$set": [string, …]}</c> → a set.</summary>
    public static HashSet<string> Set(JsonNode? node)
        => Key(node, "$set") is JsonArray items
            ? items.Select(Str).ToHashSet(StringComparer.Ordinal)
            : throw new ArgumentException($"expected a $set, got {VectorCompare.Show(node)}");

    /// <summary>A number argument; <c>{"$number": "NaN"}</c> is the one non-finite input.</summary>
    public static double NumTag(JsonNode? node)
        => Key(node, "$number") is { } n
            ? Str(n) == "NaN" ? double.NaN : throw new ArgumentException($"unknown non-finite input {VectorCompare.Show(n)}")
            : Num(node);

    /// <summary><c>{"$plane": [a, b, c]}</c> → <c>(x, z) =&gt; a·x + b·z + c</c>; <c>{"$grid": field}</c> → the
    /// native <see cref="HeightGrid"/> sampler (<c>sampleWorldHeight</c>).</summary>
    public static Func<double, double, double> Sampler(JsonNode? node)
    {
        if (Key(node, "$plane") is JsonArray p)
        {
            double a = Num(p[0]), b = Num(p[1]), c = Num(p[2]);
            return (x, z) => a * x + b * z + c;
        }
        if (Key(node, "$grid") is { } g) return Grid(g).Sample;
        throw new ArgumentException($"expected a sampler tag, got {VectorCompare.Show(node)}");
    }

    /// <summary>A <c>WorldHeightField</c> through the native parser (its own <c>step_m</c>); null = the empty grid.</summary>
    public static HeightGrid Grid(JsonNode? field)
    {
        var e = Element(field);
        return HeightGrid.Parse(e, Json.Num(e, "step_m"));
    }

    /// <summary>A layer format object + tiles through <see cref="LayerCut.ParseBatch"/> (the native payload parser).</summary>
    public static LayerBatch LayerBatchOf(JsonNode? tilesMap, JsonNode? fmt)
    {
        var root = (JsonObject)fmt!.DeepClone();
        var tiles = new JsonObject();
        foreach (var (k, v) in Map(tilesMap)) tiles[k] = v?.DeepClone();
        root["tiles"] = tiles;
        return LayerCut.ParseBatch(Element(root));
    }

    /// <summary><c>{"$layerWindow": [map, format]}</c> → <see cref="LayerCut.Pack"/>.</summary>
    public static LayerMaskWindow? LayerWindow(JsonNode? node)
    {
        if (Key(node, "$layerWindow") is not JsonArray a) throw new ArgumentException($"expected a $layerWindow, got {VectorCompare.Show(node)}");
        var batch = LayerBatchOf(a[0], a[1]);
        return LayerCut.Pack(batch.Tiles, batch.Format);
    }

    /// <summary>The wire water block on a height lattice of its own size (rows = level rows, cols = first row).</summary>
    public static WaterTileField? WaterTile(double originX, double originZ, double step, JsonNode? wire)
    {
        int rows = Key(wire, "level") is JsonArray lv ? lv.Count : 0;
        int cols = rows > 0 && Key(wire, "level") is JsonArray l0 && l0[0] is JsonArray r0 ? r0.Count : 0;
        var grid = new HeightGrid(originX, originZ, step, rows, cols, new float[rows * cols]);
        return WaterTileField.Parse(Element(new JsonObject { ["water"] = wire?.DeepClone() }), grid);
    }

    /// <summary><c>{"$raster": {"tileM", "tiles": [[key, [originX, originZ, step, wire]], …]}}</c> → <see cref="Water.WaterRaster"/>.</summary>
    public static Water.WaterRaster Raster(JsonNode? node)
    {
        if (Key(node, "$raster") is not JsonObject r) throw new ArgumentException($"expected a $raster, got {VectorCompare.Show(node)}");
        var tiles = new Dictionary<string, WaterTileField>(StringComparer.Ordinal);
        foreach (var t in (JsonArray)r["tiles"]!)
        {
            var pair = (JsonArray)t!;
            var args = (JsonArray)pair[1]!;
            tiles[Str(pair[0])] = WaterTile(Num(args[0]), Num(args[1]), Num(args[2]), args[3])
                                  ?? throw new ArgumentException("a $raster tile without water");
        }
        return new Water.WaterRaster(Num(r["tileM"]), tiles);
    }

    public static JsonArray Bytes(IEnumerable<byte> b) => new(b.Select(x => (JsonNode?)(double)x).ToArray());

    public static JsonArray Floats(IEnumerable<float> f) => new(f.Select(x => (JsonNode?)(double)x).ToArray());

    /// <summary>A row-major float field as the TS <c>number[][]</c>; NaN (the dry sentinel) is <c>null</c>.</summary>
    public static JsonArray Rows(float[] f, int rows, int cols)
        => new(Enumerable.Range(0, rows).Select(j => (JsonNode?)new JsonArray(Enumerable.Range(0, cols)
               .Select(i => float.IsNaN(f[j * cols + i]) ? null : (JsonNode?)(double)f[j * cols + i]).ToArray())).ToArray());

    /// <summary>A double that may be NaN (water's dry output) as JSON — NaN is <c>null</c>.</summary>
    public static JsonNode? NumOrNullOut(double v) => double.IsFinite(v) ? v : null;
}
