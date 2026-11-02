using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.Reflection;
using System.Runtime.CompilerServices;
using System.Threading;
using Godot;

namespace AnimaNative.Ui;

/// <summary>Per-frame main-thread wall times and slow synchronous steps. Worker marks are ignored.
/// Process/physics bracket node callbacks; Godot drains posted C# continuations after rendering, outside those
/// brackets. Continuations are a separate attribution, also included in rest = frame − process − physics − render CPU.
/// Signal awaiters run inline at the signal site (e.g. process_frame before the first probe); those remain in rest
/// or the enclosing phase/mark. Marks and continuations may overlap phases and must not be added to them.</summary>
public static class HitchLog
{
    public const double HitchMs = 50, MarkMinMs = 2;
    private const int MaxLines = 300;
    private static readonly List<(string What, double Ms)> Marks = new();
    private static readonly Dictionary<string, double> Continuations = new(StringComparer.Ordinal);
    private static readonly Dictionary<string, int> TopMarks = new(StringComparer.Ordinal);
    private static readonly List<double> Frames = new(), GpuFrames = new(), ProcessFrames = new(),
        ContinuationFrames = new(), RenderCpuFrames = new();
    private static int _mainThread = -1, _lines, _unfocused, _gc0, _gc1, _gc2, _epoch;
    private static Viewport? _viewport;
    private static Func<double> _clock = WallMs;
    private static Func<(double Cpu, double Gpu)> _renderTimes = ReadRenderTimes;
    private static double _summaryStart, _processStart, _physicsStart, _process, _physics, _continuations, _frameStart;
    private static ulong _frameId;
    private static bool _hasFrame;

    /// <summary>Boot and login intentionally run busy/throttled; arm only once the first figure poll completed.</summary>
    public static bool Armed { get; set; }
    private static bool OnMainThread => System.Environment.CurrentManagedThreadId == _mainThread;
    private static double WallMs() => Stopwatch.GetTimestamp() * (1000.0 / Stopwatch.Frequency);

    public static void Init(Viewport viewport, Func<double>? clock = null, Func<(double Cpu, double Gpu)>? renderTimes = null)
    {
        _epoch++;
        _viewport = viewport;
        _clock = clock ?? WallMs;
        _renderTimes = renderTimes ?? ReadRenderTimes;
        _summaryStart = _clock();
        _lines = _unfocused = 0; Armed = false; _hasFrame = false;
        Marks.Clear(); Continuations.Clear(); ClearWindow();
        _process = _physics = _continuations = 0;
        RenderingServer.ViewportSetMeasureRenderTime(viewport.GetViewportRid(), true);
        _mainThread = System.Environment.CurrentManagedThreadId;
        (_gc0, _gc1, _gc2) = (GC.CollectionCount(0), GC.CollectionCount(1), GC.CollectionCount(2));
    }

    /// <summary>Two scene-owned nodes bracket all node callbacks, including callbacks on the persistent HUD.
    /// Frame IDs let the first physics step (or process on a frame without physics) close the previous frame;
    /// multiple physics steps are summed into the same frame. Wall intervals include the scheduler after render.</summary>
    public static void Attach(Node scene, Action<string> log)
    {
        if (SynchronizationContext.Current is { } inner && inner is not TimedContext)
            SynchronizationContext.SetSynchronizationContext(new TimedContext(inner));
        scene.AddChild(new HitchPhaseProbe(true, log));
        scene.AddChild(new HitchPhaseProbe(false, log));
    }

    internal static void BeginFrame(ulong id, Action<string> log)
    {
        if (_hasFrame && id == _frameId) return;
        double now = _clock();
        if (_hasFrame) EndFrame(now - _frameStart, log);
        else { Marks.Clear(); Continuations.Clear(); _process = _physics = _continuations = 0; }
        _frameStart = now; _frameId = id; _hasFrame = true;
    }
    internal static void BeginProcess() => _processStart = _clock();
    internal static void EndProcess() => _process += _clock() - _processStart;
    internal static void BeginPhysics() => _physicsStart = _clock();
    internal static void EndPhysics() => _physics += _clock() - _physicsStart;

    /// <summary><c>using var _ = HitchLog.Time("what");</c> around one synchronous main-thread step.</summary>
    public static Scope Time(string what) => new(what);
    public readonly struct Scope : IDisposable
    {
        private readonly string _what;
        private readonly double _start;
        private readonly bool _main;
        private readonly int _epoch;
        public Scope(string what) { _what = what; _epoch = HitchLog._epoch; _main = OnMainThread; _start = _main ? _clock() : 0; }
        public void Dispose()
        {
            if (!_main || !OnMainThread || _epoch != HitchLog._epoch) return;
            double ms = _clock() - _start;
            if (ms >= MarkMinMs) Marks.Add((_what, ms));
        }
    }

