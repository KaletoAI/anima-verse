using System;
using System.Collections.Generic;
using System.Linq;

namespace AnimaNative.Figures;

/// <summary>
/// Foot-contact root motion — client3d/src/scene/footLock.ts (the twin of <c>app/blender/scripts/_root_motion.py</c>),
/// vectors shared/test-vectors/foot_lock.json (hand derivations: client3d/scripts/smoke_foot_lock_math.mjs).
///
/// Frame: clip frame, Y up, +Z forward, +X the figure's left, centimetres. Input tracks are IN PLACE (the hips' XZ
/// stripped) — a foot planted in the world slides backwards here by exactly the travel the path rebuilds. A point in
/// FULL contact outranks a half-planted one: while any point is fully planted, only those steer the root.
/// Tracks are name → per-frame points; the dictionary's insertion order is the TS object's key order.
/// </summary>
public static class FootLock
{
    /// <summary>Height above a point's own ground at which contact fades out, cm.</summary>
    public const double BandLoCm = 2.0;
    public const double BandHiCm = 5.0;
    /// <summary>Vertical speed at which contact fades out, cm/s.</summary>
    public const double VyLoCmS = 15.0;
    public const double VyHiCmS = 30.0;
    /// <summary>Percentile of a point's heights taken as its ground.</summary>
    public const double GroundPct = 0.05;
    /// <summary>Below this summed weight a frame has no planted point.</summary>
    public const double MinWeight = 1e-3;
    /// <summary>A frame pair at or above this weight counts as FULL contact.</summary>
    public const double Full = 0.999;
    /// <summary>Ankle and ball of each foot: one rigid foot, two points.</summary>
    public static readonly IReadOnlyList<string> ContactPoints = new[] { "LeftFoot", "LeftToeBase", "RightFoot", "RightToeBase" };

    /// <summary><c>ramp(v, lo, hi)</c>: 1 at or below lo, 0 at or above hi, linear between; NaN → 0.</summary>
    public static double Ramp(double v, double lo, double hi)
    {
        if (!double.IsFinite(v)) return 0;
        if (v <= lo) return 1;
        if (v >= hi) return 0;
        return (hi - v) / (hi - lo);
    }

    public static bool Finite(V3 p) => double.IsFinite(p.X) && double.IsFinite(p.Y) && double.IsFinite(p.Z);

    /// <summary>
    /// <c>groundHeights(tracks, rest)</c>: per point the low percentile of its finite heights (index
    /// <c>min(n−1, floor(0.05·(n−1)))</c> of the sorted list), never above its rest height; a point without a finite
    /// height has none.
    /// </summary>
    public static Dictionary<string, double> GroundHeights(IReadOnlyDictionary<string, V3[]> tracks,
                                                           IReadOnlyDictionary<string, double> restHeights)
    {
        var output = new Dictionary<string, double>();
        foreach (var (name, pts) in tracks)
        {
            var ys = pts.Where(Finite).Select(p => p.Y).OrderBy(y => y).ToList();
            if (ys.Count == 0) continue;
            double pct = ys[Math.Min(ys.Count - 1, (int)Math.Floor(GroundPct * (ys.Count - 1)))];
            output[name] = Math.Min(pct, restHeights.TryGetValue(name, out var r) ? r : double.PositiveInfinity);
        }
        return output;
    }

    /// <summary>
    /// <c>contactWeights(tracks, ground, fps)</c>: per point and frame the height band × the vertical-speed band
    /// (central difference, one-sided at the ends); a point without ground or a non-finite frame weighs 0.
    /// </summary>
    public static Dictionary<string, double[]> ContactWeights(IReadOnlyDictionary<string, V3[]> tracks,
                                                              IReadOnlyDictionary<string, double> ground, double fps)
    {
        var output = new Dictionary<string, double[]>();
        foreach (var (name, pts) in tracks)
        {
            int n = pts.Length;
            bool has = ground.TryGetValue(name, out double g);
            var w = new double[n];
            for (int f = 0; f < n; f++)
            {
                var p = pts[f];
                if (!has || !Finite(p)) { w[f] = 0; continue; }
                int a = Math.Max(f - 1, 0), b = Math.Min(f + 1, n - 1);
                double vy = b > a && Finite(pts[a]) && Finite(pts[b]) ? (pts[b].Y - pts[a].Y) / ((b - a) / fps) : 0;
                w[f] = Ramp(p.Y - g, BandLoCm, BandHiCm) * Ramp(Math.Abs(vy), VyLoCmS, VyHiCmS);
            }
            output[name] = w;
        }
        return output;
    }

