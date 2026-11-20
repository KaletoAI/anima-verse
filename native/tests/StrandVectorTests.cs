using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using AnimaNative.Figures;
using AnimaNative.Tests.Vectors;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>
/// The adapters of scripts/export_strand_vectors.mjs (per-strand hair, stage 4 of the hair port), mirrored for the
/// native port: the fixture builder of scripts/smoke_hair_sim.mjs (the head sphere SDF, the curved fan, straight
/// cards; "[fx] fixture digest" pins that both sides build the same inputs) and one function per smoke case. The
/// clock (&lt;c&gt;strandClock&lt;/c&gt;) runs &lt;see cref="StrandHairDriver"/&gt; where the exporter runs hairSim.ts through three:
/// the rig's joint matrices are &lt;c&gt;boneWorld · inverse(boneBindWorld)&lt;/c&gt; (three's endpoint rule with the mesh on the
/// root: &lt;c&gt;meshWorld · meshWorld⁻¹ · boneWorld · boneInverse · I&lt;/c&gt;), the torso capsule through Spine2's joint.
/// </summary>
internal static class StrandVectorAdapters
{
    private const int R = StrandSim.Rows;
    private static readonly double[] Cc = { 0, 1.60, 0 };
    private const double Rad = 0.09, Rho = 0.092, Ear = 1.5625;
    private static readonly double Alpha0 = 30 * Math.PI / 180, SphereArc = Rho * (Math.PI / 2 - Alpha0);
    private static readonly double[] FaceBoxV = { -0.06, 0.06, 1.48, 1.66, 0.0225 }, EyeBoxV = { -0.04, 0.04, 1.555, 1.645, 0.0225 };
    private const string ParamsJson = "{\"damping\":0.04,\"stiffness\":1.0,\"bend\":0.15,\"iterations\":6,\"root_deg\":10,\"root_frac\":0.2,"
        + "\"fly_soft\":true,\"fly_arc\":0.30,\"tether\":true,\"tether_r0\":0.015,\"tether_r1\":0.06,\"tether_head\":0.012,\"head_clr\":0.03,\"face_box\":true}";
    private const double DT = 1.0 / 60;
    private static readonly CollisionCapsule Torso = new("chest", "mixamorig:Spine2", "mixamorig:Spine2", 0.08, "torso", new V3(0, 1.0, 0), new V3(0, 1.45, 0));
    private static readonly double[] TorsoA = { 0, 1.0, 0 }, TorsoB = { 0, 1.45, 0 };

    private static readonly Lazy<StrandSdfPayload> Sdf = new(() =>
    {
        double[] lo = { -0.15, 1.46, -0.16 }; double vox = 0.0068; int[] dims = { 45, 44, 48 };
        var q = new byte[dims[0] * dims[1] * dims[2]];
        for (int iz = 0; iz < dims[2]; iz++) for (int iy = 0; iy < dims[1]; iy++) for (int ix = 0; ix < dims[0]; ix++)
        {
            double x = lo[0] + ix * vox, y = lo[1] + iy * vox, z = lo[2] + iz * vox;
            double d = StrandMath.Hypot(x - Cc[0], y - Cc[1], z - Cc[2]) - Rad;
            double r = Math.Floor(d * 1000 + 0.5);   // JavaScript Math.round
            q[ix + dims[0] * (iy + dims[1] * iz)] = unchecked((byte)(sbyte)Math.Max(-127, Math.Min(127, r)));
        }
        return new StrandSdfPayload(dims, lo, vox, "x_fastest", "mm_int8", Convert.ToBase64String(q));
    });

    private sealed record Card(double[][] Rows, int Pins, double[] Side);
    internal sealed record Fixture(HairStrandRecord Record, float[] Pos, float[] Nrm, ushort[] CardIds, float[] U);

    private static double[][] CurvedRows(double theta)
    {
        double st = Math.Sin(theta), ct = Math.Cos(theta);
        var rows = new double[R][];
        for (int i = 0; i < R; i++)
        {
            double s = 0.02 * i;
            if (s <= SphereArc)
            {
                double a = Alpha0 + s / Rho;
                rows[i] = new[] { Rho * Math.Sin(a) * st, Cc[1] + Rho * Math.Cos(a), Rho * Math.Sin(a) * ct };
            }
            else rows[i] = new[] { Rho * st, Cc[1] - (s - SphereArc), Rho * ct };
        }
        return rows;
    }

    private static double[][] StraightRows(double x, double z, double y0 = 1.60, double gap = 0.02)
        => Enumerable.Range(0, R).Select(i => new[] { x, y0 - gap * i, z }).ToArray();

    private static Card Curved(double theta) => new(CurvedRows(theta), 3, new[] { Math.Cos(theta), 0, -Math.Sin(theta) });

