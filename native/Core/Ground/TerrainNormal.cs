using System;
using AnimaNative.World;

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
/// with s = the base lattice step (<c>tile_step_m</c>) and h the FINEST level: the near window (the loaded
/// tiles plus a margin, filled through the tile-first height — <c>buildNear</c>) inside its rectangle, the
/// overview lattice (<c>buildFar</c>) outside, both read with four <c>texelFetch</c> and the bilinear of
/// <c>tlodGrid</c>. The S1a meshes carry vertex normals; this replaces them in the fragment, like the browser
/// (whose CDLOD patches carry no normal at all). This class is the CPU twin the check compares with.
/// </summary>
public static class TerrainNormal
{
    /// <summary><c>NEAR_MAX_TEXELS</c>, <c>NEAR_MARGIN_CELLS</c>, <c>NEAR_MARGIN_MIN_M</c> (terrainLod.ts).</summary>
    public const int NearMaxTexels = 1025, NearMarginCells = 2;
    public const double NearMarginMinM = 16;

    /// <summary><c>buildFar</c> level 0: the overview heights at their own lattice.</summary>
    public static HeightLattice? BuildFar(HeightGrid ov)
    {
        if (ov.Rows < 2 || ov.Cols < 2 || !(ov.Step > 0)) return null;
        return new HeightLattice { OriginX = ov.OriginX, OriginZ = ov.OriginZ, Step = ov.Step, Cols = ov.Cols, Rows = ov.Rows,
                                   H = (float[])ov.Heights.Clone() };
    }

    /// <summary>
    /// <c>buildNear</c>: the loaded tiles' bounding box grown by max(16 m, 2 overview steps), snapped onto the fine
    /// lattice, capped at 1025 texels per axis (then centred on the anchor), filled through the tile-first height.
    /// Rect = (x0, z0, x1, z1) of the lattice's outer support points.
    /// </summary>
    public static (HeightLattice Lattice, double[] Rect)? BuildNear(WorldHeight height, double step, double anchorX, double anchorZ)
    {
        double tileM = height.Overview.TileM;
        if (height.Tiles.Count == 0 || !(step > 0) || !(tileM > 0)) return null;
        double x0 = double.PositiveInfinity, z0 = double.PositiveInfinity, x1 = double.NegativeInfinity, z1 = double.NegativeInfinity;
        foreach (var t in height.Tiles)
        {
            x0 = Math.Min(x0, t.Key.Tx * tileM); z0 = Math.Min(z0, t.Key.Tz * tileM);
            x1 = Math.Max(x1, (t.Key.Tx + 1) * tileM); z1 = Math.Max(z1, (t.Key.Tz + 1) * tileM);
        }
        double ovStep = height.Overview.Grid.Step > 0 ? height.Overview.Grid.Step : step;
        double margin = Math.Max(NearMarginMinM, NearMarginCells * ovStep);
        x0 -= margin; z0 -= margin; x1 += margin; z1 += margin;
        x0 = Math.Floor(x0 / step) * step;
        z0 = Math.Floor(z0 / step) * step;
        int cols = (int)Math.Floor((x1 - x0) / step) + 1;
        int rows = (int)Math.Floor((z1 - z0) / step) + 1;
        if (cols > NearMaxTexels || rows > NearMaxTexels)
        {
            double halfX = Math.Min(cols, NearMaxTexels) * step / 2, halfZ = Math.Min(rows, NearMaxTexels) * step / 2;
            x0 = Math.Floor((anchorX - halfX) / step) * step;
            z0 = Math.Floor((anchorZ - halfZ) / step) * step;
            cols = Math.Min(cols, NearMaxTexels);
            rows = Math.Min(rows, NearMaxTexels);
        }
        if (cols < 2 || rows < 2) return null;
        var h = new float[cols * rows];
        for (int j = 0; j < rows; j++)
        for (int i = 0; i < cols; i++)
            h[j * cols + i] = (float)height.GroundAt(x0 + i * step, z0 + j * step);
        var lat = new HeightLattice { OriginX = x0, OriginZ = z0, Step = step, Cols = cols, Rows = rows, H = h };
        return (lat, new[] { x0, z0, x0 + (cols - 1) * step, z0 + (rows - 1) * step });
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
