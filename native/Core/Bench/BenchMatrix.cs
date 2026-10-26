using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text;

namespace AnimaNative.Bench;

/// <summary>One pass of the bench matrix: its <c>variant</c> name (the key every result carries) and what it switches.</summary>
public sealed record BenchVariant(string Name, string Switches);

/// <summary>One finished pass, as far as the summary table needs it (null = the renderer did not measure it).</summary>
public readonly record struct BenchMatrixRow(string Variant, double Fps, double FrameMsMedian, double FrameMsP95, double? GpuMs,
                                             double Draws, double Triangles, bool Applied);

/// <summary>
/// <c>--bench-matrix</c> (Task 26b): the camera drive of <c>--bench</c>, run once per variant in ONE process with the same
/// warm-up and duration, each pass with exactly one feature switched off at runtime (no rebuild between passes). The
/// order is fixed: the baseline first, the single switches, the candidate swap <c>fog-compute</c> (the distance fog as a
/// compute pass instead of the screen-texture pass — a different technique, not a feature off), and the baseline once
/// more at the end as the drift control (an iGPU in a laptop warms up and clocks down over five minutes; a moved end
/// baseline says by how much every delta in between is blurred).
/// </summary>
public static class BenchMatrix
{
    public const string Baseline = "baseline", BaselineEnd = "baseline-end";

    public static readonly IReadOnlyList<BenchVariant> Variants = new BenchVariant[]
    {
        new(Baseline, "nothing switched"),
        new("no-shadow", "the sun's directional shadow off (no shadow pass, no shadow sampling)"),
        new("no-hemi-extra-lights", "the hemisphere pair off (ambient only): both shadowless directional lights hidden and the terrain's shader term zeroed"),
        new("no-fog-pass", "the distance fog off (no screen/depth copy, no full-screen pass)"),
        new("no-veil", "the exploration veil off (fv_alpha 0 on every ground material: its uniform branch reads no texture)"),
        new("no-backdrop", "the mountain backdrop rings hidden"),
        new("no-water-extras", "the terrain water's ripple off (tw_ripple_on 0), the underwater ghosts, waterfalls and prop water sheets hidden"),
        new("no-mirrors", "no mirror reflection passes (panes keep their last picture)"),
        new("no-prop-lights", "the six prop lamps and every halo hidden"),
        new("no-cut-shader", "every cut surface wears its plain source material instead of the cut shader port"),
        new("terrain-lod-coarse", "the CDLOD terrain with the pixel scale halved (= allowed pixel error 2 -> 4 px, rings shrink up to one level)"),
        new("shadow-atlas-2048", "the directional shadow atlas 4096 -> 2048 px (texel twice as large)"),
        new("fog-compute", "the distance fog as one compute pass on the colour buffer (post-transparent compositor effect) instead of the screen-texture pass"),
        new(BaselineEnd, "nothing switched (drift control)"),
    };

    public static BenchVariant? Find(string name) => Variants.FirstOrDefault(v => v.Name == name);

    /// <summary>
    /// <c>--bench-matrix=a,b,…</c>: a subset in the matrix's own order (unknown names refuse the start); null or empty =
    /// all of them. The baseline always runs first — a subset without it gets it added, deltas need it.
    /// </summary>
    public static IReadOnlyList<BenchVariant> Select(string? names)
    {
        if (string.IsNullOrWhiteSpace(names)) return Variants;
        var want = names.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries).ToHashSet();
        var unknown = want.Where(n => Find(n) is null).ToList();
        if (unknown.Count > 0)
            throw new ArgumentException($"--bench-matrix: unknown variant(s) {string.Join(", ", unknown)}; known: "
                                        + string.Join(", ", Variants.Select(v => v.Name)));
        want.Add(Baseline);
        return Variants.Where(v => want.Contains(v.Name)).ToList();
    }

    /// <summary>The pass's delta against the FIRST baseline (negative = cheaper); null without both GPU times.</summary>
    public static double? GpuDelta(BenchMatrixRow row, BenchMatrixRow baseline)
        => row.GpuMs is { } g && baseline.GpuMs is { } b ? g - b : null;

    private static string N(double? v, string fmt) => v is { } x ? x.ToString(fmt, CultureInfo.InvariantCulture) : "-";

    /// <summary>
    /// The summary table printed after the last pass: per variant fps, frame median/P95, GPU median and its delta to the
    /// baseline, draws, triangles (millions). A pass whose switch found nothing to switch is marked "(n/a)".
    /// </summary>
    public static string Table(IReadOnlyList<BenchMatrixRow> rows)
    {
        var sb = new StringBuilder();
        sb.Append("variant                 fps     frame ms  p95 ms   gpu ms   Δgpu ms  draws  tris M\n");
        BenchMatrixRow? baseline = rows.FirstOrDefault(r => r.Variant == Baseline) is { Variant: not null } b ? b : null;
        foreach (var r in rows)
        {
            double? delta = baseline is { } bl ? GpuDelta(r, bl) : null;
            string name = r.Applied ? r.Variant : r.Variant + " (n/a)";
            sb.Append(name.PadRight(22)).Append(' ')
              .Append(N(r.Fps, "0.0").PadLeft(6)).Append(' ')
              .Append(N(r.FrameMsMedian, "0.00").PadLeft(9)).Append(' ')
              .Append(N(r.FrameMsP95, "0.00").PadLeft(7)).Append(' ')
              .Append(N(r.GpuMs, "0.00").PadLeft(8)).Append(' ')
              .Append((delta is { } d ? (d >= 0 ? "+" : "") + N(d, "0.00") : "-").PadLeft(9)).Append(' ')
              .Append(N(r.Draws, "0").PadLeft(6)).Append(' ')
              .Append(N(r.Triangles / 1e6, "0.00").PadLeft(7)).Append('\n');
        }
        return sb.ToString();
    }
}
