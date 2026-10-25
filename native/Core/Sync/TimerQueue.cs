using System;
using System.Collections.Generic;
using System.Linq;

namespace AnimaNative.Sync;

/// <summary>
/// The clock and the one-shot timers the sync layer runs on — the <c>PollEnv</c> of pollCore.ts and the
/// <c>setTimeout</c>/<c>now</c> deps of syncHub.ts. Everything that uses it is single-threaded: the host
/// calls into the scheduler, the hub and the timers from ONE thread (Godot's main thread; a test's thread).
/// </summary>
public interface ISyncClock
{
    /// <summary>Monotonic milliseconds.</summary>
    double Now();
    /// <summary>Run <paramref name="fn"/> once, <paramref name="ms"/> from now; the handle cancels it.</summary>
    object SetTimeout(Action fn, double ms);
    void ClearTimeout(object? handle);
}

/// <summary>
/// An <see cref="ISyncClock"/> whose timers fire only when the host pumps it (<see cref="Pump"/>): Godot pumps
/// it once per frame with <c>Time.GetTicksMsec()</c>, a test advances a simulated clock. Timers fire in due
/// order, ties in the order they were set (like a browser's timer queue); a timer set by a firing timer with
/// a due time already passed fires in the same pump.
/// </summary>
public sealed class TimerQueue : ISyncClock
{
    private sealed class Timer
    {
        public required double Due;
        public required long Seq;
        public required Action Fn;
        public bool Cancelled;
    }

    private readonly Func<double> _now;
    private readonly List<Timer> _timers = new();
    private long _seq;

    public TimerQueue(Func<double> now) => _now = now;

    public double Now() => _now();

    public object SetTimeout(Action fn, double ms)
    {
        var t = new Timer { Due = _now() + Math.Max(0, ms), Seq = _seq++, Fn = fn };
        _timers.Add(t);
        return t;
    }

    public void ClearTimeout(object? handle)
    {
        if (handle is Timer t)
        {
            t.Cancelled = true;
            _timers.Remove(t);
        }
    }

    /// <summary>Timers still pending.</summary>
    public int Pending => _timers.Count;

    /// <summary>The earliest due time of a pending timer, or null (a simulated host advances to it).</summary>
    public double? NextDue => _timers.Count == 0 ? null : _timers.Min(t => t.Due);

    /// <summary>Fire every timer due at the current time; returns how many fired.</summary>
    public int Pump()
    {
        int fired = 0;
        while (true)
        {
            double now = _now();
            Timer? next = null;
            foreach (var t in _timers)
                if (t.Due <= now && (next is null || t.Due < next.Due || (t.Due == next.Due && t.Seq < next.Seq)))
                    next = t;
            if (next is null) return fired;
            _timers.Remove(next);
            if (next.Cancelled) continue;
            fired++;
            next.Fn();
        }
    }
}

/// <summary>A hand-moved clock for tests and checks.</summary>
public sealed class ManualClock
{
    public double Ms { get; private set; }
    public ManualClock(double start = 0) => Ms = start;
    public void Set(double ms) => Ms = ms;
    public void Advance(double ms) => Ms += ms;
}
