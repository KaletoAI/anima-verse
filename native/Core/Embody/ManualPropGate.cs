using System;
using System.Collections.Generic;
using System.Threading.Tasks;

namespace AnimaNative.Embody;

/// <summary>
/// Task 47 (E7-T2): propActionMotion.ts createManualPropGate, used by main.ts applyDriver.
/// Cancellation is an awaited mutation. Concurrent calls share the pending task; only successful cancellation
/// withdraws the captured journey, and a failure releases the gate for retry. Execution identity is deliberately
/// unused, matching the browser: the gate coalesces every cancellation while one is pending.
/// </summary>
public sealed class ManualPropGate
{
    private readonly object _sync = new();
    private readonly HashSet<string> _withdrawn = new(StringComparer.Ordinal);
    private Task? _pending;
    public bool Pending { get { lock (_sync) return _pending is not null; } }
    public bool Withdrawn(string? journey)
    {
        lock (_sync) return !string.IsNullOrEmpty(journey) && _withdrawn.Contains(journey);
    }
    public Task Cancel(string execution, string? journey, Func<Task> cancel)
    {
        TaskCompletionSource completion;
        lock (_sync)
        {
            if (_pending is not null) return _pending;
            completion = new(TaskCreationOptions.RunContinuationsAsynchronously);
            _pending = completion.Task;
        }
        _ = Complete(cancel, journey, completion);
        return completion.Task;
    }
    private async Task Complete(Func<Task> cancel, string? journey, TaskCompletionSource completion)
    {
        Exception? error = null;
        try
        {
            await cancel();
            lock (_sync) if (!string.IsNullOrEmpty(journey)) _withdrawn.Add(journey);
        }
        catch (Exception e) { error = e; }
        finally { lock (_sync) _pending = null; }
        if (error is null) completion.SetResult();
        else completion.SetException(error);
    }
}
