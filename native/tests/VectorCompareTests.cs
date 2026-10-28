using System;
using System.Collections.Generic;
using System.IO;
using System.Text.Json.Nodes;
using AnimaNative.Tests.Vectors;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>
/// The loading and comparison rules of format <c>anima-test-vectors/1</c>
/// (shared/test-vectors/README.md), mirroring the JS self-check
/// shared/test-vectors/smoke_vectors_format.mjs group for group ([1]..[10]).
/// The cases are written inline on purpose: this checks the loader, so it must
/// not depend on a vector file the loader reads.
/// </summary>
public class VectorCompareTests
{
    private static bool Near(JsonNode? expect, JsonNode? actual, double eps = VectorFile.DefaultEps)
        => VectorCompare.Near(expect, actual, eps, out _);

    private static JsonNode? J(string json) => JsonNode.Parse(json);

    private static JsonNode N(double d) => JsonValue.Create(d);

    /// <summary>A minimal well-formed file with the given cases (JSON text) and fixtures.</summary>
    private static string FileText(string cases, string? fixtures = null)
        => "{\"format\":\"anima-test-vectors/1\",\"source\":\"inline\","
           + (fixtures is null ? "" : $"\"fixtures\":{fixtures},")
           + $"\"cases\":{cases}}}";

    private const string Good =
        "{\"format\":\"anima-test-vectors/1\",\"source\":\"x\",\"cases\":[{\"label\":\"a\",\"fn\":\"f\",\"args\":[],\"expect\":1}]}";

    private static Dictionary<string, Func<JsonArray, JsonNode?>> Table(params (string, Func<JsonArray, JsonNode?>)[] fns)
    {
        var d = new Dictionary<string, Func<JsonArray, JsonNode?>>();
        foreach (var (name, f) in fns) d[name] = f;
        return d;
    }

    // ---- [1] null -------------------------------------------------------------------------

    [Fact]
    public void NullOnlyEqualsNull()
    {
        Assert.True(Near(null, null), "null == null");
        Assert.False(Near(null, N(0)), "null != 0");
        Assert.False(Near(N(0), null), "0 != null");
        Assert.False(Near(null, JsonValue.Create(false)), "null != false");
        Assert.False(Near(J("{\"a\":null}"), J("{}")), "expected null key missing in actual fails");
        Assert.True(Near(J("{\"a\":null}"), J("{\"a\":null}")), "present null key matches");
    }

    // ---- [2] -0 ---------------------------------------------------------------------------

    [Fact]
    public void NegativeZeroEqualsZero()
    {
        Assert.True(Near(N(0), N(-0.0)), "0 == -0");
        Assert.True(Near(N(-0.0), N(0)), "-0 == 0");
        Assert.True(Near(J("-0"), J("0")), "parsed -0 == parsed 0");
        Assert.True(Near(J("[0]"), J("[-0]")), "inside an array");
    }

    // ---- [3] eps boundary -----------------------------------------------------------------

    [Fact]
    public void EpsBoundary()
    {
        Assert.True(Near(N(1.0), N(1.0 + 5e-10), 1e-9), "1.0 vs 1.0+5e-10 equal at eps 1e-9");
        Assert.False(Near(N(1.0), N(1.0 + 2e-9), 1e-9), "1.0 vs 1.0+2e-9 not equal at eps 1e-9");
        var f = VectorFile.Parse(FileText("[{\"label\":\"a\",\"fn\":\"f\",\"args\":[],\"expect\":1}]"));
        Assert.Equal(1e-9, f.Cases[0].Eps);
    }

    [Fact]
    public void IntegerActualComparesAsDouble()
    {
        // A dispatch adapter may hand back an int/long JsonValue; JsonValue<int>.TryGetValue<double> fails.
        Assert.True(Near(J("4"), JsonValue.Create(4)), "int 4 == 4");
        Assert.True(Near(J("4"), JsonValue.Create(4L)), "long 4 == 4");
        Assert.True(Near(J("2.5"), JsonValue.Create(2.5f)), "float 2.5 == 2.5");
        Assert.False(Near(J("4"), JsonValue.Create("4")), "string \"4\" != 4");
    }

