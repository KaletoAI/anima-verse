using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using AnimaNative.Audio;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>Task 59: hand-derived lifecycle cases, independent of shared vectors and of Godot's audio driver.</summary>
public class AudioScheduleTests
{
    private sealed record Clip(double Duration) : IAudioClip;
    private sealed class Player : IAudioPlayback
    {
        public double Gain; public bool Stopped; public bool Started;
        public void Start(IAudioClip clip, double gain) { Started = true; Gain = gain; }
        public void SetGain(double gain) => Gain = gain;
        public void Stop() => Stopped = true;
    }
    private sealed class Rig
    {
        public double Now = 10;
        public List<Player> Players = [];
        public List<(string Url, bool Cache)> Loads = [];
        public List<string> Logs = [];
        public Func<string, Task<IAudioClip>> Fetch = _ => Task.FromResult<IAudioClip>(new Clip(9));
        public Task<IAudioClip> Load(string url, bool cache) { Loads.Add((url, cache)); return Fetch(url); }
        public IAudioPlayback Player() { var p = new Player(); Players.Add(p); return p; }
        public PlaylistSchedule Playlist() => new(() => Now, Load, Player, Logs.Add);
        public SpeechQueue Speech() => new(() => Now, Load, Player, Logs.Add);
    }
    [Fact]
    public void SpeechCompletionWaitsForEndAndSettlesAllDroppedOrStoppedLines()
    {
        var r = new Rig { Fetch = _ => Task.FromResult<IAudioClip>(new Clip(1)) };
        var s = r.Speech();
        var first = s.Speak("first"); var dropped = s.Speak("oldest");
        var a = s.Speak("a"); var b = s.Speak("b"); var c = s.Speak("c");
        Assert.True(dropped.IsCompletedSuccessfully);
        Assert.False(first.IsCompleted); s.Tick(); Assert.False(first.IsCompleted);
        r.Now = 11; s.Tick(); Assert.True(first.IsCompletedSuccessfully); Assert.False(a.IsCompleted);
        s.Stop(); Assert.All(new[] { a, b, c }, t => Assert.True(t.IsCompletedSuccessfully));
        Assert.True(s.Speak("").IsCompletedSuccessfully);
    }

    [Fact]
    public void FailedAndAbandonedSpeechCompletesWithoutWaitingForDownload()
    {
        var late = new TaskCompletionSource<IAudioClip>();
        var r = new Rig { Fetch = url => url == "late" ? late.Task : Task.FromException<IAudioClip>(new Exception("bad")) };
        var s = r.Speech(); var bad = s.Speak("bad"); s.Tick(); Assert.True(bad.IsCompletedSuccessfully);
        var pending = s.Speak("late"); s.Stop(); Assert.True(pending.IsCompletedSuccessfully);
        late.SetResult(new Clip(1)); s.Tick(); Assert.Empty(r.Players);
    }

