using System;
using System.Collections.Generic;
using AnimaNative.Water;

namespace AnimaNative.Terrain;

/// <summary>A float texture as the shader reads it with <c>texelFetch</c>: row-major, <see cref="W"/> texels per row.</summary>
public sealed record TwinTexture(float[] Data, int W, int H)
{
    /// <summary><c>texelFetch(tex, ivec2(i, j), 0).r</c>; a fetch outside the texture is a bug the shader must never make.</summary>
    public double Fetch(int i, int j)
    {
        if (i < 0 || j < 0 || i >= W || j >= H)
            throw new InvalidOperationException($"texelFetch ({i}, {j}) outside a {W}x{H} texture");
        return Data[j * W + i];
    }
}

/// <summary>
/// The uniform values of the terrain programs as the GPU holds them — what <see cref="TerrainLodGlsl"/> declares, one
/// field per uniform (vectors as double arrays, a level array as rows of four). A null texture is the unbound one: the
/// twin throws if the shader logic would read it.
/// </summary>
public sealed record TerrainShaderState(
    TwinTexture? Near, double[] NearGeom, double[][] NearLevels, double[] NearRect,
    TwinTexture? Far, double[] FarGeom, double[][] FarLevels,
    double[] Extent, double[] Range, double BaseStep, double NormalSpan,
    TwinTexture? Cap, double[] CapGeom, double[] CapFit,
    TwinTexture? Water, TwinTexture? WaterSd, double[] WaterGeom, double[][] WaterLevels)
{
    /// <summary>The state <see cref="TerrainField.Uniforms"/> + one frame's rings and cap relaxation describe (what the client uploads).</summary>
    public static TerrainShaderState From(TerrainUniforms u, TerrainFrame frame)
    {
        static TwinTexture? Tex(HeightPyramid? p) => p is null ? null : new TwinTexture(p.Data, p.TexW, p.TexH);
        var range = new double[TerrainLod.MaxLodLevels];
        for (int i = 0; i < range.Length; i++) range[i] = i < frame.Ranges.Count ? frame.Ranges[i] : 0;
        return new TerrainShaderState(
            Tex(u.Near), u.NearGeom, u.NearLevels, u.NearRect,
            Tex(u.Far), u.FarGeom, u.FarLevels,
            u.Extent, range, u.BaseStep, u.NormalSpan,
            u.Cap is { } c ? new TwinTexture(c.Caps, c.Cols, c.Rows) : null, u.CapGeom,
            new double[] { u.Cap?.Rows ?? 0, frame.CapRelax, 0, 0 },
            Tex(u.Water), u.WaterSd is { } sd ? new TwinTexture(sd.Data, sd.Cols, sd.Rows) : null, u.WaterGeom, u.WaterLevels);
    }
}

/// <summary>
/// The GPU-free twin of the terrain vertex stage: <see cref="TerrainLodGlsl"/> statement for statement, in double,
/// reading the uniform values a <see cref="TerrainShaderState"/> holds and the constants of <see cref="TerrainLod"/> /
/// <see cref="WaterShade"/> (the same numbers the shader text prints). The check runs it on the state READ BACK from
/// the Godot materials and compares it with <see cref="TerrainLod.LodVertex"/> — the vector-checked CPU answer — so a
/// wrong texture, level row, rectangle, frame, ring or instance number shows as a different vertex.
/// </summary>
public static class TerrainShaderTwin
{
    private const double Dry = -1.0e30;

    private static double Clamp(double v, double lo, double hi) => Math.Min(Math.Max(v, lo), hi);
    private static double Mix(double a, double b, double t) => a * (1 - t) + b * t;
    /// <summary>GLSL <c>mod(x, y)</c> = x − y·floor(x/y).</summary>
    private static double Mod(double x, double y) => x - y * Math.Floor(x / y);

    private static double Grid(TwinTexture? tex, double ox, double oz, double[] lv, double px, double pz)
    {
        double cols = lv[0], rows = lv[1], stp = lv[2];
        if (cols < 2 || rows < 2 || stp <= 0) return 0;
        if (tex is null) throw new InvalidOperationException("the shader would read an unbound height texture");
        double fx = Clamp((px - ox) / stp, 0, cols - 1), fz = Clamp((pz - oz) / stp, 0, rows - 1);
        double fi = Math.Min(Math.Floor(fx), cols - 2), fj = Math.Min(Math.Floor(fz), rows - 2);
        double tx = fx - fi, tz = fz - fj;
        int i = (int)fi, j = (int)(fj + lv[3]);
        double north = tex.Fetch(i, j) * (1 - tx) + tex.Fetch(i + 1, j) * tx;
        double south = tex.Fetch(i, j + 1) * (1 - tx) + tex.Fetch(i + 1, j + 1) * tx;
        return north * (1 - tz) + south * tz;
    }

