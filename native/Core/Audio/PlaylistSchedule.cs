using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;

namespace AnimaNative.Audio;

/// <summary>Task 59: endless playlist on an injected monotonic seconds clock. Tick consumes completed downloads,
/// preloads six seconds before the seam, and starts a ready stream on the first frame at/after that seam.
/// Only Tick touches players, so HTTP continuations never enter Godot. Replacing pending work invalidates late
/// loads; old live sources keep their independent linear stop ramps while the new list fades in.</summary>
public sealed class PlaylistSchedule(Func<double> clock, AudioLoader loader, Func<IAudioPlayback> player, Action<string> log)
{
    private string[] _urls = [];
    private int _at, _tries;
    private double _crossfade, _requested, _wake = double.PositiveInfinity;
    private Task<IAudioClip>? _loading;
    private IAudioClip? _ready;
    private string _url = "";
    private readonly List<PlaylistTrack> _live = [];
    public string Key { get; private set; } = "";
    public IReadOnlyList<PlaylistTrack> Live => _live;

    public void Play(IEnumerable<string> urls, double crossfade = AudioMath.DefaultCrossfadeS, string? seed = null)
    {
        var list = urls.ToArray(); var key = string.Join('|', list);
        if (key == Key) return;
        Stop(crossfade);
        Key = key;
        if (list.Length == 0) return;
        _urls = AudioMath.Shuffle(list, seed ?? key);
        _at = 0; _crossfade = Math.Max(0, crossfade); _requested = _wake = clock();
    }

    public void Stop(double fade = AudioMath.RampS)
    {
        var now = clock();
        foreach (var track in _live) track.FadeOut(now, fade);
        Key = ""; _urls = []; _ready = null;
        AudioLoad.IgnoreFailure(_loading); _loading = null;
        _wake = double.PositiveInfinity;
    }

    /// <summary>Task 59: bounded work per frame (at most one round of bad URLs); all bad means silence until a new list.</summary>
    public void Tick()
    {
        var now = clock();
        foreach (var track in _live.ToArray())
        {
            if (track.End <= now) { track.Player.Stop(); _live.Remove(track); }
            else track.Player.SetGain(track.GainAt(now));
        }
        if (_urls.Length == 0) return;
        if (_loading is null && _ready is null && now >= _wake)
        {
            _tries = 0;
            BeginLoad();
        }
        while (_loading is { IsCompleted: true })
        {
            var task = _loading; _loading = null;
            try
            {
                _ready = task.GetAwaiter().GetResult();
                if (!double.IsFinite(_ready.Duration) || _ready.Duration <= 0) throw new InvalidOperationException("empty audio stream");
            }
            catch (Exception e)
            {
                _ready = null;
                log($"audio: skipped {_url}: {e.Message}");
                if (++_tries >= _urls.Length) { _wake = double.PositiveInfinity; return; }
                BeginLoad();
            }
        }
        if (_ready is null || now < _requested) return;
        var timing = AudioMath.Schedule(_requested, now, _ready.Duration, _crossfade);
        var source = player();
        var live = new PlaylistTrack(_url, _ready.Duration, timing, source);
        source.Start(_ready, live.GainAt(now));
        _live.Add(live);
        _ready = null;
        _requested = timing.Seam;
        _wake = timing.Seam - AudioMath.PreloadS;
        // A short track's immediate preload is processed next Tick, never recursively into an endless future list.
    }

    private void BeginLoad()
    {
        _url = _urls[_at]; _at = (_at + 1) % _urls.Length;
        _loading = AudioLoad.Start(loader, _url, true);
    }

    /// <summary>Task 59: scene teardown releases sources immediately; normal playlist changes use Stop's fade.</summary>
    public void Shutdown()
    {
        Stop(0);
        foreach (var track in _live) track.Player.Stop();
        _live.Clear();
    }
}

/// <summary>Task 59: timing and gain for one source. A stop overrides future automation from the CURRENT gain.</summary>
public sealed class PlaylistTrack(string url, double duration, TrackTiming timing, IAudioPlayback player)
{
    private double? _stopAt;
    private double _stopGain, _stopFade;
    public string Url { get; } = url;
    public TrackTiming Timing { get; } = timing;
    public double End => Math.Min(Timing.Begin + duration, _stopAt is { } at ? AudioMath.StopRampEnd(at, _stopFade) : double.PositiveInfinity);
    internal IAudioPlayback Player { get; } = player;
    public double GainAt(double now)
    {
        if (_stopAt is { } at) return AudioMath.StopGainAt(_stopGain, at, _stopFade, now);
        if (now < Timing.Begin || now >= Timing.Begin + duration) return 0;
        if (Timing.Fade <= 0) return 1;
        return now < Timing.Seam ? AudioMath.EqualPowerGainAt(Timing.Begin, Timing.Fade, true, now)
            : AudioMath.EqualPowerGainAt(Timing.Seam, Timing.Fade, false, now);
    }
    internal void FadeOut(double now, double fade)
    {
        if (_stopAt is not null) return;
        _stopGain = GainAt(now); _stopFade = fade; _stopAt = now;
    }
}
