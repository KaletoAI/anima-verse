using System;
using System.Collections.Generic;
using System.Threading.Tasks;

namespace AnimaNative.Figures;

/// <summary>One job of a <see cref="FocusQueue"/> (<c>FocusJob</c> of client3d/src/game/focusQueue.ts).</summary>
public sealed record FocusJob(Func<double> Distance, Func<Task> Run, string? Key = null, bool Avatar = false);

/// <summary>
/// The browser's <c>createFocusQueue({max})</c>: at most <see cref="Max"/> jobs run at once; the next one to start
/// is picked when a slot frees up — avatar jobs first, then the smallest <c>distance()</c> (read at pick time, NaN =
/// ∞), then submission order. A job's failure is swallowed (the job reports its own errors), its slot is freed.
/// <see cref="Cancel"/> takes a waiting job out (its push answers <c>false</c>). Single-threaded use: call it from
/// one synchronisation context (Godot's main thread), like the browser's event loop.
/// </summary>
public sealed class FocusQueue
{
    private sealed record Waiting(FocusJob Job, long Seq, TaskCompletionSource<bool> Done);

    private readonly List<Waiting> _waiting = new();
    private readonly object _gate = new();
    private long _seq;
    private bool _scheduled;

    public FocusQueue(int max) => Max = max > 0 ? max : throw new ArgumentOutOfRangeException(nameof(max));

    public int Max { get; }
    public int Active { get; private set; }
    public int Size => _waiting.Count;

    /// <summary>Queue a job; completes true when it ran (whatever its outcome), false when it was cancelled.</summary>
    public Task<bool> Push(FocusJob job)
    {
        var done = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
        bool schedule;
        lock (_gate)
        {
            _waiting.Add(new Waiting(job, _seq++, done));
            schedule = !_scheduled;
            _scheduled = true;
        }
        // Like queueMicrotask(pump): the jobs pushed in one synchronous pass compete for the first slots.
        if (schedule) _ = PumpLater();
        return done.Task;
    }

    private async Task PumpLater()
    {
        await Task.Yield();
        lock (_gate) _scheduled = false;
        Pump();
    }

    public bool Cancel(string key)
    {
        lock (_gate)
        {
            int i = _waiting.FindIndex(w => w.Job.Key == key);
            if (i < 0) return false;
            var w = _waiting[i];
            _waiting.RemoveAt(i);
            w.Done.TrySetResult(false);
            return true;
        }
    }

    /// <summary>The index of the job that starts next (<c>pick</c>).</summary>
    private int Pick()
    {
        int best = 0;
        for (int i = 1; i < _waiting.Count; i++)
        {
            var a = _waiting[i];
            var b = _waiting[best];
            int pa = a.Job.Avatar ? 0 : 1, pb = b.Job.Avatar ? 0 : 1;
            double da = a.Job.Distance(), db = b.Job.Distance();
            if (double.IsNaN(da)) da = double.PositiveInfinity;
            if (double.IsNaN(db)) db = double.PositiveInfinity;
            if (pa != pb ? pa < pb : da != db ? da < db : a.Seq < b.Seq) best = i;
        }
        return best;
    }

    private void Pump()
    {
        while (true)
        {
            Waiting w;
            lock (_gate)
            {
                if (Active >= Max || _waiting.Count == 0) return;
                int i = Pick();
                w = _waiting[i];
                _waiting.RemoveAt(i);
                Active++;
            }
            _ = RunOne(w);
        }
    }

    private async Task RunOne(Waiting w)
    {
        try { await Task.Yield(); await w.Job.Run(); }
        catch (Exception) { /* the job logs its own failure */ }
        finally
        {
            lock (_gate) Active--;
            w.Done.TrySetResult(true);
            Pump();
        }
    }
}
