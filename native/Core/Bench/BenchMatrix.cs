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
/// warm-up and duration, each pass with exactly one feature switched off (or one technique swapped) at runtime, no
/// rebuild between passes.
///
/// <b>Drift (Task 26c).</b> A laptop iGPU warms up and clocks down over the minutes a matrix takes: in the user's second
/// run the middle passes came out 2–3 ms SLOWER than the baseline although each switched something off. So the run is
/// interleaved — <see cref="Schedule"/>: baseline, variant, baseline, variant, …, baseline — and every variant is reported
/// against the mean of the two baselines right around it (<see cref="NeighbourDeltas"/>): a drift that is linear over
/// one variant's pair of neighbours cancels exactly. The baselines themselves show their drift against the first one.
/// </summary>
public static class BenchMatrix
{
    public const string Baseline = "baseline";

    /// <summary>The variants in their order (the baseline first; <see cref="Schedule"/> puts a baseline between all of them).</summary>
    public static readonly IReadOnlyList<BenchVariant> Variants = new BenchVariant[]
    {
        new(Baseline, "nothing switched"),
        new("no-shadow", "the sun's directional shadow off (no shadow pass, no shadow sampling)"),
        new("shadow-full-view", "the browser's 140 m caster box off: every caster in Godot's frustum fit (camera slice to the max distance) draws into the shadow pass"),
        new("no-hemi-extra-lights", "the hemisphere pair off (ambient only): both shadowless directional lights hidden and the shader term (terrain, scatter) zeroed"),
        new("no-fog-pass", "the distance fog off (no compute pass, no screen pass, no copies)"),
        new("no-veil", "the exploration veil off (fv_alpha 0 on every ground material: its uniform branch reads no texture)"),
        new("no-backdrop", "the mountain backdrop rings hidden"),
        new("no-water-extras", "the terrain water's ripple off (tw_ripple_on 0), the underwater ghosts, waterfalls and prop water sheets hidden"),
        new("no-mirrors", "no mirror reflection passes (panes keep their last picture)"),
        new("no-prop-lights", "the six prop lamps and every halo hidden"),
        new("no-cut-shader", "every cut surface wears its plain source material instead of the cut shader port"),
        new("terrain-lod-coarse", "the CDLOD terrain with the pixel scale halved (= allowed pixel error 2 -> 4 px, rings shrink up to one level)"),
        new("shadow-atlas-2048", "the directional shadow atlas 4096 -> 2048 px (texel twice as large)"),
        new("fog-pass", "the distance fog as the screen-texture pass (the fallback, --fog=pass) instead of the compute pass (the default)"),
        new("no-figures", "every figure hidden and its frame tick stopped (no walking, no clip advance, no skinning, nothing drawn)"),
    };

    public static BenchVariant? Find(string name) => Variants.FirstOrDefault(v => v.Name == name);

    /// <summary>
    /// <c>--bench-matrix=a,b,…</c>: a subset in the matrix's own order (unknown names refuse the start); null or empty =
    /// all of them. The baseline always comes first — a subset without it gets it added, deltas need it.
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

    /// <summary>
    /// The passes in the order they run: a baseline before every variant and one after the last — n variants make
    /// 2n + 1 passes (B V₁ B V₂ … Vₙ B). A selection of the baseline alone is one pass.
    /// </summary>
    public static IReadOnlyList<BenchVariant> Schedule(IReadOnlyList<BenchVariant> selected)
    {
        var baseline = Find(Baseline)!;
        var list = new List<BenchVariant> { baseline };
        foreach (var v in selected.Where(v => v.Name != Baseline))
        {
            list.Add(v);
            list.Add(baseline);
        }
        return list;
    }

    /// <summary>The pass's delta against one baseline (negative = cheaper); null without both GPU times.</summary>
    public static double? GpuDelta(BenchMatrixRow row, BenchMatrixRow baseline)
        => row.GpuMs is { } g && baseline.GpuMs is { } b ? g - b : null;

