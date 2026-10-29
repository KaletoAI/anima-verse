using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json.Nodes;
using AnimaNative.Api;
using Godot;

namespace AnimaNative.Audio;

/// <summary>Task 59: explicit playlist destination; voice has its own serial API and never loops.</summary>
public enum PlaylistBus { Music, Ambient }

/// <summary>Task 59 / E8-T2: three non-positional buses into Master, driven by monotonic per-frame gains.
/// Configure before use; the optional clock is for headless checks. Task 60 consumes PlayPlaylist and
/// PrefsChanged, owning WHICH playlist is appropriate. No soundtrack selection or TTS rendering happens here.</summary>
public partial class AudioOut : Node
{
    public const string MusicBus = "Music", AmbientBus = "Ambient", VoiceBus = "Voice";
    private Func<double> _clock = () => Time.GetTicksUsec() / 1_000_000.0;
    private AudioStreamLoader? _loader;
    private readonly Dictionary<string, VolumeRamp> _volumes = new();
    private readonly List<string> _ownedBuses = [];
    private bool _closed;
    public AudioPrefs Prefs { get; private set; } = AudioPrefs.Defaults;
    public event Action<AudioPrefs>? PrefsChanged;
    public PlaylistSchedule Music { get; private set; } = null!;
    public PlaylistSchedule Ambient { get; private set; } = null!;
    public SpeechQueue Speech { get; private set; } = null!;

    public AudioOut Configure(Func<IWorldSource?> source, Action<string> log, Func<double>? clock = null)
    {
        if (clock is not null) _clock = clock;
        foreach (var bus in new[] { MusicBus, AmbientBus, VoiceBus })
        {
            if (AudioServer.GetBusIndex(bus) >= 0) continue;
            AudioServer.AddBus(); int index = AudioServer.BusCount - 1;
            AudioServer.SetBusName(index, bus); AudioServer.SetBusSend(index, "Master"); _ownedBuses.Add(bus);
        }
        _loader = new AudioStreamLoader(source);
        IAudioPlayback Player(string bus) => new GodotPlayback(this, bus);
        Music = new(_clock, _loader.Load, () => Player(MusicBus), log);
        Ambient = new(_clock, _loader.Load, () => Player(AmbientBus), log);
        Speech = new(_clock, _loader.Load, () => Player(VoiceBus), log);
        InitializePrefs(null);
        return this;
    }

    /// <summary>Task 59: boot is immediate, before HUD handoff/reconnect; no-hud uses exactly the same stored string.</summary>
    public void InitializePrefs(string? stored)
    {
        Prefs = AudioPrefs.Load(stored);
        _volumes.Clear();
        _volumes["Master"] = new(Prefs.Master); _volumes[MusicBus] = new(Prefs.Music);
        _volumes[AmbientBus] = new(Prefs.Ambient); _volumes[VoiceBus] = new(Prefs.Tts);
        ApplyVolumes();
    }
    public void PlayPlaylist(PlaylistBus bus, IEnumerable<string> urls, double crossfadeS = AudioMath.DefaultCrossfadeS, string? seed = null)
        => (bus == PlaylistBus.Music ? Music : Ambient).Play(urls, crossfadeS, seed);
    public void Speak(string url) => Speech.Speak(url);
    public void StopSpeech() => Speech.Stop();

    /// <summary>Task 59: shared handler registration for Main and offline checks, retaining bridge v3 fire-and-forget.</summary>
    public void AttachHandlers(IDictionary<string, Action<JsonArray>> handlers)
    {
        handlers["setVolumes"] = a => { if (a.Count > 0 && a[0] is JsonObject p) SetVolumes(p); };
        handlers["applyAudioPrefs"] = a => { if (a.Count > 0 && a[0] is JsonObject p) ApplyAudioPrefs(p); };
        handlers["speak"] = a =>
        {
            if (a.Count > 0 && a[0] is JsonValue v && v.TryGetValue<string>(out var url)) Speak(url);
        };
        handlers["stopSpeech"] = _ => StopSpeech();
    }
    public void SetVolumes(JsonObject p)
    {
        double Volume(string key, string bus, double current)
        {
            if (!AudioPrefs.TryVolume(p[key], out var n)) return current;
            n = AudioMath.ClampVolume(n); _volumes[bus].Set(n, _clock()); return n;
        }
        Prefs = Prefs with { Master = Volume("master", "Master", Prefs.Master), Music = Volume("music", MusicBus, Prefs.Music),
            Ambient = Volume("ambient", AmbientBus, Prefs.Ambient), Tts = Volume("tts", VoiceBus, Prefs.Tts) };
    }
    /// <summary>Task 59: only musicOn/ambientOn belong to the scene driver; ttsOn remains the HUD's decision.</summary>
    public void ApplyAudioPrefs(JsonObject p)
    {
        bool Flag(string key, bool old) => p[key] is JsonValue v && v.TryGetValue<bool>(out var b) ? b : old;
        var next = Prefs with { MusicOn = Flag("musicOn", Prefs.MusicOn), AmbientOn = Flag("ambientOn", Prefs.AmbientOn) };
        if (next == Prefs) return;
        Prefs = next; PrefsChanged?.Invoke(Prefs);
    }
    public override void _Process(double delta) => Tick();
    public void Tick()
    {
        if (_closed || _loader is null) return;
        _loader.Pump(); ApplyVolumes(); Music.Tick(); Ambient.Tick(); Speech.Tick();
    }
    private void ApplyVolumes()
    {
        foreach (var (bus, ramp) in _volumes)
            AudioServer.SetBusVolumeLinear(AudioServer.GetBusIndex(bus), (float)ramp.At(_clock()));
    }
    public override void _ExitTree()
    {
        _closed = true;
        Music?.Shutdown(); Ambient?.Shutdown(); Speech?.Stop(); _loader?.Dispose();
        foreach (var bus in _ownedBuses.AsEnumerable().Reverse())
        {
            int index = AudioServer.GetBusIndex(bus);
            if (index >= 0) AudioServer.RemoveBus(index);
        }
        _ownedBuses.Clear();
    }

    /// <summary>Task 59: one source per sounding track, released on end/stop; the schedules supply its amplitude.</summary>
    private sealed class GodotPlayback(AudioOut host, string bus) : IAudioPlayback
    {
        private AudioStreamPlayer? _node;
        public void Start(IAudioClip clip, double gain)
        {
            _node = new AudioStreamPlayer { Bus = bus, Stream = ((LoadedAudio)clip).Stream, VolumeLinear = (float)gain };
            host.AddChild(_node);
            // The dummy driver never mixes/retire playbacks. Keep the same node/stream/gain state without
            // allocating mixer playbacks that would survive an offline check's exit (Task 59).
            if (AudioServer.GetDriverName() != "Dummy") _node.Play();
        }
        public void SetGain(double gain) { if (_node is not null) _node.VolumeLinear = (float)gain; }
        public void Stop()
        {
            if (_node is null) return;
            _node.Stop(); _node.Stream = null; _node.QueueFree(); _node = null;
        }
    }
}
