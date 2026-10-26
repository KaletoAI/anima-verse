using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using AnimaNative.World;

namespace AnimaNative.Scatter;

/// <summary>One authored row of <c>terrain_areas.meta.scatter[]</c>, as the server enriches it (§ A9).</summary>
public sealed record ScatterEntry(
    double DensityPer100m2, string? Model, double? MinSpacingM, string? YawMode, double? YawDeg, string? Place,
    double? Variant, double? ReshuffleMin, double? PropHeightM, double? SwayFactor, double? GroundOffsetM,
    Dictionary<string, string> Variants, List<Dictionary<string, string>>? ModelVariants);

/// <summary>A type of the catalog; <c>Surface</c> = <c>surfaceOfType</c> (the library id it wears, trimmed + lower-cased, '' = none).</summary>
public sealed record TerrainTypeInfo(string Kind, string Color, double Undergrowth, double SwayM, string Surface = "")
{
    /// <summary><c>swayFor</c>'s clamp of a type's <c>sway_m</c> (client3d ground.ts <c>SWAY_MIN_M</c>/<c>SWAY_MAX_M</c>); the scatter shaders read the same bounds.</summary>
    public const double SwayMinM = 0.01, SwayMaxM = 0.5;
}

/// <summary>A painted area: id, kind, the RAW polygon (junk corners as NaN — <c>cleanRing</c> drops them),
/// its scatter rows, and how many rows of the kinds the spike does not port (along/edge/center).</summary>
public sealed record TerrainAreaInfo(string Id, string Kind, List<P2> Polygon, List<ScatterEntry> Scatter, int OtherRows)
{
    /// <summary><c>meta.water_profile</c> is there — the bake carved a bed (<c>waterProfileOf</c>, W1).</summary>
    public bool WaterProfile { get; init; }
    /// <summary><c>meta.water_depth_effective</c> (null = the bake default).</summary>
    public double? WaterDepthEffective { get; init; }
}

public sealed record PropBox(double X, double Z, double YawDeg, double HalfW, double HalfD);

/// <summary><c>GET /play/terrain</c> (client3d <c>TerrainPayload</c>): types, areas bottom to top, prop boxes.</summary>
public sealed class TerrainPayload
{
    public string DefaultKind { get; private set; } = "";
    public Dictionary<string, TerrainTypeInfo> Types { get; } = new();
    public List<TerrainAreaInfo> Areas { get; } = new();
    public List<PropBox> PropBoxes { get; } = new();
    public string Sig { get; private set; } = "";

    /// <summary>The server's grey for a kind without a colour (<c>TERRAIN_FALLBACK_COLOR</c>).</summary>
    public const string FallbackColor = "#888888";

    public static double? NumOrNull(JsonElement e, string name)
        => e.ValueKind == JsonValueKind.Object && e.TryGetProperty(name, out var v) && v.ValueKind == JsonValueKind.Number
            ? v.GetDouble() : null;

    private static string? StrOrNull(JsonElement e, string name)
        => e.ValueKind == JsonValueKind.Object && e.TryGetProperty(name, out var v) && v.ValueKind == JsonValueKind.String
            ? v.GetString() : null;

    private static Dictionary<string, string> Map(JsonElement e)
    {
        var d = new Dictionary<string, string>();
        if (e.ValueKind != JsonValueKind.Object) return d;
        foreach (var p in e.EnumerateObject())
            if (p.Value.ValueKind == JsonValueKind.String) d[p.Name] = p.Value.GetString() ?? "";
        return d;
    }

    public static List<P2> Points(JsonElement poly)
    {
        var list = new List<P2>();
        if (poly.ValueKind != JsonValueKind.Array) return list;
        foreach (var p in poly.EnumerateArray())
        {
            if (p.ValueKind != JsonValueKind.Array || p.GetArrayLength() < 2) continue;
            double x = p[0].ValueKind == JsonValueKind.Number ? p[0].GetDouble() : double.NaN;
            double z = p[1].ValueKind == JsonValueKind.Number ? p[1].GetDouble() : double.NaN;
            list.Add(new P2(x, z));
        }
        return list;
    }

