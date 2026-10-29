using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;

namespace AnimaNative.Audio;

/// <summary>Task 65 / P3-R38: serial speech with completion on end, failure, stop and overflow.
/// The HUD now waits for completion; three waiting lines remain only as a safety net.
/// Stop detaches downloads immediately so a late result can never start playback.</summary>
public sealed class SpeechQueue(Func<double> clock, AudioLoader loader, Func<IAudioPlayback> player, Action<string> log)
{
    public const int MaxPending = 3;
    private sealed record Line(string Url, TaskCompletionSource Done);
    private readonly Queue<Line> _pending = new();
    private Line? _active;
    private Task<IAudioClip>? _loading;
    private IAudioPlayback? _playing;
    private IAudioClip? _clip;
    private readonly List<Task<IAudioClip>> _discarded = [];
    private double _end;
    public IReadOnlyList<string> Pending => _pending.Select(l => l.Url).ToArray();
    public string? CurrentUrl => _active?.Url;
    public static string[] Enqueue(IEnumerable<string> queue, IEnumerable<string> incoming)
        => queue.Concat(incoming).TakeLast(MaxPending).ToArray();
    public Task Speak(string url)
    {
        if (url.Length == 0) return Task.CompletedTask;
        var line = new Line(url, new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously));
        if (_active is null) BeginLoad(line);
        else
        {
            if (_pending.Count == MaxPending) _pending.Dequeue().Done.TrySetResult();
            _pending.Enqueue(line);
        }
        return line.Done.Task;
    }
    public void Stop()
    {
        while (_pending.TryDequeue(out var line)) line.Done.TrySetResult();
        if (_loading is not null) { AudioLoad.IgnoreFailure(_loading); _discarded.Add(_loading); }
        _loading = null;
        FinishActive(); ReleaseDiscarded();
    }
    public void Tick()
    {
        ReleaseDiscarded();
        if (_playing is not null && clock() >= _end) FinishActive();
        // Even a burst of failed loads is bounded by the safety cap.
        for (int tries = 0; tries <= MaxPending; tries++)
        {
            if (_active is null && _pending.TryDequeue(out var next)) BeginLoad(next);
            if (_loading is not { IsCompleted: true }) return;
            var task = _loading; _loading = null;
            try
            {
                var clip = _clip = task.GetAwaiter().GetResult();
                if (!double.IsFinite(clip.Duration) || clip.Duration <= 0) throw new InvalidOperationException("empty audio stream");
                _playing = player(); _playing.Start(clip, 1); _end = clock() + clip.Duration;
                return;
            }
            catch (Exception e) { log($"audio: skipped {CurrentUrl}: {e.Message}"); FinishActive(); }
        }
    }
    private void FinishActive()
    {
        _playing?.Stop(); _playing = null; ReleaseClip();
        var done = _active?.Done; _active = null; done?.TrySetResult();
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
    private void BeginLoad(Line line) { _active = line; _loading = AudioLoad.Start(loader, line.Url, false); }
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
