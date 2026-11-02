using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using AnimaNative.Ui;
using Godot;

namespace AnimaNative.Check;

/// <summary>Hand-derived wall times on a fixture clock; no sleeps, world or Performance.TimeProcess monitor.</summary>
public static class HitchCheck
{
    public static int Run(Viewport viewport)
    {
        int count = 0;
        void Require(string label, bool ok) { if (!ok) throw new InvalidOperationException("hitch: " + label); count++; }
        var lines = new List<string>();
        double now = 0, renderCpu = 4, gpu = 15;
        void Reset()
        {
            now = 0; lines.Clear();
            HitchLog.Init(viewport, () => now, () => (renderCpu, gpu)); HitchLog.Armed = true;
        }
        float oldScale = viewport.Scaling3DScale;
        var previous = SynchronizationContext.Current;
        try
        {
            Reset();
            viewport.Scaling3DScale = .7f;
            // Two physics steps of 3 and 5 ms, followed by 12 ms of node processing; 100−12−8−4 = 76 ms rest.
            HitchLog.BeginPhysics(); now += 3; HitchLog.EndPhysics();
            HitchLog.BeginPhysics(); now += 5; HitchLog.EndPhysics();
            HitchLog.BeginProcess(); now += 12; HitchLog.EndProcess();
            HitchLog.EndFrame(100, lines.Add);
            Require("phase arithmetic", lines.Single().Contains("process 12 ms, physics 8 ms, continuations 0 ms [], render cpu 4 ms, gpu 15 ms, rest 76 ms"));
            Require("effective viewport scale", lines[0].Contains("render scale 0.70"));
            Require("focus and visibility", lines[0].Contains("focus ") && lines[0].Contains("visible "));
            viewport.Scaling3DScale = 1;
            HitchLog.EndFrame(60, lines.Add);
            Require("effective scale follows resize", lines[1].Contains("render scale 1.00"));
            Require("frame accumulators cleared", lines[1].Contains("process 0 ms, physics 0 ms, continuations 0 ms []"));
            HitchLog.BeginProcess(); now += 80; HitchLog.EndProcess(); HitchLog.EndFrame(60, lines.Add);
            Require("rest is not clamped or interpreted", lines[2].Contains("rest -24 ms"));

            // An engine frame ID, not the number of physics ticks, owns the wall interval.
            Reset();
            HitchLog.BeginFrame(7, lines.Add); HitchLog.BeginPhysics(); now = 3; HitchLog.EndPhysics();
            HitchLog.BeginFrame(7, lines.Add); HitchLog.BeginPhysics(); now = 8; HitchLog.EndPhysics();
            HitchLog.BeginFrame(7, lines.Add); HitchLog.BeginProcess(); now = 20; HitchLog.EndProcess();
            now = 100; HitchLog.BeginFrame(8, lines.Add);
            Require("physics before process belongs to the same frame", lines.Single().Contains("hitch 100 ms:") && lines[0].Contains("process 12 ms, physics 8 ms"));
            HitchLog.BeginProcess(); now = 107; HitchLog.EndProcess();
            now = 160; HitchLog.BeginFrame(9, lines.Add);
            Require("a frame without physics has zero physics time", lines[1].Contains("process 7 ms, physics 0 ms"));

            Reset();
            using var inner = new GodotSynchronizationContext();
            var context = new HitchLog.TimedContext(inner);
            SynchronizationContext.SetSynchronizationContext(context);
            var order = new List<int>();
            int mainThread = System.Environment.CurrentManagedThreadId;
            SendOrPostCallback lambda = state => { Require("posted state and main thread", ReferenceEquals(state, order) && System.Environment.CurrentManagedThreadId == mainThread); order.Add(1); now += 7; };
            context.Post(lambda, order);
            Require("Post is queued", order.Count == 0);
            // Pump under the inner context: the decorator must install itself for callbacks and nested awaits.
            SynchronizationContext.SetSynchronizationContext(inner);
            inner.ExecutePendingContinuations();
            Require("Post restores pump context", SynchronizationContext.Current == inner);
            SynchronizationContext.SetSynchronizationContext(context);
            context.Send(state => { Require("Send forwards state", ReferenceEquals(state, order)); order.Add(2); now += 3; }, order);
            Require("Send is synchronous and restores decorator", order.SequenceEqual(new[] { 1, 2 }) && SynchronizationContext.Current == context);
            HitchLog.EndFrame(100, lines.Add);
            Require("posted lambda attribution", lines[0].Contains($"{lambda.Method.DeclaringType!.Name}.{lambda.Method.Name} 7 ms"));
            Require("Post and Send total", lines[0].Contains("continuations 10 ms"));

            Reset();
            // Task.Yield posts a runtime trampoline; name its async state machine, not the trampoline.
            var task = NamedAsync(() => now += 5, order, mainThread, context);
            Require("async method suspended", !task.IsCompleted);
            inner.ExecutePendingContinuations(); task.GetAwaiter().GetResult();
            HitchLog.EndFrame(100, lines.Add);
            Require("async method name through runtime callback", lines.Single().Contains("HitchCheck.NamedAsync 10 ms"));
            Require("nested awaits keep decorator, order and main thread", order.SequenceEqual(new[] { 1, 2, 3, 4 }));

            Reset();
            var gate = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
            var awaited = AwaitWorkerAsync(gate.Task, () => now += 9, mainThread, context);
            Task.Run(() => gate.SetResult()).GetAwaiter().GetResult();
            inner.ExecutePendingContinuations(); awaited.GetAwaiter().GetResult();
            HitchLog.EndFrame(100, lines.Add);
            Require("worker-completed Task returns to main thread with method name", lines.Single().Contains("HitchCheck.AwaitWorkerAsync 9 ms"));

            Reset();
            context.Post(_ => { now += 5; context.Send(__ => now += 3, null); now += 2; }, null);
            inner.ExecutePendingContinuations(); HitchLog.EndFrame(100, lines.Add);
            Require("nested Send does not double count continuation wall time", lines.Single().Contains("continuations 10 ms"));

            Reset();
            context.Post(Alpha, null); context.Post(Beta, null); context.Post(Gamma, null); context.Post(Delta, null);
            // Named delegates use state for clock advancement; the duplicate aggregates before top-three selection.
            void PostTimed(SendOrPostCallback callback, double ms) => context.Post(callback, (Action)(() => now += ms));
            inner.ExecutePendingContinuations();
            PostTimed(Alpha, 1); PostTimed(Beta, 6); PostTimed(Gamma, 4); PostTimed(Delta, 3); PostTimed(Alpha, 8);
            inner.ExecutePendingContinuations(); HitchLog.EndFrame(100, lines.Add);
            string top = lines.Single().Split("continuations ")[1].Split('[')[1].Split(']')[0];
            Require("top three aggregate and sort", top == "HitchCheck.Alpha 9 ms; HitchCheck.Beta 6 ms; HitchCheck.Gamma 4 ms");
            Require("total includes fourth name and subthreshold callback", lines[0].Contains("continuations 22 ms"));

            Reset();
            var error = new InvalidOperationException("fixture");
            context.Post(_ => { now += 5; throw error; }, null);
            context.Post(_ => order.Add(5), null);
            Exception? caught = null;
            try { inner.ExecutePendingContinuations(); } catch (Exception e) { caught = e; }
            Require("Post exception identity and context unchanged", ReferenceEquals(caught, error) && SynchronizationContext.Current == context);
            Require("exception stops the inner pump unchanged", !order.Contains(5));
            inner.ExecutePendingContinuations();
            Require("subsequent Post retained in order", order.Last() == 5);
            caught = null;
            try { context.Send(_ => { now += 2; throw error; }, null); } catch (Exception e) { caught = e; }
            Require("Send exception identity and context unchanged", ReferenceEquals(caught, error) && SynchronizationContext.Current == context);
            HitchLog.EndFrame(100, lines.Add);
            Require("throwing callbacks are timed", lines.Single().Contains("continuations 7 ms"));

            Reset();
            context.Post(_ => { now += 5; HitchLog.Init(viewport, () => now, () => (renderCpu, gpu)); HitchLog.Armed = true; now += 7; }, null);
            inner.ExecutePendingContinuations(); HitchLog.EndFrame(100, lines.Add);
            Require("a reset discards an in-flight old-session callback", lines.Single().Contains("continuations 0 ms []"));

            // Send from a worker must enter Godot's queue and wait for the main thread, never run on that worker.
            Reset();
            using var sendInner = new GodotSynchronizationContext();
            var sendContext = new HitchLog.TimedContext(sendInner);
            int sentOn = -1;
            var sender = Task.Run(() => sendContext.Send(_ => { sentOn = System.Environment.CurrentManagedThreadId; now += 6; }, null));
            Require("worker Send returns after the main-thread pump", SpinWait.SpinUntil(() =>
            {
                sendInner.ExecutePendingContinuations();
                return sender.IsCompleted;
            }, 5000));
            sender.GetAwaiter().GetResult();
            Require("worker Send dispatches on main thread", sentOn == mainThread);
            HitchLog.EndFrame(100, lines.Add);
            Require("worker Send callback measured", lines.Single().Contains("continuations 6 ms"));

            Reset();
            Exception? workerCaught = null;
            var throwingSender = Task.Run(() => sendContext.Send(_ => { now += 4; throw error; }, null));
            Require("worker Send completes after its callback throws on main", SpinWait.SpinUntil(() =>
            {
                try { sendInner.ExecutePendingContinuations(); } catch (Exception e) { workerCaught = e; }
                return throwingSender.IsCompleted;
            }, 5000));
            throwingSender.GetAwaiter().GetResult();
            Require("worker Send keeps Godot's main-thread exception identity", ReferenceEquals(workerCaught, error));
            HitchLog.EndFrame(100, lines.Add);
            Require("throwing worker Send is timed", lines.Single().Contains("continuations 4 ms"));
            Reset();
            Task.Run(() => { using var mark = HitchLog.Time("worker mark"); }).GetAwaiter().GetResult();
            HitchLog.EndFrame(100, lines.Add);
            Require("worker marks ignored", !lines.Single().Contains("worker mark"));

            Reset();
            // Hitch-only window, per-frame deduplicated top marks; medians of [10,40,20,30] and [2,8,4,6].
            double[] process = { 10, 40, 20, 30 }, callbacks = { 2, 8, 4, 6 };
            for (int i = 0; i < 4; i++)
            {
                renderCpu = new[] { 1d, 7, 3, 5 }[i]; gpu = new[] { 10d, 40, 20, 30 }[i];
                HitchLog.BeginProcess(); now += process[i]; HitchLog.EndProcess();
                PostTimed(Alpha, callbacks[i]); inner.ExecutePendingContinuations();
                using (HitchLog.Time("FigureManager")) now += 3;
                using (HitchLog.Time("FigureManager")) now += 2;
                if (i < 2) using (HitchLog.Time("worldmap parse")) now += 4;
                using (HitchLog.Time("silent")) now += 1.99;
                HitchLog.EndFrame(100, lines.Add);
            }
            now = 60000; HitchLog.EndFrame(16, lines.Add);
            Require("window medians", lines[4].Contains("p50 process 25 ms, p50 continuations 5 ms, p50 render cpu 4 ms, p50 gpu 25 ms"));
            Require("top mark frequency counts frames, not nested calls", lines[4].EndsWith("top: FigureManager 4×, worldmap parse 2×"));
            Require("subthreshold marks silent", !lines.Any(l => l.Contains("silent")));
            now = 120000; HitchLog.EndFrame(16, lines.Add);
            Require("quiet window does not log", lines.Count == 5);
            HitchLog.EndFrame(200, lines.Add); now = 180000; HitchLog.EndFrame(16, lines.Add);
            Require("window resets medians and top names", lines[6].Contains("n=1,") && lines[6].Contains("p50 process 0 ms") && !lines[6].Contains("FigureManager"));

            Reset();
            for (int i = 0; i < 350; i++) HitchLog.EndFrame(100, lines.Add);
            Require("detail cap", lines.Count == 300);
            now = 60000; HitchLog.EndFrame(16, lines.Add);
            Require("summary continues past detail cap", lines.Count == 301 && lines[300].StartsWith($"hitches 60 s: n=350, unfocused={(DisplayServer.WindowIsFocused() ? 0 : 350)},"));
            HitchLog.Armed = false;
            using (HitchLog.Time("unarmed")) now += 10;
            HitchLog.EndFrame(200, lines.Add);
            now = 120000; HitchLog.EndFrame(16, lines.Add);
            Require("unarmed frame stays silent", lines.Count == 301);
            Reset(); HitchLog.Armed = false;
            HitchLog.BeginProcess(); now += 9; HitchLog.EndProcess();
            HitchLog.EndFrame(100, lines.Add); HitchLog.Armed = true; HitchLog.EndFrame(100, lines.Add);
            Require("unarmed data cannot leak into armed frame", lines.Single().Contains("process 0 ms"));
            return count;
        }
        finally
        {
            SynchronizationContext.SetSynchronizationContext(previous);
            viewport.Scaling3DScale = oldScale; HitchLog.Init(viewport);
        }
    }