    public static ScatterEntry ParseEntry(JsonElement e)
    {
        List<Dictionary<string, string>>? mv = null;
        if (e.TryGetProperty("model_variants", out var mvs) && mvs.ValueKind == JsonValueKind.Array)
        {
            mv = mvs.EnumerateArray().Where(m => m.ValueKind == JsonValueKind.Object).Select(Map).ToList();
            if (mv.Count == 0) mv = null;
        }
        return new ScatterEntry(
            NumOrNull(e, "density_per_100m2") ?? 0, StrOrNull(e, "model"), NumOrNull(e, "min_spacing_m"),
            StrOrNull(e, "yaw_mode"), NumOrNull(e, "yaw_deg"), StrOrNull(e, "place"), NumOrNull(e, "variant"),
            NumOrNull(e, "reshuffle_min"), NumOrNull(e, "prop_height_m"), NumOrNull(e, "sway_factor"),
            NumOrNull(e, "ground_offset_m"),
            e.TryGetProperty("variants", out var v) ? Map(v) : new Dictionary<string, string>(), mv);
    }

    public static TerrainPayload Parse(JsonElement root)
    {
        var t = new TerrainPayload { DefaultKind = Json.Str(root, "default_kind"), Sig = Json.Str(root, "sig") };
        foreach (var ty in Json.Arr(root, "types"))
        {
            var kind = Json.Str(ty, "kind");
            if (kind.Length == 0) continue;
            ty.TryGetProperty("meta", out var meta);
            double ug = NumOrNull(meta, "undergrowth") ?? double.NaN;
            double sway = NumOrNull(meta, "sway_m") ?? double.NaN;
            t.Types[kind.ToLowerInvariant()] = new TerrainTypeInfo(kind, Json.Str(ty, "color"),
                !double.IsFinite(ug) || ug <= 0 ? 0 : Math.Min(ug, 1),                                  // undergrowthFor
                !double.IsFinite(sway) || sway <= 0 ? 0 : Math.Min(Math.Max(sway, TerrainTypeInfo.SwayMinM), TerrainTypeInfo.SwayMaxM), // swayFor
                (ty.TryGetProperty("surface", out var sf) && sf.ValueKind == JsonValueKind.String ? sf.GetString() ?? "" : "")
                    .Trim().ToLowerInvariant());                                                         // surfaceOfType
        }
        foreach (var a in Json.Arr(root, "areas"))
        {
            if (a.ValueKind != JsonValueKind.Object) continue;
            var rows = new List<ScatterEntry>();
            int other = 0;
            if (a.TryGetProperty("meta", out var meta) && meta.ValueKind == JsonValueKind.Object)
            {
                if (meta.TryGetProperty("scatter", out var sc) && sc.ValueKind == JsonValueKind.Array)
                    foreach (var e in sc.EnumerateArray())
                        if (e.ValueKind == JsonValueKind.Object) rows.Add(ParseEntry(e));
                if (meta.TryGetProperty("stroke", out var st) && st.ValueKind == JsonValueKind.Object
                    && st.TryGetProperty("along", out var al) && al.ValueKind == JsonValueKind.Array)
                    other += al.EnumerateArray().Count(e => e.ValueKind == JsonValueKind.Object);
            }
            other += rows.Count(r => r.Place is "edge" or "center");
            bool hasMeta = a.TryGetProperty("meta", out var am) && am.ValueKind == JsonValueKind.Object;
            t.Areas.Add(new TerrainAreaInfo(Json.Str(a, "id"), Json.Str(a, "kind"),
                a.TryGetProperty("polygon", out var poly) ? Points(poly) : new List<P2>(), rows, other)
            {
                WaterProfile = hasMeta && am.TryGetProperty("water_profile", out var wp) && wp.ValueKind == JsonValueKind.Object,
                // The browser hands the raw value to waterOpaqueDepthM, which reads it with Number(): a numeric
                // string is a depth, junk is NaN (→ the default); absent stays null (undefined).
                WaterDepthEffective = hasMeta && am.TryGetProperty("water_depth_effective", out var wd)
                    ? Scene.Js.Number(wd) : null,
            });
        }
        foreach (var b in Json.Arr(root, "prop_boxes"))
            t.PropBoxes.Add(new PropBox(NumOrNull(b, "x") ?? double.NaN, NumOrNull(b, "z") ?? double.NaN,
                                        NumOrNull(b, "yaw_deg") ?? double.NaN, NumOrNull(b, "half_w") ?? double.NaN,
                                        NumOrNull(b, "half_d") ?? double.NaN));
        return t;
    }