    /// <summary>
    /// <c>footLockPath(tracks, weights)</c>: root (x, z) per frame from the origin — each step moves the root by the
    /// weighted opposite of the planted points' slide, of the FULLY planted points only whenever there is one.
    /// </summary>
    public static List<(double X, double Z)> FootLockPath(IReadOnlyDictionary<string, V3[]> tracks,
                                                          IReadOnlyDictionary<string, double[]> weights)
    {
        int n = 0;
        foreach (var pts in tracks.Values) n = Math.Max(n, pts.Length);
        var path = new List<(double X, double Z)>();
        if (n == 0) return path;
        path.Add((0, 0));
        var steps = new List<(double W, double Dx, double Dz)>();
        for (int f = 0; f < n - 1; f++)
        {
            steps.Clear();
            foreach (var (name, pts) in tracks)
            {
                var w = weights.TryGetValue(name, out var ww) ? ww : Array.Empty<double>();
                if (f + 1 >= pts.Length || f + 1 >= w.Length) continue;
                double ws = Math.Min(w[f], w[f + 1]);
                if (!(ws > 0) || !Finite(pts[f]) || !Finite(pts[f + 1])) continue;
                steps.Add((ws, pts[f + 1].X - pts[f].X, pts[f + 1].Z - pts[f].Z));
            }
            var full = steps.Where(s => s.W >= Full).ToList();
            var use = full.Count > 0 ? full : steps;
            double sw = use.Sum(s => s.W);
            var (x, z) = path[^1];
            if (sw >= MinWeight)
            {
                x -= use.Sum(s => s.W * s.Dx) / sw;
                z -= use.Sum(s => s.W * s.Dz) / sw;
            }
            path.Add((x, z));
        }
        return path;
    }

    /// <summary>
    /// <c>maxPlantedDrift(tracks, weights, path)</c>: the largest horizontal distance a point travels in the WORLD
    /// (track + path) during one unbroken run of full contact, cm.
    /// </summary>
    public static double MaxPlantedDrift(IReadOnlyDictionary<string, V3[]> tracks, IReadOnlyDictionary<string, double[]> weights,
                                         IReadOnlyList<(double X, double Z)> path)
    {
        double worst = 0;
        foreach (var (name, pts) in tracks)
        {
            var w = weights.TryGetValue(name, out var ww) ? ww : Array.Empty<double>();
            (double X, double Z)? start = null;
            int n = Math.Min(pts.Length, Math.Min(w.Length, path.Count));
            for (int f = 0; f < n; f++)
            {
                var p = pts[f];
                if (w[f] >= Full && Finite(p))
                {
                    double wx = p.X + path[f].X, wz = p.Z + path[f].Z;
                    start ??= (wx, wz);
                    worst = Math.Max(worst, Math.Sqrt((wx - start.Value.X) * (wx - start.Value.X) + (wz - start.Value.Z) * (wz - start.Value.Z)));
                }
                else start = null;
            }
        }
        return worst;
    }
}

/// <summary>A unit quaternion in the importer's (w, x, y, z) order (legPin.ts <c>Quat</c>).</summary>
public readonly record struct WQuat(double W, double X, double Y, double Z)
{
    public static readonly WQuat Identity = new(1, 0, 0, 0);

    /// <summary>The same rotation in three's (x, y, z, w) order (footLockMeasure.ts <c>toThree</c>).</summary>
    public Quat ToThree() => new(X, Y, Z, W);
}

/// <summary>
/// LEG PIN — client3d/src/scene/legPin.ts (the twin of <c>app/blender/scripts/_foot_plant.py</c>), vectors
/// shared/test-vectors/leg_pin.json (hand derivations: client3d/scripts/smoke_leg_pin.mjs).
/// </summary>
public static class LegPin
{
    /// <summary>Shortest contact that is pinned, s.</summary>
    public const double PinMinS = 0.2;
    /// <summary>Fade-in/out of a pinned contact's weight, s.</summary>
    public const double PinFadeS = 0.1;
    /// <summary>Share of the rest foot's ankle-over-ball rise a foot must keep to count as standing on its sole.</summary>
    public const double SoleMinFraction = 0.5;

    private static double Dot(V3 a, V3 b) => a.X * b.X + a.Y * b.Y + a.Z * b.Z;
    private static V3 Cross(V3 a, V3 b) => new(a.Y * b.Z - a.Z * b.Y, a.Z * b.X - a.X * b.Z, a.X * b.Y - a.Y * b.X);
    private static double Len(V3 a) => Math.Sqrt(Dot(a, a));
    private static V3 Unit(V3 a)
    {
        double n = Len(a);
        return n > 1e-12 ? a * (1 / n) : V3.Zero;
    }

    /// <summary><c>qrot(q, v)</c>: v turned by the unit quaternion q.</summary>
    public static V3 Qrot(WQuat q, V3 v)
    {
        var qv = new V3(q.X, q.Y, q.Z);
        var t = Cross(qv, v) * 2;
        return v + t * q.W + Cross(qv, t);
    }

