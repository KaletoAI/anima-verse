using System;
using System.Collections.Generic;
using System.Text.Json;
using AnimaNative.Scatter;
using AnimaNative.World;

namespace AnimaNative.Embody;

/// <summary>Outside door on level 0 in world metres, as delivered on a worldmap location row.</summary>
public sealed record EntryDoor(double X, double Z, double OutX, double OutZ, double WidthM, string Room, int Level);

/// <summary>Entry tolerances from the worldmap root; absent keys parse as 0 (never hard-coded).</summary>
public sealed record EntryTolerance(double AlongPadM, double AcrossM, double GateM)
{
    public static EntryTolerance Parse(JsonElement worldmapRoot)
    {
        double alongPad = 0, across = 0;
        if (worldmapRoot.ValueKind == JsonValueKind.Object
            && worldmapRoot.TryGetProperty("door_tolerance", out var dt)
            && dt.ValueKind == JsonValueKind.Object)
        {
            alongPad = Json.Num(dt, "along_pad_m", 0);
            across = Json.Num(dt, "across_m", 0);
        }
        double gate = Json.Num(worldmapRoot, "gate_tolerance_m", 0);
        return new EntryTolerance(alongPad, across, gate);
    }
}

/// <summary>Parsed worldmap entry snapshot (locations, tolerances and slope limits); built once per map generation.</summary>
public sealed class EntryWorld
{
    public const double DefaultMaxStepM = 0.4, DefaultMaxSlopeDeg = 40;
    public static readonly EntryWorld Empty = new(
        new Dictionary<string, LocationInfo>(StringComparer.Ordinal),
        new EntryTolerance(0, 0, 0), DefaultMaxStepM, DefaultMaxSlopeDeg);

    public IReadOnlyDictionary<string, LocationInfo> Locations { get; }
    public EntryTolerance Tolerance { get; }
    public double MaxStepM { get; }
    public double MaxSlopeDeg { get; }

    private EntryWorld(IReadOnlyDictionary<string, LocationInfo> locations, EntryTolerance tolerance,
                       double maxStepM, double maxSlopeDeg)
    {
        Locations = locations; Tolerance = tolerance; MaxStepM = maxStepM; MaxSlopeDeg = maxSlopeDeg;
    }

    public static EntryWorld Parse(JsonElement worldmapRoot)
    {
        var byId = new Dictionary<string, LocationInfo>(StringComparer.Ordinal);
        foreach (var loc in LocationInfo.ParseList(worldmapRoot)) byId[loc.Id] = loc;
        var tol = EntryTolerance.Parse(worldmapRoot);
        double maxStep = Json.NumOrNull(worldmapRoot, "max_step_height_m") ?? DefaultMaxStepM;
        double maxSlope = Json.NumOrNull(worldmapRoot, "max_slope_deg") ?? DefaultMaxSlopeDeg;
        return new EntryWorld(byId, tol, maxStep, maxSlope);
    }

    public IReadOnlyList<EntryOpening> Gates(string id)
        => Locations.TryGetValue(id, out var loc) ? loc.Gates : Array.Empty<EntryOpening>();

    public IReadOnlyList<EntryDoor> Doors(string id)
        => Locations.TryGetValue(id, out var loc) ? loc.Doors : Array.Empty<EntryDoor>();

    public bool Fenced(string id)
        => Locations.TryGetValue(id, out var loc) && loc.Fenced;
}

/// <summary>Pure entry proximity rules matching the server contract.</summary>
public static class EntryRules
{
    /// <summary>True when (x, z) lies within the door's along and across tolerances.</summary>
    public static bool AtDoor(EntryDoor door, double x, double z, EntryTolerance t)
    {
        double dx = x - door.X, dz = z - door.Z;
        double across = dx * door.OutX + dz * door.OutZ;
        double along = dx * door.OutZ - dz * door.OutX;
        return Math.Abs(along) <= door.WidthM * 0.5 + t.AlongPadM && Math.Abs(across) <= t.AcrossM;
    }

    /// <summary>True when (x, z) lies within gate tolerance of the gate's world point.</summary>
    public static bool AtGate(P2 gate, double x, double z, EntryTolerance t)
        => double.Hypot(x - gate.X, z - gate.Z) <= t.GateM;
}
