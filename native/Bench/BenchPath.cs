using System;
using System.IO;
using System.Linq;
using System.Text.Json;

namespace AnimaNative.Bench;

/// <summary>One keyframe of the bench drive: anchor-relative metres, y up.</summary>
public sealed record PathKey(double T, double[] Pos, double[] Target);

/// <summary>
/// <c>shared/bench/camera_path_v1.json</c> — THE camera drive of both clients.
/// Port of <c>client3d/src/bench/benchPath.ts</c> (<c>loadPath</c> with the same
/// validation, <c>samplePath</c> piecewise linear with clamping at both ends).
/// The file is embedded into the assembly from the repository (csproj
/// <c>EmbeddedResource</c>, logical name <see cref="ResourceName"/>), so the
/// browser bundle and this binary read the same bytes.
/// </summary>
public sealed record CameraPath(int Version, string Space, double Duration, double Warmup, PathKey[] Keyframes)
{
    public const string ResourceName = "AnimaNative.Bench.camera_path_v1.json";
    public const string RepoPath = "shared/bench/camera_path_v1.json";
    public const string SpaceV1 = "anchor-relative metres, y up";

    /// <summary>The embedded <c>camera_path_v1.json</c>, validated.</summary>
    public static CameraPath LoadEmbedded()
    {
        using var stream = typeof(CameraPath).Assembly.GetManifestResourceStream(ResourceName)
                           ?? throw new InvalidOperationException($"embedded resource {ResourceName} missing");
        using var doc = JsonDocument.Parse(stream);
        return Load(doc.RootElement);
    }

    /// <summary>The raw bytes of the embedded file (for the check).</summary>
    public static byte[] EmbeddedBytes()
    {
        using var stream = typeof(CameraPath).Assembly.GetManifestResourceStream(ResourceName)
                           ?? throw new InvalidOperationException($"embedded resource {ResourceName} missing");
        using var ms = new MemoryStream();
        stream.CopyTo(ms);
        return ms.ToArray();
    }

    /// <summary>
    /// <c>loadPath</c>: version exactly the number 1, the v1 space string,
    /// finite duration &gt; 0, finite warmup ≥ 0, ≥ 2 keyframes with finite
    /// <c>t</c> strictly increasing, 3-vectors of finite numbers, first
    /// <c>t</c> = 0 and last <c>t</c> = duration. Anything else throws
    /// "Invalid camera path v1".
    /// </summary>
    public static CameraPath Load(JsonElement p)
    {
        static Exception Invalid() => new InvalidDataException("Invalid camera path v1");
        static bool Finite(JsonElement e, out double v)
        {
            v = 0;
            return e.ValueKind == JsonValueKind.Number && e.TryGetDouble(out v) && double.IsFinite(v);
        }
        static double[]? Vector(JsonElement o, string name)
        {
            if (!o.TryGetProperty(name, out var a) || a.ValueKind != JsonValueKind.Array || a.GetArrayLength() != 3)
                return null;
            var r = new double[3];
            int i = 0;
            foreach (var x in a.EnumerateArray())
            {
                if (!Finite(x, out r[i])) return null;
                i++;
            }
            return r;
        }

        if (p.ValueKind != JsonValueKind.Object) throw Invalid();
        if (!p.TryGetProperty("version", out var ver) || !Finite(ver, out var version) || version != 1) throw Invalid();
        if (!p.TryGetProperty("space", out var sp) || sp.ValueKind != JsonValueKind.String || sp.GetString() != SpaceV1)
            throw Invalid();
        if (!p.TryGetProperty("duration", out var du) || !Finite(du, out var duration) || duration <= 0) throw Invalid();
        if (!p.TryGetProperty("warmup", out var wu) || !Finite(wu, out var warmup) || warmup < 0) throw Invalid();
        if (!p.TryGetProperty("keyframes", out var kf) || kf.ValueKind != JsonValueKind.Array || kf.GetArrayLength() < 2)
            throw Invalid();
        var keys = new PathKey[kf.GetArrayLength()];
        int n = 0;
        foreach (var k in kf.EnumerateArray())
        {
            if (k.ValueKind != JsonValueKind.Object) throw Invalid();
            if (!k.TryGetProperty("t", out var te) || !Finite(te, out var t)) throw Invalid();
            var pos = Vector(k, "pos") ?? throw Invalid();
            var target = Vector(k, "target") ?? throw Invalid();
            if (n > 0 && t <= keys[n - 1].T) throw Invalid();
            keys[n++] = new PathKey(t, pos, target);
        }
        if (keys[0].T != 0 || keys[^1].T != duration) throw Invalid();
        return new CameraPath(1, SpaceV1, duration, warmup, keys);
    }

    /// <summary>
    /// <c>samplePath</c>: the keyframes before the first / after the last are
    /// clamped to them; in between the first keyframe with <c>t ≥ time</c> and
    /// its predecessor are interpolated linearly (pos and target alike).
    /// </summary>
    public (double[] Pos, double[] Target) Sample(double t)
    {
        if (!double.IsFinite(t)) throw new ArgumentException("Path time must be finite");
        var keys = Keyframes;
        var end = keys[^1];
        if (t <= keys[0].T) return ((double[])keys[0].Pos.Clone(), (double[])keys[0].Target.Clone());
        if (t >= end.T) return ((double[])end.Pos.Clone(), (double[])end.Target.Clone());
        int hi = Array.FindIndex(keys, k => k.T >= t);
        var a = keys[hi - 1];
        var b = keys[hi];
        double u = (t - a.T) / (b.T - a.T);
        double[] Lerp(double[] x, double[] y) => x.Select((v, i) => v + (y[i] - v) * u).ToArray();
        return (Lerp(a.Pos, b.Pos), Lerp(a.Target, b.Target));
    }
}
