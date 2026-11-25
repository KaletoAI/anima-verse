using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace AnimaNative.Figures;

/// <summary>One leg at a relation's deepest frame: hip, knee and ankle joints (metres; x/z relative to the role's hips).</summary>
public sealed record PairLeg(V3 Hip, V3 Knee, V3 Ankle);

/// <summary>A role's pose at a relation's deepest frame, at 1.70 m: support height, hips height, legs [left, right].</summary>
public sealed record PairRolePose(double SupportM, double HipsM, IReadOnlyList<PairLeg> Legs);

/// <summary>One contact relation's stored height (<c>pair_contact_heights[key]</c>).</summary>
public sealed record PairContactHeight(string Key, string Part, string Receiver, double HeightM,
                                       IReadOnlyDictionary<string, PairRolePose> Roles);

/// <summary>The offsets a role may take (metres; <see cref="Down"/> ≤ 0 ≤ <see cref="Up"/>), its stance and its held legs.</summary>
public sealed record PairHeightRange(double Down, double Up, string Stance, bool[] Planted);

/// <summary>The solve of a clip: per role the hips offset (+ = up), held legs and range; per relation the gap and its residual.</summary>
public sealed class PairHeightSolve
{
    public Dictionary<string, double> Offsets { get; } = new();
    public Dictionary<string, bool[]> Planted { get; } = new();
    public Dictionary<string, PairHeightRange> Ranges { get; } = new();
    public Dictionary<string, double> Gaps { get; } = new();
    public Dictionary<string, double> Residuals { get; } = new();
}

/// <summary>
/// PAIR HEIGHT — packages/scene-render/src/pairHeight.ts (owner decision 2026-11-25): the VERTICAL half of the pair scale
/// (<see cref="PairScale"/>). A contact at the stored height h_c (1.70 m) misses by
/// Δ = (s_p + a_p·(h_c − s_p)) − (s_r + a_r·(h_c − s_r)) for figures of scales a; it closes with a constant hips offset per
/// figure and clip, o_receiver − o_part = Δ, inside each role's range (furniture, lying/sitting and carried figures take
/// nothing; a standing figure only lowers by bending its knees; a kneeling/crouching one goes both ways, every planted
/// ankle held by a two-bone IK). The solve is a projected Gauss–Seidel least squares, figures in the order of their range.
/// Equal heights give exactly 0 everywhere (nothing applied). Vectors shared/test-vectors/pair_scale.json (cases H[…],
/// hand derivations scripts/smoke_pair_height.mjs). Every constant and step mirrors the TS twin, operation for operation.
/// </summary>
public static class PairHeight
{
    public const double FurnitureM = 0.05;
    public const double HipsRestM = 0.22;
    public const double FootPlantM = 0.16;
    public const double KneePlantM = 0.13;
    public const double KneeHoldM = 0.02;
    public const double KneeFloorM = 0.06;
    public const double MinBendDeg = 12;
    public const double StandBendDeg = 35;
    public const double FoldM = 0.02;
    public const double MaxM = 0.15;
    public const double MinStepM = 1e-4;
    public const int BisectSteps = 40;
    public const int Sweeps = 64;
    private const double BoundCm = 300;
    private const double Deg = Math.PI / 180;

    private static double Dot(V3 a, V3 b) => a.X * b.X + a.Y * b.Y + a.Z * b.Z;
    private static double Len(V3 a) => Math.Sqrt(Dot(a, a));
    private static V3 Cross(V3 a, V3 b) => new(a.Y * b.Z - a.Z * b.Y, a.Z * b.X - a.X * b.Z, a.X * b.Y - a.Y * b.X);

    /// <summary><c>pairHeightGap</c>: the part's height minus the target's, metres.</summary>
    public static double Gap(double heightM, double partSupportM, double aPart, double recvSupportM, double aRecv)
        => (aPart - aRecv) * heightM + partSupportM * (1 - aPart) - recvSupportM * (1 - aRecv);