    private static int Level(double baseStep, double count, double nodeStep)
    {
        if (baseStep <= 0) return 0;
        double k = Math.Floor(Math.Log2(Math.Max(nodeStep / baseStep, 1)) + 0.5);
        return (int)Clamp(k, 0, count - 1);
    }

    /// <summary><c>tl_height(p, node_step)</c>.</summary>
    public static double Height(TerrainShaderState s, double px, double pz, double nodeStep)
    {
        var r = s.NearRect;
        if (s.NearGeom[3] > 0 && px >= r[0] && px <= r[2] && pz >= r[1] && pz <= r[3])
            return Grid(s.Near, s.NearGeom[0], s.NearGeom[1], s.NearLevels[Level(s.NearGeom[2], s.NearGeom[3], nodeStep)], px, pz);
        if (s.FarGeom[3] <= 0) return 0;
        return Grid(s.Far, s.FarGeom[0], s.FarGeom[1], s.FarLevels[Level(s.FarGeom[2], s.FarGeom[3], nodeStep)], px, pz);
    }

    private static double Lambda(TerrainShaderState s, double d)
    {
        double lam = 0, prev = 0;
        for (int i = 0; i < TerrainLod.MaxLodLevels; i++)
        {
            double r = s.Range[i];
            if (!(r > 0)) continue;
            double st = prev + TerrainLod.MorphStart * (r - prev);
            prev = r;
            lam += r > st ? Clamp((d - st) / (r - st), 0, 1) : d >= r ? 1 : 0;
        }
        return lam;
    }

    private static double CapAt(TerrainShaderState s, double px, double pz)
    {
        double cols = s.CapGeom[3], rows = s.CapFit[0], stp = s.CapGeom[2];
        if (cols < 2 || rows < 2 || stp <= 0) return TerrainLod.LodCapNone;
        double fx = (px - s.CapGeom[0]) / stp, fz = (pz - s.CapGeom[1]) / stp;
        if (fx <= 0 || fz <= 0 || fx >= cols - 1 || fz >= rows - 1) return TerrainLod.LodCapNone;
        if (s.Cap is null) throw new InvalidOperationException("the shader would read an unbound cap texture");
        double fi = Math.Floor(fx), fj = Math.Floor(fz), tx = fx - fi, tz = fz - fj;
        int i = (int)fi, j = (int)fj;
        double north = s.Cap.Fetch(i, j) * (1 - tx) + s.Cap.Fetch(i + 1, j) * tx;
        double south = s.Cap.Fetch(i, j + 1) * (1 - tx) + s.Cap.Fetch(i + 1, j + 1) * tx;
        return north * (1 - tz) + south * tz + s.CapFit[1];
    }

    private static double MorphAt(TerrainShaderState s, double[] node, double gx, double gz, double nodeStep,
                                  (double X, double Y, double Z) eye)
    {
        double px = Clamp(node[0] + gx * nodeStep, s.Extent[0], s.Extent[2]);
        double pz = Clamp(node[1] + gz * nodeStep, s.Extent[1], s.Extent[3]);
        double dx = px - eye.X, dy = Height(s, px, pz, 0) - eye.Y, dz = pz - eye.Z;
        double d = Math.Sqrt(dx * dx + dy * dy + dz * dz);
        return Math.Max(Math.Min(Lambda(s, d), CapAt(s, px, pz)) - node[3], 0);
    }

    private static double WaterGrid(TerrainShaderState s, double[] lv, double px, double pz)
    {
        double cols = lv[0], rows = lv[1], stp = lv[2];
        if (cols < 2 || rows < 2 || stp <= 0) return Dry;
        if (s.Water is null) throw new InvalidOperationException("the shader would read an unbound water texture");
        double fx = Clamp((px - s.WaterGeom[0]) / stp, 0, cols - 1), fz = Clamp((pz - s.WaterGeom[1]) / stp, 0, rows - 1);
        double fi = Math.Min(Math.Floor(fx), cols - 2), fj = Math.Min(Math.Floor(fz), rows - 2);
        double tx = fx - fi, tz = fz - fj;
        int i = (int)fi, j = (int)(fj + lv[3]);
        double w00 = (1 - tx) * (1 - tz), w10 = tx * (1 - tz), w01 = (1 - tx) * tz, w11 = tx * tz;
        double sum = 0;
        if (w00 != 0) sum += s.Water.Fetch(i, j) * w00;
        if (w10 != 0) sum += s.Water.Fetch(i + 1, j) * w10;
        if (w01 != 0) sum += s.Water.Fetch(i, j + 1) * w01;
        if (w11 != 0) sum += s.Water.Fetch(i + 1, j + 1) * w11;
        return sum;
    }

