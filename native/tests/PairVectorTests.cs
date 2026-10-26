using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json.Nodes;
using AnimaNative.Figures;
using AnimaNative.Overview;
using AnimaNative.Scatter;
using AnimaNative.Scene;
using AnimaNative.Tests.Vectors;
using Xunit;
using static AnimaNative.Tests.ScatterVectorAdapters;

namespace AnimaNative.Tests;

/// <summary>
/// The adapters of client3d/scripts/pairVectorDispatch.mjs (Task 32), mirrored for the native ports:
/// <code>
///   TS fn                   C#                                     shape translation
///   pairClipValue           PairClip.Phase                         (PairClipInput, 'clipT' | 'phase')
///   pairSnapS               PairClip.SnapS
///   pairFrames              PairClip.Phase per frame               local clock += dt while rate &gt; 0, written back
///   isPairClipName          PairClip.IsPairClipName
///   extractPairRootPath     PairClip.ExtractRootPath (/100)        tracks {name, times, values} → {times, xz}
///   pairRootPathValue       BridgeTravel.RootPathAt                ({times, xz}, t, 'x' | 'z')
///   pairRoomStandY          FigureStands.RoomStandY                the tile: centre, roomFloors [[id, {hull, declared}]],
///                                                                  roomCenters [[id, [x, y, z]]], surfaces (always [])
///   pairPlacementValue      PairPlay.Advance(1/30) + Place         the source smoke's NPC: clip handshake__a, elapsed 0,
///                                                                  clipT 0, duration 2, loop, rate 1; root stub = data.root;
///                                                                  seat = slot 0 of seatSlots (null = unknown place); room
///                                                                  stand = roomStandY(tile, room, x − ax, z − az); ground = terrainY
///   anchorFigureBindValue   FigureBind.Anchor                      {min, max, height, initialPosition, initialScale} →
///                                                                  {scale, position, min, max}; the initial pose is reset
///                                                                  by the routine (owned), so it does not enter
/// </code>
/// </summary>
internal static class PairVectorAdapters
{
    private static double N(JsonNode? n) => VectorCompare.Num(n);

    private static double? NumOpt(JsonObject o, string key)
        => o.TryGetPropertyValue(key, out var v) && v is not null ? N(v) : null;

    public static PairClipInput Input(JsonNode? node)
    {
        var o = (JsonObject)node!;
        return new PairClipInput(NumOpt(o, "elapsedGameS"), N(o["rate"]), o["loop"]!.GetValue<bool>(), N(o["clipDurationS"]),
                                 NumOpt(o, "localClipT"), NumOpt(o, "snapS"));
    }

    public static JsonNode? Field((double ClipT, double Phase) r, JsonNode? field) => Str(field) switch
    {
        "clipT" => r.ClipT,
        "phase" => r.Phase,
        var f => throw new ArgumentException($"Unknown pair clip field {f}"),
    };

    private static float[] Floats(JsonNode? n) => ((JsonArray)n!).Select(v => (float)N(v)).ToArray();

    public static FigureStands Tile(JsonNode? node)
    {
        var t = (JsonObject)node!;
        if (((JsonArray)t["surfaces"]!).Count > 0) throw new ArgumentException("tile surfaces are not part of the pair vectors");
        var c = (JsonArray)t["center"]!;
        var stands = new FigureStands { Frame = new TileFrame(new Vec3(N(c[0]), N(c[1]), N(c[2])), 0) };
        foreach (var entry in (JsonArray)t["roomFloors"]!)
        {
            var e = (JsonArray)entry!;
            var f = (JsonObject)e[1]!;
            var hull = ((JsonArray)f["hull"]!).Select(p => new P2(N(p![0]), N(p[1]))).ToList();
            stands.RoomFloors.Add(new KeyValuePair<string, RoomFloor>(Str(e[0]), new RoomFloor { Hull = hull, Declared = NumOpt(f, "declared") }));
        }
        foreach (var entry in (JsonArray)t["roomCenters"]!)
        {
            var e = (JsonArray)entry!;
            var p = (JsonArray)e[1]!;
            stands.RoomCenters[Str(e[0])] = new Vec3(N(p[0]), N(p[1]), N(p[2]));
        }
        return stands;
    }

