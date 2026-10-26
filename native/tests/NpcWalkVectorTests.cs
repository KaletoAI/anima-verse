using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using AnimaNative.Figures;
using AnimaNative.Overview;
using AnimaNative.Scatter;
using AnimaNative.Scene;
using AnimaNative.Tests.Vectors;
using AnimaNative.Water;
using AnimaNative.World;
using Xunit;
using static AnimaNative.Tests.ScatterVectorAdapters;
using static AnimaNative.Tests.SceneVectorAdapters;

namespace AnimaNative.Tests;

/// <summary>
/// shared/test-vectors/npc_walk.json (hand derivations: client3d/scripts/smoke_npc_walk.mjs; TS source
/// client3d/src/game/npcWalk.ts). Points are <c>{x, y, z}</c>.
/// <code>
///   TS fn            C#                         shape translation
///   npcGoal          NpcWalk.Goal               plan ↔ {goal, retired, delta, distToGoal, dist, moving}
///   npcStepValue     NpcWalk.Step               the smoke adapter: (d, hasWaypoint, movement, reckoning, dt, pace,
///                                               limit, measured = null) builds the plan {delta (d, 0, 0), distToGoal d,
///                                               dist d (+10 with a waypoint), moving d &gt; 0.05}
///   neighbourFacing  NpcWalk.NeighbourFacing
///   standingFacing   NpcWalk.StandingFacing     null marker / neighbour / view yaw
///   facingYaw        NpcWalk.FacingYaw
///   easeNpcYaw       NpcWalk.EaseYaw
///   easeNpcY         NpcWalk.EaseY
///   liftStops        NpcWalk.LiftStops          [level, point] pairs → the stop dictionary (the smoke's Map)
/// </code>
/// </summary>
public class NpcWalkVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("npc_walk"));

    private static Vec3? XYZOrNull(JsonNode? n) => n is null ? null : XYZ(n);

    private static JsonObject? Json3(Vec3? v) => v is { } p ? Obj(p) : null;

    private static readonly Dictionary<string, Func<JsonArray, JsonNode?>> Dispatch = new()
    {
        ["npcGoal"] = a =>
        {
            Arity(a, 3, 4);
            var plan = NpcWalk.Goal(XYZ(a[0]), XYZ(a[1]), ((JsonArray)a[2]!).Select(XYZ).ToList(),
                                    Arg(a, 3) is { } r ? Num(r) : NpcWalk.WaypointArriveM);
            return new JsonObject
            {
                ["goal"] = Obj(plan.Goal), ["retired"] = plan.Retired, ["delta"] = Obj(plan.Delta),
                ["distToGoal"] = plan.DistToGoal, ["dist"] = plan.Dist, ["moving"] = plan.Moving,
            };
        },
        ["npcStepValue"] = a =>
        {
            Arity(a, 7, 8);
            double d = Num(a[0]);
            var plan = new NpcGoalPlan(new Vec3(d, 0, 0), 0, new Vec3(d, 0, 0), d, d + (Bool(a[1]) ? 10 : 0), d > 0.05);
            var (running, step) = NpcWalk.Step(plan, Str(a[2]), Bool(a[3]), Num(a[4]), Num(a[5]), Num(a[6]),
                                               Arg(a, 7) is { } m ? Num(m) : null);
            return new JsonObject { ["running"] = running, ["step"] = step };
        },
        ["neighbourFacing"] = a => Json3(NpcWalk.NeighbourFacing(XYZ(Arity(a, 2, 2)[0]), ((JsonArray)a[1]!).Select(XYZ).ToList())),
        ["standingFacing"] = a =>
        {
            Arity(a, 4, 4);
            return Json3(NpcWalk.StandingFacing(XYZ(a[0]), XYZOrNull(a[1]), XYZOrNull(a[2]), a[3] is { } y ? Num(y) : null));
        },
        ["facingYaw"] = a => NpcWalk.FacingYaw(XYZ(Arity(a, 1, 1)[0])),
        ["easeNpcYaw"] = a => NpcWalk.EaseYaw(Num(Arity(a, 3, 3)[0]), Num(a[1]), Num(a[2])),
        ["easeNpcY"] = a => NpcWalk.EaseY(Num(Arity(a, 3, 3)[0]), Num(a[1]), Num(a[2])),
        ["liftStops"] = a =>
        {
            Arity(a, 3, 3);
            var stops = new Dictionary<int, Vec3>();
            foreach (var pair in (JsonArray)a[0]!) stops[Int(pair![0])] = XYZ(pair[1]);
            return new JsonArray(NpcWalk.LiftStops(stops, Int(a[1]), Int(a[2])).Select(p => (JsonNode?)Obj(p)).ToArray());
        },
    };

    public static TheoryData<string> Cases => VectorFile.Labels("npc_walk");

    [Theory]
    [MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, Dispatch);

    [Fact]
    public void EveryFunctionIsDispatched() => Assert.Empty(File.Value.MissingFunctions(Dispatch));

    /// <summary>The smoke's purity check: the inputs of <c>npcGoal</c> / <c>neighbourFacing</c> are not changed.</summary>
    [Fact]
    public void GoalLeavesItsInputsAlone()
    {
        var stations = new List<Vec3> { new(1, 0, 0) };
        var plan = NpcWalk.Goal(new Vec3(0, 0, 0), new Vec3(10, 2, 0), stations);
        NpcWalk.NeighbourFacing(new Vec3(0, 0, 0), stations);
        Assert.Single(stations);
        Assert.Equal(1, plan.Retired);
    }
}

