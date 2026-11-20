using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.Linq;
using System.Text.Json;

namespace AnimaNative.Figures;

// Per-strand hair dynamics, pure: the port of packages/scene-render/src/hairSimMath.ts (strand-hair spec
// docs/superpowers/specs/2026-11-13-strand-hair-design.md § 6.2; the module docstring there is the reference for every
// rule — gravity (Ruling T-U3), the step (spec § 6.2.1), the root's motion (Ruling H-R10)). A line-by-line
// transcription: the TypeScript keeps the simulated rows and most per-row constants in Float32Arrays and computes in
// doubles in between; here those arrays are F32 (float storage, double reads), so every store rounds where the
// browser's does. Matrices are column-major double[16] (three's Matrix4.elements). Math.hypot is V8's
// (StrandMath.Hypot), so the distances agree bit for bit with the browser's. Checked against
// shared/test-vectors/strand_sim.json (scripts/export_strand_vectors.mjs, the fixture of scripts/smoke_hair_sim.mjs).

/// <summary>A float32 array read as doubles (JavaScript's Float32Array): a read widens, a store rounds to nearest.</summary>
public sealed class F32
{
    public readonly float[] A;
    public F32(int n) { A = new float[n]; }
    public F32(float[] a) { A = a; }
    public static F32 From(IReadOnlyList<double> v) { var f = new F32(v.Count); for (int i = 0; i < v.Count; i++) f.A[i] = (float)v[i]; return f; }
    public int Length => A.Length;
    public double this[int i] { get => A[i]; set => A[i] = (float)value; }
    public void Set(F32 src, int count) => Array.Copy(src.A, A, count);
    public F32 Clone() => new((float[])A.Clone());
}

/// <summary>The JavaScript arithmetic the port needs bit for bit.</summary>
public static class StrandMath
{
    /// <summary>V8's &lt;c&gt;Math.hypot&lt;/c&gt; (src/builtins/math.tq MathHypot): abs values over their max, a Kahan sum of
    /// the squares, sqrt × max.</summary>
    public static double Hypot(double a, double b, double c)
    {
        a = Math.Abs(a); b = Math.Abs(b); c = Math.Abs(c);
        if (double.IsNaN(a) || double.IsNaN(b) || double.IsNaN(c))
            return double.IsPositiveInfinity(a) || double.IsPositiveInfinity(b) || double.IsPositiveInfinity(c) ? double.PositiveInfinity : double.NaN;
        double max = Math.Max(a, Math.Max(b, c));
        if (double.IsPositiveInfinity(max)) return max;
        if (max == 0) return 0;
        double sum = 0, comp = 0;
        Kahan(a / max, ref sum, ref comp); Kahan(b / max, ref sum, ref comp); Kahan(c / max, ref sum, ref comp);
        return Math.Sqrt(sum) * max;
    }

    public static double Hypot(double a, double b)
    {
        a = Math.Abs(a); b = Math.Abs(b);
        if (double.IsNaN(a) || double.IsNaN(b)) return double.IsPositiveInfinity(a) || double.IsPositiveInfinity(b) ? double.PositiveInfinity : double.NaN;
        double max = Math.Max(a, b);
        if (double.IsPositiveInfinity(max)) return max;
        if (max == 0) return 0;
        double sum = 0, comp = 0;
        Kahan(a / max, ref sum, ref comp); Kahan(b / max, ref sum, ref comp);
        return Math.Sqrt(sum) * max;
    }

    public static double Hypot(double a, double b, double c, double d)
    {
        a = Math.Abs(a); b = Math.Abs(b); c = Math.Abs(c); d = Math.Abs(d);
        double max = Math.Max(Math.Max(a, b), Math.Max(c, d));
        if (double.IsNaN(max) || double.IsNaN(a + b + c + d)) return double.NaN;
        if (double.IsPositiveInfinity(max)) return max;
        if (max == 0) return 0;
        double sum = 0, comp = 0;
        Kahan(a / max, ref sum, ref comp); Kahan(b / max, ref sum, ref comp); Kahan(c / max, ref sum, ref comp); Kahan(d / max, ref sum, ref comp);
        return Math.Sqrt(sum) * max;
    }

    private static void Kahan(double n, ref double sum, ref double comp)
    {
        double summand = n * n - comp;
        double preliminary = sum + summand;
        comp = (preliminary - sum) - summand;
        sum = preliminary;
    }

    /// <summary>JavaScript's &lt;c&gt;x || 1&lt;/c&gt; for a number: 1 for 0, -0 and NaN.</summary>
    public static double Or1(double x) => x == 0 || double.IsNaN(x) ? 1 : x;

    /// <summary>JavaScript's &lt;c&gt;Number(v)&lt;/c&gt; of a JSON value (undefined → NaN, null → 0, booleans 0/1, strings parsed).</summary>
    public static double Number(JsonElement? v)
    {
        if (v is not { } e) return double.NaN;
        switch (e.ValueKind)
        {
            case JsonValueKind.Number: return e.GetDouble();
            case JsonValueKind.True: return 1;
            case JsonValueKind.False: case JsonValueKind.Null: return 0;
            case JsonValueKind.String:
            {
                var s = e.GetString()!.Trim();
                if (s.Length == 0) return 0;
                return double.TryParse(s, NumberStyles.Float, CultureInfo.InvariantCulture, out var d) ? d : double.NaN;
            }
            default: return double.NaN;
        }
    }

    /// <summary>JavaScript's &lt;c&gt;!!v&lt;/c&gt; of a JSON value.</summary>
    public static bool Truthy(JsonElement? v)
    {
        if (v is not { } e) return false;
        return e.ValueKind switch
        {
            JsonValueKind.True => true,
            JsonValueKind.Number => e.GetDouble() is var d && d != 0 && !double.IsNaN(d),
            JsonValueKind.String => e.GetString()!.Length > 0,
            JsonValueKind.Object or JsonValueKind.Array => true,
            _ => false,
        };
    }

    /// <summary>&lt;c&gt;m · (p, 1)&lt;/c&gt; divided by w (collision.ts &lt;c&gt;transformPoint&lt;/c&gt;).</summary>
    public static double[] TransformPoint(double[] m, double[] p)
    {
        double x = p[0], y = p[1], z = p[2];
        double w = Or1(m[3] * x + m[7] * y + m[11] * z + m[15]);
        return new[] { (m[0] * x + m[4] * y + m[8] * z + m[12]) / w, (m[1] * x + m[5] * y + m[9] * z + m[13]) / w,
            (m[2] * x + m[6] * y + m[10] * z + m[14]) / w };
    }

    /// <summary>collision.ts &lt;c&gt;linearScale&lt;/c&gt;: the mean length of the three basis columns.</summary>
    public static double LinearScale(double[] m)
    {
        double sum = 0;
        for (int col = 0; col < 3; col++) sum += Hypot(m[col * 4], m[col * 4 + 1], m[col * 4 + 2]);
        return sum / 3;
    }

    /// <summary>&lt;c&gt;a · b&lt;/c&gt;, column-major 4×4 (hairSimMath.ts &lt;c&gt;mul&lt;/c&gt;).</summary>
    public static double[] Mul(double[] a, double[] b)
    {
        var out_ = new double[16];
        for (int c = 0; c < 4; c++)
            for (int r = 0; r < 4; r++)
                out_[4 * c + r] = a[r] * b[4 * c] + a[4 + r] * b[4 * c + 1] + a[8 + r] * b[4 * c + 2] + a[12 + r] * b[4 * c + 3];
        return out_;
    }
}

/// <summary>A record and a hair primitive that do not belong together — the hair stays on its skin, never scrambled.</summary>
public sealed class StrandMismatch : Exception
{
    public StrandMismatch(string message) : base(message) { }
}

/// <summary>The record's &lt;c&gt;params&lt;/c&gt;, camelCase (hairSimMath.ts &lt;c&gt;StrandParams&lt;/c&gt;).</summary>
public sealed record StrandParams(double Damping, double Stiffness, double Bend, double Iterations, double RootDeg, double RootFrac,
    bool FlySoft, double FlyArc, bool Tether, double TetherR0, double TetherR1, double TetherHead, double HeadClr, bool FaceBox);

/// <summary>The record's head SDF payload (int8 mm, x fastest, base64).</summary>
public sealed record StrandSdfPayload(int[] Dims, double[] Lo, double Vox, string Order, string Unit, string Data);

/// <summary>
/// The strand record (spec § 6.2.3, docs/schnittstellen-3d.md "Hair strands"; hairSimMath.ts &lt;c&gt;HairStrandRecord&lt;/c&gt;),
/// served by &lt;c&gt;GET /characters/{name}/model/hair-strands&lt;/c&gt;.
/// </summary>
public sealed class HairStrandRecord
{
    public double Version { get; init; } = double.NaN;
    public string ItemId { get; init; } = "";
    public string Fsig { get; init; } = "";
    public string Mode { get; init; } = "";
    public string FitSha256 { get; init; } = "";
    public string Frame { get; init; } = "";
    public string HeadBone { get; init; } = "";
    public int Rows { get; init; }
    public int Cards { get; init; }
    public double[] Rest { get; init; } = Array.Empty<double>();
    public double[] Pins { get; init; } = Array.Empty<double>();
    public double[] FreeArc { get; init; } = Array.Empty<double>();
    public double[] FreeFrac { get; init; } = Array.Empty<double>();
    public string[] FollowBones { get; init; } = Array.Empty<string>();
    public double[] FollowW { get; init; } = Array.Empty<double>();
    public double EarY { get; init; }
    public double[] FaceBox { get; init; } = Array.Empty<double>();
    public double[] EyeBox { get; init; } = Array.Empty<double>();
    public StrandSdfPayload Sdf { get; init; } = new(new[] { 0, 0, 0 }, new double[3], 0, "", "", "");
    /// <summary>&lt;c&gt;capsules.capsules&lt;/c&gt;: the fit body's capsules (the &lt;c&gt;collision&lt;/c&gt; payload's shape).</summary>
    public IReadOnlyList<CollisionCapsule> Capsules { get; init; } = Array.Empty<CollisionCapsule>();
    public StrandParams Params { get; init; } = StrandSim.ParamsOf(default);
    public string VertexCard { get; init; } = "_STRAND_CARD";
    public string VertexU { get; init; } = "_STRAND_U";

