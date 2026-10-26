using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using AnimaNative.Overview;
using AnimaNative.Terrain;
using AnimaNative.World;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>
/// The CPU half of the CDLOD terrain the client builds on top of the vector-checked <see cref="TerrainLod"/>
/// (<see cref="TerrainField"/>: pyramids, frame, partition, stats; <see cref="TerrainShaderTwin"/>: the vertex stage's
/// twin; <see cref="TerrainLodGlsl"/>: the printed constants). Expectations are derived by hand in the comments; the
/// <c>nodeHasWater</c> cases are the hand cases of <c>client3d/scripts/smoke_terrain_lod.mjs</c> § (c) "the gate"
/// (no shared vector exists for that function yet).
/// </summary>
public class TerrainFieldTests
{
    // ---- the world of these tests: the --check fixture's relief, plus a water tile ----

    private const string Overview = """
        {"origin_x": -256.0, "origin_z": -256.0, "step_m": 256.0, "rows": 3, "cols": 3,
         "heights": [[0, 0, 0], [0, 4, 8], [0, 8, 16]], "sig": "t", "tile_m": 256.0, "tile_step_m": 2.0,
         "tiles": ["0,0", "5,5"], "mip_levels_m": [4, 8, 16, 32, 64],
         "tile_stats": {"5,5": {"min": 99, "max": 99, "err": [9, 9, 9, 9, 9]}}, "tile_stats_complete": true}
        """;

    /// <summary>Tile 0,0 of fixtures/s3c (h = 2i + j on 64 m, a lake over five lattice points), with stats err 1..5.</summary>
    private const string Tiles = """
        {"sig": "t", "tile_m": 256.0, "step_m": 64.0, "tiles": {"0,0": {"origin_x": 0.0, "origin_z": 0.0, "rows": 5, "cols": 5,
         "heights": [[0, 2, 4, 6, 8], [1, 3, 5, 7, 9], [2, 4, 6, 8, 10], [3, 5, 7, 9, 11], [4, 6, 8, 10, 12]],
         "stats": {"min": 0, "max": 12, "err": [1, 2, 3, 4, 5]},
         "water": {"level": [[6.0, 6.0, null, null, null], [6.0, 6.0, null, null, null], [6.0, null, null, null, null],
                             [null, null, null, null, null], [null, null, null, null, null]],
                   "sd": [[1.0, 0.25, null, null, null], [1.0, -0.5, null, null, null], [0.125, null, null, null, null],
                          [null, null, null, null, null], [null, null, null, null, null]],
                   "kinds": ["lake"], "kind_idx": [[0, 0, 0, 0, 0], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0], [0, 0, 0, 0, 0]]}}}}
        """;

    private static WorldHeight Height(bool withTile = true)
    {
        using var ov = JsonDocument.Parse(Overview);
        var h = new WorldHeight(HeightfieldOverview.Parse(ov.RootElement));
        if (withTile)
        {
            using var t = JsonDocument.Parse(Tiles);
            h.AddTiles(HeightTile.ParseBatch(t.RootElement));
        }
        return h;
    }

    private static readonly double[] Frame = TerrainField.ExtentOf(new BoundsXZ(-104, 300, -203, 134));

    // ---- nodeHasWater (smoke_terrain_lod.mjs § (c)) ----

    [Fact]
    public void NodeHasWaterHandCases()
    {
        var wet = new HashSet<string> { "1,0" };
        Assert.False(TerrainField.NodeHasWater(wet, 256, 0, 0, 64));            // west of the water
        Assert.True(TerrainField.NodeHasWater(wet, 256, 256, 0, 64));           // inside the wet tile
        Assert.True(TerrainField.NodeHasWater(wet, 256, 192, 0, 64));           // east EDGE on the border: closed rectangle
        Assert.False(TerrainField.NodeHasWater(new HashSet<string>(), 256, 0, 0, 64));
        Assert.False(TerrainField.NodeHasWater(null, 256, 0, 0, 64));
        Assert.False(TerrainField.NodeHasWater(wet, 0, 0, 0, 64));              // no tile size
        Assert.False(TerrainField.NodeHasWater(wet, 256, -4096, 0, 2048));      // 9 × 9 = 81 = the cap: scanned
        Assert.True(TerrainField.NodeHasWater(new HashSet<string> { "99,99" }, 128, -4096, 0, 2048));   // 17² = 289 > 81: wet unseen
    }

    // ---- frame, pixel scale ----

