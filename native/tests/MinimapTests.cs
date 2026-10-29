using System;
using System.Collections.Generic;
using System.Text.Json;
using System.Text.Json.Nodes;
using AnimaNative.Hud;
using AnimaNative.Scatter;
using AnimaNative.World;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>Task 55 / E7-T10: state/wire regressions against hand-sized terrain and known-place payloads.
/// Catches reversed paint order, base64 relief, cadence/anchor/yaw drift, stale dots/bounds and rebuilds on a step.</summary>
public class MinimapTests
{
    private static JsonElement Parse(string s) { using var d = JsonDocument.Parse(s); return d.RootElement.Clone(); }
    private static JsonElement Map => Parse("""
        {"locations":[{"id":"a","name":"Known","pos_x":1,"pos_z":2},
        {"id":"unplaced","pos_x":null,"pos_z":2},{"id":"b","name":"","pos_x":3,"pos_z":4}],
        "world_bounds":{"min_x":-10,"max_x":30,"min_z":-5,"max_z":5}}
        """);
    private static TerrainPayload Terrain => TerrainPayload.Parse(Parse("""
        {"types":[{"kind":"MeAdOw","color":"#123456"}],"areas":[
        {"id":"bottom","kind":" MEADOW ","polygon":[[0,0],[2,0],[0,2]]},
        {"id":"top","kind":"unknown","polygon":[[1,1],[3,1],[1,3]]}]}
        """));
    private static WorldHeight Heights => new(HeightfieldOverview.Parse(Parse("""
        {"origin_x":-2,"origin_z":-4,"step_m":2,"heights":[[0,1],[1,2]]}
        """)));

    [Fact]
    public void WireCarriesSixFieldsPaintOrderKnownDotsAndNumericRgba()
    {
        var p = new MinimapProducer();
        Assert.True(p.Tick(.25, true, Terrain, Heights, Map, new(0, 0), Math.PI / 2));
        using var d = JsonDocument.Parse(HudProtocol.Minimap(p.State));
        var root = d.RootElement;
        Assert.Equal(3, root.GetProperty("v").GetInt32());
        Assert.Equal("minimap", root.GetProperty("kind").GetString());
        var s = root.GetProperty("value");
        int fields = 0; foreach (var _ in s.EnumerateObject()) fields++;
        Assert.Equal(6, fields);
        Assert.Equal("#123456", s.GetProperty("areas")[0].GetProperty("color").GetString());
        Assert.Equal("#888888", s.GetProperty("areas")[1].GetProperty("color").GetString());
        Assert.Equal(1, s.GetProperty("areas")[1].GetProperty("polygon")[0][0].GetInt32());
        Assert.Equal(2, s.GetProperty("locations").GetArrayLength());
        Assert.Equal("b", s.GetProperty("locations")[1].GetProperty("name").GetString());
        Assert.Equal(0, s.GetProperty("avatar").GetProperty("x").GetDouble());
        Assert.Equal(Math.PI / 2, s.GetProperty("yaw").GetDouble(), 10);
        Assert.Equal(30, s.GetProperty("bounds").GetProperty("max_x").GetDouble());
        var relief = s.GetProperty("relief");
        Assert.Equal(-2, relief.GetProperty("origin_x").GetDouble());
        Assert.Equal(-4, relief.GetProperty("origin_z").GetDouble());
        Assert.Equal(2, relief.GetProperty("step_m").GetDouble());
        var rgba = relief.GetProperty("image").GetProperty("data");
        Assert.Equal(JsonValueKind.Array, rgba.ValueKind);
        Assert.Equal(16, rgba.GetArrayLength());
        Assert.Equal(170, rgba[0].GetInt32());
        Assert.Equal(81, rgba[3].GetInt32());
    }

