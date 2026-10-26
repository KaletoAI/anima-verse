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
using Xunit;
using static AnimaNative.Tests.ScatterVectorAdapters;
using static AnimaNative.Tests.SceneVectorAdapters;

namespace AnimaNative.Tests;

/// <summary>The JSON conventions of the four E5 placement files (shared/test-vectors/README.md "E5 room placement").</summary>
internal static class PlacementVectorAdapters
{
    /// <summary>A number argument; <c>{"$number": "NaN" | "Infinity"}</c> is a non-finite input.</summary>
    public static double N(JsonNode? node)
        => Key(node, "$number") is { } n
            ? Str(n) switch
            {
                "NaN" => double.NaN,
                "Infinity" => double.PositiveInfinity,
                var s => throw new ArgumentException($"unknown non-finite input {s}"),
            }
            : Num(node);

    /// <summary>A number or JSON null (absent = null as well).</summary>
    public static double? NOrNull(JsonNode? node) => node is null ? null : N(node);

    /// <summary><c>[a, b, c]</c> → <c>(u, v) =&gt; a·u + b·v + c</c>.</summary>
    public static Func<double, double, double> Plane(JsonNode? node)
    {
        var p = VectorCompare.NumList(node);
        if (p.Count != 3) throw new ArgumentException($"expected a plane [a, b, c], got {VectorCompare.Show(node)}");
        double a = p[0], b = p[1], c = p[2];
        return (u, v) => a * u + b * v + c;
    }

    public static JsonObject? Point(Vec3? v) => v is { } p ? Obj(p) : null;

    public static string TransitionName(FigureTransition t) => t switch
    {
        FigureTransition.Snap => "snap",
        FigureTransition.Route => "route",
        _ => "stay",
    };

    public static ShownPlacement Shown(JsonNode? n) => new(Key(n, "room") is { } r ? Str(r) : null, Bool(Key(n, "interiorShown")));
}

/// <summary>
/// shared/test-vectors/figure_ground.json (hand derivations: client3d/scripts/smoke_walk_math.mjs).
/// <code>
///   TS fn              C#                            TS source
///   placementOf        FigureGround.PlacementOf      client3d game/placement.ts (absent point = omitted argument)
///   figureTransition   FigureGround.Transition       client3d game/placement.ts
///   gateStandY         FigureGround.GateStandY       client3d game/walk.ts (null = the rung is silent)
///   standY             FigureGround.StandY           client3d game/ground.ts
///   tileWalkLadder     FigureGround.TileWalkLadder   client3d game/ground.ts
/// </code>
/// </summary>
public class FigureGroundVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("figure_ground"));

    private static readonly Dictionary<string, Func<JsonArray, JsonNode?>> Dispatch = new()
    {
        ["placementOf"] = a =>
        {
            Arity(a, 1, 2);
            var pos = Arg(a, 1);
            var p = FigureGround.PlacementOf(Bool(a[0]), pos is null ? null : PlacementVectorAdapters.N(Key(pos, "x")),
                                             pos is null ? null : PlacementVectorAdapters.N(Key(pos, "z")));
            var o = new JsonObject { ["kind"] = p.Kind.ToString().ToLowerInvariant() };
            if (p.Pos is { } at) o["pos"] = new JsonObject { ["x"] = at.X, ["z"] = at.Z };
            return o;
        },
        ["figureTransition"] = a =>
        {
            Arity(a, 2, 2);
            ShownPlacement? prev = a[0] is null ? null : PlacementVectorAdapters.Shown(a[0]);
            return PlacementVectorAdapters.TransitionName(FigureGround.Transition(prev, PlacementVectorAdapters.Shown(a[1])));
        },
        ["gateStandY"] = a => FigureGround.GateStandY(PlacementVectorAdapters.NOrNull(Arity(a, 3, 3)[0]),
                                                      PlacementVectorAdapters.NOrNull(a[1]), PlacementVectorAdapters.N(a[2])),
        ["standY"] = a => FigureGround.StandY(PlacementVectorAdapters.N(Arity(a, 2, 2)[0]), PlacementVectorAdapters.N(a[1])),
        ["tileWalkLadder"] = a => FigureGround.TileWalkLadder(Num(Arity(a, 4, 4)[0]), VectorCompare.NumOrNull(a[1]),
                                                              VectorCompare.NumOrNull(a[2]), VectorCompare.NumOrNull(a[3])),
    };

    public static TheoryData<string> Cases => VectorFile.Labels("figure_ground");

    [Theory]
    [MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, Dispatch);

    [Fact]
    public void EveryFunctionIsDispatched() => Assert.Empty(File.Value.MissingFunctions(Dispatch));
}