    /// <summary>A record object; throws &lt;see cref="StrandMismatch"/&gt; when it is not one.</summary>
    public static HairStrandRecord Parse(JsonElement r)
    {
        if (r.ValueKind != JsonValueKind.Object) throw new StrandMismatch("the strand record is no object");
        JsonElement? Get(JsonElement o, string k) => o.ValueKind == JsonValueKind.Object && o.TryGetProperty(k, out var v) ? v : null;
        double[] Nums(JsonElement? e) => e is { ValueKind: JsonValueKind.Array } a ? a.EnumerateArray().Select(x => StrandMath.Number(x)).ToArray() : Array.Empty<double>();
        string Str(JsonElement? e) => e is { ValueKind: JsonValueKind.String } s ? s.GetString()! : "";
        var follow = Get(r, "follow");
        var sdf = Get(r, "sdf");
        var caps = Get(r, "capsules");
        var vattr = Get(r, "vertex_attributes");
        int Int(JsonElement? e) { double d = StrandMath.Number(e); return double.IsFinite(d) ? (int)d : -1; }
        var dims = Nums(sdf is { } s0 ? Get(s0, "dims") : null);
        var lo = Nums(sdf is { } s1 ? Get(s1, "lo") : null);
        return new HairStrandRecord
        {
            Version = StrandMath.Number(Get(r, "version")),
            ItemId = Str(Get(r, "item_id")), Fsig = Str(Get(r, "fsig")), Mode = Str(Get(r, "mode")),
            FitSha256 = Str(Get(r, "fit_sha256")), Frame = Str(Get(r, "frame")), HeadBone = Str(Get(r, "head_bone")),
            Rows = Int(Get(r, "rows")), Cards = Int(Get(r, "cards")),
            Rest = Nums(Get(r, "rest")), Pins = Nums(Get(r, "pins")), FreeArc = Nums(Get(r, "free_arc")), FreeFrac = Nums(Get(r, "free_frac")),
            FollowBones = follow is { } f && Get(f, "bones") is { ValueKind: JsonValueKind.Array } fb ? fb.EnumerateArray().Select(x => Str(x)).ToArray() : Array.Empty<string>(),
            FollowW = follow is { } f2 ? Nums(Get(f2, "w")) : Array.Empty<double>(),
            EarY = StrandMath.Number(Get(r, "ear_y")),
            FaceBox = Nums(Get(r, "face_box")), EyeBox = Nums(Get(r, "eye_box")),
            Sdf = new StrandSdfPayload(dims.Length == 3 ? dims.Select(d => (int)d).ToArray() : new[] { 0, 0, 0 },
                lo.Length == 3 ? lo : new double[3], StrandMath.Number(sdf is { } s2 ? Get(s2, "vox") : null),
                Str(sdf is { } s3 ? Get(s3, "order") : null), Str(sdf is { } s4 ? Get(s4, "unit") : null), Str(sdf is { } s5 ? Get(s5, "data") : null)),
            Capsules = caps is { } c ? CollisionPayload.Parse(c)?.Capsules ?? Array.Empty<CollisionCapsule>() : Array.Empty<CollisionCapsule>(),
            Params = StrandSim.ParamsOf(Get(r, "params")),
            VertexCard = vattr is { } va && Get(va, "card") is { ValueKind: JsonValueKind.String } vc ? vc.GetString()! : "_STRAND_CARD",
            VertexU = vattr is { } vb && Get(vb, "u") is { ValueKind: JsonValueKind.String } vu ? vu.GetString()! : "_STRAND_U",
        };
    }
}

/// <summary>The record's head SDF, decoded: int8 millimetres, x fastest.</summary>
public sealed record StrandSdf(sbyte[] Q, int[] Dims, double[] Lo, double Vox);

/// <summary>The rest frames of every card and the per-vertex offsets (&lt;c&gt;bindStrands&lt;/c&gt;).</summary>
public sealed class StrandBinding
{
    public int S;
    public F32 C0 = null!;
    public double[] N00 = null!;
    public int[] Vk = null!;
    public byte[] Va = null!;
    public double[] Vt = null!;
    public double[] Off = null!;
    public double[] Noff = null!;
    public int[] CStart = null!;
    public int[] CVerts = null!;
    public int[] Rigid = null!;
    public float[] Pos0 = null!;
    public float[] Nrm0 = null!;
}

/// <summary>The bind-space ends of a capsule (the bind rule's reference). Its identity keys the per-row factor
/// tables (&lt;c&gt;StrandSim.Factors&lt;/c&gt;): keep the same object from frame to frame.</summary>
public sealed class StrandBind
{
    public readonly double[] A, B;
    public StrandBind(double[] a, double[] b) { A = a; B = b; }
}

/// <summary>A capsule of a step (hairSimMath.ts / garmentCollision.ts &lt;c&gt;CollideCapsule&lt;/c&gt;): world ends now, radius,
/// optional bind ends.</summary>
public sealed class StrandCapsule
{
    public double[] A, B;
    public double R;
    public StrandBind? Bind;
    public StrandCapsule(double[] a, double[] b, double r, StrandBind? bind = null) { A = a; B = b; R = r; Bind = bind; }
}

/// <summary>One frame of the figure (hairSimMath.ts &lt;c&gt;StrandFrame&lt;/c&gt;).</summary>
public sealed class StrandFrame
{
    public F32 Targets = null!;
    public double[] Head = null!;
    public IReadOnlyList<StrandCapsule> Capsules = Array.Empty<StrandCapsule>();
    public IReadOnlyList<double[]>? Follow;
}

/// <summary>The pure strand simulation (hairSimMath.ts &lt;c&gt;StrandSim&lt;/c&gt; and its free functions).</summary>
public sealed class StrandSim
{
    /// <summary>Simulated rows per card, root first (&lt;c&gt;hair_strands.ROWS&lt;/c&gt;).</summary>
    public const int Rows = 17;
    private const int R = Rows;
    private const double G = 9.81;
    private const double MinArc = 0.03;
    private const double FlyClear = 0.03;
    private const double Clearance = 0.003;
    private const double SdfOutside = 0.127;
    private const double HangProjectM = 0.002;
    private const double HangSampleM = 0.02;
    private const int HangSamples = 4;
    private const double HangClearTolM = 0.0005;
    private const double GravityFreeDeg = 20;
    private const double GravityFullDeg = 45;
    private static readonly double CosFree = Math.Cos((GravityFreeDeg * Math.PI) / 180);
    private static readonly double CosFull = Math.Cos((GravityFullDeg * Math.PI) / 180);
    /// <summary>The length clamp (Ruling H-R10).</summary>
    public const double StretchMax = 1.05;
    /// <summary>The record version this simulation reads (&lt;c&gt;STRAND_RECORD_VERSION&lt;/c&gt;).</summary>
    public const int RecordVersion = 2;
    private const int FactorTablesKept = 2;

    private static double SmoothShare(double c)
    {
        if (c >= CosFree) return 0;
        if (c <= CosFull) return 1;
        double x = (CosFree - c) / (CosFree - CosFull);
        return x * x * (3 - 2 * x);
    }

    /// <summary>&lt;c&gt;strandParams&lt;/c&gt;: the record's snake_case params (JavaScript &lt;c&gt;Number&lt;/c&gt; / &lt;c&gt;!!&lt;/c&gt; of each).</summary>
    public static StrandParams ParamsOf(JsonElement? p)
    {
        JsonElement? Get(string k) => p is { ValueKind: JsonValueKind.Object } o && o.TryGetProperty(k, out var v) ? v : null;
        double Num(string k) => StrandMath.Number(Get(k));
        return new StrandParams(Num("damping"), Num("stiffness"), Num("bend"), Num("iterations"), Num("root_deg"), Num("root_frac"),
            StrandMath.Truthy(Get("fly_soft")), Num("fly_arc"), StrandMath.Truthy(Get("tether")), Num("tether_r0"), Num("tether_r1"),
            Num("tether_head"), Num("head_clr"), StrandMath.Truthy(Get("face_box")));
    }

    // --- small math ------------------------------------------------------------------------------------------------

    /// <summary>The inverse of an affine column-major 4×4 (zeros for a singular one).</summary>
    public static double[] InvertAffine(double[] m)
    {
        double a = m[0], b = m[4], c = m[8], d = m[1], e = m[5], f = m[9], g = m[2], h = m[6], i = m[10];
        double A = e * i - f * h, B = f * g - d * i, C = d * h - e * g;
        double det = a * A + b * B + c * C;
        if (det == 0 || double.IsNaN(det)) return new double[16];
        double s = 1 / det;
        var r = new[] { A * s, B * s, C * s, 0, (c * h - b * i) * s, (a * i - c * g) * s, (b * g - a * h) * s, 0,
            (b * f - c * e) * s, (c * d - a * f) * s, (a * e - b * d) * s, 0, 0, 0, 0, 1.0 };
        double tx = m[12], ty = m[13], tz = m[14];
        r[12] = -(r[0] * tx + r[4] * ty + r[8] * tz);
        r[13] = -(r[1] * tx + r[5] * ty + r[9] * tz);
        r[14] = -(r[2] * tx + r[6] * ty + r[10] * tz);
        return r;
    }

