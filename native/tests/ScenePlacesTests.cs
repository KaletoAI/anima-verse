using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using AnimaNative.Overview;
using AnimaNative.Scatter;
using AnimaNative.Scene;
using AnimaNative.World;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>
/// The places data of a mount (<see cref="PlaceInventory"/>) and the problems toast (<see cref="SceneProblems"/>). Every
/// expectation is derived by hand in the comments from the browser code: sceneRecipe.ts <c>mountShell</c> (extras → lift
/// stops, <c>stairs</c> → StairWorldLink, vertical targets, corridors, markers), tiles.ts <c>deriveCorridorCentres</c>,
/// sceneRecipe.ts <c>reliftScene</c>, placeSlot.ts <c>slotFor</c>, placeGlyphs.ts <c>glyphRows</c> and main.ts
/// <c>announceSceneProblems</c>.
///
/// The frame: centre (100, 10, 50), yaw 90° → cos 0, sin 1, so tileToWorld(lx, lz, ly) = (100 + lz, 10 + ly, 50 − lx).
/// The ground: g(x, z) = 10 + 0.1·(x − 100) (a slope along world x), so the datum under the pin is 10.
/// </summary>
public class ScenePlacesTests
{
    private static readonly TileFrame Frame = new(new Vec3(100, 10, 50), Math.PI / 2);
    private static double Ground(double x, double z) => 10 + 0.1 * (x - 100);

    private const string Payload = """
    {
      "levels": [{"level": 0, "floor_y": 0}, {"level": 1, "floor_y": 3}],
      "rooms": [{"room_id": "r-a", "level": 0}, {"room_id": "r-b", "level": 1}],
      "plates": [
        {"level": 1, "room_id": "r-b", "outline": [[0,0],[4,0],[4,4]], "top_y": 3.02, "thickness": 0.02},
        {"level": 1, "outline": [[0,0],[4,0],[4,4]], "top_y": 3.0, "thickness": 0.2}
      ],
      "extras": [
        {"kind": "elevator_pad", "center": [1, 0.05, 2], "size": [1, 0.1, 1], "level": 0},
        {"kind": "elevator_pad", "center": [1, 3.05, 2], "size": [1, 0.1, 1], "level": 1},
        {"kind": "elevator_shaft", "center": [1, 1.5, 2], "size": [1, 6, 1]},
        {"kind": "stair_tread", "center": [3, 0.1, -0.3], "size": [1, 0.2, 0.3], "level": 0, "stair": 7},
        {"kind": "stair_tread", "center": [9, 0.1, 9], "size": [1, 0.2, 0.3], "level": 0, "stair": 9}
      ],
      "stairs": [
        {"id": 7, "from_level": 0, "to_level": 1, "at": [3, 0], "dir_deg": 180, "run_m": 1.2, "rise_m": 3, "steps": 4,
         "tread_m": 0.3, "width_m": 1, "foot": [3, 0.01, 0.5], "head": [3, 3.03, -2.5],
         "footprint": [[2.5, 0], [3.5, 0], [3.5, -1.2], [2.5, -1.2]]},
        {"id": 8, "from_level": 0, "to_level": 1, "at": [0, 0], "dir_deg": 0, "run_m": 1, "rise_m": 3, "steps": 4,
         "tread_m": 0.25, "width_m": 1, "foot": [0, 0, 0], "head": [0, 3, 1], "footprint": []}
      ],
      "corridors": [
        {"room_id": "__floor__1", "level": 1, "anchor": [2, -1], "outline": [[0,0],[4,0],[4,4]]},
        {"room_id": "__floor__0", "level": 0, "anchor": [0, 0], "outline": [[0,0],[4,0],[4,4]]},
        {"room_id": "", "level": 1, "anchor": [0, 0], "outline": []}
      ],
      "markers": [
        {"room_id": "r-a", "id": "m1", "group": "seat", "label": "Bench", "capacity": 2, "at_world": [4, 0],
         "slots": [[4, 0.5], [4, -0.5]], "y_world": 0.45, "root_offset": 0.42, "facing": 90, "anchor": [2, -3], "source": "prop"},
        {"room_id": "r-b", "id": "m2", "group": "lie", "label": "Bed", "capacity": 1, "at_world": [1, 1],
         "slots": [[1, 1]], "y_world": 3.5, "source": "room"},
        {"room_id": "r-b", "id": "", "group": "seat", "label": "", "capacity": 1, "at_world": [0, 0],
         "slots": [[0, 0]], "y_world": 3, "source": "room"},
        {"room_id": "r-x", "id": "m3", "group": "stand", "label": "Spot", "capacity": 1, "at_world": [-10, 0],
         "slots": [[-10, 0]], "y_world": 0.2, "source": "room"}
      ],
      "problems": []
    }
    """;

