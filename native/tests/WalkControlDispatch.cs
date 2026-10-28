using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json.Nodes;
using AnimaNative.Embody;
using AnimaNative.Scene;
using static AnimaNative.Tests.EmbodyVectorAdapters;

namespace AnimaNative.Tests;

/// <summary>Task 47: callback and sequence shapes of walk_control.json, as in embodyVectorDispatch.mjs.</summary>
internal static class WalkControlDispatch
{
    public static Dictionary<string, Func<JsonArray, JsonNode?>> Create()
    {
        var d = new Dictionary<string, Func<JsonArray, JsonNode?>>
        {
            ["constant"] = a => Constant(S(a[0])),
            ["walkDir"] = a => Point(Walk.WalkDir(((JsonArray)a[0]!).Select(S).ToHashSet(StringComparer.Ordinal), N(a[1]))),
            ["slideBlocked"] = a => Point(Walk.SlideBlocked(P(a[0]), P(a[1]), Blocked(a[2]))),
            ["terrainBlocks"] = a => JsonValue.Create(Walk.TerrainBlocks(B(a[0]), B(a[1]))),
            ["slopeBlocks"] = a => JsonValue.Create(Walk.SlopeBlocks(N(a[0]), N(a[1]), N(a[2]), N(a[3]))),
            ["groundStoreyFloors"] = a => Array(Walk.GroundStoreyFloors((JsonArray)a[0]!, f => S(f!["roomId"]),
                id => NullableN(Get(a[1], id)) is double lv ? (int)lv : null), f => f?.DeepClone()),
            ["planClickWalk"] = a => Point(ClickMove.PlanClickWalk(P(a[0]), P(a[1]), Blocked(a[2]))),
            ["reachedGoal"] = a => JsonValue.Create(ClickMove.ReachedGoal(P(a[0]), P(a[1]))),
            ["walkStalled"] = a => JsonValue.Create(ClickMove.WalkStalled(P(a[0]), P(a[1]))),
            ["goalDir"] = a => ClickMove.GoalDir(P(a[0]), P(a[1])) is { } g
                ? new JsonObject { ["x"] = g.X, ["z"] = g.Z, ["dist"] = g.Dist } : null,
            ["talkTargetNear"] = a => Talk(a) is { } t ? new JsonObject { ["name"] = t.Name, ["dist"] = t.Dist } : null,
            ["talkName"] = a => JsonValue.Create(Talk(a)?.Name),
            ["idleRoomWalk"] = _ => StateJson(RoomWalk.IdleRoomWalk()),
            ["isLocked"] = a => JsonValue.Create(Locks.IsLocked(LockMap(a[0]), S(a[1]))),
            ["lockReason"] = a => JsonValue.Create(Locks.LockReason(LockMap(a[0]), S(a[1]))),
            ["doorwayLock"] = a => JsonValue.Create(Locks.DoorwayLock((a[0] as JsonArray)?.Select(S), LockMap(a[1]), S(Arg(a, 2)))),
            ["unlockedRooms"] = a => Array(Locks.UnlockedRooms((JsonArray)a[0]!, LockMap(a[1]), r => S(r!["id"]), S(Arg(a, 2))), r => r?.DeepClone()),
            ["roomSwitchSequence"] = SwitchSequence,
            ["roomWalkCandidatesValue"] = Candidates,
            ["elevatorAt"] = a => Elevator.At(P(a[0]), I(a[1]), ((JsonArray)a[2]!).Select(s => new ElevatorStop(I(s!["level"]), P(s["pos"]))).ToList(), Rooms(a[3]), N(a[4])) is { } e
                ? new JsonObject { ["levels"] = Nums(e.Levels), ["current"] = e.Current, ["dist"] = e.Dist } : null,
            ["elevatorOptions"] = a => Nums(Elevator.Options(Lift(a[0]))),
            ["elevatorSoleOption"] = a => JsonValue.Create(Elevator.SoleOption(Lift(a[0]))),
        };
        AddProjections(d);
        return d;
    }
    private static ElevatorState Lift(JsonNode? n) => new(((JsonArray)n!["levels"]!).Select(I).ToList(), I(n["current"]), NullableN(n["dist"]) ?? 0);
    private static TalkOffer? Talk(JsonArray a)
    {
        var n = a[0]!;
        return Proximity.TalkTargetNear(new(S(n["name"]), P(n["pos"]), S(n["locId"]), NullableS(n["room"])),
            ((JsonArray)a[1]!).Select(o => new TalkCandidate(S(o!["name"]), P(o["pos"]), S(o["locId"]), NullableS(o["room"]), N(o["scale"]))));
    }
    private static JsonNode SwitchSequence(JsonArray a)
    {
        string? current = NullableS(a[0]);
        var rooms = Locks.UnlockedRooms(Rooms(a[1]), LockMap(Arg(a, 5)), r => r.Id, current ?? "");
        var state = RoomWalk.IdleRoomWalk();
        var results = new JsonArray();
        foreach (var step in (JsonArray)a[3]!)
        {
            var r = RoomWalk.NearestRoomSwitch(current, P(step![0]), rooms, I(a[2]), state, N(step[1]), NullableN(Arg(a, 4)) ?? 1.5);
            state = r.State; results.Add(r.Next);
        }
        return new JsonObject { ["next"] = results, ["state"] = StateJson(state) };
    }
    private static JsonNode Candidates(JsonArray a)
    {
        var n = a[0]!;
        var insideRooms = ((JsonArray)n["insideRooms"]!).Select(S).ToHashSet();
        var insideLevels = ((JsonArray)n["insideLevels"]!).Select(I).ToHashSet();
        var rooms = RoomWalk.RoomWalkCandidates(NullableN(n["ownLevel"]) is double lv ? (int)lv : null, P(n["pos"]), Rooms(n["rooms"]),
            insideRooms.Contains, insideLevels.Contains, S(n["groundId"]), l => S(Get(n["floorIds"], l.ToString(System.Globalization.CultureInfo.InvariantCulture))));
        return Array(rooms, RoomJson);
    }
}
