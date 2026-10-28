using System.Text.Json;
using AnimaNative.Scatter;
using AnimaNative.Ground;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>Task 39: payload, epoch and footprint regressions beyond the unchanged geometry vectors.</summary>
public class ScatterPlacementTests
{
    [Fact]
    public void PayloadReadsStrokeRowsAndPlacementOptions()
    {
        using var doc = JsonDocument.Parse("""
        {"areas":[{"id":"road","kind":"street","polygon":[[0,0],[20,0],[20,4],[0,4]],"meta":{
          "stroke":{"points":[[0,2],[20,2]],"width_m":4,"style":"wavy","along":[{"model":"lamp","spacing_m":5,"offset_m":3,"side":"both","start_m":1,"spacing_jitter_m":2,"reshuffle_min":120}]},
          "scatter":[{"place":"edge","offset_m":0.8,"spacing_jitter_m":5,"sides":"opposite","reshuffle_min":120}]}}]}
        """);
        var t = TerrainPayload.Parse(doc.RootElement); var a = Assert.Single(t.Areas);
        Assert.NotNull(a.Stroke); Assert.Equal("wavy", a.Stroke!.Style);
        var along = Assert.Single(a.Along);
        Assert.Equal(5, along.SpacingM); Assert.Equal(3, along.OffsetM); Assert.Equal("both", along.Side); Assert.Equal(1, along.StartM);
        var edge = Assert.Single(a.Scatter);
        Assert.Equal(0.8, edge.OffsetM); Assert.Equal(5, edge.SpacingJitterM); Assert.Equal("opposite", edge.Sides);
        Assert.Equal(t.EpochSignature(14465), t.EpochSignature(21599));
        Assert.NotEqual(t.EpochSignature(14465), t.EpochSignature(21665));
        Assert.Contains("road/a0:2", t.EpochSignature(14465)); Assert.Contains("road/s0:2", t.EpochSignature(14465));
    }
    [Fact]
    public void LayerMaskSnapshotOwnsBothByteArraysAndFormat()
    {
        var mask = new LayerMaskWindow { OriginX = -64, OriginZ = 0, IdSize = 1, IdStep = 64,
            SdSize = 1, SdStep = 64, SdZero = 128, SdCodesPerM = 8, SdBandM = 16,
            Id = new byte[] { 2, 2 }, Sd = new byte[] { 128 } };
        var frozen = mask.Snapshot();
        mask.Id[0] = 3; mask.Id[1] = 3; mask.Sd[0] = 255; mask.OriginX = 999;
        Assert.Equal(2, LayerCut.TopLayerAt(frozen, -30, 20));
        Assert.Equal(-64, frozen.OriginX); Assert.Equal(128, frozen.Sd[0]);
        Assert.Equal(64, frozen.IdStep); Assert.Equal(8, frozen.SdCodesPerM);
    }

    [Fact]
    public void FootprintSignatureChangesForMovesTurnsAndBoundaryEdits()
    {
        string Sig(string row) { using var d = JsonDocument.Parse("{\"locations\":[" + row + "]}"); return TerrainPayload.FootprintSignature(d.RootElement); }
        const string start = "{\"id\":\"house\",\"pos_x\":0,\"pos_z\":0,\"boundary\":[[0,0],[4,0],[4,4],[0,4]],\"yaw_deg\":0}";
        Assert.Equal(Sig(start), Sig(start.Replace("\"id\":\"house\"", "\"label\":\"renamed\",\"id\":\"house\"")));
        Assert.NotEqual(Sig(start), Sig(start.Replace("\"pos_x\":0", "\"pos_x\":10")));
        Assert.NotEqual(Sig(start), Sig(start.Replace("\"yaw_deg\":0", "\"yaw_deg\":90")));
        Assert.NotEqual(Sig(start), Sig(start.Replace("[4,4]", "[5,4]")));
    }
}
