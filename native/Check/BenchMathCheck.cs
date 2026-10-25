using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using AnimaNative.Bench;
using AnimaNative.World;

namespace AnimaNative.Check;

/// <summary>
/// The bench maths of Task S2 inside <c>--check</c>, with the HAND values of the
/// browser smokes (no recording of current output):
///
///   • path   — client3d/scripts/smoke_bench_path.mjs: 17 keyframes, duration 20,
///              warm-up 3; t = 0.625 halfway between keyframes 0 and 1 →
///              [7.45, 23.6805, 37.9855]; t = 10.625 halfway between keyframes 8
///              and 9 → [−2.5, 7.5195, −12.0355]; target [0, 1.5, 0]; clamping at
///              t = −1 / 21; plus a quarter point (see below); the nine invalid mutations (NaN → JSON null here,
///              which is what <c>JSON.stringify(NaN)</c> writes);
///   • maths  — client3d/scripts/smoke_bench_math.mjs, numbers verbatim;
///   • anchor — client3d/scripts/smoke_bench_anchor.mjs, rows and cases verbatim,
///              height rule h(x, z) = 0.5x − 0.25z.
/// Plus: the embedded path is byte-identical to the repository file.
/// </summary>
public static class BenchMathCheck
{
    public static string Run(FixtureSource source)
    {
        int n = CheckPath(source);
        CheckMath();
        int anchors = CheckAnchor();
        return $"path_keyframes={n} path_mutations_rejected=9 math_cases=17 anchor_cases={anchors}";
    }

    private static int CheckPath(FixtureSource source)
    {
        var embedded = CameraPath.EmbeddedBytes();
        var repoFile = source.Resolve("repo:" + CameraPath.RepoPath);
        Expect("embedded path = repository file", embedded.AsSpan().SequenceEqual(File.ReadAllBytes(repoFile)),
               $"embedded resource differs from {repoFile} — rebuild");

        var path = CameraPath.LoadEmbedded();
        Expect("keyframes", path.Keyframes.Length == 17, $"{path.Keyframes.Length}");
        Expect("duration/warmup", path.Duration == 20 && path.Warmup == 3, $"{path.Duration}/{path.Warmup}");
        NearArr("t=0.625 pos", path.Sample(0.625).Pos, new[] { 7.45, 23.6805, 37.9855 });
        NearArr("t=10.625 pos", path.Sample(10.625).Pos, new[] { -2.5, 7.5195, -12.0355 });
        NearArr("t=10.625 target", path.Sample(10.625).Target, new[] { 0, 1.5, 0 });
        // Not in the browser smoke: a QUARTER point. The midpoints above cannot reject cosine easing
        // (u = 0.5 maps to 0.5 under (1 − cos πu)/2); u = 0.25 between keyframes 0 and 1 can:
        // [0 + 14.9·0.25, 24 − 0.639·0.25, 40 − 4.029·0.25] = [3.725, 23.84025, 38.99275] (cosine: u' = 0.1464…).
        NearArr("t=0.3125 pos (quarter point)", path.Sample(0.3125).Pos, new[] { 3.725, 23.84025, 38.99275 });
        var first = path.Keyframes[0];
        var last = path.Keyframes[16];
        Expect("t=-1 clamps to keyframe 0", path.Sample(-1).Pos.SequenceEqual(first.Pos)
               && path.Sample(-1).Target.SequenceEqual(first.Target), "not clamped");
        Expect("t=21 clamps to keyframe 16", path.Sample(21).Pos.SequenceEqual(last.Pos)
               && path.Sample(21).Target.SequenceEqual(last.Target), "not clamped");
        Throws("non-finite t", () => path.Sample(double.NaN));

        var raw = JsonNode.Parse(embedded)!;
        var mutations = new (string Name, Action<JsonNode> Mutate)[]
        {
            ("version=2", p => p["version"] = 2),
            ("space=world", p => p["space"] = "world"),
            ("duration=0", p => p["duration"] = 0),
            ("warmup=-1", p => p["warmup"] = -1),
            ("keyframes[0].t=1", p => p["keyframes"]![0]!["t"] = 1),
            ("keyframes[1].t=0", p => p["keyframes"]![1]!["t"] = 0),
            ("keyframes[16].t=19", p => p["keyframes"]![16]!["t"] = 19),
            ("keyframes[1].pos=[0,NaN,0]", p => p["keyframes"]![1]!["pos"] = new JsonArray(0, null, 0)),
            ("keyframes=[]", p => p["keyframes"] = new JsonArray()),
        };
        foreach (var (name, mutate) in mutations)
        {
            var copy = raw.DeepClone();
            mutate(copy);
            using var doc = JsonDocument.Parse(copy.ToJsonString());
            Throws($"loadPath rejects {name}", () => CameraPath.Load(doc.RootElement));
        }
        return path.Keyframes.Length;
    }

