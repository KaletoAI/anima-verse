using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using AnimaNative.Ground;
using AnimaNative.Overview;
using AnimaNative.Scatter;
using AnimaNative.Terrain;
using AnimaNative.Water;
using AnimaNative.World;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>
/// Task 25's water beside the vectors: the ripple twin (<c>twRipple</c>; the identities of
/// client3d/scripts/smoke_water_shade.mjs § [5]/[6] — no shared vector exists for it), the ghost gates (the hand tables
/// of walk.ts' docstrings), the waterfall look (waterfall.ts constants), the topmost-area mirror (ground.ts
/// <c>typeAt</c>), the prop water sheet, and the fragment's look rows and flow on the near lattice
/// (terrainLod.ts <c>buildKindRows</c> / <c>buildFlow</c>). Every expectation is derived by hand in its comment.
/// </summary>
public class WaterExtrasTests
{
    private static void Near((double, double) got, (double, double) want, double eps = 1e-12)
    {
        Assert.Equal(want.Item1, got.Item1, eps);
        Assert.Equal(want.Item2, got.Item2, eps);
    }

    // ---- the ripple (twRipple) ----

    /// <summary>
    /// Still water, p = (7.25, −3.5), λ 1.6, speed 0.05, t = 10: A = p/1.6 + (1, 0.6)·(10·0.05/1.6)
    /// = (4.53125 + 0.3125, −2.1875 + 0.1875) = (4.84375, −2); the frame is the identity; the ribbon weighs 0.
    /// </summary>
    [Fact]
    public void StillWaterCounterScrollsInTheWorldFrame()
    {
        var r = WaterShade.Ripple(7.25, -3.5, 0, 0, 1.6, 0.05, 0.5, 10, 0);
        Assert.True(r.Still);
        Near(r.A, (4.84375, -2.0));
        // B: λ 1.008, dir −(0.8, 1.3), drift 0.5/1.008 → p/1.008 − (0.8, 1.3)·0.496031746…
        Near(r.B, (7.25 / 1.008 - 0.8 * 0.5 / 1.008, -3.5 / 1.008 - 1.3 * 0.5 / 1.008));
        Assert.Equal(0, r.WeightC);
        Assert.Equal(0.05, r.Speed);
    }

    /// <summary>
    /// Flowing water, flow (2, 0) (the area factor 2 rides the length), flow speed 0.5 → sp = 1 m/s, sign −1, cross
    /// 0.15 / 0.3: dir A = (1, 0.15), dir B = (0.8, −0.3); THE IDENTITY uv(p0 + dir·sp·t, t) = uv(p0, 0) for every sheet
    /// at every t — the crests ride downstream at dir·sp (smoke_water_shade.mjs § [6]).
    /// </summary>
    [Fact]
    public void FlowingWaterRidesDownstream()
    {
        var p0 = (X: 7.25, Z: -3.5);
        var r0 = WaterShade.Ripple(p0.X, p0.Z, 2, 0, 1.6, 0.05, 0.5, 0, 0);
        Assert.False(r0.Still);
        Assert.Equal(1.0, r0.Speed, 12);
        Near(r0.DirA, (1, 0.15));
        Near(r0.DirB, (0.8, -0.3));
        Assert.Equal(0.35, r0.WeightC);
        foreach (double t in new[] { 0.5, 2, 7.5, 60 })
        {
            Near(WaterShade.Ripple(p0.X + 1 * t, p0.Z + 0.15 * t, 2, 0, 1.6, 0.05, 0.5, t, 0).A, r0.A, 1e-9);
            Near(WaterShade.Ripple(p0.X + 0.8 * t, p0.Z - 0.3 * t, 2, 0, 1.6, 0.05, 0.5, t, 0).B, r0.B, 1e-9);
            Near(WaterShade.Ripple(p0.X + t, p0.Z, 2, 0, 1.6, 0.05, 0.5, t, 0).C, r0.C, 1e-9);
        }
        // RED: the upstream sign (the mirror's bug until 09f2b29f) breaks it — the same point at t = 2 is 2·dir away.
        var wrong = WaterShade.Ripple(p0.X - 2, p0.Z - 0.3, 2, 0, 1.6, 0.05, 0.5, 2, 0).A;
        Assert.True(Math.Abs(wrong.U - r0.A.U) > 1);
    }

