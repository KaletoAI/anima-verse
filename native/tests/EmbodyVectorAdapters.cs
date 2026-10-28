using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using AnimaNative.Embody;
using AnimaNative.Scatter;
using AnimaNative.Scene;
using AnimaNative.Tests.Vectors;

namespace AnimaNative.Tests;

/// <summary>Task 47 (E7-T2): shape-only adapters matching embodyVectorDispatch.mjs, including callback data and projections.</summary>
internal static class EmbodyVectorAdapters
{
    public static JsonNode? Get(JsonNode? n, string key) => n is JsonObject o ? o[key] : null;
    public static bool Missing(JsonNode? n) => n is null || n is JsonValue v && v.TryGetValue<JsonElement>(out var e) && e.ValueKind == JsonValueKind.Undefined;
    public static double N(JsonNode? n) => VectorCompare.Num(n);
    public static double? NullableN(JsonNode? n) => Missing(n) ? null : N(n);
    public static int I(JsonNode? n) => (int)N(n);
    public static bool B(JsonNode? n) => !Missing(n) && n!.GetValue<bool>();
    public static string S(JsonNode? n) => Missing(n) ? "" : n!.GetValue<string>();
    public static string? NullableS(JsonNode? n) => Missing(n) ? null : S(n);
    public static JsonNode? Arg(JsonArray a, int i) => i < a.Count ? a[i] : null;
    public static P2 P(JsonNode? n) => new(N(Get(n, "x")), N(Get(n, "z")));
    public static P2 Pt(JsonNode? n) => new(N(n![0]), N(n[1]));
    public static P2[]? Ring(JsonNode? n) => Missing(n) ? null : ((JsonArray)n!).Select(p => p is JsonArray a && a.Count >= 2 ? Pt(p) : new P2(double.NaN, double.NaN)).ToArray();
    public static JsonNode? Point(P2? p) => p is P2 v ? new JsonObject { ["x"] = v.X, ["z"] = v.Z } : null;
    public static JsonArray Array<T>(IEnumerable<T> values, Func<T, JsonNode?> map) => new(values.Select(map).ToArray());
    public static JsonArray Nums(IEnumerable<int> values) => Array(values, v => JsonValue.Create(v));
    public static JsonArray RingJson(IEnumerable<P2> ring) => Array(ring, p => new JsonArray(p.X, p.Z));
    public static IReadOnlyDictionary<string, string>? LockMap(JsonNode? n)
        => Missing(n) ? null : ((JsonObject)n!).ToDictionary(k => k.Key, k => k.Value is JsonValue v && v.TryGetValue<string>(out var s) ? s : "", StringComparer.Ordinal);
    public static ElevatorRoom Room(JsonNode? n) => new(S(n!["id"]), I(n["level"]), P(n["center"]), B(n["floor"]));
    public static List<ElevatorRoom> Rooms(JsonNode? n) => ((JsonArray)n!).Select(Room).ToList();
    public static JsonNode RoomJson(ElevatorRoom r)
    {
        var o = new JsonObject { ["id"] = r.Id, ["level"] = r.Level, ["center"] = Point(r.Center) };
        if (r.Floor) o["floor"] = true;
        return o;
    }
    public static JsonNode StateJson(RoomWalkState s) => new JsonObject { ["candidate"] = s.Candidate, ["sinceMs"] = s.SinceMs };

    /// <summary>Only the test adapter constructs rectangle/disc predicates; terrain policy remains in Walk.</summary>
    public static Func<double, double, bool> Blocked(JsonNode? data) => (x, z) =>
    {
        bool InRect(JsonNode? r, bool inclusive) => inclusive
            ? x >= N(r![0]) && z >= N(r[1]) && x <= N(r[2]) && z <= N(r[3])
            : x > N(r![0]) && z > N(r[1]) && x < N(r[2]) && z < N(r[3]);
        bool rock = (Get(data, "rects") as JsonArray ?? new()).Any(r => InRect(r, B(Get(data, "inclusive"))))
            || (Get(data, "discs") as JsonArray ?? new()).Any(r => double.Hypot(x - N(r![0]), z - N(r[1])) < N(r[2]));
        var footprints = Get(data, "footprints") as JsonArray;
        return footprints is null ? rock : Walk.TerrainBlocks(!rock, footprints.Any(r => InRect(r, true)));
    };

    /// <summary>Explicit projection paths from the fixture; never inspect expectations to choose a result.</summary>
    public static void AddProjections(Dictionary<string, Func<JsonArray, JsonNode?>> dispatch)
    {
        foreach (var (name, fn) in dispatch.ToArray())
            if (!dispatch.ContainsKey(name + "Value")) dispatch[name + "Value"] = a => Project(fn((JsonArray)a[0]!), (JsonArray)a[1]!);
    }
    private static JsonNode? Project(JsonNode? value, JsonArray path)
    {
        foreach (var k in path)
        {
            if (k is JsonValue kv && kv.TryGetValue<int>(out var index)) { value = value![index]; continue; }
            string key = S(k);
            value = key switch
            {
                "$ids" => Array((JsonArray)value!, v => v!["id"]?.DeepClone()),
                "$roomIds" => Array((JsonArray)value!, v => v!["roomId"]?.DeepClone()),
                "$length" => JsonValue.Create(double.Hypot(N(value!["x"]), N(value["z"]))),
                "length" when value is JsonArray ar => JsonValue.Create(ar.Count),
                _ => value is JsonObject o ? o[key] : null,
            };
        }
        return value?.DeepClone();
    }
    public static JsonNode? Constant(string name) => JsonValue.Create(name switch
    {
        "GOAL_ARRIVE_M" => ClickMove.GoalArriveM, "STALL_STEP_M" => ClickMove.StallStepM,
        "STALL_FRAMES" => ClickMove.StallFrames, "TALK_RANGE" => Proximity.TalkRange,
        "ELEVATOR_RANGE" => Elevator.ElevatorRange, "BODY_RADIUS_M" => Collide.BodyRadiusM,
        "DOOR_EASE_M" => Collide.DoorEaseM, "PLACE_PICK_RADIUS_M" => PlacePick.PlacePickRadiusM,
        "ECHO_RING_CAP" => PosEcho.EchoRingCap, "STEP_DISTANCE_M" => Walk.StepDistanceM,
        _ => throw new ArgumentException("Unknown constant " + name),
    });
}
