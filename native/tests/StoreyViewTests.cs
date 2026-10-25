using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using AnimaNative.Scatter;
using AnimaNative.Scene;
using AnimaNative.World;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>
/// The storey decisions around the vector-checked cores (<see cref="StoreyView"/>): the level switch, the room labels,
/// the door marks, the locks and the per-frame gates. Every expectation is derived by hand in the comments from the
/// browser code the method names (sceneRecipe.ts mountShell steps 16/17, tiles.ts applyTileFade / applyLevelDisplay,
/// main.ts frame hook / buildDoorMarks, game/doors.ts, game/locks.ts).
/// </summary>
public class StoreyViewTests
{
    private static SceneLevel L(int level, double floorY) => new(level, floorY);

    [Fact]
    public void SwitchExistsOnlyWithMoreThanOneStorey()
    {
        // levels.length > 1
        Assert.False(StoreyView.HasLevelSwitch(new[] { L(0, 0) }));
        Assert.True(StoreyView.HasLevelSwitch(new[] { L(0, 0), L(1, 3) }));
        Assert.False(StoreyView.HasLevelSwitch(new SceneLevel[0]));
    }

    [Fact]
    public void SwitchButtonsAreSortedAscendingWithTheBrowsersLabels()
    {
        // [...levels].sort((a, b) => a - b); 0 → 'G', else `${lv}.` (a basement keeps its minus sign).
        var b = StoreyView.SwitchButtons(new[] { L(1, 3), L(-1, -3), L(0, 0), L(2, 6) });
        Assert.Equal(new[] { -1, 0, 1, 2 }, b.Select(x => x.Level));
        Assert.Equal(new[] { "-1.", "G", "1.", "2." }, b.Select(x => x.Label));
    }

    [Fact]
    public void OnlyALiftAnchorsTheSwitch()
    {
        // A stair box first, then the lift: the lift's centre (x, z) = (4, −1.5); without a lift: null.
        var stair = new SceneExtra("stair_tread", new double[] { -2, 0.1, 2 }, new double[] { 1, 0.2, 0.3 }, null);
        var shaft = new SceneExtra("elevator_shaft", new double[] { 4, 0, -1.5 }, new double[] { 1, 9, 1 }, null);
        var glass = new SceneExtra("elevator_glass", new double[] { 9, 0, 9 }, new double[] { 1, 9, 1 }, null);
        Assert.Equal(new P2(4, -1.5), StoreyView.ElevatorAnchor(new[] { stair, shaft, glass }));
        Assert.Null(StoreyView.ElevatorAnchor(new[] { stair }));
    }

    [Fact]
    public void SwitchFloatsTwoThirdsUpTheShownStorey()
    {
        // storey_m 3 → + 2. Lift at (4, −1.5), storey 1 declared at floor_y 3.2 → (4, 5.2, −1.5).
        var p = StoreyView.SwitchPosition(new P2(4, -1.5), 3.2, 1, 3);
        Assert.Equal(4, p.X, 12);
        Assert.Equal(5.2, p.Y, 12);
        Assert.Equal(-1.5, p.Z, 12);
        // No lift, storey −1 undeclared → (2.2, −1·3 + 2 = −1, 0).
        var q = StoreyView.SwitchPosition(null, null, -1, 3);
        Assert.Equal(2.2, q.X, 12);
        Assert.Equal(-1, q.Y, 12);
        Assert.Equal(0, q.Z, 12);
    }

    [Fact]
    public void RoomHullsTakeTheFloorPlanForStoreyZeroAndTheOutlineForTheRest()
    {
        const string json = """
        { "rooms": [
            { "room_id": "a", "level": 0, "outline": [[9, 9], [10, 9], [10, 10]] },
            { "room_id": "b", "level": 1, "outline": [[0, 0], [4, 0], [4, 2]] },
            { "room_id": "c", "level": -1, "outline": [[0, 0], [1, 0]] } ],
          "floor_plan": [
            { "room_id": "a", "polygon_world": [[-6, -4], [0, -4], [0, 4], [-6, 4]] },
            { "room_id": "d", "polygon_world": [[0, 0], [1, 1]] } ] }
        """;
        using var doc = JsonDocument.Parse(json);
        var hulls = StoreyView.RoomHulls(ScenePayload.Parse(doc.RootElement));
        // a: storey 0 → floor_plan (its own level-0 outline is never read); b: level 1 → outline; c: 2 points → none;
        // d: a 2-point polygon → none.
        Assert.Equal(new[] { "a", "b" }, hulls.Keys.OrderBy(k => k));
        Assert.Equal(new P2(-3, 0), StoreyView.RectCentre(hulls["a"]));   // x −6…0, z −4…4
        Assert.Equal(new P2(2, 1), StoreyView.RectCentre(hulls["b"]));    // x 0…4, z 0…2
        Assert.Null(StoreyView.RectCentre(new P2[0]));
    }