    [Fact]
    public void CadenceAnchorAndYawGateWhileStepsReuseReliefJson()
    {
        var p = new MinimapProducer(); var terrain = Terrain; var height = Heights; var map = Map;
        Assert.False(p.Tick(.249, true, terrain, height, map, new(0, 0), 0));
        Assert.True(p.Tick(.001, true, terrain, height, map, new(0, 0), 0));
        var relief = p.State!.ReliefJson;
        // 40m world -> radius20 -> .6 * 40 / 160 = .15m, inclusive dead zone.
        Assert.False(p.Tick(.25, true, terrain, height, map, new(.15, 0), .4 * Math.PI / 180));
        Assert.True(p.Tick(.25, true, terrain, height, map, new(.151, 0), .5 * Math.PI / 180));
        Assert.Equal(.151, p.State!.Avatar!.Value.X);
        Assert.Equal(Math.PI / 180, p.State.Yaw, 10);
        Assert.Same(relief, p.State.ReliefJson);
        Assert.True(p.Tick(.25, true, terrain, height, map, new(.151, 0), -.5 * Math.PI / 180));
        Assert.Equal(0, p.State!.Yaw);
        height.Reset(Heights.Overview);
        Assert.True(p.Tick(.25, true, terrain, height, map, new(.151, 0), 0));
        Assert.NotSame(relief, p.State!.ReliefJson);
        var changedRelief = p.State.ReliefJson;
        Assert.True(p.Tick(.25, false, terrain, height, map, null, 0));
        Assert.Null(p.State);
        Assert.Equal("{\"v\":3,\"kind\":\"minimap\",\"value\":null}", HudProtocol.Minimap(null));
        Assert.False(p.Tick(.25, false, terrain, height, map, null, 0));
        Assert.True(p.Tick(.25, true, terrain, height, map, new(5, 5), 0));
        Assert.Equal(5, p.State!.Avatar!.Value.X);
        Assert.Same(changedRelief, p.State.ReliefJson);
    }

    [Fact]
    public void LateHeightsMovedLocationsBoundsAndMissingAvatarInvalidate()
    {
        var p = new MinimapProducer(); var terrain = Terrain; var map = Map;
        Assert.True(p.Tick(.25, true, terrain, null, map, null, 0));
        Assert.Null(p.State!.Avatar);
        using (var d = JsonDocument.Parse(HudProtocol.Minimap(p.State)))
            Assert.Equal(JsonValueKind.Null, d.RootElement.GetProperty("value").GetProperty("relief").ValueKind);
        var height = Heights;
        Assert.True(p.Tick(.25, true, terrain, height, map, null, 0));
        var next = JsonNode.Parse(map.GetRawText())!;
        next["locations"]![0]!["pos_x"] = 8;
        Assert.True(p.Tick(.25, true, terrain, height, Parse(next.ToJsonString()), null, 0));
        Assert.Equal(8, p.State!.Locations[0]!["x"]!.GetValue<double>());
        next["world_bounds"]!["max_x"] = 50;
        Assert.True(p.Tick(.25, true, terrain, height, Parse(next.ToJsonString()), null, 0));
        Assert.Equal(50, p.State!.Bounds!.Value.MaxX);
        Assert.True(p.Tick(.25, true, Terrain, height, Parse(next.ToJsonString()), new(0, 0), 0));
        Assert.True(p.Tick(.25, true, terrain, height, Parse(next.ToJsonString()), null, 0));
        Assert.Null(p.State!.Avatar);
    }

    [Fact]
    public void SixtyHzFramesPublishOnlyOncePerQuarterSecond()
    {
        var p = new MinimapProducer(); var terrain = Terrain; var height = Heights; var map = Map;
        var frames = new List<int>();
        for (int frame = 1; frame <= 60; frame++)
            if (p.Tick(1.0 / 60, true, terrain, height, map, new(frame, 0), 0)) frames.Add(frame);
        Assert.Equal(new[] { 15, 30, 45, 60 }, frames);
    }

