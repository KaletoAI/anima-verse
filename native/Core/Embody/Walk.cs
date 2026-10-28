using System;
using System.Collections.Generic;
using System.Linq;
using AnimaNative.Scatter;

namespace AnimaNative.Embody;

/// <summary>Task 47 (E7-T2), walk.ts: renderer-free steering and terrain gates; walk_control.json.</summary>
public static class Walk
{
    public const double StepDistanceM = 1;

    /// <summary>Camera-relative unit direction; opposite keys cancel, diagonals retain unit speed.</summary>
    public static P2? WalkDir(IReadOnlySet<string> keys, double yaw)
    {
        double fx = -Math.Sin(yaw), fz = -Math.Cos(yaw), x = 0, z = 0;
        if (keys.Contains("w") || keys.Contains("arrowup")) { x += fx; z += fz; }
        if (keys.Contains("s") || keys.Contains("arrowdown")) { x -= fx; z -= fz; }
        if (keys.Contains("d") || keys.Contains("arrowright")) { x -= fz; z += fx; }
        if (keys.Contains("a") || keys.Contains("arrowleft")) { x += fz; z -= fx; }
        double len = double.Hypot(x, z);
        return len < 1e-6 ? null : new P2(x / len, z / len);
    }

    /// <summary>Try the full target, larger axis (X wins ties), smaller axis, then the origin.</summary>
    public static P2 SlideBlocked(P2 from, P2 to, Func<double, double, bool> blocked)
    {
        if (!blocked(to.X, to.Z)) return to;
        double dx = to.X - from.X, dz = to.Z - from.Z;
        var alongX = new P2(to.X, from.Z);
        var alongZ = new P2(from.X, to.Z);
        bool xFirst = Math.Abs(dx) >= Math.Abs(dz);
        var first = xFirst ? alongX : alongZ;
        var second = xFirst ? alongZ : alongX;
        if ((xFirst ? dx : dz) != 0 && !blocked(first.X, first.Z)) return first;
        if ((xFirst ? dz : dx) != 0 && !blocked(second.X, second.Z)) return second;
        return from;
    }

    /// <summary>A footprint's own floor overrides painted terrain passability.</summary>
    public static bool TerrainBlocks(bool passable, bool insideFootprint) => !insideFootprint && !passable;

    /// <summary>Only uphill movement is gated: strict step and slope limits, exactly as walk.ts.</summary>
    public static bool SlopeBlocks(double dh, double dist, double maxStep, double maxSlope)
        => dh > 0 && ((dist < StepDistanceM && dh > maxStep) || Math.Atan2(dh, dist) * 180 / Math.PI > maxSlope);

    /// <summary>Unknown room levels read as ground; retain payload objects and order.</summary>
    public static List<T> GroundStoreyFloors<T>(IEnumerable<T> floors, Func<T, string> roomId, Func<string, int?> levelOf)
        => floors.Where(f => (levelOf(roomId(f)) ?? 0) == 0).ToList();
}