/// <summary>
/// shared/test-vectors/place_poll.json (hand derivations: client3d/scripts/smoke_places_client.mjs [9]).
/// <code>
///   pollIsStale        FigureGround.PollIsStale      client3d game/placement.ts (null = Infinity)
/// </code>
/// </summary>
public class PlacePollVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("place_poll"));

    private static readonly Dictionary<string, Func<JsonArray, JsonNode?>> Dispatch = new()
    {
        ["pollIsStale"] = a => FigureGround.PollIsStale(Num(Arity(a, 2, 2)[0]), a[1] is null ? double.PositiveInfinity : Num(a[1])),
    };

    public static TheoryData<string> Cases => VectorFile.Labels("place_poll");

    [Theory]
    [MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, Dispatch);

    [Fact]
    public void EveryFunctionIsDispatched() => Assert.Empty(File.Value.MissingFunctions(Dispatch));
}

/// <summary>
/// shared/test-vectors/room_spots.json (hand derivations: client3d/scripts/smoke_room_spots.mjs).
/// <code>
///   polygonCentroid     RoomSpots.PolygonCentroid     client3d game/ground.ts
///   roomSpotConstants   RoomSpots.* constants         (smoke wrapper; only the expected keys compared)
///   roomSpotGridHead    RoomSpots.Grid                (smoke wrapper: {length, first, firstDist})
///   furnitureUse        RoomSpots.FurnitureUse
///   roomFloorLadder     FigureGround.RoomFloorLadder  null declared = undefined, {"$number": "NaN"} terrain
///   roomStandLadder     FigureGround.RoomStandLadder  null centreY = undefined
///   roomSpotsOfValue    RoomSpots.Of                  client3d game/roomSpots.ts; samplers as [a, b, c] planes
/// </code>
/// </summary>
public class RoomSpotsVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("room_spots"));

    private static JsonObject P(P2 p) => new() { ["x"] = p.X, ["z"] = p.Z };

    private static JsonArray Points(IEnumerable<Vec3> list) => new(list.Select(v => (JsonNode?)Obj(v)).ToArray());

    private static readonly Dictionary<string, Func<JsonArray, JsonNode?>> Dispatch = new()
    {
        ["polygonCentroid"] = a => RoomSpots.PolygonCentroid(RingOrNull(Arity(a, 1, 1)[0])) is { } c ? P(c) : null,
        ["roomSpotConstants"] = a =>
        {
            Arity(a, 0, 0);
            return new JsonObject
            {
                ["SPOT_GRID"] = RoomSpots.SpotGrid, ["SPOT_SPREAD"] = RoomSpots.SpotSpread,
                ["SEAT_MIN_M"] = RoomSpots.SeatMinM, ["SEAT_MAX_M"] = RoomSpots.SeatMaxM,
                ["LIE_LENGTH_M"] = RoomSpots.LieLengthM, ["LIE_WIDTH_M"] = RoomSpots.LieWidthM,
            };
        },
        ["roomSpotGridHead"] = a =>
        {
            Arity(a, 5, 5);
            double cx = Num(a[1]), cz = Num(a[2]);
            var grid = RoomSpots.Grid(RingOrNull(a[0]), cx, cz, Num(a[3]), Num(a[4]));
            return new JsonObject
            {
                ["length"] = grid.Count,
                ["first"] = grid.Count > 0 ? P(grid[0]) : null,
                ["firstDist"] = grid.Count > 0 ? Math.Sqrt((grid[0].X - cx) * (grid[0].X - cx) + (grid[0].Z - cz) * (grid[0].Z - cz)) : null,
            };
        },
        ["furnitureUse"] = a => RoomSpots.FurnitureUse(Num(Arity(a, 4, 4)[0]), Num(a[1]), Num(a[2]), Num(a[3])),
        ["roomFloorLadder"] = a => FigureGround.RoomFloorLadder(Num(Arity(a, 4, 4)[0]), VectorCompare.NumOrNull(a[1]),
                                                                VectorCompare.NumOrNull(a[2]), PlacementVectorAdapters.N(a[3])),
        ["roomStandLadder"] = a => FigureGround.RoomStandLadder(VectorCompare.NumOrNull(Arity(a, 2, 2)[0]), VectorCompare.NumOrNull(a[1])),
        ["roomSpotsOfValue"] = a =>
        {
            var input = Arity(a, 1, 1)[0];
            var frame = new TileFrame(XYZ(Key(Key(input, "frame"), "center")), Num(Key(Key(input, "frame"), "yaw")));
            var props = ((JsonArray)Key(input, "props")!).Select(b => new SpotBox(XYZ(Key(b, "min")), XYZ(Key(b, "max")))).ToList();
            var markers = ((JsonArray)Key(input, "markers")!).Select(m => new SpotMarker(
                ((JsonArray)Key(m, "slots")!).Select(XYZ).ToList(), Num(Key(m, "drop")), Num(Key(m, "offsetY")),
                Key(m, "fixed") is { } f && Bool(f))).ToList();
            var r = RoomSpots.Of(Ring(Key(input, "hull")), frame, PlacementVectorAdapters.Plane(Key(input, "floorAt")),
                                 PlacementVectorAdapters.Plane(Key(input, "baseFloorAt")), props, markers);
            if (r is null) return null;
            return new JsonObject
            {
                ["rect"] = new JsonObject { ["x"] = r.Rect.X, ["z"] = r.Rect.Z, ["w"] = r.Rect.W, ["d"] = r.Rect.D },
                ["centreLocal"] = P(r.CentreLocal),
                ["centre"] = Obj(r.Centre),
                ["floorY"] = r.FloorY,
                ["sit"] = Points(r.Sit),
                ["lie"] = Points(r.Lie),
                ["markerY"] = new JsonArray(r.MarkerY.Select(y => y is { } v ? (JsonNode?)v : null).ToArray()),
            };
        },
    };

    public static TheoryData<string> Cases => VectorFile.Labels("room_spots");

    [Theory]
    [MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, Dispatch);

    [Fact]
    public void EveryFunctionIsDispatched() => Assert.Empty(File.Value.MissingFunctions(Dispatch));
}

