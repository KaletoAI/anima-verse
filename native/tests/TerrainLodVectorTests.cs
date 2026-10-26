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
///   TS fn            C#                         shape translation
///   liftedHeight     WaterShade.Lifted
///   nearWindow       TerrainLod.NearWindow      {x0, z0, cols, rows} | null
///   fragmentNormal   TerrainNormal.NormalAt     $pyramid → its level 0 as a HeightLattice; nearRect [x0, z0, x1, z1]
/// </code>
/// </summary>
public class TerrainLodVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("terrain_lod"));

    /// <summary>
    /// The base level of <c>{"$pyramid": [sampler, originX, originZ, step, cols, rows, levels]}</c> — what
    /// <c>buildPyramid</c> writes into level 0 (the sampler at every lattice point, stored as float32) and the only
    /// level <see cref="TerrainNormal"/> reads.
    /// </summary>
    private static HeightLattice? Level0(JsonNode? node)
    {
        if (node is null) return null;
        if (Key(node, "$pyramid") is not JsonArray p) throw new ArgumentException($"expected a $pyramid, got {VectorCompare.Show(node)}");
        var at = Sampler(p[0]);
        double ox = Num(p[1]), oz = Num(p[2]), step = Num(p[3]);
        int cols = Math.Max(2, (int)Math.Floor(Num(p[4]))), rows = Math.Max(2, (int)Math.Floor(Num(p[5])));
        var h = new float[cols * rows];
        for (int j = 0; j < rows; j++)
        for (int i = 0; i < cols; i++)
            h[j * cols + i] = (float)at(ox + i * step, oz + j * step);
        return new HeightLattice { OriginX = ox, OriginZ = oz, Step = step, Cols = cols, Rows = rows, H = h };
    }

    private static readonly Dictionary<string, Func<JsonArray, JsonNode?>> Dispatch = new()
    {
        ["liftedHeight"] = a => WaterShade.Lifted(Num(Arity(a, 3, 3)[0]), NumTag(a[1]), Num(a[2])),
        ["nearWindow"] = a =>
        {
            Arity(a, 6, 6);
            var keys = ((JsonArray)a[0]!).Select(Str).ToList();
            var w = TerrainLod.NearWindow(keys, Num(a[1]), Num(a[2]), a[3] is null ? null : Num(a[3]), Num(a[4]), Num(a[5]));
            return w is { } r ? new JsonObject { ["x0"] = r.X0, ["z0"] = r.Z0, ["cols"] = r.Cols, ["rows"] = r.Rows } : null;
        },
        ["fragmentNormal"] = a =>
        {
            Arity(a, 6, 6);
            var rect = a[1] is null ? null : VectorCompare.NumList(a[1]).ToArray();
            var (x, y, z) = TerrainNormal.NormalAt(Level0(a[0]), rect, Level0(a[2]), Num(a[5]), Num(a[3]), Num(a[4]));
            return new JsonObject { ["x"] = x, ["y"] = y, ["z"] = z };
        },
    };

    public static TheoryData<string> Cases => DispatchedLabels("terrain_lod", Dispatch);

    [Theory, MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, Dispatch);

    /// <summary>The fns native has not ported yet — the next commit ports them; nothing is skipped silently.</summary>
    [Fact]
    public void PendingFunctions() => AssertPending(File.Value, Dispatch,
        "lodRanges", "lodLambda", "liftedDepth", "buildLodCapGrid", "levelErrorsFrom", "nodeBounds", "selectLodNodes",
        "selectLodFitted", "buildPyramid", "pyramidLevelFor", "morphedVertex", "lodVertex", "lodCapAt", "lodCapOverSquare",
        "waterTileCaps");
}