    /// <summary>Close the measured frame, then clear all phase/mark accumulators, even while unarmed.</summary>
    public static void EndFrame(double frameMs, Action<string> log)
    {
        int g0 = GC.CollectionCount(0), g1 = GC.CollectionCount(1), g2 = GC.CollectionCount(2);
        if (Armed && frameMs > HitchMs)
        {
            var (renderCpu, gpu) = _renderTimes();
            bool focused = DisplayServer.WindowIsFocused();
            bool visible = DisplayServer.WindowGetMode() != DisplayServer.WindowMode.Minimized && DisplayServer.WindowCanDraw();
            Frames.Add(frameMs); GpuFrames.Add(gpu); ProcessFrames.Add(_process);
            ContinuationFrames.Add(_continuations); RenderCpuFrames.Add(renderCpu);
            if (!focused) _unfocused++;
            var top = Marks.GroupBy(m => m.What).Select(g => (What: g.Key, Ms: g.Sum(m => m.Ms), N: g.Count()))
                .OrderByDescending(m => m.Ms).ThenBy(m => m.What, StringComparer.Ordinal).Take(6).ToArray();
            foreach (var mark in top) TopMarks[mark.What] = TopMarks.GetValueOrDefault(mark.What) + 1;
            if (_lines < MaxLines)
            {
                _lines++;
                var markText = top.Select(m => m.N > 1 ? FormattableString.Invariant($"{m.What} {m.Ms:0.#} ms ×{m.N}")
                    : FormattableString.Invariant($"{m.What} {m.Ms:0.#} ms"));
                var callbacks = Continuations.OrderByDescending(m => m.Value).ThenBy(m => m.Key, StringComparer.Ordinal)
                    .Take(3).Select(m => FormattableString.Invariant($"{m.Key} {m.Value:0.#} ms"));
                float scale = _viewport?.Scaling3DScale ?? 1;
                double rest = frameMs - _process - _physics - renderCpu;
                log(FormattableString.Invariant($"hitch {frameMs:0.#} ms: marked {Marks.Sum(m => m.Ms):0.#} ms [{string.Join("; ", markText)}] gc {g0 - _gc0}/{g1 - _gc1}/{g2 - _gc2} process {_process:0.#} ms, physics {_physics:0.#} ms, continuations {_continuations:0.#} ms [{string.Join("; ", callbacks)}], render cpu {renderCpu:0.#} ms, gpu {gpu:0.#} ms, rest {rest:0.#} ms, render scale {scale:0.00}, focus {(focused ? "yes" : "no")}, visible {(visible ? "yes" : "no")}"));
            }
        }
        double now = _clock();
        if (now - _summaryStart >= 60000)
        {
            if (Frames.Count > 0)
            {
                var names = TopMarks.OrderByDescending(m => m.Value).ThenBy(m => m.Key, StringComparer.Ordinal)
                    .Take(6).Select(m => $"{m.Key} {m.Value}×");
                log(FormattableString.Invariant($"hitches 60 s: n={Frames.Count}, unfocused={_unfocused}, p50 frame {Median(Frames):0.#} ms, p50 process {Median(ProcessFrames):0.#} ms, p50 continuations {Median(ContinuationFrames):0.#} ms, p50 render cpu {Median(RenderCpuFrames):0.#} ms, p50 gpu {Median(GpuFrames):0.#} ms, top: {string.Join(", ", names)}"));
            }
            ClearWindow(); _unfocused = 0; _summaryStart = now;
        }
        Marks.Clear(); Continuations.Clear(); _process = _physics = _continuations = 0;
        (_gc0, _gc1, _gc2) = (g0, g1, g2);
    }
    private static (double Cpu, double Gpu) ReadRenderTimes() => _viewport is not null && GodotObject.IsInstanceValid(_viewport)
        ? (RenderingServer.ViewportGetMeasuredRenderTimeCpu(_viewport.GetViewportRid()),
           RenderingServer.ViewportGetMeasuredRenderTimeGpu(_viewport.GetViewportRid())) : (0, 0);
    private static void ClearWindow()
    {
        Frames.Clear(); GpuFrames.Clear(); ProcessFrames.Clear(); ContinuationFrames.Clear(); RenderCpuFrames.Clear(); TopMarks.Clear();
    }
    private static double Median(List<double> values)
    {
        values.Sort();
        int middle = values.Count / 2;
        return values.Count % 2 == 0 ? (values[middle - 1] + values[middle]) / 2 : values[middle];
    }

