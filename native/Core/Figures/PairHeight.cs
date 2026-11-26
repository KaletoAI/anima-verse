using System;
using System.Collections.Generic;
using System.Linq;

namespace AnimaNative.Figures;

/// <summary>One leg: hip, knee and ankle joints (world metres).</summary>
public sealed record PairLeg(V3 Hip, V3 Knee, V3 Ankle);

/// <summary>One role at one sampled phase (world metres): the ground under it, its hips height, its legs [left, right].</summary>
public sealed record PairHeightRoleFrame(double GroundM, double HipsM, IReadOnlyList<PairLeg> Legs);

/// <summary>One role's sampled loop; &lt;see cref="Fixed"/&gt; = it sits on a place (furniture) and takes nothing.</summary>
public sealed record PairHeightRole(IReadOnlyList<PairHeightRoleFrame> Frames, bool Fixed = false);

/// <summary>One relation at one sampled phase: the part's straight axis (root, unit direction, length) and the opening.</summary>
public sealed record PairHeightRelationFrame(V3 Root, V3 Axis, double LengthM, V3 Opening);

/// <summary>One contact relation (&lt;c&gt;&lt;part&gt;&gt;&lt;receiver&gt;:&lt;target&gt;&lt;/c&gt;); per sampled phase a frame or null.</summary>
public sealed record PairHeightRelation(string Key, string Part, string Receiver, IReadOnlyList<PairHeightRelationFrame?> Frames);

/// <summary>A role's class over its loop: stance, planted legs, held knees.</summary>
public record PairRoleClass(string Stance, bool[] Planted, bool[] KneeHeld);

/// <summary>The offsets a role may take (metres; &lt;see cref="Down"/&gt; ≤ 0 ≤ &lt;see cref="Up"/&gt;) and its class.</summary>
public sealed record PairHeightRange(string Stance, bool[] Planted, bool[] KneeHeld, double Down, double Up)
    : PairRoleClass(Stance, Planted, KneeHeld);

/// <summary>The solve of an interaction: per role the hips offset (+ = up), held legs and range; per relation its contact
/// phase, the gap there and its residual.</summary>
public sealed class PairHeightSolve
{
    public Dictionary<string, double> Offsets { get; } = new();
    public Dictionary<string, bool[]> Planted { get; } = new();
    public Dictionary<string, PairHeightRange> Ranges { get; } = new();
    public Dictionary<string, int> ContactFrames { get; } = new();
    public Dictionary<string, double> Gaps { get; } = new();
    public Dictionary<string, double> Residuals { get; } = new();
}

/// <summary>
/// PAIR HEIGHT — packages/scene-render/src/pairHeight.ts (owner decision 2026-11-25, reworked 2026-11-26): nothing is
/// stored; a renderer samples one loop of the clip as the figures really stand (&lt;see cref="Samples"/&gt; phases, without the
/// compensation) and hands per role its ground, hips and legs, per relation the part's straight axis and the receiving
/// opening. The gap of a relation is read at its contact phase (the frame where the opening is nearest the straight
/// segment): Δ = P_y + λ·u_y − O_y with λ the axis parameter horizontally nearest to O. It closes with a constant hips offset
/// per figure and clip, o_receiver − o_part = Δ, inside each role's range, decided over the WHOLE loop (planted legs
/// relative to the figure's lowest joint, with a hysteresis band). The solve is a projected Gauss–Seidel least squares.
/// Vectors shared/test-vectors/pair_scale.json (cases H[…], hand derivations scripts/smoke_pair_height.mjs). Every
/// constant and step mirrors the TS twin, operation for operation.
/// </summary>
public static class PairHeight
{
    public const double DeadbandM = 0.005;
    public const double HipsRestM = 0.22;
    public const double CarriedM = 0.35;
    public const double DownFrac = 0.12;
    public const double UpFrac = 0.22;
    public const double KneeHoldM = 0.02;
    public const double KneeFloorM = 0.06;
    public const double MinBendDeg = 12;
    public const double StandBendDeg = 35;
    public const double FoldM = 0.02;
    public const double MaxM = 0.15;
    public const double MinStepM = 1e-4;
    public const int BisectSteps = 40;
    public const int Sweeps = 64;
    /// <summary>How many phases of one loop a renderer samples.</summary>
    public const int Samples = 24;
    private const double Deg = Math.PI / 180;