/// <summary>
/// shared/test-vectors/npc_ground.json (hand derivations: client3d/scripts/smoke_walk_math.mjs [30]; TS sources
/// client3d/src/game/walk.ts, doors.ts, elevator.ts). Non-finite inputs are <c>{"$number": "NaN"}</c>.
/// <code>
///   TS fn               C#                           shape translation
///   groundScope         WaterGates.ScopeOf           null = undefined; GroundScope ↔ "wilderness" | "open" | "built"
///   terrainPace         WalkGround.TerrainPace
///   sinkForState        WalkGround.SinkForState      sink {move, idle}
///   groundSink          WalkGround.GroundSink
///   floatRootY          WalkGround.FloatRootY        null mirror
///   floatBodyY          FloatRootY − sink            the smoke adapter
///   wadeGate            WaterGates.WadeGate          GroundWater ↔ {movement, sink: {move, idle}, water}
///   ghostCutY           WaterGates.GhostCutY
///   roomDoor            Doors.RoomDoor               the payload's doorways through the native parser (SceneJson.Doorway);
///                                                    DoorMarker ↔ {mid: {x, z}, along, width, baseY, roomIds, outside};
///                                                    the optional origin {x, z}
///   doorwayBetween      Doors.DoorwayBetween         as roomDoor
///   elevatorLevels      Elevator.Levels              stops [{level, pos: {x, z}}], rooms [{id, level, center, floor?}]
///   elevatorTargetRoom  Elevator.TargetRoom
///   &lt;fn&gt;Value           the smoke's nameValue        call &lt;fn&gt;(...args[0]) and select the key path args[1]
/// </code>
/// </summary>
public class NpcGroundVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("npc_ground"));

    private static double N(JsonNode? n) => PlacementVectorAdapters.N(n);

    private static bool? BoolOrNull(JsonNode? n) => n is null ? null : Bool(n);

    private static GroundScope Scope(JsonNode? n) => Str(n) switch
    {
        "wilderness" => GroundScope.Wilderness,
        "open" => GroundScope.Open,
        "built" => GroundScope.Built,
        var s => throw new ArgumentException($"unknown scope '{s}'"),
    };

    private static string ScopeName(GroundScope s) => s.ToString().ToLowerInvariant();

    private static GroundSink Sink(JsonNode? n) => new(N(Key(n, "move")), N(Key(n, "idle")));

    private static GroundWater Word(JsonNode? o)
        => new(Str(Key(o, "movement")), Sink(Key(o, "sink")), Key(o, "water") is { } w ? N(w) : null);

    private static JsonObject WordJson(GroundWater w) => new()
    {
        ["movement"] = w.Movement,
        ["sink"] = new JsonObject { ["move"] = w.Sink.Move, ["idle"] = w.Sink.Idle },
        ["water"] = w.Water,
    };

    /// <summary>The payload's <c>doorways[]</c> through the native parser; a null payload has none.</summary>
    private static List<SceneDoorway>? Doorways(JsonNode? payload)
        => payload is null ? null
            : (Key(payload, "doorways") as JsonArray ?? new JsonArray()).Select(d => SceneJson.Doorway(Element(d))).ToList();

    private static P2 Origin(JsonArray a, int i) => Arg(a, i) is { } o ? XZ(o) : default;

    private static JsonObject? MarkerJson(DoorMarker? m) => m is null ? null : new JsonObject
    {
        ["mid"] = new JsonObject { ["x"] = m.Mid.X, ["z"] = m.Mid.Z },
        ["along"] = new JsonObject { ["x"] = m.Along.X, ["z"] = m.Along.Z },
        ["width"] = m.Width,
        ["baseY"] = m.BaseY,
        ["roomIds"] = new JsonArray(m.RoomIds.Select(r => (JsonNode?)r).ToArray()),
        ["outside"] = m.Outside,
    };

    private static List<ElevatorStop> Stops(JsonNode? n)
        => ((JsonArray)n!).Select(s => new ElevatorStop(Int(Key(s, "level")), XZ(Key(s, "pos")))).ToList();

    private static List<ElevatorRoom> Rooms(JsonNode? n)
        => ((JsonArray)n!).Select(r => new ElevatorRoom(Str(Key(r, "id")), Int(Key(r, "level")), XZ(Key(r, "center")),
                                                        Key(r, "floor") is { } f && Bool(f))).ToList();

    private static readonly Dictionary<string, Func<JsonArray, JsonNode?>> Fns = new()
    {
        ["groundScope"] = a => ScopeName(WaterGates.ScopeOf(BoolOrNull(Arity(a, 2, 2)[0]), BoolOrNull(a[1]))),
        ["terrainPace"] = a => WalkGround.TerrainPace(N(Arity(a, 2, 2)[0]), Scope(a[1])),
        ["sinkForState"] = a => WalkGround.SinkForState(Bool(Arity(a, 3, 3)[0]), Str(a[1]), Sink(a[2])),
        ["groundSink"] = a => WalkGround.GroundSink(N(Arity(a, 2, 2)[0]), Scope(a[1])),
        ["floatRootY"] = a => WalkGround.FloatRootY(N(Arity(a, 3, 3)[0]), a[1] is { } w ? N(w) : null, N(a[2])),
        ["floatBodyY"] = a => WalkGround.FloatRootY(N(Arity(a, 3, 3)[0]), a[1] is { } w ? N(w) : null, N(a[2])) - N(a[2]),
        ["wadeGate"] = a => WordJson(WaterGates.WadeGate(Word(Arity(a, 3, 3)[0]), N(a[1]), N(a[2]))),
        ["ghostCutY"] = a => WaterGates.GhostCutY(N(Arity(a, 2, 2)[0]), a[1] is { } w ? N(w) : null),
        ["roomDoor"] = a => MarkerJson(Doors.RoomDoor(Doorways(Arity(a, 2, 3)[0]), Str(a[1]), Origin(a, 2))),
        ["doorwayBetween"] = a => MarkerJson(Doors.DoorwayBetween(Doorways(Arity(a, 3, 4)[0]), Str(a[1]), Str(a[2]), Origin(a, 3))),
        ["elevatorLevels"] = a => new JsonArray(Elevator.Levels(Stops(Arity(a, 2, 2)[0]), Rooms(a[1])).Select(l => (JsonNode?)l).ToArray()),
        ["elevatorTargetRoom"] = a => Elevator.TargetRoom(Int(Arity(a, 3, 3)[0]), Stops(a[1]), Rooms(a[2])),
    };

    private static readonly Dictionary<string, Func<JsonArray, JsonNode?>> Dispatch = Build();

    /// <summary>Every function plus its <c>&lt;fn&gt;Value</c> twin (the smoke's <c>nameValue(args, fields)</c>).</summary>
    private static Dictionary<string, Func<JsonArray, JsonNode?>> Build()
    {
        var d = new Dictionary<string, Func<JsonArray, JsonNode?>>(Fns);
        foreach (var (name, fn) in Fns)
            d[name + "Value"] = a =>
            {
                Arity(a, 2, 2);
                var v = fn((JsonArray)a[0]!.DeepClone());
                foreach (var key in (JsonArray)a[1]!) v = Key(v, Str(key));
                return v?.DeepClone();
            };
        return d;
    }

    public static TheoryData<string> Cases => VectorFile.Labels("npc_ground");

    [Theory]
    [MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, Dispatch);

    [Fact]
    public void EveryFunctionIsDispatched() => Assert.Empty(File.Value.MissingFunctions(Dispatch));
}