    /// <summary>The source smoke's one NPC in a pair, one 1/30 s tick through the production clock and placement.</summary>
    public static V3 Placement(JsonNode? node)
    {
        var d = (JsonObject)node!;
        var anchor = (JsonObject)d["anchor"]!;
        var stands = Tile(d["tile"]);
        string? room = d["room"] is { } r ? Str(r) : null;
        var play = new PairPlay
        {
            Id = "p1", Clip = "handshake__a",
            Anchor = new PairAnchor(N(anchor["x"]), N(anchor["z"]), N(anchor["yaw"]), d["placeId"] is { } pid ? Str(pid) : null),
            Elapsed = 0, ClipT = 0, ClipDuration = 2, Loop = true, Rate = 1, Stamp = 0,
        };
        play.Advance(1.0 / 30);
        var root = (JsonObject)d["root"]!;
        double? seatY = d["seatSlots"] is JsonArray slots ? N(slots[0]!["y"]) : null;
        double terrain = N(d["terrainY"]);
        return play.Place((N(root["x"]), N(root["z"])), (_, _, _) => seatY,
                          (x, z) => room is null ? null : stands.RoomStandY(room, x - play.Anchor.X, z - play.Anchor.Z),
                          (_, _) => terrain);
    }

    public static JsonNode? Axis(V3 v, JsonNode? field) => Str(field) switch
    {
        "x" => v.X,
        "y" => v.Y,
        "z" => v.Z,
        var f => throw new ArgumentException($"Unknown axis {f}"),
    };

    private static V3 Vec(JsonNode? n) => new(N(n![0]), N(n[1]), N(n[2]));

    private static JsonArray Arr(V3 v) => new(v.X, v.Y, v.Z);

    public static JsonObject AnchorBind(JsonNode? node)
    {
        var d = (JsonObject)node!;
        V3 min = Vec(d["min"]), max = Vec(d["max"]);
        var (k, pos) = FigureBind.Anchor(min, max, N(d["height"]));
        return new JsonObject
        {
            ["scale"] = k, ["position"] = Arr(pos), ["min"] = Arr(min * k + pos), ["max"] = Arr(max * k + pos),
        };
    }

    public static readonly Dictionary<string, Func<JsonArray, JsonNode?>> Dispatch = new()
    {
        ["pairClipValue"] = a => Field(PairClip.Phase(Input(Arity(a, 2, 2)[0])), a[1]),
        ["pairSnapS"] = a =>
        {
            Arity(a, 0, 0);
            return PairClip.SnapS;
        },
        ["pairFrames"] = a =>
        {
            Arity(a, 3, 3);
            var input = Input(a[0]);
            (double ClipT, double Phase) result = default;
            foreach (var dt in (JsonArray)a[1]!)
            {
                input = input with { LocalClipT = input.LocalClipT + (input.Rate > 0 ? N(dt) : 0) };
                result = PairClip.Phase(input);
                input = input with { LocalClipT = result.ClipT };
            }
            return Field(result, a[2]);
        },
        ["isPairClipName"] = a => PairClip.IsPairClipName(Str(Arity(a, 1, 1)[0])),
        ["extractPairRootPath"] = a =>
        {
            var tracks = ((JsonArray)Arity(a, 1, 1)[0]!).Select(t => new PairTrack(Str(t!["name"]), Floats(t["times"]), Floats(t["values"])));
            var path = PairClip.ExtractRootPath(tracks);
            return new JsonObject
            {
                ["times"] = new JsonArray(path.Times.Select(v => (JsonNode?)(double)v).ToArray()),
                ["xz"] = new JsonArray(path.Xz.Select(v => (JsonNode?)(double)v).ToArray()),
            };
        },
        ["pairRootPathValue"] = a =>
        {
            Arity(a, 3, 3);
            var p = BridgeTravel.RootPathAt(new RootPath(Floats(a[0]!["times"]), Floats(a[0]!["xz"])), N(a[1]));
            return Str(a[2]) switch
            {
                "x" => p.X,
                "z" => p.Z,
                var f => throw new ArgumentException($"Unknown axis {f}"),
            };
        },
        ["pairRoomStandY"] = a =>
        {
            Arity(a, 4, 4);
            return Tile(a[0]).RoomStandY(Str(a[1]), N(a[2]), N(a[3]));
        },
        ["pairPlacementValue"] = a => Axis(Placement(Arity(a, 2, 2)[0]), a[1]),
        ["anchorFigureBindValue"] = a => AnchorBind(Arity(a, 1, 1)[0]),
    };
}