    private static double Dot(V3 a, V3 b) => a.X * b.X + a.Y * b.Y + a.Z * b.Z;
    private static double Len(V3 a) => Math.Sqrt(Dot(a, a));
    private static V3 Cross(V3 a, V3 b) => new(a.Y * b.Z - a.Z * b.Y, a.Z * b.X - a.X * b.Z, a.X * b.Y - a.Y * b.X);

    private static double Median(IEnumerable<double> xs)
    {
        var s = xs.OrderBy(x => x).ToArray();
        if (s.Length == 0) return 0;
        return s.Length % 2 == 1 ? s[(s.Length - 1) / 2] : (s[s.Length / 2 - 1] + s[s.Length / 2]) / 2;
    }

    /// <summary><c>pairRelationFrame</c>: a relation frame from the chain's points (root first, tip last); null when degenerate.</summary>
    public static PairHeightRelationFrame? RelationFrame(IReadOnlyList<V3> chain, V3 opening)
    {
        if (chain.Count < 2) return null;
        var root = chain[0];
        var d = chain[^1] - root;
        double l = Len(d);
        if (!(l > 1e-6)) return null;
        return new PairHeightRelationFrame(root, d * (1 / l), l, opening);
    }

    /// <summary><c>pairAxisDistance</c>: the opening's distance from the straight segment.</summary>
    public static double AxisDistance(PairHeightRelationFrame f)
    {
        double t = Math.Max(0, Math.Min(f.LengthM, Dot(f.Opening - f.Root, f.Axis)));
        return Len(f.Opening - (f.Root + f.Axis * t));
    }

    /// <summary><c>pairContactFrame</c>: the frame index of the smallest axis distance; −1 when none resolved.</summary>
    public static int ContactFrame(IReadOnlyList<PairHeightRelationFrame?> frames)
    {
        int best = -1;
        double d = double.PositiveInfinity;
        for (int i = 0; i < frames.Count; i++)
        {
            if (frames[i] is not { } f) continue;
            double x = AxisDistance(f);
            if (x < d) { d = x; best = i; }
        }
        return best;
    }

    /// <summary><c>pairAxisGap</c>: the axis line's height where it is horizontally nearest to the opening, minus the opening's.</summary>
    public static double AxisGap(PairHeightRelationFrame f)
    {
        var u = f.Axis;
        var o = f.Opening - f.Root;
        double h2 = u.X * u.X + u.Z * u.Z;
        double lambda = Math.Max(0, h2 > 1e-6 ? (o.X * u.X + o.Z * u.Z) / h2 : Dot(o, u));
        return f.Root.Y + lambda * u.Y - f.Opening.Y;
    }

    /// <summary><c>ikKnee</c>: the knee the two-bone IK puts down when the hip is at hip and the ankle reaches target (pole = the knee).</summary>
    public static V3 IkKnee(V3 hip, V3 knee, V3 ankle, V3 target)
    {
        double l1 = Len(knee - hip), l2 = Len(ankle - knee);
        var toT = target - hip;
        double d = Len(toT);
        if (l1 < 1e-9 || l2 < 1e-9 || d < 1e-9) return knee;
        var t = toT * (1 / d);
        d = Math.Min(Math.Max(d, Math.Abs(l1 - l2) + 1e-9), l1 + l2);
        var p = knee - hip;
        var u = p - t * Dot(p, t);
        if (Len(u) < 1e-9)
        {
            u = Cross(t, new V3(1, 0, 0));
            if (Len(u) < 1e-6) u = Cross(t, new V3(0, 0, 1));
        }
        u = u * (1 / Len(u));
        double cosA = Math.Max(-1, Math.Min(1, (l1 * l1 + d * d - l2 * l2) / (2 * l1 * d)));
        double sinA = Math.Sqrt(Math.Max(0, 1 - cosA * cosA));
        return hip + (t * (l1 * cosA) + u * (l1 * sinA));
    }

