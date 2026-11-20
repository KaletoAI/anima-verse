using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text.Json;
using AnimaNative.Overview;

namespace AnimaNative.Figures;

/// <summary>One capsule of the model's <c>collision</c> payload (collision.ts <c>CollisionCapsule</c>): two joints, a
/// radius in metres of the body's bind space, optional bind-space endpoints fixed to those joints.</summary>
public sealed record CollisionCapsule(string Id, string A, string B, double R, string Region, V3? APos, V3? BPos);

/// <summary>
/// The model's <c>collision</c> payload (collision.ts <c>CollisionPayload</c>; model3d <c>model.collision</c>,
/// docs/schnittstellen-3d.md "Collision capsules"). Only what the hair chains read is kept: the version and the
/// capsules (channels, mouth, scales and the rest belong to partner contact, a later stage).
/// </summary>
public sealed record CollisionPayload(int Version, IReadOnlyList<CollisionCapsule> Capsules)
{
    /// <summary>A payload object; null when it is none (absent / null / not an object).</summary>
    public static CollisionPayload? Parse(JsonElement p)
    {
        if (p.ValueKind != JsonValueKind.Object) return null;
        int version = p.TryGetProperty("version", out var v) && v.ValueKind == JsonValueKind.Number && v.TryGetInt32(out var n) ? n : -1;
        var capsules = new List<CollisionCapsule>();
        if (p.TryGetProperty("capsules", out var cs) && cs.ValueKind == JsonValueKind.Array)
            foreach (var c in cs.EnumerateArray())
            {
                if (c.ValueKind != JsonValueKind.Object) continue;
                string Str(string k) => c.TryGetProperty(k, out var s) && s.ValueKind == JsonValueKind.String ? s.GetString()! : "";
                V3? Pos(string k) => c.TryGetProperty(k, out var a) && a.ValueKind == JsonValueKind.Array && a.GetArrayLength() >= 3
                                     && a.EnumerateArray().Take(3).All(x => x.ValueKind == JsonValueKind.Number)
                    ? new V3(a[0].GetDouble(), a[1].GetDouble(), a[2].GetDouble()) : null;
                // A radius that is no number is JS undefined: !(r > 0) leaves the capsule out at the binding.
                double r = c.TryGetProperty("r", out var rr) && rr.ValueKind == JsonValueKind.Number ? rr.GetDouble() : double.NaN;
                capsules.Add(new CollisionCapsule(Str("id"), Str("a"), Str("b"), r, Str("region"), Pos("a_pos"), Pos("b_pos")));
            }
        return new CollisionPayload(version, capsules);
    }

    /// <summary>The <c>collision</c> of a model3d answer's <c>model</c> object; null when absent.</summary>
    public static CollisionPayload? Of(JsonElement model)
        => model.ValueKind == JsonValueKind.Object && model.TryGetProperty("collision", out var c) ? Parse(c) : null;
}

/// <summary>A capsule in the current frame, world space (collision.ts <c>CapsuleNow</c>).</summary>
public readonly record struct CapsuleNow(V3 A, V3 B, double R);

/// <summary>One endpoint's joint in the current frame: its world position and its bind→world matrix (<c>JointNow</c>).</summary>
public readonly record struct JointNow(V3 Position, Affine BindToWorld);

/// <summary>
/// A capsule the push reads (garmentCollision.ts <c>CollideCapsule</c>): the capsule now, plus — under the BIND RULE —
/// the same capsule in the bind pose (<see cref="BindA"/>/<see cref="BindB"/>; null = no bind rule).
/// </summary>
public readonly record struct CollideCapsule(V3 A, V3 B, double R, V3? BindA = null, V3? BindB = null);

/// <summary>A body joint the binding looks capsules up in: its rig node and its bone inverse (three's
/// <c>boneInverse</c>, Godot's skin bind pose) from a BODY skin.</summary>
public readonly record struct BodyJoint(int Node, Affine BoneInverse);

