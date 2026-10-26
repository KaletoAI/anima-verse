using System;
using System.Collections.Generic;
using System.Text.Json;
using AnimaNative.Scatter;
using AnimaNative.World;

namespace AnimaNative.Scene;

/// <summary>The eased room ambience: daylight factor and an sRGB tint (kept sRGB while easing, like the browser).</summary>
public readonly record struct AmbienceState(double Daylight, double R, double G, double B)
{
    public static readonly AmbienceState Neutral = new(1, 1, 1, 1);
}

/// <summary>A room's rectangle in the tile frame (<c>tile.roomRects</c>): centre and size.</summary>
public readonly record struct RoomRect(double X, double Z, double W, double D);

/// <summary>
/// Room ambience and the night clock, a port of client3d/src/scene/ambience.ts (<c>ambienceTarget</c>,
/// <c>stepAmbience</c>, <c>nightFactorAt</c>) and client3d/src/game/roomAt.ts (<c>roomRectOf</c>, <c>roomAtRects</c>,
/// <c>corridorAtOutline</c>), checked against shared/test-vectors/ambience.json (hand derivations in
/// client3d/scripts/smoke_ambience.mjs).
/// </summary>
public static class Ambience
{
    /// <summary>The easing time constant τ in seconds.</summary>
    public const double TauS = 0.5;

    /// <summary><c>ambienceTarget</c>: daylight ?? 1; a "#rrggbb" tint → its bytes / 255 (sRGB), none → white.</summary>
    public static AmbienceState Target(SceneAmbience? a)
    {
        double daylight = a is null ? 1 : a.Daylight;
        var hex = a?.Tint ?? "";
        if (hex.Length == 0) return new AmbienceState(daylight, 1, 1, 1);
        // JS hex.slice(i, i + 2): a short string keeps what is there, past the end it is empty (parseInt → NaN).
        double Byte(int i) => Js.ParseIntHex(i < hex.Length ? hex.Substring(i, Math.Min(2, hex.Length - i)) : "") / 255;
        return new AmbienceState(daylight, Byte(1), Byte(3), Byte(5));
    }

    /// <summary><c>stepAmbience</c>: k = 1 − exp(−dt/τ), every channel cur + (target − cur)·k.</summary>
    public static AmbienceState Step(AmbienceState cur, AmbienceState target, double dt)
    {
        double k = 1 - Math.Exp(-dt / TauS);
        return new AmbienceState(cur.Daylight + (target.Daylight - cur.Daylight) * k,
                                 cur.R + (target.R - cur.R) * k,
                                 cur.G + (target.G - cur.G) * k,
                                 cur.B + (target.B - cur.B) * k);
    }

    /// <summary><c>nightFactorAt</c>: 0 = bright day, 1 = deep night, from the sun arc of <c>Engine.setGameHour</c>.</summary>
    public static double NightFactorAt(double hour)
    {
        double h = ((hour % 24) + 24) % 24;
        double day = Math.Min(Math.Max(Math.Sin((h - 6) / 12 * Math.PI), 0), 1);
        return Math.Min(Math.Max(1 - day * 3, 0), 1);
    }

    /// <summary>
    /// main.ts <c>takeGameHour</c>: <c>map.game_time.hour_fraction</c> when it is a number (the engine takes it as the
    /// time of day); null otherwise (the clock stays where it was).
    /// </summary>
    public static double? GameHourOf(JsonElement map)
        => map.ValueKind == JsonValueKind.Object && map.TryGetProperty("game_time", out var gt) && gt.ValueKind == JsonValueKind.Object
           && gt.TryGetProperty("hour_fraction", out var h) && h.ValueKind == JsonValueKind.Number ? h.GetDouble() : null;

    /// <summary><c>roomRectOf</c>: the hull's bounding box, each side at least 0.5 m; null without a finite point.</summary>
    public static RoomRect? RoomRectOf(IReadOnlyList<P2> hull)
    {
        double minX = double.PositiveInfinity, maxX = double.NegativeInfinity, minZ = double.PositiveInfinity, maxZ = double.NegativeInfinity;
        foreach (var p in hull)
        {
            if (p.X < minX) minX = p.X;
            if (p.X > maxX) maxX = p.X;
            if (p.Z < minZ) minZ = p.Z;
            if (p.Z > maxZ) maxZ = p.Z;
        }
        if (!double.IsFinite(minX)) return null;
        return new RoomRect((minX + maxX) / 2, (minZ + maxZ) / 2, Math.Max(maxX - minX, 0.5), Math.Max(maxZ - minZ, 0.5));
    }

    /// <summary><c>roomAtRects</c>: the smallest rectangle covering the tile-local point (edges inside), the first of equals.</summary>
    public static string? RoomAtRects(IEnumerable<KeyValuePair<string, RoomRect>> rects, double x, double z)
    {
        string? best = null;
        double bestArea = double.PositiveInfinity;
        foreach (var (id, r) in rects)
        {
            if (Math.Abs(x - r.X) > r.W / 2 || Math.Abs(z - r.Z) > r.D / 2) continue;
            double area = r.W * r.D;
            if (area < bestArea) { best = id; bestArea = area; }
        }
        return best;
    }

    /// <summary><c>corridorAtOutline</c>: the lowest corridor at level ≥ 0 (first of equals), outline ≥ 3, half-open ray cast.</summary>
    public static string? CorridorAtOutline(IEnumerable<SceneCorridor> corridors, double x, double z)
    {
        SceneCorridor? lowest = null;
        foreach (var c in corridors)
            if (c.Level >= 0 && (lowest is null || c.Level < lowest.Level)) lowest = c;
        if (lowest is null || lowest.Outline.Length < 3) return null;
        return SceneView.PointInPolygon(x, z, lowest.Outline) ? lowest.RoomId : null;
    }
}
