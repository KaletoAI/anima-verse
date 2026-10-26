using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json.Nodes;
using AnimaNative.Ground;
using AnimaNative.Terrain;
using AnimaNative.Tests.Vectors;
using AnimaNative.Water;
using Xunit;
using static AnimaNative.Tests.E3VectorAdapters;
using static AnimaNative.Tests.SceneVectorAdapters;
using static AnimaNative.Tests.ScatterVectorAdapters;

namespace AnimaNative.Tests;

/// <summary>
/// shared/test-vectors/terrain_lod.json against the native terrain math (hand derivations:
/// client3d/scripts/smoke_terrain_lod.mjs; TS source client3d/src/scene/terrainLod.ts).
///
/// <code>
///   TS fn             C#                           shape translation
///   lodRanges         TerrainLod.LodRanges
///   lodLambda         TerrainLod.LodLambda
///   liftedHeight      WaterShade.Lifted
///   liftedDepth       WaterShade.LiftedDepth
///   nearWindow        TerrainLod.NearWindow        {x0, z0, cols, rows} | null
///   levelErrorsFrom   TerrainLod.LevelErrorsFrom   $map of {err} → the err lists in map order
///   nodeBounds        TerrainLod.NodeBounds        $map of {min, max} → key → NodeStatSpan
///   selectLodNodes    TerrainLod.SelectLodNodes    $select → LodSelectOpts with a constant BoundsOf
///   selectLodFitted   TerrainLod.SelectLodFitted
///   buildPyramid      TerrainLod.BuildPyramid      $plane / $grid → sampler
///   pyramidLevelFor   TerrainLod.PyramidLevelFor   $pyramid → TerrainLod.BuildPyramid
///   morphedVertex     TerrainLod.MorphedVertex     node {x, z, size, level, cells, morph}; t given or the node's
///   lodVertex         TerrainLod.LodVertex         cam {x, y, z}
///   fragmentNormal    TerrainNormal.NormalAt       $pyramid's level 0 as a HeightLattice; nearRect [x0, z0, x1, z1]
///   buildLodCapGrid   TerrainLod.BuildLodCapGrid   $map → ordered (key, cap) pairs
///   lodCapAt          TerrainLod.LodCapAt          $capGrid → TerrainLod.BuildLodCapGrid
///   lodCapOverSquare  TerrainLod.LodCapOverSquare
///   waterTileCaps     TerrainLod.WaterTileCaps     ordered (key, cap) pairs ↔ [[key, cap], …]
/// </code>
/// </summary>
public class TerrainLodVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("terrain_lod"));

    /// <summary><c>{"$pyramid": [sampler, originX, originZ, step, cols, rows, levels]}</c> → <see cref="TerrainLod.BuildPyramid"/>; null = none.</summary>
    private static HeightPyramid? Pyramid(JsonNode? node)
    {
        if (node is null) return null;
        if (Key(node, "$pyramid") is not JsonArray p) throw new ArgumentException($"expected a $pyramid, got {VectorCompare.Show(node)}");
        return TerrainLod.BuildPyramid(Sampler(p[0]), Num(p[1]), Num(p[2]), Num(p[3]), Num(p[4]), Num(p[5]), Int(p[6]));
    }

    /// <summary>A pyramid's level 0 as the <see cref="HeightLattice"/> <see cref="TerrainNormal"/> reads (rows are contiguous: texW = cols).</summary>
    private static HeightLattice? Level0(HeightPyramid? pyr)
    {
        if (pyr is null) return null;
        var lv = pyr.Levels[0];
        return new HeightLattice { OriginX = pyr.OriginX, OriginZ = pyr.OriginZ, Step = lv.Step, Cols = lv.Cols, Rows = lv.Rows,
                                   H = pyr.Data.Take(lv.Cols * lv.Rows).ToArray() };
    }

    private static JsonNode? PyramidJson(HeightPyramid p) => new JsonObject
    {
        ["originX"] = p.OriginX, ["originZ"] = p.OriginZ, ["step"] = p.Step, ["texW"] = p.TexW, ["texH"] = p.TexH,
        ["levels"] = new JsonArray(p.Levels.Select(l => (JsonNode?)new JsonObject
            { ["cols"] = l.Cols, ["rows"] = l.Rows, ["step"] = l.Step, ["row0"] = l.Row0 }).ToArray()),
        ["data"] = Floats(p.Data),
    };

    private static List<double>? NumsOrNull(JsonNode? n) => n is null ? null : VectorCompare.NumList(n);

    private static LodNode Node(JsonNode? n) => new(Num(Key(n, "x")), Num(Key(n, "z")), Num(Key(n, "size")), Int(Key(n, "level")),
                                                    Int(Key(n, "cells")), Num(Key(n, "morph")));

    private static JsonObject NodeJson(LodNode n) => new()
    {
        ["x"] = n.X, ["z"] = n.Z, ["size"] = n.Size, ["level"] = n.Level, ["cells"] = n.Cells, ["morph"] = n.Morph,
    };

    private static JsonArray NodesJson(IEnumerable<LodNode> nodes) => new(nodes.Select(n => (JsonNode?)NodeJson(n)).ToArray());

    private static readonly string[] SelectKeys =
        { "x0", "z0", "x1", "z1", "leafM", "levels", "minLodDistance", "camX", "camY", "camZ", "bounds", "levelErrorM", "pixelScale", "ranges" };

    /// <summary><c>{"$select": {...options, "bounds": {min, max}}}</c> → options with a constant <c>boundsOf</c>.</summary>
    private static LodSelectOpts Select(JsonNode? node)
    {
        if (Key(node, "$select") is not JsonObject o) throw new ArgumentException($"expected a $select, got {VectorCompare.Show(node)}");
        var unknown = o.Select(kv => kv.Key).Where(k => !SelectKeys.Contains(k)).ToList();
        if (unknown.Count > 0) throw new ArgumentException($"$select: unknown key(s) {string.Join(", ", unknown)}");
        var b = new NodeStatSpan(Num(Key(Key(o, "bounds"), "min")), Num(Key(Key(o, "bounds"), "max")));
        return new LodSelectOpts(Num(o["x0"]), Num(o["z0"]), Num(o["x1"]), Num(o["z1"]), Num(o["leafM"]), Num(o["levels"]),
                                 Num(o["minLodDistance"]), Num(o["camX"]), Num(o["camY"]), Num(o["camZ"]), (_, _, _) => b)
        {
            LevelErrorM = NumsOrNull(Key(o, "levelErrorM")),
            PixelScale = Key(o, "pixelScale") is { } ps ? Num(ps) : null,
            Ranges = NumsOrNull(Key(o, "ranges")),
        };
    }

    /// <summary><c>{"$capGrid": [map, tileM]}</c> → <see cref="TerrainLod.BuildLodCapGrid"/>.</summary>
    private static LodCapGrid? CapGrid(JsonNode? node)
    {
        if (Key(node, "$capGrid") is not JsonArray a) throw new ArgumentException($"expected a $capGrid, got {VectorCompare.Show(node)}");
        return TerrainLod.BuildLodCapGrid(CapMap(a[0]), Num(a[1]));
    }

    private static List<KeyValuePair<string, double>> CapMap(JsonNode? map)
        => Map(map).Select(kv => new KeyValuePair<string, double>(kv.Key, Num(kv.Value))).ToList();

    private static JsonObject VertexJson(LodVertexPos v, bool withT)
    {
        var o = new JsonObject { ["x"] = v.X, ["z"] = v.Z, ["y"] = v.Y };
        if (withT) o["t"] = v.T;
        return o;
    }

    private static readonly Dictionary<string, Func<JsonArray, JsonNode?>> Dispatch = new()
    {
        ["lodRanges"] = a =>
        {
            Arity(a, 2, 4);
            return Nums(TerrainLod.LodRanges(Num(a[0]), Num(a[1]), NumsOrNull(Arg(a, 2)), Arg(a, 3) is { } ps ? Num(ps) : null));
        },
        ["lodLambda"] = a => TerrainLod.LodLambda(Num(Arity(a, 2, 2)[0]), VectorCompare.NumList(a[1])),
        ["liftedHeight"] = a => WaterShade.Lifted(Num(Arity(a, 3, 3)[0]), NumTag(a[1]), Num(a[2])),
        ["liftedDepth"] = a => WaterShade.LiftedDepth(Num(Arity(a, 3, 3)[0]), NumTag(a[1]), Num(a[2])),
        ["nearWindow"] = a =>
        {
            Arity(a, 6, 6);
            var keys = ((JsonArray)a[0]!).Select(Str).ToList();
            var w = TerrainLod.NearWindow(keys, Num(a[1]), Num(a[2]), a[3] is null ? null : Num(a[3]), Num(a[4]), Num(a[5]));
            return w is { } r ? new JsonObject { ["x0"] = r.X0, ["z0"] = r.Z0, ["cols"] = r.Cols, ["rows"] = r.Rows } : null;
        },
        ["levelErrorsFrom"] = a =>
        {
            Arity(a, 4, 4);
            var errs = Map(a[0]).Select(kv => (IReadOnlyList<double>?)NumsOrNull(Key(kv.Value, "err"))).ToList();
            return Nums(TerrainLod.LevelErrorsFrom(errs, NumsOrNull(a[1]), Num(a[2]), Int(a[3])));
        },
        ["nodeBounds"] = a =>
        {
            Arity(a, 6, 6);
            var stats = Map(a[0]).ToDictionary(kv => kv.Key, kv => new NodeStatSpan(Num(Key(kv.Value, "min")), Num(Key(kv.Value, "max"))));
            var g = new NodeStatSpan(Num(Key(a[2], "min")), Num(Key(a[2], "max")));
            var b = TerrainLod.NodeBounds(stats, Num(a[1]), g, Num(a[3]), Num(a[4]), Num(a[5]));
            return new JsonObject { ["min"] = b.Min, ["max"] = b.Max };
        },
        ["selectLodNodes"] = a => NodesJson(TerrainLod.SelectLodNodes(Select(Arity(a, 1, 1)[0]))),
        ["selectLodFitted"] = a =>
        {
            var r = TerrainLod.SelectLodFitted(Select(Arity(a, 1, 1)[0]));
            return new JsonObject
            {
                ["nodes"] = NodesJson(r.Nodes), ["ranges"] = Nums(r.Ranges), ["coarsenings"] = r.Coarsenings, ["capRelax"] = r.CapRelax,
            };
        },
        ["buildPyramid"] = a =>
        {
            Arity(a, 7, 7);
            return PyramidJson(TerrainLod.BuildPyramid(Sampler(a[0]), Num(a[1]), Num(a[2]), Num(a[3]), Num(a[4]), Num(a[5]), Int(a[6])));
        },
        ["pyramidLevelFor"] = a => TerrainLod.PyramidLevelFor(Pyramid(Arity(a, 2, 2)[0]), Num(a[1])),
        ["morphedVertex"] = a =>
        {
            Arity(a, 6, 10);
            var v = TerrainLod.MorphedVertex(Node(a[0]), Num(a[1]), Num(a[2]), Pyramid(a[3]), NumsOrNull(a[4]), Pyramid(a[5]),
                NumsOrNull(Arg(a, 6)), Arg(a, 7) is { } t ? Num(t) : null, Pyramid(Arg(a, 8)),
                Arg(a, 9) is null ? null : throw new ArgumentException("no $sd tag in the contract"));
            return VertexJson(v, withT: false);
        },
        ["lodVertex"] = a =>
        {
            Arity(a, 9, 9);
            var c = a[7];
            var v = TerrainLod.LodVertex(Node(a[0]), Num(a[1]), Num(a[2]), Pyramid(a[3]), NumsOrNull(a[4]), Pyramid(a[5]),
                NumsOrNull(a[6]), new LodCamera(Num(Key(c, "x")), Num(Key(c, "y")), Num(Key(c, "z"))), VectorCompare.NumList(a[8]));
            return VertexJson(v, withT: true);
        },
        ["fragmentNormal"] = a =>
        {
            Arity(a, 6, 6);
            var rect = a[1] is null ? null : VectorCompare.NumList(a[1]).ToArray();
            var (x, y, z) = TerrainNormal.NormalAt(Level0(Pyramid(a[0])), rect, Level0(Pyramid(a[2])), Num(a[5]), Num(a[3]), Num(a[4]));
            return new JsonObject { ["x"] = x, ["y"] = y, ["z"] = z };
        },
        ["buildLodCapGrid"] = a =>
        {
            var g = TerrainLod.BuildLodCapGrid(CapMap(Arity(a, 2, 2)[0]), Num(a[1]));
            return g is null ? null : new JsonObject
            {
                ["x0"] = g.X0, ["z0"] = g.Z0, ["step"] = g.Step, ["cols"] = g.Cols, ["rows"] = g.Rows, ["min"] = g.Min,
                ["caps"] = Floats(g.Caps),
            };
        },
        ["lodCapAt"] = a => TerrainLod.LodCapAt(CapGrid(Arity(a, 3, 3)[0]), Num(a[1]), Num(a[2])),
        ["lodCapOverSquare"] = a => TerrainLod.LodCapOverSquare(CapGrid(Arity(a, 4, 4)[0]), Num(a[1]), Num(a[2]), Num(a[3])),
        ["waterTileCaps"] = a =>
        {
            Arity(a, 4, 5);
            if (a[3] is not null) throw new ArgumentException("no $sd tag in the contract");
            var caps = Arg(a, 4) is { } lc
                ? TerrainLod.WaterTileCaps(Pyramid(a[0]), Pyramid(a[1]), Num(a[2]), null, Int(lc))
                : TerrainLod.WaterTileCaps(Pyramid(a[0]), Pyramid(a[1]), Num(a[2]), null);
            return new JsonArray(caps.Select(kv => (JsonNode?)new JsonArray(kv.Key, kv.Value)).ToArray());
        },
    };

    public static TheoryData<string> Cases => VectorFile.Labels("terrain_lod");

    [Theory, MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, Dispatch);

    /// <summary>Every fn of the file has a C# port in the table.</summary>
    [Fact]
    public void EveryFunctionDispatched() => AssertAllDispatched(File.Value, Dispatch);
}
