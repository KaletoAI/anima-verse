using System;
using System.Collections.Generic;
using AnimaNative.Overview;
using AnimaNative.Scene;
using AnimaNative.World;

namespace AnimaNative.Figures;

/// <summary>
/// The stations of a room change (<see cref="Via"/>, world metres) and, when it climbs stairs, the legs of that climb
/// (<see cref="Legs"/>, empty = no ride).
/// </summary>
public sealed record NpcRoutePlan(IReadOnlyList<Vec3> Via, IReadOnlyList<StairLeg> Legs);

/// <summary>What a mounted tile hands the room-change routing (main.ts <c>tile</c> + <c>scenes.get(loc)</c>).</summary>
public sealed class RouteTile
{
    public required TileFrame Frame { get; init; }
    /// <summary>The scene's <c>doorways[]</c>, tile-local.</summary>
    public IReadOnlyList<SceneDoorway> Doorways { get; init; } = Array.Empty<SceneDoorway>();
    /// <summary><c>roomIdOf(tile, raw)</c>: a room id or name → the room's id, null when the location has no such room.</summary>
    public Func<string?, string?> RoomIdOf { get; init; } = _ => null;
    /// <summary><c>tile.roomLevels</c> (keyed by id and name).</summary>
    public IReadOnlyDictionary<string, int> RoomLevels { get; init; } = new Dictionary<string, int>();
    /// <summary><c>tile.stairs</c> in world metres.</summary>
    public IReadOnlyList<StairLink> Stairs { get; init; } = Array.Empty<StairLink>();
    /// <summary><c>tile.elevatorStops</c>: storey → the pad's top face in world metres.</summary>
    public IReadOnlyDictionary<int, Vec3> LiftStops { get; init; } = new Dictionary<int, Vec3>();
}

/// <summary>
/// DOOR ROUTING of a real room change — client3d/src/main.ts <c>computeNpcPlacements</c>' <c>transition === 'route'</c>
/// branch: two rooms sharing a doorway walk through it; otherwise leave by the old room's door (<see cref="Doors.RoomDoor"/>),
/// climb a storey change by STAIRS FIRST (<see cref="Stairs.Chain"/> + its legs as the ride), else the lift stops
/// (<see cref="NpcWalk.LiftStops{T}"/>), and enter by the new room's door. Door stops are the doorway's centre at its
/// <c>base_y</c>, turned into the world (<c>doorStop</c> = <see cref="SceneView.TileToWorld"/>).
/// </summary>
public static class NpcRoute
{
    public static NpcRoutePlan Plan(RouteTile tile, string? prevRoom, string? inRoom)
    {
        var from = tile.RoomIdOf(prevRoom);
        var to = tile.RoomIdOf(inRoom);
        int LevelOf(string? r) => r is not null && tile.RoomLevels.TryGetValue(r, out var l) ? l : 0;
        int lf = LevelOf(prevRoom), lt = LevelOf(inRoom);
        var stops = new List<Vec3>();
        var legs = new List<StairLeg>();
        Vec3 DoorStop(DoorMarker m) => SceneView.TileToWorld(tile.Frame, m.Mid.X, m.Mid.Z, m.BaseY);
        var shared = from is not null && to is not null ? Doors.DoorwayBetween(tile.Doorways, from, to) : null;
        if (shared is not null)
        {
            stops.Add(DoorStop(shared));
        }
        else
        {
            var leave = from is not null ? Doors.RoomDoor(tile.Doorways, from) : null;
            if (leave is not null) stops.Add(DoorStop(leave));
            var chain = lf != lt && tile.Stairs.Count > 0 ? Stairs.Chain(tile.Stairs, lf, lt) : null;
            if (chain is not null)
            {
                foreach (var e in chain) stops.Add(e.Pos);
                legs.AddRange(Stairs.Legs(tile.Stairs, chain));
            }
            else if (lf != lt && tile.LiftStops.Count > 0)
            {
                stops.AddRange(NpcWalk.LiftStops(tile.LiftStops, lf, lt));
            }
            var enter = to is not null ? Doors.RoomDoor(tile.Doorways, to) : null;
            if (enter is not null) stops.Add(DoorStop(enter));
        }
        return new NpcRoutePlan(stops, legs);
    }
}