    [Fact]
    public void RoomLabelHangsAtMostOneAndAHalfMetresAboveItsFloor()
    {
        // floorY + min(1.5, 0.8·storey_m): storey 3 → +1.5; storey 1.5 → +1.2; no rect → (0, ·, 0); undeclared → 0.
        var a = StoreyView.RoomLabelPosition(new P2(-3, 0), 3, 3);
        Assert.Equal((-3.0, 4.5, 0.0), (a.X, a.Y, a.Z));
        var b = StoreyView.RoomLabelPosition(null, null, 1.5);
        Assert.Equal(0, b.X, 12);
        Assert.Equal(1.2, b.Y, 12);
        Assert.Equal(0, b.Z, 12);
    }

    private static SceneModelSpec Building(string display)
        => new("building", "b", display, false, new Dictionary<string, string>(), null, 0, 0, 0, 0, 0, 1, "xz", null, 0, 0, 0);

    [Fact]
    public void AreaLocationsShowNoRoomNames()
    {
        // natureSite ∨ !isBuilding ∨ area_detail ∨ a building shown as ground / shell_area.
        Assert.False(StoreyView.AreaLocation(false, true, false, new[] { Building("shell") }));
        Assert.True(StoreyView.AreaLocation(true, true, false, new SceneModelSpec[0]));
        Assert.True(StoreyView.AreaLocation(false, false, false, new SceneModelSpec[0]));
        Assert.True(StoreyView.AreaLocation(false, true, true, new SceneModelSpec[0]));
        Assert.True(StoreyView.AreaLocation(false, true, false, new[] { Building("ground") }));
        Assert.True(StoreyView.AreaLocation(false, true, false, new[] { Building("shell_area") }));
    }

    [Fact]
    public void DoorMarkersKeepTheUsableDoorwaysOfOneStorey()
    {
        const string json = """
        { "doorways": [
            { "level": 0, "at_world": [1, 2], "along": [1, 0], "width_m": 1, "base_y": 0, "rooms": ["a"] },
            { "level": 0, "at_world": [1, 2], "along": [1, 0], "width_m": 0, "rooms": ["a"] },
            { "level": 0, "along": [1, 0], "width_m": 1, "rooms": ["a"] },
            { "level": 1, "at_world": [3, 4], "along": [0, 1], "width_m": 0.9, "base_y": 3.2, "rooms": ["b", "c"] },
            { "level": 0, "at_world": [5, 6], "along": [1, 0], "width_m": 1.2, "rooms": [] } ] }
        """;
        using var doc = JsonDocument.Parse(json);
        var s = ScenePayload.Parse(doc.RootElement);
        // Storey 0: #0 and #4 (#1 has width 0, #2 no at_world); storey 1: #3; storey 2: none.
        Assert.Equal(new[] { 1.0, 5.0 }, StoreyView.DoorMarkers(s.Doorways, 0).Select(d => d.AtWorld.X));
        Assert.Equal(new[] { 0.9 }, StoreyView.DoorMarkers(s.Doorways, 1).Select(d => d.WidthM));
        Assert.Empty(StoreyView.DoorMarkers(s.Doorways, 2));
    }

    [Fact]
    public void MarkDepthIsTheFirstNonPaneWallOfTheStorey()
    {
        var glass = new SceneWall(0, (0, 0), (1, 0), 0, 1, 0.05, true, false, false);
        var leaf = new SceneWall(0, (0, 0), (1, 0), 0, 1, 0.04, false, true, false);
        var wall = new SceneWall(0, (0, 0), (1, 0), 0, 3, 0.25, false, false, false);
        var upper = new SceneWall(1, (0, 0), (1, 0), 0, 3, 0.3, false, false, false);
        Assert.Equal(0.25, StoreyView.DoorMarkThickness(new[] { glass, leaf, wall, upper }, 0));
        Assert.Equal(0.3, StoreyView.DoorMarkThickness(new[] { glass, leaf, wall, upper }, 1));
        Assert.Equal(0, StoreyView.DoorMarkThickness(new[] { glass, leaf }, 0));
    }