/// <summary>A capsule bound to a figure (<c>BoundCapsule</c>): <see cref="Now"/> refreshed by
/// <see cref="CollisionBinding.Update"/>, <see cref="Bind"/> the same capsule in the bind pose — fixed.</summary>
public sealed class BoundCapsule
{
    public required CollisionCapsule Capsule { get; init; }
    public CapsuleNow Now { get; internal set; }
    public required CapsuleNow Bind { get; init; }
    public required BodyJoint Ja { get; init; }
    public required BodyJoint Jb { get; init; }
}

/// <summary>
/// collision.ts <c>bindCollision</c> / <c>CollisionBinding</c> without three: the body joints come in as a name map
/// (<see cref="BoneNames.Norm"/> → node + bone inverse, the first BODY skin that has the joint — <c>bodyJoints</c>),
/// the current bone world matrices from the caller.
/// </summary>
public sealed class CollisionBinding
{
    private readonly Affine _bindMatrix;
    /// <summary>The capsules whose joints the figure has, in payload order.</summary>
    public IReadOnlyList<BoundCapsule> Capsules { get; }
    /// <summary>Ids of payload capsules whose joints the figure lacks, or whose radius is not &gt; 0.</summary>
    public IReadOnlyList<string> Missing { get; }

    private CollisionBinding(List<BoundCapsule> capsules, List<string> missing, Affine bindMatrix)
    {
        Capsules = capsules;
        Missing = missing;
        _bindMatrix = bindMatrix;
    }

    /// <summary>
    /// <c>bindCollision</c>: null for a payload of another version or without capsules. A joint at bind goes through
    /// <c>jointNowFrom(bindMatrix, bindMatrix⁻¹, boneInverse⁻¹, boneInverse, bindMatrix)</c>; on Godot the geometry
    /// space IS the bind space, so <paramref name="bindMatrix"/> is the identity there.
    /// </summary>
    public static CollisionBinding? Bind(CollisionPayload? payload, IReadOnlyDictionary<string, BodyJoint> joints, Affine bindMatrix)
    {
        if (payload is null || payload.Version != Collision.Version || payload.Capsules.Count == 0) return null;
        var bindInverse = bindMatrix.Inverted();
        JointNow AtBind(BodyJoint j) => Collision.JointNowFrom(bindMatrix, bindInverse, j.BoneInverse.Inverted(), j.BoneInverse, bindMatrix);
        var bound = new List<BoundCapsule>();
        var missing = new List<string>();
        foreach (var c in payload.Capsules)
        {
            if (!joints.TryGetValue(BoneNames.Norm(c.A), out var ja) || !joints.TryGetValue(BoneNames.Norm(c.B), out var jb) || !(c.R > 0))
            {
                missing.Add(c.Id);
                continue;
            }
            bound.Add(new BoundCapsule { Capsule = c, Ja = ja, Jb = jb, Now = new CapsuleNow(V3.Zero, V3.Zero, c.R),
                                         Bind = Collision.CapsuleNowOf(c, AtBind(ja), AtBind(jb)) });
        }
        return new CollisionBinding(bound, missing, bindMatrix);
    }

    /// <summary>
    /// <c>update()</c>: every capsule from the CURRENT bone matrices (<c>jointRefNow</c>: mesh world · bindMatrixInverse
    /// · bone world, then · boneInverse · bindMatrix). On Godot mesh world · bindMatrixInverse is the identity.
    /// </summary>
    public void Update(Func<int, Affine> boneWorld, Affine meshWorld, Affine bindMatrixInverse)
    {
        JointNow Now(BodyJoint j) => Collision.JointNowFrom(meshWorld, bindMatrixInverse, boneWorld(j.Node), j.BoneInverse, _bindMatrix);
        foreach (var e in Capsules) e.Now = Collision.CapsuleNowOf(e.Capsule, Now(e.Ja), Now(e.Jb));
    }
}

