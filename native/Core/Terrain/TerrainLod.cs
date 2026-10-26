using System;
using System.Collections.Generic;
using AnimaNative.Ground;

namespace AnimaNative.Terrain;

/// <summary>The near window's lattice: origin (x0, z0) and size in texels (<c>nearWindow</c>'s answer).</summary>
public readonly record struct NearWindowRect(double X0, double Z0, int Cols, int Rows);

/// <summary>
/// The pure CDLOD math of the browser's terrain (<c>client3d/src/scene/terrainLod.ts</c>, contract § A16.6), line for
/// line in the same double arithmetic; checked against <c>shared/test-vectors/terrain_lod.json</c>.
/// </summary>
public static class TerrainLod
{
    /// <summary><c>NEAR_MAX_TEXELS</c>, <c>NEAR_MARGIN_CELLS</c>, <c>NEAR_MARGIN_MIN_M</c>.</summary>
    public const int NearMaxTexels = 1025, NearMarginCells = 2;
    public const double NearMarginMinM = 16;

    /// <summary>
    /// <c>nearWindow</c>: the loaded tiles' bounding box grown by max(16 m, 2 overview steps), snapped onto the fine
    /// lattice, capped at 1025 texels per axis (then centred on the anchor). Keys are <c>"tx,tz"</c>; an unreadable
    /// key is skipped. <paramref name="overviewStep"/> null = the fine step (<c>overview?.step_m ?? step</c>).
    /// </summary>
    public static NearWindowRect? NearWindow(IReadOnlyCollection<string> keys, double tileM, double step,
                                             double? overviewStep, double anchorX, double anchorZ)
    {
        var parsed = new List<(double Tx, double Tz)>();
        foreach (var key in keys)
            parsed.Add(LayerCut.TryKey(key, out var tx, out var tz) ? (tx, tz) : (double.NaN, double.NaN));
        return NearWindow(parsed, tileM, step, overviewStep, anchorX, anchorZ);
    }

    /// <summary><see cref="NearWindow(IReadOnlyCollection{string}, double, double, double?, double, double)"/> on parsed keys (NaN = unreadable).</summary>
    public static NearWindowRect? NearWindow(IReadOnlyCollection<(double Tx, double Tz)> keys, double tileM, double step,
                                             double? overviewStep, double anchorX, double anchorZ)
    {
        if (keys.Count == 0 || !(step > 0) || !(tileM > 0)) return null;
        double x0 = double.PositiveInfinity, z0 = double.PositiveInfinity;
        double x1 = double.NegativeInfinity, z1 = double.NegativeInfinity;
        foreach (var (tx, tz) in keys)
        {
            if (!double.IsFinite(tx) || !double.IsFinite(tz)) continue;
            x0 = Math.Min(x0, tx * tileM);
            z0 = Math.Min(z0, tz * tileM);
            x1 = Math.Max(x1, (tx + 1) * tileM);
            z1 = Math.Max(z1, (tz + 1) * tileM);
        }
        if (!double.IsFinite(x0)) return null;
        double ovStep = overviewStep ?? step;
        double margin = Math.Max(NearMarginMinM, NearMarginCells * ovStep);
        x0 -= margin; z0 -= margin; x1 += margin; z1 += margin;
        x0 = Math.Floor(x0 / step) * step;
        z0 = Math.Floor(z0 / step) * step;
        double cols = Math.Floor((x1 - x0) / step) + 1;
        double rows = Math.Floor((z1 - z0) / step) + 1;
        if (cols > NearMaxTexels || rows > NearMaxTexels)
        {
            double halfX = Math.Min(cols, NearMaxTexels) * step / 2;
            double halfZ = Math.Min(rows, NearMaxTexels) * step / 2;
            x0 = Math.Floor((anchorX - halfX) / step) * step;
            z0 = Math.Floor((anchorZ - halfZ) / step) * step;
            cols = Math.Min(cols, NearMaxTexels);
            rows = Math.Min(rows, NearMaxTexels);
        }
        if (cols < 2 || rows < 2) return null;
        return new NearWindowRect(x0, z0, (int)cols, (int)rows);
    }
}