    private static readonly Dictionary<string, string> Names = new() { ["r-a"] = "Hall", ["r-x"] = "Ghost" };

    private static PlaceInventory Compose()
        => PlaceInventory.Compose(ScenePayload.Parse(JsonDocument.Parse(Payload).RootElement), Frame, Names, Ground);

    private static void Near(Vec3 want, Vec3 got)
    {
        Assert.Equal(want.X, got.X, 9);
        Assert.Equal(want.Y, got.Y, 9);
        Assert.Equal(want.Z, got.Z, 9);
    }

    private static void Near(P2 want, P2 got)
    {
        Assert.Equal(want.X, got.X, 9);
        Assert.Equal(want.Z, got.Z, 9);
    }

    [Fact]
    public void LiftStopsAreThePadsTopFacesInTheWorld()
    {
        // elevator_pad level 0: (1, 0.05 + 0.1/2 = 0.1, 2) → (100 + 2, 10 + 0.1, 50 − 1) = (102, 10.1, 49);
        // level 1: (1, 3.05 + 0.05 = 3.1, 2) → (102, 13.1, 49). The shaft has no level and is no stop.
        var inv = Compose();
        Assert.Equal(new[] { 0, 1 }, inv.ElevatorStops.Keys);
        Near(new Vec3(102, 10.1, 49), inv.ElevatorStops[0]);
        Near(new Vec3(102, 13.1, 49), inv.ElevatorStops[1]);
    }

    [Fact]
    public void StairsAreThePayloadsFlightsTurnedIntoTheWorld()
    {
        // foot (3, 0.01, 0.5) → (100.5, 10.01, 47); head (3, 3.03, −2.5) → (97.5, 13.03, 47); at (3, 0) → (100, 47);
        // dir = normalize(head − at) = normalize(−2.5, 0) = (−1, 0) (the payload's dir_deg is not turned);
        // footprint (2.5,0)(3.5,0)(3.5,−1.2)(2.5,−1.2) → (100,47.5)(100,46.5)(98.8,46.5)(98.8,47.5).
        var inv = Compose();
        Assert.Equal(2, inv.Stairs.Count);
        var s = inv.Stairs[0];
        Assert.Equal(7, s.Id);
        Assert.Equal(0, s.Foot.Level);
        Assert.Equal(1, s.Head.Level);
        Near(new Vec3(100.5, 10.01, 47), s.Foot.Pos);
        Near(new Vec3(97.5, 13.03, 47), s.Head.Pos);
        Near(new P2(100, 47), s.At);
        Near(new P2(-1, 0), s.Dir);
        Assert.Equal(1.2, s.RunM);
        Assert.Equal(1, s.WidthM);
        Assert.Equal(4, s.Steps);
        var want = new[] { new P2(100, 47.5), new P2(100, 46.5), new P2(98.8, 46.5), new P2(98.8, 47.5) };
        Assert.Equal(4, s.Footprint.Length);
        for (int i = 0; i < 4; i++) Near(want[i], s.Footprint[i]);
        // Flight 8: head − at = (0+1, 0−0)… at (0,0) → (100, 50), head (0, 3, 1) → (101, 13, 50): dir (1, 0).
        Near(new P2(1, 0), inv.Stairs[1].Dir);
    }

