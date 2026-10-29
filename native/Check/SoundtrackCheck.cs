using System;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using AnimaNative.Audio;
using AnimaNative.Scene;
using AnimaNative.Ui;
using AnimaNative.World;
using Godot;

namespace AnimaNative.Check;

/// <summary>Task 60 / E8-T3: fixture-world driver proof with mounted FootprintAt, GAME-clock night factor,
/// camera target, rendered avatar root and the real Task 59 audio output on an injected monotonic clock.
/// Synthetic tones prove selection/routing/fades, not device sound or subjective listening acceptance.</summary>
public static class SoundtrackCheck
{
    public static async Task<int> RunAsync(Node host, string fixtures)
    {
        const string Day = "/assets/audio/music/day/day-a.mp3", DayB = "/assets/audio/music/day/day-b.ogg";
        const string Night = "/assets/audio/music/night/night.wav", Forest = "/assets/audio/ambient/Forest/forest.ogg";
        const string GrassKey = "/assets/audio/ambient/grass/broken.mp3|/assets/audio/ambient/grass/grass-a.mp3|/assets/audio/ambient/grass/grass-b.wav";
        var source = new FixtureSource(Path.Combine(fixtures, "audio"), fixtures);
        var world = new Node3D { Name = "SoundtrackFixture" }; host.AddChild(world);
        var builder = new WorldBuilder(source, _ => { }, strict: true) { PlainGround = true, NoWater = true };
        var camera = new OverviewCamera(); world.AddChild(camera); camera.SetProcess(false);
        var avatar = new Node3D(); world.AddChild(avatar);
        double now = 0, factor = Ambience.NightFactorAt(12);
        bool embodied = false, avatarPresent = true;
        int assertions = 0;
        void Expect(string label, bool ok) { assertions++; if (!ok) throw new InvalidOperationException("soundtrack: " + label); }
        var output = new AudioOut().Configure(() => source, _ => { }, () => now / 1000);
        world.AddChild(output); output.SetProcess(false);
        SoundtrackDriver? driver = null;
        SoundtrackFrame Frame() => new(factor, embodied ? "embodied" : "overview",
            avatarPresent ? (avatar.GlobalPosition.X, avatar.GlobalPosition.Z) : null, (camera.Target.X, camera.Target.Z));
        void Step(double ms) { now = ms; driver!.Tick(); for (int i = 0; i < 3; i++) output.Tick(); }
        var handlers = new System.Collections.Generic.Dictionary<string, Action<JsonArray>>(); output.AttachHandlers(handlers);
        void Switches(AudioPrefs p) => driver?.SetSwitches(p.MusicOn, p.AmbientOn);
        try
        {
            var stats = await builder.BuildAsync(world, null);
            Expect("fixture mounted without failures", stats.Failures == 0);
            Expect("mounted camera grass", builder.FootprintAt(0, 0)?.Loc.Terrain == "grass");
            Expect("mounted avatar forest", builder.FootprintAt(20, 0)?.Loc.Terrain == "forest");
            using var map = await source.GetWorldMapAsync();
            var pos = map.RootElement.GetProperty("characters")[0].GetProperty("pos");
            avatar.GlobalPosition = new Vector3(pos.GetProperty("x").GetSingle(), 0, pos.GetProperty("z").GetSingle());
            camera.JumpTo(Vector3.Zero, 50);
            driver = new(() => now, Frame, (x, z) => builder.FootprintAt(x, z)?.Loc.Terrain ?? "",
                source.GetAudioManifestAsync, (urls, fade) => output.PlayPlaylist(PlaylistBus.Music, urls, fade),
                (urls, fade) => output.PlayPlaylist(PlaylistBus.Ambient, urls, fade), output.Prefs.MusicOn, output.Prefs.AmbientOn);
            output.PrefsChanged += Switches;
            driver.Pump(); Step(0);
            Expect("12h day list", output.Music.Key == Day + "|" + DayB);
            Expect("first terrain immediate", output.Ambient.Key == GrassKey);
            Step(4500);
            var track = output.Music.Live.Last();
            double beforeStop = track.GainAt(4.5);
            Expect("music track sounding before switch", beforeStop > .99);
            handlers["applyAudioPrefs"](new JsonArray(new JsonObject { ["musicOn"] = false }));
            Expect("live music switch immediate", output.Music.Key == "" && output.Ambient.Key == GrassKey);
            now = 6500; output.Tick();
            Expect("four second linear stop midpoint", Math.Abs(track.GainAt(6.5) - beforeStop / 2) < 1e-8);
            now = 8500; output.Tick(); Expect("four second stop ends", !output.Music.Live.Contains(track));
            handlers["applyAudioPrefs"](new JsonArray(new JsonObject { ["musicOn"] = true }));
            Expect("reenable immediate day", output.Music.Key == Day + "|" + DayB);
            factor = Ambience.NightFactorAt(22); driver.Tick(); Expect("22h night list", output.Music.Key == Night);
            foreach (double f in new[] { .21, .2 }) { factor = f; driver.Tick(); Expect("dawn band keeps night", output.Music.Key == Night); }
            factor = .19; driver.Tick(); Expect("dawn below .2 becomes day", output.Music.Key == Day + "|" + DayB);
            foreach (double f in new[] { .19, .21, .19, .8 }) { factor = f; driver.Tick(); Expect("dusk band keeps day", output.Music.Key == Day + "|" + DayB); }
            factor = .81; driver.Tick(); Expect("dusk above .8 becomes night", output.Music.Key == Night);
            camera.JumpTo(new Vector3(20, 0, 0), 50); Step(9000);
            Step(13999); Expect("terrain held before 5s", output.Ambient.Key == GrassKey);
            Step(14000); Expect("terrain changes at 5s", output.Ambient.Key == Forest);
            camera.JumpTo(Vector3.Zero, 50); Step(15000); Step(20000);
            Expect("overview follows camera rather than avatar", output.Ambient.Key == GrassKey);
            embodied = true; Step(21000); Step(25999); Expect("mode change still holds terrain", output.Ambient.Key == GrassKey);
            Step(26000); Expect("embodied follows rendered avatar", output.Ambient.Key == Forest);
            avatarPresent = false; Step(27000); Step(32000); Expect("missing embodied avatar stays silent", output.Ambient.Key == "");
            Expect("one manifest across all clock/view/switch changes", source.AudioManifestRequests == 1);
            driver.Dispose();
            embodied = false; avatarPresent = true;
            driver = new(() => now, Frame, (_, _) => "water",
                () => Task.FromResult(JsonDocument.Parse("{\"music\":{\"day\":[\"unused-day\"]},\"ambient\":{\"sand\":[\"unused-sand\"]}}")),
                (urls, fade) => output.PlayPlaylist(PlaylistBus.Music, urls, fade),
                (urls, fade) => output.PlayPlaylist(PlaylistBus.Ambient, urls, fade));
            driver.Pump();
            Expect("manifest without matching night/terrain is silent", output.Music.Key == "" && output.Ambient.Key == "");
            Step(37000); Expect("unmatched silence retires old players", output.Music.Live.Count == 0 && output.Ambient.Live.Count == 0);
        }
        finally
        {
            output.PrefsChanged -= Switches; driver?.Dispose();
            builder.Models?.FreeAll(); world.Free();
            await host.ToSignal(host.GetTree(), SceneTree.SignalName.ProcessFrame);
        }
        return assertions;
    }
}