    [Fact]
    public void StringAndBooleanAreStrict()
    {
        Assert.True(Near(J("\"a\""), JsonValue.Create("a")));
        Assert.False(Near(J("\"a\""), JsonValue.Create("A")));
        Assert.True(Near(J("true"), JsonValue.Create(true)));
        Assert.False(Near(J("true"), N(1)));
        Assert.False(Near(J("false"), null));
    }

    // ---- [4] objects ----------------------------------------------------------------------

    [Fact]
    public void ExtraActualKeysIgnored()
    {
        Assert.True(Near(J("{\"a\":1}"), J("{\"a\":1,\"b\":\"extra\"}")), "extra actual keys ignored");
        Assert.True(Near(J("{\"p\":{\"x\":1}}"), J("{\"p\":{\"x\":1,\"y\":9}}")), "nested objects compare only expected keys");
    }

    [Fact]
    public void MissingExpectedKeyFails()
    {
        Assert.False(VectorCompare.Near(J("{\"a\":1,\"b\":2}"), J("{\"a\":1}"), 1e-9, out var diff));
        Assert.Contains(".b", diff);
    }

    [Fact]
    public void ArrayIsNotAnObject()
    {
        Assert.False(Near(J("{\"a\":1}"), J("[1]")));
        Assert.False(Near(J("[1]"), J("{\"0\":1}")));
    }

    // ---- [5] arrays -----------------------------------------------------------------------

    [Fact]
    public void ArrayLengthMismatchFails()
    {
        Assert.False(Near(J("[1,2]"), J("[1,2,3]")), "longer actual fails");
        Assert.False(Near(J("[1,2,3]"), J("[1,2]")), "shorter actual fails");
        Assert.True(Near(J("[0,[1,2]]"), J("[-0,[1,2]]")), "nested arrays elementwise");
        Assert.False(VectorCompare.Near(J("[0,[1,2]]"), J("[0,[1,3]]"), 1e-9, out var diff));
        Assert.Contains("[1][1]", diff);
    }

    // ---- [6] NaN / Infinity in actual -----------------------------------------------------

    [Fact]
    public void NonFiniteActualNeverMatches()
    {
        Assert.False(Near(N(0), N(double.NaN)), "NaN != 0");
        Assert.False(Near(N(1), N(double.NaN), 1e300), "NaN fails even with a huge eps");
        var obj = new JsonObject { ["v"] = double.NaN };
        Assert.False(Near(J("{\"v\":0}"), obj), "NaN inside an object fails");
        Assert.False(Near(N(1e308), N(double.PositiveInfinity), 1e300), "Infinity fails");
        Assert.False(Near(null, N(double.NaN)), "NaN != null");
        Assert.False(VectorCompare.Near(N(0), N(double.NaN), 1e-9, out var diff));
        Assert.Contains("NaN", diff);
    }

    // ---- [7] load errors ------------------------------------------------------------------

    [Fact]
    public void NaNInExpectationIsFormatError()
    {
        Assert.Throws<VectorFormatException>(() => VectorFile.Parse(Good.Replace("\"expect\":1", "\"expect\":NaN")));
        Assert.Throws<VectorFormatException>(() => VectorFile.Parse(Good.Replace("\"expect\":1", "\"expect\":Infinity")));
        // JSON allows 1e400; it parses to Infinity, which the format forbids everywhere.
        Assert.Throws<VectorFormatException>(() => VectorFile.Parse(Good.Replace("\"expect\":1", "\"expect\":1e400")));
        Assert.Throws<VectorFormatException>(() => VectorFile.Parse(Good.Replace("\"expect\":1", "\"expect\":{\"a\":[-1e400]}")));
    }

    [Fact]
    public void NonFiniteNumberInArgsOrFixturesIsFormatError()
    {
        Assert.Throws<VectorFormatException>(() => VectorFile.Parse(Good.Replace("\"args\":[]", "\"args\":[-1e400]")));
        Assert.Throws<VectorFormatException>(() => VectorFile.Parse(FileText(
            "[{\"label\":\"a\",\"fn\":\"f\",\"args\":[],\"expect\":1}]", "{\"P\":{\"x\":1e400}}")));
    }