    /// <summary>Exercise the installed startup decorator and both real priority probes in the engine loop.</summary>
    public static async Task<int> RunLiveAsync(Node host)
    {
        var viewport = host.GetViewport();
        var context = SynchronizationContext.Current;
        int thread = System.Environment.CurrentManagedThreadId;
        if (context is not HitchLog.TimedContext) throw new InvalidOperationException("hitch startup decorator missing");
        double now = 0;
        var lines = new List<string>();
        HitchLog.Init(viewport, () => now, () => (4, 15));
        var scene = new Node();
        var work = new HitchFixtureWork(() => now += 70, () => now += 3);
        var startupProbes = host.GetChildren().OfType<HitchPhaseProbe>().ToArray();
        foreach (var probe in startupProbes) { probe.SetProcess(false); probe.SetPhysicsProcess(false); }
        host.AddChild(scene);
        HitchLog.Attach(scene, lines.Add);
        scene.AddChild(work);
        HitchLog.Armed = true;
        try
        {
            // Signal awaiters resume before the first process probe. Queued Task continuations run after render.
            await host.ToSignal(host.GetTree(), SceneTree.SignalName.ProcessFrame);
            await LiveContinuationAsync(() => now += 9, thread, context);
            for (int i = 0; i < 3; i++) await host.ToSignal(host.GetTree(), SceneTree.SignalName.ProcessFrame);
            if (!lines.Any(l => l.Contains("process 70 ms,") && l.Contains("HitchCheck.LiveContinuationAsync 9 ms")))
                throw new InvalidOperationException("hitch live process bracket / post-render continuation missing: " + string.Join(" | ", lines));
            if (!lines.Any(l => l.Contains("physics 3 ms,") || l.Contains("physics 6 ms,")))
                throw new InvalidOperationException("hitch live physics brackets missing: " + string.Join(" | ", lines));
            return 3;
        }
        finally
        {
            host.RemoveChild(scene); scene.Free();
            foreach (var probe in startupProbes) { probe.SetProcess(true); probe.SetPhysicsProcess(true); }
            HitchLog.Init(viewport);
        }
    }
    private static async Task LiveContinuationAsync(Action advance, int thread, SynchronizationContext? context)
    {
        await Task.Yield();
        if (System.Environment.CurrentManagedThreadId != thread || SynchronizationContext.Current != context)
            throw new InvalidOperationException("hitch engine await lost main thread/decorator");
        advance();
    }

