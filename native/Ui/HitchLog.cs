using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using Godot;

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
    private static Viewport? _viewport;
    private static Func<double> _clock = () => Godot.Time.GetTicksMsec();
    private static double _summaryStart;
    private static readonly List<double> Frames = new(), GpuFrames = new();
    private static int _unfocused;

    /// <summary>Frames count only once the world is up: the login screen and the boot run throttled or busy on
    /// purpose (the first field run spent all <see cref="MaxLines"/> lines on the ~7 fps login screen).</summary>
    public static bool Armed { get; set; }

    /// <summary>Called once from the main thread before the first frame.</summary>
    public static void Init(Viewport viewport, Func<double>? clock = null)
    {
        _viewport = viewport;
        _clock = clock ?? (() => Godot.Time.GetTicksMsec());
        _summaryStart = _clock();
        _lines = _unfocused = 0; Armed = false;
        Marks.Clear(); Frames.Clear(); GpuFrames.Clear();
        RenderingServer.ViewportSetMeasureRenderTime(viewport.GetViewportRid(), true);
        _mainThread = System.Environment.CurrentManagedThreadId;
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
            if (System.Environment.CurrentManagedThreadId != _mainThread) return;
            double ms = Stopwatch.GetElapsedTime(_start).TotalMilliseconds;
            if (ms >= MarkMinMs) Marks.Add((_what, ms));
        }
    }

    /// <summary>End of a frame of <paramref name="frameMs"/>: log it when it is a hitch, then start the next frame.</summary>
    public static void EndFrame(double frameMs, Action<string> log)
    {
        int g0 = GC.CollectionCount(0), g1 = GC.CollectionCount(1), g2 = GC.CollectionCount(2);
        if (Armed && frameMs > HitchMs)
        {
            double gpu = _viewport is not null && GodotObject.IsInstanceValid(_viewport)
                ? RenderingServer.ViewportGetMeasuredRenderTimeGpu(_viewport.GetViewportRid()) : 0;
            bool focused = DisplayServer.WindowIsFocused();
            bool visible = DisplayServer.WindowGetMode() != DisplayServer.WindowMode.Minimized && DisplayServer.WindowCanDraw();
            Frames.Add(frameMs); GpuFrames.Add(gpu);
            if (!focused) _unfocused++;
            if (_lines < MaxLines)
            {
                _lines++;
                double marked = Marks.Sum(m => m.Ms);
                var top = Marks.GroupBy(m => m.What).Select(g => (What: g.Key, Ms: g.Sum(m => m.Ms), N: g.Count()))
                    .OrderByDescending(m => m.Ms).Take(6)
                    .Select(m => m.N > 1 ? $"{m.What} {m.Ms:0.#} ms ×{m.N}" : $"{m.What} {m.Ms:0.#} ms");
                float scale = _viewport?.Scaling3DScale ?? 1;
                log(FormattableString.Invariant($"hitch {frameMs:0.#} ms: marked {marked:0.#} ms [{string.Join("; ", top)}] gc {g0 - _gc0}/{g1 - _gc1}/{g2 - _gc2} gpu {gpu:0.#} ms, render scale {scale:0.00}, focus {(focused ? "yes" : "no")}, visible {(visible ? "yes" : "no")}"));
            }
        }
        double now = _clock();
        if (now - _summaryStart >= 60000)
        {
            if (Frames.Count > 0)
                log(FormattableString.Invariant($"hitches 60 s: n={Frames.Count}, unfocused={_unfocused}, p50 frame {Median(Frames):0.#} ms, p50 gpu {Median(GpuFrames):0.#} ms"));
            Frames.Clear(); GpuFrames.Clear(); _unfocused = 0; _summaryStart = now;
        }
        Marks.Clear();
        (_gc0, _gc1, _gc2) = (g0, g1, g2);
    }
    private static double Median(List<double> values)
    {
        values.Sort();
        int middle = values.Count / 2;
        return values.Count % 2 == 0 ? (values[middle - 1] + values[middle]) / 2 : values[middle];
    }
}
