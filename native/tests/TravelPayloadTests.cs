using System.Text.Json;
using AnimaNative.Figures;
using AnimaNative.Overview;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>Task 42: travel fields retain nulls and the perf readout carries measured sync counters.</summary>
public class TravelPayloadTests
{
    [Fact]
    public void WholeTravelAndRootSyncAreParsed()
    {
        using var doc = JsonDocument.Parse("""
        {"sync":{"clock_age_ms":300,"build_ms":200},"characters":[{"name":"T","travel":{
        "waypoints":[[0,0],[30,0]],"progress_m":2,"total_m":30,"journey_id":"J","starts_in_s":2,
        "paces_m_s_real":[null,1.4],"pace_m_s_real":1.4,"speed_m_s_real":2,"target_id":"L",
        "target_name":"Home","eta_game":"Y0002-D109T14:00:00","eta_hhmm":"14:00","eta_label":"Summer"}}]}
        """);
        var t = CharacterRow.ParseList(doc.RootElement)[0].Travel!;
        Assert.Equal("J", t.JourneyId); Assert.Equal(30d, t.TotalM); Assert.Equal(2d, t.StartsInS);
        Assert.Equal(new double?[] { null, 1.4 }, t.Paces); Assert.Equal(1.4, t.PaceMSReal); Assert.Equal(2d, t.SpeedMSReal);
        Assert.Equal("L", t.TargetId); Assert.Equal("Home", t.TargetName); Assert.Equal("14:00", t.EtaHhmm);
        Assert.Equal("Summer", t.EtaLabel); Assert.Equal("Y0002-D109T14:00:00", t.EtaGame);
        Assert.Equal(new TravelSync(300, 200), TravelSync.Parse(doc.RootElement));
    }
    [Fact]
    public void ReceiptSurvivesTheBootstrapAndPollRootClones()
    {
        using var raw = JsonDocument.Parse("{\"sync\":{\"clock_age_ms\":300,\"build_ms\":200}}");
        var stamp = new MapReceipt(0, 500, 540);
        using var stamped = stamp.Attach(raw.RootElement);
        var clone = stamped.RootElement.Clone();
        Assert.Equal(stamp, MapReceipt.FromMap(clone));
        Assert.Equal(.49, TravelPath.AgeAtReceiptS(TravelSync.Parse(clone), MapReceipt.FromMap(clone)!.Value), 9);
        Assert.Null(MapReceipt.FromMap(raw.RootElement));
    }
    [Fact]
    public void SyncCountersReachPerfReadout()
    {
        var j = PerfReadout.ToJson(new PerfSample(60, 0, 0, 0, 0, 0, 0, 0, 0, 0, Sync: new TravelCounters(2, 3, 4.5, 6, 7)));
        Assert.Equal(2, j["sync"]!["travBack"]!.GetValue<int>());
        Assert.Equal(3, j["sync"]!["travFwd"]!.GetValue<int>());
        Assert.Equal(4.5, j["sync"]!["travErrMaxM"]!.GetValue<double>());
        Assert.Equal(6, j["sync"]!["arrive"]!.GetValue<int>());
        Assert.Equal(7, j["sync"]!["place"]!.GetValue<int>());
    }
}
