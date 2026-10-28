using System;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using AnimaNative.Hud;
using AnimaNative.Overview;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>
/// Task 11, the parts the shared vectors do not reach: the world-map parser behind the name tags and the frame
/// readout of the performance overlay (client3d/src/game/perfstats.ts <c>pushFrame</c>/<c>pushWorstFrame</c> —
/// hand cases mirroring smoke_walk_math.mjs' "perf" section; every expected number is derived in the comment).
/// </summary>
public class TagRowTests
{
    [Fact]
    public void RowsCarryNameActivityTravelAndTheAvatar()
    {
        using var doc = JsonDocument.Parse("""
            { "avatar": "Ada",
              "characters": [
                { "name": "Ada", "activity": "reading", "travel": null },
                { "name": "Bram", "activity": null, "travel": { "starts_in_s": 0, "eta_hhmm": "14:30" } },
                { "name": "Cleo", "travel": { "starts_in_s": 30, "eta_hhmm": "09:00" } },
                { "name": "", "activity": "nameless rows are skipped" },
                "not an object" ] }
            """);
        var (rows, avatar) = OverviewLabels.RowsOf(doc.RootElement);
        Assert.Equal("Ada", avatar);
        Assert.Equal(new[] { "Ada", "Bram", "Cleo" }, rows.Select(r => r.Name));
        // npcs.ts `st.char.activity || ''`: null and absent read as "".
        Assert.Equal(new[] { "reading", "", "" }, rows.Select(r => r.Activity));
        // A JSON null travel is falsy → not under way; Bram is under way with a clock; Cleo's start lies ahead.
        Assert.Equal(new[] { "Ada", "🚶 14:30 Bram", "Cleo" }, rows.Select(r => OverviewLabels.TagName(r.Name, r.Travel)));
    }

    [Fact]
    public void NoAvatarAndNoCharactersAreEmpty()
    {
        using var doc = JsonDocument.Parse("""{ "locations": [] }""");
        var (rows, avatar) = OverviewLabels.RowsOf(doc.RootElement);
        Assert.Empty(rows);
        Assert.Equal("", avatar);
    }

    [Theory]
    // JS truthiness of starts_in_s: NaN cannot come through JSON; a string "0" is truthy, "" falsy, true truthy.
    [InlineData("""{"starts_in_s": "0"}""", false)]
    [InlineData("""{"starts_in_s": ""}""", true)]
    [InlineData("""{"starts_in_s": true}""", false)]
    [InlineData("""{"starts_in_s": false}""", true)]
    [InlineData("""{"starts_in_s": -0.0}""", true)]
    public void StartsInSFollowsJsTruthiness(string travel, bool under)
    {
        using var doc = JsonDocument.Parse($$"""{ "name": "x", "travel": {{travel}} }""");
        Assert.Equal(under, OverviewLabels.TagTravelling(TagTravel.FromJson(doc.RootElement)));
    }
}

public class PerfStatsTests
{
    [Fact]
    public void FpsOverTheLastSecond()
    {
        var m = new FpsMeter();
        Assert.Equal(0, m.Fps);                         // nothing pushed yet
        Assert.Equal(0, m.Push(0));                     // THREE.Clock's first 0 is ignored
        Assert.Equal(0, m.Push(double.NaN));
        // 60 frames of 1/60 s: the sum stays at 1 s (± rounding) → 60 fps.
        for (int i = 0; i < 60; i++) m.Push(1.0 / 60);
        Assert.Equal(60, m.Fps, 6);
        // 30 frames of 1/30 s more: each pushes the oldest 1/60 frames out while the sum exceeds 1 s; after them the
        // window holds the 30 slow frames (1 s) → 30 fps (± the last 1/60 frame left by rounding).
        for (int i = 0; i < 30; i++) m.Push(1.0 / 30);
        Assert.InRange(m.Fps, 29.9, 31.1);
    }

    [Fact]
    public void AFreezeReadsAsItself()
    {
        // pushFrame never empties the window: a 2 s frame alone → 1 / 2 = 0.5 fps.
        var m = new FpsMeter();
        m.Push(1.0 / 60);
        Assert.Equal(0.5, m.Push(2.0), 12);
        Assert.Equal(1, m.Count);
    }

    [Fact]
    public void TheWindowIsCappedAt240Samples()
    {
        // 1000 frames of 1 ms: the sum would allow 1000, the cap keeps 240 → 240 / 0.24 = 1000 fps.
        var m = new FpsMeter();
        for (int i = 0; i < 1000; i++) m.Push(0.001);
        Assert.Equal(240, m.Count);
        Assert.Equal(1000, m.Fps, 6);
    }

    [Fact]
    public void WorstFrameIsTheLargestRawInterval()
    {
        // Stamps 0, 16, 50, 66 ms → intervals 16, 34, 16 → worst 34; the first stamp has no interval.
        var w = new WorstFrame();
        Assert.Equal(0, w.Push(0));
        Assert.Equal(16, w.Push(16));
        Assert.Equal(34, w.Push(50));
        Assert.Equal(34, w.Push(66));
    }

    /// <summary>Task 40: measured stage costs and LOD time must reach the same HUD keys without zeroing.</summary>
    [Fact]
    public void ReadoutPreservesMeasuredScatterSplit()
    {
        var json = PerfReadout.ToJson(new PerfSample(60, 20, 100, 4, 10, 0, 0, 0, 0, 1.25,
            new ScatterCost(2, 7, 70), new ScatterCost(1, 3, 6)));
        Assert.Equal("{\"mesh\":{\"calls\":2,\"instances\":7,\"triangles\":70},\"impostor\":{\"calls\":1,\"instances\":3,\"triangles\":6}}",
            json["scatter"]!.ToJsonString());
        Assert.Equal(1.25, (double)json["scatterLodMs"]!);
    }

    [Fact]
    public void ReadoutHasEveryPerfStatsKey()
    {
        // bus.ts PerfStats: the HUD reads every key (PerfOverlay.tsx calls toFixed on scatterLodMs and on
        // sync.travErrMaxM, so none may be missing or null).
        var json = PerfReadout.ToJson(new PerfSample(59.5, 33, 1200, 40, 5000, 0, 0, 3, 1, 0));
        Assert.Equal(new[] { "fps", "worstFrameMs", "triangles", "calls", "vertices", "geometries", "textures", "tiers",
                             "scatter", "scatterLodMs", "sync" }, json.Select(kv => kv.Key));
        Assert.Equal("""{"full":3,"low":1}""", json["tiers"]!.ToJsonString());
        Assert.Equal("""{"mesh":{"calls":0,"instances":0,"triangles":0},"impostor":{"calls":0,"instances":0,"triangles":0}}""",
                     json["scatter"]!.ToJsonString());
        Assert.Equal(new[] { "posCorr", "pos409", "travBack", "travFwd", "travErrMaxM", "arrive", "place" },
                     ((JsonObject)json["sync"]!).Select(kv => kv.Key));
        var wire = JsonNode.Parse(HudProtocol.Perf(json))!.AsObject();
        Assert.Equal(3, (int)wire["v"]!);
        Assert.Equal("perf", (string)wire["kind"]!);
        Assert.Equal(59.5, (double)wire["value"]!["fps"]!);
        Assert.Equal("""{"v":3,"kind":"perf","value":null}""", HudProtocol.Perf(null));
        Assert.Equal(300, PerfReadout.PublishMs);
        Assert.Equal(1000, PerfReadout.HeavyMs);
    }
}