    [Fact]
    public void FrameIsWorldBoundsPlusSixtyElseTheFallbackSquare()
    {
        Assert.Equal(new double[] { -164, -263, 360, 194 }, Frame);
        Assert.Equal(new double[] { -100, -100, 100, 100 }, TerrainField.ExtentOf(null));
        // A point frame: min − 60 and max + 60 = 120 m — the 1 m floor does not bite; a NaN-free degenerate keeps ≥ 1 m.
        Assert.Equal(new double[] { -55, -53, 65, 67 }, TerrainField.ExtentOf(new BoundsXZ(5, 5, 7, 7)));
    }

    /// <summary>1080 / (2·tan 22.5°) = 1080 / (2·(√2 − 1)) = 1303.6753236814712.</summary>
    [Fact]
    public void PixelScaleFollowsTheViewportHeight()
    {
        Assert.Equal(1303.6753236814712, TerrainField.PixelScale(1080, 45), 9);
        Assert.Equal(2 * 1303.6753236814712, TerrainField.PixelScale(2160, 45), 9);
        Assert.Equal(0, TerrainField.PixelScale(0, 45));
        Assert.Equal(0, TerrainField.PixelScale(1080, 0));
    }

    // ---- payload stats ----

    [Fact]
    public void TileStatsReadTheJsWay()
    {
        using var d = JsonDocument.Parse("""{"min": "3", "max": null, "err": [1, "x", "2"]}""");
        var s = TileStat.Parse(d.RootElement);
        Assert.Equal(3, s.Min);                      // Number("3")
        Assert.Equal(0, s.Max);                      // Number(null) || 0
        Assert.Equal(1, s.Err[0]);
        Assert.True(double.IsNaN(s.Err[1]));         // Number("x")
        Assert.Equal(2, s.Err[2]);
        using var e = JsonDocument.Parse("""{"min": "junk"}""");
        var j = TileStat.Parse(e.RootElement);
        Assert.Equal(0, j.Min);                      // Number("junk") = NaN || 0
        Assert.Equal(0, j.Max);                      // absent: Number(undefined) = NaN || 0
        Assert.Empty(j.Err);                         // (err ?? []).map(Number)
    }

    [Fact]
    public void StatsComeFromTheOverviewAndEveryLoadedTile()
    {
        var h = Height(withTile: false);
        Assert.Equal(new double[] { 4, 8, 16, 32, 64 }, h.Overview.MipLevelsM);
        Assert.Equal(new[] { "5,5" }, h.Stats.Keys);
        Assert.Null(h.WaterRaster());
        h = Height();
        Assert.Equal(new[] { "0,0", "5,5" }, h.Stats.Keys.OrderBy(k => k, StringComparer.Ordinal));
        Assert.Equal(new double[] { 1, 2, 3, 4, 5 }, h.Stats["0,0"].Err);
        var raster = h.WaterRaster();
        Assert.NotNull(raster);
        Assert.Equal(new[] { "0,0" }, raster!.Tiles.Keys);
    }

    // ---- the field ----

    /// <summary>
    /// Near: tile 0,0 (0…256) + max(16, 2·256) = −512…768 at 2 m → 641 per axis; levels 641/321/161/81/41/21 stacked
    /// (rows 0, 641, 962, 1123, 1204, 1245; 1266 high). Far: the 3 × 3 overview, then 2 × 2 at 512 m, then a side
    /// below 2 points stops it. Level errors: base step 2 → level L wants 2·2^L m = mip index L − 1 → the largest err
    /// over both tiles there (tile 0,0: 1..5, tile 5,5: 9) = 0, 9, 9, 9, 9, 9. Range: from (0, 0) over both level-0
    /// lattices: 0 … 16 (the overview corner 16; the near window clamps the overview there too).
    /// </summary>
    [Fact]
    public void BuildsThePyramidsTheRangeAndTheLevelErrors()
    {
        var f = TerrainField.Build(Height(), 64, 128, null, Frame);
        Assert.Equal(2, f.BaseStep);
        Assert.Equal(64, f.LeafM);
        var near = f.Near!;
        Assert.Equal(new[] { 641, 321, 161, 81, 41, 21 }, near.Levels.Select(l => l.Cols));
        Assert.Equal(new[] { 0, 641, 962, 1123, 1204, 1245 }, near.Levels.Select(l => l.Row0));
        Assert.Equal(1266, near.TexH);
        Assert.Equal(new double[] { -512, -512, 768, 768 }, f.NearRect);
        Assert.Equal(new[] { 3, 2 }, f.Far!.Levels.Select(l => l.Cols));
        Assert.Equal(new double[] { 0, 9, 9, 9, 9, 9 }, f.LevelErrorM);
        Assert.Equal(new NodeStatSpan(0, 16), f.GlobalRange);
        Assert.Null(f.Water);
        Assert.Null(f.WaterTileKeys);
        Assert.Null(f.CapGrid);
        // The near lattice IS the tile-first height: at (64, 128) h = 64/32 + 128/64 = 4.
        Assert.Equal(4, TerrainLod.PyramidHeight(near, 64, 128, 0), 6);
    }