    public TerrainTypeInfo? TypeOf(string kind) => Types.TryGetValue((kind ?? "").ToLowerInvariant(), out var t) ? t : null;

    public string KindColor(string kind) => TypeOf(kind)?.Color is { Length: > 0 } c ? c : FallbackColor;

    /// <summary>Every usable prop box as a footprint (<c>propBoxFootprints</c>).</summary>
    public List<P2[]> PropFootprints()
    {
        var list = new List<P2[]>();
        foreach (var b in PropBoxes)
            if (ScatterMath.PropBoxFootprint(b.X, b.Z, b.YawDeg, b.HalfW, b.HalfD) is { } fp) list.Add(fp);
        return list;
    }

    /// <summary>
    /// The placed locations' drawn outlines in world metres (<c>worldFootprints</c> in ground.ts): the
    /// worldmap row's <c>boundary</c> (else <c>map3d.boundary</c>) through § A1.1; a row without a usable
    /// boundary or position is dropped.
    /// </summary>
    public static List<P2[]> LocationFootprints(JsonElement worldmap)
    {
        var list = new List<P2[]>();
        foreach (var loc in Json.Arr(worldmap, "locations"))
        {
            if (loc.ValueKind != JsonValueKind.Object) continue;
            JsonElement b = default;
            bool has = loc.TryGetProperty("boundary", out b) && b.ValueKind == JsonValueKind.Array;
            if (!has && loc.TryGetProperty("map3d", out var m3) && m3.ValueKind == JsonValueKind.Object)
                has = m3.TryGetProperty("boundary", out b) && b.ValueKind == JsonValueKind.Array;
            if (!has) continue;
            var local = Sanitize(b);
            if (local is null) continue;
            double? cx = NumOrNull(loc, "pos_x"), cz = NumOrNull(loc, "pos_z");
            if (cx is not double x0 || !double.IsFinite(x0) || cz is not double z0 || !double.IsFinite(z0)) continue;
            double yawDeg = NumOrNull(loc, "yaw_deg") is double y && double.IsFinite(y) ? y : 0;
            double yaw = yawDeg * Math.PI / 180;
            double c = Math.Cos(yaw), s = Math.Sin(yaw);
            list.Add(local.Select(p => new P2(x0 + p.X * c + p.Z * s, z0 - p.X * s + p.Z * c)).ToArray());
        }
        return list;
    }

    /// <summary><c>sanitizePolygon</c>: all-or-nothing finite pairs, closing duplicate dropped, ≥ 3.</summary>
    private static List<P2>? Sanitize(JsonElement b)
    {
        var pts = new List<P2>();
        foreach (var p in b.EnumerateArray())
        {
            if (p.ValueKind != JsonValueKind.Array || p.GetArrayLength() < 2) return null;
            if (p[0].ValueKind != JsonValueKind.Number || p[1].ValueKind != JsonValueKind.Number) return null;
            pts.Add(new P2(p[0].GetDouble(), p[1].GetDouble()));
        }
        if (pts.Count >= 2 && pts[0] == pts[^1]) pts.RemoveAt(pts.Count - 1);
        return pts.Count >= 3 ? pts : null;
    }

    /// <summary><c>pickVariant</c>: the wanted tier, else full/low, else any; '' = no mesh.</summary>
    public static string PickVariant(Dictionary<string, string>? variants, string tier)
    {
        if (variants is null) return "";
        foreach (var t in new[] { tier, "full", "low" }.Concat(variants.Keys))
            if (variants.TryGetValue(t, out var url) && !string.IsNullOrEmpty(url)) return url;
        return "";
    }
}