    /// <summary>A diagonal current (1, 1)/√2 at unit length: dir A = ax + 0.15 ay with ay = (−ax.z, ax.x); same identity.</summary>
    [Fact]
    public void ADiagonalCurrentIsNoAxisAccident()
    {
        double s = Math.Sqrt(0.5);
        var r0 = WaterShade.Ripple(7.25, -3.5, s, s, 1.6, 0.05, 1, 0, 0);
        Near(r0.DirA, (s - 0.15 * s, s + 0.15 * s), 1e-12);
        var (dx, dz) = r0.DirA;
        Near(WaterShade.Ripple(7.25 + dx * 3, -3.5 + dz * 3, s, s, 1.6, 0.05, 1, 3, 0).A, r0.A, 1e-9);
    }

    /// <summary>The detail fade 1 − px/λ: 0.4 m pixels on λ 1.6 → 0.75; a pixel of 2 m → 0; below |flow| 1e-4 still.</summary>
    [Fact]
    public void DetailFadeAndStillThreshold()
    {
        Assert.Equal(0.75, WaterShade.Ripple(0, 0, 0, 0, 1.6, 0.05, 0.5, 0, 0.4).Detail, 12);
        Assert.Equal(0, WaterShade.Ripple(0, 0, 0, 0, 1.6, 0.05, 0.5, 0, 2).Detail);
        Assert.True(WaterShade.Ripple(0, 0, 9e-5, 0, 1.6, 0.05, 0.5, 0, 0).Still);
        Assert.False(WaterShade.Ripple(0, 0, 1e-3, 0, 1.6, 0.05, 0.5, 0, 0).Still);
    }

    // ---- the ghost gates (walk.ts docstring tables) ----

    [Theory]
    [InlineData(12.00, null, null)]       // dry ground: no water at all
    [InlineData(12.00, 11.90, null)]      // the mirror is UNDER the base
    [InlineData(12.00, 12.00, null)]      // exactly at the waterline
    [InlineData(12.00, 12.04, null)]      // 4 cm: the look has not faded in
    [InlineData(12.00, 12.05, 12.05)]     // 5 cm: the rim ramp is up
    [InlineData(12.00, 12.60, 12.60)]     // a ford, knee deep — the wader
    [InlineData(12.00, 13.50, 13.50)]     // a swimmer, cut at the chest
    [InlineData(12.00, double.NaN, null)] // a raster that knows nothing is dry
    [InlineData(0.0, 0.045, null)]        // 4.5 cm on an exact base: under the 5 cm threshold
    [InlineData(0.0, 0.05, 0.05)]         // exactly 5 cm: the threshold counts (≥)
    public void GhostCutYHandTable(double bed, double? water, double? cut)
    {
        Assert.Equal(cut, WaterGates.GhostCutY(bed, water));
        Assert.Equal(cut is not null, WaterGates.SubmergedInWater(bed, water));
    }

    /// <summary>ghostWaterLevel: the dilated collar (inside 0) and the outline itself are NaN; half a band in and deeper the level.</summary>
    [Fact]
    public void GhostWaterLevelNeedsTheOutline()
    {
        Assert.True(double.IsNaN(WaterGates.GhostWaterLevel(12.6, 0)));
        Assert.Equal(12.6, WaterGates.GhostWaterLevel(12.6, 0.5));
        Assert.Equal(12.6, WaterGates.GhostWaterLevel(12.6, 1));
    }

    /// <summary>
    /// The placement gate on a 2 × 2 raster at 12.6 m: sd 1 everywhere → inside 1 → cut 12.6 over a base at 12; sd −1
    /// (the dilation collar) → inside 0 → dry; sd 0.25 → smoothstep(0.5) = 0.5 → 12.6; a base at 12.58 (2 cm) → dry.
    /// </summary>
    [Fact]
    public void PlacementGateReadsLevelAndOutline()
    {
        WaterRaster Raster(float sd) => new(256, new Dictionary<string, WaterTileField>
        {
            ["0,0"] = new(0, 0, 1, 2, 2, new[] { 12.6f, 12.6f, 12.6f, 12.6f }, new[] { sd, sd, sd, sd }, new[] { "" },
                          new int[4], null, null),
        });
        Assert.Equal(12.6, WaterGates.PlacementGhostCut(Raster(1), 0.5, 0.5, 12)!.Value, 6);
        Assert.Null(WaterGates.PlacementGhostCut(Raster(-1), 0.5, 0.5, 12));
        Assert.Equal(12.6, WaterGates.PlacementGhostCut(Raster(0.25f), 0.5, 0.5, 12)!.Value, 6);
        Assert.Null(WaterGates.PlacementGhostCut(Raster(1), 0.5, 0.5, 12.58));
        Assert.Null(WaterGates.PlacementGhostCut(null, 0.5, 0.5, 12));
    }

