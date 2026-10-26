using System;
using System.Collections.Generic;
using System.Text.Json;

namespace AnimaNative.Sky;

/// <summary>
/// The worldmap payload's <c>backdrop</c> block (types.ts <c>BackdropSpec</c>, server <c>app/core/backdrop.py</c>):
/// ridge height, seed and the arcs already resolved to compass degrees. Fields arrive as the server wrote them; junk
/// is passed on as "unusable" and <see cref="Backdrop.RidgeProfile"/> treats it like the browser does (height →
/// default, seed → 1, an arc with a non-finite end → skipped).
/// </summary>
public sealed record BackdropSpec(double? HeightM, double Seed, IReadOnlyList<(double Start, double End)> Arcs, string Key)
{
    /// <summary>
    /// main.ts <c>takeBackdrop</c>: <c>map.backdrop ?? null</c> — a missing block, <c>null</c> or a non-object is the ring
    /// being off (also what an older server sends). <see cref="Key"/> is backdrop.ts' rebuild key
    /// <c>JSON.stringify([height_m, seed, arcs])</c>, here over the raw JSON text of the three fields (the same server
    /// always prints the same value the same way).
    /// </summary>
    public static BackdropSpec? Of(JsonElement map)
    {
        if (map.ValueKind != JsonValueKind.Object || !map.TryGetProperty("backdrop", out var b) || b.ValueKind != JsonValueKind.Object)
            return null;
        string Raw(string name) => b.TryGetProperty(name, out var v) ? v.GetRawText() : "undefined";
        double? height = b.TryGetProperty("height_m", out var h) && h.ValueKind == JsonValueKind.Number ? h.GetDouble() : null;
        double seed = b.TryGetProperty("seed", out var s) && s.ValueKind == JsonValueKind.Number ? s.GetDouble() : double.NaN;
        var arcs = new List<(double, double)>();
        if (b.TryGetProperty("arcs", out var a) && a.ValueKind == JsonValueKind.Array)
            foreach (var arc in a.EnumerateArray())
            {
                // `arc?.[0]` / `arc?.[1]`: anything that is not a pair of numbers is a non-finite end → skipped.
                double At(int i) => arc.ValueKind == JsonValueKind.Array && arc.GetArrayLength() > i
                                    && arc[i].ValueKind == JsonValueKind.Number ? arc[i].GetDouble() : double.NaN;
                arcs.Add((At(0), At(1)));
            }
        return new BackdropSpec(height, seed, arcs, $"[{Raw("height_m")},{Raw("seed")},{Raw("arcs")}]");
    }
}

/// <summary>
/// backdrop.ts <c>ridgeGeometry</c>: one ring as a low-poly strip — per pair of neighbouring ridge points of the layer a
/// vertical quad from y = 0 up to the two peaks at the layer's radius, built through the vector-checked
/// <see cref="Backdrop.RidgeDirection"/> / <see cref="Backdrop.LayerRadiusM"/>. A pair whose peaks are BOTH ≤ 0 (the
/// join between two arcs) is skipped. Vertex order per quad: foot at a, peak at a, foot at b, peak at b. The faces
/// point at the ring's centre: three's order (b, b+1, b+3) / (b, b+3, b+2) is counter-clockwise from the centre; Godot's
/// front faces wind CLOCKWISE, so every triple is emitted reversed — (b, b+3, b+1) / (b, b+2, b+3).
/// </summary>
public static class BackdropMesh
{
    /// <summary>The strip of <paramref name="layer"/>: positions as x, y, z triples and Godot-wound indices; null when the
    /// layer has fewer than two points or nothing to draw (the browser's <c>null</c> geometry).</summary>
    public static (double[] Positions, int[] Indices)? Ring(IReadOnlyList<RidgePoint> profile, int layer)
    {
        var pts = new List<RidgePoint>();
        foreach (var p in profile)
            if (p.Layer == layer) pts.Add(p);
        if (pts.Count < 2) return null;
        double r = Backdrop.LayerRadiusM(layer);
        var pos = new List<double>();
        var idx = new List<int>();
        for (int i = 0; i + 1 < pts.Count; i++)
        {
            var p = pts[i];
            var q = pts[i + 1];
            if (p.PeakH <= 0 && q.PeakH <= 0) continue;
            var (pdx, pdz) = Backdrop.RidgeDirection(p.AngleDeg);
            var (qdx, qdz) = Backdrop.RidgeDirection(q.AngleDeg);
            int b = pos.Count / 3;
            pos.AddRange(new[] { pdx * r, 0, pdz * r, pdx * r, p.PeakH, pdz * r, qdx * r, 0, qdz * r, qdx * r, q.PeakH, qdz * r });
            idx.AddRange(new[] { b, b + 3, b + 1, b, b + 2, b + 3 });
        }
        if (idx.Count == 0) return null;
        return (pos.ToArray(), idx.ToArray());
    }
}

/// <summary>
/// backdrop.ts' tint: per ring a base rock colour mixed towards the CURRENT sky by
/// <c>min(0.92, 0.30 + 0.55·night + 0.18·layer)</c> (<c>applyTint</c>, three <c>Color.set(hex).lerp(sky, mix)</c> in
/// the linear working space), on an unlit material. The constants are backdrop.ts' (no shared vector carries them yet;
/// retyped with their source names).
/// </summary>
public static class BackdropLook
{
    /// <summary><c>LAYER_BASE_COLOR</c>: front, back.</summary>
    public static readonly int[] LayerBaseHex = { 0x5f6d84, 0x76859c };
    /// <summary><c>SKY_MIX_DAY</c>, <c>SKY_MIX_NIGHT</c>, <c>SKY_MIX_PER_LAYER</c> and the cap of <c>applyTint</c>.</summary>
    public const double SkyMixDay = 0.30, SkyMixNight = 0.55, SkyMixPerLayer = 0.18, SkyMixMax = 0.92;

    /// <summary><c>setDayNight</c>'s guard: a non-finite night is 0, the rest clamped to [0, 1].</summary>
    public static double ClampNight(double n) => double.IsFinite(n) ? Math.Min(1, Math.Max(0, n)) : 0;

    /// <summary>The sky share of a ring at a night factor.</summary>
    public static double SkyMix(int layer, double night)
        => Math.Min(SkyMixMax, SkyMixDay + SkyMixNight * ClampNight(night) + SkyMixPerLayer * layer);

    /// <summary>The ring's material colour (linear working space): <c>LAYER_BASE_COLOR[layer] ?? [0]</c> lerped to the sky.</summary>
    public static LinearRgb Colour(int layer, double night, LinearRgb sky)
    {
        int hex = layer >= 0 && layer < LayerBaseHex.Length ? LayerBaseHex[layer] : LayerBaseHex[0];
        return LinearRgb.FromSrgbHex(hex).Lerp(sky, SkyMix(layer, night));
    }
}
