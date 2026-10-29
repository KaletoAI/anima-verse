using System;
using System.Collections.Generic;
using System.Threading.Tasks;
using AnimaNative.Api;
using Godot;

namespace AnimaNative.Audio;

/// <summary>Task 59: Godot stream retained by an engine-free schedule. Compressed MP3/Ogg remain compressed in memory.</summary>
public sealed class LoadedAudio(AudioStream stream) : IAudioClip, IDisposable
{
    private bool _disposed;
    public AudioStream Stream { get; } = stream;
    public double Duration => Stream.GetLength();
    internal Action<LoadedAudio>? Released { get; set; }
    public void Dispose()
    {
        if (_disposed) return;
        _disposed = true; Released?.Invoke(this); Stream.Dispose();
    }
}

/// <summary>Task 59: all bytes, including TTS, come from the current session's IWorldSource.GetBytesAsync.
/// HTTP can finish off-thread; Pump alone decodes on the Godot thread. Successful playlist loads are cached
/// per URL, speech is never cached, and failed cache entries are evicted for a later retry.</summary>
public sealed class AudioStreamLoader(Func<IWorldSource?> source) : IDisposable
{
    private sealed record Pending(string Url, bool Cache, Task<byte[]> Bytes, TaskCompletionSource<IAudioClip> Result);
    private readonly Dictionary<string, Task<IAudioClip>> _cache = new();
    private readonly List<Pending> _pending = [];
    private readonly HashSet<LoadedAudio> _uncached = [];
    private bool _disposed;
    public Task<IAudioClip> Load(string url, bool cache)
    {
        if (_disposed) return Task.FromException<IAudioClip>(new ObjectDisposedException(nameof(AudioStreamLoader)));
        if (cache && _cache.TryGetValue(url, out var known)) return known;
        var result = new TaskCompletionSource<IAudioClip>(TaskCreationOptions.RunContinuationsAsynchronously);
        Task<byte[]> bytes;
        try { bytes = source()?.GetBytesAsync(url) ?? Task.FromException<byte[]>(new InvalidOperationException("no audio session")); }
        catch (Exception e) { bytes = Task.FromException<byte[]>(e); }
        _pending.Add(new(url, cache, bytes, result));
        if (cache) _cache[url] = result.Task;
        return result.Task;
    }
    public void Pump()
    {
        foreach (var pending in _pending.ToArray())
        {
            if (!pending.Bytes.IsCompleted) continue;
            _pending.Remove(pending);
            try
            {
                var decoded = Decode(pending.Bytes.GetAwaiter().GetResult());
                if (!pending.Cache) { _uncached.Add(decoded); decoded.Released = audio => _uncached.Remove(audio); }
                pending.Result.SetResult(decoded);
            }
            catch (Exception e)
            {
                if (pending.Cache) _cache.Remove(pending.Url);
                pending.Result.SetException(e);
            }
        }
    }
    /// <summary>Task 59: signatures win over extensions; null/empty/throwing decoders become ordinary skipped loads.</summary>
    public static LoadedAudio Decode(byte[] bytes)
    {
        AudioStream? stream = AudioFormats.Detect(bytes) switch
        {
            AudioFormat.Mp3 => AudioStreamMP3.LoadFromBuffer(bytes),
            AudioFormat.Ogg => AudioStreamOggVorbis.LoadFromBuffer(bytes),
            AudioFormat.Wav => AudioStreamWav.LoadFromBuffer(bytes, new Godot.Collections.Dictionary()),
            _ => throw new InvalidOperationException("unsupported or broken audio data"),
        };
        if (stream is null || !double.IsFinite(stream.GetLength()) || stream.GetLength() <= 0)
        { stream?.Dispose(); throw new InvalidOperationException("empty or broken audio stream"); }
        switch (stream)
        {
            case AudioStreamMP3 mp3: mp3.Loop = false; break;
            case AudioStreamOggVorbis ogg: ogg.Loop = false; break;
            case AudioStreamWav wav: wav.LoopMode = AudioStreamWav.LoopModeEnum.Disabled; break;
        }
        return new(stream);
    }
    public void Dispose()
    {
        _disposed = true;
        foreach (var pending in _pending)
        {
            pending.Result.TrySetCanceled();
            _ = pending.Bytes.ContinueWith(t => { _ = t.Exception; }, TaskContinuationOptions.OnlyOnFaulted);
        }
        foreach (var task in _cache.Values)
            if (task.IsCompletedSuccessfully) (task.Result as IDisposable)?.Dispose();
        foreach (var clip in new List<LoadedAudio>(_uncached)) clip.Dispose();
        _pending.Clear(); _cache.Clear(); _uncached.Clear();
    }
}