    private static Fixture BuildFrom(IReadOnlyList<Card> cards, string[]? bones = null, Func<double[], double[]>? followOf = null,
        IReadOnlyList<CollisionCapsule>? capsules = null, JsonElement? parameters = null)
    {
        bones ??= new[] { "mixamorig:Head" };
        followOf ??= _ => new[] { 1.0 };
        var rest = new List<double>(); var pins = new List<double>(); var freeArc = new List<double>(); var freeFrac = new List<double>();
        var w = new List<double>(); var pos = new List<double>(); var nrm = new List<double>(); var card = new List<ushort>(); var u = new List<double>();
        for (int k = 0; k < cards.Count; k++)
        {
            var cd = cards[k];
            pins.Add(cd.Pins);
            var arc = new List<double> { 0 };
            for (int i = 1; i < R; i++)
                arc.Add(arc[i - 1] + StrandMath.Hypot(cd.Rows[i][0] - cd.Rows[i - 1][0], cd.Rows[i][1] - cd.Rows[i - 1][1], cd.Rows[i][2] - cd.Rows[i - 1][2]));
            double last = arc[cd.Pins - 1], total = arc[R - 1] - last;
            for (int i = 0; i < R; i++)
            {
                var p = cd.Rows[i];
                rest.AddRange(p);
                double fa = i < cd.Pins ? 0 : arc[i] - last;
                freeArc.Add(fa); freeFrac.Add(i < cd.Pins ? 0 : fa / total);
                w.AddRange(followOf(p));
                double[] n = { p[0] - Cc[0], p[1] - Cc[1], p[2] - Cc[2] };
                double nl = StrandMath.Hypot(n[0], n[1], n[2]);
                foreach (int sgn in new[] { -1, 1 })
                {
                    pos.Add(p[0] + sgn * 0.004 * cd.Side[0]); pos.Add(p[1] + sgn * 0.004 * cd.Side[1]); pos.Add(p[2] + sgn * 0.004 * cd.Side[2]);
                    nrm.Add(n[0] / nl); nrm.Add(n[1] / nl); nrm.Add(n[2] / nl);
                    card.Add((ushort)(k + 1)); u.Add(i);
                }
            }
        }
        foreach (var (x, z) in new[] { (-0.02, -0.02), (0.02, -0.02), (0.02, 0.02), (-0.02, 0.02) })
        {
            pos.Add(x); pos.Add(1.695); pos.Add(z); nrm.Add(0); nrm.Add(1); nrm.Add(0); card.Add(0); u.Add(0);
        }
        var record = new HairStrandRecord
        {
            Version = 2, ItemId = "hair_fixture", Fsig = "0123456789ab", Mode = "hairdeck", FitSha256 = "0", Frame = "head_bind",
            HeadBone = "mixamorig:Head", Rows = R, Cards = cards.Count, Rest = rest.ToArray(), Pins = pins.ToArray(),
            FreeArc = freeArc.ToArray(), FreeFrac = freeFrac.ToArray(), FollowBones = bones, FollowW = w.ToArray(), EarY = Ear,
            FaceBox = FaceBoxV, EyeBox = EyeBoxV, Sdf = Sdf.Value, Capsules = capsules ?? Array.Empty<CollisionCapsule>(),
            Params = StrandSim.ParamsOf(parameters ?? JsonDocument.Parse(ParamsJson).RootElement),
        };
        return new Fixture(record, pos.Select(x => (float)x).ToArray(), nrm.Select(x => (float)x).ToArray(), card.ToArray(), u.Select(x => (float)x).ToArray());
    }

    /// <summary>A build spec (exporter docstring) → fixture.</summary>
    internal static Fixture Build(JsonNode? specNode)
    {
        var spec = (JsonObject)specNode!;
        var cards = new List<Card>();
        if (spec["fan"] is { } fanN)
        {
            int n = (int)N(fanN);
            for (int k = 0; k < n; k++) cards.Add(Curved((75 + (k + 0.5) * 210 / n) * Math.PI / 180));
        }
        foreach (var c in (JsonArray?)spec["cards"] ?? new JsonArray())
        {
            if (c!["curved"] is { } deg) { cards.Add(Curved(N(deg) * Math.PI / 180)); continue; }
            var s = (JsonArray)c["straight"]!;
            cards.Add(new Card(StraightRows(N(s[0]), N(s[1]), s.Count > 2 ? N(s[2]) : 1.60, s.Count > 3 ? N(s[3]) : 0.02),
                (int)N(c["pins"]), Vec(c["side"])));
        }
        var merged = JsonNode.Parse(ParamsJson)!.AsObject();
        foreach (var (k, v) in (JsonObject?)spec["params"] ?? new JsonObject()) merged[k] = v?.DeepClone();
        var prm = JsonDocument.Parse(merged.ToJsonString()).RootElement;
        bool spine = spec["spine"] is { } sp && sp.GetValue<bool>();
        bool torso = spec["torso"] is { } to && to.GetValue<bool>();
        return BuildFrom(cards, spine ? new[] { "mixamorig:Head", "mixamorig:Spine2" } : null,
            spine ? p => p[1] < 1.52 ? new[] { 0.0, 1 } : new[] { 1.0, 0 } : null,
            torso ? new[] { Torso } : null, prm);
    }

    private static double N(JsonNode? n) => VectorCompare.Num(n);
    private static double[] Vec(JsonNode? n) => ((JsonArray)n!).Select(x => N(x)).ToArray();
    private static double[] Mat(JsonNode? n) => ((JsonArray)n!).Select(x => N(x)).ToArray();
    private static JsonArray Nums(IEnumerable<double> v) => new(v.Select(x => (JsonNode?)x).ToArray());
    private static JsonArray Floats(F32 a) => Nums(a.A.Select(x => (double)x));
    private static JsonArray Floats(float[] a) => Nums(a.Select(x => (double)x));
    private static readonly int[] Sampled = { 4, 10, 16 };
    private static JsonArray SampledRows(F32 X)
    {
        var out_ = new List<double>();
        for (int c = 0; c < X.Length / (3 * R); c++) foreach (int i in Sampled) for (int d = 0; d < 3; d++) out_.Add(X[3 * (c * R + i) + d]);
        return Nums(out_);
    }
    private static JsonArray EverySeventh(float[] A)
    {
        var out_ = new List<double>();
        for (int v = 0; v < A.Length / 3; v += 7) { out_.Add(A[3 * v]); out_.Add(A[3 * v + 1]); out_.Add(A[3 * v + 2]); }
        return Nums(out_);
    }

    internal static StrandSim MakeSim(Fixture fx) => new(StrandSim.Bind(fx.Record, fx.Pos, fx.Nrm, fx.CardIds, fx.U), fx.Record);