    [Fact]
    public void VerticalTargetsAreTheLiftThenEveryFlightABoxNames()
    {
        // Any elevator_* box → the lift first (flight −1); stairs[0] (id 7) has a stair_* box → flight 0; stairs[1] (id 8)
        // has none; the box naming stair 9 has no flight.
        Assert.Equal(new[] { new VerticalTarget("elevator", -1), new VerticalTarget("stairs", 0) }, Compose().VerticalTargets);
    }

    [Fact]
    public void CorridorsStandOnTheirStoreysOwnPlate()
    {
        // __floor__1: the storey's OWN plate is the one without a room id (top 3.0, not r-b's 3.02) → stand
        // tileToWorld(2, −1, 3.0 + 0.01) = (100 − 1, 13.01, 50 − 2) = (99, 13.01, 48).
        // __floor__0: no level-0 plate → plateTop null → no stand (the ground ladder, E5/E7). The entry without a room is skipped.
        var inv = Compose();
        Assert.Equal(new[] { "__floor__1", "__floor__0" }, inv.Corridors.Select(c => c.RoomId));
        Assert.Equal(3.0, inv.Corridors[0].PlateTop);
        Near(new Vec3(99, 13.01, 48), inv.Corridors[0].Stand!.Value);
        Assert.Null(inv.Corridors[1].PlateTop);
        Assert.Null(inv.Corridors[1].Stand);
        Assert.Equal(new P2(2, -1), inv.Corridors[0].Anchor);
    }

    [Fact]
    public void APropMarkerLiftsAtItsAnchorAndTakesItsRootOffsetOff()
    {
        // m1 (prop): lift point = anchor (2, −3) → world (100 − 3, 50 − 2) = (97, 48); g = 9.7 → lift 9.7 − 10 = −0.3
        // (its own point (4, 0) → (100, 46) would say 0). Slot y = 10 + 0.45 − 0.42 − 0.3 = 9.73;
        // (4, 0.5) → (100.5, 9.73, 46), (4, −0.5) → (99.5, 9.73, 46). Fixed, offsetY 0, drop 0.42, level 0 (r-a).
        var inv = Compose();
        var e = inv.Markers["r-a"]["m1"];
        Assert.True(e.Fixed);
        Assert.Equal(0, e.OffsetY);
        Assert.Equal(0.42, e.Drop, 12);
        Assert.Equal(0, e.Level);
        Assert.Equal(-0.3, e.Lift, 9);
        Near(new P2(97, 48), e.LiftAt);
        Assert.Equal(new P2(2, -3), e.Anchor);
        Assert.Equal(90, e.Rotation);
        Near(new Vec3(100.5, 9.73, 46), e.Slots[0]);
        Near(new Vec3(99.5, 9.73, 46), e.Slots[1]);
    }

    [Fact]
    public void RoomMarkersKeepTheirStoreyOffsetAndAreKeyedByIdAndName()
    {
        var inv = Compose();
        // m2 (room, r-b on storey 1): no terrain lift off storey 0; offsetY = 3.5 − floor_y(1) 3 = 0.5; drop 0;
        // slot (1, 1) at 3.5 → (101, 13.5, 49).
        var m2 = inv.Markers["r-b"]["m2"];
        Assert.False(m2.Fixed);
        Assert.Equal(1, m2.Level);
        Assert.Equal(0, m2.Lift);
        Assert.Equal(0.5, m2.OffsetY, 12);
        Assert.Null(m2.Anchor);
        Near(new Vec3(101, 13.5, 49), m2.Slots[0]);
        // m3 sits in r-x, a room rooms[] does not declare: storey 0 by default, lifted at its own point (−10, 0) →
        // (100, 60), g 10 → lift 0; offsetY 0.2 − 0; slot (100, 10.2, 60). Not keyed by "Ghost" (nameOf holds declared rooms only).
        var m3 = inv.Markers["r-x"]["m3"];
        Assert.Equal(0, m3.Level);
        Near(new Vec3(100, 10.2, 60), m3.Slots[0]);
        // The marker without an id is skipped; r-a hangs under "Hall" too, as ONE map.
        Assert.Equal(new[] { "Hall", "r-a", "r-b", "r-x" }, inv.Markers.Keys.OrderBy(k => k, StringComparer.Ordinal));
        Assert.Same(inv.Markers["r-a"], inv.Markers["Hall"]);
        Assert.Single(inv.Markers["r-b"]);
        Assert.Equal(3, inv.Entries().Count());
    }