/// <summary>shared/test-vectors/pair_clip_phase.json (hand derivations: client3d/scripts/smoke_pair_realtime.mjs).</summary>
public class PairClipPhaseVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("pair_clip_phase"));
    public static TheoryData<string> Cases => VectorFile.Labels("pair_clip_phase");

    [Theory]
    [MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, PairVectorAdapters.Dispatch);

    [Fact]
    public void EveryFunctionIsDispatched() => Assert.Empty(File.Value.MissingFunctions(PairVectorAdapters.Dispatch));
}

/// <summary>shared/test-vectors/pair_clip_geometry.json (hand derivations: client3d/scripts/smoke_clip_pair.mjs).</summary>
public class PairClipGeometryVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("pair_clip_geometry"));
    public static TheoryData<string> Cases => VectorFile.Labels("pair_clip_geometry");

    [Theory]
    [MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, PairVectorAdapters.Dispatch);

    [Fact]
    public void EveryFunctionIsDispatched() => Assert.Empty(File.Value.MissingFunctions(PairVectorAdapters.Dispatch));
}

/// <summary>shared/test-vectors/pair_height.json (hand derivations: client3d/scripts/smoke_pair_storey.mjs).</summary>
public class PairHeightVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("pair_height"));
    public static TheoryData<string> Cases => VectorFile.Labels("pair_height");

    [Theory]
    [MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, PairVectorAdapters.Dispatch);

    [Fact]
    public void EveryFunctionIsDispatched() => Assert.Empty(File.Value.MissingFunctions(PairVectorAdapters.Dispatch));
}

/// <summary>shared/test-vectors/figure_normalisation.json (hand derivations: client3d/scripts/smoke_figure_normalisation.mjs).</summary>
public class FigureNormalisationVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("figure_normalisation"));
    public static TheoryData<string> Cases => VectorFile.Labels("figure_normalisation");

    [Theory]
    [MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, PairVectorAdapters.Dispatch);

    [Fact]
    public void EveryFunctionIsDispatched() => Assert.Empty(File.Value.MissingFunctions(PairVectorAdapters.Dispatch));
}

/// <summary>
/// The runtime rules around the vectors (npcs.ts <c>adoptInteraction</c>, <c>tickInteraction</c>; figures.ts
/// <c>playPair</c>'s resync), every number derived by hand here.
/// </summary>
public class PairPlayTests
{
    private static PairInteraction Row(string id = "p1", double elapsed = 3, double rate = 1, bool loop = true, double dur = 2,
                                       string role = "a", double ax = 10, double az = 22, double yaw = 0)
        => new(id, "greeting-hug", role, "B", new PairAnchor(ax, az, yaw, null), elapsed, dur, loop, rate);

    [Fact]
    public void AdoptionTakesTheServerClockAndKeepsItBetweenPolls()
    {
        // A new id: clipT = elapsed / rate = 3 / 1 = 3; fresh.
        var p = PairPlay.Adopt(null, Row(), 1, out bool fresh)!;
        Assert.True(fresh);
        Assert.Equal("greeting-hug__a", p.Clip);
        Assert.Equal(3, p.ClipT, 12);
        // Ten frames of 0.05 s: clipT 3.5, elapsed 3.5; the phase wraps at 2 → 1.5.
        double phase = 0;
        for (int i = 0; i < 10; i++) phase = p.Advance(0.05);
        Assert.Equal(3.5, p.ClipT, 12);
        Assert.Equal(1.5, phase, 12);
        // The SAME poll again (1 Hz pass over the cached map): nothing reconciles, the clock keeps 3.5.
        Assert.Same(p, PairPlay.Adopt(p, Row(elapsed: 3), 1, out fresh));
        Assert.False(fresh);
        Assert.Equal(3.5, p.ClipT, 12);
        // A NEW poll 0.2 s off (3.7): within 0.3 → kept; 0.5 s off (4.0) → snapped.
        PairPlay.Adopt(p, Row(elapsed: 3.7), 2, out _);
        Assert.Equal(3.5, p.ClipT, 12);
        PairPlay.Adopt(p, Row(elapsed: 4.0), 3, out _);
        Assert.Equal(4.0, p.ClipT, 12);
        // Another id is a new interaction, adopted whole.
        var q = PairPlay.Adopt(p, Row(id: "p2", elapsed: 1), 4, out fresh)!;
        Assert.True(fresh);
        Assert.NotSame(p, q);
        Assert.Equal(1, q.ClipT, 12);
        // No block: no interaction.
        Assert.Null(PairPlay.Adopt(q, null, 5, out _));
    }

