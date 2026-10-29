using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using AnimaNative.Audio;
using Godot;

namespace AnimaNative.Check;

/// <summary>Task 59: real authenticated-source boundary, runtime codecs, buses, handlers and players on a fake clock.
/// No assertion depends on dummy audio playback positions or audible sound. Hand timings and codec tolerances come
/// from fixtures/audio/README.md; failures throw into CheckRunner's normal nonzero exit path.</summary>
public static class AudioCheck
{
    public static async Task<string> RunAsync(Node host, string fixtures)
    {
        const string Day = "/assets/audio/music/day/day-a.mp3", DayB = "/assets/audio/music/day/day-b.ogg";
        const string Night = "/assets/audio/music/night/night.wav", Grass = "/assets/audio/ambient/grass/grass-a.mp3";
        const string GrassB = "/assets/audio/ambient/grass/grass-b.wav", Forest = "/assets/audio/ambient/Forest/forest.ogg";
        const string Speech = "/tts/tmp/fixture.wav", Broken = "/assets/audio/ambient/grass/broken.mp3";
        var source = new FixtureSource(Path.Combine(fixtures, "audio"), fixtures);
        int assertions = 0;
        void Expect(string label, bool ok) { assertions++; if (!ok) throw new InvalidOperationException("audio: " + label); }
        void Near(string label, double actual, double expected, double eps = 1e-6) => Expect($"{label}: {actual} vs {expected}", Math.Abs(actual - expected) <= eps);
        using (var loader = new AudioStreamLoader(() => source))
        {
            foreach (var (url, duration, tolerance) in new[] { (Day, 9d, .072), (DayB, 12d, .064), (Night, 2d, .000125),
                (Grass, 1.5, .072), (GrassB, 3d, .000125), (Forest, 3d, .064), (Speech, 1d, .000125) })
            {
                var pending = loader.Load(url, true); loader.Pump();
                var clip = await pending; Near("decoded " + url, clip.Duration, duration, tolerance);
                Expect("playlist cache reuses " + url, ReferenceEquals(pending, loader.Load(url, true)));
            }
            int before = source.ByteRequests.Count;
            var first = loader.Load(Speech, false); loader.Pump(); await first;
            var second = loader.Load(Speech, false); loader.Pump(); await second;
            Expect("speech never cached", source.ByteRequests.Count == before + 2 && !ReferenceEquals(first, second));
            for (int i = 0; i < 2; i++)
            {
                var bad = loader.Load(Broken, true); loader.Pump();
                try { await bad; Expect("broken decode must throw", false); }
                catch (InvalidOperationException) { Expect("broken decode rejected", bad.IsFaulted); }
            }
            Expect("failed cache entry evicted", source.ByteRequests.Count(u => u == Broken) == 2);
        }
        double now = 2;
        var logs = new List<string>();
        var output = new AudioOut { Name = "CheckAudio" }.Configure(() => source, logs.Add, () => now);
        host.AddChild(output); output.SetProcess(false);
        var handlers = new Dictionary<string, Action<JsonArray>>(); output.AttachHandlers(handlers);
        void Step(double time) { now = time; for (int i = 0; i < 3; i++) output.Tick(); }
        double Bus(string name) => AudioServer.GetBusVolumeLinear(AudioServer.GetBusIndex(name));
        int Players(string bus) => output.GetChildren().OfType<AudioStreamPlayer>().Count(p => !p.IsQueuedForDeletion() && p.Bus == bus);
        try
        {
            output.InitializePrefs("{\"master\":0.8,\"music\":0.25,\"ambient\":0.4,\"tts\":0.6,\"musicOn\":false}");
            Near("stored master", Bus("Master"), .8); Near("stored music", Bus(AudioOut.MusicBus), .25);
            Near("stored ambient", Bus(AudioOut.AmbientBus), .4); Near("stored voice", Bus(AudioOut.VoiceBus), .6);
            Expect("stored switch", !output.Prefs.MusicOn);
            foreach (var bus in new[] { AudioOut.MusicBus, AudioOut.AmbientBus, AudioOut.VoiceBus })
                Expect(bus + " sends to Master", AudioServer.GetBusSend(AudioServer.GetBusIndex(bus)) == "Master");
            handlers["setVolumes"](new JsonArray(new JsonObject { ["master"] = .2 }));
            Step(2.02); handlers["setVolumes"](new JsonArray(new JsonObject { ["master"] = .2 }));
            Step(2.025); Near("volume midpoint", Bus("Master"), .5); Near("bus isolation", Bus(AudioOut.MusicBus), .25);
            Step(2.05); Near("50ms volume target", Bus("Master"), .2);
            handlers["setVolumes"](new JsonArray(new JsonObject { ["tts"] = 0 })); Step(2.1);
            Near("zero linear voice volume", Bus(AudioOut.VoiceBus), 0);
            int changes = 0; output.PrefsChanged += _ => changes++;
            handlers["applyAudioPrefs"](new JsonArray(new JsonObject { ["musicOn"] = true, ["ambientOn"] = false, ["master"] = 1 }));
            Expect("switch handler/event", output.Prefs.MusicOn && !output.Prefs.AmbientOn && changes == 1);
            Near("switch handler leaves volume alone", Bus("Master"), .2);
            handlers["speak"](new JsonArray(42)); handlers["setVolumes"](new JsonArray("bad"));
            Expect("malformed bridge args ignored", output.Speech.CurrentUrl is null);
            now = 10; output.PlayPlaylist(PlaylistBus.Music, [Day], 4); Step(10);
            var firstTrack = output.Music.Live.Single();
            Near("fade cap", firstTrack.Timing.Fade, 3); Near("seam", firstTrack.Timing.Seam, 16);
            Step(10.1875); Near("first segment midpoint", firstTrack.GainAt(now), .09754516100806413);
            Near("real player gain", output.GetChildren().OfType<AudioStreamPlayer>().Single(p => !p.IsQueuedForDeletion()).VolumeLinear, .09754516100806413);
            Step(11.5); Near("fade-in middle", firstTrack.GainAt(now), .7071067811865476);
            output.PlayPlaylist(PlaylistBus.Music, [Day], 1); Step(15.99);
            Expect("identical list no-op", output.Music.Live.Count == 1 && Players(AudioOut.MusicBus) == 1);
            Step(16); Expect("next starts at seam", output.Music.Live.Count == 2 && output.Music.Live[1].Timing.Begin == 16);
            Step(17.5); Near("outgoing crossfade gain", firstTrack.GainAt(now), .7071067811865476);
            var secondTrack = output.Music.Live[1]; Near("incoming crossfade gain", secondTrack.GainAt(now), .7071067811865476);
            output.PlayPlaylist(PlaylistBus.Music, [], 4); Step(19.5);
            Near("linear stop midpoint", secondTrack.GainAt(now), .3535533905932738);
            Step(21.5); Expect("empty list stops", output.Music.Live.Count == 0 && Players(AudioOut.MusicBus) == 0);
            now = 22; output.PlayPlaylist(PlaylistBus.Music, [Night], 4); Step(22);
            Near("short track fade cap", output.Music.Live.Single().Timing.Fade, 2d / 3);
            Near("short track seam", output.Music.Live.Single().Timing.Seam, 23d + 1d / 3);
            now = 30; output.PlayPlaylist(PlaylistBus.Ambient, [Broken, Forest], 3, "a"); Step(30);
            Expect("broken file skipped", output.Ambient.Live.Single().Url == Forest);
            Expect("one broken-file log", logs.Count == 1 && logs[0].Contains(Broken));
            handlers["speak"](new JsonArray(Speech)); Step(30);
            foreach (var url in new[] { Day, DayB, Night, Grass }) handlers["speak"](new JsonArray(url));
            Expect("three waiting, oldest dropped", output.Speech.Pending.SequenceEqual(new[] { DayB, Night, Grass }));
            Expect("one sounding voice", Players(AudioOut.VoiceBus) == 1 && output.Speech.CurrentUrl == Speech);
            Step(31); Expect("speech FIFO", output.Speech.CurrentUrl == DayB && Players(AudioOut.VoiceBus) == 1);
            handlers["stopSpeech"](new JsonArray());
            Expect("stop immediate and clears queue", output.Speech.CurrentUrl is null && output.Speech.Pending.Count == 0 && Players(AudioOut.VoiceBus) == 0);
            Expect("stop speech leaves playlists", output.Music.Key.Length > 0 && output.Ambient.Key.Length > 0);
            // Stop before the Godot loader pumps a finished fetch: no late voice source may be created.
            handlers["speak"](new JsonArray(Speech)); handlers["stopSpeech"](new JsonArray()); Step(31);
            Expect("late speech load never starts", Players(AudioOut.VoiceBus) == 0);
            output.PlayPlaylist(PlaylistBus.Ambient, [Broken]); Step(31);
            int requests = source.ByteRequests.Count; Step(50);
            Expect("all broken does not spin", source.ByteRequests.Count == requests && output.Ambient.Live.Count == 0);
        }
        finally
        {
            output.Free();
            await host.ToSignal(host.GetTree(), SceneTree.SignalName.ProcessFrame);
        }
        int driverAssertions = await SoundtrackCheck.RunAsync(host, fixtures);
        return $"audio driver_assertions={driverAssertions} assertions={assertions} codecs=7 buses=3 ramp=0.05 fade_steps=8 speech_pending_cap=3 broken_logs={logs.Count}";
    }
}
