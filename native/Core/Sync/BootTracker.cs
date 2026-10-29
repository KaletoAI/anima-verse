using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using AnimaNative.Overview;

namespace AnimaNative.Sync;

/// <summary>
/// The line below the loading bar — <c>BootNote</c> of client3d/src/game/boot.ts: <c>retry</c> (the server did not
/// answer, the next attempt in <see cref="Seconds"/>), <c>failed</c> (the start threw), <c>characters</c> (the
/// world stands, the figures are still loading).
/// </summary>
public sealed record BootNote(string Kind, int? Seconds = null)
{
    public static BootNote Retry(int seconds) => new("retry", seconds);
    public static readonly BootNote Failed = new("failed");
    public static readonly BootNote Characters = new("characters");

    public JsonObject ToJson()
    {
        var o = new JsonObject { ["kind"] = Kind };
        if (Kind == "retry") o["seconds"] = Seconds ?? 0;
        return o;
    }
}

/// <summary>
/// The store of game/boot.ts on the native side: which of the six stages (<see cref="BootProgress.Stages"/>) are
/// through, the note, and the measurement report — published to the HUD as <c>{state, report}</c>
/// (<c>HudBoot</c> of bus.ts) on every change.
///   • <see cref="Report"/> is idempotent; stages may finish out of order, the label is the first missing one;
///   • <see cref="SetNote"/> ignores a note equal to the current one (the retry loop repeats the capped wait);
///   • the report carries the stage times (ms since construction = <c>markBootStart</c>); the phase sums stay 0
///     and the long-task fields null — the browser measures them with <c>PerformanceObserver</c>, which has no
///     counterpart in this client yet.
/// </summary>
public sealed class BootTracker
{
    /// <summary>The phases of <c>BootPhase</c>, all 0 in the native report.</summary>
    public static readonly IReadOnlyList<string> Phases = Array.AsReadOnly(new[]
    {
        "clip:download", "clip:parse", "clip:fit", "model:download", "model:build", "scene:fetch",
        "arrival:mount", "ground:fetch", "ground:build",
    });

    /// <summary>Task 62: bound by the app to the current source; no ambient/static state.</summary>
    public BootMeasurements? Measurements { get; set; }
    public Func<string>? CacheSummary { get; set; }
    private readonly Dictionary<string, string> _splits = new();
    private int _measured;
    private readonly Func<double> _now;
    private readonly double _start;
    private readonly HashSet<string> _done = new(StringComparer.Ordinal);
    private readonly Dictionary<string, double?> _times = BootProgress.Stages.ToDictionary(s => s, _ => (double?)null);

    public BootTracker(Func<double> nowMs)
    {
        _now = nowMs;
        _start = nowMs();
    }

    /// <summary>Fired after every change (a new stage, a different note).</summary>
    public event Action? Changed;

    public BootNote? Note { get; private set; }
    public BootProgress Progress => BootProgress.Of(_done);
    /// <summary>The finished stages in display order (<c>BOOT_STAGES.filter(done)</c>).</summary>
    public IReadOnlyList<string> Done => BootProgress.Stages.Where(_done.Contains).ToList();
    /// <summary>The stages in the order they were reported (for the log and the check).</summary>
    public List<string> Order { get; } = new();
    public double? TimeOf(string stage) => _times.GetValueOrDefault(stage);

    /// <summary><c>reportBootStage</c>: a stage is through; a repeat changes nothing.</summary>
    public void Report(string stage)
    {
        if (!_times.ContainsKey(stage)) throw new ArgumentException($"'{stage}' is not a boot stage");
        if (!_done.Add(stage)) return;
        _times[stage] = _now() - _start;
        if (Measurements is { } measurements)
        {
            var samples = measurements.Snapshot();
            _splits[stage] = BootMeasurements.Split(samples.Skip(_measured));
            _measured = samples.Length;
        }
        Order.Add(stage);
        if (_done.Count == BootProgress.Stages.Count) Measurements?.Stop();
        Changed?.Invoke();
    }