    /// <summary><c>rotationBetween(a, b)</c>: the shortest rotation taking direction a onto b (180° about a normal when opposite).</summary>
    public static WQuat RotationBetween(V3 a, V3 b)
    {
        var ua = Unit(a);
        var ub = Unit(b);
        double c = Dot(ua, ub);
        if (c < -1 + 1e-12)
        {
            var axis = Cross(ua, new V3(1, 0, 0));
            if (Len(axis) < 1e-6) axis = Cross(ua, new V3(0, 1, 0));
            axis = Unit(axis);
            return new WQuat(0, axis.X, axis.Y, axis.Z);
        }
        var x = Cross(ua, ub);
        double w = 1 + c;
        double n = Math.Sqrt(w * w + x.X * x.X + x.Y * x.Y + x.Z * x.Z);
        return new WQuat(w / n, x.X / n, x.Y / n, x.Z / n);
    }

    /// <summary>
    /// <c>twoBoneIk(hip, knee, ankle, target, pole)</c>: world-space rotation deltas (upper about the hip, lower about
    /// the new knee) so the ankle reaches the target; the knee stays in the hip→target / pole plane; out of reach
    /// stretches, too close folds; degenerate input answers two identities.
    /// </summary>
    public static (WQuat Upper, WQuat Lower) TwoBoneIk(V3 hip, V3 knee, V3 ankle, V3 target, V3 pole)
    {
        double l1 = Len(knee - hip), l2 = Len(ankle - knee);
        var toT = target - hip;
        double d = Len(toT);
        if (l1 < 1e-9 || l2 < 1e-9 || d < 1e-9) return (WQuat.Identity, WQuat.Identity);
        var t = toT * (1 / d);
        d = Math.Min(Math.Max(d, Math.Abs(l1 - l2) + 1e-9), l1 + l2);
        var p = pole - hip;
        var u = p - t * Dot(p, t);
        if (Len(u) < 1e-9)
        {
            u = Cross(t, new V3(1, 0, 0));
            if (Len(u) < 1e-6) u = Cross(t, new V3(0, 0, 1));
        }
        u = Unit(u);
        double cosA = Math.Max(-1, Math.Min(1, (l1 * l1 + d * d - l2 * l2) / (2 * l1 * d)));
        double sinA = Math.Sqrt(Math.Max(0, 1 - cosA * cosA));
        var newKnee = hip + (t * (l1 * cosA) + u * (l1 * sinA));
        var reach = hip + t * d;
        var upper = RotationBetween(knee - hip, newKnee - hip);
        var shin = Qrot(upper, ankle - knee);
        var lower = RotationBetween(shin, reach - newKnee);
        return (upper, lower);
    }

    private static int LongestFull(IReadOnlyList<double> w, int a, int b)
    {
        int best = 0, cur = 0;
        for (int g = a; g <= b; g++)
        {
            cur = w[g] >= FootLock.Full ? cur + 1 : 0;
            best = Math.Max(best, cur);
        }
        return best;
    }

    /// <summary>
    /// <c>pinRuns(w, fps)</c>: a run of w &gt; 0 is pinned only with PIN_MIN_S of full weight in one piece; a kept run
    /// keeps its weights faded in and out over round(PIN_FADE_S·fps) frames — not on a side that touches the take's
    /// first or last frame. Every other frame weighs 0.
    /// </summary>
    public static double[] PinRuns(IReadOnlyList<double> w, double fps)
    {
        int n = w.Count;
        var output = new double[n];
        int fade = (int)Math.Floor(PinFadeS * fps + 0.5);
        int f = 0;
        while (f < n)
        {
            if (!(w[f] > 0)) { f++; continue; }
            int a = f;
            while (f + 1 < n && w[f + 1] > 0) f++;
            int b = f;
            f++;
            if (LongestFull(w, a, b) / fps < PinMinS - 1e-9) continue;
            for (int g = a; g <= b; g++)
            {
                double fadeIn = a == 0 ? 1 : (g - a + 1) / (double)(fade + 1);
                double fadeOut = b == n - 1 ? 1 : (b - g + 1) / (double)(fade + 1);
                output[g] = w[g] * Math.Min(1, Math.Min(fadeIn, fadeOut));
            }
        }
        return output;
    }

    /// <summary>
    /// <c>soleDown(ankle, ball, restRise)</c>: per frame the ankle above the ball by at least SOLE_MIN_FRACTION of the
    /// rest rise (≤ 0 → threshold 0); non-finite heights answer false.
    /// </summary>
    public static bool[] SoleDown(IReadOnlyList<double> ankleHeights, IReadOnlyList<double> ballHeights, double restRise)
    {
        double need = SoleMinFraction * Math.Max(restRise, 0);
        var output = new bool[ankleHeights.Count];
        for (int f = 0; f < output.Length; f++)
        {
            double a = ankleHeights[f];
            double b = f < ballHeights.Count ? ballHeights[f] : double.NaN;
            output[f] = double.IsFinite(a) && double.IsFinite(b) && a - b >= need;
        }
        return output;
    }
}
