using System.Text.Json;
using AnimaNative.Embody;
using AnimaNative.World;
using Xunit;

namespace AnimaNative.Tests;

public sealed class EntryRulesTests
{
    [Fact]
    public void EntryToleranceParseReadsPresentKeysAndDefaultsMissingToZero()
    {
        using var present = JsonDocument.Parse(
            "{\"door_tolerance\":{\"along_pad_m\":0.3,\"across_m\":1.5},\"gate_tolerance_m\":1.5}");
        var tol = EntryTolerance.Parse(present.RootElement);
        Assert.Equal(0.3, tol.AlongPadM);
        Assert.Equal(1.5, tol.AcrossM);
        Assert.Equal(1.5, tol.GateM);

        using var missing = JsonDocument.Parse("{\"max_step_height_m\":0.4}");
        var zero = EntryTolerance.Parse(missing.RootElement);
        Assert.Equal(0, zero.AlongPadM);
        Assert.Equal(0, zero.AcrossM);
        Assert.Equal(0, zero.GateM);
    }

    [Fact]
    public void LocationInfoParsesFencedGatesAndDoorsWithPlainDefaults()
    {
        using var doc = JsonDocument.Parse("""
        {
          "locations": [
            {
              "id": "loc-a",
              "name": "Hall",
              "pos_x": 10,
              "pos_z": 20,
              "yaw_deg": 90,
              "fenced": true,
              "openings": [
                { "edge": 2, "at_world": [13, 24], "inward": [0, -1] }
              ],
              "doors": [
                { "x": 13, "z": 24, "out_x": 0, "out_z": 1, "width_m": 1.2, "room": "r-b", "level": 0 }
              ]
            },
            {
              "id": "loc-b",
              "name": "Meadow",
              "pos_x": 30,
              "pos_z": 40,
              "yaw_deg": 0
            }
          ]
        }
        """);
        var list = LocationInfo.ParseList(doc.RootElement);
        Assert.Equal(2, list.Count);

        var a = list[0];
        Assert.True(a.Fenced);
        var gate = Assert.Single(a.Gates);
        Assert.Equal(2, gate.Edge);
        Assert.Equal(13, gate.AtWorld.X);
        Assert.Equal(24, gate.AtWorld.Z);
        Assert.Equal(0, gate.Inward.X);
        Assert.Equal(-1, gate.Inward.Z);
        var door = Assert.Single(a.Doors);
        Assert.Equal(13, door.X);
        Assert.Equal(24, door.Z);
        Assert.Equal(0, door.OutX);
        Assert.Equal(1, door.OutZ);
        Assert.Equal(1.2, door.WidthM);
        Assert.Equal("r-b", door.Room);
        Assert.Equal(0, door.Level);

        var b = list[1];
        Assert.False(b.Fenced);
        Assert.Empty(b.Gates);
        Assert.Empty(b.Doors);
    }

    [Fact]
    public void EntryWorldParseReadsLocationsTolerancesAndDefaults()
    {
        using var fullDoc = JsonDocument.Parse("""
        {
          "max_step_height_m": 0.55,
          "max_slope_deg": 35,
          "door_tolerance": { "along_pad_m": 0.3, "across_m": 1.5 },
          "gate_tolerance_m": 1.5,
          "locations": [
            {
              "id": "loc-a",
              "name": "Hall",
              "pos_x": 0,
              "pos_z": 0,
              "yaw_deg": 0,
              "fenced": true,
              "openings": [{ "edge": 2, "at_world": [3, 4], "inward": [0, -1] }],
              "doors": [{ "x": 3, "z": 4, "out_x": 0, "out_z": 1, "width_m": 1.2, "room": "r-b", "level": 0 }]
            },
            {
              "id": "loc-b",
              "name": "Meadow",
              "pos_x": 20,
              "pos_z": 0,
              "yaw_deg": 0,
              "fenced": false,
              "openings": [],
              "doors": []
            }
          ]
        }
        """);
        var world = EntryWorld.Parse(fullDoc.RootElement);
        Assert.Equal(0.55, world.MaxStepM);
        Assert.Equal(35, world.MaxSlopeDeg);
        Assert.Equal(0.3, world.Tolerance.AlongPadM);
        Assert.Equal(1.5, world.Tolerance.AcrossM);
        Assert.Equal(1.5, world.Tolerance.GateM);
        Assert.True(world.Fenced("loc-a"));
        Assert.Single(world.Gates("loc-a"));
        Assert.Single(world.Doors("loc-a"));
        Assert.False(world.Fenced("loc-b"));
        Assert.Empty(world.Gates("loc-b"));
        Assert.Empty(world.Doors("loc-b"));
        Assert.False(world.Fenced("unknown"));
        Assert.Empty(world.Gates("unknown"));
        Assert.Empty(world.Doors("unknown"));

        using var minimalDoc = JsonDocument.Parse("{\"locations\":[]}");
        var minimal = EntryWorld.Parse(minimalDoc.RootElement);
        Assert.Equal(0.4, minimal.MaxStepM);
        Assert.Equal(40, minimal.MaxSlopeDeg);
        Assert.Equal(0, minimal.Tolerance.AlongPadM);
        Assert.Equal(0, minimal.Tolerance.AcrossM);
        Assert.Equal(0, minimal.Tolerance.GateM);
    }
}
