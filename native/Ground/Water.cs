using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text.Json;
using AnimaNative.World;
using Godot;
using Json = AnimaNative.World.Json;

namespace AnimaNative.Ground;

/// <summary>One water kind's look (waterShade.ts <c>WaterLook</c>), packed 3 texels per row.</summary>
public readonly record struct WaterLook(Vector3 Tint, double SkyMix, double WaveM, double Speed, double FlowSpeed,
                                        double OpaqueDepthM, double Roughness, double Metalness);

/// <summary>
/// The water numbers and CPU twins of the browser's terrain water variant (client3d/src/scene/waterShade.ts,
/// waterPlaneMath.ts, terrainLod.ts <c>liftedHeight</c>). Under Wasser v2 K-A there is NO water mesh: a terrain
/// vertex is lifted onto <c>max(h, level)</c>, ramped by the shore gate, and the same pixels are shaded as water.
/// The literals of <see cref="GroundShader"/>'s water branch come from here.
/// </summary>
public static class Water
{
    public const double SdDry = WaterTileField.SdDry;
    public const double SdBandM = 0.5;
    public const double EdgeFadeM = 0.05;
    public const double FoamBandM = 0.6;
    public const double FoamStrength = 0.6;
    public const double FoamMinCover = 0.15;
    public const double ShallowSurfaceMin = 0.35;
    public const double DepthDefaultM = 2.0;
    public const double OpaqueFraction = 0.75;
    public const double MinSeeDepthM = 1.0;
    public const double FlowSpeedDefault = 0.5;
    /// <summary><c>surfaceSkyUniform</c> (scene-render materials.ts).</summary>
    public static readonly Vector3 Sky = new(0.62f, 0.78f, 0.91f);

    /// <summary><c>waterInside</c>: <c>smoothstep(0, 0.5 m, sd)</c>.</summary>
    public static double Inside(double sd)
    {
        double t = Math.Min(Math.Max(sd / SdBandM, 0), 1);
        return t * t * (3 - 2 * t);
    }

    /// <summary><c>liftedHeight(h, w, sd)</c>: the ground lifted onto the mirror, ramped by the gate; NaN w = dry.</summary>
    public static double Lifted(double h, double w, double sd)
    {
        double g = Inside(sd);
        return g > 0 && w > h ? h + (w - h) * g : h;
    }

    /// <summary><c>waterOpaqueDepthM</c>: ¾ of the bed depth (default 2 m), at least 1 m.</summary>
    public static double OpaqueDepthM(double? depthM)
    {
        double depth = depthM is double d && double.IsFinite(d) && d > 0 ? d : DepthDefaultM;
        return Math.Max(MinSeeDepthM, depth * OpaqueFraction);
    }

    /// <summary><c>waterTintRgb</c>: '#rrggbb' → 0…1 per channel, default #3f7fb8.</summary>
    public static Vector3 TintRgb(string? hex)
    {
        var text = (hex ?? "").Trim();
        if (!(text.Length == 7 && text[0] == '#' && int.TryParse(text[1..], NumberStyles.HexNumber, CultureInfo.InvariantCulture, out _)))
            text = "#3f7fb8";
        int v = int.Parse(text[1..], NumberStyles.HexNumber, CultureInfo.InvariantCulture);
        return new Vector3(((v >> 16) & 255) / 255f, ((v >> 8) & 255) / 255f, (v & 255) / 255f);
    }

    private static double Num(JsonElement? spec, string field, double fallback)
        => spec is { } s && s.TryGetProperty(field, out var v) && v.ValueKind == JsonValueKind.Number && double.IsFinite(v.GetDouble())
            ? v.GetDouble() : fallback;

    /// <summary><c>waterLookFrom(spec, depth)</c>.</summary>
    public static WaterLook LookFrom(JsonElement? spec, double? depthM)
        => new(TintRgb(spec is { } s && s.TryGetProperty("tint", out var t) && t.ValueKind == JsonValueKind.String ? t.GetString() : null),
               Num(spec, "sky_mix", 0.55), Math.Max(Num(spec, "wave_m", 1.6), 0.05), Num(spec, "speed", 0.05),
               Num(spec, "flow_speed", FlowSpeedDefault), OpaqueDepthM(depthM),
               Num(spec, "roughness", 0.08), Num(spec, "metalness", 0.15));

    /// <summary><c>packWaterLook</c>: per row (tint, sky_mix) (wave_m, speed, flow_speed, opaque) (roughness, metalness, 0, 0).</summary>
    public static float[] Pack(IReadOnlyList<WaterLook> looks)
    {
        int rows = Math.Max(1, looks.Count);
        var o = new float[rows * 12];
        for (int j = 0; j < rows; j++)
        {
            var l = j < looks.Count ? looks[j] : LookFrom(null, null);
            int b = j * 12;
            o[b] = l.Tint.X; o[b + 1] = l.Tint.Y; o[b + 2] = l.Tint.Z; o[b + 3] = (float)l.SkyMix;
            o[b + 4] = (float)l.WaveM; o[b + 5] = (float)l.Speed; o[b + 6] = (float)l.FlowSpeed; o[b + 7] = (float)l.OpaqueDepthM;
            o[b + 8] = (float)l.Roughness; o[b + 9] = (float)l.Metalness;
        }
        return o;
    }