    [Fact]
    public void ADatumStepCarriesTheWorldPointsAndTheReliftKeepsThemOnTheGround()
    {
        // The whole field rises by 0.5 and the datum with it (10 → 10.5): stops, landings and PROP seats ride +0.5
        // (stops 10.6 / 13.6, foot 10.51, head 13.53, m1 10.23); the ROOM marker m2 is not carried (13.5 stays — the
        // browser re-derives it from its room's floor, FigureStands); the re-lift then measures m1 at (97, 48):
        // g' = 10.2, datum 10.5 → lift −0.3 = what it carries → no delta → no seat moved. The corridor stand is derived
        // from the new datum: 10.5 + 3.01 = 13.51; the storey-0 one stands on the ground ladder handed in, here
        // g'(anchor (0, 0) → world (100, 50)) = 10.5.
        var inv = Compose();
        var frame = Frame with { Center = new Vec3(100, 10.5, 50) };
        bool seats = inv.Relift(frame, 0.5, (x, z) => Ground(x, z) + 0.5, (x, z) => Ground(x, z) + 0.5);
        Assert.False(seats);
        Assert.Equal(10.6, inv.ElevatorStops[0].Y, 9);
        Assert.Equal(13.6, inv.ElevatorStops[1].Y, 9);
        Assert.Equal(10.51, inv.Stairs[0].Foot.Pos.Y, 9);
        Assert.Equal(13.53, inv.Stairs[0].Head.Pos.Y, 9);
        Assert.Equal(10.23, inv.Markers["Hall"]["m1"].Slots[1].Y, 9);
        Assert.Equal(13.5, inv.Markers["r-b"]["m2"].Slots[0].Y, 9);
        Assert.Equal(-0.3, inv.Markers["r-a"]["m1"].Lift, 9);
        Assert.Equal(13.51, inv.Corridors[0].Stand!.Value.Y, 9);
        Assert.Equal(new Vec3(100, 10.5, 50), inv.Corridors[1].Stand!.Value);
        // Without a ground ladder the storey-0 stand stays unknown.
        inv.DeriveCorridorStands(frame);
        Assert.Null(inv.Corridors[1].Stand);
    }

    [Fact]
    public void ATerrainChangeUnderASeatMovesItInPlace()
    {
        // The datum stays (delta 0), the field rises by 0.2 off the pin: m1 at (97, 48) → g'' = 9.9 → lift −0.1, delta
        // +0.2 → slots 9.73 → 9.93, written into the SAME array a holder keeps; the room markers m3 and m2 are not
        // touched here (their heights are derived from the room floor, FigureStands). Returns true.
        var inv = Compose();
        var held = inv.Markers["r-a"]["m1"].Slots;
        double m3 = inv.Markers["r-x"]["m3"].Slots[0].Y;
        bool seats = inv.Relift(Frame, 0, (x, z) => Ground(x, z) + 0.2);
        Assert.True(seats);
        Assert.Same(held, inv.Markers["r-a"]["m1"].Slots);
        Assert.Equal(9.93, held[0].Y, 9);
        Assert.Equal(9.93, held[1].Y, 9);
        Assert.Equal(-0.1, inv.Markers["r-a"]["m1"].Lift, 9);
        Assert.Equal(m3, inv.Markers["r-x"]["m3"].Slots[0].Y, 9);
        Assert.Equal(13.5, inv.Markers["r-b"]["m2"].Slots[0].Y, 9);
        // A sampler with nothing to say keeps every lift (storeyGroundRelift: NaN → keep).
        Assert.False(inv.Relift(Frame, 0, (x, z) => double.NaN));
        Assert.Equal(9.93, held[0].Y, 9);
    }