    [Fact]
    public void PlaylistUsesCappedFadePiecewiseGainsAndStartsNextAtSeam()
    {
        var r = new Rig(); var p = r.Playlist(); p.Play(["a"], 4); p.Tick();
        var first = Assert.Single(p.Live);
        Assert.Equal(new TrackTiming(10, 3, 16, 0), first.Timing);
        r.Now = 10.1875; p.Tick(); Assert.Equal(.09754516100806413, r.Players[0].Gain, 12);
        r.Now = 11.5; p.Tick(); Assert.Equal(.7071067811865476, r.Players[0].Gain, 12);
        r.Now = 15.99; p.Tick(); Assert.Single(r.Players);
        r.Now = 16; p.Tick(); Assert.Equal(2, r.Players.Count);
        Assert.Equal(16, p.Live[1].Timing.Begin);
        r.Now = 17.5; p.Tick(); Assert.Equal(.7071067811865476, r.Players[0].Gain, 12);
        Assert.Equal(.7071067811865476, r.Players[1].Gain, 12);
        r.Now = 19; p.Tick(); Assert.True(r.Players[0].Stopped);
        Assert.All(r.Loads, load => Assert.True(load.Cache));
    }
    [Fact]
    public void PreloadWaitsUntilSeamMinusSixAndSameListIsNoOp()
    {
        var r = new Rig { Fetch = _ => Task.FromResult<IAudioClip>(new Clip(18)) };
        var p = r.Playlist(); p.Play(["a"], 4); p.Tick();
        p.Play(["a"], 1, "changed seed");
        r.Now = 17.99; p.Tick(); Assert.Single(r.Loads);
        r.Now = 18; p.Tick(); Assert.Equal(2, r.Loads.Count);
        r.Now = 24; p.Tick(); Assert.Equal(24, p.Live[1].Timing.Begin);
    }
    [Fact]
    public void EmptyListStopsLinearlyAndDoesNotStartPreloadedTrack()
    {
        var r = new Rig(); var p = r.Playlist(); p.Play(["a"], 4); p.Tick();
        r.Now = 13; p.Tick(); p.Play([], 4);
        Assert.Equal("", p.Key);
        r.Now = 15; p.Tick(); Assert.Equal(.5, r.Players[0].Gain, 12);
        r.Now = 17; p.Tick(); Assert.True(r.Players[0].Stopped); Assert.Single(r.Players);
    }
    [Fact]
    public void BrokenTrackSkipsOnceAndAllBrokenStopsTrying()
    {
        var r = new Rig { Fetch = u => u == "bad" ? Task.FromException<IAudioClip>(new Exception("broken")) : Task.FromResult<IAudioClip>(new Clip(9)) };
        var p = r.Playlist(); p.Play(["bad", "good"], 4, "a"); p.Tick();
        Assert.Equal("good", Assert.Single(p.Live).Url); Assert.Single(r.Logs);
        p.Play(["bad"], 4); p.Tick(); int attempts = r.Loads.Count;
        r.Now = 100; p.Tick(); Assert.Equal(attempts, r.Loads.Count); Assert.Empty(p.Live);
    }
    [Fact]
    public void LatePlaylistLoadCannotSurviveStopOrSwitch()
    {
        var slow = new TaskCompletionSource<IAudioClip>();
        var r = new Rig { Fetch = u => u == "old" ? slow.Task : Task.FromResult<IAudioClip>(new Clip(9)) };
        var p = r.Playlist(); p.Play(["old"]); p.Tick(); p.Play(["new"]); p.Tick();
        slow.SetResult(new Clip(9)); p.Tick(); Assert.Equal("new", Assert.Single(p.Live).Url);
        Assert.Single(r.Players);
    }
    [Fact]
    public void SpeechIsSerialDropsOldestWaitingAndStopSilencesImmediately()
    {
        var r = new Rig { Fetch = _ => Task.FromResult<IAudioClip>(new Clip(1)) }; var s = r.Speech();
        s.Speak("a"); s.Tick(); foreach (var u in new[] { "b", "c", "d", "e" }) s.Speak(u);
        Assert.Equal(new[] { "c", "d", "e" }, s.Pending);
        r.Now = 11; s.Tick(); Assert.Equal("c", s.CurrentUrl); Assert.True(r.Players[0].Stopped);
        Assert.All(r.Loads, load => Assert.False(load.Cache));
        s.Stop(); Assert.Null(s.CurrentUrl); Assert.Empty(s.Pending); Assert.True(r.Players[1].Stopped);
        r.Now = 50; s.Tick(); Assert.Equal(2, r.Players.Count);
    }
    [Fact]
    public void StoppedSpeechDownloadNeverStartsAndFreshQueueRuns()
    {
        var slow = new TaskCompletionSource<IAudioClip>();
        var r = new Rig { Fetch = u => u == "old" ? slow.Task : Task.FromResult<IAudioClip>(new Clip(1)) }; var s = r.Speech();
        s.Speak("old"); s.Speak("waiting"); s.Stop(); s.Speak("fresh"); s.Tick();
        slow.SetResult(new Clip(1)); s.Tick(); Assert.Equal("fresh", s.CurrentUrl); Assert.Single(r.Players);
    }
    [Fact]
    public void SpeechFailedOrSynchronousThrowingLoadSkipsToNextLine()
    {
        var r = new Rig { Fetch = u => u == "bad" ? throw new Exception("broken") : Task.FromResult<IAudioClip>(new Clip(1)) };
        var s = r.Speech(); s.Speak("bad"); s.Speak("good"); s.Tick();
        Assert.Equal("good", s.CurrentUrl); Assert.Single(r.Logs);
    }
    private sealed class ReleasableClip : IAudioClip, IDisposable
    {
        public double Duration => 1;
        public bool Released;
        public void Dispose() => Released = true;
    }
    [Fact]
    public void SpeechReleasesPlayedStoppedAndAbandonedStreams()
    {
        var clips = new Queue<ReleasableClip>();
        var first = new ReleasableClip(); var second = new ReleasableClip(); var late = new ReleasableClip();
        clips.Enqueue(first); clips.Enqueue(second);
        var slow = new TaskCompletionSource<IAudioClip>();
        var r = new Rig { Fetch = u => u == "late" ? slow.Task : Task.FromResult<IAudioClip>(clips.Dequeue()) };
        var s = r.Speech(); s.Speak("first"); s.Tick(); r.Now = 11; s.Tick(); Assert.True(first.Released);
        s.Speak("second"); s.Tick(); s.Stop(); Assert.True(second.Released);
        s.Speak("late"); s.Stop(); slow.SetResult(late); s.Tick(); Assert.True(late.Released);
        Assert.Equal(2, r.Players.Count);
    }
    [Fact]
    public void VolumeRampInterruptsFromCurrentGainAndRepeatedTargetKeepsDeadline()
    {
        var v = new VolumeRamp(.8); v.Set(.2, 2); v.Set(.2, 2.02);
        Assert.Equal(.5, v.At(2.025), 12); Assert.Equal(.2, v.At(2.05), 12);
        v.Set(1, 3); v.Set(0, 3.025); Assert.Equal(.6, v.At(3.025), 12);
        Assert.Equal(.3, v.At(3.05), 12); Assert.Equal(0, v.At(3.075), 12);
    }
}
