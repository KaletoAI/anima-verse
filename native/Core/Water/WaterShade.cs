using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text.Json;
using AnimaNative.Ground;
using AnimaNative.Scatter;

namespace AnimaNative.Water;

/// <summary>One water kind's look (waterShade.ts <c>WaterLook</c>), packed 3 texels per row. Tint is 0…1 per channel.</summary>
public readonly record struct WaterLook((double R, double G, double B) Tint, double SkyMix, double WaveM, double Speed,
                                        double FlowSpeed, double OpaqueDepthM, double Roughness, double Metalness);

/// <summary>
/// The water numbers and CPU twins of the browser's terrain water variant (client3d/src/scene/waterShade.ts,
/// waterPlaneMath.ts, terrainLod.ts <c>liftedHeight</c>, scene-render materials.ts <c>waveNormalSample</c>). Under
/// Wasser v2 K-A there is NO water mesh: a terrain vertex is lifted onto <c>max(h, level)</c>, ramped by the shore
/// gate, and the same pixels are shaded as water. The literals of <c>GroundShader</c>'s water branch come from here.
/// </summary>
public static class WaterShade
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
    /// <summary><c>surfaceSkyUniform</c> (scene-render materials.ts), sRGB numbers.</summary>
    public static readonly (double R, double G, double B) Sky = (0.62, 0.78, 0.91);

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

    /// <summary><c>liftedDepth(h, w, sd)</c>: how far the gate lifts the ground (the varying <c>vTlodWet</c>); 0 where dry.</summary>
    public static double LiftedDepth(double h, double w, double sd)
    {
        double g = Inside(sd);
        return g > 0 && w > h ? (w - h) * g : 0;
    }

    private static double Smoothstep01(double t)
    {
        double c = t <= 0 ? 0 : t >= 1 ? 1 : t;
        return c * c * (3 - 2 * c);
    }

    /// <summary><c>waterShoreAlpha(depth, opaque)</c>: smoothstep of depth / opaque depth; no depth = 0.</summary>
    public static double ShoreAlpha(double depthM, double opaqueDepthM)
        => !double.IsFinite(depthM) || depthM <= 0 ? 0 : Smoothstep01(depthM / opaqueDepthM);

    /// <summary><c>waterFoam(depth)</c>: 1 − smoothstep(depth / 0.6 m); no depth = full foam.</summary>
    public static double Foam(double depthM)
        => !double.IsFinite(depthM) || depthM <= 0 ? 1 : 1 - Smoothstep01(depthM / FoamBandM);

    /// <summary><c>waterEdgeFade(depth, edge)</c>: the rim ramp over max(edge, 5 cm); no depth = 0.</summary>
    public static double EdgeFade(double depthM, double edgeM)
    {
        double e = Math.Max(edgeM, EdgeFadeM);
        if (!double.IsFinite(depthM) || depthM <= 0) return 0;
        double t = depthM / e;
        return t >= 1 ? 1 : t;
    }

    /// <summary><c>waterAbsorb(depth, opaque, edge)</c>: how much of the bed the water hides (the tint share).</summary>
    public static double Absorb(double depthM, double opaqueDepthM, double edgeM)
        => !(depthM > 0) ? 0 : ShoreAlpha(depthM, Math.Max(opaqueDepthM, 1e-3)) * EdgeFade(depthM, edgeM);

    /// <summary><c>waterShallowRamp(depth, opaque)</c>: the surface share ramp, 0.35 at the shore to 1 at the opaque depth.</summary>
    public static double ShallowRamp(double depthM, double opaqueDepthM)
        => ShallowSurfaceMin + (1 - ShallowSurfaceMin) * ShoreAlpha(depthM, Math.Max(opaqueDepthM, 1e-3));

    /// <summary><c>waterSurface(depth, edge, inside, opaque)</c>: the share of the water's own surface (ripple, sky).</summary>
    public static double Surface(double depthM, double edgeM, double inside, double opaqueDepthM)
    {
        if (!(depthM > 0)) return 0;
        double g = !double.IsFinite(inside) ? 0 : inside <= 0 ? 0 : inside >= 1 ? 1 : inside;
        return EdgeFade(depthM, edgeM) * g * ShallowRamp(depthM, opaqueDepthM);
    }

    /// <summary><c>waterFoamAt(depth, opaque, edge)</c>: the shore foam, covered by the shore share plus 15 % of itself.</summary>
    public static double FoamAt(double depthM, double opaqueDepthM, double edgeM)
    {
        if (!(depthM > 0)) return 0;
        double foam = Foam(depthM);
        double cover = Math.Min(ShoreAlpha(depthM, Math.Max(opaqueDepthM, 1e-3)) + foam * FoamMinCover, 1);
        return foam * cover * EdgeFade(depthM, edgeM);
    }

    /// <summary><c>waterOpaqueDepthM</c>: ¾ of the bed depth (default 2 m), at least 1 m.</summary>
    public static double OpaqueDepthM(double? depthM)
    {
        double depth = depthM is double d && double.IsFinite(d) && d > 0 ? d : DepthDefaultM;
        return Math.Max(MinSeeDepthM, depth * OpaqueFraction);
    }

    /// <summary><c>waterTintRgb</c>: '#rrggbb' → 0…1 per channel, default #3f7fb8.</summary>
    public static (double R, double G, double B) TintRgb(string? hex)
    {
        // /^#[0-9a-fA-F]{6}$/ on hex.trim(): exactly six hex digits, nothing else (int.TryParse would let white
        // space through), trimmed with the JS white-space set.
        var text = JsTrim(hex ?? "");
        if (!(text.Length == 7 && text[0] == '#' && text.Skip(1).All(Uri.IsHexDigit)))
            text = "#3f7fb8";
        int v = int.Parse(text[1..], NumberStyles.HexNumber, CultureInfo.InvariantCulture);
        return (((v >> 16) & 255) / 255.0, ((v >> 8) & 255) / 255.0, (v & 255) / 255.0);
    }

    private static string JsTrim(string s)
    {
        int a = 0, b = s.Length;
        while (a < b && Overview.JsSemantics.IsWhiteSpace(s[a])) a++;
        while (b > a && Overview.JsSemantics.IsWhiteSpace(s[b - 1])) b--;
        return s[a..b];
    }

    private static double Num(JsonElement? spec, string field, double fallback)
        => spec is { } s && s.ValueKind == JsonValueKind.Object && s.TryGetProperty(field, out var v)
           && v.ValueKind == JsonValueKind.Number && double.IsFinite(v.GetDouble())
            ? v.GetDouble() : fallback;

    /// <summary><c>waterLookFrom(spec, depth)</c>.</summary>
    public static WaterLook LookFrom(JsonElement? spec, double? depthM)
        => new(TintRgb(spec is { ValueKind: JsonValueKind.Object } s && s.TryGetProperty("tint", out var t)
                       && t.ValueKind == JsonValueKind.String ? t.GetString() : null),
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
            o[b] = (float)l.Tint.R; o[b + 1] = (float)l.Tint.G; o[b + 2] = (float)l.Tint.B; o[b + 3] = (float)l.SkyMix;
            o[b + 4] = (float)l.WaveM; o[b + 5] = (float)l.Speed; o[b + 6] = (float)l.FlowSpeed; o[b + 7] = (float)l.OpaqueDepthM;
            o[b + 8] = (float)l.Roughness; o[b + 9] = (float)l.Metalness;
        }
        return o;
    }

    /// <summary>
    /// <c>waveNormalSample</c> (scene-render materials.ts): one RGBA8 texel of the procedural, seamless wave normal
    /// map — a sum of four sine layers with integer frequencies, central differences, scale 0.02, tangent space +z up.
    /// </summary>
    public static byte[] WaveNormalSample(int x, int y, int n = 256)
    {
        var layers = new (double Fx, double Fy, double A, double Ph)[] { (1, 2, 1.0, 0.0), (2, -1, 0.7, 1.7), (3, 2, 0.4, 3.1), (-2, 3, 0.3, 5.0) };
        double H(double u, double v)
        {
            double s = 0;
            foreach (var (fx, fy, a, ph) in layers) s += a * Math.Sin(2 * Math.PI * (fx * u + fy * v) + ph);
            return s;
        }
        double d = 1.0 / n;
        double uu = (double)x / n, vv = (double)y / n;
        double dx = (H(uu + d, vv) - H(uu - d, vv)) / (2 * d);
        double dy = (H(uu, vv + d) - H(uu, vv - d)) / (2 * d);
        double nx = -dx * 0.02, ny = -dy * 0.02, nz = 1;
        double len = Math.Sqrt(nx * nx + ny * ny + nz * nz);
        nx /= len; ny /= len;
        // JS Math.round (a tie goes up), not .NET's round-half-to-even.
        return new[]
        {
            (byte)Js.Round((nx * 0.5 + 0.5) * 255), (byte)Js.Round((ny * 0.5 + 0.5) * 255),
            (byte)Js.Round((nz / len * 0.5 + 0.5) * 255), (byte)255,
        };
    }

    /// <summary><c>makeWaveNormal</c>'s pixels: the n² RGBA8 texels of <see cref="WaveNormalSample"/>, row-major.</summary>
    public static byte[] WaveNormalBytes(int n = 256)
    {
        var data = new byte[n * n * 4];
        for (int y = 0; y < n; y++)
        for (int x = 0; x < n; x++)
            Array.Copy(WaveNormalSample(x, y, n), 0, data, (y * n + x) * 4, 4);
        return data;
    }
}
