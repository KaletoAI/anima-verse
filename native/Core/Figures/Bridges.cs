using System;
using System.Collections.Generic;
using AnimaNative.Scatter;

namespace AnimaNative.Figures;

/// <summary>What a bridge clip needs for its height, measured once per rig (bridgeLift.ts <c>BridgeLift</c>).</summary>
/// <param name="EndLift">lift that puts the lowest foot point of the clip's LAST frame onto the rig's rest floor, template units</param>
/// <param name="FirstContactS">clip time of the first frame with a foot point in FULL contact (the duration when none is)</param>
public sealed record BridgeLiftSpec(double EndLift, double FirstContactS);

/// <summary>
/// The TURN of a bridge clip (bridgeTravel.ts <c>RootTurn</c>): yaw per key relative to frame 0 (radians, the
/// <see cref="BridgeTravel.ToWorld"/> convention) and the hips' rest point in template-local coordinates (the pivot).
/// </summary>
public sealed record RootTurn(float[] Times, float[] Yaw, V3 Pivot);

/// <summary>
/// THE HEIGHT OF A BRIDGE — client3d/src/scene/bridgeLift.ts, vectors shared/test-vectors/bridge_lift.json (hand
/// derivations: client3d/scripts/smoke_bridge_lift.mjs). Lifts are metres in the frame of the figure root, times clip
/// seconds.
/// </summary>
public static class BridgeLift
{
    /// <summary>How long before the feet's first ground contact the body starts to move onto the landing height, s.</summary>
    public const double LiftRampS = 0.6;
    /// <summary>The crossfade a bridge clip starts with, s (the bridge fades in, the clip it leaves out, by this).</summary>
    public const double BridgeFadeInS = 0.25;

    /// <summary><c>liftRamp(firstContactS)</c>: ends at the first contact but never before the start crossfade, begins LIFT_RAMP_S earlier (not before 0).</summary>
    public static (double From, double To) LiftRamp(double firstContactS)
    {
        double to = Math.Max(firstContactS, BridgeFadeInS);
        return (Math.Max(0, to - LiftRampS), to);
    }

    /// <summary>
    /// <c>liftAt(t, startLift, endLift, firstContactS)</c>: startLift up to the ramp, a smoothstep onto endLift, endLift
    /// after; a non-finite t / endLift / firstContactS answers startLift, a non-finite startLift counts as 0.
    /// </summary>
    public static double LiftAt(double t, double startLift, double endLift, double firstContactS)
    {
        double start = double.IsFinite(startLift) ? startLift : 0;
        if (!double.IsFinite(t) || !double.IsFinite(endLift) || !double.IsFinite(firstContactS)) return start;
        var (from, to) = LiftRamp(firstContactS);
        if (t >= to) return endLift;
        if (t <= from) return start;
        double x = (t - from) / (to - from);
        double s = x * x * (3 - 2 * x);
        return start + (endLift - start) * s;
    }

    /// <summary><c>fadeCarry(amount, elapsedS)</c>: amount at 0, a smoothstep down to 0 at LIFT_RAMP_S; non-finite → 0.</summary>
    public static double FadeCarry(double amount, double elapsedS)
    {
        if (!double.IsFinite(amount) || !double.IsFinite(elapsedS)) return 0;
        if (elapsedS <= 0) return amount;
        if (elapsedS >= LiftRampS) return 0;
        double x = elapsedS / LiftRampS;
        return amount * (1 - x * x * (3 - 2 * x));
    }
}

/// <summary>
/// The horizontal TRAVEL and TURN of a clip's root — client3d/src/scene/bridgeTravel.ts, vectors
/// shared/test-vectors/bridge_travel.json (smoke_bridge_root.mjs) and bridge_heading.json (<c>turnAt</c>). Frame: the
/// clip frame (+Z forward, +X the figure's LEFT).
/// </summary>
public static class BridgeTravel
{
    /// <summary>Binary search: the key pair around <paramref name="t"/> (times[lo] ≤ t &lt; times[hi]).</summary>
    private static (int Lo, int Hi) Bracket(float[] times, double t)
    {
        int lo = 0, hi = times.Length - 1;
        while (hi - lo > 1)
        {
            int mid = (lo + hi) >> 1;
            if (times[mid] <= t) lo = mid; else hi = mid;
        }
        return (lo, hi);
    }

    /// <summary><c>rootPathAt(path, t)</c>: root (x, z) at clip time t — linear between keys, clamped at both ends; NaN → the first key.</summary>
    public static (double X, double Z) RootPathAt(RootPath path, double t)
    {
        var times = path.Times;
        var xz = path.Xz;
        int n = times.Length;
        if (n == 0) return (0, 0);
        if (!(t > times[0])) return (xz[0], xz[1]);
        if (t >= times[n - 1]) return (xz[(n - 1) * 2], xz[(n - 1) * 2 + 1]);
        var (lo, hi) = Bracket(times, t);
        double span = times[hi] - (double)times[lo];
        if (span == 0) span = 1;
        double f = (t - times[lo]) / span;
        return (xz[lo * 2] + (xz[hi * 2] - (double)xz[lo * 2]) * f, xz[lo * 2 + 1] + (xz[hi * 2 + 1] - (double)xz[lo * 2 + 1]) * f);
    }