    /// <summary><c>legBendDeg</c>: degrees from straight.</summary>
    public static double LegBendDeg(PairLeg leg)
    {
        var a = leg.Knee - leg.Hip;
        var b = leg.Ankle - leg.Knee;
        double la = Len(a), lb = Len(b);
        if (la < 1e-9 || lb < 1e-9) return 0;
        return Math.Acos(Math.Max(-1, Math.Min(1, Dot(a, b) / (la * lb)))) / Deg;
    }

    private static double LegLength(PairLeg l) => Len(l.Knee - l.Hip) + Len(l.Ankle - l.Knee);

    /// <summary><c>pairRoleClass</c>: the class of one role over its sampled frames.</summary>
    public static PairRoleClass RoleClass(PairHeightRole role)
    {
        var frames = role.Frames;
        int nLegs = frames.Count == 0 ? 0 : frames.Max(f => f.Legs.Count);
        PairRoleClass None(string stance) => new(stance, new bool[nLegs], new bool[nLegs]);
        if (role.Fixed) return None("fixed");
        if (frames.Count == 0 || nLegs == 0) return None("free");
        var lowest = frames.Select(f => f.Legs.SelectMany(l => new[] { l.Ankle.Y, l.Knee.Y }).Min()).ToArray();
        if (Median(frames.Select((f, i) => f.HipsM - lowest[i])) < HipsRestM) return None("resting");
        if (Median(frames.Select((f, i) => lowest[i] - f.GroundM)) > CarriedM) return None("free");
        var planted = new bool[nLegs];
        var kneeHeld = new bool[nLegs];
        for (int i = 0; i < nLegs; i++)
        {
            int legDown = 0, legUp = 0, kneeDown = 0, kneeUp = 0;
            for (int k = 0; k < frames.Count; k++)
            {
                if (i >= frames[k].Legs.Count) continue;
                var l = frames[k].Legs[i];
                double ll = LegLength(l), low = lowest[k];
                int State(double y) => y - low <= DownFrac * ll ? 1 : y - low > UpFrac * ll ? -1 : 0;
                int a = State(l.Ankle.Y), kn = State(l.Knee.Y);
                int leg = Math.Max(a, kn);
                if (leg > 0) legDown++; else if (leg < 0) legUp++;
                if (kn > 0) kneeDown++; else if (kn < 0) kneeUp++;
            }
            planted[i] = legDown > legUp;
            kneeHeld[i] = planted[i] && kneeDown > kneeUp;
        }
        if (!planted.Any(x => x)) return new("free", planted, kneeHeld);
        bool standing = !kneeHeld.Any(x => x);
        for (int i = 0; standing && i < nLegs; i++)
        {
            if (!planted[i]) continue;
            int straight = frames.Count(f => i < f.Legs.Count && LegBendDeg(f.Legs[i]) < StandBendDeg);
            if (!(straight * 2 > frames.Count)) standing = false;
        }
        return new(standing ? "standing" : "bent", planted, kneeHeld);
    }

    /// <summary><c>pairOffsetAllowed</c>: whether the hips of one frame may move by delta with every planted ankle held.</summary>
    public static bool OffsetAllowed(PairHeightRoleFrame frame, PairRoleClass cls, double delta)
    {
        if (Math.Abs(delta) > MaxM + 1e-12) return false;
        double s = frame.GroundM;
        double cosMin = Math.Cos(MinBendDeg * Deg);
        for (int i = 0; i < frame.Legs.Count; i++)
        {
            if (i >= cls.Planted.Length || !cls.Planted[i]) continue;
            var leg = frame.Legs[i];
            double l1 = Len(leg.Knee - leg.Hip), l2 = Len(leg.Ankle - leg.Knee);
            var up = new V3(0, delta, 0);
            var hip = leg.Hip + up;
            double d = Len(hip - leg.Ankle);
            if (d > Math.Sqrt(l1 * l1 + l2 * l2 + 2 * l1 * l2 * cosMin) + 1e-12) return false;
            if (d < Math.Abs(l1 - l2) + FoldM) return false;
            var knee = IkKnee(hip, leg.Knee + up, leg.Ankle + up, leg.Ankle);
            if (cls.KneeHeld[i] && Len(knee - leg.Knee) > KneeHoldM + 1e-12) return false;
            if (knee.Y < s + Math.Min(leg.Knee.Y - s, KneeFloorM) - 1e-12) return false;
        }
        return true;
    }