    private static double WaterAt(TerrainShaderState s, double px, double pz, double nodeStep)
    {
        var r = s.NearRect;
        if (s.WaterGeom[3] <= 0 || px < r[0] || px > r[2] || pz < r[1] || pz > r[3]) return Dry;
        return WaterGrid(s, s.WaterLevels[Level(s.WaterGeom[2], s.WaterGeom[3], nodeStep)], px, pz);
    }

    /// <summary><c>tl_sd_at(p)</c>: the outline distance on the water lattice, dry outside it.</summary>
    public static double SdAt(TerrainShaderState s, double px, double pz)
    {
        const double sdDry = Ground.WaterTileField.SdDry;
        if (s.WaterGeom[3] <= 0) return sdDry;
        if (s.WaterSd is null) throw new InvalidOperationException("the shader would read an unbound sd texture");
        double cols = s.WaterSd.W, rows = s.WaterSd.H, stp = s.WaterGeom[2];
        if (cols < 2 || rows < 2 || stp <= 0) return sdDry;
        double fx = (px - s.WaterGeom[0]) / stp, fz = (pz - s.WaterGeom[1]) / stp;
        if (fx < 0 || fz < 0 || fx > cols - 1 || fz > rows - 1) return sdDry;
        double fi = Math.Min(Math.Floor(fx), cols - 2), fj = Math.Min(Math.Floor(fz), rows - 2);
        double tx = fx - fi, tz = fz - fj;
        int i = (int)fi, j = (int)fj;
        return Mix(Mix(s.WaterSd.Fetch(i, j), s.WaterSd.Fetch(i + 1, j), tx),
                   Mix(s.WaterSd.Fetch(i, j + 1), s.WaterSd.Fetch(i + 1, j + 1), tx), tz);
    }

    private static double Lift(TerrainShaderState s, double h, double px, double pz, double nodeStep, double sd)
    {
        double c = Clamp(sd / WaterShade.SdBandM, 0, 1);
        double g = c * c * (3 - 2 * c);
        if (g <= 0) return h;
        double w = WaterAt(s, px, pz, nodeStep);
        return w > h ? h + (w - h) * g : h;
    }

    /// <summary>
    /// <c>tl_compute(node, patch_xz, eye, wet)</c>: the drawn world point of the patch vertex (<paramref name="patchX"/>,
    /// <paramref name="patchZ"/>) ∈ [0, 1]² of the instance <paramref name="node"/> = (x, z, size, level), and (wet
    /// program) the water depth over the drawn bed.
    /// </summary>
    public static (double X, double Y, double Z, double Wet) Compute(TerrainShaderState s, double[] node, double patchX, double patchZ,
                                                                    (double X, double Y, double Z) eye, bool water)
    {
        double nodeStep = s.BaseStep * Math.Pow(2, node[3]);
        double cells = Math.Floor(node[2] / nodeStep + 0.5);
        double gx = Math.Min(patchX * TerrainLod.PatchN, cells), gz = Math.Min(patchZ * TerrainLod.PatchN, cells);
        double k = 0;
        double t = MorphAt(s, node, gx, gz, nodeStep, eye);
        for (int j = TerrainLod.MaxLodLevels - 1; j >= 1; j--)
        {
            double m = Math.Pow(2, j);
            double tj = MorphAt(s, node, gx - Mod(gx, m), gz - Mod(gz, m), nodeStep, eye);
            if (Math.Floor(tj) >= j) { k = j; t = tj; break; }
        }
        double f = Clamp(t - k, 0, 1);
        double m1 = Math.Pow(2, k), m2 = m1 * 2;
        double gmx = Mix(gx - Mod(gx, m1), gx - Mod(gx, m2), f), gmz = Mix(gz - Mod(gz, m1), gz - Mod(gz, m2), f);
        double px = Clamp(node[0] + gmx * nodeStep, s.Extent[0], s.Extent[2]);
        double pz = Clamp(node[1] + gmz * nodeStep, s.Extent[1], s.Extent[3]);
        if (!water) return (px, Mix(Height(s, px, pz, nodeStep * m1), Height(s, px, pz, nodeStep * m2), f), pz, 0);
        double sdw = SdAt(s, px, pz);
        double h1 = Height(s, px, pz, nodeStep * m1), h2 = Height(s, px, pz, nodeStep * m2);
        double l1 = Lift(s, h1, px, pz, nodeStep * m1, sdw), l2 = Lift(s, h2, px, pz, nodeStep * m2, sdw);
        return (px, Mix(l1, l2, f), pz, Mix(l1 - h1, l2 - h2, f));
    }

    /// <summary>The patch vertices the checks sample per piece: corners, edges, an inner lattice point, the quadrant edge.</summary>
    public static IReadOnlyList<(int I, int J)> SampleVertices { get; } = new[]
    {
        (0, 0), (32, 0), (0, 32), (32, 32), (1, 1), (7, 3), (16, 16), (17, 9), (31, 30), (16, 32), (5, 16),
    };
}
