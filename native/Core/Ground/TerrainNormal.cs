using System;
using System.Collections.Generic;
using AnimaNative.Terrain;

namespace AnimaNative.Ground;

/// <summary>One height lattice as the shader reads it with <c>texelFetch</c> (level 0 of a browser pyramid).</summary>
public sealed class HeightLattice
{
    public double OriginX, OriginZ, Step;
    public int Cols, Rows;
    public float[] H = Array.Empty<float>();

    public float At(int i, int j) => H[j * Cols + i];
}

/// <summary>
/// The terrain's SHADING NORMAL, per fragment, from the height field — the browser's <c>tlodNormalAt</c>
/// (<c>client3d/src/scene/terrainLod.ts</c> <c>terrainLodNormalGlsl</c> on <c>terrainLodSampleGlsl</c>):
///
///   n(x, z) = normalize(−(h(x+s, z) − h(x−s, z)), 2s, −(h(x, z+s) − h(x, z−s)))
///
/// with s = the base lattice step (<c>tile_step_m</c>) and h the FINEST level: level 0 of the near pyramid (the
/// loaded tiles plus a margin, filled through the tile-first height — <see cref="TerrainField"/>) inside its
/// rectangle, the overview's far pyramid outside, both read with four <c>texelFetch</c> and the bilinear of
/// <c>tlodGrid</c>. The CDLOD patches carry no normal of their own (it is straight up); this replaces it in the
/// fragment, like the browser. This class is the CPU twin the check compares with.
/// </summary>
public static class TerrainNormal
{
    /// <summary>
    /// Level 0 of a terrain pyramid (<see cref="TerrainField"/>) as the lattice the normal reads: the first
    /// <c>rows</c> texture rows of <c>texW</c> = cols texels each. Null for no pyramid.
    /// </summary>
    public static HeightLattice? Level0(HeightPyramid? pyr)
    {
        if (pyr is null || pyr.Levels.Count == 0) return null;
        var lv = pyr.Levels[0];
        var h = new float[lv.Cols * lv.Rows];
        for (int j = 0; j < lv.Rows; j++) Array.Copy(pyr.Data, (lv.Row0 + j) * pyr.TexW, h, j * lv.Cols, lv.Cols);
        return new HeightLattice { OriginX = pyr.OriginX, OriginZ = pyr.OriginZ, Step = lv.Step, Cols = lv.Cols, Rows = lv.Rows, H = h };
    }

    /// <summary><c>tlodGrid</c> on level 0.</summary>
    public static double Grid(HeightLattice? lv, double x, double z)
    {
        if (lv is null || lv.Cols < 2 || lv.Rows < 2 || lv.Step <= 0) return 0;
        double fx = Math.Clamp((x - lv.OriginX) / lv.Step, 0, lv.Cols - 1.0);
        double fz = Math.Clamp((z - lv.OriginZ) / lv.Step, 0, lv.Rows - 1.0);
        double fi = Math.Min(Math.Floor(fx), lv.Cols - 2.0), fj = Math.Min(Math.Floor(fz), lv.Rows - 2.0);
        double tx = fx - fi, tz = fz - fj;
        int i = (int)fi, j = (int)fj;
        double north = lv.At(i, j) * (1 - tx) + lv.At(i + 1, j) * tx;
        double south = lv.At(i, j + 1) * (1 - tx) + lv.At(i + 1, j + 1) * tx;
        return north * (1 - tz) + south * tz;
    }

    /// <summary><c>tlodHeight(p, 0)</c>: the near window inside its rectangle, else the far lattice.</summary>
    public static double Height(HeightLattice? near, double[]? rect, HeightLattice? far, double x, double z)
    {
        if (near is not null && rect is not null && x >= rect[0] && x <= rect[2] && z >= rect[1] && z <= rect[3])
            return Grid(near, x, z);
        return Grid(far, x, z);
    }

    /// <summary><c>tlodNormalAt</c>, world space.</summary>
    public static (double X, double Y, double Z) NormalAt(HeightLattice? near, double[]? rect, HeightLattice? far,
                                                         double span, double x, double z)
    {
        double s = Math.Max(span, 1e-3);
        double hx = Height(near, rect, far, x + s, z) - Height(near, rect, far, x - s, z);
        double hz = Height(near, rect, far, x, z + s) - Height(near, rect, far, x, z - s);
        double nx = -hx, ny = 2 * s, nz = -hz;
        double len = Math.Sqrt(nx * nx + ny * ny + nz * nz);
        return (nx / len, ny / len, nz / len);
    }
}