    [Fact]
    public void SlotForReadsTheInventory()
    {
        // slotFor: a pair sits on the mean of the slots (100, 9.73, 46); an index out of range falls back to slot 0;
        // an unknown room or place answers nothing.
        var inv = Compose();
        Near(new Vec3(100, 9.73, 46), inv.SlotFor("Hall", "m1", null)!.Value);
        Near(new Vec3(100.5, 9.73, 46), inv.SlotFor("r-a", "m1", 5)!.Value);
        Assert.Null(inv.SlotFor("r-a", "nope", 0));
        Assert.Null(inv.SlotFor("r-q", "m1", 0));
    }

    [Fact]
    public void GlyphRowsComeFromTheInventoryThroughTheVectorCheckedRule()
    {
        // r-a: m1 is a prop marker with an anchor → its mesh is the target, no ring. r-b: m2 free slot 0 → one lie ring
        // (0x8fb3ff) at the slot + 0.03 = (101, 13.53, 49); the avatar's own place is skipped; an unknown room → none.
        var inv = Compose();
        Assert.Empty(inv.GlyphRows("r-a", new[] { new PlaceOffer("m1", "seat", 1, new[] { 1 }) }));
        var rows = inv.GlyphRows("r-b", new[] { new PlaceOffer("m2", "lie", 1, new[] { 0 }) });
        var row = Assert.Single(rows);
        Assert.Equal("m2", row.PlaceId);
        Assert.Equal(PlaceSlots.ColourLie, row.Colour);
        Near(new Vec3(101, 13.53, 49), row.Position);
        Assert.Empty(inv.GlyphRows("r-b", new[] { new PlaceOffer("m2", "lie", 1, new[] { 0 }) }, skipPlaceId: "m2"));
        Assert.Empty(inv.GlyphRows("r-q", new[] { new PlaceOffer("m2", "lie", 1, new[] { 0 }) }));
    }

    [Fact]
    public void AnEmptySceneHasNoPlacesData()
    {
        var inv = PlaceInventory.Compose(ScenePayload.Parse(JsonDocument.Parse("{}").RootElement), Frame, null, null);
        Assert.Empty(inv.Markers);
        Assert.Empty(inv.ElevatorStops);
        Assert.Empty(inv.Stairs);
        Assert.Empty(inv.VerticalTargets);
        Assert.Empty(inv.Corridors);
    }

    [Fact]
    public void ProblemsAreToastedOncePerLocationKindAndRoomNeverEditorOnes()
    {
        // announceSceneProblems: skip scope 'editor'; key `${loc}|${kind}|${room_id ?? ''}`; a spent key is not toasted again.
        var problems = new[]
        {
            new SceneProblem("no_entrance", "Room r-up has no entrance") { RoomId = "r-up", Scope = "editor" },
            new SceneProblem("unreachable_rooms", "2 rooms cannot be reached"),
            new SceneProblem("no_entrance", "Room r-a has no entrance") { RoomId = "r-a" },
            new SceneProblem("no_entrance", "Room r-a has no entrance (again)") { RoomId = "r-a" },
        };
        var spent = new HashSet<string>();
        var first = SceneProblems.Announce("loc-1", problems, spent);
        Assert.Equal(new[] { "loc-1|unreachable_rooms|", "loc-1|no_entrance|r-a" }, first.Select(t => t.Key));
        Assert.Equal("2 rooms cannot be reached", first[0].Message);
        Assert.Equal("[scene] loc-1: unreachable_rooms — 2 rooms cannot be reached", first[0].Log);
        Assert.Empty(SceneProblems.Announce("loc-1", problems, spent));
        Assert.Equal(2, SceneProblems.Announce("loc-2", problems, spent).Count);
        Assert.Empty(SceneProblems.Announce(null, problems, spent));
        Assert.Empty(SceneProblems.Announce("loc-3", null, spent));
        Assert.Equal(4, spent.Count);
    }
}