    private static void Alpha(object? state) => (state as Action)?.Invoke();
    private static void Beta(object? state) => (state as Action)?.Invoke();
    private static void Gamma(object? state) => (state as Action)?.Invoke();
    private static void Delta(object? state) => (state as Action)?.Invoke();
    private static async Task NamedAsync(Action advance, List<int> order, int thread, SynchronizationContext context)
    {
        await Task.Yield();
        if (System.Environment.CurrentManagedThreadId != thread || SynchronizationContext.Current != context)
            throw new InvalidOperationException("first await lost main thread/decorator");
        order.Add(3); advance();
        await Task.Yield();
        if (System.Environment.CurrentManagedThreadId != thread || SynchronizationContext.Current != context)
            throw new InvalidOperationException("nested await lost main thread/decorator");
        order.Add(4); advance();
    }
    private static async Task AwaitWorkerAsync(Task gate, Action advance, int thread, SynchronizationContext context)
    {
        await gate;
        if (System.Environment.CurrentManagedThreadId != thread || SynchronizationContext.Current != context)
            throw new InvalidOperationException("worker completion lost main thread/decorator");
        advance();
    }

}

/// <summary>Fixture work between the actual min/max-priority probes, on a hand-driven clock.</summary>
internal partial class HitchFixtureWork : Node
{
    private readonly Action _process, _physics;
    public HitchFixtureWork(Action process, Action physics) { _process = process; _physics = physics; }
    public override void _Process(double delta) => _process();
    public override void _PhysicsProcess(double delta) => _physics();
}
