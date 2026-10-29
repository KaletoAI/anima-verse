using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using AnimaNative.Audio;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>Task 60 / E8-T3: hand-derived driver transitions, fetch lifetime and frame-thread publication.
/// Expectations are literal lists/times; audio.json already covers the shared selection math.</summary>
public class SoundtrackDriverTests
{
    private sealed class Rig
    {
        public double Now, Night;
        public string Mode = "overview", Terrain = "grass";
        public (double X, double Z)? Avatar = (20, 0), Camera = (0, 0);
        public int Fetches;
        public readonly List<(string[] Urls, double Fade)> Music = [], Ambient = [];
        // Task 60: downloads need not inline continuations on the test's synchronization context.
        public readonly TaskCompletionSource<JsonDocument> Reply = new(TaskCreationOptions.RunContinuationsAsynchronously);
        public readonly List<int> PublicationThreads = [];
        public SoundtrackDriver Driver(bool music = true, bool ambient = true) => new(() => Now,
            () => new(Night, Mode, Avatar, Camera), (x, _) => x == 20 ? " Forest " : Terrain,
            () => { Fetches++; return Reply.Task; }, (u, f) => { Music.Add((u, f)); PublicationThreads.Add(Environment.CurrentManagedThreadId); },
            (u, f) => { Ambient.Add((u, f)); PublicationThreads.Add(Environment.CurrentManagedThreadId); }, music, ambient);
        public void Manifest() => Reply.SetResult(JsonDocument.Parse("""
            {"music":{"day":["day-a","day-b"],"night":["night"]},"ambient":{"grass":["grass"],"Forest":["forest"]}}
            """));
    }
    [Fact]
    public void ManifestArrivalReticksBeforeTheNextSecondAndNeverRefetches()
    {
        var r = new Rig(); using var d = r.Driver(); d.Pump(); Assert.Empty(r.Music[^1].Urls);
        r.Now = 50; r.Manifest(); d.Pump(); Assert.Equal(new[] { "day-a", "day-b" }, r.Music[^1].Urls);
        Assert.Equal(4, r.Music[^1].Fade); Assert.Equal(3, r.Ambient[^1].Fade);
        int count = r.Music.Count; r.Now = 999; d.Pump(); Assert.Equal(count, r.Music.Count);
        r.Now = 1000; d.Pump(); Assert.Equal(count + 1, r.Music.Count);
        r.Now = 100000; d.Pump(); d.Tick(); Assert.Equal(1, r.Fetches);
    }
    [Fact]
    public void DayNightChangesUseStrictHysteresis()
    {
        var r = new Rig(); using var d = r.Driver(); r.Manifest(); d.Pump();
        foreach (double f in new[] { .19, .21, .19, .8 }) { r.Night = f; d.Tick(); Assert.Equal("day-a", r.Music[^1].Urls[0]); }
        r.Night = .81; d.Tick(); Assert.Equal(new[] { "night" }, r.Music[^1].Urls);
        foreach (double f in new[] { .79, .21, .2 }) { r.Night = f; d.Tick(); Assert.Equal(new[] { "night" }, r.Music[^1].Urls); }
        r.Night = .19; d.Tick(); Assert.Equal("day-a", r.Music[^1].Urls[0]);
    }
    [Fact]
    public void TerrainHoldIncludesSilenceAndCancelsTransientCandidates()
    {
        var r = new Rig(); using var d = r.Driver(); r.Manifest(); d.Pump(); Assert.Equal(new[] { "grass" }, r.Ambient[^1].Urls);
        r.Now = 1000; r.Camera = (20, 0); d.Tick();
        r.Now = 5999; d.Tick(); Assert.Equal(new[] { "grass" }, r.Ambient[^1].Urls);
        r.Now = 6000; d.Tick(); Assert.Equal(new[] { "forest" }, r.Ambient[^1].Urls);
        r.Camera = null; r.Now = 7000; d.Tick(); r.Now = 12000; d.Tick(); Assert.Empty(r.Ambient[^1].Urls);
        r.Camera = (0, 0); r.Now = 13000; d.Tick(); r.Now = 17999; d.Tick(); Assert.Empty(r.Ambient[^1].Urls);
        r.Now = 18000; d.Tick(); Assert.Equal(new[] { "grass" }, r.Ambient[^1].Urls);
        r.Camera = (20, 0); r.Now = 19000; d.Tick(); r.Camera = (0, 0); r.Now = 20000; d.Tick();
        r.Camera = (20, 0); r.Now = 23000; d.Tick(); r.Now = 24000; d.Tick(); Assert.Equal(new[] { "grass" }, r.Ambient[^1].Urls);
    }
    [Fact]
    public void EmbodiedMissingAvatarNeverFallsBackToCamera()
    {
        var r = new Rig { Mode = "embodied" }; using var d = r.Driver(); r.Manifest(); d.Pump();
        Assert.Equal(new[] { "forest" }, r.Ambient[^1].Urls);
        r.Avatar = null; d.Tick(); r.Now = 5000; d.Tick(); Assert.Empty(r.Ambient[^1].Urls);
    }
    [Fact]
    public void StoredAndLiveSwitchesActImmediatelyWithoutRestartingTerrainHold()
    {
        var r = new Rig(); using var d = r.Driver(false, false); r.Manifest(); d.Pump();
        Assert.Empty(r.Music[^1].Urls); Assert.Empty(r.Ambient[^1].Urls);
        d.SetSwitches(true, true); Assert.Equal("day-a", r.Music[^1].Urls[0]); Assert.Equal(new[] { "grass" }, r.Ambient[^1].Urls);
        int count = r.Music.Count; d.SetSwitches(true, true); Assert.Equal(count, r.Music.Count);
        d.SetSwitches(false, true); Assert.Empty(r.Music[^1].Urls); Assert.Equal(4, r.Music[^1].Fade);
        Assert.Equal(new[] { "grass" }, r.Ambient[^1].Urls);
    }
    [Theory]
    [InlineData("null")]
    [InlineData("{\"music\":{\"day\":[null,7,\"\"]},\"ambient\":[]}")]
    [InlineData("{\"music\":{\"night\":[\"night-only\"]},\"ambient\":{\"water\":[\"water\"]}}")]
    public void MissingMatchingListsStaySilent(string raw)
    {
        var r = new Rig(); using var d = r.Driver(); r.Reply.SetResult(JsonDocument.Parse(raw)); d.Pump();
        Assert.Empty(r.Music[^1].Urls); Assert.Empty(r.Ambient[^1].Urls);
    }
    [Fact]
    public void FailedManifestIsSilenceUntilANewDriverSession()
    {
        var r = new Rig(); using (var d = r.Driver()) { r.Reply.SetException(new Exception("offline")); d.Pump(); r.Now = 99999; d.Pump(); Assert.Empty(r.Music[^1].Urls); Assert.Equal(1, r.Fetches); }
        using var next = r.Driver(); next.Pump(); Assert.Equal(2, r.Fetches);
    }
    [Fact]
    public void BackgroundManifestWaitsForCallerPumpAndPublishesOnThatThread()
    {
        var r = new Rig(); using var d = r.Driver(); d.Pump();
        int caller = Environment.CurrentManagedThreadId, worker = 0;
        int count = r.Music.Count;
        var thread = new Thread(() => { worker = Environment.CurrentManagedThreadId; r.Manifest(); });
        thread.Start(); Assert.True(thread.Join(TimeSpan.FromSeconds(5)), "fixture reply worker did not finish");
        Assert.NotEqual(caller, worker);
        Assert.Equal(count, r.Music.Count);
        d.Pump();
        Assert.Equal(new[] { "day-a", "day-b" }, r.Music[^1].Urls);
        Assert.Equal(new[] { "grass" }, r.Ambient[^1].Urls);
        Assert.All(r.PublicationThreads, id => Assert.Equal(caller, id));
    }
    [Fact]
    public void TeardownReleasesCompletedButUnconsumedManifestDocument()
    {
        var r = new Rig(); var d = r.Driver();
        using var doc = JsonDocument.Parse("{}");
        r.Reply.SetResult(doc); d.Dispose();
        Assert.Throws<ObjectDisposedException>(() => doc.RootElement.ValueKind);
        d.Pump(); Assert.Empty(r.Music); Assert.Empty(r.Ambient);
    }
    [Fact]
    public void LateManifestCannotPublishAfterTeardown()
    {
        var r = new Rig(); var d = r.Driver(); d.Dispose(); r.Manifest(); d.Pump(); d.Tick(); d.SetSwitches(false, false);
        Assert.Empty(r.Music); Assert.Empty(r.Ambient);
    }
}
