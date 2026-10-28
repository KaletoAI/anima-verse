using System;
using System.Collections.Generic;
using System.Text.Json.Nodes;

namespace AnimaNative.Overview;

/// <summary>
/// Port of the frame-rate half of client3d/src/game/perfstats.ts: <c>pushFrame</c>/<c>fpsOf</c> — a sliding
/// one-second window of frame times, the rate = frames in the window / their summed time.
/// <list type="bullet">
/// <item>A <c>dt</c> that is not a positive finite number is ignored (the reading is kept).</item>
/// <item>The window drops from the front while the sum EXCEEDS 1 s or it holds more than 240 samples, never
/// below one sample — a 2 s freeze reads 0.5 fps instead of vanishing.</item>
/// </list>
/// Same arithmetic order as the TS (push, add, then shift-and-subtract), so the sums round alike.
/// </summary>
public sealed class FpsMeter
{
    /// <summary><c>FPS_WINDOW_S</c>.</summary>
    public const double WindowS = 1;
    /// <summary><c>FPS_MAX_SAMPLES</c>.</summary>
    public const int MaxSamples = 240;

    private readonly Queue<double> _samples = new();

    /// <summary>Sum of the samples in the window (s).</summary>
    public double Sum { get; private set; }

    /// <summary>Frames in the window.</summary>
    public int Count => _samples.Count;

    /// <summary><c>pushFrame(meter, dt)</c>: add one frame time (s), return the smoothed rate.</summary>
    public double Push(double dt)
    {
        if (!double.IsFinite(dt) || dt <= 0) return Fps;
        _samples.Enqueue(dt);
        Sum += dt;
        while (_samples.Count > 1 && (Sum > WindowS || _samples.Count > MaxSamples))
            Sum -= _samples.Dequeue();
        return Fps;
    }

    /// <summary><c>fpsOf(meter)</c>: the current reading, 0 while nothing was pushed.</summary>
    public double Fps => Sum > 0 ? _samples.Count / Sum : 0;
}

/// <summary>
/// <c>pushWorstFrame</c> of perfstats.ts: the largest raw interval between two frame stamps (ms) since the readout
/// was switched on. Raw monotonic stamps, not the (clamped) simulation dt.
/// </summary>
public sealed class WorstFrame
{
    public double? LastFrameAt { get; private set; }
    public double WorstFrameMs { get; private set; }

    public double Push(double nowMs)
    {
        if (LastFrameAt is { } last) WorstFrameMs = Math.Max(WorstFrameMs, nowMs - last);
        LastFrameAt = nowMs;
        return WorstFrameMs;
    }
}

/// <summary>Task 40: browser ScatterCost, counting visible stage nodes, instances and triangles (before frustum culling).</summary>
public readonly record struct ScatterCost(long Calls, long Instances, long Triangles);

/// <summary>Task 42: cumulative browser sync counters and the maximum route error over the last 30 seconds.</summary>
public readonly record struct TravelCounters(int TravBack, int TravFwd, double TravErrMaxM, int Arrive, int Place);

/// <summary>One native readout, with measured scatter stages (Task 40); unsupported monitors stay zero.</summary>
public readonly record struct PerfSample(
    double Fps, double WorstFrameMs, long Triangles, long Calls, long Vertices, long Geometries, long Textures,
    int TiersFull, int TiersLow, double ScatterLodMs, ScatterCost Mesh = default, ScatterCost Impostor = default, TravelCounters Sync = default);

/// <summary>
/// The HUD's performance readout (<c>{v:3, kind:'perf', value: PerfStats}</c>, client3d/src/hud/bus.ts /
/// game/perfstats.ts) as the native client fills it. main.ts' cadences: the frame rate and the worst frame are
/// sampled every frame, the heavy count on the 1 s LOD tick, the readout published every
/// <see cref="PublishMs"/> — and nothing at all while <c>HudUiState.perfOn</c> is off; switching it off throws the
/// window and the worst frame away, so switching on starts measuring anew.
///
/// Every key of the TS <c>PerfStats</c> is sent (the HUD reads them all): Task 40 supplies the scatter split and LOD time; Task 42 supplies the journey and placement sync counters.
/// </summary>
public static class PerfReadout
{
    /// <summary><c>PERF_UI_MS</c>.</summary>
    public const int PublishMs = 300;
    /// <summary><c>LOD_TICK_MS</c>: the heavy count's beat.</summary>
    public const int HeavyMs = 1000;

    /// <summary>The <c>PerfStats</c> object of bus.ts for one sample.</summary>
    public static JsonObject ToJson(PerfSample s)
    {
        static JsonObject Cost(ScatterCost c) => new() { ["calls"] = c.Calls, ["instances"] = c.Instances, ["triangles"] = c.Triangles };
        return new JsonObject
        {
            ["fps"] = s.Fps,
            ["worstFrameMs"] = s.WorstFrameMs,
            ["triangles"] = s.Triangles,
            ["calls"] = s.Calls,
            ["vertices"] = s.Vertices,
            ["geometries"] = s.Geometries,
            ["textures"] = s.Textures,
            ["tiers"] = new JsonObject { ["full"] = s.TiersFull, ["low"] = s.TiersLow },
            ["scatter"] = new JsonObject { ["mesh"] = Cost(s.Mesh), ["impostor"] = Cost(s.Impostor) },
            ["scatterLodMs"] = s.ScatterLodMs,
            ["sync"] = new JsonObject
            {
                ["posCorr"] = 0, ["pos409"] = 0, ["travBack"] = s.Sync.TravBack, ["travFwd"] = s.Sync.TravFwd, ["travErrMaxM"] = s.Sync.TravErrMaxM,
                ["arrive"] = s.Sync.Arrive, ["place"] = s.Sync.Place,
            },
        };
    }
}
