using System;
using System.Collections.Generic;
using System.Linq;
using AnimaNative.Audio;
using System.Text.Json.Nodes;
using AnimaNative.Tests.Vectors;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>Task 59: every audio.json case and dispatch name is mandatory; the source smoke holds the hand oracle.</summary>
public class AudioVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("audio"));
    private static double N(JsonNode? n) => VectorCompare.Num(n);
    private static double N(JsonArray a, int i) => N(a[i]);
    private static string S(JsonNode? n) => n?.GetValue<string>() ?? "";
    private static string[] Strings(JsonNode? n) => n!.AsArray().Select(S).ToArray();
    private static JsonArray List(IEnumerable<string> values) => new(values.Select(s => (JsonNode?)JsonValue.Create(s)).ToArray());
    private static (double X, double Z)? Point(JsonNode? n) => n is null ? null : (N(n["x"]), N(n["z"]));
    private static readonly Dictionary<string, Func<JsonArray, JsonNode?>> Dispatch = new()
    {
        ["audioPrefsConstants"] = _ => new JsonObject { ["key"] = AudioPrefs.Key, ["defaults"] = AudioPrefs.Defaults.ToJson() },
        ["loadAudioPrefs"] = a => AudioPrefs.Load(a[0]?.GetValue<string>()).ToJson(),
        ["saveAudioPrefs"] = a => JsonValue.Create(AudioPrefs.From(a[0]).Save()),
        ["audioPrefsRoundTrip"] = a => AudioPrefs.Load(AudioPrefs.From(a[0]).Save()).ToJson(),
        ["soundtrackConstants"] = _ => new JsonObject { ["nightOn"] = SoundtrackRules.NightOn, ["nightOff"] = SoundtrackRules.NightOff, ["holdMs"] = SoundtrackRules.HoldMs },
        ["readManifest"] = a => AudioManifest.Read(a[0]).ToJson(),
        ["nightForMusic"] = a => JsonValue.Create(SoundtrackRules.NightForMusic(a[0]!.GetValue<bool>(), N(a, 1))),
        ["nightForMusicSeq"] = a =>
        {
            bool night = a[0]!.GetValue<bool>(); var result = new JsonArray();
            foreach (var factor in a[1]!.AsArray()) { night = SoundtrackRules.NightForMusic(night, N(factor)); result.Add(night); }
            return result;
        },
        ["pickMusic"] = a => List(AudioManifest.Read(a[0]).PickMusic(a[1]!.GetValue<bool>())),
        ["pickAmbient"] = a => List(AudioManifest.Read(a[0]).PickAmbient(S(a[1]))),
        ["ambientTerrainFor"] = a => JsonValue.Create(SoundtrackRules.AmbientTerrainFor(S(a[0]), Point(a[1]), Point(a[2]),
            (x,z) => a[3]!.AsArray().FirstOrDefault(r => N(r![0]) == x && N(r[1]) == z)?[2]?.GetValue<string>() ?? "")),
        ["terrainSwitchSeq"] = a =>
        {
            var state = new TerrainSwitch(); var result = new JsonArray();
            foreach (var step in a[0]!.AsArray())
            {
                state = SoundtrackRules.Switch(state, S(step![0]), N(step[1]), a.Count > 1 ? N(a, 1) : SoundtrackRules.HoldMs);
                result.Add(new JsonObject { ["applied"] = state.Applied, ["pending"] = state.Pending, ["since"] = state.Since, ["started"] = state.Started });
            }
            return result;
        },
        ["equalPowerGainAt"] = a => JsonValue.Create(AudioMath.EqualPowerGainAt(N(a, 0), N(a, 1), a[2]!.GetValue<bool>(), N(a, 3))),
        ["playlistSchedule"] = a =>
        {
            var t = AudioMath.Schedule(N(a, 0), N(a, 1), N(a, 2), a.Count > 3 ? N(a, 3) : AudioMath.DefaultCrossfadeS);
            return new JsonObject { ["begin"] = t.Begin, ["fade"] = t.Fade, ["seam"] = t.Seam, ["wakeInS"] = t.WakeInS };
        },
        ["stopRamp"] = a => new JsonObject { ["gain"] = AudioMath.StopGainAt(N(a, 0), N(a, 1), N(a, 2), N(a, 3)), ["end"] = AudioMath.StopRampEnd(N(a, 1), N(a, 2)) },
        ["volumeRamp"] = a => JsonValue.Create(AudioMath.RampGainAt(N(a, 0), N(a, 1), N(a, 2), N(a, 3))),
        ["shuffle"] = a => List(AudioMath.Shuffle(Strings(a[0]), S(a[1]))),
        ["enqueueSpeech"] = a => List(SpeechQueue.Enqueue(Strings(a[0]), Strings(a[1]))),
    };
    [Fact]
    public void DuplicateStoredKeysUseLastValueWithoutBreakingStartup()
    {
        var prefs = AudioPrefs.Load("{\"master\":0.1,\"master\":0.2,\"musicOn\":true,\"musicOn\":false,\"ttsOn\":\"off\",\"ttsOn\":\"on\"}");
        Assert.Equal(.2, prefs.Master); Assert.False(prefs.MusicOn); Assert.Equal("on", prefs.TtsOn);
        Assert.Equal(AudioPrefs.Defaults, AudioPrefs.Load("{\"master\":{\"x\":1,\"x\":2}}"));
    }
    public static TheoryData<string> Cases => VectorFile.Labels("audio");
    [Theory, MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, Dispatch);
    [Fact]
    public void EveryFunctionIsDispatched() => Assert.Empty(File.Value.MissingFunctions(Dispatch));
}
