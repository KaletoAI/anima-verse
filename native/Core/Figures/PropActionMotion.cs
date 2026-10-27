using System;
using System.Collections.Generic;
using System.Text.Json;
using AnimaNative.Scatter;
using AnimaNative.World;

namespace AnimaNative.Figures;

/// <summary>Authoritative remaining polyline; timing is supplied by Core, not inferred from poll positions.</summary>
public sealed record PublicMotionRoute(string JourneyId, string RoomId, P2[] Points, double?[] Paces,
                                       double ProgressM, double StartsInS)
{
    public static PublicMotionRoute? Parse(JsonElement value, string journeyId = "", string roomId = "")
    {
        if (value.ValueKind != JsonValueKind.Object || !value.TryGetProperty("waypoints", out var wp)
            || wp.ValueKind != JsonValueKind.Array || wp.GetArrayLength() < 2) return null;
        var points = new P2[wp.GetArrayLength()];
        int i = 0;
        foreach (var p in wp.EnumerateArray())
        {
            double x = p.ValueKind == JsonValueKind.Array ? p[0].GetDouble() : Json.Num(p, "x");
            double z = p.ValueKind == JsonValueKind.Array ? p[1].GetDouble() : Json.Num(p, "z");
            if (!double.IsFinite(x) || !double.IsFinite(z)) return null;
            points[i++] = new P2(x, z);
        }
        var paces = new double?[points.Length - 1];
        if (value.TryGetProperty("paces_m_s_real", out var ps) && ps.ValueKind == JsonValueKind.Array)
        {
            i = 0;
            foreach (var pace in ps.EnumerateArray())
            {
                if (i >= paces.Length) break;
                paces[i++] = pace.ValueKind == JsonValueKind.Number && pace.GetDouble() > 0 ? pace.GetDouble() : null;
            }
        }
        return new PublicMotionRoute(Json.Str(value, "journey_id", journeyId), Json.Str(value, "room_id", roomId), points, paces,
            Json.Num(value, "progress_m"), Json.Num(value, "starts_in_s"));
    }

    public P2 At(double ageS)
    {
        double distance = Math.Max(0, ProgressM), seconds = Math.Max(0, ageS - StartsInS);
        for (int i = 0; i < Points.Length - 1; i++)
        {
            var a = Points[i]; var b = Points[i + 1];
            double dx = b.X - a.X, dz = b.Z - a.Z, length = Math.Sqrt(dx * dx + dz * dz);
            if (length <= 1e-9) continue;
            if (distance >= length) { distance -= length; continue; }
            double pace = i < Paces.Length ? Paces[i] ?? 0 : 0;
            double left = length - distance;
            double step = Math.Min(left, seconds * pace);
            if (step < left || pace <= 0)
            {
                double f = (distance + step) / length;
                return new P2(a.X + dx * f, a.Z + dz * f);
            }
            seconds -= left / pace;
            distance = 0;
        }
        return Points[^1];
    }
}

/// <summary>Per-figure route lifetime. A cancelled owned journey is never revived by an older in-flight poll.</summary>
public sealed class PublicMotionState
{
    private PublicMotionRoute? _route;
    private double _received;
    private readonly HashSet<string> _cancelled = new(StringComparer.Ordinal);
    public string? JourneyId => _route?.JourneyId;
    public void Adopt(PublicMotionRoute? route, double received)
    {
        _route = route is not null && !_cancelled.Contains(route.JourneyId) ? route : null;
        _received = received;
    }
    public void CancelOwned()
    {
        if (_route is { JourneyId.Length: > 0 } route) _cancelled.Add(route.JourneyId);
        _route = null;
    }
    public bool TryAt(double now, out P2 point)
    {
        point = _route?.At(Math.Max(0, now - _received)) ?? default;
        return _route is not null;
    }
}

public readonly record struct EntryPoint(double X, double Y, double Z, double Yaw)
{
    internal static EntryPoint Parse(JsonElement value) => new(Json.Num(value, "x"), Json.Num(value, "y"),
        Json.Num(value, "z"), Json.Num(value, "yaw"));
}

/// <summary>Public geometry and actual game-clock progress only; no execution or consent identity.</summary>
public sealed record PublicPropEntry(string Kind, string PoseKey, EntryPoint Access, EntryPoint Anchor,
    double DurationGameS, double ElapsedGameS, double Rate, double HeightCm, string Role, double StartedGameS)
{
    public double RootOffset { get; init; }
    public static double? SupportPhase(double firstY, double lastY, double currentY)
        => Math.Abs(lastY - firstY) > 1e-6 ? Math.Clamp((currentY - firstY) / (lastY - firstY), 0, 1) : null;
    public static double? SupportLift(double firstY, double lastY, double currentY,
                                      double supportY, double rootOffset, double accessY)
    {
        double correction = supportY - rootOffset - accessY;
        if (Math.Abs(correction) < 1e-6) return 0;
        return SupportPhase(firstY, lastY, currentY) is { } phase ? correction * phase : null;
    }
    public static double Phase(double elapsed, double duration, double rate, double age)
        => duration > 0 ? Math.Clamp((elapsed + Math.Max(0, rate) * Math.Max(0, age)) / duration, 0, 1) : 1;
    public double PhaseAt(double age) => Phase(ElapsedGameS, DurationGameS, Rate, age);
    public bool SameClip(PublicPropEntry other) => Kind == other.Kind && StartedGameS == other.StartedGameS
        && Access == other.Access && Anchor == other.Anchor;
    public static PublicPropEntry? Parse(JsonElement c)
    {
        if (!c.TryGetProperty("prop_action_entry", out var e) || e.ValueKind != JsonValueKind.Object
            || !e.TryGetProperty("access", out var a) || !e.TryGetProperty("anchor", out var b)) return null;
        return new PublicPropEntry(Json.Str(e, "kind"), Json.Str(e, "pose_key"), EntryPoint.Parse(a), EntryPoint.Parse(b),
            Json.Num(e, "duration_game_s"), Json.Num(e, "elapsed_game_s"), Json.Num(e, "game_seconds_per_real_second"),
            Json.Num(e, "height_cm"), Json.Str(e, "role"), Json.Num(e, "started_game_s"))
            { RootOffset = Json.Num(e, "root_offset") };
    }
}