    [Fact]
    public void LargeNumericReliefIsReusedAcrossStepMessages()
    {
        // 201x151 points, decimated for the bridge (P3-R28): k = ceil(201 / 192) = 2 -> 101 x 76 points = 30704 RGBA
        // channels, still a large (>60 KB) numeric fragment that must be reused, never rebuilt, across steps.
        var rows = new JsonArray();
        for (int j = 0; j < 151; j++)
        {
            var row = new JsonArray();
            for (int i = 0; i < 201; i++) row.Add(i + j);
            rows.Add(row);
        }
        var field = new JsonObject { ["step_m"] = 2, ["heights"] = rows };
        var height = new WorldHeight(HeightfieldOverview.Parse(Parse(field.ToJsonString())));
        var p = new MinimapProducer(); var terrain = Terrain; var map = Map;
        Assert.True(p.Tick(.25, true, terrain, height, map, new(0, 0), 0));
        var relief = p.State!.ReliefJson;
        Assert.True(relief.Length > 60000);
        using (var r = JsonDocument.Parse(relief))
        {
            Assert.Equal(101, r.RootElement.GetProperty("image").GetProperty("cols").GetInt32());
            Assert.Equal(76, r.RootElement.GetProperty("image").GetProperty("rows").GetInt32());
            Assert.Equal(4, r.RootElement.GetProperty("step_m").GetDouble());
        }
        for (int step = 1; step <= 3; step++)
        {
            Assert.True(p.Tick(.25, true, terrain, height, map, new(step, 0), 0));
            Assert.Same(relief, p.State!.ReliefJson);
            using var wire = JsonDocument.Parse(HudProtocol.Minimap(p.State));
            var value = wire.RootElement.GetProperty("value");
            Assert.Equal(step, value.GetProperty("avatar").GetProperty("x").GetDouble());
            var data = value.GetProperty("relief").GetProperty("image").GetProperty("data");
            Assert.Equal(30704, data.GetArrayLength());   // 101 × 76 × 4; same slope (0.5 m/m) → same shade at pixel 0
            Assert.Equal(170, data[0].GetInt32()); Assert.Equal(81, data[3].GetInt32());
        }
    }

    [Fact]
    public void EmptyWorldAndInvalidHeightGridHaveNullReliefAndBounds()
    {
        var p = new MinimapProducer();
        var empty = new WorldHeight(HeightfieldOverview.Parse(Parse("{\"step_m\":1,\"heights\":[]}")));
        Assert.True(p.Tick(.25, true, null, empty, Parse("{}"), new(0, 0), 0));
        Assert.Null(p.State!.Bounds);
        Assert.Empty(p.State.Areas);
        Assert.Empty(p.State.Locations);
        Assert.Equal("null", p.State.ReliefJson);
    }

    /// <summary>
    /// Ruling P3-R28: the bridge carries at most 192 px per relief edge. A 521 × 198 overview (the user world) at 16 m:
    /// k = ceil(521 / 192) = 3 → cols = ceil(521 / 3) = 174, rows = ceil(198 / 3) = 66, step 48 m, origin unchanged,
    /// sample (i, j) = source (3i, 3j). A 160 × 90 field passes unchanged (same instance).
    /// </summary>
    [Fact]
    public void ReliefIsDecimatedForTheBridge()
    {
        var heights = new float[521 * 198];
        for (int j = 0; j < 198; j++) for (int i = 0; i < 521; i++) heights[j * 521 + i] = i + 1000 * j;
        var big = new HeightGrid(-4000, -1500, 16, 198, 521, heights);
        var wire = AnimaNative.Hud.MinimapProducer.ForWire(big)!;
        Assert.Equal(174, wire.Cols);
        Assert.Equal(66, wire.Rows);
        Assert.Equal(48, wire.Step);
        Assert.Equal(-4000, wire.OriginX);
        Assert.Equal(-1500, wire.OriginZ);
        Assert.Equal(3 + 1000 * 3, wire.At(1, 1));
        Assert.Equal(519 + 1000 * 195, wire.At(173, 65));
        var small = new HeightGrid(0, 0, 16, 90, 160, new float[160 * 90]);
        Assert.Same(small, AnimaNative.Hud.MinimapProducer.ForWire(small));
    }
}