    /// <summary><c>scaleRolePose</c>: x, z → a·x, a·z; y → s + a·(y − s); a == 1 returns the pose itself.</summary>
    public static PairRolePose ScaleRolePose(PairRolePose pose, double a)
    {
        if (a == 1) return pose;
        double s = pose.SupportM;
        V3 P(V3 v) => new(a * v.X, s + a * (v.Y - s), a * v.Z);
        return new PairRolePose(s, s + a * (pose.HipsM - s), pose.Legs.Select(l => new PairLeg(P(l.Hip), P(l.Knee), P(l.Ankle))).ToArray());
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

    private static bool LegPlanted(PairLeg leg, double s) => leg.Ankle.Y - s <= FootPlantM || leg.Knee.Y - s <= KneePlantM;

    /// <summary><c>pairOffsetAllowed</c>: whether the hips may move by delta with every planted ankle held.</summary>
    public static bool OffsetAllowed(PairRolePose pose, IReadOnlyList<bool> planted, double delta)
    {
        if (Math.Abs(delta) > MaxM + 1e-12) return false;
        double s = pose.SupportM;
        double cosMin = Math.Cos(MinBendDeg * Deg);
        for (int i = 0; i < pose.Legs.Count; i++)
        {
            if (!planted[i]) continue;
            var leg = pose.Legs[i];
            double l1 = Len(leg.Knee - leg.Hip), l2 = Len(leg.Ankle - leg.Knee);
            var up = new V3(0, delta, 0);
            var hip = leg.Hip + up;
            double d = Len(hip - leg.Ankle);
            if (d > Math.Sqrt(l1 * l1 + l2 * l2 + 2 * l1 * l2 * cosMin) + 1e-12) return false;
            if (d < Math.Abs(l1 - l2) + FoldM) return false;
            var knee = IkKnee(hip, leg.Knee + up, leg.Ankle + up, leg.Ankle);
            if (leg.Knee.Y - s <= KneePlantM && Len(knee - leg.Knee) > KneeHoldM + 1e-12) return false;
            if (knee.Y < s + Math.Min(leg.Knee.Y - s, KneeFloorM) - 1e-12) return false;
        }
        return true;
    }

    private static double Reach(PairRolePose pose, bool[] planted, double sign)
    {
        if (OffsetAllowed(pose, planted, sign * MaxM)) return sign * MaxM;
        if (!OffsetAllowed(pose, planted, sign * MinStepM)) return 0;
        double lo = MinStepM, hi = MaxM;
        for (int k = 0; k < BisectSteps; k++)
        {
            double mid = (lo + hi) / 2;
            if (OffsetAllowed(pose, planted, sign * mid)) lo = mid; else hi = mid;
        }
        return sign * lo;
    }

    /// <summary><c>pairRoleRange</c>: the offsets a role may take for a figure of scale a.</summary>
    public static PairHeightRange RoleRange(PairRolePose pose, double a)
    {
        var p = ScaleRolePose(pose, a);
        double s = p.SupportM;
        var planted = p.Legs.Select(l => LegPlanted(l, s)).ToArray();
        if (s > FurnitureM) return new(0, 0, "fixed", new bool[planted.Length]);
        if (p.HipsM - s < HipsRestM) return new(0, 0, "resting", new bool[planted.Length]);
        if (!planted.Any(x => x)) return new(0, 0, "free", planted);
        bool standing = true;
        for (int i = 0; i < p.Legs.Count; i++)
        {
            var l = p.Legs[i];
            if (planted[i] && !(LegBendDeg(l) < StandBendDeg && l.Knee.Y - s > KneePlantM)) { standing = false; break; }
        }
        return new(Reach(p, planted, -1), standing ? 0 : Reach(p, planted, 1), standing ? "standing" : "bent", planted);
    }

    /// <summary><c>pairHeightOffsets</c>: the offsets of every role of a clip for the figures' scales.</summary>
    public static PairHeightSolve Offsets(IReadOnlyList<PairContactHeight> relations, Func<string, double> scaleOf)
    {
        var output = new PairHeightSolve();
        var poses = new Dictionary<string, PairRolePose>();
        var order0 = new List<string>();
        foreach (var r in relations)
            foreach (var role in new[] { r.Part, r.Receiver })
                if (r.Roles.TryGetValue(role, out var pose) && !poses.ContainsKey(role)) { poses[role] = pose; order0.Add(role); }
        var usable = relations.Where(r => poses.ContainsKey(r.Part) && poses.ContainsKey(r.Receiver) && r.Part != r.Receiver).ToList();
        foreach (var r in usable)
            output.Gaps[r.Key] = Gap(r.HeightM, poses[r.Part].SupportM, scaleOf(r.Part), poses[r.Receiver].SupportM, scaleOf(r.Receiver));
        var roles = order0.OrderBy(x => x, StringComparer.Ordinal).ToList();
        var o = output.Offsets;
        foreach (var role in roles) o[role] = 0;
        if (usable.All(r => output.Gaps[r.Key] == 0))
        {
            foreach (var r in usable) output.Residuals[r.Key] = 0;
            return output;
        }
        foreach (var role in roles)
        {
            output.Ranges[role] = RoleRange(poses[role], scaleOf(role));
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

    // ── the sidecar wire (pair_contact_heights, cm) ──

    private static readonly Regex KeyRx = new(@"^([a-e])>([a-e]):([a-z_]{1,40})\z", RegexOptions.CultureInvariant);
    // \z, not $: .NET's $ also matches before a final newline, JS's does not.
    private static readonly Regex RoleRx = new(@"^[a-e]\z", RegexOptions.CultureInvariant);

    private static bool Num(JsonElement e, out double v, double lo = -BoundCm, double hi = BoundCm)
    {
        v = 0;
        return e.ValueKind == JsonValueKind.Number && e.TryGetDouble(out v) && double.IsFinite(v) && v >= lo && v <= hi;
    }

    private static bool Vec(JsonElement e, out V3 v)
    {
        v = V3.Zero;
        if (e.ValueKind != JsonValueKind.Array || e.GetArrayLength() != 3) return false;
        if (!Num(e[0], out var x) || !Num(e[1], out var y) || !Num(e[2], out var z)) return false;
        v = new V3(x / 100, y / 100, z / 100);
        return true;
    }

    private static PairRolePose? RoleOf(JsonElement w)
    {
        if (w.ValueKind != JsonValueKind.Object) return null;
        if (!w.TryGetProperty("support_cm", out var sc) || !Num(sc, out var support, -50)) return null;
        if (!w.TryGetProperty("hips_cm", out var hc) || !Num(hc, out var hips)) return null;
        if (!w.TryGetProperty("legs", out var lw) || lw.ValueKind != JsonValueKind.Array || lw.GetArrayLength() > 2) return null;
        var legs = new List<PairLeg>();
        foreach (var l in lw.EnumerateArray())
        {
            if (l.ValueKind != JsonValueKind.Array || l.GetArrayLength() != 3) return null;
            if (!Vec(l[0], out var hip) || !Vec(l[1], out var knee) || !Vec(l[2], out var ankle)) return null;
            legs.Add(new PairLeg(hip, knee, ankle));
        }
        return new PairRolePose(support / 100, hips / 100, legs);
    }

    /// <summary><c>pairContactHeightsOf</c>: the listing's <c>pair_contact_heights</c>, sorted by key; empty for none or
    /// malformed (a malformed relation is skipped, the others stay).</summary>
    public static IReadOnlyList<PairContactHeight> ContactHeightsOf(JsonElement wire)
    {
        var output = new List<PairContactHeight>();
        if (wire.ValueKind != JsonValueKind.Object) return output;
        var entries = new Dictionary<string, JsonElement>(StringComparer.Ordinal);
        foreach (var p in wire.EnumerateObject()) entries[p.Name] = p.Value;
        foreach (var key in entries.Keys.OrderBy(k => k, StringComparer.Ordinal))
        {
            var m = KeyRx.Match(key);
            var e = entries[key];
            if (!m.Success || m.Groups[1].Value == m.Groups[2].Value || e.ValueKind != JsonValueKind.Object) continue;
            if (!e.TryGetProperty("height_cm", out var hc) || !Num(hc, out var height, 0)) continue;
            if (!e.TryGetProperty("roles", out var rw) || rw.ValueKind != JsonValueKind.Object) continue;
            var roles = new Dictionary<string, PairRolePose>();
            bool bad = false;
            foreach (var rp in rw.EnumerateObject())
            {
                var pose = RoleRx.IsMatch(rp.Name) ? RoleOf(rp.Value) : null;
                if (pose is null) { bad = true; break; }
                roles[rp.Name] = pose;
            }
            if (bad || !roles.ContainsKey(m.Groups[1].Value) || !roles.ContainsKey(m.Groups[2].Value)) continue;
            output.Add(new PairContactHeight(key, m.Groups[1].Value, m.Groups[2].Value, height / 100, roles));
        }
        return output;
    }
}
