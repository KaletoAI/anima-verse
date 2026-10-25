using System;
using System.Collections.Generic;

namespace AnimaNative.Scatter;

/// <summary>
/// The pure half of <c>client3d/src/scene/undergrowth.ts</c>: the 64 m cell raster around the anchor,
/// the per-cell seed, the procedural blade texture, the three-plane star tuft and the colour variation.
/// </summary>
public static class UndergrowthMath
{
    private const int MaxCellsPerAxis = 32;
    public const int TexSize = 64;
    public const int Blades = 9;
    private const double BladeHalfW = 0.045;
    private const double BladeBend = 0.12;
    private static readonly double[] BladeHeights = { 0.55, 0.725, 0.90 };
    private const double BladeShadeMin = 0.7, BladeShadeSpan = 0.3;
    private static readonly double[] BladeBrown = { 1.20, 0.86, 0.97 };
    private static readonly double[] BladeGreen = { 0.80, 1.14, 1.03 };
    private const double BladeBrightSpan = 0.10;
    private static readonly int[] BladeRamp = { 5, 1, 6, 0, 8, 2, 7, 3, 4 };
    public static readonly double BladeTintMax = BladeBrown[0] * (1 + BladeBrightSpan / 2);
    public static readonly double HRefM = (ScatterLod.UgHMin + ScatterLod.UgHMax) / 2;
    private const double WRatio = 1.25;
    private static readonly double[] StarDeg = { 0, 55, 118 };
    public const double AlphaTest = 0.35;
    public const double Albedo = 0.75;
    /// <summary>UNDERGROWTH_REACH_M — the bounding-sphere padding of a cell layer.</summary>
    public static readonly double ReachM = ScatterLod.UgHMax + (ScatterLod.UgHMax * WRatio) / 2 + 0.5;
    private const double ShadeR = 0.24, ShadeG = 0.10, ShadeB = 0.05;
    public static readonly double[] TintA = { 1 + ShadeR, 1 - ShadeG, 1 - ShadeB };
    public static readonly double[] TintB = { 1 - ShadeR, 1 + ShadeG, 1 + ShadeB };

    public static string CellKey(int cx, int cz) => $"{cx},{cz}";

    public static string CellSeed(string areaId, int cx, int cz) => $"terrain:undergrowth:{areaId}:{cx},{cz}";

    /// <summary><c>wantedUndergrowthCells</c>: cells whose square lies within the radius, nearest first,
    /// ties by key (string order).</summary>
    public static List<(int Cx, int Cz)> WantedCells(double x, double z, double radiusM = ScatterLod.UgCellRadiusM)
    {
        var result = new List<(int, int)>();
        if (!double.IsFinite(x) || !double.IsFinite(z) || !(radiusM >= 0)) return result;
        double cell = ScatterLod.UgCellM;
        int firstX = (int)Math.Floor((x - radiusM) / cell), lastX = (int)Math.Floor((x + radiusM) / cell);
        int firstZ = (int)Math.Floor((z - radiusM) / cell), lastZ = (int)Math.Floor((z + radiusM) / cell);
        if (lastX - firstX > MaxCellsPerAxis || lastZ - firstZ > MaxCellsPerAxis) return result;
        double reach = radiusM * radiusM;
        var hits = new List<(string Key, double D2, int Cx, int Cz)>();
        for (int cz = firstZ; cz <= lastZ; cz += 1)
        {
            double dz = Math.Max(Math.Max(cz * cell - z, 0), z - (cz + 1) * cell);
            for (int cx = firstX; cx <= lastX; cx += 1)
            {
                double dx = Math.Max(Math.Max(cx * cell - x, 0), x - (cx + 1) * cell);
                double d2 = dx * dx + dz * dz;
                if (d2 > reach) continue;
                hits.Add((CellKey(cx, cz), d2, cx, cz));
            }
        }
        hits.Sort((a, b) => a.D2 != b.D2 ? a.D2.CompareTo(b.D2) : string.CompareOrdinal(a.Key, b.Key));
        foreach (var h in hits) result.Add((h.Cx, h.Cz));
        return result;
    }

    public static double[][] BladeTints()
    {
        var tints = new double[BladeRamp.Length][];
        for (int i = 0; i < BladeRamp.Length; i++)
        {
            double u = (double)BladeRamp[i] / (BladeRamp.Length - 1);
            double bright = 1 - BladeBrightSpan * (u - 0.5);
            tints[i] = new[]
            {
                (BladeBrown[0] + (BladeGreen[0] - BladeBrown[0]) * u) * bright,
                (BladeBrown[1] + (BladeGreen[1] - BladeBrown[1]) * u) * bright,
                (BladeBrown[2] + (BladeGreen[2] - BladeBrown[2]) * u) * bright,
            };
        }
        return tints;
    }