    /// <summary>Keep Godot's queue, ordering and exception path. Set the decorator while invoking callbacks so
    /// subsequent awaits capture it too. Names are resolved/cached on the main thread, never on posting workers.</summary>
    internal sealed class TimedContext : SynchronizationContext
    {
        private readonly SynchronizationContext _inner;
        private readonly Dictionary<Type, string?> _asyncNames = new();
        private readonly Dictionary<MethodInfo, string> _methodNames = new();
        private double _childrenMs;
        private int _depth;
        public TimedContext(SynchronizationContext inner) => _inner = inner;
        public override SynchronizationContext CreateCopy() => this;
        public override void OperationStarted() => _inner.OperationStarted();
        public override void OperationCompleted() => _inner.OperationCompleted();
        private sealed record Work(TimedContext Owner, SendOrPostCallback Callback, object? State);
        private static readonly SendOrPostCallback Run = state =>
        {
            var work = (Work)state!;
            work.Owner.Invoke(work.Callback, work.State);
        };
        public override void Post(SendOrPostCallback d, object? state) => _inner.Post(Run, new Work(this, d, state));
        public override void Send(SendOrPostCallback d, object? state)
        {
            var previous = Current;
            // Godot's Send inlines only when Current == inner. Preserve that test on the main thread;
            // doing this on a worker would incorrectly run its callback there instead of blocking on Godot.
            if (OnMainThread && previous == this) SetSynchronizationContext(_inner);
            try { _inner.Send(Run, new Work(this, d, state)); }
            finally { SetSynchronizationContext(previous); }
        }
        private void Invoke(SendOrPostCallback d, object? state)
        {
            if (!OnMainThread) { d(state); return; }
            string name = NameOf(d, state);
            var previous = Current;
            SetSynchronizationContext(this);
            int epoch = _epoch;
            double start = _clock(), parentChildren = _childrenMs;
            _childrenMs = 0; _depth++;
            try { d(state); }
            finally
            {
                double ms = _clock() - start, own = ms - _childrenMs;
                if (--_depth == 0)
                {
                    if (epoch == _epoch) _continuations += ms;
                    _childrenMs = 0;
                }
                else _childrenMs = parentChildren + ms;
                // A scene reload/check can reinitialize the logger inside this callback.
                if (epoch == _epoch) Continuations[name] = Continuations.GetValueOrDefault(name) + own;
                SetSynchronizationContext(previous);
            }
        }
        private string NameOf(Delegate callback, object? state)
        {
            // .NET await callbacks commonly post a static trampoline with an Action or an
            // AsyncStateMachineBox<TStateMachine> as state. Inspect types only, never read/box the machine.
            string? name = AsyncName(callback.Target?.GetType());
            if (name is not null) return name;
            if (state is Delegate continuation)
            {
                name = AsyncName(continuation.Target?.GetType());
                if (name is not null) return name;
            }
            name = AsyncName(state?.GetType());
            if (name is not null) return name;
            var method = callback.Method;
            if (!_methodNames.TryGetValue(method, out name))
                _methodNames[method] = name = $"{method.DeclaringType?.Name ?? "?"}.{method.Name}";
            return name;
        }
        private string? AsyncName(Type? type)
        {
            if (type is null) return null;
            if (_asyncNames.TryGetValue(type, out var cached)) return cached;
            Type? machine = typeof(IAsyncStateMachine).IsAssignableFrom(type) ? type
                : type.IsGenericType ? type.GetGenericArguments().FirstOrDefault(t => typeof(IAsyncStateMachine).IsAssignableFrom(t)) : null;
            string? name = null;
            if (machine is not null && machine.Name.StartsWith('<') && machine.Name.IndexOf('>') is int end && end > 1)
                name = $"{machine.DeclaringType?.Name ?? "?"}.{machine.Name[1..end]}";
            _asyncNames[type] = name;
            return name;
        }
    }
}

/// <summary>Created in code; no separate scene/script resource. Both priorities cover the scene's default process group.</summary>
internal partial class HitchPhaseProbe : Node
{
    private readonly bool _first;
    private readonly Action<string> _log;
    public HitchPhaseProbe(bool first, Action<string> log)
    {
        _first = first; _log = log;
        Name = first ? "HitchFirst" : "HitchLast";
        ProcessPriority = ProcessPhysicsPriority = first ? int.MinValue : int.MaxValue;
        ProcessMode = ProcessModeEnum.Always;
    }
    public override void _Process(double delta)
    {
        if (_first) { HitchLog.BeginFrame(Engine.GetProcessFrames(), _log); HitchLog.BeginProcess(); }
        else HitchLog.EndProcess();
    }
    public override void _PhysicsProcess(double delta)
    {
        if (_first) { HitchLog.BeginFrame(Engine.GetProcessFrames(), _log); HitchLog.BeginPhysics(); }
        else HitchLog.EndPhysics();
    }
}