    private static double[] QuatOf(double[] m)
    {
        double m11 = m[0], m12 = m[4], m13 = m[8], m21 = m[1], m22 = m[5], m23 = m[9], m31 = m[2], m32 = m[6], m33 = m[10];
        double tr = m11 + m22 + m33;
        if (tr > 0)
        {
            double s = 0.5 / Math.Sqrt(tr + 1);
            return new[] { (m32 - m23) * s, (m13 - m31) * s, (m21 - m12) * s, 0.25 / s };
        }
        if (m11 > m22 && m11 > m33)
        {
            double s = 2 * Math.Sqrt(1 + m11 - m22 - m33);
            return new[] { 0.25 * s, (m12 + m21) / s, (m13 + m31) / s, (m32 - m23) / s };
        }
        if (m22 > m33)
        {
            double s = 2 * Math.Sqrt(1 + m22 - m11 - m33);
            return new[] { (m12 + m21) / s, 0.25 * s, (m23 + m32) / s, (m13 - m31) / s };
        }
        {
            double s = 2 * Math.Sqrt(1 + m33 - m11 - m22);
            return new[] { (m13 + m31) / s, (m23 + m32) / s, 0.25 * s, (m21 - m12) / s };
        }
    }

    /// <summary>Ruling H-R11 &lt;c&gt;lerpFrame&lt;/c&gt;: the frame between two shear-free affine frames — rotation slerped, each
    /// column's scale and the translation linear in &lt;paramref name="s"/&gt;; s ≤ 0 gives a, s ≥ 1 gives b exactly.</summary>
    public static double[] LerpFrame(double[] a, double[] b, double s, double[] out_)
    {
        if (s <= 0 || s >= 1)
        {
            var src = s <= 0 ? a : b;
            for (int i = 0; i < 16; i++) out_[i] = src[i];
            return out_;
        }
        var sa = new double[3]; var sb = new double[3]; var ra = new double[11]; var rb = new double[11];
        for (int c = 0; c < 3; c++)
        {
            sa[c] = StrandMath.Or1(StrandMath.Hypot(a[4 * c], a[4 * c + 1], a[4 * c + 2]));
            sb[c] = StrandMath.Or1(StrandMath.Hypot(b[4 * c], b[4 * c + 1], b[4 * c + 2]));
            for (int r = 0; r < 3; r++) { ra[4 * c + r] = a[4 * c + r] / sa[c]; rb[4 * c + r] = b[4 * c + r] / sb[c]; }
        }
        var qa = QuatOf(ra); var qb = QuatOf(rb);
        double dot = qa[0] * qb[0] + qa[1] * qb[1] + qa[2] * qb[2] + qa[3] * qb[3];
        if (dot < 0) { dot = -dot; for (int k = 0; k < 4; k++) qb[k] = -qb[k]; }
        double wa = 1 - s, wb = s;
        if (dot < 0.9995)
        {
            double th = Math.Acos(Math.Min(1, dot)), sn = Math.Sin(th);
            wa = Math.Sin((1 - s) * th) / sn;
            wb = Math.Sin(s * th) / sn;
        }
        double x = wa * qa[0] + wb * qb[0], y = wa * qa[1] + wb * qb[1], z = wa * qa[2] + wb * qb[2], w = wa * qa[3] + wb * qb[3];
        double l = StrandMath.Or1(StrandMath.Hypot(x, y, z, w));
        x /= l; y /= l; z /= l; w /= l;
        var rot = new[] { 1 - 2 * (y * y + z * z), 2 * (x * y + w * z), 2 * (x * z - w * y),
            2 * (x * y - w * z), 1 - 2 * (x * x + z * z), 2 * (y * z + w * x),
            2 * (x * z + w * y), 2 * (y * z - w * x), 1 - 2 * (x * x + y * y) };
        for (int c = 0; c < 3; c++)
        {
            double sc = sa[c] + (sb[c] - sa[c]) * s;
            out_[4 * c] = rot[3 * c] * sc; out_[4 * c + 1] = rot[3 * c + 1] * sc; out_[4 * c + 2] = rot[3 * c + 2] * sc;
            out_[4 * c + 3] = 0;
        }
        out_[12] = a[12] + (b[12] - a[12]) * s;
        out_[13] = a[13] + (b[13] - a[13]) * s;
        out_[14] = a[14] + (b[14] - a[14]) * s;
        out_[15] = 1;
        return out_;
    }

    /// <summary>Parallel-transport frames along one centreline &lt;c&gt;C[base .. base + 17·3)&lt;/c&gt; from the root normal.</summary>
    private static void FrameAt(double[] C, int @base, double[] out_, double n0x, double n0y, double n0z)
    {
        double nx = n0x, ny = n0y, nz = n0z;
        for (int i = 0; i < R; i++)
        {
            int a = @base + 3 * Math.Min(i, R - 2), b = a + 3;
            double tx = C[b] - C[a], ty = C[b + 1] - C[a + 1], tz = C[b + 2] - C[a + 2];
            double l = StrandMath.Hypot(tx, ty, tz);
            if (l == 0 || double.IsNaN(l)) l = 1e-9;
            tx /= l; ty /= l; tz /= l;
            double d = nx * tx + ny * ty + nz * tz;
            nx -= d * tx; ny -= d * ty; nz -= d * tz;
            l = StrandMath.Hypot(nx, ny, nz);
            if (l < 1e-9)
            {
                if (Math.Abs(tx) < 0.9) { nx = 0; ny = -tz; nz = ty; } else { nx = tz; ny = 0; nz = -tx; }
                l = StrandMath.Hypot(nx, ny, nz);
            }
            nx /= l; ny /= l; nz /= l;
            int o = 9 * i;
            out_[o] = tx; out_[o + 1] = ty; out_[o + 2] = tz;
            out_[o + 3] = nx; out_[o + 4] = ny; out_[o + 5] = nz;
            out_[o + 6] = ty * nz - tz * ny; out_[o + 7] = tz * nx - tx * nz; out_[o + 8] = tx * ny - ty * nx;
        }
    }

    /// <summary>A box &lt;c&gt;[x0, x1, y0, y1, z0]&lt;/c&gt; open to the front: (depth, exit) of a point inside (exit 0 = −x,
    /// 1 = +x, 2 = +y, the nearest), (0, −1) outside.</summary>
    public static (double Depth, int Exit) BoxDepth(IReadOnlyList<double> b, double x, double y, double z)
    {
        if (x <= b[0] || x >= b[1] || y <= b[2] || y >= b[3] || z <= b[4]) return (0, -1);
        double d = x - b[0]; int e = 0;
        if (b[1] - x < d) { d = b[1] - x; e = 1; }
        if (b[3] - y < d) { d = b[3] - y; e = 2; }
        return (d, e);
    }

    private static bool InBox(IReadOnlyList<double> b, double x, double y, double z)
        => x > b[0] && x < b[1] && y > b[2] && y < b[3] && z > b[4];

    private static double SegDist(double px, double py, double pz, double[] a, double[] b)
    {
        double abx = b[0] - a[0], aby = b[1] - a[1], abz = b[2] - a[2];
        double apx = px - a[0], apy = py - a[1], apz = pz - a[2];
        double l2 = abx * abx + aby * aby + abz * abz;
        double t = l2 > 1e-12 ? Math.Min(1, Math.Max(0, (apx * abx + apy * aby + apz * abz) / l2)) : 0;
        return StrandMath.Hypot(apx - abx * t, apy - aby * t, apz - abz * t);
    }

    // --- the head SDF ----------------------------------------------------------------------------------------------

    /// <summary>Decode the record's &lt;c&gt;sdf&lt;/c&gt; (base64 int8 mm, x fastest).</summary>
    public static StrandSdf DecodeSdf(StrandSdfPayload sdf)
    {
        byte[] bin;
        try { bin = Convert.FromBase64String(sdf.Data); }
        catch (FormatException) { throw new StrandMismatch("the SDF is no base64"); }
        var q = new sbyte[bin.Length];
        for (int i = 0; i < bin.Length; i++) q[i] = unchecked((sbyte)bin[i]);
        int nx = sdf.Dims[0], ny = sdf.Dims[1], nz = sdf.Dims[2];
        if (q.Length != (long)nx * ny * nz) throw new StrandMismatch($"SDF holds {q.Length} values for {nx}×{ny}×{nz}");
        return new StrandSdf(q, new[] { nx, ny, nz }, new[] { sdf.Lo[0], sdf.Lo[1], sdf.Lo[2] }, sdf.Vox);
    }