    /// <summary><c>travelAt(path, t)</c>: how far the clip has carried its root at t, RELATIVE to frame 0.</summary>
    public static (double X, double Z) TravelAt(RootPath path, double t)
    {
        if (path.Times.Length == 0) return (0, 0);
        var p = RootPathAt(path, t);
        return (p.X - path.Xz[0], p.Z - path.Xz[1]);
    }

    /// <summary><c>turnAt(turn, t)</c>: the turn at clip time t (linear, clamped; NaN → the first key; empty → 0).</summary>
    public static double TurnAt(RootTurn turn, double t)
    {
        var times = turn.Times;
        var yaw = turn.Yaw;
        int n = times.Length;
        if (n == 0) return 0;
        if (!(t > times[0])) return yaw[0];
        if (t >= times[n - 1]) return yaw[n - 1];
        var (lo, hi) = Bracket(times, t);
        double span = times[hi] - (double)times[lo];
        if (span == 0) span = 1;
        return yaw[lo] + (yaw[hi] - (double)yaw[lo]) * ((t - times[lo]) / span);
    }

    /// <summary><c>toWorld(local, yaw)</c>: a clip-frame offset turned by the yaw: x' = x·cos + z·sin, z' = −x·sin + z·cos.</summary>
    public static (double X, double Z) ToWorld(double x, double z, double yaw)
    {
        double c = Math.Cos(yaw), s = Math.Sin(yaw);
        return (x * c + z * s, -x * s + z * c);
    }
}

/// <summary>
/// THE HEADING OF A BRIDGE CLIP'S PELVIS — client3d/src/scene/bridgeHeading.ts, vectors
/// shared/test-vectors/bridge_heading.json (hand derivations: client3d/scripts/smoke_bridge_heading.mjs).
/// </summary>
public static class BridgeHeading
{
    /// <summary>Least share of the cross vector that must lie in the ground plane for a frame to have a heading.</summary>
    public const double HeadingMinHorizontal = 0.5;

    private static double Wrap(double a) => Math.Atan2(Math.Sin(a), Math.Cos(a));

    /// <summary>
    /// <c>headingTrack(left, right)</c>: the pelvis heading per frame relative to frame 0, unwrapped (Float32 like the
    /// browser); L = left − right, heading = atan2(L.x, L.z) − π/2; a frame less than half horizontal keeps the last value.
    /// </summary>
    public static float[] HeadingTrack(IReadOnlyList<V3> leftUpLeg, IReadOnlyList<V3> rightUpLeg)
    {
        int n = Math.Min(leftUpLeg.Count, rightUpLeg.Count);
        var output = new float[n];
        double? prev = null;
        double acc = 0;
        for (int f = 0; f < n; f++)
        {
            var l = leftUpLeg[f];
            var r = rightUpLeg[f];
            double x = l.X - r.X, y = l.Y - r.Y, z = l.Z - r.Z;
            double flat = Math.Sqrt(x * x + z * z);
            double len = Math.Sqrt(x * x + y * y + z * z);
            if (len > 0 && flat / len >= HeadingMinHorizontal)
            {
                double h = Math.Atan2(x, z) - Math.PI / 2;
                if (prev is { } p) acc += Wrap(h - p);
                prev = h;
            }
            output[f] = (float)acc;
        }
        return output;
    }
}

/// <summary>
/// WHERE AN NPC STANDS AFTER A BRIDGE CLIP — client3d/src/scene/standSettle.ts, vectors
/// shared/test-vectors/stand_settle.json (hand derivations: client3d/scripts/smoke_stand_settle.mjs).
/// </summary>
public static class StandSettle
{
    /// <summary>How far off the server's stand point a figure may stand and keep its spot, m (the server's stand raster).</summary>
    public const double StandAdoptM = 0.25;
    /// <summary>Two server positions closer than this are the SAME position, m.</summary>
    public const double SameStandM = 0.001;

    /// <summary>
    /// <c>settleOffset(figurePos, serverPos, lastServerPos, tol)</c>: the offset figure − server the NPC keeps, or null
    /// (the server moved further than SAME_STAND_M, or the figure stands further than tol off; the bound is inclusive).
    /// </summary>
    public static P2? SettleOffset(P2 figurePos, P2 serverPos, P2 lastServerPos, double tol = StandAdoptM)
    {
        double mx = serverPos.X - lastServerPos.X, mz = serverPos.Z - lastServerPos.Z;
        if (!(Math.Sqrt(mx * mx + mz * mz) <= SameStandM)) return null;
        double x = figurePos.X - serverPos.X, z = figurePos.Z - serverPos.Z;
        return Math.Sqrt(x * x + z * z) <= tol ? new P2(x, z) : null;
    }
}
