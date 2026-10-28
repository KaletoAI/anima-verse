using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;

namespace AnimaNative.Ui;

/// <summary>
/// Where a long frame went (user report 2026-10-28: "weniger ruckeln" after the billboard shader fix, a 1.7 s session
/// maximum still unexplained). Known heavy main-thread work reports its duration through <see cref="Time"/>; the main
/// loop calls <see cref="EndFrame"/> once per frame, and a frame over <see cref="HitchMs"/> logs one line with the
/// biggest marks and the GC collections of that frame. Main thread only: marks from other threads are ignored.
/// </summary>
public static class HitchLog
{
    public const double HitchMs = 50, MarkMinMs = 2;
    private const int MaxLines = 300;

    private static readonly List<(string What, double Ms)> Marks = new();
    private static int _mainThread = -1, _lines;
    private static int _gc0, _gc1, _gc2;

    /// <summary>Called once from the main thread before the first frame.</summary>
    public static void Init()
    {
        _mainThread = Environment.CurrentManagedThreadId;
        (_gc0, _gc1, _gc2) = (GC.CollectionCount(0), GC.CollectionCount(1), GC.CollectionCount(2));
    }

    /// <summary><c>using var _ = HitchLog.Time("what");</c> around one synchronous main-thread step.</summary>
    public static Scope Time(string what) => new(what);

    public readonly struct Scope : IDisposable
    {
        private readonly string _what;
        private readonly long _start;
        public Scope(string what) { _what = what; _start = Stopwatch.GetTimestamp(); }
        public void Dispose()
        {
            if (Environment.CurrentManagedThreadId != _mainThread) return;
            double ms = Stopwatch.GetElapsedTime(_start).TotalMilliseconds;
            if (ms >= MarkMinMs) Marks.Add((_what, ms));
        }
    }

    /// <summary>End of a frame of <paramref name="frameMs"/>: log it when it is a hitch, then start the next frame.</summary>
    public static void EndFrame(double frameMs, Action<string> log)
    {
        int g0 = GC.CollectionCount(0), g1 = GC.CollectionCount(1), g2 = GC.CollectionCount(2);
        if (frameMs > HitchMs && _lines < MaxLines)
        {
            _lines++;
            double marked = Marks.Sum(m => m.Ms);
            var top = Marks.GroupBy(m => m.What).Select(g => (What: g.Key, Ms: g.Sum(m => m.Ms), N: g.Count()))
                .OrderByDescending(m => m.Ms).Take(6)
                .Select(m => m.N > 1 ? $"{m.What} {m.Ms:0.#} ms ×{m.N}" : $"{m.What} {m.Ms:0.#} ms");
            log($"hitch {frameMs:0.#} ms: marked {marked:0.#} ms [{string.Join("; ", top)}] gc {g0 - _gc0}/{g1 - _gc1}/{g2 - _gc2}");
        }
        Marks.Clear();
        (_gc0, _gc1, _gc2) = (g0, g1, g2);
    }
}
