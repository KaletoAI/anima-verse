using System;
using System.Collections.Generic;
using System.Text.Json;

namespace AnimaNative.Water;

/// <summary>One axis knot of a water profile: (x, z) in world metres, arc length s, the mirror's level there.</summary>
public readonly record struct WaterKnot(double X, double Z, double S, double Level);

/// <summary>
/// An area's exact water profile (<c>meta.water_profile</c>, <c>client3d/src/scene/waterPlaneMath.ts</c>
/// <c>WaterProfile</c>): the axis knots and the nine numbers the server resolved. The gameplay reads THIS (wading,
/// swimming, the submerged ghost), never the rastered render field.
/// </summary>
public sealed record WaterProfile(IReadOnlyList<WaterKnot> Axis, double LevelUp, double LevelDown, double? FlowDirDeg,
                                  double AxisX, double AxisZ, double DirX, double DirZ, double SMin, double SMax)
{
    /// <summary>The payload's <c>finite()</c>: absent / null / '' = none, else JS <c>Number()</c> when finite.</summary>
    internal static double? Finite(JsonElement? raw)
    {
        if (raw is not { } e || e.ValueKind is JsonValueKind.Null or JsonValueKind.Undefined) return null;
        if (e.ValueKind == JsonValueKind.String && e.GetString() == "") return null;
        double n = Scene.Js.Number(e);
        return double.IsFinite(n) ? n : null;
    }

    private static JsonElement? Field(JsonElement o, string name)
        => o.ValueKind == JsonValueKind.Object && o.TryGetProperty(name, out var v) ? v : null;

    /// <summary><c>axisOf</c>: at least one knot, each an array of ≥ 4 finite numbers; anything else = no axis.</summary>
    private static List<WaterKnot>? AxisOf(JsonElement? raw)
    {
        if (raw is not { ValueKind: JsonValueKind.Array } a || a.GetArrayLength() < 1) return null;
        var knots = new List<WaterKnot>();
        foreach (var k in a.EnumerateArray())
        {
            if (k.ValueKind != JsonValueKind.Array || k.GetArrayLength() < 4) return null;
            if (Finite(k[0]) is not { } x || Finite(k[1]) is not { } z || Finite(k[2]) is not { } s
                || Finite(k[3]) is not { } level) return null;
            knots.Add(new WaterKnot(x, z, s, level));
        }
        return knots;
    }

    /// <summary><c>waterProfileOf(meta)</c>: the profile when every required number is there, else null.</summary>
    public static WaterProfile? Of(JsonElement? meta)
    {
        if (meta is not { ValueKind: JsonValueKind.Object } m || Field(m, "water_profile") is not { ValueKind: JsonValueKind.Object } p)
            return null;
        var axis = AxisOf(Field(p, "axis"));
        if (axis is null || Finite(Field(p, "level_up")) is not { } up || Finite(Field(p, "level_down")) is not { } down
            || Finite(Field(p, "axis_x")) is not { } ax || Finite(Field(p, "axis_z")) is not { } az
            || Finite(Field(p, "dir_x")) is not { } dx || Finite(Field(p, "dir_z")) is not { } dz
            || Finite(Field(p, "s_min")) is not { } sMin || Finite(Field(p, "s_max")) is not { } sMax) return null;
        return new WaterProfile(axis, up, down, Finite(Field(p, "flow_dir_deg")), ax, az, dx, dz, sMin, sMax);
    }

    /// <summary><c>nearestOnAxis</c>: the arc length of the axis point nearest to (x, z).</summary>
    private static double NearestOnAxis(IReadOnlyList<WaterKnot> axis, double x, double z)
    {
        double bestS = axis[0].S;
        double bestD2 = (x - axis[0].X) * (x - axis[0].X) + (z - axis[0].Z) * (z - axis[0].Z);
        for (int i = 1; i < axis.Count; i++)
        {
            var (ax, az, aS, _) = axis[i - 1];
            var (bx, bz, bS, _) = axis[i];
            double dx = bx - ax, dz = bz - az;
            double seg = dx * dx + dz * dz;
            double u = seg <= 1e-18 ? 0 : ((x - ax) * dx + (z - az) * dz) / seg;
            u = u < 0 ? 0 : u > 1 ? 1 : u;
            double px = ax + dx * u, pz = az + dz * u;
            double d2 = (x - px) * (x - px) + (z - pz) * (z - pz);
            if (d2 < bestD2)
            {
                bestD2 = d2;
                bestS = aS + (bS - aS) * u;
            }
        }
        return bestS;
    }

    /// <summary><c>axisLevelAt</c>: the level at arc length s, linear between knots, held past the ends.</summary>
    private static double AxisLevelAt(IReadOnlyList<WaterKnot> axis, double s)
    {
        if (s <= axis[0].S) return axis[0].Level;
        var last = axis[^1];
        if (s >= last.S) return last.Level;
        for (int i = 1; i < axis.Count; i++)
        {
            var a = axis[i - 1];
            var b = axis[i];
            if (s <= b.S)
            {
                double span = b.S - a.S;
                if (span <= 1e-12) return b.Level;
                return a.Level + (b.Level - a.Level) * ((s - a.S) / span);
            }
        }
        return last.Level;
    }

    /// <summary><c>waterLevelAt(profile, x, z)</c>: the exact mirror height at a point — the level at its nearest axis point.</summary>
    public static double LevelAt(IReadOnlyList<WaterKnot> axis, double x, double z) => AxisLevelAt(axis, NearestOnAxis(axis, x, z));

    /// <inheritdoc cref="LevelAt(IReadOnlyList{WaterKnot}, double, double)"/>
    public double LevelAt(double x, double z) => LevelAt(Axis, x, z);
}
