using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;

namespace AnimaNative.Scatter;

/// <summary>Task 39 (E4-T4): stroke.ts decoration and along stations. Decoration rounds to centimetres
/// with JS rounding; station rejection preserves candidate ordinals and draws before verdicts.</summary>
public static class StrokeMath
{
    private const double Eps = 1e-9;
    public sealed record Recipe(IReadOnlyList<P2> Points, string? Style = null, double? SpacingM = null, double? AmplitudeM = null);
    public sealed record Decoration(IReadOnlyList<P2> Points, double SpacingM, bool Capped);
    public static string AlongSeed(string areaId, int index, double? epoch = null)
        => $"terrain:along:{areaId}:{index}{ScatterMath.SeedEpochSuffix(epoch)}";
    private static double Ease(double t) => (1 - Math.Cos(Math.PI * t)) / 2;
    private static double Len(P2 a, P2 b) => Math.Sqrt(Math.Pow(b.X - a.X, 2) + Math.Pow(b.Z - a.Z, 2));
    private static string Num(double d) => d == 0 ? "0" : d.ToString("R", CultureInfo.InvariantCulture);
    public static string StrokeSeed(IReadOnlyList<P2> points) => "terrain:stroke" + string.Concat(points.Select(p => $":{Num(p.X)},{Num(p.Z)}"));
    private static List<P2>? Clean(IReadOnlyList<P2> points)
    {
        var line = new List<P2>();
        foreach (var p in points)
        {
            if (!double.IsFinite(p.X) || !double.IsFinite(p.Z)) return null;
            if (line.Count == 0 || !ScatterRows.Near(line[^1], p)) line.Add(p);
        }
        return line;
    }
    private static List<double> Cumulative(IReadOnlyList<P2> line)
    {
        var cum = new List<double> { 0 };
        for (int i = 1; i < line.Count; i++) cum.Add(cum[^1] + Len(line[i - 1], line[i]));
        return cum;
    }
    public static IReadOnlyList<P2> CentreLine(Recipe recipe)
    {
        double Positive(double? n, double fallback) => n is double v && double.IsFinite(v) && v > 0 ? v : fallback;
        return Decorate(recipe.Points, recipe.Style, Positive(recipe.SpacingM, 10), Positive(recipe.AmplitudeM, 2)).Points;
    }
    public static Decoration Decorate(IReadOnlyList<P2> points, string? style, double spacingM, double amplitudeM, string? seed = null)
    {
        var plain = new Decoration(points, spacingM, false);
        if (style is not ("jagged" or "wavy") || !double.IsFinite(spacingM) || spacingM <= 0 || !double.IsFinite(amplitudeM) || amplitudeM <= 0) return plain;
        var line = Clean(points); if (line is null || line.Count < 2) return plain;
        var cum = Cumulative(line); double total = cum[^1]; if (!(total > 0)) return plain;
        var normals = new List<P2>();
        for (int i = 1; i < line.Count; i++) { double len = cum[i] - cum[i - 1]; normals.Add(new((line[i].Z - line[i - 1].Z) / len, -(line[i].X - line[i - 1].X) / len)); }
        int room = 1024 - line.Count; if (room <= 0) return new(line, spacingM, true);
        double spacing = spacingM, step = 0; bool capped = false;
        if (style == "wavy")
        {
            step = Math.Min(spacing / 3, 3);
            if (step < total / room) { step = total / room; spacing = Math.Max(spacing, step * 3); capped = true; }
        }
        else if (spacing < total / room) { spacing = total / room; capped = true; }
        var rnd = ScatterMath.SeededRandom(seed ?? StrokeSeed(points)); double phase = rnd() * Math.PI * 2;
        var anchorD = new List<double>(); var anchorH = new List<double>();
        for (double d = spacing / 2; d < total - Eps; d += spacing) { anchorD.Add(d); anchorH.Add(amplitudeM * (0.4 + 0.6 * rnd())); }
        P2 NormalAt(double d, int seg)
        {
            foreach (int c in new[] { seg - 1, seg })
            {
                if (c < 1 || c > line.Count - 2) continue;
                double dd = d - cum[c], half = Math.Min(spacing * 0.5, Math.Min((cum[c] - cum[c - 1]) / 2, (cum[c + 1] - cum[c]) / 2));
                if (!(half > Eps) || Math.Abs(dd) >= half) continue;
                double b = Ease((dd + half) / (2 * half));
                double mx = (1 - b) * normals[c - 1].X + b * normals[c].X, mz = (1 - b) * normals[c - 1].Z + b * normals[c].Z;
                double ml = Math.Sqrt(mx * mx + mz * mz); if (ml > Eps) return new(mx / ml, mz / ml);
            }
            return normals[seg - 1];
        }
        var envD = new List<double> { 0 }; envD.AddRange(anchorD); envD.Add(total);
        var envH = new List<double> { 0 }; envH.AddRange(anchorH); envH.Add(0); int envI = 0;
        double Envelope(double d)
        {
            while (envI + 2 < envD.Count && envD[envI + 1] < d) envI++;
            double span = envD[envI + 1] - envD[envI]; if (!(span > 0)) return envH[envI + 1];
            return envH[envI] + (envH[envI + 1] - envH[envI]) * Ease(Math.Clamp((d - envD[envI]) / span, 0, 1));
        }
        var ds = new List<double>(); var tag = new List<int>();
        if (style == "jagged")
        {
            int walk = 1;
            for (int i = 0; i < anchorD.Count; i++)
            {
                while (walk < line.Count - 1 && cum[walk] <= anchorD[i]) { ds.Add(cum[walk++]); tag.Add(-1); }
                ds.Add(anchorD[i]); tag.Add(i);
            }
            while (walk < line.Count - 1) { ds.Add(cum[walk++]); tag.Add(-1); }
        }
        else
        {
            int walk = 1;
            void Push(double d) { if (ds.Count > 0 && d - ds[^1] <= Eps) return; ds.Add(d); tag.Add(0); }
            for (int k = 0; k * step < total - Eps; k++)
            {
                double d = k * step;
                while (walk <= line.Count - 2 && cum[walk] < d - Eps) Push(cum[walk++]); Push(d);
            }
            while (walk <= line.Count - 2) Push(cum[walk++]);
        }
        var output = new List<P2> { line[0] }; int segment = 1;
        for (int k = 0; k < ds.Count; k++)
        {
            double d = ds[k];
            while (segment < line.Count - 1 && (style == "jagged" ? cum[segment] <= d : cum[segment] < d - Eps)) segment++;
            if (tag[k] == -1) { output.Add(line[segment - 1]); continue; }
            if (d <= Eps) continue;
            var a = line[segment - 1]; var b = line[segment]; double f = (d - cum[segment - 1]) / (cum[segment] - cum[segment - 1]);
            var n = NormalAt(d, segment);
            double off = style == "jagged" ? anchorH[tag[k]] * (tag[k] % 2 == 0 ? 1 : -1) : Envelope(d) * Math.Sin(phase + (2 * Math.PI * d) / (4 * spacing));
            output.Add(new(Js.Round((a.X + f * (b.X - a.X) + off * n.X) * 100) / 100 + 0,
                Js.Round((a.Z + f * (b.Z - a.Z) + off * n.Z) * 100) / 100 + 0));
        }
        output.Add(line[^1]); return new(output, spacing, capped);
    }
    public static List<ScatterInstance> Stations(ScatterRows.Options o)
    {
        var output = new List<ScatterInstance>(); double spacing = o.SpacingM, offset = o.OffsetM ?? double.NaN;
        if (!double.IsFinite(spacing) || spacing <= 0 || !double.IsFinite(offset) || offset < 0) return output;
        var line = Clean(o.Line); if (line is null || line.Count < 2) return output;
        var cum = Cumulative(line); double total = cum[^1]; if (!(total > 0)) return output;
        var sides = o.Side == "left" ? new[] { -1 } : o.Side == "both" ? new[] { 1, -1 } : new[] { 1 };
        var rnd = o.YawMode == "random" ? ScatterMath.SeededRandom(o.Seed) : null;
        double yawRel = o.YawDeg is double deg && double.IsFinite(deg) ? deg * Math.PI / 180 : 0;
        double start = ScatterRows.Start(o), jitter = o.JitterM ?? double.NaN;
        var jitterRnd = jitter > 0 ? o.JitterRng ?? ScatterMath.SeededRandom(o.Seed + ":jitter") : null;
        int seg = 1, ordinal = 0; double s = 0;
        for (int k = 0; ; k++)
        {
            s = jitterRnd is null ? start + k * spacing : Math.Max(0, (k == 0 ? start : s + spacing) + (2 * jitterRnd() - 1) * jitter);
            if (s > total + Eps || output.Count >= (o.MaxPoints ?? ScatterMath.MaxPerEntry)) break;
            while (seg < line.Count - 1 && cum[seg] < s - Eps) seg++;
            var a = line[seg - 1]; var b = line[seg]; double len = cum[seg] - cum[seg - 1];
            double t = len > 0 ? Math.Clamp((s - cum[seg - 1]) / len, 0, 1) : 0, dx = (b.X - a.X) / len, dz = (b.Z - a.Z) / len;
            double px = a.X + t * (b.X - a.X), pz = a.Z + t * (b.Z - a.Z), heading = Math.Atan2(dx, dz);
            foreach (int sign in o.Side == "alternate" ? new[] { k % 2 == 0 ? 1 : -1 } : sides)
            {
                int index = ordinal++; double x = px + (sign > 0 ? -dz : dz) * offset, z = pz + (sign > 0 ? dx : -dx) * offset;
                double yaw = ScatterRows.Norm(rnd is not null ? rnd() * Math.PI * 2 : heading + (sign > 0 ? 0 : Math.PI) + yawRel);
                if (!ScatterRows.Rejected(o, x, z)) output.Add(ScatterRows.Accepted(o, x, z, yaw, index, along: true));
            }
        }
        return output;
    }
}