    /// <summary>groundScope: a room answers first (outdoor → open, else built), then the footprint (area → open), else wilderness.</summary>
    [Fact]
    public void ScopeRule()
    {
        Assert.Equal(GroundScope.Wilderness, WaterGates.ScopeOf(null, null));
        Assert.Equal(GroundScope.Open, WaterGates.ScopeOf(true, null));
        Assert.Equal(GroundScope.Built, WaterGates.ScopeOf(false, null));
        Assert.Equal(GroundScope.Built, WaterGates.ScopeOf(true, false));
        Assert.Equal(GroundScope.Open, WaterGates.ScopeOf(false, true));
    }

    // ---- waterfalls ----

    /// <summary>
    /// The fall of fixtures/water (README "Water (Task 25)"): mid (11, 0), dir (1, 0), width 4, 10 → 6, chord 2.
    /// h = 4: foam radius max(2, 0.5·4) = 2, mean speed √(9.81·4/2) = 4.429446918 m/s → 1.771778767 tiles/s, tiles
    /// (1.6, 1.6); the disc at the foot (11 + 1 + 1.2, 6.05, 0) with alpha 0.6, rim point 0 at (15.2, ·, 0), point 6
    /// (a = π/2) at (13.2, ·, −2), 1 + 25 vertices, 24 triangles.
    /// </summary>
    [Fact]
    public void WaterfallLook()
    {
        var fall = new Waterfall(11, 0, 1, 0, 4, 10, 6, 2);
        Assert.Equal(2, Waterfalls.FoamRadius(fall, 4));
        Assert.Equal(4.4294469180700204, Waterfalls.FallSpeedMs(4), 12);
        var (sp, tx, ty) = Waterfalls.Curtain(fall);
        Assert.Equal(1.771778767228008, sp, 12);
        Assert.Equal((1.6, 1.6), (tx, ty));
        var (v, idx) = Waterfalls.FoamDisc(fall)!.Value;
        Assert.Equal(26 * 4, v.Length);
        Assert.Equal(24 * 3, idx.Length);
        Assert.Equal(new[] { 13.2, 6.05, 0, 0.6 }, v.Take(4).Select(x => Math.Round(x, 9)));
        Assert.Equal(new[] { 15.2, 6.05, 0, 0 }, v.Skip(4).Take(4).Select(x => Math.Round(x, 9)));
        Assert.Equal(new[] { 13.2, 6.05, -2, 0 }, v.Skip(4 * 7).Take(4).Select(x => Math.Round(x, 9)));
        Assert.Equal(new[] { 1, 2, 0 }, idx.Take(3));
        // A tall narrow fall: width 1, drop 6 → radius max(0.5, 3) = 3.
        Assert.Equal(3, Waterfalls.FoamRadius(new Waterfall(0, 0, 1, 0, 1, 6, 0, 1), 6));
    }

    private const string Payload = """
        {"default_kind": "grass", "areas": [
          {"id": "lake", "kind": "lake", "polygon": [[0, -10], [40, -10], [40, 10], [0, 10]],
           "meta": {"water_profile": {"axis": [[0, 0, 0, 5], [40, 0, 40, 5]], "level_up": 5, "level_down": 5,
                    "axis_x": 0, "axis_z": 0, "dir_x": 1, "dir_z": 0, "s_min": 0, "s_max": 40}}},
          {"id": "bank", "kind": "sand", "polygon": [[30, -2], [34, -2], [34, 2], [30, 2]], "meta": {}},
          {"id": "river", "kind": "river", "polygon": [[0, 20], [20, 20], [20, 24], [0, 24]],
           "meta": {"stroke": {"width_m": 4},
                    "water_profile": {"axis": [[0, 22, 0, 10], [10, 22, 10, 10], [12, 22, 12, 6], [20, 22, 20, 6]],
                    "level_up": 10, "level_down": 6, "axis_x": 0, "axis_z": 22, "dir_x": 1, "dir_z": 0, "s_min": 0, "s_max": 20}}}
        ]}
        """;