/// <summary>
/// shared/test-vectors/npc_placement.json (hand derivations: client3d/scripts/smoke_npc_placement.mjs [1]–[5]).
/// <code>
///   huddleOffset           NpcPlacement.HuddleOffset      client3d game/npcPlacement.ts
///   placeAtLocationValue   NpcPlacement.PlaceAtLocation   tile + ctx as JSON; seatOf = PlaceSlots.SlotFor ('pair' → null);
///                                                         roomStand planes over tile-local, ground over world metres
/// </code>
/// The sort is <see cref="LocaleCompare"/>; <see cref="CollationMatchesTheBrowser"/> proves it against V8's order.
/// </summary>
public class NpcPlacementVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("npc_placement"));

    private static Dictionary<string, T> Map<T>(JsonNode? node, Func<JsonNode?, T> read)
        => node is JsonObject o ? o.ToDictionary(kv => kv.Key, kv => read(kv.Value)) : new Dictionary<string, T>();

    private static PlacementRow Row(JsonNode? r)
    {
        PlaceRef? place = null;
        if (Key(r, "place") is { } p)
        {
            var slot = Key(p, "slot");
            int? s = slot is JsonValue v && v.TryGetValue(out JsonElement e) && e.ValueKind == JsonValueKind.String
                ? (Str(slot) == "pair" ? null : throw new ArgumentException("slot string must be 'pair'"))
                : Int(slot);
            place = new PlaceRef(Str(Key(p, "id")), s);
        }
        return new PlacementRow(Str(Key(r, "name")), Key(r, "pos") is { } pos ? XZ(pos) : null, place,
                                Key(r, "activity_animation") is { } aa ? Str(aa) : "",
                                Key(r, "movement_target_id") is { } mt ? Str(mt) : "");
    }

    private static PlacementTile Tile(JsonNode? t)
    {
        var markers = Map(Key(t, "roomMarkers"), byId => Map(byId, m => new PlaceEntry
        {
            Id = "", RoomId = "", Group = "",
            Slots = ((JsonArray)Key(m, "slots")!).Select(XYZ).ToArray(),
            Rotation = PlacementVectorAdapters.NOrNull(Key(m, "rotation")),
            Tilt = PlacementVectorAdapters.NOrNull(Key(m, "tilt")),
            Roll = PlacementVectorAdapters.NOrNull(Key(m, "roll")),
        }));
        return new PlacementTile
        {
            Frame = new TileFrame(XYZ(Key(t, "center")), Num(Key(t, "yaw"))),
            Width = Num(Key(t, "width")),
            IsBuilding = Bool(Key(t, "isBuilding")),
            Fade = Num(Key(t, "fade")),
            LevelFilter = Int(Key(t, "levelFilter")),
            AlwaysVisibleRooms = ((JsonArray)Key(t, "alwaysVisibleRooms")!).Select(Str).ToHashSet(),
            RoomCenters = Map(Key(t, "roomCenters"), XYZ),
            RoomLevels = Map(Key(t, "roomLevels"), Int),
            RoomMarkers = markers,
            RoomSitSpots = Map(Key(t, "roomSitSpots"), l => (IReadOnlyList<Vec3>)((JsonArray)l!).Select(XYZ).ToList()),
            RoomLieSpots = Map(Key(t, "roomLieSpots"), l => (IReadOnlyList<Vec3>)((JsonArray)l!).Select(XYZ).ToList()),
            Corridors = ((JsonArray)Key(t, "corridors")!).Select(Str).ToList(),
        };
    }

    private static PlacementContext Context(JsonNode? c, Dictionary<string, string> roomOf)
    {
        var shown = Map(Key(c, "shown"), PlacementVectorAdapters.Shown);
        var stand = Map(Key(c, "roomStand"), PlacementVectorAdapters.Plane);
        var ground = PlacementVectorAdapters.Plane(Key(c, "ground"));
        var targets = Map(Key(c, "targets"), XYZ);
        return new PlacementContext
        {
            LocId = Str(Key(c, "locId")),
            Near = Bool(Key(c, "near")),
            RoomOf = name => roomOf.TryGetValue(name, out var r) ? r : null,
            ShownOf = name => shown.TryGetValue(name, out var s) ? s : null,
            RoomStandY = (room, lx, lz) => stand.TryGetValue(room, out var f) ? f(lx, lz) : null,
            GroundY = ground,
            TargetCentre = id => targets.TryGetValue(id, out var p) ? p : null,
        };
    }

    private static readonly Dictionary<string, Func<JsonArray, JsonNode?>> Dispatch = new()
    {
        ["huddleOffset"] = a =>
        {
            var p = NpcPlacement.HuddleOffset(Bool(Arity(a, 4, 4)[0]), Num(a[1]), Int(a[2]), Int(a[3]));
            return new JsonObject { ["x"] = p.X, ["z"] = p.Z };
        },
        ["placeAtLocationValue"] = a =>
        {
            Arity(a, 4, 4);
            var rows = ((JsonArray)a[0]!).Select(Row).ToList();
            var roomOf = Map(a[1], Str);
            var placed = NpcPlacement.PlaceAtLocation(rows, Tile(a[2]), Context(a[3], roomOf));
            return new JsonArray(placed.Select(p => (JsonNode?)new JsonObject
            {
                ["name"] = p.Row.Name,
                ["branch"] = p.Branch,
                ["pos"] = Obj(p.Pos),
                ["face"] = PlacementVectorAdapters.Point(p.Face),
                ["lean"] = p.Lean is { } l ? new JsonObject { ["tilt"] = l.Tilt, ["roll"] = l.Roll } : null,
                ["inRoom"] = p.InRoom,
                ["interiorShown"] = p.InteriorShown,
                ["hidden"] = p.Hidden,
                ["transition"] = PlacementVectorAdapters.TransitionName(p.Transition),
            }).ToArray());
        },
    };

    public static TheoryData<string> Cases => VectorFile.Labels("npc_placement");

    [Theory]
    [MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, Dispatch);

    [Fact]
    public void EveryFunctionIsDispatched() => Assert.Empty(File.Value.MissingFunctions(Dispatch));

    /// <summary>
    /// THE COLLATION PROOF: V8 (node 22, ICU 78.2, default locale en-US) sorts these names with
    /// <c>[...names].sort((a, b) =&gt; a.localeCompare(b))</c> into exactly the order below (run 2026-10-26); the
    /// placement sort must give the same — case-insensitive first ("bo" between "Ada" and "Cem"), lower before
    /// upper on a tie, accents secondary, punctuation before letters, digits as text.
    /// </summary>
    [Fact]
    public void CollationMatchesTheBrowser()
    {
        var names = new[]
        {
            "bo", "Ada", "Cem", "Dov", "ada", "Ada", "Émile", "Emil", "Zoë", "zoe", "Anne-Marie", "Annemarie", "Anne Marie",
            "O'Brien", "Obrien", "Öz", "Oz", "Ålborg", "Aaron", "ß", "ss", "Kai", "kai", "Ka", "Kä", "10", "9", "Bob2", "Bob10",
            "_x", "x",
        };
        var v8 = new[]
        {
            "_x", "10", "9", "Aaron", "ada", "Ada", "Ada", "Ålborg", "Anne Marie", "Anne-Marie", "Annemarie", "bo", "Bob10",
            "Bob2", "Cem", "Dov", "Emil", "Émile", "Ka", "Kä", "kai", "Kai", "O'Brien", "Obrien", "Oz", "Öz", "ss", "ß", "x",
            "zoe", "Zoë",
        };
        var sorted = names.OrderBy(n => n, LocaleCompare.Instance).ToArray();
        Assert.Equal(v8, sorted);
        // …and an ordinal sort would NOT (the reason the comparer exists).
        Assert.NotEqual(v8, names.OrderBy(n => n, StringComparer.Ordinal).ToArray());
    }
}