    [Fact]
    public void WellFormedFileLoadsAndAbsentFileThrows()
    {
        var dir = Path.Combine(Path.GetTempPath(), "anima-vectors-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(dir);
        try
        {
            var good = Path.Combine(dir, "good.json");
            File.WriteAllText(good, Good);
            var f = VectorFile.LoadPath(good);
            Assert.Equal("x", f.Source);
            Assert.Single(f.Cases);
            Assert.Equal("a", f.Cases[0].Label);
            Assert.Equal("f", f.Cases[0].Fn);
            Assert.Throws<VectorFormatException>(() => VectorFile.LoadPath(Path.Combine(dir, "absent.json")));
        }
        finally { Directory.Delete(dir, true); }
    }

    [Fact]
    public void BadFileNameIsRejected()
    {
        Assert.Throws<VectorFormatException>(() => VectorFile.Load("../bench_math"));
        Assert.Throws<VectorFormatException>(() => VectorFile.Load("Bench_Math"));
        Assert.Throws<VectorFormatException>(() => VectorFile.Load("nope_no_such_file"));
    }

    [Fact]
    public void WrongTopLevelIsFormatError()
    {
        Assert.Throws<VectorFormatException>(() => VectorFile.Parse(Good.Replace("anima-test-vectors/1", "anima-test-vectors/2")));
        Assert.Throws<VectorFormatException>(() => VectorFile.Parse(Good.Replace("\"source\":\"x\",", "")));
        Assert.Throws<VectorFormatException>(() => VectorFile.Parse(Good.Replace("\"source\":\"x\"", "\"source\":\"\"")));
        Assert.Throws<VectorFormatException>(() => VectorFile.Parse(FileText("[]")));
        Assert.Throws<VectorFormatException>(() => VectorFile.Parse(FileText("[{\"label\":\"a\",\"fn\":\"f\",\"args\":[],\"expect\":1}]", "[]")));
        Assert.Throws<VectorFormatException>(() => VectorFile.Parse("[]"));
        Assert.Throws<VectorFormatException>(() => VectorFile.Parse("{"));
        Assert.Throws<VectorFormatException>(() => VectorFile.Parse(Good.Replace("\"args\":[]", "\"args\":[1,]")));
    }

    [Theory]
    [InlineData("label")]
    [InlineData("fn")]
    [InlineData("args")]
    [InlineData("expect")]
    public void MissingCaseFieldIsFormatError(string key)
    {
        var c = new JsonObject { ["label"] = "a", ["fn"] = "f", ["args"] = new JsonArray(), ["expect"] = 1 };
        c.Remove(key);
        Assert.Throws<VectorFormatException>(() => VectorFile.Parse(FileText(new JsonArray(c).ToJsonString())));
    }

    [Fact]
    public void BadCaseFieldsAreFormatErrors()
    {
        Assert.Throws<VectorFormatException>(() => VectorFile.Parse(FileText("[{\"label\":\"\",\"fn\":\"f\",\"args\":[],\"expect\":1}]")));
        Assert.Throws<VectorFormatException>(() => VectorFile.Parse(FileText("[{\"label\":\"a\",\"fn\":7,\"args\":[],\"expect\":1}]")));
        Assert.Throws<VectorFormatException>(() => VectorFile.Parse(FileText("[{\"label\":\"a\",\"fn\":\"f\",\"args\":{},\"expect\":1}]")));
        Assert.Throws<VectorFormatException>(() => VectorFile.Parse(FileText("[{\"label\":\"a\",\"fn\":\"f\",\"args\":[],\"expect\":1,\"eps\":-1}]")));
        Assert.Throws<VectorFormatException>(() => VectorFile.Parse(FileText("[{\"label\":\"a\",\"fn\":\"f\",\"args\":[],\"expect\":1,\"eps\":\"1e-9\"}]")));
        Assert.Throws<VectorFormatException>(() => VectorFile.Parse(FileText("[{\"label\":\"a\",\"fn\":\"f\",\"args\":[],\"expect\":1,\"eps\":null}]")));
        Assert.Throws<VectorFormatException>(() => VectorFile.Parse(FileText("[7]")));
    }

    [Fact]
    public void NullExpectationIsValid()
    {
        var f = VectorFile.Parse(FileText("[{\"label\":\"a\",\"fn\":\"f\",\"args\":[],\"expect\":null}]"));
        Assert.Null(f.Cases[0].Expect);
        Assert.Null(f.Check(f.Cases[0], Table(("f", _ => null))));
        Assert.NotNull(f.Check(f.Cases[0], Table(("f", _ => JsonValue.Create(0)))));
    }

    [Fact]
    public void UnknownFixtureIsFormatError()
    {
        Assert.Throws<VectorFormatException>(() => VectorFile.Parse(FileText(
            "[{\"label\":\"a\",\"fn\":\"f\",\"args\":[{\"$fixture\":\"NOPE\"}],\"expect\":1}]")));
        // ... at any depth inside args
        Assert.Throws<VectorFormatException>(() => VectorFile.Parse(FileText(
            "[{\"label\":\"a\",\"fn\":\"f\",\"args\":[{\"k\":[{\"$fixture\":\"NOPE\"}]}],\"expect\":1}]", "{\"P\":1}")));
    }

    [Fact]
    public void DuplicateLabelIsFormatError()
    {
        Assert.Throws<VectorFormatException>(() => VectorFile.Parse(FileText(
            "[{\"label\":\"a\",\"fn\":\"f\",\"args\":[],\"expect\":1},{\"label\":\"a\",\"fn\":\"f\",\"args\":[],\"expect\":2}]")));
    }

    [Fact]
    public void DuplicateJsonKeyIsFormatError()
    {
        // JSON.parse keeps the last value; System.Text.Json throws on access. Either way
        // a duplicate key is a mistake in a hand-written file, so the C# loader rejects it.
        Assert.Throws<VectorFormatException>(() => VectorFile.Parse(Good.Replace("\"expect\":1", "\"expect\":1,\"expect\":2")));
    }

    // ---- [8] $fixture / $with -------------------------------------------------------------

    [Fact]
    public void FixtureWithOverride()
    {
        var fixtures = J("{\"P\":{\"a\":1,\"b\":{\"c\":2}},\"L\":[1,2]}")!.AsObject();
        var r = VectorFile.ResolveArgs(J("[{\"$fixture\":\"P\",\"$with\":{\"b\":{\"d\":3},\"e\":4}},7]")!.AsArray(), fixtures);
        var p = r[0]!.AsObject();
        Assert.True(Near(J("1"), p["a"]) && Near(J("4"), p["e"]), "$with adds/keeps top-level keys");
        Assert.True(Near(J("{\"d\":3}"), p["b"]), "$with replaces a nested object whole");
        Assert.False(p["b"]!.AsObject().ContainsKey("c"), "... shallow: no merge into the nested object");
        Assert.True(Near(J("7"), r[1]), "plain args pass through");
        Assert.True(Near(J("2"), fixtures["P"]!["b"]!["c"]) && !fixtures["P"]!.AsObject().ContainsKey("e"),
            "fixture itself is not mutated");
    }

    [Fact]
    public void ResolvedFixtureIsACopy()
    {
        var fixtures = J("{\"L\":[1,2]}")!.AsObject();
        var plain = VectorFile.ResolveArgs(J("[{\"$fixture\":\"L\"}]")!.AsArray(), fixtures);
        plain[0]!.AsArray().Add(99);
        Assert.Equal(2, fixtures["L"]!.AsArray().Count);

        // Through a loaded file: a dispatch fn mutating its input cannot leak into the next case.
        var f = VectorFile.Parse(FileText(
            "[{\"label\":\"a\",\"fn\":\"push\",\"args\":[{\"$fixture\":\"L\"}],\"expect\":3},"
            + "{\"label\":\"b\",\"fn\":\"push\",\"args\":[{\"$fixture\":\"L\"}],\"expect\":3}]", "{\"L\":[1,2]}"));
        var table = Table(("push", a => { var l = a[0]!.AsArray(); l.Add(9); return JsonValue.Create(l.Count); }));
        Assert.Null(f.Check(f.Cases[0], table));
        Assert.Null(f.Check(f.Cases[1], table));
    }

    [Fact]
    public void FixtureNestedInsideArgsResolves()
    {
        var fixtures = J("{\"L\":[1,2]}")!.AsObject();
        Assert.True(Near(J("[[[1,2]]]"), VectorFile.ResolveArgs(J("[[{\"$fixture\":\"L\"}]]")!.AsArray(), fixtures)));
        Assert.True(Near(J("[{\"k\":[1,2]}]"), VectorFile.ResolveArgs(J("[{\"k\":{\"$fixture\":\"L\"}}]")!.AsArray(), fixtures)));
    }

    [Fact]
    public void BadFixtureReferencesThrow()
    {
        var fixtures = J("{\"L\":[1,2],\"P\":{\"a\":1}}")!.AsObject();
        Assert.Throws<VectorFormatException>(() => VectorFile.ResolveArgs(J("[{\"$fixture\":\"L\",\"$with\":{\"a\":1}}]")!.AsArray(), fixtures));
        Assert.Throws<VectorFormatException>(() => VectorFile.ResolveArgs(J("[{\"$fixture\":\"P\",\"$with\":[1]}]")!.AsArray(), fixtures));
        Assert.Throws<VectorFormatException>(() => VectorFile.ResolveArgs(J("[{\"$fixture\":\"P\",\"x\":1}]")!.AsArray(), fixtures));
        Assert.Throws<VectorFormatException>(() => VectorFile.ResolveArgs(J("[{\"$fixture\":7}]")!.AsArray(), fixtures));
        // ... and the same in a file is a load error
        Assert.Throws<VectorFormatException>(() => VectorFile.Parse(FileText(
            "[{\"label\":\"a\",\"fn\":\"f\",\"args\":[{\"$fixture\":\"L\",\"$with\":{\"a\":1}}],\"expect\":1}]", "{\"L\":[1,2]}")));
    }

    [Fact]
    public void ArgumentSentinelsDecodeAfterFixtureCopyAndShallowOverride()
    {
        var f = VectorFile.Parse(FileText(
            """[{"label":"sentinels","fn":"f","args":["$NaN","$Infinity","$-Infinity","$undefined",null,{"nested":["$NaN"]},{"$fixture":"P","$with":{"v":"$undefined"}},"x$NaN","$Inf","$Infinity suffix"," $undefined"],"expect":"$NaN"}]""",
            """{"P":{"v":1,"nested":["$Infinity"]}}"""));
        var a = f.ResolveArgs(f.Cases[0]);
        Assert.True(double.IsNaN(VectorCompare.Num(a[0])));
        Assert.Equal(double.PositiveInfinity, VectorCompare.Num(a[1]));
        Assert.Equal(double.NegativeInfinity, VectorCompare.Num(a[2]));
        Assert.NotNull(a[3]);
        Assert.Equal(System.Text.Json.JsonValueKind.Undefined, a[3]!.GetValue<System.Text.Json.JsonElement>().ValueKind);
        Assert.Null(a[4]);
        Assert.True(double.IsNaN(VectorCompare.Num(a[5]!["nested"]![0])));
        Assert.Equal(double.PositiveInfinity, VectorCompare.Num(a[6]!["nested"]![0]));
        Assert.Equal(System.Text.Json.JsonValueKind.Undefined, a[6]!["v"]!.GetValue<System.Text.Json.JsonElement>().ValueKind);
        Assert.Equal("$Infinity", f.Fixtures["P"]!["nested"]![0]!.GetValue<string>());
        Assert.Equal(1, f.Fixtures["P"]!["v"]!.GetValue<int>());
        Assert.Equal("$NaN", f.Cases[0].Expect!.GetValue<string>());
        Assert.Equal("x$NaN", a[7]!.GetValue<string>());
        Assert.Equal("$Inf", a[8]!.GetValue<string>());
        Assert.Equal("$Infinity suffix", a[9]!.GetValue<string>());
        Assert.Equal(" $undefined", a[10]!.GetValue<string>());
        Assert.Null(f.Check(f.Cases[0], Table(("f", args =>
            JsonValue.Create(double.IsNaN(VectorCompare.Num(args[0])) ? "$NaN" : "bad")))));
    }

    // ---- [9] unknown fn -------------------------------------------------------------------

    [Fact]
    public void UnknownFunctionFails()
    {
        var f = VectorFile.Parse(FileText(
            "[{\"label\":\"known\",\"fn\":\"f\",\"args\":[],\"expect\":1},"
            + "{\"label\":\"unknown case\",\"fn\":\"g\",\"args\":[],\"expect\":1}]"));
        var table = Table(("f", _ => JsonValue.Create(1)));
        Assert.Null(f.Check(f.Cases[0], table));
        var msg = f.Check(f.Cases[1], table);
        Assert.NotNull(msg);
        Assert.Contains("unknown case", msg);
        Assert.Contains("\"g\"", msg);
        var ex = Assert.ThrowsAny<Exception>(() => f.AssertCase("unknown case", table));
        Assert.Contains("unknown case", ex.Message);
        Assert.Equal(new[] { "g" }, f.MissingFunctions(table));
    }

    [Fact]
    public void UnknownLabelFails()
    {
        var f = VectorFile.Parse(Good);
        Assert.ThrowsAny<Exception>(() => f.AssertCase("no such label", Table(("f", _ => JsonValue.Create(1)))));
    }

    // ---- [10] $throws ---------------------------------------------------------------------

    [Fact]
    public void ThrowsExpectation()
    {
        Func<JsonArray, JsonNode?> boom = _ => throw new InvalidOperationException("boom");
        var t = VectorFile.Parse(FileText("[{\"label\":\"t\",\"fn\":\"f\",\"args\":[],\"expect\":{\"$throws\":true}}]"));
        Assert.True(t.Cases[0].ExpectsThrow);
        Assert.Null(t.Check(t.Cases[0], Table(("f", boom))));                         // throwing call passes
        Assert.NotNull(t.Check(t.Cases[0], Table(("f", _ => JsonValue.Create(1))))); // returning call fails
        var v = VectorFile.Parse(FileText("[{\"label\":\"t\",\"fn\":\"f\",\"args\":[],\"expect\":1}]"));
        var msg = v.Check(v.Cases[0], Table(("f", boom)));                           // unexpected throw fails
        Assert.NotNull(msg);
        Assert.Contains("boom", msg);
    }

    [Fact]
    public void MalformedThrowsIsFormatError()
    {
        Assert.Throws<VectorFormatException>(() => VectorFile.Parse(FileText(
            "[{\"label\":\"t\",\"fn\":\"f\",\"args\":[],\"expect\":{\"$throws\":false}}]")));
        Assert.Throws<VectorFormatException>(() => VectorFile.Parse(FileText(
            "[{\"label\":\"t\",\"fn\":\"f\",\"args\":[],\"expect\":{\"$throws\":true,\"x\":1}}]")));
    }

    [Fact]
    public void NaNResultFailsTheCase()
    {
        var f = VectorFile.Parse(FileText("[{\"label\":\"t\",\"fn\":\"nan\",\"args\":[],\"expect\":0}]"));
        Assert.NotNull(f.Check(f.Cases[0], Table(("nan", _ => JsonValue.Create(double.NaN)))));
    }

    [Fact]
    public void ArgsArePassedAndEpsZeroAllowed()
    {
        var f = VectorFile.Parse(FileText("[{\"label\":\"e\",\"fn\":\"f\",\"args\":[[1,2],3],\"expect\":6,\"eps\":0}]"));
        Assert.Equal(0, f.Cases[0].Eps);
        var table = Table(("f", a => JsonValue.Create(a[0]!.AsArray().Count * VectorCompare.Num(a[1]))));
        Assert.Null(f.Check(f.Cases[0], table));
    }
}
