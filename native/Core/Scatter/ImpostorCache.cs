using System;
using System.Collections.Generic;
using System.Linq;

namespace AnimaNative.Scatter;

/// <summary>Task 38 (E4-T3): URL-keyed LRU ownership. Null is a loaded model's refusal; held bakes never evict,
/// so the cap may be exceeded until entries release. The baker alone owns in-flight jobs and retry verdicts.</summary>
public sealed class ImpostorCache<T> : IDisposable where T : class, IDisposable
{
    private sealed class Entry { public T? Value; public int Refs; public long Used; }
    private readonly Dictionary<string, Entry> _entries = new(StringComparer.Ordinal);
    private readonly int _capacity;
    private long _clock;
    public int Count => _entries.Count;
    public ImpostorCache(int capacity = 16) => _capacity = Math.Max(1, capacity);
    public bool Contains(string url) => _entries.ContainsKey(url);
    public T? Acquire(string url)
    {
        if (!_entries.TryGetValue(url, out var e)) return null;
        e.Used = ++_clock;
        if (e.Value is not null) e.Refs++;
        return e.Value;
    }
    public void Store(string url, T? value, bool acquire = false)
    {
        if (_entries.ContainsKey(url)) throw new InvalidOperationException("impostor stored twice: " + url);
        _entries[url] = new Entry { Value = value, Refs = acquire && value is not null ? 1 : 0, Used = ++_clock };
        Evict();
    }
    public void Release(string url)
    {
        if (_entries.TryGetValue(url, out var e) && e.Refs > 0) e.Refs--;
        Evict();
    }
    private void Evict()
    {
        foreach (var pair in _entries.Where(p => p.Value.Refs == 0).OrderBy(p => p.Value.Used).ToArray())
        {
            if (_entries.Count <= _capacity) break;
            _entries.Remove(pair.Key);
            pair.Value.Value?.Dispose();
        }
    }
    public void Dispose()
    {
        foreach (var e in _entries.Values) e.Value?.Dispose();
        _entries.Clear();
    }
}
