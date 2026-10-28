using System;
using System.Collections.Generic;
using System.Linq;
using AnimaNative.Scatter;
using AnimaNative.Scene;

namespace AnimaNative.Embody;

/// <summary>The caller-owned hysteresis clock of roomwalk.ts (Task 47, E7-T2).</summary>
public readonly record struct RoomWalkState(string? Candidate, double SinceMs);
public readonly record struct RoomSwitch(string? Next, RoomWalkState State);

/// <summary>Task 47 (E7-T2): roomwalk.ts room/corridor/ground selection and delayed switching; walk_control.json.</summary>
public static class RoomWalk
{
    public static RoomWalkState IdleRoomWalk() => new(null, 0);

    /// <summary>Nearest on this storey; a tie keeps the occupied room, a changed candidate restarts the hold.</summary>
    public static RoomSwitch NearestRoomSwitch(string? current, P2 pos, IEnumerable<ElevatorRoom> rooms,
                                               int currentLevel, RoomWalkState state, double nowMs, double holdSeconds)
    {
        var scored = rooms.Where(r => r.Level == currentLevel)
            .Select(r => (r.Id, D: double.Hypot(r.Center.X - pos.X, r.Center.Z - pos.Z)))
            .OrderBy(r => r.D).ThenBy(r => r.Id, StringComparer.Ordinal).ToList();
        if (scored.Count == 0) return new(current, IdleRoomWalk());
        string best = scored[0].Id;
        var cur = scored.FindIndex(r => r.Id == current);
        if (cur >= 0 && scored[cur].D - scored[0].D <= 1e-9) best = current!;
        if (best == current) return new(current, IdleRoomWalk());
        if (state.Candidate != best) return new(current, new(best, nowMs));
        if (nowMs - state.SinceMs >= holdSeconds * 1000) return new(best, new(best, nowMs));
        return new(current, state);
    }

    /// <summary>Real rectangles first; otherwise a non-ground corridor, ground corridor within the outline, or ground.</summary>
    public static List<ElevatorRoom> RoomWalkCandidates(int? ownLevel, P2 pos, IReadOnlyList<ElevatorRoom> rooms,
        Func<string, bool> insideRect, Func<int, bool> insideLevelOutline, string groundId, Func<int, string> floorIdOf)
    {
        var inside = rooms.Where(r => insideRect(r.Id)).ToList();
        if (inside.Count > 0) return inside;
        if (rooms.Count == 0) return new();
        int level = ownLevel ?? 0;
        string floor = floorIdOf(level);
        if (level != 0) return floor.Length > 0 ? new() { new(floor, level, pos) } : rooms.ToList();
        if (floor.Length > 0 && insideLevelOutline(0)) return new() { new(floor, 0, pos) };
        return groundId.Length > 0 ? new() { new(groundId, 0, pos) } : rooms.ToList();
    }
}