    /// <summary>Trilinear SDF in metres at a head-bind-space point (+0.127 outside the grid); writes the (unnormalised)
    /// gradient into &lt;paramref name="g"/&gt; when given.</summary>
    public static double SdfAt(StrandSdf s, double x, double y, double z, F32? g = null)
    {
        int nx = s.Dims[0], ny = s.Dims[1], nz = s.Dims[2]; double v = s.Vox;
        double fx = (x - s.Lo[0]) / v, fy = (y - s.Lo[1]) / v, fz = (z - s.Lo[2]) / v;
        if (fx < 0 || fy < 0 || fz < 0 || fx > nx - 1.001 || fy > ny - 1.001 || fz > nz - 1.001 || double.IsNaN(fx + fy + fz))
        {
            if (double.IsNaN(fx + fy + fz))
            {
                // JavaScript: every comparison with NaN is false, so a NaN point falls through to the lookup with index
                // 0 (NaN | 0) and NaN fractions — a NaN distance. Kept, so a broken row stays visibly broken.
                if (g is not null) { g[0] = double.NaN; g[1] = double.NaN; g[2] = double.NaN; }
                return double.NaN;
            }
            if (g is not null) { g[0] = 0; g[1] = 0; g[2] = 0; }
            return SdfOutside;
        }
        int ix = (int)fx, iy = (int)fy, iz = (int)fz;
        double ux = fx - ix, uy = fy - iy, uz = fz - iz;
        var q = s.Q; int sy = nx, sz = nx * ny, o = ix + nx * (iy + ny * iz);
        double c000 = q[o], c100 = q[o + 1], c010 = q[o + sy], c110 = q[o + 1 + sy];
        double c001 = q[o + sz], c101 = q[o + 1 + sz], c011 = q[o + sy + sz], c111 = q[o + 1 + sy + sz];
        double c00 = c000 + (c100 - c000) * ux, c10 = c010 + (c110 - c010) * ux;
        double c01 = c001 + (c101 - c001) * ux, c11 = c011 + (c111 - c011) * ux;
        double c0 = c00 + (c10 - c00) * uy, c1 = c01 + (c11 - c01) * uy;
        if (g is not null)
        {
            g[0] = (c100 - c000) * (1 - uy) * (1 - uz) + (c110 - c010) * uy * (1 - uz) + (c101 - c001) * (1 - uy) * uz
                + (c111 - c011) * uy * uz;
            g[1] = (c10 - c00) * (1 - uz) + (c11 - c01) * uz;
            g[2] = c1 - c0;
        }
        return (c0 + (c1 - c0) * uz) * 0.001;
    }

    // --- the rest binding ------------------------------------------------------------------------------------------

    /// <summary>&lt;c&gt;bindStrands&lt;/c&gt;: rest frames + per-vertex offsets; throws &lt;see cref="StrandMismatch"/&gt; when the
    /// attribute lengths differ, a card number exceeds &lt;c&gt;record.cards&lt;/c&gt;, or the record's arrays do not fit.</summary>
    public static StrandBinding Bind(HairStrandRecord record, float[] pos0, float[] nrm0, ushort[] card, float[] u)
    {
        int nv = card.Length, S = record.Cards;
        if (pos0.Length != 3 * nv || nrm0.Length != 3 * nv || u.Length != nv)
            throw new StrandMismatch($"attribute lengths differ: {pos0.Length / 3.0} positions, {nrm0.Length / 3.0} normals, {nv} cards, {u.Length} u");
        if (!(S > 0) || record.Rows != R || record.Rest.Length != S * R * 3 || record.Pins.Length != S
            || record.FreeArc.Length != S * R || record.FreeFrac.Length != S * R
            || record.FollowW.Length != S * R * record.FollowBones.Length)
            throw new StrandMismatch($"the record's arrays do not fit {S} cards of {R} rows");
        int maxCard = 0;
        for (int v = 0; v < nv; v++) if (card[v] > maxCard) maxCard = card[v];
        if (maxCard - 1 >= S) throw new StrandMismatch($"_STRAND_CARD {maxCard} names card {maxCard - 1}; the record has {S} cards");
        var C0 = F32.From(record.Rest);
        var vk = new int[nv]; var va = new byte[nv]; var vt = new double[nv];
        for (int v = 0; v < nv; v++)
        {
            int k = card[v] - 1;
            vk[v] = k;
            if (k < 0) continue;
            double uu = Math.Min(R - 1, Math.Max(0, (double)u[v]));
            int ia = (int)Math.Min(R - 2, Math.Floor(uu));
            va[v] = (byte)ia;
            double t = Math.Min(1, Math.Max(0, uu - ia));
            vt[v] = t < 1e-6 ? 0 : t;
        }
        var cStart = new int[S + 1]; var cVerts = new int[nv];
        for (int v = 0; v < nv; v++) if (vk[v] >= 0) cStart[vk[v] + 1]++;
        for (int k = 0; k < S; k++) cStart[k + 1] += cStart[k];
        var fill = cStart.Take(S).ToArray();
        var rigid = new List<int>();
        for (int v = 0; v < nv; v++)
        {
            if (vk[v] >= 0) cVerts[fill[vk[v]]++] = v;
            else rigid.Add(v);
        }
        var C0d = Array.ConvertAll(C0.A, x => (double)x);
        var N00 = new double[S * 3]; var frames = new double[R * 9];
        var off = new double[nv * 6]; var noff = new double[nv * 6];
        for (int k = 0; k < S; k++)
        {
            int b = k * R * 3;
            double tx = C0d[b + 3] - C0d[b], tz = C0d[b + 5] - C0d[b + 2];
            double nx = -tz, nz = tx;
            double l = StrandMath.Hypot(nx, nz);
            if (l < 1e-6) { nx = 1; nz = 0; l = 1; }
            N00[3 * k] = nx / l; N00[3 * k + 1] = 0; N00[3 * k + 2] = nz / l;
            FrameAt(C0d, b, frames, N00[3 * k], N00[3 * k + 1], N00[3 * k + 2]);
            for (int q = cStart[k]; q < cStart[k + 1]; q++)
            {
                int v = cVerts[q];
                for (int h = 0; h < 2; h++)
                {
                    if (h == 1 && vt[v] == 0) break;
                    int i = va[v] + h, c = b + 3 * i, f = 9 * i, o = 6 * v + 3 * h;
                    double dx = pos0[3 * v] - C0d[c], dy = pos0[3 * v + 1] - C0d[c + 1], dz = pos0[3 * v + 2] - C0d[c + 2];
                    for (int a = 0; a < 3; a++)
                    {
                        off[o + a] = dx * frames[f + 3 * a] + dy * frames[f + 3 * a + 1] + dz * frames[f + 3 * a + 2];
                        noff[o + a] = (double)nrm0[3 * v] * frames[f + 3 * a] + (double)nrm0[3 * v + 1] * frames[f + 3 * a + 1]
                            + (double)nrm0[3 * v + 2] * frames[f + 3 * a + 2];
                    }
                }
            }
        }
        return new StrandBinding
        {
            S = S, C0 = C0, N00 = N00, Vk = vk, Va = va, Vt = vt, Off = off, Noff = noff, CStart = cStart, CVerts = cVerts,
            Rigid = rigid.ToArray(), Pos0 = (float[])pos0.Clone(), Nrm0 = (float[])nrm0.Clone(),
        };
    }

    // --- the animated targets --------------------------------------------------------------------------------------

    /// <summary>&lt;c&gt;strandTargets&lt;/c&gt;: every row's target &lt;c&gt;Σ_b w_b · follow[b] · p_bind&lt;/c&gt; into
    /// &lt;paramref name="out_"/&gt; (world).</summary>
    public static void Targets(HairStrandRecord record, IReadOnlyList<double[]> follow, F32 out_)
    {
        var rest = record.Rest; var w = record.FollowW;
        int nb = record.FollowBones.Length, n = rest.Length / 3;
        if (follow.Count != nb) throw new StrandMismatch($"{follow.Count} follow matrices for {nb} bones");
        for (int p = 0; p < n; p++)
        {
            double x = rest[3 * p], y = rest[3 * p + 1], z = rest[3 * p + 2];
            double tx = 0, ty = 0, tz = 0;
            for (int b = 0; b < nb; b++)
            {
                double wb = w[p * nb + b];
                if (wb == 0 || double.IsNaN(wb)) continue;
                var m = follow[b];
                tx += wb * (m[0] * x + m[4] * y + m[8] * z + m[12]);
                ty += wb * (m[1] * x + m[5] * y + m[9] * z + m[13]);
                tz += wb * (m[2] * x + m[6] * y + m[10] * z + m[14]);
            }
            out_[3 * p] = tx; out_[3 * p + 1] = ty; out_[3 * p + 2] = tz;
        }
    }

    // --- the angle limit -------------------------------------------------------------------------------------------

    private static bool LimitInto(double px, double py, double pz, double cx, double cy, double cz,
        double rx, double ry, double rz, double cosLim, out double ox, out double oy, out double oz)
    {
        ox = oy = oz = 0;
        double rl = StrandMath.Hypot(rx, ry, rz);
        if (rl == 0 || double.IsNaN(rl)) rl = 1e-9;
        rx /= rl; ry /= rl; rz /= rl;
        double dx = cx - px, dy = cy - py, dz = cz - pz;
        double L = StrandMath.Hypot(dx, dy, dz);
        if (L < 1e-9) return false;
        dx /= L; dy /= L; dz /= L;
        double cs = dx * rx + dy * ry + dz * rz;
        if (cs >= cosLim) return false;
        double qx = dx - cs * rx, qy = dy - cs * ry, qz = dz - cs * rz;
        double ql = StrandMath.Hypot(qx, qy, qz);
        if (ql < 1e-9) { qx = 0; qy = 0; qz = 0; } else { qx /= ql; qy /= ql; qz /= ql; }
        double sl = Math.Sqrt(Math.Max(0, 1 - cosLim * cosLim));
        ox = px + L * (rx * cosLim + qx * sl);
        oy = py + L * (ry * cosLim + qy * sl);
        oz = pz + L * (rz * cosLim + qz * sl);
        return true;
    }