    private static byte Clamp8(double v) => v <= 0 ? (byte)0 : v >= 255 ? (byte)255 : (byte)v;

    /// <summary><c>undergrowthTexturePixels</c>: RGBA bytes, row 0 = the blade ROOTS (three's DataTexture
    /// has flipY false, so row 0 sits at v = 0, the bottom of the quad).</summary>
    public static byte[] TexturePixels(int size = TexSize)
    {
        int n = Math.Max(1, size);
        var outBytes = new byte[n * n * 4];
        var tints = BladeTints();
        var blades = new (double RootX, double HeightPx, double Bend, double HalfW0, double[] Tint)[Blades];
        for (int i = 0; i < Blades; i += 1)
            blades[i] = (((i + 0.5) / Blades) * n, BladeHeights[i % BladeHeights.Length] * n,
                         BladeBend * n * (i % 2 == 0 ? 1 : -1), BladeHalfW * n, tints[i % tints.Length]);
        var neutral = new double[] { 1, 1, 1 };
        for (int r = 0; r < n; r += 1)
        {
            double py = r + 0.5;
            double grey = (BladeShadeMin + BladeShadeSpan * (py / n)) / BladeTintMax;
            for (int c = 0; c < n; c += 1)
            {
                double px = c + 0.5;
                double best = 0;
                int win = -1;
                for (int b = 0; b < blades.Length; b += 1)
                {
                    var bl = blades[b];
                    double t = py / bl.HeightPx;
                    if (t > 1) continue;
                    double x = bl.RootX + bl.Bend * t * t;
                    double halfW = bl.HalfW0 * (1 - t);
                    double v = halfW - Math.Abs(px - x) + 0.5;
                    if (v > best) { best = v; win = b; }
                }
                double cov = best > 1 ? 1 : best;
                var tint = win >= 0 ? blades[win].Tint : neutral;
                int o = (r * n + c) * 4;
                outBytes[o] = Clamp8(Js.Round(255 * grey * tint[0]));
                outBytes[o + 1] = Clamp8(Js.Round(255 * grey * tint[1]));
                outBytes[o + 2] = Clamp8(Js.Round(255 * grey * tint[2]));
                outBytes[o + 3] = Clamp8(Js.Round(255 * cov));
            }
        }
        return outBytes;
    }

    /// <summary><c>undergrowthGeometry</c>: three vertical quads at 0/55/118°, both windings (12 triangles).
    /// Indices in three's order; the caller reverses them for Godot's clockwise front face (both windings
    /// are present either way).</summary>
    public static (float[] Pos, float[] Uv, int[] Index) Geometry(double h)
    {
        double halfW = (h * WRatio) / 2;
        var pos = new List<float>();
        var uv = new List<float>();
        foreach (double deg in StarDeg)
        {
            double c = Math.Cos((deg * Math.PI) / 180), s = Math.Sin((deg * Math.PI) / 180);
            pos.AddRange(new[]
            {
                (float)(-halfW * c), 0f, (float)(halfW * s), (float)(halfW * c), 0f, (float)(-halfW * s),
                (float)(halfW * c), (float)h, (float)(-halfW * s), (float)(-halfW * c), (float)h, (float)(halfW * s),
            });
            uv.AddRange(new[] { 0f, 0f, 1f, 0f, 1f, 1f, 0f, 1f });
        }
        var index = new List<int>();
        for (int q = 0; q < StarDeg.Length; q += 1)
        {
            int v = q * 4;
            index.AddRange(new[] { v, v + 1, v + 2, v, v + 2, v + 3 });
        }
        int forward = index.Count;
        for (int t = 0; t < forward; t += 3) index.AddRange(new[] { index[t], index[t + 2], index[t + 1] });
        return (pos.ToArray(), uv.ToArray(), index.ToArray());
    }

    /// <summary><c>undergrowthShade</c>: a [0, 1) hash of the instance's float32 position (centimetres).</summary>
    public static double Shade(double x, double z)
    {
        double xv = Js.Fround(x), zv = Js.Fround(z);
        if (!double.IsFinite(xv) || !double.IsFinite(zv)) return 0.5;
        int xi = Js.ToInt32(Js.Round(xv * 100));
        int zi = Js.ToInt32(Js.Round(zv * 100));
        return ScatterLod.InstanceHash(unchecked(xi * 73856093 ^ zi * 19349663));
    }

    public static (double R, double G, double B) Tint(double h)
    {
        double t = double.IsFinite(h) ? Math.Min(Math.Max(h, 0), 1) : 0.5;
        return (TintA[0] + (TintB[0] - TintA[0]) * t, TintA[1] + (TintB[1] - TintA[1]) * t,
                TintA[2] + (TintB[2] - TintA[2]) * t);
    }
}