    private static double Reach(IReadOnlyList<PairHeightRoleFrame> frames, PairRoleClass cls, double sign)
    {
        bool Ok(double m) => frames.All(f => OffsetAllowed(f, cls, sign * m));
        if (Ok(MaxM)) return sign * MaxM;
        if (!Ok(MinStepM)) return 0;
        double lo = MinStepM, hi = MaxM;
        for (int k = 0; k < BisectSteps; k++)
        {
            double mid = (lo + hi) / 2;
            if (Ok(mid)) lo = mid; else hi = mid;
        }
        return sign * lo;
    }

    /// <summary><c>pairRoleRange</c>: the offsets a role may take over its sampled frames.</summary>
    public static PairHeightRange RoleRange(PairHeightRole role)
    {
        var c = RoleClass(role);
        if (c.Stance is "fixed" or "resting" or "free") return new(c.Stance, c.Planted, c.KneeHeld, 0, 0);
        return new(c.Stance, c.Planted, c.KneeHeld, Reach(role.Frames, c, -1), c.Stance == "standing" ? 0 : Reach(role.Frames, c, 1));
    }

    /// <summary><c>pairHeightOffsets</c>: the offsets of every role of an interaction from its sampled loop.</summary>
    public static PairHeightSolve Offsets(IReadOnlyDictionary<string, PairHeightRole> roleMap, IReadOnlyList<PairHeightRelation> relations)
    {
        var output = new PairHeightSolve();
        var roles = roleMap.Keys.OrderBy(x => x, StringComparer.Ordinal).ToList();
        var o = output.Offsets;
        foreach (var role in roles) o[role] = 0;
        var usable = new List<PairHeightRelation>();
        foreach (var r in relations)
        {
            if (r.Part == r.Receiver || !roleMap.ContainsKey(r.Part) || !roleMap.ContainsKey(r.Receiver)) continue;
            int k = ContactFrame(r.Frames);
            if (k < 0) continue;
            double gap = AxisGap(r.Frames[k]!);
            output.ContactFrames[r.Key] = k;
            output.Gaps[r.Key] = Math.Abs(gap) < DeadbandM ? 0 : gap;
            usable.Add(r);
        }
        if (usable.All(r => output.Gaps[r.Key] == 0))
        {
            foreach (var r in usable) output.Residuals[r.Key] = 0;
            return output;
        }
        foreach (var role in roles)
        {
            output.Ranges[role] = RoleRange(roleMap[role]);
            output.Planted[role] = output.Ranges[role].Planted;
        }
        double? Want(string role)
        {
            double sum = 0;
            int n = 0;
            foreach (var r in usable)
            {
                if (r.Receiver == role) { sum += o[r.Part] + output.Gaps[r.Key]; n++; }
                if (r.Part == role) { sum += o[r.Receiver] - output.Gaps[r.Key]; n++; }
            }
            return n > 0 ? sum / n : null;
        }
        var first = new Dictionary<string, double>();
        foreach (var role in roles)
        {
            double w = Want(role) ?? 0;
            var rg = output.Ranges[role];
            first[role] = w > 0 ? rg.Up : w < 0 ? -rg.Down : 0;
        }
        var order = roles.ToList();
        order.Sort((x, y) => { double c = first[y] - first[x]; return c != 0 ? Math.Sign(c) : string.CompareOrdinal(x, y); });
        for (int sweep = 0; sweep < Sweeps; sweep++)
        {
            double change = 0;
            foreach (var role in order)
            {
                if (Want(role) is not { } w) continue;
                var rg = output.Ranges[role];
                double v = Math.Max(rg.Down, Math.Min(rg.Up, w));
                change = Math.Max(change, Math.Abs(v - o[role]));
                o[role] = v;
            }
            if (change < 1e-12) break;
        }
        foreach (var r in usable) output.Residuals[r.Key] = output.Gaps[r.Key] - (o[r.Receiver] - o[r.Part]);
        return output;
    }
}