/// <summary>
/// The pure collision core the hair chains need — packages/scene-render/src/collision.ts (the endpoint rule),
/// garmentCollision.ts (the TypeScript twin of the push, own capsules only: no partner list) and the contact search of
/// secondaryMotion.ts. Godot-free. Vectors: shared/test-vectors/collision_core.json (generated from the TypeScript by
/// scripts/export_hair_vectors.mjs).
/// </summary>
public static class Collision
{
    /// <summary><c>COLLISION_VERSION</c>: every reader compares against it, another version is ignored.</summary>
    public const int Version = 9;
    /// <summary><c>HAIR_ONLY_REGIONS</c>.</summary>
    public static readonly string[] HairOnlyRegions = { "chest_hair", "shoulder_hair" };
    /// <summary><c>PARTNER_ONLY_REGIONS</c>.</summary>
    public static readonly string[] PartnerOnlyRegions = { "outer_trunk" };
    /// <summary>garmentCollision.ts <c>HAIR_REGIONS</c>: what pushes the hair (cards and chains).</summary>
    public static readonly string[] HairRegions = { "torso", "arm", "head", "shoulder_hair", "chest_hair" };

    /// <summary><c>COLLIDE_MAX</c>: capsules per push list.</summary>
    public const int CollideMax = 16;
    /// <summary><c>COLLIDE_PASSES</c>.</summary>
    public const int CollidePasses = 2;
    /// <summary><c>COLLIDE_EPS</c>: squared axis length below which a capsule is a sphere around a.</summary>
    public const double CollideEps = 1e-12;
    /// <summary><c>COLLIDE_MIN_D</c>: a point this close to the axis has no outward direction.</summary>
    public const double CollideMinD = 1e-6;
    public const int SqueezeRounds = 3;
    public const int SqueezeSteps = 16;
    public const double SqueezeMinN = 1e-3;

    /// <summary>secondaryMotion.ts <c>CONTACT_SCAN</c> / <c>CONTACT_REFINE</c> / <c>COLLIDE_SLACK</c>.</summary>
    public const int ContactScan = 12;
    public const int ContactRefine = 14;
    public const double CollideSlack = 1e-6;

    // ---- collision.ts ------------------------------------------------------------------------------------------

    /// <summary><c>linearScale</c>: the mean length of the three basis columns.</summary>
    public static double LinearScale(Affine m)
        => (Math.Sqrt(m.Xx * m.Xx + m.Xy * m.Xy + m.Xz * m.Xz) + Math.Sqrt(m.Yx * m.Yx + m.Yy * m.Yy + m.Yz * m.Yz)
            + Math.Sqrt(m.Zx * m.Zx + m.Zy * m.Zy + m.Zz * m.Zz)) / 3;

    /// <summary><c>jointNowFrom</c>: posed = meshWorld · bindMatrixInverse · boneWorld; position = its origin,
    /// bindToWorld = posed · boneInverse · bindMatrix.</summary>
    public static JointNow JointNowFrom(Affine meshWorld, Affine bindMatrixInverse, Affine boneWorld, Affine boneInverse, Affine bindMatrix)
    {
        var posed = meshWorld.Times(bindMatrixInverse).Times(boneWorld);
        return new JointNow(posed.Position(), posed.Times(boneInverse).Times(bindMatrix));
    }

    /// <summary><c>capsuleNow</c> — THE ENDPOINT RULE: an endpoint with a bind position goes through its joint's
    /// bind→world matrix, one without is the joint itself; the radius scales with joint a's matrix.</summary>
    public static CapsuleNow CapsuleNowOf(CollisionCapsule c, JointNow a, JointNow b)
        => new(c.APos is { } ap ? a.BindToWorld.Apply(ap) : a.Position, c.BPos is { } bp ? b.BindToWorld.Apply(bp) : b.Position,
               c.R * LinearScale(a.BindToWorld));

    // ---- secondaryMotion.ts (pure parts) -------------------------------------------------------------------

    /// <summary><c>hairChainCapsules</c>: every bound capsule whose region is in <see cref="HairRegions"/>, payload
    /// order, ancestors NOT excluded.</summary>
    public static List<T> HairChainCapsules<T>(IEnumerable<T> bound, Func<T, string> region)
        => bound.Where(e => HairRegions.Contains(region(e))).ToList();

