using System;
using System.Collections.Generic;
using AnimaNative.Scatter;

namespace AnimaNative.Sky;

/// <summary>One ridge node of a backdrop ring (<c>RidgePoint</c>): compass angle in degrees, peak height, ring index.</summary>
public readonly record struct RidgePoint(double AngleDeg, double PeakH, int Layer);

/// <summary>
/// The mountain backdrop's pure profile (<c>client3d/src/scene/backdropProfile.ts</c>, contract § A17): two rings at
/// 380 m and 440 m around the camera target, the back one 25 % taller, a seeded ridge line per ring in the arcs the
/// server resolved, tapered over 12° at each arc end. The compass is the figure compass (0° = south, +z).
/// </summary>
public static class Backdrop
{
    public const double DistM = 380, LayerGapM = 60, LayerHeightK = 0.25;
    public const int Layers = 2, Segments = 96;
    public const double RidgeMinShare = 0.45, RidgeTaperDeg = 12;
    public const double HeightMinM = 20, HeightMaxM = 300, HeightDefaultM = 120;

    /// <summary><c>backdropRandom(seed)</c>: FNV-1a over the UTF-16 units, then the xorshift stream — the very
    /// generator of scene-render's <c>seededRandom</c> (<see cref="ScatterMath.SeededRandom"/>).</summary>
    public static Func<double> Random(string seed) => ScatterMath.SeededRandom(seed);

    /// <summary><c>layerRadiusM</c>.</summary>
    public static double LayerRadiusM(double layer) => DistM + LayerGapM * layer;

    /// <summary><c>ridgeDirection(angleDeg)</c>: (sin a, cos a) — 0° points to +z (south).</summary>
    public static (double X, double Z) RidgeDirection(double angleDeg)
    {
        double a = angleDeg * Math.PI / 180;
        return (Math.Sin(a), Math.Cos(a));
    }

    /// <summary><c>layerHeightFactor</c>.</summary>
    public static double LayerHeightFactor(double layer) => 1 + LayerHeightK * layer;

    /// <summary><c>clampBackdropHeightM</c>: a finite number clamped to [20, 300]; anything else is the default 120.</summary>
    public static double ClampHeightM(double? heightM)
    {
        double h = heightM is double v && double.IsFinite(v) ? v : HeightDefaultM;
        return Math.Min(HeightMaxM, Math.Max(HeightMinM, h));
    }

    private static double SmoothRamp(double t)
    {
        double x = t <= 0 ? 0 : t >= 1 ? 1 : t;
        return x * x * (3 - 2 * x);
    }

    /// <summary>
    /// <c>ridgeProfile(seed, arcs, heightM, segments, rnd)</c>: per ring, n random node heights in
    /// [0.45, 1] × the ring's top, then per arc the start (height 0), every ring node strictly inside (tapered), the
    /// end (0); a full ring closes at +360° untapered. <paramref name="rnd"/> null = the seeded streams
    /// <c>backdrop-&lt;seed&gt;-l&lt;layer&gt;</c>; an arc with a non-finite end or no span is skipped.
    /// </summary>
    public static List<RidgePoint> RidgeProfile(double seed, IReadOnlyList<(double Start, double End)>? arcs, double? heightM,
                                                double segments = Segments, Func<double>? rnd = null)
    {
        double h0 = ClampHeightM(heightM);
        int n = double.IsFinite(segments) ? (int)Math.Min(720, Math.Max(8, Js.Round(segments))) : Segments;
        double step = 360.0 / n;
        double seedInt = double.IsFinite(seed) ? Math.Truncate(seed) : 1;
        var outList = new List<RidgePoint>();
        for (int layer = 0; layer < Layers; layer++)
        {
            var draw = rnd ?? Random($"backdrop-{FormatInt(seedInt)}-l{layer}");
            double top = h0 * LayerHeightFactor(layer);
            var nodes = new double[n];
            for (int i = 0; i < n; i++) nodes[i] = top * (RidgeMinShare + (1 - RidgeMinShare) * draw());
            foreach (var (start, end) in arcs ?? Array.Empty<(double, double)>())
            {
                if (!double.IsFinite(start) || !double.IsFinite(end)) continue;
                double span = end - start;
                if (span <= 0) continue;
                int Wrap(double i) => (int)(((i % n) + n) % n);
                if (span >= 360 - 1e-9)
                {
                    double i0 = Math.Ceiling(start / step - 1e-9);
                    for (int k = 0; k <= n; k++) outList.Add(new RidgePoint((i0 + k) * step, nodes[Wrap(i0 + k)], layer));
                    continue;
                }
                outList.Add(new RidgePoint(start, 0, layer));
                double first = Math.Ceiling((start + 1e-9) / step);
                double last = Math.Floor((end - 1e-9) / step);
                for (double i = first; i <= last; i += 1)
                {
                    double a = i * step;
                    double dEnd = Math.Min(a - start, end - a);
                    outList.Add(new RidgePoint(a, nodes[Wrap(i)] * SmoothRamp(dEnd / RidgeTaperDeg), layer));
                }
                outList.Add(new RidgePoint(end, 0, layer));
            }
        }
        return outList;
    }

    /// <summary>An integer as a template literal prints it (−0 as "0"; no exponent below 1e21).</summary>
    private static string FormatInt(double v)
        => (v + 0.0).ToString("0", System.Globalization.CultureInfo.InvariantCulture);
}