    /// <summary><c>setBootNote</c>: set or (null) clear the line below the bar; an equal note is no change.</summary>
    public void SetNote(BootNote? next)
    {
        if (Equals(Note, next)) return;
        Note = next;
        Changed?.Invoke();
    }

    /// <summary>The HUD's <c>HudBoot</c>: <c>{state: {percent, label, note, stages}, report}</c>.</summary>
    public JsonObject ToHud()
    {
        var p = Progress;
        var stages = new JsonArray();
        foreach (var s in Done) stages.Add(s);
        var times = new JsonObject();
        foreach (var s in BootProgress.Stages) times[s] = _times[s] is double ms ? JsonValue.Create(ms) : null;
        var phases = new JsonObject();
        foreach (var ph in Phases) phases[ph] = 0;
        return new JsonObject
        {
            ["state"] = new JsonObject
            {
                ["percent"] = p.Percent, ["label"] = p.Label, ["note"] = Note?.ToJson(), ["stages"] = stages,
            },
            ["report"] = new JsonObject
            {
                ["stages"] = times, ["phases"] = phases, ["longTasks"] = null,
                ["longTaskMaxByPhase"] = new JsonObject(), ["afterVisible"] = null,
            },
        };
    }

    /// <summary>TitleScreen's <c>stageText(label)</c>: what the client is doing right now, in words.</summary>
    public static string StageText(string label) => label switch
    {
        "world" => "Consulting the map…",
        "figures" => "Waking the inhabitants…",
        "scenes" => "Raising the buildings…",
        "tiles" => "Laying out the land…",
        "visible" => "Preparing the arrival…",
        "arrival" => "Finding your place…",
        _ => "Ready",
    };

    /// <summary>
    /// TitleScreen's <c>noteText(note)</c>; a failed start says how to retry HERE (the browser asks for a page
    /// reload, the native client goes back to its title).
    /// </summary>
    public static string NoteText(BootNote note) => note.Kind switch
    {
        "characters" => "Loading characters…",
        "failed" => "Start failed — go back to the title and log in again.",
        _ => $"The server is not answering — trying again in {note.Seconds ?? 0} s…",
    };

    /// <summary>One line for the log: the stage times in report order.</summary>
    public string Describe()
        => string.Join(", ", Order.Select(s => $"{s} {_times[s]:0} ms" + (_splits.TryGetValue(s, out var split) ? $" [{split}]" : ""))) + (Note is { } n ? $" (note {n.Kind})" : "")
           + (Measurements is { } m ? $"\nboot work: {m.Describe()}" : "")
           + (CacheSummary is { } cache ? "\n" + cache() : "");
}

/// <summary>
/// <c>retryBoot</c> of client3d/src/main.ts: run the start's fetch until it succeeds, waiting
/// <see cref="DelayMs"/> between attempts and telling the title screen how long (<c>retry</c> note in whole
/// seconds, cleared on success). Native difference: an authentication failure is not retried — the session is
/// gone, the client goes back to its login screen, and this boot ends with that exception.
/// </summary>
public static class BootRetry
{
    /// <summary><c>min(15000, 1000 · 2^min(attempt, 4))</c> ms: 1, 2, 4, 8, 15, 15 … s.</summary>
    public static double DelayMs(int attempt) => Math.Min(15_000, 1000 * Math.Pow(2, Math.Min(attempt, 4)));

    public static async Task<T> RunAsync<T>(Func<Task<T>> fn, Func<Exception, bool> isAuth, Action<int> waiting,
                                            Action clear, Func<double, Task> sleep, Action<string, Exception>? log = null)
    {
        for (int attempt = 0; ; attempt++)
        {
            try
            {
                var result = await fn();
                clear();
                return result;
            }
            catch (Exception e) when (!isAuth(e))
            {
                double wait = DelayMs(attempt);
                log?.Invoke($"attempt {attempt + 1} failed — retrying in {wait / 1000} s", e);
                waiting((int)JsSemantics.Round(wait / 1000));
                await sleep(wait);
            }
        }
    }
}
