using System;
using System.Collections.Generic;
using AnimaNative.Ground;
using AnimaNative.Terrain;

namespace AnimaNative.Water;

/// <summary>
/// The world's water as a field — the readers of <c>client3d/src/scene/waterRaster.ts</c> over the loaded tiles'
/// <see cref="WaterTileField"/>s (Wasser v2 K-A). The level is NaN where dry, the signed distance
/// <see cref="WaterTileField.SdDry"/>; there is no overview rung, an unloaded tile is dry. <see cref="TileM"/> is the
/// payload's, the keys <c>"tx,tz"</c> (<see cref="HeightTiles.TileKeyAt"/>).
/// </summary>
public sealed record WaterRaster(double TileM, IReadOnlyDictionary<string, WaterTileField> Tiles)
{
    private WaterTileField? Field(double x, double z)
        => Tiles.TryGetValue(HeightTiles.TileKeyAt(TileM, x, z), out var f) ? f : null;

    /// <summary>
    /// <c>waterBilinear</c>: the MASKED bilinear mix — a corner of weight 0 is not read, so a NaN (dry) neighbour
    /// with no weight cannot drag a sample on a lattice line to NaN; NaN exactly when a contributing corner is dry.
    /// </summary>
    public static double WaterBilinear(double h00, double h10, double h01, double h11, double tx, double tz)
    {
        double w00 = (1 - tx) * (1 - tz), w10 = tx * (1 - tz), w01 = (1 - tx) * tz, w11 = tx * tz;
        double sum = 0;
        if (w00 != 0) sum += h00 * w00;
        if (w10 != 0) sum += h10 * w10;
        if (w01 != 0) sum += h01 * w01;
        if (w11 != 0) sum += h11 * w11;
        return sum;
    }

    /// <summary><c>cellAt</c>: the <c>latticeSample</c> clamp, cell and fraction.</summary>
    private static (int I, double T) CellAt(double f, int n)
    {
        double c = f < 0 ? 0 : f > n - 1 ? n - 1 : f;
        int i = (int)Math.Min(Math.Floor(c), n - 2);
        return (i, c - i);
    }

    /// <summary><c>nearestIndex</c>: the nearest lattice index (JS <c>Math.round</c>), clamped; every kind read uses it.</summary>
    public static int NearestIndex(double f, int n)
    {
        if (!(n > 0)) return 0;
        double i = Scatter.Js.Round(f);
        return i < 0 ? 0 : i > n - 1 ? n - 1 : (int)i;
    }

    /// <summary><c>rasterLevelAt</c>: the water level at (x, z), masked bilinear on the tile's lattice; NaN = dry.</summary>
    public static double LevelAt(WaterRaster? raster, double x, double z)
    {
        var f = raster?.Field(x, z);
        if (f is null || f.Rows < 2 || f.Cols < 2) return double.NaN;
        var (i, tx) = CellAt((x - f.OriginX) / f.Step, f.Cols);
        var (j, tz) = CellAt((z - f.OriginZ) / f.Step, f.Rows);
        double At(int a, int b) => f.Level[b * f.Cols + a];
        return WaterBilinear(At(i, j), At(i + 1, j), At(i, j + 1), At(i + 1, j + 1), tx, tz);
    }

    /// <summary><c>rasterSdAt</c>: the signed distance to the painted outline, PLAIN bilinear (the dry sentinel is finite).</summary>
    public static double SdAt(WaterRaster? raster, double x, double z)
    {
        var f = raster?.Field(x, z);
        if (f is null || f.Rows < 2 || f.Cols < 2) return WaterTileField.SdDry;
        var (i, tx) = CellAt((x - f.OriginX) / f.Step, f.Cols);
        var (j, tz) = CellAt((z - f.OriginZ) / f.Step, f.Rows);
        double At(int a, int b) => f.Sd[b * f.Cols + a];
        double north = At(i, j) * (1 - tx) + At(i + 1, j) * tx;
        double south = At(i, j + 1) * (1 - tx) + At(i + 1, j + 1) * tx;
        return north * (1 - tz) + south * tz;
    }

    /// <summary><c>rasterKindAt</c>: the painted kind of the water at (x, z), nearest texel, never mixed; '' where unknown.</summary>
    public static string KindAt(WaterRaster? raster, double x, double z)
    {
        var f = raster?.Field(x, z);
        if (f is null || f.Rows < 1) return "";
        int j = NearestIndex((z - f.OriginZ) / f.Step, f.Rows);
        int i = NearestIndex((x - f.OriginX) / f.Step, f.Cols);
        int idx = i < f.Cols ? f.KindIdx[j * f.Cols + i] : 0;   // row[i] ?? 0
        return idx >= 0 && idx < f.Kinds.Length ? f.Kinds[idx] : "";
    }

    /// <summary><c>rasterFlowAt</c>: the flow vector, masked bilinear; (0, 0) where still, unloaded or not finite.</summary>
    public static (double X, double Z) FlowAt(WaterRaster? raster, double x, double z)
    {
        var f = raster?.Field(x, z);
        if (f?.FlowX is not { } fx || f.FlowZ is not { } fz) return (0, 0);
        if (f.Rows < 2 || f.Cols < 2) return (0, 0);
        var (i, tx) = CellAt((x - f.OriginX) / f.Step, f.Cols);
        var (j, tz) = CellAt((z - f.OriginZ) / f.Step, f.Rows);
        double Mix(float[] g) => WaterBilinear(g[j * f.Cols + i], g[j * f.Cols + i + 1],
                                               g[(j + 1) * f.Cols + i], g[(j + 1) * f.Cols + i + 1], tx, tz);
        double vx = Mix(fx), vz = Mix(fz);
        return double.IsFinite(vx) && double.IsFinite(vz) ? (vx, vz) : (0, 0);
    }
}