    private static StrandFrame FrameOf(HairStrandRecord record, double[] m, IReadOnlyList<StrandCapsule>? capsules = null)
    {
        var targets = new F32(record.Cards * R * 3);
        StrandSim.Targets(record, record.FollowBones.Select(_ => m).ToArray(), targets);
        return new StrandFrame { Targets = targets, Head = m, Capsules = capsules ?? Array.Empty<StrandCapsule>() };
    }

    internal static double[] RootMotion(string kind, double t, double amp, double[]? pivot = null)
    {
        pivot ??= new[] { 0, Ear, 0 };
        double yaw = 0, pitch = 0, ox = 0, oy = 0, oz = 0;
        if (kind == "sway")
        {
            yaw = amp * (15 * Math.PI / 180) * Math.Sin(2 * Math.PI * 0.5 * t);
            pitch = amp * (5 * Math.PI / 180) * Math.Sin(2 * Math.PI * 0.5 * t + Math.PI / 2);
        }
        else if (kind == "walk")
        {
            oz = amp * 0.25 * Math.Sin(2 * Math.PI * 0.5 * t);
            oy = amp * 0.015 * (1 - Math.Cos(2 * Math.PI * 1.0 * t));
        }
        double cy = Math.Cos(yaw), sy = Math.Sin(yaw), cp = Math.Cos(pitch), sp = Math.Sin(pitch);
        double[] Rm = { cy, sy * sp, sy * cp, 0, cp, -sp, -sy, cy * sp, cy * cp };
        var T = Enumerable.Range(0, 3).Select(r => pivot[r] - (Rm[3 * r] * pivot[0] + Rm[3 * r + 1] * pivot[1] + Rm[3 * r + 2] * pivot[2])).ToArray();
        T[0] += ox; T[1] += oy; T[2] += oz;
        return new[] { Rm[0], Rm[3], Rm[6], 0, Rm[1], Rm[4], Rm[7], 0, Rm[2], Rm[5], Rm[8], 0, T[0], T[1], T[2], 1 };
    }

    private static double[] Xf(double[] m, double[] p) => new[] { m[0] * p[0] + m[4] * p[1] + m[8] * p[2] + m[12],
        m[1] * p[0] + m[5] * p[1] + m[9] * p[2] + m[13], m[2] * p[0] + m[6] * p[1] + m[10] * p[2] + m[14] };
    private static StrandCapsule[] TorsoNow(double[] m, StrandBind bind) => new[] { new StrandCapsule(Xf(m, TorsoA), Xf(m, TorsoB), 0.08, bind) };
    private static readonly double[] I16 = { 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1 };

    private static StrandParams Still(StrandParams p) => p with { Iterations = 0, Bend = 0, RootDeg = 0, Tether = false };

    /// <summary>The case's &lt;c&gt;params&lt;/c&gt; override (camelCase StrandParams keys).</summary>
    private static StrandParams Override(StrandParams p, JsonNode? o)
    {
        if (o is not JsonObject obj) return p;
        foreach (var (k, v) in obj)
        {
            double d = v is null ? 0 : N(v);
            bool b = v is JsonValue jv && jv.TryGetValue(out bool bb) ? bb : d != 0;
            p = k switch
            {
                "damping" => p with { Damping = d }, "stiffness" => p with { Stiffness = d }, "bend" => p with { Bend = d },
                "iterations" => p with { Iterations = d }, "rootDeg" => p with { RootDeg = d }, "rootFrac" => p with { RootFrac = d },
                "flySoft" => p with { FlySoft = b }, "flyArc" => p with { FlyArc = d }, "tether" => p with { Tether = b },
                "tetherR0" => p with { TetherR0 = d }, "tetherR1" => p with { TetherR1 = d }, "tetherHead" => p with { TetherHead = d },
                "headClr" => p with { HeadClr = d }, "faceBox" => p with { FaceBox = b },
                _ => throw new ArgumentException("unknown param " + k),
            };
        }
        return p;
    }

    public static JsonNode? Run(JsonNode? spec, JsonNode? runNode)
    {
        var r = (JsonObject)runNode!;
        var fx = Build(spec); var sim = MakeSim(fx);
        var p = Override(fx.Record.Params, r["params"]);
        var bind = new StrandBind(TorsoA, TorsoB);
        string kind = r["kind"]!.GetValue<string>();
        var snaps = ((JsonArray?)r["snapshots"] ?? new JsonArray()).Select(x => (int)N(x)).ToHashSet();
        var full = ((JsonArray?)r["full"] ?? new JsonArray()).Select(x => (int)N(x)).ToHashSet();
        int rebuildAt = r["rebuild"] is { } rb ? (int)N(rb) : -1;
        bool metrics = r["metrics"] is { } me && me.GetValue<bool>();
        var restEye = sim.RestInsideBox(EyeBoxV);
        double amp = 0, deep = 0; int eye = 0;
        sim.Reset(FrameOf(fx.Record, RootMotion(kind, 0, 0)).Targets);
        double seconds = N(r["seconds"]), settle = N(r["settle"]);
        int steps = (int)Math.Round((seconds + settle) / DT, MidpointRounding.AwayFromZero);
        var snapshots = new JsonArray(); JsonObject? rebuild = null;
        for (int s = 0; s < steps; s++)
        {
            double t = s * DT;
            amp += ((t < seconds ? 1 : 0) - amp) * Math.Min(1, DT / 0.5);
            var m = RootMotion(kind, t, amp);
            var f = FrameOf(fx.Record, m, r["capsules"]?.GetValue<string>() == "torso" ? TorsoNow(m, bind) : null);
            sim.Step(DT, f, p);
            if (metrics && s % 6 == 0)
            {
                deep = Math.Max(deep, sim.MaxSdfDepthMm(m));
                eye = Math.Max(eye, sim.EyePointsEntered(m, EyeBoxV, restEye));
            }
            if (snaps.Contains(s)) snapshots.Add(new JsonObject { ["step"] = s, ["X"] = full.Contains(s) ? Floats(sim.X) : SampledRows(sim.X) });
            if (rebuildAt == s)
            {
                var pos = new float[fx.Pos.Length]; var nrm = new float[pos.Length];
                sim.Rebuild(StrandSim.InvertAffine(m), pos, nrm);
                rebuild = new JsonObject { ["pos"] = EverySeventh(pos), ["nrm"] = EverySeventh(nrm) };
            }
        }
        var out_ = new JsonObject { ["snapshots"] = snapshots };
        if (rebuild is not null) out_["rebuild"] = rebuild;
        if (metrics) { out_["deep"] = deep; out_["eye"] = eye; }
        return out_;
    }

