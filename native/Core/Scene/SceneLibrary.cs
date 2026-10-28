using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;

namespace AnimaNative.Scene;

/// <summary>
/// Task 44: SceneLibrary's epoch guarded cache (sceneRecipe.ts). Forget invalidates pending requests AND
/// not-yet-started sweep work; late responses still complete their callers but cannot resurrect the cache or
/// publish OnScene. Request deduplicates by promise identity. Payloads are managed data, never Godot templates.
/// </summary>
public sealed class SceneLibrary<T> where T : class
{
    private readonly Dictionary<string, T?> _cache = new();
    private readonly Dictionary<string, Task<T?>> _pending = new();
    private readonly Dictionary<string, int> _epochs = new();
    private readonly Func<string, Task<T?>> _fetch;
    private readonly Func<T, string?> _signature;
    public event Action<string, T?>? OnScene;

    public SceneLibrary(Func<string, Task<T?>> fetch, Func<T, string?> signature) => (_fetch, _signature) = (fetch, signature);
    private int Epoch(string id) => _epochs.GetValueOrDefault(id);
    public T? Get(string id) => _cache.GetValueOrDefault(id);
    public void Forget(string id) { _epochs[id] = Epoch(id) + 1; _cache.Remove(id); _pending.Remove(id); }

    public Task<T?> Request(string id)
    {
        if (_cache.TryGetValue(id, out var cached)) return Task.FromResult(cached);
        if (_pending.TryGetValue(id, out var pending)) return pending;
        int epoch = Epoch(id);
        var done = new TaskCompletionSource<T?>();
        _pending[id] = done.Task;
        _ = Fetch();
        return done.Task;
        async Task Fetch()
        {
            try
            {
                var scene = await _fetch(id);
                if (Epoch(id) == epoch) { _cache[id] = scene; OnScene?.Invoke(id, scene); }
                done.TrySetResult(scene);
            }
            catch (Exception e) { done.TrySetException(e); }
            finally { if (_pending.GetValueOrDefault(id) == done.Task) _pending.Remove(id); }
        }
    }

    public async Task Sweep(IEnumerable<string> ids)
    {
        var snapshot = ids.Select(id => (Id: id, Epoch: Epoch(id))).ToArray();
        foreach (var (id, epoch) in snapshot)
        {
            if (Epoch(id) != epoch) continue;
            try
            {
                var fresh = await _fetch(id);
                if (Epoch(id) != epoch) continue;
                var old = Get(id);
                bool changed = (old is null ? null : _signature(old)) != (fresh is null ? null : _signature(fresh));
                _cache[id] = fresh;
                if (changed) OnScene?.Invoke(id, fresh);
            }
            catch { /* A later sweep retries a transient failure. */ }
        }
    }
}
