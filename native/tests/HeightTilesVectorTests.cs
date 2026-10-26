using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json.Nodes;
using AnimaNative.Ground;
using AnimaNative.Tests.Vectors;
using AnimaNative.World;
using Xunit;
using static AnimaNative.Tests.E3VectorAdapters;
using static AnimaNative.Tests.SceneVectorAdapters;
using static AnimaNative.Tests.ScatterVectorAdapters;

namespace AnimaNative.Tests;

/// <summary>
/// shared/test-vectors/height_tiles.json against the native height ground (hand derivations:
/// client3d/scripts/smoke_height_tiles.mjs, smoke_world_height.mjs; TS sources client3d/src/scene/heightTiles.ts,
/// packages/scene-render/src/worldHeight.ts, client3d/src/scene/waterRaster.ts).
///
/// <code>
///   TS fn              C#                                  shape translation
///   wantedTiles        LayerCut.WantedTiles                $set → set of keys
///   sampleWorldHeight  HeightGrid.Parse + Sample           the field through the payload parser; null = no grid
///   heightAt           WorldHeight.GroundAt                {tileM, overview, tiles: $map} → HeightfieldOverview + HeightTiles
///   tileKeyAt          LayerCut.TileKeyAt
///   latticeSample      HeightGrid.Sample                   row matrix (missing = 0) → the grid's row-major store
///   waterTileFrom      WaterTileField.Parse                (originX, originZ, step, wire) → {water: wire} on that lattice
/// </code>
/// </summary>
public class HeightTilesVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("height_tiles"));

    private static JsonArray Keys(IEnumerable<string> keys) => new(keys.Select(k => (JsonNode?)k).ToArray());

    private static JsonNode? FieldJson(WaterTileField? f)
    {
        if (f is null) return null;
        JsonArray IntRows(int[] v) => new(Enumerable.Range(0, f.Rows).Select(j => (JsonNode?)new JsonArray(
            Enumerable.Range(0, f.Cols).Select(i => (JsonNode?)(double)v[j * f.Cols + i]).ToArray())).ToArray());
        return new JsonObject
        {
            ["originX"] = f.OriginX, ["originZ"] = f.OriginZ, ["step"] = f.Step,
            ["level"] = Rows(f.Level, f.Rows, f.Cols), ["sd"] = Rows(f.Sd, f.Rows, f.Cols),
            ["flowX"] = f.FlowX is { } fx ? Rows(fx, f.Rows, f.Cols) : null,
            ["flowZ"] = f.FlowZ is { } fz ? Rows(fz, f.Rows, f.Cols) : null,
            ["kinds"] = Keys(f.Kinds), ["kindIdx"] = IntRows(f.KindIdx),
        };
    }

    /// <summary>The wire water block on a height lattice of its own size (rows = level rows, cols = first row).</summary>
    internal static WaterTileField? WaterTile(double originX, double originZ, double step, JsonNode? wire)
    {
        int rows = Key(wire, "level") is JsonArray lv ? lv.Count : 0;
        int cols = rows > 0 && Key(wire, "level") is JsonArray l0 && l0[0] is JsonArray r0 ? r0.Count : 0;
        var grid = new HeightGrid(originX, originZ, step, rows, cols, new float[rows * cols]);
        return WaterTileField.Parse(Element(new JsonObject { ["water"] = wire?.DeepClone() }), grid);
    }

    private static readonly Dictionary<string, Func<JsonArray, JsonNode?>> Dispatch = WithValues(new()
    {
        ["wantedTiles"] = a =>
        {
            Arity(a, 4, 5);
            var keys = Arg(a, 4) is { } r
                ? LayerCut.WantedTiles(Set(a[0]), Num(a[1]), Num(a[2]), Num(a[3]), Num(r))
                : LayerCut.WantedTiles(Set(a[0]), Num(a[1]), Num(a[2]), Num(a[3]));
            return Keys(keys);
        },
        ["sampleWorldHeight"] = a => Grid(Arity(a, 3, 3)[0]).Sample(Num(a[1]), Num(a[2])),
        ["heightAt"] = a =>
        {
            var c = Arity(a, 3, 3)[0];
            var root = Key(c, "overview") is JsonObject ov ? (JsonObject)ov.DeepClone() : new JsonObject();
            root["tile_m"] = c is null ? 0 : Num(Key(c, "tileM"));
            var world = new WorldHeight(HeightfieldOverview.Parse(Element(root)));
            if (c is not null)
                world.AddTiles(Map(Key(c, "tiles")).Select(kv => HeightfieldOverview.TryTileKey(kv.Key, out var key)
                    ? new HeightTile(key, Grid(kv.Value))
                    : throw new ArgumentException($"bad tile key {kv.Key}")));
            return world.GroundAt(Num(a[1]), Num(a[2]));
        },
        ["tileKeyAt"] = a => LayerCut.TileKeyAt(Num(Arity(a, 3, 3)[0]), Num(a[1]), Num(a[2])),
        ["latticeSample"] = a =>
        {
            Arity(a, 8, 8);
            var m = (JsonArray)a[0]!;
            int cols = Int(a[1]), rows = Int(a[2]);
            var h = new float[Math.Max(cols, 0) * Math.Max(rows, 0)];
            for (int j = 0; j < rows; j++)
            for (int i = 0; i < cols; i++)
                h[j * cols + i] = j < m.Count && m[j] is JsonArray row && i < row.Count && row[i] is { } v ? (float)Num(v) : 0;
            return new HeightGrid(Num(a[3]), Num(a[4]), Num(a[5]), rows, cols, h).Sample(Num(a[6]), Num(a[7]));
        },
        ["waterTileFrom"] = a => FieldJson(WaterTile(Num(Arity(a, 4, 4)[0]), Num(a[1]), Num(a[2]), a[3])),
    });

    /// <summary>
    /// The SECOND native reader of the want set: the boot ring of the world build asks
    /// <see cref="WorldHeight.IndexedTilesNear"/> which height tiles to fetch — the same <c>wantedTiles</c> rule.
    /// The index comes through the <c>/play/heightfield</c> parser (<c>tiles</c>, <c>tile_m</c>).
    /// </summary>
    private static readonly Dictionary<string, Func<JsonArray, JsonNode?>> BootRing = WithValues(new()
    {
        ["wantedTiles"] = a =>
        {
            Arity(a, 5, 5);
            var root = new JsonObject { ["tile_m"] = Num(a[1]), ["tiles"] = new JsonArray(Set(a[0]).Select(k => (JsonNode?)k).ToArray()) };
            var world = new WorldHeight(HeightfieldOverview.Parse(Element(root)));
            return Keys(world.IndexedTilesNear(Num(a[2]), Num(a[3]), Num(a[4])).Select(k => $"{k.Tx},{k.Tz}"));
        },
    });

    public static TheoryData<string> BootRingCases => DispatchedLabels("height_tiles", BootRing);

    [Theory, MemberData(nameof(BootRingCases))]
    public void BootRingCase(string label) => File.Value.AssertCase(label, BootRing);

    public static TheoryData<string> Cases => DispatchedLabels("height_tiles", Dispatch);

    [Theory, MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, Dispatch);

    /// <summary>The fns native has not ported yet — the next commit ports them; nothing is skipped silently.</summary>
    [Fact]
    public void PendingFunctions() => AssertPending(File.Value, Dispatch, "tileBatchesValue");
}