    /// <summary>&lt;c&gt;limitSegmentAngle&lt;/c&gt;: &lt;paramref name="cur"/&gt; turned about &lt;paramref name="prev"/&gt; towards
    /// &lt;paramref name="restDir"/&gt; until the angle is at most acos(cosLim), keeping the length.</summary>
    public static double[] LimitSegmentAngle(double[] prev, double[] cur, double[] restDir, double cosLim)
        => LimitInto(prev[0], prev[1], prev[2], cur[0], cur[1], cur[2], restDir[0], restDir[1], restDir[2], cosLim, out var x, out var y, out var z)
            ? new[] { x, y, z } : new[] { cur[0], cur[1], cur[2] };

    /// <summary>&lt;c&gt;strandCapsules&lt;/c&gt;: the record's capsules the hair collides with (HAIR_REGIONS, at most COLLIDE_MAX).</summary>
    public static List<CollisionCapsule> RecordCapsules(HairStrandRecord record)
        => record.Capsules.Where(c => Collision.HairRegions.Contains(c.Region)).Take(Collision.CollideMax).ToList();

    /// <summary>garmentCollision.ts &lt;c&gt;capsuleInFrame&lt;/c&gt;: ends through m, radius × m's scale.</summary>
    public static StrandCapsule CapsuleInFrame(double[] a, double[] b, double r, double[] m)
        => new(StrandMath.TransformPoint(m, a), StrandMath.TransformPoint(m, b), r * StrandMath.LinearScale(m));

    // --- the simulation --------------------------------------------------------------------------------------------

    public readonly StrandBinding Binding;
    /// <summary>Rows (cards · 17).</summary>
    public readonly int N;
    public readonly F32 X, Xp;
    public readonly byte[] Pin;
    public readonly F32 F;
    public readonly StrandSdf Sdf;
    public readonly F32 Sdf0;
    public readonly double[] FaceBox;
    private readonly F32 _k, _arcFree, _clr, _onHead, _boxD0, _L1, _L2, _cosLim, _kb2, _kFly;
    private readonly byte[] _fly;
    private string _limKey = "";
    private double _flyKey = double.NaN;
    private readonly F32 _g = new(3);
    private F32 _capFactors = new(0);
    private readonly List<(StrandBind?[] Key, F32 Fac)> _capTables = new();
    private readonly double[] _frames = new double[R * 9];
    private readonly F32 _Tp;
    private bool _tpOk;
    private readonly double[] _Cl;
    /// <summary>Ruling T-U3: where gravity holds each row this step (world).</summary>
    public readonly F32 Hang;
    private readonly F32 _fw;
    private readonly int _nb;
    private readonly double[] _downs;
    /// <summary>Per row its rest clearance above the ear line (0 elsewhere; the head tether's run).</summary>
    public F32 OnHead => _onHead;

    public StrandSim(StrandBinding binding, HairStrandRecord record)
    {
        int S = binding.S, n = S * R;
        if (record.Cards != S) throw new StrandMismatch($"binding of {S} cards for a record of {record.Cards}");
        Binding = binding;
        N = n;
        X = new F32(3 * n); Xp = new F32(3 * n); _Tp = new F32(3 * n);
        Pin = new byte[n]; F = F32.From(record.FreeFrac);
        _arcFree = F32.From(record.FreeArc);
        _k = new F32(n); _clr = new F32(n); _fly = new byte[n];
        _onHead = new F32(n); _boxD0 = new F32(n); Sdf0 = new F32(n);
        _L1 = new F32(n); _L2 = new F32(n);
        _cosLim = new F32(n); _kb2 = new F32(n); _kFly = new F32(n);
        _Cl = new double[3 * n];
        Hang = new F32(3 * n);
        _nb = Math.Max(1, record.FollowBones.Length);
        _fw = F32.From(record.FollowW);
        _downs = new double[3 * _nb];
        Sdf = DecodeSdf(record.Sdf);
        FaceBox = record.FaceBox.Take(5).ToArray();
        var C0 = binding.C0; double ear = record.EarY;
        for (int c = 0; c < S; c++)
        {
            double pins = Math.Max(1, record.Pins[c]);
            for (int i = 0; i < R; i++)
            {
                int p = c * R + i; double x = C0[3 * p], y = C0[3 * p + 1], z = C0[3 * p + 2];
                bool pinned = i < pins;
                Pin[p] = (byte)(pinned ? 1 : 0);
                _k[p] = G / Math.Max(_arcFree[p], MinArc);
                double dr = SdfAt(Sdf, x, y, z);
                Sdf0[p] = dr;
                _clr[p] = Math.Min(Clearance, dr);
                _fly[p] = (byte)(!pinned && y > ear && dr > FlyClear ? 1 : 0);
                _onHead[p] = !pinned && y > ear ? Math.Max(dr, 1e-4) : 0;
                _boxD0[p] = BoxDepth(FaceBox, x, y, z).Depth;
            }
        }
        X.Set(C0, 3 * n); Xp.Set(C0, 3 * n); Hang.Set(C0, 3 * n);
    }

    /// <summary>Every row at its target, at rest.</summary>
    public void Reset(F32 targets)
    {
        X.Set(targets, 3 * N); Xp.Set(targets, 3 * N);
        _Tp.Set(targets, 3 * N); _tpOk = true;
        Hang.Set(targets, 3 * N);
    }

    /// <summary>Carry every simulated row and its previous position by the affine m (world → world).</summary>
    public void Carry(double[] m)
    {
        foreach (var A in new[] { X, Xp, _Tp })
        {
            for (int o = 0; o < A.Length; o += 3)
            {
                double x = A[o], y = A[o + 1], z = A[o + 2];
                A[o] = m[0] * x + m[4] * y + m[8] * z + m[12];
                A[o + 1] = m[1] * x + m[5] * y + m[9] * z + m[13];
                A[o + 2] = m[2] * x + m[6] * y + m[10] * z + m[14];
            }
        }
    }

    public void Step(double dt, StrandFrame frame, StrandParams p)
    {
        var T = frame.Targets; int n = N;
        if (!_tpOk) { _Tp.Set(T, 3 * n); _tpOk = true; }
        double damp = p.Damping, dt2 = dt * dt, ks = p.Stiffness, kb = p.Bend; bool flySoft = p.FlySoft;
        if (flySoft && _flyKey != p.FlyArc)
        {
            _flyKey = p.FlyArc;
            for (int q = 0; q < n; q++) _kFly[q] = G / Math.Max(_arcFree[q], p.FlyArc);
        }
        for (int q = 0; q < n; q++)
        {
            int i = q % R, o = 3 * q;
            _L1[q] = i > 0 ? StrandMath.Hypot(T[o] - T[o - 3], T[o + 1] - T[o - 2], T[o + 2] - T[o - 1]) : 0;
            _L2[q] = i > 1 ? StrandMath.Hypot(T[o] - T[o - 6], T[o + 1] - T[o - 5], T[o + 2] - T[o - 4]) : 0;
        }
        var H = Hang;
        Colliders(frame, p);
        Gravity(frame, p);
        for (int q = 0; q < n; q++)
        {
            int o = 3 * q;
            if (Pin[q] != 0)
            {
                X[o] = Xp[o] = T[o]; X[o + 1] = Xp[o + 1] = T[o + 1]; X[o + 2] = Xp[o + 2] = T[o + 2];
                continue;
            }
            double kk = (flySoft && _fly[q] != 0 ? _kFly[q] : _k[q]) * ks * dt2;
            for (int d = 0; d < 3; d++)
            {
                double xo = X[o + d], vr = T[o + d] - _Tp[o + d];
                double nx = xo + (xo - Xp[o + d] - vr) * (1 - damp) + vr - kk * (xo - _Tp[o + d] - (H[o + d] - T[o + d]));
                Xp[o + d] = xo; X[o + d] = nx;
            }
        }
        bool grad = p.RootDeg > 0;
        if (grad) Limits(p);
        for (int it = 0; it < p.Iterations; it++)
        {
            for (int c = 0; c < n; c += R)
            {
                for (int i = 1; i < R; i++)
                {
                    Dist(c + i - 1, c + i, _L1[c + i], 1);
                    if (i > 1)
                    {
                        double s = grad && !(flySoft && _fly[c + i] != 0) ? _kb2[c + i] : kb;
                        if (s > 0) Dist(c + i - 2, c + i, _L2[c + i], s);
                    }
                }
            }
        }
        if (grad) AngleLimit(H, flySoft);
        Collide();
        if (p.Tether) Tether(H, p, StrandMath.LinearScale(frame.Head));
        ClampLengths();
        _Tp.Set(T, 3 * n);
    }

