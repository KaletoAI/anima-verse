using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;

namespace AnimaNative.Figures;

/// <summary>The inputs of <see cref="HipsTrack.Map"/> (<c>HipsTrackOptions</c> of packages/scene-render/src/hipsTrack.ts).</summary>
/// <param name="SourceRest">the library's standing reference (caller guarantees &gt; 1e-6)</param>
/// <param name="Median">this clip's hips median (<see cref="HipsTrack.Median"/>, 0 when it has none)</param>
/// <param name="HipsPosScale">world rest height of the target hips</param>
/// <param name="ParentInverse">column-major inverse world matrix of the hips' parent (16 numbers)</param>
/// <param name="Rest">the target hips' local rest position</param>
public sealed record HipsTrackOptions(double SourceRest, double Median, double HipsPosScale,
                                      IReadOnlyList<double> ParentInverse, V3 Rest, bool RootMotion, bool RigKnown);

/// <summary>A root travel path: times and the (x, z) of every frame, frame 0 = origin, clip frame, template units.</summary>
public sealed record RootPath(float[] Times, float[] Xz);

/// <summary>
/// The hips-height side of the clip library, ported from packages/scene-render/src/figure.ts
/// (<c>standingHipsRef</c>, <c>clipHipsDrop</c>, <c>hipsTrackMedian</c>) and hipsTrack.ts (<c>mapHipsTrack</c>);
/// vectors shared/test-vectors/hips_tracks.json (hand derivations: client3d/scripts/smoke_rig_stand_ref.mjs).
/// </summary>
public static class HipsTrack
{
    private static readonly Regex MixamoPrefix = new("^mixamorig:?", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);
    private static readonly Regex HipsDot = new("hips\\.", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant);

    /// <summary>
    /// <c>standingHipsRef(rigHips, idleMedian)</c>: the rig's rest hips height when finite and &gt; 0
    /// (<c>rig</c>), else the idle median (<c>idle</c>), else <c>(null, none)</c>.
    /// </summary>
    public static (double? Ref, string Source) StandingRef(double? rigHips, double? idleMedian)
    {
        static bool Usable(double? v) => v is { } d && double.IsFinite(d) && d > 0;
        if (Usable(rigHips)) return (rigHips, "rig");
        if (Usable(idleMedian)) return (idleMedian, "idle");
        return (null, "none");
    }

    /// <summary><c>clipHipsDrop(hipsBindY, hipsMedian, standRef)</c> = bind·(1 − median/ref); any unusable input → 0.</summary>
    public static double Drop(double? hipsBindY, double? hipsMedian, double? standRef)
    {
        static bool Ok(double? v) => v is { } d && double.IsFinite(d);
        if (!Ok(hipsBindY) || !Ok(hipsMedian) || !Ok(standRef) || standRef!.Value <= 0) return 0;
        return hipsBindY!.Value * (1 - hipsMedian!.Value / standRef.Value);
    }

    /// <summary>
    /// <c>hipsTrackMedian(clip)</c>: |y| of every hips <c>.position</c> track (name, with a leading
    /// <c>mixamorig:</c> stripped, matching <c>/hips\./i</c>), sorted, the element at floor(n/2); null without one.
    /// </summary>
    public static double? Median(IEnumerable<(string Name, IReadOnlyList<double> Values)>? tracks)
    {
        var ys = new List<double>();
        foreach (var (name, values) in tracks ?? Enumerable.Empty<(string, IReadOnlyList<double>)>())
        {
            if (!name.EndsWith(".position", StringComparison.Ordinal)) continue;
            if (!HipsDot.IsMatch(MixamoPrefix.Replace(name, ""))) continue;
            for (int i = 1; i < values.Count; i += 3) ys.Add(Math.Abs(values[i]));
        }
        if (ys.Count == 0) return null;
        ys.Sort();
        return ys[ys.Count / 2];
    }

    /// <summary>
    /// <c>mapHipsTrack(raw, times, options)</c>: the vertical bounce <c>(|y|·scaleFix − ref)·k</c>,
    /// <c>k = hipsPosScale/ref</c>, through the parent inverse's linear part plus the rest; scale healing
    /// <c>scaleFix = ref/median</c> only when median &gt; 1.5·ref (strict); the horizontal travel
    /// <c>(raw − frame0)·scaleFix·k</c> only for a root-motion clip AND a known rig. Float32 output like the browser.
    /// </summary>
    public static (float[] Values, RootPath? Path) Map(IReadOnlyList<double> raw, IReadOnlyList<double> times, HipsTrackOptions o)
    {
        double k = o.HipsPosScale / o.SourceRest;
        double scaleFix = o.SourceRest > 1e-6 && o.Median > o.SourceRest * 1.5 ? o.SourceRest / o.Median : 1;
        var m = o.ParentInverse;
        var values = new float[raw.Count];
        for (int i = 0; i + 2 < raw.Count; i += 3)
        {
            double bounce = (Math.Abs(raw[i + 1]) * scaleFix - o.SourceRest) * k;
            double w = 1 / (m[3] * 0 + m[7] * bounce + m[11] * 0 + m[15]);
            values[i] = (float)((m[0] * 0 + m[4] * bounce + m[8] * 0 + m[12]) * w - m[12] + o.Rest.X);
            values[i + 1] = (float)((m[1] * 0 + m[5] * bounce + m[9] * 0 + m[13]) * w - m[13] + o.Rest.Y);
            values[i + 2] = (float)((m[2] * 0 + m[6] * bounce + m[10] * 0 + m[14]) * w - m[14] + o.Rest.Z);
        }
        RootPath? path = null;
        if (o.RootMotion && o.RigKnown)
        {
            var xz = new float[times.Count * 2];
            double x0 = raw[0] * scaleFix, z0 = raw[2] * scaleFix;
            for (int i = 0; i < times.Count; i++)
            {
                xz[i * 2] = (float)((raw[i * 3] * scaleFix - x0) * k);
                xz[i * 2 + 1] = (float)((raw[i * 3 + 2] * scaleFix - z0) * k);
            }
            path = new RootPath(times.Select(t => (float)t).ToArray(), xz);
        }
        return (values, path);
    }

    /// <summary>
    /// The library's standing-cluster fallback of <c>adaptExternalClips</c> (figures.ts), used only when NO rig is
    /// served and no clip named <c>idle</c> carries a median: medians &gt; 1e-6 sorted descending; the cap is the first
    /// one a next median confirms within 70 % (a single median is its own cap); the cluster is [0.7·cap, cap],
    /// its element at floor(n/2) ascending — else the largest median, else 0. (No shared vector: the browser's
    /// smokes only reach it through real clips; the rig path is the one every served world takes.)
    /// </summary>
    public static double ClusterRest(IEnumerable<double> medians)
    {
        var sorted = medians.Where(m => m > 1e-6).OrderByDescending(m => m).ToList();
        double cap = sorted.Count > 0 ? sorted[0] : 0;
        for (int i = 0; i < sorted.Count; i++)
        {
            if (sorted.Count == 1 || (i + 1 < sorted.Count && sorted[i + 1] >= sorted[i] * 0.7))
            {
                cap = sorted[i];
                break;
            }
        }
        var cluster = sorted.Where(m => m >= cap * 0.7 && m <= cap).OrderBy(m => m).ToList();
        return cluster.Count > 0 ? cluster[cluster.Count / 2] : sorted.Count > 0 ? sorted[0] : 0;
    }
}