    public static JsonNode? Rest1(JsonNode? spec)
    {
        var fx = Build(spec); var sim = MakeSim(fx); var f = FrameOf(fx.Record, I16);
        sim.Reset(f.Targets);
        for (int s = 0; s < 120; s++) sim.Step(DT, f, fx.Record.Params);
        var pos = new float[fx.Pos.Length]; var nrm = new float[fx.Nrm.Length];
        sim.Rebuild(StrandSim.InvertAffine(I16), pos, nrm);
        double dp = 0, dn = 0;
        for (int i = 0; i < pos.Length; i++) { dp = Math.Max(dp, Math.Abs(pos[i] - fx.Pos[i])); dn = Math.Max(dn, Math.Abs(nrm[i] - fx.Nrm[i])); }
        return Nums(new[] { dp, dn });
    }

    private static JsonObject Straight(double[] side) => new() { ["cards"] = new JsonArray(new JsonObject
        { ["straight"] = new JsonArray(0.5, 0), ["pins"] = 2, ["side"] = Nums(side) }) };

    public static JsonNode? Haar6(double rootDeg)
    {
        var fx = Build(Straight(new double[] { 1, 0, 0 })); var sim = MakeSim(fx); var f = FrameOf(fx.Record, I16);
        sim.Reset(f.Targets);
        double c = Math.Cos(Math.PI / 6), s = Math.Sin(Math.PI / 6); double[] p1 = { 0.5, 1.58, 0 };
        for (int i = 2; i < R; i++)
        {
            double dx = sim.X[3 * i] - p1[0], dy = sim.X[3 * i + 1] - p1[1];
            sim.X[3 * i] = p1[0] + c * dx - s * dy; sim.Xp[3 * i] = sim.X[3 * i];
            sim.X[3 * i + 1] = p1[1] + s * dx + c * dy; sim.Xp[3 * i + 1] = sim.X[3 * i + 1];
        }
        sim.Step(0, f, fx.Record.Params with { RootDeg = rootDeg, Bend = 0, Tether = false });
        return Floats(sim.X);
    }

    private static JsonObject Spec7() => (JsonObject)JsonNode.Parse("{\"fan\":60,\"cards\":[{\"straight\":[0,-0.10],\"pins\":2,\"side\":[1,0,0]},"
        + "{\"straight\":[0,-0.095,1.60,0.03],\"pins\":2,\"side\":[1,0,0]}],\"spine\":true,\"torso\":true}")!;

    public static JsonNode? Follow7(bool withCapsule)
    {
        double pitch = 30 * Math.PI / 180, c = Math.Cos(pitch), s = Math.Sin(pitch);
        double[] P = { 1, 0, 0, 0, 0, c, s, 0, 0, -s, c, 0, 0, 1.30 - 1.30 * c, -1.30 * s, 1 };
        var fx = Build(Spec7()); var sim = MakeSim(fx); var prm = fx.Record.Params;
        var T = new F32(fx.Record.Cards * R * 3);
        StrandSim.Targets(fx.Record, new[] { P, P }, T);
        var caps = withCapsule ? TorsoNow(P, new StrandBind(TorsoA, TorsoB)) : Array.Empty<StrandCapsule>();
        sim.Reset(FrameOf(fx.Record, I16).Targets);
        var f = FrameOf(fx.Record, P, caps);
        JsonArray? mid = null;
        for (int st = 0; st < 120; st++)
        {
            sim.Step(DT, f, prm);
            if (st == 29) mid = SampledRows(sim.X);
        }
        return new JsonObject { ["targets"] = SampledRows(T), ["X30"] = mid, ["X"] = Floats(sim.X) };
    }

    public static JsonNode? Clamp9()
    {
        var fx = Build(Straight(new double[] { 0, 0, 1 })); var sim = MakeSim(fx); var f = FrameOf(fx.Record, I16);
        sim.Reset(f.Targets);
        sim.X[27] += 0.10; sim.Xp[27] += 0.10;
        sim.Step(0, f, Still(fx.Record.Params));
        return Floats(sim.X);
    }