    /// <summary>
    /// Per row its reference and delta: a variant against the mean GPU time of the nearest baseline before it and the
    /// nearest one after it (only one of them when the other is missing or unmeasured); a baseline against the FIRST
    /// measured baseline (its drift). Null where there is nothing to compare.
    /// </summary>
    public static IReadOnlyList<(double? Reference, double? Delta)> NeighbourDeltas(IReadOnlyList<BenchMatrixRow> rows)
    {
        double? first = rows.FirstOrDefault(r => r.Variant == Baseline && r.GpuMs is not null).GpuMs;
        var result = new List<(double?, double?)>();
        for (int i = 0; i < rows.Count; i++)
        {
            var r = rows[i];
            double? reference;
            if (r.Variant == Baseline) reference = first;
            else
            {
                double? before = null, after = null;
                for (int j = i - 1; j >= 0 && before is null; j--)
                    if (rows[j].Variant == Baseline && rows[j].GpuMs is { } g) before = g;
                for (int j = i + 1; j < rows.Count && after is null; j++)
                    if (rows[j].Variant == Baseline && rows[j].GpuMs is { } g) after = g;
                reference = before is { } b && after is { } a ? (b + a) / 2 : before ?? after;
            }
            result.Add((reference, r.GpuMs is { } own && reference is { } rf ? own - rf : null));
        }
        return result;
    }

    private static string N(double? v, string fmt) => v is { } x ? x.ToString(fmt, CultureInfo.InvariantCulture) : "-";

    private static string Signed(double? v) => v is { } d ? (d >= 0 ? "+" : "") + N(d, "0.00") : "-";

    /// <summary>
    /// The summary table printed after the last pass: per pass fps, frame median/P95, GPU median, its reference (the
    /// neighbouring baselines' mean; for a baseline the first baseline) and the delta to it, draws, triangles
    /// (millions); a pass whose switch found nothing to switch is marked "(n/a)". Below it the variants once more, sorted
    /// by their delta, and the baselines' drift (first, last, spread).
    /// </summary>
    public static string Table(IReadOnlyList<BenchMatrixRow> rows)
    {
        var sb = new StringBuilder();
        var deltas = NeighbourDeltas(rows);
        sb.Append("pass variant                 fps     frame ms  p95 ms   gpu ms   ref ms   Δgpu ms  draws  tris M\n");
        for (int i = 0; i < rows.Count; i++)
        {
            var r = rows[i];
            var (reference, delta) = deltas[i];
            string name = r.Applied ? r.Variant : r.Variant + " (n/a)";
            sb.Append((i + 1).ToString(CultureInfo.InvariantCulture).PadLeft(4)).Append(' ')
              .Append(name.PadRight(22)).Append(' ')
              .Append(N(r.Fps, "0.0").PadLeft(6)).Append(' ')
              .Append(N(r.FrameMsMedian, "0.00").PadLeft(9)).Append(' ')
              .Append(N(r.FrameMsP95, "0.00").PadLeft(7)).Append(' ')
              .Append(N(r.GpuMs, "0.00").PadLeft(8)).Append(' ')
              .Append(N(reference, "0.00").PadLeft(8)).Append(' ')
              .Append(Signed(delta).PadLeft(9)).Append(' ')
              .Append(N(r.Draws, "0").PadLeft(6)).Append(' ')
              .Append(N(r.Triangles / 1e6, "0.00").PadLeft(7)).Append('\n');
        }
        var variants = rows.Select((r, i) => (r, d: deltas[i].Delta)).Where(x => x.r.Variant != Baseline).ToList();
        if (variants.Count > 0)
        {
            sb.Append("by Δgpu against the neighbouring baselines:");
            foreach (var (r, d) in variants.OrderBy(x => x.d ?? double.MaxValue))
                sb.Append(' ').Append(r.Applied ? r.Variant : r.Variant + "(n/a)").Append(' ').Append(Signed(d));
            sb.Append('\n');
        }
        var bases = rows.Where(r => r.Variant == Baseline && r.GpuMs is not null).Select(r => r.GpuMs!.Value).ToList();
        if (bases.Count > 1)
            sb.Append($"baseline drift: {bases.Count} baselines, first {N(bases[0], "0.00")}, last {N(bases[^1], "0.00")}, "
                      + $"spread {N(bases.Max() - bases.Min(), "0.00")} ms\n");
        return sb.ToString();
    }
}
