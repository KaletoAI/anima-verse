using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json.Nodes;
using AnimaNative.Bench;
using AnimaNative.Tests.Vectors;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>
/// shared/test-vectors/bench_math.json against the C# port <see cref="BenchStats"/>
/// (hand derivations: client3d/scripts/smoke_bench_math.mjs). The dispatch adapters
/// translate between the vector's JSON (the TS shapes, camelCase keys, null) and the
/// C# types; they never reinterpret a value.
/// </summary>
public class BenchMathVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("bench_math"));

    private static readonly Dictionary<string, Func<JsonArray, JsonNode?>> Dispatch = new()
    {
        ["percentile"] = args => JsonValue.Create(BenchStats.Percentile(VectorCompare.NumList(args[0]), VectorCompare.Num(args[1]))),
        ["summarize"] = args => SummaryJson(BenchStats.Summarize(Samples(args[0]))),
    };

    /// <summary>A JSON array of the TS <c>BenchSample</c> shape.</summary>
    private static List<BenchSample> Samples(JsonNode? node)
        => node!.AsArray().Select(n =>
        {
            var o = n!.AsObject();
            return new BenchSample(
                Dt: VectorCompare.Num(o["dt"]),
                CpuMs: VectorCompare.Num(o["cpuMs"]),
                GpuMs: VectorCompare.NumOrNull(o["gpuMs"]),
                Calls: VectorCompare.Num(o["calls"]),
                Tris: VectorCompare.Num(o["tris"]));
        }).ToList();

    /// <summary>The TS <c>BenchSummary</c> shape, key for key.</summary>
    private static JsonObject SummaryJson(BenchSummary s) => new()
    {
        ["frames"] = s.Frames,
        ["seconds"] = s.Seconds,
        ["fpsMean"] = s.FpsMean,
        ["frameMsMedian"] = s.FrameMsMedian,
        ["frameMsP95"] = s.FrameMsP95,
        ["cpuMsMedian"] = s.CpuMsMedian,
        ["cpuMsP95"] = s.CpuMsP95,
        ["gpuMsMedian"] = s.GpuMsMedian,
        ["callsMedian"] = s.CallsMedian,
        ["trisMedian"] = s.TrisMedian,
    };

    public static TheoryData<string> Cases => VectorFile.Labels("bench_math");

    [Theory]
    [MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, Dispatch);

    [Fact]
    public void EveryFunctionIsDispatched()
        => Assert.Empty(File.Value.MissingFunctions(Dispatch));
}