    [Fact]
    public void BuildFarReadsTheOverviewAtItsLattice()
    {
        var far = TerrainField.BuildFar(Height(false).Overview.Grid)!;
        Assert.Equal(new float[] { 0, 0, 0, 0, 4, 8, 0, 8, 16, 0, 0, 0, 0, 16, 0 }, far.Data);
        Assert.Null(TerrainField.BuildFar(new HeightGrid(0, 0, 4, 1, 3, new float[3])));
    }

    /// <summary>
    /// With the water: the water pyramid and the sd field share the near lattice; the cap of tile 0,0 is 4 (README
    /// "CDLOD terrain": the cell [0, 64]² is fully lifted except its far corner — sd = 1 − 0.75·u·(1 + v) — so a 17 × 17
    /// block fits and a 33 × 33 one does not); the cap grid is the tile plus a two-tile ring, corners 4 where they touch it.
    /// </summary>
    [Fact]
    public void WaterGivesTheWetSetTheSdAndTheCap()
    {
        var h = Height();
        var f = TerrainField.Build(h, 64, 128, h.WaterRaster(), Frame);
        Assert.Equal(new[] { "0,0" }, f.WaterTileKeys!);
        Assert.Equal(256, f.WaterTileM);
        Assert.Equal(f.Near!.OriginX, f.Water!.OriginX);
        Assert.Equal(641, f.Sd!.Cols);
        Assert.Equal(1.0, TerrainLod.GpuWaterSdAt(f.Sd, 0, 64), 6);
        Assert.Equal(6.0, TerrainLod.GpuWaterAt(f.Water, f.NearRect, 32, 32, 2), 6);
        Assert.True(double.IsNaN(TerrainLod.GpuWaterAt(f.Water, f.NearRect, 200, 200, 2)));
        var g = f.CapGrid!;
        Assert.Equal((-256.0, -256.0, 256.0, 4, 4, 4.0), (g.X0, g.Z0, g.Step, g.Cols, g.Rows, g.Min));
        Assert.Equal(new float[] { 6, 6, 6, 6, 6, 4, 4, 6, 6, 4, 4, 6, 6, 6, 6, 6 }, g.Caps);
    }

    [Fact]
    public void ThePartitionIsNodeHasWaterAndTheTrianglesCountCells()
    {
        var h = Height();
        var f = TerrainField.Build(h, 64, 128, h.WaterRaster(), Frame);
        var frame = f.Select(32, 10, 32, TerrainField.PixelScale(1080, 45));
        Assert.NotEmpty(frame.Wet);
        Assert.NotEmpty(frame.Dry);
        Assert.All(frame.Wet, n => Assert.True(TerrainField.NodeHasWater(f.WaterTileKeys, 256, n.X, n.Z, n.Size)));
        Assert.All(frame.Dry, n => Assert.False(TerrainField.NodeHasWater(f.WaterTileKeys, 256, n.X, n.Z, n.Size)));
        Assert.Equal(frame.Dry.Concat(frame.Wet).Sum(n => n.Cells * n.Cells * 2), frame.Triangles);
        Assert.Equal(1, f.Coverage(frame), 12);      // disjoint squares whose clipped areas fill the frame: no hole
        Assert.Equal(2, frame.Draws);
        Assert.Equal(TerrainLod.MaxLodLevels, frame.Ranges.Count);
        // Without water the same camera draws one program.
        var dry = TerrainField.Build(h, 64, 128, null, Frame).Select(32, 10, 32, TerrainField.PixelScale(1080, 45));
        Assert.Empty(dry.Wet);
        Assert.Equal(1, dry.Draws);
    }

    [Fact]
    public void NoFieldSelectsNothingAndTheUniformsSayNone()
    {
        var f = TerrainField.Build(Height(withTile: false), 0, 0, null, TerrainField.ExtentOf(null));
        Assert.Null(f.Near);
        var u = f.Uniforms();
        Assert.Equal(new double[] { 0, 0, -1, -1 }, u.NearRect);
        Assert.Equal(new double[] { 0, 0, 1, 0 }, u.NearGeom);
        Assert.Equal(new double[] { 0, 0, 1, 0 }, u.CapGeom);
        Assert.Equal(new double[] { -256, -256, 256, 2 }, u.FarGeom);
        Assert.Equal(new double[] { 3, 3, 256, 0 }, u.FarLevels[0]);
        Assert.Equal(new double[] { 2, 2, 512, 3 }, u.FarLevels[1]);
        Assert.All(u.FarLevels.Skip(2), r => Assert.Equal(new double[4], r));
    }