    private static void CheckMath()
    {
        // [1] percentile
        Near("p50 of 1,2,3,4", BenchStats.Percentile(new double[] { 1, 2, 3, 4 }, 50), 2.5);
        Near("p0", BenchStats.Percentile(new double[] { 1, 2, 3, 4 }, 0), 1);
        Near("p100", BenchStats.Percentile(new double[] { 1, 2, 3, 4 }, 100), 4);
        Near("single sample", BenchStats.Percentile(new double[] { 5 }, 95), 5);
        Near("p95 of 10..40", BenchStats.Percentile(new double[] { 10, 20, 30, 40 }, 95), 38.5);
        Expect("empty percentile", BenchStats.Percentile(Array.Empty<double>(), 50) == 0, "not 0");

        // [2] summarize
        var s4 = new List<BenchSample>
        {
            new(0.01, 2, null, 100, 1000),
            new(0.02, 4, null, 120, 1200),
            new(0.03, 6, null, 110, 1100),
            new(0.04, 8, null, 130, 1300),
        };
        var s = BenchStats.Summarize(s4);
        Expect("frames 4", s.Frames == 4, $"{s.Frames}");
        Near("seconds 0.1", s.Seconds, 0.1);
        Near("fpsMean = frames/seconds = 40", s.FpsMean, 40);
        Near("frameMsMedian 25", s.FrameMsMedian, 25);
        Near("frameMsP95 38.5", s.FrameMsP95, 38.5);
        Near("cpuMs median 5", s.CpuMsMedian, 5);
        Near("cpuMs p95 7.7", s.CpuMsP95, 7.7);
        Expect("gpuMsMedian null when never resolved", s.GpuMsMedian is null, $"{s.GpuMsMedian}");
        Expect("calls / tris medians", Math.Abs(s.CallsMedian - 115) <= 1e-9 && Math.Abs(s.TrisMedian - 1150) <= 1e-9,
               $"{s.CallsMedian} / {s.TrisMedian}");
        var withGpu = BenchStats.Summarize(s4.Select((x, i) => x with { GpuMs = i == 0 ? null : 3 + i }).ToList());
        Expect("gpuMsMedian ignores unresolved frames (median of 4,5,6 = 5)",
               withGpu.GpuMsMedian is double g && Math.Abs(g - 5) <= 1e-9, $"{withGpu.GpuMsMedian}");

        // [3] empty
        var e = BenchStats.Summarize(Array.Empty<BenchSample>());
        Expect("empty summary: zeros/nulls, no NaN",
               e.Frames == 0 && e.Seconds == 0 && e.FpsMean == 0 && e.FrameMsMedian == 0 && e.GpuMsMedian is null
               && new[] { e.Seconds, e.FpsMean, e.FrameMsMedian, e.FrameMsP95, e.CpuMsMedian, e.CpuMsP95,
                          e.CallsMedian, e.TrisMedian }.All(double.IsFinite), $"{e}");
    }