    /// <summary>
    /// <c>makeWaveNormal</c> (scene-render materials.ts): the one procedural, seamless 256² wave normal map — a sum
    /// of four sine layers with integer frequencies, central differences, scale 0.02, tangent space +z up.
    /// </summary>
    public static Image WaveNormal()
    {
        const int n = 256;
        var layers = new (double Fx, double Fy, double A, double Ph)[] { (1, 2, 1.0, 0.0), (2, -1, 0.7, 1.7), (3, 2, 0.4, 3.1), (-2, 3, 0.3, 5.0) };
        double H(double u, double v)
        {
            double s = 0;
            foreach (var (fx, fy, a, ph) in layers) s += a * Math.Sin(2 * Math.PI * (fx * u + fy * v) + ph);
            return s;
        }
        var data = new byte[n * n * 4];
        double d = 1.0 / n;
        for (int y = 0; y < n; y++)
        for (int x = 0; x < n; x++)
        {
            double u = (double)x / n, v = (double)y / n;
            double dx = (H(u + d, v) - H(u - d, v)) / (2 * d);
            double dy = (H(u, v + d) - H(u, v - d)) / (2 * d);
            double nx = -dx * 0.02, ny = -dy * 0.02, nz = 1;
            double len = Math.Sqrt(nx * nx + ny * ny + nz * nz);
            nx /= len; ny /= len;
            int i = (y * n + x) * 4;
            data[i] = (byte)Math.Round((nx * 0.5 + 0.5) * 255);
            data[i + 1] = (byte)Math.Round((ny * 0.5 + 0.5) * 255);
            data[i + 2] = (byte)Math.Round((nz / len * 0.5 + 0.5) * 255);
            data[i + 3] = 255;
        }
        var img = Image.CreateFromData(n, n, false, Image.Format.Rgba8, data);
        img.GenerateMipmaps();
        return img;
    }
}

/// <summary>
/// The water window the water variant samples (the browser's water pyramid base level over the near window):
/// the loaded wet tiles merged onto ONE 2 m lattice spanning their bounding tiles — sd (R32F, dry = −1e4), kind
/// row (R32F, resolved on the CPU like <c>buildKindRows</c>, unknown kind → row 0 = the primary water) and flow
/// (RG32F, 0 = still). Tiles share their edge rows, so the merge is exact.
/// </summary>
public sealed class WaterWindow
{
    public double OriginX, OriginZ, Step;
    public int Cols, Rows;
    public float[] Sd = Array.Empty<float>();
    public float[] KindRow = Array.Empty<float>();
    public float[] Flow = Array.Empty<float>();
    public int Tiles, WetTexels;

    public static WaterWindow? Build(IEnumerable<(int Tx, int Tz, WaterTileField F)> tiles, double tileM,
                                     IReadOnlyDictionary<string, int> rowOfKind)
    {
        var list = tiles.ToList();
        if (list.Count == 0) return null;
        double step = list[0].F.Step;
        int per = (int)Math.Round(tileM / step);
        int tx0 = list.Min(t => t.Tx), tz0 = list.Min(t => t.Tz);
        int tx1 = list.Max(t => t.Tx), tz1 = list.Max(t => t.Tz);
        var w = new WaterWindow
        {
            OriginX = tx0 * tileM, OriginZ = tz0 * tileM, Step = step,
            Cols = (tx1 - tx0 + 1) * per + 1, Rows = (tz1 - tz0 + 1) * per + 1, Tiles = list.Count,
        };
        w.Sd = new float[w.Cols * w.Rows];
        Array.Fill(w.Sd, (float)Water.SdDry);
        w.KindRow = new float[w.Cols * w.Rows];
        w.Flow = new float[w.Cols * w.Rows * 2];
        foreach (var (tx, tz, f) in list)
        {
            int oi = (int)Math.Round((f.OriginX - w.OriginX) / step), oj = (int)Math.Round((f.OriginZ - w.OriginZ) / step);
            var rows = f.Kinds.Select(k => rowOfKind.TryGetValue(k.ToLowerInvariant(), out var r) ? r : 0).ToArray();
            for (int j = 0; j < f.Rows; j++)
            for (int i = 0; i < f.Cols; i++)
            {
                int gi = oi + i, gj = oj + j;
                if (gi < 0 || gj < 0 || gi >= w.Cols || gj >= w.Rows) continue;
                int k = j * f.Cols + i, g = gj * w.Cols + gi;
                w.Sd[g] = f.Sd[k];
                int idx = f.KindIdx[k];
                w.KindRow[g] = idx >= 0 && idx < rows.Length ? rows[idx] : 0;
                w.Flow[2 * g] = f.FlowX?[k] ?? 0;
                w.Flow[2 * g + 1] = f.FlowZ?[k] ?? 0;
            }
            w.WetTexels += f.Wet;
        }
        return w;
    }
}