    [Fact]
    public void ADoorwayInheritsTheLockOfARoomBehindIt()
    {
        var locks = new Dictionary<string, string> { ["b"] = "Private", ["c"] = "" };
        // a open; b locked with words; c locked without words ("" ≠ null); the avatar's own room is left out.
        Assert.Null(StoreyView.DoorwayLock(new[] { "a" }, locks));
        Assert.Equal("Private", StoreyView.DoorwayLock(new[] { "a", "b" }, locks));
        Assert.Equal("", StoreyView.DoorwayLock(new[] { "c", "b" }, locks));
        Assert.Equal("Private", StoreyView.DoorwayLock(new[] { "c", "b" }, locks, "c"));
        Assert.Null(StoreyView.DoorwayLock(new[] { "b" }, locks, "b"));
        Assert.True(StoreyView.IsLocked(locks, "c"));
        Assert.False(StoreyView.IsLocked(locks, ""));
        Assert.False(StoreyView.IsLocked(null, "b"));
    }

    [Fact]
    public void LocksArePaintedOnlyInTheAvatarsLocation()
    {
        var state = new LockState(new Dictionary<string, string> { ["b"] = "" }, "loc-1", new Dictionary<string, string>(), "a");
        Assert.True(StoreyView.IsLocked(state.RoomsFor("loc-1"), "b"));
        Assert.False(StoreyView.IsLocked(state.RoomsFor("loc-2"), "b"));
    }

    [Fact]
    public void LockStateReadsTheHudsFields()
    {
        // bus.ts: lockedRooms {id: reason}, lockedLoc string, lockedLocations {id: reason}; a null reason is a lock
        // without words; a field of the wrong shape reads empty.
        var rooms = System.Text.Json.Nodes.JsonNode.Parse("{\"b\": \"Private\", \"c\": null}");
        var state = LockState.FromHud(rooms, System.Text.Json.Nodes.JsonValue.Create("loc-1"),
                                      System.Text.Json.Nodes.JsonNode.Parse("[1]"), "a");
        Assert.Equal("Private", state.Rooms["b"]);
        Assert.Equal("", state.Rooms["c"]);
        Assert.Equal("loc-1", state.Loc);
        Assert.Empty(state.Locations);
        Assert.Equal("a", state.AvatarRoom);
        var none = LockState.FromHud(null, null, null, "");
        Assert.Empty(none.Rooms);
        Assert.Equal("", none.Loc);
    }

    [Fact]
    public void FrameGatesFollowTheFadeAndTheFilter()
    {
        // Level display at f > 0.03 (strict), marks/labels at f > 0.5 (strict).
        Assert.False(StoreyView.LevelDisplayActive(0.03));
        Assert.True(StoreyView.LevelDisplayActive(0.0301));
        Assert.False(StoreyView.MarksVisible(0.5));
        Assert.True(StoreyView.MarksVisible(0.51));
        // Slabs on their storey only.
        Assert.True(StoreyView.SlabVisible(-1, -1));
        Assert.False(StoreyView.SlabVisible(1, 0));
        // Outline walls: own storey while the display runs, all of them otherwise (outdoor, closed).
        Assert.True(StoreyView.OutlineWallStoreyVisible(1, 0, false));
        Assert.False(StoreyView.OutlineWallStoreyVisible(1, 0, true));
        Assert.True(StoreyView.OutlineWallStoreyVisible(0, 0, true));
        // Ground model / basement: only a storey below ground with the interior up.
        Assert.True(StoreyView.GroundModelHidden(0.04, -1));
        Assert.False(StoreyView.GroundModelHidden(0.03, -1));
        Assert.False(StoreyView.GroundModelHidden(1, 0));
        Assert.True(StoreyView.BasementOpen(true, 1, -1));
        Assert.False(StoreyView.BasementOpen(false, 1, -1));
        Assert.False(StoreyView.BasementOpen(true, 1, 0));
        Assert.True(StoreyView.HasBasement(new[] { L(-1, -3), L(0, 0) }));
        Assert.False(StoreyView.HasBasement(new[] { L(0, 0), L(1, 3) }));
        // Labels: a tile that cannot open never runs applyTileFade → stays on.
        Assert.True(StoreyView.LabelsOn(false, 0));
        Assert.False(StoreyView.LabelsOn(true, 0.5));
        Assert.True(StoreyView.LabelsOn(true, 0.6));
    }

    [Fact]
    public void RoomNamesComeFromTheDetailRow()
    {
        const string json = """
        { "locations": [ { "id": "l", "name": "L", "rooms": [ { "id": "a", "name": "Hall" }, { "id": "a", "name": "Dup" },
                                                              { "id": "__floor__1", "name": "" }, { "name": "x" } ] } ] }
        """;
        using var doc = JsonDocument.Parse(json);
        var row = LocationInfo.ParseList(doc.RootElement).Single();
        // rooms.find(r => r.id === id): the first "a" wins; an empty name stays "" (no label); no id → no entry.
        Assert.Equal("Hall", row.Rooms["a"]);
        Assert.Equal("", row.Rooms["__floor__1"]);
        Assert.Equal(2, row.Rooms.Count);
    }
}
