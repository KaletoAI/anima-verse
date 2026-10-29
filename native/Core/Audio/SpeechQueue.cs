using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;

namespace AnimaNative.Audio;

/// <summary>Task 59 / P3-R30: serial speech, with three waiting URLs and oldest-waiting overflow.
/// The current download counts as active (like the browser render+play chain), not as waiting.
/// Stop detaches pending work and stops the active player immediately; a late old download has no path to Start.</summary>
public sealed class SpeechQueue(Func<double> clock, AudioLoader loader, Func<IAudioPlayback> player, Action<string> log)
{
    public const int MaxPending = 3;
    private string[] _pending = [];
    private Task<IAudioClip>? _loading;
    private IAudioPlayback? _playing;
    private IAudioClip? _clip;
    private readonly List<Task<IAudioClip>> _discarded = [];
    private double _end;
    public IReadOnlyList<string> Pending => _pending;
    public string? CurrentUrl { get; private set; }
    public static string[] Enqueue(IEnumerable<string> queue, IEnumerable<string> incoming)
        => queue.Concat(incoming).TakeLast(MaxPending).ToArray();
    public void Speak(string url)
    {
        if (url.Length == 0) return;
        if (CurrentUrl is null) BeginLoad(url);
        else _pending = Enqueue(_pending, [url]);
    }
    public void Stop()
    {
        _pending = [];
        if (_loading is not null) { AudioLoad.IgnoreFailure(_loading); _discarded.Add(_loading); }
        _loading = null;
        _playing?.Stop(); _playing = null; ReleaseClip(); CurrentUrl = null;
        ReleaseDiscarded();
    }
    public void Tick()
    {
        ReleaseDiscarded();
        if (_playing is not null && clock() >= _end)
        { _playing.Stop(); _playing = null; ReleaseClip(); CurrentUrl = null; }
        // A burst has at most three waiting URLs; failures can be drained in one frame without recursion.
        for (int tries = 0; tries <= MaxPending; tries++)
        {
            if (CurrentUrl is null && _pending.Length > 0)
            {
                var next = _pending[0]; _pending = _pending.Skip(1).ToArray(); BeginLoad(next);
            }
            if (_loading is not { IsCompleted: true }) return;
            var task = _loading; _loading = null;
            try
            {
                var clip = _clip = task.GetAwaiter().GetResult();
                if (!double.IsFinite(clip.Duration) || clip.Duration <= 0) throw new InvalidOperationException("empty audio stream");
                _playing = player(); _playing.Start(clip, 1); _end = clock() + clip.Duration;
                return;
            }
            catch (Exception e) { ReleaseClip(); log($"audio: skipped {CurrentUrl}: {e.Message}"); CurrentUrl = null; }
        }
    }
    private void ReleaseClip() { (_clip as IDisposable)?.Dispose(); _clip = null; }
    private void ReleaseDiscarded()
    {
        foreach (var task in _discarded.ToArray())
        {
            if (!task.IsCompleted) continue;
            _discarded.Remove(task);
            if (task.IsCompletedSuccessfully) (task.Result as IDisposable)?.Dispose();
        }
    }
    private void BeginLoad(string url) { CurrentUrl = url; _loading = AudioLoad.Start(loader, url, false); }
}

/// <summary>Task 59: normalize synchronous source failures and observe abandoned asynchronous failures.</summary>
internal static class AudioLoad
{
    public static Task<IAudioClip> Start(AudioLoader loader, string url, bool cache)
    {
        try { return loader(url, cache); }
        catch (Exception e) { return Task.FromException<IAudioClip>(e); }
    }
    public static void IgnoreFailure(Task<IAudioClip>? task)
    {
        if (task is not null) _ = task.ContinueWith(t => { _ = t.Exception; }, TaskContinuationOptions.OnlyOnFaulted);
    }
}
