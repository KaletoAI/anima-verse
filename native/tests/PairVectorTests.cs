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
/// The adapters of the browser scene's deleted pairVectorDispatch.mjs (Task 32), mirrored for the native ports:
/// <code>
///   TS fn                   C#                                     shape translation
///   pairClipValue           PairClip.Phase                         (PairClipInput, 'clipT' | 'phase')
///   pairSnapS               PairClip.SnapS
///   pairFrames              PairClip.Phase per frame               each frame as Dt (no server value), clock written back
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
        return new PairClipInput(NumOpt(o, "clipS"), NumOpt(o, "tempo") ?? 1, o["frozen"]?.GetValue<bool>() ?? false,
                                 o["loop"]!.GetValue<bool>(), N(o["clipDurationS"]), NumOpt(o, "localClipT"), NumOpt(o, "snapS"),
                                 NumOpt(o, "dt") ?? 0);
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
            Id = "p1", Clip = d["clip"] is { } clip ? Str(clip) : "handshake__a",
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
                result = PairClip.Phase(input with { Dt = N(dt) });
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

/// <summary>shared/test-vectors/group_role_points.json (G3; hand derivations: scripts/smoke_group_role_points.py).</summary>
public class GroupRolePointVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("group_role_points"));
    public static TheoryData<string> Cases => VectorFile.Labels("group_role_points");

    [Theory]
    [MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, PairVectorAdapters.Dispatch);

    [Fact]
    public void EveryFunctionIsDispatched() => Assert.Empty(File.Value.MissingFunctions(PairVectorAdapters.Dispatch));
}

/// <summary>shared/test-vectors/pair_clip_phase.json (hand derivations: native/tests/Derivations/pair_realtime.md).</summary>
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

/// <summary>shared/test-vectors/pair_clip_geometry.json (hand derivations: native/tests/Derivations/clip_pair.md).</summary>
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

/// <summary>shared/test-vectors/pair_height.json (hand derivations: native/tests/Derivations/pair_storey.md).</summary>
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

