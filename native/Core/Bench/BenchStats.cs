using System;
using System.Collections.Generic;
using System.Linq;

namespace AnimaNative.Bench;

/// <summary>
/// One measured frame — the browser's <c>BenchSample</c> plus
/// <see cref="RenderCpuMs"/> (Godot's own render-thread CPU time, reported
/// next to the plan's <c>cpuMs</c>; <see cref="BenchStats.Summarize"/> ignores it).
/// </summary>
public readonly record struct BenchSample(double Dt, double CpuMs, double? GpuMs, double Calls, double Tris,
                                          double? RenderCpuMs = null);

/// <summary>The browser's <c>BenchSummary</c>, field for field.</summary>
public sealed record BenchSummary(int Frames, double Seconds, double FpsMean, double FrameMsMedian, double FrameMsP95,
                                  double CpuMsMedian, double CpuMsP95, double? GpuMsMedian, double CallsMedian,
                                  double TrisMedian);

/// <summary>
/// Port of <c>client3d/src/bench/benchStats.ts</c> (itself from 183d873):
/// seconds are wall time, fps = frames / seconds (not the mean of per-frame
/// rates), medians/P95 by the linear-interpolated percentile.
/// </summary>
public static class BenchStats
{
    /// <summary>Linear-interpolated percentile of a SORTED ascending list; 0 for empty.</summary>
    public static double Percentile(IReadOnlyList<double> sorted, double p)
    {
        int n = sorted.Count;
        if (n == 0) return 0;
        if (n == 1) return sorted[0];
        double rank = (Math.Min(Math.Max(p, 0), 100) / 100) * (n - 1);
        int lo = (int)Math.Floor(rank);
        int hi = Math.Min(lo + 1, n - 1);
        return sorted[lo] + (sorted[hi] - sorted[lo]) * (rank - lo);
    }

    private static List<double> Asc(IEnumerable<double> values)
    {
        var list = values.ToList();
        list.Sort();
        return list;
    }

    public static BenchSummary Summarize(IReadOnlyList<BenchSample> samples)
    {
        int frames = samples.Count;
        double seconds = samples.Aggregate(0.0, (s, x) => s + x.Dt);
        var frameMs = Asc(samples.Select(x => x.Dt * 1000));
        var cpu = Asc(samples.Select(x => x.CpuMs));
        var gpu = Asc(samples.Where(x => x.GpuMs.HasValue).Select(x => x.GpuMs!.Value));
        var calls = Asc(samples.Select(x => x.Calls));
        var tris = Asc(samples.Select(x => x.Tris));
        return new BenchSummary(
            frames,
            seconds,
            seconds > 0 ? frames / seconds : 0,
            Percentile(frameMs, 50),
            Percentile(frameMs, 95),
            Percentile(cpu, 50),
            Percentile(cpu, 95),
            gpu.Count > 0 ? Percentile(gpu, 50) : null,
            Percentile(calls, 50),
            Percentile(tris, 50));
    }

    /// <summary>Median of the frames that carry a value; null when none does (like <c>gpuMsMedian</c>).</summary>
    public static double? MedianOrNull(IEnumerable<double?> values)
    {
        var list = Asc(values.Where(v => v.HasValue).Select(v => v!.Value));
        return list.Count > 0 ? Percentile(list, 50) : null;
    }
}