    // ---- the vertex stage's twin against the CPU vertex ----

    /// <summary>The twin on the uploaded state = <see cref="TerrainLod.LodVertex"/> for every piece of three frames,
    /// dry and wet (the lift), 11 patch vertices each.</summary>
    [Theory]
    [InlineData(32, 10, 32)]
    [InlineData(64, 31.5, 168)]
    [InlineData(1000, 400, -600)]
    public void TwinEqualsLodVertex(double cx, double cy, double cz)
    {
        var h = Height();
        var f = TerrainField.Build(h, 64, 128, h.WaterRaster(), Frame);
        var frame = f.Select(cx, cy, cz, TerrainField.PixelScale(1080, 45));
        var state = TerrainShaderState.From(f.Uniforms(), frame);
        int n = 0;
        foreach (var (pieces, water) in new[] { (frame.Dry, false), (frame.Wet, true) })
        foreach (var node in pieces)
        foreach (var (i, j) in TerrainShaderTwin.SampleVertices)
        {
            var twin = TerrainShaderTwin.Compute(state, new[] { node.X, node.Z, node.Size, node.Level }, i / 32.0, j / 32.0, (cx, cy, cz), water);
            var cpu = TerrainLod.LodVertex(node, i, j, f.Near, f.NearRect, f.Far, f.Extent, new LodCamera(cx, cy, cz), frame.Ranges,
                                           water ? f.Water : null, (x, z) => f.CapAt(x, z, frame.CapRelax), water ? f.Sd : null);
            Assert.Equal(cpu.X, twin.X, 9);
            Assert.Equal(cpu.Z, twin.Z, 9);
            Assert.Equal(cpu.Y, twin.Y, 6);
            n++;
        }
        Assert.True(n >= 50, $"{n}");
    }

    /// <summary>
    /// README "Water (tile 0, 0)": the drawn lift at the lattice points, through the twin, by every piece that draws
    /// them — (0, 64) h 1 → 6 (depth 5), (64, 64) sd −0.5 → 3 (0), (0, 128) sd 0.125 → gate 0.15625 → 2.625 (0.625).
    /// </summary>
    [Fact]
    public void TheWetProgramDrawsTheTableAtEveryPieceThatOwnsThePoint()
    {
        var h = Height();
        var f = TerrainField.Build(h, 64, 128, h.WaterRaster(), Frame);
        var frame = f.Select(32, 10, 32, TerrainField.PixelScale(1080, 45));
        var state = TerrainShaderState.From(f.Uniforms(), frame);
        var want = new Dictionary<(double, double), (double Y, double Wet)> { [(0, 64)] = (6, 5), [(64, 64)] = (3, 0), [(0, 128)] = (2.625, 0.625) };
        var seen = new Dictionary<(double, double), int>();
        foreach (var node in frame.Wet)
            for (int j = 0; j <= 32; j++)
            for (int i = 0; i <= 32; i++)
            {
                var v = TerrainShaderTwin.Compute(state, new[] { node.X, node.Z, node.Size, node.Level }, i / 32.0, j / 32.0, (32, 10, 32), true);
                if (!want.TryGetValue((v.X, v.Z), out var w)) continue;
                Assert.Equal(w.Y, v.Y, 4);
                Assert.Equal(w.Wet, v.Wet, 4);
                seen[(v.X, v.Z)] = seen.GetValueOrDefault((v.X, v.Z)) + 1;
            }
        Assert.Equal(3, seen.Count);
    }

    // ---- the printed constants ----

    [Fact]
    public void TheShaderPrintsTheTwinsConstants()
    {
        var dry = TerrainLodGlsl.Chunk(false);
        var wet = TerrainLodGlsl.Chunk(true);
        foreach (var code in new[] { dry, wet })
        {
            Assert.Contains($"const float TL_PATCH_N = {TerrainLodGlsl.Lit(TerrainLod.PatchN)};", code);
            Assert.Contains("const float TL_PATCH_N = 32.0;", code);
            Assert.Contains("const float TL_MORPH_START = 0.5;", code);
            Assert.Contains("const float TL_CAP_NONE = 6.0;", code);
            Assert.Contains("uniform float tl_range[6];", code);
        }
        Assert.Contains("clamp(sd / 0.5, 0.0, 1.0)", wet);
        Assert.Contains("const float TL_SD_DRY = -10000.0;", wet);
        Assert.DoesNotContain("tl_lift", dry);
        Assert.DoesNotContain("tl_water", dry);
        Assert.Equal("2.0", TerrainLodGlsl.Lit(2));
        Assert.Equal("0.5", TerrainLodGlsl.Lit(0.5));
        Assert.Equal("-1e-30", TerrainLodGlsl.Lit(-1e-30));
    }
}