    private static int CheckAnchor()
    {
        var rows = new List<LocationInfo>
        {
            new("harbor", "Old Market", 10, -4, 0),
            new("market", "Harbor Gate", 30, 8, 0),
            new("shed", "", null, 5, 0),             // pos_x undefined
            new("tower", "", 20, 40, 0),             // name null
            new("reef", "Reef", double.NaN, 3, 0),   // non-finite
        };
        var names = new Dictionary<string, string> { ["shed"] = "Fisher Shed", ["tower"] = "Lighthouse" };
        const string hs = "test height";
        int heightCalls = 0;
        AnchorInfo Pick(string? gotoQuery, string? currentId = null)
            => Anchor.Pick(gotoQuery, rows, id => names.TryGetValue(id, out var v) ? v : null, currentId,
                           (x, z) => { heightCalls++; return 0.5 * x - 0.25 * z; }, hs);
        int cases = 0;
        void Is(string what, AnchorInfo got, double x, double y, double z, string? id, string source)
        {
            cases++;
            Expect(what, got.X == x && got.Y == y && got.Z == z && got.LocationId == id && got.Source == source,
                   $"got ({got.X}, {got.Y}, {got.Z}) {got.LocationId ?? "null"} '{got.Source}', "
                   + $"expected ({x}, {y}, {z}) {id ?? "null"} '{source}'");
        }

        Is("goto=MARKET (exact id beats the earlier name)", Pick("MARKET"), 30, 13, 8, "market", hs);
        Is("goto=harbor g (name substring)", Pick("harbor g"), 30, 13, 8, "market", hs);
        Is("goto=old MAR (case-insensitive)", Pick("old MAR"), 10, 6, -4, "harbor", hs);
        Is("goto=light (nameOf fallback)", Pick("light"), 20, 0, 40, "tower", hs);
        foreach (var bad in new[] { "shed", "fisher", "reef", "nowhere" })
        {
            cases++;
            bool threw = false;
            try { Pick(bad); }
            catch (InvalidOperationException ex) when (ex.Message.StartsWith("Bench goto location is unknown or unplaced"))
            { threw = true; }
            Expect($"goto={bad} rejected", threw, "resolved instead of failing");
        }
        Is("no goto, current harbor", Pick(null, "harbor"), 10, 6, -4, "harbor", hs);
        Is("goto='' counts as none", Pick("", "harbor"), 10, 6, -4, "harbor", hs);
        heightCalls = 0;
        Is("no goto, current shed (unplaced) → origin", Pick(null, "shed"), 0, 0, 0, null, "world origin");
        Is("no goto, no current → origin", Pick(null, null), 0, 0, 0, null, "world origin");
        Is("no rows → origin", Anchor.Pick(null, new List<LocationInfo>(), null, null,
                                           (_, _) => { heightCalls++; return 99; }, hs), 0, 0, 0, null, "world origin");
        Expect("origin must not sample the height field", heightCalls == 0, $"{heightCalls} calls");

        // The worldmap wiring: the avatar's current location comes from characters[name == avatar].
        using var map = JsonDocument.Parse(
            """{"avatar":"Ada","characters":[{"name":"Bo","location_id":"market"},{"name":"Ada","location_id":"harbor"}]}""");
        cases++;
        Expect("avatar location from the worldmap", Anchor.AvatarLocation(map.RootElement) == "harbor",
               Anchor.AvatarLocation(map.RootElement) ?? "null");
        using var noAvatar = JsonDocument.Parse("""{"avatar":null,"characters":[{"name":"","location_id":"market"}]}""");
        cases++;
        Expect("no avatar → no current location", Anchor.AvatarLocation(noAvatar.RootElement) is null,
               Anchor.AvatarLocation(noAvatar.RootElement) ?? "null");
        return cases;
    }

    private static void NearArr(string what, double[] got, double[] want)
        => Expect(what, got.Length == want.Length && got.Zip(want).All(p => Math.Abs(p.First - p.Second) < 1e-8),
                  $"got [{string.Join(", ", got)}], expected [{string.Join(", ", want)}]");

    private static void Near(string what, double got, double want)
        => Expect(what, Math.Abs(got - want) <= 1e-9, $"got {got}, expected {want}");

    private static void Throws(string what, Action act)
    {
        bool threw = false;
        try { act(); }
        catch (Exception) { threw = true; }
        Expect(what, threw, "did not throw");
    }

    private static void Expect(string what, bool ok, string detail)
    {
        if (!ok) throw new InvalidOperationException($"{what}: {detail}");
    }
}