    /// <summary><c>tipBindFactors</c>: per capsule min(1, d0 / r), d0 the tip's distance to the bind capsule's axis;
    /// 1 for a radius that is not &gt; 0.</summary>
    public static double[] TipBindFactors(V3 tipBind, IReadOnlyList<CapsuleNow> capsules)
    {
        var out_ = new double[capsules.Count];
        for (int i = 0; i < capsules.Count; i++)
        {
            var c = capsules[i];
            if (!(c.R > 0)) { out_[i] = 1; continue; }
            double abx = c.B.X - c.A.X, aby = c.B.Y - c.A.Y, abz = c.B.Z - c.A.Z;
            double apx = tipBind.X - c.A.X, apy = tipBind.Y - c.A.Y, apz = tipBind.Z - c.A.Z;
            double len2 = abx * abx + aby * aby + abz * abz;
            double t = len2 > 1e-12 ? Math.Min(1, Math.Max(0, (apx * abx + apy * aby + apz * abz) / len2)) : 0;
            out_[i] = Math.Min(1, Hypot(apx - abx * t, apy - aby * t, apz - abz * t) / c.R);
        }
        return out_;
    }

    /// <summary>
    /// <c>contactAngle</c>: the turn in [0, limit] that takes a tip out of the capsules (<paramref name="depthAt"/> =
    /// its depth after that turn, <paramref name="depth0"/> at 0) — the first outside angle of a 12-step scan refined
    /// by 14 bisections; when no angle gets out, the shallowest one (ternary search around the best sample), null when
    /// that is no shallower than <paramref name="depth0"/>.
    /// </summary>
    public static double? ContactAngle(Func<double, double> depthAt, double depth0, double limit)
    {
        double step = limit / ContactScan;
        double inside = 0, outside = -1, best = 0, bestDepth = depth0;
        for (int k = 1; k <= ContactScan; k++)
        {
            double depth = depthAt(k * step);
            if (depth < CollideSlack) { outside = k * step; break; }
            inside = k * step;
            if (depth < bestDepth) { best = k * step; bestDepth = depth; }
        }
        double angle;
        if (outside > 0)
        {
            for (int i = 0; i < ContactRefine; i++)
            {
                double mid = (inside + outside) / 2;
                if (depthAt(mid) < CollideSlack) outside = mid; else inside = mid;
            }
            angle = outside;
        }
        else
        {
            double lo = Math.Max(0, best - step), hi = Math.Min(limit, best + step);
            for (int i = 0; i < ContactRefine; i++)
            {
                double m1 = lo + (hi - lo) / 3, m2 = hi - (hi - lo) / 3;
                if (depthAt(m1) <= depthAt(m2)) hi = m2; else lo = m1;
            }
            angle = (lo + hi) / 2;
            double depth = depthAt(angle);
            if (!(depth < depth0)) return null;
            if (depth < CollideSlack)
            {
                // An outside window the scan stepped over: its near edge, by bisection from below.
                double below = Math.Max(0, best - step);
                for (int i = 0; i < ContactRefine; i++)
                {
                    double mid = (below + angle) / 2;
                    if (depthAt(mid) < CollideSlack) angle = mid; else below = mid;
                }
            }
        }
        return angle;
    }

    // ---- garmentCollision.ts: THE PUSH, TypeScript edition (own capsules only) ----------------------------------

    /// <summary>JS <c>Math.hypot</c> of three (overflow-safe scaling is irrelevant at body scale; the sum is exact the
    /// same way: √(x² + y² + z²)).</summary>
    private static double Hypot(double x, double y, double z) => Math.Sqrt(x * x + y * y + z * z);

    private static double SegmentDistance(V3 p, V3 a, V3 b)
    {
        double abx = b.X - a.X, aby = b.Y - a.Y, abz = b.Z - a.Z;
        double apx = p.X - a.X, apy = p.Y - a.Y, apz = p.Z - a.Z;
        double len2 = abx * abx + aby * aby + abz * abz;
        double t = len2 > CollideEps ? Math.Min(1, Math.Max(0, (apx * abx + apy * aby + apz * abz) / len2)) : 0;
        return Hypot(apx - abx * t, apy - aby * t, apz - abz * t);
    }