    public static JsonNode? Tether10()
    {
        double theta = Math.PI; var rows = CurvedRows(theta);
        var r3 = rows[3]; double rr = StrandMath.Hypot(r3[0] - Cc[0], r3[1] - Cc[1], r3[2] - Cc[2]);
        rows[3] = Enumerable.Range(0, 3).Select(d => Cc[d] + (r3[d] - Cc[d]) * (rr + 0.04) / rr).ToArray();
        var fx = BuildFrom(new[] { new Card(rows, 3, new[] { Math.Cos(theta), 0, -Math.Sin(theta) }) });
        var sim = MakeSim(fx); var f = FrameOf(fx.Record, I16);
        var p = Still(fx.Record.Params) with { Tether = true, TetherR0 = 10, TetherR1 = 10 };
        double Turn(int sign)
        {
            sim.Reset(f.Targets);
            double a = sign * 25 * Math.PI / 180, c = Math.Cos(a), sn = Math.Sin(a);
            double[] p3 = { sim.X[9], sim.X[10], sim.X[11] };
            for (int i = 4; i < R; i++)
            {
                double dy = sim.X[3 * i + 1] - p3[1], dz = sim.X[3 * i + 2] - p3[2];
                sim.X[3 * i + 1] = p3[1] + c * dy - sn * dz; sim.Xp[3 * i + 1] = sim.X[3 * i + 1];
                sim.X[3 * i + 2] = p3[2] + sn * dy + c * dz; sim.Xp[3 * i + 2] = sim.X[3 * i + 2];
            }
            return StrandMath.Hypot(sim.X[18] - Cc[0], sim.X[19] - Cc[1], sim.X[20] - Cc[2]);
        }
        int sign = Turn(1) > Turn(-1) ? 1 : -1;
        Turn(sign);
        var before = Floats(sim.X); var onHead = Floats(sim.OnHead);
        sim.Step(0, f, p);
        return new JsonObject { ["before"] = before, ["onHead"] = onHead, ["X"] = Floats(sim.X) };
    }

    public static JsonNode? Walk11()
    {
        var fx = Build(Straight(new double[] { 0, 0, 1 })); var sim = MakeSim(fx);
        double[] At(double t) => new[] { 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 3.4 * t, 1 };
        sim.Reset(FrameOf(fx.Record, At(0)).Targets);
        var snaps = new JsonArray();
        for (int st = 1; st <= 240; st++)
        {
            sim.Step(DT, FrameOf(fx.Record, At(st * DT)), fx.Record.Params);
            if (st % 60 == 0) snaps.Add(st == 240 ? Floats(sim.X) : SampledRows(sim.X));
        }
        return snaps;
    }

    public static JsonNode? LastWord12()
    {
        var spec = (JsonObject)JsonNode.Parse("{\"cards\":[{\"straight\":[0,-0.095],\"pins\":2,\"side\":[1,0,0]}]}")!;
        var fx = Build(spec); var sim = MakeSim(fx);
        var cap = new StrandCapsule(new[] { 0, 1.56, -0.135 }, new[] { 0, 1.56, -0.135 }, 0.06, new StrandBind(new double[] { 0, 0, 5 }, new double[] { 0, 0, 5 }));
        var f = FrameOf(fx.Record, I16, new[] { cap });
        sim.Reset(f.Targets);
        sim.Step(0, f, Still(fx.Record.Params) with { FaceBox = false });
        return Floats(sim.X);
    }

    public static JsonNode? Inertia13(JsonNode? roots, double dt)
    {
        var ri = new RootInertia();
        return new JsonArray(((JsonArray)roots!).Select(m => ri.Update(Mat(m), dt) is { } c ? (JsonNode?)Nums(c) : null).ToArray());
    }

    public static JsonNode? Carry13e(double[] m)
    {
        var fx = Build(Straight(new double[] { 0, 0, 1 })); var sim = MakeSim(fx);
        sim.Reset(FrameOf(fx.Record, I16).Targets);
        for (int q = 0; q < sim.X.Length; q++) sim.Xp[q] -= 0.001 * (q % 3 == 2 ? 1 : 0);
        sim.Carry(m);
        return new JsonObject { ["X"] = Floats(sim.X), ["Xp"] = Floats(sim.Xp) };
    }

    public static JsonNode? Gravity14(double deg, int steps, bool loose)
    {
        var fx = Build(Straight(new double[] { 1, 0, 0 })); var sim = MakeSim(fx); double[] P = { 0.5, 1.58, 0 }; var prm = fx.Record.Params;
        double a = deg * Math.PI / 180, c = Math.Cos(a), s = Math.Sin(a);
        double[] Mt = { 1, 0, 0, 0, 0, c, s, 0, 0, -s, c, 0, 0, P[1] - (c * P[1] - s * P[2]), P[2] - (s * P[1] + c * P[2]), 1 };
        var p = loose ? prm with { Bend = 0, RootDeg = 0 } : prm;
        var f = FrameOf(fx.Record, Mt);
        if (steps == 1) sim.Reset(f.Targets); else sim.Reset(FrameOf(fx.Record, I16).Targets);
        for (int st = 0; st < steps; st++) sim.Step(DT, f, p);
        return new JsonObject { ["hang"] = Floats(sim.Hang), ["targets"] = Floats(f.Targets), ["X"] = Floats(sim.X) };
    }

    public static JsonNode? Mismatch8(string which)
    {
        var fx = Build(JsonNode.Parse("{\"fan\":60,\"cards\":[{\"straight\":[0,-0.10],\"pins\":2,\"side\":[1,0,0]}]}"));
        if (which == "card")
        {
            var card = (ushort[])fx.CardIds.Clone(); card[0] = 62;
            StrandSim.Bind(fx.Record, fx.Pos, fx.Nrm, card, fx.U);
        }
        else StrandSim.Bind(fx.Record, fx.Pos, fx.Nrm, fx.CardIds, fx.U.Skip(1).ToArray());
        return null;
    }