/// <summary>shared/test-vectors/figure_normalisation.json (hand derivations: native/tests/Derivations/figure_normalisation.md).</summary>
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
    /// <summary>A row whose clip clock is <paramref name="clipS"/> (default: the elapsed — rate-1 rows, where they agree).</summary>
    private static PairInteraction Row(string id = "p1", double elapsed = 3, double rate = 1, bool loop = true, double dur = 2,
                                       string role = "a", double ax = 10, double az = 22, double yaw = 0,
                                       double? clipS = null, double? tempo = null)
        => new(id, "greeting-hug", role, new Dictionary<string, string> { ["a"] = "A", ["b"] = "B" }, new PairAnchor(ax, az, yaw, null), elapsed, dur, loop, rate)
        { ClipS = clipS ?? elapsed, Tempo = PairClip.ClipTempo(tempo) };

    [Fact]
    public void AdoptionTakesTheServerClockAndKeepsItBetweenPolls()
    {
        // A new id: clipT = clip_s = 3; fresh.
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
        // rate 2: the game clock runs twice as fast, the CLIP clock in real time at tempo 1 (E1): 0.5 s → elapsed +1, clipT +0.5.
        PairPlay.Adopt(p, Row(elapsed: 1, rate: 2), 1, out _);
        for (int i = 0; i < 5; i++) p.Advance(0.1);
        Assert.Equal(1.5, p.ClipT, 12);
        Assert.Equal(2, p.Elapsed, 12);
    }

    [Fact]
    public void TheClipClockRunsAtTheSceneTempo()
    {
        // clip_s 2, tempo 0.5: adopted at 2; ten frames of 0.1 s add 1 · 0.5 → 2.5; in a 2 s cycle the phase is 0.5.
        var p = PairPlay.Adopt(null, Row(clipS: 2, tempo: 0.5), 1, out _)!;
        Assert.Equal(0.5, p.Tempo, 12);
        double phase = 0;
        for (int i = 0; i < 10; i++) phase = p.Advance(0.1);
        Assert.Equal(2.5, p.ClipT, 12);
        Assert.Equal(0.5, phase, 12);
        // A new poll, same id: the tempo is taken at once; clip_s 2.7 is 0.2 off → kept, 3.0 is 0.5 off → snapped.
        PairPlay.Adopt(p, Row(clipS: 2.7, tempo: 1), 2, out _);
        Assert.Equal(1, p.Tempo, 12);
        Assert.Equal(2.5, p.ClipT, 12);
        PairPlay.Adopt(p, Row(clipS: 3.0, tempo: 1), 3, out _);
        Assert.Equal(3.0, p.ClipT, 12);
        // Frozen (rate 0): ten frames add nothing.
        PairPlay.Adopt(p, Row(clipS: 3.0, rate: 0), 3, out _);
        for (int i = 0; i < 10; i++) p.Advance(0.1);
        Assert.Equal(3.0, p.ClipT, 12);
        // The tempo is clamped: 5 → 1, 0.05 → 0.2, none → 1 (one 1 s frame each from 0).
        foreach (var (tempo, expected) in new[] { (5.0, 1.0), (0.05, 0.2) })
        {
            var q = PairPlay.Adopt(null, Row(id: $"t{tempo}", clipS: 0, tempo: tempo), 1, out _)!;
            q.Advance(1);
            Assert.Equal(expected, q.ClipT, 12);
        }
        // A pose switch (same id, another clip) is adopted whole from the new clip_s 0; the blend stays.
        p.Blend = (new PairPose(1, 2, 3, 0), 4);
        var switched = PairPlay.Adopt(p, Row(clipS: 0) with { Kind = "greeting-handshake" }, 4, out bool fresh)!;
        Assert.True(fresh);
        Assert.Equal(0, switched.ClipT, 12);
        Assert.Equal(p.Blend, switched.Blend);
    }

    [Fact]
    public void WorldmapRowCarriesClipClockAndTempo()
    {
        using var map = System.Text.Json.JsonDocument.Parse(System.Text.Json.JsonSerializer.Serialize(new { characters = new[] {
            new { name = "B", interaction = new { id = "p1", kind = "greeting-hug", role = "b", alt = "",
                anchor = new { x = 10, z = 22, yaw = 0 }, elapsed_s = 9, clip_s = 1.25, tempo = 0.5, rate = 1, loop = true, clip_duration_s = 2 } }
        }}));
        var it = CharacterRow.ParseList(map.RootElement)[0].Interaction!;
        Assert.Equal(1.25, it.ClipS);
        Assert.Equal(0.5, it.Tempo, 12);
        // The clip clock is clip_s, never elapsed / rate: adopted at 1.25.
        Assert.Equal(1.25, PairPlay.Adopt(null, it, 1, out _)!.ClipT, 12);
    }

    [Fact]
    public void TheSoloSceneHeldClockRunsOnThePlaceBlock()
    {
        // Hand-derived (the browser 3D scene smoke_pair_clip_tempo.mjs [7]): adopt 2.0 at tempo 0.5; dt 1 → 2.5; frozen stays 2.5;
        // the same poll again (clip_s 2.0, 0.5 off) is not reconciled; poll 2: clip_s 2.7 (0.2 off) kept, tempo 0.25;
        // poll 3: clip_s 3.0 (0.5 off) snaps; dt 2 at 0.25 → 3.5; another scene adopts fresh; no block → null.
        using var map = System.Text.Json.JsonDocument.Parse(System.Text.Json.JsonSerializer.Serialize(new { characters = new object[] {
            new { name = "S", place = new { id = "bench", slot = 0, scene_id = "S", clip_s = 2.0, tempo = 0.5 } },
            new { name = "N", place = new { id = "bench", slot = 1 } },
        }}));
        var rows = CharacterRow.ParseList(map.RootElement);
        Assert.Equal(new SoloSceneClock("S", 2.0, 0.5), rows[0].SceneClock);
        Assert.Null(rows[1].SceneClock);
        Assert.Equal(new PlaceRef("bench", 0), rows[0].Place);
        var held = HeldClock.Adopt(null, rows[0].SceneClock, 1)!;
        Assert.Equal(new HeldClock("S", 2.0, 0.5, 1), held);
        held = held.Step(1, false);
        Assert.Equal(2.5, held.ClipT, 12);
        held = held.Step(1, true);
        Assert.Equal(2.5, held.ClipT, 12);
        held = HeldClock.Adopt(held, new SoloSceneClock("S", 2.0, 0.5), 1)!;
        Assert.Equal(2.5, held.ClipT, 12);
        held = HeldClock.Adopt(held, new SoloSceneClock("S", 2.7, 0.25), 2)!;
        Assert.Equal(2.5, held.ClipT, 12);
        Assert.Equal(0.25, held.Tempo, 12);
        held = HeldClock.Adopt(held, new SoloSceneClock("S", 3.0, 0.25), 3)!;
        Assert.Equal(3.0, held.ClipT, 12);
        held = held.Step(2, false);
        Assert.Equal(3.5, held.ClipT, 12);
        Assert.Equal(new HeldClock("T", 0.4, 0.25, 4), HeldClock.Adopt(held, new SoloSceneClock("T", 0.4, 0.25), 4));
        Assert.Null(HeldClock.Adopt(held, null, 5));
        Assert.Equal(1, HeldClock.Adopt(null, new SoloSceneClock("U", 1, 5), 6)!.Tempo, 12);
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

    [Theory]
    [InlineData("wave", "greeting-hug__b~wave")]
    [InlineData("", "greeting-hug__b")]
    public void WorldmapInteractionSelectsAlternativeHalf(string alt, string clip)
    {
        using var map = System.Text.Json.JsonDocument.Parse(System.Text.Json.JsonSerializer.Serialize(new { characters = new[] {
            new { name = "B", interaction = new { id = "p1", kind = "greeting-hug", role = "b", alt,
                anchor = new { x = 10, z = 22, yaw = 0 }, elapsed_s = 3, clip_s = 3, rate = 1, loop = true, clip_duration_s = 2 } }
        }}));
        var row = CharacterRow.ParseList(map.RootElement)[0];
        var play = PairPlay.Adopt(null, row.Interaction, 1, out _)!;
        Assert.Equal(clip, play.Clip);
        Assert.Equal(1, play.Advance(0), 9);
        Assert.Equal(new PairAnchor(10, 22, 0, null), play.Anchor);
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

/// <summary>G2b: <c>interaction.members</c> (role → name, own figure included) replaces <c>partner</c>.</summary>
public class PairMembersTests
{
    private static PairInteraction? Interaction(string members) =>
        CharacterRow.ParseList(System.Text.Json.JsonDocument.Parse(
            "{\"characters\":[{\"name\":\"Bob\",\"location_id\":\"l\",\"interaction\":{\"id\":\"p\",\"kind\":\"greeting-hug\",\"role\":\"b\","
            + members + "\"anchor\":{\"x\":1,\"z\":2,\"yaw\":0}}}]}").RootElement).Single().Interaction;

    [Fact]
    public void MembersCarryEveryRoleIncludingTheOwnFigure()
    {
        var it = Interaction("\"members\":{\"a\":\"Ann\",\"b\":\"Bob\"},")!;
        Assert.Equal(new Dictionary<string, string> { ["a"] = "Ann", ["b"] = "Bob" }, it.Members);
        Assert.Equal("Ann", it.Members.Single(m => m.Key != it.Role).Value);
    }

    [Fact]
    public void MissingOrMalformedMembersAreEmptyAndNonStringNamesDropped()
    {
        Assert.Empty(Interaction("")!.Members);
        Assert.Empty(Interaction("\"members\":[\"Ann\"],")!.Members);
        Assert.Equal(new Dictionary<string, string> { ["b"] = "Bob" }, Interaction("\"members\":{\"a\":7,\"b\":\"Bob\"},")!.Members);
    }
}
