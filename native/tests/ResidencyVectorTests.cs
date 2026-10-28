using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using AnimaNative.Figures;
using AnimaNative.Scene;
using AnimaNative.Sync;
using AnimaNative.Tests.Vectors;
using AnimaNative.World;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>
/// Task 44 / P3-R21: interprets shared/test-vectors/residency.json verbatim, like the TS
/// residencyVectorDispatch adapter. Oracles stay in the shared file; this harness only supplies gates,
/// a single-thread event loop and observable mounts. Catches stale publication, premature settlement,
/// unbounded work, lost retries and a forgotten scene resurrecting its cache.
/// </summary>
public class ResidencyVectorTests
{
    private static readonly VectorFile File = VectorFile.Load("residency");
    public static TheoryData<string> Cases => VectorFile.Labels("residency");

    [Theory]
    [MemberData(nameof(Cases))]
    public void Case(string label) => SingleThread.Run(async () =>
    {
        var c = File.Case(label);
        var a = File.ResolveArgs(c);
        var actual = await Scenario(a[0]!.GetValue<string>(), (JsonArray)a[1]!);
        Assert.True(VectorCompare.Near(c.Expect, actual, c.Eps, out var diff), $"{label}: {diff}");
    });

    /// <summary>Task 44: real TimerQueue retries at 5/10/20/40/60 s, holds at 60, then recovers without a new wish.</summary>
    [Fact]
    public void RetryBackoffCapsAndRecovers() => SingleThread.Run(async () =>
    {
        var clock = new ManualClock();
        var timers = new TimerQueue(() => clock.Ms);
        bool recover = false;
        int calls = 0;
        var driver = new ResidencyDriver<int>((_, _, _, _) =>
        { calls++; return Task.FromResult(recover ? ResidencyStep.Ok : ResidencyStep.Failed); },
            (_, _, _) => { }, new FocusQueue(2), timers);
        driver.Want("X", 1, Ring.Far, () => 0);
        int attempts = 0;
        foreach (var delay in new[] { 5000, 10000, 20000, 40000, 60000, 60000 })
        {
            await driver.WhenIdle();
            Assert.Equal(++attempts, calls);
            Assert.False(driver.HasJob("X"));
            Assert.False(driver.Settled("X").IsCompleted);
            Assert.Equal(clock.Ms + delay, timers.NextDue);
            clock.Advance(delay - 1); Assert.Equal(0, timers.Pump());
            clock.Advance(1); Assert.Equal(1, timers.Pump());
        }
        recover = true;
        await driver.Settled("X").WaitAsync(TimeSpan.FromSeconds(3));
        Assert.Equal(Ring.Far, driver.Ring("X"));
        Assert.Equal(0, timers.Pending);
    });

    private sealed class Timers : ISyncClock
    {
        public readonly List<(Action Fn, double Ms)> Pending = new();
        public double Now() => 0;
        public object SetTimeout(Action fn, double ms) { var h = (fn, ms); Pending.Add(h); return h; }
        public void ClearTimeout(object? h) { if (h is ValueTuple<Action, double> t) Pending.Remove(t); }
        public void Retry() { var t = Pending[0]; Pending.RemoveAt(0); t.Fn(); }
    }

    private static async Task Flush() { for (int i = 0; i < 100; i++) await Task.Yield(); }
    private static async Task Bound(Task t) => await t.WaitAsync(TimeSpan.FromSeconds(3));
    private static string Name(Ring r) => r.ToString().ToLowerInvariant();
    private static Ring RingOf(string s) => Enum.Parse<Ring>(s, true);