    public static JsonNode? FixtureDigest(JsonNode? spec)
    {
        var fx = Build(spec);
        var q = StrandSim.DecodeSdf(fx.Record.Sdf).Q;
        double sdfSum = 0, sdfWeighted = 0;
        for (int i = 0; i < q.Length; i++) { sdfSum += q[i]; sdfWeighted += q[i] * (i % 9973); }
        static double Sum(IEnumerable<double> a) { double s = 0; foreach (var v in a) s += v; return s; }
        return new JsonObject
        {
            ["sdfSum"] = sdfSum, ["sdfWeighted"] = sdfWeighted, ["rest"] = Sum(fx.Record.Rest), ["freeArc"] = Sum(fx.Record.FreeArc),
            ["freeFrac"] = Sum(fx.Record.FreeFrac), ["w"] = Sum(fx.Record.FollowW), ["pins"] = Sum(fx.Record.Pins),
            ["pos"] = Sum(fx.Pos.Select(x => (double)x)), ["nrm"] = Sum(fx.Nrm.Select(x => (double)x)), ["card"] = Sum(fx.CardIds.Select(x => (double)x)),
            ["u"] = Sum(fx.U.Select(x => (double)x)), ["cards"] = fx.Record.Cards, ["vertices"] = fx.CardIds.Length,
        };
    }

    public static JsonNode? BindValue(JsonNode? spec)
    {
        var fx = Build(spec); var b = StrandSim.Bind(fx.Record, fx.Pos, fx.Nrm, fx.CardIds, fx.U);
        return new JsonObject
        {
            ["C0"] = Floats(b.C0), ["N00"] = Nums(b.N00), ["vk"] = Nums(b.Vk.Select(x => (double)x)), ["va"] = Nums(b.Va.Select(x => (double)x)),
            ["vt"] = Nums(b.Vt), ["off"] = Nums(b.Off), ["noff"] = Nums(b.Noff), ["cStart"] = Nums(b.CStart.Select(x => (double)x)),
            ["cVerts"] = Nums(b.CVerts.Select(x => (double)x)), ["rigid"] = Nums(b.Rigid.Select(x => (double)x)),
        };
    }

    public static JsonNode? SdfAtPoints(JsonNode? points)
    {
        var sdf = StrandSim.DecodeSdf(Sdf.Value); var g = new F32(3);
        return new JsonArray(((JsonArray)points!).Select(p =>
        {
            var v = Vec(p); double s = StrandSim.SdfAt(sdf, v[0], v[1], v[2], g);
            return (JsonNode?)Nums(new[] { s, g[0], g[1], g[2] });
        }).ToArray());
    }

    public static JsonNode? StrandParamsOf(JsonNode? p)
    {
        var sp = StrandSim.ParamsOf(JsonDocument.Parse(p!.ToJsonString()).RootElement);
        JsonNode? D(double d) => double.IsNaN(d) ? JsonValue.Create("NaN") : JsonValue.Create(d);
        return new JsonObject
        {
            ["damping"] = D(sp.Damping), ["stiffness"] = D(sp.Stiffness), ["bend"] = D(sp.Bend), ["iterations"] = D(sp.Iterations),
            ["rootDeg"] = D(sp.RootDeg), ["rootFrac"] = D(sp.RootFrac), ["flySoft"] = sp.FlySoft, ["flyArc"] = D(sp.FlyArc),
            ["tether"] = sp.Tether, ["tetherR0"] = D(sp.TetherR0), ["tetherR1"] = D(sp.TetherR1), ["tetherHead"] = D(sp.TetherHead),
            ["headClr"] = D(sp.HeadClr), ["faceBox"] = sp.FaceBox,
        };
    }

    public static JsonNode? Pick(JsonNode? cands, JsonNode? limits)
    {
        var list = ((JsonArray)cands!).Select(c => new StrandCandidate(c!["name"]!.GetValue<string>(), N(c["distance"]), N(c["costMs"]), c["running"]!.GetValue<bool>()));
        (int, double, double, double)? lim = limits is JsonObject l ? ((int)N(l["maxFigures"]), N(l["cutoffM"]), N(l["leaveM"]), N(l["budgetMs"])) : null;
        // the admission order: nearest first (ties by name) among the picked
        var picked = StrandBudget.Pick(list, lim);
        var ordered = list.Where(c => picked.Contains(c.Name)).OrderBy(c => c.Distance).ThenBy(c => c.Name, StringComparer.Ordinal);
        return new JsonArray(ordered.Select(c => (JsonNode?)c.Name).ToArray());
    }

    /// <summary>three's &lt;c&gt;Matrix4.compose&lt;/c&gt; with scale 1.</summary>
    private static double[] Compose(double[] p, double[] q)
    {
        double x = q[0], y = q[1], z = q[2], w = q[3];
        double x2 = x + x, y2 = y + y, z2 = z + z;
        double xx = x * x2, xy = x * y2, xz = x * z2, yy = y * y2, yz = y * z2, zz = z * z2, wx = w * x2, wy = w * y2, wz = w * z2;
        return new[] { 1 - (yy + zz), xy + wz, xz - wy, 0, xy - wz, 1 - (xx + zz), yz + wx, 0, xz + wy, yz - wx, 1 - (xx + yy), 0, p[0], p[1], p[2], 1 };
    }

