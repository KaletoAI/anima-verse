using System;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading.Tasks;

namespace AnimaNative.Audio;

/// <summary>Task 60: one snapshot of the GAME night factor and rendered view; positions are world metres.</summary>
public sealed record SoundtrackFrame(double Night, string Mode, (double X, double Z)? Avatar, (double X, double Z)? Camera);

/// <summary>Task 60 / E8-T3: soundtrack.ts selection with main.ts' 1 Hz tick and immediate input re-ticks.
/// Fetch exactly once per scene session, including failures; only Pump/Tick publish to audio on the caller's
/// thread. Downloads never touch scene objects. Disposal invalidates late manifest completion. The engine
/// owns list identity, seeded shuffle and fading; this driver sends opaque manifest URLs without substitutions.</summary>
public sealed class SoundtrackDriver : IDisposable
{
    public const double TickMs = 1000, MusicCrossfadeS = 4, AmbientCrossfadeS = 3;
    private readonly Func<double> _clock;
    private readonly Func<SoundtrackFrame> _frame;
    private readonly Func<double, double, string> _terrainAt;
    private readonly Action<string[], double> _music, _ambient;
    private Task<JsonDocument>? _loading;
    private AudioManifest _manifest = AudioManifest.Read(null);
    private TerrainSwitch _terrain = new();
    private double _nextTick;
    private bool _night, _musicOn, _ambientOn, _closed;

    public SoundtrackDriver(Func<double> clockMs, Func<SoundtrackFrame> frame, Func<double, double, string> terrainAt,
        Func<Task<JsonDocument>> fetch, Action<string[], double> music, Action<string[], double> ambient,
        bool musicOn = true, bool ambientOn = true)
    {
        _clock = clockMs; _frame = frame; _terrainAt = terrainAt; _music = music; _ambient = ambient;
        _musicOn = musicOn; _ambientOn = ambientOn; _nextTick = clockMs();
        _loading = Load(fetch);
    }
    /// <summary>Task 60: retain the actual fetch task, not a second task waiting on a parsing continuation.
    /// A completed reply must be visible to the next Pump even when the caller has a custom synchronization
    /// context or the fetch uses asynchronous continuations. All parsing/publication belongs to that Pump.</summary>
    private static Task<JsonDocument> Load(Func<Task<JsonDocument>> fetch)
    {
        try { return fetch(); }
        catch (Exception e) { return Task.FromException<JsonDocument>(e); }
    }
    /// <summary>Task 60: consume manifest arrival every frame; keep periodic sampling independent of event ticks.
    /// A stalled frame produces one current sample, never a burst of obsolete interval callbacks.</summary>
    public void Pump()
    {
        if (_closed) return;
        bool changed = false;
        if (_loading is { IsCompleted: true })
        {
            var reply = _loading; _loading = null;
            try
            {
                using var doc = reply.GetAwaiter().GetResult();
                _manifest = AudioManifest.Read(JsonNode.Parse(doc.RootElement.GetRawText()));
            }
            catch { _manifest = AudioManifest.Read(null); }
            changed = true;
        }
        double now = _clock();
        bool due = now >= _nextTick;
        if (due) { _nextTick += TickMs; if (_nextTick <= now) _nextTick = now + TickMs; }
        if (changed || due) Tick();
    }
    /// <summary>Task 60: game-hour/manifest/switch changes recompute both buses from the same current view.
    /// Terrain hold continues even while ambient is disabled, exactly like main.ts tickSoundtrack.</summary>
    public void Tick()
    {
        if (_closed) return;
        var frame = _frame();
        _night = SoundtrackRules.NightForMusic(_night, frame.Night);
        _music(_musicOn ? _manifest.PickMusic(_night) : [], MusicCrossfadeS);
        string here = SoundtrackRules.AmbientTerrainFor(frame.Mode, frame.Avatar, frame.Camera, _terrainAt);
        _terrain = SoundtrackRules.Switch(_terrain, here, _clock());
        _ambient(_ambientOn ? _manifest.PickAmbient(_terrain.Applied) : [], AmbientCrossfadeS);
    }
    public void SetSwitches(bool musicOn, bool ambientOn)
    {
        if (_closed || (_musicOn == musicOn && _ambientOn == ambientOn)) return;
        _musicOn = musicOn; _ambientOn = ambientOn; Tick();
    }
    /// <summary>Task 60: relinquish unconsumed replies on teardown, including a download finishing later.
    /// Cleanup may run off-thread; it only disposes JSON and never reads driver state or calls audio.</summary>
    public void Dispose()
    {
        _closed = true;
        if (_loading is { } reply) { _loading = null; _ = Discard(reply); }
    }
    private static async Task Discard(Task<JsonDocument> reply)
    {
        try { using var doc = await reply.ConfigureAwait(false); }
        catch { /* An abandoned optional manifest cannot fail scene teardown (Task 60). */ }
    }
}