    /// <summary><c>axisOffset</c>: (dx, dy, dz, d) of a point from the capsule's closest axis point.</summary>
    private static (double Dx, double Dy, double Dz, double D) AxisOffset(double x, double y, double z, in CollideCapsule c)
    {
        double ax = c.A.X, ay = c.A.Y, az = c.A.Z;
        double abx = c.B.X - ax, aby = c.B.Y - ay, abz = c.B.Z - az;
        double apx = x - ax, apy = y - ay, apz = z - az;
        double len2 = abx * abx + aby * aby + abz * abz;
        double t = len2 > CollideEps ? Math.Min(1, Math.Max(0, (apx * abx + apy * aby + apz * abz) / len2)) : 0;
        double dx = apx - abx * t, dy = apy - aby * t, dz = apz - abz * t;
        return (dx, dy, dz, Math.Sqrt(dx * dx + dy * dy + dz * dz));
    }

    private static V3 OrdinaryPasses(V3 p, IReadOnlyList<CollideCapsule> capsules, double[] radii, int n)
    {
        double x = p.X, y = p.Y, z = p.Z;
        for (int it = 0; it < CollidePasses; it++)
        {
            bool moved = false;
            for (int i = 0; i < n; i++)
            {
                var (dx, dy, dz, d) = AxisOffset(x, y, z, capsules[i]);
                double r = radii[i];
                if (d < r && d > CollideMinD)
                {
                    double k = r / d - 1;
                    x += dx * k; y += dy * k; z += dz * k;
                    moved = true;
                }
            }
            if (!moved) break;
        }
        return new V3(x, y, z);
    }

    private static V3? SqueezeOut(V3 p, IReadOnlyList<CollideCapsule> capsules, double[] radii, int n)
    {
        var inS = new bool[n];
        int count = 0;
        for (int i = 0; i < n; i++)
            if (AxisOffset(p.X, p.Y, p.Z, capsules[i]).D < radii[i]) { inS[i] = true; count++; }
        if (count == 0) return p;
        double qx = p.X, qy = p.Y, qz = p.Z;
        for (int k = 0; k < SqueezeRounds; k++)
        {
            if (k == 0 && count == 1)
            {
                // the exact radial push out of the one capsule
                for (int i = 0; i < n; i++)
                {
                    if (!inS[i]) continue;
                    var (dx, dy, dz, d) = AxisOffset(p.X, p.Y, p.Z, capsules[i]);
                    if (d > CollideMinD)
                    {
                        double kk = radii[i] / d - 1;
                        qx = p.X + dx * kk; qy = p.Y + dy * kk; qz = p.Z + dz * kk;
                    }
                }
            }
            else
            {
                double nx = 0, ny = 0, nz = 0, rMax = 0;
                for (int i = 0; i < n; i++)
                {
                    if (!inS[i]) continue;
                    var (dx, dy, dz, d) = AxisOffset(p.X, p.Y, p.Z, capsules[i]);
                    if (d > CollideMinD) { nx += dx / d; ny += dy / d; nz += dz / d; }
                    rMax = radii[i] > rMax ? radii[i] : rMax;
                }
                double nl = Math.Sqrt(nx * nx + ny * ny + nz * nz);
                if (nl < SqueezeMinN) return null;
                nx /= nl; ny /= nl; nz /= nl;
                double lo = 0, hi = 2 * rMax;
                for (int s = 0; s <= SqueezeSteps; s++)
                {
                    double tt = s == 0 ? hi : 0.5 * (lo + hi);
                    double ox = p.X + nx * tt, oy = p.Y + ny * tt, oz = p.Z + nz * tt;
                    bool clear = true;
                    for (int i = 0; i < n; i++)
                        if (inS[i] && AxisOffset(ox, oy, oz, capsules[i]).D < radii[i]) clear = false;
                    if (s == 0) { if (!clear) return null; }
                    else if (clear) hi = tt;
                    else lo = tt;
                }
                qx = p.X + nx * hi; qy = p.Y + ny * hi; qz = p.Z + nz * hi;
            }
            int added = 0;
            for (int i = 0; i < n; i++)
                if (!inS[i] && AxisOffset(qx, qy, qz, capsules[i]).D < radii[i]) { inS[i] = true; added++; }
            count += added;
            if (added == 0 || k == SqueezeRounds - 1) break;
        }
        return new V3(qx, qy, qz);
    }