    public static JsonNode? StrandClock(JsonNode? specNode)
    {
        var spec = (JsonObject)specNode!;
        var fx = Build(spec["build"]);
        var sim = MakeSim(fx);
        double[] spinePos = { 0, 1.30, 0 }, headPos = { 0, 0.30, 0 };
        double[] spineQ = { 0, 0, 0, 1 }, headQ = { 0, 0, 0, 1 };
        double[] root = Mat(spec["root0"]);
        double[] SpineWorld() => StrandMath.Mul(root, Compose(spinePos, spineQ));
        double[] HeadWorld() => StrandMath.Mul(SpineWorld(), Compose(headPos, headQ));
        var spineBindInv = StrandSim.InvertAffine(StrandMath.Mul(I16, Compose(spinePos, new double[] { 0, 0, 0, 1 })));
        var headBindInv = StrandSim.InvertAffine(StrandMath.Mul(StrandMath.Mul(I16, Compose(spinePos, new double[] { 0, 0, 0, 1 })), Compose(headPos, new double[] { 0, 0, 0, 1 })));
        // the record's hair capsules without the head region (Ruling H-R7): the torso on Spine2, bind ends = its a_pos / b_pos
        var own = StrandSim.RecordCapsules(fx.Record).Where(c => c.Region != "head").ToList();
        var binds = own.Select(c => new StrandBind(new[] { c.APos!.Value.X, c.APos.Value.Y, c.APos.Value.Z }, new[] { c.BPos!.Value.X, c.BPos.Value.Y, c.BPos.Value.Z })).ToList();
        var driver = new StrandHairDriver(fx.Record, sim, binds);
        StrandPose Pose()
        {
            var head = StrandMath.Mul(HeadWorld(), headBindInv);
            var spine = StrandMath.Mul(SpineWorld(), spineBindInv);
            var follow = fx.Record.FollowBones.Select(b => b == "mixamorig:Head" ? head : spine).ToArray();
            var caps = own.Select(c =>
            {
                var j = c.A == "mixamorig:Head" ? head : spine;
                return (StrandMath.TransformPoint(j, new[] { c.APos!.Value.X, c.APos.Value.Y, c.APos.Value.Z }),
                        StrandMath.TransformPoint(j, new[] { c.BPos!.Value.X, c.BPos.Value.Y, c.BPos.Value.Z }), c.R * StrandMath.LinearScale(j));
            }).ToArray();
            return new StrandPose { Follow = follow, Head = head, Capsules = caps };
        }
        driver.Enable(Pose(), root);
        var record = ((JsonArray)spec["record"]!).Select(x => (int)N(x)).ToHashSet();
        var full = ((JsonArray?)spec["full"] ?? new JsonArray()).Select(x => (int)N(x)).ToHashSet();
        var mesh = ((JsonArray?)spec["mesh"] ?? new JsonArray()).Select(x => (int)N(x)).ToHashSet();
        bool restDev = spec["restDev"] is { } rd && rd.GetValue<bool>();
        var frames = new JsonArray();
        int k = 0;
        foreach (var f in (JsonArray)spec["frames"]!)
        {
            k++;
            if (f!["root"] is { } r) root = Mat(r);
            if (f["spine"] is { } sq) spineQ = Vec(sq);
            if (f["head"] is { } hq) headQ = Vec(hq);
            driver.Update(N(f["dt"]), Pose, root, f["frozen"] is { } fr && fr.GetValue<bool>());
            if (!record.Contains(k)) continue;
            var entry = new JsonObject { ["frame"] = k };
            if (!restDev) entry["X"] = full.Contains(k) ? Floats(sim.X) : SampledRows(sim.X);
            if (mesh.Contains(k)) { entry["pos"] = EverySeventh(driver.Pos); entry["nrm"] = EverySeventh(driver.Nrm); }
            if (restDev)
            {
                double dp = 0, dn = 0;
                for (int i = 0; i < driver.Pos.Length; i++) { dp = Math.Max(dp, Math.Abs(driver.Pos[i] - fx.Pos[i])); dn = Math.Max(dn, Math.Abs(driver.Nrm[i] - fx.Nrm[i])); }
                entry["restDev"] = Nums(new[] { dp, dn });
            }
            frames.Add(entry);
        }
        return new JsonObject { ["capsuleIds"] = new JsonArray(own.Select(c => (JsonNode?)c.Id).ToArray()), ["frames"] = frames };
    }

    public static readonly Dictionary<string, Func<JsonArray, JsonNode?>> Dispatch = new()
    {
        ["strandParams"] = a => StrandParamsOf(a[0]),
        ["limitSegmentAngle"] = a => Nums(StrandSim.LimitSegmentAngle(Vec(a[0]), Vec(a[1]), Vec(a[2]), N(a[3]))),
        ["lerpFrame"] = a => Nums(StrandSim.LerpFrame(Mat(a[0]), Mat(a[1]), N(a[2]), new double[16])),
        ["boxDepth"] = a => { var (d, e) = StrandSim.BoxDepth(Vec(a[0]), N(a[1]), N(a[2]), N(a[3])); return Nums(new[] { d, e }); },
        ["sdfAt"] = a => SdfAtPoints(a[0]),
        ["fixtureDigest"] = a => FixtureDigest(a[0]),
        ["bind"] = a => BindValue(a[0]),
        ["run"] = a => Run(a[0], a[1]),
        ["rest1"] = a => Rest1(a[0]),
        ["haar6"] = a => Haar6(N(a[0])),
        ["follow7"] = a => Follow7(a[0]!.GetValue<bool>()),
        ["clamp9"] = _ => Clamp9(),
        ["tether10"] = _ => Tether10(),
        ["walk11"] = _ => Walk11(),
        ["lastWord12"] = _ => LastWord12(),
        ["inertia13"] = a => Inertia13(a[0], N(a[1])),
        ["carry13e"] = a => Carry13e(Mat(a[0])),
        ["gravity14"] = a => Gravity14(N(a[0]), (int)N(a[1]), a[2]!.GetValue<bool>()),
        ["mismatch8"] = a => Mismatch8(a[0]!.GetValue<string>()),
        ["gravityOff14"] = a =>
        {
            var g = (JsonObject)Gravity14(N(a[0]), 1, false)!;
            var h = (JsonArray)g["hang"]!; var t = (JsonArray)g["targets"]!;
            double off = 0;
            for (int i = 0; i < h.Count; i++) off = Math.Max(off, Math.Abs(N(h[i]) - N(t[i])));
            return off;
        },
        ["pick"] = a => Pick(a[0], a[1]),
        ["strandClock"] = a => StrandClock(a[0]),
    };
}