    /// <summary>
    /// typeAt's mirror: inside the lake 5 (flat profile); on the sandbank painted over it nothing (the topmost area has
    /// no profile); outside every area nothing; on the river's upper reach 10, past the fall 6. The river's axis drops
    /// 4 m over 2 m (slope 2 > 0.5, drop 4 > 1) → one fall at the segment's midpoint (11, 22); the polygon lake has no
    /// stroke width → none.
    /// </summary>
    [Fact]
    public void TopmostAreaDecidesTheMirrorAndTheFalls()
    {
        using var doc = JsonDocument.Parse(Payload);
        var t = TerrainPayload.Parse(doc.RootElement);
        Assert.Equal(5, t.WaterLevelAt(10, 0));
        Assert.Null(t.WaterLevelAt(32, 0));
        Assert.Null(t.WaterLevelAt(50, 0));
        Assert.Equal(10, t.WaterLevelAt(5, 22));
        Assert.Equal(6, t.WaterLevelAt(15, 22));
        Assert.Empty(t.Areas[0].Falls);
        var f = Assert.Single(t.Areas[2].Falls);
        Assert.Equal(new Waterfall(11, 22, 1, 0, 4, 10, 6, 2), f);
    }

    // ---- prop water ----

    /// <summary>
    /// The sheet's albedo for #3f7fb8: 0.25·(63, 127, 184)/255 + 0.75·sRGB→linear = (0.0990446, 0.2836829, 0.5398823)
    /// (linear 0.0497066, 0.2122308, 0.4793202). A 4 × 4 square with a 1 × 1 hole: 8 points, 8 triangles, all at y 0.
    /// </summary>
    [Fact]
    public void PropWaterSheetAndLook()
    {
        var a = PropWater.Albedo("#3f7fb8");
        Assert.Equal(0.09904463036531876, a.R, 9);
        Assert.Equal(0.2836828719741351, a.G, 9);
        Assert.Equal(0.5398822941812502, a.B, 9);
        var region = new SceneWaterRegion(new[] { new P2(0, 0), new P2(4, 0), new P2(4, 4), new P2(0, 4) },
                                          new[] { new[] { new P2(1, 1), new P2(1, 2), new P2(2, 2), new P2(2, 1) } },
                                          1.5, 0, "#3f7fb8", 0.7, 1);
        var m = PropWater.Sheet(region);
        Assert.Equal(8, m.Positions.Count);
        Assert.Equal(8, m.Triangles);
        Assert.All(m.Positions, p => Assert.Equal(0, p.Y, 12));
        Assert.Equal((0.0, 4.0), (m.Positions.Min(p => p.Z), m.Positions.Max(p => p.Z)));
        // Area: Σ triangles = 16 − 1 = 15 (the hole stays open).
        double area = 0;
        for (int i = 0; i < m.Indices.Count; i += 3)
        {
            var (p, q, r) = (m.Positions[m.Indices[i]], m.Positions[m.Indices[i + 1]], m.Positions[m.Indices[i + 2]]);
            area += Math.Abs((q.X - p.X) * (r.Z - p.Z) - (r.X - p.X) * (q.Z - p.Z)) / 2;
        }
        Assert.Equal(15, area, 9);
    }

    // ---- the fragment's fields on the near lattice ----

    private const string Overview = """
        {"origin_x": -256.0, "origin_z": -256.0, "step_m": 256.0, "rows": 3, "cols": 3,
         "heights": [[0, 0, 0], [0, 0, 0], [0, 0, 0]], "sig": "t", "tile_m": 256.0, "tile_step_m": 2.0,
         "tiles": ["0,0"], "mip_levels_m": [4, 8, 16, 32, 64]}
        """;