    [Fact]
    public void AFrozenWorldStopsTheClipClockAndRateIsTakenAtOnce()
    {
        var p = PairPlay.Adopt(null, Row(elapsed: 1), 1, out _)!;
        // rate 0 on the SAME stamp still applies at once (a freeze must stop the mixer).
        PairPlay.Adopt(p, Row(elapsed: 1, rate: 0), 1, out _);
        for (int i = 0; i < 5; i++) p.Advance(0.1);
        Assert.Equal(1, p.ClipT, 12);
        Assert.Equal(1, p.Elapsed, 12);
        // rate 2: the game clock runs twice as fast, the CLIP clock in real time (E1): 0.5 s → elapsed +1, clipT +0.5.
        PairPlay.Adopt(p, Row(elapsed: 1, rate: 2), 1, out _);
        for (int i = 0; i < 5; i++) p.Advance(0.1);
        Assert.Equal(1.5, p.ClipT, 12);
        Assert.Equal(2, p.Elapsed, 12);
    }

    [Fact]
    public void PlacementLadderSeatRoomGround()
    {
        var p = PairPlay.Adopt(null, Row(ax: 10, az: 22, yaw: Math.PI / 2), 1, out _)!;
        // yaw π/2: c = 0, s = 1 → root (0.3, 0.1) → (10 + 0.1, 22 − 0.3) = (10.1, 21.7).
        var ground = p.Place((0.3, 0.1), (_, _, _) => 9, (_, _) => 5, (_, _) => 1);
        Assert.Equal(10.1, ground.X, 12);
        Assert.Equal(21.7, ground.Z, 12);
        Assert.Equal(5, ground.Y, 12);   // no place named: the room's stand
        Assert.Equal(1, p.Place((0, 0), (_, _, _) => 9, (_, _) => null, (_, _) => 1).Y, 12);
        p.Anchor = p.Anchor with { PlaceId = "sofa" };
        Assert.Equal(9, p.Place((0, 0), (_, _, _) => 9, (_, _) => 5, (_, _) => 1).Y, 12);
        Assert.Equal(5, p.Place((0, 0), (_, _, _) => null, (_, _) => 5, (_, _) => 1).Y, 12);
    }

    [Fact]
    public void NativeRootPathIsInMetresAlready()
    {
        // Godot's FBX import yields metres (the handshake's constant hips x −0.366742 m = the browser's −36.6742 cm / 100).
        var path = PairClip.ExtractRootPath(new[] { new PairTrack("mixamorig_Hips.position", new float[] { 0 }, new[] { -0.366742f, 1.12f, 0f }) }, 1);
        Assert.Equal(-0.366742, path.Xz[0], 6);
        Assert.Equal(0, path.Xz[1], 12);
    }

    [Fact]
    public void BodyOffsetCentresAndGrounds()
    {
        // A box x 0.1…0.5, y −0.3…0.55, z −0.2…0 at scale 2: centre (0.3, −0.1) → offset (−0.6, 0.6, 0.2).
        var o = FigureBind.Offset(new V3(0.1, -0.3, -0.2), new V3(0.5, 0.55, 0), 2);
        Assert.Equal(-0.6, o.X, 12);
        Assert.Equal(0.6, o.Y, 12);
        Assert.Equal(0.2, o.Z, 12);
    }
}
