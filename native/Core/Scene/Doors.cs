using System;
using System.Collections.Generic;
using System.Linq;
using AnimaNative.Scatter;
using AnimaNative.World;

namespace AnimaNative.Scene;

/// <summary>
/// One walk-through gap of one storey (client3d/src/game/doors.ts <c>DoorMarker</c>): every field is the payload's
/// <c>doorways[]</c> entry — the clear opening's centre (+ <c>origin</c>), the wall direction, the clear width, the base
/// height, the rooms it joins (non-empty strings, payload order) and whether it leads outside.
/// </summary>
public sealed record DoorMarker(P2 Mid, P2 Along, double Width, double BaseY, IReadOnlyList<string> RoomIds, bool Outside);

/// <summary>
/// The doorway lookups of client3d/src/game/doors.ts the figure routing walks through (<c>roomDoor</c>,
/// <c>doorwayBetween</c>) — checked against shared/test-vectors/npc_ground.json (hand derivations:
/// client3d/scripts/smoke_walk_math.mjs [30]). The payload is tile-local; <c>origin</c> only shifts the point, and the
/// 3D client leaves it at 0/0 and turns the result with <see cref="SceneView.TileToWorld"/>.
/// </summary>
public static class Doors
{
    /// <summary>doors.ts <c>marker(d, origin)</c>: the entry in the caller's frame, or null when it is not usable.</summary>
    public static DoorMarker? Marker(SceneDoorway? d, P2 origin)
    {
        if (d is null || !d.Usable) return null;
        return new DoorMarker(new P2(origin.X + d.AtWorld.X, origin.Z + d.AtWorld.Z), d.Along, d.WidthM,
                              double.IsFinite(d.BaseY) ? d.BaseY : 0, d.Rooms.Where(r => r.Length > 0).ToList(), d.Outside);
    }

    /// <summary>
    /// <c>roomDoor(payload, roomId, origin)</c>: the first door of the room that leads OUTSIDE, else the first one
    /// listed; null for an empty id or a room without a doorway. (An unusable outside door answers null, as in TS.)
    /// </summary>
    public static DoorMarker? RoomDoor(IEnumerable<SceneDoorway>? doorways, string roomId, P2 origin = default)
    {
        if (string.IsNullOrEmpty(roomId)) return null;
        SceneDoorway? first = null;
        foreach (var d in doorways ?? Array.Empty<SceneDoorway>())
        {
            if (d is null || !d.Rooms.Contains(roomId)) continue;
            if (d.Outside) return Marker(d, origin);
            first ??= d;
        }
        return Marker(first, origin);
    }

    /// <summary><c>doorwayBetween(payload, a, b, origin)</c>: the first doorway naming both rooms; a room joins nothing with itself.</summary>
    public static DoorMarker? DoorwayBetween(IEnumerable<SceneDoorway>? doorways, string a, string b, P2 origin = default)
    {
        if (string.IsNullOrEmpty(a) || string.IsNullOrEmpty(b) || a == b) return null;
        foreach (var d in doorways ?? Array.Empty<SceneDoorway>())
        {
            if (d is null) continue;
            if (d.Rooms.Contains(a) && d.Rooms.Contains(b)) return Marker(d, origin);
        }
        return null;
    }
}

/// <summary>Where the lift holds on one storey (elevator.ts <c>ElevatorStop</c>, XZ only).</summary>
public readonly record struct ElevatorStop(int Level, P2 Pos);

/// <summary>One room of a building as the lift and the stairs choose (elevator.ts <c>ElevatorRoom</c>); <see cref="Floor"/> = the storey corridor.</summary>
public readonly record struct ElevatorRoom(string Id, int Level, P2 Center, bool Floor = false);

/// <summary>
/// The storey choice of client3d/src/game/elevator.ts (<c>elevatorLevels</c>, <c>elevatorTargetRoom</c>) and
/// stairs.ts <c>nearestRoomAt</c> — checked against shared/test-vectors/npc_ground.json.
/// </summary>
public static class Elevator
{
    /// <summary><c>elevatorLevels(stops, rooms)</c>: the storeys with a stop AND a room, ascending, each once.</summary>
    public static List<int> Levels(IEnumerable<ElevatorStop> stops, IEnumerable<ElevatorRoom> rooms)
    {
        var withRooms = new HashSet<int>(rooms.Select(r => r.Level));
        var levels = new SortedSet<int>();
        foreach (var s in stops)
            if (withRooms.Contains(s.Level)) levels.Add(s.Level);
        return levels.ToList();
    }

    /// <summary><c>elevatorTargetRoom(level, stops, rooms)</c>: <see cref="NearestRoomAt"/> from that storey's first stop; null without one.</summary>
    public static string? TargetRoom(int level, IReadOnlyList<ElevatorStop> stops, IReadOnlyList<ElevatorRoom> rooms)
    {
        foreach (var s in stops)
            if (s.Level == level) return NearestRoomAt(level, s.Pos, rooms);
        return null;
    }

    /// <summary>
    /// stairs.ts <c>nearestRoomAt(level, pos, rooms)</c>: the storey's corridor first; else the room whose centre is
    /// nearest (a tie to the lower id, ordinal like JS <c>&lt;</c>); null when the storey has no room.
    /// </summary>
    public static string? NearestRoomAt(int level, P2 pos, IReadOnlyList<ElevatorRoom> rooms)
    {
        foreach (var r in rooms)
            if (r.Level == level && r.Floor) return r.Id;
        string? best = null;
        double bestDist = double.PositiveInfinity;
        foreach (var r in rooms)
        {
            if (r.Level != level) continue;
            double dist = Math.Sqrt((r.Center.X - pos.X) * (r.Center.X - pos.X) + (r.Center.Z - pos.Z) * (r.Center.Z - pos.Z));
            if (dist < bestDist || (dist == bestDist && best is not null && string.CompareOrdinal(r.Id, best) < 0))
            {
                best = r.Id;
                bestDist = dist;
            }
        }
        return best;
    }
}