    private void Gravity(StrandFrame frame, StrandParams p)
    {
        var H = Hang; var T = frame.Targets; int n = N;
        var fm = frame.Follow is { } fo && fo.Count == _nb ? fo : null;
        int nb = fm is not null ? _nb : 1;
        for (int b = 0; b < nb; b++)
        {
            var m = fm is not null ? fm[b] : frame.Head;
            double x = -m[4], y = -m[5], z = -m[6], l = StrandMath.Or1(StrandMath.Hypot(x, y, z));
            _downs[3 * b] = x / l; _downs[3 * b + 1] = y / l; _downs[3 * b + 2] = z / l;
        }
        double ks = p.Stiffness > 1e-3 ? p.Stiffness : 1e-3;
        double share = 1, @base = 0; bool run = true;
        for (int q = 0; q < n; q++)
        {
            int o = 3 * q, i0 = q % R;
            if (i0 == 0) { @base = 0; run = true; share = 1; }
            H[o] = T[o]; H[o + 1] = T[o + 1]; H[o + 2] = T[o + 2];
            if (Pin[q] != 0) @base = _arcFree[q];
            else if (run && _onHead[q] > 0 && _onHead[q] < p.HeadClr) @base = _arcFree[q];
            else run = false;
            double reach = Pin[q] != 0 ? 0 : (_arcFree[q] - @base) / ks;
            if (reach > 0)
            {
                double dx = 0, dy = 0, dz = 0;
                if (fm is not null)
                {
                    for (int b = 0; b < nb; b++)
                    {
                        double w = _fw[q * nb + b];
                        if (w == 0 || double.IsNaN(w)) continue;
                        dx += w * _downs[3 * b]; dy += w * _downs[3 * b + 1]; dz += w * _downs[3 * b + 2];
                    }
                    double l = StrandMath.Or1(StrandMath.Hypot(dx, dy, dz));
                    dx /= l; dy /= l; dz /= l;
                }
                else { dx = _downs[0]; dy = _downs[1]; dz = _downs[2]; }
                double ww = SmoothShare(-dy);
                dx = -ww * dx; dy = ww * (-1 - dy); dz = -ww * dz;
                if (Math.Abs(dx) >= 1e-6 || Math.Abs(dy) >= 1e-6 || Math.Abs(dz) >= 1e-6)
                {
                    double len = reach * StrandMath.Hypot(dx, dy, dz);
                    if (len >= HangProjectM)
                    {
                        int steps = (int)Math.Min(HangSamples, Math.Ceiling(len / HangSampleM));
                        int k = 1;
                        for (; k <= steps && (double)k / steps <= share; k++)
                        {
                            double s = (reach * k) / steps;
                            H[o] = T[o] + s * dx; H[o + 1] = T[o + 1] + s * dy; H[o + 2] = T[o + 2] + s * dz;
                            if (!ClearOf(q, H)) break;
                        }
                        share = Math.Min(share, (double)(k - 1) / steps);
                    }
                    H[o] = T[o] + reach * dx; H[o + 1] = T[o + 1] + reach * dy; H[o + 2] = T[o + 2] + reach * dz;
                }
            }
            if (i0 != R - 1) continue;
            for (int r = q - (R - 1); r <= q; r++)
            {
                int or = 3 * r; double tx = T[or], ty = T[or + 1], tz = T[or + 2];
                if (H[or] == tx && H[or + 1] == ty && H[or + 2] == tz) continue;
                if (share < 1)
                {
                    H[or] = tx + share * (H[or] - tx); H[or + 1] = ty + share * (H[or + 1] - ty); H[or + 2] = tz + share * (H[or + 2] - tz);
                }
                if (StrandMath.Hypot(H[or] - tx, H[or + 1] - ty, H[or + 2] - tz) >= HangProjectM) PushRow(r, true, 2, H);
            }
        }
    }

    private bool ClearOf(int q, F32 X)
    {
        if (_col is not { } col) return true;
        var inv = col.Inv; var local = col.Local; var fac = col.Fac; int o = 3 * q, nc = local.Length;
        double wx = X[o], wy = X[o + 1], wz = X[o + 2];
        double px = inv[0] * wx + inv[4] * wy + inv[8] * wz + inv[12],
               py = inv[1] * wx + inv[5] * wy + inv[9] * wz + inv[13], pz = inv[2] * wx + inv[6] * wy + inv[10] * wz + inv[14];
        if (SdfAt(Sdf, px, py, pz, _g) < _clr[q] - HangClearTolM) return false;
        for (int c = 0; c < nc; c++)
            if (SegDist(px, py, pz, local[c].A, local[c].B) < local[c].R * fac[q * nc + c] - HangClearTolM) return false;
        return true;
    }

    private void ClampLengths()
    {
        int n = N;
        for (int c = 0; c < n; c += R)
        {
            for (int i = 1; i < R; i++)
            {
                int q = c + i;
                if (Pin[q] != 0) continue;
                int o = 3 * q, b = o - 3; double L = _L1[q] * StretchMax;
                double dx = X[o] - X[b], dy = X[o + 1] - X[b + 1], dz = X[o + 2] - X[b + 2], l = StrandMath.Hypot(dx, dy, dz);
                if (l <= L) continue;
                double s = L / l;
                X[o] = X[b] + dx * s; X[o + 1] = X[b + 1] + dy * s; X[o + 2] = X[b + 2] + dz * s;
                PushRow(q);
                double ex = X[o] - X[b], ey = X[o + 1] - X[b + 1], ez = X[o + 2] - X[b + 2], m = StrandMath.Hypot(ex, ey, ez);
                if (m <= L) continue;
                double t = L / m;
                X[o] = X[b] + ex * t; X[o + 1] = X[b + 1] + ey * t; X[o + 2] = X[b + 2] + ez * t;
                PushRow(q, false, 2);
            }
        }
    }

    /// <summary>&lt;c&gt;rebuild&lt;/c&gt;: the simulated rows in head-bind space (&lt;paramref name="headInv"/&gt; = bind ← world), then
    /// every vertex of the hair primitive into &lt;paramref name="pos"/&gt; / &lt;paramref name="nrm"/&gt; (the rigid ones at rest).</summary>
    public void Rebuild(double[] headInv, float[] pos, float[] nrm)
    {
        var Hb = Binding; var Cl = _Cl; var Fr = _frames; var off = Hb.Off; var noff = Hb.Noff; var m = headInv;
        for (int q = 0; q < X.Length; q += 3)
        {
            double x = X[q], y = X[q + 1], z = X[q + 2];
            Cl[q] = m[0] * x + m[4] * y + m[8] * z + m[12];
            Cl[q + 1] = m[1] * x + m[5] * y + m[9] * z + m[13];
            Cl[q + 2] = m[2] * x + m[6] * y + m[10] * z + m[14];
        }
        foreach (int v in Hb.Rigid)
            for (int d = 0; d < 3; d++) { pos[3 * v + d] = Hb.Pos0[3 * v + d]; nrm[3 * v + d] = Hb.Nrm0[3 * v + d]; }
        for (int c = 0; c < Hb.S; c++)
        {
            int b = c * R * 3;
            FrameAt(Cl, b, Fr, Hb.N00[3 * c], Hb.N00[3 * c + 1], Hb.N00[3 * c + 2]);
            for (int q = Hb.CStart[c]; q < Hb.CStart[c + 1]; q++)
            {
                int v = Hb.CVerts[q], i = Hb.Va[v]; double t = Hb.Vt[v]; int cc = b + 3 * i, f = 9 * i, o = 6 * v;
                for (int d = 0; d < 3; d++)
                {
                    double pv = Cl[cc + d] + off[o] * Fr[f + d] + off[o + 1] * Fr[f + 3 + d] + off[o + 2] * Fr[f + 6 + d];
                    double nv = noff[o] * Fr[f + d] + noff[o + 1] * Fr[f + 3 + d] + noff[o + 2] * Fr[f + 6 + d];
                    if (t != 0)
                    {
                        int c2 = cc + 3, f2 = f + 9, o2 = o + 3;
                        double p2 = Cl[c2 + d] + off[o2] * Fr[f2 + d] + off[o2 + 1] * Fr[f2 + 3 + d] + off[o2 + 2] * Fr[f2 + 6 + d];
                        double n2 = noff[o2] * Fr[f2 + d] + noff[o2 + 1] * Fr[f2 + 3 + d] + noff[o2 + 2] * Fr[f2 + 6 + d];
                        pv += t * (p2 - pv); nv += t * (n2 - nv);
                    }
                    pos[3 * v + d] = (float)pv; nrm[3 * v + d] = (float)nv;
                }
            }
        }
    }

    private void Limits(StrandParams p)
    {
        string key = $"{p.RootDeg.ToString("R", CultureInfo.InvariantCulture)}:{p.RootFrac.ToString("R", CultureInfo.InvariantCulture)}:{p.Bend.ToString("R", CultureInfo.InvariantCulture)}";
        if (key == _limKey) return;
        _limKey = key;
        for (int q = 0; q < N; q++)
        {
            double f = F[q];
            double a = f <= p.RootFrac ? p.RootDeg : p.RootDeg + (180 - p.RootDeg) * (f - p.RootFrac) / (1 - p.RootFrac);
            _cosLim[q] = Math.Cos(Math.Min(180, a) * Math.PI / 180);
            double r = Math.Max(0, 1 - f / 0.5);
            _kb2[q] = p.Bend + (1 - p.Bend) * r * r;
        }
    }

    private void Dist(int a, int b, double L, double stiff)
    {
        int wa = Pin[a] != 0 ? 0 : 1, wb = Pin[b] != 0 ? 0 : 1, w = wa + wb;
        if (w == 0) return;
        int oa = 3 * a, ob = 3 * b;
        double dx = X[ob] - X[oa], dy = X[ob + 1] - X[oa + 1], dz = X[ob + 2] - X[oa + 2];
        double l = StrandMath.Hypot(dx, dy, dz);
        if (l < 1e-9) return;
        double s = stiff * (l - L) / (l * w);
        X[oa] += wa * s * dx; X[oa + 1] += wa * s * dy; X[oa + 2] += wa * s * dz;
        X[ob] -= wb * s * dx; X[ob + 1] -= wb * s * dy; X[ob + 2] -= wb * s * dz;
    }