public class StrandSimVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("strand_sim"));
    public static TheoryData<string> Cases => VectorFile.Labels("strand_sim");

    [Theory]
    [MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, StrandVectorAdapters.Dispatch);

    [Fact]
    public void EveryFunctionIsDispatched() => Assert.Empty(File.Value.MissingFunctions(StrandVectorAdapters.Dispatch));
}

public class StrandClockVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("strand_clock"));
    public static TheoryData<string> Cases => VectorFile.Labels("strand_clock");

    [Theory]
    [MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, StrandVectorAdapters.Dispatch);

    [Fact]
    public void EveryFunctionIsDispatched() => Assert.Empty(File.Value.MissingFunctions(StrandVectorAdapters.Dispatch));
}

/// <summary>The parts of the strand port the vectors cannot hold (object identity, V8's hypot), by hand.</summary>
public class StrandCoreTests
{
    /// <summary>smoke_hair_sim [7b]: the factor tables of the last two capsule lists are kept and handed back as the
    /// same objects; a third list evicts the oldest.</summary>
    [Fact]
    public void FactorTablesFlipWithoutRebuild()
    {
        var fx = StrandVectorAdapters.Build(JsonNode.Parse("{\"fan\":4}"));
        var sim = StrandVectorAdapters.MakeSim(fx);
        var own = new[] { new StrandCapsule(new[] { 0, 1.0, 0 }, new[] { 0, 1.45, 0 }, 0.08, new StrandBind(new[] { 0, 1.0, 0 }, new[] { 0, 1.45, 0 })) };
        var partner = new StrandCapsule(new[] { 0, 1.2, 0.3 }, new[] { 0, 1.4, 0.3 }, 0.05);
        var both = new[] { partner, own[0] };
        var tOwn = sim.Factors(own, new[] { 0.08 }); var tBoth = sim.Factors(both, new[] { 0.05, 0.08 });
        Assert.Same(tOwn, sim.Factors(own, new[] { 0.08 }));
        Assert.Same(tBoth, sim.Factors(both, new[] { 0.05, 0.08 }));
        for (int q = 0; q < sim.N; q++) { Assert.Equal(1.0, tBoth[2 * q]); Assert.Equal(tOwn[q], tBoth[2 * q + 1]); }
        sim.Factors(new[] { partner, partner, own[0] }, new[] { 0.05, 0.05, 0.08 });
        var again = sim.Factors(own, new[] { 0.08 });
        Assert.NotSame(tOwn, again);
        Assert.Equal(tOwn.A, again.A);
    }

    /// <summary>V8's Math.hypot (Kahan sum over the max): values printed by node.</summary>
    [Fact]
    public void HypotIsV8s()
    {
        Assert.Equal(5.0, StrandMath.Hypot(3, 4));
        Assert.Equal(0.0, StrandMath.Hypot(0, 0, 0));
        Assert.Equal(double.PositiveInfinity, StrandMath.Hypot(double.NaN, double.PositiveInfinity, 1));
        Assert.True(double.IsNaN(StrandMath.Hypot(double.NaN, 1, 1)));
        // node -e "console.log(Math.hypot(0.1, 0.2, 0.3))" → 0.37416573867739417
        Assert.Equal(0.37416573867739417, StrandMath.Hypot(0.1, 0.2, 0.3));
    }

    [Fact]
    public void RecordParseReadsTheServedShape()
    {
        var json = "{\"version\":2,\"item_id\":\"h\",\"fsig\":\"f\",\"mode\":\"hairdeck\",\"fit_sha256\":\"abc\",\"frame\":\"head_bind\","
            + "\"head_bone\":\"mixamorig:Head\",\"rows\":17,\"cards\":1,\"rest\":[1,2,3],\"pins\":[2],\"free_arc\":[0],\"free_frac\":[0],"
            + "\"follow\":{\"bones\":[\"mixamorig:Head\"],\"w\":[1]},\"ear_y\":1.5,\"face_box\":[1,2,3,4,5],\"eye_box\":[1,2,3,4,5],"
            + "\"sdf\":{\"dims\":[1,1,1],\"lo\":[0,0,0],\"vox\":0.01,\"order\":\"x_fastest\",\"unit\":\"mm_int8\",\"data\":\"AA==\"},"
            + "\"capsules\":{\"version\":9,\"capsules\":[{\"id\":\"c\",\"a\":\"A\",\"b\":\"B\",\"r\":0.1,\"region\":\"torso\"}]},"
            + "\"params\":{\"damping\":0.04,\"tether\":true},\"vertex_attributes\":{\"card\":\"_STRAND_CARD\",\"u\":\"_STRAND_U\"}}";
        var r = HairStrandRecord.Parse(JsonDocument.Parse(json).RootElement);
        Assert.Equal(2, r.Version);
        Assert.Equal("mixamorig:Head", r.HeadBone);
        Assert.Equal(17, r.Rows);
        Assert.Equal(new[] { 1.0, 2, 3 }, r.Rest);
        Assert.Equal(new[] { "mixamorig:Head" }, r.FollowBones);
        Assert.Equal(new[] { 1, 1, 1 }, r.Sdf.Dims);
        Assert.Single(r.Capsules);
        Assert.Equal(0.04, r.Params.Damping);
        Assert.True(r.Params.Tether);
        Assert.True(double.IsNaN(r.Params.Bend));
        Assert.Equal("_STRAND_U", r.VertexU);
        Assert.Throws<StrandMismatch>(() => HairStrandRecord.Parse(JsonDocument.Parse("[]").RootElement));
    }
}