    private static async Task<JsonArray> Scenario(string kind, JsonArray steps)
    {
        var ids = new HashSet<string>();
        var gates = new Dictionary<string, TaskCompletionSource>();
        var wait = new Queue<TaskCompletionSource>();
        var calls = new JsonArray();
        var live = new Dictionary<string, int>();
        int active = 0, max = 0, rollback = 0, resolved = 0;
        bool fail = false;
        var timers = new Timers();
        var driver = new ResidencyDriver<int>(async (id, version, from, alive) =>
        {
            calls.Add(new JsonArray("up", id, version, Name(from)));
            max = Math.Max(max, ++active);
            if (wait.TryDequeue(out var gate)) await gate.Task;
            active--;
            if (!alive()) { rollback++; return ResidencyStep.Aborted; }
            if (fail) { fail = false; return ResidencyStep.Failed; }
            live[id] = version;
            return ResidencyStep.Ok;
        }, (id, version, from) =>
        {
            calls.Add(new JsonArray("down", id, version, Name(from)));
            if (from == Ring.Far) live.Remove(id);
        }, new FocusQueue(2), timers);
        var pending = new List<(string Id, TaskCompletionSource<string?> Reply)>();
        var events = new List<string>();
        var results = new JsonObject();
        var handles = new Dictionary<string, Task>();
        var library = new SceneLibrary<string>(id =>
        {
            var reply = new TaskCompletionSource<string?>();
            pending.Add((id, reply));
            return reply.Task;
        }, s => s);
        library.OnScene += (id, _) => events.Add(id);
        var snapshots = new JsonArray();
        foreach (var ops in steps.Cast<JsonArray>())
        {
            foreach (var op in ops.Cast<JsonArray>())
            {
                string S(int i) => op[i]!.GetValue<string>();
                int N(int i) => op[i]!.GetValue<int>();
                switch (S(0))
                {
                    case "gate": var g = new TaskCompletionSource(); gates[S(1)] = g; wait.Enqueue(g); break;
                    case "release": gates[S(1)].SetResult(); break;
                    case "want":
                        var id = S(1); var distance = op.Count > 4 ? N(4) : 0;
                        ids.Add(id); driver.Want(id, N(2), RingOf(S(3)), () => distance); break;
                    case "rebuild": driver.Rebuild(S(1), N(2)); break;
                    case "drop": driver.Drop(S(1)); break;
                    case "fail": fail = true; break;
                    case "flush": await Flush(); break;
                    case "settled": await Bound(driver.Settled(S(1))); break;
                    case "watch": _ = Watch(driver.Settled(S(1))); break;
                    case "retry": timers.Retry(); break;
                    case "sweep":
                        var names = ((JsonArray)op[2]!).Select(n => n!.GetValue<string>()).ToArray();
                        foreach (var name in names) ids.Add(name);
                        handles[S(1)] = library.Sweep(names); break;
                    case "request":
                        ids.Add(S(2)); var task = library.Request(S(2)); handles[S(1)] = task;
                        _ = Result(S(1), task); break;
                    case "forget": library.Forget(S(1)); break;
                    case "reply": pending[N(1)].Reply.SetResult(S(2)); break;
                    case "await": await Bound(handles[S(1)]); await Task.Yield(); break;
                    case "samePromise": results["samePromise"] = ReferenceEquals(handles[S(1)], handles[S(2)]); break;
                    default: throw new InvalidOperationException($"unknown op {op}");
                }
            }
            JsonObject Map<T>(Func<string, T> value)
            {
                var o = new JsonObject();
                foreach (var id in ids) o[id] = System.Text.Json.JsonSerializer.SerializeToNode(value(id));
                return o;
            }
            if (kind == "driver")
                snapshots.Add(new JsonObject
                {
                    ["rings"] = Map(id => Name(driver.Ring(id))), ["targets"] = Map(id => Name(driver.Target(id))),
                    ["jobs"] = Map(driver.HasJob), ["calls"] = calls.DeepClone(),
                    ["live"] = new JsonArray(live.Select(k => (JsonNode)new JsonArray(k.Key, k.Value)).ToArray()),
                    ["max"] = max, ["rollback"] = rollback, ["resolved"] = resolved,
                    ["timers"] = new JsonArray(timers.Pending.Select(t => (JsonNode)JsonValue.Create(t.Ms)!).ToArray()),
                });
            else
                snapshots.Add(new JsonObject
                {
                    ["pending"] = new JsonArray(pending.Select(p => (JsonNode)JsonValue.Create(p.Id)!).ToArray()),
                    ["events"] = new JsonArray(events.Select(e => (JsonNode)JsonValue.Create(e)!).ToArray()),
                    ["results"] = results.DeepClone(), ["cache"] = Map(library.Get),
                });
            calls.Clear();
        }
        return snapshots;
        async Task Watch(Task t) { await t; resolved++; }
        async Task Result(string key, Task<string?> t) { results[key] = await t; }
    }
}