    private void AngleLimit(F32 T, bool flySoft)
    {
        int n = N;
        for (int c = 0; c < n; c += R)
        {
            double sx = 0, sy = 0, sz = 0;
            for (int i = 1; i < R; i++)
            {
                int q = c + i, o = 3 * q, b = o - 3;
                if (Pin[q] != 0) continue;
                X[o] += sx; X[o + 1] += sy; X[o + 2] += sz;
                if (_cosLim[q] <= -0.999 || (flySoft && _fly[q] != 0)) continue;
                if (!LimitInto(X[b], X[b + 1], X[b + 2], X[o], X[o + 1], X[o + 2],
                        T[o] - T[b], T[o + 1] - T[b + 1], T[o + 2] - T[b + 2], _cosLim[q], out var lx, out var ly, out var lz)) continue;
                sx += lx - X[o]; sy += ly - X[o + 1]; sz += lz - X[o + 2];
                X[o] = lx; X[o + 1] = ly; X[o + 2] = lz;
            }
        }
    }

    /// <summary>Per row and capsule the bind-rule factor (&lt;c&gt;tipBindFactors&lt;/c&gt;), keyed by the capsules' bind objects;
    /// the last two lists are kept (hairSimMath.ts &lt;c&gt;factors&lt;/c&gt;).</summary>
    public F32 Factors(IReadOnlyList<StrandCapsule> caps, IReadOnlyList<double> localR)
    {
        var key = caps.Select(c => c.Bind).ToArray();
        int hit = _capTables.FindIndex(t => t.Key.Length == key.Length && key.Select((b, i) => ReferenceEquals(b, t.Key[i])).All(x => x));
        if (hit >= 0)
        {
            var t = _capTables[hit];
            if (hit > 0) { _capTables.RemoveAt(hit); _capTables.Insert(0, t); }
            return _capFactors = t.Fac;
        }
        int nc = caps.Count; var C0 = Binding.C0; var out_ = new F32(N * nc);
        Array.Fill(out_.A, 1f);
        var withBind = new List<CapsuleNow>(); var slot = new List<int>();
        for (int i = 0; i < nc; i++)
            if (caps[i].Bind is { } bd) { withBind.Add(new CapsuleNow(V(bd.A), V(bd.B), localR[i])); slot.Add(i); }
        if (withBind.Count > 0)
        {
            for (int q = 0; q < N; q++)
            {
                var fq = Collision.TipBindFactors(new V3(C0[3 * q], C0[3 * q + 1], C0[3 * q + 2]), withBind);
                for (int j = 0; j < slot.Count; j++) out_[q * nc + slot[j]] = fq[j];
            }
        }
        _capTables.Insert(0, (key, out_));
        if (_capTables.Count > FactorTablesKept) _capTables.RemoveRange(FactorTablesKept, _capTables.Count - FactorTablesKept);
        _capFactors = out_;
        return out_;
    }

    private static V3 V(double[] a) => new(a[0], a[1], a[2]);

    private sealed record Col(double[] M, double[] Inv, StrandCapsule[] Local, F32 Fac, bool Box);
    private Col? _col;

    private void Colliders(StrandFrame frame, StrandParams p)
    {
        var m = frame.Head; var inv = InvertAffine(m);
        var caps = frame.Capsules ?? Array.Empty<StrandCapsule>();
        var local = caps.Select(c => CapsuleInFrame(c.A, c.B, c.R, inv)).ToArray();
        var fac = caps.Count > 0 ? Factors(caps, local.Select(c => c.R).ToArray()) : _capFactors;
        _col = new Col(m, inv, local, fac, p.FaceBox);
    }

    private void Collide()
    {
        for (int q = 0; q < N; q++) if (Pin[q] == 0) PushRow(q);
    }

    private readonly CollideCapsule[] _scratch = new CollideCapsule[0];

    private void PushRow(int q, bool body = true, int sdfSteps = 1, F32? Xin = null)
    {
        var X_ = Xin ?? X;
        if (_col is not { } col) return;
        var m = col.M; var inv = col.Inv; var local = col.Local; var fac = col.Fac;
        int nc = local.Length; var fb = FaceBox; var d0 = _boxD0;
        int o = 3 * q;
        double lx, ly, lz, parx, pary, parz;
        {
            double wx = X_[o], wy = X_[o + 1], wz = X_[o + 2];
            lx = inv[0] * wx + inv[4] * wy + inv[8] * wz + inv[12]; ly = inv[1] * wx + inv[5] * wy + inv[9] * wz + inv[13];
            lz = inv[2] * wx + inv[6] * wy + inv[10] * wz + inv[14];
        }
        if (o >= 3)
        {
            double wx = X_[o - 3], wy = X_[o - 2], wz = X_[o - 1];
            parx = inv[0] * wx + inv[4] * wy + inv[8] * wz + inv[12]; pary = inv[1] * wx + inv[5] * wy + inv[9] * wz + inv[13];
            parz = inv[2] * wx + inv[6] * wy + inv[10] * wz + inv[14];
        }
        else { parx = pary = parz = double.NaN; }   // JavaScript: X[-3] is undefined
        double reach = ReferenceEquals(X_, X) ? _L1[q] * StretchMax : double.PositiveInfinity;
        double x = lx, y = ly, z = lz;
        var g = _g;
        void SdfPush()
        {
            double s = SdfAt(Sdf, x, y, z, g);
            if (s >= _clr[q]) return;
            double gl = StrandMath.Hypot(g[0], g[1], g[2]);
            if (gl < 1e-9) return;
            double f = (_clr[q] - s) / gl;
            x += g[0] * f; y += g[1] * f; z += g[2] * f;
        }
        for (int k = 0; k < sdfSteps; k++) SdfPush();
        double hx = x, hy = y, hz = z;
        if (nc > 0 && body)
        {
            bool inside = false;
            var scratch = new CollideCapsule[nc];
            for (int c = 0; c < nc; c++)
            {
                double r = local[c].R * fac[q * nc + c];
                double rr;
                if (SegDist(x, y, z, local[c].A, local[c].B) < r)
                {
                    inside = true;
                    rr = Math.Min(r, SegDist(parx, pary, parz, local[c].A, local[c].B) + reach);
                }
                else rr = r;
                scratch[c] = new CollideCapsule(V(local[c].A), V(local[c].B), rr);
            }
            if (inside)
            {
                var pushed = Collision.PushOutOfCapsules(new V3(x, y, z), scratch, 1);
                x = pushed.X; y = pushed.Y; z = pushed.Z;
            }
        }
        if (col.Box && body)
        {
            var (d, e) = BoxDepth(fb, x, y, z);
            double allowed = e >= 0 && d > d0[q] ? Math.Max(d0[q], BoxDepth(fb, parx, pary, parz).Depth - reach) : d0[q];
            if (e >= 0 && d > allowed)
            {
                double mm = d - allowed;
                if (e == 0) x -= mm; else if (e == 1) x += mm; else y += mm;
            }
        }
        if (x != hx || y != hy || z != hz) SdfPush();
        if (x == lx && y == ly && z == lz) return;
        double dx = x - lx, dy = y - ly, dz = z - lz;
        X_[o] += m[0] * dx + m[4] * dy + m[8] * dz;
        X_[o + 1] += m[1] * dx + m[5] * dy + m[9] * dz;
        X_[o + 2] += m[2] * dx + m[6] * dy + m[10] * dz;
    }

    private void Tether(F32 T, StrandParams p, double scale)
    {
        double r0 = p.TetherR0, r1 = p.TetherR1;
        for (int c = 0; c < N; c += R)
        {
            bool run = p.TetherHead > 0;
            for (int i = 1; i < R; i++)
            {
                int q = c + i;
                if (Pin[q] != 0) continue;
                run = run && _onHead[q] > 0 && _onHead[q] < p.HeadClr;
                if (p.FlySoft && _fly[q] != 0) continue;
                bool upper = F[q] <= 1.0 / 3, head = run;
                if (!upper && !head) continue;
                int o = 3 * q; double tx = T[o], ty = T[o + 1], tz = T[o + 2];
                double dx = X[o] - tx, dy = X[o + 1] - ty, dz = X[o + 2] - tz, d = StrandMath.Hypot(dx, dy, dz);
                double r = Math.Min(upper ? r0 + (r1 - r0) * 3 * F[q] : double.PositiveInfinity, head ? p.TetherHead : double.PositiveInfinity) * scale;
                if (d <= r) continue;
                double s = r / d;
                X[o] = tx + dx * s; X[o + 1] = ty + dy * s; X[o + 2] = tz + dz * s;
                PushRow(q);
            }
        }
    }

    // --- metrics (the spike's measure) -----------------------------------------------------------------------------

    /// <summary>Per row: 1 where its REST position lies inside the box.</summary>
    public byte[] RestInsideBox(IReadOnlyList<double> box)
    {
        var C0 = Binding.C0; var out_ = new byte[N];
        for (int q = 0; q < N; q++) out_[q] = (byte)(InBox(box, C0[3 * q], C0[3 * q + 1], C0[3 * q + 2]) ? 1 : 0);
        return out_;
    }

    /// <summary>Rows inside the eye box now (head-bind space) that were not inside at rest.</summary>
    public int EyePointsEntered(double[] head, IReadOnlyList<double> eyeBox, byte[] restInside)
    {
        var inv = InvertAffine(head); int count = 0;
        for (int q = 0; q < N; q++)
        {
            if (restInside[q] != 0) continue;
            double x = X[3 * q], y = X[3 * q + 1], z = X[3 * q + 2];
            if (InBox(eyeBox, inv[0] * x + inv[4] * y + inv[8] * z + inv[12], inv[1] * x + inv[5] * y + inv[9] * z + inv[13],
                    inv[2] * x + inv[6] * y + inv[10] * z + inv[14])) count++;
        }
        return count;
    }

