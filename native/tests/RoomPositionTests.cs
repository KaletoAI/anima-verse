using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using AnimaNative.Figures;
using AnimaNative.Overview;
using AnimaNative.Scatter;
using AnimaNative.Scene;
using AnimaNative.Tests.Vectors;
using Xunit;

namespace AnimaNative.Tests;

public class RoomPositionTests
{
    [Fact]
    public void AuthoritativeRoomRejectsStalePointsAndLogsOnceAcrossPolls()
    {
        using var fixture = JsonDocument.Parse(File.ReadAllBytes(Path.Combine(VectorFile.Directory,
            "../../native/fixtures/placement/stale_positions.json")));
        var root = fixture.RootElement;
        Vec3 Point(JsonElement p) => new(p.GetProperty("x").GetDouble(), p.GetProperty("y").GetDouble(), p.GetProperty("z").GetDouble());
        var tile = new PlacementTile
        {
            Frame = new(Point(root.GetProperty("center")), root.GetProperty("yaw").GetDouble()), Fade = 1,
            RoomCenters = root.GetProperty("roomCenters").EnumerateObject().ToDictionary(e => e.Name, e => Point(e.Value)),
            RoomFloors = root.GetProperty("hulls").EnumerateObject().ToDictionary(e => e.Name, e => new RoomFloor
            {
                Hull = e.Value.EnumerateArray().Select(p => new P2(p[0].GetDouble(), p[1].GetDouble())).ToArray(),
            }),
        };
        var lines = new List<string>();
        var diagnostics = new RoomPositionDiagnostics(lines.Add);
        foreach (var c in root.GetProperty("cases").EnumerateArray())
        {
            lines.Clear();
            var p = c.GetProperty("pos");
            for (int poll = 0; poll < 4; poll++)
            {
                var placed = Assert.Single(NpcPlacement.PlaceAtLocation(new[] { new PlacementRow("demo",
                    new P2(p.GetProperty("x").GetDouble(), p.GetProperty("z").GetDouble())) }, tile, new PlacementContext
                {
                    Near = true, RoomOf = _ => "r-bed",
                    RoomStandY = (_, lx, lz) => (64 + lz)/32 + (128 - lx)/64 + .01,
                    StalePos = (name, room, point) => diagnostics.Report("loc-inn", name, room, point),
                }));
                Assert.Equal(c.GetProperty("branch").GetString(), placed.Branch);
                Assert.Equal("r-bed", placed.InRoom);
                var expected = Point(c.GetProperty("expected"));
                Assert.Equal(expected.X, placed.Pos.X, 8);
                Assert.Equal(expected.Y, placed.Pos.Y, 8);
                Assert.Equal(expected.Z, placed.Pos.Z, 8);
            }
            Assert.Equal(c.GetProperty("logs").GetInt32(), lines.Count);
            if (lines.Count > 0) Assert.Contains("outside room r-bed", lines[0]);
        }
    }

    [Fact]
    public void ConcaveRoomRejectsItsNotchOnTheRoomsOwnStorey()
    {
        var tile = new PlacementTile
        {
            Frame = new(default, 0), Fade = 1, LevelFilter = 1,
            RoomCenters = new Dictionary<string, Vec3> { ["upstairs"] = new(1, 7, 1) },
            RoomLevels = new Dictionary<string, int> { ["upstairs"] = 1 },
            RoomFloors = new Dictionary<string, RoomFloor> { ["upstairs"] = new() {
                Hull = new P2[] { new(0,0), new(4,0), new(4,2), new(2,2), new(2,4), new(0,4) } } },
        };
        var placed = Assert.Single(NpcPlacement.PlaceAtLocation(new[] { new PlacementRow("demo", new P2(3,3)) },
            tile, new PlacementContext { RoomOf = _ => "upstairs", RoomStandY = (_,_,_) => 7 }));
        Assert.Equal("centre", placed.Branch);
        Assert.Equal(new Vec3(1,7,1), placed.Pos);
        Assert.False(placed.Hidden);
    }
}