    /// <summary>
    /// <c>pushOutOfCapsules(p, capsules, weight, bindP, {squeeze})</c> without partners: p pushed out of the first
    /// <see cref="CollideMax"/> capsules (the SQUEEZE rule first when <paramref name="squeeze"/>, the ordinary passes
    /// where it does not apply), then <paramref name="weight"/> (clamped 0..1) blends original → pushed. With
    /// <paramref name="bindP"/>, a capsule carrying a bind axis has its radius capped at the bind distance (BIND RULE).
    /// </summary>
    public static V3 PushOutOfCapsules(V3 p, IReadOnlyList<CollideCapsule> capsules, double weight = 1, V3? bindP = null, bool squeeze = false)
    {
        int n = Math.Min(capsules.Count, CollideMax);
        var radii = new double[n];
        for (int i = 0; i < n; i++)
        {
            var c = capsules[i];
            radii[i] = c.BindA is { } ba && c.BindB is { } bb && bindP is { } q ? Math.Min(c.R, SegmentDistance(q, ba, bb)) : c.R;
        }
        var pushed = (squeeze ? SqueezeOut(p, capsules, radii, n) : null) ?? OrdinaryPasses(p, capsules, radii, n);
        double w = Math.Min(1, Math.Max(0, weight));
        return new V3(p.X + (pushed.X - p.X) * w, p.Y + (pushed.Y - p.Y) * w, p.Z + (pushed.Z - p.Z) * w);
    }

    /// <summary>three <c>Matrix4.makeRotationAxis(axis, angle)</c> (axis normalised), element for element.</summary>
    public static Affine RotationAxis(V3 axis, double angle)
    {
        double c = Math.Cos(angle), s = Math.Sin(angle), t = 1 - c;
        double x = axis.X, y = axis.Y, z = axis.Z, tx = t * x, ty = t * y;
        // three sets rows: (tx·x + c, tx·y − s·z, tx·z + s·y), (tx·y + s·z, ty·y + c, ty·z − s·x), (tx·z − s·y, ty·z + s·x, t·z·z + c)
        return new Affine(tx * x + c, tx * y + s * z, tx * z - s * y,
                          tx * y - s * z, ty * y + c, ty * z + s * x,
                          tx * z + s * y, ty * z - s * x, t * z * z + c, 0, 0, 0);
    }

    /// <summary>
    /// The hair tip turn of secondaryMotion.ts <c>keepHairTipOutside</c> on points: the SQUEEZE push says how deep
    /// <paramref name="tip"/> is and which way out; the turn about <paramref name="head"/> in the plane of the lever
    /// and that way out, by <see cref="ContactAngle"/> capped at <paramref name="limit"/>. Null = no turn (outside,
    /// a degenerate lever / way out, or no shallower angle); else the axis and the angle.
    /// </summary>
    public static (V3 Axis, double Angle, double Depth0)? HairTipTurn(V3 head, V3 tip, IReadOnlyList<CollideCapsule> capsules, double limit)
    {
        if (!(limit > 0)) return null;
        var pushed = PushOutOfCapsules(tip, capsules, 1, null, true);
        double depth0 = Hypot(pushed.X - tip.X, pushed.Y - tip.Y, pushed.Z - tip.Z);
        if (depth0 < CollideSlack) return null;
        var lever = tip - head;
        var axis = lever.Cross(pushed - tip);
        if (axis.LengthSq() < 1e-20 || lever.LengthSq() < 1e-12) return null;
        axis = axis.Normalized();
        var angle = ContactAngle(turn =>
        {
            var t = lever.ApplyAxisAngle(axis, turn) + head;
            var q = PushOutOfCapsules(t, capsules, 1, null, true);
            return Hypot(q.X - t.X, q.Y - t.Y, q.Z - t.Z);
        }, depth0, limit);
        return angle is { } a ? (axis, a, depth0) : null;
    }
}