    /// <summary>The deepest a free row now lies inside the head SDF beyond its own rest depth (mm).</summary>
    public double MaxSdfDepthMm(double[] head)
    {
        var inv = InvertAffine(head); var C0 = Binding.C0; double deep = 0;
        for (int q = 0; q < N; q++)
        {
            if (Pin[q] != 0) continue;
            double x = X[3 * q], y = X[3 * q + 1], z = X[3 * q + 2];
            double now = SdfAt(Sdf, inv[0] * x + inv[4] * y + inv[8] * z + inv[12], inv[1] * x + inv[5] * y + inv[9] * z + inv[13],
                inv[2] * x + inv[6] * y + inv[10] * z + inv[14]);
            double rest = SdfAt(Sdf, C0[3 * q], C0[3 * q + 1], C0[3 * q + 2]);
            deep = Math.Max(deep, Math.Min(0, rest) - now);
        }
        return deep * 1000;
    }
}

/// <summary>
/// How much of the figure root's motion the strands feel (Ruling H-R10, hairSimMath.ts &lt;c&gt;RootInertia&lt;/c&gt;): the felt
/// velocity changes by at most &lt;c&gt;accel&lt;/c&gt;·dt / &lt;c&gt;angAccel&lt;/c&gt;·dt; &lt;see cref="Update"/&gt; returns the rest as this
/// frame's world → world carry (null for the identity).
/// </summary>
public sealed class RootInertia
{
    /// <summary>&lt;c&gt;STRAND_ROOT_LIMITS&lt;/c&gt;: the spike's tuning motions (walk 0.25·π² m/s², sway 15°·π² rad/s²).</summary>
    public static readonly (double Accel, double AngAccel) Limits = (0.25 * Math.PI * Math.PI, (15 * Math.PI / 180) * Math.PI * Math.PI);

    private double[]? _prev;
    private double[] _v = new double[3], _w = new double[3];
    private bool _fresh = true;
    private readonly (double Accel, double AngAccel) _limits;
    public RootInertia() : this(Limits) { }
    public RootInertia((double Accel, double AngAccel) limits) { _limits = limits; }

    public void Reset() { _prev = null; _fresh = true; _v = new double[3]; _w = new double[3]; }

    private static double[] RigidOf(double[] m)
    {
        var out_ = new double[16];
        for (int c = 0; c < 3; c++)
        {
            double l = StrandMath.Or1(StrandMath.Hypot(m[4 * c], m[4 * c + 1], m[4 * c + 2]));
            out_[4 * c] = m[4 * c] / l; out_[4 * c + 1] = m[4 * c + 1] / l; out_[4 * c + 2] = m[4 * c + 2] / l;
        }
        out_[12] = m[12]; out_[13] = m[13]; out_[14] = m[14]; out_[15] = 1;
        return out_;
    }

    private static double[] RotationVector(double[] m)
    {
        double tr = m[0] + m[5] + m[10];
        double angle = Math.Acos(Math.Max(-1, Math.Min(1, (tr - 1) / 2)));
        if (angle < 1e-9) return new double[3];
        double x = m[6] - m[9], y = m[8] - m[2], z = m[1] - m[4];
        double l = StrandMath.Hypot(x, y, z);
        if (l < 1e-6)
        {
            x = Math.Sqrt(Math.Max(0, (m[0] + 1) / 2)); y = Math.Sqrt(Math.Max(0, (m[5] + 1) / 2));
            z = Math.Sqrt(Math.Max(0, (m[10] + 1) / 2));
            static double SignOr(double s, double v) { double r = Math.Sign(s) * v; return r == 0 || double.IsNaN(r) ? v : r; }
            if (x >= y && x >= z) { y = SignOr(m[1] + m[4], y); z = SignOr(m[2] + m[8], z); }
            else if (y >= z) { x = SignOr(m[1] + m[4], x); z = SignOr(m[6] + m[9], z); }
            else { x = SignOr(m[2] + m[8], x); y = SignOr(m[6] + m[9], y); }
            double k = StrandMath.Or1(StrandMath.Hypot(x, y, z));
            return new[] { x / k * angle, y / k * angle, z / k * angle };
        }
        return new[] { x / l * angle, y / l * angle, z / l * angle };
    }

    private static double[] RigidFrom(double[] w, double[] t)
    {
        double a = StrandMath.Hypot(w[0], w[1], w[2]);
        var out_ = new[] { 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, t[0], t[1], t[2], 1.0 };
        if (a < 1e-12) return out_;
        double x = w[0] / a, y = w[1] / a, z = w[2] / a, c = Math.Cos(a), s = Math.Sin(a), k = 1 - c;
        out_[0] = c + x * x * k; out_[1] = y * x * k + z * s; out_[2] = z * x * k - y * s;
        out_[4] = x * y * k - z * s; out_[5] = c + y * y * k; out_[6] = z * y * k + x * s;
        out_[8] = x * z * k + y * s; out_[9] = y * z * k - x * s; out_[10] = c + z * z * k;
        return out_;
    }

    private static double[] RigidInverse(double[] m)
    {
        var out_ = new[] { m[0], m[4], m[8], 0, m[1], m[5], m[9], 0, m[2], m[6], m[10], 0, 0, 0, 0, 1.0 };
        out_[12] = -(out_[0] * m[12] + out_[4] * m[13] + out_[8] * m[14]);
        out_[13] = -(out_[1] * m[12] + out_[5] * m[13] + out_[9] * m[14]);
        out_[14] = -(out_[2] * m[12] + out_[6] * m[13] + out_[10] * m[14]);
        return out_;
    }

    private static double[] ClampTowards(double[] cur, double[] want, double max)
    {
        double dx = want[0] - cur[0], dy = want[1] - cur[1], dz = want[2] - cur[2], l = StrandMath.Hypot(dx, dy, dz);
        double s = l > max ? max / l : 1;
        return new[] { cur[0] + dx * s, cur[1] + dy * s, cur[2] + dz * s };
    }

    public double[]? Update(double[] root, double dt)
    {
        var now = RigidOf(root);
        var prev = _prev;
        _prev = now;
        if (prev is null || !(dt > 0)) return null;
        var local = StrandMath.Mul(RigidInverse(prev), now);
        var rv = RotationVector(local);
        var vReal = new[] { local[12] / dt, local[13] / dt, local[14] / dt };
        var wReal = new[] { rv[0] / dt, rv[1] / dt, rv[2] / dt };
        if (_fresh) { _fresh = false; _v = vReal; }
        else _v = ClampTowards(_v, vReal, _limits.Accel * dt);
        _w = ClampTowards(_w, wReal, _limits.AngAccel * dt);
        var felt = RigidFrom(new[] { _w[0] * dt, _w[1] * dt, _w[2] * dt }, new[] { _v[0] * dt, _v[1] * dt, _v[2] * dt });
        return StrandMath.Mul(StrandMath.Mul(now, RigidInverse(felt)), RigidInverse(prev));
    }
}

/// <summary>One full-tier figure with a strand record (hairSimMath.ts &lt;c&gt;StrandCandidate&lt;/c&gt;).</summary>
public readonly record struct StrandCandidate(string Name, double Distance, double CostMs, bool Running);

/// <summary>The figure budget (spec § 6.2.2; hairSimMath.ts &lt;c&gt;pickStrandFigures&lt;/c&gt;, strandBudget.ts).</summary>
public static class StrandBudget
{
    /// <summary>&lt;c&gt;STRAND_LIMITS&lt;/c&gt;.</summary>
    public static readonly (int MaxFigures, double CutoffM, double LeaveM, double BudgetMs) Limits = (2, 8, 9, 8);

    /// <summary>&lt;c&gt;pickStrandFigures&lt;/c&gt;: nearest first (ties by name, ordinal); the nearest in range always, the next
    /// only while the cost sum stays ≤ budget and the count ≤ max; the first that does not fit ends the list.</summary>
    public static HashSet<string> Pick(IEnumerable<StrandCandidate> c, (int MaxFigures, double CutoffM, double LeaveM, double BudgetMs)? limits = null)
    {
        var lim = limits ?? Limits;
        var inRange = c.Where(x => x.Distance <= (x.Running ? lim.LeaveM : lim.CutoffM))
            .OrderBy(x => x.Distance).ThenBy(x => x.Name, StringComparer.Ordinal).ToList();
        var out_ = new HashSet<string>();
        double sum = 0;
        foreach (var x in inRange)
        {
            if (out_.Count > 0 && (out_.Count + 1 > lim.MaxFigures || sum + x.CostMs > lim.BudgetMs)) break;
            out_.Add(x.Name);
            sum += x.CostMs;
        }
        return out_;
    }

    /// <summary>strandBudget.ts &lt;c&gt;strandCandidates&lt;/c&gt;: full tier, a bound record, not the first-person body.</summary>
    public static List<StrandCandidate> Candidates(IEnumerable<(string Name, V3 Position, bool Full, bool HasRecord, bool FirstPerson, double CostMs, bool Running)> figures, V3 camera)
    {
        var out_ = new List<StrandCandidate>();
        foreach (var f in figures)
        {
            if (!f.Full || !f.HasRecord || f.FirstPerson) continue;
            out_.Add(new StrandCandidate(f.Name, StrandMath.Hypot(f.Position.X - camera.X, f.Position.Y - camera.Y, f.Position.Z - camera.Z), f.CostMs, f.Running));
        }
        return out_;
    }
}
