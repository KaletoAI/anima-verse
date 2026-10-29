using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;

namespace AnimaNative.Sync;

/// <summary>Task 62 / E10-T1: instance-owned, worker-safe operation sums. Parallel operations overlap;
/// these are work milliseconds, not additive critical-path durations. Snapshots charge completed operations
/// to the stage reporting them. CPU comprises generate, clip import and fitting, each separately visible.</summary>
public sealed class BootMeasurements
{
    public sealed record Sample(string Category, string Work, double Ms, long Requests, long Bytes);
    private readonly object _gate = new();
    private readonly List<Sample> _samples = new();
    private bool _recording = true;
    public void Add(string category, string work, double ms, long requests = 0, long bytes = 0)
    { lock (_gate) { if (_recording) _samples.Add(new(category, work, ms, requests, bytes)); } }
    public Sample[] Snapshot() { lock (_gate) return _samples.ToArray(); }
    public void Reset() { lock (_gate) { _samples.Clear(); _recording = true; } }
    /// <summary>Task 62: retain the boot snapshot without accumulating the session's live poll samples.</summary>
    public void Stop() { lock (_gate) _recording = false; }
    public IDisposable Time(string category, string work) => new Measurement(this, category, work);
    private sealed class Measurement(BootMeasurements owner, string category, string work) : IDisposable
    {
        private readonly long _start = Stopwatch.GetTimestamp();
        public void Dispose() => owner.Add(category, work, Stopwatch.GetElapsedTime(_start).TotalMilliseconds);
    }
    public static string Split(IEnumerable<Sample> samples)
    {
        var list = samples.ToList();
        double Sum(string work) => list.Where(s => s.Work == work).Sum(s => s.Ms);
        return $"download={Sum("download"):0} parse={Sum("parse"):0} CPU={list.Where(s => s.Work is not ("download" or "parse")).Sum(s => s.Ms):0} ms "
            + $"(clip import={Sum("clip import"):0} fitting={Sum("fitting"):0} cached={Sum("cached"):0} generate={Sum("generate"):0})";
    }
    public string Describe() => string.Join("; ", Snapshot().GroupBy(s => s.Category).OrderBy(g => g.Key)
        .Select(g => $"{g.Key}: requests={g.Sum(s => s.Requests)} bytes={g.Sum(s => s.Bytes)} {Split(g)}"));
    public static string Category(string path)
        => path.StartsWith("/assets/animation-", StringComparison.Ordinal) ? "clip"
         : path.Contains("/model3d/file", StringComparison.Ordinal) ? "character GLB"
         : path.Contains("/model3d/texture", StringComparison.Ordinal) ? "texture"
         : path.EndsWith("/model", StringComparison.Ordinal) || path.EndsWith("/model.glb", StringComparison.Ordinal)
            || path.EndsWith(".glb", StringComparison.Ordinal) || path.EndsWith(".fbx", StringComparison.Ordinal) ? "scene GLB"
         : path.StartsWith("/assets/audio/", StringComparison.Ordinal) ? "audio"
         : path.EndsWith(".json", StringComparison.Ordinal) ? "JSON" : "texture";
}