    /// <summary>Tile 0,0 at 64 m: water on its first two lattice points, kind "lake" at (0, 0), "River" at (1, 0); flow x 2 at
    /// (0, 0), 0 elsewhere.</summary>
    private const string Tiles = """
        {"sig": "t", "tile_m": 256.0, "step_m": 64.0, "tiles": {"0,0": {"origin_x": 0.0, "origin_z": 0.0, "rows": 2, "cols": 2,
         "heights": [[0, 0], [0, 0]],
         "water": {"level": [[1.0, 1.0], [null, null]], "sd": [[1.0, 1.0], [null, null]],
                   "kinds": ["lake", "River"], "kind_idx": [[0, 1], [0, 0]],
                   "flow_x": [[2.0, 0.0], [0.0, 0.0]], "flow_z": [[0.0, 0.0], [0.0, 0.0]]}}}}
        """;

    /// <summary>
    /// buildKindRows / buildFlow on the near lattice (2 m): the row is the NEAREST texel's kind (JS Math.round: x 30 →
    /// 0.46875 → lake = row 0; x 32 → 0.5 → 1 → "River", lower-cased → row 1; x 64 → river 1); an unknown kind → row 0
    /// (no table: all 0). The flow is the masked bilinear: (0, 0) 2, (32, 0) 1, (64, 0) 0. Both on the sd's lattice.
    /// </summary>
    [Fact]
    public void LookRowsAndFlowRideTheNearLattice()
    {
        using var ov = JsonDocument.Parse(Overview);
        var h = new WorldHeight(HeightfieldOverview.Parse(ov.RootElement));
        using var t = JsonDocument.Parse(Tiles);
        h.AddTiles(HeightTile.ParseBatch(t.RootElement));
        var rows = new Dictionary<string, int> { ["lake"] = 0, ["river"] = 1 };
        var f = TerrainField.Build(h, 0, 0, h.WaterRaster(), TerrainField.ExtentOf(null), rowOfKind: rows);
        var k = f.KindRows!;
        var fl = f.Flow!;
        Assert.Equal((f.Sd!.OriginX, f.Sd.OriginZ, f.Sd.Step, f.Sd.Cols, f.Sd.Rows), (k.OriginX, k.OriginZ, k.Step, k.Cols, k.Rows));
        Assert.Equal((f.Sd.Cols, f.Sd.Rows), (fl.Cols, fl.Rows));
        int At(double x, double z) => (int)Math.Round((z - k.OriginZ) / k.Step) * k.Cols + (int)Math.Round((x - k.OriginX) / k.Step);
        Assert.Equal(0, k.Data[At(30, 0)]);
        Assert.Equal(1, k.Data[At(32, 0)]);
        Assert.Equal(1, k.Data[At(64, 0)]);
        Assert.Equal(2, fl.Data[2 * At(0, 0)]);
        Assert.Equal(1, fl.Data[2 * At(32, 0)], 6);
        Assert.Equal(0, fl.Data[2 * At(64, 0)]);
        var none = TerrainField.Build(h, 0, 0, h.WaterRaster(), TerrainField.ExtentOf(null));
        Assert.All(none.KindRows!.Data, v => Assert.Equal(0, v));
        var dry = TerrainField.Build(h, 0, 0, null, TerrainField.ExtentOf(null));
        Assert.Null(dry.KindRows);
        Assert.Null(dry.Flow);
    }

    /// <summary>The cursor's tile memo answers exactly what the uncached readers answer — across tile borders too.</summary>
    [Fact]
    public void CursorEqualsTheReaders()
    {
        using var ov = JsonDocument.Parse(Overview);
        var h = new WorldHeight(HeightfieldOverview.Parse(ov.RootElement));
        using var t = JsonDocument.Parse(Tiles);
        h.AddTiles(HeightTile.ParseBatch(t.RootElement));
        var r = h.WaterRaster();
        var c = new WaterRaster.Cursor(r);
        for (double z = -10; z <= 300; z += 7.5)
        for (double x = -10; x <= 300; x += 3.25)
        {
            double l1 = WaterRaster.LevelAt(r, x, z), l2 = c.LevelAt(x, z);
            Assert.True(l1.Equals(l2), $"level ({x}, {z})");
            Assert.Equal(WaterRaster.SdAt(r, x, z), c.SdAt(x, z));
            Assert.Equal(WaterRaster.KindAt(r, x, z), c.KindAt(x, z));
            Assert.Equal(WaterRaster.FlowAt(r, x, z), c.FlowAt(x, z));
        }
    }
}
